"""Authored language-scope and exact-property regressions; no user acceptance."""
import copy
import json
import threading

import pikepdf
import pytest

from pdf_remediator import sidecar,language_edits,structure_edits
from pdf_remediator.inspection import compare_fidelity
from pdf_remediator.language_tags import validate_language_tag,is_language_tag


def language_pdf(path, *, container_language=None, passage_language=None,catalog_language='en-US',
                 missing_page_container=False,shared=False,inline_language=False,actual_text=False,container_role='Sect'):
    path.parent.mkdir(parents=True,exist_ok=True)
    with pikepdf.new() as pdf:
        pages=[pdf.add_blank_page(page_size=(400,500)) for _ in range(2)]
        font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))
        root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Document,P=root))
        sections=[];all_nodes=[];parents=[]
        for number,page in enumerate(pages):
            section=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name('/'+container_role),P=document))
            if number==0 and container_language is not None:section.Lang=container_language
            if number==0 and actual_text:section.ActualText='A source replacement statement'
            children=[]
            for mcid,role in enumerate(['H1','P','P']):
                node=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name('/'+role),P=section,Pg=page.obj,K=mcid))
                if number==0 and mcid==2 and passage_language is not None:node.Lang=passage_language
                children.append(node)
            section.K=pikepdf.Array(children);sections.append(section);all_nodes.extend(children)
            parents.extend([number,pikepdf.Array(children)])
            page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            texts=[f'Page {number+1} heading','Every original English word remains unchanged.','Une courte phrase francaise pour la lecture.']
            commands=[]
            for mcid,text in enumerate(texts):
                extra=' /Lang (fr)' if number==0 and mcid==1 and inline_language else ''
                commands.append(f'/{"H1" if mcid==0 else "P"} <</MCID {mcid}{extra}>> BDC BT /F1 12 Tf 40 {450-mcid*70} Td ({text}) Tj ET EMC')
            page.Contents=pdf.make_stream('\n'.join(commands).encode('ascii'));page.StructParents=number;page.Tabs=pikepdf.Name.S
        if missing_page_container:
            for node in all_nodes:node.P=document
            document.K=pikepdf.Array(all_nodes)
        else:document.K=pikepdf.Array(sections)
        if shared:
            first=all_nodes[1];second=all_nodes[4]
            first.K=pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name.MCR,Pg=pages[0].obj,MCID=1),
                pikepdf.Dictionary(Type=pikepdf.Name.MCR,Pg=pages[1].obj,MCID=1)])
            sections[1].K=pikepdf.Array([all_nodes[3],all_nodes[5]])
            parents[3][1]=first
        root.K=document;root.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(parents)));root.ParentTreeNextKey=2
        pdf.Root.StructTreeRoot=root;pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True)
        if catalog_language is not None:pdf.Root.Lang=catalog_language
        pdf.Root.ViewerPreferences=pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.docinfo.Title='Authored local-language fixture'
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    return path


def inventory(path):return sidecar.collect_decisions(path,inventory_profile=sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE)
def pick(data,kind,page=1,override=None):
    return next(i for i in data['decisions'] if i['kind']==kind and i['page']==page and
        (override is None or i['language_context']['direct']==override))
def accept(item,tag):
    item['value']=language_edits.value_for(tag);sidecar.bind_approval(item,'Synthetic local-language reviewer','2026-10-27')
def apply(path,data,tmp_path,name='result.pdf'):
    output=tmp_path/name;receipt=sidecar.apply_decisions(path,output,data,sidecar.file_sha256(path));return output,receipt
def graph_without_language(path):
    with pikepdf.open(path) as pdf:
        tree=structure_edits._snapshot(pdf)
        for node in tree['objects'].values():
            if node.get('t')=='dict' and '/S' in node.get('v',{}):node['v'].pop('/Lang',None)
        return structure_edits._canonical(structure_edits._prune(tree))


@pytest.mark.parametrize('tag',['en','en-US','fr-CA','zh-Hant','sr-Latn-RS','de-CH-1901',
    'sl-rozaj-biske-1994','en-u-ca-gregory','en-a-foo-b-bar','x-private','en-x-course',
    'i-klingon','en-GB-oed','sgn-BE-FR','zh-cmn-Hans-CN'])
def test_rfc5646_well_formed_tags_preserve_explicit_spelling(tag):
    assert validate_language_tag(tag)==tag and is_language_tag(tag)


@pytest.mark.parametrize('tag',['','en_US',' en','en ','e','en--US','en-US-US','en-12345-12345',
    'en-a','en-a-foo-a-bar','en-x','x','en-1234-1234','en-@','français',None,True,123,'en-'+'a'*9])
def test_malformed_tags_are_not_silently_repaired_or_inferred(tag):
    assert not is_language_tag(tag)
    with pytest.raises(ValueError):validate_language_tag(tag)


def test_three_existing_profiles_remain_exact_and_new_scope_context_is_explicit(tmp_path):
    path=language_pdf(tmp_path/'source.pdf',container_language='fr',passage_language='de')
    old=[sidecar.collect_decisions(path,inventory_profile=p) for p in
        [sidecar.LEGACY_INVENTORY_PROFILE,sidecar.STRUCTURAL_INVENTORY_PROFILE,sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE]]
    data=inventory(path)
    assert data['inventory_profile']=='reviewed-passage-language-3'
    assert [i for i in data['decisions'] if i['kind'] not in language_edits.KINDS]==old[2]['decisions']
    local=pick(data,'passage-language',override='de');ctx=local['language_context']
    assert ctx['direct']=='de' and ctx['inherited']=='fr' and ctx['effective']=='de'
    assert ctx['inherited_source']['kind']=='structure' and ctx['policy']==language_edits.POLICY
    page=pick(data,'page-language');assert page['current']==language_edits.value_for('fr')
    assert page['language_scope']['coverage']=={'known_references':3,'page_real_references':3,'complete_page':True}
    assert len(page['language_scope']['descendant_overrides'])==1
    assert page['language_scope']['descendant_overrides'][0]['language']=='de'
    for profile,expected in zip([sidecar.LEGACY_INVENTORY_PROFILE,sidecar.STRUCTURAL_INVENTORY_PROFILE,sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE],old):
        assert sidecar.collect_decisions(path,inventory_profile=profile)==expected


def test_passage_changes_only_its_lang_and_not_global_language_paint_or_navigation(tmp_path):
    path=language_pdf(tmp_path/'source.pdf');before=path.read_bytes();data=inventory(path);item=pick(data,'passage-language')
    assert item['structural_eligible'];accept(item,'fr-CA')
    output,receipt=apply(path,data,tmp_path)
    assert receipt['changed']==[item['id']] and path.read_bytes()==before
    assert graph_without_language(output)==graph_without_language(path)
    assert compare_fidelity(path,output)['status']=='pass'
    with pikepdf.open(output) as pdf:
        assert str(pdf.Root.Lang)=='en-US' and str(pdf.Root.StructTreeRoot.K.K[0].K[0].Lang)=='fr-CA'
        assert all('/Lang' not in page.obj for page in pdf.pages)


def test_structure_tree_root_custom_language_is_not_a_structure_element_ancestor(tmp_path):
    original=language_pdf(tmp_path/'source.pdf',passage_language='fr')
    with pikepdf.open(original) as pdf:
        pdf.Root.StructTreeRoot.Lang='de'
        path=tmp_path/'root-language.pdf'
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=inventory(path);item=pick(data,'passage-language',override='fr')
    assert item['language_context']['inherited']=='en-US'
    assert item['language_context']['inherited_source']['kind']=='document'
    accept(item,None);output,_=apply(path,data,tmp_path)
    with pikepdf.open(output) as pdf:
        assert str(pdf.Root.StructTreeRoot.Lang)=='de' and '/Lang' not in pdf.Root.StructTreeRoot.K.K[0].K[2]
    fresh=inventory(output);plain=pick(fresh,'passage-language')
    assert plain['language_context']['effective']=='en-US'


def test_page_default_preserves_explicit_passage_override_and_other_page(tmp_path):
    path=language_pdf(tmp_path/'source.pdf',passage_language='de');data=inventory(path);page=pick(data,'page-language')
    accept(page,'fr');output,_=apply(path,data,tmp_path)
    assert graph_without_language(output)==graph_without_language(path) and compare_fidelity(path,output)['status']=='pass'
    with pikepdf.open(output) as pdf:
        sections=pdf.Root.StructTreeRoot.K.K
        assert str(sections[0].Lang)=='fr' and str(sections[0].K[2].Lang)=='de'
        assert '/Lang' not in sections[1] and str(pdf.Root.Lang)=='en-US'


def test_page_and_child_inheritance_compose_with_global_language_and_container_role(tmp_path):
    path=language_pdf(tmp_path/'source.pdf',container_language='es',passage_language='de',container_role='Div');data=inventory(path)
    page=pick(data,'page-language');child=pick(data,'passage-language',override='de')
    accept(page,'fr');accept(child,None)
    global_language=next(i for i in data['decisions'] if i['kind']=='language');global_language['value']='it';sidecar.bind_approval(global_language,'Synthetic combined reviewer','2026-10-27')
    role=next(i for i in data['decisions'] if i['kind']=='structure-role' and i['element']==page['element'])
    role['value']='Sect'
    sidecar.bind_approval(role,'Synthetic combined reviewer','2026-10-27')
    output,receipt=apply(path,data,tmp_path)
    assert set(receipt['changed'])=={page['id'],child['id'],global_language['id'],role['id']}
    with pikepdf.open(output) as pdf:
        section=pdf.Root.StructTreeRoot.K.K[0]
        assert str(section.S)=='/Sect' and str(section.Lang)=='fr' and '/Lang' not in section.K[2] and str(pdf.Root.Lang)=='it'
    assert compare_fidelity(path,output)['status']=='pass'


def test_local_choices_replay_safely_with_later_title_edit_and_can_restore_original(tmp_path):
    path=language_pdf(tmp_path/'source.pdf');data=inventory(path);page=pick(data,'page-language');accept(page,'fr')
    first,_=apply(path,data,tmp_path,'first.pdf');first_bytes=first.read_bytes()
    title=next(i for i in data['decisions'] if i['kind']=='title');title['value']='An explicit later title';sidecar.bind_approval(title,'Synthetic title reviewer','2026-10-27')
    second,_=apply(path,data,tmp_path,'second.pdf')
    with pikepdf.open(second) as pdf:assert str(pdf.Root.StructTreeRoot.K.K[0].Lang)=='fr' and str(pdf.docinfo.Title)==title['value']
    assert first.read_bytes()==first_bytes and compare_fidelity(path,second)['status']=='pass'
    page['value']=page['current'];sidecar.bind_approval(page,'Synthetic reset reviewer','2026-10-27')
    title['value']=title['current'];sidecar.bind_approval(title,'Synthetic reset reviewer','2026-10-27')
    restored,receipt=apply(path,data,tmp_path,'restored.pdf')
    assert restored.read_bytes()==path.read_bytes() and not receipt['changed']


@pytest.mark.parametrize('flag',['shared','missing_page_container','inline_language','actual_text'])
def test_ambiguous_page_scope_stays_read_only_without_disabling_eligible_old_controls(tmp_path,flag):
    path=language_pdf(tmp_path/'source.pdf',**{flag:True});data=inventory(path)
    page=pick(data,'page-language')
    assert not page['structural_eligible'] and page['structural_limitations']
    with pytest.raises(sidecar.DecisionError):accept(page,'fr')
    assert next(i for i in data['decisions'] if i['kind']=='title')['status']=='pending'


@pytest.mark.parametrize('alias',['passage','page','info'])
def test_mutated_language_nodes_require_unique_source_ownership(tmp_path,alias):
    path=language_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        section=pdf.Root.StructTreeRoot.K.K[0];node=section.K[1] if alias=='passage' else section
        if alias=='info':pdf.trailer.Info=node
        else:pdf.Root.CustomAlias=node
        altered=tmp_path/'aliased.pdf'
        with altered.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=inventory(altered)
    item=(next(i for i in data['decisions'] if i['kind']=='passage-language' and i['page']==1 and any(r.get('mcid')==1 for r in i['references']))
        if alias=='passage' else pick(data,'page-language'))
    assert not item['structural_eligible']


@pytest.mark.parametrize('cross_page',[False,True])
def test_objectless_or_cross_page_descendant_language_scopes_disable_page_default(tmp_path,cross_page):
    original=language_pdf(tmp_path/'source.pdf')
    with pikepdf.open(original) as pdf:
        group=pdf.Root.StructTreeRoot.K.K[0]
        empty=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Figure,
            P=group,Alt='An objectless source alternative'))
        if cross_page:empty.Pg=pdf.pages[1].obj
        group.K.append(empty)
        source=tmp_path/'objectless.pdf'
        with source.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    page=pick(inventory(source),'page-language')
    assert not page['structural_eligible']
    assert any('descendant' in reason for reason in page['structural_limitations'])


@pytest.mark.parametrize('field',['language_context','language_scope','context_sha256','references'])
def test_resealed_context_or_capability_changes_never_authorize_local_edits(tmp_path,field):
    path=language_pdf(tmp_path/'source.pdf');data=inventory(path);item=pick(data,'passage-language');accept(item,'fr')
    if field=='context_sha256':item[field]='0'*64
    elif field=='references':item[field]=[]
    else:item[field]={'forged':True}
    item['approval_sha256']=sidecar.approval_digest(item)
    with pytest.raises(sidecar.DecisionError):apply(path,data,tmp_path)
    assert not (tmp_path/'result.pdf').exists()


def test_pending_and_automatic_language_choices_do_not_silently_apply(tmp_path):
    path=language_pdf(tmp_path/'source.pdf');data=inventory(path);item=pick(data,'passage-language')
    item['value']=language_edits.value_for('fr');output,receipt=apply(path,data,tmp_path)
    assert output.read_bytes()==path.read_bytes() and not receipt['changed']
    with pytest.raises(sidecar.DecisionError):
        sidecar.make_automatic_authorization(data['source_sha256'],data['document_sha256'],'2026-10-27',decision_ids=[item['id']])
    item['status']='auto-accepted';item['automatic_acceptance_sha256']='0'*64
    with pytest.raises(sidecar.DecisionError):apply(path,data,tmp_path,'forged.pdf')
    assert not (tmp_path/'forged.pdf').exists()


def test_graph_corruption_after_local_writer_is_independently_refused(tmp_path,monkeypatch):
    path=language_pdf(tmp_path/'source.pdf');data=inventory(path);accept(pick(data,'passage-language'),'fr')
    original=language_edits.apply_prepared
    def bad(plans,**kwargs):
        result=original(plans,**kwargs);plans[0]['node']['/S']=pikepdf.Name.Figure;return result
    monkeypatch.setattr(language_edits,'apply_prepared',bad)
    with pytest.raises(sidecar.DecisionError):apply(path,data,tmp_path)
    assert not (tmp_path/'result.pdf').exists()


def test_local_scope_cancellation_publishes_nothing(tmp_path):
    path=language_pdf(tmp_path/'source.pdf');data=inventory(path);accept(pick(data,'passage-language'),'fr')
    cancel=threading.Event();cancel.set()
    with pytest.raises(InterruptedError):sidecar.apply_decisions(path,tmp_path/'cancelled.pdf',data,sidecar.file_sha256(path),cancel=cancel)
    assert not (tmp_path/'cancelled.pdf').exists()
