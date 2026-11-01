"""Loopback HTTP/security regressions; expensive worker/validator are named stubs."""
from __future__ import annotations

import hashlib
import http.client
import io
import json
from pathlib import Path
import shutil
import threading
import time
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from pdf_remediator import pipeline, preview, web, workspace
from pdf_remediator.config import RuntimeConfig
from test_pipeline import input_pdf, fast_validator, tagged_control


@pytest.fixture
def application(tmp_path):
    app = web.Application(tmp_path / "application", RuntimeConfig(project_root=tmp_path))
    yield app
    app.close()


@pytest.fixture
def http_app(application):
    server = web.ReviewServer(application)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    yield application, server
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    assert not thread.is_alive()


def request(http_app, path, method="GET", payload=None, headers=None, token=True):
    app, server = http_app
    chosen = {"Host": "127.0.0.1:" + str(server.server_port)}
    if token:
        chosen["X-Review-Token"] = app.token
    body = payload
    if isinstance(payload, (dict, list)):
        body = json.dumps(payload).encode()
        chosen["Content-Type"] = "application/json"
    chosen.update(headers or {})
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
    try:
        connection.request(method, path, body=body, headers=chosen)
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
        return response.status, dict(response.getheaders()), result
    finally:
        connection.close()


def wait_job(app, identifier, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with app.lock:
            job = app.jobs[identifier]
            if job["status"] not in {"queued", "running"}:
                return app.public_job(job)
        time.sleep(.01)
    raise AssertionError("Synthetic local job did not finish")


def imported(application, input_pdf, tmp_path):
    report = pipeline.process_file(input_pdf, tmp_path / "initial", application.config)
    identifier = application.import_bundle(report["bundle_path"])
    return identifier, application.view(identifier), report


def test_http_private_api_requires_exact_host_and_token(http_app):
    status, headers, body = request(http_app, "/", token=False)
    assert status == 200 and b"PDF Remediator" in body
    assert http_app[0].token.encode() not in body
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "object-src 'none'" in headers["Content-Security-Policy"]
    assert request(http_app, "/api/dashboard", token=False)[0] == 403
    assert request(http_app, "/api/dashboard", headers={"X-Review-Token": "wrong"})[0] == 403
    assert request(http_app, "/api/dashboard", headers={"Host": "attacker.invalid"})[0] == 403
    assert request(http_app, "/api/dashboard")[0] == 200


@pytest.mark.parametrize('route,filename,content_type', [
    ('/PDFRemediator.svg', 'PDFRemediator.svg', 'image/svg+xml; charset=utf-8'),
    ('/favicon.ico', 'PDFRemediator.ico', 'image/vnd.microsoft.icon'),
])
def test_http_icon_assets_keep_same_origin_and_security_headers(http_app, route, filename, content_type):
    status, headers, body = request(http_app, route, token=False)
    assert status == 200 and body == (web.ASSETS / filename).read_bytes()
    assert headers['Content-Type'] == content_type
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['Cache-Control'] == 'no-store'
    assert "img-src 'self' blob:" in headers['Content-Security-Policy']
    assert "object-src 'none'" in headers['Content-Security-Policy']
    assert 'Access-Control-Allow-Origin' not in headers
    for external in ({'Host': 'attacker.invalid'}, {'Origin': 'https://attacker.invalid'}, {'Sec-Fetch-Site': 'cross-site'}):
        assert request(http_app, route, headers=external, token=False)[0] == 403


def test_http_page_declares_svg_favicon_with_ico_fallback(http_app):
    status, _, body = request(http_app, '/', token=False)
    assert status == 200
    assert b'<link rel="icon" href="/favicon.ico" type="image/vnd.microsoft.icon">' in body
    assert b'<link rel="icon" href="/PDFRemediator.svg" type="image/svg+xml" sizes="any">' in body
    assert b'<img class="brand-icon" src="/PDFRemediator.svg" alt="">' in body


@pytest.mark.parametrize('route', ['/web_assets/PDFRemediator.svg', '/PDFRemediator.ico', '/other.svg', '/other.ico'])
def test_http_icon_routes_do_not_expose_other_asset_paths(http_app, route):
    assert request(http_app, route, token=False)[0] == 404


@pytest.mark.parametrize("headers", [{"Origin": "https://attacker.invalid"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}])
def test_http_rejects_external_origins_even_with_valid_token(http_app, headers):
    assert request(http_app, "/api/dashboard", headers=headers)[0] == 403
    assert request(http_app, "/api/stop", "POST", {}, headers)[0] == 403


def test_http_same_origin_and_options_are_explicit(http_app):
    status, headers, body = request(http_app, "/api/dashboard", headers={"Origin": http_app[1].origin})
    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers
    status, headers, body = request(http_app, "/api/upload", "OPTIONS", token=False)
    assert status == 403 and "Access-Control-Allow-Origin" not in headers


@pytest.mark.parametrize("payload,headers", [
    (b"{}", {"Content-Type": "text/plain"}),
    (b"{}", {"Content-Type": "application/json", "Content-Length": str(web.MAX_JSON + 1)}),
    (b"{}", {"Content-Type": "application/json", "Content-Length": "-1"}),
    (b"{}", {"Content-Type": "application/json", "Content-Length": "invalid"}),
    ([], {}),
])
def test_http_json_framing_and_size_are_rejected_before_action(http_app, payload, headers):
    assert request(http_app, "/api/process", "POST", payload, headers)[0] == 400
    assert not http_app[0].jobs


@pytest.mark.parametrize("path", ["/../secret.txt", "/%2e%2e/secret.txt", "/api/workspaces/../../secret.txt", "/api/workspaces/" + "a" * 24 + "/../../secret.txt", "/source?path=C:/private.pdf"])
def test_http_no_static_traversal_or_arbitrary_file_route(http_app, path):
    assert request(http_app, path)[0] in {400, 404}


@pytest.mark.parametrize("name", ["../escape.pdf", "folder/escape.pdf", r"..\escape.pdf", r"C:\private.pdf", "wrong.html", "nul\x00.pdf"])
def test_http_upload_filename_cannot_escape_or_choose_another_type(http_app, name):
    status, headers, body = request(http_app, "/api/upload", "POST", b"%PDF-test", {"Content-Type": "application/pdf", "X-File-Name": quote(name)})
    assert status == 400
    assert not list((http_app[0].root / "inputs").rglob("*.pdf"))


def test_http_upload_content_and_size_guard(http_app):
    assert request(http_app, "/api/upload", "POST", b"not pdf", {"Content-Type": "application/pdf", "X-File-Name": "reading.pdf"})[0] == 400
    assert request(http_app, "/api/upload", "POST", b"%PDF-", {"Content-Type": "text/plain", "X-File-Name": "reading.pdf"})[0] == 400
    assert request(http_app, "/api/upload", "POST", b"", {"Content-Type": "application/pdf", "X-File-Name": "reading.pdf", "Content-Length": str(web.MAX_UPLOAD + 1)})[0] == 400
    assert not list((http_app[0].root / "inputs").rglob("*.pdf"))


def test_http_cannot_import_outside_selected_project(http_app, tmp_path):
    # This location is outside both the configured project and review directory.
    status, headers, body = request(http_app, "/api/import", "POST", {"path": str(tmp_path.parent / "outside-project")})
    assert status == 400
    assert "inside this project" in body["error"]


def test_http_upload_process_job_preserves_original_and_has_bound_bundle(http_app, input_pdf, fast_validator, monkeypatch):
    original_hash = pipeline.sha(input_pdf)
    called = []

    def named_inline_worker_test_stub(source, destination, config, cancel, progress, sidecar=None, decision_bundle=None, expected_source_sha256=None):
        called.append(Path(source))
        return pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, sidecar=sidecar, decision_bundle=decision_bundle,
                                     expected_source_sha256=expected_source_sha256)

    monkeypatch.setattr(web, "process_isolated", named_inline_worker_test_stub)
    status, headers, upload = request(http_app, "/api/upload", "POST", input_pdf.read_bytes(), {"Content-Type": "application/pdf", "X-File-Name": "reading.pdf"})
    assert status == 201
    status, headers, result = request(http_app, "/api/process", "POST", {"inputs": [upload["id"]], "options": {}})
    assert status == 202
    job = wait_job(http_app[0], result["job_id"])
    assert job["status"] == "done", job
    assert called and called[0] != input_pdf
    assert pipeline.sha(input_pdf) == original_hash and pipeline.sha(called[0]) == original_hash
    identifier = job["result"]["documents"][0]["workspace_id"]
    status, headers, view = request(http_app, "/api/workspaces/" + identifier)
    assert status == 200 and view["verification"] == "not-verified"
    assert pipeline.verify_bundle(view["bundle_path"])
    status, headers, downloaded = request(http_app, "/api/workspaces/" + identifier + "/download")
    assert status == 200
    assert headers["Content-Disposition"] == 'attachment; filename="reading-candidate.pdf"'
    assert downloaded == Path(view["output"]["path"]).read_bytes()


def test_http_process_cannot_override_tool_paths_or_reference_arbitrary_inputs(http_app):
    for payload in [{"inputs": ["../../private.pdf"]}, {"inputs": ["a" * 24], "options": {"project_root": "C:/"}}, {"inputs": []}]:
        assert request(http_app, "/api/process", "POST", payload)[0] in {400, 404}
    assert not http_app[0].jobs


def test_http_unmeasured_scan_layout_is_refused_before_queue(http_app, input_pdf, monkeypatch):
    app = http_app[0]
    original = input_pdf.read_bytes()
    uploaded = app.upload(io.BytesIO(original), len(original), 'source.pdf')
    monkeypatch.setattr(app, 'submit', lambda *a: pytest.fail('Unmeasured scan layout was queued'))
    status, _, body = request(http_app, '/api/process', 'POST', {
        'inputs': [uploaded['id']], 'options': {'ocr_profile': 'arbitrary-plugin'}})
    assert status == 400 and 'Scan layout' in body['error']
    assert not app.jobs and input_pdf.read_bytes() == original


def test_http_unknown_ocr_page_mode_is_refused_before_queue(http_app, input_pdf, monkeypatch):
    app = http_app[0]
    original = input_pdf.read_bytes()
    uploaded = app.upload(io.BytesIO(original), len(original), 'source.pdf')
    before = {p.relative_to(app.root): p.read_bytes() for p in app.root.rglob('*') if p.is_file()}
    monkeypatch.setattr(app, 'submit', lambda *a: pytest.fail('Unknown OCR mode was queued'))
    status, _, body = request(http_app, '/api/process', 'POST', {
        'inputs': [uploaded['id']], 'options': {'ocr_mode': 'force', 'ocr_profile': 'angles'}})
    assert status == 400 and 'OCR must be' in body['error']
    assert not app.jobs and input_pdf.read_bytes() == original
    assert before == {p.relative_to(app.root): p.read_bytes() for p in app.root.rglob('*') if p.is_file()}


def test_http_tilted_redo_refuses_before_runtime_check_or_queue(http_app, input_pdf, monkeypatch):
    app = http_app[0]; original = input_pdf.read_bytes()
    uploaded = app.upload(io.BytesIO(original), len(original), 'source.pdf')
    before = {p.relative_to(app.root): p.read_bytes() for p in app.root.rglob('*') if p.is_file()}
    monkeypatch.setattr(web, 'ocr_availability', lambda *a: pytest.fail('Unsupported combination reached a runtime check'))
    monkeypatch.setattr(app, 'submit', lambda *a: pytest.fail('Unsupported combination was queued'))
    status, _, body = request(http_app, '/api/process', 'POST', {
        'inputs': [uploaded['id']], 'options': {'ocr_mode': 'redo', 'ocr_profile': 'angles'}})
    assert status == 400 and 'wholly scanned pages' in body['error']
    assert not app.jobs and input_pdf.read_bytes() == original
    assert before == {p.relative_to(app.root): p.read_bytes() for p in app.root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode,profile', [('textless', 'standard'), ('textless', 'angles'), ('skip', 'angles')])
def test_http_new_ocr_choices_reach_the_queue_unchanged_with_named_presence_and_queue_doubles(
        http_app, input_pdf, monkeypatch, mode, profile):
    app = http_app[0]; original = input_pdf.read_bytes(); checked = []; queued = []
    uploaded = app.upload(io.BytesIO(original), len(original), 'source.pdf')
    def named_presence_metadata_only(config):
        checked.append((config.ocr_mode, config.ocr_profile))
        return {'available': True, 'runtime_verified': False, 'message': 'Named presence-only double; no native probe'}
    def named_queue_only(label, work):
        queued.append(label)
        return {'job_id': 'named-not-executed-OCR-job'}
    monkeypatch.setattr(web, 'ocr_availability', named_presence_metadata_only)
    monkeypatch.setattr(app, 'submit', named_queue_only)
    status, _, body = request(http_app, '/api/process', 'POST', {
        'inputs': [uploaded['id']], 'options': {'ocr_mode': mode, 'ocr_profile': profile}})
    assert status == 202 and body == {'job_id': 'named-not-executed-OCR-job'}
    assert checked == [(mode, profile)] and len(queued) == 1
    assert app.config.ocr_mode == 'off' and app.config.ocr_profile == 'standard' and not app.jobs
    assert input_pdf.read_bytes() == original


def test_dashboard_exposes_sanitized_ocr_presence_without_probes(application, tmp_path, monkeypatch):
    from pdf_remediator import doctor
    application.config.ocr_python = tmp_path / "not-included/python.exe"
    application.config.tesseract_dir = tmp_path / "not-included"
    monkeypatch.setattr(doctor, "inventory", lambda *a, **kw: pytest.fail("Dashboard ran full native doctor probes"))
    monkeypatch.setattr(doctor, "_probe", lambda *a, **kw: pytest.fail("Dashboard started a native probe"))
    result = application.dashboard()["capabilities"]["ocr"]
    assert result == doctor.ocr_availability(application.config)
    assert result["available"] is False and result["runtime_verified"] is False
    assert str(tmp_path) not in result["message"]
    assert not application.jobs


@pytest.mark.parametrize("mode", ["skip", "textless", "redo"])
def test_http_forged_unavailable_ocr_is_refused_before_queue(http_app, input_pdf, tmp_path, monkeypatch, mode):
    app = http_app[0]
    app.config.ocr_python = tmp_path / "not-included/python.exe"
    app.config.tesseract_dir = tmp_path / "not-included"
    original = input_pdf.read_bytes()
    uploaded = app.upload(io.BytesIO(original), len(original), "source.pdf")
    before = {path.relative_to(app.root): path.read_bytes() for path in app.root.rglob("*") if path.is_file()}
    monkeypatch.setattr(app, "submit", lambda *a, **kw: pytest.fail("Unavailable OCR was queued"))
    status, _, body = request(http_app, "/api/process", "POST", {"inputs": [uploaded["id"]], "options": {"ocr_mode": mode}})
    assert status == 400 and "OCR is not installed or configured" in body["error"]
    assert "Keep OCR off" in body["error"] and "accessible source document" in body["error"]
    assert app.config.ocr_mode == "off" and not app.jobs
    assert input_pdf.read_bytes() == original
    assert before == {path.relative_to(app.root): path.read_bytes() for path in app.root.rglob("*") if path.is_file()}


def test_http_cancel_sets_only_the_selected_job_event(http_app):
    release, entered = threading.Event(), threading.Event()

    def blocker(cancel, progress, identifier):
        entered.set()
        while not cancel.is_set() and not release.wait(.01):
            pass
        return {"cancel_observed": cancel.is_set()}

    job = http_app[0].submit("Synthetic cancellable job", blocker)
    try:
        assert entered.wait(2)
        assert request(http_app, "/api/jobs/" + job["job_id"] + "/cancel", "POST", {})[0] == 200
        finished = wait_job(http_app[0], job["job_id"])
        assert finished["status"] == "cancelled" and finished["result"]["cancel_observed"]
        assert "cancel" not in finished and "future" not in finished
    finally:
        release.set()


def test_http_edits_reject_stale_revision_and_do_not_modify_pdf(http_app, input_pdf, fast_validator, tmp_path):
    identifier, view, report = imported(http_app[0], input_pdf, tmp_path)
    before = pipeline.sha(Path(view["output"]["path"]))
    title = next(item for item in view["decisions"] if item["kind"] == "title")
    path = "/api/workspaces/" + identifier + "/edit"
    status, headers, changed = request(http_app, path, "POST", {"revision": view["revision"], "id": title["id"], "value": "An explicit edited title"})
    assert status == 200
    assert request(http_app, path, "POST", {"revision": view["revision"], "id": title["id"], "value": "Stale overwrite"})[0] == 409
    assert pipeline.sha(Path(view["output"]["path"])) == before


def approved_title(application, identifier):
    view = application.view(identifier)
    title = next(item for item in view["decisions"] if item["kind"] == "title")
    state = application.state_path(identifier)
    workspace.edit_decision(state, title["id"], "Accepted human course title", view["revision"])
    edited = application.view(identifier)
    workspace.approve_decision(state, title["id"], "Human Reviewer", "2026-10-16", edited["revision"])
    return application.view(identifier)


def test_importing_same_immutable_bundle_returns_existing_workspace(application, input_pdf, fast_validator, tmp_path):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    assert application.import_bundle(report["bundle_path"]) == identifier
    assert len(list((application.root / "workspaces").glob("*/state.json"))) == 1


def test_http_apply_accepted_edits_forwards_both_exact_hashes_and_rechecks(
        http_app, input_pdf, fast_validator, tmp_path, monkeypatch):
    app = http_app[0]
    identifier, original_view, report = imported(app, input_pdf, tmp_path)
    view = approved_title(app, identifier)
    source_hash = pipeline.sha(input_pdf)
    artifact = Path(original_view["output"]["path"])
    artifact_hash = pipeline.sha(artifact)
    calls = []

    def named_inline_apply_worker(source, destination, config, cancel, progress, **kwargs):
        calls.append(kwargs)
        assert kwargs["expected_source_sha256"] == source_hash
        assert kwargs["expected_sidecar_sha256"] == pipeline.sha(kwargs["sidecar"])
        assert Path(kwargs["decision_bundle"]) == Path(report["bundle_path"])
        return pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, **kwargs)

    monkeypatch.setattr(web, "process_isolated", named_inline_apply_worker)
    status, headers, queued = request(http_app, "/api/workspaces/" + identifier + "/apply", "POST", {"revision": view["revision"]})
    assert status == 202
    job = wait_job(app, queued["job_id"])
    assert job["status"] == "done", job
    assert len(calls) == 1 and len(fast_validator) == 4
    new_id = job["result"]["documents"][0]["workspace_id"]
    assert new_id != identifier
    refreshed = app.view(new_id)
    new_report = json.loads((Path(refreshed["bundle_path"]) / "report.json").read_text(encoding="utf-8"))
    assert new_report["checkpoint_reused"] is True
    assert new_report["output"]["sha256"] != artifact_hash
    assert new_report["gate1"]["input_sha256"] == new_report["output"]["sha256"]
    assert new_report["fidelity"]["after_sha256"] == new_report["output"]["sha256"]
    assert pipeline.verify_bundle(refreshed["bundle_path"])
    assert pipeline.sha(input_pdf) == source_hash and pipeline.sha(artifact) == artifact_hash


def test_queued_apply_rejects_export_changes_before_any_new_assessment(
        application, input_pdf, fast_validator, tmp_path, monkeypatch):
    identifier, original_view, report = imported(application, input_pdf, tmp_path)
    view = approved_title(application, identifier)
    source_hash = pipeline.sha(input_pdf)
    original_hash = pipeline.sha(original_view["output"]["path"])
    observed = []

    def named_inline_apply_worker_with_hash_guard(source, destination, config, cancel, progress, **kwargs):
        observed.append(kwargs)
        return pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, **kwargs)

    monkeypatch.setattr(web, "process_isolated", named_inline_apply_worker_with_hash_guard)
    release = threading.Event()
    application.submit("Queue barrier", lambda cancel, progress, job: release.wait(3))
    try:
        queued = application.apply(identifier, {"revision": view["revision"]})
        exported = next((application.root / "exports").rglob("decisions.json"))
        accepted_hash = pipeline.sha(exported)
        with exported.open("ab") as stream:
            stream.write(b"\n")
        release.set()
        result = wait_job(application, queued["job_id"])
        assert result["status"] == "failed", result
        assert "decisions changed while waiting" in result["error"]
        assert len(observed) == 1
        assert observed[0]["expected_sidecar_sha256"] == accepted_hash
        assert observed[0]["expected_source_sha256"] == source_hash
        assert len(fast_validator) == 2
        assert not list((application.root / "runs").rglob("*.pdf"))
        assert pipeline.sha(input_pdf) == source_hash
        assert pipeline.sha(original_view["output"]["path"]) == original_hash
    finally:
        release.set()


@pytest.mark.parametrize("consent", [False, None, "true", 1])
def test_assistance_requires_literal_explicit_consent(application, input_pdf, fast_validator, tmp_path, monkeypatch, consent):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    from pdf_remediator import assistance
    called = []
    monkeypatch.setattr(assistance, "suggest", lambda *args, **kwargs: called.append(args))
    with pytest.raises(ValueError, match="Explicitly"):
        application.assist(identifier, {"revision": view["revision"], "consent": consent, "endpoint": "http://127.0.0.1:11434/v1", "model": "test"})
    assert not called and not application.jobs


def test_queued_assistance_rechecks_revision_before_sending_context(application, input_pdf, fast_validator, tmp_path, monkeypatch):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    from pdf_remediator import assistance
    sent = []
    monkeypatch.setattr(assistance, "suggest", lambda *args, **kwargs: sent.append(args) or {"status": "no-suggestions"})
    release = threading.Event()
    block = application.submit("Queue barrier", lambda cancel, progress, job: release.wait(3))
    try:
        draft = application.assist(identifier, {"revision": view["revision"], "consent": True, "endpoint": "http://127.0.0.1:11434/v1", "model": "test"})
        title = next(item for item in view["decisions"] if item["kind"] == "title")
        workspace.edit_decision(application.state_path(identifier), title["id"], "Human change after queuing", view["revision"])
        release.set()
        result = wait_job(application, draft["job_id"])
        assert result["status"] == "failed"
        assert not sent, "Stale queued AI consent must be rejected before any document context is sent"
    finally:
        release.set()


def test_queued_processing_rechecks_selected_upload_hash(application, input_pdf, fast_validator, monkeypatch):
    uploaded = application.upload(io.BytesIO(input_pdf.read_bytes()), input_pdf.stat().st_size, "selected.pdf")
    selected = application.input_path(uploaded["id"])
    original_hash = pipeline.sha(selected)
    observed = []

    def named_inline_worker_with_real_hash_guard(source, destination, config, cancel, progress, **kwargs):
        observed.append(kwargs.get("expected_source_sha256"))
        return pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, **kwargs)

    monkeypatch.setattr(web, "process_isolated", named_inline_worker_with_real_hash_guard)
    release = threading.Event()
    application.submit("Queue barrier", lambda cancel, progress, job: release.wait(3))
    try:
        job = application.process({"inputs": [uploaded["id"]], "options": {}})
        selected.write_bytes(selected.read_bytes() + b"\n% Uploaded source changed while queued\n")
        release.set()
        result = wait_job(application, job["job_id"])
        assert result["status"] == "failed"
        assert observed == [original_hash]
        assert "input changed" in result["error"]
        assert not fast_validator and not list((application.root / "runs").rglob("*.pdf"))
    finally:
        release.set()


def test_ai_consent_revision_must_be_an_integer_before_context_send(application, input_pdf, fast_validator, tmp_path, monkeypatch):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    from pdf_remediator import assistance
    sent = []
    monkeypatch.setattr(assistance, "suggest", lambda *args, **kwargs: sent.append(args) or {"status": "no-suggestions"})
    with pytest.raises(ValueError, match="revision|changed"):
        application.assist(identifier, {"revision": False, "consent": True, "endpoint": "http://127.0.0.1:11434/v1", "model": "test"})
    assert not sent and not application.jobs


def test_ai_never_sends_context_from_a_stale_workspace(application, input_pdf, fast_validator, tmp_path, monkeypatch):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    input_pdf.write_bytes(input_pdf.read_bytes() + b"\n% original changed\n")
    stale = application.view(identifier)
    assert stale["stale"]
    from pdf_remediator import assistance
    sent = []
    monkeypatch.setattr(assistance, "suggest", lambda *args, **kwargs: sent.append(args) or {"status": "no-suggestions"})
    with pytest.raises(ValueError, match="stale|changed"):
        application.assist(identifier, {"revision": stale["revision"], "consent": True, "endpoint": "http://127.0.0.1:11434/v1", "model": "test"})
    assert not sent and not application.jobs


def test_preview_render_has_source_and_png_bindings(input_pdf, tmp_path):
    png, context = tmp_path / "preview.png", tmp_path / "preview.json"
    preview.render(input_pdf, pipeline.sha(input_pdf), 1, png, context)
    data = json.loads(context.read_text(encoding="utf-8"))
    assert data["page"] == 1 and "CONTROL-ANCHOR" in data["text"]
    assert data["source_sha256"] == pipeline.sha(input_pdf)
    assert data["png_sha256"] == pipeline.sha(png)


def test_preview_wrong_source_or_page_publishes_nothing(input_pdf, tmp_path):
    for expected, page in [("0" * 64, 1), (pipeline.sha(input_pdf), 0), (pipeline.sha(input_pdf), 999)]:
        png, context = tmp_path / "preview.png", tmp_path / "preview.json"
        with pytest.raises(ValueError):
            preview.render(input_pdf, expected, page, png, context)
        assert not png.exists() and not context.exists()


def test_preview_source_change_during_render_leaves_no_cache(input_pdf, tmp_path, monkeypatch):
    expected = pipeline.sha(input_pdf)
    calls = []

    def changed_after_read(path):
        calls.append(path)
        return expected if len(calls) == 1 else "changed"

    monkeypatch.setattr(preview, "file_sha256", changed_after_read)
    png, context = tmp_path / "preview.png", tmp_path / "preview.json"
    with pytest.raises(ValueError, match="changed during"):
        preview.render(input_pdf, expected, 1, png, context)
    assert not png.exists() and not context.exists()


def test_application_refuses_or_regenerates_corrupted_preview_cache(application, input_pdf, fast_validator, tmp_path, monkeypatch):
    identifier, view, report = imported(application, input_pdf, tmp_path)
    from pdf_remediator import process
    renders = []

    def named_inline_preview_worker(command, *args, **kwargs):
        renders.append(command)
        preview.render(Path(command[3]), command[command.index("--sha256") + 1], int(command[command.index("--page") + 1]),
                       Path(command[command.index("--png") + 1]), Path(command[command.index("--context") + 1]))
        return {"status": "completed"}

    monkeypatch.setattr(process, "run", named_inline_preview_worker)
    first = application.render_page(identifier, "original", 1)
    assert first.startswith(b"\x89PNG")
    cache = application.root / "page-cache" / (web.PREVIEW_PROFILE + "-" + view["source"]["sha256"] + "-1.png")
    cache.write_bytes(b"Unbound corrupted preview")
    try:
        result = application.render_page(identifier, "original", 1)
    except (ValueError, RuntimeError):
        return
    assert result.startswith(b"\x89PNG") and result != b"Unbound corrupted preview"
    assert len(renders) == 2


@pytest.mark.parametrize("path,status,expected", [
    (r"C:\inputs\reading-source.pdf", "candidate", "reading-source-candidate.pdf"),
    ("/inputs/reading-source.pdf", "needs-manual", "reading-source-review-draft.pdf"),
    ('/inputs/notes\r\nInjected: bad.pdf', "candidate", "notes-Injected-bad-candidate.pdf"),
])
def test_download_filename_keeps_source_identity_and_safe_header_bytes(path, status, expected):
    name = web.download_filename({"source": {"path": path}, "status": status})
    assert name == expected
    assert not any(character in name for character in '\r\n"/\\')


def failed_attempt(application, input_pdf, tmp_path, monkeypatch, ocr_mode='off', ocr_profile='standard'):
    # Reproduce the desktop's exact baseline blocker without invoking a native engine.
    with monkeypatch.context() as patch:
        from pdf_remediator import validation
        patch.setattr(validation, 'validate_pdf', lambda *a, **kw: {'status': 'error'})
        report = pipeline.process_file(input_pdf, tmp_path / 'failed', RuntimeConfig(
            project_root=tmp_path, title='Retry title', document_kind='reading',
            validator_cli=tmp_path/'missing-validator', ocr_mode=ocr_mode, ocr_profile=ocr_profile))
    assert report['status'] == 'failed'
    assert any('baseline validator did not assess' in item.get('description', '') for item in report['residual_issues'])
    identifier = application.import_bundle(report['bundle_path'])
    return identifier, application.view(identifier), report


@pytest.mark.parametrize("action", ["retry", "apply", "auto_fix"])
def test_historical_ocr_options_refuse_before_queue_or_export_and_preserve_review(
        application, input_pdf, fast_validator, tmp_path, monkeypatch, action):
    from pdf_remediator import ocr
    application.config.ocr_python = tmp_path / "not-included/python.exe"
    application.config.tesseract_dir = tmp_path / "not-included"
    config = RuntimeConfig(project_root=tmp_path, ocr_mode="redo", ocr_python=application.config.ocr_python,
                           tesseract_dir=application.config.tesseract_dir)

    def named_historical_ocr_test_stub(source, output, *args, **kwargs):
        # Author a coherent historical bundle without invoking any OCR engine.
        if action == "retry":
            return {"status": "error", "error": "Named historical OCR failure; no runtime was executed"}
        shutil.copyfile(source, output)
        return {"status": "completed", "preservation": {"status": "pass"},
                "scope": "Named identity-copy OCR test stub; no native process"}

    with monkeypatch.context() as patch:
        patch.setattr(ocr, "run_ocr", named_historical_ocr_test_stub)
        report = pipeline.process_file(input_pdf, tmp_path / "historical-ocr", config)
    assert report["settings"]["ocr_mode"] == "redo"
    assert report["status"] == ("failed" if action == "retry" else "candidate")
    identifier = application.import_bundle(report["bundle_path"])
    view = approved_title(application, identifier) if action == "apply" else application.view(identifier)
    state = application.state_path(identifier)
    before_state = state.read_bytes()
    bundle = Path(report["bundle_path"])
    before_bundle = {path.relative_to(bundle): path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
    before_source = input_pdf.read_bytes()
    monkeypatch.setattr(application, "submit", lambda *a, **kw: pytest.fail("Historical unavailable OCR was queued"))
    monkeypatch.setattr(workspace, "export_workspace", lambda *a, **kw: pytest.fail("Unavailable OCR created an export"))
    with pytest.raises(ValueError, match="OCR is not installed or configured"):
        getattr(application, action)(identifier, {"revision": view["revision"], "consent": True, "use_ai": False})
    assert not application.jobs and not list((application.root / "exports").iterdir())
    assert state.read_bytes() == before_state and input_pdf.read_bytes() == before_source
    assert before_bundle == {path.relative_to(bundle): path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
    assert json.loads((bundle / "report.json").read_text(encoding="utf-8"))["settings"]["ocr_mode"] == "redo"
    assert application.config.ocr_mode == "off"


def test_http_retry_preserves_failed_attempt_and_reruns_all_gates_with_current_runtime(
        http_app, input_pdf, fast_validator, tmp_path, monkeypatch):
    app = http_app[0]
    identifier, view, report = failed_attempt(app, input_pdf, tmp_path, monkeypatch)
    bundle = Path(report['bundle_path'])
    before = {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
    state_before = app.state_path(identifier).read_bytes()
    seen = []
    def processing(source, destination, config, cancel, progress, **kwargs):
        seen.append((config, kwargs))
        return pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, **kwargs)
    monkeypatch.setattr(web, 'process_isolated', processing)
    status, _, job = request(http_app, '/api/workspaces/'+identifier+'/retry', 'POST', {'revision': view['revision']})
    assert status == 202
    finished = wait_job(app, job['job_id'])
    assert finished['status'] == 'done', finished
    result_id = finished['result']['documents'][0]['workspace_id']
    result = app.view(result_id)
    assert result_id != identifier and result['status'] == 'candidate'
    assert result['counts']['manual_approved'] == 0 and result['verification'] == 'not-verified'
    assert seen[0][0].validator_cli == app.config.validator_cli
    assert seen[0][0].title == 'Retry title' and seen[0][0].document_kind == 'reading'
    assert seen[0][0].ocr_mode == 'off'
    assert seen[0][0].ocr_profile == 'standard'
    assert seen[0][1] == {'expected_source_sha256': view['source']['sha256']}
    assert [call['kind'] for call in fast_validator] == ['baseline', 'final']
    fresh_report = json.loads((Path(result['bundle_path'])/'report.json').read_text())
    assert fresh_report['gate1']['status'] == fresh_report['gate2']['status'] == fresh_report['fidelity']['status'] == 'pass'
    assert app.state_path(identifier).read_bytes() == state_before
    assert before == {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode,profile', [
    ('off', None), ('off', 'standard'), ('off', 'table-lines'), ('off', 'angles'),
    ('textless', 'standard'), ('textless', 'angles'),
])
def test_retry_keeps_saved_ocr_mode_and_layout_instead_of_current_service_default(
        application, input_pdf, tmp_path, monkeypatch, mode, profile):
    """Author bounded old/current settings; preserve both bundle and review."""
    original_public = RuntimeConfig.public
    def authored_saved_settings(config):
        settings = original_public(config)
        if profile is None:
            settings.pop('ocr_profile')
        return settings
    with monkeypatch.context() as prior:
        prior.setattr(RuntimeConfig, 'public', authored_saved_settings)
        identifier, view, report = failed_attempt(application, input_pdf, tmp_path, prior,
                                                 ocr_mode=mode, ocr_profile=profile or 'standard')
    bundle = Path(report['bundle_path'])
    before = {str(p): pipeline.sha(p) for p in bundle.rglob('*') if p.is_file()}
    state_before = application.state_path(identifier).read_bytes()
    application.config.ocr_profile = 'standard' if profile == 'angles' else 'angles'
    application.config.ocr_mode = 'redo' if mode == 'textless' else 'textless'
    configurations = []
    load = web.load_config
    def capture_config(**options):
        config = load(**options)
        configurations.append(config)
        return config
    monkeypatch.setattr(web, 'load_config', capture_config)
    presence_checks = []
    def named_presence_metadata_only(config):
        presence_checks.append((config.ocr_mode, config.ocr_profile))
        return {'available': True, 'runtime_verified': False, 'message': 'Named presence-only double; no native probe'}
    monkeypatch.setattr(web, 'ocr_availability', named_presence_metadata_only)
    monkeypatch.setattr(application, 'submit', lambda *a: {'job_id': 'named-queued-only-control'})
    application.retry(identifier, {'revision': view['revision']})
    assert configurations[-1].ocr_profile == (profile or 'standard')
    assert configurations[-1].ocr_mode == mode
    if mode != 'off':
        assert presence_checks == [(mode, profile or 'standard')]
    assert application.state_path(identifier).read_bytes() == state_before
    assert before == {str(p): pipeline.sha(p) for p in bundle.rglob('*') if p.is_file()}


@pytest.mark.parametrize('problem', ['revision', 'missing', 'changed', 'bundle'])
def test_retry_refuses_stale_revision_or_changed_evidence_before_processing(
        application, input_pdf, fast_validator, tmp_path, monkeypatch, problem):
    identifier, view, report = failed_attempt(application, input_pdf, tmp_path, monkeypatch)
    revision = view['revision']
    if problem == 'revision': revision -= 1
    elif problem == 'missing': input_pdf.unlink()
    elif problem == 'changed': input_pdf.write_bytes(input_pdf.read_bytes()+b'\nchanged')
    else: (Path(report['bundle_path'])/'report.json').write_text('{}')
    monkeypatch.setattr(application, 'submit', lambda *a: pytest.fail('Unsafe retry was queued'))
    with pytest.raises(ValueError):
        application.retry(identifier, {'revision': revision})


def test_retry_checks_review_revision_again_when_job_starts(application, input_pdf, fast_validator, tmp_path, monkeypatch):
    identifier, view, _ = failed_attempt(application, input_pdf, tmp_path, monkeypatch)
    pending = []
    monkeypatch.setattr(application, 'submit', lambda label, work: pending.append(work) or {'job_id': 'test'})
    application.retry(identifier, {'revision': view['revision']})
    input_pdf.unlink()
    monkeypatch.setattr(web, 'process_isolated', lambda *a, **kw: pytest.fail('Changed source reached processing'))
    with pytest.raises(workspace.RevisionConflict):
        pending[0](threading.Event(), lambda message: None, 'queued-retry')


def test_retry_does_not_replace_successful_candidate(application, input_pdf, fast_validator, tmp_path):
    identifier, view, _ = imported(application, input_pdf, tmp_path)
    with pytest.raises(ValueError, match='only for failed'):
        application.retry(identifier, {'revision': view['revision']})


@pytest.mark.parametrize('mismatch', ['legacy', 'implementation', 'settings'])
def test_launcher_refuses_live_outdated_session_without_replacing_it(http_app, tmp_path, monkeypatch, mismatch):
    from pdf_remediator import launcher
    app, server = http_app
    config = tmp_path/'local-runtime.toml'
    config.write_text('[runtime]\nproject_root = "'+tmp_path.as_posix()+'"\n')
    saved = {'url': server.origin+'/#'+app.token,
             'implementation_digest': pipeline.implementation_digest(app.config),
             'settings_digest': app.config.digest()}
    if mismatch == 'legacy':
        saved.pop('implementation_digest');saved.pop('settings_digest')
    else: saved[mismatch+'_digest'] = 'older-service'
    session = app.root/'.private-session.json'
    session.write_text(json.dumps(saved))
    before = session.read_bytes()
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Duplicate service started'))
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda *a: pytest.fail('Outdated service silently reopened'))
    with pytest.raises(RuntimeError, match='Stop application'):
        launcher.launch(app.root, config_path=config)
    assert session.read_bytes() == before
    assert request(http_app, '/api/dashboard')[0] == 200


def test_launcher_reopens_matching_authenticated_session(http_app, tmp_path, monkeypatch):
    from pdf_remediator import launcher
    app, server = http_app
    config = tmp_path/'local-runtime.toml'
    config.write_text('[runtime]\nproject_root = "'+tmp_path.as_posix()+'"\n')
    saved = {'url': server.origin+'/#'+app.token,
             'implementation_digest': pipeline.implementation_digest(app.config),
             'settings_digest': app.config.digest()}
    session = app.root/'.private-session.json'
    session.write_text(json.dumps(saved))
    opened = []
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Duplicate service started'))
    monkeypatch.setattr(launcher.webbrowser, 'open', opened.append)
    assert 'Reopened' in launcher.launch(app.root, config_path=config)
    assert opened == [saved['url']]


@pytest.mark.parametrize("accepted", [False, True])
def test_saved_edits_and_reported_problem_survive_service_reconstruction(
        input_pdf, fast_validator, tmp_path, accepted):
    config = RuntimeConfig(project_root=tmp_path)
    root = tmp_path/'saved-service'
    first = web.Application(root, config)
    try:
        identifier, view, _ = imported(first, input_pdf, tmp_path)
        original_hash = pipeline.sha(input_pdf)
        output_hash = pipeline.sha(Path(view['output']['path']))
        edited = workspace.edit_decision(first.state_path(identifier), 'metadata:title',
            'Saved synthetic title', view['revision'])
        if accepted:
            edited = workspace.approve_decision(first.state_path(identifier), 'metadata:title',
                'Synthetic Reviewer', '2026-10-18', edited['revision'])
        item = next(item for item in edited['manual_items'] if item['status'] == 'pending')
        saved = workspace.review_item(first.state_path(identifier), item['id'], 'blocked',
            'Synthetic Reviewer', '2026-10-18', edited['revision'], notes='Authored persistence test issue')
        before = first.state_path(identifier).read_bytes()
        old_token = first.token
    finally:
        first.close()
    second = web.Application(root, config)
    try:
        assert second.token != old_token
        restored = second.view(identifier)
        title = next(d for d in restored['decisions'] if d['id'] == 'metadata:title')
        assert title['value'] == 'Saved synthetic title' and title['human_touched']
        assert title['status'] == ('approved' if accepted else 'pending')
        if accepted: assert title['approved_by'] == 'Synthetic Reviewer'
        problem = next(d for d in restored['manual_items'] if d['id'] == item['id'])
        assert problem['status'] == 'blocked' and problem['notes'] == 'Authored persistence test issue'
        assert restored['revision'] == saved['revision'] and restored['verification'] == 'not-verified'
        assert second.state_path(identifier).read_bytes() == before
        assert pipeline.sha(input_pdf) == original_hash
        assert pipeline.sha(Path(restored['output']['path'])) == output_hash
        with pytest.raises(workspace.RevisionConflict):
            workspace.edit_decision(second.state_path(identifier), 'metadata:title', 'Stale overwrite', view['revision'])
        assert second.state_path(identifier).read_bytes() == before
    finally:
        second.close()


@pytest.mark.parametrize('changed_binding', ['source', 'prepared', 'output'])
def test_legacy_notes_survive_stale_refresh_and_application_reconstruction(
        tmp_path, monkeypatch, changed_binding):
    # These are authored PDF/bundle fixtures with synthetic gate records. This
    # exercises the real application and download dispatcher without a server,
    # browser, validator, worker, OCR recognition or provider request.
    from test_workspace import _make_bundle
    bundle, source, prepared, output, _ = _make_bundle(tmp_path / 'fixture')
    protected = list(bundle.iterdir()) + [source, prepared]
    hashes = {str(path): pipeline.sha(path) for path in protected}
    target = {'source': source, 'prepared': prepared, 'output': output}[changed_binding]
    original = target.read_bytes()
    config = RuntimeConfig(project_root=tmp_path)
    root = tmp_path / 'saved-legacy-service'
    expected_notes = {
        'reading-order': 'Reported problem in the original review must remain visible.',
        'contrast': 'Keep my unfinished contrast-review note.',
        'regroup-a': 'Historical positive observation; new bytes require new approval.',
    }
    first = web.Application(root, config)
    try:
        identifier = first.import_bundle(bundle)
        state = first.state_path(identifier)
        view = first.view(identifier)
        assert not workspace.load_workspace(state).get('source_lineage')
        view = workspace.approve_decision(state, 'metadata:title', 'Synthetic persistence reviewer',
            '2026-10-27', view['revision'])
        for item_id, status in [('reading-order', 'blocked'), ('contrast', 'pending'), ('regroup-a', 'approved')]:
            view = workspace.review_item(state, item_id, status, 'Synthetic persistence reviewer',
                '2026-10-27', view['revision'], expected_notes[item_id])
        before = state.read_bytes()
        before_history = view['history']
        assert view['counts']['manual_approved'] == view['counts']['manual_blocked'] == 1
        assert view['counts']['decision_approved'] == 1
        old_token = first.token
    finally:
        first.close()

    second = web.Application(root, config)
    try:
        assert second.token != old_token
        assert second.view(identifier) == view
        assert state.read_bytes() == before
        target.write_bytes(original + b'\n% Intentional stale-review regression fixture change\n')
        # Dashboard summaries are saved-state listings, not artifact checks.
        summary = second.dashboard()['documents'][0]
        assert summary['id'] == identifier and not summary['stale']
        assert summary['artifacts_checked'] is False and state.read_bytes() == before

        stale = second.view(identifier)
        items = {item['id']: item for item in stale['manual_items']}
        assert stale['stale'] and stale['status'] == 'needs-manual'
        assert stale['verification'] == 'not-verified'
        assert {key: items[key]['notes'] for key in expected_notes} == expected_notes
        assert items['reading-order']['status'] == 'blocked'
        assert items['contrast']['status'] == items['regroup-a']['status'] == 'pending'
        assert stale['counts']['manual_approved'] == stale['counts']['decision_approved'] == 0
        assert stale['counts']['manual_blocked'] == 1
        assert all('reviewer' not in items[key] and 'reviewed_at' not in items[key] for key in expected_notes)
        assert stale['history'][:-1] == before_history
        assert {entry['id']: entry['notes'] for entry in stale['history'][-1]['retained_manual_notes']} == expected_notes
        saved = workspace.load_workspace(state)
        assert saved['manual_approvals'] == {}
        assert all('approval_sha256' not in decision for decision in saved['sidecar']['decisions'])
        stale_bytes = state.read_bytes()
        assert second.view(identifier) == stale and state.read_bytes() == stale_bytes
        summary = second.dashboard()['documents'][0]
        assert summary['stale'] and summary['counts']['manual_blocked'] == 1
        assert summary['counts']['manual_approved'] == 0

        monkeypatch.setattr(second, 'submit', lambda *a, **kw: pytest.fail('A stale review was queued'))
        with pytest.raises(ValueError, match='reported problem'):
            second.apply(identifier, {'revision': stale['revision']})
        with pytest.raises(workspace.StaleWorkspace):
            workspace.export_workspace(state, root / 'exports' / 'refused', stale['revision'])
        with pytest.raises(workspace.StaleWorkspace):
            workspace.approve_decision(state, 'metadata:title', 'Synthetic persistence reviewer',
                '2026-10-27', stale['revision'])

        # Invoke the actual authenticated GET dispatcher in memory. Only the
        # response writer is replaced; download eligibility is production code.
        responses = []
        handler = object.__new__(web.Handler)
        handler.server = SimpleNamespace(application=second, origin='http://127.0.0.1:55555')
        handler.headers = {'Host': '127.0.0.1:55555', 'X-Review-Token': second.token}
        handler.command = 'GET'
        handler.path = '/api/workspaces/' + identifier + '/download'
        handler.respond = lambda status, body, *a, **kw: responses.append((status, body))
        handler.do_GET()
        assert responses == [(400, {'error': 'No current result is available for download.'})]
        assert state.read_bytes() == stale_bytes
        assert not second.jobs and not list((root / 'exports').iterdir())
        assert not list((root / 'runs').iterdir())
    finally:
        target.write_bytes(original)
        second.close()

    third = web.Application(root, config)
    try:
        reopened = third.view(identifier)
        assert reopened == stale and state.read_bytes() == stale_bytes
        assert reopened['stale'] and reopened['counts']['manual_approved'] == 0
        assert reopened['counts']['decision_approved'] == 0
        assert {item['id']: item['notes'] for item in reopened['manual_items']
                if item['id'] in expected_notes} == expected_notes
        assert {str(path): pipeline.sha(path) for path in protected} == hashes
        assert not third.jobs
    finally:
        third.close()


def test_http_cancelling_queued_work_never_invokes_its_operation(http_app):
    app = http_app[0]
    entered, release, invoked = threading.Event(), threading.Event(), threading.Event()
    def running(cancel, progress, identifier):
        entered.set()
        assert release.wait(3), 'Synthetic queue blocker timed out'
        return {'finished': True}
    def queued(cancel, progress, identifier):
        invoked.set()
        return {'unexpected_operation': True}
    first = app.submit('Synthetic running work', running)
    try:
        assert entered.wait(2)
        second = app.submit('Synthetic queued work', queued)
        assert request(http_app, '/api/jobs/'+second['job_id']+'/cancel', 'POST', {})[0] == 200
        release.set()
        assert wait_job(app, first['job_id'])['status'] == 'done'
        cancelled = wait_job(app, second['job_id'])
        assert cancelled['status'] == 'cancelled'
        assert not invoked.is_set() and cancelled['result'] is None
        assert not list((app.root/'runs').iterdir())
    finally:
        release.set()


def test_pre_cancelled_isolated_processing_never_starts_a_child(tmp_path, monkeypatch):
    cancelled = threading.Event();cancelled.set()
    monkeypatch.setattr(web.multiprocessing, 'get_context', lambda *a: pytest.fail('Cancelled work started a child context'))
    with pytest.raises(InterruptedError, match='cancelled'):
        web.process_isolated(tmp_path/'not-opened.pdf', tmp_path/'not-created', RuntimeConfig(), cancelled, lambda message: None)
    assert not (tmp_path/'not-created').exists()


def test_retry_cannot_turn_a_failed_read_only_check_into_pdf_modification(
        application, input_pdf, fast_validator, tmp_path, monkeypatch):
    cancelled = threading.Event();cancelled.set()
    report = pipeline.process_file(input_pdf, tmp_path/'read-only', application.config, mode='check', cancel=cancelled)
    assert report['status'] == 'failed' and report['mode'] == 'check'
    identifier = application.import_bundle(report['bundle_path'])
    view = application.view(identifier)
    original_hash = pipeline.sha(input_pdf)
    monkeypatch.setattr(application, 'submit', lambda *a: pytest.fail('A read-only check was queued as a modification'))
    with pytest.raises(ValueError, match='read-only'):
        application.retry(identifier, {'revision': view['revision']})
    assert pipeline.sha(input_pdf) == original_hash
    assert not application.jobs


def change_saved_review(app, identifier, change):
    view = app.view(identifier)
    if change == 'edit':
        return workspace.edit_decision(app.state_path(identifier), 'metadata:title',
            'Later protected human title', view['revision'])
    item = next(item for item in view['manual_items'] if item['status'] == 'pending')
    return workspace.review_item(app.state_path(identifier), item['id'], 'blocked',
        'Synthetic Reviewer', '2026-10-18', view['revision'], notes='Later authored problem report')


def test_apply_cannot_drop_an_existing_reported_problem(application, input_pdf, fast_validator, tmp_path, monkeypatch):
    identifier, _, _ = imported(application, input_pdf, tmp_path)
    approved_title(application, identifier)
    view = change_saved_review(application, identifier, 'problem')
    before = application.state_path(identifier).read_bytes()
    monkeypatch.setattr(application, 'submit', lambda *a: pytest.fail('Blocked review was submitted for application'))
    with pytest.raises(ValueError, match='reported problem'):
        application.apply(identifier, {'revision': view['revision']})
    assert application.state_path(identifier).read_bytes() == before
    assert not list((application.root/'exports').iterdir())


@pytest.mark.parametrize('accept_changed_value', [False, True])
def test_problem_then_decision_edit_still_refuses_apply_before_export_or_worker(
        application, tmp_path, monkeypatch, accept_changed_value):
    # Reuse the entirely synthetic bundle/state fixture; no pipeline, external
    # validator, HTTP service, provider or native worker is started in this case.
    from test_workspace import _make_bundle
    bundle, source, prepared, output, _ = _make_bundle(tmp_path)
    identifier = application.import_bundle(bundle)
    state = application.state_path(identifier)
    view = workspace.review_item(state, 'reading-order', 'blocked', 'Synthetic Test Reviewer',
        '2026-10-16', 0, 'Confirmed unrelated problem must survive editing the title.')
    original_problem = next(item for item in workspace.load_workspace(state)['manual_items']
                            if item['id'] == 'reading-order')
    paths = list(bundle.iterdir()) + [source, prepared]
    hashes = {str(path): pipeline.sha(path) for path in paths}
    view = workspace.edit_decision(state, 'metadata:title', 'Changed title after reporting a problem', view['revision'])
    if accept_changed_value:
        view = workspace.approve_decision(state, 'metadata:title', 'Synthetic Test Reviewer', '2026-10-16', view['revision'])
    before_apply = state.read_bytes()
    monkeypatch.setattr(application, 'submit', lambda *a, **kw: pytest.fail('Reported problem reached the worker queue'))
    monkeypatch.setattr(web, 'process_isolated', lambda *a, **kw: pytest.fail('Reported problem reached a native worker'))
    monkeypatch.setattr(workspace, 'export_workspace', lambda *a, **kw: pytest.fail('Reported problem reached export'))
    with pytest.raises(ValueError, match='reported problem'):
        application.apply(identifier, {'revision': view['revision']})
    assert state.read_bytes() == before_apply
    current = workspace.load_workspace(state)
    assert next(item for item in current['manual_items'] if item['id'] == 'reading-order') == original_problem
    assert application.view(identifier)['counts']['manual_blocked'] == 1
    assert not application.jobs and not list((application.root/'exports').iterdir())
    assert {str(path): pipeline.sha(path) for path in paths} == hashes


@pytest.mark.parametrize('change', ['edit', 'problem'])
def test_apply_rechecks_saved_review_after_waiting_in_queue(
        application, input_pdf, fast_validator, tmp_path, monkeypatch, change):
    identifier, _, _ = imported(application, input_pdf, tmp_path)
    view = approved_title(application, identifier)
    entered, release = threading.Event(), threading.Event()
    def barrier(cancel, progress, job):
        entered.set()
        assert release.wait(3)
    application.submit('Synthetic queue barrier', barrier)
    calls = []
    def inline_worker(source, destination, config, cancel, progress, **kwargs):
        calls.append(kwargs)
        return pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, **kwargs)
    monkeypatch.setattr(web, 'process_isolated', inline_worker)
    try:
        assert entered.wait(2)
        queued = application.apply(identifier, {'revision': view['revision']})
        changed = change_saved_review(application, identifier, change)
        before = application.state_path(identifier).read_bytes()
        release.set()
        finished = wait_job(application, queued['job_id'])
        assert finished['status'] == 'failed' and 'changed while waiting' in finished['error']
        assert application.state_path(identifier).read_bytes() == before
        assert application.view(identifier)['revision'] == changed['revision']
        assert not calls
        assert not list((application.root/'runs').iterdir())
        assert len(fast_validator) == 2
    finally:
        release.set()


@pytest.mark.parametrize('change', ['edit', 'problem'])
def test_apply_keeps_later_human_changes_and_does_not_switch_to_an_outdated_result(
        application, input_pdf, fast_validator, tmp_path, monkeypatch, change):
    identifier, original, _ = imported(application, input_pdf, tmp_path)
    view = approved_title(application, identifier)
    original_hash = pipeline.sha(original['output']['path'])
    completed, saved = [], []
    def inline_worker(source, destination, config, cancel, progress, **kwargs):
        report = pipeline.process_file(source, destination, config, cancel=cancel, progress=progress, **kwargs)
        assert report['status'] == 'candidate'
        assert report['gate1']['status'] == report['gate2']['status'] == report['fidelity']['status'] == 'pass'
        completed.append(report)
        change_saved_review(application, identifier, change)
        saved.append(application.state_path(identifier).read_bytes())
        return report
    monkeypatch.setattr(web, 'process_isolated', inline_worker)
    queued = application.apply(identifier, {'revision': view['revision']})
    finished = wait_job(application, queued['job_id'])
    assert finished['status'] == 'failed' and 'changed during' in finished['error']
    assert finished['result'] is None
    assert application.state_path(identifier).read_bytes() == saved[0]
    assert pipeline.sha(original['output']['path']) == original_hash
    assert pipeline.verify_bundle(completed[0]['bundle_path'])
    assert str(Path(completed[0]['bundle_path'])) in {item['path'] for item in application.catalog()['bundles']}
    assert len(list((application.root/'workspaces').glob('*/state.json'))) == 1
    latest = application.view(identifier)
    assert latest['verification'] == 'not-verified'
    assert latest['counts']['manual_blocked'] == (change == 'problem')
    if change == 'edit':
        title = next(d for d in latest['decisions'] if d['id'] == 'metadata:title')
        assert title['value'] == 'Later protected human title' and title['human_touched']


def test_dashboard_saved_summary_reads_no_artifacts_and_preserves_saved_choices(
        http_app, input_pdf, fast_validator, tmp_path, monkeypatch):
    app = http_app[0]
    identifier, initial, _ = imported(app, input_pdf, tmp_path)
    state_path = app.state_path(identifier)
    edited = workspace.edit_decision(state_path, 'metadata:title', 'Saved dashboard title', initial['revision'])
    item = next(item for item in edited['manual_items'] if item['status'] == 'pending')
    workspace.review_item(state_path, item['id'], 'blocked', 'Synthetic dashboard reviewer',
                          '2026-10-20', edited['revision'], notes='Saved dashboard problem note')
    before = state_path.read_bytes()
    saved = json.loads(before)

    def forbidden_expensive_operation(*args, **kwargs):
        pytest.fail('A dashboard summary invoked full review/artifact validation')

    real_read = workspace._read_json
    def read_only_state(path):
        assert Path(path) == state_path
        return real_read(path)

    monkeypatch.setattr(workspace, '_read_json', read_only_state)
    for name in ('_refresh', 'verify_bundle', 'file_sha256', 'collect_decisions', '_view', '_automatic_snapshot'):
        monkeypatch.setattr(workspace, name, forbidden_expensive_operation)
    monkeypatch.setattr(app, 'view', forbidden_expensive_operation)

    summary = workspace.get_saved_summary(state_path)
    status, _, dashboard = request(http_app, '/api/dashboard')
    assert status == 200 and len(dashboard['documents']) == 1
    row = dashboard['documents'][0]
    assert summary['artifacts_checked'] is row['artifacts_checked'] is False
    assert row['id'] == identifier and row['status'] == 'needs-manual'
    assert row['counts']['manual_pending'] == sum(item['status'] == 'pending' for item in saved['manual_items'])
    assert row['counts']['manual_blocked'] == 1 and row['counts']['manual_approved'] == 0
    assert 'manual_pending_actionable' not in row['counts'] and 'automated_count' not in row['counts']
    assert state_path.read_bytes() == before


def test_dashboard_saved_summary_does_not_wait_for_pdf_lock(
        http_app, input_pdf, fast_validator, tmp_path):
    app = http_app[0]
    identifier, _, _ = imported(app, input_pdf, tmp_path)
    locked, release = threading.Event(), threading.Event()

    def hold_pdf_lock():
        with app.pdf_lock:
            locked.set()
            release.wait(10)

    holder = threading.Thread(target=hold_pdf_lock, daemon=True)
    holder.start()
    try:
        assert locked.wait(2), 'Synthetic review lock was not acquired'
        status, _, dashboard = request(http_app, '/api/dashboard')
        assert status == 200 and dashboard['documents'][0]['id'] == identifier
        assert dashboard['documents'][0]['artifacts_checked'] is False
        assert holder.is_alive() and not release.is_set()
    finally:
        release.set()
        holder.join(timeout=2)
    assert not holder.is_alive()


@pytest.mark.parametrize('corruption', ['schema', 'checksum'])
def test_dashboard_corrupt_saved_state_requires_attention_without_overwriting_it(
        http_app, input_pdf, fast_validator, tmp_path, corruption):
    app = http_app[0]
    identifier, _, _ = imported(app, input_pdf, tmp_path)
    state_path = app.state_path(identifier)
    saved = json.loads(state_path.read_text(encoding='utf-8'))
    if corruption == 'schema':
        saved['schema_version'] = 'unrecognized-test-schema'
    else:
        saved['revision'] += 1
    state_path.write_text(json.dumps(saved), encoding='utf-8')
    corrupted = state_path.read_bytes()

    with pytest.raises(workspace.WorkspaceError):
        workspace.get_saved_summary(state_path)
    status, _, dashboard = request(http_app, '/api/dashboard')
    row = dashboard['documents'][0]
    assert status == 200 and row['id'] == identifier
    assert row['title'] == 'Review needs attention' and row['status'] == 'needs-manual'
    assert row['artifacts_checked'] is False and row['error']
    with pytest.raises(workspace.WorkspaceError):
        app.view(identifier)
    assert state_path.read_bytes() == corrupted


@pytest.mark.parametrize('binding', ['source', 'output', 'prepared'])
def test_saved_dashboard_does_not_authorize_tampered_artifacts_or_protected_actions(
        http_app, input_pdf, fast_validator, tmp_path, binding):
    app = http_app[0]
    identifier, original, _ = imported(app, input_pdf, tmp_path)
    state_path = app.state_path(identifier)
    before = state_path.read_bytes()
    artifact = Path(original[binding]['path'])
    artifact.write_bytes(artifact.read_bytes() + b'\n% Intentional dashboard regression fixture tamper\n')

    status, _, dashboard = request(http_app, '/api/dashboard')
    row = dashboard['documents'][0]
    assert status == 200 and row['artifacts_checked'] is False
    assert row['status'] == original['status']
    assert state_path.read_bytes() == before

    status, _, current = request(http_app, '/api/workspaces/' + identifier)
    assert status == 200 and current['stale'] is True and current['status'] == 'needs-manual'
    assert current['counts']['manual_approved'] == current['counts']['decision_approved'] == 0
    assert request(http_app, '/api/workspaces/' + identifier + '/download')[0] in (400, 409)
    payload = {'revision': current['revision']}
    assert request(http_app, '/api/workspaces/' + identifier + '/export', 'POST', payload)[0] in (400, 409)
    payload.update(id='metadata:title', reviewer='Synthetic dashboard reviewer', reviewed_at='2026-10-20')
    assert request(http_app, '/api/workspaces/' + identifier + '/approve', 'POST', payload)[0] in (400, 409)
    assert not list((app.root / 'exports').rglob('export.json'))


def test_authenticated_stop_logs_fixed_diagnostic_without_private_authority(http_app, capsys):
    assert request(http_app, '/api/stop', 'POST', {}, token=False)[0] == 403
    assert request(http_app, '/api/stop', 'POST', b'{}', headers={'Content-Type': 'text/plain'})[0] == 400
    assert 'Stop application requested' not in capsys.readouterr().out
    status, _, response = request(http_app, '/api/stop', 'POST', {})
    assert status == 200 and response['status'] == 'stopping'
    output = capsys.readouterr().out
    assert output.count('Stop application requested through authenticated local action.') == 1
    assert '+00:00 Stop application requested' in output
    assert http_app[0].token not in output and '/#' not in output


def _stop_handler_with_immediate_shutdown(monkeypatch, events, *, failure=None,
                                          body=b'{}', content_type='application/json', token=True):
    # Named socket-free transport doubles force shutdown to run immediately.
    # This tests the real parsing, authentication and response code without a
    # timing-dependent process exit; the real HTTP Stop test remains above.
    class NamedStopWriter(io.BytesIO):
        def __init__(self):
            super().__init__()
            self.failure = failure

        def write(self, raw):
            if raw == b'{"status": "stopping"}':
                events.append('ack-body')
                if self.failure == 'write':
                    raise BrokenPipeError('Synthetic disconnected Stop response')
            return super().write(raw)

        def flush(self):
            events.append('ack-flush')
            if self.failure == 'flush':
                self.failure = None
                raise OSError('Synthetic Stop response flush failure')
            return super().flush()

    class NamedImmediateShutdownThread:
        def __init__(self, target, *, daemon):
            self.target = target

        def start(self):
            self.target()

    class NamedReadConnection:
        timeout = 30

        def gettimeout(self):
            return self.timeout

        def settimeout(self, value):
            self.timeout = value

    monkeypatch.setattr(web.threading, 'Thread', NamedImmediateShutdownThread)
    handler = object.__new__(web.Handler)
    handler.server = SimpleNamespace(origin='http://127.0.0.1:49321',
        application=SimpleNamespace(token='synthetic-stop-authority'),
        shutdown=lambda: events.append('shutdown'))
    handler.path = '/api/stop'
    handler.command = 'POST'
    handler.requestline = 'POST /api/stop HTTP/1.1'
    handler.request_version = 'HTTP/1.1'
    handler.headers = {'Host': '127.0.0.1:49321', 'Origin': handler.server.origin,
        'Content-Type': content_type, 'Content-Length': str(len(body))}
    if token:
        handler.headers['X-Review-Token'] = handler.app.token
    handler.rfile = io.BytesIO(body)
    handler.wfile = NamedStopWriter()
    handler.connection = NamedReadConnection()
    return handler


def test_stop_acknowledgement_is_written_and_flushed_before_shutdown(monkeypatch):
    events = []
    handler = _stop_handler_with_immediate_shutdown(monkeypatch, events)
    handler.do_POST()
    assert handler.wfile.getvalue().startswith(b'HTTP/1.0 200 ')
    assert handler.wfile.getvalue().endswith(b'{"status": "stopping"}')
    assert events == ['ack-body', 'ack-flush', 'shutdown']


@pytest.mark.parametrize('failure', ['write', 'flush'])
def test_stop_disconnected_acknowledgement_still_shuts_down_without_second_response(monkeypatch, capsys, failure):
    events = []
    handler = _stop_handler_with_immediate_shutdown(monkeypatch, events, failure=failure)
    handler.do_POST()
    assert events.count('shutdown') == 1
    assert events.index('ack-body') < events.index('shutdown')
    assert b'HTTP/1.0 500 ' not in handler.wfile.getvalue()
    output = capsys.readouterr().out
    assert 'Stop acknowledgement could not be delivered; authenticated shutdown will continue.' in output
    assert handler.app.token not in output and '/#' not in output


@pytest.mark.parametrize('body,content_type,token,expected', [
    (b'{}', 'application/json', False, 403),
    (b'{', 'application/json', True, 400),
    (b'[]', 'application/json', True, 400),
    (b'{}', 'text/plain', True, 400),
])
def test_stop_bad_authority_or_unreadable_action_never_schedules_shutdown(monkeypatch, capsys, body, content_type, token, expected):
    events = []
    handler = _stop_handler_with_immediate_shutdown(monkeypatch, events,
        body=body, content_type=content_type, token=token)
    handler.do_POST()
    assert handler.wfile.getvalue().startswith(f'HTTP/1.0 {expected} '.encode())
    assert 'shutdown' not in events
    assert 'Stop application requested' not in capsys.readouterr().out


def test_service_closing_logs_fixed_diagnostic_without_private_authority(tmp_path, monkeypatch, capsys):
    actions = []

    class NamedSocketFreeServer:
        origin = 'http://127.0.0.1:49321'
        def __init__(self, application, port):
            assert port == 0
        def serve_forever(self, **kwargs):
            pass
        def server_close(self):
            actions.append('server-close')

    monkeypatch.setattr(web, 'ReviewServer', NamedSocketFreeServer)
    monkeypatch.setattr(pipeline, 'implementation_digest', lambda config: 'synthetic-startup-digest')
    private_session = tmp_path / 'private-session.json'
    web.serve(tmp_path / 'diagnostic-service', RuntimeConfig(project_root=tmp_path),
              open_browser=False, session_file=private_session)
    output = capsys.readouterr().out
    assert output.count('PDF Remediator service closing.') == 1 and '+00:00 PDF Remediator service closing.' in output
    assert json.loads(private_session.read_text(encoding='utf-8'))['url'] not in output
    assert '/#' not in output and actions == ['server-close']


def test_http_letter_dictionary_repair_needs_the_ocr_runtime_and_reaches_the_queue_alone(http_app, input_pdf, monkeypatch):
    """The page's tick-box sends repair_ocr_mappings: refused politely without the OCR components, queued (OCR mode off) with them."""
    app = http_app[0]; original = input_pdf.read_bytes(); queued = []; configs = []
    uploaded = app.upload(io.BytesIO(original), len(original), 'source.pdf')
    monkeypatch.setattr(app, 'submit', lambda label, work: queued.append(label) or {'job_id': 'named-not-executed-repair-job'})
    monkeypatch.setattr(web, 'ocr_availability', lambda config: {'available': False, 'runtime_verified': False, 'message': 'Named double: OCR components are missing'})
    status, _, body = request(http_app, '/api/process', 'POST', {'inputs': [uploaded['id']], 'options': {'repair_ocr_mappings': True}})
    assert status == 400 and 'OCR components are missing' in body['error'] and not queued
    load = web.load_config
    def capture(**options):
        config = load(**options); configs.append(config); return config
    monkeypatch.setattr(web, 'load_config', capture)
    monkeypatch.setattr(web, 'ocr_availability', lambda config: {'available': True, 'runtime_verified': False, 'message': 'Named presence-only double'})
    status, _, body = request(http_app, '/api/process', 'POST', {'inputs': [uploaded['id']], 'options': {'repair_ocr_mappings': True}})
    assert status == 202 and body == {'job_id': 'named-not-executed-repair-job'} and len(queued) == 1
    assert configs[-1].repair_ocr_mappings is True and configs[-1].ocr_mode == 'off' and configs[-1].repair_source_mappings is False
    assert app.config.repair_ocr_mappings is False, 'The service default is not changed by one request.'
    assert input_pdf.read_bytes() == original


@pytest.mark.parametrize('other', [{'ocr_mode': 'textless'}, {'repair_source_mappings': True}])
def test_http_letter_dictionary_repair_refuses_to_be_combined_before_the_queue(http_app, input_pdf, monkeypatch, other):
    app = http_app[0]; original = input_pdf.read_bytes()
    uploaded = app.upload(io.BytesIO(original), len(original), 'source.pdf')
    monkeypatch.setattr(app, 'submit', lambda *a: pytest.fail('A combined request was queued'))
    monkeypatch.setattr(web, 'ocr_availability', lambda config: {'available': True, 'runtime_verified': False, 'message': 'Named presence-only double'})
    status, _, body = request(http_app, '/api/process', 'POST', {'inputs': [uploaded['id']], 'options': {'repair_ocr_mappings': True, **other}})
    assert status == 400 and 'own operation' in body['error']
    assert not app.jobs and input_pdf.read_bytes() == original


def test_retry_keeps_the_saved_letter_dictionary_repair(application, input_pdf, tmp_path, monkeypatch):
    original_public = RuntimeConfig.public
    def saved_with_repair(config):
        settings = original_public(config); settings['repair_ocr_mappings'] = True
        return settings
    with monkeypatch.context() as prior:
        prior.setattr(RuntimeConfig, 'public', saved_with_repair)
        identifier, view, report = failed_attempt(application, input_pdf, tmp_path, prior)
    configurations = []
    load = web.load_config
    def capture(**options):
        config = load(**options); configurations.append(config); return config
    monkeypatch.setattr(web, 'load_config', capture)
    checks = []
    monkeypatch.setattr(web, 'ocr_availability', lambda config: checks.append(config.repair_ocr_mappings) or {'available': True, 'runtime_verified': False, 'message': 'Named presence-only double'})
    monkeypatch.setattr(application, 'submit', lambda *a: {'job_id': 'named-queued-only-control'})
    application.retry(identifier, {'revision': view['revision']})
    assert configurations[-1].repair_ocr_mappings is True and configurations[-1].ocr_mode == 'off'
    assert checks == [True], 'The OCR components are required again for the retried repair.'


def test_a_cancelled_job_that_ends_in_an_unrelated_error_reports_as_cancelled_without_the_technical_text(http_app):
    """Cancel can leave a half-made result whose import is refused ('stale evidence'); the person asked for the cancel, so no technical error is shown."""
    app = http_app[0]
    def cut_short(cancel, progress, identifier):
        cancel.set()
        from pdf_remediator.workspace import StaleWorkspace
        raise StaleWorkspace('Cannot import stale evidence: Prepared PDF decision occurrence context changed')
    job = wait_job(app, app.submit('Synthetic cut-short work', cut_short)['job_id'])
    assert job['status'] == 'cancelled' and job['error'] is None


def test_a_cancel_message_is_kept_and_an_ordinary_failure_keeps_its_error(http_app):
    app = http_app[0]
    def cancelled_with_message(cancel, progress, identifier):
        cancel.set()
        raise InterruptedError('Separate-copy processing was cancelled; retained evidence was not discarded.')
    def fails(cancel, progress, identifier):
        raise RuntimeError('An ordinary failure with its own reason')
    kept = wait_job(app, app.submit('Synthetic cancel message', cancelled_with_message)['job_id'])
    assert kept['status'] == 'cancelled' and kept['error'] == 'Separate-copy processing was cancelled; retained evidence was not discarded.'
    failed = wait_job(app, app.submit('Synthetic ordinary failure', fails)['job_id'])
    assert failed['status'] == 'failed' and failed['error'] == 'An ordinary failure with its own reason'

