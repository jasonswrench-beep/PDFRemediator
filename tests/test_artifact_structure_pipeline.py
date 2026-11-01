"""Independent authored-PDF integration for reviewed artifact/structure edits.

The external validator is an explicitly named double. Parsing, source-authoring,
decision application, inspection, all-page pixels/text, immutable publication and
review-state bindings are real. These tests do not grant semantic accessibility
approval and invoke no browser, desktop, AI provider, OCR or native tagger.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path

import pikepdf
import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from pdf_remediator import checks, inspection, pipeline, sidecar, workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import (
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE, PASSAGE_LANGUAGE_INVENTORY_PROFILE, NAVIGATION_INVENTORY_PROFILE, SEMANTIC_TREE_INVENTORY_PROFILE,TABLE_INVENTORY_PROFILE,FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE, LEGACY_INVENTORY_PROFILE,
    STRUCTURAL_INVENTORY_PROFILE, DecisionError, bind_approval, collect_decisions,
    file_sha256, load_sidecar, make_automatic_authorization, write_sidecar,
)
from test_pipeline import fast_validator, tagged_control


@pytest.fixture(autouse=True)
def registered_fonts(tagged_control):
    """The ordinary source-generated control registers its licensed Vera font."""
    return tagged_control


def artifact_source(directory, *, root_role="Document", section_role="Sect", scanned_first=False):
    """Independent two-page source with live navigation and an unrelated link."""
    directory.mkdir(parents=True, exist_ok=True)
    raw, output = directory / "authored-paint.pdf", directory / "authored-source.pdf"
    c = canvas.Canvas(str(raw), pagesize=(400, 600), invariant=1)
    c.setTitle("Authored decorative and structure preservation control")

    def text(role, mcid, value, y):
        c._code.append(f"/{role} <</MCID {mcid}>> BDC")
        c.setFillColorRGB(0, 0, 0)
        c.setFont("SyntheticVera", 15 if role in {"H1", "H2"} else 10)
        c.drawString(35, y, value)
        c._code.append("EMC")

    def drawing(mcid, *, image=False):
        c._code.append(f"/Figure <</MCID {mcid}>> BDC")
        if image:
            with Image.new("RGB", (32, 24), (80, 120, 180)) as pixels:
                data = io.BytesIO()
                pixels.save(data, format="PNG")
                data.seek(0)
                c.drawImage(ImageReader(data), 60, 400, width=200, height=100)
        else:
            c.setFillColorRGB(.2, .4, .7)
            c.rect(60, 400, 200, 100, stroke=0, fill=1)
        c._code.append("EMC")

    c.bookmarkPage("opening")
    c.addOutlineEntry("Opening section", "opening", level=0)
    if scanned_first:
        drawing(0, image=True)
        c._code.append("/Figure <</MCID 1>> BDC")
        c.setFillColorRGB(.1, .1, .1)
        c.circle(300, 200, 20, stroke=0, fill=1)
        c._code.append("EMC")
    else:
        text("H1", 0, "Opening section", 555)
        text("P", 1, "Every original word must remain selectable.", 530)
        drawing(2)
    c.showPage()
    c.bookmarkPage("continuation")
    c.addOutlineEntry("Continuation", "continuation", level=0)
    text("H1" if scanned_first else "H2", 0, "Continuation", 555)
    text("P", 1, "Unchanged content, illustration and navigation.", 530)
    drawing(2)
    text("Link", 3, "Return to opening section", 65)
    c.showPage()
    c.save()

    with pikepdf.open(raw) as pdf:
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name("/" + root_role), P=tree, T="Whole authored document"))
        sections = [pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name("/" + section_role), P=document, T=f"Authored section {i + 1}"))
            for i in range(2)]
        parents = []
        for index, page in enumerate(pdf.pages):
            roles = (["Figure", "Figure"] if scanned_first else ["H1", "P", "Figure"]) if index == 0 else ["H1" if scanned_first else "H2", "P", "Figure", "Link"]
            children = []
            for mcid, role in enumerate(roles):
                node = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                    S=pikepdf.Name("/" + role), P=sections[index], Pg=page.obj, K=mcid))
                if role == "Figure" and (index == 1 or scanned_first):
                    node.Alt = "Authored blue rectangle showing the control illustration."
                    node.A = pikepdf.Dictionary(O=pikepdf.Name.Layout,
                        BBox=pikepdf.Array([60, 400, 260, 500]))
                children.append(node)
            sections[index].K = pikepdf.Array(children)
            parents.extend([index, pikepdf.Array(children)])
            page.StructParents = index
            page.Tabs = pikepdf.Name.S
        second = pdf.pages[1]
        link = sections[1].K[3]
        annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Link, Rect=pikepdf.Array([35, 60, 245, 78]),
            Contents="Return to opening section", NM="authored-preserved-link",
            Border=pikepdf.Array([0, 0, 0]), C=pikepdf.Array([0, 0, 1]), F=4,
            Dest=pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit]), StructParent=2))
        second.Annots = pikepdf.Array([annotation])
        link.K = pikepdf.Array([3, pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Pg=second.obj, Obj=annotation)])
        parents.extend([2, link])
        document.K = pikepdf.Array(sections)
        tree.K = document
        tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(parents)))
        tree.ParentTreeNextKey = 3
        pdf.Root.StructTreeRoot = tree
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = "en-US"
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([
            0, pikepdf.Dictionary(S=pikepdf.Name.r), 1, pikepdf.Dictionary(S=pikepdf.Name.D, St=5)]))
        pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([
            "authored-opening-destination", pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit])])))
        with output.open("wb") as stream:
            pdf.save(stream, deterministic_id=True)
    return output


def execute(source, output, **kwargs):
    return pipeline.process_file(source, output, RuntimeConfig(), **kwargs)


def decisions(report):
    return load_sidecar(Path(report["bundle_path"]) / "decisions.json")


def select(data, kind, page=None):
    return next(item for item in data["decisions"] if item["kind"] == kind
                and (page is None or item.get("page") == page))


def files(root):
    return {p.relative_to(root).as_posix(): file_sha256(p) for p in root.rglob("*") if p.is_file()}


def canonical(value):
    """Independent semantic serialization; no production transformation helper."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, pikepdf.Name):
        return {"name": str(value)}
    if isinstance(value, pikepdf.String):
        return {"string_bytes": bytes(value).hex()}
    if isinstance(value, pikepdf.Array):
        return [canonical(item) for item in value]
    if isinstance(value, pikepdf.Stream):
        return {"dictionary": {str(k): canonical(v) for k, v in value.items()
                               if k not in {"/Length", "/Filter", "/DecodeParms"}},
                "decoded_stream_sha256": hashlib.sha256(value.read_bytes()).hexdigest()}
    if isinstance(value, pikepdf.Dictionary):
        return {str(k): canonical(v) for k, v in value.items()}
    return str(value)


def independent_paint_and_navigation(path):
    """All non-mark instructions, resource bytes, boxes and raw annotation fields."""
    with pikepdf.open(path) as pdf:
        numbers = {page.obj.objgen: i + 1 for i, page in enumerate(pdf.pages)}
        rows = []
        for page in pdf.pages:
            instructions = [i for i in pikepdf.parse_content_stream(page)
                            if str(i.operator) not in {"BMC", "BDC", "EMC"}]
            annotations = []
            for item in page.obj.get("/Annots", []):
                attrs = {}
                for key, value in item.items():
                    if key == "/Dest":
                        attrs[key] = [numbers[value[0].objgen], *[canonical(x) for x in list(value)[1:]]]
                    elif key == "/P":
                        attrs[key] = numbers[value.objgen]
                    else:
                        attrs[key] = canonical(value)
                annotations.append(attrs)
            rows.append({"operators": pikepdf.unparse_content_stream(instructions),
                "resources": canonical(page.Resources), "annotations": annotations,
                "mediabox": list(page.mediabox), "cropbox": list(page.cropbox),
                "rotation": int(page.obj.get("/Rotate", 0))})
    inspected = inspection.inspect_pdf(path)
    return rows, inspected["navigation"]


def exact_fidelity(report):
    fidelity = report["fidelity"]
    assert fidelity["status"] == "pass" and len(fidelity["pages"]) == 2
    assert fidelity["thresholds"] == {"pixel_delta": 0, "max_changed_fraction": 0.0}
    assert fidelity["text"]["ordered_status"] == "pass"
    for page in fidelity["pages"]:
        assert page["changed_pixel_fraction"] == 0
        assert page["text"]["removed_tokens"] == page["text"]["added_tokens"] == 0
        assert page["text"]["ordered_status"] == "pass"
        assert page["page_boxes_status"] == page["annotations_status"] == "pass"


def semantic_reviews(report, accepted):
    """A mechanical edit creates new, exactly bound human purpose judgments."""
    changed = {item["id"]: item for item in accepted["decisions"]
               if item["kind"] in {"figure-purpose", "structure-role"}
               and item["status"] == "approved" and item["value"] != item["current"]}
    rows = [item for item in report["manual_review"]["items"]
            if item["id"].startswith("structural-decision-")]
    assert len(rows) == len({item["id"] for item in rows}) == len(changed)
    assert {item["decision_id"] for item in rows} == set(changed)
    assert report["manual_review"]["artifact_sha256"] == report["output"]["sha256"]
    for item in rows:
        decision = changed[item["decision_id"]]
        assert item["id"] == "structural-decision-" + hashlib.sha256(decision["id"].encode()).hexdigest()[:20]
        assert item["required"] is True and item["status"] == "pending"
        assert item["category"] == "reading-order" and item["page"] == decision.get("page")
        assert item["context_sha256"] == decision["context_sha256"]
        assert item["evidence"] == {
            "kind": decision["kind"], "element": decision.get("element"),
            "structure_path": decision.get("structure_path"), "references": decision["references"],
            "binding": decision["binding"], "previous_value": decision["current"],
            "applied_value": decision["value"],
        }
        assert all(key not in item for key in ("reviewer", "reviewed_at", "notes", "approval_sha256"))
        if decision["kind"] == "figure-purpose":
            assert "meaningful logo or illustration" in item["detail"]
            assert "does not establish its purpose" in item["detail"]
        else:
            assert "does not establish correct heading hierarchy or reading order" in item["detail"]
    if rows:
        assert report["manual_review"]["complete"] is False
    return rows


def test_new_processing_lists_pending_artifact_structure_controls_without_approval(tmp_path, fast_validator):
    source = artifact_source(tmp_path / "source")
    original = source.read_bytes()
    report = execute(source, tmp_path / "runs")
    assert report["status"] == "needs-manual", report.get("error")
    data = decisions(report)
    assert data["inventory_profile"] == EMPTY_TAG_INVENTORY_PROFILE
    older = collect_decisions(report["decision_source"]["path"], report["input"]["sha256"],
        inventory_profile=ARTIFACT_STRUCTURE_INVENTORY_PROFILE)
    assert [item for item in data["decisions"] if item["kind"] not in
        {"page-language", "passage-language", "annotation-name", "link-name", "link-target",
         "bookmark-entry", "bookmark-additions", "semantic-role", "reading-order", "tree-move", "semantic-list", "table-structure", "form-controls", "empty-tag-removal"}] == older["decisions"]
    purpose = select(data, "figure-purpose", 1)
    assert purpose["current"] == purpose["value"] == "Figure"
    assert purpose["structural_eligible"] and purpose["allowed_values"] == ["Figure", "Artifact"]
    assert purpose["figure_bbox"]["status"] == "missing"
    assert all(item["status"] == "pending" and item["value"] == item["current"] for item in data["decisions"])
    state = tmp_path / "review.json"
    workspace.create_workspace(report["bundle_path"], state)
    view = workspace.get_view(state)
    assert not view["stale"] and view["verification"] == "not-verified"
    assert view["counts"]["manual_approved"] == view["counts"]["decision_approved"] == 0
    assert report["data_sent"]["document_api_calls"] == 0 and source.read_bytes() == original
    assert semantic_reviews(report, data) == []
    exact_fidelity(report)


def test_accepted_decorative_change_rechecks_all_gates_and_preserves_review_navigation_and_paint(
        tmp_path, fast_validator, monkeypatch):
    source = artifact_source(tmp_path / "source")
    original_sha = file_sha256(source)
    before_contract = independent_paint_and_navigation(source)
    previous = execute(source, tmp_path / "before")
    assert previous["status"] == "needs-manual"
    assert next(x for x in previous["gate2"]["checks"] if x["id"] == "figure-alternatives")["status"] == "fail"
    bundle = Path(previous["bundle_path"])
    protected = files(bundle)
    state = tmp_path / "prior-review.json"
    workspace.create_workspace(bundle, state)
    view = workspace.get_view(state)
    view = workspace.review_item(state, "reading-order", "pending", "Synthetic artifact reviewer",
        "2026-10-27", view["revision"], "Keep this unfinished review note attached to the earlier result.")
    target = select(view, "figure-purpose", 1)
    view = workspace.edit_decision(state, target["id"], "Artifact", view["revision"])
    view = workspace.approve_decision(state, target["id"], "Synthetic artifact reviewer", "2026-10-27", view["revision"])
    exported = workspace.export_workspace(state, tmp_path / "exports", view["revision"])
    saved = state.read_bytes()
    assert exported["requires_reprocessing"] and not exported["ledger_eligible"]
    assessments = []
    real_assess = checks.assess
    def observe_assess(result, *args, **kwargs):
        assessments.append(result["sha256"])
        return real_assess(result, *args, **kwargs)
    monkeypatch.setattr(checks, "assess", observe_assess)
    count = len(fast_validator)
    report = execute(source, tmp_path / "after", sidecar=exported["sidecar_path"], decision_bundle=bundle)
    assert report["status"] == "candidate", report.get("error")
    assert report["checkpoint_reused"] and report["output"]["path"] != previous["output"]["path"]
    final = Path(report["output"]["path"])
    assert independent_paint_and_navigation(final) == before_contract
    with pikepdf.open(final) as pdf:
        first, second = list(pdf.Root.StructTreeRoot.K.K)
        assert [str(child.S) for child in first.K] == ["/H1", "/P"]
        assert [str(child.S) for child in second.K] == ["/H2", "/P", "/Figure", "/Link"]
        slots = pdf.Root.StructTreeRoot.ParentTree.Nums[1]
        assert len(slots) == 3 and slots[2] is None
        assert list(first.K[0].K if isinstance(first.K[0].K, pikepdf.Array) else [first.K[0].K]) == [0]
        marks = [(list(i.operands), str(i.operator)) for i in pikepdf.parse_content_stream(pdf.pages[0])
                 if str(i.operator) in {"BMC", "BDC"}]
        assert sum(str(operands[0]) == "/Artifact" for operands, _ in marks) == 1
        assert not any(len(operands) > 1 and isinstance(operands[1], pikepdf.Dictionary)
                       and operands[1].get("/MCID") == 2 for operands, _ in marks)
    inspected = inspection.inspect_pdf(final)
    assert inspected["structure"]["errors"] == []
    assert all(next(c for c in inspected["checks"] if c["id"] == kind)["status"] == "pass"
               for kind in ("content-linkage", "content-coverage", "link-structure"))
    final_sha = file_sha256(final)
    assert assessments == [final_sha]
    assert [x["sha256"] for x in fast_validator[count:]] == [original_sha, final_sha]
    assert report["gate1"]["input_sha256"] == report["fidelity"]["after_sha256"] == final_sha
    required = semantic_reviews(report, load_sidecar(exported["sidecar_path"]))
    assert len(required) == 1 and required[0]["decision_id"] == target["id"]
    exact_fidelity(report)
    fresh = tmp_path / "fresh-review.json"
    workspace.create_workspace(report["bundle_path"], fresh)
    fresh_view = workspace.get_view(fresh)
    assert fresh_view["verification"] == "not-verified" and fresh_view["counts"]["manual_approved"] == 0
    assert all(item["status"] == "pending" for item in fresh_view["manual_items"])
    assert {item["id"] for item in fresh_view["manual_items"] if item["id"].startswith("structural-decision-")} == {item["id"] for item in required}
    assert all(not item.get("notes") for item in fresh_view["manual_items"])
    assert workspace.get_view(state) == view and state.read_bytes() == saved
    assert files(bundle) == protected and file_sha256(source) == original_sha
    assert report["data_sent"]["document_api_calls"] == 0


def test_reviewed_root_and_section_roles_change_no_content_or_other_structure(tmp_path, fast_validator):
    source = artifact_source(tmp_path / "source", root_role="Div", section_role="Div")
    previous = execute(source, tmp_path / "before")
    protected = files(Path(previous["bundle_path"]))
    accepted = decisions(previous)
    roles = [item for item in accepted["decisions"] if item["kind"] == "structure-role"]
    root = next(item for item in roles if item["structure_path"] == "root/K")
    root["value"] = "Document"
    bind_approval(root, "Synthetic structure reviewer", "2026-10-27")
    sections = [item for item in roles if item["structure_path"] != "root/K" and "Sect" in item["allowed_values"]]
    assert len(sections) == 2
    for item in sections:
        item["value"] = "Sect"
        bind_approval(item, "Synthetic structure reviewer", "2026-10-27")
    sidecar_path = write_sidecar(accepted, tmp_path / "accepted-roles.json")
    report = execute(source, tmp_path / "after", sidecar=sidecar_path, decision_bundle=previous["bundle_path"])
    assert report["output"] is not None, report.get("error")
    assert independent_paint_and_navigation(report["output"]["path"]) == independent_paint_and_navigation(source)
    with pikepdf.open(report["output"]["path"]) as pdf:
        document = pdf.Root.StructTreeRoot.K
        assert str(document.S) == "/Document" and str(document.T) == "Whole authored document"
        assert [str(node.S) for node in document.K] == ["/Sect", "/Sect"]
        assert [str(node.T) for node in document.K] == ["Authored section 1", "Authored section 2"]
        assert [str(child.S) for child in document.K[0].K] == ["/H1", "/P", "/Figure"]
        assert str(document.K[1].K[3].S) == "/Link"
    assert files(Path(previous["bundle_path"])) == protected
    assert len(semantic_reviews(report, accepted)) == 3
    exact_fidelity(report)


def test_marking_an_image_decorative_does_not_hide_the_scanned_page_blocker(tmp_path, fast_validator):
    source = artifact_source(tmp_path / "source", scanned_first=True)
    previous = execute(source, tmp_path / "before")
    accepted = decisions(previous)
    target = next(item for item in accepted["decisions"] if item["kind"] == "figure-purpose"
                  and item.get("page") == 1 and any(ref.get("mcid") == 0 for ref in item["references"]))
    assert target["structural_eligible"]
    target["value"] = "Artifact"
    bind_approval(target, "Synthetic image-purpose reviewer", "2026-10-27")
    path = write_sidecar(accepted, tmp_path / "accepted-image-purpose.json")
    report = execute(source, tmp_path / "after", sidecar=path, decision_bundle=previous["bundle_path"])
    assert report["status"] == "needs-manual" and report["output"]["review_only"], report.get("error")
    scan = next(item for item in report["gate2"]["checks"] if item["id"] == "scan-text-layer")
    assert scan["status"] == "fail" and scan["blocking"]
    assert scan["evidence"]["image_only_pages_without_text"] == [1]
    assert any(item["category"] == "image-and-ocr" for item in report["manual_review"]["items"])
    assert independent_paint_and_navigation(report["output"]["path"]) == independent_paint_and_navigation(source)
    assert len(semantic_reviews(report, accepted)) == 1
    exact_fidelity(report)


@pytest.mark.parametrize("kind", ["figure-purpose", "structure-role"])
def test_pending_new_structural_drafts_never_change_the_candidate(tmp_path, fast_validator, kind):
    source = artifact_source(tmp_path / "source", root_role="Div")
    previous = execute(source, tmp_path / "before")
    data = decisions(previous)
    item = select(data, kind, 1 if kind == "figure-purpose" else None)
    item["value"] = "Artifact" if kind == "figure-purpose" else "Document"
    assert item["status"] == "pending"
    path = write_sidecar(data, tmp_path / "pending.json")
    report = execute(source, tmp_path / "after", sidecar=path, decision_bundle=previous["bundle_path"])
    assert report["output"] is not None
    assert file_sha256(report["output"]["path"]) == previous["output"]["sha256"]
    applied = next(x for x in report["processors"] if x["name"] == "approved-decisions")
    assert applied["changed"] == [] and applied["approved"] == [] and applied["auto_accepted"] == []
    assert semantic_reviews(report, data) == []
    exact_fidelity(report)


@pytest.mark.parametrize("kind", ["figure-purpose", "structure-role"])
def test_structural_ids_cannot_be_swept_into_automatic_authorization(tmp_path, fast_validator, kind):
    source = artifact_source(tmp_path / "source", root_role="Div")
    previous = execute(source, tmp_path / "before")
    data = decisions(previous)
    item = select(data, kind)
    with pytest.raises(DecisionError):
        make_automatic_authorization(data["source_sha256"], data["document_sha256"],
            "2026-10-27", decision_ids=[item["id"]])
    item["value"] = "Artifact" if kind == "figure-purpose" else "Document"
    item["status"] = "auto-accepted"
    item["automatic_acceptance_sha256"] = "0" * 64
    path = write_sidecar(data, tmp_path / "forged-automatic.json")
    before = files(Path(previous["bundle_path"]))
    report = execute(source, tmp_path / "refused", sidecar=path, decision_bundle=previous["bundle_path"])
    assert report["status"] == "failed" and report["output"] is None
    assert not list(Path(report["bundle_path"]).rglob("*.pdf"))
    assert files(Path(previous["bundle_path"])) == before


@pytest.mark.parametrize("profile", [LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE])
def test_older_profiles_and_saved_reviews_are_not_widened_by_artifact_controls(tmp_path, fast_validator, monkeypatch, profile):
    source = artifact_source(tmp_path / "source")
    original_collect = sidecar.collect_decisions
    expected = original_collect(source, inventory_profile=profile)
    assert not {"figure-purpose", "structure-role"} & {i["kind"] for i in expected["decisions"]}
    assert all("allowed_values" not in item and "figure_bbox" not in item for item in expected["decisions"])
    def older_producer(path, source_sha=None, **kwargs):
        return original_collect(path, source_sha, inventory_profile=profile)
    with monkeypatch.context() as producer:
        producer.setattr(sidecar, "collect_decisions", older_producer)
        previous = execute(source, tmp_path / "before")
    prior = decisions(previous)
    assert semantic_reviews(previous, prior) == []
    assert sidecar.inventory_profile_for(prior) == profile
    assert not {"figure-purpose", "structure-role"} & {i["kind"] for i in prior["decisions"]}
    state = tmp_path / "saved-old-review.json"
    workspace.create_workspace(previous["bundle_path"], state)
    view = workspace.get_view(state)
    view = workspace.review_item(state, "reading-order", "pending", "Synthetic old-review author",
        "2026-10-27", view["revision"], "Keep my old inventory and unfinished review.")
    saved = state.read_bytes()
    assert workspace.get_view(state) == view and state.read_bytes() == saved
    assert sidecar.inventory_profile_for(workspace.load_workspace(state)["sidecar"]) == profile
    assert workspace.load_workspace(state)["sidecar"]["decisions"] == prior["decisions"]
    assert original_collect(source, inventory_profile=profile) == expected
    assert file_sha256(source) == expected["source_sha256"]


def test_later_title_edit_replays_artifact_roles_and_requires_all_semantic_reviews_again(tmp_path, fast_validator):
    source = artifact_source(tmp_path / "source", root_role="Div", section_role="Div")
    original_sha = file_sha256(source)
    original_contract = independent_paint_and_navigation(source)
    previous = execute(source, tmp_path / "before")
    old_bundle = Path(previous["bundle_path"])
    old_files = files(old_bundle)
    accepted = decisions(previous)
    target = select(accepted, "figure-purpose", 1)
    target["value"] = "Artifact"
    bind_approval(target, "Synthetic semantic fixture author", "2026-10-27")
    roles = [item for item in accepted["decisions"] if item["kind"] == "structure-role"]
    assert len(roles) == 3
    for item in roles:
        item["value"] = "Document" if item["structure_path"] == "root/K" else "Sect"
        bind_approval(item, "Synthetic semantic fixture author", "2026-10-27")
    accepted_path = write_sidecar(accepted, tmp_path / "accepted-structure.json")
    changed = execute(source, tmp_path / "changed", sidecar=accepted_path, decision_bundle=old_bundle)
    assert changed["status"] == "candidate", changed.get("error")
    first_required = semantic_reviews(changed, accepted)
    assert len(first_required) == 4
    first_ids = {item["id"] for item in first_required}
    changed_bundle = Path(changed["bundle_path"])
    changed_files = files(changed_bundle)
    state = tmp_path / "structure-review.json"
    workspace.create_workspace(changed_bundle, state)
    view = workspace.get_view(state)
    assert view["verification"] == "not-verified" and view["counts"]["manual_approved"] == 0
    # A synthetic positive choice demonstrates invalidation, not real semantic
    # acceptance; the new output below must require every judgment afresh.
    view = workspace.review_item(state, first_required[0]["id"], "approved", "Synthetic semantic fixture author",
        "2026-10-27", view["revision"], "Historical fixture observation remains with this earlier artifact.")
    assert view["counts"]["manual_approved"] == 1
    title = select(view, "title")
    view = workspace.edit_decision(state, title["id"], "Reviewed metadata follow-up fixture title", view["revision"])
    assert view["counts"]["manual_approved"] == 0
    view = workspace.approve_decision(state, title["id"], "Synthetic semantic fixture author", "2026-10-27", view["revision"])
    prior_item = next(item for item in view["manual_items"] if item["id"] == first_required[0]["id"])
    assert prior_item["status"] == "pending" and prior_item["notes"] == "Historical fixture observation remains with this earlier artifact."
    exported = workspace.export_workspace(state, tmp_path / "exports", view["revision"])
    saved_bytes = state.read_bytes()
    replay = load_sidecar(exported["sidecar_path"])
    final = execute(source, tmp_path / "metadata-followup", sidecar=exported["sidecar_path"], decision_bundle=changed_bundle)
    assert final["status"] == "candidate", final.get("error")
    required = semantic_reviews(final, replay)
    assert len(required) == 4 and {item["id"] for item in required} == first_ids
    assert final["manual_review"]["artifact_sha256"] != changed["manual_review"]["artifact_sha256"]
    assert final["output"]["sha256"] != changed["output"]["sha256"]
    assert independent_paint_and_navigation(final["output"]["path"]) == original_contract
    with pikepdf.open(final["output"]["path"]) as pdf:
        root = pdf.Root.StructTreeRoot.K
        assert str(root.S) == "/Document" and [str(item.S) for item in root.K] == ["/Sect", "/Sect"]
        assert [str(item.S) for item in root.K[0].K] == ["/H1", "/P"]
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][2] is None
        assert str(pdf.docinfo.Title) == "Reviewed metadata follow-up fixture title"
    fresh_state = tmp_path / "metadata-review.json"
    workspace.create_workspace(final["bundle_path"], fresh_state)
    fresh = workspace.get_view(fresh_state)
    assert fresh["verification"] == "not-verified" and fresh["counts"]["manual_approved"] == 0
    assert all(item["status"] == "pending" and not item.get("notes") for item in fresh["manual_items"])
    assert {item["id"] for item in fresh["manual_items"] if item["id"].startswith("structural-decision-")} == first_ids
    assert workspace.get_view(state) == view and state.read_bytes() == saved_bytes
    assert files(old_bundle) == old_files and files(changed_bundle) == changed_files
    assert file_sha256(source) == original_sha and final["data_sent"]["document_api_calls"] == 0
    exact_fidelity(final)
