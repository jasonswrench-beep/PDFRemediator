"""Independent authored language-scope screens; no external service or OCR."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import textwrap
import threading

import pikepdf
import pypdfium2 as pdfium
import pytest
from reportlab.pdfgen import canvas

from pdf_remediator import inspection
from pdf_remediator.language import assess_language
from pdf_remediator.language_scopes import assess_language_scopes
from test_language import TEXTS
from test_pipeline import tagged_control


@pytest.fixture(autouse=True)
def registered_language_fonts(tagged_control):
    return tagged_control


def language_scope_pdf(path, *, languages=("fr", "fr"), body_languages=("fr", "fr"),
                       catalog="en-US", declarations=True, inline=False, form=False,
                       unowned=False, actual_text=False, malformed=False, nested=False):
    """Two real pages with English default, authored tags and optional hazards."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=path.with_name(path.stem+'-paint.pdf')
    c=canvas.Canvas(str(raw),pagesize=(460,640),invariant=1)
    c.setTitle('Authored mixed-language preservation control')
    for index,body_language in enumerate(body_languages):
        destination='opening' if index==0 else 'continuation'
        c.bookmarkPage(destination);c.addOutlineEntry('Page '+str(index+1),destination,level=0)
        title='La recherche collective' if body_language=='fr' else 'Community research'
        c._code.append('/H1 <</MCID 0>> BDC')
        c.setFont('SyntheticVera',15);c.drawString(28,603,title);c._code.append('EMC')
        c._code.append('/P <</MCID 1>> BDC')
        if inline:c._code.append('/Span <</Lang (fr)>> BDC')
        if form:
            c.beginForm('language-form-'+str(index),0,0,460,640)
        c.setFont('SyntheticVera',9)
        for line_number,line in enumerate(textwrap.wrap(TEXTS[body_language],width=84)):
            c.drawString(28,570-line_number*13,line)
        if form:
            c.endForm();c.doForm('language-form-'+str(index))
        if inline:c._code.append('EMC')
        c._code.append('EMC')
        if unowned:
            c.setFont('SyntheticVera',9)
            for line_number,line in enumerate(textwrap.wrap(TEXTS['fr'],width=84)):
                c.drawString(28,310-line_number*13,line)
        if index==1:
            c._code.append('/Link <</MCID 2>> BDC')
            c.setFont('SyntheticVera',9)
            c.drawString(28,45,'Retour à la première page' if body_language=='fr' else 'Return to first page')
            c._code.append('EMC')
        c.showPage()
    c.save()
    with pikepdf.open(raw) as pdf:
        tree=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Document,P=tree))
        sections=[];numbers=[]
        for index,page in enumerate(pdf.pages):
            section=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Sect,
                P=document,Pg=page.obj,T='Authored page '+str(index+1)))
            if declarations and languages[index] is not None:section.Lang=languages[index]
            heading=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.H1,P=section,Pg=page.obj,K=0))
            paragraph=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.P,P=section,Pg=page.obj,K=1))
            if actual_text:paragraph.ActualText=TEXTS['fr']
            if malformed:section.Lang=pikepdf.Name('/private-invalid-language-SECRET')
            if nested:
                span=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Span,
                    P=paragraph,Pg=page.obj,K=1,Lang='fr'))
                paragraph.K=span
                owners=[heading,span]
            else:owners=[heading,paragraph]
            children=[heading,paragraph]
            if index==1:
                link=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Link,P=section,Pg=page.obj))
                annotation=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.Link,
                    Rect=pikepdf.Array([28,40,235,57]),Contents='Return to first page',NM='language-preserved-link',
                    Border=pikepdf.Array([0,0,0]),C=pikepdf.Array([0,0,1]),F=4,
                    Dest=pikepdf.Array([pdf.pages[0].obj,pikepdf.Name.Fit]),StructParent=2))
                page.Annots=pikepdf.Array([annotation])
                link.K=pikepdf.Array([2,pikepdf.Dictionary(Type=pikepdf.Name.OBJR,Pg=page.obj,Obj=annotation)])
                children.append(link);owners.append(link)
            section.K=pikepdf.Array(children);sections.append(section)
            page.StructParents=index;page.Tabs=pikepdf.Name.S
            numbers.extend([index,pikepdf.Array(owners)])
        document.K=pikepdf.Array(sections);tree.K=document
        numbers.extend([2,link])
        tree.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(numbers)))
        tree.ParentTreeNextKey=3
        pdf.Root.StructTreeRoot=tree;pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True)
        if catalog is not None:pdf.Root.Lang=catalog
        pdf.Root.ViewerPreferences=pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.Root.PageLabels=pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Dictionary(S=pikepdf.Name.r),1,pikepdf.Dictionary(S=pikepdf.Name.D,St=4)]))
        pdf.Root.Names=pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([
            'first-language-page',pikepdf.Array([pdf.pages[0].obj,pikepdf.Name.Fit])])))
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    return path


def language_check(path):
    result=inspection.inspect_pdf(path)
    assert not result.get('error'),result.get('error')
    return next(item for item in result['checks'] if item['id']=='language-correctness'),result


def global_expected(path,catalog):
    samples=[]
    with pdfium.PdfDocument(str(path)) as pdf:
        for page in pdf:
            try:
                text=page.get_textpage()
                try:samples.append(text.get_text_range()[:2000])
                finally:text.close()
            finally:page.close()
    result=assess_language('\n\n'.join(samples)[:100000],catalog)
    result['sampling']={'sampled_pages':[1,2],'total_pages':2,'maximum_pages':50,
        'maximum_characters_per_page':2000,'maximum_total_characters':100000,'complete_document_text_assessed':False}
    return result


def test_no_local_declarations_return_the_original_result_without_opening_a_pdf():
    raw={'status':'fail','suggested_language':'fr','sampling':{'declared-old-scope':True}}
    assert assess_language_scopes('never-open-this.pdf',None,raw,sampled_pages=[],structure={},owners={},
        elements={},parent_tree={},page_contents={}) is raw


@pytest.mark.parametrize('catalog,body,status,suggestion',[('en-US','en','pass',None),('en-US','fr','fail','fr')])
def test_global_only_screen_and_sampling_are_byte_exact(tmp_path,catalog,body,status,suggestion):
    path=language_scope_pdf(tmp_path/'global.pdf',catalog=catalog,declarations=False,body_languages=(body,body))
    check,report=language_check(path)
    assert check['evidence']==global_expected(path,catalog)
    assert check['status']==status and check['evidence']['suggested_language']==suggestion
    assert all('language_override_signals' not in row['content'] for row in report['pages'])


def test_correct_declared_french_pages_do_not_inherit_false_english_global_blocker(tmp_path):
    path=language_scope_pdf(tmp_path/'french-local.pdf')
    check,_=language_check(path);evidence=check['evidence']
    assert evidence['raw_global_diagnostic']['assessment']['status']=='fail'
    assert evidence['raw_global_diagnostic']['assessment']['suggested_language']=='fr'
    assert check['status']=='pass' and evidence['suggested_language'] is None
    assert evidence['evidence']['sampled_selectable_text_coverage_complete'] is True
    scopes=evidence['evidence']['scopes']
    assert len(scopes)==2 and all(item['status']=='pass' and item['declared_language']=='fr' for item in scopes)
    assert [item['pages'] for item in scopes]==[[1],[2]]
    assert 'page or passage' in check['fix_path'] and 'Document language' not in check['fix_path']


def test_mixed_correct_pages_use_their_declared_and_inherited_languages(tmp_path):
    path=language_scope_pdf(tmp_path/'mixed.pdf',languages=(None,'fr'),body_languages=('en','fr'))
    check,_=language_check(path);evidence=check['evidence']
    assert check['status']=='pass' and evidence['suggested_language'] is None
    assert {item['declared_language'] for item in evidence['evidence']['scopes']}=={'en-US','fr'}
    assert all(item['status']=='pass' for item in evidence['evidence']['scopes'])


@pytest.mark.parametrize('activated',[False,True])
def test_tree_root_and_its_custom_parent_cannot_supply_inherited_language(tmp_path,activated):
    original=language_scope_pdf(tmp_path/'tree-root-paint.pdf',languages=(None,'en'),
        body_languages=('en','en'),declarations=activated)
    path=tmp_path/'off-tag-language.pdf'
    with pikepdf.open(original) as pdf:
        tree=pdf.Root.StructTreeRoot
        tree.Lang='de'
        tree.P=pdf.make_indirect(pikepdf.Dictionary(Lang='fr'))
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    check,_=language_check(path)
    assert check['status']=='pass'
    if activated:
        scopes=check['evidence']['evidence']['scopes']
        inherited=[scope for scope in scopes if scope['pages']==[1]]
        assert len(inherited)==1 and inherited[0]['declared_language']=='en-US'
        assert inherited[0]['declaration_origins']==['catalog']
        assert {scope['declared_language'] for scope in scopes}=={'en-US','en'}
    else:
        assert check['evidence']==global_expected(path,'en-US')


def test_explicit_non_structelem_dictionary_cannot_supply_proven_language(tmp_path):
    original=language_scope_pdf(tmp_path/'valid.pdf')
    path=tmp_path/'invalid-language-ancestor.pdf'
    with pikepdf.open(original) as pdf:
        pdf.Root.StructTreeRoot.K.K[0].Type=pikepdf.Name('/CustomLanguageContainer')
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    check,_=language_check(path)
    evidence=check['evidence']['evidence']
    assert check['status']=='fail' and evidence['unproven_sample_characters']>0
    assert 'invalid-structure-language-scope' in evidence['unproven']['reasons']


def test_good_english_page_cannot_mask_a_french_page_explicitly_mislabeled_english(tmp_path):
    path=language_scope_pdf(tmp_path/'wrong-local.pdf',languages=('en-US','en-US'),body_languages=('en','fr'))
    check,_=language_check(path);evidence=check['evidence']
    assert check['status']=='fail' and evidence['suggested_language'] is None
    failed=[item for item in evidence['evidence']['scopes'] if item['status']=='fail']
    assert len(failed)==1 and failed[0]['pages']==[2]
    assert failed[0]['assessment']['suggested_language']=='fr'


def test_direct_child_language_has_precedence_over_its_wrong_parent(tmp_path):
    path=language_scope_pdf(tmp_path/'nested.pdf',languages=('en','en'),nested=True)
    check,_=language_check(path);scopes=check['evidence']['evidence']['scopes']
    french=[item for item in scopes if item['declared_language']=='fr']
    assert len(french)==2 and all(item['status']=='pass' for item in french)
    assert all(item['declaration_origins'][0]!='catalog' for item in french)
    assert check['status']=='needs-review' # Short wrongly inherited headings are not guessed.


@pytest.mark.parametrize('hazard',['inline','form','actual_text','malformed'])
def test_unsupported_or_invalid_local_scope_is_never_presumed_agreement(tmp_path,hazard):
    path=language_scope_pdf(tmp_path/'unproven.pdf',**{hazard:True})
    check,_=language_check(path);evidence=check['evidence']['evidence']
    assert check['status'] in {'fail','needs-review'}
    assert evidence['unproven_sample_characters']>0
    assert not evidence['sampled_selectable_text_coverage_complete']
    assert evidence['unproven']['reasons']
    assert check['evidence']['suggested_language'] is None
    assert 'private-invalid-language-SECRET' not in json.dumps(check['evidence'])


def test_inline_only_language_signal_does_not_silently_use_old_global_agreement(tmp_path):
    path=language_scope_pdf(tmp_path/'inline-only.pdf',declarations=False,inline=True)
    check,report=language_check(path)
    assert check['evidence']['profile']=='local-declared-language-scopes-1'
    assert check['status']=='fail'
    assert check['evidence']['evidence']['inline_override_pages']==[1,2]
    assert all(row['content']['language_override_signals'] for row in report['pages'])


def test_unowned_french_text_is_not_hidden_by_a_valid_local_english_declaration(tmp_path):
    path=language_scope_pdf(tmp_path/'unknown.pdf',languages=('en','en'),body_languages=('en','en'),unowned=True)
    check,_=language_check(path);evidence=check['evidence']['evidence']
    assert check['status']=='fail'
    assert evidence['unproven_sample_characters']>0
    assert evidence['unproven']['catalog_screen']['status']=='fail'


@pytest.mark.parametrize('catalog',[None,'en_US'])
def test_local_agreement_never_clears_missing_or_invalid_catalog_metadata(tmp_path,catalog):
    path=language_scope_pdf(tmp_path/'metadata.pdf',catalog=catalog)
    check,report=language_check(path)
    assert check['status']=='pass'
    metadata=next(item for item in report['checks'] if item['id']=='metadata')
    if catalog is None:assert metadata['status']=='fail'
    from pdf_remediator.checks import assess
    assessed=assess(report)
    assert assessed['status']=='fail'
    assert any(item['id']=='metadata' for item in assessed['blockers'])


def test_scoped_evidence_contains_no_document_excerpts_and_is_json_portable(tmp_path):
    path=language_scope_pdf(tmp_path/'private.pdf')
    check,_=language_check(path)
    raw=json.dumps(check['evidence'],ensure_ascii=False)
    assert 'communauté' not in raw and 'quartier' not in raw and 'La recherche collective' not in raw
    assert json.loads(raw)==check['evidence']


def test_pre_cancelled_scope_analysis_does_not_open_pdfium(tmp_path):
    path=language_scope_pdf(tmp_path/'cancel.pdf')
    token=threading.Event();token.set()
    with pikepdf.open(path) as pdf:
        number={inspection._id(page.obj):index for index,page in enumerate(pdf.pages,1)}
        structure,owners,_,elements,tree=inspection._structure(pdf,number)
        raw=global_expected(path,'en-US')
        with pytest.raises(InterruptedError):
            assess_language_scopes(path,pdf,raw,sampled_pages=[1,2],structure=structure,owners=owners,
                elements=elements,parent_tree=tree,page_contents={},cancel=token)
