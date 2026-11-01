"""the LMS checker-category integration with authored PDFs and named validator doubles.

Real parsing, reviewed structure writes, supplemental gates, exact all-page
render/text fidelity, immutable bundles and review recovery run here. No native
validator/tagger, provider, OCR, browser or the LMS checker service runs.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import textwrap
import threading

import pikepdf
import pytest
from reportlab.pdfgen import canvas

from pdf_remediator import checks, inspection, pipeline, sidecar, workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import (LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE,
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE, PASSAGE_LANGUAGE_INVENTORY_PROFILE, NAVIGATION_INVENTORY_PROFILE, SEMANTIC_TREE_INVENTORY_PROFILE,TABLE_INVENTORY_PROFILE,FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE,
    bind_approval, collect_decisions, file_sha256, load_sidecar, write_sidecar)
from test_language import TEXTS
from test_pipeline import fast_validator, tagged_control


@pytest.fixture(autouse=True)
def registered_authored_fonts(tagged_control):
    """Reuse the source-generated control's bundled, licensed Vera registration."""
    return tagged_control


def authored_pdf(tmp_path, *, roles=("H1", "P"), pages=1, language="en-US", body=None, gray=0):
    raw = tmp_path / "authored-visible-content.pdf"
    output = tmp_path / "authored-tagged-input.pdf"
    document = canvas.Canvas(str(raw), pagesize=(612, 792), invariant=1)
    document.setTitle("Authored the LMS checker integration reading")
    for page in range(pages):
        y = 730
        for mcid, role in enumerate(roles):
            document._code.append(f"/{role} <</MCID {mcid}>> BDC")
            document.setFillGray(gray)
            document.setFont("SyntheticVera", 19 if mcid == 0 else 11)
            text = body if body and mcid == len(roles) - 1 else f"AUTHORED-PAGE-{page + 1}-BLOCK-{mcid + 1}. A source-authored reading section."
            for line in textwrap.wrap(text, width=75 if mcid else 45):
                document.drawString(44, y, line)
                y -= 16 if mcid else 24
            y -= 24
            document._code.append("EMC")
        document.showPage()
    document.save()
    with pikepdf.open(raw) as pdf:
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        logical = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        elements, parents = [], []
        for page_number, page in enumerate(pdf.pages):
            page_elements = [pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                S=pikepdf.Name("/" + role), P=logical, Pg=page.obj, K=mcid)) for mcid, role in enumerate(roles)]
            elements.extend(page_elements)
            parents.extend([page_number, pikepdf.Array(page_elements)])
            page.StructParents = page_number
            page.Tabs = pikepdf.Name.S
        logical.K = pikepdf.Array(elements)
        root.K = logical
        root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(parents)))
        root.ParentTreeNextKey = len(pdf.pages)
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = language
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.save(output, deterministic_id=True)
    return output


def execute(source, directory, **kwargs):
    return pipeline.process_file(source, directory, RuntimeConfig(), **kwargs)


def decision_data(report):
    return load_sidecar(Path(report["bundle_path"]) / "decisions.json")


def check(report, identifier):
    return next(item for item in report["gate2"]["checks"] if item["id"] == identifier)


def snapshot(directory):
    return {str(path.relative_to(directory)): file_sha256(path) for path in directory.rglob("*") if path.is_file()}


def assert_exact_fidelity(report, page_count):
    fidelity = report["fidelity"]
    assert fidelity["status"] == "pass" and len(fidelity["pages"]) == page_count
    assert fidelity["thresholds"] == {"pixel_delta": 0, "max_changed_fraction": 0.0}
    for page in fidelity["pages"]:
        assert page["render_status"] == "pass" and page["changed_pixel_fraction"] == 0
        assert page["text"]["removed_tokens"] == page["text"]["added_tokens"] == 0
        assert page["text"]["ordered_status"] == "pass"


def test_new_processing_exposes_reviewed_structure_controls_without_granting_approval(tmp_path, fast_validator):
    source = authored_pdf(tmp_path)
    source_bytes = source.read_bytes()
    report = execute(source, tmp_path / "runs")
    assert report["status"] == "candidate", report.get("error")
    data = decision_data(report)
    assert data["inventory_profile"] == EMPTY_TAG_INVENTORY_PROFILE
    older = collect_decisions(report["decision_source"]["path"], report["input"]["sha256"],
        inventory_profile=STRUCTURAL_INVENTORY_PROFILE)
    assert [item for item in data["decisions"] if item["kind"] not in
        {"figure-purpose", "structure-role", "page-language", "passage-language",
         "annotation-name", "link-name", "link-target", "bookmark-entry", "bookmark-additions",
         "semantic-role", "reading-order", "tree-move", "semantic-list", "table-structure", "form-controls", "empty-tag-removal"}] == older["decisions"]
    structural = [item for item in data["decisions"] if item["kind"] == "heading-tag"]
    assert {item["current"] for item in structural} == {"H1", "P"}
    assert all(item["status"] == "pending" and item["value"] == item["current"] for item in structural)
    state = tmp_path / "review.json"
    workspace.create_workspace(report["bundle_path"], state)
    view = workspace.get_view(state)
    assert not view["stale"] and view["verification"] == "not-verified"
    assert view["counts"]["manual_approved"] == view["counts"]["decision_approved"] == 0
    assert source.read_bytes() == source_bytes and report["data_sent"]["document_api_calls"] == 0
    assert_exact_fidelity(report, 1)


@pytest.mark.parametrize("roles,pages,identifier", [
    (("P", "P"), 3, "marked-headings"),
    (("H2", "P"), 1, "heading-start-level"),
    (("H1", "H7"), 1, "heading-depth"),
    (("H1", "H3"), 1, "heading-sequence"),
])
def test_real_heading_defects_block_candidate_and_remain_review_drafts(tmp_path, fast_validator, roles, pages, identifier):
    source = authored_pdf(tmp_path, roles=roles, pages=pages)
    report = execute(source, tmp_path / "runs")
    assert report["status"] == "needs-manual", report.get("error")
    finding = check(report, identifier)
    assert finding["status"] == "fail" and finding["blocking"]
    assert identifier in {item["id"] for item in report["gate2"]["blockers"]}
    assert report["output"]["review_only"] and Path(report["output"]["path"]).name == "review-draft.pdf"
    assert report["gate1"]["validator"] == "test-stub"
    assert_exact_fidelity(report, pages)


def test_two_page_heading_absence_is_not_mislabeled_as_three_page_failure(tmp_path, fast_validator):
    report = execute(authored_pdf(tmp_path, roles=("P", "P"), pages=2), tmp_path / "runs")
    assert report["status"] == "candidate", report.get("error")
    assert check(report, "marked-headings")["status"] == "not-applicable"
    assert_exact_fidelity(report, 2)


def test_accepted_existing_tag_fix_reruns_all_gates_and_preserves_prior_bundle_and_every_page(tmp_path, fast_validator, monkeypatch):
    source = authored_pdf(tmp_path, roles=("P", "P"), pages=3)
    original_hash = file_sha256(source)
    previous = execute(source, tmp_path / "before")
    assert previous["status"] == "needs-manual"
    prior_files = snapshot(Path(previous["bundle_path"]))
    accepted = decision_data(previous)
    target = next(item for item in accepted["decisions"] if item["kind"] == "heading-tag" and item["page"] == 1)
    target["value"] = "H1"
    bind_approval(target, "Synthetic integration reviewer", "2026-10-21")
    accepted_path = write_sidecar(accepted, tmp_path / "accepted-structural.json")
    calls_before = len(fast_validator)
    assessments, fidelities = [], []
    real_assess, real_fidelity = checks.assess, inspection.compare_fidelity
    def fresh_assess(inspected, *args, **kwargs):
        assessments.append(inspected["sha256"])
        return real_assess(inspected, *args, **kwargs)
    def fresh_fidelity(before, after, **kwargs):
        fidelities.append((file_sha256(before), file_sha256(after)))
        return real_fidelity(before, after, **kwargs)
    monkeypatch.setattr(checks, "assess", fresh_assess)
    monkeypatch.setattr(inspection, "compare_fidelity", fresh_fidelity)
    report = execute(source, tmp_path / "after", sidecar=accepted_path, decision_bundle=previous["bundle_path"])
    assert report["status"] == "candidate", report.get("error")
    assert report["checkpoint_reused"] and report["output"]["path"] != previous["output"]["path"]
    assert check(report, "marked-headings")["status"] == "pass"
    assert all(check(report, identifier)["status"] == "pass" for identifier in ("heading-start-level", "heading-depth", "heading-sequence"))
    final_hash = report["output"]["sha256"]
    assert [call["sha256"] for call in fast_validator[calls_before:]] == [original_hash, final_hash]
    assert assessments == [final_hash] and fidelities == [(original_hash, final_hash)]
    assert report["gate1"]["input_sha256"] == report["fidelity"]["after_sha256"] == final_hash
    assert file_sha256(source) == original_hash and snapshot(Path(previous["bundle_path"])) == prior_files
    with pikepdf.open(report["output"]["path"]) as pdf:
        assert str(pdf.Root.StructTreeRoot.K.K[0].S) == "/H1"
        assert all(str(item.S) == "/P" for item in list(pdf.Root.StructTreeRoot.K.K)[1:])
    assert_exact_fidelity(report, 3)


def test_old_format_saved_review_and_checkpoint_keep_legacy_inventory_when_applied(tmp_path, tagged_control, fast_validator, monkeypatch):
    source = tmp_path / "old-format-source.pdf"
    shutil.copyfile(tagged_control, source)
    current_collect = sidecar.collect_decisions
    def legacy_inventory_producer(pdf, source_sha=None, **kwargs):
        return current_collect(pdf, source_sha, inventory_profile=LEGACY_INVENTORY_PROFILE)
    # Authored old-format producer double only. Restore the current inventory
    # code before opening, recording, exporting or applying the old review.
    with monkeypatch.context() as old_producer:
        old_producer.setattr(sidecar, "collect_decisions", legacy_inventory_producer)
        previous = execute(source, tmp_path / "before")
    assert previous["status"] == "candidate", previous.get("error")
    assert "inventory_profile" not in decision_data(previous)
    prior_files = snapshot(Path(previous["bundle_path"]))
    state = tmp_path / "old-saved-review.json"
    workspace.create_workspace(previous["bundle_path"], state)
    view = workspace.get_view(state)
    view = workspace.review_item(state, "reading-order", "pending", "Synthetic reviewer", "2026-10-21", view["revision"], notes="Preserve the older saved review and this note")
    view = workspace.edit_decision(state, "metadata:title", "Reviewed legacy title", view["revision"])
    view = workspace.approve_decision(state, "metadata:title", "Synthetic reviewer", "2026-10-21", view["revision"])
    exported = workspace.export_workspace(state, tmp_path / "exports", view["revision"])
    saved_bytes = state.read_bytes()
    report = execute(source, tmp_path / "after", sidecar=exported["sidecar_path"], decision_bundle=previous["bundle_path"])
    assert report["status"] == "candidate", report.get("error")
    assert "inventory_profile" not in decision_data(report)
    assert {item["kind"] for item in decision_data(report)["decisions"]} == {"title", "language"}
    reopened = workspace.get_view(state)
    assert not reopened["stale"] and state.read_bytes() == saved_bytes
    assert next(item for item in reopened["manual_items"] if item["id"] == "reading-order")["notes"] == "Preserve the older saved review and this note"
    assert snapshot(Path(previous["bundle_path"])) == prior_files
    with pikepdf.open(report["output"]["path"]) as pdf:
        assert str(pdf.docinfo.Title) == "Reviewed legacy title"
    assert_exact_fidelity(report, 1)


def test_reviewed_language_decision_resolves_real_high_confidence_mismatch(tmp_path, fast_validator):
    source = authored_pdf(tmp_path, language="fr", body=TEXTS["en"])
    original_hash = file_sha256(source)
    previous = execute(source, tmp_path / "before")
    assert previous["status"] == "needs-manual", previous.get("error")
    language = check(previous, "language-correctness")
    assert language["status"] == "fail" and language["blocking"]
    assert language["evidence"]["suggested_language"] == "en"
    data = decision_data(previous)
    target = next(item for item in data["decisions"] if item["kind"] == "language")
    assert target["value"] == target["current"] == "fr" and target["status"] == "pending"
    target["value"] = language["evidence"]["suggested_language"]
    bind_approval(target, "Synthetic language reviewer", "2026-10-21")
    accepted = write_sidecar(data, tmp_path / "reviewed-language.json")
    calls_before = len(fast_validator)
    report = execute(source, tmp_path / "after", sidecar=accepted, decision_bundle=previous["bundle_path"])
    assert report["status"] == "candidate", report.get("error")
    assert check(report, "language-correctness")["status"] == "pass"
    assert len(fast_validator) - calls_before == 2 and file_sha256(source) == original_hash
    with pikepdf.open(report["output"]["path"]) as pdf:
        assert str(pdf.Root.Lang) == "en"
    with pikepdf.open(source) as pdf:
        assert str(pdf.Root.Lang) == "fr"
    assert report["data_sent"]["document_api_calls"] == 0
    assert_exact_fidelity(report, 1)


def test_low_contrast_measurement_stays_advisory_with_required_human_applicability_review(tmp_path, fast_validator):
    source = authored_pdf(tmp_path, gray=.75)
    original_hash = file_sha256(source)
    report = execute(source, tmp_path / "runs")
    assert report["status"] == "candidate", report.get("error")
    measured = check(report, "contrast")
    assert measured["status"] == "fail" and measured["blocking"] is False
    assert measured["evidence"]["failed_text_objects"] > 0
    failed = [item for item in measured["evidence"]["measurements"] if item["status"] == "fail"]
    assert failed and all(item["ratio"] < item["minimum_ratio"] for item in failed)
    assert "contrast" not in {item["id"] for item in report["gate2"]["blockers"]}
    manual = next(item for item in report["manual_review"]["items"] if item["id"] == "contrast")
    assert manual["required"] and manual["status"] == "pending"
    assert "exceptions" in manual["detail"] and "does not silently recolor" in manual["detail"]
    assert file_sha256(source) == original_hash
    state = tmp_path / "contrast-review.json"
    workspace.create_workspace(report["bundle_path"], state)
    view = workspace.get_view(state)
    finding = next(item for item in view["repair_findings"] if item["id"] == "contrast")
    assert finding["status"] == "fail" and finding["evidence"] == measured["evidence"]
    assert view["verification"] == "not-verified" and view["counts"]["manual_approved"] == 0
    assert_exact_fidelity(report, 1)


@pytest.mark.parametrize("interrupt_call", [1, 2, 3])
def test_inspection_cancellation_receives_token_and_prevents_pdf_publication(tmp_path, tagged_control, fast_validator, monkeypatch, interrupt_call):
    source = tmp_path / "cancel-source.pdf"
    shutil.copyfile(tagged_control, source)
    original_hash = file_sha256(source)
    token = threading.Event()
    real_inspect = inspection.inspect_pdf
    inspected_paths = []
    def interrupt_at_stage(path, cancel=None):
        assert cancel is token, "Every baseline/preparation/final inspection must receive the cancellation token"
        inspected_paths.append(Path(path))
        if len(inspected_paths) == interrupt_call:
            token.set()
            raise InterruptedError("Authored inspection-stage cancellation")
        return real_inspect(path, cancel=cancel)
    monkeypatch.setattr(inspection, "inspect_pdf", interrupt_at_stage)
    report = execute(source, tmp_path / "runs", cancel=token)
    assert len(inspected_paths) == interrupt_call
    assert report["status"] == "failed" and report["cancelled"]
    assert report["error"]["type"] == "InterruptedError" and report["output"] is None
    root = Path(report["bundle_path"])
    assert pipeline.verify_bundle(root) and not list(root.rglob("*.pdf"))
    assert file_sha256(source) == original_hash
