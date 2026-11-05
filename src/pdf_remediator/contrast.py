"""Read-only, bounded text contrast measurements; never a document-wide pass.

Only opaque fill text, without rotation/skew, on a uniform background is
measured. A disposable PDFium document hides text in memory for the background
render. The file is never saved or modified. Unsupported paint, overlaps and
render ambiguity remain explicit review work. Ratios follow WCAG 2.2 1.4.3;
semantic exceptions (logos, incidental text, etc.) require human judgment.
"""
from __future__ import annotations

from ctypes import c_uint
import math
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as raw

from .process import cancelled

VERSION = "bounded-text-contrast-1.0"
MAX_PAGES = 100
MAX_OBJECTS_PER_PAGE = 2000
MAX_PIXELS_PER_PAGE = 8_000_000
MAX_SAMPLE_PIXELS = 1_000_000
MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_DECLARED_CONTENT_BYTES = 2 * 1024 * 1024
MAX_CONTENT_STREAMS_PER_PAGE = 256
MAX_RESOURCE_ENTRIES = 256
MAX_MEASUREMENTS = 2000
SCALE = 2
LIMITATIONS = [
    "Measured digital text only; images of text, outlined text and graphics are not assessed.",
    "Pattern/image/shading/Form paint, transparency, clipping, rotation, ambiguous backgrounds and overlaps require review.",
    "Measurements are rendered device RGB; color management and semantic WCAG exceptions require review.",
    "A passing measurement is not an LMS checker result, complete contrast assessment or human verification.",
    "PDFium page loading/decoding occurs before object limits; engine-level resource use is not bounded by these counters. Encoded stream lengths do not bound decompressed size.",
]
FIX = ("Edit the original authoring document: increase text/background contrast to at least "
       "the recorded threshold, then export a new tagged PDF and reprocess it. If the source "
       "is unavailable, request a corrected accessible replacement. Recoloring changes visible "
       "content and cannot bypass the existing exact visual-fidelity gate.")


def contrast_ratio(foreground, background):
    """WCAG relative-luminance ratio for two 8-bit sRGB triples, unrounded."""
    def luminance(rgb):
        components = [v / 255 for v in rgb]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
                  for v in components]
        return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))
    a, b = sorted((luminance(foreground), luminance(background)))
    return (b + .05) / (a + .05)


def _cancel(cancel):
    if cancelled(cancel):
        raise InterruptedError("Contrast inspection cancelled")


def _overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _page_reasons(page, cancel):
    """Conservative metadata preflight; never decode or parse a content stream.

    Declared encoded lengths only reject obviously oversized/ambiguous input;
    they are not an expansion bound. PDFium subsequently parses the page and
    has no interrupt/resource guarantee supplied by this module.
    """
    reasons = []
    if int(page.obj.get("/Rotate", 0)) % 360:
        reasons.append("rotated-page")
    if float(page.obj.get("/UserUnit", 1)) != 1:
        reasons.append("non-default-user-unit")
    if page.obj.get("/Group"):
        reasons.append("page-transparency-group")
    if page.obj.get("/Annots"):
        reasons.append("annotations-not-assessed")
    resources = page.resources
    for category in ("/ExtGState", "/Pattern", "/Shading", "/XObject", "/ColorSpace"):
        if resources.get(category):
            reasons.append("unsupported-resource-" + category.lstrip("/"))
    fonts = resources.get("/Font", {})
    if len(fonts) > MAX_RESOURCE_ENTRIES:
        reasons.append("font-resource-limit")
    else:
        for font in fonts.values():
            _cancel(cancel)
            if font.get("/Subtype") == pikepdf.Name.Type3:
                reasons.append("type3-font-glyph-paint")
    if any(float(v) != 0 for v in page.cropbox[:2]):
        reasons.append("nonzero-crop-origin")
    contents = page.obj.get("/Contents")
    streams = contents if isinstance(contents, pikepdf.Array) else [contents] if contents is not None else []
    if len(streams) > MAX_CONTENT_STREAMS_PER_PAGE:
        reasons.append("content-stream-count-limit")
    else:
        declared_bytes = 0
        for stream in streams:
            _cancel(cancel)
            if not isinstance(stream, pikepdf.Stream):
                reasons.append("unresolved-content-stream-metadata")
                break
            length = stream.get("/Length")
            if not isinstance(length, int) or length < 0:
                reasons.append("unresolved-content-stream-length")
                break
            declared_bytes += length
            if declared_bytes > MAX_DECLARED_CONTENT_BYTES:
                reasons.append("declared-content-length-limit")
                break
    return sorted(set(reasons))


def _render(page):
    bitmap = page.render(scale=SCALE, draw_annots=False)
    try:
        return bitmap.to_pil().convert("RGB").copy()
    finally:
        bitmap.close()


def _measure_page(page, page_number, cancel, remaining_records):
    """Return evidence; handles belong to this caller's disposable document."""
    records, objects = [], []
    if page.get_rotation():
        return [], ["rotated-page"], 0
    # These guards operate AFTER PDFium page loading and decoding. They bound
    # this Python traversal/render, not the native engine's earlier work.
    count = raw.FPDFPage_CountObjects(page)
    if count < 0 or count > MAX_OBJECTS_PER_PAGE:
        return [], ["page-object-limit"], 0
    if raw.FPDFPage_HasTransparency(page):
        return [], ["page-transparency"], 0
    # max_depth=1 does not descend into Forms; metadata and object guards refuse them.
    for index, obj in enumerate(page.get_objects(max_depth=1)):
        _cancel(cancel)
        if index >= MAX_OBJECTS_PER_PAGE:
            return [], ["page-object-limit"], 0
        if obj.type not in {raw.FPDF_PAGEOBJ_TEXT, raw.FPDF_PAGEOBJ_PATH}:
            return [], ["unsupported-page-object-type"], 0
        if raw.FPDFPageObj_HasTransparency(obj):
            return [], ["transparent-or-blended-page-object"], 0
        clip = raw.FPDFPageObj_GetClipPath(obj)
        # A valid page object's empty clip state also returns -1 (HasRef=false)
        # in PDFium. Positive path counts identify explicit path clipping.
        # Text clipping is separately refused through the page-wide mode guard.
        if clip and raw.FPDFClipPath_CountPaths(clip) > 0:
            return [], ["clipped-page-object"], 0
        if obj.type == raw.FPDF_PAGEOBJ_TEXT and raw.FPDFTextObj_GetTextRenderMode(obj) != raw.FPDF_TEXTRENDERMODE_FILL:
            return [], ["non-fill-text-mode"], 0
        objects.append((obj, obj.get_bounds()))
    texts = [(index, obj, bounds) for index, (obj, bounds) in enumerate(objects)
             if obj.type == raw.FPDF_PAGEOBJ_TEXT]
    if not texts:
        return [], ["no-digital-text-objects"], 0
    width, height = page.get_size()
    if (not all(math.isfinite(v) and v > 0 for v in (width, height))
            or math.ceil(width * SCALE) * math.ceil(height * SCALE) > MAX_PIXELS_PER_PAGE):
        return [], ["page-render-size-limit"], len(texts)
    actual = _render(page)
    background = None
    try:
        for _, obj, _ in texts:
            _cancel(cancel)
            if not raw.FPDFPageObj_SetIsActive(obj, False):
                return [], ["background-text-hiding-failed"], len(texts)
        _cancel(cancel)
        background = _render(page)
        for index, obj, bounds in texts:
            _cancel(cancel)
            if len(records) >= remaining_records:
                return records, ["document-measurement-record-limit"], len(texts)
            result = {"page": page_number, "object_index": index,
                      "bounds": list(bounds), "status": "needs-review"}
            records.append(result)
            reason = None
            matrix = obj.get_matrix()
            if not all(math.isfinite(v) for v in (*bounds, matrix.a, matrix.b, matrix.c, matrix.d)):
                reason = "non-finite-text-geometry"
            elif abs(matrix.b) > 1e-6 or abs(matrix.c) > 1e-6 or matrix.a <= 0 or matrix.d <= 0:
                reason = "rotated-skewed-or-reflected-text"
            elif raw.FPDFTextObj_GetTextRenderMode(obj) != raw.FPDF_TEXTRENDERMODE_FILL:
                reason = "non-fill-text-render-mode"
            elif raw.FPDFPageObj_HasTransparency(obj):
                reason = "transparent-or-blended-text"
            elif any(other != index and _overlaps(bounds, other_bounds)
                     and (other_obj.type == raw.FPDF_PAGEOBJ_TEXT or other > index)
                     for other, (other_obj, other_bounds) in enumerate(objects)):
                reason = "overlapping-text-or-later-paint"
            rgba = [c_uint() for _ in range(4)]
            if not reason and (not raw.FPDFPageObj_GetFillColor(obj, *rgba) or rgba[3].value != 255):
                reason = "unknown-or-transparent-fill"
            left, bottom, right, top = bounds
            box = (math.floor(left * SCALE), math.floor((height - top) * SCALE),
                   math.ceil(right * SCALE), math.ceil((height - bottom) * SCALE)) if not reason else None
            if not reason and (box[0] < 0 or box[1] < 0 or box[2] > actual.width or box[3] > actual.height
                               or box[2] <= box[0] or box[3] <= box[1]):
                reason = "text-outside-render-bounds"
            if not reason and (box[2] - box[0]) * (box[3] - box[1]) > MAX_SAMPLE_PIXELS:
                reason = "text-sample-size-limit"
            if reason:
                result["reason"] = reason
                continue
            crop = background.crop(box)
            try:
                colors = crop.getcolors(maxcolors=1)
            finally:
                crop.close()
            if not colors or len(colors) != 1:
                result["reason"] = "nonuniform-background"
                continue
            fg, bg = tuple(value.value for value in rgba[:3]), colors[0][1]
            visible = actual.crop(box)
            try:
                # Reject hidden/occluded/unresolved render paint rather than assuming
                # that a foreground specified in a stream actually reaches the page.
                matches = any(all(abs(a - b) <= 2 for a, b in zip(pixel, fg))
                              for pixel in visible.get_flattened_data())
            finally:
                visible.close()
            if not matches:
                result["reason"] = "foreground-not-confirmed-in-render"
                continue
            size = obj.get_font_size() * abs(matrix.d)
            font = obj.get_font()
            weight = font.get_weight()
            font_name = font.get_base_name()
            # PDFium may report a zero weight for the built-in Standard 14.
            # Their exact standardized names identify the known bold faces;
            # arbitrary font-name substrings are not evidence of boldness.
            if weight <= 0 and not font.is_embedded and font_name in {
                    "Helvetica-Bold", "Helvetica-BoldOblique", "Times-Bold",
                    "Times-BoldItalic", "Courier-Bold", "Courier-BoldOblique"}:
                weight = 700
            elif weight <= 0 and not font.is_embedded and font_name in {
                    "Helvetica", "Helvetica-Oblique", "Times-Roman", "Times-Italic",
                    "Courier", "Courier-Oblique", "Symbol", "ZapfDingbats"}:
                weight = 400
            large = size >= 18 or (size >= 14 and weight >= 700)
            threshold = 3.0 if large else 4.5
            ratio = contrast_ratio(fg, bg)
            uncertain_bold = 14 <= size < 18 and weight <= 0 and 3 <= ratio < 4.5
            result.update({"status": "needs-review" if uncertain_bold else "pass" if ratio >= threshold else "fail",
                           "foreground_rgb": list(fg), "background_rgb": list(bg),
                           "ratio": ratio, "minimum_ratio": threshold,
                           "effective_font_size_pt": size, "font_weight": weight,
                           "font_base_name": font_name,
                           "large_text": large,
                           "fix": FIX if ratio < threshold else None})
            if uncertain_bold:
                result["reason"] = "font-bold-weight-unresolved"
            if result["status"] == "fail":
                # Advice for a reviewed source edit only. Never recolor this
                # PDF, exempt a semantic category, or weaken visual fidelity.
                suggested = max(((0, 0, 0), (255, 255, 255)),
                                key=lambda color: contrast_ratio(color, bg))
                result["source_edit_suggestion"] = {
                    "suggested_foreground_rgb": list(suggested),
                    "suggested_ratio": contrast_ratio(suggested, bg),
                    "minimum_ratio": threshold,
                    "review_required": True,
                    "action": "source-edit-and-reprocess",
                    "review_note": "Confirm this text needs contrast repair in its context; logos or incidental text may be exceptions. Edit the authoring source and reprocess a new PDF.",
                }
        return records, [], len(texts)
    finally:
        actual.close()
        if background is not None:
            background.close()


def inspect_contrast(pdf_path, cancel_event=None):
    """Return JSON-safe measurements without changing the input or claiming a global pass.

    Cancellation raises InterruptedError so callers cannot mistake it for a
    completed assessment. Other failures are explicit error results. Limits
    produce review evidence, never an omitted or passing scope.
    """
    result = {"version": VERSION, "status": "needs-review", "measurements": [],
              "unmeasured_pages": [], "page_count": 0, "measured_text_objects": 0,
              "failed_text_objects": 0, "unknown_text_objects": 0,
              "scope": "Opaque, axis-aligned fill text on uniform rendered backgrounds",
              "limitations": list(LIMITATIONS), "repair_guidance": FIX,
              "complete_document_coverage": False}
    try:
        _cancel(cancel_event)
        if Path(pdf_path).stat().st_size > MAX_INPUT_BYTES:
            result["unmeasured_pages"].append({"reasons": ["input-size-limit"]})
            return result
        with pikepdf.open(Path(pdf_path)) as syntax, pdfium.PdfDocument(str(pdf_path)) as document:
            result["page_count"] = len(syntax.pages)
            if len(document) != len(syntax.pages):
                raise ValueError("PDF engines disagree on page count")
            for index, syntax_page in enumerate(syntax.pages):
                _cancel(cancel_event)
                if len(result["measurements"]) >= MAX_MEASUREMENTS:
                    result["unmeasured_pages"].append({"from_page": index + 1,
                        "through_page": len(syntax.pages), "reasons": ["document-measurement-record-limit"]})
                    break
                if index >= MAX_PAGES:
                    result["unmeasured_pages"].append({"from_page": index + 1,
                        "through_page": len(syntax.pages), "reasons": ["page-count-limit"]})
                    break
                reasons = _page_reasons(syntax_page, cancel_event)
                if reasons:
                    result["unmeasured_pages"].append({"page": index + 1, "reasons": reasons})
                    continue
                page = document[index]
                try:
                    records, reasons, _ = _measure_page(page, index + 1, cancel_event,
                        MAX_MEASUREMENTS - len(result["measurements"]))
                finally:
                    page.close()
                result["measurements"].extend(records)
                if reasons:
                    if "document-measurement-record-limit" in reasons:
                        result["unmeasured_pages"].append({"from_page": index + 1,
                            "through_page": len(syntax.pages), "reasons": reasons})
                        break
                    result["unmeasured_pages"].append({"page": index + 1, "reasons": reasons})
            result["measured_text_objects"] = sum(r["status"] in {"pass", "fail"} for r in result["measurements"])
            result["failed_text_objects"] = sum(r["status"] == "fail" for r in result["measurements"])
            result["unknown_text_objects"] = sum(r["status"] == "needs-review" for r in result["measurements"])
            if result["failed_text_objects"]:
                result["status"] = "fail"
    except InterruptedError:
        raise
    except Exception as exc:
        result["status"] = "error"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    return result
