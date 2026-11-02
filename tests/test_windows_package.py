"""Portable refusal/integrity contracts for the offline internal package builder."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import zipfile

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/package-windows.py"
spec = importlib.util.spec_from_file_location("windows_package", SOURCE)
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
TEST_RUNTIME = {"version": "3.14.9", "abi": "cp314"}
RENAMED_COPY = "msvcp140-7c26614e1d733892c2deac7e245ce115.dll"  # pikepdf's wheel carries Microsoft's msvcp140.dll under a hashed name


@pytest.mark.parametrize("missing", sorted(package.ICON_ASSETS))
def test_build_refuses_missing_reviewed_icon_before_runtime_or_output(tmp_path, monkeypatch, missing):
    from types import SimpleNamespace
    monkeypatch.setattr(package, "os", SimpleNamespace(name="nt"))
    plan = {"schema": "windows-internal-inputs-1", "release_status": "internal-unqualified",
            "ai_enabled": False, "redistribution_cleared": False,
            "source": {"files": {name: "0" * 64 for name in package.ICON_ASSETS - {missing}}}}
    output = tmp_path / "new-build"
    with pytest.raises(package.Refusal, match="Both exact reviewed application icon assets"):
        package.build(plan, output, Path("never-executed"))
    assert not output.exists()


@pytest.mark.parametrize("name", ["other.svg", "other.ico", "pdfremediator.svg", "private.png"])
def test_source_icon_extension_does_not_allow_arbitrary_assets(name):
    files = {asset: "0" * 64 for asset in package.ICON_ASSETS}
    files["src/pdf_remediator/web_assets/" + name] = "0" * 64
    with pytest.raises(package.Refusal, match="Only application source and exact declared icon assets"):
        package.validate_source({"files": files})


@pytest.mark.parametrize("name", sorted(package.EDITOR_FONT_ASSETS))
@pytest.mark.parametrize("change", ["missing", "changed"])
def test_source_refuses_missing_or_changed_editor_font_or_notices(name, change):
    files = {asset: "0" * 64 for asset in package.ICON_ASSETS}
    files.update(package.EDITOR_FONT_ASSETS)
    if change == "missing":
        del files[name]
    else:
        files[name] = "0" * 64
    with pytest.raises(package.Refusal, match="exact OCR editor font, complete license and provenance"):
        package.validate_source({"files": files})


@pytest.mark.parametrize("name", ["another.ttf", "NotoSans-Regular.otf", "notosans-regular.ttf"])
def test_font_allowlist_does_not_admit_arbitrary_binary_fonts(name):
    files = {asset: "0" * 64 for asset in package.ICON_ASSETS}
    files.update(package.EDITOR_FONT_ASSETS)
    files["src/pdf_remediator/data/" + name] = "0" * 64
    with pytest.raises(package.Refusal, match="Only application source"):
        package.validate_source({"files": files})


def test_compile_cs_binds_exact_icon_and_resources_with_space_safe_arguments(tmp_path, monkeypatch):
    from types import SimpleNamespace
    icon = tmp_path / "reviewed icon.ico"
    icon.write_bytes(b"authored compiler-input stub; no real executable")
    calls = []
    def compile_stub(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(package.subprocess, "run", compile_stub)
    package.compile_cs(Path("declared-csc"), tmp_path / "source.cs", tmp_path / "output.exe",
                       [(tmp_path / "payload.zip", "payload.zip")], icon=icon)
    argv, options = calls[0]
    assert [arg for arg in argv if arg.startswith("/win32icon:")] == ["/win32icon:" + str(icon)]
    assert "/resource:" + str(tmp_path / "payload.zip") + ",payload.zip" in argv
    assert options == {"capture_output": True, "text": True, "timeout": 120, "check": False}


def test_compile_cs_refuses_icon_changed_during_compilation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    icon = tmp_path / "reviewed.ico"
    icon.write_bytes(b"authored original icon")
    def compile_stub(*args, **kwargs):
        icon.write_bytes(b"authored replacement icon")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(package.subprocess, "run", compile_stub)
    with pytest.raises(package.Refusal, match="icon changed during compilation"):
        package.compile_cs(Path("declared-csc"), tmp_path / "source.cs", tmp_path / "output.exe", icon=icon)


def wheel_metadata(archive, metadata_path, text, filename, requires_python=">=3.11"):
    from packaging.utils import parse_wheel_filename
    _, _, _, tags = parse_wheel_filename(filename)
    archive.writestr(metadata_path, text + ("Requires-Python: " + requires_python + "\n" if requires_python else ""))
    archive.writestr(metadata_path.rsplit("/", 1)[0] + "/WHEEL", "Wheel-Version: 1.0\n" +
                     "".join("Tag: " + str(tag) + "\n" for tag in sorted(tags, key=str)))


@pytest.mark.parametrize("name", ["../file", "/root", "C:/root", "a\\b", "a//b", "a/./b", "a/../b",
    "file.", "folder /x", "AUX.txt", "con", "lpt9.dat", "x:n", "a?b", "a*b", "a|b", 'a"b', "a<b", "a>b", "a\nb", ""])
def test_windows_unsafe_names_refused(name):
    with pytest.raises(package.Refusal):
        package.safe_name(name)


@pytest.mark.parametrize("name", ["runtime/python/python.exe", "src/pdf_remediator/web_assets/app.js", "NOTICES/LICENSE.txt"])
def test_windows_relative_names_accepted(name):
    assert package.safe_name(name) == name


@pytest.mark.parametrize("names", [["a", "A"], ["a", "a"], ["folder/a", "folder/A"]])
def test_archive_conflicting_members_refused(tmp_path, names):
    path = tmp_path / "input.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"data")
    with zipfile.ZipFile(path) as archive, pytest.raises(package.Refusal, match="colliding"):
        list(package.entries(archive))


def test_archive_link_refused_before_extraction(tmp_path):
    path = tmp_path / "link.zip"
    entry = zipfile.ZipInfo("linked")
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(entry, "../outside")
    with zipfile.ZipFile(path) as archive, pytest.raises(package.Refusal, match="Nonregular"):
        list(package.entries(archive))


def test_archive_byte_budget_refused(tmp_path, monkeypatch):
    path = tmp_path / "large.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", b"12345")
    monkeypatch.setattr(package, "MAX_BYTES", 4)
    with zipfile.ZipFile(path) as archive, pytest.raises(package.Refusal, match="byte limit"):
        list(package.entries(archive))


def test_archive_path_failure_writes_nothing(tmp_path):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("safe.txt", "safe")
        archive.writestr("../outside.txt", "bad")
    target = tmp_path / "new"
    with pytest.raises(package.Refusal):
        package.extract_checked(path, target, set())
    assert not target.exists()
    assert not (tmp_path / "outside.txt").exists()


def test_repeated_archive_cannot_replace_prior_file(tmp_path):
    path = tmp_path / "valid.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("keep.txt", "original")
    target, occupied = tmp_path / "new", set()
    package.extract_checked(path, target, occupied)
    with pytest.raises(package.Refusal, match="collide"):
        package.extract_checked(path, target, occupied)
    assert (target / "keep.txt").read_text() == "original"


def test_explicit_native_map_never_copies_unlisted_local_data(tmp_path):
    source = tmp_path / "vendor"
    source.mkdir()
    (source / "java.exe").write_bytes(b"vendor")
    (source / "private.log").write_bytes(b"private")
    target = tmp_path / "new"
    package.copy_map({"root": str(source), "origin": "declared synthetic vendor", "files": {
        "java.exe": package.sha(source / "java.exe")}}, target)
    assert package.snapshot(target) == {"java.exe": hashlib.sha256(b"vendor").hexdigest()}
    assert (source / "private.log").read_bytes() == b"private"


def test_changed_native_file_refused_without_copy(tmp_path):
    source = tmp_path / "vendor"
    source.mkdir()
    (source / "tool").write_bytes(b"changed")
    target = tmp_path / "new"
    with pytest.raises(package.Refusal, match="changed"):
        package.copy_map({"root": str(source), "origin": "synthetic", "files": {"tool": "0" * 64}}, target)
    assert not target.exists()


def test_explicit_map_cannot_escape_root(tmp_path):
    outside = tmp_path / "keep.txt"
    outside.write_bytes(b"original")
    with pytest.raises(package.Refusal):
        package.copy_map({"root": str(tmp_path / "vendor"), "origin": "synthetic", "files": {
            "../keep.txt": package.sha(outside)}}, tmp_path / "new")
    assert outside.read_bytes() == b"original"


def test_reviewed_download_hash_required(tmp_path):
    file = tmp_path / "archive.zip"
    file.write_bytes(b"changed")
    with pytest.raises(package.Refusal, match="hash mismatch"):
        package.checked_file({"path": str(file), "sha256": "0" * 64, "origin": "https://example.invalid"})


def test_download_origin_required(tmp_path):
    file = tmp_path / "archive.zip"
    file.write_bytes(b"archive")
    with pytest.raises(package.Refusal, match="origin"):
        package.checked_file({"path": str(file), "sha256": package.sha(file)})


@pytest.mark.parametrize("filename", ["pillow-12.3.0-cp312-cp312-win_amd64.whl",
                                      "pillow-12.3.0-cp314-cp314t-win_amd64.whl",
                                      "pillow-12.3.0-cp314-cp314-manylinux_2_28_x86_64.whl"])
def test_nonportable_wheel_tag_refused(tmp_path, filename):
    file = tmp_path / filename
    with zipfile.ZipFile(file, "w") as archive:
        wheel_metadata(archive, "pillow-12.3.0.dist-info/METADATA", "Name: pillow\nVersion: 12.3.0\n", file.name)
    with pytest.raises(package.Refusal, match="runtime"):
        package.inspect_wheel(file, {"name": "pillow", "version": "12.3.0"}, TEST_RUNTIME)


def test_wheel_metadata_must_match_reviewed_filename(tmp_path):
    file = tmp_path / "packaging-26.3-py3-none-any.whl"
    with zipfile.ZipFile(file, "w") as archive:
        wheel_metadata(archive, "packaging-26.3.dist-info/METADATA", "Name: packaging\nVersion: 1.0\n", file.name)
    with pytest.raises(package.Refusal, match="metadata"):
        package.inspect_wheel(file, {"name": "packaging", "version": "26.3"}, TEST_RUNTIME)


def test_wheel_unsupported_relocation_refused(tmp_path):
    file = tmp_path / "packaging-26.3-py3-none-any.whl"
    with zipfile.ZipFile(file, "w") as archive:
        wheel_metadata(archive, "packaging-26.3.dist-info/METADATA", "Name: packaging\nVersion: 26.3\n", file.name)
        archive.writestr("packaging-26.3.data/scripts/unexpected.exe", "data")
    with pytest.raises(package.Refusal, match="relocation"):
        package.inspect_wheel(file, {"name": "packaging", "version": "26.3"}, TEST_RUNTIME)


def test_valid_wheel_metadata_and_tag(tmp_path):
    file = tmp_path / "packaging-26.3-py3-none-any.whl"
    with zipfile.ZipFile(file, "w") as archive:
        wheel_metadata(archive, "packaging-26.3.dist-info/METADATA", "Name: packaging\nVersion: 26.3\n", file.name)
    assert package.inspect_wheel(file, {"name": "packaging", "version": "26.3"}, TEST_RUNTIME) == []


def test_wheel_documentation_relocation_keeps_vendor_bytes(tmp_path):
    file = tmp_path / "fonttools-4.67.0-cp314-cp314-win_amd64.whl"
    with zipfile.ZipFile(file, "w") as archive:
        wheel_metadata(archive, "fonttools-4.67.0.dist-info/METADATA", "Name: fonttools\nVersion: 4.67.0\n", file.name)
        archive.writestr("fontTools/__init__.py", "# vendor")
        archive.writestr("fonttools-4.67.0.data/data/share/man/man1/ttx.1", b"unchanged vendor manual")
    package.inspect_wheel(file, {"name": "fonttools", "version": "4.67.0"}, TEST_RUNTIME)
    root = tmp_path / "python"
    moved = package.extract_wheel(file, root, set())
    assert (root / "share/man/man1/ttx.1").read_bytes() == b"unchanged vendor manual"
    assert (root / "Lib/site-packages/fontTools/__init__.py").read_text() == "# vendor"
    assert moved == [{"wheel_member": "fonttools-4.67.0.data/data/share/man/man1/ttx.1", "installed_path": "share/man/man1/ttx.1"}]


def test_wheel_relocation_cannot_replace_another_component(tmp_path):
    file = tmp_path / "collision.whl"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("demo.data/data/python.exe", b"replacement")
    root = tmp_path / "python"
    root.mkdir()
    (root / "python.exe").write_bytes(b"original")
    with pytest.raises(package.Refusal, match="collide"):
        package.extract_wheel(file, root, {(root / "python.exe").absolute().as_posix().casefold()})
    assert (root / "python.exe").read_bytes() == b"original"


@pytest.mark.parametrize("requires_python", [None, ">=3.15", "<3.14"])
def test_wheel_requires_python_must_include_exact_runtime(tmp_path, requires_python):
    file = tmp_path / "packaging-26.3-py3-none-any.whl"
    with zipfile.ZipFile(file, "w") as archive:
        wheel_metadata(archive, "packaging-26.3.dist-info/METADATA", "Name: packaging\nVersion: 26.3\n",
                       file.name, requires_python)
    with pytest.raises(package.Refusal, match="Requires-Python"):
        package.inspect_wheel(file, {"name": "packaging", "version": "26.3"}, TEST_RUNTIME)


@pytest.mark.parametrize("format_text", [None, "Wheel-Version: 2.0\nTag: py3-none-any\n",
                                         "Wheel-Version: 1.0\nTag: cp313-cp313-win_amd64\n"])
def test_wheel_format_metadata_must_match_filename(tmp_path, format_text):
    file = tmp_path / "packaging-26.3-py3-none-any.whl"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("packaging-26.3.dist-info/METADATA", "Name: packaging\nVersion: 26.3\nRequires-Python: >=3.11\n")
        if format_text:
            archive.writestr("packaging-26.3.dist-info/WHEEL", format_text)
    with pytest.raises(package.Refusal, match="format"):
        package.inspect_wheel(file, {"name": "packaging", "version": "26.3"}, TEST_RUNTIME)


def test_wheel_markers_use_packaged_windows_runtime_and_no_extras(tmp_path):
    file = tmp_path / "demo-1.0-py3-none-any.whl"
    metadata = ('Name: demo\nVersion: 1.0\nRequires-Dist: win-only>=2; sys_platform == "win32"\n'
                'Requires-Dist: current-only; python_full_version == "3.14.9"\n'
                'Requires-Dist: ignored; sys_platform == "linux"\n'
                'Requires-Dist: optional; extra == "test"\n')
    with zipfile.ZipFile(file, "w") as archive:
        wheel_metadata(archive, "demo-1.0.dist-info/METADATA", metadata, file.name)
    assert [str(req) for req in package.inspect_wheel(file, {"name": "demo", "version": "1.0"}, TEST_RUNTIME)] == [
        'win-only>=2; sys_platform == "win32"', 'current-only; python_full_version == "3.14.9"']


@pytest.mark.parametrize("requirement", ["missing>=1", "child>=2", "child[optional]>=1",
                                         "child @ https://example.invalid/child.whl"])
def test_active_dependency_requires_complete_exact_closure(requirement):
    from packaging.requirements import Requirement
    lock = {"direct_dependencies": ["root"], "wheels": [{"name": "root", "version": "1"}, {"name": "child", "version": "1"}]}
    with pytest.raises(package.Refusal, match="dependenc"):
        package.check_dependency_closure(lock, {"root": [Requirement(requirement)], "child": []})


def test_transitive_dependency_closure_accepts_exact_satisfied_graph():
    from packaging.requirements import Requirement
    lock = {"direct_dependencies": ["root"], "wheels": [{"name": "root", "version": "1"}, {"name": "child", "version": "1"},
                                                        {"name": "leaf", "version": "3"}]}
    package.check_dependency_closure(lock, {"root": [Requirement("child>=1")], "child": [Requirement("leaf==3")], "leaf": []})


def test_unnecessary_transitive_wheel_is_refused():
    lock = {"direct_dependencies": ["root"], "wheels": [{"name": "root", "version": "1"}, {"name": "unused", "version": "1"}]}
    with pytest.raises(package.Refusal, match="unreachable"):
        package.check_dependency_closure(lock, {"root": [], "unused": []})


def test_runtime_lock_matches_exact_project_core_dependencies():
    import tomllib
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name
    lock, digest, raw = package.load_runtime_lock()
    project = tomllib.loads((SOURCE.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    direct = {canonicalize_name(req.name): str(req.specifier) for req in map(Requirement, project["project"]["dependencies"])}
    locked = {item["name"]: "==" + item["version"] for item in lock["wheels"] if item["name"] in lock["direct_dependencies"]}
    assert direct == locked
    assert lock["python"]["version"] in SpecifierSet(project["project"]["requires-python"])
    assert digest == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("field,value", [("abi", "cp314t"), ("threading", "free-threaded"), ("architecture", "win32"),
                                         ("filename", "python-3.11.9-embed-amd64.zip"), ("origin", "https://example.invalid/python.zip"),
                                         ("sha256", "invalid")])
def test_inconsistent_runtime_lock_is_refused(tmp_path, monkeypatch, field, value):
    lock = json.loads(package.RUNTIME_LOCK.read_text(encoding="utf-8"))
    lock["python"][field] = value
    file = tmp_path / "lock.json"
    file.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(package, "RUNTIME_LOCK", file)
    with pytest.raises(package.Refusal, match="lock"):
        package.load_runtime_lock()


def test_duplicate_runtime_lock_wheel_is_refused(tmp_path, monkeypatch):
    lock = json.loads(package.RUNTIME_LOCK.read_text(encoding="utf-8"))
    lock["wheels"].append(lock["wheels"][0])
    file = tmp_path / "lock.json"
    file.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(package, "RUNTIME_LOCK", file)
    with pytest.raises(package.Refusal, match="duplicated"):
        package.load_runtime_lock()


def test_plan_cannot_choose_a_different_runtime_lock():
    with pytest.raises(package.Refusal, match="bind"):
        package.prepare_runtime_inputs({"runtime_lock_sha256": "0" * 64})


@pytest.mark.parametrize("field,value", [("version", "3.11.9"), ("origin", "https://example.invalid/other.zip"), ("sha256", "0" * 64)])
def test_local_plan_cannot_redefine_reviewed_input(tmp_path, field, value):
    file = tmp_path / "selected.zip"
    file.write_bytes(b"declared synthetic input")
    item = {"path": str(file), "version": "3.14.9", "origin": "https://www.python.org/selected.zip", "sha256": package.sha(file)}
    locked = {key: item[key] for key in ("version", "origin", "sha256")}
    locked["filename"] = file.name
    locked[field] = value
    with pytest.raises(package.Refusal, match="exact runtime lock"):
        package.check_locked_input(item, locked)


def recorded_wheel(tmp_path, name, version, requirements=(), members=None):
    import base64
    import csv
    import io
    filename = name.replace("-", "_") + "-" + version + "-py3-none-any.whl"
    path = tmp_path / filename
    root = name.replace("-", "_") + "-" + version + ".dist-info"
    data = {root + "/METADATA": ("Name: " + name + "\nVersion: " + version + "\nRequires-Python: >=3.11\n" +
            "".join("Requires-Dist: " + item + "\n" for item in requirements)).encode(),
            root + "/WHEEL": b"Wheel-Version: 1.0\nTag: py3-none-any\n", **(members or {})}
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for member, raw in data.items():
        writer.writerow([member, "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode(), str(len(raw))])
    writer.writerow([root + "/RECORD", "", ""])
    data[root + "/RECORD"] = output.getvalue().encode()
    with zipfile.ZipFile(path, "w") as archive:
        for member, raw in data.items():
            archive.writestr(member, raw)
    return {"name": name, "version": version, "filename": filename, "path": str(path),
            "origin": "https://files.pythonhosted.org/packages/synthetic/" + filename, "sha256": package.sha(path)}


def synthetic_ocr_plan(tmp_path, monkeypatch, extra_native=None, omit=()):
    """Authored bytes test assembly without running supplier/native code."""
    python = tmp_path / "python-3.14.9-embed-amd64.zip"
    with zipfile.ZipFile(python, "w") as archive:
        for name in ("python.exe", "python314.dll", "python314.zip", "python314._pth", "vcruntime140.dll", "vcruntime140_1.dll"):
            archive.writestr(name, b"synthetic factory bytes")
    runtime = {"version": "3.14.9", "abi": "cp314", "filename": python.name, "origin": "https://www.python.org/synthetic/" + python.name,
               "sha256": package.sha(python)}
    wheels = [recorded_wheel(tmp_path, "ocrmypdf", "17.13.0", ["child[pdfa]>=1"]),
              recorded_wheel(tmp_path, "child", "1", ['leaf>=1; extra == "pdfa"']),
              recorded_wheel(tmp_path, "leaf", "1", members={
                  "leaf/_core.pyd": b"MZ\0head\0" + RENAMED_COPY.encode() + b"\0VCRUNTIME140.dll\0", "leaf.libs/" + RENAMED_COPY: b"microsoft copy"})]
    native = tmp_path / "native"
    native.mkdir()
    for name in ("tesseract.exe", "doc/LICENSE", "tessdata/pdf.ttf"):
        path = native / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(("synthetic " + name).encode())
    for name, data in (extra_native or {}).items():
        path = native / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    model_root = tmp_path / "models"
    model_root.mkdir()
    models = []
    for name in ("eng.traineddata", "osd.traineddata", "LICENSE", "README.md"):
        path = model_root / name
        path.write_bytes(("synthetic " + name).encode())
        models.append({"path": str(path), "filename": name, "version": "test", "origin": "synthetic immutable model/" + name, "sha256": package.sha(path)})
    lock = {"python": runtime, "direct_dependencies": ["ocrmypdf"], "wheels": wheels,
            "native": {"origin": "synthetic native archive", "files": package.snapshot(native), **({"omit": sorted(omit)} if omit else {})},
            "models": models}
    raw = json.dumps(lock, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(package, "load_ocr_lock", lambda: (lock, digest, raw))
    plan = {"ocr_enabled": True, "ocr": {"runtime_lock_sha256": digest, "python": dict(runtime, path=str(python)),
            "wheels": wheels, "tesseract": {"root": str(native), **lock["native"]}, "models": models}}
    return plan, lock, raw


def test_exact_optional_ocr_lock_has_separate_maintained_runtime_and_english_models():
    lock, digest, raw = package.load_ocr_lock()
    assert digest == hashlib.sha256(raw).hexdigest()
    assert len(lock["wheels"]) == 31
    assert lock["python"] == package.load_runtime_lock()[0]["python"]
    assert lock["enabled_languages"] == ["eng"]
    assert {row["filename"] for row in lock["models"]} == {"eng.traineddata", "osd.traineddata", "LICENSE", "README.md"}
    assert len(lock["native"]["files"]) == 138
    assert "tesseract-uninstall.exe" not in lock["native"]["files"]


# --- the Tesseract files that are left out ---------------------------------------------------------------------

# The 33 libraries that tesseract.exe needs (found by following library names through the real files; see docs/LICENCE-REVIEW.md).
TESSERACT_NEEDED_LIBRARIES = {
    "libarchive-13.dll", "libb2-1.dll", "libbrotlicommon.dll", "libbrotlidec.dll", "libbz2-1.dll", "libcurl-4.dll", "libdeflate.dll",
    "libexpat-1.dll", "libgcc_s_seh-1.dll", "libgif-7.dll", "libiconv-2.dll", "libidn2-0.dll", "libintl-8.dll", "libjbig-0.dll",
    "libjpeg-8.dll", "libleptonica-6.dll", "liblerc.dll", "liblz4.dll", "liblzma-5.dll", "libopenjp2-7.dll", "libpng16-16.dll",
    "libpsl-5.dll", "libsharpyuv-0.dll", "libssh2-1.dll", "libstdc++-6.dll", "libtesseract-5.dll", "libtiff-6.dll",
    "libunistring-5.dll", "libwebp-7.dll", "libwebpmux-3.dll", "libwinpthread-1.dll", "libzstd.dll", "zlib1.dll"}


def test_real_lock_leaves_out_only_files_tesseract_exe_does_not_need():
    lock = package.load_ocr_lock()[0]
    files, omit = lock["native"]["files"], set(lock["native"]["omit"])
    kept = set(files) - omit
    assert len(files) == 138 and len(omit) == 67 and len(kept) == 71
    assert package.NATIVE_ALWAYS_KEPT <= kept
    kept_libraries = {name for name in kept if name.lower().endswith(".dll")}
    assert {name.lower() for name in kept_libraries} == {name.lower() for name in TESSERACT_NEEDED_LIBRARIES}
    assert "libjbig-0.dll" in kept, "tesseract.exe loads it through libtiff, so it stays and needs its notice"
    assert not any(name.endswith(".exe") and name != "tesseract.exe" for name in kept)
    assert not any(name.startswith("$PLUGINSDIR/") or name.endswith(".jar") for name in kept)
    assert "tessdata/pdf.ttf" in kept
    assert any(name.startswith("tessdata/configs/") for name in kept), "the hocr, pdf, txt and tsv configs are used"


@pytest.mark.parametrize("change", ["required-file", "unknown-file", "unsorted", "duplicate", "not-a-list"])
def test_inconsistent_omission_list_is_refused(tmp_path, monkeypatch, change):
    lock = json.loads(package.OCR_RUNTIME_LOCK.read_text(encoding="utf-8"))
    omit = list(lock["native"]["omit"])
    lock["native"]["omit"] = {"required-file": sorted([*omit, "tesseract.exe"]), "unknown-file": sorted([*omit, "not-in-the-lock.dll"]),
                              "unsorted": omit[::-1], "duplicate": sorted([*omit, omit[0]]), "not-a-list": "tesseract.1.html"}[change]
    file = tmp_path / "lock.json"
    file.write_text(json.dumps(lock), encoding="utf-8")
    monkeypatch.setattr(package, "OCR_RUNTIME_LOCK", file)
    with pytest.raises(package.Refusal, match="omission"):
        package.load_ocr_lock()


def factory_with_libraries(tmp_path, programs):
    root = tmp_path / "factory"
    root.mkdir()
    for name, data in programs.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {"root": str(root), "origin": "synthetic factory", "files": package.snapshot(root)}


def test_library_names_are_followed_through_other_libraries_in_any_letter_case(tmp_path):
    factory = factory_with_libraries(tmp_path, {
        "tesseract.exe": b"MZ imports LibKeep.DLL", "libkeep.dll": b"MZ imports libdeep.dll", "libdeep.dll": b"MZ",
        "libgone.dll": b"MZ", "text2image.exe": b"MZ imports libgone.dll", "$PLUGINSDIR/System.dll": b"MZ", "doc/LICENSE": b"licence"})
    view = package.tesseract_runtime_view(factory, ["libgone.dll", "text2image.exe", "$PLUGINSDIR/System.dll"])
    assert sorted(view["files"]) == ["doc/LICENSE", "libdeep.dll", "libkeep.dll", "tesseract.exe"]
    assert view["root"] == factory["root"] and len(factory["files"]) == 7, "the locked map itself is not changed"
    assert sorted(package.tesseract_runtime_view(factory, [])["files"]) == sorted(factory["files"])


@pytest.mark.parametrize("omitted", [["libkeep.dll"], ["libdeep.dll"], ["libkeep.dll", "libdeep.dll"]])
def test_omitting_a_library_that_tesseract_exe_needs_is_refused(tmp_path, omitted):
    factory = factory_with_libraries(tmp_path, {"tesseract.exe": b"MZ libkeep.dll", "libkeep.dll": b"MZ libdeep.dll", "libdeep.dll": b"MZ"})
    with pytest.raises(package.Refusal, match="needs a library"):
        package.tesseract_runtime_view(factory, omitted)


def test_a_reference_in_other_letter_case_still_counts_as_needed(tmp_path):
    factory = factory_with_libraries(tmp_path, {"tesseract.exe": b"MZ LIBKEEP.DLL", "libkeep.dll": b"MZ"})
    with pytest.raises(package.Refusal, match="needs a library"):
        package.tesseract_runtime_view(factory, ["libkeep.dll"])


@pytest.mark.parametrize("omitted", [["tesseract.exe"], ["nothing-like-this.dll"], ["doc/LICENSE"]])
def test_the_view_refuses_to_omit_required_or_unknown_files(tmp_path, omitted):
    factory = factory_with_libraries(tmp_path, {"tesseract.exe": b"MZ", "doc/LICENSE": b"licence"})
    with pytest.raises(package.Refusal, match="omission"):
        package.tesseract_runtime_view(factory, omitted)


def test_assembly_packages_only_the_kept_tesseract_files(tmp_path, monkeypatch):
    extra = {"tesseract.exe": b"MZ refers to libkeep.dll", "libkeep.dll": b"MZ", "libgone.dll": b"MZ", "text2image.exe": b"MZ libgone.dll",
             "$PLUGINSDIR/System.dll": b"MZ", "tessdata/ScrollView.jar": b"PK"}
    plan, lock, raw = synthetic_ocr_plan(tmp_path, monkeypatch, extra_native=extra,
                                         omit=["libgone.dll", "text2image.exe", "$PLUGINSDIR/System.dll", "tessdata/ScrollView.jar"])
    prepared = package.prepare_ocr_inputs(plan)
    payload = tmp_path / "payload"
    payload.mkdir()
    package.assemble_ocr_runtime(prepared, payload, set())
    packaged = package.snapshot(payload / "runtime/tesseract")
    assert set(packaged) == {"tesseract.exe", "libkeep.dll", "doc/LICENSE", "tessdata/pdf.ttf",
                             "tessdata/eng.traineddata", "tessdata/osd.traineddata", "tessdata/LICENSE", "tessdata/README.md"}
    assert (payload / "ocr-runtime-baseline.json").read_bytes() == raw


def test_assembly_refuses_when_the_omission_list_would_remove_a_needed_library(tmp_path, monkeypatch):
    plan, lock, raw = synthetic_ocr_plan(tmp_path, monkeypatch, extra_native={"tesseract.exe": b"MZ refers to libkeep.dll", "libkeep.dll": b"MZ"},
                                         omit=["libkeep.dll"])
    prepared = package.prepare_ocr_inputs(plan)
    payload = tmp_path / "payload"
    payload.mkdir()
    with pytest.raises(package.Refusal, match="needs a library"):
        package.assemble_ocr_runtime(prepared, payload, set())
    assert not (payload / "runtime/tesseract/tesseract.exe").exists(), "nothing of Tesseract is copied before the check passes"


def test_legacy_off_plan_has_no_optional_inputs():
    assert package.prepare_ocr_inputs({"ocr_enabled": False}) is None


@pytest.mark.parametrize("plan", [{}, {"ocr_enabled": 0}, {"ocr_enabled": "false"}, {"ocr_enabled": False, "ocr": {}},
                                  {"ocr_enabled": True}, {"ocr_enabled": True, "ocr": {"root": "arbitrary"}}])
def test_optional_ocr_inputs_fail_closed(plan):
    with pytest.raises(package.Refusal):
        package.prepare_ocr_inputs(plan)


def test_optional_ocr_preflight_resolves_real_metadata_extras_and_exact_inputs(tmp_path, monkeypatch):
    plan, lock, raw = synthetic_ocr_plan(tmp_path, monkeypatch)
    prepared = package.prepare_ocr_inputs(plan)
    assert prepared["active_extras"] == {"child": ["pdfa"]}
    assert len(prepared["wheels"]) == 3 and prepared["raw"] == raw


@pytest.mark.parametrize("change", ["lock", "wheel-missing", "wheel-extra", "model-fra", "model-bytes", "factory-map", "factory-extra", "factory-bytes"])
def test_optional_ocr_forged_or_incomplete_inputs_refused(tmp_path, monkeypatch, change):
    plan, lock, raw = synthetic_ocr_plan(tmp_path, monkeypatch)
    ocr = plan["ocr"]
    if change == "lock":
        ocr["runtime_lock_sha256"] = "0" * 64
    elif change == "wheel-missing":
        ocr["wheels"] = ocr["wheels"][:-1]
    elif change == "wheel-extra":
        ocr["wheels"] = [*ocr["wheels"], ocr["wheels"][0]]
    elif change == "model-fra":
        ocr["models"] = [*ocr["models"], dict(ocr["models"][0], path=str(tmp_path / "fra.traineddata"))]
    elif change == "model-bytes":
        Path(ocr["models"][0]["path"]).write_bytes(b"changed")
    elif change == "factory-map":
        ocr["tesseract"]["files"] = {"tesseract.exe": "0" * 64}
    elif change == "factory-extra":
        (Path(ocr["tesseract"]["root"]) / "private.log").write_bytes(b"do not package")
    else:
        (Path(ocr["tesseract"]["root"]) / "tesseract.exe").write_bytes(b"changed")
    with pytest.raises(package.Refusal):
        package.prepare_ocr_inputs(plan)
    assert not (tmp_path / "output").exists()


def test_optional_ocr_extra_dependency_is_mandatory_and_url_dependency_refused():
    from packaging.requirements import Requirement
    lock = {"python": TEST_RUNTIME, "direct_dependencies": ["root"], "wheels": [{"name": "root", "version": "1"}, {"name": "child", "version": "1"}]}
    for dependencies in ({"root": [Requirement("child[pdfa]")], "child": [Requirement('missing; extra == "pdfa"')]},
                         {"root": [Requirement("child @ https://example.invalid/child.whl")], "child": []}):
        with pytest.raises(package.Refusal, match="closure"):
            package.check_ocr_dependency_closure(lock, dependencies)


@pytest.mark.parametrize("member", ["pdfminer_six-20260107.data/scripts/dumppdf.py", "pdfminer_six-20260107.data/scripts/pdf2txt.py"])
def test_exact_pdfminer_scripts_are_preserved_inert_and_never_global(tmp_path, member):
    row = recorded_wheel(tmp_path, "pdfminer-six", "20260107", members={member: b"#!/vendor/python\n# unchanged"})
    path, root = Path(row["path"]), tmp_path / "private-ocr"
    package.inspect_wheel(path, row, TEST_RUNTIME, all_requirements=True)
    moved = package.extract_wheel(path, root, set(), ocr_scripts=True)
    assert (root / "Scripts" / Path(member).name).read_bytes() == b"#!/vendor/python\n# unchanged"
    assert moved == [{"wheel_member": member, "installed_path": "Scripts/" + Path(member).name}]
    with pytest.raises(package.Refusal, match="relocation"):
        package.inspect_wheel(path, row, TEST_RUNTIME)


@pytest.mark.parametrize("member", ["pdfminer_six-20260107.data/scripts/unexpected.exe", "pdfminer_six-20260107.data/scripts/other.py"])
def test_optional_ocr_does_not_allow_arbitrary_script_relocations(tmp_path, member):
    row = recorded_wheel(tmp_path, "pdfminer-six", "20260107", members={member: b"unreviewed"})
    with pytest.raises(package.Refusal, match="relocation"):
        package.inspect_wheel(Path(row["path"]), row, TEST_RUNTIME, all_requirements=True)
    with pytest.raises(package.Refusal, match="relocation"):
        package.extract_wheel(Path(row["path"]), tmp_path / "output", set(), ocr_scripts=True)


def test_optional_ocr_record_detects_changed_vendor_member(tmp_path):
    row = recorded_wheel(tmp_path, "example", "1", members={"example.py": b"original"})
    path = Path(row["path"])
    with zipfile.ZipFile(path) as archive:
        data = {name: archive.read(name) for name in archive.namelist()}
    data["example.py"] = b"modified"
    with zipfile.ZipFile(path, "w") as archive:
        for name, raw in data.items():
            archive.writestr(name, raw)
    with pytest.raises(package.Refusal, match="RECORD hash"):
        package.inspect_wheel(path, row, TEST_RUNTIME, all_requirements=True)


@pytest.mark.parametrize("ocr_enabled", [False, True])
def test_built_payload_config_and_compiled_installer_bind_optional_ocr_policy(tmp_path, monkeypatch, ocr_enabled):
    import tomllib
    plan, ocr_lock, ocr_raw = synthetic_ocr_plan(tmp_path, monkeypatch)
    if not ocr_enabled:
        plan = {"ocr_enabled": False}
    plan.update(schema="windows-internal-inputs-1", release_status="internal-unqualified", ai_enabled=False, redistribution_cleared=False)
    core = {"python": ocr_lock["python"], "wheels": []}
    core_raw = json.dumps(core, sort_keys=True).encode()
    core_sha = hashlib.sha256(core_raw).hexdigest()
    monkeypatch.setattr(package, "prepare_runtime_inputs", lambda _: (core, core_sha, core_raw, tmp_path / core["python"]["filename"], []))
    from types import SimpleNamespace
    monkeypatch.setattr(package, "os", SimpleNamespace(name="nt"))
    compiled_icons, compiled_sources, checked_payloads = [], [], []
    def compile_authored_stub(csc, source, output, resources=(), *, icon):
        compiled_icons.append((Path(icon), package.sha(icon)))
        compiled_sources.append(Path(source))
        output.write_bytes(b"authored compiler stub; never a qualified executable")
    monkeypatch.setattr(package, "compile_cs", compile_authored_stub)
    real_payload_check = package.check_no_microsoft_runtime
    monkeypatch.setattr(package, "check_no_microsoft_runtime", lambda payload: (checked_payloads.append(Path(payload)), real_payload_check(payload)))
    plan["native"] = {}
    for group, names in {"java": ["bin/java.exe", "legal/LICENSE", "bin/msvcp140.dll", "bin/ucrtbase.dll", "bin/api-ms-win-core-file-l1-1-0.dll"],
                         "odl": ["jar/opendataloader-pdf-cli.jar", "LICENSE", "NOTICE"],
                         "verapdf": ["verapdf.bat", "bin/cli-1.30.3.jar"]}.items():
        root = tmp_path / group
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic native")
        plan["native"][group] = {"root": str(root), "origin": "authored " + group, "files": package.snapshot(root)}
    source = tmp_path / "source"
    (source / "src/pdf_remediator").mkdir(parents=True)
    (source / "src/pdf_remediator/__init__.py").write_bytes(b"# authored app")
    for name in package.ICON_ASSETS:
        asset = source / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(("authored asset, not a qualified icon: " + name).encode())
    for name, digest in package.EDITOR_FONT_ASSETS.items():
        asset = source / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes((SOURCE.parents[1] / name).read_bytes())
        assert package.sha(asset) == digest
    plan["source"] = {"root": str(source), "origin": "authored source", "files": package.snapshot(source)}
    notices = tmp_path / "notices"
    notices.mkdir()
    (notices / "LICENSE").write_bytes(b"authored notice")
    plan["notices"] = {"root": str(notices), "origin": "authored notices", "files": package.snapshot(notices)}
    output = tmp_path / "new-build"
    result = package.build(plan, output, Path("not-executed"))
    payload = output / "payload"
    config = tomllib.loads((payload / "local-runtime.toml").read_text())["runtime"]
    manifest = json.loads((payload / "package-manifest.json").read_text())
    bound = (output / "installer-bound.cs").read_text()
    assert config["ocr_mode"] == "off" and manifest["ai_enabled"] is False
    assert result["ocr_enabled"] is manifest["ocr_enabled"] is ocr_enabled
    assert 'const bool OcrEnabled = "' + str(ocr_enabled).lower() + '" == "true";' in bound
    assert "Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath)" in bound
    assert compiled_icons == [(payload / package.ICON_ICO, plan["source"]["files"][package.ICON_ICO])] * 2
    assert all(manifest["files"][name] == plan["source"]["files"][name] == package.sha(payload / name)
               for name in package.ICON_ASSETS)
    assert all(manifest["files"][name] == plan["source"]["files"][name] == digest == package.sha(payload / name)
               for name, digest in package.EDITOR_FONT_ASSETS.items())
    assert "__OCR_" not in bound
    launcher = (output / "launcher-bound.cs").read_text()
    for text in (bound, launcher):
        assert "__MIN_VC_RUNTIME__" not in text and 'const string Minimum = "' + package.MS_RUNTIME_MINIMUM + '";' in text
        assert "internal static class VcRuntime" in text and "VcRuntime.Problem()" in text
    start_here = (payload / "START-HERE.txt").read_text(encoding="utf-8")
    assert "opens in its own window" in start_here and "Closing that window stops the program" in start_here
    assert (payload / "launch_portable.py").read_text(encoding="utf-8") == package.LAUNCH_PORTABLE
    assert package.FREETYPE_CREDIT in start_here
    assert package.FREETYPE_CREDIT.startswith("Portions of this software are copyright © 2026 The FreeType Project (www.freetype.org). All rights reserved.\n")
    assert "based in part on the work of the FreeType Team" in start_here
    assert compiled_sources == [output / "launcher-bound.cs", output / "installer-bound.cs"]
    assert checked_payloads == [payload], "the finished payload is checked for Microsoft runtime files before it is listed"
    microsoft = manifest["microsoft_runtime"]
    assert microsoft["minimum_version"] == package.MS_RUNTIME_MINIMUM
    expected = ["runtime/java/bin/api-ms-win-core-file-l1-1-0.dll", "runtime/java/bin/msvcp140.dll", "runtime/java/bin/ucrtbase.dll",
                "runtime/python/vcruntime140.dll", "runtime/python/vcruntime140_1.dll"]
    if ocr_enabled:
        expected += ["runtime/ocr/Lib/site-packages/leaf.libs/" + RENAMED_COPY, "runtime/ocr/vcruntime140.dll", "runtime/ocr/vcruntime140_1.dll"]
    assert microsoft["left_out"] == sorted(expected)
    assert not any(package.is_microsoft_runtime(name) for name in manifest["files"])
    assert not any(package.is_microsoft_runtime(path.name) for path in payload.rglob("*"))
    assert (payload / "runtime/java/bin/java.exe").is_file() and (payload / "runtime/java/legal/LICENSE").is_file()
    if ocr_enabled:
        core = (payload / "runtime/ocr/Lib/site-packages/leaf/_core.pyd").read_bytes()
        assert core == b"MZ\0head\0msvcp140.dll" + b"\0" * (len(RENAMED_COPY) - len("msvcp140.dll")) + b"\0VCRUNTIME140.dll\0"
        assert [row["file"] for row in microsoft["redirected_imports"]] == ["runtime/ocr/Lib/site-packages/leaf/_core.pyd"]
    else:
        assert microsoft["redirected_imports"] == []
    assert (payload / "runtime-baseline.json").read_bytes() == core_raw
    if ocr_enabled:
        assert config["ocr_python"] == "runtime/ocr/python.exe" and config["tesseract_dir"] == "runtime/tesseract"
        assert (payload / "ocr-runtime-baseline.json").read_bytes() == ocr_raw
        assert manifest["ocr_runtime_lock_sha256"] == hashlib.sha256(ocr_raw).hexdigest()
        assert (payload / "runtime/ocr/python314._pth").read_text() == "python314.zip\n.\nLib/site-packages\n"
        assert "../../src" not in (payload / "runtime/ocr/python314._pth").read_text()
        assert (payload / "runtime/tesseract/tessdata/eng.traineddata").is_file()
        assert not (payload / "runtime/tesseract/tessdata/fra.traineddata").exists()
    else:
        assert config["ocr_python"] == "runtime/not-included/python.exe"
        assert manifest["ocr_runtime_lock_sha256"] == ""
        assert not (payload / "ocr-runtime-baseline.json").exists() and not (payload / "runtime/ocr").exists()


# --- Microsoft's runtime files are left out and the installer checks for Microsoft's own copy -------------------

@pytest.mark.parametrize("name,expected", [
    ("vcruntime140.dll", True), ("runtime/python/VCRUNTIME140_1.dll", True), ("msvcp140.dll", True), ("msvcp140_1.dll", True),
    ("msvcp140_atomic_wait.dll", True), ("Lib/site-packages/pikepdf.libs/" + RENAMED_COPY, True), ("concrt140.dll", True),
    ("vcomp140.dll", True), ("ucrtbase.dll", True), ("bin/api-ms-win-crt-heap-l1-1-0.dll", True), ("bin/ext-ms-win-ntuser-window-l1-1-0.dll", True),
    ("python314.dll", False), ("libssl-3.dll", False), ("qpdf30-14efc7eef6c9cae2095b94960308fa11.dll", False), ("vcruntime140.dll.txt", False),
    ("msvcp140-not-a-hash.dll", False), ("legal/microsoft-visual-cpp-runtime.txt", False), ("msvcrt.dll", False), ("libstdc++-6.dll", False)])
def test_microsoft_runtime_file_names(name, expected):
    assert package.is_microsoft_runtime(name) is expected


def test_minimum_runtime_version_is_not_older_than_the_copies_that_used_to_be_carried():
    # Python 3.14.9 and pikepdf 10.17.0 each carried 14.51.36247.0; a program built with those tools can fail on an older runtime.
    assert tuple(int(part) for part in package.MS_RUNTIME_MINIMUM.split(".")) >= (14, 51, 36247, 0)


def test_python_archive_leaves_microsoft_runtime_out_and_lists_it(tmp_path):
    path = tmp_path / "embed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in ("python.exe", "python314.dll", "vcruntime140.dll", "VCRUNTIME140_1.dll"):
            archive.writestr(name, b"data")
    target, left_out = tmp_path / "new", []
    package.extract_checked(path, target, set(), left_out)
    assert sorted(item.name for item in target.iterdir()) == ["python.exe", "python314.dll"]
    assert sorted(left_out) == ["VCRUNTIME140_1.dll", "vcruntime140.dll"]
    everything = tmp_path / "everything"
    package.extract_checked(path, everything, set())
    assert len(list(everything.iterdir())) == 4, "without a left_out list nothing is skipped"


def test_wheel_leaves_the_renamed_microsoft_copy_out_but_keeps_its_notice(tmp_path):
    file = tmp_path / "pikepdf-1.0-cp314-cp314-win_amd64.whl"
    notice = "pikepdf-1.0.dist-info/licenses/third-party-licenses/microsoft-visual-cpp-runtime.txt"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("pikepdf/_core.pyd", b"MZ core")
        archive.writestr("pikepdf.libs/" + RENAMED_COPY, b"microsoft copy")
        archive.writestr("pikepdf.libs/qpdf30-14efc7eef6c9cae2095b94960308fa11.dll", b"MZ qpdf")
        archive.writestr(notice, b"notice text")
    root, left_out = tmp_path / "python", []
    package.extract_wheel(file, root, set(), left_out=left_out)
    site = root / "Lib/site-packages"
    assert left_out == ["Lib/site-packages/pikepdf.libs/" + RENAMED_COPY]
    assert not (site / "pikepdf.libs" / RENAMED_COPY).exists()
    assert (site / "pikepdf.libs/qpdf30-14efc7eef6c9cae2095b94960308fa11.dll").is_file() and (site / "pikepdf/_core.pyd").is_file()
    assert (site / notice).read_bytes() == b"notice text"


def test_native_map_leaves_microsoft_runtime_out_without_reading_it(tmp_path):
    source = tmp_path / "vendor"
    (source / "bin").mkdir(parents=True)
    (source / "bin/java.exe").write_bytes(b"java")
    (source / "bin/vcruntime140.dll").write_bytes(b"microsoft")
    files = {"bin/java.exe": package.sha(source / "bin/java.exe"), "bin/vcruntime140.dll": "0" * 64,
             "bin/api-ms-win-core-file-l1-1-0.dll": "0" * 64}  # wrong digests and a missing file: never read
    item = {"root": str(source), "origin": "synthetic vendor", "files": files}
    target, left_out = tmp_path / "new", []
    package.copy_map(item, target, left_out)
    assert package.snapshot(target) == {"bin/java.exe": hashlib.sha256(b"java").hexdigest()}
    assert sorted(left_out) == ["bin/api-ms-win-core-file-l1-1-0.dll", "bin/vcruntime140.dll"]
    with pytest.raises(package.Refusal):
        package.copy_map(item, tmp_path / "other")


def tree_with_renamed_references(tmp_path, **changes):
    root = tmp_path / "python"
    site = root / "Lib/site-packages"
    files = {"pikepdf/_core.pyd": b"MZ\0head\0" + RENAMED_COPY.encode() + b"\0VCRUNTIME140.dll\0tail",
             "pikepdf.libs/qpdf30-14efc7eef6c9cae2095b94960308fa11.dll": b"MZ\0" + RENAMED_COPY.encode() + b"\0KERNEL32.dll\0",
             "PIL/_imaging.pyd": b"MZ\0VCRUNTIME140.dll\0", "pikepdf/notes.txt": b"mentions " + RENAMED_COPY.encode() + b" in text"}
    files.update(changes)
    for name, data in files.items():
        (site / name).parent.mkdir(parents=True, exist_ok=True)
        (site / name).write_bytes(data)
    return root, files


@pytest.mark.parametrize("spelling", [str.lower, str.upper])
def test_renamed_copy_imports_are_pointed_at_the_system_library(tmp_path, spelling):
    old = spelling(RENAMED_COPY).encode()
    root, files = tree_with_renamed_references(tmp_path, **{"pikepdf/_core.pyd": b"MZ\0head\0" + old + b"\0VCRUNTIME140.dll\0tail"})
    site = root / "Lib/site-packages"
    changes = package.redirect_renamed_runtime(root, ["Lib/site-packages/pikepdf.libs/" + RENAMED_COPY])
    padding = b"\0" * (len(RENAMED_COPY) - len("msvcp140.dll"))
    assert (site / "pikepdf/_core.pyd").read_bytes() == b"MZ\0head\0msvcp140.dll" + padding + b"\0VCRUNTIME140.dll\0tail"
    assert (site / "pikepdf.libs/qpdf30-14efc7eef6c9cae2095b94960308fa11.dll").read_bytes() == b"MZ\0msvcp140.dll" + padding + b"\0KERNEL32.dll\0"
    assert (site / "PIL/_imaging.pyd").read_bytes() == files["PIL/_imaging.pyd"], "files that do not refer to it are untouched"
    assert (site / "pikepdf/notes.txt").read_bytes() == files["pikepdf/notes.txt"], "only programs are changed, never text files"
    assert sorted(change["file"] for change in changes) == ["Lib/site-packages/pikepdf.libs/qpdf30-14efc7eef6c9cae2095b94960308fa11.dll",
                                                            "Lib/site-packages/pikepdf/_core.pyd"]
    assert all(change["now"] == "msvcp140.dll" and change["sha256_before"] != change["sha256_after"] for change in changes)


@pytest.mark.parametrize("data", [b"MZ\0" + RENAMED_COPY.encode() + b"\0" + RENAMED_COPY.encode() + b"\0",
                                  b"MZ\0" + RENAMED_COPY.encode() + b"x\0"])
def test_unexpected_layout_around_the_renamed_copy_is_refused(tmp_path, data):
    root, files = tree_with_renamed_references(tmp_path, **{"pikepdf/_core.pyd": data})
    with pytest.raises(package.Refusal, match="Unexpected layout"):
        package.redirect_renamed_runtime(root, ["Lib/site-packages/pikepdf.libs/" + RENAMED_COPY])


@pytest.mark.parametrize("left_out", [[], ["vcruntime140.dll"], ["Lib/site-packages/leaf.libs/msvcp140-not-a-hash.dll"]])
def test_nothing_is_redirected_unless_a_renamed_copy_was_left_out(tmp_path, left_out):
    root, files = tree_with_renamed_references(tmp_path)
    assert package.redirect_renamed_runtime(root, left_out) == []
    assert (root / "Lib/site-packages/pikepdf/_core.pyd").read_bytes() == files["pikepdf/_core.pyd"]


def test_payload_check_accepts_programs_that_need_only_the_files_the_installer_checks(tmp_path):
    (tmp_path / "a.dll").write_bytes(b"MZ\0VCRUNTIME140.dll\0VCRUNTIME140_1.dll\0MSVCP140.dll\0")
    (tmp_path / "notes.txt").write_bytes(b"msvcp140_1.dll is only named in a text file, " + RENAMED_COPY.encode())
    package.check_no_microsoft_runtime(tmp_path)


@pytest.mark.parametrize("name", ["vcruntime140.dll", "bin/msvcp140.dll", "bin/ucrtbase.dll", "a/api-ms-win-core-file-l1-1-0.dll",
                                  "Lib/pikepdf.libs/" + RENAMED_COPY])
def test_payload_check_refuses_a_microsoft_runtime_file(tmp_path, name):
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_bytes(b"MZ")
    with pytest.raises(package.Refusal, match="must not enter the package"):
        package.check_no_microsoft_runtime(tmp_path)


@pytest.mark.parametrize("needed", [b"msvcp140_1.dll", b"concrt140.dll", b"VCOMP140.DLL", b"vcruntime140_threads.dll"])
def test_payload_check_refuses_a_program_needing_a_runtime_file_the_installer_does_not_check(tmp_path, needed):
    (tmp_path / "tool.exe").write_bytes(b"MZ\0VCRUNTIME140.dll\0" + needed + b"\0")
    with pytest.raises(package.Refusal, match="does not check for"):
        package.check_no_microsoft_runtime(tmp_path)


def test_payload_check_refuses_a_program_still_loading_a_renamed_copy(tmp_path):
    (tmp_path / "_core.pyd").write_bytes(b"MZ\0" + RENAMED_COPY.encode() + b"\0")
    with pytest.raises(package.Refusal, match="renamed copy"):
        package.check_no_microsoft_runtime(tmp_path)


def test_installer_and_launcher_check_for_the_runtime_before_anything_else():
    scripts = SOURCE.parent
    installer = (scripts / "windows-installer.cs").read_text(encoding="utf-8")
    launcher = (scripts / "windows-launcher.cs").read_text(encoding="utf-8")
    check = (scripts / "windows-vc-runtime.cs").read_text(encoding="utf-8")
    assert installer.index("VcRuntime.Problem()") < installer.index("PrepareTarget(requested, false)")
    assert "throw new RuntimeMissing(runtime)" in installer and "VcRuntime.OfferDownload(early)" in installer
    assert launcher.index("VcRuntime.Problem()") < launcher.index("File.Exists(python)") < launcher.index("RunPython(root, python")
    assert check.count("__MIN_VC_RUNTIME__") == 1
    assert {name.lower() for name in package.MS_RUNTIME_SYSTEM_FILES} == set(re.findall(r'"([a-z0-9_]+\.dll)"', check)) - {"ucrtbase.dll"}


def test_installer_window_says_the_program_opens_in_its_own_window():
    installer = (SOURCE.parent / "windows-installer.cs").read_text(encoding="utf-8")
    assert "The local workspace opens in its own window, not in your browser." in installer
    assert "Your browser will show the local workspace" not in installer


def test_installer_offers_a_desktop_and_start_menu_icon_and_the_start_text_explains_it():
    installer = (SOURCE.parent / "windows-installer.cs").read_text(encoding="utf-8")
    assert "Put a PDF Remediator icon on my desktop and in the Start menu" in installer and "Checked = true" in installer
    assert "SpecialFolder.DesktopDirectory" in installer and "SpecialFolder.Programs" in installer
    assert "Open PDF Remediator now?" in installer
    # a failed icon never undoes the installation, and the test-only command line cannot reach the real desktop by accident
    assert "The icon could not be made, but the program is installed" in installer
    assert '--shortcuts-in' in installer and installer.count("MakeShortcut(") == 4  # definition, headless test, desktop, Start menu
    source = (SOURCE).read_text(encoding="utf-8")
    assert "icon the installer put on your desktop" in source and "delete the PDF Remediator icons" in source


def csc_path():
    import os
    windir = os.environ.get("WINDIR")
    path = Path(windir) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe" if windir else None
    return path if path is not None and path.is_file() else None


@pytest.mark.skipif(csc_path() is None, reason="needs the Windows C# compiler")
def test_compiled_installer_refuses_without_a_new_enough_runtime_and_changes_nothing(tmp_path):
    import subprocess
    scripts = SOURCE.parent
    check = (scripts / "windows-vc-runtime.cs").read_text(encoding="utf-8")
    installer = (scripts / "windows-installer.cs").read_text(encoding="utf-8")
    for token in ("__PAYLOAD_SHA256__", "__RUNTIME_LOCK_SHA256__", "__OCR_RUNTIME_LOCK_SHA256__"):
        installer = installer.replace(token, "0" * 64)
    installer = installer.replace("__PYTHON_VERSION__", "3.14.9").replace("__PYTHON_ABI__", "cp314").replace("__OCR_ENABLED__", "false")
    icon = SOURCE.parents[1] / package.ICON_ICO

    def run(minimum):
        folder = tmp_path / minimum.replace(".", "-")
        folder.mkdir()
        source = folder / "installer.cs"
        source.write_text(installer + "\n" + check.replace("__MIN_VC_RUNTIME__", minimum), encoding="utf-8")
        program = folder / "setup.exe"
        package.compile_cs(csc_path(), source, program, icon=icon)
        result = folder / "result.json"
        done = subprocess.run([str(program), "--install-dir", str(folder / "target"), "--no-launch", "--result", str(result)],
                              capture_output=True, text=True, timeout=60, check=False)
        assert done.returncode == 1 and not (folder / "target").exists()
        return json.loads(result.read_text(encoding="utf-8"))

    too_new = run("99.0.0.0")
    assert too_new["status"] == "installation-refused" and "Visual C++ Redistributable" in too_new["message"]
    assert "version 99.0.0.0 or newer" in too_new["message"]
    assert "learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist" in too_new["message"]
    from os import environ
    if (Path(environ["WINDIR"]) / "System32/vcruntime140.dll").is_file():
        passes = run("1.0.0.0")
        assert "Redistributable" not in passes["message"], "with an old enough minimum the check passes and the next step runs"


@pytest.mark.skipif(csc_path() is None, reason="needs the Windows C# compiler")
def test_installer_shortcut_code_makes_a_working_shortcut_with_the_program_icon(tmp_path):
    import subprocess
    text = (SOURCE.parent / "windows-installer.cs").read_text(encoding="utf-8")
    start = text.index("    static void MakeShortcut(")
    end = text.index("    [STAThread]", start)
    harness = ("using System;\nusing System.IO;\nusing System.Reflection;\n"
               "internal static class T {\n"
               "    static void Need(bool ok, string message) { if (!ok) throw new InvalidOperationException(message); }\n"
               + text[start:end] +
               "    static int Main(string[] a) { MakeShortcut(a[0], a[1]); return 0; }\n}\n")
    source = tmp_path / "shortcut.cs"
    source.write_text(harness, encoding="utf-8")
    program = tmp_path / "shortcut-test.exe"
    package.compile_cs(csc_path(), source, program, icon=SOURCE.parents[1] / package.ICON_ICO)
    install = tmp_path / "install"
    install.mkdir()
    fake = install / "PDF Remediator.exe"
    fake.write_bytes(b"MZ")  # only its path matters to a shortcut
    where = tmp_path / "where"
    where.mkdir()
    done = subprocess.run([str(program), str(where), str(install)], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr + done.stdout
    link = where / "PDF Remediator.lnk"
    assert link.is_file()
    read = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                           "$l=(New-Object -ComObject WScript.Shell).CreateShortcut('%s'); $l.TargetPath; $l.WorkingDirectory; $l.IconLocation" % str(link).replace("'", "''")],
                          capture_output=True, text=True, timeout=60, check=False).stdout.splitlines()
    assert read[0] == str(fake) and read[1] == str(install) and read[2].startswith(str(fake)), read
    missing = subprocess.run([str(program), str(where), str(tmp_path / "nowhere")], capture_output=True, text=True, timeout=60, check=False)
    assert missing.returncode != 0, "no shortcut is made for a program that is not there"


def test_launcher_program_passes_the_arguments_that_launch_portable_understands():
    launcher = (SOURCE.parent / "windows-launcher.cs").read_text(encoding="utf-8")
    assert '"--no-open"' in launcher and '"--stop"' in launcher
    assert '"--no-open"' in package.LAUNCH_PORTABLE and '"--stop"' in package.LAUNCH_PORTABLE
    assert launcher.index("VcRuntime.Problem()") < launcher.index("AppWindow.Find()") < launcher.index('RunPython(root, python, "--no-open"')
    assert launcher.index('RunPython(root, python, "--no-open"') < launcher.index("AppWindow.Open(") < launcher.index('RunPython(root, python, "--stop"')
    assert "if (host && window != null) window.WaitForExit();" in launcher and "if (host) {" in launcher, "only one launcher per installation waits for the window and stops the service"
    assert "--app=" in launcher and "--user-data-dir=" in launcher


@pytest.mark.skipif(csc_path() is None, reason="needs the Windows C# compiler")
def test_launcher_source_compiles_together_with_the_runtime_check(tmp_path):
    scripts = SOURCE.parent
    source = tmp_path / "launcher.cs"
    source.write_text((scripts / "windows-launcher.cs").read_text(encoding="utf-8") + "\n" +
                      (scripts / "windows-vc-runtime.cs").read_text(encoding="utf-8").replace("__MIN_VC_RUNTIME__", package.MS_RUNTIME_MINIMUM),
                      encoding="utf-8")
    program = tmp_path / "launcher.exe"
    package.compile_cs(csc_path(), source, program, icon=SOURCE.parents[1] / package.ICON_ICO)
    assert program.stat().st_size > 0


@pytest.mark.parametrize("arguments,name,opens", [([], "launch", True), (["--no-open"], "launch", False), (["--stop"], "stop", None)])
def test_launch_portable_runs_the_launcher_functions_with_the_arguments_the_program_passes(tmp_path, monkeypatch, arguments, name, opens):
    import runpy
    import sys
    from pdf_remediator import launcher
    calls = []
    monkeypatch.setattr(launcher, "launch", lambda **kwargs: calls.append(("launch", kwargs)))
    monkeypatch.setattr(launcher, "stop", lambda **kwargs: calls.append(("stop", kwargs)))
    script = tmp_path / "launch_portable.py"
    script.write_text(package.LAUNCH_PORTABLE)
    monkeypatch.setattr(sys, "argv", [str(script), *arguments])
    runpy.run_path(str(script), run_name="__main__")
    (kind, kwargs), = calls
    root = tmp_path.resolve()
    assert kind == name and kwargs["data_dir"] == root / "output/review-app"
    if name == "launch":
        assert kwargs["open_browser"] is opens and kwargs["config_path"] == root / "local-runtime.toml"
