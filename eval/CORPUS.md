# Phase 0 original synthetic corpus

The generator creates fifteen original fixture PDFs (220 pages), an image asset, the embedded font license, and a ground-truth manifest. It uses reportlab, pikepdf, and Pillow in the isolated evaluator environment. It makes no network requests and neither reads nor changes supplied documents. All fixture content is invented for this evaluation.

Run from the `pdf-remediator` directory after the PDF authoring marker has succeeded:

```text
<evaluator-python> eval/build_corpus.py --output corpus
```

The destination must be empty. A rerun goes into a new directory. The random seed, PDF authoring timestamps, and content are fixed. The manifest records the generator, PDF, font, and asset hashes plus runtime versions. Byte identity must be tested with the same pinned runtime; the fixed seed alone is not a claim of byte identity across releases.

| Fixture | Pages | Ground truth and purpose |
|---|---:|---|
| simple-embedded.pdf | 1 | Digital text using embedded Vera TrueType fonts; no tags. |
| simple-standard-unembedded.pdf | 1 | Similar simple reading with standard unembedded Helvetica fonts; no tags. |
| structured-chapter.pdf | 4 | Heading hierarchy, nested list, simple and complex tables, two columns, a footnote, URI annotation, page labels, and one shared image under two different captions. |
| synthetic-book-200.pdf | 200 | Fourteen chapters, contents, index, alternating running headers, footer labels, repeated Form XObject, bookmarks, roman/decimal page labels, columns, notes, illustrations, and one table spanning pages 20-21. Each page has a unique body-text anchor. |
| scan-only.pdf | 1 | Image pixels only, including known visible text. |
| mixed-same-page.pdf | 1 | Selectable introductory text and scanned text share a page. |
| tagged-control.pdf | 1 | Genuine positive structural control: embedded fonts, H1/P/P marked-content sequences, MCIDs, parent references, ParentTree, metadata, and language. |
| phantom-tree.pdf | 1 | Same visible content and a retained tree, but zero content marking. Must be rejected as a phantom tree. |
| incomplete-tags.pdf | 1 | Two valid linked sequences and an unmarked final visible paragraph. A single valid link must not pass whole-page coverage. |
| deliberate-content-loss.pdf | 1 | The final paragraph is absent, with a reduced valid-looking tree. Text and render fidelity against the positive control must fail. |
| mis-mapped-font.pdf | 1 | Glyph appearance preserved while the embedded font's C-to-Unicode mapping changes to Z. A ToUnicode dictionary being present is insufficient. |
| forms-detect-only.pdf | 1 | Interactive text field and Widget annotation; preserve and flag as unsupported. |
| slides-detect-only.pdf | 3 | Wide presentation-style pages; detection only. |
| equation-detect-only.pdf | 1 | Visually positioned superscript and equation; detection only. |
| intentional-blank.pdf | 2 | Digital first page followed by a genuinely blank second page. |

`tagged-control.pdf` is known-good for its specified structural ground truth. Its PDF/UA declaration is an input to validation, not evidence of conformance. Only a successful pinned validator run may establish its automated validator result; semantic review remains separately recorded. Any control deficiency found by the validator must be reported and repaired with a new manifest hash before using it as a positive validator control.

The manifest declares expected content anchors, relationships, known blockers, scan classification, preservation requirements, PDF dimensions, navigation, and fixture lineage. A raw fixture's expected status is separate from the result of an engine. A missing scan anchor from ordinary PDF extraction is expected; it must be evaluated against visible image text in the OCR experiment. The deliberately incorrect font mapping requires extraction-versus-render evidence rather than a presence check.

Each generated book page has a stable `BOOK-PAGE-NNN` anchor. Pages 20-21 are one conceptual table with a repeated heading row. Pages 30-31, 90-91, and 150-151 read down the left column before the right column. Pages 40 and 110 use identical drawing bytes for different purposes. The small repeated blue marker is a shared Form XObject in the running header area; geometric repetition alone does not justify removing nearby body content. A repeated body phrase on the figure pages is explicitly meaningful.

No representative real book has been added. Synthetic results support a provisional feasibility recommendation only. The corpus does not model damaged PDFs, encrypted/signed inputs, advanced scripts, embedded attachments, every table topology, poor-quality OCR, or all font mapping mechanisms. Do not extend supported-case claims from these fixtures without additional evidence.

The generator checks page counts and captures basic baseline features. It does not imply visual QA or engine assessment. Render every evaluated input/output page with the same pinned renderer and settings; inspect a montage plus full-size representative pages. Inspect the control, chapter table/columns/figures, mixed scan, chapter opening, book table continuation, and final index page for clipping, overlap, or missing content before engine scoring.

The initial generated corpus was rendered successfully on all 220 pages with pypdfium2 5.14.0 at scale 1 (72 pixels per inch); all declared digital anchors were present. `corpus/qa/render-and-anchor-checks.json` records the per-page render coverage, source hashes, and control comparisons. `contact-sheet.png` and `all-book-pages.png` were visually inspected, together with full-size images of the complex table, footnote, tagged control, mixed page, and table continuation. No clipping or overlap was observed in those views. This limited visual inspection is distinct from full-page fidelity comparison of each engine output.

The phantom and incomplete variants rendered and extracted identically to the positive control. The incorrect font mapping rendered identically while extraction changed C to Z. The content-loss variant differed in both rendered pixels and extracted text. Those checks confirm the intended corruption is observable by separate structural, text, and visual assessments.
