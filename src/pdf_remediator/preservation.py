"""Conservative, source-checked repair of a tagging engine's painting changes.

By default, text fragments may be coalesced only when their existing structure
owner is identical. Explicit tag-regrouping mode supports two bounded list
shapes and records every semantic reassignment for mandatory human review.
Unowned literal-space artifacts can be absorbed only when restoring one source
Tj whose substantive fragments already share one identical paragraph owner.
Unsupported changes refuse the whole checkpoint. Source-extracted line separators may be preserved only in the bounded plain
ASCII paragraph shape recorded by line_separators.py. A successful result still
needs independent validation and full-page rendering; this module cannot
declare a PDF an accessible candidate.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
from pathlib import Path

import pikepdf

VERSION = "source-aligned-painting-1.4"
TEXT = {"Tj", "TJ", "'", '"'}
MARK = {"BMC", "BDC", "EMC"}
STREAM_IGNORED = {"/Length", "/Filter", "/DecodeParms"}


class PreservationRefusal(ValueError):
    """The engine output cannot be repaired with the supported proof."""


def _ident(obj):
    return tuple(obj.objgen) if hasattr(obj, "objgen") else (0, 0)


def _value(obj, active=None):
    """Compare values rather than object numbers or numeric spelling."""
    active = set() if active is None else active
    if isinstance(obj, pikepdf.String):
        return ("string", bytes(obj))
    if isinstance(obj, pikepdf.Name):
        return ("name", str(obj))
    if isinstance(obj, (int, Decimal, bool, float)) or obj is None:
        return obj
    if isinstance(obj, (list, tuple)):
        return tuple(_value(value, active) for value in obj)
    if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream, pikepdf.Array)):
        ident = _ident(obj)
        if ident[0] and ident in active:
            raise PreservationRefusal("Cyclic painting resource")
        child_active = active | {ident} if ident[0] else active
        if isinstance(obj, pikepdf.Array):
            return tuple(_value(v, child_active) for v in obj)
        ignored = STREAM_IGNORED if isinstance(obj, pikepdf.Stream) else set()
        pairs = tuple((key, _value(value, child_active)) for key, value in sorted(obj.items()) if key not in ignored)
        if isinstance(obj, pikepdf.Stream):
            try:
                return (pairs, "decoded", hashlib.sha256(obj.read_bytes()).hexdigest())
            except pikepdf.PdfError:
                # Generalized stream decoding does not decode image codecs such
                # as JPEG. Preserve only byte-identical encoded image resources,
                # including every codec/filter parameter; never treat matching
                # compressed bytes with different interpretation as equivalent.
                filters = obj.get("/Filter")
                filters = list(filters) if isinstance(filters, pikepdf.Array) else [filters]
                image_codecs = {"/DCTDecode", "/JPXDecode", "/CCITTFaxDecode", "/JBIG2Decode"}
                if str(obj.get("/Subtype", "")) != "/Image" or not any(str(f) in image_codecs for f in filters):
                    raise
                encoded_pairs = tuple((key, _value(value, child_active)) for key, value in sorted(obj.items()) if key != "/Length")
                return (encoded_pairs, "encoded-image", hashlib.sha256(obj.read_raw_bytes()).hexdigest())
        return pairs
    raise PreservationRefusal(f"Unsupported painting resource value: {type(obj).__name__}")


def _same_instruction(left, right):
    return str(left.operator) == str(right.operator) and tuple(_value(v) for v in left.operands) == tuple(_value(v) for v in right.operands)


def _text_atoms(instruction):
    values = instruction.operands[0] if str(instruction.operator) == "TJ" else [instruction.operands[-1]]
    return [atom for value in values for atom in
            ([("byte", byte) for byte in bytes(value)] if isinstance(value, pikepdf.String) else [("adjustment", value)])]


def _text_slice(instruction, start, end):
    """Keep source TJ-array boundaries when coalescing only part of a run."""
    op, values, offset, result = str(instruction.operator), instruction.operands, 0, []
    entries = values[0] if op == "TJ" else [values[-1]]
    for value in entries:
        length = len(bytes(value)) if isinstance(value, pikepdf.String) else 1
        lo, hi = max(start - offset, 0), min(end - offset, length)
        if lo < hi:
            result.append(pikepdf.String(bytes(value)[lo:hi]) if isinstance(value, pikepdf.String) else value)
        offset += length
    if op == "TJ":
        return pikepdf.ContentStreamInstruction([pikepdf.Array(result)], pikepdf.Operator("TJ"))
    if start == 0:
        operands = list(values[:-1]) + result
        return pikepdf.ContentStreamInstruction(operands, instruction.operator)
    return pikepdf.ContentStreamInstruction(result, pikepdf.Operator("Tj"))


def _instructions(target):
    result = list(pikepdf.parse_content_stream(target))
    if any(not hasattr(i, "operator") for i in result):
        raise PreservationRefusal("Inline images are outside source-alignment support")
    return result


def _number_tree(node, result=None, seen=None):
    result, seen = ({} if result is None else result), (set() if seen is None else seen)
    if not isinstance(node, pikepdf.Dictionary):
        raise PreservationRefusal("Missing or malformed ParentTree")
    key = _ident(node)
    if key[0] and key in seen:
        raise PreservationRefusal("Cyclic ParentTree")
    if key[0]:
        seen.add(key)
    nums = node.get("/Nums", [])
    if len(nums) % 2:
        raise PreservationRefusal("Odd ParentTree /Nums array")
    for index in range(0, len(nums), 2):
        number = int(nums[index])
        if number in result:
            raise PreservationRefusal("Duplicate ParentTree key")
        result[number] = nums[index + 1]
    for child in node.get("/Kids", []):
        _number_tree(child, result, seen)
    return result


def _structure_refs(pdf):
    root = pdf.Root.get("/StructTreeRoot")
    if not isinstance(root, pikepdf.Dictionary):
        raise PreservationRefusal("Engine output has no structure tree")
    page_keys = {_ident(page.obj): index for index, page in enumerate(pdf.pages)}
    refs, seen = {}, set()

    def add(page, stream, mcid, owner):
        if page is None and stream == "page":
            raise PreservationRefusal("Structure content reference has no page")
        key = (page if stream == "page" else stream, int(mcid))
        if key in refs:
            raise PreservationRefusal("Ambiguous or duplicated structure MCID reference")
        refs[key] = owner

    def walk(node, page=None, owner=None, depth=0):
        if depth > 180:
            raise PreservationRefusal("Structure exceeds supported traversal depth")
        if isinstance(node, pikepdf.Array):
            for child in node:
                walk(child, page, owner, depth + 1)
        elif isinstance(node, int):
            add(page, "page", node, owner)
        elif isinstance(node, pikepdf.Dictionary):
            page = page_keys.get(_ident(node["/Pg"])) if "/Pg" in node else page
            kind = str(node.get("/Type", ""))
            if kind == "/MCR" or "/MCID" in node:
                add(page, _ident(node["/Stm"]) if "/Stm" in node else "page", node["/MCID"], owner)
            elif kind == "/OBJR":
                if not isinstance(node.get("/Obj"), pikepdf.Dictionary):
                    raise PreservationRefusal("Unresolved annotation reference")
            elif "/S" in node:
                ident = _ident(node)
                if ident in seen:
                    raise PreservationRefusal("Repeated or cyclic structure element")
                seen.add(ident)
                walk(node.get("/K"), page, node, depth + 1)
            else:
                raise PreservationRefusal("Unexpected structure child")
        elif node is not None:
            raise PreservationRefusal("Unsupported structure payload")

    walk(root.get("/K"))
    return refs, _number_tree(root.get("/ParentTree")), page_keys


def _scan(target, resources, stream_key, refs, parents, definitions):
    """Inventory every marking sequence; reject unknown properties and overlaps."""
    instructions = _instructions(target)
    active, records = [], []
    parent_number = target.obj.get("/StructParents") if isinstance(target, pikepdf.Page) else target.get("/StructParents")
    for index, instruction in enumerate(instructions):
        op, operands = str(instruction.operator), instruction.operands
        if op in ("BMC", "BDC"):
            if not operands:
                raise PreservationRefusal("Marked content without a role")
            if str(operands[0]) == "/OC":
                raise PreservationRefusal("Optional-content marking can change painting")
            props = operands[1] if op == "BDC" and len(operands) > 1 else None
            if isinstance(props, pikepdf.Name):
                props = resources.get("/Properties", {}).get(str(props))
                if not isinstance(props, pikepdf.Dictionary):
                    raise PreservationRefusal("Unresolved named marked-content property")
            if isinstance(props, pikepdf.Dictionary) and any(key in props for key in ("/ActualText", "/OC")):
                raise PreservationRefusal("Replacement text or optional-content properties are outside source-alignment support")
            key = None
            if isinstance(props, pikepdf.Dictionary) and "/MCID" in props:
                key = (stream_key, int(props["/MCID"]))
                if key in definitions:
                    raise PreservationRefusal("Repeated MCID definition")
                if key not in refs:
                    raise PreservationRefusal("Marked content has no structure owner")
                if parent_number is None:
                    raise PreservationRefusal("Marked stream has no StructParents key")
                slots = parents.get(int(parent_number))
                mcid = key[1]
                if not isinstance(slots, pikepdf.Array) or mcid < 0 or mcid >= len(slots) or slots[mcid] is None or _ident(slots[mcid]) != _ident(refs[key]):
                    raise PreservationRefusal("ParentTree owner does not match marked content")
                definitions[key] = (int(parent_number), refs[key])
            active.append({"key": key, "artifact": str(operands[0]) == "/Artifact", "start": index})
        elif op == "EMC":
            if not active:
                raise PreservationRefusal("Unbalanced marked-content sequence")
            active.pop()
        else:
            if op == "Do" and (not operands or str(operands[0]) not in resources.get("/XObject", {})):
                raise PreservationRefusal("Unresolved XObject invocation")
            records.append((index, instruction, tuple(dict(item) for item in active)))
    if active:
        raise PreservationRefusal("Unclosed marked-content sequence")
    return instructions, records


def _regroup_target(fragments, instructions, refs, owner_keys, definitions=None):
    """Recognize two precise list shapes; do not infer a general reading order."""
    keys, semantic = [], []
    for index, instruction, marking in fragments:
        if len(marking) != 1 or index != marking[0]["start"] + 1 or index + 1 >= len(instructions) or str(instructions[index + 1].operator) != "EMC":
            return None
        frame = marking[0]
        if frame["artifact"]:
            atoms = _text_atoms(instruction)
            if any(kind != "byte" or byte not in b" \t\r\n" for kind, byte in atoms):
                return None
            keys.append(None)
        elif frame["key"] is not None:
            key = frame["key"]
            keys.append(key)
            if not semantic or _ident(semantic[-1]) != _ident(refs[key]):
                semantic.append(refs[key])
        else:
            return None
    if len(semantic) != 2:
        return None
    first, body = semantic
    if str(body.get("/S")) != "/LBody":
        return None
    parent = body.get("/P")
    if not isinstance(parent, pikepdf.Dictionary) or str(parent.get("/S")) != "/LI":
        return None
    children = parent.get("/K")
    if not isinstance(children, pikepdf.Array) or len(children) != 2:
        return None
    label = first if str(first.get("/S")) == "/Lbl" else first.get("/P")
    if not isinstance(label, pikepdf.Dictionary) or str(label.get("/S")) != "/Lbl" or _ident(label.get("/P")) != _ident(parent):
        return None
    if [_ident(child) for child in children] != [_ident(label), _ident(body)]:
        return None
    # Do not erase IDs, alternate descriptions, replacement text or attributes.
    if set(label.keys()) - {"/Type", "/S", "/P", "/Pg", "/K"}:
        return None
    group_keys = {key for key in keys if key is not None}
    body_keys = owner_keys.get(_ident(body), set())
    body_payload = body.get("/K")
    if not isinstance(body_payload, pikepdf.Array) or not all(isinstance(k, int) for k in body_payload):
        return None
    label_payload = label.get("/K")
    if str(first.get("/S")) == "/Lbl":
        label_keys = owner_keys.get(_ident(label), set())
        if not label_keys <= group_keys or not isinstance(label_payload, pikepdf.Array) or not all(isinstance(k, int) for k in label_payload):
            return None
        selected = next(key for key in keys if key is not None and _ident(refs[key]) == _ident(body))
        return {"kind": "list-label-regroup", "selected": selected, "parent": parent, "label": label, "body": body, "link": None}
    if str(first.get("/S")) != "/Link" or not isinstance(label_payload, pikepdf.Array) or len(label_payload) != 1 or _ident(label_payload[0]) != _ident(first):
        return None
    if set(body.keys()) - {"/Type", "/S", "/P", "/Pg", "/K"}:
        return None
    # A TOC entry can paint its title and page number with separate source text
    # shows while both belong to one LBody. Replace only an ordered prefix of
    # its direct MCID children with the existing link, retaining the remaining
    # children in precisely their existing order. Nested relationships and an
    # unresolved trailing MCID cannot be proved by this bounded transformation.
    body_group_keys = [key for key in keys if key is not None and _ident(refs[key]) == _ident(body)]
    body_prefix = [key[1] for key in body_group_keys]
    body_values = list(body_payload)
    if body_values[:len(body_prefix)] != body_prefix:
        return None
    body_tail = body_values[len(body_prefix):]
    if body_tail:
        stream = body_group_keys[0][0]
        if definitions is None or any((stream, mcid) not in definitions or (stream, mcid) not in body_keys for mcid in body_tail):
            return None
    link_payload = first.get("/K")
    if not isinstance(link_payload, pikepdf.Array):
        return None
    objects = [k for k in link_payload if isinstance(k, pikepdf.Dictionary) and str(k.get("/Type")) == "/OBJR"]
    if len(objects) != 1 or any(not isinstance(k, int) and k not in objects for k in link_payload):
        return None
    if not owner_keys.get(_ident(first), set()) <= group_keys:
        return None
    annotation = objects[0].get("/Obj")
    if not isinstance(annotation, pikepdf.Dictionary) or str(annotation.get("/Subtype")) != "/Link":
        return None
    if ("/Dest" in annotation) == ("/A" in annotation):
        return None
    if "/Dest" not in annotation and str(annotation.get("/A", {}).get("/S")) not in {"/GoTo", "/URI"}:
        return None
    selected = next(key for key in keys if key is not None and _ident(refs[key]) == _ident(first))
    return {"kind": "single-target-list-link-expansion-preserving-tail" if body_tail else "single-target-list-link-expansion",
            "selected": selected, "parent": parent, "label": label, "body": body, "link": first, "body_tail": body_tail}


def _same_paragraph_with_artifact_spaces(source_instruction, fragments, instructions, refs):
    """Restore one source Tj split only by unowned literal-space artifacts.

    Every substantive fragment must already belong to one identical paragraph.
    This never joins distinct owners or accepts marked artifact properties,
    nested marking, text-state operations, adjustments or non-space artifacts.
    """
    if str(source_instruction.operator) != "Tj":
        return None
    selected, owner, semantic_keys, spaces = None, None, set(), 0
    for index, show, marking in fragments:
        if len(marking) != 1 or index != marking[0]["start"] + 1 or index + 1 >= len(instructions) or str(instructions[index + 1].operator) != "EMC":
            return None
        frame = marking[0]
        opening = instructions[frame["start"]]
        if frame["artifact"]:
            if frame["key"] is not None or str(opening.operator) != "BMC" or len(opening.operands) != 1 or str(show.operator) != "Tj":
                return None
            raw = bytes(show.operands[0])
            if not raw or any(value != 32 for value in raw):
                return None
            spaces += 1
        else:
            key = frame["key"]
            if key is None or str(opening.operator) != "BDC" or len(opening.operands) != 2 or str(opening.operands[0]) != "/P":
                return None
            properties = opening.operands[1]
            current = refs[key]
            if not isinstance(properties, pikepdf.Dictionary) or set(properties.keys()) != {"/MCID"} or str(current.get("/S")) != "/P":
                return None
            if owner is not None and _ident(current) != _ident(owner):
                return None
            selected, owner = (key if selected is None else selected), current
            semantic_keys.add(key)
    if selected is None or not spaces or not all(right[0] == left[0] + 3 for left, right in zip(fragments, fragments[1:])):
        return None
    ancestor, seen = owner, set()
    while isinstance(ancestor, pikepdf.Dictionary):
        identity = _ident(ancestor)
        if identity in seen or any(key in ancestor for key in ("/ActualText", "/Alt", "/E")) or len(seen) > 180:
            return None
        seen.add(identity)
        ancestor = ancestor.get("/P")
    return selected, semantic_keys, spaces


def _repair_stream(original, tagged, resources, stream_key, refs, parents, definitions, removals, changes, allow_tag_regrouping, semantic_reviews, owner_keys):
    source = _instructions(original)
    if any(str(i.operator) in MARK for i in source):
        raise PreservationRefusal("Source already contains marked content; preserve its original tags instead")
    instructions, records = _scan(tagged, resources, stream_key, refs, parents, definitions)
    replacements, consumed = {}, 0
    for source_instruction in source:
        op = str(source_instruction.operator)
        if op not in TEXT:
            if consumed >= len(records) or not _same_instruction(source_instruction, records[consumed][1]):
                raise PreservationRefusal(f"Unmatched source operator {op} in {stream_key}")
            # Preserve the source's exact operand values, including positions.
            replacements[records[consumed][0]] = source_instruction
            consumed += 1
            continue
        target_atoms, actual_atoms, fragments = _text_atoms(source_instruction), [], []
        while len(actual_atoms) < len(target_atoms) or not fragments:
            if consumed >= len(records) or str(records[consumed][1].operator) not in TEXT:
                raise PreservationRefusal(f"Unmatched source text-show in {stream_key}")
            record = records[consumed]
            fragment_op = str(record[1].operator)
            if not fragments and (op in {"'", '"'} and fragment_op != op or op in {"Tj", "TJ"} and fragment_op not in {"Tj", "TJ"}):
                raise PreservationRefusal("Engine changed a text positioning operation")
            if fragments and fragment_op in {"'", '"'}:
                if fragment_op != op or fragment_op == '"' and _value(record[1].operands[:2]) != _value(source_instruction.operands[:2]):
                    raise PreservationRefusal("Unsupported split text positioning")
                replacements[record[0]] = pikepdf.ContentStreamInstruction([record[1].operands[-1]], pikepdf.Operator("Tj"))
                changes["duplicated_quote_advances_removed"] += 1
            actual_atoms.extend(_text_atoms(record[1]))
            fragments.append(record)
            consumed += 1
            if len(actual_atoms) > len(target_atoms) or actual_atoms != target_atoms[:len(actual_atoms)]:
                raise PreservationRefusal("Engine text bytes or positioning adjustments differ from source")
        if len(fragments) == 1:
            replacements[fragments[0][0]] = source_instruction
            continue
        spaced = _same_paragraph_with_artifact_spaces(source_instruction, fragments, instructions, refs)
        if spaced is not None:
            selected, semantic_keys, spaces = spaced
            selected_record = next(record for record in fragments if record[2][0]["key"] == selected)
            replacements[fragments[0][0] - 1] = instructions[selected_record[0] - 1]
            replacements[fragments[0][0]] = source_instruction
            for record in fragments[1:]:
                for index in (record[0] - 1, record[0], record[0] + 1):
                    replacements[index] = None
            removals.update(semantic_keys - {selected})
            changes["same_paragraph_artifact_space_runs_restored"] += 1
            changes["literal_space_artifact_fragments_absorbed"] += spaces
            continue
        regroup = _regroup_target(fragments, instructions, refs, owner_keys, definitions) if allow_tag_regrouping else None
        if regroup is not None and all(right[0] == left[0] + 3 for left, right in zip(fragments, fragments[1:])):
            selected = regroup["selected"]
            selected_record = next(record for record in fragments if len(record[2]) == 1 and record[2][0]["key"] == selected)
            replacements[fragments[0][0] - 1] = instructions[selected_record[0] - 1]
            replacements[fragments[0][0]] = source_instruction
            for record in fragments[1:]:
                for index in (record[0] - 1, record[0], record[0] + 1):
                    replacements[index] = None
            removed = {frame["key"] for _, _, frames in fragments for frame in frames if frame["key"] is not None and frame["key"] != selected}
            removals.update(removed)
            if regroup["link"] is not None:
                link, body, parent = regroup["link"], regroup["body"], regroup["parent"]
                body["/K"] = pikepdf.Array([link] + regroup["body_tail"])
                link["/P"] = body
                parent["/K"] = pikepdf.Array([body])
            changes["opt_in_semantic_regroupings"] += 1
            semantic_reviews.append({"kind": regroup["kind"], "status": "pending", "stream": f"page:{stream_key + 1}" if isinstance(stream_key, int) else f"form:{stream_key[0]}:{stream_key[1]}",
                                     "page": stream_key + 1 if isinstance(stream_key, int) else None,
                                     "retained_mcid": selected[1], "removed_mcids": sorted(key[1] for key in removed),
                                     "retained_body_tail_mcids": list(regroup.get("body_tail", [])),
                                     "source_text_bytes_sha256": hashlib.sha256(bytes(atom for kind, atom in target_atoms if kind == "byte")).hexdigest(),
                                     "review": "Review the full text, list label/body relationships, link purpose where present, and reading order after the recorded semantic regrouping."})
            continue
        # Coalesce only flat, individually wrapped fragments with one identical
        # semantic owner. Mixed Lbl/LBody and Link/paragraph runs stay unchanged.
        keys = [record[2][0]["key"] if len(record[2]) == 1 and not record[2][0]["artifact"] else None for record in fragments]
        flat = all(key is not None and record[0] == record[2][0]["start"] + 1 and record[0] + 1 < len(instructions) and str(instructions[record[0] + 1].operator) == "EMC" for key, record in zip(keys, fragments))
        contiguous = all(right[0] == left[0] + 3 for left, right in zip(fragments, fragments[1:]))
        same_owner = flat and len({_ident(refs[key]) for key in keys}) == 1
        if flat and contiguous and same_owner:
            replacements[fragments[0][0]] = source_instruction
            for key, record in zip(keys[1:], fragments[1:]):
                for index in (record[0] - 1, record[0], record[0] + 1):
                    replacements[index] = None
                removals.add(key)
            changes["same_owner_text_runs_restored"] += 1
        else:
            changes["mixed_owner_text_runs_retained"] += 1
            # A label/link prefix need not prevent preservation of a following
            # paragraph run. Coalesce only contiguous fragments whose owner is
            # exactly identical; keep the surrounding roles and MCIDs intact.
            offsets, offset = [], 0
            for record in fragments:
                offsets.append(offset)
                offset += len(_text_atoms(record[1]))
            group_start = 0
            while group_start < len(fragments):
                group_end = group_start + 1
                first_key = keys[group_start]
                if first_key is not None:
                    while group_end < len(fragments) and keys[group_end] is not None and _ident(refs[keys[group_end]]) == _ident(refs[first_key]) and fragments[group_end][0] == fragments[group_end - 1][0] + 3:
                        group_end += 1
                group = fragments[group_start:group_end]
                group_flat = all(key is not None and record[0] == record[2][0]["start"] + 1 and record[0] + 1 < len(instructions) and str(instructions[record[0] + 1].operator) == "EMC" for key, record in zip(keys[group_start:group_end], group))
                if len(group) > 1 and group_flat:
                    last_offset = offsets[group_end] if group_end < len(offsets) else offset
                    replacements[group[0][0]] = _text_slice(source_instruction, offsets[group_start], last_offset)
                    for key, record in zip(keys[group_start + 1:group_end], group[1:]):
                        for index in (record[0] - 1, record[0], record[0] + 1):
                            replacements[index] = None
                        removals.add(key)
                    changes["same_owner_partial_text_runs_restored"] += 1
                group_start = group_end
    if consumed != len(records):
        raise PreservationRefusal("Engine added or reordered painting/state operators")
    return pikepdf.unparse_content_stream([replacements.get(index, instruction) for index, instruction in enumerate(instructions) if replacements.get(index, instruction) is not None])


def _prune_refs(pdf, removals, page_keys, parents, definitions, changes):
    """Remove only proved nonexistent/coalesced references, never reassign them."""
    root = pdf.Root.StructTreeRoot

    def prune(node, page=None):
        if isinstance(node, pikepdf.Array):
            values = [value for child in node if (value := prune(child, page)) is not None]
            return pikepdf.Array(values)
        if isinstance(node, int):
            return None if (page, node) in removals else node
        if not isinstance(node, pikepdf.Dictionary):
            return node
        page = page_keys.get(_ident(node["/Pg"])) if "/Pg" in node else page
        if "/MCID" in node:
            stream = _ident(node["/Stm"]) if "/Stm" in node else page
            return None if (stream, int(node["/MCID"])) in removals else node
        if "/S" in node and "/K" in node:
            old = node["/K"]
            new = prune(old, page)
            node["/K"] = pikepdf.Array() if new is None else new
            was_nonempty = not isinstance(old, pikepdf.Array) or bool(len(old))
            is_empty = isinstance(node["/K"], pikepdf.Array) and not len(node["/K"])
            if was_nonempty and is_empty:
                if any(key in node for key in ("/Alt", "/ActualText", "/E")):
                    raise PreservationRefusal("Removing a nonexistent reference would strand semantic replacement text")
                changes["empty_engine_structure_nodes_removed"] += 1
                return None
        return node

    root["/K"] = prune(root.get("/K")) or pikepdf.Array()
    for key in removals:
        stream, mcid = key
        if key in definitions:
            number = definitions[key][0]
        elif isinstance(stream, int):
            number = int(pdf.pages[stream].obj["/StructParents"])
        else:
            number = int(pdf.get_object(stream)["/StructParents"])
        values = parents.get(number)
        if isinstance(values, pikepdf.Array) and 0 <= mcid < len(values):
            values[mcid] = None


def preserve_painting(source, engine_output, destination, *, allow_tag_regrouping=False):
    """Write a separate source-aligned checkpoint, or refuse without publishing.

    ``status=pass`` means the bounded syntactic proof succeeded, not fidelity or
    accessibility. The caller MUST run strict independent validation, coverage,
    and all-page fidelity before candidate publication.
    """
    source, engine_output, destination = map(lambda p: Path(p).resolve(), (source, engine_output, destination))
    report = {"version": VERSION, "status": "needs-manual", "changes": {}, "warnings": [],
              "supported": False, "independent_validation_required": True, "all_page_fidelity_required": True,
              "allow_tag_regrouping": bool(allow_tag_regrouping), "semantic_review_required": [],
              "automatic_line_separators": []}
    if destination in {source, engine_output}:
        raise ValueError("Preservation must write a separate checkpoint")
    if destination.exists():
        raise FileExistsError(destination)
    changes, removals, definitions, semantic_reviews = Counter(), set(), {}, []
    try:
        with pikepdf.open(source) as original, pikepdf.open(engine_output) as tagged:
            if original.is_encrypted or tagged.is_encrypted or "/StructTreeRoot" in original.Root:
                raise PreservationRefusal("Encrypted or previously tagged input requires a different route")
            if any(key in original.Root for key in ("/AcroForm", "/OCProperties")) or any(isinstance(obj, pikepdf.Dictionary) and str(obj.get("/Type", "")) == "/Sig" for obj in original.objects):
                raise PreservationRefusal("Forms, signatures or optional content require a different route")
            if len(original.pages) != len(tagged.pages):
                raise PreservationRefusal("Engine changed page count")
            refs, parents, page_keys = _structure_refs(tagged)
            owner_keys = {}
            for key, owner in refs.items():
                owner_keys.setdefault(_ident(owner), set()).add(key)
            streams, active = {}, set()

            def pair_resources(before, after):
                for name in set(before.keys()) | set(after.keys()):
                    if name in {"/XObject", "/Properties"}:
                        continue
                    if _value(before.get(name)) != _value(after.get(name)):
                        raise PreservationRefusal(f"Engine changed painting resource {name}")
                left, right = before.get("/XObject", {}), after.get("/XObject", {})
                if set(left.keys()) != set(right.keys()):
                    raise PreservationRefusal("Engine changed XObject resource names")
                for name, item in left.items():
                    other = right[name]
                    if str(item.get("/Subtype")) != "/Form":
                        if _value(item) != _value(other):
                            raise PreservationRefusal("Engine changed an image/resource payload")
                        continue
                    ident = _ident(other)
                    if ident in active:
                        raise PreservationRefusal("Recursive Form XObject")
                    if ident in streams:
                        if streams[ident][0] != _ident(item):
                            raise PreservationRefusal("Ambiguous Form resource mapping")
                        continue
                    active.add(ident)
                    for key in set(item.keys()) | set(other.keys()):
                        if key not in STREAM_IGNORED | {"/Resources", "/StructParents"} and _value(item.get(key)) != _value(other.get(key)):
                            raise PreservationRefusal("Engine changed Form geometry or dictionary")
                    br, ar = item.get("/Resources", before), other.get("/Resources", after)
                    pair_resources(br, ar)
                    content = _repair_stream(item, other, ar, ident, refs, parents, definitions, removals, changes, allow_tag_regrouping, semantic_reviews, owner_keys)
                    streams[ident] = (_ident(item), other, content)
                    active.remove(ident)

            page_contents = []
            for index, (before, after) in enumerate(zip(original.pages, tagged.pages)):
                for key in ("/MediaBox", "/CropBox", "/Rotate", "/UserUnit"):
                    if _value(before.obj.get(key)) != _value(after.obj.get(key)):
                        raise PreservationRefusal("Engine changed page geometry")
                pair_resources(before.resources, after.resources)
                content = _repair_stream(before, after, after.resources, index, refs, parents, definitions, removals, changes, allow_tag_regrouping, semantic_reviews, owner_keys)
                page_contents.append(content)
            # The complete inventory above has parsed every page and every Form
            # reachable through all resource dictionaries. Thus absent MCIDs
            # carry no original painting. Never retarget one to a nearby MCID.
            dangling = set(refs) - set(definitions)
            if refs and not definitions:
                raise PreservationRefusal("Wholly phantom engine structure cannot be normalized into a pass")
            removals.update(dangling)
            changes["nonexistent_mcid_references_removed"] = len(dangling)
            _prune_refs(tagged, removals, page_keys, parents, definitions, changes)
            from .line_separators import preserve_line_separators
            for page_number, (page, content) in enumerate(zip(tagged.pages, page_contents)):
                page.obj["/Contents"] = tagged.make_stream(content)
                content, line_records = preserve_line_separators(source, page_number, page, content, refs)
                report['automatic_line_separators'].extend(line_records)
                changes['source_line_separators_added'] += len(line_records)
                page.obj["/Contents"] = tagged.make_stream(content)
            for _, stream, content in streams.values():
                stream.write(content)
            destination.parent.mkdir(parents=True, exist_ok=True)
            tagged.save(destination, deterministic_id=True)
            changes["pages_source_checked"] = len(original.pages)
            changes["forms_source_checked"] = len(streams)
        report.update(status="pass", supported=True, changes=dict(changes), semantic_review_required=semantic_reviews)
        if changes["mixed_owner_text_runs_retained"]:
            report["warnings"].append("Mixed semantic owners retain engine text splitting; exact render/text fidelity may still fail.")
        if report['automatic_line_separators']:
            report['warnings'].append("Automatic source line separators preserve bounded paragraph boundaries; desktop PDF viewer/reading-order review remains required.")
        if semantic_reviews:
            report["warnings"].append("Opted-in tag regrouping changed semantic assignment. Every recorded regrouping needs human review; this is never implicit verification.")
        return report
    except (PreservationRefusal, pikepdf.PdfError, ValueError, KeyError, TypeError, IndexError) as exc:
        report.update(changes={}, automatic_line_separators=[], reason=str(exc), error_type=type(exc).__name__)
        return report
