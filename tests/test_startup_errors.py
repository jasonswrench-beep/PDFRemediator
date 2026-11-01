"""Exercise the real desktop entry point without opening any desktop UI."""
import builtins
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest


def run_entry(monkeypatch, error=None):
    calls = []
    original_import = builtins.__import__

    class Root:
        def withdraw(self): calls.append('withdraw')
        def destroy(self): calls.append('destroy')

    box = SimpleNamespace(showerror=lambda *args: calls.append(args))
    tkinter = SimpleNamespace(Tk=Root, messagebox=box)

    def import_module(name, *args, **kwargs):
        if name == 'pdf_remediator.launcher':
            if error is not None:
                raise error
            return SimpleNamespace(launch=lambda path: calls.append(('launch', path)))
        if name == 'tkinter':
            return tkinter
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', import_module)
    entry = Path(__file__).resolve().parents[1] / 'launch_review.pyw'
    runpy.run_path(str(entry))
    return calls, entry


@pytest.mark.parametrize('detail', [
    'DLL load failed while importing _core: The filename or extension is too long.',
    'A Windows path is too long.',
])
def test_import_failure_explains_shorter_fresh_installation_and_saved_review_boundary(monkeypatch, detail):
    calls, _ = run_entry(monkeypatch, ImportError(detail))
    assert calls[0] == 'withdraw' and calls[-1] == 'destroy'
    title, message = calls[1]
    assert title == 'PDF Remediator could not start'
    assert detail in message
    assert 'fresh installation in a shorter local folder' in message
    assert 'Setup PDF Remediator.cmd' in message
    assert 'original PDFs and saved reviews in place' in message
    assert 'does not automatically transfer saved reviews' in message


def test_native_path_error_code_gets_actionable_message(monkeypatch):
    error = OSError('Localized native loader failure')
    error.winerror = 206
    calls, _ = run_entry(monkeypatch, error)
    assert 'shorter local folder' in calls[1][1]


def test_generic_import_failure_is_not_misdiagnosed_as_path_length(monkeypatch):
    detail = 'DLL load failed: The specified module could not be found.'
    calls, _ = run_entry(monkeypatch, ImportError(detail))
    message = calls[1][1]
    assert detail in message and 'Run Setup PDF Remediator.cmd' in message
    assert 'shorter' not in message and 'too long' not in message


def test_other_startup_error_keeps_its_own_recovery_instructions(monkeypatch):
    detail = 'Open its existing browser page and click Stop application.'
    calls, _ = run_entry(monkeypatch, RuntimeError(detail))
    assert detail in calls[1][1] and 'START-HERE.md' in calls[1][1]
    assert 'shorter' not in calls[1][1]


def test_successful_entry_point_launches_same_local_review_directory(monkeypatch):
    calls, entry = run_entry(monkeypatch)
    assert calls == [('launch', entry.parent / 'output/review-app')]
