"""Synthetic review-state tests; OCR inventory is an explicitly named core stub."""
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from types import ModuleType
import pytest

from pdf_remediator import workspace as ws
from pdf_remediator.sidecar import file_sha256, write_sidecar
from test_workspace import _make_bundle


def install_inventory_stub(monkeypatch):
    module = ModuleType("pdf_remediator.ocr_corrections")
    def inventory(bundle, *, profile="legacy"):
        report = json.loads((Path(bundle) / "report.json").read_text(encoding="utf-8"))
        source = report["input"]["sha256"]
        document = report["output"]["sha256"]
        items = [{"id": "ocr-page-1", "page": 1, "current": "WRNG", "original": "WRNG",
                  "context_sha256": hashlib.sha256(b"first OCR occurrence").hexdigest(),
                  "editable": True, "eligible": True, "limitations": [],
                  "supported_characters": "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "max_characters": 256},
                 {"id": "ocr-page-2", "page": 2, "current": "TEX", "original": "TEX",
                  "context_sha256": hashlib.sha256(b"second OCR occurrence").hexdigest(),
                  "editable": True, "eligible": True, "limitations": [],
                  "supported_characters": "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "max_characters": 256}]
        result = {"schema_version": "phase2-ocr-text-inventory-1", "source_sha256": source,
                "document_sha256": document, "inventory_sha256": hashlib.sha256((source + document).encode()).hexdigest(),
                "items": items, "eligible": True, "limitations": []}
        if profile == "expanded-v2":
            result.update(schema_version="phase2-ocr-text-inventory-2",
                          inventory_sha256=hashlib.sha256((source + document + "expanded").encode()).hexdigest(),
                          expansion_sha256=hashlib.sha256(b"explicit synthetic bundled font proof").hexdigest(),
                          font_policy={"id": "synthetic-verified-font", "sha256": hashlib.sha256(b"font").hexdigest(),
                                       "characters": "ABCDEFGHIJKLMNOPQRSTUVWXYZéΩ"})
            for item in items:
                item.update(context_sha256=hashlib.sha256((item["id"] + " expanded").encode()).hexdigest(),
                            font_policy="synthetic-verified-font", font_sha256=result["font_policy"]["sha256"],
                            insertion_eligible=True,
                            insertion_reason="", bbox=[.1, .1, .2, .08],
                            page_geometry={"rotation": 0, "width": 300, "height": 300})
                item.pop("supported_characters")
        return result
    def validate(item, value):
        characters = item.get("supported_characters", "")
        if (item.get("font_policy") == "synthetic-verified-font" and
                item.get("font_sha256") == hashlib.sha256(b"font").hexdigest()):
            characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZéΩ"
        if (not isinstance(value, str) or not value or len(value) > 256 or
                any(char not in characters for char in value)):
            raise ValueError("Replacement uses unsupported characters or whitespace")
        return value
    module.get_inventory = inventory
    module.validate_replacement = validate
    def insertion(anchor, value, placement):
        validate(anchor, value)
        if anchor.get("insertion_eligible") is not True or not isinstance(placement, dict):
            raise ValueError("No safe insertion anchor")
        rect = placement.get("rect")
        if (placement.get("order") not in ("before", "after") or not isinstance(rect, list) or len(rect) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in rect) or
                not (0 <= rect[0] < 1 and 0 <= rect[1] < 1 and rect[2] > 0 and rect[3] > 0 and
                     rect[0] + rect[2] <= 1 and rect[1] + rect[3] <= 1)):
            raise ValueError("Unsupported insertion placement")
        return {"rect": [float(v) for v in rect], "order": placement["order"]}
    def operation(inventory, row):
        if row.get("kind") not in ("replace", "insert"):
            raise ValueError("Unknown synthetic operation")
        anchor = next((item for item in inventory["items"] if item["id"] == row.get("anchor_id", row.get("id"))), None)
        if anchor is None or anchor["context_sha256"] != row.get("context_sha256"):
            raise ValueError("Synthetic anchor context changed")
        if row["kind"] == "insert":
            if row.get("original") != "" or row.get("page") != anchor["page"]:
                raise ValueError("Synthetic inserted word scope changed")
            insertion(anchor, row["value"], row["placement"])
        else:
            if row.get("original") != anchor["current"]:
                raise ValueError("Synthetic replacement context changed")
            validate(anchor, row["value"])
    module.validate_insertion = insertion
    module.validate_operation = operation
    def lineage_bindings(path, source, expected_sha256=None, cancel=None):
        # Explicit small metadata/hash stub: actual core proof traversal is
        # covered by core tests; workspace tests must call this guard afresh.
        if expected_sha256 != file_sha256(path) or not Path(source).is_file():
            raise ValueError("Synthetic lineage binding changed")
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        for row in record.get("dependencies", []):
            if file_sha256(row["path"]) != row["sha256"]:
                raise ValueError("Synthetic external lineage dependency changed")
        return {"bindings_verified": True}
    module.validate_lineage_bindings = lineage_bindings
    monkeypatch.setitem(sys.modules, "pdf_remediator.ocr_corrections", module)
    return module


@pytest.fixture
def ocr_sample(tmp_path, monkeypatch):
    core = install_inventory_stub(monkeypatch)
    bundle, source, prepared, output, report = _make_bundle(tmp_path)
    state = tmp_path / "reviews" / "workspace.json"
    ws.create_workspace(bundle, state)
    return {"bundle": bundle, "source": source, "prepared": prepared, "output": output,
            "report": report, "state": state, "core": core, "tmp": tmp_path}


def save(sample, value="WRONG", page=1):
    view = ws.get_ocr_editor(sample["state"], page)
    item = view["items"][0]
    return ws.edit_ocr_text(sample["state"], item["id"], value, view["revision"],
                            view["inventory_sha256"], item["context_sha256"])


def accept(sample, page=1):
    view = ws.get_ocr_editor(sample["state"], page)
    item = view["items"][0]
    return ws.approve_ocr_text(sample["state"], item["id"], "Synthetic Reviewer", "2026-10-25",
                              view["revision"], view["inventory_sha256"], item["context_sha256"])


def expanded_view(sample, page=1):
    return ws.get_ocr_editor(sample["state"], page, profile="expanded-v2")


def save_expanded(sample, value="WRéNG", page=1):
    view = expanded_view(sample, page)
    item = view["items"][0]
    return ws.edit_ocr_text(sample["state"], item["id"], value, view["revision"],
                            view["inventory_sha256"], item["context_sha256"], expansion_sha256=view["expansion_sha256"])


def save_insertion(sample, value="WORD", *, page=1, placement=None, identifier=None):
    view = expanded_view(sample, page)
    anchor = view["items"][0]
    return ws.insert_ocr_text(sample["state"], anchor["id"], value,
        placement or {"rect": [.35, .1, .1, .08], "order": "after"}, view["revision"],
        view["inventory_sha256"], anchor["context_sha256"], identifier=identifier,
        expansion_sha256=view["expansion_sha256"])


def accept_expanded(sample, identifier=None, page=1):
    view = expanded_view(sample, page)
    item = next((item for item in view["insertions"] if item["id"] == identifier), view["items"][0])
    return ws.approve_ocr_text(sample["state"], identifier or item["id"], "Synthetic Reviewer", "2026-10-25",
        view["revision"], view["inventory_sha256"], item["context_sha256"], expansion_sha256=view["expansion_sha256"])


def test_old_review_editor_inspection_does_not_migrate_or_rewrite_saved_work(ocr_sample):
    s = ocr_sample
    old = s["state"].read_bytes()
    pdfs = {key: file_sha256(s[key]) for key in ("source", "prepared", "output")}
    one = ws.get_ocr_editor(s["state"], 1)
    two = ws.get_ocr_editor(s["state"], 2)
    assert [item["current"] for item in one["items"]] == ["WRNG"]
    assert [item["current"] for item in two["items"]] == ["TEX"]
    assert s["state"].read_bytes() == old
    assert "ocr_text_edits" not in json.loads(old)
    assert pdfs == {key: file_sha256(s[key]) for key in pdfs}


def test_extended_inventory_is_opt_in_and_does_not_migrate_the_saved_review(ocr_sample):
    s = ocr_sample
    before = s["state"].read_bytes()
    legacy = ws.get_ocr_editor(s["state"])
    expanded = expanded_view(s)
    assert legacy["profile"] == "legacy" and legacy["expansion_sha256"] is None
    assert expanded["profile"] == "expanded-v2" and expanded["expansion_available"]
    assert expanded["insertion_enabled"] and expanded["items"][0]["bbox"] == [.1, .1, .2, .08]
    assert expanded["font_policy"]["id"] == "synthetic-verified-font"
    assert expanded["insertions"] == [] and s["state"].read_bytes() == before


def test_expanded_coverage_is_returned_once_and_not_required_on_each_public_word(ocr_sample):
    s = ocr_sample
    inventory = expanded_view(s)
    assert "é" in inventory["font_policy"]["characters"]
    assert all("supported_characters" not in item for item in inventory["items"])
    save_expanded(s); view = accept_expanded(s)
    exported = ws.export_ocr_corrections(s["state"], s["tmp"] / "compact-font-coverage", view["revision"])
    plan = json.loads(Path(exported["ocr_corrections_path"]).read_text(encoding="utf-8"))
    assert plan["corrections"][0]["value"] == "WRéNG"
    assert plan["expansion_sha256"] == inventory["expansion_sha256"]


def test_legacy_accepted_drafts_keep_their_digest_and_export_until_applied_or_reverted(ocr_sample):
    s = ocr_sample
    save(s); accept(s)
    before = s["state"].read_bytes()
    old_editor = json.loads(before)["ocr_text_edits"]
    expanded = expanded_view(s)
    assert expanded["profile"] == "legacy" and not expanded["expansion_available"]
    assert "Apply or revert" in expanded["expansion_reason"]
    assert s["state"].read_bytes() == before
    exported = ws.export_ocr_corrections(s["state"], s["tmp"] / "old-plan", expanded["revision"])
    plan = json.loads(Path(exported["ocr_corrections_path"]).read_text(encoding="utf-8"))
    assert plan["schema_version"] == "phase2-ocr-text-corrections-1"
    assert "expansion_sha256" not in plan and "kind" not in plan["corrections"][0]
    assert plan["corrections"][0]["acceptance_sha256"] == old_editor["items"]["ocr-page-1"]["acceptance_sha256"]
    assert s["state"].read_bytes() == before
    save(s, "WRNG")
    assert expanded_view(s)["profile"] == "expanded-v2"
    save_expanded(s)
    assert ws.load_workspace(s["state"])["ocr_text_edits"]["schema_version"] == "phase2-ocr-text-corrections-2"


def test_extended_font_replacement_acceptance_binds_the_expansion_and_exports_exact_fields(ocr_sample):
    s = ocr_sample
    legacy = ws.get_ocr_editor(s["state"])
    before = s["state"].read_bytes()
    with pytest.raises(ValueError, match="unsupported"):
        ws.edit_ocr_text(s["state"], legacy["items"][0]["id"], "WRéNG", legacy["revision"],
                         legacy["inventory_sha256"], legacy["items"][0]["context_sha256"])
    assert s["state"].read_bytes() == before
    save_expanded(s); accepted = accept_expanded(s)
    reopened = ws.get_ocr_editor(s["state"])
    assert reopened["profile"] == "expanded-v2" and reopened["items"][0]["value"] == "WRéNG"
    exported = ws.export_ocr_corrections(s["state"], s["tmp"] / "extended-replace", accepted["revision"])
    plan = json.loads(Path(exported["ocr_corrections_path"]).read_text(encoding="utf-8"))
    row = plan["corrections"][0]
    assert set(row) == {"kind", "id", "context_sha256", "original", "value", "reviewer", "reviewed_at", "acceptance_sha256"}
    assert row["kind"] == "replace" and "page" not in row
    payload = {key: val for key, val in row.items() if key != "acceptance_sha256"}
    payload.update({key: plan[key] for key in ("source_sha256", "document_sha256", "inventory_sha256", "expansion_sha256")})
    assert row["acceptance_sha256"] == ws._digest(payload)
    assert plan["human_approved"] is plan["accessibility_approved"] is False


def test_missing_word_reopens_accepts_and_exports_placement_without_changing_pdfs_or_blocker_notes(ocr_sample):
    s = ocr_sample
    before = {key: file_sha256(s[key]) for key in ("source", "prepared", "output")}
    view = ws.get_view(s["state"])
    ws.review_item(s["state"], "reading-order", "blocked", "Synthetic Reviewer", "2026-10-25",
                   view["revision"], notes="Earlier missing content must still be reviewed.")
    saved = save_insertion(s, "ΩWORD")
    identifier = saved["ocr_saved_insertion_id"]
    assert saved["ocr_editor"]["changed_count"] == 1 and identifier in saved["unapplied_decisions"]
    opened = expanded_view(s)
    inserted = opened["insertions"][0]
    assert inserted["id"] == identifier and inserted["original"] == "" and inserted["value"] == "ΩWORD"
    assert inserted["placement"] == {"rect": [.35, .1, .1, .08], "order": "after"}
    assert inserted["context_sha256"] == opened["items"][0]["context_sha256"]
    accepted = accept_expanded(s, identifier)
    assert accepted["ocr_editor"]["accepted_count"] == 1
    note = next(item for item in accepted["manual_items"] if item["id"] == "reading-order")
    assert note["status"] == "blocked" and note["notes"] == "Earlier missing content must still be reviewed."
    old_review = s["state"].read_bytes()
    exported = ws.export_ocr_corrections(s["state"], s["tmp"] / "insert-plan", accepted["revision"])
    plan = json.loads(Path(exported["ocr_corrections_path"]).read_text(encoding="utf-8"))
    row = plan["corrections"][0]
    assert set(row) == {"kind", "id", "anchor_id", "page", "original", "value", "placement", "context_sha256",
                        "reviewer", "reviewed_at", "acceptance_sha256"}
    payload = {key: value for key, value in row.items() if key != "acceptance_sha256"}
    payload.update({key: plan[key] for key in ("source_sha256", "document_sha256", "inventory_sha256", "expansion_sha256")})
    assert row["acceptance_sha256"] == ws._digest(payload)
    assert s["state"].read_bytes() == old_review
    assert before == {key: file_sha256(s[key]) for key in before}
    assert not exported["ledger_eligible"] and exported["requires_reprocessing"]


def test_insertion_changes_reset_acceptance_same_save_retains_it_and_remove_preserves_history(ocr_sample):
    s = ocr_sample
    identifier = save_insertion(s)["ocr_saved_insertion_id"]
    accept_expanded(s, identifier)
    assert save_insertion(s, identifier=identifier)["ocr_editor"]["accepted_count"] == 1
    changed = save_insertion(s, placement={"rect": [.5, .2, .1, .08], "order": "before"}, identifier=identifier)
    assert changed["ocr_editor"]["accepted_count"] == 0
    with pytest.raises(ws.WorkspaceError, match="Accept each"):
        ws.export_ocr_corrections(s["state"], s["tmp"] / "not-accepted", changed["revision"])
    accept_expanded(s, identifier)
    view = expanded_view(s)
    removed = ws.remove_ocr_insertion(s["state"], identifier, view["revision"], view["inventory_sha256"],
        view["insertions"][0]["context_sha256"], expansion_sha256=view["expansion_sha256"])
    assert removed["ocr_editor"]["changed_count"] == 0 and not removed["unapplied_decisions"]
    assert expanded_view(s)["insertions"] == []
    assert any(event["action"] == "remove-ocr-insertion" and event["previous"]["value"] == "WORD"
               for event in ws.load_workspace(s["state"])["history"])


@pytest.mark.parametrize("defect", ["missing-capability", "wrong-capability", "revision", "context", "inventory", "unknown-id", "ai"])
def test_invalid_insert_action_preserves_saved_review_bytes(ocr_sample, defect):
    s = ocr_sample
    view = expanded_view(s)
    anchor = view["items"][0]
    kwargs = {"state_path": s["state"], "anchor_identifier": anchor["id"], "value": "WORD",
              "placement": {"rect": [.35, .1, .1, .08], "order": "after"}, "expected_revision": view["revision"],
              "inventory_sha256": view["inventory_sha256"], "context_sha256": anchor["context_sha256"],
              "expansion_sha256": view["expansion_sha256"]}
    if defect == "missing-capability": kwargs.pop("expansion_sha256")
    if defect == "wrong-capability": kwargs["expansion_sha256"] = "0" * 64
    if defect == "revision": kwargs["expected_revision"] += 1
    if defect == "context": kwargs["context_sha256"] = "0" * 64
    if defect == "inventory": kwargs["inventory_sha256"] = "0" * 64
    if defect == "unknown-id": kwargs["identifier"] = "ocr-insert-" + "0" * 32
    if defect == "ai": kwargs["actor"] = "ai"
    before = s["state"].read_bytes()
    with pytest.raises(ValueError):
        ws.insert_ocr_text(**kwargs)
    assert s["state"].read_bytes() == before


@pytest.mark.parametrize("placement,value", [
    ({"rect": [-.1, .1, .1, .08], "order": "after"}, "WORD"),
    ({"rect": [.95, .1, .1, .08], "order": "after"}, "WORD"),
    ({"rect": [.35, .1, 0, .08], "order": "after"}, "WORD"),
    ({"rect": [.35, .1, .1, float("nan")], "order": "after"}, "WORD"),
    ({"rect": [True, .1, .1, .08], "order": "after"}, "WORD"),
    ({"rect": [.35, .1, .1, .08], "order": "first"}, "WORD"),
    ({"rect": [.35, .1, .1, .08], "order": "after"}, "TWO WORDS"),
    ({"rect": [.35, .1, .1, .08], "order": "after"}, ""),
    ({"rect": [.35, .1, .1, .08], "order": "after"}, "字"),
])
def test_invalid_insertion_text_or_geometry_cannot_write_a_draft(ocr_sample, placement, value):
    s = ocr_sample
    before = s["state"].read_bytes()
    with pytest.raises(ValueError):
        save_insertion(s, value, placement=placement)
    assert s["state"].read_bytes() == before


@pytest.mark.parametrize("first", ["replacement", "insertion"])
def test_replacement_and_insertion_cannot_share_an_anchor(ocr_sample, first):
    s = ocr_sample
    if first == "replacement": save_expanded(s)
    else: save_insertion(s)
    before = s["state"].read_bytes()
    with pytest.raises(ws.WorkspaceError, match="same OCR anchor"):
        (save_insertion(s) if first == "replacement" else save_expanded(s))
    assert s["state"].read_bytes() == before


def test_duplicate_insertion_anchor_is_refused_and_pending_insertion_is_never_silently_discarded(ocr_sample):
    s = ocr_sample
    first = save_insertion(s)["ocr_saved_insertion_id"]
    before = s["state"].read_bytes()
    with pytest.raises(ws.WorkspaceError, match="Only one"):
        save_insertion(s, placement={"rect": [.5, .2, .1, .08], "order": "before"})
    assert s["state"].read_bytes() == before
    accept_expanded(s, first)
    save_insertion(s, "SECOND", page=2)
    view = ws.get_view(s["state"])
    assert view["ocr_editor"]["changed_count"] == 2 and view["ocr_editor"]["accepted_count"] == 1
    with pytest.raises(ws.WorkspaceError, match="Accept each"):
        ws.export_ocr_corrections(s["state"], s["tmp"] / "strict-pending-insertion", view["revision"])
    exported = ws.export_workspace(s["state"], s["tmp"] / "general-insert-export", view["revision"])
    plan = json.loads(Path(exported["ocr_corrections_path"]).read_text(encoding="utf-8"))
    assert [item["id"] for item in plan["corrections"]] == [first]
    assert exported["requires_reprocessing"] and not exported["ledger_eligible"]


def test_changed_font_policy_blocks_saved_expanded_operations_without_overwriting_them(ocr_sample, monkeypatch):
    s = ocr_sample
    save_expanded(s); accept_expanded(s)
    before = s["state"].read_bytes()
    real = s["core"].get_inventory
    def changed(bundle, *, profile="legacy"):
        result = real(bundle, profile=profile)
        if profile == "expanded-v2": result["expansion_sha256"] = "0" * 64
        return result
    monkeypatch.setattr(s["core"], "get_inventory", changed)
    with pytest.raises(ws.StaleWorkspace, match="capability changed"):
        expanded_view(s)
    with pytest.raises(ws.StaleWorkspace):
        ws.export_ocr_corrections(s["state"], s["tmp"] / "font-changed", ws.get_view(s["state"])["revision"])
    assert s["state"].read_bytes() == before


def test_overlapping_insertions_at_different_anchors_cannot_be_saved_together(ocr_sample, monkeypatch):
    s = ocr_sample
    real = s["core"].get_inventory
    def two_anchors(bundle, *, profile="legacy"):
        result = real(bundle, profile=profile)
        if profile == "expanded-v2":
            extra = copy.deepcopy(result["items"][0])
            extra.update(id="ocr-page-1-second", context_sha256=hashlib.sha256(b"extra synthetic anchor").hexdigest())
            result["items"].append(extra)
        return result
    monkeypatch.setattr(s["core"], "get_inventory", two_anchors)
    save_insertion(s)
    view = expanded_view(s)
    anchor = view["items"][1]
    before = s["state"].read_bytes()
    with pytest.raises(ws.WorkspaceError, match="must not overlap"):
        ws.insert_ocr_text(s["state"], anchor["id"], "SECOND", {"rect": [.38, .1, .1, .08], "order": "after"},
            view["revision"], view["inventory_sha256"], anchor["context_sha256"], expansion_sha256=view["expansion_sha256"])
    assert s["state"].read_bytes() == before


@pytest.mark.parametrize("change", ["anchor-context", "prepared-pdf"])
def test_saved_insertion_rejects_changed_preparation_or_anchor_and_retains_its_text(ocr_sample, monkeypatch, change):
    s = ocr_sample
    identifier = save_insertion(s)["ocr_saved_insertion_id"]
    accept_expanded(s, identifier)
    before = s["state"].read_bytes()
    if change == "anchor-context":
        real = s["core"].get_inventory
        def changed(bundle, *, profile="legacy"):
            result = real(bundle, profile=profile)
            if profile == "expanded-v2": result["items"][0]["context_sha256"] = "0" * 64
            return result
        monkeypatch.setattr(s["core"], "get_inventory", changed)
        with pytest.raises(ws.StaleWorkspace, match="operation changed"):
            expanded_view(s)
        assert s["state"].read_bytes() == before
    else:
        s["prepared"].write_bytes(s["prepared"].read_bytes() + b"\n% synthetic changed preparation")
        view = ws.get_view(s["state"])
        assert view["stale"] and view["ocr_editor"]["accepted_count"] == 0
    assert ws.load_workspace(s["state"])["ocr_text_edits"]["items"][identifier]["value"] == "WORD"


def test_saved_word_reopens_and_acceptance_is_occurrence_and_value_bound(ocr_sample):
    s = ocr_sample
    before = {key: file_sha256(s[key]) for key in ("source", "prepared", "output")}
    saved = save(s)
    assert saved["ocr_editor"] == {"available": True, "changed_count": 1, "accepted_count": 0,
                                  "requires_reprocessing": True, "limits": ws._OCR_LIMITS}
    reopened = ws.get_ocr_editor(s["state"])
    assert reopened["items"][0]["value"] == "WRONG"
    accepted = accept(s)
    assert accepted["ocr_editor"]["accepted_count"] == 1
    state = ws.load_workspace(s["state"])
    editor = state["ocr_text_edits"]
    item = editor["items"]["ocr-page-1"]
    payload = {key: item[key] for key in ("id", "context_sha256", "original", "value", "reviewer", "reviewed_at")}
    payload.update({key: editor[key] for key in ("source_sha256", "document_sha256", "inventory_sha256")})
    assert item["acceptance_sha256"] == hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert before == {key: file_sha256(s[key]) for key in before}
    assert accepted["verification"] == "not-verified"


def test_ocr_edit_retains_blocker_pending_and_approved_notes_without_transferring_approval(ocr_sample):
    s = ocr_sample
    v = ws.get_view(s["state"])
    v = ws.review_item(s["state"], "reading-order", "blocked", "Synthetic Reviewer", "2026-10-25",
                       v["revision"], notes="The earlier reading-order problem remains.")
    v = ws.review_item(s["state"], "contrast", "approved", "Synthetic Reviewer", "2026-10-25",
                       v["revision"], notes="Earlier contrast observations must remain.")
    v = save(s)
    items = {item["id"]: item for item in v["manual_items"]}
    assert items["reading-order"]["status"] == "blocked"
    assert items["reading-order"]["notes"] == "The earlier reading-order problem remains."
    assert items["contrast"]["status"] == "pending"
    assert items["contrast"]["notes"] == "Earlier contrast observations must remain."
    assert not ws.load_workspace(s["state"])["manual_approvals"]
    accept(s)
    exported = ws.export_ocr_corrections(s["state"], s["tmp"] / "export", ws.get_view(s["state"])["revision"])
    plan = json.loads(Path(exported["ocr_corrections_path"]).read_text(encoding="utf-8"))
    assert len(plan["corrections"]) == 1
    assert plan["corrections"][0]["original"] == "WRNG"
    assert plan["human_approved"] is plan["accessibility_approved"] is False
    assert ws.get_view(s["state"])["manual_items"] == v["manual_items"]


@pytest.mark.parametrize("defect", ["revision", "bool-revision", "inventory", "context", "unknown-id", "unsupported"])
def test_stale_or_wrong_occurrence_edits_leave_saved_review_byte_identical(ocr_sample, defect):
    s = ocr_sample
    view = ws.get_ocr_editor(s["state"])
    item = view["items"][0]
    args = [s["state"], item["id"], "WRONG", view["revision"], view["inventory_sha256"], item["context_sha256"]]
    if defect == "revision": args[3] += 1
    if defect == "bool-revision": args[3] = False
    if defect == "inventory": args[4] = "0" * 64
    if defect == "context": args[5] = "0" * 64
    if defect == "unknown-id": args[1] = "other-occurrence"
    if defect == "unsupported": args[2] = "no whitespace"
    before = s["state"].read_bytes()
    with pytest.raises(ValueError):
        ws.edit_ocr_text(*args)
    assert s["state"].read_bytes() == before


def test_changed_draft_invalidates_acceptance_and_revert_removes_unapplied_text(ocr_sample):
    s = ocr_sample
    save(s); accept(s)
    same = save(s)
    assert same["ocr_editor"]["accepted_count"] == 1
    changed = save(s, "WRONGER")
    assert changed["ocr_editor"]["accepted_count"] == 0
    with pytest.raises(ws.WorkspaceError, match="Accept each"):
        ws.export_ocr_corrections(s["state"], s["tmp"] / "pending", changed["revision"])
    reverted = save(s, "WRNG")
    assert reverted["ocr_editor"]["changed_count"] == 0
    assert not reverted["unapplied_decisions"]


def test_pending_other_words_are_not_silently_dropped_from_strict_application(ocr_sample):
    s = ocr_sample
    save(s); accept(s); save(s, "TEXT", page=2)
    before = s["state"].read_bytes()
    destination = s["tmp"] / "strict-pending"
    with pytest.raises(ws.WorkspaceError, match="Accept each"):
        ws.export_ocr_corrections(s["state"], destination, ws.get_view(s["state"])["revision"])
    assert not destination.exists() and s["state"].read_bytes() == before
    exported = ws.export_workspace(s["state"], s["tmp"] / "general-export", ws.get_view(s["state"])["revision"])
    plan = json.loads(Path(exported["ocr_corrections_path"]).read_text(encoding="utf-8"))
    assert [item["id"] for item in plan["corrections"]] == ["ocr-page-1"]
    assert exported["requires_reprocessing"] and not exported["ledger_eligible"]


def test_document_edits_and_ocr_corrections_require_explicit_separate_passes(ocr_sample):
    s = ocr_sample
    save(s); accept(s)
    v = ws.get_view(s["state"])
    ws.edit_decision(s["state"], "metadata:title", "Changed title draft", v["revision"])
    before = s["state"].read_bytes()
    with pytest.raises(ws.WorkspaceError, match="other document edits"):
        ws.export_ocr_corrections(s["state"], s["tmp"] / "mixed", ws.get_view(s["state"])["revision"])
    assert s["state"].read_bytes() == before


def test_changed_pdf_invalidates_ocr_acceptance_but_retains_the_saved_text(ocr_sample):
    s = ocr_sample
    save(s); accept(s)
    raw = s["source"].read_bytes()
    s["source"].write_bytes(raw + b"\n% changed test input")
    v = ws.get_view(s["state"])
    assert v["stale"] and v["ocr_editor"]["accepted_count"] == 0
    state = ws.load_workspace(s["state"])
    assert state["ocr_text_edits"]["items"]["ocr-page-1"]["value"] == "WRONG"
    s["source"].write_bytes(raw)
    assert ws.get_view(s["state"])["stale"]
    with pytest.raises(ws.StaleWorkspace):
        ws.get_ocr_editor(s["state"])


def test_ai_actor_cannot_save_or_accept_ocr_text(ocr_sample):
    s = ocr_sample
    view = ws.get_ocr_editor(s["state"]); item = view["items"][0]
    before = s["state"].read_bytes()
    with pytest.raises(ws.WorkspaceError, match="human"):
        ws.edit_ocr_text(s["state"], item["id"], "WRONG", view["revision"],
                         view["inventory_sha256"], item["context_sha256"], actor="ai")
    with pytest.raises(ws.WorkspaceError, match="human"):
        ws.approve_ocr_text(s["state"], item["id"], "AI", "2026-10-25", view["revision"],
                            view["inventory_sha256"], item["context_sha256"], actor="ai")
    assert s["state"].read_bytes() == before


def test_export_race_with_original_change_publishes_no_partial_plan(ocr_sample, monkeypatch):
    s = ocr_sample
    save(s); accept(s)
    real = ws.write_sidecar
    def during_write(data, path):
        result = real(data, path)
        if Path(path).name == "ocr-corrections.json":
            s["source"].write_bytes(s["source"].read_bytes() + b"\n% export race")
        return result
    monkeypatch.setattr(ws, "write_sidecar", during_write)
    destination = s["tmp"] / "raced-export"
    with pytest.raises(ws.StaleWorkspace):
        ws.export_ocr_corrections(s["state"], destination, ws.get_view(s["state"])["revision"])
    assert not list(destination.glob("review-*"))
    assert not list(destination.glob(".review-export-*"))


def test_ocr_inventory_context_change_refuses_saved_edits_without_overwriting_them(ocr_sample, monkeypatch):
    s = ocr_sample
    save(s); accept(s)
    original_inventory = s["core"].get_inventory
    def changed(bundle):
        inventory = original_inventory(bundle)
        inventory["items"][0]["context_sha256"] = "a" * 64
        return inventory
    monkeypatch.setattr(s["core"], "get_inventory", changed)
    before = s["state"].read_bytes()
    with pytest.raises(ws.StaleWorkspace, match="occurrence changed"):
        ws.get_ocr_editor(s["state"])
    assert s["state"].read_bytes() == before


def test_accepted_ocr_draft_blocks_artifact_approval_and_never_qualifies_for_ledger(ocr_sample):
    s = ocr_sample
    save(s); accept(s)
    v = ws.get_view(s["state"])
    with pytest.raises(ws.WorkspaceError, match="reprocessing"):
        ws.review_item(s["state"], "reading-order", "approved", "Synthetic Reviewer", "2026-10-25", v["revision"])
    exported = ws.export_workspace(s["state"], s["tmp"] / "not-verified", v["revision"])
    assert exported["verification"] == "not-verified" and exported["requires_reprocessing"]
    assert exported["ledger_eligible"] is False


def lineaged_review(sample):
    bundle, source, prepared, output, report = _make_bundle(sample["tmp"], name="lineaged-result")
    lineage = sample["tmp"] / "external-lineage-metadata-stub.json"
    lineage.write_text(json.dumps({"test": "explicit small metadata/hash stub", "dependencies": [
        {"path": str(sample["source"]), "sha256": file_sha256(sample["source"])}]}), encoding="utf-8")
    report["source_lineage"] = {"path": str(lineage), "sha256": file_sha256(lineage)}
    write_sidecar(report, bundle / "report.json")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["report.json"] = file_sha256(bundle / "report.json")
    write_sidecar(manifest, bundle / "manifest.json")
    state = sample["tmp"] / "reviews" / "lineaged-workspace.json"
    ws.create_workspace(bundle, state)
    return state, lineage


def test_corrected_review_checks_lineage_dependencies_without_ocr_inventory_parsing(ocr_sample, monkeypatch):
    s = ocr_sample
    state, _ = lineaged_review(s)
    before = state.read_bytes()
    def no_ocr_parse(bundle):
        raise AssertionError("A normal view or approval must not build the OCR inventory")
    monkeypatch.setattr(s["core"], "get_inventory", no_ocr_parse)
    view = ws.get_view(state)
    assert not view["stale"] and state.read_bytes() == before
    view = ws.review_item(state, "contrast", "approved", "Synthetic Reviewer", "2026-10-25",
                          view["revision"], notes="Current reviewed contrast observation.")
    assert view["counts"]["manual_approved"] == 1
    exported = ws.export_workspace(state, s["tmp"] / "lineage-export", view["revision"])
    assert exported["verification"] == "not-verified"


@pytest.mark.parametrize("defect", ["lineage", "true-original", "missing-lineage"])
def test_changed_external_lineage_invalidates_approval_and_blocks_export(ocr_sample, defect):
    s = ocr_sample
    state, lineage = lineaged_review(s)
    v = ws.get_view(state)
    v = ws.review_item(state, "contrast", "approved", "Synthetic Reviewer", "2026-10-25",
                       v["revision"], notes="Keep this earlier review observation.")
    v = ws.review_item(state, "reading-order", "blocked", "Synthetic Reviewer", "2026-10-25",
                       v["revision"], notes="Keep the earlier blocked problem note.")
    v = ws.review_item(state, "regroup-a", "pending", "Synthetic Reviewer", "2026-10-25",
                       v["revision"], notes="Keep this pending observation too.")
    if defect == "lineage":
        lineage.write_bytes(lineage.read_bytes() + b" ")
    elif defect == "true-original":
        s["source"].write_bytes(s["source"].read_bytes() + b"\n% changed original dependency")
    else:
        lineage.unlink()
    stale = ws.get_view(state)
    assert stale["stale"] and stale["counts"]["manual_approved"] == 0
    manual = {item["id"]: item for item in stale["manual_items"]}
    assert manual["contrast"]["notes"] == "Keep this earlier review observation."
    assert manual["reading-order"]["status"] == "blocked"
    assert manual["reading-order"]["notes"] == "Keep the earlier blocked problem note."
    assert manual["regroup-a"]["notes"] == "Keep this pending observation too."
    assert all("reviewer" not in item and "reviewed_at" not in item for item in manual.values())
    assert len(stale["history"][-1]["retained_manual_notes"]) == 3
    assert any("lineage" in reason.lower() for reason in ws.load_workspace(state)["stale_reasons"])
    destination = s["tmp"] / "refused-stale-lineage"
    with pytest.raises(ws.StaleWorkspace):
        ws.export_workspace(state, destination, stale["revision"])
    assert not destination.exists()
    with pytest.raises(ws.StaleWorkspace):
        ws.review_item(state, "contrast", "approved", "Synthetic Reviewer", "2026-10-25", stale["revision"])


