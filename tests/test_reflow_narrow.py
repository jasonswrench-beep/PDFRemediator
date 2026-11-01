"""At 400% zoom a 1280 px window is 320 CSS pixels wide. The shipped start screen must not scroll sideways there (WCAG 1.4.10 Reflow),
and the top bar with Home and Reset has to wrap instead of running off the edge. Measured in a real headless Edge or Chrome on the
shipped page and stylesheet (the page's script is left out: this is about layout). A browser window cannot be made narrower than about
500 px, so the page is shown inside a frame of exactly the width being tested. Skipped, with its reason, without such a browser."""
from pathlib import Path
import re
import shutil

import pytest

from browser_page import browser, dump_dom, result_of

ASSETS = Path(__file__).resolve().parents[1] / "src" / "pdf_remediator" / "web_assets"

WRAPPER = """<!doctype html><meta charset="utf-8"><body style="margin:0">
<iframe id="frame" style="width:%(width)dpx;height:900px;border:0" srcdoc="%(page)s"></iframe>
<script>
document.getElementById('frame').addEventListener('load', function () {
  setTimeout(function () {
    var d = document.getElementById('frame').contentDocument, root = d.documentElement, header = d.querySelector('header');
    var rect = function (id) { var r = d.getElementById(id).getBoundingClientRect(); return {left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width)}; };
    var wide = Array.from(d.querySelectorAll('body *')).filter(function (e) { var r = e.getBoundingClientRect(); return r.width > 0 && r.right > root.clientWidth + 1; })
      .slice(0, 5).map(function (e) { return e.tagName.toLowerCase() + (e.id ? '#' + e.id : ''); });
    document.body.insertAdjacentHTML('beforeend', '<pre id="out">RESULT ' + JSON.stringify({overflow: root.scrollWidth - root.clientWidth, clientWidth: root.clientWidth, wide: wide,
      home: rect('home-button'), reset: rect('reset-button'), process: rect('process'), resetChoices: rect('reset-start'), header: Math.round(header.getBoundingClientRect().height)}) + '</pre>');
  }, 400);
});
</script>"""


def page_for_width(tmp_path, width):
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/style.css"', 'href="style.css"').replace("/PDFRemediator.svg", "PDFRemediator.svg")
    html = re.sub(r'<script[^>]*src="[^"]*app\.js"[^>]*></script>', "", html)
    escaped = html.replace("&", "&amp;").replace('"', "&quot;")
    (tmp_path / "start.html").write_text(WRAPPER % {"width": width, "page": escaped}, encoding="utf-8")
    shutil.copy(ASSETS / "style.css", tmp_path / "style.css")
    shutil.copy(ASSETS / "PDFRemediator.svg", tmp_path / "PDFRemediator.svg")


@pytest.mark.skipif(browser() is None, reason="needs Microsoft Edge or Google Chrome")
@pytest.mark.parametrize("width", [320, 360, 700, 1280])
def test_the_start_screen_does_not_scroll_sideways_and_keeps_home_and_reset_on_screen(tmp_path, width):
    page_for_width(tmp_path, width)
    result = result_of(dump_dom(tmp_path, "start.html", window="1400,1000"))
    assert result["clientWidth"] <= width, "The frame is not the width under test: %s" % result
    assert result["overflow"] <= 1, "The start screen scrolls sideways by %d px at %d px wide; widest: %s" % (result["overflow"], width, result["wide"])
    for name in ("home", "reset", "process", "resetChoices"):
        assert result[name]["width"] > 0 and result[name]["left"] >= 0 and result[name]["right"] <= result["clientWidth"] + 1, \
            "%s is not fully on screen at %d px wide: %s" % (name, width, result[name])
