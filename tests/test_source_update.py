"""Transactional local source updates from deterministic synthetic ZIPs."""
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest

SCRIPT = Path(__file__).parents[1] / 'scripts/update-local-source.py'
spec = importlib.util.spec_from_file_location('tested_local_source_updater', SCRIPT)
updater = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = updater
spec.loader.exec_module(updater)

PROJECT = b'[project]\nname = "local-pdf-remediator"\nversion = "0.3.0"\n'


def package(label):
    return {name: (f'FLAG = "{label}"\n'.encode() if name.endswith('.py') else b'/* synthetic asset */\n')
            for name in sorted(updater.REQUIRED)}


def archive(path, payload=None, extra=None, metadata=PROJECT):
    entries = {'project/pyproject.toml': metadata, 'project/.gitignore': b'work/\n',
               'project/.gitattributes': b'* text=auto\n'}
    entries.update({'project/src/pdf_remediator/' + name: data
                    for name, data in (package('new') if payload is None else payload).items()})
    entries.update(extra or {})
    with zipfile.ZipFile(path, 'w') as zipped:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            # ZipInfo normalizes backslashes on Windows before writing. These
            # adversarial fixtures must serialize the requested raw spelling.
            info.filename = name
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            zipped.writestr(info, data)
    return path


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / 'installed'
    installed = root / 'src/pdf_remediator'
    for name, data in package('old').items():
        dest = installed / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    (root / 'pyproject.toml').write_bytes(PROJECT)
    for name in ('local-runtime.toml', 'output/review-state.json', 'work/input.txt', '.venvs/app/keep.txt'):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b'Synthetic local sentinel; must remain unchanged\n')
    source = archive(tmp_path / 'source.zip', extra={'project/README.md': b'Do not copy outside package\n'})
    return root, installed, source


def preserved_local(root):
    return {name: (root / name).read_bytes() for name in
            ('pyproject.toml', 'local-runtime.toml', 'output/review-state.json', 'work/input.txt', '.venvs/app/keep.txt')}


def test_default_cli_checks_without_changing_installation(installation, tmp_path):
    root, installed, source = installation
    before, local = updater.snapshot(installed), preserved_local(root)
    run = subprocess.run([sys.executable, str(SCRIPT), '--archive', str(source), '--target', str(root)],
                         cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report['status'] == 'checked-not-applied' and report['publisher_authenticated'] is False
    assert updater.snapshot(installed) == before and preserved_local(root) == local
    assert sorted(p.name for p in (root / 'work').iterdir()) == ['input.txt']


def test_applied_update_has_full_hash_verification_and_retains_original(installation):
    root, installed, source = installation
    cache = installed / '__pycache__/config.cpython-311.pyc'
    cache.parent.mkdir()
    cache.write_bytes(b'Synthetic old bytecode sentinel')
    before, local = updater.snapshot(installed), preserved_local(root)
    result = updater.apply_update(updater.inspect_update(source, root))
    assert result['status'] == 'applied' and result['human_acceptance'] == 'not-assessed'
    assert result['restart_required'] is True
    assert updater.snapshot(installed) == {name: updater.digest(data) for name, data in package('new').items()}
    assert updater.snapshot(Path(result['backup'])) == before
    assert preserved_local(root) == local
    assert not (root / 'README.md').exists()
    assert not (root / 'work/source-update.lock').exists()


@pytest.mark.parametrize('already_has_icons', [False, True])
def test_exact_icon_assets_update_old_and_icon_enabled_installations(installation, already_has_icons):
    root, installed, source = installation
    icons = {'web_assets/PDFRemediator.svg': b'<svg xmlns="http://www.w3.org/2000/svg"/>\n',
             'web_assets/PDFRemediator.ico': b'\x00\x00\x01\x00Synthetic exact icon bytes'}
    if already_has_icons:
        for name in icons:
            path = installed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'Synthetic previous icon; preserve in backup')
    before, local = updater.snapshot(installed), preserved_local(root)
    payload = package('new') | icons
    archive(source, payload=payload)
    result = updater.apply_update(updater.inspect_update(source, root))
    assert updater.snapshot(installed) == {name: updater.digest(data) for name, data in payload.items()}
    assert updater.snapshot(Path(result['backup'])) == before
    assert preserved_local(root) == local
    assert updater.inspect_update(source, root).previous == updater.snapshot(installed)


@pytest.mark.parametrize('name', ['web_assets/other.svg', 'web_assets/other.ico', 'data/PDFRemediator.svg', 'PDFRemediator.ico'])
def test_noncanonical_icon_archive_members_remain_refused(installation, name):
    root, installed, source = installation
    before, local = updater.snapshot(installed), preserved_local(root)
    archive(source, payload=package('new') | {name: b'Synthetic unapproved asset'})
    with pytest.raises(updater.UpdateRefusal, match='Unexpected package artifact'):
        updater.inspect_update(source, root)
    assert updater.snapshot(installed) == before and preserved_local(root) == local


@pytest.mark.parametrize('name', ['web_assets/other.svg', 'web_assets/other.ico'])
def test_noncanonical_installed_icon_members_remain_refused(installation, name):
    root, installed, source = installation
    path = installed / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'Synthetic unapproved installed asset')
    with pytest.raises(updater.UpdateRefusal, match='Unexpected installed file'):
        updater.inspect_update(source, root)
    assert path.read_bytes() == b'Synthetic unapproved installed asset'


@pytest.mark.parametrize('bad_path', [
    '../escape.py', '/absolute.py', 'project/src/pdf_remediator/../../escape.py',
    r'project\src\pdf_remediator\escape.py', 'project/src/pdf_remediator/CON.py',
    'project/src/pdf_remediator/notes:stream.py', 'project/src/pdf_remediator/trailing. /file.py',
    'project/src/pdf_remediator/wild*.py', 'project/src/pdf_remediator/control\x01.py',
    'other-root/file.py', 'project/src/pdf_remediator/PIPELINE.py',
    'project/src/pdf_remediator/pipeline.py/nested.py'])
def test_unsafe_archive_layout_is_refused_before_any_code_change(installation, bad_path):
    root, installed, source = installation
    before, local = updater.snapshot(installed), preserved_local(root)
    archive(source, extra={bad_path: b'FLAG = "unexpected"\n'})
    with zipfile.ZipFile(source) as zipped:
        assert bad_path in [item.orig_filename for item in zipped.infolist()]
    with pytest.raises(updater.UpdateRefusal):
        updater.inspect_update(source, root)
    assert updater.snapshot(installed) == before and preserved_local(root) == local
    assert not list((root / 'work').glob('update-*'))


def test_zip_symlink_is_refused(installation):
    root, installed, source = installation
    with zipfile.ZipFile(source, 'a') as zipped:
        info = zipfile.ZipInfo('project/src/pdf_remediator/link.py')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(info, '../../outside')
    with pytest.raises(updater.UpdateRefusal, match='Linked or special'):
        updater.inspect_update(source, root)
    assert (installed / 'pipeline.py').read_bytes() == package('old')['pipeline.py']


@pytest.mark.parametrize('kind', ['missing-file', 'dependencies', 'syntax', 'artifact', 'size'])
def test_unsupported_source_refuses_without_mutation(installation, kind, monkeypatch):
    root, installed, source = installation
    payload = package('new')
    before = updater.snapshot(installed)
    if kind == 'missing-file':
        payload.pop('pipeline.py')
    elif kind == 'syntax':
        payload['pipeline.py'] = b'def broken(\n'
    elif kind == 'artifact':
        payload['generated.pdf'] = b'Not a distributable source file'
    elif kind == 'size':
        monkeypatch.setattr(updater, 'MAX_PACKAGE_BYTES', 80)
    archive(source, payload=payload, metadata=PROJECT + b'# changed dependencies\n' if kind == 'dependencies' else PROJECT)
    with pytest.raises((updater.UpdateRefusal, SyntaxError)):
        updater.inspect_update(source, root)
    assert updater.snapshot(installed) == before


@pytest.mark.parametrize('kind', ['archive', 'installed', 'metadata'])
def test_changes_after_inspection_are_refused(installation, kind):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    if kind == 'archive':
        source.write_bytes(source.read_bytes() + b'changed')
    elif kind == 'installed':
        (installed / 'pipeline.py').write_bytes(b'FLAG = "newer local edit"\n')
    else:
        (root / 'pyproject.toml').write_bytes(PROJECT + b'# local edit\n')
    before, local = updater.snapshot(installed), preserved_local(root)
    with pytest.raises(updater.UpdateRefusal, match='changed after inspection'):
        updater.apply_update(plan)
    assert updater.snapshot(installed) == before and preserved_local(root) == local
    assert not list((root / 'work').glob('code-backup-*'))
    assert not (root / 'work/source-update.lock').exists()


@pytest.mark.parametrize('kind', ['rename-error', 'corrupted-install', 'interrupted'])
def test_failure_during_replacement_rolls_back_verified_original(installation, monkeypatch, kind):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    original_rename = updater.rename
    before, local = updater.snapshot(installed), preserved_local(root)
    injected = []
    rename_events = []

    def interrupted_rename(src, dest):
        rename_events.append((src.name, dest.name))
        if src.name.startswith('update-stage-'):
            if kind == 'interrupted':
                injected.append(kind)
                raise KeyboardInterrupt()
            if kind == 'rename-error':
                injected.append(kind)
                raise PermissionError('Synthetic replacement failure')
            original_rename(src, dest)
            (dest / 'pipeline.py').write_bytes(b'FLAG = "corrupted copy"\n')
            injected.append(kind)
            return
        original_rename(src, dest)

    monkeypatch.setattr(updater, 'rename', interrupted_rename)
    with pytest.raises(updater.UpdateRefusal, match='previous package restored and verified') as refusal:
        updater.apply_update(plan)
    # A genuine earlier filesystem failure can safely roll back too, but does
    # not exercise the explicitly selected synthetic fault. Keep that failure
    # visible with its cause rather than treating it as corrupted-install proof.
    cause = refusal.value.__cause__
    assert injected == [kind], f'Fault not reached; actual cause: {cause!r}; renames: {rename_events!r}'
    assert updater.snapshot(installed) == before and preserved_local(root) == local
    assert not (root / 'work/source-update.lock').exists()
    if kind == 'corrupted-install':
        assert isinstance(cause, updater.UpdateRefusal) and str(cause) == 'Installed package hash mismatch', (cause, rename_events)
        failed = list((root / 'work').glob('failed-update-*'))
        assert len(failed) == 1
        expected_failed = {name: updater.digest(data) for name, data in package('new').items()}
        expected_failed['pipeline.py'] = updater.digest(b'FLAG = "corrupted copy"\n')
        assert updater.snapshot(failed[0]) == expected_failed
    elif kind == 'rename-error':
        assert isinstance(cause, PermissionError) and str(cause) == 'Synthetic replacement failure', (cause, rename_events)
    else:
        assert isinstance(cause, KeyboardInterrupt), (cause, rename_events)


def test_concurrent_update_lock_is_never_removed(installation):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    lock = root / 'work/source-update.lock'
    lock.write_bytes(b'Synthetic other updater')
    with pytest.raises(FileExistsError):
        updater.apply_update(plan)
    assert lock.read_bytes() == b'Synthetic other updater'
    assert updater.snapshot(installed) == plan.previous


def test_cli_refusal_is_nonzero_without_success_message(installation, tmp_path):
    root, installed, source = installation
    before = updater.snapshot(installed)
    run = subprocess.run([sys.executable, str(SCRIPT), '--archive', str(tmp_path / 'absent.zip'),
                          '--target', str(root), '--apply'], capture_output=True, text=True)
    assert run.returncode == 2 and run.stdout == '' and 'Update refused:' in run.stderr
    assert updater.snapshot(installed) == before


def test_synthetic_zip_generation_is_byte_reproducible(tmp_path):
    a, b = archive(tmp_path / 'a.zip'), archive(tmp_path / 'b.zip')
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize('linked_part', ['src', 'work', 'src/pdf_remediator'])
def test_linked_checkout_paths_are_refused(installation, monkeypatch, linked_part):
    root, installed, source = installation
    original = updater.linked
    monkeypatch.setattr(updater, 'linked', lambda path: path == root / linked_part or original(path))
    with pytest.raises(updater.UpdateRefusal, match='linked'):
        updater.inspect_update(source, root)
    assert (installed / 'pipeline.py').read_bytes() == package('old')['pipeline.py']


def test_windows_reparse_attribute_is_checked_without_python312_junction_api():
    from types import SimpleNamespace
    class ReparsePath:
        def exists(self): return True
        def is_symlink(self): return False
        def lstat(self): return SimpleNamespace(st_file_attributes=0x400)
    assert updater.linked(ReparsePath()) is True


def test_linked_parent_after_inspection_is_refused(installation, monkeypatch):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    original = updater.linked
    monkeypatch.setattr(updater, 'linked', lambda path: path == root / 'src' or original(path))
    with pytest.raises(updater.UpdateRefusal, match='became linked'):
        updater.apply_update(plan)
    assert (installed / 'pipeline.py').read_bytes() == package('old')['pipeline.py']


def test_rollback_failure_reports_backup_without_claiming_success(installation, monkeypatch):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    original_rename = updater.rename
    def blocked_rename(src, dest):
        if src.name.startswith(('update-stage-', 'code-backup-')):
            raise PermissionError('Synthetic replacement and restore failures')
        original_rename(src, dest)
    monkeypatch.setattr(updater, 'rename', blocked_rename)
    with pytest.raises(updater.UpdateRefusal, match='Update and rollback failed; keep the app closed. Inspect installed:'):
        updater.apply_update(plan)
    backups = list((root / 'work').glob('code-backup-*'))
    assert len(backups) == 1 and updater.snapshot(backups[0]) == plan.previous
    assert not installed.exists()
    assert not (root / 'work/source-update.lock').exists()


def test_duplicate_zip_entries_refused(installation):
    root, installed, source = installation
    with pytest.warns(UserWarning, match='Duplicate name'):
        with zipfile.ZipFile(source, 'a') as zipped:
            zipped.writestr('project/src/pdf_remediator/pipeline.py', b'FLAG = "duplicate"\n')
    with pytest.raises(updater.UpdateRefusal, match='Duplicate'):
        updater.inspect_update(source, root)
    assert (installed / 'pipeline.py').read_bytes() == package('old')['pipeline.py']


def test_interrupt_immediately_after_backup_rename_restores_original(installation, monkeypatch):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    original_rename = updater.rename
    def interrupted_after_move(src, dest):
        original_rename(src, dest)
        if src == installed:
            raise KeyboardInterrupt()
    monkeypatch.setattr(updater, 'rename', interrupted_after_move)
    with pytest.raises(updater.UpdateRefusal, match='previous package restored and verified'):
        updater.apply_update(plan)
    assert updater.snapshot(installed) == plan.previous
    assert not (root / 'work/source-update.lock').exists()


def test_failed_original_rename_leaves_existing_code_in_place(installation, monkeypatch):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    def denied(src, dest):
        raise PermissionError('Synthetic original directory lock')
    monkeypatch.setattr(updater, 'rename', denied)
    with pytest.raises(PermissionError, match='original directory lock'):
        updater.apply_update(plan)
    assert updater.snapshot(installed) == plan.previous
    assert not list((root / 'work').glob('code-backup-*'))
    assert not (root / 'work/source-update.lock').exists()


def test_staged_application_code_is_compiled_but_never_imported(installation):
    root, installed, source = installation
    payload = package('new')
    payload['__init__.py'] = b'raise RuntimeError("Application must not execute during update")\n'
    archive(source, payload=payload)
    result = updater.apply_update(updater.inspect_update(source, root))
    assert result['status'] == 'applied'
    assert (installed / '__init__.py').read_bytes() == payload['__init__.py']


def test_rollback_hash_failure_reports_actual_recovery_locations(installation, monkeypatch):
    root, installed, source = installation
    plan = updater.inspect_update(source, root)
    original_rename = updater.rename
    def edited_after_backup(src, dest):
        original_rename(src, dest)
        if src == installed:
            (dest / 'pipeline.py').write_bytes(b'FLAG = "concurrent original edit"\n')
    monkeypatch.setattr(updater, 'rename', edited_after_backup)
    with pytest.raises(updater.UpdateRefusal, match='Update and rollback failed') as error:
        updater.apply_update(plan)
    assert str(installed) in str(error.value)
    assert 'backup:' in str(error.value) and 'displaced:' in str(error.value)
    assert (installed / 'pipeline.py').read_bytes() == b'FLAG = "concurrent original edit"\n'


def test_backslash_fixture_survives_windows_zip_filename_normalization(installation, monkeypatch):
    root, installed, source = installation
    bad_path = r'project\src\pdf_remediator\escape.py'
    before, local = updater.snapshot(installed), preserved_local(root)
    # Exercise the stdlib's real platform separator normalization on Linux too.
    # Windows readers preserve the serialized spelling in orig_filename even
    # when filename is normalized, so inspect exactly what the updater reads.
    with monkeypatch.context() as platform:
        platform.setattr(zipfile.os, 'sep', '\\')
        assert zipfile.ZipInfo(bad_path).filename == bad_path.replace('\\', '/')
        archive(source, extra={bad_path: b'FLAG = "unexpected"\n'})
        with zipfile.ZipFile(source) as zipped:
            assert bad_path in [item.orig_filename for item in zipped.infolist()]
        with pytest.raises(updater.UpdateRefusal, match='Unsafe archive path'):
            updater.inspect_update(source, root)
    assert updater.snapshot(installed) == before and preserved_local(root) == local
