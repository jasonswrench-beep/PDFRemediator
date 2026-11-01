"""Shared by the real-browser tests: load a page in a headless Edge or Chrome with its own scratch profile and read back what the
page reports. Only the browser processes started with that scratch profile are stopped afterwards."""
from pathlib import Path
import os
import re
import subprocess
import tempfile


def browser():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            for candidate in (Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"):
                if candidate.is_file():
                    return candidate
    return None


def dump_dom(tmp_path, page, window="1200,800", budget=4000):
    """Open tmp_path/<page> and return the DOM text after its scripts have run."""
    profile = tempfile.mkdtemp(prefix="edge-page-", dir=tmp_path)
    command = [str(browser()), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--user-data-dir=" + profile,
               "--window-size=" + window, "--virtual-time-budget=%d" % budget, "--dump-dom", (Path(tmp_path) / page).as_uri()]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    try:
        output, _ = process.communicate(timeout=90)
    finally:
        if process.poll() is None:
            process.kill()
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*%s*' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" % Path(profile).name],
                       capture_output=True, check=False)
    return output or ""


def result_of(output):
    import html
    import json
    found = re.search(r"RESULT (\{.*?\})(?:</pre>|<)", output, re.S)
    assert found, "the page did not report a measurement: " + output[:300]
    return json.loads(html.unescape(found.group(1)))
