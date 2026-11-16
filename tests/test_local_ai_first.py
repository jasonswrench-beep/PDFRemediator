"""Hold the AI plan (docs/AI-PLAN.md): optional, local only, no hosted route and no stored key.

If a hosted provider is ever added, it must come in behind the shared runtime with the owner's say, and these tests are the place where
that decision is made visible: they must be changed on purpose, not by accident.
"""
from pathlib import Path

import pytest

from pdf_remediator import assistance
from pdf_remediator.assistance import AssistanceError

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("url", [
    "https://api.example.com/v1",
    "http://api.example.com/v1",
    "http://10.0.0.5:11434/v1",
    "http://192.168.1.20:8080",
    "http://[2001:db8::1]:8080",
    "http://user:secret@127.0.0.1:8080/v1",
    "http://127.0.0.1:8080/v1?key=abc",
])
def test_only_a_loopback_model_server_without_credentials_is_accepted(url):
    with pytest.raises(AssistanceError):
        assistance._endpoint(url)


@pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:8080/v1", "http://[::1]:8080"])
def test_loopback_addresses_are_accepted_and_localhost_is_pinned(url):
    provider = assistance._endpoint(url)
    assert provider["url"].startswith("http")
    assert "localhost" not in provider["url"]


def test_the_example_configuration_holds_no_key_or_hosted_setting():
    text = (ROOT / "remediator.example.toml").read_text(encoding="utf-8").lower()
    for word in ("api_key", "api-key", "apikey", "token", "secret", "bearer", "openai.com", "anthropic.com"):
        assert word not in text.replace("no api keys or cloud-provider settings belong in this file.", "")


def _option_strings(parser):
    found = set()
    for action in parser._actions:
        found.update(action.option_strings)
        for child in getattr(action, "choices", None) or {}:
            sub = action.choices[child] if isinstance(action.choices, dict) else None
            if sub is not None and hasattr(sub, "_actions"):
                found |= _option_strings(sub)
    return found


def test_the_command_line_has_no_key_or_hosted_provider_option():
    from pdf_remediator.cli import _parser

    options = {option.lower() for option in _option_strings(_parser())}
    assert "--endpoint" in options  # the one local model server address; it must stay loopback only (tests above)
    for word in ("key", "token", "secret", "password", "provider", "cloud", "hosted", "openai", "anthropic", "download"):
        assert not [option for option in options if word in option], (word, sorted(options))


def test_assistance_provenance_names_only_the_local_kind():
    source = (ROOT / "src" / "pdf_remediator" / "assistance.py").read_text(encoding="utf-8")
    assert '"kind": "local-openai-compatible"' in source
    for forbidden in ("api.openai.com", "api.anthropic.com", "Authorization", "Bearer "):
        assert forbidden not in source
