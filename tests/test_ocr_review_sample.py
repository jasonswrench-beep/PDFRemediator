"""The scanned-page sample and a person's records of it. Authored fixtures; gate labels are named stubs.

Nothing here runs text recognition. The recognition's per-page measurements are built with the program's own summary function, so
the sample sees exactly the shape a real run records. A passing test is not accuracy or accessibility evidence for any real scan.
"""
import copy
import json
from pathlib import Path
import shutil

import pikepdf
import pytest

from pdf_remediator import ledger, ocr_confidence, review
from pdf_remediator import ocr_review_sample as sample_module
from pdf_remediator import web, workspace as ws
from pdf_remediator.cli import _review_data
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.ledger import _eligible
from pdf_remediator.pipeline import verify_bundle
from pdf_remediator.sidecar import collect_decisions, file_sha256, write_sidecar

REVIEWER = "Synthetic Scan Reviewer"
DATE = "2026-11-16"
ALL_PASS = {key: "pass" for key in sample_module.CHECKS}


def _pdf(path, pages):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.new() as pdf:
        for _ in range(pages):
            pdf.add_blank_page(page_size=(200, 300))
        pdf.Root.Lang = "en-US"
        pdf.docinfo.Title = "Synthetic scan fixture"
        pdf.save(path, deterministic_id=True)


def _readings(table, layout="standard"):
    measured = [{"page": page, "reading": {"words": words, "sure_words": sure, "mean_confidence": 90.0}} for page, (words, sure) in table.items()]
    return ocr_confidence.summarise(measured, sorted(table), layout)


DEFAULT_TABLE = {1: (200, 195), 2: (150, 60), 3: (3, 3), 4: (120, 100), 5: (300, 290), 6: (80, 78)}


def make_report(tmp_path, *, pages=8, scanned=range(1, 7), table=None, name="scan", mixed=()):
    source = tmp_path / "inputs" / (name + ".pdf")
    _pdf(source, pages)
    prepared = tmp_path / "prepared" / (name + ".pdf")
    prepared.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, prepared)
    bundle = tmp_path / name
    bundle.mkdir()
    output = bundle / "candidate.pdf"
    shutil.copyfile(prepared, output)
    sha = file_sha256(source)
    classes = [{"page": number, "class": "scanned" if number in scanned else "mixed" if number in mixed else "text",
                "text_characters": 0 if number in scanned else 900} for number in range(1, pages + 1)]
    manual = [{"id": "image-and-ocr", "category": "image-and-ocr", "subject": "Scanned text and image meaning",
               "detail": "Check each image region for missing scanned text.", "pages": sorted(scanned), "required": True, "status": "pending"},
              {"id": "reading-order", "category": "reading-order", "detail": "Inspect all pages in logical order", "pages": [], "required": True, "status": "pending"}]
    processors = []
    if table is None:
        table = {page: DEFAULT_TABLE.get(page, (100, 99)) for page in scanned}
    if table:
        processors.append({"name": "ocr", "status": "pass", "reading_confidence": _readings(table)})
    report = {"status": "candidate", "mode": "fix", "run_fingerprint": "synthetic-" + name,
              "input": {"path": str(source), "sha256": sha},
              "output": {"path": str(output), "sha256": sha, "review_only": False},
              "decision_source": {"path": str(prepared), "sha256": sha, "source_sha256": sha},
              "classification": classes, "baseline": {"pages": classes, "page_count": pages},
              "inspection": {"page_count": pages, "pages": [{"page": n, "text_characters": 800} for n in range(1, pages + 1)]},
              "processors": processors,
              "manual_review": {"artifact_sha256": sha, "items": manual, "complete": False}, "residual_issues": [],
              "gate1": {"status": "pass", "profile": "ua1", "is_compliant": True, "input_sha256": sha,
                        "execution": {"status": "completed", "returncode": 0},
                        "counts": {"passedRules": 106, "failedRules": 0, "failedChecks": 0}},
              "gate2": {"status": "pass", "checks": [{"id": "synthetic-test-stub", "status": "pass", "blocking": True}],
                        "blockers": [], "manual_queue": copy.deepcopy(manual)},
              "fidelity": {"status": "pass", "after_sha256": sha}}
    write_sidecar(report, bundle / "report.json")
    write_sidecar(report["manual_review"], bundle / "review.json")
    write_sidecar(collect_decisions(prepared, sha), bundle / "decisions.json")
    (bundle / "review.html").write_text("<!doctype html><html lang='en'><title>Test review</title></html>", encoding="utf-8")
    files = {path.name: file_sha256(path) for path in bundle.iterdir() if path.is_file()}
    write_sidecar({"schema_version": "phase1-bundle-1", "complete": True, "run_fingerprint": report["run_fingerprint"], "files": files}, bundle / "manifest.json")
    assert verify_bundle(bundle)
    return bundle, source, output, report


@pytest.fixture
def scan(tmp_path):
    bundle, source, output, report = make_report(tmp_path)
    state = tmp_path / "reviews" / "workspace.json"
    ws.create_workspace(bundle, state)
    return {"bundle": bundle, "source": source, "output": output, "report": report, "state": state, "tmp": tmp_path}


def _record(scan, page, checks=None, notes="", reviewer=REVIEWER):
    view = ws.get_view(scan["state"])
    return ws.record_ocr_sample_page(scan["state"], page, checks or ALL_PASS, notes, reviewer, DATE, view["revision"])


def _record_all(scan):
    view = ws.get_view(scan["state"])
    for entry in view["ocr_review_sample"]["pages"]:
        view = _record(scan, entry["page"])
    return view


def _approve_scan_review(scan, status="approved"):
    view = ws.get_view(scan["state"])
    return ws.review_item(scan["state"], "image-and-ocr", status, REVIEWER, DATE, view["revision"])


# --- choosing the sample -------------------------------------------------------------------------------------------------

def test_sample_is_bounded_reproducible_and_explains_every_page(scan):
    sha = scan["report"]["output"]["sha256"]
    first = sample_module.choose_sample(scan["report"], sha)
    again = sample_module.choose_sample(copy.deepcopy(scan["report"]), sha)
    assert first == again
    assert first["policy"] == sample_module.POLICY and first["pool_pages"] == [1, 2, 3, 4, 5, 6]
    assert first["limit"] == 3 and [item["page"] for item in first["pages"]] == [1, 2, 3]
    reasons = {item["page"]: item["reasons"] for item in first["pages"]}
    # The least surely read come first: too few words (3), then many unsure words (2); page 1 is the first scanned page.
    assert reasons[3] == ["read-least-surely"] and reasons[2] == ["read-least-surely"] and reasons[1] == ["first-scanned-page"]
    assert all(item["reasons"] for item in first["pages"])
    assert first["pages"][1]["reading"]["grade"] == "poor" and first["pages"][2]["reading"]["grade"] == "little-text"
    assert first["recognition_measured"] is True


@pytest.mark.parametrize("pool,expected", [(0, 0), (1, 1), (2, 2), (3, 3), (4, 3), (15, 3), (16, 4), (30, 6), (50, 10), (51, 10), (400, 10)])
def test_sample_size_follows_the_declared_rule(pool, expected):
    assert sample_module.quota(pool) == expected


def test_large_document_sample_is_ten_pages_with_first_last_and_worst(tmp_path):
    table = {page: (120, 118) for page in range(1, 61)}
    table[17], table[44] = (120, 30), (90, 40)
    bundle, _, _, report = make_report(tmp_path, pages=60, scanned=range(1, 61), table=table)
    chosen = sample_module.choose_sample(report, report["output"]["sha256"])
    pages = {item["page"]: item["reasons"] for item in chosen["pages"]}
    assert len(pages) == 10 == chosen["limit"]
    assert {1, 60, 17, 44} <= set(pages)
    assert "read-least-surely" in pages[17] and "read-least-surely" in pages[44]
    assert "first-scanned-page" in pages[1] and "last-scanned-page" in pages[60]
    assert "drawn-from-document-fingerprint" in {reason for reasons in pages.values() for reason in reasons}


def test_unmeasured_scans_are_still_sampled_and_the_draw_follows_the_result_fingerprint(tmp_path):
    bundle, _, _, report = make_report(tmp_path, pages=40, scanned=range(1, 41), table={})
    sha = report["output"]["sha256"]
    one = sample_module.choose_sample(report, sha)
    other = sample_module.choose_sample(report, "a" * 64)
    assert one["recognition_measured"] is False and len(one["pages"]) == 8
    assert {1, 40} <= {item["page"] for item in one["pages"]}
    assert [item["page"] for item in one["pages"]] != [item["page"] for item in other["pages"]]
    assert one["selection_sha256"] != other["selection_sha256"]
    assert one == sample_module.choose_sample(report, sha)


def test_scanned_pages_with_no_text_in_the_result_are_named_but_not_sampled(tmp_path):
    bundle, _, _, report = make_report(tmp_path, pages=8, scanned=range(1, 8), table={page: DEFAULT_TABLE[page] for page in range(1, 7)})
    report["inspection"]["pages"][6]["text_characters"] = 0      # page 7: no text layer and no recognition measurement
    chosen = sample_module.choose_sample(report, report["output"]["sha256"])
    assert chosen["no_text_pages"] == [7] and 7 not in chosen["pool_pages"]
    assert 7 not in {item["page"] for item in chosen["pages"]}
    only_blank = copy.deepcopy(report)
    only_blank["processors"] = []
    only_blank["classification"] = only_blank["baseline"]["pages"] = [{"page": 1, "class": "scanned", "text_characters": 0}]
    only_blank["inspection"]["pages"] = [{"page": 1, "text_characters": 0}]
    assert sample_module.choose_sample(only_blank, only_blank["output"]["sha256"]) is None


def test_digital_and_figure_only_documents_have_no_sample(tmp_path):
    _, _, _, digital = make_report(tmp_path, scanned=(), table={}, name="digital")
    assert sample_module.choose_sample(digital, digital["output"]["sha256"]) is None
    _, _, _, photos = make_report(tmp_path, scanned=(), mixed=(2, 3), table={}, name="photos")
    assert sample_module.choose_sample(photos, photos["output"]["sha256"]) is None
    assert sample_module.choose_sample(photos, None) is None
    assert sample_module.choose_sample({}, "b" * 64) is None


def test_documents_with_a_sample_show_it_in_the_review_packet_and_others_do_not(scan, tmp_path):
    scanned = review.render_review_packet(scan["report"], {"decisions": []}, tmp_path / "scanned.html").read_text(encoding="utf-8")
    assert "Scanned pages to compare with the scan" in scanned and "Page 3" in scanned and "cannot recreate the missing" in scanned
    _, _, _, digital = make_report(tmp_path, scanned=(), table={}, name="digital")
    plain = review.render_review_packet(digital, {"decisions": []}, tmp_path / "plain.html").read_text(encoding="utf-8")
    assert "Scanned pages to compare" not in plain


# --- a person's records ---------------------------------------------------------------------------------------------------

def test_a_record_needs_a_sampled_page_a_named_person_and_real_values(scan):
    view = ws.get_view(scan["state"])
    revision = view["revision"]
    for page, checks, notes, reviewer in [
            (5, ALL_PASS, "", REVIEWER),                                               # not in the sample
            (1, ALL_PASS, "", ""),                                                     # no name
            (1, ALL_PASS, "", "OCR"), (1, ALL_PASS, "", "automatic"), (1, ALL_PASS, "", "AI"),   # machine labels
            (1, {**ALL_PASS, "words_accurate": "maybe"}, "", REVIEWER),               # not a recognized value
            (1, {"words_accurate": "pass"}, "", REVIEWER),                             # a check missing
            (1, {**ALL_PASS, "extra": "pass"}, "", REVIEWER),
            (1, {**ALL_PASS, "nothing_missing": "problem"}, "", REVIEWER),            # a problem needs words
            (1, ALL_PASS, "x" * 2001, REVIEWER), (1, ALL_PASS, "bad\x00note", REVIEWER),
            ("1", ALL_PASS, "", REVIEWER), (True, ALL_PASS, "", REVIEWER)]:
        with pytest.raises(ws.WorkspaceError):
            ws.record_ocr_sample_page(scan["state"], page, checks, notes, reviewer, DATE, revision)
    with pytest.raises(ValueError, match="ISO review date"):
        ws.record_ocr_sample_page(scan["state"], 1, ALL_PASS, "", REVIEWER, "not a date", revision)
    assert ws.get_view(scan["state"])["revision"] == revision
    assert ws.load_workspace(scan["state"], refresh=False).get("ocr_sample_records", {}) == {}


def test_records_are_human_entered_bound_and_never_approve_the_scan_review(scan):
    view = _record(scan, 1, {**ALL_PASS, "reading_order_correct": "not-checked"}, "Columns still to check.")
    sample = view["ocr_review_sample"]
    record = sample["records"]["1"]
    assert record["origin"] == "human-entered" and record["reviewer"] == REVIEWER and record["reviewed_at"] == DATE
    assert record["record_sha256"] == sample_module.record_digest(record, scan["report"]["output"]["sha256"], sample["selection_sha256"])
    assert sample["standing"]["satisfied"] is False and sample["standing"]["unchecked_pages"] == [1]
    assert sample["standing"]["missing_pages"] == [2, 3]
    view = _record_all(scan)
    assert view["ocr_review_sample"]["standing"]["satisfied"] is True
    item = next(row for row in view["manual_items"] if row["id"] == "image-and-ocr")
    assert item["status"] == "pending" and "reviewer" not in item
    assert view["verification"] == "not-verified" and view["counts"]["manual_approved"] == 0
    assert view["history"][-1]["action"] == "record-ocr-sample-page"


def test_the_scan_review_cannot_be_approved_until_every_sampled_page_passes(scan):
    with pytest.raises(ws.WorkspaceError, match="Not yet recorded: pages 1, 2, 3"):
        _approve_scan_review(scan)
    _record(scan, 1)
    _record(scan, 2, {**ALL_PASS, "nothing_missing": "problem"}, "The last two lines of the table are cut off.")
    _record(scan, 3, {**ALL_PASS, "words_accurate": "not-checked"})
    with pytest.raises(ws.WorkspaceError) as refused:
        _approve_scan_review(scan)
    assert "marked as a problem: page 2" in str(refused.value) and "left as not-checked: page 3" in str(refused.value)
    _record(scan, 2)
    _record(scan, 3)
    # The other required review is not gated by the sample.
    view = ws.get_view(scan["state"])
    assert ws.review_item(scan["state"], "reading-order", "approved", REVIEWER, DATE, view["revision"])["counts"]["manual_approved"] == 1
    approved = _approve_scan_review(scan)
    assert next(row for row in approved["manual_items"] if row["id"] == "image-and-ocr")["status"] == "approved"
    # Blocking is always allowed: a confirmed defect never needs a complete sample.
    assert _approve_scan_review(scan, "blocked")["counts"]["manual_blocked"] == 1


def test_group_approval_cannot_bypass_the_sample(scan):
    view = ws.get_view(scan["state"])
    group = next(group for group in view["groups"] if "image-and-ocr" in group["member_ids"])
    with pytest.raises(ws.WorkspaceError, match="cannot be approved yet"):
        ws.approve_group(scan["state"], group["id"], ["image-and-ocr"], group["membership_digest"], REVIEWER, DATE, view["revision"])
    assert ws.get_view(scan["state"])["counts"]["manual_approved"] == 0


def test_a_later_problem_withdraws_an_approval_it_contradicts_but_keeps_the_observation(scan):
    _record_all(scan)
    assert next(row for row in _approve_scan_review(scan)["manual_items"] if row["id"] == "image-and-ocr")["status"] == "approved"
    changed = _record(scan, 2, {**ALL_PASS, "reading_order_correct": "problem"}, "Two columns are read straight across.")
    item = next(row for row in changed["manual_items"] if row["id"] == "image-and-ocr")
    assert item["status"] == "pending" and "reviewer" not in item and "reviewed_at" not in item
    assert changed["ocr_review_sample"]["standing"]["problem_pages"] == [2]
    assert changed["ocr_review_sample"]["records"]["2"]["notes"] == "Two columns are read straight across."


def test_a_changed_result_makes_records_history_not_authority(scan, tmp_path):
    _record(scan, 1, ALL_PASS, "Looks right at 200 percent.")
    _record(scan, 2, {**ALL_PASS, "words_accurate": "problem"}, "Digits read as letters in the table.")
    scan["output"].write_bytes(scan["output"].read_bytes() + b"\n% changed after review\n")
    stale = ws.get_view(scan["state"])
    assert stale["stale"] is True
    current = ws.load_workspace(scan["state"], refresh=False)
    assert current["ocr_sample_records"] == {}
    kept = {item["page"]: item["notes"] for item in current["ocr_sample_invalidated"]}
    assert kept == {1: "Looks right at 200 percent.", 2: "Digits read as letters in the table."}
    assert all(item["reason"] == "review-inputs-changed" for item in current["ocr_sample_invalidated"])
    assert current["history"][-1]["retained_ocr_sample_notes"][0]["notes"] == "Looks right at 200 percent."
    with pytest.raises(ws.WorkspaceError):
        ws.record_ocr_sample_page(scan["state"], 1, ALL_PASS, "", REVIEWER, DATE, stale["revision"])


def test_tampered_or_foreign_records_are_found_and_refused(scan):
    view = _record_all(scan)
    sample = ws._ocr_sample(ws.load_workspace(scan["state"], refresh=False))
    records = list(view["ocr_review_sample"]["records"].values())
    assert sample_module.record_problems(sample, records) == []
    forged = copy.deepcopy(records)
    forged[0]["checks"]["words_accurate"] = "problem"
    assert any("no longer matches" in text for text in sample_module.record_problems(sample, forged))
    machine = copy.deepcopy(records)
    machine[0]["origin"] = "machine"
    assert any("not a genuine human record" in text for text in sample_module.record_problems(sample, machine))
    other_artifact = copy.deepcopy(sample)
    other_artifact["artifact_sha256"] = "c" * 64
    assert sample_module.record_problems(other_artifact, records)
    assert sample_module.record_problems(sample, records + [copy.deepcopy(records[0])])
    assert not sample_module.status(sample, forged)["satisfied"]
    # A state edited outside the review operations is refused by the existing state fingerprint.
    document = json.loads(scan["state"].read_text(encoding="utf-8"))
    document["ocr_sample_records"]["1"]["checks"]["words_accurate"] = "problem"
    scan["state"].write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ws.WorkspaceError, match="changed outside"):
        ws.get_view(scan["state"])


# --- export and the human-verification ledger ------------------------------------------------------------------------------

def _approved_everything(scan):
    _record_all(scan)
    view = ws.get_view(scan["state"])
    for identifier in ("reading-order", "image-and-ocr"):
        view = ws.review_item(scan["state"], identifier, "approved", REVIEWER, DATE, view["revision"])
    return view


def test_export_carries_the_human_records_and_the_ledger_requires_them(scan, tmp_path):
    view = _approved_everything(scan)
    exported = ws.export_workspace(scan["state"], tmp_path / "exports", view["revision"])
    review_file = Path(exported["review_path"])
    payload = json.loads(review_file.read_text(encoding="utf-8"))
    assert payload["ocr_sample"]["policy"] == sample_module.POLICY
    assert [record["page"] for record in payload["ocr_sample_records"]] == [1, 2, 3]
    assert all(record["origin"] == "human-entered" for record in payload["ocr_sample_records"])
    reviewed = _review_data(scan["report"], review_file)
    assert len(_eligible(reviewed, file_sha256(scan["output"]))) == 2
    assert exported["ledger_eligible"] is True and exported["verification"] == "not-verified"
    # Approved lines alone, without the records, are refused even though every item says approved.
    bare = copy.deepcopy(payload)
    bare.pop("ocr_sample_records")
    bare_path = tmp_path / "bare-review.json"
    bare_path.write_text(json.dumps(bare), encoding="utf-8")
    with pytest.raises(ledger.LedgerError, match="no human records"):
        _eligible(_review_data(scan["report"], bare_path), file_sha256(scan["output"]))
    # A record left unchecked, or marked as a problem, is refused as well.
    for value in ("not-checked", "problem"):
        weak = copy.deepcopy(payload)
        weak["ocr_sample_records"][0]["checks"]["words_accurate"] = value
        weak_path = tmp_path / f"weak-{value}.json"
        weak_path.write_text(json.dumps(weak), encoding="utf-8")
        with pytest.raises(ledger.LedgerError, match="incomplete or adverse"):
            _eligible(_review_data(scan["report"], weak_path), file_sha256(scan["output"]))


def test_a_ledger_record_keeps_the_page_records_as_human_entered_evidence(scan, tmp_path):
    view = _approved_everything(scan)
    exported = ws.export_workspace(scan["state"], tmp_path / "exports", view["revision"])
    reviewed = _review_data(scan["report"], Path(exported["review_path"]))
    record = ledger.add_record(tmp_path / "ledger.jsonl", scan["output"], reviewed, REVIEWER, DATE, checker_score=100,
                               checker_context="Synthetic course", review_scope="Synthetic scope")
    assert record["human_ocr_sample"]["origin"] == "human-entered"
    assert [item["page"] for item in record["human_ocr_sample"]["records"]] == [1, 2, 3]
    assert ledger.list_records(tmp_path / "ledger.jsonl")[0]["current_status"] == "verified"


def test_documents_without_scans_keep_the_existing_ledger_rules(tmp_path):
    bundle, source, output, report = make_report(tmp_path, scanned=(), table={}, name="digital")
    state = tmp_path / "reviews" / "digital.json"
    ws.create_workspace(bundle, state)
    view = ws.get_view(state)
    assert view["ocr_review_sample"] is None
    for identifier in ("image-and-ocr", "reading-order"):
        view = ws.review_item(state, identifier, "approved", REVIEWER, DATE, view["revision"])
    exported = ws.export_workspace(state, tmp_path / "exports", view["revision"])
    assert "ocr_sample" not in json.loads(Path(exported["review_path"]).read_text(encoding="utf-8"))
    assert len(_eligible(_review_data(report, Path(exported["review_path"])), file_sha256(output))) == 2


# --- the local service -----------------------------------------------------------------------------------------------------

def test_the_service_route_records_a_page_and_refuses_a_machine_name(scan, tmp_path):
    import http.client
    import threading
    app = web.Application(tmp_path / "application", RuntimeConfig(project_root=scan["tmp"]))
    server = web.ReviewServer(app)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        identifier = app.import_bundle(str(scan["bundle"]))
        def post(payload):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
            try:
                connection.request("POST", f"/api/workspaces/{identifier}/ocr-sample", body=json.dumps(payload).encode(),
                                   headers={"Host": f"127.0.0.1:{server.server_port}", "X-Review-Token": app.token, "Content-Type": "application/json"})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        revision = app.view(identifier)["revision"]
        status, body = post({"revision": revision, "page": 1, "checks": ALL_PASS, "notes": "", "reviewer": "AI"})
        assert status >= 400 and "machine or automatic" in json.dumps(body)
        status, body = post({"revision": revision, "page": 1, "checks": ALL_PASS, "notes": "Compared at 200 percent.", "reviewer": REVIEWER})
        assert status == 200
        assert body["ocr_review_sample"]["records"]["1"]["reviewer"] == REVIEWER
        assert body["ocr_review_sample"]["records"]["1"]["reviewed_at"]
        assert body["verification"] == "not-verified"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()
