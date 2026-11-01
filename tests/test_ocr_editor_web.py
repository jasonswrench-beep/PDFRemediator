"""Application and routing tests use named worker/inventory stubs; no live server starts."""
import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest

from pdf_remediator import web, workspace as ws
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import file_sha256, write_sidecar
from test_workspace import _make_bundle
from test_ocr_editor_workspace import install_inventory_stub


def update_report(bundle, report):
    write_sidecar(report, bundle / "report.json")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["report.json"] = file_sha256(bundle / "report.json")
    write_sidecar(manifest, bundle / "manifest.json")


@pytest.fixture
def editor_app(tmp_path, monkeypatch, request):
    install_inventory_stub(monkeypatch)
    app = web.Application(tmp_path / "application", RuntimeConfig(project_root=tmp_path))
    bundle, source, prepared, output, report = _make_bundle(tmp_path)
    report["settings"] = app.config.public()
    report["settings"]["ocr_mode"], report["settings"]["ocr_profile"] = getattr(request, "param", ("textless", "standard"))
    update_report(bundle, report)
    identifier = app.import_bundle(bundle)
    captured = {}
    def capture_submit(kind, work):
        captured.update(kind=kind, work=work)
        return {"job_id": "b" * 24}
    monkeypatch.setattr(app, "submit", capture_submit)
    yield app, identifier, captured, tmp_path
    app.close()


def dispatch(app, path, payload=None):
    """Exercise actual route dispatch with framing/security represented by named stubs."""
    handler = object.__new__(web.Handler)
    handler.server = SimpleNamespace(application=app)
    handler.path = path
    handler.command = "GET" if payload is None else "POST"
    handler.headers = {}
    result = {}
    secured = []
    handler.secure = lambda api=False: secured.append(api)
    handler.read_json = lambda: payload
    handler.respond = lambda status, body, *args, **kwargs: result.update(status=status, body=body)
    def failure(error):
        raise error
    handler.failure = failure
    (handler.do_GET if payload is None else handler.do_POST)()
    assert secured == [True]
    return result["status"], result["body"]


def save_and_accept(app, identifier):
    path = f"/api/workspaces/{identifier}"
    _, view = dispatch(app, path + "/ocr?page=1")
    item = view["items"][0]
    payload = {"revision": view["revision"], "id": item["id"], "value": "WRONG",
               "inventory_sha256": view["inventory_sha256"], "context_sha256": item["context_sha256"]}
    _, saved = dispatch(app, path + "/ocr-edit", payload)
    _, accepted = dispatch(app, path + "/ocr-approve", {**payload, "revision": saved["revision"], "reviewer": "Synthetic Reviewer"})
    return accepted


def corrected_result(app, tmp_path):
    bundle, _, _, _, report = _make_bundle(tmp_path, name="corrected-result")
    lineage = tmp_path / "lineage-stub.json"
    lineage.write_text(json.dumps({"test": "explicit synthetic lineage stub", "dependencies": [
        {"path": str(report["input"]["path"]), "sha256": report["input"]["sha256"]}]}), encoding="utf-8")
    report["source_lineage"] = {"path": str(lineage), "sha256": file_sha256(lineage)}
    report["settings"] = app.config.public()
    update_report(bundle, report)
    return {**report, "bundle_path": str(bundle)}


def test_editor_routes_save_reopen_and_named_acceptance_without_a_server(editor_app):
    app, identifier, _, _ = editor_app
    state = app.state_path(identifier)
    before = state.read_bytes()
    status, view = dispatch(app, f"/api/workspaces/{identifier}/ocr?page=1")
    assert status == 200 and state.read_bytes() == before
    accepted = save_and_accept(app, identifier)
    assert accepted["ocr_editor"]["accepted_count"] == 1
    _, reopened = dispatch(app, f"/api/workspaces/{identifier}/ocr?page=1")
    assert reopened["items"][0]["value"] == "WRONG"
    assert reopened["items"][0]["approved_by"] == "Synthetic Reviewer"
    assert reopened["items"][0]["approved_at"]


def save_and_accept_insertion(app, identifier):
    path = f"/api/workspaces/{identifier}"
    _, inventory = dispatch(app, path + "/ocr?page=1&profile=expanded-v2")
    anchor = inventory["items"][0]
    payload = {"revision": inventory["revision"], "anchor_id": anchor["id"], "value": "ΩWORD",
        "placement": {"rect": [.35, .1, .1, .08], "order": "after"},
        "inventory_sha256": inventory["inventory_sha256"], "context_sha256": anchor["context_sha256"],
        "expansion_sha256": inventory["expansion_sha256"]}
    _, saved = dispatch(app, path + "/ocr-insert", payload)
    insertion = saved["ocr_saved_insertion_id"]
    _, accepted = dispatch(app, path + "/ocr-approve", {**payload, "revision": saved["revision"],
        "id": insertion, "reviewer": "Synthetic Reviewer"})
    return accepted, insertion


def test_expanded_routes_save_reopen_accept_and_remove_one_missing_word_without_a_server(editor_app):
    app, identifier, _, _ = editor_app
    state = app.state_path(identifier)
    before = state.read_bytes()
    path = f"/api/workspaces/{identifier}"
    _, inventory = dispatch(app, path + "/ocr?page=1&profile=expanded-v2")
    assert inventory["profile"] == "expanded-v2" and inventory["insertion_enabled"]
    assert state.read_bytes() == before
    accepted, insertion = save_and_accept_insertion(app, identifier)
    _, reopened = dispatch(app, path + "/ocr?page=1")
    assert reopened["profile"] == "expanded-v2"
    assert reopened["insertions"][0]["id"] == insertion
    assert reopened["insertions"][0]["value"] == "ΩWORD"
    assert reopened["insertions"][0]["approved_by"] == "Synthetic Reviewer"
    _, removed = dispatch(app, path + "/ocr-remove", {"id": insertion, "revision": accepted["revision"],
        "inventory_sha256": reopened["inventory_sha256"], "context_sha256": reopened["insertions"][0]["context_sha256"],
        "expansion_sha256": reopened["expansion_sha256"]})
    assert removed["ocr_editor"]["changed_count"] == 0
    _, cleared = dispatch(app, path + "/ocr?page=1&profile=expanded-v2")
    assert not cleared["insertions"]


def test_expanded_replacement_routes_accept_a_font_backed_character_and_bind_its_capability(editor_app):
    app, identifier, _, _ = editor_app
    path = f"/api/workspaces/{identifier}"
    _, inventory = dispatch(app, path + "/ocr?page=1&profile=expanded-v2")
    item = inventory["items"][0]
    payload = {"revision": inventory["revision"], "id": item["id"], "value": "WRéNG",
        "inventory_sha256": inventory["inventory_sha256"], "context_sha256": item["context_sha256"],
        "expansion_sha256": inventory["expansion_sha256"]}
    _, saved = dispatch(app, path + "/ocr-edit", payload)
    before = app.state_path(identifier).read_bytes()
    with pytest.raises(ws.RevisionConflict, match="capability"):
        dispatch(app, path + "/ocr-approve", {**payload, "revision": saved["revision"],
            "reviewer": "Synthetic Reviewer", "expansion_sha256": "0" * 64})
    assert app.state_path(identifier).read_bytes() == before
    _, accepted = dispatch(app, path + "/ocr-approve", {**payload, "revision": saved["revision"], "reviewer": "Synthetic Reviewer"})
    assert accepted["ocr_editor"]["accepted_count"] == 1


@pytest.mark.parametrize("action", ["ocr-insert", "ocr-approve", "ocr-remove"])
def test_expanded_routes_reject_ai_actor_and_keep_the_saved_review(editor_app, action):
    app, identifier, _, _ = editor_app
    _, insertion = save_and_accept_insertion(app, identifier)
    path = f"/api/workspaces/{identifier}"
    _, inventory = dispatch(app, path + "/ocr?page=1")
    item = inventory["insertions"][0]
    payload = {"revision": inventory["revision"], "id": insertion, "anchor_id": item["anchor_id"], "value": "WORD",
        "placement": item["placement"], "reviewer": "AI actor", "actor": "ai",
        "inventory_sha256": inventory["inventory_sha256"], "context_sha256": item["context_sha256"],
        "expansion_sha256": inventory["expansion_sha256"]}
    before = app.state_path(identifier).read_bytes()
    with pytest.raises(ws.WorkspaceError, match="human"):
        dispatch(app, path + "/" + action, payload)
    assert app.state_path(identifier).read_bytes() == before


def test_expanded_copy_worker_receives_exact_plan2_and_preserves_earlier_notes(editor_app, monkeypatch):
    app, identifier, captured, tmp_path = editor_app
    view = app.view(identifier)
    ws.review_item(app.state_path(identifier), "reading-order", "blocked", "Synthetic Reviewer", "2026-10-25",
        view["revision"], notes="The earlier omitted text problem remains for human review.")
    accepted, insertion = save_and_accept_insertion(app, identifier)
    old = app.state_path(identifier).read_bytes()
    result = corrected_result(app, tmp_path)
    plans = []
    def worker(source, destination, config, cancel, progress, **kwargs):
        plan = json.loads(Path(kwargs["ocr_correction_plan"]).read_text(encoding="utf-8"))
        plans.append(plan)
        assert plan["schema_version"] == "phase2-ocr-text-corrections-2"
        assert plan["corrections"][0]["id"] == insertion
        assert plan["corrections"][0]["value"] == "ΩWORD"
        assert file_sha256(kwargs["ocr_correction_plan"]) == kwargs["expected_ocr_correction_sha256"]
        assert config.public() == json.loads((Path(accepted["bundle_path"]) / "report.json").read_text(encoding="utf-8"))["settings"]
        return result
    monkeypatch.setattr(web, "process_isolated", worker)
    app.ocr_apply(identifier, {"revision": accepted["revision"]})
    finished = captured["work"](threading.Event(), lambda value: None, "d" * 24)
    assert len(plans) == 1 and app.state_path(identifier).read_bytes() == old
    new = app.view(finished["documents"][0]["workspace_id"])
    assert new["previous_review"]["notes_count"] == new["previous_review"]["blocked_count"] == 1
    assert new["counts"]["manual_approved"] == 0


@pytest.mark.parametrize("change", ["queued-revision", "frozen-plan", "later-note"])
def test_expanded_copy_keeps_revision_and_plan_race_guards(editor_app, monkeypatch, change):
    app, identifier, captured, tmp_path = editor_app
    accepted, _ = save_and_accept_insertion(app, identifier)
    result = corrected_result(app, tmp_path)
    calls = []
    def worker(*args, **kwargs):
        calls.append(True)
        if change == "later-note":
            view = app.view(identifier)
            ws.review_item(app.state_path(identifier), "reading-order", "blocked", "Synthetic Reviewer", "2026-10-25",
                view["revision"], notes="A later note saved while processing the new insertion.")
        return result
    monkeypatch.setattr(web, "process_isolated", worker)
    app.ocr_apply(identifier, {"revision": accepted["revision"]})
    if change == "queued-revision":
        ws.review_item(app.state_path(identifier), "reading-order", "pending", "Synthetic Reviewer", "2026-10-25",
            accepted["revision"], notes="New note before processing starts.")
    if change == "frozen-plan":
        plan = next((app.root / "exports").glob("*/review-*/ocr-corrections.json"))
        plan.write_bytes(b'{"changed":true}')
    before = app.state_path(identifier).read_bytes()
    with pytest.raises(ws.RevisionConflict):
        captured["work"](threading.Event(), lambda value: None, "d" * 24)
    assert bool(calls) == (change == "later-note")
    if change != "later-note": assert app.state_path(identifier).read_bytes() == before
    else:
        item = next(item for item in app.view(identifier)["manual_items"] if item["id"] == "reading-order")
        assert item["status"] == "blocked" and "later note" in item["notes"]
    assert len(list((app.root / "workspaces").glob("*/state.json"))) == 1


def test_cancelled_expanded_copy_keeps_the_named_insertion_acceptance(editor_app, monkeypatch):
    app, identifier, captured, _ = editor_app
    accepted, _ = save_and_accept_insertion(app, identifier)
    before = app.state_path(identifier).read_bytes()
    def cancelled(*args, **kwargs):
        raise InterruptedError("Synthetic cancellation; no PDF worker started")
    monkeypatch.setattr(web, "process_isolated", cancelled)
    app.ocr_apply(identifier, {"revision": accepted["revision"]})
    with pytest.raises(InterruptedError):
        captured["work"](threading.Event(), lambda value: None, "d" * 24)
    assert app.state_path(identifier).read_bytes() == before
    assert app.view(identifier)["ocr_editor"]["accepted_count"] == 1


@pytest.mark.parametrize("operation", ["ocr-edit", "ocr-approve"])
def test_editor_route_cannot_claim_an_ai_actor(editor_app, operation):
    app, identifier, _, _ = editor_app
    _, view = dispatch(app, f"/api/workspaces/{identifier}/ocr?page=1")
    item = view["items"][0]
    payload = {"revision": view["revision"], "id": item["id"], "value": "WRONG", "reviewer": "Model",
               "inventory_sha256": view["inventory_sha256"], "context_sha256": item["context_sha256"], "actor": "ai"}
    before = app.state_path(identifier).read_bytes()
    with pytest.raises(ws.WorkspaceError, match="human"):
        dispatch(app, f"/api/workspaces/{identifier}/{operation}", payload)
    assert app.state_path(identifier).read_bytes() == before


@pytest.mark.parametrize("editor_app", [("textless", "standard"), ("textless", "angles"), ("skip", "angles")], indirect=True)
def test_ocr_only_apply_keeps_old_blocker_notes_and_creates_fresh_review(editor_app, monkeypatch):
    app, identifier, captured, tmp_path = editor_app
    v = app.view(identifier)
    ws.review_item(app.state_path(identifier), "reading-order", "blocked", "Synthetic Reviewer",
                   "2026-10-25", v["revision"], notes="Keep the earlier reported issue.")
    accepted = save_and_accept(app, identifier)
    old = app.state_path(identifier).read_bytes()
    result = corrected_result(app, tmp_path)
    saved_settings = json.loads((Path(accepted["bundle_path"]) / "report.json").read_text(encoding="utf-8"))["settings"]
    def no_recognition_presence_check(config):
        raise AssertionError("Editing existing OCR text must not require an OCR runtime or rerun recognition")
    monkeypatch.setattr(web, "_require_ocr_runtime", no_recognition_presence_check)
    calls = []
    def worker(source, destination, config, cancel, progress, **kwargs):
        calls.append((source, destination, config, kwargs))
        # This boundary adopts the exact old preparation. The real pipeline
        # validates it before switching only the new derivative to OCR off.
        assert config.public() == saved_settings
        assert kwargs["ocr_correction_bundle"] == accepted["bundle_path"]
        assert kwargs["expected_source_sha256"] == accepted["source"]["sha256"]
        assert file_sha256(kwargs["ocr_correction_plan"]) == kwargs["expected_ocr_correction_sha256"]
        assert "sidecar" not in kwargs
        return result
    monkeypatch.setattr(web, "process_isolated", worker)
    response = app.ocr_apply(identifier, {"revision": accepted["revision"]})
    assert response["job_id"] == "b" * 24
    finished = captured["work"](threading.Event(), lambda message: None, "c" * 24)
    new_id = finished["documents"][0]["workspace_id"]
    assert new_id != identifier and len(calls) == 1
    assert app.state_path(identifier).read_bytes() == old
    new = app.view(new_id)
    assert new["source_lineage"] == result["source_lineage"]
    assert new["previous_review"]["workspace_id"] == identifier
    assert new["previous_review"]["notes_count"] == 1
    assert new["previous_review"]["blocked_count"] == 1
    assert new["previous_review"]["human_approvals_copied"] == 0
    assert all(item["status"] == "pending" for item in new["manual_items"])


@pytest.mark.parametrize("revision", [False, True, -1, 1000])
def test_ocr_apply_refuses_wrong_revision_before_export_or_queue(editor_app, revision):
    app, identifier, captured, _ = editor_app
    save_and_accept(app, identifier)
    with pytest.raises(ws.RevisionConflict):
        app.ocr_apply(identifier, {"revision": revision})
    assert not captured
    assert not list((app.root / "exports").iterdir())


def test_legacy_apply_cannot_silently_ignore_saved_ocr_drafts(editor_app):
    app, identifier, captured, _ = editor_app
    accepted = save_and_accept(app, identifier)
    before = app.state_path(identifier).read_bytes()
    with pytest.raises(ValueError, match="separate passes"):
        app.apply(identifier, {"revision": accepted["revision"]})
    assert not captured and app.state_path(identifier).read_bytes() == before


@pytest.mark.parametrize("change", ["review-revision", "frozen-plan"])
def test_queued_ocr_apply_rechecks_revision_and_plan_before_worker(editor_app, monkeypatch, change):
    app, identifier, captured, _ = editor_app
    accepted = save_and_accept(app, identifier)
    app.ocr_apply(identifier, {"revision": accepted["revision"]})
    if change == "review-revision":
        ws.review_item(app.state_path(identifier), "reading-order", "pending", "Synthetic Reviewer",
                       "2026-10-25", accepted["revision"], notes="Later saved note.")
    else:
        plan = next((app.root / "exports").glob("*/review-*/ocr-corrections.json"))
        plan.write_bytes(b'{"changed":true}')
    calls = []
    monkeypatch.setattr(web, "process_isolated", lambda *args, **kwargs: calls.append(args))
    before = app.state_path(identifier).read_bytes()
    with pytest.raises(ws.RevisionConflict, match="changed"):
        captured["work"](threading.Event(), lambda message: None, "c" * 24)
    assert not calls and app.state_path(identifier).read_bytes() == before


def test_later_human_edit_preserved_without_switching_to_completed_copy(editor_app, monkeypatch):
    app, identifier, captured, tmp_path = editor_app
    accepted = save_and_accept(app, identifier)
    result = corrected_result(app, tmp_path)
    def worker(*args, **kwargs):
        current = app.view(identifier)
        ws.review_item(app.state_path(identifier), "reading-order", "blocked", "Synthetic Reviewer",
                       "2026-10-25", current["revision"], notes="A new problem reported during processing.")
        return result
    monkeypatch.setattr(web, "process_isolated", worker)
    app.ocr_apply(identifier, {"revision": accepted["revision"]})
    with pytest.raises(ws.RevisionConflict, match="during OCR correction"):
        captured["work"](threading.Event(), lambda message: None, "c" * 24)
    latest = app.view(identifier)
    item = next(item for item in latest["manual_items"] if item["id"] == "reading-order")
    assert item["status"] == "blocked" and item["notes"] == "A new problem reported during processing."
    assert len(list((app.root / "workspaces").glob("*/state.json"))) == 1


def test_cancelled_correction_retains_saved_acceptance_and_old_review(editor_app, monkeypatch):
    app, identifier, captured, _ = editor_app
    accepted = save_and_accept(app, identifier)
    old = app.state_path(identifier).read_bytes()
    def cancelled(source, destination, config, cancel, progress, **kwargs):
        assert cancel.is_set()
        raise InterruptedError("Synthetic worker cancellation before any processing")
    monkeypatch.setattr(web, "process_isolated", cancelled)
    app.ocr_apply(identifier, {"revision": accepted["revision"]})
    cancel = threading.Event(); cancel.set()
    with pytest.raises(InterruptedError):
        captured["work"](cancel, lambda message: None, "c" * 24)
    assert app.state_path(identifier).read_bytes() == old
    assert app.view(identifier)["ocr_editor"]["accepted_count"] == 1
    assert len(list((app.root / "workspaces").glob("*/state.json"))) == 1


def test_worker_forwards_bound_ocr_and_lineage_options_without_starting_a_process(tmp_path, monkeypatch):
    received = {}
    def process(source, destination, config, **options):
        received.update(options)
        return {"bundle_path": str(tmp_path / "synthetic-result")}
    monkeypatch.setattr(web, "process_file", process)
    messages = []
    channel = SimpleNamespace(put=messages.append)
    extra = {"ocr_correction_plan": "accepted-plan.json", "expected_ocr_correction_sha256": "a" * 64,
             "ocr_correction_bundle": "bound-bundle", "source_lineage": "lineage.json", "expected_lineage_sha256": "b" * 64}
    web._process_child("input.pdf", "output", RuntimeConfig(), None, None, "c" * 64, None, None,
                       channel, threading.Event(), extra)
    assert all(received[key] == value for key, value in extra.items())
    assert received["expected_source_sha256"] == "c" * 64
    assert messages == [("result", str(tmp_path / "synthetic-result"))]


