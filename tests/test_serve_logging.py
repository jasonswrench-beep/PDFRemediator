"""Startup logging boundaries; socket-free service stubs, real session JSON."""
import json

import pytest

from pdf_remediator import web


@pytest.mark.parametrize("with_session_file", [True, False], ids=["hidden-helper-log", "explicit-console-link"])
def test_startup_private_link_is_logged_only_for_explicit_console_entry(tmp_path, monkeypatch, capsys, with_session_file):
    token = "fixture-private-launch-token"
    origin = "http://127.0.0.1:49321"
    private_url = origin + "/#" + token
    actions = []

    class ApplicationStub:
        def __init__(self, data_dir, config):
            assert data_dir == tmp_path / "application"
            self.token = token
            self.config = config or web.RuntimeConfig()

        def close(self):
            actions.append("application-close")

    class ServerStub:
        def __init__(self, application, port):
            assert application.token == token and port == 0
            self.origin = origin

        def serve_forever(self, *, poll_interval):
            assert 0 < poll_interval <= 1
            actions.append("serve")

        def server_close(self):
            actions.append("server-close")

    monkeypatch.setattr(web, "Application", ApplicationStub)
    monkeypatch.setattr(web, "ReviewServer", ServerStub)
    monkeypatch.setattr(web.webbrowser, "open", lambda *args: pytest.fail("No browser should be opened by this test"))
    session = tmp_path / "session.json" if with_session_file else None

    web.serve(tmp_path / "application", open_browser=False, session_file=session)

    captured = capsys.readouterr()
    assert "ready" in captured.out.lower() and origin in captured.out
    assert captured.err == ""
    if with_session_file:
        assert token not in captured.out and "/#" not in captured.out
        record = json.loads(session.read_text(encoding="utf-8"))
        assert record["url"] == private_url and record["origin"] == origin
        assert type(record["pid"]) is int and record["pid"] > 0
    else:
        assert private_url in captured.out
        assert not (tmp_path / "session.json").exists()
    assert actions == ["serve", "server-close", "application-close"]


@pytest.mark.parametrize('phase', ['bind', 'import', 'session', 'browser'])
def test_service_startup_failure_closes_created_resources(tmp_path, monkeypatch, phase):
    actions = []
    class ApplicationStub:
        token = 'synthetic-startup-token'
        config = web.RuntimeConfig()
        def __init__(self, *args):pass
        def import_bundle(self, bundle):raise OSError('synthetic startup failure')
        def close(self):actions.append('application-close')
    class ServerStub:
        origin = 'http://127.0.0.1:49321'
        def __init__(self, *args):
            if phase == 'bind':raise OSError('synthetic startup failure')
        def serve_forever(self, **kwargs):pytest.fail('Failed startup reached service loop')
        def server_close(self):actions.append('server-close')
    def fail(*args, **kwargs):raise OSError('synthetic startup failure')
    monkeypatch.setattr(web, 'Application', ApplicationStub)
    monkeypatch.setattr(web, 'ReviewServer', ServerStub)
    if phase == 'session':monkeypatch.setattr(web, 'write_json', fail)
    monkeypatch.setattr(web.webbrowser, 'open', fail)
    with pytest.raises(OSError, match='synthetic startup failure'):
        web.serve(tmp_path/'application', import_bundle=tmp_path/'bundle' if phase == 'import' else None,
            session_file=tmp_path/'session.json' if phase == 'session' else None, open_browser=phase == 'browser')
    assert actions == (['application-close'] if phase == 'bind' else ['server-close', 'application-close'])
