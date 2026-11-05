# Phase 3 pilot — limited Windows visual scope started

On October 17, 2026, the owner authorized and performed a limited local Windows
visual/usability trial in the desktop PDF viewer, without a screen reader. Source and
candidate looked the same to the owner; copied text exposed joined words at two
paragraph line boundaries. This is a finding, not accessibility acceptance.
The owner subsequently confirmed that the separate bounded experiment retained
appearance and corrected both clipboard boundaries. See
[Windows pilot continuation](WINDOWS-PILOT.md) for the record and remaining scope.
Assistive-technology acceptance and the LMS accessibility checker testing remain deferred.

The broader human-dependent milestone is the existing roadmap's actual-user,
assistive-technology, and the LMS accessibility checker acceptance. AGENTS.md requires owner
authorization before those trials. Native synthetic passes do not waive it.

Detailed tasks, seeded controls and evidence-binding instructions are prepared
in [ACCEPTANCE-TESTS.md](ACCEPTANCE-TESTS.md). That document does not authorize
execution or fill any review state. The fresh normal-application Windows
visual/clipboard retest is also complete, as recorded in the Windows pilot.

## Proposed first scope for approval

Start with the one-page reading and one-page two-figure control from the Linux
review packet. Both are original synthetic material. The packet includes their
sources, candidates, exact SHA-256 hashes, font notice, and current automated
results. Include the 200-page book only if the owner chooses the larger review
scope; spot checks cannot complete all 1,234 pending reviews.

1. Ask the owner to approve this limited pilot and identify the actual tester,
   operating system, PDF reader and screen reader. Record their real versions.
2. Have the tester compare source and candidate visually and with their normal
   reading tools: all text, title/language, reading sequence, each figure's
   occurrence-specific description, navigation, and any reported blockers.
   Record actual actions/findings and effort; do not infer success from silence.
3. Test the application's local review workflow only on an explicitly prepared
   local installation or a separately approved authenticated preview. Keep the
   cloud review server on loopback; do not expose it for this pilot. Record
   usability separately from PDF/assistive-technology results.
4. If the owner has an authorized Canvas course with the LMS checker and explicitly approves
   upload, the owner uploads each exact candidate and records the actual the LMS checker
   score, feedback, course/context, date and candidate hash. No credentials or
   institutional/private material belong in Git. No upload occurs by default.
5. Bind genuine named human reviews to the exact artifact. Keep all unperformed
   checks pending, resolve confirmed blockers, and revalidate any changed PDF.
   A changed hash invalidates earlier artifact verification. Use the existing
   verification ledger only after every required review and qualifying actual
   the LMS checker result meet the product's established policy.

## Review record

Capture: artifact name and SHA-256; tester/reviewer and date; OS/reader/screen
reader versions; exact review scope/pages; actual observations and blockers;
completed versus pending checks; original/candidate comparison; actual the LMS checker
score/context if tested; and the final disposition. No automatic value is a
named human approval. No untested result receives a score, pass, or verified label.

## Stop conditions

Stop for changed source/candidate hashes, an unresolved confirmed blocker,
missing reviewer authority, inaccessible tooling, or an unavailable/unauthorized
Canvas course. Do not fill those gaps with automatic approvals, simulated
screen-reader results, invented the LMS checker feedback, or relaxed preservation gates.

Approval of this plan would authorize only the specified synthetic pilot, not a
broader user study, private document upload, public server, deployment, merge,
or general accessibility claim. All those boundaries remain in place.
