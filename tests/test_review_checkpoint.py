"""Exact review-checkpoint adoption across code updates, with fresh gates.

The PDF inspection, editing, rendering, and bundle boundaries are real. Only
the external PDF/UA validator uses test_pipeline's explicitly named stub.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator import checks, engines, inspection, pipeline, validation
from pdf_remediator.config import RuntimeConfig
from test_pipeline import (assert_no_published_pdf, bundle, fast_validator,
                           input_pdf, run, sidecar_for, tagged_control)


def newer_code(monkeypatch):
    digest = hashlib.sha256(b"explicit test-only application update").hexdigest()
    monkeypatch.setattr(pipeline, "implementation_digest", lambda config: digest)
    return digest


def rewrite_manifest_member(report, name, change):
    """Retain a coherent bundle while testing independent checkpoint checks."""
    root = bundle(report)
    path = root / name
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    pipeline.write_json(path, value)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][name] = pipeline.sha(path)
    pipeline.write_json(root / "manifest.json", manifest)
    assert pipeline.verify_bundle(root)


def prepared_case(input_pdf, tmp_path, config=RuntimeConfig()):
    previous = run(input_pdf, tmp_path / "before", config=config)
    assert previous["status"] == "candidate", previous.get("error")
    sidecar = sidecar_for(previous, tmp_path / "accepted.json", "Reviewed course reading")
    return previous, sidecar


def apply_checkpoint(input_pdf, tmp_path, previous, sidecar, config=RuntimeConfig(), **kwargs):
    return pipeline.process_file(input_pdf, tmp_path / "after", config,
                                 sidecar=sidecar, decision_bundle=bundle(previous), **kwargs)


def test_cross_code_adoption_retains_exact_preparation_and_reruns_every_assessment(
        input_pdf, tmp_path, fast_validator, monkeypatch):
    source_hash = pipeline.sha(input_pdf)
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    old_checkpoint = Path(previous["decision_source"]["path"])
    old_hash = pipeline.sha(old_checkpoint)
    new_digest = newer_code(monkeypatch)
    calls_before = len(fast_validator)
    assessments, comparisons = [], []
    real_assess, real_compare = checks.assess, inspection.compare_fidelity

    def forbidden_preparation(*args, **kwargs):
        pytest.fail("An explicitly adopted preparation must not be rebuilt under new code")

    def fresh_assess(*args, **kwargs):
        assessments.append(args[0]["sha256"])
        return real_assess(*args, **kwargs)

    def fresh_compare(before, after, **kwargs):
        comparisons.append((Path(before), pipeline.sha(after)))
        return real_compare(before, after, **kwargs)

    monkeypatch.setattr(engines, "tag", forbidden_preparation)
    monkeypatch.setattr(pipeline, "normalize_catalog", forbidden_preparation)
    monkeypatch.setattr(checks, "assess", fresh_assess)
    monkeypatch.setattr(inspection, "compare_fidelity", fresh_compare)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar)
    assert report["status"] == "candidate", report.get("error")
    assert report["implementation_digest"] == new_digest
    assert report["checkpoint_reused"] is True
    assert report["decision_source"]["sha256"] == old_hash
    assert Path(report["decision_source"]["path"]) != old_checkpoint
    assert pipeline.sha(old_checkpoint) == old_hash
    assert pipeline.sha(input_pdf) == source_hash
    assert [call["kind"] for call in fast_validator[calls_before:]] == ["baseline", "final"]
    final_hash = report["output"]["sha256"]
    assert final_hash != previous["output"]["sha256"]
    assert report["gate1"]["input_sha256"] == final_hash
    assert report["fidelity"]["after_sha256"] == final_hash
    assert assessments == [final_hash]
    assert comparisons == [(input_pdf.resolve(), final_hash)]
    evidence = Path(report["gate1"]["raw_report"])
    assert bundle(report) in evidence.parents and evidence.is_file()
    assert evidence != Path(previous["gate1"]["raw_report"])
    adopted = [item for item in report["processors"] if item["name"] == "review-checkpoint-import"]
    assert len(adopted) == 1 and adopted[0]["prepared_sha256"] == old_hash
    assert adopted[0]["manifest_sha256"] == pipeline.sha(bundle(previous) / "manifest.json")
    assert len([item for item in report["processors"] if item["name"] == "approved-decisions"]) == 1
    with pikepdf.open(report["output"]["path"]) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Reviewed course reading"
    assert pipeline.verify_bundle(bundle(report)) and pipeline.verify_bundle(bundle(previous))


def test_prior_validator_pass_cannot_override_new_validator_failure(
        input_pdf, tmp_path, fast_validator, monkeypatch):
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    newer_code(monkeypatch)
    real_validate = validation.validate_pdf

    def now_fails(path, *args, **kwargs):
        outcome = real_validate(path, *args, **kwargs)
        if Path(path).name == "processed.pdf":
            outcome.update(status="fail", is_compliant=False)
            outcome["counts"].update(failedRules=1, failedChecks=1)
        return outcome

    monkeypatch.setattr(validation, "validate_pdf", now_fails)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar)
    assert report["gate1"]["status"] == "fail"
    assert report["status"] == "needs-manual"
    assert Path(report["output"]["path"]).name == "review-draft.pdf"
    assert not (bundle(report) / "candidate.pdf").exists()
    assert pipeline.verify_bundle(bundle(report))


def test_prior_semantic_pass_cannot_override_new_assessment_blocker(
        input_pdf, tmp_path, fast_validator, monkeypatch):
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    newer_code(monkeypatch)
    real_assess = checks.assess

    def now_blocks(*args, **kwargs):
        outcome = real_assess(*args, **kwargs)
        block = {"id": "test-new-rule", "status": "fail", "description": "New assessment regression rule"}
        outcome["status"] = "fail"
        outcome["checks"].append(block)
        outcome["blockers"].append(block)
        return outcome

    monkeypatch.setattr(checks, "assess", now_blocks)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar)
    assert report["status"] == "needs-manual"
    assert report["gate2"]["status"] == "fail"
    assert report["output"]["review_only"] is True


def test_prior_fidelity_pass_cannot_override_new_comparison_failure(
        input_pdf, tmp_path, fast_validator, monkeypatch):
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    newer_code(monkeypatch)
    real_compare = inspection.compare_fidelity

    def now_fails(*args, **kwargs):
        outcome = real_compare(*args, **kwargs)
        outcome["status"] = "fail"
        return outcome

    monkeypatch.setattr(inspection, "compare_fidelity", now_fails)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar)
    assert report["fidelity"]["status"] == "fail"
    assert_no_published_pdf(report)
    assert pipeline.verify_bundle(bundle(report))


@pytest.mark.parametrize("damage", ["manifest", "checkpoint-changed", "checkpoint-missing",
                                   "source-binding", "inventory", "policy", "settings", "source"])
def test_invalid_review_checkpoint_is_refused_without_repreparing_or_shipping(
        damage, input_pdf, tmp_path, fast_validator, monkeypatch):
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    config = RuntimeConfig()
    if damage == "manifest":
        with (bundle(previous) / "report.json").open("ab") as stream:
            stream.write(b"\n")
    elif damage == "checkpoint-changed":
        with Path(previous["decision_source"]["path"]).open("ab") as stream:
            stream.write(b"\n% changed checkpoint bytes\n")
    elif damage == "checkpoint-missing":
        Path(previous["decision_source"]["path"]).unlink()
    elif damage == "source-binding":
        rewrite_manifest_member(previous, "report.json",
                                lambda value: value["decision_source"].update(source_sha256="0" * 64))
    elif damage == "inventory":
        rewrite_manifest_member(previous, "decisions.json",
                                lambda value: value["decisions"][0].update(current="invented stale context"))
    elif damage == "policy":
        rewrite_manifest_member(previous, "report.json",
                                lambda value: value["fidelity"].update(policy="relax-arbitrary-text"))
    elif damage == "settings":
        config = RuntimeConfig(title="Changed preparation settings")
    elif damage == "source":
        with input_pdf.open("ab") as stream:
            stream.write(b"\n% changed source bytes\n")
    newer_code(monkeypatch)
    calls_before = len(fast_validator)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid checkpoint must fail explicitly rather than silently rebuild")

    monkeypatch.setattr(engines, "tag", forbidden)
    monkeypatch.setattr(pipeline, "normalize_catalog", forbidden)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar, config=config)
    assert report["status"] == "failed"
    assert report["error"]["type"] == "ValueError"
    assert [call["kind"] for call in fast_validator[calls_before:]] == ["baseline"]
    assert_no_published_pdf(report)
    assert pipeline.verify_bundle(bundle(report))


@pytest.mark.parametrize("mode,with_sidecar", [("check", True), ("fix", False)])
def test_checkpoint_adoption_requires_explicit_fix_and_accepted_decisions(
        mode, with_sidecar, input_pdf, tmp_path, fast_validator):
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    with pytest.raises(ValueError, match="explicit accepted decision"):
        apply_checkpoint(input_pdf, tmp_path, previous, sidecar if with_sidecar else None, mode=mode)
    assert not (tmp_path / "after").exists()


def test_read_only_check_bundle_cannot_be_used_as_preparation(
        input_pdf, tmp_path, fast_validator, monkeypatch):
    previous = run(input_pdf, tmp_path / "before", mode="check")
    assert pipeline.verify_bundle(bundle(previous))
    sidecar = sidecar_for(previous, tmp_path / "accepted.json", "Reviewed course reading")
    newer_code(monkeypatch)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar)
    assert report["status"] == "failed"
    assert "read-only check" in report["error"]["message"]
    assert_no_published_pdf(report)


def test_preservation_reference_is_copied_exactly_and_recompared_after_code_update(
        input_pdf, tmp_path, fast_validator, monkeypatch):
    config = RuntimeConfig(repair_source_mappings=True)
    previous, sidecar = prepared_case(input_pdf, tmp_path, config)
    assert previous["fidelity"]["policy"] == "authoritative-character-mapping"
    previous_reference = Path(previous["decision_source"]["path"]).parent / "reference.pdf"
    expected = pipeline.sha(previous_reference)
    newer_code(monkeypatch)
    real_compare = inspection.compare_fidelity
    comparisons = []

    def observed(before, after, **kwargs):
        comparisons.append((pipeline.sha(before), pipeline.sha(after)))
        return real_compare(before, after, **kwargs)

    monkeypatch.setattr(inspection, "compare_fidelity", observed)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar, config)
    assert report["status"] == "candidate", report.get("error")
    new_reference = Path(report["decision_source"]["path"]).parent / "reference.pdf"
    assert new_reference != previous_reference and pipeline.sha(new_reference) == expected
    assert report["fidelity"]["reference_sha256"] == expected
    assert report["fidelity"]["status"] == "pass"
    assert comparisons == [(pipeline.sha(input_pdf), report["output"]["sha256"]),
                           (expected, report["output"]["sha256"]), (pipeline.sha(input_pdf), expected)]
    assert len(fast_validator) == 4
    assert pipeline.verify_bundle(bundle(report))


@pytest.mark.parametrize("damage", ["missing", "changed", "unbound"])
def test_reference_policy_never_accepts_missing_changed_or_unbound_reference(
        damage, input_pdf, tmp_path, fast_validator, monkeypatch):
    config = RuntimeConfig(repair_source_mappings=True)
    previous, sidecar = prepared_case(input_pdf, tmp_path, config)
    reference = Path(previous["decision_source"]["path"]).parent / "reference.pdf"
    if damage == "missing":
        reference.unlink()
    elif damage == "changed":
        with reference.open("ab") as stream:
            stream.write(b"\n% changed preservation reference\n")
    else:
        rewrite_manifest_member(previous, "report.json", lambda value: value["fidelity"].pop("reference_sha256"))
    newer_code(monkeypatch)
    report = apply_checkpoint(input_pdf, tmp_path, previous, sidecar, config)
    assert report["status"] == "failed"
    assert "independent preservation reference" in report["error"]["message"]
    assert_no_published_pdf(report)


@pytest.mark.parametrize("damage", ["proof", "reference-policy", "checkpoint-bytes", "anchor"])
def test_mutated_global_cache_cannot_create_its_own_unpublished_provenance(
        damage, input_pdf, tmp_path, fast_validator):
    previous, sidecar = prepared_case(input_pdf, tmp_path)
    checkpoint = Path(previous["decision_source"]["path"])
    metadata_path = checkpoint.parent / "checkpoint.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if damage == "proof":
        metadata["processors"].append({"name": "source-mappings", "status": "pass"})
    elif damage == "reference-policy":
        metadata["reference"] = {"policy": "authoritative-character-mapping", "sha256": pipeline.sha(checkpoint)}
        (checkpoint.parent / "reference.pdf").write_bytes(checkpoint.read_bytes())
    elif damage == "checkpoint-bytes":
        with checkpoint.open("ab") as stream:
            stream.write(b"\n% changed cached bytes with self-reported hash\n")
        metadata["sha256"] = pipeline.sha(checkpoint)
    else:
        metadata["anchor_bundle"] = str(tmp_path / "unpublished")
    pipeline.write_json(metadata_path, metadata)
    # Same output/code/settings intentionally select the existing global cache.
    report = pipeline.process_file(input_pdf, tmp_path / "before" / "output", RuntimeConfig(), sidecar=sidecar)
    assert report["status"] == "failed"
    assert "provenance" in report["error"]["message"]
    assert_no_published_pdf(report)
    assert pipeline.verify_bundle(bundle(report))
