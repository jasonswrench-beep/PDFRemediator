"""Atomic table drafts, named acceptance, note invalidation and saved recovery."""
from __future__ import annotations

import copy
import json
import shutil

import pytest

from pdf_remediator import workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import TABLE_INVENTORY_PROFILE, collect_decisions, file_sha256, write_sidecar
from pdf_remediator.web import Application
from test_table_pipeline import (KIND, OLD_PROFILES, REVIEWER, table_source, selected_value,
    value, choose, registered_language_fonts, tagged_control)


def fixture(tmp_path, *, profile=TABLE_INVENTORY_PROFILE, hazard=None):
    source=table_source(tmp_path/'original',hazard=hazard)
    bundle=tmp_path/'bundle'; bundle.mkdir(); output=bundle/'candidate.pdf'; shutil.copyfile(source,output)
    digest=file_sha256(source)
    manual=[{'id':'table-relationships','category':'table-relationships','required':True,'status':'pending','pages':[1],
        'detail':'Inspect the authored header hierarchy, table grid, associations and summary.'},
        {'id':'metadata-meaning','category':'metadata-meaning','required':True,'status':'pending','pages':[],
        'detail':'Inspect the authored title and language.'}]
    report={'status':'candidate','run_fingerprint':'authored-table-structure-review',
        'input':{'path':str(source),'sha256':digest},'output':{'path':str(output),'sha256':digest},
        'decision_source':{'path':str(source),'sha256':digest,'source_sha256':digest},'inspection':{'page_count':2},
        'manual_review':{'artifact_sha256':digest,'items':manual,'complete':False},'residual_issues':[],
        'gate1':{'status':'pass','scope':'Workspace-only explicitly synthetic gate'},
        'gate2':{'status':'pass','checks':[],'manual_queue':copy.deepcopy(manual)},
        'fidelity':{'status':'pass','after_sha256':digest}}
    write_sidecar(report,bundle/'report.json'); write_sidecar(report['manual_review'],bundle/'review.json')
    write_sidecar(collect_decisions(source,inventory_profile=profile),bundle/'decisions.json')
    (bundle/'review.html').write_text('<!doctype html><title>Authored table relationship review</title>',encoding='utf-8')
    write_sidecar({'schema_version':'phase1-bundle-1','complete':True,'run_fingerprint':report['run_fingerprint'],
        'files':{path.name:file_sha256(path) for path in bundle.iterdir()}},bundle/'manifest.json')
    assert verify_bundle(bundle)
    state=tmp_path/'saved-review.json'; workspace.create_workspace(bundle,state)
    return source,bundle,state


def test_table_save_named_acceptance_export_reopen_preserve_original_and_observations(tmp_path):
    source,bundle,state=fixture(tmp_path); protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    view=workspace.review_item(state,'table-relationships','approved',REVIEWER,'2026-10-27',0,'Keep the table relationship observation after editing the plan.')
    row=choose(view); new=selected_value(view)
    view=workspace.edit_decision(state,row['id'],new,view['revision'])
    draft=choose(view); assert draft['value']==new and draft['status']=='pending' and 'approval_sha256' not in draft
    note=next(item for item in view['manual_items'] if item['id']=='table-relationships')
    assert note['status']=='pending' and note['notes'].startswith('Keep the table') and 'reviewer' not in note and 'reviewed_at' not in note
    saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError): workspace.approve_decision(state,row['id'],'','2026-10-27',view['revision'])
    with pytest.raises(workspace.RevisionConflict): workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision']-1)
    assert state.read_bytes()==saved
    accepted=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    exported=workspace.export_workspace(state,tmp_path/'export',accepted['revision'])
    assert exported['requires_reprocessing'] and not exported['ledger_eligible']
    assert accepted['verification']=='not-verified' and accepted['counts']['manual_approved']==0
    assert workspace.get_view(state)==accepted and {path:file_sha256(path) for path in protected}==protected


def test_incomplete_source_plan_can_be_withdrawn_without_granting_table_credit(tmp_path):
    source,bundle,state=fixture(tmp_path); protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    view=workspace.review_item(state,'table-relationships','blocked',REVIEWER,'2026-10-27',0,'Keep the ragged source grid problem after withdrawing the repair.')
    row=choose(view); original=row['current']
    view=workspace.edit_decision(state,row['id'],selected_value(view),view['revision']); assert row['id'] in view['unapplied_decisions']
    view=workspace.edit_decision(state,row['id'],original,view['revision']); assert not view['unapplied_decisions']
    view=workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',view['revision'])
    assert not view['unapplied_decisions'] and view['counts']['manual_approved']==0 and view['verification']=='not-verified'
    note=next(item for item in view['manual_items'] if item['id']=='table-relationships')
    assert note['status']=='blocked' and note['notes'].startswith('Keep the ragged')
    assert {path:file_sha256(path) for path in protected}==protected


def invalid_value(view, case):
    if case=='bad-json': return 'not-json'
    if case=='empty-object': return '{}'
    if case=='too-large': return 'x'*150001
    plan=json.loads(selected_value(view)); cells=plan['cells']
    if case=='extra-field': plan['delete']=True
    elif case=='summary-too-long': plan['summary']='x'*4001
    elif case=='summary-type': plan['summary']=True
    elif case=='summary-nul': plan['summary']='Invalid\x00summary'
    elif case=='missing-cell': cells.pop()
    elif case=='duplicate-cell': cells[-1]=copy.deepcopy(cells[0])
    elif case=='changed-order': cells.reverse()
    elif case=='unknown-cell': cells[0]['element']='unknown:cell'
    elif case=='extra-cell-field': cells[0]['actual_text']='Unrequested replacement text'
    elif case=='unknown-role': cells[0]['role']='CustomRole'
    elif case=='data-scope': cells[6]['scope']='Column'
    elif case=='unknown-scope': cells[0]['scope']='Diagonal'
    elif case=='duplicate-id': cells[0]['id']=cells[1]['id']
    elif case=='outside-id': cells[0]['id']='outside-note'
    elif case=='unicode-id': cells[0]['id']='h-categoría'
    elif case=='empty-id': cells[0]['id']=''
    elif case=='id-too-long': cells[0]['id']='x'*129
    elif case=='unknown-header': cells[6]['headers']=['unknown:header']
    elif case=='non-th-header': cells[6]['headers']=[cells[7]['element']]
    elif case=='unnamed-header': cells[0]['id']=None
    elif case=='self-header': cells[0]['headers']=[cells[0]['element']]
    elif case=='duplicate-header': cells[6]['headers']=[cells[0]['element'],cells[0]['element']]
    elif case=='header-cycle': cells[0]['headers']=[cells[3]['element']]; cells[3]['headers']=[cells[0]['element']]
    elif case=='span-boolean': cells[0]['row_span']=True
    elif case=='span-zero': cells[0]['row_span']=0
    elif case=='span-too-large': cells[0]['row_span']=101
    elif case=='out-of-table-span': cells[9]['row_span']=3
    elif case=='cross-group-span': cells[0]['row_span']=3
    elif case=='grid-hole': cells[1]['col_span']=1
    elif case=='span-overlap': cells[3]['col_span']=3
    else: raise ValueError('Unknown invalid table plan')
    return value(plan)


INVALID=['bad-json','empty-object','too-large','extra-field','summary-too-long','summary-type','summary-nul',
    'missing-cell','duplicate-cell','changed-order','unknown-cell','extra-cell-field','unknown-role','data-scope',
    'unknown-scope','duplicate-id','outside-id','unicode-id','empty-id','id-too-long','unknown-header','non-th-header',
    'unnamed-header','self-header','duplicate-header','header-cycle','span-boolean','span-zero','span-too-large',
    'out-of-table-span','cross-group-span','grid-hole','span-overlap']


@pytest.mark.parametrize('case',INVALID)
def test_invalid_atomic_table_drafts_refuse_without_rewriting_saved_reviews(tmp_path,case):
    _,_,state=fixture(tmp_path); view=workspace.get_view(state); row=choose(view); saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError): workspace.edit_decision(state,row['id'],invalid_value(view,case),view['revision'])
    assert state.read_bytes()==saved


def test_nonhuman_table_edits_cannot_bypass_named_review(tmp_path):
    _,_,state=fixture(tmp_path); view=workspace.get_view(state); row=choose(view); saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError): workspace.edit_decision(state,row['id'],selected_value(view),view['revision'],actor='automation')
    assert state.read_bytes()==saved


@pytest.mark.parametrize('field',['table','rows','cells','global_ids','limits'])
def test_resealed_table_capability_tamper_invalidates_authority_and_keeps_problem_note(tmp_path,field):
    _,_,state=fixture(tmp_path)
    workspace.review_item(state,'table-relationships','blocked',REVIEWER,'2026-10-27',0,'Retain this table problem when its source context becomes stale.')
    raw=workspace.load_workspace(state); row=choose({'decisions':raw['sidecar']['decisions']})
    row['table_context'][field]={'changed':'untrusted-context'}; workspace._save(state,raw)
    stale=workspace.get_view(state)
    assert stale['stale'] and stale['counts']['manual_blocked']==1 and stale['counts']['decision_approved']==0
    assert next(item for item in stale['manual_items'] if item['id']=='table-relationships')['notes'].startswith('Retain this')
    with pytest.raises(workspace.StaleWorkspace): workspace.approve_decision(state,row['id'],REVIEWER,'2026-10-27',stale['revision'])
    with pytest.raises(workspace.StaleWorkspace): workspace.export_workspace(state,tmp_path/'refused',stale['revision'])
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('profile',OLD_PROFILES)
def test_all_six_older_saved_profiles_keep_exact_choices_and_problem_notes(tmp_path,profile):
    _,_,state=fixture(tmp_path,profile=profile)
    view=workspace.review_item(state,'table-relationships','blocked',REVIEWER,'2026-10-27',0,'Keep the older table review and problem note.')
    saved=state.read_bytes(); assert not any(row['kind']==KIND for row in view['decisions'])
    assert workspace.get_view(state)==view and state.read_bytes()==saved


def test_application_reconstruction_keeps_atomic_table_draft_and_refuses_unaccepted_apply(tmp_path):
    source,bundle,_=fixture(tmp_path/'fixture'); protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    config=RuntimeConfig(project_root=tmp_path); root=tmp_path/'service'; app=Application(root,config)
    try:
        identifier=app.import_bundle(bundle); state=app.state_path(identifier); view=app.view(identifier)
        row=choose(view); view=workspace.edit_decision(state,row['id'],selected_value(view),view['revision']); saved=state.read_bytes()
    finally: app.close()
    reopened=Application(root,config)
    try:
        assert reopened.view(identifier)==view and state.read_bytes()==saved
        with pytest.raises(ValueError): reopened.apply(identifier,{'revision':view['revision']})
        assert not reopened.jobs and state.read_bytes()==saved
        assert {path:file_sha256(path) for path in protected}==protected
    finally: reopened.close()
