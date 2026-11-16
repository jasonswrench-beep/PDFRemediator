"""Colour-only-meaning candidate screen: seeded positives, negatives, limits and end-to-end wiring.

Every PDF is built at run time. Nothing here decides whether colour is the only
carrier of meaning; the screen's job is to list candidates for a person.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import threading

import pikepdf
import pypdfium2 as pdfium
import pytest

from pdf_remediator import checks, color_meaning, inspection

BODY = '0 g'
RED = '0.8 0 0 rg'
GREEN = '0 0.55 0 rg'
BLUE = '0 0 0.8 rg'
YELLOW = '1 0.85 0 rg'


def text(x, y, string, fill=BODY, size=12):
    escaped = string.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    return f'BT /F1 {size} Tf {fill} {x} {y} Td ({escaped}) Tj ET\n'


def rect(x, y, width, height, fill):
    return f'q {fill} {x} {y} {width} {height} re f Q\n'


def link(rect_values, *, border=(0, 0, 0), flags=None):
    entry = {'Type': pikepdf.Name.Annot, 'Subtype': pikepdf.Name.Link, 'Rect': pikepdf.Array(rect_values),
             'A': pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String('https://example.org/'))}
    if border is not None:
        entry['Border'] = pikepdf.Array(list(border))
    if flags is not None:
        entry['F'] = flags
    return entry


def source_pdf(directory, content='', *, annots=(), form=None, form_matrix='1 0 0 1 0 0', image=False,
               pages=1, width=612, name='source.pdf'):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    pdf = pikepdf.Pdf.new()
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica))
    for number in range(pages):
        page = pdf.add_blank_page(page_size=(width, 792))
        resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        body = content
        xobjects = pikepdf.Dictionary()
        if form is not None:
            stream = pdf.make_stream(form.encode('ascii'))
            stream.Type, stream.Subtype = pikepdf.Name.XObject, pikepdf.Name.Form
            stream.BBox = pikepdf.Array([0, 0, 400, 400])
            stream.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            xobjects['/Fm'] = stream
            body += f'q {form_matrix} cm /Fm Do Q\n'
        if image:
            picture = pdf.make_stream(b'\xff\x00\x00')
            picture.Type, picture.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
            picture.Width, picture.Height, picture.BitsPerComponent = 1, 1, 8
            picture.ColorSpace = pikepdf.Name.DeviceRGB
            xobjects['/Im'] = picture
            body += 'q 100 0 0 100 300 300 cm /Im Do Q\n'
        if len(xobjects):
            resources['/XObject'] = xobjects
        page.Resources = resources
        page.Contents = pdf.make_stream(body.encode('ascii'))
        if annots and number == 0:
            page.Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(**{k: v for k, v in item.items()}))
                                         for item in annots])
    with path.open('xb') as stream:
        pdf.save(stream, min_version='1.7', deterministic_id=True)
    pdf.close()
    return path


def screen(path, **kwargs):
    original = path.read_bytes()
    result = color_meaning.assess(path, **kwargs)
    assert path.read_bytes() == original
    assert result['source_sha256'] == hashlib.sha256(original).hexdigest()
    assert result['policy'] == color_meaning.POLICY == 'bounded-color-meaning-1' and result['advisory'] is True
    return result


def kinds(result):
    return sorted(row['kind'] for row in result['findings'])


def relative_luminance(rgb):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return .2126 * r + .7152 * g + .0722 * b


def ratio(first, second):
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + .05) / (low + .05)


def test_all_black_text_is_a_clean_complete_pass_with_no_candidates(tmp_path):
    result = screen(source_pdf(tmp_path, text(40, 700, 'Plain black paragraph of text') + text(40, 680, 'Second line')))
    assert result['status'] == 'pass' and result['coverage']['complete'] is True
    assert result['findings'] == [] and result['uncertain'] == []
    assert result['body_color_rgb'] == [0, 0, 0]
    assert any('not a Use of Color' in item or 'no result here is a Use of Color' in item for item in result['limitations'])
    assert 'does not recolor' in result['fix_path']


def test_chromatic_text_unlike_the_body_colour_is_a_candidate_with_evidence(tmp_path):
    content = (text(40, 700, 'Body text that sets the dominant colour of this page and is long') +
               text(40, 680, 'Another black line of the body text for the count') +
               text(40, 660, 'Overdue', RED))
    result = screen(source_pdf(tmp_path, content))
    assert kinds(result) == ['colored-text'] and result['status'] == 'needs-review'
    row = result['findings'][0]
    assert row['page'] == 1 and row['hue'] == 'red' and row['color_rgb'] == [204, 0, 0]
    assert row['body_color_rgb'] == [0, 0, 0] and row['samples'] == ['Overdue'] and row['character_count'] == 7
    assert row['run_count'] == 1 and row['status'] == 'needs-review'
    assert row['luminance_ratio_to_body'] == pytest.approx(ratio((204, 0, 0), (0, 0, 0)), abs=.002)
    assert row['difference'] == 'hue-and-lightness'
    assert row['boxes'] and len(row['boxes'][0]) == 4
    assert result['coverage']['complete'] is True
    assert result['counts']['colored_text_candidates'] == 1


def test_a_difference_that_is_mostly_hue_is_labelled_hue_only(tmp_path):
    body, other = (90, 90, 90), (160, 60, 60)
    assert ratio(body, other) < 3
    content = (text(40, 700, 'Gray body text that sets the dominant colour here', '0.352941 g') +
               text(40, 680, 'Warm', '0.627451 0.235294 0.235294 rg'))
    row = screen(source_pdf(tmp_path, content))['findings'][0]
    assert row['difference'] == 'hue-only' and row['luminance_ratio_to_body'] < 3


@pytest.mark.parametrize('fill', ['0.5 g', '1 g', '0.92 0.92 0.98 rg', '0.05 0.05 0.05 rg'])
def test_gray_white_pale_and_near_black_text_are_never_chromatic_candidates(tmp_path, fill):
    content = text(40, 700, 'Black body text for the dominant colour of the page') + text(40, 680, 'Quiet words', fill)
    result = screen(source_pdf(tmp_path, content))
    assert result['findings'] == [] and result['status'] == 'pass'


def test_a_red_green_pair_on_one_page_is_marked_confusable(tmp_path):
    content = (text(40, 700, 'Black body text for the dominant colour of the page') +
               text(40, 680, 'Stop', RED) + text(40, 660, 'Go', GREEN))
    result = screen(source_pdf(tmp_path, content))
    rows = [row for row in result['findings'] if row['kind'] == 'colored-text']
    assert {row['hue'] for row in rows} == {'red', 'green'}
    assert all(row['red_green_confusable_pair_on_page'] is True for row in rows)


def test_invisible_coloured_text_such_as_an_ocr_layer_is_ignored(tmp_path):
    content = text(40, 700, 'Black body text for the dominant colour of the page') + \
        'BT /F1 12 Tf 3 Tr 0.8 0 0 rg 40 680 Td (Hidden red words) Tj ET\n'
    result = screen(source_pdf(tmp_path, content))
    assert result['findings'] == [] and result['status'] == 'pass'


def test_dominant_colour_comes_from_the_whole_document_not_one_page(tmp_path):
    content = text(40, 700, 'Black body text that dominates the whole document') + \
        text(40, 680, 'Rare accent', BLUE)
    result = screen(source_pdf(tmp_path, content, pages=3))
    blue = [row for row in result['findings'] if row['kind'] == 'colored-text']
    assert [row['page'] for row in blue] == [1, 2, 3]
    assert result['body_color_rgb'] == [0, 0, 0]


LINK_TEXT = text(40, 700, 'Black body text for the dominant colour of this page') + text(40, 660, 'See the guide', BLUE)
LINK_RECT = [38, 656, 130, 674]


def test_link_text_in_a_different_colour_with_no_underline_or_border_is_a_link_candidate(tmp_path):
    result = screen(source_pdf(tmp_path, LINK_TEXT, annots=[link(LINK_RECT)]))
    assert kinds(result) == ['link-color-only']
    row = result['findings'][0]
    assert row['underline_found'] is False and row['border_visible'] is False and row['hue'] == 'blue'
    assert row['sample'] == 'See the guide' and row['rect'] == [38.0, 656.0, 130.0, 674.0]
    assert row['luminance_ratio_to_body'] == pytest.approx(ratio((0, 0, 204), (0, 0, 0)), abs=.002)
    assert row['meets_3_to_1_with_body'] is (row['luminance_ratio_to_body'] >= 3)
    assert result['counts']['links_checked'] == 1 and result['counts']['link_candidates'] == 1
    # The link's words are reported once, as a link, not again as coloured body text.
    assert result['counts']['colored_text_candidates'] == 0


@pytest.mark.parametrize('decoration', [
    '0 0 0.8 RG 1 w 40 657 m 125 657 l S',
    '0 0 0.8 rg 40 656.5 85 1 re f'])
def test_an_underline_drawn_under_the_link_text_removes_the_candidate(tmp_path, decoration):
    result = screen(source_pdf(tmp_path, LINK_TEXT + decoration + '\n', annots=[link(LINK_RECT)]))
    assert result['findings'] == [] and result['counts']['links_checked'] == 1


def test_a_visible_link_border_is_another_cue_and_removes_the_candidate(tmp_path):
    result = screen(source_pdf(tmp_path, LINK_TEXT, annots=[link(LINK_RECT, border=(0, 0, 1))]))
    assert result['findings'] == []


def test_a_link_without_any_border_entry_uses_the_default_visible_border(tmp_path):
    result = screen(source_pdf(tmp_path, LINK_TEXT, annots=[link(LINK_RECT, border=None)]))
    assert result['findings'] == []


def test_a_link_in_the_body_colour_is_not_a_colour_candidate(tmp_path):
    content = text(40, 700, 'Black body text for the dominant colour of this page') + text(40, 660, 'See the guide')
    assert screen(source_pdf(tmp_path, content, annots=[link(LINK_RECT)]))['findings'] == []


def test_a_hidden_link_and_a_link_over_no_text_are_not_candidates(tmp_path):
    result = screen(source_pdf(tmp_path, LINK_TEXT, annots=[link(LINK_RECT, flags=2), link([300, 300, 340, 320])]))
    # The hidden link is not a link to the reader, so its blue words are ordinary colored text.
    assert kinds(result) == ['colored-text'] and result['counts']['links_checked'] == 1


def test_an_unreadable_link_rectangle_is_uncertain_not_ignored(tmp_path):
    broken = link(LINK_RECT)
    broken['Rect'] = pikepdf.Array([1, 2, 3])
    result = screen(source_pdf(tmp_path, LINK_TEXT, annots=[broken]))
    assert result['coverage']['complete'] is False and result['status'] == 'needs-review'
    assert 'unknown-link-rectangle' in result['pages'][0]['reasons']


CHART = (rect(100, 300, 40, 120, '0.8 0 0 rg') + rect(160, 300, 40, 80, '0 0.55 0 rg') +
         rect(220, 300, 40, 100, '0 0 0.8 rg'))


def test_nearby_shapes_in_several_hues_are_a_graphic_candidate(tmp_path):
    result = screen(source_pdf(tmp_path, CHART))
    assert kinds(result) == ['multi-hue-graphic']
    row = result['findings'][0]
    assert row['hues'] == ['blue', 'green', 'red'] and row['path_count'] == 3
    assert row['bbox'] == [100.0, 300.0, 260.0, 420.0] and row['text_characters_inside'] == 0
    assert row['red_green_confusable_pair_on_page'] is True
    assert result['counts']['graphic_regions'] == 1 and result['coverage']['complete'] is True


def test_a_labelled_chart_is_still_listed_and_shows_the_label_text_as_evidence(tmp_path):
    labels = text(100, 285, 'Red 12') + text(160, 285, 'Green 8') + text(220, 285, 'Blue 10')
    row = screen(source_pdf(tmp_path, CHART + labels))['findings'][0]
    assert row['kind'] == 'multi-hue-graphic' and row['text_characters_inside'] == 0 and row['text_characters_nearby'] > 0
    assert 'Red 12' in row['text_sample'] and 'Green 8' in row['text_sample']


@pytest.mark.parametrize('content', [
    rect(100, 300, 40, 120, '0.8 0 0 rg') + rect(160, 300, 40, 80, '0.7 0 0 rg') + rect(220, 300, 40, 100, '0.9 0.1 0.1 rg'),
    rect(100, 300, 40, 120, '0.5 g') + rect(160, 300, 40, 80, '0.7 g') + rect(220, 300, 40, 100, '0.3 g'),
    rect(100, 300, 40, 120, '0.8 0 0 rg') + rect(160, 300, 40, 80, '0 0.55 0 rg'),
    rect(0, 0, 612, 792, '1 0.9 0 rg') + rect(100, 300, 40, 120, '0 0 0.8 rg') + rect(160, 300, 40, 80, '0 0 0.7 rg'),
    rect(100, 300, 40, 120, '0.8 0 0 rg') + rect(100, 600, 40, 80, '0 0.55 0 rg') + rect(400, 100, 40, 100, '0 0 0.8 rg'),
], ids=['one-hue', 'grays-only', 'two-shapes-only-below-the-minimum', 'page-background-ignored', 'far-apart-shapes'])
def test_single_hue_gray_tiny_background_or_distant_shapes_are_not_graphic_candidates(tmp_path, content):
    result = screen(source_pdf(tmp_path, content))
    assert [row for row in result['findings'] if row['kind'] == 'multi-hue-graphic'] == []


def test_artifact_marked_coloured_shapes_are_skipped_and_counted(tmp_path):
    content = '/Artifact BMC\n' + CHART + 'EMC\n'
    result = screen(source_pdf(tmp_path, content))
    assert [row for row in result['findings'] if row['kind'] == 'multi-hue-graphic'] == []
    assert result['counts']['artifact_graphics_skipped'] == 3


def test_shapes_inside_a_scaled_form_are_located_in_page_space(tmp_path):
    form = rect(10, 10, 20, 60, '0.8 0 0 rg') + rect(40, 10, 20, 40, '0 0.55 0 rg') + rect(70, 10, 20, 50, '0 0 0.8 rg')
    result = screen(source_pdf(tmp_path, '', form=form, form_matrix='2 0 0 2 100 100'))
    row = result['findings'][0]
    assert row['kind'] == 'multi-hue-graphic' and row['path_count'] == 3
    assert row['bbox'] == [120.0, 120.0, 280.0, 240.0]


def test_a_stroked_line_chart_with_series_in_several_hues_is_a_candidate(tmp_path):
    lines = ''.join(f'{colour} RG 3 w 100 {y} m 200 {y + 15} l S\n'
                    for colour, y in (('0.8 0 0', 300), ('0 0.55 0 ', 330), ('0 0 0.8', 360)))
    row = screen(source_pdf(tmp_path, lines))['findings'][0]
    assert row['kind'] == 'multi-hue-graphic' and row['hues'] == ['blue', 'green', 'red']


def annotation(subtype, colour=None, contents=None, **extra):
    entry = {'Type': pikepdf.Name.Annot, 'Subtype': pikepdf.Name(subtype), 'Rect': pikepdf.Array([40, 600, 200, 620]), **extra}
    if colour is not None:
        entry['C'] = pikepdf.Array(list(colour))
    if contents is not None:
        entry['Contents'] = pikepdf.String(contents)
    return entry


def test_coloured_markup_annotations_are_candidates_but_uncoloured_or_pale_ones_are_not(tmp_path):
    result = screen(source_pdf(tmp_path, text(40, 700, 'Black body text'), annots=[
        annotation('/Highlight', (1, 0.9, 0)), annotation('/Highlight', (1, 0.9, 0), contents='Check'),
        annotation('/Underline'), annotation('/Square', (0.95, 0.95, 0.99)), annotation('/Popup', (1, 0, 0))]))
    rows = [row for row in result['findings'] if row['kind'] == 'colored-annotation']
    assert len(rows) == 1
    assert rows[0]['subtype'] == '/Highlight' and rows[0]['count'] == 2 and rows[0]['with_comment_text'] == 1
    assert rows[0]['hue'] == 'yellow' and rows[0]['color_rgb'] == [255, 230, 0]


def test_widget_or_stamp_appearance_streams_are_not_measured_and_keep_the_page_under_review(tmp_path):
    widget = annotation('/Widget', AP=pikepdf.Dictionary())
    result = screen(source_pdf(tmp_path, text(40, 700, 'Black body text'), annots=[widget]))
    assert 'annotation-appearance-color-not-assessed' in result['pages'][0]['reasons']
    assert result['coverage']['complete'] is False and result['status'] == 'needs-review'


@pytest.mark.parametrize('sentence,pattern', [
    ('Pay the items in red first.', 'noun-in-color'),
    ('The red items are overdue.', 'the-color-noun'),
    ('This table is colour-coded for each region.', 'color-coded'),
    ('Rows are highlighted in yellow when late.', 'shown-in-color'),
    ('Click the green button to continue.', 'act-on-color'),
    ('Red means stop and green means go.', 'color-means'),
    ('See the colour legend below.', 'color-key'),
    ('The colors indicate each department.', 'the-colors-mean'),
])
def test_text_that_points_at_colour_is_a_phrase_candidate(tmp_path, sentence, pattern):
    result = screen(source_pdf(tmp_path, text(40, 700, sentence)))
    rows = [row for row in result['findings'] if row['kind'] == 'color-reference-text']
    assert rows and rows[0]['pattern'] == pattern and rows[0]['page'] == 1
    assert rows[0]['phrase'].lower() in rows[0]['context'].lower()
    assert result['counts']['phrase_candidates'] == len(rows)


@pytest.mark.parametrize('sentence', [
    'The Red Cross appeals for funds.', 'We went to the blue lagoon last summer.',
    'Black text on a white page.', 'The report is complete and accurate.', 'Greenhouse gases rose in recent years.'])
def test_ordinary_colour_words_without_a_pointing_phrase_are_not_candidates(tmp_path, sentence):
    result = screen(source_pdf(tmp_path, text(40, 700, sentence)))
    assert [row for row in result['findings'] if row['kind'] == 'color-reference-text'] == []


def test_a_picture_makes_the_page_uncertain_and_never_a_clean_pass(tmp_path):
    result = screen(source_pdf(tmp_path, text(40, 700, 'Black body text'), image=True))
    assert result['status'] == 'needs-review' and result['coverage']['complete'] is False
    assert 'raster-image-color-not-assessed' in result['pages'][0]['reasons']
    assert result['uncertain'][0]['kind'] == 'page-coverage' and result['uncertain'][0]['page'] == 1
    assert 'raster-images' in result['coverage']['not_assessed']


def test_a_page_with_no_text_or_graphics_is_not_applicable(tmp_path):
    result = screen(source_pdf(tmp_path, ''))
    assert result['status'] == 'not-applicable' and result['findings'] == []


def test_the_record_limit_is_visible_and_cannot_earn_clean_coverage(tmp_path, monkeypatch):
    monkeypatch.setitem(color_meaning.LIMITS, 'records', 1)
    content = (text(40, 700, 'Black body text for the dominant colour of the page') +
               text(40, 680, 'Red words', RED) + text(40, 660, 'Blue words', BLUE))
    result = screen(source_pdf(tmp_path, content))
    assert len(result['findings']) == 1 and result['counts']['records'] == 1
    assert result['coverage']['complete'] is False and 'record-limit' in result['coverage']['reasons']
    assert result['status'] == 'needs-review'


@pytest.mark.parametrize('limit,value,reason', [('characters', 10, 'character-limit'), ('objects_per_page', 1, 'object-limit')])
def test_character_and_object_limits_are_reported_not_hidden(tmp_path, monkeypatch, limit, value, reason):
    monkeypatch.setitem(color_meaning.LIMITS, limit, value)
    result = screen(source_pdf(tmp_path, text(40, 700, 'A long enough paragraph of black text') + CHART))
    assert reason in result['pages'][0]['reasons'] and result['coverage']['complete'] is False


def test_pages_past_the_page_limit_are_listed_as_unmeasured(tmp_path, monkeypatch):
    monkeypatch.setitem(color_meaning.LIMITS, 'pages', 2)
    result = screen(source_pdf(tmp_path, text(40, 700, 'Black body text'), pages=3))
    assert result['coverage']['unmeasured_pages'] == [3] and result['coverage']['complete'] is False
    assert 'page-limit' in result['coverage']['reasons']


def test_cancellation_is_checked_inside_the_character_pass_and_the_source_stays_exact(tmp_path, monkeypatch):
    source = source_pdf(tmp_path, text(40, 700, 'a' * 1000), width=10000)
    original = source.read_bytes()
    flag = threading.Event()
    actual = color_meaning.raw.FPDFText_GetUnicode
    called = []

    def read(page, index):
        called.append(index)
        if index == 1:
            flag.set()
        return actual(page, index)
    monkeypatch.setattr(color_meaning.raw, 'FPDFText_GetUnicode', read)
    with pytest.raises(InterruptedError):
        color_meaning.assess(source, cancel=flag)
    assert called and max(called) <= 255 and source.read_bytes() == original


def test_borrowed_contexts_stay_open_and_no_pdf_writer_is_used(tmp_path, monkeypatch):
    source = source_pdf(tmp_path, text(40, 700, 'Black body text') + text(40, 680, 'Red', RED))

    def refuse(*args, **kwargs):
        raise AssertionError('The advisory screen cannot write a PDF')
    monkeypatch.setattr(pikepdf.Pdf, 'save', refuse)
    with pikepdf.open(source) as pdf, pdfium.PdfDocument(str(source)) as document:
        result = screen(source, pdf=pdf, document=document)
        assert len(pdf.pages) == len(document) == 1
    assert result['findings']


def test_a_source_that_changes_during_the_screen_is_an_error_not_a_result(tmp_path, monkeypatch):
    source = source_pdf(tmp_path, text(40, 700, 'Black body text'))
    original = color_meaning._sha
    calls = []

    def changing(path):
        calls.append(1)
        return original(path) if len(calls) == 1 else '0' * 64
    monkeypatch.setattr(color_meaning, '_sha', changing)
    result = color_meaning.assess(source)
    assert result['status'] == 'error' and result['coverage']['complete'] is False


def test_the_result_is_deterministic_and_json_serialisable(tmp_path):
    import json
    source = source_pdf(tmp_path, LINK_TEXT + CHART + text(40, 500, 'Items in red are late.'), annots=[link(LINK_RECT)])
    first, second = color_meaning.assess(source), color_meaning.assess(source)
    assert first == second
    json.dumps(first, sort_keys=True)


# End to end through the inspection and the supplemental-check profile.

def assessed(path):
    original = path.read_bytes()
    report = inspection.inspect_pdf(path)
    assert path.read_bytes() == original and not report.get('error'), report.get('error')
    assert report['color_meaning']['policy'] == color_meaning.POLICY
    return report, checks.assess(report)


def test_inspection_carries_the_screen_and_the_check_profile_makes_a_required_pending_review(tmp_path):
    content = (text(40, 700, 'Black body text for the dominant colour of the page') +
               text(40, 680, 'Overdue', RED))
    report, result = assessed(source_pdf(tmp_path, content))
    row = next(item for item in result['checks'] if item['id'] == 'color-meaning')
    assert row['blocking'] is False and row['severity'] == 'advisory' and row['status'] == 'needs-review'
    assert 'color-meaning' not in result['blocking_checks'] and 'color-meaning' in result['coverage']['automated']
    manual = next(item for item in result['manual_queue'] if item['category'] == 'color-meaning')
    assert manual['status'] == 'pending' and manual['required'] is True and manual['id'] == 'color-meaning'
    assert manual['evidence'] == report['color_meaning'] and manual['pages'] == [1]
    assert 'does not recolor' in manual['detail'] and 'authoring document' in manual['detail']
    assert row['fix_path'] == color_meaning.FIX
    assert 'color-meaning' in result['coverage']['human_pending']
    assert not any(item['id'] == 'color-meaning' for item in report['checks'])
    assert result['claim'].startswith('Declared automated profile only')


def test_a_complete_candidate_free_screen_adds_no_colour_review(tmp_path):
    report, result = assessed(source_pdf(tmp_path, text(40, 700, 'Black body text only')))
    assert report['color_meaning']['status'] == 'pass'
    assert not any(item['category'] == 'color-meaning' for item in result['manual_queue'])
    row = next(item for item in result['checks'] if item['id'] == 'color-meaning')
    assert row['status'] == 'pass' and row['blocking'] is False


@pytest.mark.parametrize('change', ['unknown-policy', 'forged-clean', 'missing', 'older-report-without-the-field'])
def test_unknown_forged_or_absent_screens_cannot_remove_the_colour_review(tmp_path, change):
    report, _ = assessed(source_pdf(tmp_path, text(40, 700, 'Black body text only')))
    modified = copy.deepcopy(report)
    if change == 'unknown-policy':
        modified['color_meaning']['policy'] = 'unknown-screen'
    elif change == 'forged-clean':
        modified['color_meaning'].update(status='pass', coverage={'complete': False})
    else:
        del modified['color_meaning']
    result = checks.assess(modified)
    row = next(item for item in result['checks'] if item['id'] == 'color-meaning')
    assert row['blocking'] is False and row['status'] in {'needs-review', 'not-tested'}
    assert any(item['category'] == 'color-meaning' and item['required'] for item in result['manual_queue'])


def test_the_absent_screen_message_does_not_pretend_to_be_about_other_screens(tmp_path):
    report, _ = assessed(source_pdf(tmp_path, text(40, 700, 'Black body text only')))
    del report['color_meaning']
    row = next(item for item in checks.assess(report)['checks'] if item['id'] == 'color-meaning')
    assert any('color' in item.lower() and 'meaning' in item.lower() for item in row['limitations'])


def test_the_screen_never_changes_the_strict_blocking_set_or_other_screens(tmp_path):
    report, result = assessed(source_pdf(tmp_path, CHART + LINK_TEXT, annots=[link(LINK_RECT)]))
    baseline = copy.deepcopy(report)
    del baseline['color_meaning']
    older = checks.assess(baseline)
    assert result['blocking_checks'] == older['blocking_checks']
    assert [item['id'] for item in result['blockers']] == [item['id'] for item in older['blockers']]
    others = {item['id']: item['status'] for item in result['checks'] if item['id'] != 'color-meaning'}
    assert others == {item['id']: item['status'] for item in older['checks'] if item['id'] != 'color-meaning'}


def test_the_workspace_view_offers_the_colour_evidence_as_a_repair_finding_without_new_authority(tmp_path):
    from pdf_remediator import workspace as ws
    report, result = assessed(source_pdf(tmp_path, text(40, 700, 'Black body text for the page') + text(40, 680, 'Late', RED)))
    manual = next(item for item in result['manual_queue'] if item['category'] == 'color-meaning')
    state = {'manual_items': [{**manual, 'status': 'pending'}], 'residual_issues': []}
    findings = ws._repair_findings(state)
    assert findings == [{'id': 'color-meaning', 'status': 'needs-review', 'evidence': manual['evidence'],
                         'fix_path': manual['detail']}]
    findings[0]['evidence']['status'] = 'pass'
    assert state['manual_items'][0]['evidence']['status'] == 'needs-review'


# Content the screen cannot measure keeps its page under review instead of passing silently.

def custom_pdf(directory, build, name='custom.pdf'):
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(612, 792))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica))
    build(pdf, page, font)
    path = Path(directory) / name
    with path.open('xb') as stream:
        pdf.save(stream, min_version='1.7', deterministic_id=True)
    pdf.close()
    return path


def tiling_pattern(pdf):
    tile = pdf.make_stream(b'1 0 0 rg 0 0 5 5 re f')
    tile.Type, tile.PatternType, tile.PaintType, tile.TilingType = pikepdf.Name.Pattern, 1, 1, 1
    tile.BBox, tile.XStep, tile.YStep, tile.Resources = pikepdf.Array([0, 0, 10, 10]), 10, 10, pikepdf.Dictionary()
    return tile


def test_stroked_or_outline_text_is_not_measured_and_keeps_the_page_under_review(tmp_path):
    content = text(40, 700, 'Black body text for the page') + 'BT /F1 12 Tf 1 Tr 0.8 0 0 RG 40 680 Td (Outlined) Tj ET\n'
    result = screen(source_pdf(tmp_path, content))
    assert 'stroked-or-clipping-text-color-not-assessed' in result['pages'][0]['reasons']
    assert result['findings'] == [] and result['coverage']['complete'] is False and result['status'] == 'needs-review'


def test_a_pattern_painted_shape_cannot_be_silently_treated_as_a_neutral_color(tmp_path):
    def build(pdf, page, font):
        page.Resources = pikepdf.Dictionary(Pattern=pikepdf.Dictionary(P1=tiling_pattern(pdf)))
        page.Contents = pdf.make_stream(b'/Pattern cs /P1 scn 100 300 80 80 re f 0 0.5 0 rg 200 300 80 80 re f')
    result = screen(custom_pdf(tmp_path, build))
    assert result['pages'][0]['reasons'] == ['pattern-paint-color-not-assessed']
    assert result['coverage']['complete'] is False and result['status'] == 'needs-review'
    assert result['uncertain'][0]['reasons'] == ['pattern-paint-color-not-assessed']


def test_pattern_and_shading_resources_inside_a_nested_form_are_found(tmp_path):
    def build(pdf, page, font):
        inner = pdf.make_stream(b'/Pattern cs /P1 scn 0 0 50 50 re f')
        inner.Type, inner.Subtype, inner.BBox = pikepdf.Name.XObject, pikepdf.Name.Form, pikepdf.Array([0, 0, 100, 100])
        inner.Resources = pikepdf.Dictionary(Pattern=pikepdf.Dictionary(P1=tiling_pattern(pdf)),
                                             Shading=pikepdf.Dictionary(S1=pdf.make_indirect(pikepdf.Dictionary(ShadingType=2))))
        outer = pdf.make_stream(b'/In Do')
        outer.Type, outer.Subtype, outer.BBox = pikepdf.Name.XObject, pikepdf.Name.Form, pikepdf.Array([0, 0, 100, 100])
        outer.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(In=inner))
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Out=outer))
        page.Contents = pdf.make_stream(b'/Out Do')
    reasons = screen(custom_pdf(tmp_path, build))['pages'][0]['reasons']
    assert reasons == ['pattern-paint-color-not-assessed', 'shading-color-not-assessed']


def test_a_form_that_contains_itself_does_not_loop_and_a_type3_font_is_reported(tmp_path):
    def build(pdf, page, font):
        loop = pdf.make_stream(b'/Self Do')
        loop.Type, loop.Subtype, loop.BBox = pikepdf.Name.XObject, pikepdf.Name.Form, pikepdf.Array([0, 0, 100, 100])
        loop.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Self=loop))
        charproc = pdf.make_stream(b'600 0 d0 0 0 500 700 re f')
        type3 = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type3, FontBBox=pikepdf.Array([0, 0, 600, 700]),
            FontMatrix=pikepdf.Array([.001, 0, 0, .001, 0, 0]), CharProcs=pikepdf.Dictionary(A=charproc),
            Encoding=pikepdf.Dictionary(Differences=pikepdf.Array([65, pikepdf.Name.A])), FirstChar=65, LastChar=65,
            Widths=pikepdf.Array([600]), Resources=pikepdf.Dictionary()))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F3=type3), XObject=pikepdf.Dictionary(L=loop))
        page.Contents = pdf.make_stream(b'BT /F3 12 Tf 40 700 Td (A) Tj ET')
    result = screen(custom_pdf(tmp_path, build))
    assert 'type3-glyph-color-not-assessed' in result['pages'][0]['reasons'] and result['coverage']['complete'] is False


def test_optional_content_is_a_document_reason_and_prevents_a_clean_pass(tmp_path):
    def build(pdf, page, font):
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(b'BT /F1 12 Tf 40 700 Td (Layers) Tj ET')
        pdf.Root.OCProperties = pikepdf.Dictionary(OCGs=pikepdf.Array(), D=pikepdf.Dictionary())
    result = screen(custom_pdf(tmp_path, build))
    assert result['coverage']['reasons'] == ['optional-content-context']
    assert result['coverage']['complete'] is False and result['status'] == 'needs-review'


def test_text_inside_a_scaled_form_keeps_its_color_and_page_space_position(tmp_path):
    form = text(10, 10, 'Late', RED, size=10)
    result = screen(source_pdf(tmp_path, text(40, 700, 'Black body text for the dominant color of the page'),
                               form=form, form_matrix='2 0 0 2 100 100'))
    row = next(item for item in result['findings'] if item['kind'] == 'colored-text')
    assert row['samples'] == ['Late'] and row['boxes'][0][0] == pytest.approx(120, abs=3) and row['boxes'][0][1] == pytest.approx(120, abs=6)


# The guide must describe exactly what the code does.

DOC = Path(__file__).resolve().parents[1] / 'docs' / 'COLOR-ONLY-MEANING.md'
DOC_REASONS = ['raster-image-color-not-assessed', 'shading-color-not-assessed', 'pattern-paint-color-not-assessed',
               'annotation-appearance-color-not-assessed', 'type3-glyph-color-not-assessed',
               'stroked-or-clipping-text-color-not-assessed', 'text-color-unresolved', 'unknown-link-rectangle',
               'character-limit', 'object-limit', 'chromatic-path-limit', 'record-limit', 'page-limit',
               'region-limit', 'region-work-limit', 'annotation-limit', 'phrase-limit',
               'pattern-or-unresolved-paint-color', 'unknown-graphic-bounds', 'unknown-path-paint',
               'unknown-artifact-marks', 'unknown-character-bounds', 'unknown-annotation-structure',
               'unsupported-page-rotation']


def test_the_guide_names_every_pattern_color_word_threshold_and_reason_the_code_uses():
    import re
    guide = DOC.read_text(encoding='utf-8')
    source = Path(color_meaning.__file__).read_text(encoding='utf-8')
    for name in color_meaning.PHRASE_PATTERNS:
        assert f'`{name}`' in guide, name
    for word in color_meaning.COLOR_WORDS:
        assert f'`{word}`' in guide, word
    for stem in re.findall(r'([a-z]+)\??', color_meaning._NOUN):
        assert stem in guide, stem
    thresholds = color_meaning.THRESHOLDS
    for value, wording in [(thresholds['chromatic_min_saturation'], 'saturation is at least {}'),
                           (thresholds['chromatic_min_value'], 'value at least {}'),
                           (thresholds['clear_difference_rgb_distance'], 'distance of at least {}'),
                           (thresholds['region_gap_pt'], 'within {} points'),
                           (thresholds['underline_max_height_pt'], 'not more than {} points tall'),
                           (round(thresholds['underline_min_overlap_fraction'] * 100), 'at least {} percent as wide'),
                           (thresholds['min_graphic_region_paths'], 'number at least {}'),
                           (thresholds['min_graphic_dimension_pt'], 'under {} point')]:
        assert wording.format(f'{value:g}' if isinstance(value, float) else value) in guide, wording
    for reason in DOC_REASONS:
        assert f'`{reason}`' in guide, reason
        assert f"'{reason}'" in source, reason
    for band_end, hue in color_meaning.HUE_BANDS[:-1]:
        assert hue in guide


def test_every_example_in_the_guide_is_found_by_the_pattern_it_is_listed_under():
    import re
    rows = [line for line in DOC.read_text(encoding='utf-8').splitlines()
            if re.match(r'\| `[a-z-]+` \|', line) and re.match(r'\| `([a-z-]+)`', line).group(1) in color_meaning.PHRASE_PATTERNS]
    assert {re.match(r'\| `([a-z-]+)`', row).group(1) for row in rows} == set(color_meaning.PHRASE_PATTERNS)
    for row in rows:
        name = re.match(r'\| `([a-z-]+)`', row).group(1)
        examples = re.findall(r'"([^"]+)"', row.split('|')[-2])
        assert examples, row
        for example in examples:
            assert color_meaning._PHRASES[name].search(example), (name, example)


def test_the_record_carries_the_exact_patterns_and_thresholds_that_produced_it(tmp_path):
    result = screen(source_pdf(tmp_path, text(40, 700, 'Black words')))
    assert result['phrase_patterns'] == color_meaning.PHRASE_PATTERNS
    assert result['thresholds'] == color_meaning.THRESHOLDS and result['limits'] == color_meaning.LIMITS


def test_the_region_clustering_budget_is_bounded_and_a_partly_grouped_page_never_looks_complete(tmp_path, monkeypatch):
    monkeypatch.setitem(color_meaning.LIMITS, 'region_comparisons', 3)
    result = screen(source_pdf(tmp_path, CHART))
    assert 'region-work-limit' in result['pages'][0]['reasons'] and result['coverage']['complete'] is False
    assert [row for row in result['findings'] if row['kind'] == 'multi-hue-graphic'] == []


def test_a_page_dense_with_colored_shapes_finishes_quickly_and_reports_its_limits(tmp_path):
    import time
    cells = ''.join(rect(20 + 12 * column, 20 + 12 * row, 10, 10, ('0.8 0 0 rg', '0 0.55 0 rg', '0 0 0.8 rg')[(row + column) % 3])
                    for row in range(45) for column in range(45))
    started = time.time()
    result = screen(source_pdf(tmp_path, cells))
    assert time.time() - started < 20
    page = result['pages'][0]
    assert 'chromatic-path-limit' in page['reasons'] and result['coverage']['complete'] is False
    assert result['status'] == 'needs-review'


# This program marks untagged shapes /Artifact in its processed copy. The screen of the copy then skips them, so the
# card takes the graphic findings from the unmodified input (``with_original_graphics``) and nothing else from it.

BODY_LINE = text(40, 700, 'Black body text for the dominant colour of this page')
HIDDEN_CHART = '/Artifact BMC\n' + CHART + 'EMC\n'


def original_and_copy(tmp_path, *, original_extra='', copy_extra='', original_image=False):
    original = screen(source_pdf(tmp_path / 'original', BODY_LINE + CHART + original_extra, image=original_image))
    processed = screen(source_pdf(tmp_path / 'copy', BODY_LINE + HIDDEN_CHART + copy_extra))
    return original, processed


def test_the_copys_own_artifact_marks_hide_the_chart_but_the_input_still_shows_it(tmp_path):
    original, processed = original_and_copy(tmp_path)
    assert kinds(original) == ['multi-hue-graphic'] and kinds(processed) == []
    assert processed['counts']['artifact_graphics_skipped'] == 3 and original['counts']['artifact_graphics_skipped'] == 0


def test_the_inputs_graphic_findings_are_restored_and_the_record_says_where_they_came_from(tmp_path):
    original, processed = original_and_copy(tmp_path)
    before = (copy.deepcopy(original), copy.deepcopy(processed))
    merged = color_meaning.with_original_graphics(processed, original)
    assert (original, processed) == before
    assert kinds(merged) == ['multi-hue-graphic'] and merged['findings'] == original['findings']
    assert merged['status'] == 'needs-review' and merged['counts']['graphic_regions'] == 1
    assert merged['counts']['artifact_graphics_skipped'] == 0 and merged['counts']['records'] == 1
    assert merged['coverage']['complete'] is True
    assert merged['graphics_from_original'] == {'source_sha256': original['source_sha256'],
                                                'result_artifact_graphics_skipped': 3,
                                                'original_artifact_graphics_skipped': 0}
    assert merged['limitations'][-1] == color_meaning.ORIGINAL_GRAPHICS_NOTE
    assert merged['source_sha256'] == processed['source_sha256']
    merged['findings'][0]['hues'].append('marker')
    assert 'marker' not in original['findings'][0]['hues']


def test_a_clean_copy_screen_cannot_hide_a_chart_the_input_has(tmp_path):
    original, processed = original_and_copy(tmp_path)
    assert processed['status'] == 'pass' and processed['findings'] == []
    merged = color_meaning.with_original_graphics(processed, original)
    assert merged['status'] == 'needs-review'


def test_the_copys_own_findings_stay_and_are_not_replaced_by_the_inputs(tmp_path):
    # An OCR text layer exists only in the copy: its phrase and colour findings must survive.
    original, processed = original_and_copy(tmp_path, copy_extra=text(40, 640, 'Late', RED) +
                                            text(40, 620, 'The red items are overdue.'))
    assert kinds(processed) == ['color-reference-text', 'colored-text']
    merged = color_meaning.with_original_graphics(processed, original)
    assert kinds(merged) == ['color-reference-text', 'colored-text', 'multi-hue-graphic']
    order = [color_meaning.KIND_ORDER[row['kind']] for row in merged['findings']]
    assert order == sorted(order)


def test_when_the_copy_hid_nothing_the_input_did_not_already_hide_the_record_is_returned_unchanged(tmp_path):
    marked = BODY_LINE + HIDDEN_CHART
    first = screen(source_pdf(tmp_path / 'a', marked))
    second = screen(source_pdf(tmp_path / 'b', marked))
    assert color_meaning.with_original_graphics(second, first) is second
    plain = screen(source_pdf(tmp_path / 'c', BODY_LINE + CHART))
    assert color_meaning.with_original_graphics(plain, plain) is plain


def test_what_the_input_could_not_measure_still_limits_the_merged_record(tmp_path):
    original, processed = original_and_copy(tmp_path, original_image=True)
    assert original['pages'][0]['reasons'] == ['raster-image-color-not-assessed'] and processed['pages'][0]['reasons'] == []
    merged = color_meaning.with_original_graphics(processed, original)
    assert merged['pages'][0]['reasons'] == ['raster-image-color-not-assessed'] and merged['pages'][0]['status'] == 'needs-review'
    assert merged['coverage']['complete'] is False
    assert [row['kind'] for row in merged['uncertain']] == ['page-coverage'] and merged['uncertain'][0]['page'] == 1
    assert merged['counts']['records'] == 2


@pytest.mark.parametrize('damage', ['policy', 'advisory', 'error', 'pages', 'findings', 'counts', 'coverage', 'page-count'])
def test_an_unusable_or_mismatched_input_screen_leaves_the_copys_record_alone(tmp_path, damage):
    original, processed = original_and_copy(tmp_path)
    broken = copy.deepcopy(original)
    if damage == 'policy':
        broken['policy'] = 'something-else'
    elif damage == 'advisory':
        broken['advisory'] = False
    elif damage == 'error':
        broken['status'] = 'error'
    elif damage == 'pages':
        broken['pages'] = 'nope'
    elif damage == 'findings':
        broken['findings'] = None
    elif damage == 'counts':
        broken['counts'] = []
    elif damage == 'coverage':
        broken['coverage'] = {'complete': 'yes', 'unmeasured_pages': []}
    else:
        broken['pages'].append({'page': 2, 'status': 'pass', 'reasons': []})
    assert color_meaning.with_original_graphics(processed, broken) is processed
    assert color_meaning.with_original_graphics(processed, None) is processed
    assert color_meaning.with_original_graphics(None, original) is None


def test_the_record_limit_is_kept_and_a_truncated_merge_never_looks_complete(tmp_path, monkeypatch):
    original, processed = original_and_copy(tmp_path, copy_extra=text(40, 640, 'Late', RED))
    monkeypatch.setitem(color_meaning.LIMITS, 'records', 1)
    merged = color_meaning.with_original_graphics(processed, original)
    assert kinds(merged) == ['colored-text'] and merged['coverage']['complete'] is False
    assert 'record-limit' in merged['coverage']['reasons'] and merged['status'] == 'needs-review'


def test_the_checks_use_the_inputs_graphics_only_when_given_the_input_inspection(tmp_path):
    original_path = source_pdf(tmp_path / 'original', BODY_LINE + CHART)
    copy_path = source_pdf(tmp_path / 'copy', BODY_LINE + HIDDEN_CHART)
    original_report, copy_report = inspection.inspect_pdf(original_path), inspection.inspect_pdf(copy_path)
    assert [row['kind'] for row in copy_report['color_meaning']['findings']] == []
    plain = checks.assess(copy_report)
    assert not any(item['category'] == 'color-meaning' for item in plain['manual_queue'])
    with_input = checks.assess(copy_report, source=original_report)
    manual = next(item for item in with_input['manual_queue'] if item['category'] == 'color-meaning')
    assert [row['kind'] for row in manual['evidence']['findings']] == ['multi-hue-graphic']
    assert manual['status'] == 'pending' and manual['required'] is True
    row = next(item for item in with_input['checks'] if item['id'] == 'color-meaning')
    assert row['status'] == 'needs-review' and row['blocking'] is False
    assert color_meaning.ORIGINAL_GRAPHICS_NOTE in row['limitations']
    assert with_input['blocking_checks'] == plain['blocking_checks']
    assert copy_report['color_meaning']['findings'] == []  # the raw inspection of the copy is not edited
    same = checks.assess(original_report, source=original_report)
    assert next(item for item in same['checks'] if item['id'] == 'color-meaning')['evidence'] == original_report['color_meaning']
