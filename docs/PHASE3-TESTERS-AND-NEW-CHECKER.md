# Phase 3 kit: real users, a screen-reader tester, and the campus's new checker

**Status: prepared, not started.** `AGENTS.md` keeps actual-user, assistive-technology and LMS checker testing deferred until the owner
authorizes it. This file does not authorize anything and fills in no review state. It only makes the three kinds of testing ready to hand to
people, so that when the owner says go there is nothing left to write. The tasks themselves, the seeded defects and the way to bind a test
to exact file hashes are in `docs/ACCEPTANCE-TESTS.md`; the first limited scope is in `docs/PHASE3-PILOT.md`. Read those first.

What this adds: how to find and brief each kind of person, one place to write down what happened, and a plan for the change of checkers
that the campus is making in the spring.

Nothing here is a claim about what the program achieves with real people. No results exist yet.

## 0. Before anyone is asked

1. **The owner's go-ahead**, in writing, naming which of the three groups below may start.
2. **Ethics.** Watching people use the program and writing about it can need a research ethics determination at the owner's institution.
   Check before recruiting whether the board must see the plan, and what consent wording it wants. Do not collect names, recordings or
   documents beyond what that determination allows.
3. **A frozen build.** One installer, with its name and SHA-256 recorded (`Get-FileHash`), signed or not as it stands that day
   (`docs/FRESH-PC-AND-SIGNING.md`). Every observation belongs to that build. A new build means new observations.
4. **Documents.** Use the synthetic documents named in `docs/PHASE3-PILOT.md`, or documents the owner is entitled to share. Do not use a
   private document, a student's document or a licensed book without the rights holder's say. The seeded negatives in
   `docs/ACCEPTANCE-TESTS.md` stay labelled as test defects.

## 1. Real users (nontechnical people who would use it)

**Who.** Three to five people who prepare course PDFs or readings but are not developers: for example a faculty member, a teaching
assistant, someone who supports a department's materials. At least one person who has never seen the program, and at least one who works
with only a keyboard if such a person is willing. Do not recruit people who helped build it.

**What they do (about 60 minutes, one at a time, with a facilitator who may not help unless the person asks or is stuck for two minutes).**
Run the tasks in `docs/ACCEPTANCE-TESTS.md`, "Application usability and keyboard tasks", in this order: start the program; choose a PDF and
process it; read the result summary and say in their own words whether it is finished; open a review item and say what it asks of them;
edit one figure description; save, close and reopen; cancel a job; find the original and the result.

**What the facilitator writes down (one sheet per person; keep sheets apart from any name).**

| Field | Note |
|---|---|
| Person code, date, facilitator | no name |
| Build name and SHA-256 | |
| Computer, Windows version, screen size, input device | |
| Each task: done / done with help / not done | and the minutes it took |
| Every point where the person paused, asked, or went the wrong way | exact words |
| Their own account of "is this document finished?" | exact words; the program's wording is meant to say it is a draft |
| Seeded defects missed or caught (if tested blind) | |
| Anything the person said they would do differently | |

**Exit** (from the roadmap): a nontechnical user can set up, process a supported document, understand the review queue and complete the
documented review workflow. Count the number who could, not an average of how pleased they were.

## 2. A screen-reader tester

**Who.** An experienced person who uses a screen reader as their usual tool, not someone learning one for the test. The owner does not need to
own the software; the tester brings their own setup and says exactly which. Offer a fair fee or credit; agree it in advance.

**What they are asked to do (about two hours, split if they prefer).**

1. **The program's window.** Using only their screen reader and keyboard: start the program, choose a file, process, hear the progress,
   cancel, open a review, fix one field, use Home and Reset, close it. Say what was announced and what was silent or confusing. The
   dialogs, the progress bar, the Auto-fix line and focus after Home or Reset are named in `TESTING-TODO.md` and have only had a scripted
   pass.
2. **The remediated PDFs.** Open the original and the candidate for each document in the tester's usual reader. Compare: title and
   language announced, headings and the heading list, reading order, list and table navigation and header announcements, links (name and
   target), figure descriptions in their two contexts, form fields if any, the bookmarks, and whether any character is read wrongly.
3. **Say what they would do next**: could they use the document as a student? What did they have to work around?

**Record (one sheet per document):** reader and version (from its own About), screen reader and version, browser or app, Windows build,
build and file SHA-256, pages covered, each finding with page and a plain description, and which findings are in the program's list of
things it said a person must check. A finding the program did not flag is a missed defect; keep those as a list of their own.

**Rules for what the results may say.** A spoken-output pass on these pages is a pass on those pages with that setup. It is not
conformance, not "accessible", and not a pass for other readers. Do not infer anything from silence: an unrecorded check is "not checked".

## 3. The campus's new checker (spring change)

The campus is switching its accessibility checker for the spring term. The program's current record is built around the old checker's
published PDF checklist (`docs/LMS-CHECK-APPLICABILITY.md`) and says plainly that no result has been tested in either.

**Plan.**

1. **Before the switch, while the old checker is still available:** with the owner's authorization and for a course the owner may use,
   upload each frozen candidate **and its original** once, and keep the checker's own report for each: date, course context, file SHA-256,
   score or rating as shown, and every item listed. This is the baseline. Do this for the same files you will later test in the new checker.
2. **When the new checker is available:** upload the same original and candidate files again (same hashes). Keep the same fields.
3. **Name it.** The campus's name for the new checker and its version belong in the record as the campus states them; this file does not guess
   them. Keep a copy of its published PDF checklist (with the page address and date read).
4. **Map it.** Make a table with one row per rule in the new checker's published PDF list: the program's check, reviewed control or review
   item that relates to it (use `docs/WCAG-2.1-AA-COVERAGE.md` and `docs/LMS-CHECK-APPLICABILITY.md`), or "none". Rules with "none" are
   development items, not failures of the program's tests. Do not describe the program as matching, replacing or scoring against either
   checker.
5. **Compare** old and new results file by file, so a change is attributed to the checker and not to the document. For each confirmed
   defect: fix, produce a new file, and test again (a changed hash is a new file).
6. **Verified status** needs the product's own conditions (an exact candidate hash, completed required human reviews, and a qualifying
   checker result at the threshold the owner has chosen). Any threshold set for the old checker needs a fresh decision for the new one;
   do not carry the old number over.

**Record per upload:** file name and SHA-256; original or candidate; date and time; checker name and version as shown; course or context
(no student data); the full list of issues and the score or rating exactly as shown; who uploaded it; a screenshot of the report if the
owner allows. Keep these records outside the repository (`AGENTS.md`); put only the summary in `docs/STATUS.md`.

## 4. Where the results go

* `TESTING-TODO.md` lists each of these as a box with who and when. Tick a box only when it was done.
* The program's human-verification ledger records a named person's own review of a named file. A tester's findings are not entered for them.
* Findings that need a change become development items in `docs/STATUS.md`. A finding is never deleted because it was inconvenient.
* A summary of Phase 3 in `HANDOFF.md` should say how many people, which setups, which files, and what was found, without scores
  that were not observed.
