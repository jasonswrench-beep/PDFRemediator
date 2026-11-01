"""Actual mapped Type0 layers expose missing word separators without OCR/FPDF."""
import math
from pathlib import Path

from fontTools.ttLib import TTFont
import pikepdf
import pypdfium2 as pdfium
import pytest
import reportlab

from pdf_remediator import ocr_angle_evidence as evidence


WORDS = [{'text': 'Harbor,'}, {'text': 'Beacon'}]


@pytest.fixture
def installed_test_font():
    # Same installed QA font pattern as existing authored native-driver controls.
    return Path(reportlab.__file__).parent / 'fonts/Vera.ttf'


def layer(path, font_path, texts, *, angle=0, gap=.5, include_space_map=True):
    """Use actual font widths, a shared baseline and independently sized words."""
    with TTFont(font_path) as font:
        cmap, units = font.getBestCmap(), font['head'].unitsPerEm
        gids = b''.join(font.getGlyphID(cmap.get(point, '.notdef')).to_bytes(2, 'big') for point in range(128))
        widths = [font['hmtx'].metrics[cmap.get(point, '.notdef')][0] * 1000/units for point in range(128)]
        first_advance = sum(font['hmtx'].metrics[cmap[ord(char)]][0] for char in WORDS[0]['text']) * 8/units
    with pikepdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 300))
        descriptor = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor,
            FontName=pikepdf.Name.SyntheticVera, Flags=4, FontBBox=pikepdf.Array([-1000, -1000, 2000, 2000]),
            ItalicAngle=0, Ascent=1000, Descent=-300, CapHeight=800, StemV=80,
            FontFile2=pdf.make_stream(font_path.read_bytes())))
        descendant = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2,
            BaseFont=pikepdf.Name.SyntheticVera, FontDescriptor=descriptor, DW=600,
            W=pikepdf.Array([0, pikepdf.Array(widths)]),
            CIDSystemInfo=pikepdf.Dictionary(Registry='Adobe', Ordering='Identity', Supplement=0),
            CIDToGIDMap=pdf.make_stream(gids)))
        points = sorted(set(map(ord, ''.join(texts))))
        if not include_space_map:
            points = [point for point in points if point != 32]
        mapping = (b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n'
            b'/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
            b'/CMapName /Synthetic-UCS def /CMapType 2 def\n'
            b'1 begincodespacerange <0000> <ffff> endcodespacerange\n' +
            f'{len(points)} beginbfchar\n'.encode() +
            b''.join(f'<{point:04x}> <{point:04x}>\n'.encode() for point in points) +
            b'endbfchar endcmap CMapName currentdict /CMap defineresource pop end end')
        mapped = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0,
            BaseFont=pikepdf.Name.SyntheticVera, Encoding=pikepdf.Name('/Identity-H'),
            DescendantFonts=pikepdf.Array([descendant]), ToUnicode=pdf.make_stream(mapping)))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=mapped))
        cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        shows = []
        for index, text in enumerate(texts):
            raw = ''.join(f'{ord(char):04x}' for char in text)
            shows.append(f'/F1 {8 if index == 0 else 20} Tf 1 0 0 1 {0 if index == 0 else first_advance+gap} 0 Tm <{raw}> Tj')
        page.Contents = pdf.make_stream((f'q {cosine:.12f} {sine:.12f} {-sine:.12f} {cosine:.12f} 110 150 cm BT 3 Tr '
            + ' '.join(shows) + ' ET Q').encode())
        pdf.save(path, deterministic_id=True)


def extracted(path):
    with pdfium.PdfDocument(path) as document:
        page = document[0]
        try:
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_range()
                letters = [(textpage.get_text_range(index, 1), textpage.get_charbox(index))
                    for index in range(textpage.count_chars()) if not textpage.get_text_range(index, 1).isspace()]
            finally:
                textpage.close()
        finally:
            page.close()
    return text, letters


@pytest.mark.parametrize('angle', [0, 30, 90, 270])
@pytest.mark.parametrize('encoded', [False, True])
def test_real_mixed_size_rotated_words_require_actual_encoded_separators(tmp_path, installed_test_font, angle, encoded):
    unspaced, spaced = tmp_path / 'unspaced.pdf', tmp_path / 'spaced.pdf'
    layer(unspaced, installed_test_font, ['Harbor,', 'Beacon'], angle=angle)
    layer(spaced, installed_test_font, ['Harbor, ', 'Beacon'], angle=angle)
    # Explicit spaces must not move any existing character, even across size changes.
    assert extracted(unspaced)[1] == extracted(spaced)[1]
    assert extracted(spaced)[0].split() == ['Harbor,', 'Beacon']
    if encoded:
        evidence._require_layer(spaced, [300, 300], 72, WORDS)
    else:
        with pytest.raises(ValueError, match='explicit word separators'):
            evidence._require_layer(unspaced, [300, 300], 72, WORDS)


def test_spatially_generated_whitespace_cannot_replace_the_encoded_native_boundary(tmp_path, installed_test_font):
    path = tmp_path / 'wide-gap.pdf'
    layer(path, installed_test_font, ['Harbor,', 'Beacon'], gap=24)
    assert extracted(path)[0].split() == ['Harbor,', 'Beacon']
    with pytest.raises(ValueError, match='explicit word separators'):
        evidence._require_layer(path, [300, 300], 72, WORDS)


@pytest.mark.parametrize('texts', [(['Harbor,  ', 'Beacon']), (['Harbor, ', 'Beacon ']),
    (['Harbor,\u00a0', 'Beacon']), (['Harbor! ', 'Beacon'])])
def test_encoded_boundary_policy_preserves_exact_unicode_and_separator_count(tmp_path, installed_test_font, texts):
    path = tmp_path / 'wrong-boundary.pdf'
    layer(path, installed_test_font, texts)
    with pytest.raises(ValueError, match='explicit word separators or encoded Unicode'):
        evidence._require_layer(path, [300, 300], 72, WORDS)


def test_explicit_space_must_have_a_real_unicode_font_mapping(tmp_path, installed_test_font):
    path = tmp_path / 'unmapped-space.pdf'
    layer(path, installed_test_font, ['Harbor, ', 'Beacon'], include_space_map=False)
    with pytest.raises(ValueError, match='unmapped native text codes'):
        evidence._require_layer(path, [300, 300], 72, WORDS)


@pytest.mark.parametrize('texts,needs_space', [(['Harbor,'], False), (['Harbor,', 'Beacon'], True), (['Harbor Beacon'], True)])
def test_font_proof_includes_space_only_when_rendered_text_uses_it(installed_test_font, texts, needs_space):
    mapping = evidence.glyph_mapping([{'text': text} for text in texts], installed_test_font)
    assert ('32' in mapping) == needs_space
    if needs_space:
        with TTFont(installed_test_font) as font:
            assert mapping['32'] == font.getBestCmap()[32]


@pytest.mark.parametrize('entries', [b'1 beginbfchar\n<0001> <0041>\n',
    b'2 beginbfchar\n<0001> <0041>\n<0001> <0042>\nendbfchar',
    b'1 beginbfchar\n<0001> <d800>\nendbfchar',
    b'1 beginbfchar\n<01> <0041>\nendbfchar', b'1 beginbfrange\n<0001> <0002> <0041>\nendbfrange',
    b'2 beginbfchar\n<0001> <0041>\nendbfchar', b'65537 beginbfchar\n<0001> <0041>\nendbfchar',
    b'1 beginbfchar\n<0001> <0041>\nendbfchar\n1 beginbfrange\n<0002> <0003> <0042>\nendbfrange',
    b'1 beginbfchar\n<0001> <0041>\nendbfchar\n/OtherMap usecmap',
    b'1 beginbfchar\n<0001> <0041>\nendbfchar\n1 begincidchar\n<0002> 66\nendcidchar',
    b'1 beginbfchar\n<0001> <0041>\nendbfchar\n1 begincidrange\n<0002> <0003> 66\nendcidrange'])
def test_fixed_native_unicode_map_refuses_ambiguous_or_unsupported_coding(entries):
    with pikepdf.new() as pdf:
        font = pikepdf.Dictionary(ToUnicode=pdf.make_stream(entries))
        with pytest.raises(ValueError, match='Unicode map'):
            evidence._unicode_cmap(font)
