"""Independent literal AcroForm fixtures and exact reviewed metadata changes."""
from __future__ import annotations

import copy
from decimal import Decimal
import json

import pikepdf
import pytest

from pdf_remediator import form_edits as forms, sidecar, structure_edits as graph

OLD = [sidecar.LEGACY_INVENTORY_PROFILE, sidecar.STRUCTURAL_INVENTORY_PROFILE,
       sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE, sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE,
       sidecar.NAVIGATION_INVENTORY_PROFILE, sidecar.SEMANTIC_TREE_INVENTORY_PROFILE,
       sidecar.TABLE_INVENTORY_PROFILE]


def form_pdf(path, *, nested=False, separate=False, hazard=None, tooltip=None, source_version='1.3', omit_optional=False, mirror=False, version_metadata=None):
    pdf = pikepdf.Pdf.new(); page = pdf.add_blank_page(page_size=(400, 500))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
        BaseFont=pikepdf.Name.Helvetica, Encoding=pikepdf.Name.WinAnsiEncoding))
    resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F0=font)); page.Resources = resources
    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    doc = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
    group = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Div, P=doc, Pg=page.obj))
    fields = []; widgets = []; owners = []; commands = []
    def appearance(text, width=120):
        stream = pdf.make_stream(('q BT /F0 10 Tf 4 8 Td (' + text + ') Tj ET Q').encode())
        stream.Type = pikepdf.Name.XObject; stream.Subtype = pikepdf.Name.Form
        stream.BBox = pikepdf.Array([0, 0, width, 24]); stream.Resources = resources
        return stream
    for index, (name, ft, value) in enumerate([('Name', 'Tx', 'Original filled text'), ('Delivery', 'Ch', 'Online'), ('Consent', 'Btn', None)]):
        y = 400 - index * 90
        field = pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name('/' + ft), T=name, Ff=0))
        if tooltip is not None: field.TU = pikepdf.String(tooltip)
        if ft == 'Tx': field.V = value; field.DV = 'Original default'
        elif ft == 'Ch': field.Opt = pikepdf.Array(['Online', 'In person']); field.V = value; field.DV = 'In person'
        else: field.V = pikepdf.Name.Yes; field.DV = pikepdf.Name.Off
        widget = pdf.make_indirect(pikepdf.Dictionary(Parent=field)) if separate else field
        widget.Type = pikepdf.Name.Annot; widget.Subtype = pikepdf.Name.Widget; widget.P = page.obj
        widget.Rect = pikepdf.Array([150, y - 5, 270, y + 19]); widget.F = 4; widget.StructParent = index + 1
        if ft == 'Btn':
            widget.AP = pikepdf.Dictionary(N=pikepdf.Dictionary(Off=appearance(''), Yes=appearance('X'))); widget.AS = pikepdf.Name.Yes
        else: widget.AP = pikepdf.Dictionary(N=appearance(value))
        if separate: field.Kids = pikepdf.Array([widget])
        owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Form, P=group, Pg=page.obj))
        objr = pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=widget, Pg=page.obj)
        owner.K = pikepdf.Array([index, objr]); owner.Alt = pikepdf.String('Original form alternative ' + str(index))
        fields.append(field); widgets.append(widget); owners.append(owner)
        commands.append('/Form <</MCID ' + str(index) + '>> BDC BT /F0 11 Tf 30 ' + str(y) + ' Td (' + name + ') Tj ET EMC')
    if mirror:
        assert separate
        widget = pdf.make_indirect(pikepdf.Dictionary(widgets[0])); widget.StructParent = 4
        widget.Rect = pikepdf.Array([150, 120, 270, 144]); fields[0].Kids.append(widget)
        owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Form, P=group, Pg=page.obj,
            K=pikepdf.Array([3, pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=widget, Pg=page.obj)]), Alt='Original repeated text view'))
        widgets.append(widget); owners.append(owner)
        commands.append('/Form <</MCID 3>> BDC BT /F0 11 Tf 30 130 Td (Name repeated) Tj ET EMC')
    group.K = pikepdf.Array([owners[2], owners[0], owners[1], *owners[3:]]); doc.K = group; root.K = doc
    page.Contents = pdf.make_stream('\n'.join(commands).encode()); page.Annots = pikepdf.Array(widgets); page.StructParents = 0; page.Tabs = pikepdf.Name.R
    root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array(owners), *[value for index, owner in enumerate(owners, 1) for value in [index, owner]]])))
    root.ParentTreeNextKey = len(owners) + 1
    if nested:
        parent = pdf.make_indirect(pikepdf.Dictionary(T='Registration', TU='Ancestor diagnostic only', FT=pikepdf.Name.Tx, Ff=2, Kids=pikepdf.Array(fields)))
        for field in fields: field.Parent = parent; del field.Ff
        del fields[0].FT
        roots = pikepdf.Array([parent])
    else: roots = pikepdf.Array(fields)
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=roots, NeedAppearances=False, CO=pikepdf.Array(),
        DR=resources, DA='/F0 10 Tf 0 g')
    pdf.Root.StructTreeRoot = root; pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True); pdf.Root.Lang = 'en-US'
    if omit_optional:
        del root.ParentTreeNextKey
        for widget in widgets: del widget.P
    pdf.docinfo.Title = 'Authored AcroForm control'; pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
    if version_metadata is not None:
        metadata = pdf.make_stream(('<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" xmlns:pdf="http://ns.adobe.com/pdf/1.3/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:xmp="http://ns.adobe.com/xap/1.0/"><pdf:PDFVersion>' + version_metadata + '</pdf:PDFVersion><dc:title><rdf:Alt><rdf:li xml:lang="x-default">Authored AcroForm control</rdf:li></rdf:Alt></dc:title><dc:description>Keep the original description</dc:description><xmp:CreatorTool>Original source generator</xmp:CreatorTool></rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>').encode())
        metadata.Type = pikepdf.Name.Metadata; metadata.Subtype = pikepdf.Name.XML
        pdf.Root.Metadata = metadata
    if hazard == 'xfa': pdf.Root.AcroForm.XFA = 'Unsupported XFA'
    elif hazard == 'actions': fields[0].AA = pikepdf.Dictionary(K=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS='ignored'))
    elif hazard == 'calculation': pdf.Root.AcroForm.CO = pikepdf.Array([fields[0]])
    elif hazard == 'radio': fields[2].Ff = 1 << 15
    elif hazard == 'pushbutton': fields[2].Ff = 1 << 16
    elif hazard == 'password': fields[0].Ff = 1 << 13
    elif hazard == 'signature': fields[0].FT = pikepdf.Name.Sig
    elif hazard == 'need-appearances': pdf.Root.AcroForm.NeedAppearances = True
    elif hazard == 'missing-appearance': del widgets[0].AP
    elif hazard == 'state': widgets[2].AS = pikepdf.Name.Off
    elif hazard == 'orphan': page.Annots.append(pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget, Rect=pikepdf.Array([0, 0, 10, 10]))))
    elif hazard == 'unlinked': owners[0].K = pikepdf.Array([0])
    elif hazard == 'parent-tree': root.ParentTree.Nums[3] = owners[1]
    elif hazard == 'field-alias': pdf.Root.PrivateFieldAlias = fields[0]
    elif hazard == 'owner-alias': pdf.Root.PrivateOwnerAlias = owners[0]
    elif hazard == 'array-alias': pdf.Root.PrivateOrderAlias = group.K
    elif hazard == 'unknown-field': fields[0].DeveloperMeaning = 'Unknown authority'
    elif hazard == 'unknown-widget': widgets[0].DeveloperWidget = 'Unknown authority'
    elif hazard == 'unknown-acroform': pdf.Root.AcroForm.DeveloperCalculation = 'Unknown authority'
    elif hazard == 'direct-action': pdf.Root.AcroForm.DR.Properties = pikepdf.Dictionary(Nested=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS='Unknown nested action'))
    elif hazard == 'direct-signature': pdf.Root.AcroForm.DR.Properties = pikepdf.Dictionary(Nested=pikepdf.Dictionary(Type=pikepdf.Name.Sig, ByteRange=pikepdf.Array([0, 1, 2, 3])))
    elif hazard == 'owner-attributes': owners[0].A = pikepdf.Dictionary(O=pikepdf.Name.PrintField, Desc='Protected source field name')
    elif hazard == 'ancestor-alternative': group.Alt = 'Protected original group alternative'
    elif hazard == 'nested-link':
        key = root.ParentTreeNextKey
        annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            P=page.obj, Rect=pikepdf.Array([30, 30, 120, 45]), F=4, StructParent=key,
            Dest=pikepdf.Array([page.obj, pikepdf.Name.Fit]), Contents='Related local destination'))
        link = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Link,
            P=owners[0], Pg=page.obj, Alt='Related local destination',
            K=pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=annotation, Pg=page.obj)))
        owners[0].K.append(link); page.Annots.append(annotation)
        root.ParentTree.Nums.extend([key, link]); root.ParentTreeNextKey = key + 1
    elif hazard in {'descendant-label-alternative', 'descendant-label-role'}:
        label = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.P if hazard == 'descendant-label-alternative' else pikepdf.Name.Figure,
            P=owners[0], Pg=page.obj, K=0))
        if hazard == 'descendant-label-alternative': label.Alt = 'Protected label alternative'
        owners[0].K[0] = label; root.ParentTree.Nums[1][0] = label
    elif hazard == 'nontext-label':
        commands[0] = '/Form <</MCID 0>> BDC 30 400 80 12 re f EMC'
        page.Contents = pdf.make_stream('\n'.join(commands).encode())

    elif hazard is not None: raise ValueError('Unknown authored hazard')
    with path.open('xb') as stream: pdf.save(stream, min_version=source_version, deterministic_id=True, fix_metadata_version=False)
    return path


def inventory(path, profile=sidecar.FORM_INVENTORY_PROFILE):
    return sidecar.collect_decisions(path, inventory_profile=profile)


def choose(data):
    rows = [row for row in data['decisions'] if row['kind'] == 'form-controls']
    assert len(rows) == 1
    return rows[0]


def accepted(data):
    row = choose(data); assert row['structural_eligible'], row['structural_limitations']
    value = json.loads(row['current'])
    for index, field in enumerate(value['fields']):
        field['tooltip'] = 'Explicit reviewed field label ' + str(index)
        for widget in field['widgets']: widget['alternative'] = 'Explicit reviewed Form description ' + str(index)
    for page in value['pages']: page['tabs'] = 'S'
    for order in value['orders']: order['children'].reverse()
    row['value'] = forms.canonical_value(value); sidecar.bind_approval(row, 'Developer form reviewer', '2026-10-27')
    return row


@pytest.mark.parametrize('nested,separate', [(False, False), (True, False), (False, True), (True, True)])
def test_complete_form_plan_preserves_values_appearances_field_and_annotation_identity(tmp_path, nested, separate):
    source = form_pdf(tmp_path / 'source.pdf', nested=nested, separate=separate); original = source.read_bytes()
    data = inventory(source); row = accepted(data); plan = json.loads(row['value']); out = tmp_path / 'out.pdf'
    result = sidecar.apply_decisions(source, out, data, data['source_sha256'])
    assert result['changed'] == [row['id']] and source.read_bytes() == original
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        assert after.pdf_version == '1.7'
        old_fields = before.Root.AcroForm.Fields[0].Kids if nested else before.Root.AcroForm.Fields
        new_fields = after.Root.AcroForm.Fields[0].Kids if nested else after.Root.AcroForm.Fields
        for old, new in zip(old_fields, new_fields):
            assert bytes(old.T) == bytes(new.T) and old.get('/V') == new.get('/V') and old.get('/DV') == new.get('/DV')
            assert old.get('/Ff') == new.get('/Ff') and old.get('/FT') == new.get('/FT')
            assert str(new.TU).startswith('Explicit reviewed field label')
            ow = old.Kids[0] if separate else old; nw = new.Kids[0] if separate else new
            assert list(ow.Rect) == list(nw.Rect) and ow.F == nw.F and ow.get('/AS') == nw.get('/AS')
            assert forms.canonical_snapshot(graph._snapshot(before)) != forms.canonical_snapshot(graph._snapshot(after))
        assert [bytes(x.T) if '/T' in x else bytes(x.Parent.T) for x in before.pages[0].Annots] == [bytes(x.T) if '/T' in x else bytes(x.Parent.T) for x in after.pages[0].Annots]
        assert after.pages[0].Tabs == pikepdf.Name.S
        if nested: assert bytes(before.Root.AcroForm.Fields[0].TU) == bytes(after.Root.AcroForm.Fields[0].TU)
    fresh = choose(inventory(out)); assert json.loads(fresh['current'])['fields'][0]['tooltip'] == plan['fields'][0]['tooltip']


def test_seven_old_inventory_profiles_are_not_expanded_by_new_form_support(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf'); new = inventory(source)
    previous = inventory(source, sidecar.TABLE_INVENTORY_PROFILE)
    assert [row for row in new['decisions'] if row['kind'] != 'form-controls'] == previous['decisions']
    for profile in OLD:
        old = inventory(source, profile)
        assert not any(row['kind'] == 'form-controls' for row in old['decisions'])
        assert old == inventory(source, profile)


def test_parent_tooltip_is_never_inherited_as_terminal_accessible_name(tmp_path):
    row = choose(inventory(form_pdf(tmp_path / 'source.pdf', nested=True)))
    assert row['structural_eligible'], row['structural_limitations']
    assert all(field['tooltip'] is None for field in row['form_context']['fields'])
    assert [field['field_type'] for field in row['form_context']['fields']] == ['Tx', 'Ch', 'Btn']
    assert all(field['flags'] == 2 for field in row['form_context']['fields'])


def test_absent_optional_next_key_and_annotation_page_pointer_remain_absent(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf', omit_optional=True); data = inventory(source); accepted(data)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        assert '/ParentTreeNextKey' not in pdf.Root.StructTreeRoot
        assert all('/P' not in widget for widget in pdf.pages[0].Annots)


def test_one_terminal_tooltip_is_shared_across_uniquely_proven_text_widget_views(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf', separate=True, mirror=True); data = inventory(source); row = accepted(data)
    assert len(row['form_context']['fields']) == 3
    assert [len(field['widgets']) for field in row['form_context']['fields']] == [2, 1, 1]
    first = row['form_context']['fields'][0]
    assert len({widget['element'] for widget in first['widgets']}) == 2
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        old = before.Root.AcroForm.Fields[0]; new = after.Root.AcroForm.Fields[0]
        assert len(new.Kids) == 2 and str(new.TU) == 'Explicit reviewed field label 0'
        assert new.V == old.V and all(widget.Parent == new for widget in new.Kids)
        assert new.Kids[0].AP.N == new.Kids[1].AP.N


@pytest.mark.parametrize('hazard', ['xfa', 'actions', 'calculation', 'radio', 'pushbutton', 'password', 'signature',
    'need-appearances', 'missing-appearance', 'state', 'orphan', 'unlinked', 'parent-tree',
    'field-alias', 'owner-alias', 'array-alias', 'unknown-field', 'unknown-widget', 'unknown-acroform',
    'direct-action', 'direct-signature', 'owner-attributes', 'ancestor-alternative', 'nested-link', 'nontext-label', 'descendant-label-alternative', 'descendant-label-role'])
def test_unsupported_form_semantics_or_aliases_are_readonly(tmp_path, hazard):
    source = form_pdf(tmp_path / 'source.pdf', hazard=hazard); raw = source.read_bytes()
    row = choose(inventory(source)); assert not row['structural_eligible'] and row['structural_limitations']
    with pytest.raises(sidecar.DecisionError): sidecar.bind_approval(row, 'Developer', '2026-10-27')
    assert source.read_bytes() == raw


@pytest.mark.parametrize('case', ['missing-field', 'duplicate-widget', 'rename-field', 'null-tooltip', 'blank-tooltip',
    'long-tooltip', 'nul-tooltip', 'bad-alternative', 'wrong-tabs', 'missing-order', 'foreign-child', 'ineffective-order'])
def test_malformed_or_incomplete_whole_form_plans_are_typed_refusals(tmp_path, case):
    row = choose(inventory(form_pdf(tmp_path / 'source.pdf', tooltip='Original accessible name' if case == 'null-tooltip' else None))); value = json.loads(row['current'])
    if case == 'missing-field': value['fields'].pop()
    elif case == 'duplicate-widget': value['fields'][0]['widgets'].append(copy.deepcopy(value['fields'][0]['widgets'][0]))
    elif case == 'rename-field': value['fields'][0]['field'] = 'foreign:0'
    elif case == 'null-tooltip': value['fields'][0]['tooltip'] = None
    elif case == 'blank-tooltip': value['fields'][0]['tooltip'] = '  '
    elif case == 'long-tooltip': value['fields'][0]['tooltip'] = 'x' * 4001
    elif case == 'nul-tooltip': value['fields'][0]['tooltip'] = 'New\x00label'
    elif case == 'bad-alternative': value['fields'][0]['widgets'][0]['alternative'] = []
    elif case == 'wrong-tabs': value['pages'][0]['tabs'] = 'C'
    elif case == 'missing-order': value['orders'].pop()
    elif case == 'foreign-child': value['orders'][0]['children'][0] = 'foreign:0'
    elif case == 'ineffective-order': value['orders'][0]['children'].reverse()
    row['value'] = forms.canonical_value(value)
    with pytest.raises(sidecar.DecisionError): sidecar.bind_approval(row, 'Developer', '2026-10-27')


@pytest.mark.parametrize('tooltip', ['Original\r\nmultiline\r\nname', 'Original ' + 'x' * 4001])
def test_unchanged_raw_tooltips_survive_other_explicit_form_changes(tmp_path, tooltip):
    source = form_pdf(tmp_path / 'source.pdf', tooltip=tooltip); data = inventory(source); row = choose(data)
    assert row['structural_eligible'], row['structural_limitations']
    value = json.loads(row['current']); value['fields'][1]['widgets'][0]['alternative'] = 'A separately reviewed alternative'
    row['value'] = forms.canonical_value(value); sidecar.bind_approval(row, 'Developer', '2026-10-27')
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        assert [bytes(field.TU) for field in before.Root.AcroForm.Fields] == [bytes(field.TU) for field in after.Root.AcroForm.Fields]


def test_exact_original_plan_withdrawal_is_a_byte_copy_and_never_repairs_source(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf'); data = inventory(source); row = choose(data)
    sidecar.bind_approval(row, 'Developer', '2026-10-27'); out = tmp_path / 'out.pdf'
    result = sidecar.apply_decisions(source, out, data, data['source_sha256'])
    assert not result['changed'] and out.read_bytes() == source.read_bytes()


def test_resealed_capability_change_and_automatic_authority_cannot_authorize_forms(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf'); data = inventory(source); accepted(data)
    row = choose(data); row['form_context']['fields'][0]['name'] = 'Tampered'; row['approval_sha256'] = sidecar.approval_digest(row)
    with pytest.raises(sidecar.DecisionError): sidecar.apply_decisions(source, tmp_path / 'tampered.pdf', data, data['source_sha256'])
    data = inventory(source); row = accepted(data); row['status'] = 'auto-accepted'
    with pytest.raises(sidecar.DecisionError): sidecar.apply_decisions(source, tmp_path / 'automatic.pdf', data, data['source_sha256'])


@pytest.mark.parametrize('version', ['1.3', '2.0'])
def test_reopened_form_proof_rejects_underdeclared_or_downgraded_header(tmp_path, version):
    source = form_pdf(tmp_path / 'source.pdf', source_version=version); data = inventory(source); row = accepted(data)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    desired = '2.0' if version == '2.0' else '1.7'; assert out.read_bytes().startswith(('%PDF-' + desired).encode())
    raw = out.read_bytes(); lower = '1.7' if version == '2.0' else '1.3'
    tampered = tmp_path / 'lower.pdf'; tampered.write_bytes(('%PDF-' + lower).encode() + raw[len('%PDF-' + desired):])
    with pytest.raises(sidecar.DecisionError, match='insufficient PDF version'):
        graph.verify_output(source, tampered, [], other_changes=[row])


@pytest.mark.parametrize('kind,new_value', [('title', 'A separately reviewed form title'), ('language', 'fr-FR')])
def test_metadata_only_new_form_save_preserves_unselected_xmp_version_and_form_graph(tmp_path, kind, new_value):
    source = form_pdf(tmp_path / 'source.pdf', version_metadata='1.0'); original = source.read_bytes()
    data = inventory(source); form = choose(data)
    assert form['value'] == form['current'] and form['status'] == 'pending'
    item = next(item for item in data['decisions'] if item['kind'] == kind)
    item['value'] = new_value; sidecar.bind_approval(item, 'Developer', '2026-10-27')
    out = tmp_path / 'out.pdf'; result = sidecar.apply_decisions(source, out, data, data['source_sha256'])
    assert result['changed'] == [item['id']] and source.read_bytes() == original
    graph.verify_output(source, out, [], other_changes=[item])
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        assert before.pdf_version == after.pdf_version == '1.3'
        assert [bytes(field.T) for field in before.Root.AcroForm.Fields] == [bytes(field.T) for field in after.Root.AcroForm.Fields]
        assert [field.get('/TU') for field in before.Root.AcroForm.Fields] == [field.get('/TU') for field in after.Root.AcroForm.Fields]
        assert before.pages[0].Tabs == after.pages[0].Tabs == pikepdf.Name.R
        with after.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            assert metadata['pdf:PDFVersion'] == '1.0'
            assert metadata['dc:description'] == 'Keep the original description'
            assert metadata['xmp:CreatorTool'] == 'Original source generator'
        if kind == 'title': assert str(after.docinfo.Title) == new_value
        else: assert str(after.Root.Lang) == new_value


def test_older_form_profile_keeps_its_existing_metadata_version_save_behavior(tmp_path):
    source = form_pdf(tmp_path / 'source.pdf', version_metadata='1.0')
    data = inventory(source, sidecar.TABLE_INVENTORY_PROFILE)
    item = next(item for item in data['decisions'] if item['kind'] == 'title')
    item['value'] = 'Older scoped metadata-only title'; sidecar.bind_approval(item, 'Developer', '2026-10-27')
    out = tmp_path / 'old-profile.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            assert metadata['pdf:PDFVersion'] == pdf.pdf_version == '1.3'


def test_nonform_new_profile_keeps_its_existing_metadata_version_save_behavior(tmp_path):
    source = tmp_path / 'ordinary.pdf'
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(300, 400)); pdf.docinfo.Title = 'Original plain document'
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            metadata['pdf:PDFVersion'] = '1.0'; metadata['dc:title'] = 'Original plain document'
        with source.open('xb') as stream: pdf.save(stream, min_version='1.3', fix_metadata_version=False, deterministic_id=True)
    data = inventory(source)
    assert not any(item['kind'] == 'form-controls' for item in data['decisions'])
    item = next(item for item in data['decisions'] if item['kind'] == 'title')
    item['value'] = 'Ordinary metadata-only title'; sidecar.bind_approval(item, 'Developer', '2026-10-27')
    out = tmp_path / 'ordinary-out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            assert metadata['pdf:PDFVersion'] == pdf.pdf_version == '1.3'


def inert_pdf(path, *, variant='resources', no_acro=False):
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(300, 400)); pdf.docinfo.Title = 'Legacy empty form container'
        encoding = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Encoding,
            Differences=pikepdf.Array([24, pikepdf.Name.breve, pikepdf.Name.caron, 128, pikepdf.Name.bullet])))
        helv = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.Helvetica, Name=pikepdf.Name.Helv, Encoding=encoding))
        ding = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name.ZapfDingbats, Name=pikepdf.Name.ZaDb))
        resource = pikepdf.Dictionary(Font=pikepdf.Dictionary(Helv=helv, ZaDb=ding),
            Encoding=pikepdf.Dictionary(PDFDocEncoding=encoding))
        fields = pdf.make_indirect(pikepdf.Array())
        acro = pdf.make_indirect(pikepdf.Dictionary(Fields=fields))
        if variant != 'bare': acro.DR = resource; acro.DA = '/Helv 0 Tf 0 g '
        if variant == 'defaults': acro.NeedAppearances = False; acro.SigFlags = 0; acro.Q = 2; acro.CO = pikepdf.Array()
        elif variant == 'missing-fields': del acro.Fields
        elif variant == 'bad-fields': acro.Fields = pikepdf.Name.Unknown
        elif variant == 'nonempty-fields': acro.Fields.append(pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Tx, T='Unproved')))
        elif variant == 'unknown-key': acro.Developer = 'Unknown authority'
        elif variant == 'xfa': acro.XFA = 'Unproved XFA'
        elif variant == 'need-appearances': acro.NeedAppearances = True
        elif variant == 'signature-flags': acro.SigFlags = 1
        elif variant == 'boolean-flags': acro.SigFlags = False
        elif variant == 'permissions': pdf.Root.Perms = pikepdf.Dictionary(DocMDP=pikepdf.Dictionary())
        elif variant == 'calculation': acro.CO = pikepdf.Array(['Unproved'])
        elif variant == 'appearance-paint': acro.DA = '/Helv 10 Tf 0 0 20 20 re f'
        elif variant == 'appearance-font': acro.DA = '/Missing 10 Tf'
        elif variant == 'unknown-resource': acro.DR.XObject = pikepdf.Dictionary()
        elif variant == 'unknown-font': helv.Subtype = pikepdf.Name.Type3
        elif variant == 'unknown-encoding': encoding.Developer = 1
        elif variant == 'bad-differences': encoding.Differences = pikepdf.Array([255, pikepdf.Name.a, pikepdf.Name.b])
        elif variant == 'orphan-widget': pdf.Root.Orphan = pdf.make_indirect(pikepdf.Dictionary(Subtype=pikepdf.Name.Widget))
        elif variant == 'direct-widget': pdf.Root.Orphan = pikepdf.Dictionary(Nested=pikepdf.Dictionary(Subtype=pikepdf.Name.Widget))
        elif variant == 'direct-field': pdf.Root.Orphan = pikepdf.Dictionary(Nested=pikepdf.Dictionary(FT=pikepdf.Name.Tx))
        elif variant == 'nested-action': pdf.Root.Unproved = pikepdf.Dictionary(Nested=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS='Ignored'))
        elif variant == 'struct-attributes': pdf.Root.Unproved = pikepdf.Dictionary(A=pikepdf.Dictionary(O=pikepdf.Name.PrintField, Desc='Unproved'))
        elif variant == 'shared-container': pdf.Root.Shared = acro
        elif variant == 'shared-fields': pdf.Root.Shared = fields
        elif variant not in {'resources', 'bare', 'defaults'}: raise ValueError('Unknown inert fixture variant')
        if not no_acro: pdf.Root.AcroForm = acro
        with path.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    return path


@pytest.mark.parametrize('variant', ['bare', 'resources', 'defaults'])
def test_strict_empty_acroform_defaults_are_inert_and_add_no_new_form_inventory(tmp_path, variant):
    source = inert_pdf(tmp_path / 'source.pdf', variant=variant); raw = source.read_bytes()
    with pikepdf.open(source) as pdf:
        assert forms.is_inert_acroform(pdf) and not forms.has_form_signals(pdf)
        assert forms.preflight(pdf)['signals'] is False
    new = inventory(source); previous = inventory(source, sidecar.TABLE_INVENTORY_PROFILE)
    assert new['decisions'] == previous['decisions']
    assert not any(row['kind'] == 'form-controls' for row in new['decisions'])
    assert source.read_bytes() == raw


@pytest.mark.parametrize('variant', ['missing-fields', 'bad-fields', 'nonempty-fields', 'unknown-key', 'xfa',
    'need-appearances', 'signature-flags', 'boolean-flags', 'permissions', 'calculation', 'appearance-paint', 'appearance-font',
    'unknown-resource', 'unknown-font', 'unknown-encoding', 'bad-differences', 'orphan-widget', 'direct-widget',
    'direct-field', 'nested-action', 'struct-attributes', 'shared-container', 'shared-fields'])
def test_unknown_empty_or_hidden_active_form_authority_is_never_classified_inert(tmp_path, variant):
    source = inert_pdf(tmp_path / 'source.pdf', variant=variant); raw = source.read_bytes()
    with pikepdf.open(source) as pdf:
        assert not forms.is_inert_acroform(pdf) and forms.has_form_signals(pdf)
    row = choose(inventory(source)); assert not row['structural_eligible']
    assert source.read_bytes() == raw


@pytest.mark.parametrize('variant', ['orphan-widget', 'direct-widget', 'direct-field'])
def test_orphan_and_direct_form_signals_are_found_even_without_acroform(tmp_path, variant):
    source = inert_pdf(tmp_path / 'source.pdf', variant=variant, no_acro=True)
    with pikepdf.open(source) as pdf:
        assert '/AcroForm' not in pdf.Root and forms.has_form_signals(pdf)
    assert not choose(inventory(source))['structural_eligible']


def test_encrypted_empty_form_container_never_classified_inert(tmp_path):
    source = inert_pdf(tmp_path / 'source.pdf'); encrypted = tmp_path / 'encrypted.pdf'
    with pikepdf.open(source) as pdf:
        with encrypted.open('xb') as stream:
            pdf.save(stream, encryption=pikepdf.Encryption(owner='owner-only', user='', R=6))
    raw = encrypted.read_bytes()
    with pikepdf.open(encrypted) as pdf:
        assert pdf.is_encrypted and not forms.is_inert_acroform(pdf) and forms.has_form_signals(pdf)
    assert encrypted.read_bytes() == raw



def inert_layout_pdf(path, *, variant='generated'):
    source = inert_pdf(path.parent / 'ordinary-source.pdf')
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0].obj
        page.Contents = pikepdf.Stream(pdf, b'/Figure <</MCID 0>> BDC 0 0 10 10 re f EMC\n')
        page.StructParents = 0
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        attributes = pdf.make_indirect(pikepdf.Dictionary(O=pikepdf.Name.Layout,
            BBox=pikepdf.Array([Decimal('-0.9600000000000364'), 0, 792, Decimal('612.0000000000001')])))
        figure = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.Figure, P=document, Pg=page, K=0, A=attributes))
        document.K = pikepdf.Array([figure]); root.K = pikepdf.Array([document])
        root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([figure])])))
        root.ParentTreeNextKey = 1; pdf.Root.StructTreeRoot = root; pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        if variant == 'direct-attribute': figure.A = pikepdf.Dictionary(O=pikepdf.Name.Layout, BBox=pikepdf.Array([0, 0, 10, 10]))
        elif variant == 'wrong-role': figure.S = pikepdf.Name.P
        elif variant == 'wrong-owner': del figure.Type; del figure.P  # /Type alone is optional; with no parent as well it is only a lookalike
        elif variant == 'orphan-owner': document.K = pikepdf.Array(); pdf.Root.OrphanFigure = figure
        elif variant == 'wrong-parent': figure.P = root
        elif variant == 'duplicate-owner': document.K.append(figure)
        elif variant == 'role-map': root.RoleMap = pikepdf.Dictionary(Figure=pikepdf.Name.P)
        elif variant == 'attribute-extra': attributes.Developer = 'Unknown layout authority'
        elif variant == 'attribute-array': figure.A = pikepdf.Array([attributes])
        elif variant == 'attribute-stream': figure.A = pikepdf.Stream(pdf, b'', pikepdf.Dictionary(O=pikepdf.Name.Layout, BBox=pikepdf.Array([0, 0, 10, 10])))
        elif variant == 'wrong-layout': attributes.O = pikepdf.Name.PrintField
        elif variant == 'bad-bbox': attributes.BBox = pikepdf.Array([0, 0, 10])
        elif variant == 'boolean-bbox': attributes.BBox = pikepdf.Array([0, False, 10, 10])
        elif variant == 'string-bbox': attributes.BBox = pikepdf.Array([0, 'Unproved', 10, 10])
        elif variant == 'shared-attribute': pdf.Root.Unproved = attributes
        elif variant == 'shared-bbox': attributes.BBox = pdf.make_indirect(attributes.BBox); pdf.Root.Unproved = attributes.BBox
        elif variant == 'attribute-action': attributes.A = pikepdf.Dictionary(S=pikepdf.Name.URI, URI='https://invalid.example/')
        elif variant == 'type-action': pdf.Root.Unproved = pikepdf.Dictionary(Type=pikepdf.Name.Action)
        elif variant == 'latent-lock': pdf.Root.Unproved = pikepdf.Dictionary(Lock=pikepdf.Dictionary())
        elif variant == 'latent-seed': pdf.Root.Unproved = pikepdf.Dictionary(SV=pikepdf.Dictionary())
        elif variant != 'generated': raise ValueError('Unknown inert-layout fixture')
        with path.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    return path


@pytest.mark.parametrize('variant', ['generated', 'direct-attribute'])
def test_known_generated_figure_layout_preserves_inert_empty_form_behavior(tmp_path, variant):
    source = inert_layout_pdf(tmp_path / 'source.pdf', variant=variant); raw = source.read_bytes()
    with pikepdf.open(source) as pdf:
        assert forms.is_inert_acroform(pdf) and not forms.has_form_signals(pdf)
    data = inventory(source); old = inventory(source, sidecar.TABLE_INVENTORY_PROFILE)
    assert data['decisions'] == old['decisions'] and not any(row['kind'] == 'form-controls' for row in data['decisions'])
    title = next(row for row in data['decisions'] if row['kind'] == 'title')
    title['value'] = 'Reviewed ordinary Figure title'; sidecar.bind_approval(title, 'Reviewer', '2026-10-27')
    out = tmp_path / 'reviewed.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        assert forms.is_inert_acroform(pdf) and not forms.has_form_signals(pdf)
        assert str(pdf.docinfo.Title) == 'Reviewed ordinary Figure title'
        figure = pdf.Root.StructTreeRoot.K[0].K[0]
        assert figure.A.O == pikepdf.Name.Layout and len(figure.A.BBox) == 4 and len(pdf.Root.AcroForm.Fields) == 0
    assert source.read_bytes() == raw


@pytest.mark.parametrize('variant', ['wrong-role', 'wrong-owner', 'orphan-owner', 'wrong-parent',
    'duplicate-owner', 'role-map', 'attribute-extra', 'attribute-array', 'attribute-stream', 'wrong-layout',
    'bad-bbox', 'boolean-bbox', 'string-bbox', 'shared-attribute', 'shared-bbox', 'attribute-action',
    'type-action', 'latent-lock', 'latent-seed'])
def test_inert_layout_exception_rejects_lookalikes_shared_and_latent_authority(tmp_path, variant):
    source = inert_layout_pdf(tmp_path / 'source.pdf', variant=variant); raw = source.read_bytes()
    with pikepdf.open(source) as pdf:
        assert not forms.is_inert_acroform(pdf) and forms.has_form_signals(pdf)
    assert source.read_bytes() == raw



def inert_mcr_pdf(path, *, variant='marked-text'):
    base = inert_layout_pdf(path.parent / 'layout-source.pdf')
    with pikepdf.open(base) as pdf:
        root = pdf.Root.StructTreeRoot; document = root.K[0]; page = pdf.pages[0].obj
        font = pdf.Root.AcroForm.DR.Font.Helv
        content = b'BT /F1 12 Tf /P <</MCID 0>> BDC (Existing OCR words) Tj EMC ET\n'
        stream = pikepdf.Stream(pdf, content, pikepdf.Dictionary(Type=pikepdf.Name.XObject,
            Subtype=pikepdf.Name.Form, FormType=1, BBox=pikepdf.Array([0, 0, 300, 400]),
            Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)), StructParents=1))
        paragraph = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.P, P=document, Pg=page))
        mcr = pikepdf.Dictionary(Type=pikepdf.Name.MCR, MCID=0, Stm=stream)
        paragraph.K = pikepdf.Array([mcr]); document.K.append(paragraph)
        root.ParentTree.Nums.extend([1, pikepdf.Array([paragraph])]); root.ParentTreeNextKey = 2
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(OCR=stream))
        page.Contents = pikepdf.Stream(pdf, page.Contents.read_bytes() + b'q /OCR Do Q\n')
        if variant == 'wrong-owner': root.ParentTree.Nums[3] = pikepdf.Array([document.K[0]])
        elif variant == 'phantom': stream.write(b'BT /F1 12 Tf ET\n')
        elif variant == 'wrong-key': stream.StructParents = 9
        elif variant == 'extra-mcr-key': mcr.Unknown = 1
        elif variant == 'wrong-stream-type': stream.Subtype = pikepdf.Name.Image
        elif variant == 'missing-formtype': del stream.FormType  # accepted since the standard makes FormType 1 the default (tests/test_inert_stream_agreement.py)
        elif variant == 'bad-bbox': stream.BBox = pikepdf.Array([0, 0, 300])
        elif variant == 'alias-key': page.StructParents = 1
        elif variant == 'duplicate-reference': paragraph.K.append(mcr)
        elif variant == 'wrong-role': paragraph.S = pikepdf.Name.H1
        elif variant == 'empty-text': stream.write(content.replace(b'(Existing OCR words)', b'()'))
        elif variant == 'missing-font': stream.write(content.replace(b'/F1 12 Tf ', b''))
        elif variant == 'duplicate-marker': stream.write(content + content)
        elif variant == 'nested-marker': stream.write(content.replace(b'(Existing OCR words)', b'/P <</MCID 1>> BDC (Nested) EMC'))
        elif variant == 'replacement-marker': stream.write(content.replace(b'/MCID 0', b'/MCID 0 /ActualText (Replacement)'))
        elif variant == 'path-paint': stream.write(content.replace(b'(Existing OCR words) Tj', b'0 0 10 10 re f'))
        elif variant == 'xobject-paint': stream.write(content.replace(b'(Existing OCR words) Tj', b'/Unknown Do'))
        elif variant == 'action': stream.AA = pikepdf.Dictionary(O=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS='Ignored'))
        elif variant != 'marked-text': raise ValueError('Unknown inert marked-stream fixture')
        with path.open('xb') as target: pdf.save(target, deterministic_id=True)
    return path


def test_existing_marked_text_form_xobject_is_passive_not_an_interactive_form(tmp_path):
    source = inert_mcr_pdf(tmp_path / 'source.pdf'); raw = source.read_bytes()
    with pikepdf.open(source) as pdf:
        assert forms.is_inert_acroform(pdf) and not forms.has_form_signals(pdf)
        before_stream = pdf.pages[0].Resources.XObject.OCR.read_raw_bytes()
    data = inventory(source); old = inventory(source, sidecar.TABLE_INVENTORY_PROFILE)
    assert data['decisions'] == old['decisions'] and not any(row['kind'] == 'form-controls' for row in data['decisions'])
    title = next(row for row in data['decisions'] if row['kind'] == 'title')
    title['value'] = 'Ordinary tagged OCR metadata'; sidecar.bind_approval(title, 'Reviewer', '2026-10-27')
    out = tmp_path / 'reviewed.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        assert forms.is_inert_acroform(pdf) and not forms.has_form_signals(pdf)
        assert pdf.pages[0].Resources.XObject.OCR.read_raw_bytes() == before_stream
    assert source.read_bytes() == raw


@pytest.mark.parametrize('variant', ['wrong-owner', 'phantom', 'wrong-key', 'extra-mcr-key', 'wrong-stream-type',
    'bad-bbox', 'alias-key', 'duplicate-reference', 'wrong-role', 'empty-text', 'missing-font',
    'duplicate-marker', 'nested-marker', 'replacement-marker', 'path-paint', 'xobject-paint', 'action'])
def test_passive_mcr_stream_proof_rejects_wrong_or_unpainted_authority(tmp_path, variant):
    source = inert_mcr_pdf(tmp_path / 'source.pdf', variant=variant); raw = source.read_bytes()
    with pikepdf.open(source) as pdf:
        assert not forms.is_inert_acroform(pdf) and forms.has_form_signals(pdf)
    assert source.read_bytes() == raw
