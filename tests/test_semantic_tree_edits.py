"""Independent small source graphs for bounded semantic tree mechanics."""
from __future__ import annotations

import copy
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator import sidecar
from pdf_remediator import semantic_tree_edits as tree
from pdf_remediator import structure_edits as graph


def tree_pdf(path,*,different_language=False,shared_leaf=False,shared_parent_array=False,
             actual_text=False,rolemap=False,mixed_content=False,image_only=False,
             existing_list=False,source_form=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    pdf=pikepdf.Pdf.new();pages=[pdf.add_blank_page(page_size=(420,600)) for _ in range(2)]
    font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))
    root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
    doc=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Document,P=root))
    root.K=doc;pdf.Root.StructTreeRoot=root;pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True);pdf.Root.Lang='en-US'
    sections=[];owners=[];all_leaves=[]
    def group(role,parent,page):return pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name('/'+role),P=parent,Pg=page.obj))
    for n,page in enumerate(pages):
        section=group('Sect',doc,page);sections.append(section);leaves=[]
        def leaf(role,text,parent):
            node=group(role,parent,page);node.K=len(leaves);leaves.append((node,text));return node
        if n==0:
            heading=leaf('H1','Semantic developer control',section)
            a=group('Div',section,page);b=group('Div',section,page);c=group('Div',section,page)
            false=leaf('H2','This is an ordinary paragraph.',a)
            labels=[]
            for label,body in [('1.','First explicit list body.'),('2.','Second explicit list body.')]:
                labels.extend([leaf('P',label,a),leaf('P',body,a)])
            a.K=pikepdf.Array([false,*labels])
            if existing_list:
                listing=group('L',a,page);lis=[]
                listing.A=pikepdf.Dictionary(O=pikepdf.Name.List,ListNumbering=pikepdf.Name.Decimal)
                for label,body in [labels[:2],labels[2:]]:
                    item=group('LI',listing,page);label.S=pikepdf.Name.Lbl;label.P=item;body.P=item;item.K=pikepdf.Array([label,body]);lis.append(item)
                listing.K=pikepdf.Array(lis);a.K=pikepdf.Array([false,listing])
            move=leaf('P','Movable existing paragraph.',b);stay=leaf('P','Retained sibling paragraph.',b);b.K=pikepdf.Array([move,stay])
            alpha=leaf('P','Alpha paragraph.',c);beta=leaf('P','Beta paragraph.',c);c.K=pikepdf.Array([alpha,beta])
            section.K=pikepdf.Array([heading,a,b,c])
            if different_language:c.Lang='fr'
            if shared_leaf:pdf.Root.ExtraLeaf=move
            if shared_parent_array:
                b.K=pdf.make_indirect(b.K);pdf.Root.ExtraChildren=b.K
            if actual_text:a.ActualText='Replacement text protects this group.'
            if rolemap:root.RoleMap=pikepdf.Dictionary(P=pikepdf.Name.Span)
        else:
            first=leaf('H1','Second page',section);last=leaf('P','Keep the second page unchanged.',section);section.K=pikepdf.Array([first,last])
        owners.append([node for node,text in leaves]);all_leaves.append(leaves)
        lines=['q']
        for i,(node,text) in enumerate(leaves):
            lines.append('/P <</MCID '+str(i)+'>> BDC')
            if not (image_only and n==0 and i==1):
                lines.append('BT /F1 11 Tf 28 '+str(565-i*30)+' Td ('+text+') Tj ET')
            if (mixed_content or image_only) and n==0 and i==1:lines.append('/Im0 Do')
            lines.append('EMC')
        lines.append('Q');page.Contents=pdf.make_stream('\n'.join(lines).encode('ascii'));page.StructParents=n;page.Tabs=pikepdf.Name.S
        page.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        if mixed_content or image_only:
            image=pdf.make_stream(b'\xff\x00\x00');image.Type=pikepdf.Name.XObject;image.Subtype=pikepdf.Name.Image
            image.Width=1;image.Height=1;image.ColorSpace=pikepdf.Name.DeviceRGB;image.BitsPerComponent=8
            page.Resources.XObject=pikepdf.Dictionary(Im0=image)
    doc.K=pikepdf.Array(sections);root.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Array(owners[0]),1,pikepdf.Array(owners[1])])));root.ParentTreeNextKey=2
    pdf.docinfo.Title='Semantic developer control'
    if source_form:pdf.Root.AcroForm=pikepdf.Dictionary(Fields=pikepdf.Array())
    pdf.save(path,deterministic_id=True);pdf.close();return path


def inventory(path):return sidecar.collect_decisions(path,inventory_profile=sidecar.SEMANTIC_TREE_INVENTORY_PROFILE)
def rows(data,kind):return [item for item in data['decisions'] if item['kind']==kind]
def choose(data,kind,part):
    found=[item for item in rows(data,kind) if item['structure_path']==part]
    assert len(found)==1;return found[0]
def accept(data,item,value):
    item['value']=value if isinstance(value,str) else tree.canonical_value(value)
    sidecar.bind_approval(item,'Developer tree fixture','2026-10-27');return item
def apply(path,data,out):return sidecar.apply_decisions(path,out,data,data['source_sha256'])


A='root/K/K/0/K/1';B='root/K/K/0/K/2';C='root/K/K/0/K/3';SECT='root/K/K/0'


def test_inventory_is_pending_source_bound_and_old_five_profiles_remain_exact(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source)
    assert data['inventory_profile']=='reviewed-semantic-tree-5'
    assert tree.KINDS<={item['kind'] for item in data['decisions']}
    assert all(item['status']=='pending' and item['value']==item['current'] for item in data['decisions'])
    for profile in [sidecar.LEGACY_INVENTORY_PROFILE,sidecar.STRUCTURAL_INVENTORY_PROFILE,sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE,sidecar.PASSAGE_LANGUAGE_INVENTORY_PROFILE,sidecar.NAVIGATION_INVENTORY_PROFILE]:
        old=sidecar.collect_decisions(source,inventory_profile=profile)
        assert not any(item['kind'] in tree.KINDS for item in old['decisions'])
        assert sidecar.collect_decisions(source,inventory_profile=profile)==old
    assert any('ordinary paragraph' in item['context_text'] for item in rows(data,'semantic-role'))


def test_heading_can_be_changed_to_paragraph_without_text_or_other_fields(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'semantic-role',A+'/K/0');accept(data,item,'P')
    out=tmp_path/'out.pdf';result=apply(source,data,out);assert item['id'] in result['changed']
    with pikepdf.open(source) as before,pikepdf.open(out) as after:
        expected=graph._snapshot(before);expected['objects'][item['element']]['v']['/S']={'t':'name','v':'/P'}
        assert tree.canonical_snapshot(expected)==tree.canonical_snapshot(graph._snapshot(after))


def test_sibling_order_is_exact_permutation_and_does_not_change_parent_tree(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'reading-order',C)
    accept(data,item,{'children':list(reversed(item['tree_context']['source']['children']))});out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(source) as before,pikepdf.open(out) as after:
        assert [int(x.K) for x in after.Root.StructTreeRoot.K.K[0].K[3].K]==list(reversed([int(x.K) for x in before.Root.StructTreeRoot.K.K[0].K[3].K]))
        assert bytes(before.pages[0].Contents.read_bytes())==bytes(after.pages[0].Contents.read_bytes())
        assert [(str(node.S),int(node.K)) for node in before.Root.StructTreeRoot.ParentTree.Nums[1]]==[(str(node.S),int(node.K)) for node in after.Root.StructTreeRoot.ParentTree.Nums[1]]


def test_leaf_move_preserves_original_owner_and_keeps_source_parent_nonempty(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'tree-move',B+'/K/0')
    target=next(x for x in item['tree_context']['parent_choices'] if x['element']==choose(data,'reading-order',SECT)['element'])
    accept(data,item,{'parent':target['element'],'index':1});out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:
        section=pdf.Root.StructTreeRoot.K.K[0];assert int(section.K[1].K)==6
        assert len(section.K[3].K)==1 and section.K[1].P==section
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][6]==section.K[1]


def test_explicit_label_body_list_creates_only_wrappers_and_retains_mcid_owners(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'semantic-list',A);nodes=item['tree_context']['source']['children']
    accept(data,item,{'items':[{'label':nodes[1],'body':nodes[2]},{'label':nodes[3],'body':nodes[4]}],'numbering':'Decimal'})
    out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:
        a=pdf.Root.StructTreeRoot.K.K[0].K[1];assert len(a.K)==2;listing=a.K[1]
        assert listing.S==pikepdf.Name.L and listing.A.ListNumbering==pikepdf.Name.Decimal
        assert [str(node.S) for node in listing.K]==['/LI','/LI']
        assert [[str(child.S) for child in node.K] for node in listing.K]==[['/Lbl','/LBody'],['/Lbl','/LBody']]
        for node in listing.K:
            for child in node.K:assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][int(child.K)]==child


def test_list_item_order_is_explicit_and_selected_union_stays_contiguous(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'semantic-list',A);ids=item['tree_context']['source']['children']
    accept(data,item,{'items':[{'label':ids[3],'body':ids[4]},{'label':ids[1],'body':ids[2]}],'numbering':'Decimal'})
    out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:assert [int(li.K[1].K) for li in pdf.Root.StructTreeRoot.K.K[0].K[1].K[1].K]==[5,3]


def test_unlabelled_list_uses_existing_bodies_without_inventing_label_text(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'semantic-list',C);ids=item['tree_context']['source']['children']
    accept(data,item,{'items':[{'label':None,'body':node} for node in ids],'numbering':'None'});out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:
        listing=pdf.Root.StructTreeRoot.K.K[0].K[3].K[0]
        assert all(len(li.K)==1 and li.K[0].S==pikepdf.Name.LBody for li in listing.K)


def test_heading_to_paragraph_can_compose_with_move_of_that_same_leaf(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);role=choose(data,'semantic-role',A+'/K/0');move=choose(data,'tree-move',A+'/K/0')
    target=choose(data,'reading-order',C)['element'];accept(data,role,'P');accept(data,move,{'parent':target,'index':0})
    out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:assert pdf.Root.StructTreeRoot.K.K[0].K[3].K[0].S==pikepdf.Name.P


def test_false_heading_can_be_explicit_list_body_instead_of_separate_demotion(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'semantic-list',A);ident=item['tree_context']['source']['children'][0]
    accept(data,item,{'items':[{'label':None,'body':ident}],'numbering':'None'});out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:assert pdf.Root.StructTreeRoot.K.K[0].K[1].K[0].K[0].K[0].S==pikepdf.Name.LBody


def test_existing_list_body_roles_can_be_repaired_together(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf',existing_list=True);data=inventory(source)
    selected=[row for row in rows(data,'semantic-role') if row['current']=='P' and row['tree_context']['source']['parent'] not in {None}]
    # The only ordinary P nodes with LBody as a source-bound alternative are the two deliberate wrong list bodies.
    selected=[row for row in selected if 'LBody' in row['allowed_values']];assert len(selected)==2
    for item in selected:accept(data,item,'LBody')
    out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:assert all(li.K[1].S==pikepdf.Name.LBody for li in pdf.Root.StructTreeRoot.K.K[0].K[1].K[1].K)


@pytest.mark.parametrize('hazard',['shared_leaf','shared_parent_array','actual_text','source_form'])
def test_unsafe_source_ownership_or_semantic_context_is_read_only(tmp_path,hazard):
    source=tree_pdf(tmp_path/'source.pdf',**{hazard:True});data=inventory(source)
    item=choose(data,'tree-move',B+'/K/0') if hazard!='actual_text' else choose(data,'semantic-role',A+'/K/0')
    assert not item['structural_eligible'] and item['structural_limitations']
    item['value']='P' if item['kind']=='semantic-role' else tree.canonical_value({'parent':'forged','index':0})
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer','2026-10-27')


@pytest.mark.parametrize('hazard',['mixed_content','image_only'])
def test_nontext_or_mixed_marked_scope_cannot_be_advertised_as_text_editable(tmp_path,hazard):
    source=tree_pdf(tmp_path/'source.pdf',**{hazard:True});data=inventory(source);item=choose(data,'semantic-role',A+'/K/0')
    assert not item['structural_eligible'] and any('text-object' in reason for reason in item['structural_limitations'])


def test_rolemap_paragraph_target_is_read_only_instead_of_reinterpreted(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf',rolemap=True);data=inventory(source);item=choose(data,'semantic-role',A+'/K/0')
    assert not item['structural_eligible'] and any('remapped' in reason for reason in item['structural_limitations'])


def test_different_inherited_language_is_not_an_available_move_destination(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf',different_language=True);data=inventory(source)
    move=choose(data,'tree-move',B+'/K/0');destination=choose(data,'reading-order',C)['element']
    assert destination not in {row['element'] for row in move['tree_context']['parent_choices']}


@pytest.mark.parametrize('value',[
    {'children':[]},{'children':['forged']},{'children':['x','x']},{'children':None},{'children':[],'extra':1},
])
def test_invalid_reading_order_cannot_duplicate_drop_or_add_nodes(tmp_path,value):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'reading-order',C);item['value']=tree.canonical_value(value)
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer','2026-10-27')


@pytest.mark.parametrize('kind,value',[
    ('tree-move',{'parent':'forged','index':0}),('tree-move',{'parent':'forged','index':True}),
    ('semantic-list',{'items':[],'numbering':'Decimal'}),('semantic-list',{'items':[],'numbering':'Auto'}),
    ('semantic-list',{'items':[{'body':'forged','label':None}],'numbering':'None'}),
])
def test_invalid_move_and_list_choices_are_rejected(tmp_path,kind,value):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,kind,B+'/K/0' if kind=='tree-move' else A);item['value']=tree.canonical_value(value)
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer','2026-10-27')


def test_list_cannot_reuse_one_node_or_skip_an_unselected_middle_node(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'semantic-list',A);ids=item['tree_context']['source']['children']
    for value in [{'items':[{'label':ids[1],'body':ids[1]}],'numbering':'None'}, {'items':[{'label':None,'body':ids[1]},{'label':None,'body':ids[3]}],'numbering':'None'}]:
        item['value']=tree.canonical_value(value)
        with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer','2026-10-27')


def test_overlapping_parent_edge_plans_refuse_without_publishing(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);listing=choose(data,'semantic-list',C);order=choose(data,'reading-order',C);ids=listing['tree_context']['source']['children']
    accept(data,listing,{'items':[{'label':None,'body':node} for node in ids],'numbering':'None'});accept(data,order,{'children':list(reversed(ids))})
    out=tmp_path/'out.pdf'
    with pytest.raises(sidecar.DecisionError,match='overlap'):apply(source,data,out)
    assert not out.exists()


def test_semantic_list_and_separate_role_cannot_compete_for_same_heading(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);listing=choose(data,'semantic-list',A);role=choose(data,'semantic-role',A+'/K/0');node=role['element']
    accept(data,listing,{'items':[{'label':None,'body':node}],'numbering':'None'});accept(data,role,'P')
    with pytest.raises(sidecar.DecisionError,match='overlap|same'):apply(source,data,tmp_path/'out.pdf')


def test_legacy_heading_change_and_new_role_conflict_is_explicit(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);role=choose(data,'semantic-role',A+'/K/0')
    legacy=next(row for row in data['decisions'] if row['kind']=='heading-tag' and row['element']==role['element'])
    accept(data,role,'P');accept(data,legacy,'H3')
    with pytest.raises(sidecar.DecisionError,match='same role'):apply(source,data,tmp_path/'out.pdf')


@pytest.mark.parametrize('field',['tree_context','context_sha256','references','allowed_values'])
def test_source_context_tampering_refuses_apply(tmp_path,field):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);item=choose(data,'semantic-role',A+'/K/0');accept(data,item,'P')
    if field=='tree_context':item[field]['source']['role']='P'
    elif field=='references':item[field]=[]
    elif field=='allowed_values':item[field].append('Figure')
    else:item[field]='0'*64
    with pytest.raises(sidecar.DecisionError):apply(source,data,tmp_path/'out.pdf')


def test_exact_noop_choices_copy_source_bytes_without_new_nodes(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source)
    for kind in tree.KINDS:
        item=next(row for row in rows(data,kind) if row['structural_eligible']);accept(data,item,item['current'])
    out=tmp_path/'out.pdf';result=apply(source,data,out);assert result['changed']==[] and source.read_bytes()==out.read_bytes()


def test_unsupported_proof_bound_explains_optional_control_without_inventory_error(tmp_path,monkeypatch):
    source=tree_pdf(tmp_path/'source.pdf')
    with pikepdf.open(source) as pdf:
        monkeypatch.setattr(tree,'_analyse',lambda *args,**kwargs: (_ for _ in ()).throw(ValueError('bounded proof unavailable')))
        actual,targets,errors=tree.inventory(pdf)
    assert not errors and not targets and len(actual)==1 and not actual[0]['structural_eligible']
    assert 'bounded proof' in actual[0]['structural_limitations'][0]


def test_cancelled_inventory_propagates_without_weakening_existing_processing(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf')
    with pikepdf.open(source) as pdf,pytest.raises(InterruptedError):tree.inventory(pdf,cancel=lambda:True)


def test_scalar_structure_child_can_be_grouped_as_a_one_item_list(tmp_path):
    source=tree_pdf(tmp_path/'before.pdf');changed=tmp_path/'scalar.pdf'
    with pikepdf.open(source) as pdf:
        c=pdf.Root.StructTreeRoot.K.K[0].K[3];first,second=list(c.K)
        # Keep the second text leaf in a different neutral source parent.
        b=pdf.Root.StructTreeRoot.K.K[0].K[2];b.K.append(second);second.P=b;c.K=first
        pdf.save(changed,deterministic_id=True)
    data=inventory(changed);item=choose(data,'semantic-list',C);ids=item['tree_context']['source']['children'];assert len(ids)==1
    accept(data,item,{'items':[{'label':None,'body':ids[0]}],'numbering':'None'});out=tmp_path/'out.pdf';apply(changed,data,out)
    with pikepdf.open(out) as pdf:assert pdf.Root.StructTreeRoot.K.K[0].K[3].K[0].S==pikepdf.Name.L


def test_move_can_insert_into_a_scalar_structure_child_destination(tmp_path):
    source=tree_pdf(tmp_path/'before.pdf');changed=tmp_path/'scalar.pdf'
    with pikepdf.open(source) as pdf:
        c=pdf.Root.StructTreeRoot.K.K[0].K[3];first,second=list(c.K)
        a=pdf.Root.StructTreeRoot.K.K[0].K[1];a.K.append(second);second.P=a;c.K=first;pdf.save(changed,deterministic_id=True)
    data=inventory(changed);move=choose(data,'tree-move',B+'/K/0');dest=choose(data,'semantic-list',C)['element']
    accept(data,move,{'parent':dest,'index':1});out=tmp_path/'out.pdf';apply(changed,data,out)
    with pikepdf.open(out) as pdf:assert len(pdf.Root.StructTreeRoot.K.K[0].K[3].K)==2


def test_meaningful_figure_can_be_reordered_as_an_atomic_existing_child(tmp_path):
    source=tree_pdf(tmp_path/'before.pdf',image_only=True);changed=tmp_path/'figure.pdf'
    with pikepdf.open(source) as pdf:
        a=pdf.Root.StructTreeRoot.K.K[0].K[1];figure=a.K[0];figure.S=pikepdf.Name.Figure;figure.Alt='A meaningful developer logo.'
        figure.A=pikepdf.Dictionary(O=pikepdf.Name.Layout,BBox=pikepdf.Array([0,0,1,1]));pdf.save(changed,deterministic_id=True)
    data=inventory(changed);item=choose(data,'reading-order',A);assert item['structural_eligible']
    ids=item['tree_context']['source']['children'];accept(data,item,{'children':[ids[1],ids[0],*ids[2:]]});out=tmp_path/'out.pdf';apply(changed,data,out)
    with pikepdf.open(changed) as old,pikepdf.open(out) as new:
        figure=new.Root.StructTreeRoot.K.K[0].K[1].K[1]
        assert figure.S==pikepdf.Name.Figure and str(figure.Alt)=='A meaningful developer logo.'
        assert list(figure.A.BBox)==[0,0,1,1]
        assert old.pages[0].Resources.XObject.Im0.read_bytes()==new.pages[0].Resources.XObject.Im0.read_bytes()
        assert old.pages[0].Contents.read_bytes()==new.pages[0].Contents.read_bytes()


def test_reorder_cannot_reattach_an_accepted_decorative_removal(tmp_path):
    source=tree_pdf(tmp_path/'before.pdf',image_only=True);changed=tmp_path/'figure.pdf'
    with pikepdf.open(source) as pdf:
        figure=pdf.Root.StructTreeRoot.K.K[0].K[1].K[0];figure.S=pikepdf.Name.Figure;figure.Alt='Meaningful source illustration.';pdf.save(changed,deterministic_id=True)
    data=inventory(changed);order=choose(data,'reading-order',A);figure=next(row for row in data['decisions'] if row['kind']=='figure-purpose')
    assert figure['structural_eligible'];accept(data,figure,'Artifact');ids=order['tree_context']['source']['children'];accept(data,order,{'children':list(reversed(ids))})
    with pytest.raises(sidecar.DecisionError,match='same original parent'):apply(changed,data,tmp_path/'out.pdf')


def test_global_language_replay_can_compose_when_both_move_parents_inherit_it(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);move=choose(data,'tree-move',B+'/K/0');dest=choose(data,'reading-order',C)['element']
    accept(data,move,{'parent':dest,'index':0});global_language=next(row for row in data['decisions'] if row['kind']=='language');accept(data,global_language,'en-GB')
    out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:assert str(pdf.Root.Lang)=='en-GB' and len(pdf.Root.StructTreeRoot.K.K[0].K[3].K)==3


def test_simultaneous_local_language_must_not_change_the_moved_leaf_inheritance(tmp_path):
    source=tree_pdf(tmp_path/'source.pdf');data=inventory(source);move=choose(data,'tree-move',B+'/K/0');dest=choose(data,'reading-order',C)['element']
    accept(data,move,{'parent':dest,'index':0})
    language=next(row for row in data['decisions'] if row['kind']=='page-language' and row['element']==dest) if any(row['kind']=='page-language' and row['element']==dest for row in data['decisions']) else None
    # A local language edit on an existing destination grouping scope can also
    # be exercised directly against prepared plans, without inventing a review.
    with pikepdf.open(source) as pdf:
        contexts=sidecar._marked_text_contexts(source)
        with pytest.raises(sidecar.DecisionError,match='inherited language'):
            tree.prepare_changes(pdf,[move],text_contexts=contexts,other_changes=[{'kind':'page-language','element':dest,'current':'{"language":null}','value':'{"language":"fr"}'}])


@pytest.mark.parametrize('alias',['root','ancestor','info'])
def test_root_and_ancestor_aliases_protect_descendant_edits(tmp_path,alias):
    before=tree_pdf(tmp_path/'before.pdf');source=tmp_path/'aliased.pdf'
    with pikepdf.open(before) as pdf:
        if alias=='root':pdf.Root.ExtraRoot=pdf.Root.StructTreeRoot
        elif alias=='ancestor':pdf.Root.ExtraDocument=pdf.Root.StructTreeRoot.K
        else:pdf.trailer.Info=pdf.Root.StructTreeRoot.K
        pdf.save(source,deterministic_id=True)
    data=inventory(source);item=choose(data,'semantic-role',A+'/K/0')
    assert not item['structural_eligible'] and any('alias' in reason for reason in item['structural_limitations'])
    item['value']='P'
    with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer','2026-10-27')


def wrong_list_wrapper(path):
    before=tree_pdf(Path(path).with_name('before.pdf'),existing_list=True)
    with pikepdf.open(before) as pdf:
        listing=pdf.Root.StructTreeRoot.K.K[0].K[1].K[1]
        first=listing.K[0];first.S=pikepdf.Name.Div;first.K[0].S=pikepdf.Name.P
        listing.K[1].K[1].S=pikepdf.Name.LBody
        pdf.save(path,deterministic_id=True)
    return Path(path)


def test_known_list_wrong_wrapper_and_two_roles_can_be_repaired_together(tmp_path):
    source=wrong_list_wrapper(tmp_path/'source.pdf');data=inventory(source);base=A+'/K/1/K/0'
    wrapper=choose(data,'semantic-role',base);label=choose(data,'semantic-role',base+'/K/0');body=choose(data,'semantic-role',base+'/K/1')
    accept(data,wrapper,'LI');accept(data,label,'Lbl');accept(data,body,'LBody');out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:
        listing=pdf.Root.StructTreeRoot.K.K[0].K[1].K[1]
        assert all(li.S==pikepdf.Name.LI and [str(child.S) for child in li.K]==['/Lbl','/LBody'] for li in listing.K)


def test_child_list_role_without_required_wrapper_correction_is_refused(tmp_path):
    source=wrong_list_wrapper(tmp_path/'source.pdf');data=inventory(source);base=A+'/K/1/K/0'
    label=choose(data,'semantic-role',base+'/K/0');body=choose(data,'semantic-role',base+'/K/1')
    accept(data,label,'Lbl');accept(data,body,'LBody')
    with pytest.raises(sidecar.DecisionError,match='list item|list-item'):apply(source,data,tmp_path/'out.pdf')


def test_root_indirect_child_array_alias_protects_descendant_edits(tmp_path):
    before=tree_pdf(tmp_path/'before.pdf');source=tmp_path/'aliased.pdf'
    with pikepdf.open(before) as pdf:
        root=pdf.Root.StructTreeRoot;root.K=pdf.make_indirect(pikepdf.Array([root.K]));pdf.Root.ExtraChildren=root.K
        pdf.save(source,deterministic_id=True)
    data=inventory(source);item=next(row for row in rows(data,'semantic-role') if row['current']=='H2')
    assert not item['structural_eligible'] and any('root child array' in reason for reason in item['structural_limitations'])


@pytest.mark.parametrize('carrier',['branch','numbers','values'])
def test_parent_tree_indirect_carrier_aliases_protect_text_owner_edits(tmp_path,carrier):
    before=tree_pdf(tmp_path/'before.pdf');source=tmp_path/'aliased.pdf'
    with pikepdf.open(before) as pdf:
        parent_tree=pdf.Root.StructTreeRoot.ParentTree
        if carrier=='branch':value=parent_tree
        elif carrier=='numbers':parent_tree.Nums=pdf.make_indirect(parent_tree.Nums);value=parent_tree.Nums
        else:parent_tree.Nums[1]=pdf.make_indirect(parent_tree.Nums[1]);value=parent_tree.Nums[1]
        pdf.Root.ExtraParentTreeCarrier=value;pdf.save(source,deterministic_id=True)
    data=inventory(source);item=choose(data,'semantic-role',A+'/K/0')
    assert not item['structural_eligible'] and any('ParentTree' in reason and 'alias' in reason for reason in item['structural_limitations'])


def test_shared_page_parent_key_does_not_claim_unique_owner_scope(tmp_path):
    before=tree_pdf(tmp_path/'before.pdf');source=tmp_path/'shared-key.pdf'
    with pikepdf.open(before) as pdf:pdf.pages[1].StructParents=0;pdf.save(source,deterministic_id=True)
    data=inventory(source);item=choose(data,'semantic-role',A+'/K/0')
    assert not item['structural_eligible'] and any('StructParents key' in reason for reason in item['structural_limitations'])


def test_unique_indirect_parent_child_array_supports_list_grouping(tmp_path):
    before=tree_pdf(tmp_path/'before.pdf');source=tmp_path/'indirect.pdf'
    with pikepdf.open(before) as pdf:
        c=pdf.Root.StructTreeRoot.K.K[0].K[3];c.K=pdf.make_indirect(c.K);pdf.save(source,deterministic_id=True)
    data=inventory(source);item=choose(data,'semantic-list',C);assert item['structural_eligible'];ids=item['tree_context']['source']['children']
    accept(data,item,{'items':[{'label':None,'body':ident} for ident in ids],'numbering':'None'});out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:assert len(pdf.Root.StructTreeRoot.K.K[0].K[3].K[0].K)==2


def test_unique_indirect_source_and_destination_child_arrays_support_move(tmp_path):
    before=tree_pdf(tmp_path/'before.pdf');source=tmp_path/'indirect.pdf'
    with pikepdf.open(before) as pdf:
        section=pdf.Root.StructTreeRoot.K.K[0]
        for index in [2,3]:section.K[index].K=pdf.make_indirect(section.K[index].K)
        pdf.save(source,deterministic_id=True)
    data=inventory(source);item=choose(data,'tree-move',B+'/K/0');dest=choose(data,'reading-order',C)['element']
    accept(data,item,{'parent':dest,'index':1});out=tmp_path/'out.pdf';apply(source,data,out)
    with pikepdf.open(out) as pdf:
        section=pdf.Root.StructTreeRoot.K.K[0];assert len(section.K[2].K)==1 and len(section.K[3].K)==3


@pytest.mark.parametrize('image_only',[False,True])
def test_heading_container_requires_a_proven_text_subtree_for_paragraph_correction(tmp_path,image_only):
    before=tree_pdf(tmp_path/'before.pdf',image_only=image_only);source=tmp_path/'heading-container.pdf'
    with pikepdf.open(before) as pdf:
        heading=pdf.Root.StructTreeRoot.K.K[0].K[1].K[0]
        span=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Span,P=heading,Pg=pdf.pages[0].obj,K=heading.K))
        heading.K=pikepdf.Array([span]);pdf.Root.StructTreeRoot.ParentTree.Nums[1][1]=span;pdf.save(source,deterministic_id=True)
    data=inventory(source);item=choose(data,'semantic-role',A+'/K/0')
    if image_only:
        assert not item['structural_eligible'] and any('pure-text subtree' in reason for reason in item['structural_limitations'])
        assert not choose(data,'semantic-list',A)['structural_eligible']
        item['value']='P'
        with pytest.raises(sidecar.DecisionError):sidecar.bind_approval(item,'Developer','2026-10-27')
    else:
        assert item['structural_eligible'] and 'ordinary paragraph' in item['context_text']
        assert choose(data,'semantic-list',A)['structural_eligible']
        assert len(item['references'])==1 and item['references'][0]['mcid']==1
        accept(data,item,'P');out=tmp_path/'out.pdf';apply(source,data,out)
        with pikepdf.open(out) as pdf:
            heading=pdf.Root.StructTreeRoot.K.K[0].K[1].K[0]
            assert heading.S==pikepdf.Name.P and heading.K[0].S==pikepdf.Name.Span
            assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][1]==heading.K[0]
