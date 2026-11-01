"""Independent authored semantic-tree integration and exact preservation checks.

Only the strict CLI is a test double. PDFs, ownership, typed decisions, saved
reviews, render/text fidelity and immutable bundles are real developer evidence.
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

from pdf_remediator import pipeline,sidecar,workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import (SEMANTIC_TREE_INVENTORY_PROFILE,TABLE_INVENTORY_PROFILE,FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE,NAVIGATION_INVENTORY_PROFILE,
    PASSAGE_LANGUAGE_INVENTORY_PROFILE,ARTIFACT_STRUCTURE_INVENTORY_PROFILE,
    STRUCTURAL_INVENTORY_PROFILE,LEGACY_INVENTORY_PROFILE,bind_approval,collect_decisions,
    file_sha256,load_sidecar,write_sidecar)
from test_artifact_structure_pipeline import canonical,files,independent_paint_and_navigation,exact_fidelity
from test_language import TEXTS
from test_language_scopes import registered_language_fonts
from test_pipeline import fast_validator,tagged_control

KINDS={'semantic-role','reading-order','tree-move','semantic-list'}
REVIEWER='Synthetic semantic-tree reviewer'
SECTION='root/K/K/0'
DIV_A=SECTION+'/K/1'
DIV_B=SECTION+'/K/2'
DIV_C=SECTION+'/K/3'
PATHS={'semantic-role':DIV_A+'/K/0','reading-order':DIV_C,
    'tree-move':DIV_B+'/K/0','semantic-list':DIV_A}
OLD_PROFILES=[LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE,PASSAGE_LANGUAGE_INVENTORY_PROFILE,NAVIGATION_INVENTORY_PROFILE]


def value(data):return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def semantic_source(directory,*,hazard=None,existing_list=False):
    """Two licensed-font pages with separated candidate labels and bodies.

    Every text owner/MCID is authored independently of the production editor.
    The three neutral containers permit independent list, move and order edits.
    """
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    raw=directory/'paint.pdf';path=directory/'source.pdf'
    c=canvas.Canvas(str(raw),pagesize=(460,640),invariant=1)
    c.setTitle('Authored semantic tree and reading order control')
    def paint(mcid,tag,text,x,y,size=9,wrap=False):
        c._code.append('/'+tag+' <</MCID '+str(mcid)+'>> BDC');c.setFont('SyntheticVera',size)
        for index,line in enumerate(textwrap.wrap(text,width=84) if wrap else [text]):c.drawString(x,y-index*13,line)
        c._code.append('EMC')
    c.bookmarkPage('opening');c.addOutlineEntry('Opening research plan','opening',level=0)
    paint(0,'H1','Community research plan',28,603,15)
    paint(1,'H2','This is supporting information, not a section heading.',28,575,10)
    paint(2,'P','1.',28,542);paint(3,'P','Prepare clear questions before the community meeting.',55,542)
    paint(4,'P','2.',28,512);paint(5,'P','Compare the findings before deciding which project to support.',55,512)
    paint(6,'P','Move this existing paragraph only after reviewing its surrounding context.',28,462)
    paint(7,'P',TEXTS['en'],28,430,wrap=True)
    paint(8,'P','The first authored reading-order passage discusses the local research.',28,172)
    paint(9,'P','The second authored passage describes the participants and their decisions.',28,142)
    c.showPage();c.bookmarkPage('continuation');c.addOutlineEntry('Research continuation','continuation',level=0)
    paint(0,'H1','Community research continuation',28,603,15)
    paint(1,'P',TEXTS['en'],28,570,wrap=True)
    paint(2,'Link','Return to the opening research page',28,45)
    c.showPage();c.save()
    with pikepdf.open(raw) as pdf:
        tree=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        doc=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Document,P=tree))
        first,second=pdf.pages
        def element(role,parent,page,children=None):
            node=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name('/'+role),P=parent,Pg=page.obj))
            if children is not None:node.K=children
            return node
        section=element('Sect',doc,first);divs=[element('Div',section,first) for _ in range(3)]
        a,b,d=divs;owners=[]
        for mcid in range(10):
            parent=section if mcid==0 else a if mcid<=5 else b if mcid<=7 else d
            owners.append(element('H1' if mcid==0 else 'H2' if mcid==1 else 'P',parent,first,mcid))
        a.K=pikepdf.Array(owners[1:6]);b.K=pikepdf.Array(owners[6:8]);d.K=pikepdf.Array(owners[8:10])
        if existing_list:
            listed=element('L',a,first);listed.A=pikepdf.Dictionary(O=pikepdf.Name.List,ListNumbering=pikepdf.Name.Decimal)
            items=[]
            for label,body in [(owners[2],owners[3]),(owners[4],owners[5])]:
                item=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.LI,P=listed))
                label.S=pikepdf.Name.Lbl;label.P=item;body.P=item
                item.K=pikepdf.Array([label,body]);items.append(item)
            listed.K=pikepdf.Array(items);a.K=pikepdf.Array([owners[1],listed])
        section.K=pikepdf.Array([owners[0],a,b,d])
        section2=element('Sect',doc,second)
        heading=element('H1',section2,second,0);paragraph=element('P',section2,second,1)
        link=element('Link',section2,second)
        annotation=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([28,40,248,57]),Contents='Return to the opening research page',
            NM='semantic-tree-preserved-link',Border=pikepdf.Array([0,0,0]),F=4,
            Dest=pikepdf.Array([first.obj,pikepdf.Name.Fit]),StructParent=2))
        second.Annots=pikepdf.Array([annotation]);link.Alt='Read the opening research plan'
        link.K=pikepdf.Array([2,pikepdf.Dictionary(Type=pikepdf.Name.OBJR,Pg=second.obj,Obj=annotation)])
        section2.K=pikepdf.Array([heading,paragraph,link]);doc.K=pikepdf.Array([section,section2]);tree.K=doc
        tree.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([
            0,pikepdf.Array(owners),1,pikepdf.Array([heading,paragraph,link]),2,link])))
        tree.ParentTreeNextKey=3
        for index,page in enumerate(pdf.pages):page.StructParents=index;page.Tabs=pikepdf.Name.S
        pdf.Root.StructTreeRoot=tree;pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True);pdf.Root.Lang='en-US'
        pdf.Root.ViewerPreferences=pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.Root.PageLabels=pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Dictionary(S=pikepdf.Name.r),
            1,pikepdf.Dictionary(S=pikepdf.Name.D,St=4)]))
        pdf.Root.Names=pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([
            'research-opening',pikepdf.Array([first.obj,pikepdf.Name.XYZ,0,620,None])])))
        pdf.Root.Outlines.First.F=2;pdf.Root.Outlines.First.C=pikepdf.Array([0.2,0.3,0.4])
        if hazard=='different-language':a.Lang='fr'
        elif hazard=='source-language':b.Lang='fr'
        elif hazard=='actual-text':a.ActualText='Keep the original replacement meaning'
        elif hazard=='alternate-text':a.Alt='Preserved inherited description'
        elif hazard=='expansion':a.E='Preserved inherited expansion'
        elif hazard=='attributes':a.A=pikepdf.Dictionary(O=pikepdf.Name.Layout,WritingMode=pikepdf.Name.RlTb)
        elif hazard=='aliased':pdf.Root['/DeveloperAlias']=owners[6]
        elif hazard=='rolemap':tree.RoleMap=pikepdf.Dictionary(L=pikepdf.Name.P)
        elif hazard=='cross-page':owners[8].Pg=second.obj
        elif hazard=='cycle':a.K=pikepdf.Array([a,*owners[1:6]])
        elif hazard=='shared':b.K=pikepdf.Array([owners[6],owners[7],owners[3]])
        elif hazard is not None:raise ValueError('Unknown authored hazard')
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    return path


def execute(source,output,**kwargs):return pipeline.process_file(source,output,RuntimeConfig(),**kwargs)
def data(report):return load_sidecar(Path(report['bundle_path'])/'decisions.json')


def choose(decisions,kind,path=None):
    rows=[row for row in decisions['decisions'] if row['kind']==kind and row.get('structure_path')==(path or PATHS[kind])]
    assert len(rows)==1,(kind,path,[(row['id'],row.get('structure_path')) for row in decisions['decisions'] if row['kind']==kind])
    assert rows[0]['structural_eligible'],rows[0].get('structural_limitations')
    return rows[0]


def selected_value(decisions,kind,*,reverse_list=False):
    row=choose(decisions,kind)
    if kind=='semantic-role':return 'P'
    if kind=='reading-order':return value({'children':list(reversed(json.loads(row['current'])['children']))})
    context=row['tree_context']
    if kind=='tree-move':
        parent=next(item for item in context['parent_choices'] if item['role'].lstrip('/')=='Sect' and item['page']==1)
        return value({'parent':parent['element'],'index':1})
    children=context['children']
    pairs=[{'label':children[1]['element'],'body':children[2]['element']},
        {'label':children[3]['element'],'body':children[4]['element']}]
    return value({'items':list(reversed(pairs)) if reverse_list else pairs,'numbering':'Decimal'})


def accept(decisions,kind,new_value=None):
    row=choose(decisions,kind);row['value']=selected_value(decisions,kind) if new_value is None else new_value
    bind_approval(row,REVIEWER,'2026-10-27');return row


def logical_snapshot(path):
    """Independent logical tree, backlinks and MCID/annotation owner signatures."""
    with pikepdf.open(path) as pdf:
        pages={page.obj.objgen:index+1 for index,page in enumerate(pdf.pages)};seen=set()
        def signature(node):
            values=node.get('/K');values=list(values) if isinstance(values,pikepdf.Array) else [values]
            return {'page':pages.get(node.get('/Pg').objgen) if '/Pg' in node else None,
                'mcids':[item for item in values if isinstance(item,int)],
                'objects':[str(item['/Obj'].get('/NM','')) for item in values if isinstance(item,pikepdf.Dictionary) and item.get('/Type')==pikepdf.Name.OBJR]}
        def walk(node,parent):
            if node is None:return None
            if isinstance(node,pikepdf.Array):return [walk(child,parent) for child in node]
            if isinstance(node,int):return {'mcid':node}
            assert isinstance(node,pikepdf.Dictionary)
            if node.get('/Type')==pikepdf.Name.OBJR:
                return {'object_reference':str(node['/Obj'].get('/NM','')),'page':pages[node['/Pg'].objgen]}
            assert node.objgen not in seen and node.get('/Type')==pikepdf.Name.StructElem
            seen.add(node.objgen);assert node['/P'].objgen==parent.objgen
            return {'role':str(node['/S']),'attributes':{str(k):canonical(v) for k,v in node.items() if k not in {'/S','/K','/P','/Pg'}},
                'page':pages[node['/Pg'].objgen] if '/Pg' in node else None,'children':walk(node.get('/K'),node)}
        tree=pdf.Root.StructTreeRoot;logical=walk(tree.K,tree);owners={}
        def number_tree(node):
            nums=node.get('/Nums',[]);assert len(nums)%2==0
            for i in range(0,len(nums),2):
                key=int(nums[i]);assert key not in owners;values=nums[i+1]
                owners[key]=[None if item is None else signature(item) for item in values] if isinstance(values,pikepdf.Array) else signature(values)
            for child in node.get('/Kids',[]):number_tree(child)
        number_tree(tree.ParentTree)
        marks=[hashlib.sha256(pikepdf.unparse_content_stream(list(pikepdf.parse_content_stream(page)))).hexdigest() for page in pdf.pages]
        return {'logical':logical,'owners':owners,'root':{str(k):canonical(v) for k,v in tree.items() if k not in {'/K','/ParentTree'}},'marks':marks}


def expected_logical(before,kinds,*,reverse_list=False):
    result=copy.deepcopy(before);section=result['logical']['children'][0];a,b,c=section['children'][1:4]
    if 'semantic-role' in kinds:a['children'][0]['role']='/P'
    if 'reading-order' in kinds:c['children'].reverse()
    if 'semantic-list' in kinds:
        leaves=a['children'][1:5];items=[]
        for label,body in [(leaves[0],leaves[1]),(leaves[2],leaves[3])]:
            label['role']='/Lbl';body['role']='/LBody'
            items.append({'role':'/LI','attributes':{'/Type':{'name':'/StructElem'}},'page':None,'children':[label,body]})
        if reverse_list:items.reverse()
        new={'role':'/L','attributes':{'/Type':{'name':'/StructElem'},'/A':{'/O':{'name':'/List'},'/ListNumbering':{'name':'/Decimal'}}},
            'page':1,'children':items}
        a['children'][1:5]=[new]
    if 'tree-move' in kinds:section['children'].insert(1,b['children'].pop(0))
    return result


def fresh_tree_reviews(report,decisions):
    changed={row['id']:row for row in decisions['decisions'] if row['kind'] in KINDS and row['status']=='approved' and row['value']!=row['current']}
    items=[item for item in report['manual_review']['items'] if item['id'].startswith('semantic-tree-decision-')]
    assert len(items)==len(changed)==len({item['id'] for item in items})
    assert {item['decision_id'] for item in items}==set(changed)
    assert report['manual_review']['artifact_sha256']==report['output']['sha256']
    for item in items:
        decision=changed[item['decision_id']]
        assert item['id']=='semantic-tree-decision-'+hashlib.sha256(decision['id'].encode()).hexdigest()[:20]
        assert item['category']=='reading-order' and item['required'] is True and item['status']=='pending'
        assert item['page']==decision.get('page') and item['context_sha256']==decision['context_sha256']
        assert item['evidence']=={'kind':decision['kind'],'element':decision.get('element'),'structure_path':decision.get('structure_path'),
            'references':decision['references'],'binding':decision['binding'],'previous_value':decision['current'],
            'applied_value':decision['value'],'source_tree_context':decision['tree_context']}
        assert not any(key in item for key in ['reviewer','reviewed_at','notes','approval_sha256'])
    return items


def assert_preserved(source,report):
    assert report['status'] in {'candidate','needs-manual'},report.get('error')
    exact_fidelity(report)
    assert report['data_sent']['document_api_calls']==0 and report['settings']['ocr_mode']=='off'
    assert report['inspection']['sha256']==report['fidelity']['after_sha256']==report['gate1']['input_sha256']==report['output']['sha256']
    assert independent_paint_and_navigation(source)==independent_paint_and_navigation(report['output']['path'])


def test_new_semantic_profile_is_pending_and_five_older_profiles_remain_exact(tmp_path,fast_validator):
    source=semantic_source(tmp_path/'source');before=file_sha256(source);report=execute(source,tmp_path/'prepared');decisions=data(report)
    assert decisions['inventory_profile']==EMPTY_TAG_INVENTORY_PROFILE
    assert KINDS<={row['kind'] for row in decisions['decisions']}
    previous=collect_decisions(report['decision_source']['path'],before,inventory_profile=SEMANTIC_TREE_INVENTORY_PROFILE)
    assert [row for row in decisions['decisions'] if row['kind'] not in {'table-structure','form-controls','empty-tag-removal'}]==previous['decisions']
    assert all(row['status']=='pending' and row['value']==row['current'] for row in decisions['decisions'])
    for kind in KINDS:choose(decisions,kind)
    for profile in OLD_PROFILES:
        old=collect_decisions(report['decision_source']['path'],before,inventory_profile=profile)
        assert not any(row['kind'] in KINDS for row in old['decisions'])
    old=collect_decisions(report['decision_source']['path'],before,inventory_profile=NAVIGATION_INVENTORY_PROFILE)
    assert [row for row in decisions['decisions'] if row['kind'] not in KINDS | {'table-structure','form-controls','empty-tag-removal'}]==old['decisions']
    assert {k:v for k,v in decisions.items() if k not in {'inventory_profile','decisions'}}=={k:v for k,v in old.items() if k not in {'inventory_profile','decisions'}}
    assert fresh_tree_reviews(report,decisions)==[] and file_sha256(source)==before
    assert_preserved(source,report)


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_each_named_tree_edit_has_only_its_exact_logical_delta_and_fresh_review(tmp_path,fast_validator,kind):
    source=semantic_source(tmp_path/'source');prepared=execute(source,tmp_path/'prepared');decisions=data(prepared)
    protected=files(Path(prepared['bundle_path']));before=logical_snapshot(prepared['decision_source']['path'])
    accept(decisions,kind);plan=write_sidecar(decisions,tmp_path/'accepted.json')
    result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result)
    assert logical_snapshot(result['output']['path'])==expected_logical(before,{kind})
    assert len(fresh_tree_reviews(result,decisions))==1 and files(Path(prepared['bundle_path']))==protected


def test_disjoint_list_order_move_and_heading_demotion_compose_and_metadata_replays(tmp_path,fast_validator):
    source=semantic_source(tmp_path/'source');source_hash=file_sha256(source);prepared=execute(source,tmp_path/'prepared');decisions=data(prepared)
    before=logical_snapshot(prepared['decision_source']['path']);protected=files(Path(prepared['bundle_path']))
    for kind in sorted(KINDS):accept(decisions,kind)
    plan=write_sidecar(decisions,tmp_path/'accepted.json');result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result);assert logical_snapshot(result['output']['path'])==expected_logical(before,KINDS)
    assert len(fresh_tree_reviews(result,decisions))==4
    state=tmp_path/'edited-review.json';workspace.create_workspace(result['bundle_path'],state);view=workspace.get_view(state)
    fresh=next(item for item in view['manual_items'] if item['id'].startswith('semantic-tree-decision-'))
    view=workspace.review_item(state,fresh['id'],'approved',REVIEWER,'2026-10-27',view['revision'],'Retain this earlier observation without carrying its approval.')
    for kind,new_value in [('title','Reviewed semantic tree - metadata follow-up'),('language','en-GB')]:
        row=next(item for item in view['decisions'] if item['kind']==kind)
        view=workspace.edit_decision(state,row['id'],new_value,view['revision'])
        view=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    assert view['counts']['manual_approved']==0 and next(item for item in view['manual_items'] if item['id']==fresh['id'])['notes'].startswith('Retain')
    previous_state=state.read_bytes();export=workspace.export_workspace(state,tmp_path/'metadata-plan',view['revision'])
    later=execute(source,tmp_path/'metadata-result',sidecar=export['sidecar_path'],decision_bundle=result['bundle_path'])
    assert_preserved(source,later);assert logical_snapshot(later['output']['path'])==logical_snapshot(result['output']['path'])
    assert len(fresh_tree_reviews(later,data(later)))==4
    with pikepdf.open(later['output']['path']) as pdf:assert str(pdf.Root.Lang)=='en-GB' and str(pdf.docinfo.Title)=='Reviewed semantic tree - metadata follow-up'
    assert state.read_bytes()==previous_state and files(Path(prepared['bundle_path']))==protected and file_sha256(source)==source_hash


def test_explicit_list_item_order_can_reverse_and_replay_without_rearranging_page_text(tmp_path,fast_validator):
    source=semantic_source(tmp_path/'source');prepared=execute(source,tmp_path/'prepared');decisions=data(prepared)
    before=logical_snapshot(prepared['decision_source']['path'])
    accept(decisions,'semantic-list',selected_value(decisions,'semantic-list',reverse_list=True))
    plan=write_sidecar(decisions,tmp_path/'accepted.json');result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result);assert logical_snapshot(result['output']['path'])==expected_logical(before,{'semantic-list'},reverse_list=True)
    title=next(row for row in decisions['decisions'] if row['kind']=='title');title['value']='Replayed reversed list';bind_approval(title,REVIEWER,'2026-10-27')
    second=write_sidecar(decisions,tmp_path/'later.json');later=execute(source,tmp_path/'later',sidecar=second,decision_bundle=result['bundle_path'])
    assert_preserved(source,later);assert logical_snapshot(later['output']['path'])==logical_snapshot(result['output']['path'])


def test_explicit_unlabelled_existing_paragraphs_form_a_list_without_generated_labels(tmp_path,fast_validator):
    source=semantic_source(tmp_path/'source');prepared=execute(source,tmp_path/'prepared');decisions=data(prepared)
    row=choose(decisions,'semantic-list',DIV_C);children=row['tree_context']['children']
    row['value']=value({'items':[{'label':None,'body':child['element']} for child in children],'numbering':'None'})
    bind_approval(row,REVIEWER,'2026-10-27');plan=write_sidecar(decisions,tmp_path/'accepted.json')
    before=logical_snapshot(prepared['decision_source']['path']);expected=copy.deepcopy(before)
    c=expected['logical']['children'][0]['children'][3];items=[]
    for body in c['children']:
        body['role']='/LBody';items.append({'role':'/LI','attributes':{'/Type':{'name':'/StructElem'}},'page':None,'children':[body]})
    c['children']=[{'role':'/L','attributes':{'/Type':{'name':'/StructElem'},'/A':{'/O':{'name':'/List'},'/ListNumbering':{'name':'/None'}}},'page':1,'children':items}]
    result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result);assert logical_snapshot(result['output']['path'])==expected
    assert len(fresh_tree_reviews(result,decisions))==1


def test_existing_list_body_role_errors_can_be_explicitly_corrected_together(tmp_path,fast_validator):
    source=semantic_source(tmp_path/'source',existing_list=True);prepared=execute(source,tmp_path/'prepared');decisions=data(prepared)
    before=logical_snapshot(prepared['decision_source']['path']);expected=copy.deepcopy(before)
    paths=[DIV_A+'/K/1/K/0/K/1',DIV_A+'/K/1/K/1/K/1']
    for path in paths:
        row=choose(decisions,'semantic-role',path);assert row['current']=='P';row['value']='LBody';bind_approval(row,REVIEWER,'2026-10-27')
    for item in expected['logical']['children'][0]['children'][1]['children'][1]['children']:item['children'][1]['role']='/LBody'
    plan=write_sidecar(decisions,tmp_path/'accepted.json');result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result);assert logical_snapshot(result['output']['path'])==expected
    assert len(fresh_tree_reviews(result,decisions))==2


@pytest.mark.parametrize('profile',OLD_PROFILES)
def test_five_older_saved_profiles_reopen_without_new_tree_choices_or_note_loss(tmp_path,fast_validator,monkeypatch,profile):
    source=semantic_source(tmp_path/'source');original=sidecar.collect_decisions
    def older(path,source_sha=None,**kwargs):return original(path,source_sha,inventory_profile=profile)
    with monkeypatch.context() as selected:
        selected.setattr(sidecar,'collect_decisions',older);report=execute(source,tmp_path/'prepared')
    decisions=data(report);assert sidecar.inventory_profile_for(decisions)==profile
    assert not any(row['kind'] in KINDS for row in decisions['decisions'])
    state=tmp_path/'older-review.json';workspace.create_workspace(report['bundle_path'],state)
    view=workspace.review_item(state,'reading-order','blocked',REVIEWER,'2026-10-27',0,'Keep the older structural problem note.')
    saved=state.read_bytes();assert workspace.get_view(state)==view and state.read_bytes()==saved


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_semantic_edits_cannot_use_automatic_title_figure_authority(tmp_path,fast_validator,kind):
    source=semantic_source(tmp_path/'source');prepared=execute(source,tmp_path/'prepared');decisions=data(prepared);row=choose(decisions,kind)
    with pytest.raises(sidecar.DecisionError):sidecar.make_automatic_authorization(decisions['source_sha256'],decisions['document_sha256'],'2026-10-27',decision_ids=[row['id']])
    row['value']=selected_value(decisions,kind);row['status']='auto-accepted';row['automatic_acceptance_sha256']='0'*64
    plan=write_sidecar(decisions,tmp_path/'forged.json');protected=files(Path(prepared['bundle_path']))
    result=execute(source,tmp_path/'refused',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert result['status']=='failed' and result['output'] is None and files(Path(prepared['bundle_path']))==protected


@pytest.mark.parametrize('hazard,kind,path',[
    ('actual-text','semantic-list',DIV_A),('alternate-text','semantic-list',DIV_A),
    ('expansion','semantic-list',DIV_A),('attributes','semantic-list',DIV_A),
    ('aliased','tree-move',DIV_B+'/K/0'),('rolemap','semantic-list',DIV_A),
    ('cross-page','reading-order',DIV_C),('shared','semantic-list',DIV_A),('cycle','semantic-list',DIV_A),
])
def test_ambiguous_shared_replacement_or_inherited_attribute_scopes_remain_readonly(tmp_path,hazard,kind,path):
    source=semantic_source(tmp_path/'source',hazard=hazard);before=file_sha256(source)
    decisions=collect_decisions(source,inventory_profile=SEMANTIC_TREE_INVENTORY_PROFILE)
    rows=[row for row in decisions['decisions'] if row['kind']==kind and row.get('structure_path')==path]
    assert not any(row.get('structural_eligible') for row in rows)
    for row in rows:assert row['structural_limitations'] and row['status']=='pending' and row['value']==row['current']
    assert file_sha256(source)==before


def test_moves_cannot_silently_change_an_inherited_passage_language(tmp_path):
    source=semantic_source(tmp_path/'source',hazard='source-language');before=file_sha256(source)
    decisions=collect_decisions(source,inventory_profile=SEMANTIC_TREE_INVENTORY_PROFILE)
    rows=[row for row in decisions['decisions'] if row['kind']=='tree-move' and row.get('structure_path')==PATHS['tree-move']]
    assert not any(parent['role'].lstrip('/')=='Sect' for row in rows for parent in row['tree_context']['parent_choices'])
    assert file_sha256(source)==before


@pytest.mark.parametrize('conflict',['same-heading-role','list-selected-leaf-heading','order-and-list','order-and-move'])
def test_overlapping_or_contradictory_authored_changes_refuse_without_publishing(tmp_path,fast_validator,conflict):
    source=semantic_source(tmp_path/'source');prepared=execute(source,tmp_path/'prepared');decisions=data(prepared)
    protected=files(Path(prepared['bundle_path']));source_hash=file_sha256(source)
    if conflict in {'same-heading-role','list-selected-leaf-heading'}:
        selected=accept(decisions,'semantic-role' if conflict=='same-heading-role' else 'semantic-list')
        target=selected['element'] if conflict=='same-heading-role' else selected['tree_context']['children'][1]['element']
        old=next(row for row in decisions['decisions'] if row['kind']=='heading-tag' and row.get('element')==target)
        old['value']='H3';bind_approval(old,REVIEWER,'2026-10-27')
    elif conflict=='order-and-list':
        accept(decisions,'semantic-list');order=choose(decisions,'reading-order',DIV_A)
        order['value']=value({'children':list(reversed(json.loads(order['current'])['children']))});bind_approval(order,REVIEWER,'2026-10-27')
    else:
        accept(decisions,'tree-move');order=choose(decisions,'reading-order',DIV_B)
        order['value']=value({'children':list(reversed(json.loads(order['current'])['children']))});bind_approval(order,REVIEWER,'2026-10-27')
    plan=write_sidecar(decisions,tmp_path/'conflicting.json');result=execute(source,tmp_path/'refused',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert result['status']=='failed' and result['output'] is None
    assert files(Path(prepared['bundle_path']))==protected and file_sha256(source)==source_hash


@pytest.mark.parametrize('navigation_kind',['annotation-name','link-name','link-target','bookmark-entry','bookmark-additions'])
def test_new_profile_navigation_and_semantic_changes_share_exact_fidelity_and_replay(tmp_path,fast_validator,navigation_kind):
    from test_navigation_pipeline import accept as accept_navigation,nav_snapshot
    source=semantic_source(tmp_path/'source');prepared=execute(source,tmp_path/'prepared');decisions=data(prepared)
    original_tree=logical_snapshot(prepared['decision_source']['path'])
    accept(decisions,'semantic-role');accept_navigation(decisions,navigation_kind)
    plan=write_sidecar(decisions,tmp_path/'accepted.json');result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert result['status'] in {'candidate','needs-manual'},result.get('error');exact_fidelity(result)
    assert result['fidelity']['reviewed_navigation']['expected_common_navigation_matches'] is True
    assert len(result['fidelity']['reviewed_navigation']['deltas'])==1
    expected=expected_logical(original_tree,{'semantic-role'})
    if navigation_kind=='link-name':
        name=next(row['value'] for row in decisions['decisions'] if row['kind']=='link-name' and row['status']=='approved')
        expected['logical']['children'][1]['children'][2]['attributes']['/Alt']=canonical(pikepdf.String(name))
    assert logical_snapshot(result['output']['path'])==expected
    assert len(fresh_tree_reviews(result,decisions))==1
    assert len([item for item in result['manual_review']['items'] if item['id'].startswith('navigation-decision-')])==1
    actual_nav=nav_snapshot(result['output']['path'])
    for kind,new_value in [('title','Combined reviewed navigation and tree replay'),('language','en-GB')]:
        row=next(row for row in decisions['decisions'] if row['kind']==kind);row['value']=new_value;bind_approval(row,REVIEWER,'2026-10-27')
    later_plan=write_sidecar(decisions,tmp_path/'metadata.json');later=execute(source,tmp_path/'metadata',sidecar=later_plan,decision_bundle=result['bundle_path'])
    assert later['status'] in {'candidate','needs-manual'},later.get('error');exact_fidelity(later)
    assert nav_snapshot(later['output']['path'])==actual_nav
    assert logical_snapshot(later['output']['path'])==logical_snapshot(result['output']['path'])
    assert len(fresh_tree_reviews(later,data(later)))==1
    assert len([item for item in later['manual_review']['items'] if item['id'].startswith('navigation-decision-')])==1
