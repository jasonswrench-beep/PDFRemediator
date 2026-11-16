# WCAG 2.1 Level A and AA: what PDF Remediator covers, and what it does not

**Revision 2, 2026-11-16, for program version 0.3.0** (revision 1 was the same day, before the colour-only, character-meaning and logo/OCR-review additions). The roadmap (`docs/ROADMAP.md`, section 3) promised a matrix that relates the checks to
the WCAG 2.1 criteria and that also shows the criteria a person must judge or that are outside the program. This is that matrix. It is written
from the checks as they are in the code (`src/pdf_remediator/checks.py`, `inspection.py` and the reviewed-edit modules) and from
`docs/LMS-CHECK-APPLICABILITY.md`. Where the program does not test something, the table says so.

## How to read it

**This is not a conformance claim.** The program makes a draft copy of a PDF and tells a person what it found and what is left. It does not
certify a document against WCAG, against PDF/UA, or against any institution's checker. A passing screen says that one narrow mechanical
test passed. Every criterion that needs a human judgement (meaning, purpose, sequence, adequacy of a description) stays a human judgement
even when the program also has a screen for part of it.

The word in the **Coverage** column is one of:

| Word | Meaning |
|---|---|
| **Screened** | The program runs a mechanical test that can fail the document or hold it back (a blocking check or a strict-validator rule). The test covers only the part named; the meaning is still a person's. |
| **Advisory** | The program measures or lists candidates, never fails the document for it, and raises a required review item for a person. |
| **Repair** | The program has a reviewed control that can change the draft once a named person has entered and accepted the change. Nothing is changed by guess. |
| **Review only** | The program raises a required review item with guidance but tests nothing itself. |
| **Not assessed** | The program does not look. A person has to. |
| **Not applicable** | The criterion concerns behaviour a static PDF does not have (for example timing, scripts, live media), or behaviour of the PDF reader and not of the file. The program refuses documents that carry the active content that would make it apply (scripts, signatures, encryption). |

Words are combined where more than one is true. "Repair" never means "approved": every change creates a fresh pending human review, and
the human-verification ledger records only a person's own entries.

**The check names** below (`figure-alternatives`, `link-structure` and so on) are the ids in the program's report. **Blocking** checks hold a
draft back from `candidate` status; **advisory** ones never do. The strict validator is veraPDF's PDF/UA-1 profile; it tests the tag structure
and metadata the profile asks for, not the meaning.

## Level A and AA criteria

### 1 Perceivable

| Criterion | Level | Coverage | What the program does | What stays with a person |
|---|---|---|---|---|
| 1.1.1 Non-text Content | A | Screened, Repair, Review only | `figure-alternatives` (blocking) finds tagged figures with no description or an obvious placeholder ("image 33", a file name). Reviewed controls write a person's description, or mark an occurrence decorative (the picture stays; assistive technology skips it). A **Logo and branding** group lists likely logos (the same picture on several pages, small, in a margin band, or already described as a logo) so one description can be saved for the selected occurrences, each of which keeps its own decision and named acceptance (`docs/LOGO-AND-OCR-REVIEW.md`). `scan-text-layer` (blocking) holds back image-only pages with no text. OCR (off by default) can add a text layer to scans. Form fields get reviewed names (see 4.1.2). | Whether a description conveys the picture's purpose; whether an image is decorative; untagged images that carry meaning; logos; text inside images; OCR accuracy, completeness and order (`figure-meaning` and `image-and-ocr` review items). For scanned pages the program picks a reproducible sample of pages and records a named person's pass / problem / not-checked for words, completeness and order on each; the `image-and-ocr` review cannot be approved until every sampled page has a complete record. |
| 1.2.1 Audio-only and Video-only (Prerecorded) | A | Not assessed | The program does not look for embedded audio or video. | Any PDF with embedded media needs a person (and an alternative in the source). |
| 1.2.2 Captions (Prerecorded) | A | Not assessed | As 1.2.1. | As 1.2.1. |
| 1.2.3 Audio Description or Media Alternative (Prerecorded) | A | Not assessed | As 1.2.1. | As 1.2.1. |
| 1.2.4 Captions (Live) | AA | Not applicable | A PDF has no live media. | |
| 1.2.5 Audio Description (Prerecorded) | AA | Not assessed | As 1.2.1. | As 1.2.1. |
| 1.3.1 Info and Relationships | A | Screened, Repair, Review only | The strict validator tests the tag tree. `content-linkage` and `content-coverage` (blocking) check that structure elements resolve to page content and that page content is covered. `table-header-associations` (blocking) checks Scope or Headers/ID relationships. `marked-headings`, `heading-start-level`, `heading-depth` and `heading-sequence` check heading roles. `form-accessibility` (blocking) checks static field names and ownership. Reviewed controls: headings to paragraphs and back, list construction and roles, table roles/IDs/spans/summary, form tooltips and descriptions, empty-tag removal, document containers. | Whether the tags tell the truth about the page: list and table meaning, heading purpose, label and field pairing (`table-relationships`, `form-meaning`, `reading-order`). Complex tables are not rebuilt. |
| 1.3.2 Meaningful Sequence | A | Review only, Repair | The program does **not** test reading order automatically (`reading-order` is reported as not tested). It shows the tag order with the page and lets a reviewer permute existing children and move eligible text tags between neutral groups. | The whole sequence: listening with a screen reader or reading the tag order against the page. |
| 1.3.3 Sensory Characteristics | A | Advisory (colour wording only) | `color-meaning` lists text that points at a colour ("the red items", "click the green button", "colour-coded"; eight exact phrase patterns, listed in `docs/COLOR-ONLY-MEANING.md`). Instructions that rely on shape, size, position or sound are not tested. | Reading the text for any instruction that depends on a sensory characteristic. |
| 1.3.4 Orientation | AA | Not applicable | A PDF page has a fixed orientation and the file does not lock a viewer's. The program records page rotation and offers a layout for scans stored sideways, which is a reading aid, not a test of this criterion. | |
| 1.3.5 Identify Input Purpose | AA | Not assessed | PDF forms have no input-purpose attribute the program checks. | |
| 1.4.1 Use of Color | A | Advisory, Review only | `color-meaning` (advisory, never blocking) lists **candidates**: coloured text unlike the body text, link text told apart by colour alone (no underline or border), nearby shapes in several hues (chart-like), coloured markup, and wording that points at a colour. It raises a required pending review item with source-repair guidance. It never decides that colour is the only carrier of meaning, never recolours, and a clean result is not a 1.4.1 result: pictures, patterns, form-field appearances, Type 3 text, layers and pages past its bounds stay under review. | Whether colour is the only way information is shown, and whether the listed candidates matter (`color-meaning` review item). |
| 1.4.2 Audio Control | A | Not assessed | As 1.2.1. | |
| 1.4.3 Contrast (Minimum) | AA | Advisory, Review only | `contrast` measures opaque digital text on uniform rendered backgrounds against the 4.5:1 and 3:1 thresholds, for at most the first 100 pages and 2,000 text regions. Findings carry page, region, colours, ratio and a black or white suggestion for the source. Rotated, transparent, patterned, image, clipped or overlapping paint, images of text and graphics stay unmeasured. | Applicability (logos, incidental and decorative text are exceptions), and everything unmeasured (`contrast` review item). Pages are never recoloured. |
| 1.4.4 Resize text | AA | Advisory | A reader zooms a PDF; the file cannot stop that. The `small-font` screen lists supported digital text strictly under 9 points as a readability advisory. 9 points is not a WCAG threshold. | Whether a size is a problem in context; enlarging needs a source change and re-export. |
| 1.4.5 Images of Text | AA | Screened (page level), Review only | `scan-text-layer` holds back pages that are only a picture. Pages with both text and pictures are classed `mixed` and raise the `image-and-ocr` review. | Images of text inside digital pages; whether a picture of text is essential. |
| 1.4.10 Reflow | AA | Not assessed | A PDF is a fixed layout. The program does not reflow or test reflow. | Source repair if reflow matters (a tagged PDF may reflow in some readers). |
| 1.4.11 Non-text Contrast | AA | Not assessed | The contrast screen measures text only. | Icons, chart marks, form-control borders. |
| 1.4.12 Text Spacing | AA | Not applicable | Text spacing is changed by a reader's tools, not by the file. | |
| 1.4.13 Content on Hover or Focus | AA | Not assessed | PDF tooltips are not tested. | |

### 2 Operable

| Criterion | Level | Coverage | What the program does | What stays with a person |
|---|---|---|---|---|
| 2.1.1 Keyboard | A | Screened (forms), Review only | `form-accessibility` checks static field names, widget ownership and structure-based tab navigation (`/Tabs /S`). `link-structure` checks that links are in the tag tree. | Actually operating the form and the links with a keyboard in the reader (`form-meaning`). |
| 2.1.2 No Keyboard Trap | A | Not applicable | Documents with JavaScript or active actions are refused (`unsupported-features`). | |
| 2.1.4 Character Key Shortcuts | A | Not applicable | As 2.1.2. | |
| 2.2.1 Timing Adjustable | A | Not applicable | A static PDF has no time limits; active content is refused. | |
| 2.2.2 Pause, Stop, Hide | A | Not applicable | As 2.2.1. | |
| 2.3.1 Three Flashes or Below Threshold | A | Not assessed | Embedded animation or rich media is not inventoried. | |
| 2.4.1 Bypass Blocks | A | Screened, Repair | `heading-navigation` inventories headings and bookmarks, and fails on bookmark errors. Reviewed controls rename and retarget existing bookmarks and append a new bookmark outline (up to 200 entries, 10 levels). | Whether bookmarks cover the document usefully. |
| 2.4.2 Page Titled | A | Screened, Repair | `metadata` (blocking) checks that a title exists, is not a placeholder, and that the document title is displayed. A reviewed control writes a person's title to the PDF and XMP. | Whether the title is meaningful (`metadata-meaning`). |
| 2.4.3 Focus Order | A | Repair, Review only | Reviewed controls choose document tag order for a page's navigation (`/Tabs /S`) and permute same-page form controls inside one neutral group. The whole page annotation sequence is shown read-only. | Real keyboard behaviour in the reader. |
| 2.4.4 Link Purpose (In Context) | A | Screened, Repair, Review only | `link-structure` (blocking) checks each link's tag owner and linkage. Reviewed controls write a link's alternative name and description and set a local page or `http`, `https` or `mailto` target. Addresses are never opened or checked for availability. | Whether the link text or name says where it goes. |
| 2.4.5 Multiple Ways | AA | Advisory | Bookmarks and headings are inventoried (see 2.4.1). A table of contents or search is not detected as such. | Whether the document offers more than one way to find content. |
| 2.4.6 Headings and Labels | AA | Screened, Repair, Review only | The four heading checks above test marking and level order. Reviewed controls set a heading's level or turn a heading into a paragraph. Form tooltips are the reviewed labels. | Whether headings and labels describe their content. |
| 2.4.7 Focus Visible | AA | Not applicable | Drawn by the reader, not stored in the file. | |
| 2.5.1 Pointer Gestures | A | Not applicable | No scripts. | |
| 2.5.2 Pointer Cancellation | A | Not applicable | No scripts. | |
| 2.5.3 Label in Name | A | Repair, Review only | The tooltip editor asks for the visible label to be included in a field's accessible name. The program does not compare the two automatically. | A person compares the visible label with the name. |
| 2.5.4 Motion Actuation | A | Not applicable | No scripts. | |

### 3 Understandable

| Criterion | Level | Coverage | What the program does | What stays with a person |
|---|---|---|---|---|
| 3.1.1 Language of Page | A | Screened, Repair, Review only | `metadata` (blocking) checks that a well-formed language tag is present. `language-correctness` compares a bounded sample of the text with function-word lists for seven languages (English, Spanish, French, German, Italian, Portuguese, Dutch): a high-confidence mismatch blocks, a short, mixed or unsupported text stays for review. A reviewed control writes a person's tag. A missing value can be filled from the configured default (`en-US`), which is not an inference. | Whether the tag is right, and every language outside the seven. |
| 3.1.2 Language of Parts | AA | Advisory, Repair | Reviewed controls set or clear a language on one existing passage or page container; the screen considers tag inheritance inside its bounded sample. | Finding the passages: the program does not detect foreign-language passages by itself. |
| 3.2.1 On Focus | A | Not applicable | No scripts or actions that fire on focus; active documents are refused. | |
| 3.2.2 On Input | A | Not applicable | As 3.2.1. | |
| 3.2.3 Consistent Navigation | AA | Not applicable | Concerns a set of pages; a PDF is one document. | |
| 3.2.4 Consistent Identification | AA | Not applicable | As 3.2.3. | |
| 3.3.1 Error Identification | A | Not applicable | Needs a form that validates input; the program supports static fields only and refuses scripted or active forms. | |
| 3.3.2 Labels or Instructions | A | Repair, Review only | Form tooltips and optional descriptions are reviewed text (see 2.5.3 and 4.1.2). Visible labels are never created. | Whether instructions exist and are adequate. |
| 3.3.3 Error Suggestion | AA | Not applicable | As 3.3.1. | |
| 3.3.4 Error Prevention (Legal, Financial, Data) | AA | Not applicable | As 3.3.1. | |

### 4 Robust

| Criterion | Level | Coverage | What the program does | What stays with a person |
|---|---|---|---|---|
| 4.1.1 Parsing | A | Screened | Unreadable or malformed input blocks processing (`document-open`); the strict validator tests the PDF and tag syntax. (WCAG 2.2 removed this criterion; 2.1 keeps it.) | |
| 4.1.2 Name, Role, Value | A | Screened, Advisory, Repair | The strict validator tests that structure elements have standard roles; `form-accessibility` and the tooltip editor cover form field names; `link-structure` covers link roles; `font-mapping-shape` and `font-embedding` (blocking) cover the character mapping and embedding that a reader's text output depends on. `character-meaning` (advisory) lists characters whose extracted Unicode is implausible or unverifiable and unembedded fonts (guidance only). For an embedded font with an existing Unicode map, a reviewer can supply the intended text for named codes and create a separate corrected copy from the command line (`docs/UNICODE-AND-FONT-REPAIR.md`). | Assistive-technology output in the intended reader; that characters read as the page shows them (`font-characters`, `character-meaning`). No glyph shape is read: a mapping with no flag can still be wrong. |
| 4.1.3 Status Messages | AA | Not applicable | | |

## Rows by program check

This lists every check in the report and the criteria it informs, so a result can be read back against the table above.

| Check id | Kind | Informs |
|---|---|---|
| `document-open` | Blocking | 4.1.1 |
| `content-linkage`, `content-coverage` | Blocking | 1.3.1, 4.1.2 |
| `metadata` | Blocking | 2.4.2, 3.1.1 |
| `figure-alternatives` | Blocking | 1.1.1 |
| `table-header-associations` | Blocking | 1.3.1 |
| `link-structure` | Blocking | 2.4.4, 4.1.2, 2.1.1 |
| `form-accessibility` | Blocking (only when the file has forms) | 1.3.1, 2.1.1, 3.3.2, 4.1.2 |
| `font-embedding`, `font-mapping-shape` | Blocking | 4.1.2 (and the character meaning a reader speaks) |
| `unsupported-features` | Blocking | refuses scripts, signatures, encryption, attachments, optional content, equations, PDF 2.x: keeps 2.1.2, 2.2, 2.5 and 3.2 out of scope |
| `scan-text-layer` | Blocking | 1.1.1, 1.4.5 |
| `marked-headings`, `heading-start-level`, `heading-depth`, `heading-sequence` | Checker screens (blocking on failure) | 1.3.1, 2.4.6 |
| `language-correctness` | Checker screen | 3.1.1, 3.1.2 |
| `contrast` | Advisory | 1.4.3 |
| `heading-navigation` | Reported, review | 2.4.1, 2.4.5 |
| `reading-order` | Not tested; review | 1.3.2 |
| `small-font` | Advisory | 1.4.4 |
| `color-meaning` | Advisory | 1.4.1, 1.3.3 (colour wording only) |
| `character-meaning` | Advisory | 4.1.2 (character meaning a reader speaks), 1.1.1 where text is in images |
| `empty-structure-tags` | Advisory | 1.3.1 |
| `content-credentials` | Needs review | none (provenance labels; not an accessibility criterion) |

Human review items that the program raises (all start "pending"; none is ever filled in by the program): `scans`, `image-and-ocr`,
`small-fonts`, `empty-tags`, `color-meaning`, `character-meaning`, `reading-order`, `metadata-meaning`, `contrast`, `font-characters`,
`figure-meaning`, `table-relationships` and `form-meaning`.

## What is deliberately not here

* **No percentage and no conformance level.** The program does not predict an institution's checker score or a WCAG result.
* **Checks that are not tests of the file.** Zoom, focus drawing, tooltips, text spacing and similar are behaviours of the reader.
* **Anything about a set of pages** (consistent navigation, consistent identification).
* **PDF/UA is not WCAG.** Passing the strict profile means the tag structure and metadata it tests are well formed.

## Open items

These are open development or acceptance items (`docs/STATUS.md` is the live list):

* **1.4.1 and 1.3.3 (colour):** the screen exists, but no real document has been judged with it. Its thresholds are the build's own choices
  (recorded in every result) and need a person to tune them on real files.
* **1.1.1 (logos) and 1.4.5 (scans):** the logo group and the scanned-page sample exist; no person has used either on a real document yet.
* **4.1.2 (character meaning):** the window does not yet offer the correction editor, and a corrected copy does not yet enter ordinary
  review as a recorded new source. Fonts with no Unicode map and any embedding or substitution of fonts are not offered.
* Actual-user, screen-reader and institutional-checker testing has not been done (Phase 3); nothing in this table is evidence from it.

## For the shared accessibility rules

The contrast ratio, language-tag handling and review status words in this table are the ones that the shared core's accessibility rules
(C2) are to take over; see `CORE-REQUESTS.md`.
