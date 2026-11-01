"""Auto-fix integration: real PDF pipeline, explicit named expensive stubs.

The isolated-worker test double calls the real pipeline in this process. Only
the external validator and optional local model are replaced. Inspection,
decisions, PDF writes, pixel comparisons, workspaces, and manifests are real.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import threading

import pikepdf
import pytest

from pdf_remediator import assistance, ledger, pipeline, web, workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import automatic_acceptance_valid
from test_assistance import sidecar as read_fixture_sidecar
from test_pipeline import fast_validator, input_pdf, tagged_control, generated_chapter
from test_web import application, imported, wait_job


@pytest.fixture
def inline_worker(monkeypatch):
    worker = {"calls": [], "before": None, "after": None}

    def named_inline_worker_calling_real_pipeline(source, destination, config, cancel, progress, **kwargs):
        call = {"source": Path(source), "destination": Path(destination), "config": copy.deepcopy(config),
                "kwargs": copy.deepcopy(kwargs)}
        worker["calls"].append(call)
        if worker["before"]:
            worker["before"](call)
        result = pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, **kwargs)
        call["report"] = result
        if worker["after"]:
            worker["after"](call, result)
        return result

    monkeypatch.setattr(web, "process_isolated", named_inline_worker_calling_real_pipeline)
    return worker


@pytest.fixture
def local_model(monkeypatch):
    model = {"calls": [], "mode": "draft", "after": None}

    def named_local_model_envelope_test_stub(bundle_path, endpoint, name, decision_ids=None, **kwargs):
        model["calls"].append({"bundle": Path(bundle_path), "ids": list(decision_ids or []), "model": name})
        if model["mode"] == "error":
            return {"status": "error", "error": "Explicit model-fixture outage; no model service was used."}
        if model["mode"] == "raise":
            raise assistance.AssistanceError("Explicit model-fixture transport failure")
        if model["mode"] == "cancelled":
            return {"status": "cancelled"}
        context = assistance.build_context(bundle_path, decision_ids)
        inventory = read_fixture_sidecar(Path(bundle_path))
        by_id = {item["id"]: item for item in inventory["decisions"]}
        cache_key = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
        provenance = {"provider": "local-openai-compatible", "endpoint": endpoint, "model": name,
                      "schema_version": "phase2-assistance-1", "context_version": "occurrence-context-1",
                      "prompt_version": "explicit-integration-fixture-1", "cache_key": cache_key,
                      "request_sha256": "1" * 64, "response_sha256": "2" * 64,
                      "model_metadata_sha256": "3" * 64, "generated_at": "2026-10-16T16:00:00Z"}
        suggestions = []
        for item in context["items"]:
            value = ("Automatic course reading title" if item["kind"] == "title" else
                     "The orange circle and blue square represent two archive bins in this caption context."
                     if "archive" in item.get("caption_context", "").lower() else
                     "The orange circle and blue square represent two garden plots in this caption context.")
            suggestions.append({"id": item["id"], "kind": item["kind"], "value": value, "status": "draft",
                                "binding": copy.deepcopy(item["binding"]), "context_sha256": item["context_sha256"],
                                "request_context_sha256": item["request_context_sha256"],
                                "original_value_sha256": hashlib.sha256(by_id[item["id"]]["value"].encode()).hexdigest(),
                                "provenance": copy.deepcopy(provenance)})
        envelope = {"schema_version": "phase2-assistance-1", "status": "draft",
                    "source_sha256": context["source_sha256"], "document_sha256": context["document_sha256"],
                    "suggestions": suggestions, "cache": {"key": cache_key, "hit": False},
                    "data_sent": {"provider_calls": 0, "document_requests": 0,
                                  "scope": "Explicit test envelope; no model service was invoked."}}
        assistance.validate_suggestions(inventory, envelope)
        if model["after"]:
            model["after"](envelope)
        return envelope

    monkeypatch.setattr(assistance, "suggest", named_local_model_envelope_test_stub)
    return model


@pytest.fixture
def tagged_chapter(tmp_path, generated_chapter):
    # Generated occurrence control; no historical engine output is required.
    source = generated_chapter
    target = tmp_path / "chapter.pdf"
    shutil.copyfile(source, target)
    return target


def payload(view, use_ai=False):
    return {"revision": view["revision"], "consent": True, "use_ai": use_ai,
            "ai_consent": True, "endpoint": "http://127.0.0.1:11434/v1", "model": "explicit-test-model",
            "include_images": True}


def finish(app, queued):
    return wait_job(app, queued["job_id"], seconds=12)


def result_view(app, job):
    assert job["status"] == "done", job
    return app.view(job["result"]["documents"][0]["workspace_id"])


def result_report(view):
    return json.loads((Path(view["bundle_path"]) / "report.json").read_text(encoding="utf-8"))


def assert_no_human_approval(view):
    assert view["verification"] == "not-verified"
    assert view["counts"]["manual_approved"] == 0 and view["counts"]["decision_approved"] == 0
    assert all(item["status"] == "pending" and not item.get("reviewer") for item in view["manual_items"])
    assert all(not any(key in item for key in ("approved_by", "approved_at", "approval_sha256")) for item in view["decisions"])


@pytest.mark.parametrize("bad", [{"consent": False}, {"consent": "true"}, {"consent": 1},
                                  {"revision": False}, {"use_ai": "true"},
                                  {"use_ai": True, "ai_consent": False}, {"use_ai": True, "model": ""}])
def test_auto_fix_requires_explicit_literal_authority_before_any_work(
        bad, application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    chosen = {**payload(view), **bad}
    with pytest.raises(ValueError):
        application.auto_fix(identifier, chosen)
    assert not application.jobs and not inline_worker["calls"] and not local_model["calls"]


def test_confirmed_blocker_is_protected_before_ai_or_processing(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    blocked = workspace.review_item(application.state_path(identifier), view["manual_items"][0]["id"],
                                    "blocked", "Explicit test reviewer", "2026-10-16", view["revision"], notes="Seeded defect")
    with pytest.raises(ValueError, match="blocked|problem"):
        application.auto_fix(identifier, payload(blocked, True))
    assert application.view(identifier)["counts"]["manual_blocked"] == 1
    assert not inline_worker["calls"] and not local_model["calls"]


@pytest.mark.parametrize("change", ["decision", "source", "blocker"])
def test_queued_auto_fix_rechecks_revision_and_source_before_ai(
        change, application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    release = threading.Event()
    application.submit("Test-only queue barrier", lambda cancel, progress, job: release.wait(10))
    try:
        queued = application.auto_fix(identifier, payload(view, True))
        if change == "decision":
            workspace.edit_decision(application.state_path(identifier), "metadata:title", "Human queued edit", view["revision"])
        elif change == "blocker":
            workspace.review_item(application.state_path(identifier), view["manual_items"][0]["id"], "blocked",
                                  "Explicit test reviewer", "2026-10-16", view["revision"], notes="Defect found after queuing")
        else:
            with input_pdf.open("ab") as stream:
                stream.write(b"\n% changed queued source\n")
        release.set()
        job = finish(application, queued)
        assert job["status"] == "failed" and "changed" in job["error"]
        assert not inline_worker["calls"] and not local_model["calls"]
        assert len(fast_validator) == 2
        if change == "blocker":
            assert application.view(identifier)["counts"]["manual_blocked"] == 1
    finally:
        release.set()


def test_queued_cancellation_stops_auto_fix_before_model_or_new_pdf(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    release = threading.Event()
    application.submit("Test-only queue barrier", lambda cancel, progress, job: release.wait(10))
    try:
        queued = application.auto_fix(identifier, payload(view, True))
        application.jobs[queued["job_id"]]["cancel"].set()
        release.set()
        job = finish(application, queued)
        assert job["status"] == "cancelled"
        assert not inline_worker["calls"] and not local_model["calls"]
        assert application.view(identifier)["output"]["sha256"] == view["output"]["sha256"]
        assert not list((application.root / "runs").rglob("*.pdf"))
    finally:
        release.set()


def test_mechanical_only_run_makes_fresh_bound_bundle_with_same_pdf_and_zero_approvals(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, initial = imported(application, input_pdf, tmp_path)
    source_hash, original_hash = pipeline.sha(input_pdf), before["output"]["sha256"]
    job = finish(application, application.auto_fix(identifier, payload(before)))
    after = result_view(application, job)
    report = result_report(after)
    assert after["bundle_path"] != before["bundle_path"]
    assert after["output"]["sha256"] == original_hash
    assert pipeline.sha(input_pdf) == source_hash
    assert len(inline_worker["calls"]) == 1 and len(fast_validator) == 4
    authority = inline_worker["calls"][0]["kwargs"]["automatic_authorization"]
    assert authority["decision_ids"] == [] and authority["human_reviewed"] is False
    assert report["automatic_mode"]["authorization"] == authority
    assert report["checkpoint_reused"] is True
    assert report["gate1"]["input_sha256"] == report["fidelity"]["after_sha256"] == original_hash
    assert pipeline.verify_bundle(after["bundle_path"]) and pipeline.verify_bundle(before["bundle_path"])
    assert not local_model["calls"]
    assert_no_human_approval(after)
    assert len(after["manual_items"]) == len(before["manual_items"])
    assert job["result"]["auto_fix"]["newly_changed_decisions"] == []
    with pytest.raises(ledger.LedgerError, match="human review"):
        ledger._eligible(report, original_hash)


def test_local_ai_values_apply_without_individual_review_and_repeat_without_new_ai(
        application, tagged_chapter, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, initial = imported(application, tagged_chapter, tmp_path)
    source_hash = pipeline.sha(tagged_chapter)
    assert before["status"] == "needs-manual" and before["output"]
    job = finish(application, application.auto_fix(identifier, payload(before, True)))
    after = result_view(application, job)
    report = result_report(after)
    assert after["status"] == "candidate" and len(local_model["calls"]) == 1
    selected = {item["id"] for item in before["decisions"] if item["kind"] in {"title", "figure-description"}}
    assert set(local_model["calls"][0]["ids"]) == selected and len(selected) == 3
    assert after["output"]["sha256"] != before["output"]["sha256"]
    assert pipeline.sha(tagged_chapter) == source_hash
    accepted = [item for item in after["decisions"] if item["status"] == "auto-accepted"]
    assert {item["id"] for item in accepted} == selected
    raw_accepted = [item for item in read_fixture_sidecar(Path(after["bundle_path"]))["decisions"]
                    if item["status"] == "auto-accepted"]
    assert all(automatic_acceptance_valid(item) for item in raw_accepted)
    assert all(item["automatic_application"]["human_reviewed"] is False for item in accepted)
    assert report["data_sent"]["document_api_calls"] == 0
    assert {item["decision_id"] for item in report["data_sent"]["prior_assistance"]} == selected
    assert set(job["result"]["auto_fix"]["newly_changed_decisions"]) == selected
    with pikepdf.open(after["output"]["path"]) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Automatic course reading title"
    assert_no_human_approval(after)
    with pytest.raises(ledger.LedgerError, match="human review"):
        ledger._eligible(report, after["output"]["sha256"])
    old_authority = report["automatic_mode"]["authorization"]["authorization_id"]
    new_identifier = job["result"]["documents"][0]["workspace_id"]
    repeated = finish(application, application.auto_fix(new_identifier, payload(after, True)))
    repeat_view = result_view(application, repeated)
    assert repeat_view["output"]["sha256"] == after["output"]["sha256"]
    assert len(local_model["calls"]) == 1 and len(inline_worker["calls"]) == 2
    assert result_report(repeat_view)["automatic_mode"]["authorization"]["authorization_id"] != old_authority
    assert_no_human_approval(repeat_view)


def test_pending_human_edit_is_preserved_and_not_sent_for_automatic_replacement(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, report = imported(application, input_pdf, tmp_path)
    edited = workspace.edit_decision(application.state_path(identifier), "metadata:title", "My unfinished human title", before["revision"])
    job = finish(application, application.auto_fix(identifier, payload(edited, True)))
    after = result_view(application, job)
    title = next(item for item in after["decisions"] if item["id"] == "metadata:title")
    assert title["value"] == "My unfinished human title" and title["status"] == "pending"
    assert title["human_touched"] is True and not local_model["calls"]
    assert after["output"]["sha256"] == before["output"]["sha256"]
    assert after["status"] == "needs-manual" and after["unapplied_decisions"] == ["metadata:title"]
    assert job["result"]["auto_fix"]["warnings"]
    assert_no_human_approval(after)


def test_existing_named_approval_is_retained_without_automation_claiming_new_review(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, initial = imported(application, input_pdf, tmp_path)
    approved = workspace.approve_decision(application.state_path(identifier), "metadata:title",
                                          "Existing explicit test reviewer", "2026-10-16", before["revision"])
    existing = next(item for item in approved["decisions"] if item["id"] == "metadata:title")
    job = finish(application, application.auto_fix(identifier, payload(approved, True)))
    after = result_view(application, job)
    retained = next(item for item in after["decisions"] if item["id"] == "metadata:title")
    assert retained["value"] == existing["value"] and retained["approval_sha256"] == existing["approval_sha256"]
    assert retained["approved_by"] == "Existing explicit test reviewer"
    assert after["counts"]["decision_approved"] == 1 and after["counts"]["manual_approved"] == 0
    assert job["result"]["auto_fix"]["human_approvals_granted"] == 0
    assert after["verification"] == "not-verified" and not local_model["calls"]
    assert after["output"]["sha256"] == before["output"]["sha256"]


def test_earlier_unselected_drafts_are_not_swept_into_current_automatic_authority(
        application, tagged_chapter, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, initial = imported(application, tagged_chapter, tmp_path)
    ids = [item["id"] for item in before["decisions"] if item["kind"] in {"title", "figure-description"}]
    earlier = assistance.suggest(before["bundle_path"], payload(before)["endpoint"], "explicit-test-model", decision_ids=ids)
    for item in earlier["suggestions"]:
        item["value"] = "An earlier unselected proposal for this occurrence"
    staged = workspace.merge_ai_drafts(application.state_path(identifier), earlier, before["revision"])

    def return_only_current_title(envelope):
        envelope["suggestions"] = [item for item in envelope["suggestions"] if item["kind"] == "title"]

    local_model["after"] = return_only_current_title
    job = finish(application, application.auto_fix(identifier, payload(staged, True)))
    after = result_view(application, job)
    decisions = {item["id"]: item for item in after["decisions"]}
    assert decisions["metadata:title"]["status"] == "auto-accepted"
    assert decisions["metadata:title"]["value"] == "Automatic course reading title"
    assert all(item["status"] == "pending" and item["value"] == item["current"]
               for item in decisions.values() if item["kind"] == "figure-description")
    assert job["result"]["auto_fix"]["newly_changed_decisions"] == ["metadata:title"]
    authority = result_report(after)["automatic_mode"]["authorization"]
    assert authority["decision_ids"] == ["metadata:title"]
    assert after["status"] == "needs-manual"
    assert_no_human_approval(after)


@pytest.mark.parametrize("failure", ["error", "raise"])
def test_provider_failure_leaves_pending_values_and_surfaces_warning(
        failure, application, tagged_chapter, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, initial = imported(application, tagged_chapter, tmp_path)
    local_model["mode"] = failure
    job = finish(application, application.auto_fix(identifier, payload(before, True)))
    after = result_view(application, job)
    assert job["result"]["auto_fix"]["warnings"]
    assert job["result"]["auto_fix"]["status"] == "needs-attention"
    assert job["result"]["auto_fix"]["newly_changed_decisions"] == []
    assert after["status"] == "needs-manual" and after["output"]["sha256"] == before["output"]["sha256"]
    assert all(item["status"] == "pending" for item in after["decisions"])
    assert_no_human_approval(after)


def test_unsupported_no_pdf_route_reprepares_with_new_config_then_refuses_safely(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    config = RuntimeConfig(project_root=tmp_path, document_kind="equations")
    initial = pipeline.process_file(input_pdf, tmp_path / "initial", config)
    identifier = application.import_bundle(initial["bundle_path"])
    before = application.view(identifier)
    assert before["output"] is None
    job = finish(application, application.auto_fix(identifier, payload(before, True)))
    after = result_view(application, job)
    assert after["output"] is None and after["status"] == "needs-manual"
    assert job["result"]["auto_fix"]["status"] == "needs-attention"
    assert len(inline_worker["calls"]) == 1 and not local_model["calls"]
    call = inline_worker["calls"][0]
    assert call["config"].allow_tag_regrouping is True
    assert call["config"].document_kind == "equations"
    assert "decision_bundle" not in call["kwargs"] and "automatic_authorization" not in call["kwargs"]
    assert call["kwargs"]["expected_source_sha256"] == pipeline.sha(input_pdf)
    assert not list((application.root / "runs").rglob("candidate.pdf"))
    assert not fast_validator and pipeline.verify_bundle(after["bundle_path"])


def test_source_change_during_repreparation_is_refused_before_ai_or_adoption(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    initial = pipeline.process_file(input_pdf, tmp_path / "initial", RuntimeConfig(project_root=tmp_path, document_kind="equations"))
    identifier = application.import_bundle(initial["bundle_path"])
    before = application.view(identifier)

    def change_original_after_preparation(call, result):
        with input_pdf.open("ab") as stream:
            stream.write(b"\n% original changed during preparation\n")

    inline_worker["after"] = change_original_after_preparation
    job = finish(application, application.auto_fix(identifier, payload(before, True)))
    assert job["status"] == "failed" and "initiating review changed" in job["error"]
    assert not local_model["calls"] and len(inline_worker["calls"]) == 1
    assert application.view(identifier)["stale"]


def test_human_edit_during_model_request_blocks_automatic_adoption(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, initial = imported(application, input_pdf, tmp_path)

    def human_changes_while_model_is_working(envelope):
        workspace.edit_decision(application.state_path(identifier), "metadata:title", "Concurrent human title", before["revision"])

    local_model["after"] = human_changes_while_model_is_working
    job = finish(application, application.auto_fix(identifier, payload(before, True)))
    assert job["status"] == "failed" and not inline_worker["calls"]
    current = application.view(identifier)
    assert next(item for item in current["decisions"] if item["id"] == "metadata:title")["value"] == "Concurrent human title"
    assert current["output"]["sha256"] == before["output"]["sha256"]
    assert_no_human_approval(current)


def test_human_edit_during_final_processing_preserves_edit_and_withholds_success(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model):
    identifier, before, initial = imported(application, input_pdf, tmp_path)

    def human_changes_after_real_worker(call, result):
        current = application.view(identifier)
        workspace.edit_decision(application.state_path(identifier), "metadata:title", "Latest human title", current["revision"])

    inline_worker["after"] = human_changes_after_real_worker
    job = finish(application, application.auto_fix(identifier, payload(before)))
    assert job["status"] == "failed" and "changed during automatic processing" in job["error"]
    current = application.view(identifier)
    assert next(item for item in current["decisions"] if item["id"] == "metadata:title")["value"] == "Latest human title"
    assert current["output"]["sha256"] == before["output"]["sha256"]
    assert len(inline_worker["calls"]) == 1
    assert pipeline.verify_bundle(inline_worker["calls"][0]["report"]["bundle_path"])
    assert_no_human_approval(current)


def test_dashboard_read_during_auto_fix_workspace_write_waits_and_job_completes(
        application, input_pdf, fast_validator, tmp_path, inline_worker, local_model, monkeypatch):
    """Exercise the real workspace file lock while a normal dashboard read races.

    The read is released only after the real write is attempted. An uncoordinated
    write raises WorkspaceError; application serialization lets both complete.
    """
    identifier, before, initial = imported(application, input_pdf, tmp_path)
    poll_holds_file_lock, release_poll = threading.Event(), threading.Event()
    poll_results, poll_errors, threads = [], [], []
    real_read = workspace._read_state
    real_apply = workspace.apply_automatic_suggestions

    def synchronize_real_poll_read(path):
        value = real_read(path)
        if threading.current_thread().name == "explicit-auto-fix-dashboard-race":
            poll_holds_file_lock.set()
            assert release_poll.wait(4), "Test race barrier was not released"
        return value

    def poll_current_workspace():
        try:
            poll_results.append(application.view(identifier))
        except Exception as exc:
            poll_errors.append(exc)

    def initiate_dashboard_read_at_real_write(*args, **kwargs):
        thread = threading.Thread(target=poll_current_workspace, name="explicit-auto-fix-dashboard-race")
        threads.append(thread)
        thread.start()
        # A serialized application read waits behind the in-flight write; an
        # uncoordinated read reaches the real workspace lock before this write.
        poll_holds_file_lock.wait(.5)
        try:
            return real_apply(*args, **kwargs)
        finally:
            release_poll.set()

    monkeypatch.setattr(workspace, "_read_state", synchronize_real_poll_read)
    monkeypatch.setattr(workspace, "apply_automatic_suggestions", initiate_dashboard_read_at_real_write)
    try:
        job = finish(application, application.auto_fix(identifier, payload(before)))
        after = result_view(application, job)
        assert after["status"] == "candidate"
        assert after["output"]["sha256"] == before["output"]["sha256"]
        assert_no_human_approval(after)
    finally:
        release_poll.set()
        for thread in threads:
            thread.join(timeout=4)
    assert poll_results and not poll_errors
    assert all(not thread.is_alive() for thread in threads)
