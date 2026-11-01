"""Keeping an author's own tags, and reading low-resolution scans at a usable size.

* ``cover_unmarked_graphics`` marks a few unmarked pictures and drawings as page decoration so existing tags can stay.
* ``repair_author_tags`` maps browser-style inline types, un-wraps a Figure that only wraps a Figure and gives a visible Link
  its printed words as /Contents.
* ``author_descriptions`` lists real picture descriptions already in a file's tags.
* ``ocr.oversample_plan`` and the OCR command ask for 300 dpi recognition pictures only for low-resolution scans.

Every PDF is built in the test. The tagging engine and the external validator are explicit stubs; PDF parsing, structure
inspection, text extraction, rendering and the all-page fidelity gate are the real implementations.
"""
import shutil
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name
import pypdfium2 as pdfium
import pytest
from PIL import Image

from pdf_remediator import designed_pdf as dp
from pdf_remediator import engines, ocr
from pdf_remediator.inspection import inspect_pdf
from pdf_remediator.pipeline import _check

from test_designed_pdf import TEXT, marked, pictures, tagged_pdf
from test_designed_pdf_pipeline import process, processor, published
from test_pipeline import fast_validator  # noqa: F401  (fixture)

GOOD = [dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2])]
BODY = b''.join(marked(m, b'Para %d' % m) for m in (0, 1, 2))
# Three paragraphs printed at different heights, so a link rectangle can sit over just one of them.
SPREAD = b''.join(b'/P <</MCID %d>> BDC BT /F1 14 Tf 20 %d Td (Para %d) Tj ET EMC ' % (m, 20 + m * 100, m) for m in (0, 1, 2))


def picture(pdf, *, width=2, height=2):
    stream = pikepdf.Stream(pdf, bytes(width * height * 3))
    stream['/Type'], stream['/Subtype'], stream['/Width'], stream['/Height'] = Name.XObject, Name.Image, width, height
    stream['/ColorSpace'], stream['/BitsPerComponent'] = Name.DeviceRGB, 8
    return stream


def with_image(pdf, font):
    return {'/Im1': picture(pdf)}


def statuses(path):
    inspection = inspect_pdf(path)
    return {kind: _check(inspection, kind).get('status') for kind in ('content-linkage', 'content-coverage')}


def operators(path, page=0):
    with pikepdf.open(path) as pdf:
        return [str(op) for _, op in pikepdf.parse_content_stream(pdf.pages[page].obj)]


def cover(tmp_path, source):
    return dp.cover_unmarked_graphics(source, tmp_path / 'covered.pdf')


# --- cover_unmarked_graphics -----------------------------------------------------------------------------------

def test_an_unmarked_picture_and_drawing_become_decoration_and_the_tags_stay(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', GOOD, content=BODY + b'q 40 0 0 40 300 200 cm /Im1 Do Q 0.5 g 10 100 30 30 re f', forms=with_image)
    assert statuses(source) == {'content-linkage': 'pass', 'content-coverage': 'fail'}
    result = cover(tmp_path, source)
    assert result['status'] == 'pass', result
    assert result['covered'] == [{'page': 1, 'kind': 'image'}, {'page': 1, 'kind': 'vector'}]
    assert result['visible_preservation']['status'] == 'pass'
    output = tmp_path / 'covered.pdf'
    assert statuses(output) == {'content-linkage': 'pass', 'content-coverage': 'pass'}
    assert pictures(source) == pictures(output) and pictures(source, 2) == pictures(output, 2)
    ops = operators(output)
    assert ops.count('BMC') == 2 and ops.count('EMC') == ops.count('BDC') + 2
    # A drawing is wrapped together with its path building, never in the middle of a path.
    start = ops.index('BMC', ops.index('Do') + 1) if ops.index('BMC') < ops.index('Do') else ops.index('BMC')
    assert ops[start:start + 4] == ['BMC', 're', 'f', 'EMC']
    with pikepdf.open(output) as pdf, pikepdf.open(source) as original:
        assert len(pdf.Root['/StructTreeRoot']['/K'][0]['/K']) == len(original.Root['/StructTreeRoot']['/K'][0]['/K'])


def test_an_unmarked_picture_form_without_text_is_covered_and_one_with_text_is_left_alone(tmp_path):
    from test_designed_pdf import make_form

    def plain(pdf, font):
        return {'/Fm1': make_form(pdf, b'0 0 1 rg 0 0 5 5 re f', bbox=(0, 0, 5, 5))}

    source = tagged_pdf(tmp_path / 'plain.pdf', GOOD, content=BODY + b'/Fm1 Do', forms=plain)
    result = cover(tmp_path, source)
    assert result['status'] == 'pass' and result['covered'] == [{'page': 1, 'kind': 'form'}]
    assert statuses(tmp_path / 'covered.pdf')['content-coverage'] == 'pass'

    def texty(pdf, font):
        return {'/Fm1': make_form(pdf, TEXT % b'Inside', font=font)}

    source = tagged_pdf(tmp_path / 'texty.pdf', GOOD, content=BODY + b'/Fm1 Do', forms=texty)
    result = dp.cover_unmarked_graphics(source, tmp_path / 'texty-covered.pdf')
    assert result['status'] == 'not-needed' and result['covered'] == []
    assert not (tmp_path / 'texty-covered.pdf').exists(), 'A form that paints text is never hidden as decoration.'

    def nested(pdf, font):
        inner = make_form(pdf, TEXT % b'Deep inside', font=font)
        outer = make_form(pdf, b'/In Do', bbox=(0, 0, 5, 5))
        outer['/Resources'] = Dictionary(XObject=Dictionary(In=inner), Font=Dictionary(F1=font))
        return {'/Fm1': outer}

    source = tagged_pdf(tmp_path / 'nested.pdf', GOOD, content=BODY + b'/Fm1 Do', forms=nested)
    result = dp.cover_unmarked_graphics(source, tmp_path / 'nested-covered.pdf')
    assert result['status'] == 'not-needed' and not (tmp_path / 'nested-covered.pdf').exists(), 'Text inside a nested form is not hidden either.'


def test_unmarked_text_is_never_hidden_so_the_tags_are_not_kept(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', GOOD, content=BODY + b'BT /F1 12 Tf 20 100 Td (Loose words) Tj ET')
    result = cover(tmp_path, source)
    assert result['status'] == 'refused' and 'text' in result['reason'] and result['covered'] == []
    assert not (tmp_path / 'covered.pdf').exists() and not list(tmp_path.glob('*partial*'))


def test_more_than_twenty_five_loose_pieces_are_refused(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', GOOD, content=BODY + b''.join(b'%d 100 5 5 re f ' % (i * 8) for i in range(26)))
    result = cover(tmp_path, source)
    assert result['status'] == 'refused' and '25' in result['reason']
    assert not (tmp_path / 'covered.pdf').exists()


def test_a_fully_marked_or_untagged_file_is_left_alone(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', GOOD)
    assert dp.cover_unmarked_graphics(source, tmp_path / 'a.pdf')['status'] == 'not-needed' and not (tmp_path / 'a.pdf').exists()
    with pikepdf.open(source) as pdf:
        del pdf.Root['/StructTreeRoot']
        pdf.save(tmp_path / 'untagged.pdf')
    assert dp.cover_unmarked_graphics(tmp_path / 'untagged.pdf', tmp_path / 'b.pdf')['status'] == 'not-needed'
    with pytest.raises(FileExistsError):
        dp.cover_unmarked_graphics(source, source)


def test_a_covering_that_changes_a_page_is_discarded(tmp_path, monkeypatch):
    source = tagged_pdf(tmp_path / 'tagged.pdf', GOOD, content=BODY + b'0.5 g 10 100 30 30 re f')
    monkeypatch.setattr(dp, '_fidelity_gate', lambda *a, **k: {'status': 'fail', 'pages_compared': 1, 'policy': 'test'})
    result = cover(tmp_path, source)
    assert result['status'] == 'refused' and 'changed a page' in result['reason']
    assert not (tmp_path / 'covered.pdf').exists() and not list(tmp_path.glob('*partial*'))


def test_a_covering_that_still_leaves_tags_failing_is_discarded(tmp_path):
    # An unmarked drawing sits next to marked content whose structure reference is missing, so linkage cannot pass.
    source = tagged_pdf(tmp_path / 'tagged.pdf', GOOD + [dict(role='P', mcids=[9])], content=BODY + b'0.5 g 10 100 30 30 re f')
    assert statuses(source)['content-linkage'] != 'pass'
    result = cover(tmp_path, source)
    assert result['status'] == 'refused' and 'cannot be kept' in result['reason']
    assert not (tmp_path / 'covered.pdf').exists()


# --- author_descriptions ---------------------------------------------------------------------------------------

def test_only_real_descriptions_are_listed_in_document_order(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [
        dict(role='Figure', mcids=[0], alt='Bar chart of weekly attendance'), dict(role='Figure', mcids=[1], alt='image 2'),
        dict(role='Figure', mcids=[2]), dict(role='P', mcids=[3], alt='Not a figure')],
        content=b''.join(marked(m, b'Item %d' % m) for m in range(4)))
    assert dp.author_descriptions(source) == [{'page': 1, 'role': 'Figure', 'description': 'Bar chart of weekly attendance'}]
    with pikepdf.open(source) as pdf:
        del pdf.Root['/StructTreeRoot']
        pdf.save(tmp_path / 'untagged.pdf')
    assert dp.author_descriptions(tmp_path / 'untagged.pdf') == []


# --- repair_author_tags ----------------------------------------------------------------------------------------

def repair(tmp_path, source):
    return dp.repair_author_tags(source, tmp_path / 'repaired.pdf')


def role_map(path):
    with pikepdf.open(path) as pdf:
        mapping = pdf.Root['/StructTreeRoot'].get('/RoleMap')
        return None if mapping is None else {str(k): str(v) for k, v in mapping.items()}


def test_browser_style_inline_types_are_mapped_to_span_and_other_types_are_only_reported(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='Strong', mcids=[1]), dict(role='Em', mcids=[2]),
                                                  dict(role='Mystery', mcids=[3])], content=b''.join(marked(m, b'Para %d' % m) for m in range(4)))
    result = repair(tmp_path, source)
    assert result['status'] == 'pass', result
    assert result['mapped'] == {'/Strong': {'to': '/Span', 'elements': 1}, '/Em': {'to': '/Span', 'elements': 1}}
    assert result['left_alone'] == {'/Mystery': 1}
    assert role_map(tmp_path / 'repaired.pdf') == {'/Strong': '/Span', '/Em': '/Span'}
    assert pictures(source) == pictures(tmp_path / 'repaired.pdf')


def test_a_type_the_author_already_mapped_is_not_touched_and_a_clean_file_writes_nothing(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='Strong', mcids=[1]), dict(role='P', mcids=[2])])
    with pikepdf.open(source) as pdf:
        pdf.Root['/StructTreeRoot']['/RoleMap'] = Dictionary({'/Strong': Name.Em})
        pdf.save(tmp_path / 'mapped.pdf')
    result = repair(tmp_path, tmp_path / 'mapped.pdf')
    assert result['status'] == 'not-needed' and not (tmp_path / 'repaired.pdf').exists()
    clean = tagged_pdf(tmp_path / 'clean.pdf', GOOD)
    assert dp.repair_author_tags(clean, tmp_path / 'other.pdf')['status'] == 'not-needed' and not (tmp_path / 'other.pdf').exists()


def wrapped(tmp_path, *, alt=None, extra_child=None, replace_figure=False, name='wrapped.pdf'):
    source = tagged_pdf(tmp_path / 'base.pdf', [dict(role='P', mcids=[0]), dict(role='Figure', mcids=[1], alt='A bar chart'), dict(role='P', mcids=[2])])
    with pikepdf.open(source) as pdf:
        document = pdf.Root['/StructTreeRoot']['/K'][0]
        figure = document['/K'][1]
        wrapper = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name.Figure, P=document))
        if alt:
            wrapper['/Alt'] = pikepdf.String(alt)
        if replace_figure:
            # Only a caption inside: a Figure around a caption is not a wrapper around a picture.
            figure['/S'] = Name.Caption
            del figure['/Alt']
        wrapper['/K'] = Array([figure] + ([extra_child] if extra_child is not None else []))
        figure['/P'] = wrapper
        document['/K'][1] = wrapper
        pdf.save(tmp_path / name)
    return tmp_path / name


def figure_roles(path):
    with pikepdf.open(path) as pdf:
        return [str(e['/S']) for e in pdf.Root['/StructTreeRoot']['/K'][0]['/K']]


def test_a_figure_that_only_wraps_a_figure_becomes_a_div_and_nothing_else_does(tmp_path):
    source = wrapped(tmp_path)
    result = repair(tmp_path, source)
    assert result['status'] == 'pass' and result['retyped'] == 1
    assert figure_roles(tmp_path / 'repaired.pdf') == ['/P', '/Div', '/P']
    with pikepdf.open(tmp_path / 'repaired.pdf') as pdf:
        assert str(pdf.Root['/StructTreeRoot']['/K'][0]['/K'][1]['/K'][0]['/Alt']) == 'A bar chart', 'The real picture keeps its description.'
    for name, kwargs in (('alt.pdf', dict(alt='Described wrapper')), ('content.pdf', dict(extra_child=99)), ('caption.pdf', dict(replace_figure=True))):
        kept = dp.repair_author_tags(wrapped(tmp_path, name=name, **kwargs), tmp_path / ('out-' + name))
        assert kept['status'] == 'not-needed' and kept['retyped'] == 0, name


def linked(tmp_path, annotations):
    source = tagged_pdf(tmp_path / 'base.pdf', GOOD, content=SPREAD)
    with pikepdf.open(source) as pdf:
        pdf.pages[0].obj['/Annots'] = Array([pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Border=Array([0, 0, 0]), **a)) for a in annotations])
        pdf.save(tmp_path / 'linked.pdf')
    return tmp_path / 'linked.pdf'


def contents(path):
    with pikepdf.open(path) as pdf:
        return [str(a['/Contents']) if '/Contents' in a else None for a in pdf.pages[0].obj['/Annots']]


def test_a_link_with_no_description_gets_the_words_printed_under_it_or_its_address(tmp_path):
    uri = Dictionary(S=Name.URI, URI=pikepdf.String('https://example.org/data'))
    source = linked(tmp_path, [
        dict(Rect=Array([15, 15, 90, 40]), A=uri),                                   # over "Para 0"
        dict(Rect=Array([250, 250, 300, 280]), A=uri),                                # nothing printed there: the address
        dict(Rect=Array([250, 150, 300, 180]), A=Dictionary(S=Name.GoTo, D=Array([pikepdf.Dictionary(), Name.Fit]))),   # nothing, no address
        dict(Rect=Array([15, 15, 90, 40]), A=uri, F=2),                               # hidden
        dict(Rect=Array([15, 15, 90, 40]), A=uri, Contents=pikepdf.String('Already described')),
    ])
    result = repair(tmp_path, source)
    assert result['status'] == 'pass', result
    assert result['links_described'] == [{'page': 1, 'description': 'Para 0', 'from': 'visible text'},
                                         {'page': 1, 'description': 'https://example.org/data', 'from': 'link address'}]
    assert contents(tmp_path / 'repaired.pdf') == ['Para 0', 'https://example.org/data', None, None, 'Already described']
    assert pictures(source) == pictures(tmp_path / 'repaired.pdf')


def test_a_tag_repair_that_changes_a_page_is_discarded(tmp_path, monkeypatch):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='Strong', mcids=[1]), dict(role='P', mcids=[2])])
    monkeypatch.setattr(dp, '_fidelity_gate', lambda *a, **k: {'status': 'fail', 'pages_compared': 1, 'policy': 'test'})
    result = repair(tmp_path, source)
    assert result['status'] == 'refused' and result['mapped'] == {} and result['links_described'] == []
    assert not (tmp_path / 'repaired.pdf').exists() and not list(tmp_path.glob('*partial*'))


# --- recognition picture size ----------------------------------------------------------------------------------

def scan(path, *, size=(400, 500), resolution=80.0):
    Image.new('L', size, 255).save(path, 'PDF', resolution=resolution)
    return path


@pytest.mark.parametrize('resolution, enlarged', [(80.0, True), (200.0, True), (249.0, True), (300.0, False), (600.0, False)])
def test_only_pictures_under_250_dpi_are_enlarged_for_recognition(tmp_path, resolution, enlarged):
    plan = ocr.oversample_plan(scan(tmp_path / 'scan.pdf', resolution=resolution), [1])
    assert (plan['dpi'] == 300) is enlarged, plan
    assert plan['pages_below'] == ([1] if enlarged else [])
    assert abs(plan['lowest_estimated_dpi'] - resolution) <= 2


def test_a_page_that_would_need_too_many_pixels_is_read_as_it_is_and_unreadable_files_do_not_stop_the_plan(tmp_path):
    big = scan(tmp_path / 'big.pdf', size=(400, 400), resolution=4.0)
    plan = ocr.oversample_plan(big, [1])
    assert plan['dpi'] is None and plan['pages_below'] == [1] and 'megapixels' in plan['reason']
    plan = ocr.oversample_plan(tmp_path / 'missing.pdf', [1])
    assert plan['dpi'] is None
    (tmp_path / 'junk.pdf').write_bytes(b'not a pdf')
    assert ocr.oversample_plan(tmp_path / 'junk.pdf', [1])['dpi'] is None
    assert ocr.oversample_plan(scan(tmp_path / 'ok.pdf'), [5])['dpi'] is None, 'A page that does not exist is ignored, not fatal.'


def command_for(tmp_path, monkeypatch, profile, source):
    seen = []
    version = tmp_path / 'version.txt'
    version.write_text('17.13.0\n', encoding='utf-8')

    def double(command, directory, timeout, memory, cancel, env):
        if '--version' in command:
            return {'status': 'completed', 'stdout': str(version)}
        seen.append(list(map(str, command)))
        return {'status': 'error', 'returncode': 1, 'error': 'explicit test stub'}

    monkeypatch.setattr(ocr, 'run', double)
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'test double'})
    result = ocr.run_ocr(source, tmp_path / 'out.pdf', {'project_root': tmp_path / 'project', 'ocr_profile': profile}, tmp_path / 'evidence', mode='textless')
    return seen, result


@pytest.mark.parametrize('profile, asks', [('standard', True), ('turns', True), ('table-lines', False)])
def test_recognition_is_asked_for_an_enlarged_picture_only_for_the_profiles_that_support_it(tmp_path, monkeypatch, profile, asks):
    seen, result = command_for(tmp_path, monkeypatch, profile, scan(tmp_path / 'scan.pdf'))
    assert len(seen) == 1
    assert ('--oversample' in seen[0]) is asks
    if asks:
        assert seen[0][seen[0].index('--oversample') + 1] == '300'
        assert result['oversample']['dpi'] == 300 and result['oversample']['pages_below'] == [1]
    else:
        assert 'oversample' not in result


def test_a_sharp_scan_is_not_enlarged(tmp_path, monkeypatch):
    seen, result = command_for(tmp_path, monkeypatch, 'standard', scan(tmp_path / 'sharp.pdf', resolution=400.0))
    assert '--oversample' not in seen[0] and result['oversample']['dpi'] is None


# --- inside the whole pipeline ---------------------------------------------------------------------------------

def stub_engine(monkeypatch, handed_back, calls):
    def fake_tag(input, output, settings=None, workdir=None, cancel=None):
        calls.append(Path(input))
        shutil.copyfile(handed_back, output)
        return {'status': 'completed', 'engine': 'explicit-test-stub', 'output': str(output)}
    monkeypatch.setattr(engines, 'tag', fake_tag)


def test_existing_tags_with_one_loose_picture_are_kept_with_their_description_and_the_review_is_told(tmp_path, monkeypatch, fast_validator):
    (tmp_path / 'input').mkdir()
    source = tagged_pdf(tmp_path / 'input' / 'article.pdf', [dict(role='P', mcids=[0]), dict(role='Figure', mcids=[1], alt='Bar chart of attendance by week'),
                                                            dict(role='P', mcids=[2])], content=BODY + b'q 40 0 0 40 300 200 cm /Im1 Do Q', forms=with_image)
    monkeypatch.setattr(engines, 'tag', lambda *a, **k: pytest.fail('Tags that can be kept must not be sent to the engine'))
    report = process(source, tmp_path)
    assert processor(report, 'covered-graphics')['status'] == 'pass' and processor(report, 'engine')['status'] == 'skipped'
    assert processor(report, 'author-descriptions') is None
    item = next(i for i in report['manual_review']['items'] if i['id'] == 'unmarked-graphics-marked-decorative')
    assert item['required'] is True and item['status'] == 'pending' and item['page'] == 1 and 'page 1: image' in item['detail']
    with pikepdf.open(published(report)) as pdf:
        assert 'Bar chart of attendance by week' in [str(e['/Alt']) for e in pdf.Root['/StructTreeRoot']['/K'][0]['/K'] if '/Alt' in e]
    assert pictures(source) == pictures(published(report))
    assert report['fidelity']['status'] == 'pass'


def test_when_the_tags_cannot_be_kept_the_descriptions_written_in_them_are_listed_for_the_reviewer(tmp_path, monkeypatch, fast_validator):
    (tmp_path / 'input').mkdir()
    source = tagged_pdf(tmp_path / 'input' / 'article.pdf', [dict(role='P', mcids=[0]), dict(role='Figure', mcids=[1], alt='Bar chart of attendance by week'),
                                                            dict(role='P', mcids=[2])], content=BODY + b'BT /F1 12 Tf 20 100 Td (Loose words) Tj ET')
    handed_back = tagged_pdf(tmp_path / 'engine-made.pdf', [dict(role='P', mcids=[0]), dict(role='Figure', mcids=[1], alt='image 1'), dict(role='P', mcids=[2])],
                             content=BODY + b'BT /F1 12 Tf 20 100 Td (Loose words) Tj ET')
    calls = []
    stub_engine(monkeypatch, handed_back, calls)
    report = process(source, tmp_path)
    assert calls and processor(report, 'covered-graphics')['status'] == 'refused'
    written = processor(report, 'author-descriptions')
    assert written['descriptions'] == [{'page': 1, 'role': 'Figure', 'description': 'Bar chart of attendance by week'}]
    item = next(i for i in report['manual_review']['items'] if i['id'] == 'author-descriptions-not-carried')
    assert item['required'] is True and 'Bar chart of attendance by week' in item['detail'] and item['page'] == 1


def test_browser_style_types_links_and_wrappers_are_repaired_inside_the_pipeline(tmp_path, monkeypatch, fast_validator):
    (tmp_path / 'input').mkdir()
    base = tagged_pdf(tmp_path / 'base.pdf', [dict(role='P', mcids=[0]), dict(role='Strong', mcids=[1]), dict(role='P', mcids=[2])], content=SPREAD)
    with pikepdf.open(base) as pdf:
        pdf.pages[0].obj['/Annots'] = Array([pdf.make_indirect(Dictionary(Type=Name.Annot, Subtype=Name.Link, Rect=Array([15, 15, 90, 40]), Border=Array([0, 0, 0]),
                                                                           A=Dictionary(S=Name.URI, URI=pikepdf.String('https://example.org/x'))))])
        pdf.save(tmp_path / 'input' / 'browser.pdf')
    source = tmp_path / 'input' / 'browser.pdf'
    monkeypatch.setattr(engines, 'tag', lambda *a, **k: pytest.fail('Usable tags must not be sent to the engine'))
    report = process(source, tmp_path)
    repair_report = processor(report, 'author-tag-repairs')
    assert repair_report['status'] == 'pass' and repair_report['mapped'] == {'/Strong': {'to': '/Span', 'elements': 1}}
    assert [x['description'] for x in repair_report['links_described']] == ['Para 0']
    assert role_map(published(report)) == {'/Strong': '/Span'} and contents(published(report)) == ['Para 0']
    assert report['fidelity']['status'] == 'pass' and pictures(source) == pictures(published(report))
    again = process(tmp_path / 'input' / 'browser.pdf', tmp_path / 'second')
    assert processor(again, 'covered-graphics') is None
