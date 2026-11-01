"""Actual loopback rejections must reach clients without accepting an action."""
from __future__ import annotations

import http.client
import json
import socket
import time
from urllib.parse import quote

import pytest

from pdf_remediator import web
from test_web import application, http_app, request


@pytest.mark.parametrize("origin", ["https://attacker.invalid", "null"])
def test_repeated_rejected_origin_posts_deliver_403_and_do_not_stop_application(http_app, origin):
    # Each connection is real and the token is valid. The body can still be in
    # transit when the origin check rejects it, which formerly raced Windows RST.
    for index in range(24):
        payload = b"{}" if index % 2 else b'{"padding":"' + b"x" * 8192 + b'"}'
        status, _, body = request(http_app, "/api/stop", "POST", payload,
                                  {"Origin": origin, "Content-Type": "application/json"})
        assert status == 403 and "External origins" in body["error"]
    assert request(http_app, "/api/dashboard")[0] == 200
    assert not http_app[0].jobs


@pytest.mark.parametrize("filename", ["../escape.pdf", r"..\escape.pdf", "wrong.html"])
def test_repeated_invalid_upload_names_deliver_400_without_copying_a_file(http_app, filename):
    body = b"%PDF-test-rejected-upload\n" + b"x" * 8192
    for _ in range(12):
        status, _, result = request(http_app, "/api/upload", "POST", body,
            {"Content-Type": "application/pdf", "X-File-Name": quote(filename)})
        assert status == 400 and result["error"]
    assert not any(path.is_file() for path in (http_app[0].root / "inputs").rglob("*"))
    assert not list((http_app[0].root / "inputs").iterdir()) and not http_app[0].jobs
    assert request(http_app, "/api/dashboard")[0] == 200


@pytest.mark.parametrize("path,external_origin,status", [
    ("/api/process", False, 400),
    ("/api/stop", True, 403),
])
def test_incomplete_oversized_declared_body_is_rejected_within_one_second(http_app, path, external_origin, status):
    app, server = http_app
    headers = [f"POST {path} HTTP/1.1", f"Host: 127.0.0.1:{server.server_port}",
        f"X-Review-Token: {app.token}", "Content-Type: application/json",
        f"Content-Length: {max(web.MAX_JSON + 1, 128 * 1024 * 1024)}", "Connection: close"]
    if external_origin:
        headers.append("Origin: https://attacker.invalid")
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=.8) as connection:
        connection.settimeout(.8)
        start = time.monotonic()
        # Deliberately keep the sending side open. Neither EOF nor the declared
        # remainder arrives; draining must have its own bounded deadline.
        connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + b"{}")
        response = http.client.HTTPResponse(connection)
        try:
            response.begin()
            raw = response.read()
            elapsed = time.monotonic() - start
            assert response.status == status and json.loads(raw)["error"]
            assert elapsed < 1.0
        finally:
            response.close()
    assert not app.jobs and not list((app.root / "inputs").iterdir())
    assert request(http_app, "/api/dashboard")[0] == 200
