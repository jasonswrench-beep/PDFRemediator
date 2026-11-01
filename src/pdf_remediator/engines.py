"""One explicit local tagging adapter. No downloads, hybrid engine, or AI."""
from pathlib import Path
import shutil

from .doctor import odl_identity, option, resolve_tools, sha
from .process import local_environment, run


def tag(input, output, settings=None, workdir=None, cancel=None):
    source, destination = Path(input).resolve(), Path(output).resolve()
    if source == destination or destination.exists():
        raise FileExistsError("Tagging requires a distinct new output")
    if not source.is_file():
        raise FileNotFoundError(source)
    directory = Path(workdir or destination.parent / "engine").resolve()
    tools = resolve_tools(settings=settings)
    identity = odl_identity(tools["odl_jar"])
    if identity["status"] != "available":
        return {"status": "error", "error": "Pinned local OpenDataLoader JAR unavailable", "identity": identity}
    heap = int(option(settings, "java_heap_mb", 2048))
    if not 64 <= heap <= 16384:
        raise ValueError("Invalid Java heap limit")
    raw = directory / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    expected = raw / (source.stem + "_tagged.pdf")
    if expected.exists():
        raise FileExistsError("Tagging output checkpoint already exists")
    original_hash = sha(source)
    command = [tools["java"], f"-Xmx{heap}m", "-Djava.awt.headless=true", "-Dfile.encoding=UTF8",
               "-jar", tools["odl_jar"], "--format", "tagged-pdf", "--output-dir", raw, source]
    result = run(command, directory, option(settings, "timeout_seconds", 600),
                 option(settings, "memory_limit_bytes", 4 * 1024**3), cancel,
                 local_environment(tools["java_home"]))
    result.update(engine="opendataloader", identity=identity, input_sha256=original_hash,
                  document_network_calls=0, no_ai=True, java_heap_limit_mb=heap)
    if sha(source) != original_hash:
        result.update(status="error", error="Input changed during tagging")
    if result["status"] == "completed":
        if not expected.is_file() or expected.stat().st_size == 0:
            result.update(status="error", error="Tagger reported success without a nonempty PDF")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Copy only after success; the raw checkpoint remains evidence.
            with expected.open("rb") as inp, destination.open("xb") as out:
                shutil.copyfileobj(inp, out)
            result.update(output=str(destination), output_sha256=sha(destination))
    return result


def available():
    return [{"id": "opendataloader", "version": "2.5.13", "local": True,
             "selection": "explicit", "default_for_books": False,
             "limitations": "Phase 0 found book rendering and structure failures; strict gates remain mandatory."}]
