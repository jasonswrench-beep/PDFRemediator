"""Rule-set changes retain original evidence and never invent assertion fixes."""
import copy

import pytest

from pdf_remediator.validation_delta import compare_rules


def rule(clause, failures=1, details=None):
    listed = failures if details is None else details
    return {"rule_id": f"ISO 14289-1:2014:{clause}:1", "specification": "ISO 14289-1:2014",
            "clause": clause, "testNumber": "1", "status": "failed", "failedChecks": failures,
            "checks": [{"status": "failed", "context": f"context-{index}"} for index in range(listed)],
            "assertion_detail_coverage": {"status": "complete" if listed == failures else "partial",
                                          "declared_failed_assertions": failures,
                                          "listed_failed_checks": listed}}


def result(rules=(), fingerprint="a" * 64):
    failed = sum(item["failedChecks"] for item in rules)
    return {"status": "fail" if failed else "pass", "profile": "ua1", "version": "1.30.3",
            "is_compliant": not failed, "input_sha256": fingerprint,
            "execution": {"status": "completed", "returncode": 1 if failed else 0},
            "counts": {"passedRules": 106 - len(rules), "failedRules": len(rules),
                       "passedChecks": 200, "failedChecks": failed}, "failed_rules": list(rules)}


def ids(items):
    return [item["rule_id"] for item in items]


def test_rule_groups_preserve_ids_counts_and_full_original_rule_evidence():
    before = result([rule("7.1", 2), rule("7.2", 5)])
    after = result([rule("7.2", 1), rule("7.3", 3)], "b" * 64)
    original_before, original_after = copy.deepcopy(before), copy.deepcopy(after)
    delta = compare_rules(before, after)
    assert delta["status"] == "compared"
    assert ids(delta["fixed"]) == ["ISO 14289-1:2014:7.1:1"]
    assert ids(delta["remaining"]) == ["ISO 14289-1:2014:7.2:1"]
    assert ids(delta["newly_failing"]) == ["ISO 14289-1:2014:7.3:1"]
    assert delta["remaining"][0]["baseline_failed_checks"] == 5
    assert delta["remaining"][0]["final_failed_checks"] == 1
    assert delta["remaining"][0]["baseline_rule"] == before["failed_rules"][1]
    assert delta["baseline"]["counts"] == before["counts"]
    assert delta["final"]["counts"] == after["counts"]
    assert delta["coverage"]["assertion_identity_delta"] == "not-performed"
    assert before == original_before and after == original_after


def test_fewer_assertions_under_one_rule_does_not_claim_fixed_assertions():
    delta = compare_rules(result([rule("7.21.7", 9)]), result([rule("7.21.7", 1)], "b" * 64))
    assert delta["status"] == "compared"
    assert not delta["fixed"] and len(delta["remaining"]) == 1
    assert delta["rule_counts"] == {"fixed": 0, "remaining": 1, "newly_failing": 0}
    assert "assertions_fixed" not in delta


def test_partial_assertion_detail_retains_failed_rules_and_warns_about_identity_coverage():
    before = result([rule("7.1", 10050, details=3)])
    after = result([rule("7.1", 10010, details=1)], "b" * 64)
    delta = compare_rules(before, after)
    assert delta["status"] == "compared"
    assert delta["coverage"]["rule_inventory"] == "complete"
    assert delta["coverage"]["assertion_details"] == "partial-or-unknown"
    assert delta["warnings"] and not delta["fixed"]
    assert delta["baseline"]["counts"]["failedChecks"] == 10050
    assert delta["final"]["counts"]["failedChecks"] == 10010


def test_missing_assertion_details_are_unknown_instead_of_assumed_complete():
    before = result([rule("7.1", 4)])
    before["failed_rules"][0].pop("checks")
    before["failed_rules"][0].pop("assertion_detail_coverage")
    delta = compare_rules(before, result())
    assert delta["status"] == "compared" and len(delta["fixed"]) == 1
    assert delta["coverage"]["assertion_details"] == "partial-or-unknown"
    assert delta["warnings"]


@pytest.mark.parametrize("bad", [None, {}, {"status": "error"}, {"status": "unavailable"}, {"status": "not-run"}])
def test_unavailable_baseline_or_final_never_becomes_a_fixed_rule(bad):
    for before, after in ((bad, result()), (result([rule("7.1")]), bad)):
        delta = compare_rules(before, after)
        assert delta["status"] == "not-compared"
        assert not delta["fixed"] and not delta["remaining"] and not delta["newly_failing"]
        assert delta["reason"] and delta["warnings"]


@pytest.mark.parametrize("defect", ["rule-count", "assertion-count", "missing-rules", "duplicate-ids", "missing-id",
                                    "contradictory-id", "wrong-profile", "wrong-version", "unknown-version",
                                    "wrong-execution", "missing-hash", "bool-count", "more-details-than-count"])
def test_malformed_or_incomparable_evidence_fails_closed(defect):
    before, after = result([rule("7.1")]), result()
    if defect == "rule-count":
        before["counts"]["failedRules"] = 2
    elif defect == "assertion-count":
        before["counts"]["failedChecks"] = 100
    elif defect == "missing-rules":
        before["failed_rules"] = []
    elif defect == "duplicate-ids":
        before = result([rule("7.1"), rule("7.1")])
    elif defect == "missing-id":
        before["failed_rules"][0] = {"failedChecks": 1}
    elif defect == "contradictory-id":
        before["failed_rules"][0]["rule_id"] = "a-different-id"
    elif defect == "wrong-profile":
        after["profile"] = "2b"
    elif defect == "wrong-version":
        after["version"] = "another-version"
    elif defect == "unknown-version":
        before.pop("version")
    elif defect == "wrong-execution":
        before["execution"]["returncode"] = 0
    elif defect == "missing-hash":
        before.pop("input_sha256")
    elif defect == "bool-count":
        before["counts"]["failedChecks"] = True
    elif defect == "more-details-than-count":
        before["failed_rules"][0]["checks"].append({"status": "failed"})
    delta = compare_rules(before, after)
    assert delta["status"] == "not-compared"
    assert not delta["fixed"] and not delta["remaining"] and not delta["newly_failing"]


def test_two_real_pass_results_compare_as_no_failing_rules():
    delta = compare_rules(result(), result(fingerprint="b" * 64))
    assert delta["status"] == "compared"
    assert delta["rule_counts"] == {"fixed": 0, "remaining": 0, "newly_failing": 0}


def test_original_identifier_components_are_used_without_reformatting():
    before = result([rule("7.21.7")])
    before["failed_rules"][0].pop("rule_id")
    before["failed_rules"][0]["testNumber"] = "01"
    delta = compare_rules(before, result())
    assert ids(delta["fixed"]) == ["ISO 14289-1:2014:7.21.7:01"]


def test_xml_rule_count_attributes_remain_strings_in_original_evidence():
    before, after = result([rule("7.1", 2)]), result([rule("7.1", 1)])
    before["failed_rules"][0]["failedChecks"] = "2"
    after["failed_rules"][0]["failedChecks"] = "1"
    delta = compare_rules(before, after)
    assert delta["status"] == "compared"
    assert delta["remaining"][0]["baseline_failed_checks"] == 2
    assert delta["remaining"][0]["baseline_rule"]["failedChecks"] == "2"


@pytest.mark.parametrize("value", ["+1", " 1", "1.0", "1e0", "01", "-1"])
def test_noncanonical_rule_count_strings_do_not_produce_a_comparison(value):
    before = result([rule("7.1")])
    before["failed_rules"][0]["failedChecks"] = value
    assert compare_rules(before, result())["status"] == "not-compared"
