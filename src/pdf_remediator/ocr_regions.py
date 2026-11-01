"""Bounded, word-agnostic connected-ink crop proposals for rotated OCR rasters."""
from collections import defaultdict
from math import ceil, floor, log1p
from statistics import median

from PIL import Image

MAX_SIDE = 1800
MAX_PIXELS = 4_000_000
MAX_COMPONENTS = 20_000
MAX_RUNS = 250_000
MAX_PAIRS = 500_000
MAX_REGIONS = 64
THRESHOLD = 180


class RegionLimit(ValueError):
    """An untrusted raster exceeded the bounded proposal workload."""


def _find(parent, item):
    while parent[item] != item:
        parent[item] = parent[parent[item]]
        item = parent[item]
    return item


def _components(gray):
    width, height = gray.size
    pixels = gray.tobytes()
    parent, boxes, areas = [], [], []
    previous, runs_seen = [], 0

    def join(first, second):
        first, second = _find(parent, first), _find(parent, second)
        if first == second:
            return first
        if areas[first] < areas[second]:
            first, second = second, first
        parent[second] = first
        a, b = boxes[first], boxes[second]
        boxes[first] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        areas[first] += areas[second]
        return first

    for y in range(height):
        row, x, current, cursor = y * width, 0, [], 0
        while x < width:
            if pixels[row + x] >= THRESHOLD:
                x += 1
                continue
            left = x
            while x < width and pixels[row + x] < THRESHOLD:
                x += 1
            right = x
            runs_seen += 1
            if runs_seen > MAX_RUNS:
                raise RegionLimit('Connected-ink run budget exceeded')
            while cursor < len(previous) and previous[cursor][1] < left:
                cursor += 1
            touches, scan = [], cursor
            while scan < len(previous) and previous[scan][0] <= right:
                touches.append(previous[scan][2])
                scan += 1
            if touches:
                label = _find(parent, touches[0])
                for other in touches[1:]:
                    label = join(label, other)
                bounds = boxes[label]
                boxes[label] = [min(bounds[0], left), min(bounds[1], y), max(bounds[2], right), y + 1]
                areas[label] += right - left
            else:
                if len(parent) >= MAX_COMPONENTS:
                    raise RegionLimit('Connected-ink component budget exceeded')
                label = len(parent)
                parent.append(label)
                boxes.append([left, y, right, y + 1])
                areas.append(right - left)
            current.append((left, right, label))
        previous = current
    return [(boxes[i], areas[i]) for i in range(len(parent)) if _find(parent, i) == i], runs_seen


def _glyphs(components, size):
    width, height = size
    kept, discarded = [], {'speckle': 0, 'rule': 0, 'frame': 0}
    for bounds, ink in components:
        left, top, right, bottom = bounds
        w, h = right - left, bottom - top
        if ink < 3 or max(w, h) < 2:
            discarded['speckle'] += 1
            continue
        density = ink / (w * h)
        # A glyph I/l/1 is allowed to be narrow. Require a page-scale length,
        # extreme aspect ratio and substantial continuous ink to call it a rule.
        if (w >= width * .5 or h >= height * .5) and max(w, h) / min(w, h) >= 22 and density >= .25:
            discarded['rule'] += 1
            continue
        # Large hollow border/frame, including a skewed fold connected to it.
        # No generic maximum character height or aspect filter is applied.
        if w >= width * .5 and h >= height * .5 and w * h >= width * height * .2 and density < .15:
            discarded['frame'] += 1
            continue
        kept.append({'bounds': bounds, 'ink': ink})
    return kept, discarded


def _neighbors(first, second):
    a, b = first['bounds'], second['bounds']
    aw, ah, bw, bh = a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]
    gap = max(0, b[0] - a[2])
    if gap > max(4, min(ah, bh) * 1.8):
        return False
    overlap_x = min(a[2], b[2]) - max(a[0], b[0])
    overlap_y = min(a[3], b[3]) - max(a[1], b[1])
    center_gap = abs((a[1] + a[3] - b[1] - b[3]) / 2)
    # A disconnected dot/accent can belong to the same glyph/line. Comparable
    # vertically stacked letters do not become one horizontal line this way.
    if overlap_x > 0 and overlap_y <= 0:
        ygap = max(a[1], b[1]) - min(a[3], b[3])
        return min(ah, bh) <= .45 * max(ah, bh) and ygap <= max(3, max(ah, bh) * .25)
    return (overlap_y >= min(ah, bh) * .35 or
            abs(a[3] - b[3]) <= max(3, max(ah, bh) * .32) and center_gap <= max(ah, bh) * .65)


def _lines(glyphs):
    glyphs = sorted(glyphs, key=lambda row: (row['bounds'][0], row['bounds'][1]))
    parent = list(range(len(glyphs)))
    bottom_bins, center_bins = defaultdict(list), defaultdict(list)
    pairs = 0
    for index, item in enumerate(glyphs):
        bounds = item['bounds']
        h = bounds[3] - bounds[1]
        bottom, center = bounds[3], (bounds[1] + bounds[3]) / 2
        candidates = set()
        for position, bins, radius in ((bottom, bottom_bins, max(6, h * .45)), (center, center_bins, max(6, h * 1.1))):
            for bucket in range(floor((position - radius) / 8), ceil((position + radius) / 8) + 1):
                candidates.update(bins.get(bucket, ()))
        for other in sorted(candidates):
            a = glyphs[other]['bounds']
            # Spatial rejection before the bounded more expensive shape test.
            if bounds[0] - a[2] > max(4, min(h, a[3] - a[1]) * 1.8):
                continue
            pairs += 1
            if pairs > MAX_PAIRS:
                raise RegionLimit('Connected-ink adjacency budget exceeded')
            if _neighbors(glyphs[other], item):
                one, two = _find(parent, index), _find(parent, other)
                if one != two:
                    parent[one] = two
        bottom_bins[floor(bottom / 8)].append(index)
        center_bins[floor(center / 8)].append(index)
    groups = defaultdict(list)
    for index, item in enumerate(glyphs):
        groups[_find(parent, index)].append(item)
    return list(groups.values()), pairs


def _envelope(items):
    boxes = [item['bounds'] for item in items]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _words(items):
    items = sorted(items, key=lambda item: (item['bounds'][0], item['bounds'][1]))
    typical_h = median(item['bounds'][3] - item['bounds'][1] for item in items)
    groups, current = [], []
    right = None
    for item in items:
        box = item['bounds']
        if current:
            previous_h = current[-1]['bounds'][3] - current[-1]['bounds'][1]
            local_h = max(min(previous_h, box[3] - box[1]), typical_h * .5)
            if box[0] - right > max(2, local_h * .32):
                groups.append(current)
                current = []
        current.append(item)
        right = max(right or box[2], box[2]) if current else box[2]
    if current:
        groups.append(current)
    return groups


def analyze(image):
    """Return bounded region proposals and mechanical measurements.

    Proposal bounds are in the supplied image's coordinates, even if detection
    downsamples a larger image. This only reads pixels and never modifies input.
    """
    if not isinstance(image, Image.Image) or image.width <= 0 or image.height <= 0:
        raise ValueError('A nonempty PIL image is required')
    scale = min(1.0, MAX_SIDE / max(image.size))
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    if size[0] * size[1] > MAX_PIXELS:
        raise RegionLimit('Recognition thumbnail pixel budget exceeded')
    rgb = image.convert('RGB')
    if rgb.size != size:
        resized = rgb.resize(size, Image.Resampling.LANCZOS)
        rgb.close()
        rgb = resized
    gray = rgb.convert('L')
    try:
        components, runs = _components(gray)
        glyphs, discarded = _glyphs(components, size)
        groups, pairs = _lines(glyphs)
    finally:
        gray.close()
        rgb.close()
    groups = sorted(groups, key=lambda items: (_envelope(items)[1], _envelope(items)[0]))
    proposals = []
    for lineid, items in enumerate(groups):
        envelope = _envelope(items)
        if envelope[3] - envelope[1] < 4:
            continue
        height = median(item['bounds'][3] - item['bounds'][1] for item in items)
        padding = max(2, ceil(height * .12))
        score = sum(item['ink'] for item in items) * log1p(len(items))
        sets = [('line', items)] + [('word', words) for words in _words(items)]
        for kind, members in sets:
            box = _envelope(members)
            padded = [max(0, box[0] - padding), max(0, box[1] - padding), min(size[0], box[2] + padding), min(size[1], box[3] + padding)]
            mapped = [max(0, floor(padded[0] * image.width / size[0])), max(0, floor(padded[1] * image.height / size[1])),
                      min(image.width, ceil(padded[2] * image.width / size[0])), min(image.height, ceil(padded[3] * image.height / size[1]))]
            proposals.append((score, {'bounds': mapped, 'component_count': len(members), 'count': len(members), 'kind': kind, 'line_id': lineid}))
    # Prioritize coherent text-rich lines, then retain their word crops. The
    # region budget is a proposal limit; unproposed pixels remain baseline OCR.
    proposals.sort(key=lambda row: (-row[0], row[1]['line_id'], row[1]['kind'] != 'line', row[1]['bounds'][0]))
    selected = proposals[:MAX_REGIONS]
    selected.sort(key=lambda row: (row[1]['line_id'], row[1]['kind'] != 'line', row[1]['bounds'][0]))
    return {'regions': [item for _, item in selected], 'measurements': {'input_size': list(image.size), 'thumbnail_size': list(size),
            'components': len(components), 'retained_components': len(glyphs), 'discarded': discarded,
            'runs': runs, 'adjacency_checks': pairs, 'line_groups': len(groups), 'proposals': len(proposals),
            'truncated_proposals': max(0, len(proposals) - MAX_REGIONS)}}


def regions(image):
    """Return dict proposals with bounds, count/component_count, kind, line_id."""
    return analyze(image)['regions']
