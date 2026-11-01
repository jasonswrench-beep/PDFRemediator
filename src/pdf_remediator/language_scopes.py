"""Bounded language screening by independently owned, declared text scope.

No language is inferred into a PDF. Evidence contains counts/identifiers, never
document excerpts. A screen agreement is not a pronunciation or semantic review.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import ctypes
import hashlib

import pikepdf
import pypdfium2 as pdfium

from .language import assess_language
from .language_tags import is_language_tag
from .process import cancelled

PROFILE = "local-declared-language-scopes-1"
MAX_PAGE_OBJECTS = 20000
MAX_OBJECTS = 100000
MAX_CHARACTERS_PER_PAGE = 2000
MAX_TOTAL_CHARACTERS = 100000


def _tick(cancel):
    if cancelled(cancel):
        raise InterruptedError("Declared-language scope screening cancelled")


def _id(value):
    try:
        number, generation = value.objgen
        return f"{number}:{generation}" if number else None
    except (AttributeError, TypeError, ValueError):
        return None


def _dict(value):
    return isinstance(value, (pikepdf.Dictionary, pikepdf.Stream))


def _tag(value):
    if isinstance(value, pikepdf.String) and is_language_tag(str(value)):
        return str(value)
    return None


def _effective_languages(pdf, elements, cancel):
    """Use actual child ancestry; parent pointers alone cannot supply context."""
    root = pdf.Root.get("/StructTreeRoot")
    catalog = _tag(pdf.Root.get("/Lang"))
    mapped, active, repeated = {}, set(), set()
    declarations = 0
    visits = 0

    def walk(value, parent, inherited, origin, inherited_reasons=(), depth=0):
        nonlocal declarations, visits
        visits += 1
        if visits % 256 == 0:
            _tick(cancel)
        if depth > 200 or visits > 100000:
            raise ValueError("Language ancestry exceeds supported bounds")
        if isinstance(value, pikepdf.Array):
            for child in value:
                walk(child, parent, inherited, origin, inherited_reasons, depth + 1)
            return
        if not _dict(value) or "/S" not in value:
            return
        ident = _id(value)
        if ident is None:
            return
        if ident in active or ident in mapped:
            repeated.add(ident)
            return
        active.add(ident)
        reasons = set(inherited_reasons)
        if (isinstance(value, pikepdf.Stream) or not isinstance(value.get("/S"), pikepdf.Name)
                or ("/Type" in value and value.get("/Type") != pikepdf.Name.StructElem)):
            reasons.add("invalid-structure-language-scope")
        if _id(parent) is None or _id(value.get("/P")) != _id(parent):
            reasons.add("unproven-structure-ancestry")
        if "/ActualText" in value:
            reasons.add("structure-actualtext-not-assessed")
        language = inherited
        source = origin
        invalid = False
        if "/Lang" in value:
            declarations += 1
            language = _tag(value.get("/Lang"))
            source = ident
            invalid = language is None
            if invalid:
                reasons.add("invalid-source-language-declaration")
            else:
                reasons.discard("invalid-source-language-declaration")
        mapped[ident] = {"language": language, "origin": source,
                         "invalid": invalid, "reasons": sorted(reasons)}
        walk(value.get("/K"), value, language, source, reasons, depth + 1)
        active.remove(ident)

    if _dict(root):
        walk(root.get("/K"), root, catalog, "catalog")
    if repeated:
        # A second ancestry can change every descendant's inherited language.
        def descendants(node, seen=None):
            seen = set() if seen is None else seen
            if isinstance(node, pikepdf.Array):
                for child in node:
                    descendants(child, seen)
            elif _dict(node) and "/S" in node:
                ident = _id(node)
                if ident in seen:
                    return
                seen.add(ident)
                if ident in mapped:
                    mapped[ident]["reasons"] = sorted(set(mapped[ident]["reasons"]) | {"ambiguous-structure-ancestry"})
                descendants(node.get("/K"), seen)
        for ident in repeated:
            descendants(elements.get(ident))
    return mapped, declarations


def _page_marks(page):
    """Prove direct page MCID definitions and reject inline replacement scopes."""
    stack, definitions, blocked = [], defaultdict(int), set()
    malformed = False
    for number, instruction in enumerate(pikepdf.parse_content_stream(page)):
        if number > 500000:
            raise ValueError("Page language marking exceeds supported bounds")
        operands, operator = instruction.operands, str(instruction.operator)
        if operator in {"BMC", "BDC"}:
            props = operands[1] if operator == "BDC" and len(operands) == 2 else None
            if isinstance(props, pikepdf.Name):
                props = page.resources.get("/Properties", {}).get(str(props))
                if not _dict(props):
                    malformed = True
            mcid = props.get("/MCID") if _dict(props) else None
            if mcid is not None and (isinstance(mcid, bool) or not isinstance(mcid, int) or mcid < 0):
                malformed = True
                mcid = None
            if mcid is not None:
                definitions[mcid] += 1
            sensitive = bool(_dict(props) and any(key in props for key in ("/Lang", "/ActualText")))
            artifact = bool(operands and str(operands[0]) == "/Artifact")
            stack.append((mcid, sensitive, artifact))
        elif operator == "EMC":
            if not stack:
                malformed = True
            else:
                stack.pop()
        elif operator in {"Tj", "TJ", "'", '"'}:
            mcids = [item[0] for item in stack if item[0] is not None]
            if len(mcids) != 1 or any(item[1] or item[2] for item in stack):
                blocked.update(mcids)
    if stack:
        malformed = True
    return definitions, blocked, malformed


def _object_mcid(obj):
    count = pdfium.raw.FPDFPageObj_CountMarks(obj)
    if not 0 <= count <= 128:
        return None
    values = []
    for index in range(count):
        mark = pdfium.raw.FPDFPageObj_GetMark(obj, index)
        value = ctypes.c_int()
        if mark and pdfium.raw.FPDFPageObjMark_GetParamIntValue(mark, b"MCID", ctypes.byref(value)):
            values.append(value.value)
    return values[0] if len(values) == 1 and values[0] >= 0 else None


def assess_language_scopes(path, pdf, raw_global, *, sampled_pages, structure,
                           owners, elements, parent_tree, page_contents, cancel=None):
    """Return the identical old result when there are no local declarations.

    With declarations, map the exact represented sample characters to verified
    direct-page MCID owners. Unknown text is retained as unknown and independently
    screened against the catalog; a real supported mismatch is never hidden.
    """
    has_structural = any("/Lang" in node for node in elements.values())
    inline_pages = {number for number, content in page_contents.items()
                    if content.get("language_override_signals")}
    if not has_structural and not inline_pages:
        return raw_global
    _tick(cancel)
    grouped, unknown, origins, scope_pages, scope_elements = defaultdict(list), [], defaultdict(set), defaultdict(set), defaultdict(set)
    unknown_reasons, unknown_pages = set(), set()
    represented = proven = unproven = objects_total = 0
    ancestry_error = False
    try:
        language_map, declaration_count = _effective_languages(pdf, elements, cancel)
    except (ValueError, TypeError, KeyError, RuntimeError):
        language_map, declaration_count, ancestry_error = {}, sum("/Lang" in n for n in elements.values()), True
        unknown_reasons.add("unproven-structure-ancestry")

    with pdfium.PdfDocument(str(path)) as document:
        for number in sampled_pages:
            _tick(cancel)
            page = document[number - 1]
            textpage = None
            try:
                textpage = page.get_textpage()
                sample = textpage.get_text_range()[:MAX_CHARACTERS_PER_PAGE]
                represented += sum(not c.isspace() for c in sample)
                raw = []
                for index in range(min(textpage.count_chars(), MAX_CHARACTERS_PER_PAGE)):
                    codepoint = int(pdfium.raw.FPDFText_GetUnicode(textpage.raw, index))
                    raw.append(chr(codepoint) if 0 < codepoint <= 0x10FFFF else "\ufffd")
                if "".join(raw) != sample:
                    unknown.append(sample + "\n")
                    unproven += sum(not c.isspace() for c in sample)
                    unknown_pages.add(number); unknown_reasons.add("sample-character-map-unproven")
                    continue
                pdf_page = pdf.pages[number - 1]
                try:
                    definitions, blocked, malformed = _page_marks(pdf_page)
                except (pikepdf.PdfError, ValueError, TypeError, RuntimeError):
                    definitions, blocked, malformed = {}, set(), True
                pointers = {}
                for index, obj in enumerate(page.get_objects(max_depth=1, textpage=textpage)):
                    objects_total += 1
                    if index >= MAX_PAGE_OBJECTS or objects_total > MAX_OBJECTS:
                        malformed = True; unknown_reasons.add("sample-object-limit")
                        break
                    if obj.type == pdfium.raw.FPDF_PAGEOBJ_TEXT:
                        pointer = ctypes.cast(obj.raw, ctypes.c_void_p).value
                        pointers[pointer] = _object_mcid(obj)
                content = page_contents.get(number, {})
                bad_mcids = {item.get("mcid") for key in ["parent_tree_failures", "duplicate_mcids"]
                             for item in content.get(key, []) if item.get("stream") == "page"}
                if content.get("errors"):
                    malformed = True
                struct_parent = pdf_page.obj.get("/StructParents")
                values = parent_tree.get(struct_parent) if isinstance(struct_parent, int) and not isinstance(struct_parent, bool) else None
                last_key = None
                for index, character in enumerate(raw):
                    if index % 256 == 0:
                        _tick(cancel)
                    object_pointer = pdfium.raw.FPDFText_GetTextObject(textpage.raw, index)
                    pointer = ctypes.cast(object_pointer, ctypes.c_void_p).value if object_pointer else None
                    if character.isspace() and pointer is None:
                        if last_key is None: unknown.append(character)
                        else: grouped[last_key].append(character)
                        continue
                    mcid = pointers.get(pointer)
                    key = (number, "page", mcid)
                    candidates = owners.get(key, [])
                    owner = candidates[0] if len(candidates) == 1 else None
                    declaration = language_map.get(owner)
                    actual_parent = values[mcid] if isinstance(values, pikepdf.Array) and isinstance(mcid, int) and 0 <= mcid < len(values) else None
                    safe = (not ancestry_error and not malformed and mcid is not None
                            and definitions.get(mcid) == 1 and mcid not in blocked and mcid not in bad_mcids
                            and owner is not None and _id(actual_parent) == owner and declaration is not None
                            and not declaration["reasons"] and declaration["language"] is not None)
                    if not safe:
                        unknown.append(character)
                        if not character.isspace():
                            unproven += 1; unknown_pages.add(number)
                            if declaration and declaration["reasons"]: unknown_reasons.update(declaration["reasons"])
                            else: unknown_reasons.add("sampled-text-language-ownership-unproven")
                        last_key = None
                        continue
                    language = declaration["language"]
                    scope_key = (language, declaration["origin"], number)
                    if last_key != scope_key:
                        grouped[scope_key].append("\n")
                    grouped[scope_key].append(character)
                    if not character.isspace(): proven += 1
                    origins[scope_key].add(declaration["origin"])
                    scope_pages[scope_key].add(number); scope_elements[scope_key].add(owner)
                    last_key = scope_key
                for language in grouped: grouped[language].append("\n")
            finally:
                if textpage is not None: textpage.close()
                page.close()
    scopes = []
    for scope_key, characters in sorted(grouped.items()):
        language = scope_key[0]
        text = "".join(characters)[:MAX_TOTAL_CHARACTERS]
        assessment = assess_language(text, language)
        scopes.append({"id": "declared-language-" + hashlib.sha256(repr(scope_key).encode()).hexdigest()[:16],
            "declared_language": language, "declaration_syntax_valid": is_language_tag(language),
            "pages": sorted(scope_pages[scope_key]), "element_ids": sorted(scope_elements[scope_key]),
            "declaration_origins": sorted(origins[scope_key]), "characters": sum(not c.isspace() for c in text),
            "status": assessment["status"], "assessment": assessment})
    unknown_text = "".join(unknown)[:MAX_TOTAL_CHARACTERS]
    unknown_screen = assess_language(unknown_text, raw_global.get("declared_language", "")) if unproven else None
    failures = [scope for scope in scopes if scope["status"] == "fail"]
    retained_raw_failure = bool(unproven and raw_global.get("status") == "fail")
    if failures or (unknown_screen and unknown_screen["status"] == "fail") or retained_raw_failure:
        status = "fail"
    elif not scopes or unproven or any(scope["status"] != "pass" for scope in scopes):
        status = "needs-review"
    else:
        status = "pass"
    return {"profile": PROFILE, "status": status,
        "declared_language": raw_global.get("declared_language", ""),
        "declared_primary_language": raw_global.get("declared_primary_language"),
        "detected_language": None, "suggested_language": None,
        "sampling": copy.deepcopy(raw_global["sampling"]),
        "evidence": {"scope_mode": "verified-structure-effective-language", "structural_override_count": declaration_count,
            "inline_override_pages": sorted(inline_pages), "scope_count": len(scopes), "scopes": scopes,
            "represented_sample_characters": represented, "proven_sample_characters": proven,
            "unproven_sample_characters": unproven, "sampled_selectable_text_coverage_complete": not unproven and represented == proven,
            "complete_document_text_assessed": False, "alternate_text_assessed": False,
            "unproven": {"pages": sorted(unknown_pages), "reasons": sorted(unknown_reasons), "catalog_screen": unknown_screen},
            "raw_global_failure_retained_for_unproven_text": retained_raw_failure},
        "raw_global_diagnostic": {"scope": "Ignores local declarations; retained as a diagnostic, not an instruction to change document language.",
                                  "assessment": copy.deepcopy(raw_global)},
        "limitations": list(raw_global.get("limitations", [])) + [
            "Only the represented sampled selectable characters with exact direct-page MCID ownership are partitioned by declared effective language.",
            "Forms, inline language/replacement properties, ActualText, ambiguous ownership, unknown declarations and extraction gaps remain unproven.",
            "Language declarations are syntax-checked, not registry-authenticated; speech, translation, alternate text and semantic correctness require human review.",
            "Scoped suggestions are local diagnostic evidence only; no document language or PDF content is changed automatically."]}
