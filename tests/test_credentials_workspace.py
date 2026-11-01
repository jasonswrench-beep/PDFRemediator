"""Saved-review consent guards; parent executes all synthetic PDF creation."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from pdf_remediator import credentials, pipeline, workspace
from pdf_remediator.config import RuntimeConfig
from test_credentials import credential_source, consent_for


def blocked_review(tmp_path):
    source = credential_source(tmp_path/'source')
    report = pipeline.process_file(source, tmp_path/'blocked', RuntimeConfig(project_root=tmp_path))
    assert report['output'] is None and report['baseline']['content_credentials']['supported'] is True
    state = tmp_path/'review.json'
    workspace.create_workspace(report['bundle_path'], state)
    return source, report, state


def request_for(state):
    view = workspace.get_view(state)
    return {'revision':view['revision'], 'source_sha256':view['source']['sha256'],
            'context_sha256':view['credential_copy']['context_sha256'], 'allow_remove':True,
            'reviewer':'Separate-copy test reviewer', 'reviewed_at':'2026-10-28T12:00:00+00:00'}


def protected(source, report, state):
    return {str(p):pipeline.sha(p) for p in [source,state,*Path(report['bundle_path']).rglob('*')] if p.is_file()}


def test_actual_blocked_credentials_offer_explicit_copy_without_rewriting_review(tmp_path):
    source, report, state = blocked_review(tmp_path)
    view = workspace.get_view(state); before = protected(source,report,state)
    assert view['historical_status'] in {'failed','needs-manual'}
    assert view['credential_copy']['eligible'] is True and view['credential_lineage'] is None
    consent = workspace.credential_copy_consent(state,request_for(state))
    assert consent == {'policy':'remove-content-credentials-1','source_sha256':pipeline.sha(source),
        'reviewer':'Separate-copy test reviewer','reviewed_at':'2026-10-28T12:00:00+00:00','allow_remove':True}
    assert {path:pipeline.sha(path) for path in before} == before
    assert workspace.get_view(state) == view


@pytest.mark.parametrize('change', [
    {'revision':True},{'revision':-1},{'allow_remove':False},{'allow_remove':1},{'allow_remove':'true'},
    {'reviewer':''},{'reviewer':'  '},{'reviewed_at':'2026-10-28'},
    {'reviewed_at':'2026-10-28T12:00:00'},{'context_sha256':'a'*64},{'source_sha256':'a'*64},
    {'actor':'AI'},{'automatic':True},{'ai_consent':True},{'consent':True},{'policy':'other'},
])
def test_copy_consent_refuses_missing_or_unbound_authority_without_state_change(tmp_path,change):
    source,report,state = blocked_review(tmp_path); before=protected(source,report,state)
    request=request_for(state);request.update(change)
    with pytest.raises(workspace.WorkspaceError):workspace.credential_copy_consent(state,request)
    assert {path:pipeline.sha(path) for path in before} == before


@pytest.mark.parametrize('key',['revision','allow_remove','reviewer','context_sha256','source_sha256'])
def test_copy_consent_requires_every_explicit_field(tmp_path,key):
    source,report,state=blocked_review(tmp_path);request=request_for(state);request.pop(key)
    before=protected(source,report,state)
    with pytest.raises(workspace.WorkspaceError):workspace.credential_copy_consent(state,request)
    assert {path:pipeline.sha(path) for path in before} == before


def test_changed_original_disables_copy_and_retains_saved_review_observations(tmp_path):
    source,report,state=blocked_review(tmp_path);request=request_for(state)
    before=workspace.load_workspace(state,refresh=False)
    source.write_bytes(source.read_bytes()+b'\n% external source change\n')
    with pytest.raises(workspace.WorkspaceError):workspace.credential_copy_consent(state,request)
    after=workspace.load_workspace(state,refresh=False)
    assert after['stale'] is True
    assert after['manual_items'] == before['manual_items']
    assert after['sidecar'] == before['sidecar']
    assert workspace.get_view(state)['credential_copy']['eligible'] is False


def test_derivative_lineage_reopens_and_ocr_editor_refuses_before_export_or_draft_mutation(tmp_path):
    source,report,state=blocked_review(tmp_path);before=protected(source,report,state)
    derived=credentials.create_derivative(source,tmp_path/'working.pdf',tmp_path/'evidence',consent=consent_for(source))
    copied=pipeline.process_file(derived['source_path'],tmp_path/'recheck',RuntimeConfig(project_root=tmp_path),mode='check',
        credential_lineage=derived['lineage_path'],expected_credential_lineage_sha256=derived['lineage_sha256'])
    new_state=tmp_path/'new-review.json';workspace.create_workspace(copied['bundle_path'],new_state)
    view=workspace.get_view(new_state);saved=new_state.read_bytes()
    assert view['credential_lineage'] == copied['credential_lineage']
    assert view['credential_derivative']['original']['sha256'] == pipeline.sha(source)
    assert view['credential_derivative']['status'] == 'credentials-removed-original-not-verified'
    assert view['ocr_editor']['available'] is False
    for action in [
        lambda:workspace.get_ocr_editor(new_state),
        lambda:workspace.edit_ocr_text(new_state,'unselected','changed',view['revision'],'a'*64,'b'*64),
        lambda:workspace.approve_ocr_text(new_state,'unselected','Named test reviewer','2026-10-28',view['revision'],'a'*64,'b'*64),
        lambda:workspace.remove_ocr_insertion(new_state,'unselected',view['revision'],'a'*64,'b'*64),
        lambda:workspace.export_ocr_corrections(new_state,tmp_path/'must-not-export',view['revision']),
    ]:
        with pytest.raises(workspace.WorkspaceError,match='Content Credentials'):action()
        assert new_state.read_bytes() == saved
    assert not (tmp_path/'must-not-export').exists()
    assert {path:pipeline.sha(path) for path in before} == before
    assert workspace.get_view(new_state) == view
