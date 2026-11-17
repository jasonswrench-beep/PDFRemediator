# Things only a person can check by hand

Everything a program can check is checked by tests (see `tests/` and `scripts/test-web-assets.cjs`). This list holds only what
needs a human: judgement, a real assistive technology, or a computer that is not this one. Tick a box and add the date and who did it when it is done; do not
delete a line that was never checked.

Last updated 2026-11-16 (the section "Development-list round of 2026-11-16" is new).

## Test runs on an unstable computer

Some computers (for example ones with a degraded processor) make plain Python crash at random: "access violation" errors, odd errors that cannot happen in correct code,
or a failure that never comes back. If a test fails once and passes on a rerun, suspect the computer first. `python scripts/run-tests-by-file.py` runs every test file in its own
process and retries a crashed one. Limiting the process to the stable cores (for example `psutil.Process().cpu_affinity([...])`, children inherit it) gave clean runs on such a machine.
The full suite is expected to end with only the environment failures listed below.

## Screen readers and keyboard (a person with a screen reader should do these)

- [ ] **New dialogs with NVDA/Narrator.** (A scripted NVDA pass on 2026-11-01 found both dialogs announced correctly with the right focus and Escape behaviour; this is still for a person to repeat, and for Narrator.) Open Processing options and tick "Rebuild a missing letter dictionary by reading each page": the dialog should be announced with its title and
  text, focus should land inside it, and Escape should return to the box unticked. In a review, change a field without saving and press "All documents": the "Leave this review without saving?"
  dialog should be announced with "Stay and keep editing" focused.

- [ ] **Status bar and Auto-fix line.** With a screen reader (NVDA, Narrator, or another): start a scan and listen. The step should be spoken when it
  changes; the clock ("Working for 1:23") must not be read out every second. Check that "Cancelling..." is announced after Cancel.
- [ ] **Home, Reset (top bar) and "Reset choices".** Tab to each; the spoken name should say what it does (the top-bar Reset is
  announced as "Reset: go to the start screen and clear the PDFs you chose and every option"). Check that "Reset choices" is
  read together with the line under it.
- [ ] **Keyboard only, whole flow.** Scripted already (`scripts/e2e-browser.cjs`): Tab visits every enabled control on the start
  screen (10 stops) and on a review (106 stops) in a sensible order, each shows a focus indicator and is scrolled into view, none
  is hidden behind the bottom bar, and the tour comes back to its start (no trap). A person should still do the real flow with
  only Tab, Shift+Tab, Enter and Space: choose a PDF, process, Cancel, Reset, Home, open a review, Auto-fix, Stop application,
  and judge whether the order and the focus outline feel right.
- [ ] **Focus after Home/Reset.** After pressing Home or Reset, where does a screen reader start reading? (The page moves focus to
  the main area.)

## Looks and fit (a person should look)

- [ ] **High zoom and small windows.** Scripted checks already prove the start and review screens do not scroll sideways at 320 px
  wide (400% zoom) and that Home, Reset, Process and Reset choices stay on screen (`tests/test_reflow_narrow.py`, and the
  end-to-end driver). A person should still look at 200% and 400% zoom: the bottom bar wrapping over several lines, the review
  screen's page pictures, and whether the wrapped top bar looks tidy.
- [ ] **Windows High Contrast / forced colours.** The bar, the Auto-fix line, the Reset explanation and the new buttons must still
  be visible and readable.
- [ ] **Dark mode / text-only sizes.** The page is light only; check it is acceptable when Windows is in dark mode.

## Other computers

- [ ] **Spare PC, build 09.** Follow `TEST-STEPS - build 09.txt` in the USB kit folder on the other PC: installer folder box
  (the suggested name already exists, so it must be changed), own window opens, Stop and X both close it, nothing left running.
- [ ] **A PC without the Microsoft Visual C++ Redistributable.** The message in the installer and in the launcher has only been
  tried with an impossible minimum version, never on a real PC without the package (a virtual machine would settle it).
- [ ] **A PC without the WebView2 Runtime** (an older Windows 10). The program should say it needs Microsoft's free WebView2
  Runtime and offer Microsoft's page, instead of opening.
- [ ] **Windows SmartScreen.** The installer is unsigned; check what a first-time user sees and that the note's wording matches.
- [ ] **Relaunch after the program was killed** (not stopped): start it again; it should recover from the stale session file.

## Judgement about documents (always a person)

- [ ] **The guide's review draft.** For the long designed-guide test file: read order, table header
  relationships, picture descriptions, link structure and the small-font and contrast checks need a person. Page 1 is a scan with
  a few hidden text marks; the OCR options stop there on purpose, so it needs OCR by hand or a better source.
- [ ] **Anything the program calls "not verified".** Automatic mode and review drafts are never human approvals.
- [ ] **A second opinion on the form rule.** `form_edits._form_signal_scan` and `inspection._inert_empty_acroform` now accept plain
  page links, bookmarks and a short list of standard structure attributes next to an empty form shell. A qualified person should
  read `tests/test_inert_form_navigation.py` and the two functions and say whether any accepted case could hide real form
  behaviour. An independent read by a separate assistant (fresh context, 2026-10-31) tried about 134,000 single-key mutations and
  4,000 random documents and found no way to make a real field, widget, signature, XFA, script or active action look like an
  inert shell through the new code. It found one disagreement between the two checkers about direct (non-indirect) bookmark
  entries, now fixed and tested, and four action types missing from the lists (GoToDp, RichMediaExecute, SetState, NoOp), now
  added. Left as they were, for a qualified reviewer to judge (all the same before this change): a 3D annotation whose data stream
  carries a script, and a RichMedia annotation that activates on opening, are not treated as form signals; a dictionary with a
  duplicated key is read by qpdf as its last value, and a viewer that keeps the first could see a different link target; the two
  checkers differ slightly in nesting-depth and size limits (each is the stricter one in a different case); only the inspector
  checks that a structure element's /Pg is a page.

## Release decisions (only the owner can make these)

- [ ] Making the repository public (the written offer for the GPL-2.0 libjbig points at its issues page, so it must stay up).
- [ ] Counsel review of `THIRD-PARTY-NOTICES.md`, `docs/LICENCE-REVIEW.md` and the Microsoft runtime route.

## Known flake in the test suite

- [ ] Native-code tests (`test_form_additional.py`, `test_adapters.py`, `test_semantic_tree_pipeline.py`) sometimes ended the whole Python process with
  "Windows fatal exception: access violation" on one development computer, also on the commit from the start of the work, so it is the computer and not the code (see above).
  `python scripts/run-tests-by-file.py` runs every test file in its own process and retries a crashed one. On stable cores all 87 test files passed on the first attempt
  (3377 tests, about 14 minutes) with only the 8 environment failures: the 7 font tests stop with "Set PDF_REMEDIATOR_AMSFONTS_ARCHIVE to the reviewed amsfonts.zip",
  and the jar test needs the local OpenDataLoader jar to be configured (it reports "missing").
- [ ] If you want those 8 to run: put the reviewed `amsfonts.zip` somewhere and set `PDF_REMEDIATOR_AMSFONTS_ARCHIVE` to its path, and set up the local jar as the project docs say.

- [ ] One unexplained failure was seen twice on one development computer: a second scan of a long PDF, after a cancelled first scan, ended with `Cannot import stale evidence: Prepared PDF decision occurrence context changed`.
  It did not come back in 16 later attempts and is most likely the unstable-computer effect described above; if anyone sees it again on a healthy computer, keep the `runs` folder of that data directory (the refusal can be reproduced offline from the kept bundle). The page now says it in plain words and keeps the detail in brackets.

- [ ] The local service process exited once, without any message, in about 25 cancel-then-rescan runs of the long guide (the rescan began about three seconds before the page reported
  "The local service is not responding"). It did not come back in 11 later runs with the crash tracer on (`PYTHONFAULTHANDLER=1` in the service's environment writes the native stack to its log).
  If it happens again, keep the service log of that run.
  Since 2026-11-01 the service turns the crash tracer on by itself (`faulthandler`, writing to the same `application.log`), says "PDF Remediator service starting (process N)" when it starts and "closing" when it ends normally,
  and the launcher's "could not start" message now says how the service ended (for example "an access violation", with the code) and where the log is. So a silent exit now leaves one of three traces:
  a native stack, a "closing" line, or neither (which means Windows ended the process from outside). Tested with a real hard crash in a child process; not yet seen on a real silent exit.
- [ ] **OCR evidence in plain words.** On a review item that carries the text recognition's page-by-page evidence, the page now shows one sentence per unsure page
  ("Page 3: many words were unsure (40 percent of its 120 words were read confidently).") with the rating rule in words, and keeps the recorded data underneath in a closed section. Tested by running the shipped function alone in Node
  (`scripts/test-plain-evidence.cjs`, 8 cases). Not looked at in a real browser on a real scan: open a scan that has pages the program flagged and read the sentences against the page images.

## Development-list round of 2026-11-16 (things only a person can do)

Written for the 2026-11-15 development list. The program-side work for items 2 to 6 is done and tested as far as a program can test it; these
are the parts that are a person's, a second computer's, or the owner's decision.

**The three build items (list item 1; software-tested on synthetic documents only, no real document has been judged with any of them)**

*Colour-only meaning* (`docs/COLOR-ONLY-MEANING.md`)

- [ ] **The colour card in the real window.** Process a PDF of your own that has coloured text, a link without an underline and a multi-colour
  chart. Open the review: the card "Meaning that may depend on color needs review" should list each candidate in plain words with working Page
  buttons, no edit buttons, and a required pending `color-meaning` item.
- [ ] **Screen reader and keyboard on that card.** Plain headings, paragraphs and Page buttons: read in order, buttons reachable.
- [ ] **Judge the candidates on 5 to 10 real course documents.** Are the coloured-text, link, chart and phrase candidates the ones a person cares
  about? Too many (brand-coloured headings, decorative strips)? Which are missed (a chart saved as a picture is never listed, only the page is
  flagged)? The thresholds are in `color_meaning.THRESHOLDS` and recorded in every result; tune them from what you see.
- [ ] **Judge the repair guidance** (`fix_path` and the guide): could an author act on it?
- [ ] **Decision: is a required colour review on most documents too much?** Pictures, pattern or shading paint, form fields, layers, Type 3 text
  and anything over 100 pages keep a page under review, so the review is required on most real documents. Decide whether pictures alone should
  require it.

*Wrong characters and fonts* (`docs/UNICODE-AND-FONT-REPAIR.md`; the in-window editor is not built)

- [ ] **The characters card.** Open a review of a PDF whose extracted text has private-use or replacement characters and read "Some characters may
  be extracted wrongly": plain words, right pages, announced sensibly by a screen reader?
- [ ] **A real corrected copy.** With a real PDF, run `remediator characters inventory`, `plan` and `apply` for one wrong code. Open both PDFs: does the
  corrected one look identical, does copy and paste give the right character, does a screen reader speak it? Only a person can judge that the
  typed character is the right one.
- [ ] **A second opinion on the proofs.** A qualified reader should read `character_corrections.canonical_graph` and `_text_proof` and say whether
  any change other than the ToUnicode maps could pass them (for example through an object the graph walk does not reach).
- [ ] **False positives and misses on 5 to 10 real documents** (Word, InDesign, LaTeX, scan plus OCR): does the screen flag too much (glyph-name
  versus mapping on legitimate minus or hyphen choices, ActualText used on purpose) or too little?
- [ ] **The text proof on a messy long document.** Correct one code in a long book and confirm the proof does not refuse for reasons unrelated to
  the edit.

*Logo and branding, and the scanned-page sample* (`docs/LOGO-AND-OCR-REVIEW.md`)

- [ ] **Logo and branding on a real document.** Open a real course PDF whose header logo repeats, press "Find logos and repeated branding" and check
  the list matches what you see. Describe one group (3 to 10 words), mark another decorative, accept by name, Apply, and check the new PDF with a
  screen reader: each logo reads as chosen or is skipped, and nothing else changed. Does the guidance wording help?
- [ ] **The scanned-page sample on a real scan.** Run OCR on a real scan of 15 or more pages, open Review checks, and compare each sampled page with its
  picture. Are the chosen pages sensible (worst first)? Is it easy to see the page and its recognized text together? Record all three checks,
  confirm the scanned-text review cannot be approved before every page passes and can be after, mark one page a Problem and follow the guidance,
  and try a cut-off page.
- [ ] **Screen reader, keyboard and zoom on both panels.** Status line takes focus after Find, Save, Accept and Save record and is read; each radio group
  is announced with its legend; Tab order; 200 percent and 400 percent zoom, forced colours, dark mode (a 320 px reflow check exists and passes where a
  headless Edge or Chrome is installed).
- [ ] **Decisions made for you (keep or change):** the logo thresholds (15 percent repeated, 6 percent margin, 12 and 8 percent bands), the sample size
  (about 20 percent, 3 to 10), gating only the `image-and-ocr` review, and **`ledger add` now refusing a scanned document that has no complete
  page records for its sample**.

**Seen while building (not changed)**

- [ ] **Do the small-text and empty-tag cards ever appear in a real review?** `workspace._repair_findings` maps only `metadata-meaning`,
  `contrast` and the two new ids to a card, so the existing `small-font` and `empty-structure-tags` cards in `app.js` look reachable only from
  test fixtures. Open a real review of a document with small text and see. If they do not show, mapping `"small-fonts": "small-font"` and
  `"empty-tags": "empty-structure-tags"` is a two-token change (and `prettyGroup` has no friendly name for them either).

**Alpha 8 (built and signed 2026-11-16)**

- [x] **Install alpha 8 over alpha 7 and test it (2026-11-16, by the assistant on the owner's own PC, silent setup).** `PDF-Remediator-Setup.exe /S /D=<the alpha 7 folder>` ran over the real alpha 7 copy: exit code 0 in 33 seconds; the folder now holds release 0.3.0-alpha.8 and all 3,763 listed files match the manifest byte for byte, with nothing left over from alpha 7 (only `.installation-complete.json`, `package-manifest.json` and `uninstall.exe` sit outside the list, as expected); the Settings > Apps entry and both shortcuts (desktop, Start menu) point at the install. Program window: opens titled "PDF Remediator" with its service on a loopback port; closing the window stopped the service (log: "Stop application requested", the port closed); force-killing it and starting it again recovered from the stale session file (new port, answered). Check for updates said "You have the newest version, PDF Remediator 0.3.0 alpha 8." Then, on a **second copy of the installed runtime with an empty scratch data folder** (so no real reviews were touched), four small PDFs were processed and the new reviews used: the colour-meaning card (see the finding below), the logo workflow on a tagged two-page file (found the repeated logo, saved a description, refused to accept without a name, accepted by name, "Apply accepted edits" made a new bundle in which both figures carry the description and the figure check passes; the original PDF is byte-identical), OCR with the sampled-page review on a six-page scan (the sample chose pages 1, 3, 6; approving the scanned-text check was refused until all three had a pass record, then allowed; the recognized text equalled the printed text word for word and in order on all three), and `remediator characters inventory` from the installed runtime. **Not done:** the setup wizard's own pages (folder suggestion, the Retry stop while the program runs), uninstalling from Settings > Apps (that would have removed the owner's working copy), a silent or wizard update over an install that has saved reviews (the real alpha 7 copy had none: its `workspaces` folder was empty, so "keeps saved reviews" was only shown as "every file in `output` unchanged by setup"), a character-meaning card on a real candidate, anything with a screen reader. Installer SHA-256 `3ce529c7efb630dac01cf4e7a8a2e93a8ba08aae178425a54e37e9d5f53680f3`.
- [x] **The uninstaller's signature (2026-11-16).** `uninstall.exe` in the install folder is signed Valid by Jason Wrench with a Microsoft timestamp, as is `PDF Remediator.exe`.
- [ ] **Colour screen missed vector graphics in untagged PDFs (found 2026-11-16; fixed in the source the same day, not yet in any installer).** The program's own tagging step marks the untagged chart shapes and pictures of the result `/Artifact`, and the card was built from the result, so its graphic screen skipped them (4 candidates shown where the original has 5). `color_meaning.with_original_graphics` now takes the graphic findings from the unmodified input and keeps the copy's other findings (`docs/COLOR-ONLY-MEANING.md`, "Shapes the program itself marks as Artifact"). Checked by 16 new tests and by running the real pipeline from the fixed source on the same test PDF (5 candidates, `graphics_from_original` recorded). **Built into alpha 9 (not installed yet):** the installed alpha 8 has the old behaviour until alpha 9 is installed; then look at the card in the real window on a document with a chart (a person should judge whether the added sentence about "the unmodified input" reads clearly).
- [ ] **Group list shows the raw name "small-fonts".** In "Work through the review" the group for small text is listed as `small-fonts` because `prettyGroup` in `app.js` has no name for it (older than alpha 8).
- [ ] **Other tools' copies of `sign_windows.py`.** The same file is shared by the other OpenStage tools' builds; the copy here now asks PowerShell for UTF-8 so a non-ASCII name cannot break the signature reader. Copy the change to the others (it was not made in their repositories).
- [ ] **Signing quota.** Each signed build uses about 94 signatures of the signing account's allowance; a repeated or failed build uses more.

**Alpha 9 (built and signed 2026-11-16, evening)**

- [x] **Install alpha 9 over alpha 8 and test it (2026-11-16, by the assistant on the owner's own PC, silent setup).** Before installing, the installed alpha 8's Check for updates said "PDF Remediator 0.3.0 alpha 9 is available. You have 0.3.0 alpha 8. Installing it over this copy keeps your saved reviews." with a link to the alpha 9 page (the first time the "available" answer was seen against the real GitHub list). `PDF-Remediator-Setup.exe /S /D=<the install folder>`: exit code 0 in 30 seconds; release 0.3.0-alpha.9; all 3,763 listed files equal the manifest, nothing left over; the 303 files of the `output` folder are byte-identical before and after (the real copy holds no saved reviews: `workspaces` is empty); `uninstall.exe` and `PDF Remediator.exe` are signed Valid by Jason Wrench with a timestamp (**this settles the uninstaller-signature question for alpha 9**); both shortcuts and the Settings > Apps entry are right (its size, 555,662 KB, equals the program files plus the `output` folder, which had grown). Program window: opens as "PDF Remediator", closing it stops the service, a forced kill then a relaunch recovers (new port), closing again leaves nothing running. After install, Check for updates says "You have the newest version, PDF Remediator 0.3.0 alpha 9." On a scratch copy of the installed runtime: the colour card for a test file with coloured text, a four-colour block of shapes and a repeated picture lists **5 candidates including the block** (alpha 8 showed 4) and ends its grey notes with "Chart-like shapes were read from the unmodified input, because this program marks untagged shapes as artifacts in its processed copy and the graphic screen skips artifacts there." It reads clearly enough as the last small note, but a person should judge it (it is technical, and the note above it still says artifact content is skipped). **Not done:** the wizard pages, uninstalling from Settings > Apps, an update over an install that holds saved reviews, any screen reader. Installer SHA-256 `48fddc18ad9aed90025cab35be7be8e9d0ade2094d775af634cfc7d9785ccf2f`.
- [ ] **BUG, found 2026-11-16 in alpha 8 and alpha 9: scanned-page OCR fails at random because the build replaced the makers' signature on two Tesseract files. Fixed in the build script the same day (not released): alpha 8 and alpha 9 keep the defect, so the fix needs a new build (alpha 10) and an install.** `runtime/tesseract/tesseract.exe` and `libtesseract-5.dll` come from the makers (Universität Mannheim) already signed; Windows reports that certificate as expired ("UnknownError"), `sign_windows.sign_one` treats every status other than Valid as unsigned, and `package-windows.py` `ArtifactSigner.sign_programs` replaced the makers' signature with ours (34 programs in the Tesseract tree: 32 unsigned, these 2 re-signed). A launch of the re-signed `tesseract.exe` returns exit code 0 with **no output** about 1 to 3 percent of the time (measured: 3 of 400, 4 of 200, 6 of 192, 8 of 240 launches; one at a time or in parallel), so ocrmypdf stops with "did not report its version", "could not be executed" or "not enough values to unpack" and the run ends `failed` ("OCR did not complete"). In 3 simultaneous OCR runs 2 of 9 failed; a single run usually succeeds, so a many-page scan is at real risk. The same file with the **makers' signature kept** failed 0 of 1,000+ launches (as the original, and in a copy of the installed tree with only those two files restored: 0 of 700, against 3 of 400 as installed in the same session); a copy re-signed with a local self-signed certificate also failed (3 of 300), so it is the replaced signature, not our certificate or the folder. Alpha 7 (makers' signature kept) is not affected. **The fix:** `ArtifactSigner.sign_programs` (`scripts/package-windows.py`) now leaves any program whose signer is not us and whose status is not Valid, NotSigned or HashMismatch, does not count it as a problem in the check after signing, and lists it in `build-summary.json` as `makers_signatures_kept_not_validating_now`; `sign_windows.py` is unchanged (shared with the other tools). 8 new tests with a fake signer in `tests/test_windows_package.py` (they fail with the rule switched off). Run against the real inputs the rule keeps exactly the two Tesseract files and changes nothing else: the other 32 Tesseract programs are unsigned and get signed, and all 167 programs in the wheels and archives are either Valid (Eclipse, Microsoft, Python Software Foundation) or unsigned. `docs/FRESH-PC-AND-SIGNING.md` now describes the rule and gives a 400-launch `tesseract.exe --version` check (9 of 400 failed on the installed alpha 9 copy, 0 of 400 on the makers' original). **Still to do (needs the owner's go-ahead):** build alpha 10 (about 94 signatures), run that check on the new payload, install it and process a multi-page scan three times at once, then publish.

**Distribution (list item 2)**

- [ ] **Fresh-PC install test.** Follow `docs/FRESH-PC-AND-SIGNING.md`, section 1, on a PC or a virtual machine restored from a clean
  snapshot that really lacks Microsoft's Visual C++ Redistributable and the WebView2 Runtime (at least once each). Record the table's "Seen"
  column and the SmartScreen text word for word. (This subsumes the two older "A PC without ..." boxes above; tick those too if the same run
  settles them.)
- [ ] **Sign a build and check the signature.** Section 3 of the same file: `az login`, set the four `OPENSTAGE_SIGN_*` variables, build with
  `--sign`, run `scripts/sign_windows.py --check`, look at Digital Signatures on a second PC. Only the owner can sign in; no program step
  can. The publisher name on the signature has to match the verified identity on the signing account.
- [ ] **WebView2 SDK licence text.** Copy Microsoft's licence for the WebView2 SDK (NuGet package `Microsoft.Web.WebView2`, licence page
  linked in `THIRD-PARTY-NOTICES.md`, "Still to do", item 8) into `third-party/licenses/webview2-sdk-LICENSE.txt` and into the build's notices.
  It was not copied by the build session because the text has to come from Microsoft, not from memory.
- [ ] **Licence recheck on release day** (`THIRD-PARTY-NOTICES.md`, items 3, 6 and 7) and counsel's review: unchanged from before, still open.

**The coverage matrix (list item 3)**

- [ ] **A person who knows WCAG and PDF accessibility reads `docs/WCAG-2.1-AA-COVERAGE.md`** and says whether any row claims more than the
  program does (the "Coverage" word for each criterion), or leaves a criterion out that matters to faculty. It was written from the code and
  the existing notes, not from a test of real documents.

**Phase 3 (list item 4; deferred until the owner says go)**

- [ ] **Owner's go-ahead**, in writing, for which of the three groups in `docs/PHASE3-TESTERS-AND-NEW-CHECKER.md` may start, and whether the
  ethics board needs to see the plan before any person is observed.
- [ ] **Real users:** three to five nontechnical people run the tasks and the facilitator fills in the sheet.
- [ ] **A screen-reader tester** works through the program's window and the original and candidate PDFs; the two scripted-only items near the
  top of this file are theirs to repeat.
- [ ] **The campus's new checker (spring change):** upload each frozen original and candidate to the old checker **before** the switch to get a
  baseline, then to the new one, with file SHA-256s; name the new checker and keep its published PDF checklist. Records stay outside the
  repository. No upload happens without the owner's say.

**The core (list items 5 and 6)**

- [ ] **Give `CORE-REQUESTS.md` to the core's session** (C2-1 to C2-3, C8-1 and C8-2). Nothing was built against the core in this round, because
  C2 is not published and C8 is not specified; the program kept its own contrast, language-tag and AI code.
- [ ] **Not done in this session:** the instruction to switch PrismQDA to the core's `prismqda-stats-v1.0.0` tag. PrismQDA is another
  repository and there is no copy of it on this PC under `C:\Dev` (only the core's crate), so it belongs to the PrismQDA session
  (`CORE-NOTES.md`, "For the PrismQDA session", item 1).

