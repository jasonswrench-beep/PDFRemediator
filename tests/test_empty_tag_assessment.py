"""Independent empty-looking tag assessment and advisory boundary fixtures."""
from __future__ import annotations

import copy
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator import checks, inspection, empty_tag_edits


def source_pdf(directory, *, variant='safe', shape='empty-array'):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory/'source.pdf'
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(500, 700)).obj
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        page.Contents = pdf.make_stream(b'/P <</MCID 0>> BDC BT /F1 12 Tf 40 600 Td (Retained meaningful words) Tj ET EMC')
        page.StructParents = 0
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        group = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=root))
        text = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.P, P=group, Pg=page, K=0))
        blank = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.P, P=group, Pg=page))
        if shape == 'empty-array': blank.K = pikepdf.Array()
        elif shape == 'null':
            blank = pdf.make_indirect(pikepdf.Object.parse(b'<< /Type /StructElem /S /P /K null >>'))
            blank.P = group; blank.Pg = page
        elif shape != 'absent': raise ValueError('Unknown authored empty shape')
        group.K = pikepdf.Array([text, blank]); root.K = group
        root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array([text])])))
        root.ParentTreeNextKey = 1; pdf.Root.StructTreeRoot = root
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True); pdf.Root.Lang = 'en-US'; pdf.docinfo.Title = 'Independent empty-tag example'
        if variant == 'span': blank.S = pikepdf.Name.Span
        elif variant == 'optional-type': del blank.Type; del group.Type; del text.Type
        elif variant == 'indirect-carriers': group.K = pdf.make_indirect(group.K); blank.K = pdf.make_indirect(pikepdf.Array())
        elif variant == 'no-empty': group.K = pikepdf.Array([text])
        elif variant == 'mcid-zero': blank.K = 0
        elif variant == 'dangling-mcid': blank.K = 99
        elif variant == 'dangling-mcr': blank.K = pikepdf.Dictionary(Type=pikepdf.Name.MCR, MCID=99, Pg=page)
        elif variant == 'objr':
            target = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([20, 20, 80, 30]), Dest=pikepdf.Array([page, pikepdf.Name.Fit])))
            page.Annots = pikepdf.Array([target]); blank.K = pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=target, Pg=page)
        elif variant == 'malformed-objr': blank.K = pikepdf.Dictionary(Type=pikepdf.Name.OBJR)
        elif variant == 'nested-child':
            child = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Span, P=blank))
            blank.K = pikepdf.Array([child])
        elif variant == 'null-child': blank.K = pikepdf.Array([None])
        elif variant.startswith('protected-'):
            blank['/'+variant.split('-', 1)[1]] = pikepdf.String('Preserved interpretation')
        elif variant == 'empty-actualtext': blank.ActualText = pikepdf.String('')
        elif variant == 'whitespace-alt': blank.Alt = pikepdf.String('   ')
        elif variant == 'parenttree-reference': root.ParentTree.Nums[1].append(blank)
        elif variant == 'idtree-reference': root.IDTree = pikepdf.Dictionary(Names=pikepdf.Array(['Protected', blank]))
        elif variant == 'leaf-alias': pdf.Root.Protected = blank
        elif variant == 'info-alias': pdf.trailer.Info = blank
        elif variant == 'parent-alias': pdf.Root.Protected = group
        elif variant == 'empty-carrier-alias': blank.K = pdf.make_indirect(pikepdf.Array()); pdf.Root.Protected = blank.K
        elif variant == 'parent-carrier-alias': group.K = pdf.make_indirect(group.K); pdf.Root.Protected = group.K
        elif variant == 'semantic-ancestor': group.S = pikepdf.Name.Table
        elif variant == 'ancestor-alt': group.Alt = 'Protected ancestor interpretation'
        elif variant == 'ancestor-language': group.Lang = 'fr-FR'
        elif variant == 'remapped-role': root.RoleMap = pikepdf.Dictionary(P=pikepdf.Name.Span)
        elif variant == 'only-empty': group.K = pikepdf.Array([blank]); page.Contents = pdf.make_stream(b''); root.ParentTree.Nums[1] = pikepdf.Array()
        elif variant == 'unpainted-survivor': page.Contents = pdf.make_stream(b'/P <</MCID 0>> BDC EMC')
        elif variant == 'wrong-survivor-parenttree': root.ParentTree.Nums[1][0] = blank
        elif variant == 'duplicate-child': group.K.append(blank)
        elif variant == 'wrong-parent': blank.P = root
        elif variant == 'cycle': blank.K = pikepdf.Array([blank])
        elif variant == 'unknown-child': blank.K = pikepdf.Name.Unknown
        elif variant == 'signature-authority': pdf.Root.Perms = pikepdf.Dictionary()
        elif variant == 'script-authority': pdf.Root.Protected = pikepdf.Dictionary(JS='Unexecuted code')
        elif variant == 'form-authority': pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array())
        elif variant != 'safe': raise ValueError('Unknown authored assessment variant')
        target = str(blank.objgen[0])+':'+str(blank.objgen[1])
        # The saved IDs may be renumbered. A private inert identity string is
        # unnecessary: the test resolves the second child from the saved tree.
        with path.open('xb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7')
    return path


def assessed(path):
    original = path.read_bytes(); report = inspection.inspect_pdf(path)
    assert path.read_bytes() == original and not report.get('error'), report.get('error')
    screen = report['empty_tags']
    assert screen['policy'] == 'bounded-empty-structure-1' and screen['advisory'] is True
    return report, screen


@pytest.mark.parametrize('shape', ['absent', 'null', 'empty-array'])
@pytest.mark.parametrize('variant', ['safe', 'span', 'optional-type', 'indirect-carriers'])
def test_only_literal_empty_leaf_shapes_with_proved_survivors_overlap_the_editor(tmp_path, shape, variant):
    source = source_pdf(tmp_path, shape=shape, variant=variant); report, screen = assessed(source)
    assert screen['status'] == 'fail' and screen['counts']['empty'] == 1, screen
    row = screen['findings'][0]
    assert row['safely_empty'] is True and row['editable_candidate'] is True
    assert row['k_shape'] in {'absent', 'null', 'empty-array'}
    assert row['nonempty_siblings'] and row['limitations'] == []
    with pikepdf.open(source) as pdf:
        candidates, _, errors = empty_tag_edits.inventory(pdf)
        assert errors == []
        actual = next(item for item in candidates if item['structural_eligible'])
        assert actual['element'] == row['element']
        assert actual['empty_tag_context']['source']['k_shape'] == row['k_shape']
    assessed_checks = checks.assess(report)
    check = next(item for item in assessed_checks['checks'] if item['id'] == 'empty-structure-tags')
    assert check['blocking'] is False and check['severity'] == 'advisory'
    assert 'empty-structure-tags' not in assessed_checks['blocking_checks']
    manual = next(item for item in assessed_checks['manual_queue'] if item['category'] == 'empty-tags')
    assert manual['status'] == 'pending' and manual['required'] is True and manual['evidence'] == screen
    assert not any(item['id'] == 'empty-structure-tags' for item in report['checks'])


@pytest.mark.parametrize('variant', ['mcid-zero', 'dangling-mcid', 'dangling-mcr', 'objr', 'malformed-objr', 'nested-child', 'null-child', 'unknown-child'])
def test_content_and_object_reference_shapes_never_turn_into_empty_leaf_candidates(tmp_path, variant):
    source = source_pdf(tmp_path, variant=variant); _, screen = assessed(source)
    with pikepdf.open(source) as pdf:
        node = pdf.Root.StructTreeRoot.K.K[1]; target = f'{node.objgen[0]}:{node.objgen[1]}'
    assert target not in {item['element'] for item in screen['findings']}
    assert all(item['k_shape'] in {'absent', 'null', 'empty-array'} for item in screen['findings'])
    if variant in {'dangling-mcid', 'dangling-mcr', 'malformed-objr', 'null-child', 'unknown-child'}:
        assert screen['coverage']['complete'] is False and screen['status'] == 'needs-review'


@pytest.mark.parametrize('variant', ['protected-Alt', 'protected-ActualText', 'protected-E', 'protected-ID',
    'protected-Ref', 'protected-AF', 'protected-A', 'protected-C', 'protected-R', 'protected-NS', 'protected-Lang',
    'protected-T', 'empty-actualtext', 'whitespace-alt', 'parenttree-reference', 'idtree-reference', 'leaf-alias',
    'info-alias', 'empty-carrier-alias'])
def test_replacement_descriptions_and_independent_reference_authority_are_protected_even_if_text_is_blank(tmp_path, variant):
    _, screen = assessed(source_pdf(tmp_path, variant=variant))
    assert screen['findings'] == []
    assert screen['uncertain'] and screen['counts']['protected'] == 1
    assert screen['status'] == 'needs-review' and screen['coverage']['complete'] is False
    assert all(item['safely_empty'] is False for item in screen['uncertain'])


@pytest.mark.parametrize('variant', ['parent-alias', 'parent-carrier-alias', 'semantic-ancestor', 'ancestor-alt',
    'ancestor-language', 'remapped-role', 'only-empty', 'unpainted-survivor', 'wrong-survivor-parenttree',
    'duplicate-child', 'wrong-parent', 'cycle', 'signature-authority', 'script-authority', 'form-authority'])
def test_unproved_ancestry_survivors_or_document_authority_never_receive_editable_credit(tmp_path, variant):
    _, screen = assessed(source_pdf(tmp_path, variant=variant))
    assert not any(item['editable_candidate'] for item in screen['findings'])
    assert screen['status'] in {'fail', 'needs-review'}


def test_a_complete_empty_free_screen_does_not_add_an_empty_tag_review(tmp_path):
    report, screen = assessed(source_pdf(tmp_path, variant='no-empty'))
    assert screen['status'] == 'pass' and screen['findings'] == screen['uncertain'] == []
    assert screen['coverage']['complete'] is True
    result = checks.assess(report)
    assert not any(item['category'] == 'empty-tags' for item in result['manual_queue'])


def test_advisory_unknown_reports_and_forged_clean_status_cannot_remove_manual_review(tmp_path):
    report, _ = assessed(source_pdf(tmp_path, variant='no-empty'))
    for key, policy in [('empty_tags', 'bounded-empty-structure-1'), ('small_font', 'bounded-small-font-1')]:
        for change in ['unknown-policy', 'forged-clean', 'missing']:
            modified = copy.deepcopy(report)
            if change == 'unknown-policy': modified[key]['policy'] = 'unknown-screen'
            elif change == 'forged-clean': modified[key].update(status='pass', coverage={'complete': False})
            else: del modified[key]
            result = checks.assess(modified)
            category = 'empty-tags' if key == 'empty_tags' else 'small-fonts'
            row_name = 'empty-structure-tags' if key == 'empty_tags' else 'small-font'
            row = next(item for item in result['checks'] if item['id'] == row_name)
            assert row['blocking'] is False and row['status'] in {'needs-review', 'not-tested'}
            assert any(item['category'] == category and item['required'] for item in result['manual_queue'])


def test_small_font_measurements_are_nonblocking_and_only_findings_or_unknown_create_their_review(tmp_path):
    report, _ = assessed(source_pdf(tmp_path, variant='no-empty'))
    assert report['small_font']['status'] == 'pass', report['small_font']
    assert not any(item['category'] == 'small-fonts' for item in checks.assess(report)['manual_queue'])
    changed = copy.deepcopy(report); screen = changed['small_font']
    screen['status'] = 'fail'; screen['findings'] = [{'page': 1, 'effective_pt': 8, 'sample': 'Small source words'}]
    result = checks.assess(changed)
    row = next(item for item in result['checks'] if item['id'] == 'small-font')
    assert row['blocking'] is False and row['severity'] == 'advisory'
    assert row not in result['blockers'] and 'small-font' not in result['blocking_checks']
    assert any(item['category'] == 'small-fonts' and item['required'] for item in result['manual_queue'])
