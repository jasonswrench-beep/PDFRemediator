"""A small, reproducible sample of scanned pages for a person to compare with the page picture.

The text recognition's own measurements say where misread words are likely; they never say that a page is right. This module
chooses a bounded set of pages a person should compare with the scan (the least surely read, the first and last, the busiest, and
a few drawn by the document's own fingerprint), and defines the record a person fills in for each: are the words accurate, is
nothing missing, is the reading order right. Nothing here reads a PDF or changes one, and nothing here approves anything.

Rules that keep it honest:
- The sample is computed only from the immutable run report and the exact result's SHA-256, so the same document and policy always
  give the same pages, each with the reason it was chosen.
- A record is human-entered: a named reviewer, a review date, one of pass / problem / not-checked for each of three checks, and
  notes. Machine, automatic or unnamed labels are refused.
- A record is bound to the exact result PDF, the exact sample and the page. Any change to those makes it stale; it is kept as a
  note, never as authority.
- Complete records (every sampled page, all three checks marked pass) are what the required scanned-text review needs before a
  person may approve it. They are not approval themselves, and they never create verified status.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
import re

POLICY = 'bounded-ocr-review-sample-1'
CHECKS = ('words_accurate', 'nothing_missing', 'reading_order_correct')
CHECK_LABELS = {'words_accurate': 'The words are accurate',
                'nothing_missing': 'Nothing is missing',
                'reading_order_correct': 'The reading order is right'}
VALUES = ('pass', 'problem', 'not-checked')
ORIGIN = 'human-entered'
MIN_SAMPLE = 3          # pools this small are sampled whole
MAX_SAMPLE = 10         # never more than this many pages
SAMPLE_SHARE = 0.2      # about one page in five
MAX_POOL = 100_000
MAX_NOTES = 2000
# A page graded below 'confident' is looked at first; lower number = earlier. Same order as the confidence screen.
GRADE_ORDER = {'no-words': 0, 'little-text': 1, 'poor': 2, 'check': 3}
MACHINE_NAMES = {'auto', 'automatic', 'ai', 'machine', 'model', 'system', 'ocr', 'tesseract', 'program', 'robot', 'bot', 'synthetic label'}
REASON_TEXT = {
    'read-least-surely': 'The text recognition was least sure of this page.',
    'first-scanned-page': 'First scanned page.',
    'last-scanned-page': 'Last scanned page.',
    'most-words': 'One of the pages with the most recognized words.',
    'drawn-from-document-fingerprint': 'Drawn from the document fingerprint so the choice cannot be steered.',
}
LIMITS = ('The sample is a guide to where to look, not proof about the pages it leaves out. A page that is not in the sample '
          'has not been checked. Pass on every sampled page is still the reviewer\'s own judgment, and it does not make the '
          'document accessible or verified.')
BETTER_SOURCE = ('If part of a page is cut off, faint or unreadable in the scan, the program cannot recreate the missing '
                 'content from its pixels. Get a clearer scan or the original document and process that instead.')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _is_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _baseline_pages(report):
    baseline = report.get('baseline') if isinstance(report.get('baseline'), dict) else {}
    rows = baseline.get('pages')
    if not isinstance(rows, list):
        rows = report.get('classification')
    return [row for row in rows or [] if isinstance(row, dict) and type(row.get('page')) is int and row['page'] > 0]


def _readings(report):
    for processor in report.get('processors') or []:
        if isinstance(processor, dict) and processor.get('name') == 'ocr':
            summary = processor.get('reading_confidence')
            if isinstance(summary, dict) and isinstance(summary.get('pages'), list):
                return {row['page']: row for row in summary['pages'] if isinstance(row, dict) and type(row.get('page')) is int and row['page'] > 0}
    return {}


def _result_characters(report):
    inspection = report.get('inspection') if isinstance(report.get('inspection'), dict) else {}
    return {row['page']: row.get('text_characters') for row in inspection.get('pages') or []
            if isinstance(row, dict) and type(row.get('page')) is int}


def quota(pool_size):
    """How many pages a pool of this size is sampled to."""
    if pool_size <= MIN_SAMPLE:
        return pool_size
    return min(pool_size, max(MIN_SAMPLE, min(MAX_SAMPLE, math.ceil(SAMPLE_SHARE * pool_size))))


def choose_sample(report, artifact_sha256):
    """The pages to compare, or None when the document has no scanned or recognized pages (or no exact result to bind to).

    Reproducible: only the report's page classification, the recognition's recorded measurements, the policy and the exact result
    fingerprint are used.
    """
    if not isinstance(report, dict) or not _is_sha(artifact_sha256):
        return None
    readings = _readings(report)
    characters = _result_characters(report)
    scanned = {row['page'] for row in _baseline_pages(report) if row.get('class') == 'scanned'}
    # A scanned page the result holds no text for has nothing to compare; the scan-text-layer check already blocks it.
    no_text = sorted(page for page in scanned if page not in readings and characters.get(page) == 0)
    pool = sorted((scanned | set(readings)) - set(no_text))
    if not pool or len(pool) > MAX_POOL:
        return None
    limit = quota(len(pool))
    chosen = {}

    def pick(page, reason, may_add=True):
        if page in chosen:
            if reason not in chosen[page]:
                chosen[page].append(reason)
        elif may_add and len(chosen) < limit:
            chosen[page] = [reason]

    def weakness(page):
        row = readings[page]
        share = row.get('share_sure')
        return (GRADE_ORDER[row['grade']], share if isinstance(share, (int, float)) else 0, page)

    flagged = sorted((page for page in readings if readings[page].get('grade') in GRADE_ORDER), key=weakness)
    for index, page in enumerate(flagged):
        pick(page, 'read-least-surely', may_add=index < math.ceil(limit / 2))
    pick(pool[0], 'first-scanned-page')
    pick(pool[-1], 'last-scanned-page')
    busiest = sorted((page for page in readings if type(readings[page].get('words')) is int), key=lambda page: (-readings[page]['words'], page))
    for page in busiest[:max(1, limit // 4)]:
        pick(page, 'most-words')
    for page in sorted(pool, key=lambda number: hashlib.sha256(f'{artifact_sha256}:{POLICY}:{number}'.encode()).hexdigest()):
        if page not in chosen:
            pick(page, 'drawn-from-document-fingerprint')
    pages = []
    for page in sorted(chosen):
        row = readings.get(page)
        entry = {'page': page, 'reasons': list(chosen[page]), 'scanned_in_original': page in scanned,
                 'result_text_characters': characters.get(page) if type(characters.get(page)) is int else None,
                 'reading': None}
        if row is not None:
            entry['reading'] = {key: row.get(key) for key in ('words', 'sure_words', 'mean_confidence', 'share_sure', 'grade')}
        pages.append(entry)
    return {'policy': POLICY, 'artifact_sha256': artifact_sha256, 'pool_pages': pool, 'limit': limit, 'pages': pages,
            'no_text_pages': no_text,
            'selection_sha256': _digest({'policy': POLICY, 'artifact_sha256': artifact_sha256, 'pool': pool, 'no_text': no_text,
                                         'pages': [(item['page'], item['reasons']) for item in pages]}),
            'checks': [{'id': key, 'label': CHECK_LABELS[key]} for key in CHECKS], 'limits': LIMITS,
            'better_source': BETTER_SOURCE, 'recognition_measured': bool(readings)}


def _date(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return True


def _name_problem(reviewer):
    if not isinstance(reviewer, str) or not reviewer.strip():
        return 'A named human reviewer is required.'
    if reviewer.strip().lower() in MACHINE_NAMES:
        return 'A machine or automatic label cannot be a reviewer; enter your own name.'
    return None


def record_digest(record, artifact_sha256, selection_sha256):
    body = {key: record.get(key) for key in ('page', 'checks', 'notes', 'reviewer', 'reviewed_at', 'origin')}
    return _digest({'policy': POLICY, 'record': body, 'artifact_sha256': artifact_sha256, 'selection_sha256': selection_sha256})


def _clean_checks(checks):
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        raise ValueError('Mark each of the three checks: ' + ', '.join(CHECK_LABELS[key].lower() for key in CHECKS) + '.')
    if any(value not in VALUES for value in checks.values()):
        raise ValueError('Each check must be pass, problem or not-checked.')
    return {key: checks[key] for key in CHECKS}


def make_record(sample, page, checks, notes, reviewer, reviewed_at):
    """One page's human record, bound to this exact sample and result. Raises ValueError with a plain reason."""
    if type(page) is not int or page not in {item['page'] for item in sample['pages']}:
        raise ValueError('That page is not in this review\'s sample. Record only the listed pages.')
    problem = _name_problem(reviewer)
    if problem:
        raise ValueError(problem)
    if not _date(reviewed_at):
        raise ValueError('Use an ISO review date or timestamp.')
    if not isinstance(notes, str) or len(notes) > MAX_NOTES or '\x00' in notes:
        raise ValueError('Notes must be plain text of at most %d characters.' % MAX_NOTES)
    record = {'page': page, 'checks': _clean_checks(checks), 'notes': notes.replace('\r\n', '\n').strip(), 'reviewer': reviewer.strip(),
              'reviewed_at': reviewed_at, 'origin': ORIGIN, 'policy': POLICY}
    if any(value == 'problem' for value in record['checks'].values()) and not record['notes']:
        raise ValueError('Say in the notes what is wrong on this page, so it can be corrected or the source replaced.')
    record['record_sha256'] = record_digest(record, sample['artifact_sha256'], sample['selection_sha256'])
    return record


def record_problems(sample, records):
    """Why these stored records cannot be trusted for this sample. An empty list means each record is genuine and bound."""
    problems = []
    if sample is None:
        return ['The recorded OCR sample no longer applies to this document.'] if records else []
    pages = {item['page'] for item in sample['pages']}
    seen = set()
    for record in records:
        if not isinstance(record, dict) or type(record.get('page')) is not int:
            problems.append('A sample record is malformed.')
            continue
        page = record['page']
        if page not in pages or page in seen:
            problems.append('Page %s has a record outside this sample or more than one.' % page)
            continue
        seen.add(page)
        try:
            _clean_checks(record.get('checks'))
        except ValueError:
            problems.append('Page %d has an invalid check.' % page)
            continue
        if (record.get('origin') != ORIGIN or record.get('policy') != POLICY or _name_problem(record.get('reviewer'))
                or not _date(record.get('reviewed_at')) or not isinstance(record.get('notes'), str)):
            problems.append('Page %d is not a genuine human record.' % page)
            continue
        if record.get('record_sha256') != record_digest(record, sample['artifact_sha256'], sample['selection_sha256']):
            problems.append('Page %d no longer matches its checks, reviewer or exact result.' % page)
    return problems


def status(sample, records):
    """Where the sample stands. 'satisfied' means every sampled page has a genuine record with all three checks marked pass."""
    if sample is None:
        return {'applies': False, 'satisfied': True, 'recorded_pages': [], 'missing_pages': [], 'problem_pages': [],
                'unchecked_pages': [], 'invalid': [], 'summary': 'This document has no scanned pages to sample.'}
    invalid = record_problems(sample, records)
    by_page = {record['page']: record for record in records if isinstance(record, dict) and type(record.get('page')) is int}
    sampled = [item['page'] for item in sample['pages']]
    recorded = [page for page in sampled if page in by_page]
    missing = [page for page in sampled if page not in by_page]
    problem_pages, unchecked = [], []
    for page in recorded:
        values = by_page[page].get('checks', {})
        if any(value == 'problem' for value in values.values()):
            problem_pages.append(page)
        elif any(value != 'pass' for value in values.values()):
            unchecked.append(page)
    satisfied = not invalid and not missing and not problem_pages and not unchecked
    if satisfied:
        summary = 'Every sampled page has your record with all three checks marked pass. You may now decide the scanned-text review yourself.'
    else:
        parts = []
        if missing:
            parts.append('not yet recorded: page%s %s' % ('' if len(missing) == 1 else 's', ', '.join(map(str, missing))))
        if unchecked:
            parts.append('has a check left as not-checked: page%s %s' % ('' if len(unchecked) == 1 else 's', ', '.join(map(str, unchecked))))
        if problem_pages:
            parts.append('marked as a problem: page%s %s' % ('' if len(problem_pages) == 1 else 's', ', '.join(map(str, problem_pages))))
        if invalid:
            parts.append('records that no longer match: ' + '; '.join(invalid))
        detail = '; '.join(parts)
        summary = 'The scanned-text review cannot be approved yet. ' + detail[:1].upper() + detail[1:] + '.'
    return {'applies': True, 'satisfied': satisfied, 'recorded_pages': recorded, 'missing_pages': missing, 'problem_pages': problem_pages,
            'unchecked_pages': unchecked, 'invalid': invalid, 'summary': summary}


def ledger_problem(report, manual, artifact_sha256):
    """Why a verification record must be refused for want of the sample's human records, or None when none are needed or all are there."""
    sample = choose_sample(report, artifact_sha256)
    if sample is None:
        return None
    manual = manual if isinstance(manual, dict) else {}
    recorded = manual.get('ocr_sample') if isinstance(manual.get('ocr_sample'), dict) else {}
    records = manual.get('ocr_sample_records')
    if recorded.get('selection_sha256') != sample['selection_sha256'] or not isinstance(records, list):
        return 'The scanned-page sample for this exact document has no human records. Record each sampled page in the review before verification.'
    state = status(sample, records)
    return None if state['satisfied'] else 'OCR sample records are incomplete or adverse. ' + state['summary']
