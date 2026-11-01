"""Bounded advisory measurements of digital text, without changing a PDF.

The nine-point screen is a readability aid, not a WCAG minimum or a vendor
accessibility result. PDFium's nominal font size is multiplied by the complete
character matrix's vertical basis and the page UserUnit. Glyph ink-box height is
never used as the font size. Context, visibility and unsupported content remain
explicit human review work; there is no font substitution or automatic resize.
"""
from __future__ import annotations

from contextlib import ExitStack
from ctypes import c_ulong, cast, c_void_p
from decimal import Decimal
import hashlib
import math
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as raw

from .process import cancelled

POLICY = 'bounded-small-font-1'
THRESHOLD_PT = 9.0
LIMITS = {'pages': 100, 'characters': 250000, 'records': 2000,
          'input_bytes': 100 * 1024 * 1024, 'streams_per_page': 256,
          'resource_entries': 256, 'declared_content_bytes_per_page': 2 * 1024 * 1024,
          'operations_per_page': 200000, 'form_depth': 12, 'sample_characters': 80}
FIX = ('Review the reported text in context. If it needs enlargement, increase '
       'the font in the original authoring document, reflow the layout, export a '
       'separate tagged PDF and process it again. Automatic resizing is not '
       'available because it can change wrapping, layout and visible content.')
LIMITATIONS = [
    'Nine points is an optional readability threshold, not a WCAG minimum, PDF/UA rule or vendor result.',
    'Measurements cover supported selectable digital text, not images of text, outlined text or annotation/widget appearance text.',
    'Superscripts, subscripts, artifacts, captions, footnotes and other context require human judgment; no semantic exception is inferred.',
    'Clipping, transparency, replacement text, vertical writing, Type3 fonts and ambiguous geometry remain review work.',
    'PDFium parsing happens before glyph counters apply; declared encoded lengths do not bound decompression or native engine resource use.',
    'A complete supported digital-text screen is not complete document accessibility or proof of comfortable reading.',
]


def _tick(cancel):
    if cancelled(cancel): raise InterruptedError('Small-font inspection cancelled')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def _plain(value):
    return isinstance(value, pikepdf.Dictionary)


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float, Decimal)) and math.isfinite(float(value))


def _context(page, cancel):
    """Conservative raw context census; never construct or save PDF objects."""
    reasons = set(); state = {'operations': 0, 'streams': 0, 'declared_bytes': 0, 'shows': 0}
    path = set()
    if page.obj.get('/Annots'): reasons.add('annotation-and-widget-text-not-assessed')
    if page.obj.get('/Group'): reasons.add('page-transparency-group')
    rotation = page.obj.get('/Rotate', 0)
    if not _number(rotation) or float(rotation) % 90: reasons.add('unsupported-page-rotation')
    unit = page.obj.get('/UserUnit', 1)
    if not _number(unit) or not 0 < float(unit) <= 75000:
        reasons.add('invalid-user-unit'); unit = None
    else: unit = float(unit)

    def scan(owner, resources, depth=0):
        _tick(cancel)
        if depth > LIMITS['form_depth']:
            reasons.add('form-depth-limit'); return
        if not _plain(resources): reasons.add('unknown-resources'); return
        if len(resources) > LIMITS['resource_entries']:
            reasons.add('resource-entry-limit'); return
        fonts = resources.get('/Font', {})
        if not isinstance(fonts, (dict, pikepdf.Dictionary)) or len(fonts) > LIMITS['resource_entries']:
            reasons.add('font-resource-limit-or-unknown')
        else:
            for font in fonts.values():
                if not _plain(font): reasons.add('unknown-font-resource'); continue
                if font.get('/Subtype') == pikepdf.Name.Type3: reasons.add('type3-font')
                encoding = font.get('/Encoding')
                if isinstance(encoding, pikepdf.Name) and str(encoding).endswith('-V') or _plain(encoding) and encoding.get('/WMode') == 1:
                    reasons.add('vertical-writing')
        content = owner.obj.get('/Contents') if isinstance(owner, pikepdf.Page) else owner
        streams = list(content) if isinstance(content, pikepdf.Array) else [content] if content is not None else []
        for stream in streams:
            state['streams'] += 1
            length = stream.get('/Length') if isinstance(stream, pikepdf.Stream) else None
            if not isinstance(length, int) or isinstance(length, bool) or length < 0:
                reasons.add('unknown-content-length'); return
            state['declared_bytes'] += length
        if state['streams'] > LIMITS['streams_per_page'] or state['declared_bytes'] > LIMITS['declared_content_bytes_per_page']:
            reasons.add('content-metadata-limit'); return
        try:
            for instruction in pikepdf.parse_content_stream(owner):
                state['operations'] += 1
                if state['operations'] % 256 == 0: _tick(cancel)
                if state['operations'] > LIMITS['operations_per_page']:
                    reasons.add('content-operation-limit'); return
                operands, operator = instruction.operands, str(instruction.operator)
                if operator in {'Tj', 'TJ', "'", '"'}: state['shows'] += 1
                if operator in {'W', 'W*'}: reasons.add('clipping-context')
                elif operator == 'Tr' and (len(operands) != 1 or not _number(operands[0]) or int(operands[0]) in {4, 5, 6, 7}):
                    reasons.add('text-clipping-context')
                elif operator == 'gs': reasons.add('extended-graphics-state')
                elif operator == 'Ts' and (len(operands) != 1 or not _number(operands[0]) or float(operands[0]) != 0):
                    reasons.add('superscript-or-subscript-context')
                elif operator in {'BMC', 'BDC'}:
                    if operands and str(operands[0]) == '/Artifact': reasons.add('artifact-context')
                    if operands and str(operands[0]) == '/OC': reasons.add('optional-content-context')
                    if operator == 'BDC' and len(operands) == 2:
                        properties = operands[1]
                        if isinstance(properties, pikepdf.Name): properties = resources.get('/Properties', {}).get(str(properties))
                        if _plain(properties) and any(key in properties for key in ('/ActualText', '/Alt', '/E')):
                            reasons.add('replacement-or-alternative-text')
                elif operator in {'BI', 'INLINE IMAGE'}: reasons.add('image-text-not-assessed')
                elif operator in {'S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*', 'sh'}:
                    reasons.add('outlined-or-graphic-text-not-assessed')
                elif operator == 'Do':
                    name = str(operands[0]) if len(operands) == 1 else ''
                    xobject = resources.get('/XObject', {}).get(name)
                    if isinstance(xobject, pikepdf.Stream) and xobject.get('/Subtype') == pikepdf.Name.Form:
                        ident = tuple(xobject.objgen)
                        if ident in path: reasons.add('cyclic-form'); continue
                        path.add(ident)
                        try: scan(xobject, xobject.get('/Resources', resources), depth + 1)
                        finally: path.remove(ident)
                    elif isinstance(xobject, pikepdf.Stream) and xobject.get('/Subtype') == pikepdf.Name.Image:
                        reasons.add('image-text-not-assessed')
                    else: reasons.add('unresolved-xobject')
        except InterruptedError: raise
        except Exception: reasons.add('content-context-parse-error')
    scan(page, page.resources)
    return sorted(reasons), unit, state


def _pointer(value):
    return cast(value, c_void_p).value if value else None


def _object_context(obj, *, clip_context_proven=True):
    reasons = set()
    mode = raw.FPDFTextObj_GetTextRenderMode(obj)
    if mode not in {0, 1, 2, 3, 4, 5, 6, 7}: reasons.add('unknown-text-render-mode')
    if mode in {4, 5, 6}: reasons.add('text-clipping-render-mode')
    clip = raw.FPDFPageObj_GetClipPath(obj)
    if clip:
        count = raw.FPDFClipPath_CountPaths(clip)
        # PDFium returns the address of a clip wrapper even without a clipping
        # reference. Its CountPaths implementation returns -1 for that empty
        # default state; positive paths indicate actual clipping. The raw
        # W/W*/Tr preflight independently guards explicit/text clipping.
        if count > 0: reasons.add('text-clip-path')
        elif count == -1 and not clip_context_proven: reasons.add('unknown-text-clip-state')
        elif count not in {-1, 0}: reasons.add('unknown-text-clip-state')
    else: reasons.add('unknown-text-clip-state')
    if raw.FPDFPageObj_HasTransparency(obj): reasons.add('transparent-or-blended-text')
    count = raw.FPDFPageObj_CountMarks(obj)
    if count < 0 or count > 64: reasons.add('unknown-mark-context')
    else:
        for index in range(count):
            mark = raw.FPDFPageObj_GetMark(obj, index)
            length = c_ulong()
            if not mark or not raw.FPDFPageObjMark_GetName(mark, None, 0, length) or not 0 < length.value <= 4096:
                reasons.add('unknown-mark-context'); continue
            buffer = (raw.FPDF_WCHAR * ((length.value + 1) // 2))()
            if not raw.FPDFPageObjMark_GetName(mark, buffer, length.value, length):
                reasons.add('unknown-mark-context'); continue
            name = bytes(buffer)[:length.value].decode('utf-16-le', 'replace').rstrip('\0')
            if name == 'Artifact': reasons.add('artifact-context')
            if name == 'OC': reasons.add('optional-content-context')
            for key in (b'ActualText', b'Alt', b'E'):
                if raw.FPDFPageObjMark_GetParamValueType(mark, key) != raw.FPDF_OBJECT_UNKNOWN:
                    reasons.add('replacement-or-alternative-text')
    return int(mode), sorted(reasons)


def _geometry(nominal, matrix, unit):
    reasons = []
    if not math.isfinite(nominal) or nominal <= 0: reasons.append('unknown-nominal-font-size')
    if matrix is None or not all(math.isfinite(value) for value in matrix): reasons.append('unknown-character-matrix')
    if unit is None: reasons.append('invalid-user-unit')
    if reasons: return None, None, reasons
    a, b, c, d = matrix[:4]
    width, height = math.hypot(a, b), math.hypot(c, d)
    if min(width, height) <= 1e-10 or a * d - b * c <= 1e-10:
        reasons.append('degenerate-or-reflected-text-matrix')
    if abs(a * c + b * d) > 1e-5 * width * height or abs(width - height) > 1e-5 * max(width, height):
        reasons.append('anisotropic-or-skewed-text-matrix')
    return nominal * height * unit, nominal * width * unit, reasons


def assess(path, *, cancel=None, pdf=None, document=None):
    """Read source-bound digital-text evidence; borrowed contexts stay open."""
    _tick(cancel); path = Path(path).resolve()
    result = {'policy': POLICY, 'status': 'needs-review', 'advisory': True,
        'threshold_pt': THRESHOLD_PT, 'comparison': 'strictly-less-than',
        'calculation': 'abs(nominal_pt) * hypot(character_matrix.c, character_matrix.d) * user_unit',
        'point_size_units': '1/72 inch', 'bbox_units': 'default PDF user-space units before page rotation',
        'source_sha256': None, 'pages': [], 'findings': [], 'uncertain': [],
        'counts': {'characters': 0, 'measured_characters': 0, 'below_threshold_characters': 0,
                   'uncertain_characters': 0, 'invisible_characters': 0, 'ignored_characters': 0,
                   'groups': 0, 'records': 0},
        'coverage': {'complete': False, 'supported_digital_text_only': True, 'unmeasured_pages': []},
        'limits': dict(LIMITS), 'limitations': list(LIMITATIONS), 'fix_path': FIX}
    try:
        result['source_sha256'] = _sha(path)
        if path.stat().st_size > LIMITS['input_bytes']:
            result['reason'] = 'input-byte-limit'; return result
        with ExitStack() as stack:
            if pdf is None: pdf = stack.enter_context(pikepdf.open(path))
            if document is None:
                document = pdfium.PdfDocument(str(path)); stack.callback(document.close)
            total_pages = len(pdf.pages)
            reasons_document = set()
            if total_pages > LIMITS['pages']: reasons_document.add('page-limit')
            if '/OCProperties' in pdf.Root: reasons_document.add('optional-content-context')
            for number, source_page in enumerate(pdf.pages, 1):
                _tick(cancel)
                if number > LIMITS['pages'] or result['counts']['characters'] >= LIMITS['characters']:
                    result['coverage']['unmeasured_pages'].extend(range(number, total_pages + 1)); break
                reasons, unit, raw_state = _context(source_page, cancel)
                clip_context_proven = not any(reason in {
                    'clipping-context', 'text-clipping-context', 'extended-graphics-state',
                    'unknown-resources', 'resource-entry-limit', 'font-resource-limit-or-unknown',
                    'unknown-font-resource', 'unknown-content-length', 'content-metadata-limit',
                    'content-operation-limit', 'content-context-parse-error', 'form-depth-limit',
                    'cyclic-form', 'unresolved-xobject'} for reason in reasons)
                page_result = {'page': number, 'status': 'pass', 'reasons': reasons,
                    'counts': {'characters': 0, 'measured_characters': 0, 'below_threshold_characters': 0,
                               'uncertain_characters': 0, 'invisible_characters': 0, 'ignored_characters': 0},
                    'min_effective_pt': None, 'raw_text_show_operations': raw_state['shows']}
                result['pages'].append(page_result)
                page = document[number - 1]; text_page = None
                try:
                    text_page = page.get_textpage(); total = text_page.count_chars()
                    object_cache = {}; objects = set(); group = None
                    def flush():
                        nonlocal group
                        if group is None: return
                        result['counts']['groups'] += 1
                        if group['status'] != 'pass':
                            if result['counts']['records'] >= LIMITS['records']:
                                if 'record-limit' not in page_result['reasons']: page_result['reasons'].append('record-limit')
                            else:
                                result['findings' if group['status'] == 'fail' else 'uncertain'].append(group)
                                result['counts']['records'] += 1
                        group = None
                    for index in range(total):
                        if index % 256 == 0: _tick(cancel)
                        if result['counts']['characters'] >= LIMITS['characters']:
                            page_result['reasons'].append('character-limit'); break
                        for count in (result['counts'], page_result['counts']): count['characters'] += 1
                        generated = raw.FPDFText_IsGenerated(text_page, index)
                        unicode_value = raw.FPDFText_GetUnicode(text_page, index)
                        char = chr(unicode_value) if 0 < unicode_value <= 0x10ffff and not 0xd800 <= unicode_value <= 0xdfff else '\ufffd'
                        obj = raw.FPDFText_GetTextObject(text_page, index); ident = _pointer(obj)
                        if ident: objects.add(ident)
                        if generated == 1 or char.isspace():
                            flush()
                            for count in (result['counts'], page_result['counts']): count['ignored_characters'] += 1
                            continue
                        local = []
                        if generated < 0: local.append('unknown-generated-character-state')
                        if not obj:
                            mode, object_reasons = -1, ['missing-text-object']
                        else:
                            if ident not in object_cache: object_cache[ident] = _object_context(obj, clip_context_proven=clip_context_proven)
                            mode, object_reasons = object_cache[ident]
                        if mode in {3, 7}:
                            flush()
                            for count in (result['counts'], page_result['counts']): count['invisible_characters'] += 1
                            continue
                        local.extend(object_reasons)
                        if char == '\ufffd' or raw.FPDFText_HasUnicodeMapError(text_page, index) != 0:
                            local.append('unknown-unicode-mapping')
                        nominal = float(raw.FPDFText_GetFontSize(text_page, index))
                        raw_matrix = raw.FS_MATRIX()
                        matrix = ([float(getattr(raw_matrix, key)) for key in ('a', 'b', 'c', 'd', 'e', 'f')]
                                  if raw.FPDFText_GetMatrix(text_page, index, raw_matrix) else None)
                        effective, width, geometry_reasons = _geometry(nominal, matrix, unit)
                        local.extend(geometry_reasons)
                        # Raw replacement/Type3/vertical contexts cannot supply a
                        # reliable per-glyph em measurement or literal sample.
                        local.extend(reason for reason in reasons if reason in {
                            'replacement-or-alternative-text', 'type3-font', 'vertical-writing', 'invalid-user-unit',
                            'superscript-or-subscript-context', 'clipping-context', 'extended-graphics-state',
                            'text-clipping-context', 'optional-content-context'})
                        try:
                            bbox = list(text_page.get_charbox(index))
                            if not all(math.isfinite(v) for v in bbox): raise ValueError('nonfinite')
                            crop = list(source_page.cropbox)
                            if bbox[0] < crop[0] or bbox[1] < crop[1] or bbox[2] > crop[2] or bbox[3] > crop[3]:
                                local.append('text-outside-page-crop')
                        except Exception:
                            bbox = None; local.append('unknown-character-bounds')
                        local = sorted(set(local))
                        status = 'needs-review' if local else 'fail' if effective < THRESHOLD_PT else 'pass'
                        bucket = 'uncertain_characters' if local else 'below_threshold_characters' if status == 'fail' else None
                        for count in (result['counts'], page_result['counts']):
                            if bucket: count[bucket] += 1
                            if not local: count['measured_characters'] += 1
                        if not local:
                            previous = page_result['min_effective_pt']
                            page_result['min_effective_pt'] = effective if previous is None else min(previous, effective)
                        signature = (ident, status, nominal, tuple(matrix or ()), mode, tuple(local))
                        if group is None or group['_signature'] != signature:
                            flush()
                            group = {'_signature': signature, 'status': status, 'page': number,
                                'char_start': index, 'char_count': 0, 'sample': '', 'bbox': bbox,
                                'nominal_pt': nominal if math.isfinite(nominal) else None,
                                'effective_pt': effective, 'width_pt': width, 'matrix': matrix,
                                'user_unit': unit, 'rotation': int(source_page.obj.get('/Rotate', 0)) if _number(source_page.obj.get('/Rotate', 0)) else None,
                                'render_mode': mode, 'reasons': local}
                        group['char_count'] += 1
                        if len(group['sample']) < LIMITS['sample_characters']: group['sample'] += char
                        if bbox is not None and group['bbox'] is not None:
                            old = group['bbox']; group['bbox'] = [min(old[0], bbox[0]), min(old[1], bbox[1]), max(old[2], bbox[2]), max(old[3], bbox[3])]
                    flush()
                    page_result['text_objects'] = len(objects)
                    if raw_state['shows'] > len(objects): page_result['reasons'].append('text-object-coverage-not-proven')
                    if not page_result['counts']['measured_characters'] and raw_state['shows']:
                        page_result['reasons'].append('no-measured-visible-digital-text')
                finally:
                    if text_page is not None: text_page.close()
                    page.close()
                page_result['reasons'] = sorted(set(page_result['reasons']))
                if page_result['counts']['below_threshold_characters']: page_result['status'] = 'fail'
                elif page_result['reasons'] or page_result['counts']['uncertain_characters']: page_result['status'] = 'needs-review'
            unknown = bool(reasons_document or result['coverage']['unmeasured_pages'] or any(p['reasons'] or p['counts']['uncertain_characters'] for p in result['pages']))
            result['coverage']['complete'] = not unknown
            if reasons_document: result['coverage']['reasons'] = sorted(reasons_document)
            if result['findings']: result['status'] = 'fail'
            elif unknown: result['status'] = 'needs-review'
            elif result['counts']['measured_characters']: result['status'] = 'pass'
            else: result['status'] = 'not-applicable'
        for record in result['findings'] + result['uncertain']: record.pop('_signature', None)
        if _sha(path) != result['source_sha256']:
            raise ValueError('The source changed during small-font inspection')
    except InterruptedError: raise
    except Exception as exc:
        result.update(status='error', error={'type': type(exc).__name__, 'message': str(exc)[:300]})
        result['coverage']['complete'] = False
    for record in result['findings'] + result['uncertain']: record.pop('_signature', None)
    return result
