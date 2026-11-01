"""Phase 0-only experiment isolating OCRmyPDF 17.13.0's hOCR text move.

An initial run failed with WinError 5 during the stock sidecar replace in the
desktop sandbox's default temporary directory. This launcher tests distinct
sidecar naming without changing the installed distribution. It wraps only
generate_hocr's output_text argument: the original moves its text into a
distinct sibling, then this wrapper moves that sibling to its destination.

The experiment did not fix default-temp failures. Stock OCRmyPDF succeeded
with a project-local TEMP/TMP directory, without this wrapper. A same-path
library defect was therefore not established. Keep this launcher only as
diagnostic evidence; the canonical route uses unchanged stock OCRmyPDF.

This is experimental evaluation evidence, not a supported production fix.
Invoke with the OCR environment's Python and ordinary OCRmyPDF CLI options.
"""
from __future__ import annotations

from functools import wraps
from importlib.metadata import version
import logging
import multiprocessing
from pathlib import Path
import sys

from ocrmypdf._exec import tesseract


if version("ocrmypdf") != "17.13.0":
    raise RuntimeError("The Phase 0 compatibility launcher is scoped to OCRmyPDF 17.13.0 only")

_ORIGINAL_GENERATE_HOCR = tesseract.generate_hocr


@wraps(_ORIGINAL_GENERATE_HOCR)
def generate_hocr_with_distinct_text_output(*args, **kwargs):
    if args:
        raise TypeError("OCRmyPDF 17.13.0 generate_hocr accepts keyword arguments only")
    intended = Path(kwargs["output_text"])
    staged = intended.with_name(intended.stem + ".phase0-compat" + intended.suffix)
    if staged == intended or staged.exists():
        raise FileExistsError("Phase 0 OCR compatibility staging file must be distinct and absent")
    arguments = dict(kwargs)
    arguments["output_text"] = staged
    logging.getLogger("ocrmypdf").info("Phase 0 Windows compatibility: stage hOCR sidecar to a distinct sibling")
    _ORIGINAL_GENERATE_HOCR(**arguments)
    if staged.exists():
        staged.replace(intended)


# Patch only this function in the current launcher process. Applying it at
# import also covers Windows workers that import their __mp_main__ launcher.
tesseract.generate_hocr = generate_hocr_with_distinct_text_output


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from ocrmypdf.__main__ import run
    sys.exit(run())
