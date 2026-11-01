"""Designed-PDF repairs: unsharing repeated page forms and repairing the engine's structure links.

Every PDF here is built in the test with pikepdf. No Java, validator, OCR or network is used; page rendering, text
extraction, structure parsing and the all-page fidelity gate are the real implementations.
"""
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name
import pypdfium2 as pdfium
import pytest

from pdf_remediator import designed_pdf as dp

TEXT = b'BT /F1 14 Tf 20 20 Td (%s) Tj ET'


def pictures(path, scale=1):
    document = pdfium.PdfDocument(str(path))
    try:
        return [(page.get_size(), page.render(scale=scale).to_pil().convert('RGB').tobytes()) for page in document]
    finally:
        document.close()


def new_pdf():
    pdf = pikepdf.new()
    return pdf, pdf.make_indirect(Dictionary(Type=Name.Font, Subtype=Name.Type1, BaseFont=Name.Helvetica))


def make_form(pdf, content, *, font=None, bbox=(0, 0, 300, 60)):
    form = pikepdf.Stream(pdf, content)
    form['/Type'], form['/Subtype'], form['/BBox'] = Name.XObject, Name.Form, Array(bbox)
    if font is not None:
        form['/Resources'] = Dictionary(Font=Dictionary(F1=font))
    return form


def add_page(pdf, content, font, forms=None):
    page = pdf.add_blank_page(page_size=(400, 300))
    page['/Resources'] = Dictionary(Font=Dictionary(F1=font), XObject=Dictionary(forms or {}))
    page['/Contents'] = pdf.make_stream(content)
    return page


def shared_forms_pdf(path):
    pdf, font = new_pdf()
    header = make_form(pdf, b'0.8 0.9 1 rg 0 0 300 60 re f 0 g ' + TEXT % b'Running header', font=font)
    inherits = make_form(pdf, b'q 1 0 0 rg 0 0 40 40 re f Q ' + TEXT % b'Inherited font')
    wrapper = make_form(pdf, b'q /Hd Do Q', font=font)
    wrapper['/Resources']['/XObject'] = Dictionary(Hd=header)
    add_page(pdf, b'q 1 0 0 1 20 220 cm /Hd Do Q ' + TEXT % b'Page one', font, {'/Hd': header, '/In': inherits})
    add_page(pdf, b'q 1 0 0 1 20 220 cm /Hd Do Q q 1 0 0 1 20 120 cm /Hd Do Q q 1 0 0 1 200 20 cm /In Do Q', font, {'/Hd': header, '/In': inherits})
    add_page(pdf, b'q 1 0 0 1 20 220 cm /Wr Do Q q 1 0 0 1 20 100 cm /Hd Do Q q 1 0 0 1 200 20 cm /In Do Q', font,
             {'/Wr': wrapper, '/Hd': header, '/In': inherits})
    pdf.save(path)


# --- unshare_forms ---------------------------------------------------------------------------------------

def test_each_repeated_use_gets_its_own_copy_and_every_page_is_identical(tmp_path):
    source = tmp_path / 'shared.pdf'
    shared_forms_pdf(source)
    with pikepdf.open(source) as pdf:
        before = dict(dp._form_uses(pdf))
    assert max(before.values()) >= 4 and sum(1 for count in before.values() if count > 1) == 2
    output = tmp_path / 'unshared.pdf'
    result = dp.unshare_forms(source, output)
    assert result['status'] == 'pass', result
    assert result['forms_unshared'] == 2 and result['copies_made'] == sum(count - 1 for count in before.values() if count > 1)
    assert result['shared_forms_left'] == 0
    assert result['visible_preservation'] == {'status': 'pass', 'pages_compared': 3,
                                              'policy': 'Every page picture, box and annotation identical; no text token added or removed.'}
    with pikepdf.open(output) as pdf:
        assert max(dp._form_uses(pdf).values()) == 1
    assert pictures(source) == pictures(output)
    assert pictures(source, 2) == pictures(output, 2)
    # The inheriting form still draws with the page's font after it was copied.
    text = pdfium.PdfDocument(str(output))[1].get_textpage().get_text_range()
    assert text.count('Running header') == 2 and 'Inherited font' in text


def test_the_original_is_never_modified_and_an_existing_output_is_refused(tmp_path):
    source = tmp_path / 'shared.pdf'
    shared_forms_pdf(source)
    original = source.read_bytes()
    output = tmp_path / 'unshared.pdf'
    dp.unshare_forms(source, output)
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError):
        dp.unshare_forms(source, output)
    with pytest.raises(FileExistsError):
        dp.unshare_forms(source, source)


def test_nothing_is_written_when_no_form_is_repeated(tmp_path):
    pdf, font = new_pdf()
    only = make_form(pdf, TEXT % b'Once', font=font)
    add_page(pdf, b'/Fm Do', font, {'/Fm': only})
    add_page(pdf, TEXT % b'Plain', font)
    source, output = tmp_path / 'once.pdf', tmp_path / 'out.pdf'
    pdf.save(source)
    assert dp.unshare_forms(source, output)['status'] == 'not-needed'
    assert not output.exists() and not list(tmp_path.glob('*partial'))


def test_a_file_with_a_structure_tree_keeps_its_forms(tmp_path):
    source = tmp_path / 'shared.pdf'
    shared_forms_pdf(source)
    with pikepdf.open(source, allow_overwriting_input=True) as pdf:
        pdf.Root['/StructTreeRoot'] = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot))
        pdf.save(source)
    result = dp.unshare_forms(source, tmp_path / 'out.pdf')
    assert result['status'] == 'not-needed' and 'already has a structure tree' in result['reason']
    assert not (tmp_path / 'out.pdf').exists()


def test_encrypted_files_and_self_drawing_forms_are_refused_without_output(tmp_path):
    source = tmp_path / 'shared.pdf'
    shared_forms_pdf(source)
    encrypted = tmp_path / 'locked.pdf'
    with pikepdf.open(source) as pdf:
        pdf.save(encrypted, encryption=pikepdf.Encryption(owner='o', user=''))
    with pikepdf.open(encrypted) as probe:
        assert probe.is_encrypted
    result = dp.unshare_forms(encrypted, tmp_path / 'a.pdf')
    assert result['status'] == 'refused' and not (tmp_path / 'a.pdf').exists()
    pdf, font = new_pdf()
    loop = make_form(pdf, b'/Self Do ' + TEXT % b'Loop', font=font)
    loop['/Resources']['/XObject'] = Dictionary(Self=loop)
    add_page(pdf, b'/Fm Do /Fm Do', font, {'/Fm': loop})
    cycle = tmp_path / 'cycle.pdf'
    pdf.save(cycle)
    result = dp.unshare_forms(cycle, tmp_path / 'b.pdf')
    assert result['status'] == 'refused' and 'draws itself' in result['reason']
    assert not (tmp_path / 'b.pdf').exists()


def test_a_failed_fidelity_gate_discards_the_copy(tmp_path, monkeypatch):
    source = tmp_path / 'shared.pdf'
    shared_forms_pdf(source)
    monkeypatch.setattr(dp, '_fidelity_gate', lambda *args, **kwargs: {'status': 'fail', 'pages_compared': 3, 'policy': 'test'})
    result = dp.unshare_forms(source, tmp_path / 'out.pdf')
    assert result['status'] == 'refused' and 'original was kept' in result['reason']
    assert not (tmp_path / 'out.pdf').exists() and not list(tmp_path.glob('*partial'))


# --- repair_tagged_output --------------------------------------------------------------------------------

def marked(mcid, words):
    return b'/P <</MCID %d>> BDC ' % mcid + TEXT % words + b' EMC '


def tagged_pdf(path, specs, *, content=None, font_cidset=False, tables=None, id_tree=False, headers=None, forms=None):
    """One page. specs: list of dict(role, mcids, alt, id). Content defaults to one marked paragraph per spec mcid < 3."""
    pdf, font = new_pdf()
    body = content if content is not None else b''.join(marked(m, b'Para %d' % m) for m in (0, 1, 2))
    page = add_page(pdf, body, font, forms(pdf, font) if forms else None)
    page['/StructParents'] = 0
    root = pdf.make_indirect(Dictionary(Type=Name.StructTreeRoot))
    document = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name.Document, P=root))
    slots, kids = {}, []
    for spec in specs:
        element = pdf.make_indirect(Dictionary(Type=Name.StructElem, S=Name('/' + spec['role']), P=document, Pg=page.obj))
        mcids = spec['mcids']
        element['/K'] = mcids[0] if len(mcids) == 1 else Array(mcids)
        if spec.get('alt'):
            element['/Alt'] = pikepdf.String(spec['alt'])
        if spec.get('id'):
            element['/ID'] = pikepdf.String(spec['id'])
        if spec.get('headers'):
            element['/A'] = Dictionary(O=Name.Table, Headers=Array([pikepdf.String(h) for h in spec['headers']]))
        kids.append(element)
        for mcid in mcids:
            slots[mcid] = element
    document['/K'] = Array(kids)
    root['/K'] = Array([document])
    size = max(slots) + 1 if slots else 0
    root['/ParentTree'] = Dictionary(Nums=Array([0, Array([slots.get(i) for i in range(size)])]))
    if id_tree:
        root['/IDTree'] = Dictionary(Names=Array([]))
    pdf.Root['/StructTreeRoot'] = root
    pdf.Root['/MarkInfo'] = Dictionary(Marked=True)
    if font_cidset:
        descriptor = pdf.make_indirect(Dictionary(Type=Name.FontDescriptor, FontName=Name('/ABCDEF+Sample'), CIDSet=pdf.make_stream(b'\xff\xff'), Flags=4))
        pdf.Root['/DebugDescriptor'] = descriptor
    pdf.save(path)
    return path


def structure_of(path):
    with pikepdf.open(path) as pdf:
        root = pdf.Root['/StructTreeRoot']
        return {'roles': [str(e['/S']) for e in root['/K'][0]['/K']],
                'alts': [str(e['/Alt']) for e in root['/K'][0]['/K'] if '/Alt' in e],
                'ids': [bytes(e['/ID']) for e in root['/K'][0]['/K'] if '/ID' in e],
                'parent': [str(v['/S']) for v in root['/ParentTree']['/Nums'][1] if v is not None]}


def repair(tmp_path, source, **options):
    return dp.repair_tagged_output(source, tmp_path / 'repaired.pdf', **options)


def test_references_to_marked_content_that_does_not_exist_are_removed(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [
        dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2]),
        dict(role='P', mcids=[7]), dict(role='H1', mcids=[9, 1000])])
    result = repair(tmp_path, source)
    assert result['status'] == 'pass', result
    assert result['dangling_removed'] == 3 and result['empty_nodes_removed'] == 2 and result['set_aside'] == []
    shape = structure_of(tmp_path / 'repaired.pdf')
    assert shape['roles'] == ['/P', '/P', '/P'] and shape['parent'] == ['/P', '/P', '/P']
    assert pictures(source) == pictures(tmp_path / 'repaired.pdf')


def test_a_placeholder_description_on_an_emptied_figure_is_set_aside_and_recorded(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2]),
                                                    dict(role='Figure', mcids=[5], alt='image 33')])
    result = repair(tmp_path, source)
    assert result['status'] == 'pass', result
    assert [(a['role'], a['description'], a['references'], a['page']) for a in result['set_aside']] == [('/Figure', 'image 33', 1, 1)]
    assert structure_of(tmp_path / 'repaired.pdf')['alts'] == []


def test_real_replacement_text_is_never_set_aside(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2]),
                                                    dict(role='Figure', mcids=[5], alt='Bar chart of enrolment by year')])
    result = repair(tmp_path, source)
    assert result['status'] == 'refused' and 'strand semantic replacement text' in result['prune_refused']
    assert 'strand semantic replacement text' in result['reason']
    assert not (tmp_path / 'repaired.pdf').exists()


def test_a_refused_prune_does_not_stop_the_other_repairs(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0], id='stray'), dict(role='P', mcids=[1]), dict(role='P', mcids=[2]),
                                                    dict(role='Figure', mcids=[5], alt='Bar chart of enrolment by year')])
    result = repair(tmp_path, source)
    assert result['status'] == 'pass' and result['dangling_removed'] == 0
    assert 'strand semantic replacement text' in result['prune_refused']
    assert [i['id'] for i in result['ids_dropped']] == ['stray']
    assert structure_of(tmp_path / 'repaired.pdf')['alts'] == ['Bar chart of enrolment by year']


def test_an_element_that_still_has_live_content_keeps_its_description(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[2]),
                                                    dict(role='Figure', mcids=[1, 6], alt='image 4')])
    result = repair(tmp_path, source)
    assert result['status'] == 'pass' and result['dangling_removed'] == 1 and result['set_aside'] == []
    assert structure_of(tmp_path / 'repaired.pdf')['alts'] == ['image 4']


def test_content_found_in_a_form_the_page_draws_is_left_alone_not_removed(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[3])],
                        content=marked(0, b'Page text') + b'/Fm Do',
                        forms=lambda pdf, font: {'/Fm': make_form(pdf, marked(3, b'Inside form'), font=font)})
    result = repair(tmp_path, source)
    assert result['status'] == 'not-needed' and result['dangling_removed'] == 0
    assert any('point at the wrong stream' in w for w in result['warnings'])


def test_an_unused_structure_id_is_dropped_only_without_an_id_tree_or_header_reference(tmp_path):
    specs = [dict(role='P', mcids=[0], id='lonely'), dict(role='P', mcids=[1]), dict(role='P', mcids=[2])]
    result = repair(tmp_path, tagged_pdf(tmp_path / 'a.pdf', specs))
    assert result['status'] == 'pass' and [i['id'] for i in result['ids_dropped']] == ['lonely']
    assert structure_of(tmp_path / 'repaired.pdf')['ids'] == []
    (tmp_path / 'repaired.pdf').unlink()
    result = repair(tmp_path, tagged_pdf(tmp_path / 'b.pdf', specs, id_tree=True))
    assert result['status'] == 'not-needed' and result['ids_dropped'] == []
    named = specs[:1] + [dict(role='TD', mcids=[1], headers=['lonely'])] + specs[2:]
    result = repair(tmp_path, tagged_pdf(tmp_path / 'c.pdf', named))
    assert result['status'] == 'not-needed' and any('table cell refers to a structure ID' in w for w in result['warnings'])


def test_cidset_lists_go_only_when_the_caller_says_so(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2])], font_cidset=True)
    assert repair(tmp_path, source)['status'] == 'not-needed'
    result = repair(tmp_path, source, remove_cidset=True)
    assert result['status'] == 'pass' and result['cidset_removed'] == ['/ABCDEF+Sample'] and result['cidset_lists'] == 1
    with pikepdf.open(tmp_path / 'repaired.pdf') as pdf:
        assert not [o for o in pdf.objects if isinstance(o, pikepdf.Dictionary) and '/CIDSet' in o]
    assert pictures(source) == pictures(tmp_path / 'repaired.pdf')


def test_existing_tags_are_only_touched_for_the_optional_font_lists(tmp_path):
    specs = [dict(role='P', mcids=[0], id='kept'), dict(role='P', mcids=[1]), dict(role='P', mcids=[7])]
    source = tagged_pdf(tmp_path / 'tagged.pdf', specs, font_cidset=True)
    assert repair(tmp_path, source, engine_made=False)['status'] == 'not-needed'
    result = repair(tmp_path, source, engine_made=False, remove_cidset=True)
    assert result['status'] == 'pass' and result['dangling_removed'] == 0 and result['ids_dropped'] == []
    shape = structure_of(tmp_path / 'repaired.pdf')
    assert shape['ids'] == [b'kept'] and len(shape['roles']) == 3


def test_a_failed_fidelity_gate_discards_the_repair(tmp_path, monkeypatch):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2]), dict(role='P', mcids=[8])])
    monkeypatch.setattr(dp, '_fidelity_gate', lambda *args, **kwargs: {'status': 'fail', 'pages_compared': 1, 'policy': 'test'})
    result = repair(tmp_path, source)
    assert result['status'] == 'refused' and 'engine output was kept' in result['reason']
    assert not (tmp_path / 'repaired.pdf').exists() and not list(tmp_path.glob('*partial'))


def test_a_file_that_needs_nothing_writes_nothing_and_an_output_is_never_overwritten(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[1]), dict(role='P', mcids=[2])])
    assert repair(tmp_path, source)['status'] == 'not-needed'
    assert not (tmp_path / 'repaired.pdf').exists()
    (tmp_path / 'repaired.pdf').write_bytes(b'x')
    with pytest.raises(FileExistsError):
        repair(tmp_path, source)
    with pytest.raises(FileExistsError):
        dp.repair_tagged_output(source, source)


def test_repeated_references_are_reported_not_guessed_at(tmp_path):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0]), dict(role='P', mcids=[0]), dict(role='P', mcids=[2], id='x')])
    result = repair(tmp_path, source)
    assert any('Ambiguous or duplicated' in w for w in result['warnings'])
    assert result['dangling_removed'] == 0
    assert [i['id'] for i in result['ids_dropped']] == ['x']


def test_the_real_gate_refuses_a_repair_that_changes_a_page(tmp_path, monkeypatch):
    source = tagged_pdf(tmp_path / 'tagged.pdf', [dict(role='P', mcids=[0], id='x'), dict(role='P', mcids=[1]), dict(role='P', mcids=[2])])
    real = dp._unused_ids

    def sabotage(pdf):
        found = real(pdf)
        page = pdf.pages[0].obj
        page['/Contents'] = pdf.make_stream(b'1 0 0 rg 0 0 90 90 re f ' + page['/Contents'].read_bytes())
        return found

    monkeypatch.setattr(dp, '_unused_ids', sabotage)
    result = repair(tmp_path, source)
    assert result['status'] == 'refused' and result['visible_preservation']['status'] == 'fail'
    assert not (tmp_path / 'repaired.pdf').exists() and not list(tmp_path.glob('*partial'))
