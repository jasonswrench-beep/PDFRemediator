"""Trusted OCRmyPDF hook; load only by the application's fixed plugin path."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

from ocrmypdf import hookimpl

ALGORITHM = Path(__file__).resolve().with_name('ocr_table_lines.py')
_spec = importlib.util.spec_from_file_location('pdf_remediator_ruled_table_filter', ALGORITHM)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


@hookimpl(wrapper=True, tryfirst=True)
def filter_ocr_image(page, image):
    # Let the built-in hook retain its native image-size/downsampling safeguards.
    prepared = yield
    destination = Path(os.environ['PDF_REMEDIATOR_TABLE_EVIDENCE'])
    source_hash = os.environ['PDF_REMEDIATOR_TABLE_SOURCE_SHA256']
    if not destination.is_absolute() or not destination.is_dir() or not re.fullmatch('[0-9a-f]{64}', source_hash):
        raise ValueError('Ruled-table OCR evidence binding is invalid.')
    result, proof = _module.filter_table_lines(prepared)
    proof.update(schema='phase1-ocr-table-preprocess-1', profile='table-lines', page=page.pageno + 1,
                 adapter_source_sha256=source_hash,
                 plugin_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                 algorithm_sha256=hashlib.sha256(ALGORITHM.read_bytes()).hexdigest())
    try:
        with (destination / f'{page.pageno + 1:06d}.json').open('x', encoding='utf-8') as stream:
            json.dump(proof, stream, indent=2)
            stream.write('\n')
        return result
    except BaseException:
        result.close()
        raise
