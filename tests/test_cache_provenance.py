"""Cached preparation never supplies unanchored repair/exception authority.

These use real PDF inspection/fidelity and an explicitly named validator stub.
The anchor-rewrite case simulates a coherent corrupt local cache, then checks
that an independent, selected immutable review bundle remains authoritative.
"""
import copy
import json
from pathlib import Path
import shutil

import pytest

from pdf_remediator import pipeline, validation
from pdf_remediator.config import RuntimeConfig, load_config
from pdf_remediator.sidecar import bind_approval, file_sha256, load_sidecar, write_sidecar

from test_pipeline import tagged_control


@pytest.fixture
def environment(tmp_path, monkeypatch, tagged_control):
    source = tmp_path / "source.pdf"
    shutil.copyfile(tagged_control, source)
    calls = []

    def validator(path, directory, *args, **kwargs):
        path, directory = Path(path), Path(directory)
        directory.mkdir(parents=True)
        evidence = directory / "explicit-test-stub.txt"
        evidence.write_text("Regression validator stub; no external validator invoked", encoding="utf-8")
        calls.append(path.name)
        return {"status": "pass", "profile": "ua1", "version": "test-stub", "is_compliant": True,
                "input_sha256": file_sha256(path), "raw_report": str(evidence), "failed_rules": [],
                "counts": {"passedRules": 106, "passedChecks": 106, "failedRules": 0, "failedChecks": 0},
                "execution": {"status": "completed", "returncode": 0}}
    monkeypatch.setattr(validation, "validate_pdf", validator)
    monkeypatch.setattr(pipeline, "implementation_digest", lambda config: "f" * 64)
    config = RuntimeConfig()
    first = pipeline.process_file(source, tmp_path / "ordinary", config)
    assert first["status"] == "candidate"
    return {"source": source, "config": config, "first": first, "calls": calls, "tmp": tmp_path}


def decisions(report, path, title, approved=False):
    value = load_sidecar(Path(report["bundle_path"]) / "decisions.json")
    item = next(item for item in value["decisions"] if item["kind"] == "title")
    item["value"] = title
    if approved:
        bind_approval(item, "Synthetic Cache Test Reviewer", "2026-10-16")
    return write_sidecar(value, path)


def cache_metadata(report):
    return Path(report["decision_source"]["path"]).parent / "checkpoint.json"


def assert_failed_without_pdf(report):
    assert report["status"] == "failed" and report["output"] is None
    assert not list(Path(report["bundle_path"]).rglob("*.pdf"))


def test_normal_preparation_has_immutable_metadata_anchor_and_can_be_reused(environment):
    first = environment["first"]
    meta = json.loads(cache_metadata(first).read_text(encoding="utf-8"))
    assert meta["anchor_bundle"] == first["bundle_path"]
    assert first["checkpoint_provenance_sha256"] == pipeline._metadata_digest(meta)
    sidecar = decisions(first, environment["tmp"] / "pending.json", "Pending title is not applied")
    reused = pipeline.process_file(environment["source"], environment["tmp"] / "ordinary", environment["config"], sidecar=sidecar)
    assert reused["status"] == "candidate" and reused["checkpoint_reused"]
    assert reused["checkpoint_provenance_sha256"] == first["checkpoint_provenance_sha256"]
    assert environment["calls"].count("processed.pdf") == 2


def legacy_standard_review(environment, monkeypatch):
    """Author an old-shaped settings record; never migrate an existing review."""
    original_public = RuntimeConfig.public
    def prior_public(config):
        return {key: value for key, value in original_public(config).items() if key != 'ocr_profile'}
    with monkeypatch.context() as prior:
        prior.setattr(RuntimeConfig, 'public', prior_public)
        result = pipeline.process_file(environment['source'], environment['tmp'] / 'authored-legacy', environment['config'])
    assert result['status'] == 'candidate' and 'ocr_profile' not in result['settings']
    return result


def test_legacy_standard_review_adopts_without_rewriting_its_saved_settings(environment, monkeypatch):
    legacy = legacy_standard_review(environment, monkeypatch)
    bundle = Path(legacy['bundle_path'])
    before = {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}
    accepted = decisions(legacy, environment['tmp'] / 'legacy-accepted.json', 'Synthetic accepted title', approved=True)
    result = pipeline.process_file(environment['source'], environment['tmp'] / 'legacy-adopted', environment['config'],
                                   sidecar=accepted, decision_bundle=bundle)
    assert result['status'] == 'candidate' and result['fidelity']['status'] == 'pass'
    assert result['settings']['ocr_profile'] == 'standard'
    assert any(p['name'] == 'review-checkpoint-import' for p in result['processors'])
    assert before == {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('profile', ['table-lines', 'angles'])
def test_changed_scan_layout_cannot_adopt_standard_review(environment, monkeypatch, legacy, profile):
    from dataclasses import replace
    previous = legacy_standard_review(environment, monkeypatch) if legacy else environment['first']
    bundle = Path(previous['bundle_path'])
    before = {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}
    accepted = decisions(previous, environment['tmp'] / 'different-layout.json', 'Synthetic accepted title', approved=True)
    result = pipeline.process_file(environment['source'], environment['tmp'] / 'different-layout',
                                   replace(environment['config'], ocr_profile=profile), sidecar=accepted, decision_bundle=bundle)
    assert_failed_without_pdf(result)
    assert 'original preparation settings' in result['error']['message']
    assert before == {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}


def test_scan_layout_is_validated_and_changes_preparation_identity():
    standard = load_config()
    tables = load_config(ocr_profile='table-lines')
    angles = load_config(ocr_profile='angles')
    textless = load_config(ocr_mode='textless')
    assert standard.ocr_mode == 'off' and standard.ocr_profile == 'standard'
    assert len({config.digest() for config in (standard, tables, angles, textless)}) == 4
    with pytest.raises(ValueError, match='Scan layout'):
        load_config(ocr_profile='arbitrary-flags-or-plugin')


@pytest.mark.parametrize('legacy', [False, True])
def test_textless_mode_cannot_adopt_edits_prepared_with_ocr_off(environment, monkeypatch, legacy):
    from dataclasses import replace
    previous = legacy_standard_review(environment, monkeypatch) if legacy else environment['first']
    bundle = Path(previous['bundle_path'])
    before = {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}
    accepted = decisions(previous, environment['tmp'] / 'different-page-mode.json', 'Synthetic accepted title', approved=True)
    result = pipeline.process_file(environment['source'], environment['tmp'] / 'different-page-mode',
                                   replace(environment['config'], ocr_mode='textless'), sidecar=accepted, decision_bundle=bundle)
    assert_failed_without_pdf(result)
    assert 'original preparation settings' in result['error']['message']
    assert before == {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}


def test_changed_layout_processes_separately_without_reusing_the_saved_checkpoint(environment):
    from dataclasses import replace
    first = environment['first']; bundle = Path(first['bundle_path'])
    before = {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}
    source_hash = file_sha256(environment['source'])
    result = pipeline.process_file(environment['source'], environment['tmp'] / 'ordinary',
                                   replace(environment['config'], ocr_profile='angles'))
    assert result['status'] == 'candidate' and not result.get('checkpoint_reused')
    assert result['bundle_path'] != first['bundle_path']
    assert result['settings']['ocr_mode'] == 'off' and result['settings']['ocr_profile'] == 'angles'
    assert cache_metadata(result) != cache_metadata(first)
    assert file_sha256(environment['source']) == source_hash
    assert before == {str(p): file_sha256(p) for p in bundle.rglob('*') if p.is_file()}


def test_command_line_selects_textless_angles_explicitly_without_changing_defaults():
    from pdf_remediator.cli import _parser
    args = _parser().parse_args(['fix', 'authored.pdf', '-o', 'authored-output', '--ocr', 'textless', '--ocr-profile', 'angles'])
    config = load_config(ocr_mode=args.ocr, ocr_profile=args.ocr_profile)
    assert config.ocr_mode == 'textless' and config.ocr_profile == 'angles'
    defaults = _parser().parse_args(['fix', 'authored.pdf', '-o', 'authored-output'])
    assert defaults.ocr is defaults.ocr_profile is None
    assert load_config(ocr_mode=defaults.ocr, ocr_profile=defaults.ocr_profile).ocr_mode == 'off'


def test_tilted_layout_refuses_redo_before_processing_and_allows_an_off_draft():
    with pytest.raises(ValueError, match='wholly scanned pages'):
        load_config(ocr_mode='redo', ocr_profile='angles')
    draft = load_config(ocr_mode='off', ocr_profile='angles')
    assert draft.ocr_mode == 'off' and draft.ocr_profile == 'angles'


@pytest.mark.parametrize('flag,field,value,message', [
    ('--ocr', 'ocr_mode', 'force', 'OCR'),
    ('--ocr-profile', 'ocr_profile', 'external-plugin', 'Scan layout'),
])
def test_command_line_and_configuration_refuse_unknown_ocr_choices(flag, field, value, message):
    from pdf_remediator.cli import _parser
    with pytest.raises(SystemExit) as refused:
        _parser().parse_args(['fix', 'authored.pdf', '-o', 'authored-output', flag, value])
    assert refused.value.code == 2
    with pytest.raises(ValueError, match=message):
        load_config(**{field: value})


@pytest.mark.parametrize("corruption", ["processors", "reference", "anchor", "body-digest"])
def test_corrupt_normal_cache_cannot_grant_repair_or_reference_authority(environment, corruption):
    first, tmp = environment["first"], environment["tmp"]
    path = cache_metadata(first)
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "processors":
        metadata["processors"].append({"name": "source-mappings", "status": "pass", "source": "invented cache authority"})
    elif corruption == "reference":
        metadata["reference"] = {"policy": "authoritative-character-mapping", "sha256": metadata["sha256"]}
    elif corruption == "anchor":
        metadata["anchor_bundle"] = str(tmp / "nonexistent-anchor")
    else:
        metadata["unanchored_extra_field"] = "changed even though the prepared bytes are identical"
    write_sidecar(metadata, path)
    sidecar = decisions(first, tmp / "changed-request.json", "A distinct pending request")
    failed = pipeline.process_file(environment["source"], tmp / "ordinary", environment["config"], sidecar=sidecar)
    assert_failed_without_pdf(failed)
    assert "provenance" in failed["error"]["message"].lower()
    assert environment["calls"].count("processed.pdf") == 1
    assert pipeline.verify_bundle(first["bundle_path"])


def test_missing_or_changed_anchor_bundle_prevents_cache_reuse(environment):
    first, tmp = environment["first"], environment["tmp"]
    report_path = Path(first["bundle_path"]) / "report.json"
    report_path.write_text(report_path.read_text(encoding="utf-8") + "\n ", encoding="utf-8")
    sidecar = decisions(first, tmp / "changed-request.json", "A distinct pending request")
    failed = pipeline.process_file(environment["source"], tmp / "ordinary", environment["config"], sidecar=sidecar)
    assert_failed_without_pdf(failed)
    assert "provenance" in failed["error"]["message"].lower()


@pytest.mark.parametrize("corruption", ["processor-proof", "reference-policy", "reference-omission"])
def test_imported_cache_cannot_override_selected_bundle_after_its_own_anchor_is_rewritten(environment, corruption):
    first, tmp = environment["first"], environment["tmp"]
    old_bundle = Path(first["bundle_path"])
    old_manifest_sha = file_sha256(old_bundle / "manifest.json")
    sidecar = decisions(first, tmp / "accepted.json", "First explicit title", approved=True)
    adopted = pipeline.process_file(environment["source"], tmp / "adopted", environment["config"],
                                     sidecar=sidecar, decision_bundle=old_bundle)
    assert adopted["status"] == "candidate"
    path = cache_metadata(adopted)
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if corruption == "processor-proof":
        metadata["processors"].append({"name": "source-mappings", "status": "pass", "authority": "invented"})
    elif corruption == "reference-policy":
        reference = path.parent / "reference.pdf"
        shutil.copyfile(path.parent / "prepared.pdf", reference)
        metadata["reference"] = {"policy": "authoritative-character-mapping", "sha256": file_sha256(reference)}
    else:
        # An unexpected metadata shape must differ from the selected bundle's
        # explicit absence of a reference, even if false-y to later code.
        metadata["reference"] = {}
    write_sidecar(metadata, path)
    anchor = Path(metadata["anchor_bundle"])
    anchor_report_path = anchor / "report.json"
    anchor_report = json.loads(anchor_report_path.read_text(encoding="utf-8"))
    anchor_report["checkpoint_provenance_sha256"] = pipeline._metadata_digest(metadata)
    write_sidecar(anchor_report, anchor_report_path)
    manifest_path = anchor / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["report.json"] = file_sha256(anchor_report_path)
    write_sidecar(manifest, manifest_path)
    assert pipeline.verify_bundle(anchor)  # coherent local corruption simulation
    sidecar = decisions(first, tmp / "second-accepted.json", "Second explicit title", approved=True)
    failed = pipeline.process_file(environment["source"], tmp / "adopted", environment["config"],
                                    sidecar=sidecar, decision_bundle=old_bundle)
    assert_failed_without_pdf(failed)
    assert "selected immutable review bundle" in failed["error"]["message"]
    assert file_sha256(old_bundle / "manifest.json") == old_manifest_sha
    assert pipeline.verify_bundle(old_bundle)
    assert environment["calls"].count("processed.pdf") == 2


def test_source_change_while_queued_is_refused_before_processing(environment):
    original = file_sha256(environment["source"])
    with environment["source"].open("ab") as stream:
        stream.write(b"\n% A new source revision while queued\n")
    with pytest.raises(ValueError, match="waiting"):
        pipeline.process_file(environment["source"], environment["tmp"] / "queued", environment["config"], expected_source_sha256=original)
    assert not (environment["tmp"] / "queued").exists()


def test_accepted_sidecar_bytes_changed_during_processing_cannot_publish(environment, monkeypatch):
    first, tmp = environment["first"], environment["tmp"]
    sidecar = decisions(first, tmp / "accepted.json", "An explicitly accepted title", approved=True)
    validate = validation.validate_pdf

    def alter_decision_file(path, *args, **kwargs):
        report = validate(path, *args, **kwargs)
        if Path(path).name == "processed.pdf":
            with sidecar.open("ab") as stream:
                stream.write(b"\n ")
        return report

    monkeypatch.setattr(validation, "validate_pdf", alter_decision_file)
    failed = pipeline.process_file(environment["source"], tmp / "changed-sidecar", environment["config"],
                                    sidecar=sidecar, decision_bundle=first["bundle_path"])
    assert_failed_without_pdf(failed)
    assert "decisions changed" in failed["error"]["message"].lower()
    assert pipeline.verify_bundle(first["bundle_path"])


@pytest.mark.parametrize("layout", ["embedded", "windows-venv"])
def test_selected_ocr_runtime_sources_and_dependency_metadata_change_preparation_identity(tmp_path, layout):
    """Read fake selected runtime files; never import or execute the fake OCR.

    Embedded layout matches the private factory._pth Lib/site-packages entry.
    Both layouts retain the prior OCR-source/dependency-metadata hash scope;
    unrelated host sites do not gain authority and OCR-off remains independent.
    """
    root = tmp_path / "selected-ocr"
    executable = root / "Scripts/python.exe" if layout == "windows-venv" else root / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"Named fake executable; must never run")
    site = root / "Lib/site-packages"
    code = site / "ocrmypdf/__init__.py"
    metadata = site / "named_dependency-1.0.dist-info/METADATA"
    code.parent.mkdir(parents=True)
    metadata.parent.mkdir(parents=True)
    code.write_text("# Named selected OCR source version one\n", encoding="utf-8")
    metadata.write_text("Name: named-dependency\nVersion: 1.0\n", encoding="utf-8")
    config = RuntimeConfig(project_root=tmp_path, java_home=tmp_path / "absent-java",
        odl_jar=tmp_path / "absent.jar", validator_cli=tmp_path / "absent-validator/verapdf.bat",
        ocr_python=executable, tesseract_dir=tmp_path / "absent-tesseract", ocr_mode="skip")
    original = pipeline.implementation_digest(config)
    code.write_text("# Named selected OCR source version two\n", encoding="utf-8")
    assert pipeline.implementation_digest(config) != original
    code.write_text("# Named selected OCR source version one\n", encoding="utf-8")
    assert pipeline.implementation_digest(config) == original
    metadata.write_text("Name: named-dependency\nVersion: 1.1\n", encoding="utf-8")
    assert pipeline.implementation_digest(config) != original
    config.ocr_mode = "off"
    off = pipeline.implementation_digest(config)
    code.write_text("# Unused OCR source changed again\n", encoding="utf-8")
    metadata.write_text("Name: named-dependency\nVersion: 1.2\n", encoding="utf-8")
    assert pipeline.implementation_digest(config) == off
