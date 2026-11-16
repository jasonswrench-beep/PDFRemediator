"""Finds likely logo and branding pictures and groups them for a person to decide, without changing a PDF.

A logo is one of the few pictures where the right answer is often one of two things: give it a short description that names the
organisation, or mark it decorative because the same name is already written beside it. The program cannot know which. It can
show the reviewer every place the same picture appears, so a decision is made once and still applied to each occurrence on
purpose.

How a figure becomes a candidate (policy ``bounded-logo-branding-1``; every threshold is recorded in the evidence):
- the same picture (identical pixels) is a figure on two or more pages and takes up at most 15 percent of the page; or
- it takes up at most 6 percent of the page and sits in the top or bottom band or a side margin; or
- its existing description already calls it a logo.
Anything else is left alone and not listed. These are screening signals about position, size and repetition. They say nothing about
what the picture means, and a picture that is not listed may still be a logo.

The module only reads. It opens the exact prepared PDF in memory, never saves it, and never decides or describes anything.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import math
import re

import pypdfium2 as pdfium
import pypdfium2.raw as raw

from .process import cancelled

POLICY = 'bounded-logo-branding-1'
LABEL = 'Logo and branding'
THRESHOLDS = {'repeat_pages_at_least': 2, 'repeat_max_area_fraction': 0.15, 'margin_max_area_fraction': 0.06,
              'header_footer_band_fraction': 0.12, 'side_band_fraction': 0.08}
LIMITS = {'pages': 300, 'figures': 2000, 'objects_per_page': 20000, 'image_pixels': 16_000_000}
LOGO_WORD = re.compile(r'\b(?:logo|logotype|wordmark|brand ?mark|emblem|crest|seal)\b', re.I)
GUIDANCE = (
    'For a picture that carries meaning, write a short description: name the organisation or product as the logo shows it, add '
    '"logo" only if that helps, and leave out slogans and marketing words. A line of about 3 to 10 words is usually enough. '
    'If the same name is already written next to the picture, marking it decorative is usually better, so a screen reader does '
    'not repeat it on every page. Look at each page before choosing.')
SOURCE_GUIDANCE = (
    'Make the lasting fix where the document is written. In a word processor or layout program, give the logo alternative text '
    'once (right-click the picture and add it), or mark it decorative if its name is written beside it, and put it in the page '
    'header or footer so it is repeated as an artifact. Then export a new tagged PDF and process that.')
LIMITATIONS = [
    'Candidates are found from size, position and repetition only; the program does not read the picture and cannot tell what it shows.',
    'Pictures inside Form XObjects, vector-drawn logos and pictures the page content does not tie to a figure are not matched here and stay in the ordinary figure list.',
    'Two copies of a logo drawn from different image files are treated as different pictures even if they look alike.',
    'Listing a picture here does not decide anything. Each occurrence keeps its own decision, acceptance and result.',
]


def _tick(cancel):
    if cancelled(cancel):
        raise InterruptedError('Logo and branding screening cancelled')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _mcids(obj):
    found = set()
    count = raw.FPDFPageObj_CountMarks(obj.raw)
    if not 0 <= count <= 128:
        return found
    for index in range(count):
        mark = raw.FPDFPageObj_GetMark(obj.raw, index)
        value = ctypes.c_int()
        if mark and raw.FPDFPageObjMark_GetParamIntValue(mark, b'MCID', ctypes.byref(value)):
            found.add(value.value)
    return found


def _picture_fingerprint(obj):
    """Hash of the picture's own pixels (not its size or place on the page); None when it cannot be read within bounds."""
    try:
        # The picture's own pixels, still owned by PDFium's page object: read them, never close or free them here.
        bitmap = obj.get_bitmap(render=False)
        if bitmap.width * bitmap.height > LIMITS['image_pixels']:
            return None, None
        return hashlib.sha256(bytes(bitmap.buffer)).hexdigest(), [int(bitmap.width), int(bitmap.height)]
    except Exception:
        return None, None


def _position(bounds, size):
    """Which part of the page a box centre sits in: header, footer, left margin, right margin or body."""
    width, height = size
    if not width or not height:
        return 'unknown'
    centre_x, centre_y = (bounds[0] + bounds[2]) / 2 / width, (bounds[1] + bounds[3]) / 2 / height
    if centre_y >= 1 - THRESHOLDS['header_footer_band_fraction']:
        return 'header'
    if centre_y <= THRESHOLDS['header_footer_band_fraction']:
        return 'footer'
    if centre_x <= THRESHOLDS['side_band_fraction']:
        return 'left margin'
    if centre_x >= 1 - THRESHOLDS['side_band_fraction']:
        return 'right margin'
    return 'body'


def _declared(item):
    box = item.get('figure_bbox')
    if (isinstance(box, dict) and box.get('status') == 'valid' and isinstance(box.get('bbox'), list) and isinstance(box.get('page_box'), list)
            and len(box['bbox']) == 4 and len(box['page_box']) == 4 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in box['bbox'] + box['page_box'])):
        return box['bbox'], box['page_box']
    return None


def assess(pdf_path, decisions, *, cancel=None):
    """Evidence for every figure occurrence, and the candidates among them.

    ``decisions`` is the review's decision list; only figure-description rows (one per figure occurrence) are examined, each with
    the matching figure-purpose row when the review offers one.
    """
    figures = [item for item in decisions if isinstance(item, dict) and item.get('kind') == 'figure-description']
    purposes = {(item.get('element'), item.get('page')): item for item in decisions
                if isinstance(item, dict) and item.get('kind') == 'figure-purpose'}
    reasons = []
    if len(figures) > LIMITS['figures']:
        reasons.append('More than %d figure occurrences; only the first %d were examined.' % (LIMITS['figures'], LIMITS['figures']))
        figures = figures[:LIMITS['figures']]
    by_page = {}
    for item in figures:
        if type(item.get('page')) is int and item['page'] >= 1:
            by_page.setdefault(item['page'], []).append(item)
    occurrences = []
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        count = len(document)
        for number in sorted(by_page):
            _tick(cancel)
            if number > LIMITS['pages'] or number > count:
                reasons.append('Page %d is outside the pages this screen examines.' % number)
                continue
            page = document[number - 1]
            try:
                size = tuple(float(v) for v in page.get_size())
                plain = page.get_rotation() == 0 and all(abs(a) < .01 for a in page.get_cropbox()[:2])
                wanted = {}
                for item in by_page[number]:
                    ids = {ref['mcid'] for ref in item.get('references', []) if isinstance(ref, dict) and ref.get('stream') == 'page'
                           and ref.get('page') == number and type(ref.get('mcid')) is int}
                    wanted[item['id']] = ids
                found = {identifier: [] for identifier in wanted}
                if plain and any(wanted.values()):
                    for index, obj in enumerate(page.get_objects(max_depth=1)):
                        if index >= LIMITS['objects_per_page']:
                            reasons.append('Page %d has more than %d page objects; later ones were not examined.' % (number, LIMITS['objects_per_page']))
                            break
                        if obj.type != raw.FPDF_PAGEOBJ_IMAGE:
                            continue
                        marked = _mcids(obj)
                        if not marked:
                            continue
                        for identifier, ids in wanted.items():
                            if ids & marked:
                                bounds = obj.get_bounds()
                                if all(math.isfinite(v) for v in bounds):
                                    fingerprint, pixels = _picture_fingerprint(obj)
                                    found[identifier].append({'bounds': [float(v) for v in bounds], 'asset': fingerprint, 'pixels': pixels})
                for item in by_page[number]:
                    pictures = found[item['id']]
                    source, bounds, asset, pixels = 'unavailable', None, None, None
                    if pictures:
                        left, bottom = min(p['bounds'][0] for p in pictures), min(p['bounds'][1] for p in pictures)
                        right, top = max(p['bounds'][2] for p in pictures), max(p['bounds'][3] for p in pictures)
                        bounds, source = [left, bottom, right, top], 'picture-object'
                        hashes = sorted(p['asset'] for p in pictures)
                        asset = hashes[0] if len(hashes) == 1 and hashes[0] else (_digest(hashes) if all(hashes) else None)
                        pixels = pictures[0]['pixels'] if len(pictures) == 1 else None
                    else:
                        declared = _declared(purposes.get((item.get('element'), number), {}))
                        if declared and plain:
                            (x0, y0, x1, y1), box = declared
                            width, height = box[2] - box[0], box[3] - box[1]
                            if width > 0 and height > 0:
                                bounds, source = [x0 - box[0], y0 - box[1], x1 - box[0], y1 - box[1]], 'declared-bounding-box'
                    area = None
                    position = 'unknown'
                    if bounds and size[0] > 0 and size[1] > 0:
                        area = max(0.0, (min(bounds[2], size[0]) - max(bounds[0], 0)) * (min(bounds[3], size[1]) - max(bounds[1], 0))) / (size[0] * size[1])
                        position = _position(bounds, size)
                    occurrences.append({'id': item['id'], 'page': number, 'element': item.get('element'), 'asset_sha256': asset, 'picture_pixels': pixels,
                                        'geometry_source': source, 'bounds_pdf': [round(v, 3) for v in bounds] if bounds else None,
                                        'page_size_pdf': [round(v, 3) for v in size], 'area_fraction': None if area is None else round(area, 5),
                                        'position': position, 'current_description': str(item.get('current', ''))[:300],
                                        'context_sha256': item.get('context_sha256')})
            finally:
                page.close()
    finally:
        document.close()
    pages_by_asset = {}
    for row in occurrences:
        if row['asset_sha256']:
            pages_by_asset.setdefault(row['asset_sha256'], set()).add(row['page'])
    candidates = []
    for row in occurrences:
        signals = []
        area = row['area_fraction']
        repeats = len(pages_by_asset.get(row['asset_sha256'], ()))
        if repeats >= THRESHOLDS['repeat_pages_at_least'] and area is not None and area <= THRESHOLDS['repeat_max_area_fraction']:
            signals.append('The same picture is a figure on %d pages and is small on the page.' % repeats)
        if area is not None and area <= THRESHOLDS['margin_max_area_fraction'] and row['position'] in ('header', 'footer', 'left margin', 'right margin'):
            signals.append('A small picture in the %s of the page.' % row['position'])
        if LOGO_WORD.search(row['current_description']):
            signals.append('Its description already calls it a logo or brand mark.')
        row['repeat_pages'] = repeats
        row['signals'] = signals
        if signals:
            candidates.append(row)
    groups = {}
    for row in candidates:
        key = row['asset_sha256'] if row['asset_sha256'] and row['repeat_pages'] >= 2 else 'single:' + row['id']
        groups.setdefault(key, []).append(row)
    listed = []
    for key, rows in groups.items():
        rows.sort(key=lambda row: (row['page'], row['id']))
        repeated = not key.startswith('single:')
        listed.append({'id': 'logo-' + _digest({'policy': POLICY, 'key': key})[:24], 'label': LABEL,
                       'kind': 'same-picture-on-several-pages' if repeated else 'single-occurrence',
                       'asset_sha256': key if repeated else None, 'member_ids': [row['id'] for row in rows],
                       'pages': sorted({row['page'] for row in rows}),
                       'summary': ('The same picture on %d pages.' % len({row['page'] for row in rows})) if repeated else 'One occurrence.'})
    listed.sort(key=lambda group: (group['pages'][0], group['id']))
    status = 'not-applicable' if not figures else 'measured' if not reasons else 'partial'
    return {'policy': POLICY, 'label': LABEL, 'status': status, 'thresholds': dict(THRESHOLDS), 'limits': dict(LIMITS),
            'figures_examined': len(occurrences), 'figures_in_review': len(figures), 'candidate_count': len(candidates),
            'partial_reasons': reasons, 'occurrences': candidates, 'groups': listed, 'guidance': GUIDANCE,
            'source_guidance': SOURCE_GUIDANCE, 'limitations': list(LIMITATIONS)}
