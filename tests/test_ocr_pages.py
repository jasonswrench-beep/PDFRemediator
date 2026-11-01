"""Selective OCR policy controls; no OCR subprocess or PDF is executed here."""
from copy import deepcopy

import pytest

from pdf_remediator.ocr_pages import PageSelectionRefusal, check_textless_coverage, select_textless_pages


def authored_page(number, kind='scanned', characters=0, text_paints=0):
    return {'page': number, 'class': kind, 'text_characters': characters,
            'content': {'image_objects': 1 if kind in ('scanned', 'mixed') else 0,
                        'counts': {'text_paints': text_paints}, 'errors': [], 'warnings': []}}


def authored_document(*pages):
    return {'page_count': len(pages), 'pages': list(pages)}


def source_with_cover_and_existing_text():
    # Authored policy control matching the shape of a scanned cover followed
    # by two text-bearing image pages. These are not recognized PDF words.
    return authored_document(authored_page(1), authored_page(2, 'mixed', 100, 25),
                             authored_page(3, 'mixed', 180, 40))


def authored_completion():
    before = source_with_cover_and_existing_text()
    after = deepcopy(before)
    after['pages'][0].update({'class': 'mixed', 'text_characters': 17})
    fidelity = {'pages': [{'page': 1, 'text': {'removed_tokens': 0, 'added_tokens': 3}},
                          {'page': 2, 'text': {'removed_tokens': 0, 'added_tokens': 0}},
                          {'page': 3, 'text': {'removed_tokens': 0, 'added_tokens': 0}}]}
    return select_textless_pages(before), fidelity, after


def test_mixed_document_selects_scanned_cover_and_excludes_existing_text_pages():
    selection = select_textless_pages(source_with_cover_and_existing_text())
    assert selection['requested_mode'] == 'textless' and selection['native_mode'] == 'skip'
    assert selection['selected_pages'] == [1] and selection['excluded_pages'] == [2, 3]
    assert selection['native_page_clause'] == '1'


def test_range_clause_is_source_ordered_and_never_includes_excluded_text():
    source = authored_document(*(authored_page(n, 'text', 20, 3) if n in (4, 6) else authored_page(n)
                                 for n in range(1, 10)))
    selection = select_textless_pages(source)
    assert selection['native_page_clause'] == '1-3,5,7-9'
    assert selection['excluded_pages'] == [4, 6]


def test_true_mixed_content_without_wholly_scanned_pages_is_explicitly_refused():
    # Digital heading plus an image is not permission to replace any old text.
    with pytest.raises(PageSelectionRefusal, match='No wholly scanned pages'):
        select_textless_pages(authored_document(authored_page(1, 'mixed', 30, 5)))


@pytest.mark.parametrize('change', ['unmapped-paints', 'whitespace-characters', 'parse-error', 'parse-warning',
                                  'missing-content', 'missing-paint-count', 'negative-paints', 'boolean-paints', 'no-image'])
def test_poor_extraction_or_ambiguous_painting_never_authorizes_page_replacement(change):
    source = authored_document(authored_page(1))
    page = source['pages'][0]
    if change == 'unmapped-paints':
        page['content']['counts']['text_paints'] = 4
    elif change == 'whitespace-characters':
        page['text_characters'] = 1
    elif change == 'parse-error':
        page['content']['errors'] = ['Authored undecodable Form stream']
    elif change == 'parse-warning':
        page['content']['warnings'] = ['Authored uncertain page inventory']
    elif change == 'missing-content':
        page.pop('content')
    elif change == 'missing-paint-count':
        page['content']['counts'].pop('text_paints')
    elif change == 'negative-paints':
        page['content']['counts']['text_paints'] = -1
    elif change == 'boolean-paints':
        page['content']['counts']['text_paints'] = False
    elif change == 'no-image':
        page['content']['image_objects'] = 0
    with pytest.raises(PageSelectionRefusal, match='not proven wholly scanned'):
        select_textless_pages(source)


@pytest.mark.parametrize('change', ['missing-page', 'duplicate-page', 'wrong-count', 'boolean-page', 'inspection-error'])
def test_source_page_selection_requires_a_complete_unambiguous_inventory(change):
    source = source_with_cover_and_existing_text()
    if change == 'missing-page':
        source['pages'].pop()
    elif change == 'duplicate-page':
        source['pages'][1]['page'] = 1
    elif change == 'wrong-count':
        source['page_count'] = 4
    elif change == 'boolean-page':
        source['pages'][0]['page'] = True
    elif change == 'inspection-error':
        source['error'] = 'Authored parser refusal'
    with pytest.raises(PageSelectionRefusal):
        select_textless_pages(source)


def test_selected_page_can_gain_ocr_text_while_excluded_text_pages_remain_exact():
    selection, fidelity, after = authored_completion()
    proof = check_textless_coverage(selection, fidelity, after)
    assert proof['status'] == 'pass' and proof['errors'] == []
    assert [row['page'] for row in proof['selected_page_text']] == [1]
    assert [row['page'] for row in proof['excluded_page_token_deltas']] == [2, 3]


@pytest.mark.parametrize('page,field', [(2, 'removed_tokens'), (2, 'added_tokens'), (3, 'removed_tokens'), (3, 'added_tokens')])
def test_native_success_cannot_hide_text_additions_or_loss_on_excluded_pages(page, field):
    selection, fidelity, after = authored_completion()
    fidelity['pages'][page - 1]['text'][field] = 1
    proof = check_textless_coverage(selection, fidelity, after)
    assert proof['status'] == 'fail'
    assert any(f'Excluded page {page}' in error for error in proof['errors'])


@pytest.mark.parametrize('change', ['missing-compared-page', 'duplicate-compared-page', 'missing-output-page',
                                  'missing-token-count', 'boolean-token-count', 'empty-selection', 'wrong-native-mode'])
def test_selective_completion_requires_every_page_and_bound_explicit_native_route(change):
    selection, fidelity, after = authored_completion()
    if change == 'missing-compared-page':
        fidelity['pages'].pop()
    elif change == 'duplicate-compared-page':
        fidelity['pages'][1]['page'] = 1
    elif change == 'missing-output-page':
        after['pages'].pop()
    elif change == 'missing-token-count':
        fidelity['pages'][1]['text'].pop('added_tokens')
    elif change == 'boolean-token-count':
        fidelity['pages'][1]['text']['removed_tokens'] = False
    elif change == 'empty-selection':
        selection['selected_pages'] = []
    elif change == 'wrong-native-mode':
        selection['native_mode'] = 'redo'
    assert check_textless_coverage(selection, fidelity, after)['status'] == 'fail'


@pytest.mark.parametrize('kind,characters', [('scanned', 0), ('blank', 0), ('mixed', 0)])
def test_successful_native_exit_without_selectable_text_on_selected_page_is_not_ocr_success(kind, characters):
    selection, fidelity, after = authored_completion()
    after['pages'][0].update({'class': kind, 'text_characters': characters})
    proof = check_textless_coverage(selection, fidelity, after)
    assert proof['status'] == 'fail' and any('Selected page 1' in error for error in proof['errors'])
