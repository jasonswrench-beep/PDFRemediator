"""Bounded advisory screen for meaning that may be carried by color alone.

WCAG 2.1 success criterion 1.4.1 (Use of Color) cannot be decided from PDF
objects: whether color is the only carrier of meaning depends on what the
color is for. This module therefore finds *candidates* for a person to look at
and never decides, recolors, repairs or approves anything. The source is read
only and its hash is checked before and after.

Candidate kinds (each record names its kind):

* ``colored-text``: supported digital text whose fill color is chromatic and
  clearly different from the document's dominant body-text color;
* ``link-color-only``: link text drawn in such a color with no underline-like
  line and no visible link border;
* ``multi-hue-graphic``: nearby vector shapes painted in two or more different
  chromatic hues (chart, legend or diagram-like areas);
* ``colored-annotation``: markup annotations (highlights and similar) whose
  own color is chromatic;
* ``color-reference-text``: text that tells the reader to find or do
  something by color (the exact phrase patterns are in
  ``docs/COLOR-ONLY-MEANING.md``).

Raster pictures, shading and pattern paint, annotation appearance streams and
Type3 glyph color are not measured; a page that has them stays
``needs-review`` with its reasons listed. A clean result means only that this
bounded screen found no candidate. It is not a Use of Color result.
"""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import copy
from ctypes import c_int, c_uint, c_ulong, c_void_p, cast
import colorsys
import hashlib
import math
from pathlib import Path
import re

import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as raw

from .contrast import contrast_ratio
from .process import cancelled

POLICY = 'bounded-color-meaning-1'
LIMITS = {'pages': 100, 'characters': 250000, 'records': 400, 'input_bytes': 100 * 1024 * 1024,
          'objects_per_page': 5000, 'chromatic_paths_per_page': 2000, 'annotations_per_page': 500,
          'regions_per_page': 20, 'phrases_per_page': 10, 'phrase_text_characters': 250000,
          'samples_per_record': 5, 'boxes_per_record': 8, 'sample_characters': 80, 'form_depth': 12,
          'resource_entries': 256, 'region_comparisons': 1_000_000}
THRESHOLDS = {
    'chromatic_min_saturation': 0.35, 'chromatic_min_value': 0.25,
    'clear_difference_rgb_distance': 60.0, 'hue_only_luminance_ratio_below': 3.0,
    'region_gap_pt': 72.0, 'min_graphic_dimension_pt': 1.0, 'max_background_area_fraction': 0.5,
    'min_graphic_region_paths': 3, 'min_graphic_region_hues': 2,
    'underline_max_height_pt': 2.5, 'underline_min_overlap_fraction': 0.6}
HUE_BANDS = ((15, 'red'), (45, 'orange'), (70, 'yellow'), (170, 'green'), (200, 'cyan'),
             (260, 'blue'), (300, 'purple'), (345, 'pink'), (360.01, 'red'))
CONFUSABLE_PAIRS = (frozenset({'red', 'green'}), frozenset({'orange', 'green'}))
MARKUP_SUBTYPES = frozenset({'/Highlight', '/Underline', '/Squiggly', '/StrikeOut', '/Square', '/Circle',
                             '/Line', '/Ink', '/Polygon', '/PolyLine', '/FreeText', '/Caret', '/Stamp', '/Text'})
COLOR_WORDS = ('red', 'orange', 'yellow', 'green', 'blue', 'purple', 'violet', 'pink', 'brown',
               'gray', 'grey', 'teal', 'magenta', 'cyan')
_COLOR = '(?:' + '|'.join(COLOR_WORDS) + ')'
_NOUN = ('(?:items?|text|words?|lines?|areas?|boxes|box|buttons?|links?|labels?|bars?|columns?|rows?|cells?|'
         'sections?|squares?|circles?|dots?|marks?|markers?|icons?|fields?|entries|headings?|sentences|ones|'
         'slices?|arrows?|shapes?|triangles?|lights?)')
_SHADE = '(?:(?:bright|dark|light|bold)\\s+)?'
PHRASE_PATTERNS = {
    'color-coded': r'\bcolou?r[- ]?cod(?:ed|ing|e)\b',
    'color-key': r'\bcolou?r[- ]?(?:key|legend)\b',
    'the-color-noun': r'\b(?:the|all|any|each|every)\s+' + _SHADE + _COLOR + r'\s+' + _NOUN + r'\b',
    'shown-in-color': (r'\b(?:highlighted|shaded|marked|underlined|circled|outlined|printed|shown|indicated|'
                        r'labell?ed|displayed|written|colou?red|filled|flagged)\s+(?:in|with|by)\s+' + _SHADE + _COLOR + r'\b'),
    'act-on-color': (r'\b(?:click|press|select|choose|tap|use|follow|see|refer to|look for)\s+the\s+'
                      + _SHADE + _COLOR + r'\b'),
    'noun-in-color': r'\b(?:items?|text|words?|cells?|rows?|columns?|areas?|bars?|lines?|sections?|links?|entries)\s+in\s+' + _COLOR + r'\b',
    'color-means': r'\b' + _COLOR + r'\s+(?:indicates?|means?|shows?|represents?|denotes?|signals?|signifies|marks)\b',
    'the-colors-mean': r'\b(?:the\s+)?colou?rs?\s+(?:indicates?|shows?|means?|represents?|denotes?|signals?)\b',
}
_PHRASES = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in PHRASE_PATTERNS.items()}
CELL = 40.0
FIX = ('Review each candidate in context. Where color is the only way to tell items, states, links or series '
       'apart, repair the original authoring document so the same information is also available another way: '
       'add a text label, a symbol or pattern, an underline or a position cue, and say in the text what a '
       'color means instead of relying on a color key alone. Then export a separate tagged PDF and process it '
       'again. This program does not recolor, add marks to or rewrite pages: that would change visible '
       'content and cannot bypass the exact visual-fidelity gate.')
LIMITATIONS = [
    'This is a candidate screen. Whether color is the only carrier of meaning depends on what it is for; no result here is a Use of Color (WCAG 1.4.1) determination.',
    'Only supported digital text, link annotations, vector path colors, markup-annotation colors and a bounded phrase list are screened.',
    'Raster pictures, shading and pattern paint, annotation or form-field appearance streams and Type3 glyph color are not measured.',
    'Content marked as an artifact is skipped by the graphic screen and counted; whether a graphic is decorative is a human judgment.',
    'A tagged text alternative is not matched to a graphic here; compare the figure description during the figure review.',
    'Meaning carried by position, shape, size or context needs a person; a missing candidate does not show that color is not needed.',
    'PDFium parses a page before the object counters apply; declared limits do not bound the native engine.',
]
KIND_ORDER = {'colored-text': 0, 'link-color-only': 1, 'multi-hue-graphic': 2, 'colored-annotation': 3,
              'color-reference-text': 4, 'page-coverage': 5}


def _tick(cancel):
    if cancelled(cancel):
        raise InterruptedError('Color-meaning inspection cancelled')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _number(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def hue_name(rgb):
    """Name a chromatic color, or None for black, white, grays and pale tints."""
    hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
    if saturation < THRESHOLDS['chromatic_min_saturation'] or value < THRESHOLDS['chromatic_min_value']:
        return None
    degrees = hue * 360
    return next(name for upper, name in HUE_BANDS if degrees < upper)


def _luminance_ratio(first, second):
    return round(contrast_ratio(first, second), 3)


def _transform(rect, matrix):
    a, b, c, d, e, f = matrix
    xs, ys = [], []
    for x, y in ((rect[0], rect[1]), (rect[2], rect[1]), (rect[0], rect[3]), (rect[2], rect[3])):
        xs.append(a * x + c * y + e)
        ys.append(b * x + d * y + f)
    return [min(xs), min(ys), max(xs), max(ys)]


def _page_rect(obj):
    """Bounds in default page space, applying every enclosing Form XObject's matrix."""
    try:
        rect = [float(value) for value in obj.get_bounds()]
        container, depth = obj.container, 0
        while container is not None:
            depth += 1
            if depth > LIMITS['form_depth']:
                return None
            rect = _transform(rect, [float(value) for value in container.get_matrix().get()])
            container = container.container
    except Exception:
        return None
    return rect if all(math.isfinite(value) for value in rect) else None


def _mark_names(obj):
    names = set()
    count = raw.FPDFPageObj_CountMarks(obj.raw)
    if count < 0 or count > 64:
        return None
    for index in range(count):
        mark = raw.FPDFPageObj_GetMark(obj.raw, index)
        length = c_ulong()
        if not mark or not raw.FPDFPageObjMark_GetName(mark, None, 0, length) or not 0 < length.value <= 4096:
            return None
        buffer = (raw.FPDF_WCHAR * ((length.value + 1) // 2))()
        if not raw.FPDFPageObjMark_GetName(mark, buffer, length.value, length):
            return None
        names.add(bytes(buffer)[:length.value].decode('utf-16-le', 'replace').rstrip('\0'))
    return names


def _is_artifact(obj):
    """True for an Artifact-marked object or Form; None when the marks cannot be read."""
    current, depth = obj, 0
    while current is not None and depth <= LIMITS['form_depth']:
        names = _mark_names(current)
        if names is None:
            return None
        if 'Artifact' in names:
            return True
        current, depth = current.container, depth + 1
    return False


def _rgba(getter, handle):
    red, green, blue, alpha = c_uint(), c_uint(), c_uint(), c_uint()
    if not getter(handle, red, green, blue, alpha):
        return None
    return (red.value, green.value, blue.value), alpha.value


def _overlap(a, b, gap=0.0):
    return min(a[2], b[2]) + gap > max(a[0], b[0]) and min(a[3], b[3]) + gap > max(a[1], b[1])


def _round_box(box):
    return [round(float(value), 2) for value in box]


class _Grid:
    """Coarse spatial index over character boxes; keeps rectangle lookups from scanning a page."""

    def __init__(self):
        self.cells, self.items = {}, []

    def add(self, item):
        index = len(self.items)
        self.items.append(item)
        centre = ((item[0] + item[2]) / 2, (item[1] + item[3]) / 2)
        self.cells.setdefault((int(centre[0] // CELL), int(centre[1] // CELL)), []).append(index)

    def inside(self, rect, margin=0.0):
        left, bottom, right, top = rect[0] - margin, rect[1] - margin, rect[2] + margin, rect[3] + margin
        found = []
        for cx in range(int(left // CELL), int(right // CELL) + 1):
            for cy in range(int(bottom // CELL), int(top // CELL) + 1):
                for index in self.cells.get((cx, cy), ()):
                    item = self.items[index]
                    x, y = (item[0] + item[2]) / 2, (item[1] + item[3]) / 2
                    if left <= x <= right and bottom <= y <= top:
                        found.append(item)
        return found


class _LinkIndex:
    """Which link rectangle, if any, a point lies in; empty pages cost nothing."""

    def __init__(self, rects):
        self.rects, self.cells = rects, {}
        for index, rect in enumerate(rects):
            for cx in range(int(rect[0] // CELL), int(rect[2] // CELL) + 1):
                for cy in range(int(rect[1] // CELL), int(rect[3] // CELL) + 1):
                    self.cells.setdefault((cx, cy), []).append(index)

    def contains(self, x, y):
        if not self.rects:
            return False
        return any(self.rects[i][0] <= x <= self.rects[i][2] and self.rects[i][1] <= y <= self.rects[i][3]
                   for i in self.cells.get((int(x // CELL), int(y // CELL)), ()))


def _sample(chars):
    """Characters in reading order (top to bottom, left to right) with spaces put back at gaps and line breaks."""
    ordered = sorted(chars, key=lambda value: (-round((value[1] + value[3]) / 2), value[0]))
    text, previous = '', None
    for value in ordered:
        if previous is not None:
            same_line = abs((value[1] + value[3]) / 2 - (previous[1] + previous[3]) / 2) < 0.5 * max(1.0, value[3] - value[1])
            if not same_line or value[0] - previous[2] > 0.15 * max(1.0, value[3] - value[1]):
                text += ' '
        text += value[5]
        previous = value
    return text[:LIMITS['sample_characters']]


def _page_text_chars(text_page, number, page_result, cancel, state, link_index):
    """Visible character boxes with fill colors, and same-object same-color runs outside links."""
    grid, runs, run = _Grid(), [], None
    unresolved = clipped_or_stroked = 0
    for index in range(text_page.count_chars()):
        if index % 256 == 0:
            _tick(cancel)
        if state['characters'] >= LIMITS['characters']:
            page_result['reasons'].append('character-limit')
            break
        state['characters'] += 1
        generated = raw.FPDFText_IsGenerated(text_page, index)
        code = raw.FPDFText_GetUnicode(text_page, index)
        char = chr(code) if 0 < code <= 0x10ffff and not 0xd800 <= code <= 0xdfff else 'Fffd'
        if generated == 1 or char.isspace():
            run = None
            continue
        obj = raw.FPDFText_GetTextObject(text_page, index)
        mode = raw.FPDFTextObj_GetTextRenderMode(obj) if obj else -1
        if mode in {3, 7}:
            run = None
            continue
        try:
            box = [float(value) for value in text_page.get_charbox(index, loose=True)]
            if not all(math.isfinite(value) for value in box):
                raise ValueError('nonfinite')
        except Exception:
            page_result['reasons'].append('unknown-character-bounds')
            run = None
            continue
        if mode not in {0, 2}:
            clipped_or_stroked += 1
            run = None
            continue
        red, green, blue, alpha = c_uint(), c_uint(), c_uint(), c_uint()
        if not raw.FPDFText_GetFillColor(text_page, index, red, green, blue, alpha) or alpha.value == 0:
            unresolved += 1
            run = None
            continue
        color = (red.value, green.value, blue.value)
        state['visible_characters'] += 1
        state['colors'][color] += 1
        grid.add((*box, color, char))
        if link_index.contains((box[0] + box[2]) / 2, (box[1] + box[3]) / 2):
            run = None
            continue
        identity = (cast(obj, c_void_p).value if obj else None, color)
        if run is None or run['identity'] != identity:
            run = {'identity': identity, 'rgb': color, 'text': '', 'box': box, 'characters': 0}
            runs.append(run)
        run['characters'] += 1
        if len(run['text']) < LIMITS['sample_characters']:
            run['text'] += char
        run['box'] = [min(run['box'][0], box[0]), min(run['box'][1], box[1]),
                      max(run['box'][2], box[2]), max(run['box'][3], box[3])]
    if unresolved:
        page_result['reasons'].append('text-color-unresolved')
    if clipped_or_stroked:
        page_result['reasons'].append('stroked-or-clipping-text-color-not-assessed')
    return grid, runs


def _link_records(pdf_page, page_result, cancel):
    """Link rectangles with the text they cover, border facts and annotation-color candidates."""
    links, markup, other_appearance = [], [], 0
    annots = pdf_page.obj.get('/Annots')
    if annots is None:
        return links, markup
    if not isinstance(annots, pikepdf.Array):
        page_result['reasons'].append('unknown-annotation-structure')
        return links, markup
    if len(annots) > LIMITS['annotations_per_page']:
        page_result['reasons'].append('annotation-limit')
    for position, annot in enumerate(list(annots)[:LIMITS['annotations_per_page']]):
        _tick(cancel)
        if not isinstance(annot, pikepdf.Dictionary):
            page_result['reasons'].append('unknown-annotation-structure')
            continue
        subtype = str(annot.get('/Subtype', ''))
        if subtype == '/Popup':
            continue
        rect = annot.get('/Rect')
        if subtype == '/Link':
            if not isinstance(rect, pikepdf.Array) or len(rect) != 4 or not all(_number(v) for v in rect):
                page_result['reasons'].append('unknown-link-rectangle')
                continue
            numbers = [float(v) for v in rect]
            box = [min(numbers[0], numbers[2]), min(numbers[1], numbers[3]), max(numbers[0], numbers[2]), max(numbers[1], numbers[3])]
            width = 1.0
            border, style = annot.get('/Border'), annot.get('/BS')
            if isinstance(style, pikepdf.Dictionary) and '/W' in style and _number(style['/W']):
                width = float(style['/W'])
            elif isinstance(border, pikepdf.Array) and len(border) >= 3 and _number(border[2]):
                width = float(border[2])
            color = annot.get('/C')
            transparent = isinstance(color, pikepdf.Array) and len(color) == 0
            flags = annot.get('/F', 0)
            hidden = _number(flags) and int(flags) & 0b100010  # Hidden or NoView
            if hidden:
                continue
            links.append({'rect': box, 'border_visible': width > 0 and not transparent, 'border_width': width})
        elif subtype in MARKUP_SUBTYPES:
            color = annot.get('/C')
            if isinstance(color, pikepdf.Array) and len(color) == 3 and all(_number(v) and 0 <= float(v) <= 1 for v in color):
                markup.append({'subtype': subtype, 'rgb': tuple(round(float(v) * 255) for v in color),
                               'has_contents': bool(str(annot.get('/Contents', '')).strip())})
        elif subtype and '/AP' in annot:
            other_appearance += 1
    if other_appearance:
        page_result['reasons'].append('annotation-appearance-color-not-assessed')
    return links, markup


def _paint_resource_reasons(resources, reasons, seen=None, depth=0):
    """Pattern and shading resources on the page or in nested Forms: their paint color is not measured."""
    seen = set() if seen is None else seen
    if not isinstance(resources, pikepdf.Dictionary) or depth > LIMITS['form_depth']:
        return
    patterns, shadings = resources.get('/Pattern'), resources.get('/Shading')
    if isinstance(patterns, pikepdf.Dictionary) and len(patterns):
        reasons.add('pattern-paint-color-not-assessed')
    if isinstance(shadings, pikepdf.Dictionary) and len(shadings):
        reasons.add('shading-color-not-assessed')
    xobjects = resources.get('/XObject')
    if not isinstance(xobjects, pikepdf.Dictionary):
        return
    for value in list(xobjects.values())[:LIMITS['resource_entries']]:
        if isinstance(value, pikepdf.Stream) and value.get('/Subtype') == pikepdf.Name.Form:
            ident = tuple(value.objgen)
            if ident in seen or len(seen) >= LIMITS['resource_entries']:
                continue
            seen.add(ident)
            _paint_resource_reasons(value.get('/Resources'), reasons, seen, depth + 1)


def _page_graphics(page, page_area, page_result, cancel):
    """Chromatic painted paths and thin horizontal lines in page space; flags unsupported paint."""
    paths, lines, skipped_artifacts, examined = [], [], 0, 0
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_SHADING],
                                max_depth=LIMITS['form_depth']):
        examined += 1
        if examined % 256 == 0:
            _tick(cancel)
        if examined > LIMITS['objects_per_page']:
            page_result['reasons'].append('object-limit')
            break
        if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
            page_result['reasons'].append('raster-image-color-not-assessed')
            continue
        if obj.type == raw.FPDF_PAGEOBJ_SHADING:
            page_result['reasons'].append('shading-color-not-assessed')
            continue
        rect = _page_rect(obj)
        if rect is None:
            page_result['reasons'].append('unknown-graphic-bounds')
            continue
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        if max(width, height) < THRESHOLDS['min_graphic_dimension_pt']:
            continue
        fill_mode, stroke = c_int(), c_int()
        if not raw.FPDFPath_GetDrawMode(obj.raw, fill_mode, stroke):
            page_result['reasons'].append('unknown-path-paint')
            continue
        painted = []
        if fill_mode.value:
            painted.append(('fill', _rgba(raw.FPDFPageObj_GetFillColor, obj.raw)))
        if stroke.value:
            painted.append(('stroke', _rgba(raw.FPDFPageObj_GetStrokeColor, obj.raw)))
        if not painted:
            continue
        if height <= THRESHOLDS['underline_max_height_pt'] and width >= 2 * height:
            if len(lines) < LIMITS['chromatic_paths_per_page']:
                lines.append(rect)
        artifact = False
        checked_artifact = False
        for mode, color in painted:
            if color is None:
                page_result['reasons'].append('pattern-or-unresolved-paint-color')
                continue
            rgb, alpha = color
            if alpha == 0 or hue_name(rgb) is None:
                continue
            if mode == 'fill' and width * height > THRESHOLDS['max_background_area_fraction'] * page_area:
                continue
            if not checked_artifact:
                artifact, checked_artifact = _is_artifact(obj), True
            if artifact:
                skipped_artifacts += 1
                continue
            if artifact is None:
                page_result['reasons'].append('unknown-artifact-marks')
                continue
            if len(paths) >= LIMITS['chromatic_paths_per_page']:
                page_result['reasons'].append('chromatic-path-limit')
                return paths, lines, skipped_artifacts
            paths.append({'rect': rect, 'rgb': rgb, 'hue': hue_name(rgb), 'mode': mode})
    return paths, lines, skipped_artifacts


def _regions(paths):
    """Union nearby chromatic paths into regions (grid-hashed single-link clustering).

    Returns None when the comparison budget is exhausted: a partly clustered page must not look complete."""
    gap = THRESHOLDS['region_gap_pt']
    budget = LIMITS['region_comparisons']
    parent = list(range(len(paths)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index
    cells = {}
    for index, path in enumerate(paths):
        left, bottom, right, top = path['rect']
        for cx in range(int((left - gap) // CELL), int((right + gap) // CELL) + 1):
            for cy in range(int((bottom - gap) // CELL), int((top + gap) // CELL) + 1):
                bucket = cells.setdefault((cx, cy), [])
                budget -= len(bucket) + 1
                if budget < 0:
                    return None
                for other in bucket:
                    if find(other) != find(index) and _overlap(paths[other]['rect'], path['rect'], gap):
                        parent[find(other)] = find(index)
                bucket.append(index)
    groups = {}
    for index in range(len(paths)):
        groups.setdefault(find(index), []).append(index)
    return list(groups.values())


def _phrases(text, number, page_result):
    text = re.sub(r'\s+', ' ', text)
    found, seen = [], set()
    for name, pattern in _PHRASES.items():
        for match in pattern.finditer(text):
            phrase = match.group(0).lower()
            if (name, phrase) in seen:
                continue
            seen.add((name, phrase))
            start, end = max(0, match.start() - 60), min(len(text), match.end() + 60)
            found.append({'kind': 'color-reference-text', 'status': 'needs-review', 'page': number,
                          'pattern': name, 'phrase': match.group(0)[:LIMITS['sample_characters']],
                          'context': text[start:end], 'position': match.start()})
    found.sort(key=lambda row: (row['position'], row['pattern']))
    if len(found) > LIMITS['phrases_per_page']:
        page_result['reasons'].append('phrase-limit')
        found = found[:LIMITS['phrases_per_page']]
    for row in found:
        row.pop('position')
    return found


def _confusable(hues):
    return any(pair <= hues for pair in CONFUSABLE_PAIRS)


def assess(path, *, cancel=None, pdf=None, document=None):
    """Read source-bound color evidence; borrowed contexts stay open. Never writes a PDF."""
    _tick(cancel)
    path = Path(path).resolve()
    result = {'policy': POLICY, 'status': 'needs-review', 'advisory': True, 'source_sha256': None,
              'thresholds': dict(THRESHOLDS), 'phrase_patterns': dict(PHRASE_PATTERNS), 'body_color_rgb': None,
              'pages': [], 'findings': [], 'uncertain': [],
              'counts': {'characters': 0, 'visible_characters': 0, 'colored_text_candidates': 0, 'links_checked': 0,
                         'link_candidates': 0, 'graphic_regions': 0, 'annotation_candidates': 0,
                         'phrase_candidates': 0, 'artifact_graphics_skipped': 0, 'records': 0},
              'coverage': {'complete': False,
                           'screened': ['digital-text-fill-color', 'link-text-styling', 'vector-path-colors',
                                        'markup-annotation-colors', 'color-reference-phrases'],
                           'not_assessed': ['raster-images', 'shading-and-pattern-paint',
                                            'annotation-and-widget-appearance-streams', 'type3-glyph-color',
                                            'meaning-from-position-shape-or-context'],
                           'unmeasured_pages': []},
              'limits': dict(LIMITS), 'limitations': list(LIMITATIONS), 'fix_path': FIX}
    try:
        result['source_sha256'] = _sha(path)
        if path.stat().st_size > LIMITS['input_bytes']:
            result['reason'] = 'input-byte-limit'
            return result
        with ExitStack() as stack:
            if pdf is None:
                pdf = stack.enter_context(pikepdf.open(path))
            if document is None:
                document = pdfium.PdfDocument(str(path))
                stack.callback(document.close)
            total_pages = len(pdf.pages)
            document_reasons = set()
            if total_pages > LIMITS['pages']:
                document_reasons.add('page-limit')
            if '/OCProperties' in pdf.Root:
                document_reasons.add('optional-content-context')
            state = {'characters': 0, 'visible_characters': 0, 'colors': Counter(), 'phrase_characters': 0}
            gathered = []
            for number, pdf_page in enumerate(pdf.pages, 1):
                _tick(cancel)
                if number > LIMITS['pages'] or state['characters'] >= LIMITS['characters']:
                    result['coverage']['unmeasured_pages'].extend(range(number, total_pages + 1))
                    break
                page_result = {'page': number, 'status': 'pass', 'reasons': []}
                result['pages'].append(page_result)
                fonts = pdf_page.resources.get('/Font', {}) if isinstance(pdf_page.resources, pikepdf.Dictionary) else {}
                if isinstance(fonts, pikepdf.Dictionary) and any(
                        isinstance(font, pikepdf.Dictionary) and font.get('/Subtype') == pikepdf.Name.Type3
                        for font in fonts.values()):
                    page_result['reasons'].append('type3-glyph-color-not-assessed')
                paint_reasons = set()
                _paint_resource_reasons(pdf_page.resources, paint_reasons)
                page_result['reasons'].extend(sorted(paint_reasons))
                rotation = pdf_page.obj.get('/Rotate', 0)
                if not _number(rotation) or float(rotation) % 90:
                    page_result['reasons'].append('unsupported-page-rotation')
                crop = [float(value) for value in pdf_page.cropbox]
                page_area = max(1.0, (crop[2] - crop[0]) * (crop[3] - crop[1]))
                page = document[number - 1]
                text_page = None
                try:
                    text_page = page.get_textpage()
                    links, markup = _link_records(pdf_page, page_result, cancel)
                    grid, runs = _page_text_chars(text_page, number, page_result, cancel, state,
                                                  _LinkIndex([link['rect'] for link in links]))
                    paths, lines, skipped = _page_graphics(page, page_area, page_result, cancel)
                    result['counts']['artifact_graphics_skipped'] += skipped
                    phrases = []
                    if state['phrase_characters'] < LIMITS['phrase_text_characters']:
                        text = text_page.get_text_range()
                        state['phrase_characters'] += len(text)
                        phrases = _phrases(text[:LIMITS['phrase_text_characters']], number, page_result)
                    else:
                        page_result['reasons'].append('phrase-text-limit')
                finally:
                    if text_page is not None:
                        text_page.close()
                    page.close()
                gathered.append({'number': number, 'grid': grid, 'runs': runs, 'links': links, 'markup': markup,
                                 'paths': paths, 'lines': lines, 'phrases': phrases, 'page_result': page_result})
            result['counts']['characters'] = state['characters']
            result['counts']['visible_characters'] = state['visible_characters']
            body = None
            if state['colors']:
                body = sorted(state['colors'].items(), key=lambda item: (-item[1], sum(item[0])))[0][0]
                result['body_color_rgb'] = list(body)
            clear = THRESHOLDS['clear_difference_rgb_distance']

            def add(record):
                if result['counts']['records'] >= LIMITS['records']:
                    document_reasons.add('record-limit')
                    return False
                result['findings'].append(record)
                result['counts']['records'] += 1
                return True

            for item in gathered:
                _tick(cancel)
                number, grid, page_result = item['number'], item['grid'], item['page_result']
                text_hues = {hue_name(run['rgb']) for run in item['runs']} - {None}
                # (a) colored text outside links
                groups = {}
                for run in item['runs']:
                    hue = hue_name(run['rgb'])
                    if body is None or hue is None or math.dist(run['rgb'], body) < clear:
                        continue
                    group = groups.setdefault(run['rgb'], {'runs': 0, 'characters': 0, 'samples': [], 'boxes': []})
                    group['runs'] += 1
                    group['characters'] += run['characters']
                    if run['text'] not in group['samples'] and len(group['samples']) < LIMITS['samples_per_record']:
                        group['samples'].append(run['text'])
                    if len(group['boxes']) < LIMITS['boxes_per_record']:
                        group['boxes'].append(_round_box(run['box']))
                for rgb, group in sorted(groups.items()):
                    ratio = _luminance_ratio(rgb, body)
                    if add({'kind': 'colored-text', 'status': 'needs-review', 'page': number, 'color_rgb': list(rgb),
                            'hue': hue_name(rgb), 'body_color_rgb': list(body), 'run_count': group['runs'],
                            'character_count': group['characters'],
                            'difference': 'hue-only' if ratio < THRESHOLDS['hue_only_luminance_ratio_below'] else 'hue-and-lightness',
                            'luminance_ratio_to_body': ratio, 'samples': group['samples'], 'boxes': group['boxes'],
                            'red_green_confusable_pair_on_page': _confusable(text_hues)}):
                        result['counts']['colored_text_candidates'] += 1
                # (b) links distinguished only by color
                for link in item['links']:
                    result['counts']['links_checked'] += 1
                    covered = grid.inside(link['rect'], margin=1.0)
                    if not covered or body is None:
                        continue
                    color = Counter(char[4] for char in covered).most_common(1)[0][0]
                    if hue_name(color) is None or math.dist(color, body) < clear:
                        continue
                    box = [min(c[0] for c in covered), min(c[1] for c in covered),
                           max(c[2] for c in covered), max(c[3] for c in covered)]
                    span = max(1e-9, box[2] - box[0])
                    underlined = any(
                        min(box[2], line[2]) - max(box[0], line[0]) >= THRESHOLDS['underline_min_overlap_fraction'] * span
                        and line[3] >= box[1] - 4 and line[1] <= box[1] + 0.4 * (box[3] - box[1])
                        for line in item['lines'])
                    if underlined or link['border_visible']:
                        continue
                    ratio = _luminance_ratio(color, body)
                    if add({'kind': 'link-color-only', 'status': 'needs-review', 'page': number,
                            'color_rgb': list(color), 'hue': hue_name(color), 'body_color_rgb': list(body),
                            'luminance_ratio_to_body': ratio,
                            'meets_3_to_1_with_body': ratio >= 3.0,
                            'underline_found': False, 'border_visible': False,
                            'sample': _sample(covered),
                            'rect': _round_box(link['rect'])}):
                        result['counts']['link_candidates'] += 1
                # (c) nearby vector shapes in two or more hues
                regions = []
                clusters = _regions(item['paths'])
                if clusters is None:
                    page_result['reasons'].append('region-work-limit')
                    clusters = []
                for members in clusters:
                    hues = {item['paths'][i]['hue'] for i in members}
                    if len(members) < THRESHOLDS['min_graphic_region_paths'] or len(hues) < THRESHOLDS['min_graphic_region_hues']:
                        continue
                    rects = [item['paths'][i]['rect'] for i in members]
                    box = [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]
                    regions.append((len(members), box, members, hues))
                regions.sort(key=lambda row: (-row[0], row[1]))
                if len(regions) > LIMITS['regions_per_page']:
                    page_result['reasons'].append('region-limit')
                for count, box, members, hues in regions[:LIMITS['regions_per_page']]:
                    inside = grid.inside(box)
                    nearby = grid.inside(box, margin=THRESHOLDS['region_gap_pt'])
                    colors = sorted({item['paths'][i]['rgb'] for i in members})
                    if add({'kind': 'multi-hue-graphic', 'status': 'needs-review', 'page': number, 'bbox': _round_box(box),
                            'hues': sorted(hues), 'colors_rgb': [list(c) for c in colors[:8]], 'path_count': count,
                            'text_characters_inside': len(inside), 'text_characters_nearby': len(nearby),
                            'text_sample': _sample(nearby),
                            'red_green_confusable_pair_on_page': _confusable(hues)}):
                        result['counts']['graphic_regions'] += 1
                # (e) colored markup annotations
                tally = Counter((row['subtype'], row['rgb']) for row in item['markup'] if hue_name(row['rgb']) is not None)
                for (subtype, rgb), count in sorted(tally.items()):
                    if add({'kind': 'colored-annotation', 'status': 'needs-review', 'page': number, 'subtype': subtype,
                            'color_rgb': list(rgb), 'hue': hue_name(rgb), 'count': count,
                            'with_comment_text': sum(1 for row in item['markup'] if row['rgb'] == rgb and row['subtype'] == subtype and row['has_contents'])}):
                        result['counts']['annotation_candidates'] += 1
                # (d) text that points at color
                for row in item['phrases']:
                    if add(row):
                        result['counts']['phrase_candidates'] += 1
                page_result['reasons'] = sorted(set(page_result['reasons']))
                page_findings = sum(1 for row in result['findings'] if row['page'] == number)
                if page_result['reasons']:
                    page_result['status'] = 'needs-review'
                    if result['counts']['records'] < LIMITS['records']:
                        result['uncertain'].append({'kind': 'page-coverage', 'status': 'needs-review', 'page': number,
                                                    'reasons': list(page_result['reasons'])})
                        result['counts']['records'] += 1
                    else:
                        document_reasons.add('record-limit')
                elif page_findings:
                    page_result['status'] = 'needs-review'
            unknown = bool(document_reasons or result['coverage']['unmeasured_pages']
                           or any(page['reasons'] for page in result['pages']))
            result['coverage']['complete'] = not unknown
            if document_reasons:
                result['coverage']['reasons'] = sorted(document_reasons)
            if result['findings'] or unknown:
                result['status'] = 'needs-review'
            elif result['counts']['visible_characters'] or any(item['paths'] for item in gathered):
                result['status'] = 'pass'
            else:
                result['status'] = 'not-applicable'
            result['findings'].sort(key=lambda row: (row['page'], KIND_ORDER.get(row['kind'], 9)))
        if _sha(path) != result['source_sha256']:
            raise ValueError('The source changed during color-meaning inspection')
    except InterruptedError:
        raise
    except Exception as exc:
        result.update(status='error', error={'type': type(exc).__name__, 'message': str(exc)[:300]})
        result['coverage']['complete'] = False
    return result


GRAPHIC_KIND = 'multi-hue-graphic'
ORIGINAL_GRAPHICS_NOTE = ('Chart-like shapes were read from the unmodified input, because this program marks untagged '
                          'shapes as artifacts in its processed copy and the graphic screen skips artifacts there.')


def _usable(measured):
    return (isinstance(measured, dict) and measured.get('policy') == POLICY and measured.get('advisory') is True
            and measured.get('status') in {'pass', 'fail', 'needs-review', 'not-applicable'}
            and isinstance(measured.get('findings'), list) and isinstance(measured.get('uncertain'), list)
            and isinstance(measured.get('pages'), list) and isinstance(measured.get('counts'), dict)
            and isinstance(measured.get('coverage'), dict) and isinstance(measured['coverage'].get('complete'), bool)
            and isinstance(measured['coverage'].get('unmeasured_pages'), list)
            and all(isinstance(page, dict) and isinstance(page.get('page'), int) and isinstance(page.get('reasons'), list)
                    for page in measured['pages']))


def with_original_graphics(measured, original):
    """Return the screen of a processed copy with the graphic findings of the unmodified input.

    The tagging step of this program wraps untagged shapes in ``/Artifact`` in its result, and the graphic screen
    skips artifacts, so a chart that the author never marked disappears from the result's screen. The input's own
    screen still sees it. Only the graphic findings (and what limits them) are taken from the input; text, link,
    annotation and phrase findings stay the result's own (an OCR text layer exists only there). When the result
    hid nothing that the input did not already hide, or either record is unusable, ``measured`` is returned as is.
    """
    if not (_usable(measured) and _usable(original)):
        return measured
    hidden = measured['counts'].get('artifact_graphics_skipped')
    already = original['counts'].get('artifact_graphics_skipped')
    if not (isinstance(hidden, int) and isinstance(already, int)) or hidden <= already:
        return measured
    if [page['page'] for page in measured['pages']] != [page['page'] for page in original['pages']]:
        return measured
    merged = copy.deepcopy(measured)
    graphics = [copy.deepcopy(row) for row in original['findings'] if isinstance(row, dict) and row.get('kind') == GRAPHIC_KIND]
    kept = [row for row in merged['findings'] if not (isinstance(row, dict) and row.get('kind') == GRAPHIC_KIND)]
    document_reasons = set(merged['coverage'].get('reasons', [])) | set(original['coverage'].get('reasons', []))
    by_page = {page['page']: page for page in original['pages']}
    for page in merged['pages']:
        page['reasons'] = sorted(set(page['reasons']) | set(by_page[page['page']]['reasons']))
    unmeasured = sorted(set(merged['coverage']['unmeasured_pages']) | set(original['coverage']['unmeasured_pages']))
    coverage_records = {row['page']: row for row in merged['uncertain']
                        if isinstance(row, dict) and row.get('kind') == 'page-coverage' and isinstance(row.get('page'), int)}
    others = [row for row in merged['uncertain'] if row not in coverage_records.values()]
    for page in merged['pages']:
        if page['reasons']:
            page['status'] = 'needs-review'
            coverage_records[page['page']] = {'kind': 'page-coverage', 'status': 'needs-review', 'page': page['page'],
                                              'reasons': list(page['reasons'])}
    uncertain = others + [coverage_records[number] for number in sorted(coverage_records)]
    room = LIMITS['records'] - len(kept) - len(uncertain)
    if len(graphics) > max(room, 0):
        graphics = graphics[:max(room, 0)]
        document_reasons.add('record-limit')
    findings = sorted(kept + graphics, key=lambda row: (row.get('page', 0), KIND_ORDER.get(row.get('kind'), 9)))
    for page in merged['pages']:
        if any(row.get('page') == page['page'] for row in findings):
            page['status'] = 'needs-review'
    merged['findings'], merged['uncertain'] = findings, uncertain
    merged['counts'].update(graphic_regions=len(graphics), artifact_graphics_skipped=already,
                            records=len(findings) + len(uncertain))
    complete = (measured['coverage']['complete'] and original['coverage']['complete'] and not unmeasured
                and 'record-limit' not in document_reasons)
    merged['coverage'].update(complete=complete, unmeasured_pages=unmeasured)
    if document_reasons:
        merged['coverage']['reasons'] = sorted(document_reasons)
    if findings or not complete:
        merged['status'] = 'needs-review'
    elif 'pass' in (measured['status'], original['status']):
        merged['status'] = 'pass'
    merged['limitations'] = list(merged.get('limitations', [])) + [ORIGINAL_GRAPHICS_NOTE]
    merged['graphics_from_original'] = {'source_sha256': original.get('source_sha256'),
                                        'result_artifact_graphics_skipped': hidden,
                                        'original_artifact_graphics_skipped': already}
    return merged
