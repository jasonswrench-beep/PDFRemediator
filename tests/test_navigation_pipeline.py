"""Independent reviewed-navigation integration; only the strict CLI is a double.

All source PDFs, ordinary typed decisions, review persistence, object inspection,
rendering, text comparisons and immutable bundles are real. These authored cases
are developer evidence and do not supply a person's accessibility approval.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator import inspection,pipeline,workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import (NAVIGATION_INVENTORY_PROFILE,SEMANTIC_TREE_INVENTORY_PROFILE,TABLE_INVENTORY_PROFILE,FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE,PASSAGE_LANGUAGE_INVENTORY_PROFILE,
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,LEGACY_INVENTORY_PROFILE,
    bind_approval,collect_decisions,file_sha256,load_sidecar,write_sidecar)
from test_artifact_structure_pipeline import canonical,files
from test_language_scopes import language_scope_pdf,registered_language_fonts
from test_pipeline import fast_validator,tagged_control

KINDS={'annotation-name','link-name','link-target','bookmark-entry','bookmark-additions'}
REVIEWER='Synthetic navigation reviewer'


def value(data):return json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def navigation_source(directory,*,uri=False,remove_bookmarks=False,missing_name=False):
    """Independent fully tagged/embedded-font two-page source with old navigation."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    built=language_scope_pdf(directory/'paint-and-tags.pdf',languages=(None,None),body_languages=('en','en'))
    output=directory/'source.pdf'
    with pikepdf.open(built) as pdf:
        link=pdf.Root.StructTreeRoot.K.K[1].K[2]
        link.Alt='Return to the opening community research page'
        annotation=pdf.pages[1].Annots[0]
        annotation.Contents='Return to first page'
        if missing_name:del annotation['/Contents'];del link['/Alt']
        if uri:
            del annotation['/Dest']
            annotation.A=pikepdf.Dictionary(S=pikepdf.Name.URI,URI='https://example.org/original')
        pdf.Root.Outlines['/DeveloperRootNote']='Preserve original outline root attributes'
        pdf.Root.Outlines.First.F=2
        pdf.Root.Outlines.First.C=pikepdf.Array([0.2,0.3,0.4])
        pdf.Root.Outlines.Last.F=1
        pdf.Root.Outlines.Last['/DeveloperEntryNote']='Preserve original sibling attributes'
        if remove_bookmarks:del pdf.Root['/Outlines']
        with output.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    return output


def execute(source,output,**kwargs):return pipeline.process_file(source,output,RuntimeConfig(),**kwargs)
def data(report):return load_sidecar(Path(report['bundle_path'])/'decisions.json')


def choose(decisions,kind):
    rows=[row for row in decisions['decisions'] if row['kind']==kind and row.get('structural_eligible')]
    assert rows,(kind,[(row['id'],row.get('structural_limitations')) for row in decisions['decisions'] if row['kind']==kind])
    return rows[0]


def selected_value(kind):
    return {'annotation-name':'Read the opening community research page',
        'link-name':'Read the community research opening',
        'link-target':value({'kind':'page','page':2}),
        'bookmark-entry':value({'title':'Community research continuation','target':{'kind':'page','page':2}}),
        'bookmark-additions':value({'entries':[{'title':'Research summary','page':2,'level':1},
            {'title':'Opening background','page':1,'level':2}]})}[kind]


def accept(decisions,kind,new_value=None):
    row=choose(decisions,kind);row['value']=selected_value(kind) if new_value is None else new_value
    bind_approval(row,REVIEWER,'2026-10-27');return row


def nav_snapshot(path):
    """Independent navigation/selected-attribute view, without product writer helpers."""
    with pikepdf.open(path) as pdf:
        page_numbers={page.obj.objgen:index+1 for index,page in enumerate(pdf.pages)}
        def destination(target):
            if isinstance(target,pikepdf.Array):
                return [page_numbers.get(item.objgen) if index==0 and isinstance(item,pikepdf.Dictionary) else str(item)
                        for index,item in enumerate(target)]
            return str(target) if target is not None else ''
        bookmarks=[];node=pdf.Root.get('/Outlines',{}).get('/First')
        def walk(item,depth):
            while isinstance(item,pikepdf.Dictionary):
                action=item.get('/A',{})
                bookmarks.append({'title':str(item.get('/Title','')),'depth':depth,
                    'destination':destination(item.get('/Dest',action.get('/D'))),
                    'action':str(action.get('/S','')),'uri':str(action.get('/URI',''))})
                walk(item.get('/First'),depth+1);item=item.get('/Next')
        walk(node,0)
        annotations=[]
        for page_index,page in enumerate(pdf.pages,1):
            for index,annotation in enumerate(page.obj.get('/Annots',[])):
                action=annotation.get('/A',{})
                annotations.append({'page':page_index,'index':index,'contents':str(annotation.get('/Contents','')),
                    'destination':destination(annotation.get('/Dest',action.get('/D'))),
                    'action':str(action.get('/S','')),'uri':str(action.get('/URI','')),
                    'other':{str(k):canonical(v) for k,v in annotation.items() if k not in {'/Contents','/Dest','/A'}}})
        link=pdf.Root.StructTreeRoot.K.K[1].K[2]
        names=pdf.Root.Names.Dests.Names
        named=[[str(names[index]),destination(names[index+1])] for index in range(0,len(names),2)]
        return {'annotations':annotations,'bookmarks':bookmarks,'link_alt':str(link.get('/Alt','')),
                'named_destinations':named,'page_labels':canonical(pdf.Root.PageLabels)}


def fresh_navigation_reviews(report,decisions):
    changed={row['id']:row for row in decisions['decisions'] if row['kind'] in KINDS
        and row['status']=='approved' and row['value']!=row['current']}
    items=[item for item in report['manual_review']['items'] if item['id'].startswith('navigation-decision-')]
    assert len(items)==len(changed)==len({item['id'] for item in items})
    assert {item['decision_id'] for item in items}==set(changed)
    assert report['manual_review']['artifact_sha256']==report['output']['sha256']
    for item in items:
        decision=changed[item['decision_id']]
        assert item['id']=='navigation-decision-'+hashlib.sha256(decision['id'].encode()).hexdigest()[:20]
        assert item['category']=='reading-order' and item['required'] is True and item['status']=='pending'
        assert item['page']==decision.get('page') and item['context_sha256']==decision['context_sha256']
        assert item['evidence']=={'kind':decision['kind'],'element':decision.get('element'),
            'structure_path':decision.get('structure_path'),'references':decision['references'],'binding':decision['binding'],
            'previous_value':decision['current'],'applied_value':decision['value'],
            'source_navigation_context':decision['navigation_context']}
        assert not any(key in item for key in ['reviewer','reviewed_at','notes','approval_sha256'])
    return items


def assert_pixels_text_and_bindings(report):
    fidelity=report['fidelity']
    assert fidelity['status']=='pass' and fidelity['text']['ordered_status']=='pass'
    assert fidelity['text']['removed_tokens']==fidelity['text']['added_tokens']==0
    assert len(fidelity['pages'])==2
    assert all(page['changed_pixel_fraction']==0 and page['dimensions_status']=='pass'
        and page['page_boxes_status']=='pass' and page['annotations_status']=='pass' for page in fidelity['pages'])
    assert report['inspection']['sha256']==fidelity['after_sha256']==report['gate1']['input_sha256']==report['output']['sha256']
    assert report['data_sent']['document_api_calls']==0 and report['settings']['ocr_mode']=='off'


def test_new_navigation_profile_is_pending_and_older_four_profiles_are_not_expanded(tmp_path,fast_validator):
    source=navigation_source(tmp_path/'source');source_hash=file_sha256(source)
    report=execute(source,tmp_path/'prepared');decisions=data(report)
    assert decisions['inventory_profile']==EMPTY_TAG_INVENTORY_PROFILE
    previous_navigation=collect_decisions(report['decision_source']['path'],source_hash,inventory_profile=NAVIGATION_INVENTORY_PROFILE)
    assert [row for row in decisions['decisions'] if row['kind'] not in
        {'semantic-role','reading-order','tree-move','semantic-list','table-structure','form-controls','empty-tag-removal'}]==previous_navigation['decisions']
    assert KINDS<={row['kind'] for row in decisions['decisions']}
    assert all(row['status']=='pending' and row['value']==row['current'] for row in decisions['decisions'])
    for profile in [LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,ARTIFACT_STRUCTURE_INVENTORY_PROFILE,PASSAGE_LANGUAGE_INVENTORY_PROFILE]:
        old=collect_decisions(report['decision_source']['path'],source_hash,inventory_profile=profile)
        assert not any(row['kind'] in KINDS for row in old['decisions'])
    old=collect_decisions(report['decision_source']['path'],source_hash,inventory_profile=PASSAGE_LANGUAGE_INVENTORY_PROFILE)
    retained={key:val for key,val in decisions.items() if key not in {'inventory_profile','decisions'}}
    assert retained=={key:val for key,val in old.items() if key not in {'inventory_profile','decisions'}}
    assert [row for row in decisions['decisions'] if row['kind'] not in KINDS |
        {'semantic-role','reading-order','tree-move','semantic-list','table-structure','form-controls','empty-tag-removal'}]==old['decisions']
    assert fresh_navigation_reviews(report,decisions)==[] and file_sha256(source)==source_hash


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_named_navigation_edits_preserve_source_old_bundle_and_exact_unselected_navigation(tmp_path,fast_validator,kind):
    source=navigation_source(tmp_path/'source');source_hash=file_sha256(source);original=nav_snapshot(source)
    before=execute(source,tmp_path/'before');bundle=Path(before['bundle_path']);protected=files(bundle)
    state=tmp_path/'review.json';workspace.create_workspace(bundle,state)
    view=workspace.review_item(state,'reading-order','pending',REVIEWER,'2026-10-27',0,'Retain this unfinished navigation observation.')
    row=choose(view,kind)
    view=workspace.edit_decision(state,row['id'],selected_value(kind),view['revision'])
    view=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    export=workspace.export_workspace(state,tmp_path/'export',view['revision']);saved=state.read_bytes()
    report=execute(source,tmp_path/'after',sidecar=export['sidecar_path'],decision_bundle=bundle)
    assert report['status']=='candidate',report.get('error')
    assert report['checkpoint_reused'] and report['output']['path']!=before['output']['path']
    assert_pixels_text_and_bindings(report)
    expected=copy.deepcopy(original);actual=nav_snapshot(report['output']['path'])
    if kind=='annotation-name':expected['annotations'][0]['contents']=selected_value(kind)
    elif kind=='link-name':expected['link_alt']=selected_value(kind)
    elif kind=='link-target':expected['annotations'][0].update(destination=[2,'/Fit'],action='',uri='')
    elif kind=='bookmark-entry':expected['bookmarks'][0].update(title='Community research continuation',destination=[2,'/Fit'],action='',uri='')
    else:expected['bookmarks'] += [{'title':'Research summary','depth':0,'destination':[2,'/Fit'],'action':'','uri':''},
        {'title':'Opening background','depth':1,'destination':[1,'/Fit'],'action':'','uri':''}]
    assert actual==expected
    assert len(fresh_navigation_reviews(report,load_sidecar(export['sidecar_path'])))==1
    assert report['fidelity']['reviewed_navigation']['expected_common_navigation_matches'] is True
    assert state.read_bytes()==saved and workspace.get_view(state)==view and files(bundle)==protected
    assert file_sha256(source)==source_hash


def test_all_five_navigation_choices_compose_and_later_metadata_replay_requires_fresh_judgments(tmp_path,fast_validator):
    source=navigation_source(tmp_path/'source');before=execute(source,tmp_path/'before');decisions=data(before)
    for kind in sorted(KINDS):accept(decisions,kind)
    edited=execute(source,tmp_path/'edited',sidecar=write_sidecar(decisions,tmp_path/'all.json'),decision_bundle=before['bundle_path'])
    assert edited['status']=='candidate',edited.get('error')
    assert_pixels_text_and_bindings(edited);assert len(fresh_navigation_reviews(edited,decisions))==5
    state=tmp_path/'edited-review.json';workspace.create_workspace(edited['bundle_path'],state)
    view=workspace.get_view(state);assert view['counts']['manual_approved']==0 and view['verification']=='not-verified'
    semantic=next(row for row in view['manual_items'] if row['id'].startswith('navigation-decision-'))
    view=workspace.review_item(state,semantic['id'],'approved',REVIEWER,'2026-10-27',view['revision'],'Keep this earlier purpose observation.')
    for kind,new in [('title','Reviewed navigation follow-up'),('language','en-GB')]:
        row=next(row for row in view['decisions'] if row['kind']==kind)
        view=workspace.edit_decision(state,row['id'],new,view['revision'])
        view=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    old_semantic=next(row for row in view['manual_items'] if row['id']==semantic['id'])
    assert old_semantic['status']=='pending' and old_semantic['notes']=='Keep this earlier purpose observation.'
    export=workspace.export_workspace(state,tmp_path/'follow-up-export',view['revision']);saved=state.read_bytes();old_files=files(Path(edited['bundle_path']))
    final=execute(source,tmp_path/'final',sidecar=export['sidecar_path'],decision_bundle=edited['bundle_path'])
    assert final['status']=='candidate',final.get('error');assert_pixels_text_and_bindings(final)
    assert nav_snapshot(final['output']['path'])==nav_snapshot(edited['output']['path'])
    assert len(fresh_navigation_reviews(final,load_sidecar(export['sidecar_path'])))==5
    assert state.read_bytes()==saved and files(Path(edited['bundle_path']))==old_files
    assert all(not row.get('notes') for row in final['manual_review']['items'])


@pytest.mark.parametrize('kind',['annotation-name','link-target','bookmark-entry'])
def test_changed_names_and_targets_fail_ordinary_fidelity_but_exact_accepted_deltas_pass(tmp_path,fast_validator,kind):
    source=navigation_source(tmp_path/'source');before=execute(source,tmp_path/'before');decisions=data(before);accept(decisions,kind)
    edited=execute(source,tmp_path/'edited',sidecar=write_sidecar(decisions,tmp_path/'accepted.json'),decision_bundle=before['bundle_path'])
    assert edited.get('output'),edited.get('error')
    raw=inspection.compare_fidelity(source,edited['output']['path'])
    assert raw['status']=='fail'
    reviewed=inspection.compare_fidelity(source,edited['output']['path'],navigation_review=decisions,
        navigation_source=before['decision_source']['path'],navigation_original_sha256=file_sha256(source))
    assert reviewed['status']=='pass'
    assert reviewed['reviewed_navigation']['expected_common_navigation_matches'] is True


@pytest.mark.parametrize('tamper',['missing-reviewer','edited-value','resealed-context','wrong-checkpoint','wrong-original','omitted-row','duplicate-row','automatic'])
def test_navigation_fidelity_refuses_unbound_or_stale_authority(tmp_path,fast_validator,tamper):
    source=navigation_source(tmp_path/'source');before=execute(source,tmp_path/'before');decisions=data(before)
    row=accept(decisions,'annotation-name');edited=execute(source,tmp_path/'edited',sidecar=write_sidecar(decisions,tmp_path/'accepted.json'),decision_bundle=before['bundle_path'])
    protected={str(path):file_sha256(path) for path in [source,Path(edited['output']['path']),Path(before['decision_source']['path'])]}
    review=copy.deepcopy(decisions);row=choose(review,'annotation-name');checkpoint=before['decision_source']['path'];original=file_sha256(source)
    if tamper=='missing-reviewer':row['approved_by']='';row['approval_sha256']='not-valid'
    elif tamper=='edited-value':row['value']='Unaccepted replacement'
    elif tamper=='resealed-context':row['navigation_context']['source_name']='An invented original';bind_approval(row,REVIEWER,'2026-10-27')
    elif tamper=='wrong-checkpoint':checkpoint=edited['output']['path']
    elif tamper=='wrong-original':original='0'*64
    elif tamper=='omitted-row':review['decisions'].pop()
    elif tamper=='duplicate-row':review['decisions'].append(copy.deepcopy(row))
    else:row['status']='auto-accepted'
    result=inspection.compare_fidelity(source,edited['output']['path'],navigation_review=review,navigation_source=checkpoint,navigation_original_sha256=original)
    assert result['status']=='error' and result.get('error')
    assert {path:file_sha256(path) for path in protected}==protected


@pytest.mark.parametrize('unexpected',['unselected-contents','unselected-target','extra-bookmark','deleted-bookmark','reordered-bookmarks','page-label','annotation-rect'])
def test_one_name_acceptance_cannot_excuse_unselected_navigation_changes(tmp_path,fast_validator,unexpected):
    source=navigation_source(tmp_path/'source');before=execute(source,tmp_path/'before');decisions=data(before);accept(decisions,'link-name')
    edited=execute(source,tmp_path/'edited',sidecar=write_sidecar(decisions,tmp_path/'accepted.json'),decision_bundle=before['bundle_path'])
    changed=tmp_path/'unselected.pdf'
    with pikepdf.open(edited['output']['path']) as pdf:
        if unexpected=='unselected-contents':pdf.pages[1].Annots[0].Contents='Unaccepted name'
        elif unexpected=='unselected-target':pdf.pages[1].Annots[0].Dest=pikepdf.Array([pdf.pages[1].obj,pikepdf.Name.Fit])
        elif unexpected=='extra-bookmark':
            with pdf.open_outline() as outline:outline.root.append(pikepdf.OutlineItem('Unaccepted addition',1))
        elif unexpected=='deleted-bookmark':
            with pdf.open_outline() as outline:outline.root.pop()
        elif unexpected=='reordered-bookmarks':
            with pdf.open_outline() as outline:outline.root[:]=list(reversed(outline.root))
        elif unexpected=='page-label':pdf.Root.PageLabels.Nums[1].P='changed'
        else:pdf.pages[1].Annots[0].Rect[0]=31
        with changed.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    result=inspection.compare_fidelity(source,changed,navigation_review=decisions,navigation_source=before['decision_source']['path'],navigation_original_sha256=file_sha256(source))
    assert result['status'] in {'fail','error'}
    assert not result.get('reviewed_navigation',{}).get('expected_common_navigation_matches',False)


def test_bookmark_authoring_can_start_from_no_outline_without_inventing_titles(tmp_path,fast_validator):
    source=navigation_source(tmp_path/'source',remove_bookmarks=True);before=execute(source,tmp_path/'before');decisions=data(before)
    assert not any(row['kind']=='bookmark-entry' for row in decisions['decisions'])
    additions=choose(decisions,'bookmark-additions');assert json.loads(additions['current'])=={'entries':[]}
    assert additions['value']==additions['current'] and additions['status']=='pending'
    accept(decisions,'bookmark-additions')
    result=execute(source,tmp_path/'created',sidecar=write_sidecar(decisions,tmp_path/'bookmarks.json'),decision_bundle=before['bundle_path'])
    assert result['status']=='candidate',result.get('error');assert_pixels_text_and_bindings(result)
    assert [(row['title'],row['depth']) for row in nav_snapshot(result['output']['path'])['bookmarks']]==[('Research summary',0),('Opening background',1)]
    assert len(fresh_navigation_reviews(result,decisions))==1


def test_title_only_bookmark_edit_preserves_named_destination_representation(tmp_path,fast_validator):
    source=navigation_source(tmp_path/'source');named=tmp_path/'named-source.pdf'
    with pikepdf.open(source) as pdf:
        pdf.Root.Outlines.First.Dest=pikepdf.String('first-language-page')
        with named.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    before=execute(named,tmp_path/'before');decisions=data(before);row=choose(decisions,'bookmark-entry');new=json.loads(row['current']);new['title']='Meaningful opening bookmark'
    accept(decisions,'bookmark-entry',value(new))
    result=execute(named,tmp_path/'edited',sidecar=write_sidecar(decisions,tmp_path/'title.json'),decision_bundle=before['bundle_path'])
    assert result['status']=='candidate',result.get('error');assert_pixels_text_and_bindings(result)
    with pikepdf.open(result['output']['path']) as pdf:
        assert isinstance(pdf.Root.Outlines.First.Dest,pikepdf.String) and str(pdf.Root.Outlines.First.Dest)=='first-language-page'


def test_title_only_bookmark_edit_preserves_exact_XYZ_fit_and_zoom(tmp_path,fast_validator):
    source=navigation_source(tmp_path/'source');xyz=tmp_path/'xyz-source.pdf'
    with pikepdf.open(source) as pdf:
        pdf.Root.Outlines.First.Dest=pikepdf.Array([pdf.pages[0].obj,pikepdf.Name.XYZ,28,603,1.25])
        with xyz.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    before=execute(xyz,tmp_path/'before');decisions=data(before);row=choose(decisions,'bookmark-entry')
    chosen=json.loads(row['current']);chosen['title']='Reviewed opening with exact zoom'
    accept(decisions,'bookmark-entry',value(chosen))
    result=execute(xyz,tmp_path/'edited',sidecar=write_sidecar(decisions,tmp_path/'title.json'),decision_bundle=before['bundle_path'])
    assert result['status']=='candidate',result.get('error');assert_pixels_text_and_bindings(result)
    with pikepdf.open(result['output']['path']) as pdf:
        dest=pdf.Root.Outlines.First.Dest
        assert dest[0].objgen==pdf.pages[0].obj.objgen and str(dest[1])=='/XYZ'
        assert [float(item) for item in list(dest)[2:]]==[28,603,1.25]


@pytest.mark.parametrize('blank',['absent','','   '])
def test_existing_missing_or_blank_bookmark_title_can_be_explicitly_repaired(tmp_path,fast_validator,blank):
    source=navigation_source(tmp_path/'source');untitled=tmp_path/'untitled-source.pdf'
    with pikepdf.open(source) as pdf:
        if blank=='absent':del pdf.Root.Outlines.First['/Title']
        else:pdf.Root.Outlines.First.Title=blank
        with untitled.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    before=execute(untitled,tmp_path/'before');decisions=data(before);row=choose(decisions,'bookmark-entry')
    chosen=json.loads(row['current']);assert not chosen['title'].strip();chosen['title']='Opening research background'
    accept(decisions,'bookmark-entry',value(chosen))
    result=execute(untitled,tmp_path/'edited',sidecar=write_sidecar(decisions,tmp_path/'title.json'),decision_bundle=before['bundle_path'])
    assert result['status']=='candidate',result.get('error');assert_pixels_text_and_bindings(result)
    with pikepdf.open(result['output']['path']) as pdf:
        assert str(pdf.Root.Outlines.First.Title)=='Opening research background'
        assert pdf.Root.Outlines.First.Dest[0].objgen==pdf.pages[0].obj.objgen
    assert len(fresh_navigation_reviews(result,decisions))==1


@pytest.mark.parametrize('kind',['link-target','bookmark-entry'])
@pytest.mark.parametrize('missing',['absent','unresolved-name'])
def test_missing_or_unresolved_passive_targets_can_be_repaired_to_explicit_local_page(tmp_path,fast_validator,kind,missing):
    source=navigation_source(tmp_path/'source');broken=tmp_path/'missing-target-source.pdf'
    with pikepdf.open(source) as pdf:
        node=pdf.pages[1].Annots[0] if kind=='link-target' else pdf.Root.Outlines.First
        for key in ('/Dest','/A'):
            if key in node:del node[key]
        if missing=='unresolved-name':node.Dest=pikepdf.String('not-a-real-destination')
        with broken.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    before=execute(broken,tmp_path/'before');decisions=data(before);row=choose(decisions,kind)
    if kind=='link-target':replacement=value({'kind':'page','page':2})
    else:
        chosen=json.loads(row['current']);chosen['target']={'kind':'page','page':2};replacement=value(chosen)
    accept(decisions,kind,replacement)
    result=execute(broken,tmp_path/'repaired',sidecar=write_sidecar(decisions,tmp_path/'target.json'),decision_bundle=before['bundle_path'])
    assert result['status']=='candidate',result.get('error');assert_pixels_text_and_bindings(result)
    with pikepdf.open(result['output']['path']) as pdf:
        node=pdf.pages[1].Annots[0] if kind=='link-target' else pdf.Root.Outlines.First
        assert node.Dest[0].objgen==pdf.pages[1].obj.objgen and str(node.Dest[1])=='/Fit'
    assert len(fresh_navigation_reviews(result,decisions))==1


@pytest.mark.parametrize('kind',['link-target','bookmark-entry'])
def test_accepting_exact_named_target_noop_never_rewrites_raw_target(tmp_path,fast_validator,monkeypatch,kind):
    from pdf_remediator import navigation_edits
    source=navigation_source(tmp_path/'source');named=tmp_path/'named-source.pdf'
    with pikepdf.open(source) as pdf:
        node=pdf.pages[1].Annots[0] if kind=='link-target' else pdf.Root.Outlines.First
        node.Dest=pikepdf.String('first-language-page')
        with named.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    before=execute(named,tmp_path/'before');decisions=data(before);row=choose(decisions,kind)
    bind_approval(row,REVIEWER,'2026-10-27')
    def forbidden(*args,**kwargs):raise AssertionError('A named no-op reached the navigation target writer')
    monkeypatch.setattr(navigation_edits,'_write_target',forbidden)
    result=execute(named,tmp_path/'replayed',sidecar=write_sidecar(decisions,tmp_path/'same.json'),decision_bundle=before['bundle_path'])
    assert result['status']=='candidate',result.get('error')
    assert fresh_navigation_reviews(result,decisions)==[] and 'reviewed_navigation' not in result['fidelity']
    with pikepdf.open(result['output']['path']) as pdf:
        node=pdf.pages[1].Annots[0] if kind=='link-target' else pdf.Root.Outlines.First
        assert isinstance(node.Dest,pikepdf.String) and str(node.Dest)=='first-language-page'


@pytest.mark.parametrize('profile',[LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,ARTIFACT_STRUCTURE_INVENTORY_PROFILE,PASSAGE_LANGUAGE_INVENTORY_PROFILE])
def test_existing_profile_pipeline_replay_does_not_gain_navigation_controls(tmp_path,fast_validator,profile):
    source=navigation_source(tmp_path/'source');prepared=execute(source,tmp_path/'prepared')
    old=collect_decisions(prepared['decision_source']['path'],file_sha256(source),inventory_profile=profile)
    title=next(row for row in old['decisions'] if row['kind']=='title');title['value']='Older-profile title review';bind_approval(title,REVIEWER,'2026-10-27')
    result=execute(source,tmp_path/'replayed',sidecar=write_sidecar(old,tmp_path/'older.json'),decision_bundle=prepared['bundle_path'])
    assert result['status']=='candidate',result.get('error')
    assert data(result).get('inventory_profile',LEGACY_INVENTORY_PROFILE)==profile
    assert not any(row['kind'] in KINDS for row in data(result)['decisions'])
    assert nav_snapshot(result['output']['path'])==nav_snapshot(source)
    assert 'reviewed_navigation' not in result['fidelity']
