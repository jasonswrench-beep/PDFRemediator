"""Source-only anchored crop contracts; no OCR engine or document fixtures."""
from copy import deepcopy
import math

import pytest
from PIL import Image, ImageDraw

from pdf_remediator import ocr_regions, ocr_rescue


def source():
    image = Image.new('RGB', (320, 200), 'white')
    draw = ImageDraw.Draw(image)
    # Two small groups and one larger sibling on one bottom-aligned line.
    for left in (20, 28, 36, 44, 52, 60, 80, 88):
        draw.rectangle((left, 110, left+4, 129), fill='black')
    for left in (110, 123, 136, 149, 162, 175):
        draw.rectangle((left, 90, left+7, 129), fill='black')
    return image


def accepted(**changes):
    return {'quad': [[110, 90], [183, 90], [183, 130], [110, 130]],
            'confidence': 95, 'angle': 0, 'attempt': 7, 'raw_word_index': 2,
            'raster_sha256': 'a'*64, **changes}


def test_source_component_line_proposes_both_small_groups_with_actual_large_sibling():
    with source() as image:
        result = ocr_rescue.proposals(image, [accepted()], ocr_regions)
    assert result['version'] == ocr_rescue.VERSION
    assert sorted(plan['component_count'] for plan in result['plans']) == [2, 6]
    for plan in result['plans']:
        assert plan['kind'] == 'anchored-native-height-group'
        assert plan['angle'] == 0 and plan['parent']['line_glyph_count'] == 14
        assert plan['anchor']['confidence'] == 95
        assert len(plan['anchor']['component_indices']) == 6
        assert plan['anchor']['reference'] == {'attempt': 7, 'raw_word_index': 2, 'raster_sha256': 'a'*64}
        assert plan['measurements']['uncovered_ink_fraction'] == 1
        assert len(plan['parent']['line_glyphs_sha256']) == len(plan['id']) == 64
        assert 'text' not in plan and all('text' not in glyph for glyph in plan['group'])


def test_native_source_and_existing_accepted_records_are_never_modified():
    words = [accepted()]
    before = deepcopy(words)
    with source() as image:
        pixels = image.tobytes()
        first = ocr_rescue.proposals(image, words, ocr_regions)
        assert image.tobytes() == pixels
        assert ocr_rescue.proposals(image, words, ocr_regions) == first
    assert words == before


@pytest.mark.parametrize('confidence', [70, 84])
def test_low_confidence_context_cannot_anchor_optional_rescue(confidence):
    with source() as image:
        assert not ocr_rescue.proposals(image, [accepted(confidence=confidence)], ocr_regions)['plans']


def test_isolated_small_ink_without_accepted_sibling_never_becomes_an_auto_rescue_plan():
    with source() as image:
        assert not ocr_rescue.proposals(image, [], ocr_regions)['plans']


def test_large_context_box_covering_the_new_group_is_not_a_distinct_sibling():
    with source() as image:
        word = accepted(quad=[[10, 80], [195, 80], [195, 140], [10, 140]])
        assert not ocr_rescue.proposals(image, [word], ocr_regions)['plans']


def test_distant_existing_word_cannot_anchor_a_different_native_component_line():
    with source() as image:
        word = accepted(quad=[[220, 20], [290, 20], [290, 60], [220, 60]])
        assert not ocr_rescue.proposals(image, [word], ocr_regions)['plans']


def test_blank_native_pixels_propose_nothing():
    with Image.new('RGB', (320, 200), 'white') as image:
        assert not ocr_rescue.proposals(image, [accepted()], ocr_regions)['plans']


@pytest.mark.parametrize('damage', ['missing-hash', 'invalid-hash', 'nan-quad', 'outside-quad', 'negative-attempt', 'bool-angle'])
def test_malformed_accepted_context_is_refused(damage):
    word = accepted()
    if damage == 'missing-hash':
        del word['raster_sha256']
    elif damage == 'invalid-hash':
        word['raster_sha256'] = 'g'*64
    elif damage == 'nan-quad':
        word['quad'][0][0] = math.nan
    elif damage == 'outside-quad':
        word['quad'][0][0] = -1
    elif damage == 'negative-attempt':
        word['attempt'] = -1
    else:
        word['angle'] = False
    with source() as image, pytest.raises(ValueError):
        ocr_rescue.proposals(image, [word], ocr_regions)


@pytest.mark.parametrize('mode', [None, 'L'])
def test_native_rgb_source_is_mandatory(mode):
    if mode is None:
        with pytest.raises(ValueError):
            ocr_rescue.proposals(None, [], ocr_regions)
    else:
        with Image.new(mode, (32, 32), 'white') as image, pytest.raises(ValueError):
            ocr_rescue.proposals(image, [], ocr_regions)


def test_source_pixel_bound_is_checked_before_any_region_work(monkeypatch):
    monkeypatch.setattr(ocr_rescue, 'MAX_INPUT_PIXELS', 100)
    monkeypatch.setattr(ocr_regions, 'regions', lambda image: pytest.fail('Oversized source reached region analysis'))
    with Image.new('RGB', (11, 10), 'white') as image, pytest.raises(ValueError):
        ocr_rescue.proposals(image, [], ocr_regions)


@pytest.mark.parametrize('limit,allowed', [(10404, True), (10403, False)])
def test_rotation_preallocation_has_an_explicit_pixel_boundary(monkeypatch, limit, allowed):
    monkeypatch.setattr(ocr_rescue, 'MAX_ROTATED_PIXELS', limit)
    if allowed:
        assert ocr_rescue.rotated_extent((100, 100), 0) == (102, 102)
    else:
        with pytest.raises(ocr_rescue.RescueLimit):
            ocr_rescue.rotated_extent((100, 100), 0)


def test_extreme_aspect_rotation_is_rejected_without_allocating_a_native_frame():
    with pytest.raises(ocr_rescue.RescueLimit):
        ocr_rescue.rotated_extent((40000, 1000), 45)


def test_canonical_crop_preserves_native_pixels_and_uses_measured_ink():
    with Image.new('RGB', (40, 40), 'white') as image:
        ImageDraw.Draw(image).rectangle((10, 12, 19, 21), fill='black')
        before = image.tobytes()
        assert ocr_rescue.canonical_crop(image, [5, 5, 30, 30]) == [8, 10, 22, 24]
        assert image.tobytes() == before


@pytest.mark.parametrize('limit,allowed', [(100, True), (99, False)])
def test_native_parent_crop_pixel_bound(monkeypatch, limit, allowed):
    monkeypatch.setattr(ocr_rescue, 'MAX_CROP_PIXELS', limit)
    with Image.new('RGB', (10, 10), 'black') as image:
        if allowed:
            assert ocr_rescue.canonical_crop(image, [0, 0, 10, 10]) == [0, 0, 10, 10]
        else:
            with pytest.raises(ocr_rescue.RescueLimit):
                ocr_rescue.canonical_crop(image, [0, 0, 10, 10])


def test_plan_limit_preserves_a_deterministic_prefix_and_reports_omissions(monkeypatch):
    monkeypatch.setattr(ocr_rescue, 'MAX_PLANS', 1)
    with source() as image:
        result = ocr_rescue.proposals(image, [accepted()], ocr_regions)
    assert len(result['plans']) == 1 and result['measurements']['omitted_by_plan_bound'] == 1


def test_parent_limit_can_stop_optional_work_without_touching_baseline(monkeypatch):
    monkeypatch.setattr(ocr_rescue, 'MAX_PARENTS', 0)
    words = [accepted()]
    with source() as image:
        result = ocr_rescue.proposals(image, words, ocr_regions)
    assert not result['plans'] and result['measurements']['native_parents_examined'] == 0
    assert words == [accepted()]


def test_detector_resource_refusal_keeps_optional_proposals_empty(monkeypatch):
    def limited(image):
        raise ocr_regions.RegionLimit('Named component-budget control')
    monkeypatch.setattr(ocr_regions, 'regions', limited)
    with source() as image:
        result = ocr_rescue.proposals(image, [accepted()], ocr_regions)
    assert not result['plans'] and result['measurements']['skipped'] == {'region-limit': 1}


def test_many_native_groups_stop_at_global_context_budget_without_modifying_source(monkeypatch):
    words = [accepted(attempt=index, quad=[[x, y+160*index] for x, y in accepted()['quad']]) for index in range(4)]
    words += [accepted(attempt=100+index, quad=[[220, 20], [290, 20], [290, 60], [220, 60]]) for index in range(16)]
    before = deepcopy(words)
    with Image.new('RGB', (320, 800), 'white') as image, source() as row:
        for index in range(4):
            image.paste(row, (0, 160*index))
        pixels = image.tobytes()
        full = ocr_rescue.proposals(image, words, ocr_regions)
        observed = []
        inside = ocr_rescue._inside

        def counted_inside(point, quad):
            observed.append((point, quad))
            return inside(point, quad)

        monkeypatch.setattr(ocr_rescue, '_inside', counted_inside)
        monkeypatch.setattr(ocr_rescue, 'MAX_CONTEXT_WORK', 100)
        limited = ocr_rescue.proposals(image, words, ocr_regions)
        assert image.tobytes() == pixels
        assert words == before
        assert limited['measurements']['context_budget_exhausted']
        assert limited['measurements']['skipped']['context-work-budget'] == 1
        assert limited['measurements']['context_work'] == 100
        assert limited['measurements']['context_quad_tests'] == len(observed) <= 100
        assert limited['measurements']['context_work'] == sum(limited['measurements']['context_work_by_kind'].values())
        assert 0 < len(limited['plans']) < len(full['plans'])
        assert all(plan in full['plans'] for plan in limited['plans'])
        observed.clear()
        assert ocr_rescue.proposals(image, words, ocr_regions) == limited
        assert limited['measurements']['context_quad_tests'] == len(observed)


def test_empty_height_context_does_not_rescan_thousands_of_accepted_words(monkeypatch):
    words = [accepted(attempt=index) for index in range(ocr_rescue.MAX_WORDS)]
    monkeypatch.setattr(ocr_rescue, 'MAX_CONTEXT_WORK', 5000)
    with Image.new('RGB', (320, 200), 'white') as image:
        draw = ImageDraw.Draw(image)
        for left in (20, 28, 36, 44, 52, 60, 80, 88, 110, 123, 136, 149, 162, 175):
            draw.rectangle((left, 110, left+4, 129), fill='black')
        before = image.tobytes()
        result = ocr_rescue.proposals(image, words, ocr_regions)
        assert image.tobytes() == before
    assert not result['plans'] and not result['measurements']['context_budget_exhausted']
    counts = result['measurements']['context_work_by_kind']
    assert counts['word_projections'] == ocr_rescue.MAX_WORDS
    assert counts.get('line_word_checks', 0) == counts.get('quad_tests', 0) == 0


@pytest.mark.parametrize('limit', [0, 1])
def test_context_budget_refuses_the_next_operation_instead_of_exceeding_it(monkeypatch, limit):
    monkeypatch.setattr(ocr_rescue, 'MAX_CONTEXT_WORK', limit)
    with source() as image:
        before = image.tobytes()
        result = ocr_rescue.proposals(image, [accepted()], ocr_regions)
        assert image.tobytes() == before
    assert not result['plans'] and result['measurements']['context_budget_exhausted']
    assert result['measurements']['context_work'] == limit
    assert result['measurements']['context_quad_tests'] == 0
    assert result['measurements']['skipped']['context-work-budget'] == 1
