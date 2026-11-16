"""Read-only inventory of characters whose Unicode meaning is implausible or unverifiable.

For every font that shows text, this walks the page programs and records which
character codes are used and what text a reader would extract for them. A code
is reported when its text is a private-use, replacement, control or unassigned
character, when it has no mapping at all, when a mapping disagrees with the
font's own glyph name or with a declared ActualText, or when a word mixes
look-alike letters from different scripts. Unembedded fonts are listed with
guidance only.

Nothing here proves that a mapping is *right*: a mapping that passes every
screen can still name the wrong character. The result is an advisory screen,
separate from strict validation and from human review, and it never changes
the PDF.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import re
import unicodedata
from pathlib import Path

import pikepdf

from . import tounicode
from .process import cancelled

POLICY = 'bounded-character-meaning-1'
LIMITS = {'input_bytes': 100 * 1024 * 1024, 'pages': 500, 'operations_per_page': 200000,
          'operations': 3000000, 'form_depth': 12, 'forms_per_page': 2000, 'fonts': 300,
          'records': 400, 'codes_per_record': 40, 'pages_per_record': 20, 'sample_characters': 60,
          'text_characters_per_page': 20000, 'mixed_script_records': 50}
FIX = ('Compare each reported character with the visible page. If the visible character is real '
       'but its text is wrong, the reliable repair is in the authoring source: use a font with '
       'proper Unicode mapping, re-export a tagged PDF with fonts embedded, and process that copy. '
       'For an embedded font whose existing ToUnicode map names the wrong character, a reviewer can '
       'supply the intended text per code and create a separate corrected copy '
       '(docs/UNICODE-AND-FONT-REPAIR.md). For OCR text, correct the word in the OCR text editor. '
       'A rerun of OCR or an extraction that looks plausible does not prove the characters are right.')
LIMITATIONS = [
    'Reads page content and nested Form XObjects only. Annotation appearances, patterns and Type 3 glyph programs are not scanned.',
    'A mapping with no flag can still name the wrong character. Only a person comparing the visible glyph can establish meaning.',
    'Glyph-name and ActualText comparisons use compatibility-normalised text and skip names with no known Unicode value.',
    'Fonts that use a named two-byte CMap other than Identity-H/V cannot be decoded here and are listed as uncertain.',
    'The mixed-script word screen covers only Latin letters mixed with look-alike Cyrillic or Greek letters, in extracted page text.',
    'The parsed page and font data come from this program\'s own reader, so a defect that only appears in another reader is not modelled.',
]
_STANDARD_14 = {'Courier', 'Courier-Bold', 'Courier-Oblique', 'Courier-BoldOblique', 'Helvetica',
                'Helvetica-Bold', 'Helvetica-Oblique', 'Helvetica-BoldOblique', 'Times-Roman',
                'Times-Bold', 'Times-Italic', 'Times-BoldItalic', 'Symbol', 'ZapfDingbats'}
_SYMBOLIC = {'Symbol', 'ZapfDingbats'}
# Letters that look like a Latin letter but belong to another script (code points, never literal letters).
_CYRILLIC_LOOK_ALIKES = (0x0410, 0x0412, 0x0415, 0x041A, 0x041C, 0x041D, 0x041E, 0x0420, 0x0421, 0x0422, 0x0423, 0x0425, 0x0430, 0x0435, 0x043E, 0x0440, 0x0441, 0x0443, 0x0445, 0x0455, 0x0456, 0x0458)
_GREEK_LOOK_ALIKES = (0x0391, 0x0392, 0x0395, 0x0396, 0x0397, 0x0399, 0x039A, 0x039C, 0x039D, 0x039F, 0x03A1, 0x03A4, 0x03A5, 0x03A7, 0x03BF)
_HOMOGLYPHS = {chr(cp) for cp in _CYRILLIC_LOOK_ALIKES + _GREEK_LOOK_ALIKES}
_TEXT_OPERATORS = {'Tj', 'TJ', "'", '"'}
_SUBTYPES = {'Type1', 'MMType1', 'TrueType', 'Type3', 'Type0'}


def _tick(cancel):
    if cancelled(cancel):
        raise InterruptedError('Character meaning inspection cancelled')


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _ident(value):
    try:
        number, generation = value.objgen
        return f'{number}:{generation}' if number else None
    except (AttributeError, ValueError, TypeError):
        return None


def _dict(value):
    return isinstance(value, pikepdf.Dictionary) and not isinstance(value, pikepdf.Stream)


def _name(value):
    return str(value)[1:] if isinstance(value, pikepdf.Name) else ''


def escape(text):
    """Show a character string without relying on the font that drew it."""
    out = []
    for ch in text:
        cp = ord(ch)
        printable = ch.isprintable() and not (0xE000 <= cp <= 0xF8FF or cp >= 0xF0000 or cp == 0xFFFD)
        out.append(ch if printable and ch != ' ' else f'⟦U+{cp:04X}⟧' if ch != ' ' else ' ')
    return ''.join(out)


def code_point_flags(text):
    flags = []
    for ch in text:
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFD or 0x100000 <= cp <= 0x10FFFD:
            flags.append('private-use')
        elif cp == 0xFFFD:
            flags.append('replacement-character')
        elif 0xFDD0 <= cp <= 0xFDEF or (cp & 0xFFFE) == 0xFFFE:
            flags.append('noncharacter')
        else:
            category = unicodedata.category(ch)
            if category == 'Cc':
                flags.append('control-character')
            elif category == 'Cn':
                flags.append('unassigned-code-point')
    return sorted(set(flags))


def _glyph_text(name):
    from fontTools import agl
    try:
        value = agl.toUnicode(name)
    except Exception:
        return ''
    return value if value and not re.fullmatch(r'[gG]\d+|cid\d+|\.notdef', name) else ''


def _encoding(font):
    """Return (base_encoding_name, {code: glyph_name}) for a simple font."""
    encoding = font.get('/Encoding')
    base, differences = None, {}
    if isinstance(encoding, pikepdf.Name):
        base = _name(encoding)
    elif _dict(encoding):
        base = _name(encoding.get('/BaseEncoding')) or None
        array = encoding.get('/Differences')
        if isinstance(array, pikepdf.Array):
            code = None
            for item in array:
                if isinstance(item, int) and not isinstance(item, bool):
                    code = int(item)
                elif isinstance(item, pikepdf.Name) and code is not None:
                    differences[code] = _name(item)
                    code += 1
    return base, differences


def _bounded_bytes(stream, limit=tounicode.MAX_BYTES):
    """Read a small map stream without ever expanding more than the limit."""
    import zlib
    raw = stream.read_raw_bytes()
    if len(raw) > limit:
        raise tounicode.CMapError('The ToUnicode stream is larger than the supported size')
    filters = stream.get('/Filter')
    names = [str(item) for item in filters] if isinstance(filters, pikepdf.Array) else [] if filters is None else [str(filters)]
    if not names:
        return bytes(raw)
    if names == ['/FlateDecode'] and stream.get('/DecodeParms') is None:
        inflater = zlib.decompressobj()
        try:
            data = inflater.decompress(bytes(raw), limit + 1)
        except zlib.error as exc:
            raise tounicode.CMapError('The ToUnicode stream does not decompress') from exc
        if len(data) > limit or inflater.unconsumed_tail:
            raise tounicode.CMapError('The ToUnicode stream expands beyond the supported size')
        return data
    raise tounicode.CMapError('Only uncompressed or Flate-compressed ToUnicode streams are supported')


def _font_facts(font):
    subtype = _name(font.get('/Subtype'))
    base_font = _name(font.get('/BaseFont'))
    plain = re.sub(r'^[A-Z]{6}\+', '', base_font)
    descendant = font
    problems = []
    if subtype == 'Type0':
        descendants = font.get('/DescendantFonts')
        descendant = descendants[0] if isinstance(descendants, pikepdf.Array) and len(descendants) == 1 else None
        if descendant is None or not _dict(descendant):
            problems.append('The composite font has no single descendant font.')
            descendant = pikepdf.Dictionary()
    descriptor = descendant.get('/FontDescriptor')
    descriptor = descriptor if _dict(descriptor) else pikepdf.Dictionary()
    embedded = any(key in descriptor for key in ('/FontFile', '/FontFile2', '/FontFile3'))
    if subtype == 'Type3':
        embedded = isinstance(font.get('/CharProcs'), pikepdf.Dictionary) and len(font['/CharProcs']) > 0
    encoding_name = _name(font.get('/Encoding')) if subtype == 'Type0' else ''
    width = 2 if subtype == 'Type0' else 1
    supported_codes = subtype != 'Type0' or encoding_name in {'Identity-H', 'Identity-V'}
    parsed, state, digest = None, 'absent', None
    mapping = font.get('/ToUnicode')
    if isinstance(mapping, pikepdf.Stream):
        try:
            raw = _bounded_bytes(mapping)
            digest = hashlib.sha256(raw).hexdigest()
            parsed = tounicode.parse(raw)
            state = 'present'
        except tounicode.CMapError as exc:
            state = 'unreadable'
            problems.append('The ToUnicode map cannot be read: ' + str(exc)[:160])
        except Exception as exc:  # unreadable stream filters, truncated data
            state = 'unreadable'
            problems.append('The ToUnicode stream cannot be decoded: ' + type(exc).__name__)
    elif mapping is not None:
        state = 'unreadable'
        problems.append('The ToUnicode entry is not a stream.')
    base, differences = (None, {}) if subtype == 'Type0' else _encoding(font)
    return {'object': _ident(font), 'base_font': base_font, 'plain_name': plain, 'subtype': subtype,
            'embedded': embedded, 'standard_14': plain in _STANDARD_14 and not embedded,
            'width': width, 'supported_codes': supported_codes, 'cmap_encoding': encoding_name,
            'to_unicode': state, 'parsed': parsed, 'to_unicode_sha256': digest,
            'base_encoding': base, 'differences': differences, 'problems': problems,
            'descendant_subtype': _name(descendant.get('/Subtype')) if subtype == 'Type0' else ''}


def text_for(facts, code):
    """(source, text) for a code; text is None when nothing established it."""
    parsed = facts['parsed']
    if parsed is not None:
        value = parsed['entries'].get((facts['width'], code))
        if value is not None:
            return 'to-unicode', value
    if facts['width'] == 1:
        name = facts['differences'].get(code)
        if name:
            value = _glyph_text(name)
            if value:
                return 'encoding', value
        elif facts['base_encoding'] in ('WinAnsiEncoding', 'MacRomanEncoding') or (
                facts['standard_14'] and facts['plain_name'] not in _SYMBOLIC and facts['base_encoding'] in (None, 'StandardEncoding')):
            if 32 <= code < 256:
                try:
                    if facts['base_encoding'] == 'WinAnsiEncoding':
                        return 'encoding', bytes([code]).decode('cp1252')
                    if facts['base_encoding'] == 'MacRomanEncoding':
                        return 'encoding', bytes([code]).decode('mac_roman')
                    from fontTools.encodings.StandardEncoding import StandardEncoding
                    value = _glyph_text(StandardEncoding[code])
                    if value:
                        return 'encoding', value
                except (UnicodeDecodeError, IndexError):
                    pass
    return None, None


def _decode(facts, raw):
    width = facts['width']
    if width == 2 and len(raw) % 2:
        return None
    return [int.from_bytes(raw[i:i + width], 'big') for i in range(0, len(raw), width)]


def _norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


class _Walker:
    def __init__(self, pdf, cancel):
        self.pdf, self.cancel = pdf, cancel
        self.fonts = {}      # id -> record
        self.uncertain = []
        self.actual = []     # ActualText disagreements
        self.operations = 0
        self.incomplete = set()
        self.page = 0
        self.direct = 0

    def record(self, font):
        key = _ident(font)
        if key is None:
            self.direct += 1
            key = f'direct-{self.direct}'
        entry = self.fonts.get(key)
        if entry is None:
            if len(self.fonts) >= LIMITS['fonts']:
                self.incomplete.add('font-limit')
                return None
            facts = _font_facts(font)
            facts['object'] = key
            entry = {'facts': facts, 'codes': {}, 'pages': [], 'uses': 0, 'font': font}
            self.fonts[key] = entry
        return entry

    def show(self, entry, raw, spans):
        facts = entry['facts']
        entry['uses'] += 1
        if self.page not in entry['pages'] and len(entry['pages']) < 200:
            entry['pages'].append(self.page)
        if not facts['supported_codes'] or facts['subtype'] not in _SUBTYPES:
            return
        codes = _decode(facts, raw)
        if codes is None:
            self.incomplete.add('odd-length-two-byte-string')
            return
        for code in codes:
            row = entry['codes'].get(code)
            if row is None:
                if len(entry['codes']) >= 70000:
                    self.incomplete.add('code-limit')
                    continue
                row = {'count': 0, 'page': self.page, 'context': bytes(raw[:200])}
                entry['codes'][code] = row
            row['count'] += 1
        if spans:
            pieces, known = [], True
            for code in codes:
                _, value = text_for(facts, code)
                if value is None:
                    known = False
                pieces.append(value or '')
            for span in spans:
                span['known'] = span['known'] and known
                span['text'].append(''.join(pieces))
                span['fonts'].append(entry['facts']['object'])

    def run(self, stream, resources, font, depth, active):
        stack, marked = [], []
        local_ops = 0
        try:
            instructions = pikepdf.parse_content_stream(stream)
        except Exception:
            self.incomplete.add('content-parse-error')
            return
        forms = 0
        for instruction in instructions:
            local_ops += 1
            self.operations += 1
            if local_ops % 512 == 0:
                _tick(self.cancel)
            if local_ops > LIMITS['operations_per_page'] or self.operations > LIMITS['operations']:
                self.incomplete.add('operation-limit')
                break
            operator = str(instruction.operator)
            operands = instruction.operands
            if operator == 'q':
                stack.append(font)
            elif operator == 'Q':
                if stack:
                    font = stack.pop()
            elif operator == 'Tf' and operands:
                table = resources.get('/Font') if _dict(resources) else None
                found = table.get(str(operands[0])) if _dict(table) else None
                font = found if _dict(found) else None
                if font is None:
                    self.incomplete.add('unresolved-font-resource')
            elif operator == 'gs' and operands:
                states = resources.get('/ExtGState') if _dict(resources) else None
                state = states.get(str(operands[0])) if _dict(states) else None
                setting = state.get('/Font') if _dict(state) else None
                if isinstance(setting, pikepdf.Array) and len(setting) == 2 and _dict(setting[0]):
                    font = setting[0]
            elif operator in ('BDC', 'BMC'):
                actual = None
                if operator == 'BDC' and len(operands) == 2:
                    properties = operands[1]
                    if isinstance(properties, pikepdf.Name):
                        table = resources.get('/Properties') if _dict(resources) else None
                        properties = table.get(str(properties)) if _dict(table) else None
                    if _dict(properties) and '/ActualText' in properties:
                        try:
                            actual = str(properties['/ActualText'])
                        except Exception:
                            actual = None
                marked.append({'actual': actual, 'known': True, 'text': [], 'fonts': [], 'page': self.page})
            elif operator == 'EMC':
                if marked:
                    span = marked.pop()
                    if span['actual'] is not None and span['known'] and span['text']:
                        shown = ''.join(span['text'])
                        if shown.strip() and _norm(shown) != _norm(span['actual']):
                            self.actual.append({'page': span['page'], 'fonts': sorted(set(span['fonts'])),
                                                'shown': shown[:LIMITS['sample_characters']],
                                                'declared': span['actual'][:LIMITS['sample_characters']]})
            elif operator in _TEXT_OPERATORS and operands:
                if font is None:
                    self.incomplete.add('text-without-font')
                    continue
                entry = self.record(font)
                if entry is None:
                    continue
                spans = [s for s in marked if s['actual'] is not None]
                if operator == 'TJ':
                    for item in operands[0] if isinstance(operands[0], pikepdf.Array) else []:
                        if isinstance(item, pikepdf.String):
                            self.show(entry, bytes(item), spans)
                elif isinstance(operands[-1], pikepdf.String):
                    self.show(entry, bytes(operands[-1]), spans)
            elif operator == 'Do' and operands:
                table = resources.get('/XObject') if _dict(resources) else None
                form = table.get(str(operands[0])) if _dict(table) else None
                if isinstance(form, pikepdf.Stream) and form.get('/Subtype') == pikepdf.Name.Form:
                    key = _ident(form)
                    forms += 1
                    if depth >= LIMITS['form_depth'] or forms > LIMITS['forms_per_page'] or key in active:
                        self.incomplete.add('form-depth-or-cycle')
                        continue
                    inner = form.get('/Resources')
                    self.run(form, inner if _dict(inner) else resources, font, depth + 1, active | {key})


def _first_context(facts, raw):
    codes = _decode(facts, bytes(raw)) or []
    pieces = []
    for code in codes[:LIMITS['sample_characters']]:
        _, value = text_for(facts, code)
        pieces.append(escape(value) if value is not None else '⟦?⟧')
    return ''.join(pieces)


def correction_limits(facts, document_limits):
    """Reasons a reviewed ToUnicode correction cannot be offered for this font."""
    reasons = list(document_limits)
    if facts['object'] is None or str(facts['object']).startswith('direct-'):
        reasons.append('The font is not a shared indirect object, so one edit cannot be bound to it.')
    if facts['subtype'] not in _SUBTYPES:
        reasons.append('This font type is not supported.')
    if not facts['embedded']:
        reasons.append('The font is not embedded. A reader substitutes its own glyphs, so the visible character is not fixed by the file. Re-export with the font embedded.')
    if facts['subtype'] == 'Type0' and (facts['cmap_encoding'] not in {'Identity-H', 'Identity-V'}
                                          or facts['descendant_subtype'] not in {'CIDFontType0', 'CIDFontType2'}):
        reasons.append('Only Identity-H/V composite fonts with an embedded CID font are supported.')
    if facts['to_unicode'] != 'present':
        reasons.append('There is no readable ToUnicode map to correct. Supplying every code of a font that has none is not supported yet; re-export from the source.')
    elif facts['subtype'] != 'Type0' and any(w != 1 for w, _ in facts['parsed']['entries']):
        reasons.append('The ToUnicode map uses code widths this font cannot use.')
    elif facts['subtype'] == 'Type0' and any(w != 2 for w, _ in facts['parsed']['entries']):
        reasons.append('The ToUnicode map uses code widths this font cannot use.')
    return sorted(set(reasons))


def document_correction_limits(pdf):
    reasons = []
    if pdf.is_encrypted:
        reasons.append('Encrypted documents need a separately selected workflow.')
    if '/Perms' in pdf.Root or any(_dict(obj) and (obj.get('/Type') == pikepdf.Name.Sig or '/ByteRange' in obj)
                                    for obj in pdf.objects):
        reasons.append('Signed documents need a separately selected workflow.')
    if '/AcroForm' in pdf.Root:
        reasons.append('Interactive forms are outside this repair; their values and appearances are kept exactly.')
    try:
        if float(pdf.pdf_version) >= 2:
            reasons.append('PDF 2.x is outside the evaluated workflow.')
    except (TypeError, ValueError):
        reasons.append('The PDF version is not readable.')
    return reasons


def analyse(pdf, *, cancel=None):
    """Walk every page once and return per-font usage; never writes."""
    walker = _Walker(pdf, cancel)
    total = len(pdf.pages)
    for number, page in enumerate(pdf.pages, 1):
        _tick(cancel)
        if number > LIMITS['pages']:
            walker.incomplete.add('page-limit')
            break
        walker.page = number
        resources = page.resources
        walker.run(page, resources if _dict(resources) else pikepdf.Dictionary(), None, 0, set())
    return walker, total


def _row(facts, code, usage):
    source, text = text_for(facts, code)
    flags = code_point_flags(text) if text else []
    name = facts['differences'].get(code, '')
    glyph_text = _glyph_text(name) if name else ''
    if text is not None and glyph_text and source == 'to-unicode' and unicodedata.normalize('NFKC', text) != unicodedata.normalize('NFKC', glyph_text):
        flags = sorted(set(flags) | {'glyph-name-disagrees'})
    width = facts['width']
    return {'code': code, 'code_hex': f'{code:0{2 * width}X}', 'width': width, 'uses': usage['count'],
            'source': source, 'text': escape(text) if text is not None else None,
            'text_utf16be_hex': text.encode('utf-16-be').hex().upper() if text is not None else None,
            'glyph_name': name or None, 'flags': flags, 'page': usage['page'],
            'context': _first_context(facts, usage['context'])}


def inventory(pdf, *, cancel=None, walker=None, total=None):
    """Per-font rows for correction and the screen; includes every used code."""
    if walker is None:
        walker, total = analyse(pdf, cancel=cancel)
    document_limits = document_correction_limits(pdf)
    fonts = []
    for key in sorted(walker.fonts):
        _tick(cancel)
        entry = walker.fonts[key]
        facts = entry['facts']
        rows = [_row(facts, code, usage) for code, usage in sorted(entry['codes'].items())]
        fonts.append({'facts': facts, 'rows': rows, 'pages': entry['pages'], 'uses': entry['uses'],
                      'correction_limits': correction_limits(facts, document_limits)})
    return fonts, walker, total


def _mixed_script(token):
    letters = [ch for ch in token if ch.isalpha()]
    if len(letters) < 3:
        return False
    latin = sum(1 for ch in letters if 'LATIN' in unicodedata.name(ch, ''))
    look_alike = sum(1 for ch in letters if ch in _HOMOGLYPHS)
    return latin >= 2 and look_alike >= 1


def _page_text_screen(document, pages, cancel):
    suspect, mixed = [], []
    for number in range(1, pages + 1):
        _tick(cancel)
        page = document[number - 1]
        text_page = page.get_textpage()
        try:
            count = text_page.count_chars()
            text = text_page.get_text_range(0, min(count, LIMITS['text_characters_per_page'])) if count else ''
        finally:
            text_page.close()
            page.close()
        flags = {}
        for ch in text:
            for flag in code_point_flags(ch):
                if flag in ('private-use', 'replacement-character', 'control-character'):
                    if ch in '\r\n\t\x02\x0c':
                        continue
                    flags[flag] = flags.get(flag, 0) + 1
        if flags:
            suspect.append({'page': number, 'counts': flags})
        for token in re.findall(r'\w+', text):
            if _mixed_script(token) and len(mixed) < LIMITS['mixed_script_records']:
                mixed.append({'page': number, 'sample': escape(token[:LIMITS['sample_characters']])})
    return suspect, mixed


def _codes_view(rows):
    return [{key: row[key] for key in ('code_hex', 'width', 'uses', 'source', 'text', 'glyph_name', 'flags', 'page', 'context')}
            for row in rows[:LIMITS['codes_per_record']]]


def assess(path, *, cancel=None, pdf=None, document=None):
    """Source-bound advisory evidence; borrowed contexts stay open."""
    _tick(cancel)
    path = Path(path).resolve()
    result = {'policy': POLICY, 'status': 'needs-review', 'advisory': True, 'source_sha256': None,
              'fonts': [], 'findings': [], 'uncertain': [], 'unembedded_fonts': [],
              'counts': {'fonts_used': 0, 'codes_used': 0, 'records': 0},
              'coverage': {'complete': False, 'pages_scanned': 0, 'pages_total': 0},
              'limits': dict(LIMITS), 'limitations': list(LIMITATIONS), 'fix_path': FIX}
    try:
        result['source_sha256'] = _sha(path)
        if path.stat().st_size > LIMITS['input_bytes']:
            result['coverage']['reasons'] = ['input-byte-limit']
            return result
        with ExitStack() as stack:
            if pdf is None:
                pdf = stack.enter_context(pikepdf.open(path))
            fonts, walker, total = inventory(pdf, cancel=cancel)
            scanned = min(total, LIMITS['pages'])
            result['coverage'].update(pages_scanned=scanned, pages_total=total)
            records = result['findings']

            def add(record):
                if len(records) >= LIMITS['records']:
                    walker.incomplete.add('record-limit')
                else:
                    records.append(record)

            for font in fonts:
                facts, rows = font['facts'], font['rows']
                summary = {'object': facts['object'], 'base_font': facts['base_font'], 'subtype': facts['subtype'],
                           'embedded': facts['embedded'], 'standard_14': facts['standard_14'],
                           'to_unicode': facts['to_unicode'], 'used_codes': len(rows), 'uses': font['uses'],
                           'pages': font['pages'][:LIMITS['pages_per_record']],
                           'reviewed_correction_available': not font['correction_limits'],
                           'reviewed_correction_limits': font['correction_limits']}
                result['fonts'].append(summary)
                result['counts']['codes_used'] += len(rows)
                head = {'font': {key: summary[key] for key in ('object', 'base_font', 'subtype', 'embedded', 'standard_14')},
                        'pages': summary['pages'],
                        'reviewed_correction_available': summary['reviewed_correction_available']}
                if not facts['embedded']:
                    guess = ('A standard font: the viewer draws its own copy of the glyphs.' if facts['standard_14']
                             else 'The viewer substitutes a font of its own, so the visible character is not fixed by this file.')
                    result['unembedded_fonts'].append({**head, 'uses': font['uses'], 'used_codes': len(rows),
                        'note': guess, 'guidance': 'This tool does not embed or substitute fonts. Re-export the source with the font embedded, or with a font that has Unicode mapping.'})
                for problem in facts['problems']:
                    result['uncertain'].append({**head, 'reasons': [problem]})
                if not facts['supported_codes'] and font['uses']:
                    result['uncertain'].append({**head, 'reasons': [
                        'Used codes cannot be decoded for the CMap ' + (facts['cmap_encoding'] or 'of this font') + '; their text is not screened.']})
                    continue
                by_flag = {}
                for row in rows:
                    for flag in row['flags']:
                        by_flag.setdefault(flag, []).append(row)
                    if row['source'] is None:
                        by_flag.setdefault('unmapped-code' if facts['to_unicode'] == 'present' else 'missing-tounicode', []).append(row)
                for flag, flagged in sorted(by_flag.items()):
                    add({**head, 'issue': flag, 'codes': _codes_view(flagged), 'code_count': len(flagged),
                         'omitted_codes': max(0, len(flagged) - LIMITS['codes_per_record']),
                         'page': min(r['page'] for r in flagged)})
            fonts_by_id = {f['facts']['object']: f for f in fonts}
            for item in walker.actual:
                shown = [fonts_by_id[o]['facts'] for o in item['fonts'] if o in fonts_by_id]
                add({'issue': 'actualtext-disagrees', 'page': item['page'],
                     'fonts': [{'object': f['object'], 'base_font': f['base_font']} for f in shown],
                     'shown_text': escape(item['shown']), 'declared_actual_text': escape(item['declared']),
                     'note': 'The text this font maps to differs from the ActualText of the same marked content. A reader that honours ActualText will use the declared text; one that does not will use the mapped text.'})
            if document is not None:
                suspect, mixed = _page_text_screen(document, scanned, cancel)
                font_flags = {r['issue'] for r in records}
                if suspect and not font_flags & {'private-use', 'replacement-character', 'control-character'}:
                    add({'issue': 'extracted-text-suspect-characters', 'pages': [s['page'] for s in suspect][:LIMITS['pages_per_record']],
                         'page': suspect[0]['page'], 'per_page': suspect[:LIMITS['pages_per_record']],
                         'note': 'The extracted text of these pages holds private-use, replacement or control characters. If this text came from OCR, correct the words in the OCR text editor.'})
                for item in mixed:
                    add({'issue': 'mixed-script-word', 'page': item['page'], 'sample': item['sample'],
                         'note': 'A word mixes Latin letters with look-alike Cyrillic or Greek letters. Check the visible word; if this is OCR text, correct it in the OCR text editor, otherwise repair the source.'})
            else:
                walker.incomplete.add('page-text-not-screened')
            result['uncertain'] = result['uncertain'][:LIMITS['records']]
            result['counts'].update(fonts_used=len(fonts), records=len(records))
            reasons = sorted(walker.incomplete)
            if reasons:
                result['coverage']['reasons'] = reasons
            result['coverage']['complete'] = not reasons
            if records or result['uncertain']:
                result['status'] = 'needs-review'
            elif reasons:
                result['status'] = 'needs-review'
            elif not fonts:
                result['status'] = 'not-applicable'
            else:
                result['status'] = 'pass'
        if _sha(path) != result['source_sha256']:
            raise ValueError('The source changed during character meaning inspection')
    except InterruptedError:
        raise
    except Exception as exc:
        result.update(status='error', error={'type': type(exc).__name__, 'message': str(exc)[:300]})
        result['coverage']['complete'] = False
    return result
