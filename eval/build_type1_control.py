"""Generate a two-symbol PDF from unchanged, licensed AMS Type1 programs.

No book, engine, model, OCR, or network is used. Supply the reviewed AMS archive;
missing or changed dependencies fail. Font programs and OFL notice stay beside
local generated fixtures, never in Git. This is not mathematical acceptance.
"""
from pathlib import Path
import argparse
import hashlib
import struct
import zipfile

import pikepdf

ARCHIVE_SHA256 = "aaab3930b952128b7ed65260144493eb3d88cb063b50da1f90272e23c7e08ba2"
FILES = {
    "cmsy10.pfb": "62ee8cef552017551cd3e026a483e700730103eceaad959c87b7730017f59cff",
    "cmex10.pfb": "791b31aa1db8608d0144b3a40fc0fe53383a60f6b00d0e8fd9f06ac4a11df8cb",
    "OFL.txt": "aa783fdd47e92743bafe79277ac4067d20339344dc5b64a09c2d0f869b2999dc",
}


def _program(data):
    """Unwrap PFB transport segments without rewriting any Type1 program byte."""
    chunks, offset = [], 0
    while offset < len(data):
        if data[offset] != 128:
            raise ValueError("Invalid PFB marker")
        kind = data[offset + 1]
        offset += 2
        if kind == 3:
            if offset != len(data):
                raise ValueError("Trailing PFB data")
            break
        if kind not in (1, 2):
            raise ValueError("Invalid PFB segment type")
        length = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        chunk = data[offset:offset + length]
        if len(chunk) != length:
            raise ValueError("Truncated PFB segment")
        chunks.append((kind, chunk))
        offset += length
    if [kind for kind, _ in chunks] != [1, 2, 1] or kind != 3:
        raise ValueError("Unexpected pinned PFB segment shape")
    return b''.join(chunk for _, chunk in chunks), [len(chunk) for _, chunk in chunks]


def build_control(path, archive, existing_mapsto=False):
    path, archive = Path(path), Path(archive)
    if path.exists():
        raise FileExistsError(path)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("AMS archive integrity mismatch")
    data = {}
    with zipfile.ZipFile(archive) as z:
        for name, digest in FILES.items():
            entry = 'amsfonts/' + ('doc/' if name == 'OFL.txt' else 'pfb/') + name
            raw = z.read(entry)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("AMS fixture asset integrity mismatch: " + name)
            data[name] = raw
    path.parent.mkdir(parents=True, exist_ok=True)
    assets = path.parent / 'ams-font-assets'
    assets.mkdir(exist_ok=True)
    for name, raw in data.items():
        asset = assets / name
        if asset.exists():
            if asset.read_bytes() != raw:
                raise ValueError("Existing font evidence changed")
        else:
            with asset.open('xb') as stream:
                stream.write(raw)
    with pikepdf.Pdf.new() as pdf:
        selected = {}
        for key, name in [('SY', 'cmsy10'), ('EX', 'cmex10')]:
            raw, lengths = _program(data[name + '.pfb'])
            from fontTools.t1Lib import T1Font
            parsed = T1Font.__new__(T1Font)
            parsed.data, parsed.encoding = raw, 'ascii'
            encoding, strings = parsed['Encoding'], parsed['CharStrings']
            widths = []
            for glyph in encoding:
                string = strings.get(glyph, strings['.notdef'])
                string.decompile()
                program = string.program
                widths.append(program[1] if program[2] == 'hsbw' else 0)
            program = pdf.make_stream(raw)
            for index, length in enumerate(lengths, 1):
                program['/Length' + str(index)] = length
            base = pikepdf.Name('/SYNTHA+' + name.upper())
            descriptor = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.FontDescriptor, FontName=base, Flags=4,
                FontBBox=pikepdf.Array(parsed['FontBBox']), ItalicAngle=parsed['FontInfo']['ItalicAngle'],
                Ascent=800, Descent=-3000, CapHeight=700, StemV=80, FontFile=program))
            cmap = (b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n'
                    b'/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
                    b'/CMapName /SyntheticKnownMissing def /CMapType 2 def\n'
                    b'1 begincodespacerange\n<00> <FF>\nendcodespacerange\n'
                    b'1 beginbfchar\n<00> <2212>\nendbfchar\nendcmap\n'
                    b'CMapName currentdict /CMap defineresource pop end end')
            if key == 'SY' and existing_mapsto:
                cmap = cmap.replace(b'endcmap', b'1 beginbfchar\n<37> <0037>\nendbfchar\nendcmap')
            selected[key] = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                BaseFont=base, FirstChar=0, LastChar=255, Widths=pikepdf.Array(widths),
                FontDescriptor=descriptor, ToUnicode=pdf.make_stream(cmap)))
        page = pdf.add_blank_page(page_size=(240, 160))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(**selected))
        page.Contents = pdf.make_stream(b'BT /SY 24 Tf 30 90 Td (7) Tj /EX 24 Tf 30 0 Td (q) Tj ET')
        pdf.docinfo.Title = 'Synthetic exact-source Type1 mapping control'
        pdf.save(path, deterministic_id=True)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--amsfonts-archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build_control(args.output, args.amsfonts_archive)
