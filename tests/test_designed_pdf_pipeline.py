"""The designed-PDF repairs inside the whole pipeline, plus the review-adoption path of OCR-derived character maps.

The tagging engine, the OCR reading and the external PDF/UA validator are explicit test stubs (the engine stub hands back a
pre-built tagged file). PDF parsing, structure repair, content linkage, text extraction, rendering and publication are real.
"""
import shutil
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator import cli, engines, ocr_mappings, pipeline
from pdf_remediator.config import RuntimeConfig, load_config

from test_designed_pdf import TEXT, add_page, make_form, new_pdf, pictures, tagged_pdf
from test_pipeline import bundle, fast_validator, input_pdf, run, tagged_control
from test_review_checkpoint import apply_checkpoint, newer_code, prepared_case, rewrite_manifest_member

SPECS = [dict(role='P', mcids=[0], id='stray'), dict(role='P', mcids=[1]), dict(role='P', mcids=[2]),
         dict(role='Figure', mcids=[5], alt='image 33')]


def untagged_copy(tagged, destination):
    with pikepdf.open(tagged) as pdf:
        for key in ('/StructTreeRoot', '/MarkInfo'):
            if key in pdf.Root:
                del pdf.Root[key]
        for page in pdf.pages:
            if '/StructParents' in page.obj:
                del page.obj['/StructParents']
        pdf.save(destination)
    return destination


@pytest.fixture
def engine_case(tmp_path, monkeypatch, fast_validator):
    """An untagged source whose 'engine output' carries every defect the repair step handles."""
    tagged = tagged_pdf(tmp_path / 'engine-made.pdf', SPECS, font_cidset=True)
    (tmp_path / 'input').mkdir()
    source = untagged_copy(tagged, tmp_path / 'input' / 'designed.pdf')
    calls = []

    def fake_tag(input, output, settings=None, workdir=None, cancel=None):
        calls.append(Path(input))
        shutil.copyfile(tagged, output)
        return {'status': 'completed', 'engine': 'explicit-test-stub', 'output': str(output)}

    monkeypatch.setattr(engines, 'tag', fake_tag)
    return source, calls


def process(source, tmp_path, **options):
    return pipeline.process_file(source, tmp_path / 'output', RuntimeConfig(preserve_painting=False, language='en-US', title='Designed test document', **options))


def processor(report, name):
    return next((item for item in report['processors'] if item['name'] == name), None)


def published(report):
    return Path(report['output']['path']) if report.get('output') else None


def cidset_lists(path):
    with pikepdf.open(path) as pdf:
        return sum(1 for obj in pdf.objects if isinstance(obj, pikepdf.Dictionary) and '/CIDSet' in obj)


def test_engine_defects_are_repaired_noted_and_the_pages_stay_identical(engine_case, tmp_path):
    source, calls = engine_case
    report = process(source, tmp_path)
    repair = processor(report, 'tagged-repairs')
    assert repair['status'] == 'pass', repair
    assert repair['dangling_removed'] == 1 and [i['id'] for i in repair['ids_dropped']] == ['stray']
    assert repair['cidset_removed'] == [] and cidset_lists(published(report)) == 1, 'No consent was given, so the font lists stay.'
    assert [(a['description'], a['page']) for a in repair['set_aside']] == [('image 33', 1)]
    item = next(i for i in report['manual_review']['items'] if i['id'] == 'engine-placeholder-description-set-aside')
    assert item['required'] is True and item['status'] == 'pending' and item['page'] == 1 and '"image 33"' in item['detail']
    linkage = next(c for c in report['gate2']['checks'] if c['id'] == 'content-linkage')
    assert linkage['status'] == 'pass' and linkage['evidence']['missing_references'] == 0
    assert report['fidelity']['status'] == 'pass' and report['status'] != 'failed'
    assert pictures(source) == pictures(published(report))
    assert processor(report, 'unshared-forms') is None, 'Nothing was repeated, so no unsharing is reported.'
    assert calls == [source.resolve()]
    assert pipeline.verify_bundle(bundle(report))


def test_the_font_list_removal_happens_only_with_consent_and_is_recorded(engine_case, tmp_path):
    source, _ = engine_case
    report = process(source, tmp_path, remove_cidset=True)
    repair = processor(report, 'tagged-repairs')
    assert repair['status'] == 'pass' and repair['cidset_removed'] == ['/ABCDEF+Sample'] and repair['cidset_lists'] == 1
    assert cidset_lists(published(report)) == 0
    assert report['settings']['remove_cidset'] is True
    assert pictures(source) == pictures(published(report))


def test_repeated_page_parts_are_unshared_before_the_engine_sees_the_file(tmp_path, monkeypatch, fast_validator):
    pdf, font = new_pdf()
    header = make_form(pdf, b'0.8 0.9 1 rg 0 0 300 60 re f 0 g ' + TEXT % b'Header', font=font)
    for number in range(3):
        add_page(pdf, b'q 1 0 0 1 20 200 cm /Hd Do Q ' + TEXT % (b'Page %d' % number), font, {'/Hd': header})
    (tmp_path / 'input').mkdir()
    source = tmp_path / 'input' / 'repeats.pdf'
    pdf.save(source)
    seen = []
    handed_back = tagged_pdf(tmp_path / 'engine-made.pdf', SPECS[:3])

    def fake_tag(input, output, settings=None, workdir=None, cancel=None):
        from pdf_remediator import designed_pdf
        with pikepdf.open(input) as probe:
            seen.append((Path(input), max(designed_pdf._form_uses(probe).values())))
        shutil.copyfile(handed_back, output)
        return {'status': 'completed', 'engine': 'explicit-test-stub', 'output': str(output)}

    monkeypatch.setattr(engines, 'tag', fake_tag)
    report = process(source, tmp_path)
    unshared = processor(report, 'unshared-forms')
    assert unshared['status'] == 'pass' and unshared['forms_unshared'] == 1 and unshared['copies_made'] == 2
    assert unshared['visible_preservation']['status'] == 'pass' and unshared['visible_preservation']['pages_compared'] == 3
    assert len(seen) == 1 and seen[0][0] != source.resolve() and seen[0][1] == 1, 'The engine received the unshared copy.'


def test_a_refused_unsharing_keeps_the_original_for_the_engine(tmp_path, monkeypatch, fast_validator):
    from pdf_remediator import designed_pdf
    pdf, font = new_pdf()
    header = make_form(pdf, TEXT % b'Header', font=font)
    for _ in range(2):
        add_page(pdf, b'/Hd Do', font, {'/Hd': header})
    (tmp_path / 'input').mkdir()
    source = tmp_path / 'input' / 'repeats.pdf'
    pdf.save(source)
    monkeypatch.setattr(designed_pdf, '_fidelity_gate', lambda *args, **kwargs: {'status': 'fail', 'pages_compared': 2, 'policy': 'test'})
    seen = []
    handed_back = tagged_pdf(tmp_path / 'engine-made.pdf', SPECS[:3])

    def fake_tag(input, output, settings=None, workdir=None, cancel=None):
        seen.append(Path(input))
        shutil.copyfile(handed_back, output)
        return {'status': 'completed', 'engine': 'explicit-test-stub', 'output': str(output)}

    monkeypatch.setattr(engines, 'tag', fake_tag)
    report = process(source, tmp_path)
    assert processor(report, 'unshared-forms')['status'] == 'refused'
    assert seen == [source.resolve()]


def test_existing_usable_tags_keep_their_structure_and_only_lose_the_font_lists_on_request(tmp_path, monkeypatch, fast_validator):
    (tmp_path / 'input').mkdir()
    source = tagged_pdf(tmp_path / 'input' / 'tagged.pdf', [dict(role='P', mcids=[0], id='kept'), dict(role='P', mcids=[1]), dict(role='P', mcids=[2])], font_cidset=True)
    monkeypatch.setattr(engines, 'tag', lambda *a, **k: pytest.fail('Usable existing tags must not be sent to the engine'))
    report = process(source, tmp_path, remove_cidset=True)
    assert processor(report, 'engine')['status'] == 'skipped'
    repair = processor(report, 'tagged-repairs')
    assert repair['status'] == 'pass' and repair['ids_dropped'] == [] and repair['dangling_removed'] == 0
    assert cidset_lists(published(report)) == 0
    with pikepdf.open(published(report)) as pdf:
        assert bytes(pdf.Root['/StructTreeRoot']['/K'][0]['/K'][0]['/ID']) == b'kept'
    report = process(source, tmp_path / 'again')
    assert processor(report, 'tagged-repairs') is None and cidset_lists(published(report)) == 1


def test_the_option_is_a_checked_boolean_with_a_matching_command_line_flag():
    assert RuntimeConfig().remove_cidset is False
    assert load_config(remove_cidset=True).remove_cidset is True
    with pytest.raises(ValueError):
        load_config(remove_cidset='yes')
    parser = cli._parser()
    assert parser.parse_args(['fix', 'in.pdf', '-o', 'out', '--remove-cidset']).remove_cidset is True
    assert parser.parse_args(['fix', 'in.pdf', '-o', 'out']).remove_cidset is None


# --- adoption of a review after edits ---------------------------------------------------------------------

def ocr_map_stub(monkeypatch):
    def run_stub(source, destination, settings, workdir, cancel=None):
        shutil.copyfile(source, destination)
        return {'name': 'ocr-mappings', 'status': 'pass', 'fonts': [], 'evidence_words': 300, 'fonts_left_incomplete': [],
                'holdout': {'words_tested': 60, 'words_matching': 60, 'agreement': 1.0}, 'round_trip': {'status': 'pass'},
                'visible_preservation': {'status': 'pass', 'pages_compared': 1}}

    monkeypatch.setattr(ocr_mappings, 'repair_from_ocr', run_stub)


def test_a_review_made_with_ocr_derived_character_maps_can_be_adopted_after_edits(input_pdf, tmp_path, fast_validator, monkeypatch):
    ocr_map_stub(monkeypatch)
    config = RuntimeConfig(repair_ocr_mappings=True)
    previous, sidecar = prepared_case(input_pdf, tmp_path, config)
    assert previous['fidelity']['policy'] == 'ocr-derived-character-mapping'
    assert any(item['id'] == 'ocr-derived-character-maps' for item in previous['manual_review']['items'])
    newer_code(monkeypatch)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar, config)
    assert report['status'] == 'candidate', report.get('error')
    assert report['fidelity']['policy'] == 'ocr-derived-character-mapping' and report['fidelity']['status'] == 'pass'


def test_reviews_made_before_the_option_existed_are_still_adopted_but_a_changed_setting_is_not(input_pdf, tmp_path, fast_validator, monkeypatch):
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    rewrite_manifest_member(previous, 'report.json', lambda value: value['settings'].pop('remove_cidset'))
    newer_code(monkeypatch)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar)
    assert report['status'] == 'candidate', report.get('error')
    other = tmp_path / 'other'
    other.mkdir()
    changed = apply_checkpoint(input_pdf, other, previous, sidecar, RuntimeConfig(remove_cidset=True))
    assert changed['status'] == 'failed' and 'original preparation settings' in changed['error']['message']


def test_an_interactive_form_is_refused_when_font_list_removal_is_requested(tmp_path, monkeypatch, fast_validator):
    from test_form_edits import form_pdf
    (tmp_path / 'input').mkdir()
    source = form_pdf(tmp_path / 'input' / 'form.pdf')
    original = source.read_bytes()
    monkeypatch.setattr(engines, 'tag', lambda *a, **k: pytest.fail('A refused form must never reach the engine'))
    report = pipeline.process_file(source, tmp_path / 'output', RuntimeConfig(remove_cidset=True))
    assert report['status'] == 'needs-manual' and report['error']['type'] == 'UnsupportedDocument'
    assert 'font-list removal off' in report['error']['message'] and report['output'] is None
    assert source.read_bytes() == original
