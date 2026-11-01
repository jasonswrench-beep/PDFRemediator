"""Authored PDF contrast controls; no external corpus, AI/OCR or native tools."""
from __future__ import annotations

import hashlib
import json
import threading

import pikepdf
from PIL import Image
import pytest
from reportlab.pdfgen import canvas

from pdf_remediator import contrast


def _pdf(tmp_path, paint, name="control.pdf"):
    path = tmp_path / name
    document = canvas.Canvas(str(path), pagesize=(300, 200), invariant=1)
    paint(document)
    document.save()
    return path


def _text(document, gray=0, size=12, font="Helvetica"):
    document.setFont(font, size)
    document.setFillGray(gray)
    document.drawString(30, 100, "Authored contrast control")


def test_ratio_matches_wcag_luminance_without_rounding():
    assert contrast.contrast_ratio((0, 0, 0), (255, 255, 255)) == 21
    assert contrast.contrast_ratio((100, 100, 100), (100, 100, 100)) == 1
    assert contrast.contrast_ratio((119, 119, 119), (255, 255, 255)) < 4.5
    assert contrast.contrast_ratio((118, 118, 118), (255, 255, 255)) > 4.5


@pytest.mark.parametrize("gray,status", [(0, "pass"), (.75, "fail"), (1, "fail")])
def test_opaque_text_measures_real_render_background_and_preserves_pdf(tmp_path, gray, status):
    path = _pdf(tmp_path, lambda document: _text(document, gray))
    before = path.read_bytes()
    result = contrast.inspect_contrast(path)
    assert "error" not in result, result
    assert result["measured_text_objects"] == 1
    measurement = result["measurements"][0]
    assert measurement["status"] == status
    assert measurement["background_rgb"] == [255, 255, 255]
    assert result["status"] == ("fail" if status == "fail" else "needs-review")
    assert result["complete_document_coverage"] is False
    if status == "fail":
        assert "authoring document" in measurement["fix"]
        assert "fidelity" in measurement["fix"]
        assert measurement["source_edit_suggestion"]["review_required"] is True
    else:
        assert "source_edit_suggestion" not in measurement
    json.dumps(result, allow_nan=False)
    assert path.read_bytes() == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(before).hexdigest()


@pytest.mark.parametrize("size,font,minimum,status", [
    (12, "Helvetica", 4.5, "fail"),
    (18, "Helvetica", 3, "pass"),
    (14, "Helvetica-Bold", 3, "pass"),
    (14, "Helvetica", 4.5, "fail"),
])
def test_large_text_size_and_bold_thresholds(tmp_path, size, font, minimum, status):
    path = _pdf(tmp_path, lambda document: _text(document, .55, size, font))
    result = contrast.inspect_contrast(path)
    assert "error" not in result, result
    measurement = result["measurements"][0]
    assert measurement["minimum_ratio"] == minimum
    assert measurement["status"] == status


def test_actual_uniform_colored_background_is_measured(tmp_path):
    def paint(document):
        document.setFillColorRGB(.2, .2, .2)
        document.rect(0, 0, 300, 200, fill=1, stroke=0)
        _text(document, 1)
    result = contrast.inspect_contrast(_pdf(tmp_path, paint))
    measurement = result["measurements"][0]
    assert measurement["status"] == "pass", result
    assert measurement["background_rgb"] == [51, 51, 51]
    assert measurement["ratio"] > 12


@pytest.mark.parametrize("background,expected", [
    ((.08, .25, .45), [255, 255, 255]),
    ((.85, .9, .75), [0, 0, 0]),
])
def test_low_contrast_colored_background_gets_reviewed_source_edit_suggestion_without_pdf_changes(tmp_path, background, expected):
    def paint(document):
        document.setFillColorRGB(*background)
        document.rect(0, 0, 300, 200, fill=1, stroke=0)
        document.setFont("Helvetica", 12)
        # Identical text and background colors intentionally produce a real
        # 1:1 failure, independent of an assumed default white background.
        document.drawString(30, 100, "Authored color repair control")
    path = _pdf(tmp_path, paint)
    original = path.read_bytes()
    result = contrast.inspect_contrast(path)
    measurement = result["measurements"][0]
    assert measurement["status"] == "fail" and measurement["ratio"] == 1
    suggestion = measurement["source_edit_suggestion"]
    assert suggestion["suggested_foreground_rgb"] == expected
    assert suggestion["suggested_ratio"] == contrast.contrast_ratio(expected, measurement["background_rgb"])
    assert suggestion["suggested_ratio"] >= measurement["minimum_ratio"]
    alternative = [255 - component for component in expected]
    assert suggestion["suggested_ratio"] > contrast.contrast_ratio(alternative, measurement["background_rgb"])
    assert suggestion["review_required"] is True
    assert suggestion["action"] == "source-edit-and-reprocess"
    assert "logos or incidental text may be exceptions" in suggestion["review_note"]
    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.pdf")) == [path]


def test_background_changed_under_half_the_text_is_unmeasured(tmp_path):
    def paint(document):
        document.setFillGray(.5)
        document.rect(30, 90, 40, 40, fill=1, stroke=0)
        _text(document)
    result = contrast.inspect_contrast(_pdf(tmp_path, paint))
    assert result["status"] == "needs-review"
    assert result["measurements"][0]["reason"] == "nonuniform-background"
    assert "source_edit_suggestion" not in result["measurements"][0]
    assert result["measured_text_objects"] == 0


@pytest.mark.parametrize("mode", ["alpha", "image", "gradient", "form", "clipping", "rotation"])
def test_unsupported_paint_is_explicit_and_not_a_global_pass(tmp_path, mode):
    def paint(document):
        if mode == "alpha":
            document.setFillAlpha(.3)
        if mode == "image":
            image = tmp_path / "authored.png"
            Image.new("RGB", (4, 4), "white").save(image)
            document.drawImage(str(image), 20, 80, width=180, height=40)
        if mode == "gradient":
            document.linearGradient(20, 80, 200, 120, [(0, 0, 0), (1, 1, 1)])
        if mode == "form":
            document.beginForm("form")
            _text(document)
            document.endForm()
            document.doForm("form")
        if mode == "clipping":
            clipping = document.beginPath()
            # An effective clip through the glyphs; PDFium optimizes away a
            # full-page rectangle that has no effect on the text object's paint.
            clipping.rect(30, 100, 40, 5)
            document.clipPath(clipping, stroke=0)
        if mode == "rotation":
            document.setPageRotation(90)
        _text(document)
    path = _pdf(tmp_path, paint)
    result = contrast.inspect_contrast(path)
    assert "error" not in result, result
    assert result["status"] == "needs-review"
    assert result["measured_text_objects"] == 0
    assert result["unmeasured_pages"][0]["reasons"]


@pytest.mark.parametrize("mode", ["text-overlap", "later-cover", "rotated-run"])
def test_overlaps_occlusion_and_transformed_runs_are_not_assumed_measurable(tmp_path, mode):
    def paint(document):
        if mode == "rotated-run":
            document.translate(40, 80)
            document.rotate(20)
            document.setFont("Helvetica", 12)
            document.drawString(0, 0, "Rotated control")
            return
        _text(document)
        if mode == "text-overlap":
            _text(document, .7)
        else:
            document.setFillGray(1)
            document.rect(20, 90, 200, 40, fill=1, stroke=0)
    result = contrast.inspect_contrast(_pdf(tmp_path, paint))
    assert "error" not in result, result
    assert result["status"] == "needs-review"
    assert result["measured_text_objects"] == 0
    assert all(record["reason"] in {"overlapping-text-or-later-paint", "rotated-skewed-or-reflected-text"}
               for record in result["measurements"])


def test_no_text_and_explicit_bounds_are_not_successful_measurements(tmp_path, monkeypatch):
    blank = _pdf(tmp_path, lambda document: document.showPage())
    result = contrast.inspect_contrast(blank)
    assert result["status"] == "needs-review"
    assert result["unmeasured_pages"][0]["reasons"] == ["no-digital-text-objects"]
    text = _pdf(tmp_path, _text, "text.pdf")
    monkeypatch.setattr(contrast, "MAX_PIXELS_PER_PAGE", 100)
    result = contrast.inspect_contrast(text)
    assert result["unmeasured_pages"][0]["reasons"] == ["page-render-size-limit"]


def test_nonzero_crop_origin_refused_instead_of_sampling_wrong_coordinates(tmp_path):
    path = _pdf(tmp_path, _text)
    cropped = tmp_path / "cropped.pdf"
    with pikepdf.open(path) as pdf:
        pdf.pages[0].cropbox = [10, 10, 290, 190]
        pdf.save(cropped)
    result = contrast.inspect_contrast(cropped)
    assert result["measured_text_objects"] == 0
    assert "nonzero-crop-origin" in result["unmeasured_pages"][0]["reasons"]


def test_cancel_raises_and_bad_input_is_an_error(tmp_path):
    event = threading.Event()
    event.set()
    with pytest.raises(InterruptedError, match="cancelled"):
        contrast.inspect_contrast(tmp_path / "never-opened.pdf", event)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a PDF")
    result = contrast.inspect_contrast(broken)
    assert result["status"] == "error"
    assert result["error"]


def test_scaled_text_uses_effective_vertical_point_size(tmp_path):
    def paint(document):
        document.scale(.5, .5)
        _text(document, .55, 24)
    result = contrast.inspect_contrast(_pdf(tmp_path, paint))
    measurement = result["measurements"][0]
    assert measurement["effective_font_size_pt"] == 12
    assert measurement["minimum_ratio"] == 4.5
    assert measurement["status"] == "fail"


@pytest.mark.parametrize("limit,reason", [
    ("MAX_PAGES", "page-count-limit"),
    ("MAX_OBJECTS_PER_PAGE", "page-object-limit"),
    ("MAX_INPUT_BYTES", "input-size-limit"),
])
def test_limits_leave_explicit_unmeasured_scope(tmp_path, monkeypatch, limit, reason):
    path = _pdf(tmp_path, _text)
    monkeypatch.setattr(contrast, limit, 0)
    result = contrast.inspect_contrast(path)
    assert result["status"] == "needs-review"
    assert result["measured_text_objects"] == 0
    assert reason in result["unmeasured_pages"][0]["reasons"]


def test_cancellation_during_paint_traversal_is_not_a_partial_success(tmp_path):
    def paint(document):
        for index in range(30):
            document.drawString(20, index * 5, "Bounded cancellation control")
    path = _pdf(tmp_path, paint)
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 10
    before = path.read_bytes()
    with pytest.raises(InterruptedError):
        contrast.inspect_contrast(path, cancel)
    assert calls >= 10
    assert path.read_bytes() == before


def test_metadata_preflight_does_not_eagerly_decode_or_parse_content(tmp_path, monkeypatch):
    path = _pdf(tmp_path, _text)
    def forbidden(*args, **kwargs):
        pytest.fail("Contrast preflight must not invoke pikepdf's eager content parser")
    monkeypatch.setattr(pikepdf, "parse_content_stream", forbidden)
    result = contrast.inspect_contrast(path)
    assert result["measured_text_objects"] == 1, result
    assert result["measurements"][0]["status"] == "pass"
    assert any("loading/decoding occurs before object limits" in item for item in result["limitations"])


def test_encoded_length_metadata_abstains_before_pdfium_page_loading(tmp_path, monkeypatch):
    path = _pdf(tmp_path, _text)
    monkeypatch.setattr(contrast, "MAX_DECLARED_CONTENT_BYTES", 1)
    def forbidden(*args, **kwargs):
        pytest.fail("Oversized declared page content must be rejected before PDFium page loading")
    monkeypatch.setattr(contrast.pdfium.PdfDocument, "__getitem__", forbidden)
    result = contrast.inspect_contrast(path)
    assert result["measured_text_objects"] == 0
    assert "declared-content-length-limit" in result["unmeasured_pages"][0]["reasons"]


@pytest.mark.parametrize("same_page", [False, True])
def test_document_record_limit_preserves_findings_and_explicit_remaining_scope(tmp_path, monkeypatch, same_page):
    def paint(document):
        _text(document, .75)
        if not same_page:
            document.showPage()
        document.setFont("Helvetica", 12)
        document.drawString(20, 50, "Unmeasured later control")
    path = _pdf(tmp_path, paint)
    monkeypatch.setattr(contrast, "MAX_MEASUREMENTS", 1)
    result = contrast.inspect_contrast(path)
    assert result["status"] == "fail"
    assert len(result["measurements"]) == 1
    assert result["measurements"][0]["status"] == "fail"
    assert result["failed_text_objects"] == 1
    assert result["complete_document_coverage"] is False
    assert result["unmeasured_pages"][0] == {
        "from_page": 1 if same_page else 2,
        "through_page": 1 if same_page else 2,
        "reasons": ["document-measurement-record-limit"],
    }
