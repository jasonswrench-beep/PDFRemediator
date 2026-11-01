# Things only a person can check by hand

Everything a program can check is checked by tests (see `tests/` and `scripts/test-web-assets.cjs`). This list holds only what
needs a human: judgement, a real assistive technology, or a computer that is not this one. Tick a box and add the date and who did it when it is done; do not
delete a line that was never checked.

Last updated 2026-10-31 (late).

## Test runs on an unstable computer

Some computers (for example ones with a degraded processor) make plain Python crash at random: "access violation" errors, odd errors that cannot happen in correct code,
or a failure that never comes back. If a test fails once and passes on a rerun, suspect the computer first. `python scripts/run-tests-by-file.py` runs every test file in its own
process and retries a crashed one. Limiting the process to the stable cores (for example `psutil.Process().cpu_affinity([...])`, children inherit it) gave clean runs on such a machine.
The full suite is expected to end with only the environment failures listed below.

## Screen readers and keyboard (a person with a screen reader should do these)

- [ ] **New dialogs with NVDA/Narrator.** (A scripted NVDA pass on 2026-11-01 found both dialogs announced correctly with the right focus and Escape behaviour; this is still for a person to repeat, and for Narrator.) Open Processing options and tick "Rebuild a missing letter dictionary by reading each page": the dialog should be announced with its title and
  text, focus should land inside it, and Escape should return to the box unticked. In a review, change a field without saving and press "All documents": the "Leave this review without saving?"
  dialog should be announced with "Stay and keep editing" focused.

- [ ] **Status bar and Auto-fix line.** With NVDA, Narrator or JAWS: start a scan and listen. The step should be spoken when it
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
- [ ] **A PC without Microsoft Edge.** The window should open in Google Chrome, or in the default browser if neither is there.
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
