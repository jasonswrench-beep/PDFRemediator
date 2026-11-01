"""Native-raster policy contracts; no recognition engine or document fixtures."""
import copy
import math

import pytest
from PIL import Image

from pdf_remediator import ocr_angles as algorithm


SIZE = (320, 320)
CENTER = (160, 160)


def candidate(text, confidence, attempt, *, width=140, height=50,
              angle=0, center=CENTER, psm=7):
    """A complete, internally mapped native-shaped rectangular word record."""
    theta = math.radians(angle)
    cosine, sine = math.cos(theta), math.sin(theta)
    corners = [(-width / 2, -height / 2), (width / 2, -height / 2),
               (width / 2, height / 2), (-width / 2, height / 2)]
    quad = [[center[0] + cosine * x - sine * y,
             center[1] + sine * x + cosine * y] for x, y in corners]
    with Image.new('RGB', SIZE, 'white') as source:
        with source.rotate(angle, expand=True) as rotated:
            rotated_size = list(rotated.size)
    dx, dy = center[0] - SIZE[0] / 2, center[1] - SIZE[1] / 2
    rx = cosine * dx + sine * dy + rotated_size[0] / 2
    ry = -sine * dx + cosine * dy + rotated_size[1] / 2
    return {'text': text, 'confidence': confidence, 'attempt': attempt,
            'raw_word_index': 0, 'psm': psm, 'angle': angle,
            'raster_sha256': f'{attempt + 1:064x}',
            'box': [min(point[0] for point in quad), min(point[1] for point in quad),
                    max(point[0] for point in quad), max(point[1] for point in quad)],
            'quad': quad, 'rotated_box': [rx - width / 2, ry - height / 2,
                                         rx + width / 2, ry + height / 2],
            'rotated_size': rotated_size, 'working_size': list(SIZE),
            'scale': 1, 'height': height}


def pair(text, confidence, attempt, **geometry):
    return [candidate(text, confidence, attempt, psm=7, **geometry),
            candidate(text, confidence - 1, attempt + 1, psm=13, **geometry)]


def alternatives(*, large_text='Harbor', small_text='HARBOR',
                 small_confidence=74, large_angle=0, small_width=100,
                 small_height=20, small_center=CENTER):
    return (pair(large_text, 95, 0, angle=large_angle)
            + pair(small_text, small_confidence, 2, width=small_width,
                   height=small_height, center=small_center))


def pixels(count=80, value=0, extra=()):
    image = Image.new('RGB', SIZE, 'white')
    for number in range(count):
        image.putpixel((144 + number % 16, 156 + number // 16), (value,) * 3)
    for point in extra:
        image.putpixel(point, (value,) * 3)
    return image


def chosen(candidates, image):
    selected = algorithm.select_words(candidates, source_image=image)
    assert len(selected) == 1
    return selected[0]


def test_same_source_ink_prefers_tighter_qualified_native_candidate():
    candidates = alternatives(large_angle=15)
    with Image.new('RGB', SIZE, 'white') as blank:
        assert chosen(candidates, blank)['attempt'] == 0
    with pixels() as image:
        result = chosen(candidates, image)
    assert result['attempt'] == 2 and result['text'] == 'HARBOR'
    assert result['confidence'] == 74 and result['agreement_votes'] >= 2
    for key, value in candidates[2].items():
        assert result[key] == value


def test_native_source_image_is_a_required_keyword_argument():
    with pytest.raises(TypeError):
        algorithm.select_words([])


@pytest.mark.parametrize('mode', [None, 'L'])
def test_native_source_image_cannot_be_missing_or_silently_converted(mode):
    if mode is None:
        with pytest.raises(ValueError):
            algorithm.select_words([], source_image=None)
    else:
        with Image.new(mode, SIZE, 'white') as image, pytest.raises(ValueError):
            algorithm.select_words([], source_image=image)


def test_native_source_image_must_retain_the_existing_pixel_bound(monkeypatch):
    monkeypatch.setattr(algorithm, 'MAX_PIXELS', SIZE[0] * SIZE[1] - 1)
    with Image.new('RGB', SIZE, 'white') as image, pytest.raises(ValueError):
        algorithm.select_words([], source_image=image)


def test_source_fit_never_mutates_source_pixels_or_native_candidate_records():
    candidates = alternatives(large_angle=15)
    before = copy.deepcopy(candidates)
    with pixels() as image:
        raw = image.tobytes()
        chosen(candidates, image)
        assert image.tobytes() == raw and image.size == SIZE
    assert candidates == before


def test_equal_dark_pixel_counts_at_different_source_positions_are_not_equivalent():
    candidates = alternatives(small_center=(160, 184))
    with Image.new('RGB', SIZE, 'white') as image:
        # The large and small quads each cover 80 dark pixels, but none coincide.
        for y in (145, 186):
            for offset in range(80):
                image.putpixel((144 + offset % 16, y + offset // 16), (0, 0, 0))
        assert chosen(candidates, image)['attempt'] == 0


def test_footprints_use_oriented_quads_rather_than_their_axis_aligned_boxes():
    candidates = pair('Harbor', 95, 0, angle=45, height=20)
    candidates += pair('HARBOR', 74, 2, width=110, height=20)
    with Image.new('RGB', SIZE, 'white') as image:
        for number in range(80):
            # Both quads contain the central group. Only the horizontal quad
            # contains the second group, although both AABBs contain all ink.
            image.putpixel((156 + number % 8, 155 + number // 8), (0, 0, 0))
            image.putpixel((195 + number % 16, 156 + number // 16), (0, 0, 0))
        assert chosen(candidates, image)['attempt'] == 0


def test_area_comparison_uses_quad_area_rather_than_axis_aligned_envelope():
    candidates = pair('Harbor', 95, 0, angle=45, height=20)
    # The horizontal quad has a smaller AABB but a much larger actual area.
    candidates += pair('HARBOR', 74, 2, width=110, height=50)
    with Image.new('RGB', SIZE, 'white') as image:
        for number in range(80):
            image.putpixel((156 + number % 8, 155 + number // 8), (0, 0, 0))
        assert chosen(candidates, image)['attempt'] == 0


def test_distant_repeated_word_remains_a_separate_native_occurrence():
    candidates = pair('Harbor', 95, 0, width=100, height=40, center=(70, 160))
    candidates += pair('HARBOR', 74, 2, width=60, height=20, center=(250, 160))
    with Image.new('RGB', SIZE, 'white') as image:
        for center in (70, 250):
            for number in range(80):
                image.putpixel((center - 16 + number % 16, 156 + number // 16), (0, 0, 0))
        selected = algorithm.select_words(candidates, source_image=image)
    assert [word['attempt'] for word in selected] == [0, 2]


@pytest.mark.parametrize('difference,expected_attempt', [(1, 2), (2, 0)])
def test_source_footprint_symmetric_difference_has_a_one_pixel_bound(difference, expected_attempt):
    outside_tighter_quad = [(160 + number, 140) for number in range(difference)]
    with pixels(extra=outside_tighter_quad) as image:
        assert chosen(alternatives(), image)['attempt'] == expected_attempt


@pytest.mark.parametrize('count,expected_attempt', [(0, 0), (1, 0), (63, 0), (64, 2)])
def test_both_footprints_need_at_least_64_dark_source_pixels(count, expected_attempt):
    with pixels(count=count) as image:
        assert chosen(alternatives(), image)['attempt'] == expected_attempt


@pytest.mark.parametrize('gray,expected_attempt', [(179, 2), (180, 0)])
def test_source_ink_threshold_is_strictly_below_180(gray, expected_attempt):
    with pixels(value=gray) as image:
        assert chosen(alternatives(), image)['attempt'] == expected_attempt


@pytest.mark.parametrize('width,expected_attempt', [(112, 2), (112.01, 0), (139, 0)])
def test_tighter_quad_requires_at_least_twenty_percent_area_improvement(width, expected_attempt):
    with pixels() as image:
        result = chosen(alternatives(small_width=width, small_height=50), image)
    assert result['attempt'] == expected_attempt


@pytest.mark.parametrize('large,small', [('Harbor!', 'HARBOR?'),
                                        ('Straße', 'STRASSE'),
                                        ('Harbor', 'Harbou')])
def test_source_fit_requires_matching_casefolded_text_and_native_character_length(large, small):
    with pixels() as image:
        assert chosen(alternatives(large_text=large, small_text=small), image)['attempt'] == 0


def test_tighter_geometry_cannot_lower_selected_confidence_floor():
    with pixels() as image:
        assert chosen(alternatives(small_confidence=69), image)['attempt'] == 0


def test_source_fit_cannot_create_a_word_without_two_native_support_keys():
    first = candidate('Harbor', 95, 0)
    duplicate = {**first, 'attempt': 1, 'confidence': 94}
    with pixels() as image:
        assert algorithm.select_words([first, duplicate], source_image=image) == []


def test_existing_sixty_confidence_corroboration_remains_valid():
    first = candidate('Harbor', 74, 0)
    support = candidate('HARBOR', 60, 1, psm=13)
    with pixels() as image:
        result = chosen([first, support], image)
    assert result['attempt'] == 0 and result['agreement_votes'] == 2


def test_tighter_replacement_cannot_collide_with_another_accepted_word():
    candidates = alternatives(large_angle=15)
    candidates += pair('River', 90, 4, width=40, height=300)
    with pixels() as image:
        selected = algorithm.select_words(candidates, source_image=image)
    assert len(selected) == 2
    assert {word['attempt'] for word in selected} == {0, 4}


def test_successive_near_equivalences_cannot_drift_from_original_winner_ink():
    candidates = pair('Harbor', 95, 0)
    candidates += pair('HARBOR', 74, 2, width=100, height=40)
    candidates += pair('HARBOR', 80, 4, width=90, height=30)
    # A->B drops one pixel, B->C drops one more; A->C exceeds the reviewed limit.
    with pixels(extra=[(160, 137), (160, 142)]) as image:
        assert chosen(candidates, image)['attempt'] == 2


def test_replacement_preserves_other_native_words_and_reassembles_measured_lines():
    candidates = pair('Harbor', 95, 0, angle=15, center=(90, 160))
    candidates += pair('HARBOR', 74, 2, width=100, height=20, center=(90, 160))
    candidates += pair('River', 90, 4, width=60, height=20, center=(250, 160))
    with Image.new('RGB', SIZE, 'white') as image:
        for number in range(80):
            image.putpixel((74 + number % 16, 156 + number // 16), (0, 0, 0))
        selected = algorithm.select_words(candidates, source_image=image)
    assert [word['text'] for word in selected] == ['HARBOR', 'River']
    assert [word['attempt'] for word in selected] == [2, 4]


@pytest.mark.parametrize('name,limit,expected_attempt', [
    ('MAX_SOURCE_FIT_PAIRS_PER_WORD', 2, 2),
    ('MAX_SOURCE_FIT_PAIRS_PER_WORD', 1, 0),
    ('MAX_SOURCE_FIT_PAIRS', 2, 2),
    ('MAX_SOURCE_FIT_PAIRS', 1, 0),
    ('MAX_SOURCE_FIT_CROP_PIXELS', 7000, 2),
    ('MAX_SOURCE_FIT_CROP_PIXELS', 6999, 0),
    ('MAX_SOURCE_FIT_PIXELS', 14000, 2),
    ('MAX_SOURCE_FIT_PIXELS', 13999, 0),
])
def test_whole_alternative_group_is_bounded_without_partial_sampling(monkeypatch, name, limit, expected_attempt):
    # Two qualifying alternatives each inspect the same 140*50 source union.
    monkeypatch.setattr(algorithm, name, limit)
    with pixels() as image:
        assert chosen(alternatives(), image)['attempt'] == expected_attempt


@pytest.mark.parametrize('name,limit,expected_second', [
    ('MAX_SOURCE_FIT_PAIRS', 4, 6),
    ('MAX_SOURCE_FIT_PAIRS', 3, 4),
    ('MAX_SOURCE_FIT_PIXELS', 28000, 6),
    ('MAX_SOURCE_FIT_PIXELS', 27999, 4),
])
def test_budget_is_global_across_separate_selected_words(monkeypatch, name, limit, expected_second):
    monkeypatch.setattr(algorithm, name, limit)
    candidates = pair('Harbor', 95, 0, center=(90, 160))
    candidates += pair('HARBOR', 74, 2, width=100, height=20, center=(90, 160))
    candidates += pair('River', 94, 4, center=(250, 160))
    candidates += pair('RIVER', 74, 6, width=100, height=20, center=(250, 160))
    with Image.new('RGB', SIZE, 'white') as image:
        for center in (90, 250):
            for number in range(80):
                image.putpixel((center - 16 + number % 16, 156 + number // 16), (0, 0, 0))
        selected = algorithm.select_words(candidates, source_image=image)
    assert [word['attempt'] for word in selected] == [2, expected_second]
