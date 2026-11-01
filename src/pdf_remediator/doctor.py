"""Read-only inventory of explicitly selected local tools; never installs."""
from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ODL_VERSION = "2.5.13"
VERAPDF_VERSION = "1.30.3"
OCR_VERSION = "17.13.0"
_PYTHON_IMPORTS = {"pikepdf": ("pikepdf",), "pypdfium2": ("pypdfium2",),
                   "Pillow": ("PIL.Image", "PIL._imaging"), "psutil": ("psutil",)}


def _local_environment(java_home):
    # Doctor must remain importable when a required native Python package is
    # broken, including psutil (which the normal process adapter imports).
    env = os.environ.copy()
    for name in ("JAVA_OPTS", "JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS"):
        env.pop(name, None)
    env["PYTHONUTF8"] = "1"
    env["JAVA_HOME"] = str(java_home)
    env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def _python_dependency(name, env):
    try:
        installed_version = version(name)
    except PackageNotFoundError:
        return {"status": "missing"}
    probe_env = dict(env)
    for key in ("PYTHONHOME", "PYTHONPATH"):
        probe_env.pop(key, None)
    # -I ignores inherited Python options and cwd/user-site modules. The
    # selected interpreter still uses its installed (including editable)
    # environment; imports are fresh even if doctor already loaded a package.
    script = "import importlib, sys; [importlib.import_module(name) for name in sys.argv[1:]]; print('Import readiness passed')"
    startup = _probe([sys.executable, "-I", "-B", "-X", "utf8", "-c", script, *_PYTHON_IMPORTS[name]], probe_env)
    startup["scope"] = "Fresh-process import of the installed package and required native bindings; no PDF is opened"
    result = {"status": startup["status"], "version": installed_version, "startup": startup}
    if result["status"] != "available":
        detail = startup.get("output", "") + " " + startup.get("error", "")
        if re.search(r"filename or extension is too long|file name too long|filename too long|path too long|WinError\s*206\b", detail, re.I):
            result["guidance"] = ("The selected Python runtime could not load this package because a filename or path is too long. "
                                  "Create a new installation in a short folder, then run Setup there. "
                                  "Keep the existing installation and all saved reviews unchanged; do not move or delete them. "
                                  "No Windows settings change is required by this check.")
        else:
            result["guidance"] = ("The installed package could not pass a fresh-process import in the selected Python runtime. "
                                  "Review the startup error and rerun Setup in a supported installation folder. "
                                  "Keep existing originals and saved reviews unchanged.")
    return result


def option(settings, name, default=None):
    value = settings.get(name, default) if isinstance(settings, dict) else getattr(settings, name, default)
    return default if value is None else value


def resolve_tools(project_root=None, settings=None):
    root = Path(project_root or option(settings, "project_root", Path(__file__).resolve().parents[2])).resolve()
    known_java = Path(r"C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot")
    java_home = Path(option(settings, "java_home", known_java)).resolve()
    return {"project_root": root, "java_home": java_home,
            "java": java_home / "bin" / ("java.exe" if os.name == "nt" else "java"),
            "odl_jar": Path(option(settings, "odl_jar", root / ".venvs/odl/Lib/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar")).resolve(),
            "validator_cli": Path(option(settings, "validator_cli", root / "tools/verapdf/verapdf.bat")).resolve(),
            "ocr_python": Path(option(settings, "ocr_python", root / ".venvs/ocr/Scripts/python.exe")).resolve(),
            "tesseract_dir": Path(option(settings, "tesseract_dir", root / "tools/tesseract")).resolve()}


def ocr_availability(settings=None):
    """Check configured OCR files only; never probe or claim runtime readiness."""
    try:
        paths = resolve_tools(settings=settings)
        tesseract = paths["tesseract_dir"] / ("tesseract.exe" if os.name == "nt" else "tesseract")
        available = all(path.is_file() for path in (
            paths["ocr_python"], tesseract, paths["tesseract_dir"] / "tessdata/eng.traineddata"))
    except OSError:
        available = False
    message = ("OCR components are present. Their versions and preservation checks still run when OCR is requested."
               if available else
               "OCR is not installed or configured in this copy. Keep OCR off for PDFs with selectable text. "
               "Scanned text needs an OCR-equipped setup or an accessible source document.")
    return {"available": available, "message": message, "runtime_verified": False}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def odl_identity(jar):
    jar = Path(jar)
    result = {"path": str(jar), "expected_version": ODL_VERSION, "status": "missing"}
    if not jar.is_file():
        return result
    try:
        with zipfile.ZipFile(jar) as archive:
            properties = archive.read("META-INF/maven/org.opendataloader/opendataloader-pdf-cli/pom.properties").decode("utf-8")
        match = re.search(r"(?m)^version=(\S+)", properties)
        result.update({"version": match.group(1) if match else None, "sha256": sha(jar)})
        result["status"] = "available" if result["version"] == ODL_VERSION else "unsupported"
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    return result


def _probe(command, env=None, timeout=15):
    result = {"command": [str(x) for x in command], "timeout_seconds": timeout}
    probe_env = dict(env or os.environ)
    probe_env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        run = subprocess.run(result["command"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=probe_env, timeout=timeout, shell=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result.update(status="available" if run.returncode == 0 else "failed", returncode=run.returncode,
                      output=(run.stdout + run.stderr).decode("utf-8", errors="replace")[:8192])
    except subprocess.TimeoutExpired:
        result.update(status="timeout")
    except FileNotFoundError:
        result.update(status="missing")
    except OSError as exc:
        result.update(status="failed", error=str(exc))
    return result


def inventory(project_root=None, settings=None):
    """Probe installed package imports and tool startup, without writing files."""
    paths = resolve_tools(project_root, settings)
    env = _local_environment(paths["java_home"])
    dependencies = {name: _python_dependency(name, env) for name in _PYTHON_IMPORTS}
    java = _probe([paths["java"], "-version"], env)
    java["path"] = str(paths["java"])
    odl = odl_identity(paths["odl_jar"])
    if odl["status"] == "available":
        # This pinned CLI has no --version or --help switch. Its Maven
        # properties provide the version; an empty invocation exercises startup
        # and must report its expected missing-input usage response.
        odl["startup"] = _probe([paths["java"], "-Xmx256m", "-Djava.awt.headless=true", "-jar", paths["odl_jar"]], env)
        startup = odl["startup"]
        startup["scope"] = "Expected missing-input usage response; version read from pinned JAR Maven properties"
        if startup.get("returncode") in (1, 2) and "usage: [options]" in startup.get("output", ""):
            startup["status"] = "available"
        if odl["startup"]["status"] != "available":
            odl["status"] = "failed"
    validator = {"path": str(paths["validator_cli"]), "expected_version": VERAPDF_VERSION, "status": "missing"}
    try:
        if paths["validator_cli"].is_file():
            from .validation import _launch
            command, validator_env, mode = _launch(paths["validator_cli"], paths["java_home"], 256)
            validator.update(_probe(command + ["--version"], validator_env))
            found = re.search(r"veraPDF\s+(\d+\.\d+\.\d+)", validator.get("output", ""), re.I)
            validator["version"] = found.group(1) if found else None
            validator["launch_mode"] = mode
            if validator["status"] == "available" and validator["version"] != VERAPDF_VERSION:
                validator["status"] = "unsupported"
    except (ImportError, OSError, ValueError) as exc:
        validator.update(status="failed", error=str(exc))
    ocr = _probe([paths["ocr_python"], "-I", "-B", "-X", "utf8", "-m", "ocrmypdf", "--version"], env)
    ocr["expected_version"] = OCR_VERSION
    if ocr["status"] == "available" and ocr.get("output", "").strip() != OCR_VERSION:
        ocr["status"] = "unsupported"
    tesseract = paths["tesseract_dir"] / ("tesseract.exe" if os.name == "nt" else "tesseract")
    tess_env = dict(env)
    tess_env["TESSDATA_PREFIX"] = str(paths["tesseract_dir"] / "tessdata")
    tess = _probe([tesseract, "--version"], tess_env)
    tess["english_model"] = str(paths["tesseract_dir"] / "tessdata/eng.traineddata")
    tess["english_model_available"] = Path(tess["english_model"]).is_file()
    all_tools = {"java": java, "opendataloader": odl, "verapdf": validator,
                 "ocrmypdf": ocr, "tesseract": tess}
    python_ready = all(item["status"] == "available" for item in dependencies.values())
    required = [java["status"], odl["status"], validator["status"]] + [x["status"] for x in dependencies.values()]
    return {"schema_version": "phase1-doctor-1.0", "status": "ready" if all(s == "available" for s in required) else "incomplete",
            "paths": {k: str(v) for k, v in paths.items()}, "dependencies": dependencies, "tools": all_tools,
            "capabilities": {"tagging": python_ready and java["status"] == odl["status"] == "available",
                             "validation": python_ready and java["status"] == validator["status"] == "available",
                             "ocr": ocr["status"] == tess["status"] == "available" and tess["english_model_available"]},
            "read_only": True, "downloads": False, "document_network_calls": 0,
            "limitations": ["Import and version probes demonstrate startup only; end-to-end processing is covered by acceptance evidence.",
                            "The verified Java path avoids the unresponsive system Java shortcut; no system configuration is changed."]}


doctor = inventory
