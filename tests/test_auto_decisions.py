"""Explicit best-guess application never fabricates human semantic review.

PDF application/inspection are real. The pipeline integration uses the named
external-validator stub from test_pipeline and never invokes a model.
"""
import copy
import json
from pathlib import Path
import shutil

import pikepdf
import pytest

from pdf_remediator import inspection, pipeline
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.ledger import LedgerError, add_record
from pdf_remediator.sidecar import (DecisionError, apply_decisions, automatic_acceptance_valid,
    bind_approval, bind_automatic_acceptance, collect_decisions, decisions_digest,
    file_sha256, make_automatic_authorization, rebind_automatic_acceptance, write_sidecar)
from test_pipeline import input_pdf, fast_validator, tagged_control, generated_chapter
from test_review import make_pdf


@pytest.fixture
def document(tmp_path, generated_chapter):
    path = tmp_path / "prepared.pdf"
    shutil.copyfile(generated_chapter, path)
    return path


def authority(data, ids=None, ident="synthetic-best-guess-consent"):
    return make_automatic_authorization(data["source_sha256"], data["document_sha256"], "2026-10-16T15:00:00+00:00", ident,
        decision_ids=ids if ids is not None else [item["id"] for item in data["decisions"] if item["kind"] in {"title", "figure-description"}])


def origin(item):
    return {"schema_version": "phase2-ai-origin-1", "provider": "local-test-fixture",
            "model": "TEST STUB: no model inference", "context_sha256": item["context_sha256"],
            "request_context_sha256": "a" * 64}


def accept(item, auth, value="A bounded automatically selected title"):
    return bind_automatic_acceptance(item, value, auth, origin=origin(item))


def test_bound_best_guesses_apply_without_human_approval_and_preserve_appearance(document, tmp_path):
    data = collect_decisions(document)
    auth = authority(data)
    selected = [item for item in data["decisions"] if item["kind"] in {"title", "figure-description"}]
    for index, item in enumerate(selected):
        accept(item, auth, "A synthetic chapter title" if item["kind"] == "title" else f"Supported caption-context draft for figure occurrence {index}.")
        assert automatic_acceptance_valid(item, auth)
        assert not {"approved_by", "approved_at", "approval_sha256"}.intersection(item)
    before = document.read_bytes()
    destination = tmp_path / "automatic.pdf"
    result = apply_decisions(document, destination, data, data["source_sha256"], automatic_authorization=auth)
    assert result["approved"] == [] and result["auto_accepted"] == [item["id"] for item in selected]
    assert result["human_reviewed_automatic"] is False and result["automatic_authorization_sha256"] == decisions_digest(auth)
    assert document.read_bytes() == before
    assert inspection.compare_fidelity(document, destination)["status"] == "pass"
    actual = collect_decisions(destination)
    expected_values = {item["id"]: item["value"] for item in selected}
    assert actual["decisions"][0]["current"] == expected_values["metadata:title"]
    assert [item["current"] for item in actual["decisions"] if item["kind"] == "figure-description"] == [item["value"] for item in selected if item["kind"] == "figure-description"]


@pytest.mark.parametrize("mismatch", ["absent", "other-authorization", "source", "document", "scope", "human-review"])
def test_automatic_application_requires_explicit_exact_run_authority(document, tmp_path, mismatch):
    data = collect_decisions(document)
    auth = authority(data, ["metadata:title"])
    accept(data["decisions"][0], auth)
    supplied = copy.deepcopy(auth)
    if mismatch == "absent":
        supplied = None
    elif mismatch == "other-authorization":
        supplied["authorization_id"] = "another-consent"
    elif mismatch in {"source", "document"}:
        supplied[mismatch + "_sha256"] = "b" * 64
    elif mismatch == "scope":
        supplied["decision_ids"] = []
    else:
        supplied["human_reviewed"] = True
    output = tmp_path / "refused.pdf"
    with pytest.raises(DecisionError):
        apply_decisions(document, output, data, data["source_sha256"], automatic_authorization=supplied)
    assert not output.exists()


@pytest.mark.parametrize("protection", ["value-edit", "approved", "human-touched", "human-flag", "old-human-fields"])
def test_existing_human_values_and_approvals_win_without_mutation(document, protection):
    data = collect_decisions(document)
    item, auth = data["decisions"][0], authority(data, ["metadata:title"])
    if protection == "value-edit":
        item["value"] = "An existing human draft"
    elif protection == "approved":
        bind_approval(item, "Named human fixture reviewer", "2026-10-16")
    elif protection == "human-flag":
        item["human_touched"] = True
    elif protection == "old-human-fields":
        item["approved_by"] = "Previous human reviewer"
    before = copy.deepcopy(item)
    with pytest.raises(DecisionError, match="protected"):
        bind_automatic_acceptance(item, "AI must not replace this", auth, origin=origin(item), human_touched=protection == "human-touched")
    assert item == before


@pytest.mark.parametrize("tamper", ["value", "context", "binding", "origin", "embedded-authority", "digest", "kind", "human-fields"])
def test_automatic_value_context_and_origin_tampering_are_refused(document, tmp_path, tamper):
    data = collect_decisions(document)
    item, auth = data["decisions"][0], authority(data, ["metadata:title"])
    accept(item, auth)
    if tamper == "value":
        item["value"] = "Changed after automatic acceptance"
    elif tamper == "context":
        item["context_sha256"] = "b" * 64
    elif tamper == "binding":
        item["binding"]["document_sha256"] = "b" * 64
    elif tamper == "origin":
        item["automatic_application"]["origin"]["model"] = "A different model"
    elif tamper == "embedded-authority":
        item["automatic_application"]["authorization"]["authorization_id"] = "other"
    elif tamper == "digest":
        item["automatic_acceptance_sha256"] = "b" * 64
    elif tamper == "kind":
        item["kind"] = "language"
    else:
        item["approved_by"] = "Invented reviewer"
    assert not automatic_acceptance_valid(item, auth)
    output = tmp_path / "refused.pdf"
    with pytest.raises(DecisionError):
        apply_decisions(document, output, data, data["source_sha256"], automatic_authorization=auth)
    assert not output.exists()


def test_automatic_scope_cannot_authorize_language_or_unknown_decisions(document):
    data = collect_decisions(document)
    with pytest.raises(DecisionError):
        authority(data, ["metadata:language"])
    with pytest.raises(DecisionError):
        authority(data, ["metadata:title", "metadata:title"])
    auth = authority(data, ["metadata:title"])
    with pytest.raises(DecisionError, match="outside"):
        accept(data["decisions"][1], auth, "fr-CA")


def test_authorization_cannot_invent_an_occurrence_even_without_automatic_values(document, tmp_path):
    data = collect_decisions(document)
    auth = authority(data, ["figure:missing-occurrence"])
    output = tmp_path / "refused.pdf"
    with pytest.raises(DecisionError, match="absent decision"):
        apply_decisions(document, output, data, data["source_sha256"], automatic_authorization=auth)
    assert not output.exists()


def test_changed_prepared_bytes_refuse_automatic_authority(document, tmp_path):
    data = collect_decisions(document)
    auth = authority(data, ["metadata:title"])
    accept(data["decisions"][0], auth)
    with document.open("ab") as stream:
        stream.write(b"\n% changed prepared context\n")
    output = tmp_path / "refused.pdf"
    with pytest.raises(DecisionError, match="staged PDF"):
        apply_decisions(document, output, data, data["source_sha256"], automatic_authorization=auth)
    assert not output.exists()


def test_repeat_authorization_rebinds_only_intact_value_and_keeps_its_model_origin(document, tmp_path):
    data = collect_decisions(document)
    old_auth = authority(data, ["metadata:title"], "first-explicit-consent")
    item = accept(data["decisions"][0], old_auth)
    prior = copy.deepcopy(item)
    new_auth = authority(data, ["metadata:title"], "second-explicit-consent")
    rebind_automatic_acceptance(item, new_auth)
    assert automatic_acceptance_valid(item, new_auth) and not automatic_acceptance_valid(item, old_auth)
    assert {key: item[key] for key in ("id", "current", "value", "binding", "context_sha256", "ai_origin")} == {key: prior[key] for key in ("id", "current", "value", "binding", "context_sha256", "ai_origin")}
    assert item["automatic_application"]["origin"] == prior["automatic_application"]["origin"]
    assert prior["automatic_application"]["authorization"] == old_auth
    result = apply_decisions(document, tmp_path / "rebound.pdf", data, data["source_sha256"], automatic_authorization=new_auth)
    assert result["auto_accepted"] == [item["id"]] and result["approved"] == []


@pytest.mark.parametrize("defect", ["edited-value", "human-touched", "stale-document", "outside-scope"])
def test_rebinding_refuses_touched_stale_or_unauthorized_values_without_mutation(document, defect):
    data = collect_decisions(document)
    item = accept(data["decisions"][0], authority(data, ["metadata:title"]))
    auth = authority(data, ["metadata:title"], "new-consent")
    if defect == "edited-value":
        item["value"] = "Human edited this value"
    elif defect == "stale-document":
        auth["document_sha256"] = "b" * 64
    elif defect == "outside-scope":
        auth["decision_ids"] = []
    before = copy.deepcopy(item)
    with pytest.raises(DecisionError):
        rebind_automatic_acceptance(item, auth, human_touched=defect == "human-touched")
    assert item == before


def test_shared_figure_auto_guesses_must_all_agree_or_refuse(tmp_path):
    document = make_pdf(tmp_path / "shared.pdf", shared_element=True)
    data = collect_decisions(document)
    figures = [item for item in data["decisions"] if item["kind"] == "figure-description"]
    auth = authority(data, [item["id"] for item in figures])
    accept(figures[0], auth, "One shared description")
    with pytest.raises(DecisionError, match="shared Figure"):
        apply_decisions(document, tmp_path / "partial.pdf", data, data["source_sha256"], automatic_authorization=auth)
    accept(figures[1], auth, "A contradictory description")
    with pytest.raises(DecisionError, match="shared Figure"):
        apply_decisions(document, tmp_path / "contradictory.pdf", data, data["source_sha256"], automatic_authorization=auth)
    assert not (tmp_path / "partial.pdf").exists() and not (tmp_path / "contradictory.pdf").exists()


def test_pipeline_preserves_automatic_attribution_revalidates_and_cannot_verify(input_pdf, tmp_path, fast_validator):
    config = RuntimeConfig()
    first = pipeline.process_file(input_pdf, tmp_path / "first", config)
    data = json.loads((Path(first["bundle_path"]) / "decisions.json").read_text())
    title = next(item for item in data["decisions"] if item["kind"] == "title")
    auth = authority(data, [title["id"]])
    accept(title, auth, "An automatically selected synthetic reading title")
    sidecar = write_sidecar(data, tmp_path / "automatic.json")
    count_before = len(fast_validator)
    report = pipeline.process_file(input_pdf, tmp_path / "automatic", config, sidecar=sidecar,
        decision_bundle=first["bundle_path"], automatic_authorization=auth)
    assert report["status"] == "candidate" and len(fast_validator) == count_before + 2
    assert all(report[key]["status"] == "pass" for key in ("gate1", "gate2", "fidelity"))
    assert report["automatic_mode"]["human_reviewed"] is False
    assert report["automatic_mode"]["authorization_sha256"] == decisions_digest(auth)
    assert report["data_sent"]["document_api_calls"] == 0
    assert report["data_sent"]["prior_assistance"] == [{"decision_id": title["id"], "origin": origin(title)}]
    applied = next(processor for processor in report["processors"] if processor["name"] == "approved-decisions")
    assert applied["approved"] == [] and applied["auto_accepted"] == [title["id"]]
    pending = [item for item in report["manual_review"]["items"] if item["category"] == "automatic-decision-semantics"]
    assert len(pending) == 1 and pending[0]["status"] == "pending" and pending[0]["decision_id"] == title["id"]
    assert not report["manual_review"]["complete"] and pipeline.verify_bundle(report["bundle_path"])
    ledger_report = copy.deepcopy(report)
    for item in ledger_report["manual_review"]["items"]:
        if item["category"] != "automatic-decision-semantics":
            item.update(status="approved", reviewer="Explicit fixture human review only", reviewed_at="2026-10-16")
    with pytest.raises(LedgerError, match="Required human review remains: automatic-decision-"):
        add_record(tmp_path / "ledger.jsonl", report["output"]["path"], ledger_report, "Named fixture reviewer", "2026-10-16", 95,
            "Synthetic test context; no actual upload", review_scope="Test must not fabricate completed human review")
    assert not (tmp_path / "ledger.jsonl").exists()


def test_mechanical_only_authority_does_not_apply_pending_text_or_claim_review(input_pdf, tmp_path, fast_validator):
    config = RuntimeConfig()
    first = pipeline.process_file(input_pdf, tmp_path / "first", config)
    data = json.loads((Path(first["bundle_path"]) / "decisions.json").read_text())
    auth = authority(data, [])
    sidecar = write_sidecar(data, tmp_path / "mechanical-only.json")
    report = pipeline.process_file(input_pdf, tmp_path / "mechanical", config, sidecar=sidecar,
        decision_bundle=first["bundle_path"], automatic_authorization=auth)
    assert report["status"] == "candidate" and report["automatic_mode"]["authorization"]["decision_ids"] == []
    applied = next(processor for processor in report["processors"] if processor["name"] == "approved-decisions")
    assert applied["changed"] == [] and applied["approved"] == [] and applied["auto_accepted"] == []
    assert all(item["status"] == "pending" for item in report["manual_review"]["items"])
    assert not report["manual_review"]["complete"]
