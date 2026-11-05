"""Real Auto-fix release trial: spawned workers, validator, and local Ollama.

Uses exact previously evaluated preparations; no source fixture is generated or
changed. Revalidates the real full book, applies local-model chapter choices,
rebinds them without another model call, and checks an unsupported refusal.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pdf_remediator import __version__
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.inspection import inspect_pdf
from pdf_remediator.ledger import LedgerError, _eligible
from pdf_remediator.pipeline import implementation_digest, sha, verify_bundle, write_json
from pdf_remediator.preview import render
from pdf_remediator.sidecar import automatic_acceptance_valid
from pdf_remediator.web import Application
from pdf_remediator import workspace


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def package_files():
    return {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
            for path in sorted((ROOT / "src/pdf_remediator").rglob("*"))
            if path.is_file() and path.suffix in {".py", ".json", ".txt", ".tex", ".html", ".css", ".js"}}


def cache_inventory(application):
    return {path.name: sha(path) for path in sorted((application.root / "ai-cache").glob("*.json"))}


def rss():
    parent = psutil.Process(os.getpid())
    total = parent.memory_info().rss
    for child in parent.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total


def run(destination, data_dir, expected_digest=None, model="qwen2.5:1.5b", include_images=False):
    destination, data_dir = Path(destination).resolve(), Path(data_dir).resolve()
    if destination.exists() or data_dir.exists():
        raise FileExistsError("Use fresh trial and application-data directories; earlier evidence is never overwritten.")
    initial_code = package_files()
    initial_digest = implementation_digest(RuntimeConfig())
    if expected_digest and initial_digest != expected_digest:
        raise ValueError("The package differs from the requested frozen release digest.")
    core = read(ROOT / "output/phase2/core-final-private/summary.json")
    corpus = read(ROOT / "output/phase2/corpus-final-private/summary.json")
    selected = {"published-book": next(case for case in core["cases"] if case["case"] == "published-book"),
                "chapter-ai": next(case for case in core["cases"] if case["case"] == "chapter-before"),
                "unsupported-form": next(case for case in corpus["cases"] if case["fixture"] == "form")}
    originals, old_manifests, old_artifacts = {}, {}, {}
    for case in selected.values():
        old = Path(case["bundle_path"])
        if not verify_bundle(old):
            raise ValueError("A prior exact preparation bundle is incomplete or changed: " + str(old))
        report = read(old / "report.json")
        originals[report["input"]["path"]] = sha(report["input"]["path"])
        old_manifests[str(old / "manifest.json")] = sha(old / "manifest.json")
        if report.get("output"):
            old_artifacts[report["output"]["path"]] = sha(report["output"]["path"])
    destination.mkdir(parents=True)
    write_json(destination / "run-provenance.json", {
        "schema_version": "auto-fix-release-trial-1", "started_utc": datetime.now(timezone.utc).isoformat(),
        "package_version": __version__, "implementation_digest": initial_digest, "package_files": initial_code,
        "runner_sha256": sha(Path(__file__)), "source_sha256_before": originals,
        "prior_manifests": old_manifests, "prior_artifacts": old_artifacts,
        "application_data_dir": str(data_dir), "model": model, "include_images": include_images,
        "policy": "Actual Application.auto_fix, actual spawned PDF workers, actual strict validator and selected installed local model. No stubs, human approvals, actual-user/AT/LMS checker trials, or verified records."})
    application = Application(data_dir, RuntimeConfig())
    rows, visuals = [], []
    started = time.monotonic()

    def save_summary(complete=False):
        stable = initial_code == package_files() and initial_digest == implementation_digest(RuntimeConfig())
        unchanged = all(sha(path) == digest for path, digest in {**originals, **old_manifests, **old_artifacts}.items())
        summary = {"schema_version": "auto-fix-release-trial-1", "complete": complete,
                   "package_version": __version__, "implementation_digest": initial_digest,
                   "implementation_unchanged": stable, "originals_and_prior_evidence_unchanged": unchanged,
                   "expected_cases": 4, "cases_completed": len(rows), "cases": rows,
                   "all_case_invariants_pass": len(rows) == 4 and all(row["invariants_pass"] for row in rows),
                   "verified_records_created": 0, "visuals": visuals, "seconds": round(time.monotonic() - started, 3),
                   "resource_scope": "Sampled trial-runner plus descendants during queued/running jobs, 0.15-second sampling; excludes brief synchronous preflight and independently running Ollama/model-service processes. Not an OS hard allocation cap.",
                   "human_testing": "Developer-controlled trial only; no actual-user, assistive-technology acceptance, or LMS checker testing."}
        write_json(destination / "summary.json", summary)
        if rows:
            with (destination / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader(); writer.writerows(rows)
        return summary

    def execute(label, identifier, use_ai=False):
        before = application.view(identifier)
        before_cache = cache_inventory(application)
        source_hash = sha(before["source"]["path"])
        old_output = before.get("output")
        begin = time.monotonic()
        parameters = {"revision": before["revision"], "consent": True, "use_ai": use_ai}
        if use_ai:
            parameters.update(ai_consent=True, endpoint="http://127.0.0.1:11434/v1", model=model,
                              include_images=include_images, reasoning_effort="none" if include_images else None)
        queued = application.auto_fix(identifier, parameters)
        peak, observed, exceeded = 0, 0, False
        while True:
            peak = max(peak, rss())
            with application.lock:
                current = application.public_job(application.jobs[queued["job_id"]])
            for message in current["progress"][observed:]:
                print(label + ": " + message, flush=True)
                with (destination / "progress.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"case": label, "message": message, "utc": datetime.now(timezone.utc).isoformat()}) + "\n")
            observed = len(current["progress"])
            if peak > application.config.memory_limit_bytes:
                exceeded = True
                application.jobs[queued["job_id"]]["cancel"].set()
            if current["status"] not in {"queued", "running"}:
                break
            if time.monotonic() - begin > 1800:
                application.jobs[queued["job_id"]]["cancel"].set()
                raise TimeoutError("Auto-fix trial exceeded 30 minutes")
            time.sleep(.15)
        write_json(destination / "cases" / label / "job.json", current)
        if current["status"] != "done":
            raise RuntimeError(label + ": " + str(current.get("error")))
        result_id = current["result"]["documents"][0]["workspace_id"]
        view = application.view(result_id)
        report = read(Path(view["bundle_path"]) / "report.json")
        raw_state = workspace.load_workspace(application.state_path(result_id))
        sidecar = read(Path(view["bundle_path"]) / "decisions.json")
        raw_automatic = [item for item in sidecar.get("decisions", []) if item.get("status") == "auto-accepted"]
        after_cache = cache_inventory(application)
        new_cache = sorted(set(after_cache) - set(before_cache))
        requests = sum(read(application.root / "ai-cache" / name).get("envelope", {}).get("data_sent", {}).get("document_requests", 0)
                       for name in new_cache)
        exported = workspace.export_workspace(application.state_path(result_id), destination / "exports" / label, view["revision"])
        review = read(exported["review_path"]) if exported.get("review_path") else None
        automatic_export = read(exported["automatic_review_path"]) if exported.get("automatic_review_path") else None
        output = report.get("output")
        gates = {key: report.get(key, {}).get("status", "not-run") for key in ("gate1", "gate2", "fidelity")}
        counts = report.get("gate1", {}).get("counts", {})
        inspection = inspect_pdf(output["path"]) if output else {}
        linked = {item["id"]: item.get("status") for item in inspection.get("checks", [])}
        candidate_ok = (report["status"] == "candidate" and all(value == "pass" for value in gates.values()) and
                        counts.get("failedRules") == counts.get("failedChecks") == 0 and output and
                        report["gate1"].get("input_sha256") == report["fidelity"].get("after_sha256") == sha(output["path"]) and
                        linked.get("content-linkage") == linked.get("content-coverage") == "pass" and
                        not inspection.get("structure", {}).get("phantom_tree"))
        no_approvals = (view["verification"] == "not-verified" and view["counts"]["manual_approved"] == 0 and
                        view["counts"]["decision_approved"] == 0 and
                        all(item.get("status") == "pending" and not item.get("reviewer") for item in raw_state["manual_items"]) and
                        all(not any(key in item for key in ("approved_by", "approved_at", "approval_sha256")) for item in raw_automatic))
        ledger_refused = True
        if output and report["status"] == "candidate":
            try:
                _eligible(report, output["sha256"])
            except LedgerError:
                pass
            else:
                ledger_refused = False
        preserved_review = (not review and not raw_state["manual_items"]) or (review is not None and
                            len(review["items"]) == len(raw_state["manual_items"]) and
                            all(item.get("status") == "pending" for item in review["items"]))
        invariants = [verify_bundle(view["bundle_path"]), sha(before["source"]["path"]) == source_hash,
                      no_approvals, ledger_refused, bool(preserved_review), not exceeded,
                      all(automatic_acceptance_valid(item) for item in raw_automatic),
                      gates["fidelity"] == "pass" or not output]
        if label == "published-book":
            invariants += [candidate_ok, view["counts"]["automated_count"] == 623,
                           view["counts"]["manual_pending"] == 630,
                           view["counts"]["manual_pending_actionable"] == 7,
                           not raw_automatic, before_cache == after_cache,
                           bool(output and output["sha256"] == old_output["sha256"]),
                           bool(automatic_export and len(automatic_export["active_item_ids"]) == 623)]
        elif label == "chapter-ai":
            invariants += [candidate_ok, len(raw_automatic) == 3,
                           {item["kind"] for item in raw_automatic} == {"title", "figure-description"},
                           requests == 1, bool(output and output["sha256"] != old_output["sha256"]),
                           len(report.get("data_sent", {}).get("prior_assistance", [])) == 3]
        elif label == "chapter-repeat":
            invariants += [candidate_ok, len(raw_automatic) == 3, before_cache == after_cache,
                           bool(output and output["sha256"] == old_output["sha256"])]
            original_authority = read(Path(before["bundle_path"]) / "report.json")["automatic_mode"]["authorization"]["authorization_id"]
            invariants.append(report["automatic_mode"]["authorization"]["authorization_id"] != original_authority)
        else:
            invariants += [report["status"] == "needs-manual", output is None, before_cache == after_cache,
                           not list(Path(view["bundle_path"]).rglob("*.pdf"))]
        row = {"case": label, "status": report["status"], **gates,
               "failed_rules": counts.get("failedRules"), "failed_assertions": counts.get("failedChecks"),
               "automatically_handled": view["counts"].get("automated_count", 0),
               "manual_pending_actionable": view["counts"].get("manual_pending_actionable", 0),
               "raw_manual_pending": view["counts"]["manual_pending"], "human_approvals": view["counts"]["manual_approved"],
               "auto_accepted_decisions": len(raw_automatic), "new_model_document_requests": requests,
               "model_cache_unchanged": before_cache == after_cache,
               "output_same_as_prior": bool(output and old_output and output["sha256"] == old_output["sha256"]),
               "pdf_published": bool(output), "source_unchanged": sha(before["source"]["path"]) == source_hash,
               "bundle_verified": verify_bundle(view["bundle_path"]), "ledger_human_review_bar_retained": ledger_refused,
               "complete_raw_review_export_retained": bool(preserved_review), "verification": view["verification"],
               "seconds": round(time.monotonic() - begin, 3), "peak_sampled_runner_descendant_rss_bytes": peak,
               "rss_limit_bytes": application.config.memory_limit_bytes, "rss_limit_exceeded": exceeded,
               "bundle_path": view["bundle_path"], "source_workspace": identifier, "result_workspace": result_id,
               "authorization_id": report.get("automatic_mode", {}).get("authorization", {}).get("authorization_id"),
               "invariants_pass": all(invariants), "warnings": current["result"].get("auto_fix", {}).get("warnings", [])}
        write_json(destination / "cases" / label / "report.json", report)
        write_json(destination / "cases" / label / "view.json", view)
        write_json(destination / "cases" / label / "workspace-snapshot.json", raw_state)
        write_json(destination / "cases" / label / "evidence.json", {"summary": row, "checks": invariants,
                   "published_pdf_independent_inspection": inspection, "export": exported,
                   "automatic_summary": current["result"].get("auto_fix"), "cache_before": before_cache, "cache_after": after_cache})
        rows.append(row); save_summary()
        print("RESULT " + json.dumps(row), flush=True)
        if output and label in {"published-book", "chapter-ai"}:
            page = 16 if label == "published-book" else 3
            png, context = destination / "visuals" / (label + ".png"), destination / "visuals" / (label + ".json")
            png.parent.mkdir(parents=True, exist_ok=True)
            render(output["path"], output["sha256"], page, png, context)
            visuals.append({"case": label, "page": page, "pdf_sha256": output["sha256"],
                            "png": str(png), "png_sha256": sha(png), "context": str(context),
                            "scope": "Developer visual inspection pending; all-page automated fidelity is separately recorded."})
        return result_id

    try:
        book_id = application.import_bundle(selected["published-book"]["bundle_path"])
        execute("published-book", book_id)
        chapter_id = application.import_bundle(selected["chapter-ai"]["bundle_path"])
        chapter_result = execute("chapter-ai", chapter_id, use_ai=True)
        execute("chapter-repeat", chapter_result)
        unsupported_id = application.import_bundle(selected["unsupported-form"]["bundle_path"])
        execute("unsupported-form", unsupported_id)
    except Exception as exc:
        write_json(destination / "trial-error.json", {"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        application.close()
        summary = save_summary(complete=len(rows) == 4)
        write_json(destination / "build-provenance.json", {"package_files_before": initial_code, "package_files_after": package_files(),
                   "implementation_digest_before": initial_digest, "implementation_digest_after": implementation_digest(RuntimeConfig()),
                   "sources_after": {path: sha(path) for path in originals}})
    return 0 if summary["all_case_invariants_pass"] and summary["implementation_unchanged"] and summary["originals_and_prior_evidence_unchanged"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/auto-fix/final-trial")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "work/af-final")
    parser.add_argument("--expected-digest")
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--include-images", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.data_dir, args.expected_digest, args.model, args.include_images))
