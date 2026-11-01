"""Explicit human corrections to bounded, invisible, locally produced OCR words.

No original, immutable result, saved review, font or Unicode map is overwritten.
The corrected PDF becomes a separate source for ordinary processing and fresh
review. Unsupported text is refused rather than replaced by notes/ActualText.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import copy
import ctypes
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

import pikepdf
import pypdfium2 as pdfium

from .inspection import compare_fidelity, inspect_pdf
from .ocr_angle_evidence import _unicode_cmap
from .process import cancelled

INVENTORY_SCHEMA = "phase2-ocr-text-inventory-1"
PLAN_SCHEMA = "phase2-ocr-text-corrections-1"
LINEAGE_SCHEMA = "phase2-ocr-text-lineage-1"
EVIDENCE_SCHEMA = "phase2-ocr-text-correction-evidence-1"
EXPANDED_INVENTORY_SCHEMA = "phase2-ocr-text-inventory-2"
EXPANDED_PLAN_SCHEMA = "phase2-ocr-text-corrections-2"
FONT_SHA256 = "2ec33f84606cbaa0a1a944488e14f97faf2f6a25ecdd8354f5358f06da13c7d9"
FONT_POLICY = "bundled-noto-sans-latin-greek-cyrillic-no-shaping-1"
_FONT_CACHE = None
MAX_CHARACTERS = 256
MAX_ITEMS = 100_000
MAX_STREAM = 32 * 1024**2
MAX_DEPTH = 12
MAX_ANCESTRY = 8
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_TEXT = {"Tj", "TJ", "'", '"'}
_LIMITS = ["Only existing uniquely encoded, invisible OCR word occurrences are editable.",
           "New glyphs, word insertion/deletion, shared Forms, clipping and ambiguous text are unsupported.",
           "Saving or applying a correction is not accessibility approval; accuracy, completeness and reading order still require review."]


class OCRCorrectionError(ValueError):
    pass


def _matrix(outer, inner):
    a,b,c,d,e,f = outer; g,h,i,j,k,l = inner
    return (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)


def _inverse(matrix):
    a,b,c,d,e,f = matrix; det = a*d-b*c
    _need(math.isfinite(det) and abs(det) > 1e-12, "OCR placement has a singular coordinate transform")
    return (d/det,-b/det,-c/det,a/det,(c*f-d*e)/det,(b*e-a*f)/det)


def _point(matrix, x, y):
    a,b,c,d,e,f = matrix
    return (a*x+c*y+e,b*x+d*y+f)


def _qualified_font():
    """Program resource only: no host font lookup, network or OCR import."""
    global _FONT_CACHE
    path = Path(__file__).with_name("data") / "NotoSans-Regular.ttf"
    _need(path.is_file() and _sha(path) == FONT_SHA256, "The qualified bundled correction font is missing or changed")
    from fontTools.ttLib import TTFont
    raw = path.read_bytes()
    _need(hashlib.sha256(raw).hexdigest() == FONT_SHA256,"The bundled correction font changed while it was read")
    if _FONT_CACHE is not None: return _FONT_CACHE
    with TTFont(io.BytesIO(raw)) as font:
        cmap = font.getBestCmap(); order = font.getGlyphOrder(); upem = font["head"].unitsPerEm
        metrics = {}; gids = {}; widths = {}
        for code, name in cmap.items():
            char = chr(code); category = unicodedata.category(char); label = unicodedata.name(char, "")
            allowed = (char == " " or (0 < code <= 0xffff and category[0] in "LNPS"
                and unicodedata.bidirectional(char) not in ("R", "AL", "AN", "BN")
                and (category[0] != "L" or label.startswith(("LATIN ", "GREEK ", "CYRILLIC ")))))
            if not allowed or name == ".notdef": continue
            glyph = font["glyf"][name]
            if glyph.isComposite(): glyph.recalcBounds(font["glyf"])
            advance = font["hmtx"].metrics[name][0] * 1000 / upem
            if advance <= 0: continue
            metrics[char] = [getattr(glyph,key,0)*1000/upem for key in ("xMin","yMin","xMax","yMax")]
            gids[code] = font.getGlyphID(name); widths[code] = advance
        _need(32 in gids and all(ord(c) in gids for c in "éñΩЖ"), "The bundled correction font lacks its qualified coverage")
        descriptor = {"bbox": [getattr(font["head"],key)*1000/upem for key in ("xMin","yMin","xMax","yMax")],
                      "ascent": font["hhea"].ascent*1000/upem, "descent": font["hhea"].descent*1000/upem,
                      "capheight": getattr(font["OS/2"],"sCapHeight",font["hhea"].ascent)*1000/upem}
    characters = "".join(chr(code) for code in sorted(gids) if code != 32)
    _FONT_CACHE = {"path":str(path),"sha256":FONT_SHA256,"raw":raw,"characters":characters,"gids":gids,
                   "widths":widths,"metrics":metrics,"descriptor":descriptor}
    return _FONT_CACHE


def _private_font(pdf, qualified):
    """An independent full embedded font; existing resources are never modified."""
    widths = qualified["widths"]; gids = qualified["gids"]; d = qualified["descriptor"]
    descriptor = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor, FontName=pikepdf.Name("/NotoSans-Regular"),
        Flags=32, FontBBox=pikepdf.Array([Decimal(str(v)) for v in d["bbox"]]), ItalicAngle=0,
        Ascent=Decimal(str(d["ascent"])), Descent=Decimal(str(d["descent"])), CapHeight=Decimal(str(d["capheight"])),
        StemV=80, FontFile2=pdf.make_stream(qualified["raw"])))
    descriptor.FontFile2.Length1 = len(qualified["raw"])
    table = bytearray((max(gids)+1)*2)
    for code,gid in gids.items(): table[code*2:code*2+2] = gid.to_bytes(2,"big")
    entries = []
    for code in sorted(widths): entries.extend([code,pikepdf.Array([Decimal(str(widths[code]))])])
    child = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.CIDFontType2,
        BaseFont=pikepdf.Name("/NotoSans-Regular"), CIDSystemInfo=pikepdf.Dictionary(Registry="Adobe",Ordering="Identity",Supplement=0),
        FontDescriptor=descriptor,CIDToGIDMap=pdf.make_stream(bytes(table)),DW=1000,W=pikepdf.Array(entries)))
    pairs = [f"<{code:04X}> <{code:04X}>" for code in sorted(gids)]
    chunks = [f"{len(pairs[n:n+100])} beginbfchar\n"+"\n".join(pairs[n:n+100])+"\nendbfchar" for n in range(0,len(pairs),100)]
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /PDFRemediatorOCRCorrection def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            +"\n".join(chunks)+"\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n")
    return pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type0,
        BaseFont=pikepdf.Name("/NotoSans-Regular"),Encoding=pikepdf.Name("/Identity-H"),DescendantFonts=pikepdf.Array([child]),
        ToUnicode=pdf.make_stream(cmap.encode("ascii"))))


def _need(value, message):
    if not value:
        raise OCRCorrectionError(message)


def _cancel(cancel):
    if cancelled(cancel):
        raise InterruptedError("OCR text correction was cancelled")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            h.update(block)
    return h.hexdigest()


def _bind(path):
    path = Path(path).resolve()
    _need(path.is_file(), "A bound OCR correction file is unavailable")
    return {"path": str(path), "sha256": _sha(path)}


def _checked(row):
    _need(isinstance(row, dict) and set(row) == {"path", "sha256"}
          and isinstance(row["path"], str) and isinstance(row["sha256"], str)
          and bool(_SHA.fullmatch(row["sha256"])), "Invalid OCR correction file binding")
    path = Path(row["path"]).resolve()
    _need(_sha(path) == row["sha256"], "A bound OCR correction input changed")
    return path


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _save(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def _number(value):
    _need(not isinstance(value, bool), "Boolean PDF text measurement is unsupported")
    n = float(value)
    _need(math.isfinite(n), "Non-finite PDF text measurement is unsupported")
    return n


def _font_info(font):
    _need(isinstance(font, pikepdf.Dictionary) and font.get("/Subtype") == pikepdf.Name.Type0
          and font.get("/Encoding") == pikepdf.Name("/Identity-H"), "Only mapped horizontal embedded Type0 OCR fonts are supported")
    descendants = font.get("/DescendantFonts", [])
    _need(len(descendants) == 1 and descendants[0].get("/Subtype") == pikepdf.Name.CIDFontType2,
          "OCR font descendants are unsupported")
    child = descendants[0]
    program = child.get("/FontDescriptor", {}).get("/FontFile2")
    _need(isinstance(program, pikepdf.Stream), "The OCR font is not embedded")
    raw = program.read_bytes()
    _need(0 < len(raw) <= 16 * 1024**2, "The embedded OCR font exceeds its supported bounds")
    try:
        mapping = _unicode_cmap(font)
    except (ValueError, KeyError, TypeError) as error:
        raise OCRCorrectionError("The OCR font Unicode map is unsupported: " + str(error)) from error
    inverse = {}
    for code, text in mapping.items():
        if len(text) == 1 and 0 < ord(text) <= 0xffff:
            inverse.setdefault(text, []).append(code)
    inverse = {text: values[0] for text, values in inverse.items() if len(values) == 1}
    widths = {}
    entries = child.get("/W", [])
    _need(len(entries) <= 200_000, "OCR font width table exceeds its supported bounds")
    i = 0
    while i < len(entries):
        first = entries[i]; i += 1
        _need(type(first) is int and 0 <= first <= 65535 and i < len(entries), "Invalid OCR font width table")
        value = entries[i]; i += 1
        if isinstance(value, pikepdf.Array):
            _need(first + len(value) <= 65536, "OCR font width range is too large")
            for offset, width in enumerate(value):
                code = first + offset
                _need(code not in widths, "Ambiguous OCR font width")
                widths[code] = _number(width)
        else:
            _need(type(value) is int and first <= value <= 65535 and i < len(entries), "Invalid OCR font width range")
            width = _number(entries[i]); i += 1
            for code in range(first, value + 1):
                _need(code not in widths, "Ambiguous OCR font width")
                widths[code] = width
    default = _number(child.get("/DW", 1000))
    _need(default > 0 and all(width >= 0 for width in widths.values()), "Invalid OCR glyph advance")
    # Existing subset codes must select a real embedded glyph, not .notdef.
    from fontTools.ttLib import TTFont
    try:
        with TTFont(io.BytesIO(raw)) as actual:
            glyph_count = len(actual.getGlyphOrder())
    except Exception as error:
        raise OCRCorrectionError("The embedded OCR font cannot be verified") from error
    gids = child.get("/CIDToGIDMap", pikepdf.Name.Identity)
    if isinstance(gids, pikepdf.Stream):
        gid_bytes = gids.read_bytes()
        _need(len(gid_bytes) <= 131072 and len(gid_bytes) % 2 == 0, "Unsupported OCR glyph mapping")
        gid = lambda code: int.from_bytes(gid_bytes[code * 2:code * 2 + 2], "big") if code * 2 + 2 <= len(gid_bytes) else 0
    else:
        _need(gids == pikepdf.Name.Identity, "Unsupported inherited OCR glyph mapping")
        gid = lambda code: code
    inverse = {text: code for text, code in inverse.items()
               if 0 < gid(int.from_bytes(code, "big")) < glyph_count
               and widths.get(int.from_bytes(code, "big"), default) > 0}
    identity = {"font_program_sha256": hashlib.sha256(raw).hexdigest(),
                "unicode_sha256": hashlib.sha256(font["/ToUnicode"].read_bytes()).hexdigest(),
                "mapping": {key.hex(): value for key, value in mapping.items()},
                "widths": widths, "default_width": default,
                "glyph_map_sha256": hashlib.sha256(gid_bytes).hexdigest() if isinstance(gids, pikepdf.Stream) else "Identity"}
    descriptor = child.get("/FontDescriptor",{})
    def metric(value):
        if isinstance(value,pikepdf.Array): return [metric(v) for v in value]
        if isinstance(value,(int,float,Decimal)) and not isinstance(value,bool): return _number(value)
        return None if value is None else str(value)
    policy = {"names":[str(font.get("/BaseFont","")),str(child.get("/BaseFont","")),str(descriptor.get("/FontName",""))],
              "descriptor":{name:metric(descriptor.get(name)) for name in ("/FontBBox","/Flags","/ItalicAngle","/Ascent","/Descent","/CapHeight","/StemV")},
              "cid_system":{name:metric(child.get("/CIDSystemInfo",{}).get(name)) for name in ("/Registry","/Ordering","/Supplement")}}
    return {"mapping":mapping,"inverse":inverse,"widths":widths,"default":default,"sha256":_digest(identity),"private_policy_sha256":_digest(policy)}


def _decode(raw, font):
    _need(len(raw) % 2 == 0 and len(raw) <= 4096, "Unsupported OCR text code length")
    codes = [raw[i:i + 2] for i in range(0, len(raw), 2)]
    _need(all(code in font["mapping"] for code in codes), "Unmapped OCR text code")
    result = "".join(font["mapping"][code] for code in codes)
    _need(all(len(font["mapping"][code]) == 1 and 0 < ord(font["mapping"][code]) <= 0xffff for code in codes),
          "Multi-character or non-BMP OCR codes are unsupported")
    return result


def _advance(raw, font):
    result = sum(font["widths"].get(int.from_bytes(raw[i:i + 2], "big"), font["default"])
                 for i in range(0, len(raw), 2))
    _need(math.isfinite(result) and result > 0, "The OCR word has no proven positive advance")
    return result


def _page_text(path, pages=None, boxes=False, cancel=None):
    output = {}
    with pdfium.PdfDocument(path) as pdf:
        for index in range(len(pdf)):
            if pages is not None and index + 1 not in pages:
                continue
            _cancel(cancel)
            page = pdf[index]
            try:
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range()
                    positions = []
                    if boxes:
                        _need(textpage.count_chars() == len(text), "Independent OCR text indexing is ambiguous")
                        for n, character in enumerate(text):
                            _need(pdfium.raw.FPDFText_GetUnicode(textpage.raw, n) == ord(character),
                                  "Independent OCR Unicode indexing is ambiguous")
                            positions.append(list(textpage.get_charbox(n)))
                    output[index + 1] = {"text": text, "boxes": positions}
                finally:
                    textpage.close()
            finally:
                page.close()
    return output


def _page_objects(path, pages=None, cancel=None):
    """Independent PDFium occurrence text, geometry and raw character ownership."""
    output = {}
    with pdfium.PdfDocument(path) as pdf:
        for page_number in range(1, len(pdf) + 1) if pages is None else pages:
            _cancel(cancel)
            page = pdf[page_number - 1]
            try:
                textpage = page.get_textpage()
                try:
                    objects = list(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_TEXT], max_depth=MAX_DEPTH + 1, textpage=textpage))
                    _need(len(objects) <= MAX_ITEMS, "Independent OCR object count exceeds its supported bounds")
                    pointers = {ctypes.cast(obj.raw, ctypes.c_void_p).value: index for index, obj in enumerate(objects)}
                    rows = []
                    for obj in objects:
                        matrix = obj.get_matrix()
                        rows.append({"text": obj.extract(), "bounds": list(obj.get_bounds()),
                                     "matrix": [getattr(matrix, name) for name in ("a", "b", "c", "d", "e", "f")]})
                    characters = []; character_boxes = []; glyph_boxes = {index: [] for index in range(len(objects))}
                    for index in range(textpage.count_chars()):
                        owner = pdfium.raw.FPDFText_GetTextObject(textpage.raw, index)
                        pointer = ctypes.cast(owner, ctypes.c_void_p).value if owner else None
                        _need(pointer is None or pointer in pointers, "Independent OCR text has an unresolved object owner")
                        owner_index = pointers.get(pointer); codepoint = pdfium.raw.FPDFText_GetUnicode(textpage.raw, index)
                        characters.append([owner_index, codepoint])
                        bounds = list(textpage.get_charbox(index)); character_boxes.append(bounds)
                        if owner_index is not None and codepoint and not chr(codepoint).isspace():
                            glyph_boxes[owner_index].append(bounds)
                    output[page_number] = {"objects": rows, "characters": characters, "character_boxes": character_boxes,
                                           "glyph_boxes": glyph_boxes, "page_box": list(page.get_bbox()), "text": textpage.get_text_range(),
                                           "rotation":page.get_rotation()}
                finally:
                    textpage.close()
            finally:
                page.close()
    return output


def _scan(path, selected, cancel=None, *, expanded=False):
    """Read supported leaf Form occurrences; never edit globally shared resources."""
    units, errors, forms, font_cache = [], {}, Counter(), {}
    with pikepdf.open(path) as pdf:
        _need(len(pdf.pages) <= 1000 and not pdf.is_encrypted, "Encrypted or oversized OCR documents are unsupported")
        _need(not pdf.Root.get("/OCProperties") and not pdf.Root.get("/AcroForm", {}).get("/SigFlags"),
              "Optional content or signed OCR documents are unsupported")
        external_forms = set()
        def external(value, active=None, depth=0):
            active = set() if active is None else active
            _need(depth <= MAX_DEPTH, "Appearance or soft-mask nesting exceeds supported bounds")
            if not isinstance(value, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)):
                return
            key = tuple(value.objgen)
            if key[0] and key in active:
                return
            if isinstance(value, pikepdf.Stream) and value.get("/Subtype") == pikepdf.Name.Form:
                external_forms.add(key)
            children = list(value) if isinstance(value, pikepdf.Array) else list(value.values())
            for child in children:
                if isinstance(child, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)):
                    external(child, active | {key} if key[0] else active, depth + 1)
        metadata_seen = set(); metadata_nodes = 0
        def inspect_references(value, depth=0):
            nonlocal metadata_nodes
            if not isinstance(value, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)):
                return
            key = tuple(value.objgen)
            if key[0] and key in metadata_seen:
                return
            metadata_nodes += 1
            _need(depth <= 64 and metadata_nodes <= MAX_ITEMS, "OCR resource graph exceeds its supported bounds")
            if key[0]: metadata_seen.add(key)
            if isinstance(value, pikepdf.Array):
                children = list(value)
            else:
                _need("/ActualText" not in value, "Existing document or structure ActualText overrides are unsupported")
                for name in ("/AP", "/G"):
                    if name in value: external(value[name])
                children = list(value.values())
            for child in children: inspect_references(child, depth + 1)
        inspect_references(pdf.Root)
        visits = 0

        def count(target, resources, active, depth):
            nonlocal visits
            _cancel(cancel)
            _need(depth <= MAX_DEPTH, "OCR Form nesting is too deep")
            for instruction in pikepdf.parse_content_stream(target):
                if str(instruction.operator) != "Do":
                    continue
                child = resources.get("/XObject", {}).get(str(instruction.operands[0]))
                if not isinstance(child, pikepdf.Stream) or child.get("/Subtype") != pikepdf.Name.Form:
                    continue
                key = tuple(child.objgen)
                _need(key not in active and visits < MAX_ITEMS, "Recursive or excessive OCR Form invocations")
                visits += 1
                forms[key] += 1
                count(child, child.get("/Resources", resources), active | {key}, depth + 1)
        for page in pdf.pages:
            count(page, page.Resources, set(), 0)

        def walk(target, resources, page, path_parts, inherited, active, depth):
            _cancel(cancel)
            _need(depth <= MAX_DEPTH, "OCR Form nesting is too deep")
            raw = target.read_bytes() if isinstance(target, pikepdf.Stream) else b""
            _need(len(raw) <= MAX_STREAM, "OCR content stream exceeds its supported bounds")
            instructions = list(pikepdf.parse_content_stream(target))
            _need(len(instructions) <= 500_000, "OCR content stream has too many operators")
            contains_form = any(str(ins.operator) == "Do" and isinstance(resources.get("/XObject", {}).get(str(ins.operands[0])), pikepdf.Stream)
                                and resources["/XObject"][str(ins.operands[0])].get("/Subtype") == pikepdf.Name.Form for ins in instructions)
            state = dict(inherited); stack = []; marks = []; in_text = False; show = 0
            tm = tlm = (1.,0.,0.,1.,0.,0.)
            for index, instruction in enumerate(instructions):
                operands, operator = instruction.operands, str(instruction.operator)
                if operator == "q":
                    stack.append(dict(state))
                elif operator == "Q":
                    _need(stack, "Unbalanced OCR graphics state")
                    state = stack.pop()
                elif operator == "BT":
                    _need(not in_text, "Nested OCR text objects are unsupported")
                    in_text = True
                    tm = tlm = (1.,0.,0.,1.,0.,0.)
                elif operator == "ET":
                    _need(in_text, "Unbalanced OCR text object")
                    in_text = False
                elif operator == "Tf":
                    _need(len(operands) == 2, "Invalid OCR text font")
                    state["font"] = resources.get("/Font", {}).get(str(operands[0]))
                    state["font_name"] = str(operands[0]); state["size"] = _number(operands[1])
                elif operator == "cm":
                    _need(len(operands) == 6, "Invalid OCR coordinate transform")
                    state["ctm"] = _matrix(state["ctm"], tuple(_number(v) for v in operands))
                elif operator == "Tm":
                    _need(in_text and len(operands) == 6, "Invalid OCR text matrix")
                    tm = tlm = tuple(_number(v) for v in operands)
                elif operator in ("Td", "TD"):
                    _need(in_text and len(operands) == 2, "Invalid OCR text displacement")
                    x,y = (_number(v) for v in operands)
                    if operator == "TD": state["leading"] = -y
                    tm = tlm = _matrix(tlm,(1.,0.,0.,1.,x,y))
                elif operator == "T*":
                    tm = tlm = _matrix(tlm,(1.,0.,0.,1.,0.,-state.get("leading",0)))
                elif operator in ("Ts", "TL"):
                    _need(len(operands) == 1, "Invalid OCR text vertical state")
                    state["rise" if operator == "Ts" else "leading"] = _number(operands[0])
                elif operator in ("Tr", "Tz", "Tc", "Tw"):
                    _need(len(operands) == 1, "Invalid OCR text state")
                    key = {"Tr": "render", "Tz": "scale", "Tc": "char_space", "Tw": "word_space"}[operator]
                    state[key] = _number(operands[0])
                    if operator == "Tr" and state[key] >= 4:
                        state["clipping"] = True
                elif operator in ("W", "W*"):
                    state["clipping"] = True
                elif operator in ("BDC", "BMC"):
                    props = operands[1] if len(operands) == 2 else None
                    if isinstance(props, pikepdf.Name):
                        props = resources.get("/Properties", {}).get(str(props))
                        _need(props is not None, "Unresolved OCR marked-content properties")
                    _need(not (isinstance(props, pikepdf.Dictionary) and "/ActualText" in props),
                          "Existing ActualText overrides are unsupported")
                    marks.append(int(props["/MCID"]) if isinstance(props, pikepdf.Dictionary) and "/MCID" in props else None)
                elif operator == "EMC":
                    _need(marks, "Unbalanced OCR marked content")
                    marks.pop()
                elif operator == "Do":
                    child = resources.get("/XObject", {}).get(str(operands[0]))
                    if isinstance(child, pikepdf.Stream) and child.get("/Subtype") == pikepdf.Name.Form:
                        key = tuple(child.objgen)
                        _need(key not in active, "Recursive OCR Form")
                        nested_state = dict(state)
                        nested_state["ctm"] = _matrix(state["ctm"],tuple(_number(v) for v in child.get("/Matrix",[1,0,0,1,0,0])))
                        _need(len(child.get("/BBox",[])) == 4,"OCR Form has no supported clipping bounds")
                        nested_state["form_clips"] = state.get("form_clips",[])+[{"matrix":list(nested_state["ctm"]),"bbox":[_number(v) for v in child.BBox]}]
                        walk(child, child.get("/Resources", resources), page,
                             path_parts + [{"name": str(operands[0]), "operator": index}], nested_state, active | {key}, depth + 1)
                elif operator in _TEXT:
                    if expanded and operator == "TJ" and len(operands) == 1 and isinstance(operands[0],pikepdf.Array) and all(isinstance(v,(int,float,Decimal)) and not isinstance(v,bool) for v in operands[0]):
                        _need(in_text, "An OCR numeric text adjustment is outside text")
                        offset = -sum(_number(v) for v in operands[0])*state["size"]*state["scale"]/100000
                        tm = _matrix(tm,(1.,0.,0.,1.,offset,0.))
                        continue
                    _need(operator == "Tj" and len(operands) == 1 and isinstance(operands[0], pikepdf.String),
                          "Only individual OCR Tj words are supported")
                    _need(in_text and path_parts and not contains_form and forms[tuple(target.objgen)] == 1 and tuple(target.objgen) not in external_forms,
                          "Only uniquely invoked leaf OCR Forms are editable")
                    _need(state.get("render") == 3 and not state.get("clipping") and state.get("size", 0) > 0
                          and state.get("scale", 0) > 0 and state.get("char_space", 0) == 0 and state.get("word_space", 0) == 0,
                          "Visible, clipped or specially spaced OCR text is unsupported")
                    font = state.get("font"); key = tuple(font.objgen) if isinstance(font, pikepdf.Dictionary) else None
                    _need(key is not None, "OCR text has no resolved font")
                    if key not in font_cache:
                        font_cache[key] = _font_info(font)
                    info = font_cache[key]; encoded = bytes(operands[0]); text = _decode(encoded, info)
                    body = text.rstrip(" "); trailing = text[len(body):]; leading = ""
                    if expanded:
                        leading = body[:len(body)-len(body.lstrip(" "))]; body = body.lstrip(" ")
                    editable = bool(body) and not any(character.isspace() for character in body) and len(body) <= MAX_CHARACTERS and all(unicodedata.category(c)[0] != "C" for c in body)
                    _advance(encoded, info)
                    location = {"page": page, "form_path": path_parts, "show": show}
                    anchor = {**location, "operator": index, "stream_sha256": hashlib.sha256(raw).hexdigest(),
                              "encoded_hex": encoded.hex(), "trailing": trailing, "font_sha256": info["sha256"],
                              "font_name": state["font_name"], "font_size": state["size"], "scale": state["scale"],
                              "mcids": list(marks)}
                    if expanded and leading: anchor["leading"] = leading
                    ident = "ocr:" + _digest(location)[:24]
                    supported = "".join(sorted(c for c in info["inverse"] if not c.isspace() and unicodedata.category(c)[0] != "C"))
                    units.append({"id": ident, "page": page, "current": body, "original": body,
                                  "editable": editable, "eligible": editable,
                                  "limitations": [] if editable else ["This text object is not one supported printable OCR word."], "max_characters": MAX_CHARACTERS,
                                   "supported_characters": supported, "anchor": anchor, "font": info,
                                   "geometry": {"ctm":list(state["ctm"]),"tm":list(tm),"tlm":list(tlm),"form_clips":state.get("form_clips",[])}})
                    advance = _advance(encoded, info)*state["size"]*state["scale"]/100000
                    tm = _matrix(tm,(1.,0.,0.,1.,advance,0.))
                    _need(len(units) <= MAX_ITEMS, "OCR word inventory exceeds its supported bounds")
                    show += 1
            _need(not stack and not marks and not in_text, "Unbalanced OCR content state")

        state = {"render": 0, "scale": 100, "size": 0, "char_space": 0, "word_space": 0, "clipping": False,
                 "ctm":(1.,0.,0.,1.,0.,0.),"rise":0,"leading":0,"form_clips":[]}
        for page_number in selected:
            before = len(units)
            try:
                walk(pdf.pages[page_number - 1], pdf.pages[page_number - 1].Resources, page_number, [], state, set(), 0)
                _need(len(units) > before, "This page has no supported OCR words")
            except (OCRCorrectionError, ValueError, TypeError, KeyError, pikepdf.PdfError) as error:
                del units[before:]
                errors[page_number] = str(error)
    return units, errors


def _inventory(bundle_path, cancel=None, seen=(), profile="legacy"):
    from .pipeline import verify_bundle
    bundle = Path(bundle_path).resolve(); _cancel(cancel)
    _need(len(seen) <= MAX_ANCESTRY * 2 and str(bundle) not in seen, "OCR correction ancestry is cyclic or too deep")
    _need(verify_bundle(bundle), "The OCR review bundle is incomplete or changed")
    report = _read(bundle / "report.json")
    def pdf_binding(value):
        return {key: value[key] for key in ("path", "sha256") if key in value} if isinstance(value, dict) else None
    source = pdf_binding(report.get("input")); artifact = pdf_binding(report.get("output")); prepared = pdf_binding(report.get("decision_source"))
    _checked(source)
    base = {"schema_version": INVENTORY_SCHEMA, "source_sha256": source["sha256"],
            "document_sha256": artifact.get("sha256") if isinstance(artifact, dict) else None,
            "source": source, "artifact": artifact, "prepared": prepared, "items": [], "ocr_pages": [],
            "eligible": False, "reason": "No completed local OCR output is available for correction.", "limitations": list(_LIMITS)}
    if report.get("mode") != "fix" or not artifact or not prepared:
        base["inventory_sha256"] = _digest(base)
        return _expanded_inventory(base,[],{},cancel) if profile == "expanded-v2" else base
    _need(report.get("status") in ("candidate", "needs-manual", "verified")
          and report.get("fidelity", {}).get("status") == "pass", "The prior OCR result lacks a passing preservation assessment")
    _checked(artifact); _checked(prepared)
    prior = report.get("source_lineage")
    if prior:
        _need(isinstance(prior, dict) and set(prior) == {"path", "sha256"}, "Invalid source OCR lineage binding")
        lineage = _validate_lineage(prior["path"], source["path"], prior["sha256"], cancel, seen + (str(bundle),))
        original, pages = lineage["original"], lineage["ocr_pages"]
    else:
        processor = next((p for p in report.get("processors", []) if p.get("name") == "ocr"), None)
        if (not processor or processor.get("status") != "completed" or processor.get("preservation", {}).get("status") != "pass"
                or report.get("settings", {}).get("ocr_mode") not in ("skip", "textless")):
            base["inventory_sha256"] = _digest(base)
            return _expanded_inventory(base,[],{},cancel) if profile == "expanded-v2" else base
        original, pages = source, report.get("ocr_pages")
    original_path = _checked(original)
    original_inspection = inspect_pdf(original_path, cancel=cancel)
    _need(not original_inspection.get("error"), "The unchanged original cannot be independently inspected")
    _need(isinstance(pages, list) and pages and len(pages) == len(set(pages))
          and all(type(page) is int and 1 <= page <= original_inspection["page_count"] for page in pages), "Invalid original OCR page scope")
    for page in pages:
        source_page = original_inspection["pages"][page - 1]
        _need(source_page["text_characters"] == 0 and source_page["content"]["counts"].get("text_paints", 0) == 0
              and source_page["content"].get("image_objects", 0) > 0, "Original text-bearing or ambiguous pages cannot be edited as added OCR")
    try:
        units, failures = _scan(artifact["path"],pages,cancel,expanded=profile == "expanded-v2")
    except OCRCorrectionError as error:
        units, failures = [], {page: str(error) for page in pages}
    objects = _page_objects(artifact["path"], pages, cancel)
    for page in pages:
        page_units = [item for item in units if item["page"] == page]
        if page not in failures:
            actual = objects[page]["objects"]
            if len(page_units) != len(actual):
                failures[page] = "Independent text objects do not match unambiguous OCR occurrences"
                continue
            for object_index, (item, record) in enumerate(zip(page_units, actual)):
                leading = item["anchor"].get("leading","")
                matches = record["text"] in (item["current"],item["current"]+item["anchor"]["trailing"],leading+item["current"],leading+item["current"]+item["anchor"]["trailing"])
                if profile == "expanded-v2":
                    owned = "".join(chr(code) for owner,code in objects[page]["characters"] if owner == object_index)
                    matches = record["text"].strip(" ") == item["current"] and owned.strip(" ") == item["current"]
                if not matches:
                    item["editable"] = item["eligible"] = False
                    item["limitations"].append("Independent extraction transforms this occurrence; it is read-only in this editor.")
                box = objects[page]["page_box"]
                for bounds in objects[page]["glyph_boxes"][object_index]:
                    if not all(math.isfinite(value) for value in bounds) or bounds[0] < box[0] - .001 or bounds[1] < box[1] - .001 or bounds[2] > box[2] + .001 or bounds[3] > box[3] + .001:
                        item["editable"] = item["eligible"] = False
                        item["limitations"].append("This OCR occurrence is clipped by the page bounds; it is read-only.")
                        break
            for index, item in enumerate(page_units):
                item["occurrence"] = index + 1
                item["context_text"] = " ".join(row["current"] for row in page_units[max(0, index - 2):index + 3])
                item["context_text_source"] = "Neighboring OCR-layer words; meaningful reading order remains unapproved."
    unsupported_occurrences = [{"id": item["id"], "page": item["page"], "occurrence": item.get("occurrence"),
                                "limitations": list(item["limitations"])} for item in units if item["page"] not in failures and not item["editable"]]
    units = [item for item in units if item["page"] not in failures and item["editable"]]
    base.update(true_original=original, ocr_pages=pages, eligible=bool(units), reason="" if units else "No safely editable OCR occurrences were found.",
                settings_sha256=_digest(report.get("settings", {})), unsupported_pages=[{"page": p, "reason": reason} for p, reason in sorted(failures.items())],
                bundle={"path": str(bundle), "manifest_sha256": _sha(bundle / "manifest.json"), "report_sha256": _sha(bundle / "report.json")},
                source_lineage=copy.deepcopy(prior), unsupported_occurrences=unsupported_occurrences)
    context = {key: base.get(key) for key in ("source_sha256", "document_sha256", "prepared", "settings_sha256", "true_original", "ocr_pages")}
    for item in units:
        public = {key: value for key, value in item.items() if key not in ("font","geometry")}
        public["context_sha256"] = _digest({"binding": context, "occurrence": public})
        base["items"].append(public)
    base["inventory_sha256"] = _digest(base)
    if profile == "expanded-v2":
        return _expanded_inventory(base, units, objects, cancel)
    return base


def get_inventory(bundle_path, cancel=None, *, profile="legacy"):
    """Read only; old saved reviews are not migrated or rewritten."""
    _need(profile in ("legacy","expanded-v2"), "Unknown OCR editor inventory profile")
    return _inventory(bundle_path, cancel, profile=profile)


def _leaf(pdf, unit):
    target = pdf.pages[unit["page"]-1]; resources = target.Resources
    for part in unit["anchor"]["form_path"]:
        target = resources["/XObject"][part["name"]]; resources = target.get("/Resources",resources)
    return target, resources


def _owners(path, units):
    """Insertion inherits exactly one existing, independently linked MCID owner."""
    result = {}
    from .preservation import _structure_refs, PreservationRefusal
    with pikepdf.open(path) as pdf:
        try: refs, parents, _ = _structure_refs(pdf)
        except (PreservationRefusal,KeyError,TypeError,ValueError): return result
        for unit in units:
            marks = [v for v in unit["anchor"]["mcids"] if v is not None]
            if len(marks) != 1: continue
            target,_ = _leaf(pdf,unit); mcid = marks[0]; owner = refs.get((tuple(target.objgen),mcid))
            slots = parents.get(int(target.get("/StructParents",-1)))
            if (isinstance(owner,pikepdf.Dictionary) and isinstance(slots,pikepdf.Array) and 0 <= mcid < len(slots)
                and isinstance(slots[mcid],pikepdf.Dictionary) and tuple(slots[mcid].objgen) == tuple(owner.objgen)):
                result[unit["id"]] = {"role":str(owner.get("/S","")),"mcid":mcid}
    return result


def _display_frame(page_box, rotation):
    l,b,r,t = page_box; width,height = r-l,t-b
    _need(width > 0 and height > 0 and rotation in (0,90,180,270),"Invalid OCR preview page geometry")
    frame = {0:(1,0,0,1,l,b),90:(0,1,-1,0,r,b),180:(-1,0,0,-1,r,t),270:(0,-1,1,0,l,t)}[rotation]
    return frame, (width,height) if rotation in (0,180) else (height,width)


def _normalized_box(bounds, page_box, rotation=0):
    frame,(width,height) = _display_frame(page_box,rotation)
    inverse = _inverse(frame); x,y,z,w = bounds
    points = [_point(inverse,a,b) for a,b in ((x,y),(z,y),(z,w),(x,w))]
    left,bottom,right,top = min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)
    return [left/width,(height-top)/height,(right-left)/width,(top-bottom)/height]


def _expanded_inventory(base, units, objects, cancel=None):
    qualified = _qualified_font(); output = copy.deepcopy(base)
    output["schema_version"] = EXPANDED_INVENTORY_SCHEMA
    output["font_policy"] = {"id":FONT_POLICY,"sha256":FONT_SHA256,"characters":qualified["characters"]}
    output["limitations"] = ["One word per replacement or explicit insertion rectangle; complex scripts, combining marks and unsupported characters are refused.",
        "Each inserted word inherits its selected occurrence's existing structure owner. Its accuracy and meaningful reading order still require review.",
        "Insertion rectangles must fit the displayed preview page and avoid existing OCR text; one insertion per anchor, with no simultaneous replacement of that anchor."]
    owners = _owners(base["artifact"]["path"],units) if units else {}; by_id = {unit["id"]:unit for unit in units}; geometry = {}
    for page, record in objects.items():
        occupied = []
        for bounds in record["glyph_boxes"].values():
            if bounds:
                union = [min(v[0] for v in bounds),min(v[1] for v in bounds),max(v[2] for v in bounds),max(v[3] for v in bounds)]
                occupied.append(_normalized_box(union,record["page_box"],record["rotation"]))
        geometry[str(page)] = {"page_box":record["page_box"],"rotation":record["rotation"],"occupied_rects":occupied}
    output["page_geometry"] = geometry
    for item in output["items"]:
        _cancel(cancel); unit = by_id[item["id"]]; record = objects[item["page"]]
        item.pop("supported_characters",None)
        item["font_policy"] = FONT_POLICY
        item["font_sha256"] = FONT_SHA256
        item["page_geometry"] = {key:geometry[str(item["page"])][key] for key in ("page_box","rotation")}
        index = item["occurrence"]-1
        bounds = record["glyph_boxes"][index]
        item["bbox"] = _normalized_box([min(v[0] for v in bounds),min(v[1] for v in bounds),max(v[2] for v in bounds),max(v[3] for v in bounds)],record["page_box"],record["rotation"]) if bounds else None
        reason = ""
        try:
            _inverse(unit["geometry"]["ctm"])
            relative = _matrix(_inverse(unit["geometry"]["tlm"]),unit["geometry"]["tm"])
            _need(all(abs(relative[n]-v) <= 1e-6 for n,v in ((0,1),(1,0),(2,0),(3,1),(5,0))),"The anchor text matrix cannot be restored exactly")
            _display_frame(record["page_box"],record["rotation"])
            _need(item["id"] in owners,"Insertion requires an existing uniquely resolved marked-content structure owner")
        except OCRCorrectionError as error: reason = str(error)
        item["insertion_eligible"] = not reason; item["insertion_reason"] = reason
        item["structure_owner"] = owners.get(item["id"])
        item["geometry"] = unit["geometry"]
        item["context_sha256"] = _digest({"prior_context":item["context_sha256"],"font":{key:output["font_policy"][key] for key in ("id","sha256")},
                                          "item":{k:v for k,v in item.items() if k != "context_sha256"}})
    output["expansion_sha256"] = _digest({"font":output["font_policy"],"geometry":geometry,"contexts":[i["context_sha256"] for i in output["items"]]})
    output.pop("inventory_sha256",None); output["inventory_sha256"] = _digest(output)
    return output


def validate_insertion(anchor, value, placement):
    _need(isinstance(anchor,dict) and anchor.get("insertion_eligible") is True,
          "This OCR anchor cannot safely own an omitted-word insertion")
    validate_replacement(anchor,value)
    _need(isinstance(placement,dict) and set(placement) == {"rect","order"} and placement["order"] in ("before","after"),"Choose before or after the OCR anchor")
    rect = placement["rect"]
    _need(isinstance(rect,list) and len(rect) == 4 and all(type(v) in (int,float) and math.isfinite(v) for v in rect),"Enter a finite left, top, width and height rectangle")
    l,t,w,h = (float(v) for v in rect)
    _need(0 <= l < 1 and 0 <= t < 1 and 0 < w <= 1 and 0 < h <= 1 and l+w <= 1 and t+h <= 1,
          "The omitted-word rectangle must fit wholly inside the preview page")
    frame,(width,height) = _display_frame(anchor["page_geometry"]["page_box"],anchor["page_geometry"]["rotation"])
    points = [_point(frame,x*width,(1-y)*height) for x,y in ((l,t),(l+w,t),(l+w,t+h),(l,t+h))]
    _check_form_clips(points,anchor["geometry"])
    return {"rect":[l,t,w,h],"order":placement["order"]}


def _check_form_clips(points, geometry):
    for clip in geometry.get("form_clips",[]):
        inverse = _inverse(clip["matrix"]); l,b,r,t = clip["bbox"]
        local = [_point(inverse,*point) for point in points]
        _need(all(l-1e-5 <= x <= r+1e-5 and b-1e-5 <= y <= t+1e-5 for x,y in local),"Corrected glyph placement would be clipped by an enclosing OCR Form")


def _overlap(left,right):
    return min(left[0]+left[2],right[0]+right[2])-max(left[0],right[0]) > 1e-9 and min(left[1]+left[3],right[1]+right[3])-max(left[1],right[1]) > 1e-9


def validate_operation(inventory, row):
    """Fresh draft/accepted operation check; approval fields are checked at Apply."""
    _need(isinstance(row,dict) and inventory.get("schema_version") == EXPANDED_INVENTORY_SCHEMA,"Unknown expanded OCR operation")
    items = {item["id"]:item for item in inventory["items"]}; kind = row.get("kind")
    ident = row.get("anchor_id") if kind == "insert" else row.get("id")
    _need(ident in items and kind in ("replace","insert"),"Unknown expanded OCR occurrence")
    item = items[ident]
    _need(row.get("context_sha256") == item["context_sha256"],"OCR occurrence context changed")
    if kind == "replace":
        _need(row.get("original") == item["current"],"OCR replacement original changed")
        validate_replacement(item,row.get("value"))
    else:
        _need(row.get("original") == "" and row.get("page") == item["page"] and isinstance(row.get("id"),str)
              and bool(re.fullmatch(r"ocr-insert-[a-f0-9]{32}",row["id"])),"Invalid insertion anchor, page or identifier")
        placement = validate_insertion(item,row.get("value"),row.get("placement"))
        _need(not any(_overlap(placement["rect"],rect) for rect in inventory["page_geometry"][str(item["page"])]["occupied_rects"]),
              "The omitted-word rectangle overlaps existing OCR text")


def validate_replacement(item, value):
    _need(isinstance(item, dict) and item.get("editable") is True, "This OCR occurrence is not editable")
    _need(isinstance(value, str) and 0 < len(value) <= MAX_CHARACTERS
          and not any(c.isspace() or unicodedata.category(c)[0] == "C" or ord(c) > 0xffff for c in value),
          "Enter one nonempty OCR word, at most 256 characters, without spaces or control characters")
    expanded = item.get("font_policy") == FONT_POLICY
    if expanded: _need(item.get("font_sha256") == FONT_SHA256,"The expanded correction font binding changed")
    supported = _qualified_font()["characters"] if expanded else item.get("supported_characters", "")
    _need(all(c in supported for c in value),
          ("The bundled correction font does not support this character or script without complex shaping" if item.get("font_policy") == FONT_POLICY else
           "This correction needs a character absent from the current embedded OCR font; it cannot be applied safely in this editor yet"))
    return value


def _plan(path, inventory, expected=None):
    path = Path(path).resolve()
    if expected is not None:
        _need(isinstance(expected, str) and bool(_SHA.fullmatch(expected)) and _sha(path) == expected, "The frozen OCR correction plan changed")
    _need(path.stat().st_size <= 32 * 1024**2, "OCR correction plan exceeds its supported bounds")
    data = _read(path)
    expanded = inventory.get("schema_version") == EXPANDED_INVENTORY_SCHEMA
    keys = {"schema_version", "source_sha256", "document_sha256", "inventory_sha256", "workspace_id", "revision", "corrections", "human_approved", "accessibility_approved"}
    if expanded: keys.add("expansion_sha256")
    _need(isinstance(data, dict) and set(data) == keys and data["schema_version"] == (EXPANDED_PLAN_SCHEMA if expanded else PLAN_SCHEMA)
          and data["human_approved"] is data["accessibility_approved"] is False
          and isinstance(data["workspace_id"], str) and data["workspace_id"] and type(data["revision"]) is int and data["revision"] >= 0,
          "Unknown or malformed explicit OCR correction plan")
    _need(inventory["eligible"] and all(data[key] == inventory[key] for key in ("source_sha256", "document_sha256", "inventory_sha256")),
          "OCR corrections are stale or belong to different source, result or occurrence bytes")
    if expanded: _need(data["expansion_sha256"] == inventory["expansion_sha256"],"The correction font or insertion geometry changed")
    rows = data["corrections"]; _need(isinstance(rows, list) and 0 < len(rows) <= MAX_ITEMS, "Accept at least one changed OCR word")
    fresh = {item["id"]: item for item in inventory["items"]}; ids = set(); inserts = {}; replacements = set()
    for row in rows:
        _need(isinstance(row,dict),"Invalid OCR correction occurrence")
        rowkeys = {"id", "context_sha256", "original", "value", "reviewer", "reviewed_at", "acceptance_sha256"}
        if expanded:
            rowkeys.add("kind")
            if row.get("kind") == "insert": rowkeys |= {"anchor_id","page","placement"}
        _need(isinstance(row, dict) and set(row) == rowkeys, "Invalid OCR correction occurrence")
        ident = row["id"]
        _need(isinstance(ident,str) and ident not in ids and (expanded or ident in fresh),"Unknown or duplicate OCR correction occurrence")
        ids.add(ident)
        if expanded:
            validate_operation(inventory,row)
            if row["kind"] == "insert":
                anchor = row["anchor_id"]
                _need(anchor not in inserts,"Only one insertion per anchor is supported")
                _need(not any(other["page"] == row["page"] and _overlap(other["placement"]["rect"],row["placement"]["rect"]) for other in inserts.values()),"Insertion rectangles overlap")
                inserts[anchor] = row
            else: replacements.add(ident)
        else:
            item = fresh[ident]
            _need(row["context_sha256"] == item["context_sha256"] and row["original"] == item["current"], "OCR occurrence context changed")
            validate_replacement(item,row["value"])
        _need(row["value"] != row["original"], "Only changed OCR words belong in a correction plan")
        _need(isinstance(row["reviewer"], str) and row["reviewer"].strip() and len(row["reviewer"]) <= 200, "An explicit correction reviewer is required")
        try:
            stamp = row["reviewed_at"]
            _need(isinstance(stamp, str), "An explicit correction date is required")
            date.fromisoformat(stamp) if len(stamp) == 10 else datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise OCRCorrectionError("Use an ISO correction date or timestamp") from error
        payload = ({key:value for key,value in row.items() if key != "acceptance_sha256"} if expanded else
                   {key:row[key] for key in ("id","context_sha256","original","value","reviewer","reviewed_at")})
        payload.update({key:data[key] for key in (("source_sha256","document_sha256","inventory_sha256","expansion_sha256") if expanded else ("source_sha256","document_sha256","inventory_sha256"))})
        _need(row["acceptance_sha256"] == _digest(payload), "OCR correction acceptance is stale after an edit")
    _need(not replacements.intersection(inserts),"Apply a replacement and insertion at different anchors in this version")
    return data


def _plan_profile(path):
    _need(Path(path).stat().st_size <= 32*1024**2,"OCR correction plan exceeds its supported bounds")
    header = _read(path)
    return "expanded-v2" if isinstance(header,dict) and header.get("schema_version") == EXPANDED_PLAN_SCHEMA else "legacy"


def _replace(pdf, units, edits):
    grouped = {}
    for item in units:
        if item["id"] in edits:
            grouped.setdefault((item["page"], json.dumps(item["anchor"]["form_path"], sort_keys=True)), []).append(item)
    records = []
    for (page_number, path_json), items in grouped.items():
        target = pdf.pages[page_number - 1]; resources = target.Resources
        for part in json.loads(path_json):
            target = resources["/XObject"][part["name"]]
            resources = target.get("/Resources", resources)
        instructions = list(pikepdf.parse_content_stream(target)); changes = {item["anchor"]["operator"]: item for item in items}; output = []
        for index, instruction in enumerate(instructions):
            if index not in changes:
                output.append(instruction); continue
            item = changes[index]; font = item["font"]; anchor = item["anchor"]; row = edits[item["id"]]
            encoded = b"".join(font["inverse"][c] for c in row["value"] + anchor["trailing"])
            old_width = _advance(bytes.fromhex(anchor["encoded_hex"]), font); new_width = _advance(encoded, font)
            scale = anchor["scale"] * old_width / new_width
            _need(math.isfinite(scale) and .001 <= scale <= 100000, "Corrected OCR text exceeds supported fitting bounds")
            scale_decimal = Decimal(format(scale, ".12f")); old_scale = Decimal(str(anchor["scale"]))
            output.extend([pikepdf.ContentStreamInstruction([scale_decimal], pikepdf.Operator("Tz")),
                           pikepdf.ContentStreamInstruction([pikepdf.String(encoded)], pikepdf.Operator("Tj")),
                           pikepdf.ContentStreamInstruction([old_scale], pikepdf.Operator("Tz"))])
            records.append({"id": item["id"], "page": item["page"], "original": item["current"], "value": row["value"],
                            "old_advance_units": old_width * anchor["scale"] / 100,
                            "new_advance_units": new_width * float(scale_decimal) / 100,
                            "font_sha256": font["sha256"], "trailing_separator_preserved": True})
        target.write(pikepdf.unparse_content_stream(output))
    return sorted(records, key=lambda row: row["id"])


def _instruction(operator, values=()):
    return pikepdf.ContentStreamInstruction([Decimal(format(v,".12f")) if isinstance(v,float) else v for v in values],pikepdf.Operator(operator))


def _restore_text(unit, after=False):
    geometry = unit["geometry"]; tm = geometry["tm"]; anchor = unit["anchor"]
    if after:
        shift = _advance(bytes.fromhex(anchor["encoded_hex"]),unit["font"])*anchor["font_size"]*anchor["scale"]/100000
        tm = _matrix(tm,(1,0,0,1,shift,0))
    relative = _matrix(_inverse(geometry["tlm"]),tm)
    _need(all(abs(relative[n]-v) <= 1e-6 for n,v in ((0,1),(1,0),(2,0),(3,1),(5,0))),"The original text-line matrix cannot be restored")
    adjustment = -relative[4]*100000/(anchor["font_size"]*anchor["scale"])
    result = [_instruction("BT"),_instruction("Tm",geometry["tlm"])]
    if abs(adjustment) > 1e-10: result.append(_instruction("TJ",[pikepdf.Array([Decimal(format(adjustment,".12f"))])]))
    return result


def _ink_bounds(value, qualified):
    offset = 0.; ink = []
    for char in value:
        bounds = qualified["metrics"][char]
        if not char.isspace() and bounds[2] > bounds[0] and bounds[3] > bounds[1]:
            ink.append([offset+bounds[0],bounds[1],offset+bounds[2],bounds[3]])
        offset += qualified["widths"][ord(char)]
    _need(ink,"The correction font cannot supply nonempty glyph ink")
    return (min(v[0] for v in ink),min(v[1] for v in ink),max(v[2] for v in ink),max(v[3] for v in ink))


def _insertion_text(row, unit):
    # Both encoded boundaries belong to the new occurrence. Old separators,
    # including an absent old separator, are never changed or inferred.
    return " "+row["value"]+" "


def _independent_ink_bounds(text, qualified):
    """Measure the actual embedded glyphs at the exact writer size, in memory.

    PDFium's glyph bounds differ slightly from raw glyf bounds. Measuring the
    unchanged private font first fits its actual extraction boxes inside the
    user's rectangle without relaxing the later independent containment gate.
    """
    _ink_bounds(text,qualified)
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(1000,1000)); page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F=_private_font(pdf,qualified)))
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream([_instruction("BT"),_instruction("Tf",[pikepdf.Name.F,1]),
            _instruction("Tr",[3]),_instruction("Td",[100,100]),_instruction("Tj",[pikepdf.String(text.encode("utf-16-be"))]),_instruction("ET")]))
        buffer = io.BytesIO(); pdf.save(buffer,deterministic_id=True)
    record = _page_objects(buffer.getvalue())[1]
    _need(len(record["objects"]) == 1 and record["objects"][0]["text"].strip(" ") == text.strip(" "),"The private font's independent placement measurement is ambiguous")
    bounds = record["glyph_boxes"][0]; _need(bounds,"The private font has no independently measurable glyph ink")
    return ((min(v[0] for v in bounds)-100)*1000,(min(v[1] for v in bounds)-100)*1000,
            (max(v[2] for v in bounds)-100)*1000,(max(v[3] for v in bounds)-100)*1000)


def _insert_word(unit, row, name, qualified, page_geometry):
    text = _insertion_text(row,unit); x0,y0,x1,y1 = _independent_ink_bounds(text,qualified)
    frame,(width,height) = _display_frame(page_geometry["page_box"],page_geometry["rotation"])
    l,t,w,h = row["placement"]["rect"]; left,bottom,rectwidth,rectheight = l*width,(1-t-h)*height,w*width,h*height
    sx,sy = rectwidth*1000/(x1-x0),rectheight*1000/(y1-y0)
    displayed = (sx,0.,0.,sy,left-x0*sx/1000,bottom-y0*sy/1000)
    local = _matrix(_inverse(unit["geometry"]["ctm"]),_matrix(frame,displayed))
    _need(all(math.isfinite(v) and abs(v) <= 10**8 for v in local),"Insertion placement exceeds supported coordinate bounds")
    return ([_instruction("ET"),_instruction("q"),_instruction("BT"),_instruction("Tf",[pikepdf.Name(name),1]),
        _instruction("Tr",[3]),_instruction("Tz",[100]),_instruction("Tc",[0]),_instruction("Tw",[0]),_instruction("Ts",[0]),
        _instruction("Tm",list(local)),_instruction("Tj",[pikepdf.String(text.encode("utf-16-be"))]),_instruction("ET"),_instruction("Q")]
        +_restore_text(unit,row["placement"]["order"] == "after"))


def _write_expanded(pdf, units, rows, inventory, qualified, cancel=None):
    grouped = {}; by_id = {unit["id"]:unit for unit in units}; records = []
    for row in rows:
        _cancel(cancel)
        ident = row["anchor_id"] if row["kind"] == "insert" else row["id"]; unit = by_id[ident]
        key = (unit["page"],json.dumps(unit["anchor"]["form_path"],sort_keys=True))
        grouped.setdefault(key,[]).append((unit,row))
    for entries in grouped.values():
        _cancel(cancel)
        target,resources = _leaf(pdf,entries[0][0]); localresources = pikepdf.Dictionary(resources)
        fonts = pikepdf.Dictionary(resources.get("/Font",{})); localresources.Font = fonts; target.Resources = localresources
        name = "/OCRCopy0"; serial = 0
        while name in fonts: serial += 1; name = "/OCRCopy"+str(serial)
        fonts[name] = _private_font(pdf,qualified); private = _font_info(fonts[name])
        changes = {unit["anchor"]["operator"]:(unit,row) for unit,row in entries}; instructions = []
        for index,instruction in enumerate(pikepdf.parse_content_stream(target)):
            if index % 1000 == 0: _cancel(cancel)
            if index not in changes: instructions.append(instruction); continue
            unit,row = changes[index]; anchor = unit["anchor"]
            if row["kind"] == "insert":
                added = _insert_word(unit,row,name,qualified,inventory["page_geometry"][str(unit["page"])])
                instructions.extend(([instruction]+added) if row["placement"]["order"] == "after" else (added+[instruction]))
                records.append({"id":row["id"],"kind":"insert","anchor_id":unit["id"],"page":unit["page"],"value":row["value"],
                    "placement":row["placement"],"encoded_text":_insertion_text(row,unit),"inherited_mcids":anchor["mcids"],"font_sha256":private["sha256"]})
            else:
                text = anchor.get("leading","")+row["value"]+anchor["trailing"]; raw = text.encode("utf-16-be")
                old = _advance(bytes.fromhex(anchor["encoded_hex"]),unit["font"]); new = _advance(raw,private)
                scale = anchor["scale"]*old/new
                _need(math.isfinite(scale) and .001 <= scale <= 100000,"Corrected OCR text exceeds supported fitting bounds")
                instructions += [_instruction("Tf",[pikepdf.Name(name),Decimal(str(anchor["font_size"]))]),_instruction("Tz",[scale]),
                    _instruction("Tj",[pikepdf.String(raw)]),_instruction("Tf",[pikepdf.Name(anchor["font_name"]),Decimal(str(anchor["font_size"]))]),
                    _instruction("Tz",[anchor["scale"]])]
                records.append({"id":row["id"],"kind":"replace","page":unit["page"],"original":unit["current"],"value":row["value"],
                    "old_advance_units":old*anchor["scale"]/100,"new_advance_units":new*scale/100,"font_sha256":private["sha256"],"trailing_separator_preserved":True})
        _cancel(cancel); target.write(pikepdf.unparse_content_stream(instructions))
    return records


def _raw_annotations(path):
    """Preserve raw annotation fields, ignoring only structural/page backrefs."""
    with pikepdf.open(path) as pdf:
        pages = {tuple(page.obj.objgen): index + 1 for index, page in enumerate(pdf.pages)}
        def canonical(value, active=()):
            if isinstance(value, pikepdf.String):
                return ["string", bytes(value).hex()]
            if isinstance(value, pikepdf.Name):
                return ["name", str(value)]
            if value is None or isinstance(value, (bool, int, float, Decimal)):
                return value if value is None or isinstance(value, (bool, int)) else _number(value)
            _need(isinstance(value, (pikepdf.Array, pikepdf.Dictionary, pikepdf.Stream)), "Unsupported annotation value")
            key = tuple(value.objgen)
            if key in pages:
                return ["page", pages[key]]
            _need(not key[0] or key not in active, "Cyclic annotation fields are unsupported")
            children = active + (key,) if key[0] else active
            if isinstance(value, pikepdf.Array):
                return [canonical(item, children) for item in value]
            ignored = {"/P", "/StructParent", "/StructParents"}
            if isinstance(value, pikepdf.Stream):
                ignored |= {"/Length", "/Filter", "/DecodeParms"}
            result = {str(k): canonical(v, children) for k, v in value.items() if str(k) not in ignored}
            if isinstance(value, pikepdf.Stream):
                try:
                    result["$decoded_sha256"] = hashlib.sha256(value.read_bytes()).hexdigest()
                except pikepdf.PdfError:
                    result["$encoded_sha256"] = hashlib.sha256(value.read_raw_bytes()).hexdigest()
                    result["$filter"] = str(value.get("/Filter")); result["$decode"] = str(value.get("/DecodeParms"))
            return result
        return [[canonical(item) for item in page.obj.get("/Annots", [])] for page in pdf.pages]


def _verify_original_relation(inventory, cancel=None):
    """Do not promote a forged/wrong prior OCR image into an authoritative source."""
    original, artifact = inventory["true_original"]["path"], inventory["artifact"]["path"]
    original_text = _page_text(original, cancel=cancel); current_text = _page_text(artifact, cancel=cancel)
    _need(set(original_text) == set(current_text), "The original-to-OCR page coverage changed")
    selected = set(inventory["ocr_pages"])
    _need(all(not row["text"] if page in selected else row["text"] == current_text[page]["text"]
              for page, row in original_text.items()), "Original or excluded-page literal text changed before OCR correction")
    raw_annotations = _raw_annotations(original)
    _need(raw_annotations == _raw_annotations(artifact), "Original raw annotation fields changed before OCR correction")
    fidelity = compare_fidelity(original, artifact, cancel=cancel)
    _need(not fidelity.get("error") and len(fidelity.get("pages", [])) == len(original_text)
          and all(all(page.get(key) == "pass" for key in ("render_status", "dimensions_status", "page_boxes_status", "annotations_status")) for page in fidelity["pages"])
          and all(check.get("status") == "pass" for check in fidelity["checks"] if check.get("id") != "all-page-render-and-content"),
          "Original page appearance, boxes, navigation or protected features changed before OCR correction")
    return {"status": "pass-original-to-ocr-preservation", "original_sha256": _sha(original), "artifact_sha256": _sha(artifact),
            "excluded_page_literal_text_verified": True, "raw_annotation_fields_verified": True,
            "fidelity": fidelity}


def _raw_structure(path):
    """Canonical structure graph; Form references name their invocation, not bytes."""
    with pikepdf.open(path) as pdf:
        pages = {tuple(page.obj.objgen):index+1 for index,page in enumerate(pdf.pages)}; forms = {}; visited = {}
        def walk_forms(target,resources,page,parts=(),active=()):
            for instruction in pikepdf.parse_content_stream(target):
                if str(instruction.operator) != "Do": continue
                name = str(instruction.operands[0]); child = resources.get("/XObject",{}).get(name)
                if not isinstance(child,pikepdf.Stream) or child.get("/Subtype") != pikepdf.Name.Form: continue
                key = tuple(child.objgen); _need(key not in active,"Cyclic Form structure reference")
                forms.setdefault(key,[]).append([page,list(parts+(name,))])
                walk_forms(child,child.get("/Resources",resources),page,parts+(name,),active+(key,))
        for index,page in enumerate(pdf.pages): walk_forms(page,page.Resources,index+1)
        def value(item,depth=0):
            _need(depth <= 180 and len(visited) <= MAX_ITEMS,"Structure graph exceeds its supported bounds")
            if isinstance(item,pikepdf.Name): return ["name",str(item)]
            if isinstance(item,pikepdf.String): return ["string",bytes(item).hex()]
            if item is None or isinstance(item,(int,float,bool,Decimal)): return item if item is None or isinstance(item,(int,bool)) else _number(item)
            _need(isinstance(item,(pikepdf.Dictionary,pikepdf.Array,pikepdf.Stream)),"Unknown structure value")
            key = tuple(item.objgen)
            if key in pages: return ["page",pages[key]]
            if key in forms: return ["form",forms[key]]
            if key[0]:
                if key in visited: return ["ref",visited[key]]
                visited[key] = len(visited)
            if isinstance(item,pikepdf.Array): return [value(v,depth+1) for v in item]
            result = {str(k):value(item[k],depth+1) for k in sorted(item.keys()) if str(k) not in {"/Length","/Filter","/DecodeParms"}}
            if isinstance(item,pikepdf.Stream): result["$sha256"] = hashlib.sha256(item.read_bytes()).hexdigest()
            return result
        return value(pdf.Root.get("/StructTreeRoot"))


def _character_projection(record, mapping, affected, changed=None):
    """Keep literal old Unicode and untouched generated separators in their order."""
    rows = record["characters"]; output = []; changed = affected if changed is None else changed
    for index,(owner,code) in enumerate(rows):
        if owner is not None:
            old = mapping.get(owner)
            if old is not None and old not in changed: output.append([old,code])
            continue
        _need(code == 0 or chr(code).isspace(),"Independent extraction created unowned non-separator text")
        neighbors = []; inserted_boundary = False
        for step in (-1,1):
            cursor = index+step
            while 0 <= cursor < len(rows):
                candidate = rows[cursor][0]
                if candidate is not None:
                    if candidate not in mapping: inserted_boundary = True; break
                    old = mapping.get(candidate)
                    if old is not None: neighbors.append(old); break
                cursor += step
        if not inserted_boundary and not any(owner in affected for owner in neighbors): output.append([None,code])
    return output


def _verify_expanded(inventory, output, rows, cancel=None):
    _cancel(cancel)
    before = Path(inventory["artifact"]["path"]); after = Path(output); qualified = _qualified_font()
    original_relation = _verify_original_relation(inventory,cancel)
    left,le = _scan(before,inventory["ocr_pages"],cancel,expanded=True); right,re = _scan(after,inventory["ocr_pages"],cancel,expanded=True)
    _need(le == re,"Expanded correction changed unsupported OCR page coverage")
    replacements = {row["id"]:row for row in rows if row["kind"] == "replace"}
    insertions = {row["anchor_id"]:row for row in rows if row["kind"] == "insert"}; expected = []
    for unit in left:
        row = insertions.get(unit["id"])
        if row and row["placement"]["order"] == "before": expected.append(("insert",unit,row))
        expected.append(("replace" if unit["id"] in replacements else "unchanged",unit,replacements.get(unit["id"])))
        if row and row["placement"]["order"] == "after": expected.append(("insert",unit,row))
    _need(len(right) == len(expected),"Expanded correction changed text occurrence coverage")
    with pikepdf.Pdf.new() as fontpdf: private_info = _font_info(_private_font(fontpdf,qualified))
    old_owners = _owners(before,left); new_owners = _owners(after,right)
    for (kind,old,row),new in zip(expected,right):
        _cancel(cancel)
        _need(old["page"] == new["page"] and old["anchor"]["form_path"] == new["anchor"]["form_path"]
              and old["anchor"]["mcids"] == new["anchor"]["mcids"],"The corrected word changed page, Form or structure scope")
        if kind == "unchanged":
            _need(old["current"] == new["current"] and old["anchor"]["encoded_hex"] == new["anchor"]["encoded_hex"]
                  and old["font"]["sha256"] == new["font"]["sha256"] and old["anchor"]["font_size"] == new["anchor"]["font_size"]
                  and old["font"]["private_policy_sha256"] == new["font"]["private_policy_sha256"]
                  and old["anchor"]["scale"] == new["anchor"]["scale"],"An untouched encoded OCR occurrence or font changed")
        else:
            expected_text = _insertion_text(row,old) if kind == "insert" else old["anchor"].get("leading","")+row["value"]+old["anchor"]["trailing"]
            _need(new["anchor"]["encoded_hex"] == expected_text.encode("utf-16-be").hex() and new["font"]["sha256"] == private_info["sha256"]
                  and new["font"]["private_policy_sha256"] == private_info["private_policy_sha256"],
                  "The new private font, Unicode map or literal correction text is wrong")
            if kind == "insert":
                _need(old["id"] in old_owners and new_owners.get(new["id"]) == old_owners[old["id"]],"The inserted word lost its unique existing structure owner")
            else:
                old_advance = _advance(bytes.fromhex(old["anchor"]["encoded_hex"]),old["font"])*old["anchor"]["scale"]*old["anchor"]["font_size"]
                new_advance = _advance(bytes.fromhex(new["anchor"]["encoded_hex"]),new["font"])*new["anchor"]["scale"]*new["anchor"]["font_size"]
                _need(abs(old_advance-new_advance) <= 1e-7*max(1,abs(old_advance)),"A replacement moved the following text advance")
    old_pages,new_pages = _page_objects(before,cancel=cancel),_page_objects(after,cancel=cancel); max_delta = 0.
    _need(set(old_pages) == set(new_pages),"Expanded correction changed page coverage")
    for page,oldpage in old_pages.items():
        newpage = new_pages[page]; sequence = [e for e in expected if e[1]["page"] == page]
        changes = [e for e in sequence if e[0] != "unchanged"]
        if not changes:
            _need(oldpage == newpage,"An untouched page's literal text or geometry changed"); continue
        oldunits = [unit for unit in left if unit["page"] == page]; oldindexes = {unit["id"]:index for index,unit in enumerate(oldunits)}
        _need(len(oldpage["objects"]) == len(oldunits) and len(newpage["objects"]) == len(sequence),"Independent text-object coverage is ambiguous")
        mapping = {}; affected = {oldindexes[unit["id"]] for kind,unit,row in changes}; newinsertindexes = {}
        replaced_indexes = {oldindexes[unit["id"]] for kind,unit,row in changes if kind == "replace"}
        for index,(kind,unit,row) in enumerate(sequence):
            actual = newpage["objects"][index]; oldindex = oldindexes[unit["id"]]
            if kind != "insert": mapping[index] = oldindex
            if kind == "unchanged":
                prior = oldpage["objects"][oldindex]
                same_text = actual["text"] == prior["text"]
                if unit["id"] in insertions:
                    # PDFium may append a generated U0020 to this anchor when
                    # a neighboring word is added. Only this extraction view
                    # may vary at its ASCII-space boundaries. Encoded old
                    # bytes/font and all independently owned old characters
                    # remain exact below; other occurrences stay literal.
                    same_text = actual["text"].strip(" ") == prior["text"].strip(" ") == unit["current"]
                _need(same_text,"An untouched literal OCR occurrence changed")
                delta = max(abs(x-y) for key in ("bounds","matrix") for x,y in zip(actual[key],prior[key]))
                max_delta = max(max_delta,delta); _need(delta <= .001,"An untouched OCR occurrence moved")
            else:
                _need(newpage["glyph_boxes"][index],"Independent extraction has no nonempty corrected glyph bounds")
                if kind == "replace":
                    previous = oldpage["objects"][oldindex]["text"]
                    leading = unit["anchor"].get("leading","")
                    _need(previous.strip(" ") == unit["current"],"Independent extraction transforms this replacement")
                    _need(actual["text"].strip(" ") == row["value"],"Independent replacement Unicode is wrong")
                else:
                    _need(actual["text"].strip(" ") == row["value"],"Independent inserted Unicode is wrong")
                    newinsertindexes[index] = (oldindex,row["placement"]["order"])
                for bounds in newpage["glyph_boxes"][index]:
                    _need(all(math.isfinite(v) for v in bounds),"A corrected glyph has invalid geometry")
                    _check_form_clips([(bounds[0],bounds[1]),(bounds[2],bounds[1]),(bounds[2],bounds[3]),(bounds[0],bounds[3])],unit["geometry"])
                    normalized = _normalized_box(bounds,newpage["page_box"],newpage["rotation"])
                    _need(normalized[0] >= -1e-6 and normalized[1] >= -1e-6 and normalized[0]+normalized[2] <= 1+1e-6
                          and normalized[1]+normalized[3] <= 1+1e-6,"A corrected glyph would be clipped by page bounds")
                    if kind == "insert":
                        l,t,w,h = row["placement"]["rect"]
                        _need(normalized[0] >= l-1e-5 and normalized[1] >= t-1e-5 and normalized[0]+normalized[2] <= l+w+1e-5
                              and normalized[1]+normalized[3] <= t+h+1e-5,"Inserted glyph ink lies outside the accepted preview rectangle")
                    else:
                        _need(not any(_overlap(normalized,_normalized_box(other,newpage["page_box"],newpage["rotation"]))
                            for otherindex,otherbounds in oldpage["glyph_boxes"].items() if otherindex != oldindex for other in otherbounds),
                            "The replacement glyph ink would overlap another existing OCR occurrence")
        oldmapping = {i:i for i in range(len(oldunits))}
        _need(_character_projection(oldpage,oldmapping,affected,replaced_indexes) == _character_projection(newpage,mapping,affected,replaced_indexes),
              "Untouched literal Unicode, order or generated separators changed")
        # Verify the inserted object is adjacent to its anchor in independent
        # character order as well as in PDF operator/structure order.
        owner_order = []
        for owner,code in newpage["characters"]:
            if owner is not None and code and (not owner_order or owner_order[-1] != owner): owner_order.append(owner)
        for inserted,(oldindex,order) in newinsertindexes.items():
            anchors = [index for index,old in mapping.items() if old == oldindex]
            _need(len(anchors) == 1 and owner_order.count(inserted) == 1 and owner_order.count(anchors[0]) == 1,"Independent insertion order is ambiguous")
            delta = owner_order.index(inserted)-owner_order.index(anchors[0])
            _need(delta == (-1 if order == "before" else 1),"Independent insertion order differs from the accepted anchor order")
    _need(_raw_annotations(before) == _raw_annotations(after),"Expanded correction changed raw annotation fields")
    _need(_raw_structure(before) == _raw_structure(after),"Expanded correction changed the existing structure graph")
    fidelity = compare_fidelity(before,after,cancel=cancel)
    _need(not fidelity.get("error") and len(fidelity.get("pages",[])) == len(old_pages)
        and all(all(page.get(key) == "pass" for key in ("render_status","dimensions_status","page_boxes_status","annotations_status")) for page in fidelity["pages"])
        and all(check.get("status") == "pass" for check in fidelity["checks"] if check.get("id") != "all-page-render-and-content"),
        "Expanded correction changed page appearance, boxes, annotations, navigation or protected features")
    return {"schema_version":EVIDENCE_SCHEMA,"status":"pass-explicit-ocr-text-corrections","before_sha256":_sha(before),"after_sha256":_sha(after),
        "corrections_applied":len(rows),"literal_substitutions_verified":True,"literal_insertions_verified":True,"untouched_text_verified":True,
        "encoded_unicode_verified":True,"structure_ownership_verified":True,"insertion_geometry_verified":True,"anchor_order_verified":True,
        "insertions_applied":len(insertions),"replacements_applied":len(replacements),"max_untouched_character_delta_points":max_delta,
        "font_resource":{"resource":"pdf_remediator/data/NotoSans-Regular.ttf","sha256":qualified["sha256"]},"font_policy":FONT_POLICY,
        "separator_scope":"Original encoded separators retained; generated separators adjacent to explicitly changed anchors require fresh reading-order review.",
        "fidelity":fidelity,"original_relation":original_relation,"human_approved":False,"accessibility_approved":False,"AI_calls":0,"OCR_calls":0}


def _verify_output(inventory, output, rows, cancel=None):
    before = Path(inventory["artifact"]["path"]); after = Path(output)
    _cancel(cancel)
    original_relation = _verify_original_relation(inventory, cancel)
    left, le = _scan(before, inventory["ocr_pages"], cancel); right, re = _scan(after, inventory["ocr_pages"], cancel)
    _need(le == re and len(left) == len(right), "The corrected PDF changed supported OCR occurrence coverage")
    edits = {row["id"]: row["value"] for row in rows}; changed_positions = set()
    for index, (a, b) in enumerate(zip(left, right)):
        _need(a["page"] == b["page"] and a["anchor"]["form_path"] == b["anchor"]["form_path"]
              and a["anchor"]["show"] == b["anchor"]["show"] and a["font"]["sha256"] == b["font"]["sha256"]
              and a["anchor"]["font_size"] == b["anchor"]["font_size"] and a["anchor"]["mcids"] == b["anchor"]["mcids"]
              and a["anchor"]["trailing"] == b["anchor"]["trailing"], "OCR fonts, marking, positioning scope or separators changed")
        expected = edits.get(a["id"], a["current"])
        _need(b["current"] == expected, "The actual encoded OCR text differs from the authorized correction")
        if a["id"] not in edits:
            _need(a["anchor"]["encoded_hex"] == b["anchor"]["encoded_hex"] and a["anchor"]["scale"] == b["anchor"]["scale"], "An untouched OCR word changed")
        else:
            changed_positions.add(index)
        old = _advance(bytes.fromhex(a["anchor"]["encoded_hex"]), a["font"]) * a["anchor"]["scale"] / 100
        new = _advance(bytes.fromhex(b["anchor"]["encoded_hex"]), b["font"]) * b["anchor"]["scale"] / 100
        _need(abs(old - new) <= 1e-7 * max(1, abs(old)), "A corrected word changed the following text advance")
    _need(len(changed_positions) == len(rows), "Not every accepted OCR correction was applied exactly once")
    old_pages, new_pages = _page_objects(before, cancel=cancel), _page_objects(after, cancel=cancel)
    _need(set(old_pages) == set(new_pages), "Corrected source page coverage changed")
    max_untouched_delta = 0.0
    for page_number, old_page in old_pages.items():
        fresh_page = new_pages[page_number]
        page_units = [item for item in left if item["page"] == page_number]
        if any(item["id"] in edits for item in page_units):
            _need(len(old_page["objects"]) == len(fresh_page["objects"]) == len(page_units), "Independent OCR text-object coverage is ambiguous")
            changed_objects = set()
            for index, (a, b, item) in enumerate(zip(old_page["objects"], fresh_page["objects"], page_units)):
                if item["id"] in edits:
                    _need(a["text"] in (item["current"], item["current"] + item["anchor"]["trailing"]),
                          "Independent extraction transforms this occurrence; it cannot be edited safely")
                    suffix = item["anchor"]["trailing"] if a["text"] == item["current"] + item["anchor"]["trailing"] else ""
                    _need(b["text"] == edits[item["id"]] + suffix, "Independent final Unicode or separator text differs from the authorized correction")
                    _need(all(math.isfinite(v) for v in b["bounds"] + b["matrix"]), "Corrected OCR text has invalid geometry")
                    box = fresh_page["page_box"]
                    for bounds in fresh_page["glyph_boxes"][index]:
                        _need(all(math.isfinite(v) for v in bounds) and bounds[0] >= box[0] - .001 and bounds[1] >= box[1] - .001
                              and bounds[2] <= box[2] + .001 and bounds[3] <= box[3] + .001,
                              "Corrected OCR glyphs would be clipped by the page bounds")
                    changed_objects.add(index)
                else:
                    _need(a["text"] == b["text"], "An untouched OCR occurrence changed in independent extraction")
                    delta = max(abs(x - y) for key in ("bounds", "matrix") for x, y in zip(a[key], b[key]))
                    max_untouched_delta = max(max_untouched_delta, delta)
                    _need(delta <= .001, "An untouched OCR occurrence moved")
            _need([row for row in old_page["characters"] if row[0] not in changed_objects]
                  == [row for row in fresh_page["characters"] if row[0] not in changed_objects],
                  "Independent untouched Unicode order or generated word separators changed")
        else:
            _need(fresh_page == old_page, "An untouched page's literal text, ownership or geometry changed")
    fidelity = compare_fidelity(before, after, cancel=cancel)
    _need(not fidelity.get("error") and len(fidelity.get("pages", [])) == len(old_pages)
          and all(all(page.get(key) == "pass" for key in ("render_status", "dimensions_status", "page_boxes_status", "annotations_status")) for page in fidelity["pages"])
          and all(check.get("status") == "pass" for check in fidelity["checks"] if check.get("id") != "all-page-render-and-content"),
          "OCR correction changed a page appearance, box, annotation, navigation or protected feature")
    return {"schema_version": EVIDENCE_SCHEMA, "status": "pass-explicit-ocr-text-corrections", "before_sha256": _sha(before),
            "after_sha256": _sha(after), "corrections_applied": len(rows), "literal_substitutions_verified": True,
            "untouched_text_verified": True, "encoded_unicode_verified": True, "max_untouched_character_delta_points": max_untouched_delta,
            "fidelity": fidelity, "original_relation": original_relation,
            "human_approved": False, "accessibility_approved": False, "AI_calls": 0, "OCR_calls": 0}


def _watched(inventory, plan_path, bundle):
    paths = [plan_path, Path(bundle) / "manifest.json", Path(bundle) / "report.json"]
    paths += [inventory[key]["path"] for key in ("source", "artifact", "prepared", "true_original")]
    if inventory.get("source_lineage"):
        paths.append(inventory["source_lineage"]["path"])
    return {str(Path(path).resolve()): _sha(path) for path in paths}


def create_derivative(bundle_path, plan_path, destination, expected_plan_sha256=None, cancel=None):
    """Publish a separate corrected source plus immutable correction provenance."""
    plan_path = Path(plan_path).resolve(); profile = _plan_profile(plan_path)
    inventory = get_inventory(bundle_path,cancel,profile=profile)
    plan = _plan(plan_path, inventory, expected_plan_sha256); watched = _watched(inventory, plan_path, bundle_path)
    qualified = _qualified_font() if profile == "expanded-v2" else None
    if qualified: watched[qualified["path"]] = qualified["sha256"]
    destination = Path(destination).absolute()
    _need(not destination.exists(), "An OCR correction source destination cannot be overwritten")
    for part in (destination, *destination.parents):
        _need(not part.is_symlink() and not getattr(part, "is_junction", lambda: False)(), "OCR correction destinations cannot traverse aliases")
    destination = destination.resolve()
    _need(destination.parent.is_dir() and not any(destination == Path(p) or destination in Path(p).parents for p in watched)
          and Path(bundle_path).resolve() not in destination.parents, "Choose a separate OCR correction source directory")
    staging = Path(tempfile.mkdtemp(prefix=".ocr-source-", dir=destination.parent))
    published = False
    try:
        _cancel(cancel)
        units, failures = _scan(inventory["artifact"]["path"],inventory["ocr_pages"],cancel,expanded=qualified is not None)
        edits = {row["id"]: row for row in plan["corrections"]}
        targets = {row.get("anchor_id",row["id"]) for row in plan["corrections"]}
        _need(targets <= {item["id"] for item in units}, "OCR correction occurrences changed before writing")
        output = staging / "corrected-source.pdf"
        with pikepdf.open(inventory["artifact"]["path"]) as pdf:
            operations = _write_expanded(pdf,units,plan["corrections"],inventory,qualified,cancel) if qualified else _replace(pdf, units, edits)
            with output.open("xb") as stream:
                pdf.save(stream, deterministic_id=True)
        evidence = (_verify_expanded if qualified else _verify_output)(inventory, output, plan["corrections"], cancel)
        evidence["operations"] = operations
        _save(staging / "correction-evidence.json", evidence)
        with (staging / "ocr-corrections.json").open("xb") as stream:
            stream.write(plan_path.read_bytes())
        lineage = {"schema_version": LINEAGE_SCHEMA, "original": inventory["true_original"],
                   "current_source": {"path": str(destination / output.name), "sha256": _sha(output)},
                   "parent_source": inventory["source"], "corrected_from": inventory["artifact"], "prepared": inventory["prepared"],
                   "bundle": inventory["bundle"], "ocr_pages": inventory["ocr_pages"],
                   "parent_lineage": inventory.get("source_lineage"),
                   "plan": {"path": str(destination / "ocr-corrections.json"), "sha256": _sha(staging / "ocr-corrections.json")},
                   "evidence": {"path": str(destination / "correction-evidence.json"), "sha256": _sha(staging / "correction-evidence.json")},
                   "human_approved": False, "accessibility_approved": False, "AI_calls": 0, "OCR_calls": 0,
                   "required_review": "Review corrected OCR text against the source image, including accuracy, completeness and reading order. This is a corrected source copy; the original was not overwritten."}
        lineage["binding_sha256"] = _digest(lineage)
        _save(staging / "source-lineage.json", lineage)
        _cancel(cancel)
        _need(all(_sha(path) == digest for path, digest in watched.items()), "A correction input or saved review changed during processing")
        from .pipeline import verify_bundle
        _need(verify_bundle(bundle_path), "The immutable correction review changed during processing")
        if inventory.get("source_lineage"):
            row = inventory["source_lineage"]
            validate_lineage_bindings(row["path"], inventory["source"]["path"], row["sha256"], cancel)
        staging.rename(destination); published = True
        return {"source_path": str(destination / output.name), "source_sha256": lineage["current_source"]["sha256"],
                "lineage_path": str(destination / "source-lineage.json"), "lineage_sha256": _sha(destination / "source-lineage.json"),
                "plan_path": str(destination / "ocr-corrections.json"), "plan_sha256": lineage["plan"]["sha256"],
                "evidence_path": str(destination / "correction-evidence.json"), "evidence_sha256": lineage["evidence"]["sha256"],
                "corrections_applied": len(plan["corrections"]), "original": inventory["true_original"], "review_required": True}
    finally:
        if not published:
            # Only this function's fresh, owned staging directory can be removed.
            _need(staging.parent == destination.parent and staging.name.startswith(".ocr-source-")
                  and staging.resolve() == staging and not staging.is_symlink()
                  and not getattr(staging, "is_junction", lambda: False)(),
                  "The owned correction staging directory moved; retain it for review")
            shutil.rmtree(staging)


def _validate_lineage(lineage_path, source_path, expected_sha256=None, cancel=None, seen=()):
    _cancel(cancel)
    path = Path(lineage_path).resolve(); source_path = Path(source_path).resolve()
    _need(len(seen) <= MAX_ANCESTRY * 2 and str(path) not in seen, "OCR correction ancestry is cyclic or too deep")
    if expected_sha256 is not None:
        _need(isinstance(expected_sha256, str) and bool(_SHA.fullmatch(expected_sha256)) and _sha(path) == expected_sha256,
              "Source OCR correction lineage changed")
    _need(path.stat().st_size <= 8 * 1024**2, "Source OCR lineage exceeds its supported bounds")
    lineage = _read(path)
    keys = {"schema_version", "original", "current_source", "parent_source", "corrected_from", "prepared", "bundle", "ocr_pages", "parent_lineage", "plan", "evidence", "human_approved", "accessibility_approved", "AI_calls", "OCR_calls", "required_review", "binding_sha256"}
    _need(isinstance(lineage, dict) and set(lineage) == keys and lineage["schema_version"] == LINEAGE_SCHEMA
          and lineage["binding_sha256"] == _digest({k: v for k, v in lineage.items() if k != "binding_sha256"})
          and lineage["human_approved"] is lineage["accessibility_approved"] is False and lineage["AI_calls"] == lineage["OCR_calls"] == 0,
          "Unknown or altered source OCR lineage")
    watched = {str(path): _sha(path), str(source_path): _sha(source_path)}
    for key in ("original", "current_source", "parent_source", "corrected_from", "prepared", "plan", "evidence"):
        bound = _checked(lineage[key]); watched[str(bound)] = lineage[key]["sha256"]
    _need(_sha(source_path) == lineage["current_source"]["sha256"], "OCR lineage belongs to another corrected source")
    bundle = lineage["bundle"]
    _need(isinstance(bundle, dict) and set(bundle) == {"path", "manifest_sha256", "report_sha256"}, "Invalid source correction bundle binding")
    for name, key in (("manifest.json", "manifest_sha256"), ("report.json", "report_sha256")):
        file = Path(bundle["path"]) / name; _need(_sha(file) == bundle[key], "Original correction bundle changed"); watched[str(file)] = bundle[key]
    profile = _plan_profile(lineage["plan"]["path"])
    inventory = _inventory(bundle["path"],cancel,seen+(str(path),),profile=profile)
    _need(lineage["original"] == inventory.get("true_original") and lineage["parent_source"] == inventory["source"]
          and lineage["corrected_from"] == inventory["artifact"] and lineage["prepared"] == inventory["prepared"]
          and lineage["ocr_pages"] == inventory["ocr_pages"] and lineage["parent_lineage"] == inventory.get("source_lineage"),
          "OCR correction ancestry or source scope changed")
    plan = _plan(lineage["plan"]["path"], inventory, lineage["plan"]["sha256"])
    evidence = _read(lineage["evidence"]["path"])
    fresh = (_verify_expanded if profile == "expanded-v2" else _verify_output)(inventory,source_path,plan["corrections"],cancel)
    _need(evidence.get("schema_version") == EVIDENCE_SCHEMA and evidence.get("status") == fresh["status"]
          and evidence.get("before_sha256") == fresh["before_sha256"] and evidence.get("after_sha256") == fresh["after_sha256"]
          and evidence.get("corrections_applied") == fresh["corrections_applied"]
          and all(evidence.get(key) is True for key in ("literal_substitutions_verified", "untouched_text_verified", "encoded_unicode_verified")),
          "Retained OCR correction proof does not match the current independently verified bytes")
    if profile == "expanded-v2":
        _need(all(evidence.get(key) == fresh.get(key) for key in ("literal_insertions_verified","structure_ownership_verified","insertion_geometry_verified",
            "anchor_order_verified","insertions_applied","replacements_applied","font_policy","font_resource","separator_scope")),
            "Retained expanded proof differs from the independently verified operations")
    _cancel(cancel)
    _need(all(_sha(file) == digest for file, digest in watched.items()), "Source correction ancestry changed during verification")
    validate_lineage_bindings(path, source_path, expected_sha256, cancel)
    return {"schema_version": LINEAGE_SCHEMA, "original": copy.deepcopy(lineage["original"]),
            "current_source": {"path": str(source_path), "sha256": _sha(source_path)}, "ocr_pages": list(lineage["ocr_pages"]),
            "lineage": _bind(path), "corrections_applied": len(plan["corrections"]), "review_required": True,
            "required_review": lineage["required_review"], "human_approved": False, "accessibility_approved": False,
            "AI_calls": 0, "OCR_calls": 0}


def validate_lineage(lineage_path, source_path, expected_sha256=None, cancel=None):
    """Recheck retained provenance and the literal/visible correction proof."""
    return _validate_lineage(lineage_path, source_path, expected_sha256, cancel)


def validate_lineage_bindings(lineage_path, source_path, expected_sha256=None, cancel=None):
    """Freshness guard for review actions: JSON and hashes only, never PDF parsing.

    This does not replace full create/application verification. It makes every
    external dependency of the retained proof part of saved-review freshness.
    """
    watched = {}

    def watch(row):
        _cancel(cancel)
        _need(isinstance(row, dict) and set(row) == {"path", "sha256"}
              and isinstance(row["path"], str) and isinstance(row["sha256"], str)
              and bool(_SHA.fullmatch(row["sha256"])), "Invalid retained OCR dependency binding")
        path = Path(row["path"]).resolve(); key = str(path)
        if key in watched:
            _need(watched[key] == row["sha256"], "Conflicting OCR ancestry bindings")
        else:
            _need(len(watched) < MAX_ITEMS and path.is_file() and _sha(path) == row["sha256"],
                  "A retained OCR lineage dependency changed or is missing")
            watched[key] = row["sha256"]
        return path

    def inspect(path, source, expected, seen=()):
        path, source = Path(path).resolve(), Path(source).resolve()
        _need(len(seen) < MAX_ANCESTRY and str(path) not in seen, "OCR lineage dependencies are cyclic or too deep")
        if expected is None:
            expected = _sha(path)
        watch({"path": str(path), "sha256": expected})
        _need(path.stat().st_size <= 8 * 1024**2, "Source OCR lineage exceeds its supported bounds")
        lineage = _read(path)
        keys = {"schema_version", "original", "current_source", "parent_source", "corrected_from", "prepared", "bundle", "ocr_pages", "parent_lineage", "plan", "evidence", "human_approved", "accessibility_approved", "AI_calls", "OCR_calls", "required_review", "binding_sha256"}
        _need(isinstance(lineage, dict) and set(lineage) == keys and lineage["schema_version"] == LINEAGE_SCHEMA
              and lineage["binding_sha256"] == _digest({k: v for k, v in lineage.items() if k != "binding_sha256"})
              and lineage["human_approved"] is lineage["accessibility_approved"] is False
              and lineage["AI_calls"] == lineage["OCR_calls"] == 0,
              "Unknown or altered source OCR lineage")
        for key in ("original", "current_source", "parent_source", "corrected_from", "prepared", "plan", "evidence"):
            watch(lineage[key])
        watch({"path": str(source), "sha256": lineage["current_source"]["sha256"]})
        pages = lineage["ocr_pages"]
        _need(isinstance(pages, list) and pages and len(pages) == len(set(pages))
              and all(type(page) is int and 1 <= page <= 1000 for page in pages), "Invalid retained OCR page scope")
        bundle = lineage["bundle"]
        _need(isinstance(bundle, dict) and set(bundle) == {"path", "manifest_sha256", "report_sha256"}, "Invalid retained OCR bundle binding")
        root = Path(bundle["path"]).resolve()
        manifest_path = watch({"path": str(root / "manifest.json"), "sha256": bundle["manifest_sha256"]})
        report_path = watch({"path": str(root / "report.json"), "sha256": bundle["report_sha256"]})
        manifest, report = _read(manifest_path), _read(report_path)
        _need(isinstance(manifest, dict) and manifest.get("complete") is True
              and isinstance(manifest.get("files"), dict) and len(manifest["files"]) <= MAX_ITEMS
              and {"report.json", "review.html", "review.json", "decisions.json"} <= set(manifest["files"])
              and isinstance(report, dict) and report.get("run_fingerprint") == manifest.get("run_fingerprint"),
              "The retained OCR bundle is incomplete")
        for relative, digest in manifest["files"].items():
            file = (root / relative).resolve()
            _need(root in file.parents, "A retained OCR bundle dependency escaped its directory")
            watch({"path": str(file), "sha256": digest})
        def normalized(value):
            return {key: value[key] for key in ("path", "sha256") if key in value} if isinstance(value, dict) else None
        _need(report.get("mode") == "fix" and report.get("status") in ("candidate", "needs-manual", "verified")
              and report.get("fidelity", {}).get("status") == "pass"
              and normalized(report.get("input")) == lineage["parent_source"]
              and normalized(report.get("output")) == lineage["corrected_from"]
              and normalized(report.get("decision_source")) == lineage["prepared"]
              and report.get("source_lineage") == lineage["parent_lineage"], "Retained OCR source or preparation bindings changed")
        plan, evidence = _read(lineage["plan"]["path"]), _read(lineage["evidence"]["path"])
        _need(isinstance(plan, dict) and plan.get("schema_version") in (PLAN_SCHEMA,EXPANDED_PLAN_SCHEMA)
              and plan.get("source_sha256") == lineage["parent_source"]["sha256"]
              and plan.get("document_sha256") == lineage["corrected_from"]["sha256"]
              and isinstance(plan.get("corrections"), list) and 0 < len(plan["corrections"]) <= MAX_ITEMS
              and plan.get("human_approved") is plan.get("accessibility_approved") is False,
              "The retained OCR plan belongs to different source bytes")
        relation = evidence.get("original_relation", {}) if isinstance(evidence, dict) else {}
        _need(isinstance(evidence, dict) and evidence.get("schema_version") == EVIDENCE_SCHEMA
              and evidence.get("status") == "pass-explicit-ocr-text-corrections"
              and evidence.get("before_sha256") == lineage["corrected_from"]["sha256"]
              and evidence.get("after_sha256") == lineage["current_source"]["sha256"]
              and evidence.get("corrections_applied") == len(plan["corrections"])
              and evidence.get("human_approved") is evidence.get("accessibility_approved") is False
              and evidence.get("AI_calls") == evidence.get("OCR_calls") == 0
              and all(evidence.get(key) is True for key in ("literal_substitutions_verified", "untouched_text_verified", "encoded_unicode_verified"))
              and relation.get("status") == "pass-original-to-ocr-preservation"
              and relation.get("original_sha256") == lineage["original"]["sha256"]
              and relation.get("artifact_sha256") == lineage["corrected_from"]["sha256"],
              "Retained OCR proof dependencies do not match their source bytes")
        if plan["schema_version"] == EXPANDED_PLAN_SCHEMA:
            _need(isinstance(plan.get("expansion_sha256"),str) and bool(_SHA.fullmatch(plan["expansion_sha256"]))
                  and evidence.get("font_policy") == FONT_POLICY and evidence.get("font_resource") == {"resource":"pdf_remediator/data/NotoSans-Regular.ttf","sha256":FONT_SHA256}
                  and evidence.get("insertions_applied") == sum(row.get("kind") == "insert" for row in plan["corrections"])
                  and evidence.get("replacements_applied") == sum(row.get("kind") == "replace" for row in plan["corrections"])
                  and all(evidence.get(key) is True for key in ("literal_insertions_verified","structure_ownership_verified","insertion_geometry_verified","anchor_order_verified")),
                  "The retained expanded correction proof is incomplete")
        if lineage["parent_lineage"]:
            parent = lineage["parent_lineage"]; parent_path = watch(parent)
            previous = inspect(parent_path, lineage["parent_source"]["path"], parent["sha256"], seen + (str(path),))
            _need(previous["original"] == lineage["original"] and previous["ocr_pages"] == pages,
                  "The retained true original or OCR page ancestry changed")
        else:
            processor = next((row for row in report.get("processors", []) if isinstance(row, dict) and row.get("name") == "ocr"), None)
            _need(lineage["original"] == lineage["parent_source"] and report.get("ocr_pages") == pages
                  and report.get("settings", {}).get("ocr_mode") in ("skip", "textless") and processor is not None
                  and processor.get("status") == "completed" and processor.get("preservation", {}).get("status") == "pass",
                  "The first correction lacks its original local OCR scope")
        return {"schema_version": LINEAGE_SCHEMA, "original": copy.deepcopy(lineage["original"]),
                "current_source": {"path": str(source), "sha256": lineage["current_source"]["sha256"]},
                "ocr_pages": list(pages), "lineage": {"path": str(path), "sha256": expected},
                "corrections_applied": len(plan["corrections"]), "review_required": True,
                "required_review": lineage["required_review"], "human_approved": False, "accessibility_approved": False,
                "AI_calls": 0, "OCR_calls": 0, "bindings_verified": True}

    result = inspect(lineage_path, source_path, expected_sha256)
    for file, digest in watched.items():
        _cancel(cancel)
        _need(_sha(file) == digest, "OCR lineage dependencies changed during freshness checking")
    return result | {"dependency_count": len(watched), "dependency_sha256": _digest(watched)}
