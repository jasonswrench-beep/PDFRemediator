"""Adversarial hand-authored PDFs check the evaluator, independently of engines."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

import pikepdf

from inspect_pdf import compare_fidelity, inspect_pdf


def _tiny(path, *, text="ALPHA BETA", tagged=True, phantom=False, extra=False,
          named=False, form=False, parent_bad=False, image=False, metadata=True,
          bookmark=False, label=False, annotation=False, swapped=False):
    """Hand-encode ground truth; no engine or evaluator helper authors the tags."""
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(240, 180))
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                   BaseFont=pikepdf.Name.Helvetica, Encoding=pikepdf.Name.WinAnsiEncoding))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        body = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET"
        if swapped:
            body = "BT /F1 12 Tf 20 100 Td (BETA ALPHA) Tj ET"
        if tagged:
            body = ("/P /Props BDC " if named else "/P << /MCID 0 >> BDC ") + body + " EMC"
            if named:
                page.Resources.Properties = pikepdf.Dictionary(Props=pikepdf.Dictionary(MCID=0))
        if extra:
            body += " BT /F1 12 Tf 20 70 Td (UNCOVERED) Tj ET"
        if image:
            raster = pikepdf.Stream(pdf, bytes([128, 40, 30]))
            raster.Type = pikepdf.Name.XObject
            raster.Subtype = pikepdf.Name.Image
            raster.Width, raster.Height = 1, 1
            raster.ColorSpace = pikepdf.Name.DeviceRGB
            raster.BitsPerComponent = 8
            page.Resources.XObject = pikepdf.Dictionary(Im=raster)
            body += " q 20 0 0 20 150 80 cm /Im Do Q"
        content_stream = None
        if form:
            content_stream = pikepdf.Stream(pdf, body.encode("ascii"))
            content_stream.Type = pikepdf.Name.XObject
            content_stream.Subtype = pikepdf.Name.Form
            content_stream.BBox = pikepdf.Array([0, 0, 240, 180])
            content_stream.Resources = page.Resources
            content_stream.StructParents = 1
            page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm=content_stream))
            body = "q /Fm Do Q"
        page.Contents = pikepdf.Stream(pdf, body.encode("ascii"))
        if tagged:
            element = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.P, Pg=page.obj))
            root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot, K=pikepdf.Array([element])))
            element.P = root
            if content_stream is not None:
                element.K = pikepdf.Dictionary(Type=pikepdf.Name.MCR, Pg=page.obj, Stm=content_stream, MCID=7 if phantom else 0)
            else:
                page.StructParents = 0
                element.K = 7 if phantom else 0
            root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([1 if form else 0, pikepdf.Array([None if parent_bad else element])])))
            root.ParentTreeNextKey = 2
            pdf.Root.StructTreeRoot = root
            pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        if metadata:
            pdf.docinfo.Title = "Known test content"
            pdf.Root.Lang = "en-US"
            pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        if bookmark:
            root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines))
            item = pdf.make_indirect(pikepdf.Dictionary(Title="Chapter one", Parent=root, Dest=pikepdf.Array([page.obj, pikepdf.Name.Fit])))
            root.First = item
            root.Last = item
            root.Count = 1
            pdf.Root.Outlines = root
        if label:
            pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Dictionary(S=pikepdf.Name.r, St=1)]))
        if annotation:
            link = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                                                       Rect=pikepdf.Array([20, 95, 100, 115]), Border=pikepdf.Array([0, 0, 0]),
                                                       A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI="https://example.org/")))
            page.Annots = pikepdf.Array([link])
        pdf.save(path)


def _check(report, name):
    return next(check for check in report["checks"] if check["id"] == name)


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make(self, name="input.pdf", **options):
        path = self.folder / name
        _tiny(path, **options)
        return path

    def test_valid_mcid_and_parent_tree(self):
        report = inspect_pdf(self.make())
        self.assertNotIn("error", report)
        self.assertEqual(_check(report, "content-linkage")["status"], "pass")
        self.assertEqual(_check(report, "content-coverage")["status"], "pass")
        self.assertEqual(report["pages"][0]["class"], "text")
        self.assertEqual(report["pages"][0]["content"]["counts"]["linked_paints"], 1)
        self.assertFalse(report["structure"]["phantom_tree"])

    def test_phantom_references_rejected_despite_bdc(self):
        report = inspect_pdf(self.make(phantom=True))
        self.assertTrue(report["structure"]["phantom_tree"])
        self.assertEqual(_check(report, "content-linkage")["status"], "fail")
        self.assertEqual(report["structure"]["missing_content_references"][0]["mcid"], 7)

    def test_partial_dangling_reference_is_not_wholly_phantom(self):
        original = self.make()
        partial = self.folder / "partial.pdf"
        with pikepdf.open(original) as pdf:
            pdf.Root.StructTreeRoot.K[0].K = pikepdf.Array([0, 7])
            pdf.save(partial)
        report = inspect_pdf(partial)
        self.assertFalse(report["structure"]["phantom_tree"])
        self.assertEqual(report["structure"]["linkage_class"], "partially-unresolved")
        self.assertEqual(report["structure"]["content_reference_counts"], {"declared_unique": 2, "matched_definitions": 1, "unresolved": 1, "ambiguous": 0})
        self.assertEqual(_check(report, "content-linkage")["status"], "fail")
        self.assertEqual(_check(report, "content-coverage")["status"], "pass")

    def test_one_link_does_not_cover_extra_text(self):
        report = inspect_pdf(self.make(extra=True))
        self.assertEqual(_check(report, "content-coverage")["status"], "fail")
        self.assertEqual(report["pages"][0]["content"]["counts"]["uncovered_paints"], 1)
        self.assertEqual(report["pages"][0]["content"]["counts"]["linked_paints"], 1)

    def test_unmapped_parent_tree_rejected(self):
        report = inspect_pdf(self.make(parent_bad=True))
        self.assertEqual(_check(report, "content-linkage")["status"], "fail")
        self.assertEqual(len(report["pages"][0]["content"]["parent_tree_failures"]), 1)

    def test_named_property_mcid_resolved(self):
        report = inspect_pdf(self.make(named=True))
        self.assertEqual(_check(report, "content-linkage")["status"], "pass")
        self.assertEqual(_check(report, "content-coverage")["status"], "pass")

    def test_form_mcr_and_parent_tree_resolved(self):
        report = inspect_pdf(self.make(form=True))
        self.assertNotIn("error", report)
        self.assertEqual(_check(report, "content-linkage")["status"], "pass")
        self.assertEqual(_check(report, "content-coverage")["status"], "pass")
        self.assertEqual(len(report["fonts"]), 1)

    def test_untagged_paint_is_uncovered(self):
        report = inspect_pdf(self.make(tagged=False))
        self.assertFalse(report["structure"]["present"])
        self.assertEqual(_check(report, "content-coverage")["status"], "fail")

    def test_missing_tounicode_is_review_signal_not_automatic_failure(self):
        report = inspect_pdf(self.make())
        self.assertEqual(_check(report, "font-unicode-mapping")["status"], "needs-review")
        self.assertEqual(_check(report, "font-embedding")["status"], "fail")

    def test_mixed_page_is_detected_with_classification_limit(self):
        report = inspect_pdf(self.make(image=True))
        self.assertEqual(report["pages"][0]["class"], "mixed")
        self.assertEqual(report["pages"][0]["classification_status"], "needs-review")
        self.assertTrue(any("photographs" in limit for limit in report["limitations"]))

    def test_identical_file_has_exact_all_page_fidelity(self):
        path = self.make(bookmark=True, label=True, annotation=True)
        result = compare_fidelity(path, path)
        self.assertNotIn("error", result)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["pages"][0]["changed_pixel_fraction"], 0)
        self.assertEqual(result["pages"][0]["max_channel_delta"], 0)
        self.assertEqual(result["pages"][0]["mean_absolute_channel_delta"], 0)
        self.assertEqual(result["text"]["multiset_status"], "pass")

    def test_deleted_word_is_failure(self):
        source = self.make()
        loss = self.make("loss.pdf", text="ALPHA")
        result = compare_fidelity(source, loss)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["text"]["removed_tokens"], 1)
        self.assertEqual(result["pages"][0]["text"]["multiset_status"], "fail")
        self.assertGreater(result["pages"][0]["changed_pixel_fraction"], 0)
        self.assertIsNotNone(result["pages"][0]["changed_bbox_pixels"])

    def test_image_loss_is_rejected_when_all_text_is_unchanged(self):
        result = compare_fidelity(self.make(image=True), self.make("loss.pdf"))
        self.assertEqual(result["text"]["multiset_status"], "pass")
        self.assertEqual(result["pages"][0]["render_status"], "fail")
        self.assertEqual(result["status"], "fail")

    def test_missing_input_is_error_not_silent_not_run(self):
        missing = self.folder / "missing.pdf"
        self.assertEqual(inspect_pdf(missing)["status"], "error")
        self.assertEqual(compare_fidelity(missing, missing)["status"], "error")

    def test_bookmark_loss_fails_despite_same_visible_content(self):
        source = self.make(bookmark=True)
        loss = self.make("loss.pdf")
        result = compare_fidelity(source, loss)
        self.assertEqual(result["pages"][0]["render_status"], "pass")
        self.assertEqual(_check(result, "bookmarks-preservation")["status"], "fail")
        self.assertEqual(result["status"], "fail")

    def test_label_loss_fails_despite_same_visible_content(self):
        result = compare_fidelity(self.make(label=True), self.make("loss.pdf"))
        self.assertEqual(result["pages"][0]["render_status"], "pass")
        self.assertEqual(_check(result, "page_labels-preservation")["status"], "fail")

    def test_annotation_loss_fails_despite_same_visible_content(self):
        result = compare_fidelity(self.make(annotation=True), self.make("loss.pdf"))
        self.assertEqual(result["pages"][0]["render_status"], "pass")
        self.assertEqual(result["pages"][0]["annotations_status"], "fail")
        self.assertEqual(result["status"], "fail")

    def test_valid_added_bookmark_is_reported_without_loss(self):
        result = compare_fidelity(self.make(), self.make("added.pdf", bookmark=True))
        self.assertEqual(result["status"], "pass")
        check = _check(result, "bookmarks-preservation")
        self.assertEqual(len(check["evidence"]["added"]), 1)
        self.assertEqual(check["evidence"]["target_statuses"], ["pass"])

    def test_invalid_added_bookmark_is_rejected(self):
        source = self.make()
        added = self.make("added.pdf", bookmark=True)
        changed = self.folder / "invalid.pdf"
        with pikepdf.open(added) as pdf:
            pdf.Root.Outlines.First.Dest = pikepdf.Array([999, pikepdf.Name.Fit])
            pdf.save(changed)
        result = compare_fidelity(source, changed)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(_check(result, "bookmarks-preservation")["evidence"]["target_statuses"], ["fail"])

    def test_existing_bookmark_target_change_fails(self):
        source = self.make(bookmark=True)
        changed = self.folder / "changed.pdf"
        with pikepdf.open(source) as pdf:
            pdf.Root.Outlines.First.Dest = pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.XYZ, 10, 20, 1])
            pdf.save(changed)
        result = compare_fidelity(source, changed)
        self.assertEqual(result["pages"][0]["render_status"], "pass")
        self.assertEqual(_check(result, "bookmarks-preservation")["status"], "fail")

    def test_empty_annotation_contents_can_be_enriched(self):
        source = self.make(annotation=True)
        changed = self.folder / "changed.pdf"
        with pikepdf.open(source) as pdf:
            pdf.pages[0].Annots[0].Contents = "A descriptive link label"
            pdf.save(changed)
        result = compare_fidelity(source, changed)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["pages"][0]["annotations"]["empty_contents_enriched"]), 1)
        self.assertEqual(result["pages"][0]["annotations"]["empty_contents_enriched"][0]["review_status"], "needs-review")

    def test_nonempty_annotation_contents_cannot_be_silently_overwritten(self):
        original = self.make(annotation=True)
        source, changed = self.folder / "source.pdf", self.folder / "changed.pdf"
        with pikepdf.open(original) as pdf:
            pdf.pages[0].Annots[0].Contents = "Established human description"
            pdf.save(source)
            pdf.pages[0].Annots[0].Contents = "Replacement description"
            pdf.save(changed)
        result = compare_fidelity(source, changed)
        self.assertEqual(result["pages"][0]["render_status"], "pass")
        self.assertEqual(result["pages"][0]["annotations_status"], "fail")

    def test_link_target_change_is_rejected(self):
        source = self.make(annotation=True)
        changed = self.folder / "changed.pdf"
        with pikepdf.open(source) as pdf:
            pdf.pages[0].Annots[0].A.URI = "https://other.example.org/"
            pdf.save(changed)
        self.assertEqual(compare_fidelity(source, changed)["status"], "fail")

    def test_added_named_destination_can_resolve_added_bookmark(self):
        source = self.make()
        added = self.make("added.pdf", bookmark=True)
        changed = self.folder / "changed.pdf"
        with pikepdf.open(added) as pdf:
            pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array(["chapter", pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit])])))
            pdf.Root.Outlines.First.Dest = "chapter"
            pdf.save(changed)
        result = compare_fidelity(source, changed)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(_check(result, "named_destinations-preservation")["evidence"]["added"], ["chapter"])

    def test_equivalent_numeric_labels_are_preserved(self):
        source = self.make()
        changed = self.folder / "changed.pdf"
        with pikepdf.open(source) as pdf:
            pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Dictionary(S=pikepdf.Name.D, St=1)]))
            pdf.save(changed)
        self.assertEqual(compare_fidelity(source, changed)["status"], "pass")

    def test_unused_unembedded_font_does_not_fail_embedding(self):
        source = self.make(text="")
        report = inspect_pdf(source)
        self.assertEqual(report["fonts"][0]["used_text_operations"], 0)
        self.assertEqual(_check(report, "font-embedding")["status"], "not-applicable")

    def test_token_multiset_and_order_are_separate(self):
        original = self.make(text="ALPHA                     BETA")
        swapped = self.make("swapped.pdf", swapped=True)
        result = compare_fidelity(original, swapped)
        self.assertEqual(result["text"]["multiset_status"], "pass")
        self.assertEqual(result["text"]["removed_tokens"], 0)
        # A true order change is not token deletion, even though pixels change.
        self.assertEqual(result["text"]["ordered_status"], "needs-review")

    def test_malformed_pdf_reports_error(self):
        bad = self.folder / "bad.pdf"
        bad.write_bytes(b"not a PDF")
        self.assertEqual(inspect_pdf(bad)["status"], "error")


class CorpusMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Regenerate original synthetic ground truth. Missing generator packages
        # or fonts must fail, rather than silently skipping corpus contracts.
        work = Path(__file__).resolve().parents[1] / "work"
        work.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="metrics-corpus-", dir=work)
        cls.addClassCleanup(temporary.cleanup)
        cls.corpus = Path(temporary.name)
        spec = importlib.util.spec_from_file_location("metrics_synthetic_corpus",
            Path(__file__).with_name("build_corpus.py"))
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        builder.register_fonts(cls.corpus)
        builder.tag_control(cls.corpus / "tagged-control.pdf")
        builder.tag_control(cls.corpus / "deliberate-content-loss.pdf", lost=True)
        builder.tag_variants(cls.corpus / "tagged-control.pdf",
            cls.corpus / "phantom-tree.pdf", cls.corpus / "incomplete-tags.pdf")
        builder.mis_mapping(cls.corpus / "tagged-control.pdf", cls.corpus / "mis-mapped-font.pdf")
        builder.scans(cls.corpus / "scan-only.pdf")
        builder.scans(cls.corpus / "mixed-same-page.pdf", mixed=True)
        builder.detection_fixtures(cls.corpus)
        builder.book(cls.corpus / "synthetic-book-200.pdf", builder.ImageReader(builder.image_asset()))

    def test_independent_corpus_controls(self):
        good = inspect_pdf(self.corpus / "tagged-control.pdf")
        self.assertEqual(_check(good, "content-linkage")["status"], "pass")
        self.assertEqual(_check(good, "content-coverage")["status"], "pass")
        phantom = inspect_pdf(self.corpus / "phantom-tree.pdf")
        self.assertTrue(phantom["structure"]["phantom_tree"])
        incomplete = inspect_pdf(self.corpus / "incomplete-tags.pdf")
        self.assertEqual(_check(incomplete, "content-coverage")["status"], "fail")

    def test_scan_mixed_and_blank_ground_truth(self):
        self.assertEqual(inspect_pdf(self.corpus / "scan-only.pdf")["pages"][0]["class"], "scanned")
        self.assertEqual(inspect_pdf(self.corpus / "mixed-same-page.pdf")["pages"][0]["class"], "mixed")
        self.assertEqual(inspect_pdf(self.corpus / "intentional-blank.pdf")["pages"][1]["class"], "blank")

    def test_independent_loss_and_mapping_controls(self):
        good = self.corpus / "tagged-control.pdf"
        loss = compare_fidelity(good, self.corpus / "deliberate-content-loss.pdf")
        self.assertEqual(loss["status"], "fail")
        self.assertEqual(loss["pages"][0]["render_status"], "fail")
        self.assertGreater(loss["text"]["removed_tokens"], 0)
        mismapped = compare_fidelity(good, self.corpus / "mis-mapped-font.pdf")
        self.assertEqual(mismapped["pages"][0]["render_status"], "pass")
        self.assertEqual(mismapped["text"]["multiset_status"], "fail")

    def test_book_inventory_counts_every_page_and_navigation(self):
        report = inspect_pdf(self.corpus / "synthetic-book-200.pdf")
        self.assertEqual(report["page_count"], 200)
        self.assertEqual(len(report["pages"]), 200)
        self.assertTrue(report["navigation"]["bookmarks"])
        self.assertTrue(report["navigation"]["page_labels"])
        self.assertTrue(report["features"]["annotation_count"])


if __name__ == "__main__":
    unittest.main()
