"""Disposable saved-review contracts for explicit, source-bound empty-tag removal.

The local bundle below has explicitly synthetic validator statuses. These tests
exercise saved authority and preservation; they do not establish accessibility.
"""
from __future__ import annotations

import copy
import json
import shutil

import pytest

from pdf_remediator import workspace
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import (EMPTY_TAG_INVENTORY_PROFILE, collect_decisions,
    file_sha256, write_sidecar)
from test_empty_tag_edits import empty_pdf
from test_empty_tag_pipeline import empty_source, registered_language_fonts, tagged_control


KIND = 'empty-tag-removal'
REVIEWER = 'Authored empty-tag workspace reviewer'
OLD_PROFILES = ('metadata-figures-1', 'reviewed-structure-1',
    'reviewed-artifacts-structure-2', 'reviewed-passage-language-3',
    'reviewed-navigation-4', 'reviewed-semantic-tree-5', 'reviewed-table-6',
    'reviewed-form-7')


def fixture(tmp_path, *, profile=EMPTY_TAG_INVENTORY_PROFILE, variant='safe', empty_count=1):
    source = (empty_source(tmp_path/'source', empty_count=empty_count) if variant == 'safe'
        else empty_pdf(tmp_path/'source.pdf', variant=variant, empty_count=empty_count))
    page_count = 2 if variant == 'safe' else 1
    bundle = tmp_path/'bundle'; bundle.mkdir(); output = bundle/'candidate.pdf'
    shutil.copyfile(source, output); digest = file_sha256(source)
    manual = [{'id': 'empty-tags', 'category': 'empty-tags', 'required': True,
        'status': 'pending', 'pages': [1], 'detail': 'Inspect the original empty-looking tags and their meaning.'},
        {'id': 'reading-order', 'category': 'reading-order', 'required': True,
        'status': 'pending', 'pages': [1], 'detail': 'Inspect the complete source reading sequence.'}]
    report = {'status': 'candidate', 'run_fingerprint': 'authored-empty-tag-workspace',
        'input': {'path': str(source), 'sha256': digest}, 'output': {'path': str(output), 'sha256': digest},
        'decision_source': {'path': str(source), 'sha256': digest, 'source_sha256': digest},
        'inspection': {'page_count': page_count}, 'manual_review': {'artifact_sha256': digest,
            'items': manual, 'complete': False}, 'residual_issues': [],
        'gate1': {'status': 'pass', 'scope': 'Workspace-only explicitly synthetic gate'},
        'gate2': {'status': 'pass', 'checks': [], 'manual_queue': copy.deepcopy(manual)},
        'fidelity': {'status': 'pass', 'after_sha256': digest}}
    write_sidecar(report, bundle/'report.json'); write_sidecar(report['manual_review'], bundle/'review.json')
    write_sidecar(collect_decisions(source, inventory_profile=profile), bundle/'decisions.json')
    (bundle/'review.html').write_text('<!doctype html><title>Authored empty-tag saved review</title>', encoding='utf-8')
    write_sidecar({'schema_version': 'phase1-bundle-1', 'complete': True,
        'run_fingerprint': report['run_fingerprint'],
        'files': {path.name: file_sha256(path) for path in bundle.iterdir()}}, bundle/'manifest.json')
    assert verify_bundle(bundle)
    state = tmp_path/'saved-review.json'; workspace.create_workspace(bundle, state)
    return source, bundle, state


def choose(view):
    return next(row for row in view['decisions'] if row['kind'] == KIND)


def protected(source, bundle):
    return {str(path): file_sha256(path) for path in [source, *bundle.iterdir()]}


def unchanged(paths):
    assert {path: file_sha256(path) for path in paths} == paths


def test_removal_save_accept_export_reopen_preserves_originals_bundles_and_prior_notes(tmp_path):
    source, bundle, state = fixture(tmp_path); originals = protected(source, bundle)
    view = workspace.review_item(state, 'empty-tags', 'approved', REVIEWER, '2026-10-27', 0,
        'Retain this earlier structural observation.')
    item = choose(view)
    assert item['current'] == item['value'] == 'keep' and item['structural_eligible'] is True
    edited = workspace.edit_decision(state, item['id'], 'remove', view['revision'])
    assert choose(edited)['value'] == 'remove' and choose(edited)['status'] == 'pending'
    observed = next(row for row in edited['manual_items'] if row['id'] == 'empty-tags')
    assert observed['status'] == 'pending' and observed['notes'] == 'Retain this earlier structural observation.'
    assert 'reviewer' not in observed and 'reviewed_at' not in observed
    saved = state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):
        workspace.approve_decision(state, item['id'], '', '2026-10-27', edited['revision'])
    with pytest.raises(workspace.RevisionConflict):
        workspace.approve_decision(state, item['id'], REVIEWER, '2026-10-27', edited['revision']-1)
    assert state.read_bytes() == saved
    accepted = workspace.approve_decision(state, item['id'], REVIEWER, '2026-10-27', edited['revision'])
    assert choose(accepted)['status'] == 'approved' and choose(accepted)['approved_by'] == REVIEWER
    assert accepted['verification'] == 'not-verified' and accepted['counts']['manual_approved'] == 0
    saved = state.read_bytes(); assert workspace.get_view(state) == accepted and state.read_bytes() == saved
    exported = workspace.export_workspace(state, tmp_path/'export', accepted['revision'])
    assert exported['requires_reprocessing'] and not exported['ledger_eligible']
    assert state.read_bytes() == saved; unchanged(originals)


def test_exact_keep_withdraws_accepted_removal_without_repair_or_note_loss(tmp_path):
    source, bundle, state = fixture(tmp_path); originals = protected(source, bundle)
    view = workspace.review_item(state, 'empty-tags', 'blocked', REVIEWER, '2026-10-27', 0,
        'Do not infer that the empty-looking tag is meaningless.')
    item = choose(view); view = workspace.edit_decision(state, item['id'], 'remove', view['revision'])
    view = workspace.approve_decision(state, item['id'], REVIEWER, '2026-10-27', view['revision'])
    restored = workspace.edit_decision(state, item['id'], 'keep', view['revision'])
    row = choose(restored)
    assert row['current'] == row['value'] == 'keep' and row['status'] == 'pending'
    assert item['id'] not in restored['unapplied_decisions']
    assert restored['counts']['manual_blocked'] == 1
    assert next(row for row in restored['manual_items'] if row['id'] == 'empty-tags')['notes'] == 'Do not infer that the empty-looking tag is meaningless.'
    saved = state.read_bytes(); assert workspace.get_view(state) == restored and state.read_bytes() == saved
    unchanged(originals)


@pytest.mark.parametrize('value', ['', 'REMOVE', 'Remove', 'delete', 'remove ', ' keep', 'remove\x00',
    'remove\n', '{}', 'null', None, True, 1, [], {}])
def test_invalid_scalar_removal_values_cannot_change_saved_authority(tmp_path, value):
    source, bundle, state = fixture(tmp_path); originals = protected(source, bundle)
    view = workspace.get_view(state); item = choose(view); saved = state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):
        workspace.edit_decision(state, item['id'], value, view['revision'])
    assert state.read_bytes() == saved; unchanged(originals)


@pytest.mark.parametrize('variant', ['dangling-mcid', 'dangling-mcr', 'objr', 'property-Alt',
    'property-ActualText', 'property-ID', 'role-H1', 'role-Figure', 'role-Form', 'role-Link',
    'role-L', 'role-TD', 'ancestor-Table', 'leaf-alias', 'parenttree-ref', 'only-empty'])
def test_disputed_empty_looking_rows_are_readonly_and_cannot_gain_removal_authority(tmp_path, variant):
    source, bundle, state = fixture(tmp_path, variant=variant); originals = protected(source, bundle)
    view = workspace.get_view(state); saved = state.read_bytes()
    rows = [row for row in view['decisions'] if row['kind'] == KIND]
    if variant in {'dangling-mcid', 'dangling-mcr', 'objr'}:
        # These sources contain content references, not an absent/null/empty K.
        # The complete zero-candidate census must not manufacture an editor row.
        assert rows == []
        with pytest.raises(workspace.WorkspaceError):
            workspace.edit_decision(state, 'empty-tag:unavailable-content-reference', 'remove', view['revision'])
        assert state.read_bytes() == saved; unchanged(originals)
        return
    item = rows[0]
    assert item['structural_eligible'] is False and item['allowed_values'] == ['keep']
    assert item['structural_limitations']
    with pytest.raises(workspace.WorkspaceError):
        workspace.edit_decision(state, item['id'], 'remove', view['revision'])
    assert state.read_bytes() == saved; unchanged(originals)


@pytest.mark.parametrize('profile', OLD_PROFILES)
def test_all_eight_older_saved_profiles_keep_exact_inventory_without_new_removal_authority(tmp_path, profile):
    source, bundle, state = fixture(tmp_path, profile=profile); originals = protected(source, bundle)
    saved = state.read_bytes(); inventory = (bundle/'decisions.json').read_bytes()
    first = workspace.get_view(state); second = workspace.get_view(state)
    assert first == second and state.read_bytes() == saved and (bundle/'decisions.json').read_bytes() == inventory
    assert not any(row['kind'] == KIND for row in first['decisions'])
    assert not any('empty_tag_context' in row for row in first['decisions'])
    unchanged(originals)


@pytest.mark.parametrize('defect', ['policy', 'source-element', 'parent-element', 'index', 'nonempty-proof',
    'parent-children', 'allowed-values', 'source-current'])
def test_forged_saved_context_cannot_widen_empty_tag_removal_capability(tmp_path, defect):
    source, bundle, state = fixture(tmp_path); originals = protected(source, bundle)
    raw = json.loads(state.read_text(encoding='utf-8')); item = next(row for row in raw['sidecar']['decisions'] if row['kind'] == KIND)
    context = item['empty_tag_context']
    if defect == 'policy': context['policy'] = 'unproved-policy'
    elif defect == 'source-element': context['source']['element'] = '99999:0'
    elif defect == 'parent-element': context['parent']['element'] = '99999:0'
    elif defect == 'index': context['source']['index'] = 0
    elif defect == 'nonempty-proof': context['parent']['nonempty_children'] = []
    elif defect == 'parent-children': context['parent']['children'].reverse()
    elif defect == 'allowed-values': item['allowed_values'] = ['keep', 'remove', 'delete-content']
    else: item['current'] = 'remove'
    state.write_text(json.dumps(raw), encoding='utf-8'); saved = state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):
        workspace.edit_decision(state, item['id'], 'remove', raw['revision'])
    assert state.read_bytes() == saved; unchanged(originals)


def test_stale_source_refuses_empty_tag_edits_without_rewriting_saved_review_or_bundle(tmp_path):
    source, bundle, state = fixture(tmp_path); originals = {str(path): file_sha256(path) for path in bundle.iterdir()}
    view = workspace.review_item(state, 'empty-tags', 'blocked', REVIEWER, '2026-10-27', 0,
        'Preserve this source-bound observation when detecting staleness.')
    item = choose(view); before = json.loads(state.read_text(encoding='utf-8'))
    source.write_bytes(source.read_bytes()+b'\n% disposable source identity changed\n')
    stale = workspace.get_view(state)
    assert stale['stale'] is True and stale['revision'] == view['revision']+1
    refreshed = json.loads(state.read_text(encoding='utf-8'))
    for key in ['sidecar', 'bindings', 'original_decision_values', 'decision_contexts']:
        assert refreshed[key] == before[key]
    assert next(row for row in stale['manual_items'] if row['id'] == 'empty-tags')['notes'] == 'Preserve this source-bound observation when detecting staleness.'
    assert stale['counts']['manual_approved'] == 0
    saved = state.read_bytes()
    with pytest.raises(workspace.WorkspaceError):
        workspace.edit_decision(state, item['id'], 'remove', stale['revision'])
    assert state.read_bytes() == saved; unchanged(originals)


def test_two_removal_drafts_keep_distinct_source_occurrences_and_acceptance(tmp_path):
    source, bundle, state = fixture(tmp_path, empty_count=2); originals = protected(source, bundle)
    view = workspace.get_view(state); rows = [row for row in view['decisions'] if row['kind'] == KIND]
    assert len(rows) == 2 and rows[0]['element'] != rows[1]['element']
    first = workspace.edit_decision(state, rows[0]['id'], 'remove', view['revision'])
    accepted = workspace.approve_decision(state, rows[0]['id'], REVIEWER, '2026-10-27', first['revision'])
    second = next(row for row in accepted['decisions'] if row['id'] == rows[1]['id'])
    assert second['value'] == 'keep' and second['status'] == 'pending'
    assert accepted['unapplied_decisions'] == [rows[0]['id']]
    unchanged(originals)
