# Phase 1 product corpus trial

`run_phase1.py` calls the real `process_file` product API on all 15 original
synthetic fixtures with conservative processing defaults. It separately tests
one-page scan OCR skip, one-page mixed OCR redo, and explicit tag regrouping on
the 200-page synthetic book. It does not run or regenerate the public real book.

Slides and equations carry explicit `document_kind` declarations sourced from
the fixture manifest. This tests refusal of a declared unsupported document
type. It does not claim that arbitrary slide/equation content can be recognized.

Each case gets a separate output parent. The short `r/01` through `r/18` parents
reduce native Windows path depth; the observations and provenance retain the
full fixture identity. A fresh destination is required so earlier evidence is
not overwritten. Completed product bundles are immutable and independently
checked with `verify_bundle`.

The summary records all source hashes before and after, product source hashes
around each case, strict validator counts, all three candidate gates, pending
human review counts, output hashes, independent published-PDF structure checks,
and whether any PDF was published without a fidelity pass. Full product reports,
validator reports and progress are retained. Diagnostics and cache PDFs are
explicitly outside the published artifact count.

Two additional comparisons use the known `tagged-control.pdf` original:

* `deliberate-content-loss.pdf` must fail text and rendering comparison. When
  supplied by itself, the application cannot infer that an absent paragraph
  existed in a different, unavailable original.
* `mis-mapped-font.pdf` has an intentionally incorrect C-to-Z character map.
  Its rendering remains identical while extracted text differs from the known
  control. Standalone validator and syntax passes do not establish that spoken
  or extracted characters have the correct meaning. That remains a confirmed
  semantic problem in this evaluation and must not be called verified.

Run from the workspace:

```powershell
& 'pdf-remediator/.venvs/app/Scripts/python.exe' 'pdf-remediator/eval/run_phase1.py' --output 'pdf-remediator/output/phase1/corpus-next'
```

The trial exits nonzero if release invariants fail, source files change, or the
product implementation changes while the trial runs. An implementation change
requires a new complete trial after the code settles. Expected unsupported or
fidelity-failing fixtures are not harness errors when no unsafe PDF is published.

The initial `corpus-trial` run is retained as pre-audit evidence. It encountered
long native subprocess/Tesseract paths and detected a concurrent product code
change. Its mixed-version outcomes must not be used as final release evidence.

## Definitive recorded run

Final evidence is in `output/phase1/corpus-final/summary.json` and `summary.csv`.
The complete 18-case run exits successfully with every release invariant passed,
every source hash unchanged, no product code drift and all 18 bundles verified.
There are seven automated candidates and 11 manual-work results, with 13 total
published PDFs (seven candidates and six clearly labeled review drafts). Every
published PDF has a fidelity pass and independently verified intact content
structure; no phantom/broken PDF is published.

Both OCR routes complete with strict PDF/UA-1 and declared visible/original-text
preservation passes. They remain manual-work results because their figure
alternatives require explicit descriptions. Forms and declared slides/equations
produce reports without a PDF. Both synthetic-book configurations fail exact
fidelity and publish no PDF. The two known-original comparison failures match
their expected text/render outcomes.

The candidate count measures only the declared automated profile. In particular,
the intentionally reduced standalone file cannot reveal an unavailable original,
and the intentionally wrong but syntactically valid font mapping still requires
semantic review. Those fixtures are not presented as semantically correct or
verified examples.
