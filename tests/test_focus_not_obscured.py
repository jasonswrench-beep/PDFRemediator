"""The status bar stays at the bottom of the window, so keyboard focus must never land underneath it.

This is measured in a real (headless) Microsoft Edge with the shipped stylesheet and the shipped bar markup: a control that is
only just visible at the bottom edge is given focus, which makes the browser scroll it into view by the smallest amount.
Without scroll padding the control ends up flush with the bottom edge, directly behind the bar. The test is skipped, with its
reason, on a computer that has no Edge or Chrome."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "pdf_remediator" / "web_assets"


def browser():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            for candidate in (Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"):
                if candidate.is_file():
                    return candidate
    return None


PAGE = """<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="style.css">
<body><main style="padding:1rem"><div style="height:1400px">Top of a long page</div>
<button id="target" class="secondary">The control that gets keyboard focus</button><div style="height:1400px">More page below</div></main>
%(bar)s
<pre id="out"></pre>
<script>
var target = document.getElementById('target');
window.scrollTo(0, target.getBoundingClientRect().top + window.scrollY - innerHeight + 20);
target.focus();
setTimeout(function () {
  var t = target.getBoundingClientRect(), b = document.getElementById('job-bar').getBoundingClientRect();
  document.getElementById('out').textContent = 'RESULT ' + JSON.stringify({hidden: t.bottom > b.top && t.top < b.bottom && b.height > 0,
    targetBottom: Math.round(t.bottom), barTop: Math.round(b.top)});
}, 300);
</script>"""


def measure(tmp_path, bar_markup):
    shutil.copy(ASSETS / "style.css", tmp_path / "style.css")
    (tmp_path / "page.html").write_text(PAGE % {"bar": bar_markup}, encoding="utf-8")
    profile = tempfile.mkdtemp(prefix="edge-focus-", dir=tmp_path)
    command = [str(browser()), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--user-data-dir=" + profile,
               "--window-size=1200,800", "--virtual-time-budget=4000", "--dump-dom", (tmp_path / "page.html").as_uri()]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    try:
        output, _ = process.communicate(timeout=90)
    finally:
        if process.poll() is None:
            process.kill()
        # only the browser processes that were started with this test's own scratch profile
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*%s*' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" % Path(profile).name],
                       capture_output=True, check=False)
    found = re.search(r"RESULT (\{.*?\})", output or "")
    assert found, "the page did not report a measurement: " + (output or "")[:300]
    return json.loads(found.group(1))


BAR = ('<div id="job-bar" class="job-bar"><strong id="job-label">Process 1 selected PDF(s)</strong> <span id="job-step">Reading the document '
       'structure.</span> <span id="job-clock">Working for 0:42. Please keep this window open.</span> '
       '<button id="job-cancel" class="quiet" type="button">Cancel</button></div>')


@pytest.mark.skipif(browser() is None, reason="needs Microsoft Edge or Google Chrome")
def test_a_control_given_keyboard_focus_near_the_bottom_is_not_hidden_behind_the_status_bar(tmp_path):
    result = measure(tmp_path, BAR)
    assert result["hidden"] is False, "The focused control is behind the bar: " + json.dumps(result)


@pytest.mark.skipif(browser() is None, reason="needs Microsoft Edge or Google Chrome")
def test_the_measurement_does_notice_a_control_hidden_behind_a_bar_without_scroll_padding(tmp_path):
    shutil.copy(ASSETS / "style.css", tmp_path / "style.css")
    css = (tmp_path / "style.css").read_text(encoding="utf-8")
    stripped = re.sub(r"html\{scroll-padding-bottom:[^}]*\}", "", css)
    assert stripped != css, "The stylesheet must carry the scroll-padding rule this test is about."

    original = (ASSETS / "style.css").read_bytes()
    # measure() copies the shipped stylesheet; replace it afterwards with the stripped one to prove the check can fail
    page = PAGE % {"bar": BAR}
    (tmp_path / "page.html").write_text(page, encoding="utf-8")
    (tmp_path / "style.css").write_text(stripped, encoding="utf-8")
    profile = tempfile.mkdtemp(prefix="edge-focus-", dir=tmp_path)
    command = [str(browser()), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--user-data-dir=" + profile,
               "--window-size=1200,800", "--virtual-time-budget=4000", "--dump-dom", (tmp_path / "page.html").as_uri()]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    try:
        output, _ = process.communicate(timeout=90)
    finally:
        if process.poll() is None:
            process.kill()
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*%s*' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" % Path(profile).name],
                       capture_output=True, check=False)
    found = re.search(r"RESULT (\{.*?\})", output or "")
    assert found and json.loads(found.group(1))["hidden"] is True, "Without the rule the bar must hide the control: " + (output or "")[:200]
    assert (ASSETS / "style.css").read_bytes() == original
