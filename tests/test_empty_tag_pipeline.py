"""Real tagged PDFs and transactional empty-tag edits; CLI alone is a test double."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import textwrap
import threading

import pikepdf
import pytest
from reportlab.pdfgen import canvas

from pdf_remediator import inspection, pipeline, sidecar, workspace
from pdf_remediator.config import RuntimeConfig
from test_artifact_structure_pipeline import canonical, exact_fidelity, files, independent_paint_and_navigation
from test_language import TEXTS
from test_language_scopes import registered_language_fonts
from test_pipeline import fast_validator, tagged_control

KIND = 'empty-tag-removal'
REVIEWER = 'Developer empty-tag fixture'
OLD = [sidecar.LEGACY_INVENTORY_PROFILE, sidecar.STRUCTURAL_INVENTORY_PROFILE,
       sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE, sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE,
       sidecar.NAVIGATION_INVENTORY_PROFILE, sidecar.SEMANTIC_TREE_INVENTORY_PROFILE,
       sidecar.TABLE_INVENTORY_PROFILE, sidecar.FORM_INVENTORY_PROFILE]


def empty_tag_source(directory, *, hazard=None, empty_count=3, small_font=True, root_scalar=True):
    """Independently authored two-page, licensed-font control with three empty leaves."""
    assert isinstance(empty_count, int) and not isinstance(empty_count, bool) and 1 <= empty_count <= 100
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    paint = directory / 'paint.pdf'; output = directory / 'source.pdf'
    c = canvas.Canvas(str(paint), pagesize=(560, 700), invariant=1, initialFontName='SyntheticVera')
    c.setTitle('Community research notes and readable footnotes')
    def text(mcid, role, words, x, y, size=11, wrap=False):
        c._code.append('/' + role + ' <</MCID ' + str(mcid) + '>> BDC')
        c.setFont('SyntheticVera', size)
        for index, line in enumerate(textwrap.wrap(words, width=91) if wrap else [words]): c.drawString(x, y-index*14, line)
        c._code.append('EMC')
    c.bookmarkPage('opening'); c.addOutlineEntry('Opening research notes', 'opening', level=0)
    text(0, 'H1', 'Community research notes', 28, 660, 18)
    text(1, 'P', TEXTS['en'], 28, 610, wrap=True)
    c.showPage(); c.bookmarkPage('continuation'); c.addOutlineEntry('Notes and footnotes', 'continuation', level=0)
    text(0, 'H2', 'Notes and footnotes', 28, 660, 15)
    text(1, 'P', TEXTS['en'], 28, 610, wrap=True)
    text(2, 'P', 'Small print: this eight-point footnote is preserved for a reviewer to inspect.', 28, 125, 8 if small_font else 11)
    text(3, 'P', 'Nine-point control: retain this readable-size comparison exactly.', 28, 100, 9)
    text(4, 'Link', 'Return to opening research notes', 28, 60, 11)
    c.showPage(); c.save()
    with pikepdf.open(paint) as pdf:
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        sections = []; numbers = []; blanks = []
        for number, page in enumerate(pdf.pages):
            section = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Sect, P=document, Pg=page.obj)); sections.append(section)
            roles = ['H1', 'P'] if number == 0 else ['H2', 'P', 'P', 'P', 'Link']
            owners = [pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                S=pikepdf.Name('/' + role), P=section, Pg=page.obj, K=mcid)) for mcid, role in enumerate(roles)]
            if number == 1:
                annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                    P=page.obj, Rect=pikepdf.Array([28, 55, 285, 75]), F=4, Border=pikepdf.Array([0, 0, 0]),
                    Contents='Return to opening research notes', NM='empty-tag-unrelated-link', StructParent=2,
                    Dest=pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit])))
                page.Annots = pikepdf.Array([annotation]); owners[-1].Alt = 'Return to opening research notes'
                owners[-1].K = pikepdf.Array([4, pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=annotation, Pg=page.obj)])
                numbers.extend([2, owners[-1]])
            local = []
            for index in range(min(2, empty_count) if number == 0 else max(0, empty_count-2)):
                node = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                    S=pikepdf.Name.P if number == 0 else pikepdf.Name.Span, P=section, Pg=page.obj))
                if number == 0 and index == 0: node.K = pikepdf.Array()
                elif number == 1:
                    node = pdf.make_indirect(pikepdf.Object.parse(b'<< /Type /StructElem /S /Span /K null >>')); node.P = section; node.Pg = page.obj
                local.append(node); blanks.append(node)
            section.K = pikepdf.Array([*owners, *local]); page.StructParents = number; page.Tabs = pikepdf.Name.S
            numbers.extend([number, pikepdf.Array(owners)])
        root.K = document if root_scalar else pikepdf.Array([document]); document.K = pikepdf.Array(sections)
        pairs = sorted((int(numbers[index]), numbers[index+1]) for index in range(0, len(numbers), 2))
        root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([part for pair in pairs for part in pair])))
        root.ParentTreeNextKey = 3; pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True); pdf.Root.Lang = 'en-US'
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Dictionary(S=pikepdf.Name.r), 1, pikepdf.Dictionary(S=pikepdf.Name.D, St=5)]))
        pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array(['empty-tag-opening', pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit])])))
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            metadata['dc:title'] = str(pdf.docinfo.Title); metadata['dc:language'] = ['en-US']; metadata['pdfuaid:part'] = 1
        pdf.Root.Metadata.Type = pikepdf.Name.Metadata; pdf.Root.Metadata.Subtype = pikepdf.Name.XML
        if hazard == 'description': blanks[0].Alt = 'A source description must remain'
        elif hazard == 'dangling': blanks[0].K = 99
        elif hazard == 'alias': pdf.Root.Unproved = blanks[0]
        elif hazard is not None: raise ValueError('Unknown authored empty-tag hazard')
        with output.open('xb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7')
    return output


empty_source = empty_tag_source


def logical_snapshot(path, *, remove_empty=False):
    """Independent literal structure/ParentTree proof; no editor plan helper."""
    with pikepdf.open(path) as pdf:
        pages = {page.obj.objgen: n for n, page in enumerate(pdf.pages, 1)}; owners = {}; seen = set()
        def blank(node):
            return (isinstance(node, pikepdf.Dictionary) and node.get('/S') in (pikepdf.Name.P, pikepdf.Name.Span)
                    and set(node.keys()) <= {'/Type', '/S', '/P', '/Pg', '/K'}
                    and ('/K' not in node or node['/K'] is None or isinstance(node['/K'], pikepdf.Array) and len(node['/K']) == 0))
        def visit(node, position, parent):
            if node is None: return None
            if isinstance(node, int): return {'mcid': node}
            if isinstance(node, pikepdf.Array):
                return [visit(child, position+'/'+str(index), parent) for index, child in enumerate(node) if not (remove_empty and blank(child))]
            if node.get('/Type') == pikepdf.Name.OBJR:
                return {'objr': str(node.Obj.NM), 'page': pages[node.Pg.objgen]}
            assert node.objgen not in seen and node.P.objgen == parent
            seen.add(node.objgen); owners[node.objgen] = position
            return {'attributes': {str(key): canonical(value) for key, value in node.items() if key not in {'/P', '/Pg', '/K'}},
                'page': pages[node.Pg.objgen] if '/Pg' in node else None, 'children': visit(node.get('/K'), position+'/K', node.objgen)}
        root = pdf.Root.StructTreeRoot; result = visit(root.K, 'root/K', root.objgen)
        slots = {}
        for index in range(0, len(root.ParentTree.Nums), 2):
            key, target = list(root.ParentTree.Nums)[index:index+2]
            slots[str(key)] = [None if owner is None else owners[owner.objgen] for owner in target] if isinstance(target, pikepdf.Array) else owners[target.objgen]
        return {'logical': result, 'parent_tree': slots,
            'root_attributes': {str(key): canonical(value) for key, value in root.items() if key not in {'/K', '/ParentTree'}}}


def execute(source, output, **kwargs): return pipeline.process_file(source, output, RuntimeConfig(), **kwargs)
def decisions(report): return sidecar.load_sidecar(Path(report['bundle_path'])/'decisions.json')
def empty_rows(data): return [row for row in data['decisions'] if row['kind'] == KIND]


def accept(data):
    rows = empty_rows(data); assert len(rows) == 3 and all(row['structural_eligible'] for row in rows)
    for row in rows: row['value'] = 'remove'; sidecar.bind_approval(row, REVIEWER, '2026-10-27')
    return rows


def fresh_reviews(report, accepted):
    changed = {row['id']: row for row in empty_rows(accepted) if row['status'] == 'approved' and row['value'] != row['current']}
    rows = [row for row in report['manual_review']['items'] if row['id'].startswith('empty-tag-decision-')]
    assert len(rows) == len(changed) and {row['decision_id'] for row in rows} == set(changed)
    for row in rows:
        decision = changed[row['decision_id']]
        assert row['id'] == 'empty-tag-decision-'+hashlib.sha256(decision['id'].encode()).hexdigest()[:20]
        assert row['category'] == 'empty-tags' and row['required'] is True and row['status'] == 'pending'
        assert row['context_sha256'] == decision['context_sha256']
        assert row['evidence']['source_empty_tag_context'] == decision['empty_tag_context']
        assert not any(key in row for key in ('reviewer', 'reviewed_at', 'approval_sha256', 'notes'))
    return rows


def assert_output(report):
    assert report['status'] in {'candidate', 'needs-manual'}, report.get('error')
    assert report['output'] and report['gate1']['validator'] == 'test-stub'
    exact_fidelity(report)
    assert report['settings']['ocr_mode'] == 'off' and report['data_sent']['provider'] is None and report['data_sent']['document_api_calls'] == 0
    assert report['inspection']['sha256'] == report['gate1']['input_sha256'] == report['output']['sha256'] == report['fidelity']['after_sha256']
    assert all(item['status'] == 'pending' for item in report['manual_review']['items'])


def test_original_empty_tags_survive_normal_preparation_and_only_new_profile_gets_controls(tmp_path, fast_validator):
    source = empty_tag_source(tmp_path/'source'); raw = source.read_bytes(); before = logical_snapshot(source)
    report = execute(source, tmp_path/'prepared'); assert_output(report); data = decisions(report)
    assert data['inventory_profile'] == sidecar.EMPTY_TAG_INVENTORY_PROFILE
    assert len(empty_rows(data)) == 3 and all(row['structural_eligible'] and row['current'] == row['value'] == 'keep' for row in empty_rows(data))
    assert logical_snapshot(report['decision_source']['path']) == before
    engines = [item for item in report['processors'] if item['name'] == 'engine']
    assert len(engines) == 1 and engines[0]['status'] == 'skipped'
    for profile in OLD:
        old = sidecar.collect_decisions(report['decision_source']['path'], report['input']['sha256'], inventory_profile=profile)
        assert not any(row['kind'] == KIND for row in old['decisions'])
    previous = sidecar.collect_decisions(report['decision_source']['path'], report['input']['sha256'], inventory_profile=sidecar.FORM_INVENTORY_PROFILE)
    assert [row for row in data['decisions'] if row['kind'] != KIND] == previous['decisions']
    assert fresh_reviews(report, data) == [] and source.read_bytes() == raw


def test_reviewed_removals_preserve_content_navigation_and_saved_review_during_metadata_replay(tmp_path, fast_validator):
    source = empty_tag_source(tmp_path/'source'); raw = source.read_bytes()
    paint = independent_paint_and_navigation(source); expected = logical_snapshot(source, remove_empty=True)
    initial = execute(source, tmp_path/'initial'); data = decisions(initial); protected = files(Path(initial['bundle_path']))
    accept(data); plan = sidecar.write_sidecar(data, tmp_path/'accepted.json')
    edited = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=initial['bundle_path']); assert_output(edited)
    assert logical_snapshot(edited['output']['path']) == expected
    assert independent_paint_and_navigation(edited['output']['path']) == paint
    required = fresh_reviews(edited, data); assert len(required) == 3
    state = tmp_path/'review.json'; workspace.create_workspace(edited['bundle_path'], state); view = workspace.get_view(state)
    view = workspace.review_item(state, required[0]['id'], 'approved', REVIEWER, '2026-10-27', view['revision'], 'Retain this developer observation in the old review.')
    for kind, value in [('title', 'Reviewed research notes'), ('language', 'en-GB')]:
        row = next(row for row in view['decisions'] if row['kind'] == kind)
        view = workspace.edit_decision(state, row['id'], value, view['revision']); view = workspace.approve_decision(state, row['id'], REVIEWER, '2026-10-27', view['revision'])
    assert view['counts']['manual_approved'] == 0
    assert next(row for row in view['manual_items'] if row['id'] == required[0]['id'])['notes'].startswith('Retain this developer')
    saved = state.read_bytes(); export = workspace.export_workspace(state, tmp_path/'export', view['revision'])
    final = execute(source, tmp_path/'final', sidecar=export['sidecar_path'], decision_bundle=edited['bundle_path']); assert_output(final)
    assert logical_snapshot(final['output']['path']) == expected and independent_paint_and_navigation(final['output']['path']) == paint
    assert len(fresh_reviews(final, sidecar.load_sidecar(export['sidecar_path']))) == 3
    assert not any(row.get('notes') for row in final['manual_review']['items'])
    with pikepdf.open(final['output']['path']) as pdf: assert str(pdf.Root.Lang) == 'en-GB' and str(pdf.docinfo.Title) == 'Reviewed research notes'
    assert state.read_bytes() == saved and files(Path(initial['bundle_path'])) == protected and source.read_bytes() == raw


def test_pending_choice_stays_unapplied_and_cancellation_can_retry_unchanged_source(tmp_path, fast_validator):
    source = empty_tag_source(tmp_path/'source'); raw = source.read_bytes(); initial = execute(source, tmp_path/'initial'); data = decisions(initial)
    empty_rows(data)[0]['value'] = 'remove'; plan = sidecar.write_sidecar(data, tmp_path/'pending.json')
    pending = execute(source, tmp_path/'pending-result', sidecar=plan, decision_bundle=initial['bundle_path']); assert_output(pending)
    assert logical_snapshot(pending['output']['path']) == logical_snapshot(initial['output']['path'])
    retained = decisions(pending)
    assert any(row['value'] == 'remove' and row['status'] == 'pending' for row in empty_rows(retained))
    assert fresh_reviews(pending, retained) == []
    cancel = threading.Event(); cancel.set(); stopped = execute(source, tmp_path/'cancelled', cancel=cancel)
    assert stopped['cancelled'] is True and stopped['output'] is None
    cancel.clear(); retried = execute(source, tmp_path/'retry', cancel=cancel); assert_output(retried)
    assert len(empty_rows(decisions(retried))) == 3 and source.read_bytes() == raw


@pytest.mark.parametrize('hazard', ['description', 'dangling', 'alias'])
def test_negative_source_never_grants_removal_for_protected_first_leaf(tmp_path, fast_validator, hazard):
    source = empty_tag_source(tmp_path/'source', hazard=hazard); raw = source.read_bytes()
    data = sidecar.collect_decisions(source, inventory_profile=sidecar.EMPTY_TAG_INVENTORY_PROFILE); rows = empty_rows(data)
    assert any(not row['structural_eligible'] for row in rows)
    row = next(row for row in rows if not row['structural_eligible']); row['value'] = 'remove'; attempted = copy.deepcopy(row)
    with pytest.raises(sidecar.DecisionError): sidecar.bind_approval(row, REVIEWER, '2026-10-27')
    assert row == attempted
    # Even a caller that bypasses the approval API and forges its complete
    # digest cannot grant unsupported source-removal authority at Apply.
    row.update(status='approved', reviewer=REVIEWER, reviewed_at='2026-10-27')
    row['approval_sha256'] = sidecar.approval_digest(row)
    with pytest.raises(sidecar.DecisionError): sidecar.apply_decisions(source, tmp_path/'must-not-exist.pdf', data, data['source_sha256'])
    assert not (tmp_path/'must-not-exist.pdf').exists() and source.read_bytes() == raw
