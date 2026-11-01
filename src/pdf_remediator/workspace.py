"""Mutable local review state outside an immutable, hash-bound run bundle.

Grouping changes navigation, never the inventory or semantic approval burden.
No operation in this module grants verified status or modifies a PDF/bundle.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .pipeline import verify_bundle
from .io_utils import atomic_replace
from .sidecar import (approval_digest, bind_approval, collect_decisions,
                      file_sha256, inventory_profile_for, load_sidecar, write_sidecar,
                      _STRUCTURAL_CONTEXT, _validate_date, _validate_value)

SCHEMA_VERSION = "phase2-review-workspace-1"
_MUTABLE_REVIEW = {"status", "reviewer", "reviewed_at", "notes"}
_LOCK_MAXIMUM_AGE_SECONDS = 3600
_INVENTORY_MATCHED = {}
_INVENTORY_MATCHED_LIMIT = 32
_INVENTORY_FILE_KEYS = 8
_ACTIVE = threading.local()
_CODE_FINGERPRINT = None
_DECISION_CONTEXT = ("id", "kind", "binding", "context_sha256", "current", "element", "page", "structure_path", "references")
_REGROUP_KINDS = {"list-label-regroup", "single-target-list-link-expansion", "single-target-list-link-expansion-preserving-tail"}
_AUTOMATIC_POLICY = "bounded-regrouping-quick-review-1"


class WorkspaceError(ValueError):
    pass


class RevisionConflict(WorkspaceError):
    pass


class StaleWorkspace(WorkspaceError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _credential_copy_context(state, report):
    """Describe one separately authorized source-copy action, never a repair."""
    baseline = report.get("baseline") or report.get("inspection") or {}
    assessment = baseline.get("content_credentials")
    if not isinstance(assessment, dict) or assessment.get("status") == "not-applicable":
        return None
    eligible = (state["bundle"]["status"] in {"failed", "needs-manual"} and state["bindings"].get("output") is None
                and assessment.get("policy") == "bounded-c2pa-associated-file-1"
                and assessment.get("supported") is True and assessment.get("status") == "supported"
                and isinstance(assessment.get("context_sha256"), str)
                and re.fullmatch(r"[a-f0-9]{64}", assessment["context_sha256"]) is not None)
    context = {"policy": "credential-copy-context-1", "workspace_id": state["workspace_id"],
               "source": copy.deepcopy(state["bindings"]["source"]),
               "report_sha256": state["bundle"]["report_sha256"],
               "assessment": copy.deepcopy(assessment), "eligible": eligible}
    context["context_sha256"] = _digest(context)
    return context


def credential_copy_consent(state_path, payload):
    """Validate explicit consent without changing the original saved review."""
    allowed = {"revision", "context_sha256", "source_sha256", "allow_remove", "reviewer", "reviewed_at"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise WorkspaceError("Use the separate content-credentials copy controls; automatic or extra authority is not accepted")
    with _locked(state_path) as path:
        state = _read_state(path)
        if _refresh(state):
            _save(path, state)
        if type(payload.get("revision")) is not int or payload["revision"] != state["revision"]:
            raise RevisionConflict("Workspace revision changed; reload before creating the separate copy")
        _actionable(state)
        if _unapplied(state) or _ocr_editor_summary(state).get("changed_count"):
            raise WorkspaceError("Save or restore outstanding document and OCR choices in their existing review before creating a separate source copy")
        context = state.get("credential_copy_context")
        if not context or context.get("eligible") is not True:
            raise WorkspaceError("This result has no supported content-credentials copy operation; other attachments remain protected")
        if payload.get("context_sha256") != context["context_sha256"] or payload.get("source_sha256") != state["bindings"]["source"]["sha256"]:
            raise RevisionConflict("The source or content-credentials context changed; reload before authorizing the copy")
        if payload.get("allow_remove") is not True:
            raise WorkspaceError("Explicitly select removing content credentials from the separate working copy")
        date = payload.get("reviewed_at", _now())
        try:
            name = _person(payload.get("reviewer"), date)
        except WorkspaceError:
            raise
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc
        try:
            timestamp = datetime.fromisoformat(date.replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("timezone required")
        except (AttributeError, TypeError, ValueError) as exc:
            raise WorkspaceError("A timezone-qualified consent date is required") from exc
        return {"policy": "remove-content-credentials-1", "source_sha256": context["source"]["sha256"],
                "reviewer": name, "reviewed_at": date, "allow_remove": True}


def _report_cancelled(report):
    """Cancellation is display metadata, never a different release status."""
    return (isinstance(report, dict) and report.get("status") == "failed" and report.get("cancelled") is True and
            "output" in report and report["output"] is None)


def _saved_cancelled(state):
    """Recognize old cancelled reviews without migrating saved human work.

    New states retain the explicit flag in their checked envelope. Only old
    failed/no-output states need a hash-bound report-only read; no PDF or
    manifest validation is performed by this display-only fallback.
    """
    bundle, bindings = state["bundle"], state["bindings"]
    def well_formed(binding):
        return (isinstance(binding, dict) and isinstance(binding.get("path"), str) and bool(binding["path"]) and
                isinstance(binding.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", binding["sha256"]) is not None)
    if (bundle["status"] != "failed" or state["stale"] or
            "output" not in bindings or bindings["output"] is not None or
            not well_formed(bindings.get("source")) or
            (bindings.get("prepared") is not None and not well_formed(bindings["prepared"])) or
            state["artifact_sha256"] is not None):
        return False
    if "cancelled" in bundle:
        return bundle["cancelled"] is True
    try:
        raw = (Path(bundle["path"]) / "report.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != bundle["report_sha256"]:
            return False
        report = json.loads(raw)
        if (not isinstance(report, dict) or not _report_cancelled(report) or
                not isinstance(bundle.get("run_fingerprint"), str) or not bundle["run_fingerprint"] or
                report.get("run_fingerprint") != bundle["run_fingerprint"]):
            return False
        return all(state["bindings"].get(key) == report.get(report_key)
                   for key, report_key in (("source", "input"), ("output", "output"),
                                           ("prepared", "decision_source")))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _outside(path, bundle, protected=()):
    path, bundle = Path(path).resolve(), Path(bundle).resolve()
    if path == bundle or bundle in path.parents or any(path == Path(item).resolve() for item in protected if item):
        raise WorkspaceError("Mutable review files must be outside the immutable bundle and separate from PDF inputs/checkpoints")
    return path


@contextmanager
def _locked(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        # A lock left by a process that is gone (crash, power loss, forced stop) would block this review for good.
        if not _lock_is_abandoned(lock):
            raise RevisionConflict("Workspace is being updated by another process; reload before retrying") from exc
        lock.unlink(missing_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as again:
            raise RevisionConflict("Workspace is being updated by another process; reload before retrying") from again
    if not hasattr(_ACTIVE, "paths"):
        _ACTIVE.paths = []
    try:
        os.write(descriptor, ("pid=%d\n" % os.getpid()).encode("ascii"))
        os.close(descriptor)
        _ACTIVE.paths.append(path)
        yield path
    finally:
        if _ACTIVE.paths and _ACTIVE.paths[-1] == path:
            _ACTIVE.paths.pop()
        lock.unlink(missing_ok=True)


def _code_fingerprint():
    """What decides how a PDF is analysed: this package's own source and the PDF libraries' versions."""
    global _CODE_FINGERPRINT
    if _CODE_FINGERPRINT is None:
        from importlib.metadata import version
        package = Path(__file__).parent
        payload = {str(file.relative_to(package)): file_sha256(file) for file in sorted(package.rglob("*.py"))}
        for name in ("pikepdf", "pypdfium2", "fontTools", "Pillow"):
            try:
                payload[name] = version(name)
            except Exception:
                payload[name] = "unknown"
        _CODE_FINGERPRINT = _digest(payload)
    return _CODE_FINGERPRINT


def _inventory_cache_file():
    paths = getattr(_ACTIVE, "paths", None)
    return paths[-1].with_name(paths[-1].name + ".inventory-ok") if paths else None


def _stored_inventory_matches():
    """Matches saved by an earlier run of exactly this code; anything unreadable counts as no match."""
    file = _inventory_cache_file()
    if file is None:
        return set()
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if data.get("code") == _code_fingerprint() and isinstance(data.get("matches"), list):
            return {item for item in data["matches"] if isinstance(item, str)}
    except (OSError, ValueError, AttributeError):
        pass
    return set()


def _inventory_already_matched(token):
    if token in _INVENTORY_MATCHED:
        return True
    if token in _stored_inventory_matches():
        _INVENTORY_MATCHED[token] = True
        return True
    return False


def _remember_inventory_match(token):
    _INVENTORY_MATCHED[token] = True
    while len(_INVENTORY_MATCHED) > _INVENTORY_MATCHED_LIMIT:
        _INVENTORY_MATCHED.pop(next(iter(_INVENTORY_MATCHED)))
    file = _inventory_cache_file()
    if file is None:
        return
    try:
        matches = sorted(_stored_inventory_matches() | {token})[-_INVENTORY_FILE_KEYS:]
        temporary = file.with_name(file.name + ".tmp-" + uuid.uuid4().hex)
        temporary.write_text(json.dumps({"code": _code_fingerprint(), "matches": matches}), encoding="utf-8")
        atomic_replace(temporary, file)
    except OSError:
        pass


def _lock_is_abandoned(lock):
    """True only when the lock's owner is provably gone, or the lock is far older than any single review operation."""
    try:
        age = time.time() - lock.stat().st_mtime
        text = lock.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return False
    if age > _LOCK_MAXIMUM_AGE_SECONDS:
        return True
    match = re.fullmatch(r"pid=(\d+)", text)
    if match is None:
        return False
    try:
        import psutil
        return not psutil.pid_exists(int(match.group(1)))
    except Exception:
        return False


def _save(path, state):
    state["state_sha256"] = _digest({key: value for key, value in state.items() if key != "state_sha256"})
    write_sidecar(state, path)


def _read_state(path):
    state = _read_json(path)
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise WorkspaceError("Unknown workspace schema")
    if state.get("state_sha256") != _digest({key: value for key, value in state.items() if key != "state_sha256"}):
        raise WorkspaceError("Workspace state changed outside its atomic review operations")
    _outside(path, state["bundle"]["path"], [binding["path"] for binding in state["bindings"].values() if binding])
    return state


def _scope(item):
    return {key: value for key, value in item.items() if key not in _MUTABLE_REVIEW}


def _contexts(sidecar):
    return {item["id"]: {**{key: item.get(key) for key in _DECISION_CONTEXT},
                         **{key: item[key] for key in _STRUCTURAL_CONTEXT if key in item}}
            for item in sidecar.get("decisions", [])}


def _applied_values(sidecar):
    return {item["id"]: (item.get("value") if (item.get("status") == "approved" and
                         item.get("approval_sha256") == approval_digest(item)) or _valid_automatic_decision(item)
                         else item.get("current"))
            for item in sidecar.get("decisions", [])}


def _valid_automatic_decision(item):
    if item.get("status") != "auto-accepted":
        return False
    from .sidecar import automatic_acceptance_valid
    return automatic_acceptance_valid(item)


def _person(reviewer, reviewed_at):
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise WorkspaceError("An explicit named reviewer is required")
    _validate_date(reviewed_at)
    return reviewer.strip()


def _record_event(state, action, **details):
    state["revision"] += 1
    state["updated_at"] = _now()
    state["history"].append({"revision": state["revision"], "at": state["updated_at"], "action": action, **details})


def _clear_approval(item, manual=False):
    old = item.get("status")
    item["status"] = "pending"
    # Notes are observations, not approval authority. Silent invalidation must
    # retain them even when the reviewer/date no longer authorize this artifact.
    keys = {"reviewer", "reviewed_at"} if manual else {"approved_by", "approved_at", "approval_sha256"}
    for key in keys:
        item.pop(key, None)
    if not manual:
        item.pop("automatic_application", None)
        item.pop("automatic_acceptance_sha256", None)
    return old == "approved"


def _invalidate(state, reasons):
    if state.get("stale") and state.get("stale_reasons") == reasons:
        return False
    invalidated, automatic_decisions = [], []
    retained_notes = []
    for item in state["manual_items"]:
        prior_status, prior_notes = item.get("status"), item.get("notes")
        if _clear_approval(item, manual=True):
            invalidated.append(item["id"])
        if prior_status == "blocked":
            item["status"] = "blocked"
        if "notes" in item:
            retained_notes.append({"id": item["id"], "notes": copy.deepcopy(prior_notes), "previous_status": prior_status})
    for item in state["sidecar"].get("decisions", []):
        if item.get("status") == "auto-accepted":
            automatic_decisions.append(item["id"])
        if _clear_approval(item):
            invalidated.append(item["id"])
    state["manual_approvals"] = {}
    for item in _ocr_saved_items(state).values():
        _clear_ocr_acceptance(item)
    state["stale"], state["stale_reasons"] = True, reasons
    _record_event(state, "invalidate-stale-inputs", reasons=reasons, invalidated_ids=invalidated,
                  invalidated_automatic_decision_ids=automatic_decisions,
                  invalidated_automatic_ids=[item["item_id"] for item in state.get("automatic_review_records", [])],
                  retained_manual_notes=retained_notes)
    return True


def _binding_problems(state):
    reasons, bundle = [], Path(state["bundle"]["path"])
    try:
        if file_sha256(bundle / "manifest.json") != state["bundle"]["manifest_sha256"]:
            reasons.append("Immutable bundle manifest changed")
        if not verify_bundle(bundle):
            reasons.append("Immutable bundle or published PDF is missing, changed, or incomplete")
        report = _read_json(bundle / "report.json")
        if file_sha256(bundle / "report.json") != state["bundle"]["report_sha256"]:
            reasons.append("Immutable run report changed")
        if state["bundle"]["status"] != report["status"]:
            reasons.append("Workspace run status differs from immutable report")
        if state.get("source_lineage") != report.get("source_lineage"):
            reasons.append("Corrected-source lineage differs from immutable report")
        if state.get("credential_lineage") != report.get("credential_lineage"):
            reasons.append("Content-credentials source lineage differs from immutable report")
        if state.get("credential_derivative") != report.get("credential_derivative"):
            reasons.append("Content-credentials copy description differs from immutable report")
        if state.get("credential_copy_context") != _credential_copy_context(state, report):
            reasons.append("Content-credentials copy context differs from immutable report")
        if "cancelled" in state["bundle"] and (type(state["bundle"]["cancelled"]) is not bool or
                state["bundle"]["cancelled"] != _report_cancelled(report)):
            reasons.append("Workspace cancellation metadata differs from immutable report")
        if {item["id"]: _scope(item) for item in report["manual_review"]["items"]} != state["manual_contexts"]:
            reasons.append("Human-review scope or occurrence context changed")
        if {item["id"]: _scope(item) for item in state["manual_items"]} != state["manual_contexts"]:
            reasons.append("Workspace human-review occurrence scope changed")
        for key, report_key in (("source", "input"), ("output", "output"), ("prepared", "decision_source")):
            if state["bindings"].get(key) != report.get(report_key):
                reasons.append("Workspace artifact bindings differ from immutable report")
        original = load_sidecar(bundle / "decisions.json")
        if inventory_profile_for(state["sidecar"]) != inventory_profile_for(original):
            reasons.append("Decision inventory profile changed")
        if _contexts(original) != state["decision_contexts"]:
            reasons.append("Decision inventory or context changed")
        if _contexts(state["sidecar"]) != state["decision_contexts"]:
            reasons.append("Workspace decision context changed")
        if _applied_values(original) != state["original_decision_values"]:
            reasons.append("Original decision values changed")
    except (OSError, ValueError, KeyError, TypeError):
        reasons.append("Immutable bundle evidence cannot be read")
    for name, binding in state["bindings"].items():
        if not binding:
            continue
        try:
            if file_sha256(binding["path"]) != binding["sha256"]:
                reasons.append(f"{name} PDF fingerprint changed")
        except OSError:
            reasons.append(f"{name} PDF is unavailable")
    if state.get("source_lineage"):
        try:
            from .ocr_corrections import validate_lineage_bindings
            lineage = state["source_lineage"]
            proof = validate_lineage_bindings(lineage["path"], state["bindings"]["source"]["path"], lineage["sha256"])
            if proof.get("bindings_verified") is not True:
                reasons.append("Corrected-source lineage dependencies could not be verified")
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            reasons.append("Corrected-source lineage or an earlier original, review, plan or proof is missing or changed")
    if state.get("credential_lineage"):
        try:
            from .credentials import validate_lineage_bindings
            lineage = state["credential_lineage"]
            proof = validate_lineage_bindings(lineage["path"], state["bindings"]["source"]["path"], lineage["sha256"])
            if proof.get("binding_verified") is not True or proof.get("summary") != state.get("credential_derivative"):
                reasons.append("Content-credentials lineage or copy description could not be verified")
        except (OSError, ValueError, KeyError, TypeError, ImportError):
            reasons.append("Content-credentials lineage or its original, consent, payload or proof is missing or changed")
    prepared = state["bindings"].get("prepared")
    if prepared:
        # Re-reading every decision from a long PDF takes many seconds and its answer is fixed by the prepared file's exact bytes,
        # the original's hash, the inventory profile, the saved contexts and the code that is running. A match is remembered for
        # this process and, beside the review file, for later runs of exactly this code; the file fingerprints above are still checked on every load, so a changed file is never skipped.
        token = _digest([prepared["sha256"], state["bindings"]["source"]["sha256"], inventory_profile_for(state["sidecar"]), _digest(state["decision_contexts"])])
        if not _inventory_already_matched(token):
            try:
                fresh = collect_decisions(prepared["path"], state["bindings"]["source"]["sha256"],
                                          inventory_profile=inventory_profile_for(state["sidecar"]))
                if fresh.get("inventory_errors") or _contexts(fresh) != state["decision_contexts"]:
                    reasons.append("Prepared PDF decision occurrence context changed")
                else:
                    _remember_inventory_match(token)
            except (OSError, ValueError, RuntimeError):
                reasons.append("Prepared PDF decision context cannot be checked")
    for item in state["sidecar"].get("decisions", []):
        if item.get("status") == "approved" and item.get("approval_sha256") != approval_digest(item):
            reasons.append("Decision approval no longer matches its value/context")
        if item.get("status") == "auto-accepted" and not _valid_automatic_decision(item):
            reasons.append("Automatic decision acceptance no longer matches its value/context/authorization")
    for item in state["manual_items"]:
        if item.get("status") == "approved" and state["manual_approvals"].get(item["id"]) != _digest({"item": item, "artifact_sha256": state["artifact_sha256"]}):
            reasons.append("Human approval no longer matches its scope or artifact")
    for record in state.get("automatic_review_records", []):
        if (not isinstance(record, dict) or record.get("record_sha256") !=
                _digest({key: value for key, value in record.items() if key != "record_sha256"}) or
                record.get("scope_sha256") != _digest(state["manual_contexts"].get(record.get("item_id"))) or
                record.get("binding_sha256") != _automatic_binding(state)):
            reasons.append("Automatic review disposition no longer matches its occurrence or artifact")
    reasons.extend(_ocr_stored_problems(state))
    return sorted(set(reasons))


def _refresh(state):
    problems = _binding_problems(state)
    # Once inputs change, restoring old bytes does not silently restore approval.
    return _invalidate(state, problems) if problems else False


def create_workspace(bundle_path, state_path):
    bundle = Path(bundle_path).resolve()
    if not verify_bundle(bundle):
        raise WorkspaceError("Cannot import an incomplete or changed immutable bundle")
    report = _read_json(bundle / "report.json")
    source, output, prepared = report.get("input"), report.get("output"), report.get("decision_source")
    protected = [item.get("path") for item in (source, output, prepared) if item]
    state_path = _outside(state_path, bundle, protected)
    with _locked(state_path):
        if state_path.exists():
            raise WorkspaceError("An existing workspace cannot be overwritten; load it or choose another path")
        sidecar = load_sidecar(bundle / "decisions.json")
        if sidecar and prepared and (sidecar.get("source_sha256") != source.get("sha256") or sidecar.get("document_sha256") != prepared.get("sha256")):
            raise WorkspaceError("Decision sidecar is not bound to the original and prepared PDFs")
        manual = copy.deepcopy(report.get("manual_review", {}).get("items", []))
        if len({item["id"] for item in manual}) != len(manual):
            raise WorkspaceError("Duplicate human-review occurrence IDs")
        if len({item["id"] for item in sidecar.get("decisions", [])}) != len(sidecar.get("decisions", [])):
            raise WorkspaceError("Duplicate decision occurrence IDs")
        timestamp = _now()
        state = {"schema_version": SCHEMA_VERSION, "workspace_id": uuid.uuid4().hex, "revision": 0,
                 "created_at": timestamp, "updated_at": timestamp,
                 "bundle": {"path": str(bundle), "manifest_sha256": file_sha256(bundle / "manifest.json"),
                            "report_sha256": file_sha256(bundle / "report.json"), "status": report["status"],
                            "cancelled": _report_cancelled(report),
                            "run_fingerprint": report.get("run_fingerprint")},
                 "bindings": {"source": copy.deepcopy(source), "output": copy.deepcopy(output), "prepared": copy.deepcopy(prepared)},
                 "artifact_sha256": output.get("sha256") if output else None,
                 "page_count": report.get("inspection", report.get("baseline", {})).get("page_count", len(report.get("classification", []))),
                 "manual_items": manual, "manual_contexts": {item["id"]: _scope(item) for item in manual},
                 "manual_approvals": {}, "sidecar": copy.deepcopy(sidecar),
                 "manual_touched": [], "automatic_review_records": [],
                 "automatic_review_invalidations": [],
                 "original_decision_values": _applied_values(sidecar),
                 "decision_contexts": _contexts(sidecar),
                 "human_touched": [item["id"] for item in sidecar.get("decisions", [])
                                   if item.get("status") == "approved" or
                                   (item.get("status") != "auto-accepted" and item.get("value") != item.get("current") and not item.get("ai_draft"))],
                 "suggestions": [],
                 "residual_issues": copy.deepcopy(report.get("residual_issues", [])),
                 "stale": False, "stale_reasons": [], "history": []}
        if report.get("source_lineage") is not None:
            state["source_lineage"] = copy.deepcopy(report["source_lineage"])
        if report.get("credential_lineage") is not None:
            state["credential_lineage"] = copy.deepcopy(report["credential_lineage"])
            state["credential_derivative"] = copy.deepcopy(report.get("credential_derivative"))
        credential_context = _credential_copy_context(state, report)
        if credential_context is not None:
            state["credential_copy_context"] = credential_context
        for item in manual:
            if item.get("status") == "approved":
                _person(item.get("reviewer"), item.get("reviewed_at"))
                state["manual_approvals"][item["id"]] = _digest({"item": item, "artifact_sha256": state["artifact_sha256"]})
        problems = _binding_problems(state)
        if problems:
            raise StaleWorkspace("Cannot import stale evidence: " + "; ".join(problems))
        _save(state_path, state)
    return state


def load_workspace(state_path, refresh=True):
    with _locked(state_path) as path:
        state = _read_state(path)
        if refresh and _refresh(state):
            _save(path, state)
        return state


def _detail(item):
    try:
        value = json.loads(item.get("detail", ""))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _pages(item):
    result = {page for page in item.get("pages", []) if type(page) is int and page > 0}
    if type(item.get("page")) is int and item["page"] > 0:
        result.add(item["page"])
    match = re.fullmatch(r"page:(\d+)", str(_detail(item).get("stream", "")))
    if match:
        result.add(int(match[1]))
    return sorted(result)


def _pattern(item, decision=False):
    if decision:
        # Even byte-identical images retain separate occurrence/context groups.
        return {"category": item["kind"], "occurrence": item["id"]}
    detail = _detail(item)
    if item.get("category") == "tag-regrouping" and detail.get("kind") in _REGROUP_KINDS:
        stream = str(detail.get("stream", ""))
        tail = detail.get("retained_body_tail_mcids", [])
        if (not isinstance(tail, list) or any(type(mcid) is not int or mcid < 0 for mcid in tail)
            or len(set(tail)) != len(tail) or (detail["kind"].endswith("-preserving-tail") and not tail)):
            return {"category": "tag-regrouping", "scope_sha256": _digest(_scope(item)), "exception": "unrecognized-tail-metadata"}
        return {"category": "tag-regrouping", "repair_kind": detail["kind"],
                "stream_kind": "page" if re.fullmatch(r"page:\d+", stream) else "form-or-unknown",
                "removed_mcid_count": len(detail.get("removed_mcids", [])) if isinstance(detail.get("removed_mcids", []), list) else "unknown",
                "retained_tail_mcid_count": len(tail),
                "exception": bool(detail.get("warnings") or detail.get("exception"))}
    return {"category": item.get("category", "manual"), "scope_sha256": _digest(_scope(item))}


def _automatic_binding(state):
    return _digest({"workspace_id": state["workspace_id"], "bundle": state["bundle"],
                    "bindings": state["bindings"], "artifact_sha256": state["artifact_sha256"]})


def _automatic_snapshot(state):
    """Prove already-applied mechanical repairs, without assessing their meaning."""
    try:
        report = _read_json(Path(state["bundle"]["path"]) / "report.json")
    except (OSError, ValueError):
        report = {}
    gate1, gate2, fidelity = (report.get(key) if isinstance(report.get(key), dict) else {}
                            for key in ("gate1", "gate2", "fidelity"))
    processors = [item for item in report.get("processors", []) or []
                  if isinstance(item, dict) and item.get("name") == "preserve-painting"]
    preservation = processors[0] if len(processors) == 1 else {}
    proof_sha = _digest({"gate1": gate1, "gate2": gate2, "fidelity": fidelity, "preservation": preservation})
    reason = None
    counts = gate1.get("counts") if isinstance(gate1.get("counts"), dict) else {}
    execution = gate1.get("execution") if isinstance(gate1.get("execution"), dict) else {}
    required_checks = {"content-linkage", "content-coverage", "link-structure", "unsupported-features"}
    checks = gate2.get("checks") if isinstance(gate2.get("checks"), list) else []
    checked = {item.get("id") for item in checks if isinstance(item, dict) and item.get("status") == "pass"}
    comparison = fidelity.get("reference_comparison", fidelity)
    comparison = comparison if isinstance(comparison, dict) else {}
    pages = comparison.get("pages", [])
    if state["stale"]:
        reason = "stale-workspace"
    elif state["bundle"]["status"] != "candidate" or not state["artifact_sha256"] or type(state["page_count"]) is not int or state["page_count"] <= 0:
        reason = "no-strict-candidate"
    elif _unapplied(state):
        reason = "decision-edits-require-reprocessing"
    elif state["residual_issues"]:
        reason = "unresolved-run-issues"
    elif (gate1.get("status") != "pass" or gate1.get("profile") != "ua1" or gate1.get("is_compliant") is not True or
          gate1.get("input_sha256") != state["artifact_sha256"] or
          any(type(counts.get(key)) is not int or counts[key] != 0 for key in ("failedRules", "failedChecks")) or
          type(counts.get("passedRules")) is not int or counts["passedRules"] <= 0 or
          type(counts.get("passedChecks")) is not int or counts["passedChecks"] <= 0 or
          execution.get("status") != "completed" or type(execution.get("returncode")) is not int or execution["returncode"] != 0 or
          not isinstance(gate1.get("assertion_detail_coverage"), dict) or gate1["assertion_detail_coverage"].get("status") != "complete"):
        reason = "strict-validator-proof-incomplete"
    elif (gate2.get("status") != "pass" or gate2.get("blockers") or not required_checks.issubset(checked) or
          any(not isinstance(item, dict) or ((item.get("blocking") is True or item.get("required") is True) and
              item.get("status") not in {"pass", "not-applicable"}) for item in checks)):
        reason = "supplemental-proof-incomplete"
    elif (fidelity.get("status") != "pass" or fidelity.get("after_sha256") != state["artifact_sha256"] or
          fidelity.get("before_sha256") != state["bindings"]["source"]["sha256"] or comparison.get("status") != "pass" or
          comparison.get("after_sha256") != state["artifact_sha256"] or not isinstance(pages, list) or
          len(pages) != state["page_count"] or {item.get("page") for item in pages if isinstance(item, dict)} != set(range(1, state["page_count"] + 1)) or
          any(not isinstance(item, dict) or item.get("status") != "pass" for item in pages) or
          (comparison is not fidelity and comparison.get("before_sha256") != fidelity.get("reference_sha256"))):
        reason = "all-page-fidelity-proof-incomplete"
    elif (preservation.get("status") != "pass" or preservation.get("supported") is not True or
          preservation.get("allow_tag_regrouping") is not True or
          preservation.get("independent_validation_required") is not True or
          preservation.get("all_page_fidelity_required") is not True or
          not isinstance(preservation.get("changes"), dict) or
          type(preservation["changes"].get("pages_source_checked")) is not int or
          preservation["changes"]["pages_source_checked"] != state["page_count"]):
        reason = "mechanical-preservation-proof-incomplete"
    details = preservation.get("semantic_review_required", [])
    processor_scopes = Counter(_digest(item) for item in details if isinstance(item, dict)) if isinstance(details, list) else Counter()
    manual_scopes = Counter(_digest(_detail(item)) for item in state["manual_items"] if item.get("category") == "tag-regrouping")
    if not reason and processor_scopes != manual_scopes:
        reason = "mechanical-occurrence-inventory-incomplete"
    eligible, excluded = [], []
    touched = set(state.get("manual_touched", []))
    for item in state["manual_items"]:
        detail, issue = _detail(item), reason
        removed, tail, retained = detail.get("removed_mcids"), detail.get("retained_body_tail_mcids", []), detail.get("retained_mcid")
        stream = re.fullmatch(r"page:([1-9]\d*)", str(detail.get("stream", "")))
        if item.get("category") != "tag-regrouping" or not isinstance(detail.get("kind"), str) or detail["kind"] not in _REGROUP_KINDS:
            issue = "human-semantic-review"
        elif item.get("status") != "pending" or item["id"] in touched or item.get("reviewer") or item.get("notes"):
            issue = "human-choice-protected"
        elif (not stream or int(stream[1]) > state["page_count"] or _pages(item) != [int(stream[1])] or
              type(retained) is not int or retained < 0 or
              not isinstance(removed, list) or not removed or any(type(value) is not int or value < 0 for value in removed) or
              len(set(removed)) != len(removed) or not isinstance(tail, list) or
              any(type(value) is not int or value < 0 for value in tail) or len(set(tail)) != len(tail) or
              retained in removed or retained in tail or set(removed).intersection(tail) or
              bool(tail) != detail["kind"].endswith("-preserving-tail") or detail.get("warnings") or detail.get("exception") or
              not re.fullmatch(r"[0-9a-f]{64}", str(detail.get("source_text_bytes_sha256", "")))):
            issue = "unrecognized-mechanical-context"
        elif processor_scopes[_digest(detail)] != manual_scopes[_digest(detail)]:
            issue = "occurrence-not-proved-by-preservation-processor"
        if issue:
            excluded.append({"id": item["id"], "reason": issue})
        else:
            eligible.append(item["id"])
    return {"proof_sha256": proof_sha, "binding_sha256": _automatic_binding(state),
            "eligible_ids": sorted(eligible), "ineligible": excluded, "unavailable_reason": reason}


def _active_automatic_records(state, snapshot=None):
    if state["stale"] or _unapplied(state):
        return {}
    records = state.get("automatic_review_records", [])
    if not records:
        return {}
    snapshot = snapshot or _automatic_snapshot(state)
    invalidated = {item["record_sha256"] for item in state.get("automatic_review_invalidations", [])}
    eligible = set(snapshot["eligible_ids"])
    return {record["item_id"]: record for record in records
            if record.get("record_sha256") not in invalidated and record.get("policy_version") == _AUTOMATIC_POLICY and
            record.get("author") == "automation" and record.get("proof_sha256") == snapshot["proof_sha256"] and
            record.get("binding_sha256") == snapshot["binding_sha256"] and record["item_id"] in eligible}


def _automatic_plan(state):
    snapshot = _automatic_snapshot(state)
    active = _active_automatic_records(state, snapshot)
    plan = {"schema_version": "phase2-automatic-review-plan-1", "policy_version": _AUTOMATIC_POLICY,
            "workspace_id": state["workspace_id"], "revision": state["revision"], **snapshot,
            "already_handled_ids": sorted(active)}
    plan["eligible_ids"] = [identifier for identifier in snapshot["eligible_ids"] if identifier not in active]
    plan["plan_sha256"] = _digest(plan)
    return plan


def plan_automatic_review(state_path):
    """Plan optional quick-review triage; this read does not approve or repair."""
    return _automatic_plan(load_workspace(state_path))


def get_automatic_review_summary(state_path):
    plan = plan_automatic_review(state_path)
    return {**plan, "eligible_count": len(plan["eligible_ids"]), "automated_count": len(plan["already_handled_ids"]),
            "human_approved": False, "verification": "not-verified"}


def commit_automatic_review(state_path, plan, expected_revision):
    def operation(state):
        _actionable(state, require_artifact=True, review_approval=True)
        actual = _automatic_plan(state)
        if not isinstance(plan, dict) or plan != actual:
            raise RevisionConflict("Automatic review plan or its exact occurrence/proof bindings changed; replan")
        records = state.setdefault("automatic_review_records", [])
        for identifier in actual["eligible_ids"]:
            item = _find(state["manual_items"], identifier)
            record = {"item_id": identifier, "author": "automation", "recorded_at": _now(),
                      "policy_version": _AUTOMATIC_POLICY, "disposition": "already-applied-mechanical-repair",
                      "human_approved": False, "scope_sha256": _digest(_scope(item)),
                      "proof_sha256": actual["proof_sha256"], "binding_sha256": actual["binding_sha256"],
                      "plan_sha256": actual["plan_sha256"]}
            record["record_sha256"] = _digest(record)
            records.append(record)
        _record_event(state, "automatic-mechanical-review-triage", author="automation",
                      item_ids=actual["eligible_ids"], policy_version=_AUTOMATIC_POLICY,
                      plan_sha256=actual["plan_sha256"], human_approved=False)
    return _change(state_path, expected_revision, operation)


def _groups(state):
    grouped = {}
    for decision, items in ((False, state["manual_items"]), (True, state["sidecar"].get("decisions", []))):
        for item in items:
            pattern = _pattern(item, decision)
            identifier = ("decision-" if decision else "review-") + _digest(pattern)[:24]
            group = grouped.setdefault(identifier, {"id": identifier, "label": pattern.get("repair_kind", pattern["category"]),
                        "category": pattern["category"], "pattern": pattern, "member_ids": [],
                        "kind": "decision" if decision else "manual", "group_approvable": not decision,
                        "requires_context_review": True, "counts": {"total": 0, "pending": 0, "approved": 0, "blocked": 0, "auto-accepted": 0},
                        "pages": [], "_contexts": []})
            group["member_ids"].append(item["id"])
            group["counts"]["total"] += 1
            group["counts"][item.get("status", "pending")] += 1
            group["pages"] = sorted(set(group["pages"]) | set(_pages(item)))
            context = item.get("context_sha256") if decision else _digest(_scope(item))
            group["_contexts"].append({"id": item["id"], "context_sha256": context})
    for group in grouped.values():
        group["member_ids"].sort()
        group["membership_digest"] = _digest({"group_id": group["id"], "artifact_sha256": state["artifact_sha256"],
                                             "members": sorted(group.pop("_contexts"), key=lambda item: item["id"])})
    return list(grouped.values())


def _unapplied(state):
    return ([item["id"] for item in state["sidecar"].get("decisions", [])
             if item.get("value") != state["original_decision_values"].get(item["id"])] +
            [item["id"] for item in _ocr_saved_items(state).values()
             if item.get("value") != item.get("original")])


_OCR_EDITS_SCHEMA = "phase2-ocr-text-corrections-1"
_OCR_EXPANDED_SCHEMA = "phase2-ocr-text-corrections-2"
_OCR_LIMITS = ("Only proven invisible OCR text can be corrected. Extended editing can add a missing word with explicit placement and order. "
               "Characters are checked against the bundled font; unsupported characters and ambiguous text are refused. "
               "Saving does not change the PDF. Create a corrected copy and recheck it; previous reviews remain separate.")


def _ocr_saved_items(state):
    editor = state.get("ocr_text_edits")
    return ({key: item for key, item in editor["items"].items() if isinstance(item, dict)}
            if isinstance(editor, dict) and isinstance(editor.get("items"), dict) else {})


def _clear_ocr_acceptance(item):
    item["status"] = "pending"
    for key in ("reviewer", "reviewed_at", "acceptance_sha256"):
        item.pop(key, None)


def _ocr_acceptance_payload(editor, item):
    if editor.get("schema_version") == _OCR_EXPANDED_SCHEMA:
        return _ocr_operation_fields(item, acceptance=False) | {
            key: editor[key] for key in ("source_sha256", "document_sha256", "inventory_sha256", "expansion_sha256")}
    return {key: item[key] for key in ("id", "context_sha256", "original", "value", "reviewer", "reviewed_at")} | {
        key: editor[key] for key in ("source_sha256", "document_sha256", "inventory_sha256")}


def _ocr_operation_fields(item, acceptance=True):
    keys = ["kind", "id", "context_sha256", "original", "value", "reviewer", "reviewed_at"]
    if item.get("kind") == "insert":
        keys += ["anchor_id", "page", "placement"]
    if acceptance:
        keys.append("acceptance_sha256")
    return {key: copy.deepcopy(item[key]) for key in keys}


def _ocr_profile(state, requested="legacy"):
    if requested not in ("legacy", "expanded-v2"):
        raise WorkspaceError("Choose a supported OCR editing mode")
    editor = state.get("ocr_text_edits") or {}
    if editor.get("items"):
        return "expanded-v2" if editor.get("schema_version") == _OCR_EXPANDED_SCHEMA else "legacy"
    return requested


def _ocr_schema(inventory):
    return (_OCR_EXPANDED_SCHEMA if inventory.get("schema_version") == "phase2-ocr-text-inventory-2"
            else _OCR_EDITS_SCHEMA)


def _ocr_editor_for_save(state, inventory):
    schema = _ocr_schema(inventory)
    editor = state.get("ocr_text_edits")
    if not editor or not editor.get("items"):
        editor = {"schema_version": schema,
            **{key: inventory[key] for key in ("source_sha256", "document_sha256", "inventory_sha256")}, "items": {}}
        if schema == _OCR_EXPANDED_SCHEMA:
            editor["expansion_sha256"] = inventory["expansion_sha256"]
        state["ocr_text_edits"] = editor
    return editor


def _ocr_compatible_operations(items):
    """Refuse ambiguous draft combinations before accepting or exporting them."""
    insertions, replacements = {}, set()
    rectangles = []
    for item in items:
        if item.get("kind") != "insert":
            replacements.add(item["id"])
            continue
        anchor = item["anchor_id"]
        if anchor in insertions:
            raise WorkspaceError("Only one missing word can be inserted beside each OCR anchor in this pass")
        insertions[anchor] = item["id"]
        left, top, width, height = item["placement"]["rect"]
        for page, old in rectangles:
            if page == item["page"] and min(left + width, old[0] + old[2]) > max(left, old[0]) and min(top + height, old[1] + old[3]) > max(top, old[1]):
                raise WorkspaceError("Missing-word placement rectangles must not overlap")
        rectangles.append((item["page"], [left, top, width, height]))
    if set(insertions) & replacements:
        raise WorkspaceError("Apply or revert a replacement before inserting beside the same OCR anchor")


def _ocr_acceptance_valid(editor, item):
    if item.get("status") != "approved":
        return False
    try:
        _person(item.get("reviewer"), item.get("reviewed_at"))
        return item.get("acceptance_sha256") == _digest(_ocr_acceptance_payload(editor, item))
    except (KeyError, ValueError, TypeError):
        return False


def _ocr_stored_problems(state):
    editor = state.get("ocr_text_edits")
    if editor is None:
        return []
    try:
        if (not isinstance(editor, dict) or editor.get("schema_version") not in (_OCR_EDITS_SCHEMA, _OCR_EXPANDED_SCHEMA) or
                editor.get("source_sha256") != state["bindings"]["source"]["sha256"] or
                editor.get("document_sha256") != (state["bindings"].get("output") or {}).get("sha256") or
                not isinstance(editor.get("inventory_sha256"), str) or
                re.fullmatch(r"[a-f0-9]{64}", editor["inventory_sha256"]) is None or
                not isinstance(editor.get("items"), dict) or len(editor["items"]) > 2000):
            return ["Saved OCR corrections no longer match the reviewed artifact"]
        expanded = editor["schema_version"] == _OCR_EXPANDED_SCHEMA
        if expanded and (not isinstance(editor.get("expansion_sha256"), str) or
                         re.fullmatch(r"[a-f0-9]{64}", editor["expansion_sha256"]) is None):
            return ["Saved extended OCR editing capability changed"]
        for key, item in editor["items"].items():
            if (not isinstance(item, dict) or key != item.get("id") or
                    not isinstance(item.get("original"), str) or not isinstance(item.get("value"), str) or
                    not isinstance(item.get("context_sha256"), str) or
                    re.fullmatch(r"[a-f0-9]{64}", item["context_sha256"]) is None or
                    item.get("status") not in ("pending", "approved") or
                    (item["status"] == "approved" and not _ocr_acceptance_valid(editor, item))):
                return ["Saved OCR correction context or acceptance changed"]
            if expanded:
                if item.get("kind") not in ("replace", "insert"):
                    return ["Saved OCR editing operation changed"]
                if item["kind"] == "insert":
                    rect = item.get("placement", {}).get("rect") if isinstance(item.get("placement"), dict) else None
                    if (not isinstance(item.get("anchor_id"), str) or not item["anchor_id"] or item["original"] != "" or
                            type(item.get("page")) is not int or not 1 <= item["page"] <= state["page_count"] or
                            item["placement"].get("order") not in ("before", "after") or
                            not isinstance(rect, list) or len(rect) != 4 or
                            any(type(v) not in (int, float) or not math.isfinite(v) for v in rect) or
                            not (0 <= rect[0] < 1 and 0 <= rect[1] < 1 and rect[2] > 0 and rect[3] > 0 and
                                 rect[0] + rect[2] <= 1 and rect[1] + rect[3] <= 1)):
                        return ["Saved missing-word placement changed"]
        if expanded:
            _ocr_compatible_operations(editor["items"].values())
    except (KeyError, TypeError):
        return ["Saved OCR corrections are malformed"]
    except WorkspaceError:
        return ["Saved OCR editing operations conflict"]
    return []


def _ocr_editor_summary(state):
    editor = state.get("ocr_text_edits") if isinstance(state.get("ocr_text_edits"), dict) else {}
    changed = [item for item in _ocr_saved_items(state).values() if isinstance(item, dict) and item.get("value") != item.get("original")]
    return {"available": bool(state["bindings"].get("output") and not state["stale"] and not state.get("credential_lineage")),
            "changed_count": len(changed),
            "accepted_count": sum(_ocr_acceptance_valid(editor, item) for item in changed),
            "requires_reprocessing": bool(changed), "limits": (["OCR text-editor chaining is not yet supported for a Content Credentials working copy. Its recorded original and credential-removal proof must remain intact; ordinary document edits can still be reviewed."] if state.get("credential_lineage") else _OCR_LIMITS)}


def _require_ocr_ancestry(state):
    if state.get("credential_lineage"):
        raise WorkspaceError("OCR text-editor chaining is not supported for a Content Credentials working copy; its original and removal proof remain unchanged")


def _ocr_inventory(state, profile="legacy"):
    from .ocr_corrections import get_inventory
    _require_ocr_ancestry(state)
    _actionable(state, require_artifact=True)
    selected = _ocr_profile(state, profile)
    inventory = (get_inventory(state["bundle"]["path"], profile=selected) if selected == "expanded-v2"
                 else get_inventory(state["bundle"]["path"]))
    if (inventory.get("source_sha256") != state["bindings"]["source"]["sha256"] or
            inventory.get("document_sha256") != state["bindings"]["output"]["sha256"] or
            not isinstance(inventory.get("inventory_sha256"), str) or
            re.fullmatch(r"[a-f0-9]{64}", inventory["inventory_sha256"]) is None):
        raise StaleWorkspace("OCR text inventory is not bound to the current reviewed artifact")
    if selected == "expanded-v2" and (inventory.get("schema_version") != "phase2-ocr-text-inventory-2" or
            not isinstance(inventory.get("expansion_sha256"), str) or
            re.fullmatch(r"[a-f0-9]{64}", inventory["expansion_sha256"]) is None):
        raise StaleWorkspace("Extended OCR editing capability cannot be verified")
    items = inventory.get("items")
    if not isinstance(items, list) or len({item["id"] for item in items}) != len(items):
        raise WorkspaceError("OCR text inventory contains invalid or duplicate occurrences")
    editor = state.get("ocr_text_edits")
    if editor is not None and editor.get("items"):
        if any(editor.get(key) != inventory.get(key) for key in ("source_sha256", "document_sha256", "inventory_sha256")):
            raise StaleWorkspace("The OCR occurrence inventory changed; keep the saved review and import a fresh result")
        if selected == "expanded-v2" and editor.get("expansion_sha256") != inventory["expansion_sha256"]:
            raise StaleWorkspace("The extended OCR font or placement capability changed; keep the saved review")
        current = {item["id"]: item for item in items}
        for ident, saved in editor["items"].items():
            if selected == "expanded-v2":
                from .ocr_corrections import validate_operation
                try:
                    validate_operation(inventory, saved)
                except ValueError as error:
                    raise StaleWorkspace("A saved extended OCR operation changed: " + str(error)) from error
                continue
            item = current.get(ident)
            if item is None or saved["original"] != item["current"] or saved["context_sha256"] != item["context_sha256"]:
                raise StaleWorkspace("A saved OCR correction occurrence changed")
    return inventory


def get_ocr_editor(state_path, page=1, profile="legacy"):
    """Inspect OCR text without migrating or rewriting an existing saved review."""
    state = load_workspace(state_path)
    if type(page) is not int or not 1 <= page <= state["page_count"]:
        raise WorkspaceError("Choose an existing PDF page for OCR text review")
    selected = _ocr_profile(state, profile)
    inventory = _ocr_inventory(state, profile)
    stored = (state.get("ocr_text_edits") or {}).get("items", {})
    items = []
    for original in inventory["items"]:
        if original["page"] != page:
            continue
        saved = stored.get(original["id"], {})
        public = {key: copy.deepcopy(original[key]) for key in ("id", "page", "current", "context_sha256",
                  "supported_characters", "max_characters", "context_text", "context_text_source", "occurrence", "limitations",
                  "bbox", "page_geometry", "insertion_eligible", "insertion_reason") if key in original}
        items.append({**public, "original": original["current"],
                      "original_text": original["current"], "value": saved.get("value", original["current"]),
                      "status": saved.get("status", "pending"), "eligible": original.get("editable", False),
                      "approved_by": saved.get("reviewer"), "approved_at": saved.get("reviewed_at")})
    insertions = [{**copy.deepcopy(item), "approved_by": item.get("reviewer"), "approved_at": item.get("reviewed_at")}
                  for item in stored.values() if item.get("kind") == "insert" and item.get("page") == page]
    fallback = selected == "legacy" and profile == "expanded-v2"
    insertion_enabled = selected == "expanded-v2" and any(item.get("insertion_eligible") is True for item in items)
    return {"revision": state["revision"], "page": page, "source": copy.deepcopy(state["bindings"]["source"]),
            "document": copy.deepcopy(state["bindings"]["output"]), "inventory_sha256": inventory["inventory_sha256"],
            "available": bool(inventory.get("eligible", bool(inventory["items"]))), "items": items,
            "limitations": copy.deepcopy(inventory.get("limitations", [])), "limits": _OCR_LIMITS,
            "reason": inventory.get("reason"), "true_original": copy.deepcopy(inventory.get("true_original")),
            "verification": "not-verified", "profile": selected, "requested_profile": profile,
            "expansion_sha256": inventory.get("expansion_sha256"),
            "expansion_available": not (selected == "legacy" and bool(stored)),
            "expansion_reason": ("Apply or revert the saved OCR corrections before enabling extended editing." if fallback else ""),
            "font_policy": copy.deepcopy(inventory.get("font_policy")),
            "page_geometry": next((item["page_geometry"] for item in items if "page_geometry" in item), None),
            "insertions": insertions, "insertion_enabled": insertion_enabled,
            "insertion_reason": ("" if insertion_enabled else "This page has no safe missing-word insertion anchor in the selected editing mode.")}


def _ocr_target(state, identifier, inventory_sha256, context_sha256, expansion_sha256=None):
    profile = "expanded-v2" if expansion_sha256 is not None else "legacy"
    if profile == "expanded-v2" and _ocr_profile(state, profile) != profile:
        raise WorkspaceError("Apply or revert the saved OCR corrections before enabling extended editing")
    inventory = _ocr_inventory(state, profile)
    if _ocr_schema(inventory) == _OCR_EXPANDED_SCHEMA and expansion_sha256 != inventory.get("expansion_sha256"):
        raise RevisionConflict("Extended OCR editing capability changed; reload the page before saving")
    if inventory_sha256 != inventory["inventory_sha256"]:
        raise RevisionConflict("OCR inventory changed; reload the page before saving")
    item = _find(inventory["items"], identifier)
    if item.get("context_sha256") != context_sha256:
        raise RevisionConflict("OCR occurrence context changed; reload the page before saving")
    if item.get("editable") is not True:
        raise WorkspaceError("This OCR occurrence cannot be corrected safely")
    return inventory, item


def _invalidate_for_ocr_edit(state):
    invalidated = []
    for item in state["manual_items"]:
        if item.get("status") == "approved":
            invalidated.append({"id": item["id"], "previous_review": {key: copy.deepcopy(item.get(key))
                                for key in ("status", "reviewer", "reviewed_at", "notes")}})
            item["status"] = "pending"
    state["manual_approvals"] = {}
    _invalidate_automatic_records(state, "ocr-text-value-changed")
    return invalidated


def edit_ocr_text(state_path, identifier, value, expected_revision, inventory_sha256, context_sha256, actor="human", expansion_sha256=None):
    if actor != "human":
        raise WorkspaceError("Only explicit human editing can change OCR correction values")
    def operation(state):
        _require_ocr_ancestry(state)
        from .ocr_corrections import validate_replacement
        inventory, item = _ocr_target(state, identifier, inventory_sha256, context_sha256, expansion_sha256)
        value_checked = validate_replacement(item, value)
        editor = _ocr_editor_for_save(state, inventory)
        previous = copy.deepcopy(editor["items"].get(identifier))
        old_value = (previous or {}).get("value", item["current"])
        invalidated = []
        if value_checked != old_value:
            invalidated = _invalidate_for_ocr_edit(state)
        if value_checked == item["current"]:
            editor["items"].pop(identifier, None)
        elif value_checked != old_value or previous is None:
            if identifier not in editor["items"] and len(editor["items"]) >= 2000:
                raise WorkspaceError("Create a corrected copy before saving more than 2,000 OCR corrections")
            editor["items"][identifier] = {"id": identifier, "page": item["page"], "context_sha256": item["context_sha256"],
                "original": item["current"], "value": value_checked, "status": "pending"}
            if editor["schema_version"] == _OCR_EXPANDED_SCHEMA:
                editor["items"][identifier]["kind"] = "replace"
        if editor["schema_version"] == _OCR_EXPANDED_SCHEMA:
            _ocr_compatible_operations(editor["items"].values())
        _record_event(state, "edit-ocr-text", actor="human", occurrence_id=identifier, previous=previous,
                      invalidated_manual_approvals=invalidated, accessibility_approval=False)
    return _change(state_path, expected_revision, operation)


def approve_ocr_text(state_path, identifier, reviewer, reviewed_at, expected_revision, inventory_sha256, context_sha256, actor="human", expansion_sha256=None):
    if actor != "human":
        raise WorkspaceError("Only explicit human acceptance can authorize an OCR correction")
    reviewer = _person(reviewer, reviewed_at)
    def operation(state):
        _require_ocr_ancestry(state)
        from .ocr_corrections import validate_replacement
        editor = state.get("ocr_text_edits") or {}
        saved = (editor.get("items") or {}).get(identifier)
        anchor_id = saved.get("anchor_id", identifier) if saved else identifier
        inventory, item = _ocr_target(state, anchor_id, inventory_sha256, context_sha256, expansion_sha256)
        if saved is None or (saved.get("kind") != "insert" and saved["value"] == item["current"]):
            raise WorkspaceError("Save a changed OCR correction before accepting it")
        if editor.get("schema_version") == _OCR_EXPANDED_SCHEMA:
            from .ocr_corrections import validate_operation
            validate_operation(inventory, saved)
            _ocr_compatible_operations(editor["items"].values())
        else:
            validate_replacement(item, saved["value"])
        saved.update(status="approved", reviewer=reviewer, reviewed_at=reviewed_at)
        saved["acceptance_sha256"] = _digest(_ocr_acceptance_payload(editor, saved))
        _record_event(state, "accept-ocr-text-correction", occurrence_id=identifier, reviewer=reviewer,
                      reviewed_at=reviewed_at, accessibility_approval=False)
    return _change(state_path, expected_revision, operation)


def insert_ocr_text(state_path, anchor_identifier, value, placement, expected_revision, inventory_sha256,
                    context_sha256, identifier=None, actor="human", expansion_sha256=None):
    if actor != "human":
        raise WorkspaceError("Only explicit human editing can insert missing OCR words")
    if expansion_sha256 is None:
        raise WorkspaceError("Enable extended OCR editing before inserting a missing word")
    saved_identifier = identifier or "ocr-insert-" + uuid.uuid4().hex
    if not isinstance(saved_identifier, str) or re.fullmatch(r"ocr-insert-[a-f0-9]{32}", saved_identifier) is None:
        raise WorkspaceError("Choose an existing saved insertion to edit")
    def operation(state):
        _require_ocr_ancestry(state)
        from .ocr_corrections import validate_insertion, validate_operation
        inventory, anchor = _ocr_target(state, anchor_identifier, inventory_sha256, context_sha256, expansion_sha256)
        normalized = validate_insertion(anchor, value, placement)
        editor = _ocr_editor_for_save(state, inventory)
        previous = copy.deepcopy(editor["items"].get(saved_identifier))
        if identifier is not None and (previous is None or previous.get("kind") != "insert"):
            raise WorkspaceError("The saved missing-word insertion no longer exists")
        if previous is None and len(editor["items"]) >= 2000:
            raise WorkspaceError("Create a corrected copy before saving more than 2,000 OCR corrections")
        candidate = {"kind": "insert", "id": saved_identifier, "anchor_id": anchor_identifier,
            "page": anchor["page"], "original": "", "value": value, "placement": normalized,
            "context_sha256": anchor["context_sha256"], "status": "pending"}
        validate_operation(inventory, candidate)
        same = previous is not None and all(previous.get(key) == val for key, val in candidate.items() if key != "status")
        invalidated = []
        if not same:
            editor["items"][saved_identifier] = candidate
            _ocr_compatible_operations(editor["items"].values())
            invalidated = _invalidate_for_ocr_edit(state)
        _record_event(state, "edit-ocr-insertion", actor="human", occurrence_id=saved_identifier,
                      previous=previous, invalidated_manual_approvals=invalidated, accessibility_approval=False)
    result = _change(state_path, expected_revision, operation)
    result["ocr_saved_insertion_id"] = saved_identifier
    return result


def remove_ocr_insertion(state_path, identifier, expected_revision, inventory_sha256, context_sha256,
                         actor="human", expansion_sha256=None):
    if actor != "human":
        raise WorkspaceError("Only explicit human editing can remove a missing-word draft")
    def operation(state):
        _require_ocr_ancestry(state)
        editor = state.get("ocr_text_edits") or {}
        saved = (editor.get("items") or {}).get(identifier)
        if not saved or saved.get("kind") != "insert":
            raise WorkspaceError("Choose a saved missing-word insertion to remove")
        _ocr_target(state, saved["anchor_id"], inventory_sha256, context_sha256, expansion_sha256)
        previous = editor["items"].pop(identifier)
        invalidated = _invalidate_for_ocr_edit(state)
        _record_event(state, "remove-ocr-insertion", occurrence_id=identifier, previous=previous,
                      invalidated_manual_approvals=invalidated, accessibility_approval=False)
    return _change(state_path, expected_revision, operation)


def _ocr_plan(state, strict=False):
    if strict:
        _require_ocr_ancestry(state)
    editor = state.get("ocr_text_edits")
    changed = list((editor or {}).get("items", {}).values())
    if not changed:
        if strict:
            raise WorkspaceError("Save and accept at least one changed OCR word")
        return None
    if strict and any(item.get("value") != state["original_decision_values"].get(item["id"])
                      for item in state["sidecar"].get("decisions", [])):
        raise WorkspaceError("Apply or revert other document edits before creating an OCR-corrected copy; saved edits remain in this review")
    inventory = _ocr_inventory(state)
    current = {item["id"]: item for item in inventory["items"]}
    accepted = []
    for saved in changed:
        if not _ocr_acceptance_valid(editor, saved):
            if strict:
                raise WorkspaceError("Accept each changed OCR word, or revert it, before creating the corrected copy")
            continue
        if editor["schema_version"] == _OCR_EXPANDED_SCHEMA:
            from .ocr_corrections import validate_operation
            validate_operation(inventory, saved)
            accepted.append(_ocr_operation_fields(saved))
        else:
            from .ocr_corrections import validate_replacement
            validate_replacement(current[saved["id"]], saved["value"])
            accepted.append({key: saved[key] for key in ("id", "context_sha256", "original", "value",
                                                        "reviewer", "reviewed_at", "acceptance_sha256")})
    if not accepted:
        if strict:
            raise WorkspaceError("Accept at least one changed OCR word")
        return None
    return {"schema_version": editor["schema_version"],
            **{key: inventory[key] for key in ("source_sha256", "document_sha256", "inventory_sha256")},
            **({"expansion_sha256": inventory["expansion_sha256"]} if editor["schema_version"] == _OCR_EXPANDED_SCHEMA else {}),
            "workspace_id": state["workspace_id"], "revision": state["revision"],
            "corrections": sorted(accepted, key=lambda item: item["id"]),
            "human_approved": False, "accessibility_approved": False}


def export_ocr_corrections(state_path, destination, expected_revision):
    return export_workspace(state_path, destination, expected_revision, _ocr_strict=True)


def record_prior_ocr_review(source_state_path, destination_state_path, expected_source_revision, expected_revision, source_identifier):
    """Link the preserved earlier review without transferring any approval."""
    source_path, destination_path = Path(source_state_path).resolve(), Path(destination_state_path).resolve()
    if source_path == destination_path or not isinstance(source_identifier, str) or not re.fullmatch(r"[a-f0-9]{24}", source_identifier):
        raise WorkspaceError("A separate earlier review is required for corrected-source context")
    with _locked(source_path):
        source = _read_state(source_path)
        if _refresh(source):
            _save(source_path, source)
        _actionable(source)
        if type(expected_source_revision) is not int or source["revision"] != expected_source_revision:
            raise RevisionConflict("The earlier review changed; its current notes remain preserved")
        def operation(state):
            if not state.get("source_lineage"):
                raise WorkspaceError("Only a separately checked corrected-source result can link the earlier OCR review")
            state["prior_review_context"] = {"workspace_id": source_identifier, "review_workspace_id": source["workspace_id"],
                "revision": source["revision"], "state_sha256": source["state_sha256"],
                "bundle_manifest_sha256": source["bundle"]["manifest_sha256"],
                "notes_count": sum(bool(item.get("notes")) for item in source["manual_items"]),
                "blocked_count": sum(item.get("status") == "blocked" for item in source["manual_items"]),
                "notice": "Previous notes and reported problems remain in the earlier review; this corrected copy requires fresh review.",
                "human_approvals_copied": 0}
            _record_event(state, "link-preserved-earlier-ocr-review", source_workspace_id=source["workspace_id"],
                          source_revision=source["revision"], human_approvals_copied=0)
        return _change(destination_path, expected_revision, operation)


def _repair_findings(state):
    """Read stored screen evidence; opening a view never measures it again."""
    names = {"metadata-meaning": "language-correctness", "contrast": "contrast"}
    issues = {item.get("id"): item for item in state["residual_issues"]}
    findings = []
    for item in state["manual_items"]:
        identifier = names.get(item.get("id"))
        evidence = item.get("evidence")
        if identifier and isinstance(evidence, dict) and evidence:
            findings.append({"id": identifier, "status": evidence.get("status", "needs-review"),
                             "evidence": copy.deepcopy(evidence),
                             "fix_path": issues.get(identifier, {}).get("fix_path", item.get("detail", ""))})
    return findings


def _view(state):
    automatic = _active_automatic_records(state)
    manual = [{**copy.deepcopy(item), "context_sha256": _digest(_scope(item)), "resolved_pages": _pages(item),
               "evidence": _detail(item), "automatic_handled": item["id"] in automatic,
               "human_touched": item["id"] in state.get("manual_touched", []),
               "optional_quick_review": item["id"] in automatic,
               "automatic_record": copy.deepcopy(automatic.get(item["id"]))} for item in state["manual_items"]]
    decisions = [{**copy.deepcopy(item), "human_touched": item["id"] in state["human_touched"]}
                 for item in state["sidecar"].get("decisions", [])]
    blocked = [item for item in manual if item.get("status") == "blocked"]
    unapplied = _unapplied(state)
    historical = state["bundle"]["status"]
    status = "needs-manual" if state["stale"] or blocked or unapplied else ("candidate" if historical == "verified" else historical)
    banner = ("Approval invalidated: " + "; ".join(state["stale_reasons"]) if state["stale"] else
              "A confirmed blocker requires manual remediation." if blocked else
              "Changed decisions require a new processing bundle; the existing PDF has not changed." if unapplied else
              "Review state is local. Automated candidacy does not grant human verification.")
    return {"schema_version": SCHEMA_VERSION, "workspace_id": state["workspace_id"], "revision": state["revision"],
            "status": status, "historical_status": historical, "cancelled": status == "failed" and _saved_cancelled(state),
            "stale": state["stale"], "banner": banner,
            "bundle_path": state["bundle"]["path"], "source": state["bindings"]["source"],
            "output": state["bindings"]["output"], "prepared": state["bindings"]["prepared"],
            "page_count": state["page_count"], "decisions": decisions, "manual_items": manual, "groups": _groups(state),
            "counts": {"manual_total": len(manual), "manual_pending": sum(item["status"] == "pending" for item in manual),
                       "manual_pending_actionable": sum(item["status"] == "pending" and not item["automatic_handled"] for item in manual),
                       "automated_count": len(automatic),
                       "manual_approved": sum(item["status"] == "approved" for item in manual), "manual_blocked": len(blocked),
                       "decision_total": len(decisions), "decision_approved": sum(item["status"] == "approved" for item in decisions),
                       "decision_auto_accepted": sum(item["status"] == "auto-accepted" for item in decisions)},
            "automatic_review_summary": {"automatic_handled": len(automatic), "policy_version": _AUTOMATIC_POLICY,
                "remaining_actionable": sum(item["status"] == "pending" and not item["automatic_handled"] for item in manual),
                "human_approved": False, "required_human_verification_reviews_unchanged": True},
            "blockers": copy.deepcopy(state["residual_issues"]) + blocked, "unapplied_decisions": unapplied,
            "repair_findings": _repair_findings(state),
             "ocr_editor": _ocr_editor_summary(state), "source_lineage": copy.deepcopy(state.get("source_lineage")),
             "credential_copy": ({**copy.deepcopy(state["credential_copy_context"]),
                                  "eligible": not state["stale"] and state["credential_copy_context"]["eligible"]}
                                 if state.get("credential_copy_context") else None),
             "credential_lineage": copy.deepcopy(state.get("credential_lineage")),
             "credential_derivative": copy.deepcopy(state.get("credential_derivative")),
             "previous_review": copy.deepcopy(state.get("prior_review_context")),
            "suggestions": copy.deepcopy(state["suggestions"]), "verification": "not-verified", "history": copy.deepcopy(state["history"])}


def get_view(state_path):
    return _view(load_workspace(state_path))


def get_saved_summary(state_path):
    """Read the checked state envelope without refreshing its PDF bindings.

    Dashboard listings describe saved work, not a fresh artifact assessment.
    Opening a review and every protected action still perform the full refresh.
    Atomic state replacement permits this read without a mutable review lock.
    """
    state = _read_state(Path(state_path))
    manual = state["manual_items"]
    blocked = sum(item["status"] == "blocked" for item in manual)
    historical = state["bundle"]["status"]
    status = ("needs-manual" if state["stale"] or blocked or _unapplied(state)
              else "candidate" if historical == "verified" else historical)
    return {"workspace_id": state["workspace_id"], "revision": state["revision"],
            "source": state["bindings"]["source"], "status": status,
            "cancelled": status == "failed" and _saved_cancelled(state),
            "stale": state["stale"], "page_count": state["page_count"],
            "counts": {"manual_total": len(manual),
                       "manual_pending": sum(item["status"] == "pending" for item in manual),
                       "manual_approved": sum(item["status"] == "approved" for item in manual),
                       "manual_blocked": blocked},
            "artifacts_checked": False}


def _actionable(state, require_artifact=False, review_approval=False):
    if state["stale"]:
        raise StaleWorkspace("Review inputs changed; import a fresh bundle before further approvals or export")
    if require_artifact and not state["artifact_sha256"]:
        raise WorkspaceError("There is no published artifact to approve or export for human verification")
    if review_approval and _unapplied(state):
        raise WorkspaceError("Changed PDF decisions require reprocessing before approving the resulting artifact")


def _change(path, expected_revision, operation):
    with _locked(path) as path:
        state = _read_state(path)
        if _refresh(state):
            _save(path, state)
        if type(expected_revision) is not int or expected_revision != state["revision"]:
            raise RevisionConflict("Workspace revision changed; reload before applying this action")
        _actionable(state)
        operation(state)
        if _refresh(state):
            _save(path, state)
            raise StaleWorkspace("Review inputs changed during this action; approvals were invalidated")
        _save(path, state)
        return _view(state)


def _find(items, identifier):
    for item in items:
        if item["id"] == identifier:
            return item
    raise WorkspaceError("Unknown review occurrence or decision ID")


def _invalidate_automatic_records(state, reason):
    invalidations = state.setdefault("automatic_review_invalidations", [])
    existing = {item["record_sha256"] for item in invalidations}
    for record in state.get("automatic_review_records", []):
        if record["record_sha256"] not in existing:
            invalidations.append({"record_sha256": record["record_sha256"], "reason": reason, "at": _now()})


def _edit_value(state, identifier, value):
    item = _find(state["sidecar"].get("decisions", []), identifier)
    navigation_kind = item.get("kind") in {"annotation-name", "link-name", "link-target", "bookmark-entry", "bookmark-additions"}
    semantic_tree_kind = item.get("kind") in {"semantic-role", "reading-order", "tree-move", "semantic-list"}
    table_kind = item.get("kind") == "table-structure"
    form_kind = item.get("kind") == "form-controls"
    max_characters = 100000 if semantic_tree_kind else 150000 if navigation_kind or table_kind or form_kind else 20000
    if not isinstance(value, str) or len(value) > max_characters or "\x00" in value:
        raise WorkspaceError(f"Decision value must be plain text without NUL characters, at most {max_characters:,} characters")
    if item.get("kind") in {"heading-tag", "table-header", "figure-purpose", "structure-role", "page-language", "passage-language",
            "annotation-name", "link-name", "link-target", "bookmark-entry", "bookmark-additions",
            "semantic-role", "reading-order", "tree-move", "semantic-list", "table-structure", "form-controls", "empty-tag-removal"}:
        candidate = {**item, "value": value}
        try:
            _validate_value(candidate)
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc
    if item.get("value") != value:
        item["value"] = value
        _clear_approval(item)
        if isinstance(item.get("ai_origin"), dict):
            origin = item["ai_origin"]
            current_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
            origin["human_modified_after_adoption"] = True
            origin["current_value_sha256"] = current_hash
            origin["current_value_differs_from_draft"] = current_hash != origin.get("draft_value_sha256")
        for manual in state["manual_items"]:
            if manual.get("status") == "approved":
                _clear_approval(manual, manual=True)
        state["manual_approvals"] = {}
        _invalidate_automatic_records(state, "decision-value-changed")
    if identifier not in state["human_touched"]:
        state["human_touched"].append(identifier)


def edit_decision(state_path, identifier, value, expected_revision, actor="human"):
    if actor != "human":
        raise WorkspaceError("AI proposals must remain separate drafts; only explicit human editing can change decision values")
    def operation(state):
        _edit_value(state, identifier, value)
        _record_event(state, "edit-decision", actor="human", decision_id=identifier)
    return _change(state_path, expected_revision, operation)


def approve_decision(state_path, identifier, reviewer, reviewed_at, expected_revision):
    reviewer = _person(reviewer, reviewed_at)
    def operation(state):
        _actionable(state, require_artifact=True)
        item = _find(state["sidecar"].get("decisions", []), identifier)
        item.pop("automatic_application", None)
        item.pop("automatic_acceptance_sha256", None)
        bind_approval(item, reviewer, reviewed_at)
        if identifier not in state["human_touched"]:
            state["human_touched"].append(identifier)
        _record_event(state, "approve-decision", reviewer=reviewer, reviewed_at=reviewed_at, decision_id=identifier)
    return _change(state_path, expected_revision, operation)


def _approve_item(state, item, reviewer, reviewed_at, status, notes=""):
    if status == "approved":
        _actionable(state, require_artifact=True, review_approval=True)
    item.update(status=status, reviewer=reviewer, reviewed_at=reviewed_at, notes=str(notes))
    state["manual_approvals"].pop(item["id"], None)
    if item["id"] not in state.setdefault("manual_touched", []):
        state["manual_touched"].append(item["id"])
    if status == "approved":
        state["manual_approvals"][item["id"]] = _digest({"item": item, "artifact_sha256": state["artifact_sha256"]})


def review_item(state_path, identifier, status, reviewer, reviewed_at, expected_revision, notes=""):
    if status not in {"approved", "pending", "blocked"}:
        raise WorkspaceError("Review status must be approved, pending, or blocked")
    reviewer = _person(reviewer, reviewed_at)
    def operation(state):
        item = _find(state["manual_items"], identifier)
        _approve_item(state, item, reviewer, reviewed_at, status, notes)
        _record_event(state, "review-item", item_id=identifier, status=status, reviewer=reviewer, reviewed_at=reviewed_at, notes=str(notes))
    return _change(state_path, expected_revision, operation)


def preserve_manual_preferences(source_state_path, destination_state_path, expected_revision):
    """Carry an explicit request for individual review, never a human approval."""
    source_path, destination_path = Path(source_state_path).resolve(), Path(destination_state_path).resolve()
    if source_path == destination_path:
        raise WorkspaceError("Preference transfer requires two separate review workspaces")
    # Exclusive creation locks fail immediately instead of waiting, so competing
    # cross-workspace transfers cannot deadlock or silently lose a source edit.
    with _locked(source_path):
        source = _read_state(source_path)
        if _refresh(source):
            _save(source_path, source)
        _actionable(source)
        if any(item.get("status") == "blocked" for item in source["manual_items"]):
            raise WorkspaceError("Resolve confirmed source blockers before automatic processing")
        def operation(state):
            if source["bindings"]["source"]["sha256"] != state["bindings"]["source"]["sha256"]:
                raise WorkspaceError("Individual review preferences belong to a different original source")
            destination_items = {item["id"]: item for item in state["manual_items"]}
            copied, skipped = [], []
            touched = state.setdefault("manual_touched", [])
            for item in source["manual_items"]:
                if item["id"] not in source.get("manual_touched", []) or item.get("status") != "pending":
                    continue
                target = destination_items.get(item["id"])
                if target is None or _scope(target) != _scope(item):
                    skipped.append({"id": item["id"], "reason": "occurrence-context-changed"})
                elif target.get("status") != "pending":
                    skipped.append({"id": item["id"], "reason": "destination-human-choice-protected"})
                else:
                    if item["id"] not in touched:
                        touched.append(item["id"])
                    copied.append(item["id"])
            if _refresh(source):
                _save(source_path, source)
                raise StaleWorkspace("Source review inputs changed during preference transfer")
            _record_event(state, "preserve-individual-pending-review-preferences", source_workspace_id=source["workspace_id"],
                          source_revision=source["revision"], copied_ids=copied, skipped=skipped,
                          human_approvals_copied=0, blocker_statuses_copied=0)
        return _change(destination_path, expected_revision, operation)


def approve_group(state_path, group_id, member_ids, membership_digest, reviewer, reviewed_at, expected_revision):
    reviewer = _person(reviewer, reviewed_at)
    if not isinstance(member_ids, list) or not member_ids or any(not isinstance(ident, str) for ident in member_ids) or len(set(member_ids)) != len(member_ids):
        raise WorkspaceError("Explicitly select a nonempty list of distinct occurrence IDs")
    def operation(state):
        group = _find(_groups(state), group_id)
        if not group["group_approvable"] or membership_digest != group["membership_digest"] or not set(member_ids).issubset(group["member_ids"]):
            raise RevisionConflict("Group membership/context changed, or selected items are outside this group")
        _actionable(state, require_artifact=True, review_approval=True)
        if any(_find(state["manual_items"], identifier).get("status") == "blocked" for identifier in member_ids):
            raise WorkspaceError("Resolve each confirmed blocker on its individual occurrence before group approval")
        for identifier in member_ids:
            _approve_item(state, _find(state["manual_items"], identifier), reviewer, reviewed_at, "approved")
        _record_event(state, "approve-selected-group-members", group_id=group_id, member_ids=sorted(member_ids),
                      membership_digest=membership_digest, reviewer=reviewer, reviewed_at=reviewed_at)
    return _change(state_path, expected_revision, operation)


def merge_ai_drafts(state_path, envelope, expected_revision):
    def operation(state):
        from .assistance import validate_suggestions
        suggestions = validate_suggestions(state["sidecar"], envelope)
        accepted, skipped = [], []
        for suggestion in suggestions:
            item = _find(state["sidecar"]["decisions"], suggestion["id"])
            if item["id"] in state["human_touched"] or item.get("status") == "approved":
                skipped.append(item["id"])
                continue
            if suggestion.get("original_value_sha256") != hashlib.sha256(item.get("value", "").encode("utf-8")).hexdigest():
                raise StaleWorkspace("AI draft was generated from an older decision value")
            draft = copy.deepcopy(suggestion)
            draft["suggestion_id"] = _digest(draft)
            draft["status"] = "draft"
            if not any(existing["suggestion_id"] == draft["suggestion_id"] for existing in state["suggestions"]):
                state["suggestions"].append(draft)
            accepted.append(item["id"])
        _record_event(state, "stage-ai-drafts", staged_ids=accepted, skipped_human_protected_ids=skipped,
                      data_sent=copy.deepcopy(envelope.get("data_sent", {})))
    return _change(state_path, expected_revision, operation)


add_suggestions = merge_ai_drafts


def _suggestion_origin(suggestion):
    provenance = suggestion.get("provenance", {})
    allowed = ("provider", "model", "prompt_version", "context_version", "schema_version", "model_revision",
               "model_metadata_sha256", "request_sha256", "response_sha256", "generated_at", "include_images", "cache_key")
    draft_hash = hashlib.sha256(suggestion["value"].encode("utf-8")).hexdigest()
    return {"schema_version": "phase2-ai-origin-1", "suggestion_id": suggestion["suggestion_id"],
            "provider": provenance.get("provider"), "model": provenance.get("model"),
            "prompt_version": provenance.get("prompt_version"), "context_sha256": suggestion.get("context_sha256"),
            "request_context_sha256": suggestion.get("request_context_sha256"), "cache_key": provenance.get("cache_key"),
            "draft_value_sha256": draft_hash, "current_value_sha256": draft_hash,
            "human_modified_after_adoption": False, "current_value_differs_from_draft": False,
            "provenance": {key: copy.deepcopy(provenance[key]) for key in allowed if key in provenance}}


def accept_suggestion(state_path, suggestion_id, expected_revision):
    def operation(state):
        suggestion = next((item for item in state["suggestions"] if item["suggestion_id"] == suggestion_id), None)
        if suggestion is None or suggestion.get("status") != "draft":
            raise WorkspaceError("Unknown or already handled AI draft")
        item = _find(state["sidecar"]["decisions"], suggestion["id"])
        if item["id"] in state["human_touched"] or item.get("status") == "approved":
            raise WorkspaceError("This decision has a human edit or approval; AI cannot replace it")
        if suggestion.get("original_value_sha256") != hashlib.sha256(item.get("value", "").encode("utf-8")).hexdigest():
            raise StaleWorkspace("AI draft value binding is stale")
        _edit_value(state, item["id"], suggestion["value"])
        # Retain origin in the portable sidecar, not just mutable UI history.
        # A later explicit approval hashes this object along with the decision.
        # Credentials, endpoint configuration, prompts and response bodies are
        # deliberately excluded from this allowlisted attribution record.
        item["ai_origin"] = _suggestion_origin(suggestion)
        suggestion["status"] = "accepted-as-pending"
        _record_event(state, "accept-ai-draft-as-pending", suggestion_id=suggestion_id, decision_id=item["id"])
    return _change(state_path, expected_revision, operation)


def apply_automatic_suggestions(state_path, authorization, expected_revision, *, suggestion_ids=None):
    """Accept selected best guesses under explicit run authority, never as a human."""
    def operation(state):
        from .sidecar import bind_automatic_acceptance, rebind_automatic_acceptance, validate_automatic_authorization
        if not isinstance(authorization, dict) or not isinstance(authorization.get("decision_ids"), list):
            raise WorkspaceError("An explicit bounded automatic run authorization is required")
        identifiers = authorization["decision_ids"]
        if (any(not isinstance(identifier, str) for identifier in identifiers) or
                len(set(identifiers)) != len(identifiers)):
            raise WorkspaceError("Automatic run must identify distinct selected decisions")
        validate_automatic_authorization(authorization, state["sidecar"].get("source_sha256"),
                                         state["sidecar"].get("document_sha256"))
        if (authorization.get("source_sha256") != state["sidecar"].get("source_sha256") or
                authorization.get("document_sha256") != state["sidecar"].get("document_sha256")):
            raise StaleWorkspace("Automatic run authorization belongs to different source or prepared bytes")
        selected_ids = [] if suggestion_ids is None else suggestion_ids
        if (not isinstance(selected_ids, list) or any(not isinstance(identifier, str) for identifier in selected_ids) or
                len(set(selected_ids)) != len(selected_ids)):
            raise WorkspaceError("Select distinct draft IDs returned by this explicit assistance request")
        selected = {}
        for suggestion_id in selected_ids:
            suggestion = next((entry for entry in state["suggestions"] if entry.get("suggestion_id") == suggestion_id), None)
            if suggestion is None or suggestion.get("status") != "draft" or suggestion["id"] not in identifiers:
                raise WorkspaceError("A selected automatic draft is unknown, already handled, or outside this authorization")
            if suggestion["id"] in selected:
                raise WorkspaceError("Select at most one automatic draft per decision occurrence")
            selected[suggestion["id"]] = suggestion
        adopted, rebound, skipped, changed = [], [], [], False
        for identifier in identifiers:
            item = _find(state["sidecar"].get("decisions", []), identifier)
            if item.get("status") == "auto-accepted" and identifier not in state["human_touched"]:
                if not _valid_automatic_decision(item):
                    raise StaleWorkspace("Existing automatic value/context binding is invalid")
                rebind_automatic_acceptance(item, authorization, human_touched=False)
                rebound.append(identifier)
                continue
            if identifier in state["human_touched"] or item.get("status") != "pending":
                skipped.append({"id": identifier, "reason": "existing-choice-protected"})
                continue
            suggestion = selected.get(identifier)
            if suggestion is None:
                skipped.append({"id": identifier, "reason": "no-current-draft"})
                continue
            if item.get("kind") not in {"title", "figure-description"}:
                raise WorkspaceError("Automatic suggestions are restricted to title and figure descriptions")
            if (suggestion.get("context_sha256") != item.get("context_sha256") or
                    suggestion.get("binding") != item.get("binding") or
                    suggestion.get("original_value_sha256") != hashlib.sha256(item.get("value", "").encode("utf-8")).hexdigest()):
                raise StaleWorkspace("Automatic suggestion belongs to a different value or occurrence context")
            origin = _suggestion_origin(suggestion)
            previous = item.get("value")
            bind_automatic_acceptance(item, suggestion["value"], authorization, origin=origin, human_touched=False)
            changed = changed or previous != item.get("value")
            suggestion["status"] = "auto-accepted"
            adopted.append(identifier)
        if changed:
            for manual in state["manual_items"]:
                if manual.get("status") == "approved":
                    _clear_approval(manual, manual=True)
            state["manual_approvals"] = {}
            _invalidate_automatic_records(state, "automatic-decision-values-require-reprocessing")
        _record_event(state, "automatic-best-guess-decisions", author="automation", human_approved=False,
                      adopted_ids=adopted, rebound_ids=rebound, skipped=skipped, authorization=copy.deepcopy(authorization))
    return _change(state_path, expected_revision, operation)


auto_accept_workspace_decisions = apply_automatic_suggestions


def export_workspace(state_path, destination, expected_revision, *, _ocr_strict=False):
    with _locked(state_path) as path:
        state = _read_state(path)
        if _refresh(state):
            _save(path, state)
        if type(expected_revision) is not int or expected_revision != state["revision"]:
            raise RevisionConflict("Workspace revision changed before export; reload")
        if _ocr_strict:
            _require_ocr_ancestry(state)
        _actionable(state, require_artifact=_ocr_strict)
        ocr_plan = _ocr_plan(state, strict=_ocr_strict)
        protected = [path] + [binding["path"] for binding in state["bindings"].values() if binding]
        destination = _outside(destination, state["bundle"]["path"], protected)
        destination.mkdir(parents=True, exist_ok=True)
        export = destination / ("review-" + state["workspace_id"][:12] + "-r" + str(state["revision"]))
        if export.exists():
            raise WorkspaceError("This exact workspace revision was already exported to this destination")
        staging = destination / (".review-export-" + uuid.uuid4().hex)
        staging.mkdir()
        try:
            sidecar_path = export / "decisions.json"
            write_sidecar(copy.deepcopy(state["sidecar"]), staging / "decisions.json")
            if ocr_plan is not None:
                write_sidecar(ocr_plan, staging / "ocr-corrections.json")
            review_path = None
            if state["artifact_sha256"]:
                review = {"artifact_sha256": state["artifact_sha256"], "items": copy.deepcopy(state["manual_items"]),
                          "complete": all(item.get("status") == "approved" for item in state["manual_items"] if item.get("required", True))}
                write_sidecar(review, staging / "review.json")
                review_path = export / "review.json"
            automatic_review_path = None
            if state.get("automatic_review_records"):
                active = _active_automatic_records(state)
                automatic_review = {"schema_version": "phase2-automatic-review-export-1",
                    "workspace_id": state["workspace_id"], "revision": state["revision"],
                    "policy_version": _AUTOMATIC_POLICY, "bindings": copy.deepcopy(state["bindings"]),
                    "bundle": copy.deepcopy(state["bundle"]), "artifact_sha256": state["artifact_sha256"],
                    "records": copy.deepcopy(state["automatic_review_records"]), "active_item_ids": sorted(active),
                    "invalidations": copy.deepcopy(state.get("automatic_review_invalidations", [])),
                    "human_approved": False, "required_human_verification_reviews_unchanged": True,
                    "verification": "not-verified"}
                write_sidecar(automatic_review, staging / "automatic-review.json")
                automatic_review_path = export / "automatic-review.json"
            complete = bool(review_path) and all(item.get("status") == "approved" for item in state["manual_items"] if item.get("required", True))
            ledger_eligible = bool(state["manual_items"]) and complete and state["bundle"]["status"] == "candidate" and not _unapplied(state) and not state["residual_issues"]
            metadata = {"schema_version": SCHEMA_VERSION, "workspace_id": state["workspace_id"], "revision": state["revision"],
                        "sidecar_path": str(sidecar_path), "review_path": str(review_path) if review_path else None,
                        "automatic_review_path": str(automatic_review_path) if automatic_review_path else None,
                        "ledger_eligible": ledger_eligible, "requires_reprocessing": bool(_unapplied(state)),
                        "verification": "not-verified", "files": {file.name: file_sha256(file) for file in staging.iterdir() if file.is_file()}}
            if ocr_plan is not None:
                metadata["ocr_corrections_path"] = str(export / "ocr-corrections.json")
                metadata["ocr_correction_count"] = len(ocr_plan["corrections"])
            if state.get("credential_lineage"):
                metadata["credential_lineage"] = copy.deepcopy(state["credential_lineage"])
                metadata["credential_derivative"] = copy.deepcopy(state["credential_derivative"])
            write_sidecar(metadata, staging / "export.json")
            if _refresh(state):
                _save(path, state)
                raise StaleWorkspace("Review inputs changed during export; no export published")
            atomic_replace(staging, export)
            return metadata
        finally:
            if staging.exists():
                for name in ("decisions.json", "review.json", "automatic-review.json", "ocr-corrections.json", "export.json"):
                    (staging / name).unlink(missing_ok=True)
                try:
                    staging.rmdir()
                except OSError:
                    pass


export = export_workspace
