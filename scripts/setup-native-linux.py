"""Provision reviewed uploaded archives locally; never download or change PATH.

Use a fresh output directory, an explicit Java home and a preinstalled ODL JAR.
This installs veraPDF CLI/docs and creates local config, not qualification.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pdf_remediator.doctor import odl_identity

VERAPDF_SHA = 'b512bf24945503a33fc10738ecffc1f2dccaaf8593a448e94ee9ac86a9559a59'
AMS_SHA = 'aaab3930b952128b7ed65260144493eb3d88cb063b50da1f90272e23c7e08ba2'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validator-archive', type=Path, required=True)
    parser.add_argument('--amsfonts-archive', type=Path, required=True)
    parser.add_argument('--java-home', type=Path, required=True)
    parser.add_argument('--odl-jar', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('This provisioning script is Linux-specific')
    for path, expected in [(args.validator_archive, VERAPDF_SHA), (args.amsfonts_archive, AMS_SHA)]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            parser.error('Reviewed archive hash mismatch: ' + path.name)
    if odl_identity(args.odl_jar)['status'] != 'available':
        parser.error('Pinned ODL 2.5.13 JAR is required')
    java_home = args.java_home.resolve()
    if not (java_home / 'bin/java').is_file():
        parser.error('Selected Java home has no bin/java')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(args.validator_archive) as archive:
        for info in archive.infolist():
            path = Path(info.filename)
            if path.is_absolute() or '..' in path.parts or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Unsafe installer archive entry')
        archive.extractall(output)
    shutil.copyfile(args.amsfonts_archive, output / 'amsfonts.zip')
    xml = ET.Element('AutomatedInstallation', langpack='eng')
    prefix = 'com.izforge.izpack.panels.'
    ET.SubElement(xml, prefix + 'htmlhello.HTMLHelloPanel', id='welcome')
    target = ET.SubElement(xml, prefix + 'target.TargetPanel', id='install_dir')
    ET.SubElement(target, 'installpath').text = str(output / 'verapdf')
    packs = ET.SubElement(xml, prefix + 'packs.PacksPanel', id='sdk_pack_select')
    for index, (name, selected) in enumerate([('veraPDF GUI', 'false'), ('veraPDF CLI', 'true'),
                                             ('veraPDF Documentation', 'true'), ('veraPDF Sample Plugins', 'false')]):
        ET.SubElement(packs, 'pack', index=str(index), name=name, selected=selected)
    ET.SubElement(xml, prefix + 'install.InstallPanel', id='install')
    ET.SubElement(xml, prefix + 'finish.FinishPanel', id='finish')
    xml_path = output / 'auto-install.xml'
    ET.ElementTree(xml).write(xml_path, encoding='utf-8', xml_declaration=True)
    installer = output / 'verapdf-greenfield-1.30.3/verapdf-izpack-installer-1.30.3.jar'
    with (output / 'install.stdout.txt').open('wb') as stdout, (output / 'install.stderr.txt').open('wb') as stderr:
        subprocess.run([str(java_home / 'bin/java'), '-jar', str(installer), str(xml_path)],
                       stdout=stdout, stderr=stderr, timeout=120, check=True)
    config = {'project_root': ROOT, 'java_home': java_home, 'odl_jar': args.odl_jar.resolve(),
              'validator_cli': output / 'verapdf/verapdf'}
    (output / 'runtime.toml').write_text('[runtime]\n' + ''.join(
        key + ' = ' + json.dumps(str(value)) + '\n' for key, value in config.items()) + 'ocr_mode = "off"\n', encoding='utf-8')
    (output / 'archive-hashes.json').write_text(json.dumps(
        {'validator_archive': VERAPDF_SHA, 'amsfonts_archive': AMS_SHA,
         'signature_verified': False, 'scope': 'uploaded archives matching reviewed hashes'}, indent=2) + '\n', encoding='utf-8')
    print('Installed local CLI and config. Run qualify-native-linux.py separately; no qualification is implied.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
