"""Check/apply a trusted source ZIP to an existing editable installation.

Offline, standard-library only. Close PDFRemediator first. Default is inspection;
--apply explicitly replaces only src/pdf_remediator, retaining a complete backup.
The ZIP must come from the owner-selected trusted source: these checks establish
safe layout and copy integrity, not publisher authentication. Dependency changes
require the normal installation workflow and are refused here.
"""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import stat
import sys
import uuid
import zipfile

MAX_FILES = 3000
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
EXTENSIONS = {'.py', '.json', '.txt', '.tex', '.html', '.css', '.js'}
ICON_ASSETS = {'web_assets/PDFRemediator.svg', 'web_assets/PDFRemediator.ico'}
REQUIRED = {'__init__.py', '__main__.py', 'pipeline.py', 'config.py', 'web.py', 'web_assets/app.js'}
RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}


class UpdateRefusal(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise UpdateRefusal(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest_digest(manifest):
    return digest(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode())


def linked(path):
    # Python 3.11 on Windows lacks Path.is_junction(). Cover junction/reparse
    # attributes directly as well as normal POSIX symbolic links.
    if not path.exists() and not path.is_symlink():
        return False
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def snapshot(directory):
    require(directory.is_dir() and not linked(directory), 'Package directory is missing or linked')
    result = {}
    for root, directories, files in os.walk(directory, followlinks=False):
        for name in directories + files:
            entry = Path(root) / name
            require(not linked(entry), 'Linked installed paths are unsupported')
        for name in files:
            entry = Path(root) / name
            require(entry.is_file(), 'Nonregular installed path')
            relative = entry.relative_to(directory).as_posix()
            require(entry.suffix in EXTENSIONS or relative in ICON_ASSETS or entry.suffix == '.pyc' and '__pycache__' in entry.parts,
                    'Unexpected installed file; inspect the existing package before updating')
            require(len(result) < MAX_FILES and entry.stat().st_size <= MAX_PACKAGE_BYTES,
                    'Installed package exceeds update limits')
            result[relative] = digest(entry.read_bytes())
    return result


@dataclass
class Plan:
    archive: Path
    target: Path
    archive_sha256: str
    metadata_sha256: str
    payload: dict
    previous: dict

    def public(self):
        files = {name: digest(data) for name, data in self.payload.items()}
        return {'status': 'checked-not-applied', 'archive_sha256': self.archive_sha256,
                'files': len(files), 'package_sha256': manifest_digest(files),
                'previous_package_sha256': manifest_digest(self.previous),
                'dependencies_changed': False, 'publisher_authenticated': False}


def inspect_update(archive, target):
    archive, raw_target = Path(archive).absolute(), Path(target).absolute()
    target = raw_target.resolve()
    require(raw_target == target, 'Choose a direct checkout path without links or parent traversal')
    for path in (target / 'src', target / 'work'):
        require(not linked(path),
                'Checkout src/work must not be linked')
    installed = target / 'src/pdf_remediator'
    previous = snapshot(installed)
    require(REQUIRED <= set(previous), 'Target is not a complete PDFRemediator source installation')
    metadata_path = target / 'pyproject.toml'
    require(not linked(metadata_path) and metadata_path.stat().st_size <= MAX_PACKAGE_BYTES, 'Unsupported project metadata')
    metadata = metadata_path.read_bytes()
    require(archive.is_file() and archive.stat().st_size <= MAX_ARCHIVE_BYTES, 'Source ZIP is missing or too large')
    before = digest(archive.read_bytes())
    payload, paths = {}, {}
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        require(0 < len(entries) <= MAX_FILES, 'Archive entry count is unsupported')
        require(sum(item.file_size for item in entries) <= MAX_ARCHIVE_BYTES, 'Archive contents exceed limits')
        roots = set()
        for item in entries:
            name = item.orig_filename
            clean = name[:-1] if item.is_dir() else name
            parts = PurePosixPath(clean).parts
            require(name and '\\' not in name and not any(ord(c) < 32 or c in ':<>"|?*' for c in name) and
                    parts and not clean.startswith('/') and str(PurePosixPath(clean)) == clean,
                    'Unsafe archive path')
            require(all(part not in ('.', '..') and part == part.strip(' ') and not part.endswith('.') and
                        part.split('.')[0].upper() not in RESERVED for part in parts),
                    'Unsafe or nonportable archive path')
            key = clean.casefold()
            require(key not in paths, 'Duplicate or case-colliding archive paths')
            paths[key] = item.is_dir()
            roots.add(parts[0])
            kind = stat.S_IFMT(item.external_attr >> 16)
            require(kind in (0, stat.S_IFREG, stat.S_IFDIR), 'Linked or special archive entry')
            require(not item.flag_bits & 1, 'Encrypted source archives are unsupported')
        require(len(roots) == 1, 'Expected exactly one archive root')
        for key in paths:
            require(all(paths.get(str(parent), True) for parent in PurePosixPath(key).parents if str(parent) != '.'),
                    'Archive file/directory collision')
        root = next(iter(roots))
        require(root + '/pyproject.toml' in zipped.namelist(), 'Source ZIP is missing project metadata')
        metadata_info = zipped.getinfo(root + '/pyproject.toml')
        require(metadata_info.file_size <= MAX_PACKAGE_BYTES, 'Oversized project metadata')
        require(zipped.read(metadata_info) == metadata, 'Project metadata/dependencies differ; use the normal installation workflow')
        prefix = root + '/src/pdf_remediator/'
        total = 0
        for item in entries:
            if item.is_dir() or not item.filename.startswith(prefix):
                continue
            name = item.filename[len(prefix):]
            require((PurePosixPath(name).suffix in EXTENSIONS or name in ICON_ASSETS) and '__pycache__' not in PurePosixPath(name).parts,
                    'Unexpected package artifact in source ZIP')
            total += item.file_size
            require(total <= MAX_PACKAGE_BYTES, 'Package contents exceed limits')
            data = zipped.read(item)
            if name.endswith('.py'):
                compile(data, name, 'exec', dont_inherit=True)
            payload[name] = data
    require(REQUIRED <= set(payload), 'Source ZIP is missing required application files')
    require(digest(archive.read_bytes()) == before, 'Source ZIP changed during inspection')
    return Plan(archive, target, before, digest(metadata), payload, previous)


def rename(source, destination):
    source.rename(destination)


def apply_update(plan):
    installed = plan.target / 'src/pdf_remediator'
    work = plan.target / 'work'
    require(plan.target.resolve() == plan.target and not linked(plan.target / 'src'),
            'Checkout path changed or src became linked after inspection')
    require(not linked(work), 'Linked work directory')
    work.mkdir(exist_ok=True)
    lock = work / 'source-update.lock'
    # Exclusive creation prevents concurrent updater processes. It does not stop
    # a running PDFRemediator server: the owner must close that before applying.
    with lock.open('x', encoding='ascii') as stream:
        stream.write(str(os.getpid()))
    token = uuid.uuid4().hex
    staging, backup = work / ('update-stage-' + token), work / ('code-backup-' + token)
    displaced = work / ('failed-update-' + token)
    try:
        require(digest(plan.archive.read_bytes()) == plan.archive_sha256, 'Archive changed after inspection')
        require(not linked(plan.target / 'pyproject.toml') and digest((plan.target / 'pyproject.toml').read_bytes()) == plan.metadata_sha256, 'Project metadata changed after inspection')
        staging.mkdir()
        for name, data in plan.payload.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
        expected = {name: digest(data) for name, data in plan.payload.items()}
        require(snapshot(staging) == expected, 'Staged package hash mismatch')
        require(snapshot(installed) == plan.previous, 'Installed code changed after inspection')
        result = {**plan.public(), 'status': 'applied', 'backup': str(backup),
                  'human_acceptance': 'not-assessed', 'restart_required': True}
        try:
            rename(installed, backup)
            require(snapshot(backup) == plan.previous, 'Original package changed during replacement')
            rename(staging, installed)
            require(snapshot(installed) == expected, 'Installed package hash mismatch')
        except BaseException as error:
            if not backup.exists():
                raise
            try:
                if installed.exists():
                    rename(installed, displaced)
                rename(backup, installed)
                require(snapshot(installed) == plan.previous, 'Restored package hash mismatch')
            except BaseException as rollback_error:
                raise UpdateRefusal(f'Update and rollback failed; keep the app closed. Inspect installed: {installed}; backup: {backup}; displaced: {displaced}') from rollback_error
            raise UpdateRefusal('Update failed; previous package restored and verified') from error
        return result
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='App must be stopped; replace package after all checks')
    args = parser.parse_args()
    try:
        plan = inspect_update(args.archive, args.target)
        result = apply_update(plan) if args.apply else plan.public()
    except (UpdateRefusal, OSError, zipfile.BadZipFile, KeyError, SyntaxError, UnicodeError) as error:
        print('Update refused: ' + str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
