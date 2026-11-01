"""Optional native evidence must not rewrite, rescore or invent baseline text.

These tests use drawn shapes and native-record fixtures only. They never run an
OCR engine, read private document fixtures or derive an expected corpus word.
"""
from copy import deepcopy
import math

import pytest
from PIL import Image, ImageDraw

from pdf_remediator import ocr_angles, ocr_regions, ocr_rescue


def record(text, *, confidence=92, attempt=0, psm=7,
           bounds=(20, 20, 80, 50), angle=0, raster=None, **extra):
    left, top, right, bottom = bounds
    cx, cy = (left+right)/2, (top+bottom)/2
    cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    quad = [[cx+cosine*(x-cx)-sine*(y-cy), cy+sine*(x-cx)+cosine*(y-cy)]
            for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
    box = [min(p[0] for p in quad), min(p[1] for p in quad),
           max(p[0] for p in quad), max(p[1] for p in quad)]
    return {'text': text, 'confidence': confidence, 'attempt': attempt,
            'raw_word_index': 0, 'psm': psm, 'raster_sha256': raster or f'{attempt+1:064x}',
            'quad': quad, 'box': box, 'angle': angle, 'height': bottom-top,
            'rotated_box': [left, top, right, bottom], 'rotated_size': [240, 120],
            'working_size': [240, 120], 'scale': 1, **extra}


def pair(text, *, attempt=10, confidence=92, **extra):
    return [record(text, attempt=attempt, confidence=confidence, psm=7, **extra),
            record(text, attempt=attempt+1, confidence=61, psm=13, **extra)]


def initial_evidence(original, *forms):
    return [original, *(item for index, text in enumerate(forms)
                        for item in pair(text, attempt=10+index*2))]


def native_pair(text='GLADE', *, attempt=30, plan_index=0, **extra):
    return pair(text, attempt=attempt, phase='confirmation', plan_index=plan_index, **extra)


def confirmation_plan(*allowed):
    return {'selected_index': 0, 'allowed_literals': list(allowed)}


@pytest.fixture
def ink_source():
    with Image.new('RGB', (240, 120), 'white') as image:
        draw = ImageDraw.Draw(image)
        # Two separated, asymmetric shapes provide more than 64 actual pixels;
        # all word-box edges lie in a white margin unless a test adds pixels.
        draw.rectangle((25, 25, 35, 35), fill='black')
        draw.rectangle((48, 27, 60, 40), fill='black')
        yield image


def test_exact_votes_require_same_literal_location_and_distinct_native_control():
    original = record('gLaDe', attempt=0)
    duplicate = {**original, 'attempt': 99, 'confidence': 99}
    distant = record('gLaDe', attempt=1, psm=13, bounds=(150, 20, 210, 50))
    evidence = [original, duplicate, distant,
                record('GLADE', attempt=2), record('gLaDe,', attempt=3),
                record('gLaDe', attempt=4, confidence=59)]
    assert ocr_angles.exact_literal_votes(original, evidence) == 1
    evidence.append(record('gLaDe', attempt=5, confidence=60, psm=13))
    assert ocr_angles.exact_literal_votes(original, evidence) == 2


def test_same_psm_on_a_distinct_conditioned_raster_can_supply_exact_support():
    first = record('GLADE', attempt=0, psm=7)
    second = record('GLADE', attempt=1, psm=7, confidence=60)
    assert ocr_angles.exact_literal_votes(first, [first, second]) == 2
    repeated = {**second, 'raster_sha256': first['raster_sha256']}
    assert ocr_angles.exact_literal_votes(first, [first, repeated]) == 1


def test_casefold_or_punctuation_agreement_never_becomes_exact_optional_support():
    words = [record('GLADE', attempt=0), record('Glade', attempt=1, psm=13),
             record('GLADE,', attempt=2)]
    assert ocr_angles.exact_supported_words(words) == []


@pytest.mark.parametrize('confidence, supported', [(69, False), (70, True)])
def test_optional_candidate_still_requires_one_native_confidence_at_least70(confidence, supported):
    words = pair('GLADE', confidence=confidence)
    before = deepcopy(words)
    result = ocr_angles.exact_supported_words(words)
    assert bool(result) is supported
    if supported:
        assert result[0]['text'] == 'GLADE' and result[0]['confidence'] == 70
        assert result[0]['agreement_votes'] == 2
    assert words == before


def test_confirmation_plan_binds_the_weak_literal_and_only_old_corroborated_case_form(ink_source):
    original = record('gLaDe', attempt=0)
    evidence = initial_evidence(original, 'GLADE')
    evidence += [record('Glade', attempt=20), record('GRADE', attempt=21)]
    before = deepcopy(evidence)
    pixels = ink_source.tobytes()
    plans = ocr_angles.confirmation_plans(ink_source, evidence, [original])
    assert len(plans) == 1
    assert plans[0]['selected_index'] == 0 and plans[0]['allowed_literals'] == ['GLADE']
    assert plans[0]['source_reference'] == {key: original[key] for key in
                                           ('attempt', 'raw_word_index', 'raster_sha256')}
    assert plans[0]['angle'] == 0 and plans[0]['kind'] == 'selected-word-confirmation'
    assert evidence == before and ink_source.tobytes() == pixels


def test_already_exactly_supported_baseline_cannot_become_a_confirmation_seed(ink_source):
    original = record('gLaDe', attempt=0)
    evidence = initial_evidence(original, 'GLADE') + [record('gLaDe', attempt=1, psm=13)]
    assert ocr_angles.confirmation_plans(ink_source, evidence, [original]) == []


def test_planning_does_not_turn_letter_changes_or_punctuation_changes_into_case_repairs(ink_source):
    original = record('gLaDe')
    evidence = initial_evidence(original, 'GRADE', 'GLADE,')
    assert ocr_angles.confirmation_plans(ink_source, evidence, [original]) == []


def test_distant_alternate_word_cannot_seed_a_local_confirmation(ink_source):
    original = record('gLaDe')
    evidence = [original, *pair('GLADE', bounds=(150, 20, 210, 50))]
    assert ocr_angles.confirmation_plans(ink_source, evidence, [original]) == []


def test_blank_selected_quad_never_creates_a_confirmation_crop():
    original = record('gLaDe')
    with Image.new('RGB', (240, 120), 'white') as image:
        assert ocr_angles.confirmation_plans(image, initial_evidence(original, 'GLADE'), [original]) == []


def test_confirmation_plan_bound_keeps_the_original_deterministic_prefix():
    with Image.new('RGB', (600, 180), 'white') as image:
        draw = ImageDraw.Draw(image)
        words, evidence = [], []
        for index in range(9):
            x = 10+index*60
            bounds = (x, 30, x+40, 60)
            draw.rectangle((x+8, 36, x+20, 49), fill='black')
            original = record('gLaDe', attempt=index, bounds=bounds)
            words.append(original)
            evidence.extend([original, *pair('GLADE', attempt=100+index*2, bounds=bounds)])
        plans = ocr_angles.confirmation_plans(image, evidence, words)
    assert [plan['selected_index'] for plan in plans] == list(range(8))


def test_comparison_budget_refuses_confirmation_before_allocating_a_native_frame(ink_source, monkeypatch):
    original = record('gLaDe')
    evidence = initial_evidence(original, 'GLADE')
    monkeypatch.setattr(ocr_angles, 'MAX_CONFIRMATION_COMPARISONS', 1)
    monkeypatch.setattr(ocr_angles, 'native_frame',
                        lambda *args: pytest.fail('Exhausted comparison work allocated a native raster'))
    before = deepcopy(evidence)
    assert ocr_angles.confirmation_plans(ink_source, evidence, [original]) == []
    assert evidence == before


def test_comparison_budget_retains_only_completed_plan_prefix_without_more_rasters(ink_source, monkeypatch):
    first = record('gLaDe', attempt=0)
    second = record('gLaDe', attempt=1, bounds=(150, 20, 210, 50))
    evidence = [first, second, *pair('GLADE', attempt=10),
                *pair('GLADE', attempt=20, bounds=(150, 20, 210, 50))]
    before = deepcopy([evidence, first, second])
    pixels = ink_source.tobytes()
    # Enough work for one literal/alternative scan group; the next seed can
    # start comparing but cannot complete its evidence or allocate its frame.
    monkeypatch.setattr(ocr_angles, 'MAX_CONFIRMATION_COMPARISONS', 3*len(evidence)+1)
    actual_frame = ocr_angles.native_frame
    allocations = []

    def measured_frame(image, angle):
        allocations.append(angle)
        return actual_frame(image, angle)

    monkeypatch.setattr(ocr_angles, 'native_frame', measured_frame)
    plans = ocr_angles.confirmation_plans(ink_source, evidence, [first, second])
    assert [plan['selected_index'] for plan in plans] == [0]
    assert allocations == [0]
    assert ocr_angles.confirmation_plans(ink_source, evidence, [first, second]) == plans
    assert allocations == [0, 0]
    assert [evidence, first, second] == before and ink_source.tobytes() == pixels


def test_confirmation_replaces_with_the_whole_native_record_without_rescoring_other_words(ink_source):
    original = record('gLaDe', baseline_only='must not be copied to replacement')
    neighbor = record('STONE', attempt=3, bounds=(150, 20, 210, 50),
                      agreement_votes=11, selection_score=123, baseline_only='retain verbatim')
    evidence = initial_evidence(original, 'GLADE')
    native = native_pair(bounds=(19, 20, 81, 50), native_layer_trace={'retained': [8, 3]})
    before = deepcopy([original, neighbor, evidence, native])
    result = ocr_angles.confirm_words([original, neighbor], evidence, native,
                                     [confirmation_plan('GLADE')], source_image=ink_source)
    assert result[0] == {**native[0], 'agreement_votes': 2, 'selection_score': 100}
    assert 'baseline_only' not in result[0]
    assert result[1] is neighbor and result[1]['selection_score'] == 123
    assert [original, neighbor, evidence, native] == before


@pytest.mark.parametrize('extra_pixels, replace', [(1, True), (2, False)])
def test_confirmation_keeps_the_existing_one_source_pixel_difference_limit(ink_source, extra_pixels, replace):
    draw = ImageDraw.Draw(ink_source)
    for offset in range(extra_pixels):
        draw.point((80, 30+offset), fill='black')
    original = record('gLaDe')
    result = ocr_angles.confirm_words([original], initial_evidence(original, 'GLADE'),
                                     native_pair(bounds=(19, 20, 81, 50)),
                                     [confirmation_plan('GLADE')], source_image=ink_source)
    assert (result[0]['text'] == 'GLADE') is replace
    if not replace:
        assert result[0] is original


def test_insufficient_actual_source_ink_cannot_confirm_even_identical_quads():
    original = record('gLaDe')
    with Image.new('RGB', (240, 120), 'white') as image:
        ImageDraw.Draw(image).rectangle((25, 25, 31, 33), fill='black')  # Exactly 63 pixels.
        result = ocr_angles.confirm_words([original], initial_evidence(original, 'GLADE'), native_pair(),
                                         [confirmation_plan('GLADE')], source_image=image)
    assert result[0] is original


def test_two_confirmed_literal_alternatives_leave_the_original_record_unchanged(ink_source):
    original = record('gLaDe')
    evidence = initial_evidence(original, 'GLADE', 'Glade')
    native = native_pair('GLADE') + native_pair('Glade', attempt=40)
    result = ocr_angles.confirm_words([original], evidence, native,
                                     [confirmation_plan('GLADE', 'Glade')], source_image=ink_source)
    assert result[0] is original


def test_folded_confirmation_votes_cannot_choose_a_single_raw_case_literal(ink_source):
    original = record('gLaDe')
    native = [record('GLADE', phase='confirmation', plan_index=0, attempt=30),
              record('Glade', phase='confirmation', plan_index=0, attempt=31, psm=13)]
    result = ocr_angles.confirm_words([original], initial_evidence(original, 'GLADE'), native,
                                     [confirmation_plan('GLADE')], source_image=ink_source)
    assert result[0] is original


@pytest.mark.parametrize('damage', ['unseeded-literal', 'different-angle', 'wrong-phase', 'different-plan'])
def test_confirmation_cannot_escape_its_old_literal_angle_or_phase_scope(ink_source, damage):
    original = record('gLaDe')
    native = native_pair()
    if damage == 'unseeded-literal':
        native = native_pair('Glade')
    elif damage == 'different-angle':
        native = native_pair(angle=1)
    elif damage == 'wrong-phase':
        native = [{**word, 'phase': 'rescue'} for word in native]
    else:
        native = [{**word, 'plan_index': 1} for word in native]
    result = ocr_angles.confirm_words([original], initial_evidence(original, 'GLADE'), native,
                                     [confirmation_plan('GLADE', 'Glade')], source_image=ink_source)
    assert result[0] is original


def test_same_source_ink_does_not_authorize_collision_with_another_selected_word(ink_source):
    original = record('gLaDe')
    neighbor = record('STONE', bounds=(75, 20, 125, 50), attempt=3)
    ImageDraw.Draw(ink_source).rectangle((110, 25, 119, 35), fill='black')
    native = native_pair(bounds=(19, 20, 98, 50))
    result = ocr_angles.confirm_words([original, neighbor], initial_evidence(original, 'GLADE'), native,
                                     [confirmation_plan('GLADE')], source_image=ink_source)
    assert result[0] is original and result[1] is neighbor


def test_optional_rescue_never_rescores_or_displaces_an_existing_record():
    baseline = record('gLaDe', confidence=72, agreement_votes=7, selection_score=83)
    overlapping = pair('OTHER', attempt=30, confidence=99, phase='rescue', plan_index=0)
    separate = pair('RIVER', attempt=40, phase='rescue', plan_index=1, bounds=(120, 20, 180, 50))
    before = deepcopy([baseline, overlapping, separate])
    result = ocr_angles.add_rescue_words([baseline], overlapping+separate)
    assert result[0] is baseline and result[0]['selection_score'] == 83
    assert [word['text'] for word in result] == ['gLaDe', 'RIVER']
    assert [baseline, overlapping, separate] == before


def test_different_rescue_plans_cannot_pool_one_vote_each():
    baseline = record('STONE', bounds=(150, 20, 210, 50))
    candidates = [record('RIVER', attempt=30, phase='rescue', plan_index=0),
                  record('RIVER', attempt=31, psm=13, phase='rescue', plan_index=1)]
    assert ocr_angles.add_rescue_words([baseline], candidates) == [baseline]


def test_nonrescue_phase_is_not_admitted_as_a_new_word():
    baseline = record('STONE', bounds=(150, 20, 210, 50))
    assert ocr_angles.add_rescue_words([baseline], native_pair('RIVER')) == [baseline]


def test_no_unanchored_component_line_can_reach_optional_rescue_selection():
    with Image.new('RGB', (240, 140), 'white') as image:
        draw = ImageDraw.Draw(image)
        for x in (20, 29, 38, 47):
            draw.rectangle((x, 90, x+4, 109), fill='black')
        # The accepted word belongs to another source component line entirely.
        draw.rectangle((165, 20, 175, 39), fill='black')
        baseline = record('STONE', bounds=(150, 15, 195, 45), confidence=95)
        plans = ocr_rescue.proposals(image, [baseline], ocr_regions)['plans']
        assert plans == []
        assert ocr_angles.add_rescue_words([baseline], []) == [baseline]


def test_ordering_preserves_records_and_restores_one_oblique_line_reading_direction():
    angle = -math.degrees(math.atan(.5))
    first = record('GLADE', bounds=(40, 130, 80, 150), angle=angle)
    middle = record('STONE', bounds=(100, 100, 140, 120), angle=angle)
    last = record('RIVER', bounds=(160, 70, 200, 90), angle=angle)
    input_words = [last, first, middle]
    before = deepcopy(input_words)
    result = ocr_angles.order_words(input_words)
    assert result == [first, middle, last]
    assert all(actual is expected for actual, expected in zip(result, (first, middle, last)))
    assert input_words == before
