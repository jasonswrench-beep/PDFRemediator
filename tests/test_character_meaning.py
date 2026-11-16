"""Read-only screen for implausible or unverifiable extracted characters.

Every fixture is built here from the TrueType font that ships with reportlab,
so no external PDF, licensed font or native tool is needed.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from pdf_remediator import character_meaning as meaning
from pdf_remediator import tounicode

VERA = Path(reportlab.__file__).parent / 'fonts/Vera.ttf'
VERA_BOLD = Path(reportlab.__file__).parent / 'fonts/VeraBd.ttf'


def vera_pdf(directory, text='Cafe au lait 123', *, name='source.pdf', second=None):
    """One page of text in an embedded, subset TrueType font with its ToUnicode map."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for face, path in (('Vera', VERA), ('VeraBd', VERA_BOLD)):
        try:
            pdfmetrics.getFont(face)
        except KeyError:
            pdfmetrics.registerFont(TTFont(face, str(path)))
    target = directory / name
    page = canvas.Canvas(str(target), invariant=True)
    page.setFont('Vera', 14)
    page.drawString(72, 700, text)
    if second:
        page.setFont('VeraBd', 14)
        page.drawString(72, 660, second)
    page.showPage()
    page.save()
    return target


def subset_fonts(pdf):
    return [o for o in pdf.objects if isinstance(o, pikepdf.Dictionary) and o.get('/Subtype') == pikepdf.Name.TrueType]


def rewrite(source, destination, *, entries=None, drop=(), remove_key=False, font_index=0, differences=None, content=None):
    """Copy a PDF, changing one font's ToUnicode entries (by code) or page content."""
    with pikepdf.open(source) as pdf:
        font = subset_fonts(pdf)[font_index]
        if remove_key:
            del font['/ToUnicode']
        else:
            parsed = tounicode.parse(font['/ToUnicode'].read_bytes())
            for code, value in (entries or {}).items():
                parsed['entries'][(1, code)] = value
            for code in drop:
                del parsed['entries'][(1, code)]
            font['/ToUnicode'] = pdf.make_stream(tounicode.serialize(parsed))
        if differences:
            font['/Encoding'] = pikepdf.Dictionary(Type=pikepdf.Name.Encoding, Differences=pikepdf.Array(differences))
        if content is not None:
            pdf.pages[0].Contents = pdf.make_stream(content(pdf.pages[0].Contents.read_bytes()))
        pdf.save(destination)
    return Path(destination)


def type0_pdf(directory, text='Cafe', *, name='type0.pdf', with_to_unicode=True):
    """A composite Identity-H font with an embedded CID font and 2-byte codes."""
    from fontTools.ttLib import TTFont as FontFile
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = VERA.read_bytes()
    face = FontFile(str(VERA))
    cmap, order = face.getBestCmap(), face.getGlyphOrder()
    gids = [order.index(cmap[ord(ch)]) for ch in text]
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(612, 792))
    program = pdf.make_stream(data)
    program.Length1 = len(data)
    descriptor = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor, FontName=pikepdf.Name('/AAAAAA+Vera'),
        Flags=4, FontBBox=pikepdf.Array([-200, -300, 1200, 1000]), ItalicAngle=0, Ascent=900, Descent=-200,
        CapHeight=700, StemV=80, FontFile2=program))
    cid = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2,
        BaseFont=pikepdf.Name('/AAAAAA+Vera'), CIDToGIDMap=pikepdf.Name.Identity, DW=600, FontDescriptor=descriptor,
        CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String('Adobe'), Ordering=pikepdf.String('Identity'), Supplement=0)))
    entries = {(2, gid): ch for gid, ch in zip(gids, text)}
    fields = dict(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, BaseFont=pikepdf.Name('/AAAAAA+Vera'),
                  Encoding=pikepdf.Name('/Identity-H'), DescendantFonts=pikepdf.Array([cid]))
    if with_to_unicode:
        fields['ToUnicode'] = pdf.make_stream(tounicode.serialize({'codespaces': [(2, 0, 0xFFFF)], 'entries': entries}))
    font = pdf.make_indirect(pikepdf.Dictionary(**fields))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    shown = ''.join(f'{gid:04X}' for gid in gids)
    page.Contents = pdf.make_stream(f'BT /F1 24 Tf 72 700 Td <{shown}> Tj ET'.encode('ascii'))
    target = directory / name
    pdf.save(target, deterministic_id=True)
    return target, {ch: gid for gid, ch in zip(gids, text)}


def screen(path):
    before = Path(path).read_bytes()
    document = pdfium.PdfDocument(str(path))
    try:
        result = meaning.assess(path, document=document)
    finally:
        document.close()
    assert Path(path).read_bytes() == before, 'the screen must never change the file'
    assert result['policy'] == meaning.POLICY and result['advisory'] is True
    assert result['source_sha256'] == hashlib.sha256(before).hexdigest()
    json.dumps(result)  # the whole record must be storable
    return result


def issues(result):
    return {finding['issue'] for finding in result['findings']}


# ------------------------------------------------------------------ the CMap reader and writer

CMAP = b"""/CIDInit /ProcSet findresource begin 12 dict begin begincmap
/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def
/CMapName /Adobe-Identity-UCS def /CMapType 2 def
1 begincodespacerange <00> <FF> endcodespacerange
2 beginbfchar <01> <0041> <02> <D83DDE00> endbfchar
1 beginbfrange <10> <12> <0061> endbfrange
1 beginbfrange <20> <21> [<0062> <00630064>] endbfrange
endcmap CMapName currentdict /CMap defineresource pop end end"""


def test_cmap_reads_chars_ranges_arrays_and_surrogate_pairs():
    parsed = tounicode.parse(CMAP)
    assert parsed['entries'] == {(1, 1): 'A', (1, 2): '\U0001F600', (1, 16): 'a', (1, 17): 'b', (1, 18): 'c',
                                 (1, 32): 'b', (1, 33): 'cd'}
    assert parsed['codespaces'] == [(1, 0, 255)]


def test_cmap_round_trips_exactly_and_deterministically():
    parsed = tounicode.parse(CMAP)
    written = tounicode.serialize(parsed)
    assert tounicode.parse(written) == parsed
    assert tounicode.serialize(tounicode.parse(written)) == written


def test_cmap_writer_supports_two_byte_codes_and_many_entries():
    entries = {(2, code): chr(0x4E00 + code) for code in range(1, 450)}
    written = tounicode.serialize({'codespaces': [(2, 0, 0xFFFF)], 'entries': entries})
    assert written.count(b'beginbfchar') == 5  # blocks of at most 100
    assert tounicode.parse(written)['entries'] == entries


@pytest.mark.parametrize('raw,why', [
    (b'not a cmap', 'Not a single complete CMap'),
    (CMAP.replace(b'begincmap', b'begincmap /Other usecmap'), 'usecmap'),
    (CMAP.replace(b'<01> <0041>', b'<01> <004>'), 'Odd or empty'),
    (CMAP.replace(b'<D83DDE00>', b'<D83D>'), 'unpaired surrogate'),
    (CMAP.replace(b'<02> <D83DDE00>', b'<01> <0042>'), 'more than once'),
    (CMAP.replace(b'<10> <12> <0061>', b'<12> <10> <0061>'), 'Reversed'),
    (CMAP.replace(b'<00> <FF>', b'<00> <0F>'), 'outside the declared code space'),
    (CMAP.replace(b'<10> <12> <0061>', b'<10> <12> <FFFF>'), 'overflows'),
    (CMAP.replace(b'<20> <21> [<0062> <00630064>]', b'<20> <21> [<0062>]'), 'wrong length'),
    (b'begincmap endcmap', 'no mappings'),
    (CMAP + b' ' * (tounicode.MAX_BYTES + 1), 'bounded parser size'),
], ids=['garbage', 'usecmap', 'odd-hex', 'lone-surrogate', 'duplicate', 'reversed', 'outside-codespace', 'overflow',
        'short-array', 'no-mappings', 'too-large'])
def test_cmap_refuses_everything_outside_its_grammar(raw, why):
    with pytest.raises(tounicode.CMapError, match='(?i)' + why):
        tounicode.parse(raw)


def test_cmap_destination_length_is_bounded():
    long = '<' + ''.join(f'{0x41 + i:04X}' for i in range(tounicode.MAX_TEXT_CODE_POINTS + 1)) + '>'
    raw = CMAP.replace(b'<01> <0041>', b'<01> ' + long.encode())
    with pytest.raises(tounicode.CMapError, match='longer'):
        tounicode.parse(raw)


# ------------------------------------------------------------------ the screen

def test_clean_embedded_font_passes_and_changes_nothing(tmp_path):
    result = screen(vera_pdf(tmp_path))
    assert result['status'] == 'pass', result
    assert result['findings'] == [] and result['uncertain'] == []
    assert result['coverage']['complete'] is True and result['coverage']['pages_scanned'] == 1
    [font] = result['fonts']
    assert font['embedded'] and font['to_unicode'] == 'present' and font['reviewed_correction_available'] is True
    assert font['used_codes'] == len(set('Cafe au lait 123'))


@pytest.mark.parametrize('replacement,flag', [
    ('\ue001', 'private-use'), ('\ufffd', 'replacement-character'), ('\x01', 'control-character'),
    ('\U0010FFFD', 'private-use'), ('\ufdd0', 'noncharacter'), ('\u0378', 'unassigned-code-point')])
def test_implausible_code_points_are_reported_with_context(tmp_path, replacement, flag):
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: replacement})
    result = screen(broken)
    assert result['status'] == 'needs-review'
    [finding] = [f for f in result['findings'] if f['issue'] == flag]
    [code] = finding['codes']
    assert code['code_hex'] == '65' and flag in code['flags'] and code['uses'] == 1
    assert code['context'].startswith('Caf') and ' au lait 123' in code['context']
    assert finding['page'] == 1 and finding['reviewed_correction_available'] is True


def test_a_code_missing_from_a_partial_to_unicode_map_is_reported(tmp_path):
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', drop=[0x6C])
    result = screen(broken)
    [finding] = [f for f in result['findings'] if f['issue'] == 'unmapped-code']
    assert [c['code_hex'] for c in finding['codes']] == ['6C'] and finding['codes'][0]['source'] is None


def test_an_embedded_font_without_to_unicode_is_reported_not_guessed(tmp_path):
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', remove_key=True)
    result = screen(broken)
    [finding] = [f for f in result['findings'] if f['issue'] == 'missing-tounicode']
    assert finding['code_count'] == len(set('Cafe au lait 123'))
    [font] = result['fonts']
    assert font['reviewed_correction_available'] is False
    assert any('no readable ToUnicode map' in reason for reason in font['reviewed_correction_limits'])


def test_unembedded_standard_font_is_listed_but_is_not_a_character_problem(tmp_path):
    path = tmp_path / 'helvetica.pdf'
    page = canvas.Canvas(str(path), invariant=True)
    page.setFont('Helvetica', 12)
    page.drawString(72, 700, 'Plain text 123')
    page.showPage()
    page.save()
    result = screen(path)
    assert result['status'] == 'pass' and result['findings'] == []
    [listed] = result['unembedded_fonts']
    assert listed['font']['standard_14'] is True and listed['font']['embedded'] is False
    assert 'does not embed or substitute fonts' in listed['guidance']
    [font] = result['fonts']
    assert font['reviewed_correction_available'] is False
    assert any('not embedded' in reason for reason in font['reviewed_correction_limits'])


def test_unembedded_unknown_font_without_mapping_is_unverifiable(tmp_path):
    path = tmp_path / 'unknown.pdf'
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(612, 792))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.TrueType,
                                                BaseFont=pikepdf.Name('/MysterySans')))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    page.Contents = pdf.make_stream(b'BT /F1 12 Tf 72 700 Td (abc) Tj ET')
    pdf.save(path)
    result = screen(path)
    assert result['status'] == 'needs-review'
    assert 'missing-tounicode' in issues(result)
    assert result['unembedded_fonts'][0]['font']['standard_14'] is False


def test_glyph_name_that_disagrees_with_the_mapping_is_reported(tmp_path):
    differences = [0x65, pikepdf.Name('/e')]
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: 'x'}, differences=differences)
    result = screen(broken)
    [finding] = [f for f in result['findings'] if f['issue'] == 'glyph-name-disagrees']
    assert finding['codes'][0]['glyph_name'] == 'e' and finding['codes'][0]['text'] == 'x'
    agreeing = rewrite(vera_pdf(tmp_path, name='ok.pdf'), tmp_path / 'ok2.pdf', differences=differences)
    assert 'glyph-name-disagrees' not in issues(screen(agreeing))


def test_ligature_glyph_names_agree_after_compatibility_normalisation(tmp_path):
    ligature = rewrite(vera_pdf(tmp_path), tmp_path / 'lig.pdf', entries={0x65: 'fi'},
                       differences=[0x65, pikepdf.Name('/fi')])
    assert 'glyph-name-disagrees' not in issues(screen(ligature))


def test_actual_text_that_disagrees_with_the_mapping_is_reported(tmp_path):
    wrap = lambda stream: b'/Span << /ActualText (Zed) >> BDC ' + stream + b' EMC'
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', content=wrap)
    result = screen(broken)
    [finding] = [f for f in result['findings'] if f['issue'] == 'actualtext-disagrees']
    assert finding['declared_actual_text'] == 'Zed' and finding['shown_text'].startswith('Cafe')
    agreeing = rewrite(vera_pdf(tmp_path, name='ok.pdf'), tmp_path / 'ok2.pdf',
                       content=lambda stream: b'/Span << /ActualText (Cafe au lait 123) >> BDC ' + stream + b' EMC')
    assert 'actualtext-disagrees' not in issues(screen(agreeing))


def test_mixed_script_word_is_reported_for_the_ocr_editor(tmp_path):
    broken = rewrite(vera_pdf(tmp_path, text='Cafe au lait'), tmp_path / 'broken.pdf', entries={0x61: '\u0430'})
    result = screen(broken)
    found = [f for f in result['findings'] if f['issue'] == 'mixed-script-word']
    assert {f['sample'] for f in found} == {'C\u0430fe', 'l\u0430it'}
    assert all(f['page'] == 1 and 'OCR text editor' in f['note'] for f in found)


def test_suspect_extracted_text_without_a_font_level_finding_is_reported(tmp_path, monkeypatch):
    path = vera_pdf(tmp_path)
    document = pdfium.PdfDocument(str(path))
    monkeypatch.setattr(meaning, '_page_text_screen',
                        lambda doc, pages, cancel: ([{'page': 1, 'counts': {'replacement-character': 2}}], []))
    result = meaning.assess(path, document=document)
    document.close()
    [finding] = result['findings']
    assert finding['issue'] == 'extracted-text-suspect-characters' and finding['per_page'][0]['page'] == 1


def test_text_in_a_form_xobject_is_seen(tmp_path):
    source = vera_pdf(tmp_path)
    nested = tmp_path / 'nested.pdf'
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0]
        form = pdf.make_stream(page.Contents.read_bytes())
        form.Type, form.Subtype = pikepdf.Name.XObject, pikepdf.Name.Form
        form.BBox = pikepdf.Array([0, 0, 612, 792])
        form.Resources = page.Resources
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm1=form))
        page.Contents = pdf.make_stream(b'q /Fm1 Do Q')
        pdf.save(nested)
    broken = rewrite(nested, tmp_path / 'broken.pdf', entries={0x65: '\ue001'})
    result = screen(broken)
    assert 'private-use' in issues(result) and result['fonts'][0]['used_codes'] == len(set('Cafe au lait 123'))


def test_graphics_state_restore_returns_to_the_outer_font(tmp_path):
    source = vera_pdf(tmp_path, second='Bold line')
    with pikepdf.open(source) as pdf:
        names = {str(k): v for k, v in pdf.pages[0].Resources.Font.items() if v.get('/Subtype') == pikepdf.Name.TrueType}
    assert len(names) == 2
    first, second = sorted(names)
    path = tmp_path / 'q.pdf'
    with pikepdf.open(source) as pdf:
        pdf.pages[0].Contents = pdf.make_stream(
            f'BT {first} 12 Tf 72 700 Td (ab) Tj ET q BT {second} 12 Tf 72 680 Td (xy) Tj ET Q BT 72 660 Td (cd) Tj ET'.encode())
        pdf.save(path)
    result = screen(path)
    by_name = {f['object']: f for f in result['fonts']}
    used = sorted(font['used_codes'] for font in by_name.values())
    assert used == [2, 4] and 'text-without-font' not in result['coverage'].get('reasons', [])


def test_composite_identity_font_is_decoded_in_two_byte_codes(tmp_path):
    path, gids = type0_pdf(tmp_path)
    result = screen(path)
    assert result['status'] == 'pass', result
    [font] = result['fonts']
    assert font['subtype'] == 'Type0' and font['used_codes'] == 4 and font['reviewed_correction_available'] is True
    with pikepdf.open(path) as pdf:
        font = [o for o in pdf.objects if isinstance(o, pikepdf.Dictionary) and o.get('/Subtype') == pikepdf.Name.Type0][0]
        parsed = tounicode.parse(font['/ToUnicode'].read_bytes())
        parsed['entries'][(2, gids['f'])] = '\ue010'
        font['/ToUnicode'] = pdf.make_stream(tounicode.serialize(parsed))
        pdf.save(tmp_path / 'flag2.pdf')
    result = screen(tmp_path / 'flag2.pdf')
    [finding] = [f for f in result['findings'] if f['issue'] == 'private-use']
    assert finding['codes'][0]['width'] == 2 and finding['codes'][0]['code_hex'] == f"{gids['f']:04X}"


def test_composite_font_without_to_unicode_is_reported_once(tmp_path):
    path, _ = type0_pdf(tmp_path, with_to_unicode=False)
    result = screen(path)
    [finding] = [f for f in result['findings'] if f['issue'] == 'missing-tounicode']
    assert finding['code_count'] == 4


def test_named_cmap_other_than_identity_is_uncertain_not_decoded(tmp_path):
    path, _ = type0_pdf(tmp_path)
    with pikepdf.open(path) as pdf:
        font = [o for o in pdf.objects if isinstance(o, pikepdf.Dictionary) and o.get('/Subtype') == pikepdf.Name.Type0][0]
        font['/Encoding'] = pikepdf.Name('/UniJIS-UCS2-H')
        pdf.save(tmp_path / 'named.pdf')
    result = screen(tmp_path / 'named.pdf')
    assert result['status'] == 'needs-review'
    assert any('cannot be decoded' in reason for item in result['uncertain'] for reason in item['reasons'])


def test_unreadable_to_unicode_is_uncertain_and_blocks_a_clean_pass(tmp_path):
    path = vera_pdf(tmp_path)
    with pikepdf.open(path) as pdf:
        subset_fonts(pdf)[0]['/ToUnicode'] = pdf.make_stream(b'begincmap garbage endcmap')
        pdf.save(tmp_path / 'bad.pdf')
    result = screen(tmp_path / 'bad.pdf')
    assert result['status'] == 'needs-review'
    assert any('ToUnicode map cannot be read' in reason for item in result['uncertain'] for reason in item['reasons'])


def test_operation_limit_makes_coverage_incomplete_never_a_pass(tmp_path, monkeypatch):
    monkeypatch.setitem(meaning.LIMITS, 'operations_per_page', 3)
    result = screen(vera_pdf(tmp_path))
    assert result['coverage']['complete'] is False and 'operation-limit' in result['coverage']['reasons']
    assert result['status'] == 'needs-review'


def test_page_limit_is_reported_as_unscanned_pages(tmp_path, monkeypatch):
    path = tmp_path / 'pages.pdf'
    page = canvas.Canvas(str(path), invariant=True)
    for number in range(3):
        page.setFont('Helvetica', 12)
        page.drawString(72, 700, f'Page {number}')
        page.showPage()
    page.save()
    monkeypatch.setitem(meaning.LIMITS, 'pages', 2)
    result = screen(path)
    assert result['coverage']['pages_scanned'] == 2 and result['coverage']['pages_total'] == 3
    assert 'page-limit' in result['coverage']['reasons'] and result['status'] == 'needs-review'


def test_record_limit_is_bounded_and_reported(tmp_path, monkeypatch):
    monkeypatch.setitem(meaning.LIMITS, 'records', 1)
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: '\ue001', 0x61: '\ufffd'})
    result = screen(broken)
    assert len(result['findings']) == 1 and 'record-limit' in result['coverage']['reasons']


def test_codes_per_record_are_bounded_with_an_omitted_count(tmp_path, monkeypatch):
    monkeypatch.setitem(meaning.LIMITS, 'codes_per_record', 1)
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: '\ue001', 0x61: '\ue002'})
    [finding] = [f for f in screen(broken)['findings'] if f['issue'] == 'private-use']
    assert len(finding['codes']) == 1 and finding['omitted_codes'] == 1 and finding['code_count'] == 2


def test_cancellation_is_not_swallowed(tmp_path):
    flag = threading.Event()
    flag.set()
    with pytest.raises(InterruptedError):
        meaning.assess(vera_pdf(tmp_path), cancel=flag)


def test_a_missing_file_is_an_error_record_not_a_crash(tmp_path):
    result = meaning.assess(tmp_path / 'absent.pdf')
    assert result['status'] == 'error' and result['coverage']['complete'] is False


def test_the_input_is_never_modified_even_for_a_broken_document(tmp_path):
    broken = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: '\ue001'})
    before = broken.read_bytes()
    screen(broken)
    meaning.assess(broken)
    assert broken.read_bytes() == before


# ------------------------------------------------------------------ the check profile

def test_checks_profile_adds_an_advisory_screen_and_a_manual_item(tmp_path):
    from pdf_remediator.checks import assess
    from pdf_remediator.inspection import inspect_pdf
    clean = assess(inspect_pdf(vera_pdf(tmp_path)))
    row = next(item for item in clean['checks'] if item['id'] == 'character-meaning')
    assert row['status'] == 'pass' and row['blocking'] is False and row['severity'] == 'advisory'
    assert 'character-meaning' not in {item['id'] for item in clean['manual_queue']}
    assert 'character-meaning' in clean['coverage']['automated']
    broken = rewrite(vera_pdf(tmp_path, name='b.pdf'), tmp_path / 'broken.pdf', entries={0x65: '\ue001'})
    result = assess(inspect_pdf(broken))
    row = next(item for item in result['checks'] if item['id'] == 'character-meaning')
    assert row['status'] == 'needs-review' and row['blocking'] is False
    [item] = [m for m in result['manual_queue'] if m['id'] == 'character-meaning']
    assert item['required'] is True and item['status'] == 'pending' and item['pages'] == [1]
    assert 'never embeds or substitutes a font' in item['detail']
    assert result['status'] == clean['status'], 'an advisory screen must not change the blocking result'


def test_stored_screen_evidence_reaches_the_review_view_without_new_authority():
    from pdf_remediator import workspace
    evidence = {'policy': meaning.POLICY, 'status': 'needs-review', 'advisory': True, 'findings': [{'issue': 'private-use'}]}
    state = {'residual_issues': [], 'manual_items': [{'id': 'character-meaning', 'category': 'character-meaning',
                                                         'status': 'pending', 'detail': 'Compare each character.', 'evidence': evidence}]}
    found = workspace._repair_findings(state)
    assert found == [{'id': 'character-meaning', 'status': 'needs-review', 'evidence': evidence, 'fix_path': 'Compare each character.'}]
    assert found[0]['evidence'] is not evidence, 'the view holds a copy; stored evidence is not editable through it'


def test_a_compressed_map_that_expands_beyond_the_limit_is_refused_without_expanding_it(tmp_path):
    import zlib
    bomb = zlib.compress(b' ' * (tounicode.MAX_BYTES * 3))
    assert len(bomb) < tounicode.MAX_BYTES
    path = vera_pdf(tmp_path)
    with pikepdf.open(path) as pdf:
        stream = pdf.make_stream(bomb)
        stream['/Filter'] = pikepdf.Name.FlateDecode
        subset_fonts(pdf)[0]['/ToUnicode'] = stream
        pdf.save(tmp_path / 'bomb.pdf')
    result = screen(tmp_path / 'bomb.pdf')
    assert result['status'] == 'needs-review'
    assert any('expands beyond' in reason for item in result['uncertain'] for reason in item['reasons'])


def test_an_unsupported_stream_filter_on_a_map_is_uncertain(tmp_path):
    path = vera_pdf(tmp_path)
    with pikepdf.open(path) as pdf:
        stream = pdf.make_stream(b'ZZZZ')
        stream['/Filter'] = pikepdf.Name.ASCII85Decode
        subset_fonts(pdf)[0]['/ToUnicode'] = stream
        pdf.save(tmp_path / 'filter.pdf', stream_decode_level=pikepdf.StreamDecodeLevel.none, compress_streams=False)
    result = screen(tmp_path / 'filter.pdf')
    assert any('Flate-compressed' in reason for item in result['uncertain'] for reason in item['reasons'])
