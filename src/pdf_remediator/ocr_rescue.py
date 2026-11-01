"""Pure, bounded source proposals for context-anchored native OCR rescue.

No recognition, file I/O or PDF editing occurs here. A proposal proves neither
that its ink is text nor that a later recognized word is correct. The driver
and independent evidence reader must call this same function on bound pixels.
"""
from collections import Counter
import hashlib
import json
import math
import re
from statistics import median

from PIL import Image, ImageChops, ImageDraw

VERSION = 'anchored-native-region-rescue-1'
ANGLES = (0, -45, -35, -30, -25, -20, -15, 15, 20, 25, 30, 35, 45, 90, 180, 270)
MAX_INPUT_PIXELS = 40_000_000
MAX_ROTATED_PIXELS = 80_000_000
MAX_CROP_PIXELS = 4_000_000
MAX_PARENTS = 24
MAX_PARENTS_PER_ANGLE = 4
MAX_PLANS = 16
MAX_CANDIDATES = MAX_PARENTS * 16
MAX_WORDS = 4096
MAX_COVERAGE_WORDS = 64
MAX_CONTEXT_WORK = 500_000
THRESHOLD = 180


class RescueLimit(ValueError):
    """An optional source proposal exceeds its supported workload."""


class _ContextLimit(Exception):
    """Stop optional planning before the next unbudgeted context operation."""


class _ContextWork:
    def __init__(self):
        self.counts = Counter()
        self.used = 0

    def take(self, kind):
        if self.used >= MAX_CONTEXT_WORK:
            raise _ContextLimit
        self.used += 1
        self.counts[kind] += 1


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _box(bounds, size):
    return (isinstance(bounds, (list, tuple)) and len(bounds) == 4
            and all(type(value) is int for value in bounds)
            and 0 <= bounds[0] < bounds[2] <= size[0] and 0 <= bounds[1] < bounds[3] <= size[1])


def _bounds(quad):
    return [min(point[0] for point in quad), min(point[1] for point in quad),
            max(point[0] for point in quad), max(point[1] for point in quad)]


def _direction(first, second):
    return abs((first-second+180) % 360-180)


def rotated_extent(size, angle):
    cosine, sine = abs(math.cos(math.radians(angle))), abs(math.sin(math.radians(angle)))
    result = (math.ceil(size[0]*cosine+size[1]*sine)+2, math.ceil(size[0]*sine+size[1]*cosine)+2)
    if result[0]*result[1] > MAX_ROTATED_PIXELS:
        raise RescueLimit('Optional native rotation exceeds its preallocation bound.')
    return result


def canonical_crop(frame, bounds):
    if not _box(bounds, frame.size):
        raise ValueError('Invalid source-derived native proposal bounds.')
    if (bounds[2]-bounds[0])*(bounds[3]-bounds[1]) > MAX_CROP_PIXELS:
        raise RescueLimit('Optional native parent crop exceeds its pixel bound.')
    with frame.crop(bounds) as crop, crop.convert('L') as gray:
        with gray.point(lambda value: 255 if value < THRESHOLD else 0) as ink:
            measured = ink.getbbox()
    if measured is None:
        return None
    left, top, right, bottom = (bounds[0]+measured[0], bounds[1]+measured[1],
                                bounds[0]+measured[2], bounds[1]+measured[3])
    margin = max(2, round((bottom-top)*.035))
    result = [max(0, left-margin), max(0, top-margin), min(frame.width, right+margin), min(frame.height, bottom+margin)]
    if (result[2]-result[0])*(result[3]-result[1]) > MAX_CROP_PIXELS:
        raise RescueLimit('Optional canonical native crop exceeds its pixel bound.')
    return result


def split_line(glyphs):
    """Split native glyph heights/gaps, never native or expected word strings."""
    groups, current = [], []
    for item in sorted(glyphs, key=lambda row: (row['bounds'][0], row['bounds'][1])):
        if current:
            a, b = current[-1]['bounds'], item['bounds']
            ah, bh = a[3]-a[1], b[3]-b[1]
            if max(ah, bh) >= 1.5*min(ah, bh) or b[0]-a[2] > .4*min(ah, bh):
                groups.append(current)
                current = []
        current.append(item)
    if current:
        groups.append(current)
    return groups


def _forward(point, angle, source_size, rotated_size):
    x, y = point[0]-source_size[0]/2, point[1]-source_size[1]/2
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return (cosine*x+sine*y+rotated_size[0]/2, -sine*x+cosine*y+rotated_size[1]/2)


def _inverse(point, angle, source_size, rotated_size):
    x, y = point[0]-rotated_size[0]/2, point[1]-rotated_size[1]/2
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return (cosine*x-sine*y+source_size[0]/2, sine*x+cosine*y+source_size[1]/2)


def _inside(point, quad):
    values = [(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
              for a, b in zip(quad, quad[1:]+quad[:1])]
    return all(value >= -1e-6 for value in values) or all(value <= 1e-6 for value in values)


def _intersects(first, second):
    return first[0] < second[2] and first[2] > second[0] and first[1] < second[3] and first[3] > second[1]


def _project_words(baseline, angle, source_size, rotated_size, work):
    projected = []
    for word in baseline:
        work.take('word_projections')
        quad = [_forward(point, angle, source_size, rotated_size) for point in word['quad']]
        projected.append({'word': word, 'quad': quad, 'bounds': _bounds(quad),
                          'anchor_eligible': word['confidence'] >= 85 and _direction(angle, word['angle']) <= 12})
    return projected


def _line_anchors(line, projected, work):
    """Associate eligible baseline words with this line once, not per child."""
    line_bounds = _bounds([point for glyph in line for point in
                           ((glyph['bounds'][0], glyph['bounds'][1]), (glyph['bounds'][2], glyph['bounds'][3]))])
    anchors = []
    for record in projected:
        work.take('line_word_checks')
        if not record['anchor_eligible']:
            continue
        if not _intersects(line_bounds, record['bounds']):
            continue
        siblings = []
        for index, glyph in enumerate(line):
            work.take('quad_tests')
            box = glyph['bounds']
            if _inside(((box[0]+box[2])/2, (box[1]+box[3])/2), record['quad']):
                siblings.append(index)
        if len(siblings) >= 2:
            anchors.append({'word': record['word'], 'siblings': siblings,
                            'height': median(line[index]['bounds'][3]-line[index]['bounds'][1] for index in siblings)})
    return anchors


def _anchor(line, members, contexts, work):
    small_height = median(item['bounds'][3]-item['bounds'][1] for item in members)
    chosen = {id(item) for item in members}
    for context in contexts:
        work.take('group_anchor_checks')
        siblings, word = context['siblings'], context['word']
        if any(id(line[index]) in chosen for index in siblings) or 1.5*small_height > context['height']:
            continue
        return {'reference': {key: word[key] for key in ('attempt', 'raw_word_index', 'raster_sha256')},
                'confidence': word['confidence'], 'angle': word['angle'], 'component_indices': siblings,
                'small_median_height': small_height, 'anchor_median_height': context['height']}
    return None


def _uncovered(frame, bounds, baseline, work):
    projected = []
    for record in baseline:
        work.take('coverage_word_checks')
        if _intersects(record['bounds'], bounds):
            projected.append(record['quad'])
    if len(projected) > MAX_COVERAGE_WORDS:
        raise RescueLimit('Optional native coverage overlap inventory exceeds its bound.')
    with frame.crop(bounds) as crop, crop.convert('L') as gray:
        with gray.point(lambda value: 255 if value < THRESHOLD else 0) as ink, Image.new('L', crop.size, 0) as mask:
            draw = ImageDraw.Draw(mask)
            for quad in projected:
                draw.polygon([(x-bounds[0], y-bounds[1]) for x, y in quad], fill=255)
            with ImageChops.multiply(ink, mask) as covered:
                total, matched = ink.histogram()[255], covered.histogram()[255]
    return {'ink_pixels': total, 'uncovered_ink_fraction': 1-matched/total if total else 0,
            'coverage_method': 'native-threshold-polygon-raster-1'}


def proposals(native_rgb, accepted_words, region_module):
    """Return deterministic anchored crop plans from source pixels alone.

    Existing accepted words only provide verified geometric context. No literal
    words are consulted or returned. No isolated unanchored region is eligible.
    The caller must keep every baseline record and independently enforce native
    recognition confidence, complete-group, time, font and preservation gates.
    """
    if (not isinstance(native_rgb, Image.Image) or native_rgb.mode != 'RGB'
            or not 0 < native_rgb.width*native_rgb.height <= MAX_INPUT_PIXELS
            or not isinstance(accepted_words, list) or len(accepted_words) > MAX_WORDS):
        raise ValueError('Bounded native RGB pixels and accepted-word inventory required.')
    for word in accepted_words:
        if (not isinstance(word, dict) or not isinstance(word.get('quad'), (list, tuple)) or len(word['quad']) != 4
                or any(not isinstance(point, (list, tuple)) or len(point) != 2
                       or any(type(value) not in (int, float) or not math.isfinite(value) for value in point) for point in word['quad'])
                or any(not 0 <= x <= native_rgb.width or not 0 <= y <= native_rgb.height for x, y in word['quad'])
                or type(word.get('confidence')) is not int or not 70 <= word['confidence'] <= 100
                or type(word.get('attempt')) is not int or word['attempt'] < 0
                or type(word.get('raw_word_index')) is not int or word['raw_word_index'] < 0
                or type(word.get('angle')) is not int or word['angle'] not in ANGLES
                or not isinstance(word.get('raster_sha256'), str) or not re.fullmatch('[a-f0-9]{64}', word['raster_sha256'])):
            raise ValueError('Malformed accepted-word context for native rescue.')
    skipped = Counter()
    work = _ContextWork()
    budget_exhausted = False
    parents_seen = 0
    candidates = []
    baseline = sorted(accepted_words, key=lambda row: (-row['confidence'], row['attempt'], row['raw_word_index']))
    active = [angle for angle in ANGLES if any(word['confidence'] >= 85 and _direction(angle, word['angle']) < .01 for word in accepted_words)]
    try:
        for angle in active:
            if parents_seen >= MAX_PARENTS:
                break
            try:
                rotated_extent(native_rgb.size, angle)
            except RescueLimit:
                skipped['rotation-pixels'] += 1
                continue
            with native_rgb.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC, fillcolor='white') as frame:
                if frame.width*frame.height > MAX_ROTATED_PIXELS:
                    raise RescueLimit('Native rotation exceeded its preallocation bound.')
                projected = _project_words(baseline, angle, native_rgb.size, frame.size, work)
                try:
                    proposed = region_module.regions(frame)
                except region_module.RegionLimit:
                    skipped['region-limit'] += 1
                    continue
                if len(proposed) > 64:
                    raise RescueLimit('Source region detector exceeded its proposal bound.')
                unique = {tuple(row['bounds']): row for row in proposed
                          if row.get('kind') == 'line' and type(row.get('component_count')) is int and 8 <= row['component_count'] <= 32}
                parents = sorted(unique.values(), key=lambda row: (-row['component_count'], row['bounds'][1], row['bounds'][0]))
                for parent in parents[:MAX_PARENTS_PER_ANGLE]:
                    if parents_seen >= MAX_PARENTS:
                        break
                    parents_seen += 1
                    try:
                        bounds = canonical_crop(frame, parent['bounds'])
                    except RescueLimit:
                        skipped['parent-pixels'] += 1
                        continue
                    if bounds is None:
                        skipped['blank-parent'] += 1
                        continue
                    try:
                        with frame.crop(bounds) as crop, crop.convert('L') as gray:
                            components, _ = region_module._components(gray)
                            glyphs, _ = region_module._glyphs(components, crop.size)
                            lines, _ = region_module._lines(glyphs)
                    except region_module.RegionLimit:
                        skipped['component-limit'] += 1
                        continue
                    for line_index, local_line in enumerate(lines):
                        work.take('line_checks')
                        if not 8 <= len(local_line) <= 32:
                            continue
                        line = [{'bounds': [item['bounds'][0]+bounds[0], item['bounds'][1]+bounds[1],
                                            item['bounds'][2]+bounds[0], item['bounds'][3]+bounds[1]], 'ink': item['ink']}
                                for item in sorted(local_line, key=lambda row: (row['bounds'][0], row['bounds'][1]))]
                        groups = split_line(line)
                        heights = [median(item['bounds'][3]-item['bounds'][1] for item in group) for group in groups]
                        small = [group for index, group in enumerate(groups) if len(group) >= 2
                                 and any(other != index and any(item['bounds'][3]-item['bounds'][1] >= 1.5*heights[index]
                                                               for item in outside)
                                         for other, outside in enumerate(groups))]
                        # Empty/equal-height lines need no scan of the baseline inventory.
                        if not small:
                            continue
                        contexts = _line_anchors(line, projected, work)
                        for members in small:
                            work.take('group_checks')
                            anchor = _anchor(line, members, contexts, work)
                            if anchor is None:
                                skipped['no-distinct-large-sibling'] += 1
                                continue
                            group_bounds = _bounds([point for item in members for point in
                                                    ((item['bounds'][0], item['bounds'][1]), (item['bounds'][2], item['bounds'][3]))])
                            group_bounds = canonical_crop(frame, group_bounds)
                            if group_bounds is None:
                                continue
                            left, top, right, bottom = group_bounds
                            quad = [_inverse(point, angle, native_rgb.size, frame.size) for point in
                                    ((left, top), (right, top), (right, bottom), (left, bottom))]
                            if any(x < 0 or y < 0 or x > native_rgb.width or y > native_rgb.height for x, y in quad):
                                skipped['outside-source'] += 1
                                continue
                            coverage = _uncovered(frame, group_bounds, projected, work)
                            if coverage['ink_pixels'] < 3 or coverage['uncovered_ink_fraction'] < .35:
                                skipped['covered-or-empty'] += 1
                                continue
                            item = {'angle': angle, 'bounds': group_bounds, 'kind': 'anchored-native-height-group',
                                    'component_count': len(members), 'native_quad': quad, 'native_box': _bounds(quad),
                                    'parent': {'region': parent, 'native_bounds': bounds, 'line_index': line_index,
                                               'line_glyphs_sha256': _digest(line), 'line_glyph_count': len(line)},
                                    'group': members, 'anchor': anchor, 'measurements': coverage}
                            item['id'] = _digest(item)
                            candidates.append(item)
                            if len(candidates) > MAX_CANDIDATES:
                                raise RescueLimit('Optional native candidate-plan count exceeds its bound.')
    except _ContextLimit:
        budget_exhausted = True
        skipped['context-work-budget'] += 1
    unique = {}
    for item in candidates:
        unique.setdefault((item['angle'], tuple(item['bounds'])), item)
    by_angle = {angle: sorted([item for item in unique.values() if item['angle'] == angle],
                             key=lambda row: (-row['measurements']['uncovered_ink_fraction'], row['bounds'][1], row['bounds'][0], row['id']))
                for angle in active}
    chosen = []
    while len(chosen) < MAX_PLANS:
        available = False
        for angle in active:
            if by_angle[angle] and len(chosen) < MAX_PLANS:
                chosen.append(by_angle[angle].pop(0))
                available = True
        if not available:
            break
    return {'version': VERSION, 'plans': chosen, 'measurements': {'active_angles': active,
            'native_parents_examined': parents_seen, 'candidate_plans': len(candidates), 'deduplicated_plans': len(unique),
            'returned_plans': len(chosen), 'omitted_by_plan_bound': max(0, len(unique)-len(chosen)),
            'context_work_limit': MAX_CONTEXT_WORK, 'context_work': work.used,
            'context_quad_tests': work.counts['quad_tests'], 'context_work_by_kind': dict(sorted(work.counts.items())),
            'context_budget_exhausted': budget_exhausted, 'skipped': dict(sorted(skipped.items()))}}
