# Checked updates for an existing local source installation

`scripts/update-local-source.py` replaces the former manual wildcard copy recipe.
It is an offline, Python 3.11+ standard-library tool for an existing editable
installation. It updates only `src/pdf_remediator`; it does not install Python,
dependencies, Java, veraPDF, OpenDataLoader, models, launchers or configuration.
Project metadata must match byte-for-byte. Use the normal installation workflow
when dependencies or packaging change. No automatic background update is added.

Use only a source ZIP obtained from the owner's trusted private repository in
an authenticated browser. File hashes establish inspection/copy integrity; this
tool does not authenticate a publisher or make downloaded code safe to trust.
Do not paste private codeload URLs or browser session tokens into commands/logs.

## Check before applying

1. Stop the local application with Ctrl+C in its server window. Keep it closed
   through the update. The updater's lock excludes other updater processes; it
   cannot stop or reliably detect every running server/editor.
2. Download the chosen development source ZIP through GitHub. Keep that ZIP.
   Extract it to a new folder to obtain `scripts/update-local-source.py`.
3. Use the existing application's Python to run the script from the extracted
   folder. Supply the original ZIP and the existing checkout explicitly. The
   following paths are examples; replace the extracted folder and ZIP paths
   with the actual selected download, not a guessed wildcard match.

```powershell
& "C:\Users\Jason\PDFRemediator\.venvs\app\Scripts\python.exe" `
  "C:\path\to\extracted\scripts\update-local-source.py" `
  --archive "C:\path\to\trusted-source.zip" `
  --target "C:\Users\Jason\PDFRemediator"
```

Default mode does not write to the installation. A successful check prints JSON
with `status: checked-not-applied`, archive/package hashes and a file count.
Refusal exits nonzero and prints no success JSON. Fix the reported issue before
continuing. Shell automation must check `$LASTEXITCODE`; wrapping a complete
PowerShell sequence in `& { $ErrorActionPreference = "Stop"; ... }` prevents
independent pasted statements from continuing after a PowerShell error. Native
program exit codes still need an explicit check.

When ready, rerun the same command with `--apply` at the end. That invocation
repeats inspection, stages the complete new package under ignored `work/`,
compiles Python syntax without importing the application, checks every staged
file hash, and checks the original installed package has not changed. It moves
the original package to a unique `work/code-backup-*` path, replaces the package,
and compares every installed file hash. Old bytecode is retained in the backup
and does not enter the new package. Only a verified replacement prints
`status: applied`, the backup path, and `restart_required: true`.

The existing Python environment, local runtime TOML, PDFs, generated results and
review states are outside this replacement. They are not copied, rewritten or
merged. Local edits to application code are retained in the complete backup;
the installed code is replaced with the selected source package. Source changes
still invalidate preparation caches through the application's implementation
digest; preserving review files does not waive revision/provenance checks.

## Refusal and recovery boundaries

The tool refuses absent/incomplete archives, unsafe or nonportable paths,
Windows device names/streams, symlinks/special entries, duplicate/case-colliding
entries, unexpected package artifacts, oversized contents, changed project
metadata/dependencies, incompatible Python syntax and linked checkout paths.
Python 3.11 Windows reparse attributes are checked without depending on the
Python 3.12 junction API. Archive and installed-file changes between inspection
and replacement are also checked.

Catchable errors during replacement trigger rollback and full hash verification
of the previous package. The tool reports rollback success as a refusal, never
as an applied update. If rollback fails, it explicitly says to keep the app
closed and reports installed, backup and displaced-package recovery locations.
Inspect which locations exist; a failed rollback verification may have already
restored the original directory without establishing its expected hash. Do not retry as administrator,
blindly remove a lock, or copy a drive-root wildcard. Retain the backup and
failed staging material for diagnosis. Hard termination, power loss, hostile
concurrent filesystem changes, and unavailable/damaged disks are outside the
rollback guarantee. After an interrupted process, confirm its state and inspect
its unique backup/staging directories before manual recovery.

## Verification status

The source-only tests create deterministic ZIPs and isolated synthetic checkout
trees. They cover whole-package integrity, protected local data, changed inputs,
archive refusal, locking, interrupted renames, corrupt copies, rollback and
rollback failure. A real repository `git archive` was also checked and applied
to an isolated Linux copy, without importing the application or running native
PDF tools. On October 18 the owner also ran all 41 updater contracts within passing
Windows suites and exercised real-package dry-run/application on a disposable
Windows copy: all 32 package files verified, the old package was retained and a
local configuration sentinel stayed unchanged. This is bounded actual Windows
happy-path evidence; deliberately denied native replacement/recovery and broader
installer qualification remain separate. The working installation was not
replaced, and the earlier manual update/the desktop PDF viewer pilot is not used as updater proof.


### October 19 disposable Windows installation and sharing-denial checks

At validation commit `9d857fa`, seven real-package updater cases passed in
7.687s on disposable Windows copies. Actual non-delete-sharing directory handles
produced WinError 32 during original replacement, staged replacement, and staged
replacement plus rollback. The original package remained intact in the first
case; the second rolled back with every prior hash verified. The terminal case
explicitly refused success and retained recovery locations. After releasing the
trial handles, a verified fresh copy of the retained backup restored that
disposable installation; retry then applied and verified the complete package.
The full baseline, source ZIP, synthetic original/configuration/review/environment
sentinels and recovery evidence were preserved. The process was not an
administrator; no ACL changes, mocked updater errors or elevation were used.

Seven separate bounded installation/startup checks also passed, including a fresh
editable environment, dependency/entry-point checks, explicit-config native
readiness, and authenticated private-service startup/shutdown. The setup helper
does not load `local-runtime.toml` for its readiness check: external configured
tools alone yielded a candid incomplete-defaults result; supplying the already
reviewed tool copies at the disposable default paths made setup complete.
This is prepared-computer evidence, not a complete cross-machine installer.

Full local reports and corrected harnesses are retained under ignored
`work/windows-install-update-1792448885617/`; see HANDOFF.md for exact commands,
hash/preservation scope and earlier harness-attempt limits. Actual ACL-denial,
power-loss, unavailable/damaged-disk, browser/keyboard and human accessibility
acceptance remain separate. No working installation/reviews were replaced and
no merge or release occurred.


### October 19 setup runtime-selection correction

The setup configuration limitation in the preceding checkpoint is now corrected
in the validation checkout. `Setup PDF Remediator.cmd` supplies the quoted local
`local-runtime.toml` path to its readiness check when present. Missing config
retains default behavior; invalid config or unavailable required native tools produce
failure without fallback. All 12 fresh disposable Windows installation/config
checks passed in 62.141s, including selected external paths with no default
tool copies, spaces/unrelated working directory, malformed/missing-validator
refusals despite ready defaults, missing-config fallback, and private installed
startup/shutdown. Existing originals/reviews and trial sentinels were preserved;
AI/OCR stayed off. Full local evidence is under ignored
`work/windows-setup-config-1792449672174/`.

This root setup-helper correction is not delivered by the source-only updater,
which intentionally updates only `src/pdf_remediator`. No updater production code
changed or denied-update cases were rerun for this setup-only fix. Earlier
recovery findings and wider qualification limits remain as recorded above.
