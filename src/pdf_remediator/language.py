"""A deliberately bounded, local screen for a declared document language.

This is a function-word screen, not a language model or semantic validation.
It uses no network, optional dependency, OCR, provider, or persisted text.  A
positive result means only that this screen agrees with the primary subtag;
human review of language, multilingual spans and pronunciation remains needed.
"""

from collections import Counter
import re
import unicodedata


PROFILE = "local-function-word-language-v1"
SUPPORTED_LANGUAGES = ("en", "es", "fr", "de", "it", "pt", "nl")
MAX_TEXT_CHARACTERS = 1_000_000
MAX_WORDS = 30_000
MIN_WORDS = 80
MIN_LETTERS = 300

# Authored function-word lists, kept in source so every inference is auditable.
# Words shared by these profiles are discounted; distinct diagnostic words are
# required as well. Accents are significant, not silently transliterated.
_WORDS = {
    "en": "the and this that with from are have will which their there but not can been was were because about into each these those than also without through before after when where while should would could your does between under over then of for you they our who its such some any them no",
    "es": "el los las una uno unos unas del por para con pero como cuando donde porque también entre sobre desde hasta aunque esta este estos estas sus sin muy más son será fueron puede pueden hay tiene tienen hemos han hacia quien quienes cuyo cuya esos esas aquel aquella nuestro nuestra usted ustedes ello ellas ellos de la no cada durante antes después al se que su le si",
    "fr": "le la les un une des du aux et que qui pour dans avec sur par pas plus nous vous ils elles est sont être comme cette ces au se ne leur leurs lui mais où même car ont avait avez notre votre sans chaque tout tous ainsi quand dont puis depuis lequel laquelle de si entre",
    "de": "der die das dem den ein eine einer einem einen und ist sind für mit nicht auch sich auf aus als zum zur von bei über nach noch werden wird wurde seine ihre dieser diese dieses oder aber weil wenn durch ohne zwischen können kann haben hat wir sie unser unsere jeder welche während schon dann dort",
    "it": "il lo gli uno una degli delle della dello del che non per con nel nella sul sono siamo come questo questa questi queste anche ma dal dalla alla alle agli tra fra perché quando dove senza dopo prima quale molto dei hanno aveva viene essere ogni loro nostro nostra quello quella oppure quindi sulle negli la le di in si durante de",
    "pt": "os as um uma uns umas ao aos do dos da das no nos na nas com que não para por pelo pela pelos pelas são está estão ser mas também entre sobre quando onde porque muito mais sem até você vocês nós seu sua seus suas aquele aquela isso isto têm tem nosso nossa foram pode podem cada após durante ainda assim antes quais quem de se si como",
    "nl": "het een de deze dit dat en voor van zijn wordt niet met als aan door om op ook maar omdat naar bij uit over wij zij hun onze heeft hebben was waren waar wanneer tussen zonder zullen kunnen welke wie ieder iedere daar deze heeft werd worden nog dan tijdens terwijl moet moeten onze ons zich",
}
_LEXICONS = {language: frozenset(words.split()) for language, words in _WORDS.items()}
_OWNERS = {}
for _language, _words in _LEXICONS.items():
    for _word in _words:
        _OWNERS.setdefault(_word, set()).add(_language)

LIMITATIONS = (
    "A deterministic function-word screen for en, es, fr, de, it, pt and nl only; it is not a vendor-equivalent language detector.",
    "Short, ambiguous, mixed-language, unsupported-script and unsupported-language text requires human review; untagged language spans are not validated.",
    "Agreement checks only the primary language subtag, not regional variants, wording, translation, spoken pronunciation or all content.",
    "Unsupported languages can resemble a supported profile; a screen agreement does not establish that the document language is correct.",
    "Only caller-supplied extracted text is screened; the caller must separately disclose page sampling and text-extraction limits. Full-document coverage is not established by this function.",
    "A suggested language requires a named reviewed language decision before a separate output can be written; this screen never changes a PDF.",
)


def _script(character):
    name = unicodedata.name(character, "")
    for script in ("LATIN", "GREEK", "CYRILLIC", "HEBREW", "ARABIC", "HIRAGANA", "KATAKANA", "HANGUL"):
        if script in name:
            return script.lower()
    if "CJK" in name or "IDEOGRAPH" in name:
        return "cjk"
    return "other"


def _scores(tokens):
    counts = Counter(tokens)
    profiles = {}
    for language, words in _LEXICONS.items():
        matched = {word: counts[word] for word in sorted(words) if counts[word]}
        unique = {word: count for word, count in matched.items() if len(_OWNERS[word]) == 1}
        score = sum(min(count, 3) / len(_OWNERS[word]) for word, count in matched.items())
        profiles[language] = {
            "score": round(score, 3),
            "marker_occurrences": sum(matched.values()),
            "distinct_markers": len(matched),
            "distinct_diagnostic_markers": len(unique),
            "diagnostic_occurrences": sum(unique.values()),
            "diagnostic_markers": unique,
        }
    return profiles


def _candidate(profiles, *, local=False):
    ranked = sorted(profiles, key=lambda language: (-profiles[language]["score"], language))
    first, second = (profiles[language] for language in ranked[:2])
    minimum_distinct, minimum_unique, minimum_hits, minimum_score = (5, 3, 6, 6) if local else (10, 6, 18, 16)
    if (first["distinct_markers"] < minimum_distinct
            or first["distinct_diagnostic_markers"] < minimum_unique
            or first["marker_occurrences"] < minimum_hits
            or first["score"] < minimum_score
            or first["score"] < second["score"] * 1.8 + 2):
        return None
    return ranked[0]


def assess_language(text, declared):
    """Return JSON-safe evidence and a review-only suggestion, without mutation.

    ``pass`` is a supported, high-confidence primary-language *screen agreement*;
    ``fail`` is a high-confidence disagreement with a supported declared primary
    language; ``needs-review`` is an abstention, never a presumed agreement.
    No text excerpts are returned: evidence contains counts and the fixed
    diagnostic function words from this module only.
    """
    text = text if isinstance(text, str) else ""
    declared = declared.strip() if isinstance(declared, str) else ""
    valid = bool(re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", declared))
    primary = declared.split("-", 1)[0].lower() if valid else None
    evidence = {
        "supported_languages": list(SUPPORTED_LANGUAGES),
        "declared_syntax_valid": valid,
        "minimum_words": MIN_WORDS,
        "minimum_letters": MIN_LETTERS,
        "maximum_text_characters": MAX_TEXT_CHARACTERS,
        "maximum_words": MAX_WORDS,
        "character_count": len(text),
        "text_scope": "caller-supplied-extracted-text; full-document coverage not established",
        "reasons": [],
    }
    result = {
        "profile": PROFILE,
        "status": "needs-review",
        "declared_language": declared,
        "declared_primary_language": primary,
        "detected_language": None,
        "suggested_language": None,
        "evidence": evidence,
        "limitations": list(LIMITATIONS),
    }
    if len(text) > MAX_TEXT_CHARACTERS:
        evidence["reasons"].append("text-exceeds-screen-limit")
        return result
    normalized = unicodedata.normalize("NFC", text).casefold()
    tokens = re.findall(r"[^\W\d_]+", normalized, re.UNICODE)
    scripts = Counter(_script(character) for character in normalized if character.isalpha())
    letters = sum(scripts.values())
    evidence.update({"word_count": len(tokens), "distinct_words": len(set(tokens)),
                     "letter_count": letters, "scripts": dict(sorted(scripts.items())),
                     "replacement_characters": normalized.count("\ufffd")})
    if len(tokens) > MAX_WORDS:
        evidence["reasons"].append("text-exceeds-word-limit")
        return result
    if not valid:
        evidence["reasons"].append("missing-or-invalid-declared-language")
    elif primary not in SUPPORTED_LANGUAGES:
        evidence["reasons"].append("unsupported-declared-language")
    if len(tokens) < MIN_WORDS or letters < MIN_LETTERS or len(set(tokens)) < 30:
        evidence["reasons"].append("insufficient-distinct-text")
    if letters and scripts["latin"] / letters < 0.95:
        evidence["reasons"].append("mixed-or-unsupported-script")
    if evidence["replacement_characters"]:
        evidence["reasons"].append("extracted-text-replacement-characters")
    profiles = _scores(tokens)
    evidence["profiles"] = profiles
    candidate = _candidate(profiles)
    if candidate is None:
        evidence["reasons"].append("ambiguous-or-unsupported-language-profile")
        return result
    # Small minority passages must not disappear behind a strong whole-document
    # majority. A few foreign names alone do not establish a second language.
    minority = [language for language, profile in profiles.items() if language != candidate
                and profile["distinct_diagnostic_markers"] >= 3
                and profile["diagnostic_occurrences"] >= 5]
    windows = [tokens[start:start + 40] for start in range(0, len(tokens), 20)
               if len(tokens[start:start + 40]) >= 20]
    window_languages = sorted({language for window in windows
                               if (language := _candidate(_scores(window), local=True))})
    evidence["window_languages"] = window_languages
    evidence["minority_language_profiles"] = minority
    if minority or any(language != candidate for language in window_languages):
        evidence["reasons"].append("mixed-language-signals")
    if not window_languages or candidate not in window_languages:
        evidence["reasons"].append("insufficient-distributed-agreement")
    if evidence["reasons"]:
        return result
    result["detected_language"] = candidate
    if candidate == primary:
        result["status"] = "pass"
        evidence["reasons"].append("supported-primary-language-screen-agreement")
    else:
        result["status"] = "fail"
        result["suggested_language"] = candidate
        evidence["reasons"].append("supported-primary-language-screen-mismatch")
    return result
