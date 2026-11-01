"""Turn-first recognition for sideways and upside-down scans: turn rule, placement maths, font map, evidence and configuration."""
import json
import os
from pathlib import Path

import pikepdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from pdf_remediator import ocr_turns as turns
from pdf_remediator.cli import _parser
from pdf_remediator.config import load_config
from pdf_remediator.doctor import ocr_availability

SRC = Path(turns.__file__).resolve().parent


def hocr(*words):
    body = ''.join("<span class='ocrx_word' id='word_1_%d' title='bbox 1 2 3 4; x_wconf %s'>%s</span>" % (i, conf, text)
                   for i, (conf, text) in enumerate(words))
    return "<div class='ocr_page'><span class='ocr_line' title='bbox 1 2 3 4'>%s</span></div>" % body


def test_only_confident_words_with_enough_letters_count():
    page = hocr((96, 'Accessible'), (59, 'maybe'), (95, '12'), (90, 'to'), (80, '<strong>Bold</strong>'), (75, 'caf&#233;'), (60, 'edge'))
    assert turns.confident_words(page) == 4
    assert turns.confident_words('') == 0
    assert turns.confident_words("<span class='ocr_line' title='x_wconf 99'>line</span>") == 0


@pytest.mark.parametrize('scores,expected', [
    ({0: 200, 90: 34, 180: 34, 270: 200}, (0, 'kept')),             # upright: Tesseract also reads the neighbouring turn
    ({0: 34, 90: 34, 180: 202, 270: 202}, (270, 'upright-pair')),  # picture turned 90 counter-clockwise
    ({0: 40, 90: 200, 180: 200, 270: 40}, (180, 'upright-pair')),  # upside down
    ({0: 200, 90: 200, 180: 40, 270: 40}, (90, 'upright-pair')),   # picture turned 90 clockwise: turn 0 reads only partly
    ({0: 0, 90: 1, 180: 0, 270: 9}, (270, 'best')),                # a single clear peak, no neighbouring pair
    ({0: 3, 90: 2, 180: 1, 270: 4}, (0, 'kept')),                  # almost no text anywhere
    ({0: 80, 90: 80, 180: 80, 270: 80}, (0, 'kept')),              # no turn is distinguishable
    ({0: 100, 90: 20, 180: 15, 270: 30}, (0, 'kept')),             # already best as it is
    ({0: 100, 90: 100, 180: 70, 270: 70}, (0, 'kept')),            # an unreadable pair that is not clearly worse
])
def test_turn_rule_keeps_upright_pages_and_picks_the_upright_member_of_a_readable_pair(scores, expected):
    assert turns.choose_turn(scores) == expected


@pytest.mark.parametrize('scores', [{0: 1}, {0: 1, 90: 1, 180: 1}, {0: 1, 90: 1, 180: 1, 270: -1}, {0: 1, 90: 1, 180: 1, 270: 1.5}])
def test_turn_rule_refuses_incomplete_or_invalid_scores(scores):
    with pytest.raises(ValueError):
        turns.choose_turn(scores)


@pytest.mark.parametrize('turn,forward', [
    (0, lambda x, y, w, h: (x, y)),
    (90, lambda x, y, w, h: (h - y, x)),
    (180, lambda x, y, w, h: (w - x, h - y)),
    (270, lambda x, y, w, h: (y, w - x))])
def test_placement_matrix_undoes_the_counter_clockwise_turn_of_the_page(turn, forward):
    w, h = 300.0, 200.0
    layer = (h, w) if turn in (90, 270) else (w, h)
    a, b, c, d, e, f = turns.placement_matrix(turn, w, h, *layer)
    for x, y in [(0, 0), (300, 0), (0, 200), (300, 200), (37.5, 120.25)]:
        lx, ly = forward(x, y, w, h)
        assert (a * lx + c * ly + e, b * lx + d * ly + f) == pytest.approx((x, y))


def test_placement_matrix_scales_a_layer_of_slightly_different_size_and_refuses_other_angles():
    a, b, c, d, e, f = turns.placement_matrix(0, 300, 200, 150, 100)
    assert (a, d) == (2, 2)
    with pytest.raises(ValueError):
        turns.placement_matrix(45, 300, 200, 300, 200)


def test_explicit_font_map_lists_each_used_code_and_has_no_giant_range():
    cmap = turns.explicit_to_unicode([0x41, 0x2019, 0x41, 0xe9]).decode('ascii')
    assert '<0041> <0041>' in cmap and '<2019> <2019>' in cmap and '<00E9> <00E9>' in cmap
    assert cmap.count('beginbfchar') == 1 and '<0000> <FFFF> <0000>' not in cmap and 'beginbfrange' not in cmap
    with pytest.raises(ValueError):
        turns.explicit_to_unicode(range(turns.MAX_CODES + 1))


def layer_pdf(path, text_codes=(0x48, 0x69), size=(200, 300)):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=size)
    page = pdf.pages[0]
    range_map = b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap 1 begincodespacerange <0000> <FFFF> endcodespacerange 1 beginbfrange <0000> <FFFF> <0000> endbfrange endcmap end end"
    descendant = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2, BaseFont=pikepdf.Name.Test,
        CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String('Adobe'), Ordering=pikepdf.String('Identity'), Supplement=0), DW=500))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, BaseFont=pikepdf.Name.Test,
        Encoding=pikepdf.Name('/Identity-H'), DescendantFonts=pikepdf.Array([descendant]), ToUnicode=pdf.make_stream(range_map)))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    hexed = ''.join('%04X' % c for c in text_codes)
    page.Contents = pdf.make_stream(('q 200 0 0 300 0 0 cm Q\nBT\n3 Tr 1 0 0 1 10 20 Tm /F1 12 Tf <%s> Tj\nET\n' % hexed).encode('ascii'))
    pdf.save(path)


@pytest.mark.parametrize('turn,size', [(0, (200, 300)), (90, (300, 200)), (180, (200, 300)), (270, (300, 200))])
def test_placed_layer_has_the_original_page_size_an_explicit_font_map_and_no_form_xobject(tmp_path, turn, size):
    layer, placed = tmp_path / 'layer.pdf', tmp_path / 'placed.pdf'
    layer_pdf(layer, (0x48, 0x69, 0x2019))
    turns.place_text_layer(layer, placed, turn)
    with pikepdf.open(placed) as pdf:
        page = pdf.pages[0]
        assert [float(v) for v in page.MediaBox] == [0, 0, *map(float, size)]
        assert '/XObject' not in page.Resources
        cmap = list(page.Resources.Font.values())[0].ToUnicode.read_bytes().decode('ascii')
        assert '<0048> <0048>' in cmap and '<2019> <2019>' in cmap and '<FFFF> <0000>' not in cmap
        assert page.Contents.read_bytes().startswith(b'q\n')


def test_placed_text_lands_where_the_inverse_turn_puts_it(tmp_path):
    pdfium = pytest.importorskip('pypdfium2')
    layer, placed = tmp_path / 'layer.pdf', tmp_path / 'placed.pdf'
    layer_pdf(layer)
    turns.place_text_layer(layer, placed, 90)  # the layer's (10, 20) is the original page's (x=20, y=200-10) after a 90 degree turn
    page = pdfium.PdfDocument(str(placed))[0]
    text = page.get_textpage()
    assert text.get_text_range().strip() == 'Hi'
    assert text.count_rects() >= 1
    left, bottom, right, top = text.get_rect(0)
    # The text starts at the original page's (20, 190) and runs DOWN the page with its glyphs standing to the right of that line.
    assert 18 <= left <= 22 and 186 <= top <= 192 and right - left < 12 and bottom < top


def proof_set(tmp_path, scores=None, turn=None, page=1, source='a' * 64):
    scores = scores or {'0': 34, '90': 34, '180': 202, '270': 202}
    turn = 270 if turn is None else turn
    binding = {'plugin_sha256': 'b' * 64, 'algorithm_sha256': 'c' * 64}
    folder = tmp_path / 'ev'
    folder.mkdir(exist_ok=True)
    proof = {'schema': turns.SCHEMA, 'profile': 'turns', 'version': turns.VERSION, 'page': page, 'adapter_source_sha256': source, **binding,
             'turn_ccw': turn, 'trial_scores': scores}
    (folder / ('%06d.json' % page)).write_text(json.dumps(proof), encoding='utf-8')
    return folder, binding


def test_evidence_is_accepted_only_when_complete_bound_and_rule_following(tmp_path):
    folder, binding = proof_set(tmp_path)
    pages = turns.validate_pages(folder, [1], binding, 'a' * 64, 3)
    assert [(p['page'], p['turn_ccw']) for p in pages] == [(1, 270)]
    with pytest.raises(ValueError):
        turns.validate_pages(folder, [1, 2], binding, 'a' * 64, 3)                   # a required page is missing
    with pytest.raises(ValueError):
        turns.validate_pages(folder, [1], binding, 'f' * 64, 3)                      # a different source document
    with pytest.raises(ValueError):
        turns.validate_pages(folder, [1], {**binding, 'plugin_sha256': 'd' * 64}, 'a' * 64, 3)  # the implementation changed
    with pytest.raises(ValueError):
        turns.validate_pages(folder, [1], binding, 'a' * 64, 0)                      # page outside the document


def test_evidence_that_disagrees_with_the_fixed_turn_rule_or_filename_is_refused(tmp_path):
    folder, binding = proof_set(tmp_path, turn=180)
    with pytest.raises(ValueError):
        turns.validate_pages(folder, [1], binding, 'a' * 64, 3)
    other = tmp_path / 'other'
    other.mkdir()
    proof_set(tmp_path)
    (tmp_path / 'ev' / '000001.json').rename(other / '000002.json')
    with pytest.raises(ValueError):
        turns.validate_pages(other, [1], binding, 'a' * 64, 3)


def test_configuration_and_command_line_accept_the_profile_but_never_with_redo():
    assert load_config(ocr_profile='turns', ocr_mode='textless').ocr_profile == 'turns'
    assert load_config(ocr_profile='turns', ocr_mode='skip').ocr_profile == 'turns'
    with pytest.raises(ValueError):
        load_config(ocr_profile='turns', ocr_mode='redo')
    args = _parser().parse_args(['fix', 'in.pdf', '-o', 'out', '--ocr', 'textless', '--ocr-profile', 'turns'])
    assert args.ocr_profile == 'turns'


def test_ocr_step_refuses_redo_for_the_profile_before_touching_any_file(tmp_path):
    from pdf_remediator.ocr import run_ocr
    result = run_ocr(tmp_path / 'in.pdf', tmp_path / 'out.pdf', {'ocr_profile': 'turns'}, mode='redo')
    assert result['status'] == 'unsupported' and 'redo' in result['error']
    assert not (tmp_path / 'out.pdf').exists()


def sideways_scan(path, turn):
    font = ImageFont.truetype(str(SRC / 'data' / 'NotoSans-Regular.ttf'), 38)
    page = Image.new('L', (1700, 2200), 255)
    draw = ImageDraw.Draw(page)
    for i in range(14):
        draw.text((90, 120 + i * 120), 'The committee reviewed the annual budget and approved several changes to the program.', font=font, fill=0)
    if turn:
        page = page.transpose({90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}[turn])
    page.save(path, 'PDF', resolution=200.0)


@pytest.mark.skipif(not os.environ.get('PDF_REMEDIATOR_OCR_TEST_CONFIG'), reason='set PDF_REMEDIATOR_OCR_TEST_CONFIG to a runtime config to run real OCR')
@pytest.mark.parametrize('turn', [90, 180])
def test_real_ocr_reads_a_sideways_scan_with_the_profile_and_keeps_the_page_picture(tmp_path, turn):
    from pdf_remediator.ocr import run_ocr
    config = load_config(os.environ['PDF_REMEDIATOR_OCR_TEST_CONFIG'], ocr_profile='turns', ocr_mode='textless')
    if not ocr_availability(config)['available']:
        pytest.skip('OCR runtime is not present in the configured copy')
    scan = tmp_path / 'scan.pdf'
    sideways_scan(scan, turn)
    result = run_ocr(scan, tmp_path / 'ocr.pdf', config, tmp_path / 'work', mode='textless')
    assert result['status'] == 'completed', result.get('error')
    assert result['preservation']['status'] == 'pass'
    assert result['recognition_turns']['turned_pages'] == [1]
    import pypdfium2 as pdfium
    text = pdfium.PdfDocument(str(tmp_path / 'ocr.pdf'))[0].get_textpage().get_text_range()
    assert 'committee' in text and 'budget' in text and text.count('annual') >= 10
