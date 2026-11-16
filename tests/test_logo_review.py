"""Logo and branding review: screening evidence, grouping, and per-occurrence decisions. Authored fixtures; gate labels are stubs.

The pictures are small synthetic rectangles of pixels. Nothing here reads a real logo, and a passing test says nothing about what a
real organisation's logo should be called.
"""
import copy
import http.client
import json
from pathlib import Path
import shutil
import threading

import pikepdf
import pytest

from pdf_remediator import logo_review, web, workspace as ws
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import (ARTIFACT_STRUCTURE_INVENTORY_PROFILE, LEGACY_INVENTORY_PROFILE, approval_digest,
                                    collect_decisions, file_sha256, write_sidecar)

REVIEWER = "Synthetic Logo Reviewer"
DATE = "2026-11-16"


def _image(pdf, pixels, width, height):
    stream = pdf.make_stream(bytes(pixels))
    stream.Type, stream.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
    stream.Width, stream.Height, stream.ColorSpace, stream.BitsPerComponent = width, height, pikepdf.Name.DeviceRGB, 8
    return stream


def logo_pdf(path, *, pages=4, photo_alt="A crowd at the opening ceremony", seal_alt="Institutional logo"):
    """Four pages. The same small picture is a figure in every page's header; page 3 adds a large photograph and page 4 a seal
    that is described as a logo; page 2 adds a small vector-drawn figure. Page content is real text and tagged figures."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.new() as pdf:
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        root.K = pikepdf.Array([document])
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        logo = _image(pdf, [30, 90, 160] * 8 + [255, 255, 255] * 8, 4, 4)
        photo = _image(pdf, [(i * 7) % 256 for i in range(3 * 16)], 4, 4)
        seal = _image(pdf, [200, 20, 20] * 16, 4, 4)
        sections, nums = [], []
        for number in range(pages):
            page = pdf.add_blank_page(page_size=(400, 500))
            page.obj.StructParents = number
            section = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Sect, P=document))
            sections.append(section)
            content = [b"/H1 <</MCID 0>> BDC BT /F1 14 Tf 50 400 Td (Chapter heading) Tj ET EMC",
                       b"/Figure <</MCID 1>> BDC q 60 0 0 30 40 440 cm /Logo Do Q EMC",
                       b"/P <</MCID 2>> BDC BT /F1 11 Tf 50 100 Td (Body paragraph text.) Tj ET EMC"]
            roles = [("H1", None), ("Figure", "Our university"), ("P", None)]
            images = {"Logo": logo}
            if number == 1:
                content.append(b"/Figure <</MCID 3>> BDC q .1 .5 .2 rg 300 20 30 20 re f Q EMC")
                roles.append(("Figure", "Decorative flourish"))
            if number == 2:
                content.append(b"/Figure <</MCID 3>> BDC q 300 0 0 200 50 150 cm /Photo Do Q EMC")
                roles.append(("Figure", photo_alt))
                images["Photo"] = photo
            if number == 3:
                content.append(b"/Figure <</MCID 3>> BDC q 40 0 0 40 320 440 cm /Seal Do Q EMC")
                roles.append(("Figure", seal_alt))
                images["Seal"] = seal
            page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font),
                                                    XObject=pikepdf.Dictionary({"/" + name: value for name, value in images.items()}))
            page.obj.Contents = pdf.make_stream(b"\n".join(content))
            children = []
            for mcid, (role, alt) in enumerate(roles):
                node = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name("/" + role), P=section, Pg=page.obj, K=mcid))
                if alt:
                    node.Alt = alt
                children.append(node)
            section.K = pikepdf.Array(children)
            nums.extend([number, pikepdf.Array(children)])
        document.K = pikepdf.Array(sections)
        root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(nums)))
        root.ParentTreeNextKey = pages
        pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = "en-US"
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.docinfo.Title = "Synthetic logo review fixture"
        pdf.save(path, deterministic_id=True)
    return path


def make_bundle(tmp_path, *, profile=ARTIFACT_STRUCTURE_INVENTORY_PROFILE, name="logos", **kwargs):
    document = logo_pdf(tmp_path / (name + ".pdf"), **kwargs)
    bundle = tmp_path / (name + "-bundle")
    bundle.mkdir()
    output = bundle / "candidate.pdf"
    shutil.copyfile(document, output)
    sha = file_sha256(document)
    manual = [{"id": "reading-order", "category": "reading-order", "required": True, "detail": "Review the structure.", "status": "pending", "pages": []}]
    report = {"status": "candidate", "run_fingerprint": "synthetic-" + name, "input": {"path": str(document), "sha256": sha},
              "output": {"path": str(output), "sha256": sha}, "decision_source": {"path": str(document), "sha256": sha, "source_sha256": sha},
              "inspection": {"page_count": 4}, "manual_review": {"artifact_sha256": sha, "items": manual, "complete": False}, "residual_issues": [],
              "gate1": {"status": "pass", "scope": "named workspace-only fixture gate"},
              "gate2": {"status": "pass", "checks": [], "manual_queue": copy.deepcopy(manual)}, "fidelity": {"status": "pass", "after_sha256": sha}}
    write_sidecar(report, bundle / "report.json")
    write_sidecar(collect_decisions(document, inventory_profile=profile), bundle / "decisions.json")
    write_sidecar(report["manual_review"], bundle / "review.json")
    (bundle / "review.html").write_text("<!doctype html><title>Authored review fixture</title>", encoding="utf-8")
    write_sidecar({"schema_version": "phase1-bundle-1", "complete": True, "run_fingerprint": report["run_fingerprint"],
                   "files": {path.name: file_sha256(path) for path in bundle.iterdir()}}, bundle / "manifest.json")
    assert verify_bundle(bundle)
    state = tmp_path / (name + "-state.json")
    ws.create_workspace(bundle, state)
    return document, bundle, state, output


@pytest.fixture
def logos(tmp_path):
    document, bundle, state, output = make_bundle(tmp_path)
    return {"document": document, "bundle": bundle, "state": state, "output": output, "tmp": tmp_path}


def _group(logos, kind="same-picture-on-several-pages"):
    review = ws.get_logo_review(logos["state"])
    return review, next(group for group in review["groups"] if group["kind"] == kind)


def _decision(view, identifier):
    return next(item for item in view["decisions"] if item["id"] == identifier)


def _save(logos, group, ids, choice, description="", revision=None):
    revision = ws.get_view(logos["state"])["revision"] if revision is None else revision
    return ws.logo_group_save(logos["state"], group["id"], ids, group["membership_digest"], choice, description, revision)


def _accept(logos, group, ids, reviewer=REVIEWER):
    return ws.logo_group_accept(logos["state"], group["id"], ids, group["membership_digest"], reviewer, DATE, ws.get_view(logos["state"])["revision"])


# --- the screen ------------------------------------------------------------------------------------------------------------

def test_the_same_small_picture_on_several_pages_becomes_one_group_with_every_occurrence_kept(logos):
    review, group = _group(logos)
    assert review["label"] == "Logo and branding" and review["policy"] == logo_review.POLICY and review["status"] == "measured"
    assert group["label"] == "Logo and branding" and group["pages"] == [1, 2, 3, 4]
    assert [member["page"] for member in group["members"]] == [1, 2, 3, 4]
    assert group["asset_sha256"] and len(group["member_ids"]) == 4
    assert all(member["position"] == "header" and member["geometry_source"] == "picture-object" and member["area_fraction"] < 0.02
               for member in group["members"])
    assert all("The same picture is a figure on 4 pages" in " ".join(member["signals"]) for member in group["members"])
    assert all(member["purpose_id"] and member["decorative_available"] for member in group["members"])
    assert review["guidance"].startswith("For a picture that carries meaning") and "marking it decorative" in review["guidance"]
    assert "alternative text" in review["source_guidance"]
    assert review["verification"] == "not-verified"


def test_a_picture_described_as_a_logo_is_listed_alone_and_large_photographs_are_left_out(logos):
    review, _ = _group(logos)
    single = next(group for group in review["groups"] if group["kind"] == "single-occurrence")
    assert single["pages"] == [4] and single["members"][0]["current_description"] == "Institutional logo"
    assert single["members"][0]["signals"][0].startswith("A small picture in the header") or "calls it a logo" in " ".join(single["members"][0]["signals"])
    listed_pages = {member["page"] for group in review["groups"] for member in group["members"]}
    assert listed_pages == {1, 2, 3, 4}
    members = [member for group in review["groups"] for member in group["members"]]
    # 4 header logos + the seal; neither the page 3 photograph (30 percent of the page) nor the page 2 drawn figure is a candidate.
    assert len(members) == 5 and review["candidate_count"] == 5 and review["figures_in_review"] == 7
    assert all(member["area_fraction"] <= 0.06 for member in members)


def test_screening_is_deterministic_and_never_changes_the_pdf(logos):
    before = file_sha256(logos["document"])
    state = ws.load_workspace(logos["state"])
    rows = [item for item in state["sidecar"]["decisions"] if item["kind"] in {"figure-description", "figure-purpose"}]
    first = logo_review.assess(logos["document"], rows)
    second = logo_review.assess(logos["document"], copy.deepcopy(rows))
    assert first == second and file_sha256(logos["document"]) == before
    assert first["thresholds"]["repeat_pages_at_least"] == 2 and first["limits"]["pages"] == 300
    assert first["partial_reasons"] == []


def test_a_figure_that_only_appears_once_and_is_not_called_a_logo_is_not_listed(tmp_path):
    document = logo_pdf(tmp_path / "one.pdf", pages=1)
    decisions = collect_decisions(document, inventory_profile=ARTIFACT_STRUCTURE_INVENTORY_PROFILE)["decisions"]
    figure_rows = [item for item in decisions if item["kind"] == "figure-description"]
    assert len(figure_rows) == 1
    result = logo_review.assess(document, decisions)
    # One small picture in the header still counts as a margin candidate, but with no repeat signal.
    assert [row["repeat_pages"] for row in result["occurrences"]] == [1]
    assert result["groups"][0]["kind"] == "single-occurrence"
    assert all("pages" not in signal or "The same picture" not in signal for row in result["occurrences"] for signal in row["signals"])


def test_a_review_without_figures_has_nothing_to_examine(tmp_path):
    with pikepdf.new() as pdf:
        pdf.add_blank_page()
        pdf.Root.Lang = "en-US"
        pdf.docinfo.Title = "Plain"
        pdf.save(tmp_path / "plain.pdf", deterministic_id=True)
    assert logo_review.assess(tmp_path / "plain.pdf", [])["status"] == "not-applicable"


# --- saving a choice ---------------------------------------------------------------------------------------------------------

def test_describing_a_group_saves_a_pending_description_on_each_selected_occurrence_only(logos):
    _, group = _group(logos)
    chosen = group["member_ids"][:3]
    view = _save(logos, group, chosen, "describe", "  Northfield University  ")
    for identifier in chosen:
        item = _decision(view, identifier)
        assert item["value"] == "Northfield University" and item["status"] == "pending" and "approval_sha256" not in item
    untouched = _decision(view, group["member_ids"][3])
    assert untouched["value"] == untouched["current"] == "Our university" and untouched["status"] == "pending"
    assert set(chosen) <= set(view["unapplied_decisions"]) and group["member_ids"][3] not in view["unapplied_decisions"]
    assert view["history"][-1]["action"] == "logo-group-save" and view["history"][-1]["member_ids"] == sorted(chosen)
    assert view["counts"]["decision_approved"] == 0 and view["verification"] == "not-verified"


def test_marking_decorative_sets_the_purpose_decision_and_withdraws_a_saved_description(logos):
    _, group = _group(logos)
    ids = group["member_ids"][:2]
    _save(logos, group, ids, "describe", "Northfield University")
    view = _save(logos, group, ids, "decorative")
    for member in group["members"][:2]:
        purpose = _decision(view, member["purpose_id"])
        description = _decision(view, member["id"])
        assert purpose["value"] == "Artifact" and purpose["status"] == "pending"
        assert description["value"] == description["current"]
    # Choosing to describe again takes the decorative marking back, so the two never apply together.
    back = _save(logos, group, ids, "describe", "Northfield University")
    for member in group["members"][:2]:
        assert _decision(back, member["purpose_id"])["value"] == "Figure"
        assert _decision(back, member["id"])["value"] == "Northfield University"


def test_a_shared_figure_tag_cannot_be_split_across_a_selection():
    rows = [{"id": "a", "kind": "figure-description", "element": "9:0"}, {"id": "b", "kind": "figure-description", "element": "9:0"},
            {"id": "c", "kind": "figure-description", "element": "10:0"}]
    state = {"sidecar": {"decisions": rows}}
    one = {"id": "a", "element": "9:0", "page": 1}
    assert "one shared figure tag" in ws._logo_shared_figure_problem(state, [one])
    assert ws._logo_shared_figure_problem(state, [one, {"id": "b", "element": "9:0", "page": 2}]) is None
    assert ws._logo_shared_figure_problem(state, [{"id": "c", "element": "10:0", "page": 3}]) is None


def test_each_occurrence_can_get_a_different_choice(logos):
    _, group = _group(logos)
    first, second, *rest = group["member_ids"]
    _save(logos, group, [first], "describe", "Northfield University")
    view = _save(logos, group, [second], "decorative")
    member = {item["id"]: item for item in group["members"]}
    assert _decision(view, first)["value"] == "Northfield University"
    assert _decision(view, member[second]["purpose_id"])["value"] == "Artifact" and _decision(view, second)["value"] == "Our university"
    assert all(_decision(view, member[identifier]["purpose_id"])["value"] == "Figure" for identifier in rest)


@pytest.mark.parametrize("defect", ["revision", "digest", "foreign", "duplicate", "empty", "choice", "blank", "placeholder", "control", "long"])
def test_unsafe_or_stale_saves_are_refused_and_change_nothing(logos, defect):
    review, group = _group(logos)
    other = next(group for group in review["groups"] if group["kind"] == "single-occurrence")
    view = ws.get_view(logos["state"])
    saved = logos["state"].read_bytes()
    ids, digest, revision, choice, text = list(group["member_ids"][:2]), group["membership_digest"], view["revision"], "describe", "Northfield University"
    if defect == "revision":
        revision -= 1
    elif defect == "digest":
        digest = "0" * 64
    elif defect == "foreign":
        ids = [group["member_ids"][0], other["member_ids"][0]]
    elif defect == "duplicate":
        ids = [group["member_ids"][0]] * 2
    elif defect == "empty":
        ids = []
    elif defect == "choice":
        choice = "approve"
    elif defect == "blank":
        text = "   "
    elif defect == "placeholder":
        text = "image"
    elif defect == "control":
        text = "Northfield\nUniversity"
    elif defect == "long":
        text = "x" * 1001
    with pytest.raises(ws.WorkspaceError):
        ws.logo_group_save(logos["state"], group["id"], ids, digest, choice, text, revision)
    assert logos["state"].read_bytes() == saved


def test_decorative_marking_is_refused_where_the_review_does_not_offer_it(tmp_path):
    document, bundle, state, output = make_bundle(tmp_path, profile=LEGACY_INVENTORY_PROFILE, name="legacy")
    review = ws.get_logo_review(state)
    group = next(group for group in review["groups"] if group["kind"] == "same-picture-on-several-pages")
    assert all(member["purpose_id"] is None and not member["decorative_available"] for member in group["members"])
    revision = ws.get_view(state)["revision"]
    with pytest.raises(ws.WorkspaceError, match="Decorative marking is not available"):
        ws.logo_group_save(state, group["id"], group["member_ids"], group["membership_digest"], "decorative", "", revision)
    # Describing still works in the older review.
    view = ws.logo_group_save(state, group["id"], group["member_ids"], group["membership_digest"], "describe", "Northfield University", revision)
    assert all(_decision(view, identifier)["value"] == "Northfield University" for identifier in group["member_ids"])


# --- accepting by name -------------------------------------------------------------------------------------------------------

def test_acceptance_is_explicit_named_and_limited_to_the_selected_occurrences(logos):
    _, group = _group(logos)
    ids = group["member_ids"]
    _save(logos, group, ids[:3], "describe", "Northfield University")
    _save(logos, group, [ids[2]], "decorative")
    with pytest.raises(ws.WorkspaceError, match="Nothing is saved for the occurrence on page 4"):
        _accept(logos, group, ids)
    with pytest.raises(ws.WorkspaceError, match="named reviewer"):
        _accept(logos, group, ids[:2], reviewer="")
    view = _accept(logos, group, ids[:2])
    approved = [item for item in view["decisions"] if item["status"] == "approved"]
    assert {item["id"] for item in approved} == set(ids[:2])
    stored = {item["id"]: item for item in ws.load_workspace(logos["state"], refresh=False)["sidecar"]["decisions"]}
    for item in approved:
        assert item["approved_by"] == REVIEWER and item["approved_at"] == DATE
        assert stored[item["id"]]["approval_sha256"] == approval_digest(stored[item["id"]])
    members = {member["id"]: member for member in group["members"]}
    # The third member's decorative marking is saved but not accepted; the fourth was never touched.
    assert _decision(view, members[ids[2]]["purpose_id"])["status"] == "pending"
    assert _decision(view, ids[3])["status"] == "pending"
    assert view["history"][-1]["action"] == "logo-group-accept" and view["history"][-1]["member_ids"] == sorted(ids[:2])
    assert view["counts"]["decision_approved"] == 2 and view["verification"] == "not-verified"


def test_accepting_a_decorative_choice_approves_the_purpose_decision_and_waits_for_apply(logos):
    _, group = _group(logos)
    ids = group["member_ids"][:2]
    _save(logos, group, ids, "decorative")
    view = _accept(logos, group, ids)
    members = {member["id"]: member for member in group["members"]}
    for identifier in ids:
        purpose = _decision(view, members[identifier]["purpose_id"])
        assert purpose["status"] == "approved" and purpose["value"] == "Artifact"
        assert _decision(view, identifier)["status"] == "pending"
    assert set(view["unapplied_decisions"]) == {members[identifier]["purpose_id"] for identifier in ids}
    # Nothing in the PDF or bundle changed.
    assert file_sha256(logos["document"]) == view["output"]["sha256"]


def test_accepted_logo_choices_go_through_the_ordinary_writer_unchanged(logos, tmp_path):
    from pdf_remediator.sidecar import apply_decisions, load_sidecar
    _, group = _group(logos)
    members = {member["id"]: member for member in group["members"]}
    described, marked, left = group["member_ids"][:2], group["member_ids"][2], group["member_ids"][3]
    _save(logos, group, described, "describe", "Northfield University")
    _save(logos, group, [marked], "decorative")
    _accept(logos, group, described)
    view = _accept(logos, group, [marked])
    exported = ws.export_workspace(logos["state"], tmp_path / "exports", view["revision"])
    data = load_sidecar(exported["sidecar_path"])
    applied = tmp_path / "applied.pdf"
    receipt = apply_decisions(logos["document"], applied, data, file_sha256(logos["document"]))
    assert receipt and applied.is_file()
    before = file_sha256(logos["document"])
    assert before == view["output"]["sha256"], "The original and its published copy stay as they were."
    # Read the result back the way the program reads any PDF: its figures, page by page, with their descriptions.
    figures = {}
    for row in collect_decisions(applied, inventory_profile=ARTIFACT_STRUCTURE_INVENTORY_PROFILE)["decisions"]:
        if row["kind"] == "figure-description":
            figures.setdefault(row["page"], []).append(row["current"])
    page = lambda identifier: members[identifier]["page"]
    assert figures[page(described[0])] == ["Northfield University"]
    assert figures[page(described[1])] == ["Northfield University", "Decorative flourish"], "Only the selected logo changed."
    assert figures[page(left)] == ["Our university", "Institutional logo"], "An occurrence nobody decided keeps its description."
    assert figures[page(marked)] == ["A crowd at the opening ceremony"], "The decorative logo is no longer a described figure; the photograph stays."
    assert file_sha256(logos["document"]) == before
    assert any(row["current"] == "Our university" for row in collect_decisions(logos["document"], inventory_profile=ARTIFACT_STRUCTURE_INVENTORY_PROFILE)["decisions"]
               if row["kind"] == "figure-description" and row["page"] == page(marked)), "The original still has every logo."


def test_changing_a_saved_description_takes_back_its_acceptance(logos):
    _, group = _group(logos)
    ids = group["member_ids"][:2]
    _save(logos, group, ids, "describe", "Northfield University")
    _accept(logos, group, ids)
    view = _save(logos, group, [ids[0]], "describe", "Northfield State University")
    assert _decision(view, ids[0])["status"] == "pending" and _decision(view, ids[1])["status"] == "approved"


def test_a_changed_result_stops_group_actions_and_hides_nothing(logos):
    _, group = _group(logos)
    _save(logos, group, group["member_ids"][:2], "describe", "Northfield University")
    _accept(logos, group, group["member_ids"][:2])
    logos["output"].write_bytes(logos["output"].read_bytes() + b"\n% changed after review\n")
    stale = ws.get_view(logos["state"])
    assert stale["stale"] and stale["counts"]["decision_approved"] == 0
    with pytest.raises(ws.WorkspaceError):
        ws.get_logo_review(logos["state"])
    with pytest.raises(ws.WorkspaceError):
        ws.logo_group_accept(logos["state"], group["id"], group["member_ids"][:2], group["membership_digest"], REVIEWER, DATE, stale["revision"])


def test_the_summary_in_the_view_is_cheap_and_names_what_is_offered(logos):
    summary = ws.get_view(logos["state"])["logo_review"]
    assert summary == {"available": True, "figures": 7, "decorative_controls": True, "schema_version": "phase2-logo-review-1"}


# --- the local service ----------------------------------------------------------------------------------------------------------

def test_the_service_routes_serve_evidence_save_and_accept(logos, tmp_path):
    app = web.Application(tmp_path / "application", RuntimeConfig(project_root=logos["tmp"]))
    server = web.ReviewServer(app)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        identifier = app.import_bundle(str(logos["bundle"]))
        def call(method, path, payload=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=8)
            headers = {"Host": f"127.0.0.1:{server.server_port}", "X-Review-Token": app.token}
            body = None
            if payload is not None:
                body, headers["Content-Type"] = json.dumps(payload).encode(), "application/json"
            try:
                connection.request(method, f"/api/workspaces/{identifier}{path}", body=body, headers=headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        status, review = call("GET", "/logo-review")
        assert status == 200 and review["label"] == "Logo and branding"
        assert call("GET", "/logo-review?x=1")[0] >= 400
        group = next(item for item in review["groups"] if item["kind"] == "same-picture-on-several-pages")
        body = {"group_id": group["id"], "member_ids": group["member_ids"][:2], "membership_digest": group["membership_digest"], "revision": review["revision"]}
        status, saved = call("POST", "/logo-save", {**body, "choice": "describe", "description": "Northfield University"})
        assert status == 200 and next(item for item in saved["decisions"] if item["id"] == body["member_ids"][0])["value"] == "Northfield University"
        status, refused = call("POST", "/logo-accept", {**body, "revision": saved["revision"], "reviewer": ""})
        assert status >= 400 and "named reviewer" in json.dumps(refused)
        status, accepted = call("POST", "/logo-accept", {**body, "revision": saved["revision"], "reviewer": REVIEWER})
        assert status == 200 and accepted["counts"]["decision_approved"] == 2 and accepted["verification"] == "not-verified"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()
