"""Literal empty-tag sources, independent expected graph and refusal cases."""
from __future__ import annotations

import copy

import pikepdf
import pytest

from pdf_remediator import empty_tag_edits as empty, structure_edits as graph
from pdf_remediator.navigation_edits import canonical_snapshot
from pdf_remediator.sidecar import DecisionError


def empty_pdf(path, *, variant='safe', empty_count=1, indirect_children=False):
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400)).obj
        pdf.docinfo.Title = 'Empty tag fixture'; pdf.Root.Lang = 'en-US'
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica, Encoding=pikepdf.Name.WinAnsiEncoding))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(b'BT /F1 12 Tf 20 350 Td /P <</MCID 0>> BDC (Retained visible words) Tj EMC ET\n')
        page.StructParents = 0
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        parent = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.Document, P=root, Pg=page))
        text = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.P, P=parent, Pg=page, K=0))
        blanks = [pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.P, P=parent, Pg=page, K=pikepdf.Array())) for _ in range(empty_count)]
        children = pikepdf.Array([text, *blanks]); parent.K = pdf.make_indirect(children) if indirect_children else children
        root.K = pikepdf.Array([parent]); root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([text])])))
        root.ParentTreeNextKey = 1; pdf.Root.StructTreeRoot = root; pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        selected = blanks[0]
        if variant == 'absent': del selected.K
        elif variant == 'root-scalar': root.K = parent
        elif variant.startswith('intermediate-scalar'):
            upper = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Part, P=root, K=parent))
            parent.P = upper; root.K = pikepdf.Array([upper])
            if variant == 'intermediate-scalar-alias': pdf.Root.Unproved = upper
            elif variant == 'intermediate-scalar-wrong-parent': parent.P = root
        elif variant == 'root-scalar-alias': root.K = parent; pdf.Root.Unproved = parent
        elif variant == 'null':
            null_node = pdf.make_indirect(pikepdf.Object.parse(b'<< /Type /StructElem /S /P /K null >>'))
            null_node.P = parent; null_node.Pg = page; parent.K[1] = null_node
        elif variant == 'span': selected.S = pikepdf.Name.Span
        elif variant == 'optional-type': del selected.Type; del parent.Type; del text.Type
        elif variant == 'bad-type': selected.Type = pikepdf.Name.Unknown
        elif variant == 'indirect-empty': selected.K = pdf.make_indirect(pikepdf.Array())
        elif variant == 'dangling-mcid': selected.K = 99
        elif variant == 'dangling-mcr': selected.K = pikepdf.Dictionary(Type=pikepdf.Name.MCR, MCID=99, Pg=page)
        elif variant == 'objr': selected.K = pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link)))
        elif variant == 'null-child': selected.K = pikepdf.Array([None])
        elif variant == 'nested-child':
            nested = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Span, P=selected))
            selected.K = pikepdf.Array([nested])
        elif variant.startswith('property-'): selected[pikepdf.Name('/' + variant.split('-', 1)[1])] = pikepdf.String('Protected source property')
        elif variant.startswith('role-'): selected.S = pikepdf.Name('/' + variant.split('-', 1)[1])
        elif variant.startswith('ancestor-') and variant not in {'ancestor-alt', 'ancestor-lang'}: parent.S = pikepdf.Name('/' + variant.split('-', 1)[1])
        elif variant == 'ancestor-alt': parent.Alt = 'Protected interpretation'
        elif variant == 'ancestor-lang': parent.Lang = 5
        elif variant == 'remapped-role': root.RoleMap = pikepdf.Dictionary(P=pikepdf.Name.Span)
        elif variant == 'leaf-alias': pdf.Root.Unproved = selected
        elif variant == 'orphan-alias': pdf.Root.Unproved = pdf.make_indirect(pikepdf.Dictionary(Other=selected))
        elif variant == 'parent-alias': pdf.Root.Unproved = parent
        elif variant == 'parent-array-alias': parent.K = pdf.make_indirect(parent.K); pdf.Root.Unproved = parent.K
        elif variant == 'empty-array-alias': selected.K = pdf.make_indirect(selected.K); pdf.Root.Unproved = selected.K
        elif variant == 'parenttree-ref': root.ParentTree.Nums[1].append(selected)
        elif variant == 'idtree-ref': root.IDTree = pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array(['Unproved ID', selected])))
        elif variant == 'duplicate-child': parent.K.append(selected)
        elif variant == 'wrong-parent': selected.P = root
        elif variant == 'only-empty':
            parent.K = pikepdf.Array(blanks); page.Contents = pdf.make_stream(b''); root.ParentTree.Nums[1] = pikepdf.Array()
        elif variant == 'signature': pdf.Root.Perms = pikepdf.Dictionary()
        elif variant == 'form': pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array())
        elif variant == 'script': pdf.Root.Unproved = pikepdf.Dictionary(Nested=pikepdf.Dictionary(JS='Ignored'))
        elif variant != 'safe': raise ValueError('Unknown empty-tag fixture')
        with path.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    return path


def choices(pdf):
    rows, _, errors = empty.inventory(pdf)
    assert errors == []
    return rows


def removal(row):
    changed = copy.deepcopy(row); changed['value'] = 'remove'; return changed


@pytest.mark.parametrize('variant', ['safe', 'absent', 'null', 'span', 'optional-type', 'indirect-empty', 'root-scalar', 'intermediate-scalar'])
@pytest.mark.parametrize('indirect_children', [False, True])
def test_proved_empty_leaves_detach_only_parent_edge_and_preserve_reopened_graph(tmp_path, variant, indirect_children):
    source = empty_pdf(tmp_path / 'source.pdf', variant=variant, indirect_children=indirect_children); raw = source.read_bytes()
    out = tmp_path / 'reviewed.pdf'
    with pikepdf.open(source) as pdf:
        before = graph._snapshot(pdf); row = next(row for row in choices(pdf) if row['structural_eligible'])
        leaf = row['element']; parent = next(obj for obj in pdf.objects if graph._id(obj) == row['empty_tag_context']['parent']['element']); old_carrier = graph._id(parent.K)
        content = pdf.pages[0].Contents.read_raw_bytes(); tree_id = graph._id(pdf.Root.StructTreeRoot.ParentTree); old_tree = copy.deepcopy(before['objects'][tree_id])
        plans = empty.prepare_changes(pdf, [removal(row)]); expected = empty.expected_snapshot(before, plans)
        assert empty.apply_prepared(pdf, plans) == [row['id']]
        assert len(parent.K) == 1 and graph._id(parent.K) == old_carrier
        assert leaf not in graph._snapshot(pdf)['objects'] and leaf not in expected['objects']
        assert any(graph._id(obj) == leaf for obj in pdf.objects)  # Detach; do not physically delete the object.
        assert pdf.pages[0].Contents.read_raw_bytes() == content and graph._snapshot(pdf)['objects'][tree_id] == old_tree
        assert canonical_snapshot(graph._snapshot(pdf)) == canonical_snapshot(expected)
        with out.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    with pikepdf.open(out) as pdf:
        assert canonical_snapshot(graph._snapshot(pdf)) == canonical_snapshot(expected)
        assert not any(row['structural_eligible'] for row in choices(pdf))
    assert source.read_bytes() == raw


@pytest.mark.parametrize('variant', ['dangling-mcid', 'dangling-mcr', 'objr', 'null-child', 'nested-child',
    'bad-type', 'property-Alt', 'property-ActualText', 'property-E', 'property-ID', 'property-Ref', 'property-AF',
    'property-A', 'property-C', 'property-Lang', 'property-NS', 'property-T', 'role-H1', 'role-Figure', 'role-Form',
    'role-Link', 'role-L', 'role-TD', 'ancestor-L', 'ancestor-Table', 'ancestor-Form', 'ancestor-Link', 'ancestor-Figure',
    'ancestor-alt', 'ancestor-lang', 'remapped-role', 'leaf-alias', 'orphan-alias', 'parent-alias', 'parent-array-alias',
    'empty-array-alias', 'parenttree-ref', 'idtree-ref', 'duplicate-child', 'wrong-parent', 'only-empty', 'signature', 'form', 'script',
    'root-scalar-alias', 'intermediate-scalar-alias', 'intermediate-scalar-wrong-parent'])
def test_apparent_emptiness_never_authorizes_protected_or_unresolved_structure(tmp_path, variant):
    source = empty_pdf(tmp_path / 'source.pdf', variant=variant); raw = source.read_bytes()
    with pikepdf.open(source) as pdf:
        before = graph._snapshot(pdf); rows = choices(pdf)
        assert not any(row['structural_eligible'] for row in rows)
        if rows:
            with pytest.raises(DecisionError): empty.prepare_changes(pdf, [removal(rows[0])])
        assert graph._snapshot(pdf) == before
    assert source.read_bytes() == raw


def test_complete_batch_retains_original_painted_sibling_and_exact_unselected_order(tmp_path):
    source = empty_pdf(tmp_path / 'source.pdf', empty_count=3, indirect_children=True)
    with pikepdf.open(source) as pdf:
        rows = [row for row in choices(pdf) if row['structural_eligible']]; assert len(rows) == 3
        parent = pdf.Root.StructTreeRoot.K[0]; original = [graph._id(child) for child in parent.K]
        plans = empty.prepare_changes(pdf, [removal(rows[0]), removal(rows[2])])
        expected = empty.expected_snapshot(graph._snapshot(pdf), plans); empty.apply_prepared(pdf, plans)
        assert [graph._id(child) for child in parent.K] == [ident for ident in original if ident not in {rows[0]['element'], rows[2]['element']}]
        assert canonical_snapshot(graph._snapshot(pdf)) == canonical_snapshot(expected)


@pytest.mark.parametrize('field', ['context_sha256', 'element', 'page', 'structure_path', 'allowed_values', 'empty_tag_context'])
def test_stale_or_forged_capabilities_are_refused_without_mutation(tmp_path, field):
    source = empty_pdf(tmp_path / 'source.pdf')
    with pikepdf.open(source) as pdf:
        row = removal(next(row for row in choices(pdf) if row['structural_eligible'])); before = graph._snapshot(pdf)
        row[field] = None
        with pytest.raises(DecisionError): empty.prepare_changes(pdf, [row])
        assert graph._snapshot(pdf) == before


def test_prepared_writer_rejects_new_parent_order_before_any_mutation(tmp_path):
    source = empty_pdf(tmp_path / 'source.pdf', empty_count=2)
    with pikepdf.open(source) as pdf:
        row = next(row for row in choices(pdf) if row['structural_eligible']); plans = empty.prepare_changes(pdf, [removal(row)])
        parent = pdf.Root.StructTreeRoot.K[0]; parent.K = pikepdf.Array(list(reversed(parent.K))); before = graph._snapshot(pdf)
        with pytest.raises(DecisionError): empty.apply_prepared(pdf, plans)
        assert graph._snapshot(pdf) == before


def test_failed_live_oracle_restores_original_arrays_and_graph(tmp_path, monkeypatch):
    source = empty_pdf(tmp_path / 'source.pdf', indirect_children=True)
    with pikepdf.open(source) as pdf:
        row = next(row for row in choices(pdf) if row['structural_eligible']); plans = empty.prepare_changes(pdf, [removal(row)])
        before = graph._snapshot(pdf); real = empty.expected_snapshot
        def wrong(snapshot, plans, *, cancel=None):
            result = real(snapshot, plans, cancel=cancel); result['objects'][row['empty_tag_context']['parent']['element']]['v']['/Unapproved'] = {'t': 'number', 'v': '1'}; return result
        monkeypatch.setattr(empty, 'expected_snapshot', wrong)
        with pytest.raises(DecisionError): empty.apply_prepared(pdf, plans)
        assert graph._snapshot(pdf) == before


@pytest.mark.parametrize('kind', ['reading-order', 'tree-move', 'figure-purpose', 'structure-role', 'table-structure', 'form-controls', 'passage-language'])
def test_other_changed_structural_plans_require_separate_application(tmp_path, kind):
    source = empty_pdf(tmp_path / 'source.pdf')
    with pikepdf.open(source) as pdf:
        row = next(row for row in choices(pdf) if row['structural_eligible']); before = graph._snapshot(pdf)
        with pytest.raises(DecisionError):
            empty.prepare_changes(pdf, [removal(row)], other_changes=[{'kind': kind, 'value': 'new', 'current': 'old', 'element': 'unrelated'}])
        assert graph._snapshot(pdf) == before


@pytest.mark.parametrize('kind', ['title', 'language', 'figure-description', 'heading-tag', 'table-header'])
def test_compatible_unrelated_existing_choices_can_share_a_reviewed_apply(tmp_path, kind):
    source = empty_pdf(tmp_path / 'source.pdf')
    with pikepdf.open(source) as pdf:
        row = next(row for row in choices(pdf) if row['structural_eligible'])
        assert len(empty.prepare_changes(pdf, [removal(row)], other_changes=[{'kind': kind, 'element': 'unrelated', 'current': 'old', 'value': 'new'}])) == 1
        if kind not in {'title', 'language'}:
            with pytest.raises(DecisionError): empty.prepare_changes(pdf, [removal(row)], other_changes=[{'kind': kind, 'element': row['element'], 'current': 'old', 'value': 'new'}])


def test_keep_and_exact_original_withdrawal_do_not_mutate_or_get_removal_credit(tmp_path):
    source = empty_pdf(tmp_path / 'source.pdf')
    with pikepdf.open(source) as pdf:
        rows = choices(pdf); before = graph._snapshot(pdf)
        assert empty.prepare_changes(pdf, rows) == []
        assert empty.apply_prepared(pdf, []) == [] and graph._snapshot(pdf) == before


@pytest.mark.parametrize('variant', ['plain', 'populated', 'unused-form'])
def test_complete_zero_candidate_census_creates_no_empty_tag_controls(tmp_path, variant, monkeypatch):
    source = empty_pdf(tmp_path / 'source.pdf')
    with pikepdf.open(source) as pdf:
        if variant == 'plain': del pdf.Root.StructTreeRoot
        elif variant == 'populated': del pdf.Root.StructTreeRoot.K[0].K[1]
        else:
            del pdf.Root.StructTreeRoot; pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array())
        def forbidden(*args, **kwargs): raise AssertionError('No full graph proof is needed for zero actual candidates')
        monkeypatch.setattr(graph, '_analyse', forbidden)
        assert empty.inventory(pdf) == ([], {}, [])
