"""Setup readiness must demonstrate imports, not merely distribution metadata.

Native tool/version responses below are named startup doubles. No PDF, optional
OCR operation, model, browser, network request or environment installation runs.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from pdf_remediator import cli, doctor, validation


@pytest.fixture
def installed_runtime(tmp_path, monkeypatch):
    paths = {"project_root": tmp_path, "java_home": tmp_path / "jdk",
             "java": tmp_path / "jdk/bin/java", "odl_jar": tmp_path / "tagger.jar",
             "validator_cli": tmp_path / "validator", "ocr_python": tmp_path / "ocr-python",
             "tesseract_dir": tmp_path / "tesseract"}
    paths["validator_cli"].touch()
    (paths["tesseract_dir"] / "tessdata").mkdir(parents=True)
    (paths["tesseract_dir"] / "tessdata/eng.traineddata").touch()
    monkeypatch.setattr(doctor, "resolve_tools", lambda *args, **kwargs: paths)
    monkeypatch.setattr(doctor, "version", lambda name: "installed-metadata-version")
    monkeypatch.setattr(doctor, "odl_identity", lambda path: {"status": "available", "version": doctor.ODL_VERSION})
    monkeypatch.setattr(validation, "_launch", lambda *args: (["validator-probe"], {}, "startup-double"))
    failures = {}
    calls = []

    def startup(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == sys.executable:
            module = command[command.index("-c") + 2]
            failure = failures.get(module)
            if isinstance(failure, BaseException):
                raise failure
            return SimpleNamespace(returncode=1 if failure else 0,
                                   stdout=b"" if failure else b"Import readiness passed\n",
                                   stderr=(failure or "").encode("utf-8"))
        if "-jar" in command:
            return SimpleNamespace(returncode=1, stdout=b"usage: [options]", stderr=b"")
        if command[0] == "validator-probe":
            output = f"veraPDF {doctor.VERAPDF_VERSION}"
        elif command[0] == str(paths["ocr_python"]):
            output = doctor.OCR_VERSION
        else:
            output = "native tool startup double"
        return SimpleNamespace(returncode=0, stdout=output.encode("utf-8"), stderr=b"")

    monkeypatch.setattr(doctor.subprocess, "run", startup)
    return failures, calls


def test_healthy_required_imports_allow_ready_without_pdf_processing(installed_runtime):
    result = doctor.inventory()
    assert result["status"] == "ready"
    assert result["capabilities"]["tagging"] and result["capabilities"]["validation"]
    assert set(result["dependencies"]) == {"pikepdf", "pypdfium2", "Pillow", "psutil"}
    assert all(item["status"] == "available" and item["startup"]["returncode"] == 0
               for item in result["dependencies"].values())
    assert result["read_only"] and not result["downloads"] and result["document_network_calls"] == 0


def test_optional_ocr_startup_uses_explicit_isolation_no_bytecode_and_utf8(installed_runtime):
    """A named startup double proves argv; no OCR package is imported."""
    _, calls = installed_runtime
    result = doctor.inventory()
    probes = [(command, kwargs) for command, kwargs in calls if "ocrmypdf" in command]
    assert len(probes) == 1 and result["tools"]["ocrmypdf"]["status"] == "available"
    command, kwargs = probes[0]
    assert command[1:] == ["-I", "-B", "-X", "utf8", "-m", "ocrmypdf", "--version"]
    assert kwargs["shell"] is False and kwargs["timeout"] == 15
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


@pytest.mark.parametrize("package,module", [("pikepdf", "pikepdf"), ("pypdfium2", "pypdfium2"),
                                          ("Pillow", "PIL.Image"), ("psutil", "psutil")])
def test_installed_metadata_does_not_hide_a_failed_native_import(installed_runtime, package, module):
    failures, _ = installed_runtime
    failures[module] = "ImportError: native binding could not load"
    result = doctor.inventory()
    dependency = result["dependencies"][package]
    assert result["status"] == "incomplete" and dependency["status"] == "failed"
    assert dependency["version"] == "installed-metadata-version"
    assert "native binding could not load" in dependency["startup"]["output"]
    assert "too long" not in dependency["guidance"]
    assert not result["capabilities"]["tagging"] and not result["capabilities"]["validation"]


@pytest.mark.parametrize("command", ["doctor", "engines"])
def test_cli_refuses_readiness_and_explains_actual_windows_loader_length_failure(installed_runtime, capsys, command):
    failures, _ = installed_runtime
    failures["pikepdf"] = "ImportError: DLL load failed while importing _core: The filename or extension is too long."
    assert cli.main([command, "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    runtime = result.get("runtime", result)
    assert runtime["status"] == "incomplete"
    dependency = runtime["dependencies"]["pikepdf"]
    assert dependency["status"] == "failed"
    assert "new installation in a short folder" in dependency["guidance"]
    assert "do not move or delete" in dependency["guidance"]
    assert "Windows settings change" in dependency["guidance"]


@pytest.mark.parametrize("failure,status", [
    (subprocess.TimeoutExpired(["selected-python"], 15), "timeout"),
    (FileNotFoundError("selected runtime is absent"), "missing"),
    (OSError("runtime execution denied"), "failed"),
])
def test_import_probe_timeout_and_execution_failures_stay_incomplete(installed_runtime, failure, status):
    failures, _ = installed_runtime
    failures["pikepdf"] = failure
    result = doctor.inventory()
    assert result["status"] == "incomplete"
    assert result["dependencies"]["pikepdf"]["status"] == status
    assert not result["capabilities"]["tagging"] and not result["capabilities"]["validation"]


def test_missing_distribution_stays_missing_without_an_import_probe(installed_runtime, monkeypatch):
    _, calls = installed_runtime

    def version(name):
        if name == "Pillow":
            raise doctor.PackageNotFoundError(name)
        return "installed-metadata-version"

    monkeypatch.setattr(doctor, "version", version)
    result = doctor.inventory()
    assert result["status"] == "incomplete"
    assert result["dependencies"]["Pillow"] == {"status": "missing"}
    imports = [command for command, _ in calls if command[0] == sys.executable]
    assert len(imports) == 3
    assert all("PIL.Image" not in command for command in imports)


def test_fresh_probes_use_selected_interpreter_hidden_local_no_write_environment(installed_runtime, monkeypatch):
    _, calls = installed_runtime
    inherited = {"PYTHONPATH": "unrelated-user-project", "PYTHONHOME": "another-runtime",
                 "JAVA_TOOL_OPTIONS": "-agentlib:unrelated", "JAVA_OPTS": "unrelated"}
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)
    result = doctor.inventory()
    assert result["status"] == "ready"
    imports = [(command, kwargs) for command, kwargs in calls if command[0] == sys.executable]
    assert len(imports) == 4
    assert {tuple(command[command.index("-c") + 2:]) for command, _ in imports} == {
        ("pikepdf",), ("pypdfium2",), ("PIL.Image", "PIL._imaging"), ("psutil",)}
    for command, kwargs in imports:
        assert command[0] == sys.executable and "-B" in command and "-I" in command
        assert kwargs["shell"] is False and kwargs["timeout"] == 15
        assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = kwargs["env"]
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
        assert not any(name in env for name in inherited)
        assert kwargs["stdout"] == subprocess.PIPE and kwargs["stderr"] == subprocess.PIPE
    assert all(os.environ[name] == value for name, value in inherited.items())


def test_doctor_itself_can_import_when_native_psutil_is_unavailable():
    # This real child imports only doctor, with psutil explicitly unavailable.
    # Dependency inventory must not depend on importing the process adapter.
    source = str(Path(doctor.__file__).resolve().parents[1])
    script = ("import sys; sys.path.insert(0, sys.argv[1]); sys.modules['psutil'] = None; "
              "import pdf_remediator.doctor; assert 'pdf_remediator.process' not in sys.modules")
    run = subprocess.run([sys.executable, "-I", "-B", "-c", script, source],
                         capture_output=True, timeout=15, shell=False,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert run.returncode == 0, run.stderr.decode("utf-8", errors="replace")
