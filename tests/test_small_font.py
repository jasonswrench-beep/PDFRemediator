"""Independent physical-size fixtures, advisory boundaries and read-only proof."""
from __future__ import annotations

import hashlib
from pathlib import Path
import threading

import pikepdf
import pypdfium2 as pdfium
import pytest

from pdf_remediator import small_font


def source_pdf(directory, *, size=8, text='Readable example', prefix='', suffix='',
               matrix='1 0 0 1 40 700', unit=1, rotation=0, forms=(), type3=False, text_state='',
               image=False, annotation=False, width=600):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory/'source.pdf'
    pdf = pikepdf.Pdf.new(); page = pdf.add_blank_page(page_size=(width, 800))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
        Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
    if type3:
        charproc = pdf.make_stream(b'600 0 d0 0 0 500 700 re f')
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type3,
            FontBBox=pikepdf.Array([0, 0, 600, 700]), FontMatrix=pikepdf.Array([.001, 0, 0, .001, 0, 0]),
            CharProcs=pikepdf.Dictionary(A=charproc), Encoding=pikepdf.Dictionary(Differences=pikepdf.Array([65, pikepdf.Name.A])),
            FirstChar=65, LastChar=65, Widths=pikepdf.Array([600]), Resources=pikepdf.Dictionary()))
        text = 'A'
    resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    content = (prefix + f' BT /F1 {size} Tf {text_state} {matrix} Tm ({escaped}) Tj ET ' + suffix).encode('ascii')
    for index, scale in enumerate(forms):
        leaf = pdf.make_stream(content); leaf.Type = pikepdf.Name.XObject; leaf.Subtype = pikepdf.Name.Form
        leaf.FormType = 1; leaf.BBox = pikepdf.Array([0, 0, width, 800])
        leaf.Matrix = pikepdf.Array([scale, 0, 0, scale, 0, 0]); leaf.Resources = resources
        resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary({f'/F{index}': leaf}))
        content = f'q /F{index} Do Q'.encode('ascii')
    if image:
        picture = pdf.make_stream(b'\xff\xff\xff'); picture.Type = pikepdf.Name.XObject
        picture.Subtype = pikepdf.Name.Image; picture.Width = 1; picture.Height = 1
        picture.BitsPerComponent = 8; picture.ColorSpace = pikepdf.Name.DeviceRGB
        resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Image=picture))
        content = b'q 200 0 0 200 10 10 cm /Image Do Q'
    page.Resources = resources; page.Contents = pdf.make_stream(content)
    page.UserUnit = unit; page.Rotate = rotation
    if annotation:
        page.Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Text, Rect=pikepdf.Array([20, 20, 40, 40]), Contents='Unmeasured annotation text'))])
    with path.open('xb') as stream: pdf.save(stream, min_version='1.7', deterministic_id=True)
    pdf.close(); return path


def assess_unchanged(path, **kwargs):
    original = path.read_bytes(); result = small_font.assess(path, **kwargs)
    assert path.read_bytes() == original
    assert result['source_sha256'] == hashlib.sha256(original).hexdigest()
    assert result['policy'] == small_font.POLICY and result['advisory'] is True
    assert result['threshold_pt'] == 9.0 and result['comparison'] == 'strictly-less-than'
    return result


@pytest.mark.parametrize('size,expected', [(8, 'fail'), (9, 'pass'), (9.1, 'pass')])
def test_strict_advisory_boundary_uses_em_points_not_glyph_ink_height(tmp_path, size, expected):
    source = source_pdf(tmp_path, size=size, text='iiii xxxx')
    report = assess_unchanged(source)
    assert report['status'] == expected, report
    assert report['coverage']['complete'] is True
    assert bool(report['findings']) is (size < 9)
    for finding in report['findings']:
        assert finding['nominal_pt'] == pytest.approx(size)
        assert finding['effective_pt'] == pytest.approx(size)
        assert finding['bbox'][3] - finding['bbox'][1] < finding['effective_pt']
        assert finding['sample'] and finding['page'] == 1 and finding['reasons'] == []


@pytest.mark.parametrize('size,prefix,matrix,forms,unit,expected', [
    (16, 'q .5 0 0 .5 0 0 cm', '1 0 0 1 40 700', (), 1, 8),
    (4, 'q 2 0 0 2 0 0 cm', '1 0 0 1 40 300', (), 1, 8),
    (4, '', '2 0 0 2 40 300', (), 1, 8),
    (32, '', '1 0 0 1 40 700', (.5, .5), 1, 8),
    (4, '', '1 0 0 1 40 300', (2,), 1, 8),
    (4, '', '1 0 0 1 40 700', (), 2, 8),
])
def test_complete_character_matrix_includes_text_ctm_nested_forms_and_user_unit(tmp_path, size, prefix, matrix, forms, unit, expected):
    source = source_pdf(tmp_path, size=size, prefix=prefix, suffix='Q' if prefix else '', matrix=matrix, forms=forms, unit=unit)
    report = assess_unchanged(source)
    assert report['status'] == 'fail' and report['findings'], report
    assert not report['uncertain']
    assert all(row['effective_pt'] == pytest.approx(expected) for row in report['findings'])


@pytest.mark.parametrize('rotation,matrix', [(0, '0 1 -1 0 300 300'), (90, '1 0 0 1 40 700'), (180, '1 0 0 1 40 700'), (270, '1 0 0 1 40 700')])
def test_rotation_preserves_physical_em_size(tmp_path, rotation, matrix):
    report = assess_unchanged(source_pdf(tmp_path, rotation=rotation, matrix=matrix))
    assert report['status'] == 'fail', report
    assert all(row['effective_pt'] == pytest.approx(8) and row['rotation'] == rotation for row in report['findings'])


def test_user_unit_enlargement_can_put_nominal_small_type_above_threshold(tmp_path):
    report = assess_unchanged(source_pdf(tmp_path, size=5, unit=2))
    assert report['status'] == 'pass' and report['findings'] == []
    assert report['pages'][0]['min_effective_pt'] == pytest.approx(10)


@pytest.mark.parametrize('kwargs,reason', [
    ({'matrix': '1 .2 0 1 40 400'}, 'anisotropic-or-skewed-text-matrix'),
    ({'text_state': '50 Tz'}, 'anisotropic-or-skewed-text-matrix'),
    ({'matrix': '-1 0 0 1 300 400'}, 'degenerate-or-reflected-text-matrix'),
    ({'unit': 0}, 'invalid-user-unit'),
    ({'type3': True}, 'type3-font'),
    ({'prefix': 'q 40 700 10 10 re W n', 'suffix': 'Q'}, 'clipping-context'),
    ({'text_state': '4 Ts', 'size': 7}, 'superscript-or-subscript-context'),
    ({'prefix': '/Artifact BMC', 'suffix': 'EMC'}, 'artifact-context'),
    ({'prefix': '/Span << /ActualText (Replacement words) >> BDC', 'suffix': 'EMC'}, 'replacement-or-alternative-text'),
])
def test_unsupported_geometry_or_context_is_uncertain_and_never_a_definite_tiny_text_finding(tmp_path, kwargs, reason):
    report = assess_unchanged(source_pdf(tmp_path, **kwargs))
    assert report['status'] == 'needs-review', report
    assert report['findings'] == [] and report['coverage']['complete'] is False
    assert reason in {item for row in report['uncertain'] for item in row['reasons']} or reason in report['pages'][0]['reasons']


@pytest.mark.parametrize('mode', [3, 7])
def test_invisible_and_clipping_only_ocr_like_text_does_not_raise_small_visible_text_warning(tmp_path, mode):
    report = assess_unchanged(source_pdf(tmp_path, text_state=f'{mode} Tr', size=2))
    assert report['findings'] == [] and report['status'] == 'needs-review'
    assert report['coverage']['complete'] is False
    assert report['counts']['invisible_characters'] or report['counts']['characters'] == 0


@pytest.mark.parametrize('kind', ['scan', 'outlined', 'annotation', 'zero-size', 'whitespace'])
def test_absent_or_unmeasured_digital_text_never_becomes_a_clean_small_font_pass(tmp_path, kind):
    kwargs = {'image': True} if kind == 'scan' else {'annotation': True, 'size': 12} if kind == 'annotation' else {'size': 0} if kind == 'zero-size' else {'text': '     ', 'size': 2} if kind == 'whitespace' else {'prefix': 'q 10 10 100 100 re f Q', 'text': ''}
    report = assess_unchanged(source_pdf(tmp_path, **kwargs))
    assert report['status'] in {'needs-review', 'not-applicable'} and report['status'] != 'pass'
    assert report['findings'] == []


def test_a_long_same_object_run_is_grouped_and_does_not_consume_one_record_per_glyph(tmp_path, monkeypatch):
    monkeypatch.setitem(small_font.LIMITS, 'records', 1)
    report = assess_unchanged(source_pdf(tmp_path, text='a' * 1000, width=10000))
    assert report['status'] == 'fail' and len(report['findings']) == 1, report
    assert report['findings'][0]['char_count'] == 1000
    assert len(report['findings'][0]['sample']) == 80
    assert report['coverage']['complete'] is True


@pytest.mark.parametrize('limit,value,reason', [('characters', 10, 'character-limit'), ('records', 1, 'record-limit'), ('pages', 0, 'page-limit'), ('input_bytes', 1, 'input-byte-limit')])
def test_limits_are_visible_and_cannot_earn_clean_coverage(tmp_path, monkeypatch, limit, value, reason):
    monkeypatch.setitem(small_font.LIMITS, limit, value)
    report = assess_unchanged(source_pdf(tmp_path, text='one two three four five six'))
    assert report['coverage']['complete'] is False
    reasons = {report.get('reason'), *report['coverage'].get('reasons', []), *(item for row in report['pages'] for item in row['reasons'])}
    assert reason in reasons
    assert report['status'] != 'pass'


def test_missing_unicode_or_font_matrix_is_uncertain_not_a_below_nine_claim(tmp_path, monkeypatch):
    source = source_pdf(tmp_path)
    monkeypatch.setattr(small_font.raw, 'FPDFText_GetUnicode', lambda *args: 0)
    report = assess_unchanged(source)
    assert report['findings'] == [] and report['uncertain'] and report['status'] == 'needs-review'
    assert all('unknown-unicode-mapping' in item['reasons'] for item in report['uncertain'])
    monkeypatch.setattr(small_font.raw, 'FPDFText_GetMatrix', lambda *args: False)
    report = assess_unchanged(source)
    assert report['findings'] == [] and report['uncertain']
    assert all('unknown-character-matrix' in item['reasons'] for item in report['uncertain'])


def test_cancellation_is_checked_within_each_256_character_block_and_sources_stay_exact(tmp_path, monkeypatch):
    source = source_pdf(tmp_path, text='a' * 1000, width=10000); original = source.read_bytes()
    flag = threading.Event(); actual = small_font.raw.FPDFText_GetUnicode; called = []
    def read(page, index):
        called.append(index)
        if index == 1: flag.set()
        return actual(page, index)
    monkeypatch.setattr(small_font.raw, 'FPDFText_GetUnicode', read)
    with pytest.raises(InterruptedError): small_font.assess(source, cancel=flag)
    assert called and max(called) <= 255 and source.read_bytes() == original


def test_borrowed_contexts_remain_open_and_assessment_never_uses_a_pdf_writer(tmp_path, monkeypatch):
    source = source_pdf(tmp_path)
    def refuse(*args, **kwargs): raise AssertionError('The advisory screen cannot write a PDF')
    monkeypatch.setattr(pikepdf.Pdf, 'save', refuse)
    with pikepdf.open(source) as pdf, pdfium.PdfDocument(str(source)) as document:
        report = assess_unchanged(source, pdf=pdf, document=document)
        assert report['status'] == 'fail'
        assert len(pdf.pages) == len(document) == 1
    assert 'resize' in report['fix_path'] or 'resizing' in report['fix_path']
    assert any('WCAG minimum' in text for text in report['limitations'])


def test_default_pdfium_clip_wrapper_is_distinct_from_an_actual_clipping_path(tmp_path):
    ordinary = source_pdf(tmp_path/'ordinary', size=8)
    clipped = source_pdf(tmp_path/'clipped', size=8, prefix='q 40 700 10 10 re W n', suffix='Q')
    observed = []
    for source in (ordinary, clipped):
        with pdfium.PdfDocument(str(source)) as document:
            page = document[0]; text = page.get_textpage()
            try:
                obj = small_font.raw.FPDFText_GetTextObject(text, 0)
                clip = small_font.raw.FPDFPageObj_GetClipPath(obj)
                assert clip
                observed.append(small_font.raw.FPDFClipPath_CountPaths(clip))
            finally: text.close(); page.close()
    assert observed[0] in {-1, 0} and observed[1] > 0
    measured = assess_unchanged(ordinary); uncertain = assess_unchanged(clipped)
    assert measured['status'] == 'fail' and measured['findings'] and not measured['uncertain']
    assert uncertain['status'] == 'needs-review' and uncertain['uncertain'] and not uncertain['findings']


def test_text_clipping_from_an_earlier_object_keeps_later_visible_type_uncertain(tmp_path):
    source = source_pdf(tmp_path, size=8,
        prefix='BT /F1 10 Tf 7 Tr 1 0 0 1 40 700 Tm (Clip) Tj ET', text_state='0 Tr')
    report = assess_unchanged(source)
    assert report['status'] == 'needs-review' and report['findings'] == []
    assert 'text-clipping-context' in report['pages'][0]['reasons']
    assert report['uncertain'] and all('text-clipping-context' in row['reasons'] for row in report['uncertain'])


@pytest.mark.parametrize('failed_getter', ['missing-handle', 'invalid-count'])
def test_unknown_clip_api_state_cannot_receive_a_clean_measurement(tmp_path, monkeypatch, failed_getter):
    source = source_pdf(tmp_path, size=8)
    if failed_getter == 'missing-handle':
        monkeypatch.setattr(small_font.raw, 'FPDFPageObj_GetClipPath', lambda obj: None)
    else:
        monkeypatch.setattr(small_font.raw, 'FPDFClipPath_CountPaths', lambda clip: -2)
    report = assess_unchanged(source)
    assert report['findings'] == [] and report['status'] == 'needs-review'
    assert report['uncertain'] and all('unknown-text-clip-state' in row['reasons'] for row in report['uncertain'])


@pytest.mark.parametrize('context', ['explicit-clip', 'unproved-preflight'])
def test_no_reference_clip_sentinel_cannot_override_raw_clipping_or_unproved_context(tmp_path, monkeypatch, context):
    kwargs = {'prefix': 'q 40 700 10 10 re W n', 'suffix': 'Q'} if context == 'explicit-clip' else {}
    source = source_pdf(tmp_path, **kwargs)
    monkeypatch.setattr(small_font.raw, 'FPDFClipPath_CountPaths', lambda clip: -1)
    if context == 'unproved-preflight':
        actual = small_font._context
        def unproved(page, cancel):
            reasons, unit, counters = actual(page, cancel)
            return reasons + ['content-context-parse-error'], unit, counters
        monkeypatch.setattr(small_font, '_context', unproved)
    report = assess_unchanged(source)
    assert report['findings'] == [] and report['status'] == 'needs-review'
    assert report['coverage']['complete'] is False and report['uncertain']
    assert all('unknown-text-clip-state' in row['reasons'] for row in report['uncertain'])
