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

## October 28: bounded Content Credentials derivative scope

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
genuine human, keyboard, screen-reader, LMS checker or accessibility approval.

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

The institution's planned move to a different LMS accessibility checker adds that
checker's published PDF checklist as an external acceptance reference. Its explicit PDF rules reinforce headings,
tables, reading order, language, links and form tooltip work already on this
roadmap. No result has been tested in that checker, and no checker score or WCAG
conformance is implied. Disabled checker defaults do not remove the need for
human judgment. AI stays off. The reference is the checker's own published PDF
checklist.

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
workflows, actual-user/assistive-technology/LMS checker, fresh-PC, distribution packaging
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
Graphical/keyboard/assistive-technology/LMS checker, fresh-PC, packaging and final release
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
developer evidence; actual-user, speech, keyboard and LMS checker acceptance remain open.

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
Graphical/keyboard checks, actual-user/assistive-technology/LMS checker acceptance,
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
new controls, actual-user/AT/LMS checker, fresh-PC, distribution and release gates remain.

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
graphical, user, screen-reader, LMS checker, packaging, distribution or release acceptance
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

# Development integration readiness

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
new graphical/fresh-PC, user/assistive-technology/LMS checker and distribution clearance
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
**18 open master items** in [the live checklist](STATUS.md).

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
screen-reader/LMS checker acceptance and release gates remain open.


Original PDFs, the selected saved input/review guards, original checkout,
validation source/Git state, installed application, prior builds/trials and
qualified runtimes stayed unchanged during these checks. All failed/intermediate
attempts remain evidence. No AI provider call, named approval, commit, merge,
release, installation or distribution occurred. New graphical/browser workflows,
a fresh Windows computer, actual-user/screen-reader/LMS checker acceptance and external
release remain separate qualification; the older GUI evidence does not qualify
this new OCR package.

Exact local evidence is bound by the new repair QA/source plan, package authority,
three-case program summary, whole-folder summary and separate table comparison.
These private documents, extracted text, logs and reviews remain outside Git.
The official artwork and Git allowlist are unchanged.


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
Fresh-PC, licensing, signing, human/AT/LMS checker and final owner/build gates remain separate.
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
semantic/usability review, screen-reader testing, authorized LMS checker feedback and
final owner/build decisions retain their separate gates. No external
distribution, commit, merge or release is cleared.

Retained evidence is under `work/rt-20261022-01/`: the native result is
`runtime-qualification-summary.json`, passing prepared results are in `prepared-02/`,
and the original failed attempt remains in `prepared-01/`. Acquisition,
independent-audit and preservation summaries are copied into `evidence/`.
That checkpoint's prior checkout authority is `source-application.json`, key `source_after`;
it records the guarded 135-to-136-file application and complete prior-byte
backups. The earlier 945-test and Python 3.11.9 package trials remain retained.

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
See [Windows distribution development](WINDOWS-DISTRIBUTION.md) for
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
authorized LMS checker feedback, final-build review and the owner's integration
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
LMS checker feedback, final-build review and an owner integration/release
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
remaining Windows workflow, actual-user, screen-reader and authorized LMS checker work
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
remaining user, screen-reader, broader keyboard and LMS checker acceptance boundaries
remain unchanged.

## October 21 controls and focus continuation — completed

The exact 127-file focus-repair source passed **841 tests in 141.71s**, with zero failures, errors or skips. Its complete shipped JavaScript harness passed **83/83** cases separately and runs within one Python test; it is not an additional Python count. Two independent retained probes also passed, for 85/85 cases in that bounded rereview. These are software checks with declared native adapters and named doubles, separate from browser and human acceptance.

A first deep mirror-path installation passed only three of five preparation cases, including selected-runtime Setup, then Start failed before creating review data; a read-only import reproduced a pikepdf native-DLL filename/path-length failure. That failed installation and evidence remain preserved. A distinct short-path validation/work installation then used normal copied Setup/Start with the exact tested focus-repair bytes. This follow-up does not fix or qualify the failed long-path environment. All 5 normal Setup/Start cases passed in 32.234s. Its initial combined authored PDF was processed by the installed CLI, then imported through the real browser. The outer helper initially assumed UTF-8 for redirected CLI stdout; a verified CP1252 byte roundtrip and complete equality to the independently written UTF-8 batch summary recovered the existing result binding. Setup, Start and processing were not rerun. The recorded browser focus cases passed for language draft, heading/table Save and named Accept, problem reporting, Return to pending and saved-review recovery. These observations used the actual in-app browser against the Windows service; they do not establish native default-browser keyboard behavior or a live delayed-response race. Only H1 and the Recurso TH/Column choice received explicit synthetic named acceptance; es remained pending, and title, Cantidad and all other decisions remained unchanged. Return to pending cleared the problem note through its existing backend route and focused the new empty note field; the same authored problem was then explicitly reported again. Independent raw-state checks confirmed the revision-6/revision-8 notes matched exactly, and revision 8 stayed byte-identical across skip-link reload/reopening. One manual item remained blocked, all others pending, with zero manual approvals and no Apply in this focus trial. The fresh visible Stop ended both owned service identities and the bounded startup console helper/listener; all 24 saved/bound/input/bundle files were unchanged. Stop and saved-data audit passed before the guarded two-file application; the final executable/test bytes match the tested source. These five later documentation updates change no executable bytes.

The original controls build and later focus build have separate source/evidence bindings. The earlier real native PDF Apply passed all three gates with six explicitly accepted synthetic structural/language edits; the later focus repair changes browser response/focus handling and its harness only. Strict gates and human-review requirements remain unchanged.

Audits preserved all 344 protected original/review/runtime files, 91 earlier retained files, 6,343 historical trial/installed files, 1,164 earlier installed source files and the separately recorded historical downloads. Existing originals, reviews and historical incomplete evidence remain intact. AI/OCR stayed off; synthetic named approvals never populate genuine human verification. No commit, merge, release, distribution or LMS upload occurred.

Broader native Windows keyboard/modifier and populated-control workflows, safe legacy import in this new trial, actual navigation/response overlap, genuine nontechnical-user semantic review, experienced screen-reader acceptance and explicitly authorized LMS checker feedback remain open. No conversation or developer fixture result grants human verification or release authority.

The earlier source-only and Linux counts below remain historical; no current source-only or Linux result is inferred. Formal integration/release remains separately authorized and bound to the eventual exact target and final source bytes.

Local exact-source manifests, commands, raw browser/native records and preservation maps remain outside Git under `work/lms-checker-native-controls-20261021-01/` (development mirror staging before retention). Start with `old-trial-summary.json`, `snapshots/final-stopped/`, and `focus-fix/prepared-final-01/suite-summary.json`; fresh focus records are kept separately under `focus-fix/`. Do not commit session authority, runtime logs, authored PDFs, review states or extracts.

October 21 implementation update: the new LMS-checker-related checks and reviewed fixes, their prepared software result and remaining qualification are recorded in [STATUS.md](STATUS.md) and [LMS-CHECK-APPLICABILITY.md](LMS-CHECK-APPLICABILITY.md). The October 20 comparison/native evidence below retains its earlier exact-source scope; it does not qualify the new controls. The development changes remain unmerged and unreleased.

Updated October 20, 2026. Application version remains **0.3.0**. This document
prepares review; it authorizes no merge, commit, distribution or release.
At that October 20 checkpoint, the Windows validation checkout was detached at
`9d857fa16bc92aaf5a416fe833e6481ea9049ad0` with preserved uncommitted setup,
browser/dashboard and test changes. Identify the actual source bytes, not just
the version or HEAD. The owner's working installation is separate and unchanged
by that disposable validation/documentation review. AI/OCR stayed off then.

## Local review and comparison baseline

The October 20 review fetched main from this checkout's existing private origin
without changing working files or merging. It resolved to the same revision used
by the October 18 Linux review:
`37fbf10ba18a7a8f206100e35dc458a09b079168`.
The merge base with this development history is
`762b087cbb9acd106898611f76a7cefa81b50107`. Main's source/tool/test tree matches the
available initial source baseline; the temporary missing-object limitation was
resolved before this review completed.

The committed source/tool/test comparison has 34 changed files (2,759 inserted,
155 removed lines), plus the separate working correction diff. Independent review
covers runtime, startup, updater, line preservation, fixture/assertion changes and
qualification tooling; retained notes state the inspection limits. Reproduce the
comparison without another fetch or working-file mutation:

```sh
git status --short
git ls-files --others --exclude-standard
git rev-parse HEAD
git diff 37fbf10ba18a7a8f206100e35dc458a09b079168...HEAD --stat
git diff 37fbf10ba18a7a8f206100e35dc458a09b079168...HEAD -- src scripts tests eval pyproject.toml
git diff --stat
git diff -- src tests "Setup PDF Remediator.cmd" README.md docs HANDOFF.md
git diff --check
```

The working diff and two new test files matter: HEAD alone omits the local
fixes. Include scripts/test-web-assets.cjs and tests/test_web_assets.py when
reviewing an uncommitted source tree. Review the
committed comparison and working diff together. No new actionable regression was
identified within the documented earlier static review scope. The Ctrl+Home
handler and renderer coverage have software and bounded native shortcut proof.
The subsequent protected-note backend repair has an independent patch/test review
and a fresh prepared suite; broader browser/human acceptance remains open. This does not
prove every race/platform condition or grant integration approval. Recheck a
changed target/build before a later proposal. Do not reset, clean, switch, merge
or overwrite the checkout to make a comparison work.

| Area | Resulting behavior and reviewer focus |
| --- | --- |
| Reproducible inputs | Runtime-authored fixtures replace historical/private corpus dependencies. Native tools and the pinned licensed AMS archive remain explicit external prerequisites. Software doubles remain distinct from native proof. |
| Bounded line preservation | Source-proven ASCII paragraph boundaries receive explicit spaces under strict font/operator constraints. Unsupported shapes remain unchanged. Validator, supplemental and every-page fidelity gates remain required. |
| Setup and startup | Setup and double-click startup select local-runtime.toml when present; invalid selected configuration refuses. Startup detects incompatible live implementation/settings and gives restart instructions. Digests diagnose compatibility, not publisher authenticity. |
| Retry/cancellation | Failed modifying runs retry into separate bundles using the hash-bound original/settings and current runtime. Read-only failures cannot become modifying retries. Queued cancellation prevents work; active native cancellation retains cooperative bounds. |
| Apply authority | Existing reported problems and later revisions prevent outdated Apply attachment. Title/figure edits preserve blocked and pending manual items, notes and attribution while invalidating positive artifact approvals and obsolete automatic dispositions. Detached completed bundles remain separate/discoverable. |
| Browser recovery | Reopened problem-note fields display saved notes. Skip destination main does not replace private session authority. Drafts, named accepted values, automatic choices and human verification remain separate. |
| Dashboard performance | Listings validate the saved envelope without rehashing historical PDFs or holding the global PDF lock. Saved labels and artifacts_checked=false communicate the boundary; opening and protected actions perform full current validation. |
| Lifecycle diagnosis | Authenticated Stop and service-closing emit fixed UTC messages without private URLs/tokens/configuration. The old unexplained closure remains undiagnosed. |
| Checked source updater | Inspection by default, complete-package checks, staged replacement/backups and explicit rollback failure locations. Local configuration/reviews are preserved. It updates only src/pdf_remediator, not root helpers/docs/dependencies, and does not authenticate a publisher. |

## Recorded checks and evidence

The earlier source-only Windows run passed **654 tests in 90.05s**, zero
failures/skips, on the keyboard-fix source copy, before the backend note repair.
No new source-only count is inferred. Its explicit native-JAR/licensed-font
exclusions are not counted as passes. The new pytest entry executes the complete
shipped app.js under Node with named DOM/HTTP doubles: **39 checks passed** (the
original 18 plus seven saved-note and 14 keyboard-event checks). These 39 are
embedded in one Python test, not 39 additional Python passes. The final affected
wrapper passed again after moving the Node version diagnostic before imports.

The old keyboard handler fails five new modifier cases; removing only the saved
note assignment fails six renderer cases. The source runner and normal pytest
require Node.js 20+ and fail clearly when it is missing/too old. This is a
developer-test dependency, with no npm packages and no application runtime change.
Cloud setup checks it before preparing the Python environment.

The latest prepared Windows suite passed **675 tests in 64.45s**, zero
failures/errors/skips, on a fresh 118-file snapshot including the exact three-file
backend repair and eight new public-operation tests. The previous backend failed
six new cases while two same-value controls passed; the repaired focused scope
passed 88 tests in 15.47s. The new tests retain problem notes/status/attribution
through changed title/figure values and preserve Apply refusal. They do not
restore previously erased active notes or replace native/human observations.

The earlier fresh prepared snapshot passed **667 in 72.98s** before the backend
repair. Its socket-restricted attempt (607 passes/60 failures) is retained
separately; the permitted private-loopback retry skipped no refusal test.
The earlier **666 in 90.05s** and focused **185 in 26.77s** retain their original
source/evidence bindings. Both native installations retained their exact frozen 118-file source manifests. Phase A precedes the backend repair; Phase B matches the 675-case tested snapshot with the exact three repaired source/test files. These five documentation-only updates follow testing; executable bytes remain unchanged.

Phase A observed native Ctrl+Home/Ctrl+End scrolling without changing the selected
review panel, bare Home/End/Left/Right tab selection/focus, Tab/Shift+Tab traversal
and Shift+Home preserving selection. Review bytes stayed unchanged. Visible Stop
ended the owned service/listener. Its exact source precedes the backend repair;
the file chooser used native set-value rather than full keyboard-only upload.
All 20 bounded Phase B native observation groups passed: protected notes survived title/figure edits, skip-link reload, reopening and a full application restart; Apply refused the retained problem; exports/download stayed bound; paired chapter pages, separate figure drafts and group-selection reset behaved as observed. Both visible Stops ended the owned services/listeners.

Native Windows checkpoints separately establish the named cases, not all platform
conditions: 12 selected-runtime setup cases; seven real-package updater cases,
including actual sharing-denied rollback/recovery; launcher/session mismatch;
accepted-title Apply; graceful restart with saved values/downloads/exports; active
Java-job cancellation and separate retry; and the earlier 11-observation Edge
recovery/download/visible Stop run with five final and eight independent checks.
That earlier recovery trial preserved 344 protected existing files and seven
earlier trial histories. Final audits preserved all 344 protected original/review/runtime files and eight earlier trials: 14 reviews/bundles, 220 immutable files, 38 bindings, 33 exports, 928 installed source files, 4,836 retained trial files and 1,497 retained installed files. Phase A retained its review, 16 immutable files, 118 source files and 36 native proof files. Phase B retained both revision-3 reviews, 32 immutable files, all 62 saved/input/run/export files, three exports and the matching native/retained download through restart, reopening and final Stop. Historical findings and incomplete dispositions remain unchanged. AI provider calls were zero, OCR never ran, and synthetic human
approvals do not become actual-user acceptance.

Authoritative local reports and exact reproduction helpers remain under ignored
`work/`; see the evidence index in [STATUS.md](STATUS.md) and dated
[HANDOFF.md](../HANDOFF.md) sections. In particular:

- `native-keyboard-20261020-01/` retains the latest prepared/repair/native
  continuation evidence. Start with `PhaseB-native-summary.json`, `phaseA-native-summary.json`, `final-preservation-audit.json` and `notes-edit-fix/prepared-final/prepared-suite-summary.json`.
- `windows-launcher-browser-dashboard-recovery-20261020-01/prepared-suite.log`
  records the 666-test result. Its summary retains the incomplete initial native
  UI attempt and authenticated background cleanup without claiming native Stop.
- `windows-launcher-browser-recovery-retry-20261020-01/native-browser-recovery-retry-summary.json`
  records the subsequent successful native recovery, exact download and visible
  Stop with independently observed process/listener closure.
- `readiness-review-20261020-01/` retains the documentation review snapshots,
  source/preservation checks and independent code review notes. Raw local paths,
  manifests, reviews, logs, PDFs and private session authority stay outside Git.

At the earlier Linux checkpoint, source-only **644 / prepared 657** tests passed;
seven native lifecycle cases and 11 named native cases plus two fidelity negatives
completed. Default 200-page publication refused on fidelity failure; regrouping
alone remained a draft; authored automatic descriptions plus regrouping produced
a candidate with **1,234 human items pending**. See [NATIVE-LINUX.md](NATIVE-LINUX.md)
and the dated handoff for exact hashes/timings. These historical results are not
new runs of the current Windows working diff.

## Reproduce software checks

Use a fresh disposable source copy with its own prepared application/test
environment and the exact reviewed native/font prerequisites. Never reuse an
existing --basetemp or run native trials over saved evidence. Node.js 20+ must be available on PATH for both normal pytest and the source-only
runner. It is not required by the application installer/runtime. The source-only
runner chooses a fresh directory and calls no real model/OCR/native engine:

```powershell
& '.\.venvs\app\Scripts\python.exe' -B '.\scripts\test-cloud.py'
if ($LASTEXITCODE -ne 0) { throw 'Source-only checks failed.' }
```

For the prepared Windows suite, replace the AMS placeholder with the reviewed
archive. Set these variables in a dedicated shell (or restore prior values):

```powershell
$env:PDF_REMEDIATOR_NATIVE_CONFIG = (Resolve-Path -LiteralPath '.\local-runtime.toml').Path
$env:PDF_REMEDIATOR_AMSFONTS_ARCHIVE = 'C:\actual\reviewed\amsfonts.zip'
$preparedRun = Join-Path '.\work' ('readiness-prepared-' + [guid]::NewGuid().ToString('N'))
& '.\.venvs\app\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider `
  tests eval/test_validate.py eval/test_metrics.py --basetemp $preparedRun --tb=short
if ($LASTEXITCODE -ne 0) { throw 'Prepared checks failed; retain the evidence.' }
```

Missing/altered prerequisites fail the declared scope; do not skip them or count
those modules as source-only passes. Tests contain explicit worker/validator/
provider doubles where declared. Real native evidence remains separate.

The actual-script harness is now source-distributed and included in normal
Python/source-only tests. Run the complete actual-script harness independently from any source checkout
with Node.js 20+ (no browser, service or npm dependencies):

```powershell
& node --test-reporter=tap '.\scripts\test-web-assets.cjs'
if ($LASTEXITCODE -ne 0) { throw 'JavaScript checks failed.' }
```

The historical 18-case local harness remains retained without overwriting it.
The earlier background evidence is under
`work/background-ui-fixes-20261020-01/`; its summary
links the fresh source-only output, final 39-case TAP, guarded source manifests,
mutation/refusal controls and review note. Native keyboard acceptance is separate.

Existing native Linux reproduction commands remain Linux-specific:

```sh
.venv/bin/python scripts/test-cloud.py
PDF_REMEDIATOR_NATIVE_CONFIG=work/native-linux-reproduced-tools/runtime.toml \
PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-reproduced-tools/amsfonts.zip \
.venv/bin/python -m pytest -q tests eval/test_validate.py eval/test_metrics.py \
  --basetemp work/readiness-prepared-new --tb=short
.venv/bin/python scripts/qualify-review-lifecycle.py \
  --config work/native-linux-reproduced-tools/runtime.toml \
  --output work/readiness-review-lifecycle-new
.venv/bin/python scripts/qualify-native-linux.py \
  --config work/native-linux-reproduced-tools/runtime.toml \
  --output work/readiness-native-new --include-book
git diff --check
```

Replace runtime/archive and output paths with actual reviewed/fresh locations.
The native lifecycle fixture deliberately injects a later edit and uses synthetic
reviewer attribution; it does not complete genuine human reviews. Windows native
reproduction uses the retained named trial helpers and actual browser actions,
not the Linux scripts or a replay of raw artifact assertions.

## Remaining gates and support boundary

A passing PDF is an accessibility **candidate** for supported bounded inputs.
Automated results do not establish correct semantic meaning, reading order,
mathematical meaning, WCAG conformance, screen-reader usability or an LMS checker score.
Unsupported equations/forms, complex layouts, arbitrary fonts, signed/encrypted
PDFs and PDF 2.x retain manual/refusal boundaries. Automatic records are not human
approval. No general platform or complex-document support expansion is implied.

Before any later integration/release decision:

- Complete the remaining [browser/keyboard acceptance tasks](ACCEPTANCE-TESTS.md).
  Complete the remaining full Windows keyboard protocol and supported modifier combinations, multi-file picker qualification, grouped exceptions and individual/group acceptance controls, and seeded negative controls beyond the authored missing-description chapter. The completed page, occurrence and selection-reset cases remain bounded developer proof. The completed bounded cases retain their own exact
  source/artifact evidence and do not complete genuine human acceptance.
- Obtain genuinely completed human semantic/usability reviews and experienced
  screen-reader observations on exact representative artifacts. Actual-user/AT
  work remains deferred until authorized.
- Obtain the qualifying actual LMS checker record only with explicit course/
  upload authorization. Bind hashes, reader/OS/AT versions, reviewer/date and
  scope; do not populate verification from conversation or synthetic labels.
- Resolve confirmed blockers and repeat affected checks on changed code/artifacts.
  Further Windows reboot/crash, ACL/disk and fresh-machine variants are additional
  hardening scope; the completed sharing-denial/graceful-restart cases stand.
- Bind the exact final build to its tests and selected integration target. The
  source review against fetched main `37fbf10` is complete for its stated scope;
  recheck affected changes if the build or target moves. No merge rehearsal or
  integration is claimed by static source comparison.
- Have the owner separately decide whether to authorize integration or release.
  No merge, commit, tag, upload, publication or distribution occurs in this work.
