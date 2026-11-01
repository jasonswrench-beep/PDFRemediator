"""The real page against the real service, driven in a headless browser (scripts/e2e-browser.cjs).

It needs this work copy's runtime (Java, OpenDataLoader, veraPDF) and a PDF, so it runs only when these are named in the
environment; otherwise it is skipped with its reason:
  PDFR_E2E_PYTHON, PDFR_E2E_CONFIG, PDFR_E2E_SHORT_PDF  (required)   PDFR_E2E_LONG_PDF, PDFR_E2E_EDGE  (optional)
Nothing is installed and no window appears; the service and the browser use a scratch folder that is removed afterwards."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e2e-browser.cjs"
REQUIRED = ("PDFR_E2E_PYTHON", "PDFR_E2E_CONFIG", "PDFR_E2E_SHORT_PDF")


@pytest.mark.skipif(any(not os.environ.get(name) for name in REQUIRED) or shutil.which("node") is None,
                    reason="needs Node.js 22+ and PDFR_E2E_PYTHON, PDFR_E2E_CONFIG and PDFR_E2E_SHORT_PDF")
def test_the_real_page_works_end_to_end_against_the_real_service():
    result = subprocess.run([shutil.which("node"), str(SCRIPT)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(any(not os.environ.get(name) for name in REQUIRED + ("PDFR_E2E_LONG_PDF",)) or shutil.which("node") is None,
                    reason="needs Node.js 22+ and PDFR_E2E_PYTHON, PDFR_E2E_CONFIG, PDFR_E2E_SHORT_PDF and PDFR_E2E_LONG_PDF")
def test_when_the_service_disappears_during_a_long_scan_the_page_says_so_and_stops_showing_progress():
    result = subprocess.run([shutil.which("node"), str(SCRIPT)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                            env=dict(os.environ, PDFR_E2E_ONLY="crash"))
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_driver_script_is_valid_javascript():
    node = shutil.which("node")
    assert node, "Node.js 20 or newer is required for the browser-script tests; no cases were skipped."
    result = subprocess.run([node, "--check", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
