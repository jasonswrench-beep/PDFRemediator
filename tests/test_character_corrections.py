"""Reviewed ToUnicode corrections: what is written, what is refused, and the proofs.

All fixtures are built at run time; no external PDF, licensed font or native
tool is used. Page rendering and text extraction come from PDFium, which is
independent of the code that writes the corrected copy.
"""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest
from reportlab.pdfgen import canvas

from pdf_remediator import character_corrections as cc
from pdf_remediator import character_meaning as meaning
from pdf_remediator import tounicode
from pdf_remediator.cli import main as cli_main

from test_character_meaning import rewrite, subset_fonts, type0_pdf, vera_pdf

PUA = '\ue001'
PUA2 = '\ue002'


def page_text(path, page=0):
    document = pdfium.PdfDocument(str(path))
    try:
        text_page = document[page].get_textpage()
        try:
            return text_page.get_text_range()
        finally:
            text_page.close()
    finally:
        document.close()


def row_for(inventory, code_hex, *, font_index=0):
    fonts = [f for f in inventory['fonts'] if f['rows']]
    return next(r for r in fonts[font_index]['rows'] if r['code_hex'] == code_hex)


def build_plan(source, sets, *, by='Ada Reviewer', at='2026-11-16', font_index=0, mutate=None):
    """sets: {code_hex: text}. Returns (inventory, plan)."""
    inventory = cc.get_inventory(source)
    corrections = []
    for code_hex, text in sets.items():
        row = row_for(inventory, code_hex, font_index=font_index)
        corrections.append({'id': row['id'], 'font': row['font'], 'code_hex': row['code_hex'],
                            'previous_text_utf16be_hex': row['text_utf16be_hex'], 'text': text,
                            'fingerprint': row['fingerprint']})
    plan = {'schema': cc.PLAN_SCHEMA, 'source_sha256': inventory['source_sha256'],
            'inventory_sha256': inventory['inventory_sha256'], 'accepted_by': by, 'accepted_at': at,
            'corrections': corrections}
    if mutate:
        mutate(plan)
    return inventory, plan


def apply(source, plan, destination, **kwargs):
    return cc.create_corrected_copy(source, plan, destination, **kwargs)


def broken_pdf(tmp_path, **entries):
    entries = entries or {0x65: PUA}
    return rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries=entries)


def only_expected_files(directory, names):
    leftovers = sorted(p.name for p in Path(directory).iterdir() if p.name not in names)
    assert leftovers == [], f'unexpected leftovers: {leftovers}'


# ------------------------------------------------------------------ what is accepted

def test_a_reviewed_correction_writes_a_separate_copy_with_proofs(tmp_path):
    source = broken_pdf(tmp_path)
    original = source.read_bytes()
    assert page_text(source) == 'Caf\ue001 au lait 123'
    _, plan = build_plan(source, {'65': 'e'})
    out = tmp_path / 'fixed.pdf'
    result = apply(source, plan, out)
    assert result['status'] == 'pass', result
    assert source.read_bytes() == original, 'the original is never changed'
    assert page_text(out) == 'Cafe au lait 123'
    assert result['source_sha256'] != result['output_sha256']
    assert result['accepted_by'] == 'Ada Reviewer' and result['ai_used'] is False
    assert result['proofs']['extracted_text']['changed_characters'] == 1
    assert result['proofs']['fidelity']['pages_compared'] == 1
    assert any('visible page' in line for line in result['human_review_pending'])
    saved = json.loads(Path(result['evidence_path']).read_text(encoding='utf-8'))
    assert saved['output_sha256'] == result['output_sha256'] and saved['corrections'][0]['text'] == 'e'
    only_expected_files(tmp_path, {'source.pdf', 'broken.pdf', 'fixed.pdf', 'fixed.character-corrections.json'})


def test_only_the_named_to_unicode_entries_differ_in_the_copy(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    out = tmp_path / 'fixed.pdf'
    assert apply(source, plan, out)['status'] == 'pass'
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        old = tounicode.parse(subset_fonts(before)[0]['/ToUnicode'].read_bytes())
        new = tounicode.parse(subset_fonts(after)[0]['/ToUnicode'].read_bytes())
        assert {k: v for k, v in new['entries'].items() if old['entries'].get(k) != v} == {(1, 0x65): 'e'}
        assert new['codespaces'] == old['codespaces'] and len(new['entries']) == len(old['entries'])
        left = subset_fonts(before)[0]
        right = subset_fonts(after)[0]
        for key in ('/BaseFont', '/FirstChar', '/LastChar', '/Widths', '/FontDescriptor', '/Subtype'):
            assert str(left[key]) == str(right[key]) or key == '/FontDescriptor'
        assert (left['/FontDescriptor']['/FontFile2'].read_bytes()
                == right['/FontDescriptor']['/FontFile2'].read_bytes())
        assert before.pages[0].Contents.read_bytes() == after.pages[0].Contents.read_bytes()


def test_the_corrected_copy_screens_clean_and_the_source_still_reports_the_problem(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    out = tmp_path / 'fixed.pdf'
    assert apply(source, plan, out)['status'] == 'pass'
    assert 'private-use' in {f['issue'] for f in meaning.assess(source)['findings']}
    assert meaning.assess(out)['findings'] == []


def test_several_codes_in_two_fonts_are_corrected_together(tmp_path):
    base = vera_pdf(tmp_path, text='Cafe au lait', second='Bold face')
    source = rewrite(base, tmp_path / 'step1.pdf', entries={0x65: PUA})
    source = rewrite(source, tmp_path / 'broken.pdf', entries={0x6F: PUA2}, font_index=1)
    assert page_text(source).splitlines()[0].startswith('Caf\ue001') and '\ue002' in page_text(source)
    inventory = cc.get_inventory(source)
    sets = []
    for font in inventory['fonts']:
        for row in font['rows']:
            if row['text'] and row['flags']:
                sets.append({'id': row['id'], 'font': row['font'], 'code_hex': row['code_hex'],
                             'previous_text_utf16be_hex': row['text_utf16be_hex'],
                             'text': 'e' if row['code_hex'] == '65' else 'o', 'fingerprint': row['fingerprint']})
    assert len(sets) == 2 and len({s['font'] for s in sets}) == 2
    plan = {'schema': cc.PLAN_SCHEMA, 'source_sha256': inventory['source_sha256'],
            'inventory_sha256': inventory['inventory_sha256'], 'accepted_by': 'Ada Reviewer',
            'accepted_at': '2026-11-16T09:30:00', 'corrections': sets}
    result = apply(source, plan, tmp_path / 'fixed.pdf')
    assert result['status'] == 'pass', result
    assert page_text(tmp_path / 'fixed.pdf').replace('\r\n', '\n').splitlines() == ['Cafe au lait', 'Bold face']


def test_a_reviewed_value_may_be_several_characters(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'ee'})
    out = tmp_path / 'fixed.pdf'
    assert apply(source, plan, out)['status'] == 'pass'
    assert page_text(out) == 'Cafee au lait 123'


def test_two_codes_sharing_one_wrong_text_may_be_corrected_together_to_the_same_text(tmp_path):
    source = broken_pdf(tmp_path, **{})  # placeholder to build the base file
    source = rewrite(vera_pdf(tmp_path, name='s2.pdf'), tmp_path / 'shared.pdf', entries={0x65: PUA, 0x61: PUA})
    _, plan = build_plan(source, {'65': 'e', '61': 'e'})
    result = apply(source, plan, tmp_path / 'fixed.pdf')
    assert result['status'] == 'pass', result
    assert page_text(tmp_path / 'fixed.pdf') == 'Cefe eu leit 123'


def test_composite_font_with_two_byte_codes_is_corrected(tmp_path):
    path, gids = type0_pdf(tmp_path)
    broken = tmp_path / 'broken0.pdf'
    with pikepdf.open(path) as pdf:
        font = [o for o in pdf.objects if isinstance(o, pikepdf.Dictionary) and o.get('/Subtype') == pikepdf.Name.Type0][0]
        parsed = tounicode.parse(font['/ToUnicode'].read_bytes())
        parsed['entries'][(2, gids['f'])] = PUA
        font['/ToUnicode'] = pdf.make_stream(tounicode.serialize(parsed))
        pdf.save(broken)
    assert page_text(broken) == 'Ca\ue001e'
    _, plan = build_plan(broken, {f"{gids['f']:04X}": 'f'})
    result = apply(broken, plan, tmp_path / 'fixed0.pdf')
    assert result['status'] == 'pass', result
    assert page_text(tmp_path / 'fixed0.pdf') == 'Cafe'
    assert result['corrections'][0]['code_hex'] == f"{gids['f']:04X}"


def test_the_inventory_is_read_only_and_stable(tmp_path):
    source = broken_pdf(tmp_path)
    before = source.read_bytes()
    first, second = cc.get_inventory(source), cc.get_inventory(source)
    assert first == second and source.read_bytes() == before
    [font] = first['fonts']
    assert font['eligible'] is True and font['limits'] == [] and font['rows']
    assert any(r['flags'] == ['private-use'] and r['code_hex'] == '65' for r in font['rows'])
    json.dumps(first)


# ------------------------------------------------------------------ what is refused

def refuse(source, plan, tmp_path, match, **kwargs):
    out = tmp_path / 'refused.pdf'
    before = {p.name for p in tmp_path.iterdir()}
    result = apply(source, plan, out, **kwargs)
    assert result['status'] == 'refused', result
    assert match.lower() in result['reason'].lower(), result['reason']
    assert {p.name for p in tmp_path.iterdir()} == before, 'a refusal publishes and leaves nothing'
    return result


@pytest.mark.parametrize('mutation,match', [
    (lambda p: p.update(schema='phase2-other'), 'schema'),
    (lambda p: p.update(extra=1), 'unknown fields'),
    (lambda p: p.update(source_sha256='0' * 64), 'different source'),
    (lambda p: p.update(inventory_sha256='1' * 64), 'different source or inventory'),
    (lambda p: p.update(accepted_by=''), 'name'),
    (lambda p: p.update(accepted_by='A'), 'name'),
    (lambda p: p.update(accepted_by='Ada\x07 Reviewer'), 'name'),
    (lambda p: p.update(accepted_at='yesterday'), 'date'),
    (lambda p: p.update(accepted_at=20261116), 'date'),
    (lambda p: p.update(corrections=[]), '1 to'),
    (lambda p: p['corrections'].append(copy.deepcopy(p['corrections'][0])), 'twice'),
    (lambda p: p['corrections'][0].update(id='9:9:41'), 'not in this inventory'),
    (lambda p: p['corrections'][0].update(fingerprint='2' * 64), 'no longer matches'),
    (lambda p: p['corrections'][0].update(previous_text_utf16be_hex='0041'), 'no longer matches'),
    (lambda p: p['corrections'][0].update(note='x'), 'unknown fields'),
    (lambda p: p['corrections'][0].update(text=''), 'empty'),
    (lambda p: p['corrections'][0].update(text=PUA), 'private-use'),
    (lambda p: p['corrections'][0].update(text='\ufffd'), 'replacement'),
    (lambda p: p['corrections'][0].update(text='\x07'), 'control'),
    (lambda p: p['corrections'][0].update(text='\u202e'), 'format'),
    (lambda p: p['corrections'][0].update(text='\ud800'), 'surrogate'),
    (lambda p: p['corrections'][0].update(text='x' * 17), 'longer than'),
    (lambda p: p['corrections'][0].update(text=PUA2), 'private-use'),
    (lambda p: p['corrections'][0].update(text=7), 'empty'),
], ids=lambda value: getattr(value, '__name__', None) if not callable(value) else None)
def test_a_plan_with_any_defect_is_refused_and_publishes_nothing(tmp_path, mutation, match):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    mutation(plan)
    refuse(source, plan, tmp_path, match)


def test_a_correction_that_repeats_the_current_text_is_refused(tmp_path):
    source = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: 'e'})
    _, plan = build_plan(source, {'65': 'e'})
    refuse(source, plan, tmp_path, 'repeats the text')


def test_a_code_that_extracts_as_several_characters_is_refused(tmp_path):
    source = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: 'ab'})
    _, plan = build_plan(source, {'65': 'e'})
    refuse(source, plan, tmp_path, 'exactly one character')


def test_codes_sharing_one_wrong_text_cannot_be_split(tmp_path):
    source = rewrite(vera_pdf(tmp_path), tmp_path / 'broken.pdf', entries={0x65: PUA, 0x61: PUA})
    _, plan = build_plan(source, {'65': 'e'})
    refuse(source, plan, tmp_path, 'cannot tell them apart')
    _, split = build_plan(source, {'65': 'e', '61': 'a'})
    refuse(source, split, tmp_path, 'cannot tell them apart')


def test_a_same_named_font_object_drawing_the_same_text_blocks_the_change(tmp_path):
    source = broken_pdf(tmp_path)
    twin = tmp_path / 'twin.pdf'
    with pikepdf.open(source) as pdf:
        font = subset_fonts(pdf)[0]
        clone = pdf.make_indirect(pikepdf.Dictionary({key: font[key] for key in font.keys()}))
        clone['/BaseFont'] = pikepdf.Name('/BBBBBB+BitstreamVeraSans-Roman')
        parsed = tounicode.parse(font['/ToUnicode'].read_bytes())
        parsed['entries'][(1, 0x78)] = PUA
        clone['/ToUnicode'] = pdf.make_stream(tounicode.serialize(parsed))
        page = pdf.pages[0]
        page.Resources.Font['/F9'] = clone
        page.Contents = pdf.make_stream(page.Contents.read_bytes() + b' BT /F9 14 Tf 72 600 Td (xx) Tj ET')
        pdf.save(twin)
    inventory = cc.get_inventory(twin)
    first = next(f for f in inventory['fonts'] if f['base_font'].startswith('AAAAAA'))
    row = next(r for r in first['rows'] if r['code_hex'] == '65')
    plan = {'schema': cc.PLAN_SCHEMA, 'source_sha256': inventory['source_sha256'],
            'inventory_sha256': inventory['inventory_sha256'], 'accepted_by': 'Ada Reviewer', 'accepted_at': '2026-11-16',
            'corrections': [{'id': row['id'], 'font': row['font'], 'code_hex': '65',
                             'previous_text_utf16be_hex': row['text_utf16be_hex'], 'text': 'e', 'fingerprint': row['fingerprint']}]}
    refuse(twin, plan, tmp_path, 'same name extracts the same text')


def test_a_changed_source_makes_an_old_plan_stale(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    other = rewrite(vera_pdf(tmp_path, name='o.pdf'), tmp_path / 'other.pdf', entries={0x65: PUA, 0x61: PUA2})
    refuse(other, plan, tmp_path, 'different source')


def test_a_plan_file_with_the_wrong_hash_is_refused(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    plan_file = tmp_path / 'plan.json'
    plan_file.write_text(json.dumps(plan), encoding='utf-8')
    refuse(source, plan_file, tmp_path, 'plan changed', expected_plan_sha256='0' * 64)
    result = apply(source, plan_file, tmp_path / 'ok.pdf', expected_plan_sha256=cc._sha(plan_file))
    assert result['status'] == 'pass' and result['plan_file_sha256'] == cc._sha(plan_file)


def test_existing_destination_is_never_overwritten(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    out = tmp_path / 'fixed.pdf'
    out.write_bytes(b'precious')
    result = apply(source, plan, out)
    assert result['status'] == 'refused' and out.read_bytes() == b'precious'
    assert apply(source, plan, source)['status'] == 'refused'
    assert apply(source, plan, tmp_path / 'missing' / 'x.pdf')['status'] == 'refused'


def test_fonts_without_a_readable_map_or_embedding_have_no_editable_rows(tmp_path):
    no_map = rewrite(vera_pdf(tmp_path), tmp_path / 'nomap.pdf', remove_key=True)
    [font] = cc.get_inventory(no_map)['fonts']
    assert font['eligible'] is False and font['rows'] == [] and font['rows_withheld'] > 0
    assert any('no readable ToUnicode' in reason for reason in font['limits'])
    plain = tmp_path / 'helv.pdf'
    page = canvas.Canvas(str(plain), invariant=True)
    page.setFont('Helvetica', 12)
    page.drawString(72, 700, 'Plain')
    page.showPage()
    page.save()
    [font] = cc.get_inventory(plain)['fonts']
    assert font['eligible'] is False and any('not embedded' in reason for reason in font['limits'])


@pytest.mark.parametrize('document_limit,build', [
    ('Interactive forms', lambda pdf: pdf.Root.__setitem__('/AcroForm', pikepdf.Dictionary(Fields=pikepdf.Array()))),
    ('Signed documents', lambda pdf: pdf.Root.__setitem__('/Perms', pikepdf.Dictionary())),
])
def test_forms_and_signed_documents_are_refused(tmp_path, document_limit, build):
    source = broken_pdf(tmp_path)
    marked = tmp_path / 'marked.pdf'
    with pikepdf.open(source) as pdf:
        build(pdf)
        pdf.save(marked)
    inventory = cc.get_inventory(marked)
    assert any(document_limit in reason for reason in inventory['document_limits'])
    assert all(not font['eligible'] and font['rows'] == [] for font in inventory['fonts'])
    refuse(marked, {}, tmp_path, 'cannot be corrected')


def test_encrypted_documents_are_refused(tmp_path):
    source = broken_pdf(tmp_path)
    locked = tmp_path / 'locked.pdf'
    with pikepdf.open(source) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(owner='o', user=''))
    result = apply(locked, {}, tmp_path / 'x.pdf')
    assert result['status'] == 'refused'


def test_correction_limits_name_each_reason():
    facts = {'object': 'direct-1', 'subtype': 'Type1', 'embedded': False, 'cmap_encoding': '', 'descendant_subtype': '',
             'to_unicode': 'absent', 'parsed': None}
    reasons = meaning.correction_limits(facts, ['Signed documents need a separately selected workflow.'])
    text = ' '.join(reasons)
    for expected in ('shared indirect object', 'not embedded', 'no readable ToUnicode', 'Signed documents'):
        assert expected in text
    composite = {**facts, 'object': '5:0', 'subtype': 'Type0', 'embedded': True, 'cmap_encoding': 'UniJIS-UCS2-H',
                 'descendant_subtype': 'CIDFontType2', 'to_unicode': 'present',
                 'parsed': {'entries': {(2, 1): 'a'}}}
    assert any('Identity-H/V' in reason for reason in meaning.correction_limits(composite, []))


@pytest.mark.parametrize('text,ok', [('e', True), ('\u00e9', True), ('fi', True), (' ', True), ('\u0301', True),
                                     ('', False), ('\x00', False), ('\u200b', False), ('\u202e', False),
                                     ('\ue000', False), ('\ufffd', False), ('\U000f0000', False), ('\u0378', False),
                                     ('\ud800', False), (None, False), (5, False)])
def test_reviewed_text_rules(text, ok):
    assert (cc.reviewed_text_problem(text) is None) is ok


# ------------------------------------------------------------------ the independent proofs

def test_graph_comparison_ignores_object_numbering_but_not_content(tmp_path):
    source = broken_pdf(tmp_path)
    renumbered = tmp_path / 'renumbered.pdf'
    with pikepdf.open(source) as pdf:
        junk = pdf.make_indirect(pikepdf.Dictionary(Junk=1))  # unreachable object shifts numbers on save
        pdf.save(renumbered, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    with pikepdf.open(source) as a, pikepdf.open(renumbered) as b:
        assert cc.canonical_graph(a)[0] == cc.canonical_graph(b)[0]
    changed = tmp_path / 'changed.pdf'
    with pikepdf.open(source) as pdf:
        pdf.pages[0].Contents = pdf.make_stream(pdf.pages[0].Contents.read_bytes() + b' ')
        pdf.save(changed)
    with pikepdf.open(source) as a, pikepdf.open(changed) as b:
        left, right = cc.canonical_graph(a)[0], cc.canonical_graph(b)[0]
        assert left != right and 'differs' in cc._diff_summary(left, right)
    widths = tmp_path / 'widths.pdf'
    with pikepdf.open(source) as pdf:
        font = subset_fonts(pdf)[0]
        font['/Widths'][5] = 777
        pdf.save(widths)
    with pikepdf.open(source) as a, pikepdf.open(widths) as b:
        assert cc.canonical_graph(a)[0] != cc.canonical_graph(b)[0]


def test_a_stream_filter_change_alone_is_not_a_content_change(tmp_path):
    source = broken_pdf(tmp_path)
    compressed = tmp_path / 'compressed.pdf'
    with pikepdf.open(source) as pdf:
        pdf.save(compressed, compress_streams=True, recompress_flate=True)
    with pikepdf.open(source) as a, pikepdf.open(compressed) as b:
        assert cc.canonical_graph(a)[0] == cc.canonical_graph(b)[0]


def test_the_graph_proof_catches_an_extra_change_made_next_to_a_reviewed_one(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    good = tmp_path / 'good.pdf'
    assert apply(source, plan, good)['status'] == 'pass'
    tampered = tmp_path / 'tampered.pdf'
    with pikepdf.open(good) as pdf:
        pdf.pages[0].MediaBox = pikepdf.Array([0, 0, 600, 792])
        pdf.save(tampered)
    with pikepdf.open(source) as original, pikepdf.open(tampered) as saved:
        edited = {subset_fonts(original)[0].objgen}
        left, left_index, found = cc.canonical_graph(original, edited_keys=edited)
        right, _, _ = cc.canonical_graph(saved, edited_indexes=set(found))
        assert left != right
    with pikepdf.open(source) as original, pikepdf.open(good) as saved:
        left, _, found = cc.canonical_graph(original, edited_keys={subset_fonts(original)[0].objgen})
        right, _, _ = cc.canonical_graph(saved, edited_indexes=set(found))
        assert left == right, 'only the edited ToUnicode differs in a good copy'
        unmarked, _, _ = cc.canonical_graph(saved)
        assert unmarked != cc.canonical_graph(original)[0]


def test_the_pixel_proof_refuses_any_visible_difference(tmp_path):
    source = broken_pdf(tmp_path)
    other = rewrite(vera_pdf(tmp_path, text='Cafe au lait 124', name='o.pdf'), tmp_path / 'o2.pdf', entries={0x65: PUA})
    with pytest.raises(cc.CorrectionError, match='render exactly'):
        cc._check_fidelity(source, other, None)


def test_the_text_proof_allows_only_the_edited_font_and_code(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    good = tmp_path / 'good.pdf'
    assert apply(source, plan, good)['status'] == 'pass'
    plain = 'BitstreamVeraSans-Roman'
    assert cc._text_proof(source, good, {plain: {PUA: 'e'}})[0]['after'] == 'e'
    with pytest.raises(cc.CorrectionError, match='somewhere other than'):
        cc._text_proof(source, good, {plain: {PUA: 'x'}})
    with pytest.raises(cc.CorrectionError, match='somewhere other than'):
        cc._text_proof(source, good, {'SomeOtherFont': {PUA: 'e'}})
    with pytest.raises(cc.CorrectionError, match='would not correct anything'):
        cc._text_proof(source, source, {plain: {'Z': 'e'}})


def test_every_proof_failure_publishes_nothing(tmp_path, monkeypatch):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    for name in ('_text_proof', '_check_fidelity'):
        def fail(*args, **kwargs):
            raise cc.CorrectionError('seeded proof failure')
        monkeypatch.setattr(cc, name, fail)
        refuse(source, plan, tmp_path, 'seeded proof failure')
        monkeypatch.undo()
    monkeypatch.setattr(cc, 'canonical_graph', lambda *a, **k: ([{'a': 1}], {}, {})
                        if k.get('edited_keys') is not None else ([{'a': 2}], {}, {}))
    refuse(source, plan, tmp_path, 'edited font was not found')


def test_a_writer_that_changes_another_entry_is_caught_by_the_read_back(tmp_path, monkeypatch):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    real = tounicode.serialize

    def sneaky(parsed):
        sneaked = copy.deepcopy(parsed)
        sneaked['entries'][(1, 0x61)] = 'q'
        return real(sneaked)
    monkeypatch.setattr(cc.tounicode, 'serialize', sneaky)
    refuse(source, plan, tmp_path, 'read back')


def test_cancellation_leaves_nothing_behind(tmp_path):
    source = broken_pdf(tmp_path)
    _, plan = build_plan(source, {'65': 'e'})
    flag = threading.Event()
    flag.set()
    before = {p.name for p in tmp_path.iterdir()}
    with pytest.raises(InterruptedError):
        apply(source, plan, tmp_path / 'fixed.pdf', cancel=flag)
    assert {p.name for p in tmp_path.iterdir()} == before


# ------------------------------------------------------------------ command line

def test_command_line_inventory_plan_and_apply(tmp_path, capsys):
    source = broken_pdf(tmp_path)
    inventory_file = tmp_path / 'inventory.json'
    assert cli_main(['characters', 'inventory', str(source), '-o', str(inventory_file)]) == 0
    inventory = json.loads(inventory_file.read_text(encoding='utf-8'))
    row = next(r for f in inventory['fonts'] for r in f['rows'] if r['code_hex'] == '65')
    plan_file = tmp_path / 'plan.json'
    assert cli_main(['characters', 'plan', str(source), '--accepted-by', 'Ada Reviewer', '--accepted-at', '2026-11-16',
                     '--set', row['id'] + '=U+0065', '-o', str(plan_file)]) == 0
    plan = json.loads(plan_file.read_text(encoding='utf-8'))
    assert plan['corrections'][0]['text'] == 'e' and plan['accepted_by'] == 'Ada Reviewer'
    capsys.readouterr()
    out = tmp_path / 'fixed.pdf'
    assert cli_main(['characters', 'apply', str(source), '--plan', str(plan_file), '--plan-sha256', cc._sha(plan_file),
                     '-o', str(out)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'pass' and page_text(out) == 'Cafe au lait 123'
    assert cli_main(['characters', 'apply', str(source), '--plan', str(plan_file), '-o', str(out)]) == 1


def test_command_line_refuses_an_unknown_row_and_never_overwrites_a_plan(tmp_path, capsys):
    source = broken_pdf(tmp_path)
    plan_file = tmp_path / 'plan.json'
    args = ['characters', 'plan', str(source), '--accepted-by', 'Ada Reviewer', '--accepted-at', '2026-11-16', '-o', str(plan_file)]
    assert cli_main(args + ['--set', '9:9:41=a']) == 1 and not plan_file.exists()
    assert 'Unknown row id' in capsys.readouterr().err
    inventory = cc.get_inventory(source)
    row = next(r for f in inventory['fonts'] for r in f['rows'] if r['code_hex'] == '65')
    assert cli_main(args + ['--set', row['id'] + '=e']) == 0
    assert cli_main(args + ['--set', row['id'] + '=e']) == 1


def test_a_source_with_object_streams_is_corrected_and_proved_the_same_way(tmp_path):
    base = broken_pdf(tmp_path)
    packed = tmp_path / 'packed.pdf'
    with pikepdf.open(base) as pdf:
        pdf.save(packed, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    assert page_text(packed) == 'Caf au lait 123'
    _, plan = build_plan(packed, {'65': 'e'})
    result = apply(packed, plan, tmp_path / 'fixed-packed.pdf')
    assert result['status'] == 'pass', result
    assert page_text(tmp_path / 'fixed-packed.pdf') == 'Cafe au lait 123'
