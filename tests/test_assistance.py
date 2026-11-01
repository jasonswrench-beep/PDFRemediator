"""Local provider contract/security tests. Fixture responses are not model quality.

PDF inputs are generated synthetic occurrence controls, not native evidence.
The HTTP fixture implements the provider protocol only; it is not an LLM.
"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time

import pikepdf
import pytest

from pdf_remediator import assistance
from pdf_remediator.sidecar import bind_approval, collect_decisions

from test_pipeline import generated_chapter


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def manifest(bundle):
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.iterdir() if p.name != "manifest.json" and p.is_file()}
    write_json(bundle / "manifest.json", {"complete": True, "run_fingerprint": "fixture-run", "files": files})


@pytest.fixture
def bundle(tmp_path, generated_chapter):
    directory = tmp_path / "bundle"
    directory.mkdir()
    prepared = directory / "prepared.pdf"
    # Keep source and prepared hashes distinct, as in a real preparation flow.
    # This only removes synthetic tags; it does not claim native engine output.
    source = tmp_path / "source.pdf"
    with pikepdf.open(generated_chapter) as pdf:
        del pdf.Root.StructTreeRoot
        del pdf.Root.MarkInfo
        for page in pdf.pages:
            del page.obj.StructParents
            del page.obj.Tabs
        pdf.save(source, deterministic_id=True)
    shutil.copyfile(generated_chapter, prepared)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    decisions = collect_decisions(prepared, source_sha)
    write_json(directory / "decisions.json", decisions)
    write_json(directory / "report.json", {"status": "needs-manual", "mode": "fix", "run_fingerprint": "fixture-run", "output": None,
        "input": {"path": str(source), "sha256": source_sha},
        "decision_source": {"path": str(prepared), "sha256": decisions["document_sha256"]}})
    write_json(directory / "review.json", {"items": []})
    (directory / "review.html").write_text("Explicit fixture bundle; no processing claim.", encoding="utf-8")
    manifest(directory)
    return directory


@pytest.fixture
def provider():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, payload, status=200):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.server.calls.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
            if self.server.mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "https://example.org/must-not-connect")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send({"data": [{"id": "fixture-model", "created": self.server.revision, "owned_by": "local-contract-fixture"}]})

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.server.calls.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "request": request})
            if self.server.mode == "http-error":
                self.send({"error": "secret-provider-detail-must-not-be-logged"}, status=500)
                return
            if self.server.mode == "slow":
                time.sleep(1)
            if self.server.mode == "oversize":
                self.send(b"x" * 10000)
                return
            user = request["messages"][1]["content"]
            document = json.loads(user[0]["text"] if isinstance(user, list) else user)
            values = []
            for item in document["items"]:
                caption = item.get("caption_context", "").lower()
                value = "A test reading title" if item["kind"] == "title" else "Draft for archive bins; visually review the supplied crop." if "archive" in caption else "Draft for garden plots; visually review the supplied crop."
                values.append({"id": item["id"], "kind": item["kind"], "value": value})
            if self.server.mode == "unknown-id":
                values[0]["id"] = "invented-id"
            elif self.server.mode == "wrong-kind":
                values[0]["kind"] = "language"
            elif self.server.mode == "object-value":
                values[0]["value"] = {"command": "write PDF"}
            elif self.server.mode == "approval":
                values[0]["approved_by"] = "Model"
            elif self.server.mode == "duplicate":
                values.append(values[0])
            content = json.dumps({"suggestions": values})
            if self.server.mode == "duplicate-field":
                content = '{"suggestions": [], "suggestions": ' + json.dumps(values) + '}'
            payload = {"model": "fixture-model", "choices": [{"finish_reason": "length" if self.server.mode == "truncated" else "stop", "message": {"role": "assistant", "content": content}}]}
            if self.server.mode == "tool-call":
                payload["choices"][0]["message"]["tool_calls"] = [{"function": {"name": "write_pdf"}}]
            self.send(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.calls, server.mode, server.revision = [], "normal", 1
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def sidecar(bundle):
    return json.loads((bundle / "decisions.json").read_text(encoding="utf-8"))


def test_generated_source_and_prepared_retain_distinct_bindings_and_appearance(bundle):
    from pdf_remediator.inspection import compare_fidelity

    report = json.loads((bundle / "report.json").read_text(encoding="utf-8"))
    source = Path(report["input"]["path"])
    prepared = bundle / "prepared.pdf"
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    prepared_sha = hashlib.sha256(prepared.read_bytes()).hexdigest()
    assert source_sha != prepared_sha
    assert report["input"]["sha256"] == source_sha
    assert report["decision_source"]["sha256"] == prepared_sha
    assert sidecar(bundle)["source_sha256"] == source_sha
    assert sidecar(bundle)["document_sha256"] == prepared_sha
    with pikepdf.open(source) as pdf:
        assert "/StructTreeRoot" not in pdf.Root
    with pikepdf.open(prepared) as pdf:
        assert "/StructTreeRoot" in pdf.Root
    assert compare_fidelity(source, prepared)["status"] == "pass"


def test_context_has_real_bounded_crops_and_separate_caption_occurrences(bundle, monkeypatch):
    before = hashlib.sha256((bundle / "prepared.pdf").read_bytes()).hexdigest()
    monkeypatch.setattr(assistance, "_http", lambda *args, **kwargs: pytest.fail("Context extraction must not connect to a provider"))
    result = assistance.build_context(bundle)
    figures = [item for item in result["items"] if item["kind"] == "figure-description"]
    assert len(figures) == 2
    assert all(item["image_status"] == "included-safe-crop" for item in figures)
    assert all(item["image"]["bytes"] <= assistance.MAX_IMAGE_BYTES for item in figures)
    assert all(max(item["image"]["pixels"]) <= 512 for item in figures)
    assert "garden" in figures[0]["caption_context"].lower()
    assert "archive" in figures[1]["caption_context"].lower()
    assert figures[0]["request_context_sha256"] != figures[1]["request_context_sha256"]
    assert result["no_pdf_writes"] is True
    assert hashlib.sha256((bundle / "prepared.pdf").read_bytes()).hexdigest() == before


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://192.168.1.2/v1", "http://example.org/v1", "http://127.0.0.1.evil.test/v1", "http://user:secret@127.0.0.1/v1", "http://127.0.0.1/v1?api_key=secret", "http://127.0.0.1:0/v1", "http://127.1/v1", "http://127.0.0.1/v1#secret", "file:///etc/passwd"])
def test_nonloopback_credentials_and_ambiguous_endpoints_are_rejected(url):
    with pytest.raises(assistance.AssistanceError):
        assistance._endpoint(url)


def test_localhost_is_pinned_to_literal_address_without_dns():
    assert assistance._endpoint("http://localhost:1234/v1/chat/completions")["url"] == "http://127.0.0.1:1234/v1"
    assert assistance._endpoint("http://[::1]:1234/v1")["address"] == "::1"


def test_unknown_or_unsupported_inventory_ids_are_rejected_before_connection(bundle):
    for selected in (["unknown"], ["metadata:language"], ["metadata:title", "metadata:title"]):
        with pytest.raises(assistance.AssistanceError):
            assistance.build_context(bundle, selected)


def test_changed_prepared_checkpoint_or_bundle_is_refused(bundle):
    with (bundle / "prepared.pdf").open("ab") as stream:
        stream.write(b"\n% changed\n")
    with pytest.raises(assistance.AssistanceError):
        assistance.build_context(bundle)


@pytest.mark.parametrize("change", ["changed", "missing", "missing-path"])
def test_stale_original_source_is_refused_before_any_provider_request(bundle, tmp_path, monkeypatch, change):
    report = json.loads((bundle / "report.json").read_text(encoding="utf-8"))
    source_copy = tmp_path / "original.pdf"
    shutil.copyfile(report["input"]["path"], source_copy)
    report["input"]["path"] = str(source_copy)
    if change == "changed":
        with source_copy.open("ab") as stream:
            stream.write(b"\n% changed original source\n")
    elif change == "missing":
        source_copy.unlink()
    else:
        del report["input"]["path"]
    write_json(bundle / "report.json", report)
    manifest(bundle)
    requests = []

    def refuse_request(*args, **kwargs):
        requests.append((args, kwargs))
        pytest.fail("A stale original source must be refused before model inventory or document requests")

    monkeypatch.setattr(assistance, "_http", refuse_request)
    with pytest.raises(assistance.AssistanceError, match="original source"):
        assistance.suggest(bundle, "http://127.0.0.1:11434/v1", "fixture-model", ["metadata:title"], cache_dir=tmp_path / "cache")
    assert requests == []
    assert not (tmp_path / "cache").exists()


def test_live_contract_drafts_bound_values_no_approval_and_contextual_figures(bundle, provider):
    result = assistance.suggest(bundle, provider.url, "fixture-model")
    assert result["status"] == "draft", result.get("error")
    assert len(result["suggestions"]) == 3
    assert result["data_sent"]["document_requests"] == 1 and result["data_sent"]["images"] == 2
    checked = assistance.validate_suggestions(sidecar(bundle), result)
    assert all(item["status"] == "draft" and "approval_sha256" not in item for item in checked)
    assert all(item["binding"]["document_sha256"] == result["document_sha256"] for item in checked)
    assert all(item["provenance"]["provider"] == "local-openai-compatible" for item in checked)
    assert all(item["provenance"]["cache_key"] == result["cache"]["key"] for item in checked)
    assert "garden" in checked[1]["value"] and "archive" in checked[2]["value"]
    assert all(call["path"] in ("/v1/models", "/v1/chat/completions") for call in provider.calls)


def test_proxy_environment_and_keys_are_not_used_or_serialized(bundle, provider, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://user:must-never-appear@198.51.100.1:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:must-never-appear@198.51.100.1:9999")
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-appear")
    result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], include_images=False)
    assert result["status"] == "draft", result.get("error")
    assert "must-never-appear" not in json.dumps(result)
    assert all("Authorization" not in call["headers"] and "Proxy-Authorization" not in call["headers"] for call in provider.calls)


def test_redirect_is_not_followed_and_no_document_is_sent(bundle, provider):
    provider.mode = "redirect"
    result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"])
    assert result["status"] == "error"
    assert "redirect" in result["error"].lower()
    assert len(provider.calls) == 1 and provider.calls[0]["method"] == "GET"
    assert result["data_sent"]["document_requests"] == 0


@pytest.mark.parametrize("mode", ["unknown-id", "wrong-kind", "object-value", "approval", "duplicate", "duplicate-field", "truncated", "tool-call", "oversize"])
def test_untrusted_model_output_is_rejected_as_a_whole(bundle, provider, mode):
    provider.mode = mode
    result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], max_response_bytes=2048)
    assert result["status"] == "error"
    assert result["suggestions"] == []
    assert result["human_review_pending"] is True


def test_request_timeout_and_precancellation_are_bounded(bundle, provider):
    provider.mode = "slow"
    started = time.monotonic()
    result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], timeout_seconds=.25)
    assert result["status"] == "error"
    assert time.monotonic() - started < 2
    before = len(provider.calls)
    cancel = threading.Event()
    cancel.set()
    result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cancel=cancel)
    assert result["status"] == "cancelled"
    assert len(provider.calls) == before


def test_active_cancellation_does_not_apply_or_cache_a_partial_response(bundle, provider, tmp_path):
    provider.mode = "slow"
    cancel = threading.Event()
    timer = threading.Timer(.15, cancel.set)
    timer.start()
    try:
        result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=tmp_path / "cache", cancel=cancel)
    finally:
        timer.cancel()
    assert result["status"] == "cancelled"
    assert result["suggestions"] == []
    assert not list((tmp_path / "cache").glob("*.json"))


def test_provider_error_body_is_not_copied_to_evidence(bundle, provider):
    provider.mode = "http-error"
    result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"])
    assert result["status"] == "error"
    assert "secret-provider-detail" not in json.dumps(result)


def test_caption_only_choice_discloses_that_no_image_was_sent(bundle, provider):
    ids = [item["id"] for item in sidecar(bundle)["decisions"] if item["kind"] == "figure-description"]
    result = assistance.suggest(bundle, provider.url, "fixture-model", ids, include_images=False)
    assert result["status"] == "draft"
    assert result["data_sent"]["images"] == 0
    request = next(call["request"] for call in provider.calls if call["method"] == "POST")
    assert all(item["image_status"] == "not-sent-caption-only-request" for item in json.loads(request["messages"][1]["content"])["items"])


def test_corrupted_cached_provenance_is_invalidated_and_not_silently_reused(bundle, provider, tmp_path):
    cache = tmp_path / "cache"
    first = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=cache)
    path = cache / (first["cache"]["key"] + ".json")
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["envelope"]["suggestions"][0]["provenance"]["cache_key"] = "wrong-request"
    # Even an internally consistent JSON wrapper cannot change request lineage.
    saved["sha256"] = assistance._digest(saved["envelope"])
    write_json(path, saved)
    result = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=cache)
    assert result["status"] == "draft"
    assert result["cache"]["hit"] is False and result["cache"]["invalidated"] is True
    assert result["suggestions"][0]["provenance"]["cache_key"] == result["cache"]["key"]
    assert len([call for call in provider.calls if call["method"] == "POST"]) == 2


def test_cache_reuses_only_exact_context_model_metadata_and_settings(bundle, provider, tmp_path):
    cache = tmp_path / "cache"
    first = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=cache)
    assert first["status"] == "draft"
    second = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=cache)
    assert second["cache"]["hit"] is True
    assert second["data_sent"]["document_requests"] == 0
    assert len([x for x in provider.calls if x["method"] == "POST"]) == 1
    provider.revision += 1
    changed_model = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=cache)
    assert changed_model["cache"]["hit"] is False
    assert changed_model["cache"]["key"] != first["cache"]["key"]
    changed_settings = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=cache, max_tokens=1200)
    assert changed_settings["cache"]["key"] != changed_model["cache"]["key"]
    decision = sidecar(bundle)
    decision["decisions"][0]["value"] = "An explicit pending human edit"
    write_json(bundle / "decisions.json", decision)
    manifest(bundle)
    changed_context = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"], cache_dir=cache)
    assert changed_context["cache"]["key"] != changed_model["cache"]["key"]


def test_human_edits_and_approvals_win_and_draft_adoption_remains_pending(bundle, provider):
    envelope = assistance.suggest(bundle, provider.url, "fixture-model")
    original = sidecar(bundle)
    edited = deepcopy(original)
    edited["decisions"][0]["value"] = "A human title edit"
    figure = next(item for item in edited["decisions"] if item["kind"] == "figure-description")
    figure["value"] = "A human approved figure description"
    bind_approval(figure, "Human Reviewer", "2026-10-16")
    approved_bytes = json.dumps(figure, sort_keys=True)
    merged = assistance.merge_drafts(edited, envelope)
    assert merged["decisions"][0]["value"] == "A human title edit"
    assert json.dumps(next(item for item in merged["decisions"] if item["id"] == figure["id"]), sort_keys=True) == approved_bytes
    other = [item for item in merged["decisions"] if item["kind"] == "figure-description" and item["id"] != figure["id"]][0]
    assert other["status"] == "pending" and "ai_draft" in other
    assert "approval_sha256" not in other
    assert original == sidecar(bundle)


def test_unavailable_model_is_not_downloaded_or_replaced(bundle, provider):
    result = assistance.suggest(bundle, provider.url, "not-installed", ["metadata:title"])
    assert result["status"] == "error"
    assert len(provider.calls) == 1
    assert result["suggestions"] == []


def test_document_prompt_instructions_are_quoted_evidence_not_system_commands(bundle, provider):
    values = sidecar(bundle)
    # This is an untrusted existing metadata value in the fixture, not an instruction.
    # The schema/binding checks reject attempts to invent new decision operations.
    context = assistance.build_context(bundle, ["metadata:title"])
    encoded, summary = assistance._request(context, "fixture-model", False, 512)
    request = json.loads(encoded)
    assert request["messages"][0]["role"] == "system"
    assert "untrusted quoted evidence" in request["messages"][0]["content"]
    assert json.loads(request["messages"][1]["content"])["items"][0]["id"] == "metadata:title"
    assert "tools" not in request


@pytest.mark.parametrize("change", ["source", "document", "context", "approval"])
def test_stale_or_forged_drafts_cannot_be_adopted(bundle, provider, change):
    envelope = assistance.suggest(bundle, provider.url, "fixture-model", ["metadata:title"])
    if change == "source":
        envelope["source_sha256"] = "0" * 64
    elif change == "document":
        envelope["document_sha256"] = "0" * 64
    elif change == "context":
        envelope["suggestions"][0]["context_sha256"] = "0" * 64
    else:
        envelope["suggestions"][0]["approved_by"] = "Model"
    with pytest.raises(assistance.AssistanceError):
        assistance.merge_drafts(sidecar(bundle), envelope)
