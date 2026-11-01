"""Explicit OCR of wholly scanned pages while retaining text-bearing pages."""

VERSION = 'textless-pages-1'
MAX_PAGE_CLAUSE = 8192


class PageSelectionRefusal(ValueError):
    """The inspected source cannot support the requested textless-page route."""


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _page_list(inspection):
    pages = inspection.get('pages') if isinstance(inspection, dict) else None
    count = inspection.get('page_count') if isinstance(inspection, dict) else None
    if (inspection.get('error') if isinstance(inspection, dict) else True) or not _integer(count, 1) or not isinstance(pages, list):
        raise PageSelectionRefusal('Textless-page OCR requires a complete, successful page inspection.')
    if len(pages) != count or any(not isinstance(page, dict) or type(page.get('page')) is not int
                                 or page['page'] != number for number, page in enumerate(pages, 1)):
        raise PageSelectionRefusal('Textless-page OCR requires every source page exactly once in order.')
    return pages


def _clause(pages):
    parts = []
    first = previous = pages[0]
    for number in pages[1:]:
        if number != previous + 1:
            parts.append(str(first) if first == previous else f'{first}-{previous}')
            first = number
        previous = number
    parts.append(str(first) if first == previous else f'{first}-{previous}')
    value = ','.join(parts)
    if len(value) > MAX_PAGE_CLAUSE:
        raise PageSelectionRefusal('The selected page list exceeds the supported local command length; process separate source documents.')
    return value


def select_textless_pages(inspection):
    """Select only image-bearing pages with no extracted or painted text.

    A mixed document can contain wholly scanned and text-bearing pages. The
    latter remain excluded even if some of their images contain unread text.
    Poor extraction alone never authorizes replacement of existing text paints.
    """
    pages = _page_list(inspection)
    selected, excluded = [], []
    for page in pages:
        number, kind = page['page'], page.get('class')
        characters = page.get('text_characters')
        if kind not in ('scanned', 'mixed', 'text', 'blank') or not _integer(characters):
            raise PageSelectionRefusal(f'Page {number} has an unsupported or incomplete text classification.')
        if kind != 'scanned':
            excluded.append(number)
            continue
        content = page.get('content')
        counts = content.get('counts') if isinstance(content, dict) else None
        if (characters != 0 or not isinstance(counts, dict) or not _integer(counts.get('text_paints'))
                or counts['text_paints'] != 0 or not _integer(content.get('image_objects'), 1)
                or content.get('errors') != [] or content.get('warnings') != []):
            raise PageSelectionRefusal(f'Page {number} is not proven wholly scanned: existing or uncertain text must be preserved. Use source/manual repair.')
        selected.append(number)
    if not selected:
        raise PageSelectionRefusal('No wholly scanned pages are eligible. Existing text-bearing pages remain unchanged; use source/manual repair for text inside their images.')
    return {'version': VERSION, 'requested_mode': 'textless', 'native_mode': 'skip', 'page_count': len(pages),
            'selected_pages': selected, 'excluded_pages': excluded, 'native_page_clause': _clause(selected),
            'scope': 'OCR only the listed wholly scanned pages. Existing selectable text and text-bearing image pages are not re-recognized; their completeness still needs review.'}


def check_textless_coverage(selection, fidelity, output_inspection):
    """Require text on selected pages and exact token retention elsewhere.

    This adds a selective-page requirement to the unchanged whole-document
    preservation gate. It cannot waive pixels, geometry, annotations, navigation,
    tags, original tokens or any strict/supplemental validation requirement.
    """
    result = {'version': VERSION, 'status': 'fail', 'selected_pages': [], 'excluded_pages': [],
              'selected_page_text': [], 'excluded_page_token_deltas': [], 'errors': []}
    try:
        if not isinstance(selection, dict):
            raise PageSelectionRefusal('The textless-page selection record is missing.')
        count = selection.get('page_count')
        selected, excluded = selection.get('selected_pages'), selection.get('excluded_pages')
        if (selection.get('version') != VERSION or selection.get('requested_mode') != 'textless'
                or selection.get('native_mode') != 'skip' or not _integer(count, 1)
                or not isinstance(selected, list) or not selected or not isinstance(excluded, list)
                or any(not _integer(number, 1) or number > count for number in selected + excluded)
                or selected != sorted(set(selected)) or excluded != sorted(set(excluded))
                or set(selected) & set(excluded) or set(selected + excluded) != set(range(1, count + 1))
                or selection.get('native_page_clause') != _clause(selected)):
            raise PageSelectionRefusal('The recorded textless-page selection is inconsistent.')
        result.update(selected_pages=selected, excluded_pages=excluded)
        after = _page_list(output_inspection)
        compared = fidelity.get('pages') if isinstance(fidelity, dict) else None
        if (len(after) != count or not isinstance(fidelity, dict) or fidelity.get('error') or not isinstance(compared, list) or len(compared) != count
                or any(not isinstance(page, dict) or type(page.get('page')) is not int or page['page'] != number
                       for number, page in enumerate(compared, 1))):
            raise PageSelectionRefusal('Selective OCR must retain an all-page output and fidelity comparison.')
        for number in selected:
            page = after[number - 1]
            characters = page.get('text_characters')
            passed = page.get('class') in ('text', 'mixed') and _integer(characters, 1)
            result['selected_page_text'].append({'page': number, 'text_characters': characters, 'selectable_text_present': passed})
            if not passed:
                result['errors'].append(f'Selected page {number} still has no proven selectable text.')
        for number in excluded:
            text = compared[number - 1].get('text', {})
            if not isinstance(text, dict):
                raise PageSelectionRefusal(f'Excluded page {number} has no complete text comparison.')
            removed, added = text.get('removed_tokens'), text.get('added_tokens')
            passed = _integer(removed) and _integer(added) and removed == added == 0
            result['excluded_page_token_deltas'].append({'page': number, 'removed_tokens': removed,
                                                         'added_tokens': added, 'unchanged': passed})
            if not passed:
                result['errors'].append(f'Excluded page {number} gained or lost original selectable-text tokens.')
        result['status'] = 'pass' if not result['errors'] else 'fail'
    except (PageSelectionRefusal, TypeError, ValueError) as error:
        result['errors'].append(str(error))
    return result
