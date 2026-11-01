"""Source-bound semantic-tree draft acceptance, invalidation and recovery."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil

import pytest

from pdf_remediator import workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import SEMANTIC_TREE_INVENTORY_PROFILE,collect_decisions,file_sha256,write_sidecar
from pdf_remediator.web import Application
from test_semantic_tree_pipeline import (KINDS,OLD_PROFILES,REVIEWER,PATHS,semantic_source,selected_value,value,choose,
    registered_language_fonts,tagged_control)


def fixture(tmp_path,*,profile=SEMANTIC_TREE_INVENTORY_PROFILE,hazard=None):
    source=semantic_source(tmp_path/'original',hazard=hazard)
    bundle=tmp_path/'bundle';bundle.mkdir();output=bundle/'candidate.pdf';shutil.copyfile(source,output);digest=file_sha256(source)
    manual=[{'id':'reading-order','category':'reading-order','required':True,'status':'pending','pages':[],
        'detail':'Inspect list meaning, tree relationships and reading order in this authored fixture.'},
        {'id':'metadata-meaning','category':'metadata-meaning','required':True,'status':'pending','pages':[],
        'detail':'Inspect this authored fixture title and language.'}]
    report={'status':'candidate','run_fingerprint':'authored-semantic-tree-review',
        'input':{'path':str(source),'sha256':digest},'output':{'path':str(output),'sha256':digest},
        'decision_source':{'path':str(source),'sha256':digest,'source_sha256':digest},'inspection':{'page_count':2},
        'manual_review':{'artifact_sha256':digest,'items':manual,'complete':False},'residual_issues':[],
        'gate1':{'status':'pass','scope':'Workspace-only explicitly synthetic gate'},
        'gate2':{'status':'pass','checks':[],'manual_queue':copy.deepcopy(manual)},'fidelity':{'status':'pass','after_sha256':digest}}
    write_sidecar(report,bundle/'report.json');write_sidecar(report['manual_review'],bundle/'review.json')
    write_sidecar(collect_decisions(source,inventory_profile=profile),bundle/'decisions.json')
    (bundle/'review.html').write_text('<!doctype html><title>Authored semantic tree review</title>',encoding='utf-8')
    write_sidecar({'schema_version':'phase1-bundle-1','complete':True,'run_fingerprint':report['run_fingerprint'],
        'files':{path.name:file_sha256(path) for path in bundle.iterdir()}},bundle/'manifest.json')
    assert verify_bundle(bundle)
    state=tmp_path/'saved-review.json';workspace.create_workspace(bundle,state);return source,bundle,state


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_tree_save_named_acceptance_export_and_reopen_preserve_original_and_observations(tmp_path,kind):
    source,bundle,state=fixture(tmp_path);protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    view=workspace.review_item(state,'reading-order','approved',REVIEWER,'2026-10-27',0,'Keep this earlier observation after changing the tree.')
    row=choose(view,kind);new=selected_value(view,kind);view=workspace.edit_decision(state,row['id'],new,view['revision'])
    draft=next(item for item in view['decisions'] if item['id']==row['id'])
    assert draft['value']==new and draft['status']=='pending' and 'approval_sha256' not in draft
    note=next(item for item in view['manual_items'] if item['id']=='reading-order')
    assert note['status']=='pending' and note['notes'].startswith('Keep this earlier') and 'reviewer' not in note and 'reviewed_at' not in note
    saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.approve_decision(state,row['id'],'','2026-10-27',view['revision'])
    with pytest.raises(workspace.RevisionConflict):workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision']-1)
    assert state.read_bytes()==saved
    accepted=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    exported=workspace.export_workspace(state,tmp_path/'export',accepted['revision'])
    assert exported['requires_reprocessing'] and not exported['ledger_eligible']
    assert accepted['verification']=='not-verified' and accepted['counts']['manual_approved']==0
    assert workspace.get_view(state)==accepted and {path:file_sha256(path) for path in protected}==protected


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_tree_repair_draft_can_be_withdrawn_without_granting_semantic_credit(tmp_path,kind):
    source,bundle,state=fixture(tmp_path);protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    view=workspace.review_item(state,'reading-order','blocked',REVIEWER,'2026-10-27',0,'Keep the original semantic problem after withdrawing the draft.')
    row=choose(view,kind);original=row['current'];view=workspace.edit_decision(state,row['id'],selected_value(view,kind),view['revision'])
    assert row['id'] in view['unapplied_decisions']
    view=workspace.edit_decision(state,row['id'],original,view['revision'])
    assert not view['unapplied_decisions']
    view=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    assert not view['unapplied_decisions'] and view['counts']['manual_approved']==0 and view['verification']=='not-verified'
    note=next(item for item in view['manual_items'] if item['id']=='reading-order')
    assert note['status']=='blocked' and note['notes'].startswith('Keep the original')
    assert {path:file_sha256(path) for path in protected}==protected


def invalid_value(view,kind,case):
    row=choose(view,kind);context=row['tree_context']
    if case=='bad-json':return 'not-json'
    if case=='empty-object':return '{}'
    if case=='extra-field':
        parsed=json.loads(selected_value(view,kind));parsed['delete']=True;return value(parsed)
    if case=='too-large':return 'x'*100001
    if kind=='semantic-role':return {'blank':'','unknown':'CustomRole','nul':'P\x00','spaces':' \n '}[case]
    if kind=='reading-order':
        children=json.loads(row['current'])['children']
        return value({'children':{'missing':children[:-1],'duplicate':[children[0]]*len(children),
            'unknown':[children[0],'unknown:node'],'wrong-type':[True,*children[1:]]}[case]})
    if kind=='tree-move':
        current=json.loads(row['current'])
        return value({'parent':'unknown:parent' if case=='unknown-parent' else current['parent'],
            'index':{'negative':-1,'too-far':999,'boolean':True,'unknown-parent':0}[case]})
    children=context['children'];label=children[1]['element'];body=children[2]['element']
    good={'label':label,'body':body}
    return value({'items':{'duplicate':[good,good],'unknown':[{'label':None,'body':'unknown:node'}],
        'noncontiguous':[{'label':label,'body':children[4]['element']}],
        'too-many':[good]*51,'wrong-item':[{'label':True,'body':body}],
        'numbering':[]}[case],'numbering':'NotANumberingKind' if case=='numbering' else 'Decimal'})


INVALID=[('semantic-role',case) for case in ['blank','unknown','nul','spaces','too-large']]
INVALID += [(kind,case) for kind in ['reading-order','tree-move','semantic-list'] for case in ['bad-json','empty-object','extra-field','too-large']]
INVALID += [('reading-order',case) for case in ['missing','duplicate','unknown','wrong-type']]
INVALID += [('tree-move',case) for case in ['negative','too-far','boolean','unknown-parent']]
INVALID += [('semantic-list',case) for case in ['duplicate','unknown','noncontiguous','too-many','wrong-item','numbering']]


@pytest.mark.parametrize('kind,case',INVALID)
def test_invalid_tree_drafts_refuse_without_rewriting_the_saved_review(tmp_path,kind,case):
    _,_,state=fixture(tmp_path);view=workspace.get_view(state);row=choose(view,kind);saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.edit_decision(state,row['id'],invalid_value(view,kind,case),view['revision'])
    assert state.read_bytes()==saved


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_nonhuman_tree_edits_cannot_bypass_named_review(tmp_path,kind):
    _,_,state=fixture(tmp_path);view=workspace.get_view(state);row=choose(view,kind);saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.edit_decision(state,row['id'],selected_value(view,kind),view['revision'],actor='automation')
    assert state.read_bytes()==saved


@pytest.mark.parametrize('field',['source','children','parent_choices'])
def test_resealed_tree_capability_tamper_invalidates_authority_and_preserves_problem_note(tmp_path,field):
    _,_,state=fixture(tmp_path)
    view=workspace.review_item(state,'reading-order','blocked',REVIEWER,'2026-10-27',0,'Retain the precise tree problem if the source context becomes stale.')
    raw=workspace.load_workspace(state);row=choose({'decisions':raw['sidecar']['decisions']},'tree-move')
    row['tree_context'][field]={'changed':'untrusted-context'};workspace._save(state,raw)
    stale=workspace.get_view(state)
    assert stale['stale'] and stale['counts']['manual_blocked']==1 and stale['counts']['decision_approved']==0
    assert next(item for item in stale['manual_items'] if item['id']=='reading-order')['notes'].startswith('Retain the precise')
    with pytest.raises(workspace.StaleWorkspace):workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',stale['revision'])
    with pytest.raises(workspace.StaleWorkspace):workspace.export_workspace(state,tmp_path/'refused',stale['revision'])
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('profile',OLD_PROFILES)
def test_all_five_older_saved_profiles_keep_exact_choices_and_problem_notes(tmp_path,profile):
    _,_,state=fixture(tmp_path,profile=profile)
    view=workspace.review_item(state,'reading-order','blocked',REVIEWER,'2026-10-27',0,'Keep the older review and its structural problem note.')
    saved=state.read_bytes();assert not any(row['kind'] in KINDS for row in view['decisions'])
    assert workspace.get_view(state)==view and state.read_bytes()==saved


def test_application_reconstruction_preserves_list_draft_and_refuses_unaccepted_apply(tmp_path):
    source,bundle,_=fixture(tmp_path/'fixture');protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    config=RuntimeConfig(project_root=tmp_path);root=tmp_path/'service';app=Application(root,config)
    try:
        identifier=app.import_bundle(bundle);state=app.state_path(identifier);view=app.view(identifier)
        row=choose(view,'semantic-list');view=workspace.edit_decision(state,row['id'],selected_value(view,'semantic-list'),view['revision']);saved=state.read_bytes()
    finally:app.close()
    reopened=Application(root,config)
    try:
        assert reopened.view(identifier)==view and state.read_bytes()==saved
        with pytest.raises(ValueError):reopened.apply(identifier,{'revision':view['revision']})
        assert not reopened.jobs and state.read_bytes()==saved
        assert {path:file_sha256(path) for path in protected}==protected
    finally:reopened.close()
