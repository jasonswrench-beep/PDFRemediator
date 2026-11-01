"""Transactional release tests with real PDF inspection and all-page fidelity.

Only the expensive external validator is replaced by an explicitly named test
stub. Its exact-input fingerprint is retained. Engine preservation/validator
adapters have separate tests; these cases exercise the release boundary.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import threading
import uuid

import pikepdf
import pytest

from pdf_remediator import inspection, pipeline, processors, validation
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import bind_approval, write_sidecar


@pytest.fixture(scope="session")
def tagged_control(tmp_path_factory):
    """Regenerate the original synthetic control; never read local corpus PDFs.

    The generator uses invariant ReportLab output, bundled Vera fonts (with
    their license copied beside the fixture), fixed metadata and deterministic
    pikepdf IDs. Missing packages/fonts fail rather than selecting a substitute.
    This structural control is not evidence of native PDF/UA qualification.
    """
    source = Path(__file__).resolve().parents[1] / "eval" / "build_corpus.py"
    spec = importlib.util.spec_from_file_location("pipeline_synthetic_corpus", source)
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    directory = tmp_path_factory.mktemp("pipeline-synthetic-control")
    corpus.register_fonts(directory)
    path = directory / "tagged-control.pdf"
    corpus.tag_control(path)
    return path



@pytest.fixture(scope="session")
def generated_chapter(tmp_path_factory):
    """Synthetic occurrence semantics; not historical native-engine evidence."""
    spec = importlib.util.spec_from_file_location("pipeline_figure_corpus",
        Path(__file__).resolve().parents[1] / "eval" / "build_corpus.py")
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    directory = tmp_path_factory.mktemp("synthetic-figure-control")
    corpus.register_fonts(directory)
    path = directory / "figure-control.pdf"
    corpus.tagged_figure_control(path)
    repeated = directory / "repeat.pdf"
    corpus.tagged_figure_control(repeated)
    assert path.read_bytes() == repeated.read_bytes()
    return path


def test_synthetic_control_is_byte_reproducible_and_fully_linked(tagged_control, tmp_path):
    # A second independent generation must retain exact bytes, not only pixels.
    spec = importlib.util.spec_from_file_location("pipeline_control_repeat",
        Path(__file__).resolve().parents[1] / "eval" / "build_corpus.py")
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    corpus.register_fonts(tmp_path)
    repeated = tmp_path / "repeat.pdf"
    corpus.tag_control(repeated)
    assert repeated.read_bytes() == tagged_control.read_bytes()
    inspected = inspection.inspect_pdf(tagged_control)
    assert inspected["structure"]["phantom_tree"] is False
    for identifier in ("content-linkage", "content-coverage", "font-embedding"):
        assert next(check for check in inspected["checks"] if check["id"] == identifier)["status"] == "pass"



def test_generated_chapter_retains_distinct_occurrences_of_one_image(generated_chapter):
    from pdf_remediator.sidecar import collect_decisions

    inventory = collect_decisions(generated_chapter)
    assert not inventory["inventory_errors"]
    figures = [item for item in inventory["decisions"] if item["kind"] == "figure-description"]
    assert len(figures) == 2
    assert len({item["id"] for item in figures}) == 2
    assert len({item["element"] for item in figures}) == 2
    assert len({item["context_sha256"] for item in figures}) == 2
    assert all(item["status"] == "pending" and item["value"] == item["current"] == "" for item in figures)
    with pikepdf.open(generated_chapter) as pdf:
        page = pdf.pages[0]
        images = [obj for obj in page.Resources.XObject.values() if obj.Subtype == pikepdf.Name.Image]
        assert len(images) == 1
        draws = [str(operands[0]) for operands, operator in pikepdf.parse_content_stream(page)
                 if str(operator) == "Do"]
        assert len(draws) == 2 and draws[0] == draws[1]
    inspected = inspection.inspect_pdf(generated_chapter)
    for identifier in ("content-linkage", "content-coverage", "font-embedding"):
        assert next(check for check in inspected["checks"] if check["id"] == identifier)["status"] == "pass"


def test_generated_chapter_has_proven_separate_figure_caption_contexts(generated_chapter):
    import pypdfium2 as pdfium
    from pdf_remediator import assistance
    from pdf_remediator.sidecar import collect_decisions

    figures = [item for item in collect_decisions(generated_chapter)["decisions"]
               if item["kind"] == "figure-description"]
    with pdfium.PdfDocument(generated_chapter) as pdf:
        page = pdf[0]
        try:
            contexts = [assistance._figure_context(page, item) for item in figures]
        finally:
            page.close()
    assert len(contexts) == 2
    assert all(item["image_status"] == "included-safe-crop" for item in contexts)
    assert all(item["caption_scope"] == "near proven figure bounds" for item in contexts)
    assert "garden plots" in contexts[0]["caption_context"]
    assert "archive bins" not in contexts[0]["caption_context"]
    assert "archive bins" in contexts[1]["caption_context"]
    assert "garden plots" not in contexts[1]["caption_context"]
    assert contexts[0]["image"]["bounds_pdf"] != contexts[1]["image"]["bounds_pdf"]


def edit_pdf(path, operation):
    destination = path.with_name("changed-" + uuid.uuid4().hex + ".pdf")
    with pikepdf.open(path) as pdf:
        operation(pdf)
        pdf.save(destination, deterministic_id=True)
    os.replace(destination, path)


@pytest.fixture
def input_pdf(tmp_path, tagged_control):
    path = tmp_path / "input" / "reading.pdf"
    path.parent.mkdir()
    shutil.copyfile(tagged_control, path)
    return path


@pytest.fixture
def fast_validator(monkeypatch):
    calls = []

    def run(pdf_path, output_dir, *args, **kwargs):
        path, destination = Path(pdf_path), Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        raw = destination / "test-validator-evidence.txt"
        raw.write_text("TEST STUB; no actual validator was invoked for this regression test.\n", encoding="utf-8")
        observed_sha = pipeline.sha(path)
        calls.append({"path": path, "sha256": observed_sha, "kind": "final" if path.name == "processed.pdf" else "baseline"})
        return {"status": "pass", "validator": "test-stub", "version": "test-stub", "profile": "ua1", "is_compliant": True,
                "counts": {"passedRules": 106, "passedChecks": 106, "failedRules": 0, "failedChecks": 0},
                "failed_rules": [], "assertion_detail_coverage": {"status": "complete"},
                "input_sha256": observed_sha, "raw_report": str(raw),
                "execution": {"status": "completed", "returncode": 0}}

    monkeypatch.setattr(validation, "validate_pdf", run)
    # Pin the real implementation fingerprint for the duration of each test:
    # parallel agents may write unrelated modules while a test is executing.
    digest = pipeline.implementation_digest(RuntimeConfig())
    monkeypatch.setattr(pipeline, "implementation_digest", lambda config: digest)
    return calls


def run(input_pdf, tmp_path, **kwargs):
    config = kwargs.pop("config", RuntimeConfig())
    return pipeline.process_file(input_pdf, tmp_path / "output", config, **kwargs)


def final_count(calls):
    return sum(call["kind"] == "final" for call in calls)


def bundle(report):
    return Path(report["bundle_path"])


def assert_no_published_pdf(report):
    assert report["output"] is None
    assert not list(bundle(report).rglob("*.pdf"))


def sidecar_for(report, path, title, approve=True):
    data = json.loads((bundle(report) / "decisions.json").read_text(encoding="utf-8"))
    decision = next(item for item in data["decisions"] if item["kind"] == "title")
    decision["value"] = title
    if approve:
        bind_approval(decision, "Human Reviewer", "2026-10-15")
    write_sidecar(data, path)
    return path


def test_candidate_publication_is_atomic_and_contains_coherent_bound_evidence(input_pdf, tmp_path, fast_validator, monkeypatch):
    source_hash = pipeline.sha(input_pdf)
    real_replace = os.replace
    publications = []

    def observe(source, destination):
        stage, final = Path(source), Path(destination)
        if stage.is_dir() and stage.parent.name == ".staging":
            assert not final.exists()
            assert (stage / "candidate.pdf").is_file()
            manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["complete"] is True
            assert manifest["files"]
            assert all(pipeline.sha(stage / relative) == digest for relative, digest in manifest["files"].items())
            staged_report = json.loads((stage / "report.json").read_text(encoding="utf-8"))
            assert staged_report["output"]["sha256"] == pipeline.sha(stage / "candidate.pdf")
            assert staged_report["gate1"]["input_sha256"] == staged_report["output"]["sha256"]
            assert staged_report["fidelity"]["after_sha256"] == staged_report["output"]["sha256"]
            assert all((stage / name).is_file() for name in ("decisions.json", "review.json", "review.html", "manifest.json"))
            publications.append(final)
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", observe)
    report = run(input_pdf, tmp_path)
    assert report["status"] == "candidate"
    assert report["manual_review"]["items"] and not report["manual_review"]["complete"]
    assert report["output"]["review_only"] is False
    assert pipeline.sha(input_pdf) == source_hash
    assert report["original_unchanged"] is True
    assert publications == [bundle(report)]
    assert pipeline.verify_bundle(bundle(report))
    assert final_count(fast_validator) == 1
    assert len(fast_validator) == 2
    assert report["validation_delta"]["status"] == "compared"


def test_intact_semantic_blocker_keeps_only_a_labeled_review_draft(input_pdf, tmp_path, fast_validator):
    report = run(input_pdf, tmp_path, config=RuntimeConfig(title="Untitled"))
    assert report["status"] == "needs-manual"
    assert report["gate2"]["status"] == "fail"
    assert report["fidelity"]["status"] == "pass"
    assert Path(report["output"]["path"]).name == "review-draft.pdf"
    assert report["output"]["review_only"] is True
    assert not (bundle(report) / "candidate.pdf").exists()


def test_phantom_tree_is_failed_and_never_published(input_pdf, tmp_path, fast_validator, monkeypatch):
    normalizer = processors.normalize_catalog

    def break_tree(source, destination, *args):
        result = normalizer(source, destination, *args)

        def change(pdf):
            def alter(node):
                if isinstance(node, pikepdf.Array):
                    for child in node:
                        alter(child)
                elif isinstance(node, pikepdf.Dictionary):
                    kids = node.get("/K")
                    if isinstance(kids, int):
                        node["/K"] = kids + 9000
                    else:
                        alter(kids)
            alter(pdf.Root.StructTreeRoot)
        edit_pdf(Path(destination), change)
        return result

    monkeypatch.setattr(pipeline, "normalize_catalog", break_tree)
    report = run(input_pdf, tmp_path)
    assert report["inspection"]["structure"]["phantom_tree"] is True
    assert report["status"] == "failed"
    assert_no_published_pdf(report)


def test_partially_broken_structure_is_failed_without_pdf(input_pdf, tmp_path, fast_validator, monkeypatch):
    normalizer = processors.normalize_catalog

    def break_one_reference(source, destination, *args):
        result = normalizer(source, destination, *args)

        def change(pdf):
            document = pdf.Root.StructTreeRoot.K
            document.K.append(pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                              S=pikepdf.Name.P, P=document, Pg=pdf.pages[0].obj, K=9000)))
        edit_pdf(Path(destination), change)
        return result

    monkeypatch.setattr(pipeline, "normalize_catalog", break_one_reference)
    report = run(input_pdf, tmp_path)
    assert report["inspection"]["structure"]["phantom_tree"] is False
    linkage = next(check for check in report["inspection"]["checks"] if check["id"] == "content-linkage")
    assert linkage["status"] == "fail"
    assert report["status"] == "failed"
    assert_no_published_pdf(report)


def test_visible_change_with_intact_tags_fails_fidelity_and_publishes_no_pdf(input_pdf, tmp_path, fast_validator, monkeypatch):
    normalizer = processors.normalize_catalog

    def change_appearance(source, destination, *args):
        result = normalizer(source, destination, *args)

        def change(pdf):
            page = pdf.pages[0]
            streams = page.obj.Contents
            streams = list(streams) if isinstance(streams, pikepdf.Array) else [streams]
            page.obj.Contents = pikepdf.Array(streams + [pdf.make_stream(b"/Artifact BMC q 1 0 0 rg 0 0 50 50 re f Q EMC")])
        edit_pdf(Path(destination), change)
        return result

    monkeypatch.setattr(pipeline, "normalize_catalog", change_appearance)
    report = run(input_pdf, tmp_path)
    assert report["fidelity"]["status"] == "fail"
    assert any(page["render_status"] == "fail" for page in report["fidelity"]["pages"])
    assert report["status"] in {"needs-manual", "failed"}
    assert_no_published_pdf(report)


def test_read_only_check_does_not_create_or_modify_a_pdf(input_pdf, tmp_path, fast_validator):
    original = input_pdf.read_bytes()
    report = run(input_pdf, tmp_path, mode="check")
    assert report["mode"] == "check"
    assert report["assessed_artifact"]["sha256"] == pipeline.sha(input_pdf)
    assert input_pdf.read_bytes() == original
    assert_no_published_pdf(report)
    assert not (tmp_path / "output" / ".cache").exists()


def test_immutable_bundle_requires_explicit_resume(input_pdf, tmp_path, fast_validator):
    report = run(input_pdf, tmp_path)
    with pytest.raises(FileExistsError):
        run(input_pdf, tmp_path)
    resumed = run(input_pdf, tmp_path, resume=True)
    assert resumed["resumed"] is True
    assert resumed["run_fingerprint"] == report["run_fingerprint"]
    assert final_count(fast_validator) == 1


def test_tampered_bundle_cannot_be_resumed(input_pdf, tmp_path, fast_validator):
    report = run(input_pdf, tmp_path)
    with (bundle(report) / "candidate.pdf").open("ab") as stream:
        stream.write(b"\n% Changed bytes after assessment\n")
    assert pipeline.verify_bundle(bundle(report)) is False
    with pytest.raises(FileExistsError):
        run(input_pdf, tmp_path, resume=True)
    assert final_count(fast_validator) == 1


def test_manifest_cannot_claim_completion_by_omitting_required_files(input_pdf, tmp_path, fast_validator):
    report = run(input_pdf, tmp_path)
    manifest = bundle(report) / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"] = {}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert pipeline.verify_bundle(bundle(report)) is False


def test_manifest_path_traversal_is_refused(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    directory = tmp_path / "bundle"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({"complete": True,
        "files": {"../outside.txt": pipeline.sha(outside)}}), encoding="utf-8")
    assert pipeline.verify_bundle(directory) is False


def test_approved_sidecar_reuses_exact_checkpoint_and_revalidates_final_hash(input_pdf, tmp_path, fast_validator):
    first = run(input_pdf, tmp_path)
    checkpoint = Path(first["decision_source"]["path"])
    source_hash, prepared_hash = pipeline.sha(input_pdf), pipeline.sha(checkpoint)
    sidecar = sidecar_for(first, tmp_path / "human-decisions.json", "Explicit human-selected reading title")
    updated = run(input_pdf, tmp_path, sidecar=sidecar, resume=True)
    assert updated["checkpoint_reused"] is True
    assert updated["status"] == "candidate"
    assert bundle(updated) != bundle(first)
    assert pipeline.sha(input_pdf) == source_hash
    assert pipeline.sha(checkpoint) == prepared_hash
    assert updated["gate1"]["input_sha256"] == updated["output"]["sha256"]
    assert updated["fidelity"]["after_sha256"] == updated["output"]["sha256"]
    assert final_count(fast_validator) == 2
    with pikepdf.open(updated["output"]["path"]) as pdf:
        assert str(pdf.docinfo.Title) == "Explicit human-selected reading title"


def test_changed_prepared_checkpoint_blocks_resume_before_decision_application(input_pdf, tmp_path, fast_validator):
    first = run(input_pdf, tmp_path)
    sidecar = sidecar_for(first, tmp_path / "human-decisions.json", "Explicit title")
    with Path(first["decision_source"]["path"]).open("ab") as stream:
        stream.write(b"\n% Prepared checkpoint changed\n")
    failed = run(input_pdf, tmp_path, sidecar=sidecar, resume=True)
    assert failed["status"] == "failed"
    assert "checkpoint" in failed["error"]["message"].lower()
    assert_no_published_pdf(failed)
    assert final_count(fast_validator) == 1


def test_edit_after_approval_blocks_resume_without_using_old_candidate(input_pdf, tmp_path, fast_validator):
    first = run(input_pdf, tmp_path)
    sidecar = sidecar_for(first, tmp_path / "human-decisions.json", "Approved title")
    approved = run(input_pdf, tmp_path, sidecar=sidecar, resume=True)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["decisions"][0]["value"] = "Edited without reapproval"
    write_sidecar(data, sidecar)
    failed = run(input_pdf, tmp_path, sidecar=sidecar, resume=True)
    assert failed["status"] == "failed"
    assert "approval" in failed["error"]["message"].lower()
    assert_no_published_pdf(failed)
    assert pipeline.verify_bundle(bundle(approved))
    assert final_count(fast_validator) == 2


def test_batch_isolates_bad_files_and_same_names_with_different_content(tmp_path, fast_validator, tagged_control):
    inputs = tmp_path / "inputs"
    a, b = inputs / "a" / "same.pdf", inputs / "b" / "same.pdf"
    for file in (a, b):
        file.parent.mkdir(parents=True)
        shutil.copyfile(tagged_control, file)
    edit_pdf(b, lambda pdf: pdf.docinfo.__setitem__("/Title", "A different explicitly titled document"))
    malformed = inputs / "broken.pdf"
    malformed.write_bytes(b"This is deliberately not a PDF")
    hashes = {file: pipeline.sha(file) for file in (a, b, malformed)}
    results, summary = pipeline.batch(inputs, tmp_path / "output", RuntimeConfig(), recurse=True)
    assert summary["files_found"] == summary["processed"] == 3
    assert sorted(report["status"] for report in results) == ["candidate", "candidate", "failed"]
    candidates = [report for report in results if report["status"] == "candidate"]
    assert len({report["bundle_path"] for report in candidates}) == 2
    assert all(pipeline.verify_bundle(bundle(report)) for report in results)
    assert {file: pipeline.sha(file) for file in hashes} == hashes


def test_recursive_discovery_excludes_outputs_and_hidden_dependencies(tmp_path):
    inputs = tmp_path / "input"
    paths = [inputs / "reading.pdf", inputs / "sub" / "chapter.PDF",
             inputs / "output" / "candidate.pdf", inputs / ".cache" / "copied.pdf",
             inputs / "tools" / "tool.pdf"]
    for file in paths:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"inventory-only")
    assert pipeline.discover(inputs, inputs / "output", recurse=True) == sorted(paths[:2], key=str)


def test_cancellation_after_fidelity_removes_a_prepared_candidate(input_pdf, tmp_path, fast_validator, monkeypatch):
    event = threading.Event()
    compare = inspection.compare_fidelity

    def stop_after_comparison(*args, **kwargs):
        result = compare(*args, **kwargs)
        event.set()
        return result

    monkeypatch.setattr(inspection, "compare_fidelity", stop_after_comparison)
    source_hash = pipeline.sha(input_pdf)
    report = run(input_pdf, tmp_path, cancel=event)
    assert report["cancelled"] is True
    assert report["status"] == "failed"
    assert_no_published_pdf(report)
    assert pipeline.sha(input_pdf) == source_hash
    assert pipeline.verify_bundle(bundle(report))


def test_cancelled_batch_stops_between_files_and_publishes_a_summary(input_pdf, tmp_path, fast_validator):
    event = threading.Event()
    event.set()
    results, summary = pipeline.batch(input_pdf.parent, tmp_path / "output", RuntimeConfig(), cancel=event)
    assert results == []
    assert summary["cancelled"] is True
    assert summary["files_found"] == 1 and summary["processed"] == 0
    assert (tmp_path / "output" / "batch-summary.json").is_file()


def test_interrupted_run_can_resume_while_retaining_failed_evidence(input_pdf, tmp_path, fast_validator):
    event = threading.Event()

    def cancel_at_validator(message):
        if "validate PDF/UA-1" in message:
            event.set()

    interrupted = run(input_pdf, tmp_path, cancel=event, progress=cancel_at_validator)
    assert interrupted["status"] == "failed" and interrupted["cancelled"]
    assert_no_published_pdf(interrupted)
    failed_report_bytes = (bundle(interrupted) / "report.json").read_bytes()
    event.clear()
    resumed = run(input_pdf, tmp_path, cancel=event, resume=True)
    assert resumed["status"] == "candidate"
    assert resumed["checkpoint_reused"] is True
    assert bundle(resumed) != bundle(interrupted)
    assert (bundle(interrupted) / "report.json").read_bytes() == failed_report_bytes
    assert pipeline.verify_bundle(bundle(interrupted)) and pipeline.verify_bundle(bundle(resumed))
    assert final_count(fast_validator) == 1


def test_old_human_sidecar_is_not_reused_after_original_changes(input_pdf, tmp_path, fast_validator):
    first = run(input_pdf, tmp_path)
    sidecar = sidecar_for(first, tmp_path / "human-decisions.json", "Title for the old source")
    edit_pdf(input_pdf, lambda pdf: pdf.docinfo.__setitem__("/Subject", "A new source revision"))
    changed_source_hash = pipeline.sha(input_pdf)
    stale = run(input_pdf, tmp_path, sidecar=sidecar, resume=True)
    assert stale["status"] == "failed"
    assert "source" in stale["error"]["message"].lower()
    assert_no_published_pdf(stale)
    assert pipeline.sha(input_pdf) == changed_source_hash
    assert final_count(fast_validator) == 1


def test_byte_identical_inputs_with_same_name_are_not_processing_failures(tmp_path, fast_validator, tagged_control):
    inputs = tmp_path / "inputs"
    paths = [inputs / "a" / "same.pdf", inputs / "b" / "same.pdf"]
    for file in paths:
        file.parent.mkdir(parents=True)
        shutil.copyfile(tagged_control, file)
    results, summary = pipeline.batch(inputs, tmp_path / "output", RuntimeConfig(), recurse=True)
    assert summary["processed"] == 2
    assert all(report["status"] == "candidate" for report in results)
    assert {Path(report["input"]["path"]) for report in results} == set(paths)


def test_validator_pass_cannot_release_later_changed_pdf_bytes(input_pdf, tmp_path, fast_validator, monkeypatch):
    validator = validation.validate_pdf

    def change_after_validation(path, *args, **kwargs):
        result = validator(path, *args, **kwargs)
        if Path(path).name == "processed.pdf":
            with Path(path).open("ab") as stream:
                stream.write(b"\n% Changed after strict validation\n")
        return result

    monkeypatch.setattr(validation, "validate_pdf", change_after_validation)
    report = run(input_pdf, tmp_path)
    assert report["status"] == "failed"
    assert_no_published_pdf(report)


def test_inspection_pass_cannot_release_later_changed_pdf_bytes(input_pdf, tmp_path, fast_validator, monkeypatch):
    inspect = inspection.inspect_pdf

    def change_after_inspection(path, *args, **kwargs):
        result = inspect(path, *args, **kwargs)
        if Path(path).name == "processed.pdf":
            with Path(path).open("ab") as stream:
                stream.write(b"\n% Changed after supplemental inspection\n")
        return result

    monkeypatch.setattr(inspection, "inspect_pdf", change_after_inspection)
    report = run(input_pdf, tmp_path)
    assert report["status"] == "failed"
    assert_no_published_pdf(report)


def test_candidate_copy_must_retain_assessed_exact_bytes(input_pdf, tmp_path, fast_validator, monkeypatch):
    copy_file = shutil.copyfile

    def change_published_copy(source, destination, *args, **kwargs):
        result = copy_file(source, destination, *args, **kwargs)
        if Path(destination).name == "candidate.pdf":
            with Path(destination).open("ab") as stream:
                stream.write(b"\n% Changed while copying release artifact\n")
        return result

    monkeypatch.setattr(shutil, "copyfile", change_published_copy)
    report = run(input_pdf, tmp_path)
    assert report["status"] == "failed"
    assert_no_published_pdf(report)


@pytest.mark.parametrize("option", ["preserve_painting", "allow_tag_regrouping", "repair_source_mappings"])
@pytest.mark.parametrize("value", ["'false'", "0", "1"])
def test_repair_selection_configuration_requires_actual_boolean_types(tmp_path, option, value):
    from pdf_remediator.config import load_config
    config = tmp_path / "invalid.toml"
    config.write_text(f"[runtime]\n{option} = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(config)


@pytest.mark.parametrize("document_kind", ["unknown", "reading", "slides", "equations"])
def test_supported_document_kind_configuration_values_are_explicit(tmp_path, document_kind):
    from pdf_remediator.config import load_config
    config = tmp_path / "kind.toml"
    config.write_text(f"[runtime]\ndocument_kind = '{document_kind}'\n", encoding="utf-8")
    assert load_config(config).document_kind == document_kind


def test_unknown_document_kind_is_the_default_and_unknown_values_are_refused(tmp_path):
    from pdf_remediator.config import load_config
    assert load_config().document_kind == "unknown"
    config = tmp_path / "invalid-kind.toml"
    config.write_text("[runtime]\ndocument_kind = 'a-filename-specific-exception'\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(config)


@pytest.mark.parametrize("document_kind", ["slides", "equations"])
def test_declared_unsupported_content_is_manual_without_processing(input_pdf, tmp_path, fast_validator, document_kind):
    report = run(input_pdf, tmp_path, config=RuntimeConfig(document_kind=document_kind))
    assert report["status"] == "needs-manual"
    assert_no_published_pdf(report)
    assert not fast_validator
    assert not (tmp_path / "output" / ".cache").exists()


@pytest.mark.parametrize("document_kind", ["unknown", "reading"])
def test_supported_document_declarations_still_require_human_scope_review(input_pdf, tmp_path, fast_validator, document_kind):
    report = run(input_pdf, tmp_path, config=RuntimeConfig(document_kind=document_kind))
    assert report["status"] == "candidate"
    item = next(item for item in report["manual_review"]["items"] if item["category"] == "unsupported-content")
    assert item["required"] is True and item["status"] == "pending"


def test_check_without_output_does_not_print_paths_to_deleted_temp_bundles(input_pdf, fast_validator, capsys):
    from pdf_remediator.cli import main
    result = main(["check", str(input_pdf), "--json"])
    captured = capsys.readouterr()
    assert result == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["results"][0]["status"] == "candidate"
    assert ".check-temp" not in captured.out
    assert payload["results"][0].get("bundle_path") is None


def test_empty_batch_is_not_reported_as_a_success(tmp_path, capsys):
    from pdf_remediator.cli import main
    empty = tmp_path / "empty"
    empty.mkdir()
    result = main(["fix", str(empty), "-o", str(tmp_path / "output"), "--json"])
    captured = capsys.readouterr()
    assert result == 1, captured.out
    payload = json.loads(captured.out)
    assert payload["files_found"] == payload["processed"] == 0


@pytest.mark.parametrize("document_kind", ["unknown", "reading", "slides", "equations"])
def test_document_kind_cli_declaration_controls_supported_route(input_pdf, tmp_path, fast_validator, capsys, document_kind):
    from pdf_remediator.cli import main
    result = main(["fix", str(input_pdf), "-o", str(tmp_path / "output"),
                   "--document-kind", document_kind, "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    unsupported = document_kind in {"slides", "equations"}
    assert result == (2 if unsupported else 0), captured.err
    report = payload["results"][0]
    assert report["status"] == ("needs-manual" if unsupported else "candidate")
    if unsupported:
        assert report["output"] is None
        assert not fast_validator


@pytest.mark.parametrize("option,value", [("timeout_seconds", "nan"), ("timeout_seconds", "inf"),
                                        ("validator_timeout_seconds", "nan"),
                                        ("memory_limit_bytes", "inf"), ("memory_limit_bytes", "nan"),
                                        ("timeout_seconds", "true"), ("java_heap_mb", "true")])
def test_resource_limits_cannot_be_disabled_by_nonfinite_or_boolean_configuration(tmp_path, option, value):
    from pdf_remediator.config import load_config
    config = tmp_path / "invalid-limits.toml"
    config.write_text(f"[runtime]\n{option} = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(config)


@pytest.mark.parametrize("document_kind", ["slides", "equations"])
def test_check_honors_explicit_unsupported_declarations(input_pdf, tmp_path, fast_validator, capsys, document_kind):
    from pdf_remediator.cli import main
    result = main(["check", str(input_pdf), "-o", str(tmp_path / "output"),
                   "--document-kind", document_kind, "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 2, captured.err
    assert payload["results"][0]["status"] == "needs-manual"
    assert payload["results"][0]["output"] is None
