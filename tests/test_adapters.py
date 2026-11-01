"""Production adapters reject known false passes and preserve bounded evidence."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

import pikepdf
import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont

from pdf_remediator.checks import assess
from pdf_remediator.engines import tag
from pdf_remediator.inspection import compare_fidelity, inspect_pdf
from pdf_remediator.ocr import _ocr_preservation, run_ocr
from pdf_remediator.process import run
from pdf_remediator.validation import parse_xml_report, validate_pdf

from test_pipeline import tagged_control


@pytest.fixture(scope="session")
def adapter_corpus(tmp_path_factory, tagged_control):
    """Original deterministic controls; no historical/native output is read."""
    directory = tmp_path_factory.mktemp("adapter-corpus")
    spec = importlib.util.spec_from_file_location("adapter_synthetic_corpus",
        Path(__file__).resolve().parents[1] / "eval/build_corpus.py")
    corpus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(corpus)
    corpus.register_fonts(directory)
    corpus.tag_variants(tagged_control, directory / "phantom-tree.pdf", directory / "incomplete-tags.pdf")
    corpus.mis_mapping(tagged_control, directory / "mis-mapped-font.pdf")
    corpus.structured(directory / "structured-chapter.pdf", corpus.ImageReader(corpus.image_asset()))
    corpus.scans(directory / "mixed-same-page.pdf", mixed=True)
    scan = directory / "scan-only.pdf"
    corpus.scans(scan)
    with pikepdf.open(scan) as pdf:
        page = pdf.pages[0]
        page.Contents = pdf.make_stream(b"/Figure <</MCID 0>> BDC\n" + page.Contents.read_bytes() + b"\nEMC")
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        element = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.Figure, P=tree, Pg=page.obj, K=0))
        tree.K = pikepdf.Array([element])
        tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([element])])))
        page.StructParents = 0
        pdf.Root.StructTreeRoot = tree
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = "en-US"
        pdf.save(directory / "scan-only_tagged.pdf", deterministic_id=True)
    return directory


def baseline(control):
    return inspect_pdf(control)


def test_good_control_has_declared_automated_pass_and_pending_human_work(tagged_control):
    result = assess(baseline(tagged_control))
    assert result["status"] == "pass"
    assert result["automated_coverage_complete"] is False
    assert {item["id"] for item in result["manual_queue"]} >= {"reading-order", "contrast", "font-characters"}
    contrast = next(item for item in result["checks"] if item["name"] == "contrast")
    assert contrast["status"] == "needs-review"
    assert contrast["blocking"] is False
    assert contrast["evidence"]["measured_text_objects"] > 0
    assert contrast["evidence"]["failed_text_objects"] == 0
    assert contrast["evidence"]["complete_document_coverage"] is False
    assert next(item for item in result["manual_queue"] if item["id"] == "contrast")["required"] is True


@pytest.mark.parametrize("title", ["", "Untitled Document", "document.pdf", "1234", "Title"])
def test_generic_title_is_not_a_meaningful_metadata_pass(title, tagged_control):
    report = baseline(tagged_control)
    report["metadata"]["title"] = title
    assert "metadata" in {item["id"] for item in assess(report)["blockers"]}


@pytest.mark.parametrize("alt", ["", "Image1", "Figure_23", "placeholder", "diagram.png"])
def test_figure_placeholders_remain_blockers(alt, tagged_control):
    report = baseline(tagged_control)
    report["structure"]["figures"] = [{"element": "known-figure", "page": 1, "alt": alt}]
    assert "figure-alternatives" in {item["id"] for item in assess(report)["blockers"]}


def test_plausible_figure_description_remains_human_work(tagged_control):
    report = baseline(tagged_control)
    report["structure"]["figures"] = [{"element": "known-figure", "page": 1, "alt": "Plot showing the two garden beds beside the north wall."}]
    result = assess(report)
    assert result["status"] == "pass"
    assert "figure-meaning" in {item["id"] for item in result["manual_queue"]}


def test_a_scanned_page_with_valid_figure_alt_still_needs_ocr(adapter_corpus):
    path = adapter_corpus / "scan-only_tagged.pdf"
    report = inspect_pdf(path)
    assert report["pages"][0]["class"] == "scanned"
    report["structure"]["figures"][0]["alt"] = "The page contains a scanned reading exercise."
    result = assess(report)
    assert "scan-text-layer" in {item["id"] for item in result["blockers"]}


def test_known_uncovered_and_phantom_controls_do_not_pass(adapter_corpus):
    for file in ("incomplete-tags.pdf", "phantom-tree.pdf"):
        result = assess(inspect_pdf(adapter_corpus / file))
        assert result["status"] != "pass"
        assert {item["id"] for item in result["blockers"]} & {"content-linkage", "content-coverage"}


@pytest.mark.parametrize("variant,expected", [
    ("direct-link", "pass"), ("reference-owner", "fail"),
    ("mapped-link", "pass"), ("mapped-link-chain", "pass"),
    ("mapped-reference", "fail"), ("rolemap-cycle", "fail"),
    ("missing-objr", "fail"), ("missing-parent", "fail"),
    ("wrong-parent", "fail"), ("multiple-owners", "fail"),
])
def test_link_annotations_require_effective_link_owner_and_existing_backlinks(tmp_path, variant, expected):
    """Real authored PDFs isolate semantic ownership from valid MCID linkage.

    No external validator, browser, network or user PDF participates. These
    checks do not assert meaningful link text or general PDF accessibility.
    """
    path = tmp_path / (variant + ".pdf")
    with pikepdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(200, 200))
        page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)))
        page.obj.Contents = pdf.make_stream(b"/Link <</MCID 0>> BDC BT /F1 12 Tf 20 150 Td (Open chapter) Tj ET EMC")
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=tree))
        role = "/Reference" if variant == "reference-owner" else "/CustomLink" if variant.startswith("mapped-") or variant == "rolemap-cycle" else "/Link"
        owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name(role),
            P=document, Pg=page.obj, K=pikepdf.Array([0])))
        annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([20, 145, 100, 165]), Contents="Jump to chapter", StructParent=1,
            Dest=pikepdf.Array([page.obj, pikepdf.Name.Fit])))
        page.obj.Annots = pikepdf.Array([annotation])
        if variant != "missing-objr":
            owner.K.append(pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Pg=page.obj, Obj=annotation))
        children = pikepdf.Array([owner])
        if variant == "multiple-owners":
            second = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Link,
                P=document, Pg=page.obj, K=pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Pg=page.obj, Obj=annotation)))
            children.append(second)
        document.K = children
        tree.K = pikepdf.Array([document])
        numbers = pikepdf.Array([0, pikepdf.Array([owner])])
        if variant != "missing-parent":
            numbers.extend([1, document if variant == "wrong-parent" else owner])
        tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=numbers))
        if variant in {"mapped-link", "mapped-reference", "mapped-link-chain", "rolemap-cycle"}:
            target = "/Reference" if variant == "mapped-reference" else "/OtherLink" if variant in {"mapped-link-chain", "rolemap-cycle"} else "/Link"
            tree.RoleMap = pikepdf.Dictionary(CustomLink=pikepdf.Name(target))
            if variant in {"mapped-link-chain", "rolemap-cycle"}:
                tree.RoleMap.OtherLink = pikepdf.Name.CustomLink if variant == "rolemap-cycle" else pikepdf.Name.Link
        page.obj.StructParents = 0
        pdf.Root.StructTreeRoot = tree
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = "en-US"
        pdf.save(path, deterministic_id=True)
    before = path.read_bytes()
    report = inspect_pdf(path)
    assert "error" not in report
    linkage = next(item for item in report["checks"] if item["id"] == "link-structure")
    assert linkage["status"] == expected
    assert bool(linkage["evidence"]["unlinked_links"]) == (expected == "fail")
    if variant in {"direct-link", "reference-owner", "mapped-link", "mapped-link-chain", "mapped-reference"}:
        assert all(next(item for item in report["checks"] if item["id"] == key)["status"] == "pass"
                   for key in ("content-linkage", "content-coverage")), "Wrong link role is independent of otherwise intact content linkage."
    assert path.read_bytes() == before, "Inspection must not repair or change the authored PDF."
    if expected == "fail":
        assert "link-structure" in {item["id"] for item in assess(report)["blockers"]}


def table_report(tagged_control, *, scopes=True, headers=False, broken=False, span=1):
    report = baseline(tagged_control)
    struct = report["structure"]
    struct["tag_counts"]["/Table"] = 1
    struct["tables"] = [{"element": "table", "page": 1}]
    struct["table_cells"] = [
        {"element": "header", "table": "table", "role": "/TH", "page": 1,
         "scope": ["/Column"] if scopes else [], "headers": [], "id": "name",
         "row_spans": [span], "col_spans": []},
        {"element": "data", "table": "table", "role": "/TD", "page": 1,
         "scope": [], "headers": ["wrong" if broken else "name"] if headers else [],
         "id": "", "row_spans": [], "col_spans": []}]
    return report


def test_scope_and_headers_id_are_independent_supported_mechanisms(tagged_control):
    assert assess(table_report(tagged_control, scopes=True))["status"] == "pass"
    assert assess(table_report(tagged_control, scopes=False, headers=True))["status"] == "pass"
    assert assess(table_report(tagged_control, scopes=True, span=2))["status"] == "pass"
    for report in (table_report(tagged_control, scopes=False), table_report(tagged_control, headers=True, broken=True), table_report(tagged_control, span=0)):
        assert "table-header-associations" in {item["id"] for item in assess(report)["blockers"]}


def test_unsupported_features_remain_blockers(tagged_control):
    for flag in ("signed_or_signature_fields", "forms", "attachments", "javascript", "optional_content", "equation_tags"):
        report = baseline(tagged_control)
        report["features"][flag] = True
        assert "unsupported-features" in {item["id"] for item in assess(report)["blockers"]}


def test_mapping_screen_does_not_claim_used_code_coverage(tagged_control):
    report = baseline(tagged_control)
    assert all(f["glyph_coverage_status"] == "not-tested" for f in report["fonts"])
    result = assess(report)
    check = next(item for item in result["checks"] if item["id"] == "font-mapping-shape")
    assert check["status"] == "pass"
    assert any("not used-code" in item for item in check["limitations"])


def test_wrong_unicode_mapping_is_detected_against_authoritative_reference(tagged_control, adapter_corpus):
    result = compare_fidelity(tagged_control, adapter_corpus / "mis-mapped-font.pdf")
    assert result["status"] == "fail"
    assert result["text"]["multiset_status"] == "fail"


def test_self_fidelity_compares_all_pages(adapter_corpus):
    source = adapter_corpus / "structured-chapter.pdf"
    result = compare_fidelity(source, source)
    assert result["status"] == "pass"
    assert len(result["pages"]) == 4
    assert all(p["changed_pixel_fraction"] == 0 for p in result["pages"])


def test_inspection_and_fidelity_honor_precancelled_event(tagged_control):
    cancel = threading.Event()
    cancel.set()
    before = tagged_control.read_bytes()
    with pytest.raises(InterruptedError, match="PDF inspection cancelled"):
        inspect_pdf(tagged_control, cancel)
    assert compare_fidelity(tagged_control, tagged_control, cancel=cancel)["status"] == "error"
    assert tagged_control.read_bytes() == before


def test_local_process_timeout_and_cancellation_keep_logs(tmp_path):
    result = run([sys.executable, "-c", "import time; print('started',flush=True); time.sleep(30)"], tmp_path / "timeout", timeout_seconds=.3)
    assert result["status"] == "timeout"
    assert result["returncode"] is not None
    assert Path(result["stdout"]).is_file()
    cancel = threading.Event()
    timer = threading.Timer(.25, cancel.set)
    timer.start()
    try:
        result = run([sys.executable, "-c", "import time;time.sleep(30)"], tmp_path / "cancel", cancel=cancel)
    finally:
        timer.cancel()
    assert result["status"] == "cancelled"
    assert result["seconds"] < 5


def test_process_cannot_overwrite_prior_evidence(tmp_path):
    run([sys.executable, "-c", "print('one')"], tmp_path)
    with pytest.raises(FileExistsError):
        run([sys.executable, "-c", "print('two')"], tmp_path)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), float("-inf"), True, False])
def test_process_rejects_nonfinite_or_boolean_time_budgets_before_starting(tmp_path, timeout):
    directory = tmp_path / "invalid-budget"
    with pytest.raises(ValueError):
        run([sys.executable, "-c", "raise RuntimeError('must never execute')"], directory, timeout_seconds=timeout)
    assert not directory.exists()


@pytest.mark.parametrize("memory", [float("nan"), float("inf"), float("-inf"), True, False, float(64 * 1024**2)])
def test_process_requires_an_actual_integer_memory_budget_before_starting(tmp_path, memory):
    directory = tmp_path / "invalid-budget"
    with pytest.raises(ValueError):
        run([sys.executable, "-c", "raise RuntimeError('must never execute')"], directory, memory_limit_bytes=memory)
    assert not directory.exists()


def test_tagging_refuses_unpinned_or_missing_jar_before_running(tmp_path, tagged_control):
    result = tag(tagged_control, tmp_path / "output.pdf", {"odl_jar": tmp_path / "absent.jar"}, tmp_path / "tag")
    assert result["status"] == "error"
    assert not (tmp_path / "output.pdf").exists()


def test_ocr_refuses_unproven_mode_and_mixed_skip_without_output(tmp_path, tagged_control, adapter_corpus):
    with pytest.raises(ValueError):
        run_ocr(tagged_control, tmp_path / "forced.pdf", workdir=tmp_path / "force", mode="force")
    result = run_ocr(adapter_corpus / "mixed-same-page.pdf", tmp_path / "mixed.pdf", workdir=tmp_path / "mixed", mode="skip")
    assert result["status"] == "unsupported"
    assert not (tmp_path / "mixed.pdf").exists()
    result = run_ocr(tagged_control, tmp_path / "tagged.pdf", workdir=tmp_path / "redo", mode="redo")
    assert result["status"] == "unsupported"


def test_ocr_uses_short_project_temporary_root_even_for_deep_work_directory(tmp_path, monkeypatch, tagged_control):
    from pdf_remediator import ocr
    project = tmp_path / "project"
    work = project / "output"
    for index in range(5):
        work /= "deep-output-stage-" + str(index)
    captured = []
    version = tmp_path / "version.txt"
    version.write_text("17.13.0\n", encoding="utf-8")

    def stub_run(command, directory, timeout_seconds, memory_limit_bytes, cancel, env):
        assert list(map(str, command[1:7])) == ["-I", "-B", "-X", "utf8", "-m", "ocrmypdf"]
        captured.append({"directory": Path(directory), "TEMP": env["TEMP"], "TMP": env["TMP"]})
        if "--version" in command:
            return {"status": "completed", "stdout": str(version)}
        return {"status": "failed", "returncode": 1, "scope": "Explicit subprocess stub; no OCR executed"}

    monkeypatch.setattr(ocr, "run", stub_run)
    # This contract isolates temporary-path handling; no OCR runtime is invoked.
    monkeypatch.setattr(ocr, "ocr_availability", lambda settings: {
        "available": True, "message": "Named OCR availability test stub", "runtime_verified": False})
    result = ocr.run_ocr(tagged_control, tmp_path / "output.pdf", {"project_root": project}, workdir=work, mode="skip")
    assert result["status"] == "failed"
    assert len(captured) == 2
    temporary = Path(result["temporary_directory"])
    assert temporary.parent == project / "tmp/ocr"
    assert len(temporary.name) == 12
    assert temporary.is_dir()
    assert all(item["TEMP"] == item["TMP"] == str(temporary) for item in captured)
    assert work not in temporary.parents
    assert len(str(temporary)) < len(str(work))


@pytest.mark.parametrize("missing", ["python", "tesseract", "model", None])
def test_ocr_availability_checks_each_component_without_native_probes(tmp_path, monkeypatch, missing):
    from pdf_remediator import doctor
    python = tmp_path / "private-ocr/python.exe"
    tesseract_dir = tmp_path / "private-tesseract"
    components = {"python": python, "tesseract": tesseract_dir / ("tesseract.exe" if os.name == "nt" else "tesseract"),
                  "model": tesseract_dir / "tessdata/eng.traineddata"}
    for name, path in components.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if name != missing:
            path.write_bytes(b"Named presence-only fixture; never executed")
    monkeypatch.setattr(doctor, "_probe", lambda *a, **kw: pytest.fail("Availability started a native probe"))
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **kw: pytest.fail("Availability spawned a process"))
    result = doctor.ocr_availability({"project_root": tmp_path, "ocr_python": python, "tesseract_dir": tesseract_dir})
    assert result["available"] is (missing is None)
    assert result["runtime_verified"] is False
    assert set(result) == {"available", "message", "runtime_verified"}
    assert str(tmp_path) not in result["message"]
    assert "not installed or configured" in result["message"] if missing else "versions and preservation checks" in result["message"]


def test_missing_ocr_refuses_before_inspection_directories_or_processes(tmp_path, monkeypatch):
    from pdf_remediator import ocr
    source = tmp_path / "original.pdf"
    original = b"%PDF-named-preflight-control; no PDF parser should open it"
    source.write_bytes(original)
    monkeypatch.setattr(ocr, "inspect_pdf", lambda *a, **kw: pytest.fail("Missing runtime reached PDF inspection"))
    monkeypatch.setattr(ocr, "run", lambda *a, **kw: pytest.fail("Missing runtime reached a native process"))
    result = ocr.run_ocr(source, tmp_path / "result.pdf", {
        "project_root": tmp_path, "ocr_python": tmp_path / "not-included/python.exe",
        "tesseract_dir": tmp_path / "not-included"}, workdir=tmp_path / "work", mode="redo")
    assert result["status"] == "unsupported" and "not installed or configured" in result["error"]
    assert "selectable text" in result["error"] and "accessible source" in result["error"]
    assert source.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["original.pdf"]


def test_ocr_added_token_policy_never_forgives_removed_original_text():
    evidence = {"pages": [{"render_status": "pass", "dimensions_status": "pass", "page_boxes_status": "pass",
                           "annotations_status": "pass", "text": {"removed_tokens": 0, "added_tokens": 8}}],
                "checks": [{"name": "page-count", "status": "pass"}]}
    assert _ocr_preservation(evidence)["status"] == "pass"
    evidence["pages"][0]["text"]["removed_tokens"] = 1
    assert _ocr_preservation(evidence)["status"] == "fail"


def test_strict_validator_parser_rejects_wrong_profile_and_truncation(tmp_path):
    source = tmp_path / "synthetic-parser-control.xml"
    source.write_text(
        '<report><buildInformation><releaseDetails id="core" version="1.30.3"/></buildInformation>'
        '<jobs><job><item><name>synthetic-control.pdf</name></item>'
        '<validationReport jobEndStatus="normal" profileName="PDF/UA-1 validation profile" isCompliant="true">'
        '<details passedRules="106" failedRules="0" passedChecks="427" failedChecks="0"/>'
        '</validationReport></job></jobs>'
        '<batchSummary totalJobs="1" failedToParse="0" encrypted="0" outOfMemory="0" veraExceptions="0">'
        '<validationReports compliant="1" nonCompliant="0" failedJobs="0">1</validationReports>'
        '</batchSummary></report>', encoding="utf-8")
    assert parse_xml_report(source)["status"] == "pass"
    value = source.read_text(encoding="utf-8")
    wrong = tmp_path / "wrong.xml"
    wrong.write_text(value.replace("PDF/UA-1 validation profile", "PDF/A-1b validation profile"), encoding="utf-8")
    with pytest.raises(ValueError):
        parse_xml_report(wrong)
    truncated = tmp_path / "truncated.xml"
    truncated.write_text(value[:len(value) // 2], encoding="utf-8")
    with pytest.raises(Exception):
        parse_xml_report(truncated)


def test_validation_missing_executable_is_an_error_not_a_pass(tmp_path, tagged_control):
    result = validate_pdf(tagged_control, tmp_path / "validation", tmp_path / "missing.bat")
    assert result["status"] == "error"
    assert result["execution"]["status"] == "not-run"


def _named_ocr_page_evidence(number):
    return {"page": number, "render_status": "pass", "dimensions_status": "pass",
            "page_boxes_status": "pass", "annotations_status": "pass",
            "text": {"removed_tokens": 0, "added_tokens": 4}}


@pytest.mark.parametrize("page_numbers,expected", [([1], "fail"), ([1, 1], "fail"),
    ([1, 3], "fail"), ([1, 2], "pass")])
def test_ocr_preservation_requires_every_expected_page_once(page_numbers, expected):
    fidelity = {"pages": [_named_ocr_page_evidence(n) for n in page_numbers],
                "checks": [{"id": "page-count", "status": "pass"}]}
    assert _ocr_preservation(fidelity, expected_pages=2)["status"] == expected


@pytest.mark.parametrize("changed", ["render_status", "dimensions_status", "page_boxes_status",
    "annotations_status", "removed_tokens"])
def test_ocr_preservation_rejects_damage_on_a_later_page(changed):
    fidelity = {"pages": [_named_ocr_page_evidence(n) for n in (1, 2)],
                "checks": [{"id": "page-count", "status": "pass"}]}
    if changed == "removed_tokens":
        fidelity["pages"][1]["text"][changed] = 1
    else:
        fidelity["pages"][1][changed] = "fail"
    assert _ocr_preservation(fidelity, expected_pages=2)["status"] == "fail"


def _authored_multiple_image_pages(path, adapter_corpus, tagged_control):
    with pikepdf.new() as pdf, pikepdf.open(adapter_corpus / "scan-only.pdf") as scan, pikepdf.open(tagged_control) as digital:
        pdf.pages.append(scan.pages[0])
        pdf.pages.append(scan.pages[0])
        pdf.pages.append(digital.pages[0])
        pdf.save(path, deterministic_id=True)


@pytest.mark.parametrize("mode", ["skip", "redo"])
def test_multiple_image_pages_use_explicit_pdfium_and_all_page_preservation(tmp_path, monkeypatch, adapter_corpus, tagged_control, mode):
    """A named subprocess stub authors added invisible text, never real OCR.

    Real PDF inspection, rendering, token and navigation checks still run on all
    three authored pages. The added words are test data, not recognized content.
    Native OCR accuracy/availability is a separate runtime qualification.
    """
    from pdf_remediator import ocr
    source = tmp_path / "authored-multiple-image-pages.pdf"
    _authored_multiple_image_pages(source, adapter_corpus, tagged_control)
    before = source.read_bytes()
    destination = tmp_path / "named-test-layer.pdf"
    commands = []
    version = tmp_path / "named-version.txt"
    version.write_text("17.13.0\n", encoding="utf-8")

    def named_subprocess_stub(command, directory, timeout_seconds, memory_limit_bytes, cancel, env):
        assert list(map(str, command[1:7])) == ["-I", "-B", "-X", "utf8", "-m", "ocrmypdf"]
        commands.append(list(map(str, command)))
        assert timeout_seconds <= 600 and memory_limit_bytes == 4 * 1024**3
        assert env["OMP_THREAD_LIMIT"] == "1"
        if "--version" in command:
            return {"status": "completed", "stdout": str(version)}
        with pikepdf.open(source) as pdf:
            for page in list(pdf.pages)[:2]:
                page.Resources.Font = pikepdf.Dictionary(FNamed=pikepdf.Dictionary(
                    Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
                addition = pdf.make_stream(b"BT /FNamed 8 Tf 3 Tr 10 10 Td (Named synthetic added text) Tj ET")
                existing = page.obj.Contents
                page.obj.Contents = pikepdf.Array(list(existing) + [addition]) if isinstance(existing, pikepdf.Array) else pikepdf.Array([existing, addition])
            pdf.save(destination, deterministic_id=True)
        return {"status": "completed", "returncode": 0,
                "scope": "Named test-layer authoring subprocess stub; OCR was not executed"}

    monkeypatch.setattr(ocr, "run", named_subprocess_stub)
    monkeypatch.setattr(ocr, "ocr_availability", lambda settings: {
        "available": True, "message": "Named availability stub", "runtime_verified": False})
    result = ocr.run_ocr(source, destination, {"project_root": tmp_path / "project"},
                         workdir=tmp_path / "evidence", mode=mode)
    assert result["status"] == "completed"
    assert result["source_image_pages"] == [1, 2]
    assert result["preservation"]["status"] == "pass"
    assert result["preservation"]["all_pages_compared"] == result["preservation"]["expected_pages"] == 3
    assert result["preservation"]["added_tokens"] > 0
    assert all(page["text"]["removed_tokens"] == 0 and page["any_delta_pixel_fraction"] == 0
               for page in result["fidelity"]["pages"])
    command = commands[-1]
    for flag, value in (("--mode", mode), ("--rasterizer", "pypdfium"), ("--output-type", "pdf"), ("--optimize", "0"), ("--jobs", "1")):
        assert command[command.index(flag) + 1] == value
    assert "ghostscript" not in command and "--force-ocr" not in command
    assert result["rasterizer"] == "pypdfium" and result["no_force"] is True
    assert result["human_review_pending"] == ["OCR accuracy", "OCR completeness", "reading order"]
    assert result['ocr_profile'] == 'standard' and command.count('--plugin') == 1
    assert Path(command[command.index('--plugin') + 1]) == Path(ocr.__file__).resolve().with_name('ocr_confidence_plugin.py')
    assert source.read_bytes() == before


def test_multiple_image_pages_never_accept_a_dropped_later_page(tmp_path, adapter_corpus, tagged_control):
    source, candidate = tmp_path / "authored-three.pdf", tmp_path / "missing-third.pdf"
    _authored_multiple_image_pages(source, adapter_corpus, tagged_control)
    with pikepdf.open(source) as pdf:
        del pdf.pages[-1]
        pdf.save(candidate, deterministic_id=True)
    fidelity = compare_fidelity(source, candidate)
    assert fidelity["status"] == "fail"
    assert _ocr_preservation(fidelity, expected_pages=3)["status"] == "fail"


def test_ocr_precancellation_stops_before_any_native_process(tmp_path, monkeypatch, tagged_control):
    from pdf_remediator import ocr
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(ocr, "ocr_availability", lambda settings: {
        "available": True, "message": "Named availability stub", "runtime_verified": False})
    monkeypatch.setattr(ocr, "run", lambda *a, **kw: pytest.fail("Cancelled input reached native OCR"))
    with pytest.raises(InterruptedError, match="PDF inspection cancelled"):
        ocr.run_ocr(tagged_control, tmp_path / "candidate.pdf", workdir=tmp_path / "evidence", cancel=cancel)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode,control,reason", [("skip", "mixed", "mixed pages"), ("redo", "tagged", "existing tags")])
def test_available_ocr_still_refuses_mixed_skip_and_tagged_redo(tmp_path, monkeypatch, adapter_corpus, tagged_control, mode, control, reason):
    from pdf_remediator import ocr
    monkeypatch.setattr(ocr, "ocr_availability", lambda settings: {
        "available": True, "message": "Named availability stub", "runtime_verified": False})
    monkeypatch.setattr(ocr, "run", lambda *a, **kw: pytest.fail("Unsupported route reached native OCR"))
    source = adapter_corpus / "mixed-same-page.pdf" if control == "mixed" else tagged_control
    result = ocr.run_ocr(source, tmp_path / "candidate.pdf", workdir=tmp_path / "evidence", mode=mode)
    assert result["status"] == "unsupported" and reason in result["error"]
    assert list(tmp_path.iterdir()) == []


def _authored_merged_grid(scale=1):
    # Leave enough surrounding page area for the real profile's unchanged
    # 15% colored-header and 12% total recognition-change limits.
    image = Image.new('RGB', (1000 * scale, 1500 * scale), 'white')
    image.info['dpi'] = (150 * scale, 150 * scale)
    draw = ImageDraw.Draw(image)
    box = lambda values: tuple(value * scale for value in values)
    draw.rectangle(box((100, 200, 900, 350)), fill=(55, 125, 180))
    draw.rectangle(box((100, 200, 350, 500)), fill=(55, 125, 180))
    for y, left in ((200, 100), (350, 350), (500, 100), (700, 100)):
        draw.line(box((left, y, 900, y)), fill='black', width=3 * scale)
    for x, top in ((100, 200), (350, 200), (650, 350), (900, 200)):
        draw.line(box((x, top, x, 700)), fill='black', width=3 * scale)
    font = ImageFont.load_default(size=24 * scale)
    draw.text(box((130, 250)), 'AUTHORED MERGED HEADER', fill='white', font=font)
    # A thin authored glyph crosses the fictitious full-width row boundary.
    draw.rectangle(box((208, 325, 211, 375)), fill='white')
    draw.text(box((120, 100)), 'Blue body text outside the table', fill=(25, 75, 160), font=font)
    return image


@pytest.mark.parametrize('scale', [1, 2])
def test_ruled_table_filter_follows_partial_rulings_and_preserves_outside_pixels(scale):
    from pdf_remediator.ocr_table_lines import filter_table_lines
    with _authored_merged_grid(scale) as image:
        before = image.tobytes()
        result, proof = filter_table_lines(image)
        try:
            assert proof['status'] == 'filtered' and proof['outside_detected_grids_unchanged'] is True
            assert proof['header_normalized'] is True
            assert image.tobytes() == before and result.size == image.size and result.info['dpi'] == image.info['dpi']
            grid = proof['grids'][0]
            partial = next(box for box in grid['horizontal'] if abs((box[1] + box[3]) / 2 - 350 * scale) < 10 * scale)
            assert partial[0] >= 345 * scale
            inner = next(box for box in grid['vertical'] if abs((box[0] + box[2]) / 2 - 650 * scale) < 10 * scale)
            assert inner[1] >= 345 * scale
            assert max(result.getpixel((209 * scale, 350 * scale))) < 30
            assert ImageChops.difference(image.crop((0, 0, 1000 * scale, 180 * scale)),
                                         result.crop((0, 0, 1000 * scale, 180 * scale))).getbbox() is None
        finally:
            result.close()


def test_ruled_table_filter_does_not_treat_text_underlines_or_a_logo_frame_as_grid():
    from pdf_remediator.ocr_table_lines import filter_table_lines
    with Image.new('RGB', (1000, 1000), 'white') as image:
        image.info['dpi'] = (150, 150)
        draw = ImageDraw.Draw(image)
        draw.text((100, 100), 'Authored paragraph and underlined link', fill='black', font=ImageFont.load_default(size=24))
        draw.line((100, 135, 700, 135), fill='black', width=2)
        draw.rectangle((100, 250, 350, 400), outline='black', width=3)
        result, proof = filter_table_lines(image)
        try:
            assert proof['status'] == 'no-grid' and proof['grids'] == []
            assert result.tobytes() == image.tobytes()
        finally:
            result.close()


@pytest.mark.parametrize('size,dpi', [((10_000, 5_000), 300), ((100, 100), float('nan'))])
def test_ruled_table_filter_refuses_unsupported_bounds_before_reading_pixels(size, dpi):
    from types import SimpleNamespace
    from pdf_remediator.ocr_table_lines import filter_table_lines
    with pytest.raises(ValueError, match='Ruled-table OCR profile'):
        filter_table_lines(SimpleNamespace(size=size, info={'dpi': (dpi, dpi)}))


def test_ruled_table_filter_refuses_dense_masks_instead_of_silently_downgrading():
    from pdf_remediator.ocr_table_lines import filter_table_lines
    with Image.new('RGB', (1000, 1000), 'white') as image:
        image.info['dpi'] = (150, 150)
        draw = ImageDraw.Draw(image)
        for value in range(100, 901, 25):
            draw.line((100, value, 900, value), fill='black', width=3)
            draw.line((value, 100, value, 900), fill='black', width=3)
        with pytest.raises(ValueError, match='ruling mask'):
            filter_table_lines(image)


@pytest.mark.parametrize('profile', ['../other-plugin.py', True])
def test_unknown_ocr_profile_refuses_before_inspection_or_native_process(tmp_path, monkeypatch, profile):
    from pdf_remediator import ocr
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'Named non-parsed profile preflight control')
    monkeypatch.setattr(ocr, 'inspect_pdf', lambda *a, **kw: pytest.fail('Unknown profile reached inspection'))
    monkeypatch.setattr(ocr, 'run', lambda *a, **kw: pytest.fail('Unknown profile reached native process'))
    result = ocr.run_ocr(source, tmp_path / 'output.pdf', {'ocr_profile': profile}, tmp_path / 'evidence')
    assert result['status'] == 'unsupported' and 'scan layout' in result['error']
    assert sorted(path.name for path in tmp_path.iterdir()) == ['source.pdf']


@pytest.mark.parametrize('evidence_kind', ['valid', 'missing', 'wrong-source', 'wrong-module',
    'minimal', 'missing-raster', 'malformed-raster', 'wrong-version', 'invalid-size',
    'invalid-grid', 'invalid-dpi', 'invalid-fraction', 'nonzero-no-grid', 'valid-filtered',
    'missing-bbox', 'missing-header-luma', 'invalid-axis', 'invalid-envelope',
    'invalid-changed-bbox', 'fractional-pixel', 'inconsistent-mask', 'invalid-candidates',
    'inconsistent-hash', 'excess-header'])
def test_table_profile_uses_only_fixed_plugin_and_requires_bound_page_evidence(tmp_path, monkeypatch, adapter_corpus, evidence_kind):
    """A named subprocess double authors a layer/proof; no OCR is executed."""
    from pdf_remediator import ocr
    source = adapter_corpus / 'scan-only.pdf'
    source_hash = ocr.sha(source)
    destination = tmp_path / 'named-added-text.pdf'
    version = tmp_path / 'version.txt'
    version.write_text('17.13.0\n', encoding='utf-8')
    plugin = Path(ocr.__file__).with_name('ocr_table_plugin.py').resolve()
    algorithm = plugin.with_name('ocr_table_lines.py')
    monkeypatch.setenv('PDF_REMEDIATOR_TABLE_EVIDENCE', 'inherited-untrusted-path')
    monkeypatch.setenv('PDF_REMEDIATOR_TABLE_SOURCE_SHA256', 'inherited-untrusted-hash')

    def named_table_subprocess_double(command, directory, timeout, memory, cancel, env):
        if '--version' in command:
            assert 'PDF_REMEDIATOR_TABLE_EVIDENCE' not in env
            return {'status': 'completed', 'stdout': str(version)}
        assert Path(command[command.index('--plugin') + 1]) == plugin
        assert list(map(str, command[1:7])) == ['-I', '-B', '-X', 'utf8', '-m', 'ocrmypdf']
        assert env['PDF_REMEDIATOR_TABLE_SOURCE_SHA256'] == source_hash
        evidence = Path(env['PDF_REMEDIATOR_TABLE_EVIDENCE'])
        assert evidence == tmp_path / 'evidence/table-lines'
        with pikepdf.open(source) as pdf:
            page = pdf.pages[0]
            page.Resources.Font = pikepdf.Dictionary(FNamed=pikepdf.Dictionary(Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
            prior = page.obj.Contents
            addition = pdf.make_stream(b'BT /FNamed 8 Tf 3 Tr 10 10 Td (Named authored text layer) Tj ET')
            page.obj.Contents = pikepdf.Array(list(prior) + [addition]) if isinstance(prior, pikepdf.Array) else pikepdf.Array([prior, addition])
            pdf.save(destination, deterministic_id=True)
        if evidence_kind != 'missing':
            from pdf_remediator.ocr_table_lines import filter_table_lines
            filtered_cases = {'valid-filtered', 'invalid-axis', 'invalid-envelope', 'invalid-changed-bbox',
                              'fractional-pixel', 'inconsistent-mask'}
            with (_authored_merged_grid() if evidence_kind in filtered_cases else Image.new('RGB', (100, 100), 'white')) as authored:
                prepared, proof = filter_table_lines(authored)
                prepared.close()
            # Round-trip the actual hook's JSON representation, including its
            # nullable fields and partial merged-cell ruling rectangles.
            proof = json.loads(json.dumps(proof))
            proof.update(schema='phase1-ocr-table-preprocess-1', profile='table-lines', page=1,
                         adapter_source_sha256=source_hash if evidence_kind != 'wrong-source' else '0' * 64,
                         plugin_sha256=ocr.sha(plugin) if evidence_kind != 'wrong-module' else '0' * 64,
                         algorithm_sha256=ocr.sha(algorithm))
            if evidence_kind == 'minimal':
                proof = {key: proof[key] for key in ('schema', 'profile', 'page', 'adapter_source_sha256',
                    'plugin_sha256', 'algorithm_sha256', 'outside_detected_grids_unchanged', 'status')}
            elif evidence_kind == 'missing-raster':
                proof.pop('input_RGB_pixels_sha256')
            elif evidence_kind == 'malformed-raster':
                proof['output_RGB_pixels_sha256'] = 'not-a-raster-hash'
            elif evidence_kind == 'wrong-version':
                proof['profile_version'] = 'unmeasured-preprocessing'
            elif evidence_kind == 'invalid-size':
                proof['image_size'] = [100_000, 100_000]
            elif evidence_kind == 'invalid-grid':
                proof.update(status='filtered', grids=[{'bounds': [-1, 0, 100, 100]}])
            elif evidence_kind == 'invalid-dpi':
                proof['dpi'] = float('nan')
            elif evidence_kind == 'invalid-fraction':
                proof['changed_recognition_fraction'] = .5
            elif evidence_kind == 'nonzero-no-grid':
                proof['ruling_mask_fraction'] = .01
            elif evidence_kind == 'missing-bbox':
                proof.pop('changed_recognition_bbox')
            elif evidence_kind == 'missing-header-luma':
                proof.pop('header_dominant_luma')
            elif evidence_kind == 'invalid-axis':
                proof['grids'][0]['horizontal'][0][3] += 50
            elif evidence_kind == 'invalid-envelope':
                proof['grids'][0]['bounds'][0] -= 1
            elif evidence_kind == 'invalid-changed-bbox':
                proof['changed_recognition_bbox'][0] = 0
            elif evidence_kind == 'fractional-pixel':
                proof['changed_recognition_fraction'] += .5 / (proof['image_size'][0] * proof['image_size'][1])
            elif evidence_kind == 'inconsistent-mask':
                proof['ruling_mask_fraction'] += 1 / (proof['image_size'][0] * proof['image_size'][1])
            elif evidence_kind == 'invalid-candidates':
                proof['horizontal_candidates'] = True
            elif evidence_kind == 'inconsistent-hash':
                proof['output_RGB_pixels_sha256'] = '0' * 64
            elif evidence_kind == 'excess-header':
                proof.update(header_pixels=2000, header_dominant_luma=100)
            (evidence / '000001.json').write_text(json.dumps(proof), encoding='utf-8')
        return {'status': 'completed', 'returncode': 0}

    monkeypatch.setattr(ocr, 'run', named_table_subprocess_double)
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'Named availability double', 'runtime_verified': False})
    result = ocr.run_ocr(source, destination, {'project_root': tmp_path / 'project', 'ocr_profile': 'table-lines'}, tmp_path / 'evidence')
    assert ocr.sha(source) == source_hash and result['ocr_profile'] == 'table-lines'
    if evidence_kind in ('valid', 'valid-filtered'):
        assert result['status'] == 'completed' and result['preservation']['status'] == 'pass'
        assert len(result['recognition_preprocessing']['pages']) == 1
        assert result['human_review_pending'] == ['OCR accuracy', 'OCR completeness', 'reading order']
    else:
        assert result['status'] == 'error' and 'evidence' in result['error']


def _append_authored_hidden_text(pdf, page, words):
    """Named test content; it does not represent recognized source words."""
    fonts = page.Resources.get('/Font', pikepdf.Dictionary())
    fonts['/FTextlessControl'] = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
    page.Resources.Font = fonts
    addition = pdf.make_stream(b'BT /FTextlessControl 8 Tf 3 Tr 10 10 Td (' + words + b') Tj ET')
    existing = page.obj.Contents
    page.obj.Contents = pikepdf.Array(list(existing) + [addition]) if isinstance(existing, pikepdf.Array) else pikepdf.Array([existing, addition])


@pytest.mark.parametrize('profile,outcome', [('standard', 'valid'), ('standard', 'added-excluded'),
    ('standard', 'removed-excluded'), ('standard', 'empty-selected'), ('table-lines', 'valid'),
    ('table-lines', 'missing-selected-proof'), ('table-lines', 'extra-excluded-proof')])
def test_textless_driver_limits_native_ocr_to_scan_pages_and_retains_existing_text(tmp_path, monkeypatch, adapter_corpus, tagged_control, profile, outcome):
    """Actual PDF gates around a named layer-writing subprocess double."""
    from pdf_remediator import ocr
    source = tmp_path / 'authored-mixed-document.pdf'
    assembly = tmp_path / 'authored-source-assembly.pdf'
    _authored_multiple_image_pages(assembly, adapter_corpus, tagged_control)
    with pikepdf.open(assembly) as pdf:
        # Page 1 is scanned; page 2 has both an image and existing OCR text;
        # page 3 carries existing digital content. Only page 1 is eligible.
        _append_authored_hidden_text(pdf, pdf.pages[1], b'Existing authored selectable control words')
        pdf.save(source, deterministic_id=True)
    original_bytes = source.read_bytes()
    destination = tmp_path / 'named-selective-layer.pdf'
    version = tmp_path / 'version.txt'
    version.write_text('17.13.0\n', encoding='utf-8')
    native = []

    def named_textless_subprocess_double(command, directory, timeout, memory, cancel, env):
        if '--version' in command:
            return {'status': 'completed', 'stdout': str(version)}
        args = list(map(str, command))
        native.append(args)
        assert args[1:7] == ['-I', '-B', '-X', 'utf8', '-m', 'ocrmypdf']
        assert args[args.index('--mode') + 1] == 'skip' and args[args.index('--pages') + 1] == '1'
        assert args.count('--pages') == 1 and '--force-ocr' not in args and '--redo-ocr' not in args
        assert timeout <= 600 and memory == 4 * 1024**3 and env['OMP_THREAD_LIMIT'] == '1'
        with pikepdf.open(source) as pdf:
            if outcome != 'empty-selected':
                _append_authored_hidden_text(pdf, pdf.pages[0], b'Named authored new cover text')
            if outcome == 'added-excluded':
                _append_authored_hidden_text(pdf, pdf.pages[1], b'Unrequested invented page content')
            elif outcome == 'removed-excluded':
                pdf.pages[1].obj.Contents = pikepdf.Array(list(pdf.pages[1].obj.Contents)[:-1])
            pdf.save(destination, deterministic_id=True)
        if profile == 'table-lines' and outcome != 'missing-selected-proof':
            from pdf_remediator.ocr_table_lines import filter_table_lines
            plugin = Path(ocr.__file__).with_name('ocr_table_plugin.py')
            for number in ([1, 2] if outcome == 'extra-excluded-proof' else [1]):
                with Image.new('RGB', (100, 100), 'white') as image:
                    prepared, proof = filter_table_lines(image)
                    prepared.close()
                proof.update(schema='phase1-ocr-table-preprocess-1', profile='table-lines', page=number,
                    adapter_source_sha256=ocr.sha(source), plugin_sha256=ocr.sha(plugin),
                    algorithm_sha256=ocr.sha(plugin.with_name('ocr_table_lines.py')))
                (Path(env['PDF_REMEDIATOR_TABLE_EVIDENCE']) / f'{number:06d}.json').write_text(json.dumps(proof), encoding='utf-8')
        return {'status': 'completed', 'returncode': 0, 'command': args}

    monkeypatch.setattr(ocr, 'run', named_textless_subprocess_double)
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'Named local runtime double'})
    result = ocr.run_ocr(source, destination, {'project_root': tmp_path / 'project', 'ocr_profile': profile},
                         tmp_path / 'evidence', mode='textless')
    assert source.read_bytes() == original_bytes and len(native) == 1
    assert result['mode'] == result['requested_mode'] == 'textless' and result['native_mode'] == 'skip'
    assert result['page_selection']['selected_pages'] == [1] and result['page_selection']['excluded_pages'] == [2, 3]
    if outcome == 'valid':
        assert result['status'] == 'completed' and result['preservation']['status'] == 'pass'
        assert result['textless_page_coverage']['status'] == 'pass'
        assert all(page['text']['removed_tokens'] == page['text']['added_tokens'] == 0 for page in result['fidelity']['pages'][1:])
        assert all(page['any_delta_pixel_fraction'] == 0 for page in result['fidelity']['pages'])
        if profile == 'table-lines':
            assert [page['page'] for page in result['recognition_preprocessing']['pages']] == [1]
    elif outcome.endswith('-proof'):
        assert result['status'] == 'error' and 'evidence' in result['error']
    else:
        assert result['status'] == 'failed' and result['preservation']['status'] == 'fail'


def test_textless_driver_refuses_true_mixed_page_before_native_work(tmp_path, monkeypatch, adapter_corpus):
    from pdf_remediator import ocr
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'Named local runtime double'})
    monkeypatch.setattr(ocr, 'run', lambda *a, **kw: pytest.fail('A text-bearing page was sent to native OCR'))
    result = ocr.run_ocr(adapter_corpus / 'mixed-same-page.pdf', tmp_path / 'output.pdf',
                         {'project_root': tmp_path / 'project'}, tmp_path / 'evidence', mode='textless')
    assert result['status'] == 'unsupported' and 'No wholly scanned pages' in result['error']
    assert not (tmp_path / 'evidence').exists() and not (tmp_path / 'project').exists()


def test_completed_scan_inventory_contains_explicit_zero_text_paints(adapter_corpus):
    inspection = inspect_pdf(adapter_corpus / 'scan-only.pdf')
    page = inspection['pages'][0]
    assert page['class'] == 'scanned' and page['text_characters'] == 0
    assert page['content']['counts']['text_paints'] == 0 and not page['content']['errors']


@pytest.mark.parametrize('drop_existing_tree', [False, True])
def test_textless_driver_retains_existing_tag_inventory_or_fails(tmp_path, monkeypatch, adapter_corpus, drop_existing_tree):
    from pdf_remediator import ocr
    source = adapter_corpus / 'scan-only_tagged.pdf'
    before = source.read_bytes()
    destination = tmp_path / 'named-tagged-selective-layer.pdf'
    version = tmp_path / 'version.txt'
    version.write_text('17.13.0\n', encoding='utf-8')

    def named_tagged_layer_double(command, *args):
        if '--version' in command:
            return {'status': 'completed', 'stdout': str(version)}
        assert command[command.index('--mode') + 1] == 'skip'
        assert command[command.index('--pages') + 1] == '1'
        with pikepdf.open(source) as pdf:
            _append_authored_hidden_text(pdf, pdf.pages[0], b'Named new selectable control text')
            if drop_existing_tree:
                del pdf.Root['/StructTreeRoot']
            pdf.save(destination, deterministic_id=True)
        return {'status': 'completed', 'returncode': 0}

    monkeypatch.setattr(ocr, 'run', named_tagged_layer_double)
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'Named local runtime double'})
    result = ocr.run_ocr(source, destination, {'project_root': tmp_path / 'project'}, tmp_path / 'evidence', mode='textless')
    assert result['status'] == ('failed' if drop_existing_tree else 'completed')
    assert result['existing_tag_inventory_preserved'] is (not drop_existing_tree)
    assert source.read_bytes() == before
