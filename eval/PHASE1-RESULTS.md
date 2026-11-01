# Phase 1 results

Phase 1's local workflow and predeclared core exit are complete on this Windows machine. A simple reading, a structured chapter with recorded synthetic-author descriptions, and a 244-page published book all reached **candidate** with strict PDF/UA-1 validation, the declared supplemental profile, and full preservation checks passing. They still require human verification. No actual the LMS checker score, assistive-technology review, or verified status was invented.

The user's request to move to Phase 1 authorized this work. The supplied planning documents remained reference material. Files in `sources/` and the original Downloads documents were not modified. Phase 0 evidence is retained unchanged.

## Implemented workflow

- `doctor`, `engines`, read-only `check`, single-file and batch `fix`, cancellation, and exact-checkpoint resume.
- Local OpenDataLoader wrapper, page classification, supported OCR routing, proven painting restoration, metadata processing, and bounded optional character-mapping repair.
- Strict standalone veraPDF validation of the original and final bytes, with fixed/remaining/newly failing **rule** IDs. Partial assertion details remain explicit.
- Every-page pixel/text/geometry/annotation comparisons and original bookmark, destination and page-label preservation.
- Atomic immutable bundles with PDF hashes, report, validator evidence, editable decision sidecar, review JSON, HTML packet, and manifest.
- Hash-bound metadata/figure decisions and a verification ledger requiring actual human review and an actual the LMS checker score.

The application contains no AI provider or cloud PDF-processing route. Dependency installation is separate from document processing. The command line is the Phase 1 interface; a graphical application and installer remain later work.

## Core exit evidence

| Case | Result | Strict PDF/UA-1 | Supplemental profile | Preservation | Time |
|---|---|---|---|---|---:|
| Simple reading, 1 page | candidate | pass | pass | pass | 3.906 s |
| Structured chapter, 4 pages | candidate | pass | pass | pass | 3.953 s |
| Think Python, 244 pages | candidate | pass | pass | pass under the declared sourced-character policy | 87.437 s |

[Core summary and exact bundle paths](../output/phase1/core-final/summary.json), [CSV](../output/phase1/core-final/summary.csv), [reproduction script](run_phase1_core.py).

The chapter first produced an intact review draft because two figure descriptions were placeholders. Its candidate applies two explicitly recorded **synthetic fixture-author test decisions**, matching the independently authored garden-plot and archive-bin contexts. These are not approvals by Jason or claims of human accessibility verification. All eight chapter review items remain pending.

The book explicitly enables `--allow-tag-regrouping` and `--repair-source-mappings`, and supplies its published title. Defaults remain conservative. It passes 106 validator rules and 1,088,514 checks with zero failures. The original baseline had 12 failing rules and 44,352 failed checks; assertion detail is partial, so the report compares complete rule inventories without claiming an assertion-by-assertion repair history.

Book preservation is explicit:

1. Proven original painting operations restore exact rendering, including the contents and diagram pages that failed Phase 0.
2. Two absent TeX mappings account for exactly nine glyph occurrences. The repair uses the unchanged embedded Type1 programs and pinned official CTAN mappings: `mapsto` → U+21A6; `radicalBig` → U+221A U+FE02.
3. An independently corrected original reference preserves all 244 source pages visually and preserves navigation. The final PDF matches that reference for every-page pixels, geometry, annotations, navigation and normalized text-token counts. Text reading order remains human review. The raw original-to-final text difference is retained as a failure in the evidence; it is never relabeled as unchanged text.

The book has **627 pending human items**, including 620 recorded list/link regroupings and the character corrections. This establishes a substantial-book automated candidate, not generally reliable book remediation or mathematical accessibility. The largest sampled external process-tree RSS was about 1.57 GiB, within its configured 4 GiB bound. Java heap is 2 GiB. Memory enforcement is sampled, not an OS allocation guarantee or a whole-application hard cap.

## Full synthetic corpus

The definitive 18-case run completed in 114.25 seconds: **7 candidates and 11 needs-manual results**. All 18 bundles independently verified. All 15 original synthetic-file hashes stayed unchanged, and implementation files stayed stable throughout the run.

| Fixture / route | Result | Reason or interpretation |
|---|---|---|
| Simple embedded reading | candidate | All automated gates pass |
| Unembedded standard-font reading | needs-manual | Font embedding/strict validation fail; no font substitution guessed |
| Structured chapter, descriptions pending | needs-manual | Placeholder figure descriptions; intact review draft |
| Synthetic 200-page book, default | needs-manual | Preservation fails; no PDF published |
| Scan-only, OCR off | needs-manual | Missing selectable text / figure description |
| Mixed page, OCR off | needs-manual | Figure description and scanned-text review remain |
| Existing tagged control | candidate | Usable tags retained |
| Phantom input tree | candidate | Retagged; independently checked final linkage and coverage pass |
| Incomplete input tags | candidate | Retagged; final linkage and coverage pass |
| Deliberately damaged input text | candidate for supplied bytes | Original-control comparison independently detects the loss; see limitation below |
| Deliberately wrong C→Z mapping | candidate for supplied bytes | Syntax-valid mapping still requires meaning review; known-control comparison fails |
| Form | needs-manual | Unsupported feature; no PDF published |
| Declared slides | needs-manual | Explicit input declaration; no PDF published |
| Declared equations | needs-manual | Explicit input declaration; no PDF published |
| Intentional blank page | candidate | Preserved; automated gates pass |
| Scan-only, explicit OCR skip | needs-manual | OCR, strict validation and OCR preservation pass; figure description remains |
| Mixed page, explicit OCR redo | needs-manual | OCR, strict validation and OCR preservation pass; figure description remains |
| Synthetic book, opt-in regrouping | needs-manual | One contents page still fails exact rendering; no PDF published |

Thirteen PDFs were published: seven candidates and six clearly labeled review drafts. **Zero PDFs with phantom or broken structure, and zero PDFs without a preservation pass, were published.** Diagnostics and caches are kept outside the completed bundles.

[Full summary](../output/phase1/corpus-final/summary.json), [results table](../output/phase1/corpus-final/summary.csv), [corpus interpretation](PHASE1-CORPUS.md), [reproduction script](run_phase1.py).

Standalone intake cannot infer content missing from an unavailable original, or establish that a syntactically valid Unicode mapping conveys the intended characters. The two deliberately damaged fixtures demonstrate that limit. Independent comparisons with their known controls fail as expected: lost content fails text and rendering; the wrong mapping fails text while rendering stays equal. Mechanical candidacy for supplied bytes is never human verification.

Slides and visual equations also cannot be recognized reliably from arbitrary untagged PDFs. Their trial classifications come from the independent fixture manifest and are supplied through `--document-kind`. Detected formula tags and forms are refused automatically. Every candidate includes a required unsupported-content review.

## Validation and delivery

- **205 regression tests passed** in 17.16 seconds. External-validator stubs are explicitly identified in unit tests; the integration trials use the actual standalone validator. [Test record](../output/phase1/release-tests.json)
- Tests cover exact assessment hashes, changed publication copies, stale approvals, manifest/checkpoint tampering, batch collisions, cancellation, resumed runs, missing tools, malformed validator reports, finite resource bounds, OCR policies, adversarial painting repairs and authoritative-mapping refusals.
- `doctor` reports the selected tools ready. The actual console entry point, a read-only check, and CLI resume were exercised. [Inventory](../output/phase1/doctor.json)
- The core Python wheel builds successfully; its 23 source/data files match the tested package, including mapping authority and license notices. It is not a bundled Windows installer. [Packaging record](../output/phase1/packaging-check.json)
- Contents page 14, mathematical page 74 and diagram page 119 were visually inspected from the book candidate. Final book page 193 and chapter page 3 were also visually inspected; the complete final run independently compares every page. No layout defects were observed in those samples.
- HTML escaping, structure and security restrictions are tested. Browser visual inspection was unavailable: the in-app browser could not reach the local preview and blocks local-file URLs. No browser security restriction was bypassed.

The supplied Downloads README, RESEARCH and SPEC SHA-256 hashes still match the recorded originals. Read-only project sources remain untouched. No LMS upload or production verification-ledger entry was made.

## Remaining limits

The synthetic book remains unsupported because one page fails exact rendering. Arbitrary font restoration, general complex-table repair, automatic meaningful descriptions, multi-page/difficult OCR, visual equation remediation, and slide remediation remain manual/source-document work. Contrast, spoken character meaning, reading order, artifact choices and table/figure semantics still need human assessment. Actual the LMS accessibility checker results have not been measured.

Open the [operating guide](../README.md) to use the prepared local environment. Later phases can improve review usability and add explicitly authorized judgment services; this result does not start those phases.
