"""Compare validator rule failures without inventing assertion identities.

This is evidence about rule sets, not a new accessibility gate or a count of
repaired assertions. Counts can change within one still-failing rule without
revealing which original assertion remains.
"""
from __future__ import annotations

import copy
import re

SCHEMA_VERSION = "phase1-validator-rule-delta-1"
COUNT_NAMES = ("passedRules", "failedRules", "passedChecks", "failedChecks")


def _count(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} is not a nonnegative integer")
    return value


def _rule_count(value, label):
    # XML attribute values remain original strings in full rule evidence.
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        return int(value)
    return _count(value, label)


def _rule_id(rule):
    explicit = rule.get("rule_id")
    names = ("specification", "clause", "testNumber")
    if isinstance(explicit, str) and explicit.strip():
        if all(rule.get(name) is not None for name in names) and explicit != ":".join(str(rule[name]) for name in names):
            raise ValueError("Original rule identifiers contradict one another")
        return explicit
    if any(rule.get(name) is None or not str(rule[name]).strip() for name in names):
        raise ValueError("A failed rule has no complete original identifier")
    return ":".join(str(rule[name]) for name in names)


def _inventory(report, label):
    if not isinstance(report, dict) or report.get("status") not in ("pass", "fail"):
        raise ValueError(f"{label} validator result is unavailable, not run, or an error")
    if report.get("profile") != "ua1":
        raise ValueError(f"{label} does not use the explicit PDF/UA-1 profile")
    fingerprint = report.get("input_sha256")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
        raise ValueError(f"{label} is not bound to an exact PDF fingerprint")
    counts = report.get("counts")
    if not isinstance(counts, dict):
        raise ValueError(f"{label} aggregate counts are missing")
    counts = {name: _count(counts.get(name), f"{label}.{name}") for name in COUNT_NAMES}
    passing = counts["failedRules"] == 0 and counts["failedChecks"] == 0
    if passing != (report["status"] == "pass") or report.get("is_compliant") is not passing:
        raise ValueError(f"{label} counts and validation result contradict one another")
    if (counts["passedRules"] + counts["failedRules"]) == 0:
        raise ValueError(f"{label} has no validated rule coverage")
    execution = report.get("execution")
    if not isinstance(execution, dict) or execution.get("status") != "completed" or execution.get("returncode") != (0 if passing else 1):
        raise ValueError(f"{label} validator execution was not a successful completed validation")
    failures = report.get("failed_rules")
    if not isinstance(failures, list) or len(failures) != counts["failedRules"]:
        raise ValueError(f"{label} failed-rule inventory is incomplete")
    inventory, partial = {}, []
    for rule in failures:
        if not isinstance(rule, dict):
            raise ValueError(f"{label} has a malformed failed rule")
        ident = _rule_id(rule)
        if ident in inventory:
            raise ValueError(f"{label} has duplicate failed-rule identifiers")
        failed_checks = _rule_count(rule.get("failedChecks"), f"{label}.{ident}.failedChecks")
        if failed_checks == 0:
            raise ValueError(f"{label} failed rule declares zero failed assertions")
        coverage = rule.get("assertion_detail_coverage", {})
        if not isinstance(coverage, dict):
            raise ValueError(f"{label} has malformed assertion-detail coverage")
        checks = rule.get("checks")
        listed = len([check for check in checks if isinstance(check, dict) and check.get("status") == "failed"]) if isinstance(checks, list) else None
        if listed is not None and listed > failed_checks:
            raise ValueError(f"{label} lists more failures than its aggregate assertion count")
        declared_listed = coverage.get("listed_failed_checks")
        if declared_listed is not None:
            declared_listed = _count(declared_listed, f"{label}.{ident}.listed_failed_checks")
            if declared_listed > failed_checks or (listed is not None and listed != declared_listed):
                raise ValueError(f"{label} assertion-detail counts contradict one another")
        # Absence of assertion records is unknown coverage, never complete.
        complete = listed == failed_checks and coverage.get("status") in (None, "complete")
        if not complete:
            partial.append(ident)
        inventory[ident] = {"rule_id": ident, "failed_checks": failed_checks,
                            "original_rule": copy.deepcopy(rule),
                            "assertion_details": "complete" if complete else "partial-or-unknown"}
    if sum(rule["failed_checks"] for rule in inventory.values()) != counts["failedChecks"]:
        raise ValueError(f"{label} failed-rule assertion totals contradict aggregate counts")
    top_coverage = report.get("assertion_detail_coverage", {})
    top_partial = isinstance(top_coverage, dict) and top_coverage.get("status") not in (None, "complete")
    return inventory, partial, top_partial


def _evidence(report):
    if not isinstance(report, dict):
        return {"status": "unavailable", "counts": None}
    return {key: copy.deepcopy(report.get(key)) for key in
            ("status", "profile", "profile_name", "version", "expected_version", "input_sha256",
             "counts", "assertion_detail_coverage", "raw_report", "warnings")}


def compare_rules(baseline, final):
    """Return fixed/remaining/newly-failing RULE IDs, or not-compared evidence.

    Incomplete assertion details do not erase declared failures. Incomplete rule
    identities or contradictory counts prevent comparison entirely, so missing
    evidence cannot be misreported as repaired rules.
    """
    result = {"schema_version": SCHEMA_VERSION, "status": "not-compared",
              "comparison_unit": "validator-rule-id", "baseline": _evidence(baseline),
              "final": _evidence(final), "fixed": [], "remaining": [], "newly_failing": [],
              "warnings": [], "coverage": {"rule_inventory": "not-compared", "assertion_identity_delta": "not-performed"},
              "limitations": "Rule disappearance means that rule no longer failed in the final validation. It does not identify individual repaired assertions or establish semantic accessibility."}
    try:
        before, before_partial, before_top_partial = _inventory(baseline, "baseline")
        after, after_partial, after_top_partial = _inventory(final, "final")
        before_version = baseline.get("version") or baseline.get("expected_version")
        after_version = final.get("version") or final.get("expected_version")
        if not isinstance(before_version, str) or not before_version or before_version != after_version:
            raise ValueError("Validator versions differ or one version is missing")
        for ident in sorted(set(before) | set(after)):
            previous, current = before.get(ident), after.get(ident)
            group = "remaining" if previous and current else "fixed" if previous else "newly_failing"
            result[group].append({"rule_id": ident,
                                  "baseline_failed_checks": previous["failed_checks"] if previous else 0,
                                  "final_failed_checks": current["failed_checks"] if current else 0,
                                  "baseline_rule": previous["original_rule"] if previous else None,
                                  "final_rule": current["original_rule"] if current else None})
        partial = bool(before_partial or after_partial or before_top_partial or after_top_partial)
        result["coverage"] = {"rule_inventory": "complete", "assertion_details": "partial-or-unknown" if partial else "complete",
                              "baseline_partial_rule_ids": before_partial, "final_partial_rule_ids": after_partial,
                              "assertion_identity_delta": "not-performed"}
        if partial:
            result["warnings"].append("Assertion details are partial or unknown. Declared failed-rule and failed-assertion counts are retained; comparison is limited to complete rule inventories. Missing assertion records are not passes or fixed assertions.")
        result["status"] = "compared"
        result["rule_counts"] = {"fixed": len(result["fixed"]), "remaining": len(result["remaining"]), "newly_failing": len(result["newly_failing"])}
    except (ValueError, TypeError, KeyError) as exc:
        result["reason"] = str(exc)
        result["fixed"], result["remaining"], result["newly_failing"] = [], [], []
        result["warnings"].append("Validator rule changes were not compared; missing or inconsistent evidence cannot establish a repair.")
    return result
