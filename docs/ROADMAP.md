# PDF Remediator Revised Plan

**Revision 0.7: current status reconciled with the development checklist**
**Updated for Jason Wrench on October 17, 2026**

For current completed work and remaining tasks, use [STATUS.md](STATUS.md). The
phase descriptions below retain their historical implementation scope; they do
not imply broad native qualification or completed accessibility acceptance. The
one-page Windows visual/clipboard pilot is complete; the rest of Phase 3 remains
pending. AI/OCR remain off for current development. Cloud-provider proposals in
this plan are future scope, not enabled features or current work authorization.

Build a local program that produces PDFs ready for an accessibility review, with evidence showing what changed, what passed automated checks, and what still needs a person. Start by proving that an existing tagging engine can preserve and improve representative book content. Keep the engine replaceable.

This revision preserves the supplied specification's local workflow, focus on books, separate outputs, and human review. It replaces the success criteria and development sequence below. Phases 0 and 1 are complete. At Jason's request, Phase 2 now combines the remaining preservation repair, local review interface, grouped reviews, and focused AI assistance. Testing with actual users and the LMS checker follows in Phase 3. Other proposed defaults remain recommendations where they have not been explicitly confirmed.

## 1 Proposed product baseline

| Topic | Proposed baseline |
|---|---|
| First supported platform | Windows. Keep the implementation portable; claim macOS or Linux support only after running the release checks there. |
| Primary documents | Born-digital course readings, chapters, and whole books. Include a 200-page book fixture in the first evaluation. |
| Initial interface | A command line interface for development, followed by an accessible local review interface. |
| Engine strategy | Compare existing engines first. OpenDataLoader is the leading candidate, pending evidence on books. |
| AI | Off in the first build. Later, support a local model and explicitly configured cloud providers. |
| AI application policy | Offer manual drafts with per-item acceptance and an optional document-level Auto-fix mode, as requested on October 16. Auto-fix may apply bounded best guesses without individual acceptance; record machine authority, context, and model origin separately from human approval. Neither mode grants human verification. |
| LMS checker workflow | Record the actual score from the LMS checker. Recommend High, 67–99%, as the initial workflow threshold and 100% as the target. The threshold affects human verification, not automated candidacy. |
| Name | Keep PDF Remediator as a working name. Naming does not block evaluation. |

The LMS checker's own documentation describes 100% as no issues identified and says further improvements may still be possible. Its score is a workflow measure, not a substitute for semantic review.

The first implementation does not promise automatic repair of complex tables, equations, forms, arbitrary font problems, or badly damaged files. Detect these cases and explain the next step. Retain them in evaluation so that limitations remain visible.

## 2 Evidence and historical results

The supplied RESEARCH.md reports five small-file experiments. Retain those numbers as historical observations attributed to that document. Reproduction requires the original input and output files, exact commands, package versions, normalization script, validator runner, and validation profile. The attached README describes helper scripts; those scripts were not among the three supplied files.

The research includes session dates of October 16, 2026, while this review uses the client's October 15 date. Preserve that source dating and establish provenance when recovering the earlier artifacts; do not relabel the earlier runs as newly reproduced results.

OpenDataLoader's official documentation distinguishes free Tagged PDF generation from enterprise PDF/UA export. The reported five-file metadata experiment does not establish what the enterprise exporter does, or that equivalent results are achievable on books. Treat “free engine plus bounded repairs is sufficient” as the hypothesis to test. [OpenDataLoader documentation](https://github.com/opendataloader-project/opendataloader-pdf/blob/main/README.md)

A future evaluator may recover the repository and branch identified in the supplied spec after verifying that they contain the relevant work. Commands embedded in the attachments describe that earlier workflow; they are not part of the current review request.

## 3 Results and release rules

Store four separate assessments: validator result, supplemental checks, fidelity, and human review. Never combine them into a predicted LMS checker percentage or a general compliance score.

### Automated validator result

Use a pinned veraPDF release and its explicit PDF/UA-1 profile. Preserve the complete machine-readable report, selected profile, process result, version, and rule/assertion counts. A pass requires successful completion and zero failed rules. Missing reports, timeouts, parser errors, and unavailable validators are errors or not-run results.

Exceptions may be recorded with reasons, but a failed rule remains a failure. veraPDF performs the machine-verifiable part of PDF/UA validation; it does not determine whether descriptions or reading order convey the right meaning. [veraPDF validation scope](https://docs.verapdf.org/validation/)

### Supplemental automated checks

Replace the “LMS checker and WCAG proxy gate” label with “supplemental automated checks.” Each check records its evidence, applicability, severity, and one of `pass`, `fail`, `needs-review`, `not-tested`, `not-applicable`, or `error`. Publish a coverage matrix relating checks to selected WCAG 2.1 AA criteria. The matrix must also show criteria requiring human assessment or outside this tool's coverage. Evaluation tools require human judgment; this set of checks is not a complete WCAG assessment. [W3C evaluation guidance](https://www.w3.org/WAI/test-evaluate/tools/selecting/)

| Check group | Required behavior |
|---|---|
| Content linkage and coverage | Resolve structure elements, marked-content references, parent mappings, and relevant annotation/object references. Measure uncovered content per page. One valid link does not establish that a page is fully tagged. |
| Metadata | Check a meaningful title, document-title display, appropriate language, and export metadata. A PDF/UA identifier is a declaration to validate, not evidence that a repair succeeded. |
| Headings and navigation | Check role resolution, structural anomalies, and bookmarks for long documents. Flag questionable hierarchy; do not invent headings from page count alone. |
| Figures | Inventory meaningful figures and artifacts. Flag missing alternatives and obvious placeholders. Length limits and filename patterns are review signals; adequacy depends on context. |
| Tables and lists | Check nesting, spans, and header associations. Support valid Scope or Headers/ID mechanisms rather than assigning Scope mechanically to every header. |
| Text and fonts | Check embedding, glyph coverage, and valid Unicode mapping mechanisms. The absence of a ToUnicode entry alone does not prove failure. |
| Page content | Distinguish blank/decorative pages, scans, digital text, and pages containing both digital and scanned text. |
| Links | Check structural linkage and description signals. Flag questionable text for review. |
| Contrast and reading order | Report the regions actually assessed and ambiguous regions. Geometric order and rendered color sampling are screening methods, not semantic proof. |

PDF/UA rule details distinguish content coverage, table-header mechanisms, and font mapping requirements. Match implementation checks to the applicable rules instead of using object-count shortcuts. [veraPDF PDF/UA-1 rules](https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFUA-Part-1-rules/)

Before an evaluation run, declare which automated checks are blocking and which findings require human assessment. An unresolved blocking check, including `error` or `not-tested`, prevents candidacy. Human-only judgments remain visibly pending. Check coverage must never expand implicitly when reporting a pass.

### Fidelity assessment

Preserve page count, dimensions, visible content, logical page labels, existing navigation, and usable annotations unless a selected operation explicitly changes them. Compare normalized text content separately from reading order so that a legitimate ordering improvement is not mistaken for text loss.

Render every page of the release artifact against the input with the same pinned renderer, resolution, and color settings. Report differences and affected regions; tolerate only measured rendering noise under thresholds established in Phase 0. Sampling may accelerate development but cannot be reported as complete verification.

OCR pages still require automated visible-content comparison. Recognition accuracy and completeness remain explicit human-review items checked against the scan; they are not implied by an automated fidelity pass. Record any permitted processing changes separately.

### Product statuses

| Status | Meaning and output policy |
|---|---|
| `failed` | Processing failed, structure integrity is broken, or a phantom tree was produced. Publish the failure report; do not publish that PDF as a usable result. |
| `needs-manual` | A blocker, unsupported case, or unresolved required automated assessment remains. Publish reasons and repair paths. A structurally intact draft may be retained only in a clearly labeled review area. |
| `candidate` | The strict validator, required supplemental automated checks, and fidelity checks pass. The review packet lists pending human judgments, including any applied AI drafts. |
| `verified` | The exact candidate PDF has a recorded LMS checker score meeting the selected threshold, a named reviewer and date, and all required human-review items completed without unresolved blockers. |

Tie all assessments and approvals to the final PDF's SHA-256 hash. Any change to that file invalidates its previous verification. Keep the actual LMS checker score and institutional context in the record. No status authorizes a certification or a claim of complete WCAG conformance.

A confirmed semantic blocker found during review moves a candidate to `needs-manual`. A blocker discovered after verification invalidates the current verified status while preserving the dated historical record. Use `failed` for processing or integrity failures, rather than for every adverse human finding.

Human review covers alt-text meaning, table relationships, heading purpose, artifact decisions, reading order, and OCR accuracy where applicable. Record the scope of listening/assistive-technology checks and sampled pages. W3C's PDF reading-order technique includes testing through a screen reader or accessibility interface. [W3C PDF reading order](https://www.w3.org/WAI/WCAG21/Techniques/pdf/PDF3.html)

## 4 Processing and preservation

The pipeline is intake, baseline measurement, optional OCR, selected tag engine, proven deterministic processors, staged output, validation, fidelity comparison, and report publication. No model writes PDF objects. Preserve usable existing tags; retagging requires a documented reason and an output comparison.

Classify each page and record document-level features. Detect malformed, encrypted, signed, and unsupported-version inputs before mutation. Signed inputs require a separately selected derivative workflow; do not silently invalidate signatures. Identify forms, attachments, equations, and other unsupported features, and explain whether they block the run or require preservation review. Never obtain or bypass a password automatically.

Each modifying stage works on a checkpoint. Roll back a failed processor. Integrity failures stop PDF publication; optional processor failures may become warnings only when the report and release policy permit it. A broad exception handler must not conceal a failed required operation.

Use independent files or whole-document checkpoints for long runs until splitting and merging are proven to preserve structure, destinations, shared resources, and page labels. Chunk extraction and model requests where useful; do not assume independently tagged page chunks can be merged safely.

Publish the PDF, report, sidecar, and manifest as one completed run bundle. Stage them on the destination filesystem and make the bundle visible only after its checks and final hashes are complete. Keep diagnostic drafts separate. Prevent filename collisions, traversal outside the selected output directory, and recursive ingestion of output folders.

Bound subprocess time, memory, repair attempts, and retries. Support cancellation and record interrupted stages. Resume only from checkpoints whose input, configuration, tool versions, and decision hashes still match. Reproducibility means matching content and recorded decisions under a pinned environment; byte identity requires a separate deterministic-export test.

## 5 Difficult repairs

### Running headers and artifacts

First test whether the chosen engine already handles running furniture correctly. If custom changes are needed, prototype them on a small tagged fixture before attempting a book. Test shared Form XObjects, repeated images, alternating headers, chapter-opening pages, footnotes, and repeated text that is meaningful content.

A successful prototype must update content marking and associated structure references, preserve all real text and appearance, and introduce no integrity or validator regression. Position and repetition identify candidates; they do not justify removing semantic content. If those criteria cannot be met, route affected files to manual review and revise the engineering estimate.

### Fonts

Include font diagnostics in Phase 0 and the initial release. Separate embedding, glyph coverage, widths, and character mapping. Implement a repair only when the exact font or authoritative mapping is available, permitted for the intended use, and preservation checks succeed. Never guess character mappings or substitute fonts solely to clear validation. Uncertain font problems remain explicit blockers with a source-document repair path.

### OCR

Evaluate OCR separately from tagging so each engine receives the same prepared input. Page-level skip mode can miss scanned text on a page that also contains selectable text. Force mode rasterizes content; it must be a separately selected recovery operation with explicit consequences, never an automatic response to tagging failure. OCR output options can affect the entire document and its existing structure. [OCRmyPDF processing and structure behavior](https://ocrmypdf.readthedocs.io/en/latest/advanced.html)

Test ordinary PDF output with optimization disabled as a preservation-oriented baseline, using flags supported by the pinned release. Compare it with the input rather than promising unchanged digital pages. Record every page processed, OCR language, recognition failure, and review requirement. [OCRmyPDF selected-page guidance](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html#process-only-certain-pages)

## 6 Dependencies and installation

Inventory before installing. Record resolved executable paths, versions, smoke-test results, and optional capabilities. Set timeouts on every probe. A program present on PATH is not proof that it works or that the selected engine uses the intended runtime.

Use separate pinned environments for the evaluator, OCR, and competing engines. They exchange PDFs and structured reports. Accesspdf's published project declaration constrains pikepdf below version 10, while current OCRmyPDF installation documentation requires a newer pikepdf. Resolve exact release dependencies independently before a run. [Accesspdf dependency declaration](https://raw.githubusercontent.com/laurenaulet/accesspdf/master/pyproject.toml), [OCRmyPDF installation requirements](https://ocrmypdf.readthedocs.io/en/latest/installation.html#requirements-for-uv-and-source-installs)

Choose required native components from the tested OCR release and backend. Current OCRmyPDF documentation includes native Windows support and treats Ghostscript as recommended or required for particular conversions, rather than universally mandatory. [OCRmyPDF Windows installation](https://ocrmypdf.readthedocs.io/en/latest/installation.html#native-windows)

Use the standalone veraPDF CLI as the evaluation baseline. A bundled-core fallback is a separately named diagnostic configuration until its profiles and reports are compared against that baseline. Do not assume different validator builds produce interchangeable counts.

Pin exact engine and dependency versions. Record source locations, applicable licenses, notices, and redistribution status. Keep any proprietary tagging SDK optional and verify that the user's license covers the intended evaluation or deployment; absence of a watermark proves nothing about permission.

## 7 Revised development sequence

Phases 0, 1, and 2 are complete; their evidence remains in the project. [Phase 2 results](../eval/PHASE2-RESULTS.md) record the preservation repair, local review interface, occurrence-bound grouping, optional local AI drafts, and release checks. Phase 3 has only the limited owner Windows visual/clipboard pilot completed. Broader actual-user studies, external assistive-technology acceptance testing, and LMS checker testing remain pending. Internal software checks do not substitute for that acceptance work, and no Phase 2 output has received verified status.

### Phase 0 Establish feasibility

1. Recover available historical fixtures and scripts, identify the correct repository state, and record missing evidence. Do not make recovery a prerequisite for independently generated tests.
2. Publish a dependency inventory and isolated environment manifest. Smoke-test the selected Java, renderer, validator, and each available engine. Separate “missing,” “failed,” “unsupported,” and “not evaluated.”
3. Define the report schema, check coverage, preservation thresholds, and engine-selection rules before scoring outputs.
4. Build small fixtures with known content and structure, a deterministic 200-page book, and representative permitted real-book excerpts when available.
5. Compare OpenDataLoader and accesspdf. Include a proprietary tagging SDK only when appropriate licensing is established. Keep cloud engines outside the default trial.
6. Score raw outputs and outputs after the same bounded normalization step separately. Preserve both reports. Run artifact, font, and OCR preservation experiments as independent tracks.
7. Produce a results table, failure examples, runtime/resource measurements, and a supported-case recommendation. State whether an existing engine is sufficient, whether bounded repairs are viable, and whether writing our own tagging engine needs a separate investigation.

**Exit:** reproducible evidence and an explicit go/no-go decision. Choose an engine only if it preserves all content on its proposed supported cases, produces no phantom trees, and has a credible path through strict machine validation and manual review. An engine may have documented unsupported cases; it cannot win by silently omitting them. A synthetic book alone supports only a provisional recommendation until representative real material is tested.

### Phase 1 Build the smallest useful local workflow

Implement `doctor`, read-only `check`, single-file `fix`, and controlled batch runs with one chosen engine. Include page-aware intake, the proven metadata/structural processors, strict validation, complete automated fidelity assessment, transactional output, cancellation/resume, a basic HTML review packet, editable sidecar, and a verification ledger. Apply explicit reviewer-supplied title, language, and figure-description decisions through the sidecar without requiring an AI provider.

OCR is included only for the routes proven in Phase 0; other scan cases receive an actionable result. Add only structural or font repairs that passed their independent preservation experiments. Keep unproven cases in the manual queue.

**Exit:** predeclared core cases—a simple reading, a structured chapter, and a representative substantial born-digital book—actually reach strict `candidate` status using the supported processing and any explicitly recorded reviewer decisions. Producing only manual-work reports is insufficient. Every other fixture has its expected documented outcome, including deliberate failures. Originals remain unchanged. No broken or phantom output is released. A full book completes within measured resource limits. Reports distinguish pending human work from passed automation.

### Phase 2 Improve preservation and build the review workflow

1. **Fix the remaining book-preservation failure.** Isolate the synthetic book's contents-page problem, implement a bounded repair, and add regression cases for the same pattern. Preserve the exact comparison thresholds and rerun both complete books and refusal controls.
2. **Build the local review interface.** Put the original page, proposed result, surrounding context, explanation, and approval controls together. Support file selection, clear blocker explanations, editable figure descriptions, and batch triage. Build keyboard access and accessible interface structure into the implementation. Prepare Windows setup, a reliable launch path, and operating instructions for the later pilot.
3. **Make repetitive reviews manageable.** Group similar mechanical repairs and highlight exceptions while retaining every occurrence, page, evidence record, and approval binding. Preserve separate decisions when the same image or repair pattern has different context. A group display must not silently approve its members or remove unresolved issues.
4. **Add focused AI assistance.** Implement the provider interface and a local endpoint first. Begin with context-aware figure descriptions and title suggestions; add heading suggestions only after testing their structured decisions and deterministic application. Optional cloud providers retain explicit provider/data/budget authorization. Suggestions remain editable and attributable. Manual mode requires per-item acceptance; the optional Auto-fix extension below permits application under explicit document-level authorization. Human edits win while their relevant input remains unchanged.

Internal checks cover the interface, seeded review defects, grouping completeness, stale approvals, cache invalidation, conflicting edits, provider failures, local-only execution, and accepted-decision reapplication. Measure displayed review groups separately from unresolved occurrences. Actual-user testing and LMS checker uploads are not Phase 2 activities.

**October 16 Auto-fix extension:** At Jason's request, add an optional mode that applies supported best guesses without hundreds of individual approvals. Automatically handled mechanical occurrences move out of the main action queue, with their identities and evidence retained in a detailed view and export. Local AI title/figure choices may be applied under explicit document-level authorization. Protect saved human edits and confirmed blockers, rerun the release gates, keep prior results unchanged, and preserve separate human-verification requirements. This supersedes mandatory per-item acceptance only for the explicitly chosen automatic mode; manual review remains available. Record the extension separately from the historical Phase 2 release evidence.

**Exit:** the synthetic book preserves every page under the existing exact policy; existing core automated gates and refusal controls still pass. The local interface supports the complete review workflow on controlled fixtures. Every grouped occurrence remains traceable and approval-bound. Every AI decision is attributable, editable, and reviewable; unapproved suggestions are not applied. No external connection occurs in local-only mode, and credentials are absent from artifacts and logs. A Windows pilot build and instructions are ready. Outputs remain candidates with pending human verification; Phase 2 completion does not grant verified status.

### Phase 3 Test with actual users and the LMS checker

Run a pilot with nontechnical users on the prepared Windows workflow. Observe setup, file selection, processing, blocker interpretation, grouped reviews, description editing, and approval. Measure task completion, review time, missed seeded defects, and unresolved issues. Check the interface with keyboard and screen-reader users and test representative output PDFs, including a substantial chapter, for reading order, lists, links, tables, figures, and character meaning.

After the development work is ready, validate a release sample in the LMS and record actual LMS checker feedback against the exact final PDF hashes. Compare original and processed results and preserve the reviewer, date, institutional context, and review scope. Resolve confirmed blockers and repeat the affected tests. LMS uploads remain the user's action unless separately authorized.

**Exit:** a nontechnical user can set up, process a supported document, understand the review queue, and complete the documented review workflow. The pilot records actual-user findings, assistive-technology results, review effort, and actual LMS checker feedback. A file becomes verified only when its exact candidate hash meets the existing LMS checker threshold and all required human checks are completed without unresolved blockers. Other platforms, proprietary integrations, and advanced document types require their own evidence and support commitments.

## 8 Evaluation corpus and measurements

The corpus must include simple text; headings and nested lists; simple and complex tables; multi-column text and footnotes; figures with captions and repeated assets in different contexts; valid tags and deliberately incomplete tags; unembedded/mis-mapped fonts; scans; mixed pages; and detection-only forms, slides, and equations. Include blank pages and a deliberate content-loss output to prove the evaluator rejects it.

The synthetic book must exercise chapter openings, alternating running headers, page numbers, bookmarks, logical page labels, a table crossing pages, notes, illustrations, a contents section, and an index. Give each fixture expected content, expected structural relationships, and expected blockers. Keep private PDFs outside the repository; record provenance and redistribution permission for shared fixtures.

For each engine/configuration record input/output hashes, validator failed rules and assertions, per-page content coverage, structural errors, supplemental checks, text/render differences, preservation of navigation, wall time, throughput, peak memory, and output size. Record failures and unavailable engines in the comparison. More tags or fewer rule failures alone do not establish better accessibility.

Check the evaluator using known-good files and deliberately corrupted variants. Test processor rollback, interrupted publication, malformed sidecars, stale caches, batch isolation, collision-safe naming, and preservation of existing usable tags. Change numeric thresholds only with a recorded reason and rerun the comparison affected by that change.

## 9 AI decisions and privacy

Default to no provider and no paid calls. Selecting a cloud provider requires a data-sending summary and an estimated budget covering the proposed run, with bounded retries and spend. Stored run authorization supports unattended processing within that scope. A generic yes flag must not silently authorize a different provider, whole-document upload, or destructive recovery operation.

Local-only mode permits only the selected loopback service and blocks external requests, redirects, telemetry, and automatic model downloads during processing. Prepare model files separately and verify offline readiness. Treat document text and model outputs as untrusted data; validate decisions against a schema and allowable object references.

Keep credentials in environment variables or an OS credential store. Use allowlisted logging and reports; do not serialize secrets or raw authenticated requests. Reports disclose the provider, model, decision categories, item counts, and amounts of content sent without reproducing sensitive snippets unnecessarily. Review HTML must escape document/model text and render without executing embedded document content.

Use an asset hash to identify image bytes and a separate occurrence/context key to identify the decision. Cache keys include relevant text, image crop, document context, prompt/schema versions, model/settings, and processing options. An identical logo under another caption may need a different description. Human approval survives only while the decision's relevant inputs match.

## 10 Interfaces and evidence bundle

Retain the proposed commands: `doctor`, `check`, `fix`, `review`, `engines`, and `ledger add|list|export`. `check` never modifies the input; any requested reports go to an explicit output location. `dry-run` estimates work without modifying PDFs, invoking providers, transmitting document content, or downloading resources.

A completed run directory contains the candidate PDF, report JSON, HTML review packet, editable decision sidecar, manifest, and full validator report. Use `candidate.pdf` for a successful automated result and a separate review area for intact drafts requiring manual work. Keep completion records and caches outside the input tree.

The report includes schema/tool versions, all tool/runtime versions, profile/config hashes, source/output hashes, classification per page, selected and skipped stages, processor outcomes, OCR pages, each assessment's coverage and result, residual issues and repair paths, human-review queue, data-sent summary, and timings. Record validator rules as fixed, remaining, or newly failing against the baseline, without discarding their original identifiers.

The ledger includes final PDF hash, run identifier, reviewer/date, actual LMS checker score and context, selected threshold, human-review completion, review scope, and notes. Configuration selects language, engine, privacy mode, review policy, and check profile; it contains no API key. Do not overwrite existing language, title, alt text, or human decisions with generic defaults.

## 11 Decisions left for the product owner

The following recommendations keep evaluation moving without treating them as confirmed product requirements: Windows first; High as the initial LMS checker workflow threshold; draft AI application with explicit review; manual LMS checker entry first; PDF Remediator as the working name. None needs to delay the initial no-AI feasibility comparison.

The next acceptance milestone is the remaining Phase 3 testing with actual users, assistive technology and the LMS checker. See the current checklist for independent development and machine-dependent work. Phase 2 is complete under the exit criteria above, as documented in its results report. This completion update preserves the user's sequencing decision; it does not enable cloud processing, authorize LMS uploads, or expand supported document types.

## 12 Version 2.0: a stand-alone program window

Done early, on 12 November 2026 (0.3.0 alpha 5): PDF Remediator has its own program window, drawn by the web view built into Windows, so nothing from a browser shows. Until then the launcher showed the page in a plain browser window with a separate profile (decided by the owner on 1 November 2026 as a stopgap). Still to do: run the screen-reader and keyboard checks again on the new window.
