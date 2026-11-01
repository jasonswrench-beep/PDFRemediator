"""Execute the shipped plain-evidence function alone in Node: the sentences the review page gives the OCR evidence.

Node.js 20+ is an explicit developer-test prerequisite, not an app runtime dependency. Missing Node fails this scope; no tests are silently skipped.
No browser, PDF/native engine, model, OCR or HTTP service is started.
"""
from pathlib import Path
import shutil
import subprocess


def test_plain_evidence_sentences(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    assert node, 'Node.js 20 or newer is required for the plain-evidence tests; no cases were skipped.'
    result = subprocess.run(
        [node, '--test-reporter=tap', str(root / 'scripts/test-plain-evidence.cjs')],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
