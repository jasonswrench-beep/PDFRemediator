"""Saved cancellation labels use explicit evidence, never release authority."""
from __future__ import annotations

import hashlib
import http.client
import json
from pathlib import Path
import threading

import pikepdf
import pytest

from pdf_remediator import inspection, pipeline, web, workspace
from pdf_remediator.config import RuntimeConfig


@pytest.fixture
def cancelled_review(tmp_path):
    source = tmp_path / "original.pdf"
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(source)
    app = web.Application(tmp_path / "application", RuntimeConfig(project_root=tmp_path))
    event = threading.Event()
    event.set()
    report = pipeline.process_file(source, app.root / "runs", app.config, cancel=event)
    assert report["status"] == "failed" and report["cancelled"] is True and report["output"] is None
    identifier = app.import_bundle(report["bundle_path"])
    yield app, identifier, report
    app.close()


def _legacy(app, identifier):
    path = app.state_path(identifier)
    state = workspace._read_state(path)
    del state["bundle"]["cancelled"]
    workspace._save(path, state)
    return path, state


def _http_dashboard(app):
    server = web.ReviewServer(app)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request("GET", "/api/dashboard", headers={"X-Review-Token": app.token})
        response = connection.getresponse()
        assert response.status == 200
        return json.loads(response.read())
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_actual_cancelled_bundle_retains_failed_status_and_reopens_without_saved_changes(cancelled_review):
    app, identifier, report = cancelled_review
    path = app.state_path(identifier)
    saved = path.read_bytes()
    bundle = Path(report["bundle_path"])
    original = Path(report["input"]["path"]).read_bytes()
    immutable = {p: p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    state = workspace._read_state(path)
    assert state["bundle"]["cancelled"] is True
    for view in (app.view(identifier), workspace.get_saved_summary(path)):
        assert view["status"] == "failed" and view["cancelled"] is True
    view = app.view(identifier)
    assert view["historical_status"] == "failed" and view["output"] is None
    assert view["verification"] == "not-verified"
    assert _http_dashboard(app)["documents"][0]["cancelled"] is True
    assert app.catalog()["bundles"][0]["cancelled"] is True
    assert path.read_bytes() == saved
    assert Path(report["input"]["path"]).read_bytes() == original
    assert all(p.read_bytes() == value for p, value in immutable.items())


def test_genuine_failure_with_cancel_wording_is_not_cancelled(cancelled_review, monkeypatch):
    app, _, cancelled = cancelled_review
    source = Path(cancelled["input"]["path"])
    misleading = source.with_name("cancelled-document.pdf")
    misleading.write_bytes(source.read_bytes())

    def named_processing_failure_stub(*args, **kwargs):
        raise RuntimeError("Processing was cancelled in an unrelated error description")

    monkeypatch.setattr(inspection, "inspect_pdf", named_processing_failure_stub)
    report = pipeline.process_file(misleading, app.root / "runs" / "failure", app.config)
    assert report["status"] == "failed" and "cancelled" not in report
    identifier = app.import_bundle(report["bundle_path"])
    path = app.state_path(identifier)
    assert workspace._read_state(path)["bundle"]["cancelled"] is False
    assert app.view(identifier)["cancelled"] is False
    _legacy(app, identifier)
    assert workspace.get_saved_summary(path)["cancelled"] is False
    row = next(row for row in app.dashboard()["documents"] if row["id"] == identifier)
    assert row["status"] == "failed" and row["cancelled"] is False


def test_legacy_cancellation_reads_bound_report_without_migration_pdf_checks_or_locks(cancelled_review, monkeypatch):
    app, identifier, report = cancelled_review
    path, _ = _legacy(app, identifier)
    before = path.read_bytes()
    assert app.view(identifier)["cancelled"] is True
    assert path.read_bytes() == before

    def forbidden(*args, **kwargs):
        pytest.fail("A display summary acquired a review/PDF lock or reassessed an artifact")

    class ForbiddenLock:
        __enter__ = forbidden
        __exit__ = forbidden

    app.pdf_lock = ForbiddenLock()
    for name in ("_locked", "_refresh", "verify_bundle", "file_sha256", "collect_decisions", "_view", "_automatic_snapshot"):
        monkeypatch.setattr(workspace, name, forbidden)
    real_read = Path.read_bytes
    allowed = {path, Path(report["bundle_path"]) / "report.json"}

    def bounded_read(self):
        assert self in allowed, "A summary read an unrelated PDF, manifest or diagnostic"
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", bounded_read)
    summary = workspace.get_saved_summary(path)
    row = _http_dashboard(app)["documents"][0]
    assert summary["cancelled"] is row["cancelled"] is True
    assert summary["status"] == row["status"] == "failed"
    assert summary["artifacts_checked"] is row["artifacts_checked"] is False
    assert path.read_bytes() == before
    assert "cancelled" not in json.loads(before)["bundle"]


@pytest.mark.parametrize("change", [
    "false", "string", "integer", "missing", "candidate", "output", "missing-output",
    "input", "prepared", "fingerprint", "missing-fingerprint", "list", "malformed", "hash", "missing-report",
])
def test_legacy_malformed_or_incoherent_evidence_stays_failed(cancelled_review, change):
    app, identifier, _ = cancelled_review
    path, state = _legacy(app, identifier)
    report_path = Path(state["bundle"]["path"]) / "report.json"
    report = json.loads(report_path.read_bytes())
    if change == "false": report["cancelled"] = False
    elif change == "string": report["cancelled"] = "true"
    elif change == "integer": report["cancelled"] = 1
    elif change == "missing": del report["cancelled"]
    elif change == "candidate": report["status"] = "candidate"
    elif change == "output": report["output"] = {"path": "unexpected.pdf", "sha256": "a" * 64}
    elif change == "missing-output": del report["output"]
    elif change == "input": report["input"]["sha256"] = "b" * 64
    elif change == "prepared": report["decision_source"] = report["input"]
    elif change == "fingerprint": report["run_fingerprint"] = "different"
    elif change == "missing-fingerprint": del state["bundle"]["run_fingerprint"]
    elif change == "list": report = [report]
    raw = b"not valid json" if change == "malformed" else json.dumps(report).encode()
    report_path.write_bytes(raw)
    if change != "hash":
        state["bundle"]["report_sha256"] = hashlib.sha256(raw).hexdigest()
    if change == "missing-report": report_path.unlink()
    workspace._save(path, state)
    before = path.read_bytes()
    summary = workspace.get_saved_summary(path)
    row = app.dashboard()["documents"][0]
    assert summary["status"] == row["status"] == "failed"
    assert summary["cancelled"] is row["cancelled"] is False
    assert summary["artifacts_checked"] is row["artifacts_checked"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("metadata", [False, "true", 1, None])
def test_new_cancelled_metadata_must_be_literal_true_and_match_immutable_report(cancelled_review, metadata):
    app, identifier, _ = cancelled_review
    path = app.state_path(identifier)
    state = workspace._read_state(path)
    state["bundle"]["cancelled"] = metadata
    workspace._save(path, state)
    before = path.read_bytes()
    assert workspace.get_saved_summary(path)["cancelled"] is False
    assert path.read_bytes() == before
    current = app.view(identifier)
    assert current["stale"] is True and current["status"] == "needs-manual"
    assert current["cancelled"] is False
    assert "Workspace cancellation metadata differs from immutable report" in workspace._read_state(path)["stale_reasons"]


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("guard", ["status", "output", "artifact", "stale"])
def test_saved_cancellation_never_overrides_status_or_output_guards(cancelled_review, legacy, guard):
    app, identifier, _ = cancelled_review
    path = app.state_path(identifier)
    state = workspace._read_state(path)
    if legacy: del state["bundle"]["cancelled"]
    if guard == "status": state["bundle"]["status"] = "candidate"
    elif guard == "output": state["bindings"]["output"] = state["bindings"]["source"]
    elif guard == "artifact": state["artifact_sha256"] = "f" * 64
    else: state["stale"] = True
    workspace._save(path, state)
    before = path.read_bytes()
    assert workspace.get_saved_summary(path)["cancelled"] is False
    assert app.dashboard()["documents"][0]["cancelled"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("binding", ["empty-source", "source-hash", "prepared-hash", "missing-output"])
def test_malformed_legacy_bindings_do_not_become_cancellation_even_when_report_matches(cancelled_review, binding):
    app, identifier, _ = cancelled_review
    path, state = _legacy(app, identifier)
    report_path = Path(state["bundle"]["path"]) / "report.json"
    report = json.loads(report_path.read_bytes())
    if binding == "empty-source":
        state["bindings"]["source"] = report["input"] = {}
    elif binding == "source-hash":
        state["bindings"]["source"]["sha256"] = report["input"]["sha256"] = "invalid"
    elif binding == "prepared-hash":
        state["bindings"]["prepared"] = report["decision_source"] = {"path": "prepared.pdf", "sha256": True}
    else:
        del state["bindings"]["output"]
    raw = json.dumps(report).encode()
    report_path.write_bytes(raw)
    state["bundle"]["report_sha256"] = hashlib.sha256(raw).hexdigest()
    workspace._save(path, state)
    before = path.read_bytes()
    assert workspace.get_saved_summary(path)["cancelled"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("legacy", [False, True])
def test_normal_saved_candidate_does_not_read_immutable_report_for_cancellation(cancelled_review, monkeypatch, legacy):
    app, identifier, _ = cancelled_review
    path = app.state_path(identifier)
    state = workspace._read_state(path)
    state["bundle"]["status"] = "candidate"
    if legacy: del state["bundle"]["cancelled"]
    workspace._save(path, state)

    def forbidden(*args, **kwargs):
        pytest.fail("An ordinary saved candidate read immutable report bytes for cancellation")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    assert workspace.get_saved_summary(path)["cancelled"] is False
    assert app.dashboard()["documents"][0]["cancelled"] is False
