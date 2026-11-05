# Licence and redistribution review (draft for Jason's decision)

Written 2026-10-30 by Claude. **This is a working checklist, not legal advice and not a clearance.**
Nothing here selects a licence for the application or declares anything cleared; the package's own `redistribution_cleared: false`
stays as it is until you decide.

How each fact was established (marked in the tables):

* **[file]** read from a licence or notice file that ships in the 0.3.0 trial package (`pi27-01/app`) or in this repository.
* **[web]** checked against a public source on 2026-10-30 (sources at the end).
* **[knowledge]** my general knowledge of that project's licence, **not** confirmed today. Confirm it from the project's own page
  when the notices file is assembled.

## In plain words

You give copies of this program away as part of the OpenStage suite, and the installed program carries other people's software
inside it. Each of those has terms. Reading them all:

**Good news**

* Nothing bundled forces PDF Remediator itself to be open source, nor stops you giving it away free. Every piece is either
  permissive (MIT, BSD, Apache) or a "weak copyleft" licence that covers only that piece's own files (MPL, LGPL, CDDL, GPL with the
  Classpath or GCC exception).
* No fees, registrations or paid licences are needed anywhere. (Publisher code-signing is a separate question and is not a licence.)
* None of the troublesome extras is inside: **no Ghostscript** (AGPL), **no unpaper, pngquant or jbig2enc**, no proprietary tagging SDK or accesspdf.
  I searched the runtime for them and found none. The app reads pages with PDFium and writes plain PDF, so it does not need them.
* Your own three tools (OpenStage Author, OpenStage Recorder, OpenExplainer) are all Apache-2.0 [file], as are the tagging engine
  (OpenDataLoader) and Tesseract. Apache-2.0 for PDF Remediator would match all of them.

**Three things to settle before giving copies away**

1. **The licence for PDF Remediator itself: decided, Apache-2.0 (2026-10-30).** `LICENSE` and `NOTICE` are in the repository.
2. **The Tesseract package carries a GPL library** (`libjbig-0.dll`, the JBIG-KIT image library, licensed GPL-2.0 [web]) and 54
   other native libraries whose licence texts are **not** shipped with it; several are LGPL. Good news inside this: the program
   only needs 33 of the 55 libraries, and I ran a slimmed copy that read a test page correctly (see "Decision 2").
3. **Notices are incomplete.** veraPDF's own licence files are missing from its folder, there is no written pointer to where the
   source of the weak-copyleft pieces can be had, and the FreeType credit line is missing. These are cheap to fix. See "Notices to add".

**Smaller things**

* `lxml` bundles an iconv library under LGPL-2.1 (the app's own notes already list this) [file]. Fixable with a notice and a source pointer.
* The Java runtime is 25.0.4.1; the app's own note says to check for 25.0.5 before sharing [file]. That is a security-update check, not a licence point.
* Sixteen Tesseract training programs, a debugging viewer (`ScrollView.jar`), three Java helper jars and 22 libraries ship but are
  never used by the app. Removing them takes away most of the LGPL list (see "Decision 2").
* The JPEG 2000 reader inside the tagging engine carries a notice that its use "may infringe existing patents" (JJ2000) [file].
  That only matters for PDFs holding JPEG 2000 pictures; keep the notice.

## Decisions for you

### Decision 1: the licence for PDF Remediator

**Decided 2026-10-30: Apache-2.0 (Jason).** `LICENSE`, `NOTICE` and the `pyproject.toml` licence fields were added the same day. The table below is kept for the record.

| Option | What it means for you | Fit |
|---|---|---|
| **Apache-2.0** (my recommendation) | Anyone may use, change and share it, including inside other products; must keep the notice; includes a patent grant. | Same as OpenStage Author, Recorder and OpenExplainer, OpenDataLoader and Tesseract. One consistent suite. |
| MIT | Same freedom, shorter text, no patent grant. | Fine, but different from the rest of your suite. |
| MPL-2.0 | Anyone may use it, but changes to *your files* must be shared back. | Matches pikepdf, OCRmyPDF and veraPDF; stricter than your other tools. |
| GPL-3.0 | Anything built on it must also be GPL. | Would cut the app off from non-GPL uses; not needed by any bundled piece. |

Whichever you pick, the bundled pieces do not constrain it: they run as separate programs (Java tools, Tesseract) or are used as
libraries under licences that only cover their own files. Apache-2.0 is not compatible with GPL-2.0-*only* **if** the two were
joined into one program, which they are not here; the GPL library in question is discussed below.

### Decision 2: the GPL library in the Tesseract package

**Decided 2026-10-30: route A, ship it with its licence and a source pointer (Jason).** Step 1 (slimming) is done; see "Progress" at the end. The text below is kept for the record.

The Windows Tesseract build (UB Mannheim, 5.5.3, made from MSYS2 packages [web]) contains `libjbig-0.dll`, the JBIG-KIT library.
MSYS2 lists JBIG-KIT as GPL-2.0, Debian and openSUSE as GPL-2.0-or-later [web]. I checked the file names inside the programs:
`tesseract.exe` loads libtiff, and libtiff loads `libjbig-0.dll`, so it is part of what runs. The app never gives Tesseract a TIFF
(OCRmyPDF hands it PNG pictures), so the library is not used for anything the app does.

**Step 1, free and small, for every route: slim the package.** Following the file names recursively, `tesseract.exe` needs only
33 of the 55 DLLs. The other 22 (the whole Pango, Cairo, GLib, FriBidi, Thai, Graphite2, HarfBuzz, FreeType, Fontconfig, ICU, Pixman,
PCRE2 and libffi group) are used only by `text2image.exe`, a training tool. I copied just the 33 DLLs, `tesseract.exe` and the
English/orientation models to a scratch folder: `tesseract --version` ran, and it read a one-line test image correctly
("Licence check sample text"). That removes most of the LGPL list and the FreeType credit for this folder. (Since then the full app was run with the slimmed folder: see "Progress".)

What is left after slimming that needs notices: `libjbig-0` (GPL-2.0), `libiconv-2`, `libintl-8`, `libunistring-5`, `libidn2-0`
(LGPL), `libstdc++-6` and `libgcc_s_seh-1` (GPL-3 with the GCC exception), `libzstd` (take the BSD choice), plus the permissive ones.
curl, ssh2, psl, idn2 and unistring are there only because this Tesseract build can fetch pictures from web addresses, which the
app never does.

| Route for `libjbig-0` | Cost | What it takes | Risk left |
|---|---|---|---|
| **A. Ship it with its licence and a source pointer** (recommended starting point) | free, small | Add the GPL text, JBIG-KIT copyright and a link to its source; describe it as a separate library loaded unmodified. This is how the UB Mannheim installer itself is distributed. | Some people read the GPL as reaching programs that load a GPL library. Tesseract and our app are separate programs, but the point is arguable; ask counsel once. |
| **B. Use a Tesseract build without JBIG-KIT** | free, real work | Build libtiff and Tesseract without JBIG support (a custom build), re-run the OCR checks, re-lock the package. | Removes the question. |
| C. Leave it as is | free | Nothing | Not acceptable for giving copies away: GPL text and source offer would be missing. |

## What is in the package

### Programs that run as separate processes

| Part | Version | Licence | Ships with licence text? | What to do | Risk |
|---|---|---|---|---|---|
| OpenDataLoader PDF (tagging engine, Hancom) | 2.5.13 | Apache-2.0 [file]. Before 2.0 it was MPL-2.0 [file], not relevant to 2.5.13 | Yes: `LICENSE`, `NOTICE`, `THIRD_PARTY/` (list + 13 licence texts) | Keep as shipped; add a link to its source to the notices | Low |
| ...inside its jar | | Apache PDFBox 3.0.4, FontBox, JBIG2 plug-in, Jackson, commons-cli/logging: Apache-2.0. JAXB, Activation, istack: CDDL-1.1 or EDL-1.0 (BSD-3). veraPDF libraries 1.31.x: MPL-2.0 (Hancom took the MPL option from the dual licence) [file]. JAI-ImageIO JPEG 2000: Sun BSD + JJ2000 notice | Yes (`THIRD_PARTY/licenses`) | MPL and CDDL files are unmodified; the notices must say where their source is (Maven Central / GitHub). Its repository-wide list also names dev tools (esbuild, ESLint...) that are not in the jar; I checked the jar's own Maven records instead | Low |
| veraPDF command line (strict PDF/UA checker) | 1.30.3 | Dual: GPL-3.0-or-later **or** MPL-2.0-or-later [file README, web]. We would use it under **MPL-2.0** | **No.** Its README points to `LICENSE.GPL` / `LICENSE.MPL`, which are not in the folder. The jar holds only Apache, Rhino-MPL and Jackson texts [file] | Add the MPL-2.0 text, the veraPDF copyright line and a source link; state that it is used under the MPL. Saxon-HE (MPL-2.0) is also inside [knowledge] | Medium, easy to fix |
| Java runtime (Eclipse Temurin JRE) | 25.0.4.1+1 | GPL-2.0 with the Classpath Exception [file, web] | Yes: `legal/` holds the GPL text, assembly exception and per-module notices, plus `NOTICE` | Add a source pointer (github.com/adoptium/jdk25u at the commit named in its `release` file). Check for 25.0.5 before sharing. The exception means the jars it runs are not GPL | Low |
| Tesseract (text recognition) | 5.5.3 (UB Mannheim build, 2026-07-24) | Apache-2.0 [file `doc/LICENSE`] | Yes, for Tesseract itself | See the DLL table below | Medium (libraries) |
| English and orientation models | tessdata_fast, pinned commit | Apache-2.0 [file `tessdata/LICENSE`] | Yes | None | Low |
| Unused extras in the Tesseract folder | | 16 other programs (training tools and helpers); `ScrollView.jar` (debug viewer); Piccolo2D (BSD) and JAXB (CDDL) jars; 22 libraries only they use | n/a | Leave out of the package; the app calls only `tesseract.exe` | n/a |

### Native libraries beside Tesseract (55 DLLs; 33 needed)

Only Tesseract itself has a licence text in the folder. The grouping below is **[knowledge]** except where marked; confirm each
from its MSYS2 package page when the notices file is built. Libraries marked "training only" are not needed by `tesseract.exe` [file
names checked] and can be left out (Decision 2, step 1).

| Group | Libraries | What is required |
|---|---|---|
| **GPL** | `libjbig-0` (JBIG-KIT) [web] | See Decision 2 |
| GPL-3.0 with GCC Runtime Library Exception | `libstdc++-6`, `libgcc_s_seh-1` | Notice and licence text; the exception lets non-GPL programs use them |
| **LGPL**, still needed | `libintl-8`, `libiconv-2`, `libunistring-5` and `libidn2-0` (LGPL-3+ or GPL-2+ choice: take LGPL) | Licence text, copyright notice, a written pointer to the source, and the libraries must stay separate DLL files so a user can swap them (they do) |
| **LGPL**, training only (can be left out) | `libglib-2.0-0`, `libgobject-2.0-0`, `libgio-2.0-0`, `libgmodule-2.0-0`, `libpango-1.0-0`, `libpangocairo-1.0-0`, `libpangoft2-1.0-0`, `libpangowin32-1.0-0`, `libcairo-2` (LGPL-2.1 or MPL-1.1), `libfribidi-0`, `libthai-0`, `libdatrie-1`, `libgraphite2` (LGPL / MPL / GPL choice) | None if left out |
| Dual with a permissive choice | `libzstd` (BSD or GPL-2: take BSD); `libfreetype-6` (FreeType Licence or GPL-2; training only) | Notice |
| Permissive | `libleptonica-6`, `libtiff-6`, `libpng16-16`, `libjpeg-8`, `libwebp-7`, `libwebpmux-3`, `libsharpyuv-0`, `libopenjp2-7`, `libgif-7`, `libLerc` (Apache-2.0), `libdeflate`, `zlib1`, `libbz2-1`, `liblz4`, `liblzma-5`, `libbrotlicommon`, `libbrotlidec`, `libexpat-1`, `libffi-8`, `libpcre2-8-0`, `libharfbuzz-0`, `libfontconfig-1`, `libpixman-1-0`, `libicudt78`, `libicuin78`, `libicuuc78` (Unicode licence), `libcurl-4`, `libssh2-1`, `libpsl-5`, `libarchive-13`, `libb2-1`, `libwinpthread-1` | Keep each one's copyright and licence text in the notices |

A custom Tesseract build without curl and archive support would remove the last of the LGPL libraries as well, but after the
slimming above that is real work for little gain; I would not do it unless counsel asks.

### Python runtime and packages

CPython 3.14.9 (PSF-2.0, `LICENSE.txt` ships [file]) with OpenSSL 3 (Apache-2.0), libffi (MIT), SQLite (public domain), libtommath
(public domain). Microsoft's Visual C++ runtime DLLs are no longer shipped (see the 2026-10-31 notes at the end).

Core runtime (8 wheels), declared licences read from each package [file]:

| Package | Licence | Notes |
|---|---|---|
| pikepdf 10.17.0 | MPL-2.0 | Wheel bundles qpdf (Apache-2.0), libjpeg-turbo, OpenSSL, zlib, GCC runtime exception, MSVC runtime, and veraPDF rule data (CC-BY-4.0, attribution file ships). Texts ship in the wheel |
| pypdfium2 5.14.0 | BSD-3-Clause / Apache-2.0 (+ PDFium) | Texts ship |
| Pillow 13.0.0 | MIT-CMU | Its licence file also carries the bundled libraries, including FreeType 2.14.3 (FreeType Licence: credit line needed) |
| lxml 6.1.3 | BSD-3-Clause | Bundles libxml2 and libxslt (MIT), zlib, and **iconv under LGPL-2.1** (already an open item in the app's notes). Used by the app in one place (`ocr_angles.py`, the tilted-text layout) and required by OCRmyPDF |
| PyYAML, psutil, fonttools, packaging | MIT, BSD-3, MIT, Apache-2.0 or BSD-2 | Texts ship |

The separate OCR runtime holds 31 packages (six are the same as above), all with texts shipped [file]:

* **MPL-2.0:** OCRmyPDF 17.13.0 (file-level copyleft; unmodified).
* **LGPL-3.0:** **fpdf2 2.8.9** and **img2pdf 0.6.3**. They are plain Python files in the runtime folder, so a user can replace them,
  which is what LGPL asks. Each needs its licence text (with the GPL-3.0 text it builds on), a notice and a source pointer.
* Permissive: pdfminer.six, pluggy, pydantic and pydantic-core, rich, markdown-it-py, mdurl, Pygments, jsonschema, referencing,
  jsonschema-specifications, rpds-py, attrs, annotated-types, typing-extensions, typing-inspection, charset-normalizer, cffi, pycparser, cryptography
  (Apache-2.0 or BSD-3), defusedxml (PSF), uharfbuzz (Apache-2.0).

### Fonts and data

| Item | Licence | Status |
|---|---|---|
| Noto Sans Regular 2.007 (in `src/pdf_remediator/data` and inside OCRmyPDF) | SIL Open Font License 1.1 | Licence text and provenance ship [file]. Fine to include unsold, unmodified |
| Occulta (hidden-text font OCRmyPDF embeds in OCR output) | Apache-2.0 (named in the font itself) [file] | Fine |
| TeX glyph-name mapping (`glyphtounicode-cmr`) | LPPL 1.2 or later; LPPL-1.3c text ships [file] | Unchanged file with notice: fine |
| veraPDF rule data inside pikepdf | CC-BY-4.0 | Attribution file ships inside the wheel [file] |

### Not in the package, and should stay out

* Your test PDFs (private). The package builder takes only `src/pdf_remediator` assets and notices.
* *Think Python* (CC BY-NC): evaluation input only; `eval/external/PROVENANCE.md` says it is not bundled. Not in git [file: no PDFs are tracked].
* The licensed AMS font archive (CMSY10/CMEX10) used by font tests: an external prerequisite, not tracked.
* If the *repository* is ever made public (item 9 of the release checklist), scrub `HANDOFF.md`, `docs/STATUS.md` and `eval/` of
  notes about private test files first.

## Notices to add (all free; I will do these once you answer Decisions 1 and 2)

1. `LICENSE` and `NOTICE` for PDF Remediator (Apache-2.0 if you agree), same layout as your other tools.
2. A `THIRD-PARTY-NOTICES` file in the package: every row above with its licence, copyright line and where its source can be had.
3. The missing licence texts: veraPDF (MPL-2.0 and its copyright), LGPL-2.1, LGPL-3.0 with GPL-3.0, GPL-2.0 (for JBIG-KIT, if kept),
   GPL-3.0 with the GCC exception, the FreeType Licence, and the short permissive texts for the Tesseract libraries.
4. A written source pointer: "Source for the MPL, LGPL, CDDL and GPL components is available from the links in
   THIRD-PARTY-NOTICES. They are shipped unmodified; replace a library by dropping a newer file of the same name in place."
5. The FreeType credit line in About/README (still needed: Pillow and PDFium carry FreeType even after the Tesseract folder is slimmed): "Portions of this software are copyright (c) The FreeType Project (www.freetype.org). All rights reserved."
6. Do not use the names Tesseract, veraPDF, OCRmyPDF, OpenDataLoader, Hancom, Adoptium/Temurin or Java in a way that suggests
   they endorse PDF Remediator.
7. Package builder: extend the "selected redistribution-review notice files" list in `scripts/package-windows.py`; drop the unused Tesseract
   extras (16 programs, 22 DLLs, the jars); run the full OCR checks on the slim folder; re-lock the file list.
8. Re-check upstream versions (Temurin 25.0.5, Tesseract, Python, wheels) on the day of release.

## Still not done after this review

* Counsel: one pass by someone qualified (your university or the OpenStage side) on Decision 2, the LGPL/MPL source-pointer wording and the app licence.
* Decision 1 and 2 answers.
* Assembling the notices file and re-running the package build (item 7 of the checklist, fresh-machine install, follows).

## Sources checked on 2026-10-30

* JBIG-KIT: [MSYS2 package page, GPL-2.0](https://packages.msys2.org/package/mingw-w64-ucrt-x86_64-jbigkit); [openSUSE spec, GPL-2.0-or-later](https://src.opensuse.org/SLFO-pool/jbigkit/src/branch/main/jbigkit.spec); [Debian copyright record via Cumulus, GPL-2+](https://docs.nvidia.com/networking-ethernet-software/cumulus-linux-50/Whats-New/licenses/libjbig0.txt)
* veraPDF dual licence: [verapdf.org](https://verapdf.org/home/)
* Temurin: GPLv2 with Classpath Exception per its [NOTICE](https://www.eclipse.org/lists/temurin-dev/msg00005.html) and the shipped `legal/` folder
* UB Mannheim Tesseract installer built from MSYS2 packages since 5.3.1: [UB-Mannheim/tesseract wiki](https://github.com/UB-Mannheim/tesseract/wiki)

## Progress

**2026-10-30, after Jason chose Apache-2.0 and "ship with notices"**

* **Slim Tesseract, checked through the real app.** The 2-page test scan was run through the app twice per layout, once with the full
  Tesseract folder and once with the 33-library folder: standard, sideways/upside-down (`turns`), ruled-table and tilted-text
  layouts. Status, strict check, page-identical check, recognised-word counts and a hash of each page's text were the same in all
  four. (One scan, two pages; not yet the whole set.)
* **Package builder.** `scripts/windows-ocr-runtime-lock.json` now carries `native.omit`, the 67 files that are left out (installer
  plug-ins, 16 unused programs and their manual pages, the debugging viewer's jars, 22 libraries only the training tool loads).
  `scripts/package-windows.py` copies the other 71, and refuses to build if the list would remove a library that `tesseract.exe`
  needs (it follows the library names through the real files at build time). 14 new tests; 8 deliberate breakages all caught. A
  full package build was **not** run (it needs the local plan inputs), so the file list is not yet re-locked in a built package.
* **Licences checked on the web.** MSYS2 records a licence for each of the 33 libraries (read 2026-10-30; three spot-checked by hand).
  Result is in `THIRD-PARTY-NOTICES.md`: one GPL library (`libjbig-0`), four LGPL libraries (`libiconv-2`, `libintl-8`,
  `libunistring-5`, `libidn2-0`, each usable under LGPL-3.0), the GCC-runtime pair under the GCC exception, the rest permissive.
* **Notices.** `THIRD-PARTY-NOTICES.md` and `third-party/licenses/` (MPL-2.0, GPL-2.0, GPL-3.0, GCC Runtime Library Exception 3.1,
  LGPL-3.0, copied unchanged from software already on this PC, with SHA-256 values) are in the repository. The notices file lists every
  item still marked TODO.
* **Still open:** the contact line for the written offer (yours), the per-library licence texts from each project's own release
  (needs a download, so I will ask first), Saxon's notice, the FreeType credit line with its year, adding these files to the package's
  notice list, a real package build and fresh-machine install, and the review by someone qualified.

**2026-10-30, licence texts downloaded (Jason approved)**

* 31 plain-text licence files were fetched from the projects' own repositories (GitHub, GitLab, sourceforge.net, sourceware.org), each into
  its own new folder, checked to be the expected licence and saved unchanged in `third-party/licenses/` with its address and SHA-256 in
  that folder's `README.md`: the 21 other Tesseract libraries, veraPDF's `LICENSE.MPL`, JBIG-KIT, and OpenSSL 3.5.9, libffi, expat and
  libtommath for Python. 26 came from the release tag for the version in the package; five came from a branch head (see the notices
  file, "Still to do", item 3).
* JBIG-KIT's `COPYING` is the plain GPL-2.0 text and the copy kept here came from a GitHub mirror, because the author's site did not
  serve the file at the address tried. Its header names the author, Markus Kuhn; no copyright year is claimed.
* Saxon: the veraPDF library depends on **Saxon-HE**, published under MPL-2.0 (Maven Central, GitHub). Its own licence file was not found at
  the addresses tried; the MPL-2.0 text kept here covers it.
* **Still open now:** the written-offer contact line (yours), Microsoft's terms for the Visual C++ runtime DLLs Python carries, the FreeType
  credit year, adding the notices to a real package build, and the review by someone qualified.

**2026-10-31, written-offer contact (Jason)**

* Jason said everything will be on GitHub. The written offer in `THIRD-PARTY-NOTICES.md` now tells people to open an issue at
  https://github.com/jasonswrench-beep/PDFRemediator/issues to ask for the source code of a GPL, LGPL, MPL or CDDL component (valid for
  three years from the day they received the copy).
* **Condition:** that repository is private today, so the address leads nowhere until it is made public. It must also stay up for at
  least three years after the last copy goes out, and the address changes if the repository is renamed or moved.
* The GPL-2.0 text also lets the source be offered "from the same place" the programs are downloaded from, so putting the libjbig
  source next to the downloadable package on GitHub would be a simpler second route. Not done; it needs a download, so it waits for a yes.
  (Not legal advice; part of the review by someone qualified.)
* **Still open now:** Microsoft's terms for the Visual C++ runtime DLLs, the FreeType credit year, making the repository public, adding
  the notices to a real package build, fresh-machine install, and the review by someone qualified.

**2026-10-31, Microsoft's runtime files (Jason asked me to start here)**

* The package carries Microsoft files in three places: Python (`vcruntime140.dll`, `vcruntime140_1.dll` in `runtime/python/` and
  `runtime/ocr/`), pikepdf (`msvcp140-<hash>.dll`) and the Java runtime (`msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll`,
  `ucrtbase.dll` and 45 `api-ms-win-*.dll` files). The earlier notes only knew about Python's two.
* **Result: not a quick yes.** Microsoft's own pages (read 2026-10-31) limit redistribution of the runtime files to licensed Visual
  Studio users, and the licence of the Visual C++ Redistributable package itself forbids offering it combined with your own
  applications for others to use. The earlier informal answers saying redistribution is allowed are not backed by these pages. Python,
  Adoptium and pikepdf ship the same files, but that does not by itself give Jason the right to pass them on.
* Microsoft recommends installing its Redistributable on the target PC instead of copying the DLLs. The Universal CRT files in the Java
  folder do nothing on Windows 10 and 11, because the system copy is always used there.
* Ways forward are written in `THIRD-PARTY-NOTICES.md`, "Still to do", item 2: (A) do not ship the files and have the installer check for
  Microsoft's package (free; changes the package lock and installer; needs a test on a PC without it), (B) take the files from Visual Studio
  Community under its licence, (C) keep shipping the copies and accept the risk after review. Nothing has been changed in the package.
* Not read: the Windows SDK licence and the Visual Studio Community licence conditions.

**2026-10-31, Route A built: Microsoft's runtime files are left out (Jason chose it)**

* `scripts/package-windows.py` now skips Microsoft's runtime files (`vcruntime140*.dll`, `msvcp140*.dll`, `ucrtbase.dll`, `api-ms-win-*.dll`
  and a few siblings) when it extracts the Python archive and the wheels and when it copies the Java, OpenDataLoader and veraPDF maps, lists
  what it left out in the package manifest (`microsoft_runtime`), and refuses to build if one remains in the payload or if any program
  needs a Microsoft runtime file the installer does not check for.
* pikepdf's wheel carried its own copy of `msvcp140.dll` under a hashed name that its two native files import. The builder rewrites that
  name in place to plain `msvcp140.dll` (same file size, rest padded with zero bytes) so they load Microsoft's own copy. Each file must hold
  the name exactly once or the build is refused. This changes two third-party binaries (`_core.pyd`, MPL-2.0; qpdf's DLL, Apache-2.0); it is
  described in the notices and recorded with before-and-after SHA-256 values. For the qualified reviewer.
* `scripts/windows-vc-runtime.cs` is added to the end of the installer and the launcher at build time. It checks the Windows system folder
  for `ucrtbase.dll`, `vcruntime140.dll`, `vcruntime140_1.dll` and `msvcp140.dll` (at least 14.51.36247.0, the newest copy that used to be
  carried), and if one is missing or older it says so and offers to open Microsoft's download page. The program downloads nothing.
* Tests: the package tests went from 127 to 170, among them a real compile of the installer that is run with a minimum version no PC has (it refuses, writes
  nothing, and names Microsoft's page) and with a minimum every PC meets (the check passes and the next step runs). 23 deliberate
  breakages in the builder, the installer, the launcher and the check were all caught.
* Checked on this PC on scratch copies of the runtime from an earlier trial package: Python, OCR-Python and Java start without Microsoft's
  files, the three runtime DLLs load from Windows' own folder, and a 2-page test scan gave the same status, word counts and text as before.
  This PC already has the Redistributable (14.51.36247.0), so the case of a PC without it is **not yet tested** (fresh-machine install,
  checklist item 7). A real package build was not run (it needs the local plan inputs).
* **Still open now:** the missing-Redistributable case on a clean PC, the FreeType credit year, making the repository public, adding the
  notices to a real package build, and the review by someone qualified (including the two changed pikepdf files).

**2026-10-31, first real build and install of the package (Jason: the install had not been tested on the main computer)**

* The builder was run with the locked inputs found on this PC: the Python archive, the 8 core and 31 OCR wheels, the 138-file Tesseract
  folder, the English and orientation models (each checked against the lock by SHA-256), the Java, OpenDataLoader and veraPDF trees of an
  earlier trial package, the 66 application source files of the work copy, and the notices (this file, `LICENSE`, `NOTICE`, the 37 files of
  `third-party/licenses/`). Nothing was downloaded. Result: a 205 MB installer, 3,756 payload files, 55 Microsoft files left out, 4 pikepdf
  native files redirected, the payload check passed.
* The installer was run on this PC into a new empty folder (`C:\Users\Jason\PDFR-test`, no administrator access, no registry changes). It
  checked every file against the package list and wrote its completion marker. The installed folder holds no Microsoft runtime file.
* The installed copy's own Python ran the application on a 2-page test scan with the turns layout and the standard layout. Status
  (needs-manual), OCR (completed), fidelity, first gate, recognised words per page and the text of both pages were identical to the earlier
  runs with Microsoft's files. Not run: the launcher program (it opens a browser and leaves the local service running), the windowed installer,
  and anything on a PC without the Redistributable.
* **Still open now:** the launcher and windowed installer on this PC, the missing-Redistributable case on a spare PC (item 7), the FreeType
  credit year, making the repository public, and the review by someone qualified.

**2026-10-31, launcher tried on this PC (Jason said to open it)**

* `PDF Remediator.exe` in the new install folder was run (nothing was running from that folder first). It exited with code 0 and left one
  Python process serving the local workspace on this computer's own address (127.0.0.1); that page answered with the title "PDF Remediator".
  The launcher's own start-up check for Microsoft's runtime passed, because this PC has the Redistributable.
* I did not see the browser window myself, so the page's appearance in the browser is unconfirmed. No PDF was processed through the window.
* The process was stopped by its exact process number (not from the page's "Stop application" button), after checking that it was the
  installed program. Afterwards nothing was running from the install folder and the address no longer answered. Not yet checked: that a second
  launch recovers cleanly from the session file that a forced stop leaves behind.
* **Still open now:** the windowed installer, the missing-Redistributable case on a spare PC (item 7), the FreeType credit year, making
  the repository public, and the review by someone qualified.

**2026-10-31, second PC (Jason's report) and a decision to skip the missing-package test**

* Jason ran the kit's windowed installer on both of his computers and had no problems on either. He did not say whether the program opened or
  the test scan ran on them, or which Windows version the second PC has. Since the installer refuses when Microsoft's runtime is missing or
  older than 14.51.36247.0, the second PC must already have it, so this shows the check passing on a second real PC.
* The missing-package message and the launcher's own check have **not** been seen on a real PC. Jason chose to skip the test of removing
  the package on the second PC. What exists instead: a real compile of the installer run here with an impossible minimum version (it
  refuses, writes nothing and names Microsoft's page) and the test that the launcher checks before it starts anything. A virtual machine
  would settle it if wanted before copies are given away.
* **Still open now:** the FreeType credit year, making the repository public, the review by someone qualified (including the two changed
  pikepdf files), and, optionally, the missing-package message on a real PC.

**2026-10-31, FreeType credit (Jason chose it next)**

* The FreeType License asks a binary distribution to say, in its documentation, that the software is based in part on the work of the
  FreeType Team, and recommends the line "Portions of this software are copyright © <year> The FreeType Project (www.freetype.org). All rights
  reserved." with the year of the FreeType version used (read in FreeType's `docs/FTL.TXT`).
* Year: FreeType 2.14.3, in Pillow 13.0.0 and in the Java runtime, was released on 2026-03-22 (freetype.org news page), and the FreeType
  snapshot inside PDFium 156.0.8076.0 was committed on 2026-08-24. So the year is **2026**; the earlier guess was right.
* The credit and the disclaimer are now in `THIRD-PARTY-NOTICES.md` (shipped under `NOTICES/`) and in the `START-HERE.txt` the builder writes
  (`FREETYPE_CREDIT` in `scripts/package-windows.py`, with a test). There is no About screen in the program to add it to.
* **Still open now:** making the repository public, the review by someone qualified, the optional virtual-machine check of the
  missing-package message, and the choice between the browser and an own window.
