"""Fixed private OCRmyPDF wrapper for recognition-only angled text layers."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil

import ocrmypdf
from ocrmypdf import hookimpl
from ocrmypdf.pluginspec import OcrEngine


def _load(name, filename):
    path = Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_angles = _load('pdf_remediator_fixed_angles', 'ocr_angles.py')
_regions = _load('pdf_remediator_fixed_angle_regions', 'ocr_regions.py')
_evidence = _load('pdf_remediator_fixed_angle_evidence', 'ocr_angle_evidence.py')
_rescue = _load('pdf_remediator_fixed_angle_rescue', 'ocr_rescue.py')


class FixedAngleEngine(OcrEngine):
    def __init__(self, native):
        if native is None:
            raise ValueError('The fixed angle recognizer requires the qualified native OCR engine.')
        self.native = native

    def version(self):
        return self.native.version()

    def creator_tag(self, options):
        return self.native.creator_tag(options) + ' / PDF Remediator local angle recognition'

    def __str__(self):
        return str(self.native) + ' / local angle recognition'

    def languages(self, options):
        return self.native.languages(options)

    def get_orientation(self, input_file, options):
        return self.native.get_orientation(input_file, options)

    def get_deskew(self, input_file, options):
        return self.native.get_deskew(input_file, options)

    def generate_hocr(self, input_file, output_hocr, output_text, options):
        raise ValueError('The fixed angle recognizer requires its hidden PDF layer renderer.')

    def generate_pdf(self, input_file, output_pdf, output_text, options):
        if options.pdf_renderer != 'sandwich' or options.mode != 'skip':
            raise ValueError('The fixed angle recognizer only supports the preserving skip route and sandwich renderer.')
        match = re.fullmatch(r'([0-9]{6})_ocr\.png', Path(input_file).name)
        if not match or int(match[1]) < 1:
            raise ValueError('Angle OCR evidence has an unexpected native page filename.')
        page = int(match[1])
        destination = Path(os.environ['PDF_REMEDIATOR_ANGLE_EVIDENCE'])
        source_hash = os.environ['PDF_REMEDIATOR_ANGLE_SOURCE_SHA256']
        font = Path(ocrmypdf.__file__).resolve().parent / 'data/NotoSans-Regular.ttf'
        if (not destination.is_absolute() or not destination.is_dir()
                or not re.fullmatch('[0-9a-f]{64}', source_hash) or _evidence.digest(font) != _evidence.FONT_SHA256):
            raise ValueError('Angle OCR evidence source, directory or qualified-font binding is invalid.')
        module_paths = {'plugin_sha256': Path(__file__).resolve(), 'algorithm_sha256': Path(_angles.__file__),
                        'regions_sha256': Path(_regions.__file__), 'evidence_sha256': Path(_evidence.__file__),
                        'rescue_sha256': Path(_rescue.__file__)}
        binding = {key: _evidence.digest(path) for key, path in module_paths.items()}
        root = destination / f'{page:06d}'
        root.mkdir()
        shutil.copyfile(input_file, root / 'input.png')
        proof = _angles.recognize(input_file, output_pdf, output_text, options, _regions.regions, root / 'attempts', font,
                                  rescue_module=_rescue, region_module=_regions)
        shutil.copyfile(output_pdf, root / 'layer.pdf')
        shutil.copyfile(output_text, root / 'recognized.txt')
        if (binding != {key: _evidence.digest(path) for key, path in module_paths.items()}
                or _evidence.digest(font) != _evidence.FONT_SHA256):
            raise ValueError('Angle OCR implementation changed during recognition.')
        retained = {str(path.relative_to(root)).replace('\\', '/'): {'sha256': _evidence.digest(path), 'size': path.stat().st_size}
                    for path in sorted(root.rglob('*')) if path.is_file()}
        proof.update(schema=_evidence.SCHEMA, profile='angles', page=page, adapter_source_sha256=source_hash,
                     **binding, font_glyphs=_evidence.glyph_mapping(proof['selected_words'], font), retained_files=retained)
        with (destination / f'{page:06d}.json').open('x', encoding='utf-8') as stream:
            json.dump(proof, stream, indent=2, allow_nan=False)
            stream.write('\n')


@hookimpl(wrapper=True, tryfirst=True)
def get_ocr_engine(options):
    native = yield
    return FixedAngleEngine(native)
