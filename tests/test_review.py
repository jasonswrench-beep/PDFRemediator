"""Review decisions and verification must become invalid when evidence changes."""
import copy
import json
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator.ledger import (LedgerError, add_record, export_ledger,
                                   invalidate_record, list_records)
from pdf_remediator.review import render_review_packet
from pdf_remediator.sidecar import (DecisionError, apply_decisions, bind_approval,
                                    collect_decisions, file_sha256, load_sidecar,
                                    write_sidecar)


def make_pdf(path, shared_element=False):
    with pikepdf.Pdf.new() as pdf:
        pages = [pdf.add_blank_page(), pdf.add_blank_page()]
        for page in pages:
            page.obj["/Contents"] = pdf.make_stream(b"/Figure <</MCID 0>> BDC\n0 0 20 20 re f\nEMC\n")
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        children = []
        if shared_element:
            markers = [pikepdf.Dictionary(Type=pikepdf.Name.MCR, Pg=page.obj, MCID=0) for page in pages]
            children.append(pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                            S=pikepdf.Name.Figure, P=tree, K=pikepdf.Array(markers))))
        else:
            for index, page in enumerate(pages):
                children.append(pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                                S=pikepdf.Name.Figure, P=tree, Pg=page.obj, K=0, T=f"Context {index + 1}")))
        tree["/K"] = pikepdf.Array(children)
        pdf.Root["/StructTreeRoot"] = tree
        pdf.Root["/Lang"] = "en-US"
        pdf.docinfo["/Title"] = "Existing document title"
        pdf.save(path, deterministic_id=True)
    return path


@pytest.fixture
def document(tmp_path):
    return make_pdf(tmp_path / "input.pdf")


def approve(item, value):
    item["value"] = value
    return bind_approval(item, "Human Reviewer", "2026-10-15")


def report_for(path):
    sha = file_sha256(path)
    item = {"id": "reading-order", "kind": "reading-order", "required": True,
            "status": "approved", "reviewer": "Human Reviewer", "reviewed_at": "2026-10-15"}
    return {"status": "candidate", "run_id": "test-run", "output": {"sha256": sha, "path": str(path)},
            "gate1": {"status": "pass", "profile": "ua1", "is_compliant": True,
                      "counts": {"failedRules": 0, "failedChecks": 0, "passedRules": 106},
                      "execution": {"status": "completed", "returncode": 0}, "input_sha256": sha},
            "gate2": {"status": "pass", "blockers": [],
                      "checks": [{"id": "coverage", "status": "pass", "blocking": True}],
                      "manual_queue": [{"id": "reading-order", "required": True}]},
            "fidelity": {"status": "pass", "after_sha256": sha},
            "manual_review": {"items": [item], "complete": True}, "residual_issues": []}


def record(path, ledger, report=None, **kwargs):
    arguments = {"reviewer": "Human Reviewer", "reviewed_at": "2026-10-15", "checker_score": 91,
                 "checker_context": "University LMS course; actual uploaded candidate", "threshold": 67,
                 "review_scope": "All pages visually; full document reading order through accessibility interface"}
    arguments.update(kwargs)
    return add_record(ledger, path, report or report_for(path), **arguments)


def test_inventory_uses_occurrences_and_does_not_invent_alternatives(document):
    data = collect_decisions(document)
    figures = [item for item in data["decisions"] if item["kind"] == "figure-description"]
    assert len(figures) == 2
    assert {item["page"] for item in figures} == {1, 2}
    assert len({item["context_sha256"] for item in figures}) == 2
    assert len({item["id"] for item in figures}) == 2
    assert all(item["value"] == "" and item["status"] == "pending" for item in figures)
    assert data["decisions"][0]["value"] == "Existing document title"


def test_pending_values_are_not_applied_and_bytes_are_preserved(document, tmp_path):
    data = collect_decisions(document)
    data["decisions"][0]["value"] = "Unapproved replacement"
    destination = tmp_path / "pending.pdf"
    outcome = apply_decisions(document, destination, data, file_sha256(document))
    assert destination.read_bytes() == document.read_bytes()
    assert not outcome["changed"]
    assert len(outcome["pending"]) == 4


def test_explicit_metadata_and_context_specific_descriptions_apply(document, tmp_path):
    data = collect_decisions(document)
    approve(data["decisions"][0], "Human selected title")
    approve(data["decisions"][1], "fr-CA")
    approve(data["decisions"][2], "Diagram under the first caption")
    approve(data["decisions"][3], "Diagram under a different caption")
    original_sha = file_sha256(document)
    destination = tmp_path / "approved.pdf"
    outcome = apply_decisions(document, destination, data, original_sha)
    assert len(outcome["changed"]) == 4
    assert file_sha256(document) == original_sha
    with pikepdf.open(destination) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Human selected title"
        assert str(pdf.Root["/Lang"]) == "fr-CA"
        children = pdf.Root["/StructTreeRoot"]["/K"]
        assert str(children[0]["/Alt"]) == "Diagram under the first caption"
        assert str(children[1]["/Alt"]) == "Diagram under a different caption"
        with pdf.open_metadata() as metadata:
            assert metadata["dc:title"] == "Human selected title"


@pytest.mark.parametrize("changed", ["source", "document", "value", "context", "binding", "reviewer", "date", "delete", "duplicate"])
def test_stale_or_incomplete_sidecar_is_refused_without_output(document, tmp_path, changed):
    data = collect_decisions(document)
    approve(data["decisions"][0], "An approved title")
    if changed == "source":
        data["source_sha256"] = "b" * 64
    elif changed == "document":
        data["document_sha256"] = "b" * 64
    elif changed == "value":
        data["decisions"][0]["value"] = "Edited after approval"
    elif changed == "context":
        data["decisions"][2]["context_sha256"] = "b" * 64
    elif changed == "binding":
        data["decisions"][0]["binding"]["source_sha256"] = "b" * 64
    elif changed == "reviewer":
        data["decisions"][0]["approved_by"] = "A different reviewer"
    elif changed == "date":
        data["decisions"][0]["approved_at"] = "2026-10-16"
    elif changed == "delete":
        data["decisions"].pop()
    elif changed == "duplicate":
        data["decisions"].append(data["decisions"][0])
    output = tmp_path / "must-not-exist.pdf"
    with pytest.raises(DecisionError):
        apply_decisions(document, output, data, file_sha256(document))
    assert not output.exists()


def test_changed_pdf_bytes_invalidate_sidecar(document, tmp_path):
    data = collect_decisions(document)
    original_sha = file_sha256(document)
    with document.open("ab") as stream:
        stream.write(b"\n% PDF bytes changed\n")
    with pytest.raises(DecisionError, match="staged PDF"):
        apply_decisions(document, tmp_path / "stale.pdf", data, original_sha)


def test_shared_figure_element_refuses_partial_or_conflicting_occurrence_approval(tmp_path):
    path = make_pdf(tmp_path / "shared.pdf", shared_element=True)
    data = collect_decisions(path)
    figures = data["decisions"][2:]
    assert len(figures) == 2 and figures[0]["element"] == figures[1]["element"]
    approve(figures[0], "One description")
    with pytest.raises(DecisionError, match="shared Figure"):
        apply_decisions(path, tmp_path / "partial.pdf", data, file_sha256(path))
    approve(figures[1], "A contradictory description")
    with pytest.raises(DecisionError, match="shared Figure"):
        apply_decisions(path, tmp_path / "contradictory.pdf", data, file_sha256(path))
    approve(figures[1], "One description")
    outcome = apply_decisions(path, tmp_path / "all-approved.pdf", data, file_sha256(path))
    assert len(outcome["approved"]) == 2


def test_decisions_never_overwrite_input_or_existing_output(document, tmp_path):
    data = collect_decisions(document)
    with pytest.raises(DecisionError, match="separate"):
        apply_decisions(document, document, data, file_sha256(document))
    output = tmp_path / "already.pdf"
    output.write_bytes(b"retain")
    with pytest.raises(DecisionError, match="overwrite"):
        apply_decisions(document, output, data, file_sha256(document))
    assert output.read_bytes() == b"retain"


def test_sidecar_roundtrip_json_and_safe_yaml(document, tmp_path):
    data = collect_decisions(document)
    assert load_sidecar(write_sidecar(data, tmp_path / "decisions.json")) == data
    import yaml
    yaml_path = tmp_path / "decisions.yaml"
    yaml_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert load_sidecar(yaml_path) == data
    yaml_path.write_text("!!python/object/apply:os.system ['echo unsafe']", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_sidecar(yaml_path)


def test_approval_requires_explicit_reviewer_date_and_supported_text(document):
    data = collect_decisions(document)
    item = data["decisions"][2]
    with pytest.raises(DecisionError):
        approve(item, "")
    item["value"] = "An exact contextual description"
    with pytest.raises(DecisionError):
        bind_approval(item, "", "2026-10-15")
    with pytest.raises(DecisionError):
        bind_approval(item, "Human Reviewer", "not-a-date")


def test_html_packet_escapes_document_and_sidecar_payloads(document, tmp_path):
    payload = '<script>alert("document")</script><img src="https://example.com/tracker">'
    data = collect_decisions(document)
    data["decisions"][0]["value"] = payload
    report = report_for(document)
    report["input"] = {"path": payload}
    report["manual_review"]["items"][0].update(status="pending", description=payload)
    html_path = render_review_packet(report, data, tmp_path / "review.html")
    content = html_path.read_text(encoding="utf-8")
    assert "<script>" not in content
    assert '<img src="https:' not in content
    assert "&lt;script&gt;" in content
    assert "Content-Security-Policy" in content and "default-src 'none'" in content
    assert "Pending human review (1)" in content
    assert "<html lang=\"en\">" in content


def test_ledger_requires_candidate_not_a_score_alone(document, tmp_path):
    report = report_for(document)
    report["status"] = "needs-manual"
    with pytest.raises(LedgerError, match="candidate"):
        record(document, tmp_path / "ledger.jsonl", report, checker_score=100)


@pytest.mark.parametrize("defect", ["validator", "rules", "execution", "validator-hash", "supplemental", "required-check", "fidelity", "fidelity-hash", "pending", "omitted", "residual"])
def test_ledger_refuses_failed_or_unresolved_evidence(document, tmp_path, defect):
    report = report_for(document)
    if defect == "validator":
        report["gate1"]["status"] = "error"
    elif defect == "rules":
        report["gate1"]["counts"]["failedRules"] = 1
    elif defect == "execution":
        report["gate1"]["execution"]["returncode"] = 1
    elif defect == "validator-hash":
        report["gate1"]["input_sha256"] = "b" * 64
    elif defect == "supplemental":
        report["gate2"]["blockers"] = ["Unresolved"]
    elif defect == "required-check":
        report["gate2"]["checks"][0]["status"] = "not-tested"
    elif defect == "fidelity":
        report["fidelity"]["status"] = "fail"
    elif defect == "fidelity-hash":
        report["fidelity"]["after_sha256"] = "b" * 64
    elif defect == "pending":
        report["manual_review"]["items"][0]["status"] = "pending"
    elif defect == "omitted":
        report["gate2"]["manual_queue"].append({"id": "ocr-accuracy", "required": True})
    elif defect == "residual":
        report["residual_issues"] = ["A confirmed semantic blocker"]
    with pytest.raises(LedgerError):
        record(document, tmp_path / "ledger.jsonl", report)


@pytest.mark.parametrize("kwargs", [{"reviewer": ""}, {"reviewed_at": ""}, {"checker_context": ""},
                                    {"review_scope": ""}, {"checker_score": 66}, {"checker_score": True},
                                    {"checker_score": float("nan")}, {"threshold": 101}])
def test_ledger_requires_actual_score_context_and_complete_human_record(document, tmp_path, kwargs):
    with pytest.raises((LedgerError, DecisionError)):
        record(document, tmp_path / "ledger.jsonl", **kwargs)


def test_verification_goes_stale_when_exact_file_changes(document, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    entry = record(document, ledger)
    assert list_records(ledger)[0]["current_status"] == "verified"
    with document.open("ab") as stream:
        stream.write(b"\n% Changed after review\n")
    current = list_records(ledger)[0]
    assert current["current_status"] == "stale"
    assert current["historical_status"] == "verified"
    assert current["pdf_sha256"] == entry["pdf_sha256"]
    exported = json.loads(export_ledger(ledger, tmp_path / "export.json").read_text(encoding="utf-8"))
    assert exported["records"][0]["current_status"] == "stale"


def test_missing_pdf_is_unavailable_and_unchecked_is_never_currently_verified(document, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    record(document, ledger)
    assert list_records(ledger, verify_files=False)[0]["current_status"] == "not-checked"
    document.unlink()
    assert list_records(ledger)[0]["current_status"] == "unavailable"


def test_ledger_detects_changed_historical_entry(document, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    record(document, ledger)
    row = json.loads(ledger.read_text(encoding="utf-8"))
    row["actual_checker_score"] = 100
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(LedgerError, match="integrity"):
        list_records(ledger)


def test_semantic_blocker_invalidates_current_status_but_retains_history(document, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    row = record(document, ledger)
    invalidate_record(ledger, row["record_id"], "Wrong table relationships found", "Human Reviewer", "2026-10-15")
    records = list_records(ledger)
    assert records[0]["historical_status"] == "verified"
    assert records[0]["current_status"] == "invalidated"
    assert records[1]["kind"] == "invalidation"


def test_ledger_accepts_older_score_and_context_names(document, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    arguments = {"reviewer": "Human Reviewer", "reviewed_at": "2026-10-15", "ally_score": 91,
                 "ally_context": "University LMS course; actual uploaded candidate", "threshold": 67,
                 "review_scope": "All pages visually; full document reading order through accessibility interface"}
    entry = add_record(ledger, document, report_for(document), **arguments)
    assert entry["actual_checker_score"] == 91 and entry["checker_context"].startswith("University")
    old = dict(entry)
    old["actual_ally_score"], old["ally_context"] = old.pop("actual_checker_score"), old.pop("checker_context")
    old.pop("record_sha256")
    from pdf_remediator.ledger import _digest
    old["record_sha256"] = _digest(old)
    ledger.write_text(json.dumps(old) + "\n", encoding="utf-8")
    current = list_records(ledger)[0]
    assert current["actual_checker_score"] == 91 and current["checker_context"] == old["ally_context"]
    from pdf_remediator.cli import _parser
    flags = ["ledger", "add", "--ledger", "ledger.jsonl", "bundle", "--reviewer", "Human Reviewer",
             "--review-scope", "All pages", "--review-file", "review.json"]
    for score, context in (("--checker-score", "--checker-context"), ("--ally-score", "--ally-context")):
        parsed = _parser().parse_args(flags + [score, "90", context, "LMS course"])
        assert parsed.checker_score == 90 and parsed.checker_context == "LMS course"
