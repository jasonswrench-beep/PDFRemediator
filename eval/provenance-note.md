# Standalone validator provenance

Research date: October 15, 2026 (client date).

The official [1.30 release directory](https://software.verapdf.org/rel/1.30/) lists
**veraPDF Greenfield 1.30.3**, dated October 7, 2026. The precise archive is
[verapdf-greenfield-1.30.3-installer.zip](https://software.verapdf.org/rel/1.30/verapdf-greenfield-1.30.3-installer.zip).
Its detached signature has the same URL with `.asc` appended. The mutable
`/rel/verapdf-installer.zip` link and its directory listing can lag the pinned
directory. Record the downloaded archive hash and observed `--version` output;
do not infer the installed build from its URL alone.

The cross-platform ZIP includes a Java IzPack installer and Windows/Linux/macOS
launch scripts. [Official installation documentation](https://docs.verapdf.org/install/)
shows unattended XML installation. The [1.30.3 source README](https://raw.githubusercontent.com/veraPDF/veraPDF-apps/v1.30.3/README.md)
lists preinstalled Java 8, 11, 17 or 21 for installation. Evaluate the selected
runtime using a real smoke test; runtime compatibility is not demonstrated by a
PATH entry.

The [official CLI help](https://docs.verapdf.org/cli/help/) documents
`--flavour ua1`, `--format xml|json`, `--maxfailures -1`,
`--maxfailuresdisplayed -1`, `--processes 1` and `--version`.
[Validation documentation](https://docs.verapdf.org/cli/validation/) explains that
an explicit flavour restricts validation to the selected profile, and that XML
from release 1.24 onward is the machine-readable report format. The adapter
requires UA-1, complete rule/check counts, coherent batch/job summaries,
successful execution and the pinned build. Raw stdout and stderr are separate.
Missing, timed-out, malformed or contradictory reports are errors.

The [official Windows launcher](https://raw.githubusercontent.com/veraPDF/veraPDF-apps/v1.30.3/installer/src/main/scripts/verapdf.bat)
selects Java through `JAVACMD`, not `JAVA_HOME`. When given the installed
`verapdf.bat`, this adapter reproduces its Java classpath and wrapper invocation
with explicit argv and the selected runtime, avoiding an intermediate shell.
This still uses the installed standalone distribution. A separately supplied
CLI JAR is also supported; it must report the same pinned build. Java heap is
bounded, but this is not a total process-memory limit.

The official [exit-code enum](https://raw.githubusercontent.com/veraPDF/veraPDF-apps/v1.30.3/cli/src/main/java/org/verapdf/cli/CliConstants.java)
defines exit 0 as complete and compliant, and exit 1 as complete with conformance
failures. The adapter requires these codes to agree with a normal report; exit 1
can never become a pass. Other codes, inconsistent reports and interrupted jobs
remain errors. The actual 1.30.3 JSON report layout was confirmed against a real
validation and is parsed independently from its XML layout.

## Observed installation and verification

The root task supplied the archive. Its SHA-256 is
`b512bf24945503a33fc10738ecffc1f2dccaaf8593a448e94ee9ac86a9559a59`.
The detached signature was not verified; the official HTTPS origin and computed
hash are recorded. Installation was then authorized for this subtask and run
unattended under `pdf-remediator/tools/verapdf`, selecting CLI and documentation
only. No global PATH or Java configuration was changed.

The explicit existing Temurin Java 25.0.3+9 runtime successfully installed the
package and ran `--version`, `--list`, `--help`, and a real UA-1 validation in
both XML and JSON formats. This is observed compatibility on this machine;
Java 25 is outside the version list in the installation README. The chosen
runtime path and complete output are in `tools/verapdf-install-manifest.json`.
The installed CLI JAR SHA-256 is
`19f6edd5c92841a38d9b3b018a555b7ba173b13e4e0d29edecc232e5ba6c1d70`.
Each adapter result also records its executable/JAR hashes and the embedded
UA-1 profile hash.

The manual shipped with veraPDF was used solely as a local CLI smoke input,
not as an accessible known-good reference: both formats found **6 failed rules
and 86 failed assertions**, with normal job completion and exit 1. The initial
adapter smoke recorded exit 1 as an infrastructure error before its documented
meaning was verified; those initial logs remain under `tools/validator-smoke-*`.
The corrected, matching results are under `tools/validator-smoke-*-v2`.
Ten parser/execution checks under `tools/validator-parser-tests/results.json`
cover a coherent zero-failure report, wrong profile, interrupted job, missing
counts/rules/assertions, contradictory compliance, batch parse error, missing
input/validator, and timeout. The zero-failure case is an artificial parser
control, not evidence that an actual test PDF passed validation.

Once independent fixtures were available, a real control run of
`eval/corpus/tagged-control.pdf` passed with 106 passed rules, 427 passed checks,
zero failures and exit 0. `incomplete-tags.pdf` failed one rule/one assertion;
`phantom-tree.pdf` failed one rule/three assertions. Those completed with exit 1.
Evidence is under `tools/validator-control-checks`. The embedded UA-1 profile
SHA-256 is
`794c9f6bf53c8cb89e532807e74fea58331a0d9a935c52cb054b63853bdd8b2a`.
These machine checks do not establish semantic accessibility of the controls.

## Large-report detail coverage correction

The first adapter additionally assumed that every counted failed assertion must
have a separate listed `check` record. Larger Phase 0 books disproved that
assumption. Their reports completed normally with exit 1, coherent aggregate
counts and valid UA-1 results, but listed fewer individual failure details.

Inspection of the **installed pinned 1.30.3 JAR bytecode** established the cause:
`BaseValidator.processAssertionResult` increments the per-rule failure count,
then suppresses stored assertion details when `results.size() > 10000`, except
the first failure of a newly encountered rule. This internal global limit is
separate from `--maxfailuresdisplayed -1`. The disassembly is retained at
`tools/validator-BaseValidator.javap.txt`; its originating CLI JAR hash is recorded
above. Public source fetch attempts did not recover the corresponding Java
source file. An initial deduplication hypothesis was superseded by this direct
binary evidence.

Adapter schema `phase0.verapdf.2` separates aggregate rule/assertion results from
`assertion_detail_coverage`. A coherent noncompliant report stays **fail**, with
all original counts, all available listed details, and explicit partial-coverage
warnings. It cannot become a pass because failure details are incomplete. Missing
reports, abnormal jobs, wrong profiles, inconsistent counts, and a true compliance
flag with nonzero failures still produce errors. Passing still requires zero
failed rules/checks and the original process, version and hash checks.

Five affected active summary files were reparsed from unchanged saved XML; no
engine or validator was rerun. Their exact former summary bytes are preserved
beside each file using the `.pre-detail-coverage-fix` suffix. The full record is
`eval/evidence/validator-detail-coverage-refresh.json`. Eight new XML/JSON parser
regressions passed in `eval/test_validate.py`. The earlier ten-check record
documents the previous adapter behavior; its expectation that missing individual
failure detail must be an infrastructure error is superseded by these tests.

Historical repository recovery was attempted read-only through the web tool at
an earlier test repository of the owner's, one of its work
branches, the corresponding raw README, and the public
branch API URL. The web tool returned cache/fetch/access errors and search found
no indexed match. Those initial web attempts did not establish availability.
Subsequently, desktop Git access resolved the branch and recovered a clean sparse
checkout at commit `df20503a1fc2c28f66a316268b443c1f22917a49`.
The original notes and three PoC scripts were recovered; all three supplied
documents match their pinned Git blobs. No historical input/output PDFs, raw
reports, dependency lock or license file are tracked in that commit. No
historical code was executed or incorporated, and no historical benchmark
numbers are treated as reproduced evidence. The recovery manifest and notes are
in `eval/evidence/historical-recovery.json` and `historical-recovery.md`.

No proprietary tagging SDK, paid API, cloud document processing or external mutation was performed
by this subtask.
