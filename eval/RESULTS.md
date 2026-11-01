# PDF Remediator Phase 0 Results

**October 15, 2026**

Phase 0 found no engine ready to serve as the default for books under the declared preservation and structure requirements. OpenDataLoader is the stronger candidate for a focused follow-up: it handled the basic reading and structured chapter well after catalog normalization. Its book outputs still changed visible content, and the published book contained unresolved structural references. Accesspdf preserved page appearance but left substantial book content outside the tag structure and changed existing bookmark navigation.

**Decision: do not begin the broad Phase 1 book implementation on the assumption that either engine is ready.** Continue a bounded OpenDataLoader preservation and structure investigation. The evidence does not yet justify building an entirely new tag writer either.

## What was tested

The comparison contains **32 completed engine cases**: two engines on 16 inputs totaling 464 pages per engine. Fifteen inputs are original synthetic fixtures totaling 220 pages, including a 200-page book. The sixteenth is Allen B. Downey's published, 244-page *Think Python*, second edition, downloaded from Green Tea Press. The publisher identifies its license as CC BY-NC 3.0; attribution and the original hash are retained separately. [Publisher and license statement](https://greenteapress.com/wp/think-python-2e/)

The corpus includes a structured chapter, multi-column content, lists, simple and complex tables, figures reused in different contexts, scans, mixed scanned/digital content, forms, slides, equations, blank pages, and deliberately corrupted controls. All 220 synthetic pages rendered successfully; declared digital text anchors were checked. The original input hashes remained unchanged.

The historical branch was recovered at commit `df20503a1fc2c28f66a316268b443c1f22917a49`. Its notes and three helper scripts are retained as references. All three supplied documents match the pinned Git blobs. The repository contains no historical fixtures, output PDFs, raw reports, dependency lock or license file, so its earlier benchmark numbers remain unreproduced. No historical code was executed or incorporated into this evaluator.

| Component | Tested configuration |
|---|---|
| Tagging engines | OpenDataLoader 2.5.13; accesspdf 1.2.1 |
| Validator | Standalone veraPDF 1.30.3, explicit PDF/UA-1 profile, XML reports |
| Java | Existing Temurin 25.0.3+9, selected by its full path |
| Evaluator | Python 3.11.9; pikepdf 10.17.0; PDFium through pypdfium2 5.14.0; Pillow 12.3.0 |
| Fixture generation | ReportLab 5.0.1, embedded Bitstream Vera fonts with license retained |
| OCR | OCRmyPDF 17.13.0; Tesseract 5.5.3; English model 4.1.0 |

All Python environments are isolated inside the project and have recorded dependency locks and successful package-consistency checks. The standalone validator was installed inside the project. The Tesseract distribution was extracted without running its installer. The working Java path avoids the stalled default Java shortcut. Java 25 worked in the actual tests but is outside the validator install README's listed Java versions; this is observed compatibility on this machine, not a platform support promise.

OCRmyPDF 17.13.1, mentioned by the documentation used during planning, was unavailable from the package index. The installed and tested release is 17.13.0. The environments confirm the expected pikepdf incompatibility between accesspdf and OCRmyPDF; they were not forced into one environment.

a proprietary tagging SDK was not tested because eligibility for its proprietary evaluation/deployment license was not established. No cloud tagging engine or AI enrichment provider was used. Evaluation scripts made no external document-processing calls. Selected rendered diagnostic evidence was inspected in this Codex conversation; the scripts' zero cloud-call count describes engine execution rather than all chat communication.

## Comparison method

For every case, the harness retains the original input fingerprint, engine command, standard output/error, observed runtime and process-tree memory, raw tagged PDF, a separately normalized copy, complete available validator output, supplemental inspection, and all-page fidelity evidence.

The identical normalization step changes only catalog/export metadata, title display, MarkInfo for an existing tree, and page tab order. It does not embed fonts, invent descriptions, repair tables, or fix content streams. Raw and normalized results remain separate.

Fidelity compares every page at 96 dpi using the same PDFium renderer, RGB/white background, and annotations enabled. The declared tolerance is **zero changed pixels**. It independently checks normalized text tokens, page geometry, existing bookmarks, logical page labels, named destinations, and common annotation properties. Valid navigation additions and enrichment of previously empty annotation descriptions are recorded rather than mistaken for lost content. Original destinations and existing nonempty descriptions must remain intact.

A zero-failure validator result means only the machine-verifiable PDF/UA checks passed. It does not establish meaningful descriptions, semantic reading order, OCR accuracy, appropriate table relationships, or complete WCAG coverage. [veraPDF validation scope](https://docs.verapdf.org/validation/)

## Core results

The figures below are **failed veraPDF rules after the same catalog normalization**. A zero is not a product candidate or a verified accessibility result.

| Input | OpenDataLoader failed rules | OpenDataLoader preservation | Accesspdf failed rules | Accesspdf preservation |
|---|---:|---|---:|---|
| Simple embedded-font reading, 1 page | 0 | Pass | 0 | Pass |
| Structured chapter, 4 pages | 0 | Pass | 5 | Pass |
| Synthetic book, 200 pages | 0 | Fail | 6 | Fail |
| Published book, 244 pages | 1 | Fail | 6 | Fail |

Across all 16 inputs, normalized OpenDataLoader outputs had 13 validator passes and three failures. Accesspdf had six passes and ten failures. Each engine passed the implemented preservation comparison on 14 inputs and failed it on both books. These totals include negative and detection-only controls; they are not success rates on a representative population of readings.

For the synthetic book, OpenDataLoader's raw output failed eight rules; normalization reduced that to zero. Accesspdf went from seven to six. For the published book, OpenDataLoader went from nine to one, with nine failed assertions remaining under rule 7.21.7, test 1. Accesspdf went from seven to six, with 10,088 failed assertions remaining. Catalog improvements therefore do not resolve either engine's book blockers.

### OpenDataLoader findings

The synthetic book kept its text tokens and existing navigation, but **173 of 200 pages had nonzero pixel differences**. The differences were often small and remain failures under the declared exact threshold; the evaluation did not silently increase the tolerance to make the engine pass.

The published book changed rendering on **three pages**. On PDF page 119, labels in a stack diagram visibly moved relative to their boxes. This is a substantive diagram change, not simply a metadata difference. Five pages also joined previously separate word boundaries during text extraction; the non-whitespace character sequences remained the same. The comparison retains those token differences rather than describing them as deleted letters.

Independent structure inspection found **1,731 declared MCID references targeting absent marked-content sequences across 103 pages**. Another 21,373 references resolved, and all 2,351 annotation-object targets existed. The tree is partially unresolved; it is not an entirely phantom tree. The validator's remaining failure was a font/Unicode rule, so the independent reverse-link check found a defect that the validator report did not identify.

Figure-description meaning and reading order remain unverified. The synthetic cross-page table was represented as separate tables, which needs semantic review even when machine validation passes.

### Accesspdf findings

Accesspdf preserved the rendered pixels and extracted text of both books. Its preservation failures concern changes to existing bookmark navigation, rather than visible page loss.

The supplemental inspector counted **531 of 6,228 paint operations uncovered by tags or artifacts in the synthetic book**, and **2,973 of 19,840 in the published book**. These counts are operation-level evidence, not percentages of meaningful document content. The books also had unresolved link-tagging and figure-description issues. The synthetic cross-page table was again split into separate table elements.

### Runtime observations

| Book | OpenDataLoader engine time | Accesspdf engine time | OpenDataLoader peak observed process-tree memory | Accesspdf peak observed process-tree memory |
|---|---:|---:|---:|---:|
| Synthetic, 200 pages | 2.5 s | 121.7 s | 1,446 MiB | 135 MiB |
| Published, 244 pages | 7.0 s | 29.9 s | 1,613 MiB | 155 MiB |

These are one-run engine observations on this computer, excluding validation and fidelity assessment. Startup, caching, document differences, concurrent evaluation work, and sampled memory affect them. They support planning further measurements, not performance guarantees or a universal speed ranking.

## Feasibility experiments

### Header and footer artifacts

A three-page, fully tagged control contained repeated header/footer text and the same phrase as meaningful body content. Six explicitly selected furniture occurrences became pagination artifacts. Their obsolete structure references and empty containers were removed, and ParentTree entries were updated. Meaningful body occurrences remained linked.

Both the original and changed control passed the strict validator. All three pages retained exactly the same pixels, extracted text, and navigation. A shared Form reused in both furniture and body contexts was explicitly refused without output or input changes.

**Result:** bounded artifact surgery is feasible with exact decisions and supported structures. Automatic detection and safe treatment of arbitrary shared resources remain unproven. The result supports a narrowly scoped processor, not general book artifacting.

### Fonts and Unicode mappings

A controlled missing-font derivative failed the embedding rule. Restoring only the exact original, permitted 28,108-byte font program and its recorded stream properties produced a strict validator pass and an exact match to the authoritative reference.

Restoration changed approximately 0.793% of pixels relative to the deficient input because the renderer had been using a fallback font. That change is recorded explicitly; it is not called preservation of the deficient appearance.

A second control contained a syntactically valid but deliberately wrong Unicode mapping. It passed veraPDF despite wrong extracted text. Restoring the exact authoritative map corrected the text without changing any pixels. Arbitrary font substitution and guessed mappings remain unsupported. The published book's rule 7.21.7 failure has not been repaired.

**Result:** exact-source repairs are feasible. There is no evidence for general automatic font repair without authoritative resources and a defined correction policy.

### Native Windows OCR

The successful route uses unchanged OCRmyPDF and Tesseract packages with project-local temporary directories, ordinary PDF output, optimization disabled, and no force OCR. Initial failures in the sandbox's default temporary directory remain documented; a compatibility wrapper did not solve those failures and was unnecessary once the temporary location changed.

| Route | Observed result |
|---|---|
| Image-only page, skip text pages | Scan text recovered; visible pixels preserved exactly |
| Mixed digital/scanned page, skip | Successful process exit, but scan text omitted |
| Mixed digital/scanned page, redo | Scan text recovered, existing digital text retained, visible pixels preserved exactly |
| Already tagged digital control, skip | Existing content and structure retained in the measured scope |

OCR intentionally adds selectable text, so the generic no-added-text comparison remains a difference. OCR-specific evidence separately verifies retained digital text, expected added scan text, and exact visible preservation. Mixed-page redo still requires semantic reading-order review. These clean one-page fixtures do not establish accuracy on difficult scans or long scanned books.

## Trust checks and corrections

The synthetic tagged positive control passed all 106 tested rules with zero failed assertions. Empty and incomplete tag controls failed the relevant checks. Deliberate content loss and wrong text mappings were detected against their authoritative references. An already-corrupted input passing against itself is not evidence that a tagger restored the missing or incorrect content.

**Forty automated regression tests passed** across the independent metrics and validator adapters. Tests cover content linkage, partial and phantom trees, named properties, Forms, preservation failures, valid additions, annotation enrichment, malformed reports, wrong profiles, count contradictions, and partial failure details.

Two measurement corrections were applied transparently. The initial comparison was too strict about valid added navigation and empty annotation descriptions; the corrected measurements retain existing meaning and report additions separately. The inspector also now distinguishes a partially unresolved tree from a completely phantom tree. Original reports are retained alongside corrected evidence. Rendering thresholds were not relaxed.

The pinned validator internally limits individual failure-detail records after approximately 10,000 results even with unlimited report flags, while aggregate failed-check totals continue. Five affected summaries were reparsed as noncompliant failures with explicit partial-detail coverage. Their old summaries and raw reports remain available. No missing details became a pass, and no engine was rerun to obtain a better result.

## Recommended next work

1. Isolate the OpenDataLoader diagram, small-rendering-difference, joined-word-boundary, and dangling-reference regressions. Test bounded configuration or upstream fixes against the same controls and both complete books.
2. Keep strict preservation rejection. Do not mask the diagram change by increasing a global pixel tolerance.
3. Retain the narrow metadata, exact-decision artifact, and exact-source font experiments as evidence. Promote a processor only after its supported structures and refusal cases are defined.
4. Expand the permitted real-document sample and include human reading-order, description, and table checks before choosing a book default. No the LMS checker score or screen-reader release check was performed in Phase 0.
5. Reconsider Phase 1 only when predeclared basic reading, chapter, and substantial-book cases can reach the planned gates. Until then, treat OpenDataLoader as the leading investigation target, not a validated default for unattended book remediation.

The comparison, raw/normalized outputs, original fingerprints, dependency locks, full available validator reports, all-page measurements, corruption controls, and experiment records are saved under this evaluation directory. The command-line product, assisted judgment layer, and local review application have not been implemented.
