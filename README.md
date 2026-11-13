# PDF Remediator

[Roadmap & Feature Requests](https://app.productbridge.io/widget/784db895-cb64-45f4-9bde-4645df4aa083?tab=roadmap)

A local helper that drafts accessibility repairs for PDFs (reading structure, tags, text for scanned pages) and lists what a person still has to check.
Your original PDF is never changed, nothing is sent to the cloud, and nothing it produces is called "verified accessible": every result is a draft for a person to review.

* **What it does and does not do:** [docs/WHAT-IT-DOES-AND-DOES-NOT-DO.md](docs/WHAT-IT-DOES-AND-DOES-NOT-DO.md)
* **Install it on Windows:** download `PDF-Remediator-Setup.exe` from [Releases](https://github.com/jasonswrench-beep/PDFRemediator/releases) and run it. It installs like any Windows program, for your Windows account only (no administrator rights), into `AppData\Local\PDF Remediator`, and appears in Settings > Apps with an uninstaller. English OCR for scanned pages is included, and optional AI help needs a local model program you install yourself. To run it from the source code instead: [START-HERE.md](START-HERE.md) and [docs/WINDOWS-DISTRIBUTION.md](docs/WINDOWS-DISTRIBUTION.md).
* **What the window is:** PDF Remediator opens in its own program window, like the other OpenStage-family programs. Its screens are drawn by Microsoft's WebView2, which is part of Windows; no browser window is opened. Closing the window stops the program. Nothing is sent over the internet.
* **Options in the app and on the command line:** [docs/REPAIR-OPTIONS.md](docs/REPAIR-OPTIONS.md)
* **PDFs with Content Credentials (C2PA labels):** [docs/C2PA-LABELS-POLICY.md](docs/C2PA-LABELS-POLICY.md)
* **Licence:** Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). Bundled third-party parts and their licences: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
* **Questions, bugs, and the written offer for the GPL-2.0 library that ships with the scan reader:** open an issue at https://github.com/jasonswrench-beep/PDFRemediator/issues
* **Before you open an issue:** issues are public. Please do not attach real documents, or paste text from them, if they hold anyone's personal or private information; describe the problem or use a document you are free to share.

Status: a work in progress. The sections below are the detailed development notes, newest first.

---

## Content Credentials: preserve the original and create a separate working copy

A new, explicit **Create separate copy without credentials and recheck** action handles one independently proven catalog-associated C2PA manifest. The unchanged original PDF, exact inert credential payload, named consent and removal proof are retained privately. The resulting working copy has a new source identity and does not carry the original Content Credentials or any old accessibility approval. The program does not verify the credential, its signer or its claims.

Ordinary Fix and OCR continue to protect credential-bearing originals. The separate-copy action requires exact current revision, original SHA, assessment context, an explicit checked removal choice and a reviewer name. It starts a new review with AI and OCR off. Changed, stale or unapplied choices cannot silently become removal consent. All pages, text, links and bookmarks must remain exact before the new copy enters ordinary remediation.

The initial scope is a single supported, unfiltered C2PA-associated file with no extra attachment, alias, signature, active action or unproved metadata claim. Other attachments remain guarded. Ordinary proven Link URI/local destinations are retained without execution. This producer's exact double-encoded MIME name and ordinary false IsMap flag are covered as explicit preserved cases. No generic attachment stripping, credential re-signing or authenticity claim is offered.

Consent and original-source lineage remain visible through recheck, supported Apply, reopen and export. Fresh required manual review remains pending; creating this copy does not prove accessibility. OCR-editor chaining on this new credential-derived lineage is explicitly refused until separately qualified; existing ordinary OCR editing retains its own scope.

Qualification and actual Windows outcomes are bound to the exact source freeze in the private validation packet content-credentials-20261028-01/qualification.json. Its full-suite, native-case and source-application receipts identify the tested bytes and actual results. The earlier dated sections below keep their original scope. The existing twelve external acceptance/development groups and visible-workflow, fresh-PC, human/assistive-technology/LMS, licensing, signing and release gates are not closed by this feature. Ask before opening the software or using the desktop.

---

## Current October 25 OCR omitted-word and character expansion

In **Document edits → OCR text corrections**, choose **Enable extended OCR
editing** to use the bundled correction font or add a missing word. Save and
explicitly accept every changed word, then **Create corrected copy and recheck**.
Earlier originals, PDFs, saved reviews and reported problems remain intact.
The new corrected source and result start fresh review requirements.

For an omitted word, choose an existing OCR word as the anchor, select Before
or After, enter one word, and specify its rectangle using percentages measured
from the top-left corner of the **Proposed result** picture. The outline follows
those keyboard-accessible values. Each insertion is horizontal in the preview;
qualified quarter-turn page rotations, cropped pages and nested Forms are
handled without rotating or rewriting the original page. Placement must stay
inside the page, avoid existing OCR words, and have a proven existing structure
owner. One insertion per anchor is supported per pass; replacing that same
anchor uses a separate pass. Save, accept, edit or remove an insertion explicitly.

Additional characters use the program's unchanged bundled Noto Sans font,
independent of OCR being enabled. Covered Latin accents, Greek, Cyrillic and
punctuation are supported. Unsupported characters, combining-mark sequences,
complex shaping and paragraphs remain refused. The original font and mappings
are preserved; a separate embedded font with verified Unicode and glyph mapping
serves the changed text. New words have explicit encoded word boundaries.
Inserted words remain editable in extended mode after reopening and later edits.

Checks retain exact untouched encoded and independently owned characters, order,
placement, all-page appearance, page geometry, navigation, annotation fields and
existing structure. Generated ASCII boundary spaces adjacent to an insertion
anchor are distinguished from original encoded/owned text. They do not permit
loss or alteration of old words or old encoded spaces. Accuracy, meaningful
reading order, table relationships and appropriateness of the chosen structure
owner still require human review. No accessibility approval is created.

The exact **164-file software source** passed **1,621 tests in 140.98s**,
with zero failures, errors or skips. All **211 browser-script checks** passed
and are included within one Python case, not added to that total. All 1,517
earlier test identities remain included, and collected/executed identities match.
The six documentation prefixes are a separately reviewed overlay.

Four retained OCR examples passed actual insertion, Unicode, placement, owner,
lineage, reopening and preservation checks, including the rotated/cropped mixed
example and a 20-page result. A real private Windows worker flow applied an
additional-character replacement and insertion, reopened both for editing, and
retained them through a later title edit. Originals and the earlier blocked
review/note remained unchanged. Both outputs passed fidelity; strict validation
failed initially on the existing missing title and passed after the title edit.
Supplemental failures remain, including the existing missing figure description.
No new strict or supplemental failed rule was introduced.

Four legacy inventories and all **12,374 occurrence contexts** match the previous
version exactly. An unchanged accepted v1 plan still applies and validates.
Existing v1 drafts can be applied or reverted before switching to extended
editing. The preexisting stale-note issue for older reviews without correction
lineage remains separate follow-up work. Earlier negative attempts are retained.

All work ran in isolated copies in the background, with AI off and no OCR
recognition rerun, software window, browser or desktop use. There are zero new
document/accessibility approvals. Actual-user, assistive-technology, LMS checker,
graphical, fresh-PC, distribution and release gates retain their separate scope.
The documentation .bat and older packaged payload remain unchanged. No merge
or release occurred; supported insertions are explicit transcription tools,
not automatic completion or semantic rehabilitation of the supplied folder.

The qualification authority is retained in the ignored development directory
'ocr-editor-expansion-20261025-01/qualification-02'. After guarded application,
its validation receipt is
'work/ocr-editor-expansion-20261025-01/source-application-01/source-application.json'.
No future receipt hash is invented here. **Prior-build text follows verbatim**;
earlier current labels and limitations retain their original build scope.
The master checklist keeps its existing completed credit and open acceptance
gates. Remaining editor work includes broader transcript/angle/shaping support
and user-authorized graphical/assistive-technology checks.

---

## Current October 25 in-program OCR text editor checkpoint

The first bounded OCR editor is implemented in the validation source. Under
**Document edits → OCR text corrections**, load a page's recognized words,
save a correction, explicitly accept each changed segment, and choose
**Create corrected copy and recheck**. The original PDF and previous saved
review stay intact. A separate corrected source and review are created; the
new review requires fresh human checks. The previous review remains available.

This first version changes supported invisible OCR words in completed local
OCR results, using characters already present in that segment's embedded font.
It does not yet insert omitted words, add new font characters, edit ordinary
visible document text, or provide a full transcript/reading-order editor.
Ambiguous, clipped, shared or unsupported text remains read-only with an
explanation. OCR corrections and other document edits use separate passes.
Changing a review's preparation settings cannot authorize old corrections.
The original, earlier result and correction evidence must remain available.

Corrections change the actual selectable text in a new PDF. Independent checks
compare literal Unicode, unchanged text/placement, all page pixels, geometry,
navigation and annotations. Later title/language edits retain corrected text.
Old notes and blocked review items are retained in this correction flow;
acceptance of a word does not approve OCR accuracy, order or accessibility.
The preexisting stale-note clearing behavior for older reviews without correction
lineage remains follow-up work; this checkpoint does not claim it is fixed.

The exact **160-file software source** passed **1,517 tests in 194.92s**, with
zero failures, errors or skips. All **168 browser-script checks** passed and
are included within one Python test, not added to that total. Collected and
executed identities match; all 1,403 earlier test identities remain included.
These six documentation prefixes are a separately reviewed overlay.

Background tests used an isolated private CPython 3.14.9 application copy.
Four actual OCR profiles passed mechanical correction/preservation checks.
A real application-worker flow changed one deliberately selected test word,
retained repeated neighbors and the old blocked note/review, and kept that
change through a later title edit. Both results passed fidelity checks.
The strict validator failed on the first result and passed after the title
edit; supplemental checks failed on both. Those diagnostics remain blockers.
The deliberately changed test word is not an accuracy-approved transcription.
There are zero new human approvals or verified accessible documents.

AI stayed off, recognition was not rerun, and no software window, browser or
desktop interaction occurred. Native keyboard, assistive-technology, actual-user,
LMS checker, fresh-PC, packaging and release acceptance retain their separate scope.
The retained documentation .bat and older packaged payload are unchanged and
do not automatically acquire this source feature. No merge or release occurred.

Qualified source and evidence are retained under the ignored development
directory 'ocr-text-editor-20261025-01'. After guarded integration, the application
authority is 'work/ocr-editor-20261025-01/source-application-01/source-application.json'.
Earlier application and negative-attempt records remain intact. This text does
not assign a hash to a future application record.

**Prior-build text follows verbatim.** Earlier “current” sections, counts and
editor omissions retain their original build scope. The master checklist keeps
its existing completed credit and open acceptance gates. Next editor work is
supported new characters and anchored omitted-word insertion, followed by broader
transcript/reading-order controls and user-authorized graphical validation.

---

## Current October 23 OCR omissions follow-up

The exact **155-file disposable software source**, prepared from the retained
151-file baseline, passed **1,403 software tests in 181.23s**
with zero failures, errors or skips. All **137 browser-script checks** passed;
they are included within one Python case and are not added to that total.
Collected and executed identities match. These six documentation overlays are
reviewed separately from the exact source that the software suite tested.

The new internal offline payload has **3,813 files**, including
**45 application files**. Private CPython 3.14.9,
the exact **8 core / 31 OCR dependency locks**, **138-file native OCR factory**,
official artwork and privacy defaults remain unchanged. OCR is off by default;
optional English OCR runs inside the program locally with AI off.

Actual local CLI checks covered the targeted **2 PDFs / 4 pages**
and then all **17 supplied PDFs / 162 pages**.
The target produced 2 review drafts; all 2 passed
the technical preservation checks. The folder produced 1 unapproved machine candidate, 16 review drafts;
all 17 passed those checks. Originals and saved reviews
were preserved. There are **zero verified accessible documents**.

Separate mechanical character/placement and encoded-word-boundary reviews
passed on both actual runs. These do not approve semantic reading order.
Each recorded **2 native rescue additions** and
**1 native case-confirmation replacement**,
with **0 lost earlier selected words** and
**0 unexplained literal changes**.
The reviewed cover comparison recovers small caption words and confirms publisher capitalization from whole native OCR records.
Source/final pixels remain identical and actual selected-character placement
stays within one PDF point of the retained native word geometry. Handwritten
year recognition, clipped-name letters, ambiguous case/punctuation, perspective,
completeness and meaningful reading order still require manual review.
The native text layer and final PDF both retain explicit Unicode spaces between
selected words, with the exact selected-word token sequence verified. This
corrects the observed joined-caption boundary; semantic reading order and
overall text accuracy still require manual review.
A built-in OCR word/transcript editor is still needed to correct uncertain
content entirely within the program. Review notes and descriptions do not
change recognized text; handwriting, clipping and reading order remain unapproved.

For wholly scanned covers, select **Scanned text → Add text only on wholly
scanned pages** and, when needed, **Scan layout → Tilted or vertical text**.
Existing page text remains excluded. Standard remains the default layout;
ruled-table limits are unchanged. Retry retains saved preparation settings;
changing mode/layout requires a separate result. Existing reviews are retained.

No graphical, fresh-PC, human/assistive-technology, LMS checker, distribution or release
gate closes here, and no master-checklist checkbox receives new acceptance.
The application authority will be written only after reviewed application at
`C:\Users\Jason\PDFRemediator-validation\work\ocr-omissions-20261023-01\source-application-01\source-application.json`.
This checkpoint does not claim that future receipt exists or invent its hash.

**Prior-build text follows verbatim.** Earlier sections, including earlier
“current” labels, test counts, omissions and negative attempts, keep their
original build scope. The existing master checklist keeps its completed credit
and open work; this follow-up creates no new approval or release clearance.

---

# PDF Remediator 0.3

## Current scanned-text update

The current source passed **1,305 software tests** and
its **137** browser-script checks. The updated
private program was also observed on all **17 supplied PDFs / 162 pages**.
Those runs produced **16 review drafts, 1 unapproved machine candidate**. These are reviewable technical
results with zero verified accessible documents. Earlier recorded results below
belong to their earlier builds. [Current status and remaining work](docs/STATUS.md)
keeps the full qualification and acceptance boundaries.

For a scanned cover in a document whose other pages already have text, choose
**Scanned text → Add text only on wholly scanned pages**. This adds text only
where the program proves the entire page has no existing text. Words pictured
on a page that already contains text still need another supported repair or
a better source.

For tilted titles or vertical lettering, choose **Scan layout → Tilted or
vertical text** with the wholly scanned-pages option. Recognition uses local
alternatives from the same engine. OCR runs inside the program; AI can stay
off. Keep OCR off for ordinary digital PDFs. Standard remains the default
layout; the separate ruled-table option remains available. The tilted/vertical
layout refuses the redo route and explains the supported choice.

The selected vertical cover word is recovered literally and its invisible text placement matches the source; existing text on other pages remains subject to separate review.

The full tilted title and publisher details are recovered, and the previously tilted publisher-word selection now aligns with the horizontal source; small-text omissions and a clipped-name error remain.

The developer comparison still leaves these review limits:

- A small angled caption and a handwritten year remain omitted from one scanned cover.
- A visible name prefix is misread, and source-clipped letters cannot be reconstructed reliably.
- Tilted lettering with changing character heights still needs placement review; capitalization, punctuation, complete OCR coverage and meaningful reading order remain unapproved.
- Existing text pages and the rest of the folder still require semantic, table, description, contrast and accessibility review.

Compare the result with the original word by word. More selectable text or
a passing validator does not establish complete rehabilitation. Check meaning,
reading order, figures and table relationships before using the result.

Change scanned-text mode or layout by processing the unchanged original as a
separate result. Retry keeps the saved settings and earlier review. Edits or
approvals from a different preparation cannot be adopted. OCR options and the
layout control are disabled if the local OCR component is unavailable. A logo
can receive a meaningful description in the usual figure-review workflow
without running OCR for it. Save a draft, review it and use the existing
acceptance and checked Apply steps. Real-user, assistive-technology and
authorized LMS checker checks remain separate.


A local Windows application and command line workflow for producing PDF accessibility **candidates** with strict validation, preservation evidence, and a review workspace. Originals remain unchanged. The core PDF workflow uses OpenDataLoader 2.5.13 and deterministic processors. Optional local AI can produce drafts for manual acceptance or apply best guesses under the explicit Auto-fix choice. AI is off by default; there is no cloud-provider integration.

For the browser workflow, begin with [START-HERE.md](START-HERE.md) and double-click **Start PDF Remediator.cmd** on the prepared Windows computer.

The supported workflow is deliberately bounded. A PDF/UA validator pass alone never establishes good descriptions, correct reading order, accurate mathematics, or complete WCAG conformance. See [Phase 0 results](eval/RESULTS.md) for the original engine failures and [the example configuration](remediator.example.toml) for runtime settings.

The [Phase 1 results](eval/PHASE1-RESULTS.md) record the completed reading, chapter and 244-page book candidates, the full corpus outcomes, and remaining limits.

The [Phase 2 results](eval/PHASE2-RESULTS.md) describe preservation repair, the local review interface, grouped reviews, focused AI assistance, and their limits. The [current development plan](docs/ROADMAP.md) places testing with actual users, the LMS checker, and assistive technologies in Phase 3. Internal software and UI checks do not constitute those user/LMS checker/assistive-technology trials.

See [current status and remaining work](docs/STATUS.md) for the support boundaries, completed evidence and open acceptance tasks. The [integration readiness review](docs/RELEASE-READINESS.md) consolidates the development diff and reproducible checks; it does not authorize a merge or release.

For checked updates to an existing editable source installation, see [local update instructions](docs/LOCAL-UPDATES.md). The updater checks by default and only replaces code when `--apply` is explicit.

For continued development from the private source backup, read [HANDOFF.md](HANDOFF.md). It documents the working scope, remaining work, run/test commands, and cloud setup. PDF inputs, private review state, local runtimes, and full raw evaluation evidence are intentionally excluded from Git; historical report links to those files refer to the prepared Windows workspace. A clean cloud checkout starts with the explicitly labeled portable contract tests.

## Scans and tables with visible grid lines

For an image-only scan on an OCR-equipped setup, open **Processing options**,
choose the appropriate **Scanned text** route, then choose **Scan layout → Tables
with visible grid lines** if ruled tables lose text under standard recognition.
Click **Process selected PDFs** to make a separate result. OCR runs locally
inside the program; English is the supported model and AI can remain off.

This option changes recognition only. Check every cell, number, description and
the surrounding text in the result, then check table relationships and reading
order. It cannot recreate content already cut off or unreadable in the source.
Keep OCR off for ordinary selectable-text PDFs; a logo alone does not need OCR.

To change scan layout, process the unchanged original in a **separate run**.
Reopening keeps saved edits. Retry uses the recorded scan layout and leaves the
earlier review intact; older reviews use standard recognition. A new profile does not reuse approvals
from a different preparation. **Save edit** still keeps a draft, and applying
accepted edits creates a separate checked PDF.

## Open the local review application

Double-click `Start PDF Remediator.cmd` to start or reopen the private local browser workspace. It uses the isolated application environment and a hidden local helper. Use **Stop application** in the workspace to stop that helper; simply closing the tab leaves it running.

The browser workflow supports choosing PDFs, bounded processing options, progress/cancellation, original/result page comparison, title/language and figure edits, reviewed heading/table controls, manual acceptance, optional Auto-fix, grouped review, local AI proposals, result downloads, and review-record export. **Save edit** retains a draft. **Accept this value** records a reviewed decision. **Apply accepted edits** produces a separate processing bundle and reruns validation and preservation checks. Changed result bytes require a new artifact review for human verification.

### Review heading, language, table and contrast findings

The tool now checks for missing headings on PDFs with at least three pages,
a first numbered heading above level 1, levels beyond H6 and skipped levels.
It also screens a supported set of document languages and measures contrast
for supported text regions. [Coverage and limits](docs/LMS-CHECK-APPLICABILITY.md)
explain what each finding establishes.

In **Document edits**, turn on **Show heading and table repairs on the previewed
page**. Compare the element's context with that page before choosing its heading
level, table cell purpose or header direction. Unsafe controls explain why they
are unavailable. The tool does not choose semantic roles for you or rebuild an
arbitrary table. **Save edit** keeps a draft; enter your name and **Accept this
value**, then use **Apply accepted edits** to make a separate checked result.

The language screen supports English, Spanish, French, German, Italian,
Portuguese and Dutch. Short, uncertain, mixed or unsupported text still needs
human review. A confident mismatch offers **Use … as a language draft**. That
copies a pending draft; review, acceptance and Apply remain separate actions.
Regional variants and every passage's pronunciation are not established by
the screen. Existing saved reviews keep their earlier decision inventory;
process the unchanged original separately to obtain current structure controls.

Contrast findings show measured ratios and page links for supported digital
text. For low ratios, they also suggest a black or white source text color and
show its computed ratio against the measured background. Review that advice,
its applicability (including logos or incidental text), and unmeasured content. For a confirmed problem, improve the authoring source's
colors or request an accessible replacement, export a separate PDF and process
it again. The tool does not recolor pages automatically. Required human review
remains even when the measured regions meet their thresholds.

### Auto-fix without hundreds of individual approvals

Open a document and choose **Auto-fix this document**. It creates a separate result, reruns the required automated checks, and automatically handles eligible repeated mechanical repairs. It records their exact occurrence, context, evidence, and machine disposition; it does not fabricate human approvals. A passing candidate can be downloaded without completing the individual review queue.

Expand **Include local AI guesses** if you also want pending titles and figure descriptions generated and applied without individually accepting each suggestion. Choose an installed local model and explicitly enable that option. For the tested automatic figure route, choose `qwen3.5:latest`, include crops, and select fast drafting mode. The smaller caption-only model may echo a placeholder; required gates still refuse that result. At most 24 eligible decisions are processed in batches of eight. Existing human edits, accepted values, and reported problems remain protected. Local AI failures are disclosed; missing or unsupported content can still prevent candidacy. No cloud connection or model download is added.

Automatic choices use a separate `auto-accepted` status and exact source/prepared/value/context authorization. The immutable result records the authorization and model origin. The default review list omits mechanical checks already handled automatically; **Include checks handled automatically** restores every occurrence. The raw required review inventory and the requirements for a separate human-verified ledger entry remain intact. Automatic mode does not claim correct semantic meaning or a measured LMS checker score. [Auto-fix results](eval/AUTO-FIX-RESULTS.md).

Grouped review keeps each occurrence's identity and context. Grouping is a navigation aid: only the explicitly selected, actually reviewed members receive a named reviewer's approval. Similar images, lists, or links do not acquire shared semantic approval automatically. A stale source, prepared checkpoint, output, or group membership prevents approval reuse.

**Export review records** writes bound sidecar/review files, including pending decisions and automatic dispositions where applicable. It does not modify a PDF or grant verification. In manual mode, AI proposals stay separate until a person adopts and accepts them. Automatic application requires the explicit document-level Auto-fix authorization instead.

The default workspace is `output/review-app`. To launch from PowerShell:

```powershell
$py = ".\.venvs\app\Scripts\python.exe"
& $py -m pdf_remediator launch
```

For a foreground service, a custom data directory/configuration, or an existing run import:

```powershell
& $py -m pdf_remediator serve --data-dir ".\output\review-app" --config ".\my-remediator.toml"
& $py -m pdf_remediator serve --import-bundle ".\output\readings\RUN-DIRECTORY"
```

`serve` binds only to the local computer, chooses an available port by default, and opens a private session. `--no-open` leaves browser opening to the caller; `--port` selects a local port. The desktop launcher reuses its running session. The application does not host a public website or require an external account.

## Start with the prepared local environment

Open PowerShell in this `pdf-remediator` directory:

```powershell
$py = ".\.venvs\app\Scripts\python.exe"
& $py -m pdf_remediator doctor
& $py -m pdf_remediator check ".\reading.pdf" -o ".\output\checks"
& $py -m pdf_remediator fix ".\reading.pdf" -o ".\output\readings" --title "The reading's actual title" --lang en-US
& $py -m pdf_remediator review ".\output\readings"
```

`doctor` probes resolved local paths and versions without installing anything. Inspect its `status`, component results, and `capabilities`; a startup probe is narrower than a complete processing test. `engines` reports the available local engine and its provisional status.

`check` reads the input and runs strict validation and supplemental checks. It does not apply repairs. Supply `-o` to keep its reports; without `-o`, reports exist only during the command and the printed summary contains no retained bundle. `fix` requires an output directory. `review` opens the generated HTML packet in the local browser; `--no-open` prints packet paths instead.

The installed entry point is also available as `.\.venvs\app\Scripts\remediator.exe`. Using the explicit Python path avoids depending on a global PATH setting.

## Recreate the application environment

`Setup PDF Remediator.cmd` prepares the isolated Python application using Python 3.11 and checks the local tools. It may download Python packages; it does not download AI models. The native tools and isolated engine/OCR environments must be present separately. This is a launcher/setup helper for a prepared computer, not a bundled native Windows installer.

When `local-runtime.toml` exists beside the setup helper, its readiness check uses that configuration, matching desktop startup. Without that file, setup uses the default runtime paths. An invalid existing configuration or unavailable required native tool makes setup report failure; it does not silently fall back to other tools.

The equivalent application-environment setup, with a trusted Python 3.11 installation, is:

```powershell
py -3.11 -m venv .venvs\app
& ".\.venvs\app\Scripts\python.exe" -m pip install -e ".[test]"
```

This setup step may download packages. The processing commands do not download dependencies. Do not merge the competing-engine and OCR environments: their dependency constraints differ.

| Component | Tested local location/configuration |
|---|---|
| Application | Python 3.11; dependencies pinned in `pyproject.toml` |
| Tagging | `.venvs/odl`, OpenDataLoader 2.5.13; its local CLI JAR is invoked directly |
| Validator | Standalone veraPDF 1.30.3 under `tools/verapdf`, explicit `ua1` profile |
| Java | An explicit `java_home`; this machine uses Temurin 25.0.3+9 |
| Optional OCR | `.venvs/ocr`, OCRmyPDF 17.13.0 |
| Optional recognition | `tools/tesseract`, Tesseract 5.5.3 and the local English model |

The existing isolated environments were prepared during Phase 0. For a new machine, provision the matching local distributions and then use `doctor` to inspect them. Dependency locks and installation evidence are under [eval/evidence](eval/evidence) and [the provenance notes](eval/provenance-note.md). Java 25 worked in this Windows evaluation but is outside the validator installation README's listed Java versions; this is observed compatibility, not a portability claim.

Copy `remediator.example.toml` to your own configuration file and set the paths that differ:

```toml
[runtime]
java_home = "C:/Program Files/Eclipse Adoptium/jdk-25.0.3.9-hotspot"
language = "en-US"
document_kind = "unknown"
ocr_mode = "off"
timeout_seconds = 600
validator_timeout_seconds = 180
memory_limit_bytes = 4294967296
java_heap_mb = 2048
preserve_painting = true
allow_tag_regrouping = false
repair_source_mappings = false
bookmark_min_pages = 20
```

Other configurable paths are `project_root`, `odl_jar`, `validator_cli`, `ocr_python`, and `tesseract_dir`. Relative paths in a TOML file resolve against that file's directory. Pass the same `--config .\my-remediator.toml` on subsequent processing commands. Configuration contains no credentials or provider keys.

## Understand the result

| Status | Meaning |
|---|---|
| `failed` | Processing or structural integrity failed. No usable PDF is published. |
| `needs-manual` | A required automated check, supported-case condition, or preservation check remains unresolved. An intact draft is retained only when its preservation checks pass. |
| `candidate` | Strict PDF/UA-1 validation, the declared automated profile, and complete preservation checks pass. Human judgments remain pending. |
| `verified` | A separate ledger record binds completed human review and an actual qualifying LMS checker score to the exact candidate hash. |

A completed run directory contains `report.json`, `review.html`, `review.json`, `decisions.json`, `manifest.json`, and the complete available validator evidence. A successful fix adds `candidate.pdf`; a reviewable manual-work result may contain `review-draft.pdf`. Preservation failures do not publish a review PDF. A read-only check does not publish a remediated copy.

The report keeps validator results, supplemental checks, fidelity, and human work separate. Figure-description meaning, semantic reading order, artifact choices, table relationships, character accuracy, and contrast remain explicit human work. There is no predicted LMS checker score or aggregate WCAG compliance percentage.

Each fix validates the unchanged original baseline before modification and validates the exact final artifact again. `validation_delta` records original rule IDs as fixed, remaining, or newly failing when the two complete rule inventories are comparable. Partial assertion details stay disclosed; a rule comparison does not invent individual repaired-assertion counts. A missing or inconsistent comparison remains explicitly not compared.

Rendering compares every page with the pinned PDFium renderer at 96 dpi, RGB on white, with annotations enabled. The default permits zero changed pixels. Text, page geometry, existing navigation, page labels, and common annotation properties are checked separately.

## Supply and approve descriptions or metadata

A first fix inventories title, language, actual Figure occurrences and eligible reviewed structure controls in `decisions.json`. Pending decisions do not change the PDF. A person can write the descriptions directly or request optional local AI drafts, then explicitly review and accept the intended values. AI output cannot supply human approval.

1. Copy the run's `decisions.json` outside the completed bundle, for example to `reading.decisions.json`. Keep the completed bundle immutable.
2. Edit only the relevant `value` fields. Keep IDs, bindings, context fingerprints, `current` values, and occurrence information intact. A repeated asset can have different descriptions in different contexts.
3. Approve the reviewed IDs explicitly. For example:

```powershell
& $py -m pdf_remediator decisions approve ".\reading.decisions.json" --id "metadata:title" --reviewer "Reviewer Name"
& $py -m pdf_remediator decisions approve ".\reading.decisions.json" --id "figure-id-copied-from-the-sidecar" --reviewer "Reviewer Name"
```

Repeat `--id` to approve several reviewed items in one command. Use `--reviewed-at 2026-10-16` for an explicit ISO date; otherwise the command records the current timestamp. Do not mark another person's review complete on their behalf.

4. Rerun the **same original file, output directory, and processing options**, adding the edited sidecar:

```powershell
& $py -m pdf_remediator fix ".\reading.pdf" -o ".\output\readings" --title "The reading's actual title" --lang en-US --sidecar ".\reading.decisions.json"
```

Approvals bind to the exact original hash, prepared checkpoint hash, decision value, and occurrence context. Editing an approved value invalidates its approval; approve it again after review. A different configuration, code/tool version, source, or staged PDF can make the sidecar stale. Reuse is refused rather than silently applying a description to another occurrence. One shared Figure element spanning pages requires the same approved description for each occurrence.

JSON is the default; `.yaml` and `.yml` sidecars are also accepted. `check` refuses a supplied sidecar because it is read-only. Description approval enables application of that text; it does not complete the final candidate's human verification.

## Request optional local AI drafts

Assistance supports title and figure-description decisions only. The selected decision context contains bounded nearby text and, when explicitly included and safely resolved, a PNG crop associated with that exact figure occurrence. It does not transmit the complete PDF. Unsafe/nested/ambiguous image regions are omitted and disclosed. Separate occurrences of a reused image retain separate context and cache bindings.

The model service must already be running locally and the named model must already be installed. The prepared computer has Ollama at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`; its local endpoint is `http://127.0.0.1:11434/v1`. The tested installed models include text/caption drafting with `qwen2.5:1.5b` and image drafting with `qwen3.5:latest`. No model is pulled or downloaded by these commands.

For title help from a text model:

```powershell
& $py -m pdf_remediator assist ".\output\readings\RUN-DIRECTORY" --endpoint "http://127.0.0.1:11434/v1" --model "qwen2.5:1.5b" --id "metadata:title" -o ".\title-drafts.json" --cache ".\output\ai-cache" --timeout 120
```

For a selected figure with a supported vision model:

```powershell
& $py -m pdf_remediator assist ".\output\readings\RUN-DIRECTORY" --endpoint "http://127.0.0.1:11434/v1" --model "qwen3.5:latest" --id "figure-id-copied-from-the-sidecar" --include-images --reasoning-effort none -o ".\figure-drafts.json" --timeout 180
```

Repeat `--id` for up to eight selected decisions. Without `--include-images`, drafting uses text/captions only. `--reasoning-effort` accepts `none`, `low`, `medium`, or `high` for models that support that control; the tested Qwen3.5 image route uses `none`. In the browser, the equivalent option is **Use fast drafting mode**. Other providers/models may have different supported controls.

`assist` saves a **draft envelope**, not an applicable approved decision file. It does not write PDF objects, apply values, or sign approvals. The browser's manual flow stages these proposals separately for **Use as editable draft** and explicit acceptance. The optional Auto-fix flow instead uses a separate, bounded machine authorization for the selected request. Existing human edits and approvals win. A model cannot invent decision IDs, change decision kinds, provide approval fields, or invoke tools.

Provider requests use direct loopback connections only. Localhost is pinned to a literal loopback address; redirects, environment proxies, endpoint credentials, and cloud endpoints are refused. Configure the local model service itself for offline inference; the tested Ollama session had cloud access disabled. The application is not a system firewall.

Reports retain the selected model/endpoint, exact source and prepared bindings, occurrence/context and request hashes, prompt/schema versions, content-sent counts, limits, and cache provenance. Credentials and environment secrets are not copied. Cache keys include context, model metadata, and settings; generic provider metadata does not establish a hash of the actual model-weight bytes. A failed or invalid AI request contributes no choices from that request. Auto-fix can still apply valid choices from earlier completed batches and discloses the partial failure. Cancellation or stale review context prevents automatic application. Semantic adequacy always remains human work.

## Optional recovery routes

These choices are explicit processing options. Their evidence and remaining human review appear in the report.

**OCR:** use `--ocr skip` for image-only scans or explicitly select `--ocr redo` for a supported mixed digital/scanned document. Bounded multi-page English OCR runs within the program; the OCR-equipped private Windows package includes its isolated OCR runtime, Tesseract and pinned local English data. OCR defaults off, with standard recognition when enabled. Opt in to `--ocr-profile table-lines` or **Scan layout: Tables with visible grid lines** for ruled-table recognition in a separate run. Every page remains subject to the same single-worker time/memory limits and all-page exact visible-content, geometry/navigation/annotation and zero-removed-original-token checks. Mixed-page skip, redo on an existing tag tree, unsupported document features and force rasterization remain refused. OCR uses ordinary PDF output, optimization zero, and a unique short temporary root under `tmp/ocr`, with its path retained as evidence. Recognition accuracy, completeness, table relationships and reading order remain pending review; unreadable or cut-off source content may require a better source. The historical 77-page technical component-OCR result and the complete-program folder results retain their separate scopes; neither establishes general scanned-book remediation.

**Tag regrouping:** `--allow-tag-regrouping` permits the bounded list/link regrouping performed by the preservation processor when direct restoration cannot retain the original painting operations. Every regrouping creates a required human review item. This does not authorize arbitrary structural rewrites or establish list/link semantics.

**Source character mappings:** `--repair-source-mappings` permits only the supported missing Type1 TeX mappings from exact original font evidence and pinned official mapping data. It never substitutes a font or overwrites an existing mapping. It adds the same proven mappings to a separate source reference and the processed PDF, records every corrected source glyph, and requires unchanged source appearance/navigation plus an exact final comparison against that reference. Raw original-to-final text differences remain visible. Mathematical and compound-symbol meaning still needs review. This option cannot be combined with OCR.

For example, after selecting the two bounded options for a suitable book:

```powershell
& $py -m pdf_remediator fix ".\book.pdf" -o ".\output\books" --allow-tag-regrouping --repair-source-mappings
```

An unsupported case remains actionable manual work; turning on an option does not waive the release checks.

Declare known content with `--document-kind reading`, `--document-kind slides`, or `--document-kind equations`, or set `document_kind` in TOML. Known slide decks and equation documents are refused by `fix` with `needs-manual` and no PDF output. The default `unknown` and an explicit `reading` declaration both retain a required human review item for visual slide layouts, untagged equations, and other content that PDF object inspection cannot reliably identify. A declaration does not establish mathematical accessibility.

## Batch, cancellation, and resume

```powershell
& $py -m pdf_remediator fix ".\input-readings" -o ".\output\batch" --recurse
& $py -m pdf_remediator fix ".\reading.pdf" -o ".\output\readings" --resume
& $py -m pdf_remediator fix ".\reading.pdf" -o ".\output\readings" --dry-run
```

Batch processing isolates each file, excludes the selected output tree, and records `batch-summary.json`. A supplied sidecar applies to exactly one document. Keep outputs separate from inputs and all synced `sources/` files read-only.

Use Ctrl+C to request cancellation, or pass `--cancel-file .\cancel.flag` and create that file to cancel. External tools have wall-time and sampled process-tree memory limits; Java heap is bounded separately. The memory measurement is not an operating-system hard allocation guarantee.

`--resume` reuses completed bundles or prepared checkpoints only when their source, settings, decisions, implementation, and tool fingerprints match, including the selected Java executable, release metadata, and JVM library. It is not an arbitrary mid-page restart. Existing completed runs are immutable; a changed or stale checkpoint is refused. Interrupted locks are reported for review. `--dry-run` inventories the selected inputs without changing PDFs, invoking providers, or downloading resources.

Processing exit codes are `0` for automated candidates, `2` when manual work remains, `1` for failures, and `130` for cancellation. Inspect the report for the actual result and scope.

## Record final human verification

Copy the candidate bundle's `review.json` outside the bundle. Complete every required item against the exact candidate PDF: set its `status` to `approved`, supply the actual `reviewer` and ISO `reviewed_at`, and add review notes. Keep the artifact hash, item IDs, and item scope unchanged. The final review should record the assistive technology used and the pages/regions actually checked.

Obtain the actual LMS checker score in the relevant LMS/institutional context. Then record it:

```powershell
& $py -m pdf_remediator ledger add ".\output\readings\RUN-DIRECTORY" --ledger ".\verification.jsonl" --reviewer "Reviewer Name" --checker-score 95 --checker-context "Institution / LMS course / item" --threshold 67 --review-scope "Record the actual listening, page, table, figure, and visual review scope" --review-file ".\reading.review.json"
& $py -m pdf_remediator ledger list --ledger ".\verification.jsonl"
& $py -m pdf_remediator ledger export --ledger ".\verification.jsonl" -o ".\verification-export.json"
```

The numbers above demonstrate the syntax; enter the observed score and selected threshold. The default workflow threshold is 67. An LMS checker score alone cannot create verification: the candidate bundle, hashes, all required automated assessments, and completed human-review items must also qualify. Verification is recorded in the ledger; it does not rewrite the immutable run report.

A later PDF edit makes its verification stale. A subsequently discovered semantic blocker can be recorded without deleting history:

```powershell
& $py -m pdf_remediator ledger invalidate RECORD-ID --ledger ".\verification.jsonl" --reason "Describe the confirmed blocker" --reviewer "Reviewer Name"
```

## Local execution, licenses, and limits

PDF Remediator itself is licensed under the Apache License 2.0 (see `LICENSE` and `NOTICE`). The programs and libraries that a packaged copy runs alongside it keep their own licences; what each requires is set out in [docs/LICENCE-REVIEW.md](docs/LICENCE-REVIEW.md), and the application is not cleared for redistribution until that review is complete.

The core processing commands invoke selected local executables. Optional assistance connects only to the explicitly selected local model service and stays off until requested. There is no cloud-provider or automatic model-download route. `--local-only` and `--no-ai` on the deterministic processing commands document their intent; they do not configure a system firewall. Reports, drafts, extracted descriptions, image crops, and validation contexts are local artifacts and can contain document content. Dependency installation and opening externally hosted links are separate from PDF processing.

Validator/engine versions and relevant artifact hashes are recorded; `doctor` separately reports dependency/runtime startup evidence. Retain each third-party distribution's notices and license terms when moving or packaging the environment. The application is not a prebuilt Windows installer. A proprietary tagging SDK and accesspdf are not Phase 1 processing engines. Historical scripts without established licensing were not incorporated.

The pinned TeX mapping reference is distributed unchanged with [its provenance notice](src/pdf_remediator/data/TEX-MAPPING-NOTICE.txt) and [LPPL license](src/pdf_remediator/data/LPPL-1.3c.txt). The published *Think Python* evaluation PDF remains subject to its separately recorded CC BY-NC attribution and provenance; it is not an unrestricted redistribution fixture.

Supported processing preserves usable existing tags and adds only bounded, evidenced repairs. Encrypted or signed files, forms, attachments, JavaScript, optional content, detected formula structures, and PDF 2.x are routed to manual/source-document handling. Complex table meaning, arbitrary font repair, badly damaged files, unrecognized scans, semantic reading order, and complete accessibility assessment remain outside automatic repair. A candidate is ready for the specified human review, not certified accessible.


Developer tests require **Node.js 20 or newer** on PATH in addition to the Python
test environment. Node runs the shipped browser script with authored DOM/HTTP
doubles; it opens no browser and is not required to install or run the application.
The normal Python suite and source-only runner include these JavaScript checks
and fail clearly if Node is missing or too old; no cases are silently skipped.
Run the actual-script checks alone from a source checkout with:

```powershell
node --test-reporter=tap .\scripts\test-web-assets.cjs
```

These checks cover session/skip reload, saved dashboard labels, occurrence-specific
problem-note display after reopening/group changes, tab navigation/modifier
handling, heading/table/language repair controls, asynchronous navigation
and active-job guards. There are 60 authored
JavaScript cases inside one Python entry; they do not replace native keyboard,
screen-reader or human acceptance.

Run the regression suite with project-local temporary storage on this Windows sandbox:

```powershell
$testTemp = Join-Path ".\work" ("regressions-" + [guid]::NewGuid().ToString("N"))
& $py -m pytest tests --basetemp $testTemp
```

The test temporary directory is disposable and must be separate from input documents and retained run bundles.
