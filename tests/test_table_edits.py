"""Small source graphs and negative contracts for explicit table metadata."""
from __future__ import annotations

import copy
import json

import pikepdf
import pytest

from pdf_remediator import sidecar
from pdf_remediator import structure_edits as graph
from pdf_remediator import table_edits as table


def table_pdf(path, *, external_id=False, outside_headers=False, attributes=False,
              alias=None, nested=False, grouped=False, existing_ids=False, source_summary=None,
              branch_index=False, orphan=None, custom_cell_role=False, unsupported_scope=False,
              source_version=None, version_metadata=False):
    pdf = pikepdf.Pdf.new(); page = pdf.add_blank_page(page_size=(400, 500))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
    root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
    root.K = document; pdf.Root.StructTreeRoot = root
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True); pdf.Root.Lang = 'en-US'; pdf.docinfo.Title = 'Table developer fixture'
    def element(role, parent):
        return pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name('/' + role), P=parent, Pg=page.obj))
    tab = element('Table', document); rows = []; cells = []; owners = []
    group = element('TBody', tab) if grouped else tab
    for r in range(2):
        row = element('TR', group); rows.append(row); children = []
        for c in range(2):
            cell = element('TD', row); cell.K = len(owners); owners.append(cell); cells.append(cell); children.append(cell)
        row.K = pikepdf.Array(children)
    if grouped: group.K = pikepdf.Array(rows); tab.K = group
    else: tab.K = pikepdf.Array(rows)
    para = element('P', document); para.K = len(owners); owners.append(para)
    document.K = pikepdf.Array([tab, para])
    if orphan:
        extra = pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.TH, P=document)
        if orphan in {'id', 'direct-id'}: extra.ID = 'orphan-header'
        else: extra.A = pikepdf.Dictionary(O=pikepdf.Name.Table, Headers=pikepdf.Array([pikepdf.String('new-header')]))
        pdf.Root.DeveloperOrphan = extra if orphan == 'direct-id' else pdf.make_indirect(extra)
    if attributes:
        cells[0].A = pikepdf.Array([pikepdf.Dictionary(O=pikepdf.Name.Layout, Placement=pikepdf.Name.Block),
                                    pikepdf.Dictionary(O=pikepdf.Name.Table, RowSpan=1)])
    if source_summary is not None:
        tab.A = pikepdf.Dictionary(O=pikepdf.Name.Table, Summary=pikepdf.String(source_summary))
    pairs = []
    if existing_ids:
        cells[0].S = pikepdf.Name.TH; cells[0].ID = pikepdf.String(b'\xfe\xff\x00h\x00e\x00a\x00d')
        cells[0].A = pikepdf.Dictionary(O=pikepdf.Name.Table, Scope=pikepdf.Name.Column)
        cells[2].A = pikepdf.Dictionary(O=pikepdf.Name.Table, Headers=pikepdf.Array([pikepdf.String(bytes(cells[0].ID))]))
        pairs.append((bytes(cells[0].ID), cells[0]))
    if external_id:
        para.ID = 'outside'; pairs.append((bytes(para.ID), para))
    if outside_headers:
        para.A = pikepdf.Dictionary(O=pikepdf.Name.Table, Headers=pikepdf.Array([pikepdf.String(bytes(cells[0].ID) if existing_ids else b'new-header')]))
    if custom_cell_role:
        cells[0].S = pikepdf.Name.DeveloperHeader
        cells[0].A = pikepdf.Dictionary(O=pikepdf.Name.Table, Scope=pikepdf.Name.Column)
        root.RoleMap = pikepdf.Dictionary(DeveloperHeader=pikepdf.Name.TH)
    if unsupported_scope:
        cells[0].A = pikepdf.Dictionary(O=pikepdf.Name.Table, Scope=pikepdf.Name.Diagonal)
    if pairs:
        root.IDTree = pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array([value for raw, node in sorted(pairs) for value in (pikepdf.String(raw), node)]), DeveloperNote='Preserve this unselected index property'))
        if branch_index:
            root.IDTree = pdf.make_indirect(pikepdf.Dictionary(Kids=pikepdf.Array([
                pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String(raw), node]),
                                                   Limits=pikepdf.Array([pikepdf.String(raw), pikepdf.String(raw)])))
                for raw, node in sorted(pairs)]), DeveloperNote='Preserve branch topology'))
    if alias == 'cell': pdf.Root.Extra = cells[0]
    if alias == 'root': pdf.Root.Extra = root
    if alias == 'children': tab.K = pdf.make_indirect(tab.K); pdf.Root.Extra = tab.K
    if alias == 'attributes':
        cells[0].A = pdf.make_indirect(pikepdf.Dictionary(O=pikepdf.Name.Table)); pdf.Root.Extra = cells[0].A
    if alias == 'parent-tree': pass
    if nested:
        inner = element('Table', cells[0]); inner_row = element('TR', inner); inner_cell = element('TD', inner_row)
        inner_cell.K = cells[0].K; owners[0] = inner_cell; cells[0].K = inner; inner_row.K = inner_cell; inner.K = inner_row
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)); page.StructParents = 0; page.Tabs = pikepdf.Name.S
    page.Contents = pdf.make_stream('\n'.join('/P <</MCID ' + str(n) + '>> BDC BT /F1 12 Tf 20 ' + str(460 - n * 30) + ' Td (Cell ' + str(n) + ') Tj ET EMC' for n in range(len(owners))).encode('ascii'))
    root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array(owners)])))
    if alias == 'parent-tree': pdf.Root.Extra = root.ParentTree
    root.ParentTreeNextKey = 1
    if version_metadata:
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            metadata['pdf:PDFVersion'] = source_version or '1.3'
    if source_version:
        pdf.save(path, deterministic_id=True, force_version=source_version, fix_metadata_version=False)
    else:
        pdf.save(path, deterministic_id=True)
    pdf.close(); return path


def inventory(path, profile=sidecar.TABLE_INVENTORY_PROFILE):
    return sidecar.collect_decisions(path, inventory_profile=profile)


def choice(data):
    found = [row for row in data['decisions'] if row['kind'] == 'table-structure']
    assert len(found) == 1
    return found[0]


def plan(row): return json.loads(row['current'])


def accept(row, value):
    row['value'] = table.canonical_value(value)
    sidecar.bind_approval(row, 'Developer table fixture', '2026-10-27')


def test_table_inventory_is_source_bound_and_six_old_profiles_are_exact(tmp_path):
    source = table_pdf(tmp_path / 'source.pdf'); data = inventory(source); row = choice(data)
    assert row['structural_eligible'], row['structural_limitations']
    assert row['value'] == row['current'] and row['status'] == 'pending'
    assert len(row['table_context']['cells']) == 4
    for profile in [sidecar.LEGACY_INVENTORY_PROFILE, sidecar.STRUCTURAL_INVENTORY_PROFILE,
                    sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE, sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE,
                    sidecar.NAVIGATION_INVENTORY_PROFILE, sidecar.SEMANTIC_TREE_INVENTORY_PROFILE]:
        old = inventory(source, profile)
        assert all(item['kind'] != 'table-structure' for item in old['decisions'])
        assert old == inventory(source, profile)


def test_explicit_header_hierarchy_summary_and_id_index_roundtrip(tmp_path):
    source = table_pdf(tmp_path / 'source.pdf', external_id=True, attributes=True)
    data = inventory(source); row = choice(data); value = plan(row); cells = value['cells']
    cells[0].update(role='TH', id='main', scope='Column')
    cells[1].update(role='TH', id='secondary', scope='Column', headers=[cells[0]['element']])
    cells[2]['headers'] = [cells[0]['element'], cells[1]['element']]
    cells[3]['headers'] = [cells[1]['element']]
    value['summary'] = 'Explicitly reviewed table summary.'; accept(row, value)
    out = tmp_path / 'out.pdf'; result = sidecar.apply_decisions(source, out, data, data['source_sha256'])
    assert row['id'] in result['changed']
    with pikepdf.open(out) as pdf:
        tab = pdf.Root.StructTreeRoot.K.K[0]; first = tab.K[0].K[0]
        assert first.S == pikepdf.Name.TH and str(first.ID) == 'main'
        assert str(tab.A.Summary) == value['summary']
        assert first.A[0].O == pikepdf.Name.Layout and first.A[0].Placement == pikepdf.Name.Block
        assert first.A[1].RowSpan == 1 and first.A[1].Scope == pikepdf.Name.Column
        names = pdf.Root.StructTreeRoot.IDTree.Names
        assert [bytes(names[n]) for n in range(0, len(names), 2)] == [b'main', b'outside', b'secondary']
        assert str(pdf.Root.StructTreeRoot.IDTree.DeveloperNote).startswith('Preserve')
    assert choice(inventory(out))['structural_eligible']


def test_summary_only_preserves_unicode_header_bytes_and_absent_defaults(tmp_path):
    source = table_pdf(tmp_path / 'source.pdf', existing_ids=True, external_id=True)
    data = inventory(source); row = choice(data); value = plan(row); value['summary'] = 'Reviewed summary'; accept(row, value)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        b = before.Root.StructTreeRoot.K.K[0]; a = after.Root.StructTreeRoot.K.K[0]
        assert bytes(a.K[0].K[0].ID) == bytes(b.K[0].K[0].ID)
        assert bytes(a.K[1].K[0].A.Headers[0]) == bytes(b.K[1].K[0].A.Headers[0])
        assert '/RowSpan' not in a.K[0].K[0].A and '/ColSpan' not in a.K[0].K[0].A
        assert graph._snapshot(before)['objects']  # exact graph oracle also runs in apply_decisions


@pytest.mark.parametrize('summary', ['Source summary\r\nwith CRLF\r\n', 'Source summary ' + 'x' * 4001])
def test_unrelated_cell_edits_preserve_unchanged_raw_summary(tmp_path, summary):
    source = table_pdf(tmp_path / 'source.pdf', source_summary=summary)
    data = inventory(source); row = choice(data); value = plan(row)
    value['cells'][0].update(role='TH', scope='Column'); accept(row, value)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        assert bytes(before.Root.StructTreeRoot.K.K[0].A.Summary) == bytes(after.Root.StructTreeRoot.K.K[0].A.Summary)


@pytest.mark.parametrize('change', ['cycle', 'foreign', 'self', 'duplicate-header', 'unnamed-header',
                                  'duplicate-id', 'invalid-id', 'data-scope', 'overlap', 'gap',
                                  'outside-row', 'zero-span', 'extra-field', 'missing-cell', 'long-summary'])
def test_invalid_complete_table_plans_are_refused(tmp_path, change):
    source = table_pdf(tmp_path / 'source.pdf'); row = choice(inventory(source)); value = plan(row); cells = value['cells']
    cells[0].update(role='TH', id='h', scope='Column'); cells[1].update(role='TH', id='h2', scope='Column')
    if change == 'cycle': cells[0]['headers'] = [cells[1]['element']]; cells[1]['headers'] = [cells[0]['element']]
    elif change == 'foreign': cells[2]['headers'] = ['999:0']
    elif change == 'self': cells[0]['headers'] = [cells[0]['element']]
    elif change == 'duplicate-header': cells[2]['headers'] = [cells[0]['element']] * 2
    elif change == 'unnamed-header': cells[0]['id'] = None; cells[2]['headers'] = [cells[0]['element']]
    elif change == 'duplicate-id': cells[1]['id'] = 'h'
    elif change == 'invalid-id': cells[0]['id'] = 'not an ID'
    elif change == 'data-scope': cells[2]['scope'] = 'Row'
    elif change == 'overlap': cells[0]['row_span'] = 2; cells[2]['col_span'] = 2
    elif change == 'gap': cells[0]['col_span'] = 2
    elif change == 'outside-row': cells[2]['row_span'] = 2
    elif change == 'zero-span': cells[0]['row_span'] = 0
    elif change == 'extra-field': cells[0]['text'] = 'invented'
    elif change == 'missing-cell': cells.pop()
    elif change == 'long-summary': value['summary'] = 'x' * 4001
    row['value'] = table.canonical_value(value)
    with pytest.raises(sidecar.DecisionError): table.validate_value(row)


@pytest.mark.parametrize('alias', ['cell', 'root', 'children', 'attributes', 'parent-tree'])
def test_shared_structure_and_index_carriers_stay_readonly(tmp_path, alias):
    row = choice(inventory(table_pdf(tmp_path / 'source.pdf', alias=alias)))
    assert not row['structural_eligible']


@pytest.mark.parametrize('existing', [False, True])
def test_outside_header_capture_or_retarget_is_refused(tmp_path, existing):
    source = table_pdf(tmp_path / 'source.pdf', existing_ids=existing, outside_headers=True)
    data = inventory(source); row = choice(data); value = plan(row); cells = value['cells']
    if existing:
        old_id = cells[0]['id']; cells[0]['id'] = 'replacement'
        cells[1].update(role='TH', id=old_id)
    else: cells[0].update(role='TH', id='new-header')
    accept(row, value)
    with pytest.raises(sidecar.DecisionError, match='outside Headers'):
        sidecar.apply_decisions(source, tmp_path / 'out.pdf', data, data['source_sha256'])


def test_nested_enclosing_table_is_readonly_but_inner_is_scoped(tmp_path):
    data = inventory(table_pdf(tmp_path / 'source.pdf', nested=True))
    rows = [row for row in data['decisions'] if row['kind'] == 'table-structure']
    assert len(rows) == 2
    assert not rows[0]['structural_eligible']
    assert rows[1]['structural_eligible'], rows[1]['structural_limitations']


def test_source_binding_changes_refused_and_unchanged_plan_preserves_bytes(tmp_path):
    source = table_pdf(tmp_path / 'source.pdf'); data = inventory(source); row = choice(data)
    accept(row, plan(row)); out = tmp_path / 'out.pdf'
    sidecar.apply_decisions(source, out, data, data['source_sha256'])
    assert source.read_bytes() == out.read_bytes()
    stale = copy.deepcopy(data); target = choice(stale); target['table_context']['cells'][0]['column'] += 1
    with pytest.raises(sidecar.DecisionError): sidecar.apply_decisions(source, tmp_path / 'stale.pdf', stale, data['source_sha256'])


@pytest.mark.parametrize('field,value', [('role', []), ('role', {}), ('scope', []), ('scope', {})])
def test_unhashable_role_and_scope_values_are_typed_refusals(tmp_path, field, value):
    row = choice(inventory(table_pdf(tmp_path / 'source.pdf'))); proposed = plan(row)
    proposed['cells'][0][field] = value; row['value'] = table.canonical_value(proposed)
    with pytest.raises(sidecar.DecisionError): table.validate_value(row)


@pytest.mark.parametrize('replacement', [None, 'a-before-outside'])
def test_id_change_that_empties_nonroot_name_tree_leaf_is_refused(tmp_path, replacement):
    source = table_pdf(tmp_path / 'source.pdf', external_id=True, existing_ids=True, branch_index=True)
    data = inventory(source); row = choice(data); value = plan(row)
    assert row['structural_eligible'], row['structural_limitations']
    value['cells'][0]['id'] = replacement
    if replacement is None: value['cells'][2]['headers'] = []
    accept(row, value)
    with pytest.raises(sidecar.DecisionError, match='empty an existing IDTree leaf'):
        sidecar.apply_decisions(source, tmp_path / 'out.pdf', data, data['source_sha256'])


@pytest.mark.parametrize('orphan', ['id', 'direct-id', 'headers'])
def test_unrooted_reachable_structure_namespace_is_readonly_in_new_profile_only(tmp_path, orphan):
    source = table_pdf(tmp_path / 'source.pdf', orphan=orphan)
    row = choice(inventory(source))
    assert not row['structural_eligible']
    assert any('unrooted' in reason for reason in row['structural_limitations'])
    for profile in [sidecar.LEGACY_INVENTORY_PROFILE, sidecar.STRUCTURAL_INVENTORY_PROFILE,
                    sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE, sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE,
                    sidecar.NAVIGATION_INVENTORY_PROFILE, sidecar.SEMANTIC_TREE_INVENTORY_PROFILE]:
        old = inventory(source, profile)
        assert all(item['kind'] != 'table-structure' for item in old['decisions'])
        assert old == inventory(source, profile)


def test_resolved_cell_role_keeps_raw_rolemap_alias_during_summary_edit(tmp_path):
    source = table_pdf(tmp_path / 'source.pdf', custom_cell_role=True)
    data = inventory(source); row = choice(data); value = plan(row)
    assert row['structural_eligible'], row['structural_limitations']
    assert value['cells'][0]['role'] == 'TH'
    value['summary'] = 'Explicit summary beside an unchanged mapped header.'; accept(row, value)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        assert pdf.Root.StructTreeRoot.K.K[0].K[0].K[0].S == pikepdf.Name.DeveloperHeader
        assert pdf.Root.StructTreeRoot.RoleMap.DeveloperHeader == pikepdf.Name.TH
    assert plan(choice(inventory(out)))['cells'][0]['role'] == 'TH'


def test_changed_mapped_cell_role_writes_only_explicit_standard_delta(tmp_path):
    source = table_pdf(tmp_path / 'source.pdf', custom_cell_role=True)
    data = inventory(source); row = choice(data); value = plan(row)
    value['cells'][0].update(role='TD', scope=None); accept(row, value)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    with pikepdf.open(out) as pdf:
        first = pdf.Root.StructTreeRoot.K.K[0].K[0].K[0]
        assert first.S == pikepdf.Name.TD and '/Scope' not in first.A
        assert pdf.Root.StructTreeRoot.RoleMap.DeveloperHeader == pikepdf.Name.TH


def test_unknown_scope_name_is_explicitly_readonly(tmp_path):
    row = choice(inventory(table_pdf(tmp_path / 'source.pdf', unsupported_scope=True)))
    assert not row['structural_eligible']
    assert any('Scope name is unsupported' in reason for reason in row['structural_limitations'])


@pytest.mark.parametrize('source_version,expected_version', [('1.3', '1.7'), ('2.0', '2.0')])
def test_authored_table_features_raise_minimum_version_without_metadata_or_higher_version_loss(tmp_path, source_version, expected_version):
    source = table_pdf(tmp_path / 'source.pdf', source_version=source_version, version_metadata=True)
    original = source.read_bytes(); data = inventory(source); row = choice(data); value = plan(row)
    value['cells'][0].update(role='TH', id='explicit-header', scope='Column')
    value['cells'][2]['headers'] = [value['cells'][0]['element']]
    value['summary'] = 'Explicit PDF 1.7 table summary.'; accept(row, value)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    assert source.read_bytes() == original
    assert out.read_bytes().startswith(('%PDF-' + expected_version).encode('ascii'))
    with pikepdf.open(source) as before, pikepdf.open(out) as after:
        assert after.pdf_version == expected_version
        assert before.Root.Metadata.read_bytes() == after.Root.Metadata.read_bytes()
        assert str(after.Root.StructTreeRoot.K.K[0].A.Summary) == value['summary']


@pytest.mark.parametrize('source_version,good_version,bad_version', [('1.3', '1.7', '1.3'), ('2.0', '2.0', '1.7')])
def test_reopened_table_oracle_refuses_header_downgrade_even_when_object_graph_is_identical(tmp_path, source_version, good_version, bad_version):
    source = table_pdf(tmp_path / 'source.pdf', source_version=source_version, version_metadata=True)
    data = inventory(source); row = choice(data); value = plan(row)
    value['summary'] = 'Reviewed summary requiring at least PDF 1.7.'; accept(row, value)
    out = tmp_path / 'out.pdf'; sidecar.apply_decisions(source, out, data, data['source_sha256'])
    raw = out.read_bytes(); expected_header = ('%PDF-' + good_version).encode('ascii')
    assert raw.startswith(expected_header)
    tampered = tmp_path / 'underdeclared.pdf'
    tampered.write_bytes(('%PDF-' + bad_version).encode('ascii') + raw[len(expected_header):])
    with pikepdf.open(out) as good, pikepdf.open(tampered) as bad:
        assert table.canonical_snapshot(graph._snapshot(good)) == table.canonical_snapshot(graph._snapshot(bad))
    with pytest.raises(sidecar.DecisionError, match='insufficient PDF version'):
        graph.verify_output(source, tampered, [], other_changes=[row])
