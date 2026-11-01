"""Declared Phase 1 check coverage, separate from strict UA and human review.

Passing this profile means its declared screens passed. Bounded contrast and
language findings supplement mechanical heading rules. Unmeasured contrast,
language meaning, reading order, descriptions and font mapping remain human work.
"""
from __future__ import annotations

import re

PROFILE = "phase1-core-1.1+ally-pdf-screens-1+bounded-readability-1"
ADVISORY_SCREENS = ('small-font', 'empty-structure-tags')
ALLY_SCREENS = ("marked-headings", "heading-start-level", "heading-depth",
                "heading-sequence", "language-correctness", "contrast")
BLOCKING = ("content-linkage", "content-coverage", "link-structure", "metadata",
            "figure-alternatives", "table-header-associations", "font-embedding",
            "font-mapping-shape", "unsupported-features", "scan-text-layer")
PLACEHOLDER_TITLE = re.compile(r"^(?:untitled(?:\s+document)?|document|pdf|test|unknown|title|new\s+document|[\W\d_]+)(?:\.pdf)?$", re.I)
PLACEHOLDER_ALT = re.compile(r"^(?:image|figure|picture|photo|graphic|illustration|alt(?:ernative)?\s*text|todo|tbd|placeholder|description(?:\s+here)?)[\s_\-]*\d*[.\s]*$|\.(?:png|jpe?g|gif|tiff?|bmp|svg)$", re.I)


def _entry(name, status, evidence, scope, limitations=None, blocking=None):
    return {"id": name, "name": name, "status": status,
            "blocking": name in BLOCKING if blocking is None else blocking,
            "severity": "blocking" if (name in BLOCKING if blocking is None else blocking) else "advisory",
            "evidence": evidence, "scope": scope, "limitations": limitations or []}


def _manual(key, subject, detail, pages=None):
    return {"id": key, "category": key, "subject": subject, "status": "pending",
            "required": True, "detail": detail, "pages": pages or []}


def _tables(structure):
    tables = structure.get("tables", [])
    count = structure.get("tag_counts", {}).get("/Table", 0)
    if not count:
        return "not-applicable", {"tables": 0, "mechanisms": []}
    if not tables or "table_cells" not in structure:
        return "not-tested", {"tables": count, "reason": "No table/cell relationship inventory"}
    results = []
    for table in tables:
        cells = [cell for cell in structure["table_cells"] if cell.get("table") == table["element"]]
        headers = [cell for cell in cells if cell["role"] == "/TH"]
        data = [cell for cell in cells if cell["role"] == "/TD"]
        identifiers = [cell["id"] for cell in headers if cell.get("id")]
        unique_ids = set(identifiers)
        scope_ok = bool(headers) and all(cell.get("scope") and all(scope in ("/Row", "/Column", "/Both") for scope in cell["scope"]) for cell in headers)
        header_refs = bool(headers and data) and len(unique_ids) == len(identifiers) and all(cell.get("headers") and all(ref in unique_ids for ref in cell["headers"]) for cell in data)
        invalid_refs = [cell["element"] for cell in cells if any(ref not in unique_ids for ref in cell.get("headers", []))]
        complex_spans = [cell["element"] for cell in cells if any(span != 1 for span in cell.get("row_spans", []) + cell.get("col_spans", []))]
        invalid_spans = [cell["element"] for cell in cells if any(span < 1 for span in cell.get("row_spans", []) + cell.get("col_spans", []))]
        status = "fail" if not headers or invalid_refs or invalid_spans or not (scope_ok or header_refs) else "pass"
        results.append({"element": table["element"], "page": table["page"], "status": status,
                        "header_count": len(headers), "data_cell_count": len(data),
                        "mechanism": "scope" if scope_ok else "headers-id" if header_refs else "missing-or-unresolved",
                        "invalid_header_references": invalid_refs, "complex_spans": complex_spans,
                        "invalid_spans": invalid_spans})
    overall = "fail" if any(x["status"] == "fail" for x in results) else "needs-review" if any(x["status"] != "pass" for x in results) else "pass"
    return overall, {"tables": count, "mechanisms": results}


def assess(inspection, source=None):
    """Assess an inspection; optional source is the unmodified input inspection.

    Source classification retains scan/OCR review signals after an OCR text
    layer is added. Actual missing text on the final image-only page blocks even
    if a tagger attached an apparently valid Figure alternative to the scan.
    """
    results, manual = [], []
    if inspection.get("error"):
        error = _entry("document-open", "error", inspection["error"], "Parse/read input", blocking=True)
        return {"profile": PROFILE, "status": "error", "checks": [error], "blocking_checks": list(BLOCKING),
                "blockers": [error], "manual_queue": [], "automated_coverage_complete": False}
    previous = {item.get("id", item.get("name")): item for item in inspection.get("checks", [])}
    for name in ("content-linkage", "content-coverage", "link-structure", "font-embedding"):
        item = previous.get(name, {})
        results.append(_entry(name, item.get("status", "not-tested"), item.get("evidence", {}),
                              item.get("scope", "Required implementation missing"), item.get("limitations")))
    meta = inspection.get("metadata", {})
    title, language = meta.get("title", "").strip(), meta.get("language", "").strip()
    plausible_title = bool(title) and not PLACEHOLDER_TITLE.search(title) and len(title) <= 1000
    plausible_language = bool(re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language))
    metadata_ok = plausible_title and plausible_language and meta.get("display_doc_title", False)
    results.append(_entry("metadata", "pass" if metadata_ok else "fail", {**meta, "title_plausible": plausible_title,
                          "language_syntax_plausible": plausible_language}, "Plausible title/language and title display",
                          ["Meaning and language appropriateness remain human judgments; strict validator checks export metadata."]))
    figures = inspection.get("structure", {}).get("figures", [])
    bad = [f["element"] for f in figures if not f.get("alt", "").strip() or PLACEHOLDER_ALT.search(f.get("alt", "").strip())]
    results.append(_entry("figure-alternatives", "fail" if bad else "pass" if figures else "not-applicable",
                          {"figure_count": len(figures), "missing_or_placeholder": bad}, "Tagged figures; present non-placeholder alternatives",
                          ["Description adequacy, decorative decisions and untagged image meaning require review."]))
    relationship_assessment = inspection.get("table_relationships")
    if (isinstance(relationship_assessment, dict)
            and relationship_assessment.get("policy") == "bounded-table-relationships-1"
            and relationship_assessment.get("status") in {"pass", "fail", "needs-review", "not-applicable"}):
        table_status, table_evidence = relationship_assessment["status"], relationship_assessment
        table_scope = "Bounded table grid, Scope, Headers hierarchy, document IDs and IDTree integrity"
        table_limitations = relationship_assessment.get("limitations", [])
    else:
        table_status, table_evidence = _tables(inspection.get("structure", {}))
        table_scope = "Direct table-cell attributes: Scope or TD Headers referencing TH IDs"
        table_limitations = ["ClassMap attributes are not resolved by this screen. Valid complex spans remain explicit human relationship review; semantics remain unverified."]
    results.append(_entry("table-header-associations", table_status, table_evidence,
                          table_scope, table_limitations))
    used_fonts = [font for font in inspection.get("fonts", []) if font.get("used_text_operations")]
    bad_mapping = [f["object"] for f in used_fonts if f.get("mapping_status") in ("fail", "error")]
    uncertain_mapping = [f["object"] for f in used_fonts if f.get("mapping_status") not in ("pass", "fail", "error")]
    results.append(_entry("font-mapping-shape", "fail" if bad_mapping else "pass" if used_fonts else "not-applicable",
                          {"invalid_mapping_fonts": bad_mapping, "mapping_requires_review": uncertain_mapping},
                          "Invalid explicit CMap detection; strict validator independently tests applicable mapping rules",
                          ["This is a syntax screen, not used-code mapping coverage or semantic character accuracy."]))
    features = inspection.get("features", {})
    form_assessment = inspection.get('form_accessibility')
    known_form = (isinstance(form_assessment, dict)
        and form_assessment.get('policy') == 'bounded-acroform-1'
        and isinstance(form_assessment.get('supported_structure'), bool)
        and form_assessment.get('status') in {'pass', 'fail', 'needs-review', 'not-applicable'})
    if features.get('forms'):
        results.append(_entry('form-accessibility', form_assessment['status'] if known_form else 'not-tested',
            form_assessment if known_form else {'reason': 'No recognized independent form assessment'},
            'Static field names, Widget/Form ownership and structure-based tab navigation',
            ['Actual label meaning, label-in-name, keyboard operation and assistive-technology output require human acceptance.'], blocking=True))
    special = {k: features[k] for k in ("encrypted", "signed_or_signature_fields", "forms", "attachments", "javascript", "optional_content", "equation_tags") if features.get(k)}
    if known_form and form_assessment.get('supported_structure') is True:
        special.pop('forms', None)
    version = features.get("pdf_version", "")
    try:
        if float(version) > 1.7:
            special["unsupported_pdf_version"] = version
    except (ValueError, TypeError):
        special["unknown_pdf_version"] = version
    results.append(_entry("unsupported-features", "fail" if special else "pass", special,
                          "Encrypted/signed/form/attachment/JavaScript/optional content/formula/version signals",
                          ["Untagged equations and visual slide layouts are outside reliable automatic detection."]))
    credential = inspection.get('content_credentials')
    if isinstance(credential, dict) and credential.get('policy') == 'bounded-c2pa-associated-file-1':
        results.append(_entry('content-credentials', 'needs-review', credential,
            'C2PA-labelled associated-file inventory; original cryptographic validity is not verified',
            ['Ordinary Fix/OCR remains blocked. Only explicit consent can create a separate copy without these credentials; this is not accessibility approval.'], blocking=False))
    pages = inspection.get("pages", [])
    no_text_images = [p["page"] for p in pages if p.get("class") == "scanned"]
    results.append(_entry("scan-text-layer", "fail" if no_text_images else "pass",
                          {"image_only_pages_without_text": no_text_images}, "Image-bearing pages without selectable text",
                          ["Photographs and image-only art cannot be distinguished from scanned text automatically; review needed before acceptance."]))
    if no_text_images:
        manual.append(_manual("scans", "Image-only pages", "Select the tested OCR route for scanned text, or document a reviewed image-only art decision before reprocessing.", no_text_images))
    original = source or inspection
    image_pages = [p["page"] for p in original.get("pages", []) if p.get("class") in ("scanned", "mixed")]
    if image_pages:
        manual.append(_manual("image-and-ocr", "Scanned text and image meaning", "Check each image region for missing scanned text; verify OCR accuracy, completeness and order where used.", image_pages))
    for name in ("heading-navigation", "reading-order"):
        item = previous.get(name, {})
        results.append(_entry(name, item.get("status", "not-tested"), item.get("evidence", {}),
                              item.get("scope", "Human assessment"), item.get("limitations"), blocking=False))
    for name in ALLY_SCREENS:
        item = previous.get(name, {})
        status = item.get("status", "not-tested")
        row = _entry(name, status, item.get("evidence", {}), item.get("scope", "Screen not measured"),
                     item.get("limitations"), blocking=status in {"fail", "error"} and name != "contrast")
        if name == "contrast":
            row["limitations"] = list(row["limitations"]) + ["A below-threshold measurement needs human applicability review for logos, decorative or incidental text; it is not an unconditional conformance failure."]
        if item.get("fix_path"):
            row["fix_path"] = item["fix_path"]
        results.append(row)
    for field, policy, name, category, subject, detail in (
        ('small_font', 'bounded-small-font-1', 'small-font', 'small-fonts', 'Text smaller than 9 points',
         'Review measured small text and any uncertain or unmeasured regions in context, including footnotes, superscripts, subscripts and artifacts. Nine points is an optional readability advisory, not a WCAG minimum or vendor result. If enlargement is needed, repair the original authoring document, reflow and export a separate PDF; this tool does not resize text.'),
        ('empty_tags', 'bounded-empty-structure-1', 'empty-structure-tags', 'empty-tags', 'Empty-looking structure tags',
         'Review each empty-looking tag and its surrounding meaning. MCIDs, object references, replacement text, descriptions and referenced elements are protected. Only an offered, source-bound P/Span leaf can be saved for removal and explicitly accepted before Apply; no tag is deleted automatically.'),
    ):
        measured = inspection.get(field)
        known = (isinstance(measured, dict) and measured.get('policy') == policy
                 and measured.get('advisory') is True
                 and measured.get('status') in {'pass', 'fail', 'needs-review', 'not-applicable', 'error'}
                 and isinstance(measured.get('findings'), list) and isinstance(measured.get('uncertain'), list)
                 and isinstance(measured.get('coverage'), dict) and isinstance(measured['coverage'].get('complete'), bool))
        clean = known and measured['coverage']['complete'] and not measured['findings'] and not measured['uncertain']
        status = measured['status'] if known else 'not-tested'
        if status in {'pass', 'not-applicable'} and not clean: status = 'needs-review'
        evidence = measured if known else {'reason': 'No recognized source-bound advisory assessment'}
        row = _entry(name, status, evidence, 'Bounded advisory screen; separate from strict validation and human meaning',
            measured.get('limitations', []) if known else ['Unknown coverage cannot establish an empty-free or small-font-free result.'], blocking=False)
        if known and measured.get('fix_path'): row['fix_path'] = measured['fix_path']
        results.append(row)
        if not clean or status not in {'pass', 'not-applicable'}:
            page_numbers = sorted({record['page'] for record in evidence.get('findings', []) + evidence.get('uncertain', [])
                                   if isinstance(record, dict) and isinstance(record.get('page'), int)})
            item = _manual(category, subject, detail, page_numbers)
            item['evidence'] = evidence; manual.append(item)
    manual += [_manual("reading-order", "Reading order and structure", "Listen/test with an assistive technology; verify headings, list relationships, artifacts and navigation."),
               _manual("metadata-meaning", "Title and language", "Confirm that the title is meaningful and languages match the document."),
               _manual("contrast", "Visual contrast", "Assess meaningful text/graphics contrast and regions not measured automatically."),
               _manual("font-characters", "Characters and font mapping", "Check extracted/spoken characters against visible text; mapping syntax and a validator pass do not establish meaning.")]
    if figures:
        manual.append(_manual("figure-meaning", "Figure descriptions", "Confirm each description conveys the figure's purpose in its document context.", sorted({f["page"] for f in figures if f.get("page")})))
    if table_evidence.get("tables"):
        manual.append(_manual("table-relationships", "Tables", "Check cell/header relationships, cross-page tables and reading order."))
    if features.get('forms'):
        manual.append(_manual('form-meaning', 'Form labels and keyboard navigation',
            'Compare each accessible name with its visible label and required instructions. Test real keyboard focus, activation/value changes and assistive-technology announcements in the intended PDF reader. The preserved fields remain interactive; static metadata and graph checks do not prove usable form operation.'))
    for item in manual:
        if item["id"] == "contrast":
            measured = previous.get("contrast", {})
            item["evidence"] = measured.get("evidence", {})
            item["detail"] = "Review below-threshold measurements for meaningful text and any applicable logo, decorative or incidental-text exceptions. Also review all unmeasured text/graphics. Report confirmed problems; repair source colors and process a separate PDF. This tool does not silently recolor pages."
        elif item["id"] == "metadata-meaning":
            item["evidence"] = previous.get("language-correctness", {}).get("evidence", {})
        elif item["id"] == "reading-order":
            item["evidence"] = {name: previous.get(name, {}).get("evidence", {}) for name in ALLY_SCREENS[:4]}
    blockers = [item for item in results if item["blocking"] and item["status"] not in ("pass", "not-applicable")]
    status = "error" if any(item["status"] == "error" for item in blockers) else "fail" if blockers else "pass"
    required = list(BLOCKING) + [item["id"] for item in results if item["blocking"] and item["id"] not in BLOCKING]
    return {"profile": PROFILE, "status": status, "checks": results, "blocking_checks": required,
            "blockers": blockers, "manual_queue": manual, "automated_coverage_complete": False,
            "coverage": {"automated": list(BLOCKING) + list(ALLY_SCREENS) + list(ADVISORY_SCREENS), "human_pending": [item["id"] for item in manual],
                         "outside_scope": ["complete WCAG assessment", "general complex-table repair", "arbitrary font restoration"]},
            "claim": "Declared automated profile only; human verification remains pending."}
