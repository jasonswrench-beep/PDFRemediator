"""Build an offline, internal-only Windows x64 trial installer from reviewed inputs.

No downloads, pip, registry changes, existing installation updates or publication.
The explicit input map is local evidence, never a publisher trust mechanism.
"""
from __future__ import annotations

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import zipfile

MAX_FILES = 20000
MAX_BYTES = 2 * 1024**3
RUNTIME_LOCK = Path(__file__).with_name("windows-runtime-lock.json")
OCR_RUNTIME_LOCK = Path(__file__).with_name("windows-ocr-runtime-lock.json")
OCR_SCRIPT_MEMBERS = {"pdfminer_six-20260107.data/scripts/dumppdf.py", "pdfminer_six-20260107.data/scripts/pdf2txt.py"}
# Files of the locked Tesseract factory that the lock's omission list may never remove.
NATIVE_ALWAYS_KEPT = {"tesseract.exe", "tessdata/pdf.ttf", "doc/LICENSE", "doc/README.md", "doc/AUTHORS"}
# Microsoft's Visual C++ runtime files are left out of the package: Microsoft limits who may pass them on (THIRD-PARTY-NOTICES.md, "Still
# to do", item 2). The programs use the copy Microsoft's own Redistributable puts in the Windows system folder, and the installer and
# launcher check for it (scripts/windows-vc-runtime.cs). MS_RUNTIME_MINIMUM is the newest of the copies that used to be carried (Python
# 3.14.9 and pikepdf 10.17.0, both 14.51.36247.0); a program built with newer tools can need a newer runtime than an older installed one,
# so raise it whenever the locked Python, wheels or Java change.
MS_RUNTIME_MINIMUM = "14.51.36247.0"
MS_RUNTIME_SYSTEM_FILES = {"vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"}  # what the installer checks for
MS_RUNTIME_FILE = re.compile(r"(vcruntime\d+(_\d+)?|msvcp\d+(_[a-z0-9_]+|-[0-9a-f]{32})?|concrt\d+|vcomp\d+|vccorlib\d+|vcamp\d+|ucrtbase|"
                             r"(api|ext)-ms-win-[a-z0-9-]+)\.dll", re.IGNORECASE)
MS_RENAMED_COPY = re.compile(rb"msvcp\d+-[0-9a-f]{32}\.dll", re.IGNORECASE)  # a copy renamed by delvewheel, as in pikepdf's wheel
# What the launcher program runs: no argument opens the default browser, --no-open only makes sure the service is running (the launcher
# program shows its own window), --stop asks the service to stop (the launcher does that when its window is closed).
LAUNCH_PORTABLE = ('from pathlib import Path\nimport sys\nfrom pdf_remediator.launcher import launch, stop\n'
                   'root = Path(__file__).resolve().parent\ndata_dir, config = root/"output/review-app", root/"local-runtime.toml"\n'
                   'arguments = sys.argv[1:]\n'
                   'if arguments == ["--stop"]:\n    stop(data_dir=data_dir)\n'
                   'else:\n    launch(data_dir=data_dir, config_path=config, open_browser=arguments != ["--no-open"])\n')
# The FreeType License asks binary redistributions to carry this credit and a disclaimer in the documentation. The year is that of the
# FreeType versions carried: Pillow 13.0.0 and the Java runtime have 2.14.3 (released 2026-03-22) and PDFium in pypdfium2 5.14.0 has a
# snapshot committed 2026-08-24. Check the year again whenever Pillow, pypdfium2 or the Java runtime change.
FREETYPE_CREDIT = ("Portions of this software are copyright © 2026 The FreeType Project (www.freetype.org). All rights reserved.\n"
                   "This software is based in part on the work of the FreeType Team.\n")
MS_RUNTIME_REFERENCE = re.compile(rb"(vcruntime|msvcp|concrt|vcomp|vccorlib|vcamp)140(_[a-z0-9_]+)?\.dll", re.IGNORECASE)
ICON_SVG = "src/pdf_remediator/web_assets/PDFRemediator.svg"
ICON_ICO = "src/pdf_remediator/web_assets/PDFRemediator.ico"
ICON_ASSETS = {ICON_SVG, ICON_ICO}
EDITOR_FONT_ASSETS = {
    "src/pdf_remediator/data/NotoSans-Regular.ttf": "2ec33f84606cbaa0a1a944488e14f97faf2f6a25ecdd8354f5358f06da13c7d9",
    "src/pdf_remediator/data/NotoSans-OFL.txt": "b0f5719689c03ed5165e834df36066f5b05811230cee8acd9d5f5a1f17250ec8",
    "src/pdf_remediator/data/NotoSans-PROVENANCE.txt": "d85cbcb77c60e5d4d204c9092e3599e73b301728c9550d2e63f81d086cec6262",
}
RESERVED = {"CON", "PRN", "AUX", "NUL", *("COM" + str(i) for i in range(1, 10)),
            *("LPT" + str(i) for i in range(1, 10))}


class Refusal(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def safe_name(name):
    require(isinstance(name, str) and bool(name) and "\\" not in name,
            "Archive paths must be nonempty forward-slash relative paths")
    parts = name.rstrip("/").split("/")
    require(not name.startswith("/") and all(parts), "Absolute or empty archive path")
    for part in parts:
        require(part not in (".", "..") and not part.endswith((".", " ")) and
                not any(ord(c) < 32 or c in '<>:"|?*' for c in part), "Nonportable archive path")
        require(part.split(".")[0].upper() not in RESERVED, "Reserved Windows path")
    return PurePosixPath(*parts).as_posix()


def regular(path):
    path = Path(path).absolute()
    for part in [path, *path.parents]:
        if part.exists():
            data = part.lstat()
            require(not stat.S_ISLNK(data.st_mode) and not getattr(data, "st_file_attributes", 0) & 1024,
                    "Links and reparse points are not accepted")
    require(path.is_file(), "Missing regular input file: " + str(path))
    return path


def checked_file(item):
    path = regular(item["path"])
    require(re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")) is not None,
            "Every input requires an explicit SHA-256")
    require(sha(path) == item["sha256"], "Reviewed input hash mismatch: " + path.name)
    require(isinstance(item.get("origin"), str) and bool(item["origin"]), "Input origin is required")
    return path


def load_runtime_lock(path=None, schema="windows-private-runtime-lock-1"):
    """The checked-in exact lock is authoritative, never an arbitrary input plan."""
    from packaging.utils import canonicalize_name, parse_wheel_filename
    from packaging.version import Version
    raw = regular(RUNTIME_LOCK if path is None else path).read_bytes()
    lock = json.loads(raw)
    require(lock.get("schema") == schema, "Unrecognized runtime lock")
    runtime = lock["python"]
    version = Version(runtime["version"])
    require(not version.is_prerelease and not version.is_devrelease and len(version.release) == 3,
            "Runtime lock requires an exact stable Python version")
    abi = "cp" + "".join(map(str, version.release[:2]))
    require(runtime["implementation"] == "cpython" and runtime["architecture"] == "win_amd64" and
            runtime["threading"] == "standard-GIL" and
            runtime["abi"] == abi and runtime["filename"] == "python-" + str(version) + "-embed-amd64.zip",
            "Runtime lock identity is inconsistent")
    require(runtime["origin"] == "https://www.python.org/ftp/python/" + str(version) + "/" + runtime["filename"],
            "Runtime lock requires the exact official Python archive URL")
    require(re.fullmatch(r"[0-9a-f]{64}", runtime.get("sha256", "")) is not None, "Invalid runtime lock digest")
    wheels = lock["wheels"]
    names = []
    for item in wheels:
        name, wheel_version, _, _ = parse_wheel_filename(item["filename"])
        require(item["name"] == canonicalize_name(item["name"]) == name and str(wheel_version) == item["version"],
                "Runtime lock wheel identity is inconsistent")
        require(re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")) is not None and
                item["origin"].startswith("https://files.pythonhosted.org/packages/") and
                item["origin"].endswith("/" + item["filename"]), "Invalid runtime lock wheel origin or digest")
        names.append(item["name"])
    require(len(set(names)) == len(names) and bool(names), "Runtime lock wheel set is empty or duplicated")
    roots = lock["direct_dependencies"]
    require(bool(roots) and len(set(roots)) == len(roots) and set(roots) <= set(names) and
            all(name == canonicalize_name(name) for name in roots), "Invalid direct dependency roots")
    return lock, hashlib.sha256(raw).hexdigest(), raw


def load_ocr_lock():
    lock, digest, raw = load_runtime_lock(OCR_RUNTIME_LOCK, "windows-private-ocr-runtime-lock-1")
    require(lock["python"] == load_runtime_lock()[0]["python"], "OCR and application Python locks differ")
    require(lock["direct_dependencies"] == ["ocrmypdf"] and len(lock["wheels"]) == 31 and
            not {"pyyaml", "psutil"} & {item["name"] for item in lock["wheels"]}, "Unexpected exact OCR dependency set")
    native = lock["native"]
    require(native["origin"] == "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/" + native["filename"] and
            native["version"] == "5.5.3.20260724" and re.fullmatch(r"[0-9a-f]{64}", native["sha256"]) is not None,
            "Invalid exact native OCR source")
    files = native["files"]
    require(len(files) == 138 and {"tesseract.exe", "tessdata/pdf.ttf", "doc/LICENSE", "doc/README.md"} <= set(files),
            "Incomplete native OCR factory lock")
    require(len({safe_name(name).casefold() for name in files}) == len(files) and
            all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in files.values()), "Invalid native OCR file map")
    omit = native.get("omit", [])
    require(isinstance(omit, list) and omit == sorted(set(omit)) and set(omit) <= set(files) and not NATIVE_ALWAYS_KEPT & set(omit),
            "Invalid native OCR omission list")
    models = lock["models"]
    require(len(models) == 4 and {row["filename"] for row in models} == {"eng.traineddata", "osd.traineddata", "LICENSE", "README.md"} and
            lock["enabled_languages"] == ["eng"], "Only the exact English/orientation model and legal set is supported")
    for row in models:
        require(row["version"] == "87416418657359cb625c412a48b6e1d6d41c29bd" and
                row["origin"] == "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/" + row["version"] + "/" + row["filename"] and
                re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None, "Invalid immutable model/legal lock")
        require("tessdata/" + row["filename"] not in files, "Model inputs collide with the native factory")
    return lock, digest, raw


def check_ocr_dependency_closure(lock, inspected):
    """Resolve the exact target's active extras without enabling unrelated options."""
    from packaging.utils import canonicalize_name
    from packaging.version import Version
    selected = {item["name"]: item["version"] for item in lock["wheels"]}
    require(set(inspected) == set(selected), "Inspected OCR wheels do not match the exact lock")
    reached, extras = set(lock["direct_dependencies"]), {name: set() for name in selected}
    require(reached <= set(selected), "OCR dependency root is missing")
    changed = True
    while changed:
        changed = False
        for name in sorted(reached):
            for requirement in inspected[name]:
                environments = [dict(runtime_environment(lock["python"]), extra=extra) for extra in {"", *extras[name]}]
                if requirement.marker is not None and not any(requirement.marker.evaluate(env) for env in environments):
                    continue
                dependency = canonicalize_name(requirement.name)
                require(not requirement.url and dependency in selected and Version(selected[dependency]) in requirement.specifier,
                        "Locked OCR closure does not satisfy " + name + ": " + str(requirement))
                requested = {canonicalize_name(extra) for extra in requirement.extras}
                if dependency not in reached or not requested <= extras[dependency]:
                    changed = True
                    reached.add(dependency)
                    extras[dependency].update(requested)
    require(reached == set(selected), "OCR lock contains unreachable or unnecessary wheels")
    return {name: sorted(values) for name, values in extras.items() if values}


def prepare_ocr_inputs(plan):
    require(type(plan.get("ocr_enabled")) is bool, "Explicit OCR enabled policy is required")
    if not plan["ocr_enabled"]:
        require("ocr" not in plan, "Disabled OCR cannot carry optional runtime inputs")
        return None
    item = plan.get("ocr")
    require(isinstance(item, dict) and set(item) == {"runtime_lock_sha256", "python", "wheels", "tesseract", "models"},
            "Exact optional OCR input plan required")
    lock, digest, raw = load_ocr_lock()
    require(item["runtime_lock_sha256"] == digest, "OCR plan does not bind the checked-in exact lock")
    python = check_locked_input(item["python"], lock["python"])
    expected = {row["name"]: row for row in lock["wheels"]}
    require(len(item["wheels"]) == len(expected) and {row["name"] for row in item["wheels"]} == set(expected),
            "Unexpected OCR wheel dependency set")
    wheels, inspected = [], {}
    for row in item["wheels"]:
        path = check_locked_input(row, expected[row["name"]])
        inspected[row["name"]] = inspect_wheel(path, row, lock["python"], all_requirements=True)
        wheels.append(path)
    extras = check_ocr_dependency_closure(lock, inspected)
    factory = item["tesseract"]
    require(factory.get("origin") == lock["native"]["origin"] and factory.get("files") == lock["native"]["files"],
            "Native OCR factory differs from the checked-in exact lock")
    require(snapshot(Path(factory["root"])) == factory["files"], "Native OCR factory membership or bytes differ")
    models = {row["filename"]: row for row in lock["models"]}
    require(len(item["models"]) == len(models) and {Path(row["path"]).name for row in item["models"]} == set(models),
            "Unexpected OCR model/legal input set")
    checked_models = [(check_locked_input(row, models[Path(row["path"]).name]), row) for row in item["models"]]
    return {"lock": lock, "sha256": digest, "raw": raw, "python": python, "wheels": wheels,
            "factory": factory, "models": checked_models, "active_extras": extras}


def check_locked_input(item, locked):
    path = checked_file(item)
    require(path.name == locked["filename"] and all(item.get(field) == locked[field]
            for field in ("version", "sha256", "origin")), "Input differs from the checked-in exact runtime lock")
    return path


def runtime_environment(runtime):
    # Evaluate wheel markers for the packaged target, independently of the build host.
    minor = ".".join(runtime["version"].split(".")[:2])
    return {"implementation_name": "cpython", "implementation_version": runtime["version"],
            "os_name": "nt", "platform_machine": "AMD64", "platform_python_implementation": "CPython",
            "platform_release": "", "platform_system": "Windows", "platform_version": "",
            "python_full_version": runtime["version"], "python_version": minor, "sys_platform": "win32", "extra": ""}


def check_dependency_closure(lock, inspected):
    from packaging.utils import canonicalize_name
    from packaging.version import Version
    selected = {item["name"]: item["version"] for item in lock["wheels"]}
    require(set(inspected) == set(selected), "Inspected wheels do not match the exact lock")
    graph = {}
    for name, requirements in inspected.items():
        graph[name] = []
        for requirement in requirements:
            dependency = canonicalize_name(requirement.name)
            require(not requirement.url and not requirement.extras, "Active URL or extra dependencies are unsupported")
            require(dependency in selected and Version(selected[dependency]) in requirement.specifier,
                    "Locked dependency closure does not satisfy " + name + ": " + str(requirement))
            graph[name].append(dependency)
    reached, pending = set(), list(lock["direct_dependencies"])
    while pending:
        name = pending.pop()
        if name not in reached:
            reached.add(name)
            pending.extend(graph[name])
    require(reached == set(selected), "Locked dependency set contains unreachable or unnecessary wheels")


def prepare_runtime_inputs(plan):
    lock, lock_sha, lock_raw = load_runtime_lock()
    runtime = lock["python"]
    require(plan.get("runtime_lock_sha256") == lock_sha, "Input plan does not bind the checked-in exact runtime lock")
    python = check_locked_input(plan["python"], runtime)
    wheels = plan["wheels"]
    expected = {item["name"]: item for item in lock["wheels"]}
    require(len(wheels) == len(expected) and {item["name"] for item in wheels} == set(expected),
            "Unexpected wheel dependency set")
    prepared, inspected = [], {}
    for item in wheels:
        path = check_locked_input(item, expected[item["name"]])
        inspected[item["name"]] = inspect_wheel(path, item, runtime)
        prepared.append(path)
    check_dependency_closure(lock, inspected)
    return lock, lock_sha, lock_raw, python, prepared


def entries(archive):
    seen, total = set(), 0
    infos = archive.infolist()
    require(len(infos) <= MAX_FILES, "Archive file limit exceeded")
    for item in infos:
        name = safe_name(item.filename)
        folded = name.casefold()
        require(folded not in seen, "Duplicate or case-colliding archive member")
        seen.add(folded)
        mode = item.external_attr >> 16
        require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "Nonregular archive member")
        require(not item.flag_bits & 1, "Encrypted archive member")
        total += item.file_size
        require(total <= MAX_BYTES and item.file_size <= MAX_BYTES, "Archive byte limit exceeded")
        yield item, name


def is_microsoft_runtime(name):
    return MS_RUNTIME_FILE.fullmatch(PurePosixPath(name).name) is not None


def extract_checked(archive_path, target, occupied, left_out=None):
    """Extract after every member name passed the checks; with a left_out list, Microsoft runtime files are skipped and listed there."""
    with zipfile.ZipFile(archive_path) as archive:
        prepared = list(entries(archive))
        for item, name in prepared:
            key = (target / name).absolute().as_posix().casefold()
            if item.is_dir():
                continue
            if left_out is not None and is_microsoft_runtime(name):
                left_out.append(name)
                continue
            require(key not in occupied, "Input files collide")
            occupied.add(key)
            destination = target.joinpath(*name.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)


def inspect_wheel(path, item, runtime=None, *, all_requirements=False):
    # Filename tags and actual metadata must independently match the selected
    # CPython x64 dependency lock; a label in the local plan is insufficient.
    from packaging.tags import cpython_tags, compatible_tags, parse_tag
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name, parse_wheel_filename
    if runtime is None:
        runtime = load_runtime_lock()[0]["python"]
    minor = tuple(int(n) for n in runtime["version"].split(".")[:2])
    expected_tags = set(cpython_tags(minor, [runtime["abi"]], ["win_amd64"]))
    expected_tags.update(compatible_tags(minor, runtime["abi"], ["win_amd64"]))
    name, version, _, tags = parse_wheel_filename(path.name)
    require(name == canonicalize_name(item["name"]) and str(version) == item["version"] and bool(tags & expected_tags),
            "Wheel filename does not match the selected dependency/runtime")
    with zipfile.ZipFile(path) as archive:
        infos = list(entries(archive))
        metadata = [x for x, name in infos if name.endswith(".dist-info/METADATA")]
        require(len(metadata) == 1, "Wheel must contain one dependency metadata record")
        wheel_info = [x for x, name in infos if name.endswith(".dist-info/WHEEL")]
        require(len(wheel_info) == 1 and wheel_info[0].filename.rsplit("/", 1)[0] == metadata[0].filename.rsplit("/", 1)[0],
                "Wheel must contain its matching format metadata")
        wheel_fields = BytesParser().parsebytes(archive.read(wheel_info[0]))
        require(wheel_fields.get_all("Wheel-Version", []) == ["1.0"], "Unsupported wheel format version")
        metadata_tags = set()
        for tag in wheel_fields.get_all("Tag", []):
            metadata_tags.update(parse_tag(tag))
        require(metadata_tags == tags, "Wheel format tags do not match the reviewed filename")
        fields = BytesParser().parsebytes(archive.read(metadata[0]))
        require(len(fields.get_all("Name", [])) == len(fields.get_all("Version", [])) == 1 and
                canonicalize_name(fields["Name"]) == name and fields["Version"] == item["version"],
                "Wheel metadata does not match the selected dependency")
        requires_python = fields.get_all("Requires-Python", [])
        require(len(requires_python) == 1 and runtime["version"] in SpecifierSet(requires_python[0]),
                "Wheel Requires-Python does not support the exact locked runtime")
        dependencies = []
        for text in fields.get_all("Requires-Dist", []):
            requirement = Requirement(text)
            if all_requirements or requirement.marker is None or requirement.marker.evaluate(runtime_environment(runtime)):
                dependencies.append(requirement)
        data_root = metadata[0].filename.split("/")[0].removesuffix(".dist-info") + ".data"
        for _, member in infos:
            if ".data/" in member:
                parts = member.split("/")
                inert_script = all_requirements and path.name == "pdfminer_six-20260107-py3-none-any.whl" and member in OCR_SCRIPT_MEMBERS
                require(parts[0] == data_root and len(parts) > 2 and (parts[1] in ("data", "purelib", "platlib") or inert_script),
                        "Wheel relocation scheme is unsupported")
        if all_requirements:
            verify_wheel_record(archive, infos, metadata[0].filename.rsplit("/", 1)[0])
        return dependencies


def verify_wheel_record(archive, infos, dist_info):
    record = dist_info + "/RECORD"
    names = {name for item, name in infos if not item.is_dir()}
    require(record in names, "OCR wheel RECORD is missing")
    rows = list(csv.reader(io.StringIO(archive.read(record).decode("utf-8"))))
    require(all(len(row) == 3 for row in rows) and len({row[0] for row in rows}) == len(rows) and
            {row[0] for row in rows} == names, "OCR wheel RECORD membership differs")
    for name, digest, size in rows:
        if name == record:
            require(not digest and not size, "OCR wheel RECORD cannot hash itself")
            continue
        algorithm, separator, encoded = digest.partition("=")
        require(separator and algorithm in ("sha256", "sha384", "sha512"), "OCR wheel RECORD requires a strong hash")
        data = archive.read(name)
        actual = base64.urlsafe_b64encode(hashlib.new(algorithm, data).digest()).rstrip(b"=").decode("ascii")
        require(encoded == actual and size == str(len(data)), "OCR wheel RECORD hash or size differs")


def extract_wheel(path, python_root, occupied, *, ocr_scripts=False, left_out=None):
    relocations = []
    with zipfile.ZipFile(path) as archive:
        prepared = list(entries(archive))
        for item, name in prepared:
            if item.is_dir():
                continue
            parts = name.split("/")
            if parts[0].endswith(".data"):
                inert_script = ocr_scripts and path.name == "pdfminer_six-20260107-py3-none-any.whl" and name in OCR_SCRIPT_MEMBERS
                require(len(parts) > 2 and (parts[1] in ("data", "purelib", "platlib") or inert_script), "Unsupported wheel relocation")
                base = python_root / "Scripts" if inert_script else python_root if parts[1] == "data" else python_root / "Lib/site-packages"
                destination = base.joinpath(*parts[2:])
                if left_out is not None and is_microsoft_runtime(name):
                    left_out.append(destination.relative_to(python_root).as_posix())
                    continue
                relocations.append({"wheel_member": name, "installed_path": destination.relative_to(python_root).as_posix()})
            else:
                destination = python_root.joinpath("Lib", "site-packages", *parts)
                if left_out is not None and is_microsoft_runtime(name):
                    left_out.append(destination.relative_to(python_root).as_posix())
                    continue
            key = destination.absolute().as_posix().casefold()
            require(key not in occupied, "Wheel installation files collide")
            occupied.add(key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)
    return relocations


def copy_map(item, target, left_out=None):
    """Copy exactly the listed files; with a left_out list, Microsoft runtime files are neither read nor copied and are listed there."""
    root = Path(item["root"]).absolute()
    require(isinstance(item.get("origin"), str) and item["origin"], "Tree origin is required")
    files = item.get("files")
    require(isinstance(files, dict) and 0 < len(files) <= MAX_FILES, "Explicit nonempty file map required")
    names = [safe_name(name) for name in files]
    require(len({n.casefold() for n in names}) == len(names), "Tree file names collide")
    total = 0
    for name in sorted(names):
        if left_out is not None and is_microsoft_runtime(name):
            left_out.append(name)
            continue
        source = regular(root.joinpath(*name.split("/")))
        require(sha(source) == files[name], "Reviewed tree changed: " + name)
        total += source.stat().st_size
        require(total <= MAX_BYTES, "Tree byte limit exceeded")
        destination = target.joinpath(*name.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        require(sha(source) == files[name] == sha(destination), "Input changed during copying")


def redirect_renamed_runtime(root, left_out):
    """Point the files that load a renamed copy of Microsoft's C++ library at the one in the Windows system folder.

    pikepdf's wheel carries its own copy of msvcp140.dll under a hashed name (msvcp140-<32 hex>.dll), and its two native files import it by
    that name. With the copy left out, each such name is rewritten in place to plain msvcp140.dll (shorter, so the rest of the old name
    becomes NUL bytes). Every file that holds the name must hold it exactly once, as a whole NUL-ended string, or the build is refused.
    """
    root = Path(root)
    renamed = sorted({PurePosixPath(name).name.lower() for name in left_out
                      if MS_RENAMED_COPY.fullmatch(PurePosixPath(name).name.encode("ascii", "replace"))})
    changes = []
    for old_name in renamed:
        old, new = old_name.encode("ascii"), re.sub(rb"-[0-9a-f]{32}", b"", old_name.encode("ascii"))
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in (".dll", ".pyd"):
                continue
            data = path.read_bytes()
            lowered = data.lower()
            count = lowered.count(old)
            if not count:
                continue
            at = lowered.index(old)
            require(count == 1 and data[at + len(old):at + len(old) + 1] == b"\0",
                    "Unexpected layout where " + path.name + " refers to the left-out Microsoft file " + old_name)
            patched = data[:at] + new + b"\0" * (len(old) - len(new)) + data[at + len(old):]
            require(len(patched) == len(data), "Redirected file changed size")
            path.write_bytes(patched)
            changes.append({"file": path.relative_to(root).as_posix(), "was": old_name, "now": new.decode("ascii"),
                            "sha256_before": hashlib.sha256(data).hexdigest(), "sha256_after": hashlib.sha256(patched).hexdigest()})
    return changes


def record_microsoft_runtime(microsoft, label, root, left_out):
    """Redirect the renamed copies under root and note what was left out and changed, with names relative to the payload."""
    changes = redirect_renamed_runtime(root, left_out)
    microsoft["left_out"].extend(label + "/" + name for name in left_out)
    microsoft["redirected"].extend({**change, "file": label + "/" + change["file"]} for change in changes)


def check_no_microsoft_runtime(payload):
    """Last check on the assembled payload: no Microsoft runtime file, and no program that needs one the installer does not check for."""
    payload = Path(payload)
    files = sorted(p for p in payload.rglob("*") if p.is_file())
    present = [p.relative_to(payload).as_posix() for p in files if is_microsoft_runtime(p.name)]
    require(not present, "Microsoft runtime files must not enter the package: " + ", ".join(present[:5]))
    for path in files:
        if path.suffix.lower() not in (".dll", ".pyd", ".exe"):
            continue
        data = path.read_bytes()
        shown = path.relative_to(payload).as_posix()
        require(MS_RENAMED_COPY.search(data) is None, shown + " still refers to a renamed copy of a Microsoft runtime file")
        for found in sorted({m.group(0).decode("ascii").lower() for m in MS_RUNTIME_REFERENCE.finditer(data)}):
            require(found in MS_RUNTIME_SYSTEM_FILES,
                    shown + " needs " + found + ", which the installer does not check for; add it to the installer check first")


def tesseract_runtime_view(factory, omit):
    """The Tesseract files that enter the package: the locked factory without the reviewed omissions.

    The factory is the whole extracted Windows installer. The app runs only tesseract.exe, so the unused training programs, their
    manual pages, the installer's leftover plug-ins, the debugging viewer's jars and the libraries only they load are left out,
    and their licences never have to be carried. Every omitted library must be one that tesseract.exe does not need, found by
    following the library names that each program refers to; the omission list can never remove one that it does.
    """
    files = factory["files"]
    omitted = set(omit)
    require(omitted <= set(files) and not NATIVE_ALWAYS_KEPT & omitted, "Invalid native OCR omission list")
    kept = {name: digest for name, digest in files.items() if name not in omitted}
    root = Path(factory["root"]).absolute()
    libraries = {PurePosixPath(name).name.lower(): name for name in files if "/" not in name and name.lower().endswith(".dll")}
    needed, queue = set(), ["tesseract.exe"]
    while queue:
        current = queue.pop()
        data = regular(root.joinpath(*current.split("/"))).read_bytes().lower()
        for short, name in libraries.items():
            if name != current and name not in needed and short.encode("ascii") in data:
                needed.add(name)
                queue.append(name)
    require(needed <= set(kept), "tesseract.exe needs a library the omission list removes: " + ", ".join(sorted(needed - set(kept))))
    return {**factory, "files": kept}


def write_new(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def snapshot(root):
    return {p.relative_to(root).as_posix(): sha(regular(p)) for p in sorted(root.rglob("*")) if p.is_file()}


def validate_source(source):
    files = source.get("files")
    require(isinstance(files, dict) and ICON_ASSETS <= set(files), "Both exact reviewed application icon assets are required")
    require(all(n.startswith("src/pdf_remediator/") and
                (Path(n).suffix in (".py", ".html", ".css", ".js", ".tex", ".txt") or n in ICON_ASSETS or n in EDITOR_FONT_ASSETS)
                for n in files), "Only application source and exact declared icon assets enter the package")
    require(all(files.get(name) == digest for name, digest in EDITOR_FONT_ASSETS.items()),
            "The exact OCR editor font, complete license and provenance must accompany every package")


def package_icon(source, payload):
    require(all(sha(regular(payload / name)) == source["files"][name] for name in ICON_ASSETS),
            "Copied reviewed application icon assets changed")
    return payload / ICON_ICO


def compile_cs(csc, source, output, resources=(), *, icon):
    icon = regular(icon)
    icon_sha = sha(icon)
    args = [str(csc), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
            "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:System.Web.Extensions.dll",
            "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll",
            "/win32icon:" + str(icon), "/out:" + str(output),
            *["/resource:" + str(p) + "," + n for p, n in resources], str(source)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)
    require(result.returncode == 0, "Windows compiler refused: " + result.stdout + result.stderr)
    require(sha(regular(icon)) == icon_sha, "Application icon changed during compilation")


def assemble_ocr_runtime(prepared, payload, occupied, microsoft=None):
    lock, python_root = prepared["lock"], payload / "runtime/ocr"
    runtime = lock["python"]
    microsoft = {"left_out": [], "redirected": []} if microsoft is None else microsoft
    left_out = []
    require(sha(prepared["python"]) == runtime["sha256"], "OCR Python input changed after preflight")
    extract_checked(prepared["python"], python_root, occupied, left_out)
    require(sha(prepared["python"]) == runtime["sha256"], "OCR Python changed during extraction")
    hashes = {row["filename"]: row["sha256"] for row in lock["wheels"]}
    relocations = []
    for path in prepared["wheels"]:
        require(sha(path) == hashes[path.name], "OCR wheel changed after preflight")
        relocations.extend({"wheel": path.name, **entry}
                           for entry in extract_wheel(path, python_root, occupied, ocr_scripts=True, left_out=left_out))
        require(sha(path) == hashes[path.name], "OCR wheel changed during extraction")
    record_microsoft_runtime(microsoft, "runtime/ocr", python_root, left_out)
    stem = "python" + runtime["abi"][2:]
    require(all((python_root / name).is_file() for name in ("python.exe", stem + ".dll", stem + ".zip", stem + "._pth")),
            "Embedded OCR Python components are missing")
    # No import site, user site, application source, script execution or global PATH.
    (python_root / (stem + "._pth")).write_text(stem + ".zip\n.\nLib/site-packages\n", encoding="ascii")
    require(snapshot(Path(prepared["factory"]["root"])) == lock["native"]["files"], "OCR factory changed after preflight")
    copy_map(tesseract_runtime_view(prepared["factory"], lock["native"].get("omit", [])), payload / "runtime/tesseract")
    require(snapshot(Path(prepared["factory"]["root"])) == lock["native"]["files"], "OCR factory changed during copying")
    for path, row in prepared["models"]:
        require(sha(path) == row["sha256"], "OCR model/legal input changed after preflight")
        destination = payload / "runtime/tesseract/tessdata" / path.name
        with path.open("rb") as source, destination.open("xb") as output:
            shutil.copyfileobj(source, output)
        require(sha(path) == row["sha256"] == sha(destination), "OCR model/legal input changed while copying")
    with (payload / "ocr-runtime-baseline.json").open("xb") as stream:
        stream.write(prepared["raw"])
    return relocations


def runtime_config(ocr_enabled):
    optional = ('ocr_python = "runtime/ocr/python.exe"\ntesseract_dir = "runtime/tesseract"\n' if ocr_enabled else
                'ocr_python = "runtime/not-included/python.exe"\ntesseract_dir = "runtime/not-included"\n')
    return ('[runtime]\nproject_root = "."\njava_home = "runtime/java"\n'
            'odl_jar = "runtime/odl/jar/opendataloader-pdf-cli.jar"\n'
            'validator_cli = "runtime/verapdf/verapdf.bat"\nocr_mode = "off"\n' + optional +
            'preserve_painting = true\nallow_tag_regrouping = false\nrepair_source_mappings = false\n')


def build(plan, output, csc):
    require(os.name == "nt", "Windows x64 build host required")
    require(plan.get("schema") == "windows-internal-inputs-1", "Unrecognized input schema")
    require(plan.get("release_status") == "internal-unqualified", "Only an internal unqualified trial is supported")
    require(plan.get("ai_enabled") is False, "AI must remain disabled")
    require(plan.get("redistribution_cleared") is False, "This builder cannot grant redistribution clearance")
    require(not output.exists(), "Build output already exists; choose a new directory")
    source = plan["source"]
    validate_source(source)
    lock, lock_sha, lock_raw, python, prepared = prepare_runtime_inputs(plan)
    ocr = prepare_ocr_inputs(plan)
    runtime = lock["python"]
    for parent in [output.parent, *output.parent.parents]:
        if parent.exists():
            require(not getattr(parent.lstat(), "st_file_attributes", 0) & 1024 and not parent.is_symlink(),
                    "Output parent is a link or reparse point")
    output.mkdir(parents=True, exist_ok=False)
    payload = output / "payload"
    payload.mkdir()
    occupied = set()
    microsoft = {"left_out": [], "redirected": []}
    left_out = []
    require(sha(python) == runtime["sha256"], "Reviewed Python input changed after preflight")
    extract_checked(python, payload / "runtime/python", occupied, left_out)
    require(sha(python) == runtime["sha256"], "Reviewed Python input changed during extraction")
    relocations = []
    wheel_hashes = {item["filename"]: item["sha256"] for item in lock["wheels"]}
    for path in prepared:
        require(sha(path) == wheel_hashes[path.name], "Reviewed wheel changed after preflight")
        relocations.extend({"wheel": path.name, **entry}
                           for entry in extract_wheel(path, payload / "runtime/python", occupied, left_out=left_out))
        require(sha(path) == wheel_hashes[path.name], "Reviewed wheel changed during extraction")
    record_microsoft_runtime(microsoft, "runtime/python", payload / "runtime/python", left_out)
    # Explicit vendored paths retain embedded isolation; no pip, user site or PATH dependencies.
    stem = "python" + runtime["abi"][2:]
    pth = payload / "runtime/python" / (stem + "._pth")
    require(all((pth.parent / name).is_file() for name in ("python.exe", stem + ".dll", stem + ".zip", pth.name)),
            "Embedded Python runtime components are missing")
    pth.write_text(stem + ".zip\n.\nLib/site-packages\n../../src\n", encoding="ascii")
    ocr_relocations = assemble_ocr_runtime(ocr, payload, occupied, microsoft) if ocr else []
    required = {"java": "bin/java.exe", "odl": "jar/opendataloader-pdf-cli.jar",
                "verapdf": "verapdf.bat"}
    for name, marker in required.items():
        item = plan["native"][name]
        require(marker in item["files"], "Required native entry missing: " + marker)
        native_left_out = []
        copy_map(item, payload / "runtime" / name, native_left_out)
        microsoft["left_out"].extend("runtime/" + name + "/" + left for left in native_left_out)
    require("bin/cli-1.30.3.jar" in plan["native"]["verapdf"]["files"], "Complete selected veraPDF CLI is required")
    require("LICENSE" in plan["native"]["odl"]["files"] and "NOTICE" in plan["native"]["odl"]["files"],
            "OpenDataLoader license and notice must accompany its unchanged JAR")
    require(any(x.startswith("legal/") for x in plan["native"]["java"]["files"]), "Java legal notices required")
    copy_map(source, payload)
    copy_map(plan["notices"], payload / "NOTICES")
    write_new(payload / "local-runtime.toml", runtime_config(bool(ocr)))
    write_new(payload / "launch_portable.py", LAUNCH_PORTABLE)
    write_new(payload / "START-HERE.txt", 'PDF Remediator — internal Windows trial\n\n'
              'Use the PDF Remediator icon the installer put on your desktop (if you left that box ticked), or open PDF Remediator.exe in the install folder.\n'
              'The private local workspace opens in its own window (Microsoft Edge, which comes with Windows;\n'
              'Chrome if Edge is missing; otherwise your default browser). Closing that window stops the program, as does Stop application.\n'
              'It is a web page that runs on this computer, so it looks like one; a stand-alone program window is planned for version 2.0.\n'
              'Your documents are processed locally; originals remain unchanged.\n'
              'Saved work stays under output/review-app.\n'
              'To remove the program, close it, delete the install folder, and delete the PDF Remediator icons from your desktop and Start menu (there is no uninstaller yet).\n'
              'Keep this entire installation in place: saved reviews are bound to their files.\n' +
              ('Local English OCR components are included; OCR stays off until you select it.\n' if ocr else 'OCR components are not included.\n') +
              'Needs Microsoft\'s free Visual C++ Redistributable (x64, version ' + MS_RUNTIME_MINIMUM + ' or newer) on this computer. It is not\n'
              'included because Microsoft\'s licence does not let us pass it on; the installer and launcher check and point to Microsoft\'s page.\n' +
              FREETYPE_CREDIT +
              'This trial has no AI, automatic updater or uninstall/delete action.\n'
              'This is an internal, unsigned, unqualified build. Do not share or release it.\n'
              'Fresh-machine qualification, packaged graphical workflow and licensing review remain open.\n')
    with (payload / "runtime-baseline.json").open("xb") as stream:
        stream.write(lock_raw)
    script_root = Path(__file__).resolve().parent
    vc_runtime_check = (script_root / "windows-vc-runtime.cs").read_text(encoding="utf-8").replace("__MIN_VC_RUNTIME__", MS_RUNTIME_MINIMUM)
    launcher_path = output / "launcher-bound.cs"
    write_new(launcher_path, (script_root / "windows-launcher.cs").read_text(encoding="utf-8") + "\n" + vc_runtime_check)
    compile_cs(csc, launcher_path, payload / "PDF Remediator.exe", icon=package_icon(source, payload))
    package_icon(source, payload)
    check_no_microsoft_runtime(payload)
    metadata = {"schema": "windows-internal-package-1", "release_status": "internal-unqualified",
                "redistribution_cleared": False, "version": "0.3.0", "architecture": "x64",
                "ai_enabled": False, "ocr_enabled": bool(ocr), "ocr_runtime_lock_sha256": ocr["sha256"] if ocr else "",
                "python_version": runtime["version"],
                "runtime_lock_sha256": lock_sha, "python_abi": runtime["abi"],
                "wheel_relocations": relocations, "ocr_wheel_relocations": ocr_relocations,
                "microsoft_runtime": {"minimum_version": MS_RUNTIME_MINIMUM, "left_out": sorted(microsoft["left_out"]),
                                      "redirected_imports": microsoft["redirected"]},
                "files": snapshot(payload), "input_plan_sha256": hashlib.sha256(
                    json.dumps(plan, sort_keys=True).encode()).hexdigest()}
    write_new(payload / "package-manifest.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    archive = output / "payload.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for path in sorted(payload.rglob("*")):
            if path.is_file():
                zipped.write(path, path.relative_to(payload).as_posix())
    installer_source = (script_root / "windows-installer.cs").read_text(encoding="utf-8")
    installer_source = installer_source.replace("__PAYLOAD_SHA256__", sha(archive))
    installer_source = installer_source.replace("__PYTHON_VERSION__", runtime["version"])
    installer_source = installer_source.replace("__PYTHON_ABI__", runtime["abi"])
    installer_source = installer_source.replace("__RUNTIME_LOCK_SHA256__", lock_sha)
    installer_source = installer_source.replace("__OCR_ENABLED__", "true" if ocr else "false")
    installer_source = installer_source.replace("__OCR_RUNTIME_LOCK_SHA256__", ocr["sha256"] if ocr else "")
    installer_source += "\n" + vc_runtime_check
    source_path = output / "installer-bound.cs"
    write_new(source_path, installer_source)
    installer = output / "PDF Remediator Internal Setup.exe"
    compile_cs(csc, source_path, installer, [(archive, "payload.zip")], icon=package_icon(source, payload))
    package_icon(source, payload)
    summary = {"status": "built-internal-unqualified", "installer": str(installer), "installer_sha256": sha(installer),
               "payload_sha256": sha(archive), "payload_files": len(metadata["files"]) + 1,
               "release_status": "internal-unqualified", "redistribution_cleared": False,
               "python_version": runtime["version"], "runtime_lock_sha256": lock_sha,
               "source_files": len(source["files"]), "ai_enabled": False, "ocr_enabled": bool(ocr),
               "ocr_runtime_lock_sha256": ocr["sha256"] if ocr else "",
               "no_runtime_downloads": True, "publisher_authenticated": False,
               "source_plan_sha256": metadata["input_plan_sha256"]}
    write_new(output / "build-summary.json", json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csc", type=Path, default=Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    args = parser.parse_args()
    try:
        result = build(json.loads(args.inputs.read_text(encoding="utf-8")), args.output.absolute(), regular(args.csc))
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        parser.exit(1, "Internal package build refused: " + str(exc) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
