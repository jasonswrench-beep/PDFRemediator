"""Shared by every test: no test may open a real browser window on the computer running the tests.

A test that means to check the browser is opened replaces webbrowser.open itself (monkeypatch), which overrides this guard."""
import webbrowser

import pytest


@pytest.fixture(autouse=True)
def no_real_browser_window(monkeypatch):
    def refuse(*args, **kwargs):
        pytest.fail("A test tried to open a real browser window: " + repr(args[:1]))
    for name in ("open", "open_new", "open_new_tab"):
        monkeypatch.setattr(webbrowser, name, refuse)
