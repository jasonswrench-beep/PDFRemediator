"""Fixed private OCRmyPDF wrapper: note how surely each page was read, and change nothing else.

Every call is handed to the built-in Tesseract engine unchanged; afterwards the page's hOCR is read and the counts of sure
and unsure words are written as a small JSON file. A problem here can never stop the reading: the page is then reported as not
measured.
"""
import importlib.util
import json
import os
from pathlib import Path
import re

from ocrmypdf import hookimpl
from ocrmypdf.pluginspec import OcrEngine


def _load(name, filename):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_confidence = _load('pdf_remediator_fixed_confidence', 'ocr_confidence.py')


def _record(input_file, hocr_file):
    match = re.fullmatch(r'([0-9]{6})_ocr\.png', Path(input_file).name)
    destination = Path(os.environ['PDF_REMEDIATOR_CONFIDENCE_EVIDENCE'])
    source_hash = os.environ['PDF_REMEDIATOR_CONFIDENCE_SOURCE_SHA256']
    if not match or int(match[1]) < 1 or not destination.is_absolute() or not destination.is_dir() or not re.fullmatch('[0-9a-f]{64}', source_hash):
        return
    page = int(match[1])
    reading = _confidence.measure(_confidence.hocr_words(Path(hocr_file).read_text(encoding='utf-8', errors='replace')))
    proof = {'schema': _confidence.SCHEMA, 'version': _confidence.VERSION, 'page': page, 'adapter_source_sha256': source_hash,
             'plugin_sha256': _confidence.digest(Path(__file__).resolve()), 'algorithm_sha256': _confidence.digest(_confidence.__file__),
             'reading': reading}
    target = destination / f'{page:06d}.json'
    target.write_text(json.dumps(proof, indent=2, allow_nan=False) + '\n', encoding='utf-8')


class MeasuringEngine(OcrEngine):
    def __init__(self, native):
        if native is None:
            raise ValueError('The confidence recorder requires the qualified native OCR engine.')
        self.native = native

    def version(self):
        return self.native.version()

    def creator_tag(self, options):
        return self.native.creator_tag(options)

    def __str__(self):
        return str(self.native)

    def languages(self, options):
        return self.native.languages(options)

    def get_orientation(self, input_file, options):
        return self.native.get_orientation(input_file, options)

    def get_deskew(self, input_file, options):
        return self.native.get_deskew(input_file, options)

    def generate_hocr(self, input_file, output_hocr, output_text, options):
        self.native.generate_hocr(input_file, output_hocr, output_text, options)
        try:
            _record(input_file, output_hocr)
        except Exception:
            # Measuring is advisory. The page keeps its reading; it is simply reported as not measured.
            pass

    def generate_pdf(self, input_file, output_pdf, output_text, options):
        self.native.generate_pdf(input_file, output_pdf, output_text, options)


@hookimpl(wrapper=True, tryfirst=True)
def get_ocr_engine(options):
    native = yield
    return MeasuringEngine(native)
