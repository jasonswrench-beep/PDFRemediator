"""Run the test suite one file per process and retry a file whose process died with a native crash.

Some tests drive native code (pdfium, pikepdf) and, on some Windows machines, now and then end the whole Python process with
"Windows fatal exception: access violation" (or 0xc0000374), which hides the result of every file after it in a single pytest run.
This runs each tests/test_*.py in its own process, retries a crashed file (default 3 more times) and prints a total, so the real
failures stay visible. Usage:  python scripts/run-tests-by-file.py [--retries N] [--keyword TEXT]"""
from pathlib import Path
import argparse
import glob
import os
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retries", type=int, default=3, help="extra attempts for a file whose process crashed")
    parser.add_argument("--keyword", default="", help="only files whose name contains this text")
    arguments = parser.parse_args()
    files = sorted(Path(item) for item in glob.glob(str(ROOT / "tests" / "test_*.py")) if arguments.keyword in os.path.basename(item))
    passed = 0; failed = []; crashed = []; started = time.time()
    for path in files:
        for attempt in range(1, arguments.retries + 2):
            process = subprocess.run([sys.executable, "-B", "-m", "pytest", str(path), "-q", "-p", "no:cacheprovider", "--tb=no", "-rf"], cwd=ROOT,
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONPATH="src"))
            text = process.stdout + process.stderr
            if "fatal exception" not in text:
                break
        died = "fatal exception" in text
        found = re.search(r"(\d+) passed", text)
        passed += int(found.group(1)) if found else 0
        failed += re.findall(r"^FAILED (\S+)", text, re.M)
        if died:
            crashed.append(path.name)
        print("%-48s attempts=%d %s" % (path.name, attempt, "CRASHED every time" if died else (found.group(0) if found else text.strip().splitlines()[-1][:60])), flush=True)
    print("\nTOTAL passed: %d | failed: %d | files that crashed on every attempt: %s | %.1f minutes" % (passed, len(failed), crashed or "none", (time.time() - started) / 60))
    for name in failed:
        print("  FAILED", name)
    return 1 if failed or crashed else 0


if __name__ == "__main__":
    sys.exit(main())
