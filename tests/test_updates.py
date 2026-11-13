"""The Check for updates button: version comparison, what it says, what it sends, and the service route. No test reaches the network."""
import http.client
import json
import threading

import pytest

from pdf_remediator import updates, web
from pdf_remediator.config import RuntimeConfig, load_config


def release(tag, draft=False, url=None):
    return {"tag_name": tag, "draft": draft, "prerelease": True,
            "html_url": url or "https://github.com/jasonswrench-beep/PDFRemediator/releases/tag/" + tag}


def installed(tmp_path, release_name):
    (tmp_path / "package-manifest.json").write_text(json.dumps({"product": "PDF Remediator", "release": release_name}), encoding="utf-8")
    return RuntimeConfig(project_root=tmp_path)


def test_versions_compare_as_releases_do():
    order = ["0.2.9", "v0.3.0-alpha.1", "0.3.0-alpha.6", "v0.3.0-alpha.10", "0.3.0-beta.1", "0.3.0-rc.2", "v0.3.0", "0.3.1-alpha.1", "1.0.0"]
    parsed = [updates.parse_version(tag) for tag in order]
    assert all(parsed) and parsed == sorted(parsed)
    for bad in ("", None, "latest", "v0.3", "0.3.0-alpha", "0.3.0-gamma.1", "0.3.0-alpha.1-extra"):
        assert updates.parse_version(bad) is None, bad
    assert updates.label("v0.3.0-alpha.7") == "0.3.0 alpha 7" and updates.label("0.3.0") == "0.3.0"


def test_a_newer_release_is_announced_with_its_own_page(tmp_path):
    calls = []
    def fetch():
        calls.append(True)
        return [release("v0.3.0-alpha.8", draft=True), release("v0.3.0-alpha.7"), release("v0.3.0-alpha.6"), {"tag_name": "nightly"}]
    result = updates.check(installed(tmp_path, "0.3.0-alpha.6"), fetch)
    assert calls == [True]
    assert result["status"] == "available" and result["newest"] == "0.3.0 alpha 7" and result["installed"] == "0.3.0 alpha 6"
    assert result["url"] == "https://github.com/jasonswrench-beep/PDFRemediator/releases/tag/v0.3.0-alpha.7", "a draft is never offered"
    assert "0.3.0 alpha 7 is available" in result["message"] and "keeps your saved reviews" in result["message"]


def test_the_newest_version_says_so_without_a_link(tmp_path):
    for mine in ("0.3.0-alpha.7", "0.3.0-alpha.9"):
        result = updates.check(installed(tmp_path, mine), lambda: [release("v0.3.0-alpha.7"), release("v0.3.0-alpha.6")])
        assert result["status"] == "current" and "url" not in result and "You have the newest version" in result["message"]


def test_a_copy_not_installed_by_setup_is_told_the_newest_version(tmp_path):
    result = updates.check(RuntimeConfig(project_root=tmp_path), lambda: [release("v0.3.0-alpha.7")])
    assert result["status"] == "unknown-version" and result["newest"] == "0.3.0 alpha 7" and result["url"].endswith("/tag/v0.3.0-alpha.7")


def test_only_this_repositorys_release_pages_are_ever_offered(tmp_path):
    for url in ("https://example.org/releases/tag/v9.9.9", "https://github.com/someone-else/PDFRemediator/releases/tag/v9.9.9",
                "javascript:alert(1)", None, "https://github.com/jasonswrench-beep/PDFRemediator/releases/tag/v9 .9.9"):
        offered = dict(release("v9.9.9"), html_url=url)
        result = updates.check(installed(tmp_path, "0.3.0-alpha.6"), lambda: [offered])
        assert result["status"] == "available" and result["url"] == updates.RELEASES_PAGE, url


def test_turned_off_it_asks_nothing(tmp_path):
    def fetch():
        raise AssertionError("no request when the check is turned off")
    config = installed(tmp_path, "0.3.0-alpha.6")
    config.update_check = "off"
    result = updates.check(config, fetch)
    assert result == {"status": "off", "message": "Checking for updates is turned off on this computer."}


@pytest.mark.parametrize("problem", [OSError("GitHub answered with status 403"), ValueError("not JSON"), http.client.HTTPException("bad")])
def test_a_failed_check_says_so_and_offers_the_list_of_versions(tmp_path, problem):
    def fetch():
        raise problem
    result = updates.check(installed(tmp_path, "0.3.0-alpha.6"), fetch)
    assert result["status"] == "error" and result["url"] == updates.RELEASES_PAGE
    assert result["message"].startswith("PDF Remediator could not check for updates (") and "). You can look" in result["message"]
    assert updates.check(installed(tmp_path, "0.3.0-alpha.6"), lambda: [])["status"] == "error"


def test_the_request_goes_only_to_githubs_release_list_and_carries_nothing_personal(monkeypatch):
    seen = {}

    class Response:
        status = 200
        def read(self, limit):
            seen["limit"] = limit
            return json.dumps([release("v0.3.0-alpha.7")]).encode()

    class Connection:
        def __init__(self, host, timeout, context):
            seen.update(host=host, timeout=timeout, verifies=context.verify_mode)
        def request(self, method, path, headers):
            seen.update(method=method, path=path, headers=headers)
        def getresponse(self):
            return Response()
        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(updates.http.client, "HTTPSConnection", Connection)
    assert updates.fetch_releases()[0]["tag_name"] == "v0.3.0-alpha.7"
    import ssl
    assert seen["host"] == "api.github.com" and seen["verifies"] == ssl.CERT_REQUIRED and seen["closed"] is True
    assert seen["method"] == "GET" and seen["path"] == "/repos/jasonswrench-beep/PDFRemediator/releases?per_page=30"
    assert set(seen["headers"]) == {"Accept", "User-Agent", "X-GitHub-Api-Version"} and seen["headers"]["User-Agent"] == "PDF-Remediator-update-check"


def test_a_refused_or_oversized_answer_is_an_error(monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass
        def request(self, *args, **kwargs):
            pass
        def getresponse(self):
            return self.answer
        def close(self):
            pass

    class Refused:
        status = 403
        def read(self, limit):
            return b"{}"

    class Oversized:
        status = 200
        def read(self, limit):
            return b"[" + b" " * limit + b"]"

    for answer, words in ((Refused(), "status 403"), (Oversized(), "unexpectedly large")):
        Connection.answer = answer
        monkeypatch.setattr(updates.http.client, "HTTPSConnection", Connection)
        with pytest.raises(OSError, match=words):
            updates.fetch_releases()


def test_the_setting_accepts_manual_or_off_only(tmp_path):
    path = tmp_path / "local-runtime.toml"
    for value in ("manual", "off"):
        path.write_text('[runtime]\nupdate_check = "' + value + '"\n', encoding="utf-8")
        assert load_config(path).update_check == value
    path.write_text('[runtime]\nupdate_check = "daily"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="update_check must be manual or off"):
        load_config(path)
    assert RuntimeConfig().update_check == "manual"


def test_the_service_answers_the_button_and_only_with_its_token(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "fetch_releases", lambda: [release("v0.3.0-alpha.7")])
    app = web.Application(tmp_path / "application", installed(tmp_path, "0.3.0-alpha.6"))
    server = web.ReviewServer(app)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        def get(token):
            headers = {"Host": "127.0.0.1:" + str(server.server_port)}
            if token:
                headers["X-Review-Token"] = app.token
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
            try:
                connection.request("GET", "/api/update-check", headers=headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()
        status, answer = get(True)
        assert status == 200 and answer["status"] == "available" and answer["newest"] == "0.3.0 alpha 7"
        assert get(False)[0] in (401, 403)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        app.close()
