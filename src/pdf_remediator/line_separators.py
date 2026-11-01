"""Bounded preservation of source-extracted ASCII line separators.

Only terminal text in separate, reset text objects belonging to consecutive
MCIDs of the same plain paragraph is eligible. This makes no reading-order or
human-verification claim. Unsupported shapes are left unchanged. Independent
validation and every-page fidelity remain mandatory after this transformation.
"""
import re

import pikepdf
import pypdfium2 as pdfium


def _ascii_font(font):
    if str(font.get('/Subtype')) != '/TrueType' or '/Encoding' in font or '/ToUnicode' not in font:
        return False
    cmap = font.ToUnicode.read_bytes()
    if b'beginbfrange' in cmap or b'usecmap' in cmap:
        return False
    ranges = re.findall(rb'begincodespacerange\s*(.*?)\s*endcodespacerange', cmap, re.S)
    blocks = re.findall(rb'beginbfchar\s*(.*?)\s*endbfchar', cmap, re.S)
    if len(ranges) != 1 or re.sub(rb'\s+', b'', ranges[0]) != b'<00><7F>' or len(blocks) != 1:
        return False
    pairs = re.findall(rb'<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4})>', blocks[0])
    if len(pairs) != 128 or len({int(a, 16) for a, _ in pairs}) != 128:
        return False
    mappings = {int(a, 16): int(b, 16) for a, b in pairs}
    return all(mappings.get(code) == code for code in range(32, 127))


def preserve_line_separators(source, page_number, page, content, refs):
    """Return new stream bytes plus automatic records, or the unchanged stream.

    The caller has already proved source painting/resource equivalence. Require
    that equivalence again for text ownership through the supplied MCID map.
    Only source PDFium's unique literal line boundary supplies a separator.
    """
    instructions = list(pikepdf.parse_content_stream(page))
    forbidden = {'Do', 'Tc', 'Tw', 'Tz', 'Tr', 'Ts', "'", '"', 'TJ'}
    if any(str(i.operator) in forbidden or
           str(i.operator) == 'cm' and list(i.operands) != [1, 0, 0, 1, 0, 0]
           for i in instructions):
        return content, []
    # Accept only independently reset, single-show horizontal line objects.
    lines, start = [], None
    for index, item in enumerate(instructions):
        op = str(item.operator)
        if op == 'BT':
            if start is not None:
                return content, []
            start = index
        elif op == 'ET' and start is not None:
            block = instructions[start:index + 1]
            if [str(i.operator) for i in block] != ['BT', 'Tm', 'Tf', 'TL', 'BDC', 'Tj', 'EMC', 'T*', 'ET']:
                return content, []
            matrix, tf, marking, show = block[1], block[2], block[4], block[5]
            if list(matrix.operands[:4]) != [1, 0, 0, 1] or len(tf.operands) != 2:
                return content, []
            props = marking.operands[1]
            if not isinstance(props, pikepdf.Dictionary) or set(props.keys()) != {'/MCID'}:
                return content, []
            mcid = int(props.MCID)
            owner = refs.get((page_number, mcid))
            raw = bytes(show.operands[0])
            font = page.resources.get('/Font', {}).get(str(tf.operands[0]))
            if not raw or any(b < 32 or b > 126 for b in raw) or font is None or not _ascii_font(font):
                return content, []
            lines.append((start + 5, raw.decode('ascii'), mcid, owner,
                          tuple(matrix.operands[4:]), tuple(tf.operands)))
            start = None
    if start is not None or len(lines) < 2:
        return content, []
    with pdfium.PdfDocument(source) as document:
        source_page = document[page_number]
        textpage = source_page.get_textpage()
        try:
            text = textpage.get_text_range().replace('\r\n', '\n').replace('\r', '\n')
        finally:
            textpage.close()
            source_page.close()
    changes = []
    for left, right in zip(lines, lines[1:]):
        idx, a, mcid, owner, position, font = left
        _, b, next_mcid, next_owner, next_position, next_font = right
        if owner is None or next_owner is None or not owner.objgen[0] or owner.objgen != next_owner.objgen:
            continue
        if str(owner.get('/S')) != '/P' or any(key in owner for key in ('/ActualText', '/Alt', '/E')):
            continue
        ancestor, seen, substituted = owner, set(), False
        while isinstance(ancestor, pikepdf.Dictionary):
            identity = ancestor.objgen
            if identity in seen or any(key in ancestor for key in ('/ActualText', '/Alt', '/E')):
                substituted = True
                break
            seen.add(identity)
            ancestor = ancestor.get('/P')
        if substituted:
            continue
        kids = owner.get('/K')
        if not isinstance(kids, pikepdf.Array) or any(not isinstance(k, int) for k in kids):
            continue
        children = list(kids)
        if children.count(mcid) != 1 or children.count(next_mcid) != 1 or children.index(next_mcid) != children.index(mcid) + 1:
            continue
        if font != next_font or position[0] != next_position[0] or not 0 < position[1] - next_position[1] <= 2 * font[1]:
            continue
        # No hyphenation, punctuation, existing whitespace, non-ASCII or columns.
        if not re.search(r'[A-Za-z]{2}$', a) or not re.match(r'^[A-Za-z]{2}', b):
            continue
        boundary = a + '\n' + b
        if text.count(boundary) != 1 or text.count(a) != 1 or text.count(b) != 1:
            continue
        instructions[idx] = pikepdf.ContentStreamInstruction(
            [pikepdf.String(a.encode('ascii') + b' ')], pikepdf.Operator('Tj'))
        changes.append({'page': page_number + 1, 'mcid': mcid, 'next_mcid': next_mcid,
                        'origin': 'automatic-source-line-separator', 'human_verified': False})
    return (pikepdf.unparse_content_stream(instructions) if changes else content), changes
