"""OCR-derived character maps for embedded two-byte fonts that carry no ToUnicode map."""
from collections import Counter
from pathlib import Path
import os

import pikepdf
import pytest

from pdf_remediator import ocr_mappings as om
from pdf_remediator.config import load_config
from pdf_remediator.doctor import ocr_availability

SRC = Path(om.__file__).resolve().parent
FONT = SRC / 'data' / 'NotoSans-Regular.ttf'
G = om.Glyph


def test_only_two_byte_identity_fonts_without_a_map_are_candidates():
    pdf = pikepdf.new()
    base = dict(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, BaseFont=pikepdf.Name('/AAAAAA+Test'), Encoding=pikepdf.Name('/Identity-H'))
    assert om.candidate_name(pikepdf.Dictionary(**base)) == 'AAAAAA+Test'
    assert om.candidate_name(pikepdf.Dictionary(**{**base, 'Encoding': pikepdf.Name('/Identity-V')})) == 'AAAAAA+Test'
    assert om.candidate_name(pikepdf.Dictionary(**base, ToUnicode=pdf.make_stream(b''))) is None   # an existing map is never rewritten
    assert om.candidate_name(pikepdf.Dictionary(**{**base, 'Encoding': pikepdf.Name('/WinAnsiEncoding')})) is None
    assert om.candidate_name(pikepdf.Dictionary(**{**base, 'Subtype': pikepdf.Name.TrueType})) is None
    assert om.candidate_name(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, Encoding=pikepdf.Name('/Identity-H'))) is None
    assert om.candidate_name(None) is None


def test_font_map_lists_each_code_in_utf16_and_splits_long_lists():
    cmap = om.to_unicode_cmap({1: ' ', 0x2A: 'e', 0x30: '\U0001D7D8'}).decode('ascii')
    assert '<0001> <0020>' in cmap and '<002A> <0065>' in cmap and '<0030> <D835DFD8>' in cmap
    assert 'beginbfrange' not in cmap
    many = om.to_unicode_cmap({code: 'a' for code in range(250)}).decode('ascii')
    assert many.count('beginbfchar') == 3 and many.count('endbfchar') == 3


def test_omitted_glyphs_are_found_in_order_and_unreconcilable_pages_are_refused():
    names = {'F'}
    content = [('F', 5), ('F', 1), ('F', 6), ('F', 7), ('F', 1), ('F', 8)]
    drawn = [G(0, 0, 5, 'F'), G(0, 0, 6, 'F'), G(0, 0, 7, 'F'), G(0, 0, 8, 'F'), G(0, 0, 65, 'Other')]
    assert om.align_omitted(content, drawn, names) == [(0, 'F', 1), (2, 'F', 1)]
    assert om.align_omitted(content[:-1], drawn, names) is None                      # the drawn list has a glyph the content lacks
    assert om.align_omitted([('F', 5), ('F', 5)], [G(0, 0, 5, 'F')], names) is None   # a code both drawn and left out is ambiguous


def test_words_take_only_the_glyphs_whose_centres_fall_inside_them_left_to_right():
    glyphs = [G(30, 10, 2, 'F'), G(10, 10, 1, 'F'), G(20, 10, 3, 'F'), G(200, 10, 9, 'F'), G(50, 10, 7, 'F')]
    words = [om.Word(0, 0, 40, 20, 'abc', 90), om.Word(45, 0, 60, 20, 'z', 90), om.Word(100, 0, 120, 20, 'q', 90)]
    owner, members = om.assign_words(glyphs, words)
    assert [glyphs[i].code for i in members[0]] == [1, 3, 2] and [glyphs[i].code for i in members[1]] == [7] and 2 not in members
    assert owner[3] is None
    overlapping = om.assign_words([G(10, 10, 1, 'F')], [om.Word(0, 0, 20, 20, 'a', 90), om.Word(5, 0, 25, 20, 'b', 90)])
    assert overlapping[0] == [None] and overlapping[1][0] == [] and overlapping[1][1] == []   # a glyph in two words belongs to neither


def counter(**kw):
    return Counter(kw)


def test_a_code_is_mapped_only_with_enough_agreeing_readable_votes():
    census = {('F', 1): 50, ('F', 2): 50, ('F', 3): 50, ('F', 4): 50, ('F', 5): 50}
    votes = {('F', 1): counter(a=40), ('F', 2): counter(b=19, d=1), ('F', 3): counter(c=1), ('F', 4): counter(e=10, f=5), ('F', 5): counter(**{'\x07': 9})}
    maps = om.decide(votes, Counter(), Counter(), Counter(), census, {'F'})['F']
    assert maps == {1: 'a', 2: 'b'}      # 3 has one vote, 4 disagrees, 5 is a control character


def test_a_code_found_between_words_is_a_space_and_never_a_letter():
    census = {('F', 1): 100, ('F', 2): 100, ('F', 3): 100, ('F', 4): 100}
    space = Counter({('F', 1): 95, ('F', 2): 4, ('F', 3): 90, ('F', 4): 3})
    inside = Counter({('F', 1): 5, ('F', 2): 0, ('F', 3): 30, ('F', 4): 0})
    outside = Counter({('F', 1): 100, ('F', 2): 100, ('F', 3): 60, ('F', 4): 0})
    votes = {('F', 3): counter(a=6), ('F', 4): counter(x=9)}      # code 3 once voted 'a' (a one-letter word beside a space)
    maps = om.decide(votes, space, inside, outside, census, {'F'})['F']
    assert maps == {1: ' ', 4: 'x'}      # 2 has too few sightings; 3 sits outside words 60% of the time and is not 90% between words


def test_a_glyph_that_mostly_sits_outside_word_boxes_cannot_become_a_letter_even_with_votes():
    census = {('F', 7): 100}
    maps = om.decide({('F', 7): counter(a=30)}, Counter(), Counter(), Counter({('F', 7): 40}), census, {'F'})['F']
    assert maps == {}


def test_a_rare_code_is_accepted_only_as_the_single_unknown_in_a_confident_word_with_agreeing_readings():
    maps = {'F': {1: 'c', 2: 'a'}}
    training = [([('F', 1), ('F', 2), ('F', 9)], 'cat', 95), ([('F', 1), ('F', 2), ('F', 9)], 'car', 95),
                ([('F', 1), ('F', 2), ('F', 8)], 'cab', 95), ([('F', 1), ('F', 7), ('F', 6)], 'cow', 99), ([('F', 5), ('F', 2), ('F', 4)], 'rat', 40)]
    assert om.add_context_readings(maps, training, {'F'}) == 1      # 8 -> b; 9 has conflicting readings; 7 and 6 share a word; 4 is low confidence
    assert maps['F'] == {1: 'c', 2: 'a', 8: 'b'}


def test_coverage_counts_glyph_occurrences_not_distinct_codes():
    facts = om.font_facts({'F': {1: 'a'}, 'G': {}}, {('F', 1): 90, ('F', 2): 10, ('G', 1): 4}, {'F', 'G'})
    assert facts['F']['coverage'] == 0.9 and facts['F']['mapped_codes'] == 1 and facts['F']['distinct_codes'] == 2
    assert facts['G']['coverage'] == 0.0


def test_heldout_words_are_a_fixed_fifth_and_never_depend_on_the_text():
    flags = [om.is_heldout(page, word) for page in range(5) for word in range(200)]
    assert 0.15 < sum(flags) / len(flags) < 0.25
    assert flags == [om.is_heldout(page, word) for page in range(5) for word in range(200)]


def test_tsv_reading_keeps_only_confident_words():
    tsv = 'level\tpage_num\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext\n' + '\n'.join([
        '5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t96\tHello', '5\t1\t1\t1\t1\t2\t50\t20\t30\t40\t60\tdoubt', '4\t1\t1\t1\t1\t0\t0\t0\t9\t9\t99\t', '5\t1\t1\t1\t1\t3\t90\t20\t30\t40\t88\t '])
    assert [(w.x0, w.y0, w.x1, w.y1, w.text) for w in om.parse_tsv(tsv)] == [(10, 20, 40, 60, 'Hello')]


TEXT = ['The committee reviewed the annual budget and approved several changes to the program.',
        'Students should submit their assignments before the deadline listed in the course schedule.',
        'Accessible documents allow every reader to find headings, lists and tables without a mouse.',
        'A careful editor checks the reading order, the language setting and the alternative text.',
        'Library staff will answer questions about borrowing, renewals and the interlibrary loan service.',
        'The workshop begins promptly at nine, and lunch will be served in the main hall at noon.',
        'Please remember that every figure needs a short description for readers who cannot see it.',
        'Results from the pilot study suggest that clear instructions reduce errors by a large margin.']


def broken_font_pdf(path, pages=3, lines=14, size=15):
    """A real text PDF whose embedded font has NO ToUnicode map: the codes are raw glyph numbers of Noto Sans."""
    fonttools = pytest.importorskip('fontTools.ttLib')
    ttf = fonttools.TTFont(str(FONT))
    cmap, order = ttf.getBestCmap(), ttf.getGlyphOrder()
    gid = {chr(c): order.index(name) for c, name in cmap.items() if c < 0x250}
    pdf = pikepdf.new()
    program = pdf.make_stream(FONT.read_bytes())
    program['/Length1'] = FONT.stat().st_size
    descriptor = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor, FontName=pikepdf.Name('/ABCDEF+NotoSans'), Flags=4,
        FontBBox=pikepdf.Array([-600, -300, 1300, 1100]), ItalicAngle=0, Ascent=1069, Descent=-293, CapHeight=714, StemV=80, FontFile2=program))
    widths = pikepdf.Array([0, pikepdf.Array([int(ttf['hmtx'][name][0] * 1000 / ttf['head'].unitsPerEm) for name in order])])
    descendant = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2, BaseFont=pikepdf.Name('/ABCDEF+NotoSans'),
        CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String('Adobe'), Ordering=pikepdf.String('Identity'), Supplement=0),
        FontDescriptor=descriptor, CIDToGIDMap=pikepdf.Name.Identity, DW=600, W=widths))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, BaseFont=pikepdf.Name('/ABCDEF+NotoSans'),
        Encoding=pikepdf.Name('/Identity-H'), DescendantFonts=pikepdf.Array([descendant])))
    for p in range(pages):
        pdf.add_blank_page(page_size=(612, 792))
        body = ['BT /F1 %d Tf' % size]
        for i in range(lines):
            line = TEXT[(i + p * 3) % len(TEXT)]
            body.append('1 0 0 1 40 %d Tm <%s> Tj' % (740 - i * 24, ''.join('%04X' % gid[ch] for ch in line)))
        body.append('ET')
        pdf.pages[p].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        pdf.pages[p].Contents = pdf.make_stream('\n'.join(body).encode('ascii'))
    pdf.save(path)
    return gid


def test_content_codes_are_the_exact_two_byte_codes_of_candidate_fonts_only(tmp_path):
    source = tmp_path / 'broken.pdf'
    gid = broken_font_pdf(source, pages=1, lines=1)
    with pikepdf.open(source) as pdf:
        names = om.candidate_fonts(pdf)
        assert list(names) == ['ABCDEF+NotoSans']
        codes = om.content_codes(pdf.pages[0], set(names))
    assert codes == [('ABCDEF+NotoSans', gid[ch]) for ch in TEXT[0]]
    with pikepdf.open(source) as pdf:
        assert om.content_codes(pdf.pages[0], {'Other+Font'}) == []


def test_applying_a_map_changes_extracted_text_but_not_one_pixel(tmp_path):
    pdfium = pytest.importorskip('pypdfium2')
    source, repaired = tmp_path / 'broken.pdf', tmp_path / 'repaired.pdf'
    gid = broken_font_pdf(source, pages=1, lines=2)
    before = pdfium.PdfDocument(str(source))[0].get_textpage().get_text_range()
    assert 'committee' not in before
    changes = om.apply_maps(source, repaired, {'ABCDEF+NotoSans': {code: ch for ch, code in gid.items()}})
    assert changes and changes[0]['font'] == 'ABCDEF+NotoSans'
    after = pdfium.PdfDocument(str(repaired))[0].get_textpage().get_text_range()
    assert TEXT[0] in after.replace('\r\n', ' ') and TEXT[1] in after.replace('\r\n', ' ')
    a = pdfium.PdfDocument(str(source))[0].render(scale=2).to_pil().convert('RGB')
    b = pdfium.PdfDocument(str(repaired))[0].render(scale=2).to_pil().convert('RGB')
    from PIL import ImageChops
    assert ImageChops.difference(a, b).getbbox() is None
    with pikepdf.open(source) as untouched:
        assert '/ToUnicode' not in [f for f in untouched.objects if om.candidate_name(f) or f.get('/ToUnicode') is not None][0]


def test_a_font_with_no_decided_map_is_left_exactly_as_it_was(tmp_path):
    source, copy = tmp_path / 'broken.pdf', tmp_path / 'copy.pdf'
    broken_font_pdf(source, pages=1, lines=1)
    assert om.apply_maps(source, copy, {'ABCDEF+NotoSans': {}}) == []
    with pikepdf.open(copy) as pdf:
        assert list(om.candidate_fonts(pdf)) == ['ABCDEF+NotoSans']


def test_configuration_and_command_line_for_the_option_and_its_exclusions():
    from pdf_remediator.cli import _parser
    assert load_config(repair_ocr_mappings=True).repair_ocr_mappings is True
    assert load_config().repair_ocr_mappings is False
    for clash in ({'ocr_mode': 'textless'}, {'repair_source_mappings': True}):
        with pytest.raises(ValueError):
            load_config(repair_ocr_mappings=True, **clash)
    assert _parser().parse_args(['fix', 'in.pdf', '-o', 'out', '--repair-ocr-mappings']).repair_ocr_mappings is True


def test_documents_without_a_candidate_font_are_reported_as_not_needed(tmp_path):
    config = os.environ.get('PDF_REMEDIATOR_OCR_TEST_CONFIG')
    if not config:
        pytest.skip('set PDF_REMEDIATOR_OCR_TEST_CONFIG to a runtime config')
    settings = load_config(config)
    if not ocr_availability(settings)['available']:
        pytest.skip('OCR runtime is not present in the configured copy')
    plain = tmp_path / 'plain.pdf'
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.save(plain)
    result = om.repair_from_ocr(plain, tmp_path / 'out.pdf', settings, tmp_path / 'work')
    assert result['status'] == 'not-needed' and not (tmp_path / 'out.pdf').exists()


@pytest.mark.skipif(not os.environ.get('PDF_REMEDIATOR_OCR_TEST_CONFIG'), reason='set PDF_REMEDIATOR_OCR_TEST_CONFIG to a runtime config to run real OCR')
def test_real_ocr_repairs_a_broken_font_map_and_proves_it_on_held_out_words(tmp_path):
    pdfium = pytest.importorskip('pypdfium2')
    settings = load_config(os.environ['PDF_REMEDIATOR_OCR_TEST_CONFIG'])
    if not ocr_availability(settings)['available']:
        pytest.skip('OCR runtime is not present in the configured copy')
    source, repaired = tmp_path / 'broken.pdf', tmp_path / 'repaired.pdf'
    broken_font_pdf(source, pages=4, lines=26)
    result = om.repair_from_ocr(source, repaired, settings, tmp_path / 'work')
    assert result['status'] in ('pass', 'partial'), result.get('error')
    assert result['holdout']['agreement'] >= 0.95 and result['visible_preservation']['status'] == 'pass'
    text = ' '.join(pdfium.PdfDocument(str(repaired))[0].get_textpage().get_text_range().split())
    assert 'committee reviewed the annual budget' in text or 'annual budget' in text
    assert 'ABCDEF+NotoSans' in {f['font'] for f in result['fonts']}


@pytest.mark.skipif(not os.environ.get('PDF_REMEDIATOR_OCR_TEST_CONFIG'), reason='set PDF_REMEDIATOR_OCR_TEST_CONFIG to a runtime config to run real OCR')
def test_real_ocr_refuses_when_there_is_not_enough_text_to_verify_a_map(tmp_path):
    settings = load_config(os.environ['PDF_REMEDIATOR_OCR_TEST_CONFIG'])
    if not ocr_availability(settings)['available']:
        pytest.skip('OCR runtime is not present in the configured copy')
    source, repaired = tmp_path / 'broken.pdf', tmp_path / 'repaired.pdf'
    broken_font_pdf(source, pages=1, lines=2)
    result = om.repair_from_ocr(source, repaired, settings, tmp_path / 'work')
    assert result['status'] == 'refused' and 'Not enough' in result['error']
    assert not repaired.exists() and not (tmp_path / 'repaired.pdf.mapping-partial').exists()
