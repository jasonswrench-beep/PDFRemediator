"""Source-bound reviewed navigation drafts and recovery, using synthetic gates."""
import copy
import json
from pathlib import Path
import shutil

import pikepdf
import pytest

from pdf_remediator import workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import (NAVIGATION_INVENTORY_PROFILE,PASSAGE_LANGUAGE_INVENTORY_PROFILE,
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,LEGACY_INVENTORY_PROFILE,
    collect_decisions,file_sha256,write_sidecar)
from pdf_remediator.web import Application
from test_navigation_pipeline import KINDS,navigation_source,selected_value,value,choose,registered_language_fonts,tagged_control


def fixture(tmp_path,*,profile=NAVIGATION_INVENTORY_PROFILE,hazard=None):
    source=navigation_source(tmp_path/'original')
    if hazard:
        changed=source.with_name('withdrawal-source.pdf')
        with pikepdf.open(source) as pdf:
            if hazard=='bookmark-blank-title':pdf.Root.Outlines.First.Title=''
            else:
                node=pdf.Root.Outlines.First if hazard.startswith('bookmark-') else pdf.pages[1].Annots[0]
                for key in ('/Dest','/A'):
                    if key in node:del node[key]
                if hazard.endswith('broken-target'):node.Dest=pikepdf.String('unresolved-original-target')
            with changed.open('wb') as stream:pdf.save(stream,deterministic_id=True)
        source=changed
    bundle=tmp_path/'bundle';bundle.mkdir();output=bundle/'candidate.pdf';shutil.copyfile(source,output)
    digest=file_sha256(source)
    manual=[{'id':'reading-order','category':'reading-order','required':True,'status':'pending','pages':[],
        'detail':'Inspect meaning and navigation in this authored fixture.'},
        {'id':'metadata-meaning','category':'metadata-meaning','required':True,'status':'pending','pages':[],
        'detail':'Inspect this authored fixture title and language.'}]
    report={'status':'candidate','run_fingerprint':'authored-navigation-review',
        'input':{'path':str(source),'sha256':digest},'output':{'path':str(output),'sha256':digest},
        'decision_source':{'path':str(source),'sha256':digest,'source_sha256':digest},
        'inspection':{'page_count':2},'manual_review':{'artifact_sha256':digest,'items':manual,'complete':False},
        'residual_issues':[],'gate1':{'status':'pass','scope':'Workspace-only explicitly synthetic gate'},
        'gate2':{'status':'pass','checks':[],'manual_queue':copy.deepcopy(manual)},'fidelity':{'status':'pass','after_sha256':digest}}
    write_sidecar(report,bundle/'report.json');write_sidecar(report['manual_review'],bundle/'review.json')
    write_sidecar(collect_decisions(source,inventory_profile=profile),bundle/'decisions.json')
    (bundle/'review.html').write_text('<!doctype html><title>Authored navigation review</title>',encoding='utf-8')
    write_sidecar({'schema_version':'phase1-bundle-1','complete':True,'run_fingerprint':report['run_fingerprint'],
        'files':{path.name:file_sha256(path) for path in bundle.iterdir()}},bundle/'manifest.json')
    assert verify_bundle(bundle)
    state=tmp_path/'saved-review.json';workspace.create_workspace(bundle,state)
    return source,bundle,state


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_navigation_save_named_acceptance_and_export_preserve_original_and_observations(tmp_path,kind):
    source,bundle,state=fixture(tmp_path)
    protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    view=workspace.review_item(state,'reading-order','approved','Synthetic navigation reviewer','2026-10-27',0,
        'Keep this observation when navigation choices require a new judgment.')
    row=choose(view,kind);view=workspace.edit_decision(state,row['id'],selected_value(kind),view['revision'])
    draft=next(item for item in view['decisions'] if item['id']==row['id'])
    assert draft['status']=='pending' and draft['value']==selected_value(kind) and 'approval_sha256' not in draft
    note=next(item for item in view['manual_items'] if item['id']=='reading-order')
    assert note['status']=='pending' and note['notes'].startswith('Keep this observation')
    assert 'reviewer' not in note and 'reviewed_at' not in note
    saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.approve_decision(state,row['id'],'','2026-10-27',view['revision'])
    with pytest.raises(workspace.RevisionConflict):workspace.approve_decision(state,row['id'],'Synthetic navigation reviewer','2026-10-27',view['revision']-1)
    assert state.read_bytes()==saved
    accepted=workspace.approve_decision(state,row['id'],'Synthetic navigation reviewer','2026-10-27',view['revision'])
    exported=workspace.export_workspace(state,tmp_path/'export',accepted['revision'])
    assert exported['requires_reprocessing'] and not exported['ledger_eligible']
    assert accepted['verification']=='not-verified' and accepted['counts']['manual_approved']==0
    assert workspace.get_view(state)==accepted
    assert {path:file_sha256(path) for path in protected}==protected


@pytest.mark.parametrize('kind,bad',[
    ('annotation-name',''),('annotation-name',' \n '),('annotation-name','bad\x00name'),('annotation-name','x'*4001),
    ('link-name',''),('link-name','x'*4001),
    ('link-target','not-json'),('link-target','{}'),('link-target',value({'kind':'page','page':0})),
    ('link-target',value({'kind':'page','page':3})),('link-target',value({'kind':'page','page':True})),
    ('link-target',value({'kind':'page','page':1,'action':'Launch'})),
    ('link-target',value({'kind':'uri','uri':'javascript:alert(1)'})),('link-target',value({'kind':'uri','uri':'file:///secret'})),
    ('link-target',value({'kind':'uri','uri':'https://user:password@example.org/'})),
    ('link-target',value({'kind':'uri','uri':'https://example.org/\nheader'})),
    ('bookmark-entry',value({'title':'','target':{'kind':'page','page':1}})),
    ('bookmark-entry',value({'title':'x'*501,'target':{'kind':'page','page':1}})),
    ('bookmark-entry',value({'title':'New','target':{'kind':'page','page':1},'delete':True})),
    ('bookmark-additions',value({'entries':[{'title':'Child without parent','page':1,'level':2}]})),
    ('bookmark-additions',value({'entries':[{'title':'Root','page':1,'level':1},{'title':'Skipped level','page':2,'level':3}]})),
    ('bookmark-additions',value({'entries':[{'title':'Outside','page':3,'level':1}]})),
    ('bookmark-additions',value({'entries':[{'title':'Root','page':1,'level':True}]})),
    ('bookmark-additions',value({'entries':[{'title':'Root','page':1,'level':1,'parent':'old-node'}]})),
    ('bookmark-additions',value({'entries':[{'title':'Root','page':1,'level':1}]*201})),
])
def test_invalid_navigation_drafts_refuse_without_rewriting_saved_review(tmp_path,kind,bad):
    _,_,state=fixture(tmp_path);view=workspace.get_view(state);row=choose(view,kind);saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.edit_decision(state,row['id'],bad,view['revision'])
    assert state.read_bytes()==saved


def test_large_but_bounded_bookmark_draft_survives_reload_without_old_20k_limit(tmp_path):
    _,_,state=fixture(tmp_path);view=workspace.get_view(state);row=choose(view,'bookmark-additions')
    plan=value({'entries':[{'title':('Reviewed bookmark '+str(index)+' ')*18,'page':1+index%2,'level':1} for index in range(100)]})
    assert 20000<len(plan)<150000
    view=workspace.edit_decision(state,row['id'],plan,view['revision'])
    assert next(item for item in workspace.get_view(state)['decisions'] if item['id']==row['id'])['value']==plan
    saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.edit_decision(state,row['id'],'x'*150001,view['revision'])
    assert state.read_bytes()==saved


@pytest.mark.parametrize('kind',sorted(KINDS))
def test_nonhuman_navigation_edit_and_approval_cannot_bypass_named_review(tmp_path,kind):
    _,_,state=fixture(tmp_path);view=workspace.get_view(state);row=choose(view,kind);saved=state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.edit_decision(state,row['id'],selected_value(kind),view['revision'],actor='automation')
    assert state.read_bytes()==saved


def test_resealed_navigation_scope_tamper_invalidates_approval_and_retains_reported_problem(tmp_path):
    _,_,state=fixture(tmp_path)
    view=workspace.review_item(state,'reading-order','blocked','Synthetic navigation reviewer','2026-10-27',0,
        'Retain this specific navigation problem even if scope evidence becomes stale.')
    raw=workspace.load_workspace(state);row=choose({'decisions':raw['sidecar']['decisions']},'annotation-name')
    row['navigation_context']['annotation_index']=999;workspace._save(state,raw)
    stale=workspace.get_view(state)
    assert stale['stale'] and stale['counts']['manual_blocked']==1 and stale['counts']['decision_approved']==0
    assert stale['manual_items'][0]['notes'].startswith('Retain this specific navigation problem')
    with pytest.raises(workspace.StaleWorkspace):workspace.approve_decision(state,row['id'],'Synthetic navigation reviewer','2026-10-27',stale['revision'])
    with pytest.raises(workspace.StaleWorkspace):workspace.export_workspace(state,tmp_path/'refused',stale['revision'])
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('profile',[LEGACY_INVENTORY_PROFILE,STRUCTURAL_INVENTORY_PROFILE,ARTIFACT_STRUCTURE_INVENTORY_PROFILE,PASSAGE_LANGUAGE_INVENTORY_PROFILE])
def test_all_four_older_saved_profiles_keep_exact_decisions_and_problem_notes(tmp_path,profile):
    _,_,state=fixture(tmp_path,profile=profile)
    view=workspace.review_item(state,'reading-order','blocked','Synthetic earlier reviewer','2026-10-27',0,
        'Keep the older navigation inventory and its original reported problem.')
    saved=state.read_bytes()
    assert not any(row['kind'] in KINDS for row in view['decisions'])
    assert workspace.get_view(state)==view and state.read_bytes()==saved


def test_application_reconstruction_retains_bookmark_draft_and_blocks_unaccepted_apply(tmp_path):
    source,bundle,_=fixture(tmp_path/'fixture')
    protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    config=RuntimeConfig(project_root=tmp_path);root=tmp_path/'service';app=Application(root,config)
    try:
        identifier=app.import_bundle(bundle);state=app.state_path(identifier);view=app.view(identifier)
        row=choose(view,'bookmark-additions');view=workspace.edit_decision(state,row['id'],selected_value('bookmark-additions'),view['revision'])
        saved=state.read_bytes()
    finally:app.close()
    reopened=Application(root,config)
    try:
        assert reopened.view(identifier)==view and state.read_bytes()==saved
        with pytest.raises(ValueError):reopened.apply(identifier,{'revision':view['revision']})
        assert not reopened.jobs and state.read_bytes()==saved
        assert {path:file_sha256(path) for path in protected}==protected
    finally:reopened.close()


@pytest.mark.parametrize('hazard,kind',[('annotation-missing-target','link-target'),('annotation-broken-target','link-target'),
    ('bookmark-missing-target','bookmark-entry'),('bookmark-broken-target','bookmark-entry'),('bookmark-blank-title','bookmark-entry')])
def test_repair_draft_can_be_withdrawn_to_exact_invalid_original_without_losing_notes(tmp_path,hazard,kind):
    source,bundle,state=fixture(tmp_path,hazard=hazard)
    protected={str(path):file_sha256(path) for path in [source,*bundle.iterdir()]}
    view=workspace.review_item(state,'reading-order','pending','Synthetic navigation reviewer','2026-10-27',0,
        'Keep the original navigation problem after withdrawing the proposed repair.')
    row=choose(view,kind);original=row['current']
    view=workspace.edit_decision(state,row['id'],selected_value(kind),view['revision'])
    assert row['id'] in view['unapplied_decisions']
    view=workspace.edit_decision(state,row['id'],original,view['revision'])
    current=next(item for item in view['decisions'] if item['id']==row['id'])
    assert current['value']==current['current']==original and current['status']=='pending'
    assert not view['unapplied_decisions']
    view=workspace.approve_decision(state,row['id'],'Synthetic navigation reviewer','2026-10-27',view['revision'])
    assert not view['unapplied_decisions'] and view['counts']['manual_approved']==0 and view['verification']=='not-verified'
    assert next(item for item in view['manual_items'] if item['id']=='reading-order')['notes'].startswith('Keep the original navigation problem')
    assert workspace.get_view(state)==view and {path:file_sha256(path) for path in protected}==protected
