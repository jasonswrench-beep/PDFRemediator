"""Authored review fixtures exercise authority; gate labels are named stubs."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from pdf_remediator import workspace as ws
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import (ARTIFACT_STRUCTURE_INVENTORY_PROFILE,
    LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE,
    collect_decisions, file_sha256, write_sidecar)
from pdf_remediator.web import Application
from test_artifact_structure import artifact_pdf


def review_fixture(tmp_path, *, profile=ARTIFACT_STRUCTURE_INVENTORY_PROFILE, **kwargs):
    document=artifact_pdf(tmp_path/'source.pdf', **kwargs)
    bundle=tmp_path/'bundle'; bundle.mkdir()
    output=bundle/'candidate.pdf'; shutil.copyfile(document,output)
    digest=file_sha256(document)
    manual=[{'id':'reading-order','category':'reading-order','required':True,
        'detail':'Review the authored structure and meaning.','status':'pending','pages':[]},
        {'id':'contrast','category':'contrast','required':True,
        'detail':'Review this authored fixture.','status':'pending','pages':[]}]
    report={'status':'candidate','run_fingerprint':'authored-artifact-backend',
        'input':{'path':str(document),'sha256':digest},
        'output':{'path':str(output),'sha256':digest},
        'decision_source':{'path':str(document),'sha256':digest,'source_sha256':digest},
        'inspection':{'page_count':2},'manual_review':{'artifact_sha256':digest,'items':manual,'complete':False},
        'residual_issues':[],'gate1':{'status':'pass','scope':'named workspace-only fixture gate'},
        'gate2':{'status':'pass','checks':[],'manual_queue':copy.deepcopy(manual)},
        'fidelity':{'status':'pass','after_sha256':digest}}
    write_sidecar(report,bundle/'report.json')
    write_sidecar(collect_decisions(document,inventory_profile=profile),bundle/'decisions.json')
    write_sidecar(report['manual_review'],bundle/'review.json')
    (bundle/'review.html').write_text('<!doctype html><title>Authored review fixture</title>',encoding='utf-8')
    write_sidecar({'schema_version':'phase1-bundle-1','complete':True,'run_fingerprint':report['run_fingerprint'],
        'files':{p.name:file_sha256(p) for p in bundle.iterdir()}},bundle/'manifest.json')
    assert verify_bundle(bundle)
    state=tmp_path/'state.json'; ws.create_workspace(bundle,state)
    return document,bundle,state


def editable(view,kind,value):
    return next(item for item in view['decisions'] if item['kind']==kind and
        item['structural_eligible'] and value in item['allowed_values'] and item['current']!=value)


@pytest.mark.parametrize('kind,value',[('figure-purpose','Artifact'),('structure-role','Document'),('structure-role','Sect')])
def test_advanced_structural_drafts_need_named_acceptance_and_preserve_prior_observations(tmp_path,kind,value):
    document,bundle,state=review_fixture(tmp_path,root_role='Div',section_role='Div')
    hashes={str(p):file_sha256(p) for p in [document,*bundle.iterdir()]}
    view=ws.get_view(state)
    view=ws.review_item(state,'contrast','approved','Synthetic structure reviewer','2026-10-27',view['revision'],
        'Keep this earlier observation when approval is invalidated.')
    before=ws.load_workspace(state)
    item=editable(view,kind,value)
    changed=ws.edit_decision(state,item['id'],value,view['revision'])
    current=next(row for row in changed['decisions'] if row['id']==item['id'])
    assert current['status']=='pending' and 'approval_sha256' not in current
    assert changed['unapplied_decisions']==[item['id']] and changed['verification']=='not-verified'
    note=next(row for row in changed['manual_items'] if row['id']=='contrast')
    assert note['notes']==before['manual_items'][1]['notes'] and note['status']=='pending'
    assert 'reviewer' not in note and 'reviewed_at' not in note
    saved=state.read_bytes()
    with pytest.raises(ws.WorkspaceError):
        ws.approve_decision(state,item['id'],'','2026-10-27',changed['revision'])
    with pytest.raises(ws.RevisionConflict):
        ws.approve_decision(state,item['id'],'Synthetic structure reviewer','2026-10-27',view['revision'])
    assert state.read_bytes()==saved
    accepted=ws.approve_decision(state,item['id'],'Synthetic structure reviewer','2026-10-27',changed['revision'])
    approved=next(row for row in accepted['decisions'] if row['id']==item['id'])
    assert approved['status']=='approved' and approved['approved_by']=='Synthetic structure reviewer'
    assert accepted['unapplied_decisions']==[item['id']]
    exported=ws.export_workspace(state,tmp_path/'exports',accepted['revision'])
    assert exported['requires_reprocessing'] and not exported['ledger_eligible']
    assert ws.get_view(state)==accepted
    assert {str(p):file_sha256(p) for p in [document,*bundle.iterdir()]}==hashes


@pytest.mark.parametrize('kind,value',[('figure-purpose','Decorative'),('figure-purpose','Document'),
    ('structure-role','Artifact'),('structure-role','H1')])
def test_invalid_advanced_values_refuse_without_rewriting_saved_review(tmp_path,kind,value):
    _,_,state=review_fixture(tmp_path,root_role='Div',section_role='Div')
    view=ws.get_view(state); item=next(row for row in view['decisions'] if row['kind']==kind)
    before=state.read_bytes()
    with pytest.raises(ws.WorkspaceError): ws.edit_decision(state,item['id'],value,view['revision'])
    assert state.read_bytes()==before


def test_unsafe_figure_and_nonhuman_edits_refuse_before_any_saved_change(tmp_path):
    _,_,state=review_fixture(tmp_path,figure_text=True)
    view=ws.get_view(state); item=next(row for row in view['decisions'] if row['kind']=='figure-purpose')
    assert not item['structural_eligible'] and item['structural_limitations']
    before=state.read_bytes()
    with pytest.raises(ws.WorkspaceError): ws.edit_decision(state,item['id'],'Artifact',view['revision'])
    with pytest.raises(ws.WorkspaceError): ws.edit_decision(state,item['id'],'Artifact',view['revision'],actor='automation')
    assert state.read_bytes()==before


@pytest.mark.parametrize('field',['allowed_values','figure_bbox'])
def test_resealed_advanced_context_tamper_invalidates_authority_but_keeps_notes(tmp_path,field):
    _,_,state=review_fixture(tmp_path)
    view=ws.review_item(state,'reading-order','blocked','Synthetic structure reviewer','2026-10-27',0,
        'Keep this reported problem across capability tampering.')
    raw=ws.load_workspace(state)
    item=next(row for row in raw['sidecar']['decisions'] if row['kind']=='figure-purpose')
    if field=='allowed_values': item[field]=['Figure','Artifact','P']
    else: item[field]={'status':'forged-declared-boundary'}
    ws._save(state,raw) # Deliberately resealed authored negative; the scope check must reject it.
    stale=ws.get_view(state)
    assert stale['stale'] and stale['counts']['manual_blocked']==1
    assert stale['counts']['manual_approved']==stale['counts']['decision_approved']==0
    assert stale['manual_items'][0]['notes']=='Keep this reported problem across capability tampering.'
    with pytest.raises(ws.StaleWorkspace):
        ws.approve_decision(state,item['id'],'Synthetic structure reviewer','2026-10-27',stale['revision'])
    with pytest.raises(ws.StaleWorkspace): ws.export_workspace(state,tmp_path/'refused',stale['revision'])
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('profile',[LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE])
def test_older_review_profiles_reopen_without_new_controls_or_rewriting_notes(tmp_path,profile):
    _,_,state=review_fixture(tmp_path,profile=profile)
    view=ws.review_item(state,'reading-order','blocked','Synthetic older reviewer','2026-10-27',0,
        'Keep the old inventory and note exactly.')
    before=state.read_bytes()
    assert not any(row['kind'] in {'figure-purpose','structure-role'} for row in view['decisions'])
    assert ws.get_view(state)==view and state.read_bytes()==before


def test_application_reconstruction_retains_unapplied_purpose_draft_and_blocked_note(tmp_path):
    fixture=tmp_path/'fixture'; fixture.mkdir()
    document,bundle,_=review_fixture(fixture)
    root=tmp_path/'service'; config=RuntimeConfig(project_root=tmp_path)
    protected={str(p):file_sha256(p) for p in [document,*bundle.iterdir()]}
    app=Application(root,config)
    try:
        identifier=app.import_bundle(bundle); state=app.state_path(identifier)
        view=app.view(identifier)
        view=ws.review_item(state,'reading-order','blocked','Synthetic structure reviewer','2026-10-27',view['revision'],
            'This separate reported problem must survive the new control.')
        item=editable(view,'figure-purpose','Artifact')
        view=ws.edit_decision(state,item['id'],'Artifact',view['revision'])
        before=state.read_bytes()
    finally: app.close()
    reopened=Application(root,config)
    try:
        assert reopened.view(identifier)==view and state.read_bytes()==before
        assert reopened.dashboard()['documents'][0]['counts']['manual_blocked']==1
        with pytest.raises(ValueError,match='problem'):
            reopened.apply(identifier,{'revision':view['revision']})
        assert not reopened.jobs and state.read_bytes()==before
        assert {str(p):file_sha256(p) for p in [document,*bundle.iterdir()]}==protected
    finally: reopened.close()
