"""Pin the contrast and language-tag behaviour that CORE-REQUESTS.md hands over to the shared accessibility rules (C2).

The vectors in CORE-REQUESTS.md were computed from this code on 2026-11-16. If one of these tests has to change, the request in
CORE-REQUESTS.md must change with it and the core must be told, because the core checks its own work against those numbers.
"""
import pytest

from pdf_remediator.contrast import contrast_ratio
from pdf_remediator.language_tags import is_language_tag, validate_language_tag

WHITE = (255, 255, 255)

RATIOS = {
    (0x00, 0x00, 0x00): 21.0000000000,
    (0xFF, 0xFF, 0xFF): 1.0000000000,
    (0x59, 0x59, 0x59): 7.0047292080,
    (0x76, 0x76, 0x76): 4.5422249596,
    (0x77, 0x77, 0x77): 4.4780894536,
    (0x00, 0x80, 0x00): 5.1374027808,
    (0xFF, 0x00, 0x00): 3.9984767708,
    (0x00, 0x00, 0xFF): 8.5924713584,
    (0x94, 0x94, 0x94): 3.0334698257,
    (0x95, 0x95, 0x95): 2.9953461357,
}

# (colour, passes at normal size, passes at large size), thresholds 4.5 and 3.0 compared without rounding
OUTCOMES = {
    (0x00, 0x00, 0x00): (True, True),
    (0xFF, 0xFF, 0xFF): (False, False),
    (0x59, 0x59, 0x59): (True, True),
    (0x76, 0x76, 0x76): (True, True),
    (0x77, 0x77, 0x77): (False, True),
    (0x00, 0x80, 0x00): (True, True),
    (0xFF, 0x00, 0x00): (False, True),
    (0x00, 0x00, 0xFF): (True, True),
    (0x94, 0x94, 0x94): (False, True),
    (0x95, 0x95, 0x95): (False, False),
}

WELL_FORMED = [
    "en", "en-US", "zh-Hant", "zh-Hans-CN", "sr-Latn-RS", "fr-CA", "es-419", "en-123", "de-CH-1901", "sl-rozaj-biske",
    "en-a-bbb-x-a-ccc", "x-private", "i-klingon", "en-GB-oed", "english-language",
]
NOT_WELL_FORMED = [
    "", "e", "x", "en-", "-en", "en--US", "en_US", "en-US ", "en-a", "en-12", "de-DE-1996-1996", "en-a-bbb-a-ccc",
    "abcdefghi", "ab-abcdefghi", "é",
]


@pytest.mark.parametrize("colour,expected", sorted(RATIOS.items()))
def test_contrast_ratio_vectors_match_the_handover(colour, expected):
    assert contrast_ratio(colour, WHITE) == pytest.approx(expected, abs=1e-9)
    assert contrast_ratio(WHITE, colour) == pytest.approx(expected, abs=1e-9)  # symmetric


@pytest.mark.parametrize("colour,expected", sorted(OUTCOMES.items()))
def test_thresholds_are_compared_without_rounding(colour, expected):
    ratio = contrast_ratio(colour, WHITE)
    assert (ratio >= 4.5, ratio >= 3.0) == expected


def test_a_ratio_just_under_the_threshold_is_not_rounded_up():
    # 4.4780894536 displays as 4.48; it must not be treated as 4.5.
    assert contrast_ratio((0x77, 0x77, 0x77), WHITE) < 4.5


@pytest.mark.parametrize("tag", WELL_FORMED)
def test_well_formed_tags_are_accepted_with_their_spelling_kept(tag):
    assert is_language_tag(tag) is True
    assert validate_language_tag(tag) == tag


@pytest.mark.parametrize("tag", NOT_WELL_FORMED)
def test_malformed_tags_are_refused(tag):
    assert is_language_tag(tag) is False
    with pytest.raises(ValueError):
        validate_language_tag(tag)


def test_there_are_twenty_six_grandfathered_tags_and_all_are_accepted():
    from pdf_remediator import language_tags
    assert len(language_tags._GRANDFATHERED) == 26
    assert all(is_language_tag(tag) for tag in language_tags._GRANDFATHERED)
