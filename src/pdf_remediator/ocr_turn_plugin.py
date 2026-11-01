"""Fixed private OCRmyPDF wrapper: read each scanned page in its best right-angle turn, then place the text back.

Like the tilted-text profile it supplies the hidden text page itself (sandwich renderer). A page that reads best as it is takes
the ordinary Tesseract text page. Nothing here changes what the page looks like.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

from ocrmypdf import hookimpl
from ocrmypdf.pluginspec import OcrEngine
from PIL import Image


def _load(name, filename):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_turns = _load('pdf_remediator_fixed_turns', 'ocr_turns.py')
_confidence = _load('pdf_remediator_fixed_confidence', 'ocr_confidence.py')

_TRANSPOSE = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}


class FixedTurnEngine(OcrEngine):
    def __init__(self, native):
        if native is None:
            raise ValueError('The fixed turn recognizer requires the qualified native OCR engine.')
        self.native = native

    def version(self):
        return self.native.version()

    def creator_tag(self, options):
        return self.native.creator_tag(options) + ' / PDF Remediator local turn-first recognition'

    def __str__(self):
        return str(self.native) + ' / local turn-first recognition'

    def languages(self, options):
        return self.native.languages(options)

    def get_orientation(self, input_file, options):
        return self.native.get_orientation(input_file, options)

    def get_deskew(self, input_file, options):
        return self.native.get_deskew(input_file, options)

    def generate_hocr(self, input_file, output_hocr, output_text, options):
        raise ValueError('The fixed turn recognizer requires its hidden PDF text page.')

    def _score(self, image, scratch, label, options):
        longest = max(image.size)
        if longest > _turns.TRIAL_SIDE:
            k = _turns.TRIAL_SIDE / longest
            image = image.resize((max(1, int(image.size[0] * k)), max(1, int(image.size[1] * k))), Image.Resampling.BILINEAR)
        picture, hocr, text = scratch / f'{label}.png', scratch / f'{label}.hocr', scratch / f'{label}.txt'
        image.save(picture, dpi=(200, 200))
        self.native.generate_hocr(picture, hocr, text, options)
        return _turns.confident_words(hocr.read_text(encoding='utf-8', errors='replace'))

    def generate_pdf(self, input_file, output_pdf, output_text, options):
        if options.pdf_renderer != 'sandwich':
            raise ValueError('The fixed turn recognizer only supports the sandwich renderer.')
        input_file, output_pdf = Path(input_file), Path(output_pdf)
        match = re.fullmatch(r'([0-9]{6})_ocr\.png', input_file.name)
        if not match or int(match[1]) < 1:
            raise ValueError('Turn recognition evidence has an unexpected native page filename.')
        page = int(match[1])
        destination = Path(os.environ['PDF_REMEDIATOR_TURN_EVIDENCE'])
        source_hash = os.environ['PDF_REMEDIATOR_TURN_SOURCE_SHA256']
        if not destination.is_absolute() or not destination.is_dir() or not re.fullmatch('[0-9a-f]{64}', source_hash):
            raise ValueError('Turn recognition evidence source or directory binding is invalid.')
        binding = {'plugin_sha256': _turns.digest(Path(__file__).resolve()), 'algorithm_sha256': _turns.digest(_turns.__file__)}
        with Image.open(input_file) as opened:
            opened.load()
            original = opened.copy()
            dpi = opened.info.get('dpi')
        if original.mode not in ('1', 'L', 'RGB'):
            original = original.convert('RGB')
        with tempfile.TemporaryDirectory(dir=output_pdf.parent) as folder:
            scratch = Path(folder)
            scores = {turn: self._score(original if turn == 0 else original.transpose(_TRANSPOSE[turn]), scratch, f'trial{turn}', options)
                      for turn in _turns.TURNS}
            turn, reason = _turns.choose_turn(scores)
            source = input_file
            if turn:
                source = scratch / 'turned.png'
                original.transpose(_TRANSPOSE[turn]).save(source, **({'dpi': dpi} if dpi else {}))
            self.native.generate_pdf(source, scratch / 'layer.pdf', output_text, options)
            try:
                # The run asks Tesseract for a tab-separated page as well; its word confidences say how surely this page was read.
                reading = _confidence.measure(_confidence.tsv_words((scratch / 'layer.tsv').read_text(encoding='utf-8', errors='replace')))
            except (OSError, ValueError):
                reading = None
            _turns.place_text_layer(scratch / 'layer.pdf', output_pdf, turn)
        proof = {'schema': _turns.SCHEMA, 'profile': 'turns', 'version': _turns.VERSION, 'page': page, 'adapter_source_sha256': source_hash,
                 **binding, 'turn_ccw': turn, 'reason': reason, 'trial_scores': {str(k): v for k, v in scores.items()},
                 'image_size': list(original.size), 'dpi': list(dpi) if dpi else None, 'reading': reading}
        with (destination / f'{page:06d}.json').open('x', encoding='utf-8') as stream:
            json.dump(proof, stream, indent=2, allow_nan=False)
            stream.write('\n')


@hookimpl(wrapper=True, tryfirst=True)
def get_ocr_engine(options):
    native = yield
    return FixedTurnEngine(native)
