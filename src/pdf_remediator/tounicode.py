"""Bounded reading and exact rewriting of PDF ToUnicode CMaps.

This is a plain parser for the character-to-Unicode maps that PDF files carry.
It never guesses a missing entry, never follows ``usecmap`` and refuses
anything outside its small, explicit grammar, so a caller can rely on
``parse(serialize(parse(raw))) == parse(raw)`` for every CMap it accepts.
"""
from __future__ import annotations

import re

MAX_BYTES = 4 * 1024 * 1024
MAX_ENTRIES = 70000
MAX_TEXT_CODE_POINTS = 16
_HEX = rb"<([0-9A-Fa-f\s]*)>"
_TOKEN = re.compile(rb"<[0-9A-Fa-f\s]*>|\[|\]|[^\s<>\[\]]+")


class CMapError(ValueError):
    pass


def _hex(token):
    digits = re.sub(rb"\s", b"", token[1:-1])
    if not digits or len(digits) % 2:
        raise CMapError("Odd or empty hexadecimal string in the CMap")
    return bytes.fromhex(digits.decode("ascii"))


def _text(raw):
    if not raw or len(raw) % 2:
        raise CMapError("A destination is not whole UTF-16BE code units")
    try:
        value = raw.decode("utf-16-be")
    except UnicodeDecodeError as exc:
        raise CMapError("A destination holds an unpaired surrogate") from exc
    if len(value) > MAX_TEXT_CODE_POINTS:
        raise CMapError("A destination is longer than the supported text length")
    return value


def parse(raw):
    """Return ``{'codespaces': [(width, low, high)], 'entries': {(width, code): text}}``."""
    try:
        return _parse(raw)
    except (IndexError, ValueError) as exc:
        if isinstance(exc, CMapError):
            raise
        raise CMapError("Malformed CMap: " + type(exc).__name__) from exc


def _parse(raw):
    if not isinstance(raw, (bytes, bytearray)):
        raise CMapError("A CMap must be bytes")
    raw = bytes(raw)
    if len(raw) > MAX_BYTES:
        raise CMapError("CMap exceeds the bounded parser size")
    text = re.sub(rb"%[^\r\n]*", b"", raw)
    if b"usecmap" in text:
        raise CMapError("An inherited CMap (usecmap) is outside the supported scope")
    if not re.search(rb"\bbegincmap\b", text) or len(re.findall(rb"\bendcmap\b", text)) != 1:
        raise CMapError("Not a single complete CMap")
    tokens = _TOKEN.findall(text)
    codespaces, entries = [], {}
    index = 0

    def add(width, code, value):
        if (width, code) in entries:
            raise CMapError("A code is mapped more than once")
        if len(entries) >= MAX_ENTRIES:
            raise CMapError("CMap has more entries than the supported limit")
        if code >> (8 * width):
            raise CMapError("A code does not fit its declared width")
        entries[(width, code)] = value

    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == b"begincodespacerange":
            while tokens[index] != b"endcodespacerange":
                low, high = _hex(tokens[index]), _hex(tokens[index + 1])
                index += 2
                if len(low) != len(high) or not 1 <= len(low) <= 2:
                    raise CMapError("Only one- and two-byte code space ranges are supported")
                codespaces.append((len(low), int.from_bytes(low, "big"), int.from_bytes(high, "big")))
            index += 1
        elif token == b"beginbfchar":
            while tokens[index] != b"endbfchar":
                source, destination = tokens[index], tokens[index + 1]
                index += 2
                if not source.startswith(b"<") or not destination.startswith(b"<"):
                    raise CMapError("Unsupported bfchar destination")
                code = _hex(source)
                if len(code) > 2:
                    raise CMapError("Only one- and two-byte codes are supported")
                add(len(code), int.from_bytes(code, "big"), _text(_hex(destination)))
            index += 1
        elif token == b"beginbfrange":
            while tokens[index] != b"endbfrange":
                low, high, destination = _hex(tokens[index]), _hex(tokens[index + 1]), tokens[index + 2]
                index += 3
                if len(low) != len(high) or not 1 <= len(low) <= 2:
                    raise CMapError("Only one- and two-byte code ranges are supported")
                first, last, width = int.from_bytes(low, "big"), int.from_bytes(high, "big"), len(low)
                if last < first or last - first > 0xFFFF:
                    raise CMapError("Reversed or oversized bfrange")
                if destination == b"[":
                    items = []
                    while tokens[index] != b"]":
                        items.append(_text(_hex(tokens[index])))
                        index += 1
                    index += 1
                    if len(items) != last - first + 1:
                        raise CMapError("A bfrange array has the wrong length")
                    for offset, value in enumerate(items):
                        add(width, first + offset, value)
                elif destination.startswith(b"<"):
                    base = _hex(destination)
                    start = int.from_bytes(base, "big")
                    for offset in range(last - first + 1):
                        try:
                            value = (start + offset).to_bytes(len(base), "big")
                        except OverflowError as exc:
                            raise CMapError("A bfrange destination overflows its length") from exc
                        add(width, first + offset, _text(value))
                else:
                    raise CMapError("Unsupported bfrange destination")
            index += 1
    if not entries:
        raise CMapError("The CMap holds no mappings")
    if not codespaces:
        widths = {width for width, _ in entries}
        codespaces = [(width, 0, (1 << (8 * width)) - 1) for width in sorted(widths)]
    for (width, code) in entries:
        if not any(w == width and low <= code <= high for w, low, high in codespaces):
            raise CMapError("A mapped code lies outside the declared code space")
    return {"codespaces": codespaces, "entries": entries}


def serialize(parsed):
    """Write a complete, deterministic ToUnicode CMap holding exactly these entries."""
    codespaces, entries = parsed["codespaces"], parsed["entries"]
    if not entries or len(entries) > MAX_ENTRIES:
        raise CMapError("Nothing to write, or too many entries")
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
             "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
             "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
             f"{len(codespaces)} begincodespacerange"]
    for width, low, high in codespaces:
        lines.append(f"<{low:0{2 * width}X}> <{high:0{2 * width}X}>")
    lines.append("endcodespacerange")
    ordered = sorted(entries.items())
    for start in range(0, len(ordered), 100):
        block = ordered[start:start + 100]
        lines.append(f"{len(block)} beginbfchar")
        for (width, code), value in block:
            lines.append(f"<{code:0{2 * width}X}> <{value.encode('utf-16-be').hex().upper()}>")
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end", ""]
    data = "\n".join(lines).encode("ascii")
    if parse(data) != {"codespaces": [tuple(c) for c in codespaces], "entries": dict(entries)}:
        raise CMapError("The written CMap does not read back to the same entries")
    return data
