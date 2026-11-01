"""Reproducible product-API trial of the original Phase 0 synthetic corpus.

No fixture is generated or modified. The application creates isolated immutable
run bundles. Deliberate content loss and incorrect character mapping are also
compared with their known original controls, separately from standalone intake.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import traceback

PROJECT = Path(__file__).resolve().parents[1]
EVAL = PROJECT / "eval"
sys.path.insert(0, str(PROJECT / "src"))

from pdf_remediator.config import RuntimeConfig
from pdf_remediator.inspection import compare_fidelity, inspect_pdf
from pdf_remediator.pipeline import implementation_digest, process_file, sha, verify_bundle, write_json

SCHEMA = "phase1-product-corpus-1"


def code_files():
    package = PROJECT / "src/pdf_remediator"
    return {str(path.relative_to(PROJECT)).replace("\\", "/"): sha(path)
            for path in sorted(package.rglob("*")) if path.is_file() and path.suffix in {".py", ".json", ".tex", ".txt"}}


def selected_cases(manifest):
    items = [{"case": item["id"] + "__conservative", "fixture": item,
              "config": {}, "route": "conservative-defaults"} for item in manifest["fixtures"]]
    for case in items:
        declared = {"slides": "slides", "equation": "equations"}.get(case["fixture"]["id"])
        if declared:
            case["config"]["document_kind"] = declared
            case["input_declaration_provenance"] = "Explicit evaluation-fixture manifest classification supplied by the harness; not automatic content detection."
    by_id = {item["id"]: item for item in manifest["fixtures"]}
    items.extend([
        {"case": "scan_only__ocr_skip", "fixture": by_id["scan_only"], "config": {"ocr_mode": "skip"}, "route": "proven-one-page-scan-ocr-skip"},
        {"case": "mixed_same_page__ocr_redo", "fixture": by_id["mixed_same_page"], "config": {"ocr_mode": "redo"}, "route": "proven-one-page-mixed-ocr-redo"},
        {"case": "book_200__opt_in_regrouping", "fixture": by_id["book_200"], "config": {"allow_tag_regrouping": True}, "route": "explicit-semantic-regrouping-with-human-review"},
    ])
    return items


def linkage_pass(inspection):
    checks = {check["id"]: check.get("status") for check in inspection.get("checks", [])}
    return not inspection.get("error") and not inspection.get("structure", {}).get("phantom_tree", False) and all(
        checks.get(name) == "pass" for name in ("content-linkage", "content-coverage"))


def summarize_case(case, report, source, source_hash, before_code, after_code, raised=None):
    status = report.get("status", "harness-error")
    bundle = Path(report["bundle_path"]) if report.get("bundle_path") else None
    verified = verify_bundle(bundle) if bundle else False
    output = report.get("output")
    output_path = Path(output["path"]) if output else None
    published_paths = sorted(bundle.glob("*.pdf")) if bundle and bundle.is_dir() else []
    published = bool(published_paths)
    declared_output_exists = bool(output_path and output_path.is_file())
    inspections = {str(path): inspect_pdf(path) for path in published_paths}
    broken_output = any(not linkage_pass(value) for value in inspections.values())
    phantom_output = any(value.get("structure", {}).get("phantom_tree", False) for value in inspections.values())
    broken_count = sum(not linkage_pass(value) for value in inspections.values())
    phantom_count = sum(bool(value.get("structure", {}).get("phantom_tree", False)) for value in inspections.values())
    output_inventory_ok = published_paths == ([output_path] if declared_output_exists else [])
    gates = {name: report.get(name, {}).get("status", "not-run") for name in ("gate1", "gate2", "fidelity")}
    candidate = status == "candidate"
    counts = report.get("gate1", {}).get("counts", {})
    candidate_gates = not candidate or all(value == "pass" for value in gates.values())
    candidate_zero_failures = not candidate or counts.get("failedRules") == 0 and counts.get("failedChecks") == 0
    candidate_pdf = not candidate or bool(declared_output_exists and len(published_paths) == 1 and output_path.name == "candidate.pdf" and sha(output_path) == output["sha256"])
    no_pdf_on_fidelity_failure = gates["fidelity"] == "pass" or not published
    source_unchanged = sha(source) == source_hash
    code_unchanged = before_code == after_code
    failures = []
    for okay, code in [(verified, "bundle-verification"), (source_unchanged, "source-modified"),
                       (code_unchanged, "implementation-changed-during-case"), (candidate_gates, "candidate-gates-not-all-pass"),
                       (candidate_zero_failures, "candidate-validator-failure-count"), (candidate_pdf, "candidate-artifact-missing-or-hash-mismatch"),
                       (no_pdf_on_fidelity_failure, "pdf-published-with-failed-or-incomplete-fidelity"),
                       (not broken_output, "broken-structure-published"), (not phantom_output, "phantom-tree-published"),
                       (output_inventory_ok, "unreported-or-multiple-published-pdfs")]:
        if not okay:
            failures.append(code)
    if raised:
        failures.append("product-api-raised-outside-report")
    declaration_refused = case["config"].get("document_kind") not in {"slides", "equations"} or status == "needs-manual" and not published
    if not declaration_refused:
        failures.append("declared-unsupported-document-not-refused")
    row = {"case": case["case"], "fixture": case["fixture"]["id"], "route": case["route"],
           "source_sha256": source_hash, "status": status, **gates,
           "failed_rules": counts.get("failedRules"), "failed_assertions": counts.get("failedChecks"),
           "pdf_published": published, "pdf_name": ";".join(path.name for path in published_paths),
           "published_pdf_count": len(published_paths),
           "verify_bundle": verified, "candidate_gates_pass": candidate_gates,
           "candidate_validator_zero_failures": candidate_zero_failures,
           "candidate_artifact_valid": candidate_pdf,
           "no_pdf_when_fidelity_not_pass": no_pdf_on_fidelity_failure,
           "source_unchanged": source_unchanged, "code_unchanged_during_case": code_unchanged,
           "phantom_pdf_shipped": phantom_output, "broken_pdf_shipped": broken_output,
           "phantom_pdf_count": phantom_count, "broken_pdf_count": broken_count,
           "published_pdf_inventory_valid": output_inventory_ok,
           "declared_document_kind": case["config"].get("document_kind", "unknown"),
           "document_kind_declaration_provenance": case.get("input_declaration_provenance", ""),
           "declared_unsupported_refused": declaration_refused,
           "human_review_items_pending": sum(item.get("status") != "approved" for item in report.get("manual_review", {}).get("items", [])),
           "tag_regrouping_reviews_pending": sum(item.get("category") == "tag-regrouping" and item.get("status") != "approved" for item in report.get("manual_review", {}).get("items", [])),
           "seconds": report.get("timings", {}).get("total_seconds"), "bundle_path": str(bundle) if bundle else "",
           "implementation_digest": report.get("implementation_digest", ""),
           "invariants_pass": not failures, "invariant_failures": ";".join(failures),
           "error": str(report.get("error", {}).get("message", ""))}
    evidence = {"summary": row, "invariant_failures": failures, "raw_product_report": report,
                "published_artifacts_independent_inspection": inspections,
                "code_files_before": before_code, "code_files_after": after_code, "raised": raised}
    return row, evidence


def run(destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    manifest_path = EVAL / "corpus/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inputs = {item["id"]: EVAL / "corpus" / item["path"] for item in manifest["fixtures"]}
    before_sources = {key: sha(value) for key, value in inputs.items()}
    if any(before_sources[item["id"]] != item["sha256"] for item in manifest["fixtures"]):
        raise ValueError("An original corpus source differs from its read-only manifest")
    code_at_start, rows = code_files(), []
    started = time.monotonic()
    write_json(destination / "run-provenance.json", {"schema_version": SCHEMA, "started_utc": datetime.now(timezone.utc).isoformat(),
        "runner_sha256": sha(Path(__file__)), "source_manifest_sha256": sha(manifest_path),
        "code_files": code_at_start, "source_sha256": before_sources,
        "cases": [{"case": c["case"], "fixture": c["fixture"]["id"], "config_overrides": c["config"], "route": c["route"],
                   "input_declaration_provenance": c.get("input_declaration_provenance")} for c in selected_cases(manifest)],
        "policy": "Conservative defaults for all original fixtures; OCR and tag-regrouping routes are separate explicit cases. No real book run here."})
    for ordinal, case in enumerate(selected_cases(manifest), 1):
        source = inputs[case["fixture"]["id"]]
        before_code = code_files()
        config = RuntimeConfig(**case["config"])
        before_digest = implementation_digest(config)
        exception = None
        with (destination / "progress.jsonl").open("a", encoding="utf-8") as log:
            def progress(message):
                log.write(json.dumps({"case": case["case"], "message": message, "utc": datetime.now(timezone.utc).isoformat()}) + "\n")
                log.flush()
                print(case["case"] + ": " + message, flush=True)
            try:
                # Short per-case parents avoid a known native Windows CWD path
                # limit without shortening fixture names or losing provenance.
                report = process_file(source, destination / "r" / f"{ordinal:02d}", config, progress=progress)
            except Exception as exc:
                exception = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
                report = {"status": "harness-error", "error": exception}
        after_code = code_files()
        row, evidence = summarize_case(case, report, source, before_sources[case["fixture"]["id"]], before_code, after_code, exception)
        evidence["implementation_digest_before"] = before_digest
        evidence["implementation_digest_after"] = implementation_digest(config)
        write_json(destination / "observations" / (case["case"] + ".json"), evidence)
        rows.append(row)
        print("RESULT " + json.dumps(row), flush=True)
        write_summary(destination, rows, before_sources, inputs, code_at_start, started, complete=False)
    comparisons = []
    for item in manifest["fixtures"]:
        reference = item.get("expected", {}).get("comparison_reference")
        if not reference:
            continue
        result = compare_fidelity(EVAL / "corpus" / reference, inputs[item["id"]])
        write_json(destination / "known-reference-comparisons" / (item["id"] + ".json"), result)
        render_statuses = sorted({p.get("render_status") for p in result.get("pages", [])})
        reference_expected = result["status"] == "fail" and result.get("text", {}).get("multiset_status") == "fail" and (
            "fail" in render_statuses if item["id"] == "content_loss" else render_statuses == ["pass"])
        comparisons.append({"fixture": item["id"], "reference": reference, "status": result["status"],
            "text_status": result.get("text", {}).get("multiset_status"),
            "render_statuses": render_statuses, "known_reference_expectation_pass": reference_expected,
            "scope": "Known original-to-damaged-fixture comparison; standalone intake cannot infer an unavailable original."})
    summary = write_summary(destination, rows, before_sources, inputs, code_at_start, started, complete=True, comparisons=comparisons)
    return 0 if summary["all_release_invariants_pass"] and summary["source_sha256_unchanged"] and not summary["code_changed_overall"] and summary["known_reference_expectations_pass"] else 1


def write_summary(destination, rows, before_sources, inputs, code_at_start, started, complete, comparisons=None):
    after_sources = {key: sha(value) for key, value in inputs.items()}
    summary = {"schema_version": SCHEMA, "complete": complete, "cases_completed": len(rows), "expected_cases": 18,
        "status_counts": dict(Counter(row["status"] for row in rows)), "cases": rows,
        "all_release_invariants_pass": all(row["invariants_pass"] for row in rows),
        "source_sha256_unchanged": before_sources == after_sources,
        "source_sha256_before": before_sources, "source_sha256_after": after_sources,
        "verified_bundles": sum(row["verify_bundle"] for row in rows),
        "published_pdfs": sum(row["published_pdf_count"] for row in rows),
        "candidates_with_all_gates_passed": sum(row["status"] == "candidate" and row["candidate_gates_pass"] and row["candidate_validator_zero_failures"] and row["candidate_artifact_valid"] for row in rows),
        "phantom_pdfs_shipped": sum(row["phantom_pdf_count"] for row in rows),
        "broken_pdfs_shipped": sum(row["broken_pdf_count"] for row in rows),
        "pdfs_shipped_without_fidelity_pass": sum(row["published_pdf_count"] for row in rows if not row["no_pdf_when_fidelity_not_pass"]),
        "code_changed_overall": code_at_start != code_files(),
        "known_reference_comparisons": comparisons or [],
        "known_reference_expectations_pass": len(comparisons or []) == 2 and all(item["known_reference_expectation_pass"] for item in comparisons),
        "seconds": round(time.monotonic() - started, 4),
        "limitations": ["A candidate is pending human review, never verified by this trial.",
            "Standalone processing preserves the supplied file; missing content relative to an unavailable original cannot be inferred.",
            "Slides and visually positioned equations remain outside reliable automatic detection; their fixture outcomes are observations, not a claim of general support.",
            "Reports, validator evidence and optional review drafts reside in separately verified immutable per-case bundles; caches/diagnostics are not publication artifacts."]}
    write_json(destination / "summary.json", summary)
    if rows:
        with (destination / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "output/phase1/corpus-trial", help="Fresh destination; existing evidence is never overwritten")
    arguments = parser.parse_args()
    raise SystemExit(run(arguments.output))
