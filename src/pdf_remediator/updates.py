"""The "Check for updates" button: is a newer version of PDF Remediator published?

Only when the person clicks the button, the local service asks GitHub for the list of PDF Remediator's published releases (one HTTPS
request to api.github.com; nothing about the person or their documents is sent) and compares the newest one with the version
installed here. It only tells the person and links to that release's page; nothing is downloaded or installed. An IT department can
turn the button off with update_check = "off" in local-runtime.toml.
"""
from __future__ import annotations

import http.client
import json
import re
import ssl
from pathlib import Path

REPOSITORY = "jasonswrench-beep/PDFRemediator"
API_HOST = "api.github.com"
API_PATH = "/repos/" + REPOSITORY + "/releases?per_page=30"
RELEASES_PAGE = "https://github.com/" + REPOSITORY + "/releases"
RELEASE_PAGE_PREFIX = RELEASES_PAGE + "/tag/"
USER_AGENT = "PDF-Remediator-update-check"
LIMIT = 2 * 1024 ** 2
TIMEOUT_SECONDS = 15
_TAG = re.compile(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-(alpha|beta|rc)\.(\d{1,4}))?")
_STAGES = {"alpha": 0, "beta": 1, "rc": 2, None: 3}


def parse_version(text):
    """(major, minor, patch, stage, number) for "0.3.0", "0.3.0-alpha.6" or "v0.3.0-alpha.6"; None for anything else.
    A final release sorts after its alphas, betas and release candidates."""
    match = _TAG.fullmatch(str(text or "").strip())
    if match is None:
        return None
    major, minor, patch, stage, number = match.groups()
    return int(major), int(minor), int(patch), _STAGES[stage], int(number or 0)


def label(text):
    """"0.3.0-alpha.6" or "v0.3.0-alpha.6" as people read it: "0.3.0 alpha 6"."""
    match = _TAG.fullmatch(str(text or "").strip())
    if match is None:
        return str(text)
    major, minor, patch, stage, number = match.groups()
    return f"{major}.{minor}.{patch}" + (f" {stage} {number}" if stage else "")


def installed_release(project_root):
    """The exact release of this installed copy, which the package records in its manifest; None when the copy was not installed by
    PDF Remediator's setup (for example a source checkout)."""
    try:
        manifest = json.loads((Path(project_root) / "package-manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    release = manifest.get("release") if isinstance(manifest, dict) else None
    return release if parse_version(release) else None


def fetch_releases():
    """The published releases, as GitHub lists them. One HTTPS request, certificate checked, no redirects followed, bounded size."""
    connection = http.client.HTTPSConnection(API_HOST, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context())
    try:
        connection.request("GET", API_PATH, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT,
                                                     "X-GitHub-Api-Version": "2022-11-28"})
        response = connection.getresponse()
        body = response.read(LIMIT + 1)
        if response.status != 200:
            raise OSError("GitHub answered with status " + str(response.status))
        if len(body) > LIMIT:
            raise OSError("GitHub's answer was unexpectedly large")
        releases = json.loads(body)
        if not isinstance(releases, list):
            raise ValueError("GitHub's answer was not a list of releases")
        return releases
    finally:
        connection.close()


def _newest(releases):
    best = None
    for item in releases:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        version = parse_version(item.get("tag_name"))
        if version is None:
            continue
        if best is None or version > best[0]:
            url = item.get("html_url")
            # Only a release page of this repository is ever offered as a link.
            if not (isinstance(url, str) and url.startswith(RELEASE_PAGE_PREFIX) and "\n" not in url and " " not in url):
                url = RELEASES_PAGE
            best = (version, item["tag_name"], url)
    return best


def check(config, fetch=None):
    """What the button says. status is one of: off, available, current, unknown-version, error."""
    if getattr(config, "update_check", "manual") == "off":
        return {"status": "off", "message": "Checking for updates is turned off on this computer."}
    mine = installed_release(config.project_root)
    try:
        newest = _newest((fetch or fetch_releases)())
    except (OSError, ValueError, http.client.HTTPException, ssl.SSLError) as error:
        return {"status": "error", "message": "PDF Remediator could not check for updates (" + (str(error) or type(error).__name__) +
                "). You can look at the list of versions yourself.", "url": RELEASES_PAGE, "link_text": "Open the list of versions"}
    if newest is None:
        return {"status": "error", "message": "No published version of PDF Remediator was found. You can look at the list of versions yourself.",
                "url": RELEASES_PAGE, "link_text": "Open the list of versions"}
    newest_version, newest_tag, newest_url = newest
    if mine is None:
        return {"status": "unknown-version", "newest": label(newest_tag), "url": newest_url, "link_text": "Open the download page",
                "message": "This copy was not installed by PDF Remediator's setup, so its exact version is not known. The newest published "
                           "version is PDF Remediator " + label(newest_tag) + "."}
    if newest_version > parse_version(mine):
        return {"status": "available", "installed": label(mine), "newest": label(newest_tag), "url": newest_url,
                "link_text": "Open the download page",
                "message": "PDF Remediator " + label(newest_tag) + " is available. You have " + label(mine) + ". Installing it over this "
                           "copy keeps your saved reviews."}
    return {"status": "current", "installed": label(mine), "newest": label(newest_tag),
            "message": "You have the newest version, PDF Remediator " + label(mine) + "."}
