#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Makes the local input plan that scripts/package-windows.py needs, and fetches only the hash-pinned inputs it lacks.

  python scripts/make-windows-plan.py --work NEW-OR-REUSED-FOLDER --plan PLAN.json \\
      --tesseract-source FOLDER --models-source FOLDER --odl-source FOLDER --verapdf-source FOLDER

The builder never downloads anything and accepts only inputs whose SHA-256 is written in the checked-in locks
(scripts/windows-runtime-lock.json, windows-ocr-runtime-lock.json, windows-native-lock.json). This helper is the step before it:

* It downloads the Python archive, the application and OCR wheels and the Java runtime archive, from the addresses in the locks
  (python.org, files.pythonhosted.org, GitHub), over HTTPS only, and keeps a file only if its SHA-256 equals the lock's. A mismatch
  deletes the file and stops. Nothing downloaded is run: archives are only read and unpacked by the builder or by this script (zip).
* The Tesseract tree, its models, OpenDataLoader and veraPDF are not downloaded: it uses folders you name, and each file in them must have
  the locked SHA-256 (a folder with a missing, extra-in-the-listed-set or changed file is refused).
* It writes the plan (schema windows-internal-inputs-1) with the absolute paths and the file maps. The work folder and the plan are build
  products and belong outside the repository.

Usage notes: --dry-run lists what would be fetched and checks the local folders, and changes nothing.
"""
import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("windows_package", ROOT / "scripts" / "package-windows.py")
package = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(package)

ALLOWED_HOSTS = {"www.python.org", "files.pythonhosted.org", "github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com"}
MAX_DOWNLOAD = 300 * 1024 * 1024
SOURCE_SUFFIXES = {".py", ".html", ".css", ".js", ".tex", ".txt"}


class Stop(Exception):
    pass


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise Stop("A download was redirected to an address that is not allowed: " + newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(item, folder, dry_run):
    """Download one locked file into folder (or reuse it) and return its path; the SHA-256 must equal item['sha256']."""
    name = item.get("filename") or Path(urllib.parse.urlsplit(item["origin"]).path).name
    target = folder / urllib.parse.unquote(name)
    if target.is_file() and package.sha(target) == item["sha256"]:
        return target
    parsed = urllib.parse.urlsplit(item["origin"])
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise Stop("Not an allowed download address: " + item["origin"])
    if dry_run:
        print("would fetch", target.name, "from", parsed.hostname)
        return target
    folder.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    opener = urllib.request.build_opener(_CheckedRedirects)
    digest, total = hashlib.sha256(), 0
    request = urllib.request.Request(item["origin"], headers={"User-Agent": "PDF-Remediator-build-input-fetch"})
    with opener.open(request, timeout=60) as response, part.open("wb") as out:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            total += len(block)
            if total > MAX_DOWNLOAD:
                part.unlink()
                raise Stop("A download is larger than the allowed size: " + target.name)
            digest.update(block)
            out.write(block)
    if digest.hexdigest() != item["sha256"]:
        part.unlink()
        raise Stop("SHA-256 mismatch, the file was deleted: " + target.name)
    part.replace(target)
    print("fetched", target.name, total, "bytes, SHA-256 matches the lock")
    return target


def unpack_java(archive_path, lock, work):
    """Unpack the Temurin zip beside the plan and require the exact 320-file tree the native lock lists."""
    info = lock["java"]["archive"]
    destination = work / "java-factory"
    root = destination / info["folder"]
    if not root.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                relative = member.filename
                if relative.startswith("/") or ".." in Path(relative).parts or ":" in relative:
                    raise Stop("Unsafe path in the Java archive: " + relative)
            archive.extractall(destination)
    if package.snapshot(root) != lock["java"]["files"]:
        raise Stop("The unpacked Java tree is not the locked one")
    return root


def verified_copy(source_root, files, destination):
    """Copy exactly the locked files from a folder you named, refusing a missing or changed file; extra files in it are ignored."""
    source_root, destination = Path(source_root), Path(destination)
    if destination.exists():
        if package.snapshot(destination) == files:
            return destination
        raise Stop("The folder " + str(destination) + " already exists and is not the locked tree; remove it or choose another work folder")
    for name, digest in files.items():
        source = package.regular(source_root.joinpath(*name.split("/")))
        if package.sha(source) != digest:
            raise Stop("A file in " + str(source_root) + " has changed from the lock: " + name)
    for name in files:
        target = destination.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root.joinpath(*name.split("/")), target)
    if package.snapshot(destination) != files:
        raise Stop("The copied tree differs from the lock")
    return destination


def checked_tree(root, files, label):
    root = Path(root)
    for name, digest in files.items():
        path = package.regular(root.joinpath(*name.split("/")))
        if package.sha(path) != digest:
            raise Stop(label + ": a file differs from the lock: " + name)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--tesseract-source", type=Path, required=True, help="a folder holding the locked 138-file Tesseract tree (it may hold more)")
    parser.add_argument("--models-source", type=Path, required=True, help="a folder holding eng.traineddata, osd.traineddata, LICENSE, README.md")
    parser.add_argument("--odl-source", type=Path, required=True)
    parser.add_argument("--verapdf-source", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    work = args.work.absolute()
    try:
        runtime, runtime_sha, _ = package.load_runtime_lock()
        ocr, ocr_sha, _ = package.load_ocr_lock()
        native, _ = package.load_native_lock()
        downloads = work / "downloads"
        python = fetch(runtime["python"], downloads, args.dry_run)
        wheel_paths = {}
        for lock in (runtime, ocr):
            for item in lock["wheels"]:
                wheel_paths.setdefault(item["filename"], fetch(item, downloads, args.dry_run))
        java_archive = fetch({"filename": native["java"]["archive"]["filename"], "origin": native["java"]["origin"],
                              "sha256": native["java"]["archive"]["sha256"]}, downloads, args.dry_run)
        odl = checked_tree(args.odl_source, native["odl"]["files"], "OpenDataLoader")
        verapdf = checked_tree(args.verapdf_source, native["verapdf"]["files"], "veraPDF")
        if args.dry_run:
            print("dry run: the local OpenDataLoader and veraPDF trees match their locks; nothing was changed")
            return 0
        java = unpack_java(java_archive, native, work)
        tesseract = verified_copy(args.tesseract_source, ocr["native"]["files"], work / "tesseract-factory")
        models_root = work / "models"
        models = []
        for row in ocr["models"]:
            source = package.regular(args.models_source / row["filename"])
            if package.sha(source) != row["sha256"]:
                raise Stop("A model or legal file differs from the lock: " + row["filename"])
            models_root.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, models_root / row["filename"])
            models.append({**{key: row[key] for key in ("filename", "version", "origin", "sha256")}, "path": str(models_root / row["filename"])})
        source_root = ROOT / "src" / "pdf_remediator"
        allowed = package.ICON_ASSETS | set(package.EDITOR_FONT_ASSETS)
        source_files = {}
        for path in sorted(source_root.rglob("*")):
            relative = path.relative_to(ROOT).as_posix()
            if path.is_file() and "__pycache__" not in path.parts and (path.suffix in SOURCE_SUFFIXES or relative in allowed):
                source_files[relative] = package.sha(path)
        notice_files = {name: package.sha(ROOT / name) for name in ("LICENSE", "NOTICE", "THIRD-PARTY-NOTICES.md")}
        for path in sorted((ROOT / "third-party" / "licenses").iterdir()):
            if path.is_file():
                notice_files["third-party/licenses/" + path.name] = package.sha(path)
        plan = {
            "schema": "windows-internal-inputs-1", "release_status": "internal-unqualified", "ai_enabled": False,
            "redistribution_cleared": False, "ocr_enabled": True,
            "runtime_lock_sha256": runtime_sha,
            "python": {**runtime["python"], "path": str(python)},
            "wheels": [{**item, "path": str(wheel_paths[item["filename"]])} for item in runtime["wheels"]],
            "native": {"java": {"root": str(java), "origin": native["java"]["origin"], "files": native["java"]["files"]},
                       "odl": {"root": str(odl), "origin": native["odl"]["origin"], "files": native["odl"]["files"]},
                       "verapdf": {"root": str(verapdf), "origin": native["verapdf"]["origin"], "files": native["verapdf"]["files"]}},
            "source": {"root": str(ROOT), "origin": package.HOMEPAGE, "files": source_files},
            "notices": {"root": str(ROOT), "origin": package.HOMEPAGE, "files": notice_files},
            "ocr": {"runtime_lock_sha256": ocr_sha,
                    "python": {**ocr["python"], "path": str(python)},
                    "wheels": [{**item, "path": str(wheel_paths[item["filename"]])} for item in ocr["wheels"]],
                    "tesseract": {"root": str(tesseract), **ocr["native"]},
                    "models": models},
        }
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        with args.plan.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(plan, stream, indent=1, sort_keys=True)
            stream.write("\n")
        print("plan written:", args.plan, "| source files:", len(source_files), "| notice files:", len(notice_files), "| wheels:", len(wheel_paths))
        return 0
    except (Stop, package.Refusal, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print("No plan was made: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
