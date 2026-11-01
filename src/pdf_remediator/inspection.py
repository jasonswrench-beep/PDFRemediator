"""Read-only PDF evidence, promoted from our independently tested Phase 0 evaluator.

This is a supplemental evaluator, not a PDF/UA or WCAG validator.  Paint
operators are the denominator for coverage, not glyphs, words or visual area.
The strict validator and human semantic review remain separate assessments.
"""
from __future__ import annotations

import argparse
import copy
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

import pikepdf
import pypdfium2 as pdfium
from PIL import ImageChops

from .process import cancelled

SCHEMA_VERSION = "phase1-metrics-1.0"
FORM_RENDERING_POLICY = 'supported-static-widget-rendering-1'
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


def _resolved_owner_role(node, rolemap):
    if not _dict(node) or not isinstance(node.get("/S"), pikepdf.Name):
        return ""
    name = str(node["/S"])
    seen = set()
    while _dict(rolemap) and name in rolemap:
        if name in seen:
            return ""
        seen.add(name)
        if not isinstance(rolemap[name], pikepdf.Name):
            return ""
        name = _str(rolemap[name])
    return name


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
            "figures": [], "table_headers": [], "table_cells": [], "tables": [],
            "errors": [], "headings": [], "roles_unresolved": []}
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

    def walk(node, page=None, owner=None, depth=0, table=None):
        if depth > 200:
            data["errors"].append("Structure exceeds traversal depth 200")
            return
        if _array(node):
            for child in node:
                walk(child, page, owner, depth + 1, table)
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
            if resolved == "/Table":
                table = ident
                data["tables"].append({"element": ident, "page": page})
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
            if resolved in ("/TH", "/TD"):
                attrs = node.get("/A", [])
                attrs = list(attrs) if _array(attrs) else [attrs]
                scopes, headers, row_spans, col_spans = [], [], [], []
                for attr in attrs:
                    if not _dict(attr):
                        continue
                    if "/Scope" in attr:
                        scopes.append(_str(attr["/Scope"]))
                    if "/Headers" in attr:
                        value = attr["/Headers"]
                        headers.extend(_str(item) for item in value) if _array(value) else headers.append(_str(value))
                    if "/RowSpan" in attr:
                        row_spans.append(int(attr["/RowSpan"]))
                    if "/ColSpan" in attr:
                        col_spans.append(int(attr["/ColSpan"]))
                data["table_cells"].append({"element": ident, "table": table, "role": resolved,
                                             "page": page, "scope": scopes, "headers": headers,
                                             "id": _str(node.get("/ID")), "row_spans": row_spans,
                                             "col_spans": col_spans})
            if re.fullmatch(r"/H(?:[0-9]+)?", resolved):
                data["headings"].append({"role": resolved, "element": ident, "page": page})
        walk(node.get("/K"), page, owner, depth + 1, table)

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
    language_override_signals = []

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
                    if _dict(props) and "/Lang" in props:
                        language_override_signals.append({"stream": stream, "mcid": mcid, "kind": "inline-language"})
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
    if not errors:
        # An explicit zero is proof of a completed inventory, not a missing
        # measurement that selective OCR may treat as permission to replace text.
        counts.setdefault("text_paints", 0)
    return {"counts": dict(counts), "marked_content_sequences": len(definitions),
            "image_objects": len(images), "parent_tree_failures": parent_failures,
            "duplicate_mcids": duplicate_mcids, "errors": errors,
            "warnings": sorted(set(warnings)), "orphan_mcid_paints": sum(marked_operator_counts.values()),
            **({"language_override_signals": language_override_signals} if language_override_signals else {})}, definitions, painted


TABLE_RELATIONSHIP_POLICY = "bounded-table-relationships-1"


def _table_relationships(pdf, page_numbers, cancel=None):
    """Independent, read-only validation of explicit table relationships.

    This deliberately does not use the editor's context, grid or ID validators.
    A pass proves the measured relationships, not header meaning or reading order.
    The old structure inventory is kept untouched for saved-review compatibility.
    """
    root = pdf.Root.get("/StructTreeRoot")
    result = {"policy": TABLE_RELATIONSHIP_POLICY, "status": "not-applicable", "tables": [],
              "document_id_issues": [], "limitations": [
                  "Relationship integrity does not establish that headers, spans or a summary describe the content correctly.",
                  "Human table-relationship review remains required; a summary is optional."]}
    if not isinstance(root, pikepdf.Dictionary):
        return result
    rolemap = root.get("/RoleMap", {})
    nodes, parents, owned, pages, tables, seen = {}, {}, {}, {}, [], set()
    traversal_issues = []

    def walk(value, parent=None, table=None, page=None, depth=0):
        if cancelled(cancel):
            raise InterruptedError("Table inspection cancelled")
        if depth > 200 or len(nodes) > 50000:
            traversal_issues.append("Structure traversal exceeds the independent inspection bound")
            return
        if _array(value):
            for child in value:
                walk(child, parent, table, page, depth + 1)
            return
        if not isinstance(value, pikepdf.Dictionary) or "/S" not in value:
            return
        key = _id(value)
        if key in seen:
            traversal_issues.append("Repeated or cyclic structure element " + key)
            return
        seen.add(key)
        nodes[key], parents[key] = value, parent
        current_page = page_numbers.get(_id(value.get("/Pg")), page) if "/Pg" in value else page
        pages[key] = current_page
        if _resolved_owner_role(value, rolemap) == "/Table":
            table = key
            tables.append(key)
        owned[key] = table
        walk(value.get("/K"), key, table, current_page, depth + 1)

    walk(root.get("/K"))
    if not tables:
        return result
    ids, id_issues = defaultdict(list), result["document_id_issues"]
    for key, node in nodes.items():
        if "/ID" not in node:
            continue
        if not isinstance(node["/ID"], pikepdf.String) or not bytes(node["/ID"]):
            id_issues.append("Invalid or empty structure ID on " + key)
        else:
            ids[bytes(node["/ID"])].append(key)
    for raw, targets in ids.items():
        if len(targets) != 1:
            id_issues.append("Duplicate structure ID " + repr(raw)[:160])
    indexed, idtree_seen = defaultdict(list), set()

    def idtree(node, depth=0):
        if not isinstance(node, pikepdf.Dictionary) or depth > 100:
            id_issues.append("Invalid or excessive-depth IDTree")
            return []
        key = _id(node)
        if key in idtree_seen:
            id_issues.append("Repeated or cyclic IDTree node")
            return []
        idtree_seen.add(key)
        names, kids = node.get("/Names"), node.get("/Kids")
        keys = []
        if names is not None and kids is not None:
            id_issues.append("IDTree node contains both Names and Kids")
        if names is not None:
            if not _array(names) or len(names) % 2:
                id_issues.append("Invalid IDTree Names array")
            else:
                previous = None
                for index in range(0, len(names), 2):
                    raw, target = names[index], names[index + 1]
                    if not isinstance(raw, pikepdf.String):
                        id_issues.append("IDTree key is not a byte string")
                        continue
                    raw = bytes(raw)
                    keys.append(raw)
                    if previous is not None and raw <= previous:
                        id_issues.append("IDTree Names keys are not strictly ordered")
                    previous = raw
                    indexed[raw].append(_id(target))
                    if not isinstance(target, pikepdf.Dictionary) or _id(target) not in nodes:
                        id_issues.append("IDTree target is not a rooted structure element")
        if kids is not None:
            if not _array(kids) or not len(kids):
                id_issues.append("Invalid IDTree Kids array")
            else:
                for child in kids:
                    keys.extend(idtree(child, depth + 1))
        if names is None and kids is None:
            id_issues.append("Empty IDTree node")
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            id_issues.append("IDTree child ranges overlap or are not ordered")
        limits = node.get("/Limits")
        if depth and (not keys or limits is None):
            id_issues.append("Non-root IDTree node is empty or lacks Limits")
        if limits is not None and (not _array(limits) or len(limits) != 2
                or any(not isinstance(value, pikepdf.String) for value in limits)
                or not keys or [bytes(value) for value in limits] != [keys[0], keys[-1]]):
            id_issues.append("IDTree Limits do not match the exact key range")
        # Unrecognized extension keys are retained and never interpreted as a
        # substitute for Names/Kids/Limits or as authority for an ID mapping.
        return keys

    if "/IDTree" in root:
        idtree(root["/IDTree"])
    for raw in set(ids) | set(indexed):
        if len(indexed[raw]) != 1 or len(ids[raw]) != 1 or indexed[raw] != ids[raw]:
            id_issues.append("IDTree/structure ID mapping mismatch for " + repr(raw)[:160])

    def children(key):
        value = nodes[key].get("/K")
        values = list(value) if _array(value) else [value]
        return [_id(item) for item in values if isinstance(item, pikepdf.Dictionary) and "/S" in item]

    uncertain_attributes = set()
    def attrs(key, issue, uncertain):
        node = nodes[key]
        if "/C" in node or "/R" in node:
            uncertain.append("ClassMap attributes require separate interpretation on " + key)
            uncertain_attributes.add(key)
        raw = node.get("/A")
        values = list(raw) if _array(raw) else [] if raw is None else [raw]
        if any(not isinstance(item, pikepdf.Dictionary) for item in values):
            uncertain.append("Revision or non-dictionary attributes on " + key)
            uncertain_attributes.add(key)
        values = [item for item in values if isinstance(item, pikepdf.Dictionary) and item.get("/O") == pikepdf.Name.Table]
        if len(values) > 1:
            uncertain.append("Multiple Table attribute dictionaries on " + key)
            uncertain_attributes.add(key)
        # The first owner supplies diagnostic values only. Its authority remains
        # unknown, so conclusions depending on those values cannot become facts.
        return values[0] if values else pikepdf.Dictionary()

    for table in tables:
        issues, conditional, uncertain, row_keys, groups = [], [], list(traversal_issues), [], {}
        table_attribute = attrs(table, issues, uncertain)
        if "/Summary" in table_attribute and not isinstance(table_attribute["/Summary"], pikepdf.String):
            conditional.append("Table Summary is not a text string")
        for child in children(table):
            role = _resolved_owner_role(nodes[child], rolemap)
            if role == "/TR":
                row_keys.append(child); groups[child] = None
            elif role in {"/THead", "/TBody", "/TFoot"}:
                attrs(child, issues, uncertain)
                for row in children(child):
                    if _resolved_owner_role(nodes[row], rolemap) != "/TR":
                        issues.append("Table row group contains a non-TR element")
                    else:
                        row_keys.append(row); groups[row] = child
            elif role != "/Caption":
                issues.append("Table contains an unsupported direct child " + role)
        if not row_keys:
            issues.append("Table has no explicit rows")
        if len(row_keys) > 100:
            uncertain.append("Table exceeds 100-row inspection bound")
        grid, cells, by_cell = {}, [], {}
        for row_index, row in enumerate(row_keys[:100]):
            attrs(row, issues, uncertain)
            column = 0
            row_cells = children(row)
            if not row_cells:
                issues.append("Empty table row")
            for cell_key in row_cells:
                role = _resolved_owner_role(nodes[cell_key], rolemap)
                if role not in {"/TH", "/TD"} or owned.get(cell_key) != table:
                    issues.append("Row contains a non-cell or foreign cell")
                    continue
                attribute = attrs(cell_key, issues, uncertain)
                spans = []
                for name in ("/RowSpan", "/ColSpan"):
                    span = attribute.get(name, 1)
                    if type(span) is not int or not 1 <= span <= 100:
                        conditional.append("Invalid " + name + " on " + cell_key); span = 1
                    spans.append(span)
                row_span, col_span = spans
                while (row_index, column) in grid:
                    column += 1
                if column + col_span > 100:
                    uncertain.append("Table exceeds 100-column inspection bound")
                    continue
                if row_index + row_span > len(row_keys):
                    conditional.append("RowSpan extends beyond the table")
                if any(groups.get(row_keys[r]) != groups.get(row) for r in range(row_index, min(row_index + row_span, len(row_keys)))):
                    conditional.append("RowSpan crosses a table row-group boundary")
                slots = {(r, c) for r in range(row_index, min(row_index + row_span, len(row_keys), 100))
                         for c in range(column, column + col_span)}
                if any(slot in grid for slot in slots):
                    conditional.append("Overlapping table spans")
                for slot in slots:
                    grid[slot] = cell_key
                scope = attribute.get("/Scope")
                if scope is not None and (not isinstance(scope, pikepdf.Name) or str(scope) not in {"/Row", "/Column", "/Both"}):
                    conditional.append("Invalid Scope on " + cell_key)
                if role == "/TD" and scope is not None:
                    conditional.append("TD has a header Scope on " + cell_key)
                raw_headers = attribute.get("/Headers")
                if raw_headers is not None and (not _array(raw_headers) or not len(raw_headers)):
                    conditional.append("Headers is not a nonempty array on " + cell_key)
                    raw_headers = []
                targets = []
                for raw in raw_headers or []:
                    if not isinstance(raw, pikepdf.String):
                        conditional.append("Headers contains a non-string reference on " + cell_key)
                        continue
                    found = ids.get(bytes(raw), [])
                    if len(found) != 1:
                        conditional.append("Dangling or ambiguous Headers reference on " + cell_key)
                        continue
                    target = found[0]
                    if owned.get(target) != table or _resolved_owner_role(nodes[target], rolemap) != "/TH":
                        conditional.append("Headers reference is cross-table or targets a non-TH on " + cell_key)
                    elif target == cell_key:
                        conditional.append("Self-referencing Headers on " + cell_key)
                    targets.append(target)
                if len(targets) != len(set(targets)):
                    conditional.append("Duplicate Headers reference on " + cell_key)
                cell = {"element": cell_key, "role": role, "row": row_index, "column": column,
                        "row_span": row_span, "col_span": col_span,
                        "scope": str(scope) if scope is not None else None, "headers": targets}
                cells.append(cell); by_cell[cell_key] = cell
                column += col_span
        width = max((column + 1 for _, column in grid), default=0)
        if any((row, column) not in grid for row in range(min(len(row_keys), 100)) for column in range(width)):
            conditional.append("Table grid contains holes or unequal row widths")
        if len(cells) > 500:
            uncertain.append("Table exceeds 500-cell inspection bound")
        visiting, visited = set(), set()
        def cycle(key):
            if key in visiting:
                return True
            if key in visited or key not in by_cell:
                return False
            visiting.add(key)
            found = any(cycle(other) for other in by_cell[key]["headers"])
            visiting.remove(key); visited.add(key)
            return found
        if any(cycle(cell["element"]) for cell in cells):
            conditional.append("Headers hierarchy contains a cycle")
        headers = [cell for cell in cells if cell["role"] == "/TH"]
        for cell in cells:
            if cell["role"] != "/TD" or cell["headers"]:
                continue
            def scoped(header, row, column):
                return ((header["scope"] in {"/Row", "/Both"} and header["row"] <= row < header["row"] + header["row_span"])
                        or (header["scope"] in {"/Column", "/Both"} and header["column"] <= column < header["column"] + header["col_span"]))
            if not all(any(scoped(header, row, column) for header in headers)
                       for row in range(cell["row"], cell["row"] + cell["row_span"])
                       for column in range(cell["column"], cell["column"] + cell["col_span"])):
                conditional.append("TD lacks Headers or covering Scope association on " + cell["element"])
        if not cells or not headers:
            issues.append("Table lacks explicit cells or TH elements")
        if any(owned.get(key) == table for key in uncertain_attributes):
            uncertain.extend("Unresolved attribute authority: " + message for message in conditional)
        else:
            issues.extend(conditional)
        status = "fail" if issues or id_issues else "needs-review" if uncertain else "pass"
        result["tables"].append({"element": table, "pages": sorted({pages[k] for k in nodes if owned.get(k) == table and pages[k] is not None}),
            "rows": len(row_keys), "columns": width, "cells": len(cells), "headers": len(headers),
            "status": status, "issues": sorted(set(issues)), "uncertain": sorted(set(uncertain))})
    result["status"] = _aggregate(result["tables"])
    return result


def _empty_structure_tags(pdf, page_numbers, *, structure=None, refs=None, parent_tree=None, painted=None, cancel=None):
    """Independent display evidence; absence of painted text is never emptiness."""
    limits = {'elements': 20000, 'depth': 100, 'records': 2000, 'raw_values': 2000000}
    result = {'policy': 'bounded-empty-structure-1', 'status': 'not-applicable',
        'advisory': True, 'findings': [], 'uncertain': [], 'counts': {'examined': 0, 'empty': 0, 'editable_candidates': 0, 'protected': 0},
        'coverage': {'complete': True}, 'limits': limits, 'limitations': [
            'An empty-looking tag with replacement text, descriptions, references or other authority is protected, not proved disposable.',
            'MCID 0, missing/dangling content references, MCRs, OBJRs and child elements are never treated as empty.',
            'Removal is a separate source-bound reviewed operation; this advisory screen does not delete tags or approve meaning.',
            'Only unprotected P/Span leaves under neutral ancestry can overlap the bounded removal editor.'],
        'fix_path': 'Review an offered empty P/Span leaf in context, save Remove and give named acceptance, then Apply accepted edits. Use the source document for unsupported structure; nothing is deleted automatically.'}
    root = pdf.Root.get('/StructTreeRoot')
    if root is None: return result
    plain = lambda item: isinstance(item, pikepdf.Dictionary)
    integer = lambda item: isinstance(item, int) and not isinstance(item, bool)
    indirect = lambda item: _id(item) if getattr(item, 'is_indirect', False) else None
    def uncertain(reason, **details):
        result['coverage']['complete'] = False
        if len(result['findings']) + len(result['uncertain']) < limits['records']:
            result['uncertain'].append({'reason': reason, 'safely_empty': False, **details})
    if not plain(root) or indirect(root) is None or root.get('/Type') != pikepdf.Name.StructTreeRoot:
        uncertain('Malformed or noncanonical structure root'); result['status'] = 'needs-review'; return result
    incoming = Counter(); scanned = 0
    protected_document = bool(pdf.is_encrypted or any(name in pdf.Root for name in ('/Perms', '/AcroForm', '/OCProperties', '/AA', '/OpenAction')))
    def census(item, depth=0, top=False):
        nonlocal scanned, protected_document
        scanned += 1
        if scanned % 256 == 0 and cancelled(cancel): raise InterruptedError('Empty-tag inspection cancelled')
        if scanned > limits['raw_values'] or depth > limits['depth']: raise ValueError('Raw ownership census exceeds its bound')
        key = indirect(item)
        if key is not None and not top:
            incoming[key] += 1; return
        if isinstance(item, (pikepdf.Dictionary, pikepdf.Stream)):
            if (any(name in item for name in ('/ByteRange', '/JS', '/AA', '/OpenAction', '/XFA', '/FT'))
                    or item.get('/Type') == pikepdf.Name.Sig or item.get('/Subtype') == pikepdf.Name.Widget
                    or item.get('/S') == pikepdf.Name.JavaScript): protected_document = True
            for child in item.values(): census(child, depth + 1)
        elif isinstance(item, pikepdf.Array):
            for child in item: census(child, depth + 1)
    try:
        for item in pdf.objects: census(item, top=True)
        census(pdf.Root); census(pdf.trailer.get('/Info'))
    except InterruptedError: raise
    except (ValueError, TypeError, pikepdf.PdfError):
        uncertain('Raw ownership census could not be completed'); result['status'] = 'needs-review'; return result
    nodes, children, paths, parents, pages = {}, {}, {}, {}, {}
    arrays = set(); empty = []
    def walk(item, parent, path, inherited_page=None, depth=0, array_child=False):
        if cancelled(cancel): raise InterruptedError('Empty-tag inspection cancelled')
        if depth > limits['depth'] or len(nodes) >= limits['elements']:
            uncertain('Structure traversal limit', structure_path=path); return
        if isinstance(item, pikepdf.Array):
            key = indirect(item)
            if array_child or key is not None and (key in arrays or incoming[key] != 1):
                uncertain('Nested or shared structure child array', structure_path=path); return
            if key is not None: arrays.add(key)
            for index, child in enumerate(item): walk(child, parent, path+'/'+str(index), inherited_page, depth + 1, True)
            return
        if integer(item):
            if item < 0 or parent == indirect(root): uncertain('Malformed MCID reference', structure_path=path)
            return
        if plain(item) and (item.get('/Type') == pikepdf.Name.MCR or item.get('/Type') == pikepdf.Name.OBJR):
            if item.get('/Type') == pikepdf.Name.MCR and (not integer(item.get('/MCID')) or item.MCID < 0):
                uncertain('Malformed MCR is protected', structure_path=path)
            if item.get('/Type') == pikepdf.Name.OBJR and (not plain(item.get('/Obj')) or indirect(item.Obj) is None):
                uncertain('Malformed OBJR is protected', structure_path=path)
            return
        if not plain(item) or not isinstance(item.get('/S'), pikepdf.Name) or '/Type' in item and item.Type != pikepdf.Name.StructElem:
            uncertain('Unknown structure child is protected', structure_path=path); return
        key = indirect(item)
        if key is None or key in nodes or indirect(item.get('/P')) != parent:
            uncertain('Direct, shared, cyclic or incorrectly parented structure element', element=key, structure_path=path); return
        nodes[key] = item; paths[key] = path; parents[key] = parent
        children.setdefault(parent, []).append(key); children.setdefault(key, [])
        pages[key] = page_numbers.get(_id(item.Pg)) if '/Pg' in item else inherited_page
        if '/Pg' in item and pages[key] is None: uncertain('Unknown structure page', element=key, structure_path=path)
        result['counts']['examined'] += 1
        if '/K' not in item: shape = 'absent'
        elif item.get('/K') is None: shape = 'null'
        elif isinstance(item.K, pikepdf.Array) and len(item.K) == 0: shape = 'empty-array'
        else: shape = None
        if shape is not None: empty.append((key, shape))
        else: walk(item.get('/K'), key, path+'/K', pages[key], depth + 1)
    walk(root.get('/K'), indirect(root), 'catalog/StructTreeRoot/K')
    if structure:
        for name in ('missing_content_references', 'ambiguous_content_references'):
            if structure.get(name): uncertain('Unresolved content references are not empty tags', category=name, count=len(structure[name]))
        if structure.get('errors'): uncertain('Structure interpretation is incomplete', count=len(structure['errors']))
    protected_parent_owners = set()
    for target in (parent_tree or {}).values():
        values = list(target) if isinstance(target, pikepdf.Array) else [target]
        for owner in values:
            if plain(owner): protected_parent_owners.add(indirect(owner))
    neutral = {'/Document', '/Part', '/Sect', '/Div'}
    own_keys = {'/Type', '/S', '/P', '/K', '/Pg'}
    rolemap = root.get('/RoleMap', {})
    def painted_child(key):
        descendants = set(); todo = [key]
        while todo:
            current = todo.pop()
            if current in descendants: return False
            descendants.add(current); todo.extend(children.get(current, []))
        for reference, owners in (refs or {}).items():
            page, stream, mcid = reference
            if (page not in range(1, len(pdf.pages) + 1) or stream != 'page' or not integer(mcid)
                    or mcid < 0 or len(owners) != 1 or owners[0] not in descendants or not (painted or {}).get(reference)): continue
            parent_key = pdf.pages[page - 1].obj.get('/StructParents')
            slots = (parent_tree or {}).get(parent_key) if integer(parent_key) else None
            if isinstance(slots, pikepdf.Array) and mcid < len(slots) and indirect(slots[mcid]) == owners[0]: return True
        return False
    for key, shape in empty:
        node = nodes[key]; parent = parents[key]; role = str(node.S)
        record = {'element': key, 'role': role, 'page': pages[key], 'parent': parent,
            'structure_path': paths[key], 'k_shape': shape, 'safely_empty': True,
            'editable_candidate': False, 'limitations': []}
        protected = sorted(set(node.keys()) - own_keys)
        empty_carrier = indirect(node.get('/K')) if shape == 'empty-array' else None
        empty_alias = empty_carrier is not None and incoming[empty_carrier] != 1
        if protected or incoming[key] != 1 or key in protected_parent_owners or empty_alias:
            result['counts']['protected'] += 1
            uncertain('Empty-looking element has preserved content or reference authority', **{k: v for k, v in record.items() if k != 'safely_empty'},
                protected_keys=protected, incoming_references=incoming[key], parent_tree_target=key in protected_parent_owners)
            continue
        if len(result['findings']) + len(result['uncertain']) >= limits['records']:
            uncertain('Empty-tag record limit'); break
        restrictions = record['limitations']
        if protected_document: restrictions.append('Protected form, signature, action or optional-content authority requires a separate workflow')
        if role not in {'/P', '/Span'}: restrictions.append('Only P/Span leaves are offered for removal')
        if not isinstance(rolemap, (dict, pikepdf.Dictionary)) or any(name in rolemap for name in ('/P', '/Span')):
            restrictions.append('Role mapping prevents the narrow literal P/Span scope')
        ancestor = parent; seen = set()
        while ancestor != indirect(root):
            if ancestor in seen or ancestor not in nodes:
                restrictions.append('Ancestry could not be proved'); break
            seen.add(ancestor); owner = nodes[ancestor]
            if incoming[ancestor] != 1 + len(children.get(ancestor, [])):
                restrictions.append('An ancestor has another reference or alias'); break
            if str(owner.S) not in neutral or set(owner.keys()) - own_keys:
                restrictions.append('Semantic or protected ancestry requires source repair'); break
            ancestor = parents[ancestor]
        owner = nodes.get(parent); raw = owner.get('/K') if owner is not None else None
        siblings = children.get(parent, [])
        if (not isinstance(raw, pikepdf.Array) or len(raw) < 2 or len(siblings) != len(raw)
                or len(set(siblings)) != len(siblings) or indirect(raw) is not None and incoming[indirect(raw)] != 1):
            restrictions.append('A unique complete grouping child array with retained siblings is required')
        meaningful = [sibling for sibling in siblings if sibling != key and painted_child(sibling)]
        if not meaningful: restrictions.append('No retained sibling has independently proven page painting and ParentTree ownership')
        record['nonempty_siblings'] = meaningful
        record['editable_candidate'] = not restrictions and result['coverage']['complete']
        result['findings'].append(record); result['counts']['empty'] += 1
        result['counts']['editable_candidates'] += int(record['editable_candidate'])
    if result['findings']: result['status'] = 'fail'
    elif not result['coverage']['complete']: result['status'] = 'needs-review'
    else: result['status'] = 'pass'
    return result


def _raw_form_signals(pdf, cancel=None):
    """Include detached and direct field/Widget authorities in form detection."""
    if '/AcroForm' in pdf.Root: return True
    traversed = 0
    def scan(item, depth=0, top=False):
        nonlocal traversed
        traversed += 1
        if traversed % 256 == 0 and cancelled(cancel): raise InterruptedError('Raw form inspection cancelled')
        if traversed > 2000000 or depth > 100: return True
        if getattr(item, 'is_indirect', False) and not top: return False
        if isinstance(item, (pikepdf.Dictionary, pikepdf.Stream)):
            if '/FT' in item or item.get('/Subtype') == pikepdf.Name.Widget or item.get('/Type') == pikepdf.Name.Sig or '/ByteRange' in item: return True
            return any(scan(child, depth + 1) for child in item.values())
        if isinstance(item, pikepdf.Array): return any(scan(child, depth + 1) for child in item)
        return False
    return any(scan(item, top=True) for item in pdf.objects)


_NAVIGATION_FITS = {'/Fit', '/FitB', '/FitH', '/FitV', '/FitBH', '/FitBV', '/XYZ', '/FitR'}
_BOOKMARK_KEYS = {'/Title', '/Parent', '/Prev', '/Next', '/First', '/Last', '/Count', '/Dest', '/A', '/C', '/F', '/SE'}
_ELEMENT_PLACES = {'/Block', '/Inline', '/Before', '/Start', '/End'}
_CELL_SCOPES = {'/Row', '/Column', '/Both'}
_LIST_STYLES = {'/None', '/Unordered', '/Ordered', '/Decimal', '/UpperRoman', '/LowerRoman', '/UpperAlpha', '/LowerAlpha', '/Disc', '/Circle', '/Square'}


def _navigation_only(action, pages):
    """A plain jump inside the document, or a web or mail link: it cannot run, open, send, hide or change anything, or chain on."""
    plain = lambda item: isinstance(item, pikepdf.Dictionary) and not isinstance(item, pikepdf.Stream)
    printable = lambda text, limit: 0 < len(text) <= limit and all(32 <= ord(c) != 127 for c in text)
    if not plain(action) or set(map(str, action.keys())) - {'/Type', '/S', '/URI', '/D', '/IsMap'}: return False
    if '/Type' in action and action.Type != pikepdf.Name.Action: return False
    kind = action.get('/S')
    if kind == pikepdf.Name.URI:
        uri = action.get('/URI')
        if '/D' in action or '/IsMap' in action and action.IsMap is not False or not isinstance(uri, pikepdf.String): return False
        text = str(uri)
        try: parts = urlsplit(text)
        except ValueError: return False
        scheme = parts.scheme.lower()
        return printable(text, 8192) and scheme in {'http', 'https', 'mailto'} and (scheme == 'mailto' or bool(parts.netloc))
    if kind == pikepdf.Name.GoTo:
        if '/URI' in action or '/IsMap' in action: return False
        target = action.get('/D')
        if isinstance(target, (pikepdf.String, pikepdf.Name)): return printable(str(target), 4096)
        if not isinstance(target, pikepdf.Array) or not 2 <= len(target) <= 6: return False
        numbers = list(target)[2:]
        return (_id(target[0]) in pages and isinstance(target[1], pikepdf.Name) and str(target[1]) in _NAVIGATION_FITS
                and all(n is None or isinstance(n, (int, float, Decimal)) and not isinstance(n, bool) and math.isfinite(float(n)) for n in numbers))
    return False


def _navigation_ids(pdf):
    """Ids of page links and bookmarks whose only action is passive navigation, and of those action objects."""
    owners = set(); actions = set()
    try:
        pages = {_id(page.obj) for page in pdf.pages}
        def accept(owner):
            action = owner.get('/A'); owner_id = _id(owner) if getattr(owner, 'is_indirect', False) else None
            if owner_id is None or not _navigation_only(action, pages): return
            owners.add(owner_id)
            if getattr(action, 'is_indirect', False): actions.add(_id(action))
        for page in pdf.pages:
            listed = page.obj.get('/Annots')
            if not isinstance(listed, pikepdf.Array): continue
            for annotation in listed:
                if (isinstance(annotation, pikepdf.Dictionary) and not isinstance(annotation, pikepdf.Stream)
                        and annotation.get('/Subtype') == pikepdf.Name.Link and '/A' in annotation): accept(annotation)
        top = pdf.Root.get('/Outlines')
        todo = [top.get('/First')] if isinstance(top, pikepdf.Dictionary) and not isinstance(top, pikepdf.Stream) else []
        visited = set()
        while todo and len(visited) < 100000:
            entry = todo.pop(); entry_id = _id(entry) if getattr(entry, 'is_indirect', False) else None
            if (not isinstance(entry, pikepdf.Dictionary) or isinstance(entry, pikepdf.Stream)
                    or entry_id is None or entry_id in visited): continue
            visited.add(entry_id)
            if '/A' in entry and not set(map(str, entry.keys())) - _BOOKMARK_KEYS: accept(entry)
            todo.extend([entry.get('/First'), entry.get('/Next')])
    except (ValueError, RuntimeError, TypeError, KeyError, pikepdf.PdfError):
        return set(), set()
    return owners, actions


def _inert_empty_acroform(pdf, cancel=None):
    """Recognize only unused, passive empty form containers without mutation.

    This independent compatibility proof does not screen an actual control or
    grant any editing capability. Unknown empty containers retain the form guard.
    """
    plain = lambda item: isinstance(item, pikepdf.Dictionary) and not isinstance(item, pikepdf.Stream)
    integer = lambda item: isinstance(item, int) and not isinstance(item, bool)
    name = lambda item: isinstance(item, pikepdf.Name) and bool(re.fullmatch(r'/[!-~]{1,127}', str(item))) and not any(c in str(item)[1:] for c in '()<>[]{}/%#')
    bases = {'/StandardEncoding', '/MacRomanEncoding', '/MacExpertEncoding', '/WinAnsiEncoding'}
    def encoding(item):
        if isinstance(item, pikepdf.Name): return str(item) in bases
        if not plain(item) or set(item.keys()) - {'/Type', '/BaseEncoding', '/Differences'}: return False
        if '/Type' in item and item.Type != pikepdf.Name.Encoding: return False
        if '/BaseEncoding' in item and (not isinstance(item.BaseEncoding, pikepdf.Name) or str(item.BaseEncoding) not in bases): return False
        if '/Differences' not in item: return True
        entries = item.Differences
        if not isinstance(entries, pikepdf.Array) or len(entries) > 512: return False
        current = None; assigned = set()
        for entry in entries:
            if integer(entry):
                if not 0 <= entry <= 255: return False
                current = entry
            else:
                if current is None or current > 255 or current in assigned or not name(entry): return False
                assigned.add(current); current += 1
        return True
    try:
        if pdf.is_encrypted or '/Perms' in pdf.Root: return False
        acro = pdf.Root.get('/AcroForm')
        if not plain(acro) or set(acro.keys()) - {'/Fields', '/DA', '/DR', '/Q', '/NeedAppearances', '/SigFlags', '/CO'}: return False
        roots = acro.get('/Fields')
        if not isinstance(roots, pikepdf.Array) or len(roots): return False
        if '/NeedAppearances' in acro and acro.NeedAppearances is not False: return False
        if '/SigFlags' in acro and (not integer(acro.SigFlags) or acro.SigFlags != 0): return False
        if '/Q' in acro and (not integer(acro.Q) or acro.Q not in {0, 1, 2}): return False
        if '/CO' in acro and (not isinstance(acro.CO, pikepdf.Array) or len(acro.CO)): return False
        resources = acro.get('/DR', pikepdf.Dictionary())
        if not plain(resources) or set(resources.keys()) - {'/Font', '/Encoding'}: return False
        fonts = resources.get('/Font', pikepdf.Dictionary())
        encodings = resources.get('/Encoding', pikepdf.Dictionary())
        if not plain(fonts) or not plain(encodings) or max(len(fonts), len(encodings)) > 100: return False
        for key, entry in encodings.items():
            if not name(pikepdf.Name(str(key))) or not encoding(entry): return False
        for key, entry in fonts.items():
            if (not name(pikepdf.Name(str(key))) or not plain(entry)
                    or set(entry.keys()) - {'/Type', '/Subtype', '/BaseFont', '/Name', '/Encoding'}
                    or entry.get('/Type') != pikepdf.Name.Font or entry.get('/Subtype') != pikepdf.Name.Type1
                    or not isinstance(entry.get('/BaseFont'), pikepdf.Name) or str(entry.BaseFont)[1:] not in STANDARD14): return False
            if '/Name' in entry and not name(entry.Name): return False
            if '/Encoding' in entry and not encoding(entry.Encoding): return False
        if '/DA' in acro:
            if not isinstance(acro.DA, pikepdf.String): return False
            raw = str(acro.DA)
            if len(raw) > 4096 or any(ord(c) > 127 for c in raw): return False
            tokens = raw.split(); operands = []
            for token in tokens:
                if re.fullmatch(r'/[A-Za-z0-9_.+\-]+', token):
                    operands.append(token); continue
                if re.fullmatch(r'[+\-]?(?:\d+(?:\.\d*)?|\.\d+)', token):
                    number = float(token)
                    if not math.isfinite(number) or abs(number) > 10000: return False
                    operands.append(number); continue
                expected = {'Tf': 2, 'g': 1, 'rg': 3, 'k': 4, 'Tc': 1, 'Tw': 1, 'TL': 1, 'Ts': 1, 'Tz': 1, 'Tr': 1}
                if token not in expected or len(operands) != expected[token]: return False
                if token == 'Tf':
                    if not isinstance(operands[0], str) or operands[0] not in fonts or not isinstance(operands[1], float) or not 0 <= operands[1] <= 10000: return False
                elif any(not isinstance(v, float) for v in operands): return False
                elif token in {'g', 'rg', 'k'} and any(not 0 <= v <= 1 for v in operands): return False
                elif token == 'Tz' and not 0 < operands[0] <= 10000: return False
                elif token == 'Tr' and (not operands[0].is_integer() or not 0 <= operands[0] <= 7): return False
                operands = []
            if operands: return False
        # Scan all indirect objects and every direct descendant, including objects
        # outside the catalog/page tree. Do not resolve indirect edges twice.
        incoming = Counter(); visited = 0; attribute_owners = []
        link_owners, link_actions = _navigation_ids(pdf)
        action_roles = {'/GoTo', '/GoToR', '/GoToE', '/Launch', '/Thread', '/URI', '/Sound', '/Movie', '/Hide', '/Named', '/SubmitForm', '/ResetForm', '/ImportData', '/JavaScript', '/SetOCGState', '/Rendition', '/Trans', '/GoTo3DView', '/GoToDp', '/RichMediaExecute', '/SetState', '/NoOp'}
        def scan(item, depth=0, top=False, via=False):
            nonlocal visited
            visited += 1
            if visited % 256 == 0 and cancelled(cancel): raise InterruptedError('Empty form inspection cancelled')
            if visited > 2000000 or depth > 100: raise ValueError('Empty form traversal exceeds its bound')
            ident = _id(item) if getattr(item, 'is_indirect', False) else None
            if ident is not None and not top:
                incoming[ident] += 1
                if ident in link_actions and not via: raise ValueError('A link action is also used somewhere else')
                return
            navigation = via or top and ident in link_actions
            if isinstance(item, (pikepdf.Dictionary, pikepdf.Stream)):
                if (any(k in item for k in ('/FT', '/XFA', '/AA', '/JS', '/OpenAction', '/ByteRange', '/Lock', '/SV'))
                        or item.get('/Subtype') == pikepdf.Name.Widget or item.get('/Type') == pikepdf.Name.Sig
                        or not navigation and (item.get('/Type') == pikepdf.Name.Action
                            or isinstance(item.get('/S'), pikepdf.Name) and str(item.S) in action_roles)):
                    raise ValueError('An active, protected or unknown form authority is present')
                if '/A' in item and ident not in link_owners: attribute_owners.append(item)
                for key, child in item.items(): scan(child, depth + 1, via=ident in link_owners and str(key) == '/A')
            elif isinstance(item, pikepdf.Array):
                for child in item: scan(child, depth + 1)
        for item in pdf.objects: scan(item, top=True)
        if attribute_owners:
            # Generated Figure geometry is a structure attribute, not an action.
            # Establish ownership from the actual tree before admitting this
            # one exact, passive attribute dictionary shape.
            tree = pdf.Root.get('/StructTreeRoot')
            if not plain(tree) or not getattr(tree, 'is_indirect', False) or tree.get('/Type') != pikepdf.Name.StructTreeRoot: return False
            rolemap = tree.get('/RoleMap', pikepdf.Dictionary())
            if not plain(rolemap) or {'/Figure', '/Table', '/TH', '/TD', '/L'} & set(map(str, rolemap.keys())): return False
            nodes = {}; arrays = set(); stream_refs = {}; edges = 0
            pages = {_id(page.obj) for page in pdf.pages}
            def tags(item, parent, depth=0, root=False, array_child=False, inherited_page=None):
                nonlocal edges
                edges += 1
                if edges > 100000 or depth > 100: raise ValueError('Attribute owner tree exceeds its bound')
                if edges % 256 == 0 and cancelled(cancel): raise InterruptedError('Empty form attribute inspection cancelled')
                if isinstance(item, pikepdf.Array):
                    key = _id(item) if getattr(item, 'is_indirect', False) else None
                    if array_child or key is not None and (key in arrays or incoming[key] != 1): raise ValueError('Attribute owner child array is nested or shared')
                    if key is not None: arrays.add(key)
                    for child in item: tags(child, parent, depth + 1, root=root, array_child=True, inherited_page=inherited_page)
                elif integer(item) and item >= 0 and not root:
                    return
                elif plain(item) and (item.get('/Type') == pikepdf.Name.StructElem or '/Type' not in item and '/S' in item and '/P' in item):
                    ident = _id(item) if getattr(item, 'is_indirect', False) else None
                    if ident is None or ident in nodes or not isinstance(item.get('/S'), pikepdf.Name) or _id(item.get('/P')) != parent: raise ValueError('Attribute owner structure is not canonical')
                    nodes[ident] = item
                    page = item.get('/Pg', inherited_page)
                    if page is not None and (not plain(page) or _id(page) not in pages): raise ValueError('Attribute owner page is not in the document')
                    if '/K' in item: tags(item.K, ident, depth + 1, inherited_page=page)
                elif plain(item) and item.get('/Type') == pikepdf.Name.MCR:
                    if root or set(item.keys()) - {'/Type', '/Pg', '/MCID', '/Stm'} or not integer(item.get('/MCID')) or item.MCID < 0: raise ValueError('Unsupported attribute-tree marked content')
                    if '/Pg' in item and (not plain(item.Pg) or item.Pg.get('/Type') != pikepdf.Name.Page): raise ValueError('Attribute-tree page is not a Page')
                    if '/Stm' in item:
                        page = item.get('/Pg', inherited_page)
                        if page is None or _id(page) not in pages: raise ValueError('Form text has no document page')
                        source_stream = item.Stm
                        if not isinstance(source_stream, pikepdf.Stream) or not getattr(source_stream, 'is_indirect', False): raise ValueError('Form text needs an indirect stream')
                        key = _id(source_stream)
                        stream_refs.setdefault(key, (source_stream, []))[1].append((item.MCID, parent))
                elif plain(item) and item.get('/Type') == pikepdf.Name.OBJR:
                    if root or set(item.keys()) - {'/Type', '/Pg', '/Obj'} or not plain(item.get('/Obj')): raise ValueError('Unsupported attribute-tree object reference')
                    if '/Pg' in item and (not plain(item.Pg) or item.Pg.get('/Type') != pikepdf.Name.Page): raise ValueError('Attribute-tree page is not a Page')
                else:
                    raise ValueError('An unknown child prevents proving attribute ownership')
            tags(tree.get('/K'), _id(tree), root=True)
            if stream_refs:
                # The retained producer text may already live in a Form
                # XObject. Prove its exact raw ownership and bounded text-only
                # markers; this never creates or changes any stream.
                parent_values = {}; number_nodes = set()
                def number_tree(item, depth=0):
                    if not plain(item) or depth > 50: raise ValueError('Malformed passive ParentTree')
                    ident = _id(item) if getattr(item, 'is_indirect', False) else None
                    if ident is not None:
                        if ident in number_nodes: raise ValueError('Shared passive ParentTree node')
                        number_nodes.add(ident)
                    nums, kids = item.get('/Nums'), item.get('/Kids')
                    if (nums is None) == (kids is None): raise ValueError('Ambiguous passive ParentTree')
                    keys = []
                    if nums is not None:
                        if not isinstance(nums, pikepdf.Array) or len(nums) % 2: raise ValueError('Malformed passive ParentTree entries')
                        for index in range(0, len(nums), 2):
                            key = nums[index]
                            if not integer(key) or key < 0 or key in parent_values: raise ValueError('Duplicate passive ParentTree key')
                            parent_values[key] = nums[index + 1]; keys.append(key)
                    elif isinstance(kids, pikepdf.Array) and len(kids):
                        for child in kids: keys.extend(number_tree(child, depth + 1))
                    else: raise ValueError('Malformed passive ParentTree children')
                    if keys != sorted(keys) or len(keys) != len(set(keys)): raise ValueError('Unordered passive ParentTree')
                    limits = item.get('/Limits')
                    if depth and (not keys or limits is None): raise ValueError('Missing passive ParentTree limits')
                    if limits is not None and (not isinstance(limits, pikepdf.Array) or len(limits) != 2 or any(not integer(v) for v in limits) or not keys or list(limits) != [keys[0], keys[-1]]): raise ValueError('Invalid passive ParentTree limits')
                    return keys
                number_tree(tree.get('/ParentTree'))
                parent_uses = Counter(obj.get('/StructParents') for obj in pdf.objects
                    if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)) and integer(obj.get('/StructParents'))
                    and (obj.get('/Type') == pikepdf.Name.Page or isinstance(obj, pikepdf.Stream) and obj.get('/Subtype') == pikepdf.Name.Form))
                allowed_ops = {'q', 'Q', 'cm', 'w', 'J', 'j', 'M', 'BT', 'ET', 'Tf', 'Tm', 'Td', 'TD', 'T*', 'Tc', 'Tw', 'Tz', 'TL', 'Tr', 'Ts', 'g', 'rg', 'k', 'G', 'RG', 'K', 'BMC', 'BDC', 'EMC', 'Tj', 'TJ', "'", '"'}
                for source_stream, references in stream_refs.values():
                    if (not isinstance(source_stream, pikepdf.Stream) or not getattr(source_stream, 'is_indirect', False)
                            or set(source_stream.keys()) - {'/Type', '/Subtype', '/FormType', '/BBox', '/Matrix', '/Resources', '/StructParents', '/Length', '/Filter', '/DecodeParms'}
                            or source_stream.get('/Type') != pikepdf.Name.XObject or source_stream.get('/Subtype') != pikepdf.Name.Form
                            or ('/FormType' in source_stream and (not integer(source_stream.get('/FormType')) or source_stream.FormType != 1))
                            or not plain(source_stream.get('/Resources'))): return False
                    for key, length, optional in [('/BBox', 4, False), ('/Matrix', 6, True)]:
                        values = source_stream.get(key)
                        if optional and values is None: continue
                        if not isinstance(values, pikepdf.Array) or len(values) != length or any(isinstance(n, bool) or not isinstance(n, (int, float, Decimal)) or not math.isfinite(float(n)) for n in values): return False
                    parent_key = source_stream.get('/StructParents')
                    slots = parent_values.get(parent_key) if integer(parent_key) else None
                    if not integer(parent_key) or parent_key < 0 or parent_uses[parent_key] != 1 or not isinstance(slots, pikepdf.Array): return False
                    expected = {}
                    for mcid, owner in references:
                        if mcid in expected or mcid >= len(slots) or _id(slots[mcid]) != owner: return False
                        expected[mcid] = str(nodes[owner].S)
                    payload = source_stream.read_bytes()
                    if len(payload) > 5 * 1024 * 1024: return False
                    marked = {}; active = None; shown = False; text = False; graphics = []; font_valid = False; operations = 0; frames = []
                    for instruction in pikepdf.parse_content_stream(source_stream):
                        operations += 1
                        if operations % 256 == 0 and cancelled(cancel): raise InterruptedError('Passive Form text inspection cancelled')
                        if operations > 200000: return False
                        operands, operator = instruction.operands, str(instruction.operator)
                        if operator not in allowed_ops: return False
                        if operator == 'q': graphics.append(font_valid)
                        elif operator == 'Q':
                            if not graphics: return False
                            font_valid = graphics.pop()
                        elif operator == 'BT':
                            if text: return False
                            text = True
                        elif operator == 'ET':
                            if not text: return False
                            text = False
                        elif operator == 'Tf':
                            if len(operands) != 2 or not isinstance(operands[0], pikepdf.Name) or isinstance(operands[1], bool) or not isinstance(operands[1], (int, float, Decimal)) or not math.isfinite(float(operands[1])) or float(operands[1]) <= 0: return False
                            font_map = source_stream.Resources.get('/Font')
                            resolved_font = font_map.get(str(operands[0])) if plain(font_map) else None
                            if not plain(resolved_font) or resolved_font.get('/Type') != pikepdf.Name.Font: return False
                            font_valid = True
                        elif operator == 'BMC':
                            # A plain marked-content wrapper has no MCID or property list and owns nothing. Text inside /Artifact is
                            # decorative; any other text still needs an owning BDC.
                            if len(operands) != 1 or not isinstance(operands[0], pikepdf.Name) or str(operands[0]) == '/OC': return False
                            frames.append('artifact' if str(operands[0]) == '/Artifact' else None)
                        elif operator == 'BDC':
                            if active is not None or len(operands) != 2 or not isinstance(operands[0], pikepdf.Name) or str(operands[0]) in {'/Artifact', '/OC'}: return False
                            properties = operands[1]
                            if not plain(properties) or set(properties.keys()) != {'/MCID'} or not integer(properties.MCID) or properties.MCID < 0: return False
                            active = properties.MCID; shown = False
                            if active in marked or expected.get(active) != str(operands[0]): return False
                            frames.append(active)
                        elif operator == 'EMC':
                            if not frames: return False
                            if isinstance(frames.pop(), int):
                                if active is None or not shown: return False
                                marked[active] = True; active = None
                        elif operator in {'Tj', 'TJ', "'", '"'}:
                            decorative = 'artifact' in frames
                            if not text or not font_valid or (active is None and not decorative): return False
                            if operator == 'TJ':
                                if len(operands) != 1 or not isinstance(operands[0], pikepdf.Array): return False
                                painted = any(isinstance(v, pikepdf.String) and len(bytes(v)) for v in operands[0])
                            else:
                                required = 3 if operator == '"' else 1
                                if len(operands) != required or not isinstance(operands[-1], pikepdf.String): return False
                                painted = bool(len(bytes(operands[-1])))
                            shown = shown or (painted and not decorative)
                    if text or graphics or frames or active is not None or set(marked) != set(expected): return False
            for owner in attribute_owners:
                ident = _id(owner) if getattr(owner, 'is_indirect', False) else None
                attribute = owner.A
                if ident not in nodes or not plain(attribute): return False
                role = owner.get('/S'); fields = set(map(str, attribute.keys())); bbox = None
                if role in (pikepdf.Name.Figure, pikepdf.Name.Table):
                    if (attribute.get('/O') != pikepdf.Name.Layout or not {'/O', '/BBox'} <= fields <= {'/O', '/BBox', '/Placement'}
                            or '/Placement' in fields and (not isinstance(attribute.Placement, pikepdf.Name) or str(attribute.Placement) not in _ELEMENT_PLACES)): return False
                    bbox = attribute.BBox
                    if not isinstance(bbox, pikepdf.Array) or len(bbox) != 4: return False
                    if any(isinstance(n, bool) or not isinstance(n, (int, float, Decimal)) or not math.isfinite(float(n)) for n in bbox): return False
                elif role in (pikepdf.Name.TH, pikepdf.Name.TD):
                    if attribute.get('/O') != pikepdf.Name.Table or fields - {'/O', '/Scope', '/RowSpan', '/ColSpan'}: return False
                    if '/Scope' in fields and (not isinstance(attribute.Scope, pikepdf.Name) or str(attribute.Scope) not in _CELL_SCOPES): return False
                    if any(span in fields and (not integer(attribute[span]) or not 1 <= attribute[span] <= 1000) for span in ('/RowSpan', '/ColSpan')): return False
                elif role == pikepdf.Name.L:
                    if attribute.get('/O') != pikepdf.Name.List or fields - {'/O', '/ListNumbering', '/ContinuedList', '/ContinuedFrom'}: return False
                    if '/ListNumbering' in fields and (not isinstance(attribute.ListNumbering, pikepdf.Name) or str(attribute.ListNumbering) not in _LIST_STYLES): return False
                    if '/ContinuedList' in fields and not isinstance(attribute.ContinuedList, bool): return False
                    if '/ContinuedFrom' in fields:
                        previous = attribute.ContinuedFrom
                        if not isinstance(previous, pikepdf.String) or not 0 < len(str(previous)) <= 128 or any(ord(c) < 32 for c in str(previous)): return False
                else: return False
                for carrier in (attribute, bbox):
                    if getattr(carrier, 'is_indirect', False) and incoming[_id(carrier)] != 1: return False
        for carrier in [acro, roots, *([acro.CO] if '/CO' in acro else [])]:
            if getattr(carrier, 'is_indirect', False) and incoming[_id(carrier)] != 1: return False
        return True
    except InterruptedError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError, pikepdf.PdfError):
        return False


def _form_accessibility(pdf, page_numbers, cancel=None):
    """Independent raw AcroForm/Widget/tag assessment, without editor helpers.

    The support flag describes a bounded, static structure only. A successful
    metadata screen does not establish label meaning, tab usability or operation.
    """
    plain = lambda value: isinstance(value, pikepdf.Dictionary) and not isinstance(value, pikepdf.Stream)
    integer = lambda value: isinstance(value, int) and not isinstance(value, bool)
    indirect = lambda value: _id(value) if getattr(value, 'is_indirect', False) else None
    result = {'policy': 'bounded-acroform-1', 'present': False, 'supported_structure': False,
              'status': 'not-applicable', 'fields': [], 'pages': [], 'issues': [],
              'unsupported_reasons': [], 'limitations': [
                  'Names, label-in-name, instructions, required-state meaning and logical order require human review.',
                  'Keyboard activation, editing and assistive-technology announcements have not been tested.',
                  'Only existing static Tx/Ch controls and simple single-widget checkbox controls are screened.']}
    unsupported, issues = result['unsupported_reasons'], result['issues']
    widgets, all_annotations, annotation_pages, page_annotations = {}, {}, {}, {}
    for number, page in enumerate(pdf.pages, 1):
        if '/AA' in page.obj:
            unsupported.append('Page actions require separate form-navigation handling')
        raw = page.obj.get('/Annots')
        if raw is None:
            page_annotations[number] = []; continue
        if not _array(raw):
            unsupported.append('Page annotation carrier is not an ordinary array'); continue
        page_annotations[number] = []
        for index, annotation in enumerate(raw):
            if not plain(annotation):
                unsupported.append('Page annotation is not an ordinary dictionary'); continue
            key = indirect(annotation)
            if key is None:
                unsupported.append('Direct annotations lack a uniquely bound object identity'); continue
            if key in annotation_pages:
                unsupported.append('An annotation occurs on more than one page or array position')
            annotation_pages[key] = number
            all_annotations[key] = annotation
            page_annotations[number].append(key)
            if annotation.get('/Subtype') == pikepdf.Name.Widget:
                widgets[key] = (annotation, number, index)
    result['present'] = _raw_form_signals(pdf, cancel) or bool(widgets)
    if result['present'] and _inert_empty_acroform(pdf, cancel):
        result['present'] = False
        result['empty_container'] = {'policy': 'passive-empty-acroform-2', 'status': 'inert',
            'scope': 'No controls, form actions or unproved authority; plain page links and bookmarks are left as they are, '
                     'and the original empty dictionary is retained.'}
    if not result['present']:
        return result
    result['status'] = 'needs-review'
    acro = pdf.Root.get('/AcroForm')
    if not plain(acro):
        unsupported.append('Widgets require an ordinary AcroForm dictionary')
        result['unsupported_reasons'] = sorted(set(unsupported)); return result
    if pdf.is_encrypted or '/Perms' in pdf.Root or acro.get('/SigFlags', 0):
        unsupported.append('Encrypted or signed forms require a separate derivative workflow')
    if any(key in acro for key in ('/XFA', '/A', '/AA')) or any(key in pdf.Root for key in ('/OpenAction', '/AA')):
        unsupported.append('Dynamic forms or document/form actions require separate handling')
    names = pdf.Root.get('/Names')
    if plain(names) and '/JavaScript' in names:
        unsupported.append('Document JavaScript requires separate form handling')
    if acro.get('/NeedAppearances', False) is not False:
        unsupported.append('Appearance regeneration is enabled or has an unsupported representation')
    if '/CO' in acro and (not _array(acro['/CO']) or len(acro['/CO'])):
        unsupported.append('A nonempty or malformed calculation order requires separate handling')
    roots = acro.get('/Fields')
    if not _array(roots) or not len(roots):
        unsupported.append('An interactive form needs a nonempty ordinary Fields array')
        roots = []
    seen_fields, terminal_widgets, field_names = set(), {}, set()
    leaves = []

    def field(node, parent=None, prefix='', inherited=None, depth=0):
        if cancelled(cancel): raise InterruptedError('Form inspection cancelled')
        if depth > 50 or len(seen_fields) >= 1000 or not plain(node) or indirect(node) is None:
            unsupported.append('Field tree is direct, malformed or exceeds the traversal bound'); return
        key = indirect(node)
        if key in seen_fields:
            unsupported.append('Field tree is shared or cyclic'); return
        seen_fields.add(key)
        if parent is None and '/Parent' in node or parent is not None and indirect(node.get('/Parent')) != parent:
            unsupported.append('Field Parent does not match its unique Fields/Kids owner')
        partial = node.get('/T')
        if partial is not None and (not isinstance(partial, pikepdf.String) or not str(partial) or '.' in str(partial) or any(ord(char) < 32 for char in str(partial))):
            unsupported.append('Field partial names must be nonempty ordinary strings without periods')
        part = str(partial) if isinstance(partial, pikepdf.String) else ''
        name = prefix + ('.' if prefix and part else '') + part
        effective = dict(inherited or {})
        for attr in ('/FT', '/Ff', '/V', '/DV', '/DA'):
            if attr in node: effective[attr] = node[attr]
        if any(attr in node for attr in ('/A', '/AA', '/Lock', '/SV')):
            unsupported.append('Field actions or signature machinery require separate handling')
        kids = node.get('/Kids')
        merged = node.get('/Subtype') == pikepdf.Name.Widget
        if merged:
            if kids is not None: unsupported.append('A merged field/widget cannot also have Kids')
            members = [node]
        elif _array(kids) and len(kids) and all(plain(kid) and kid.get('/Subtype') == pikepdf.Name.Widget and '/T' not in kid for kid in kids):
            members = list(kids)
        else:
            if not _array(kids) or not len(kids):
                unsupported.append('A terminal field lacks its existing Widget'); return
            if any(plain(kid) and kid.get('/Subtype') == pikepdf.Name.Widget and '/T' not in kid for kid in kids):
                unsupported.append('Field children mix terminal fields and Widget-only objects'); return
            for child in kids: field(child, key, name, effective, depth + 1)
            return
        if len(leaves) >= 100:
            unsupported.append('Only at most 100 unique terminal fields are supported')
        if not isinstance(partial, pikepdf.String) or not part:
            unsupported.append('Every terminal field needs its own explicit partial internal name')
        if name in field_names: unsupported.append('Qualified terminal field names are not unique')
        field_names.add(name)
        kind, flags = effective.get('/FT'), effective.get('/Ff', 0)
        if not isinstance(kind, pikepdf.Name) or kind not in {pikepdf.Name.Tx, pikepdf.Name.Ch, pikepdf.Name.Btn}:
            unsupported.append('Field type requires a separate supported workflow')
        if not integer(flags) or not 0 <= flags < 2**32:
            unsupported.append('Field flags are not an ordinary nonnegative integer'); flags = 0
        if kind == pikepdf.Name.Btn and flags & (32768 | 65536 | 33554432):
            unsupported.append('Radio groups and pushbuttons require separate name/state/appearance handling')
        if kind == pikepdf.Name.Btn and len(members) != 1:
            unsupported.append('Grouped or mirrored checkbox widgets require separate handling')
        if kind == pikepdf.Name.Tx and flags & (8192 | 1048576 | 16777216 | 33554432):
            unsupported.append('Password, file-select, comb or rich-text fields require separate handling')
        if kind == pikepdf.Name.Sig:
            unsupported.append('Signature fields require a separate derivative workflow')
        if kind == pikepdf.Name.Tx:
            for attr in ('/V', '/DV'):
                if attr in effective and not isinstance(effective[attr], pikepdf.String):
                    unsupported.append('Text field values must be ordinary strings')
        if kind == pikepdf.Name.Ch:
            options = node.get('/Opt'); exports = []
            if not _array(options) or not len(options):
                unsupported.append('Choice fields need their existing nonempty ordinary options array')
            else:
                for option in options:
                    if isinstance(option, pikepdf.String): exports.append(str(option))
                    elif _array(option) and len(option) == 2 and all(isinstance(item, pikepdf.String) for item in option): exports.append(str(option[0]))
                    else: unsupported.append('Choice options need ordinary export/display strings')
                if len(exports) != len(set(exports)): unsupported.append('Choice export values are not unique')
            for attr in ('/V', '/DV'):
                if attr not in effective: continue
                selected = effective[attr]
                selections = list(selected) if _array(selected) and flags & 2097152 else [selected]
                if any(not isinstance(item, pikepdf.String) or str(item) not in exports for item in selections):
                    unsupported.append('Choice values do not resolve to existing explicit options')
            selected_indices = node.get('/I')
            if selected_indices is not None:
                if not _array(selected_indices) or any(not integer(index) or index not in range(len(exports)) for index in selected_indices):
                    unsupported.append('Choice selection indices do not resolve to existing options')
                elif list(selected_indices) != sorted(set(selected_indices)):
                    unsupported.append('Choice selection indices are duplicated or unsorted')
                elif '/V' in effective:
                    current = effective['/V']; selections = list(current) if _array(current) else [current]
                    if [str(item) for item in selections] != [exports[index] for index in selected_indices]:
                        unsupported.append('Choice selection indices disagree with the current value')
        tooltip = node.get('/TU')
        if tooltip is not None and not isinstance(tooltip, pikepdf.String):
            unsupported.append('Field tooltip is not an ordinary text string')
        leaf = {'field': key, 'name': name, 'type': str(kind), 'flags': flags,
                'tooltip': str(tooltip) if isinstance(tooltip, pikepdf.String) else None,
                'widgets': [], 'issues': []}
        if not isinstance(tooltip, pikepdf.String) or not str(tooltip).strip():
            leaf['issues'].append('Missing nonempty accessible name/tooltip')
        for widget in members:
            ident = indirect(widget)
            if ident not in widgets:
                unsupported.append('A field Widget is absent from a unique page Annots entry'); continue
            if ident in terminal_widgets: unsupported.append('A Widget has more than one terminal field owner')
            terminal_widgets[ident] = key
            if not merged and indirect(widget.get('/Parent')) != key:
                unsupported.append('Widget Parent does not match its terminal field')
            if not merged and any(attr in widget for attr in ('/FT', '/Ff', '/V', '/DV', '/TU')):
                unsupported.append('A separate Widget contains conflicting field-state/name entries')
            if any(attr in widget for attr in ('/A', '/AA')):
                unsupported.append('Widget actions require separate handling')
            actual, number, index = widgets[ident]
            if '/P' in actual and indirect(actual.get('/P')) != indirect(pdf.pages[number - 1].obj):
                unsupported.append('Widget P does not match its page Annots owner')
            rect, widget_flags = actual.get('/Rect'), actual.get('/F', 0)
            if not _array(rect) or len(rect) != 4 or any(not isinstance(value, (int, float, Decimal)) or isinstance(value, bool) for value in rect):
                unsupported.append('Widget rectangle is malformed')
            elif any(not math.isfinite(float(value)) for value in rect) or float(rect[2]) <= float(rect[0]) or float(rect[3]) <= float(rect[1]):
                unsupported.append('Widget rectangle is empty or reversed')
            if not integer(widget_flags) or not 0 <= widget_flags < 2**32 or widget_flags & (1 | 2 | 32):
                unsupported.append('Invisible, hidden or malformed widget flags require separate handling')
            appearances = actual.get('/AP')
            normal = appearances.get('/N') if plain(appearances) else None
            if kind == pikepdf.Name.Btn:
                if not plain(normal) or '/Off' not in normal or len(normal) != 2 or any(not isinstance(value, pikepdf.Stream) for value in normal.values()):
                    unsupported.append('Checkbox needs exactly Off/on normal appearance streams')
                else:
                    states = set(normal.keys()); current = actual.get('/AS'); selected = effective.get('/V', pikepdf.Name.Off)
                    if not isinstance(current, pikepdf.Name) or str(current) not in states or not isinstance(selected, pikepdf.Name) or current != selected:
                        unsupported.append('Checkbox V and AS do not resolve to the same existing appearance state')
                    default = effective.get('/DV')
                    if default is not None and (not isinstance(default, pikepdf.Name) or str(default) not in states):
                        unsupported.append('Checkbox default value has no existing appearance state')
            elif not isinstance(normal, pikepdf.Stream):
                unsupported.append('Text/choice widget needs an existing normal appearance stream')
            if isinstance(normal, pikepdf.Stream) and not normal.read_bytes():
                unsupported.append('Normal appearance stream is empty')
            leaf['widgets'].append({'widget': ident, 'page': number, 'index': index})
        leaves.append(leaf)

    for node in roots: field(node)
    if set(widgets) != set(terminal_widgets): unsupported.append('Page Widgets and terminal field Widgets do not match exactly')
    if len(widgets) > 200 or len(pdf.pages) > 50: unsupported.append('Form exceeds the bounded widget/page scope')
    tree = pdf.Root.get('/StructTreeRoot')
    rolemap = tree.get('/RoleMap', {}) if plain(tree) else {}
    if not plain(tree): unsupported.append('Form Widgets require an existing rooted structure tree')
    tag_nodes, tag_parents, object_owners, tag_seen, tag_order = {}, {}, defaultdict(list), set(), defaultdict(list)
    pt_errors, parent_tree, pt_seen = [], {}, set()
    def form_number_tree(node, depth=0):
        if not plain(node) or depth > 50:
            pt_errors.append('Malformed or excessive-depth ParentTree node'); return []
        key = indirect(node)
        if key is not None:
            if key in pt_seen:
                pt_errors.append('Shared or cyclic ParentTree node'); return []
            pt_seen.add(key)
        nums, kids = node.get('/Nums'), node.get('/Kids')
        if (nums is None) == (kids is None):
            pt_errors.append('ParentTree needs either Nums or Kids'); return []
        keys = []
        if nums is not None:
            if not _array(nums) or len(nums) % 2:
                pt_errors.append('Malformed ParentTree Nums carrier'); return []
            for index in range(0, len(nums), 2):
                number = nums[index]
                if not integer(number) or number < 0 or number in parent_tree:
                    pt_errors.append('Invalid or duplicate ParentTree integer key'); continue
                parent_tree[number] = nums[index + 1]; keys.append(number)
        elif not _array(kids) or not len(kids):
            pt_errors.append('Malformed ParentTree Kids carrier')
        else:
            for child in kids: keys.extend(form_number_tree(child, depth + 1))
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            pt_errors.append('ParentTree keys/ranges are not strictly ordered')
        limits = node.get('/Limits')
        if depth and (not keys or limits is None):
            pt_errors.append('Nonroot ParentTree node needs a nonempty key range')
        if limits is not None and (not _array(limits) or len(limits) != 2 or any(not integer(item) for item in limits)
                                  or not keys or list(limits) != [keys[0], keys[-1]]):
            pt_errors.append('ParentTree Limits do not match the actual key range')
        return keys
    if plain(tree): form_number_tree(tree.get('/ParentTree'))
    if plain(tree) and '/ParentTreeNextKey' in tree:
        next_key = tree['/ParentTreeNextKey']
        if not integer(next_key) or next_key <= max(parent_tree, default=-1):
            pt_errors.append('Provided ParentTreeNextKey does not exceed the actual key range')
    if pt_errors: unsupported.extend('ParentTree: ' + message for message in pt_errors)

    def tags(node, parent=None, inherited_page=None, depth=0):
        if cancelled(cancel): raise InterruptedError('Form tag inspection cancelled')
        if depth > 200 or len(tag_seen) > 50000:
            unsupported.append('Structure exceeds the bounded form inspection traversal'); return
        if _array(node):
            for child in node: tags(child, parent, inherited_page, depth + 1)
            return
        if not plain(node): return
        page = page_numbers.get(_id(node.get('/Pg')), inherited_page) if '/Pg' in node else inherited_page
        if node.get('/Type') == pikepdf.Name.OBJR:
            target = indirect(node.get('/Obj'))
            object_owners[target].append((parent, page))
            if target in annotation_pages: tag_order[annotation_pages[target]].append(target)
            return
        if '/S' not in node: return
        key = indirect(node)
        if key is None or key in tag_seen:
            unsupported.append('Structure elements are direct, shared or cyclic'); return
        tag_seen.add(key); tag_nodes[key] = node; tag_parents[key] = parent
        if parent is not None and indirect(node.get('/P')) != parent:
            unsupported.append('Structure parent does not match the rooted child occurrence')
        tags(node.get('/K'), key, page, depth + 1)

    if plain(tree): tags(tree.get('/K'), indirect(tree))
    structure, mark_owners, _, _, _ = _structure(pdf, page_numbers)
    if structure['errors']: unsupported.append('Form label structure has incomplete or ambiguous references')
    label_page_content = {}
    def descendant(key, owner):
        visited = set()
        while key in tag_parents and key not in visited:
            if key == owner: return True
            visited.add(key); key = tag_parents[key]
        return key == owner
    def label_content(number):
        if number not in label_page_content:
            page = pdf.pages[number - 1]
            info, definitions, paints = _page_content(page, number, mark_owners, parent_tree, {})
            nontext, replacements, stack = Counter(), set(), []
            for instruction in pikepdf.parse_content_stream(page):
                operator = str(getattr(instruction, 'operator', 'INLINE IMAGE'))
                operands = getattr(instruction, 'operands', [])
                if operator in {'BMC', 'BDC'}:
                    props = operands[1] if operator == 'BDC' and len(operands) == 2 else None
                    if isinstance(props, pikepdf.Name): props = page.resources.get('/Properties', {}).get(str(props))
                    mcid = props.get('/MCID') if plain(props) else None
                    if plain(props) and any(attr in props for attr in ('/ActualText', '/Alt', '/E', '/Lang')):
                        covered = [item['mcid'] for item in stack if item['mcid'] is not None]
                        if integer(mcid): covered.append(mcid)
                        replacements.update(covered)
                    stack.append({'mcid': mcid if integer(mcid) else None, 'artifact': bool(operands and operands[0] == pikepdf.Name.Artifact)})
                elif operator == 'EMC':
                    if stack: stack.pop()
                elif operator in PAINT and not any(item['artifact'] for item in stack):
                    mcid = next((item['mcid'] for item in reversed(stack) if item['mcid'] is not None), None)
                    if mcid is not None and operator not in {'Tj', 'TJ', "'", '"'}: nontext[mcid] += 1
            label_page_content[number] = info, definitions, paints, nontext, replacements
        return label_page_content[number]
    for leaf in leaves:
        for widget in leaf['widgets']:
            key = widget['widget']; annotation = widgets[key][0]; owners = object_owners.get(key, [])
            owner, number = owners[0] if len(owners) == 1 else (None, None)
            node = tag_nodes.get(owner)
            if len(owners) != 1 or not plain(node) or _resolved_owner_role(node, rolemap) != '/Form' or number != widget['page']:
                unsupported.append('A Widget lacks one same-page rooted Form OBJR owner'); continue
            scope = {key for key in tag_nodes if descendant(key, owner)}
            scoped_objrs = [(target, entry) for target, entries in object_owners.items() for entry in entries if entry[0] in scope]
            if len(scoped_objrs) != 1 or scoped_objrs[0][0] != key:
                unsupported.append('Each Form subtree must retain exactly its one existing Widget OBJR')
            for child in scope - {owner}:
                if _resolved_owner_role(tag_nodes[child], rolemap) not in {'/P', '/Span'}:
                    unsupported.append('Nested interactive or non-text Form label subtrees require separate handling')
                if any(attr in tag_nodes[child] for attr in ('/ActualText', '/Alt', '/E', '/Ref', '/AF', '/C', '/R')):
                    unsupported.append('Replacement/class attributes cover an existing Form label')
            for ref in structure['references']:
                if ref['element'] not in scope: continue
                if ref['page'] != widget['page'] or ref['stream'] != 'page':
                    unsupported.append('Form labels require proven same-page direct marked content'); continue
                info, definitions, paints, nontext, replacements = label_content(widget['page'])
                mark = (widget['page'], 'page', ref['mcid'])
                if (info['errors'] or info['duplicate_mcids'] or definitions[mark] != 1 or paints[mark] < 1
                        or mark_owners.get(mark) != [ref['element']] or nontext[ref['mcid']] or ref['mcid'] in replacements
                        or any(item['stream'] == 'page' and item['mcid'] == ref['mcid'] for item in info['parent_tree_failures'])):
                    unsupported.append('A Form label lacks unique painted text and exact ParentTree ownership')
            if any(attr in node for attr in ('/ActualText', '/E', '/Ref', '/AF', '/C', '/R', '/A')):
                unsupported.append('Protected replacement/class/revision attributes cover a Form owner')
            ancestry, ancestry_seen = tag_parents.get(owner), set()
            while ancestry in tag_nodes and ancestry not in ancestry_seen:
                ancestry_seen.add(ancestry)
                if any(attr in tag_nodes[ancestry] for attr in ('/Alt', '/ActualText', '/E', '/Ref', '/AF', '/C', '/R')):
                    unsupported.append('Protected alternate/replacement/class attributes cover the Form ancestry')
                ancestry = tag_parents.get(ancestry)
            slot = annotation.get('/StructParent')
            if not integer(slot) or indirect(parent_tree.get(slot)) != owner:
                unsupported.append('Widget StructParent does not resolve back to its exact Form owner')
            alternative = node.get('/Alt')
            if alternative is not None and not isinstance(alternative, pikepdf.String):
                unsupported.append('A tagged Form alternative is not ordinary text')
            widget.update(element=owner, alternative=str(alternative) if isinstance(alternative, pikepdf.String) else None)
        issues.extend(leaf['name'] + ': ' + message for message in leaf['issues'])
    for number, ids in page_annotations.items():
        if not ids: continue
        linked = tag_order[number]
        if len(linked) != len(ids) or len(set(linked)) != len(linked) or set(linked) != set(ids):
            unsupported.append('A page annotation lacks a unique complete rooted annotation tag sequence')
        for ident in ids:
            annotation = all_annotations[ident]
            if any(attr in annotation for attr in ('/A', '/AA')):
                unsupported.append('Annotation actions require separate form-navigation handling')
            owners = object_owners.get(ident, [])
            owner = owners[0][0] if len(owners) == 1 else None
            if not integer(annotation.get('/StructParent')) or indirect(parent_tree.get(annotation.get('/StructParent'))) != owner:
                unsupported.append('An annotation ParentTree slot does not match its actual tag owner')
            subtype = annotation.get('/Subtype')
            if not isinstance(subtype, pikepdf.Name) or subtype not in {pikepdf.Name.Widget, pikepdf.Name.Link}:
                unsupported.append('Other annotation types require separate navigation handling')
            if subtype == pikepdf.Name.Link and (len(owners) != 1 or owners[0][1] != number or _resolved_owner_role(tag_nodes.get(owner), rolemap) != '/Link'):
                unsupported.append('A Link annotation lacks its unique same-page Link tag owner')
            if subtype == pikepdf.Name.Link:
                destination = annotation.get('/Dest')
                if not _array(destination) or len(destination) < 2 or _id(destination[0]) not in page_numbers or not isinstance(destination[1], pikepdf.Name):
                    unsupported.append('Mixed-page Links require an ordinary explicit local page destination')
        tabs = pdf.pages[number - 1].obj.get('/Tabs')
        if tabs is not None and (not isinstance(tabs, pikepdf.Name) or str(tabs) not in {'/R', '/C', '/S'}):
            unsupported.append('Page tab order has an unsupported representation or PDF version')
        page_row = {'page': number, 'tabs': str(tabs) if isinstance(tabs, pikepdf.Name) else None,
                    'annotation_count': len(ids), 'tag_annotation_order': linked, 'issues': []}
        if tabs != pikepdf.Name.S:
            page_row['issues'].append('Page tab order is not explicitly based on structure')
            issues.append('Page ' + str(number) + ': tab order is not explicitly based on structure')
        result['pages'].append(page_row)
    result['fields'] = leaves
    result['unsupported_reasons'] = sorted(set(unsupported)); result['issues'] = sorted(set(issues))
    result['supported_structure'] = bool(leaves and widgets) and not unsupported
    result['status'] = 'needs-review' if unsupported else 'fail' if issues else 'pass'
    return result


def inspect_pdf(path, cancel=None):
    """Return bounded structural, preservation and feature evidence for one PDF."""
    path = Path(path).resolve()
    report = {"schema_version": SCHEMA_VERSION, "path": str(path), "sha256": None,
              "status": "error", "checks": [], "limitations": [
                  "Supplemental evidence only: no complete PDF/UA or WCAG claim.",
                  "Content coverage counts paint operators, not glyphs, words, area, semantic correctness or contrast.",
                  "scanned/mixed classification infers image-containing pages; photographs cannot be distinguished from scanned text automatically.",
                  "Glyph coverage, language appropriateness, alt-text meaning and reading order require separate assessment."]}
    try:
        if cancelled(cancel):
            raise InterruptedError("PDF inspection cancelled")
        report["sha256"] = _sha(path)
        with pikepdf.open(path) as pdf:
            page_numbers = {_id(page.obj): index + 1 for index, page in enumerate(pdf.pages)}
            structure, refs, objrefs, elements, parent_tree = _structure(pdf, page_numbers)
            fonts = {}
            pages = []
            all_definitions = set(); all_painted = Counter()
            # Spread a bounded language sample across the document, rather than
            # treating a title page or an English preface as the whole book.
            sample_count = min(len(pdf.pages), 50)
            sample_indices = ({1} if sample_count == 1 else
                {1 + round(i * (len(pdf.pages) - 1) / (sample_count - 1)) for i in range(sample_count)})
            language_samples, language_pages = [], []
            pdfium_doc = pdfium.PdfDocument(str(path))
            try:
                for index, page in enumerate(pdf.pages, 1):
                    if cancelled(cancel):
                        raise InterruptedError("PDF inspection cancelled")
                    content, definitions, painted = _page_content(page, index, refs, parent_tree, fonts)
                    all_definitions.update(definitions); all_painted.update(painted)
                    render_page = pdfium_doc[index - 1]
                    text_page = render_page.get_textpage()
                    try:
                        text = text_page.get_text_range()
                    finally:
                        text_page.close()
                        render_page.close()
                    if index in sample_indices:
                        language_samples.append(text[:2000])
                        language_pages.append(index)
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
                from .small_font import assess as assess_small_font
                report['small_font'] = assess_small_font(path, cancel=cancel, pdf=pdf, document=pdfium_doc)
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
            report['empty_tags'] = _empty_structure_tags(pdf, page_numbers, structure=structure, refs=refs,
                parent_tree=parent_tree, painted=all_painted, cancel=cancel)
            form_accessibility = _form_accessibility(pdf, page_numbers, cancel)
            if form_accessibility['present']:
                report['form_accessibility'] = form_accessibility
            elif 'empty_container' in form_accessibility:
                report['empty_form_container'] = form_accessibility['empty_container']
            acroform = pdf.Root.get("/AcroForm", {})
            if not _dict(acroform): acroform = {}
            signed = bool(acroform.get("/SigFlags", 0)) or any(_dict(obj) and (obj.get("/Type") == pikepdf.Name.Sig or obj.get("/FT") == pikepdf.Name.Sig) for obj in pdf.objects)
            from .credentials import has_attachment_signals
            features = {"encrypted": bool(pdf.is_encrypted), "signed_or_signature_fields": signed,
                        "forms": form_accessibility['present'],
                        "attachments": has_attachment_signals(pdf, cancel=cancel),
                        "javascript": bool(pdf.Root.get("/Names", {}).get("/JavaScript")),
                        "optional_content": "/OCProperties" in pdf.Root,
                        "equation_tags": structure["tag_counts"].get("/Formula", 0),
                        "annotation_count": sum(len(p["annotations"]) for p in pages),
                        "pdf_version": str(pdf.pdf_version)}
            if '/AF' in pdf.Root:
                from .credentials import inspect_credentials
                report['content_credentials'] = inspect_credentials(pdf, cancel=cancel)
            checks = report["checks"]
            if form_accessibility['present']:
                checks.append(_check('form-accessibility', form_accessibility['status'], form_accessibility,
                    'Independent static field/Widget/Form OBJR/ParentTree, accessible-name and structure-tab-order screen',
                    form_accessibility['limitations']))
            parse_errors = [e for p in pages for e in p["content"]["errors"]] + structure["errors"]
            linkage_failures = sum(len(p["content"]["parent_tree_failures"]) + len(p["content"]["duplicate_mcids"]) for p in pages)
            uncovered = sum(p["content"]["counts"].get("uncovered_paints", 0) for p in pages)
            total = sum(p["content"]["counts"].get("paint_operations", 0) for p in pages)
            integrity_status = "error" if parse_errors else "fail" if phantom or structure["phantom_tree"] or structure["ambiguous_content_references"] or linkage_failures else "pass"
            checks.append(_check("content-linkage", integrity_status, {"phantom_tree": structure["phantom_tree"], "linkage_class": structure["linkage_class"], "missing_references": len(phantom), "matched_content_definitions": matched_refs, "existing_object_targets": existing_obj_targets, "parent_or_duplicate_failures": linkage_failures, "parse_errors": parse_errors}, "Parsed page and Form content; MCID->structure and ParentTree back-links", ["Matched definitions count actual MCID sequences; existing OBJR targets count object existence, with Link ParentTree linkage assessed separately. A partial dangling-reference defect is not a wholly phantom tree."]))
            checks.append(_check("content-coverage", "error" if parse_errors else "fail" if uncovered else "pass" if total else "not-applicable", {"paint_operations": total, "uncovered_paints": uncovered}, "Every parsed text/image/vector/shading paint operator", ["Artifacts are counted separately; their semantic correctness requires review."]))
            annotation_failures = []
            tree = pdf.Root.get("/StructTreeRoot")
            rolemap = tree.get("/RoleMap", {}) if _dict(tree) else {}
            for page in pages:
                for annotation in page["annotations"]:
                    if annotation["subtype"] != "/Link":
                        continue
                    owners = objrefs.get(annotation["object"], [])
                    parent = parent_tree.get(annotation["struct_parent"])
                    owner_role = _resolved_owner_role(elements.get(owners[0]), rolemap) if len(owners) == 1 else ""
                    if len(owners) != 1 or parent is None or _id(parent) != owners[0] or owner_role != "/Link":
                        annotation_failures.append({"page": page["page"], "object": annotation["object"], "resolved_owner_role": owner_role})
            checks.append(_check("link-structure", "fail" if annotation_failures else "pass" if any(a["subtype"] == "/Link" for p in pages for a in p["annotations"]) else "not-applicable", {"unlinked_links": annotation_failures}, "Link annotation OBJR, /StructParent linkage and effective Link owner role", ["Link purpose, activation and accessible name are not assessed."]))
            checks.append(_check("metadata", "pass" if metadata["title"].strip() and metadata["language"].strip() and metadata["display_doc_title"] else "fail", metadata, "Presence of title/language and document-title display", ["Meaningful title and appropriate language require review; XMP conformance is delegated to veraPDF."]))
            figures = structure["figures"]
            checks.append(_check("figure-alternatives", "fail" if any(not f["alt"] for f in figures) else "needs-review" if figures else "not-applicable", {"figure_count": len(figures), "missing_alt": sum(not f["alt"] for f in figures), "placeholder_signals": sum(f["placeholder_signal"] for f in figures)}, "Tagged /Figure elements only", ["A plausible alternative is not proof of adequate description; untagged image semantics remain unknown."]))
            headers = structure["table_headers"]
            if structure["tag_counts"].get("/Table"):
                relationships = _table_relationships(pdf, page_numbers, cancel)
                report["table_relationships"] = relationships
                checks.append(_check("table-header-associations", relationships["status"], relationships,
                    "Bounded raw table grid, header hierarchy, Scope, Headers, document IDs and IDTree integrity",
                    relationships["limitations"]))
            else:
                checks.append(_check("table-header-associations", "not-applicable", {"headers": headers, "tables": 0}, "Inventory /TH Scope and Headers/ID evidence", ["Header relationships require a tagged table."]))
            used_fonts = [f for f in fonts.values() if f["used_text_operations"]]
            checks.append(_check("font-embedding", "error" if parse_errors else "fail" if any(not f["embedded"] for f in used_fonts) else "pass" if used_fonts else "not-applicable", {"font_resource_count": len(fonts), "used_font_count": len(used_fonts), "unused_font_count": len(fonts) - len(used_fonts), "unembedded_used": [f["base_font"] for f in used_fonts if not f["embedded"]]}, "Fonts selected at parsed text-showing operators in pages and traversed Form XObjects", ["Unused font resources are inventoried but do not fail embedding. Annotation appearance, pattern and Type3 CharProc fonts, embedding permissions, glyph coverage, widths and damaged programs are not tested."]))
            checks.append(_check("font-unicode-mapping", _aggregate([{"status": f["mapping_status"]} for f in used_fonts]) if used_fonts else "not-applicable", {"fonts": list(fonts.values())}, "ToUnicode CMap shape and alternative mapping signals for fonts used at text-showing operators", ["Absence of ToUnicode alone is not failure; used-code coverage is not tested."]))
            checks.append(_check("heading-navigation", "fail" if navigation["errors"] else "needs-review", {"headings": structure["headings"], "bookmark_count": len(navigation["bookmarks"]), "navigation_errors": navigation["errors"]}, "Heading/bookmark inventory", ["Heading purpose, hierarchy and navigation adequacy require review."]))
            from .heading_checks import assess_headings
            checks.extend(assess_headings(structure, len(pages)))
            from .language import assess_language
            language_assessment = assess_language("\n\n".join(language_samples)[:100000], metadata["language"])
            language_assessment["sampling"] = {"sampled_pages": language_pages, "total_pages": len(pages),
                "maximum_pages": 50, "maximum_characters_per_page": 2000,
                "maximum_total_characters": 100000, "complete_document_text_assessed": False}
            from .language_scopes import assess_language_scopes
            language_assessment = assess_language_scopes(path, pdf, language_assessment,
                sampled_pages=language_pages, structure=structure, owners=refs, elements=elements,
                parent_tree=parent_tree, page_contents={p["page"]: p["content"] for p in pages}, cancel=cancel)
            checks.append({**_check("language-correctness", language_assessment["status"], language_assessment,
                "Conservative local language markers in sampled selectable text",
                language_assessment.get("limitations", [])),
                "fix_path": ("Review the affected page or passage and its declared/inherited language. Save and explicitly accept the appropriate local language choice, then Apply accepted edits. Scoped diagnostic suggestions do not authorize a document-language change."
                    if language_assessment.get("profile") == "local-declared-language-scopes-1" else
                    "Review the suggested language against the document. Edit Document language, explicitly accept it, then Apply accepted edits. No language is changed automatically.")})
            special = {k: features[k] for k in ("forms", "attachments", "signed_or_signature_fields", "javascript", "optional_content", "equation_tags") if features[k]}
            checks.append(_check("special-features", "needs-review" if special else "not-applicable", special, "Catalog feature signals and /Formula tag inventory", ["Untagged visual equations and slide-like layouts cannot be reliably detected from this inventory."]))
            checks.append(_check("reading-order", "not-tested", {}, "No semantic reading-order test"))
            from .contrast import inspect_contrast
            contrast = inspect_contrast(path, cancel_event=cancel)
            checks.append({**_check("contrast", contrast["status"], contrast,
                "Bounded digital-text contrast measurements against a rendered background",
                contrast.get("limitations", [])),
                "fix_path": "Use the reported page, text and colors to improve contrast in the source document, export a separate PDF and process it again. Automatic recoloring is unavailable because it changes appearance."})
            report.update({"page_count": len(pages), "pages": pages, "structure": structure,
                           "fonts": list(fonts.values()), "metadata": metadata, "navigation": navigation,
                           "features": features, "status": _aggregate(checks),
                           "tools": {"pikepdf": version("pikepdf"), "pypdfium2": version("pypdfium2")}})
    except InterruptedError:
        raise
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


_NAVIGATION_REVIEW_KINDS = frozenset({"annotation-name", "link-name", "link-target", "bookmark-entry", "bookmark-additions"})


def _navigation_record(record, navigation, *, annotation=False):
    """Independent common-field normalization, never an action/name exemption."""
    ignored = {"object", "struct_parent"} if annotation else set()
    result = {key: copy.deepcopy(value) for key, value in record.items() if key not in ignored}
    if "destination" in result:
        result["destination"] = _resolve_destination(result["destination"], navigation)
    if result.get("action") == "/GoTo":
        result["action"] = ""
    return result


def _navigation_semantics(inspected):
    navigation = inspected["navigation"]
    return {
        "bookmarks": [_navigation_record(item, navigation) for item in navigation["bookmarks"]],
        "annotations": [[_navigation_record(item, navigation, annotation=True) for item in page["annotations"]]
                        for page in inspected["pages"]],
        "named_destinations": [[name, _resolve_destination(value, navigation)]
                               for name, value in navigation["named_destinations"]],
        "page_labels": copy.deepcopy(navigation["page_labels"]),
        "errors": copy.deepcopy(navigation["errors"]),
    }


def _reviewed_navigation_baseline(baseline, candidate, review, checkpoint, original_sha256, cancel):
    """Derive exact authorized semantic deltas independently of the PDF writer.

    This deliberately does not call navigation_edits' mutation/oracle helpers.
    All existing annotation fields and the entire outline sequence remain exact
    unless the named, source-bound choice changes that particular field.
    """
    from . import sidecar

    if not isinstance(review, dict) or review.get("schema_version") != sidecar.SCHEMA_VERSION:
        raise ValueError("Reviewed navigation requires a complete decision sidecar")
    profile = sidecar.inventory_profile_for(review)
    if profile not in {sidecar.NAVIGATION_INVENTORY_PROFILE, sidecar.SEMANTIC_TREE_INVENTORY_PROFILE,
                       sidecar.TABLE_INVENTORY_PROFILE, sidecar.FORM_INVENTORY_PROFILE, sidecar.EMPTY_TAG_INVENTORY_PROFILE}:
        raise ValueError("Reviewed navigation requires its explicit inventory profile")
    if (not isinstance(original_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", original_sha256)
            or review.get("source_sha256") != original_sha256):
        raise ValueError("Reviewed navigation original fingerprint differs")
    if checkpoint is None:
        raise ValueError("Reviewed navigation requires its retained prepared checkpoint")
    checkpoint = Path(checkpoint).resolve()
    checkpoint_sha = _sha(checkpoint)
    if review.get("document_sha256") != checkpoint_sha:
        raise ValueError("Reviewed navigation prepared fingerprint differs")
    rows = review.get("decisions")
    if not isinstance(rows, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in rows):
        raise ValueError("Reviewed navigation decisions are malformed")
    if len({item["id"] for item in rows}) != len(rows):
        raise ValueError("Reviewed navigation has duplicate decision identities")
    if any(item.get("kind") in _NAVIGATION_REVIEW_KINDS and item.get("status") == "auto-accepted" for item in rows):
        raise ValueError("Navigation changes require named human acceptance")
    selected = [item for item in rows if item.get("kind") in _NAVIGATION_REVIEW_KINDS
                and item.get("status") == "approved" and item.get("value") != item.get("current")]
    if not selected:
        raise ValueError("Reviewed navigation has no changed accepted navigation choice")
    fresh = sidecar.collect_decisions(checkpoint, original_sha256,
                                      inventory_profile=profile, cancel=cancel)
    if fresh["inventory_errors"]:
        raise ValueError("Reviewed navigation inventory is incomplete")
    expected_rows = {item["id"]: item for item in fresh["decisions"]}
    if {item["id"] for item in rows} != set(expected_rows):
        raise ValueError("Reviewed navigation omits or broadens the checkpoint inventory")
    fields = ("kind", "binding", "context_sha256", "current", "element", "page", "structure_path", "references", *sidecar._STRUCTURAL_CONTEXT)
    for item in selected:
        original = expected_rows.get(item["id"])
        if original is None or any(item.get(key) != original.get(key) for key in fields):
            raise ValueError("Reviewed navigation occurrence or context differs")
        if item.get("structural_eligible") is not True:
            raise ValueError("Reviewed navigation occurrence is read-only")
        sidecar._validate_value(item)
        if not isinstance(item.get("approved_by"), str) or not item["approved_by"].strip():
            raise ValueError("Reviewed navigation has no named reviewer")
        sidecar._validate_date(item.get("approved_at"))
        if item.get("approval_sha256") != sidecar.approval_digest(item):
            raise ValueError("Reviewed navigation acceptance is stale")
    prepared = inspect_pdf(checkpoint, cancel)
    if prepared.get("error"):
        raise ValueError("Reviewed navigation checkpoint could not be independently inspected")
    if baseline["page_count"] != prepared["page_count"] or _navigation_semantics(baseline) != _navigation_semantics(prepared):
        raise ValueError("Original and prepared navigation do not have the same exact common-field baseline")
    # Indexing is deliberately conservative: every raw array member must be an
    # ordinary dictionary, so skipped malformed entries cannot shift a target.
    with pikepdf.open(checkpoint) as pdf:
        for page in pdf.pages:
            annotations = page.obj.get("/Annots", pikepdf.Array())
            if not isinstance(annotations, pikepdf.Array) or any(not isinstance(item, pikepdf.Dictionary) for item in annotations):
                raise ValueError("Malformed annotation arrays cannot establish a reviewed index")
    expected = copy.deepcopy(baseline)
    deltas = []
    annotation_targets, bookmark_targets, addition_plans = set(), set(), 0
    for item in selected:
        kind, context = item["kind"], item.get("navigation_context")
        if not isinstance(context, dict) or context.get("policy") != "reviewed-navigation-1":
            raise ValueError("Reviewed navigation is missing its source scope")
        if context.get("page_count") != baseline["page_count"]:
            raise ValueError("Reviewed navigation page count differs")
        if kind in {"annotation-name", "link-target"}:
            page, index = item.get("page"), context.get("annotation_index")
            if (isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= baseline["page_count"]
                    or isinstance(index, bool) or not isinstance(index, int) or index < 0
                    or index >= len(expected["pages"][page-1]["annotations"])):
                raise ValueError("Reviewed annotation index is outside the original page")
            location = (kind, page, index)
            if location in annotation_targets:
                raise ValueError("Duplicate reviewed annotation field")
            annotation_targets.add(location)
            record = expected["pages"][page-1]["annotations"][index]
            if kind == "annotation-name":
                if context.get("source_name") != record["contents"] or item["current"] != record["contents"]:
                    raise ValueError("Reviewed annotation name differs from the original")
                record["contents"] = item["value"]
            else:
                target = json.loads(item["value"])
                if target != json.loads(item["current"]):
                    record.update(destination=[target["page"], "/Fit"] if target["kind"] == "page" else "",
                                  action="" if target["kind"] == "page" else "/URI",
                                  uri=target["uri"] if target["kind"] == "uri" else "")
        elif kind == "bookmark-entry":
            index = context.get("bookmark_index")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(baseline["navigation"]["bookmarks"]):
                raise ValueError("Reviewed bookmark index is outside the original outline")
            if index in bookmark_targets:
                raise ValueError("Duplicate reviewed bookmark entry")
            bookmark_targets.add(index)
            value, current = json.loads(item["value"]), json.loads(item["current"])
            record = expected["navigation"]["bookmarks"][index]
            if current["title"] != record["title"]:
                raise ValueError("Reviewed bookmark title differs from the original")
            record["title"] = value["title"]
            # A title-only change leaves named destinations, fit and zoom exact.
            if value["target"] != current["target"]:
                target = value["target"]
                record.update(destination=[target["page"], "/Fit"] if target["kind"] == "page" else "",
                              action="" if target["kind"] == "page" else "/URI",
                              uri=target["uri"] if target["kind"] == "uri" else "")
        elif kind == "bookmark-additions":
            addition_plans += 1
            if addition_plans != 1 or json.loads(item["current"]) != {"entries": []}:
                raise ValueError("Only one source-bound new bookmark forest may be appended")
            for entry in json.loads(item["value"])["entries"]:
                expected["navigation"]["bookmarks"].append({"title": entry["title"], "depth": entry["level"]-1,
                    "destination": [entry["page"], "/Fit"], "action": "", "uri": ""})
        elif kind != "link-name":
            raise ValueError("Unsupported reviewed navigation field")
        deltas.append({"decision_id": item["id"], "kind": kind, "context_sha256": item["context_sha256"],
                       "page": item.get("page"), "previous_value": item["current"], "applied_value": item["value"]})
    raw_annotations = [_preserve_annotations(left["annotations"], right["annotations"], baseline["navigation"],
        candidate["navigation"], candidate["page_count"]) for left, right in zip(baseline["pages"], candidate["pages"])]
    evidence = {"policy": "exact-named-navigation-deltas-1", "original_sha256": original_sha256,
                "checkpoint_sha256": checkpoint_sha, "deltas": deltas,
                "raw_original_annotations": raw_annotations,
                "raw_original_bookmarks": _preserve_bookmarks(baseline["navigation"], candidate["navigation"],
                    baseline["page_count"], candidate["page_count"]),
                "expected_common_navigation_matches": _navigation_semantics(expected) == _navigation_semantics(candidate),
                "scope": "Only named source-bound common fields; full raw graph proof remains separately required"}
    return expected, evidence


def initialize_form_rendering(document, path, *, assessment=None, cancel=None):
    """Initialize only freshly proven static AcroForm widgets before page access.

    No document/page actions are invoked. The optional assessment is never used
    as authority over the fresh raw and canonical preflights. Ordinary PDFs keep
    their existing renderer path; unsupported form previews fail explicitly.
    """
    if cancelled(cancel): raise InterruptedError('Static form rendering cancelled')
    path = Path(path).resolve(); digest = _sha(path)
    from .form_edits import has_form_signals, preflight
    evidence = {'policy': FORM_RENDERING_POLICY, 'status': 'not-applicable',
        'source_sha256': digest, 'field_count': 0, 'widget_count': 0,
        'javascript_platform': 'disabled-null', 'xfa_disabled': True,
        'document_or_page_actions_invoked': False}
    with pikepdf.open(path) as pdf:
        if not has_form_signals(pdf):
            if _raw_form_signals(pdf, cancel) and not _inert_empty_acroform(pdf, cancel):
                raise ValueError('Unsupported form widgets cannot receive a complete static form preview')
            return evidence
        page_numbers = {_id(page.obj): number for number, page in enumerate(pdf.pages, 1)}
        independent = _form_accessibility(pdf, page_numbers, cancel)
        canonical_form = preflight(pdf, cancel=cancel)
        if (independent.get('policy') != 'bounded-acroform-1'
                or independent.get('supported_structure') is not True
                or canonical_form.get('policy') != 'reviewed-form-1'
                or canonical_form.get('supported') is not True):
            raise ValueError('Unsupported form widgets cannot receive a complete static form preview')
    if _sha(path) != digest: raise ValueError('Form source changed during rendering preflight')
    if cancelled(cancel): raise InterruptedError('Static form rendering cancelled')
    if document.formenv is not None:
        raise ValueError('Static form rendering must initialize a fresh document before page access')
    from pypdfium2 import raw as pdfium_raw
    configuration = pdfium_raw.FPDF_FORMFILLINFO(version=2, xfa_disabled=True, m_pJsPlatform=None)
    document.init_forms(configuration)
    if document.formenv is None:
        raise ValueError('The supported static form environment did not initialize')
    if cancelled(cancel): raise InterruptedError('Static form rendering cancelled')
    evidence.update(status='pass', field_count=canonical_form['field_count'], widget_count=canonical_form['widget_count'])
    return evidence


def compare_fidelity(before, after, dpi=96, max_changed_fraction=0.0, pixel_delta=0, cancel=None, *,
                     navigation_review=None, navigation_source=None, navigation_original_sha256=None):
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
        baseline = inspect_pdf(before, cancel)
        candidate = inspect_pdf(after, cancel)
        if "error" in baseline or "error" in candidate:
            raise ValueError(f"PDF inspection failed: {baseline.get('error') or candidate.get('error')}")
        if navigation_review is not None:
            baseline, navigation_evidence = _reviewed_navigation_baseline(baseline, candidate,
                navigation_review, navigation_source, navigation_original_sha256 or report["before_sha256"], cancel)
            report["reviewed_navigation"] = navigation_evidence
            report["checks"].append(_check("reviewed-navigation-exact-delta",
                "pass" if navigation_evidence["expected_common_navigation_matches"] else "fail",
                {"checkpoint_sha256": navigation_evidence["checkpoint_sha256"],
                 "decision_ids": [item["decision_id"] for item in navigation_evidence["deltas"]],
                 "expected_common_navigation_matches": navigation_evidence["expected_common_navigation_matches"]},
                "Exact reviewed common navigation fields; no unrelated annotation or outline changes permitted"))
        elif navigation_source is not None or navigation_original_sha256 is not None:
            raise ValueError("Navigation evidence requires the matching accepted review")
        form_signals = any(item.get('features', {}).get('forms') for item in (baseline, candidate))
        static_forms = form_signals and all(
            isinstance(item.get('form_accessibility'), dict)
            and item['form_accessibility'].get('policy') == 'bounded-acroform-1'
            and item['form_accessibility'].get('supported_structure') is True
            for item in (baseline, candidate))
        if form_signals:
            report['form_rendering'] = {'policy': FORM_RENDERING_POLICY,
                'status': 'pass' if static_forms else 'not-tested',
                'initialized_documents': [], 'javascript_platform': 'disabled-null',
                'xfa_disabled': True, 'document_or_page_actions_invoked': False}
            report['renderer']['form_widgets'] = 'supported-static' if static_forms else 'not-tested'
            if not static_forms:
                report['checks'].append(_check('form-widget-rendering', 'not-tested',
                    report['form_rendering'], 'Widget appearances require a proven static form structure',
                    ['Unsupported/dynamic forms are not initialized; page pixels alone cannot establish widget preservation.']))
        documents = []
        try:
            for path, digest, assessed in ((before, report['before_sha256'], baseline), (after, report['after_sha256'], candidate)):
                document = pdfium.PdfDocument(str(path))
                documents.append(document)
                if static_forms:
                    rendered = initialize_form_rendering(document, path, assessment=assessed.get('form_accessibility'), cancel=cancel)
                    if rendered['status'] != 'pass' or rendered['source_sha256'] != digest:
                        raise ValueError('Static widget rendering lost the exact compared source')
                    report['form_rendering']['initialized_documents'].append(digest)
            if static_forms:
                report['checks'].append(_check('form-widget-rendering', 'pass', report['form_rendering'],
                    'Existing static Widget appearances rendered with form environments; pixel/text comparisons remain separate'))
            same_count = len(documents[0]) == len(documents[1])
            report["checks"].append(_check("page-count", "pass" if same_count else "fail", {"before": len(documents[0]), "after": len(documents[1])}, "Whole document"))
            before_all, after_all = [], []
            for index in range(min(len(documents[0]), len(documents[1]))):
                if cancelled(cancel):
                    raise InterruptedError("Fidelity assessment cancelled")
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
