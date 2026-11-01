"""Authored local-language controls; no provider, OCR, network or PDF mutation."""

import json

import pytest

from pdf_remediator.language import MAX_TEXT_CHARACTERS, MAX_WORDS, SUPPORTED_LANGUAGES, assess_language


TEXTS = {
    "en": """The students are preparing their research for the new community garden. They have collected information from each neighborhood and will explain which plants can grow without much water. This report does not replace the practical work because every group should inspect its own space before choosing seeds. When the weather changes, these students will compare their records with those from the previous year. There are several reasons why our plan includes different vegetables, but the main purpose is to learn about healthy soil and careful observation. Each person should write what they have seen, where they worked and which questions they would like to explore after the meeting.""",
    "es": """Los estudiantes preparan una investigación sobre los jardines de nuestra comunidad. Ellos tienen información de cada barrio y pueden explicar cuáles plantas necesitan menos agua durante el verano. Este informe no reemplaza la experiencia práctica porque los grupos deben observar sus propios espacios antes de elegir las semillas. Cuando cambia el tiempo, estos estudiantes comparan sus registros con los del año anterior. Hay varias razones para incluir diferentes verduras, pero nuestro propósito principal es aprender sobre el suelo saludable y la observación cuidadosa. Cada persona debe escribir dónde trabajó, qué ha visto y cuáles preguntas quiere explorar después de la reunión con sus compañeros.""",
    "fr": """Les étudiants préparent une recherche pour les jardins de notre communauté. Ils ont recueilli des informations dans chaque quartier et peuvent expliquer quelles plantes ont besoin de moins d'eau pendant l'été. Ce rapport ne remplace pas le travail pratique parce que les groupes doivent examiner leurs propres espaces avant de choisir des graines. Quand le temps change, ces étudiants comparent leurs observations avec celles de l'année précédente. Il y a plusieurs raisons pour inclure différents légumes, mais notre objectif principal est d'apprendre comment protéger le sol. Chaque personne écrit où elle a travaillé, ce qu'elle a vu et quelles questions elle souhaite explorer après la réunion avec ses collègues.""",
    "de": """Die Studierenden bereiten eine Untersuchung für die Gärten unserer Gemeinde vor. Sie haben Informationen aus jedem Stadtteil gesammelt und können erklären, welche Pflanzen während des Sommers weniger Wasser brauchen. Dieser Bericht ersetzt nicht die praktische Arbeit, weil jede Gruppe ihren eigenen Platz untersuchen sollte, bevor sie Samen auswählt. Wenn sich das Wetter verändert, werden diese Studierenden ihre Beobachtungen mit denen aus dem vergangenen Jahr vergleichen. Es gibt mehrere Gründe für verschiedene Gemüsesorten, aber unser wichtigstes Ziel ist das Lernen über gesunden Boden und sorgfältige Beobachtung. Jeder soll schreiben, wo er gearbeitet hat und welche Fragen nach der Besprechung noch untersucht werden müssen.""",
    "it": """Gli studenti preparano una ricerca per i giardini della nostra comunità. Hanno raccolto informazioni da ogni quartiere e possono spiegare quali piante hanno bisogno di meno acqua durante l'estate. Questo rapporto non sostituisce il lavoro pratico perché ogni gruppo dovrebbe osservare il proprio spazio prima di scegliere le sementi. Quando cambia il tempo, questi studenti confrontano le loro osservazioni con quelle dell'anno precedente. Ci sono diverse ragioni per includere verdure differenti, ma il nostro obiettivo principale è conoscere il terreno e imparare a osservare. Ogni persona scrive dove ha lavorato, quello che ha visto e quali domande vuole esplorare dopo la riunione con gli altri.""",
    "pt": """Os estudantes estão preparando uma pesquisa para os jardins da nossa comunidade. Eles têm informações sobre cada bairro e podem explicar quais plantas precisam de menos água durante o verão. Este relatório não substitui o trabalho prático porque cada grupo deve observar seu próprio espaço antes de escolher as sementes. Quando o tempo muda, os estudantes comparam suas observações com aquelas do ano anterior. Existem várias razões para incluir verduras diferentes, mas nosso objetivo principal é aprender sobre o solo saudável e a observação cuidadosa. Cada pessoa deve escrever onde trabalhou, o que viu e quais perguntas deseja explorar após a reunião com os seus colegas.""",
    "nl": """De studenten bereiden een onderzoek voor de tuinen van onze gemeenschap voor. Zij hebben informatie uit iedere buurt verzameld en kunnen uitleggen welke planten tijdens de zomer minder water nodig hebben. Dit verslag vervangt het praktische werk niet, omdat iedere groep zijn eigen ruimte moet bekijken voordat er zaden worden gekozen. Wanneer het weer verandert, zullen deze studenten hun waarnemingen vergelijken met die van het vorige jaar. Er zijn verschillende redenen om andere groenten te gebruiken, maar ons belangrijkste doel is leren over gezonde grond en zorgvuldig onderzoek. Iedere persoon moet schrijven waar hij heeft gewerkt, wat hij heeft gezien en welke vragen hij na de bijeenkomst wil onderzoeken.""",
}


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_supported_primary_language_agreement_is_explicitly_bounded(language):
    result = assess_language(TEXTS[language], language)
    assert result["status"] == "pass", result
    assert result["detected_language"] == language
    assert result["suggested_language"] is None
    assert result["evidence"]["profiles"][language]["distinct_diagnostic_markers"] >= 6
    assert "not a vendor-equivalent" in " ".join(result["limitations"])
    assert json.loads(json.dumps(result)) == result


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_high_confidence_mismatch_suggests_reviewed_fix_only(language):
    declared = "fr" if language == "en" else "en"
    result = assess_language(TEXTS[language], declared)
    assert result["status"] == "fail", result
    assert result["suggested_language"] == language
    assert result["declared_language"] == declared
    assert "named reviewed language decision" in " ".join(result["limitations"])


@pytest.mark.parametrize("declared", ["en-US", "EN-gb", "en-Latn-GB", "en-x-private"])
def test_region_or_script_variant_is_not_falsely_replaced(declared):
    result = assess_language(TEXTS["en"], declared)
    assert result["status"] == "pass"
    assert result["declared_language"] == declared
    assert result["suggested_language"] is None


@pytest.mark.parametrize("declared", ["", None, "english-US-too-long-token", "en_US", " en! ",
                                     "español", "ｅｎ", "ΕΝ", "en-中文", "sv", "ja", "und", "mul",
                                     "eng", "fra", "ger", "english"])
def test_missing_invalid_or_unsupported_declaration_never_passes(declared):
    result = assess_language(TEXTS["en"], declared)
    assert result["status"] == "needs-review"
    assert result["suggested_language"] is None


@pytest.mark.parametrize("text", ["", None, "The report contains information for students.", "12345 " * 100,
                                  "the and with from " * 100,
                                  "Seminar botanica locus exemplum experimentum natura arboretum " * 30])
def test_insufficient_ambiguous_or_repeated_text_never_passes(text):
    result = assess_language(text, "en")
    assert result["status"] == "needs-review"
    assert result["detected_language"] is None
    assert result["suggested_language"] is None


@pytest.mark.parametrize("first,second", [("en", "es"), ("es", "pt"), ("fr", "it"), ("de", "nl")])
def test_multilingual_documents_abstain_even_with_supported_declaration(first, second):
    result = assess_language(TEXTS[first] + "\n" + TEXTS[second], first)
    assert result["status"] == "needs-review", result
    assert result["suggested_language"] is None


def test_small_foreign_passage_is_not_hidden_by_english_majority():
    minority = "Los estudiantes tienen una pregunta para sus compañeros. Ellos pueden explicar por qué estos jardines son importantes para nuestra comunidad."
    result = assess_language(TEXTS["en"] + "\n" + minority, "en")
    assert result["status"] == "needs-review"
    assert "mixed-language-signals" in result["evidence"]["reasons"]


def test_word_minimum_boundary_is_enforced_even_with_strong_markers():
    words = TEXTS["en"].split()
    below = assess_language(" ".join(words[:79]), "en")
    boundary = assess_language(" ".join(words[:80]), "en")
    assert below["status"] == "needs-review"
    assert "insufficient-distinct-text" in below["evidence"]["reasons"]
    assert boundary["status"] == "pass"
    assert below["evidence"]["word_count"] == 79
    assert boundary["evidence"]["word_count"] == 80


@pytest.mark.parametrize("text", ["Αυτή είναι μια δοκιμή της γλώσσας και του περιεχομένου. " * 30,
                                  "Это проверка языка документа и его содержания. " * 30,
                                  "これは文書の言語を確認するためのテストです。" * 60,
                                  TEXTS["en"] + "これは文書の言語を確認するためのテストです。" * 20])
def test_script_is_evidence_without_guessing_language(text):
    result = assess_language(text, "en")
    assert result["status"] == "needs-review"
    assert result["suggested_language"] is None
    assert "mixed-or-unsupported-script" in result["evidence"]["reasons"]


def test_unsupported_latin_language_is_not_assumed_to_be_english():
    text = "Studenterna undersöker trädgårdarna i kommunen. De behöver information om växterna och marken inför sommaren. Varje deltagare skriver sina egna anteckningar och sedan jämför gruppen resultaten från olika platser. Det finns flera anledningar till försöket men den viktigaste handlar om att förstå naturen och utveckla noggranna metoder. Före mötet samlar deltagarna material som beskriver arbetet med grönsaker blommor frön träd buskar fält odling vatten väder regn sol jord forskning planering frågor erfarenheter kunskap miljö samhälle skola familjer grannar arbete observationer resultat framtid historia rapporter bilder aktiviteter förberedelser förändringar möjligheter resurser."
    result = assess_language(text, "en")
    assert result["status"] == "needs-review"
    assert result["suggested_language"] is None


def test_bad_extraction_is_review_not_false_agreement():
    result = assess_language(TEXTS["en"] + "\ufffd", "en")
    assert result["status"] == "needs-review"
    assert "extracted-text-replacement-characters" in result["evidence"]["reasons"]


def test_unicode_normalization_keeps_french_diacritics_and_evidence_private():
    import unicodedata
    result = assess_language(unicodedata.normalize("NFD", TEXTS["fr"]), "fr-CA")
    assert result["status"] == "pass"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "quartier" not in serialized
    assert "communauté" not in serialized


def test_resource_limits_abstain_instead_of_sampling_a_misleading_prefix():
    too_large = assess_language("x" * (MAX_TEXT_CHARACTERS + 1), "en")
    too_many_words = assess_language("a " * (MAX_WORDS + 1), "en")
    assert too_large["status"] == too_many_words["status"] == "needs-review"
    assert "text-exceeds-screen-limit" in too_large["evidence"]["reasons"]
    assert "text-exceeds-word-limit" in too_many_words["evidence"]["reasons"]
