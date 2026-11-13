# Third-party notices for PDF Remediator

PDF Remediator is licensed under the Apache License 2.0 (`LICENSE`, `NOTICE`). A packaged copy also contains the separate works listed
here. Each keeps its own licence and copyright. They are included unmodified, with three exceptions: a reviewed list of unused files is
left out of the Tesseract folder (`omit` in `scripts/windows-ocr-runtime-lock.json`); Microsoft's Visual C++ runtime files are left out of
Python, pikepdf and Java (the user installs Microsoft's own copy; see "Still to do", item 2); and, because of that, pikepdf's
`_core.pyd` and its bundled qpdf library carry one changed library name (see "How the obligations are met"). PDF Remediator runs Java, veraPDF, OpenDataLoader
PDF and Tesseract as separate programs, and uses the Python packages as libraries.

**Status: draft, 2026-10-30. Not legal advice and not a clearance.** Items marked **TODO** must be finished before a copy is given to anyone
(see "Still to do" at the end and `docs/LICENCE-REVIEW.md`). The licence texts named in the tables are in `third-party/licenses/`
(`README.md` there records the address and checksum of each).

## Source code and the written offer

The programs and libraries below are free software. Where their licence asks for it (GPL, LGPL, MPL, CDDL), their source code is
available from the "Source" links, and the exact version in this package is the one named. Copies in this package are not modified,
except as the first paragraph says.

> **Written offer (TODO: the repository below is private today; this address works only once it is public).** For three years from
> the day you received this copy, you may ask for the complete source code of any component of this package that is under the GPL,
> LGPL, MPL or CDDL, for no more than the cost of copying it. To ask, open an issue at
> https://github.com/jasonswrench-beep/PDFRemediator/issues

## FreeType credit

Portions of this software are copyright © 2026 The FreeType Project (www.freetype.org). All rights reserved.

This software is based in part on the work of the FreeType Team.

FreeType is used under the FreeType License by Pillow, by PDFium inside pypdfium2, and by the Java runtime. The licence asks for this
credit in the documentation of a binary distribution and says to use the year of the FreeType version actually used. Checked 2026-10-31:
Pillow 13.0.0 and the Java runtime (Temurin 25.0.5+8, checked again 2026-11-13) carry FreeType 2.14.3, released 2026-03-22 (freetype.org news page); PDFium
156.0.8076.0 inside pypdfium2 5.14.0 carries a Chromium FreeType snapshot (commit `4800589f76dc`, committed 2026-08-24, from PDFium's
`DEPS` for branch chromium/8076). All three are 2026. The credit is also in `START-HERE.txt`. The licence texts are in the packages:
Pillow's `LICENSE` under `pillow-13.0.0.dist-info/licenses/`, pypdfium2's `BUILD_LICENSES/freetype.txt` under its `dist-info/licenses/`,
and `runtime/java/legal/java.desktop/freetype.md`. FreeType's wording is in its `docs/FTL.TXT` (https://freetype.org/license.html links to it).

## Programs that run alongside PDF Remediator

| Part | Version | Licence | Source | Licence text in the package |
|---|---|---|---|---|
| OpenDataLoader PDF (the tagging engine, Hancom) | 2.5.13 | Apache-2.0 | https://github.com/opendataloader-project/opendataloader-pdf | `runtime/odl/LICENSE`, `NOTICE`, `THIRD_PARTY/` |
| veraPDF command line (strict PDF/UA checker) | 1.30.3 | Dual licence GPL-3.0-or-later or MPL-2.0-or-later. **PDF Remediator uses it under MPL-2.0.** | https://github.com/veraPDF/veraPDF-apps and https://github.com/veraPDF/veraPDF-library | `third-party/licenses/verapdf-LICENSE.MPL.txt` and `MPL-2.0.txt` (the veraPDF folder in the package does not contain the licence files its README points to, so they are added here) |
| Eclipse Temurin JRE (Java runtime, Adoptium) | 25.0.5+8 | GPL-2.0 with the Classpath Exception | https://github.com/adoptium/jdk25u (commit `7ec19fb1eda7`, from the runtime's `release` file); build scripts https://github.com/adoptium/temurin-build | `runtime/java/legal/` (GPL, assembly exception, per-module notices), `runtime/java/NOTICE` |
| Tesseract OCR | 5.5.3 (Windows installer build 5.5.3.20260724) | Apache-2.0 | https://github.com/tesseract-ocr/tesseract ; Windows build https://github.com/UB-Mannheim/tesseract/wiki | `runtime/tesseract/doc/LICENSE` |
| Tesseract English and orientation models (`tessdata_fast`, commit `87416418657359cb625c412a48b6e1d6d41c29bd`) | n/a | Apache-2.0 | https://github.com/tesseract-ocr/tessdata_fast | `runtime/tesseract/tessdata/LICENSE` |
| PDF Remediator.exe, the program window (since 2026-11-12) | n/a | Built from about 80 Rust packages, mostly MIT OR Apache-2.0 (also MIT, Apache-2.0, Unicode-3.0, Zlib, CC0-1.0 or MIT-0 options); among them tao, wry, the `windows` crates and `webview2-com` (MIT), whose `webview2-com-sys` links in Microsoft's WebView2 loader | https://crates.io (exact versions in `scripts/windows-launcher/Cargo.lock`) | `NOTICES/program-window-licences.txt`, written at build time from the packages themselves |
| Python (embeddable build) | 3.14.10 | PSF-2.0 | https://www.python.org/downloads/ | `runtime/python/LICENSE.txt` (and `runtime/ocr/`) |
| Parts carried by Python | n/a | OpenSSL 3 (Apache-2.0), libffi (MIT), SQLite (public domain), libtommath (public domain), expat (MIT), Microsoft Visual C++ runtime DLLs (**not in the package**: Microsoft limits who may pass them on, so the user installs Microsoft's own copy; see "Still to do", item 2) | via python.org (OpenSSL 3.5.9 read from the DLL) | `openssl-LICENSE.txt`, `libffi-LICENSE.txt`, `expat-COPYING.txt`, `libtommath-LICENSE.txt`; SQLite is public domain (https://sqlite.org/copyright.html); Microsoft runtime: not in the package |

Inside the OpenDataLoader PDF jar (all unmodified; its own list is `runtime/odl/THIRD_PARTY/THIRD_PARTY_LICENSES.md`, which also
names development tools that are not in the jar): Apache PDFBox 3.0.4, FontBox, PDFBox-IO and the JBIG2 plug-in, Jackson, Apache
Commons CLI and Logging (all Apache-2.0); JAXB, Jakarta/JavaBeans Activation, istack (CDDL-1.1 or EDL-1.0 / BSD-3-Clause);
JAI Image I/O JPEG 2000 reader (Sun BSD licence and the JJ2000 notice, which warns that JPEG 2000 use "may infringe existing
patents"; it applies only to PDFs holding JPEG 2000 pictures); and veraPDF libraries 1.31.x (MPL-2.0, the option Hancom chose).
Inside the veraPDF jar: Jackson (Apache-2.0), JAXB/Activation/istack (CDDL-1.1 / EDL-1.0), Mozilla Rhino (MPL-2.0, text in the jar)
and Saxon-HE (the `net.sf.saxon` classes; veraPDF's library depends on Saxon-HE, which Saxonica publishes under MPL-2.0 at
https://github.com/Saxonica/Saxon-HE, per Maven Central and GitHub on 2026-10-30). The jar carries no Saxon licence text and does not show
which Saxon-HE version it holds; the MPL-2.0 text kept here covers it.

## Tesseract's native libraries (33 DLLs)

`tesseract.exe` loads exactly these 33 libraries (found by following the library names that each file refers to; the package
builder repeats the check and refuses a package that omits one). The licences are the ones the MSYS2 project records for the
package that provides each DLL, read on 2026-10-30 from packages.msys2.org; the Windows installer is built from MSYS2 packages.
"Text" says where the licence text is kept.

| DLL | MSYS2 package (version) | Licence (as MSYS2 lists it) | Used here under | Upstream | Text |
|---|---|---|---|---|---|
| libjbig-0.dll | jbigkit (2.1-5) | **GPL-2.0** (Debian and openSUSE: GPL-2.0-or-later) | GPL-2.0 | https://www.cl.cam.ac.uk/~mgk25/jbigkit/ (copyright Markus Kuhn) | `GPL-2.0.txt` and `jbigkit-COPYING.txt` (JBIG-KIT's own COPYING file is the GPL text; its author is Markus Kuhn) |
| libiconv-2.dll | libiconv (1.19-1) | LGPL-2.1-or-later (documentation: GPL-3.0-or-later) | LGPL-3.0 | https://www.gnu.org/software/libiconv/ | `LGPL-3.0.txt`, `GPL-3.0.txt` |
| libintl-8.dll | gettext-runtime (1.0-1) | GPL-3.0-or-later AND LGPL-2.1-or-later (the library is the LGPL part) | LGPL-3.0 | https://www.gnu.org/software/gettext/ | `LGPL-3.0.txt`, `GPL-3.0.txt` |
| libunistring-5.dll | libunistring (1.4.2-1) | LGPL-3.0-or-later OR GPL-3.0-or-later | LGPL-3.0 | https://www.gnu.org/software/libunistring | `LGPL-3.0.txt`, `GPL-3.0.txt` |
| libidn2-0.dll | libidn2 (2.3.8-4) | GPL-2.0-or-later OR LGPL-3.0-or-later | LGPL-3.0 | https://www.gnu.org/software/libidn/#libidn2 | `LGPL-3.0.txt`, `GPL-3.0.txt` |
| libstdc++-6.dll, libgcc_s_seh-1.dll | gcc-libs (16.2.0-6) | GPL-3.0-or-later WITH GCC-exception-3.1 AND GFDL-1.3-or-later | GPL-3.0 with the GCC Runtime Library Exception | https://gcc.gnu.org | `GPL-3.0.txt`, `GCC-RUNTIME-LIBRARY-EXCEPTION-3.1.txt` |
| libwinpthread-1.dll | winpthreads (14.0.0.r569) | MIT AND BSD-3-Clause | same | https://www.mingw-w64.org/ | `winpthreads-COPYING.txt`, `mingw-w64-runtime-COPYING.MinGW-w64-runtime.txt` |
| libzstd.dll | zstd (1.5.7-2) | BSD-3-Clause OR GPL-2.0-or-later | BSD-3-Clause | https://facebook.github.io/zstd/ | `zstd-LICENSE.txt` |
| liblz4.dll | lz4 (1.10.0-1) | BSD OR GPL2 (the library is BSD-2-Clause) | BSD-2-Clause | https://lz4.github.io/lz4/ | `lz4-LICENSE.txt` |
| liblzma-5.dll | xz (5.8.4-1) | 0BSD AND LGPL-2.1-or-later AND GPL-2.0-or-later (the library is 0BSD) | 0BSD | https://tukaani.org/xz | `xz-COPYING.txt`, `xz-0bsd-COPYING.0BSD.txt` |
| libarchive-13.dll | libarchive (3.8.10-1) | BSD-2-Clause | same | https://www.libarchive.org/ | `libarchive-COPYING.txt` |
| libb2-1.dll | libb2 (0.98.1-3) | custom:CC0 | same | https://blake2.net/ | `libb2-COPYING.txt` |
| libbrotlicommon.dll, libbrotlidec.dll | brotli (1.2.1-1) | MIT | same | https://github.com/google/brotli | `brotli-LICENSE.txt` |
| libbz2-1.dll | bzip2 (1.0.8-4) | custom (the bzip2 licence) | same | https://sourceware.org/bzip2/ | `bzip2-LICENSE.txt` |
| libcurl-4.dll | curl (8.23.0-1) | MIT (the curl licence) | same | https://curl.se/ | `curl-COPYING.txt` |
| libssh2-1.dll | libssh2 (1.11.1-2) | BSD-3-Clause | same | https://libssh2.org/ | `libssh2-COPYING.txt` |
| libpsl-5.dll | libpsl (0.21.5-3) | MIT | same | https://rockdaboot.github.io/libpsl/ | `libpsl-COPYING.txt` |
| libdeflate.dll | libdeflate (1.26-1) | MIT | same | https://github.com/ebiggers/libdeflate | `libdeflate-COPYING.txt` |
| libexpat-1.dll | expat (2.9.0-1) | MIT | same | https://libexpat.github.io/ | `expat-COPYING.txt` |
| libgif-7.dll | giflib (6.1.3-1) | MIT | same | https://sourceforge.net/projects/giflib/ | `giflib-COPYING.txt` |
| libjpeg-8.dll | libjpeg-turbo (3.2.1-1) | custom:BSD-like (IJG, BSD-3-Clause, zlib) | same | https://libjpeg-turbo.virtualgl.org/ | `libjpeg-turbo-LICENSE.md.txt`, `libjpeg-turbo-ijg-README.ijg.txt` |
| libleptonica-6.dll | leptonica (1.87.0-2) | BSD-2-Clause | same | http://www.leptonica.org | `leptonica-leptonica-license.txt` |
| libLerc.dll | lerc (4.1.1-1) | Apache-2.0 | same | https://github.com/Esri/lerc | `lerc-LICENSE.txt` |
| libopenjp2-7.dll | openjpeg2 (2.5.4-2) | BSD-2-Clause | same | https://www.openjpeg.org/ | `openjpeg-LICENSE.txt` |
| libpng16-16.dll | libpng (1.6.59-2) | custom (the libpng licence) | same | http://www.libpng.org/pub/png/libpng.html | `libpng-LICENSE.txt` |
| libsharpyuv-0.dll, libwebp-7.dll, libwebpmux-3.dll | libwebp (1.6.0-1) | BSD-3-Clause | same | https://developers.google.com/speed/webp/ | `libwebp-COPYING.txt`, `libwebp-patents-PATENTS.txt` |
| libtiff-6.dll | libtiff (4.7.2-2) | MIT (the libtiff licence) | same | https://libtiff.gitlab.io/libtiff/ | `libtiff-LICENSE.md.txt` |
| zlib1.dll | zlib (1.3.2-3) | Zlib | same | https://www.zlib.net/ | `zlib-LICENSE.txt` |
| libtesseract-5.dll | tesseract-ocr (5.5.3-1) | Apache-2.0 | same | https://github.com/tesseract-ocr/tesseract | `runtime/tesseract/doc/LICENSE` |

`libjbig-0.dll` (JBIG-KIT) is the one GPL library in the package. `tesseract.exe` loads it through libtiff; PDF Remediator never gives
Tesseract a TIFF picture (the OCR step hands it PNG pictures), so it is not used for anything the program does. It is shipped as a
separate, unmodified DLL with its licence text and source link, the way the Tesseract Windows installer itself ships it. Decision
recorded 2026-10-30: Jason chose to ship it with these notices rather than use a Tesseract build without it.

## Python packages

Generated on 2026-10-30 from each installed package's own metadata ("In": the core runtime, the separate OCR runtime, or both).
Each package keeps its licence texts in its `*.dist-info/licenses` folder inside the package; they are not removed.

| Package | Version | Licence | In | Source | Note |
|---|---|---|---|---|---|
| annotated-types | 0.8.0 | MIT | OCR | https://github.com/annotated-types/annotated-types |  |
| attrs | 26.1.0 | MIT | OCR | https://github.com/python-attrs/attrs |  |
| cffi | 2.1.1 | MIT-0 | OCR | https://github.com/python-cffi/cffi |  |
| charset-normalizer | 3.5.2 | MIT | OCR | https://github.com/jawah/charset_normalizer |  |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | OCR | https://github.com/pyca/cryptography | Wheel also carries OpenSSL (Apache-2.0). |
| defusedxml | 0.7.1 | PSF-2.0 (Python Software Foundation License) | OCR | https://github.com/tiran/defusedxml |  |
| fonttools | 4.67.0 | MIT | OCR + core | https://github.com/fonttools/fonttools |  |
| fpdf2 | 2.8.9 | LGPL-3.0-only | OCR | https://github.com/py-pdf/fpdf2 | LGPL: see 'Replacing LGPL parts' below. |
| img2pdf | 0.6.3 | LGPL-3.0 (LGPLv3) | OCR | https://gitlab.mister-muffin.de/josch/img2pdf | LGPL: see 'Replacing LGPL parts' below. |
| jsonschema | 4.26.0 | MIT | OCR | https://github.com/python-jsonschema/jsonschema |  |
| jsonschema-specifications | 2025.9.1 | MIT | OCR | https://github.com/python-jsonschema/jsonschema-specifications |  |
| lxml | 6.1.3 | BSD-3-Clause | OCR + core | https://github.com/lxml/lxml | Wheel also carries libxml2 and libxslt (MIT), zlib and iconv (LGPL-2.1); see its LICENSES.txt. |
| markdown-it-py | 4.2.0 | MIT | OCR | https://github.com/executablebooks/markdown-it-py |  |
| mdurl | 0.1.2 | MIT | OCR | https://github.com/executablebooks/mdurl |  |
| ocrmypdf | 17.13.0 | MPL-2.0 | OCR | https://github.com/ocrmypdf/OCRmyPDF | MPL-2.0: unmodified; source at the link. |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | OCR + core | https://github.com/pypa/packaging |  |
| pdfminer.six | 20260107 | MIT | OCR | https://github.com/pdfminer/pdfminer.six |  |
| pikepdf | 10.17.0 | MPL-2.0 | OCR + core | https://github.com/pikepdf/pikepdf | Wheel also carries qpdf (Apache-2.0), libjpeg-turbo, OpenSSL, zlib, the GCC runtime exception and veraPDF rule data (CC-BY-4.0); texts in the wheel. |
| pillow | 13.0.0 | MIT-CMU | OCR + core | https://github.com/python-pillow/Pillow | Wheel also carries FreeType (FreeType Licence), libjpeg-turbo, zlib, LittleCMS, HarfBuzz, libtiff, libwebp, OpenJPEG; texts in the wheel's LICENSE. |
| pluggy | 1.7.0 | MIT | OCR | https://github.com/pytest-dev/pluggy |  |
| psutil | 7.2.2 | BSD-3-Clause | core | https://github.com/giampaolo/psutil |  |
| pycparser | 3.12 | BSD-3-Clause | OCR | https://github.com/eliben/pycparser |  |
| pydantic | 2.14.1 | MIT | OCR | https://github.com/pydantic/pydantic |  |
| pydantic_core | 2.50.1 | MIT | OCR | https://github.com/pydantic/pydantic/tree/main/pydantic-core |  |
| Pygments | 2.21.0 | BSD-2-Clause | OCR | https://github.com/pygments/pygments |  |
| pypdfium2 | 5.14.0 | BSD-3-Clause and Apache-2.0 (and PDFium's own) | OCR + core | https://github.com/pypdfium2-team/pypdfium2 | Carries PDFium (BSD-3-Clause / Apache-2.0) with its own third-party libraries, including FreeType; texts in the wheel. |
| PyYAML | 6.0.3 | MIT | core | https://github.com/yaml/pyyaml |  |
| referencing | 0.37.0 | MIT | OCR | https://github.com/python-jsonschema/referencing |  |
| rich | 15.0.0 | MIT | OCR | https://github.com/Textualize/rich |  |
| rpds-py | 2026.9.1 | MIT | OCR | https://github.com/crate-py/rpds |  |
| typing_extensions | 4.16.0 | PSF-2.0 | OCR | https://github.com/python/typing_extensions |  |
| typing-inspection | 0.4.4 | MIT | OCR | https://github.com/pydantic/typing-inspection |  |
| uharfbuzz | 0.56.4 | Apache-2.0 | OCR | https://github.com/trufont/uharfbuzz |  |

## Fonts and data

| Item | Licence | Where |
|---|---|---|
| Noto Sans Regular 2.007 (the OCR text editor's font) | SIL Open Font License 1.1 | `src/pdf_remediator/data/NotoSans-OFL.txt`, `NotoSans-PROVENANCE.txt` |
| Occulta (the hidden-text font OCRmyPDF embeds in OCR output) | Apache-2.0 | named in the font; inside OCRmyPDF's `data` folder |
| TeX glyph-name mapping (`glyphtounicode-cmr`, CTAN pdfx 1.6.5f) | LPPL 1.2 or later | `src/pdf_remediator/data/LPPL-1.3c.txt`, `TEX-MAPPING-NOTICE.txt` |
| veraPDF validation-rule data inside pikepdf | CC-BY-4.0 (attribution: veraPDF Consortium) | in the pikepdf wheel's `licenses/third-party-licenses` |

## How the obligations are met

* **Replacing LGPL parts.** fpdf2 and img2pdf are ordinary Python files in `runtime/ocr/Lib/site-packages/`, and the four LGPL
  libraries (`libiconv-2.dll`, `libintl-8.dll`, `libunistring-5.dll`, `libidn2-0.dll`) are separate DLL files in `runtime/tesseract/`.
  None is merged into another program, so another build of the same library can be put in its place.
* **MPL-2.0 parts** (veraPDF, OCRmyPDF, pikepdf, Mozilla Rhino and Saxon-HE): unmodified, with the licence text and a source link,
  except that pikepdf's compiled `pikepdf/_core.pyd` has one library name changed (next item). pikepdf's source is at
  https://github.com/pikepdf/pikepdf and the change is made by `redirect_renamed_runtime` in `scripts/package-windows.py`.
* **The changed library name in pikepdf.** pikepdf's Windows wheel bundles its own copy of Microsoft's `msvcp140.dll` under a hashed name
  and its two native files, `pikepdf/_core.pyd` (MPL-2.0) and `pikepdf.libs/qpdf30-<hash>.dll` (qpdf, Apache-2.0), load it by that name.
  Because Microsoft's copy is left out, the 45-character name `msvcp140-<32 hex>.dll` in each file is rewritten to `msvcp140.dll`, padded with
  zero bytes to the same length, so the files load Microsoft's own copy from the Windows system folder. Nothing else in either file changes.
  The package manifest (`microsoft_runtime.redirected_imports`) records each file's SHA-256 before and after.
* **CDDL-1.1 parts** (JAXB and Activation inside the Java tools): unmodified, with a source link.
* **GPL-2.0** (`libjbig-0.dll`): see above; the GPL text is `GPL-2.0.txt`.
* **GPL-2.0 with Classpath Exception** (the Java runtime): the exception means the programs it runs are not covered by the GPL.
* **FreeType credit** (Pillow, PDFium inside pypdfium2, and the Java runtime carry FreeType under the FreeType License): done; see "FreeType
  credit" above. The credit and the disclaimer the licence asks for are in this file and in `START-HERE.txt`.
* **Names.** Tesseract, veraPDF, OCRmyPDF, OpenDataLoader, Hancom, Adoptium, Temurin and Java are names of other people's projects and
  are used only to say what is included. They do not endorse PDF Remediator.

## Still to do before a copy is given to anyone

1. The written offer points to the GitHub issues page of `jasonswrench-beep/PDFRemediator` (Jason, 2026-10-31: everything will be on GitHub).
   The repository is private today, so make it public before a copy is given to anyone, keep it up for at least three years after the last
   copy goes out, and change the address here if the repository is renamed or moved.
2. **Microsoft runtime files: left out of the package (Route A, chosen by Jason on 2026-10-31).** Microsoft's own pages limit who may pass
   on its Visual C++ runtime files (read 2026-10-31: "Redistribute Visual C++ files", the Visual Studio 2022 "Distributable Code" list,
   "Universal CRT deployment" and the licence of the Visual C++ 2015-2022 Runtime; links below). So the package carries none of them, and the
   computer needs Microsoft's own free Visual C++ Redistributable (x64, 14.51.36247.0 or newer).
   * **Left out:** `vcruntime140.dll` and `vcruntime140_1.dll` (Python, in `runtime/python/` and `runtime/ocr/`), pikepdf's renamed copy of
     `msvcp140.dll`, and from the Java runtime `msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll`, `ucrtbase.dll` and 45
     `api-ms-win-*.dll` files (Windows 10 and 11 always use their own copy of those last 46 anyway).
   * **The check:** the installer and the launcher look in the Windows system folder for `ucrtbase.dll` and the three runtime files, and if
     one is missing or older than the minimum they say so and offer to open Microsoft's page
     (https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist). The program downloads nothing. The builder refuses to build
     if any Microsoft runtime file is in the payload or any program needs one the installer does not check for.
   * **The change to pikepdf** is described under "How the obligations are met".
   * **Checked on 2026-10-31** with the builder's own functions on scratch copies of the Python, OCR-Python and Java folders from an earlier
     trial package: 3 files taken out of each Python folder and 49 out of Java, pikepdf's two files redirected, and the builder's payload
     check passed on the real binaries. pikepdf, Pillow, lxml, pypdfium2, ocrmypdf and fontTools import, the three runtime DLLs load from
     Windows' own system folder, and Java starts. A 2-page test scan run through the app (turns layout) gave the same status, recognised
     words and text as the run with Microsoft's files (needs-manual, identical text hashes); a standard-layout run also completed. The PC used
     already has the Redistributable (14.51.36247.0), so this does **not** show what happens without it.
   * **A real build and install, 2026-10-31:** the builder was run on the locked inputs found on this PC (3,756 files, 55 Microsoft files
     left out, the four pikepdf native files redirected), the installer put the result in a new folder on this PC, and the installed copy
     ran a 2-page test scan to the same status, recognised words and text as before. No Microsoft runtime file is in the installed folder.
     This PC has the Redistributable, so the missing-Redistributable path is still untried.
   * **Second PC, 2026-10-31 (Jason's report):** the windowed installer was run on this PC and on a second PC and finished without problems on
     both. Because the installer refuses when the runtime is missing or too old, the second PC must already have Microsoft's package. The
     "please install Microsoft's package" message has therefore **not been seen on a real PC**; Jason chose to skip the test of removing the
     package. The message logic was tested only by compiling the real installer here with a minimum version no PC meets.
   * **Still to do:** (a) optional: see the missing-package message and the launcher's own check on a PC that really lacks the Redistributable
     (for example a virtual machine); (b) raise `MS_RUNTIME_MINIMUM` in `scripts/package-windows.py` whenever the locked
     Python, wheels or Java change; (c) have the qualified reviewer look at the two changed pikepdf files; (d) no longer needed: the Windows
     SDK licence and the Visual Studio Community conditions.
   * **What Microsoft's pages say:** Learn, "Redistribute Visual C++ files" (updated 2026-04-15): distributing the runtime package, merge
     modules and individual binaries is limited to licensed Visual Studio users; Microsoft recommends installing its Redistributable on the
     target PC instead of putting the DLLs in the application's folder. Learn, "Distributable Code for Visual Studio 2022": someone with a
     valid Visual Studio Enterprise, Professional or Community 2022 may distribute the unmodified files under `VC\redist` with their program,
     under that licence. The licence of the Visual C++ 2015-2022 Runtime package: no offering the software stand-alone or combined with your
     own applications for others to use, and no transferring it to a third party. Learn, "Universal CRT deployment": local copies are
     supported but not recommended, and on Windows 10 and 11 the system copy is always used.
   Links: https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files ,
   https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution ,
   https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment ,
   https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/
3. Version pins: five texts came from a branch head, not a release tag (`libb2`, `giflib`, `libtommath`, the veraPDF licence file and the
   JBIG-KIT mirror copy), and `libffi` is from tag 3.4.8 because its DLL does not show a version. Licence texts rarely change, but compare
   them with the release in the package when it is built.
4. Notices in the package: done for the first real build (2026-10-31): this file, `LICENSE`, `NOTICE` and `third-party/licenses/` (37 files)
   went in through `plan["notices"]` and are in the installed `NOTICES/` folder. Still to do: the same staging for every later build.
5. FreeType credit: done (2026-10-31), year 2026 confirmed from freetype.org (2.14.3 released 2026-03-22) and from the PDFium snapshot's commit
   date. Check the year again, here and in `FREETYPE_CREDIT` in `scripts/package-windows.py`, whenever Pillow, pypdfium2 or the Java runtime
   change to a FreeType from another year.
6. Check each library's licence against the version in the package on the day of release (MSYS2 versions above were read on 2026-10-30).
7. One review by someone qualified (your university or the OpenStage side).
8. Program window (since 2026-11-12): `webview2-com`, `webview2-com-macros` and `webview2-com-sys` carry no licence file, only "MIT" in
   their manifests, so `NOTICES/program-window-licences.txt` says so (as the other suite programs' notices do). `webview2-com-sys` links in
   Microsoft's WebView2 loader (`WebView2LoaderStatic.lib` from Microsoft's WebView2 SDK); add the SDK's own licence text before a copy
   is given to anyone, and have the reviewer in item 7 look at it.
9. Bundled tools, security updates (2026-11-13): Java is Temurin 25.0.5+8 and Python 3.14.10. The exact Java, OpenDataLoader and
   veraPDF trees are pinned file by file in `scripts/windows-native-lock.json`. Tesseract stays at 5.5.3 until a Windows build of
   5.5.4 (released 2026-10-28 as source only, with fixes for memory-safety advisories) is published; then update
   `scripts/windows-ocr-runtime-lock.json` and rebuild.
