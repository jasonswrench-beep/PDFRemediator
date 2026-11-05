## October 31: own window, progress for every long job, Cancel, Home and Reset

- **Own window.** `PDF Remediator.exe` shows the page in Microsoft Edge (or Chrome) in app mode with a profile of its own
  (`output/review-app/window-profile`), no tabs or address bar. Closing the window, or the Stop application button, stops the
  program. Without either browser the default browser is used as before. See `docs/WINDOWS-DISTRIBUTION.md`.
- **Progress is visible where you look.** Auto-fix shows a live line right under its button (the step now running and a running
  clock). Every other long job (first scan, Retry, Apply, corrected copy, credential-free copy, AI drafts) shows a bar fixed to the
  bottom of the window: its name, the step, a clock and a Cancel button; "N more waiting" appears if several jobs wait. Screen
  readers hear a step only when it changes; the clock is never read out. The bar reserves scroll space (`scroll-padding-bottom`)
  so a control that takes keyboard focus is never hidden behind it (measured in a real browser by
  `tests/test_focus_not_obscured.py`). The service guards its PDF work with one lock (page pictures, opening a review, starting a job), so a request can
  wait a few seconds for its turn; Auto-fix therefore shows its line at the click itself ("Sending your request to the service...", button off, Cancel
  waiting for a job to exist) and Process says it is sending the PDFs.
- **Cancel** is in the bar and in the Auto-fix line. It reads "Cancelling..." after it is pressed, cannot be pressed twice, and
  comes back if the service refuses (the reason is shown). The old "Processing activity" cards are gone; a failure with no
  reported reason now says so and names `application.log` in the review-app folder.
- **Auto-fix on a document with nothing to repair** says plainly that nothing could be repaired automatically, that automatic
  mode changed nothing, and how many checks still need a person.
- **Home and Reset.** A labelled **Home** button in the top bar does what the logo does. **Reset** in the top bar goes to the start
  screen and clears it. On the start screen **Reset choices** (next to Process) clears the chosen PDFs and puts every option back to
  its normal setting; both send nothing to the service and leave saved documents, originals and running jobs alone. Process now
  refuses to run with nothing chosen. Leaving a review with Home, Reset or "All documents" never asks about unsaved fields.
- **Documents with an empty form shell and ordinary links** (a Word guide with a table of contents, for example) are no longer
  refused as interactive forms; see the paragraph on inert empty containers below (evidence policy `passive-empty-acroform-2`).
- **If the local service disappears** (it crashed, or the PC slept) the page no longer shows a bare "Failed to fetch" and a
  frozen bar: it says the service is not responding, that saved documents stay on this computer, and to close the window and
  open the program again; the bar and the Auto-fix line are removed and Cancel stops pointing at a job that is gone.
- **Tests.** The Node page tests (`scripts/test-web-assets.cjs`) cover every new control. `scripts/e2e-browser.cjs` drives the
  real page against the real service in a headless browser (run through `tests/test_e2e_browser.py` when its environment variables
  are set). What only a person can check is listed in `TESTING-TODO.md`.

## Current October 28: consented Content Credentials working copies

A new, explicit **Create separate copy without credentials and recheck** action handles one independently proven catalog-associated C2PA manifest. The unchanged original PDF, exact inert credential payload, named consent and removal proof are retained privately. The resulting working copy has a new source identity and does not carry the original Content Credentials or any old accessibility approval. The program does not verify the credential, its signer or its claims.

Ordinary Fix and OCR continue to protect credential-bearing originals. The separate-copy action requires exact current revision, original SHA, assessment context, an explicit checked removal choice and a reviewer name. It starts a new review with AI and OCR off. Changed, stale or unapplied choices cannot silently become removal consent. All pages, text, links and bookmarks must remain exact before the new copy enters ordinary remediation.

The initial scope is a single supported, unfiltered C2PA-associated file with no extra attachment, alias, signature, active action or unproved metadata claim. Other attachments remain guarded. Ordinary proven Link URI/local destinations are retained without execution. This producer's exact double-encoded MIME name and ordinary false IsMap flag are covered as explicit preserved cases. No generic attachment stripping, credential re-signing or authenticity claim is offered.

Consent and original-source lineage remain visible through recheck, supported Apply, reopen and export. Fresh required manual review remains pending; creating this copy does not prove accessibility. OCR-editor chaining on this new credential-derived lineage is explicitly refused until separately qualified; existing ordinary OCR editing retains its own scope.

Qualification and actual Windows outcomes are bound to the exact source freeze in the private validation packet content-credentials-20261028-01/qualification.json. Its full-suite, native-case and source-application receipts identify the tested bytes and actual results. The earlier dated sections below keep their original scope. The existing twelve external acceptance/development groups and visible-workflow, fresh-PC, human/assistive-technology/LMS, licensing, signing and release gates are not closed by this feature. Ask before opening the software or using the desktop.

---

## Current October 27 small-text measurements and reviewed empty-tag removal

New results include an optional small-text screen and **Empty-tag controls**.
The font screen reports supported digital text strictly below 9 points, with
page, sample, effective size, uncertainty and bounded coverage evidence. Exactly
9 points is not flagged. This is an advisory screen, not a universal WCAG font
minimum, a complete readability assessment or an automatic resize/reflow tool.
Images/scans, unsupported mappings or transformations and unproved measurements
remain explicit review cases. A confirmed readability problem needs an authoring
source change, wrapping/layout review, a separate PDF export and fresh checks.
Page paint is preserved; the tool never silently enlarges text.

Empty-structure assessment facts are separate from removal authority. An empty
appearance does not make descriptions, alternate text, IDs, attributes, references
or semantic roles disposable. Broken or dangling MCID/MCR/OBJR references are not
repaired by deleting their tags. A complete source with no actual absent/null/
empty-array candidates need not manufacture an empty-tag editor row.

Supported removal is limited to an existing independently proven empty P or Span
leaf with absent, null or empty-array K, unique source/parent ownership and safe
Document/Part/Sect/Div ancestors. Its existing parent retains original child order,
at least one child and an independently content-bearing sibling. The bounded
limits are 100 selected removals and 200 children per parent. Protected/shared,
described, named, semantic, content-bearing or otherwise unproved cases stay
read-only with source-repair guidance. The operation detaches only the selected
empty leaf's parent edge; page text, graphics, fonts, resources, geometry,
ParentTree ownership, navigation and unrelated structure remain protected.
General retagging, content deletion and broken-tag reconstruction are not offered.

The reviewer explicitly selects Keep or Remove. Save creates a pending draft;
named acceptance and a separate Apply create and check a new PDF. Keep withdraws
a saved removal without repair credit. Unsaved choices survive supported local
page/disclosure changes only while source/context and saved-value bindings match.
Delayed replies cannot gain acceptance across changed identity, capability,
revision, value/status, workspace, page/panel generation or newer input. A newer
unsaved choice blocks applying an earlier accepted removal. New removals never
gain automatic or AI authorization. Other changed structural plans require a
separate application; supported unrelated metadata choices retain their existing
explicit authority. Every applied removal creates a fresh pending human judgment.

New runs use `reviewed-empty-tags-8`. All eight older profiles and saved reviews
remain exact: 32 complete canonical inventories across four retained PDFs,
containing 19,457 decision rows, match the earlier qualified build. Original
checkpoints, saved observations and immutable earlier bundles remain preserved;
old positive authority does not transfer to newly changed artifacts.

The exact 201-file software source passed **2,814 tests in 412.34s**
with zero failures, errors or skips. All 2,568 previous test identities remain;
246 are new, and collection/execution identities match exactly.
The final focused run passed 246 cases. All **596
browser-script checks** passed within one Python test, retaining the exact old
540-title prefix and unchanged earlier case assertions. The shared HTTP double
adds only an explicit per-request Apply opt-in for the new named/separate-Apply
case; its default refusal and exact endpoint/payload/revision checks remain.
Each final full/core/collection result binds before/after hashes to the final
source freeze and exact check-runner bytes. Earlier attempts are retained.

The private Windows Python 3.14.9 application/worker trial used a fresh
independently authored 2-page licensed-font document with retained
8-point and exact 9-point controls, existing navigation and 3
supported empty tags. No server, software window, browser or desktop was used.
The actual initial strict/supplemental outcomes were
pass/pass;
no initial failure is assumed. Named removal acceptance and separate Apply,
full application reconstruction, then explicit title/global-language replay
produced passing real strict and supplemental results. The exact preparation
checkpoint remains bound across all stages; it is not assumed byte-identical
to the unprepared original. All-page zero-pixel and ordered literal fidelity
passed, the small-text advisory remained visible and the 9-point comparison was
not misclassified. Fresh required removal reviews numbered 0, 3
and 3; they remain pending. All six actual in-program preview pages
passed their current source/profile/PNG bindings and same-session cache checks.
The initial/reopened authentication signatures differ only because application
reconstruction creates a new local signing key; their full render payloads match.

Read-only inventory probes on four actual retained outputs completed without
inventory errors or changed source/input hashes. These are compatibility/timing
observations, not new human authoring or a new remediation of the full problem
PDF folder. Both final native pages were rendered, compared with the original
and visually inspected with no layout defects. Mechanical observations are not
genuine human, keyboard, screen-reader, the next accessibility checker or accessibility approval.

Qualification: `small-font-empty-tags-20261027-01/qualification-01`. Guarded source-application authority after
application: `work/small-font-empty-tags-20261027-01/source-application-01/source-application.json`.
This newly requested bounded group is complete; the existing master remains
**12 open groups: nine acceptance/distribution/final gates and three earlier
requested development groups**. The remaining development includes color-only
meaning, broader OCR/Unicode/font repair and genuine logo/OCR semantic review.
Human/assistive-technology/LMS acceptance, fresh-PC installation, licensing,
publisher authentication, final source review and owner release decisions remain
open. Existing installer and documentation launcher payloads were not rebuilt.

Originals, saved reviews and earlier changes are preserved. AI stayed off and
OCR was not run. No installation, staging, commit, merge, release or upload
occurred. Ask before opening the software. Earlier dated sections retain their
original evidence and scope.

---

## Current October 27 reviewed form labels, tooltips and navigation

New results offer **Form labels, tooltips and navigation** under Document edits.
A reviewer writes each terminal field's tooltip as its accessible name, with the
visible label included as appropriate, and may supply a separate description on
each proven existing Form tag. The printed label, internal field name, mapping
name, entered/default value, checked state, options and appearance stay intact.
The program does not fill fields, rename them, infer a name from their value or
rebuild missing visible labels.

The bounded route supports ordinary AcroForm text fields, choice fields and
simple checkboxes, including a text/choice field represented by multiple widgets.
A terminal field has one shared tooltip; each widget retains its own uniquely
proven Form/OBJR owner and can have its own reviewed optional description.
The tooltip is the terminal field's own /TU entry. An ancestor /TU is preserved
but is not inherited, copied into the editor or counted as the control's name.
Inherited field type and flags remain read-only. A description is not a substitute
for an accessible field name, and measured nonblank text does not prove meaning.

One complete source-bound plan retains every original field, widget and page.
Changed tooltips must be nonblank; changed optional descriptions may be removed
or must be nonblank. Newly changed text is limited to 4,000 Unicode code points
and excludes unsupported controls/surrogates. Unchanged supported raw strings,
including Unicode, CRLF and existing long strings, remain exact when the complete
plan fits. Textarea newline display cannot silently normalize an untouched value.
The limits are 100 terminal fields, 200 widgets, 50 pages, 100 order groups, 200
children per group and 150,000 characters for the complete canonical plan.

For keyboard navigation, a reviewer can keep a page's original setting or
explicitly choose document tag order (/Tabs /S). New row/column tab-order choices
are not presented as repairs. The whole existing page annotation/tag sequence,
including supported fixed local-destination links, is shown read-only with
source names and link destination pages. A supported control group contains
only existing same-page Form siblings under a proven neutral parent; the reviewer
can choose an exact permutation of that group. A changed group requires final
document tag order on its page. No field/annotation array is reordered, no
control or link is inserted/deleted, and links outside the group retain their
positions. Meaningful full-document reading order and actual keyboard behavior
remain human and assistive-technology judgments.

Signed/encrypted files, XFA, signature/radio/push-button fields, scripts/actions,
nonempty calculation order, ambiguous/shared field or tag ownership, missing
appearances, unsupported annotation types and other unproved cases remain
unsupported/read-only. Existing unsupported forms are not flattened or silently
passed through a tagging, OCR or catalog writer. This is bounded editing of
proven existing interactive forms; arbitrary broken or untagged form
reconstruction and visible-label authoring remain separate source-repair work.

A strictly proven inert AcroForm container with an empty Fields array, no
widgets and only passive default appearance/font resources is distinguished
from an interactive form. These narrowly supported empty containers retain the
established ordinary processing route and produce no form-edit controls. Active,
orphaned, XFA, unknown and otherwise unproved empty-looking containers remain
guarded. This does not turn a missing or broken interactive form into an inert
document or permit its contents to be flattened or discarded.

Ordinary navigation does not make an empty container look like a form. A page
link or bookmark whose only action is a jump inside the document, or a web or
mail address (http, https, mailto), is passive navigation and no longer counts as
form authority, provided nothing else refers to that action. Every other action
type, any chained action or extra key, and any action outside the page links and
bookmarks still does. The same proof accepts the standard passive structure
attributes that Word, the desktop PDF viewer and this program's own tagging write (figure and
table position, header-cell scope and spans, list numbering) and structure
elements that omit the optional /Type, and still refuses every other attribute.
The evidence policy is passive-empty-acroform-2.

The application retains the exact interactive original as its preparation
checkpoint. Initial processing makes no implicit title/language, catalog,
tab-order, tagging or OCR changes. Accepted form edits and later reviewed
title/global-language edits replay from that unchanged checkpoint. Exact live
and independently encoded reopened graph proofs permit only the accepted /TU,
Form /Alt, page /Tabs and selected Form-child order changes, plus compatible
explicit metadata choices. Existing values/defaults, names/mapping names,
flags/options, appearances/resources, annotation/field order, ParentTree owners,
unselected structure/navigation, original inputs and earlier bundles/reviews
remain protected. Strict all-page literal/pixel fidelity is unchanged.
Supported form widgets are initialized for actual appearance rendering before
any page is accessed, with a null JavaScript platform, XFA disabled and no
document/page actions invoked. Fidelity and previews include the rendered field
appearances; an independently seeded appearance-only negative must be detected.
Unsupported/unproved form rendering cannot silently earn a body-only pixel pass.
The versioned preview cache keeps older images and avoids reusing their earlier
body-only renderer profile.

Save the complete plan, give named acceptance, then separately Apply accepted
edits. Source occurrence, graph/capability context, original checkpoint, revision
and named acceptance stay bound. Unsaved fields and sequences survive local
page/panel changes only while their source binding and saved value match.
Delayed replies cannot accept a different saved value/status/revision, cross a
workspace, or overtake newer typing. Exact-original restoration withdraws a
draft without repair credit. Every actual form change creates a fresh required
pending review of visible labels, tooltips/descriptions, state/value
preservation, keyboard focus and reading order. Old observations stay attached
to earlier reviews while old positive authority is invalidated.

New runs use `reviewed-form-7`. All seven older profiles and saved reviews remain
exact: 28 complete canonical inventories across four retained
PDFs (15,534 decision rows) match
the earlier build. Older saved inventories are not silently widened. The
older-profile refusal of new form editing authority stays explicit.

The exact 194-file software source passed **2,568 tests in 621.74s**,
with zero failures, errors or skips. All 2,256 previous test identities remain;
312 are new, with exact collection/execution agreement. All
**540 browser-script checks** passed within one Python test,
retaining all 475 earlier titles. The final targeted run passed 312
tests. Earlier attempts and their source/evidence remain retained.

The private Windows Python 3.14.9 application/worker check used a fresh
independently authored 2-page populated form with multiple field
types, repeated widgets and a fixed local link. No server, browser or desktop
was used. Initial processing retained a byte-identical original checkpoint and
deliberately failed the real strict/supplemental checks for seeded missing form
names. Named form acceptance and separate Apply, application reconstruction,
then title/global-language replay produced passing strict and supplemental
checks. Exact all-page text/pixel fidelity passed at all three stages; values,
default/checked states, names, options, appearances and unrelated structure/
navigation stayed intact. Fresh required form reviews numbered 0, 1 and 1 and
remained pending. These are mechanical developer observations, not genuine
human, keyboard/screen-reader or accessibility approval.

Read-only inventory probes on four retained results completed without inventory
errors or changed Python source/input bytes. They qualify timing/compatibility
and the reported bounded controls/refusals, not new human authoring on those
documents or a new repair of the full problematic-PDF folder. The final probes
for retained cases c07 and c12 explicitly found zero form-control rows after
the inert-container correction, with the source and input hashes unchanged.
Earlier probes and complete-suite/native attempts retain their earlier scope.
All final native
pages were rendered, compared pixel-for-pixel with the original and visually
inspected; no layout change was found.

Qualification: `form-controls-20261027-01/qualification-01`.
Guarded source-application authority after application:
`work/form-controls-20261027-01/source-application-01/source-application.json`.
The master checklist credits this bounded development group. Twelve grouped
items remain: nine acceptance/distribution/final gates and three further
requested development groups. Genuine form judgments, graphical/keyboard,
actual-user/assistive-technology/LMS feedback, fresh-PC, distribution and final release
gates remain open. Existing installer and documentation .bat payloads were not
rebuilt.

The institution's planned move to the institution's next accessibility checker adds its published PDF checklist
as an external acceptance reference. Its explicit PDF rules reinforce headings,
tables, reading order, language, links and form tooltip work already on this
roadmap. No result has been tested in the next accessibility checker, and no vendor score or WCAG
conformance is implied. Disabled vendor defaults do not remove the need for
human judgment. AI stays off. Vendor reference:
(vendor page)

Originals, saved reviews and existing changes are preserved. AI stayed off and
OCR was not run. No software window, browser or desktop was used; no installation,
commit, merge or release occurred. Ask before opening the software. Earlier
dated sections retain their original scope and evidence.

---

## Current October 27 reviewed table header associations, IDs, spans and summaries

New results offer **Table headers, spans and summary** controls under Document
edits. A reviewer can select TH/TD roles, optional Scope direction, explicit cell
IDs, multiple header associations including parent headers, row/column spans and
an optional table summary. Header selections refer to existing source cells;
renaming an explicit ID keeps its chosen relationships attached to those same
cells. Meaning, IDs, associations and summary text are chosen by the reviewer.
No relationships, cell contents, labels or summaries are guessed.

One complete source-bound table plan retains every original row and cell exactly
once in the original order. Supported spans must form a complete rectangular
grid and stay within the original row-group identity, including separate groups
sharing the same role. IDs must be unique throughout the document; new IDs use
explicit bounded ASCII names. Selected header targets must be named TH cells,
and the association graph must have no cycles. Scope-only simple tables do not
require invented IDs. Unresolved original links must be cleared or explicitly
replaced before a changed plan can be accepted. Exact original restoration can
withdraw a draft without granting repair credit.

The supported bounds are 100 rows, 500 existing cells, 100 columns, spans of at
most 100, 32 header selections per cell, 128 characters for newly changed IDs,
4,000 Unicode code points for newly changed summaries and a 150,000-character
canonical plan. Unchanged supported source ID bytes and raw source summaries
are preserved, including line endings and existing long summaries when the
total plan fits. Actual textareas retain Unicode and multiline text; their
display newline normalization cannot silently alter an untouched source value.

This is bounded authoring of proven existing tagged tables, not reconstruction
of arbitrary visual tables. Cell/tag/text movement, splitting, insertion and
deletion are not offered. Nested parent tables, ambiguous/shared attributes or
carriers, unsafe aliases, unsupported forms/annotations/marked content and
other unproved cases remain read-only. Unsupported sources need a separate
source-repair workflow; refusing them does not establish their accessibility.

Save the whole plan, give named acceptance, then separately Apply accepted
edits. Source identity, capabilities, original checkpoint, revision and named
acceptance remain bound. Unsaved partial fields survive local page/collapse
changes only while the binding and saved value match. Delayed replies cannot
carry acceptance across changed context, workspace, page/panel generations,
active jobs or newer typing. Every actual table change creates a fresh required
pending human review of the full grid, roles, IDs, associations and summary.
Old observations remain in earlier reviews while old positive authority is
invalidated; neither a valid graph nor equal page images proves correct meaning.

New runs use `reviewed-table-6`. All six older profiles remain exact: complete
canonical inventories for six profiles on four retained PDFs (24 inventories,
11,611 rows) match the previous build. Older saved reviews are not
silently widened. Compatible title/language/navigation/tree choices can replay
from the retained checkpoint; conflicting or unsafe combinations are refused.

The live writer and independent reopened encoded-graph oracle permit only the
exact reviewed Table/TH/TD metadata and required ID-index entries. Existing
IDTree structure, outside IDs, MCIDs, ParentTree owners, literal text, painting,
resources, geometry, navigation, annotations and earlier reviews/bundles stay
protected. No content-stream or pixel-fidelity relaxation was added.
Changed table exports declare at least PDF 1.7, preserving higher source versions
and unchanged metadata bytes. The reopened proof also refuses under-declared or
downgraded exports. Exact no-op and older-profile exports keep their previous scope.
An initial mechanical run passed before this declaration gap was identified;
its full test/native evidence remains retained separately from the final rerun.

The exact 188-file software source passed **2,256 tests in 523.06s**,
with zero failures, errors or skips. All 2,119 prior test identities remain;
137 are new, with exact collection/execution identity agreement. All
**475 browser-script checks** passed within one Python test, retaining all
398 previous titles. The final targeted core run passed 45 tests.
All unsuccessful attempts and exact source versions remain retained.

Read-only probes on four retained results completed without inventory errors or
changed inputs, reviews or Python source bytes. Those examples contain no tagged
Table candidates for these new controls. This checks timing and compatibility;
it does not qualify authoring on those real documents or a new folder-wide repair.
Both pages of the final native fixture were rendered, compared pixel-for-pixel
with the original and visually inspected; no layout change was found.

The final private Windows Python 3.14.9 application/worker flow used a fresh
independently authored two-page table fixture, with no server, browser or
desktop. Initial processing deliberately retained incomplete table structure:
the real strict and supplemental checks completed and failed as expected.
Named table acceptance and separate Apply, full application reconstruction,
then title/global-language replay produced passing strict and supplemental
checks. Exact all-page pixel/literal fidelity passed at all three stages, with
fresh required table reviews 0, 1 and 1 remaining pending. This is mechanical
developer evidence, not genuine human or accessibility approval and not a new
remediation of the entire problematic PDF folder.

Qualification: `table-structure-controls-20261027-01/qualification-01`.
Guarded source-application authority after application:
`work/table-structure-controls-20261027-01/source-application-01/source-application.json`.
The master checklist credits this bounded development group. Thirteen grouped
items remain: nine acceptance/distribution/final gates and four further
requested development groups. Genuine table judgments, graphical/keyboard
workflows, actual-user/assistive-technology/the LMS checker, fresh-PC, distribution packaging
and final release gates remain open. Existing installer and documentation .bat
payloads were not rebuilt.

Originals, saved reviews and existing changes are preserved. AI stayed off and
OCR was not run. No software window, browser or desktop was used; no installation,
commit, merge or release occurred. Ask before opening the software. Earlier
dated sections retain their original scope and test evidence.

---

## Current October 27 semantic lists, tagged reading order and tree edits

New results offer **List, reading order and tree edits** under Document edits.
Reviewers can correct supported headings, including pure-text span containers,
to paragraphs; repair bounded existing list roles; reorder proven existing tag
children; move eligible text tags between neutral same-page groups; and build a
list from explicitly selected existing body and optional label tags. Labels,
pairings, order and meaning are chosen by the reviewer, never guessed.

List construction replaces one contiguous union of source sibling text nodes
with new L/LI wrappers. Existing label/body nodes become Lbl/LBody, retaining
their identities, MCIDs, ParentTree owners, content and language. Explicit item
row order can differ from the original order. List numbering is selected from
the supported PDF styles. At most 50 list items and 100 source children are
supported in a plan. No text, labels, MCIDs or content streams are invented,
split or deleted. Existing list-role corrections require a valid final L/LI/
Lbl/LBody relationship, including joint correction of a mislabeled LI wrapper.

Reading-order edits are exact child permutations in eligible existing groups.
Proven Figure atoms retain their existing alternatives, bounds and image bytes.
Moves preserve the effective language and leave the source parent nonempty;
scalar single-child destinations and uniquely owned indirect child arrays are
supported. Overlapping parent operations and conflicting role edits are refused.
Unsupported/shared/Form/annotation, protected attributes, ambiguous inheritance
and unsafe aliases remain read-only. Text-only heading containers are supported;
image-containing headings are not silently converted to paragraphs.

Source, original checkpoint, node occurrence, capabilities, revision and named
acceptance remain bound. Save a draft, give named acceptance, then separately
Apply accepted edits. Structured drafts survive page/collapse changes locally
only while their source binding and saved value still match. Restoring the exact
original plan withdraws a draft without granting repair credit. Every actually
changed semantic decision creates a fresh required pending review of roles,
label/body pairing, numbering, context, language and the full reading sequence.
Tree grammar and equal page images do not prove meaningful or accessible order.

New runs use `reviewed-semantic-tree-5`. All five older profiles and their saved
reviews remain exact; older inventories are not silently widened. New navigation
fidelity accepts only the actual explicit navigation-capable profile, including
this new profile, and recollects that same scope. Prior navigation, language,
metadata and compatible typed edits can coexist or replay from the retained
checkpoint. Unsafe combinations are explicitly refused, including moves that
would change inherited language after other accepted language edits.

Live and independently encoded reopened graph proofs allow only the selected
roles, child order, parent links and new list wrappers/attributes. Root, child
array, ancestor and ParentTree carrier ownership are checked. Existing content,
resource bytes, page geometry, navigation and annotations stay protected. The
strict all-page fidelity screen is unchanged for tree-only edits; no navigation
or pixel allowance was added for semantic operations. Proof bounds disable
unsupported new controls without creating a document-wide page-count refusal.

The exact 183-file software source passed **2,119 tests in 380.45s**, with
zero failures, errors or skips. All 1,971 earlier identities remain; 148 are new,
and collected/executed identities match. All **398 browser-script checks** passed
within one Python test, retaining all 344 previous titles. Final targeted core
checks passed 59 tests, including both heading/span cases. An earlier broader
targeted run passed 215; its first attempt had two valid scalar-child cases
incorrectly blocked, which were fixed without weakening their assertions.
An intermediate complete 2,117-test run also passed before the final heading
container guard. All attempts and source versions remain retained.
One later full run hit Windows access denied during an existing updater test's
directory replacement. Its rollback restored and verified the previous test
package; all 49 updater checks then passed in a fresh location. The unchanged
final source subsequently passed the complete suite reported above. No updater
code or refusal/rollback assertion was weakened.

Twenty complete canonical inventories (five older profiles across four retained
PDFs, 7,688 rows) are identical. Fresh read-only probes took 0.022-16.101 seconds,
including a 20-page result, without inventory errors or changed code/input bytes.
All new controls stayed read-only on those four examples. Those probes qualify
bounded refusal and timing, not editable real-document or browser responsiveness
acceptance, and are not a new remediation of the full 17-PDF problem folder.

The final private Windows Python 3.14.9 flow used a fresh independently authored
two-page fixture with H2 containing a text Span that owns the original MCID.
It completed initial processing, four accepted semantic changes and later title/
global-language replay, with full application reconstruction. All real strict,
supplemental and exact all-page fidelity checks passed at every stage. MCID
numbers and ParentTree owners, literal text, painting, resources, geometry,
navigation and prior bundles/reviews remained intact except the exact selected
tree changes. Fresh required semantic judgments numbered 0, 4 and 4 and stayed
pending. This is mechanical developer evidence, not human accessibility approval.

Qualification: `semantic-tree-controls-20261027-01/qualification-01`.
Guarded source-application authority after application:
`work/semantic-tree-controls-20261027-01/source-application-01/source-application.json`.
The master checklist credits this bounded development group. Fourteen grouped
items remain: nine acceptance/distribution/final gates and five further requested
development groups. Complex table associations, IDs, spans and summaries are next.
Graphical/keyboard/assistive-technology/the LMS checker, fresh-PC, packaging and final release
gates stay open. Installer and documentation .bat payloads were not rebuilt.

References: [W3C PDF21](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF21),
[PDF3](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF3) and
[PDF9](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF9).
Originals, saved reviews and existing changes are preserved. AI stayed off and
OCR was not run. No software window, browser or desktop was used; no merge or
release occurred. Ask before opening the software. Earlier dated sections keep
their original build scope and test evidence.

---

## Current October 27 link, annotation and bookmark authoring

New results offer **Link, annotation and bookmark edits** under Document edits.
Annotation descriptions (/Contents) and alternative Link names (the uniquely
owned Link structure element's /Alt) are separate reviewed choices. Visible
page text is not rewritten. Existing supported links can receive an explicit
local page or encoded HTTP/HTTPS/mailto target. Safe missing/unresolved passive
destinations can be repaired; script, chained, mixed and unknown actions remain
read-only. Addresses are not opened, fetched or checked for live availability.

Existing supported bookmarks can be renamed or retargeted while keeping their
position, children, style and unselected attributes. A title-only edit keeps
the exact original destination representation, including named destinations,
fit and zoom. A target-only edit keeps the original title bytes. Add a separately
reviewed new bookmark forest after the existing root entries: title, page and
level, up to 200 additions and ten levels. Existing entries are not deleted or
reordered. New titles and meaningful section coverage are not guessed.
The plan must also fit the bounded total payload and existing web-request size
limit; large Unicode-heavy plans may need fewer rows.

Save the draft, give named acceptance, then separately Apply accepted edits.
Exact original invalid values can be restored to withdraw a draft; this leaves
the original problem unresolved and grants no repair or semantic credit. Partial
bookmark drafts survive preview-page navigation locally while their source
binding and saved value remain unchanged. They are not automatically saved or
accepted. Stale responses cannot restore them against a changed binding.

New runs use `reviewed-navigation-4`. All four older inventory profiles and
saved reviews remain exact; old reviews are not silently expanded. Source,
prepared bytes, occurrence, capabilities, revision and named acceptance remain
bound. Direct/shared/malformed annotation identities, unsafe aliases, forms,
signatures, rich-text/popups and unproven Link ownership remain read-only with
explanations. Complex or malformed outline relationships require source review.
Proof bounds disable only unsupported new controls, not established processing.

Live and independently encoded reopened graph oracles permit only the named
description, alternative name, destination and necessary new outline edges.
Unselected content/resources/relationships and the ParentTree stay exact. The
independent all-page fidelity screen accepts only exact reviewed navigation
deltas and retains raw original-preservation findings; no general navigation
ignore flag or pixel tolerance was added. Unselected annotations, named
destinations and page labels remain protected. Each changed navigation decision
creates a fresh required pending purpose/coverage review bound to the final
artifact. Syntax and valid page numbers do not prove meaningful labels, correct
destinations, keyboard access, adequate coverage or accessibility.

The exact 179-file software source passed **1,971 tests in 351.89s**, with
zero failures, errors or skips. All 1,829 prior identities remain; 142 are new,
and collection/executed identities match. All **344 browser-script checks** passed
within one Python test, retaining all 264 previous titles. The focused Python
suite passed 177 tests against identical final Python files. The first retained
attempt passed 124 cases and failed ten new fixture setup cases; those used an
unsupported PDF-dictionary removal method and were corrected without removing
assertions or tests. Subsequent static audits added malformed-type, maximum-size,
untagged-source, exact-encoding and draft-recovery protections before final tests.
An intermediate DOM run caught a newer bookmark draft being lost after Save;
the response handling was fixed and every final DOM case passed. Earlier source
versions and failed-attempt evidence remain retained.

Sixteen complete canonical inventories (four older profiles across four retained
PDFs, 5,135 decision rows) are identical. Read-only new-profile probes took
0.015-7.604 seconds, including a 20-page result, with no inventory errors or
changed source/input bytes. Those four examples have no existing link/comment/
bookmark entries; they qualify timing/refusal and append-capability behavior,
not editable existing-navigation coverage. They do not represent a new
remediation or semantic approval of the full 17-PDF problem folder.

An independently authored two-page Windows fixture exercised all five kinds in
the private Python 3.14.9 Application worker: initial result, named navigation
Apply and later title/global-language replay, with full application reconstruction.
All real strict and supplemental validators and all-page fidelity passed at
every stage. Existing outline style/custom attributes, earlier bundles, notes,
saved reviews, text, painting, geometry, resources and ParentTree stayed intact
except the exact named navigation changes. Fresh required navigation judgments
numbered 0, 5 and 5 and remained pending in the new results. This is mechanical
developer evidence; actual-user, speech, keyboard and the LMS checker acceptance remain open.

Qualification: `link-bookmark-controls-20261027-01/qualification-01`.
Guarded source-application authority after application:
`work/link-bookmark-controls-20261027-01/source-application-01/source-application.json`.
The master checklist credits this bounded development group. Fifteen grouped
items remain: nine acceptance/distribution/final gates and six further development
groups. Semantic list/reading-order/tree and heading-to-paragraph editing is next.
Graphical/assistive-technology, fresh-PC, packaging and release gates stay open.
Existing installer and documentation .bat payloads were not rebuilt.

References: [W3C PDF11](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF11),
[PDF13](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF13) and
[PDF2](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF2).
Originals and saved reviews are preserved. AI stayed off and OCR was not run.
No software window, browser or desktop was used; no merge or release
occurred. Ask before opening the software. Earlier dated sections retain their
original build scope and test evidence.

---

## Current October 27 page and passage language controls

New results offer **Page and passage languages** under Document edits. Reviewers
can set a well-formed language tag or explicitly choose to inherit the parent
language. Save the draft, give named acceptance, then separately Apply accepted
edits. Current, inherited and effective language are distinguished. Global
document language remains a separate control. No language, translation or
pronunciation is inferred or automatically approved.

A passage is an existing uniquely owned single-page leaf text element with
proven direct-page MCIDs. A page control requires an existing page-exclusive
grouping container with proven complete content coverage. Set changes only that
element's own /Lang; inherit removes only that element's own /Lang. Explicit
descendant language exceptions are retained. No tags are invented or split and
no page-dictionary /Lang is written. Arbitrary text selections, shared,
multi-page, Forms, inline-language, replacement-text, unsafe aliases and
unprovable scopes remain read-only with explanations. Bounded proof failure
does not block established processing.

New runs use `reviewed-passage-language-3`. All three preceding inventory
profiles remain byte-for-byte compatible; saved reviews are not silently
expanded. Source, checkpoint, scope, revision, capabilities and named reviewer
remain bound. A later title/global-language edit replays accepted local changes
from the retained original checkpoint. Every changed local decision creates a
fresh required pending semantic review bound to the final artifact. Earlier
positive review authority is invalidated without deleting observations; a new
artifact does not inherit earlier human approvals or notes.

Language screening now considers proven tagged language inheritance within the
bounded represented text sample. Actual structure ancestors and the document
default determine inheritance; arbitrary TreeRoot language properties do not.
Unowned, ambiguous, inline and unrepresented text cannot establish local
agreement. Known wrong scopes still fail and uncertainty remains reviewable.
Local diagnostic suggestions never become a proposed document-wide language.
Missing/invalid global language remains a separate blocker. A well-formed tag
and heuristic agreement do not prove correct language, speech or accessibility.

The exact 175-file software source passed **1,829 tests in 278.32s**, with
zero failures, errors or skips. All 1,722 prior test identities remain and 107
are new; collection and executed identities match. All **264 browser-script
checks** passed within one Python test, retaining all 234 earlier titles. The
focused suite passed 237 tests. Twelve complete canonical inventories across
three older profiles and four retained PDFs stayed identical. Four read-only
new-profile probes retained all source/input hashes. These are not a new
remediation or semantic approval of the full 17-PDF problem folder.

A private Windows Python 3.14.9 worker completed four background Application
jobs on an independently authored two-page mixed-language fixture: initial
wrong declarations; page French while preserving a wrong explicit passage;
named passage inheritance; then title/global-language replay. The first two
local screens failed and the last two agreed. Real strict and supplemental
validators completed at every stage, with no new failures. All-page literal,
pixel and geometry fidelity passed; exact graph proof allowed only the selected
/Lang changes. Original sources, saved reviews and prior bundles stayed intact.
Fresh local semantic reviews numbered 0, 1, 2 and 2 and remained pending in the
new results. This is mechanical developer evidence, not user, speech or
accessibility acceptance. Strict outcomes: {"inherit": "pass", "initial": "pass", "metadata": "pass", "page": "pass"}.
Supplemental outcomes: {"inherit": "pass", "initial": "fail", "metadata": "pass", "page": "fail"}.

Qualification: `passage-language-controls-20261027-01/qualification-01`.
Guarded source-application authority after application:
`work/passage-language-controls-20261027-01/source-application-01/source-application.json`.
The master checklist credits this bounded language-development group. Sixteen
grouped items remain: nine acceptance/distribution/final gates and seven further
development groups. Link/annotation names and bookmark authoring are next.
Graphical/keyboard checks, actual-user/assistive-technology/the LMS checker acceptance,
fresh-PC, packaging and release remain open. Installer and documentation .bat
payloads were not rebuilt. Earlier dated sections retain their original scope.

AI stayed off; OCR was not run. No software window, server, browser or desktop
was used; no merge or release occurred. Ask before opening the software.

---

## Current October 27 decorative figures and document containers

New results include **Show figure purpose and structure controls for this page and
document** under Document edits. Keep a meaningful figure, or explicitly choose
**Mark decorative artifact** for an eligible existing occurrence. The picture
stays visible. Existing eligible grouping containers can be corrected to Document
at the single logical root or Sect within the document. Save, give named
acceptance, then separately Apply accepted edits. No role or decorative purpose
is inferred. A meaningful logo can retain its reviewed figure description.

The new profile is `reviewed-artifacts-structure-2`. Both previous profiles and
their saved reviews keep exact inventories; older reviews are not silently
widened. Prepare a separate new result from the unchanged original for the new
controls. Source, staged bytes, occurrence, capabilities, revision and reviewer
remain bound. Every actually changed new decision creates a fresh required,
pending purpose/role review tied to the final artifact. Named edit acceptance
does not establish complete semantic or accessibility approval.

Decorative conversion is bounded to a uniquely owned nontext leaf Figure with
one direct-page MCID, supported image/vector paint and a grouping parent that
remains nonempty. It replaces only the selected content marking, detaches that
leaf and nulls its existing ParentTree slot without renumbering other MCIDs.
Text-bearing, shared, ambiguous, nested, replacement-text, Forms/OBJR and unsafe
relationship cases remain read-only. Root and section edits change existing
eligible role names without creating, moving or reordering children. Target
RoleMap remaps and mutable object aliases are refused. A saved decorative choice
can return to Keep meaningful figure through its retained original checkpoint;
removed structure is not guessed or reconstructed.

Figure bounds are **read-only diagnostics**: declared, missing, invalid or
unresolved Layout BBox information. A finite in-page declaration does not prove
fit to the actual picture. No geometry is invented or written. Full-graph proof
limits disable only new controls with an explanation; established processing
continues. There is no new 200-page refusal. Supported JPEG/opaque resources bind
exact encoded bytes and codec parameters when decoded bytes are unavailable.

Live and reopened graph proofs check exactly authorized edits, all unselected
relationships and resource payloads. Final strict, supplemental and all-page
fidelity gates remain required. Ordinary title/language, heading/table and
unrelated description edits can coexist or replay later; changing a description
and marking that same Figure decorative is refused. Original text, painting,
page geometry, navigation and annotations remain protected. Scan blockers remain.

The exact 168-file software source passed **1,722 tests in 259.32s**, with
zero failures, errors or skips. All 1,639 prior test identities remain; 83 are new,
and collected/executed identities match. All **234 browser-script checks** passed
within one Python case, including all 211 previous titles. The final focused
suite passed 134 tests. Earlier attempts remain retained: a new test's escaped
JSON expectation and inspection key were corrected, a real compressed-image
inventory failure was repaired, and the old new-run profile expectation was
updated while strengthening exact retention of its previous controls.

A real private Windows Python 3.14.9 worker flow used an independently authored
two-page fixture, with no server/browser/desktop. Strict and supplemental checks
failed initially, passed after Document/Sect/decorative Apply and passed after
a later title Apply. All fidelity checks passed; four fresh semantic checks stayed
pending in each new result. Earlier bundles, notes and saved reviews remained
unchanged. This is mechanical developer evidence, not actual-user acceptance.

Eight complete canonical old-profile inventories on four retained PDFs remain
identical. New-profile inventory probes on those PDFs took 0.008–3.367 seconds,
including a 20-page result; unsupported occurrences stayed read-only. This is not
a new remediation or semantic approval of the full 17-file folder.

Qualification is retained under the ignored development directory
`artifact-structure-controls-20261027-01/qualification-01`. After guarded
application the authority is
`work/artifact-structure-controls-20261027-01/source-application-01/source-application.json`.
No future receipt hash is invented. Documentation is a separate reviewed overlay:
the master checklist receives a bounded reconciliation; other prior bodies remain
verbatim. This completes the first requested authoring group within item #2;
passage-specific language is the next group. Graphical/keyboard checks of these
new controls, actual-user/AT/the LMS checker, fresh-PC, distribution and release gates remain.

Originals and saved reviews are preserved. AI stayed off and OCR was not rerun.
No software window or desktop was used, and no merge or release occurred. Existing
installer and documentation .bat builds remain unchanged. Ask before opening the
software in future. Earlier checkpoints follow with their original dated scope.

---

## Current October 27 saved-review note preservation

- [x] Fix silent note loss in older reviews and during acceptance invalidation.

Manual notes now remain attached to their existing review when bound evidence
changes or becomes unavailable. Confirmed problems remain blocked. Positive
approvals become pending, with reviewer/date authority and acceptance bindings
cleared; their notes survive. Title or figure-description changes also retain
earlier positive observations while requiring new review. Stale review history
records retained notes without requiring corrected-source OCR lineage.

Unchanged saved reviews reopen without migration or rewriting. Repeated checks
are stable once the recorded reasons settle. Restoring old bytes does not restore
approval. Stale editing, acceptance, export, Apply and download safeguards remain.
Notes do not transfer as approval to a new result. Explicit user note replacement
retains its earlier behavior. This prevents future silent loss; already-erased
notes are not recreated automatically from history.

The exact 164-file software source passed **1,639 tests in 227.87s**, with
zero failures, errors or skips, including all 1,621 prior test identities and 18
new regressions. Collected and executed identities match. The focused review
suite passed 290 tests. The 211 browser-script checks run within one Python test,
not in addition to the total. New application-reconstruction and authenticated
download checks run in memory with authored fixtures and synthetic gate records.
The three new application regressions fail on the unchanged old program because
notes disappear, then pass with this fix. One first-attempt test expectation
about a legitimate reason-set transition was corrected; all earlier attempts and
their tested bytes remain retained. No approval assertion or safety gate weakened.

The first complete run recorded 1,635 passes and four setup errors from one cached
authored-fixture Windows file-replacement access denial. Its exact cause remains
unproven. All 24 affected-file tests then passed in fresh temporary storage, and
the complete unchanged-source retry passed all 1,639. No fixture, permissions,
antivirus policy or test selection was changed to obtain that result.

The qualification is retained under the ignored development directory
`legacy-review-notes-20261027-01/qualification-01`. After guarded application,
the source application authority is
`work/legacy-review-notes-20261027-01/source-application-01/source-application.json`.
No future receipt hash is asserted here. These three documentation prefixes are
reviewed separately; prior document bodies remain byte-for-byte unchanged.

Originals and existing saved reviews remain preserved. AI stayed off, OCR was not
rerun, and no software window, browser or desktop was used. No new native PDF,
graphical, user, screen-reader, the LMS checker, packaging, distribution or release acceptance
is claimed. The documentation .bat and existing installer remain on their earlier
builds. No commit, merge or release occurred. This completes the known older-review
note issue; requested PDF repair controls are the next sequential workstream.

**Earlier checkpoints follow verbatim.** Their old statements that this note issue
remains open are superseded by this checkpoint; other scope and gates remain.

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
document/accessibility approvals. Actual-user, assistive-technology, the LMS checker,
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
the LMS checker, fresh-PC, packaging and release acceptance retain their separate scope.
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

No graphical, fresh-PC, human/assistive-technology, the LMS checker, distribution or release
gate closes here, and no master-checklist checkbox receives new acceptance.
The application authority will be written only after reviewed application at
`C:\Users\Jason\PDFRemediator-validation\work\ocr-omissions-20261023-01\source-application-01\source-application.json`.
This checkpoint does not claim that future receipt exists or invent its hash.

**Prior-build text follows verbatim.** Earlier sections, including earlier
“current” labels, test counts, omissions and negative attempts, keep their
original build scope. The existing master checklist keeps its completed credit
and open work; this follow-up creates no new approval or release clearance.

---

# PDF Remediator development handoff

## Current October 23 scanned-page and angled-text checkpoint

The exact **151-file disposable source** passed **1,305
software tests in 164.69s**, with zero failures, errors or skips. All
**137** browser-script checks passed and are included within one Python case;
they are not added to the software total. Collected and executed node identities
match. QA selected a private copy of the exact previously qualified Node bytes;
the guard separately records the external replacement at the former active-cache
path. The cache and historical qualification records were retained.
The six documentation changes recorded here have a separate byte-reviewed
overlay; the completed suite binds its exact tested source map.

This section is the current checkpoint. Earlier October 23 test, folder and
installation sections below retain their earlier source and artifact scope.
Earlier failed attempts and independent comparison negatives remain unchanged.
No additional master-checklist acceptance or release gate is closed here.

The new application record will be written at
`work/orientation-repair-20261023-01/source-application-01/source-application.json`
only after this reviewed documentation overlay and its qualified source are
successfully applied. That completed record is the authority for the applied
**151-file source**, the preserved Git index and protected
scopes, and all linked qualification receipts. This documentation does not claim
that the future application record already exists or assign it a circular hash.

The separately built internal offline payload contains **3,812 files**,
the unchanged official artwork, private CPython 3.14.9, the exact eight-core
and 31-OCR locks, and the complete 138-file native OCR factory. Real CLI checks
used this payload locally with AI off. This is prepared-host developer evidence;
new graphical/fresh-PC, user/assistive-technology/the LMS checker and distribution clearance
retain their separate requirements.

The new **Scanned text → Add text only on wholly scanned pages** option
(`textless`) inspects every page and selects image-bearing pages proven to
contain no extracted or painted text. The native OCR route receives that exact
page list. A mixed document's existing text stays in place while its wholly
scanned cover can gain selectable text. Pages containing existing text remain
excluded, including images on those pages whose words still need another
supported repair or an accessible source document.

Every selected page must gain text. Every original token must remain, and
excluded pages must gain no tokens. Exact all-page appearance, page geometry,
navigation and annotation checks remain required. The optional **Scan layout →
Tilted or vertical text** (`angles`) uses bounded local recognition alternatives
from the same engine and a mechanically validated invisible text layer.
Retained native word evidence, placement, Unicode/font mapping and fixed
implementation bindings are checked. These safeguards leave word accuracy,
completeness and reading order for review. Original page painting stays intact.
The layout supports wholly scanned pages and the existing scan-only skip route;
the redo combination is refused before processing.

OCR stays off by default, Standard stays the default layout, and the optional
ruled-table profile retains its existing limits. English OCR runs locally
inside the program with AI off. The mode and layout belong to preparation and
saved-review provenance. Retry keeps saved settings; changing either requires
a separate result and cannot adopt edits or approvals from another preparation.
An older review missing a layout remains Standard only when its other
provenance matches. Existing saved reviews are not rewritten. Unavailable OCR
disables all OCR routes and the layout control. A logo can receive a reviewed
figure description through the normal description workflow without OCR.

The two difficult examples were first processed with the actual new private
CLI: **2 review drafts**. A separate complete run then observed all
**17 PDFs / 162 pages** with the same payload: **16 review drafts, 1 unapproved machine candidate**.
**17 of 17** met the declared technical processing and preservation audit.
The PNG stayed a comparison reference. Digital files kept OCR off. Eight wholly
scanned examples used the ruled-table layout; the two difficult examples used
the tilted/vertical layout. Case 17 used an explicit Standard retest bound to its
earlier technical Standard observation and retained table-limit refusal. No
automatic product fallback or approval was introduced.
Each strict, supplemental and pending-review outcome
stays bound to its actual result. There are **zero verified accessible PDFs**
and zero human approvals from these checks.

**Supplied case 07:** The selected vertical cover word is recovered literally and its invisible text placement matches the source; existing text on other pages remains subject to separate review.

**Supplied case 12:** The full tilted title and publisher details are recovered, and the previously tilted publisher-word selection now aligns with the horizontal source; small-text omissions and a clipped-name error remain.

**Supplied case 11:** the separate raw-field audit retained its
**142 annotations**, including **97 actions**
and **45 destinations**. The old independent helper's blanket
refusal of empty-description enrichment remains recorded. New descriptions and
structure associations remain unapproved review work; that comparison-policy
difference does not establish loss of existing page text or visible content.

Remaining developer observations and review limits:

- A small angled caption and a handwritten year remain omitted from one scanned cover.
- A visible name prefix is misread, and source-clipped letters cannot be reconstructed reliably.
- Tilted lettering with changing character heights still needs placement review; capitalization, punctuation, complete OCR coverage and meaningful reading order remain unapproved.
- Existing text pages and the rest of the folder still require semantic, table, description, contrast and accessibility review.

Compare every word, number, bullet and accent; confirm descriptions, table
relationships and reading order. Source clipping cannot be repaired by guessing
missing text. Existing source-font/strict defects and semantic decisions keep
their actual source-repair or review requirements. Original PDFs, saved reviews,
the original checkout, old trials and qualified runtimes remain preserved.
No installation, merge, release, named approval or external AI call occurred in
this qualification. Private PDF text, detailed comparisons, logs and reviews
remain outside Git. The live master checklist retains its existing open work.


## October 23 OCR table recognition and preservation repair

The exact **141-file disposable source** passed **1,111 software tests in
153.22s**, with zero failures, errors or skips,
including **102** package-builder cases. The **130** actual browser-script
cases passed and are included within one Python case; they are not added to
1,111. The `full-02` receipt audits the same `full-01` execution; no tests
were rerun. The initial report miscounted nested unittest classes; all
**1,111** collected/JUnit identities and **33**
module groups were reconciled against unchanged expected counts, retaining
the original failed report.

The earlier 1,040-test/137-file result and older installation evidence
retain their historical scope below. This checkpoint does not close any of the
**18 open master items** in [the live checklist](docs/STATUS.md).

The optional **Scan layout: Tables with visible grid lines** route conditions
only the image used for local recognition. It detects bounded ruling segments,
keeps partial lines around merged cells and protects pixels outside detected
grids. Original PDF painting is retained and all-page exact visual, geometry,
navigation, annotation and zero-removed-original-token checks remain required.
Standard recognition remains the default; OCR defaults off and AI remains off.
The scan-layout setting is bound to preparation and saved review provenance.
Changing it requires a separate processing run. An older saved review missing
the setting is accepted only as the standard profile with every other setting
unchanged; Retry preserves the saved profile. Existing reviews are not rewritten.

The source-painting repair is now `source-aligned-painting-1.4`. It restores a
split original text operation only when substantive fragments share the exact
same paragraph owner and intervening artifacts contain literal spaces only.
Different semantic owners, replacement text, nesting and other unsupported
operations retain the earlier refusal/retention behavior. Fresh genuine program
processing of case 02 preserved all **18 pages**, exact pixels and original
tokens, with **zero added or removed tokens**. The old failed/no-output case
remains intact; preservation success does not repair its existing unreadable extracted text,
fonts, missing descriptions or other semantic defects.

The fresh offline internal payload has **3,807 files**, unchanged
official SVG/ICO artwork, the selected private **CPython 3.14.9** baseline, separate
eight-core and 31-OCR dependency locks, and the complete 138-file native OCR
factory with pinned English/orientation data. All three genuine new packaged
program cases passed the declared technical processing/preservation policy and
retained unapproved results with their actual strict and supplemental outcomes:

| Actual new program case | Strict rules passed / failed | Fidelity | Pending manual / decisions |
|---|---:|---|---:|
| Scanned syllabus: local table OCR | 105 / 1 | pass | 7 / 24 |
| Digital syllabus: OCR off | 105 / 1 | pass | 8 / 91 |
| Supplied case 02: OCR off | 104 / 2 | pass | 7 / 669 |

A separate bounded developer comparison of the new scanned-syllabus output
recovered all **three grade-group labels**, all **seven grade weights**,
the schedule headers and all seven week numbers. This establishes those
observed recoveries only. Bullet recognition, accented character recognition
and the complete schedule reading order still need correction or review.
Table associations, every word and the complete reading order still require
real semantic review; no human approval was created. Source words, numeric
values and the detailed visual/text comparison stay in private local evidence.

The supplied folder contains **17 PDFs / 162 pages** and one PNG comparison
reference. Every PDF received a fresh complete program observation with the new
payload: **1 machine candidate unapproved**; **2 no output**; **14 review draft**. **14 of 17** met the original independent technical
checklist; **zero documents are verified accessible**. The separate follow-up
observations below explain the retained negatives and any alternate runs. Ten
image-only PDFs used local table-profile OCR; digital PDFs kept OCR off, and the
untagged mixed case used explicit redo with existing unsupported-feature and
preservation refusals intact. The PNG was retained as a reference. The older
OCR-off folder run's 16 manual results/one machine candidate and the separate
76-page component OCR experiment are not new full-remediation successes.

The negative or refused outcomes remain recorded: case 07: no output; case 11: review draft; case 17: no output.

### Folder follow-up observations

The complete original run remains **14 review drafts, two withheld outputs and
one unapproved machine candidate**. Its independent checklist recorded 14
technical passes and three negatives. The following separate observations do
not overwrite that receipt or establish complete rehabilitation of the folder.

**Case 07:** explicit redo replaced **874 existing text tokens** across two
pages, so the program withheld the result despite unchanged visible pixels.
A separate same-build **OCR off / Standard** run produced an unapproved draft
with all three pages, exact pixels and all original tokens preserved. Its
scanned cover still lacks selectable text; existing OCR meaning and the scan
text-layer, metadata and figure-description blockers remain unresolved. A
visible comparison also found that redo recognized the cover's one vertical
word incorrectly. The failed redo remains intact.

**Case 17:** the optional ruled-table filter exceeded its unchanged **128-line**
limit and withheld output. A separate explicit **Skip / Standard** run produced
an unapproved review draft: all **20 pages** retained exact pixels, geometry,
annotations and navigation; no original tokens were removed, and **16,791 OCR
tokens** were added. Strict validation passed all **106 rules / 397,665 checks**.
Metadata, figure descriptions and long-document bookmarks remain supplemental
blockers, with seven manual items and 1,128 decisions pending. Word accuracy,
completeness, contrast and reading order are not approved. The original table
filter refusal remains intact; no limit was raised and no automatic product
fallback was introduced.

**Case 11:** the original independent negative arose because its historical
helper prohibits any addition to an empty annotation description. The existing
program permits that addition only as unapproved review work. All **21 pages**
retained exact pixels and zero removed or added page-text tokens. A separate
raw-dictionary audit found no lost existing fields in **142 existing links**:
their 97 complete action dictionaries and 45 destinations remained unchanged.
New descriptions consist of 97 existing URIs and 45 generic labels; neither
their meaning nor the new structure associations is approved. Original strict
failures, supplemental blockers and the independent negative remain intact.

**Recognition quality:** case 12 produced only two incomplete words despite
substantial clearly visible title, editor and publication text. Its main
angled text was missed; additional normal text was also omitted. The table
profile found no grid and changed no recognition pixels, and source/result
appearance is identical. Part of one source line is already clipped and needs
a better source to recover the missing content. These bounded developer
observations, together with case 07's vertical-word error, establish remaining
recognition defects, with no human approval or all-document accuracy claim.

Across the separate settings trials, each of the 17 PDFs now has at least an
unapproved draft or machine candidate. This includes the incomplete OCR-off
case 07 draft and does not establish full rehabilitation of any document.
The next OCR work is recognition of angled/vertical text and safe handling of
mixed pages without replacing their existing text. Then compare every word,
number, bullet and accent, and review table relationships and reading order.
Meaningful descriptions, heading choices, titles and remaining font/strict
defects retain their real review or source-repair requirements. GUI, fresh-PC,
screen-reader/the LMS checker acceptance and release gates remain open.


Original PDFs, the selected saved input/review guards, original checkout,
validation source/Git state, installed application, prior builds/trials and
qualified runtimes stayed unchanged during these checks. All failed/intermediate
attempts remain evidence. No AI provider call, named approval, commit, merge,
release, installation or distribution occurred. New graphical/browser workflows,
a fresh Windows computer, actual-user/screen-reader/the LMS checker acceptance and external
release remain separate qualification; the older GUI evidence does not qualify
this new OCR package.

Exact local evidence is bound by the new repair QA/source plan, package authority,
three-case program summary, whole-folder summary and separate table comparison.
These private documents, extracted text, logs and reviews remain outside Git.
The official artwork and Git allowlist are unchanged.


## October 23 application icon

The owner supplied the official application artwork. Preserve the unchanged
master at `src/pdf_remediator/web_assets/PDFRemediator.svg` (SHA-256
`3095510c91cdb4ab624fe45931e9642dbd7c4bb3d05f12753c7f2a3079eeebba`).
`PDFRemediator.ico` beside it is derived from that SVG with transparent corners
and 16, 24, 32, 48, 64, 128 and 256-pixel frames. Future Windows package plans
must include both assets. The launcher and installer embed the same reviewed ICO;
the installer window uses its executable's icon. The browser tab uses the SVG
with an ICO fallback, and the application header displays the same artwork.
Both assets are Python package data, and the source updater
permits their exact paths without accepting arbitrary image files.

Icon-only qualification and preservation evidence is retained separately under
local `work/icon-20261023-01/`. Compiler/resource checks do not execute or install
the generated executables and do not replace graphical/fresh-PC qualification.
The earlier 1,040-test result retains its original source scope. Keep the owner’s
download, original PDFs, saved reviews, earlier builds and all existing changes
unchanged. No AI, OCR, merge or release is part of this icon change.

## October 23 syllabus and optional local OCR development

A fresh **137-file disposable development source** passed **1,040 software tests
in 90.32s**, with no failures, errors or skips. This includes **94** package-builder
contracts. The **128** actual browser-script cases also passed and run within one
Python case; they are not added to 1,040. The earlier 972/983/1,039 results and all
failed/intermediate attempts remain historical evidence. The prior **49** compiled
wrapper contracts are not new-OCR-installer qualification.

The changes make unavailable OCR fail clearly before work is queued, retain OCR
off for selectable-text PDFs, validate the effective Link owner role, use
exact encoded-image resource comparison and bind embedded OCR provenance.
Bounded multi-page OCR retains the unchanged all-page preservation gates.
The OCR subprocess/version commands explicitly select isolation, no bytecode and
UTF-8. Ordinary logos alone do not require OCR. Existing Figure-description edits
can save pending alternatives; adequacy and real human acceptance remain separate.

The user explicitly authorized local OCR through the program workflow for this
new trial. **AI remains off and OCR defaults off.** Actual component OCR on the
scanned syllabus (**one page**) and ten supplied image-only examples (**76 pages**)
added selectable text while preserving every tested page's exact 96-dpi PDFium
pixels, geometry/navigation/annotations and original digital tokens. These are
**77 technical OCR page checks**, not 77 accessibility or accuracy approvals;
word accuracy, completeness, reading order, tagging and semantics remain pending.
Original inputs and the private runtime stayed unchanged. No external AI call,
human approval, merge, release or distribution occurred.

The optional OCR package uses the same official CPython 3.14.9 baseline, a separate
exact **31-wheel** OCR lock, Tesseract **5.5.3.20260724**, and pinned English/orientation
models. French is not enabled. The application core retains its separate eight-wheel
lock. A new offline build produced **3,803 payload files**, followed by genuine
private packaged-program CLI runs on both supplied syllabi. The scanned route used
OCR skip and added **1,116 selectable characters/202 tokens**; the digital route
kept OCR off and retained **1,119 characters** with zero added/removed tokens.
Both passed the declared exact visual/original-token fidelity policy and preserved
all payload and input bytes, but produced **review-only drafts**, not accessible
results. Each strict result retained **105 passed rules/one failed rule**:
the scan had **6,066 passed checks/one failed check**, metadata/figure-alternative
blockers and **seven manual/25 decision items pending**; the digital PDF had
**6,494 passed checks/one failed check**, a figure-alternative blocker and
**eight manual/91 decision items pending**. Both retained **zero approvals**.

A subsequent developer comparison against the visibly rendered scanned source
confirmed **current OCR quality defects**: most grade-table labels and **five of
seven weights are missing**, three bullets become `e`, and `français` loses its
cedilla. Schedule column/row extraction order also needs semantic review. The logo
text was recovered correctly, so text absent from the digital comparison file is
not automatically an OCR hallucination. These observed default-setting defects
remain unresolved; technical processing, similar character counts and exact
pixels do not establish text completeness, accuracy or accessible reading order.
The paired visual/text evidence carries **no human approval**.

The first packaged qualifier stopped before processing PDFs because its version
checker rejected the supplier's `v` prefix. The failed attempt/startup audit remain
retained; a new helper/attempt passed without product or full-suite changes. This
does not qualify the new OCR package's graphical installation/browser workflow,
a fresh computer, OCR accuracy, semantics or release. The older graphical results
retain their original no-OCR-package scope.

A separate genuine packaged-program negative on supplied **case 02** remains
unresolved: OCR stayed off, fidelity failed and **no output PDF was published**.
It retained **104 passed/two failed strict rules**, **233,790 passed/25 failed
checks**, font-embedding/metadata/figure-alternative blockers, **28** missing
alternatives and four unembedded used fonts (Times-Roman, Times-Bold, Courier,
Times-BoldItalic). Its **seven manual/669 decision items remain pending** with
zero approvals/AI calls. Original and all 3,803 payload files stayed unchanged.
The encoded-image comparison correction does not fix this document; its negative
result is retained in `pq-case02-01/summary.json`, not counted as a success.

Evidence remains local outside Git under `syllabus-investigation-20261022-01/`:
`combined-review-02/full-01/`, the frozen source plan, and
`ocr-foundation/actual-OCR-qualification/{syllabus-01,corpus-01}/summary.json`.
The suite preserved the original checkout's **26,238** files/Git state, production
**136** files/Git state, **134** protected input/run/review files, the prior source
and the selected QA/native runtimes. Actual package/full-program evidence is
retained in `package-review-01/build-01/` and `pq-syllabi-02/summary.json`; the
startup-only failure audit remains in `pq-syllabi-01/`. No acceptance or
external-release gate closes.

## October 22 packaged Windows graphical qualification

The maintained installer and desktop launcher passed the bounded **13-case native
Windows developer protocol** on Windows 11 Home x64 build 26200. Two genuine GUI
installations, `app ü` and `recovery-app`, each matched all **1,355** pristine files.
Focus, pre-install Alt+F4 cancellation, existing/long-folder refusal and same-form
keyboard retry passed; the fresh retry target was `app ü` instead of `retry-app`.
Pointer/window-raise assistance was recorded; this was not entirely keyboard-only.

Actual desktop launch/reuse opened Edge 155.0.4283.62, matching the effective Windows
shell handler despite a raw ChromeHTML preference. Real missing-Python and
missing-launch-script dialogs passed; the latter retained its **254-byte** diagnostic.
The separate fresh complete installation recovered successfully; fault copies stayed intact.

A native file picker and actual Process job produced a candidate passing **106 strict
rules/427 checks**, supplemental checks and exact one-page pixels/ordered text.
The pending title `SYNTHETIC native packaged pending draft 2026-10-22` survived Save,
visible Stop, actual EXE restart and saved-card reopening byte-for-byte, with five
manual checks pending. A separate genuine CLI-seeded/browser-imported problem note
survived the same recovery with four pending/one blocked; it earns no upload/Process
credit. Both routes kept **zero approvals**, no Apply and AI/OCR off. Native keyboard
Stop passed, and all owned application service identities/listeners ended.

The initial unexpected default-folder installation began before the first capture;
its cause remains unknown and it receives no pass credit. All earlier attempts remain.
Full preservation checked **124,906** prior work files, **948** saved reviews,
**821** protected files, **136** validation-source files and **26,238** original-source
files, with no baseline exclusions. Original package/review bytes stayed unchanged;
new output and normal bytecode caches were inventoried separately.

Start with `work/gui-20261022-01/protocol-result.json`. Its later
`docs-application-01/source-application.json` binds the prior runtime authority to
four documentation-only changes with complete old-byte backups. All **35** application
assets and executable/test bytes are unchanged; **972** software tests and **49**
independent wrapper contracts retain their prior results and were not rerun for GUI evidence.
Only the bounded GUI checklist item closes: **nine master items remain open**.
Fresh-PC, licensing, signing, human/AT/the LMS checker and final owner/build gates remain separate.
No distribution, commit, merge or release is cleared.

## October 22 maintained private Python qualification

The selected Windows x64 private baseline is **CPython 3.14.9, standard GIL**,
with eight exact core distributions: pikepdf 10.17.0, pypdfium2 5.14.0,
Pillow 13.0.0, PyYAML 6.0.3, psutil 7.2.2, fonttools 4.67.0, lxml 6.1.3
and packaging 26.3. The reviewed lock binds exact official archive/wheel hashes,
compatible standard-CPython tags and the active Windows dependency closure.
Free-threaded wheels, changed payload metadata, alternate hashes and unbound
runtime identities are refused. The old Python 3.11.9 compatibility package is
retained as historical evidence and is superseded for this selected baseline.

Pillow 13.0.0 replaces 12.3.0 because the vendor's security release fixes
affected versions, including bundled OpenJPEG and JPEG memory-safety issues.
See the [vendor release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html).
Official PyPI metadata, artifact hashes, ZIP CRCs, hashed RECORD entries,
actual wheel requirements and retained notices were checked. This is not a
claim that every advisory is reachable here, or that an empty advisory list
proves an absence of vulnerabilities. Package attestations were not independently
verified; file hashes alone do not establish publisher identity.

A fresh offline prepared-host installation verified **1,355 files**,
refused an existing target unchanged, and loaded exactly the eight selected core
distributions from its own isolated interpreter with host Python/Java removed
from PATH. Its own doctor reported tagging/validation ready and OCR unavailable.
Two real authored tagged/untagged PDFs produced separately bound candidates,
passing 106 strict PDF/UA-1 rules with 427 and 766 checks respectively,
supplemental checks and exact one-page pixel/ordered-text comparisons. Each kept
five manual checks pending and no human approvals. Inputs and package files
remained unchanged. An independent factory/archive/native-result audit passed;
no application service, browser or graphical installer was opened.

The fresh-source prepared suite passed **972 tests** with zero failures,
errors or skips (**154.88s** reported by pytest), including **69** builder
cases. Its **110** actual-script cases are included within one Python case;
they are not added to 972. The **49** independent compiled installer/launcher
contracts passed separately against the final reviewed wrapper bytes. Declared
MessageBox/child doubles and the shared-helper GUI harness do not establish
native graphical-installer or launcher acceptance.

Full QA used a separate developer configuration of the **same official
Python 3.14.9 binary** plus seven exact QA-only distributions. That configuration
omits the supplier _pth file so the test source and QA dependencies can be used;
it is not the installed product's isolation proof. The actual installed product
retained _pth isolation and exactly eight core distributions. No QA dependency,
pytest, source checkout, pip or test fixture was added to the product payload.
The 35 application runtime source/data assets remain byte-identical.

The first fresh full-suite attempt recorded **971 passes and one failure**:
the corrupted-install updater test recovered the original but stopped before
entering its intended synthetic corruption branch. Its cause remains
undetermined; no Python-version or security-software cause is inferred. That
attempt and its preservation result remain retained. Twenty fresh genuine
corruption/rollback probes then passed. The existing negative test was
strengthened to require the intended fault branch and the specific causal
failure, retaining all original recovery and preservation assertions. The updater
implementation is unchanged. The later fresh full-suite result above passed
with that stronger test; the initial event remains an unresolved observation.

The selected native Java factory is **Temurin 25.0.4.1+1**, with OpenDataLoader
2.5.13 and standalone veraPDF 1.30.3. It is the selected published vendor input,
not a claim of complete latest-upstream Java security parity. Recheck upstream
25.0.5/vendor availability and security status before external distribution;
runtime maintenance remains ongoing rather than a one-time release clearance.

The final pre-integration preservation guard rehashed all **113,169** previous
validation-work files, **948** prior saved review states, **821** protected
original/review/runtime files, the original checkout and selected external
runtime files. The new trial remains separate. Original source, reviews and
earlier incomplete evidence were preserved; AI/OCR stayed off. The staged
136-file prepared source includes only the seven reviewed code/lock/test changes;
the five later documentation updates change no tested executable/test bytes.

At that maintained-runtime checkpoint, only the private Python/core-baseline
checklist item closed; graphical packaged installer/launcher qualification was
still pending. The later bounded graphical result above qualifies that separate
item. Fresh-computer installation, distribution licensing/source/relinking
obligations and publisher signing/authentication remain open. Human
semantic/usability review, screen-reader testing, authorized the LMS checker feedback and
final owner/build decisions retain their separate gates. No external
distribution, commit, merge or release is cleared.

Retained evidence is under `work/rt-20261022-01/`: the native result is
`runtime-qualification-summary.json`, passing prepared results are in `prepared-02/`,
and the original failed attempt remains in `prepared-01/`. Acquisition,
independent-audit and preservation summaries are copied into `evidence/`.
That checkpoint's prior checkout authority is `source-application.json`, key `source_after`;
it records the guarded 135-to-136-file application and complete prior-byte
backups. The earlier 945-test and Python 3.11.9 package trials remain retained.

Start with the single live [master checklist](docs/STATUS.md#master-checklist).
It separates remaining software/Windows checks, human acceptance, owner decisions
and optional future scope. Dated handoff entries below retain their historical
evidence; they do not replace the live checklist.

## October 22 native keyboard and internal Windows package follow-up

The bounded native Windows developer keyboard and file-picker protocol passed.
The visible keyboard Stop completed and the independent preservation/service audit passed.

A fresh disposable copy retained the exact 130-file validation source. Startup
used the selected existing qualified Windows runtime and Python webbrowser
handoff to the default browser. This did not repeat normal Setup/Start or
qualify the new packaged desktop launcher. Actual
Windows input exercised Escape cancellation, nonadjacent Ctrl selection and
contiguous Shift selection in the native file picker, then processed exactly
the three selected authored PDFs. The recorded protocol covered eight bare
Left/Right/Home/End tab transitions and seven specified modifier negatives,
selected-tab entry/exit in both Tab directions, Space checkbox/disclosure
actions, review-group selection/reset, Ctrl+A and Shift text selection.
Distinct Figure A/B drafts survived Save, replacement-action focus, native
reload, #main skip-link session recovery and reopening. The two-figure
review-draft download and the separate two-page candidate download each
matched their own bound output hash. Initial UIA pointer assistance established
upload focus; these bounded observations do not claim a keyboard-only launch,
every browser shortcut, assistive-technology acceptance or PDF semantic review.
The native page field committed page 2 and then page 1 with Tab. The two-page
candidate passed 106 strict rules/797 checks, supplemental checks and exact
two-page pixels/ordered text. The visible Stop was activated with Return;
all owned native service identities and the listener ended.

Distribution packaging is a separate workstream. A new guarded offline builder,
fresh-folder installer and desktop launcher produced an internal unsigned
Windows x64 draft from official factory inputs, without copying an existing
virtual environment, private runtime configuration, originals or saved reviews.
It vendors private Python and the core native tools; no AI models or OCR
runtime are included. The browser remains the private local interface.

The fresh exact-source prepared Windows suite passed **945 tests in 134.98s**,
with zero failures, errors or skips. Its total includes all **42** package-builder
contracts. The **110** actual-script cases run within one Python test and are
included in that total. The **43** independent compiled installer/launcher review
cases remain separate and are not added to 945. Real noninteractive
installation verified 1,346 files, refused an existing target unchanged, and
passed isolated imports and doctor with host Python/Java removed from PATH.
Two actual private-runtime native fixes produced candidates: the tagged control
passed 106 rules/427 checks, and the untagged reading 106/766, with zero
failures. Both passed supplemental checks and exact one-page pixels/ordered
text. Inputs and package files remained unchanged; each result retained five
pending manual checks and no human approvals. No graphical installer or
packaged browser/launcher workflow was opened for this package trial.

The earlier 903-test/158.22s baseline remains retained as historical evidence.
The 945-test run bound the complete integrated 135-file source snapshot. The
application runtime bytes remain unchanged; the added builder tests are now
part of the full prepared total. These later documentation-only records change
no tested application, test or script bytes.
The internal Python 3.11.9 compatibility draft is not a current-runtime release
candidate. Maintained-runtime qualification, native packaged GUI/launcher
testing, a genuinely fresh supported Windows machine, distribution licensing
and source/relinking notices, and publisher signing/trust remain open.
See [Windows distribution development](docs/WINDOWS-DISTRIBUTION.md) for
the build contract and explicit limits. No sharing or release is cleared.

Originals and reviews remain preservation targets; AI/OCR stayed off. No
commit, merge, release, external sharing or LMS upload occurred. Native app
artifacts are under `work/windows-native-keys-20261022-01/`; actual package
installation/native results are under `work/pkg-20261022-01/`. The native protocol and audit are retained under
`work/windows-native-keys-20261022-01/evidence/protocol-result.md` and
`work/windows-native-keys-20261022-01/evidence/final-native-audit.json`. The
exact prepared result is `work/pkg-20261022-01/prepared-01/suite-summary.json`.
The authoritative final 135-file checkout map is
`work/pkg-20261022-01/suite-documentation-application.json`, key `source_after`.
It records only the five documentation changes after the passing run; tested
application runtime, script and test bytes remain unchanged. Earlier manifests
remain intact as historical evidence. Detailed builder and contract evidence
remains local and outside Git; the run manifests retain its exact locations.

## October 21 specific seeded negative browser checks — completed

A fresh disposable Windows copy retained the current qualified application
bytes. The real pipeline produced genuine immutable negative bundles, which
were opened through the ordinary Find existing results / Open selected result
browser workflow. Each of the five negative bundles displayed its recorded
blocker, kept Download result disabled, and retained that outcome after reopening.
These are developer checks in the actual in-app browser against the Windows
service; they do not establish native Windows keyboard or human/AT acceptance.

Phantom and incomplete tagging were assessed with the supported read-only CLI
check mode. Both failed strict PDF/UA-1 and supplemental gates, with no published
PDF. Ordinary browser Process is a repair route and was not misrepresented as a
read-only malformed-tag test. The healthy tagged control passed every real gate.

Two explicitly declared test-only mutations changed distinct derivatives after
the real normalizer and before real inventory, decision application and native
assessments. Deliberate content loss removed the final authored paragraph and
its matching tags. Wrong Unicode changed the embedded-font C-to-Unicode mapping
without changing painting operations. Both passed strict and supplemental gates
but failed real text fidelity, preventing publication. Content loss also failed
pixel comparison; wrong Unicode retained identical pixels. No gate, report or
manifest was fabricated. The detailed native evidence is independently audited;
the browser shows the recorded preservation blocker, not a detailed gate dashboard.

For changed preparation settings, a title was saved and explicitly accepted under
a synthetic reviewer name in the browser, then exported through its normal review
records action. A separate real pipeline invocation changed only
allow_tag_regrouping from false to true while supplying that original bound
checkpoint and exact exported sidecar. It refused before adopting the checkpoint
or applying old choices, with no published PDF. The genuine refusal bundle was
then opened and reopened in the browser. This does not claim that the ordinary
Apply button silently changes preparation settings.

Application code and tests are unchanged. The existing **903-test / 158.22s**
prepared baseline and **110** browser-script cases were not rerun for these
documentation changes. Originals, saved reviews and earlier evidence remained
preserved; AI/OCR stayed off. Synthetic names do not grant human verification.
No commit, merge, release, distribution or LMS upload occurred.

The full native Windows keyboard/modifier and Ctrl/Shift file-picker task remains
open. Genuine usability/semantic review, experienced screen-reader testing,
authorized the LMS accessibility checker feedback, final-build review and the owner's integration
or release decision remain separate requirements. The earlier shared-element,
contrast and missing-description checks are distinct from these seeded cases.

Local evidence remains outside Git under
`work/windows-negatives-20261021-01/`: the disposable application's
`output/native-negatives/summary.json` and
`output/changed-settings-negative/summary.json` bind the real bundles. Retained
trial evidence includes `native-audit.json`, `browser-qualification.json` and
`browser-observations.json`, with explicit generation and browser-route boundaries.

## October 21 Windows workflow follow-up and Stop correction

The fresh disposable installation used the exact 130-file cancelled-wording
baseline. Normal Setup/Start passed five checks; Windows' effective HTTP/HTTPS
association API resolves to Edge, matching the observed handoff. Raw Chrome
registry entries alone did not establish the effective browser. Native input was
stopped when the Windows tool returned a screenshot inconsistent with its selected
window. Full native keyboard/modifier and Ctrl/Shift file-picker qualification
remain open. Subsequent interactions used the actual in-app browser against the
Windows service; they are not native keyboard or assistive-technology proof.

Five authored PDFs were selected together through the browser chooser and
processed into five separately bound results: four candidates and the expected
heading/table/language review draft. Six named synthetic choices, followed by
separate Apply, produced a candidate passing 106 veraPDF rules / 1,554 checks,
supplemental checks and exact three-page pixel/ordered-text fidelity. Eight other
decisions and all six manual checks stayed pending. Draft-only Apply and unnamed
acceptance were refused; saved action focus, the cross-page disabled paragraph,
and low-contrast advisory/source guidance behaved as recorded.

The actual 200-page book run produced 1,224 regrouping occurrences in real groups
of 1,210 and 14, with an expected missing-description blocker. Strict validation
passed 106 rules / 678,858 checks; all 200 pages preserved exact pixels and ordered
text. Missing confirmation, selection or name, and a selected blocked member,
were refused with saved bytes unchanged. Approving exactly one synthetic sibling
preserved the blocked exception, its note and every unselected occurrence. Later
distinct figure drafts invalidated that positive manual approval as required;
one figure was synthetically accepted only to confirm Apply still refuses the
retained blocker. Frozen snapshots retain each separate result and scope.

Two genuine old saved reviews were copied byte-for-byte into separate new mutable
workspace directories, retaining all original artifact paths. Their accepted
title, distinct figure drafts and blocked notes survived opening, skip-link
reload, reopening and Stop without changing a byte. A separate ordinary import
of the original legacy chapter bundle retained its four old decisions, without
silently adding current structure controls or importing mutable saved notes.
Four live response overlaps used unchanged real backend responses through a
declared bounded loopback transport. A-to-B, A-to-B-to-A, newer populated field
and newer panel/group cases preserved the newer view, unsaved draft, focus and
selection; unsaved text stayed unsaved and approval selections reset.

The first 600-page cancellation overlapped a real veraPDF version query, not PDF
validation; that limited result remains retained. A later bounded attempt
observed the actual bound PDF-validation Java command before and twice during
the browser Cancel interval. The child and worker then ended, with no published
PDF. Both separate Retry results passed all three gates across 600 exact pages
and supplied 611 pending current decisions: title, language, 603 heading/paragraph
controls and six eligible table cells. Earlier saved controls, notes, cancelled
attempts and complete bundles remained byte-identical. No ODL-tagging
interruption is claimed for this already-tagged workload.

The initial main Stop ended its owned processes/listener and preserved all 234
saved files across 11 reviews, but left a visible Failed to fetch notice while a
preview was pending. The correction preserves terminal UI state only after a
successful Stop acknowledgement, invalidates stale callbacks and polling, and
keeps unsuccessful Stop visible and retryable. The server now writes and flushes
the acknowledgement before scheduling shutdown. The original UI error does not
uniquely establish which race occurred. Four reviewed code/test files passed the
fresh prepared suite: **903 tests in 158.22s**, zero failures, errors or skips;
**110/110** browser-script cases are included within one Python test. Twelve new
script regressions and three backend regressions fail against the prior code.

An affected retest used a fresh exact-tested source copy and one byte-copied
populated saved review. A declared transport held a genuine candidate PNG,
forwarded real Stop 200, then deliberately broke that preview connection only
after the stopped message was visibly handled. The stopped message remained
visible and non-error. This retest is separate from normal Setup/Start proof.
All owned test services/transports ended. Audits preserved 94,978 historical
files with no exclusions, 821 protected original/review/runtime files, all 234
current saved files, nine local sentinels/configuration/inputs and the copied
retest state. AI/OCR stayed off. Synthetic labels never grant genuine human
verification. No commit, merge, release, distribution or LMS upload occurred.

Full native keyboard/picker work and the four specific phantom/incomplete-tag,
content-loss, wrong-Unicode and changed-settings browser negatives remain open.
Actual-user semantic review, experienced screen-reader acceptance, authorized
the LMS accessibility checker feedback, final-build review and an owner integration/release
decision remain separate requirements. The older unexplained closure remains
undiagnosed; this explicit Stop and its diagnostic log do not explain it.

Local evidence is retained outside Git under
`work/windows-workflow-20261021-02/evidence/`. Start with
`browser-observations.json`, `final-stopped-audit.json`,
`active-job/strict-native-cancel-independent-audit.json`,
`active-job/strict-cancel-retry-audit.json`, and
`stop-fix/stop-retest-audit.json`. The exact prepared result is separately under
`work/windows-stop-fix-20261021-01/prepared-01/suite-summary.json`.
The four code/test files have original-byte application backups; four later
documentation updates change no executable or test bytes. Retain the failed and
incomplete tool/test attempts and their explicit dispositions.

## October 21 cancelled job display correction

Cancelled attempts now display **Processing cancelled** on saved dashboard
cards, reopened reviews, activity and existing-results choices. Genuine failures
remain **Processing failed**, and an empty-error failed job no longer receives
the cancellation fallback notice. Retry still creates a separate attempt;
download, Apply and verification authority are unchanged.

New workspaces retain a strict cancellation display flag from the verified run
report. Legacy failed/no-output reviews use a read-only report fallback checked
against their saved report hash, run fingerprint and artifact bindings. This
does not migrate saved reviews, hash/open PDFs, acquire the PDF lock or grant a
fresh artifact assessment. Ordinary summaries and new saved flags remain
state-only. Malformed, changed or ambiguous legacy evidence stays generic rather
than being guessed cancelled from filenames or error prose. Full opening and
protected actions retain their normal binding validation.

The exact 130-file executable/test source passed **896 tests in 94.16s**, with
zero failures, errors or skips. The complete JavaScript harness passed **96/96**
separately; those cases are included within one Python test, not added to the
896 total. Its 13 new cases include six regressions that fail against the earlier
app.js; 36 new backend cases cover actual pipeline cancellation, genuine failure,
legacy preservation and refusal conditions. The earlier focused sandbox run's
two denied loopback connections remain recorded; the permitted focused and full
runs passed. No native browser/keyboard acceptance is inferred from these tests.

All 821 protected original/review/runtime files remained unchanged. AI/OCR stayed
off. This completes the master checklist's known software wording follow-up;
remaining Windows workflow, actual-user, screen-reader and authorized the LMS checker work
stays open. No commit, merge or release occurred. Evidence and original-byte
application backups are retained outside Git under
`work/cancel-wording-20261021-01/`. These three documentation summaries follow the
passing run; executable and test bytes match the frozen tested source.

## October 21 Windows installation readiness correction

Setup now checks fresh isolated imports of pikepdf, pypdfium2, Pillow native
bindings and psutil with the selected installed Python. Installed version
metadata alone cannot report readiness. A failed or timed-out import keeps
doctor incomplete and disables the tagging/validation readiness claims. The
observed native filename/path-length error supplies instructions for a fresh
shorter installation while leaving existing installations, originals,
configuration and saved reviews in place. The desktop entry point also explains
early import failures. No automatic relocation or Windows settings change is
made; deeply nested installations that cannot load these libraries remain
unsupported. A fresh installation does not automatically migrate saved reviews.

The exact executable/test source passed **860 tests in 123.74s**, with zero
failures, errors or skips. The complete shipped JavaScript harness also passed
**83/83** separately; its cases remain included within one Python test.
Three fresh Windows source installations supplied the bounded native comparison:
the unchanged helper at the recorded 170-character installation-root length
reported ready even though actual launcher import failed; the patched helper at
the same length returned failure/incomplete with the actual pikepdf DLL error;
and the shorter 129-character installation completed normal Setup and native
launcher imports. These lengths describe the trials, not a universal cutoff.
The installed deep-path entry point's actual native failure was captured through
a messagebox double without opening desktop UI.

The initial short-path service check used an incorrect test-helper assumption
that the Windows virtual-environment launcher PID equals the service PID. Its
failed disposition remains retained; normal Setup/import successes were not
rerun or reclassified. A fresh service-only recovery verified the actual service
was an owned launcher descendant, its authenticated dashboard responded, and
authenticated Stop ended both owned identities and the listener. No browser was
opened. This is background service evidence, not native keyboard or visible Stop
acceptance. All 821 protected original/review/runtime files and local trial
sentinels remained unchanged. AI/OCR stayed off; no merge or release occurred.

Evidence, frozen sources, before/after comparisons and application backups are
retained outside Git under `work/windows-path-fix-20261021-01/`. The three
documentation summaries below were added after qualification; executable and
test bytes match the tested 129-file source. Earlier incomplete trials and
remaining user, screen-reader, broader keyboard and the LMS checker acceptance boundaries
remain unchanged.

## October 21 controls and focus continuation — completed

The earlier controls trial used the preceding 127-file build with 60 JavaScript cases; it did not include this focus repair. Normal Windows Setup/Start passed five checks in 26.031s, and native multi-file selection processed five authored PDFs. After an unrelated WebView blocked native input, later interactions used the actual in-app browser against the real Windows service. Keep that boundary explicit: browser-routed keys are not native Windows keyboard or assistive-technology proof.

Six explicit synthetic heading/table/language drafts survived reopening and skip-link reload; unnamed acceptance was refused. Six named synthetic acceptances plus separate Apply created a new candidate with strict validation, supplemental checks and exact three-page pixel/text fidelity passing. veraPDF 1.30.3 recorded 106 rules and 1,554 checks without failures. The downloaded candidate matched its output hash. Reported problems survived later title edits; Apply refused a retained blocker. Group negatives preserved saved bytes, selected-only approval left other checks pending, gray contrast remained advisory with required human review, and shared multi-page structural controls stayed disabled. The black text source was authored separately, not automatically recolored.

Three authored 80-page runs passed all gates; two separate browser cancellation actions retained cancelled records with no output, and Retry produced a separate result. No active Java child was observed at the cancellation instant, and the retry review had no decision inventory; do not infer that broader populated-control/native-child coverage. Full application-service restart recovered saved values and blockers. Both visible Stops ended the owned services/listeners; all 11 reviews and 240 current saved/input/run/export files remained unchanged through restart and final Stop. The dashboard's generic cancelled-card label remains 'Processing failed', while activity and notice identify cancellation.

This trial's apparent service absence was a sandbox process-visibility diagnostic: host proof established the original service remained alive until the genuine visible Stop. Protected diagnostic helpers refused before Start. The older historical unexplained closure and stalled browser-tool waits remain undiagnosed; successful recovery does not establish forced-crash or Windows-reboot recovery.

The exact 127-file focus-repair source passed **841 tests in 141.71s**, with zero failures, errors or skips. Its complete shipped JavaScript harness passed **83/83** cases separately and runs within one Python test; it is not an additional Python count. Two independent retained probes also passed, for 85/85 cases in that bounded rereview. These are software checks with declared native adapters and named doubles, separate from browser and human acceptance.

The repair retains focus at the matching replacement action after a successful saved action, or its occurrence note when Return to pending removes the button. Delayed responses respect a newer panel choice and preserve only the newer focused card's local field values and text selection when its workspace, page, group and enabled controls still match. Draft retention never saves, accepts, applies or re-enables a control. The asynchronous overlap cases are authored software evidence; the fresh browser sequence does not independently reproduce those races.

A first deep mirror-path installation passed only three of five preparation cases, including selected-runtime Setup, then Start failed before creating review data; a read-only import reproduced a pikepdf native-DLL filename/path-length failure. That failed installation and evidence remain preserved. A distinct short-path validation/work installation then used normal copied Setup/Start with the exact tested focus-repair bytes. This follow-up does not fix or qualify the failed long-path environment. All 5 normal Setup/Start cases passed in 32.234s. Its initial combined authored PDF was processed by the installed CLI, then imported through the real browser. The outer helper initially assumed UTF-8 for redirected CLI stdout; a verified CP1252 byte roundtrip and complete equality to the independently written UTF-8 batch summary recovered the existing result binding. Setup, Start and processing were not rerun. The recorded browser focus cases passed for language draft, heading/table Save and named Accept, problem reporting, Return to pending and saved-review recovery. These observations used the actual in-app browser against the Windows service; they do not establish native default-browser keyboard behavior or a live delayed-response race. Only H1 and the Recurso TH/Column choice received explicit synthetic named acceptance; es remained pending, and title, Cantidad and all other decisions remained unchanged. Return to pending cleared the problem note through its existing backend route and focused the new empty note field; the same authored problem was then explicitly reported again. Independent raw-state checks confirmed the revision-6/revision-8 notes matched exactly, and revision 8 stayed byte-identical across skip-link reload/reopening. One manual item remained blocked, all others pending, with zero manual approvals and no Apply in this focus trial. The fresh visible Stop ended both owned service identities and the bounded startup console helper/listener; all 24 saved/bound/input/bundle files were unchanged. Stop and saved-data audit passed before the guarded two-file application; the final executable/test bytes match the tested source. These five later documentation updates change no executable bytes.

Audits preserved all 344 protected original/review/runtime files, 91 earlier retained files, 6,343 historical trial/installed files, 1,164 earlier installed source files and the separately recorded historical downloads. Existing originals, reviews and historical incomplete evidence remain intact. AI/OCR stayed off; synthetic named approvals never populate genuine human verification. No commit, merge, release, distribution or LMS upload occurred.

Broader native Windows keyboard/modifier and populated-control workflows, safe legacy import in this new trial, actual navigation/response overlap, genuine nontechnical-user semantic review, experienced screen-reader acceptance and explicitly authorized the LMS accessibility checker feedback remain open. No conversation or developer fixture result grants human verification or release authority.

Local exact-source manifests, commands, raw browser/native records and preservation maps remain outside Git under `work/ally-native-controls-20261021-01/` (development mirror staging before retention). Start with `old-trial-summary.json`, `snapshots/final-stopped/`, and `focus-fix/prepared-final-01/suite-summary.json`; fresh focus records are kept separately under `focus-fix/`. Do not commit session authority, runtime logs, authored PDFs, review states or extracts.

Updated October 21, 2026. Application version: **0.3.0**.

Current support evidence and remaining tasks are consolidated in
[docs/STATUS.md](docs/STATUS.md). Dated checkpoint sections below retain their
historical results; current status supersedes older pending-work statements.

Note (1 November 2026): this repository is now public. Statements below that call it private describe the time they were written; the Git allowlist that keeps PDFs, logs, review states and local runtime files out of the repository still applies.

This is a working Windows development project for producing PDF accessibility candidates. Its source backup is pushed to a private GitHub repository. The **PDFRemediator** cloud coding environment was published on October 16, 2026, with sharing set to **Only me**. Its Linux source-development workflow is tested; native PDF processing still requires separate qualification.

The owner selected the private repository name **PDFRemediator** at [jasonswrench-beep/PDFRemediator](https://github.com/jasonswrench-beep/PDFRemediator). Initial commit `b2c7fbfdfe65a7d546fccd65485fef29e19beeb0` was pushed and read back from GitHub; all 97 remote files matched the audited local commit. The repository was verified private, with no PDFs or local runtime state included. Continue this work autonomously within the authorized scope, without treating an unfinished setup as permission to upload private PDFs or begin Phase 3 testing.

## Implemented the LMS checker-related checks and reviewed fixes — October 21

Continued from the preserved validation checkout in a separate source staging
copy. Added explicit heading-presence (three-page boundary), first-level,
maximum-depth and skipped-level checks, including generic H and custom/deep
RoleMap roles without invented numeric hierarchy. Known mechanical failures
block candidacy; unavailable/ambiguous scope retains required structure review.

Added a local function-word language screen for en/es/fr/de/it/pt/nl, with
bounded page samples, diagnostic evidence and conservative abstention for short,
unsupported, mixed or damaged text. It compares primary subtags. High-confidence
supported mismatches block candidacy and offer a pending language draft; no
setting changes without the existing named acceptance and separate Apply route.

Contrast evidence now measures supported opaque, axis-aligned digital text on
uniform rendered backgrounds, reporting page/region/colors/ratio/size threshold.
Low-ratio regions include a black/white source text-color suggestion and its
computed ratio, for review before editing the source. Measurements remain advisory because logos, decorative or incidental text need
human applicability judgments. Required contrast review is retained. Unsupported
paint and declared limits remain explicit; no complete-document pass is claimed.
Counter limits do not bound all native engine decoding/allocation. Confirmed
problems require source-color repair or an accessible replacement, separate
export and reprocessing; automatic recoloring cannot bypass exact fidelity.

New runs use an explicit reviewed-structure decision inventory. Heading/table
controls show only existing eligible prepared elements with their page, content
references and fingerprint. They are collapsed and page-filtered in the UI;
unsafe controls are disabled. Draft Save and named Accept remain separate.
Accepted structural changes write only the reviewed role/Scope into a separate
checkpoint; IDs, Headers, spans and unrelated attributes remain preserved, and
all required gates rerun. No semantic heading/header choices are generated.
Automatic title/Figure authority cannot approve these structural operations.
Legacy sidecars/workspaces retain their original inventory rather than acquiring
new decisions silently. Old reviews without controls need a new separate process
of the unchanged original if current controls are wanted.

The fresh 127-file prepared Windows source copy passed **841 tests in 146.66s**, with zero failures, errors or skips. This includes actual parsing/rendering/fidelity and the declared native adapter tests, plus named software doubles; it does not qualify the new controls in a native browser or complete human/the LMS checker acceptance. The exact tested bytes, command and result are retained in `work/ally-checks-implementation-20261021-01/prepared-final-02/` (`source-manifest.json`, `suite.xml` and `suite-summary.json`). AI/OCR stayed off; all 344 protected original/review/runtime files and 91 retained saved-review/input/run/export files remained unchanged.

The real complete app.js harness now has 60 cases: the prior 39, 15 new
repair-control cases and six asynchronous navigation/job-guard cases. These
exercise real startup/listeners for legacy findings, collapse/page filtering, exact select
draft values, table JSON, explicit edit/approval revision sequencing, refused
unnamed acceptance, unsafe/stale controls, language draft-only copy and literal
context/evidence. Deferred responses cannot replace a subsequently opened view
or redirect approval after A-to-B or A-to-B-to-A navigation. Active-job filters,
structure toggles and page navigation cannot re-enable mutable controls. The
cases run inside one Python test. HTTP doubles deny unauthored
mutations and never implement Apply/provider/PDF actions. They are not native
browser or human-accessibility proof. Existing native results below retain their
own earlier source/artifact bindings; they do not qualify these new controls.

Current behavior/limits and fix paths are in
[LMS-CHECK-APPLICABILITY.md](docs/LMS-CHECK-APPLICABILITY.md). Malformed,
encrypted/signed and other unsupported-document refusal routes, existing scan,
table, description, title/font checks, strict validation, immutable bundles and
human-verification requirements remain in force. Originals, saved reviews and
previous evidence are preservation targets. AI/OCR remain off; no merge,
release, distribution or LMS upload is authorized. Actual-user usability,
screen-reader testing and explicitly authorized the LMS accessibility checker work remain open.
Implementation evidence is retained outside Git under
`work/ally-checks-implementation-20261021-01/`.

## the LMS checker PDF applicability reference — October 21

Compared the owner's two read-only the LMS checker CSV references with the current vendor
PDF checklist and the implemented source. The vendor explicitly confirms all six
previously uncertain PDF categories; the missing-headings rule applies at three
pages or more. [the LMS checker PDF checks and application coverage](docs/LMS-CHECK-APPLICABILITY.md)
records the 14 vendor categories, separate scan/OCR conditions, existing
supplemental checks and concrete automation gaps. This documents applicability,
not a new implemented check, the LMS checker score or completed acceptance result.

Only that reference and this handoff changed. No desktop, application, PDF engine,
AI/OCR or LMS trial ran. The last prepared result remains 675 passes on its exact
recorded snapshot; executable code, originals, reviews and all earlier evidence
remain intact. New provenance and preservation records are retained outside Git
under `work/ally-applicability-20261021-01/`. No merge or release occurred.

## Native keyboard, protected-note repair and recovery continuation — October 20

Continued detached validation HEAD `9d857fa16bc92aaf5a416fe833e6481ea9049ad0`
with all existing changes preserved. Each native phase used a new disposable
installation; the owner's installation, originals and earlier saved reviews were
not used as mutation targets. AI/OCR remained off. No merge, commit, tag, release,
upload or distribution occurred.

The first fresh 118-file prepared source copy passed **667 tests in 72.98s**,
zero failures/errors/skips. A preceding socket-restricted attempt returned 607
passes and 60 failures (WinError 10013 and dependent loopback failures); its
evidence remains separate. The passing retry used the same reviewed source and
native/font prerequisites with permitted private loopback execution. No refusal
test was skipped or listener exposed publicly.

Phase A's normal Windows Setup/Start preparation passed five checks in 22.234s
and opened Edge through the ordinary default-browser route. OCR visibly remained
off and no optional repairs were selected. Native Process completed an authored
one-page reading with strict validator, supplemental and every-page fidelity
passes; five human items remained pending and none approved. The file chooser's
filename used native set-value, followed by keyboard confirmation/processing;
this is not full keyboard-only upload proof.

From the keyboard-focused Review checks tab, native Ctrl+Home/Ctrl+End scrolled
to the page ends without changing the selected panel. Bare Home/End selected and
focused the first/last tab, Left/Right moved between tabs, Tab/Shift+Tab traversed
the selected tab and next control, and Shift+Home preserved the selected panel.
Saved review bytes and revision remained unchanged through these navigation
checks. A visible Stop click displayed the stopped message; the independent
lifetime observer and OS process/TCP inventory confirmed service/listener exit.
This phase precedes the backend repair below and is bound to its own source
manifest. It does not establish native Meta-key behavior or the full keyboard
acceptance protocol.

An independent audit found a separate backend defect: changing title or figure
description values reset every manual item, erasing active problem notes,
blocking status and attribution, including unrelated items. The two-condition
repair clears only positive manual approvals when values change. Blocked and
pending items, notes and attribution remain intact; positive artifact approvals
and obsolete automatic dispositions are still invalidated. Stale-source and
revision guards are unchanged. Historical events retained prior note text; this
repair does not reconstruct notes already erased from an older active state.

Eight public-operation regressions exercise human/automatic title/figure edits,
same-value controls and Apply refusal with a retained problem. On the old backend,
six new cases failed and two same-value controls passed. All eight pass with the
repair; the workspace/new Apply scope passed 88 tests in 15.47s. Independent
review found no actionable issue in the bounded patch/test scope. A fresh
118-file prepared snapshot with the exact three repaired files passed **675
tests in 64.45s**, zero failures/errors/skips. The 39 actual-script JavaScript
checks execute inside one Python test, not as 39 extra Python passes. The last
separately executed source-only result remains **654 in 90.05s** on the earlier
keyboard-fix snapshot; no new source-only count is inferred.

Both native installations retained their exact frozen 118-file source manifests. Phase A precedes the backend repair; Phase B matches the 675-case tested snapshot with the exact three repaired source/test files. These five documentation-only updates follow testing; executable bytes remain unchanged.

All 20 bounded Phase B native observation groups passed: protected notes survived title/figure edits, skip-link reload, reopening and a full application restart; Apply refused the retained problem; exports/download stayed bound; paired chapter pages, separate figure drafts and group-selection reset behaved as observed. Both visible Stops ended the owned services/listeners.

Phase B's normal Windows Setup/Start passed five checks in 20.969s. All 118 installed source files matched the fresh 675-case prepared snapshot. Native keyboard file selection used Return, typed the full authored reading path and Return; processing options visibly kept OCR off, and Tab/Return initiated processing. These are bounded keyboard upload/process observations, separate from Phase A's native set-value filename entry. No AI/OCR process was enabled.

A synthetic reported problem at reading revision 1 retained its entire dictionary through a title edit at revision 2. Native skip-link activation followed by reload retained authentication; reopening displayed the saved title and exact problem note. Accepting the title with explicitly synthetic attribution produced revision 3. Native Apply was refused with the visible reported-problem notice. Whole saved-state bytes and the existing inventory of one job, one bundle, 24 run files and zero exports remained unchanged across that refusal; no replacement work was queued or published. Native Export then produced three review JSON records showing reprocessing required, no ledger verification and no verified status. The native reading download remained labeled review-draft and matched the unchanged bound PDF SHA-256 85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df. The accepted title remained unapplied and its reported problem stayed blocked.

A separate authored four-page chapter completed native assessment with gate 1 passing, gate 2 intentionally failing for two missing figure descriptions, and all four pages passing exact pixel/text fidelity. It remained a review draft. Native paired original/result previews covered all four pages; Previous moved page 4 to 3 by keyboard, Next returned page 3 to 4 by click, and first/last boundaries disabled their respective controls. The Page 3 group-context link moved the preview from page 4 to 3. Distinct figure/source-context identifiers for two draws of one image were visible. A document-scope problem at chapter revision 1 remained byte-for-byte intact through separate saves of the first and second figure descriptions at revisions 2 and 3. Each edit left the other occurrence unchanged, and all pending manual dictionaries remained identical. Both figure values stayed pending and unapplied; no Figure Accept or Group Approve was performed. Transient Select all plus group confirmation was cleared by switching to Tables and remained cleared when returning to Figures; figure/group approvals remained zero. The separate reading revision 3, source and existing immutable bundles remained unchanged through this chapter workflow.

The first native visible Stop ended the owned service before a normal Windows Start created fresh process/session authority with the same build and settings. Native reopening after this full application-service restart displayed both exact revision-3 reviews: the accepted-but-unapplied reading title and blocked note, plus the chapter blocker and both different pending/unapplied figure drafts. No review, approval or processing mutation occurred during recovery. The final native Stop displayed the stopped notice; the independent lifetime observer recorded exit at 02:57:26.493684 UTC on October 21. OS identity/TCP inventory confirmed the owned service and launcher absent and port 62621 closed. This was an application-service restart, not a Windows reboot or forced-crash test. The 20 bounded native observation groups cover the retained tags 20-89, excluding the missed targeting attempt at tag 33. Final audits confirmed both complete revision-3 states, all 62 current saved/input/run/export files, 32 immutable bundle files, three review exports and the exact native/retained reading download unchanged through restart, reopening and final Stop.

Final audits preserved all 344 protected original/review/runtime files and eight earlier trials: 14 reviews/bundles, 220 immutable files, 38 bindings, 33 exports, 928 installed source files, 4,836 retained trial files and 1,497 retained installed files. Phase A retained its review, 16 immutable files, 118 source files and 36 native proof files. Phase B retained both revision-3 reviews, 32 immutable files, all 62 saved/input/run/export files, three exports and the matching native/retained download through restart, reopening and final Stop. Historical findings and incomplete dispositions remain unchanged.

Evidence is retained outside Git under ignored
`work/native-keyboard-20261020-01/`. Start with `PhaseB-native-summary.json`, `phaseA-native-summary.json`, `final-preservation-audit.json` and `notes-edit-fix/prepared-final/prepared-suite-summary.json`. The directory
retains staged/full-suite results, guarded source/documentation baselines,
red/green controls, independent review, native observations, snapshots and
preservation audits. A Windows security overlay interrupted Phase A and cleared without automated interaction; tag 16 is not Stop proof. In Phase B, an offscreen saved-card UIA click at tag 33 missed into the address bar; Escape, browser Find and Return produced the actual reopen at tag 35. The separately generated standalone one-page figure fixture was not processed. A two-name picker attempt selected only the chapter, so no multi-file upload pass or confirmed application defect is claimed. No group approval was clicked.

Complete the remaining full Windows keyboard protocol and supported modifier combinations, multi-file picker qualification, grouped exceptions and individual/group acceptance controls, and seeded negative controls beyond the authored missing-description chapter. The completed page, occurrence and selection-reset cases remain bounded developer proof.

Genuine nontechnical-user semantic/usability review, experienced screen-reader
acceptance and explicitly authorized the LMS accessibility checker work remain open. Synthetic
reviewer attribution and developer screenshots do not complete those reviews or
create verified status. The older unexplained closure remains undiagnosed;
observed Stops do not explain it. Any later integration proposal still needs
exact final source/artifact and selected-target binding plus separate owner
authorization.

## Background keyboard shortcut fix and source-distributed renderer regressions — October 20

Continued detached validation HEAD `9d857fa16bc92aaf5a416fe833e6481ea9049ad0`
with all twelve existing changed-file contents preserved. No desktop input,
browser launch or application/native PDF/model/OCR process was used. Test-only
loopback/worker/provider doubles remain explicitly separate from real services.

The sole application change makes the review-tab keydown handler return before
processing Ctrl/Alt/Meta/Shift-modified keys. Bare arrows/Home/End keep existing
selection, focus, panel visibility and roving tab stops. The saved-note, skip-link,
dashboard and protected-action corrections remain intact. Original PDFs, saved
reviews, runtime configuration and all earlier trial evidence remain untouched.

Added source-distributed `scripts/test-web-assets.cjs` (narrow Git allowlist and LF
rule) plus `tests/test_web_assets.py`, included in the exact source-only list.
The original 18 actual-script session/dashboard cases remain, with seven new
saved-note renderer cases and 14 keyboard-event cases: **39 pass, zero failures
or skips** under Node 24.21.0 using named DOM/HTTP doubles. Actual Open/group/
filter/Back/reload event paths retain occurrence-specific notes/statuses, literal
text, unchanged snapshots and no fabricated selection or approval requests.
The earlier handler fails five modifier cases; an isolated removal of the note
assignment fails six renderer cases. These are authored regression controls,
not native browser or human-accessibility observations.

The fresh disposable source-only suite passed **654 tests in 90.05s**, zero
failures/skips. The 39 JavaScript cases are included as one Python entry, not
added to that Python count. Native-JAR and licensed-font test modules are explicit
source-only exclusions, not skips. Final affected wrapper/39 cases passed again
after placing the Node version diagnostic before imports. Missing Node refuses
before subprocess execution; authored old-version probes refuse clearly. Node.js
20+ is now an explicit developer-test prerequisite, checked before cloud venv
setup; the application setup/runtime and source-updater payload stay unchanged.

Independent review found no remaining actionable integration issue. READMEs/
checklists now provide the source command and distinguish current software proof
from earlier 666 prepared/185 focused/native Windows evidence. No new prepared
or native Windows run is claimed after this handler change. The next desktop
session should verify native Ctrl+Home and other modified-key behavior plus bare
navigation/focus, then continue figure/group/keyboard acceptance. Actual-user/AT
and the LMS accessibility checker remain deferred, and the earlier closure is still undiagnosed.

Evidence is retained under ignored `work/background-ui-fixes-20261020-01/`:
start with summary.json and software-results.json. Exact source backups/manifests,
39-case TAP, red/green/missing-note and prerequisite controls, source-suite output,
independent review and installation/integrity helpers are retained. The summary
also identifies the fresh mirror source copy containing generated synthetic test
artifacts. No merge, commit, tag, release, upload or distribution occurred.

## Current checklist reconciliation and accumulated code review — October 20

Continued the detached validation checkout at `9d857fa16bc92aaf5a416fe833e6481ea9049ad0`
without changing its eight pre-existing dirty-file changes, application/setup/test
bytes, runtime, documents or saved reviews. Reconciled STATUS, RELEASE-READINESS,
ACCEPTANCE-TESTS and HOME-DESKTOP-HANDOFF against the retained October 19–20
reports. Completed bounded Windows setup/sharing-denied recovery, launcher,
cancellation, graceful restart, saved-value reload, download and visible Stop are
now distinguished from broader keyboard/human acceptance still pending. Historical
failed/incomplete attempts and their evidence are retained unchanged.

Independent static reviews cover the working backend/dashboard/tests and
frontend/setup corrections, available committed retry/session/cancellation/Apply
changes from `ee702a8` through HEAD, and the earlier source updater plus bounded
line-separator/preservation code. No new actionable regression was identified.
Opening/protected actions retain full artifact checks, later human revisions
prevent outdated Apply attachment, and originals/bundles remain separate. This is
a scoped code review, not proof of every runtime or platform condition.

The retained actual-app.js Node VM harness was rerun: **18 passed, zero failures
or skips**. No browser/service/PDF/provider/native process was started. Its named
DOM/HTTP doubles cover session/skip and saved dashboard labels, not the saved-note
textbox. The setup matrix and JS harness are retained local evidence, not source
clone test assets. The known modifier-key interception of Ctrl+Home in the tab
handler remains a broader keyboard follow-up, alongside renderer automation
coverage. The earlier **666 prepared / 185 focused** results stand; no full suite
rerun is claimed for documentation edits.

The historical integration base was initially absent locally. A final read-only
fetch of the existing private origin's main succeeded and resolved to
`37fbf10ba18a7a8f206100e35dc458a09b079168`, with merge base `762b087`.
Main's source/tool/test tree matches the initial available source baseline. The
complete committed comparison (34 source/tool/test files, 2,759 inserted/155
removed lines) and working corrections were reviewed, with separate fixture/
assertion and qualification-tool audits. No source, reset, merge or push resulted
from the fetch. The final proposal must still bind the selected target and tested
bytes. Actual-user/AT and the LMS accessibility checker testing remains deferred; the old closure
remains undiagnosed and reboot/crash/ACL/disk variants are separate scope.

Exact before copies, diff snapshots, independent audit notes, rerun output and
documentation/source/preservation checks are retained locally under ignored
`work/readiness-review-20261020-01/`. This task used no desktop input. AI/OCR stay
off; no merge, commit, tag, release, upload or distribution occurred.

## Native Windows browser recovery, download and visible Stop completed — October 20

Retried from detached validation base `9d857fa16bc92aaf5a416fe833e6481ea9049ad0` with the already
validated dashboard/notes/skip-session fixes and preserved all eight existing
changed files. A fresh disposable installation copied all 116 tracked working
files. Its five actual Setup/Start preparation checks passed in 24.203s
with selected local-runtime.toml and ordinary Windows default-browser handoff.
No application source changed during this checkpoint.

**The bounded native browser retry passed all 11 observations, with zero findings.**
Actual Edge control worked on this turn. A native Open dialog selected the exact
new disposable authored PDF. Processing options visibly retained `Leave OCR off`
and no optional repair choices. Native Process completed a separate immutable
candidate with validator 1.30.3, supplemental and every-page fidelity passes.
Five human checks initially remained pending, zero approved.

Native typing/save retained `Browser recovery retry title` as a pending draft,
and `Browser recovery retry note` as blocked on `unsupported-content` with the
fixture attribution `Synthetic browser recovery retry fixture`. Revision 2 has
four pending checks, one blocked, zero approved; no value was accepted/applied.
The dashboard visibly labels the entry `Saved: Needs attention` and explains
that opening checks current files. Native reopening displayed both exact values.

Plain Ctrl+R retained authenticated access and both exact values after reopening.
Two native Shift+Tab actions visibly reached Skip to workspace; Enter activated
`#main`. Ctrl+R with that destination retained authenticated access and both
values/statuses after another reopen. All saved revision-2 state bytes stayed
identical through recovery and download, SHA-256 `a8a0f3005bf65768c89a7ff24be2ce5a5f822ee105fed929eae6406f0f96fe3d`.
The attribution entry field resets on a full reload while saved note attribution
remains in raw state. This is not lost review data.

Actual browser Download result completed as `authored-browser-reading-review-draft (1).pdf`,
appropriately labeled review-draft for blocked/unapplied review state. Both the
download and retained copy match unchanged candidate SHA-256
`85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
No PDF metadata was changed by saving the pending title.

Clicking the visible Stop application button displayed exactly `The local
application has stopped. You may close this tab.` The authenticated Stop log is
22:05:28.912557 UTC, service-closing log 22:05:29.123398 UTC, and the independent
lifetime observer recorded PID 98008 absent at 22:05:29.694009 UTC. Owned process
identities and the OS TCP inventory independently confirm exit/no listener.
No background API Stop was used. The stopped test tab and older stopped tab
were left open; no unrelated browser tab/window was closed.

Five final integrity checks and 8 independent raw-evidence checks passed.
All 16 immutable bundle files, original input/config/sentinels and the saved
review remain coherent. All 344 protected original/review/runtime files, all
116 copied source files and seven prior trials remain unchanged. Those earlier
trials retain 13 reviews/bundles, 204 immutable files, 35 binding references across
32 distinct files, 33 exports, 812 installed source files and 4,744 retained
evidence files. Historical incomplete/finding dispositions remain unchanged.
Application provider requests: zero; AI/OCR stayed off; human verification false.

Local evidence: `work/windows-launcher-browser-recovery-retry-20261020-01/`.
Start with `native-browser-recovery-retry-summary.json`; raw native observations,
19 screenshots/accessibility captures, six raw snapshots, actual downloaded PDF,
shutdown marker/log/lifetime stream, seven-prior baseline and audit/helper copies
are retained. Reproduction uses the retained preparation helper with a fresh
trial; browser_recovery_retry_support.py records identity/download/lifetime only,
and check_launcher_reopen.py records named raw snapshots. Processing and review
mutations in this trial were all native UI actions.

Automation recovered a title-selection mismatch and delayed UIA state captures
using fresh returned windows/screenshots. The chooser lacked a standalone tree,
but visible caret, typed path, selected filename and bound source hash establish
selection. Ctrl+Home on a focused review tab selected the first tab instead of
scrolling; native scrolling was used and that shortcut is not a passing keyboard
case. Snapshot-after-reopen was retained immediately after starting plain reload;
the native reopen proofs precede it, and separate post-reload proofs follow.
This does not constitute the full keyboard protocol or general accessibility
acceptance. Windows reboot, forced crash, cancellation rerun, actual-user/AT and
the LMS accessibility checker remain outside this bounded retry. The old unexplained closure's
cause remains undetermined; this successful observed Stop does not explain it.
The earlier 666 prepared/185 focused/18 VM software results stand, with no suite
rerun here. Only this handoff checkpoint changed in the tracked checkout; no
merge, commit, tag, release or external publication occurred.

## Dashboard responsiveness fix and blocked Windows browser recovery rerun — October 20

Continued detached validation base `9d857fa16bc92aaf5a416fe833e6481ea9049ad0` while preserving
the five existing changed files. A guarded four-file fix updates workspace.py,
web.py, app.js and existing test_web.py; prior app.js skip-reload and notes fixes
remain intact. Exact original working bytes are retained locally.

The timeout mechanism was reproduced using exclusive copies of the six saved
reviews from the preceding cancellation trial, reading bound artifacts only.
One direct dashboard call took 3.594s. Four simultaneous calls took 11.171–19.484s,
exceeding the earlier observers' 10-second budget. Every old dashboard poll ran
full bundle/binding checks and prepared-PDF inventory under the global PDF lock.
The new dashboard reads checked saved-state envelopes and labels cards
`Saved: ...` / `Saved review. Open to check current files.` It grants no fresh
artifact authority or automatic-completion claim. Opening, downloading,
exporting, editing and approval retain complete validation. The same direct
profiles now take about 0.031s, including all four concurrent calls. This is a
bounded software timing reproduction, not a general performance guarantee.

Windows focused regressions: **185 passed in 26.77s**, including nine new cases
for lock-independent summaries, unchanged saved choices/bytes, corrupt states,
all three tampered source/output/prepared bindings and protected refusals, plus
safe lifecycle logs. Actual app.js under the Node VM passed **18 checks**, with
no failures/skips; the original 13 session/skip checks remain. The complete
prepared Windows suite on the new disposable source passed **666 tests in
90.05s**, no failures/skips. Named worker/validator/provider doubles remain
software contracts, separate from native browser/PDF/human acceptance.

Closure investigation found no retained command establishing the earlier
service/Edge disappearance, no recorded exit status, and no matching application
crash event in the narrowly queried interval. The launch command had completed
about 26 minutes before later successful work, ruling out immediate cleanup at
that command's return. Logged client disconnections are handled on request
threads and do not establish fatal main-server failure. Suppressed request logs
cannot exclude an outside authenticated Stop. The old closure cause remains
unknown. New fixed UTC Stop-request and service-closing messages retain no URL,
token or configuration, and do not alter shutdown behavior.

A fresh disposable Setup/Start passed all five checks in 25.750s
and opened Edge normally. **Native browser recovery and Stop rerun is incomplete.**
At the first window-state capture, Computer Use automatically stopped because it
could not determine the current browser URL confidently enough to enforce
policy. No desktop input, upload, processing job, saved-review recovery, browser
download or native Stop occurred. No further Windows input or alternative UI
control was attempted. Only the exact owned disposable service was then stopped
through its authenticated local API as cleanup; its lifetime observer recorded
exit and OS TCP inventory confirmed no listener. The application log retains both
new shutdown diagnostics. This background cleanup is not native Stop proof.

All 344 protected original/review/runtime files and the six prior browser trials
remain unchanged: 13 saved reviews/bundles, 204 immutable files, 35 binding
references across 32 distinct bound files, 33 exports, 696 installed source files
and 406 retained evidence files. AI/OCR stayed off, provider requests were zero,
and human verification remains false. No merge, commit, tag, release or external
publication occurred. The fresh browser may still show its stopped local page;
its tab was not closed by automation after the policy stop.

Local evidence: `work/windows-launcher-browser-dashboard-recovery-20261020-01/`;
start with `dashboard-recovery-summary.json`. Investigation profiles, closure
timeline, guarded source backups/patch, JS checks, independent audits and helper
copies are retained under investigation-evidence. The full prepared output is
prepared-suite.log. Reproduce the direct timing with profile_dashboard_recovery.py
and fresh tags; native browser steps must resume in a later authorized turn with
working URL verification. Remaining steps are native upload/process, saved-value
reopen/reload, bound download and visible Stop with process/listener confirmation.
The earlier native cancellation/Retry results remain historical bounded proof.

## Native Windows active-job cancellation and recovery — October 20

Continued detached validation base `9d857fa16bc92aaf5a416fe833e6481ea9049ad0` on a fresh disposable
installation, retaining all five existing changed files. The five actual Windows
preparation checks passed in 22.860s; ordinary Start opened
Edge and honored the selected local-runtime.toml. AI/OCR stayed off.

**Bounded native workflow: six passed observations, four recorded findings/limits.**
This is not an all-browser-checks-passed result. Five final integrity checks and
12 independent raw-evidence checks passed. No application source changed.

The confirmed native Cancel targeted active job `7e424d012f924281ba3005ba`
after real owned Java work had been observed on a 2,000-page workload. This is
ten repetitions of one authored 200-page book, not 2,000 unique semantic pages.
The sampled transition from running to cancelled/no descendants fell within
(1.506, 3.805] seconds after the click-command-start marker. This is not HTTP
latency or proof that Java was alive/killed at the exact click. The UI reported
`Processing was cancelled; no unfinished result was released.` The coherent
failed bundle retained InterruptedError/cancelled evidence and no published PDF;
all five sampled worker/native process identities exited. The service was still
alive at that cancellation checkpoint. Two earlier 200-page runs completed
before a confirmed Cancel; both remain excluded from cancellation success.

Native keyboard Retry started separate job `301c5897f05e4ac9a3213b15` using
the same source/settings and preserved the cancelled review/bundle. Retry
completed its assessment; gate1 passed, gate2 and fidelity failed, and output
correctly stayed withheld. The repeated fixture does not gain candidate status.

A separate ordinary one-page recovery was initiated once through the local API
and completed a coherent new native candidate with all three gates passing.
Candidate SHA-256: `85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
This proves bounded processing/artifact recovery, not native browser initiation,
download, or an observed terminal in-memory job status. The Windows Open dialog
became inaccessible to the automation target/cache, so those browser steps stay
unverified. Both dashboard observers exceeded their 10-second read timeout;
client-disconnection traces remain in the application log. Dashboard refresh
rehashes/inventories saved PDFs under a shared lock, a plausible large-history
cost but not a confirmed timeout cause or proof of failed processing.

Fresh observation afterward found the service PID and Edge window absent before
this agent issued any shutdown. The cause remains unknown; normal native final
Stop is not claimed. Owned-process checks and the OS TCP inventory independently
confirm no matching service/launcher or listening socket on the disposable port.
Unsuccessful socket probes are not counted as listener-closure proof.

The API-prepared control stayed byte-identical at revision 2, including pending
title `Active cancellation preserved title`, blocked note `Active cancellation
preserved note`, synthetic attribution and existing export. Four checks remain
pending, one blocked, zero approved. No edits were accepted/applied or presented
as human verification. All six current bundles/reviews remain coherent; all 344
protected original/review/runtime files and all 116 copied source files match.
The five earlier browser trials retain seven reviews, seven bundles, 112 immutable
files, 21 binding references across 19 distinct bound files, and 30 export files.
Provider requests: zero; OCR never ran. The earlier 657 prepared-suite result
stands and was not rerun here.

Local evidence: `work/windows-launcher-browser-active-cancel-20261020-01/`;
start with `native-active-cancel-summary.json`. Browser observations, raw monitor
streams, final snapshots, provenance/renders/screenshots, independent audit,
closure evidence and exact helper copies are retained there. Reproduction uses
the retained prepare helper against a fresh trial, `active_cancel_support.py seed`
for explicit non-UI control preparation, and separate read-only monitor prefixes
around native Process/Cancel/Retry. The seed/recover mutations must not be
repeated against existing evidence. Dashboard observation should use bounded,
infrequent requests; timeouts do not cancel already-started work.

Native short-file selection/download recovery and a normal final Stop remain
unverified in this trial. Dashboard responsiveness with large saved histories
and the unexplained closure need further diagnosis. No Windows reboot,
assistive-technology/actual-user acceptance or the LMS accessibility checker work occurred.
Only this handoff checkpoint changed in the tracked checkout; no merge, commit,
tag, release or external publication occurred. Release gates remain open.

## Native Windows full restart and saved-review recovery — October 20

Continued from detached validation base `9d857fa16bc92aaf5a416fe833e6481ea9049ad0` and preserved all
five existing changed files. A fresh disposable installation copied all 116
current tracked working files and honored its selected `local-runtime.toml`.
All five actual Windows preparation checks passed in 22.422s.
Normal Windows Start opened Microsoft Edge with no named-browser override.

**Native full-application-restart/recovery workflow: 17 passed, zero findings.**
An authored one-page PDF processed with AI/OCR off into a passing immutable
candidate. The exact draft `Full restart saved title` was saved as pending;
`Full restart problem note` was reported as blocked on `unsupported-content`
with the fixture label `Synthetic full restart fixture`. Revision 2 retained
four pending checks, one blocked check and zero approvals. No draft was accepted,
applied to the PDF, or presented as human verification.

The first native Stop displayed `The local application has stopped. You may close
this tab.` Its owned process and listener were independently confirmed closed.
Desktop input was held when an unrelated OpenExplainer window repeatedly moved
over the browser; work resumed after the owner explicitly confirmed availability.
Fresh inventory then showed no Edge window: the prior browser had closed outside
this agent's UI actions, so no agent-driven initial-tab closure is claimed.

Actual Start against the same disposable installation and saved-review data
completed in 3.765s. Service identity changed from PID
21264 to 97420, and the private token fragment's
SHA-256 changed directly; rotation was not inferred merely from the new port.
Build/settings digests and independently hashed installed source, configuration
and runtime identity stayed unchanged. Fresh Edge listed the saved document as
Needs attention. Reopening displayed the exact pending title and blocked note.
The reviewer entry field appropriately reset while saved note attribution stayed
in the raw review and both exports.

Plain Ctrl+R retained authenticated access. Native Tab/Enter activated Skip to
workspace; Ctrl+R with `#main` also kept authenticated access. Reopening again
displayed both exact values/statuses with zero approvals. All raw saved review
bytes stayed identical through restart, reopening, reload and the final snapshot,
at revision 2 and SHA-256 `6c6fafeb7e99cfef3401838d9e349f9870067336cfae9532012d8881ccdbc203`. No post-restart edit was made.

Both actual browser downloads and retained copies match unchanged candidate
SHA-256 `85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
The pre-edit download was labeled candidate; the current blocked/unapplied review
correctly downloaded as `authored-browser-reading-review-draft.pdf`, serving the
same bound PDF bytes. A trial retention-helper filename assumption was corrected
after a missing-file refusal; application source and reviews were not changed.
Two separate native exports at revision 2 preserve the exact title, note,
statuses, attribution and candidate binding; the earlier export stayed intact.

Final native Stop displayed its success message. The initial and restarted owned
services exited, their listeners closed, and the new trial's only browser tab was
closed with one Ctrl+W. Fresh inventory confirmed no Edge window remained.
All five final integrity checks and eight independent raw artifact checks passed.
The 16 immutable bundle files retain validator 1.30.3, supplemental and every-page
fidelity passes with exact output hashes. Application provider requests: zero;
OCR never ran. All 344 protected existing original/review/runtime files, all 116
copied source files, and the four prior browser trials stayed unchanged. Those
earlier trials retain six reviews, six bundles, 96 immutable files, 18 binding
references across 16 distinct bound files, and 24 export files.

Local evidence: `work/windows-launcher-browser-full-restart-20261020-01/`.
Start with `native-full-restart-summary.json`; native observations are in
`browser-results.json`, shutdown/integrity in `browser-final-summary.json`, and
independent proof in `full-restart-invariants.json`. The directory retains raw
before/after snapshots, both downloads/exports, token hashes without plaintext
authority, 12 screenshots, pause history and helper copies. Existing exclusive
creation guards prevent overwriting evidence. For a further trial, run the
retained preparation helper with a fresh direct child of validation/work, take
named snapshots with `check_launcher_reopen.py`, perform native Stop, then run
`restart_launcher_browser_check.py` once. Finalize only after native completion
and run the independent audit before changing tracked documentation.

This is one graceful application-service restart of one authored developer
fixture. Windows reboot, forced crash/corruption, active-job interruption,
multi-page/figure editing, actual-user/assistive-technology acceptance and Canvas
the LMS checker were not tested. Native clicks/value entry and scrolling were used alongside
keyboard skip/reload; the full keyboard protocol was not repeated. Preview-cache
regeneration is outside immutable-bundle preservation claims. The earlier 657
prepared software result stands and was not rerun. Only this handoff checkpoint
changed in the tracked checkout; no application code, merge, commit, tag, release
or external publication occurred. Human verification and release gates remain.

## Native Windows skip-link reload recovery completed — October 19

The owner confirmed the desktop was free. Continued on detached validation base
`9d857fa16bc92aaf5a416fe833e6481ea9049ad0` with all existing changes intact,
including the saved-note display and narrow `#main` bootstrap corrections.
A new disposable installation copied all 116 current tracked working files;
all five preparation checks passed in 40.422s.

**Native Windows browser/keyboard workflow: 24 passed, zero findings.** Actual
Start used the normal Windows shell route with no browser override. Native
inspection confirmed **Microsoft Edge 155.0.4283.62** on registry build
26200.9711. A verified normal-user shell association query resolves HTTP,
HTTPS and .html to Edge, although raw HTTP/HTTPS UserChoice still names
ChromeHTML. No settings changed and Chrome rendering was not tested. Earlier
restricted-sandbox OpenWith observations remain historical, not the current
effective-shell result. This was native Computer Use, not the in-app browser.

Tab/Shift+Tab and Enter operated the skip link, file chooser and Windows file
dialog, processing and result actions. Space operated disclosures; arrows and
Home/End operated preview layouts, the review tab strip and group choices.
Selectable text exposed both authored anchors. Native processing used AI/OCR
off and produced a passing candidate, with validator, supplemental checks and
every-page fidelity all passing. The native-browser download and retained copy
both match candidate SHA-256
`85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.

**The skip-link reload finding is resolved in this bounded native retest.**
After activating Skip to workspace, a keyboard-saved pending title survived
Ctrl+R with `#main` retained. Activating Skip again and repeating Ctrl+R also
kept authenticated access. Keyboard reopening displayed exactly
`Native keyboard saved title`, still pending, with zero approved checks.
Raw saved bytes, revision, all 16 immutable bundle files, source/output bindings,
service PID/creation time and private-session hash matched across both reloads.
The original private-link error did not recur.

Blank keyboard problem-note submission was refused with
`Describe the problem before recording it.` The authored
`Native keyboard problem note` then saved as blocked on `unsupported-content`
under a synthetic fixture label. Document close/reopen navigation displayed it,
and a third `#main` reload retained both that blocked note and the pending title.
The title/reload reopening was keyboard driven; note roundtrip navigation used
native UI clicks, followed by keyboard navigation. No title acceptance or human
check approval occurred. Keyboard exports at revisions 0 and 2 were independently
checked against each export's own saved revision, including the final note.

Native Tab/Enter Stop displayed `The local application has stopped. You may close
this tab.` The owned processes exited and private listener closed. Only this
trial's tab was closed; fresh window inventory confirmed the earlier tab remained.
Visible focus outlines and actual outcomes supported keyboard observations;
stale focused-element metadata was excluded. Window/full-screen setup and two
automation recovery actions are recorded separately and are not application
findings or additional passing UI cases.

All **five final integrity checks** and **eight independent raw artifact checks**
passed. All **344 protected existing original/review/runtime files** and all 116
copied source files remained unchanged. The three earlier browser trials retained
all five saved reviews, five immutable bundles, 80 files and 15 binding references
across 13 distinct bound files. The interrupted previous trial remains a separate
incomplete historical record; five additional preservation checks passed for its
retained source/input/config bindings, fix evidence and partial-test disposition.
No earlier complete tree manifest exists for that trial, so unbound temporary,
environment and log bytes are outside its historical hash comparison.
Application provider requests: zero; OCR never ran.
Only this handoff entry changed in the tracked checkout for the current native
UI-only pass. The earlier 657-test prepared result stands; it was not rerun here.
No merge, commit, tag, release or external publication occurred.

Local evidence: `work/windows-launcher-browser-skip-recovery-20261019-02/`.
Start with `native-skip-recovery-summary.json`; native cases are in
`browser-results.json`, final integrity in `browser-final-summary.json`, and
independent artifact checks in `skip-session-invariants.json`. Raw snapshots,
both exports, verified machine associations, 11 screenshots, native download and
helper copies remain ignored and local. Preparation's running-service status is
superseded by final shutdown evidence. This is one-page developer workflow
evidence; multi-page/figure editing, active cancellation, a full app restart,
actual-user/assistive-technology acceptance and the LMS accessibility checker remain outside this
rerun. Human verification and release gates remain unchanged.

## Skip-link session fix and background Windows checks — October 19

Continued on detached validation base `9d857fa16bc92aaf5a416fe833e6481ea9049ad0`,
preserving the existing five changed files. The `app.js` bootstrap now reserves
only the known `#main` skip-link destination as navigation and reuses the stored
private authority for that fragment. It leaves the anchor intact. Every other
nonempty supplied launch fragment still overrides stored authority and reaches
the unchanged server authentication checks. The earlier saved problem-note
display fix remains in place; no saved review, backend route or migration changed.

The complete actual script under a Node VM with explicitly named DOM/HTTP
doubles passed **13 checks**, with no skips. The preserved original working
script reproduced exactly four expected `#main` failures (9 passed, 4 failed).
Existing focused Windows Python regressions passed **170 tests in 28.19s**.
The complete prepared Windows software suite subsequently ran against the
disposable copied source with the reviewed native JAR and hash-pinned AMSFonts
archive: **657 passed in 182.09s**, no failures or skips. The 170 focused
tests are included in that prepared total. Contract tests retain their named
worker/validator/provider doubles; these results do not establish native browser
or human accessibility acceptance.

A fresh disposable Windows installation passed all **five preparation checks**
in 30.000s with the selected `local-runtime.toml`. Actual Windows Start opened
Edge through the normal shell route; native Tab reached the visible skip link.
**The native rerun is incomplete:** the owner stopped Computer Use with physical
Escape before the fixed skip/reload sequence or any new document processing.
The owner then asked for background work while using the desktop. No further
mouse, keyboard or browser control occurred. The exact native reload recovery,
saved title/note, processing/download/export and keyboard shutdown sequence
must still be repeated once the owner says the desktop is free. The prior
confirmed finding remains historical evidence, not a completed native retest.
Raw HTTP/HTTPS associations still named ChromeHTML while actual shell launch
opened Edge; no settings were changed and Chrome rendering was not tested.

Background cleanup authenticated and stopped only this trial's owned private
service after checking PID creation time and exact data directory. Its owned
processes exited and loopback listener closed. The native browser tab was left
alone after the owner stopped UI control. No new document, review, model-cache
or export was created in the interrupted trial. No private token appeared in
public service/setup logs.

All **344** protected existing original/review/configuration files stayed byte
identical. All **116** copied tracked source files matched before and after the
suite. An independent read-only audit of all three prior browser trials found
all **five saved reviews, five immutable bundles, 80 bundle files and 15 binding
references across 13 distinct bound files** unchanged. AI/OCR remained off;
provider contract doubles are not live model requests. Only this dated handoff
entry and the narrow bootstrap correction were added to the prior working
changes. No merge, commit, tag, release or external publication occurred.

Ignored local evidence: `work/windows-launcher-browser-skip-fix-20261019-01/`.
Read `skip-session-background-summary.json` for the current partial disposition,
`background-check-summary.json` and `background-prepared-tests.log` for the full
prepared scope, and `skip-session-fix-evidence/` for preserved before/after
startup tests and prior-trial preservation audit. `background-helper-copies/`
retains runnable background helpers. Preparation's earlier running-service
status is superseded by the recorded owned-service shutdown. No completed
browser-results or final native success has been manufactured for this run.

## Native Windows shell browser and keyboard workflow — October 19

Continued from validation base `9d857fa16bc92aaf5a416fe833e6481ea9049ad0`,
preserving all five already changed files, including the saved-note display fix.
A fresh disposable source installation copied all 116 tracked working bytes.
Five preparation checks passed in 26.875s. Actual Windows Start used its normal
Python `WindowsDefault` / `os.startfile` route, with no named-browser override.
Native Windows UI inspection confirmed that route opened the private workspace
in **Microsoft Edge**; its registered executable version was **155.0.4283.62**.
This run used the Computer Use skill's native Windows controls, not the in-app
Chromium browser from previous checkpoints.

Machine association observations disagree: raw HTTP/HTTPS UserChoice names
ChromeHTML (registered Chrome executable 155.0.8059.82), while a read-only shell
protocol query returns OpenWith / Pick an app and its .html query names Edge.
The cause of that disagreement is not established. The app delegates normally
to the shell and the observed browser was Edge; no Chrome rendering or cleanly
configured default-browser claim is made. No browser association or other system
setting was changed. Machine evidence retains raw Windows build 26200.9711.

**Native browser/keyboard observations: 19 passed and one confirmed finding.**
Native Tab/Shift+Tab, Enter, Space, arrows and Home/End reached and operated the
skip link, PDF chooser and Windows file dialog, processing options, processing,
download/export, preview-layout choices, selectable text, review tabs/groups,
occurrence evidence, title draft and problem-note controls. Visible orange focus
outlines and UI outcomes were inspected. Window-size/full-screen setup and input
recovery were not counted as keyboard workflow actions. Some native accessibility
focused-element metadata was stale, so no focus claim relies on that field alone.
An initial shared-desktop input interruption was excluded; testing resumed only
after the owner explicitly confirmed the desktop was free.

The authored PDF processed with OCR/AI off. The candidate passed validator,
supplemental and every-page fidelity gates, and its native-browser download SHA-256
matched `85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
Export records were created at revision 0, before later title/note edits, and
were checked against that revision rather than the final review. A title saved
by keyboard remained pending; it did not change the actual PDF or invent
approval attribution. Blank problem-note submission was refused with the status
message `Describe the problem before recording it.` An authored problem note
then saved visibly as blocked under a synthetic fixture label. No human check
was approved. After Save/Report redraws, the next Tab returned to the first
control in the corresponding redrawn card; sequential navigation continued.

**Open finding:** activating Skip to workspace adds `#main` to the address. A
later Ctrl+R treats that navigation fragment as private launch authority,
replaces the saved browser token, and shows `Open the private launch link to use
this review session.` with an empty dashboard. This is a confirmed browser-session
recovery defect, not observed deletion of the saved document. The source cause is
`app.js` selecting every nonempty `location.hash.slice(1)` before sessionStorage;
the skip link in `index.html` uses `href="#main"`. Application code was not fixed
in this check-only task. The concrete next step is to separate navigation
fragments from private launch authority and repeat this exact skip/reload case.

The actual Windows Start helper recovered access without duplicating/replacing
the private service. Raw saved review bytes, all 16 immutable bundle files,
source/output bindings and service/session identity matched exactly before the
failed reload, after it, and after launcher recovery. Keyboard navigation then
reopened the saved pending title. Final native keyboard Stop confirmed shutdown;
the owned service and listener closed, and only this task's two test tabs were
closed. Existing browser tabs were left in place.

All five final integrity checks and seven additional raw artifact checks passed,
while retaining the UI finding explicitly. All 344 protected existing original/
review/runtime files remained unchanged, as did the four saved reviews, four
entire immutable bundles and bindings from the two prior browser trials. The
only new tracked change is this dated handoff entry; existing code changes remain
in place. The application made zero provider requests and never ran OCR. No
merge, commit, tag, release or external publication occurred. No Python suite was
rerun for this native UI-only checkpoint.

Ignored local evidence and runnable helper copies:

`work/windows-launcher-browser-default-keyboard-20261019-01/`

Read `default-browser-keyboard-summary.json` for the consolidated disposition,
`browser-results.json` for the 20 UI cases, `browser-final-summary.json` for final
shutdown/native preservation checks, and `native-keyboard-invariants.json` for
the exact failure/recovery/artifact bindings. Machine/routing observations,
raw snapshots, the retained native download, revision-0 exports and five
screenshots remain local. Preparation is an earlier checkpoint; final evidence
supersedes its intentionally running-service status. Reproduction requires a
fresh disposable installation and actual native keyboard actions; replaying raw
assertions alone does not reproduce UI evidence.

This is a bounded developer workflow in the Windows-shell-opened Edge browser.
Multi-page navigation, two-occurrence figure editing, active cancellation,
nontechnical-user testing, assistive-technology acceptance and the LMS accessibility checker remain
unperformed here. No human verification or release gate is waived.

## Saved problem notes display and Windows browser rerun — October 19

Resolved the saved-note visibility finding recorded in the previous dated
checkpoint. `renderManual` now assigns saved `item.notes` to the problem-note
input's value, with an empty default for absent notes. The single-line DOM value
assignment displays quotes, angle brackets and ampersands literally. It changes
no backend record, review revision, approval rule, endpoint or status transition,
and requires no review migration. Existing Return to pending behavior is unchanged.

Independent source review found only that one-line application change.
Focused Windows checks using the existing application environment passed
**146 tests in 27.30s**, with no skips or failures:

```powershell
& '.\.venvs\app\Scripts\python.exe' -B -m pytest -q tests/test_web.py tests/test_workspace.py --basetemp work/saved-notes-regression-20261019-01 --tb=short
```

Use a new basetemp when repeating. Retained test output is
`work/saved-notes-regression-20261019-01.log`. The prior full 657-test result was
not rerun for this rendering-only correction.

A fresh disposable Windows installation included all current tracked working
bytes and the existing setup fix. All five preparation checks passed in 29.547s.
Actual Start/reopen, settings/implementation mismatch refusals and stopped-app
restart passed again without duplicate services or changed saved reviews.
**All 22 connected-Chromium browser cases passed, with zero findings.**
The exact authored note `Saved note: "review" <literal> & keep` was visible after
saving, navigating away to another group and back, browser reload/reopen, and
full stop/actual Windows Start restart. Another item remained empty. Resaving
the recovered note without retyping preserved its text; both pre-resolution
exports retained it and the saved blocker. The screenshot and DOM observations
demonstrate the formerly failing UI behavior directly, beyond API persistence.

The broader rerun retained title draft/acceptance, keyboard tab/group navigation,
blocked-Apply refusal, native processing, source/result previews, export,
accepted-title application into a separate candidate, download, both result
entries and clean browser Stop. Only the synthetic blocker was deliberately
returned to pending after preserving its note in snapshots/exports. This did
not approve a human review check. Both candidates passed validator,
supplemental and every-page fidelity gates, with five human checks still pending.
The actual applied title and browser-downloaded bytes matched the bound candidate.

All five final integrity cases passed; additional raw-state/export/download
assertions are retained separately. All 344 protected existing original/review/
runtime files stayed identical. The earlier browser trial's saved states and
entire immutable bundles also matched their retained hashes. The existing four
changed files were preserved; this task adds the app.js correction and this dated
handoff entry. AI/OCR stayed off, no provider requests occurred, owned test
services/listeners stopped, and no merge, commit, tag or release occurred.

Local ignored evidence and helper copies:

`work/windows-launcher-browser-notes-20261019-01/`

Read `saved-notes-fix-summary.json` for consolidated results,
`browser-final-summary.json` for final preservation/native/shutdown checks,
`browser-results.json` for all UI cases, and `browser-application-invariants.json`
for independent restart/note/export/application/download bindings. The preparation
summary is an earlier checkpoint; the final summary confirms subsequent shutdown.
Reproduce with a fresh disposable preparation, actual browser actions and the
retained helpers. Raw assertions alone do not reproduce the browser observations.

This closes the recorded note-display finding for the bounded developer workflow
on this Windows computer. Default-browser visual rendering, broader keyboard
usability, actual-user/assistive-technology acceptance and the LMS accessibility checker testing
remain open. Human verification and release gates are unchanged.

## Disposable Windows launcher and browser workflows — October 19

Continued from detached validation commit `9d857fa16bc92aaf5a416fe833e6481ea9049ad0`
with all four existing changed files preserved. A fresh disposable source copy
included the current setup correction and all 116 tracked working-file bytes.
The actual Windows setup command installed its pinned environment and used the
selected external native tools from `local-runtime.toml`. Five preparation
checks passed in 31.156s. AI/OCR remained off throughout the trial.

The actual `Start PDF Remediator.cmd` / `pythonw.exe` / `launch_review.pyw` route
started the private service from an unrelated working directory, with a
space-containing installation path. Reopening used the same session and process
without duplicating the service or changing reviews. Two real installed-launcher
checks refused incompatible settings and implementation identities; temporary
changes were confined to the disposable copy and restored exactly. After the
browser stopped the app, actual Start restarted it with fresh private session
authority and byte-identical saved reviews/bundles. These checks observed the
default-browser handoff request; rendering was tested separately in connected
Chromium, not the system default browser's window.

**The connected-browser workflow recorded 17 passing cases and one UI finding.**
The authored one-page PDF passed native processing, with both page previews
loaded and visually inspected. Keyboard Tab/Enter reached processing options and
arrow keys switched review tabs. A title draft remained pending, survived reload,
and required explicit acceptance. A synthetic reported problem remained visible
after full app restart and caused Apply to refuse with a clear message. The
Apply button could be enabled while blocked; the server refused publication.
Exported review records retained the accepted title, attribution and blocker note.

**Open finding:** after reopening a saved blocked review, its problem-note field
was blank and expanded occurrence evidence did not show the note. Exact saved
state and exported `review.json` still contained the authored note, so this is a
browser visibility problem, not observed data loss. No application fix was made
as part of these workflow checks. Inspect the manual-item renderer's handling of
saved `notes` in `src/pdf_remediator/web_assets/app.js` when fixing this issue.

After intentionally returning only that synthetic blocker to pending, Apply
created a separate candidate. The initiating review and every original bundle
file retained exactly the same bytes. The actual applied PDF title was
`Authored Windows browser review title`; its SHA-256 and the browser-downloaded
PDF both matched:
`d62007b8518418c8bc7c204234a9d77305a9cc6e550ec6094f85c9927859f5ad`.
Both candidate reports passed validator, supplemental and every-page fidelity
gates, retained five pending human checks, and reported zero model requests.
The dashboard retained both separate review entries. Synthetic reviewer labels
are fixture evidence and do not represent actual-user accessibility acceptance.

Final browser Stop closed both owned service generations and their listeners.
All five final integrity checks passed in 2.750s. The original 344 protected
PDF/review/runtime files, authored input, configuration and sentinels were
unchanged. All 116 validation source hashes matched their pretest values before
this dated handoff addition. The earlier 657-test result was not rerun. No merge,
commit, tag, release, upload or publication occurred.

Full local evidence and helper copies remain ignored under:

`work/windows-launcher-browser-1792450229970/`

Read `browser-final-summary.json` for the completed disposition, `browser-results.json`
for all 18 UI observations, and `browser-application-invariants.json` for actual
PDF/title/download and review preservation bindings. `launcher-reopen.json`,
`launcher-mismatches.json`, `launcher-restart.json`, raw snapshots, pre-resolution
exports and screenshots retain the individual proofs. `preparation-summary.json`
is an earlier checkpoint that intentionally left the service running; the final
summary supersedes that service/workflow status. Helpers accept the existing
trial only for bounded launcher/snapshot/final integrity steps. A new complete
trial requires a fresh prepared directory and the actual browser actions;
replaying only raw assertions does not reproduce UI evidence.

These are bounded developer checks on this Windows computer and connected
Chromium. Broader keyboard usability, default-browser rendering, actual-user/
assistive-technology acceptance and the LMS accessibility checker testing remain open. The next
concrete follow-up is the saved problem-note display fix, followed by the same
reopen/export browser check on a fresh disposable copy. No release gate is waived.

## Setup honors the selected local runtime — October 19

Fixed `Setup PDF Remediator.cmd` on validation base commit `9d857fa` so its
readiness command passes the quoted `%~dp0local-runtime.toml` path when that file
exists beside the helper. Without the file, the original default-runtime command
is retained. The existing exit-code check still rejects invalid configurations
or unavailable required native tools; setup does not silently choose defaults after a
selected configuration fails. Pip/venv setup and desktop startup are unchanged.
The previous dated configuration caveat below is resolved by this local change.

**All 12 disposable Windows installation/configuration checks passed in
62.141s.** A fresh source copy with a space-containing path,
invoked from an unrelated directory, created its own isolated editable environment
through the actual fixed setup helper and normal pinned dependency installation.
With no native tools at package-relative default locations, setup completed using
the valid external paths from its local runtime TOML. Actual doctor JSON confirmed
every selected path and ODL 2.5.13/veraPDF 1.30.3, and setup left the TOML unchanged.
Imports, editable metadata, CLI/console entry points and dependency checks were
verified with PYTHONPATH unset.

Negative/default cases used only authored disposable configuration files with
retained verified backups. Missing config plus missing defaults refused honestly.
The harness then provisioned trusted tool copies into the disposable default
locations and independently proved default readiness. Even with those defaults
working, malformed TOML and a selected missing validator still failed without a
ready message or fallback. Missing config plus prepared defaults succeeded.
Restoring the exact original synthetic TOML restored selected-config success.

The installed private loopback service matched its real owned Windows child PID
and build/settings digests; authenticated access worked, absent-token and
external-Origin access refused, and authenticated shutdown closed all owned
service/launcher processes and the listener. No browser, document job, model
request or OCR processing occurred. Synthetic originals/review/config/venv
sentinels and all 344 protected existing original/review/runtime files remained
unchanged. The real validation source matched its pretest hashes throughout the
trial; this subsequent dated documentation update preserves the previous notes.

Exact local evidence and runnable harness copies remain untracked under:

`work/windows-setup-config-1792449672174/`

The authoritative report is `summary.json`, including the copied setup hash and
all per-case outcomes. Reproduce from this validation checkout into a new folder:

```powershell
$evidence = '.\work\windows-setup-config-1792449672174'
$trial = Join-Path $PWD ('work\windows-setup-config-' + [guid]::NewGuid().ToString('N'))
& '.\.venvs\app\Scripts\python.exe' -B -u "$evidence\windows_setup_config_check.py" $trial
if ($LASTEXITCODE -ne 0) { throw 'Inspect the retained fresh setup/configuration evidence.' }
```

This rerun covers the setup-only correction, not a new full Python/PDF/native
qualification or updater-denial rerun. Earlier bounded updater recovery evidence
remains intact. The source-only updater replaces only `src/pdf_remediator` and
does not distribute root setup helpers; this change is in the validation checkout.
Original PDFs/reviews remain intact, AI/OCR stay off, and no merge, tag, release or
publication occurred. Broader machine/UI/human accessibility gates remain open.

## Disposable Windows installation and sharing-denied update recovery — October 19

Continued from validation commit `9d857fa16bc92aaf5a416fe833e6481ea9049ad0`,
preserving the prior uncommitted handoff addition. All execution used fresh
disposable source copies under ignored `work/`, not the working installation or
its reviews. The existing 344 protected original/review/configuration files and
all 116 tracked files matched their pretest hashes before this documentation
update. AI/OCR stayed off. No browser or model request, merge, tag or release
occurred. The source updater and application code were not changed.

**Seven bounded installation/startup checks passed.** The unmodified Windows
setup helper created a fresh isolated Python 3.11 environment and installed the
editable app and pinned dependencies through the normal isolated-build workflow.
Imports, project root, version 0.3.0, console entry point and dependency checks
were verified from that disposable installation with PYTHONPATH unset.

Setup has a recorded configuration caveat: its readiness command does not load
`local-runtime.toml`; it checks package-relative native-tool defaults. With only
the valid external runtime config present, Python installation succeeded but
setup correctly reported its missing default native tools. Explicit-config
doctor was ready with ODL 2.5.13 and veraPDF 1.30.3. Copying those already reviewed
native components into this disposable copy's documented default locations made
the unmodified setup helper complete successfully. No native tool was installed
globally or changed in its original location.

The installed CLI then started a private, no-browser loopback service. The actual
service PID belonged to the launched Windows Python process tree; configuration
and implementation digests matched the disposable build. Authenticated access
worked, missing-token and external-Origin access refused, and authenticated stop
closed both service/launcher and the listener. No document, AI-cache or model
job was created and no private token was logged. Synthetic input/review/config/
environment sentinels remained unchanged. The original installation stage took
29.218s; corrected separate service verification took 2.422s. These are separate
executions, not a single combined timed installation claim.

**Seven updater checks passed in 7.687s** using the real 32-file package/archive:
CLI dry-run without mutation and full applied/backup hash verification; missing
ZIP, incompatible metadata and pre-existing lock refusals; and three real
Windows sharing-denial cases. Non-delete-sharing GENERIC_READ directory handles
caused actual PermissionError/WinError 32 outcomes. For staging/rollback timing,
an isolated process's observational rename audit hook acquired the handles and
returned normally to the real rename. No updater function, exception or ACL was
replaced, and the OS token was not administrator; no elevation was requested.

- Denied installed-to-backup rename left every installed hash intact.
- Denied stage-to-installed rename restored and verified the previous package.
- Denying both replacement and rollback produced explicit failed-recovery
  locations, retained the complete original backup and failed stage, and did not
  claim success. After releasing only the trial handles, a fresh verified copy of
  that retained backup restored the disposable installation. A subsequent update
  succeeded. Original recovery evidence was retained throughout.

Every native-denial case subsequently applied successfully after handle release,
with all new package and backup hashes checked. Protected local sentinels stayed
unchanged, owned updater locks were removed, and another updater's pre-existing
lock remained. The complete 3,221-file installed baseline and source ZIP matched
their before/after hashes across the updater checks.

Full evidence and copied harnesses remain local under:

`work/windows-install-update-1792448885617/`

Authoritative reports are `installation-final-summary.json` and
`update-checks-verified/summary.json`. Earlier harness attempts remain: a Windows
command-quoting error before setup; an overly strict launcher/service PID equality
check; and attribute-only directory handles that allowed renaming. Correcting
only those harness issues produced the passing records. Failed attempts and
their backups were not deleted or counted as passing recovery checks.

Reproduce from this exact validation checkout using the copied local harnesses
and a fresh output directory:

```powershell
$evidence = '.\work\windows-install-update-1792448885617'
$trial = Join-Path $PWD ('work\windows-install-update-' + [guid]::NewGuid().ToString('N'))
& '.\.venvs\app\Scripts\python.exe' -B -u "$evidence\windows_installation_check.py" $trial
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the fresh installation evidence.' }
& "$trial\disposable-installation\.venvs\app\Scripts\python.exe" -B -u "$evidence\windows_denied_update_check.py" --baseline "$trial\disposable-installation" --archive "$trial\reviewed-source.zip" --output "$trial\update-checks"
if ($LASTEXITCODE -ne 0) { throw 'Stop and inspect the retained updater recovery evidence.' }
```

These results establish named Windows sharing-denial/recovery and prepared
installation behavior on this computer. They do not establish all ACL-denial,
power-loss/disk-failure or fresh-computer installation cases, browser/keyboard
usability, actual-user/assistive-technology acceptance or the LMS accessibility checker results.
Those remaining gates are not waived by this bounded automated checkpoint.

## Home Windows native retry and saved-review recovery — October 18

The home validation checkout was tested at detached commit
`9d857fa16bc92aaf5a416fe833e6481ea9049ad0` using Python 3.11.9 x64,
Temurin 25.0.3+9, OpenDataLoader 2.5.13 and veraPDF 1.30.3. The owner separately
reported **657 prepared tests passed in 277.31s**; that suite was not rerun here.

A separate local Windows harness passed **11 bounded native/lifecycle checks in
27.141s**. The Linux-only lifecycle driver's platform guard and all production
code remained unchanged. The Windows harness used the validation checkout's
source, the explicitly selected existing native runtime, and a fresh authored
one-page reading. OCR was off and its optional executable paths were deliberately
unavailable in the trial's in-memory settings; no AI/provider request occurred.
The owner's runtime TOML was not edited.

The checks covered native readiness and an original candidate; deliberate
missing-validator refusal without publication; retry using the corrected Windows
runtime into a new workspace; accepted synthetic title application with fresh
native gates and the actual PDF title checked; accepted-state reconstruction;
both draft and accepted titles plus blocked-item notes surviving reconstruction;
stale-revision and blocked-Apply refusal; a later saved edit preventing an old
result from switching reviews while its completed bundle remained discoverable;
and queued retry cancellation without a new bundle. Candidate paths passed
strict validation, supplemental checks and page fidelity, retained five pending
human items, and had their exact published/assessed hashes checked. Five complete
immutable bundles verified. Source, initial and metadata-applied page previews
were rendered and visually inspected.

A **separate Windows process** then passed **3 reopen checks in 1.531s**, verifying
the draft/accepted title values and statuses, blocked notes, revisions, exact
saved-state bytes, retry history, latest edit and detached-result discovery.
An earlier follow-up harness lookup used the state's internal identifier instead
of its workspace folder identifier; its error evidence is retained. Correcting
only that harness lookup produced the passing separate-process result. No
application correction or weakened assertion was required.

The original/retry candidate SHA-256 was
`85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
The PDF with title `Authored Windows lifecycle title` had SHA-256
`0d091e9b9347fe92319e52c09b4a19ce6b39a4cf5a9617fb27e57a6130ba92bd`.
All existing protected evidence/config/source bindings (344 files) and all
116 tracked checkout files matched their before/after hashes at the end of the
checks. This dated handoff addition is the only subsequent tracked change.

Full local evidence, per-case report/manifest/state hashes, provenance and copied
harnesses remain untracked under:

`work/windows-native-recovery-1792368590026/`

The authoritative results are `summary.json` and
`separate-process-reopen-verified.json`; the earlier harness error remains in
`separate-process-reopen.json`. To repeat from this validation checkout, preserve
the evidence folder and use a new output:

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:PYTHONDONTWRITEBYTECODE = '1'
$trialOutput = Join-Path $PWD ('work\windows-native-recovery-' + [guid]::NewGuid().ToString('N'))
$harnessFolder = '.\work\windows-native-recovery-1792368590026'
& '.\.venvs\app\Scripts\python.exe' -B -u "$harnessFolder\windows_lifecycle_check.py" --config 'C:\Users\Jason\PDFRemediator\local-runtime.toml' --output $trialOutput
& '.\.venvs\app\Scripts\python.exe' -B -u "$harnessFolder\windows_reopen_check.py" $trialOutput
```

This establishes bounded synthetic Windows native/recovery evidence on the named
commit. It does not establish double-click/browser interaction, keyboard or
assistive-technology usability, broader installation/denied-update recovery,
private-document support, human semantic acceptance or the LMS accessibility checker results.
Verification remained `not-verified`; synthetic reviewer labels confer no actual
human accessibility acceptance. Originals and existing saved reviews were not
modified. No merge, release, tag or publication occurred. Continue with remaining
machine/UI acceptance gates only within their separately authorized scope.

## Reproducible review lifecycle and consolidated integration review

October 18, 2026. Branch `dev/reproducible-review-lifecycle`, based on `e39e89d`,
without merging. The owner requested continued unattended development and no
routine requests to click through ambiguous checks. No owner action was needed
for this work.

`scripts/qualify-review-lifecycle.py` moves the native review evidence into a
committed, reproducible command. From source and explicitly provisioned native
Linux tools, it generates an authored licensed reading and checks seven cases:
original native candidate; deliberately absent validator refusal; retry with the
correct runtime; accepted synthetic metadata application; saved-review service
reconstruction; a later saved edit preventing result attachment; queued retry
cancellation. Candidate paths retain all real gates/hash checks and pending
human-review requirements. Trial reviewer names are authored fixture labels,
not actual human acceptance. No browser, model service, OCR, private input or
network download is used.

The command refuses non-Linux execution, OCR/expanded repair policies, outputs
outside the checkout's ignored work tree, and existing output folders. Missing
native prerequisites record failed doctor/summary evidence and return failure;
they are never skipped. Cleanup errors also prevent a successful summary.
Nine new source-only contracts cover these scope/prerequisite/output boundaries
and are included explicitly in scripts/test-cloud.py. No native assets enter Git.

`docs/RELEASE-READINESS.md` now consolidates the complete development diff,
support statement, reproducible software/native commands and remaining actual
Windows/human acceptance gates. `origin/main` was fetched and read as
`37fbf10ba18a7a8f206100e35dc458a09b079168`; no merge or branch reset occurred.
The existing Windows 604/617 suites and owner observations remain historical
bounded evidence; current Linux counts do not replace a Windows rerun of the
later cloud patches. The consolidated review is a draft, not release approval.

Actual Linux commands/results:

- Baseline `.venv/bin/python scripts/test-cloud.py`: **635 passed in 31.38s**.
- Expanded `.venv/bin/python scripts/test-cloud.py`: **644 passed in 32.54s**.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml
  PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip
  .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py
  --basetemp work/lifecycle-driver-prepared --tb=short`: **657 passed in 32.16s**,
  no missing prerequisites skipped.
- Final driver contract check `.venv/bin/python -m pytest -q
  tests/test_review_lifecycle_trial.py --basetemp work/lifecycle-driver-contracts-final
  --tb=short`: **9 passed in 0.10s**.
- `.venv/bin/python scripts/qualify-review-lifecycle.py --config
  work/native-linux-reproduced-tools/runtime.toml --output work/review-lifecycle-final`:
  **all 7 bounded cases passed**, real native tools, originals unchanged,
  human verification false. Initial/retry PDF SHA-256 stayed
  `85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`;
  authored metadata result SHA-256 was
  `88cda1310c482dee1e0e5530e0133b1fd0a75d962bc875d1d76f4dca52e07f8b`.
  An earlier full execution under work/review-lifecycle-reproduced also passed.
- `.venv/bin/python scripts/qualify-native-linux.py --config
  work/native-linux-reproduced-tools/runtime.toml --output
  work/release-readiness-native --include-book`: **all 11 named bounded cases
  plus 2 negative fidelity controls passed their expected outcomes**.
  Both 200-page book routes and the default safety boundary were refreshed:
  default published no PDF with failed fidelity (16.0452s); explicit regrouping
  produced a needs-manual draft with preserved appearance (15.9308s); regrouping
  plus authored automatic descriptions produced a candidate (11.6555s), all
  200 pages compared. The candidate retained **1,234 pending human items**,
  including **1,224 regroup reviews**, and 106 passed validator rules/678,858
  passed checks/zero failed checks. No model inference was used.
  Book source SHA-256:
  `022cfed5756a119c357ab147358e16b40f8226dfcd134ad6cc12784e9d6387fd`;
  candidate SHA-256:
  `2d58fc9ca39133ec6d370a18052f0aa462c4dd922b53a0703bab8673d957bd1c`.
  Runtime implementation digest:
  `cacd58f15ece0395a99ab44577a86a9de79117368bcfb1763ec5d905c9c9a2cf`.
  Times are observations from this container, not a platform performance promise;
  memory was not newly sampled.
- Clean staged source export: `git write-tree`, `git archive <staged-tree>`, then
  extraction under ignored `work/source-only-export-wn2uj7iv/checkout` with no
  `.git`, historical corpus or native assets. Running the exported
  `scripts/test-cloud.py` with the installed pinned application/test Python and
  its checkout-specific PYTHONPATH passed **644 tests in 32.75s**. All synthetic
  fixture artifacts were generated inside that export. No private corpus or
  untracked original-checkout inputs were copied into it.
- Tracked-artifact audit and `git diff --check`: pass. The staged additions are
  source/tests/docs only; no PDF/archive/weight/log/session/config artifact is
  tracked.

The older HOME-DESKTOP-HANDOFF now begins with an explicit historical-checkpoint
notice and points to the consolidated current branch/review, preventing its old
clone branch and counts from being mistaken for the current build.

Generated PDFs, complete validator reports, source fonts, private session/review
state and full evidence remain under ignored work directories. The new summary
is automated evidence for named synthetic controls, not full native support,
Windows qualification, actual-user/AT acceptance or an the LMS checker score. AI/OCR remain
off. Actual-user/AT/the LMS accessibility checker testing stays deferred; no merge/release occurred.

## Applying accepted edits respects the latest saved review

October 18, 2026. Branch `dev/apply-review-revisions`, based on `f5aa9a5`, without
merging. Five deterministic regressions reproduced a review-authority gap:
Apply could queue while an existing human-reported problem remained blocked;
and later saved edits/problem reports, either while queued or before result
attachment, did not prevent the job from completing and switching the UI to a
result built from the older accepted sidecar. The old review was not overwritten,
but silently switching away could hide the newer work from the active view.

Apply now refuses an already-blocked review and checks its exact revision and
evidence before starting the worker. It checks again after processing, under the
application PDF lock together with importing the result. If the review changed,
the latest review stays in place and the job gives a clear message instead of a
new workspace ID. A coherent result already produced by the full pipeline stays
as a separate immutable bundle available through **Find existing results**.
No original, saved human edit or reported problem is copied over or erased.
Current source/sidecar hashes, checkpoint checks and all validation/preservation
gates remain required; automatic choices still cannot supply human verification.

The new tests use deterministic authored PDF/review fixtures and explicitly named
stub validators. They prove existing reported-problem refusal before export or
queueing; late edits/problem reports preventing any worker call after waiting;
and late changes preventing result attachment while the completed bundle remains
verified/discoverable. Saved state bytes, source-artifact hashes, protected human
values, blocked counts and not-verified status are asserted. Existing apply,
export tampering and automatic-mode tests retain all their assertions.

Actual Linux commands/results:

- Baseline `.venv/bin/python scripts/test-cloud.py`: **630 passed in 31.65s**.
- Pre-fix `.venv/bin/python -m pytest -q tests/test_web.py -k
  'existing_reported_problem or saved_review_after_waiting or later_human_changes'
  --basetemp work/apply-revisions-before-2 --tb=short`: **5 failed, 61 deselected
  in 1.00s**, confirming the gaps before the fix.
- Focused `.venv/bin/python -m pytest -q tests/test_web.py tests/test_autofix_web.py
  --basetemp work/apply-revisions-after --tb=short`: **90 passed in 6.51s**.
- Final `.venv/bin/python scripts/test-cloud.py`: **635 passed in 32.74s**.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml
  PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip
  .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py
  --basetemp work/apply-revisions-prepared --tb=short`: **648 passed in 33.49s**,
  no prerequisite skips.
- `.venv/bin/python work/apply-native-revisions/trial.py`: actual Linux native
  baseline/preparation plus normal accepted-metadata application passed validator,
  supplemental and fidelity gates, with checkpoint adoption and verified bundle.
  Normal result SHA-256:
  `d29b3147cd63048834bac83c5ef5c88140cc15550217a1b80545034146658e3d`.
  A second real native application also passed all gates; the trial inserted a
  saved synthetic human edit after the worker returned and before result
  attachment. The job refused the result switch, retained exact latest review
  bytes and original PDF hash, and kept the completed bundle verified and
  discoverable. Verification remained not-verified. This is one controlled
  timing case, not proof of every race/native platform. The scratch trial,
  generated PDFs, reports and review state remain under ignored
  `work/apply-native-revisions`; committed source tests reproduce the authority
  checks with explicitly stubbed validators. No browser/real-user trial occurred.
- `git diff --check`: pass.

This patch has not been installed or tested on Windows. Earlier owner observations
remain bounded to successful retry and reopening a saved review, not independent
verification of every saved field or broader accessibility acceptance. AI/OCR
remain off. No merge/release, external server exposure, private artifact transfer,
actual-user/AT or the LMS accessibility checker test is implied. No owner action is requested.

## Interrupted work, read-only retry boundaries and startup recovery

October 18, 2026. Branch `dev/interrupted-work-recovery`, based on `87157de`;
no merge. Automated continuation reproduced seven failing cases before changes:
queued cancellation still invoked its operation; an already-cancelled isolated
request reached child creation; retry of a failed read-only `check` queued a
modifying `fix`; and bind/import/session-write/browser-opening startup failures
did not close created service resources.

The queue now marks an already-cancelled job cancelled without invoking its
operation, and isolated processing checks cancellation before creating a worker.
Active operations still use the existing cooperative cancellation and bounded
termination behavior; this is not an immediate-cancellation guarantee for every
native call. The original active-job cancellation regression now waits for its
callback to start before cancelling, so it deterministically tests active rather
than queued cancellation; all its previous assertions remain.

Retry now requires a failed `fix` report. A failed read-only assessment cannot
silently become a modifying operation; the owner must explicitly choose an input
for processing. Ordinary failed fix retries retain their current revision/source
binding and separate-bundle behavior. All normal validation, preservation,
refusal and human-versus-automatic authority boundaries remain unchanged.

Service startup now closes the server (if constructed) and Application resources
when binding, initial import, private-session publication or browser opening
raises. Application cleanup still runs even if server cleanup raises. Existing
successful startup, private-link logging and session compatibility checks remain.
Fault-injection tests exercise call/cleanup behavior, not actual Windows denied
filesystem permissions or every native resource-failure condition.

All new tests use authored synthetic state and local stubs/loopback HTTP; no
private fixtures, real model calls, OCR or external network are required. The
headless real launcher smoke was repeated using `.venv/bin/python
work/session-smoke/trial.py`: fresh service start, authenticated matching reopen,
changed-settings refusal and orderly shutdown passed; exactly one child started,
no browser opened and zero PDFs processed. That local scratch script and private
session/log remain ignored. This is service evidence, not a new native PDF/UA
qualification trial. The committed tests reproduce the new cases from source.

Actual Linux commands/results:

- Baseline `.venv/bin/python scripts/test-cloud.py`: **623 passed in 30.56s**.
- Pre-fix reproduction `.venv/bin/python -m pytest -q tests/test_web.py
  tests/test_serve_logging.py -k 'queued_work_never or pre_cancelled or
  failed_read_only or startup_failure_closes' --basetemp work/interrupted-before
  --tb=short`: **7 failed, 60 deselected**, demonstrating the gaps.
- Focused `.venv/bin/python -m pytest -q tests/test_web.py tests/test_launcher.py
  tests/test_serve_logging.py --basetemp work/interrupted-after --tb=short`:
  **91 passed in 2.91s**.
- Final `.venv/bin/python scripts/test-cloud.py`: **630 passed in 31.83s**.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml
  PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip
  .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py
  --basetemp work/interrupted-prepared --tb=short`: **643 passed in 31.28s**, no
  missing native/font prerequisites skipped. This prepared regression result
  is distinct from full native qualification and the earlier Windows suite.
- `git diff --check`: pass.

These changes have not been installed/tested on Windows. The previous bounded
owner retry/reopen observations remain unchanged, and no additional owner action
is requested. AI/OCR remain off; actual-user, AT and the LMS accessibility checker acceptance stay
deferred. No generated artifacts, private review states, PDFs, secrets or native
tools are added to Git.

## Windows retry/reopen observations and automatic session compatibility checks

October 18, 2026. Continuation branch `dev/session-restart-checks`, based on
`6337592`, without merging. The owner confirmed that the installed Python package
contained both the launcher-config and retry fixes. A previously running command
lacked `--config`; the UI sometimes exposed Retry while its service returned
“This action was not found.” An older running service was a supported diagnosis,
not a proven count of separate servers: the two reported Windows Python entries
could be a virtual-environment parent/child pair. Repeated source downloads were
not an appropriate remedy for a running process.

After stopping/restarting with explicit configuration, the owner reported that
retry reached **Ready for review**, later confirmed “It's working now,” and then
reported that a saved successful review opened after Stop application and a
double-click restart. Record these only as owner-reported retry success and saved
review reopen. No new report/hash was supplied, and individual saved values,
all statuses, every keyboard control, semantics or AT behavior were not reverified.
No metadata reversion defect was established. The owner requested that automated
work continue without further ambiguous manual testing tasks.

The private session record now stores startup implementation/settings digests.
Before reopening a live authenticated loopback service, the launcher compares
those against the selected local build/configuration. Legacy session records,
changed code/native implementation inputs or changed settings receive an explicit
Stop application/restart message instead of silently reopening that service.
It does not kill an existing process, erase its session file, start a duplicate,
or rewrite PDFs/reviews. Matching live services still reopen. These digests are
local compatibility diagnostics, not publisher authentication or PDF approvals.
Session URLs/tokens and configuration contents remain out of logs and Git.

New source-only contracts exercise real authenticated loopback probes for legacy,
code and configuration mismatch; matching reopen; startup identity recording;
and service reconstruction with a pending or named-approved synthetic title plus
a saved reported problem. They assert exact saved state, original/output hashes,
fresh session token, protected human values, pending/approved distinctions,
retained revision checks, and no human verification granted by restarting.
The existing startup logging regression was retained; its service double now
includes the configuration field exposed by the real Application.

Actual Linux verification:

- Baseline `.venv/bin/python scripts/test-cloud.py`: **616 passed in 31.25s**.
- Final `.venv/bin/python scripts/test-cloud.py`: **623 passed in 31.23s**.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml
  PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip
  .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py
  --basetemp work/session-prepared-2 --tb=short`: **636 passed in 30.88s**,
  no missing prerequisites skipped. These remain Linux results; earlier Windows
  full-suite counts are unchanged.
- `git diff --check`: pass.

An initial expanded run identified the startup logging double's missing config
field (622/635 passes plus one failure in the respective scopes). The double
was corrected to match the real Application; all logging assertions were kept.

The bounded headless launcher smoke command `.venv/bin/python
work/session-smoke/trial.py` used the real child service with the configured Linux
runtime and browser opening disabled: fresh start passed, matching reopen passed,
changed settings were refused, exactly one child was started, and authenticated
shutdown completed. It processed zero PDFs and left no running test service.
The scratch script/session/log stay under ignored `work/session-smoke`; the
committed regressions construct their own deterministic synthetic state and
require no private fixtures or native tool downloads.

This new compatibility patch has not run on Windows. The earlier owner result
belongs to the prior installed source. AI/OCR remain off; no merge/release,
loopback exposure, full native qualification, actual-user/AT or the LMS accessibility checker
acceptance is implied. Further Windows work should be one explicitly defined
observation at a time; there is no current request for another owner action.

## Failed-attempt retry and desktop launcher configuration

October 18, 2026. Development branch `dev/retry-and-launch-config`, based on
`ee702a8`; no merge. The owner encountered the exact baseline-source assessment
blocker after starting the double-click launcher. Inspection confirmed that
`launch_review.pyw` delegates to `launcher.launch`, which previously spawned
`serve` without `--config`. The desktop's private configuration points to a
validator outside the default tools folder. This establishes a configuration
mismatch, not independent inspection of the failing Windows validator logs.

The launcher now discovers and validates `local-runtime.toml` from the installed
project root and forwards its absolute path when starting a child. It also
supports an explicit Python API config path. Invalid settings fail instead of
silently falling back. Existing private sessions are still reopened rather than
replaced; stop the old service once before testing newly installed startup code.
The review data directory stays `output/review-app`. Neither wrapper needs manual
editing. Configuration, global Java, review files and originals are not rewritten.

Failed reviews now expose **Retry processing** with an explanation of its scope.
It preserves document options, uses the current service's native paths/resource
settings, and processes the same hash-bound source into a new run and workspace.
The previous immutable bundle and review remain intact. Saved human edits and
approvals remain in their previous review and are explicitly not copied into a
retry. No AI call or new human approval is supplied. Current revision and evidence
are checked before queuing and again when work starts; the pipeline checks the
expected source hash and runs all gates. Missing/changed originals or changed
bundle evidence refuse retry and require choosing the input again. Signed and
other unsupported inputs retain the existing pipeline refusal behavior.

The title editor also explains that it changes internal PDF metadata, not the
filename or printed heading. Owner clarification and the recording establish
that a metadata update worked; no title-reversion defect was demonstrated.
Restart persistence and full keyboard acceptance are still pending. The recording
also shows review-check interaction, but no broad semantic approval is inferred.

Actual Linux verification:

- Baseline `.venv/bin/python scripts/test-cloud.py`: **604 passed in 29.68s**.
- Expanded `.venv/bin/python scripts/test-cloud.py`: **616 passed in 32.23s**.
- Focused `.venv/bin/python -m pytest -q tests/test_launcher.py tests/test_web.py
  --basetemp work/retry-focused-3 --tb=short`: **75 passed in 2.47s**.
- Prepared `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml
  PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip
  .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py
  --basetemp work/retry-prepared --tb=short`: **629 passed in 32.60s**, no skips.
- `node --check src/pdf_remediator/web_assets/app.js` and `git diff --check`: pass.
- `.venv/bin/python work/retry-native/trial.py`: a local, ignored synthetic trial
  generated a reading, reproduced the baseline blocker with a missing validator,
  then used the real isolated worker and configured Linux native tools for retry.
  All three gates passed, bundle verified, old review bytes and manifest hash
  stayed unchanged, and new workspace had zero human approvals/not-verified.
  Output SHA-256 remained
  `85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
  This scratch trial and generated evidence remain local under ignored
  `work/retry-native`; reproducible source contracts are in the committed tests.

The source contracts explicitly label stubbed validators; they are separate from
the actual native trial. No browser automation or new Windows execution of this
patch is claimed. Earlier Windows 604/617 results apply to the earlier build;
616/629 are new Linux results. The owner need not keep clicking through diagnostics:
development/testing continues in cloud, and installation plus one bounded Windows
startup/retry check remain for a later owner checkpoint. AI/OCR remain off;
AT, actual-user acceptance and the LMS accessibility checker remain deferred. No full native
qualification, merge, release, server exposure or private-artifact Git transfer.

## Home desktop real-package updater check/apply complete

October 18, 2026. The owner ran the checked source updater on a new disposable
installation copy under ignored `work/updater-test-*`, not on the working app.
The test copied package/project metadata, appended an authored comment only in
the disposable `__init__.py` to create a real pre-update difference, and created
a synthetic local configuration sentinel. `git archive HEAD` produced the
selected source ZIP. Dry-run reported **checked-not-applied**; application then
reported **applied**, **32 files**, unchanged dependencies and restart required
for that disposable copy. The final sentinel hash comparison passed.

Observed archive SHA-256:
`39e92ecd438e2419a8fb198be38cbbd182400b4682106a9cfb639f36c14e91a1`.
Applied package digest:
`bf2775b394eed97ce0005756676e68b2f6a2d55fee3dd6021fa59dce3496b8f7`,
matching the Linux real-package trial. Previous disposable package digest:
`f9cca88ca7bd23e1a880e45f7e3ffc31f723eb7679b8ff130292014fb8875819`.
The updater verified the complete staged/installed file set and hashes, retained
the complete prior package at its reported local backup path, and the owner
reported **Isolated updater test passed; local configuration preserved.**
No reinstall, replacement or restart of the working source installation was
performed by this test. The restart flag pertains to the disposable target.

This closes the actual Windows real-package inspection/application happy path.
The 41 updater contract tests already ran within the 604/617 passing Windows
scopes, including simulated failure/rollback cases. Deliberately denied native
Windows replacement/recovery and broader installer robustness are not newly
claimed from the happy-path run. Publisher authentication remains false: the
hashes establish copy integrity of owner-selected local Git source, not a
signature or supply-chain attestation. Human PDF acceptance remains not-assessed.

Next is the local review-interface/keyboard and saved-edit workflow on authored
synthetic input with AI/OCR off. No screen-reader/the LMS checker trial or upload, private
artifact Git transfer, merge or release. This checkpoint only updates docs;
`git diff --check` passed and no code tests were repeated.

## Home desktop prepared suite and local bundle verification

October 18, 2026. The owner reported **617 passed in 79.76s** for the full declared
prepared regression scope on home Windows/Python 3.11.9 x64. This followed the
actual 604-test source-only pass, pinned native provisioning and first real
one-page candidate/the desktop PDF viewer observation. The approved AMSFonts ZIP was downloaded
to the home Downloads directory; its independently reported SHA-256 exactly
matches `aaab3930b952128b7ed65260144493eb3d88cb063b50da1f90272e23c7e08ba2`.
No missing native/font prerequisites were skipped or substituted.

Actual reported suite invocation, from the desktop checkout:

```powershell
$env:PDF_REMEDIATOR_NATIVE_CONFIG = (Resolve-Path ".\local-runtime.toml").Path
$env:PDF_REMEDIATOR_AMSFONTS_ARCHIVE = "$env:USERPROFILE\Downloads\amsfonts.zip"
& ".\.venvs\app\Scripts\python.exe" -m pytest -q tests `
  eval/test_validate.py eval/test_metrics.py `
  --basetemp ".\work\desktop-prepared-$([guid]::NewGuid().ToString('N'))" `
  --tb=short
```

The owner also supplied the actual local message **Bundle verified; PDF hash
matches report.** The guarded command calculated the actual PDF SHA-256,
compared it with the report and required `pipeline.verify_bundle` success before
opening the PDF. This adds reported local bundle-verification evidence for the
same uploaded/independently hashed candidate
`85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
The full raw Windows bundle remains local and was not independently uploaded.

The prepared suite covers its declared native/font identity/contract scope; it
is not a claim of full Windows native qualification, 200-page Windows book
execution, native model/OCR qualification, AT/the LMS checker acceptance or a verified
accessibility ledger. Those boundaries remain unchanged. Next is a real-package
updater dry-run/apply on an isolated disposable Windows copy, then the remaining
interface and separately scoped acceptance work. Documentation-only update;
`git diff --check` passed; no code tests rerun in cloud, no artifacts/review states
committed, no merge. AI/OCR remain off.

## Home desktop reader clipboard observation complete

October 18, 2026. After identifying home a desktop PDF editor **2026.002.22031, 64-bit**,
the owner pasted the candidate's text from the desktop PDF viewer. Both previously joined word
boundaries now have spaces, both authored paragraph anchors are present, and the
selected footer label is present. The paste contains the footer label only,
not its complete displayed wording; do not infer either complete footer copying
or loss from that selection. The uploaded exact candidate independently contains
the complete footer, and the owner previously confirmed its visual appearance.
This completes the bounded home native/visual/paragraph-clipboard observation
for candidate SHA-256
`85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.

No full-page reading-order, AT, the LMS checker or verification-ledger approval is inferred.
Next is the prepared Windows regression scope with the pinned licensed AMS ZIP,
then remaining updater/interface tasks. This checkpoint changes documentation
only; whitespace checks pass and no code tests were rerun. AI/OCR stay off,
no raw PDF/screenshot/clipboard extract or review state is committed, no merge.

## Home desktop checkpoint: source tests and first real native candidate

October 18, 2026. Continuing `dev/windows-zip-fixture` after `0190ffb`, the owner
reran the source-only runner on the home Windows machine and reported **604
passed in 68.41s**. This closes the earlier Windows ZIP-fixture regression for
that scope. It includes the updater's 41 contract tests; actual real-package
Windows updater application/recovery and the full prepared suite remain open.

The desktop uses Python **3.11.9 x64** in `.venvs/app`; dependency installation,
`pip check` and application **0.3.0** checks succeeded. Global `java` resolved to
Java 8, so runtime configuration explicitly selects existing **Temurin 25.0.3+9
64-bit** without changing global Java. ODL **2.5.13** is in its separate venv.
The downloaded Greenfield installer SHA-256 matched the pinned
`b512bf24945503a33fc10738ecffc1f2dccaaf8593a448e94ee9ac86a9559a59`.
Publisher signature was not checked. Installation reported completion followed
by a cleanup/reference exception; the installed veraPDF **1.30.3** launcher
subsequently started and real validation succeeded, which is the bounded actual
result rather than a claim that every installer function was flawless.

The untracked local runtime TOML selects actual desktop Java/ODL/validator paths,
OCR off and default conservative preservation options. Doctor reported ready,
with tagging and validation true, OCR false and zero document network calls.
The repeated configuration-write attempt safely refused to overwrite the first
successful configuration. No optional OCR installation is needed for this scope.

The owner generated a new original synthetic reading with `register_fonts` and
`simple` from `eval/build_corpus.py`, then ran:

```powershell
& ".\.venvs\app\Scripts\python.exe" -m pdf_remediator fix `
  ".\work\desktop-reading-ad494634350e44238eb4c23461a65bb2\reading-source.pdf" `
  --config ".\local-runtime.toml" `
  -o ".\output\desktop-native-19718ecc89b84713a7f03c6e47d02dfd"
```

The real run reported **candidate**, with validator, supplemental and fidelity
all **pass** in the owner's report summary. Bundle folder:
`output/desktop-native-19718ecc89b84713a7f03c6e47d02dfd/reading-source-ed1351295101-39dbaca69b`.
Reported candidate SHA-256:
`85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`.
The owner uploaded the candidate for inspection. Independent cloud SHA-256 of
those uploaded **43,026 bytes** exactly matches the report and the previously
qualified Linux reading. PDFium confirms one page with the full authored text
and footer. Content-stream inspection finds exactly one explicit trailing
space at each of the two corrected line endings and a structure tree.
The original uploaded file remains outside Git and unchanged.

The owner confirmed the candidate looks fine in the desktop PDF viewer. The supplied About
screenshot identifies **a desktop PDF editor, Continuous Release 2026.002.22031,
64-bit**. This is the actual home reader version; do not backfill it onto the
earlier other-computer pilot. Actual home the desktop PDF viewer clipboard output has not yet
been supplied; PDFium extraction and the prior other-machine clipboard result
are not a new home clipboard observation. Full raw Windows evidence/bundle and
a separate `verify_bundle` success message were not uploaded, so do not claim
independent verification of that entire Windows bundle. No application ledger
approval was created from this conversation.

This is one synthetic Windows native/visual case with observed Java 25 behavior,
not full Windows native qualification, general Java compatibility, AT acceptance
or the LMS checker testing. AI/OCR stay off and the loopback boundary is unchanged. Source
code did not change at this checkpoint; documentation/whitespace checks pass,
with no redundant code test run. Next: finish the actual reader clipboard check,
then supply the pinned AMS archive for the prepared suite and proceed through
separately bounded Windows updater/interface tasks. No merge or release.

## Home desktop source-only run: Windows ZIP fixture correction

October 18, 2026. Branch `dev/windows-zip-fixture` continues from `5d91586`.
The owner cloned the correct source branch into the previously empty home
`C:\Users\Jason\PDFRemediator` directory, verified Python **3.11.9 x64**, created
`.venvs/app`, installed `.[test]`, passed `pip check`, and observed CLI **0.3.0**.
The first actual Windows source-only run reported **602 passed, 1 failed in
64.90s**, not 603 passes. Failure: the backslash archive-path refusal fixture
in `tests/test_source_update.py`. No native Windows qualification is claimed.

Python's `ZipInfo` constructor normalizes Windows backslashes before the fixture
writer serializes them. The intended adversarial archive therefore contained a
safe forward-slash path; the updater correctly did not refuse that safe input.
The fixture now explicitly preserves the requested `ZipInfo.filename` when
writing. Every unsafe-path parameter also asserts the deserialized raw
`orig_filename` contains that exact path before requiring refusal. The production
updater, unsafe-path rejection and all original preservation assertions are
unchanged. Nothing is skipped or marked as an expected failure.

A new regression exercises the real stdlib separator normalization by selecting
the Windows separator within a temporary monkeypatch context on Linux. It proves
constructor normalization occurs, the fixture still serializes the raw unsafe
spelling, the updater refuses it and local sentinels remain unchanged. This test
failed before the fixture correction and passed afterward. It is a focused
simulation, not a replacement for the pending actual Windows rerun.

Actual checks:

- `.venv/bin/python -m pytest -q tests/test_source_update.py::test_backslash_fixture_survives_windows_zip_filename_normalization --basetemp work/windows-zip-reproduce --tb=short`:
  **1 failed**, reproducing the fixture defect at the raw-path assertion.
- `.venv/bin/python -m pytest -q tests/test_source_update.py --basetemp work/windows-zip-corrected --tb=short`:
  **41 passed in 0.43s**.
- `.venv/bin/python scripts/test-cloud.py`: **604 passed in 32.60s**, no skips.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py --basetemp work/windows-zip-prepared --tb=short`:
  **617 passed in 32.92s**. Native/font prerequisites were explicit; no skips.
- `git diff --check`: pass.

Next actual desktop step: fetch this development branch without overwriting
local edits and rerun `scripts/test-cloud.py` using the existing Windows app
venv. Record the actual result; do not infer a Windows pass from Linux. No new
application code, dependency change or native PDF trial is introduced here.
AI/OCR stay off; saved local data and immutable bundles stay outside Git. No
merge or public listener. The other desktop/native/AT/the LMS checker tasks remain pending.

## Home desktop transfer checkpoint

October 17, 2026. The owner requested a handoff to the larger home computer.
[docs/HOME-DESKTOP-HANDOFF.md](docs/HOME-DESKTOP-HANDOFF.md) is the receiving
agent's starting document, with exact branch/tested revision, preservation of
existing local work, fresh-checkout/runtime setup, actual Windows prerequisites,
source-only/prepared commands, ordered remaining tasks and a copyable resume
prompt. Continue `dev/regression-release-readiness`; tested development revision
`e5c7fd25780b7852eb812a9423068230ffb15e3d` is followed only by this documentation
checkpoint. The home filesystem/runtime has not been inspected from this cloud
session; paths and previous evidence must not be assumed transferable.

No application/test source changed. Existing 603 source-only, 616 prepared and
fresh bounded 200-page Linux results remain the recorded evidence, not fresh
Windows claims. Documentation link and whitespace checks passed; code tests
were not repeated for this documentation-only change. No artifacts or review
states transferred through Git, no native provisioning/install performed on the
home computer, no new pilot authorization, merge or release.

## Latest development checkpoint: broader regressions, fresh book trial and current checklist

October 17, 2026. Branch `dev/regression-release-readiness` continues from
`4e1d7bf`; no merge. The owner authorized working through independent tasks with
minimal updates. No application/PDF processor source changed in this checkpoint;
there is no new Windows installation or retest request.

### Broader deterministic regression coverage

`tests/test_preservation.py` adds fourteen cases beyond the previous scope:
three wrapped lines with both boundaries preserved; identical MCID numbers on
two independent pages; a supported first page followed by an unchanged unsupported
page; leading whitespace, numeric endings, changed font size, same-line text,
upward line movement, rotated text, an additional text-show in the same BT,
explicit font Encoding, multiple valid CMap bfchar blocks, a heading owner and
MCR dictionary children. Positive cases retain automatic page/MCID records and
pending human status; negative cases retain exact text-show operands. All new
cases compare real PDFium fidelity and preserve source/engine input hashes.
Fonts/notices and fixture bytes are generated locally; no PDF or local corpus
is introduced to Git. Existing assertions and release/refusal gates remain.

Actual commands/results:

- Baseline `.venv/bin/python scripts/test-cloud.py`: **589 passed in 30.73s**,
  no skips.
- `.venv/bin/python -m pytest -q tests/test_preservation.py --basetemp work/readiness-layout-first --tb=short`:
  **57 passed in 1.06s**.
- Expanded `.venv/bin/python scripts/test-cloud.py`: **603 passed in 30.98s**,
  no skips.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py --basetemp work/readiness-prepared-tests --tb=short`:
  **616 passed in 30.63s**, no skips or missing-prerequisite substitutions.
- Created `work/readiness-source-stage` from `git archive HEAD` at `4e1d7bf`,
  copied only the changed test source into it, and asserted absence of `.git`,
  `eval/corpus`, `eval/runs` and `tools`. Then ran
  `.venv/bin/python work/readiness-source-stage/scripts/test-cloud.py`:
  **603 passed in 31.37s**, no skips. The staged runner binds staged `src/` and generates
  fresh fixtures; its Python dependencies come from the existing external venv.

### Fresh actual native Linux trial, including the full synthetic book

`.venv/bin/python scripts/qualify-native-linux.py --config work/native-linux-reproduced-tools/runtime.toml --output work/readiness-native-book --include-book`:
**all bounded contracts passed**, eleven named cases plus two independent negative
fidelity controls. Runtime remains Python 3.12.14, Java 21.0.12.1, real ODL 2.5.13
and veraPDF 1.30.3. AI/OCR remain off. No threshold was relaxed and no unsupported
native dependency was skipped. The existing one-page candidate still records two
automatic source separators. Chapter semantic blockers, missing descriptions,
phantom/incomplete tags, forms and changed-settings refusals remain visible.

The source book SHA-256 is
`022cfed5756a119c357ab147358e16b40f8226dfcd134ad6cc12784e9d6387fd`.
Default processing compared all 200 pages, failed fidelity and published no PDF
in **15.9405 s**. Explicit regrouping compared every page and produced a labeled
review draft in **15.8314 s**, with descriptions unresolved. The separate
regrouped route with authored automatic descriptions adopted its exact preparation
checkpoint and produced a candidate in **11.7961 s**, output **746,364 bytes**,
SHA-256 `2d58fc9ca39133ec6d370a18052f0aa462c4dd922b53a0703bab8673d957bd1c`.
It passed **106 strict rules / 678,858 checks**, zero failures, supplemental gates
and all 200-page fidelity. All **1,234 human reviews**, including **1,224 regrouping
reviews**, remain pending. Authored captions are automatic fixture values, not
model inference or named human approval.

The largest native subprocess-tree RSS samples recorded in route provenance were
**561,881,088 bytes** (default) and **626,475,008 bytes** (regrouped routes), sampled
at the existing 0.05-second interval. The final route includes reused preparation
provenance. These are not whole-Python-pipeline peak measurements, a hard OS
allocation guarantee, repeated benchmarks or Windows performance promises.
Implementation digest for this unchanged application/tool configuration:
`dae55441edf57508e37ca4ab5bd428224e5b1ad1c80aca5bbc6e740822615727`.
Full generated evidence stays under ignored `work/readiness-native-book`.

### Documentation and remaining independent work

[STATUS.md](docs/STATUS.md) is the consolidated completed/open checklist and support
matrix. [ACCEPTANCE-TESTS.md](docs/ACCEPTANCE-TESTS.md) prepares exact-artifact binding,
usability/keyboard tasks, AT scenarios, seeded negatives, isolated updater
qualification and the LMS checker disposition. It is not authority to execute broader human
trials. Roadmap/native notes and the handoff's current unfinished/next sections
now distinguish present evidence from obsolete private-fixture and pending-pilot
statements. Historical dated checkpoints retain their actual results.

`git diff --check`, current README/docs local links and `.venv/bin/python -m pip
check` pass. Historical excluded-artifact links in the handoff were not asserted
to exist. Source-only repeatability and the latest 200-page run are completed
for the declared scope; general support, representative real-reading evaluation,
Windows updater qualification, full keyboard/usability/AT and actual the LMS checker testing
remain open as listed. No new owner action is needed now. No public listener,
AI/OCR activation, private-document upload, ledger approval, merge or release.
Only tests/docs are committed; raw artifacts, review states and tools stay local.

## Latest development checkpoint: checked local source updates

October 17, 2026. Branch `dev/checked-local-updates` continues from `6559f64`;
no merge. The owner asked to keep developing without additional hands-on work.
This change addresses the real failed Windows wildcard-copy update described
below. **Application/PDF processing source is unchanged** from the successful
bounded Windows retest. The owner does not need another update for this tooling.

### Offline updater and safety boundary

`scripts/update-local-source.py` uses Python 3.11+ standard library only, without
network, model/OCR requests, native PDF tools or application imports. It inspects
an explicitly selected trusted source ZIP and an existing editable checkout.
Default mode is read-only and returns `checked-not-applied`; only `--apply`
replaces `src/pdf_remediator`. All project metadata must match exactly; dependency
or packaging changes require the existing installation workflow. Hashes check
copy/input integrity, not publisher authenticity. Trusted archive provenance is
an owner prerequisite, not a claim inferred from the archive itself.

Before replacement it refuses missing/incomplete inputs, path traversal and
Windows unsafe/device/stream names, duplicate/case-colliding paths, symlinks or
special entries, unsupported package artifacts, size overruns, syntax errors,
metadata differences, linked checkout paths, changed archives or installed code,
and concurrent updater locks. Python 3.11 Windows reparse attributes are covered
without assuming Python 3.12's junction API. Legitimate repository dotfiles are
permitted after a real-archive check caught an overly restrictive first rule.

It stages and hashes every package file, then moves the complete old package to
a unique ignored `work/code-backup-*` path, replaces it and verifies the complete
installed file set/hashes. Previous bytecode stays in the backup. Configurations,
PDFs, evidence, virtual environments and review states are outside replacement.
Catchable replacement errors trigger rollback and full previous-package hash
verification. Failed rollback explicitly keeps the app closed and identifies
installed/backup/displaced recovery locations; it does not assume a backup still
occupies its original path after a failed restore-verification step. Success is
never printed on a refused update. The exclusive lock coordinates updater
processes only: the owner must stop the app/editors before applying. Forced
termination, power loss and hostile concurrent filesystem changes are outside
the recovery guarantee. See [checked local updates](docs/LOCAL-UPDATES.md).

### Actual verification

- Before edits, `.venv/bin/python scripts/test-cloud.py`: **549 passed in 31.15s**,
  no skips.
- `.venv/bin/python -m pytest -q tests/test_source_update.py --basetemp work/updater-recovery-locations --tb=short`:
  **40 passed in 0.29s**. All fixtures are deterministic authored ZIPs and isolated
  synthetic checkout trees. They test unchanged local sentinels, complete package
  hashes/backups, syntax-only checking with no application import, archive
  refusal, lock preservation, input changes, interrupted/failed directory moves,
  corruption, rollback success/failure and accurate recovery diagnostics.
- Final `.venv/bin/python scripts/test-cloud.py`: **589 passed in 30.14s**, no skips.
  The exact runner now includes `tests/test_source_update.py`.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py --basetemp work/updater-prepared-recovery-final --tb=short`:
  **602 passed in 30.17s**, no skips. Real native/font identity prerequisites remain explicit,
  with no dependency skips. Test socket permission was loopback only.
- `git archive --format=zip --prefix=project/ --output=work/updater-real-source.zip HEAD`
  at parent `6559f64`, then staged a copied real source checkout under
  `work/updater-real-target` with an authored pre-update code difference and
  configuration sentinel. Both
  `.venv/bin/python scripts/update-local-source.py --archive work/updater-real-source.zip --target work/updater-real-target`
  and the same command with `--apply` succeeded: **32 package files** checked,
  complete package digest
  `bf2775b394eed97ce0005756676e68b2f6a2d55fee3dd6021fa59dce3496b8f7`,
  full previous package retained separately. The first real archive attempt
  refused legitimate dotfiles before mutation; corrected and covered by fixtures.
  This was an isolated Linux copy, not the owner's Windows installation.
- `.venv/bin/python -m py_compile scripts/update-local-source.py`,
  `.venv/bin/python -m pip check`, `git diff --check`: pass/no broken requirements.

No new native PDF trial is claimed: application source was unchanged, and the
previous bounded native/the desktop PDF viewer results remain identified above/below. This new
updater has Linux automated and isolated-copy evidence; native Windows execution
of it remains untested. Do not conflate the successful earlier manual Windows
update with qualification of this tool. No further user action is needed now.
AI/OCR remain off, no server exposed, no merge. Only source/tests/docs enter Git;
ZIPs, staging directories, code backups, generated outputs and local state remain
ignored under `work/`. AT and the LMS accessibility checker acceptance remain deferred.

## Latest owner checkpoint: fresh Windows application retest complete

October 17, 2026. On `dev/source-line-separators`, following application commit
`5eea3fe`, the owner downloaded the updated source ZIP, reported successful
installation with line-separator file verification, started a new local test
workspace, uploaded the original reading again and processed/downloaded a fresh
result through the normal application. The owner confirmed that the pasted text
came from this new download opened in the desktop PDF viewer. Both previously joined
word boundaries were correctly spaced. The owner confirmed the footer remained
visible and explicitly confirmed that the remaining text, spacing and layout
looked the same as the original. This completes the limited Windows application
visual/clipboard retest as reported by the owner, beyond the earlier standalone
exact-pair experiment.

Installation history matters: the first pasted update commands continued after
an absent ZIP error and attempted a copy from an empty source path. That copy
reported access denied. A guarded block then moved the affected package folder
aside and restored the pre-update code backup; the owner's transcript confirmed
restoration. Only afterward did a guarded update extract the correct ZIP,
validate required files, back up the restored code, copy the package and compare
the installed line-separator file hash with the extracted source. The owner
reported that update completed. Keep backups and failed-update material local;
none is repository evidence or a reason to weaken permissions.

Limits: the exact fresh Windows candidate hash, full local evidence bundle,
actual the desktop PDF viewer version and final downloaded filename were not independently
captured in this chat. Do not bind this observation to the Linux candidate hash,
claim a full Windows automated/native suite pass, or populate application review
approvals from conversation alone. Record exact artifact/reader identifiers if
formal acceptance is pursued. No screen-reader, comprehensive reading-order or
the LMS accessibility checker acceptance has occurred. AI/OCR remained off in the instructed
workflow; no new model service or public listener was introduced.

This checkpoint changes documentation only. `git diff --check` passed; automated
code tests were not rerun because application/test source is unchanged from the
recorded 549 source-only and 562 prepared passes. No merge. Next engineering
work may extend synthetic coverage for other text layouts; broader acceptance
still needs separately authorized scope and actual testing.

## Latest checkpoint: source line separators and completed bounded the desktop PDF viewer retest

October 17, 2026. Branch `dev/source-line-separators` continues from `78ec8fa`;
no merge. The owner explicitly asked to continue after the bounded the desktop PDF viewer test.
The original development branch remains available; Windows does not auto-update.

**Owner observation:** the exact-pair probe ran on Windows and reported its gates
passed. The owner pasted the experimental PDF's text with both word boundaries
correctly spaced and the SYNTHETIC footer present, identified the subsequent
line-broken paste as `reading-source.pdf`, and explicitly confirmed the original
and experiment looked the same in the desktop PDF viewer. This completes that limited
visual/clipboard retest only. The actual the desktop PDF viewer version is still unrecorded.
It does not approve all reading order, AT behavior, the LMS checker results or any automatic
choice. No ledger approval or verified status was fabricated.

### Production integration and limits

`preservation.py` now calls `line_separators.py` only after its original complete
painting/resource/structure alignment and MCID pruning succeed. The preservation
version is 1.2. Source-extracted line boundaries may receive an explicit encoded
space only when all of these bounded conditions hold:

- Single terminal ASCII `Tj` in each independently reset, horizontal text object,
  matching the precise `BT/Tm/Tf/TL/BDC/Tj/EMC/T*/ET` shape; identity page transform,
  no forms, unsupported text state, quote operators or TJ arrays on that page.
- Embedded-source resource equivalence remains enforced by the existing proof;
  simple TrueType font with the narrow explicit ASCII CMap, no custom Encoding,
  inherited mapping or ranges; same font/size on consecutive lines.
- Adjacent MCIDs in the existing logical order of the exact same indirect plain
  paragraph; no replacement text on that owner or ancestors; same x position,
  positive line separation at most twice the font size, alphabetic boundary,
  no existing whitespace, hyphenation, punctuation or non-ASCII ambiguity.
- The unchanged source's PDFium extraction contains each literal line uniquely
  and contains their exact newline boundary once. No model infers missing words.

Unsupported/ambiguous shapes receive no inserted space. Automatic records contain
page/MCIDs, explicit automatic origin and `human_verified=false`; ordinary text
and reading-order reviews remain mandatory. No engine roles are reassigned by
this rule. The existing real strict validator, supplemental checks, exact
all-page fidelity, input/output hash binding, immutable bundle, refusal and
revision/cache gates still run normally. Source changes participate in the
existing whole-package implementation digest, invalidating stale caches.

Tests generate authored two-line fixtures with the bundled licensed ReportLab
Vera fonts and copied license notice. No local corpus is required. Eighteen new
cases cover the positive rule, sixteen unchanged ambiguous cases (including
ancestor replacement text), and byte-for-byte repeat generation. The existing
assertions remain; only the expected preservation version advances to 1.2.

### Actual verification

- Before edits, `.venv/bin/python scripts/test-cloud.py`: **531 passed in 29.60s**,
  no skips. First targeted integration exposed incorrect parser input and a
  PDFium page context-manager assumption; both were fixed before successful runs.
- `.venv/bin/python -m pytest -q tests/test_preservation.py --basetemp work/line-separators-deterministic --tb=short`:
  **43 passed in 0.54s**, including unchanged original refusal assertions.
- Final `.venv/bin/python scripts/test-cloud.py`: **549 passed in 29.85s**, no skips.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py --basetemp work/line-separators-prepared-deterministic --tb=short`:
  **562 passed in 29.64s**, no skips. Native/font prerequisites are explicit, not skipped or
  replaced. Loopback permission was used for transport tests only.
- `.venv/bin/python scripts/qualify-native-linux.py --config work/native-linux-reproduced-tools/runtime.toml --output work/native-line-separators-final`:
  **all bounded contracts pass**, nine named cases plus two negative fidelity
  controls. Real ODL 2.5.13 and veraPDF 1.30.3; AI/OCR off. Simple and existing
  tagged controls remain candidates; phantom/incomplete tags fail, semantic
  blockers retain review-only drafts, forms refuse, settings changes refuse.
  Authored automatic figure values remain distinct from human verification.
  The script now asserts exactly two automatic line records for the simple PDF.
  Its candidate SHA-256 is
  `85e820b1db32d63a2823490c02435d2ff4851ab1f0bcd0e240f44744c00624df`,
  with real UA-1, supplemental and every-page fidelity passes; human review false.
  The 200-page optional book trial was not rerun for this change. Earlier book
  evidence remains historical, not new qualification of this implementation.
- `.venv/bin/python -m pip check`: no broken requirements; `git diff --check`: pass.

Next: update the local Windows source deliberately, process the original reading
in a fresh output/data directory through the normal app (not the exact-pair
probe), and repeat the the desktop PDF viewer clipboard/appearance check on that new candidate.
The already passing experiment does not prove the production Windows route.
The source-name download fix is inherited. See [Windows pilot](docs/WINDOWS-PILOT.md).
AI/OCR stay off; no public listener, merge, full native qualification, AT
acceptance or the LMS checker test. All uploads, PDFs, tools, local configuration, caches,
generated assets/evidence and review states stay outside Git.

## Latest checkpoint: Windows pilot filenames and bounded copy experiment

October 17, 2026. Branch `dev/windows-pilot-copy-boundaries` continues from
`b9a6bfc` on `dev/native-linux-synthetic`; no merge. The owner asked for continued
useful work while asleep. The owner authorized a limited Windows visual/usability
pilot in the desktop PDF viewer without a screen reader. That subset has started; broader
assistive-technology acceptance and the LMS accessibility checker testing remain deferred.

The owner installed the application locally (Python 3.11.9 x64, Java 21.0.12.1,
ODL 2.5.13, veraPDF 1.30.3), opened the local page and processed the authored
one-page reading. The source and candidate looked the same to the owner.
Clipboard text from the desktop PDF viewer joined two word boundaries in the candidate while
source clipboard text retained line separation. Windows/the desktop PDF viewer exact versions
and full human acceptance are not recorded. Do not mark text/reading-order
reviews complete. Cloud commands cannot update the owner's Windows installation.

Both uploaded PDFs were inspected without changing them or committing them.
Source SHA-256: `ed1351295101b5dc72c5fa0f5075fb6074ac3d2f4868a2ee4feac3403d3f4a3b`.
Candidate SHA-256: `41efe341fa7bf14ef0850bec7a24e727d213de376d4797c53e976a3a691cd683`.
PDFium extraction agrees, including the footer, but candidate paragraph tags group
line strings without explicit trailing spaces. This fits the reported the desktop PDF viewer
behavior and exposes a limitation of existing extraction-based fidelity checks;
it does not prove a general repair. No preservation assertion was relaxed.

The application download name was hard-coded in the UI. It now uses the server's
safe Content-Disposition name, retaining the sanitized source stem with
`-candidate.pdf` or `-review-draft.pdf`. For this pilot the future name is
`reading-source-candidate.pdf`. Downloaded PDF bytes and all release/revision
checks are unchanged; no filename implies completed human verification.

`scripts/probe-pilot-copy.py` is a separate exact-hash synthetic experiment, not a
product Auto-fix. It adds two explicit line-end spaces only for the known authored
strings, requires unchanged font mapping and the expected text positioning,
refuses changed inputs/existing outputs/OCR enabled, and exports only after real
strict validation, supplemental checks and every-page fidelity agree on the
output hash. No review states are created or approved. The first probe attempt
refused because the production font parser requires a different CMap range; the
probe was corrected to compare the pinned source CMap and explicit space entry.
The production parser and its refusal behavior were not changed.

Actual commands/results:

- `.venv/bin/python scripts/test-cloud.py`: **531 passed in 30.09s**, no skips
  (previous baseline 528 plus three new filename cases). Loopback test permission
  was used, with no public listener or boundary changes.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip .venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py --basetemp work/windows-pilot-prepared-tests --tb=short`:
  **544 passed in 32.32s**, no skips. This prepared scope needs the declared real
  native tools and licensed archive; they are not bundled in a source checkout.
- `.venv/bin/python scripts/probe-pilot-copy.py --source /workspace/attachments/6d5592fe-21ca-49a5-986b-3833392b3127/reading-source.pdf --candidate /workspace/attachments/d2ec219a-e5af-4381-91c6-f8f7368e4f7e/accessibility-candidate.pdf --config work/native-linux-reproduced-tools/runtime.toml --output work/windows-copy-probe-2/reading-source-copy-test.pdf`:
  real veraPDF **1.30.3 UA-1 pass**, supplemental **pass**, source fidelity **pass**.
  Export SHA-256: `1ec9f6cd06cfdff099fa27596b144200e5846e4402eda34995ceebce941fd36c`.
  Report explicitly says `experimental-awaiting-the desktop PDF viewer-retest`, human false,
  production fix unconfirmed. Evidence stays ignored under `work/`.
- Two subprocess refusal checks with the same script: modified source rejected
  without output; existing output rejected and sentinel bytes preserved.
- `.venv/bin/python -m py_compile scripts/probe-pilot-copy.py`,
  `node --check src/pdf_remediator/web_assets/app.js`, `git diff --check`: pass.

Next human-dependent action: follow [Windows pilot continuation](docs/WINDOWS-PILOT.md)
to generate the separate experiment locally, compare appearance and clipboard
text in the desktop PDF viewer, and record the actual reader version. No the desktop PDF viewer fix is claimed
before that retest. No generic whitespace insertion should be added based solely
on this one synthetic example. AI/OCR stay off. No full native qualification,
AT acceptance, the LMS checker score or verified status is claimed. Generated PDFs, runtime
configuration, evidence, uploads and review states remain outside Git.

## Latest checkpoint: real native Linux trials and synthetic Type1 fixtures

October 16, 2026. Branch `dev/native-linux-synthetic` continues from `75ac526`;
no merge. The owner supplied the two public archives after host-policy denials.
The archive-transfer blocker is resolved without bypassing network policy.

**Current result:** the prepared complete application/evaluator scope passes
**541 tests with no skips** from a clean staged source tree. Real native trials
also pass all their declared bounded safety contracts, including a 200-page
candidate with real strict UA-1 validation and every-page fidelity. This is not
general native qualification or human acceptance. All 1,234 human-review items
on the book candidate remain pending. No Phase 3 trial or Canvas upload started.

### Inputs, provenance and reproducible setup

- Uploaded veraPDF 1.30.3 archive SHA-256:
  `b512bf24945503a33fc10738ecffc1f2dccaaf8593a448e94ee9ac86a9559a59`,
  matching the historical handoff. Installed CLI JAR:
  `19f6edd5c92841a38d9b3b018a555b7ba173b13e4e0d29edecc232e5ba6c1d70`.
  Observed CLI version: **1.30.3**. Publisher signature was not verified.
- Uploaded AMSFonts 3.04 archive SHA-256:
  `aaab3930b952128b7ed65260144493eb3d88cb063b50da1f90272e23c7e08ba2`.
  CMSY10 PFB: `62ee8cef552017551cd3e026a483e700730103eceaad959c87b7730017f59cff`;
  CMEX10 PFB: `791b31aa1db8608d0144b3a40fc0fe53383a60f6b00d0e8fd9f06ac4a11df8cb`.
  Both programs retain SIL OFL 1.1; the archive README describes its other LPPL
  material. The OFL notice is hash-pinned and copied beside generated fixtures.
- Runtime remains Linux/Python **3.12.14**, OpenJDK **21.0.12.1**, and actual
  ODL **2.5.13** JAR `48ed84b5bf28e6ba82b8f37771fa5604b1f864bf529543910c8825a68965210c`.
  Archives, distributions and local config stay under ignored `work/`.
- `scripts/setup-native-linux.py` validates reviewed archive hashes, refuses a
  reused output directory/unsafe installer paths, installs CLI/docs locally,
  and writes explicit runtime paths with OCR off. It neither downloads files
  nor changes system PATH/Java. Its tested invocation used `--validator-archive`
  and `--amsfonts-archive` pointing at the uploaded ZIPs, `--java-home
  /usr/lib/jvm/java-21-openjdk-amd64`, `--odl-jar
  .venvs/odl/lib/python3.12/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar`,
  and `--output work/native-linux-reproduced-tools`: completed successfully.
  [Native reproduction guide](docs/NATIVE-LINUX.md) gives the full commands.

### Synthetic font fixture replacement and tests

`eval/build_type1_control.py` embeds the unchanged full licensed CMSY10/CMEX10
programs in an original two-symbol PDF. It unwraps PFB transport without font
substitution, preserves built-in Encoding, and deliberately omits only the maps
under test. The archive/program/OFL hashes are checked before fixture output.
`tests/test_fonts.py` now requires `PDF_REMEDIATOR_AMSFONTS_ARCHIVE` explicitly;
there is no published/private book input. Missing or changed archive fails, not
skips. Existing assertions remain; new tests check deterministic bytes, exact
embedded program bytes via the independent fontTools PFB reader, and refusal of
a changed archive before any PDF/assets are emitted. No font binary enters Git.
The source-only cloud runner still excludes this explicitly provisioned module.

Actual commands/results:

- Initial default-sandbox cloud baseline: **468 passed, 60 socket setup errors in
  16.32s**; reran using supported execution permission for private loopback
  fixtures: `.venv/bin/python scripts/test-cloud.py` **528 passed in 30.18s**,
  no skips. No server was exposed or rebound publicly.
- `PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip .venv/bin/python -m pytest -q tests/test_fonts.py --basetemp work/fonts-final-corrected --tb=short`:
  **12 passed in 1.05s**. The new raw-program assertion initially used a pikepdf
  dictionary key without its slash; corrected the assertion, not production code.
- Complete application scope before adding the last two fixture-integrity tests,
  with explicit native config and reviewed archive: **499 passed in 28.17s**.
- Fresh `git archive HEAD` source staging under `work/native-source-staging-*`,
  copying only changed/new source. Asserted no local corpus, historical runs, or
  native distributions were present in the staged tree. Supplied the installed
  native config and pinned archive externally as declared dependencies, and
  bound `PYTHONPATH` to staged `src/`. Ran `.venv/bin/python -m pytest -q -p
  no:cacheprovider --basetemp <staged-root>/work/prepared-tests-final tests
  eval/test_validate.py eval/test_metrics.py --tb=short`:
  **541 passed in 30.96s**, no skips. This includes 501 application cases and 40
  evaluator cases. An initial staging harness omitted the temporary parent
  directory (95 passes/444 setup errors); creating that parent fixed the harness
  without relaxing product atomic-write safeguards. This prepared run is not a
  claim that native dependencies or licensed fonts are included in a bare clone.
- `.venv/bin/python -m pip check`: no broken requirements. `git diff --check`: pass.

### Real native qualification scope and limits

`.venv/bin/python scripts/qualify-native-linux.py --config work/native-linux-reproduced-tools/runtime.toml --output work/native-final-trial --include-book`
completed **all bounded contracts**. The script uses real Java/ODL/veraPDF/PDFium
without test stubs. Seven initial pipeline cases plus automatic-figure,
changed-settings, default-book and regrouped-book cases are recorded (11 summary
cases), alongside independent deliberate-loss and wrong-CMap fidelity controls.
Every expected refusal stays a refusal; none is counted as candidacy.

- The tagged and untagged one-page controls become candidates with strict,
  supplemental and fidelity gates passing. Direct real validation of the
  original tagged control passed 106 rules / 427 checks with zero failures.
- Phantom/incomplete tags fail strict/supplemental checks; no PDF is published.
  Missing figure alternatives and the four-page chapter remain review-only with
  unresolved semantics. Forms refuse before native validation/publication.
- Two authored fixture captions can be applied through exact automatic authority,
  with all real gates rerun. They remain automatic, with deterministic-fixture
  provenance, no model inference and no named human approval. Changing the
  preparation settings is correctly refused before application. An exploratory
  attempt using an identical validator installed at a different config path was
  likewise refused; retaining the original preparation settings succeeds.
- The 200-page book under default settings fails render fidelity and publishes
  no PDF; every page was compared and digital tokens were retained. Explicit
  opt-in tag regrouping restores all-page fidelity but still leaves figure
  semantics unresolved. This is a separately selected synthetic test route,
  not a silent configuration change or a widened default preservation policy.
- With the two descriptions supplied from authored book ground truth (page 40
  plot comparison, page 110 archive classification), the regrouped book becomes
  a candidate: **106 rules / 678,858 checks**, zero strict failures, supplemental
  pass, and all **200 pages** pass fidelity. Exact candidate SHA-256:
  `2d58fc9ca39133ec6d370a18052f0aa462c4dd922b53a0703bab8673d957bd1c`.
  All **1,234** human-review items remain pending, including **1,224** regrouping
  records. `human_reviewed` is false; no external document API call occurs.

Only the named synthetic cases have this native evidence. General documents,
other Java/platform combinations, OCR, arbitrary font restoration, model quality,
and semantic accessibility are not qualified. Originals and prior bundles stay
unchanged. All source/output hashes, gate bindings and immutable manifests are
checked. No production validation, fidelity, refusal, revision or human-authority
rules were changed to obtain these results.

### Next owner-dependent milestone

The [proposed Phase 3 pilot](docs/PHASE3-PILOT.md) is prepared for approval, not
started: begin with the one-page reading and two-figure control; include the
200-page book only if the owner chooses its larger human-review scope. A local
synthetic review packet is prepared under ignored `work/synthetic-review-packet`
and `work/PDFRemediator-synthetic-review.zip` (SHA-256
`2aac54a39af4d190dddd9156d03f634d702f53578796a06bb30c1953fb0cef16`).
It contains only source/candidate PDFs, exact-hash/native summaries, font notice,
and proposed pilot, with no credentials, live token, native distribution, or
verification ledger. It has not been delivered through a file-transfer workflow:
the projectless output mount is unavailable/read-only in this cloud executor.
Do not expose a server or upload it elsewhere to work around that limitation.

AGENTS.md explicitly keeps Phase 3 actual-user, assistive-technology acceptance,
and the LMS accessibility checker testing deferred until owner authorization. The next step needs
that authorization and an actual human tester; any Canvas upload needs its own
explicit approval. No actual-user outcomes, screen-reader results, the LMS checker scores,
or verified records have been invented. Real AI/OCR remain off. Git continues
to contain source/docs only; generated artifacts and review states remain local.

## Earlier checkpoint: source-only adapters and native preflight

October 16, 2026. Branch `dev/source-only-adapters` continues from `b0c8a19`;
no merge. The source-only runner now passes **528 tests with no skips** on
Linux/Python 3.12.14, including clean source staging. The full application suite
is **not fully passing**: with the actual JAR selected it has **494 passes and
4 missing-Type1-fixture failures**. Real native UA-1 qualification remains blocked.

Changes: adapter tests regenerate the original control, phantom/incomplete tags,
wrong CMap, four-page structured chapter, and mixed/scan controls. The tagged
scan is a synthetic image-only Figure tree, not historical ODL evidence. The
strict-parser test now uses explicitly synthetic XML; it does not claim a native
validator pass. All prior assertions remain. The actual pinned-JAR identity test
moved unchanged into `tests/test_native_tools.py`, which accepts an explicit
runtime TOML via `PDF_REMEDIATOR_NATIVE_CONFIG`; missing tools fail, never skip.
The font no-op test now uses the generated tagged control. Four font-repair
cases still require the excluded book's real embedded Type1 programs and fail.

The evaluator initially skipped four corpus contracts. `eval/test_metrics.py`
now regenerates their original synthetic fixtures (including the 200-page book)
in a disposable checkout-local directory instead of using `skipUnless`.
All assertions remain. The cloud runner adds the adapter, web, launcher,
applied-AI provenance, rejected-transport, and full evaluator-metrics modules.
It explicitly excludes only `tests/test_native_tools.py` and `tests/test_fonts.py`;
those modules are not counted as passing. No production code or Git allowlist
changed. Every selected test runs; missing dependencies are not hidden by skips.

Commands/results in this continuation:

- Initial `.venv/bin/python -m pytest -q --basetemp work/full-inventory --tb=line`:
  **469 passed, 29 failed in 28.26s** (missing fixtures/native prerequisites).
- `.venv/bin/python -m pytest -q tests/test_adapters.py --basetemp work/adapters-first --tb=short`:
  **39 passed in 1.13s**.
- Initial expanded cloud run: **524 passed, 4 skipped in 28.54s**. This exposed
  the evaluator's corpus skip; it was corrected rather than accepted as success.
- `.venv/bin/python -m pytest -q eval/test_metrics.py --basetemp work/metrics-generated --tb=short`:
  **32 passed in 1.48s**, no skips, after synthetic regeneration.
- `.venv/bin/python scripts/test-cloud.py` after that correction:
  **528 passed in 31.37s**, no skips (19 modules).
- Fresh `git archive HEAD` staging under `work/adapters-source-only-*`, copying
  only the changed/new test, evaluator, runner and probe source files, with no
  `eval/corpus`, `eval/runs`, or native distributions. Ran staged
  `scripts/test-cloud.py` using the existing `.venv/bin/python`:
  **528 passed in 30.96s**, no skips; imports bound to staged `src/`.
- `PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-preflight/runtime.toml .venv/bin/python -m pytest -q --basetemp work/full-after-adapters --tb=line`:
  **494 passed, 4 failed in 29.98s**; all failures are the missing
  `eval/external/thinkpython2.pdf` Type1 fixture, not ignored or successful cases.
- `.venv/bin/python -m pytest -q tests/test_fonts.py --basetemp work/fonts-inventory --tb=line`:
  **5 passed, 4 failed in 0.13s**, same missing fixture.
- `.venv/bin/python -m pip check` and isolated ODL `pip check`: no broken requirements.
  `git diff --check`: passed.

[Native reproduction instructions](docs/NATIVE-LINUX.md) document the installed
OpenJDK **21.0.12.1**, isolated `.venvs/odl` installation using
`python3 -m venv .venvs/odl` and
`.venvs/odl/bin/python -m pip install opendataloader-pdf==2.5.13`, and explicit
local TOML paths. The real ODL **2.5.13** JAR SHA-256 is
`48ed84b5bf28e6ba82b8f37771fa5604b1f864bf529543910c8825a68965210c`.
`PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-preflight/runtime.toml .venv/bin/python -m pytest -q tests/test_native_tools.py --basetemp work/native-identity --tb=short`
passed **1 test in 0.07s** against that actual artifact.

`.venv/bin/python scripts/probe-native-linux.py --config work/native-linux-preflight/runtime.toml --output work/native-linux-reproduced`
completed the actual one-page synthetic ODL run (exit 0), painting preservation,
catalog normalization, all-page text/render fidelity, and supplemental checks.
An earlier direct probe recorded the same results. Reusing the output directory
raised FileExistsError before any overwrite, as intended. The script generates
local evidence and explicitly records `qualified: false`, `candidate_published:
false`, `human_verified: false`, and strict validation not run. **This is a native
preflight, not end-to-end qualification or a release candidate.**

Remaining concrete blocker: the cloud outbound proxy returned **403 Forbidden**
for the pinned official veraPDF archive at `software.verapdf.org` and both CTAN
routes (`mirrors.ctan.org` and direct `ctan.math.illinois.edu`). No policy bypass
was attempted. To continue, allow the two direct hosts `software.verapdf.org`
and `ctan.math.illinois.edu` through the supported environment configuration, or
provide the official archives. Then inspect licenses/hashes, provision the full
veraPDF 1.30.3 distribution, regenerate the Type1 tests from genuine licensed
CMSY10/CMEX10 font programs with synthetic text (not a private/book PDF), and run
real strict-UA-1 end-to-end controls with preservation evidence. The final font
fixture replacement has not yet been implemented or claimed as passing.

Real AI/OCR remain off; protocol/OCR behaviors in source contracts use named
stubs. Loopback tests used supported execution permission and were never exposed
or rebound publicly. PDFs, native distributions, output JSON/logs, review states,
font assets and local runtime config remain ignored. Actual-user,
assistive-technology acceptance, and the LMS accessibility checker testing remain deferred.

## What works

- Deterministic processing with OpenDataLoader 2.5.13, standalone veraPDF 1.30.3 using the strict PDF/UA-1 profile, independent structure/content checks, and preservation comparisons. Originals remain unchanged and completed result bundles are immutable.
- The browser workspace supports upload, options, progress, cancellation, original/result previews, title/language and figure edits, reviewed heading/table controls, grouped occurrence review, downloads, and review-record export. The interface binds to loopback and uses a private session token with Host/Origin/file-route checks.
- **Auto-fix this document** handles eligible, already-proved mechanical repair records and creates a separate result with fresh automated checks. On the recorded 244-page book it handles 623 records, leaving 7 actionable checks. All 630 raw required human-review records remain pending; it does not make 623 new PDF changes or fabricate human reviews.
- Optional, explicitly authorized local AI can draft and automatically apply title/figure guesses, or supply drafts for manual acceptance. Requests are restricted to loopback, AI is off by default, and models must already be installed. Human edits, accepted values, blockers, cancellation, and revision checks take precedence. Automatic values use `auto-accepted`, not a named human approval.
- Bounded opt-in list/link regrouping and exact-source character-mapping repair preserve the tested books. The mapping route has a separate declared reference policy; it is not general font or mathematical repair.
- Batch isolation, checkpoint reuse with exact fingerprints, source/prepared/output/value/context binding, runtime limits, and a separate human-verification ledger are implemented.

Recorded internal evidence: [Phase 2 results](eval/PHASE2-RESULTS.md), [Auto-fix results](eval/AUTO-FIX-RESULTS.md), [Phase 1 results](eval/PHASE1-RESULTS.md), and [original engine evaluation](eval/RESULTS.md). The final 0.3 Windows run recorded **494 passing tests in 79.49 seconds**, four native Auto-fix cases, and wheel verification. This is historical evidence from the prepared computer, not evidence that a new Linux environment passes. Raw evidence links in those reports may point to deliberately excluded local files.

The frozen 0.3 package implementation digest was `a7354943ad8605635c4301be9141052bdce3b13fc5ce04ce5a46a75840a93df5`. Configuration/tool paths affect runtime fingerprints; do not expect Windows checkpoints to transfer to a differently configured cloud machine.

## What is unfinished

Use [the current checklist](docs/STATUS.md) for the maintained remaining-work list.
The source-only and prepared regression scopes now regenerate their synthetic
fixtures; obsolete references to a private 494-test corpus are historical, not
current prerequisites. Native tools and the pinned licensed AMS archive remain
external and explicitly required for the prepared scope.

1. Complete actual Windows qualification of the checked updater/fresh install,
   broader review workflow and keyboard access. The one-page owner the desktop PDF viewer
   visual/clipboard pilot is complete, not comprehensive acceptance.
2. Expand supported-case/refusal coverage and evaluation on further permitted
   representative material when available. Retain bounded document/font/OCR
   limits; do not turn unsupported cases into claimed support.
3. Complete separately authorized assistive-technology and actual the LMS accessibility checker
   testing, exact artifact/version records and genuine required human reviews.
4. Prepare/review final release integration, documentation and appropriate final
   checks. No merge/release or AI/OCR activation is authorized by development.

A `candidate` means its declared automated gates pass. `verified` additionally
requires the exact artifact, completed genuine human reviews and an actual
qualifying the LMS checker result. No automatic disposition is named human approval.

## Repository contents and privacy boundary

Keep source, tests, guides, safe evaluation scripts, configuration examples, and required bundled mapping/license notices. Use a **private** repository. Before the first push, inspect both tracked files and commit contents; an ignore file does not remove already tracked data.

Exclude passwords, API keys, environment secrets, Git credentials, private session URLs/tokens, local configuration with sensitive paths, user PDFs, extracted document text, image crops, AI request/response caches, workspaces, review/decision exports, verification ledgers, logs, run bundles, downloaded tools/models, virtual environments, build products, and archives. Treat JSON/HTML/PNG evidence as potentially containing document content too. Keep all PDFs out of the initial source backup unless a particular generated/public fixture is separately reviewed and explicitly included. A private GitHub repository is still cloud storage.

Typical local-only directories include `.venvs/`, `output/`, `work/`, `tmp/`, `build/`, evaluation corpus/run/spike/evidence artifacts, native distributions under `tools/`, and any sibling synced `sources/` tree. Keep `tools/` source scripts distinct from its downloaded distributions. Never edit, rename, move, or delete synced reference material. Back up excluded private evidence separately only through an explicitly chosen private-data process.

Commit the mapping data together with its [notice](src/pdf_remediator/data/TEX-MAPPING-NOTICE.txt) and [LPPL license](src/pdf_remediator/data/LPPL-1.3c.txt). The published *Think Python* input has separate attribution/license requirements and is not an unrestricted redistributable fixture. Do not add model weights or third-party native distributions without reviewing their terms.

## Run on the prepared Windows computer

Run commands from the repository/application root. These commands use a project-local environment and do not rely on the global Python PATH.

```powershell
$appPython = ".\.venvs\app\Scripts\python.exe"
& $appPython -m pdf_remediator --version
& $appPython -m pdf_remediator doctor
& $appPython -m pdf_remediator launch
```

Alternatively double-click `Start PDF Remediator.cmd`. **Stop application** stops its hidden helper; closing the tab leaves the helper running. The default local workspace is `output/review-app`. Do not commit its contents or the private bootstrap URL.

For a foreground service and explicit machine-specific configuration:

```powershell
& $appPython -m pdf_remediator serve --config .\local-runtime.toml --data-dir .\output\review-app --no-open
& $appPython -m pdf_remediator check .\input\reading.pdf -o .\output\checks --config .\local-runtime.toml
& $appPython -m pdf_remediator fix .\input\reading.pdf -o .\output\readings --config .\local-runtime.toml --title "Actual document title" --lang en-US
```

Create `local-runtime.toml` from [remediator.example.toml](remediator.example.toml) when needed. It must point to the actual local Java, ODL JAR, validator, and optional OCR/Tesseract installations. Relative TOML paths resolve against the configuration file. `doctor` reports startup/version availability; it is not an end-to-end processing test. Processing exit codes are 0 for automated candidacy, 2 for manual work, 1 for failure, and 130 for cancellation.

For a new trusted Windows Python 3.11 installation, recreate only the application environment with:

```powershell
py -3.11 -m venv .venvs\app
& .\.venvs\app\Scripts\python.exe -m pip install -e ".[test]"
```

Provision the independent native tools and engine/OCR environments separately. The setup launcher does not provide a complete installer. Follow [README.md](README.md) for all CLI routes and [START-HERE.md](START-HERE.md) for the browser workflow.

## Test and reproduce evidence

On the prepared Windows computer, with its existing fixture/evidence files:

```powershell
New-Item -ItemType Directory -Force .\output\tests | Out-Null
& .\.venvs\app\Scripts\python.exe -m pytest -q --basetemp .\output\tests\handoff-next
```

Choose a fresh disposable temporary directory, separate from retained evidence and original inputs. Some tests bind real loopback sockets. Model/provider or validator stubs are explicitly labeled in integration tests; a stubbed test pass is not a native-model/veraPDF processing claim.

The original six-module fixture-independent contract scope was defined explicitly in [scripts/test-cloud.py](scripts/test-cloud.py): `tests/test_review.py`, `tests/test_workspace.py`, `tests/test_validation_delta.py`, `tests/test_preservation.py`, `tests/test_serve_logging.py`, and `eval/test_validate.py`. These construct their own test inputs or use in-memory records. On the prepared computer, run it with `& .\.venvs\app\Scripts\python.exe scripts/test-cloud.py`. Run the complete suite after restoring its documented safe fixture prerequisites; do not silently skip missing-fixture failures and report 494 passes.

That exact six-module scope passed **188 tests in 10.15 seconds** from a source-only staging checkout on Windows/Python 3.11.9, with the staged package import verified and no external PDFs, historical fixtures, native tools, or models. It uses a fresh UUID temporary directory under ignored `work/`. An initial sandbox temporary-directory failure was resolved by changing this runner location, without relaxing product atomic-write safeguards.

The cloud onboarding subsequently installed the pinned dependencies and passed all **188 contract tests on Linux/Python 3.12.14**, including after a repeat installation. It verified CLI version 0.3.0, `pip check`, clean source at the initial pushed commit, and GitHub read access. Python 3.11 was unavailable in that environment; 3.12.14 satisfies the declared Python >=3.11 requirement. This proves the bounded source-development workflow, not native PDF processing or the complete 494-test suite. The onboarding report was inspected before publishing the environment.

### Expanded source-only pipeline regression scope (October 16, 2026)

Development branch `dev/synthetic-pipeline-regressions` starts at fetched
`origin/main` commit `762b087cbb9acd106898611f76a7cefa81b50107`.
The initial checkout was `b2c7fbf`; its baseline passed 188 tests in 2.63s.
Fetching through the execution tool's supported network permission succeeded
following an unreachable-proxy error in the default execution context. No
credentials were stored or network boundaries changed.

`tests/test_pipeline.py` now generates its control at runtime using
`eval/build_corpus.py` (`register_fonts` and `tag_control`), replacing all three
local corpus copies. This retains the original synthetic text, three MCIDs,
H1/P/P roles, embedded bundled Vera fonts, parent tree, fixed metadata, and
PDF/UA declaration. The font license is copied into disposable test artifacts.
A declaration is not a validator result. A new regression checks independent
generations are byte-identical and real content linkage, coverage, and font
embedding pass. Existing test assertions and application code are unchanged.
Missing generator packages, fonts, or required PDF libraries fail explicitly;
there are no dependency-based skips or system-font substitutions.

The test extra now pins ReportLab 5.0.1 and charset-normalizer 3.5.2, matching
the evaluator lock. Refresh existing environments with
`.venv/bin/python -m pip install -e '.[test]'`; fresh clones use
`bash scripts/setup-cloud.sh`. The cloud runner now selects seven modules,
including the full pipeline module (56 existing cases plus one new case).
Actual Linux/Python 3.12.14 commands and results in this task:

- `.venv/bin/python scripts/test-cloud.py` before changes on latest main:
  **188 passed in 2.35s**.
- `.venv/bin/python -m pip install reportlab==5.0.1`: installed ReportLab
  5.0.1 and charset-normalizer 3.5.2; `.venv/bin/python -m pip check`:
  **No broken requirements found**.
- `.venv/bin/python -m pytest -q tests/test_pipeline.py --basetemp work/pipeline-first`:
  **57 passed in 1.74s**.
- `.venv/bin/python scripts/test-cloud.py` after expansion:
  **245 passed in 4.19s**, no skips.
- Source-only staging proof: `git archive HEAD | tar -x -C work/source-only-pipeline`
  into a newly created empty directory, then copied only the changed
  `tests/test_pipeline.py`, `scripts/test-cloud.py`, and `pyproject.toml` there.
  `.venv/bin/python work/source-only-pipeline/scripts/test-cloud.py`:
  **245 passed in 4.89s**, no skips. The runner bound imports to staged `src/`;
  this reused installed Python dependencies but supplied no local corpus,
  historical outputs, native tools, models, or review states.

Pipeline tests retain the explicitly labeled strict-validator stub; real PDF
inspection, all-page rendering/fidelity, atomic publication, tamper refusal,
cancellation, source/checkpoint/approval binding, and unsupported-document
refusals run unchanged. The existing review/workspace scope retains automatic
versus human authority and revision contracts. This is **not** native ODL,
veraPDF, OCR, full-suite, or accessibility acceptance qualification. Those native
prerequisites were not provisioned or silently skipped. AI and OCR stayed off;
no review server was exposed. Actual-user, assistive-technology acceptance, and
the LMS accessibility checker tests remain deferred. Generated PDFs, licenses, and bundles stay
under ignored `work/`; only source/dependency declarations and this handoff enter
Git. Continue migrating remaining fixture-dependent modules separately, and
qualify native Linux tools in a distinct authorized synthetic trial.

### Cache/checkpoint continuation (October 16, 2026)

Branch `dev/synthetic-checkpoint-regressions` continues from `ba02a0c` without
merging either development branch. The connected execution machine remains the
published Linux cloud workspace, not the owner's laptop filesystem. Existing
Python 3.12.14 dependencies were available; no private computer files were needed.
Baseline `.venv/bin/python scripts/test-cloud.py`: **245 passed in 4.65s**.

Cache-provenance tests now copy the regenerated synthetic tagged control instead
of `eval/corpus/tagged-control.pdf`. Modules importing `input_pdf` explicitly
register its dependent `tagged_control` fixture as well (review checkpoint, web,
launcher, Auto-fix web, automatic decisions, and applied-AI provenance). The
cloud runner adds the complete cache-provenance and review-checkpoint modules.
All assertions and application behavior remain unchanged.

Commands/results:

- `.venv/bin/python -m pytest -q tests/test_cache_provenance.py tests/test_review_checkpoint.py --basetemp work/checkpoint-next`:
  **34 passed in 3.50s**.
- `.venv/bin/python scripts/test-cloud.py`: **279 passed in 8.62s**, no skips.
- Fresh source-only staging: created `work/source-only-checkpoint`, extracted
  `git archive HEAD` there, copied the changed two test modules and runner, then
  ran `.venv/bin/python work/source-only-checkpoint/scripts/test-cloud.py`:
  **279 passed in 7.53s**, no skips. Installed Python dependencies were reused;
  no corpus, historical run, or native tool files were copied.
- Compatibility probe:
  `.venv/bin/python -m pytest -q tests/test_web.py tests/test_launcher.py tests/test_autofix_web.py tests/test_auto_decisions.py tests/test_applied_ai_provenance.py --basetemp work/fixture-imports-permitted --tb=line`:
  **84 passed, 32 setup errors in 5.28s**. These 32 errors are unresolved missing
  `eval/runs/phase0-20261015/opendataloader/structured_chapter/normalized/structured-chapter_tagged.pdf`
  dependencies, not successful or skipped tests. A first default-sandbox probe
  returned **56 passed, 60 errors in 6.50s**, including loopback socket permission
  errors. The rerun used supported execution permission for existing private
  loopback tests; no public listener or rebinding was introduced. No real model
  provider or OCR process was enabled (provider behavior in these tests is stubbed).

The 279-test scope preserves fresh validator/fidelity reassessment, immutable
checkpoint anchors, stale-source/approval refusal, and human authority. It still
uses explicitly labeled validator stubs and does not qualify native ODL,
veraPDF, OCR, or the full suite. AI/OCR remain off and actual-user,
assistive-technology, and the LMS accessibility checker testing remain deferred. The next fixture
migration should reconstruct the historical structured-chapter test requirements
from safe synthetic source, preserving figure/text/decision coverage rather than
substituting a simpler control that weakens those tests. Keep generated PDFs,
review states, and evidence outside Git.

### Synthetic figure-occurrence continuation (October 16, 2026)

Branch `dev/synthetic-figure-regressions` continues from `c92f9c7`; no merge.
The cloud checkout and pinned Python 3.12.14 dependencies remained available.
Baseline `.venv/bin/python scripts/test-cloud.py`: **279 passed in 6.77s**.

The 32 missing-chapter setup errors described above are resolved for
`tests/test_auto_decisions.py` and `tests/test_autofix_web.py`. Both now copy a
fresh runtime-generated occurrence control from the shared `generated_chapter`
fixture. `eval/build_corpus.py:tagged_figure_control` reuses the original synthetic
chapter's orange-circle/blue-square asset and garden/archive caption meanings.
It deliberately creates two distinct Figure elements with absent Alt values,
five linked MCIDs, embedded bundled Vera fonts, a parent tree, and a title.
The drawing is reused at two sizes on one page. ReportLab invariant output and
pikepdf deterministic IDs produce byte-identical independent generations, checked
by the fixture. Font notices and generated artifacts remain in ignored `work/`.

This is a **bounded replacement control**, not a recreation or qualification of
historical ODL output. The larger chapter's lists, links, complex tables, columns,
and four-page layout are not represented here; these two modules test automatic
decision authority, attribution, protected human choices, partial failures, and
release gates. Their existing assertions are unchanged. Two additional fixture
contracts prove a single image XObject is painted twice, both Figure decisions
are distinct and pending, linkage/coverage/font embedding pass, and real PDFium
MCID-based crops obtain separate garden/archive captions without cross-context
leakage. Thus the figure assertions cannot pass with a text-only control.

Actual commands/results:

- `.venv/bin/python -m pytest -q tests/test_auto_decisions.py tests/test_autofix_web.py --basetemp work/figures-first --tb=short`:
  **55 passed in 4.21s**.
- `.venv/bin/python scripts/test-cloud.py` after adding both complete modules and
  the two fixture contracts: **336 passed in 11.75s**, no skips (11 modules).
- `.venv/bin/python -m pytest -q tests/test_web.py tests/test_launcher.py tests/test_autofix_web.py tests/test_auto_decisions.py tests/test_applied_ai_provenance.py --basetemp work/figure-compatibility --tb=short`:
  **116 passed in 6.67s**, no skips. This reruns the exact five-module scope that
  previously returned 84 passes and 32 missing-fixture errors. Supported execution
  permission allowed the existing tests' private loopback sockets; no public
  listener, forwarding, or security-boundary change was introduced.
- Source-only staging: extracted `git archive HEAD` into a new empty
  `work/figures-source-only`, copied only the changed generator, runner, and three
  test source files, and asserted `eval/corpus` and `eval/runs` were absent.
  `.venv/bin/python work/figures-source-only/scripts/test-cloud.py`:
  **336 passed in 12.26s**, no skips, using staged `src/` and existing installed
  pinned dependencies. No local corpus or historical/native evidence was copied.
- `.venv/bin/python -m pip check`: **No broken requirements found**.

Real PDF inspection, text/image rendering, preservation comparisons, decision
writes, workspaces, and release gates run. Validator/model envelopes remain
explicitly named test stubs. No real AI or OCR service was enabled. This does not
qualify native ODL/veraPDF/OCR, human semantic accuracy, or the complete suite.
Actual-user, assistive-technology acceptance, and the LMS accessibility checker remain deferred.
Only source and this handoff are committed; no PDFs, secrets, model weights,
generated outputs, or review states enter Git. Next source-only candidates are
reference-policy tests and assistance contexts (the latter still depends on the
larger historical chapter and needs its own requirement audit). Native Linux
qualification remains a separate task with pinned tools and explicit config.

### Reference-policy and assistance continuation (October 16, 2026)

Branch `dev/synthetic-reference-assistance` continues from `b31d82c` without
merging. The published Linux workspace retained its Python 3.12.14 environment.
Baseline `.venv/bin/python scripts/test-cloud.py`: **336 passed in 11.83s**.

`tests/test_reference_policy.py` now copies the generated `tagged_control`,
replacing its local corpus dependency. `tests/test_assistance.py` uses the
existing deterministic two-figure occurrence control, replacing both the local
source corpus and historical ODL output. Its source is generated by removing
structure/catalog tags from that control; the prepared PDF remains an unchanged
copy of the tagged control. These are bounded synthetic test stages, not native
processing evidence. They retain distinct source/prepared hashes and identical
visible content. A new regression checks distinct bound hashes, absence/presence
of the structure tree, and real all-page text/render fidelity between them.
Existing assertions, gate behavior, refusals, revision/cache checks, and human
approval distinctions remain unchanged. Production code is unchanged.

The requirement audit found these assistance tests exercise metadata and two
figure occurrences, separate caption contexts and bounded crops, source/document
binding, provider protocol, cancellation, untrusted responses, cache provenance,
and protected human edits. They do not assert the old chapter's lists, tables,
columns, or four-page layout. The bounded generated control supplies their
required occurrences, embedded fonts, linked MCIDs and captions. It does not
qualify the larger historical document or native engine behavior.

Actual commands/results:

- `.venv/bin/python -m pytest -q tests/test_reference_policy.py --basetemp work/reference-first --tb=short`:
  **10 passed in 0.87s**.
- `.venv/bin/python -m pytest -q tests/test_assistance.py --basetemp work/assistance-first --tb=short`:
  **42 passed in 13.11s** before adding the source/prepared fidelity contract.
- `.venv/bin/python scripts/test-cloud.py` with both full modules plus the new
  contract: **389 passed in 24.72s**, no skips (13 modules).
- Source-only staging: extracted `git archive HEAD` into a fresh UUID directory
  under `work/reference-assistance-source-*`, copied only the two changed test
  modules and runner, and asserted `eval/corpus` and `eval/runs` were absent.
  Ran the staged `scripts/test-cloud.py` with the existing `.venv/bin/python`:
  **389 passed in 25.45s**, no skips. Imports were bound to staged `src/`; no
  corpus, historical evidence, native tools, or review states were copied.
- `.venv/bin/python -m pip check`: **No broken requirements found**.
- `git diff --check`: passed.

Assistance protocol tests bind an ephemeral **127.0.0.1-only HTTP test double**;
its fixed responses are not an LLM or semantic-quality evidence. These runs used
supported execution permission for loopback socket tests. A restricted sandbox
that denies sockets must allow this bounded test execution or report the failure;
do not skip it or expose/rebind a server. No external network is required by
the test runner after dependency installation. The runner docstring now states
the loopback requirement explicitly.

Reference-policy tests retain explicitly named validator, font-stage, and OCR
stubs, including adversarial false-preservation claims. Test-only OCR options
exercise policy enforcement; no native OCR engine runs. Real PDF parsing,
inspection, image crops, fidelity and release boundaries remain exercised.
Real AI and OCR services stayed off. No native ODL/veraPDF/OCR qualification or
full-suite claim is made. Actual-user, assistive-technology acceptance, and Canvas
the LMS checker tests remain deferred. Generated PDFs, crops, caches, outputs and review
states remain under ignored `work/`; only source and this handoff enter Git.
Next candidates include remaining adapter/font fixture prerequisites and the
separate pinned-native Linux synthetic qualification task.

The original synthetic corpus generator is `eval/build_corpus.py`. It requires an evaluator environment including pinned ReportLab, pikepdf, Pillow, and PDFium dependencies. Write to a new empty directory and inspect/declare its provenance before using it. Generating source fixtures alone does not produce the historical tagged outputs needed by some tests. Native reproduction scripts and their assumptions are documented in [eval/README.md](eval/README.md), [Phase 1 corpus notes](eval/PHASE1-CORPUS.md), and the release reports. Never rerun a historical trial into its existing evidence directory.

## Cloud coding environment: safe starting point

The first cloud task should establish source installation and tests with synthetic data, not import private local documents or start Phase 3. The Windows browser server and installed Ollama service do not move into a cloud environment with a Git push. A laptop's `127.0.0.1` also refers to the laptop, not the home computer or the cloud container.

The current [cloud environment guide](https://learn.chatgpt.com/docs/environments/cloud-environments) describes selecting the repository, choosing **Get started**, letting the setup conversation prepare dependencies, reviewing the setup, choosing **Publish**, and then **Start new task**. Starting a task uses the prepared filesystem and can continue while the home computer is asleep. Browser/Computer Use is not supported in that cloud workflow; use CLI and automated tests there. Personal Codex skills do not transfer automatically, so essential setup and development instructions must live in the repository.

On the laptop, sign in to the same ChatGPT account and choose **Work in > Cloud > PDFRemediator**. Continue the cloud development task or start a task in that published environment. This local desktop chat and its private document workspace are separate from the cloud source checkout. The cloud environment has no proxy secrets or environment variables configured; its saved install script runs the repository setup, dependency check, CLI version check, and exact contract runner.

On Linux, [scripts/setup-cloud.sh](scripts/setup-cloud.sh) creates a separate `.venv` and installs the pinned application/test dependencies. It requires Python 3.11 or newer; the published preparation uses the available Python 3.12.14. Use these repository-root commands for the tested source-development setup:

```sh
PDF_REMEDIATOR_PYTHON=python3 bash scripts/setup-cloud.sh
.venv/bin/python -m pdf_remediator --version
.venv/bin/python scripts/test-cloud.py
```

Pinned application/test dependencies are in [pyproject.toml](pyproject.toml). Network access is needed during dependency provisioning. No API key or paid model provider is required. Keep model assistance disabled for initial cloud work.

Native Linux processing additionally needs a compatible explicitly selected Java runtime, the OpenDataLoader **2.5.13** CLI JAR, standalone veraPDF **1.30.3** with its full distribution, and an explicit TOML configuration. Supply Linux paths for `java_home`, `odl_jar`, and `validator_cli`; defaults reference Windows. `validation.py` supports the official `verapdf` launcher layout using direct Java invocation, but a real Linux run must prove compatibility. The recorded Windows Java 25 success is outside the validator README's listed installation versions and does not establish a Linux choice. Review [validator provenance](eval/provenance-note.md) and the third-party official installation requirements before selecting it.

OCR is optional and should remain off initially. Its measured support is native Windows with OCRmyPDF **17.13.0**, Tesseract **5.5.3**, and the English model; Linux OCR dependencies, subprocess behavior, and fidelity require a separate synthetic trial. Application/ODL/OCR dependencies use separate environments because their constraints differ.

Do not expose or rebind the private review server to a public interface to make cloud preview work. Its loopback/Host/token/Origin policies are intentional. First develop and test via CLI; validate an approved authenticated preview or local checkout workflow separately. No change to those security boundaries is authorized merely by creating a cloud environment.

## Next development steps

1. Continue from the latest pushed development branch/checkpoint, preserving the
   Git allowlist and clean commits. Do not merge without separate authorization.
2. Use [STATUS.md](docs/STATUS.md) as the current checklist. Baseline and broaden
   source-only contracts with deterministic fixtures as changes justify it.
3. Use [NATIVE-LINUX.md](docs/NATIVE-LINUX.md) for the current bounded native
   reproduction and resource limits. Missing prerequisites fail, never skip.
4. Prepare interface/installer checks and representative permitted document
   trials; keep private inputs and actual review records outside Git.
5. Actual Windows updater, full usability/keyboard, AT and the LMS checker acceptance require
   the selected machine/testers and authorized scope. Prepared tasks are in
   [ACCEPTANCE-TESTS.md](docs/ACCEPTANCE-TESTS.md); no new owner action is needed now.

## Code map

| Location | Responsibility |
|---|---|
| `src/pdf_remediator/pipeline.py` | Processing, checkpoints, release gates, immutable bundles |
| `src/pdf_remediator/preservation.py`, `fonts.py`, `inspection.py`, `checks.py` | Bounded preservation/mapping repair and independent checks |
| `src/pdf_remediator/heading_checks.py`, `language.py`, `contrast.py` | Mechanical headings, conservative sampled language and bounded contrast evidence |
| `src/pdf_remediator/validation.py`, `engines.py`, `ocr.py`, `process.py`, `doctor.py` | Native adapters, execution limits, tool inventory |
| `src/pdf_remediator/sidecar.py`, `workspace.py`, `ledger.py` | Decision authority, review state/automatic records, verification |
| `src/pdf_remediator/web.py`, `web_assets/` | Private local application, Auto-fix orchestration, browser UI |
| `src/pdf_remediator/assistance.py` | Optional bounded loopback model drafts and origin/cache binding |
| `tests/` | Application/unit/integration/transport regressions |
| `scripts/setup-cloud.sh`, `scripts/test-cloud.py` | Source-only environment setup and explicitly bounded contract tests |
| `eval/` | Historical evaluation reports and reproduction scripts; raw evidence may remain local |

The two critical implementation boundaries are that **only checked preservation-safe artifacts are published**, and **automatic choices never become invented human verification**.
