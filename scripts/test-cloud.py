"""Run an exact source-only contract subset; this is not native release testing.

Every selected test constructs synthetic PDF/report fixtures at runtime. No
eval/corpus, historical run, Java, OCR engine, model, or external network is
required. Node.js 20+ is required for the shipped browser-script tests, which
use named DOM/HTTP doubles and open no browser. Assistance protocol tests bind
only loopback HTTP test doubles; they do not call a real model service.
The pinned Python packages still include PDF libraries with platform wheels.
Excluded modules are tests/test_native_tools.py (actual pinned native JAR) and
tests/test_fonts.py (licensed embedded Type1 programs); they are not skipped or
claimed as passing by this runner.
"""
from pathlib import Path
import os
import subprocess
import sys
import uuid


TEST_PATHS = (
    "tests/test_heading_checks.py",
    "tests/test_language.py",
    "tests/test_contrast.py",
    "tests/test_structural_fixes.py",
    "tests/test_lms_checker_pipeline.py",
    "tests/test_pipeline.py",
    "tests/test_adapters.py",
    "tests/test_web.py",
    "tests/test_web_assets.py",
    "tests/test_launcher.py",
    "tests/test_doctor_readiness.py",
    "tests/test_startup_errors.py",
    "tests/test_cancelled_status.py",
    "tests/test_applied_ai_provenance.py",
    "tests/test_rejected_post_transport.py",
    "tests/test_reference_policy.py",
    "tests/test_assistance.py",
    "tests/test_auto_decisions.py",
    "tests/test_autofix_web.py",
    "tests/test_cache_provenance.py",
    "tests/test_review_checkpoint.py",
    "tests/test_review.py",
    "tests/test_workspace.py",
    "tests/test_validation_delta.py",
    "tests/test_preservation.py",
    "tests/test_source_update.py",
    "tests/test_serve_logging.py",
    "tests/test_review_lifecycle_trial.py",
    "eval/test_validate.py",
    "eval/test_metrics.py",
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").is_file() or not (root / "src/pdf_remediator").is_dir():
        raise SystemExit("Run this script from a complete PDF Remediator source checkout.")
    missing = [name for name in TEST_PATHS if not (root / name).is_file()]
    if missing:
        raise SystemExit("Missing required contract tests: " + ", ".join(missing))
    environment = os.environ.copy()
    # Resolve this checkout even when another checkout has an editable install.
    # Keep inherited PYTHONPATH out of the source-only test boundary.
    environment["PYTHONPATH"] = str(root / "src")
    work = root / "work"
    work.mkdir(exist_ok=True)
    # Use a fresh checkout-local location: some Windows sandbox temp roots
    # reject the atomic file replacements exercised by these contract tests.
    # The directory is generated here and never reuses existing run data.
    temporary = work / ("cloud-contracts-" + uuid.uuid4().hex)
    print("Running source-only contract tests; native engines and release trials are outside this scope.", flush=True)
    print("Synthetic test artifacts: " + str(temporary), flush=True)
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp", str(temporary), *TEST_PATHS],
        cwd=root,
        env=environment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
