"""Language review authority on authored fixtures with explicitly synthetic gates."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from pdf_remediator import workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import (PASSAGE_LANGUAGE_INVENTORY_PROFILE,
    LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE, ARTIFACT_STRUCTURE_INVENTORY_PROFILE,
    collect_decisions,file_sha256,write_sidecar)
from pdf_remediator.web import Application
from test_language_edits import language_pdf


def value(language):return json.dumps({'language':language},sort_keys=True,separators=(',',':'))


def fixture(tmp_path,profile=PASSAGE_LANGUAGE_INVENTORY_PROFILE,**kwargs):
    source=language_pdf(tmp_path/'source.pdf',**kwargs)
    bundle=tmp_path/'bundle';bundle.mkdir()
    output=bundle/'candidate.pdf';shutil.copyfile(source,output)
    digest=file_sha256(source)
    manual=[{'id':'reading-order','category':'reading-order','required':True,'status':'pending','pages':[],
        'detail':'Inspect this authored fixture.'},
        {'id':'metadata-meaning','category':'metadata-meaning','required':True,'status':'pending','pages':[],
        'detail':'Inspect the title and language assignments.'}]
    report={'status':'candidate','run_fingerprint':'authored-local-language-review',
        'input':{'path':str(source),'sha256':digest},'output':{'path':str(output),'sha256':digest},
        'decision_source':{'path':str(source),'sha256':digest,'source_sha256':digest},
        'inspection':{'page_count':2},'manual_review':{'artifact_sha256':digest,'items':manual,'complete':False},
        'residual_issues':[],'gate1':{'status':'pass','scope':'Named workspace-only synthetic gate'},
        'gate2':{'status':'pass','checks':[],'manual_queue':copy.deepcopy(manual)},'fidelity':{'status':'pass','after_sha256':digest}}
    write_sidecar(report,bundle/'report.json');write_sidecar(report['manual_review'],bundle/'review.json')
    write_sidecar(collect_decisions(source,inventory_profile=profile),bundle/'decisions.json')
    (bundle/'review.html').write_text('<!doctype html><title>Authored local-language review fixture</title>',encoding='utf-8')
    write_sidecar({'schema_version':'phase1-bundle-1','complete':True,'run_fingerprint':report['run_fingerprint'],
        'files':{p.name:file_sha256(p) for p in bundle.iterdir()}},bundle/'manifest.json')
    assert verify_bundle(bundle)
    state=tmp_path/'saved-review.json';workspace.create_workspace(bundle,state)
    return source,bundle,state


def select(view,kind):
    return next(item for item in view['decisions'] if item['kind']==kind and item['page']==1 and item['structural_eligible'])


@pytest.mark.parametrize('kind',['page-language','passage-language'])
def test_local_language_save_accept_export_keeps_source_and_old_observations(tmp_path,kind):
    source,bundle,state=fixture(tmp_path)
    protected={str(p):file_sha256(p) for p in [source,*bundle.iterdir()]}
    view=workspace.get_view(state)
    view=workspace.review_item(state,'metadata-meaning','approved','Synthetic language reviewer','2026-10-27',view['revision'],
        'Retain this observation even when the language edit requires new review.')
    item=select(view,kind)
    assert item['language_context']['effective']=='en-US'
    changed=workspace.edit_decision(state,item['id'],value('fr-CA'),view['revision'])
    current=next(row for row in changed['decisions'] if row['id']==item['id'])
    assert current['status']=='pending' and current['value']==value('fr-CA') and 'approval_sha256' not in current
    note=next(row for row in changed['manual_items'] if row['id']=='metadata-meaning')
    assert note['status']=='pending' and note['notes'].startswith('Retain this observation')
    assert 'reviewer' not in note and 'reviewed_at' not in note
    before=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):
        workspace.approve_decision(state,item['id'],'','2026-10-27',changed['revision'])
    with pytest.raises(workspace.RevisionConflict):
        workspace.approve_decision(state,item['id'],'Synthetic language reviewer','2026-10-27',view['revision'])
    assert state.read_bytes()==before
    accepted=workspace.approve_decision(state,item['id'],'Synthetic language reviewer','2026-10-27',changed['revision'])
    assert accepted['counts']['decision_approved']==1 and accepted['verification']=='not-verified'
    exported=workspace.export_workspace(state,tmp_path/'export',accepted['revision'])
    assert exported['requires_reprocessing'] and not exported['ledger_eligible']
    assert workspace.get_view(state)==accepted
    assert {str(p):file_sha256(p) for p in [source,*bundle.iterdir()]}==protected


@pytest.mark.parametrize('kind',['page-language','passage-language'])
def test_inheritance_is_an_explicit_saved_null_not_an_empty_or_guessed_tag(tmp_path,kind):
    _,_,state=fixture(tmp_path,container_language='es',passage_language='fr')
    view=workspace.get_view(state);item=select(view,kind)
    if kind=='passage-language':
        item=next(row for row in view['decisions'] if row['kind']==kind and row['page']==1
            and row['structural_eligible'] and row['language_context']['direct']=='fr')
    assert item['language_context']['direct'] in {'es','fr'}
    changed=workspace.edit_decision(state,item['id'],value(None),view['revision'])
    row=next(row for row in changed['decisions'] if row['id']==item['id'])
    assert row['value']==value(None) and row['status']=='pending'
    assert row['language_context']==item['language_context'] and row['language_scope']==item['language_scope']
    assert changed['unapplied_decisions']==[item['id']] and workspace.get_view(state)==changed


@pytest.mark.parametrize('bad',[value(''),value('en_US'),value('en-a-foo-a-bar'),value('de-1901-1901'),
    '{"language":3}','{"language":false}','{"language":"fr","scope":"all"}','{}','fr'])
def test_invalid_language_drafts_refuse_without_rewriting_saved_state(tmp_path,bad):
    _,_,state=fixture(tmp_path);view=workspace.get_view(state);item=select(view,'passage-language')
    before=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.edit_decision(state,item['id'],bad,view['revision'])
    assert state.read_bytes()==before


def test_unproven_page_and_nonhuman_language_edits_are_refused(tmp_path):
    _,_,state=fixture(tmp_path,missing_page_container=True)
    view=workspace.get_view(state)
    item=next(row for row in view['decisions'] if row['kind']=='page-language' and row['page']==1)
    assert not item['structural_eligible'] and item['structural_limitations']
    before=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.edit_decision(state,item['id'],value('fr'),view['revision'])
    passage=select(view,'passage-language')
    with pytest.raises(workspace.WorkspaceError):
        workspace.edit_decision(state,passage['id'],value('fr'),view['revision'],actor='automation')
    assert state.read_bytes()==before


@pytest.mark.parametrize('field',['language_context','language_scope'])
def test_resealed_language_scope_tamper_invalidates_authority_and_retains_problem_notes(tmp_path,field):
    _,_,state=fixture(tmp_path)
    view=workspace.review_item(state,'reading-order','blocked','Synthetic language reviewer','2026-10-27',0,
        'Keep this problem attached to the original reviewed context.')
    raw=workspace.load_workspace(state);item=select({'decisions':raw['sidecar']['decisions']},'passage-language')
    item[field]={'forged':'changed source capability'};workspace._save(state,raw)
    stale=workspace.get_view(state)
    assert stale['stale'] and stale['counts']['manual_blocked']==1 and stale['counts']['decision_approved']==0
    assert stale['manual_items'][0]['notes']=='Keep this problem attached to the original reviewed context.'
    with pytest.raises(workspace.StaleWorkspace):
        workspace.approve_decision(state,item['id'],'Synthetic language reviewer','2026-10-27',stale['revision'])
    with pytest.raises(workspace.StaleWorkspace):workspace.export_workspace(state,tmp_path/'refused',stale['revision'])
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('profile',[LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,ARTIFACT_STRUCTURE_INVENTORY_PROFILE])
def test_all_older_saved_review_profiles_keep_their_exact_inventory_and_notes(tmp_path,profile):
    _,_,state=fixture(tmp_path,profile=profile)
    view=workspace.review_item(state,'reading-order','blocked','Synthetic older reviewer','2026-10-27',0,
        'Keep the pre-language-editor inventory and reported problem.')
    before=state.read_bytes()
    assert not any(row['kind'] in {'page-language','passage-language'} for row in view['decisions'])
    assert workspace.get_view(state)==view and state.read_bytes()==before


def test_application_reconstruction_retains_language_draft_and_blocked_review(tmp_path):
    folder=tmp_path/'fixture';folder.mkdir();source,bundle,_=fixture(folder)
    hashes={str(p):file_sha256(p) for p in [source,*bundle.iterdir()]}
    root=tmp_path/'service';config=RuntimeConfig(project_root=tmp_path);app=Application(root,config)
    try:
        identifier=app.import_bundle(bundle);state=app.state_path(identifier);view=app.view(identifier)
        view=workspace.review_item(state,'reading-order','blocked','Synthetic language reviewer','2026-10-27',view['revision'],
            'A separate reported problem stays blocked during language repair drafting.')
        item=select(view,'passage-language');view=workspace.edit_decision(state,item['id'],value('fr'),view['revision'])
        before=state.read_bytes()
    finally:app.close()
    reopened=Application(root,config)
    try:
        assert reopened.view(identifier)==view and state.read_bytes()==before
        with pytest.raises(ValueError,match='problem'):reopened.apply(identifier,{'revision':view['revision']})
        assert not reopened.jobs and state.read_bytes()==before
        assert {str(p):file_sha256(p) for p in [source,*bundle.iterdir()]}==hashes
    finally:reopened.close()
