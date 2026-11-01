"""Independent multi-level table plans, saved-profile replay and PDF preservation.

Only the strict CLI is a test double. Native qualification uses the same authored
fixture with the retained private runtime and the real strict validator.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import textwrap

import pikepdf
import pytest
from reportlab.pdfgen import canvas

from pdf_remediator import checks, inspection, pipeline, sidecar, workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import (TABLE_INVENTORY_PROFILE,FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE, SEMANTIC_TREE_INVENTORY_PROFILE,
    NAVIGATION_INVENTORY_PROFILE, PASSAGE_LANGUAGE_INVENTORY_PROFILE,
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE,
    LEGACY_INVENTORY_PROFILE, bind_approval, collect_decisions, file_sha256,
    load_sidecar, write_sidecar)
from test_artifact_structure_pipeline import canonical, files, independent_paint_and_navigation, exact_fidelity
from test_language import TEXTS
from test_language_scopes import registered_language_fonts
from test_pipeline import fast_validator, tagged_control

KIND = 'table-structure'
REVIEWER = 'Synthetic table-relationship reviewer'
OLD_PROFILES = [LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE,
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE, PASSAGE_LANGUAGE_INVENTORY_PROFILE,
    NAVIGATION_INVENTORY_PROFILE, SEMANTIC_TREE_INVENTORY_PROFILE]
SUMMARY = 'Participation by workshop and delivery method, with row totals.'
LABELS = ['Category', 'Participation', 'Total', 'Online', 'In person',
          'Workshop A', '12', '8', '20', 'Workshop B', '10', '6', '16']


def value(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def table_source(directory, *, hazard=None, repaired=False):
    """A visibly complete 4x4 table whose source metadata deliberately omits spans.

    Two header levels, row headers, row groups, immutable MCIDs and an unrelated
    document ID distinguish the independent oracle from the production writer.
    """
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    raw = directory/'paint.pdf'; path = directory/'source.pdf'
    c = canvas.Canvas(str(raw), pagesize=(560, 700), invariant=1)
    c.setTitle('Community participation table and research notes')
    def paint(mcid, tag, text, x, y, size=9, wrap=False):
        c._code.append('/'+tag+' <</MCID '+str(mcid)+'>> BDC')
        c.setFont('SyntheticVera', size)
        for index, line in enumerate(textwrap.wrap(text, width=96) if wrap else [text]):
            c.drawString(x, y-index*13, line)
        c._code.append('EMC')
    c.bookmarkPage('opening'); c.addOutlineEntry('Participation table', 'opening', level=0)
    paint(0, 'H1', 'Community participation by workshop', 28, 662, 15)
    positions = [(34, 610), (170, 610), (424, 610), (170, 578), (296, 578),
        (34, 542), (170, 542), (296, 542), (424, 542), (34, 508), (170, 508), (296, 508), (424, 508)]
    for mcid, (label, (x, y)) in enumerate(zip(LABELS, positions), 1):
        paint(mcid, 'TD', label, x, y)
    paint(14, 'P', TEXTS['en'], 28, 456, wrap=True)
    c.showPage(); c.bookmarkPage('continuation'); c.addOutlineEntry('Research continuation', 'continuation', level=0)
    paint(0, 'H1', 'Community research continuation', 28, 662, 15)
    paint(1, 'P', TEXTS['en'], 28, 625, wrap=True)
    paint(2, 'Link', 'Return to the participation table', 28, 45)
    c.showPage(); c.save()
    with pikepdf.open(raw) as pdf:
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        doc = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=tree))
        first, second = pdf.pages
        def element(role, parent, page, children=None):
            obj = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name('/'+role), P=parent, Pg=page.obj))
            if children is not None: obj.K = children
            return obj
        section = element('Sect', doc, first); heading = element('H1', section, first, 0)
        table = element('Table', section, first)
        head = element('THead', table, first); body = element('TBody', table, first)
        rows = [element('TR', head if i < 2 else body, first) for i in range(4)]
        cells = [element('TD', rows[r], first, mcid) for r, indices in enumerate([(1,2,3), (4,5), (6,7,8,9), (10,11,12,13)]) for mcid in indices]
        for row, subset in zip(rows, [cells[:3], cells[3:5], cells[5:9], cells[9:]]): row.K = pikepdf.Array(subset)
        head.K = pikepdf.Array(rows[:2]); body.K = pikepdf.Array(rows[2:]); table.K = pikepdf.Array([head, body])
        # Explicit defaults must survive plans that leave those values unchanged.
        cells[-1].A = pikepdf.Dictionary(O=pikepdf.Name.Table, RowSpan=1, ColSpan=1)
        paragraph = element('P', section, first, 14); paragraph.ID = pikepdf.String('outside-note')
        section.K = pikepdf.Array([heading, table, paragraph])
        section2 = element('Sect', doc, second); heading2 = element('H1', section2, second, 0)
        paragraph2 = element('P', section2, second, 1); link = element('Link', section2, second)
        annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([28,40,248,57]), Contents='Return to the participation table',
            NM='table-preserved-link', Border=pikepdf.Array([0,0,0]), F=4,
            Dest=pikepdf.Array([first.obj,pikepdf.Name.Fit]), StructParent=2))
        second.Annots = pikepdf.Array([annotation]); link.Alt = 'Read the participation table'
        link.K = pikepdf.Array([2,pikepdf.Dictionary(Type=pikepdf.Name.OBJR,Pg=second.obj,Obj=annotation)])
        section2.K = pikepdf.Array([heading2,paragraph2,link]); doc.K = pikepdf.Array([section,section2]); tree.K = doc
        tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([
            0,pikepdf.Array([heading,*cells,paragraph]),1,pikepdf.Array([heading2,paragraph2,link]),2,link])))
        tree.ParentTreeNextKey = 3
        tree.IDTree = pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array(['outside-note',paragraph])))
        for index,page in enumerate(pdf.pages): page.StructParents=index; page.Tabs=pikepdf.Name.S
        pdf.Root.StructTreeRoot=tree; pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True); pdf.Root.Lang='en-US'
        pdf.Root.ViewerPreferences=pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.Root.PageLabels=pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Dictionary(S=pikepdf.Name.r),1,pikepdf.Dictionary(S=pikepdf.Name.D,St=4)]))
        pdf.Root.Names=pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([
            'research-opening',pikepdf.Array([first.obj,pikepdf.Name.XYZ,0,680,None])])))
        pdf.Root.Outlines.First.F=2; pdf.Root.Outlines.First.C=pikepdf.Array([0.2,0.3,0.4])
        if repaired:
            roles=['TH','TH','TH','TH','TH','TH','TD','TD','TD','TH','TD','TD','TD']
            names=['h-category','h-participation','h-total','h-online','h-in-person','h-a',None,None,None,'h-b',None,None,None]
            references=[[],[],[],[1],[1],[0],[5,3,1],[5,4,1],[5,2],[0],[9,3,1],[9,4,1],[9,2]]
            for index,cell in enumerate(cells):
                cell.S=pikepdf.Name('/'+roles[index]); attr=cell.get('/A',pikepdf.Dictionary(O=pikepdf.Name.Table))
                if names[index]: cell.ID=pikepdf.String(names[index])
                if roles[index]=='TH': attr.Scope=pikepdf.Name.Row if index in {5,9} else pikepdf.Name.Column
                if references[index]: attr.Headers=pikepdf.Array([pikepdf.String(names[j]) for j in references[index]])
                if index in {0,2}: attr.RowSpan=2
                if index==1: attr.ColSpan=2
                cell.A=attr
            table.A=pikepdf.Dictionary(O=pikepdf.Name.Table,Summary=SUMMARY)
            indexed=[('outside-note',paragraph),*[(name,cell) for name,cell in zip(names,cells) if name]]
            tree.IDTree.Names=pikepdf.Array([item for name,node in sorted(indexed) for item in [pikepdf.String(name),node]])
        if hazard=='classmap': cells[0].C=pikepdf.Name.HeaderClass; tree.ClassMap=pikepdf.Dictionary(HeaderClass=pikepdf.Dictionary(O=pikepdf.Name.Table,Scope=pikepdf.Name.Column))
        elif hazard=='revision': cells[0].A=pikepdf.Array([cells[0].get('/A',pikepdf.Dictionary(O=pikepdf.Name.Table)),1])
        elif hazard=='duplicate-attributes': cells[0].A=pikepdf.Array([cells[0].get('/A',pikepdf.Dictionary(O=pikepdf.Name.Table)),pikepdf.Dictionary(O=pikepdf.Name.Table)])
        elif hazard=='unknown-attribute': cells[0].A=pikepdf.Dictionary(O=pikepdf.Name.Table,DeveloperMeaning='Retain unknown metadata')
        elif hazard=='aliased': pdf.Root['/DeveloperAlias']=cells[0]
        elif hazard=='missing-idtree': del tree['/IDTree']
        elif hazard=='duplicate-id': cells[0].ID='outside-note'
        elif hazard=='dangling-header': cells[6].A=pikepdf.Dictionary(O=pikepdf.Name.Table,Headers=pikepdf.Array(['missing-id']))
        elif hazard=='header-cycle': cells[0].A.Headers=pikepdf.Array(['h-online']); cells[3].A.Headers=pikepdf.Array(['h-category'])
        elif hazard=='non-th-header': cells[6].A.Headers=pikepdf.Array(['outside-note'])
        elif hazard=='out-of-table-span': cells[9].A.RowSpan=3
        elif hazard=='cross-group-span': cells[0].A.RowSpan=3
        elif hazard=='grid-hole': cells[1].A.ColSpan=1
        elif hazard=='idtree-bad-root-limits': tree.IDTree.Limits=pikepdf.Array(['incorrect-first','incorrect-last'])
        elif hazard in {'idtree-bad-leaf-limits','idtree-missing-leaf-limits','idtree-reversed-kids','idtree-overlapping-kids','idtree-empty-leaf'}:
            pairs=list(tree.IDTree.Names); leaves=[]
            for values in [pairs[:8],pairs[8:]]:
                leaves.append(pdf.make_indirect(pikepdf.Dictionary(Names=pikepdf.Array(values),Limits=pikepdf.Array([values[0],values[-2]]))))
            if hazard=='idtree-bad-leaf-limits': leaves[0].Limits=pikepdf.Array(['incorrect-first','incorrect-last'])
            elif hazard=='idtree-missing-leaf-limits': del leaves[0]['/Limits']
            elif hazard=='idtree-reversed-kids': leaves.reverse()
            elif hazard=='idtree-overlapping-kids': leaves[1].Names=pikepdf.Array([*pairs[:2],*list(leaves[1].Names)]); leaves[1].Limits=pikepdf.Array([pairs[0],pairs[-2]])
            elif hazard=='idtree-empty-leaf': leaves[0].Names=pikepdf.Array([]); del leaves[0]['/Limits']
            tree.IDTree=pikepdf.Dictionary(Kids=pikepdf.Array(leaves))
        elif hazard is not None: raise ValueError('Unknown authored table hazard')
        with path.open('wb') as stream: pdf.save(stream,deterministic_id=True)
    return path


def execute(source, output, **kwargs):
    return pipeline.process_file(source, output, RuntimeConfig(), **kwargs)


def data(report):
    return load_sidecar(Path(report['bundle_path'])/'decisions.json')


def choose(decisions):
    rows=[row for row in decisions['decisions'] if row['kind']==KIND]
    assert len(rows)==1,[(row['id'],row.get('structure_path')) for row in rows]
    assert rows[0]['structural_eligible'],rows[0].get('structural_limitations')
    return rows[0]


def selected_value(decisions):
    row=choose(decisions); cells=copy.deepcopy(json.loads(row['current'])['cells'])
    assert len(cells)==len(LABELS)==13
    names=['h-category','h-participation','h-total','h-online','h-in-person','h-a',None,None,None,'h-b',None,None,None]
    refs=[[],[],[],[1],[1],[0],[5,3,1],[5,4,1],[5,2],[0],[9,3,1],[9,4,1],[9,2]]
    for index,cell in enumerate(cells):
        cell.update(role='TH' if names[index] else 'TD', id=names[index],
            scope='Row' if index in {5,9} else 'Column' if names[index] else None,
            headers=[cells[j]['element'] for j in refs[index]],
            row_span=2 if index in {0,2} else 1,col_span=2 if index==1 else 1)
    return value({'summary':SUMMARY,'cells':cells})


def accept(decisions, new_value=None):
    row=choose(decisions); row['value']=selected_value(decisions) if new_value is None else new_value
    bind_approval(row,REVIEWER,'2026-10-27'); return row


def table_snapshot(path):
    """Raw metadata and immutable owner signatures keyed by the painted MCID."""
    with pikepdf.open(path) as pdf:
        tree=pdf.Root.StructTreeRoot; section=tree.K.K[0]; table=section.K[1]
        rows=[row for group in table.K for row in group.K]; cells=[cell for row in rows for cell in row.K]
        def attrs(node): return {str(k):canonical(v) for k,v in node.items() if k not in {'/P','/Pg','/K'}}
        return {'table':attrs(table),'cells':[{'mcid':int(cell.K),'attributes':attrs(cell)} for cell in cells],
            'rows':[[int(cell.K) for cell in row.K] for row in rows],
            'outside':attrs(section.K[2]),
            'idtree':{bytes(tree.IDTree.Names[i]).hex():int(tree.IDTree.Names[i+1].K) for i in range(0,len(tree.IDTree.Names),2)},
            'owners':[[int(node.K) if isinstance(node.K,int) else 'link' for node in tree.ParentTree.Nums[1]],
                      [int(node.K) if isinstance(node.K,int) else 'link' for node in tree.ParentTree.Nums[3]]]}


def expected_table(before):
    expected=copy.deepcopy(before); expected['table']['/A']=canonical(pikepdf.Dictionary(O=pikepdf.Name.Table,Summary=SUMMARY))
    names=['h-category','h-participation','h-total','h-online','h-in-person','h-a',None,None,None,'h-b',None,None,None]
    refs=[[],[],[],[1],[1],[0],[5,3,1],[5,4,1],[5,2],[0],[9,3,1],[9,4,1],[9,2]]
    for index,cell in enumerate(expected['cells']):
        attr=pikepdf.Dictionary(O=pikepdf.Name.Table)
        if index==12: attr.RowSpan=1; attr.ColSpan=1
        if names[index]:
            cell['attributes']['/S']=canonical(pikepdf.Name.TH); cell['attributes']['/ID']=canonical(pikepdf.String(names[index]))
            attr.Scope=pikepdf.Name.Row if index in {5,9} else pikepdf.Name.Column
            expected['idtree'][bytes(pikepdf.String(names[index])).hex()]=index+1
        if refs[index]: attr.Headers=pikepdf.Array([pikepdf.String(names[j]) for j in refs[index]])
        if index in {0,2}: attr.RowSpan=2
        if index==1: attr.ColSpan=2
        cell['attributes']['/A']=canonical(attr)
    return expected


def fresh_table_reviews(report, decisions):
    changed=[row for row in decisions['decisions'] if row['kind']==KIND and row['status']=='approved' and row['value']!=row['current']]
    items=[item for item in report['manual_review']['items'] if item['id'].startswith('table-structure-decision-')]
    assert len(items)==len(changed)
    assert report['manual_review']['artifact_sha256']==report['output']['sha256']
    for item,row in zip(items,changed):
        assert item['id']=='table-structure-decision-'+hashlib.sha256(row['id'].encode()).hexdigest()[:20]
        assert item['required'] is True and item['status']=='pending' and item['category']=='table-meaning'
        assert item['decision_id']==row['id'] and item['context_sha256']==row['context_sha256']
        assert item['evidence']=={'kind':row['kind'],'element':row.get('element'),'structure_path':row.get('structure_path'),
            'references':row['references'],'binding':row['binding'],'previous_value':row['current'],
            'applied_value':row['value'],'source_table_context':row['table_context']}
        assert not any(key in item for key in ['reviewer','reviewed_at','notes','approval_sha256'])
    return items


def assert_preserved(source, report):
    assert report['status'] in {'candidate','needs-manual'},report.get('error')
    exact_fidelity(report)
    assert report['data_sent']['document_api_calls']==0 and report['settings']['ocr_mode']=='off'
    assert report['inspection']['sha256']==report['fidelity']['after_sha256']==report['gate1']['input_sha256']==report['output']['sha256']
    assert independent_paint_and_navigation(source)==independent_paint_and_navigation(report['output']['path'])


def test_table_profile_retains_six_exact_older_inventories_and_unaccepted_original(tmp_path,fast_validator):
    source=table_source(tmp_path/'source');digest=file_sha256(source)
    prepared=execute(source,tmp_path/'prepared'); decisions=data(prepared)
    assert decisions['inventory_profile']==EMPTY_TAG_INVENTORY_PROFILE
    previous=collect_decisions(prepared['decision_source']['path'],digest,inventory_profile=TABLE_INVENTORY_PROFILE)
    assert [row for row in decisions['decisions'] if row['kind'] not in {'form-controls','empty-tag-removal'}]==previous['decisions']
    row=choose(decisions); assert row['status']=='pending' and row['current']==row['value']
    assert json.loads(row['current'])['summary'] is None
    prior=collect_decisions(prepared['decision_source']['path'],digest,inventory_profile=SEMANTIC_TREE_INVENTORY_PROFILE)
    assert [item for item in decisions['decisions'] if item['kind'] not in {KIND,'form-controls','empty-tag-removal'}]==prior['decisions']
    for profile in OLD_PROFILES:
        old=collect_decisions(prepared['decision_source']['path'],digest,inventory_profile=profile)
        assert not any(item['kind']==KIND for item in old['decisions'])
    assert fresh_table_reviews(prepared,decisions)==[] and file_sha256(source)==digest
    assert prepared['inspection']['table_relationships']['status']=='fail'
    assert_preserved(source,prepared)


def test_multilevel_headers_ids_spans_and_summary_have_exact_reviewed_delta_and_metadata_replay(tmp_path,fast_validator):
    source=table_source(tmp_path/'source');digest=file_sha256(source);prepared=execute(source,tmp_path/'prepared')
    decisions=data(prepared); before=table_snapshot(prepared['decision_source']['path']); protected=files(Path(prepared['bundle_path']))
    accept(decisions); plan=write_sidecar(decisions,tmp_path/'accepted.json')
    result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result); assert table_snapshot(result['output']['path'])==expected_table(before)
    assert result['inspection']['table_relationships']['status']=='pass'
    assert next(item for item in result['gate2']['checks'] if item['id']=='table-header-associations')['status']=='pass'
    assert len(fresh_table_reviews(result,decisions))==1
    state=tmp_path/'review.json'; workspace.create_workspace(result['bundle_path'],state); view=workspace.get_view(state)
    fresh=next(item for item in view['manual_items'] if item['id'].startswith('table-structure-decision-'))
    view=workspace.review_item(state,fresh['id'],'approved',REVIEWER,'2026-10-27',view['revision'],'Retain this earlier table observation after metadata changes.')
    for kind,new in [('title','Reviewed participation table - metadata follow-up'),('language','en-GB')]:
        row=next(row for row in view['decisions'] if row['kind']==kind)
        view=workspace.edit_decision(state,row['id'],new,view['revision'])
        view=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    assert view['counts']['manual_approved']==0
    assert next(item for item in view['manual_items'] if item['id']==fresh['id'])['notes'].startswith('Retain')
    saved=state.read_bytes(); exported=workspace.export_workspace(state,tmp_path/'metadata-plan',view['revision'])
    later=execute(source,tmp_path/'metadata',sidecar=exported['sidecar_path'],decision_bundle=result['bundle_path'])
    assert_preserved(source,later); assert table_snapshot(later['output']['path'])==table_snapshot(result['output']['path'])
    assert len(fresh_table_reviews(later,data(later)))==1
    assert state.read_bytes()==saved and file_sha256(source)==digest and files(Path(prepared['bundle_path']))==protected


@pytest.mark.parametrize('profile',OLD_PROFILES)
def test_six_older_saved_profiles_reopen_without_new_table_choices_or_note_loss(tmp_path,fast_validator,monkeypatch,profile):
    source=table_source(tmp_path/'source'); original=sidecar.collect_decisions
    def older(path,source_sha=None,**kwargs): return original(path,source_sha,inventory_profile=profile)
    with monkeypatch.context() as selected:
        selected.setattr(sidecar,'collect_decisions',older); report=execute(source,tmp_path/'prepared')
    decisions=data(report); assert sidecar.inventory_profile_for(decisions)==profile
    assert not any(row['kind']==KIND for row in decisions['decisions'])
    state=tmp_path/'older-review.json'; workspace.create_workspace(report['bundle_path'],state)
    view=workspace.review_item(state,'table-relationships','blocked',REVIEWER,'2026-10-27',0,'Keep the older table problem note.')
    saved=state.read_bytes(); assert workspace.get_view(state)==view and state.read_bytes()==saved


def test_table_edits_cannot_use_automatic_title_figure_authority(tmp_path,fast_validator):
    source=table_source(tmp_path/'source'); prepared=execute(source,tmp_path/'prepared'); decisions=data(prepared); row=choose(decisions)
    with pytest.raises(sidecar.DecisionError): sidecar.make_automatic_authorization(decisions['source_sha256'],decisions['document_sha256'],'2026-10-27',decision_ids=[row['id']])
    row['value']=selected_value(decisions); row['status']='auto-accepted'; row['automatic_acceptance_sha256']='0'*64
    plan=write_sidecar(decisions,tmp_path/'forged.json'); protected=files(Path(prepared['bundle_path']))
    result=execute(source,tmp_path/'refused',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert result['status']=='failed' and result['output'] is None and files(Path(prepared['bundle_path']))==protected


@pytest.mark.parametrize('hazard',['classmap','revision','duplicate-attributes','unknown-attribute','aliased'])
def test_ambiguous_or_shared_table_scopes_remain_readonly(tmp_path,hazard):
    source=table_source(tmp_path/'source',hazard=hazard); digest=file_sha256(source)
    decisions=collect_decisions(source,inventory_profile=TABLE_INVENTORY_PROFILE)
    rows=[row for row in decisions['decisions'] if row['kind']==KIND]
    assert rows and not any(row['structural_eligible'] for row in rows)
    assert all(row['structural_limitations'] and row['value']==row['current'] for row in rows)
    assert file_sha256(source)==digest


@pytest.mark.parametrize('hazard',['missing-idtree','duplicate-id','dangling-header','header-cycle','non-th-header','out-of-table-span','cross-group-span','grid-hole',
    'idtree-bad-root-limits','idtree-bad-leaf-limits','idtree-missing-leaf-limits','idtree-reversed-kids','idtree-overlapping-kids','idtree-empty-leaf'])
def test_independent_raw_table_assessment_refuses_seeded_integrity_defects(tmp_path,hazard):
    source=table_source(tmp_path/'source',repaired=True,hazard=hazard)
    report=inspection.inspect_pdf(source); relationships=report['table_relationships']
    assert relationships['policy']=='bounded-table-relationships-1' and relationships['status']=='fail'
    supplemental=checks.assess(report)
    assert next(item for item in supplemental['checks'] if item['id']=='table-header-associations')['status']=='fail'


@pytest.mark.parametrize('hazard',['classmap','revision','duplicate-attributes'])
def test_independent_raw_table_assessment_reports_uninterpreted_attribute_authority(tmp_path,hazard):
    report=inspection.inspect_pdf(table_source(tmp_path/'source',repaired=True,hazard=hazard))
    assert report['table_relationships']['status']=='needs-review'


def test_scope_only_header_tables_need_neither_ids_nor_summaries(tmp_path):
    source=table_source(tmp_path/'source',repaired=True); changed=tmp_path/'scope-only.pdf'
    with pikepdf.open(source) as pdf:
        tree=pdf.Root.StructTreeRoot; section=tree.K.K[0]; table=section.K[1]
        for group in table.K:
            for row in group.K:
                for cell in row.K:
                    if '/ID' in cell: del cell['/ID']
                    if '/Headers' in cell.A: del cell.A['/Headers']
        del table.A['/Summary']; del section.K[2]['/ID']; del tree['/IDTree']
        pdf.save(changed)
    report=inspection.inspect_pdf(changed)
    assert report['table_relationships']['status']=='pass'
    assert not report['table_relationships']['document_id_issues']


def test_table_assessment_does_not_trust_an_unknown_declared_policy(tmp_path):
    report=inspection.inspect_pdf(table_source(tmp_path/'source'))
    report['table_relationships']={'policy':'forged-unmeasured-policy','status':'pass'}
    supplemental=checks.assess(report)
    assert next(item for item in supplemental['checks'] if item['id']=='table-header-associations')['status']=='fail'


@pytest.mark.parametrize('navigation_kind',['annotation-name','link-name','link-target','bookmark-entry','bookmark-additions'])
def test_table_profile_navigation_changes_keep_exact_fidelity_and_replay(tmp_path,fast_validator,navigation_kind):
    from test_navigation_pipeline import accept as accept_navigation,nav_snapshot
    source=table_source(tmp_path/'source'); prepared=execute(source,tmp_path/'prepared'); decisions=data(prepared)
    accept(decisions); accept_navigation(decisions,navigation_kind)
    plan=write_sidecar(decisions,tmp_path/'accepted.json'); result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert result['status'] in {'candidate','needs-manual'},result.get('error'); exact_fidelity(result)
    assert result['fidelity']['reviewed_navigation']['expected_common_navigation_matches'] is True
    assert len(result['fidelity']['reviewed_navigation']['deltas'])==1
    assert len(fresh_table_reviews(result,decisions))==1
    table=table_snapshot(result['output']['path']); nav=nav_snapshot(result['output']['path'])
    title=next(row for row in decisions['decisions'] if row['kind']=='title'); title['value']='Replayed reviewed table and navigation'; bind_approval(title,REVIEWER,'2026-10-27')
    later_plan=write_sidecar(decisions,tmp_path/'later.json'); later=execute(source,tmp_path/'later',sidecar=later_plan,decision_bundle=result['bundle_path'])
    assert later['status'] in {'candidate','needs-manual'},later.get('error'); exact_fidelity(later)
    assert table_snapshot(later['output']['path'])==table and nav_snapshot(later['output']['path'])==nav
    assert len(fresh_table_reviews(later,data(later)))==1
