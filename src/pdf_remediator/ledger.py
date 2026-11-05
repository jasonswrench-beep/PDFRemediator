"""Append-only local verification evidence tied to an exact candidate hash.

An LMS checker score alone cannot create verification. The ledger is an audit record,
not a certificate or a replacement for the recorded human assessment scope.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path

from .sidecar import _validate_date, file_sha256

SCHEMA_VERSION = "phase1-ledger-1"


class LedgerError(ValueError):
    """Verification evidence is missing, inconsistent, or stale."""


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{name} is required")
    return value.strip()


def _score(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise LedgerError(f"{name} must be an actual numeric percentage from 0 to 100")
    return value


def _mapping(value, name):
    if not isinstance(value, dict):
        raise LedgerError(f"{name} is absent or malformed")
    return value


def _eligible(report, actual_sha):
    report = _mapping(report, "Run report")
    if report.get("status") != "candidate":
        raise LedgerError("Only a strict automated candidate can be verified")
    output = _mapping(report.get("output"), "Candidate output")
    if output.get("sha256") != actual_sha:
        raise LedgerError("Candidate PDF changed after the automated assessments")
    gate1 = _mapping(report.get("gate1"), "Strict validator assessment")
    counts = _mapping(gate1.get("counts"), "Validator counts")
    if gate1.get("status") != "pass" or gate1.get("profile") != "ua1" or gate1.get("is_compliant") is not True:
        raise LedgerError("Strict PDF/UA-1 validator did not pass")
    if counts.get("failedRules") != 0 or counts.get("failedChecks") != 0:
        raise LedgerError("Validator failures remain")
    if not isinstance(counts.get("passedRules"), int) or counts["passedRules"] <= 0:
        raise LedgerError("Validator rule coverage is absent")
    execution = _mapping(gate1.get("execution"), "Validator execution")
    if execution.get("status") != "completed" or execution.get("returncode") != 0:
        raise LedgerError("Validator execution was not successful")
    if gate1.get("input_sha256") != actual_sha:
        raise LedgerError("Validator evidence belongs to different PDF bytes")
    gate2 = _mapping(report.get("gate2"), "Supplemental assessment")
    if gate2.get("status") != "pass" or gate2.get("blockers"):
        raise LedgerError("Supplemental automated blockers remain")
    checks = gate2.get("checks")
    if not isinstance(checks, list) or not checks:
        raise LedgerError("Supplemental check coverage is absent")
    for check in checks:
        if not isinstance(check, dict):
            raise LedgerError("Malformed supplemental check")
        if (check.get("blocking") is True or check.get("required") is True) and check.get("status") not in {"pass", "not-applicable"}:
            raise LedgerError("A required supplemental check is unresolved")
    fidelity = _mapping(report.get("fidelity"), "Preservation assessment")
    if fidelity.get("status") != "pass" or fidelity.get("after_sha256") != actual_sha:
        raise LedgerError("Preservation has not passed for this exact PDF")
    if report.get("residual_issues"):
        raise LedgerError("Unresolved issues prevent human verification")
    manual = _mapping(report.get("manual_review"), "Human review")
    items = manual.get("items")
    if not isinstance(items, list) or not items:
        raise LedgerError("Human-review coverage is absent")
    ids = set()
    for item in items:
        if not isinstance(item, dict) or not item.get("id") or item["id"] in ids:
            raise LedgerError("Malformed or duplicate human-review item")
        ids.add(item["id"])
        if item.get("required", True):
            if item.get("status") != "approved":
                raise LedgerError(f"Required human review remains: {item['id']}")
            _text(item.get("reviewer"), "Human-review item reviewer")
            _validate_date(item.get("reviewed_at"))
    expected = {item["id"] for item in gate2.get("manual_queue", [])
                if isinstance(item, dict) and item.get("required", True) and item.get("id")}
    if not expected.issubset(ids):
        raise LedgerError("Human review omits required supplemental assessment items")
    return items


def _read(path):
    path = Path(path)
    if not path.exists():
        return []
    rows, previous = [], "0" * 64
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"Ledger line {number} is malformed") from exc
        if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
            raise LedgerError(f"Ledger line {number} has an unknown schema")
        expected = _digest({key: value for key, value in record.items() if key != "record_sha256"})
        if record.get("previous_record_sha256") != previous or record.get("record_sha256") != expected:
            raise LedgerError(f"Ledger integrity chain failed at line {number}")
        previous = record["record_sha256"]
        rows.append(record)
    return rows


@contextmanager
def _locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LedgerError("Ledger is already being updated; retry after the other update completes") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def _append(path, record):
    path = Path(path)
    with _locked(path):
        rows = _read(path)
        record["previous_record_sha256"] = rows[-1]["record_sha256"] if rows else "0" * 64
        record["record_sha256"] = _digest(record)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return record


# Records written before the generic names used these keys; they stay readable.
LEGACY_RECORD_KEYS = {"actual_ally_score": "actual_checker_score", "ally_context": "checker_context"}


def add_record(ledger_path, pdf_path, report, reviewer, reviewed_at, checker_score=None,
               checker_context=None, threshold=67, review_scope="", notes="", *,
               ally_score=None, ally_context=None):
    """Record actual human verification, refusing score-only or stale evidence.

    ``ally_score`` and ``ally_context`` are older keyword names kept as aliases.
    """
    if ally_score is not None:
        if checker_score is not None:
            raise TypeError("Give checker_score or its older alias ally_score, not both")
        checker_score = ally_score
    if ally_context is not None:
        if checker_context is not None:
            raise TypeError("Give checker_context or its older alias ally_context, not both")
        checker_context = ally_context
    reviewer = _text(reviewer, "Reviewer")
    _validate_date(reviewed_at)
    checker_context = _text(checker_context, "Institutional LMS checker context")
    review_scope = _text(review_scope, "Human/assistive-technology review scope")
    checker_score, threshold = _score(checker_score, "Actual LMS checker score"), _score(threshold, "Selected threshold")
    if checker_score < threshold:
        raise LedgerError("The actual LMS checker score is below the selected workflow threshold")
    if isinstance(report, (str, Path)):
        report = json.loads(Path(report).read_text(encoding="utf-8"))
    pdf = Path(pdf_path).resolve()
    actual_sha = file_sha256(pdf)
    human_items = _eligible(report, actual_sha)
    timestamp = datetime.now(timezone.utc).isoformat()
    record = {"schema_version": SCHEMA_VERSION, "kind": "verification", "recorded_at": timestamp,
              "pdf_path": str(pdf), "pdf_sha256": actual_sha, "run_id": report.get("run_id"),
              "report_sha256": _digest(report), "reviewer": reviewer, "reviewed_at": reviewed_at,
              "actual_checker_score": checker_score, "checker_context": checker_context, "selected_threshold": threshold,
              "human_review": human_items, "review_scope": review_scope, "notes": str(notes),
              "historical_status": "verified"}
    record["record_id"] = _digest(record)[:24]
    if file_sha256(pdf) != actual_sha:
        raise LedgerError("Candidate changed while verification was being recorded")
    return _append(ledger_path, record)


def invalidate_record(ledger_path, record_id, reason, reviewer, reviewed_at):
    """Append a discovered semantic blocker while retaining historical evidence."""
    reason, reviewer = _text(reason, "Invalidation reason"), _text(reviewer, "Reviewer")
    _validate_date(reviewed_at)
    rows = _read(ledger_path)
    if not any(row.get("kind") == "verification" and row.get("record_id") == record_id for row in rows):
        raise LedgerError("Verification record does not exist")
    record = {"schema_version": SCHEMA_VERSION, "kind": "invalidation", "target_record_id": record_id,
              "reason": reason, "reviewer": reviewer, "reviewed_at": reviewed_at,
              "recorded_at": datetime.now(timezone.utc).isoformat()}
    record["record_id"] = _digest(record)[:24]
    return _append(ledger_path, record)


def list_records(ledger_path, verify_files=True):
    """Derive current status afresh; changed/missing files never stay verified."""
    records = _read(ledger_path)
    invalidated = {row["target_record_id"] for row in records if row.get("kind") == "invalidation"}
    result = []
    for entry in records:
        row = dict(entry)
        for old, new in LEGACY_RECORD_KEYS.items():
            if old in row and new not in row:
                row[new] = row[old]
        if row.get("kind") != "verification":
            row["current_status"] = "invalidation"
        elif row["record_id"] in invalidated:
            row["current_status"] = "invalidated"
        elif not verify_files:
            row["current_status"] = "not-checked"
        else:
            try:
                row["observed_sha256"] = file_sha256(row["pdf_path"])
                row["current_status"] = "verified" if row["observed_sha256"] == row["pdf_sha256"] else "stale"
            except (OSError, ValueError):
                row["current_status"] = "unavailable"
        result.append(row)
    return result


def export_ledger(ledger_path, destination):
    path = Path(destination)
    if path.resolve() == Path(ledger_path).resolve():
        raise LedgerError("Ledger export must use a separate file")
    data = {"schema_version": SCHEMA_VERSION, "exported_at": datetime.now(timezone.utc).isoformat(),
            "records": list_records(ledger_path),
            "limitations": "Historical human verification is limited to its recorded scope; changed or unavailable PDFs are not currently verified."}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
