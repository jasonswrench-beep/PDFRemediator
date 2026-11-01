"""Read-only Phase 0 PDF evidence, with deliberately bounded claims.

This is a supplemental evaluator, not a PDF/UA or WCAG validator.  Paint
operators are the denominator for coverage, not glyphs, words or visual area.
The strict validator and human semantic review remain separate assessments.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import re
import unicodedata

import pikepdf
import pypdfium2 as pdfium
from PIL import ImageChops

SCHEMA_VERSION = "phase0-metrics-1.2"
PAINT = {"Tj", "TJ", "'", '"', "Do", "BI", "INLINE IMAGE", "S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "sh"}
STANDARD14 = {"Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic", "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique", "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique", "Symbol", "ZapfDingbats"}
PLACEHOLDER = re.compile(r"^(?:image|figure|picture|photo|graphic|illustration|alt(?:ernative)?\s*text|todo|tbd|placeholder|description(?:\s+here)?)(?:\s*\d+)?[.\s]*$|\.(?:png|jpe?g|gif|tiff?|bmp|svg)$", re.I)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _id(obj):
    try:
        number, generation = obj.objgen
        if number:
            return f"{number}:{generation}"
    except (AttributeError, TypeError, ValueError):
        pass
    return "direct:" + str(obj)[:240]


def _dict(obj):
    return isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream))


def _array(obj):
    return isinstance(obj, pikepdf.Array)


def _str(value):
    return "" if value is None else str(value)


def _check(name, status, evidence, scope, limitations=None):
    return {"id": name, "status": status, "evidence": evidence, "scope": scope,
            "limitations": limitations or []}


def _aggregate(checks):
    states = {c["status"] for c in checks}
    for state in ("error", "fail", "needs-review", "not-tested"):
        if state in states:
            return state
    return "pass"


def _number_tree(node, errors, seen=None):
    seen = set() if seen is None else seen
    result = {}
    if not _dict(node):
        return result
    ident = _id(node)
    if ident in seen:
        errors.append("Cycle or repeated node in number tree")
        return result
    seen.add(ident)
    nums = node.get("/Nums", [])
    if len(nums) % 2:
        errors.append("Odd /Nums length in number tree")
    for index in range(0, len(nums) - 1, 2):
        try:
            key = int(nums[index])
            if key in result:
                errors.append(f"Duplicate number-tree key {key}")
            result[key] = nums[index + 1]
        except (TypeError, ValueError):
            errors.append("Invalid number-tree key")
    for child in node.get("/Kids", []):
        for key, value in _number_tree(child, errors, seen).items():
            if key in result:
                errors.append(f"Duplicate number-tree key {key}")
            result[key] = value
    return result


def _destination(value, page_numbers):
    if _array(value):
        return [page_numbers.get(_id(item), _str(item)) if i == 0 else _str(item)
                for i, item in enumerate(value)]
    return _str(value)


def _navigation(pdf, page_numbers):
    errors = []
    outline = []
    seen = set()

    def walk(node, depth=0):
        while _dict(node):
            key = _id(node)
            if key in seen or depth > 200:
                errors.append("Outline cycle or excessive depth")
                return
            seen.add(key)
            action = node.get("/A", {})
            outline.append({"title": _str(node.get("/Title")), "depth": depth,
                            "destination": _destination(node.get("/Dest", action.get("/D") if _dict(action) else None), page_numbers),
                            "action": _str(action.get("/S")) if _dict(action) else "",
                            "uri": _str(action.get("/URI")) if _dict(action) else ""})
            walk(node.get("/First"), depth + 1)
            node = node.get("/Next")

    root = pdf.Root.get("/Outlines", {})
    if _dict(root):
        walk(root.get("/First"))
    label_map = _number_tree(pdf.Root.get("/PageLabels"), errors)
    labels = [{"index": key, "style": _str(value.get("/S")), "prefix": _str(value.get("/P")),
               "start": int(value.get("/St", 1))} for key, value in sorted(label_map.items()) if _dict(value)]
    # Preserve named destinations as well as the bookmarks that may reference them.
    names = []
    names_seen = set()

    def name_tree(node):
        if not _dict(node) or _id(node) in names_seen:
            return
        names_seen.add(_id(node))
        values = node.get("/Names", [])
        for i in range(0, len(values) - 1, 2):
            dest = values[i + 1]
            names.append([_str(values[i]), _destination(dest.get("/D") if _dict(dest) else dest, page_numbers)])
        for child in node.get("/Kids", []):
            name_tree(child)

    name_tree(pdf.Root.get("/Names", {}).get("/Dests"))
    old_dests = pdf.Root.get("/Dests", {})
    if _dict(old_dests):
        for key, value in old_dests.items():
            names.append([key, _destination(value.get("/D") if _dict(value) else value, page_numbers)])
    return {"bookmarks": outline, "page_labels": labels, "named_destinations": sorted(names, key=lambda item: item[0]), "errors": errors}


def _annotations(page, page_numbers):
    result = []
    for annotation in page.obj.get("/Annots", []):
        if not _dict(annotation):
            continue
        action = annotation.get("/A", {})
        result.append({"object": _id(annotation), "subtype": _str(annotation.get("/Subtype")),
                       "rect": [float(v) for v in annotation.get("/Rect", [])],
                       "contents": _str(annotation.get("/Contents")),
                       "field_name": _str(annotation.get("/T")), "field_value": _str(annotation.get("/V")),
                       "flags": int(annotation.get("/F", 0)),
                       "destination": _destination(annotation.get("/Dest", action.get("/D") if _dict(action) else None), page_numbers),
                       "action": _str(action.get("/S")) if _dict(action) else "",
                       "uri": _str(action.get("/URI")) if _dict(action) else "",
                       "struct_parent": int(annotation["/StructParent"]) if "/StructParent" in annotation else None})
    return result


def _structure(pdf, page_numbers):
    root = pdf.Root.get("/StructTreeRoot")
    data = {"present": _dict(root), "tag_counts": {}, "references": [], "object_references": [],
            "figures": [], "table_headers": [], "errors": [], "headings": [], "roles_unresolved": []}
    refs = defaultdict(list)
    objects = defaultdict(list)
    elements = {}
    if not _dict(root):
        return data, refs, objects, elements, {}
    rolemap = root.get("/RoleMap", {})
    counts = Counter()
    seen = set()

    def role(name):
        visited = set()
        while _dict(rolemap) and name in rolemap:
            if name in visited:
                data["errors"].append(f"RoleMap cycle at {name}")
                return name
            visited.add(name)
            name = _str(rolemap[name])
        return name

    def walk(node, page=None, owner=None, depth=0):
        if depth > 200:
            data["errors"].append("Structure exceeds traversal depth 200")
            return
        if _array(node):
            for child in node:
                walk(child, page, owner, depth + 1)
            return
        if isinstance(node, int):
            key = (page, "page", node)
            refs[key].append(owner)
            data["references"].append({"page": page, "stream": "page", "mcid": node, "element": owner})
            if page is None:
                data["errors"].append("Integer MCID has no resolvable /Pg")
            return
        if not _dict(node):
            if node is not None:
                data["errors"].append("Unexpected non-object /K child")
            return
        page = page_numbers.get(_id(node.get("/Pg")), page) if "/Pg" in node else page
        kind = _str(node.get("/Type"))
        if kind == "/MCR" or "/MCID" in node:
            try:
                mcid = int(node["/MCID"])
                stream = _id(node["/Stm"]) if "/Stm" in node else "page"
                key = (page, stream, mcid)
                refs[key].append(owner)
                data["references"].append({"page": page, "stream": stream, "mcid": mcid, "element": owner})
                if page is None:
                    data["errors"].append("MCR has no resolvable /Pg")
            except (KeyError, TypeError, ValueError):
                data["errors"].append("Invalid /MCR /MCID")
            return
        if kind == "/OBJR":
            target = node.get("/Obj")
            target_id = _id(target)
            objects[target_id].append(owner)
            data["object_references"].append({"page": page, "object": target_id, "element": owner})
            if target is None:
                data["errors"].append("OBJR missing /Obj")
            return
        ident = _id(node)
        if ident in seen:
            data["errors"].append(f"Repeated structure element/cycle {ident}")
            return
        seen.add(ident)
        if "/S" in node:
            resolved = role(_str(node["/S"]))
            counts[resolved] += 1
            elements[ident] = node
            owner = ident
            if resolved == "/Figure":
                alt = _str(node.get("/Alt")).strip()
                data["figures"].append({"element": ident, "page": page, "alt": alt,
                                        "status": "fail" if not alt else "needs-review",
                                        "placeholder_signal": bool(PLACEHOLDER.search(alt))})
            if resolved == "/TH":
                attrs = node.get("/A", [])
                attrs = list(attrs) if _array(attrs) else [attrs]
                scope = [_str(item.get("/Scope")) for item in attrs if _dict(item) and "/Scope" in item]
                headers = []
                for item in attrs:
                    if _dict(item) and "/Headers" in item:
                        value = item["/Headers"]
                        headers.extend(_str(v) for v in value) if _array(value) else headers.append(_str(value))
                data["table_headers"].append({"element": ident, "page": page, "scope": scope,
                                             "headers": headers, "id": _str(node.get("/ID")),
                                             "status": "needs-review"})
            if re.fullmatch(r"/H[1-6]?", resolved):
                data["headings"].append({"role": resolved, "element": ident, "page": page})
        walk(node.get("/K"), page, owner, depth + 1)

    walk(root)
    data["tag_counts"] = dict(sorted(counts.items()))
    parent_tree = _number_tree(root.get("/ParentTree"), data["errors"])
    return data, refs, objects, elements, parent_tree


def _font(font, key):
    subtype = _str(font.get("/Subtype"))
    base = _str(font.get("/BaseFont")).lstrip("/")
    descendants = font.get("/DescendantFonts", [])
    actual = descendants[0] if len(descendants) else font
    descriptor = actual.get("/FontDescriptor", {})
    embedded = any(name in descriptor for name in ("/FontFile", "/FontFile2", "/FontFile3"))
    if subtype == "/Type3":
        embedded = bool(font.get("/CharProcs"))
    mapping = font.get("/ToUnicode")
    mapping_evidence = "No /ToUnicode; alternate mapping or ActualText requires review"
    mapping_status = "needs-review"
    if isinstance(mapping, pikepdf.Stream):
        try:
            raw = mapping.read_bytes()
            if b"begincmap" in raw and b"endcmap" in raw and any(op in raw for op in (b"beginbfchar", b"beginbfrange", b"usecmap")):
                mapping_evidence = "Nonempty /ToUnicode CMap; used-code coverage not tested"
            else:
                mapping_evidence = "/ToUnicode lacks recognizable CMap mapping operators"
                mapping_status = "fail"
        except Exception as exc:
            mapping_evidence = f"Unreadable /ToUnicode: {type(exc).__name__}"
            mapping_status = "error"
    elif mapping is not None:
        mapping_evidence = "Invalid non-stream /ToUnicode"
        mapping_status = "fail"
    elif base in STANDARD14:
        mapping_evidence = "Standard font; standard encoding/glyph-name mapping requires review"
    return {"object": key, "base_font": base, "subtype": subtype,
            "encoding": _str(font.get("/Encoding"))[:300],
            "embedded": embedded, "embedding_status": "pass" if embedded else "fail",
            "mapping_status": mapping_status, "mapping_evidence": mapping_evidence,
            "glyph_coverage_status": "not-tested", "used_text_operations": 0}


def _page_content(page, page_index, refs, parent_tree, font_map):
    """Resolve page/Form marking and count paints, including unmarked paints.

    Inherited outer page marking covers a Form only when the Form does not supply
    its own marking. Reused Forms and undecodable streams remain visible.
    """
    counts = Counter()
    definitions = Counter()
    painted = Counter()
    errors = []
    warnings = []
    images = set()
    stream_parents = {"page": page.obj.get("/StructParents")}
    active_forms = set()
    visited_forms = Counter()
    marked_operator_counts = Counter()

    def scan(target, resources, stream="page", inherited=(), inherited_font=None):
        local = list(inherited)
        initial_depth = len(local)
        current_font = inherited_font
        font_stack = []
        try:
            instructions = pikepdf.parse_content_stream(target)
            for instruction_index, instruction in enumerate(instructions):
                operands, operator = instruction
                op = str(operator)
                if op == "Tf" and operands:
                    current_font = resources.get("/Font", {}).get(_str(operands[0]))
                    if not _dict(current_font):
                        errors.append(f"Unresolved text font {_str(operands[0])} in {stream}")
                    continue
                if op == "q":
                    font_stack.append(current_font)
                elif op == "Q":
                    current_font = font_stack.pop() if font_stack else None
                if op in ("BDC", "BMC"):
                    tag = _str(operands[0]) if operands else ""
                    props = operands[1] if len(operands) > 1 else None
                    if isinstance(props, pikepdf.Name):
                        properties = resources.get("/Properties", {})
                        props = properties.get(_str(props))
                        if props is None:
                            errors.append(f"Unresolved named property in {stream}")
                    mcid = None
                    if _dict(props) and "/MCID" in props:
                        try:
                            mcid = int(props["/MCID"])
                            definitions[(page_index, stream, mcid)] += 1
                        except (ValueError, TypeError):
                            errors.append("Noninteger marked-content /MCID")
                    local.append({"artifact": tag == "/Artifact", "key": (page_index, stream, mcid) if mcid is not None else None})
                    continue
                if op == "EMC":
                    if len(local) <= initial_depth:
                        errors.append(f"Unbalanced EMC in {stream}")
                    else:
                        local.pop()
                    continue
                if op == "Do" and operands:
                    xobject = resources.get("/XObject", {}).get(_str(operands[0]))
                    if isinstance(xobject, pikepdf.Stream) and xobject.get("/Subtype") == pikepdf.Name.Form:
                        ident = _id(xobject)
                        if ident in active_forms:
                            errors.append(f"Recursive Form XObject {ident}")
                            continue
                        visited_forms[ident] += 1
                        if visited_forms[ident] > 1:
                            warnings.append(f"Reused Form {ident}: occurrence semantics require review")
                        stream_parents[ident] = xobject.get("/StructParents")
                        active_forms.add(ident)
                        scan(xobject, xobject.get("/Resources", resources), ident, tuple(local), current_font)
                        active_forms.remove(ident)
                        continue
                    if isinstance(xobject, pikepdf.Stream) and xobject.get("/Subtype") == pikepdf.Name.Image:
                        images.add(_id(xobject))
                        counts["image_paints"] += 1
                    elif xobject is None:
                        errors.append(f"Unresolved XObject {_str(operands[0])}")
                if op in ("BI", "INLINE IMAGE"):
                    images.add(f"inline:{stream}:{instruction_index}")
                    counts["image_paints"] += 1
                if op not in PAINT:
                    continue
                # Empty text-showing operators do not paint semantic content.
                if op in {"Tj", "TJ", "'", '"'}:
                    if not any(str(v) for v in operands):
                        continue
                    counts["text_paints"] += 1
                    if _dict(current_font):
                        ident = _id(current_font)
                        font_map.setdefault(ident, _font(current_font, ident))["used_text_operations"] += 1
                    else:
                        errors.append(f"Text paint has no resolved font in {stream}")
                elif op != "Do" and op not in ("BI", "INLINE IMAGE"):
                    counts["vector_or_shading_paints"] += 1
                counts["paint_operations"] += 1
                if any(item["artifact"] for item in local):
                    counts["artifact_paints"] += 1
                    continue
                key = next((item["key"] for item in reversed(local) if item["key"] is not None), None)
                if key is None:
                    counts["uncovered_paints"] += 1
                else:
                    painted[key] += 1
                    if key in refs and len(refs[key]) == 1:
                        counts["linked_paints"] += 1
                    else:
                        counts["uncovered_paints"] += 1
                        marked_operator_counts["orphan_or_ambiguous_mcid_paints"] += 1
            if len(local) != initial_depth:
                errors.append(f"Unclosed marked-content sequence in {stream}")
        except Exception as exc:
            errors.append(f"Cannot parse {stream}: {type(exc).__name__}: {str(exc)[:180]}")
        for font in resources.get("/Font", {}).values():
            if _dict(font):
                font_map.setdefault(_id(font), _font(font, _id(font)))

    scan(page, page.resources)
    parent_failures = []
    for key in definitions:
        _, stream, mcid = key
        if key not in refs:
            parent_failures.append({"stream": stream, "mcid": mcid, "reason": "No structure reference"})
            continue
        struct_parent = stream_parents.get(stream)
        if struct_parent is None:
            parent_failures.append({"stream": stream, "mcid": mcid, "reason": "Missing /StructParents"})
            continue
        parent_values = parent_tree.get(int(struct_parent))
        expected = refs[key]
        actual = parent_values[mcid] if _array(parent_values) and 0 <= mcid < len(parent_values) else None
        if len(expected) != 1 or actual is None or _id(actual) != expected[0]:
            parent_failures.append({"stream": stream, "mcid": mcid, "reason": "ParentTree does not point to owning structure element"})
    # Definitions are syntactic sequences. Repeated form invocation is not a second
    # definition, so duplicate counts for reused forms are separately reviewed.
    duplicate_mcids = [{"stream": key[1], "mcid": key[2], "definitions": number}
                       for key, number in definitions.items()
                       if number > (visited_forms[key[1]] if key[1] != "page" else 1)]
    return {"counts": dict(counts), "marked_content_sequences": len(definitions),
            "image_objects": len(images), "parent_tree_failures": parent_failures,
            "duplicate_mcids": duplicate_mcids, "errors": errors,
            "warnings": sorted(set(warnings)), "orphan_mcid_paints": sum(marked_operator_counts.values())}, definitions, painted


def inspect_pdf(path):
    """Return bounded structural, preservation and feature evidence for one PDF."""
    path = Path(path).resolve()
    report = {"schema_version": SCHEMA_VERSION, "path": str(path), "sha256": None,
              "status": "error", "checks": [], "limitations": [
                  "Supplemental evidence only: no complete PDF/UA or WCAG claim.",
                  "Content coverage counts paint operators, not glyphs, words, area, semantic correctness or contrast.",
                  "scanned/mixed classification infers image-containing pages; photographs cannot be distinguished from scanned text automatically.",
                  "Glyph coverage, language appropriateness, alt-text meaning and reading order require separate assessment."]}
    try:
        report["sha256"] = _sha(path)
        with pikepdf.open(path) as pdf:
            page_numbers = {_id(page.obj): index + 1 for index, page in enumerate(pdf.pages)}
            structure, refs, objrefs, elements, parent_tree = _structure(pdf, page_numbers)
            fonts = {}
            pages = []
            all_definitions = set()
            pdfium_doc = pdfium.PdfDocument(str(path))
            try:
                for index, page in enumerate(pdf.pages, 1):
                    content, definitions, painted = _page_content(page, index, refs, parent_tree, fonts)
                    all_definitions.update(definitions)
                    render_page = pdfium_doc[index - 1]
                    text_page = render_page.get_textpage()
                    try:
                        text = text_page.get_text_range()
                    finally:
                        text_page.close()
                        render_page.close()
                    digital_text = bool(text.strip())
                    images = content["image_objects"] > 0
                    classification = "mixed" if digital_text and images else "text" if digital_text else "scanned" if images else "blank"
                    if not digital_text and not images and content["counts"].get("paint_operations", 0):
                        content["warnings"].append("No extracted text/image but vector or text painting exists; blank classification is uncertain")
                    pages.append({"page": index, "class": classification,
                                  "classification_status": "needs-review" if images or content["warnings"] else "pass",
                                  "text_characters": len(text), "mediabox": [float(v) for v in page.mediabox],
                                  "cropbox": [float(v) for v in page.cropbox], "rotation": int(page.obj.get("/Rotate", 0)),
                                  "content": content, "annotations": _annotations(page, page_numbers)})
            finally:
                pdfium_doc.close()
            phantom = [{"page": key[0], "stream": key[1], "mcid": key[2], "owners": owners}
                       for key, owners in refs.items() if key not in all_definitions]
            structure["missing_content_references"] = phantom
            structure["ambiguous_content_references"] = [{"page": k[0], "stream": k[1], "mcid": k[2], "owners": v} for k, v in refs.items() if len(v) != 1]
            # A partially linked tree with dangling children is broken in a
            # narrower way than a wholly phantom tree. Keep both facts visible.
            matched_refs = sum(key in all_definitions for key in refs)
            indirect_objects = {_id(obj) for obj in pdf.objects}
            existing_obj_targets = sum(key in indirect_objects for key in objrefs)
            structure["content_reference_counts"] = {"declared_unique": len(refs), "matched_definitions": matched_refs,
                                                      "unresolved": len(phantom), "ambiguous": len(structure["ambiguous_content_references"])}
            structure["object_reference_counts"] = {"declared_unique": len(objrefs), "existing_indirect_targets": existing_obj_targets}
            has_payload = any(p["content"]["counts"].get("paint_operations", 0) or p["annotations"] for p in pages)
            has_tree = bool(sum(structure["tag_counts"].values()))
            structure["phantom_tree"] = bool(has_tree and not matched_refs and not existing_obj_targets and (refs or objrefs or has_payload))
            structure["linkage_class"] = ("no-structure" if not structure["present"] else "phantom-tree" if structure["phantom_tree"] else "partially-unresolved" if phantom else "linked" if refs or objrefs else "empty-tree")
            metadata = {"title": _str(pdf.docinfo.get("/Title")), "language": _str(pdf.Root.get("/Lang")),
                        "display_doc_title": bool(pdf.Root.get("/ViewerPreferences", {}).get("/DisplayDocTitle", False)),
                        "xmp_present": "/Metadata" in pdf.Root, "mark_info_marked": bool(pdf.Root.get("/MarkInfo", {}).get("/Marked", False))}
            navigation = _navigation(pdf, page_numbers)
            acroform = pdf.Root.get("/AcroForm", {})
            signed = bool(acroform.get("/SigFlags", 0)) or any(_dict(obj) and obj.get("/Type") == pikepdf.Name.Sig for obj in pdf.objects)
            features = {"encrypted": bool(pdf.is_encrypted), "signed_or_signature_fields": signed,
                        "forms": bool(acroform.get("/Fields", [])),
                        "attachments": bool(pdf.Root.get("/Names", {}).get("/EmbeddedFiles")) or "/AF" in pdf.Root,
                        "javascript": bool(pdf.Root.get("/Names", {}).get("/JavaScript")),
                        "optional_content": "/OCProperties" in pdf.Root,
                        "equation_tags": structure["tag_counts"].get("/Formula", 0),
                        "annotation_count": sum(len(p["annotations"]) for p in pages),
                        "pdf_version": str(pdf.pdf_version)}
            checks = report["checks"]
            parse_errors = [e for p in pages for e in p["content"]["errors"]] + structure["errors"]
            linkage_failures = sum(len(p["content"]["parent_tree_failures"]) + len(p["content"]["duplicate_mcids"]) for p in pages)
            uncovered = sum(p["content"]["counts"].get("uncovered_paints", 0) for p in pages)
            total = sum(p["content"]["counts"].get("paint_operations", 0) for p in pages)
            integrity_status = "error" if parse_errors else "fail" if phantom or structure["phantom_tree"] or structure["ambiguous_content_references"] or linkage_failures else "pass"
            checks.append(_check("content-linkage", integrity_status, {"phantom_tree": structure["phantom_tree"], "linkage_class": structure["linkage_class"], "missing_references": len(phantom), "matched_content_definitions": matched_refs, "existing_object_targets": existing_obj_targets, "parent_or_duplicate_failures": linkage_failures, "parse_errors": parse_errors}, "Parsed page and Form content; MCID->structure and ParentTree back-links", ["Matched definitions count actual MCID sequences; existing OBJR targets count object existence, with Link ParentTree linkage assessed separately. A partial dangling-reference defect is not a wholly phantom tree."]))
            checks.append(_check("content-coverage", "error" if parse_errors else "fail" if uncovered else "pass" if total else "not-applicable", {"paint_operations": total, "uncovered_paints": uncovered}, "Every parsed text/image/vector/shading paint operator", ["Artifacts are counted separately; their semantic correctness requires review."]))
            annotation_failures = []
            for page in pages:
                for annotation in page["annotations"]:
                    if annotation["subtype"] != "/Link":
                        continue
                    owners = objrefs.get(annotation["object"], [])
                    parent = parent_tree.get(annotation["struct_parent"])
                    if len(owners) != 1 or parent is None or _id(parent) != owners[0]:
                        annotation_failures.append({"page": page["page"], "object": annotation["object"]})
            checks.append(_check("link-structure", "fail" if annotation_failures else "pass" if any(a["subtype"] == "/Link" for p in pages for a in p["annotations"]) else "not-applicable", {"unlinked_links": annotation_failures}, "Link annotation OBJR and /StructParent linkage", ["Link purpose, activation and accessible name are not assessed."]))
            checks.append(_check("metadata", "pass" if metadata["title"].strip() and metadata["language"].strip() and metadata["display_doc_title"] else "fail", metadata, "Presence of title/language and document-title display", ["Meaningful title and appropriate language require review; XMP conformance is delegated to veraPDF."]))
            figures = structure["figures"]
            checks.append(_check("figure-alternatives", "fail" if any(not f["alt"] for f in figures) else "needs-review" if figures else "not-applicable", {"figure_count": len(figures), "missing_alt": sum(not f["alt"] for f in figures), "placeholder_signals": sum(f["placeholder_signal"] for f in figures)}, "Tagged /Figure elements only", ["A plausible alternative is not proof of adequate description; untagged image semantics remain unknown."]))
            headers = structure["table_headers"]
            checks.append(_check("table-header-associations", "needs-review" if headers or structure["tag_counts"].get("/Table") else "not-applicable", {"headers": headers, "tables": structure["tag_counts"].get("/Table", 0)}, "Inventory /TH Scope and Headers/ID evidence", ["Header associations may use TD Headers referencing TH ID; complete relationship validation is not implemented."]))
            used_fonts = [f for f in fonts.values() if f["used_text_operations"]]
            checks.append(_check("font-embedding", "error" if parse_errors else "fail" if any(not f["embedded"] for f in used_fonts) else "pass" if used_fonts else "not-applicable", {"font_resource_count": len(fonts), "used_font_count": len(used_fonts), "unused_font_count": len(fonts) - len(used_fonts), "unembedded_used": [f["base_font"] for f in used_fonts if not f["embedded"]]}, "Fonts selected at parsed text-showing operators in pages and traversed Form XObjects", ["Unused font resources are inventoried but do not fail embedding. Annotation appearance, pattern and Type3 CharProc fonts, embedding permissions, glyph coverage, widths and damaged programs are not tested."]))
            checks.append(_check("font-unicode-mapping", _aggregate([{"status": f["mapping_status"]} for f in used_fonts]) if used_fonts else "not-applicable", {"fonts": list(fonts.values())}, "ToUnicode CMap shape and alternative mapping signals for fonts used at text-showing operators", ["Absence of ToUnicode alone is not failure; used-code coverage is not tested."]))
            checks.append(_check("heading-navigation", "fail" if navigation["errors"] else "needs-review", {"headings": structure["headings"], "bookmark_count": len(navigation["bookmarks"]), "navigation_errors": navigation["errors"]}, "Heading/bookmark inventory", ["Heading purpose, hierarchy and navigation adequacy require review."]))
            special = {k: features[k] for k in ("forms", "attachments", "signed_or_signature_fields", "javascript", "optional_content", "equation_tags") if features[k]}
            checks.append(_check("special-features", "needs-review" if special else "not-applicable", special, "Catalog feature signals and /Formula tag inventory", ["Untagged visual equations and slide-like layouts cannot be reliably detected from this inventory."]))
            checks.append(_check("reading-order", "not-tested", {}, "No semantic reading-order test"))
            checks.append(_check("contrast", "not-tested", {}, "No foreground/background color sampling"))
            report.update({"page_count": len(pages), "pages": pages, "structure": structure,
                           "fonts": list(fonts.values()), "metadata": metadata, "navigation": navigation,
                           "features": features, "status": _aggregate(checks),
                           "tools": {"pikepdf": version("pikepdf"), "pypdfium2": version("pypdfium2")}})
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        report["checks"].append(_check("document-open", "error", report["error"], "PDF parsing"))
    return report


def _tokens(text):
    return re.findall(r"\w+|[^\w\s]", unicodedata.normalize("NFKC", text), re.UNICODE)


def _resolve_destination(destination, navigation):
    """Resolve local named destinations without changing document content."""
    names = {str(key).lstrip("/"): value for key, value in navigation["named_destinations"]}
    seen = set()
    while isinstance(destination, str) and destination:
        name = destination.lstrip("/")
        if name in seen or name not in names:
            return destination
        seen.add(name)
        destination = names[name]
    return destination


def _target_status(record, navigation, page_count, group=False):
    destination = _resolve_destination(record.get("destination", ""), navigation)
    action = record.get("action", "")
    if action == "/URI":
        return "pass" if re.match(r"^[a-z][a-z0-9+.-]*:", record.get("uri", ""), re.I) else "needs-review"
    if action not in ("", "/GoTo"):
        return "needs-review"
    if isinstance(destination, list):
        return "pass" if len(destination) >= 2 and isinstance(destination[0], int) and 1 <= destination[0] <= page_count and destination[1] in ("/XYZ", "/Fit", "/FitH", "/FitV", "/FitR", "/FitB", "/FitBH", "/FitBV") else "fail"
    return "pass" if group and not destination else "needs-review"


def _preserve_bookmarks(before_nav, after_nav, before_count, after_count):
    before, after = before_nav["bookmarks"], after_nav["bookmarks"]
    def normalize(item, nav):
        return {**item, "destination": _resolve_destination(item["destination"], nav),
                "action": "" if item["action"] == "/GoTo" else item["action"]}
    normalized_after = [normalize(item, after_nav) for item in after]
    matched = set()
    missing = []
    cursor = 0
    for item in before:
        normalized = normalize(item, before_nav)
        found = next((i for i in range(cursor, len(after)) if normalized_after[i] == normalized), None)
        if found is None:
            missing.append(item)
        else:
            matched.add(found)
            cursor = found + 1
    added = [item for i, item in enumerate(after) if i not in matched]
    target_statuses = []
    for i, item in enumerate(after):
        is_group = i + 1 < len(after) and after[i + 1]["depth"] > item["depth"]
        target_statuses.append(_target_status(item, after_nav, after_count, is_group))
    status = "fail" if missing or "fail" in target_statuses else "needs-review" if "needs-review" in target_statuses else "pass"
    return _check("bookmarks-preservation", status, {"before_count": len(before), "after_count": len(after), "missing_or_changed": missing, "added": added, "target_statuses": target_statuses}, "Existing bookmark sequence, hierarchy, titles and resolved targets; additions may be present", ["Added bookmark meaning and navigation adequacy remain human-review items."])


def _preserve_named_destinations(before_nav, after_nav, page_count):
    before = dict(before_nav["named_destinations"])
    after = dict(after_nav["named_destinations"])
    missing = [name for name, dest in before.items() if name not in after or _resolve_destination(dest, before_nav) != _resolve_destination(after[name], after_nav)]
    added = [name for name in after if name not in before]
    statuses = {name: _target_status({"destination": dest}, after_nav, page_count) for name, dest in after.items()}
    status = "fail" if missing or "fail" in statuses.values() else "needs-review" if "needs-review" in statuses.values() else "pass"
    return _check("named_destinations-preservation", status, {"before_count": len(before), "after_count": len(after), "missing_or_changed": missing, "added": added, "target_statuses": statuses}, "Existing named-destination names and resolved local page targets; additions may be present")


def _logical_labels(navigation, page_count):
    definitions = {item["index"]: item for item in navigation["page_labels"]}
    current = {"index": 0, "style": "/D", "prefix": "", "start": 1}
    labels = []
    for index in range(page_count):
        current = definitions.get(index, current)
        number = current["start"] + index - current["index"]
        style = current["style"]
        if number <= 0 and style:
            return None
        if style == "/D":
            suffix = str(number)
        elif style in ("/A", "/a"):
            suffix = chr(ord("A") + (number - 1) % 26) * ((number - 1) // 26 + 1)
            suffix = suffix.lower() if style == "/a" else suffix
        elif style in ("/R", "/r"):
            suffix, remainder = "", number
            if number > 10000:
                return None
            for value, symbol in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
                count, remainder = divmod(remainder, value)
                suffix += symbol * count
            suffix = suffix.lower() if style == "/r" else suffix
        elif style == "":
            suffix = ""
        else:
            return None
        labels.append(current["prefix"] + suffix)
    return labels


def _preserve_annotations(before, after, before_navigation, navigation, page_count):
    def core(item, nav):
        result = {k: v for k, v in item.items() if k not in {"object", "struct_parent", "contents"}}
        result["destination"] = _resolve_destination(result["destination"], nav)
        result["action"] = "" if result["action"] == "/GoTo" else result["action"]
        return result
    matched = set()
    missing = []
    enriched = []
    # Match nonempty original descriptions first so a generic source annotation
    # does not consume the sole candidate with an established description.
    for original in sorted(before, key=lambda item: not bool(item["contents"])):
        match = next((i for i, item in enumerate(after) if i not in matched and core(item, navigation) == core(original, before_navigation) and (not original["contents"] or item["contents"] == original["contents"])), None)
        if match is None:
            missing.append(original["object"])
            continue
        matched.add(match)
        if not original["contents"] and after[match]["contents"]:
            enriched.append({"before_object": original["object"], "after_object": after[match]["object"], "contents": after[match]["contents"], "review_status": "needs-review"})
    added = [item for i, item in enumerate(after) if i not in matched]
    target_statuses = [_target_status(item, navigation, page_count) if item["subtype"] == "/Link" else "needs-review" for item in added]
    status = "fail" if missing or "fail" in target_statuses else "needs-review" if "needs-review" in target_statuses else "pass"
    return {"status": status, "missing_or_changed": missing, "added": added, "empty_contents_enriched": enriched, "added_target_statuses": target_statuses}


def compare_fidelity(before, after, dpi=96, max_changed_fraction=0.0, pixel_delta=0):
    """Compare every page with one PDFium RGB renderer and independent text data.

    Defaults require exact equality.  A tolerance is explicit and never inferred
    from a result. The report retains unthresholded deltas, including all pixels.
    """
    if dpi <= 0 or not 0 <= max_changed_fraction <= 1 or not 0 <= pixel_delta <= 255:
        raise ValueError("Invalid render settings or preservation thresholds")
    before, after = Path(before).resolve(), Path(after).resolve()
    report = {"schema_version": SCHEMA_VERSION, "before_sha256": None, "after_sha256": None,
              "status": "error", "pages": [], "checks": [],
              "renderer": {"name": "PDFium", "pypdfium2": version("pypdfium2"), "pdfium": str(pdfium.version.PDFIUM_INFO),
                           "dpi": dpi, "colorspace": "RGB", "background": "white", "annotations": True,
                           "rotation": "intrinsic PDF page rotation", "all_pages": True},
              "thresholds": {"pixel_delta": pixel_delta, "max_changed_fraction": max_changed_fraction},
              "limitations": ["Equal rendering does not establish semantic accessibility or OCR accuracy.",
                              "Text comparison uses independent PDFium extraction and NFKC token normalization; whitespace is ignored.",
                              "Annotation comparison covers common usability fields, not all PDF annotation dictionaries or embedded file payloads."]}
    try:
        report["before_sha256"] = _sha(before)
        report["after_sha256"] = _sha(after)
        baseline = inspect_pdf(before)
        candidate = inspect_pdf(after)
        if "error" in baseline or "error" in candidate:
            raise ValueError(f"PDF inspection failed: {baseline.get('error') or candidate.get('error')}")
        documents = [pdfium.PdfDocument(str(p)) for p in (before, after)]
        try:
            same_count = len(documents[0]) == len(documents[1])
            report["checks"].append(_check("page-count", "pass" if same_count else "fail", {"before": len(documents[0]), "after": len(documents[1])}, "Whole document"))
            before_all, after_all = [], []
            for index in range(min(len(documents[0]), len(documents[1]))):
                pages = [doc[index] for doc in documents]
                images = []
                text_tokens = []
                sizes = [list(page.get_size()) for page in pages]
                try:
                    for page in pages:
                        text_page = page.get_textpage()
                        try:
                            text_tokens.append(_tokens(text_page.get_text_range()))
                        finally:
                            text_page.close()
                        bitmap = page.render(scale=dpi / 72, fill_color=(255, 255, 255, 255), grayscale=False, draw_annots=True)
                        try:
                            images.append(bitmap.to_pil().convert("RGB"))
                        finally:
                            bitmap.close()
                    before_all.extend(text_tokens[0])
                    after_all.extend(text_tokens[1])
                    equal_size = images[0].size == images[1].size and sizes[0] == sizes[1]
                    evidence = {"page": index + 1, "dimensions_before": sizes[0], "dimensions_after": sizes[1],
                                "pixel_dimensions_before": list(images[0].size), "pixel_dimensions_after": list(images[1].size),
                                "dimensions_status": "pass" if equal_size else "fail"}
                    if equal_size:
                        difference = ImageChops.difference(*images)
                        channels = difference.split()
                        maximum_channel = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
                        hist = maximum_channel.histogram()
                        pixels = images[0].width * images[0].height
                        changed = sum(hist[pixel_delta + 1:])
                        histogram = difference.histogram()
                        total_delta = sum((i % 256) * n for i, n in enumerate(histogram))
                        mask = maximum_channel.point(lambda value: 255 if value > pixel_delta else 0)
                        evidence.update({"changed_pixel_fraction": changed / pixels, "any_delta_pixel_fraction": 1 - hist[0] / pixels,
                                         "max_channel_delta": max(v[1] for v in difference.getextrema()),
                                         "mean_absolute_channel_delta": total_delta / (pixels * 3),
                                         "changed_bbox_pixels": list(mask.getbbox()) if mask.getbbox() else None,
                                         "render_status": "pass" if changed / pixels <= max_changed_fraction else "fail"})
                    else:
                        evidence["render_status"] = "fail"
                    counts = [Counter(tokens) for tokens in text_tokens]
                    evidence["text"] = {"multiset_status": "pass" if counts[0] == counts[1] else "fail",
                                        "ordered_status": "pass" if text_tokens[0] == text_tokens[1] else "needs-review",
                                        "removed_tokens": sum((counts[0] - counts[1]).values()), "added_tokens": sum((counts[1] - counts[0]).values()),
                                        "tokens_before": len(text_tokens[0]), "tokens_after": len(text_tokens[1])}
                    # Keep page-box changes visible even when the effective raster agrees.
                    page_before, page_after = baseline["pages"][index], candidate["pages"][index]
                    boxes_equal = all(page_before[k] == page_after[k] for k in ("mediabox", "cropbox", "rotation"))
                    evidence["page_boxes_status"] = "pass" if boxes_equal else "fail"
                    evidence["annotations"] = _preserve_annotations(page_before["annotations"], page_after["annotations"], baseline["navigation"], candidate["navigation"], candidate["page_count"])
                    evidence["annotations_status"] = evidence["annotations"]["status"]
                    evidence["status"] = _aggregate([{"status": evidence[key]} for key in ("render_status", "dimensions_status", "page_boxes_status", "annotations_status")] + [{"status": "pass" if counts[0] == counts[1] else "fail"}])
                    report["pages"].append(evidence)
                finally:
                    for image in images:
                        image.close()
                    for page in pages:
                        page.close()
            counts = [Counter(before_all), Counter(after_all)]
            report["text"] = {"multiset_status": "pass" if same_count and counts[0] == counts[1] else "fail",
                              "ordered_status": "pass" if same_count and before_all == after_all else "needs-review",
                              "removed_tokens": sum((counts[0] - counts[1]).values()), "added_tokens": sum((counts[1] - counts[0]).values())}
            page_status = _aggregate([{"status": p["status"]} for p in report["pages"]]) if same_count else "fail"
            report["checks"].append(_check("all-page-render-and-content", page_status, {"compared_pages": len(report["pages"]), "expected_pages": baseline["page_count"]}, "Every page at the declared renderer settings and thresholds"))
            report["checks"].append(_preserve_bookmarks(baseline["navigation"], candidate["navigation"], baseline["page_count"], candidate["page_count"]))
            report["checks"].append(_preserve_named_destinations(baseline["navigation"], candidate["navigation"], candidate["page_count"]))
            before_labels = _logical_labels(baseline["navigation"], baseline["page_count"])
            after_labels = _logical_labels(candidate["navigation"], candidate["page_count"])
            labels_status = "needs-review" if before_labels is None or after_labels is None else "pass" if before_labels == after_labels else "fail"
            report["checks"].append(_check("page_labels-preservation", labels_status, {"before_count": len(baseline["navigation"]["page_labels"]), "after_count": len(candidate["navigation"]["page_labels"]), "logical_labels_equal": before_labels == after_labels if before_labels is not None and after_labels is not None else None}, "Logical label on every page, including default numeric labels"))
            feature_keys = ("forms", "attachments", "signed_or_signature_fields", "javascript", "optional_content")
            changed_features = {key: {"before": baseline["features"][key], "after": candidate["features"][key]} for key in feature_keys if baseline["features"][key] != candidate["features"][key]}
            report["checks"].append(_check("special-features-preservation", "fail" if changed_features else "pass", changed_features, "Presence of catalog feature flags", ["Equal presence does not establish preservation of embedded payloads, scripts, signatures or form semantics."]))
            report["status"] = _aggregate(report["checks"])
        finally:
            for document in documents:
                document.close()
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        report["checks"].append(_check("fidelity-execution", "error", report["error"], "Comparison"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("inspect")
    one.add_argument("input")
    two = sub.add_parser("compare")
    two.add_argument("before")
    two.add_argument("after")
    two.add_argument("--dpi", type=int, default=96)
    two.add_argument("--max-changed-fraction", type=float, default=0.0)
    two.add_argument("--pixel-delta", type=int, default=0)
    for command in (one, two):
        command.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect_pdf(args.input) if args.command == "inspect" else compare_fidelity(args.before, args.after, args.dpi, args.max_changed_fraction, args.pixel_delta)
    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return 2 if result["status"] == "error" else 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
