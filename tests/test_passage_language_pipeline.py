"""Independent local-language PDF pipeline and saved-review regressions.

Only the external validator is a named double. Source PDFs, tag property edits,
inspection, all-page fidelity, review persistence and publication are real.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator import pipeline,sidecar,workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import (ARTIFACT_STRUCTURE_INVENTORY_PROFILE,LEGACY_INVENTORY_PROFILE,
    STRUCTURAL_INVENTORY_PROFILE,PASSAGE_LANGUAGE_INVENTORY_PROFILE,NAVIGATION_INVENTORY_PROFILE,SEMANTIC_TREE_INVENTORY_PROFILE,TABLE_INVENTORY_PROFILE,FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE,bind_approval,collect_decisions,
    file_sha256,load_sidecar,write_sidecar)
from test_artifact_structure_pipeline import independent_paint_and_navigation,files,exact_fidelity,canonical
from test_language_scopes import language_scope_pdf,registered_language_fonts
from test_pipeline import fast_validator,tagged_control


def language_source(directory,*,page_language='en-US',passage_language=None):
    directory.mkdir(parents=True,exist_ok=True)
    output=language_scope_pdf(directory/'source.pdf',languages=(None,page_language),body_languages=('en','fr'))
    if passage_language is not None:
        with pikepdf.open(output) as pdf:
            pdf.Root.StructTreeRoot.K.K[1].K[1].Lang=passage_language
            target=directory/'source-with-passage.pdf'
            with target.open('wb') as stream:pdf.save(stream,deterministic_id=True)
        output=target
    return output


def execute(source,output,**kwargs):
    return pipeline.process_file(source,output,RuntimeConfig(),**kwargs)


def data(report):return load_sidecar(Path(report['bundle_path'])/'decisions.json')


def choose(decisions,kind,page=2):
    return next(item for item in decisions['decisions'] if item['kind']==kind and item.get('page')==page
        and (kind!='passage-language' or 'Les étudiants' in item.get('context_text','')))


def accept(item,language):
    item['value']='{"language":null}' if language is None else '{"language":"'+language+'"}'
    bind_approval(item,'Synthetic local-language reviewer','2026-10-27')


def tree_contract(path):
    """All structure properties except /Lang, plus stable ParentTree owners."""
    with pikepdf.open(path) as pdf:
        tree=pdf.Root.StructTreeRoot;paths={};direct_languages={}
        def walk(node,path):
            paths[node.objgen]=path
            if '/Lang' in node:direct_languages[path]=str(node.Lang)
            children=node.get('/K');children=list(children) if isinstance(children,pikepdf.Array) else [children]
            records=[]
            for index,child in enumerate(children):
                if isinstance(child,pikepdf.Dictionary) and '/S' in child:records.append(walk(child,path+'/K/'+str(index)))
                elif isinstance(child,pikepdf.Dictionary) and str(child.get('/Type'))=='/OBJR':
                    records.append({'OBJR':'preserved-link','page':next(i for i,page in enumerate(pdf.pages,1) if page.obj.objgen==child.Pg.objgen)})
                else:records.append(canonical(child))
            return {'attributes':{str(k):canonical(v) for k,v in node.items() if k not in {'/K','/P','/Pg','/Lang'}},
                'page':next((i for i,page in enumerate(pdf.pages,1) if page.obj.objgen==node.get('/Pg',pikepdf.Dictionary()).objgen),None),
                'children':records}
        logical=walk(tree.K,'root/K')
        values=tree.ParentTree.Nums;parents={}
        for index in range(0,len(values),2):
            value=values[index+1]
            parents[str(values[index])]=[paths.get(child.objgen) if child is not None else None for child in value] if isinstance(value,pikepdf.Array) else paths[value.objgen]
        root={str(k):canonical(v) for k,v in tree.items() if k not in {'/K','/ParentTree'}}
        return {'root':root,'logical':logical,'parents':parents},direct_languages


def language_review_items(report,accepted):
    changed={item['id']:item for item in accepted['decisions'] if item['kind'] in {'page-language','passage-language'}
        and item['status']=='approved' and item['value']!=item['current']}
    items=[item for item in report['manual_review']['items'] if item['id'].startswith('local-language-decision-')]
    assert len(items)==len({item['id'] for item in items})==len(changed)
    assert {item['decision_id'] for item in items}==set(changed)
    assert report['manual_review']['artifact_sha256']==report['output']['sha256']
    for item in items:
        decision=changed[item['decision_id']]
        assert item['id']=='local-language-decision-'+hashlib.sha256(decision['id'].encode()).hexdigest()[:20]
        assert item['required'] is True and item['status']=='pending' and item['category']=='metadata-meaning'
        assert item['page']==decision['page'] and item['context_sha256']==decision['context_sha256']
        assert item['evidence']=={'kind':decision['kind'],'element':decision['element'],'structure_path':decision['structure_path'],
            'references':decision['references'],'binding':decision['binding'],'previous_value':decision['current'],
            'applied_value':decision['value'],'source_language_context':decision['language_context'],'source_language_scope':decision['language_scope']}
        assert not any(key in item for key in ['reviewer','reviewed_at','notes','approval_sha256'])
    return items


def assert_preserved(source,report):
    assert report.get('output') and independent_paint_and_navigation(report['output']['path'])==independent_paint_and_navigation(source)
    assert tree_contract(report['output']['path'])[0]==tree_contract(source)[0]
    exact_fidelity(report)
    assert report['inspection']['sha256']==report['fidelity']['after_sha256']==report['gate1']['input_sha256']==report['output']['sha256']
    assert report['data_sent']['document_api_calls']==0


def test_new_profile_lists_pending_page_and_passage_languages_without_guessing(tmp_path,fast_validator):
    source=language_source(tmp_path/'source');before=file_sha256(source)
    report=execute(source,tmp_path/'before');decisions=data(report)
    assert decisions['inventory_profile']==EMPTY_TAG_INVENTORY_PROFILE
    older=collect_decisions(report['decision_source']['path'],before,inventory_profile=PASSAGE_LANGUAGE_INVENTORY_PROFILE)
    assert [item for item in decisions['decisions'] if item['kind'] not in
        {'annotation-name','link-name','link-target','bookmark-entry','bookmark-additions',
         'semantic-role','reading-order','tree-move','semantic-list','table-structure','form-controls','empty-tag-removal'}]==older['decisions']
    assert report['status']=='needs-manual'
    language=next(item for item in report['gate2']['checks'] if item['id']=='language-correctness')
    assert language['status']=='fail'
    assert language['evidence']['suggested_language'] is None
    assert {'page-language','passage-language'}<={item['kind'] for item in decisions['decisions']}
    assert all(item['status']=='pending' and item['value']==item['current'] for item in decisions['decisions'])
    for profile in [LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,ARTIFACT_STRUCTURE_INVENTORY_PROFILE]:
        old=collect_decisions(report['decision_source']['path'],before,inventory_profile=profile)
        assert not any(item['kind'] in {'page-language','passage-language'} for item in old['decisions'])
    assert language_review_items(report,decisions)==[] and file_sha256(source)==before
    assert_preserved(source,report)


@pytest.mark.parametrize('kind',['page-language','passage-language'])
def test_named_local_language_repair_preserves_every_other_pdf_property_and_old_review(tmp_path,fast_validator,kind):
    source=language_source(tmp_path/'source');source_hash=file_sha256(source)
    before=execute(source,tmp_path/'before');old_bundle=Path(before['bundle_path']);old_files=files(old_bundle)
    state=tmp_path/'review.json';workspace.create_workspace(old_bundle,state)
    view=workspace.review_item(state,'reading-order','pending','Synthetic language reviewer','2026-10-27',0,'Retain this earlier problem observation.')
    item=choose(view,kind);assert item['structural_eligible']
    view=workspace.edit_decision(state,item['id'],'{"language":"fr"}',view['revision'])
    view=workspace.approve_decision(state,item['id'],'Synthetic language reviewer','2026-10-27',view['revision'])
    exported=workspace.export_workspace(state,tmp_path/'export',view['revision']);saved=state.read_bytes()
    report=execute(source,tmp_path/'after',sidecar=exported['sidecar_path'],decision_bundle=old_bundle)
    assert report['status']=='candidate',report.get('error')
    assert report['checkpoint_reused'] and report['output']['path']!=before['output']['path']
    assert_preserved(source,report)
    contract,old_languages=tree_contract(source);_,new_languages=tree_contract(report['output']['path'])
    target_path='root/K/K/1' if kind=='page-language' else 'root/K/K/1/K/1'
    assert new_languages=={**old_languages,target_path:'fr'}
    with pikepdf.open(report['output']['path']) as pdf:
        assert str(pdf.Root.Lang)=='en-US' and all('/Lang' not in page.obj for page in pdf.pages)
    required=language_review_items(report,load_sidecar(exported['sidecar_path']));assert len(required)==1
    fresh_state=tmp_path/'fresh.json';workspace.create_workspace(report['bundle_path'],fresh_state)
    fresh=workspace.get_view(fresh_state)
    assert fresh['verification']=='not-verified' and fresh['counts']['manual_approved']==0
    assert all(item['status']=='pending' for item in fresh['manual_items'])
    assert state.read_bytes()==saved and workspace.get_view(state)==view and files(old_bundle)==old_files
    assert file_sha256(source)==source_hash


def test_page_default_preserves_explicit_wrong_descendant_and_does_not_mask_its_blocker(tmp_path,fast_validator):
    source=language_source(tmp_path/'source',passage_language='en-US')
    before=execute(source,tmp_path/'before');accepted=data(before);page=choose(accepted,'page-language');accept(page,'fr')
    plan=write_sidecar(accepted,tmp_path/'page.json')
    report=execute(source,tmp_path/'page-result',sidecar=plan,decision_bundle=before['bundle_path'])
    assert report['status']=='needs-manual'
    assert next(item for item in report['gate2']['checks'] if item['id']=='language-correctness')['status']=='fail'
    with pikepdf.open(report['output']['path']) as pdf:
        section=pdf.Root.StructTreeRoot.K.K[1]
        assert str(section.Lang)=='fr' and str(section.K[1].Lang)=='en-US'
    assert len(language_review_items(report,accepted))==1
    assert_preserved(source,report)


def test_page_default_passage_exception_and_later_global_title_edits_replay_safely(tmp_path,fast_validator):
    source=language_source(tmp_path/'source',passage_language='en-US')
    previous=execute(source,tmp_path/'before');previous_files=files(Path(previous['bundle_path']))
    accepted=data(previous);accept(choose(accepted,'page-language'),'fr');accept(choose(accepted,'passage-language'),'fr-CA')
    path=write_sidecar(accepted,tmp_path/'local.json')
    changed=execute(source,tmp_path/'local-result',sidecar=path,decision_bundle=previous['bundle_path'])
    assert changed['status']=='candidate',changed.get('error')
    required=language_review_items(changed,accepted);assert len(required)==2
    state=tmp_path/'changed-review.json';workspace.create_workspace(changed['bundle_path'],state)
    view=workspace.get_view(state)
    view=workspace.review_item(state,required[0]['id'],'approved','Synthetic reviewer','2026-10-27',view['revision'],'Keep my earlier language observation.')
    for kind,value in [('title','Later language-review title'),('language','en-GB')]:
        item=next(row for row in view['decisions'] if row['kind']==kind)
        view=workspace.edit_decision(state,item['id'],value,view['revision'])
        view=workspace.approve_decision(state,item['id'],'Synthetic reviewer','2026-10-27',view['revision'])
    assert view['counts']['manual_approved']==0
    assert next(row for row in view['manual_items'] if row['id']==required[0]['id'])['notes']=='Keep my earlier language observation.'
    exported=workspace.export_workspace(state,tmp_path/'export',view['revision']);saved=state.read_bytes()
    changed_files=files(Path(changed['bundle_path']))
    final=execute(source,tmp_path/'later',sidecar=exported['sidecar_path'],decision_bundle=changed['bundle_path'])
    assert final['status']=='candidate',final.get('error')
    assert len(language_review_items(final,load_sidecar(exported['sidecar_path'])))==2
    assert_preserved(source,final)
    with pikepdf.open(final['output']['path']) as pdf:
        assert str(pdf.Root.Lang)=='en-GB' and str(pdf.docinfo.Title)=='Later language-review title'
        assert str(pdf.Root.StructTreeRoot.K.K[1].Lang)=='fr'
        assert str(pdf.Root.StructTreeRoot.K.K[1].K[1].Lang)=='fr-CA'
        with pdf.open_metadata(set_pikepdf_as_editor=False,update_docinfo=False) as metadata:assert list(metadata['dc:language'])==['en-GB']
    assert workspace.get_view(state)==view and state.read_bytes()==saved
    assert files(Path(changed['bundle_path']))==changed_files and files(Path(previous['bundle_path']))==previous_files
    assert final['manual_review']['artifact_sha256']!=changed['manual_review']['artifact_sha256']
    assert all(item['status']=='pending' for item in final['manual_review']['items'])


def test_removing_local_override_resumes_proven_parent_language_without_changing_catalog(tmp_path,fast_validator):
    source=language_source(tmp_path/'source',page_language='fr',passage_language='fr-CA')
    previous=execute(source,tmp_path/'before');accepted=data(previous);item=choose(accepted,'passage-language');accept(item,None)
    assert item['language_context']['inherited']=='fr'
    plan=write_sidecar(accepted,tmp_path/'inherit.json')
    final=execute(source,tmp_path/'inherit-result',sidecar=plan,decision_bundle=previous['bundle_path'])
    assert final['status']=='candidate',final.get('error')
    with pikepdf.open(final['output']['path']) as pdf:
        assert '/Lang' not in pdf.Root.StructTreeRoot.K.K[1].K[1]
        assert str(pdf.Root.StructTreeRoot.K.K[1].Lang)=='fr' and str(pdf.Root.Lang)=='en-US'
    assert len(language_review_items(final,accepted))==1
    assert_preserved(source,final)


@pytest.mark.parametrize('profile',[LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,ARTIFACT_STRUCTURE_INVENTORY_PROFILE])
def test_existing_profile_saved_reviews_keep_exact_choices_and_notes(tmp_path,fast_validator,monkeypatch,profile):
    source=language_source(tmp_path/'source');original=sidecar.collect_decisions
    def old_producer(path,source_sha=None,**kwargs):return original(path,source_sha,inventory_profile=profile)
    with monkeypatch.context() as selected:
        selected.setattr(sidecar,'collect_decisions',old_producer)
        previous=execute(source,tmp_path/'before')
    old=data(previous);assert sidecar.inventory_profile_for(old)==profile
    assert not any(item['kind'] in {'page-language','passage-language'} for item in old['decisions'])
    state=tmp_path/'old-review.json';workspace.create_workspace(previous['bundle_path'],state)
    view=workspace.review_item(state,'reading-order','pending','Synthetic old reviewer','2026-10-27',0,'Keep this old review unchanged.')
    saved=state.read_bytes();assert workspace.get_view(state)==view and state.read_bytes()==saved
    assert workspace.load_workspace(state)['sidecar']['decisions']==old['decisions']


@pytest.mark.parametrize('kind',['page-language','passage-language'])
def test_local_language_can_never_enter_automatic_title_figure_authority(tmp_path,fast_validator,kind):
    source=language_source(tmp_path/'source');previous=execute(source,tmp_path/'before');accepted=data(previous);item=choose(accepted,kind)
    with pytest.raises(sidecar.DecisionError):
        sidecar.make_automatic_authorization(accepted['source_sha256'],accepted['document_sha256'],'2026-10-27',decision_ids=[item['id']])
    item['value']='{"language":"fr"}';item['status']='auto-accepted';item['automatic_acceptance_sha256']='0'*64
    plan=write_sidecar(accepted,tmp_path/'forged.json');old=files(Path(previous['bundle_path']))
    report=execute(source,tmp_path/'refused',sidecar=plan,decision_bundle=previous['bundle_path'])
    assert report['status']=='failed' and report['output'] is None
    assert files(Path(previous['bundle_path']))==old
