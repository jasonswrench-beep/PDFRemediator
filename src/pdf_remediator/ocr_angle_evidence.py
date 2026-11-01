"""Bounded verification of the fixed local angle recognizer's retained proof.

The optional OCR runtime creates the layer. This module only reads evidence;
it does not import OCRmyPDF or FPDF, run recognition, or approve its meaning.
"""
from pathlib import Path
import hashlib
import json
import math
import re

from PIL import Image

FONT_SHA256 = '2ec33f84606cbaa0a1a944488e14f97faf2f6a25ecdd8354f5358f06da13c7d9'
SCHEMA = 'phase1-ocr-angle-recognition-3'
WORD_SEPARATOR_POLICY = 'explicit-trailing-u0020-between-selected-words-1'
ENV_KEYS = ('PDF_REMEDIATOR_ANGLE_EVIDENCE', 'PDF_REMEDIATOR_ANGLE_SOURCE_SHA256')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def runtime_font(ocr_python):
    root = Path(ocr_python).resolve().parent
    if root.name.lower() == 'scripts':
        root = root.parent
    return root / 'Lib/site-packages/ocrmypdf/data/NotoSans-Regular.ttf'


def glyph_mapping(words, font_path):
    """Bind every selected Unicode codepoint to the qualified font's cmap."""
    from fontTools.ttLib import TTFont
    with TTFont(font_path) as font:
        cmap = font.getBestCmap()
        points = sorted({ord(char) for word in words for char in word['text']})
        if points and len(words) > 1 and 32 not in points:
            points.append(32)
            points.sort()
        if not points or any(not cmap.get(point) for point in points):
            raise ValueError('Angle OCR evidence contains characters absent from the qualified font.')
        return {str(point): cmap[point] for point in points}


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _size(value, maximum):
    return (isinstance(value, list) and len(value) == 2 and all(type(v) is int and v > 0 for v in value)
            and value[0] * value[1] <= maximum)


def _box(value, width, height):
    return (isinstance(value, list) and len(value) == 4 and all(type(v) is int for v in value)
            and 0 <= value[0] < value[2] <= width and 0 <= value[1] < value[3] <= height)


def _rotated_size(size, angle):
    """Pillow's centered expanded canvas calculation without a raster allocation."""
    width, height = size
    angle %= 360
    if angle in (0, 180):
        return list(size)
    if angle in (90, 270):
        return [height, width]
    theta = -math.radians(angle)
    a, b, d, e = round(math.cos(theta), 15), round(math.sin(theta), 15), round(-math.sin(theta), 15), round(math.cos(theta), 15)
    c, f = -a * width / 2 - b * height / 2 + width / 2, -d * width / 2 - e * height / 2 + height / 2
    points = [(a * x + b * y + c, d * x + e * y + f) for x, y in ((0, 0), (width, 0), (width, height), (0, height))]
    return [math.ceil(max(p[0] for p in points)) - math.floor(min(p[0] for p in points)),
            math.ceil(max(p[1] for p in points)) - math.floor(min(p[1] for p in points))]


def _unicode_cmap(font):
    """Read the fixed native writer's bounded two-byte CID bfchar mapping."""
    raw = font['/ToUnicode'].read_bytes()
    if len(raw) > 8_000_000:
        raise ValueError('Angle OCR evidence Unicode map exceeds its supported size.')
    mapping, inside, remaining = {}, False, 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(b'%'):
            continue
        if re.search(rb'\b(?:(?:begin|end)?(?:bfrange|cidchar|cidrange)|usecmap)\b', line):
            raise ValueError('Angle OCR evidence Unicode map has unsupported coding operators.')
        if line.endswith(b'beginbfchar'):
            declaration = re.fullmatch(rb'([0-9]+)\s+beginbfchar', line)
            if inside or declaration is None or not 1 <= int(declaration[1]) <= 65_536:
                raise ValueError('Angle OCR evidence Unicode map has nested bfchar sections.')
            inside, remaining = True, int(declaration[1])
        elif re.match(rb'endbfchar(?:\s|$)', line):
            if not inside or remaining:
                raise ValueError('Angle OCR evidence Unicode map has an incomplete declared section.')
            inside = False
        elif inside:
            match = re.fullmatch(rb'<([A-Fa-f0-9]{4})>\s+<((?:[A-Fa-f0-9]{4})+)>', line)
            if not match:
                raise ValueError('Angle OCR evidence Unicode map has an unsupported native entry.')
            key = bytes.fromhex(match[1].decode('ascii'))
            try:
                value = bytes.fromhex(match[2].decode('ascii')).decode('utf-16-be')
            except (ValueError, UnicodeError) as error:
                raise ValueError('Angle OCR evidence Unicode map has invalid UTF-16.') from error
            if key in mapping or len(mapping) >= 65_536 or remaining <= 0:
                raise ValueError('Angle OCR evidence Unicode map has duplicate or excessive entries.')
            mapping[key] = value
            remaining -= 1
    if inside or not mapping:
        raise ValueError('Angle OCR evidence Unicode map has incomplete bfchar sections.')
    return mapping


def _require_layer(path, size, dpi, words):
    """Reject painting and visible text in the stand-alone graft layer."""
    import pikepdf
    with pikepdf.open(path) as pdf:
        if len(pdf.pages) != 1:
            raise ValueError('Angle OCR evidence layer must contain exactly one page.')
        page = pdf.pages[0]
        expected = [0, 0, size[0] * 72 / dpi, size[1] * 72 / dpi]
        if any(abs(float(a) - b) > .02 for a, b in zip(page.MediaBox, expected)):
            raise ValueError('Angle OCR evidence layer has inconsistent page dimensions.')
        if page.Resources.get('/XObject') or page.obj.get('/Annots'):
            raise ValueError('Angle OCR evidence layer contains an image, form or annotation.')
        fonts = page.Resources.get('/Font', {})
        if not fonts or any(font.get('/Subtype') != pikepdf.Name.Type0 or not font.get('/ToUnicode')
                            for font in fonts.values()):
            raise ValueError('Angle OCR evidence layer lacks its mapped Unicode font.')
        for font in fonts.values():
            descendants = font.get('/DescendantFonts', [])
            if not descendants or any(not child.get('/FontDescriptor', {}).get('/FontFile2') for child in descendants):
                raise ValueError('Angle OCR evidence layer lacks its embedded font.')
        font_maps = {str(name): _unicode_cmap(font) for name, font in fonts.items()}
        render, current_font, stack, paints = 0, None, [], 0
        forbidden = {'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'Do', 'sh', 'INLINE IMAGE'}
        for instruction in pikepdf.parse_content_stream(page):
            operator = str(instruction.operator)
            if operator in forbidden:
                raise ValueError('Angle OCR evidence layer contains visible painting.')
            if operator == 'q':
                stack.append((render, current_font))
            elif operator == 'Q':
                if not stack:
                    raise ValueError('Angle OCR evidence layer has unbalanced graphics state.')
                render, current_font = stack.pop()
            elif operator == 'Tf':
                if len(instruction.operands) != 2 or str(instruction.operands[0]) not in font_maps:
                    raise ValueError('Angle OCR evidence layer has an unbound text font.')
                current_font = str(instruction.operands[0])
            elif operator == 'Tr':
                if len(instruction.operands) != 1 or int(instruction.operands[0]) != 3:
                    raise ValueError('Angle OCR evidence layer has visible text rendering.')
                render = 3
            elif operator in ('Tj', 'TJ', "'", '"'):
                if render != 3:
                    raise ValueError('Angle OCR evidence layer has visible text.')
                if operator != 'Tj' or len(instruction.operands) != 1 or current_font is None or paints >= len(words):
                    raise ValueError('Angle OCR evidence layer lacks its fixed single-word text shows.')
                raw = bytes(instruction.operands[0])
                mapping = font_maps[current_font]
                if len(raw) % 2 or any(raw[index:index+2] not in mapping for index in range(0, len(raw), 2)):
                    raise ValueError('Angle OCR evidence layer has unmapped native text codes.')
                decoded = ''.join(mapping[raw[index:index+2]] for index in range(0, len(raw), 2))
                expected_text = words[paints]['text'] + (' ' if paints+1 < len(words) else '')
                if decoded != expected_text:
                    raise ValueError('Angle OCR evidence layer has inconsistent explicit word separators or encoded Unicode.')
                paints += 1
        if stack or paints != len(words):
            raise ValueError('Angle OCR evidence layer has inconsistent hidden text coverage.')
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(path) as document:
        page = document[0]
        try:
            textpage = page.get_textpage()
            try:
                actual = textpage.get_text_range()
            finally:
                textpage.close()
        finally:
            page.close()
    if actual.split() != ' '.join(word['text'] for word in words).split():
        raise ValueError('Angle OCR evidence hidden layer has inconsistent Unicode word boundaries.')


def _optional_trace(proof, name, expected, start, algorithm, *, preplanning_reserve):
    """Require a completed prefix of source-derived plans and all four controls."""
    trace = proof.get(name + '_trace')
    value_key = 'plans' if name == 'confirmation' else 'proposals'
    if not isinstance(trace, dict) or set(trace) != {value_key, 'attempted_plans', 'budget_skipped'}:
        raise ValueError('Angle OCR evidence has invalid optional planning trace.')
    count, skip = trace['attempted_plans'], trace['budget_skipped']
    if type(count) is not int or count < 0:
        raise ValueError('Angle OCR evidence has invalid optional plan count.')
    planned = trace[value_key]
    if planned is None:
        if count != 0 or skip is None:
            raise ValueError('Angle OCR evidence omitted optional planning without a budget boundary.')
        plans = []
    else:
        try:
            same = json.dumps(planned, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            same = False
        if not same:
            raise ValueError('Angle OCR evidence optional plans do not match source pixels and supported words.')
        plans = planned if name == 'confirmation' else planned['plans']
        if count > len(plans):
            raise ValueError('Angle OCR evidence optional plan count exceeds its source proposals.')
    end = start + count * len(algorithm.OPTIONAL_CONTROLS)
    if end > len(proof['attempts']):
        raise ValueError('Angle OCR evidence optional plan controls are incomplete.')
    if skip is not None:
        if (not isinstance(skip, dict) or set(skip) != {'plan_index', 'reason', 'attempt_count', 'elapsed_seconds'}
                or type(skip['plan_index']) is not int or skip['plan_index'] != count
                or type(skip['attempt_count']) is not int or skip['attempt_count'] != end
                or not _number(skip['elapsed_seconds']) or not 0 <= skip['elapsed_seconds'] <= proof['seconds'] + .001):
            raise ValueError('Angle OCR evidence has an invalid optional budget boundary.')
        if planned is None:
            if (skip['reason'] != 'time-reserve-before-' + name + '-planning'
                    or skip['elapsed_seconds'] + preplanning_reserve <= algorithm.MAX_SECONDS):
                raise ValueError('Angle OCR evidence has an unsupported preplanning budget skip.')
        elif (count == len(plans) or algorithm.optional_group_skip(plans[count], end, skip['elapsed_seconds']) != skip['reason']):
            raise ValueError('Angle OCR evidence has an unsupported optional group skip.')
    elif count != len(plans):
        raise ValueError('Angle OCR evidence silently omitted optional plans.')
    for index, plan in enumerate(plans[:count]):
        for offset, (height, stretch, psm) in enumerate(algorithm.OPTIONAL_CONTROLS):
            attempt = proof['attempts'][start + index * len(algorithm.OPTIONAL_CONTROLS) + offset]
            bounds = plan['bounds']; width, crop_height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            resized = [max(1, round(width * height / crop_height * stretch)), height]
            components = plan.get('component_count', 0)
            if (attempt.get('phase') != name or type(attempt.get('plan_index')) is not int or attempt['plan_index'] != index
                    or type(attempt.get('target_height')) is not int or attempt['target_height'] != height
                    or attempt['angle'] != plan['angle'] or attempt['psm'] != psm or attempt.get('refined_from') is not None
                    or attempt['region'] != {'bounds': bounds, 'component_count': components, 'count': components,
                                             'kind': plan['kind'], 'line_id': -1}
                    or attempt['resize'] != [resized[0] / width, resized[1] / crop_height]
                    or algorithm.optional_group_skip(plan, 0, 0) is not None):
                raise ValueError('Angle OCR evidence optional controls or native provenance are inconsistent.')
    return end, plans[:count]


def validate_pages(directory, required_pages, binding, font_path, source_sha256, page_count):
    """Validate exact page coverage, retained files and recomputed word geometry."""
    from . import ocr_angles as algorithm, ocr_rescue as rescue, ocr_regions as regions

    directory, font_path = Path(directory), Path(font_path)
    if set(binding) != {'plugin_sha256', 'algorithm_sha256', 'regions_sha256', 'evidence_sha256', 'rescue_sha256'}:
        raise ValueError('Angle OCR evidence requires all five implementation bindings.')
    if digest(font_path) != FONT_SHA256:
        raise ValueError('Angle OCR evidence font binding changed.')
    expected = sorted(required_pages)
    if (not expected or len(set(expected)) != len(expected)
            or any(type(page) is not int or not 1 <= page <= page_count for page in expected)):
        raise ValueError('Angle OCR evidence has invalid required pages.')
    actual_roots = {path.name for path in directory.iterdir()}
    expected_roots = {name for page in expected for name in (f'{page:06d}', f'{page:06d}.json')}
    if actual_roots != expected_roots:
        raise ValueError('Angle OCR evidence has incomplete or unexpected page coverage.')
    output = []
    for page in expected:
        path, root = directory / f'{page:06d}.json', directory / f'{page:06d}'
        if path.stat().st_size > 16_000_000 or not root.is_dir() or root.is_symlink():
            raise ValueError('Angle OCR evidence exceeds its proof bounds.')
        proof = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(proof, dict) or proof.get('schema') != SCHEMA or proof.get('profile') != 'angles'
                or proof.get('page') != page or type(proof.get('page')) is not int
                or proof.get('adapter_source_sha256') != source_sha256 or proof.get('version') != algorithm.VERSION
                or any(proof.get(key) != value for key, value in binding.items())
                or proof.get('font_sha256') != FONT_SHA256
                or proof.get('renderer') != 'invisible-affine'
                or proof.get('word_separator_policy') != WORD_SEPARATOR_POLICY
                or proof.get('word_separator_policy') != algorithm.WORD_SEPARATOR_POLICY
                or any(proof.get(key) != 'needs-review' for key in ('accuracy', 'completeness', 'reading_order'))):
            raise ValueError('Angle OCR evidence has invalid implementation or review bindings.')
        size, working, dpi = proof.get('image_size'), proof.get('working_size'), proof.get('dpi')
        attempts, selected = proof.get('attempts'), proof.get('selected_words')
        if (not _size(size, algorithm.MAX_PIXELS) or not _size(working, algorithm.MAX_SIDE ** 2)
                or max(working) > algorithm.MAX_SIDE or any(a > b for a, b in zip(working, size))
                or not _number(dpi) or not 50 <= dpi <= 1200
                or not _number(proof.get('seconds')) or not 0 <= proof['seconds'] <= algorithm.MAX_SECONDS + 6
                or not isinstance(attempts, list) or not 1 <= len(attempts) <= algorithm.MAX_ATTEMPTS
                or type(proof.get('attempt_count')) is not int or proof['attempt_count'] != len(attempts)
                or not isinstance(selected, list) or not 1 <= len(selected) <= algorithm.MAX_WORDS):
            raise ValueError('Angle OCR evidence has invalid workload or image bounds.')
        if type(proof.get('word_separator_count')) is not int or proof['word_separator_count'] != max(0, len(selected)-1):
            raise ValueError('Angle OCR evidence has invalid explicit word separator coverage.')
        baseline_count = proof.get('baseline_attempt_count')
        if (type(baseline_count) is not int or not 1 <= baseline_count <= len(attempts)
                or any('phase' in attempt or 'plan_index' in attempt or 'target_height' in attempt
                       for attempt in attempts[:baseline_count] if isinstance(attempt, dict))):
            raise ValueError('Angle OCR evidence has invalid baseline attempt coverage.')
        for word in selected:
            if (not isinstance(word, dict) or not isinstance(word.get('text'), str)
                    or type(word.get('confidence')) is not int or not algorithm.MIN_CONFIDENCE <= word['confidence'] <= 100
                    or type(word.get('attempt')) is not int or not 0 <= word['attempt'] < len(attempts)
                    or type(word.get('raw_word_index')) is not int or word['raw_word_index'] < 0
                    or type(word.get('agreement_votes')) is not int or not 2 <= word['agreement_votes'] <= algorithm.MAX_ATTEMPTS
                    or not _number(word.get('selection_score')) or not _number(word.get('height')) or word['height'] <= 0
                    or not _number(word.get('scale')) or word['scale'] <= 0
                    or any(not isinstance(word.get(key), list) or len(word[key]) != 4
                           or not all(_number(value) for value in word[key]) for key in ('box', 'rotated_box'))
                    or not isinstance(word.get('quad'), list) or len(word['quad']) != 4
                    or any(not isinstance(point, list) or len(point) != 2 or not all(_number(v) for v in point) for point in word['quad'])):
                raise ValueError('Angle OCR evidence has invalid selected-word geometry or agreement.')
        expected_files = {'input.png', 'layer.pdf', 'recognized.txt'} | {
            f'attempts/{number:03d}.{extension}' for number in range(len(attempts)) for extension in ('png', 'hocr', 'txt')}
        files = proof.get('retained_files')
        actual_files = {str(item.relative_to(root)).replace('\\', '/') for item in root.rglob('*') if item.is_file()}
        if (not isinstance(files, dict) or set(files) != expected_files or actual_files != expected_files
                or any(item.is_symlink() for item in root.rglob('*'))):
            raise ValueError('Angle OCR evidence has incomplete or unexpected retained files.')
        for relative, record in files.items():
            item = root / relative
            if (not isinstance(record, dict) or type(record.get('size')) is not int
                    or not 0 <= record['size'] <= 180_000_000 or item.stat().st_size != record['size']
                    or not isinstance(record.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', record['sha256'])
                    or digest(item) != record['sha256']):
                raise ValueError('Angle OCR evidence retained-file hashes are invalid.')
        with Image.open(root / 'input.png') as native:
            resolution = native.info.get('dpi')
            if (list(native.size) != size or not resolution or len(resolution) != 2
                    or any(not _number(v) or not 50 <= v <= 1200 for v in resolution)
                    or abs(resolution[0] - resolution[1]) > 1 or abs(resolution[0] - dpi) > .001):
                raise ValueError('Angle OCR evidence input raster or DPI is inconsistent.')
            with native.convert('RGB') as rgb:
                if hashlib.sha256(rgb.tobytes()).hexdigest() != proof.get('input_RGB_sha256'):
                    raise ValueError('Angle OCR evidence input raster hash is inconsistent.')
                native_pixels = rgb.copy()
                rgb.thumbnail((algorithm.MAX_SIDE, algorithm.MAX_SIDE), Image.Resampling.LANCZOS)
                if list(rgb.size) != working:
                    raise ValueError('Angle OCR evidence thumbnail dimensions are inconsistent.')
                working_pixels = rgb.copy()
        scale = working[0] / size[0]
        if abs(working[1] / size[1] - scale) > 1 / min(size):
            raise ValueError('Angle OCR evidence has inconsistent scaling.')
        candidates, native_words, mapped_words, seen, paired = [], [], [], set(), {}
        base_regions, refined_regions = {}, {}
        frame_angle, rotated_base, rotated_native = None, None, None
        for number, attempt in enumerate(attempts):
            if not isinstance(attempt, dict):
                raise ValueError('Angle OCR evidence has an invalid attempt.')
            angle, psm, region = attempt.get('angle'), attempt.get('psm'), attempt.get('region')
            if (type(attempt.get('number')) is not int or attempt['number'] != number
                    or type(angle) not in (int, float) or angle not in algorithm.ANGLES
                    or type(psm) is not int or psm not in (7, 13) or not isinstance(region, dict)):
                raise ValueError('Angle OCR evidence has invalid attempt controls.')
            refined = attempt.get('refined_from')
            optional = number >= baseline_count
            if optional and (attempt.get('phase') not in ('confirmation', 'rescue') or refined is not None):
                raise ValueError('Angle OCR evidence has invalid optional attempt provenance.')
            native_attempt = refined is not None or optional
            frame = size if native_attempt else working
            frame_scale = 1 if native_attempt else scale
            rotated_size = _rotated_size(frame, angle)
            if rotated_size[0] * rotated_size[1] > algorithm.MAX_PIXELS * 2:
                raise ValueError('Angle OCR evidence native rotation exceeds its work bounds.')
            if frame_angle != angle:
                if rotated_base is not None:
                    rotated_base.close()
                if rotated_native is not None:
                    rotated_native.close()
                rotated_base = working_pixels.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor='white')
                rotated_native, frame_angle = None, angle
            if native_attempt and rotated_native is None:
                rotated_native = native_pixels.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor='white')
            frame_pixels = rotated_native if native_attempt else rotated_base
            bounds = region.get('bounds')
            if (not _box(bounds, *rotated_size) or attempt.get('crop_box') != bounds
                    or not _size(attempt.get('working_size'), algorithm.MAX_PIXELS)
                    or not _size(attempt.get('rotated_size'), algorithm.MAX_PIXELS * 2)
                    or attempt.get('working_size') != frame or attempt.get('rotated_size') != rotated_size
                    or not _number(attempt.get('scale')) or attempt['scale'] != frame_scale
                    or type(attempt.get('padding')) is not int or attempt['padding'] != 12):
                raise ValueError('Angle OCR evidence has invalid crop geometry.')
            if optional:
                if (attempt.get('target_height') != 64 or type(attempt.get('target_height')) is not int
                        or type(attempt.get('plan_index')) is not int or not 0 <= attempt['plan_index'] < 16
                        or region.get('kind') not in ('selected-word-confirmation', 'anchored-native-height-group')
                        or any(type(region.get(key)) is not int for key in ('component_count', 'count', 'line_id'))
                        or region['line_id'] != -1 or region['count'] != region['component_count']
                        or not 0 <= region['component_count'] <= 32):
                    raise ValueError('Angle OCR evidence has invalid optional region controls.')
            elif refined is None:
                if (region.get('kind') not in ('line', 'word') or type(region.get('component_count')) is not int
                        or not 1 <= region['component_count'] <= 20_000 or type(region.get('count')) is not int
                        or region['count'] != region['component_count'] or type(region.get('line_id')) is not int
                        or not 0 <= region['line_id'] < 20_000):
                    raise ValueError('Angle OCR evidence has invalid base-region measurements.')
                base_regions.setdefault(angle, set()).add(tuple(bounds))
                if len(base_regions[angle]) > algorithm.base_region_limit(angle):
                    raise ValueError('Angle OCR evidence exceeds its base-region budget.')
            else:
                if (not isinstance(refined, dict) or set(refined) != {'attempt', 'word_index'}
                        or type(refined['attempt']) is not int or not 0 <= refined['attempt'] < number
                        or type(refined['word_index']) is not int or refined['word_index'] < 0
                        or any(type(region.get(key)) is not int for key in ('component_count', 'count', 'line_id'))
                        or region != {'bounds': bounds, 'component_count': 0, 'count': 0, 'kind': 'refined-word', 'line_id': -1}):
                    raise ValueError('Angle OCR evidence has invalid refinement provenance.')
                parent = attempts[refined['attempt']]
                words = native_words[refined['attempt']]
                if (parent.get('refined_from') is not None or parent['angle'] != angle or refined['word_index'] >= len(words)
                        or not any(word['confidence'] >= 85 for word in words)):
                    raise ValueError('Angle OCR evidence refinement lacks a supported base result.')
                raw_word = words[refined['word_index']]
                word = next((item for item in mapped_words[refined['attempt']] if item['raw_word_index'] == refined['word_index']), None)
                if (word is None or raw_word['confidence'] < 20 or sum(c.isalnum() for c in raw_word['text']) < 3):
                    raise ValueError('Angle OCR evidence refinement lacks a supported, located word.')
                expected_crop = algorithm.refinement_crop(frame_pixels, word, parent['rotated_size'], scale)
                if bounds != expected_crop:
                    raise ValueError('Angle OCR evidence refinement is outside its measured native word crop.')
                refined_regions.setdefault(angle, set()).add(tuple(bounds))
                if len(refined_regions[angle]) > 8:
                    raise ValueError('Angle OCR evidence exceeds its refinement budget.')
            base = root / 'attempts' / f'{number:03d}'
            if (attempt.get('raster_sha256') != files[f'attempts/{number:03d}.png']['sha256']
                    or attempt.get('hocr_sha256') != files[f'attempts/{number:03d}.hocr']['sha256']
                    or base.with_suffix('.hocr').stat().st_size > 8_000_000
                    or base.with_suffix('.txt').stat().st_size > 8_000_000):
                raise ValueError('Angle OCR evidence has inconsistent native-result hashes.')
            crop_width, crop_height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            if optional and (crop_width * crop_height > algorithm.MAX_SOURCE_FIT_CROP_PIXELS
                    or max(1, round(crop_width * 64 / crop_height * 1.5)) > algorithm.MAX_OPTIONAL_WIDTH):
                raise ValueError('Angle OCR evidence optional native crop exceeds its work bounds.')
            resize = 64 / crop_height if optional else min(2, 64 / max(1, crop_height))
            variants = []
            for stretch in ((1, 1.5) if native_attempt else (1,)):
                resized = [max(1, round(crop_width * resize * stretch)), max(1, round(crop_height * resize))]
                exact_resize = [resized[0] / crop_width, resized[1] / crop_height]
                if attempt.get('resize') == exact_resize:
                    variants.append((stretch, resized))
            if (len(variants) != 1 or not isinstance(attempt.get('resize'), list)
                    or not all(_number(v) and v > 0 for v in attempt['resize'])):
                raise ValueError('Angle OCR evidence crop scaling is inconsistent.')
            stretch, resized = variants[0]
            padded_size = [resized[0] + 24, resized[1] + 24]
            if attempt.get('raster_size') != padded_size:
                raise ValueError('Angle OCR evidence crop raster dimensions are inconsistent.')
            identity = (angle, psm, tuple(bounds), refined is not None, attempt.get('phase'), attempt.get('plan_index'), stretch, attempt['raster_sha256'])
            if identity in seen:
                raise ValueError('Angle OCR evidence repeats an identically conditioned recognition attempt.')
            seen.add(identity)
            paired.setdefault((angle, tuple(bounds), native_attempt, attempt.get('phase'), attempt.get('plan_index')), set()).add((psm, stretch))
            with Image.open(base.with_suffix('.png')) as raster:
                if list(raster.size) != padded_size:
                    raise ValueError('Angle OCR evidence crop raster dimensions are inconsistent.')
                with frame_pixels.crop(bounds) as crop, crop.resize(tuple(resized), Image.Resampling.LANCZOS) as fitted:
                    with Image.new('RGB', tuple(padded_size), 'white') as expected_raster, raster.convert('RGB') as actual_raster:
                        expected_raster.paste(fitted, (12, 12))
                        if expected_raster.tobytes() != actual_raster.tobytes():
                            raise ValueError('Angle OCR evidence crop pixels do not correspond to the retained source raster.')
            if '[skipped page]' in base.with_suffix('.txt').read_text(encoding='utf-8'):
                raise ValueError('Angle OCR evidence contains a skipped native attempt.')
            words = algorithm.parse_hocr(base.with_suffix('.hocr'))
            if type(attempt.get('word_count')) is not int or attempt['word_count'] != len(words):
                raise ValueError('Angle OCR evidence native word count is inconsistent.')
            if any(not _box(word['bbox'], *padded_size) for word in words):
                raise ValueError('Angle OCR evidence native word is outside its crop raster.')
            mapped = algorithm.candidate_records(words, attempt, size)
            native_words.append(words)
            mapped_words.append(mapped)
            candidates.extend(mapped)
            if len(candidates) > algorithm.MAX_WORDS:
                raise ValueError('Angle OCR evidence exceeds its candidate-word budget.')
        for (_, _, refined, _, _), controls in paired.items():
            expected_controls = {(psm, stretch) for psm in (7, 13) for stretch in ((1, 1.5) if refined else (1,))}
            if controls != expected_controls:
                raise ValueError('Angle OCR evidence has incomplete paired recognition attempts.')
        try:
            baseline_candidates = [word for word in candidates if word['attempt'] < baseline_count]
            baseline_words = algorithm.select_words(baseline_candidates, source_image=native_pixels)
            trace = proof.get('confirmation_trace')
            plans = (algorithm.confirmation_plans(native_pixels, baseline_candidates, baseline_words)
                     if isinstance(trace, dict) and trace.get('plans') is not None else None)
            boundary, completed = _optional_trace(proof, 'confirmation', plans, baseline_count, algorithm,
                preplanning_reserve=algorithm.OPTIONAL_GROUP_RESERVE_SECONDS + 2)
            confirmed = algorithm.confirm_words(baseline_words, baseline_candidates,
                [word for word in candidates if word.get('phase') == 'confirmation'], completed, source_image=native_pixels)
            trace = proof.get('rescue_trace')
            proposals = (rescue.proposals(native_pixels, confirmed, regions)
                         if isinstance(trace, dict) and trace.get('proposals') is not None else None)
            final_boundary, _ = _optional_trace(proof, 'rescue', proposals, boundary, algorithm,
                preplanning_reserve=algorithm.OPTIONAL_GROUP_RESERVE_SECONDS + algorithm.RESCUE_PLANNING_RESERVE_SECONDS)
            if final_boundary != len(attempts):
                raise ValueError('Angle OCR evidence has unexpected optional attempts.')
            recomputed = json.loads(json.dumps(algorithm.add_rescue_words(confirmed,
                [word for word in candidates if word.get('phase') == 'rescue'])))
        finally:
            working_pixels.close()
            native_pixels.close()
            if rotated_base is not None:
                rotated_base.close()
            if rotated_native is not None:
                rotated_native.close()
        if selected != recomputed or not recomputed:
            raise ValueError('Angle OCR evidence selected words, agreement or inverse geometry are inconsistent.')
        if proof.get('font_glyphs') != glyph_mapping(selected, font_path):
            raise ValueError('Angle OCR evidence Unicode font mapping is inconsistent.')
        expected_text = ' '.join(word['text'] for word in selected) + '\n'
        if (root / 'recognized.txt').read_text(encoding='utf-8') != expected_text:
            raise ValueError('Angle OCR evidence recognized text is inconsistent.')
        if proof.get('output_layer_sha256') != files['layer.pdf']['sha256']:
            raise ValueError('Angle OCR evidence hidden-layer hash is inconsistent.')
        _require_layer(root / 'layer.pdf', size, dpi, selected)
        output.append({**proof, 'path': str(path), 'sha256': digest(path)})
    return output
