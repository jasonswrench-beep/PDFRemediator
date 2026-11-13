# Check for updates

Since 0.3.0 alpha 7, PDF Remediator has a **Check for updates** button at the bottom of its window. It is the pattern for the other
OpenStage-family and Prism programs: each revision of a tool adds the same kind of check.

## What it does

* **Only when clicked.** Nothing is checked at start-up or on a timer, and nothing runs in the background.
* **Notify only.** It says whether a newer version is published and, if so, links to that release's page (release notes, checksum,
  signed installer). It downloads and installs nothing; the person runs the new setup, which updates the copy in place and keeps the
  saved reviews.
* **Where it looks.** One HTTPS request from the local service to
  `https://api.github.com/repos/jasonswrench-beep/PDFRemediator/releases?per_page=30` (certificate checked, no redirects followed, at most
  2 MB, 15-second timeout). Pre-releases count, because every release so far is one; drafts never do. The request carries only a
  generic user agent (`PDF-Remediator-update-check`); nothing about the person or their documents is sent.
* **What it compares.** The installed copy's exact release, which the package records in `package-manifest.json` (`"release"`, set
  by `RELEASE` in `scripts/package-windows.py`; raise it for every release), with the highest published tag
  (`vMAJOR.MINOR.PATCH` or `vMAJOR.MINOR.PATCH-alpha|beta|rc.N`; a final release sorts after its pre-releases). A copy not made by the
  setup (a source checkout) is told the newest published version instead.
* **Links.** Only a release page of this repository (`https://github.com/jasonswrench-beep/PDFRemediator/releases/tag/...`) is ever
  offered; anything else falls back to the list of releases. The page shows the answer as text and a plain link (no HTML), and the
  program window opens the link in the person's own browser.
* **Turning it off.** `update_check = "off"` in `local-runtime.toml` (the setup writes `update_check = "manual"`). The button then says
  that checking is turned off on this computer and asks nothing.
* **Signing.** No separate update-signing key is needed, because nothing is installed automatically; the installer itself is signed
  with the publisher's code-signing certificate, and the release page carries its SHA-256.

## Code and tests

* `src/pdf_remediator/updates.py` (version comparison, the request, the answers), the `/api/update-check` route in `web.py`, the
  setting in `config.py`, the button and its result line in `web_assets/index.html` and `app.js`.
* `tests/test_updates.py` (comparison, answers, the exact request, the setting, the route and its token) and three page checks in
  `scripts/test-web-assets.cjs`. No test reaches the network.

## For the other tools

Match this: a manual button, notify only, a switch an IT department can set, the exact release recorded in the package, the
GitHub releases list of that tool's own repository (pre-releases included), only that repository's release pages as links, and no
document or personal data in the request. A full in-place updater (with its own signing key) can come later, the same way in every tool.
