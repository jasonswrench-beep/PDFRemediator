"""Review-state tests use synthetic PDF/bundle fixtures, not human release evidence."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading

import pikepdf
import pytest

from pdf_remediator.cli import _review_data
from pdf_remediator.ledger import _eligible
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import approval_digest, collect_decisions, file_sha256, load_sidecar, write_sidecar
from pdf_remediator import workspace as ws


def _pdf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.new() as pdf:
        pages = [pdf.add_blank_page(), pdf.add_blank_page()]
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        figures = []
        for index, page in enumerate(pages):
            page.obj.Contents = pdf.make_stream(b"/Figure <</MCID 0>> BDC 0 0 20 20 re f EMC")
            figures.append(pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                S=pikepdf.Name.Figure, P=tree, Pg=page.obj, K=0, Alt=f"A square under caption {index + 1}")))
        tree.K = pikepdf.Array(figures)
        pdf.Root.StructTreeRoot = tree
        pdf.Root.Lang = "en-US"
        pdf.docinfo.Title = "Synthetic review fixture"
        pdf.save(path, deterministic_id=True)


def _regroup(identifier, page, removed, kind="list-label-regroup"):
    evidence = {"kind": kind, "stream": f"page:{page}", "retained_mcid": 0,
                "removed_mcids": removed, "source_text_bytes_sha256": hashlib.sha256(identifier.encode()).hexdigest()}
    return {"id": identifier, "category": "tag-regrouping", "subject": "Inspect regrouped content",
            "detail": json.dumps(evidence), "page": None, "required": True, "status": "pending"}


def _make_bundle(tmp_path, name="bundle", published=True):
    source = tmp_path / "inputs" / (name + ".pdf")
    _pdf(source)
    prepared = tmp_path / "prepared" / (name + ".pdf")
    prepared.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, prepared)
    bundle = tmp_path / name
    bundle.mkdir()
    output = bundle / "candidate.pdf"
    if published:
        shutil.copyfile(prepared, output)
    sha = file_sha256(source)
    manual = [_regroup("regroup-a", 1, [1]), _regroup("regroup-b", 2, [3]),
              _regroup("regroup-exception", 1, [1, 2]), _regroup("regroup-link", 2, [1], "single-target-list-link-expansion"),
              {"id": "reading-order", "category": "reading-order", "detail": "Inspect all pages in logical order", "pages": [], "required": True, "status": "pending"},
              {"id": "contrast", "category": "contrast", "detail": "Inspect visible contrast", "pages": [], "required": True, "status": "pending"}]
    report = {"status": "candidate" if published else "failed", "mode": "fix", "run_fingerprint": "synthetic-" + name,
              "input": {"path": str(source), "sha256": sha},
              "output": {"path": str(output), "sha256": sha, "review_only": False} if published else None,
              "decision_source": {"path": str(prepared), "sha256": sha, "source_sha256": sha},
              "inspection": {"page_count": 2}, "manual_review": {"artifact_sha256": sha if published else None, "items": manual, "complete": False},
              "residual_issues": [],
              # Synthetic gate records only: tests exercise state binding, never
              # claim these fixture PDFs underwent an external validator run.
              "gate1": {"status": "pass", "profile": "ua1", "is_compliant": True, "input_sha256": sha,
                        "execution": {"status": "completed", "returncode": 0},
                        "counts": {"passedRules": 106, "failedRules": 0, "failedChecks": 0}},
              "gate2": {"status": "pass", "checks": [{"id": "synthetic-test-stub", "status": "pass", "blocking": True}],
                        "blockers": [], "manual_queue": copy.deepcopy(manual)},
              "fidelity": {"status": "pass", "after_sha256": sha}}
    write_sidecar(report, bundle / "report.json")
    write_sidecar(report["manual_review"], bundle / "review.json")
    write_sidecar(collect_decisions(prepared, sha), bundle / "decisions.json")
    (bundle / "review.html").write_text("<!doctype html><html lang='en'><title>Test review</title></html>", encoding="utf-8")
    files = {path.name: file_sha256(path) for path in bundle.iterdir() if path.is_file()}
    write_sidecar({"schema_version": "phase1-bundle-1", "complete": True, "run_fingerprint": report["run_fingerprint"], "files": files}, bundle / "manifest.json")
    assert verify_bundle(bundle)
    return bundle, source, prepared, output, report


@pytest.fixture
def sample(tmp_path):
    bundle, source, prepared, output, report = _make_bundle(tmp_path)
    state = tmp_path / "reviews" / "workspace.json"
    ws.create_workspace(bundle, state)
    return {"bundle": bundle, "source": source, "prepared": prepared, "output": output, "report": report, "state": state}


def _approve_item(sample, identifier="reading-order"):
    view = ws.get_view(sample["state"])
    return ws.review_item(sample["state"], identifier, "approved", "Synthetic Test Reviewer", "2026-10-16", view["revision"])


def test_import_and_display_preserve_immutable_bundle_and_all_occurrences(sample):
    hashes = {path.name: file_sha256(path) for path in sample["bundle"].iterdir()}
    original_state = sample["state"].read_bytes()
    view = ws.get_view(sample["state"])
    assert view["status"] == "candidate" and view["verification"] == "not-verified"
    assert view["counts"]["manual_total"] == 6 and view["counts"]["manual_pending"] == 6
    assert len(view["decisions"]) == 4
    assert len({item["id"] for item in view["manual_items"]}) == 6
    group = next(group for group in view["groups"] if set(group["member_ids"]) == {"regroup-a", "regroup-b"})
    assert group["pages"] == [1, 2] and group["counts"]["total"] == 2
    assert group["requires_context_review"] is True
    assert all(len(group["member_ids"]) == 1 for group in view["groups"] if group["kind"] == "decision")
    assert {path.name: file_sha256(path) for path in sample["bundle"].iterdir()} == hashes
    assert sample["state"].read_bytes() == original_state


def test_regroup_exceptions_and_unrecognized_patterns_are_not_hidden(sample):
    view = ws.get_view(sample["state"])
    groups = {identifier: group for group in view["groups"] for identifier in group["member_ids"]}
    assert groups["regroup-exception"]["id"] != groups["regroup-a"]["id"]
    assert groups["regroup-link"]["id"] != groups["regroup-a"]["id"]
    manual = {item["id"]: item for item in view["manual_items"]}
    assert manual["regroup-a"]["page"] is None
    assert manual["regroup-a"]["resolved_pages"] == [1]
    assert manual["regroup-a"]["evidence"]["source_text_bytes_sha256"] != manual["regroup-b"]["evidence"]["source_text_bytes_sha256"]


def test_selected_group_approval_is_explicit_and_occurrence_scoped(sample):
    view = ws.get_view(sample["state"])
    group = next(group for group in view["groups"] if "regroup-a" in group["member_ids"])
    updated = ws.approve_group(sample["state"], group["id"], ["regroup-a"], group["membership_digest"],
                               "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    items = {item["id"]: item for item in updated["manual_items"]}
    assert items["regroup-a"]["status"] == "approved"
    assert items["regroup-b"]["status"] == "pending"
    assert updated["history"][-1]["member_ids"] == ["regroup-a"]
    assert updated["status"] == "candidate" and updated["verification"] == "not-verified"


@pytest.mark.parametrize("defect", ["revision", "digest", "foreign-member", "empty", "duplicate"])
def test_group_approval_refuses_ambiguous_or_stale_selection(sample, defect):
    view = ws.get_view(sample["state"])
    group = next(group for group in view["groups"] if "regroup-a" in group["member_ids"])
    revision, digest, members = view["revision"], group["membership_digest"], ["regroup-a"]
    if defect == "revision":
        revision += 1
    elif defect == "digest":
        digest = "0" * 64
    elif defect == "foreign-member":
        members = ["contrast"]
    elif defect == "empty":
        members = []
    else:
        members = ["regroup-a", "regroup-a"]
    with pytest.raises(ws.WorkspaceError):
        ws.approve_group(sample["state"], group["id"], members, digest, "Synthetic Test Reviewer", "2026-10-16", revision)
    assert ws.get_view(sample["state"])["counts"]["manual_approved"] == 0


def test_blocker_changes_current_status_and_preserves_original_candidate_history(sample, tmp_path):
    report_hash = file_sha256(sample["bundle"] / "report.json")
    view = ws.review_item(sample["state"], "reading-order", "blocked", "Synthetic Test Reviewer", "2026-10-16", 0, "Confirmed wrong order in synthetic test")
    assert view["status"] == "needs-manual" and view["historical_status"] == "candidate"
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", view["revision"])
    assert exported["ledger_eligible"] is False
    assert json.loads(Path(exported["review_path"]).read_text(encoding="utf-8"))["items"][4]["status"] == "blocked"
    assert file_sha256(sample["bundle"] / "report.json") == report_hash


def test_human_edit_invalidates_prior_artifact_reviews_and_requires_new_processing(sample, tmp_path):
    view = _approve_item(sample)
    view = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    view = ws.edit_decision(sample["state"], "metadata:title", "A revised synthetic title", view["revision"])
    assert view["counts"]["manual_approved"] == 0
    assert view["status"] == "needs-manual" and view["unapplied_decisions"] == ["metadata:title"]
    decision = next(item for item in view["decisions"] if item["id"] == "metadata:title")
    assert decision["status"] == "pending" and "approval_sha256" not in decision
    with pytest.raises(ws.WorkspaceError, match="reprocessing"):
        ws.review_item(sample["state"], "reading-order", "approved", "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    view = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", view["revision"])
    assert exported["requires_reprocessing"] and not exported["ledger_eligible"]
    assert next(item for item in load_sidecar(exported["sidecar_path"])["decisions"] if item["kind"] == "title")["status"] == "approved"
    assert file_sha256(sample["output"]) == sample["report"]["output"]["sha256"]


def _annotated_manual_choices(sample):
    view = ws.commit_automatic_review(sample["state"], ws.plan_automatic_review(sample["state"]), 0)
    for identifier, status, notes in (
        ("reading-order", "blocked", "Confirmed reading-order problem; a title edit cannot resolve it."),
        ("contrast", "pending", "Keep this note for my individual contrast review."),
        ("regroup-a", "approved", "Previous artifact's synthetic positive review."),
    ):
        view = ws.review_item(sample["state"], identifier, status, "Synthetic Test Reviewer",
                              "2026-10-16", view["revision"], notes)
    assert view["counts"]["manual_blocked"] == view["counts"]["manual_approved"] == 1
    assert view["counts"]["automated_count"] == 3
    return view


@pytest.mark.parametrize("mode", ["human", "automatic"])
@pytest.mark.parametrize("kind", ["title", "figure-description"])
def test_changed_decision_preserves_blockers_and_pending_notes_but_invalidates_approvals(tmp_path, mode, kind):
    # Automatic mode uses an authored envelope with zero provider calls. All
    # source/result PDFs and gate records are generated synthetic test fixtures.
    sample = _automatic_sample(tmp_path)
    view = _annotated_manual_choices(sample)
    decision = next(item for item in view["decisions"] if item["kind"] == kind)
    identifier, value = decision["id"], "A changed synthetic " + kind
    if mode == "automatic":
        view = ws.merge_ai_drafts(sample["state"], _envelope(sample, identifier, value), view["revision"])
    before = ws.load_workspace(sample["state"])
    protected = {item["id"]: copy.deepcopy(item) for item in before["manual_items"]
                 if item["id"] in {"reading-order", "contrast"}}
    paths = list(sample["bundle"].iterdir()) + [sample["source"], sample["prepared"]]
    hashes = {str(path): file_sha256(path) for path in paths}
    if mode == "human":
        changed = ws.edit_decision(sample["state"], identifier, value, view["revision"])
    else:
        changed = ws.apply_automatic_suggestions(sample["state"], _automatic_authorization(sample, [identifier]),
            view["revision"], suggestion_ids=[view["suggestions"][0]["suggestion_id"]])
    current = ws.load_workspace(sample["state"])
    items = {item["id"]: item for item in current["manual_items"]}
    assert {identifier: items[identifier] for identifier in protected} == protected
    assert current["manual_touched"] == before["manual_touched"]
    assert current["history"][:-1] == before["history"]
    assert current["revision"] == before["revision"] + 1
    assert items["regroup-a"]["status"] == "pending" and current["manual_approvals"] == {}
    previous_positive = next(item for item in before["manual_items"] if item["id"] == "regroup-a")
    retained_positive = {key: copy.deepcopy(value) for key, value in previous_positive.items()
                         if key not in {"reviewer", "reviewed_at"}}
    retained_positive["status"] = "pending"
    assert items["regroup-a"] == retained_positive
    assert items["regroup-a"]["notes"] == "Previous artifact's synthetic positive review."
    assert all(key not in items["regroup-a"] for key in ("reviewer", "reviewed_at"))
    assert changed["counts"]["manual_blocked"] == 1 and changed["counts"]["manual_approved"] == 0
    assert changed["counts"]["automated_count"] == 0 and changed["verification"] == "not-verified"
    assert changed["unapplied_decisions"] == [identifier]
    assert {entry["record_sha256"] for entry in current["automatic_review_invalidations"]} == {
        entry["record_sha256"] for entry in before["automatic_review_records"]}
    reopened = ws.get_view(sample["state"])
    assert reopened == changed
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", changed["revision"])
    exported_items = {item["id"]: item for item in load_sidecar(exported["review_path"])["items"]}
    assert {identifier: exported_items[identifier] for identifier in protected} == protected
    assert exported_items["regroup-a"] == retained_positive
    assert exported["requires_reprocessing"] and not exported["ledger_eligible"]
    assert {str(path): file_sha256(path) for path in paths} == hashes


@pytest.mark.parametrize("mode", ["human", "automatic"])
def test_same_value_decision_does_not_invalidate_manual_choices_or_automatic_records(tmp_path, mode):
    sample = _automatic_sample(tmp_path)
    view = _annotated_manual_choices(sample)
    title = next(item for item in view["decisions"] if item["kind"] == "title")
    if mode == "automatic":
        view = ws.merge_ai_drafts(sample["state"], _envelope(sample, title["id"], title["value"]), view["revision"])
    before = ws.load_workspace(sample["state"])
    if mode == "human":
        changed = ws.edit_decision(sample["state"], title["id"], title["value"], view["revision"])
    else:
        changed = ws.apply_automatic_suggestions(sample["state"], _automatic_authorization(sample),
            view["revision"], suggestion_ids=[view["suggestions"][0]["suggestion_id"]])
    current = ws.load_workspace(sample["state"])
    for field in ("manual_items", "manual_approvals", "manual_touched", "automatic_review_records", "automatic_review_invalidations"):
        assert current[field] == before[field]
    assert current["revision"] == before["revision"] + 1
    assert changed["counts"]["manual_blocked"] == changed["counts"]["manual_approved"] == 1
    assert changed["counts"]["automated_count"] == 3 and changed["unapplied_decisions"] == []


def test_pending_values_export_without_fake_approval_and_review_scopes_match_cli(sample, tmp_path):
    view = ws.get_view(sample["state"])
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", view["revision"])
    data = load_sidecar(exported["sidecar_path"])
    assert all(item["status"] == "pending" for item in data["decisions"])
    assert _review_data(sample["report"], Path(exported["review_path"]))["manual_review"]["items"] == sample["report"]["manual_review"]["items"]
    assert exported["verification"] == "not-verified" and not exported["ledger_eligible"]


def test_complete_explicit_human_checks_export_ledger_compatible_review_without_claiming_verification(sample, tmp_path):
    view = ws.get_view(sample["state"])
    for group in view["groups"]:
        if group["kind"] == "manual":
            view = ws.approve_group(sample["state"], group["id"], group["member_ids"], group["membership_digest"],
                                    "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", view["revision"])
    reviewed = _review_data(sample["report"], Path(exported["review_path"]))
    assert len(_eligible(reviewed, file_sha256(sample["output"]))) == 6
    assert exported["ledger_eligible"] is True
    assert exported["verification"] == view["verification"] == "not-verified"
    assert view["status"] == "candidate"


@pytest.mark.parametrize("changed", ["source", "prepared", "output", "manifest"])
def test_changed_bound_files_invalidate_every_approval_and_block_actions(sample, tmp_path, changed):
    view = _approve_item(sample)
    view = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    target = sample[changed] if changed != "manifest" else sample["bundle"] / "manifest.json"
    original = target.read_bytes()
    target.write_bytes(original + b"\n% changed after approval\n")
    stale = ws.get_view(sample["state"])
    assert stale["stale"] and stale["status"] == "needs-manual"
    assert stale["counts"]["manual_approved"] == stale["counts"]["decision_approved"] == 0
    with pytest.raises(ws.WorkspaceError):
        ws.export_workspace(sample["state"], tmp_path / "exports", stale["revision"])
    with pytest.raises(ws.WorkspaceError):
        ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", stale["revision"])
    target.write_bytes(original)
    restored = ws.get_view(sample["state"])
    assert restored["stale"] and not restored["counts"]["manual_approved"]


def _assert_stale_notes_and_authority(sample, before, tmp_path, *, decision_context_transition=False):
    """An earlier observation survives without becoming current approval."""
    stale = ws.get_view(sample["state"])
    current = ws.load_workspace(sample["state"], refresh=False)
    assert not current.get("source_lineage"), "Exercise the old non-lineage review path"
    assert stale["stale"] and stale["status"] == "needs-manual"
    assert stale["counts"]["manual_blocked"] == 1
    assert stale["counts"]["manual_approved"] == stale["counts"]["decision_approved"] == 0
    assert stale["counts"]["decision_auto_accepted"] == stale["counts"]["automated_count"] == 0
    assert stale["verification"] == "not-verified" and current["manual_approvals"] == {}
    expected = []
    for item in before["manual_items"]:
        retained = {key: copy.deepcopy(value) for key, value in item.items()
                    if key not in {"reviewer", "reviewed_at"}}
        retained["status"] = "blocked" if item["status"] == "blocked" else "pending"
        expected.append(retained)
    assert current["manual_items"] == expected
    assert current["manual_touched"] == before["manual_touched"]
    assert current["history"][:-1] == before["history"]
    event = current["history"][-1]
    assert event["action"] == "invalidate-stale-inputs"
    assert event["retained_manual_notes"] == [
        {"id": item["id"], "notes": item["notes"], "previous_status": item["status"]}
        for item in before["manual_items"] if "notes" in item]
    assert {"regroup-a", "metadata:title"}.issubset(event["invalidated_ids"])
    assert current["revision"] == before["revision"] + 1
    assert all(not any(key in item for key in ("approved_by", "approved_at", "approval_sha256",
               "automatic_application", "automatic_acceptance_sha256"))
               for item in current["sidecar"]["decisions"])
    if decision_context_transition:
        # The first refresh removes the bad approval while the independently
        # changed context remains. Record that exact, legitimate reason change
        # once; subsequent reopening must then be byte-stable.
        assert current["stale_reasons"] == [
            "Decision approval no longer matches its value/context", "Workspace decision context changed"]
        first = current
        stale = ws.get_view(sample["state"])
        current = ws.load_workspace(sample["state"], refresh=False)
        assert current["stale_reasons"] == ["Workspace decision context changed"]
        assert current["revision"] == first["revision"] + 1
        assert current["history"][:-1] == first["history"]
        settled_event = current["history"][-1]
        assert settled_event["action"] == "invalidate-stale-inputs"
        assert settled_event["reasons"] == current["stale_reasons"]
        assert settled_event["invalidated_ids"] == settled_event["invalidated_automatic_decision_ids"] == []
        assert settled_event["retained_manual_notes"] == [
            {"id": item["id"], "notes": item["notes"], "previous_status": item["status"]}
            for item in first["manual_items"] if "notes" in item]
        changed_fields = {"state_sha256", "updated_at", "revision", "history", "stale_reasons"}
        assert {key: value for key, value in current.items() if key not in changed_fields} == {
            key: value for key, value in first.items() if key not in changed_fields}
        assert stale["stale"] and stale["status"] == "needs-manual"
        assert stale["counts"]["manual_blocked"] == 1
        assert stale["counts"]["manual_approved"] == stale["counts"]["decision_approved"] == 0
        assert stale["counts"]["decision_auto_accepted"] == stale["counts"]["automated_count"] == 0
        assert stale["verification"] == "not-verified"
    saved = sample["state"].read_bytes()
    assert ws.get_view(sample["state"]) == stale
    assert ws.load_workspace(sample["state"])["revision"] == current["revision"]
    assert sample["state"].read_bytes() == saved
    destination = tmp_path / "stale-export-refused"
    with pytest.raises(ws.StaleWorkspace):
        ws.export_workspace(sample["state"], destination, stale["revision"])
    assert not destination.exists()
    with pytest.raises(ws.StaleWorkspace):
        ws.review_item(sample["state"], "contrast", "approved", "Synthetic Test Reviewer",
                       "2026-10-16", stale["revision"])
    with pytest.raises(ws.StaleWorkspace):
        ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer",
                            "2026-10-16", stale["revision"])
    with pytest.raises(ws.StaleWorkspace):
        ws.edit_decision(sample["state"], "metadata:title", "A refused stale edit", stale["revision"])
    assert sample["state"].read_bytes() == saved
    return stale, saved


@pytest.mark.parametrize("changed", ["source", "prepared", "output", "manifest"])
@pytest.mark.parametrize("defect", ["changed", "missing"])
def test_legacy_stale_review_retains_all_notes_and_blockers_without_authority(tmp_path, changed, defect):
    sample = _automatic_sample(tmp_path)
    view = _annotated_manual_choices(sample)
    ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer",
                        "2026-10-16", view["revision"])
    before = ws.load_workspace(sample["state"])
    paths = list(sample["bundle"].iterdir()) + [sample["source"], sample["prepared"]]
    hashes = {str(path): file_sha256(path) for path in paths}
    target = sample[changed] if changed != "manifest" else sample["bundle"] / "manifest.json"
    original = target.read_bytes()
    if defect == "missing":
        target.unlink()
    else:
        target.write_bytes(original + b"\n% Synthetic stale-input test\n")
    stale, saved = _assert_stale_notes_and_authority(sample, before, tmp_path)
    target.write_bytes(original)
    restored = ws.get_view(sample["state"])
    assert restored == stale and restored["stale"]
    assert sample["state"].read_bytes() == saved
    assert {str(path): file_sha256(path) for path in paths} == hashes


@pytest.mark.parametrize("defect", ["manual-scope", "decision-context", "manual-approval", "decision-approval"])
def test_legacy_context_or_approval_change_retains_annotations_but_refuses_old_authority(tmp_path, defect):
    sample = _automatic_sample(tmp_path)
    view = _annotated_manual_choices(sample)
    ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer",
                        "2026-10-16", view["revision"])
    state = ws.load_workspace(sample["state"])
    # Deliberately reseal synthetic test corruption so the independent scope and
    # approval checks, rather than only the outer state hash, must reject it.
    if defect == "manual-scope":
        next(item for item in state["manual_items"] if item["id"] == "reading-order")["detail"] += " changed"
    elif defect == "decision-context":
        next(item for item in state["sidecar"]["decisions"] if item["id"] == "metadata:title")["context_sha256"] = "0" * 64
    elif defect == "manual-approval":
        state["manual_approvals"]["regroup-a"] = "0" * 64
    else:
        next(item for item in state["sidecar"]["decisions"] if item["id"] == "metadata:title")["approval_sha256"] = "0" * 64
    ws._save(sample["state"], state)
    before = ws.load_workspace(sample["state"], refresh=False)
    _assert_stale_notes_and_authority(sample, before, tmp_path,
                                      decision_context_transition=defect == "decision-context")


def test_legacy_stale_notes_survive_additional_invalidations_and_empty_observations(sample, tmp_path):
    view = ws.review_item(sample["state"], "reading-order", "blocked", "Synthetic Test Reviewer",
                          "2026-10-16", 0, "Keep this confirmed problem.")
    view = ws.review_item(sample["state"], "contrast", "pending", "Synthetic Test Reviewer",
                          "2026-10-16", view["revision"], "")
    view = ws.review_item(sample["state"], "regroup-a", "approved", "Synthetic Test Reviewer",
                          "2026-10-16", view["revision"], "Keep this positive observation, without approval.")
    before = ws.load_workspace(sample["state"])
    original_source, original_prepared = sample["source"].read_bytes(), sample["prepared"].read_bytes()
    sample["source"].write_bytes(original_source + b"\n% first changed binding\n")
    first = ws.get_view(sample["state"])
    first_state = ws.load_workspace(sample["state"], refresh=False)
    assert first_state["history"][:-1] == before["history"]
    assert len(first_state["history"][-1]["retained_manual_notes"]) == 3
    sample["prepared"].write_bytes(original_prepared + b"\n% additional changed binding\n")
    second = ws.get_view(sample["state"])
    second_state = ws.load_workspace(sample["state"], refresh=False)
    assert second["revision"] == first["revision"] + 1
    assert second_state["history"][:-1] == first_state["history"]
    assert second_state["manual_items"] == first_state["manual_items"]
    assert len(second_state["history"][-1]["retained_manual_notes"]) == 3
    notes = {item["id"]: item.get("notes") for item in second["manual_items"]}
    assert notes["reading-order"] == "Keep this confirmed problem."
    assert notes["contrast"] == "" and notes["regroup-a"] == "Keep this positive observation, without approval."
    assert second["counts"]["manual_blocked"] == 1 and second["counts"]["manual_approved"] == 0
    saved = sample["state"].read_bytes()
    assert ws.get_view(sample["state"]) == second and sample["state"].read_bytes() == saved
    sample["source"].write_bytes(original_source)
    sample["prepared"].write_bytes(original_prepared)
    assert ws.get_view(sample["state"]) == second and sample["state"].read_bytes() == saved


def test_valid_legacy_review_reopens_with_all_saved_annotations_and_no_migration(tmp_path):
    sample = _automatic_sample(tmp_path)
    view = _annotated_manual_choices(sample)
    before = ws.load_workspace(sample["state"])
    saved = sample["state"].read_bytes()
    assert not before.get("source_lineage")
    assert ws.get_view(sample["state"]) == view
    assert ws.load_workspace(sample["state"]) == before
    assert ws.get_view(sample["state"]) == view
    assert sample["state"].read_bytes() == saved


def test_explicit_review_action_can_replace_notes_without_silent_invalidation(sample):
    view = ws.review_item(sample["state"], "reading-order", "blocked", "Synthetic Test Reviewer",
                          "2026-10-16", 0, "An earlier explicit problem note.")
    before = ws.load_workspace(sample["state"])
    updated = ws.review_item(sample["state"], "reading-order", "pending", "Synthetic Second Reviewer",
                             "2026-10-17", view["revision"])
    item = next(item for item in updated["manual_items"] if item["id"] == "reading-order")
    assert item["status"] == "pending" and item["notes"] == ""
    assert item["reviewer"] == "Synthetic Second Reviewer" and item["reviewed_at"] == "2026-10-17"
    assert updated["history"][:-1] == before["history"]
    assert updated["history"][-2]["notes"] == "An earlier explicit problem note."
    assert updated["counts"]["manual_approved"] == 0 and not updated["stale"]


def test_bad_manifest_or_checkpoint_cannot_be_imported(tmp_path):
    bundle, source, prepared, output, _ = _make_bundle(tmp_path)
    with prepared.open("ab") as stream:
        stream.write(b"\n% Stale prepared checkpoint\n")
    with pytest.raises(ws.StaleWorkspace):
        ws.create_workspace(bundle, tmp_path / "state.json")
    assert not (tmp_path / "state.json").exists()
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ws.WorkspaceError):
        ws.create_workspace(bundle, tmp_path / "state.json")


def test_workspace_and_export_paths_cannot_write_into_immutable_bundle_or_pdf(sample):
    with pytest.raises(ws.WorkspaceError):
        ws.create_workspace(sample["bundle"], sample["bundle"] / "mutable.json")
    with pytest.raises(ws.WorkspaceError):
        ws.create_workspace(sample["bundle"], sample["source"])
    with pytest.raises(ws.WorkspaceError):
        ws.export_workspace(sample["state"], sample["bundle"] / "exports", 0)
    assert verify_bundle(sample["bundle"])


def test_external_state_edit_is_detected_before_approval(sample):
    data = json.loads(sample["state"].read_text(encoding="utf-8"))
    data["manual_items"][0]["status"] = "approved"
    sample["state"].write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ws.WorkspaceError, match="outside"):
        ws.get_view(sample["state"])


def test_cross_process_lock_and_revision_guard_prevent_lost_updates(sample):
    lock = sample["state"].with_name(sample["state"].name + ".lock")
    lock.write_text("another writer", encoding="utf-8")
    with pytest.raises(ws.RevisionConflict):
        ws.review_item(sample["state"], "reading-order", "approved", "Synthetic Test Reviewer", "2026-10-16", 0)
    assert lock.read_text(encoding="utf-8") == "another writer"
    lock.unlink()
    barrier = threading.Barrier(2)

    def update(identifier):
        barrier.wait(timeout=5)
        try:
            ws.review_item(sample["state"], identifier, "approved", "Synthetic Test Reviewer", "2026-10-16", 0)
            return "updated"
        except ws.RevisionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(update, ["reading-order", "contrast"]))
    assert sorted(results) == ["conflict", "updated"]
    view = ws.get_view(sample["state"])
    assert view["revision"] == 1 and view["counts"]["manual_approved"] == 1


def test_no_output_bundle_allows_triage_without_approval_or_human_review_export(tmp_path):
    bundle, *_ = _make_bundle(tmp_path, published=False)
    path = tmp_path / "workspace.json"
    ws.create_workspace(bundle, path)
    assert ws.get_view(path)["status"] == "failed"
    with pytest.raises(ws.WorkspaceError):
        ws.review_item(path, "reading-order", "approved", "Synthetic Test Reviewer", "2026-10-16", 0)
    with pytest.raises(ws.WorkspaceError):
        ws.approve_decision(path, "metadata:title", "Synthetic Test Reviewer", "2026-10-16", 0)
    exported = ws.export_workspace(path, tmp_path / "exports", 0)
    assert exported["review_path"] is None and not exported["ledger_eligible"]


def test_new_bundle_import_never_copies_old_artifact_approvals(sample, tmp_path):
    _approve_item(sample)
    new_bundle, *_ = _make_bundle(tmp_path, name="new-bundle")
    second = tmp_path / "second-workspace.json"
    ws.create_workspace(new_bundle, second)
    view = ws.get_view(second)
    assert view["revision"] == 0 and view["counts"]["manual_approved"] == 0
    assert view["workspace_id"] != ws.get_view(sample["state"])["workspace_id"]


def test_ai_cannot_directly_edit_or_approve_decisions(sample):
    with pytest.raises(ws.WorkspaceError, match="separate drafts"):
        ws.edit_decision(sample["state"], "metadata:title", "AI replacement", 0, actor="ai")
    assert ws.get_view(sample["state"])["counts"]["decision_approved"] == 0


@pytest.mark.parametrize("reviewer,date", [("", "2026-10-16"), ("Synthetic Test Reviewer", "bad-date")])
def test_approval_requires_explicit_named_reviewer_and_date(sample, reviewer, date):
    with pytest.raises(ValueError):
        ws.approve_decision(sample["state"], "metadata:title", reviewer, date, 0)
    assert ws.get_view(sample["state"])["revision"] == 0


def _envelope(sample, identifier="metadata:title", value="A contextual AI title draft"):
    sidecar = ws.load_workspace(sample["state"])["sidecar"]
    item = next(item for item in sidecar["decisions"] if item["id"] == identifier)
    return {"schema_version": "phase2-assistance-1", "status": "draft", "source_sha256": sidecar["source_sha256"],
            "document_sha256": sidecar["document_sha256"], "suggestions": [{"id": identifier, "kind": item["kind"],
                "value": value, "status": "draft", "binding": copy.deepcopy(item["binding"]),
                "context_sha256": item["context_sha256"], "original_value_sha256": hashlib.sha256(item["value"].encode("utf-8")).hexdigest(),
                "provenance": {"provider": "local-openai-compatible", "endpoint": "http://127.0.0.1:11434/v1",
                               "schema_version": "phase2-assistance-1", "model": "synthetic-stub"}}],
            "data_sent": {"provider_calls": 0, "document_requests": 0, "scope": "test envelope; no model service used"}}


def test_ai_proposal_stays_separate_until_explicit_adoption_then_still_requires_approval(sample):
    before = ws.get_view(sample["state"])
    envelope = _envelope(sample)
    staged = ws.merge_ai_drafts(sample["state"], envelope, before["revision"])
    assert staged["decisions"][0]["value"] == before["decisions"][0]["value"]
    assert staged["decisions"][0]["status"] == "pending"
    assert staged["counts"]["manual_approved"] == staged["counts"]["decision_approved"] == 0
    assert staged["suggestions"][0]["status"] == "draft"
    adopted = ws.accept_suggestion(sample["state"], staged["suggestions"][0]["suggestion_id"], staged["revision"])
    assert adopted["decisions"][0]["value"] == envelope["suggestions"][0]["value"]
    assert adopted["decisions"][0]["status"] == "pending" and "approved_by" not in adopted["decisions"][0]
    assert adopted["status"] == "needs-manual" and adopted["verification"] == "not-verified"
    approved = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", adopted["revision"])
    assert approved["decisions"][0]["status"] == "approved" and approved["counts"]["manual_approved"] == 0


@pytest.mark.parametrize("protection", ["edited", "approved", "edited-after-staging"])
def test_ai_drafts_cannot_overwrite_current_human_edits_or_approvals(sample, protection):
    envelope = _envelope(sample)
    view = ws.get_view(sample["state"])
    if protection == "edited-after-staging":
        view = ws.merge_ai_drafts(sample["state"], envelope, view["revision"])
        suggestion_id = view["suggestions"][0]["suggestion_id"]
    if protection == "approved":
        view = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    else:
        view = ws.edit_decision(sample["state"], "metadata:title", "Keep this human title", view["revision"])
    value = view["decisions"][0]["value"]
    if protection == "edited-after-staging":
        with pytest.raises(ws.WorkspaceError, match="human"):
            ws.accept_suggestion(sample["state"], suggestion_id, view["revision"])
    else:
        view = ws.merge_ai_drafts(sample["state"], envelope, view["revision"])
        assert view["history"][-1]["skipped_human_protected_ids"] == ["metadata:title"]
        assert not view["suggestions"]
    assert ws.get_view(sample["state"])["decisions"][0]["value"] == value


@pytest.mark.parametrize("defect", ["source", "document", "context", "value-hash", "approval", "unknown-id"])
def test_stale_or_authority_seeking_ai_envelopes_cannot_enter_review_state(sample, defect):
    envelope = _envelope(sample)
    if defect == "source":
        envelope["source_sha256"] = "b" * 64
    elif defect == "document":
        envelope["document_sha256"] = "b" * 64
    elif defect == "context":
        envelope["suggestions"][0]["context_sha256"] = "b" * 64
    elif defect == "value-hash":
        envelope["suggestions"][0]["original_value_sha256"] = "b" * 64
    elif defect == "approval":
        envelope["suggestions"][0]["approved_by"] = "AI"
    else:
        envelope["suggestions"][0]["id"] = "not-a-real-occurrence"
    original = sample["state"].read_bytes()
    with pytest.raises(ValueError):
        ws.merge_ai_drafts(sample["state"], envelope, 0)
    assert sample["state"].read_bytes() == original


def test_imported_pending_human_value_is_protected_from_later_ai(sample, tmp_path):
    # A bundle may retain a reviewer-edited pending value that was deliberately
    # not applied. Import must not mistake it for a replaceable machine default.
    sidecar = load_sidecar(sample["bundle"] / "decisions.json")
    sidecar["decisions"][0]["value"] = "An imported pending human edit"
    write_sidecar(sidecar, sample["bundle"] / "decisions.json")
    manifest = json.loads((sample["bundle"] / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["decisions.json"] = file_sha256(sample["bundle"] / "decisions.json")
    write_sidecar(manifest, sample["bundle"] / "manifest.json")
    fresh = tmp_path / "new-state.json"
    ws.create_workspace(sample["bundle"], fresh)
    other = {**sample, "state": fresh}
    view = ws.merge_ai_drafts(fresh, _envelope(other), 0)
    assert view["decisions"][0]["human_touched"] is True
    assert view["decisions"][0]["value"] == "An imported pending human edit"
    assert not view["suggestions"]
    assert view["status"] == "needs-manual" and view["unapplied_decisions"] == ["metadata:title"]
    with pytest.raises(ws.WorkspaceError, match="reprocessing"):
        ws.review_item(fresh, "reading-order", "approved", "Synthetic Test Reviewer", "2026-10-16", view["revision"])


def test_export_publishes_one_coherent_revision_atomically(sample, tmp_path, monkeypatch):
    replace = ws.atomic_replace
    published = []

    def observe(source, destination):
        if Path(source).is_dir():
            assert not Path(destination).exists()
            metadata = json.loads((Path(source) / "export.json").read_text(encoding="utf-8"))
            assert metadata["revision"] == 0 and metadata["verification"] == "not-verified"
            assert all(file_sha256(Path(source) / name) == sha for name, sha in metadata["files"].items())
            published.append(Path(destination))
        replace(source, destination)

    monkeypatch.setattr(ws, "atomic_replace", observe)
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", 0)
    assert published == [Path(exported["sidecar_path"]).parent]


def test_changes_during_export_publish_nothing_and_invalidate_state(sample, tmp_path, monkeypatch):
    write = ws.write_sidecar

    def change_late(data, path):
        result = write(data, path)
        if Path(path).name == "export.json":
            with sample["output"].open("ab") as stream:
                stream.write(b"\n% Changed while exporting\n")
        return result

    monkeypatch.setattr(ws, "write_sidecar", change_late)
    destination = tmp_path / "exports"
    with pytest.raises(ws.StaleWorkspace):
        ws.export_workspace(sample["state"], destination, 0)
    assert not list(destination.iterdir())
    assert ws.get_view(sample["state"])["stale"] is True


def test_changes_during_approval_cannot_leave_an_active_approval(sample, monkeypatch):
    approve = ws._approve_item

    def change_late(*args, **kwargs):
        approve(*args, **kwargs)
        with sample["output"].open("ab") as stream:
            stream.write(b"\n% Changed while approving\n")

    monkeypatch.setattr(ws, "_approve_item", change_late)
    with pytest.raises(ws.StaleWorkspace):
        ws.review_item(sample["state"], "reading-order", "approved", "Synthetic Test Reviewer", "2026-10-16", 0)
    view = ws.get_view(sample["state"])
    assert view["stale"] and not view["counts"]["manual_approved"]


def test_group_approval_cannot_sweep_a_confirmed_blocker_into_approved_state(sample):
    view = ws.review_item(sample["state"], "regroup-a", "blocked", "Synthetic Test Reviewer", "2026-10-16", 0,
                          "Confirmed wrong list relationship in synthetic test")
    group = next(group for group in view["groups"] if "regroup-a" in group["member_ids"])
    with pytest.raises(ws.WorkspaceError, match="individual"):
        ws.approve_group(sample["state"], group["id"], group["member_ids"], group["membership_digest"],
                          "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    current = ws.get_view(sample["state"])
    assert current["status"] == "needs-manual" and current["counts"]["manual_blocked"] == 1
    assert not current["counts"]["manual_approved"]


def test_tail_preserving_groups_retain_individual_context_and_separate_different_tail_lengths(sample, tmp_path):
    report = copy.deepcopy(sample["report"])
    for identifier, page, tail in (("tail-a", 1, [2]), ("tail-b", 2, [9]), ("tail-longer", 1, [3, 4]), ("tail-malformed", 2, {"unexpected": 1})):
        item = _regroup(identifier, page, [1], "single-target-list-link-expansion-preserving-tail")
        detail = json.loads(item["detail"])
        detail["retained_body_tail_mcids"] = tail
        item["detail"] = json.dumps(detail)
        report["manual_review"]["items"].append(item)
    write_sidecar(report, sample["bundle"] / "report.json")
    write_sidecar(report["manual_review"], sample["bundle"] / "review.json")
    manifest = json.loads((sample["bundle"] / "manifest.json").read_text(encoding="utf-8"))
    for name in ("report.json", "review.json"):
        manifest["files"][name] = file_sha256(sample["bundle"] / name)
    write_sidecar(manifest, sample["bundle"] / "manifest.json")
    fresh = tmp_path / "tail-workspace.json"
    ws.create_workspace(sample["bundle"], fresh)
    view = ws.get_view(fresh)
    groups = {identifier: group for group in view["groups"] for identifier in group["member_ids"]}
    items = {item["id"]: item for item in view["manual_items"]}
    assert view["counts"]["manual_total"] == 10
    assert groups["tail-a"]["id"] == groups["tail-b"]["id"]
    assert groups["tail-a"]["pattern"]["retained_tail_mcid_count"] == 1
    assert groups["tail-longer"]["id"] != groups["tail-a"]["id"]
    assert groups["tail-malformed"]["member_ids"] == ["tail-malformed"]
    assert groups["tail-a"]["id"] != groups["regroup-link"]["id"]
    assert items["tail-a"]["evidence"]["retained_body_tail_mcids"] == [2]
    assert items["tail-b"]["evidence"]["retained_body_tail_mcids"] == [9]
    assert items["tail-a"]["context_sha256"] != items["tail-b"]["context_sha256"]
    group = groups["tail-a"]
    approved = ws.approve_group(fresh, group["id"], ["tail-a"], group["membership_digest"],
                                "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    statuses = {item["id"]: item["status"] for item in approved["manual_items"]}
    assert statuses["tail-a"] == "approved" and statuses["tail-b"] == statuses["tail-longer"] == "pending"


def test_adopted_ai_origin_is_portable_allowlisted_and_bound_by_explicit_approval(sample, tmp_path):
    envelope = _envelope(sample)
    draft = envelope["suggestions"][0]
    draft["request_context_sha256"] = "c" * 64
    draft["provenance"].update(prompt_version="test-prompt-1", request_sha256="d" * 64, cache_key="e" * 64,
                                raw_prompt="must not be exported", authorization="secret must not be exported")
    staged = ws.merge_ai_drafts(sample["state"], envelope, 0)
    suggestion_id = staged["suggestions"][0]["suggestion_id"]
    adopted = ws.accept_suggestion(sample["state"], suggestion_id, staged["revision"])
    decision = adopted["decisions"][0]
    origin = decision["ai_origin"]
    assert decision["status"] == "pending" and "approval_sha256" not in decision
    assert origin["schema_version"] == "phase2-ai-origin-1" and origin["suggestion_id"] == suggestion_id
    assert origin["provider"] == "local-openai-compatible" and origin["model"] == "synthetic-stub"
    assert origin["prompt_version"] == "test-prompt-1" and origin["request_context_sha256"] == "c" * 64
    assert origin["cache_key"] == "e" * 64
    assert origin["draft_value_sha256"] == hashlib.sha256(draft["value"].encode("utf-8")).hexdigest()
    assert "raw_prompt" not in origin["provenance"] and "authorization" not in origin["provenance"]
    assert "endpoint" not in origin["provenance"]
    approved = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", adopted["revision"])
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", approved["revision"])
    item = load_sidecar(exported["sidecar_path"])["decisions"][0]
    assert item["ai_origin"] == origin and item["approval_sha256"] == approval_digest(item)
    changed = copy.deepcopy(item)
    changed["ai_origin"]["model"] = "a different model"
    assert changed["approval_sha256"] != approval_digest(changed)
    assert ws.load_workspace(sample["state"])["suggestions"][0]["value"] == draft["value"]


def test_human_post_edit_retains_ai_origin_and_records_modification_without_preserving_approval(sample):
    staged = ws.merge_ai_drafts(sample["state"], _envelope(sample), 0)
    suggestion_id = staged["suggestions"][0]["suggestion_id"]
    adopted = ws.accept_suggestion(sample["state"], suggestion_id, staged["revision"])
    approved = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", adopted["revision"])
    changed = ws.edit_decision(sample["state"], "metadata:title", "Human correction to the AI draft", approved["revision"])
    item = changed["decisions"][0]
    assert item["status"] == "pending" and "approval_sha256" not in item
    assert item["ai_origin"]["suggestion_id"] == suggestion_id
    assert item["ai_origin"]["human_modified_after_adoption"] is True
    assert item["ai_origin"]["current_value_differs_from_draft"] is True
    assert item["ai_origin"]["current_value_sha256"] == hashlib.sha256(item["value"].encode("utf-8")).hexdigest()
    assert item["ai_origin"]["draft_value_sha256"] != item["ai_origin"]["current_value_sha256"]


def _publish_report(bundle, report):
    write_sidecar(report, bundle / "report.json")
    write_sidecar(report["manual_review"], bundle / "review.json")
    files = {path.name: file_sha256(path) for path in bundle.iterdir() if path.is_file() and path.name != "manifest.json"}
    write_sidecar({"schema_version": "phase1-bundle-1", "complete": True,
                   "run_fingerprint": report["run_fingerprint"], "files": files}, bundle / "manifest.json")
    assert verify_bundle(bundle)


def _automatic_sample(tmp_path, modify=None):
    bundle, source, prepared, output, report = _make_bundle(tmp_path)
    report["gate1"]["counts"]["passedChecks"] = 100
    report["gate1"]["assertion_detail_coverage"] = {"status": "complete"}
    report["gate2"]["checks"] = [{"id": identifier, "status": "pass", "blocking": True}
        for identifier in ("content-linkage", "content-coverage", "link-structure", "unsupported-features")]
    report["fidelity"].update(before_sha256=file_sha256(source), pages=[{"page": page, "status": "pass"} for page in (1, 2)])
    report["processors"] = [{"name": "preserve-painting", "status": "pass", "supported": True,
        "allow_tag_regrouping": True, "independent_validation_required": True, "all_page_fidelity_required": True,
        "changes": {"pages_source_checked": 2},
        "semantic_review_required": [json.loads(item["detail"]) for item in report["manual_review"]["items"]
                                     if item.get("category") == "tag-regrouping"]}]
    if modify:
        modify(report)
    _publish_report(bundle, report)
    state = tmp_path / "reviews" / "workspace.json"
    ws.create_workspace(bundle, state)
    return {"bundle": bundle, "source": source, "prepared": prepared, "output": output, "report": report, "state": state}


def test_automatic_triage_retains_all_required_occurrences_and_no_human_approvals(tmp_path):
    sample = _automatic_sample(tmp_path)
    before = sample["state"].read_bytes()
    bundle_hashes = {path.name: file_sha256(path) for path in sample["bundle"].iterdir()}
    plan = ws.plan_automatic_review(sample["state"])
    assert sample["state"].read_bytes() == before
    assert set(plan["eligible_ids"]) == {"regroup-a", "regroup-b", "regroup-exception", "regroup-link"}
    view = ws.commit_automatic_review(sample["state"], plan, 0)
    assert view["counts"]["manual_pending"] == view["counts"]["manual_total"] == 6
    assert view["counts"]["automated_count"] == 4 and view["counts"]["manual_pending_actionable"] == 2
    assert view["counts"]["manual_approved"] == 0 and view["verification"] == "not-verified"
    assert all(item["status"] == "pending" and item["required"] is True for item in view["manual_items"])
    assert sum(item["automatic_handled"] for item in view["manual_items"]) == 4
    assert {path.name: file_sha256(path) for path in sample["bundle"].iterdir()} == bundle_hashes
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", view["revision"])
    review = json.loads(Path(exported["review_path"]).read_text())
    assert not review["complete"] and not exported["ledger_eligible"]
    assert review["items"] == sample["report"]["manual_review"]["items"]
    records = ws.load_workspace(sample["state"])["automatic_review_records"]
    assert len(records) == 4 and all(record["author"] == "automation" and record["human_approved"] is False for record in records)
    assert not any("reviewer" in record or "reviewed_at" in record for record in records)
    automatic = json.loads(Path(exported["automatic_review_path"]).read_text())
    assert automatic["records"] == records and automatic["human_approved"] is False
    assert set(automatic["active_item_ids"]) == set(plan["eligible_ids"])
    assert automatic["required_human_verification_reviews_unchanged"] is True
    assert automatic["bindings"] == ws.load_workspace(sample["state"])["bindings"]
    assert file_sha256(exported["automatic_review_path"]) == exported["files"]["automatic-review.json"]


@pytest.mark.parametrize("defect", ["validator-string", "validator-bool-count", "validator-coverage", "supplemental", "fidelity", "missing-page", "preservation", "processor-occurrence"])
def test_automatic_triage_refuses_incomplete_or_non_strict_evidence(tmp_path, defect):
    def change(report):
        if defect == "validator-string":
            report["gate1"]["is_compliant"] = "true"
        elif defect == "validator-bool-count":
            report["gate1"]["counts"]["failedChecks"] = False
        elif defect == "validator-coverage":
            report["gate1"]["assertion_detail_coverage"]["status"] = "partial"
        elif defect == "supplemental":
            report["gate2"]["checks"][0]["status"] = "not-tested"
        elif defect == "fidelity":
            report["fidelity"]["status"] = "fail"
        elif defect == "missing-page":
            report["fidelity"]["pages"].pop()
        elif defect == "preservation":
            report["processors"][0]["supported"] = False
        else:
            report["processors"][0]["semantic_review_required"] = []
    sample = _automatic_sample(tmp_path, change)
    plan = ws.plan_automatic_review(sample["state"])
    assert not plan["eligible_ids"] and len(plan["ineligible"]) == 6
    view = ws.commit_automatic_review(sample["state"], plan, 0)
    assert view["counts"]["automated_count"] == 0 and view["counts"]["manual_pending_actionable"] == 6


@pytest.mark.parametrize("defect", ["unknown-kind", "bool-mcid", "overlap", "bad-tail", "missing-fingerprint", "form-context"])
def test_automatic_triage_keeps_unrecognized_occurrence_context_actionable(tmp_path, defect):
    def change(report):
        item = report["manual_review"]["items"][0]
        detail = json.loads(item["detail"])
        if defect == "unknown-kind":
            detail["kind"] = "guess-list-meaning"
        elif defect == "bool-mcid":
            detail["removed_mcids"] = [True]
        elif defect == "overlap":
            detail["removed_mcids"] = [detail["retained_mcid"]]
        elif defect == "bad-tail":
            detail["kind"] = "single-target-list-link-expansion-preserving-tail"
            detail["retained_body_tail_mcids"] = []
        elif defect == "missing-fingerprint":
            detail.pop("source_text_bytes_sha256")
        else:
            detail["stream"] = "form:10:0"
        item["detail"] = json.dumps(detail)
        report["processors"][0]["semantic_review_required"][0] = copy.deepcopy(detail)
    sample = _automatic_sample(tmp_path, change)
    plan = ws.plan_automatic_review(sample["state"])
    assert "regroup-a" not in plan["eligible_ids"] and len(plan["eligible_ids"]) == 3
    view = ws.commit_automatic_review(sample["state"], plan, 0)
    assert not next(item for item in view["manual_items"] if item["id"] == "regroup-a")["automatic_handled"]


def test_automatic_triage_never_sweeps_human_choices_or_confirmed_blockers(tmp_path):
    sample = _automatic_sample(tmp_path)
    view = ws.review_item(sample["state"], "regroup-a", "blocked", "Synthetic Test Reviewer", "2026-10-16", 0, "Meaning is wrong")
    view = ws.review_item(sample["state"], "regroup-b", "pending", "Synthetic Test Reviewer", "2026-10-16", view["revision"], "I will review this individually")
    plan = ws.plan_automatic_review(sample["state"])
    view = ws.commit_automatic_review(sample["state"], plan, view["revision"])
    items = {item["id"]: item for item in view["manual_items"]}
    assert not items["regroup-a"]["automatic_handled"] and not items["regroup-b"]["automatic_handled"]
    assert items["regroup-a"]["status"] == "blocked" and view["status"] == "needs-manual"
    assert view["counts"]["automated_count"] == 2 and view["counts"]["manual_blocked"] == 1


@pytest.mark.parametrize("changed", ["source", "prepared", "output"])
def test_changed_bound_pdf_invalidates_automatic_dispositions(tmp_path, changed):
    sample = _automatic_sample(tmp_path)
    view = ws.commit_automatic_review(sample["state"], ws.plan_automatic_review(sample["state"]), 0)
    assert view["counts"]["automated_count"] == 4
    original = sample[changed].read_bytes()
    sample[changed].write_bytes(original + b"\n% changed after automatic handling\n")
    stale = ws.get_view(sample["state"])
    assert stale["stale"] and stale["counts"]["automated_count"] == 0
    sample[changed].write_bytes(original)
    assert ws.get_view(sample["state"])["counts"]["automated_count"] == 0


def test_automatic_plan_is_exact_revision_and_membership_bound(tmp_path):
    sample = _automatic_sample(tmp_path)
    plan = ws.plan_automatic_review(sample["state"])
    forged = copy.deepcopy(plan)
    forged["eligible_ids"].append("reading-order")
    with pytest.raises(ws.RevisionConflict):
        ws.commit_automatic_review(sample["state"], forged, 0)
    ws.review_item(sample["state"], "reading-order", "pending", "Synthetic Test Reviewer", "2026-10-16", 0)
    with pytest.raises(ws.RevisionConflict):
        ws.commit_automatic_review(sample["state"], plan, 0)


def test_later_human_review_and_pdf_decision_edits_disable_automatic_dispositions(tmp_path):
    sample = _automatic_sample(tmp_path)
    view = ws.commit_automatic_review(sample["state"], ws.plan_automatic_review(sample["state"]), 0)
    view = ws.review_item(sample["state"], "regroup-a", "pending", "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    assert view["counts"]["automated_count"] == 3 and view["counts"]["manual_pending_actionable"] == 3
    current = view["decisions"][0]["value"]
    view = ws.edit_decision(sample["state"], "metadata:title", "A different title", view["revision"])
    assert view["counts"]["automated_count"] == 0 and view["unapplied_decisions"]
    view = ws.edit_decision(sample["state"], "metadata:title", current, view["revision"])
    assert not view["unapplied_decisions"] and view["counts"]["automated_count"] == 0


def _automatic_authorization(sample, identifiers=None, authorization_id="synthetic-auto-run"):
    from pdf_remediator.sidecar import make_automatic_authorization
    sidecar = ws.load_workspace(sample["state"])["sidecar"]
    return make_automatic_authorization(sidecar["source_sha256"], sidecar["document_sha256"], "2026-10-16",
        authorization_id, decision_ids=["metadata:title"] if identifiers is None else identifiers)


def test_automatic_suggestion_acceptance_retains_origin_without_human_authority(sample, tmp_path):
    from pdf_remediator.sidecar import automatic_acceptance_valid
    staged = ws.merge_ai_drafts(sample["state"], _envelope(sample), 0)
    identifier = staged["suggestions"][0]["suggestion_id"]
    authorization = _automatic_authorization(sample)
    view = ws.apply_automatic_suggestions(sample["state"], authorization, staged["revision"], suggestion_ids=[identifier])
    item = view["decisions"][0]
    assert item["status"] == "auto-accepted" and item["human_touched"] is False
    assert view["counts"]["decision_auto_accepted"] == 1 and view["counts"]["decision_approved"] == 0
    assert item["ai_origin"]["suggestion_id"] == identifier and item["ai_origin"]["model"] == "synthetic-stub"
    assert not any(key in item for key in ("approved_by", "approved_at", "approval_sha256"))
    assert view["unapplied_decisions"] == ["metadata:title"] and view["verification"] == "not-verified"
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", view["revision"])
    portable = load_sidecar(exported["sidecar_path"])["decisions"][0]
    assert automatic_acceptance_valid(portable, authorization) and portable["ai_origin"] == item["ai_origin"]
    assert exported["requires_reprocessing"] and not exported["ledger_eligible"]


@pytest.mark.parametrize("selection", [None, []])
def test_auto_mode_does_not_adopt_old_drafts_without_exact_current_request_selection(sample, selection):
    staged = ws.merge_ai_drafts(sample["state"], _envelope(sample), 0)
    original = staged["decisions"][0]["value"]
    view = ws.apply_automatic_suggestions(sample["state"], _automatic_authorization(sample), staged["revision"], suggestion_ids=selection)
    assert view["decisions"][0]["value"] == original and view["decisions"][0]["status"] == "pending"
    assert view["suggestions"][0]["status"] == "draft"


def test_automatic_mode_uses_only_selected_model_draft_even_when_another_is_newer(sample):
    first = ws.merge_ai_drafts(sample["state"], _envelope(sample, value="Selected model draft"), 0)
    first_id = first["suggestions"][0]["suggestion_id"]
    newer = _envelope(sample, value="Other model draft")
    newer["suggestions"][0]["provenance"]["model"] = "another-model"
    second = ws.merge_ai_drafts(sample["state"], newer, first["revision"])
    view = ws.apply_automatic_suggestions(sample["state"], _automatic_authorization(sample), second["revision"], suggestion_ids=[first_id])
    assert view["decisions"][0]["value"] == "Selected model draft"
    assert view["decisions"][0]["ai_origin"]["model"] == "synthetic-stub"
    assert view["suggestions"][1]["status"] == "draft"


@pytest.mark.parametrize("protection", ["edited", "approved", "same-value-touch"])
def test_automatic_mode_preserves_human_choices_after_draft_generation(sample, protection):
    staged = ws.merge_ai_drafts(sample["state"], _envelope(sample), 0)
    suggestion_id = staged["suggestions"][0]["suggestion_id"]
    if protection == "approved":
        view = ws.approve_decision(sample["state"], "metadata:title", "Synthetic Test Reviewer", "2026-10-16", staged["revision"])
    else:
        value = "A person supplied this title" if protection == "edited" else staged["decisions"][0]["value"]
        view = ws.edit_decision(sample["state"], "metadata:title", value, staged["revision"])
    before = copy.deepcopy(view["decisions"][0])
    view = ws.apply_automatic_suggestions(sample["state"], _automatic_authorization(sample), view["revision"], suggestion_ids=[suggestion_id])
    assert view["decisions"][0] == before and not view["counts"]["decision_auto_accepted"]
    assert view["history"][-1]["skipped"] == [{"id": "metadata:title", "reason": "existing-choice-protected"}]


def test_automatic_acceptance_rebinds_same_value_to_new_explicit_run_without_adopting_old_drafts(sample):
    from pdf_remediator.sidecar import automatic_acceptance_valid
    staged = ws.merge_ai_drafts(sample["state"], _envelope(sample), 0)
    first_auth = _automatic_authorization(sample, authorization_id="first-run")
    first = ws.apply_automatic_suggestions(sample["state"], first_auth, staged["revision"], suggestion_ids=[staged["suggestions"][0]["suggestion_id"]])
    new_auth = _automatic_authorization(sample, authorization_id="second-run")
    repeated = ws.apply_automatic_suggestions(sample["state"], new_auth, first["revision"], suggestion_ids=[])
    a, b = first["decisions"][0], repeated["decisions"][0]
    assert a["value"] == b["value"] and a["current"] == b["current"] and a["ai_origin"] == b["ai_origin"]
    state_item = ws.load_workspace(sample["state"])["sidecar"]["decisions"][0]
    assert automatic_acceptance_valid(state_item, new_auth) and not automatic_acceptance_valid(state_item, first_auth)
    assert repeated["history"][-1]["rebound_ids"] == ["metadata:title"]
    assert not repeated["history"][-1]["adopted_ids"] and not repeated["counts"]["decision_approved"]


def test_new_import_recognizes_valid_automatically_applied_values_as_baseline(sample, tmp_path):
    from pdf_remediator.sidecar import apply_decisions
    staged = ws.merge_ai_drafts(sample["state"], _envelope(sample), 0)
    authorization = _automatic_authorization(sample)
    accepted = ws.apply_automatic_suggestions(sample["state"], authorization, staged["revision"], suggestion_ids=[staged["suggestions"][0]["suggestion_id"]])
    portable = copy.deepcopy(ws.load_workspace(sample["state"])["sidecar"])
    new_root = tmp_path / "new-run"
    new_root.mkdir()
    bundle, source, prepared, output, report = _make_bundle(new_root, published=False)
    assert file_sha256(prepared) == portable["document_sha256"] and file_sha256(source) == portable["source_sha256"]
    apply_decisions(prepared, output, portable, file_sha256(source), automatic_authorization=authorization)
    with pikepdf.open(output) as pdf:
        assert str(pdf.docinfo.Title) == accepted["decisions"][0]["value"]
    report["status"] = "candidate"
    report["output"] = {"path": str(output), "sha256": file_sha256(output), "review_only": False}
    report["manual_review"]["artifact_sha256"] = file_sha256(output)
    report["gate1"]["input_sha256"] = report["fidelity"]["after_sha256"] = file_sha256(output)
    write_sidecar(portable, bundle / "decisions.json")
    _publish_report(bundle, report)
    new_state = new_root / "review-state.json"
    ws.create_workspace(bundle, new_state)
    view = ws.get_view(new_state)
    assert not view["unapplied_decisions"] and view["counts"]["decision_auto_accepted"] == 1
    assert view["decisions"][0]["human_touched"] is False and view["counts"]["manual_approved"] == 0
    new_auth = _automatic_authorization({"state": new_state}, authorization_id="new-run")
    rebound = ws.apply_automatic_suggestions(new_state, new_auth, view["revision"], suggestion_ids=[])
    assert not rebound["unapplied_decisions"] and rebound["history"][-1]["rebound_ids"] == ["metadata:title"]


def test_human_correction_after_automatic_acceptance_clears_authority_and_protects_value(sample):
    staged = ws.merge_ai_drafts(sample["state"], _envelope(sample), 0)
    view = ws.apply_automatic_suggestions(sample["state"], _automatic_authorization(sample), staged["revision"], suggestion_ids=[staged["suggestions"][0]["suggestion_id"]])
    changed = ws.edit_decision(sample["state"], "metadata:title", "A corrected human title", view["revision"])
    item = changed["decisions"][0]
    assert item["status"] == "pending" and item["human_touched"] is True
    assert "automatic_application" not in item and "automatic_acceptance_sha256" not in item
    assert item["ai_origin"]["human_modified_after_adoption"] is True


def test_late_artifact_change_cannot_publish_active_automatic_dispositions(tmp_path, monkeypatch):
    sample = _automatic_sample(tmp_path)
    plan = ws.plan_automatic_review(sample["state"])
    original = ws._record_event
    def mutate_after_action(*args, **kwargs):
        original(*args, **kwargs)
        if args[1] == "automatic-mechanical-review-triage":
            sample["output"].write_bytes(sample["output"].read_bytes() + b"\n% late mutation\n")
    monkeypatch.setattr(ws, "_record_event", mutate_after_action)
    with pytest.raises(ws.StaleWorkspace):
        ws.commit_automatic_review(sample["state"], plan, 0)
    view = ws.get_view(sample["state"])
    assert view["stale"] and view["counts"]["automated_count"] == 0


def test_623_automatic_occurrences_export_individually_without_reducing_ledger_requirements(tmp_path):
    def scale_inventory(report):
        repairs = [_regroup(f"regroup-{index:04}", index % 2 + 1, [index + 1]) for index in range(623)]
        semantics = [{"id": "semantic-" + str(index), "category": "reading-order", "required": True,
                      "status": "pending", "detail": "Synthetic distinct semantic assessment " + str(index)} for index in range(7)]
        report["manual_review"]["items"] = repairs + semantics
        report["gate2"]["manual_queue"] = copy.deepcopy(semantics)
        report["processors"][0]["semantic_review_required"] = [json.loads(item["detail"]) for item in repairs]
    sample = _automatic_sample(tmp_path, scale_inventory)
    plan = ws.plan_automatic_review(sample["state"])
    view = ws.commit_automatic_review(sample["state"], plan, 0)
    assert view["counts"]["automated_count"] == 623 and view["counts"]["manual_pending_actionable"] == 7
    exported = ws.export_workspace(sample["state"], tmp_path / "exports", view["revision"])
    automatic = json.loads(Path(exported["automatic_review_path"]).read_text())
    review = json.loads(Path(exported["review_path"]).read_text())
    assert len(automatic["records"]) == len(set(record["item_id"] for record in automatic["records"])) == 623
    assert set(automatic["active_item_ids"]) == set(plan["eligible_ids"])
    assert len(review["items"]) == 630 and all(item["required"] and item["status"] == "pending" for item in review["items"])
    assert not review["complete"] and not exported["ledger_eligible"]
    with pytest.raises(ValueError, match="Required human review remains"):
        _eligible(sample["report"], file_sha256(sample["output"]))
    assert exported["files"]["automatic-review.json"] == file_sha256(exported["automatic_review_path"])


def test_explicit_pending_occurrence_preference_survives_new_bundle_without_copying_approvals(tmp_path):
    old_root, new_root = tmp_path / "prior", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old, new = _automatic_sample(old_root), _automatic_sample(new_root)
    view = ws.review_item(old["state"], "regroup-a", "pending", "Synthetic Test Reviewer", "2026-10-16", 0, "Keep this for my individual review")
    ws.review_item(old["state"], "reading-order", "approved", "Synthetic Test Reviewer", "2026-10-16", view["revision"])
    transferred = ws.preserve_manual_preferences(old["state"], new["state"], 0)
    assert transferred["counts"]["manual_approved"] == 0 and all(item["status"] == "pending" for item in transferred["manual_items"])
    item = next(item for item in transferred["manual_items"] if item["id"] == "regroup-a")
    assert item["human_touched"] and "reviewer" not in item and "notes" not in item
    plan = ws.plan_automatic_review(new["state"])
    assert "regroup-a" not in plan["eligible_ids"]
    view = ws.commit_automatic_review(new["state"], plan, transferred["revision"])
    assert view["counts"]["manual_total"] == view["counts"]["manual_pending"] == 6
    assert view["counts"]["automated_count"] == 3 and view["counts"]["manual_pending_actionable"] == 3
    assert view["history"][-2]["copied_ids"] == ["regroup-a"] and view["history"][-2]["human_approvals_copied"] == 0


def test_individual_pending_preference_is_not_transferred_to_changed_context(tmp_path):
    old_root, new_root = tmp_path / "prior", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old = _automatic_sample(old_root)
    ws.review_item(old["state"], "regroup-a", "pending", "Synthetic Test Reviewer", "2026-10-16", 0)
    def changed(report):
        item = report["manual_review"]["items"][0]
        detail = json.loads(item["detail"])
        detail["removed_mcids"] = [99]
        item["detail"] = json.dumps(detail)
        report["processors"][0]["semantic_review_required"][0] = detail
    new = _automatic_sample(new_root, changed)
    view = ws.preserve_manual_preferences(old["state"], new["state"], 0)
    assert not next(item for item in view["manual_items"] if item["id"] == "regroup-a")["human_touched"]
    assert view["history"][-1]["skipped"] == [{"id": "regroup-a", "reason": "occurrence-context-changed"}]


def test_preference_transfer_refuses_changed_original_source_and_revision_conflicts(tmp_path):
    old_root, new_root = tmp_path / "prior", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old, new = _automatic_sample(old_root), _automatic_sample(new_root)
    ws.review_item(old["state"], "regroup-a", "pending", "Synthetic Test Reviewer", "2026-10-16", 0)
    with pytest.raises(ws.RevisionConflict):
        ws.preserve_manual_preferences(old["state"], new["state"], 1)
    old["source"].write_bytes(old["source"].read_bytes() + b"\n% source changed\n")
    with pytest.raises(ws.StaleWorkspace):
        ws.preserve_manual_preferences(old["state"], new["state"], 0)
    assert ws.get_view(new["state"])["revision"] == 0


def test_preference_transfer_refuses_a_different_valid_source_fingerprint(tmp_path):
    old_root, new_root = tmp_path / "prior", tmp_path / "new"
    old_root.mkdir()
    new_root.mkdir()
    old = _automatic_sample(old_root)
    ws.review_item(old["state"], "regroup-a", "pending", "Synthetic Test Reviewer", "2026-10-16", 0)
    def another_valid_source(report):
        source, prepared, output = (Path(report[key]["path"]) for key in ("input", "decision_source", "output"))
        source.write_bytes(source.read_bytes() + b"\n% a separately fingerprinted synthetic source\n")
        shutil.copyfile(source, prepared)
        shutil.copyfile(source, output)
        digest = file_sha256(source)
        for key in ("input", "decision_source", "output"):
            report[key]["sha256"] = digest
        report["decision_source"]["source_sha256"] = digest
        report["manual_review"]["artifact_sha256"] = digest
        report["gate1"]["input_sha256"] = report["fidelity"]["before_sha256"] = report["fidelity"]["after_sha256"] = digest
        write_sidecar(collect_decisions(prepared, digest), output.parent / "decisions.json")
    new = _automatic_sample(new_root, another_valid_source)
    with pytest.raises(ws.WorkspaceError, match="different original source"):
        ws.preserve_manual_preferences(old["state"], new["state"], 0)
    assert ws.get_view(new["state"])["revision"] == 0


# --- speed and robustness of opening a review ----------------------------------------------------------------

def test_the_decision_re_read_runs_once_per_unchanged_review_and_never_hides_a_change(sample, monkeypatch):
    ws._INVENTORY_MATCHED.clear()
    real, calls = ws.collect_decisions, []

    def counting(path, *args, **kwargs):
        calls.append(Path(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(ws, "collect_decisions", counting)
    first = ws.get_view(sample["state"])
    assert not first["stale"] and len(calls) == 1 and calls[0] == sample["prepared"].resolve()
    for _ in range(3):
        assert not ws.get_view(sample["state"])["stale"]
    assert len(calls) == 1, "An unchanged review must not be analysed again on every click."
    assert ws._INVENTORY_MATCHED and all(re.fullmatch('[0-9a-f]{64}', token) for token in ws._INVENTORY_MATCHED)
    # A changed prepared file is still caught by its fingerprint on every load, cache or not.
    with sample["prepared"].open("ab") as stream:
        stream.write(b"\n% changed after review\n")
    assert ws.get_view(sample["state"])["stale"]
    reasons = ws.load_workspace(sample["state"], refresh=False)["stale_reasons"]
    assert any("prepared PDF fingerprint changed" in reason for reason in reasons)


def test_new_program_code_asks_again_and_a_changed_answer_still_invalidates(sample, monkeypatch):
    ws._INVENTORY_MATCHED.clear()
    assert not ws.get_view(sample["state"])["stale"]
    ws._INVENTORY_MATCHED.clear()
    monkeypatch.setattr(ws, "_CODE_FINGERPRINT", "an updated program whose analysis differs")

    def different(path, *args, **kwargs):
        result = collect_decisions(path, *args, **kwargs)
        result["decisions"] = result.get("decisions", []) + [{"id": "extra", "kind": "title", "binding": {}, "context_sha256": "x",
                                                              "current": "", "element": None, "page": None, "structure_path": None, "references": []}]
        return result

    monkeypatch.setattr(ws, "collect_decisions", different)
    assert ws.get_view(sample["state"])["stale"]
    assert "Prepared PDF decision occurrence context changed" in ws.load_workspace(sample["state"], refresh=False)["stale_reasons"]


def _dead_process_id():
    import subprocess
    import sys
    return int(subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, check=True).stdout)


def test_a_lock_left_by_a_vanished_process_is_cleared_and_every_other_lock_is_respected(sample):
    import os
    lock = sample["state"].with_name(sample["state"].name + ".lock")
    lock.write_text("pid=%d\n" % _dead_process_id(), encoding="ascii")
    assert not ws.get_view(sample["state"])["stale"] and not lock.exists(), "A dead owner must not block the review forever."
    lock.write_text("pid=%d\n" % os.getpid(), encoding="ascii")
    with pytest.raises(ws.RevisionConflict):
        ws.get_view(sample["state"])
    assert lock.read_text(encoding="ascii") == "pid=%d\n" % os.getpid(), "A live owner's lock is untouched."
    lock.write_text("another writer", encoding="utf-8")
    with pytest.raises(ws.RevisionConflict):
        ws.get_view(sample["state"])
    old = lock.stat().st_mtime - 2 * ws._LOCK_MAXIMUM_AGE_SECONDS
    os.utime(lock, (old, old))
    assert not ws.get_view(sample["state"])["stale"] and not lock.exists(), "A lock far older than any operation is abandoned."


def test_a_held_lock_names_its_owner_and_is_removed_afterwards(sample):
    import os
    lock = sample["state"].with_name(sample["state"].name + ".lock")
    with ws._locked(sample["state"]):
        assert lock.read_text(encoding="ascii") == "pid=%d\n" % os.getpid()
        with pytest.raises(ws.RevisionConflict):
            with ws._locked(sample["state"]):
                pass
    assert not lock.exists()


def test_a_match_is_kept_beside_the_review_for_later_runs_of_exactly_the_same_code(sample, monkeypatch):
    saved = sample["state"].with_name(sample["state"].name + ".inventory-ok")
    ws._INVENTORY_MATCHED.clear()
    real, calls = ws.collect_decisions, []
    monkeypatch.setattr(ws, "collect_decisions", lambda path, *a, **k: (calls.append(path), real(path, *a, **k))[1])
    assert not ws.get_view(sample["state"])["stale"] and len(calls) == 1
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["code"] == ws._code_fingerprint() and len(data["matches"]) == 1
    # A new program run starts with an empty memory but finds the saved match.
    ws._INVENTORY_MATCHED.clear()
    assert not ws.get_view(sample["state"])["stale"] and len(calls) == 1
    # Different code means the saved match is not trusted and the PDF is analysed again.
    ws._INVENTORY_MATCHED.clear()
    monkeypatch.setattr(ws, "_CODE_FINGERPRINT", "a different version of the program")
    assert not ws.get_view(sample["state"])["stale"] and len(calls) == 2
    assert json.loads(saved.read_text(encoding="utf-8"))["code"] == "a different version of the program"


def test_an_unreadable_or_foreign_saved_match_is_ignored_and_never_blocks_a_review(sample, monkeypatch):
    saved = sample["state"].with_name(sample["state"].name + ".inventory-ok")
    for damage in ("not json at all", json.dumps({"code": ws._code_fingerprint(), "matches": "x"}), json.dumps(["list"]), ""):
        ws._INVENTORY_MATCHED.clear()
        saved.write_text(damage, encoding="utf-8")
        assert not ws.get_view(sample["state"])["stale"]
    # A match saved for other decisions does not vouch for these ones.
    ws._INVENTORY_MATCHED.clear()
    saved.write_text(json.dumps({"code": ws._code_fingerprint(), "matches": ["0" * 64]}), encoding="utf-8")
    real, calls = ws.collect_decisions, []
    monkeypatch.setattr(ws, "collect_decisions", lambda path, *a, **k: (calls.append(path), real(path, *a, **k))[1])
    assert not ws.get_view(sample["state"])["stale"] and len(calls) == 1


def test_a_changed_prepared_file_is_caught_even_when_a_match_is_saved(sample):
    ws._INVENTORY_MATCHED.clear()
    assert not ws.get_view(sample["state"])["stale"]
    assert sample["state"].with_name(sample["state"].name + ".inventory-ok").is_file()
    ws._INVENTORY_MATCHED.clear()
    with sample["prepared"].open("ab") as stream:
        stream.write(b"\n% changed after the match was saved\n")
    assert ws.get_view(sample["state"])["stale"]
    assert any("prepared PDF fingerprint changed" in reason for reason in ws.load_workspace(sample["state"], refresh=False)["stale_reasons"])
