"""Turn-first recognition for scans stored sideways or upside down.

The scan itself is never changed. Each page picture is tried in the four right-angle turns, the clearly best turn is read,
and Tesseract's own invisible text page is placed back onto the original page in its original orientation. Every existing OCR
preservation gate still runs afterwards. Confidence is a mechanical filter, never accuracy or accessibility approval.
"""
from pathlib import Path
import hashlib
import html
import json
import re

import pikepdf

VERSION = 'local-turn-recognition-3'
SCHEMA = 'phase1-ocr-turns-1'
TURNS = (0, 90, 180, 270)
TRIAL_SIDE = 2200
MIN_CONFIDENCE = 60
MIN_LETTERS = 3
MIN_WORDS = 5
MIN_GAIN = 1.5
TIE = 0.9
MAX_EVIDENCE_BYTES = 1_000_000
MAX_CODES = 4096
ENV_KEYS = ('PDF_REMEDIATOR_TURN_EVIDENCE', 'PDF_REMEDIATOR_TURN_SOURCE_SHA256')

_START_TAG = re.compile(r"<(?:span|div|p)\b[^>]*>")
_TITLE = re.compile(r"(\btitle=)([\"'])(.*?)\2", re.S)
_CLASS = re.compile(r"\bclass=([\"'])(.*?)\1", re.S)
_CONF = re.compile(r"\bx_wconf\s+(\d+(?:\.\d+)?)")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def confident_words(hocr):
    """Count words read with at least MIN_CONFIDENCE and MIN_LETTERS letters. No word list is needed."""
    count = 0
    for tag in _START_TAG.finditer(hocr):
        text = tag.group(0)
        classes = _CLASS.search(text)
        if not classes or 'ocrx_word' not in classes.group(2).split():
            continue
        title = _TITLE.search(text)
        conf = _CONF.search(title.group(3)) if title else None
        end = hocr.find('</span>', tag.end())
        if conf is None or end < 0 or float(conf.group(1)) < MIN_CONFIDENCE:
            continue
        plain = html.unescape(re.sub(r"<[^>]+>", '', hocr[tag.end():end]))
        if sum(1 for ch in plain if ch.isalpha()) >= MIN_LETTERS:
            count += 1
    return count


def choose_turn(scores):
    """scores: {turn: confident word count}. Returns (turn, reason).

    Tesseract reads text that is upright and text that sits 90 degrees clockwise of upright, so a page that reads well in two
    neighbouring turns is really upright in the later one. The page stays as it is when it is already upright, or when no
    turn reads clearly better than turn 0.
    """
    if sorted(scores) != list(TURNS) or any(type(v) is not int or v < 0 for v in scores.values()):
        raise ValueError('Turn scores must be non-negative integers for 0, 90, 180 and 270.')
    top = max(scores.values())
    if top < MIN_WORDS:
        return 0, 'kept'
    near = [t for t in TURNS if scores[t] >= TIE * top]
    upright = [t for t in near if scores[(t - 90) % 360] >= TIE * top]
    if upright and len(near) < len(TURNS):
        pick = max(upright, key=lambda t: (scores[t], -TURNS.index(t)))
        pair = (pick, (pick - 90) % 360)
        rest = max([scores[t] for t in TURNS if t not in pair] or [0])
        if top >= MIN_GAIN * max(rest, 1):
            return pick, ('kept' if pick == 0 else 'upright-pair')
    best = max(near, key=lambda t: (scores[t], -TURNS.index(t)))
    if best != 0 and top >= MIN_GAIN * max(scores[0], 1):
        return best, 'best'
    return 0, 'kept'


def placement_matrix(turn, width, height, layer_width, layer_height):
    """PDF matrix taking the text page made from the turned picture back onto the original page.

    width, height: the ORIGINAL page picture in points. layer_width, layer_height: the text page's own size in points.
    The turned picture is the original rotated counter-clockwise by `turn` degrees.
    """
    turned_w, turned_h = (height, width) if turn in (90, 270) else (width, height)
    sx, sy = turned_w / layer_width, turned_h / layer_height
    if turn == 0:
        a, b, c, d, e, f = 1, 0, 0, 1, 0, 0
    elif turn == 90:
        a, b, c, d, e, f = 0, -1, 1, 0, 0, height
    elif turn == 180:
        a, b, c, d, e, f = -1, 0, 0, -1, width, height
    elif turn == 270:
        a, b, c, d, e, f = 0, 1, -1, 0, width, 0
    else:
        raise ValueError('Only right-angle turns are supported.')
    return [a * sx, b * sx, c * sy, d * sy, e, f]


def explicit_to_unicode(codes):
    """A ToUnicode map listing exactly the two-byte codes used (identity), instead of one 0000-FFFF range.

    veraPDF rejects glyphs outside ASCII when the glyphless font carries the single giant range.
    """
    codes = sorted(set(codes))
    if len(codes) > MAX_CODES:
        raise ValueError('Too many distinct text codes for a bounded character map.')
    lines = ['/CIDInit /ProcSet findresource begin', '12 dict begin', 'begincmap', '/CIDSystemInfo',
             '<< /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def', '/CMapName /Adobe-Identity-UCS def', '/CMapType 2 def',
             '1 begincodespacerange', '<0000> <FFFF>', 'endcodespacerange']
    for k in range(0, len(codes), 100):
        chunk = codes[k:k + 100]
        lines.append('%d beginbfchar' % len(chunk))
        lines += ['<%04X> <%04X>' % (c, c) for c in chunk]
        lines.append('endbfchar')
    lines += ['endcmap', 'CMapName currentdict /CMap defineresource pop', 'end', 'end']
    return '\n'.join(lines).encode('ascii')


def _carry(target, item):
    """Copy a direct object tree into another PDF, copying every indirect object it points to."""
    if getattr(item, 'is_indirect', False):
        return target.copy_foreign(item)
    if isinstance(item, pikepdf.Dictionary):
        return pikepdf.Dictionary({key: _carry(target, value) for key, value in item.items()})
    if isinstance(item, pikepdf.Array):
        return pikepdf.Array([_carry(target, value) for value in item])
    return item


def place_text_layer(layer_pdf, output_pdf, turn):
    """Write a one-page PDF with Tesseract's invisible text page placed back in the ORIGINAL orientation.

    The page size is the text page's own size turned back (swapped for 90 and 270). The text content is inlined (no Form
    XObject) and its font map is made explicit."""
    if turn not in TURNS:
        raise ValueError('Only right-angle turns are supported.')
    with pikepdf.open(layer_pdf) as source:
        page = source.pages[0]
        box = [float(v) for v in page.MediaBox]
        layer_width, layer_height = box[2] - box[0], box[3] - box[1]
        if layer_width <= 0 or layer_height <= 0:
            raise ValueError('The text page has no size.')
        width, height = (layer_height, layer_width) if turn in (90, 270) else (layer_width, layer_height)
        matrix = placement_matrix(turn, width, height, layer_width, layer_height)
        if '/Contents' not in page:
            content = b''
        elif isinstance(page.Contents, pikepdf.Array):
            content = b'\n'.join(s.read_bytes() for s in page.Contents)
        else:
            content = page.Contents.read_bytes()
        codes = set()
        for ins in pikepdf.parse_content_stream(page):
            operands = ins.operands[0] if str(ins.operator) == 'TJ' else ins.operands[:1] if str(ins.operator) == 'Tj' else []
            for item in operands:
                if isinstance(item, pikepdf.String):
                    raw = bytes(item)
                    codes.update((raw[i] << 8) | raw[i + 1] for i in range(0, len(raw) - 1, 2))
        with pikepdf.new() as out:
            out.add_blank_page(page_size=(width, height))
            target = out.pages[0]
            if '/Resources' in page:
                target.Resources = _carry(out, page.Resources)
                fonts = target.Resources.get('/Font')
                for font in (fonts.values() if fonts is not None else []):
                    if '/ToUnicode' in font:
                        font['/ToUnicode'] = out.make_stream(explicit_to_unicode(codes))
            head = ('q\n%s cm\n' % ' '.join('%.6f' % v for v in matrix)).encode('ascii')
            target.Contents = out.make_stream(head + content + b'\nQ\n')
            out.save(output_pdf, deterministic_id=True)


def validate_pages(directory, required_pages, binding, source_sha256, page_count):
    """Read and check the fixed plugin's per-page evidence; any unreadable or unbound proof fails closed."""
    directory = Path(directory)
    required = set(required_pages)
    pages = []
    for path in sorted(directory.glob('*.json')):
        if path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise ValueError('Turn recognition evidence is too large.')
        proof = json.loads(path.read_text(encoding='utf-8'))
        scores = proof.get('trial_scores') if isinstance(proof, dict) else None
        if (not isinstance(proof, dict) or proof.get('schema') != SCHEMA or proof.get('profile') != 'turns' or proof.get('version') != VERSION
                or type(proof.get('page')) is not int or not 1 <= proof['page'] <= page_count or path.name != f"{proof['page']:06d}.json"
                or proof.get('adapter_source_sha256') != source_sha256 or proof.get('turn_ccw') not in TURNS
                or not isinstance(scores, dict) or sorted(scores) != sorted(str(t) for t in TURNS)
                or any(type(v) is not int or v < 0 for v in scores.values())
                or any(proof.get(key) != value for key, value in binding.items())):
            raise ValueError('Turn recognition evidence is invalid or not bound to this implementation and source.')
        if choose_turn({int(k): v for k, v in scores.items()})[0] != proof['turn_ccw']:
            raise ValueError('Turn recognition evidence does not follow the fixed turn rule.')
        pages.append({**proof, 'path': str(path), 'sha256': digest(path)})
    if {p['page'] for p in pages} != required:
        raise ValueError('Turn recognition evidence is incomplete.')
    return pages
