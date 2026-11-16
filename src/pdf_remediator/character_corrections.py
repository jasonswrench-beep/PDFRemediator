"""Reviewed correction of wrong extracted characters in embedded fonts.

A reviewer who has compared the visible page with the extracted text names, per
font and character code, the text that code really shows. This module writes
those choices into a *separate copy*: only the ToUnicode map of each named font
changes. Page programs, font programs, widths, encodings and every other object
stay exactly as they were, and the copy is accepted only when independent
checks prove it:

* the object graph differs from the source in nothing but those ToUnicode maps;
* each rewritten map reads back as the old entries plus exactly the reviewed ones;
* every page renders pixel-for-pixel like the source, with the same page boxes,
  annotations and navigation;
* extracted text changes only where an edited font drew an edited code.

Nothing is guessed, no font is embedded or substituted, no model is involved,
and a corrected copy is a new document that needs its own fresh review.
"""
from __future__ import annotations

from collections import deque
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
import uuid

import pikepdf
import pypdfium2 as pdfium

from . import character_meaning as meaning
from . import tounicode
from .process import cancelled

INVENTORY_SCHEMA = 'phase2-character-inventory-1'
PLAN_SCHEMA = 'phase2-character-corrections-1'
EVIDENCE_SCHEMA = 'phase2-character-correction-evidence-1'
LIMITS = {'corrections': 500, 'fonts': 50, 'text_code_points': tounicode.MAX_TEXT_CODE_POINTS,
          'rows_per_font': 2000, 'reviewer_characters': 120, 'input_bytes': 100 * 1024 * 1024}
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_REFUSED_CATEGORIES = {'Cc', 'Cf', 'Cs', 'Co', 'Cn'}


class CorrectionError(ValueError):
    """A plan or a result cannot be accepted; nothing is published."""


def _tick(cancel):
    if cancelled(cancel):
        raise InterruptedError('Character correction cancelled')


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _digest(value):
    return _sha_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                                 allow_nan=False).encode('utf-8'))


def _need(condition, message):
    if not condition:
        raise CorrectionError(message)


def reviewed_text_problem(text):
    """Why a reviewed value cannot be written, or None."""
    if not isinstance(text, str) or not text:
        return 'The intended text is empty.'
    if len(text) > LIMITS['text_code_points']:
        return f'The intended text is longer than {LIMITS["text_code_points"]} characters.'
    for ch in text:
        if unicodedata.category(ch) in _REFUSED_CATEGORIES:
            return 'The intended text holds a control, format, private-use, surrogate or unassigned character.'
    flags = meaning.code_point_flags(text)
    if flags:
        return 'The intended text holds a ' + ', '.join(flags) + ' character.'
    return None


# --------------------------------------------------------------------------- inventory

def _row_fingerprint(source_sha, facts, row):
    return _digest({'source': source_sha, 'font': facts['object'], 'base_font': facts['base_font'],
                    'to_unicode_sha256': facts['to_unicode_sha256'], 'code': row['code'],
                    'width': row['width'], 'text_utf16be_hex': row['text_utf16be_hex'], 'source_kind': row['source']})


def get_inventory(source, *, cancel=None):
    """Source-bound rows a reviewer may correct; read-only."""
    source = Path(source).resolve()
    _need(source.is_file() and source.stat().st_size <= LIMITS['input_bytes'], 'Choose a PDF smaller than 100 MB.')
    source_sha = _sha(source)
    with pikepdf.open(source) as pdf:
        fonts, walker, total = meaning.inventory(pdf, cancel=cancel)
        document_limits = meaning.document_correction_limits(pdf)
        incomplete = sorted(walker.incomplete)
    if incomplete:
        document_limits = document_limits + ['Page content could not be read completely (' + ', '.join(incomplete) + ').']
    out = []
    for font in fonts:
        facts = font['facts']
        reasons = sorted(set(font['correction_limits'] + (['Page content could not be read completely.'] if incomplete else [])))
        rows, truncated = [], False
        for row in font['rows']:
            if len(rows) >= LIMITS['rows_per_font']:
                truncated = True
                break
            rows.append({'id': f"{facts['object']}:{row['code_hex']}", 'font': facts['object'],
                         'code': row['code'], 'code_hex': row['code_hex'], 'width': row['width'],
                         'uses': row['uses'], 'page': row['page'], 'source': row['source'],
                         'text': row['text'], 'text_utf16be_hex': row['text_utf16be_hex'],
                         'flags': row['flags'], 'glyph_name': row['glyph_name'], 'context': row['context'],
                         'fingerprint': _row_fingerprint(source_sha, facts, row)})
        if truncated:
            reasons.append('More used codes than the supported row limit; the rows shown are the lowest codes only.')
        codes_by_text = {}
        for row in font['rows']:
            if row['text_utf16be_hex'] is not None:
                codes_by_text.setdefault(row['text_utf16be_hex'], []).append(row['code'])
        out.append({'object': facts['object'], 'base_font': facts['base_font'], 'subtype': facts['subtype'],
                    'used_text_utf16be_hex': sorted(codes_by_text), 'codes_by_text': codes_by_text,
                    'embedded': facts['embedded'], 'to_unicode': facts['to_unicode'],
                    'to_unicode_sha256': facts['to_unicode_sha256'], 'pages': font['pages'][:meaning.LIMITS['pages_per_record']],
                    'uses': font['uses'], 'eligible': not reasons, 'limits': reasons,
                    'rows_truncated': truncated, 'rows': rows if not reasons else rows[:0]})
        if reasons:
            out[-1]['rows_withheld'] = len(rows)
    inventory = {'schema': INVENTORY_SCHEMA, 'policy': meaning.POLICY, 'source_sha256': source_sha,
                 'document_limits': document_limits, 'fonts': out, 'limits': dict(LIMITS),
                 'pages': total,
                 'notice': 'Rows list what a reader extracts today. Only a person comparing the visible character '
                           'can decide what a code really shows; nothing here is a suggestion.'}
    inventory['inventory_sha256'] = _digest({k: v for k, v in inventory.items() if k != 'inventory_sha256'})
    return inventory


# --------------------------------------------------------------------------- plan

def _read_plan(plan):
    if isinstance(plan, (str, Path)):
        path = Path(plan)
        _need(path.is_file() and path.stat().st_size <= 4 * 1024 * 1024, 'The correction plan is missing or too large.')
        try:
            plan = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise CorrectionError('The correction plan is not valid UTF-8 JSON.') from exc
    _need(isinstance(plan, dict), 'The correction plan must be a JSON object.')
    return plan


def validate_plan(plan, inventory):
    """Return [(font_inventory, row, new_text)] after checking every binding."""
    plan = _read_plan(plan)
    _need(set(plan) == {'schema', 'source_sha256', 'inventory_sha256', 'accepted_by', 'accepted_at', 'corrections'},
          'The correction plan has missing or unknown fields.')
    _need(plan['schema'] == PLAN_SCHEMA, 'Unknown correction plan schema.')
    _need(plan['source_sha256'] == inventory['source_sha256'] and plan['inventory_sha256'] == inventory['inventory_sha256'],
          'The plan is bound to a different source or inventory; create it again from this PDF.')
    reviewer = plan['accepted_by']
    _need(isinstance(reviewer, str) and 2 <= len(reviewer.strip()) <= LIMITS['reviewer_characters']
          and not any(unicodedata.category(c).startswith('C') for c in reviewer),
          'Named acceptance needs the reviewer\'s name.')
    stamp = plan['accepted_at']
    try:
        _need(isinstance(stamp, str) and len(stamp) <= 40, 'bad')
        datetime.date.fromisoformat(stamp[:10])
    except (ValueError, CorrectionError) as exc:
        raise CorrectionError('Named acceptance needs the date of acceptance (YYYY-MM-DD).') from exc
    corrections = plan['corrections']
    _need(isinstance(corrections, list) and 1 <= len(corrections) <= LIMITS['corrections'],
          f'A plan holds 1 to {LIMITS["corrections"]} corrections.')
    fonts = {f['object']: f for f in inventory['fonts']}
    rows = {row['id']: (font, row) for font in inventory['fonts'] for row in font['rows']}
    seen, chosen = set(), []
    for item in corrections:
        _need(isinstance(item, dict) and set(item) == {'id', 'font', 'code_hex', 'previous_text_utf16be_hex', 'text', 'fingerprint'},
              'A correction has missing or unknown fields.')
        _need(item['id'] not in seen, 'A code is corrected twice in one plan.')
        seen.add(item['id'])
        found = rows.get(item['id'])
        _need(found is not None, 'A correction names a font or code that is not in this inventory.')
        font, row = found
        _need(font['eligible'], 'A correction names a font that cannot be corrected: ' + ' '.join(font['limits'])[:300])
        _need(item['font'] == row['font'] and item['code_hex'] == row['code_hex']
              and item['previous_text_utf16be_hex'] == row['text_utf16be_hex'] and item['fingerprint'] == row['fingerprint'],
              'A correction no longer matches the source row it was written for.')
        problem = reviewed_text_problem(item['text'])
        _need(problem is None, problem or '')
        _need(item['text'].encode('utf-16-be').hex().upper() != row['text_utf16be_hex'],
              'A correction repeats the text the code already has; leave it out.')
        _need(row['text_utf16be_hex'] is not None and len(bytes.fromhex(row['text_utf16be_hex']).decode('utf-16-be')) == 1,
              'Only a code that extracts as exactly one character can be corrected here; extraction cannot show which of several characters changed.')
        chosen.append((font, row, item['text']))
    _need(len({font['object'] for font, _, _ in chosen}) <= LIMITS['fonts'], f'At most {LIMITS["fonts"]} fonts per plan.')
    # Extraction cannot show which of several codes drew a shared character,
    # so codes that share previous text must change together.
    for font in {id(f): f for f, _, _ in chosen}.values():
        picked = {row['code']: text for f, row, text in chosen if f is font}
        by_old = {}
        for row in font['rows']:
            by_old.setdefault(row['text_utf16be_hex'], []).append(row['code'])
        for old, codes in by_old.items():
            touched = [c for c in codes if c in picked]
            if touched:
                _need(len(touched) == len(codes) and len({picked[c] for c in touched}) == 1,
                      'Two used codes of one font extract as the same text. Extraction cannot tell them apart, so correct all of them to the same text or none.')
    return plan, chosen


# --------------------------------------------------------------------------- proofs

def canonical_graph(pdf, *, edited_keys=None, edited_indexes=None, cancel=None):
    """Numbering-independent description of everything reachable from the catalog.

    The ToUnicode entry of an edited font is replaced by a fixed marker, so two
    graphs compare equal exactly when they differ in nothing else.
    """
    index, order, queue = {}, [], deque()
    edited_found = {}

    def ref(obj):
        key = obj.objgen
        if key not in index:
            index[key] = len(index)
            order.append(obj)
            queue.append(obj)
        return {'ref': index[key]}

    def encode(value, depth=0):
        if depth > 300:
            raise CorrectionError('The document graph is nested too deeply to compare.')
        if isinstance(value, pikepdf.Object) and value.objgen[0] and depth > 0:
            return ref(value)
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, pikepdf.Name):
            return {'n': str(value)}
        if isinstance(value, pikepdf.String):
            return {'s': bytes(value).hex()}
        if isinstance(value, pikepdf.Array):
            return [encode(item, depth + 1) for item in value]
        if isinstance(value, pikepdf.Stream):
            keys = sorted(k for k in value.keys() if k not in ('/Length', '/Filter', '/DecodeParms', '/DL'))
            try:
                data, mode = value.read_bytes(), 'decoded'
            except Exception:
                data, mode = value.read_raw_bytes(), 'raw+' + str(value.get('/Filter'))
            return {'stream': {k: encode(value[k], depth + 1) for k in keys}, 'data': _sha_bytes(data), 'mode': mode}
        if isinstance(value, pikepdf.Dictionary):
            return {k: encode(value[k], depth + 1) for k in sorted(value.keys())}
        if isinstance(value, pikepdf.Object):
            return {'other': str(value)[:200]}
        return {'d': str(value)}

    def encode_object(obj, position):
        if isinstance(obj, pikepdf.Stream):
            return encode_stream_object(obj, position)
        if isinstance(obj, pikepdf.Dictionary):
            keys = sorted(obj.keys())
            replaced = ((edited_keys is not None and obj.objgen in edited_keys)
                        or (edited_indexes is not None and position in edited_indexes)) and '/ToUnicode' in obj \
                and obj.get('/Subtype') in (pikepdf.Name.Type1, pikepdf.Name.TrueType, pikepdf.Name.MMType1,
                                            pikepdf.Name.Type3, pikepdf.Name.Type0)
            result = {}
            for key in keys:
                if replaced and key == '/ToUnicode':
                    result[key] = {'replaced_to_unicode': True}
                    edited_found[position] = obj.objgen
                else:
                    result[key] = encode(obj[key], 1)
            return result
        return encode(obj, 1)

    def encode_stream_object(obj, position):
        keys = sorted(k for k in obj.keys() if k not in ('/Length', '/Filter', '/DecodeParms', '/DL'))
        try:
            data, mode = obj.read_bytes(), 'decoded'
        except Exception:
            data, mode = obj.read_raw_bytes(), 'raw+' + str(obj.get('/Filter'))
        return {'stream': {k: encode(obj[k], 1) for k in keys}, 'data': _sha_bytes(data), 'mode': mode}

    ref(pdf.Root)
    info = pdf.trailer.get('/Info')
    if info is not None and getattr(info, 'objgen', (0, 0))[0]:
        ref(info)
    records = []
    count = 0
    while queue:
        obj = queue.popleft()
        count += 1
        if count % 256 == 0:
            _tick(cancel)
        if count > 2_000_000:
            raise CorrectionError('The document has too many objects to compare.')
        records.append(encode_object(obj, index[obj.objgen]))
    return records, index, edited_found


def _diff_summary(left, right):
    for position, (a, b) in enumerate(zip(left, right)):
        if a != b:
            kind = 'stream' if isinstance(a, dict) and 'stream' in a else 'object'
            return f'Object {position} of the traversal differs ({kind}).'
    return f'The graphs hold {len(left)} and {len(right)} objects.'


def _font_name(text_page, index):
    from .fonts import _font_name as name
    return name(text_page, index)


def _plain(name):
    return re.sub(r'^[A-Z]{6}\+', '', name.lstrip('/'))


def _text_proof(before, after, edits, cancel=None):
    """Extracted text may change only where an edited font drew an edited code.

    ``edits`` maps a font's plain name to {previous_text: new_text}.
    """
    documents = [pdfium.PdfDocument(str(path)) for path in (before, after)]
    changed = []
    try:
        _need(len(documents[0]) == len(documents[1]), 'The copy has a different page count.')
        for number in range(len(documents[0])):
            _tick(cancel)
            pages = [doc[number] for doc in documents]
            texts = [page.get_textpage() for page in pages]
            try:
                expected, pieces = [], []
                for index in range(texts[0].count_chars()):
                    ch = texts[0].get_text_range(index, 1)
                    pieces.append(ch)
                    table = edits.get(_plain(_font_name(texts[0], index)))
                    if table is not None and ch in table:
                        expected.append(table[ch])
                        changed.append({'page': number + 1, 'before': ch, 'after': table[ch]})
                    else:
                        expected.append(ch)
                _need(''.join(pieces) == texts[0].get_text_range(), 'Per-character and whole-page extraction of the source disagree.')
                _need(''.join(expected) == texts[1].get_text_range(),
                      f'Extracted text on page {number + 1} changed somewhere other than the edited codes.')
            finally:
                for text in texts:
                    text.close()
                for page in pages:
                    page.close()
    finally:
        for doc in documents:
            doc.close()
    _need(changed, 'No extracted character changed, so the copy would not correct anything.')
    return changed


def _collision_check(inventory, chosen):
    """Extraction names a font, not a code: refuse when a name could mean two things.

    Returns {plain font name: {previous text: new text}} for the text proof.
    """
    edits = {}
    for font, row, text in chosen:
        table = edits.setdefault(_plain(font['base_font']), {})
        _need(table.get(meaning_text(row), text) == text,
              'Two font objects with the same name would extract the same text differently after the change.')
        table[meaning_text(row)] = text
    edited = {(f['object'], r['code']) for f, r, _ in chosen}
    for font in inventory['fonts']:
        table = edits.get(_plain(font['base_font']))
        if table is None:
            continue
        for old_hex in font['used_text_utf16be_hex']:
            old = bytes.fromhex(old_hex).decode('utf-16-be')
            if old in table and not any((font['object'], code) in edited for code in font['codes_by_text'].get(old_hex, [])):
                raise CorrectionError('Another used code or font object with the same name extracts the same text, '
                                      'so extraction cannot show which one changed. Correct all of them together or none.')
    return edits


def meaning_text(row):
    return bytes.fromhex(row['text_utf16be_hex']).decode('utf-16-be')


def _check_fidelity(before, after, cancel):
    from .inspection import compare_fidelity
    appearance = compare_fidelity(before, after, cancel=cancel)
    pages = appearance.get('pages') or []
    keys = ('render_status', 'dimensions_status', 'page_boxes_status', 'annotations_status')
    _need(pages and all(all(p.get(key) == 'pass' for key in keys) for p in pages),
          'The copy does not render exactly like the source on every page.')
    rest = [c for c in appearance.get('checks', []) if c['id'] != 'all-page-render-and-content']
    _need(all(c['status'] in ('pass', 'not-applicable') for c in rest), 'The copy changed page boxes, annotations or navigation.')
    return {'status': 'pass', 'pages_compared': len(pages),
            'checks': [{'id': c['id'], 'status': ('text-differs-only-as-reviewed (proved separately)'
                                                  if c['id'] == 'all-page-render-and-content' else c['status'])}
                       for c in appearance.get('checks', [])],
            'scope': 'Exact PDFium pixels, page boxes, annotations and navigation; raw text differs only where reviewed.'}


# --------------------------------------------------------------------------- apply

def _locate(pdf, object_id):
    number, generation = (int(part) for part in object_id.split(':'))
    return pdf.get_object((number, generation))


def create_corrected_copy(source, plan, destination, *, expected_plan_sha256=None, cancel=None):
    """Write a corrected copy and its evidence; publish nothing on any refusal."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    evidence_path = destination.with_name(destination.stem + '.character-corrections.json')
    if source == destination or destination.exists() or evidence_path.exists() or not destination.parent.is_dir():
        return {'schema': EVIDENCE_SCHEMA, 'status': 'refused', 'output': None,
                'reason': 'CorrectionError: the corrected copy needs a new file name in an existing folder; nothing is overwritten.'}
    plan_bytes = None
    temporary = destination.with_name('.' + destination.name + '.' + uuid.uuid4().hex[:8] + '.partial')
    created, published = [], False
    try:
        if isinstance(plan, (str, Path)):
            plan_bytes = Path(plan).read_bytes()
            _need(expected_plan_sha256 is None or _sha_bytes(plan_bytes) == expected_plan_sha256, 'The accepted plan changed.')
        source_sha = _sha(source)
        inventory = get_inventory(source, cancel=cancel)
        _need(not inventory['document_limits'], 'This document cannot be corrected: ' + ' '.join(inventory['document_limits'])[:400])
        plan, chosen = validate_plan(plan, inventory)
        edits = _collision_check(inventory, chosen)
        by_font = {}
        for font, row, text in chosen:
            by_font.setdefault(font['object'], []).append((row, text))
        expected_entries = {}
        with pikepdf.open(source) as pdf:
            for object_id, changes in by_font.items():
                font = _locate(pdf, object_id)
                facts = meaning._font_facts(font)
                inv_font = next(f for f in inventory['fonts'] if f['object'] == object_id)
                _need(isinstance(font, pikepdf.Dictionary) and facts['to_unicode'] == 'present'
                      and facts['to_unicode_sha256'] == inv_font['to_unicode_sha256'],
                      'A font changed since the inventory was made.')
                parsed = copy.deepcopy(facts['parsed'])
                for row, text in changes:
                    _need(parsed['entries'].get((row['width'], row['code'])) == meaning_text(row),
                          'A mapping changed since the inventory was made.')
                    parsed['entries'][(row['width'], row['code'])] = text
                font['/ToUnicode'] = pdf.make_stream(tounicode.serialize(parsed))
                expected_entries[object_id] = parsed
            created.append(temporary)
            pdf.save(temporary, deterministic_id=True)
        # --- independent proofs, made on the saved bytes
        rewritten = {}
        with pikepdf.open(source) as original, pikepdf.open(temporary) as saved:
            keys = {_locate(original, object_id).objgen for object_id in by_font}
            left, left_index, left_found = canonical_graph(original, edited_keys=keys, cancel=cancel)
            _need(set(left_found.values()) == keys, 'An edited font was not found in the source graph.')
            right, right_index, right_found = canonical_graph(saved, edited_indexes=set(left_found), cancel=cancel)
            _need(left == right, 'The copy differs from the source beyond the reviewed ToUnicode maps. ' + _diff_summary(left, right))
            _need(set(right_found) == set(left_found), 'The same fonts are not edited in the copy.')
            by_position = {position: key for key, position in right_index.items()}
            for object_id, parsed in expected_entries.items():
                position = left_index[_locate(original, object_id).objgen]
                data = saved.get_object(by_position[position])['/ToUnicode'].read_bytes()
                _need(tounicode.parse(data) == {'codespaces': [tuple(c) for c in parsed['codespaces']], 'entries': parsed['entries']},
                      'A rewritten ToUnicode map does not read back to the reviewed entries.')
                rewritten[object_id] = _sha_bytes(data)
        fidelity = _check_fidelity(source, temporary, cancel)
        changed = _text_proof(source, temporary, edits, cancel)
        _need(_sha(source) == source_sha, 'The source changed while the copy was made.')
        with destination.open('xb'):
            created.append(destination)
        os.replace(temporary, destination)
        created.remove(temporary)
        evidence = {'schema': EVIDENCE_SCHEMA, 'status': 'pass', 'policy': meaning.POLICY,
                    'source_sha256': source_sha, 'output_sha256': _sha(destination),
                    'plan_sha256': _digest(plan), 'plan_file_sha256': _sha_bytes(plan_bytes) if plan_bytes is not None else None,
                    'inventory_sha256': inventory['inventory_sha256'],
                    'accepted_by': plan['accepted_by'], 'accepted_at': plan['accepted_at'],
                    'corrections': [{'font': font['object'], 'base_font': font['base_font'], 'code_hex': row['code_hex'],
                                     'previous_text': row['text'], 'text': text,
                                     'uses': row['uses'], 'first_page': row['page']} for font, row, text in chosen],
                    'rewritten_to_unicode_sha256': rewritten,
                    'proofs': {'object_graph': 'Identical to the source except the ToUnicode map of each edited font.',
                               'to_unicode': 'Each rewritten map reads back to the old entries plus exactly the reviewed ones.',
                               'fidelity': fidelity,
                               'extracted_text': {'status': 'pass', 'changed_characters': len(changed),
                                                  'rule': 'Text differs only where an edited font drew an edited code.'}},
                    'guarantees': ['No font, content stream, width, encoding or font program was changed.',
                                   'No character was guessed: every value was typed by the named reviewer.',
                                   'The original file is untouched and this copy is a new document.'],
                    'human_review_pending': ['Compare every corrected character with the visible page in context.',
                                             'This copy has no inherited approvals; process it as a new document.'],
                    'ai_used': False}
        with evidence_path.open('xb') as stream:
            created.append(evidence_path)
            stream.write((json.dumps(evidence, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
        published = True
        return {**evidence, 'output': str(destination), 'evidence_path': str(evidence_path)}
    except InterruptedError:
        raise
    except (CorrectionError, OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration,
            pikepdf.PdfError, tounicode.CMapError, pdfium.PdfiumError) as exc:
        return {'schema': EVIDENCE_SCHEMA, 'status': 'refused', 'reason': f'{type(exc).__name__}: {exc}'[:600], 'output': None}
    finally:
        if not published:
            for path in created + [temporary]:
                try:
                    if path.exists():
                        path.unlink()
                except OSError:
                    pass
