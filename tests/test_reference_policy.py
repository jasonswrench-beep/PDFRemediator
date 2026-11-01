"""Reference policies keep exact final fidelity and require processor evidence.

The external validator and modifying stage are explicit test stubs. PDF parsing,
content linkage, text extraction, all-page rendering and publication are real.
"""
from pathlib import Path
import shutil

import pikepdf
import pytest

from pdf_remediator import fonts, ocr, pipeline, validation
from pdf_remediator.config import RuntimeConfig

from test_pipeline import tagged_control


@pytest.fixture
def source(tmp_path, tagged_control):
    destination = tmp_path / "input/reading.pdf"
    destination.parent.mkdir()
    shutil.copyfile(tagged_control, destination)
    return destination


@pytest.fixture
def validator_stub(monkeypatch):
    calls = []

    def run(pdf, directory, *args, **kwargs):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        raw = directory / "explicit-test-stub.txt"
        raw.write_text("TEST STUB. No external validator invoked.\n", encoding="utf-8")
        digest = pipeline.sha(pdf)
        calls.append({"path": Path(pdf), "directory": directory.name, "sha256": digest})
        return {"status": "pass", "validator": "explicit-test-stub", "profile": "ua1", "is_compliant": True,
                "version": "1.30.3", "expected_version": "1.30.3", "failed_rules": [],
                "assertion_detail_coverage": {"status": "complete", "listed_failed_checks": 0},
                "input_sha256": digest, "raw_report": str(raw),
                "counts": {"passedRules": 106, "passedChecks": 106, "failedRules": 0, "failedChecks": 0},
                "execution": {"status": "completed", "returncode": 0}}

    monkeypatch.setattr(validation, "validate_pdf", run)
    # Keep unrelated concurrent edits from invalidating a test checkpoint.
    digest = pipeline.implementation_digest(RuntimeConfig())
    monkeypatch.setattr(pipeline, "implementation_digest", lambda config: digest)
    return calls


def copy_with_extra_artifact(source, destination, kind=None):
    if kind is None:
        shutil.copyfile(source, destination)
        return
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0]
        previous = page.obj.Contents
        streams = list(previous) if isinstance(previous, pikepdf.Array) else [previous]
        if kind == "visible":
            extra = b"/Artifact BMC q 1 0 0 rg 0 0 30 30 re f Q EMC"
        else:
            font_name = next(iter(page.Resources.Font.keys()))
            extra = f"/Artifact BMC BT 3 Tr {font_name} 12 Tf 20 10 Td (UNEXPECTED TOKEN) Tj ET EMC".encode("ascii")
        page.Contents = pikepdf.Array(streams + [pikepdf.Stream(pdf, extra)])
        pdf.save(destination, deterministic_id=True)


def font_stub(monkeypatch, change_final=None, change_reference=None, status="pass"):
    def run(original, processed, destination, reference_destination, cancel=None):
        copy_with_extra_artifact(processed, destination, change_final)
        copy_with_extra_artifact(original, reference_destination, change_reference)
        return {"name": "source-unicode-closure", "status": status,
                "reference_appearance": {"status": "pass"},
                "source_reference_sha256": pipeline.sha(reference_destination),
                "changes": [], "authoritative_corrections": [], "warnings": [],
                "scope": "Explicit regression stub using a byte-identical no-op reference unless the test injects a defect."}
    monkeypatch.setattr(fonts, "repair_source_mappings", run)


def process(source, tmp_path, **options):
    return pipeline.process_file(source, tmp_path / "output", RuntimeConfig(**options))


def no_published_pdf(report):
    assert report["output"] is None
    assert not list(Path(report["bundle_path"]).rglob("*.pdf"))


def test_font_stage_result_cannot_override_pipeline_processor_identity(source, tmp_path, monkeypatch, validator_stub):
    font_stub(monkeypatch)
    report = process(source, tmp_path, repair_source_mappings=True)
    assert report["status"] == "candidate", report.get("residual_issues")
    assert report["fidelity"]["policy"] == "authoritative-character-mapping"
    assert report["fidelity"]["status"] == "pass"
    assert any(item["name"] == "source-mappings" for item in report["processors"])
    assert not any(item["name"] == "source-unicode-closure" for item in report["processors"])
    assert any(item["id"] == "source-character-corrections" for item in report["manual_review"]["items"])
    assert pipeline.verify_bundle(report["bundle_path"])
    assert report["baseline_gate1"]["input_sha256"] == pipeline.sha(source)
    assert report["validation_delta"]["status"] == "compared"
    assert [item["directory"] for item in validator_stub] == ["baseline-validator", "validator"]


@pytest.mark.parametrize("kind", ["visible", "invisible-text"])
def test_font_reference_never_waives_final_pixels_or_characters(source, tmp_path, monkeypatch, validator_stub, kind):
    font_stub(monkeypatch, change_final=kind)
    report = process(source, tmp_path, repair_source_mappings=True)
    assert report["gate1"]["status"] == report["gate2"]["status"] == "pass"
    assert report["fidelity"]["status"] == "fail"
    exact = report["fidelity"]["reference_comparison"]
    assert exact["status"] == "fail"
    if kind == "visible":
        assert exact["pages"][0]["render_status"] == "fail"
    else:
        assert exact["pages"][0]["render_status"] == "pass"
        assert exact["text"]["multiset_status"] == "fail"
    no_published_pdf(report)


def test_claimed_font_appearance_proof_does_not_replace_actual_source_comparison(source, tmp_path, monkeypatch, validator_stub):
    font_stub(monkeypatch, change_final="visible", change_reference="visible")
    report = process(source, tmp_path, repair_source_mappings=True)
    assert report["fidelity"]["reference_comparison"]["status"] == "pass"
    assert report["fidelity"]["source_to_reference"]["pages"][0]["render_status"] == "fail"
    assert report["fidelity"]["status"] == "fail"
    no_published_pdf(report)


def test_refused_font_stage_cannot_become_a_candidate_from_existing_copies(source, tmp_path, monkeypatch, validator_stub):
    font_stub(monkeypatch, status="refused")
    report = process(source, tmp_path, repair_source_mappings=True)
    assert report["status"] == "needs-manual"
    assert len(validator_stub) == 1
    assert validator_stub[0]["directory"] == "baseline-validator" and validator_stub[0]["path"] == source
    no_published_pdf(report)


@pytest.mark.parametrize("proof", [None, {"status": "fail"}, {"status": "not-tested"}])
def test_ocr_requires_explicit_successful_preservation_evidence(source, tmp_path, monkeypatch, validator_stub, proof):
    def run(input, output, *args, **kwargs):
        shutil.copyfile(input, output)
        result = {"status": "completed", "scope": "Explicit OCR regression stub"}
        if proof is not None:
            result["preservation"] = proof
        return result
    monkeypatch.setattr(ocr, "run_ocr", run)
    report = process(source, tmp_path, ocr_mode="skip")
    assert report["status"] == "failed"
    assert "OCR preservation" in report["error"]["message"]
    assert len(validator_stub) == 1
    assert validator_stub[0]["directory"] == "baseline-validator" and validator_stub[0]["path"] == source
    no_published_pdf(report)


def test_successful_noop_ocr_keeps_declared_reference_policy(source, tmp_path, monkeypatch, validator_stub):
    def run(input, output, *args, **kwargs):
        shutil.copyfile(input, output)
        return {"status": "completed", "preservation": {"status": "pass"}, "scope": "Explicit no-op OCR regression stub"}
    monkeypatch.setattr(ocr, "run_ocr", run)
    report = process(source, tmp_path, ocr_mode="skip")
    assert report["status"] == "candidate"
    assert report["fidelity"]["policy"] == "ocr-added-text"
    assert report["fidelity"]["reference_comparison"]["status"] == "pass"


def test_ocr_success_claim_never_waives_source_appearance(source, tmp_path, monkeypatch, validator_stub):
    def run(input, output, *args, **kwargs):
        copy_with_extra_artifact(input, output, "visible")
        return {"status": "completed", "preservation": {"status": "pass"}, "scope": "Deliberately wrong regression stub claim"}
    monkeypatch.setattr(ocr, "run_ocr", run)
    report = process(source, tmp_path, ocr_mode="skip")
    assert report["fidelity"]["reference_comparison"]["status"] == "pass"
    assert report["fidelity"]["source_to_reference"]["pages"][0]["render_status"] == "fail"
    assert report["fidelity"]["status"] == "fail"
    no_published_pdf(report)
