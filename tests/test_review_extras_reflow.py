"""The Logo and branding panel and the scanned-page sample must reflow at 320 CSS pixels (400% zoom): no sideways scrolling, and every
control, label and button inside them stays on screen (WCAG 1.4.10). Measured in a real headless Edge or Chrome on the shipped page and
stylesheet. The page's script is left out: its markup for a group and a sampled page is written out here with the same element
structure and class names the script produces, long unbroken text included. Skipped, with its reason, without such a browser."""
from pathlib import Path
import re
import shutil

import pytest

from browser_page import browser, dump_dom, result_of

ASSETS = Path(__file__).resolve().parents[1] / "src" / "pdf_remediator" / "web_assets"
LONG = "Northfield-University-School-of-Continuing-Professional-Studies-and-Community-Engagement-" * 2

LOGO_GROUP = f"""<section class="logo-group"><h4>Logo and branding: The same picture on 12 pages.</h4>
<p class="field-note">Pages 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12. Each occurrence below keeps its own decision, acceptance and result.</p>
<fieldset class="logo-members"><legend>Occurrences to decide</legend>
<div class="logo-member"><label class="check"><input type="checkbox"><span>Page 1, in the header, 0.9 percent of the page.</span></label>
<p class="field-note">The same picture is a figure on 12 pages and is small on the page.</p><p class="logo-state">Saved description: {LONG}. Not accepted yet.</p>
<button type="button" class="item-page">Page 1</button></div></fieldset>
<div class="logo-tools"><button type="button" class="quiet">Select all occurrences</button><button type="button" class="quiet">Select none</button></div>
<label>Description for the selected occurrences</label><input type="text">
<div class="logo-actions"><button type="button" class="secondary">Save this description for the selected</button>
<button type="button" class="secondary">Save as decorative for the selected</button><button type="button" class="primary">Accept the saved choice for the selected</button></div></section>"""

SAMPLE_PAGE = f"""<section class="ocr-sample-page"><h4>Page 14</h4><p class="field-note">The text recognition was least sure of this page. Last scanned page.</p>
<p class="field-note">150 of 200 words were read confidently (75 percent). Rated: some words unsure.</p>
<div class="logo-tools"><button type="button" class="item-page">Page 14</button><button type="button" class="secondary">Show the recognized text for this page</button></div>
<fieldset class="ocr-sample-check"><legend>The words are accurate</legend><label class="check"><input type="radio" name="a"><span>Pass</span></label>
<label class="check"><input type="radio" name="a"><span>Problem</span></label><label class="check"><input type="radio" name="a"><span>Not checked</span></label></fieldset>
<label>Notes (required if you mark a problem)</label><textarea rows="3"></textarea>
<button type="button" class="primary">Save my changed record for page 14</button>
<p class="logo-state">Recorded by Avery Tester on 2026-11-16 for this exact PDF. {LONG}</p></section>"""

WRAPPER = """<!doctype html><meta charset="utf-8"><body style="margin:0">
<iframe id="frame" style="width:%(width)dpx;height:900px;border:0" srcdoc="%(page)s"></iframe>
<script>
document.getElementById('frame').addEventListener('load', function () {
  setTimeout(function () {
    var d = document.getElementById('frame').contentDocument, root = d.documentElement;
    var inside = Array.from(d.querySelectorAll('#logo-review *, #ocr-sample *')).filter(function (e) { var r = e.getBoundingClientRect(); return r.width > 0 && r.right > root.clientWidth + 1; })
      .slice(0, 6).map(function (e) { return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + '.' + e.className; });
    var shown = ['logo-review', 'ocr-sample'].map(function (id) { var r = d.getElementById(id).getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    document.body.insertAdjacentHTML('beforeend', '<pre id="out">RESULT ' + JSON.stringify({overflow: root.scrollWidth - root.clientWidth, clientWidth: root.clientWidth, wide: inside, shown: shown}) + '</pre>');
  }, 400);
});
</script>"""


def page_for_width(tmp_path, width):
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/style.css"', 'href="style.css"').replace("/PDFRemediator.svg", "PDFRemediator.svg")
    html = re.sub(r'<script[^>]*src="[^"]*app\.js"[^>]*></script>', "", html)
    for opening in ('<section id="review" hidden>', '<section id="panel-checks" role="tabpanel" aria-labelledby="tab-checks" hidden>'):
        assert opening in html
        html = html.replace(opening, opening.replace(" hidden", ""))
    for identifier in ("logo-review", "ocr-sample"):
        html, count = re.subn(r'(<section id="%s"[^>]*?) hidden>' % identifier, r"\1>", html)
        assert count == 1, identifier
    for placeholder, markup in (('<div id="logo-groups"></div>', LOGO_GROUP), ('<div id="ocr-sample-pages"></div>', SAMPLE_PAGE)):
        assert placeholder in html
        html = html.replace(placeholder, markup)
    escaped = html.replace("&", "&amp;").replace('"', "&quot;")
    (tmp_path / "review.html").write_text(WRAPPER % {"width": width, "page": escaped}, encoding="utf-8")
    shutil.copy(ASSETS / "style.css", tmp_path / "style.css")
    shutil.copy(ASSETS / "PDFRemediator.svg", tmp_path / "PDFRemediator.svg")


@pytest.mark.skipif(browser() is None, reason="needs Microsoft Edge or Google Chrome")
@pytest.mark.parametrize("width", [320, 360, 700, 1280])
def test_the_logo_and_scanned_sample_panels_do_not_scroll_sideways(tmp_path, width):
    page_for_width(tmp_path, width)
    result = result_of(dump_dom(tmp_path, "review.html", window="1400,1000"))
    assert result["clientWidth"] <= width, "The frame is not the width under test: %s" % result
    assert result["shown"] == [True, True], "The panels were not laid out: %s" % result
    assert result["overflow"] <= 1, "The review scrolls sideways by %d px at %d px wide; widest in the new panels: %s" % (result["overflow"], width, result["wide"])
    assert result["wide"] == [], "A control or line in the new panels runs past the edge at %d px: %s" % (width, result["wide"])
