"""OCR writes its invisible text into a Form XObject, every word wrapped in /Artifact BMC ... EMC inside the owning /P <</MCID n>> BDC.
The inspector's proof of such streams and the pipeline's (form_edits) must agree, because the page preview needs both to say the
document has no form. Before they agreed, an OCR result that carried an empty form shell was called "a form" by the pipeline's check
and its proposed page could not be drawn. Every case here must give the same verdict from both."""
import pikepdf
import pytest

from pdf_remediator import form_edits as forms, inspection
from test_form_edits import inert_mcr_pdf
from test_inspection_empty_form import OWNED, with_form_content


def verdicts(path):
    with pikepdf.open(path) as pdf:
        return forms.has_form_signals(pdf), inspection._inert_empty_acroform(pdf)


NOT_A_FORM = (False, True)
STILL_A_FORM = (True, False)


def test_the_ordinary_owned_text_case_is_not_a_form_for_both(tmp_path):
    assert verdicts(inert_mcr_pdf(tmp_path / 'source.pdf')) == NOT_A_FORM


@pytest.mark.parametrize('inner', [
    b'/Artifact BMC (Page 1) Tj EMC ' + OWNED,
    OWNED + b' /Artifact BMC (Footer) Tj EMC',
    b'/Span BMC ' + OWNED + b' EMC',
    b'/Artifact BMC /Span BMC (Nested decoration) Tj EMC EMC ' + OWNED,
    b'/P <</MCID 0>> BDC (Existing OCR words) Tj /Artifact BMC (Inside the owner) Tj EMC EMC'])
def test_artifact_and_plain_wrappers_around_owned_text_are_not_a_form_for_both(tmp_path, inner):
    assert verdicts(with_form_content(tmp_path, inner)) == NOT_A_FORM


def test_a_missing_form_type_is_not_a_form_for_both(tmp_path):
    assert verdicts(with_form_content(tmp_path, OWNED, form_type=None)) == NOT_A_FORM


@pytest.mark.parametrize('inner,form_type', [
    (b'/Span BMC (Loose text) Tj EMC ' + OWNED, 'keep'),
    (b'(Loose text) Tj ' + OWNED, 'keep'),
    (b'/Artifact BMC (Decoration) Tj ' + OWNED, 'keep'),
    (OWNED + b' EMC', 'keep'),
    (b'/Artifact BMC (Only decoration) Tj EMC /P <</MCID 0>> BDC (Hidden) EMC', 'keep'),
    (b'/Artifact BMC /Artifact BMC (Only decoration) Tj EMC EMC /P <</MCID 0>> BDC EMC', 'keep'),
    (b'/OC BMC ' + OWNED + b' EMC', 'keep'),
    (b'/P <</MCID 0>> BDC /Artifact BMC (Only decoration inside the owner) Tj EMC EMC', 'keep'),   # the owner paints nothing itself
    (b'/Span BMC ' + OWNED, 'keep'),                                                              # a plain wrapper that is never closed
    (b'/Artifact BMC 0 0 10 10 re f EMC ' + OWNED, 'keep'),
    (b'/Artifact BMC /Fm0 Do EMC ' + OWNED, 'keep'),
    (OWNED, 2),
    (OWNED, pikepdf.Name.One)])
def test_unowned_text_unbalanced_markers_painting_and_other_form_types_are_still_a_form_for_both(tmp_path, inner, form_type):
    assert verdicts(with_form_content(tmp_path, inner, form_type=form_type)) == STILL_A_FORM


@pytest.mark.parametrize('variant', ['wrong-owner', 'phantom', 'wrong-key', 'extra-mcr-key', 'wrong-stream-type', 'bad-bbox', 'alias-key',
    'duplicate-reference', 'wrong-role', 'empty-text', 'missing-font', 'duplicate-marker', 'nested-marker', 'replacement-marker',
    'path-paint', 'xobject-paint', 'action'])
def test_every_earlier_marked_stream_refusal_gives_the_same_verdict_from_both(tmp_path, variant):
    assert verdicts(inert_mcr_pdf(tmp_path / 'source.pdf', variant=variant)) == STILL_A_FORM
