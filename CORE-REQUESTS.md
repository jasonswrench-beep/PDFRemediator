# Core requests from PDF Remediator

**Written 2026-11-16**, after reading `CORE-NOTES.md` and `ROADMAP.md` in `jasonswrench-beep/openstage-core` (working folder
`C:\Dev\openstage-core`; its notes were updated 2026-11-15). The rule from the core: build on what it publishes, do not copy or reimplement
core code, and note here what the core does not offer yet. PDF Remediator uses nothing from the core today and has copied nothing from it.

PDF Remediator is **Python** (3.11 or later; 3.14 in the packaged build) with a Rust program window. The core's accessibility rules (C2)
are, as far as can be seen, a **Rust** crate, and its C8 is not specified. So every request below says what form of the core's work
PDF Remediator can actually use.

**What was seen of C2.** `CORE-NOTES.md` lists C2 as "Not started (priority 3)". The core's working folder on this PC holds an
unpublished, untracked draft (`specs/a11y/rules.json`, catalogue "A11Y-1" revision 1.0, WCAG 2.1, and `crates/openstage-a11y`) that was
read, not changed, on 2026-11-16 to avoid asking for something it already has. Nothing in this file depends on that draft being
published as it stands.

## Request list

| # | Request | Form PDF Remediator can use | Meanwhile | State |
|---|---|---|---|---|
| C2-1 | Contrast: ratio, thresholds, large-text rule, suggested text colour | Language-neutral conformance vectors (below), plus either a Python package or a command-line tool that reads and writes JSON | Keeps its own `contrast.py` | open |
| C2-2 | Language tags: one definition of "well-formed", with test lists | Same: vectors, and a Python package or JSON command-line tool | Keeps `language_tags.py` | open |
| C2-3 | The words for a check's result and for a review item's state | A short specification, with the rule that one word has one meaning in every tool | Keeps its own words, listed below | open |
| C8-1 | Local AI runtime: how to ask whether a model is there, and the settings for it | A local server on loopback with a small HTTP/JSON interface; Python is the caller | Keeps its own optional loopback client, off by default | open |
| C8-2 | Rules a model must obey in this tool | Words in the C8 specification | Already enforced in PDF Remediator | open |

Items C2-1 to C2-3 are the "hand its contrast math, language-tag handling and review status words to C2" item of the development list. They
are described below as what PDF Remediator hands over. Nothing is to be taken from PDF Remediator's code: its behaviour is written out
here, with vectors that the core can check against its own work.

## C2-1 Contrast

**What PDF Remediator does (`src/pdf_remediator/contrast.py`):**

* The ratio is WCAG's relative-luminance ratio of two 8-bit sRGB colours, **unrounded**: each channel divided by 255 and made linear with the
  sRGB curve (knee at 0.04045), luminance `0.2126 R + 0.7152 G + 0.0722 B`, ratio `(lighter + 0.05) / (darker + 0.05)`.
* A ratio is compared with its threshold **without rounding**: 4.4999 fails 4.5.
* Large text is **18 points or more, or 14 points or more with a weight of 700 or more**. Threshold 3:1 for large text, 4.5:1 otherwise.
* When the weight is unknown (zero) and the size is between 14 and 18 points, a ratio from 3 up to (not including) 4.5 is **needs-review**,
  not pass or fail ("font-bold-weight-unresolved"). The built-in standard fonts' weights are taken from their exact standardized names
  only (Helvetica-Bold and its kin are 700; the plain faces 400), never from a part of a name.
* The effective size is the font size times the vertical basis of the text matrix (and the page's user unit), not the glyph's ink height.
* When a text fails, the program suggests, for the *source document*, whichever of black and white has the higher ratio with the measured
  background, and reports that ratio. It never recolours a PDF.
* What stays out of the core's concern: how a background is found. PDF Remediator renders the page with its text hidden and samples a
  uniform background; that is PDF-specific.

**Vectors (computed from the program as it is on 2026-11-16, text on a white background `#ffffff`):**

| Text colour | Ratio (10 places) | At normal size | At large size |
|---|---|---|---|
| `#000000` | 21.0000000000 | pass | pass |
| `#ffffff` | 1.0000000000 | fail | fail |
| `#595959` | 7.0047292080 | pass | pass |
| `#767676` | 4.5422249596 | pass | pass |
| `#777777` | 4.4780894536 | **fail** | pass |
| `#008000` | 5.1374027808 | pass | pass |
| `#ff0000` | 3.9984767708 | **fail** | pass |
| `#0000ff` | 8.5924713584 | pass | pass |
| `#949494` | 3.0334698257 | fail | pass |
| `#959595` | 2.9953461357 | fail | **fail** |

Size cases (each at `#777777` on white, ratio 4.4780894536): 18 pt normal weight: pass (large). 14 pt weight 700: pass. 14 pt weight 400:
fail. 14 pt weight unknown: needs-review. 13.99 pt weight 700: fail. 17.99 pt weight unknown: needs-review. 12 pt weight unknown: fail.

**Request.** Publish these as C2's conformance vectors and say, in its spec, whether it agrees with each rule above. If the draft's
`Weight::Unknown` case and the "needs review" outcome differ from what is written here, say which is intended, and PDF Remediator will follow
the core's ruling (its screens are advisory, so a change of this kind is safe for it). If it can offer a Python route, the smallest useful
one is a command-line program that takes colours, a size and a weight as JSON and returns the ratio, the threshold and the status.
PDF Remediator would then call it from its own tests first and from the program afterwards, **only with its own contrast tests passing**.

Also wanted, later: the 3:1 rule for non-text graphics (1.4.11). PDF Remediator does not measure graphics today and says so.

## C2-2 Language tags

**What PDF Remediator does (`src/pdf_remediator/language_tags.py`, `checks.py`):**

* Reviewed language edits accept a value only if it is **well-formed** under RFC 5646 *syntax*: ASCII, 1 to 255 characters, no leading or
  trailing space; language (2 to 8 letters, with up to three extlang subtags only after a 2 or 3 letter language), optional script (4 letters),
  region (2 letters or 3 digits), variants (5 to 8 characters, or 4 starting with a digit; none repeated), extensions (a single character other
  than `x`, then 2 to 8 character subtags; no singleton repeated), and private use (`x-...`, needing a subtag after `x`). The finite list of 26
  grandfathered tags is accepted as written. **The original spelling is kept; nothing is canonicalized, inferred or looked up in the
  registry.** A tag is never claimed to be registered or to describe the text.
* A looser test is used in the `metadata` check that decides whether a document's language is *plausible*: letters 2 to 8, then groups of 1 to 8
  letters or digits after hyphens. **These two tests disagree on some inputs** (for example `en-12`, `en-a`, or a repeated variant such as
  `de-DE-1996-1996` pass the loose test and fail the strict one). That is a known inconsistency inside PDF Remediator, left alone until the core says which is
  intended.
* Language *detection* is separate and PDF Remediator's own: a bounded function-word screen for seven languages (English, Spanish, French,
  German, Italian, Portuguese, Dutch), which only ever produces a review suggestion.

**Vectors (strict test, from the program on 2026-11-16).** Well-formed: `en`, `en-US`, `zh-Hant`, `zh-Hans-CN`, `sr-Latn-RS`, `fr-CA`,
`es-419`, `en-123`, `de-CH-1901`, `sl-rozaj-biske`, `en-a-bbb-x-a-ccc`, `x-private`, `i-klingon`, `en-GB-oed`, `english-language`.
Not well-formed: the empty string, `e`, `x`, `en-`, `-en`, `en--US`, `en_US`, `en-US ` (trailing space), `en-a`, `en-12`, `de-DE-1996-1996`
(repeated variant), `en-a-bbb-a-ccc` (repeated singleton), `abcdefghi` (nine letters), `ab-abcdefghi`, a non-ASCII `é`.

**Request.** C2 defines one "language tag is well-formed" rule, with a list like the one above, and says whether the plausibility test (loose)
and the well-formedness test (strict) are to be one rule or two named ones. PDF Remediator will adopt it for its `metadata` check only when it
can do so without changing a saved review's recorded result, and will say so in its notes. Same Python-route question as C2-1.

## C2-3 The words for results and for reviews

**What PDF Remediator uses.**

* **A check's status** (`checks.py`): `pass`, `fail`, `needs-review`, `not-tested`, `not-applicable`, and `error` (the check itself could not
  run; on a blocking check it blocks). The first five are the words in the core's draft catalogue, with the same meanings; `error` is not in the draft.
  **Request:** keep `error` out of a finding's status and give it a place of its own in C2's report (a rule that could not run), or add it.
* **A check's weight:** `blocking` or `advisory`. Blocking stops a draft being called a candidate. The core's rule "findings warn and never
  block, a project may turn chosen rules into blockers, off by default" is the opposite default; PDF Remediator's blockers are declared in
  its own profile and stay with the tool (a tool decides what stops its own output).
* **A person's review item** (`manual_queue`, saved in the review): `pending` until a named person records an outcome; `approved` when a
  person has judged it fine; `blocked` when a person has confirmed a problem (it keeps the draft from `candidate` and `verified`). A required
  item is never filled in by the program. A review stays pending after a repair, because a repair creates a fresh item bound to the new
  file; an earlier approval does not carry over.
* **Who decided:** `auto-accepted` means a value was applied by the program's automatic mode (a rule or an optional model); it is **never**
  a person's approval. A named human approval is a different record, with a name and a date, and is lost when the file changes.
* **The tool's own final words** (not for C2): `failed`, `needs-manual`, `candidate`, `verified`.

**Request.** C2's specification should say, once, what each status word means and that **an automatic result is not a person's judgement**,
so that an assistant, a checker and a person do not use one word for two things. A state for "a person looked and this does not apply here"
is wanted in the review vocabulary; PDF Remediator has `pending`, `approved` and `blocked` only, and records "does not apply" as a note
on an approval.

## C8 The local AI runtime (development-list item 6)

**What changed.** The old plan (`docs/STATUS.md`, "AI architecture proposal") put hosted providers first and a local model later. The
development list reverses it: AI is **local by default, on the shared C8 runtime**, and a hosted provider is a possible later addition,
never the first step. PDF Remediator's AI is, and stays, **optional**: every feature works with no model, and nothing leaves the computer
unless the person turned it on for that document.

**What PDF Remediator uses AI for** (all as pending drafts a person accepts, except in the explicitly chosen Auto-fix mode, whose values are
labelled `auto-accepted`): a draft title, a draft description for a figure from its picture and its surrounding text, and later possibly
heading suggestions. No model ever writes a PDF object, sets a language, or approves anything.

**What it has today (`docs/STATUS.md`, `assistance.py`).** An optional client for a model server already running on the same computer
(loopback only, models installed by the person, nothing downloaded during processing, requests limited to a bounded context, an exact
prompt/schema version in the cache key, model origin recorded with every value). It is off by default.

| # | Request | Why |
|---|---|---|
| C8-1a | **How a tool asks.** A way to ask "is a local model available, and which?" and to send a request and get JSON back, on loopback, with a documented request and response shape (text and an image in; JSON that matches a schema out). | PDF Remediator would drop its own provider setup and use the shared one, so the person installs a model once for the whole suite. |
| C8-1b | **One settings place** for the model and for any key the person chooses to bring, so PDF Remediator holds no key. | Today it keeps none, and the plan never wanted it to. |
| C8-1c | **Visible status and Cancel.** A request can be cancelled; the runtime says whether it is loading, busy or absent, so the program can show it in its own progress bar. | The program shows progress and Cancel for every long job. |
| C8-1d | **A way to say "no network".** A setting or flag that makes the runtime refuse anything but loopback and never download a model. | PDF Remediator's local-only mode requires it. |
| C8-1e | **Image input.** The runtime accepts an image with a request (figure crops), with a documented size limit. | Figure descriptions need the picture. |
| C8-1f | **A hosted provider later.** Only after the above, and only as the person's own opt-in per document with the data-sent summary the roadmap asks for. | The development list says hosted is not first. |
| C8-2 | **Rules, in C8's spec:** a model never sets a key or an answer; a suggestion is something a person accepts or dismisses; nothing leaves the machine unless turned on; an automatic value is labelled as such and is never a person's approval. | These are PDF Remediator's existing rules and match OpenAssess's. |

**What PDF Remediator will do when C8 exists:** replace its own model client with the core's, keep every existing test of the "AI off", "loopback
only", "pending draft" and "`auto-accepted` is not a human approval" behaviours (none may be weakened), and keep running with no model.

**What it will not do meanwhile:** build a hosted-provider path, store any API key, bundle a model, or add a download. The old
"API-first" proposal in `docs/STATUS.md` is superseded by this one (see the entry dated 2026-11-16 there).

## Notes from the other items of this round (not requests to build anything now)

These are things PDF Remediator holds as plain data or rules that the core's C2 may want to own so that tools say the same thing. Nothing
was taken from the core, and nothing here blocks PDF Remediator.

| # | What | Where it is today | Form |
|---|---|---|---|
| C2-4 | **Colour test and hue names.** A colour is chromatic when its HSV saturation is at least 0.35 and its value at least 0.25. Hue bands in degrees: red 345 to 15, orange 15 to 45, yellow 45 to 70, green 70 to 170, cyan 170 to 200, blue 200 to 260, purple 260 to 300, pink 300 to 345. "Hue-only" difference means the luminance ratio to the body text colour is below 3:1. Red/green and orange/green are confusable pairs. | `color_meaning.py` | Vectors: (204,0,0) red; (0,128,0) green; (0,0,204) blue; (255,230,0) yellow; (255,128,0) orange; (128,128,128), (235,235,250) and (13,13,13) not chromatic. Ratios against black: (204,0,0) 3.567; (0,0,204) 1.872. |
| C2-5 | **The wording list for "colour is used to tell you what to do or find"** (eight patterns, e.g. "colour-coded", "the red items", "highlighted in yellow", "click the green button"), so a document tool and a slide tool flag the same sentences. | `color_meaning.PHRASE_PATTERNS`, listed in `docs/COLOR-ONLY-MEANING.md` | Shared data with test sentences. |
| C2-6 | **A vocabulary for candidates** that are not findings: `colored-text`, `link-color-only`, `multi-hue-graphic`, `colored-annotation`, `color-reference-text`; and the rule that a clean screen is never a 1.4.1 result. | `color_meaning.py` | Words in C2's spec. |
| C2-7 | **"Implausible extracted text"** as a rule family: the code-point classes (private use including the supplementary planes, U+FFFD, controls, noncharacters, unassigned), a Latin / Cyrillic / Greek look-alike table, and the rules for reviewed replacement text (one to 16 characters, no control, format, private-use, surrogate, unassigned or U+FFFD). | `character_meaning.py`, `character_corrections.reviewed_text_problem` | A shared table of code points. |
| C2-8 | **A "human check record" shape**: named reviewer, date, per check `pass` / `problem` / `not-checked`, bound to an exact artifact hash and page, origin `human-entered`, never accepted from a model or a machine label, invalidated when the artifact changes (its notes are kept, its authority is not). | `ocr_review_sample.make_record` | A worked example only; other tools may want one shared shape. |

Not requested: the PDF-specific parts (finding a link's underline, a picture's repeat count and area on a page, reading a ToUnicode map)
stay in PDF Remediator. No C8 need arises from items 1a to 1c: none of them uses a model.
