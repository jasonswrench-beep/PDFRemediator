"""The independent inspector's empty-form proof: artifact and plain marked-content wrappers and a missing /FormType are
accepted in engine Form streams, while anything that could hide a real form, action or unowned text is still refused."""
import pikepdf
import pytest

from pdf_remediator import inspection
from test_form_edits import inert_mcr_pdf, inert_pdf

OWNED = b'/P <</MCID 0>> BDC (Existing OCR words) Tj EMC'


def inert(path):
    with pikepdf.open(path) as pdf:
        return inspection._inert_empty_acroform(pdf)


def with_form_content(tmp_path, inner, *, form_type='keep'):
    source = inert_mcr_pdf(tmp_path / 'base.pdf')
    out = tmp_path / 'variant.pdf'
    with pikepdf.open(source) as pdf:
        stream = pdf.pages[0].Resources.XObject.OCR
        stream.write(b'BT /F1 12 Tf ' + inner + b' ET\n')
        if form_type is None:
            del stream.FormType
        elif form_type != 'keep':
            stream.FormType = form_type
        pdf.save(out, deterministic_id=True)
    return out


def test_the_ordinary_owned_text_case_is_still_accepted(tmp_path):
    assert inert(inert_mcr_pdf(tmp_path / 'source.pdf'))


@pytest.mark.parametrize('inner', [
    b'/Artifact BMC (Page 1) Tj EMC ' + OWNED,                       # decorative text beside the owned text
    OWNED + b' /Artifact BMC (Footer) Tj EMC',
    b'/Span BMC ' + OWNED + b' EMC',                                 # a plain wrapper around the owner
    b'/Artifact BMC /Span BMC (Nested decoration) Tj EMC EMC ' + OWNED,
    b'/P <</MCID 0>> BDC (Existing OCR words) Tj /Artifact BMC (Inside the owner) Tj EMC EMC'])
def test_artifact_and_plain_marked_content_wrappers_are_accepted_when_the_owner_still_paints(tmp_path, inner):
    assert inert(with_form_content(tmp_path, inner))


def test_a_missing_form_type_is_accepted_because_the_standard_makes_one_the_default(tmp_path):
    assert inert(with_form_content(tmp_path, OWNED, form_type=None))


@pytest.mark.parametrize('inner,form_type', [
    (b'/Span BMC (Loose text) Tj EMC ' + OWNED, 'keep'),                # text that nothing owns and is not decorative
    (b'(Loose text) Tj ' + OWNED, 'keep'),
    (b'/Artifact BMC (Decoration) Tj ' + OWNED, 'keep'),              # wrapper never closed
    (OWNED + b' EMC', 'keep'),                                       # closes more than it opened
    (b'/Artifact BMC (Only decoration) Tj EMC /P <</MCID 0>> BDC (Hidden) EMC', 'keep'),  # an owner that paints nothing itself
    (b'/Artifact BMC /Artifact BMC (Only decoration) Tj EMC EMC /P <</MCID 0>> BDC EMC', 'keep'),
    (b'/OC BMC ' + OWNED + b' EMC', 'keep'),                         # optional-content wrapper
    (b'/Artifact BMC 0 0 10 10 re f EMC ' + OWNED, 'keep'),          # painting is still not allowed, even inside an artifact
    (b'/Artifact BMC /Fm0 Do EMC ' + OWNED, 'keep'),
    (OWNED, 2),                                                      # a form type other than the default
    (OWNED, pikepdf.Name.One)])
def test_unowned_text_unbalanced_markers_painting_and_other_form_types_are_still_refused(tmp_path, inner, form_type):
    assert not inert(with_form_content(tmp_path, inner, form_type=form_type))


@pytest.mark.parametrize('variant', ['wrong-owner', 'phantom', 'wrong-key', 'extra-mcr-key', 'wrong-stream-type', 'bad-bbox', 'alias-key',
    'duplicate-reference', 'wrong-role', 'empty-text', 'missing-font', 'duplicate-marker', 'nested-marker', 'replacement-marker',
    'path-paint', 'xobject-paint', 'action'])
def test_every_earlier_marked_stream_refusal_still_holds_for_the_inspector(tmp_path, variant):
    assert not inert(inert_mcr_pdf(tmp_path / 'source.pdf', variant=variant))


@pytest.mark.parametrize('variant', ['missing-fields', 'bad-fields', 'nonempty-fields', 'unknown-key', 'xfa', 'need-appearances',
    'signature-flags', 'boolean-flags', 'permissions', 'calculation', 'appearance-paint', 'appearance-font', 'unknown-resource',
    'unknown-font', 'unknown-encoding', 'bad-differences', 'orphan-widget', 'direct-widget', 'direct-field', 'nested-action',
    'struct-attributes', 'shared-container', 'shared-fields'])
def test_real_or_unproven_form_containers_are_still_refused_by_the_inspector(tmp_path, variant):
    assert not inert(inert_pdf(tmp_path / 'source.pdf', variant=variant))
