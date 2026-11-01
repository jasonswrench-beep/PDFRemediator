"""Saved form drafts, named acceptance, recovery and immutable prior reviews."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil

import pytest

from pdf_remediator import sidecar, workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import FORM_INVENTORY_PROFILE, collect_decisions, file_sha256, write_sidecar
from pdf_remediator.web import Application
from test_form_pipeline import (KIND, OLD_PROFILES, REVIEWER, choose, form_source,
    selected_value, value, registered_language_fonts, tagged_control)


def fixture(tmp_path, *, profile=FORM_INVENTORY_PROFILE, repaired=False):
    source = form_source(tmp_path/'source', repaired=repaired)
    bundle = tmp_path/'bundle'; bundle.mkdir(); output = bundle/'candidate.pdf'; shutil.copyfile(source, output)
    digest = file_sha256(source)
    manual = [{'id': 'form-meaning', 'category': 'form-meaning', 'required': True, 'status': 'pending', 'pages': [1, 2],
        'detail': 'Inspect the authored form labels, required instructions and full keyboard sequence.'},
        {'id': 'reading-order', 'category': 'reading-order', 'required': True, 'status': 'pending', 'pages': [],
        'detail': 'Inspect the source reading order and structure.'}]
    report = {'status': 'candidate', 'run_fingerprint': 'authored-static-form-review',
        'input': {'path': str(source), 'sha256': digest}, 'output': {'path': str(output), 'sha256': digest},
        'decision_source': {'path': str(source), 'sha256': digest, 'source_sha256': digest},
        'inspection': {'page_count': 2}, 'manual_review': {'artifact_sha256': digest, 'items': manual, 'complete': False},
        'residual_issues': [], 'gate1': {'status': 'pass', 'scope': 'Workspace-only explicitly synthetic gate'},
        'gate2': {'status': 'pass', 'checks': [], 'manual_queue': copy.deepcopy(manual)},
        'fidelity': {'status': 'pass', 'after_sha256': digest}}
    write_sidecar(report, bundle/'report.json'); write_sidecar(report['manual_review'], bundle/'review.json')
    write_sidecar(collect_decisions(source, inventory_profile=profile), bundle/'decisions.json')
    (bundle/'review.html').write_text('<!doctype html><title>Authored static form review</title>', encoding='utf-8')
    write_sidecar({'schema_version': 'phase1-bundle-1', 'complete': True, 'run_fingerprint': report['run_fingerprint'],
        'files': {path.name: file_sha256(path) for path in bundle.iterdir()}}, bundle/'manifest.json')
    assert verify_bundle(bundle)
    state = tmp_path/'saved-review.json'; workspace.create_workspace(bundle, state)
    return source, bundle, state


def test_form_draft_named_acceptance_export_and_reopen_preserve_source_and_notes(tmp_path):
    source, bundle, state = fixture(tmp_path)
    protected = {str(path): file_sha256(path) for path in [source, *bundle.iterdir()]}
    view = workspace.review_item(state, 'form-meaning', 'approved', REVIEWER, '2026-10-27', 0, 'Retain the earlier form label observation.')
    row = choose(view); new = selected_value(view)
    view = workspace.edit_decision(state, row['id'], new, view['revision'])
    assert choose(view)['value'] == new and choose(view)['status'] == 'pending'
    observed = next(item for item in view['manual_items'] if item['id'] == 'form-meaning')
    assert observed['status'] == 'pending' and observed['notes'] == 'Retain the earlier form label observation.'
    assert 'reviewer' not in observed and 'reviewed_at' not in observed
    saved = state.read_bytes()
    with pytest.raises(workspace.WorkspaceError): workspace.approve_decision(state, row['id'], '', '2026-10-27', view['revision'])
    with pytest.raises(workspace.RevisionConflict): workspace.approve_decision(state, row['id'], REVIEWER, '2026-10-27', view['revision']-1)
    assert state.read_bytes() == saved
    accepted = workspace.approve_decision(state, row['id'], REVIEWER, '2026-10-27', view['revision'])
    exported = workspace.export_workspace(state, tmp_path/'export', accepted['revision'])
    assert exported['requires_reprocessing'] and not exported['ledger_eligible']
    assert accepted['verification'] == 'not-verified' and accepted['counts']['manual_approved'] == 0
    assert workspace.get_view(state) == accepted and {path: file_sha256(path) for path in protected} == protected


def test_restoring_exact_missing_label_original_withdraws_draft_without_repair_credit(tmp_path):
    source, bundle, state = fixture(tmp_path)
    view = workspace.review_item(state, 'form-meaning', 'blocked', REVIEWER, '2026-10-27', 0, 'Retain the missing label and navigation problem.')
    row = choose(view); view = workspace.edit_decision(state, row['id'], selected_value(view), view['revision'])
    view = workspace.edit_decision(state, row['id'], row['current'], view['revision'])
    restored = choose(view)
    assert restored['status'] == 'pending' and restored['value'] == restored['current']
    assert view['counts']['manual_blocked'] == 1 and view['counts']['decision_approved'] == 0
    assert next(item for item in view['manual_items'] if item['id'] == 'form-meaning')['notes'] == 'Retain the missing label and navigation problem.'
    saved = state.read_bytes(); assert workspace.get_view(state) == view and state.read_bytes() == saved


INVALID = ['bad-json', 'empty-object', 'too-large', 'extra-plan', 'missing-field', 'duplicate-field', 'field-order',
    'foreign-field', 'extra-field', 'missing-widget', 'duplicate-widget', 'foreign-widget', 'extra-widget',
    'tooltip-null', 'tooltip-blank', 'tooltip-nul', 'tooltip-type', 'tooltip-too-long',
    'alt-blank', 'alt-nul', 'alt-type', 'alt-too-long', 'missing-page', 'duplicate-page', 'page-order',
    'foreign-page', 'boolean-page', 'extra-page', 'tabs-row', 'tabs-type', 'missing-order', 'duplicate-order',
    'foreign-parent', 'duplicate-child', 'missing-child', 'foreign-child', 'extra-order', 'order-without-structure-tabs']


def invalid_value(view, case):
    plan = json.loads(selected_value(view)); fields, pages, orders = plan['fields'], plan['pages'], plan['orders']
    if case == 'bad-json': return '{'
    if case == 'empty-object': return '{}'
    if case == 'too-large': return 'x'*150001
    if case == 'extra-plan': plan['actions'] = []
    elif case == 'missing-field': fields.pop()
    elif case == 'duplicate-field': fields[1] = copy.deepcopy(fields[0])
    elif case == 'field-order': fields.reverse()
    elif case == 'foreign-field': fields[0]['field'] = '999:0'
    elif case == 'extra-field': fields[0]['internal_name'] = 'not-authorized'
    elif case == 'missing-widget': fields[0]['widgets'] = []
    elif case == 'duplicate-widget': fields[0]['widgets'].append(copy.deepcopy(fields[0]['widgets'][0]))
    elif case == 'foreign-widget': fields[0]['widgets'][0]['widget'] = '999:0'
    elif case == 'extra-widget': fields[0]['widgets'][0]['value'] = 'not-authorized'
    elif case == 'tooltip-null': fields[0]['tooltip'] = None
    elif case == 'tooltip-blank': fields[0]['tooltip'] = ' \t\r\n'
    elif case == 'tooltip-nul': fields[0]['tooltip'] = 'Name\x00'
    elif case == 'tooltip-type': fields[0]['tooltip'] = []
    elif case == 'tooltip-too-long': fields[0]['tooltip'] = 'x'*4001
    elif case == 'alt-blank': fields[0]['widgets'][0]['alternative'] = '  '
    elif case == 'alt-nul': fields[0]['widgets'][0]['alternative'] = 'Name\x00'
    elif case == 'alt-type': fields[0]['widgets'][0]['alternative'] = {}
    elif case == 'alt-too-long': fields[0]['widgets'][0]['alternative'] = 'x'*4001
    elif case == 'missing-page': pages.pop()
    elif case == 'duplicate-page': pages[1] = copy.deepcopy(pages[0])
    elif case == 'page-order': pages.reverse()
    elif case == 'foreign-page': pages[0]['page'] = 99
    elif case == 'boolean-page': pages[0]['page'] = True
    elif case == 'extra-page': pages[0]['annots'] = []
    elif case == 'tabs-row': pages[0]['tabs'] = 'R'
    elif case == 'tabs-type': pages[0]['tabs'] = []
    elif case == 'missing-order': orders.pop()
    elif case == 'duplicate-order': orders.append(copy.deepcopy(orders[0]))
    elif case == 'foreign-parent': orders[0]['parent'] = '999:0'
    elif case == 'duplicate-child': orders[0]['children'][1] = orders[0]['children'][0]
    elif case == 'missing-child': orders[0]['children'].pop()
    elif case == 'foreign-child': orders[0]['children'][0] = '999:0'
    elif case == 'extra-order': orders[0]['infer'] = True
    elif case == 'order-without-structure-tabs': pages[0]['tabs'] = None
    else: raise ValueError('Unknown invalid form plan')
    return value(plan)


@pytest.mark.parametrize('case', INVALID)
def test_invalid_atomic_form_drafts_do_not_rewrite_saved_reviews(tmp_path, case):
    _, _, state = fixture(tmp_path, repaired=True); view = workspace.get_view(state); row = choose(view); saved = state.read_bytes()
    with pytest.raises(workspace.WorkspaceError): workspace.edit_decision(state, row['id'], invalid_value(view, case), view['revision'])
    assert state.read_bytes() == saved


def test_nonhuman_form_changes_cannot_bypass_named_review(tmp_path):
    _, _, state = fixture(tmp_path); view = workspace.get_view(state); row = choose(view); saved = state.read_bytes()
    with pytest.raises(workspace.WorkspaceError): workspace.edit_decision(state, row['id'], selected_value(view), view['revision'], actor='automation')
    assert state.read_bytes() == saved
    with pytest.raises(sidecar.DecisionError):
        sidecar.make_automatic_authorization(row['binding']['source_sha256'], row['binding']['document_sha256'],
            '2026-10-27T12:00:00Z', decision_ids=[row['id']])
    title = next(item for item in view['decisions'] if item['kind'] == 'title')
    authorization = sidecar.make_automatic_authorization(row['binding']['source_sha256'], row['binding']['document_sha256'],
        '2026-10-27T12:00:00Z', decision_ids=[title['id']])
    with pytest.raises(sidecar.DecisionError, match='automatic scope'):
        sidecar.bind_automatic_acceptance(copy.deepcopy(row), selected_value(view), authorization, origin={'kind': 'developer-only'})


@pytest.mark.parametrize('field', ['fields', 'pages', 'orders', 'limits'])
def test_resealed_form_capability_tamper_keeps_problem_notes_but_invalidates_authority(tmp_path, field):
    _, _, state = fixture(tmp_path)
    workspace.review_item(state, 'form-meaning', 'blocked', REVIEWER, '2026-10-27', 0, 'Retain the original form problem note.')
    raw = workspace.load_workspace(state); row = choose({'decisions': raw['sidecar']['decisions']})
    row['form_context'][field] = {'changed': 'untrusted-context'}; workspace._save(state, raw)
    stale = workspace.get_view(state)
    assert stale['stale'] and stale['counts']['manual_blocked'] == 1 and stale['counts']['decision_approved'] == 0
    assert next(item for item in stale['manual_items'] if item['id'] == 'form-meaning')['notes'] == 'Retain the original form problem note.'
    with pytest.raises(workspace.StaleWorkspace): workspace.approve_decision(state, row['id'], REVIEWER, '2026-10-27', stale['revision'])
    with pytest.raises(workspace.StaleWorkspace): workspace.export_workspace(state, tmp_path/'refused', stale['revision'])
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('profile', OLD_PROFILES)
def test_all_seven_older_saved_profiles_reopen_without_new_choices_or_note_loss(tmp_path, profile):
    _, _, state = fixture(tmp_path, profile=profile)
    view = workspace.review_item(state, 'form-meaning', 'blocked', REVIEWER, '2026-10-27', 0, 'Keep the older form review observation.')
    saved = state.read_bytes(); assert not any(row['kind'] == KIND for row in view['decisions'])
    assert workspace.get_view(state) == view and state.read_bytes() == saved


def test_application_reconstruction_keeps_form_draft_and_refuses_unaccepted_apply(tmp_path):
    source, bundle, _ = fixture(tmp_path/'fixture')
    protected = {str(path): file_sha256(path) for path in [source, *bundle.iterdir()]}
    config = RuntimeConfig(project_root=tmp_path); root = tmp_path/'service'; app = Application(root, config)
    try:
        identifier = app.import_bundle(bundle); state = app.state_path(identifier); view = app.view(identifier)
        row = choose(view); view = workspace.edit_decision(state, row['id'], selected_value(view), view['revision']); saved = state.read_bytes()
    finally: app.close()
    reopened = Application(root, config)
    try:
        assert reopened.view(identifier) == view and state.read_bytes() == saved
        with pytest.raises(ValueError): reopened.apply(identifier, {'revision': view['revision']})
        assert not reopened.jobs and state.read_bytes() == saved
        assert {path: file_sha256(path) for path in protected} == protected
    finally: reopened.close()
