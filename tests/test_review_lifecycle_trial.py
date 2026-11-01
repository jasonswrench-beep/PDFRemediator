"""Preflight/refusal contracts for the native trial; no native tools are skipped."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

import pytest

from pdf_remediator.config import RuntimeConfig


@pytest.fixture
def trial(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1]/'scripts/qualify-review-lifecycle.py'
    spec = importlib.util.spec_from_file_location('review_lifecycle_trial_contract', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module.sys, 'platform', 'linux')
    return module


@pytest.mark.parametrize('options', [
    {'ocr_mode': 'skip'}, {'ocr_mode': 'redo'}, {'preserve_painting': False},
    {'allow_tag_regrouping': True}, {'repair_source_mappings': True},
])
def test_trial_refuses_scope_expansion_before_native_calls_or_output_creation(trial, tmp_path, monkeypatch, options):
    output = tmp_path/'work/trial'
    monkeypatch.setattr(trial, 'inventory', lambda **kw: pytest.fail('Unsafe scope reached native inventory'))
    with pytest.raises(RuntimeError):
        trial.run_trial(replace(RuntimeConfig(), **options), output)
    assert not output.exists()


def test_trial_refuses_unqualified_platform_before_creating_output(trial, tmp_path, monkeypatch):
    monkeypatch.setattr(trial.sys, 'platform', 'win32')
    with pytest.raises(RuntimeError, match='Linux-specific'):
        trial.run_trial(RuntimeConfig(), tmp_path/'work/trial')
    assert not (tmp_path/'work').exists()


def test_trial_refuses_outputs_outside_ignored_work_directory(trial, tmp_path):
    with pytest.raises(RuntimeError, match='work directory'):
        trial.run_trial(RuntimeConfig(), tmp_path/'tracked-output')
    assert not (tmp_path/'tracked-output').exists()


def test_trial_never_overwrites_existing_trial_evidence(trial, tmp_path):
    output = tmp_path/'work/existing';output.mkdir(parents=True)
    sentinel = output/'summary.json';sentinel.write_bytes(b'authored prior evidence')
    with pytest.raises(RuntimeError, match='nothing will be overwritten'):
        trial.run_trial(RuntimeConfig(), output)
    assert sentinel.read_bytes() == b'authored prior evidence'


def test_missing_native_tools_fail_cli_and_record_explicit_incomplete_evidence(trial, tmp_path, monkeypatch, capsys):
    config = RuntimeConfig(project_root=tmp_path, java_home=tmp_path/'missing-java',
        odl_jar=tmp_path/'missing-odl.jar', validator_cli=tmp_path/'missing-validator',
        ocr_python=tmp_path/'missing-ocr', tesseract_dir=tmp_path/'missing-tesseract')
    monkeypatch.setattr(trial, 'load_config', lambda path: config)
    output = tmp_path/'work/missing-tools'
    assert trial.main(['--config', str(tmp_path/'synthetic-runtime.toml'), '--output', str(output)]) == 1
    summary = json.loads((output/'summary.json').read_text())
    doctor = json.loads((output/'doctor.json').read_text())
    assert summary['status'] == 'failed' and summary['cases'] == []
    assert summary['human_verified'] is summary['full_native_qualification'] is False
    assert doctor['status'] == 'incomplete'
    assert not doctor['capabilities']['tagging'] and not doctor['capabilities']['validation']
    assert not (output/'inputs').exists()
    assert 'No prerequisites were skipped' in capsys.readouterr().err
