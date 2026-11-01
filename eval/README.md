# Phase 0 Evaluation

This folder contains the feasibility harness and evidence. It is not the Phase 1 PDF Remediator product.

Start with `RESULTS.md`, `ACCEPTANCE.md`, `CORPUS.md`, and `runs/phase0-20261015/summary.csv`. The authoritative per-case records are each engine/fixture's `evaluation.json`; raw PDFs and validator reports are retained beside them. Originals are never overwritten.

## Reproducing the run

Use Windows and Python 3.11 for the recorded dependency locks. From the `pdf-remediator` directory, create separate environments under `.venvs/eval`, `.venvs/odl`, `.venvs/accesspdf`, and `.venvs/ocr`. Install the corresponding `eval/evidence/*-requirements.lock.txt` in each environment. These locks include the observed package installer version; the environments were checked with `pip check`.

Install standalone veraPDF 1.30.3 under `tools/verapdf` using the archive/source recorded in `eval/provenance-note.md`. Set `PHASE0_JAVA_HOME` to a verified Java installation if it differs from the recorded machine path. The harness passes Java directly, with a 2 GiB heap cap. Place the documented Tesseract distribution and English model under `tools/tesseract`; OCR uses a project-local temporary directory by default.

The exact observed archives/model URLs and fingerprints are recorded in the environment and provenance records. Downloaded hashes identify the observed files; independent publisher-signature verification was not performed. Do not distribute the entire tools folder without reviewing its individual licenses.

Generate a fresh synthetic corpus:

```text
.venvs/eval/Scripts/python.exe eval/build_corpus.py --output eval/corpus-new
```

The recorded harness reads `eval/corpus/manifest.json`. Inspect a new corpus and explicitly select its path in the harness before a new comparison; do not silently replace or edit an evidence corpus. Keep the publisher's unchanged real-book PDF at `eval/external/thinkpython2.pdf`, with its attribution and fingerprint, or explicitly configure another permitted input.

Run the final metrics and parser regressions:

```text
.venvs/eval/Scripts/python.exe -m pytest eval/test_metrics.py eval/test_validate.py -q
```

Run the engines into a **new** evidence directory:

```text
.venvs/eval/Scripts/python.exe eval/run_eval.py --run phase0-reproduction
```

The default comparison is both engines and all manifest fixtures plus the published book when present. `--fixtures simple_embedded,structured_chapter` limits a diagnostic run. `--engines opendataloader` selects one engine. `--resume` requires matching input, acceptance criteria, and implementation fingerprints. The original recorded run predates implementation-fingerprint capture and subsequent inspector/parser corrections; use a new run directory rather than resuming that historical run with the final harness.

Run a new OCR experiment without overwriting prior results:

```text
.venvs/eval/Scripts/python.exe eval/ocr_spike.py --root eval/spikes/ocr-new
```

`artifact_spike.py` and `font_spike.py` document their bounded controls and produce separately retained outputs. Their recorded result folders already exist; do not rerun into them. The compatibility OCR launcher is retained as unsuccessful troubleshooting evidence and is not needed by the successful stock route.

## Evidence map

| Location | Contents |
|---|---|
| `corpus/manifest.json` and `corpus/qa/` | Synthetic ground truth, hashes, anchor checks and rendered visual checks |
| `external/PROVENANCE.md` | Published book source, license, attribution and fingerprint |
| `evidence/environment.json` | Runtime inventory, dependency locks and package consistency results |
| `evidence/baseline-validation/` | Strict validator results for original inputs |
| `evidence/baseline-inspection/` | Original structural/font/navigation measurements |
| `runs/phase0-20261015/` | 32 engine cases, raw and normalized outputs, logs, measurements and summaries |
| `spikes/artifacts/` | Successful exact-decision artifacting and shared-resource refusal |
| `spikes/fonts/` | Exact-source font/mapping restoration and explicit fidelity differences |
| `spikes/ocr/` and `spikes/ocr-compat/` | Failed default-temp experiments and successful unmodified local-temp OCR |
| `evidence/source-manifest.json` | Final implementation fingerprints and correction provenance |
| `evidence/historical-recovery.json` | Verified original branch commit, recovered notes/scripts and missing historical inputs |

The checks intentionally report their limits. Semantic order, description quality, difficult OCR accuracy, complex table meaning, contrast and complete WCAG coverage are not automatically established. No evaluation label is a product candidate or a human verification record.
