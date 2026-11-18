# History rewrite of 2026-11-17

On 2026-11-17 the owner ordered the repository's history rewritten once, and it was force-pushed the same day. This page records what changed,
what did not, and how to match an old commit hash to a new one.

## What changed

- **Author and committer.** Every commit now has one identity as author and as committer:
  `jasonswrench-beep <324576087+jasonswrench-beep@users.noreply.github.com>`. Five of the 25 commits had been made under another name or address;
  a personal e-mail address was in the public history in one of them.
- **Trailer lines.** 14 commit messages ended with a `Co-Authored-By` trailer. Those lines were removed; nothing else in any message changed.
- **Hashes.** Every commit hash changed, because a hash covers the author, the message and the parent. The table below maps each old hash to its new one.
- **Tags.** All ten release tags (`v0.3.0-alpha.1` to `v0.3.0-alpha.10`) were moved to the matching new commits. This is a one-time exception to the
  rule that a pushed tag never moves (see `CLAUDE.md`). Alpha 9 and alpha 10 are still annotated tags with their original messages; the others are still lightweight.
- **Release notes.** The "Built from" line in each of the ten release notes now names the new hash and the old one.
- **The Dependabot branch** `dependabot/pip/eval/evidence/pip-5c96377ebe` was deleted because it was built on the old history; its pull request (#2) closed with it.

## What did not change

- **The files.** All 25 trees are byte-identical to the originals, checked by comparing every commit's tree hash. Dates and commit subjects are unchanged.
- **The installers.** The ten installers attached to the releases were not rebuilt or touched. The update check compares version numbers and tag names, not commit hashes.

## What the rewrite could not fix

- **Alpha 8, alpha 9 and alpha 10 were built before their commits were made.** The installer files are dated about 2 minutes, 1 minute and 33 minutes
  earlier than the commits their tags name, so the tag was not set before the build. The program source bundled in each installer matches its tagged
  commit's `src/` folder file for file (one file differs only in line endings). The release notes for those three say so. The rule that a release tag
  is set before the build (`CLAUDE.md`, rule 3) applies from alpha 11 on.
- **Alpha 1** names a commit (`2e9dfe58737ffc07e317c54fd77d3e58fee63af7`) that is not in this repository's history; its tag points at `7152b90`.
- **GitHub keeps old objects for a while.** The old commits can still be fetched from GitHub by their hash, and the two closed or deleted Dependabot
  pull requests keep references to them. Only GitHub can remove those; the owner asks GitHub Support to do it.

## Updating another copy of the repository

If a copy holds no work that is not on GitHub: `git fetch origin --force --tags --prune`, then `git reset --hard origin/main`. Otherwise clone again.

## Old hash to new hash

| Old commit | New commit | Subject |
|---|---|---|
| `18bf164` | `bc8d10d` | PDF Remediator: first public commit |
| `23e60a7` | `59c06f4` | Review page: OCR evidence in plain words; a silent service exit now leaves a trace |
| `5f4df7d` | `7152b90` | Installer: put a PDF Remediator icon on the desktop and in the Start menu (tick box, on by default) and offer to open it |
| `4e60ef8` | `152bafd` | Add public roadmap and feature request link |
| `8094c6c` | `cf6f469` | Describe product capabilities without external comparisons |
| `c0f0faf` | `8c02aba` | Use generic names for outside accessibility checkers |
| `299d9d9` | `56679d3` | Sign the Windows package with Azure Artifact Signing (package-windows.py --sign) |
| `cfc0be6` | `ba378b8` | Installer and START-HERE: plain words instead of the old internal-trial text |
| `6e2d94f` | `c9b17e2` | Windows installer: a standard NSIS setup like the other suite apps |
| `cf7c870` | `3ae80c6` | Uninstaller removes only the shortcuts that start its own copy |
| `4505810` | `da50d18` | Distribution notes: the uninstaller keeps shortcuts to other copies |
| `f73f3e0` | `7e7c834` | Installer: the size in Settings > Apps counts the files in subfolders |
| `e7b31a5` | `49febd2` | Program window: PDF Remediator opens in its own window instead of Edge |
| `99eff52` | `b761502` | Security review fixes: installer folder check, OCR temporary files, pinned tools |
| `2f27bad` | `37ff315` | Check for updates: a button that says whether a newer version is published |
| `6062bde` | `fbbbce0` | Installer: remove an older version's files quickly in a visible setup |
| `06271cf` | `92d79f3` | Development-list round: colour-only, character and logo/OCR reviews, WCAG matrix, core requests; alpha 8 |
| `ddf0c75` | `d733db1` | Colour review: list chart-like shapes the program itself marked as artifacts |
| `bb7112e` | `2a6ce5e` | Release 0.3.0 alpha 9: colour-card fix, built and signed |
| `bca1eed` | `45b6574` | Installer signing: keep a program's makers' signature even when it no longer validates |
| `d5aafb6` | `4e0b753` | Notes: alpha 9 install-over-alpha-8 results and the Tesseract signature defect |
| `e17bc7e` | `1819426` | Release string 0.3.0-alpha.10; notes on the built, unpublished alpha 10 |
| `e68d5ec` | `6335785` | Add scripts/check-three-scans.ps1: three scans at once against an installed copy |
| `799dd53` | `9614ddb` | Notes: alpha 10 published as a pre-release, fresh-install test still open |
| `65f8fad` | `31b2886` | Add CLAUDE.md: standing rules for commit identity, attribution and release order |

| Tag | Old commit | New commit |
|---|---|---|
| `v0.3.0-alpha.1` | `5f4df7d` | `7152b90` |
| `v0.3.0-alpha.2` | `299d9d9` | `56679d3` |
| `v0.3.0-alpha.3` | `cfc0be6` | `ba378b8` |
| `v0.3.0-alpha.4` | `f73f3e0` | `7e7c834` |
| `v0.3.0-alpha.5` | `e7b31a5` | `49febd2` |
| `v0.3.0-alpha.6` | `99eff52` | `b761502` |
| `v0.3.0-alpha.7` | `6062bde` | `fbbbce0` |
| `v0.3.0-alpha.8` | `06271cf` | `92d79f3` |
| `v0.3.0-alpha.9` | `bb7112e` | `2a6ce5e` |
| `v0.3.0-alpha.10` | `e68d5ec` | `6335785` |
