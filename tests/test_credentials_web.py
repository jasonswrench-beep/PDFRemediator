"""Explicit in-program copy jobs; inline check-mode worker is a named test double."""
from __future__ import annotations

from pathlib import Path
import threading

import pytest

from pdf_remediator import pipeline, web, workspace
from test_credentials_workspace import blocked_review, request_for, protected
from test_web import application, http_app, request, wait_job


def imported_blocked(application,tmp_path):
    source,report,_=blocked_review(tmp_path/'selected')
    identifier=application.import_bundle(report['bundle_path'])
    return source,report,identifier,application.state_path(identifier)


def check_mode_worker(source,destination,config,cancel,progress,**kwargs):
    """Exercise actual derivative/lineage, not native repair qualification."""
    assert config.ocr_mode == 'off' and not kwargs.get('automatic_authorization')
    return pipeline.process_file(source,destination,config,mode='check',cancel=cancel,progress=progress,**kwargs)


def test_authenticated_copy_action_creates_new_source_and_review_retains_original_and_reopens(http_app,tmp_path,monkeypatch):
    app=http_app[0];source,report,identifier,state=imported_blocked(app,tmp_path)
    old=protected(source,report,state);old_view=app.view(identifier)
    monkeypatch.setattr(web,'process_isolated',check_mode_worker)
    route='/api/workspaces/'+identifier+'/credential-copy'
    payload=request_for(state)
    assert request(http_app,route,'POST',payload,token=False)[0] == 403
    assert request(http_app,route,'POST',payload,{'Origin':'https://untrusted.invalid'})[0] == 403
    status,_,queued=request(http_app,route,'POST',payload)
    assert status == 202
    job=wait_job(app,queued['job_id'],seconds=20);assert job['status']=='done',job
    new_id=job['result']['documents'][0]['workspace_id'];assert new_id!=identifier
    view=app.view(new_id)
    assert view['source']['sha256']!=old_view['source']['sha256']
    assert view['credential_derivative']['original']['sha256']==pipeline.sha(source)
    assert view['verification']=='not-verified' and view['counts']['manual_approved']==0
    assert view['credential_copy'] is None and view['ocr_editor']['available'] is False
    original_route='/api/workspaces/'+new_id+'/credential-original'
    record_route='/api/workspaces/'+new_id+'/credential-record'
    assert request(http_app,original_route,token=False)[0]==403
    assert request(http_app,original_route,headers={'Origin':'https://untrusted.invalid'})[0]==403
    assert request(http_app,original_route)[2]==source.read_bytes()
    assert request(http_app,original_route+'?path=C:/private.pdf')[0]==400
    status,headers,record=request(http_app,record_route)
    assert status==200 and record['original']['sha256']==pipeline.sha(source)
    assert record['credential_validity_verified'] is False
    assert 'attachment;' in headers['Content-Disposition']
    assert {path:pipeline.sha(path) for path in old}==old and app.view(identifier)==old_view
    reconstructed=web.Application(app.root,app.config)
    try:assert reconstructed.view(new_id)==view
    finally:reconstructed.close()


def test_queued_copy_revalidates_original_revision_before_derivative_creation(application,tmp_path,monkeypatch):
    source,report,identifier,state=imported_blocked(application,tmp_path)
    task={}
    def capture(label,function):task['function']=function;return {'job_id':'a'*24}
    monkeypatch.setattr(application,'submit',capture)
    payload=request_for(state);application.credential_copy(identifier,payload)
    saved=workspace.load_workspace(state,refresh=False)
    workspace._record_event(saved,'authored-later-review-observation');workspace._save(state,saved)
    current=state.read_bytes()
    with pytest.raises(workspace.RevisionConflict):task['function'](threading.Event(),lambda message:None,'b'*24)
    assert state.read_bytes()==current
    assert not list((application.root/'inputs').glob('*/credential-evidence'))


def test_copy_cancellation_before_creation_leaves_old_review_and_inputs_intact(application,tmp_path,monkeypatch):
    source,report,identifier,state=imported_blocked(application,tmp_path);old=protected(source,report,state);task={}
    monkeypatch.setattr(application,'submit',lambda label,fn:task.update(function=fn) or {'job_id':'a'*24})
    application.credential_copy(identifier,request_for(state));cancel=threading.Event();cancel.set()
    with pytest.raises(InterruptedError):task['function'](cancel,lambda message:None,'b'*24)
    assert {path:pipeline.sha(path) for path in old}==old and not list((application.root/'inputs').iterdir())


def test_credential_lineage_is_forwarded_to_existing_process_worker_without_source_override(application,tmp_path,monkeypatch):
    folder=application.root/'inputs'/('a'*24);folder.mkdir();source=folder/'source.pdf';source.write_bytes(b'%PDF-authored-routing-test')
    lineage={'path':str(folder/'credential-lineage.json'),'sha256':'b'*64}
    pipeline.write_json(folder/'input.json',{'id':'a'*24,'path':str(source),'sha256':pipeline.sha(source),'credential_lineage':lineage})
    task={};monkeypatch.setattr(application,'submit',lambda label,fn:task.update(function=fn) or {'job_id':'c'*24})
    def routed(source_path,destination,config,cancel,progress,**kwargs):
        assert Path(source_path)==source and kwargs['credential_lineage']==lineage['path']
        assert kwargs['expected_credential_lineage_sha256']==lineage['sha256']
        raise ValueError('Authored stop after exact worker routing; no PDF processed')
    monkeypatch.setattr(web,'process_isolated',routed)
    application.process({'inputs':['a'*24],'options':{'ocr_mode':'off'}})
    with pytest.raises(ValueError,match='exact worker routing'):task['function'](threading.Event(),lambda message:None,'d'*24)


def test_preserved_record_route_cannot_select_arbitrary_files_or_ordinary_reviews(application,tmp_path):
    _,_,identifier,_=imported_blocked(application,tmp_path)
    with pytest.raises(ValueError,match='Unknown'):application.credential_record(identifier,'../../private.pdf')
    with pytest.raises(ValueError,match='No current'):application.credential_record(identifier,'credential-original')
