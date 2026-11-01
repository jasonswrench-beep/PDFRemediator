"""Authored local controls for the fixed angle adapter; no native OCR runs."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pikepdf
import pytest
from PIL import Image, ImageDraw
import reportlab
from fontTools.ttLib import TTFont

from pdf_remediator import ocr, ocr_angles, ocr_regions, ocr_rescue
from pdf_remediator import ocr_angle_evidence as evidence


def _hidden_control(path, font_path, size, dpi, visible=False, texts=('Example',)):
    """Author mapped, embedded Type0 words without optional OCR/FPDF."""
    painted_texts = [word + (' ' if index < len(texts) - 1 else '') for index, word in enumerate(texts)]
    text = ''.join(painted_texts)
    with TTFont(font_path) as font:
        cmap = font.getBestCmap()
        gids = b''.join(font.getGlyphID(cmap.get(point, '.notdef')).to_bytes(2, 'big') for point in range(128))
    with pikepdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(size[0] * 72 / dpi, size[1] * 72 / dpi))
        descriptor = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor,
            FontName=pikepdf.Name.SyntheticVera, Flags=4, FontBBox=pikepdf.Array([-1000, -1000, 2000, 2000]),
            ItalicAngle=0, Ascent=1000, Descent=-300, CapHeight=800, StemV=80,
            FontFile2=pdf.make_stream(Path(font_path).read_bytes())))
        descendant = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2,
            BaseFont=pikepdf.Name.SyntheticVera, FontDescriptor=descriptor, DW=600,
            CIDSystemInfo=pikepdf.Dictionary(Registry='Adobe', Ordering='Identity', Supplement=0),
            CIDToGIDMap=pdf.make_stream(gids)))
        points = sorted(set(map(ord, text)))
        cmap = (b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n'
                b'/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
                b'/CMapName /Synthetic-UCS def /CMapType 2 def\n'
                b'1 begincodespacerange <0000> <ffff> endcodespacerange\n' +
                f'{len(points)} beginbfchar\n'.encode() +
                b''.join(f'<{point:04x}> <{point:04x}>\n'.encode() for point in points) +
                b'endbfchar endcmap CMapName currentdict /CMap defineresource pop end end')
        mapped = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0,
            BaseFont=pikepdf.Name.SyntheticVera, Encoding=pikepdf.Name('/Identity-H'),
            DescendantFonts=pikepdf.Array([descendant]), ToUnicode=pdf.make_stream(cmap)))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=mapped))
        paints = ' '.join(f"1 0 0 1 1 {10+index*10} Tm <{''.join(f'{ord(char):04x}' for char in word)}> Tj"
                          for index, word in enumerate(painted_texts))
        page.Contents = pdf.make_stream(f'BT /F1 8 Tf {0 if visible else 3} Tr {paints} ET'.encode())
        pdf.save(path, deterministic_id=True)


def _authored_proof(directory, font_path, source_hash, page=1):
    """Keep native-shaped hOCR plus recomputable, agreeing PSM alternatives."""
    root = directory / f'{page:06d}'
    attempts_dir = root / 'attempts'
    attempts_dir.mkdir(parents=True)
    with Image.new('RGB', (200, 100), 'white') as image:
        image.save(root / 'input.png', dpi=(300, 300))
    with Image.open(root / 'input.png') as image:
        dpi = image.info['dpi'][0]
        with image.convert('RGB') as rgb:
            pixel_hash = __import__('hashlib').sha256(rgb.tobytes()).hexdigest()
    attempts, candidates = [], []
    for number, psm in enumerate((7, 13)):
        base = attempts_dir / f'{number:03d}'
        with Image.new('RGB', (144, 64), 'white') as raster:
            raster.save(base.with_suffix('.png'), dpi=(300, 300))
        base.with_suffix('.hocr').write_text(
            '<html><body><span class="ocrx_word" title="bbox 12 12 112 42; x_wconf 95">Example</span></body></html>',
            encoding='utf-8')
        base.with_suffix('.txt').write_text('Example\n', encoding='utf-8')
        attempt = {'number': number, 'angle': 0, 'psm': psm,
            'region': {'bounds': [20, 20, 80, 40], 'component_count': 7, 'count': 7, 'kind': 'word', 'line_id': 0},
            'crop_box': [20, 20, 80, 40], 'working_size': [200, 100], 'rotated_size': [200, 100],
            'scale': 1, 'resize': [2, 2], 'raster_size': [144, 64], 'padding': 12, 'word_count': 1,
            'raster_sha256': evidence.digest(base.with_suffix('.png')), 'hocr_sha256': evidence.digest(base.with_suffix('.hocr'))}
        attempts.append(attempt)
        candidates.extend(ocr_angles.candidate_records(ocr_angles.parse_hocr(base.with_suffix('.hocr')), attempt, [200, 100]))
    with Image.open(root / 'input.png') as image, image.convert('RGB') as rgb:
        selected = json.loads(json.dumps(ocr_angles.select_words(candidates, source_image=rgb)))
    assert len(selected) == 1 and selected[0]['agreement_votes'] == 2
    _hidden_control(root / 'layer.pdf', font_path, [200, 100], dpi)
    (root / 'recognized.txt').write_text('Example\n', encoding='utf-8')
    binding = {key: evidence.digest(Path(ocr.__file__).with_name(name)) for key, name in (
        ('plugin_sha256', 'ocr_angle_plugin.py'), ('algorithm_sha256', 'ocr_angles.py'), ('regions_sha256', 'ocr_regions.py'),
        ('evidence_sha256', 'ocr_angle_evidence.py'), ('rescue_sha256', 'ocr_rescue.py'))}
    proof = {'schema': evidence.SCHEMA, 'profile': 'angles', 'page': page, 'adapter_source_sha256': source_hash,
        **binding, 'version': ocr_angles.VERSION, 'image_size': [200, 100], 'dpi': dpi, 'input_RGB_sha256': pixel_hash,
        'font_sha256': evidence.digest(font_path), 'working_size': [200, 100], 'attempt_count': 2,
        'attempts': attempts, 'selected_words': selected, 'output_layer_sha256': evidence.digest(root / 'layer.pdf'),
        'seconds': 1, 'renderer': 'invisible-affine', 'accuracy': 'needs-review', 'completeness': 'needs-review',
        'reading_order': 'needs-review', 'font_glyphs': evidence.glyph_mapping(selected, font_path),
        'word_separator_policy': 'explicit-trailing-u0020-between-selected-words-1',
        'word_separator_count': max(0, len(selected) - 1)}
    _empty_optional_traces(directory, proof)
    proof['retained_files'] = {str(path.relative_to(root)).replace('\\', '/'):
        {'sha256': evidence.digest(path), 'size': path.stat().st_size} for path in root.rglob('*') if path.is_file()}
    (directory / f'{page:06d}.json').write_text(json.dumps(proof), encoding='utf-8')
    return proof, binding


def _empty_optional_traces(directory, proof):
    """Legacy fixtures explicitly prove that source-derived optional work is empty."""
    root = directory / f"{proof['page']:06d}"
    candidates = [word for attempt in proof['attempts'] for word in ocr_angles.candidate_records(
        ocr_angles.parse_hocr(root / 'attempts' / f"{attempt['number']:03d}.hocr"), attempt, proof['image_size'])]
    with Image.open(root / 'input.png') as image, image.convert('RGB') as native:
        selected = ocr_angles.select_words(candidates, source_image=native)
        plans = ocr_angles.confirmation_plans(native, candidates, selected)
        proposals = ocr_rescue.proposals(native, selected, ocr_regions)
    assert plans == [] and proposals['plans'] == []
    proof['baseline_attempt_count'] = len(proof['attempts'])
    proof['confirmation_trace'] = {'plans': plans, 'attempted_plans': 0, 'budget_skipped': None}
    proof['rescue_trace'] = {'proposals': proposals, 'attempted_plans': 0, 'budget_skipped': None}


@pytest.fixture
def qualified_font_double(tmp_path, monkeypatch):
    """Use an actual, installed test font; this does not qualify a release font."""
    path = tmp_path / 'ocr-runtime/Lib/site-packages/ocrmypdf/data/NotoSans-Regular.ttf'
    path.parent.mkdir(parents=True)
    shutil.copyfile(Path(reportlab.__file__).parent / 'fonts/Vera.ttf', path)
    monkeypatch.setattr(evidence, 'FONT_SHA256', evidence.digest(path))
    monkeypatch.setattr(ocr, 'FONT_SHA256', evidence.digest(path))
    return path


@pytest.mark.parametrize('damage', ['none', 'minimal', 'source', 'module', 'version', 'font', 'glyph', 'review',
    'dpi', 'size', 'working', 'pixel-hash', 'duration', 'attempt-count', 'attempt-hash', 'region', 'crop', 'frame',
    'resize', 'padding', 'refinement', 'quad', 'votes', 'word', 'raw-index', 'missing-file', 'changed-hocr',
    'extra-file', 'extra-page', 'missing-page', 'recognized-text', 'visible-layer', 'layer-hash',
    'separator-policy', 'separator-count', 'separator-count-bool'])
def test_angle_evidence_requires_complete_bound_native_results(tmp_path, monkeypatch, qualified_font_double, damage):
    directory = tmp_path / 'evidence'
    source_hash = '1' * 64
    proof, binding = _authored_proof(directory, qualified_font_double, source_hash)
    root = directory / '000001'
    if damage == 'minimal':
        proof = {key: proof[key] for key in ('schema', 'profile', 'page', 'adapter_source_sha256', *binding)}
    elif damage in ('source', 'module', 'version', 'font', 'review', 'pixel-hash', 'layer-hash'):
        key = {'source': 'adapter_source_sha256', 'module': 'algorithm_sha256', 'version': 'version', 'font': 'font_sha256',
               'review': 'accuracy', 'pixel-hash': 'input_RGB_sha256', 'layer-hash': 'output_layer_sha256'}[damage]
        proof[key] = 'unbound'
    elif damage == 'separator-policy':
        proof['word_separator_policy'] = 'unbound'
    elif damage == 'separator-count':
        proof['word_separator_count'] = 1
    elif damage == 'separator-count-bool':
        proof['word_separator_count'] = False
    elif damage == 'glyph':
        proof['font_glyphs'][str(ord('E'))] = 'wrong-glyph'
    elif damage == 'dpi':
        proof['dpi'] = float('nan')
    elif damage == 'size':
        proof['image_size'] = [100_000, 100_000]
    elif damage == 'working':
        proof['working_size'] = [190, 100]
    elif damage == 'duration':
        proof['seconds'] = 1000
    elif damage == 'attempt-count':
        proof['attempt_count'] = 1
    elif damage == 'attempt-hash':
        proof['attempts'][0]['hocr_sha256'] = '0' * 64
    elif damage == 'region':
        proof['attempts'][0]['region']['bounds'][0] = -1
    elif damage == 'crop':
        proof['attempts'][0]['crop_box'][0] += 1
    elif damage == 'frame':
        proof['attempts'][0]['rotated_size'][0] += 1
    elif damage == 'resize':
        proof['attempts'][0]['resize'][0] = float('inf')
    elif damage == 'padding':
        proof['attempts'][0]['padding'] = True
    elif damage == 'refinement':
        proof['attempts'][0]['refined_from'] = {'attempt': 0, 'word_index': 0}
    elif damage == 'quad':
        proof['selected_words'][0]['quad'][0][0] += 10
    elif damage == 'votes':
        proof['selected_words'][0]['agreement_votes'] = 3
    elif damage == 'word':
        proof['selected_words'][0]['text'] = 'Invented'
    elif damage == 'raw-index':
        proof['selected_words'][0]['raw_word_index'] = False
    elif damage == 'missing-file':
        (root / 'attempts/001.txt').unlink()
    elif damage == 'changed-hocr':
        (root / 'attempts/000.hocr').write_text('changed native result', encoding='utf-8')
    elif damage == 'extra-file':
        (root / 'unexplained.txt').write_text('unexpected', encoding='utf-8')
    elif damage == 'extra-page':
        (directory / '000002.json').write_text('{}', encoding='utf-8')
    elif damage == 'missing-page':
        (directory / '000001.json').unlink()
    elif damage == 'recognized-text':
        (root / 'recognized.txt').write_text('Invented\n', encoding='utf-8')
        proof['retained_files']['recognized.txt'] = {'sha256': evidence.digest(root / 'recognized.txt'), 'size': (root / 'recognized.txt').stat().st_size}
    elif damage == 'visible-layer':
        _hidden_control(root / 'layer.pdf', qualified_font_double, [200, 100], proof['dpi'], visible=True)
        proof['output_layer_sha256'] = evidence.digest(root / 'layer.pdf')
        proof['retained_files']['layer.pdf'] = {'sha256': proof['output_layer_sha256'], 'size': (root / 'layer.pdf').stat().st_size}
    if damage != 'missing-page':
        (directory / '000001.json').write_text(json.dumps(proof), encoding='utf-8')
    if damage == 'none':
        result = evidence.validate_pages(directory, [1], binding, qualified_font_double, source_hash, 1)
        assert len(result) == 1 and result[0]['accuracy'] == result[0]['completeness'] == result[0]['reading_order'] == 'needs-review'
        assert result[0]['selected_words'][0]['text'] == 'Example'
    else:
        with pytest.raises((ValueError, TypeError, KeyError, OSError), match='[Ee]vidence|No such|cannot find|path specified'):
            evidence.validate_pages(directory, [1], binding, qualified_font_double, source_hash, 1)


@pytest.mark.parametrize('mode', ['skip', 'textless'])
def test_angle_driver_uses_fixed_plugin_and_preserving_native_route(tmp_path, monkeypatch, qualified_font_double, mode):
    source, destination = tmp_path / 'source.pdf', tmp_path / 'output.pdf'
    source.write_bytes(b'Named source bytes; this test doubles PDF inspection explicitly.')
    before = {'features': {}, 'structure': {'present': False}, 'page_count': 1,
        'pages': [{'page': 1, 'class': 'scanned', 'text_characters': 0,
                   'content': {'image_objects': 1, 'errors': [], 'warnings': [], 'counts': {'text_paints': 0}}}]}
    after = deepcopy(before)
    after['pages'][0].update({'class': 'mixed', 'text_characters': 7})
    monkeypatch.setattr(ocr, 'inspect_pdf', lambda path, **kwargs: deepcopy(before if Path(path) == source else after))
    monkeypatch.setattr(ocr, 'compare_fidelity', lambda *a, **kw: {'pages': [{'page': 1,
        'render_status': 'pass', 'dimensions_status': 'pass', 'page_boxes_status': 'pass', 'annotations_status': 'pass',
        'text': {'added_tokens': 1, 'removed_tokens': 0}}], 'checks': []})
    monkeypatch.setattr(ocr, 'ocr_availability', lambda settings: {'available': True, 'message': 'Named availability double'})
    monkeypatch.setattr(ocr, 'runtime_font', lambda python: qualified_font_double)
    for key in evidence.ENV_KEYS:
        monkeypatch.setenv(key, 'untrusted ambient value')
    version = tmp_path / 'version.txt'
    version.write_text('17.13.0\n', encoding='utf-8')

    def named_native_double(command, directory, timeout, memory, cancel, env):
        if '--version' in command:
            assert all(key not in env for key in evidence.ENV_KEYS)
            return {'status': 'completed', 'stdout': str(version)}
        assert command[command.index('--mode') + 1] == 'skip'
        assert command[command.index('--pdf-renderer') + 1] == 'sandwich'
        assert command.count('--max-ocr-image-mpixels') == 1 and command[command.index('--max-ocr-image-mpixels') + 1] == '32'
        assert Path(command[command.index('--plugin') + 1]) == Path(ocr.__file__).resolve().with_name('ocr_angle_plugin.py')
        assert command.count('--plugin') == 1 and '--force-ocr' not in command
        assert ('--pages' in command) == (mode == 'textless')
        if mode == 'textless':
            assert command[command.index('--pages') + 1] == '1'
        _authored_proof(Path(env['PDF_REMEDIATOR_ANGLE_EVIDENCE']), qualified_font_double, ocr.sha(source))
        destination.write_bytes(b'Named output bytes; all real preservation behavior is tested separately.')
        return {'status': 'completed', 'returncode': 0}

    monkeypatch.setattr(ocr, 'run', named_native_double)
    result = ocr.run_ocr(source, destination, {'project_root': tmp_path / 'project', 'ocr_profile': 'angles'}, tmp_path / 'job', mode=mode)
    assert result['status'] == 'completed' and result['preservation']['status'] == 'pass'
    assert result['requested_mode'] == mode and result['native_mode'] == 'skip'
    assert result['recognition_alternatives']['pages'][0]['page'] == 1
    assert result['document_network_calls'] == 0 and result['no_force'] is True
    assert result['human_review_pending'] == ['OCR accuracy', 'OCR completeness', 'reading order']
    if mode == 'textless':
        assert result['textless_page_coverage']['status'] == 'pass'


def test_angle_driver_refuses_redo_before_any_inspection_or_process(tmp_path, monkeypatch):
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'No parsing allowed for an unsupported combination.')
    monkeypatch.setattr(ocr, 'inspect_pdf', lambda *a, **kw: pytest.fail('Unsupported redo reached inspection'))
    monkeypatch.setattr(ocr, 'run', lambda *a, **kw: pytest.fail('Unsupported redo reached native process'))
    result = ocr.run_ocr(source, tmp_path / 'out.pdf', {'ocr_profile': 'angles'}, tmp_path / 'job', mode='redo')
    assert result['status'] == 'unsupported' and 'redo' in result['error']
    assert sorted(path.name for path in tmp_path.iterdir()) == ['source.pdf']


def test_angle_font_mapping_refuses_an_uncovered_character(qualified_font_double):
    with pytest.raises(ValueError, match='absent'):
        evidence.glyph_mapping([{'text': '\U0010ffff'}], qualified_font_double)


@pytest.mark.parametrize('size,angle', [([200, 100], 0), ([200, 100], 90), ([200, 100], -35), ([201, 103], 45), ([201, 103], 270)])
def test_proof_rotation_bounds_match_pillow_without_allocating_native_rasters(size, angle):
    with Image.new('L', tuple(size)) as image:
        with image.rotate(angle, expand=True) as rotated:
            assert evidence._rotated_size(size, angle) == list(rotated.size)


def _refresh_source_fit_rasters(directory, proof, *, empty_optional=True):
    """Rebuild every retained attempt from the current native pixels and hOCR."""
    root = directory / '000001'
    candidates = []
    with Image.open(root / 'input.png') as image, image.convert('RGB') as native:
        proof['input_RGB_sha256'] = __import__('hashlib').sha256(native.tobytes()).hexdigest()
        for attempt in proof['attempts']:
            bounds = attempt['crop_box']
            resized = [round((bounds[2] - bounds[0]) * attempt['resize'][0]),
                       round((bounds[3] - bounds[1]) * attempt['resize'][1])]
            base = root / 'attempts' / f"{attempt['number']:03d}"
            with native.crop(bounds) as crop, crop.resize(tuple(resized), Image.Resampling.LANCZOS) as fitted:
                with Image.new('RGB', tuple(attempt['raster_size']), 'white') as raster:
                    raster.paste(fitted, (12, 12))
                    raster.save(base.with_suffix('.png'), dpi=(300, 300))
            attempt['raster_sha256'] = evidence.digest(base.with_suffix('.png'))
            candidates.extend(ocr_angles.candidate_records(
                ocr_angles.parse_hocr(base.with_suffix('.hocr')), attempt, proof['image_size']))
        selected = json.loads(json.dumps(ocr_angles.select_words(candidates, source_image=native)))
    proof['retained_files'] = {str(path.relative_to(root)).replace('\\', '/'):
        {'sha256': evidence.digest(path), 'size': path.stat().st_size} for path in root.rglob('*') if path.is_file()}
    if empty_optional:
        _empty_optional_traces(directory, proof)
    return selected


def _active_source_fit_proof(directory, font_path, source_hash):
    """Author two supported geometries whose source ink activates substitution."""
    proof, binding = _authored_proof(directory, font_path, source_hash)
    root = directory / '000001'
    with Image.new('RGB', (200, 100), 'white') as image:
        for number in range(80):
            image.putpixel((25 + number % 16, 22 + number // 16), (0, 0, 0))
        image.save(root / 'input.png', dpi=(proof['dpi'], proof['dpi']))
    attempts = []
    for number, (bounds, bbox, confidence, psm) in enumerate([
            ([20, 20, 80, 40], [12, 12, 112, 42], 95, 7),
            ([20, 20, 80, 40], [12, 12, 112, 42], 95, 13),
            ([20, 20, 70, 35], [12, 12, 102, 32], 74, 7),
            ([20, 20, 70, 35], [12, 12, 102, 32], 74, 13)]):
        base = root / 'attempts' / f'{number:03d}'
        base.with_suffix('.hocr').write_text(
            '<html><body><span class="ocrx_word" title="bbox '
            + ' '.join(map(str, bbox)) + f'; x_wconf {confidence}">Example</span></body></html>', encoding='utf-8')
        base.with_suffix('.txt').write_text('Example\n', encoding='utf-8')
        attempts.append({'number': number, 'angle': 0, 'psm': psm,
            'region': {'bounds': bounds, 'component_count': 7, 'count': 7, 'kind': 'word', 'line_id': 0},
            'crop_box': bounds, 'working_size': [200, 100], 'rotated_size': [200, 100],
            'scale': 1, 'resize': [2, 2],
            'raster_size': [(bounds[2] - bounds[0]) * 2 + 24, (bounds[3] - bounds[1]) * 2 + 24],
            'padding': 12, 'word_count': 1, 'hocr_sha256': evidence.digest(base.with_suffix('.hocr'))})
    proof['attempts'], proof['attempt_count'] = attempts, len(attempts)
    proof['selected_words'] = _refresh_source_fit_rasters(directory, proof)
    assert len(proof['selected_words']) == 1 and proof['selected_words'][0]['attempt'] == 2
    (directory / '000001.json').write_text(json.dumps(proof), encoding='utf-8')
    return proof, binding


def test_angle_evidence_accepts_a_native_pixel_driven_tighter_word_selection(tmp_path, qualified_font_double):
    directory, source_hash = tmp_path / 'active-fit', '2' * 64
    proof, binding = _active_source_fit_proof(directory, qualified_font_double, source_hash)
    assert proof['selected_words'][0]['confidence'] == 74
    assert proof['selected_words'][0]['agreement_votes'] >= 2
    result = evidence.validate_pages(directory, [1], binding, qualified_font_double, source_hash, 1)
    assert result[0]['selected_words'] == proof['selected_words']
    assert result[0]['selected_words'][0]['quad'] == [[20, 20], [65, 20], [65, 30], [20, 30]]
    assert result[0]['accuracy'] == result[0]['completeness'] == result[0]['reading_order'] == 'needs-review'


def test_angle_evidence_recomputes_source_fit_after_consistent_native_pixel_changes(tmp_path, qualified_font_double):
    directory, source_hash = tmp_path / 'changed-active-fit', '3' * 64
    proof, binding = _active_source_fit_proof(directory, qualified_font_double, source_hash)
    root = directory / '000001'
    old_selected, old_pixel_hash = deepcopy(proof['selected_words']), proof['input_RGB_sha256']
    hocr_bytes = {path.name: path.read_bytes() for path in (root / 'attempts').glob('*.hocr')}
    with Image.open(root / 'input.png') as image, image.convert('RGB') as changed:
        changed.putpixel((25, 32), (0, 0, 0))
        changed.putpixel((26, 32), (0, 0, 0))
        changed.save(root / 'input.png', dpi=(proof['dpi'], proof['dpi']))
    recomputed = _refresh_source_fit_rasters(directory, proof)
    assert recomputed[0]['attempt'] == 0 and recomputed[0]['confidence'] == 95
    assert proof['input_RGB_sha256'] != old_pixel_hash
    assert hocr_bytes == {path.name: path.read_bytes() for path in (root / 'attempts').glob('*.hocr')}
    # Rebind the obsolete selection to its new native raster, so no stale hash
    # or geometry field can cause rejection before source-ink recomputation.
    for word in old_selected:
        word['raster_sha256'] = proof['attempts'][word['attempt']]['raster_sha256']
    proof['selected_words'] = old_selected
    (directory / '000001.json').write_text(json.dumps(proof), encoding='utf-8')
    with pytest.raises(ValueError, match='selected words, agreement or inverse geometry'):
        evidence.validate_pages(directory, [1], binding, qualified_font_double, source_hash, 1)


def _active_rescue_proof(directory, font_path, source_hash):
    """Author actual component-line context and all four native controls per child."""
    proof, binding = _authored_proof(directory, font_path, source_hash)
    root = directory / '000001'
    with Image.new('RGB', (320, 200), 'white') as native:
        draw = ImageDraw.Draw(native)
        for left in (20, 28, 36, 44, 52, 60, 80, 88):
            draw.rectangle((left, 110, left+4, 129), fill='black')
        for left in (110, 123, 136, 149, 162, 175):
            draw.rectangle((left, 90, left+7, 129), fill='black')
        native.save(root / 'input.png', dpi=(300, 300))
    proof['image_size'] = proof['working_size'] = [320, 200]
    attempts, candidates = [], []

    def append_attempt(native, bounds, text, psm, stretch=1, *, phase=None, plan_index=None, components=6):
        number = len(attempts)
        width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
        scale = 64/height if phase else min(2, 64/height)
        resized = [max(1, round(width*scale*stretch)), max(1, round(height*scale))]
        base = root / 'attempts' / f'{number:03d}'
        with native.crop(bounds) as crop, crop.resize(tuple(resized), Image.Resampling.LANCZOS) as fitted:
            with Image.new('RGB', (resized[0]+24, resized[1]+24), 'white') as raster:
                raster.paste(fitted, (12, 12))
                raster.save(base.with_suffix('.png'), dpi=(300, 300))
        base.with_suffix('.hocr').write_text(
            f'<html><body><span class="ocrx_word" title="bbox 12 12 {resized[0]+12} {resized[1]+12}; '
            f'x_wconf 95">{text}</span></body></html>', encoding='utf-8')
        base.with_suffix('.txt').write_text(text+'\n', encoding='utf-8')
        attempt = {'number': number, 'angle': 0, 'psm': psm,
            'region': {'bounds': bounds, 'component_count': components, 'count': components,
                       'kind': 'anchored-native-height-group' if phase else 'word', 'line_id': -1 if phase else 0},
            'crop_box': bounds, 'working_size': [320, 200], 'rotated_size': [320, 200], 'scale': 1,
            'resize': [resized[0]/width, resized[1]/height], 'raster_size': [resized[0]+24, resized[1]+24],
            'padding': 12, 'word_count': 1, 'raster_sha256': evidence.digest(base.with_suffix('.png')),
            'hocr_sha256': evidence.digest(base.with_suffix('.hocr'))}
        if phase:
            attempt.update({'phase': phase, 'plan_index': plan_index, 'target_height': 64})
        attempts.append(attempt)
        candidates.extend(ocr_angles.candidate_records(ocr_angles.parse_hocr(base.with_suffix('.hocr')), attempt, [320, 200]))

    with Image.open(root / 'input.png') as image, image.convert('RGB') as native:
        proof['dpi'] = image.info['dpi'][0]
        proof['input_RGB_sha256'] = __import__('hashlib').sha256(native.tobytes()).hexdigest()
        for psm in (7, 13):
            append_attempt(native, [110, 90, 183, 130], 'Example', psm)
        baseline = ocr_angles.select_words(candidates, source_image=native)
        assert len(baseline) == 1 and baseline[0]['confidence'] == 95
        confirmation = ocr_angles.confirmation_plans(native, candidates, baseline)
        assert confirmation == []
        proposals = json.loads(json.dumps(ocr_rescue.proposals(native, baseline, ocr_regions)))
        assert sorted(plan['component_count'] for plan in proposals['plans']) == [2, 6]
        for index, plan in enumerate(proposals['plans']):
            for target, stretch, psm in ocr_angles.OPTIONAL_CONTROLS:
                assert target == 64
                append_attempt(native, plan['bounds'], 'By' if plan['component_count'] == 2 else 'Caption',
                               psm, stretch, phase='rescue', plan_index=index, components=plan['component_count'])
        selected = ocr_angles.add_rescue_words(baseline, [word for word in candidates if word.get('phase') == 'rescue'])
    proof.update({'attempts': attempts, 'attempt_count': len(attempts), 'baseline_attempt_count': 2,
        'confirmation_trace': {'plans': confirmation, 'attempted_plans': 0, 'budget_skipped': None},
        'rescue_trace': {'proposals': proposals, 'attempted_plans': len(proposals['plans']), 'budget_skipped': None},
        'selected_words': json.loads(json.dumps(selected)), 'font_glyphs': evidence.glyph_mapping(selected, font_path),
        'word_separator_count': max(0, len(selected) - 1)})
    _hidden_control(root / 'layer.pdf', font_path, [320, 200], proof['dpi'], texts=[word['text'] for word in selected])
    proof['output_layer_sha256'] = evidence.digest(root / 'layer.pdf')
    (root / 'recognized.txt').write_text(' '.join(word['text'] for word in selected)+'\n', encoding='utf-8')
    proof['retained_files'] = {str(path.relative_to(root)).replace('\\', '/'):
        {'sha256': evidence.digest(path), 'size': path.stat().st_size} for path in root.rglob('*') if path.is_file()}
    (directory / '000001.json').write_text(json.dumps(proof), encoding='utf-8')
    # Match the plugin's retained JSON: shared in-memory crop lists must not
    # make changing a proposal also mutate the independently retained attempt.
    return json.loads(json.dumps(proof)), binding


def test_angle_evidence_accepts_complete_source_anchored_rescue_controls(tmp_path, qualified_font_double):
    directory, source_hash = tmp_path / 'active-rescue', '4'*64
    proof, binding = _active_rescue_proof(directory, qualified_font_double, source_hash)
    assert proof['baseline_attempt_count'] == 2 and proof['attempt_count'] == 10
    assert [word['text'] for word in proof['selected_words']] == ['Caption', 'By', 'Example']
    baseline = next(word for word in proof['selected_words'] if word['text'] == 'Example')
    assert baseline['attempt'] == 0 and baseline['agreement_votes'] == 2 and 'phase' not in baseline
    for index in range(2):
        group = [attempt for attempt in proof['attempts'] if attempt.get('plan_index') == index]
        assert len(group) == 4
        left, top, right, bottom = proof['rescue_trace']['proposals']['plans'][index]['bounds']
        width, height = right-left, bottom-top
        assert [(attempt['target_height'], attempt['psm'], attempt['resize']) for attempt in group] == [
            (target, psm, [round(width*target/height*stretch)/width, target/height])
            for target, stretch, psm in ocr_angles.OPTIONAL_CONTROLS]
    result = evidence.validate_pages(directory, [1], binding, qualified_font_double, source_hash, 1)
    assert result[0]['selected_words'] == proof['selected_words']
    assert result[0]['accuracy'] == result[0]['completeness'] == result[0]['reading_order'] == 'needs-review'


@pytest.mark.parametrize('damage', ['plan', 'anchor', 'pixels', 'partial-control', 'new-phase', 'missing-binding', 'raster'])
def test_angle_evidence_recomputes_anchored_rescue_and_refuses_incomplete_or_unbound_results(
        tmp_path, qualified_font_double, damage):
    directory, source_hash = tmp_path / 'damaged-rescue', '5'*64
    proof, binding = _active_rescue_proof(directory, qualified_font_double, source_hash)
    root = directory / '000001'
    if damage == 'plan':
        proof['rescue_trace']['proposals']['plans'][0]['bounds'][0] += 1
    elif damage == 'anchor':
        proof['rescue_trace']['proposals']['plans'][0]['anchor']['reference']['attempt'] += 1
    elif damage == 'pixels':
        with Image.open(root / 'input.png') as image, image.convert('RGB') as changed:
            ImageDraw.Draw(changed).rectangle((110, 90, 183, 130), fill='white')
            changed.save(root / 'input.png', dpi=(proof['dpi'], proof['dpi']))
        _refresh_source_fit_rasters(directory, proof, empty_optional=False)
        for word in proof['selected_words']:
            word['raster_sha256'] = proof['attempts'][word['attempt']]['raster_sha256']
    elif damage == 'partial-control':
        last = proof['attempts'].pop()
        proof['attempt_count'] -= 1
        for extension in ('png', 'hocr', 'txt'):
            relative = f"attempts/{last['number']:03d}.{extension}"
            (root / relative).unlink()
            del proof['retained_files'][relative]
    elif damage == 'new-phase':
        proof['attempts'][2]['phase'] = 'unreviewed'
    elif damage == 'missing-binding':
        del binding['rescue_sha256']
        del proof['rescue_sha256']
    else:
        attempt = proof['attempts'][2]
        path = root / 'attempts/002.png'
        with Image.open(path) as image, image.convert('RGB') as changed:
            changed.putpixel((0, 0), (0, 0, 0))
            changed.save(path, dpi=(300, 300))
        attempt['raster_sha256'] = evidence.digest(path)
        proof['retained_files']['attempts/002.png'] = {'sha256': evidence.digest(path), 'size': path.stat().st_size}
        for word in proof['selected_words']:
            if word['attempt'] == 2:
                word['raster_sha256'] = attempt['raster_sha256']
    (directory / '000001.json').write_text(json.dumps(proof), encoding='utf-8')
    expected = {'plan': 'optional plans do not match source pixels', 'anchor': 'optional plans do not match source pixels',
        'pixels': 'optional plans do not match source pixels', 'partial-control': 'incomplete paired recognition',
        'new-phase': 'invalid optional attempt provenance', 'missing-binding': 'all five implementation bindings',
        'raster': 'crop pixels do not correspond'}
    with pytest.raises(ValueError, match=expected[damage]):
        evidence.validate_pages(directory, [1], binding, qualified_font_double, source_hash, 1)
