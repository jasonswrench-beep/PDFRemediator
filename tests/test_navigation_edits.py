"""Independent authored mechanics for reviewed names, targets and bookmarks."""
import copy
import json
import threading

import pikepdf
import pytest

from pdf_remediator import sidecar,navigation_edits as navigation,structure_edits
from test_language_edits import language_pdf


def navigation_pdf(path,*,missing_target=False,broken_named_target=False,unsafe_action=False,
                   shared_annotation=False,shared_action=False,link_alias=False,rich_text=False,with_bookmarks=True,
                   blank_bookmark=False,direct_destination_dict=False,multi_page_link=False):
    temporary=path.parent/('build-'+path.name);language_pdf(temporary)
    with pikepdf.open(temporary) as pdf:
        page=pdf.pages[0];tree=pdf.Root.StructTreeRoot;link=tree.K.K[0].K[1]
        annotation=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([35,360,360,400]),Border=pikepdf.Array([0,0,0]),P=page.obj,
            Contents='Original annotation name',StructParent=100))
        if broken_named_target:annotation.Dest=pikepdf.String('missing-target')
        elif unsafe_action:annotation.A=pikepdf.Dictionary(S=pikepdf.Name.JavaScript,JS='void(0)')
        elif not missing_target:annotation.A=pdf.make_indirect(pikepdf.Dictionary(S=pikepdf.Name.URI,URI='https://example.invalid/original'))
        if rich_text:annotation.RC='<p>Original rich text</p>'
        if direct_destination_dict:
            if '/A' in annotation:del annotation['/A']
            annotation.Dest=pikepdf.Dictionary(D=pikepdf.Array([pdf.pages[1].obj,pikepdf.Name.Fit]))
        comment=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.Text,
            Rect=pikepdf.Array([350,450,370,470]),P=page.obj,Contents='Original comment'))
        page.Annots=pikepdf.Array([annotation,comment])
        if shared_annotation:pdf.pages[1].Annots=pikepdf.Array([annotation])
        if shared_action and '/A' in annotation:pdf.Root.CustomAction=annotation.A
        link.S=pikepdf.Name.Link;link.Alt='Original structure name'
        link.K=pikepdf.Array([link.K,pikepdf.Dictionary(Type=pikepdf.Name.OBJR,Obj=annotation,Pg=page.obj)])
        tree.ParentTree.Nums.append(100);tree.ParentTree.Nums.append(link);tree.ParentTreeNextKey=101
        if multi_page_link:
            link.K.append(pikepdf.Dictionary(Type=pikepdf.Name.MCR,Pg=pdf.pages[1].obj,MCID=1))
            section=tree.K.K[1];section.K=pikepdf.Array([section.K[0],section.K[2]])
            tree.ParentTree.Nums[3][1]=link
        if link_alias:pdf.docinfo.CustomLink=link
        if with_bookmarks:
            root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines))
            first=pdf.make_indirect(pikepdf.Dictionary(Title='Original first',Parent=root,Dest=pikepdf.String('chapter-one'),C=pikepdf.Array([0,0,1]),F=2))
            if blank_bookmark:first.Title='   '
            child=pdf.make_indirect(pikepdf.Dictionary(Title='Existing closed child',Parent=first,Dest=pikepdf.Array([pdf.pages[1].obj,pikepdf.Name.Fit])))
            second=pdf.make_indirect(pikepdf.Dictionary(Title='Original second',Parent=root,Dest=pikepdf.Array([pdf.pages[1].obj,pikepdf.Name.Fit])))
            first.First=child;first.Last=child;first.Count=-1;first.Next=second;second.Prev=first
            root.First=first;root.Last=second;root.Count=2;pdf.Root.Outlines=root
            pdf.Root.Names=pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String('chapter-one'),pikepdf.Array([page.obj,pikepdf.Name.XYZ,0,450,None])])))
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    return path


def inventory(path):return sidecar.collect_decisions(path,inventory_profile=sidecar.NAVIGATION_INVENTORY_PROFILE)
def pick(data,kind):return next(item for item in data['decisions'] if item['kind']==kind)
def accept(item,value):
    item['value']=value if isinstance(value,str) else navigation.canonical_value(value)
    sidecar.bind_approval(item,'Developer navigation fixture','2026-10-27')
def apply(path,data,tmp_path,name='result.pdf'):
    out=tmp_path/name;receipt=sidecar.apply_decisions(path,out,data,sidecar.file_sha256(path));return out,receipt


def test_four_previous_profiles_remain_exact_and_navigation_names_are_separate(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf');data=inventory(path)
    old=sidecar.collect_decisions(path,inventory_profile=sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE)
    assert [i for i in data['decisions'] if i['kind'] not in navigation.KINDS]==old['decisions']
    assert data['inventory_profile']=='reviewed-navigation-4' and not data['inventory_errors']
    assert pick(data,'annotation-name')['current']=='Original annotation name'
    assert pick(data,'link-name')['current']=='Original structure name'
    assert pick(data,'annotation-name')['structural_eligible'] and pick(data,'link-name')['structural_eligible']
    assert pick(data,'link-target')['navigation_context']['source_target']=={'kind':'uri','uri':'https://example.invalid/original'}
    assert pick(data,'bookmark-additions')['navigation_context']['existing_bookmarks']==3
    for profile in [sidecar.LEGACY_INVENTORY_PROFILE,sidecar.STRUCTURAL_INVENTORY_PROFILE,sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE,sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE]:
        first=sidecar.collect_decisions(path,inventory_profile=profile)
        assert all(item['kind'] not in navigation.KINDS and 'navigation_context' not in item for item in first['decisions'])
        assert sidecar.collect_decisions(path,inventory_profile=profile)==first


@pytest.mark.parametrize('kind,field',[('annotation-name','/Contents'),('link-name','/Alt')])
def test_reviewed_names_change_only_the_selected_own_property(tmp_path,kind,field):
    path=navigation_pdf(tmp_path/'source.pdf');original=path.read_bytes();data=inventory(path);item=pick(data,kind)
    accept(item,'Reviewed meaningful destination name');out,receipt=apply(path,data,tmp_path)
    assert path.read_bytes()==original and receipt['changed']==[item['id']]
    with pikepdf.open(out) as pdf:
        annotation=pdf.pages[0].Annots[0];link=pdf.Root.StructTreeRoot.K.K[0].K[1]
        assert str((annotation if kind=='annotation-name' else link)[field])=='Reviewed meaningful destination name'
        assert str(link.Alt if kind=='annotation-name' else annotation.Contents)==('Original structure name' if kind=='annotation-name' else 'Original annotation name')
        assert str(annotation.A.URI)=='https://example.invalid/original'


@pytest.mark.parametrize('target',[{'kind':'page','page':2},{'kind':'uri','uri':'https://example.invalid/reviewed#section'},{'kind':'uri','uri':'mailto:help@example.invalid?subject=Course'}])
def test_explicit_link_targets_retain_geometry_paint_and_names(tmp_path,target):
    path=navigation_pdf(tmp_path/'source.pdf');data=inventory(path);item=pick(data,'link-target');accept(item,target)
    out,receipt=apply(path,data,tmp_path)
    assert receipt['changed']==[item['id']]
    with pikepdf.open(path) as before,pikepdf.open(out) as after:
        old,new=before.pages[0].Annots[0],after.pages[0].Annots[0]
        assert list(old.Rect)==list(new.Rect) and bytes(old.Contents)==bytes(new.Contents)
        assert bytes(before.Root.StructTreeRoot.K.K[0].K[1].Alt)==bytes(after.Root.StructTreeRoot.K.K[0].K[1].Alt)
        assert before.pages[0].Contents.read_bytes()==after.pages[0].Contents.read_bytes()
        if target['kind']=='page':assert '/A' not in new and new.Dest[0].objgen==after.pages[1].obj.objgen
        else:assert '/Dest' not in new and str(new.A.URI)==target['uri']


@pytest.mark.parametrize('flag',['missing_target','broken_named_target'])
def test_missing_or_unresolved_passive_target_can_be_explicitly_repaired(tmp_path,flag):
    path=navigation_pdf(tmp_path/'source.pdf',**{flag:True});data=inventory(path);item=pick(data,'link-target')
    assert item['structural_eligible'] and item['navigation_context']['source_target']['kind'] in {'none','unresolved'}
    accept(item,{'kind':'page','page':2});out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:assert pdf.pages[0].Annots[0].Dest[0].objgen==pdf.pages[1].obj.objgen


def test_title_only_bookmark_edit_keeps_exact_named_target_and_style(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf');data=inventory(path);item=pick(data,'bookmark-entry')
    accept(item,{'title':'Reviewed chapter title','target':item['navigation_context']['source_target']})
    out,_=apply(path,data,tmp_path)
    with pikepdf.open(path) as before,pikepdf.open(out) as after:
        old,new=before.Root.Outlines.First,after.Root.Outlines.First
        assert bytes(old.Dest)==bytes(new.Dest)==b'chapter-one' and '/A' not in new
        assert list(old.C)==list(new.C) and old.F==new.F and new.Count==-1
        assert str(new.Title)=='Reviewed chapter title' and str(new.First.Title)=='Existing closed child'


def test_target_only_bookmark_edit_keeps_original_title_encoding_bytes(tmp_path):
    original=navigation_pdf(tmp_path/'source.pdf');path=tmp_path/'utf16-title.pdf'
    encoded=b'\xfe\xff'+'Original first'.encode('utf-16-be')
    with pikepdf.open(original) as pdf:
        pdf.Root.Outlines.First.Title=pikepdf.String(encoded)
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=inventory(path);item=pick(data,'bookmark-entry');accept(item,{'title':'Original first','target':{'kind':'page','page':2}})
    out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:assert bytes(pdf.Root.Outlines.First.Title)==encoded and pdf.Root.Outlines.First.Dest[0].objgen==pdf.pages[1].obj.objgen


def test_blank_existing_bookmark_title_can_be_repaired_without_changing_its_target(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf',blank_bookmark=True);data=inventory(path);item=pick(data,'bookmark-entry')
    assert item['structural_eligible'] and json.loads(item['current'])['title']=='   '
    accept(item,{'title':'Meaningful new chapter name','target':{'kind':'page','page':1}})
    out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:assert str(pdf.Root.Outlines.First.Title)=='Meaningful new chapter name' and bytes(pdf.Root.Outlines.First.Dest)==b'chapter-one'


def test_malformed_direct_destination_dictionary_can_be_repaired_at_same_page(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf',direct_destination_dict=True);data=inventory(path);item=pick(data,'link-target')
    assert item['structural_eligible'] and item['navigation_context']['source_target']['kind']=='unresolved'
    accept(item,{'kind':'page','page':2});out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:assert isinstance(pdf.pages[0].Annots[0].Dest,pikepdf.Array)


def test_cross_page_link_scope_keeps_structure_name_read_only_but_does_not_disable_own_annotation_name(tmp_path):
    data=inventory(navigation_pdf(tmp_path/'source.pdf',multi_page_link=True))
    assert pick(data,'annotation-name')['structural_eligible']
    item=pick(data,'link-name');assert not item['structural_eligible'] and any('cross-page' in x for x in item['structural_limitations'])


@pytest.mark.parametrize('existing',[True,False])
def test_append_new_bookmark_forest_preserves_old_hierarchy_and_counts(tmp_path,existing):
    path=navigation_pdf(tmp_path/'source.pdf',with_bookmarks=existing);data=inventory(path)
    accept(pick(data,'bookmark-additions'),{'entries':[{'title':'New chapter','page':1,'level':1},{'title':'New subsection','page':2,'level':2},{'title':'New sibling','page':2,'level':1}]})
    out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:
        root=pdf.Root.Outlines;first=root.First;newfirst=first.Next.Next if existing else first
        assert str(newfirst.Title)=='New chapter' and str(newfirst.First.Title)=='New subsection' and newfirst.Count==1
        assert newfirst.First.Parent.objgen==newfirst.objgen and str(newfirst.Next.Title)=='New sibling'
        assert root.Count==(5 if existing else 3) and root.Last.objgen==newfirst.Next.objgen
        assert '/PageMode' not in pdf.Root
        if existing:assert str(first.Title)=='Original first' and first.Count==-1 and str(first.First.Title)=='Existing closed child'


def test_navigation_edits_compose_with_page_language_title_and_container_role(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf');data=inventory(path)
    accept(pick(data,'annotation-name'),'Reviewed annotation description');accept(pick(data,'link-name'),'Reviewed structure name')
    accept(pick(data,'link-target'),{'kind':'page','page':2})
    accept(pick(data,'bookmark-additions'),{'entries':[{'title':'New reviewed section','page':2,'level':1}]})
    title=pick(data,'title');title['value']='Reviewed document';sidecar.bind_approval(title,'Developer navigation fixture','2026-10-27')
    page=next(i for i in data['decisions'] if i['kind']=='page-language' and i['page']==2)
    page['value']='{"language":"fr"}';sidecar.bind_approval(page,'Developer navigation fixture','2026-10-27')
    out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:
        assert str(pdf.docinfo.Title)=='Reviewed document' and str(pdf.Root.StructTreeRoot.K.K[1].Lang)=='fr'
        assert str(pdf.pages[0].Annots[0].Contents)=='Reviewed annotation description' and str(pdf.Root.Outlines.Last.Title)=='New reviewed section'


@pytest.mark.parametrize('value',[{'kind':'page','page':0},{'kind':'page','page':3},{'kind':'page','page':True},{'kind':'uri','uri':'javascript:alert(1)'},{'kind':'uri','uri':'file:///x'},{'kind':'uri','uri':'https://u:p@example.invalid'},{'kind':'uri','uri':'https://example.invalid/%zz'},{'kind':'uri','uri':'mailto:a@example.invalid%0d%0abcc:b@example.invalid'},{'kind':'uri','uri':'https://example.invalid\\x'},{'kind':'uri','uri':'https://example.invalid/has space'},{'kind':'page','page':1,'extra':True}])
def test_invalid_or_active_target_values_are_refused(tmp_path,value):
    item=pick(inventory(navigation_pdf(tmp_path/'source.pdf')),'link-target')
    item['value']=navigation.canonical_value(value)
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer navigation fixture','2026-10-27')


@pytest.mark.parametrize('entries',[[{'title':'Skipped first level','page':1,'level':2}],[{'title':'Too deep','page':1,'level':11}],[{'title':'','page':1,'level':1}],[{'title':'Wrong page','page':0,'level':1}],[{'title':'Wrong flag','page':1,'level':True}],[{'title':'One','page':1,'level':1},{'title':'Three','page':2,'level':3}]])
def test_invalid_bookmark_forest_is_not_inferred_or_repaired(tmp_path,entries):
    item=pick(inventory(navigation_pdf(tmp_path/'source.pdf')),'bookmark-additions');item['value']=navigation.canonical_value({'entries':entries})
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer navigation fixture','2026-10-27')


@pytest.mark.parametrize('flag,kind',[('unsafe_action','link-target'),('shared_annotation','annotation-name'),('shared_action','link-target'),('link_alias','link-name'),('rich_text','annotation-name')])
def test_unsafe_or_aliased_occurrences_are_read_only(tmp_path,flag,kind):
    data=inventory(navigation_pdf(tmp_path/'source.pdf',**{flag:True}));item=pick(data,kind)
    assert not item['structural_eligible'] and item['structural_limitations']
    item['value']='New name' if kind.endswith('name') else navigation.canonical_value({'kind':'page','page':2})
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer navigation fixture','2026-10-27')


def test_stale_context_duplicate_json_and_changed_capabilities_are_refused(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf');data=inventory(path);item=pick(data,'link-target')
    item['value']='{"kind":"page","page":1,"page":2}'
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer navigation fixture','2026-10-27')
    data=inventory(path);item=pick(data,'annotation-name');accept(item,'Reviewed name');item['navigation_context']['annotation_index']=1
    item['approval_sha256']=sidecar.approval_digest(item)
    with pytest.raises(sidecar.DecisionError):apply(path,data,tmp_path)
    assert not (tmp_path/'result.pdf').exists()


@pytest.mark.parametrize('flag',['missing_target','broken_named_target'])
def test_restore_original_unresolved_target_is_a_valid_noop_not_a_repair(tmp_path,flag):
    path=navigation_pdf(tmp_path/'source.pdf',**{flag:True});data=inventory(path);item=pick(data,'link-target')
    accept(item,{'kind':'page','page':2});accept(item,item['current'])
    out,receipt=apply(path,data,tmp_path)
    assert receipt['changed']==[] and out.read_bytes()==path.read_bytes()


def test_restore_original_blank_bookmark_is_a_valid_noop(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf',blank_bookmark=True);data=inventory(path);item=pick(data,'bookmark-entry')
    accept(item,{'title':'Changed title','target':{'kind':'page','page':2}});accept(item,item['current'])
    out,receipt=apply(path,data,tmp_path)
    assert receipt['changed']==[] and out.read_bytes()==path.read_bytes()


@pytest.mark.parametrize('malformation',['uri-type','goto-type','fit-mode'])
def test_wrong_type_passive_action_or_view_is_repairable_instead_of_validly_normalized(tmp_path,malformation):
    original=navigation_pdf(tmp_path/'source.pdf');path=tmp_path/'malformed.pdf'
    with pikepdf.open(original) as pdf:
        annotation=pdf.pages[0].Annots[0]
        if malformation=='uri-type':annotation.A.S=pikepdf.String('/URI')
        elif malformation=='goto-type':annotation.A=pikepdf.Dictionary(S=pikepdf.String('/GoTo'),D=pikepdf.Array([pdf.pages[1].obj,pikepdf.Name.Fit]))
        else:
            del annotation['/A'];annotation.Dest=pikepdf.Array([pdf.pages[1].obj,pikepdf.String('/Fit')])
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=inventory(path);item=pick(data,'link-target')
    assert item['structural_eligible'] and item['navigation_context']['source_target']['kind']=='unresolved'
    accept(item,{'kind':'page','page':2});out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:assert pdf.pages[0].Annots[0].Dest[1]==pikepdf.Name.Fit


@pytest.mark.parametrize('view',[['/FitR',None,0,100,100],['/FitR',100,0,0,100],['/XYZ',0,400,-1]])
def test_invalid_passive_view_parameters_are_repairable_at_the_same_page(tmp_path,view):
    original=navigation_pdf(tmp_path/'source.pdf');path=tmp_path/'invalid-view.pdf'
    with pikepdf.open(original) as pdf:
        annotation=pdf.pages[0].Annots[0];del annotation['/A']
        annotation.Dest=pikepdf.Array([pdf.pages[1].obj,pikepdf.Name(view[0]),*view[1:]])
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=inventory(path);item=pick(data,'link-target');assert item['structural_eligible'] and item['navigation_context']['source_target']['kind']=='unresolved'
    accept(item,{'kind':'page','page':2});out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:assert pdf.pages[0].Annots[0].Dest[1]==pikepdf.Name.Fit


def test_cancelled_inventory_or_apply_does_not_publish(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf');event=threading.Event();event.set()
    with pytest.raises(InterruptedError):sidecar.collect_decisions(path,inventory_profile=sidecar.NAVIGATION_INVENTORY_PROFILE,cancel=event)
    data=inventory(path);accept(pick(data,'annotation-name'),'Reviewed name');out=tmp_path/'result.pdf'
    with pytest.raises(InterruptedError):sidecar.apply_decisions(path,out,data,sidecar.file_sha256(path),cancel=event)
    assert not out.exists()


def test_reopened_graph_proof_rejects_unselected_annotation_and_navigation_damage(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf');data=inventory(path);item=pick(data,'annotation-name');accept(item,'Reviewed name')
    out,_=apply(path,data,tmp_path);damaged=tmp_path/'damaged.pdf'
    with pikepdf.open(out) as pdf:
        pdf.pages[0].Annots[0].Rect=pikepdf.Array([1,2,3,4])
        with damaged.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    with pytest.raises(sidecar.DecisionError):structure_edits.verify_output(path,damaged,[],other_changes=[item])


@pytest.mark.parametrize('field,value',[('/Subtype','/Link'),('/Type','/Annot')])
def test_string_annotation_type_is_read_only_instead_of_a_valid_name(tmp_path,field,value):
    original=navigation_pdf(tmp_path/'source.pdf');path=tmp_path/'wrong-type.pdf'
    with pikepdf.open(original) as pdf:
        pdf.pages[0].Annots[0][field]=pikepdf.String(value)
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=inventory(path)
    assert not pick(data,'annotation-name')['structural_eligible'] and not pick(data,'link-target')['structural_eligible']


def test_two_hundred_bookmarks_have_bounded_nonrecursive_graph_proof(tmp_path):
    path=navigation_pdf(tmp_path/'source.pdf');data=inventory(path)
    entries=[{'title':'Explicit section '+str(n+1),'page':1+n%2,'level':1} for n in range(200)]
    accept(pick(data,'bookmark-additions'),{'entries':entries});out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:assert pdf.Root.Outlines.Count==202 and str(pdf.Root.Outlines.Last.Title)=='Explicit section 200'


def test_names_and_bookmark_authoring_do_not_require_inventing_a_structure_tree(tmp_path):
    original=navigation_pdf(tmp_path/'source.pdf',with_bookmarks=False);path=tmp_path/'untagged.pdf'
    with pikepdf.open(original) as pdf:
        del pdf.Root['/StructTreeRoot'];del pdf.Root['/MarkInfo'];del pdf.pages[0].Annots[0]['/StructParent']
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=inventory(path);assert pick(data,'annotation-name')['structural_eligible']
    accept(pick(data,'annotation-name'),'Reviewed untagged link description')
    accept(pick(data,'bookmark-additions'),{'entries':[{'title':'Reviewed section','page':1,'level':1}]})
    out,_=apply(path,data,tmp_path)
    with pikepdf.open(out) as pdf:
        assert '/StructTreeRoot' not in pdf.Root and str(pdf.Root.Outlines.First.Title)=='Reviewed section'
        assert str(pdf.pages[0].Annots[0].Contents)=='Reviewed untagged link description'
