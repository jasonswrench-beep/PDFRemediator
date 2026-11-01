"""How surely the text recognition read each scanned page.

Tesseract gives every word it reads a confidence from 0 to 100. This module counts, page by page, how many of the words
were read with high confidence, and names the pages where that share is low or where almost no words were found. Those are the
pages most likely to hold misread words, so a person should compare them with the page picture first.

This is a mechanical signal, never accuracy or accessibility approval: a confident word can still be wrong, and a page that
is not listed has not been checked. The scan and the text layer are never changed here; the module only reads numbers.
"""
from pathlib import Path
import hashlib
import html
import json
import re

VERSION = 'local-reading-confidence-1'
SCHEMA = 'phase1-ocr-confidence-1'
POLICY = 'tesseract-word-confidence-1'
SURE = 80            # a word read with at least this confidence (0-100) counts as sure
MIN_LETTERS = 3      # shorter words, numbers and marks are not counted
MIN_WORDS = 8        # fewer counted words than this cannot be judged by share
POOR_BELOW = 0.60    # under this share of sure words: many words are probably misread
CHECK_BELOW = 0.90   # under this share: some words are probably misread (clean scans measured 92-100%)
MAX_EVIDENCE_BYTES = 100_000
MAX_LISTED = 15
ENV_KEYS = ('PDF_REMEDIATOR_CONFIDENCE_EVIDENCE', 'PDF_REMEDIATOR_CONFIDENCE_SOURCE_SHA256')
# Lower number = looked at first.
ORDER = {'no-words': 0, 'little-text': 1, 'poor': 2, 'check': 3}

_START_TAG = re.compile(r"<(?:span|div|p)\b[^>]*>")
_TITLE = re.compile(r"(\btitle=)([\"'])(.*?)\2", re.S)
_CLASS = re.compile(r"\bclass=([\"'])(.*?)\1", re.S)
_CONF = re.compile(r"\bx_wconf\s+(\d+(?:\.\d+)?)")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hocr_words(hocr):
    """(text, confidence) for every word in Tesseract's hOCR page."""
    words = []
    for tag in _START_TAG.finditer(hocr):
        text = tag.group(0)
        classes = _CLASS.search(text)
        if not classes or 'ocrx_word' not in classes.group(2).split():
            continue
        title = _TITLE.search(text)
        conf = _CONF.search(title.group(3)) if title else None
        end = hocr.find('</span>', tag.end())
        if conf is None or end < 0:
            continue
        words.append((html.unescape(re.sub(r"<[^>]+>", '', hocr[tag.end():end])), float(conf.group(1))))
    return words


def tsv_words(tsv):
    """(text, confidence) for every word row (level 5) in Tesseract's tab-separated page."""
    words = []
    for line in tsv.splitlines()[1:]:
        fields = line.split('\t')
        if len(fields) < 12 or fields[0] != '5':
            continue
        try:
            conf = float(fields[10])
        except ValueError:
            continue
        if conf >= 0:
            words.append((fields[11], conf))
    return words


def measure(words):
    """Counts for one page. Only words with at least MIN_LETTERS letters are counted."""
    counted = [conf for text, conf in words if sum(1 for ch in text if ch.isalpha()) >= MIN_LETTERS]
    sure = sum(1 for conf in counted if conf >= SURE)
    return {'words': len(counted), 'sure_words': sure,
            'mean_confidence': round(sum(counted) / len(counted), 1) if counted else None}


def share(reading):
    return reading['sure_words'] / reading['words'] if reading['words'] else None


def grade(reading):
    """'confident', 'check', 'poor', 'little-text' (too few words to judge) or 'no-words'."""
    if reading['words'] == 0:
        return 'no-words'
    if reading['words'] < MIN_WORDS:
        return 'little-text'
    ratio = share(reading)
    return 'poor' if ratio < POOR_BELOW else 'check' if ratio < CHECK_BELOW else 'confident'


def valid_reading(reading):
    return (isinstance(reading, dict) and type(reading.get('words')) is int and type(reading.get('sure_words')) is int
            and 0 <= reading['sure_words'] <= reading['words'] <= 1_000_000
            and (reading.get('mean_confidence') is None
                 or type(reading['mean_confidence']) in (int, float) and 0 <= reading['mean_confidence'] <= 100))


def validate_pages(directory, required_pages, binding, source_sha256, page_count):
    """Read the fixed hook's per-page numbers. Anything unreadable, unbound or out of range is set aside and named.

    Returns {'pages': [{'page', 'reading'}], 'problems': [text]}. Never raises for bad evidence, because measuring must not
    be able to stop the reading itself; a page without a valid measurement is reported as not measured.
    """
    pages, problems = {}, []
    try:
        paths = sorted(Path(directory).glob('*.json'))
    except OSError as error:
        return {'pages': [], 'problems': ['The confidence folder could not be read (%s).' % type(error).__name__]}
    for path in paths:
        try:
            if path.stat().st_size > MAX_EVIDENCE_BYTES:
                raise ValueError('too large')
            proof = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(proof, dict) or proof.get('schema') != SCHEMA or proof.get('version') != VERSION
                    or type(proof.get('page')) is not int or not 1 <= proof['page'] <= page_count
                    or path.name != f"{proof['page']:06d}.json" or proof.get('adapter_source_sha256') != source_sha256
                    or any(proof.get(key) != value for key, value in binding.items()) or not valid_reading(proof.get('reading'))):
                raise ValueError('not bound to this implementation and source')
        except (OSError, ValueError, TypeError) as error:
            problems.append('%s: %s' % (path.name, error))
            continue
        pages[proof['page']] = proof['reading']
    return {'pages': [{'page': n, 'reading': pages[n]} for n in sorted(pages) if n in set(required_pages)], 'problems': problems}


def summarise(measured, required_pages, layout):
    """The record kept in the run report.

    measured: [{'page', 'reading'}] for pages with a valid measurement; required_pages: every page the reading was meant to cover.
    """
    by_page = {item['page']: item['reading'] for item in measured}
    rows = []
    for number in sorted(set(required_pages)):
        if number in by_page:
            reading = by_page[number]
            ratio = share(reading)
            rows.append({'page': number, **reading, 'share_sure': None if ratio is None else round(ratio, 3), 'grade': grade(reading)})
    missing = sorted(set(required_pages) - set(by_page))
    flagged = sorted((row for row in rows if row['grade'] != 'confident'),
                     key=lambda row: (ORDER[row['grade']], row['share_sure'] if row['share_sure'] is not None else 0, row['page']))
    status = 'unavailable' if not rows else 'partial' if missing else 'measured'
    return {'status': status, 'policy': POLICY, 'version': VERSION, 'layout': layout,
            'rule': {'sure_at_least': SURE, 'counts_words_of_at_least_letters': MIN_LETTERS, 'few_words_below': MIN_WORDS,
                     'many_unsure_below': POOR_BELOW, 'some_unsure_below': CHECK_BELOW},
            'pages': rows, 'flagged_pages': [row['page'] for row in flagged], 'not_measured_pages': missing,
            'scope': 'Tesseract word confidence only. It is a guide to where misread words are likely, never a check that the text is right.'}


def _percent(row):
    # Rounded down, so a page listed for being under the line never reads as sitting on it.
    return '%d%%' % (100 * row['sure_words'] // row['words'])


def review_item(summary):
    """The required review item for the pages that need a closer look, or None when every page was read with confidence."""
    if not isinstance(summary, dict) or summary.get('status') not in ('measured', 'partial', 'unavailable'):
        return None
    rows = {row['page']: row for row in summary['pages']}
    flagged = [rows[n] for n in summary['flagged_pages']]
    missing = summary.get('not_measured_pages', [])
    if not flagged and not missing:
        return None
    groups = []
    for kind, lead in (('poor', 'Many words were unsure'), ('check', 'Some words were unsure'),
                       ('little-text', 'Too little text to judge'), ('no-words', 'No words were found')):
        rows_of_kind = [row for row in flagged if row['grade'] == kind]
        if not rows_of_kind:
            continue
        if kind in ('poor', 'check'):
            names = ['page %d (%s of its words were read confidently)' % (row['page'], _percent(row)) for row in rows_of_kind]
        elif kind == 'little-text':
            names = ['page %d (%d word%s)' % (row['page'], row['words'], '' if row['words'] == 1 else 's') for row in rows_of_kind]
        else:
            names = ['page %d' % row['page'] for row in rows_of_kind]
        groups.append((lead, names))
    if missing:
        groups.append(('Reading confidence could not be measured', ['page %d' % n for n in missing]))
    shown, text = 0, []
    for lead, names in groups:
        room = MAX_LISTED - shown
        if room <= 0:
            text.append('%s: and %d more (see the evidence).' % (lead.lower(), len(names)))
            continue
        piece = names[:room]
        shown += len(piece)
        text.append('%s: %s%s.' % (lead, ', '.join(piece), '' if len(names) <= room else ' and %d more (see the evidence)' % (len(names) - room)))
    first = (flagged[0]['page'] if flagged else missing[0])
    return {'id': 'ocr-pages-read-unsurely', 'category': 'image-and-ocr',
            'subject': 'Compare the scanned pages the text recognition read least surely',
            'detail': ('The text recognition rates how sure it is of each word it reads. These pages are the ones most likely to hold misread words, '
                       'which a screen reader would then speak wrongly. '+' '.join(text)+' Compare the text of each listed page with the page picture, '
                       'starting with the first one listed. Correct misread words, or scan the page again more clearly and run it again. Pages that are not listed '
                       'were read with more confidence, which is still not a check that they are right, so the general review of scanned text stays required.'),
            'required': True, 'status': 'pending', 'page': first,
            'evidence': {'policy': summary['policy'], 'rule': summary['rule'], 'flagged': [rows[n] for n in summary['flagged_pages']],
                         'not_measured_pages': list(missing), 'pages_read': len(summary['pages'])}}
