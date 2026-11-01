"""Static widget previews and versioned cache recovery without any browser."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest
from PIL import Image, ImageChops

from pdf_remediator import inspection, pipeline, preview, process, web, workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import file_sha256
from test_form_edits import form_pdf
from test_form_pipeline import form_source, registered_language_fonts, fast_validator, tagged_control
from test_artifact_structure_pipeline import files


def pixels(png):
    with Image.open(png if isinstance(png, Path) else io.BytesIO(png)) as image:
        return image.convert('RGB')


def body_only(path):
    """Deliberately omit widget rendering to detect the old preview defect."""
    with pdfium.PdfDocument(str(path)) as document:
        page = document[0]
        try:
            width, height = page.get_size(); scale = min(1.6, 1800 / max(width, height))
            bitmap = page.render(scale=scale, draw_annots=True, may_draw_forms=False)
            try: return bitmap.to_pil().convert('RGB')
            finally: bitmap.close()
        finally: page.close()


def test_supported_preview_includes_widget_appearances_and_explicit_safe_renderer_evidence(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf'); digest = file_sha256(source)
    png, context = tmp_path / 'preview.png', tmp_path / 'preview.json'
    preview.render(source, digest, 1, png, context)
    rendered, body = pixels(png), body_only(source)
    try:
        assert rendered.size == body.size and ImageChops.difference(rendered, body).getbbox() is not None
    finally: rendered.close(); body.close()
    data = json.loads(context.read_text(encoding='utf-8'))
    assert data['preview_profile'] == preview.PREVIEW_PROFILE
    assert data['form_rendering']['policy'] == inspection.FORM_RENDERING_POLICY == preview.FORM_RENDERING_POLICY
    assert data['form_rendering']['status'] == 'pass'
    assert data['form_rendering']['field_count'] == data['form_rendering']['widget_count'] == 3
    assert data['form_rendering']['javascript_platform'] == 'disabled-null'
    assert data['form_rendering']['xfa_disabled'] is True
    assert data['form_rendering']['document_or_page_actions_invoked'] is False
    assert preview.context_matches(data, digest, 1, file_sha256(png))
    assert file_sha256(source) == digest


def test_a_changed_widget_appearance_changes_the_real_preview_when_page_body_is_identical(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf'); digest = file_sha256(source)
    changed = tmp_path / 'changed-appearance.pdf'
    with pikepdf.open(source) as pdf:
        pdf.Root.AcroForm.Fields[0].AP.N.write(b'q 1 0 0 rg 0 0 120 24 re f Q')
        with changed.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    pictures = []
    for name, path in [('before', source), ('after', changed)]:
        png, context = tmp_path / (name + '.png'), tmp_path / (name + '.json')
        preview.render(path, file_sha256(path), 1, png, context); pictures.append(pixels(png))
    try: assert ImageChops.difference(*pictures).getbbox() is not None
    finally:
        for image in pictures: image.close()
    before_body, after_body = body_only(source), body_only(changed)
    try: assert ImageChops.difference(before_body, after_body).getbbox() is None
    finally: before_body.close(); after_body.close()
    assert file_sha256(source) == digest


def test_action_bearing_forms_publish_no_complete_preview_and_never_initialize_form_events(tmp_path, monkeypatch):
    source = form_pdf(tmp_path / 'source.pdf', hazard='actions'); digest = file_sha256(source)
    calls = []
    def unexpected_initialization(self, *args, **kwargs):
        calls.append(True); raise AssertionError('Unsupported form initialization must never occur')
    monkeypatch.setattr(pdfium.PdfDocument, 'init_forms', unexpected_initialization)
    png, context = tmp_path / 'refused.png', tmp_path / 'refused.json'
    with pytest.raises(ValueError): preview.render(source, digest, 1, png, context)
    assert not calls and not png.exists() and not context.exists() and file_sha256(source) == digest


def application_review(tmp_path):
    source = form_source(tmp_path / 'source')
    app = web.Application(tmp_path / 'application', RuntimeConfig(project_root=tmp_path))
    try:
        report = pipeline.process_file(source, tmp_path / 'result', app.config)
        assert report.get('output'), report.get('error')
        identifier = app.import_bundle(report['bundle_path']); view = app.view(identifier)
        item = view['manual_items'][0]
        workspace.review_item(app.state_path(identifier), item['id'], 'blocked', 'Synthetic preview reviewer',
            '2026-10-27', view['revision'], 'Keep this saved problem observation while preview caches change.')
        view = app.view(identifier)
        return app, identifier, view, report
    except Exception:
        app.close(); raise


def inline_worker(renders):
    def render(command, *args, **kwargs):
        renders.append(list(command))
        preview.render(Path(command[3]), command[command.index('--sha256') + 1],
            int(command[command.index('--page') + 1]), Path(command[command.index('--png') + 1]),
            Path(command[command.index('--context') + 1]))
        return {'status': 'completed'}
    return render


def test_old_preview_cache_is_retained_and_current_profile_renders_without_changing_saved_reviews(tmp_path, fast_validator, monkeypatch):
    app, identifier, view, report = application_review(tmp_path)
    try:
        digest = view['source']['sha256']; original = Path(view['source']['path'])
        legacy = app.root / 'page-cache' / (digest + '-1.png'); legacy_json = legacy.with_suffix('.json')
        legacy.write_bytes(b'Retained historical body-only preview'); legacy_json.write_text('{"legacy":true}', encoding='utf-8')
        protected = {str(path): file_sha256(path) for path in [original, app.state_path(identifier), legacy, legacy_json]}
        bundle = Path(report['bundle_path']); before_bundle = files(bundle)
        renders = []; monkeypatch.setattr(process, 'run', inline_worker(renders))
        first = app.render_page(identifier, 'original', 1)
        assert first.startswith(b'\x89PNG') and len(renders) == 1
        data = app.page_context(identifier, 1)
        assert len(renders) == 1 and data['preview_profile'] == preview.PREVIEW_PROFILE
        cache = app.root / 'page-cache' / (preview.PREVIEW_PROFILE + '-' + digest + '-1.png')
        context = cache.with_suffix('.json'); assert cache.is_file() and context.is_file()
        assert data['form_rendering']['status'] == 'pass' and data['png_sha256'] == file_sha256(cache)
        # An authentic old-profile record is still insufficient, even if its
        # source/page/image bindings and app-session signature match.
        old = json.loads(context.read_text()); old.pop('signature'); old['preview_profile'] = 'historical-body-only-1'
        old['signature'] = hmac.new(app.token.encode(), json.dumps(old, sort_keys=True, ensure_ascii=False).encode(), hashlib.sha256).hexdigest()
        context.write_text(json.dumps(old), encoding='utf-8')
        second = app.render_page(identifier, 'original', 1)
        assert second == first and len(renders) == 2
        assert app.page_context(identifier, 1)['preview_profile'] == preview.PREVIEW_PROFILE
        assert {path: file_sha256(path) for path in protected} == protected and files(bundle) == before_bundle
    finally: app.close()


def test_a_worker_without_current_widget_rendering_evidence_is_not_signed_or_served(tmp_path, fast_validator, monkeypatch):
    app, identifier, view, report = application_review(tmp_path)
    try:
        original = Path(view['source']['path']); state = app.state_path(identifier)
        protected = {str(path): file_sha256(path) for path in [original, state]}; bundle = Path(report['bundle_path']); saved = files(bundle)
        def incomplete_worker(command, *args, **kwargs):
            png = Path(command[command.index('--png') + 1]); context = Path(command[command.index('--context') + 1])
            png.write_bytes(b'Historical incomplete image')
            context.write_text(json.dumps({'source_sha256': view['source']['sha256'], 'page': 1, 'png_sha256': file_sha256(png)}), encoding='utf-8')
            return {'status': 'completed'}
        monkeypatch.setattr(process, 'run', incomplete_worker)
        with pytest.raises(RuntimeError, match='rendering evidence'): app.render_page(identifier, 'original', 1)
        cache = app.root / 'page-cache' / (preview.PREVIEW_PROFILE + '-' + view['source']['sha256'] + '-1.png')
        assert not cache.exists() and not cache.with_suffix('.json').exists()
        assert {path: file_sha256(path) for path in protected} == protected and files(bundle) == saved
    finally: app.close()


@pytest.mark.parametrize('alias', ['png-source', 'context-source', 'same-output'])
def test_preview_outputs_cannot_overwrite_the_source_or_each_other(tmp_path, alias):
    source = form_pdf(tmp_path / 'source.pdf'); digest = file_sha256(source)
    png, context = tmp_path / 'preview.png', tmp_path / 'preview.json'
    if alias == 'png-source': png = source
    elif alias == 'context-source': context = source
    else: context = png
    with pytest.raises(ValueError, match='distinct'): preview.render(source, digest, 1, png, context)
    assert file_sha256(source) == digest
