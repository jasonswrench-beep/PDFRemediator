"""Explicit application decisions bound to source, staged PDF, and occurrence.

JSON is the default editable format (and is valid YAML). No descriptions,
language, headings, or table relationships are inferred by this module.
User-authorized best guesses have a separate status and never imply review.
"""
from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

import pikepdf

from .io_utils import atomic_replace
from .process import cancelled

SCHEMA_VERSION = "phase1-decisions-1"
LEGACY_INVENTORY_PROFILE = "metadata-figures-1"
STRUCTURAL_INVENTORY_PROFILE = "reviewed-structure-1"
ARTIFACT_STRUCTURE_INVENTORY_PROFILE = "reviewed-artifacts-structure-2"
PASSAGE_LANGUAGE_INVENTORY_PROFILE = "reviewed-passage-language-3"
NAVIGATION_INVENTORY_PROFILE = "reviewed-navigation-4"
SEMANTIC_TREE_INVENTORY_PROFILE = "reviewed-semantic-tree-5"
TABLE_INVENTORY_PROFILE = "reviewed-table-6"
FORM_INVENTORY_PROFILE = "reviewed-form-7"
EMPTY_TAG_INVENTORY_PROFILE = "reviewed-empty-tags-8"
AUTOMATIC_AUTHORIZATION_SCHEMA = "phase2-automatic-authorization-1"
AUTOMATIC_APPLICATION_SCHEMA = "phase2-automatic-application-1"
AUTOMATIC_KINDS = ["figure-description", "title"]
_SHA = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_STRUCTURAL_CONTEXT = ("context_text", "context_text_source", "structural_eligible", "structural_limitations", "allowed_values", "figure_bbox", "language_context", "language_scope", "navigation_context", "tree_context", "table_context", "form_context", "empty_tag_context")


class DecisionError(ValueError):
    """A decision is invalid, stale, or outside the supported operation set."""


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _object_id(value):
    try:
        number, generation = value.objgen
        return f"{number}:{generation}" if number else None
    except (AttributeError, ValueError, TypeError):
        return None


def _is_dict(value):
    return isinstance(value, (pikepdf.Dictionary, pikepdf.Stream))


def _stream_hash(value):
    if isinstance(value, pikepdf.Stream):
        return hashlib.sha256(value.read_bytes()).hexdigest()
    return None


def _content_hash(page):
    content = page.obj.get("/Contents")
    streams = list(content) if isinstance(content, pikepdf.Array) else [content]
    return _digest([_stream_hash(stream) for stream in streams])


def inventory_profile_for(data):
    """Select an explicit inventory without silently widening old reviews."""
    profile = data.get("inventory_profile", LEGACY_INVENTORY_PROFILE)
    if not isinstance(profile, str) or profile not in {LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE, ARTIFACT_STRUCTURE_INVENTORY_PROFILE, PASSAGE_LANGUAGE_INVENTORY_PROFILE, NAVIGATION_INVENTORY_PROFILE, SEMANTIC_TREE_INVENTORY_PROFILE, TABLE_INVENTORY_PROFILE, FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE}:
        raise DecisionError("Unknown decision inventory profile")
    return profile


def _table_scope(node):
    attrs = node.get("/A", [])
    attrs = list(attrs) if isinstance(attrs, pikepdf.Array) else [attrs]
    scopes = [str(attr["/Scope"]).lstrip("/") for attr in attrs
              if _is_dict(attr) and str(attr.get("/O", "")) == "/Table" and "/Scope" in attr]
    return scopes[0] if len(scopes) == 1 else None


def _table_value(role, scope):
    return json.dumps({"role": role, "scope": scope}, sort_keys=True, separators=(",", ":"))


def _inventory_cancel(cancel):
    if cancelled(cancel):
        raise InterruptedError("Decision inventory or application cancelled")


def _marked_text_contexts(path, cancel=None):
    """Bounded existing text from unambiguous direct page-object MCID marks.

    PdfTextObj.extract uses PDFium's documented FPDFTextObj_GetText API. Forms,
    mixed/non-text objects and multiple MCID marks cannot supply an exact snippet.
    This supplies display evidence only; it never selects a heading or scope.
    """
    import pypdfium2 as pdfium
    contexts, total = {}, 0
    try:
        with pdfium.PdfDocument(str(path)) as document:
            for number in range(min(len(document), 200)):
                _inventory_cancel(cancel)
                page = document[number]
                textpage = None
                try:
                    textpage = page.get_textpage()
                    found, blocked, reliable = {}, set(), True
                    for index, obj in enumerate(page.get_objects(max_depth=1, textpage=textpage)):
                        total += 1
                        if index % 256 == 0:
                            _inventory_cancel(cancel)
                        if index >= 20000 or total > 100000:
                            reliable = False
                            break
                        count = pdfium.raw.FPDFPageObj_CountMarks(obj)
                        if not 0 <= count <= 128:
                            reliable = False
                            break
                        mcids = set()
                        for mark_number in range(count):
                            mark = pdfium.raw.FPDFPageObj_GetMark(obj, mark_number)
                            value = ctypes.c_int()
                            if mark and pdfium.raw.FPDFPageObjMark_GetParamIntValue(mark, b"MCID", ctypes.byref(value)):
                                mcids.add(value.value)
                        if not mcids:
                            continue
                        if len(mcids) != 1 or obj.type != pdfium.raw.FPDF_PAGEOBJ_TEXT:
                            blocked.update(mcids)
                            continue
                        mcid = next(iter(mcids))
                        byte_count = pdfium.raw.FPDFTextObj_GetText(obj, textpage, None, 0)
                        if not 0 < byte_count <= 40002 or byte_count % 2:
                            blocked.add(mcid)
                            continue
                        text = " ".join(obj.extract().split())
                        if not text or "\x00" in text:
                            blocked.add(mcid)
                            continue
                        found[mcid] = (found.get(mcid, "") + " " + text).strip()[:500]
                    if reliable:
                        contexts.update({(number + 1, mcid): text for mcid, text in found.items() if mcid not in blocked})
                    if total > 100000:
                        break
                finally:
                    if textpage is not None:
                        textpage.close()
                    page.close()
    except InterruptedError:
        raise
    except (OSError, RuntimeError, ValueError, TypeError, IndexError):
        # An unavailable snippet never becomes a guessed page-text excerpt.
        return {}
    return contexts


def _inventory(pdf, inventory_profile=LEGACY_INVENTORY_PROFILE, *, cancel=None, text_contexts=None):
    """Inventory Figures and optional explicitly reviewable structure tags.

    A single Figure element spanning pages can only receive one /Alt. Applying
    different descriptions to its page occurrences is refused later.
    """
    _inventory_cancel(cancel)
    if inventory_profile == EMPTY_TAG_INVENTORY_PROFILE:
        from .empty_tag_edits import inventory
        rows, targets, errors = _inventory(pdf, FORM_INVENTORY_PROFILE,
                                          cancel=cancel, text_contexts=text_contexts)
        extra, extra_targets, extra_errors = inventory(pdf, cancel=cancel, text_contexts=text_contexts)
        return rows + extra, {**targets, **extra_targets}, errors + extra_errors
    if inventory_profile == FORM_INVENTORY_PROFILE:
        from .form_edits import inventory
        rows, targets, errors = _inventory(pdf, TABLE_INVENTORY_PROFILE,
                                          cancel=cancel, text_contexts=text_contexts)
        extra, extra_targets, extra_errors = inventory(pdf, cancel=cancel, text_contexts=text_contexts)
        return rows + extra, {**targets, **extra_targets}, errors + extra_errors
    if inventory_profile == TABLE_INVENTORY_PROFILE:
        from .table_edits import inventory
        rows, targets, errors = _inventory(pdf, SEMANTIC_TREE_INVENTORY_PROFILE,
                                          cancel=cancel, text_contexts=text_contexts)
        extra, extra_targets, extra_errors = inventory(pdf, cancel=cancel, text_contexts=text_contexts)
        return rows + extra, {**targets, **extra_targets}, errors + extra_errors
    if inventory_profile == SEMANTIC_TREE_INVENTORY_PROFILE:
        from .semantic_tree_edits import inventory
        rows, targets, errors = _inventory(pdf, NAVIGATION_INVENTORY_PROFILE,
                                          cancel=cancel, text_contexts=text_contexts)
        extra, extra_targets, extra_errors = inventory(pdf, cancel=cancel,text_contexts=text_contexts)
        return rows + extra, {**targets, **extra_targets}, errors + extra_errors
    if inventory_profile == NAVIGATION_INVENTORY_PROFILE:
        from .navigation_edits import inventory
        rows, targets, errors = _inventory(pdf, PASSAGE_LANGUAGE_INVENTORY_PROFILE,
                                          cancel=cancel, text_contexts=text_contexts)
        extra, extra_targets, extra_errors = inventory(pdf, cancel=cancel)
        return rows + extra, {**targets, **extra_targets}, errors + extra_errors
    if inventory_profile == PASSAGE_LANGUAGE_INVENTORY_PROFILE:
        from .structure_edits import inventory as advanced_inventory
        from .language_edits import inventory as language_inventory
        rows, targets, errors = _inventory(pdf, STRUCTURAL_INVENTORY_PROFILE,
                                          cancel=cancel, text_contexts=text_contexts)
        analysis = {}
        advanced, advanced_targets, advanced_errors = advanced_inventory(pdf, cancel=cancel,
            base_rows=rows, base_targets=targets, analysis_out=analysis)
        languages, language_targets, language_errors = language_inventory(pdf,cancel=cancel,
            analysis=analysis.get('analysis'),proof_unavailable=analysis.get('failed',False),
            base_rows=rows,base_targets=targets,text_contexts=text_contexts)
        return rows+advanced+languages,{**targets,**advanced_targets,**language_targets},errors+advanced_errors+language_errors
    if inventory_profile == ARTIFACT_STRUCTURE_INVENTORY_PROFILE:
        from .structure_edits import inventory
        rows, targets, errors = _inventory(pdf, STRUCTURAL_INVENTORY_PROFILE,
                                          cancel=cancel, text_contexts=text_contexts)
        extra, extra_targets, extra_errors = inventory(pdf, cancel=cancel,
                                                       base_rows=rows, base_targets=targets)
        return rows + extra, {**targets, **extra_targets}, errors + extra_errors
    pages, page_hashes = {}, {}
    for index, page in enumerate(pdf.pages, 1):
        _inventory_cancel(cancel)
        pages[_object_id(page.obj)] = index
        page_hashes[index] = _content_hash(page)
    root = pdf.Root.get("/StructTreeRoot")
    if not _is_dict(root):
        return [], {}, []
    rolemap = root.get("/RoleMap", {})
    rows, targets, errors, seen = [], {}, [], set()
    resolved_content, unresolved_content = set(), set()
    resolution_failed = False
    if inventory_profile == STRUCTURAL_INVENTORY_PROFILE:
        # Use the same independent parser and ParentTree checks as the release
        # screen. A plausible /K integer alone is not a real content binding.
        from .inspection import _page_content, _structure
        try:
            structure_evidence, content_owners, _, _, parent_tree = _structure(pdf, pages)
            resolution_failed = bool(structure_evidence.get("errors"))
            for number, pdf_page in enumerate(pdf.pages, 1):
                _inventory_cancel(cancel)
                content, definitions, painted = _page_content(pdf_page, number, content_owners, parent_tree, {})
                if content["errors"]:
                    resolution_failed = True
                for key, count in definitions.items():
                    if count == 1 and painted.get(key, 0) and len(content_owners.get(key, [])) == 1:
                        resolved_content.add(key)
                unresolved_content.update((number, item["stream"], item["mcid"])
                                          for item in content["parent_tree_failures"] + content["duplicate_mcids"])
        except InterruptedError:
            raise
        except (KeyError, TypeError, ValueError, RuntimeError):
            resolution_failed = True
    traversed = 0

    def traversal_tick():
        nonlocal traversed
        traversed += 1
        if traversed % 256 == 0:
            _inventory_cancel(cancel)

    def role(value):
        value = str(value)
        visited = set()
        while _is_dict(rolemap) and value in rolemap:
            if value in visited:
                errors.append("RoleMap cycle prevents a reliable figure inventory")
                break
            visited.add(value)
            value = str(rolemap[value])
        return value

    def references(node, page, depth=0):
        traversal_tick()
        if depth > 200:
            raise DecisionError("Figure content traversal exceeds 200 levels")
        if isinstance(node, pikepdf.Array):
            return [item for child in node for item in references(child, page, depth + 1)]
        if isinstance(node, int):
            return [{"page": page, "mcid": node, "stream": "page"}]
        if not _is_dict(node):
            return []
        if "/Pg" in node:
            page = pages.get(_object_id(node["/Pg"]))
        if "/MCID" in node:
            stream = node.get("/Stm")
            return [{"page": page, "mcid": int(node["/MCID"]),
                     "stream": _object_id(stream) or "page", "stream_sha256": _stream_hash(stream)}]
        if str(node.get("/Type", "")) == "/OBJR":
            return [{"page": page, "object": _object_id(node.get("/Obj"))}]
        return references(node.get("/K"), page, depth + 1)

    def walk(node, path, page=None, ancestry=(), depth=0):
        traversal_tick()
        if depth > 200:
            errors.append("Structure traversal exceeds 200 levels")
            return
        if isinstance(node, pikepdf.Array):
            for index, child in enumerate(node):
                walk(child, f"{path}/{index}", page, ancestry, depth + 1)
            return
        if not _is_dict(node):
            return
        if "/Pg" in node:
            page = pages.get(_object_id(node["/Pg"]))
        if "/S" not in node:
            if "/K" in node:
                walk(node["/K"], f"{path}/K", page, ancestry, depth + 1)
            return
        target = _object_id(node) or f"direct@{path}"
        if target in seen:
            errors.append(f"Repeated structure element or cycle at {target}")
            return
        seen.add(target)
        resolved = role(node["/S"])
        context = {"role": resolved, "title": str(node.get("/T", "")),
                   "actual_text": str(node.get("/ActualText", ""))}
        if resolved == "/Figure":
            refs = references(node.get("/K"), page)
            occurrence_pages = sorted({ref["page"] for ref in refs if ref["page"] is not None})
            if not occurrence_pages:
                occurrence_pages = [page]
            targets[target] = node
            for occurrence_page in occurrence_pages:
                relevant = [ref for ref in refs if ref["page"] == occurrence_page]
                context_data = {"page": occurrence_page, "element": target,
                                "structure_path": path, "ancestry": list(ancestry),
                                "element_context": context, "references": relevant,
                                "page_content_sha256": page_hashes.get(occurrence_page)}
                fingerprint = _digest(context_data)
                rows.append({"id": f"figure:p{occurrence_page or 'unknown'}:{target}:{fingerprint[:16]}",
                             "kind": "figure-description", "page": occurrence_page,
                             "element": target, "structure_path": path,
                             "context_sha256": fingerprint,
                             "references": relevant, "current": str(node.get("/Alt", "")),
                             "value": str(node.get("/Alt", "")), "status": "pending"})
        if inventory_profile == STRUCTURAL_INVENTORY_PROFILE:
            heading = resolved in {"/P", "/Span", "/Lbl", "/H"} or bool(re.fullmatch(r"/H[0-9]+", resolved))
            table_cell = resolved in {"/TH", "/TD"}
            if heading or table_cell:
                refs = references(node.get("/K"), page)
                # One tag belongs to the structure element, including all of
                # its page references. Never offer conflicting per-page tags.
                occurrence_pages = sorted({ref["page"] for ref in refs if ref.get("page") is not None})
                attributes = node.get("/A", [])
                attributes = list(attributes) if isinstance(attributes, pikepdf.Array) else [attributes]
                attribute_context = [{key: str(attr.get(key, ""))[:20000]
                                      for key in ("/O", "/Scope", "/Headers", "/RowSpan", "/ColSpan")}
                                     if _is_dict(attr) else {"invalid": type(attr).__name__}
                                     for attr in attributes]
                limitations = []
                if len(occurrence_pages) != 1 or not refs or any(ref.get("page") is None or "mcid" not in ref for ref in refs):
                    limitations.append("A tag fix requires one known page and exact marked-content references; shared, empty or object-only elements need source repair.")
                keys = [(ref.get("page"), ref.get("stream"), ref.get("mcid")) for ref in refs]
                if len(keys) != len(set(keys)):
                    limitations.append("Repeated content references prevent an unambiguous tag fix.")
                if resolution_failed or any(key not in resolved_content or key in unresolved_content for key in keys):
                    limitations.append("The marked content or ParentTree ownership cannot be resolved uniquely; repair the source structure first.")
                label_key = "/ActualText" if str(node.get("/ActualText", "")).strip() else "/T" if str(node.get("/T", "")).strip() else None
                snippet = ""
                if not label_key and not limitations and text_contexts and all(ref.get("stream") == "page" for ref in refs):
                    parts = [text_contexts.get((ref.get("page"), ref.get("mcid")), "") for ref in refs]
                    if all(parts):
                        snippet = " ".join(parts)[:500]
                display = {"context_text": str(node.get(label_key, ""))[:500] if label_key else snippet,
                           "context_text_source": label_key or ("MCID-matched selectable text (bounded snippet; inspect the full page)." if snippet else "No embedded text label or unambiguous selectable-text snippet; inspect the exact page and content references."),
                           "structural_eligible": not limitations,
                           "structural_limitations": limitations}
                context_data = {"element": target, "structure_path": path,
                                "ancestry": list(ancestry), "element_context": context,
                                "references": refs, "attributes": attribute_context,
                                "class_attributes": str(node.get("/C", "")),
                                "id": str(node.get("/ID", "")), "display": display,
                                "page_content_sha256": {str(number): page_hashes.get(number) for number in occurrence_pages}}
                fingerprint = _digest(context_data)
                kind = "heading-tag" if heading else "table-header"
                current = resolved.lstrip("/") if heading else _table_value(resolved.lstrip("/"), _table_scope(node))
                rows.append({"id": f"structure:{kind}:{target}:{fingerprint[:16]}",
                             "kind": kind, "page": occurrence_pages[0] if occurrence_pages else page,
                             "element": target, "structure_path": path,
                             "context_sha256": fingerprint, "references": refs,
                             "current": current, "value": current, "status": "pending", **display})
                targets[target] = node
        walk(node.get("/K"), f"{path}/K", page, ancestry + (context,), depth + 1)

    walk(root.get("/K"), "root/K")
    return rows, targets, errors


def collect_decisions(pdf_path, source_sha=None, *, inventory_profile=LEGACY_INVENTORY_PROFILE, cancel=None):
    """Inventory exact staged-PDF decisions; structural controls are opt-in.

    The default preserves the original metadata/Figure inventory byte for byte
    so existing saved reviews remain usable. The structural profile only lists
    source-authored elements and does not select any role, level or header scope.
    """
    inventory_profile_for({"inventory_profile": inventory_profile})
    _inventory_cancel(cancel)
    path = Path(pdf_path)
    document_sha = file_sha256(path)
    source_sha = source_sha or document_sha
    if not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha):
        raise DecisionError("source_sha must be a lowercase SHA-256 fingerprint")
    with pikepdf.open(path) as pdf:
        contexts = _marked_text_contexts(path, cancel) if inventory_profile in {STRUCTURAL_INVENTORY_PROFILE, ARTIFACT_STRUCTURE_INVENTORY_PROFILE, PASSAGE_LANGUAGE_INVENTORY_PROFILE, NAVIGATION_INVENTORY_PROFILE, SEMANTIC_TREE_INVENTORY_PROFILE, TABLE_INVENTORY_PROFILE, FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE} else None
        rows, _, errors = _inventory(pdf, inventory_profile, cancel=cancel, text_contexts=contexts)
        metadata = [{"id": "metadata:title", "kind": "title", "current": str(pdf.docinfo.get("/Title", "")),
                     "value": str(pdf.docinfo.get("/Title", "")), "status": "pending"},
                    {"id": "metadata:language", "kind": "language", "current": str(pdf.Root.get("/Lang", "")),
                     "value": str(pdf.Root.get("/Lang", "")), "status": "pending"}]
    for item in metadata + rows:
        item["binding"] = {"source_sha256": source_sha, "document_sha256": document_sha}
        if "context_sha256" not in item:
            item["context_sha256"] = _digest({"id": item["id"], "current": item["current"]})
    result = {"schema_version": SCHEMA_VERSION, "source_sha256": source_sha,
            "document_sha256": document_sha, "decisions": metadata + rows,
            "inventory_errors": errors,
            "instructions": "Edit value, then explicitly approve with the review command, or use the separately authorized optional best-guess mode. An edited value invalidates its prior acceptance. Auto-accepted values are not human approvals and still need semantic review. Existing text is preserved unless an accepted decision changes it. This inventory generates no semantic alternatives."}
    if inventory_profile != LEGACY_INVENTORY_PROFILE:
        result["inventory_profile"] = inventory_profile
    return result


def _approval_payload(item):
    return {key: value for key, value in item.items()
            if key not in {"approval_sha256", "status"}}


def approval_digest(item):
    return _digest(_approval_payload(item))


def make_automatic_authorization(source_sha256, document_sha256, authorized_at,
                                 authorization_id=None, *, decision_ids):
    """Record an explicit caller's bounded best-guess application consent.

    This is application authority, not a human semantic approval. An empty ID
    list can record a mechanical-only run without authorizing text changes.
    """
    if not isinstance(decision_ids, (list, tuple)):
        raise DecisionError("Automatic decision IDs must be an explicit list")
    data = {"schema_version": AUTOMATIC_AUTHORIZATION_SCHEMA,
            "authorization_id": uuid.uuid4().hex if authorization_id is None else authorization_id,
            "authorized_at": authorized_at, "mode": "best-guess", "human_reviewed": False,
            "source_sha256": source_sha256, "document_sha256": document_sha256,
            "decision_ids": sorted(decision_ids) if all(isinstance(x, str) for x in decision_ids) else list(decision_ids),
            "allowed_kinds": list(AUTOMATIC_KINDS)}
    validate_automatic_authorization(data)
    return data


def validate_automatic_authorization(data, source_sha256=None, document_sha256=None):
    """Refuse a malformed, stale, or broadened automatic application scope."""
    required = {"schema_version", "authorization_id", "authorized_at", "mode", "human_reviewed",
                "source_sha256", "document_sha256", "decision_ids", "allowed_kinds"}
    if not isinstance(data, dict) or set(data) != required or data.get("schema_version") != AUTOMATIC_AUTHORIZATION_SCHEMA:
        raise DecisionError("Unknown or malformed automatic application authorization")
    if (data.get("mode") != "best-guess" or data.get("human_reviewed") is not False
            or data.get("allowed_kinds") != AUTOMATIC_KINDS):
        raise DecisionError("Automatic authorization cannot supply human review or unsupported decision kinds")
    if not isinstance(data.get("authorization_id"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", data["authorization_id"]):
        raise DecisionError("An explicit automatic authorization ID is required")
    _validate_date(data.get("authorized_at"))
    for key, expected in (("source_sha256", source_sha256), ("document_sha256", document_sha256)):
        if not isinstance(data.get(key), str) or not _SHA.fullmatch(data[key]) or expected is not None and data[key] != expected:
            raise DecisionError("Stale automatic authorization: " + key + " differs")
    ids = data.get("decision_ids")
    if (not isinstance(ids, list) or len(ids) > 10000 or any(not isinstance(x, str) for x in ids)
            or len(set(ids)) != len(ids) or ids != sorted(ids)
            or any(x != "metadata:title" and not x.startswith("figure:") for x in ids)):
        raise DecisionError("Automatic authorization requires exact title/figure decision IDs")
    return data


def _automatic_digest(item):
    return _digest({key: value for key, value in item.items() if key != "automatic_acceptance_sha256"})


def automatic_acceptance_valid(item, authorization=None):
    """Check one automatic value's integrity, and optional explicit run consent.

    Integrity alone is insufficient to apply a value: apply_decisions requires
    the caller to supply the matching authorization independently.
    """
    try:
        if not isinstance(item, dict) or item.get("status") != "auto-accepted":
            return False
        if any(key in item for key in ("approved_by", "approved_at", "approval_sha256")):
            return False
        _validate_value(item)
        if item.get("kind") not in AUTOMATIC_KINDS or not _SHA.fullmatch(item.get("context_sha256", "")):
            return False
        binding = item.get("binding", {})
        application = item.get("automatic_application", {})
        if (not isinstance(application, dict) or set(application) != {"schema_version", "authorization_id", "authorized_at", "mode", "human_reviewed", "authorization_sha256", "authorization", "origin"}
                or application.get("schema_version") != AUTOMATIC_APPLICATION_SCHEMA):
            return False
        bound = application.get("authorization")
        validate_automatic_authorization(bound, binding.get("source_sha256"), binding.get("document_sha256"))
        if not isinstance(binding, dict) or set(binding) != {"source_sha256", "document_sha256"}:
            return False
        if (item.get("id") not in bound["decision_ids"] or application.get("human_reviewed") is not False
                or application.get("mode") != "best-guess"
                or application.get("authorization_id") != bound["authorization_id"]
                or application.get("authorized_at") != bound["authorized_at"]
                or application.get("authorization_sha256") != _digest(bound)
                or not isinstance(application.get("origin"), dict) or not application["origin"]
                or len(json.dumps(application["origin"], allow_nan=False)) > 32768):
            return False
        if authorization is not None:
            validate_automatic_authorization(authorization, binding["source_sha256"], binding["document_sha256"])
            if authorization != bound:
                return False
        return item.get("automatic_acceptance_sha256") == _automatic_digest(item)
    except (DecisionError, TypeError, ValueError, AttributeError):
        return False


def bind_automatic_acceptance(item, value, authorization, *, origin, human_touched=False):
    """Apply explicit best-guess authority to one untouched pending decision.

    The proposed value is separate from the current item so that an existing
    human edit cannot be mistaken for an AI draft eligible for replacement.
    """
    if (not isinstance(item, dict) or human_touched or item.get("human_touched")
            or item.get("status") != "pending" or item.get("value") != item.get("current")
            or any(key in item for key in ("approved_by", "approved_at", "approval_sha256"))):
        raise DecisionError("Human-edited or approved decisions are protected from automatic replacement")
    binding = item.get("binding", {})
    if not isinstance(binding, dict) or set(binding) != {"source_sha256", "document_sha256"}:
        raise DecisionError("Automatic decisions require exact source and document bindings")
    validate_automatic_authorization(authorization, binding.get("source_sha256"), binding.get("document_sha256"))
    if item.get("kind") not in AUTOMATIC_KINDS or item.get("id") not in authorization["decision_ids"]:
        raise DecisionError("This decision is outside the authorized automatic scope")
    if not isinstance(origin, dict) or not origin or len(json.dumps(origin, allow_nan=False)) > 32768:
        raise DecisionError("An attributable bounded automatic origin is required")
    updated = copy.deepcopy(item)
    updated.update(value=value, status="auto-accepted")
    updated["automatic_application"] = {"schema_version": AUTOMATIC_APPLICATION_SCHEMA,
        "authorization_id": authorization["authorization_id"], "authorized_at": authorization["authorized_at"],
        "mode": "best-guess", "human_reviewed": False, "authorization_sha256": _digest(authorization),
        "authorization": copy.deepcopy(authorization), "origin": copy.deepcopy(origin)}
    if origin.get("schema_version") == "phase2-ai-origin-1":
        updated["ai_origin"] = copy.deepcopy(origin)
    _validate_value(updated)
    updated["automatic_acceptance_sha256"] = _automatic_digest(updated)
    if not automatic_acceptance_valid(updated, authorization):
        raise DecisionError("Automatic acceptance lacks a valid occurrence/context binding")
    item.clear()
    item.update(updated)
    return item


def rebind_automatic_acceptance(item, authorization, *, human_touched=False):
    """Carry an intact automatic value into a newly authorized exact run.

    Original values, context and model origin remain unchanged. Prior run
    authority stays in its immutable bundle; no draft or review is invented.
    """
    if human_touched or item.get("human_touched") or not automatic_acceptance_valid(item):
        raise DecisionError("Only an intact untouched automatic decision can be rebound")
    binding = item["binding"]
    validate_automatic_authorization(authorization, binding["source_sha256"], binding["document_sha256"])
    if item["id"] not in authorization["decision_ids"]:
        raise DecisionError("This decision is outside the new automatic authorization")
    updated = copy.deepcopy(item)
    updated["automatic_application"].update(authorization_id=authorization["authorization_id"],
        authorized_at=authorization["authorized_at"], authorization_sha256=_digest(authorization),
        authorization=copy.deepcopy(authorization))
    updated["automatic_acceptance_sha256"] = _automatic_digest(updated)
    if not automatic_acceptance_valid(updated, authorization):
        raise DecisionError("Rebound automatic decision is invalid")
    item.clear()
    item.update(updated)
    return item


def bind_approval(item, reviewer, reviewed_at):
    """Explicit approval helper; caller must obtain this decision from a person."""
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise DecisionError("A named human reviewer is required")
    _validate_date(reviewed_at)
    _validate_value(item)
    item.pop("automatic_acceptance_sha256", None)
    item["approved_by"] = reviewer.strip()
    item["approved_at"] = reviewed_at
    item["status"] = "approved"
    item["approval_sha256"] = approval_digest(item)
    return item


def _validate_date(value):
    from datetime import date, datetime
    if not isinstance(value, str) or not value.strip():
        raise DecisionError("An explicit review date is required")
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DecisionError("Use an ISO review date or timestamp") from exc


def _validate_value(item):
    kind, value = item.get("kind"), item.get("value")
    if kind == "empty-tag-removal":
        from .empty_tag_edits import validate_value
        return validate_value(item)
    if kind == "form-controls":
        from .form_edits import validate_value
        return validate_value(item)
    if kind == "table-structure":
        from .table_edits import validate_value
        return validate_value(item)
    if kind in {"semantic-role", "reading-order", "tree-move", "semantic-list"}:
        from .semantic_tree_edits import validate_value
        return validate_value(item)
    if kind in {"annotation-name", "link-name", "link-target", "bookmark-entry", "bookmark-additions"}:
        from .navigation_edits import validate_value
        return validate_value(item)
    if kind not in {"title", "language", "figure-description", "heading-tag", "table-header", "figure-purpose", "structure-role", "passage-language", "page-language"}:
        raise DecisionError(f"Unsupported decision kind: {kind}")
    if not isinstance(value, str) or not value.strip() or "\x00" in value or len(value) > 20000:
        raise DecisionError("An accepted decision requires nonempty text without NUL characters")
    if kind == "language" and not _LANGUAGE.fullmatch(value):
        raise DecisionError("Language must be an explicit language tag such as en-US")
    if kind in {"figure-purpose", "structure-role"}:
        from .structure_edits import validate_value
        validate_value(item)
    if kind in {"passage-language", "page-language"}:
        from .language_edits import validate_value
        validate_value(item)
    if kind in {"heading-tag", "table-header"}:
        if item.get("structural_eligible") is not True:
            raise DecisionError("This structure element has no unambiguous single-page marked-content context")
        if kind == "heading-tag":
            if value != item.get("current") and not re.fullmatch(r"H[1-6]", value):
                raise DecisionError("A reviewed heading fix must select H1 through H6; visible text is never invented")
        else:
            _validated_table_value(value)


def _validated_table_value(value):
    try:
        specification = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DecisionError("Table header fix must be an explicit role and scope specification") from exc
    if not isinstance(specification, dict) or set(specification) != {"role", "scope"}:
        raise DecisionError("Table header fix permits only role and scope; IDs, references and spans cannot be invented")
    role, scope = specification["role"], specification["scope"]
    if (not isinstance(role, str) or role not in {"TH", "TD"}
            or scope is not None and (not isinstance(scope, str) or scope not in {"Row", "Column", "Both"})):
        raise DecisionError("Table header fix requires TH/TD and Row, Column, Both or no scope")
    if role == "TD" and scope is not None:
        raise DecisionError("Only a header cell can have a header scope")
    return specification


def _apply_table_value(node, value):
    specification = _validated_table_value(value)
    node["/S"] = pikepdf.Name("/" + specification["role"])
    attrs = node.get("/A", [])
    attrs = list(attrs) if isinstance(attrs, pikepdf.Array) else [attrs]
    retained = []
    for attr in attrs:
        if _is_dict(attr) and str(attr.get("/O", "")) == "/Table":
            # Preserve IDs, Headers, spans and unrelated table attributes;
            # replace only the explicitly reviewed Scope property.
            attr = pikepdf.Dictionary({key: item for key, item in attr.items() if key != "/Scope"})
        if attr is not None:
            retained.append(attr)
    if specification["scope"] is not None:
        retained.append(pikepdf.Dictionary(O=pikepdf.Name.Table, Scope=pikepdf.Name("/" + specification["scope"])))
    if retained:
        node["/A"] = pikepdf.Array(retained)
    elif "/A" in node:
        del node["/A"]


def write_sidecar(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    descriptor, filename = tempfile.mkstemp(prefix=".decisions-", suffix=".json", dir=path.parent)
    checkpoint = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        atomic_replace(checkpoint, path)
    finally:
        checkpoint.unlink(missing_ok=True)
    return path


def load_sidecar(path):
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yml", ".yaml"}:
        try:
            import yaml
        except ImportError as exc:
            raise DecisionError("YAML decisions require PyYAML; JSON sidecars work without it") from exc
        data = yaml.safe_load(content)
    else:
        data = json.loads(content)
    if not isinstance(data, dict):
        raise DecisionError("Sidecar must contain one mapping")
    return data


def decisions_digest(data):
    return _digest(data)


def apply_decisions(input_path, output_path, sidecar, expected_source_sha, *, automatic_authorization=None, cancel=None):
    """Apply explicitly accepted values or refuse without publishing.

    Pending decisions never write PDF objects. Stale accepted decisions are a
    hard refusal. Automatic values require separate exact run authorization;
    they remain distinct from human approvals in the returned evidence.
    """
    _inventory_cancel(cancel)
    source, destination = Path(input_path).resolve(), Path(output_path).resolve()
    if source == destination:
        raise DecisionError("Decisions must write a separate checkpoint")
    if destination.exists():
        raise DecisionError("Refusing to overwrite an existing decision checkpoint")
    data = load_sidecar(sidecar) if isinstance(sidecar, (str, Path)) else copy.deepcopy(sidecar)
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise DecisionError("Unknown or missing sidecar schema")
    profile = inventory_profile_for(data)
    fresh = collect_decisions(source, expected_source_sha, inventory_profile=profile, cancel=cancel)
    if data.get("source_sha256") != expected_source_sha:
        raise DecisionError("Stale sidecar: original source fingerprint differs")
    if data.get("document_sha256") != fresh["document_sha256"]:
        raise DecisionError("Stale sidecar: staged PDF fingerprint differs")
    current = {item["id"]: item for item in fresh["decisions"]}
    items = data.get("decisions")
    if not isinstance(items, list):
        raise DecisionError("Sidecar decisions must be a list")
    if automatic_authorization is not None:
        validate_automatic_authorization(automatic_authorization, expected_source_sha, fresh["document_sha256"])
        if set(automatic_authorization["decision_ids"]) - set(current):
            raise DecisionError("Automatic authorization contains an absent decision occurrence")
    ids, approved, automatic, pending = set(), [], [], []
    for item_number, item in enumerate(items):
        if item_number % 256 == 0:
            _inventory_cancel(cancel)
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item.get("id") in ids:
            raise DecisionError("Malformed or duplicate decision ID")
        ident = item.get("id")
        ids.add(ident)
        reference = current.get(ident)
        if reference is None:
            raise DecisionError("Stale sidecar: decision occurrence is absent")
        for key in ("kind", "binding", "context_sha256", "current", "element", "page", "structure_path", "references", *_STRUCTURAL_CONTEXT):
            if item.get(key) != reference.get(key):
                raise DecisionError(f"Stale or changed decision context: {ident}")
        if item.get("status") == "approved":
            _validate_value(item)
            if not isinstance(item.get("approved_by"), str) or not item["approved_by"].strip():
                raise DecisionError("Approved decision has no named reviewer")
            _validate_date(item.get("approved_at"))
            if item.get("approval_sha256") != approval_digest(item):
                raise DecisionError(f"Approval is stale after a decision edit: {ident}")
            approved.append(item)
        elif item.get("status") == "auto-accepted":
            if automatic_authorization is None or not automatic_acceptance_valid(item, automatic_authorization):
                raise DecisionError(f"Automatic acceptance is stale or lacks explicit matching run authorization: {ident}")
            automatic.append(item)
        elif item.get("status") == "pending":
            pending.append(ident)
        else:
            raise DecisionError("Decision status must be pending, approved, or explicitly auto-accepted")
    if ids != set(current):
        raise DecisionError("Sidecar omits required inventory decisions")
    if fresh["inventory_errors"]:
        raise DecisionError("Decision inventory is incomplete: " + "; ".join(fresh["inventory_errors"]))
    figure_groups = {}
    for item in items:
        if item["kind"] == "figure-description":
            figure_groups.setdefault(item["element"], []).append(item)
    for group in figure_groups.values():
        selected = [item for item in group if item["status"] in {"approved", "auto-accepted"}]
        if selected and (len(selected) != len(group) or len({item["value"] for item in selected}) != 1):
            raise DecisionError("A shared Figure element requires identical accepted descriptions for every occurrence")
    accepted = approved + automatic
    new_changes = [item for item in accepted if item["kind"] in {"figure-purpose", "structure-role"}
                   and item["value"] != item["current"]]
    language_changes = [item for item in accepted if item["kind"] in {"passage-language", "page-language"}
                        and item["value"] != item["current"]]
    navigation_changes = [item for item in accepted if item["kind"] in {"annotation-name", "link-name", "link-target", "bookmark-entry", "bookmark-additions"}
                          and item["value"] != item["current"]]
    tree_changes = [item for item in accepted if item["kind"] in {"semantic-role", "reading-order", "tree-move", "semantic-list"}
                    and item["value"] != item["current"]]
    table_changes = [item for item in accepted if item["kind"] == "table-structure"
                     and item["value"] != item["current"]]
    form_changes = [item for item in accepted if item["kind"] == "form-controls"
                    and item["value"] != item["current"]]
    empty_changes = [item for item in accepted if item["kind"] == "empty-tag-removal"
                     and item["value"] != item["current"]]
    other_changes = [item for item in accepted if item["kind"] not in {"figure-purpose", "structure-role"}
                     and item["value"] != item["current"]]
    artifact_elements = {item["element"] for item in new_changes if item["kind"] == "figure-purpose"}
    if any(item["kind"] == "figure-description" and item.get("element") in artifact_elements for item in other_changes):
        raise DecisionError("A Figure cannot receive a changed description and become decorative in the same pass")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".decisions-", suffix=".pdf", dir=destination.parent)
    os.close(descriptor)
    checkpoint = Path(temp_name)
    changed = []
    try:
        accepted = approved + automatic
        if not accepted:
            shutil.copyfile(source, checkpoint)
        else:
            with pikepdf.open(source) as pdf:
                _, targets, errors = _inventory(pdf, profile, cancel=cancel)
                if errors:
                    raise DecisionError("Cannot apply decisions to an incomplete structure inventory")
                language_plans = []
                navigation_plans = []
                tree_plans = []
                table_plans = []
                form_plans = []
                empty_plans = []
                if empty_changes:
                    from .empty_tag_edits import prepare_changes
                    empty_plans = prepare_changes(pdf,empty_changes,cancel=cancel,other_changes=other_changes+new_changes)
                text_contexts = _marked_text_contexts(source,cancel) if tree_changes or language_changes or table_changes else None
                if form_changes:
                    from .form_edits import prepare_changes
                    form_plans = prepare_changes(pdf,form_changes,cancel=cancel,other_changes=other_changes+new_changes)
                if table_changes:
                    from .table_edits import prepare_changes
                    table_plans = prepare_changes(pdf,table_changes,cancel=cancel,text_contexts=text_contexts,other_changes=other_changes+new_changes)
                if tree_changes:
                    from .semantic_tree_edits import prepare_changes
                    tree_plans = prepare_changes(pdf,tree_changes,cancel=cancel,text_contexts=text_contexts,other_changes=other_changes+new_changes)
                if navigation_changes:
                    from .navigation_edits import prepare_changes
                    navigation_plans = prepare_changes(pdf, navigation_changes, cancel=cancel)
                if language_changes:
                    from .language_edits import prepare_changes
                    language_plans = prepare_changes(pdf, language_changes, cancel=cancel,
                        text_contexts=text_contexts)
                if new_changes:
                    from .structure_edits import apply_changes
                    changed.extend(apply_changes(pdf, new_changes, cancel=cancel))
                if language_plans:
                    from .language_edits import apply_prepared
                    changed.extend(apply_prepared(language_plans,cancel=cancel))
                if navigation_plans:
                    from .navigation_edits import apply_prepared
                    changed.extend(apply_prepared(pdf,navigation_plans,cancel=cancel))
                for item in accepted:
                    _inventory_cancel(cancel)
                    value = item["value"]
                    if item["kind"] == "title":
                        if item["current"] != value:
                            pdf.docinfo["/Title"] = value
                            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
                                metadata["dc:title"] = value
                            preferences = pdf.Root.get("/ViewerPreferences", pikepdf.Dictionary())
                            preferences["/DisplayDocTitle"] = True
                            pdf.Root["/ViewerPreferences"] = preferences
                            changed.append(item["id"])
                    elif item["kind"] == "language":
                        if item["current"] != value:
                            pdf.Root["/Lang"] = value
                            with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
                                metadata["dc:language"] = [value]
                            changed.append(item["id"])
                    elif item["kind"] == "heading-tag" and item["current"] != value:
                        targets[item["element"]]["/S"] = pikepdf.Name("/" + value)
                        changed.append(item["id"])
                    elif item["kind"] == "table-header" and item["current"] != value:
                        _apply_table_value(targets[item["element"]], value)
                        changed.append(item["id"])
                    elif item["kind"] == "figure-description" and item["current"] != value:
                        targets[item["element"]]["/Alt"] = value
                        changed.append(item["id"])
                if tree_plans:
                    from .semantic_tree_edits import apply_prepared
                    changed.extend(apply_prepared(pdf,tree_plans,cancel=cancel))
                if table_plans:
                    from .table_edits import apply_prepared
                    changed.extend(apply_prepared(pdf,table_plans,cancel=cancel))
                if form_plans:
                    from .form_edits import apply_prepared
                    changed.extend(apply_prepared(pdf,form_plans,cancel=cancel))
                if empty_plans:
                    from .empty_tag_edits import apply_prepared
                    changed.extend(apply_prepared(pdf,empty_plans,cancel=cancel))
                if changed:
                    # Save to the owned file handle: pikepdf otherwise creates
                    # another rename checkpoint, which some Windows sandboxes
                    # disallow in redirected temporary directories.
                    with checkpoint.open("wb") as stream:
                        if table_plans or form_plans:
                            # Headers/Scope require PDF 1.5 and Summary PDF 1.7.
                            # Raise the serialization version without touching
                            # protected descriptive XMP or lowering newer PDFs.
                            pdf.save(stream, deterministic_id=True, min_version="1.7",
                                     fix_metadata_version=False)
                        else:
                            save_options = {}
                            if empty_plans:
                                save_options['fix_metadata_version'] = False
                            if profile in {FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE}:
                                from .form_edits import has_form_signals
                                if has_form_signals(pdf):
                                    # Named metadata edits do not authorize an
                                    # additional automatic XMP version rewrite.
                                    save_options['fix_metadata_version'] = False
                            pdf.save(stream, deterministic_id=True, **save_options)
                else:
                    shutil.copyfile(source, checkpoint)
        if new_changes or language_changes or navigation_changes or tree_changes or table_changes or form_changes or empty_changes:
            from .structure_edits import verify_output
            verify_output(source, checkpoint, new_changes, other_changes=other_changes, cancel=cancel)
        if file_sha256(source) != fresh["document_sha256"]:
            raise DecisionError("Staged PDF changed while decisions were being applied")
        _inventory_cancel(cancel)
        atomic_replace(checkpoint, destination)
    finally:
        checkpoint.unlink(missing_ok=True)
    return {"schema_version": SCHEMA_VERSION, "source_sha256": expected_source_sha,
            "input_sha256": fresh["document_sha256"], "output_sha256": file_sha256(destination),
            "decisions_sha256": decisions_digest(data), "approved": [item["id"] for item in approved],
            "auto_accepted": [item["id"] for item in automatic], "human_reviewed_automatic": False,
            "automatic_authorization_sha256": _digest(automatic_authorization) if automatic_authorization is not None else None,
            "changed": changed, "pending": pending, "data_sent": {"provider": None, "document_api_calls": 0}}
