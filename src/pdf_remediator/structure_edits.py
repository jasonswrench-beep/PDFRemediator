"""Bounded, reviewed decorative marking and container-role edits.

Only existing source elements are editable. Paint, text, resources, navigation,
annotations and every unselected structure relationship remain unchanged.
"""
from __future__ import annotations

from collections import Counter
import copy
from decimal import Decimal
import hashlib
import json
import math
import re

import pikepdf

from .process import cancelled

KINDS = {"figure-purpose", "structure-role"}
GROUP_ROLES = {"/Document", "/Part", "/Sect", "/Div"}
_VECTOR_PAINT = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "sh"}
_SAFE = {"q", "Q", "cm", "w", "J", "j", "M", "d", "ri", "i", "gs", "m", "l", "c", "v", "y", "h", "re", "n", "W", "W*", "CS", "cs", "SC", "SCN", "sc", "scn", "G", "g", "RG", "rg", "K", "k", "Do"} | _VECTOR_PAINT


def _fail(message):
    from .sidecar import DecisionError
    raise DecisionError(message)


def _tick(cancel):
    if cancelled(cancel):
        raise InterruptedError("Decorative/structure inventory or application cancelled")


def _id(value):
    try:
        n, g = value.objgen
        return f"{n}:{g}" if n else None
    except (AttributeError, ValueError, TypeError):
        return None


def _dict(value):
    return isinstance(value, (pikepdf.Dictionary, pikepdf.Stream))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _streams(page):
    value = page.obj.get("/Contents")
    return list(value) if isinstance(value, pikepdf.Array) else [value]


def _instructions(stream):
    if not isinstance(stream, pikepdf.Stream):
        _fail("Page content is not a stream")
    return list(pikepdf.parse_content_stream(stream))


def _snapshot(pdf, cancel=None):
    """Object-identity-aware source graph; content is independently normalized.

    Stream filter encodings/lengths are serialization details. All decoded
    non-page payload bytes and all parsed page instructions remain bound.
    """
    content_ids = {_id(s) for page in pdf.pages for s in _streams(page)}
    content_ids.discard(None)
    objects, queued, active = {}, [], set()
    nodes, payload_bytes = 0, 0

    def encode(value, depth=0, dereference=False):
        nonlocal nodes, payload_bytes
        nodes += 1
        if nodes % 256 == 0:
            _tick(cancel)
        if depth > 200 or nodes > 1000000:
            _fail("Decorative/structure graph exceeds the bounded proof scope")
        ident = _id(value)
        if ident and not dereference:
            if ident not in active:
                active.add(ident); queued.append((ident, value))
            return {"ref": ident}
        if isinstance(value, pikepdf.Stream):
            opaque = False
            if ident in content_ids:
                # Page programs must remain parseable operators. Opaque encoded
                # payloads are never a substitute for inspecting page content.
                raw = pikepdf.unparse_content_stream(_instructions(value))
                payload_mode = "page-operators"
            else:
                try:
                    raw = value.read_bytes()
                    payload_mode = "decoded"
                except pikepdf.PdfError:
                    # JPEG/JPX and some other image codecs are intentionally not
                    # decoded by qpdf. Bind their exact encoded bytes AND codec
                    # parameters rather than failing ordinary image workflows.
                    raw = value.read_raw_bytes()
                    opaque = True
                    payload_mode = "opaque-encoded"
            payload_bytes += len(raw)
            if payload_bytes > 268435456:
                _fail("Decorative/structure proof exceeds 256 MiB of decoded streams")
            ignored = {"/Length"} if opaque else {"/Length", "/Filter", "/DecodeParms"}
            return {"t": "stream", "d": {str(k): encode(v, depth + 1) for k, v in sorted(value.items())
                    if str(k) not in ignored}, "payload_mode": payload_mode,
                    "payload": hashlib.sha256(raw).hexdigest()}
        if isinstance(value, pikepdf.Dictionary):
            return {"t": "dict", "v": {str(k): encode(v, depth + 1) for k, v in sorted(value.items())}}
        if isinstance(value, pikepdf.Array):
            return {"t": "array", "v": [encode(v, depth + 1) for v in value]}
        if value is None:
            return None
        if isinstance(value, bool):
            return {"t": "bool", "v": value}
        if isinstance(value, (int, float, Decimal)):
            number = Decimal(str(value))
            if not number.is_finite():
                _fail("Nonfinite PDF number prevents a structural preservation proof")
            return {"t": "number", "v": str(number.normalize())}
        if isinstance(value, pikepdf.Name):
            return {"t": "name", "v": str(value)}
        if isinstance(value, pikepdf.String):
            return {"t": "string", "v": bytes(value).hex()}
        _fail("An unsupported PDF object prevents a structural preservation proof")

    root, info = encode(pdf.Root), encode(pdf.trailer.get("/Info"))
    index = 0
    while index < len(queued):
        ident, value = queued[index]; index += 1
        objects[ident] = encode(value, dereference=True)
    return {"root": root, "info": info, "objects": objects}


def _canonical(snapshot):
    """Compare a saved graph without relying on renumbered physical objects."""
    labels = {}
    def walk(value):
        if isinstance(value, dict) and set(value) == {"ref"}:
            ident = value["ref"]
            if ident in labels:
                return {"ref": labels[ident]}
            labels[ident] = len(labels) + 1
            return {"node": labels[ident], "value": walk(snapshot["objects"][ident])}
        if isinstance(value, dict):
            return {k: walk(v) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value
    return walk({"root": snapshot["root"], "info": snapshot["info"]})


def _prune(snapshot):
    found = set()
    pending = [snapshot["root"], snapshot["info"]]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if set(value) == {"ref"}:
                ident = value["ref"]
                if ident not in found:
                    found.add(ident); pending.append(snapshot["objects"][ident])
            else:
                pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    snapshot["objects"] = {k: v for k, v in snapshot["objects"].items() if k in found}
    return snapshot


def _resolve_encoded(snapshot, value):
    return snapshot["objects"][value["ref"]] if isinstance(value, dict) and set(value) == {"ref"} else value


def _references(value):
    if isinstance(value, dict):
        if set(value) == {"ref"}:
            yield value["ref"]
        else:
            for item in value.values(): yield from _references(item)
    elif isinstance(value, list):
        for item in value: yield from _references(item)


def _parent_arrays(root):
    """Find actual ParentTree arrays without rewriting its number-tree shape."""
    result, chains, seen = {}, {}, set()
    def walk(node, depth=0, ancestry=()):
        if depth > 100 or not _dict(node):
            _fail("ParentTree number-tree shape is unsupported")
        key = _id(node) or id(node)
        if key in seen:
            _fail("ParentTree number-tree repeats a node")
        seen.add(key)
        ancestry = ancestry + (node,)
        nums, kids = node.get("/Nums"), node.get("/Kids")
        if nums is not None:
            if kids is not None or not isinstance(nums, pikepdf.Array) or len(nums) % 2:
                _fail("ParentTree numbers are malformed")
            for i in range(0, len(nums), 2):
                number = nums[i]
                if isinstance(number, bool) or not isinstance(number, int) or number < 0 or number in result:
                    _fail("ParentTree has ambiguous number keys")
                result[number] = nums[i+1]
                chains[number] = ancestry + (nums, nums[i+1])
        elif isinstance(kids, pikepdf.Array) and kids:
            for child in kids: walk(child, depth+1, ancestry + (kids,))
        else:
            _fail("ParentTree numbers are unavailable")
    walk(root.get("/ParentTree"))
    return result, chains


def _bbox(node, page):
    result = {"status": "missing", "bbox": None, "page_box": None,
        "units": "PDF default user space",
        "coordinate_system": "bottom-left PDF coordinates (not preview percentages)",
        "reason": "No direct Layout BBox is recorded; inspect the figure in the source document."}
    if page is not None:
        try:
            result["page_box"] = [float(x) for x in page.cropbox]
        except (ValueError, TypeError, AttributeError):
            pass
    attrs = node.get("/A", [])
    attrs = list(attrs) if isinstance(attrs, pikepdf.Array) else [attrs]
    boxes = [a.get("/BBox") for a in attrs if _dict(a) and str(a.get("/O")) == "/Layout" and "/BBox" in a]
    if node.get("/C") is not None:
        result.update(status="unresolved", reason="ClassMap attributes may affect the figure bounds; no class-based geometry is inferred.")
    elif len(boxes) > 1:
        result.update(status="unresolved", reason="Multiple direct Layout BBox attributes require source review.")
    elif len(boxes) == 1:
        try:
            box = boxes[0]
            if not isinstance(box, pikepdf.Array) or len(box) != 4 or any(isinstance(v, bool) for v in box):
                raise ValueError()
            box = [float(v) for v in box]
            if not all(math.isfinite(v) for v in box) or not (box[0] < box[2] and box[1] < box[3]):
                raise ValueError()
            result.update(status="valid", bbox=box, reason="A finite direct Layout BBox is recorded. Its fit to the actual figure remains unmeasured and needs review.")
            bounds = result["page_box"]
            if bounds and not (bounds[0] <= box[0] < box[2] <= bounds[2] and bounds[1] <= box[1] < box[3] <= bounds[3]):
                result.update(status="invalid", reason="The recorded BBox extends outside the current page box; inspect crop coordinates and the source figure.")
        except (ValueError, TypeError, OverflowError):
            result.update(status="invalid", reason="The direct Layout BBox is not a finite positive rectangle.")
    return result


def _analyse(pdf, cancel=None):
    from .inspection import _structure, _page_content
    _tick(cancel)
    pages = {_id(page.obj): n for n, page in enumerate(pdf.pages, 1)}
    root = pdf.Root.get("/StructTreeRoot")
    if not _dict(root): return {}, {}, [], None, None
    snapshot = _snapshot(pdf, cancel)
    global_problems = []
    if pdf.is_encrypted or "/AcroForm" in pdf.Root:
        global_problems.append("Encrypted documents and forms require a separately supported source-repair workflow.")
    structure, owners, _, _, _ = _structure(pdf, pages)
    if structure.get("errors"):
        global_problems.append("The existing structure graph is not uniquely resolvable.")
    rolemap = root.get("/RoleMap", {})
    def role(value):
        value, seen = str(value), set()
        while _dict(rolemap) and value in rolemap:
            if value in seen: return None
            seen.add(value); value = str(rolemap[value])
        return value
    nodes, refs = {}, {}
    seen = set()
    def walk(value, path, parent=None, page=None, depth=0):
        if depth > 200 or len(nodes) > 100000:
            _fail("Structure graph exceeds the bounded traversal scope")
        _tick(cancel)
        if isinstance(value, pikepdf.Array):
            for i, child in enumerate(value): walk(child, path+f"/{i}", parent, page, depth+1)
            return
        if not _dict(value) or "/S" not in value: return
        ident = _id(value)
        if ident is None or ident in seen:
            global_problems.append("Direct, repeated or cyclic structure elements require source repair.")
            return
        seen.add(ident)
        if "/Pg" in value: page = pages.get(_id(value["/Pg"]))
        if _id(value.get("/P")) != _id(parent):
            global_problems.append("An existing structure parent pointer does not match its actual tree position.")
        nodes[ident] = {"node": value, "path": path, "parent": parent, "page": page, "role": role(value["/S"])}
        walk(value.get("/K"), path+"/K", value, page, depth+1)
    walk(root.get("/K"), "root/K", root)
    for ref in structure.get("references", []): refs.setdefault(ref.get("element"), []).append({k:ref[k] for k in ("page","stream","mcid")})
    for ident,item in nodes.items():
        if item["role"] in GROUP_ROLES:
            prefix=item["path"]+"/K"
            refs[ident]=[ref for child_id,child in nodes.items() if child_id==ident or child["path"].startswith(prefix+"/") or child["path"]==prefix for ref in refs.get(child_id,[])]
    content_info, stream_uses = {}, Counter(_id(s) for page in pdf.pages for s in _streams(page))
    for number, page in enumerate(pdf.pages, 1):
        _tick(cancel)
        info, defs, painted = _page_content(page, number, owners, {}, {})
        # ParentTree is checked separately below against the actual mutable slot.
        if info.get("errors") or info.get("duplicate_mcids"):
            global_problems.append("Page content has parsing or duplicate-marked-content errors.")
        content_info[number] = (defs, painted)
    try: arrays, parent_chains = _parent_arrays(root)
    except ValueError:
        arrays, parent_chains = {}, {}; global_problems.append("ParentTree ownership cannot be safely updated.")
    # The trailer's Root and Info are graph edges too. An unusual Info alias
    # must not let a structural edit mutate that second root unnoticed.
    ref_counts = Counter(r for value in [snapshot["root"], snapshot["info"], *snapshot["objects"].values()]
                         for r in _references(value))
    parent_key_uses = Counter(page.obj.get("/StructParents") for page in pdf.pages
        if isinstance(page.obj.get("/StructParents"), int) and not isinstance(page.obj.get("/StructParents"), bool))
    for ident, item in nodes.items():
        node, current_role = item["node"], item["role"]
        item["refs"] = refs.get(ident, [])
        if current_role == "/Figure":
            limits = list(global_problems)
            r = item["refs"]
            k = node.get("/K")
            leaf = (isinstance(k, int) and not isinstance(k, bool) and k >= 0 or
                    (_dict(k) and isinstance(k.get("/MCID"), int) and not isinstance(k.get("/MCID"), bool)
                     and k["/MCID"] >= 0 and "/K" not in k and "/Stm" not in k
                     and str(k.get("/Type", "/MCR")) == "/MCR"))
            if not leaf or len(r) != 1 or r[0].get("page") not in range(1,len(pdf.pages)+1) or r[0].get("stream") != "page":
                limits.append("Decorative marking requires one leaf Figure with one direct page MCID; shared, multi-page, nested and object-only elements require source repair.")
            if any(key in node for key in ("/ActualText", "/ID", "/Ref", "/AF")):
                limits.append("ActualText, IDs, references or associated files prevent safe removal of this Figure element.")
            parent, children = item["parent"], item["parent"].get("/K") if _dict(item["parent"]) else None
            if not _dict(parent) or role(parent.get("/S")) not in GROUP_ROLES or not isinstance(children,pikepdf.Array) or sum(_id(c)==ident for c in children)!=1 or len(children)<2 or any(not _dict(c) or "/S" not in c for c in children):
                limits.append("The Figure needs one grouping parent with other retained structure children; empty-parent pruning is unsupported.")
            if isinstance(children, pikepdf.Array) and _id(children) and ref_counts[_id(children)] != 1:
                limits.append("The grouping parent's child array has another owner or alias.")
            if _dict(parent) and isinstance(children, pikepdf.Array) and ref_counts[_id(parent)] != len(children) + 1:
                limits.append("The grouping parent has additional inbound references outside its tree relationships.")
            ancestor = parent
            visited_ancestors = set()
            while _dict(ancestor) and _id(ancestor) not in visited_ancestors:
                visited_ancestors.add(_id(ancestor))
                if "/ActualText" in ancestor:
                    limits.append("An ancestor supplies replacement text; decorative marking needs source review.")
                ancestor = ancestor.get("/P")
            if ref_counts[ident] != 2:
                limits.append("Additional or missing inbound structure references prevent safe Figure detachment.")
            record = None
            if len(r)==1 and r[0].get("page") in range(1,len(pdf.pages)+1) and r[0].get("stream")=="page":
                number, mcid = r[0]["page"], r[0]["mcid"]
                page = pdf.pages[number-1]
                defs, painted = content_info[number]
                key = (number,"page",mcid)
                if defs.get(key)!=1 or not painted.get(key) or owners.get(key)!=[ident]:
                    limits.append("The Figure MCID does not have one proven paint definition and owner.")
                pkey = page.obj.get("/StructParents")
                values = arrays.get(pkey) if isinstance(pkey,int) and not isinstance(pkey,bool) else None
                if not isinstance(values,pikepdf.Array) or not 0<=mcid<len(values) or _id(values[mcid])!=ident:
                    limits.append("The Figure ParentTree slot does not point uniquely to this element.")
                if parent_key_uses[pkey] != 1:
                    limits.append("The page StructParents key is shared with another page.")
                if any(_id(obj) and ref_counts[_id(obj)] != 1 for obj in parent_chains.get(pkey, ())):
                    limits.append("The ParentTree branch, number array or value array is shared or aliased.")
                contents = page.obj.get("/Contents")
                if isinstance(contents, pikepdf.Array) and _id(contents) and ref_counts[_id(contents)] != 1:
                    limits.append("The page Contents array has another owner or alias.")
                matches=[]
                for stream in _streams(page):
                    instructions=_instructions(stream); stack=[]
                    for index,instruction in enumerate(instructions):
                        operands, op = instruction.operands, str(instruction.operator)
                        if op in {"BMC","BDC"}:
                            props=operands[1] if op=="BDC" and len(operands)==2 else None
                            if isinstance(props,pikepdf.Name): props=page.resources.get("/Properties",{}).get(str(props))
                            this_mcid=props.get("/MCID") if _dict(props) else None
                            stack.append((index,this_mcid,props,len(stack)))
                        elif op=="EMC":
                            if not stack:
                                limits.append("Marked-content boundaries are unbalanced."); continue
                            begin,marked,props,outer=stack.pop()
                            if isinstance(marked, int) and not isinstance(marked, bool) and marked == mcid:
                                matches.append((stream,instructions,begin,index,props,outer))
                if len(matches)!=1:
                    limits.append("The Figure marked-content boundaries cannot be selected uniquely.")
                else:
                    stream,instructions,begin,end,props,outer=matches[0]
                    if stream_uses[_id(stream)]!=1:
                        limits.append("The page content stream is reused; mark the source occurrence separately.")
                    if ref_counts[_id(stream)] != 1:
                        limits.append("The page content stream has another inbound reference or alias.")
                    if outer or any(str(i.operator) in {"BMC","BDC","EMC"} for i in instructions[begin+1:end]):
                        limits.append("Nested or enclosing marked content requires source repair before decorative marking.")
                    if not _dict(props) or set(str(k) for k in props.keys()) != {"/MCID"}:
                        limits.append("Only an exact MCID-only property list can be converted without discarding other marked-content properties.")
                    has_paint, balance = False, 0
                    for instruction in instructions[begin+1:end]:
                        op=str(instruction.operator)
                        if op not in _SAFE:
                            limits.append("The Figure includes text or unsupported operators; only nontext page graphics can be marked decorative."); break
                        if op=="q": balance+=1
                        if op=="Q": balance-=1
                        if balance<0:
                            limits.append("The Figure graphics-state boundary is not self-contained.")
                        if op in _VECTOR_PAINT: has_paint=True
                        if op=="Do":
                            operands=instruction.operands
                            obj=page.resources.get("/XObject",{}).get(str(operands[0])) if operands else None
                            if not isinstance(obj,pikepdf.Stream) or obj.get("/Subtype")!=pikepdf.Name.Image:
                                limits.append("Forms and unresolved image resources require source repair before decorative marking.")
                            else: has_paint=True
                    if balance or not has_paint:
                        limits.append("A complete nontext paint region with balanced graphics state is required.")
                    record={"stream":stream,"instructions":instructions,"begin":begin,"end":end,"array":values,"parent":parent,"mcid":mcid}
            item.update(limits=sorted(set(limits)), record=record)
        elif current_role in GROUP_ROLES:
            limits=list(global_problems)
            children=node.get("/K")
            if not isinstance(children,pikepdf.Array) or not children or any(not _dict(c) or "/S" not in c for c in children):
                limits.append("A role change requires an existing nonempty grouping container with structure-element children only.")
            if any(k in node for k in ("/ActualText","/ID","/Ref")):
                limits.append("Replacement text, IDs or explicit structure references require source repair before changing a grouping role.")
            if isinstance(children, pikepdf.Array) and ref_counts[ident] != len(children) + 1:
                limits.append("The grouping element has additional inbound references outside its tree relationships.")
            top=_id(item["parent"])==_id(root)
            if top:
                top_k=root.get("/K"); top_children=list(top_k) if isinstance(top_k,pikepdf.Array) else [top_k]
                if len(top_children)!=1 or _id(top_children[0])!=ident:
                    limits.append("Document role correction requires a single existing top-level grouping element.")
                target="Document"
            else: target="Sect"
            if _dict(rolemap) and "/" + target in rolemap:
                limits.append("The requested standard role is remapped by RoleMap; repair that source mapping first.")
            item.update(limits=sorted(set(limits)),role_target=target)
    return nodes, arrays, sorted(set(global_problems)), snapshot, root


def _unavailable_inventory(pdf, reason, base_rows=(), base_targets=None):
    """Keep established processing available when only the new proof is bounded."""
    root = pdf.Root.get("/StructTreeRoot")
    candidates, seen = [], set()
    for row in base_rows:
        if row.get("kind") == "figure-description" and row.get("element") not in seen:
            seen.add(row["element"])
            candidates.append((row["element"], "figure-purpose", "Figure", row.get("page"), row.get("structure_path"), row.get("references", [])))
    top = root.get("/K") if _dict(root) else None
    top = list(top) if isinstance(top,pikepdf.Array) else [top]
    for index,node in enumerate(top):
        if _dict(node) and "/S" in node and _id(node) not in seen:
            current = str(node["/S"]).lstrip("/")
            if "/" + current in GROUP_ROLES:
                seen.add(_id(node))
                candidates.append((_id(node),"structure-role",current,None,
                    f"root/K/{index}" if isinstance(root.get("/K"),pikepdf.Array) else "root/K",[]))
    rows = []
    for ident,kind,current,page,path,refs in candidates:
        display={"structural_eligible":False,"structural_limitations":[
            "Advanced decorative/structure proof is unavailable within its supported limits: " + reason +
            " Existing review controls and processing retain their earlier scope."],
            "allowed_values":[current],"context_text":"",
            "context_text_source":"Existing source element; advanced proof unavailable. No change is authorized."}
        if kind=="figure-purpose":
            display["figure_bbox"]={"status":"unresolved","bbox":None,"page_box":None,
                "units":"PDF default user space","coordinate_system":"bottom-left PDF coordinates (not preview percentages)",
                "reason":"Advanced geometry diagnostics are unavailable within the supported proof scope."}
        fingerprint=_digest({"element":ident,"kind":kind,"page":page,"path":path,"references":refs,"display":display})
        rows.append({"id":f"structure:{kind}:{ident}:{fingerprint[:16]}","kind":kind,"page":page,"element":ident,
            "structure_path":path,"references":refs,"context_sha256":fingerprint,"current":current,"value":current,"status":"pending",**display})
    return rows, {ident:node for ident,node in (base_targets or {}).items() if ident in seen}, []


def inventory(pdf, *, cancel=None, base_rows=(), base_targets=None, analysis_out=None):
    from .sidecar import DecisionError
    try:
        analysed = _analyse(pdf,cancel)
        nodes, _, errors, snapshot, _ = analysed
        if analysis_out is not None:
            analysis_out['analysis'] = analysed
    except InterruptedError:
        raise
    except (DecisionError, pikepdf.PdfError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        if analysis_out is not None:
            analysis_out['failed'] = True
        # A bound or unsupported new proof must not turn an established metadata,
        # heading or ordinary PDF workflow into a new whole-document failure.
        return _unavailable_inventory(pdf,"The complete source graph/content proof could not be established.",base_rows,base_targets)
    rows,targets=[],{}
    for ident,item in nodes.items():
        if item["role"]!="/Figure" and item["role"] not in GROUP_ROLES: continue
        node,limits=item["node"],item["limits"]
        kind="figure-purpose" if item["role"]=="/Figure" else "structure-role"
        current="Figure" if kind=="figure-purpose" else item["role"].lstrip("/")
        choices=[current]
        if not limits:
            target="Artifact" if kind=="figure-purpose" else item["role_target"]
            if target not in choices: choices.append(target)
        refs=item["refs"]
        pages=sorted({r["page"] for r in refs if r.get("page")})
        page=pages[0] if len(pages)==1 else item["page"] if kind=="figure-purpose" else None
        display={"structural_eligible":not limits,"structural_limitations":limits,"allowed_values":choices,
            "context_text":str(node.get("/T",node.get("/Alt","")))[:500],
            "context_text_source":"Existing source structure and exact content references; inspect the page before deciding."}
        if kind=="figure-purpose": display["figure_bbox"]=_bbox(node,pdf.pages[page-1] if isinstance(page,int) and 1<=page<=len(pdf.pages) else None)
        context={"element":ident,"structure_path":item["path"],"role":item["role"],"references":refs,"display":display,
            "source_object":snapshot["objects"].get(ident),"parent":_id(item["parent"])}
        fingerprint=_digest(context)
        rows.append({"id":f"structure:{kind}:{ident}:{fingerprint[:16]}","kind":kind,"page":page,"element":ident,
            "structure_path":item["path"],"references":refs,"context_sha256":fingerprint,"current":current,"value":current,"status":"pending",**display})
        targets[ident]=node
    return rows,targets,[]


def validate_value(item):
    if item.get("kind") not in KINDS: _fail("Unsupported decorative/structure decision kind")
    if item.get("structural_eligible") is not True: _fail("This element is outside the safely editable decorative/structure scope")
    choices=item.get("allowed_values")
    if not isinstance(choices,list) or item.get("value") not in choices: _fail("Choose an explicitly eligible Figure purpose or grouping role")
    if item["kind"]=="figure-purpose" and item["value"] not in {"Figure","Artifact"}: _fail("Figure purpose must remain Figure or become Artifact")
    if item["kind"]=="structure-role" and item["value"]!=item.get("current") and item["value"] not in {"Document","Sect"}: _fail("Only Document or Sect grouping corrections are supported")


def _selected(pdf, items, cancel=None):
    nodes,_,errors,snapshot,_=_analyse(pdf,cancel)
    rows,_,_=inventory(pdf,cancel=cancel)
    fresh={r["id"]:r for r in rows}
    chosen=[]
    for item in items:
        validate_value(item)
        row=fresh.get(item.get("id"))
        if row is None or any(item.get(k)!=row.get(k) for k in ("kind","element","context_sha256","current","page","structure_path","references","allowed_values","figure_bbox","structural_eligible","structural_limitations","context_text","context_text_source")):
            _fail("Decorative/structure decision context changed")
        if item["value"]!=item["current"]: chosen.append((item,nodes[item["element"]]))
    removals=Counter(_id(record["parent"]) for item,record in chosen if item["kind"]=="figure-purpose")
    for parent_id,count in removals.items():
        parent=next(record["parent"] for item,record in chosen if _id(record["parent"])==parent_id)
        if len(parent["/K"])-count<1: _fail("Selected decorative changes would empty their grouping parent; use a separate source repair")
    return chosen,snapshot


def _expected(snapshot, chosen):
    expected=copy.deepcopy(snapshot)
    streams={}
    for item,record in chosen:
        ident=item["element"]
        if item["kind"]=="structure-role":
            expected["objects"][ident]["v"]["/S"]={"t":"name","v":"/"+item["value"]}
            continue
        edit=record["record"]
        parent_id=_id(edit["parent"])
        children=_resolve_encoded(expected,expected["objects"][parent_id]["v"]["/K"])
        children["v"]=[c for c in children["v"] if c!={"ref":ident}]
        array_id=_id(edit["array"])
        # A direct ParentTree array is located by exact object identity in its
        # source encoding, without relying on an independently guessed index.
        if array_id:
            expected["objects"][array_id]["v"][edit["mcid"]]=None
        else:
            changed=0
            def null_slot(value):
                nonlocal changed
                if isinstance(value,dict):
                    if value.get("t")=="array" and len(value["v"])>edit["mcid"] and value["v"][edit["mcid"]]=={"ref":ident}:
                        # Only ParentTree, not the structure parent's /K array,
                        # still has this reference after detachment above.
                        value["v"][edit["mcid"]]=None; changed+=1
                    else:
                        for v in value.values(): null_slot(v)
                elif isinstance(value,list):
                    for v in value: null_slot(v)
            for value in expected["objects"].values(): null_slot(value)
            if changed!=1: _fail("The expected ParentTree slot is ambiguous")
        sid=_id(edit["stream"])
        streams.setdefault(sid,{"instructions":list(edit["instructions"]),"begins":[]})["begins"].append(edit["begin"])
    for sid,record in streams.items():
        instructions=record["instructions"]
        for begin in record["begins"]:
            instructions[begin]=pikepdf.ContentStreamInstruction([pikepdf.Name.Artifact],pikepdf.Operator("BMC"))
        expected["objects"][sid]["payload"]=hashlib.sha256(pikepdf.unparse_content_stream(instructions)).hexdigest()
    return _prune(expected)


def apply_changes(pdf, items, *, cancel=None):
    chosen,before=_selected(pdf,items,cancel)
    expected=_expected(before,chosen)
    streams={}
    for item,record in chosen:
        _tick(cancel)
        node=record["node"]
        if item["kind"]=="structure-role": node["/S"]=pikepdf.Name("/"+item["value"])
        else:
            edit=record["record"]
            children=edit["parent"]["/K"]
            index=next(i for i,c in enumerate(children) if _id(c)==item["element"])
            del children[index]
            edit["array"][edit["mcid"]]=None
            sid=_id(edit["stream"])
            streams.setdefault(sid,{"stream":edit["stream"],"instructions":list(edit["instructions"]),"begins":[]})["begins"].append(edit["begin"])
    for record in streams.values():
        for begin in record["begins"]:
            record["instructions"][begin]=pikepdf.ContentStreamInstruction([pikepdf.Name.Artifact],pikepdf.Operator("BMC"))
        record["stream"].write(pikepdf.unparse_content_stream(record["instructions"]))
    _tick(cancel)
    if _snapshot(pdf,cancel)!=expected:
        _fail("Decorative/structure writer changed content outside the explicitly selected operators and relationships")
    return [item["id"] for item,_ in chosen]


def _expected_other_changes(pdf, items, cancel=None):
    """Enumerate authorized older typed mutations; never mask whole subtrees.

    This is a separate graph oracle from sidecar's writer. Exact title/language
    metadata, one Alt or role, or Table Scope fields may change only as selected.
    """
    from .sidecar import _inventory, STRUCTURAL_INVENTORY_PROFILE, _validated_table_value
    _, targets, errors = _inventory(pdf, STRUCTURAL_INVENTORY_PROFILE, cancel=cancel)
    if errors: _fail("Ordinary edit targets cannot be independently resolved")
    local_languages = [item for item in items if item['kind'] in {'passage-language','page-language'}]
    local_plans = []
    if local_languages:
        from .language_edits import prepare_expected
        local_plans = prepare_expected(pdf, local_languages, cancel=cancel)
    for item in items:
        _tick(cancel)
        kind,value=item["kind"],item["value"]
        if kind=="title":
            pdf.docinfo["/Title"]=value
            with pdf.open_metadata(set_pikepdf_as_editor=False,update_docinfo=False) as meta:
                meta["dc:title"]=value
            preferences=pdf.Root.get("/ViewerPreferences",pikepdf.Dictionary())
            preferences["/DisplayDocTitle"]=True
            pdf.Root["/ViewerPreferences"]=preferences
        elif kind=="language":
            pdf.Root["/Lang"]=value
            with pdf.open_metadata(set_pikepdf_as_editor=False,update_docinfo=False) as meta:
                meta["dc:language"]=[value]
        elif kind=="figure-description":
            targets[item["element"]]["/Alt"]=value
        elif kind=="heading-tag":
            targets[item["element"]]["/S"]=pikepdf.Name("/"+value)
        elif kind=="table-header":
            specification=_validated_table_value(value)
            target=targets[item["element"]]
            target["/S"]=pikepdf.Name("/"+specification["role"])
            attrs=target.get("/A",[])
            attrs=list(attrs) if isinstance(attrs,pikepdf.Array) else [attrs]
            retained=[]
            for attr in attrs:
                if _dict(attr) and str(attr.get("/O"))=="/Table":
                    attr=pikepdf.Dictionary({key:v for key,v in attr.items() if key!="/Scope"})
                if attr is not None: retained.append(attr)
            if specification["scope"] is not None:
                retained.append(pikepdf.Dictionary(O=pikepdf.Name.Table,Scope=pikepdf.Name("/"+specification["scope"])))
            if retained: target["/A"]=pikepdf.Array(retained)
            elif "/A" in target: del target["/A"]
        elif kind in {'passage-language','page-language'}:
            continue
        else:
            _fail("An unsupported ordinary edit cannot be combined with decorative/structure changes")
    if local_languages:
        from .language_edits import apply_expected
        apply_expected(local_plans, cancel=cancel)


def _effective_pdf_version(pdf):
    """Resolve normative header/Catalog versions, never descriptive XMP."""
    values = [str(pdf.pdf_version)]
    if '/Version' in pdf.Root:
        if not isinstance(pdf.Root['/Version'], pikepdf.Name):
            _fail('The PDF Catalog version is not an ordinary version name')
        values.append(str(pdf.Root['/Version']).lstrip('/'))
    if any(re.fullmatch(r'[0-9]+\.[0-9]+', value) is None for value in values):
        _fail('The effective PDF version cannot be independently proved')
    return max(tuple(int(part) for part in value.split('.')) for value in values)


def verify_output(source, output, items, *, other_changes=(), cancel=None):
    """Reopen the result and prove exact authorized graph/operator changes."""
    _tick(cancel)
    required_output_version = None
    with pikepdf.open(source) as pdf:
        if items:chosen,before=_selected(pdf,items,cancel)
        else:chosen,before=[],_snapshot(pdf,cancel)
        navigation_kinds={'annotation-name','link-name','link-target','bookmark-entry','bookmark-additions'}
        tree_kinds={'semantic-role','reading-order','tree-move','semantic-list'}
        table_items=[item for item in other_changes if item['kind']=='table-structure']
        form_items=[item for item in other_changes if item['kind']=='form-controls']
        empty_items=[item for item in other_changes if item['kind']=='empty-tag-removal']
        empty_plans=[]
        if empty_items:
            from .empty_tag_edits import prepare_expected
            empty_plans=prepare_expected(pdf,empty_items,cancel=cancel,other_changes=other_changes+items)
        form_plans=[]
        if form_items:
            from .form_edits import prepare_expected
            form_plans=prepare_expected(pdf,form_items,cancel=cancel,other_changes=other_changes+items)
            if form_plans:
                required_output_version = max(_effective_pdf_version(pdf), (1, 7))
        table_plans=[]
        if table_items:
            from .table_edits import prepare_expected
            from .sidecar import _marked_text_contexts
            table_plans=prepare_expected(pdf,table_items,cancel=cancel,text_contexts=_marked_text_contexts(source,cancel),other_changes=other_changes+items)
            if table_plans:
                required_output_version = max(_effective_pdf_version(pdf), (1, 7))
        tree_items=[item for item in other_changes if item['kind'] in tree_kinds]
        tree_plans=[]
        if tree_items:
            from .semantic_tree_edits import prepare_expected
            from .sidecar import _marked_text_contexts
            tree_plans=prepare_expected(pdf,tree_items,cancel=cancel,text_contexts=_marked_text_contexts(source,cancel),other_changes=other_changes+items)
        navigation_items=[item for item in other_changes if item['kind'] in navigation_kinds]
        navigation_plans=[]
        if navigation_items:
            from .navigation_edits import prepare_expected
            navigation_plans=prepare_expected(pdf,navigation_items,cancel=cancel)
        ordinary_items=[item for item in other_changes if item['kind'] not in navigation_kinds|tree_kinds|{'table-structure','form-controls','empty-tag-removal'}]
        if ordinary_items:
            _expected_other_changes(pdf,ordinary_items,cancel)
            before=_snapshot(pdf,cancel)
        expected_graph=_expected(before,chosen)
        if navigation_plans:
            from .navigation_edits import expected_snapshot,canonical_snapshot
            expected_graph=expected_snapshot(expected_graph,navigation_plans,cancel=cancel)
            canonical=canonical_snapshot
        else:canonical=_canonical
        if tree_plans:
            from .semantic_tree_edits import expected_snapshot,canonical_snapshot
            expected_graph=expected_snapshot(expected_graph,tree_plans,cancel=cancel)
            canonical=canonical_snapshot
        if table_plans:
            from .table_edits import expected_snapshot,canonical_snapshot
            expected_graph=expected_snapshot(expected_graph,table_plans,cancel=cancel)
            canonical=canonical_snapshot
        if form_plans:
            from .form_edits import expected_snapshot,canonical_snapshot
            expected_graph=expected_snapshot(expected_graph,form_plans,cancel=cancel)
            canonical=canonical_snapshot
        if empty_plans:
            from .empty_tag_edits import expected_snapshot,canonical_snapshot
            expected_graph=expected_snapshot(expected_graph,empty_plans,cancel=cancel)
            canonical=canonical_snapshot
        expected=canonical(expected_graph)
    with pikepdf.open(output) as pdf:
        if required_output_version is not None and _effective_pdf_version(pdf) < required_output_version:
            _fail('Saved reviewed table or form features have an insufficient PDF version')
        actual=canonical(_snapshot(pdf,cancel))
    if actual!=expected:
        _fail("Saved decorative/structure result does not preserve the exact authorized PDF graph and content")
    return {"status":"pass","authorized_changes":len(chosen)+len(empty_plans),"graph_sha256":_digest(actual)}
