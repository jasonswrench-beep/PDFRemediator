"""Missing character maps, derived from an OCR reading of the page itself.

Some PDFs draw their text with embedded two-byte fonts that carry no ToUnicode map, so a screen reader receives control
characters instead of letters. Here every drawn glyph is lined up with the word Tesseract reads at that spot, the readings
are voted per (font, code), and a ToUnicode map is written only for fonts whose votes agree, cover the font's glyphs and
predict held-out words. Nothing visible changes and no existing map is ever rewritten. The result is a derived
reading, not an authority: every use needs human review.
"""
from collections import Counter, defaultdict, namedtuple
from pathlib import Path
import ctypes
import hashlib
import os
import re
import unicodedata

import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from .doctor import ocr_availability, resolve_tools, sha
from .inspection import compare_fidelity
from .process import cancelled, local_environment, run

VERSION = 'local-ocr-character-mapping-1'
POLICY = 'ocr-derived-character-mapping'
DPI = 300
MAX_PAGES = 150
MAX_PIXELS = 40_000_000
MIN_WORD_CONFIDENCE = 70
MIN_VOTES = 2
MIN_AGREEMENT = 0.95
MIN_REPAIRED_SHARE = 0.9
CONTEXT_CONFIDENCE = 90
MIN_EVIDENCE_WORDS = 200
HOLDOUT_EVERY = 5
MIN_HOLDOUT_WORDS = 40
MIN_HOLDOUT_AGREEMENT = 0.95
MIN_ROUND_TRIP = 0.9
SPACE_MIN = 5
SPACE_SHARE = 0.9
OUTSIDE_LIMIT = 0.3
GRID = 64

Glyph = namedtuple('Glyph', 'x y code font')
Word = namedtuple('Word', 'x0 y0 x1 y1 text conf')
SHOW = ('Tj', 'TJ', "'", '"')


def candidate_name(font):
    """The BaseFont of a two-byte Identity font with no ToUnicode map, or None."""
    if not isinstance(font, pikepdf.Dictionary) or str(font.get('/Subtype', '')) != '/Type0' or '/ToUnicode' in font:
        return None
    if str(font.get('/Encoding', '')) not in ('/Identity-H', '/Identity-V') or not isinstance(font.get('/BaseFont'), pikepdf.Name):
        return None
    return str(font['/BaseFont'])[1:]


def candidate_fonts(pdf):
    found = defaultdict(list)
    for obj in pdf.objects:
        name = candidate_name(obj)
        if name:
            found[name].append(tuple(obj.objgen))
    return dict(found)


def content_codes(page, names):
    """Ordered (font, code) for every glyph shown through a candidate font, read from the content itself."""
    out = []

    def found(res):
        fonts = res.get('/Font') if res is not None else None
        return {str(k): candidate_name(v) for k, v in (fonts.items() if fonts is not None else []) if candidate_name(v) in names}

    def walk(holder, res, current, depth, seen):
        stack = []
        for ins in pikepdf.parse_content_stream(holder):
            op = str(getattr(ins, 'operator', ''))
            operands = ins.operands
            if op == 'q':
                stack.append(current)
            elif op == 'Q':
                current = stack.pop() if stack else current
            elif op == 'Tf' and operands:
                current = str(operands[0])
            elif op in SHOW:
                name = found(res).get(current)
                if name:
                    strings = ([bytes(x) for x in operands[0] if isinstance(x, pikepdf.String)] if op == 'TJ'
                               else [bytes(operands[-1])] if operands and isinstance(operands[-1], pikepdf.String) else [])
                    for raw in strings:
                        if len(raw) % 2:
                            raise ValueError('A two-byte font shows an odd number of bytes.')
                        out.extend((name, (raw[i] << 8) | raw[i + 1]) for i in range(0, len(raw), 2))
            elif op == 'Do' and operands and depth < 4:
                xobjects = res.get('/XObject') if res is not None else None
                form = xobjects.get(str(operands[0])) if xobjects is not None else None
                if form is not None and str(form.get('/Subtype', '')) == '/Form' and tuple(form.objgen) not in seen:
                    walk(form, form.get('/Resources', res), current, depth + 1, seen | {tuple(form.objgen)})

    walk(page.obj, page.resources, None, 0, frozenset())
    return out


def _font_name(textpage, index):
    flags = ctypes.c_int()
    size = pdfium_raw.FPDFText_GetFontInfo(textpage, index, None, 0, ctypes.byref(flags))
    if size <= 0:
        return ''
    buffer = ctypes.create_string_buffer(size + 1)
    pdfium_raw.FPDFText_GetFontInfo(textpage, index, buffer, size + 1, ctypes.byref(flags))
    return buffer.value.decode('latin-1')


def _pixels(page, x, y, scale, height):
    """A user-space point -> the displayed page's pixel (any /Rotate, any CropBox)."""
    cx0, cy0, cx1, cy1 = page.get_cropbox()
    w, h = cx1 - cx0, cy1 - cy0
    x, y = x - cx0, y - cy0
    xd, yd = {0: (x, y), 90: (y, w - x), 180: (w - x, h - y), 270: (h - y, x)}[page.get_rotation() % 360]
    return xd * scale, height - yd * scale


def drawn_glyphs(textpage, page, scale, height):
    """Every glyph pdfium reports (not synthesized), in drawing order, with its centre in picture pixels."""
    glyphs = []
    for i in range(textpage.count_chars()):
        if pdfium_raw.FPDFText_IsGenerated(textpage, i):
            continue
        left, bottom, right, top = textpage.get_charbox(i)
        x, y = _pixels(page, (left + right) / 2.0, (bottom + top) / 2.0, scale, height)
        glyphs.append(Glyph(x, y, pdfium_raw.FPDFText_GetUnicode(textpage, i), _font_name(textpage, i)))
    return glyphs


def align_omitted(content, glyphs, names):
    """pdfium leaves out some glyphs (spaces, for one). Match its candidate glyphs to the content in order.

    Returns the omitted (font, code) items as (index of the pdfium candidate glyph before it, font, code), or None when
    the two lists cannot be reconciled (the page is then not used)."""
    theirs = [(g.font, g.code) for g in glyphs if g.font in names]
    omitted, j = [], 0
    for k, item in enumerate(content):
        if j < len(theirs) and theirs[j] == item:
            j += 1
        else:
            omitted.append((j - 1, *item))
    if j != len(theirs):
        return None
    shown = Counter(g for g in theirs)
    if any(shown[(font, code)] for _, font, code in omitted):
        return None  # a code both drawn and left out cannot be told apart safely
    return omitted


def assign_words(glyphs, words):
    """For each word, the glyphs whose centres fall only inside it, left to right. Also each glyph's word index (or None)."""
    grid = defaultdict(list)
    for index, g in enumerate(glyphs):
        grid[(int(g.x // GRID), int(g.y // GRID))].append(index)
    owner = [None] * len(glyphs)
    inside = defaultdict(list)
    claimed = Counter()
    for w_index, w in enumerate(words):
        for cx in range(int(w.x0 // GRID), int(w.x1 // GRID) + 1):
            for cy in range(int(w.y0 // GRID), int(w.y1 // GRID) + 1):
                for g_index in grid.get((cx, cy), ()):
                    g = glyphs[g_index]
                    if w.x0 <= g.x <= w.x1 and w.y0 <= g.y <= w.y1:
                        inside[w_index].append(g_index)
                        claimed[g_index] += 1
    for w_index, members in inside.items():
        for g_index in members:
            if claimed[g_index] == 1:
                owner[g_index] = w_index
    return owner, {w: sorted((i for i in members if claimed[i] == 1), key=lambda i: glyphs[i].x) for w, members in inside.items()}


def acceptable(char):
    return len(char) == 1 and unicodedata.category(char)[0] in 'LNPS'


def decide(votes, space_votes, inside_votes, outside, census, names):
    """votes[(font, code)] -> Counter of characters (one vote per word); outside[(font, code)] -> glyphs sitting in no word box.

    A code whose glyphs mostly sit between words is space-like: it can become a space but never a letter."""
    maps = {name: {} for name in names}
    for key, total in census.items():
        font, code = key
        spaced, within = space_votes.get(key, 0), inside_votes.get(key, 0)
        if outside.get(key, 0) / max(1, total) >= OUTSIDE_LIMIT:
            if spaced >= SPACE_MIN and spaced / (spaced + within) >= SPACE_SHARE:
                maps[font][code] = ' '
            continue
        counted = votes.get(key)
        if counted:
            char, top = counted.most_common(1)[0]
            if sum(counted.values()) >= MIN_VOTES and top / sum(counted.values()) >= MIN_AGREEMENT and acceptable(char):
                maps[font][code] = char
    return maps


def add_context_readings(maps, training, names):
    """A rare code seldom reaches two votes. Accept it when it is the ONLY unknown glyph in a confidently read word and
    every such reading agrees, so the rest of the word is independent evidence."""
    readings = defaultdict(Counter)
    for keys, text, conf in training:
        unknown = [i for i, (font, code) in enumerate(keys) if font in names and code not in maps[font]]
        if len(unknown) == 1 and conf >= CONTEXT_CONFIDENCE:
            font, code = keys[unknown[0]]
            readings[(font, code)][text[unknown[0]]] += 1
    added = 0
    for (font, code), counted in readings.items():
        if len(counted) == 1 and acceptable(next(iter(counted))) and code not in maps[font]:
            maps[font][code] = next(iter(counted))
            added += 1
    return added


def font_facts(maps, census, names):
    facts = {}
    for font in names:
        occurrences = sum(n for (f, _), n in census.items() if f == font)
        covered = sum(n for (f, c), n in census.items() if f == font and c in maps[font])
        facts[font] = {'glyphs': occurrences, 'mapped_codes': len(maps[font]), 'distinct_codes': sum(1 for (f, _) in census if f == font),
                       'coverage': (covered / occurrences) if occurrences else 0.0}
    return facts


def to_unicode_cmap(mapping):
    """A ToUnicode map listing each mapped two-byte code, for a font that had none."""
    lines = ['/CIDInit /ProcSet findresource begin', '12 dict begin', 'begincmap', '/CIDSystemInfo',
             '<< /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def', '/CMapName /Adobe-Identity-UCS def', '/CMapType 2 def',
             '1 begincodespacerange', '<0000> <FFFF>', 'endcodespacerange']
    codes = sorted(mapping)
    for k in range(0, len(codes), 100):
        chunk = codes[k:k + 100]
        lines.append('%d beginbfchar' % len(chunk))
        lines += ['<%04X> <%s>' % (c, mapping[c].encode('utf-16-be').hex().upper()) for c in chunk]
        lines.append('endbfchar')
    lines += ['endcmap', 'CMapName currentdict /CMap defineresource pop', 'end', 'end']
    return '\n'.join(lines).encode('ascii')


def apply_maps(source, destination, maps):
    """Add a ToUnicode map to every candidate font with a decided map. Nothing else in the file is edited."""
    changed = []
    with pikepdf.open(source) as pdf:
        for obj in pdf.objects:
            name = candidate_name(obj)
            if name and maps.get(name):
                obj['/ToUnicode'] = pdf.make_stream(to_unicode_cmap(maps[name]))
                changed.append({'object': obj.objgen[0], 'font': name, 'codes': len(maps[name])})
        pdf.save(destination, deterministic_id=True)
    return changed


def parse_tsv(text):
    words = []
    for line in text.splitlines()[1:]:
        f = line.split('\t')
        if len(f) >= 12 and f[0] == '5' and f[11].strip():
            try:
                conf, x, y, w, h = float(f[10]), int(f[6]), int(f[7]), int(f[8]), int(f[9])
            except ValueError:
                continue
            if conf >= MIN_WORD_CONFIDENCE:
                words.append(Word(x, y, x + w, y + h, f[11].strip(), conf))
    return words


def is_heldout(page_index, word_index):
    """A fixed one-fifth of the clearly read words never vote; they are kept to test the finished map."""
    return int(hashlib.sha256(('%d|%d' % (page_index, word_index)).encode()).hexdigest(), 16) % HOLDOUT_EVERY == 0


def repair_from_ocr(source, destination, settings=None, workdir=None, cancel=None):
    """Derive missing ToUnicode maps for the source from an OCR reading, or refuse without publishing anything."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise FileExistsError('Character-map repair needs a distinct new output')
    directory = Path(workdir or destination.parent / 'ocr-mappings').resolve()
    directory.mkdir(parents=True, exist_ok=True)
    result = {'name': 'ocr-mappings', 'status': 'refused', 'policy': POLICY, 'version': VERSION, 'input_sha256': sha(source),
              'scope': 'Derived from an OCR reading of the page; no existing map is rewritten and no appearance changes.',
              'human_review_pending': ['Compare the repaired text with the page: every derived character map is an inference from OCR, not an authority.']}
    availability = ocr_availability(settings)
    if not availability['available']:
        return {**result, 'status': 'unsupported', 'error': availability['message']}
    tools = resolve_tools(settings=settings)
    with pikepdf.open(source) as pdf:
        names = candidate_fonts(pdf)
        if pdf.is_encrypted:
            return {**result, 'status': 'unsupported', 'error': 'Encrypted documents are not changed.'}
        pages_total = len(pdf.pages)
        if not names:
            return {**result, 'status': 'not-needed', 'reason': 'No two-byte font without a Unicode map was found.'}
        if pages_total > MAX_PAGES:
            return {**result, 'error': 'More than %d pages; process separate documents.' % MAX_PAGES}
        env = local_environment(tools['java_home'])
        env['PATH'] = str(tools['tesseract_dir']) + os.pathsep + env.get('PATH', '')
        env['TESSDATA_PREFIX'] = str(tools['tesseract_dir'] / 'tessdata')
        env['OMP_THREAD_LIMIT'] = '1'
        document = pdfium.PdfDocument(str(source))
        census = Counter()
        votes = defaultdict(Counter)
        space_votes, inside_votes, outside = Counter(), Counter(), Counter()
        heldout, training = [], []
        words_total = pages_read = 0
        pages_with_candidates = []
        for number, page in enumerate(pdf.pages):
            if cancelled(cancel):
                return {**result, 'status': 'cancelled', 'error': 'Cancelled.'}
            try:
                content = content_codes(page, set(names))
            except (ValueError, pikepdf.PdfError) as error:
                return {**result, 'error': 'Page %d content could not be read exactly: %s' % (number + 1, error)}
            if not content:
                continue
            pages_with_candidates.append(number + 1)
            census.update(content)
            pdfium_page = document[number]
            width, height = pdfium_page.get_size()
            scale = min(DPI / 72.0, (MAX_PIXELS / max(1.0, width * height)) ** 0.5)
            image = pdfium_page.render(scale=scale).to_pil().convert('L')
            picture = directory / f'page-{number + 1:04d}.png'
            image.save(picture)
            ran = run([tools['tesseract_dir'] / 'tesseract.exe' if os.name == 'nt' else tools['tesseract_dir'] / 'tesseract', str(picture), 'stdout',
                       '-l', 'eng', '--psm', '3', 'tsv'], directory / f'page-{number + 1:04d}', 300, 4 * 1024**3, cancel, env)
            if ran.get('status') != 'completed':
                return {**result, 'error': 'OCR reading of page %d did not complete.' % (number + 1)}
            words = parse_tsv(Path(ran['stdout']).read_text(encoding='utf-8', errors='replace'))
            glyphs = drawn_glyphs(pdfium_page.get_textpage(), pdfium_page, scale, image.size[1])
            omitted = align_omitted(content, glyphs, set(names))
            if omitted is None:
                return {**result, 'error': 'Page %d: the drawn glyphs cannot be matched to the page content exactly.' % (number + 1)}
            owner, members = assign_words(glyphs, words)
            pages_read += 1
            for w_index, word in enumerate(words):
                chosen = members.get(w_index, [])
                # A one-letter word is too easily paired with a neighbouring glyph (a space, say), so it never votes.
                if len(word.text) < 2 or len(chosen) != len(word.text):
                    continue
                words_total += 1
                pairs = [(glyphs[i], c) for i, c in zip(chosen, word.text)]
                if any(g.font not in names and unicodedata.normalize('NFC', chr(g.code)).lower() != c.lower() for g, c in pairs if g.code < 0x110000):
                    continue  # a known glyph disagrees with the reading: the word is misaligned or misread
                reading = {}
                if any(reading.setdefault((g.font, g.code), c) != c for g, c in pairs if g.font in names):
                    continue  # the same code read two ways inside one word
                if is_heldout(number, w_index):
                    heldout.append((number, [(g.font, g.code) for g, _ in pairs], word.text))
                    continue
                training.append(([(g.font, g.code) for g, _ in pairs], word.text, word.conf))
                for key, c in reading.items():
                    votes[key][c] += 1  # one vote per word and code
            candidate_positions = [i for i, g in enumerate(glyphs) if g.font in names]
            for after, font, code in omitted:
                before = candidate_positions[after] if 0 <= after < len(candidate_positions) else None
                following = candidate_positions[after + 1] if after + 1 < len(candidate_positions) else None
                outside[(font, code)] += 1
                left = owner[before] if before is not None else None
                right = owner[following] if following is not None else None
                if (left is not None or right is not None) and left != right:
                    space_votes[(font, code)] += 1
                else:
                    inside_votes[(font, code)] += 1
            for index, g in enumerate(glyphs):
                if g.font in names and owner[index] is None:
                    # A drawn glyph that sits in no word box is space-like: it lies between words, never inside one.
                    outside[(g.font, g.code)] += 1
                    left = owner[index - 1] if index > 0 else None
                    right = owner[index + 1] if index + 1 < len(glyphs) else None
                    if (left is not None or right is not None) and left != right:
                        space_votes[(g.font, g.code)] += 1
                    else:
                        inside_votes[(g.font, g.code)] += 1
    document.close()
    maps = decide(votes, space_votes, inside_votes, outside, census, set(names))
    context_added = add_context_readings(maps, training, set(names))
    facts = font_facts(maps, census, set(names))
    # Each decided code met the evidence rules on its own, so it is applied even in a font that stays incomplete.
    incomplete = [f for f in sorted(facts) if facts[f]['coverage'] < 1.0]
    repaired_share = sum(facts[f]['glyphs'] * facts[f]['coverage'] for f in facts) / max(1, sum(facts[f]['glyphs'] for f in facts))
    result.update(fonts=[{'font': f, **facts[f], 'complete': f not in incomplete} for f in sorted(facts)], pages_read=pages_read,
                  pages_with_candidate_glyphs=len(pages_with_candidates), evidence_words=words_total, heldout_words=len(heldout),
                  context_readings_added=context_added, glyph_share_repaired=repaired_share, fonts_left_incomplete=incomplete)
    if repaired_share < MIN_REPAIRED_SHARE:
        return {**result, 'error': 'Too few glyphs could be mapped with agreeing evidence (%.0f%% of the drawn glyphs).' % (100 * repaired_share)}
    if words_total < MIN_EVIDENCE_WORDS or len(heldout) < MIN_HOLDOUT_WORDS:
        return {**result, 'error': 'Not enough clearly read words to verify a map (%d words, %d held out).' % (words_total, len(heldout))}
    tested = matched = 0
    for _, keys, text in heldout:
        if all(f not in names or c in maps[f] for f, c in keys):
            tested += 1
            predicted = ''.join(maps[f][c] if f in names else chr(c) for f, c in keys)
            matched += unicodedata.normalize('NFC', predicted) == unicodedata.normalize('NFC', text)
    result['holdout'] = {'words_tested': tested, 'words_matching': matched, 'agreement': (matched / tested) if tested else 0.0}
    if tested < MIN_HOLDOUT_WORDS or result['holdout']['agreement'] < MIN_HOLDOUT_AGREEMENT:
        return {**result, 'error': 'The map does not reliably predict words it was not built from.'}
    partial = destination.with_name(destination.name + '.mapping-partial')
    if partial.exists():
        raise FileExistsError('Character-map checkpoint already exists')
    try:
        result['changes'] = apply_maps(source, partial, maps)
        fidelity = compare_fidelity(source, partial, cancel=cancel)
        pages = fidelity.get('pages', [])
        visible = bool(pages) and len(pages) == pages_total and all(
            all(p.get(k) == 'pass' for k in ('render_status', 'dimensions_status', 'page_boxes_status', 'annotations_status')) for p in pages)
        untouched = all(p.get('text', {}).get('removed_tokens', 1) == 0 and p.get('text', {}).get('added_tokens', 1) == 0
                        for n, p in enumerate(pages, 1) if n not in pages_with_candidates)
        other = [c for c in fidelity.get('checks', []) if c.get('id', c.get('name')) != 'all-page-render-and-content']
        result['visible_preservation'] = {'status': 'pass' if visible and untouched and all(c['status'] in ('pass', 'not-applicable') for c in other) else 'fail',
                                          'pages_compared': len(pages), 'pages_changed_in_text': pages_with_candidates,
                                          'policy': 'Every page picture, box and annotation identical; text may change only where a repaired font is drawn.'}
        if result['visible_preservation']['status'] != 'pass':
            return {**result, 'error': 'The repaired file differs visibly from the source.'}
        repaired = pdfium.PdfDocument(str(partial))
        found = total = 0
        try:
            for number in pages_with_candidates[:3]:
                tokens = set(re.findall(r'\w+', repaired[number - 1].get_textpage().get_text_range()))
                for _, keys, text in [h for h in heldout if h[0] == number - 1]:
                    for token in re.findall(r'\w+', text):
                        total += 1
                        found += token in tokens
        finally:
            repaired.close()
        result['round_trip'] = {'words_checked': total, 'words_found': found}
        if total < 20 or found / total < MIN_ROUND_TRIP:
            return {**result, 'error': 'The repaired file does not extract the words it was built to extract.'}
        partial.replace(destination)
        result.update(status='partial' if incomplete else 'pass', output_sha256=sha(destination), error=None)
        if incomplete:
            result['human_review_pending'].append('Some characters in these fonts could not be mapped and still read as control characters: ' + ', '.join(incomplete))
        return result
    finally:
        if partial.exists():
            partial.unlink()
