"""Reviewed, bounded AcroForm names and structure-based navigation.

Fields, widgets, values, appearances and painting are retained.  No internal
field name, visible label, field behaviour or submission identity is authored.
"""
from __future__ import annotations

from collections import Counter
import copy
from decimal import Decimal
import json
import math
import re
from urllib.parse import urlsplit

import pikepdf

from . import structure_edits as graph
from .navigation_edits import canonical_snapshot

KINDS = {'form-controls'}
POLICY = 'reviewed-form-1'
LIMITS = {'fields': 100, 'widgets': 200, 'pages': 50, 'orders': 100,
          'children': 200, 'text_chars': 4000, 'payload_chars': 150000}
_NEUTRAL = {'/Document', '/Sect', '/Div'}


def _fail(message):
    from .sidecar import DecisionError
    raise DecisionError(message)


def _dict(value):
    return isinstance(value, pikepdf.Dictionary) and not isinstance(value, pikepdf.Stream)


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def canonical_value(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _text(value):
    return str(value) if isinstance(value, pikepdf.String) else None


def _new_text(value, *, nullable=False):
    if value is None and nullable:
        return
    if (not isinstance(value, str) or not value.strip() or len(value) > LIMITS['text_chars']
            or any(ord(c) < 32 and c not in '\n\r\t' or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        _fail('A changed form name must be explicit nonblank text within 4000 characters without invalid controls')


def source_value(context):
    return {'fields': [{'field': field['field'], 'tooltip': field['tooltip'],
                        'widgets': [{'widget': widget['widget'], 'alternative': widget['alternative']}
                                    for widget in field['widgets']]} for field in context['fields']],
            'pages': [{'page': page['page'], 'tabs': page['tabs']} for page in context['pages']],
            'orders': [{'parent': order['parent'], 'children': order['children'][:]} for order in context['orders']]}


def parse_value(value, context, *, current=None):
    if not isinstance(value, str) or len(value) > LIMITS['payload_chars']:
        _fail('Form choices exceed the supported canonical plan size')
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        _fail('Form choices require canonical JSON')
    if canonical_value(data) != value:
        _fail('Form choices require canonical JSON without duplicate properties')
    if value == current:
        return data
    if not isinstance(data, dict) or set(data) != {'fields', 'pages', 'orders'}:
        _fail('A form plan requires every existing field, page and navigation group')
    for key in ('fields', 'pages', 'orders'):
        if not isinstance(data[key], list):
            _fail('Form plan arrays must retain the complete source sequence')
    expected = source_value(context)
    if len(data['fields']) != len(expected['fields']):
        _fail('Keep every existing form field exactly once in source order')
    for field, old in zip(data['fields'], expected['fields']):
        if (not isinstance(field, dict) or set(field) != {'field', 'tooltip', 'widgets'}
                or field.get('field') != old['field'] or not isinstance(field.get('widgets'), list)
                or len(field['widgets']) != len(old['widgets'])):
            _fail('Keep each existing field and its complete widget sequence')
        if field['tooltip'] != old['tooltip']:
            _new_text(field['tooltip'])
        for widget, original in zip(field['widgets'], old['widgets']):
            if not isinstance(widget, dict) or set(widget) != {'widget', 'alternative'} or widget.get('widget') != original['widget']:
                _fail('Keep each source widget exactly once in source order')
            if widget['alternative'] != original['alternative']:
                _new_text(widget['alternative'], nullable=True)
    if len(data['pages']) != len(expected['pages']):
        _fail('Keep every original form page exactly once in source order')
    pages = {}
    for page, old in zip(data['pages'], expected['pages']):
        if not isinstance(page, dict) or set(page) != {'page', 'tabs'} or type(page.get('page')) is not int or page['page'] != old['page']:
            _fail('Keep every original form page exactly once in source order')
        if page['tabs'] != old['tabs'] and page['tabs'] != 'S':
            _fail('A changed page navigation setting must follow document structure')
        pages[page['page']] = page['tabs']
    if len(data['orders']) != len(expected['orders']):
        _fail('Keep every original form navigation group exactly once')
    for order, old, scope in zip(data['orders'], expected['orders'], context['orders']):
        if (not isinstance(order, dict) or set(order) != {'parent', 'children'} or order.get('parent') != old['parent']
                or not isinstance(order.get('children'), list) or any(not isinstance(c, str) for c in order['children'])
                or len(order['children']) != len(old['children']) or set(order['children']) != set(old['children'])):
            _fail('Navigation may only permute the complete existing Form siblings')
        if order['children'] != old['children'] and pages.get(scope['page']) != 'S':
            _fail('A changed form sequence requires structure-based page navigation')
    return data


def validate_value(item):
    context = item.get('form_context')
    if item.get('kind') not in KINDS or item.get('structural_eligible') is not True:
        _fail('This form has no complete supported source proof')
    if not isinstance(context, dict) or context.get('policy') != POLICY or context.get('limits') != LIMITS:
        _fail('Form source capabilities changed')
    return parse_value(item.get('value'), context, current=item.get('current'))


_BASE14 = {'Times-Roman', 'Times-Bold', 'Times-Italic', 'Times-BoldItalic',
           'Courier', 'Courier-Bold', 'Courier-Oblique', 'Courier-BoldOblique',
           'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique', 'Helvetica-BoldOblique',
           'Symbol', 'ZapfDingbats'}
_ACTIONS = {'/GoTo', '/GoToR', '/GoToE', '/Launch', '/Thread', '/URI', '/Sound',
            '/Movie', '/Hide', '/Named', '/SubmitForm', '/ResetForm', '/ImportData',
            '/JavaScript', '/SetOCGState', '/Rendition', '/Trans', '/GoTo3DView', '/GoToDp', '/RichMediaExecute', '/SetState', '/NoOp'}


_FIT_KINDS = {'/Fit', '/FitB', '/FitH', '/FitV', '/FitBH', '/FitBV', '/XYZ', '/FitR'}
_OUTLINE_KEYS = {'/Title', '/Parent', '/Prev', '/Next', '/First', '/Last', '/Count', '/Dest', '/A', '/C', '/F', '/SE'}
_PLACEMENTS = {'/Block', '/Inline', '/Before', '/Start', '/End'}
_SCOPES = {'/Row', '/Column', '/Both'}
_NUMBERINGS = {'/None', '/Unordered', '/Ordered', '/Decimal', '/UpperRoman', '/LowerRoman', '/UpperAlpha', '/LowerAlpha', '/Disc', '/Circle', '/Square'}


def _passive_navigation(action, page_ids):
    # A plain jump inside the document, or a web or mail link. Nothing in it can
    # run, open, send, hide or change anything, and it cannot chain to another action.
    if not _dict(action) or not set(map(str, action.keys())) <= {'/Type', '/S', '/URI', '/D', '/IsMap'}: return False
    if '/Type' in action and action['/Type'] != pikepdf.Name.Action: return False
    kind = action.get('/S')
    if kind == pikepdf.Name.URI:
        uri = action.get('/URI')
        if '/D' in action or ('/IsMap' in action and action['/IsMap'] is not False) or not isinstance(uri, pikepdf.String): return False
        text = str(uri)
        try: parsed = urlsplit(text)
        except ValueError: return False
        scheme = parsed.scheme.lower()
        return (0 < len(text) <= 8192 and all(ord(c) >= 32 and ord(c) != 127 for c in text)
                and scheme in {'http', 'https', 'mailto'} and (scheme == 'mailto' or bool(parsed.netloc)))
    if kind == pikepdf.Name.GoTo:
        if '/URI' in action or '/IsMap' in action: return False
        dest = action.get('/D')
        if isinstance(dest, (pikepdf.String, pikepdf.Name)):
            text = str(dest)
            return 0 < len(text) <= 4096 and all(ord(c) >= 32 and ord(c) != 127 for c in text)
        if not isinstance(dest, pikepdf.Array) or not 2 <= len(dest) <= 6: return False
        return (graph._id(dest[0]) in page_ids and isinstance(dest[1], pikepdf.Name) and str(dest[1]) in _FIT_KINDS
                and all(item is None or isinstance(item, (int, float, Decimal)) and not isinstance(item, bool) and math.isfinite(float(item))
                        for item in list(dest)[2:]))
    return False


def _passive_navigation_owners(pdf):
    # Ids of the page links and bookmarks whose only action is passive navigation,
    # and of those action objects. Anything outside the page /Annots arrays and the
    # /Outlines chain is deliberately not recognised.
    owners = set(); actions = set()
    try:
        page_ids = {graph._id(page.obj) for page in pdf.pages}
        def consider(owner):
            action = owner.get('/A'); ident = graph._id(owner)
            if not ident or not _passive_navigation(action, page_ids): return
            owners.add(ident)
            if graph._id(action): actions.add(graph._id(action))
        for page in pdf.pages:
            annotations = page.obj.get('/Annots')
            if not isinstance(annotations, pikepdf.Array): continue
            for annotation in annotations:
                if _dict(annotation) and annotation.get('/Subtype') == pikepdf.Name.Link and '/A' in annotation: consider(annotation)
        outlines = pdf.Root.get('/Outlines')
        queue = [outlines.get('/First')] if _dict(outlines) else []; visited = set()
        while queue and len(visited) < 100000:
            item = queue.pop(); ident = graph._id(item)
            if not _dict(item) or not ident or ident in visited: continue
            visited.add(ident)
            if '/A' in item and set(map(str, item.keys())) <= _OUTLINE_KEYS: consider(item)
            queue.extend([item.get('/First'), item.get('/Next')])
    except (ValueError, RuntimeError, TypeError, KeyError, pikepdf.PdfError):
        return set(), set()
    return owners, actions


def _form_signal_scan(pdf):
    # Dictionary properties only: never decode a content/font/script stream or
    # manufacture a temporary PDF object while deciding whether a form exists.
    # A page link or bookmark that only jumps or opens a web address is passive
    # navigation, not form authority, provided nothing else refers to its action.
    owners, passive = _passive_navigation_owners(pdf)
    queue = [(pdf.Root, True, 0, None)] + [(obj, False, 0, None) for obj in pdf.objects]
    seen = set(); incoming = Counter(); active = False; unsafe = False; count = 0; attributes = []
    while queue:
        value, edge, depth, via = queue.pop(); count += 1
        if count > 1000000 or depth > 200:
            return {'active': True, 'unsafe': True, 'complete': False, 'incoming': incoming, 'attributes': attributes}
        ident = graph._id(value)
        if ident:
            if edge: incoming[ident] += 1
            if edge and ident in passive and via != 'passive-action': unsafe = True
            if ident in seen: continue
            seen.add(ident); depth = 0
        if isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            if (value.get('/Subtype') == pikepdf.Name.Widget or '/FT' in value or '/XFA' in value
                    or value.get('/Type') == pikepdf.Name.Sig or '/ByteRange' in value):
                active = True
            if '/A' in value and ident not in owners: attributes.append(value)
            navigation = via == 'passive-action' or (ident in passive and not edge)
            if (any(key in value for key in ('/AA', '/JS', '/OpenAction', '/ByteRange', '/XFA', '/Lock', '/SV'))
                    or value.get('/Type') == pikepdf.Name.Sig or value.get('/FT') == pikepdf.Name.Sig
                    or not navigation and (value.get('/Type') == pikepdf.Name.Action
                        or isinstance(value.get('/S'), pikepdf.Name) and str(value['/S']) in _ACTIONS)):
                # Actual or unproved action/signature authority is never inert.
                unsafe = True
            queue.extend((child, True, depth + 1, 'passive-action' if ident in owners and str(key) == '/A' else None)
                         for key, child in value.items())
        elif isinstance(value, pikepdf.Array):
            queue.extend((child, True, depth + 1, None) for child in value)
    return {'active': active, 'unsafe': unsafe, 'complete': True, 'incoming': incoming, 'attributes': attributes}


def _inert_encoding(value):
    names = {'/StandardEncoding', '/MacRomanEncoding', '/MacExpertEncoding', '/WinAnsiEncoding'}
    if isinstance(value, pikepdf.Name): return str(value) in names
    if not _dict(value) or any(str(key) not in {'/Type', '/BaseEncoding', '/Differences'} for key in value): return False
    if '/Type' in value and value['/Type'] != pikepdf.Name.Encoding: return False
    if '/BaseEncoding' in value and (not isinstance(value['/BaseEncoding'], pikepdf.Name) or str(value['/BaseEncoding']) not in names): return False
    differences = value.get('/Differences', pikepdf.Array())
    if not isinstance(differences, pikepdf.Array) or len(differences) > 512: return False
    code = None; assigned = set()
    for item in differences:
        if _int(item) and 0 <= item <= 255: code = item
        elif isinstance(item, pikepdf.Name) and re.fullmatch(r'/[A-Za-z0-9_.+-]{1,128}', str(item)):
            if code is None or code > 255 or code in assigned: return False
            assigned.add(code); code += 1
        else: return False
    return True


def _inert_resources(value):
    if value is None: return set()
    if not _dict(value) or any(str(key) not in {'/Font', '/Encoding'} for key in value): return None
    fonts = value.get('/Font', pikepdf.Dictionary()); encodings = value.get('/Encoding', pikepdf.Dictionary())
    if not _dict(fonts) or not _dict(encodings) or len(fonts) > 100 or len(encodings) > 100: return None
    if any(not _inert_encoding(encoding) for encoding in encodings.values()): return None
    for name, font in fonts.items():
        if (not re.fullmatch(r'/[A-Za-z0-9_.+-]{1,128}', str(name)) or not _dict(font)
                or any(str(key) not in {'/Type', '/Subtype', '/BaseFont', '/Name', '/Encoding'} for key in font)
                or font.get('/Type') != pikepdf.Name.Font or font.get('/Subtype') != pikepdf.Name.Type1
                or not isinstance(font.get('/BaseFont'), pikepdf.Name)
                or str(font['/BaseFont']).lstrip('/') not in _BASE14
                or '/Name' in font and not isinstance(font['/Name'], pikepdf.Name)
                or '/Encoding' in font and not _inert_encoding(font['/Encoding'])):
            return None
    return {str(name) for name in fonts}


def _inert_default_appearance(value, fonts):
    if value is None: return True
    if not isinstance(value, pikepdf.String): return False
    text = str(value)
    if len(text) > 4096 or not text.isascii() or any(ord(c) < 32 and c not in '\t\r\n\f' for c in text): return False
    stack = []; tokens = text.split()
    if len(tokens) > 256: return False
    for token in tokens:
        if re.fullmatch(r'/[A-Za-z0-9_.+-]{1,128}', token):
            stack.append(token); continue
        if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', token):
            number = Decimal(token)
            if not number.is_finite() or abs(number) > 10000: return False
            stack.append(number); continue
        if token == 'Tf':
            if len(stack) != 2 or not isinstance(stack[0], str) or stack[0] not in fonts or not isinstance(stack[1], Decimal) or stack[1] < 0: return False
        elif token in {'g', 'rg', 'k'}:
            if len(stack) != {'g': 1, 'rg': 3, 'k': 4}[token] or any(not isinstance(x, Decimal) or not 0 <= x <= 1 for x in stack): return False
        elif token in {'Tc', 'Tw', 'TL', 'Ts', 'Tz', 'Tr'}:
            if len(stack) != 1 or not isinstance(stack[0], Decimal): return False
            if token == 'Tz' and stack[0] <= 0: return False
            if token == 'Tr' and (stack[0] != int(stack[0]) or not 0 <= stack[0] <= 7): return False
        else: return False
        stack = []
    return not stack




def _inert_stream_text(stream):
    # Inspect existing marked text only. No actions, rendering or rewriting.
    allowed = {'q', 'Q', 'cm', 'w', 'J', 'j', 'M', 'BT', 'ET', 'Tf', 'Tm', 'Td', 'TD', 'T*',
               'Tc', 'Tw', 'Tz', 'TL', 'Tr', 'Ts', 'g', 'rg', 'k', 'G', 'RG', 'K',
               'BMC', 'BDC', 'EMC', 'Tj', 'TJ', "'", '"'}
    try:
        if len(stream.read_bytes()) > 5000000: return None
        markers = {}; current = None; painted = False; in_text = False; graphics = []; font_selected = False; frames = []
        fonts = stream.Resources.get('/Font', pikepdf.Dictionary())
        if not _dict(fonts): return None
        for index, instruction in enumerate(pikepdf.parse_content_stream(stream)):
            if index >= 200000: return None
            operands, operator = instruction; op = str(operator)
            if op not in allowed: return None
            if op == 'q': graphics.append(font_selected)
            elif op == 'Q':
                if not graphics: return None
                font_selected = graphics.pop()
            elif op == 'BT':
                if in_text: return None
                in_text = True
            elif op == 'ET':
                if not in_text: return None
                in_text = False
            elif op == 'Tf':
                if (len(operands) != 2 or not isinstance(operands[0], pikepdf.Name)
                        or str(operands[0]) not in fonts or not _dict(fonts[str(operands[0])])
                        or fonts[str(operands[0])].get('/Type') != pikepdf.Name.Font
                        or isinstance(operands[1], bool) or not isinstance(operands[1], (int, float, Decimal))
                        or not math.isfinite(float(operands[1])) or operands[1] <= 0): return None
                font_selected = True
            elif op == 'BMC':
                # A plain marked-content wrapper has no MCID or property list and owns nothing; text inside /Artifact is
                # decorative. Optional content is refused.
                if len(operands) != 1 or not isinstance(operands[0], pikepdf.Name) or str(operands[0]) == '/OC': return None
                frames.append('artifact' if str(operands[0]) == '/Artifact' else None)
            elif op == 'BDC':
                if (current is not None or len(operands) != 2 or not isinstance(operands[0], pikepdf.Name)
                        or str(operands[0]) in {'/Artifact', '/OC'} or not _dict(operands[1])
                        or set(map(str, operands[1].keys())) != {'/MCID'}
                        or not _int(operands[1].get('/MCID')) or operands[1]['/MCID'] < 0
                        or operands[1]['/MCID'] in markers): return None
                current = operands[1]['/MCID']; markers[current] = str(operands[0]); painted = False; frames.append(current)
            elif op == 'EMC':
                if not frames: return None
                if isinstance(frames.pop(), int):
                    if current is None or not painted: return None
                    current = None
            elif op in {'Tj', 'TJ', "'", '"'}:
                decorative = 'artifact' in frames
                if not in_text or not font_selected or (current is None and not decorative): return None
                if op == 'TJ':
                    if len(operands) != 1 or not isinstance(operands[0], pikepdf.Array): return None
                    parts = list(operands[0])
                    if any(not isinstance(part, pikepdf.String) and (isinstance(part, bool)
                           or not isinstance(part, (int, float, Decimal)) or not math.isfinite(float(part))) for part in parts): return None
                else:
                    if len(operands) != (3 if op == '"' else 1) or not isinstance(operands[-1], pikepdf.String): return None
                    parts = [operands[-1]]
                painted = painted or (not decorative and any(isinstance(part, pikepdf.String) and len(bytes(part)) > 0 for part in parts))
        return markers if current is None and not in_text and not graphics and not frames else None
    except (AttributeError, TypeError, ValueError, OverflowError, pikepdf.PdfError):
        return None


def _inert_mcr_streams(pdf, root, references):
    if not references: return True
    try:
        parent_tree, _ = graph._parent_arrays(root)
        seen = set(); parsed = {}; stream_keys = {}
        for owner, mcr in references:
            stream = mcr['/Stm']; ident = graph._id(stream); mcid = mcr['/MCID']
            if (not isinstance(stream, pikepdf.Stream) or not ident
                    or stream.get('/Type') != pikepdf.Name.XObject or stream.get('/Subtype') != pikepdf.Name.Form
                    or '/FormType' in stream and (not _int(stream['/FormType']) or stream['/FormType'] != 1)
                    or set(map(str, stream.keys())) - {'/Type', '/Subtype', '/FormType', '/BBox', '/Matrix',
                        '/Resources', '/StructParents', '/Length', '/Filter', '/DecodeParms'}
                    or not _dict(stream.get('/Resources')) or not _int(stream.get('/StructParents'))
                    or stream['/StructParents'] < 0): return False
            for key, count in [('/BBox', 4), ('/Matrix', 6)]:
                if key == '/Matrix' and key not in stream: continue
                values = stream.get(key)
                if (not isinstance(values, pikepdf.Array) or len(values) != count
                        or any(isinstance(number, bool) or not isinstance(number, (int, float, Decimal))
                               or not math.isfinite(float(number)) for number in values)): return False
            key = stream['/StructParents']; slots = parent_tree.get(key)
            if (not isinstance(slots, pikepdf.Array) or mcid >= len(slots)
                    or graph._id(slots[mcid]) != graph._id(owner) or (ident, mcid) in seen): return False
            seen.add((ident, mcid))
            if ident not in parsed:
                if key in stream_keys and stream_keys[key] != ident: return False
                stream_keys[key] = ident
                # A stream key may not alias another page or Form XObject.
                if any(isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)) and graph._id(obj) != ident
                       and '/StructParents' in obj and obj['/StructParents'] == key for obj in pdf.objects): return False
                parsed[ident] = _inert_stream_text(stream)
            if parsed[ident] is None or parsed[ident].get(mcid) != str(owner['/S']): return False
        return True
    except (AttributeError, TypeError, ValueError, OverflowError, pikepdf.PdfError):
        return False


def _inert_layout_attributes(pdf, scan):
    # Permit only the passive Figure layout attribute emitted by the established
    # tagger. A dictionary that merely resembles a structure element is not proof.
    if not scan['attributes']: return True
    root = pdf.Root.get('/StructTreeRoot'); root_id = graph._id(root)
    if not _dict(root) or not root_id or root.get('/Type') != pikepdf.Name.StructTreeRoot: return False
    rolemap = root.get('/RoleMap')
    if rolemap is not None and (not _dict(rolemap) or {'/Figure', '/Table', '/TH', '/TD', '/L'} & set(map(str, rolemap.keys()))): return False
    owners = {}; seen_arrays = set(); queue = [(root.get('/K'), root_id, 0)]; count = 0; stream_references = []
    while queue:
        node, parent_id, depth = queue.pop(); count += 1
        if count > 200000 or depth > 200: return False
        if isinstance(node, pikepdf.Array):
            ident = graph._id(node)
            if ident:
                if ident in seen_arrays: return False
                seen_arrays.add(ident)
            if any(isinstance(child, pikepdf.Array) for child in node): return False
            queue.extend((child, parent_id, depth + 1) for child in node)
        elif _int(node):
            if node < 0 or parent_id == root_id: return False
        elif _dict(node):
            kind = node.get('/Type')
            if kind == pikepdf.Name.StructElem or kind is None and '/S' in node and '/P' in node:
                # /Type is optional on a structure element; the same ownership proof below still applies.
                ident = graph._id(node)
                if (not ident or ident in owners or graph._id(node.get('/P')) != parent_id
                        or not isinstance(node.get('/S'), pikepdf.Name)): return False
                owners[ident] = node
                if '/K' in node: queue.append((node['/K'], ident, depth + 1))
            elif kind == pikepdf.Name.MCR:
                if (parent_id == root_id or set(map(str, node.keys())) - {'/Type', '/Pg', '/MCID', '/Stm'}
                        or not _int(node.get('/MCID')) or node['/MCID'] < 0): return False
                if '/Pg' in node and (not _dict(node['/Pg']) or node['/Pg'].get('/Type') != pikepdf.Name.Page): return False
                if '/Stm' in node: stream_references.append((owners[parent_id], node))
            elif kind == pikepdf.Name.OBJR:
                if (parent_id == root_id or set(map(str, node.keys())) - {'/Type', '/Pg', '/Obj'}
                        or not _dict(node.get('/Obj'))): return False
                if '/Pg' in node and (not _dict(node['/Pg']) or node['/Pg'].get('/Type') != pikepdf.Name.Page): return False
            else: return False
        else: return False
    if not _inert_mcr_streams(pdf, root, stream_references): return False
    for owner in scan['attributes']:
        ident = graph._id(owner); attributes = owner['/A']
        if not ident or ident not in owners or not _dict(attributes): return False
        role = owner.get('/S'); keys = set(map(str, attributes.keys())); bbox = None
        if role in (pikepdf.Name.Figure, pikepdf.Name.Table):
            # Where the element sits on the page.
            if (attributes.get('/O') != pikepdf.Name.Layout or not {'/O', '/BBox'} <= keys <= {'/O', '/BBox', '/Placement'}
                    or '/Placement' in keys and (not isinstance(attributes['/Placement'], pikepdf.Name)
                                                 or str(attributes['/Placement']) not in _PLACEMENTS)): return False
            bbox = attributes.get('/BBox')
            if (not isinstance(bbox, pikepdf.Array) or len(bbox) != 4
                    or any(isinstance(number, bool) or not isinstance(number, (int, float, Decimal))
                           or not math.isfinite(float(number)) for number in bbox)): return False
        elif role in (pikepdf.Name.TH, pikepdf.Name.TD):
            # The scope and spans of a table cell.
            if attributes.get('/O') != pikepdf.Name.Table or not {'/O'} <= keys <= {'/O', '/Scope', '/RowSpan', '/ColSpan'}: return False
            if '/Scope' in keys and (not isinstance(attributes['/Scope'], pikepdf.Name) or str(attributes['/Scope']) not in _SCOPES): return False
            if any(span in keys and (not _int(attributes[span]) or not 1 <= attributes[span] <= 1000) for span in ('/RowSpan', '/ColSpan')): return False
        elif role == pikepdf.Name.L:
            # How a list is numbered, and whether it carries on an earlier one.
            if attributes.get('/O') != pikepdf.Name.List or not {'/O'} <= keys <= {'/O', '/ListNumbering', '/ContinuedList', '/ContinuedFrom'}: return False
            if '/ListNumbering' in keys and (not isinstance(attributes['/ListNumbering'], pikepdf.Name) or str(attributes['/ListNumbering']) not in _NUMBERINGS): return False
            if '/ContinuedList' in keys and not isinstance(attributes['/ContinuedList'], bool): return False
            if '/ContinuedFrom' in keys:
                earlier = attributes['/ContinuedFrom']
                if not isinstance(earlier, pikepdf.String) or not 0 < len(str(earlier)) <= 128 or any(ord(c) < 32 for c in str(earlier)): return False
        else: return False
        for carrier in [attributes, bbox]:
            carrier_id = graph._id(carrier)
            if carrier_id and scan['incoming'][carrier_id] != 1: return False
    return True


def _is_inert_acroform(pdf, scan):
    acro = pdf.Root.get('/AcroForm')
    if (pdf.is_encrypted or '/Perms' in pdf.Root or not scan['complete'] or scan['active'] or scan['unsafe'] or not _dict(acro)
            or not _inert_layout_attributes(pdf, scan)
            or any(str(key) not in {'/Fields', '/DA', '/DR', '/Q', '/NeedAppearances', '/SigFlags', '/CO'} for key in acro)):
        return False
    fields = acro.get('/Fields')
    if not isinstance(fields, pikepdf.Array) or fields: return False
    if '/NeedAppearances' in acro and acro['/NeedAppearances'] is not False: return False
    if '/SigFlags' in acro and (not _int(acro['/SigFlags']) or acro['/SigFlags'] != 0): return False
    if '/Q' in acro and (not _int(acro['/Q']) or acro['/Q'] not in {0, 1, 2}): return False
    calculation = acro.get('/CO')
    if '/CO' in acro and (not isinstance(calculation, pikepdf.Array) or calculation): return False
    for carrier in [acro, fields, calculation]:
        ident = graph._id(carrier)
        if ident and scan['incoming'][ident] != 1: return False
    fonts = _inert_resources(acro.get('/DR'))
    return fonts is not None and _inert_default_appearance(acro.get('/DA'), fonts)


def is_inert_acroform(pdf):
    '''Recognize only proved empty legacy containers; never strip or edit one.'''
    if '/AcroForm' not in pdf.Root: return False
    return _is_inert_acroform(pdf, _form_signal_scan(pdf))


def has_form_signals(pdf):
    scan = _form_signal_scan(pdf)
    if scan['active'] or not scan['complete']: return True
    return '/AcroForm' in pdf.Root and not _is_inert_acroform(pdf, scan)


def _role(node, rolemap):
    role = node.get('/S'); seen = set()
    if not isinstance(role, pikepdf.Name):
        raise ValueError('A structure role is not a PDF Name')
    while str(role) in rolemap:
        if str(role) in seen or not isinstance(rolemap[str(role)], pikepdf.Name):
            raise ValueError('A structure RoleMap is cyclic or unsupported')
        seen.add(str(role)); role = rolemap[str(role)]
    return str(role)


def _plain_children(node):
    raw = node.get('/K')
    items = list(raw) if isinstance(raw, pikepdf.Array) else [raw]
    return items if items and all(_dict(child) and '/S' in child for child in items) else None


def _plain_label_marks(page, number, cancel=None):
    from .inspection import PAINT
    text = set(); blocked = set(); stack = []
    for index, instruction in enumerate(pikepdf.parse_content_stream(page)):
        if index % 256 == 0: graph._tick(cancel)
        operands, op = instruction.operands, str(instruction.operator)
        if op in {'BMC', 'BDC'}:
            props = operands[1] if op == 'BDC' and len(operands) == 2 else None
            if isinstance(props, pikepdf.Name):
                props = page.resources.get('/Properties', {}).get(str(props))
            mcid = props.get('/MCID') if _dict(props) else None
            stack.append({'key': (number, 'page', mcid) if _int(mcid) and mcid >= 0 else None,
                          'artifact': bool(operands and str(operands[0]) == '/Artifact'),
                          'override': _dict(props) and any(key in props for key in ('/ActualText', '/Alt', '/E', '/Lang'))})
        elif op == 'EMC':
            if stack: stack.pop()
        elif op in PAINT and not any(mark['artifact'] for mark in stack):
            keys = [mark['key'] for mark in stack if mark['key'] is not None]
            if op in {'Tj', 'TJ', "'", '"'}:
                text.update(keys)
                if len(keys) != 1 or any(mark['override'] for mark in stack):
                    blocked.update(keys)
            else:
                blocked.update(keys)
    return text, blocked


def _analyse(pdf, cancel=None):
    graph._tick(cancel)
    if not has_form_signals(pdf):
        return [], {}, None, []
    snapshot = graph._snapshot(pdf, cancel)
    incoming = Counter(ref for value in [snapshot['root'], snapshot['info'], *snapshot['objects'].values()]
                       for ref in graph._references(value))
    limits = []
    def problem(message):
        limits.append(message)
    def protected_encoded(value):
        if not isinstance(value, dict):
            return
        if value.get('t') in {'dict', 'stream'}:
            fields = value['v'] if value['t'] == 'dict' else value['d']
            if (any(key in fields for key in ('/AA', '/JS', '/OpenAction', '/ByteRange'))
                    or fields.get('/S') == {'t': 'name', 'v': '/JavaScript'}
                    or fields.get('/Type') == {'t': 'name', 'v': '/Sig'}
                    or fields.get('/FT') == {'t': 'name', 'v': '/Sig'}):
                problem('Direct or nested action/signature authority requires source review.')
            for child in fields.values():
                protected_encoded(child)
        elif value.get('t') == 'array':
            for child in value['v']:
                protected_encoded(child)
    for encoded in snapshot['objects'].values():
        protected_encoded(encoded)
    def unique_carrier(value, label):
        ident = graph._id(value)
        if ident is not None and incoming[ident] != 1:
            problem(label + ' has another owner or alias.')
    if pdf.is_encrypted or '/Perms' in pdf.Root:
        problem('Encrypted and signed forms require a separately supported derivative workflow.')
    if '/OCProperties' in pdf.Root or _dict(pdf.Root.get('/Names')) and '/JavaScript' in pdf.Root['/Names']:
        problem('Optional-content or JavaScript catalogs require source review.')
    for obj in pdf.objects:
        graph._tick(cancel)
        if not _dict(obj):
            continue
        if '/ByteRange' in obj or obj.get('/Type') == pikepdf.Name.Sig or obj.get('/FT') == pikepdf.Name.Sig:
            problem('Signature fields and signed bytes remain unsupported.')
        if any(key in obj for key in ('/AA', '/JS', '/OpenAction')) or obj.get('/S') == pikepdf.Name.JavaScript:
            problem('Actions and JavaScript require source review before form editing.')
        if '/A' in obj and '/S' not in obj:
            problem('Action-bearing form documents require source review.')
    acro = pdf.Root.get('/AcroForm')
    if not _dict(acro):
        raise ValueError('The canonical AcroForm dictionary is missing or unsupported')
    unique_carrier(acro, 'AcroForm dictionary')
    if '/XFA' in acro or acro.get('/SigFlags', 0):
        problem('XFA, calculation order and signature settings remain unsupported.')
    if '/CO' in acro:
        if not isinstance(acro['/CO'], pikepdf.Array) or acro['/CO']:
            problem('Nonempty or unsupported calculation order remains read-only.')
        else: unique_carrier(acro['/CO'], 'Empty calculation-order array')
    if any(str(key) not in {'/Fields', '/NeedAppearances', '/SigFlags', '/CO', '/DR', '/DA', '/Q', '/XFA'} for key in acro):
        problem('Unknown AcroForm keys require source review.')
    if '/NeedAppearances' in acro and acro['/NeedAppearances'] is not False:
        problem('Forms needing regenerated appearances remain unsupported.')
    fields = acro.get('/Fields')
    if not isinstance(fields, pikepdf.Array) or not fields:
        raise ValueError('The canonical field tree is empty or unsupported')
    unique_carrier(fields, 'Root field array')
    page_ids = {graph._id(page.obj): n for n, page in enumerate(pdf.pages, 1)}
    if len(pdf.pages) > LIMITS['pages']:
        problem('The form exceeds the 50-page authoring bound.')
    field_nodes = {}; terminals = []; widget_fields = {}; field_expected = Counter(); seen_fields = set()
    def field_walk(node, parent, path, names, inherited_type=None, inherited_flags=0, depth=0):
        graph._tick(cancel)
        ident = graph._id(node)
        if depth > 50 or len(seen_fields) >= 1000 or not _dict(node) or ident is None or ident in seen_fields:
            raise ValueError('Field nodes are direct, repeated, cyclic or exceed the bounded field tree')
        seen_fields.add(ident); field_nodes[ident] = node; field_expected[ident] += 1
        field_keys = {'/FT', '/Parent', '/Kids', '/T', '/TU', '/TM', '/Ff', '/V', '/DV', '/AA', '/DA', '/Q', '/DS', '/RV', '/MaxLen', '/Opt', '/I', '/TI'}
        widget_keys = {'/Type', '/Subtype', '/Rect', '/Contents', '/P', '/NM', '/M', '/F', '/AP', '/AS', '/Border', '/C', '/StructParent', '/MK', '/BS', '/H', '/A', '/AA', '/OC'}
        if any(str(key) not in field_keys | (widget_keys if node.get('/Subtype') == pikepdf.Name.Widget else set()) for key in node):
            problem('Unknown field dictionary keys require source review.')
        if parent is None:
            if '/Parent' in node: problem('A root field has an unexpected Parent.')
        else:
            if graph._id(node.get('/Parent')) != graph._id(parent): problem('A field Parent does not match its canonical tree.')
            field_expected[graph._id(parent)] += 1
        raw_name = node.get('/T'); part = _text(raw_name)
        if any(key in node and not isinstance(node[key], pikepdf.String) for key in ('/TU', '/TM', '/DA')):
            problem('Known field text properties have an unsupported representation.')
        if raw_name is not None and (part is None or not part or '.' in part or any(ord(c) < 32 for c in part)):
            problem('A partial field name is malformed or ambiguous.')
        names = names + ([part] if part else [])
        ft = node.get('/FT', inherited_type); flags = node.get('/Ff', inherited_flags)
        if ft is not None and not isinstance(ft, pikepdf.Name) or not _int(flags) or not 0 <= flags < 2**32:
            problem('Field type or inherited flags cannot be proved.'); flags = 0
        kids = node.get('/Kids'); merged = node.get('/Subtype') == pikepdf.Name.Widget
        if kids is not None:
            if not isinstance(kids, pikepdf.Array) or not kids:
                raise ValueError('A field Kids carrier is empty or unsupported')
            unique_carrier(kids, 'Field Kids array')
        items = list(kids) if isinstance(kids, pikepdf.Array) else []
        widget_kids = bool(items) and all(_dict(child) and child.get('/Subtype') == pikepdf.Name.Widget
            and '/T' not in child and '/FT' not in child and '/Kids' not in child for child in items)
        if items and not widget_kids:
            if merged or any(not _dict(child) or child.get('/Subtype') == pikepdf.Name.Widget
                    and '/T' not in child and '/Kids' not in child for child in items):
                raise ValueError('Mixed field/widget hierarchies require source repair')
            for index, child in enumerate(items): field_walk(child, node, path + '/Kids/' + str(index), names, ft, flags, depth + 1)
            return
        if not names or part is None:
            problem('Every terminal field needs an explicit partial internal name.')
        if str(ft) not in {'/Tx', '/Ch', '/Btn'}:
            problem('Only ordinary text, choice and simple checkbox fields are supported.')
        if str(ft) == '/Btn' and flags & ((1 << 15) | (1 << 16) | (1 << 25)):
            problem('Radio and pushbutton fields require a separate supported naming workflow.')
        if str(ft) == '/Tx' and (flags & ((1 << 13) | (1 << 20) | (1 << 24) | (1 << 25)) or '/RV' in node):
            problem('Password, file-selection and rich-text fields remain unsupported.')
        tooltip = _text(node.get('/TU'))
        if '/TU' in node and tooltip is None:
            problem('A terminal tooltip is not an ordinary PDF string.')
        widgets = [node] if merged and not items else items if widget_kids and not merged else []
        if not widgets: problem('A terminal field lacks canonical widget ownership.')
        if str(ft) == '/Btn' and len(widgets) != 1:
            problem('Mirrored or grouped checkbox widgets require separate qualification.')
        record = {'field': ident, 'node': node, 'path': path, 'name': '.'.join(names), 'partial_name': part,
                  'field_type': str(ft).lstrip('/'), 'flags': flags, 'tooltip': tooltip, 'widgets': []}
        terminals.append(record)
        for widget in widgets:
            wid = graph._id(widget)
            if not _dict(widget) or wid is None or wid in widget_fields:
                raise ValueError('Widgets must be uniquely owned indirect dictionaries')
            widget_fields[wid] = record
            if widget is not node:
                if graph._id(widget.get('/Parent')) != ident: problem('A widget Parent does not match its terminal field.')
                field_expected[ident] += 1; field_expected[wid] += 1
    for index, node in enumerate(fields):
        field_walk(node, None, 'Fields/' + str(index), [])
    if len(terminals) > LIMITS['fields'] or len(widget_fields) > LIMITS['widgets']:
        problem('The form exceeds its bounded field/widget count.')
    if len({field['name'] for field in terminals}) != len(terminals):
        problem('Fully qualified terminal field names are not unique.')
    # Page annotation ownership is authoritative; fields that are merely present
    # in an object table cannot become editable controls.
    annotations = {}; widget_pages = {}; annotations_by_page = {}
    for number, page in enumerate(pdf.pages, 1):
        raw = page.obj.get('/Annots', pikepdf.Array())
        if not isinstance(raw, pikepdf.Array):
            raise ValueError('A page annotation array is malformed')
        unique_carrier(raw, 'Page annotation array')
        annotations_by_page[number] = []
        for index, annotation in enumerate(raw):
            ident = graph._id(annotation)
            if not _dict(annotation) or ident is None or ident in annotations:
                raise ValueError('Annotations are direct, repeated or shared between pages')
            annotations[ident] = {'node': annotation, 'page': number, 'index': index}
            annotations_by_page[number].append(ident)
            if '/P' in annotation and graph._id(annotation['/P']) != graph._id(page.obj):
                problem('An annotation page pointer disagrees with its page array.')
            if annotation.get('/Subtype') == pikepdf.Name.Widget:
                widget_pages[ident] = number
                if ident not in widget_fields: problem('An orphan page widget is absent from the canonical field tree.')
            elif annotation.get('/Subtype') != pikepdf.Name.Link:
                problem('Only Widget and ordinary locally targeted Link annotations are supported.')
            elif any(str(key) not in {'/Type', '/Subtype', '/Rect', '/Contents', '/P', '/NM', '/M', '/F', '/AP', '/AS', '/Border', '/C', '/StructParent', '/Dest', '/H', '/BS', '/A', '/AA', '/QuadPoints'} for key in annotation):
                problem('Unknown Link annotation keys require source review.')
    if set(widget_fields) != set(widget_pages):
        problem('Canonical field widgets and page widgets do not match exactly.')
    if any(_dict(obj) and obj.get('/Subtype') == pikepdf.Name.Widget and graph._id(obj) not in widget_fields for obj in pdf.objects):
        problem('An orphan widget exists outside the canonical field and page ownership.')
    # Build the rooted structure independently of the older editing capability
    # analyser, whose AcroForm refusal remains unchanged for older profiles.
    root = pdf.Root.get('/StructTreeRoot')
    if not _dict(root) or graph._id(root) is None:
        raise ValueError('A form requires an existing indirect structure root')
    rolemap = root.get('/RoleMap', pikepdf.Dictionary())
    if not _dict(rolemap): raise ValueError('The structure RoleMap is unsupported')
    nodes = {}; expected_struct = Counter(); objrs = {}; object_order = []; form_ids = []
    expected_struct[graph._id(root)] += 1
    def content(value, owner, page, path, depth):
        if depth > 200: raise ValueError('The structure exceeds the navigation proof bound')
        if isinstance(value, pikepdf.Array):
            unique_carrier(value, 'Structure child/content array')
            for index, child in enumerate(value): content(child, owner, page, path + '/' + str(index), depth + 1)
        elif _dict(value) and '/S' in value:
            struct(value, owner, page, path, depth + 1)
        elif _dict(value) and value.get('/Type') == pikepdf.Name.OBJR:
            unique_carrier(value, 'Object-reference dictionary')
            target = graph._id(value.get('/Obj'))
            if target is None or owner is None:
                raise ValueError('An OBJR lacks a unique structure owner or annotation target')
            actual_page = page_ids.get(graph._id(value.get('/Pg')), page) if '/Pg' in value else page
            objrs.setdefault(target, []).append((owner, actual_page, value)); object_order.append(target)
        elif _int(value) or _dict(value) and (value.get('/Type') == pikepdf.Name.MCR or '/MCID' in value):
            if _dict(value): unique_carrier(value, 'Marked-content reference dictionary')
        elif value is not None:
            raise ValueError('A structure content child is unsupported')
    def struct(node, parent, page, path, depth):
        graph._tick(cancel); ident = graph._id(node)
        if ident is None or ident in nodes or len(nodes) >= 10000:
            raise ValueError('Structure elements are direct, repeated, cyclic or exceed the proof bound')
        expected_parent = graph._id(root) if parent is None else parent
        if graph._id(node.get('/P')) != expected_parent:
            problem('A structure parent does not match its rooted occurrence.')
        if '/Type' in node and node['/Type'] != pikepdf.Name.StructElem:
            problem('A structure dictionary has an unsupported object type.')
        expected_struct[ident] += 1; expected_struct[expected_parent] += 1
        role = _role(node, rolemap)
        here = page_ids.get(graph._id(node.get('/Pg')), page) if '/Pg' in node else page
        nodes[ident] = {'node': node, 'parent': expected_parent, 'page': here, 'path': path, 'role': role}
        if role == '/Form': form_ids.append(ident)
        content(node.get('/K'), ident, here, path + '/K', depth + 1)
    content(root.get('/K'), None, None, 'root/K', 0)
    from .inspection import _structure, _page_content
    structure, references, object_references, _, _ = _structure(pdf, page_ids)
    if structure['errors']: problem('The existing logical structure has incomplete or ambiguous references.')
    parent_tree, chains = graph._parent_arrays(root)
    # Attribute, ParentTree and mutable carriers must have one canonical owner.
    for chain in chains.values():
        for carrier in chain[:-1]: unique_carrier(carrier, 'ParentTree carrier')
        if isinstance(chain[-1], pikepdf.Array): unique_carrier(chain[-1], 'ParentTree marked-content array')
    # Respect existing IDTree aliases, but no arbitrary references to mutable
    # structure objects. A complete index is required when IDs are present.
    ids = {}; index_counts = Counter()
    for ident, rec in nodes.items():
        if '/ID' in rec['node']:
            if not isinstance(rec['node']['/ID'], pikepdf.String): problem('A structure ID is not an ordinary string.')
            else: ids.setdefault(bytes(rec['node']['/ID']), []).append(ident)
    from .table_edits import _idtree
    index, index_limits = _idtree(root, ids, incoming)
    if ids and index['root'] is None: problem('Structure IDs need their complete canonical IDTree.')
    limits.extend(index_limits)
    for ident in index['entries'].values(): index_counts[ident] += 1
    # Every ParentTree reference has to be accounted for by an actual page mark
    # or annotation. Unexpected extra references are aliases, not authority.
    for ref in structure['references']:
        expected_struct[ref['element']] += 1
    for entries in objrs.values():
        for owner, _, _ in entries: expected_struct[owner] += 1
    for ident in nodes:
        if incoming[ident] != expected_struct[ident] + index_counts[ident]:
            problem('A structure element has an additional owner, alias or ParentTree reference.')
    if incoming[graph._id(root)] != expected_struct[graph._id(root)]:
        problem('The structure root has an additional owner or alias.')
    rooted_ids = set(nodes)
    def unrooted(encoded, ident=None):
        if not isinstance(encoded, dict): return False
        if encoded.get('t') == 'dict':
            values = encoded['v']
            if (values.get('/Type') == {'t': 'name', 'v': '/StructElem'} or '/S' in values and '/P' in values) and ident not in rooted_ids:
                return True
            return any(unrooted(value) for value in values.values())
        if encoded.get('t') == 'array': return any(unrooted(value) for value in encoded['v'])
        return False
    if any(unrooted(value, ident) for ident, value in snapshot['objects'].items()):
        problem('An unrooted reachable structure element prevents a complete form proof.')
    seen_parent_keys = Counter(page.obj.get('/StructParents') for page in pdf.pages if _int(page.obj.get('/StructParents')))
    seen_parent_keys.update(annotation['node'].get('/StructParent') for annotation in annotations.values()
                            if _int(annotation['node'].get('/StructParent')))
    annotation_owners = {}; annotation_order = {number: [] for number in annotations_by_page}
    def local_target(annotation):
        dest = annotation.get('/Dest')
        if not isinstance(dest, pikepdf.Array) or len(dest) < 2 or graph._id(dest[0]) not in page_ids or not isinstance(dest[1], pikepdf.Name):
            problem('A Link needs a direct ordinary local page destination.'); return None
        counts = {'/XYZ': 5, '/Fit': 2, '/FitH': 3, '/FitV': 3, '/FitR': 6, '/FitB': 2, '/FitBH': 3, '/FitBV': 3}
        if counts.get(str(dest[1])) != len(dest) or any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float, Decimal)) or not math.isfinite(float(value))) for value in list(dest)[2:]):
            problem('A local Link destination has an unsupported fit or coordinate representation.')
        return page_ids[graph._id(dest[0])]
    for aid, annotation in annotations.items():
        node = annotation['node']; entries = objrs.get(aid, [])
        pkey = node.get('/StructParent')
        if len(entries) != 1 or not _int(pkey) or pkey < 0 or seen_parent_keys[pkey] != 1:
            problem('Each page annotation needs one unique OBJR and StructParent key.'); continue
        owner, page, _ = entries[0]
        if page != annotation['page'] or graph._id(parent_tree.get(pkey)) != owner:
            problem('Annotation OBJR page and ParentTree owner do not match.')
        if node.get('/Subtype') == pikepdf.Name.Widget and nodes[owner]['role'] != '/Form':
            problem('Each widget must belong to a tagged Form element.')
        if node.get('/Subtype') == pikepdf.Name.Link and nodes[owner]['role'] != '/Link':
            problem('Each Link must belong to a tagged Link element.')
        if sum(len(values) for target, values in objrs.items() if any(entry[0] == owner for entry in values)) != 1:
            problem('Every interactive structure atom must own exactly one annotation.')
        annotation_owners[aid] = owner
        annotation['target_page'] = local_target(node) if node.get('/Subtype') == pikepdf.Name.Link else None
        field_expected[aid] += 1 + len(entries)
    if set(objrs) != set(annotations):
        problem('Tagged OBJRs and page annotations do not match exactly.')
    for aid in object_order:
        if aid in annotations:
            annotation_order[annotations[aid]['page']].append(aid)
    for ident in field_nodes.keys() | widget_fields.keys():
        if incoming[ident] != field_expected[ident]:
            problem('A field or widget has an additional inbound alias or ambiguous owner.')
    for ident in set(annotations) - set(widget_fields):
        if incoming[ident] != 2:
            problem('A Link annotation has an additional inbound alias.')
    def range_tree(node, depth=0):
        nums = node.get('/Nums'); kids = node.get('/Kids'); keys = []
        if nums is not None:
            keys = list(nums)[::2]
        elif isinstance(kids, pikepdf.Array):
            for child in kids: keys.extend(range_tree(child, depth + 1))
        if keys != sorted(keys) or len(set(keys)) != len(keys):
            problem('ParentTree key ranges are not strictly ordered and disjoint.')
        bound = node.get('/Limits')
        if depth and (bound is None or not keys):
            problem('A non-root ParentTree node lacks a nonempty key range.')
        if bound is not None and (not isinstance(bound, pikepdf.Array) or len(bound) != 2
                or any(not _int(x) for x in bound) or not keys or list(bound) != [keys[0], keys[-1]]):
            problem('ParentTree Limits do not match the exact source key range.')
        return keys
    range_tree(root['/ParentTree'])
    next_key = root.get('/ParentTreeNextKey')
    if next_key is not None and (not _int(next_key) or parent_tree and next_key <= max(parent_tree)):
        problem('ParentTreeNextKey does not reserve the existing source keys.')
    page_content = {}; label_marks = {}
    context_fields = []; widget_contexts = {}; form_owner_ids = set(annotation_owners.get(w) for w in widget_fields)
    if set(form_ids) != form_owner_ids:
        problem('Tagged Form elements and canonical widgets are not one-to-one.')
    def inherited(node, key):
        visited = set()
        while _dict(node):
            ident = graph._id(node)
            if ident in visited: return None
            visited.add(ident)
            if key in node: return node[key]
            node = node.get('/Parent')
        return None
    for field in terminals:
        children = []
        for wid, owner_field in widget_fields.items():
            if owner_field is not field: continue
            annotation = annotations.get(wid); owner = annotation_owners.get(wid)
            if annotation is None or owner not in nodes: continue
            widget = annotation['node']; rec = nodes[owner]; number = annotation['page']
            widget_keys = {'/Type', '/Subtype', '/Rect', '/Contents', '/P', '/NM', '/M', '/F', '/AP', '/AS', '/Border', '/C', '/StructParent', '/MK', '/BS', '/H', '/A', '/AA', '/OC', '/Parent'}
            if wid != field['field'] and any(str(key) not in widget_keys for key in widget):
                problem('Unknown widget dictionary keys require source review.')
            if '/OC' in widget: problem('Optional-content widgets remain unsupported.')
            flags = widget.get('/F', 0)
            if not _int(flags) or not 0 <= flags < 2**32 or flags & (1 | 2 | 32):
                problem('Invisible, hidden or unsupported widget flags require source review.')
            rect = widget.get('/Rect')
            if (not isinstance(rect, pikepdf.Array) or len(rect) != 4
                    or any(isinstance(x, bool) or not isinstance(x, (int, float, Decimal)) or not math.isfinite(float(x)) for x in rect)
                    or float(rect[2]) <= float(rect[0]) or float(rect[3]) <= float(rect[1])):
                problem('A widget rectangle is malformed.'); rect = []
            ap = widget.get('/AP'); normal = ap.get('/N') if _dict(ap) else None
            if not _dict(ap) or any(str(key) not in {'/N', '/R', '/D'} for key in ap):
                problem('Widget appearances must be ordinary supported appearance dictionaries.')
            for kind, appearance in ap.items() if _dict(ap) else []:
                values = list(appearance.values()) if _dict(appearance) else [appearance]
                if not values or any(not isinstance(value, pikepdf.Stream) or value.get('/Subtype') != pikepdf.Name.Form for value in values):
                    problem('Widget appearances must retain ordinary Form appearance streams.')
            value = inherited(field['node'], '/V'); default = inherited(field['node'], '/DV')
            if field['field_type'] == 'Btn':
                states = list(normal.keys()) if _dict(normal) else []
                state = widget.get('/AS'); effective = value if value is not None else pikepdf.Name.Off
                if (not _dict(normal) or '/Off' not in normal or len(states) != 2 or not isinstance(state, pikepdf.Name)
                        or str(state) not in normal or not isinstance(effective, pikepdf.Name) or state != effective
                        or default is not None and (not isinstance(default, pikepdf.Name) or str(default) not in normal)):
                    problem('A simple checkbox needs exact Off/on appearances and matching value/state.')
            else:
                if not isinstance(normal, pikepdf.Stream): problem('Text and choice widgets need a retained normal appearance stream.')
                if field['field_type'] == 'Tx' and any(x is not None and not isinstance(x, pikepdf.String) for x in [value, default]):
                    problem('Text values/defaults must retain ordinary text strings.')
                if field['field_type'] == 'Ch':
                    opts = field['node'].get('/Opt')
                    valid_options = isinstance(opts, pikepdf.Array) and bool(opts) and all(isinstance(x, pikepdf.String)
                            or isinstance(x, pikepdf.Array) and len(x) == 2 and all(isinstance(y, pikepdf.String) for y in x) for x in opts)
                    if not valid_options:
                        problem('Choice fields need ordinary retained option strings or export/display pairs.')
                    else:
                        exports = [bytes(x[0] if isinstance(x, pikepdf.Array) else x) for x in opts]
                        if len(exports) != len(set(exports)): problem('Ambiguous choice export values require source review.')
                        selected = []
                        for position, current in enumerate([value, default]):
                            selected_values = list(current) if isinstance(current, pikepdf.Array) else [] if current is None else [current]
                            if (isinstance(current, pikepdf.Array) and not field['flags'] & (1 << 21)
                                    or any(not isinstance(x, pikepdf.String) or bytes(x) not in exports for x in selected_values)
                                    or len({bytes(x) for x in selected_values if isinstance(x, pikepdf.String)}) != len(selected_values)):
                                problem('Choice values/defaults do not have a unique supported export selection.')
                            if position == 0: selected = [bytes(x) for x in selected_values if isinstance(x, pikepdf.String)]
                        indices = field['node'].get('/I')
                        if indices is not None:
                            if (not isinstance(indices, pikepdf.Array) or any(not _int(x) or not 0 <= x < len(exports) for x in indices)
                                    or list(indices) != sorted(set(indices))):
                                problem('Choice selection indices are malformed or ambiguous.')
                            elif [exports[index] for index in indices] != selected:
                                problem('Choice selection indices disagree with the retained field value.')
            ancestry = owner; visited = set(); scope = set()
            while ancestry in nodes and ancestry not in visited:
                visited.add(ancestry); ancestor = nodes[ancestry]['node']
                if any(key in ancestor for key in ('/ActualText', '/Ref', '/AF', '/C', '/R', '/E')):
                    problem('Protected or class-based form ancestry requires source review.')
                if ancestry != owner and '/Alt' in ancestor:
                    problem('An ancestor alternative can hide the descendant form names or sequence.')
                if ancestry == owner and '/A' in ancestor:
                    problem('Existing Form-owner attributes require source review before name editing.')
                ancestry = nodes[ancestry]['parent']
            for ident, candidate in nodes.items():
                if ident == owner or candidate['path'].startswith(rec['path'] + '/K'):
                    scope.add(ident)
                    if ident != owner:
                        if candidate['role'] not in {'/P', '/Span'}:
                            problem('Nested interactive or non-text Form label subtrees require source repair.')
                        if any(key in candidate['node'] for key in ('/ActualText', '/Alt', '/E', '/Ref', '/AF', '/C', '/R')):
                            problem('Protected replacement/class attributes cover a Form label descendant.')
            if any(target != wid and any(entry[0] in scope for entry in entries) for target, entries in objrs.items()):
                problem('A Form subtree contains another interactive annotation; its sequence is not an isolated field atom.')
            refs = [ref for ref in structure['references'] if ref['element'] in scope]
            for ref in refs:
                if ref['page'] != number or ref['stream'] != 'page':
                    problem('Form labels need proven same-page direct marked content.'); continue
                if number not in page_content:
                    page_content[number] = _page_content(pdf.pages[number - 1], number, references, parent_tree, {})[:3]
                content_info, definitions, painted = page_content[number]; key = (number, 'page', ref['mcid'])
                if number not in label_marks:
                    label_marks[number] = _plain_label_marks(pdf.pages[number - 1], number, cancel)
                text_marks, blocked_marks = label_marks[number]
                if key not in text_marks or key in blocked_marks:
                    problem('Form-owned label content must be proven plain direct-page text without replacement or nontext painting.')

                if (content_info['errors'] or content_info['duplicate_mcids'] or definitions[key] != 1 or painted[key] < 1
                        or references.get(key) != [ref['element']] or any(f['stream'] == 'page' and f['mcid'] == ref['mcid'] for f in content_info['parent_tree_failures'])):
                    problem('A Form label does not have unique painted marked-content ownership.')
            alternative = _text(rec['node'].get('/Alt'))
            if '/Alt' in rec['node'] and alternative is None: problem('A Form alternative is not an ordinary PDF string.')
            entry = {'widget': wid, 'page': number, 'index': annotation['index'], 'element': owner,
                     'structure_path': rec['path'], 'alternative': alternative, 'rect': [float(x) for x in rect],
                     'widget_flags': flags, 'state_sha256': graph._digest({'field': snapshot['objects'][field['field']], 'widget': snapshot['objects'][wid]})}
            children.append(entry); widget_contexts[wid] = entry
        context_fields.append({key: field[key] for key in ('field', 'path', 'name', 'partial_name', 'field_type', 'flags', 'tooltip')} | {'widgets': children})
    form_pages = sorted(set(widget_pages.values())); context_pages = []
    for number in form_pages:
        page = pdf.pages[number - 1]; tabs = page.obj.get('/Tabs')
        if tabs is not None and not isinstance(tabs, pikepdf.Name): problem('Page tab order is not an ordinary PDF Name.')
        full = []
        for aid in annotation_order[number]:
            annotation = annotations[aid]; owner = annotation_owners.get(aid)
            if owner is None: continue
            widget = aid in widget_fields; node = annotation['node']
            label = widget_fields[aid]['tooltip'] if widget else _text(nodes[owner]['node'].get('/Alt')) or _text(node.get('/Contents'))
            full.append({'annotation': aid, 'subtype': str(node.get('/Subtype')).lstrip('/'), 'element': owner,
                         'widget': widget, 'source_label': label, 'target_page': annotation.get('target_page')})
        if set(annotation_order[number]) != set(annotations_by_page[number]) or len(annotation_order[number]) != len(annotations_by_page[number]):
            problem('The complete page annotation/tag sequence cannot be proved.')
        context_pages.append({'page': number, 'tabs': str(tabs).lstrip('/') if isinstance(tabs, pikepdf.Name) else None,
                              'widgets': [aid for aid in annotations_by_page[number] if aid in widget_fields],
                              'tag_order': [aid for aid in annotation_order[number] if aid in widget_fields], 'annotation_order': full})
    orders = []; group_nodes = {}; field_names = {widget['element']: field['name'] for field in context_fields for widget in field['widgets']}
    for ident, rec in nodes.items():
        children = _plain_children(rec['node']); ids_in_order = [graph._id(child) for child in children or []]
        if (rec['role'] not in _NEUTRAL or not children or len(children) < 2 or len(children) > LIMITS['children']
                or any(child not in form_owner_ids for child in ids_in_order)):
            continue
        pages_in_order = {widget['page'] for widget in widget_contexts.values() if widget['element'] in ids_in_order}
        if len(pages_in_order) != 1: continue
        if any(key in rec['node'] for key in ('/ActualText', '/Alt', '/E', '/Ref', '/AF', '/C', '/R', '/A')): continue
        number = next(iter(pages_in_order)); by_owner = {widget['element']: widget for widget in widget_contexts.values()}
        orders.append({'parent': ident, 'page': number, 'structure_path': rec['path'], 'children': ids_in_order,
                       'labels': [{'element': child, 'widget': by_owner[child]['widget'], 'field_name': field_names[child], 'page': number} for child in ids_in_order]})
        group_nodes[ident] = rec['node']
    if len(orders) > LIMITS['orders']: problem('The form exceeds the navigation-group count bound.')
    context = {'policy': POLICY, 'fields': context_fields, 'pages': context_pages, 'orders': orders, 'limits': dict(LIMITS)}
    current = canonical_value(source_value(context))
    if len(current) > LIMITS['payload_chars']: problem('The complete form plan exceeds the supported payload bound.')
    display = {'structural_eligible': not limits, 'structural_limitations': sorted(set(limits)), 'allowed_values': [],
               'context_text': '', 'context_text_source': 'Existing fields, widgets and tag order; no label or sequence is guessed.', 'form_context': context}
    ident = 'forms:controls:document'
    row = {'id': ident, 'kind': 'form-controls', 'element': graph._id(acro), 'page': None,
           'structure_path': 'catalog/AcroForm', 'references': [{'page': widget['page'], 'stream': 'annotation', 'object': widget['widget']}
               for field in context_fields for widget in field['widgets']], 'current': current, 'value': current, 'status': 'pending', **display,
           'context_sha256': graph._digest({'snapshot': snapshot, 'display': display})}
    target = {'fields': {field['field']: field['node'] for field in terminals},
              'widgets': {wid: {'node': annotations[wid]['node'], 'owner': nodes[annotation_owners[wid]]['node']} for wid in widget_contexts},
              'pages': {number: pdf.pages[number - 1].obj for number in form_pages}, 'groups': group_nodes,
              'scope': {ident for wid in widget_contexts for ident, rec in nodes.items() if ident == widget_contexts[wid]['element']
                        or rec['path'].startswith(nodes[widget_contexts[wid]['element']]['path'] + '/K')}}
    return [row], {ident: target}, snapshot, limits


def _unavailable(reason):
    context = {'policy': POLICY, 'fields': [], 'pages': [], 'orders': [], 'limits': dict(LIMITS)}
    current = canonical_value(source_value(context))
    return {'id': 'forms:controls:document', 'kind': 'form-controls', 'element': None, 'page': None,
            'structure_path': 'catalog/AcroForm', 'references': [], 'current': current, 'value': current, 'status': 'pending',
            'structural_eligible': False, 'structural_limitations': [reason], 'allowed_values': [], 'context_text': '',
            'context_text_source': 'No complete canonical form proof.', 'form_context': context,
            'context_sha256': graph._digest({'context': context, 'reason': reason})}


def inventory(pdf, *, cancel=None, text_contexts=None):
    from .sidecar import DecisionError
    try:
        rows, targets, _, _ = _analyse(pdf, cancel)
        return rows, targets, []
    except InterruptedError:
        raise
    except (DecisionError, ValueError, RuntimeError, TypeError, KeyError, RecursionError) as exc:
        return [_unavailable('The bounded form proof is unavailable: ' + str(exc)[:400])], {}, []


def preflight(pdf, *, cancel=None):
    signals = has_form_signals(pdf)
    if not signals:
        return {'policy': POLICY, 'signals': False, 'supported': False, 'limitations': [], 'field_count': 0, 'widget_count': 0}
    rows, _, _ = inventory(pdf, cancel=cancel)
    row = rows[0]
    return {'policy': POLICY, 'signals': True, 'supported': row['structural_eligible'],
            'limitations': row['structural_limitations'], 'field_count': len(row['form_context']['fields']),
            'widget_count': sum(len(field['widgets']) for field in row['form_context']['fields'])}


def _prepare(pdf, items, *, cancel=None, other_changes=()):
    rows, targets, _, _ = _analyse(pdf, cancel)
    fresh = {row['id']: row for row in rows}; plans = []; seen = set()
    fields = ('kind', 'current', 'element', 'page', 'structure_path', 'references', 'context_sha256',
              'structural_eligible', 'structural_limitations', 'allowed_values', 'context_text', 'context_text_source', 'form_context')
    for item in items:
        graph._tick(cancel); row = fresh.get(item.get('id'))
        if row is None or item['id'] in seen or any(item.get(key) != row.get(key) for key in fields):
            _fail('Form source, capability or canonical occurrence changed')
        seen.add(item['id']); value = validate_value(item)
        if item['value'] == item['current']:
            continue
        target = targets[item['id']]
        for other in other_changes:
            if other.get('value') == other.get('current') or other.get('kind') in KINDS:
                continue
            if other.get('kind') in {'title', 'language'}:
                continue
            if other.get('kind') == 'figure-description' and other.get('element') not in target['scope']:
                continue
            _fail('Another accepted choice conflicts with this whole-form plan')
        plans.append({'id': item['id'], 'value': value, 'source': json.loads(item['current']), 'context': row['form_context'], **target})
    return plans


def prepare_changes(pdf, items, *, cancel=None, text_contexts=None, other_changes=()):
    return _prepare(pdf, items, cancel=cancel, other_changes=other_changes)


def prepare_expected(pdf, items, *, cancel=None, text_contexts=None, other_changes=()):
    return _prepare(pdf, items, cancel=cancel, other_changes=other_changes)


def _changes(plan):
    changes = []
    for field, old in zip(plan['value']['fields'], plan['source']['fields']):
        if field['tooltip'] != old['tooltip']:
            changes.append((field['field'], '/TU', field['tooltip'], 'text'))
        for widget, original in zip(field['widgets'], old['widgets']):
            if widget['alternative'] != original['alternative']:
                changes.append((graph._id(plan['widgets'][widget['widget']]['owner']), '/Alt', widget['alternative'], 'text'))
    for page, old in zip(plan['value']['pages'], plan['source']['pages']):
        if page['tabs'] != old['tabs']:
            changes.append((graph._id(plan['pages'][page['page']]), '/Tabs', page['tabs'], 'name'))
    for order, old in zip(plan['value']['orders'], plan['source']['orders']):
        if order['children'] != old['children']:
            changes.append((order['parent'], '/K', order['children'], 'children'))
    return changes


def expected_snapshot(snapshot, plans, *, cancel=None):
    expected = copy.deepcopy(snapshot)
    for plan in plans:
        graph._tick(cancel)
        for ident, key, value, kind in _changes(plan):
            fields = expected['objects'][ident]['v']
            if value is None:
                fields.pop(key, None)
            elif kind == 'text':
                fields[key] = {'t': 'string', 'v': bytes(pikepdf.String(value)).hex()}
            elif kind == 'name':
                fields[key] = {'t': 'name', 'v': '/' + value}
            else:
                original = graph._resolve_encoded(expected, fields[key])
                if original.get('t') != 'array':
                    _fail('The independently encoded form order carrier changed')
                original['v'] = [{'ref': child} for child in value]
    return expected


def apply_prepared(pdf, plans, *, cancel=None):
    before = graph._snapshot(pdf, cancel)
    expected = expected_snapshot(before, plans, cancel=cancel)
    targets = {}
    for plan in plans:
        targets.update(plan['fields']); targets.update(plan['groups'])
        targets.update({graph._id(page): page for page in plan['pages'].values()})
        targets.update({graph._id(widget['owner']): widget['owner'] for widget in plan['widgets'].values()})
    changed = []
    for plan in plans:
        graph._tick(cancel)
        edits = _changes(plan)
        for ident, key, value, kind in edits:
            target = targets[ident]
            if value is None:
                if key in target: del target[key]
            elif kind == 'text':
                target[key] = pikepdf.String(value)
            elif kind == 'name':
                target[key] = pikepdf.Name('/' + value)
            else:
                children = {graph._id(child): child for child in target[key]}
                for index, child in enumerate(value): target[key][index] = children[child]
        if edits: changed.append(plan['id'])
    if canonical_snapshot(graph._snapshot(pdf, cancel)) != canonical_snapshot(expected):
        _fail('The form writer changed fields outside the explicit names and tagged navigation')
    return changed
