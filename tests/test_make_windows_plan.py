"""The helper that prepares the builder's input plan must fetch only locked, allowed, hash-checked inputs (scripts/make-windows-plan.py).

No test reaches the network: downloads are replaced by a local opener double.
"""
import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "make-windows-plan.py"
spec = importlib.util.spec_from_file_location("make_windows_plan", SOURCE)
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, data):
        self.data = data
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request.full_url)
        return FakeResponse(self.data)


def item(data, url="https://files.pythonhosted.org/packages/ab/cd/demo-1-py3-none-any.whl", name="demo-1-py3-none-any.whl"):
    return {"filename": name, "origin": url, "sha256": hashlib.sha256(data).hexdigest()}


def patch_opener(monkeypatch, data):
    opener = FakeOpener(data)
    monkeypatch.setattr(plan.urllib.request, "build_opener", lambda *handlers: opener)
    return opener


def test_a_matching_download_is_kept(tmp_path, monkeypatch):
    data = b"authored wheel bytes"
    opener = patch_opener(monkeypatch, data)
    path = plan.fetch(item(data), tmp_path, dry_run=False)
    assert path.read_bytes() == data and opener.requests == [item(data)["origin"]]
    assert not list(tmp_path.glob("*.part"))


def test_a_changed_download_is_deleted_and_stops_the_run(tmp_path, monkeypatch):
    patch_opener(monkeypatch, b"not the locked bytes")
    with pytest.raises(plan.Stop, match="SHA-256 mismatch"):
        plan.fetch(item(b"the locked bytes"), tmp_path, dry_run=False)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("url", ["http://files.pythonhosted.org/x/demo.whl", "https://example.com/demo.whl",
                                 "https://files.pythonhosted.org.evil.test/demo.whl", "file:///C:/demo.whl"])
def test_only_https_on_the_allowed_hosts_is_fetched(tmp_path, monkeypatch, url):
    opener = patch_opener(monkeypatch, b"x")
    with pytest.raises(plan.Stop, match="allowed download address"):
        plan.fetch(item(b"x", url=url), tmp_path, dry_run=False)
    assert opener.requests == []


def test_a_file_already_present_with_the_locked_hash_is_not_fetched_again(tmp_path, monkeypatch):
    data = b"already here"
    (tmp_path / "demo-1-py3-none-any.whl").write_bytes(data)
    opener = patch_opener(monkeypatch, b"never used")
    assert plan.fetch(item(data), tmp_path, dry_run=False).read_bytes() == data
    assert opener.requests == []


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    opener = patch_opener(monkeypatch, b"x")
    plan.fetch(item(b"x"), tmp_path / "new", dry_run=True)
    assert opener.requests == [] and not (tmp_path / "new").exists()


def test_redirects_to_other_hosts_are_refused():
    handler = plan._CheckedRedirects()
    import urllib.request
    request = urllib.request.Request("https://github.com/a/b")
    with pytest.raises(plan.Stop):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example.com/file")
    with pytest.raises(plan.Stop):
        handler.redirect_request(request, None, 302, "Found", {}, "http://objects.githubusercontent.com/file")


def make_tree(root, names):
    for name, data in names.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in names.items()}


def test_verified_copy_copies_only_the_locked_files_and_checks_them(tmp_path):
    files = make_tree(tmp_path / "source", {"a.txt": b"one", "sub/b.txt": b"two", "extra.txt": b"not locked"})
    locked = {name: files[name] for name in ("a.txt", "sub/b.txt")}
    copy = plan.verified_copy(tmp_path / "source", locked, tmp_path / "copy")
    assert plan.package.snapshot(copy) == locked
    # a second call over the same finished copy is accepted, over a different one it is refused
    assert plan.verified_copy(tmp_path / "source", locked, tmp_path / "copy") == copy
    (copy / "a.txt").write_bytes(b"changed")
    with pytest.raises(plan.Stop, match="not the locked tree"):
        plan.verified_copy(tmp_path / "source", locked, tmp_path / "copy")


def test_verified_copy_refuses_a_changed_source_file_before_copying_anything(tmp_path):
    files = make_tree(tmp_path / "source", {"a.txt": b"one", "b.txt": b"two"})
    (tmp_path / "source" / "b.txt").write_bytes(b"tampered")
    with pytest.raises(plan.Stop, match="changed from the lock"):
        plan.verified_copy(tmp_path / "source", files, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


def test_java_archive_with_a_traversing_path_is_refused(tmp_path):
    archive = tmp_path / "java.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("jdk/../../escape.txt", b"x")
    lock = {"java": {"archive": {"folder": "jdk"}, "files": {}}}
    with pytest.raises(plan.Stop, match="Unsafe path"):
        plan.unpack_java(archive, lock, tmp_path / "work")
    assert not (tmp_path.parent / "escape.txt").exists()


def test_java_tree_that_differs_from_the_lock_is_refused(tmp_path):
    archive = tmp_path / "java.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("jdk/bin/java.exe", b"authored")
    lock = {"java": {"archive": {"folder": "jdk"}, "files": {"bin/java.exe": "0" * 64}}}
    with pytest.raises(plan.Stop, match="not the locked one"):
        plan.unpack_java(archive, lock, tmp_path / "work")
