# Bounded Linux native reproduction

The original bounded reproduction recorded **603 source-only passes**, no skips.
The current runner remains `.venv/bin/python scripts/test-cloud.py`; see
[STATUS.md](STATUS.md) for the newer development counts. It needs no native tools, licensed
AMS archive, model or OCR service. Its private loopback protocol fixtures require
socket permission. It explicitly excludes `tests/test_native_tools.py` and
`tests/test_fonts.py`; these are not silently skipped or claimed as passing.

That original prepared complete scope (`tests`, `eval/test_validate.py`, and
`eval/test_metrics.py`) passed **616 tests** with real native JAR identity and
an explicitly supplied, pinned AMS archive. Real validator/pipeline trials are
separate from those unit/integration tests.

## Provision from reviewed archives

The owner supplied both public ZIPs after the cloud proxy denied their hosts.
No policy bypass, private PDF transfer, or model download was used. The native
setup script accepts only the reviewed archive hashes:

| Artifact | SHA-256 |
| --- | --- |
| veraPDF 1.30.3 installer ZIP | `b512bf24945503a33fc10738ecffc1f2dccaaf8593a448e94ee9ac86a9559a59` |
| AMSFonts 3.04 ZIP | `aaab3930b952128b7ed65260144493eb3d88cb063b50da1f90272e23c7e08ba2` |
| Installed veraPDF CLI JAR | `19f6edd5c92841a38d9b3b018a555b7ba173b13e4e0d29edecc232e5ba6c1d70` |
| ODL 2.5.13 JAR | `48ed84b5bf28e6ba82b8f37771fa5604b1f864bf529543910c8825a68965210c` |

The validator archive matches the historical recorded hash. Publisher signature
verification was not performed. Its observed license is GPLv3/MPLv2 or later;
AMS Type1 programs are SIL OFL 1.1 (the package README also covers LPPL material).
Keep distributions and font notices local. No third-party binary enters Git.

With application/test dependencies already installed, use an isolated ODL
package and an explicitly selected Java runtime. The tested runtime is OpenJDK
21.0.12.1; the example Java location is specific to this container.

```sh
python3 -m venv .venvs/odl
.venvs/odl/bin/python -m pip install opendataloader-pdf==2.5.13
.venvs/odl/bin/python -m pip check
.venv/bin/python scripts/setup-native-linux.py \
  --validator-archive work/downloads/verapdf-greenfield-1.30.3-installer.zip \
  --amsfonts-archive work/downloads/amsfonts.zip \
  --java-home /usr/lib/jvm/java-21-openjdk-amd64 \
  --odl-jar .venvs/odl/lib/python3.12/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar \
  --output work/native-linux-tools-new
```

Use the actual locations of the reviewed uploads. The output must be new. The
script validates archive hashes and paths, installs CLI/docs only, copies the
AMS ZIP locally, and writes explicit `runtime.toml` paths with OCR off. It does
not change global Java/PATH, download tools, or imply qualification.

## Synthetic licensed font controls

`eval/build_type1_control.py` replaces the published-book font dependency with
original two-symbol test content and unchanged, full AMS CMSY10/CMEX10 programs.
PFB transport segments are unwrapped without rewriting the actual Type1 bytes.
The PDF retains built-in Encoding and deliberate missing mappings at codes 55
and 113. Each program, the archive, and OFL notice are hash-pinned; missing or
changed assets fail before PDF creation. The generated assets and OFL notice
stay beside local fixtures. The reserved font programs are not modified.

```sh
PDF_REMEDIATOR_AMSFONTS_ARCHIVE=work/native-linux-tools-new/amsfonts.zip \
  .venv/bin/python -m pytest -q tests/test_fonts.py
```

All **12 cases** passed, retaining the original mapping, existing-mapping,
source-lineage, unsupported-encoding, fidelity and output-protection assertions.
New cases cover byte reproducibility, exact embedded program bytes, and refusal
of a changed archive before any PDF/font output. These are narrow two-symbol
mapping contracts, not general font restoration or mathematical acceptance.

## Real native contracts

A lightweight tagging/preservation preflight remains available as
`scripts/probe-native-linux.py`; it deliberately does not invoke a validator.
For real strict-UA-1 and all-page checks, use:

```sh
.venv/bin/python scripts/qualify-native-linux.py \
  --config work/native-linux-tools-new/runtime.toml \
  --output work/native-trial-new --include-book
```

Every output path must be new. Missing tools and failed expectations are errors,
not skips. AI/OCR are off. The runner uses real ODL, veraPDF and PDFium; it does
not replace validator, preservation or pipeline functions with test stubs.

Observed results on the pinned Linux runtime:

| Control | Result |
| --- | --- |
| Original tagged control | Candidate; all real gates pass |
| Untagged one-page reading through ODL | Candidate; all real gates pass |
| Phantom and incomplete tags | Strict/supplemental failures; no PDF published |
| Two figures without descriptions | Needs manual work; labeled review draft only |
| Four-page structured chapter | Strict/fidelity pass; semantic blocker; review draft only |
| Interactive form | Early unsupported refusal; no validator run or PDF publication |
| Authored automatic two-figure descriptions | Candidate; all real gates pass, human review pending |
| Changed preparation settings with accepted decisions | Refused before application; no PDF published |
| Deliberate text loss and wrong CMap | Independent fidelity detects both; wrong CMap retains pixels |
| 200-page book, default settings | Fidelity fails; no PDF published |
| Book with explicit tag regrouping | All-page fidelity passes; descriptions still unresolved |
| Regrouped book plus authored automatic descriptions | Candidate; strict, supplemental and 200-page fidelity pass |

The fresh October 17 readiness run used the unchanged application tree inherited
from `4e1d7bf`, with implementation digest
`dae55441edf57508e37ca4ab5bd428224e5b1ad1c80aca5bbc6e740822615727`.
It ran the full command with `--include-book` into the new ignored directory
`work/readiness-native-book`: 11 named case contracts plus two independent
negative fidelity controls passed. No native dependency was skipped.

The book candidate passed 106 strict rules and 678,858 checks with zero failures.
All **1,234 human-review items**, including **1,224 regrouping records**, remain
pending. Authored fixture descriptions are recorded as automatic choices with
an explicit deterministic-fixture origin, not model inference or human approval.
The runner asserts exact source/output/gate bindings, unchanged originals,
immutable coherent bundles, no external document API calls, and pending human
reviews. Default rendering defects and stale preparation settings remain refusals.

This is bounded native Linux evidence for the named synthetic cases. It does
not establish general document support, OCR, arbitrary font repair, model
quality, actual-user success, assistive-technology acceptance, the LMS accessibility checker scores,
or verified accessibility. A candidate is not verified. The owner completed a
limited Windows reading/the desktop PDF viewer visual and clipboard pilot; broader usability,
assistive-technology and the LMS accessibility checker acceptance remain deferred. See
[the current checklist](STATUS.md) and [acceptance scope](PHASE3-PILOT.md).

## Fresh 200-page timing and resource observations

These are single-run observations on the prepared Linux runtime, not benchmarks
or a Windows performance promise. Each row processed/compared all 200 pages.

| Route | Pipeline time | Result | Output bytes | Largest recorded native subprocess-tree RSS sample |
| --- | --- | --- | --- | --- |
| Default settings | 15.9405 s | Fidelity fails; no PDF published | 0 | 561,881,088 |
| Explicit tag regrouping | 15.8314 s | Fidelity passes; review draft pending descriptions | 746,301 | 626,475,008 |
| Regrouping plus authored automatic descriptions | 11.7961 s | Candidate; every gate passes, human review pending | 746,364 | 626,475,008 |

The final route adopts the prior exact preparation checkpoint; its recorded
processor provenance includes earlier preparation resource samples. These RSS
values are the largest native subprocess-tree samples recorded in each route's
provenance at the existing 0.05-second interval. They are neither a measurement
of the whole Python pipeline's peak memory nor an OS allocation guarantee.
Pipeline times are the reports' measured `timings.total_seconds`; they include
that route's processing work and are not a fresh-engine-only comparison.

Synthetic book source SHA-256:
`022cfed5756a119c357ab147358e16b40f8226dfcd134ad6cc12784e9d6387fd`.
Fresh final candidate SHA-256:
`2d58fc9ca39133ec6d370a18052f0aa462c4dd922b53a0703bab8673d957bd1c`.
The default source remains unchanged, the default fidelity refusal remains in
place, and all 1,234 human items (1,224 for regrouping) remain pending in the
explicit candidate. Fixture-authored captions are automatic values with no model
requests or human approval. No performance threshold or preservation tolerance
was relaxed.


## Reproducible native review lifecycle

With the reviewed native tools explicitly configured and the application/test
packages installed, a source checkout can reproduce the complete bounded review
trial without historical scratch scripts or private PDFs:

```sh
.venv/bin/python scripts/qualify-review-lifecycle.py \
  --config work/native-linux-reproduced-tools/runtime.toml \
  --output work/review-lifecycle-new
```

The output must be a new directory under this checkout's ignored `work` tree.
An existing directory, unsupported platform, OCR mode or expanded repair policy
is refused before generating inputs. Missing native prerequisites produce a
failed summary and nonzero exit; nothing is silently skipped. This trial is
Linux-specific and does not establish Windows support.

Seven named checks cover a generated one-page candidate, deliberately absent
validator refusal, retry with the corrected runtime, accepted synthetic title
application, saved-review reconstruction, a later human edit preventing result
attachment, and queued retry cancellation. Real candidate gates and exact hashes
are checked. Doctor information, font provenance, immutable bundles and summary
remain local. No browser, model call or OCR is used. Synthetic acceptance labels
are authored fixture values; human verification remains false.

The source-only regression suite separately checks the trial's prerequisite and
output-refusal behavior. These contracts do not substitute fake successful native
results or run a tool when it is missing. The consolidated diff and remaining
qualification requirements are in [RELEASE-READINESS.md](RELEASE-READINESS.md).
