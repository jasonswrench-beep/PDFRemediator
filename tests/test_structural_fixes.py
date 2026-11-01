"""Authored PDF tag fixes are explicit human decisions, never inferred meaning."""
import copy
import json
import shutil
import threading

import pikepdf
import pytest

from pdf_remediator import workspace as ws
from pdf_remediator.sidecar import (
    DecisionError, LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE,
    apply_decisions, bind_approval, collect_decisions, file_sha256,
    inventory_profile_for, make_automatic_authorization, write_sidecar,
)


def structural_pdf(path, *, unknown_page=False, repeated=False, shared=False, role="P", missing_reference=False, broken_child=False, broken_parent_tree=False):
    """A source-authored text block, existing H3 and two table cells."""
    with pikepdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(400, 400))
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(b"\n".join(
            b"/P <</MCID %d>> BDC BT /F1 12 Tf 40 %d Td (%s) Tj ET EMC" % (i, 350 - i * 40, text)
            for i, text in enumerate((b"Source-authored heading", b"Existing section", b"Data value", b"Header label"))))
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        def node(role, mcid, parent=tree, **attributes):
            value = pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name("/" + role), P=parent, K=mcid, **attributes)
            if not unknown_page:
                value.Pg = page.obj
            return pdf.make_indirect(value)
        paragraph = node(role, 99 if missing_reference else 0)
        if broken_child:
            paragraph.K = pikepdf.Array([0, "malformed non-object child"])
        heading = node("H3", 1, T="Authored section label")
        table = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Table, P=tree))
        row = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.TR, P=table))
        data = node("TD", 2, row, A=pikepdf.Dictionary(O=pikepdf.Name.Table,
            RowSpan=1, ColSpan=2, Headers=pikepdf.Array(["authored-header"])))
        header = node("TH", 3, row, ID="authored-header", A=pikepdf.Array([
            pikepdf.Dictionary(O=pikepdf.Name.Layout, Placement=pikepdf.Name.Block),
            pikepdf.Dictionary(O=pikepdf.Name.Table, Scope=pikepdf.Name.Row, ColSpan=2),
        ]))
        row.K = pikepdf.Array([data, header])
        table.K = row
        tree.K = pikepdf.Array([paragraph, heading, table] + ([paragraph] if repeated else []))
        if shared:
            second = pdf.add_blank_page(page_size=(400, 400))
            second.Resources = page.Resources
            second.Contents = pdf.make_stream(b"/P <</MCID 0>> BDC BT /F1 12 Tf 40 350 Td (Shared text) Tj ET EMC")
            paragraph.K = pikepdf.Array([
                pikepdf.Dictionary(Type=pikepdf.Name.MCR, Pg=page.obj, MCID=0),
                pikepdf.Dictionary(Type=pikepdf.Name.MCR, Pg=second.obj, MCID=0),
            ])
        tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([paragraph, heading, data, header])])))
        if broken_parent_tree:
            tree.ParentTree.Nums.append(17)
        page.StructParents = 0
        pdf.Root.StructTreeRoot = tree
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = "en-US"
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.docinfo.Title = "Authored structural repair fixture"
        pdf.save(path, deterministic_id=True)
    return path


@pytest.fixture
def document(tmp_path):
    return structural_pdf(tmp_path / "structural-source.pdf")


def expanded(document):
    return collect_decisions(document, inventory_profile=STRUCTURAL_INVENTORY_PROFILE)


def choose(data, kind, current=None):
    return next(item for item in data["decisions"] if item["kind"] == kind and (current is None or item["current"] == current))


def accept(item, value):
    item["value"] = value
    bind_approval(item, "Synthetic structural reviewer", "2026-10-21")


def paint_contract(path):
    with pikepdf.open(path) as pdf:
        return [(page.Contents.read_bytes(), str(page.Resources)) for page in pdf.pages]


def test_legacy_inventory_is_explicitly_retained_and_expansion_is_opt_in(document):
    legacy = collect_decisions(document)
    assert inventory_profile_for(legacy) == LEGACY_INVENTORY_PROFILE
    assert "inventory_profile" not in legacy
    assert [item["kind"] for item in legacy["decisions"]] == ["title", "language"]
    assert collect_decisions(document, inventory_profile=LEGACY_INVENTORY_PROFILE) == legacy
    current = expanded(document)
    assert current["inventory_profile"] == STRUCTURAL_INVENTORY_PROFILE
    assert [item["kind"] for item in current["decisions"]] == ["title", "language", "heading-tag", "heading-tag", "table-header", "table-header"]
    paragraph = choose(current, "heading-tag", "P")
    assert paragraph["value"] == "P" and paragraph["status"] == "pending"
    assert paragraph["structural_eligible"] and paragraph["page"] == 1
    assert paragraph["context_text"] == "Source-authored heading"
    assert "MCID-matched selectable text" in paragraph["context_text_source"]
    cell_snippets = {json.loads(item["current"])["role"]: item["context_text"]
                     for item in current["decisions"] if item["kind"] == "table-header"}
    assert cell_snippets == {"TD": "Data value", "TH": "Header label"}
    heading = choose(current, "heading-tag", "H3")
    assert heading["context_text"] == "Authored section label" and heading["context_text_source"] == "/T"


@pytest.mark.parametrize("profile", ["unknown", None, [], {}])
def test_unknown_inventory_profile_refuses(document, profile):
    with pytest.raises(DecisionError, match="inventory profile"):
        collect_decisions(document, inventory_profile=profile)


def test_pending_structural_drafts_do_not_change_pdf_bytes(document, tmp_path):
    data = expanded(document)
    choose(data, "heading-tag", "P")["value"] = "H1"
    choose(data, "table-header")["value"] = '{"role":"TH","scope":"Column"}'
    result = tmp_path / "pending.pdf"
    outcome = apply_decisions(document, result, data, file_sha256(document))
    assert result.read_bytes() == document.read_bytes() and not outcome["changed"]


def test_structural_tags_and_header_semantics_cannot_enter_automatic_authority(document):
    data = expanded(document)
    for kind in ("heading-tag", "table-header"):
        with pytest.raises(DecisionError, match="title/figure decision IDs"):
            make_automatic_authorization(data["source_sha256"], data["document_sha256"],
                "2026-10-21", decision_ids=[choose(data, kind)["id"]])


def test_reviewed_heading_and_table_scope_change_only_exact_structure_targets(document, tmp_path):
    data = expanded(document)
    paragraph = choose(data, "heading-tag", "P")
    heading = choose(data, "heading-tag", "H3")
    cell = next(item for item in data["decisions"] if item["kind"] == "table-header" and json.loads(item["current"])["role"] == "TD")
    accept(paragraph, "H1")
    accept(heading, "H2")
    accept(cell, '{"role":"TH","scope":"Column"}')
    old_hash = file_sha256(document)
    before = paint_contract(document)
    result = tmp_path / "reviewed.pdf"
    outcome = apply_decisions(document, result, data, old_hash)
    assert set(outcome["changed"]) == {paragraph["id"], heading["id"], cell["id"]}
    assert file_sha256(document) == old_hash and paint_contract(result) == before
    assert outcome["auto_accepted"] == [] and outcome["data_sent"]["document_api_calls"] == 0
    with pikepdf.open(result) as pdf:
        children = pdf.Root.StructTreeRoot.K
        assert [str(children[i].S) for i in (0, 1)] == ["/H1", "/H2"]
        cells = children[2].K.K
        assert str(cells[0].S) == "/TH"
        attrs = list(cells[0].A)
        assert any(str(attr.get("/Scope", "")) == "/Column" for attr in attrs)
        assert any(int(attr.get("/ColSpan", 0)) == 2 and int(attr.get("/RowSpan", 0)) == 1 for attr in attrs)
        assert any(list(attr.get("/Headers", [])) == ["authored-header"] for attr in attrs)
        assert str(cells[1].ID) == "authored-header" and str(cells[1].S) == "/TH"
        assert str(cells[1].A[0].O) == "/Layout" and str(cells[1].A[1].Scope) == "/Row"


def test_existing_table_scope_replacement_preserves_ids_headers_spans_and_other_attributes(document, tmp_path):
    data = expanded(document)
    header = next(item for item in data["decisions"] if item["kind"] == "table-header" and json.loads(item["current"])["role"] == "TH")
    accept(header, '{"role":"TH","scope":"Both"}')
    result = tmp_path / "header.pdf"
    apply_decisions(document, result, data, file_sha256(document))
    with pikepdf.open(result) as pdf:
        value = pdf.Root.StructTreeRoot.K[2].K.K[1]
        assert str(value.ID) == "authored-header"
        assert [str(attr.Scope) for attr in value.A if "/Scope" in attr] == ["/Both"]
        assert any(str(attr.get("/O", "")) == "/Layout" and str(attr.Placement) == "/Block" for attr in value.A)
        assert any(int(attr.get("/ColSpan", 0)) == 2 for attr in value.A)


@pytest.mark.parametrize("role", ["P", "Span", "Lbl", "H", "H7", "H10"])
def test_explicit_existing_text_role_can_be_reviewed_without_inventing_content(tmp_path, role):
    document = structural_pdf(tmp_path / "role.pdf", role=role)
    data = expanded(document)
    item = choose(data, "heading-tag", role)
    accept(item, "H1")
    result = tmp_path / "fixed.pdf"
    apply_decisions(document, result, data, file_sha256(document))
    with pikepdf.open(result) as pdf:
        assert str(pdf.Root.StructTreeRoot.K[0].S) == "/H1"
    assert paint_contract(result) == paint_contract(document)


def test_individual_role_mapped_heading_fix_does_not_rewrite_shared_role_map(tmp_path):
    document = structural_pdf(tmp_path / "original.pdf")
    mapped = tmp_path / "mapped.pdf"
    with pikepdf.open(document) as pdf:
        pdf.Root.StructTreeRoot.RoleMap = pikepdf.Dictionary(CustomSection=pikepdf.Name.H3)
        pdf.Root.StructTreeRoot.K[1].S = pikepdf.Name.CustomSection
        pdf.save(mapped, deterministic_id=True)
    data = expanded(mapped)
    accept(choose(data, "heading-tag", "H3"), "H2")
    result = tmp_path / "fixed.pdf"
    apply_decisions(mapped, result, data, file_sha256(mapped))
    with pikepdf.open(result) as pdf:
        assert str(pdf.Root.StructTreeRoot.K[1].S) == "/H2"
        assert str(pdf.Root.StructTreeRoot.RoleMap.CustomSection) == "/H3"
    assert paint_contract(result) == paint_contract(mapped)


@pytest.mark.parametrize("kind,value", [
    ("heading-tag", "H7"), ("heading-tag", "H0"), ("heading-tag", "/H1"),
    ("heading-tag", "H1\n/P"), ("heading-tag", "Invented heading text"),
    ("table-header", '{"role":"TH","scope":"Diagonal"}'),
    ("table-header", '{"role":"TD","scope":"Column"}'),
    ("table-header", '{"role":"TH","scope":"Column","headers":["guessed"]}'),
    ("table-header", '{"role":[],"scope":{}}'), ("table-header", "not JSON"),
])
def test_structural_values_cannot_invent_roles_text_or_relationships(document, kind, value):
    item = choose(expanded(document), kind, "P" if kind == "heading-tag" else None)
    with pytest.raises(DecisionError):
        accept(item, value)


@pytest.mark.parametrize("changed", ["current", "context_text", "structural_eligible", "references", "binding", "context_sha256", "inventory_profile", "value"])
def test_accepted_structural_context_and_profile_tampering_refuses_without_output(document, tmp_path, changed):
    data = expanded(document)
    item = choose(data, "heading-tag", "P")
    accept(item, "H1")
    if changed == "binding":
        item["binding"]["document_sha256"] = "b" * 64
    elif changed == "inventory_profile":
        data[changed] = LEGACY_INVENTORY_PROFILE
    elif changed == "references":
        item[changed][0]["mcid"] = 123
    else:
        item[changed] = "tampered"
    result = tmp_path / "refused.pdf"
    with pytest.raises(DecisionError):
        apply_decisions(document, result, data, file_sha256(document))
    assert not result.exists()


@pytest.mark.parametrize("variant", ["unknown_page", "shared", "repeated", "missing_reference"])
def test_unresolvable_or_shared_structural_element_never_accepts_tag_fix(tmp_path, variant):
    document = structural_pdf(tmp_path / "unsupported.pdf", **{variant: True})
    data = expanded(document)
    paragraph = choose(data, "heading-tag", "P")
    if variant == "repeated":
        assert data["inventory_errors"]
    assert paragraph["structural_eligible"] is False
    with pytest.raises(DecisionError, match="single-page"):
        accept(paragraph, "H1")


@pytest.mark.parametrize("variant", ["broken_child", "broken_parent_tree"])
def test_parser_structure_errors_refuse_structural_approval_even_with_otherwise_valid_mcid(tmp_path, variant):
    document = structural_pdf(tmp_path / "malformed-structure.pdf", **{variant: True})
    data = expanded(document)
    paragraph = choose(data, "heading-tag", "P")
    assert paragraph["references"] == [{"page": 1, "mcid": 0, "stream": "page"}]
    assert paragraph["structural_eligible"] is False
    assert any("cannot be resolved uniquely" in note for note in paragraph["structural_limitations"])
    with pytest.raises(DecisionError, match="single-page"):
        accept(paragraph, "H1")
    assert not (tmp_path / "refused.pdf").exists()


def test_direct_form_text_never_becomes_a_guessed_page_stream_snippet(document, tmp_path):
    altered = tmp_path / "form-context.pdf"
    with pikepdf.open(document) as pdf:
        page = pdf.pages[0]
        form = pdf.make_stream(b"BT /F1 12 Tf 40 350 Td (Form text must remain unavailable as direct context) Tj ET")
        form.Type = pikepdf.Name.XObject
        form.Subtype = pikepdf.Name.Form
        form.BBox = pikepdf.Array([0, 0, 400, 400])
        form.Resources = pikepdf.Dictionary(Font=page.Resources.Font)
        page.Resources.XObject = pikepdf.Dictionary(SnippetForm=form)
        page.Contents = pdf.make_stream(page.Contents.read_bytes().replace(
            b"BT /F1 12 Tf 40 350 Td (Source-authored heading) Tj ET", b"/SnippetForm Do"))
        pdf.save(altered, deterministic_id=True)
    paragraph = choose(expanded(altered), "heading-tag", "P")
    assert paragraph["structural_eligible"]
    assert paragraph["context_text"] == ""
    assert "No embedded text label or unambiguous" in paragraph["context_text_source"]


def test_empty_marked_sequence_does_not_qualify_as_owned_painted_content(document, tmp_path):
    altered = tmp_path / "empty-marked-content.pdf"
    with pikepdf.open(document) as pdf:
        page = pdf.pages[0]
        original = b"/P <</MCID 0>> BDC BT /F1 12 Tf 40 350 Td (Source-authored heading) Tj ET EMC"
        replacement = b"/P <</MCID 0>> BDC EMC /Artifact BMC BT /F1 12 Tf 40 350 Td (Source-authored heading) Tj ET EMC"
        assert original in page.Contents.read_bytes()
        page.Contents = pdf.make_stream(page.Contents.read_bytes().replace(original, replacement))
        pdf.save(altered, deterministic_id=True)
    paragraph = choose(expanded(altered), "heading-tag", "P")
    assert paragraph["structural_eligible"] is False and paragraph["context_text"] == ""
    with pytest.raises(DecisionError):
        accept(paragraph, "H1")


@pytest.mark.parametrize("operation", ["collect", "apply"])
def test_cancelled_inventory_and_application_refuse_before_work_without_output(document, tmp_path, operation):
    token = threading.Event()
    token.set()
    target = tmp_path / "cancelled.pdf"
    original = document.read_bytes()
    with pytest.raises(InterruptedError, match="cancelled"):
        if operation == "collect":
            collect_decisions(document, inventory_profile=STRUCTURAL_INVENTORY_PROFILE, cancel=token)
        else:
            apply_decisions(document, target, collect_decisions(document), file_sha256(document), cancel=token)
    assert not target.exists() and document.read_bytes() == original


def test_cancellation_inside_inventory_page_loop_propagates_instead_of_becoming_inventory_error(tmp_path, monkeypatch):
    from pdf_remediator import inspection
    document = structural_pdf(tmp_path / "cancel-mid-page.pdf", shared=True)
    token = threading.Event()
    real_page = inspection._page_content
    calls = []
    def cancel_after_first_page(*args, **kwargs):
        calls.append(args[1])
        result = real_page(*args, **kwargs)
        token.set()
        return result
    monkeypatch.setattr(inspection, "_page_content", cancel_after_first_page)
    with pytest.raises(InterruptedError, match="cancelled"):
        collect_decisions(document, inventory_profile=STRUCTURAL_INVENTORY_PROFILE, cancel=token)
    assert calls == [1]


def test_cancellation_before_atomic_decision_publication_discards_checkpoint(document, tmp_path, monkeypatch):
    from pdf_remediator import sidecar
    token = threading.Event()
    real_copy = sidecar.shutil.copyfile
    def cancel_after_copy(source, target, *args, **kwargs):
        result = real_copy(source, target, *args, **kwargs)
        token.set()
        return result
    monkeypatch.setattr(sidecar.shutil, "copyfile", cancel_after_copy)
    data = collect_decisions(document)
    target = tmp_path / "not-published.pdf"
    with pytest.raises(InterruptedError, match="cancelled"):
        apply_decisions(document, target, data, file_sha256(document), cancel=token)
    assert not target.exists() and not list(tmp_path.glob(".decisions-*.pdf"))


def make_workspace(tmp_path, document, profile=LEGACY_INVENTORY_PROFILE):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    output = bundle / "candidate.pdf"
    shutil.copyfile(document, output)
    sha = file_sha256(document)
    manual = [{"id": "reading-order", "category": "reading-order", "detail": "Inspect source-authored structure", "pages": [], "required": True, "status": "pending"}]
    report = {"status": "candidate", "run_fingerprint": "authored-structure-test",
        "input": {"path": str(document), "sha256": sha},
        "output": {"path": str(output), "sha256": sha},
        "decision_source": {"path": str(document), "sha256": sha, "source_sha256": sha},
        "inspection": {"page_count": 1}, "manual_review": {"artifact_sha256": sha, "items": manual, "complete": False},
        "residual_issues": [], "gate1": {"status": "pass"},
        "gate2": {"status": "pass", "checks": [], "manual_queue": copy.deepcopy(manual)},
        "fidelity": {"status": "pass", "after_sha256": sha}}
    # Named gate stubs qualify workspace guards, not native accessibility.
    write_sidecar(report, bundle / "report.json")
    write_sidecar(collect_decisions(document, inventory_profile=profile), bundle / "decisions.json")
    write_sidecar(report["manual_review"], bundle / "review.json")
    (bundle / "review.html").write_text("<!doctype html><title>Authored review stub</title>", encoding="utf-8")
    write_sidecar({"schema_version": "phase1-bundle-1", "complete": True, "run_fingerprint": report["run_fingerprint"],
        "files": {path.name: file_sha256(path) for path in bundle.iterdir()}}, bundle / "manifest.json")
    state = tmp_path / "saved-review.json"
    ws.create_workspace(bundle, state)
    return state


def test_legacy_saved_review_reopens_byte_exact_after_profile_expansion(document, tmp_path):
    state = make_workspace(tmp_path, document)
    view = ws.get_view(state)
    ws.review_item(state, "reading-order", "blocked", "Synthetic reviewer", "2026-10-21", view["revision"], notes="Keep the pre-upgrade problem note")
    before = state.read_bytes()
    reopened = ws.get_view(state)
    assert not reopened["stale"] and reopened["counts"]["decision_total"] == 2
    assert reopened["manual_items"][0]["notes"] == "Keep the pre-upgrade problem note"
    assert state.read_bytes() == before


def test_expanded_workspace_uses_profile_and_retains_blocked_note_during_tag_edits(document, tmp_path):
    state = make_workspace(tmp_path, document, STRUCTURAL_INVENTORY_PROFILE)
    view = ws.get_view(state)
    view = ws.review_item(state, "reading-order", "blocked", "Synthetic reviewer", "2026-10-21", view["revision"], notes="Keep this exact problem")
    manual = copy.deepcopy(view["manual_items"][0])
    item = choose(view, "heading-tag", "P")
    view = ws.edit_decision(state, item["id"], "H1", view["revision"])
    assert not view["stale"] and view["manual_items"][0] == manual
    view = ws.approve_decision(state, item["id"], "Synthetic reviewer", "2026-10-21", view["revision"])
    assert view["unapplied_decisions"] == [item["id"]] and view["manual_items"][0] == manual
    assert view["verification"] == "not-verified"


@pytest.mark.parametrize("kind,value", [("heading-tag", "H99"), ("table-header", '{"role":"TD","scope":"Both"}')])
def test_invalid_structural_draft_refuses_without_changing_saved_review(document, tmp_path, kind, value):
    state = make_workspace(tmp_path, document, STRUCTURAL_INVENTORY_PROFILE)
    view = ws.get_view(state)
    item = choose(view, kind)
    before = state.read_bytes()
    with pytest.raises(ws.WorkspaceError):
        ws.edit_decision(state, item["id"], value, view["revision"])
    assert state.read_bytes() == before


def test_repair_findings_use_stored_evidence_without_new_authority_or_pdf_work(document, tmp_path, monkeypatch):
    path = make_workspace(tmp_path, document)
    state = ws.load_workspace(path, refresh=False)
    state["manual_items"].extend([
        {"id": "metadata-meaning", "category": "metadata-meaning", "status": "pending", "detail": "Confirm the language", "evidence": {"status": "fail", "suggested_language": "fr"}},
        {"id": "contrast", "category": "contrast", "status": "pending", "detail": "Repair source colors and reprocess", "evidence": {"status": "needs-review", "measurements": []}},
    ])
    state["residual_issues"] = [{"id": "language-correctness", "fix_path": "Review, edit and explicitly accept the language"}]
    before = copy.deepcopy(state)
    def no_pdf_work(*args, **kwargs):
        raise AssertionError("A view must not perform PDF work")
    monkeypatch.setattr(ws, "collect_decisions", no_pdf_work)
    view = ws._view(state)
    assert view["repair_findings"] == [
        {"id": "language-correctness", "status": "fail", "evidence": {"status": "fail", "suggested_language": "fr"}, "fix_path": "Review, edit and explicitly accept the language"},
        {"id": "contrast", "status": "needs-review", "evidence": {"status": "needs-review", "measurements": []}, "fix_path": "Repair source colors and reprocess"},
    ]
    assert state == before and view["verification"] == "not-verified"
    view["repair_findings"][0]["evidence"]["suggested_language"] = "de"
    assert state["manual_items"][-2]["evidence"]["suggested_language"] == "fr"
