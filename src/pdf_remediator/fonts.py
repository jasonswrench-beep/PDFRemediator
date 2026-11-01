"""Opt-in closure of two proven missing Type1 TeX Unicode mappings.

This does not substitute a font, infer a character from a glyph ID, or replace
an existing mapping. It requires the unchanged original embedded Type1 program
and exact built-in Encoding lineage, plus pinned official mapping data.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
from pathlib import Path
import re
import shutil

import pikepdf
import pypdfium2 as pdfium

from .inspection import compare_fidelity
from .process import cancelled

DATA = Path(__file__).parent / "data/glyphtounicode-cmr-4390c8bf.tex"
MAP_SHA256 = "4390c8bfb8a6f709b90b7502ae4accb74815a5269d99f18bb97c1dde95c16c2a"
AUTHORITY = {"package": "CTAN pdfx", "package_version": "1.6.5f", "file_revision": "2018/09/18 RRM",
             "url": "https://ctan.math.illinois.edu/macros/latex/contrib/pdfx/glyphtounicode-cmr.tex",
             "package_url": "https://ctan.org/pkg/pdfx", "file_sha256": MAP_SHA256,
             "license": "LPPL-1.2-or-later; unchanged source distributed with LPPL-1.3c",
             "scope": "Only exact glyph names mapsto and radicalBig; no general mathematical semantics claim"}


class Refused(ValueError):
    pass


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _authority():
    data = DATA.read_bytes()
    if _sha_bytes(data) != MAP_SHA256:
        raise Refused("Official mapping data integrity mismatch")
    entries = {}
    for name in ("mapsto", "radicalBig"):
        matches = re.findall(rb"\\pdfglyphtounicode\{" + name.encode("ascii") + rb"\}\{([0-9A-F ]+)\}", data)
        if len(matches) != 1:
            raise Refused("Official glyph mapping is missing or ambiguous")
        raw = bytes.fromhex(matches[0].decode("ascii").replace(" ", ""))
        entries[name] = {"utf16be_hex": raw.hex().upper(), "text": raw.decode("utf-16-be"),
                         "source_line": data[:data.index(b"\\pdfglyphtounicode{" + name.encode() + b"}")].count(b"\n") + 1}
    return entries


def _cmap_entries(raw):
    """Parse the supported one-byte CMap shape; reject ambiguity and usecmap."""
    if len(raw) > 1024 * 1024:
        raise Refused("CMap exceeds bounded parser size")
    text = re.sub(rb"%[^\r\n]*", b"", raw)
    if b"usecmap" in text or len(re.findall(rb"\bendcmap\b", text)) != 1:
        raise Refused("Inherited or malformed CMap is outside the supported repair")
    spaces = re.findall(rb"(\d+)\s+begincodespacerange\s*(.*?)\s*endcodespacerange", text, re.S)
    if len(spaces) != 1 or spaces[0][0] != b"1" or re.sub(rb"\s", b"", spaces[0][1]) != b"<00><FF>":
        raise Refused("Only an explicit one-byte 00-FF CMap is supported")
    entries = {}

    def add(code, value):
        if not 0 <= code <= 255 or code in entries:
            raise Refused("Duplicate or non-one-byte CMap code")
        if not value or len(value) % 2:
            raise Refused("Invalid UTF-16 CMap value")
        value.decode("utf-16-be")
        entries[code] = value

    for count, block in re.findall(rb"(\d+)\s+beginbfchar\s*(.*?)\s*endbfchar", text, re.S):
        pairs = re.findall(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]+)>", block)
        residual = re.sub(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]+)>", b"", block)
        if len(pairs) != int(count) or residual.strip():
            raise Refused("Unsupported bfchar block")
        for code, value in pairs:
            add(int(code, 16), bytes.fromhex(value.decode()))
    for count, block in re.findall(rb"(\d+)\s+beginbfrange\s*(.*?)\s*endbfrange", text, re.S):
        ranges = re.findall(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{2})>\s*(<[^>]+>|\[[^]]*\])", block)
        residual = re.sub(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{2})>\s*(<[^>]+>|\[[^]]*\])", b"", block)
        if len(ranges) != int(count) or residual.strip():
            raise Refused("Unsupported bfrange block")
        for start, end, value in ranges:
            first, last = int(start, 16), int(end, 16)
            if last < first:
                raise Refused("Reversed CMap range")
            if value.startswith(b"["):
                values = re.findall(rb"<([0-9A-Fa-f]+)>", value)
                if len(values) != last - first + 1:
                    raise Refused("CMap array length mismatch")
                for code, item in zip(range(first, last + 1), values):
                    add(code, bytes.fromhex(item.decode()))
            else:
                initial = bytes.fromhex(value[1:-1].decode())
                for code in range(first, last + 1):
                    add(code, (int.from_bytes(initial, "big") + code - first).to_bytes(len(initial), "big"))
    if not entries:
        raise Refused("No explicit existing CMap mappings")
    return entries


def _font_record(font, cache):
    if font.get("/Subtype") != pikepdf.Name.Type1 or font.get("/Encoding") is not None:
        return None
    program = font.get("/FontDescriptor", {}).get("/FontFile")
    cmap = font.get("/ToUnicode")
    if not isinstance(program, pikepdf.Stream) or not isinstance(cmap, pikepdf.Stream):
        return None
    raw = program.read_bytes()
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise Refused("Unsupported Type1 font program size")
    program_hash = _sha_bytes(raw)
    if program_hash not in cache:
        from fontTools.t1Lib import T1Font
        parsed = T1Font.__new__(T1Font)
        parsed.data, parsed.encoding = raw, "ascii"
        encoding = parsed["Encoding"]
        glyph_names = set(parsed["CharStrings"])
        if not isinstance(encoding, list) or len(encoding) != 256:
            raise Refused("Type1 built-in Encoding is not a 256-entry name array")
        cache[program_hash] = (encoding, glyph_names)
    encoding, glyph_names = cache[program_hash]
    return {"font": font, "object": list(font.objgen), "base_font": str(font.get("/BaseFont", "")),
            "program_sha256": program_hash, "program_bytes": len(raw), "encoding": encoding,
            "glyph_names": glyph_names, "cmap": cmap.read_bytes(), "entries": _cmap_entries(cmap.read_bytes()),
            "widths": str(font.get("/Widths")), "first_char": int(font.get("/FirstChar", -1)),
            "last_char": int(font.get("/LastChar", -1))}


def _identity(record):
    return (record["base_font"], record["program_sha256"], tuple(record["encoding"]),
            record["widths"], record["first_char"], record["last_char"])


def _add_cmap(pdf, record, changes):
    original = record["cmap"]
    lines = [f"{len(changes)} beginbfchar"]
    lines += [f"<{change['code']:02X}> <{change['utf16be_hex']}>" for change in changes]
    lines += ["endbfchar", ""]
    insertion = "\n".join(lines).encode("ascii")
    position = original.rfind(b"endcmap")
    if position < 0:
        raise Refused("No CMap end marker")
    repaired = original[:position] + insertion + original[position:]
    entries = _cmap_entries(repaired)
    expected = dict(record["entries"])
    for change in changes:
        if change["code"] in expected:
            raise Refused("Existing mappings may never be rewritten")
        expected[change["code"]] = bytes.fromhex(change["utf16be_hex"])
    if entries != expected:
        raise Refused("CMap extension changed an existing or unexpected mapping")
    record["font"]["/ToUnicode"] = pikepdf.Stream(pdf, repaired)
    return _sha_bytes(repaired)


def _font_name(textpage, index):
    flags = ctypes.c_int()
    size = pdfium.raw.FPDFText_GetFontInfo(textpage.raw, index, None, 0, ctypes.byref(flags))
    if not 0 < size <= 4096:
        return ""
    buffer = ctypes.create_string_buffer(size)
    pdfium.raw.FPDFText_GetFontInfo(textpage.raw, index, buffer, size, ctypes.byref(flags))
    return buffer.value.decode("utf-8", errors="strict")


def _verify_expected_text(before, after, changes, cancel=None):
    """Accept only the known fallback character at the exact originating font.

    Missing Type1 Unicode entries in this route previously extracted their raw
    one-byte code as a fallback. Every other extracted character must remain
    exactly identical. Different fallback behavior is refused, not normalized.
    """
    by_fallback = {}
    for change in changes:
        base = re.sub(r"^/[A-Z]{6}\+", "", change["base_font"]).lstrip("/")
        by_fallback.setdefault(chr(change["code"]), {})[base] = change
    documents = [pdfium.PdfDocument(str(path)) for path in (before, after)]
    occurrences = []
    page_count = len(documents[0])
    try:
        if len(documents[0]) != len(documents[1]):
            raise Refused("Mapping extension changed page count")
        for index in range(len(documents[0])):
            if cancelled(cancel):
                raise InterruptedError("Font mapping verification cancelled")
            pages = [doc[index] for doc in documents]
            texts = [page.get_textpage() for page in pages]
            try:
                original = texts[0].get_text_range()
                pieces, expected = [], []
                for char_index in range(texts[0].count_chars()):
                    character = texts[0].get_text_range(char_index, 1)
                    pieces.append(character)
                    change = by_fallback.get(character, {}).get(_font_name(texts[0], char_index)) if character in by_fallback else None
                    if change:
                        expected.append(change["text"])
                        occurrences.append({"page": index + 1, "char_index": char_index, "font": change["base_font"],
                                            "code": change["code"], "glyph_name": change["glyph_name"],
                                            "before": character, "after": change["text"]})
                    else:
                        expected.append(character)
                if "".join(pieces) != original:
                    raise Refused("PDFium per-character extraction does not match whole-page extraction")
                if "".join(expected) != texts[1].get_text_range():
                    raise Refused(f"Unexpected extracted text change on page {index + 1}")
            finally:
                for text in texts:
                    text.close()
                for page in pages:
                    page.close()
    finally:
        for doc in documents:
            doc.close()
    if not occurrences:
        raise Refused("No proven missing-code fallback occurrences were found")
    return {"status": "pass", "changed_glyph_occurrences": occurrences,
            "all_other_extracted_characters_unchanged": True, "all_pages_compared": page_count}


def repair_source_mappings(original, processed, destination, reference_destination, cancel=None):
    """Extend source-proven absent mappings in both reference and processed PDF.

    On refusal, no output is published. The returned reference is a deliberately
    corrected source derivative for the normal exact fidelity comparison; raw
    original-to-final text differences must remain in the product report.
    """
    original, processed, destination, reference_destination = [Path(p).resolve() for p in (original, processed, destination, reference_destination)]
    if len({original, processed, destination, reference_destination}) != 4 or destination.exists() or reference_destination.exists():
        raise FileExistsError("Font repair needs two distinct inputs and two new outputs")
    evidence = {"name": "source-unicode-closure", "status": "refused", "authority": dict(AUTHORITY),
                "input_sha256": _sha_file(processed), "original_sha256": _sha_file(original), "changes": [],
                "warnings": [], "authoritative_corrections": [],
                "no_existing_mapping_rewrite": True, "no_font_substitution": True,
                "human_review_pending": ["Check the two TeX symbol mappings and their mathematical/compound-symbol context."]}
    temporary = [destination.with_name(destination.name + ".mapping-partial"), reference_destination.with_name(reference_destination.name + ".mapping-partial")]
    if any(p.exists() for p in temporary):
        raise FileExistsError("Font repair checkpoint already exists")
    created_outputs = []
    try:
        import fontTools
        if fontTools.__version__ != "4.67.0":
            raise Refused("Source font parser must be the tested fontTools 4.67.0")
        evidence["fonttools_version"] = fontTools.__version__
        authority = _authority()
        cache = {}
        with pikepdf.open(original) as source, pikepdf.open(processed) as candidate:
            source_records = []
            for font in source.objects:
                if isinstance(font, pikepdf.Dictionary) and font.get("/Type") == pikepdf.Name.Font:
                    # Avoid parsing unrelated fonts or rewriting mappings merely
                    # because an unrelated font happens to lack a Unicode map.
                    base = str(font.get("/BaseFont", ""))
                    if not re.search(r"\+(?:CMEX10|CMSY10)$", base):
                        continue
                    record = _font_record(font, cache)
                    if record:
                        source_records.append(record)
            changes_by_identity = {}
            for record in source_records:
                changes = []
                for code, name in enumerate(record["encoding"]):
                    if name not in authority or code in record["entries"]:
                        continue
                    if name not in record["glyph_names"]:
                        raise Refused("Encoded glyph is absent from original embedded font program")
                    changes.append({"base_font": record["base_font"], "code": code, "glyph_name": name,
                                    **authority[name], "font_program_sha256": record["program_sha256"],
                                    "font_program_bytes": record["program_bytes"],
                                    "original_cmap_sha256": _sha_bytes(record["cmap"]),
                                    "original_font_object": record["object"]})
                if changes:
                    changes_by_identity[_identity(record)] = (record, changes)
            if not changes_by_identity:
                for before, after in ((original, reference_destination), (processed, destination)):
                    after.parent.mkdir(parents=True, exist_ok=True)
                    with before.open("rb") as inp, after.open("xb") as out:
                        created_outputs.append(after)
                        shutil.copyfileobj(inp, out)
                evidence.update(status="pass", reason="No supported absent TeX mappings; byte-identical reference and processed copies",
                                output=str(destination), output_sha256=_sha_file(destination),
                                reference=str(reference_destination), source_reference_sha256=_sha_file(reference_destination),
                                reference_appearance={"status": "pass", "scope": "Byte-identical reference copy"})
                return evidence
            processed_matches = {}
            target_bases = {record["base_font"] for record, changes in changes_by_identity.values()}
            for font in candidate.objects:
                if isinstance(font, pikepdf.Dictionary) and font.get("/Type") == pikepdf.Name.Font:
                    base = str(font.get("/BaseFont", ""))
                    if base not in target_bases:
                        continue
                    record = _font_record(font, cache)
                    if not record or _identity(record) not in changes_by_identity:
                        raise Refused("Processed target font no longer has the exact original program/encoding/width lineage")
                    original_record, changes = changes_by_identity[_identity(record)]
                    if record["cmap"] != original_record["cmap"]:
                        raise Refused("Processed CMap differs from the authoritative original; no existing mapping may be rewritten")
                    _add_cmap(candidate, record, changes)
                    processed_matches[_identity(record)] = processed_matches.get(_identity(record), 0) + 1
            if set(processed_matches) != set(changes_by_identity):
                raise Refused("Processed output is missing an original target font")
            for identity, (record, changes) in changes_by_identity.items():
                repaired_hash = _add_cmap(source, record, changes)
                evidence["changes"].extend({**change, "repaired_cmap_sha256": repaired_hash,
                                            "processed_font_copies": processed_matches[identity]} for change in changes)
            for path in temporary:
                path.parent.mkdir(parents=True, exist_ok=True)
            candidate.save(temporary[0], deterministic_id=True)
            source.save(temporary[1], deterministic_id=True)
        expected_text = _verify_expected_text(original, temporary[1], evidence["changes"], cancel)
        appearance = compare_fidelity(original, temporary[1], cancel=cancel)
        valid_pages = appearance.get("pages") and all(all(p[key] == "pass" for key in ("render_status", "dimensions_status", "page_boxes_status", "annotations_status")) for p in appearance["pages"])
        remaining = [c for c in appearance.get("checks", []) if c["id"] != "all-page-render-and-content"]
        if not valid_pages or any(c["status"] not in ("pass", "not-applicable") for c in remaining):
            raise Refused("Source mapping extension failed exact all-page visible/navigation preservation")
        evidence.update(expected_text=expected_text, source_reference_fidelity=appearance,
                        source_reference_appearance_navigation_status="pass",
                        reference_appearance={"status": "pass", "all_pages_compared": len(appearance["pages"]),
                                              "scope": "Exact source/reference pixels, page boxes, annotations and navigation"},
                        authoritative_corrections=expected_text["changed_glyph_occurrences"],
                        warnings=["The original fallback text changes only at the recorded missing TeX glyph codes.",
                                  "Composite math symbols and variation-selector behavior require human review."])
        if _sha_file(original) != evidence["original_sha256"] or _sha_file(processed) != evidence["input_sha256"]:
            raise Refused("An input changed while font mapping repair ran")
        temporary[0].replace(destination)
        created_outputs.append(destination)
        temporary[1].replace(reference_destination)
        created_outputs.append(reference_destination)
        evidence.update(status="pass", output=str(destination), output_sha256=_sha_file(destination),
                        reference=str(reference_destination), source_reference_sha256=_sha_file(reference_destination))
    except (OSError, ValueError, TypeError, KeyError, ImportError, AssertionError, OverflowError, pikepdf.PdfError) as exc:
        for path in created_outputs:
            if path.exists():
                path.unlink()
        evidence.update(status="refused", reason=f"{type(exc).__name__}: {exc}")
    finally:
        for path in temporary:
            if path.exists():
                path.unlink()
    return evidence
