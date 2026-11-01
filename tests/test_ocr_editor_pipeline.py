"""Correction-lineage pipeline boundaries with real PDF inspection.

The OCR writer/proof has separate real tests. Here its lineage validator is an
explicit authored stub so these cases isolate retention, fresh gates, metadata
preservation and later review-checkpoint replay. The external validator uses
test_pipeline's clearly labelled stub; these are not native PDF/UA evidence.
"""
from __future__ import annotations
import json
from pathlib import Path
import shutil

import pikepdf
import pytest

from pdf_remediator import pipeline, ocr_corrections, inspection
from pdf_remediator.config import RuntimeConfig
from test_pipeline import input_pdf, tagged_control, fast_validator, run, bundle, sidecar_for


def binding(path):
    return {"path": str(Path(path).resolve()), "sha256": pipeline.sha(path)}


def authored_lineage(tmp_path, input_pdf, monkeypatch):
    plan = tmp_path / "accepted-plan.json"
    proof = tmp_path / "independent-proof.json"
    plan.write_bytes(b'{"test_only": "accepted plan"}\n')
    proof.write_bytes(b'{"test_only": "separate writer proof"}\n')
    record = tmp_path / "lineage.json"
    # Deliberately retain a different serialization from pipeline.write_json.
    raw = json.dumps({"test_only": True, "plan": binding(plan), "proof": binding(proof)},
                     separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
    record.write_bytes(raw)
    calls = []
    source_hash = pipeline.sha(input_pdf)

    def validate(path, source, expected_sha256=None, cancel=None):
        assert pipeline.sha(path) == expected_sha256
        assert pipeline.sha(source) == source_hash
        calls.append((Path(path), Path(source)))
        return {"test_only": True, "original": binding(input_pdf), "ocr_pages": [1], "ancestry": []}

    monkeypatch.setattr(ocr_corrections, "validate_lineage", validate)
    return binding(record), raw, calls


@pytest.mark.parametrize("bad", [
    {}, {"path": "missing", "sha256": "a" * 63},
    {"path": "missing", "sha256": "A" * 64},
    {"path": "missing", "sha256": "a" * 64, "extra": True},
    {"path": 123, "sha256": "a" * 64},
    {"path": "missing", "sha256": None},
])
def test_lineage_refusal_precedes_any_output_or_validator(
        bad, input_pdf, tmp_path, fast_validator):
    original = input_pdf.read_bytes()
    with pytest.raises(ValueError):
        pipeline.process_file(input_pdf, tmp_path / "after", RuntimeConfig(), source_lineage=bad)
    assert input_pdf.read_bytes() == original
    assert not (tmp_path / "after").exists()
    assert fast_validator == []


def test_changed_lineage_hash_is_not_accepted_as_new_authority(
        input_pdf, tmp_path, monkeypatch, fast_validator):
    row, raw, calls = authored_lineage(tmp_path, input_pdf, monkeypatch)
    Path(row["path"]).write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="missing or changed"):
        run(input_pdf, tmp_path / "after", source_lineage=row)
    assert not (tmp_path / "after").exists()
    assert calls == [] and fast_validator == []


def test_changed_retained_proof_copy_is_refused(
        input_pdf, tmp_path, monkeypatch):
    row, raw, calls = authored_lineage(tmp_path, input_pdf, monkeypatch)
    original_copy = pipeline.shutil.copyfile

    def corrupted_copy(source, destination, *args, **kwargs):
        result = original_copy(source, destination, *args, **kwargs)
        Path(destination).write_bytes(b'not the bound evidence')
        return result

    monkeypatch.setattr(pipeline.shutil, 'copyfile', corrupted_copy)
    (tmp_path / 'stage').mkdir()
    with pytest.raises(ValueError, match='evidence copy differs'):
        pipeline._retain_ocr_lineage(row, tmp_path / 'stage')
    assert Path(row['path']).read_bytes() == raw


def test_lineage_retention_rechecks_full_pdf_and_keeps_raw_proof_bytes(
        input_pdf, tmp_path, monkeypatch, fast_validator):
    original = input_pdf.read_bytes()
    row, raw, calls = authored_lineage(tmp_path, input_pdf, monkeypatch)
    report = run(input_pdf, tmp_path / "after", source_lineage=row)
    assert report["status"] == "candidate", report.get("error")
    assert report["fidelity"]["status"] == "pass"
    assert "policy" not in report["fidelity"]
    assert len(fast_validator) == 2
    assert len(calls) == 2
    retained = report["source_lineage"]
    assert retained["sha256"] == row["sha256"]
    assert Path(retained["path"]).read_bytes() == raw
    assert bundle(report) in Path(retained["path"]).parents
    assert (bundle(report) / "lineage/plan.json").read_bytes() == (tmp_path / "accepted-plan.json").read_bytes()
    assert (bundle(report) / "lineage/proof.json").read_bytes() == (tmp_path / "independent-proof.json").read_bytes()
    reviews = [i for i in report["manual_review"]["items"] if i["id"] == "ocr-text-corrections"]
    assert len(reviews) == 1 and reviews[0]["status"] == "pending" and reviews[0]["required"]
    assert not report["manual_review"]["complete"]
    assert input_pdf.read_bytes() == original
    assert pipeline.verify_bundle(bundle(report))


def test_metadata_apply_after_corrected_source_retains_lineage_and_fresh_ocr_review(
        input_pdf, tmp_path, monkeypatch, fast_validator):
    row, raw, calls = authored_lineage(tmp_path, input_pdf, monkeypatch)
    previous = run(input_pdf, tmp_path / "before", source_lineage=row)
    previous_members = {str(p.relative_to(bundle(previous))): p.read_bytes()
                        for p in bundle(previous).rglob("*") if p.is_file()}
    accepted = sidecar_for(previous, tmp_path / "new-title.json", "Updated after OCR correction")
    before_text = inspection.inspect_pdf(previous["output"]["path"])["pages"]
    result = pipeline.process_file(input_pdf, tmp_path / "after", RuntimeConfig(),
        sidecar=accepted, decision_bundle=bundle(previous))
    assert result["status"] == "candidate", result.get("error")
    assert result["source_lineage"]["sha256"] == row["sha256"]
    assert Path(result["source_lineage"]["path"]).read_bytes() == raw
    assert result["fidelity"]["status"] == "pass"
    with pikepdf.open(result["output"]["path"]) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Updated after OCR correction"
    assert inspection.inspect_pdf(result["output"]["path"])["pages"] == before_text
    assert len(fast_validator) == 4
    reviews = [i for i in result["manual_review"]["items"] if i["id"] == "ocr-text-corrections"]
    assert len(reviews) == 1 and reviews[0]["status"] == "pending"
    assert {str(p.relative_to(bundle(previous))): p.read_bytes()
            for p in bundle(previous).rglob("*") if p.is_file()} == previous_members
    assert pipeline.verify_bundle(bundle(previous)) and pipeline.verify_bundle(bundle(result))


def test_lineage_changed_during_assessment_withholds_the_pdf(
        input_pdf, tmp_path, monkeypatch, fast_validator):
    row, raw, calls = authored_lineage(tmp_path, input_pdf, monkeypatch)
    actual = inspection.compare_fidelity

    def changed_during_comparison(*args, **kwargs):
        result = actual(*args, **kwargs)
        Path(row["path"]).write_bytes(raw + b" ")
        return result

    monkeypatch.setattr(inspection, "compare_fidelity", changed_during_comparison)
    result = run(input_pdf, tmp_path / "after", source_lineage=row)
    assert result["status"] == "failed" and result["output"] is None
    assert not (bundle(result) / "candidate.pdf").exists()
    assert not (bundle(result) / "review-draft.pdf").exists()
    assert len(fast_validator) == 2


@pytest.mark.parametrize("config", [RuntimeConfig(ocr_mode="textless"), RuntimeConfig(ocr_mode="skip")])
def test_corrected_source_cannot_silently_rerun_ocr(
        config, input_pdf, tmp_path, monkeypatch, fast_validator):
    row, _, _ = authored_lineage(tmp_path, input_pdf, monkeypatch)
    with pytest.raises(ValueError, match="OCR off"):
        run(input_pdf, tmp_path / "after", config=config, source_lineage=row)
    assert fast_validator == [] and not (tmp_path / "after").exists()


def test_derivative_preserves_already_accepted_title_and_language(
        input_pdf, tmp_path, monkeypatch, fast_validator):
    previous = run(input_pdf, tmp_path / "before")
    original = input_pdf.read_bytes()
    plan = tmp_path / "accepted-ocr-plan.json"
    plan.write_text('{"test_only":true}\n', encoding="utf-8")
    created = []

    def create(prior_bundle, selected_plan, destination, expected_plan_sha256=None, cancel=None):
        assert Path(prior_bundle) == bundle(previous)
        assert pipeline.sha(selected_plan) == expected_plan_sha256
        assert destination.parent.is_dir(), 'The pipeline must prepare the real writer parent.'
        destination.mkdir()
        path = destination / "corrected.pdf"
        with pikepdf.open(previous["output"]["path"]) as pdf:
            pdf.Root.Lang = pikepdf.String("fr-CA")
            pdf.docinfo["/Title"] = pikepdf.String("Previously accepted title")
            pdf.save(path)
        lineage = destination / "lineage.json"
        lineage.write_bytes(b'{"test_only":true}\n')
        created.append(path)
        return {"source_path": str(path), "lineage_path": str(lineage),
                "lineage_sha256": pipeline.sha(lineage)}

    def validate(path, source, expected_sha256=None, cancel=None):
        assert pipeline.sha(path) == expected_sha256
        assert Path(source) == created[-1]
        return {"test_only": True, "original": binding(input_pdf), "ocr_pages": [1], "ancestry": []}

    monkeypatch.setattr(ocr_corrections, "create_derivative", create)
    monkeypatch.setattr(ocr_corrections, "validate_lineage", validate)
    result = pipeline.process_file(input_pdf, tmp_path / "after", RuntimeConfig(),
        ocr_correction_plan=plan, expected_ocr_correction_sha256=pipeline.sha(plan),
        ocr_correction_bundle=bundle(previous), expected_source_sha256=pipeline.sha(input_pdf))
    assert result["status"] == "candidate", result.get("error")
    assert result["input"]["path"] == str(created[0])
    assert result["settings"]["ocr_mode"] == "off" and result["settings"]["ocr_profile"] == "standard"
    assert result["settings"]["language"] == "fr-CA"
    assert result["settings"]["title"] == "Previously accepted title"
    with pikepdf.open(result["output"]["path"]) as pdf:
        assert str(pdf.Root.Lang) == "fr-CA"
        assert str(pdf.docinfo["/Title"]) == "Previously accepted title"
    assert input_pdf.read_bytes() == original
    assert len(fast_validator) == 4
    assert pipeline.verify_bundle(bundle(previous)) and pipeline.verify_bundle(bundle(result))
