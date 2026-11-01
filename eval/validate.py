"""Fail-closed standalone veraPDF CLI adapter for the Phase 0 comparison.

No Java library bundled with a competing engine is substituted for this CLI.
The official installed launcher is accepted as an explicit path; its Java
classpath invocation is reproduced without using cmd.exe or a shell.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

SCHEMA_VERSION = "phase0.verapdf.2"
PINNED_VERSION = "1.30.3"
COUNT_KEYS = ("passedRules", "failedRules", "passedChecks", "failedChecks")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_value(element: ET.Element):
    """Preserve all rule/check attributes, contexts, errors and arguments."""
    value = dict(element.attrib)
    for child in element:
        name = _local(child.tag)
        item = _xml_value(child)
        if name in value:
            if not isinstance(value[name], list):
                value[name] = [value[name]]
            value[name].append(item)
        else:
            value[name] = item
    content = (element.text or "").strip()
    if not value:
        return content
    if content:
        value["text"] = content
    return value


def _count(value, name: str) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise ValueError(f"Missing or invalid {name}: {value!r}")
    return int(value)


def _truth(value) -> bool:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError(f"Missing or invalid isCompliant: {value!r}")


def _list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _finish_report(profile, compliant, details, rules, builds, batch, report_count=1,
                   job_end_status=None):
    if report_count != 1:
        raise ValueError(f"Expected one validation report, found {report_count}")
    if job_end_status != "normal":
        raise ValueError(f"Validation job did not finish normally: {job_end_status!r}")
    if not re.fullmatch(r"PDF/UA-1(?: validation profile)?", str(profile), re.I):
        raise ValueError(f"Unexpected validation profile: {profile!r}")
    counts = {name: _count(details.get(name), name) for name in COUNT_KEYS}
    if not isinstance(batch, dict):
        raise ValueError("Missing batchSummary")
    if _count(batch.get("totalJobs"), "totalJobs") != 1:
        raise ValueError("Expected exactly one validation job")
    for name in ("failedToParse", "encrypted", "outOfMemory", "veraExceptions"):
        if _count(batch.get(name), name):
            raise ValueError(f"Validator batch execution error: {name}={batch[name]}")
    summary = batch.get("validationReports")
    if not isinstance(summary, dict) or _count(summary.get("failedJobs"), "failedJobs"):
        raise ValueError("Missing validation job summary or failed validation job")
    is_compliant = _truth(compliant)
    if any(not isinstance(rule, dict) for rule in rules):
        raise ValueError("Invalid validation rule entry")
    failures = [dict(rule) for rule in rules if str(rule.get("status", "")).lower() == "failed"]
    if len(failures) != counts["failedRules"]:
        raise ValueError("Failed-rule count disagrees with listed rules")
    listed_checks = sum(_count(rule.get("failedChecks"), "rule.failedChecks") for rule in failures)
    if listed_checks != counts["failedChecks"]:
        raise ValueError("Failed-check count disagrees with listed rules")
    listed_failed_check_count = 0
    detail_gaps = []
    for rule in failures:
        checks = _list(rule.get("checks", rule.get("check")))
        failed_checks = [check for check in checks if isinstance(check, dict)
                         and check.get("status") == "failed"]
        declared_count = _count(rule.get("failedChecks"), "rule.failedChecks")
        if len(failed_checks) > declared_count:
            raise ValueError("Listed failed-check details exceed the declared assertion count")
        rule["checks"] = failed_checks
        rule["rule_id"] = ":".join(str(rule.get(key, "")) for key in
                                   ("specification", "clause", "testNumber"))
        complete = len(failed_checks) == declared_count
        rule["assertion_detail_coverage"] = {
            "status": "complete" if complete else "partial",
            "declared_failed_assertions": declared_count,
            "listed_failed_checks": len(failed_checks),
            "assertions_without_separate_listed_detail": declared_count - len(failed_checks),
        }
        listed_failed_check_count += len(failed_checks)
        if not complete:
            detail_gaps.append({"rule_id": rule["rule_id"], **rule["assertion_detail_coverage"]})
    if is_compliant != (counts["failedRules"] == 0 and counts["failedChecks"] == 0):
        raise ValueError("Compliance flag and rule/check counts disagree")
    for name, expected in (("compliant", int(is_compliant)), ("nonCompliant", int(not is_compliant))):
        if _count(summary.get(name), name) != expected:
            raise ValueError("Batch compliance summary disagrees with job")
    coverage = {
        "status": "partial" if detail_gaps else "complete",
        "declared_failed_assertions": counts["failedChecks"],
        "listed_failed_checks": listed_failed_check_count,
        "assertions_without_separate_listed_detail": counts["failedChecks"] - listed_failed_check_count,
        "affected_rules": detail_gaps,
        "cause": "unverified: the validator may deduplicate context records or omit detail" if detail_gaps else None,
    }
    if (detail_gaps and listed_failed_check_count >= 10000 and builds
            and all(isinstance(build, dict) and build.get("version") == "1.30.3" for build in builds)):
        coverage["cause"] = ("Known veraPDF 1.30.3 internal global detail cap: after more than 10,000 "
                             "stored assertion records, further failed details are omitted except the first failure of a rule. "
                             "Counts continue increasing; omitted assertion identities are unavailable.")
        coverage["cause_evidence"] = "Pinned CLI BaseValidator.processAssertionResult bytecode, tools/validator-BaseValidator.javap.txt"
    warnings = (["The report declares more failed assertions than separately listed failed-check details. "
                 "All reported counts and listed details are retained; completeness of per-assertion detail is not established. "
                 "This remains a failed validation and cannot be a pass."] if detail_gaps else [])
    return {
        "status": "pass" if is_compliant else "fail",
        "profile": "ua1", "profile_name": profile, "is_compliant": is_compliant,
        "counts": counts, "failed_rules": failures, "build_information": builds,
        "batch_summary": batch, "job_end_status": job_end_status,
        "assertion_detail_coverage": coverage, "warnings": warnings,
    }


def parse_xml_report(path: str | Path) -> dict:
    """Parse veraPDF 1.24+ machine-readable XML, requiring complete evidence."""
    root = ET.parse(path).getroot()
    if _local(root.tag) != "report":
        raise ValueError("Expected veraPDF report root")
    jobs = [node for node in root.iter() if _local(node.tag) == "job"]
    reports = [node for node in root.iter() if _local(node.tag) == "validationReport"]
    if len(jobs) != 1 or len(reports) != 1:
        raise ValueError(f"Expected one job/report, found {len(jobs)}/{len(reports)}")
    report = reports[0]
    details = next((node for node in report if _local(node.tag) == "details"), None)
    if details is None:
        raise ValueError("Missing validation details")
    builds = [_xml_value(node) for node in root.iter() if _local(node.tag) == "releaseDetails"]
    batch = next((node for node in root if _local(node.tag) == "batchSummary"), None)
    if batch is None:
        raise ValueError("Missing batchSummary")
    rules = [_xml_value(node) for node in details if _local(node.tag) == "rule"]
    result = _finish_report(report.get("profileName"), report.get("isCompliant"),
                            details.attrib, rules, builds, _xml_value(batch),
                            job_end_status=report.get("jobEndStatus"))
    items = [_xml_value(node) for node in jobs[0] if _local(node.tag) == "item"]
    if len(items) != 1:
        raise ValueError("Missing or ambiguous validation input item")
    result["item"] = items[0]
    return result


def parse_json_report(path: str | Path) -> dict:
    """Parse the CLI JSON report. Unknown layouts fail instead of guessing pass."""
    with Path(path).open(encoding="utf-8-sig") as stream:
        data = json.load(stream)
    root = data.get("report", data) if isinstance(data, dict) else None
    if not isinstance(root, dict):
        raise ValueError("Expected veraPDF JSON report object")
    jobs = root.get("jobs")
    if isinstance(jobs, dict):
        jobs = jobs.get("job")
    jobs = _list(jobs)
    if len(jobs) != 1 or not isinstance(jobs[0], dict):
        raise ValueError("Expected one JSON validation job")
    reports = _list(jobs[0].get("validationResult", jobs[0].get("validationReport")))
    if len(reports) != 1 or not isinstance(reports[0], dict):
        raise ValueError("Expected one JSON validationReport")
    report = reports[0]
    details = report.get("details")
    if not isinstance(details, dict):
        raise ValueError("Missing JSON validation details")
    rules = _list(details.get("ruleSummaries", details.get("rule", details.get("rules"))))
    if any(not isinstance(rule, dict) for rule in rules):
        raise ValueError("Invalid JSON rule list")
    info = root.get("buildInformation", {})
    builds = _list(info.get("releaseDetails")) if isinstance(info, dict) else []
    raw_batch = root.get("batchSummary")
    if not isinstance(raw_batch, dict):
        raise ValueError("Missing JSON batchSummary")
    if "validationSummary" in raw_batch:
        summary = raw_batch["validationSummary"]
        batch = {"totalJobs": raw_batch.get("totalJobs"),
                 "failedToParse": raw_batch.get("failedParsingJobs"),
                 "encrypted": raw_batch.get("failedEncryptedJobs"),
                 "outOfMemory": raw_batch.get("outOfMemory"),
                 "veraExceptions": raw_batch.get("veraExceptions"),
                 "validationReports": {
                     "compliant": summary.get("compliantPdfaCount"),
                     "nonCompliant": summary.get("nonCompliantPdfaCount"),
                     "failedJobs": summary.get("failedJobCount")}}
    else:
        batch = raw_batch
    result = _finish_report(report.get("profileName"), report.get("compliant", report.get("isCompliant")),
                            details, rules, builds, batch,
                            job_end_status=report.get("jobEndStatus"))
    result["raw_batch_summary"] = raw_batch
    result["item"] = jobs[0].get("itemDetails", jobs[0].get("item"))
    return result


def _launch(cli: Path, java_home: Path | None, heap_mb: int):
    env = os.environ.copy()
    # Inherited Java switches are not part of the pinned validator configuration.
    for name in ("JAVA_OPTS", "JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS"):
        env.pop(name, None)
    if java_home:
        java = java_home / "bin" / ("java.exe" if os.name == "nt" else "java")
        env["JAVA_HOME"] = str(java_home)
    else:
        found = shutil.which("java")
        if not found:
            raise FileNotFoundError("Java is unavailable; set java_home explicitly")
        java = Path(found).resolve()
    if not java.is_file():
        raise FileNotFoundError(f"Java executable not found: {java}")
    options = [str(java), f"-Xmx{heap_mb}m", "-Dfile.encoding=UTF8"]
    if cli.suffix.lower() == ".jar":
        return options + ["-jar", str(cli)], env, "explicit-cli-jar"
    if cli.name.lower() in ("verapdf", "verapdf.bat", "verapdf.cmd"):
        install = cli.parent
        if not list((install / "bin").glob("*.jar")):
            raise FileNotFoundError(f"Installed standalone CLI jars missing under {install / 'bin'}")
        # Equivalent to the pinned official launcher, avoiding its shell and
        # its JAVACMD/PATH selection. This is still the installed standalone CLI.
        options += ["-XX:+IgnoreUnrecognizedVMOptions",
                    "--add-exports=java.base/sun.security.pkcs=ALL-UNNAMED",
                    f"-Dapp.repo={install / 'bin'}", f"-Dapp.home={install}",
                    f"-Dbasedir={install}", "-classpath",
                    os.pathsep.join((str(install / "etc"), str(install / "bin" / "*"))),
                    "org.verapdf.apps.GreenfieldCliWrapper"]
        return options, env, "official-launcher-equivalent-java"
    # Executable launchers can still be used, with the chosen Java pinned by
    # JAVACMD and PATH. Arbitrary .bat/.cmd files are deliberately unsupported.
    if cli.suffix.lower() in (".bat", ".cmd"):
        raise ValueError("Use the official installed verapdf.bat or a standalone CLI jar")
    env["JAVACMD"] = str(java)
    env["JAVA_OPTS"] = f"-Xmx{heap_mb}m"
    env["PATH"] = str(java.parent) + os.pathsep + env.get("PATH", "")
    return [str(cli)], env, "explicit-executable"


def _tool_artifacts(cli: Path) -> list[dict]:
    jars = [cli] if cli.suffix.lower() == ".jar" else sorted((cli.parent / "bin").glob("*.jar"))
    artifacts = []
    for jar in jars:
        artifact = {"path": str(jar), "sha256": sha256(jar)}
        with zipfile.ZipFile(jar) as archive:
            entry = "org/verapdf/pdfa/validation/PDFUA-1.xml"
            if entry in archive.namelist():
                artifact["profile_entry"] = entry
                artifact["profile_sha256"] = hashlib.sha256(archive.read(entry)).hexdigest()
        artifacts.append(artifact)
    return artifacts


def _run(command: list[str], env: dict, output: Path, errors: Path,
         timeout_seconds: float, cwd: Path) -> dict:
    started = time.monotonic()
    with output.open("wb") as stdout, errors.open("wb") as stderr:
        try:
            process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                       env=env, cwd=cwd, shell=False)
        except OSError as exc:
            return {"status": "unavailable", "returncode": None, "error": str(exc),
                    "elapsed_seconds": time.monotonic() - started}
        try:
            code = process.wait(timeout=timeout_seconds)
            # veraPDF's official INVALID(1) means validation completed with
            # conformance failures. Report consistency is checked by the caller.
            status = "completed" if code in (0, 1) else "failed"
        except subprocess.TimeoutExpired:
            # The supported Java launches use one JVM and --processes 1.
            process.kill()
            process.wait(timeout=10)
            code, status = process.returncode, "timeout"
        return {"status": status, "returncode": code,
                "elapsed_seconds": round(time.monotonic() - started, 6)}


def validate_pdf(pdf_path: str | Path, output_dir: str | Path,
                 cli_path: str | Path, java_home: str | Path | None = None,
                 timeout_seconds: float = 180, report_format: str = "xml",
                 expected_version: str = PINNED_VERSION, heap_mb: int = 2048) -> dict:
    """Validate one exact PDF, preserving raw evidence and an explicit status.

    Use a distinct output directory for each evaluated artifact. Existing raw
    reports are refused, so a stale report can never satisfy a failed new run.
    Version probes have their own 30-second (or smaller) timeout. `pass` requires
    successful execution, the pinned version, UA-1 and zero failed rules/checks.
    """
    if report_format not in ("xml", "json"):
        raise ValueError("report_format must be xml or json")
    if timeout_seconds <= 0 or not 64 <= heap_mb <= 16384:
        raise ValueError("Invalid timeout or Java heap limit")
    pdf = Path(pdf_path).resolve()
    cli = Path(cli_path).resolve()
    destination = Path(output_dir).resolve()
    home = Path(java_home).resolve() if java_home else None
    destination.mkdir(parents=True, exist_ok=True)
    report = destination / f"{pdf.stem}.verapdf.{report_format}"
    stderr = destination / f"{pdf.stem}.verapdf.stderr.txt"
    version_file = destination / f"{pdf.stem}.verapdf.version.txt"
    version_errors = destination / f"{pdf.stem}.verapdf.version.stderr.txt"
    summary = destination / f"{pdf.stem}.verapdf.summary.json"
    if any(path.exists() for path in (report, stderr, version_file, version_errors, summary)):
        raise FileExistsError(f"Refusing to overwrite validation evidence under {destination}")
    result = {"schema_version": SCHEMA_VERSION, "validator": "standalone-verapdf-cli",
              "status": "error", "profile": "ua1", "expected_version": expected_version,
              "input": str(pdf), "input_sha256": None, "cli_path": str(cli),
              "java_home": str(home) if home else None, "timeout_seconds": timeout_seconds,
              "java_heap_limit_mb": heap_mb, "java_heap_is_not_process_memory_limit": True,
              "raw_report": str(report), "stderr": str(stderr),
              "version_output": str(version_file), "summary_path": str(summary),
              "execution": {"status": "not-run", "returncode": None}}
    try:
        if not pdf.is_file() or not cli.is_file():
            raise FileNotFoundError("Input PDF or explicit standalone CLI does not exist")
        result["input_sha256"] = sha256(pdf)
        result["cli_sha256"] = sha256(cli)
        result["tool_artifacts"] = _tool_artifacts(cli)
        command, env, launch_mode = _launch(cli, home, heap_mb)
        result["launch_mode"] = launch_mode
        result["version_probe"] = _run(command + ["--version"], env, version_file,
                                       version_errors, min(timeout_seconds, 30), destination)
        version_text = version_file.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"veraPDF\s+(\d+\.\d+\.\d+(?:[-\w.]*)?)", version_text, re.I)
        result["version"] = match.group(1) if match else None
        if result["version_probe"]["status"] != "completed" or result["version_probe"]["returncode"] != 0:
            raise RuntimeError("Validator version probe did not complete successfully")
        if result["version"] != expected_version:
            raise ValueError(f"Expected veraPDF {expected_version}, got {result['version']!r}")
        command += ["--flavour", "ua1", "--format", report_format,
                    "--maxfailures", "-1", "--maxfailuresdisplayed", "-1",
                    "--processes", "1", str(pdf)]
        result["command"] = command
        result["execution"] = _run(command, env, report, stderr, timeout_seconds, destination)
        if report.exists():
            result["raw_report_sha256"] = sha256(report)
            result["raw_report_bytes"] = report.stat().st_size
        if result["execution"]["status"] != "completed":
            raise RuntimeError(f"Validator execution {result['execution']['status']}")
        if not report.is_file() or report.stat().st_size == 0:
            raise ValueError("Validator produced no report")
        if report.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("Report exceeds the 256 MiB parser limit; raw evidence retained")
        parsed = parse_xml_report(report) if report_format == "xml" else parse_json_report(report)
        builds = parsed["build_information"]
        if not builds or any(not isinstance(build, dict) or build.get("version") != expected_version
                             for build in builds):
            raise ValueError("Report does not identify the pinned validator build")
        expected_code = 0 if parsed["status"] == "pass" else 1
        if result["execution"]["returncode"] != expected_code:
            raise ValueError("Validator return code and report compliance disagree")
        item = parsed.get("item")
        if not isinstance(item, dict) or Path(item.get("name", "")).resolve() != pdf:
            raise ValueError("Report input item does not match the selected PDF")
        if sha256(pdf) != result["input_sha256"]:
            raise ValueError("Input PDF changed during validation")
        result.update(parsed)
    except (OSError, ValueError, RuntimeError, ET.ParseError, TypeError, KeyError,
            AttributeError, zipfile.BadZipFile) as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    summary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def refresh_saved_summary(summary_path: str | Path) -> dict:
    """Reparse unchanged saved evidence, preserving the exact previous summary.

    This never invokes Java or reruns an engine. Version, input/report hashes,
    process status and report consistency are verified before replacing only the
    parsed summary. The backup and change attribution remain beside it.
    """
    path = Path(summary_path).resolve()
    old_bytes = path.read_bytes()
    old = json.loads(old_bytes)
    raw = Path(old["raw_report"]).resolve()
    pdf = Path(old["input"]).resolve()
    expected_version = old["expected_version"]
    if old.get("version") != expected_version:
        raise ValueError("Saved validator version does not match the pinned version")
    if old.get("execution", {}).get("status") != "completed":
        raise ValueError("Cannot refresh an incomplete validator execution")
    if old.get("raw_report_sha256") != sha256(raw) or old.get("input_sha256") != sha256(pdf):
        raise ValueError("Saved raw report or PDF changed; summary-only refresh refused")
    parsed = parse_json_report(raw) if raw.suffix.lower() == ".json" else parse_xml_report(raw)
    if not parsed["build_information"] or any(build.get("version") != expected_version
                                               for build in parsed["build_information"]):
        raise ValueError("Saved report build information is not pinned")
    expected_code = 0 if parsed["status"] == "pass" else 1
    if old["execution"]["returncode"] != expected_code:
        raise ValueError("Saved exit code disagrees with parsed compliance")
    item = parsed.get("item")
    if not isinstance(item, dict) or Path(item.get("name", "")).resolve() != pdf:
        raise ValueError("Saved report input item does not match the PDF")
    backup = path.with_name(path.name + ".pre-detail-coverage-fix")
    if backup.exists():
        raise FileExistsError(f"Prior summary backup already exists: {backup}")
    updated = dict(old)
    updated.pop("error", None)
    updated.update(parsed)
    updated["schema_version"] = SCHEMA_VERSION
    updated["summary_reparse"] = {
        "reason": "Separate aggregate assertion failures from listed assertion-detail coverage",
        "previous_summary": str(backup), "previous_summary_sha256": hashlib.sha256(old_bytes).hexdigest(),
        "adapter_sha256": sha256(Path(__file__)), "validator_executed_again": False,
        "raw_report_unchanged": True, "input_unchanged": True,
    }
    backup.write_bytes(old_bytes)
    path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--java-home", type=Path)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--format", choices=("xml", "json"), default="xml")
    parser.add_argument("--expected-version", default=PINNED_VERSION)
    parser.add_argument("--heap-mb", type=int, default=2048)
    args = parser.parse_args()
    result = validate_pdf(args.pdf, args.output_dir, args.cli, args.java_home,
                          args.timeout, args.format, args.expected_version, args.heap_mb)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return {"pass": 0, "fail": 1, "error": 2}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
