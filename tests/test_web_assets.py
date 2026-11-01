"""Execute the shipped browser script with named DOM/HTTP doubles in Node.

Node.js 20+ is an explicit developer-test prerequisite, not an app runtime
dependency. Missing Node fails this scope; no tests are silently skipped.
No browser, PDF/native engine, model, OCR or actual HTTP service is started.
"""
from pathlib import Path
import shutil
import subprocess


def test_browser_script_regressions(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    assert node, 'Node.js 20 or newer is required for the browser-script regression tests; no cases were skipped.'
    result = subprocess.run(
        [node, '--test-reporter=tap', str(root / 'scripts/test-web-assets.cjs')],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
