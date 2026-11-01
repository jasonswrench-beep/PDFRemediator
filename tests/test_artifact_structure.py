"""Authored PDF mechanics only; semantic purpose is never inferred or approved."""
from pathlib import Path
import copy
import hashlib
import io

import pikepdf
import pytest

from pdf_remediator import sidecar
from pdf_remediator.inspection import inspect_pdf, compare_fidelity
from pdf_remediator.structure_edits import inventory, _snapshot, _canonical

PROFILE = sidecar.ARTIFACT_STRUCTURE_INVENTORY_PROFILE


def artifact_pdf(path, *, root_role="Document", section_role="Sect", image_only=False,
                 figure_text=False, shared_stream=False, nested_marks=False,
                 actual_text=False, figure_id=False):
    """Two-page source with real text and one independently markable graphic.

    Standard Helvetica is a fixture convenience, not a font-embedding claim.
    All content is linked. The first Figure has siblings and one page MCID.
    """
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with pikepdf.new() as pdf:
        root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name('/'+root_role),P=root))
        root.K=pikepdf.Array([document]); groups=[]; nums=[]; figures=[]
        font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))
        for number in range(2):
            page=pdf.add_blank_page(page_size=(400,500)); page.obj.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font)); page.obj.StructParents=number
            section=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name('/'+section_role),P=document))
            groups.append(section); children=[]
            for mcid,role in enumerate(['H1' if number==0 else 'H2','Figure','P']):
                node=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name('/'+role),P=section,Pg=page.obj,K=mcid))
                if role=='Figure':
                    node.Alt='Meaningful diagram on the second page' if number else 'Source graphic awaiting purpose review'
                    figures.append(node)
                children.append(node)
            section.K=pikepdf.Array(children); nums.extend([number,pikepdf.Array(children)])
            graphic=b'q .2 .4 .6 rg 80 180 100 60 re f Q'
            if number==0:
                if nested_marks:graphic=b'/Span BMC '+graphic+b' EMC'
                if figure_text:graphic+=b' BT /F1 10 Tf 80 160 Td (Meaningful figure text) Tj ET'
            content=(b'/H1 <</MCID 0>> BDC BT /F1 14 Tf 50 420 Td (Source chapter heading) Tj ET EMC\n'
                b'/Figure <</MCID 1>> BDC '+graphic+b' EMC\n'
                b'/P <</MCID 2>> BDC BT /F1 11 Tf 50 100 Td (Retained paragraph text.) Tj ET EMC\n')
            page.obj.Contents=pdf.make_stream(content)
        document.K=pikepdf.Array(groups)
        if actual_text:figures[0].ActualText='Replacement content must remain meaningful'
        if figure_id:figures[0].ID='source-figure-id'
        if image_only:
            page=pdf.pages[0]; image=pdf.make_stream(bytes([32,64,160])*4)
            image.Type=pikepdf.Name.XObject; image.Subtype=pikepdf.Name.Image; image.Width=2; image.Height=2; image.ColorSpace=pikepdf.Name.DeviceRGB; image.BitsPerComponent=8
            page.obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im1=image))
            figure=figures[0]; figure.P=document; figure.K=0
            document.K=pikepdf.Array([figure,groups[1]])
            nums[1]=pikepdf.Array([figure]); page.obj.Contents=pdf.make_stream(b'/Figure <</MCID 0>> BDC q 100 0 0 100 80 180 cm /Im1 Do Q EMC')
        if shared_stream:pdf.pages[1].obj.Contents=pdf.pages[0].obj.Contents
        root.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(nums)))
        root.ParentTreeNextKey=2; pdf.Root.StructTreeRoot=root; pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang='en-US'; pdf.Root.ViewerPreferences=pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.docinfo.Title='Authored decorative and structure control fixture'
        with path.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    return path


def decisions(path):return sidecar.collect_decisions(path,inventory_profile=PROFILE)


def choose(data,kind,*,page=1):
    return next(i for i in data['decisions'] if i['kind']==kind and (page is None or i.get('page')==page))


def accept(item,value):
    item['value']=value; sidecar.bind_approval(item,'Synthetic developer fixture reviewer','2026-10-27'); return item


def apply(path,data,tmp_path,name='edited.pdf'):
    destination=tmp_path/name
    receipt=sidecar.apply_decisions(path,destination,data,sidecar.file_sha256(path))
    return destination,receipt


def test_existing_profiles_keep_exact_inventory_when_new_profile_is_available(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf')
    legacy=sidecar.collect_decisions(path)
    structural=sidecar.collect_decisions(path,inventory_profile=sidecar.STRUCTURAL_INVENTORY_PROFILE)
    expanded=decisions(path)
    assert expanded['decisions'][:len(structural['decisions'])]==structural['decisions']
    assert all(i['kind'] not in {'figure-purpose','structure-role'} for d in (legacy,structural) for i in d['decisions'])
    assert legacy==sidecar.collect_decisions(path)
    assert structural==sidecar.collect_decisions(path,inventory_profile=sidecar.STRUCTURAL_INVENTORY_PROFILE)


def test_decorative_marking_preserves_paint_and_text_and_reconciles_only_owned_relationships(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf'); old=path.read_bytes(); data=decisions(path)
    item=choose(data,'figure-purpose'); assert item['structural_eligible'] and item['allowed_values']==['Figure','Artifact']
    accept(item,'Artifact'); destination,receipt=apply(path,data,tmp_path)
    assert receipt['changed']==[item['id']] and path.read_bytes()==old
    before,after=inspect_pdf(path),inspect_pdf(destination)
    assert after['structure']['tag_counts']['/Figure']==before['structure']['tag_counts']['/Figure']-1
    linkage={c['id']:c['status'] for c in after['checks'] if c['id'] in {'content-linkage','content-coverage'}}
    assert linkage=={'content-linkage':'pass','content-coverage':'pass'}
    assert compare_fidelity(path,destination)['status']=='pass'
    with pikepdf.open(destination) as pdf:
        root=pdf.Root.StructTreeRoot
        assert root.ParentTree.Nums[1][1] is None
        assert len(root.ParentTree.Nums[1])==3
        assert [str(n.S) for n in root.K[0].K[0].K]==['/H1','/P']
        ops=list(pikepdf.parse_content_stream(pdf.pages[0]))
        assert any(str(i.operator)=='BMC' and str(i.operands[0])=='/Artifact' for i in ops)
        assert all('/MCID' not in i.operands[1] or int(i.operands[1]['/MCID'])!=1 for i in ops if str(i.operator)=='BDC')


def test_role_only_changes_existing_containers_without_reparenting_children(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf',root_role='Div',section_role='Div'); before=path.read_bytes(); data=decisions(path)
    selected=[]
    for item in data['decisions']:
        if item['kind']=='structure-role':
            target='Document' if item['structure_path']=='root/K/0' else 'Sect'
            accept(item,target);selected.append(item['id'])
    destination,receipt=apply(path,data,tmp_path)
    assert set(receipt['changed'])==set(selected) and path.read_bytes()==before
    assert compare_fidelity(path,destination)['status']=='pass'
    with pikepdf.open(destination) as pdf:
        doc=pdf.Root.StructTreeRoot.K[0]
        assert str(doc.S)=='/Document' and [str(s.S) for s in doc.K]==['/Sect','/Sect']
        assert [str(c.S) for c in doc.K[0].K]==['/H1','/Figure','/P']


def test_role_and_decorative_changes_can_share_one_explicit_structural_pass(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf',root_role='Div',section_role='Div'); data=decisions(path)
    accept(choose(data,'figure-purpose'),'Artifact')
    for item in data['decisions']:
        if item['kind']=='structure-role':accept(item,'Document' if item['structure_path']=='root/K/0' else 'Sect')
    destination,receipt=apply(path,data,tmp_path)
    assert len(receipt['changed'])==4 and compare_fidelity(path,destination)['status']=='pass'


@pytest.mark.parametrize('flag',['figure_text','shared_stream','nested_marks','actual_text','figure_id'])
def test_ambiguous_or_semantic_figure_content_is_read_only(tmp_path,flag):
    path=artifact_pdf(tmp_path/'source.pdf',**{flag:True}); data=decisions(path); item=choose(data,'figure-purpose')
    assert not item['structural_eligible'] and item['structural_limitations']
    assert item['allowed_values']==['Figure']
    with pytest.raises(sidecar.DecisionError):accept(item,'Artifact')
    assert not (tmp_path/'edited.pdf').exists()


@pytest.mark.parametrize('defect',['wrong-slot','extra-reference','single-child','form','parent-pointer','figure-child','duplicate-mark'])
def test_unsafe_relationships_are_never_offered_as_decorative_repairs(tmp_path,defect):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        root=pdf.Root.StructTreeRoot; group=root.K[0].K[0]; figure=group.K[1]
        if defect=='wrong-slot':root.ParentTree.Nums[1][1]=group.K[0]
        elif defect=='extra-reference':root.CustomReference=figure
        elif defect=='single-child':group.K=pikepdf.Array([figure])
        elif defect=='form':
            form=pdf.make_stream(b'0 0 20 20 re f');form.Type=pikepdf.Name.XObject;form.Subtype=pikepdf.Name.Form;form.BBox=pikepdf.Array([0,0,20,20]);form.Resources=pikepdf.Dictionary()
            pdf.pages[0].obj.Resources.XObject=pikepdf.Dictionary(Fm1=form)
            pdf.pages[0].obj.Contents=pdf.make_stream(b'/H1 <</MCID 0>> BDC BT /F1 14 Tf 50 420 Td (Heading) Tj ET EMC /Figure <</MCID 1>> BDC /Fm1 Do EMC /P <</MCID 2>> BDC BT /F1 11 Tf 50 100 Td (Paragraph) Tj ET EMC')
        elif defect=='parent-pointer':figure.P=root.K[0]
        elif defect=='figure-child':figure.K=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Span,P=figure,Pg=pdf.pages[0].obj,K=1))
        else:
            raw=pdf.pages[0].obj.Contents.read_bytes();pdf.pages[0].obj.Contents.write(raw+b'/Figure <</MCID 1>> BDC 0 0 20 20 re f EMC')
        target=tmp_path/'malformed.pdf'
        with target.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    item=choose(decisions(target),'figure-purpose')
    assert not item['structural_eligible'] and item['structural_limitations']


def test_bounding_box_diagnostics_are_read_only_and_explicit_about_unmeasured_fit(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf'); missing=choose(decisions(path),'figure-purpose')['figure_bbox']
    assert missing['status']=='missing' and missing['bbox'] is None
    with pikepdf.open(path) as pdf:
        pdf.Root.StructTreeRoot.K[0].K[0].K[1].A=pikepdf.Dictionary(O=pikepdf.Name.Layout,BBox=pikepdf.Array([80,180,180,240]))
        target=tmp_path/'bounds.pdf'
        with target.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=decisions(target); item=choose(data,'figure-purpose')
    assert item['figure_bbox']['status']=='valid' and item['figure_bbox']['bbox']==[80.,180.,180.,240.]
    assert 'unmeasured' in item['figure_bbox']['reason'] and 'bottom-left' in item['figure_bbox']['coordinate_system']
    edited=copy.deepcopy(data); forged=choose(edited,'figure-purpose');forged['figure_bbox']['bbox']=[0.,0.,1.,1.]
    accept(forged,'Artifact')
    with pytest.raises(sidecar.DecisionError,match='context'):apply(target,edited,tmp_path)


@pytest.mark.parametrize('box,expected',[(pikepdf.Array([180,180,80,240]),'invalid'),(pikepdf.Array([-1,0,50,50]),'invalid'),(pikepdf.Array([1,2,3]),'invalid')])
def test_malformed_or_offpage_bounds_remain_diagnostics(tmp_path,box,expected):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        pdf.Root.StructTreeRoot.K[0].K[0].K[1].A=pikepdf.Dictionary(O=pikepdf.Name.Layout,BBox=box)
        target=tmp_path/'bounds.pdf'
        with target.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    assert choose(decisions(target),'figure-purpose')['figure_bbox']['status']==expected


def test_changed_description_cannot_also_discard_the_same_figure_semantics(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf'); data=decisions(path); original=path.read_bytes()
    accept(choose(data,'figure-purpose'),'Artifact')
    item=choose(data,'figure-description')
    accept(item,'A changed explicit source-bound value')
    with pytest.raises(sidecar.DecisionError,match='changed description'):apply(path,data,tmp_path)
    assert path.read_bytes()==original and not (tmp_path/'edited.pdf').exists()


def test_accepted_noop_description_is_compatible_with_decorative_change(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf'); data=decisions(path)
    accept(choose(data,'figure-purpose'),'Artifact')
    description=choose(data,'figure-description');accept(description,description['current'])
    destination,receipt=apply(path,data,tmp_path)
    assert destination.exists() and len(receipt['changed'])==1


def test_graph_or_content_corruption_after_writer_is_independently_rejected(tmp_path,monkeypatch):
    from pdf_remediator import structure_edits
    path=artifact_pdf(tmp_path/'source.pdf'); data=decisions(path);accept(choose(data,'figure-purpose'),'Artifact')
    original=structure_edits.apply_changes
    def faulty_writer(pdf,items,**kwargs):
        changed=original(pdf,items,**kwargs)
        pdf.Root.Lang='fr-FR'
        return changed
    monkeypatch.setattr(structure_edits,'apply_changes',faulty_writer)
    with pytest.raises(sidecar.DecisionError,match='preserve'):apply(path,data,tmp_path)
    assert not (tmp_path/'edited.pdf').exists()


def test_pending_controls_copy_exact_bytes_and_noop_is_not_an_approval(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf'); data=decisions(path)
    destination,receipt=apply(path,data,tmp_path)
    assert destination.read_bytes()==path.read_bytes() and receipt['changed']==[] and receipt['approved']==[]


def test_new_kinds_are_never_automatically_authorized(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf'); data=decisions(path); item=choose(data,'figure-purpose')
    with pytest.raises(sidecar.DecisionError):
        sidecar.make_automatic_authorization(data['source_sha256'],data['document_sha256'],'2026-10-27',decision_ids=[item['id']])


@pytest.mark.parametrize('alias',['stream','contents-array','children-array','parent-values','parent-numbers','parent-branch','number-key','struct-parent-key','parent-node'])
def test_mutated_indirect_streams_arrays_and_parent_keys_require_unique_ownership(tmp_path,alias):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        root=pdf.Root.StructTreeRoot;group=root.K[0].K[0];page=pdf.pages[0]
        if alias=='stream':root.CustomAlias=page.obj.Contents
        elif alias=='contents-array':
            value=pdf.make_indirect(pikepdf.Array([page.obj.Contents]));page.obj.Contents=value;root.CustomAlias=value
        elif alias=='children-array':
            value=pdf.make_indirect(pikepdf.Array(list(group.K)));group.K=value;root.CustomAlias=value
        elif alias=='parent-values':
            value=pdf.make_indirect(pikepdf.Array(list(root.ParentTree.Nums[1])));root.ParentTree.Nums[1]=value;root.CustomAlias=value
        elif alias=='parent-numbers':
            value=pdf.make_indirect(pikepdf.Array(list(root.ParentTree.Nums)));root.ParentTree.Nums=value;root.CustomAlias=value
        elif alias=='parent-branch':root.CustomAlias=root.ParentTree
        elif alias=='number-key':
            value=pdf.make_indirect(pikepdf.Array(list(root.ParentTree.Nums[1])));root.ParentTree.Nums[1]=value;root.ParentTree.Nums[3]=value
        elif alias=='struct-parent-key':pdf.pages[1].obj.StructParents=0
        else:root.CustomAlias=group
        target=tmp_path/'aliased.pdf'
        with target.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    item=choose(decisions(target),'figure-purpose')
    assert not item['structural_eligible'] and item['allowed_values']==['Figure']
    with pytest.raises(sidecar.DecisionError):accept(item,'Artifact')


@pytest.mark.parametrize('alias',['parent-group','figure','parent-tree'])
def test_trailer_info_is_counted_as_an_independent_inbound_graph_root(tmp_path,alias):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        root=pdf.Root.StructTreeRoot;group=root.K[0].K[0]
        pdf.trailer.Info={'parent-group':group,'figure':group.K[1],'parent-tree':root.ParentTree}[alias]
        target=tmp_path/'info-alias.pdf'
        with target.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=decisions(target);item=choose(data,'figure-purpose')
    assert not item['structural_eligible'] and item['structural_limitations']
    with pytest.raises(sidecar.DecisionError):accept(item,'Artifact')
    if alias=='parent-group':
        container=next(i for i in data['decisions'] if i['kind']=='structure-role' and i['structure_path']=='root/K/0/K/0')
        assert not container['structural_eligible']
        with pytest.raises(sidecar.DecisionError):accept(container,'Sect')


@pytest.mark.parametrize('target',['Document','Sect'])
def test_standard_role_targets_cannot_be_redirected_by_rolemaps(tmp_path,target):
    path=artifact_pdf(tmp_path/'source.pdf',root_role='Div',section_role='Div')
    with pikepdf.open(path) as pdf:
        pdf.Root.StructTreeRoot.RoleMap=pikepdf.Dictionary({'/'+target:pikepdf.Name.Figure})
        output=tmp_path/'remapped.pdf'
        with output.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    items=[i for i in decisions(output)['decisions'] if i['kind']=='structure-role' and
           (i['structure_path']=='root/K/0' if target=='Document' else i['structure_path']!='root/K/0')]
    assert items
    for item in items:
        assert not item['structural_eligible'] and item['allowed_values']==['Div']
        with pytest.raises(sidecar.DecisionError):accept(item,target)


@pytest.mark.parametrize('defect',['boolean-property','boolean-mcr','expansion','language','custom-property','parent-actualtext','document-actualtext'])
def test_boolean_mcids_and_unreviewed_replacement_properties_remain_read_only(tmp_path,defect):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        group=pdf.Root.StructTreeRoot.K[0].K[0];figure=group.K[1];page=pdf.pages[0]
        if defect=='boolean-mcr':figure.K=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.MCR,Pg=page.obj,MCID=True))
        elif defect=='parent-actualtext':group.ActualText='An enclosing replacement statement'
        elif defect=='document-actualtext':pdf.Root.StructTreeRoot.K[0].ActualText='A document replacement statement'
        else:
            replacement={'boolean-property':b'/MCID true','expansion':b'/MCID 1 /E (Expanded source meaning)',
                'language':b'/MCID 1 /Lang (en-US)','custom-property':b'/MCID 1 /Custom /Important'}[defect]
            page.obj.Contents.write(page.obj.Contents.read_bytes().replace(b'/MCID 1',replacement))
        target=tmp_path/'ambiguous-properties.pdf'
        with target.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    item=choose(decisions(target),'figure-purpose')
    assert not item['structural_eligible'] and item['structural_limitations']


def test_batch_conversion_cannot_silently_prune_the_last_parent_children(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        group=pdf.Root.StructTreeRoot.K[0].K[0];first=group.K[1];second=group.K[2]
        second.S=pikepdf.Name.Figure;second.Alt='Second explicit graphic';group.K=pikepdf.Array([first,second])
        pdf.Root.StructTreeRoot.ParentTree.Nums[1][0]=None
        pdf.pages[0].obj.Contents.write(b'/Figure <</MCID 1>> BDC 80 180 100 60 re f EMC /Figure <</MCID 2>> BDC 40 40 10 10 re f EMC')
        source=tmp_path/'two-children.pdf'
        with source.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=decisions(source)
    selected=[i for i in data['decisions'] if i['kind']=='figure-purpose' and i['page']==1]
    assert len(selected)==2 and all(i['structural_eligible'] for i in selected)
    for item in selected:accept(item,'Artifact')
    with pytest.raises(sidecar.DecisionError,match='empty'):apply(source,data,tmp_path)
    assert not (tmp_path/'edited.pdf').exists()


def test_later_title_and_language_changes_replay_the_same_accepted_purpose_safely(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf');data=decisions(path)
    accept(choose(data,'figure-purpose'),'Artifact')
    first,receipt=apply(path,data,tmp_path,'first.pdf');first_hash=sidecar.file_sha256(first)
    title=next(i for i in data['decisions'] if i['kind']=='title');accept(title,'A later explicitly edited title')
    language=next(i for i in data['decisions'] if i['kind']=='language');accept(language,'en-GB')
    second,receipt=apply(path,data,tmp_path,'second.pdf')
    assert len(receipt['changed'])==3 and sidecar.file_sha256(first)==first_hash
    assert compare_fidelity(path,second)['status']=='pass'
    with pikepdf.open(second) as pdf:
        assert str(pdf.docinfo.Title)=='A later explicitly edited title' and str(pdf.Root.Lang)=='en-GB'
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][1] is None


@pytest.mark.parametrize('kind',['figure-description','heading-tag'])
def test_unrelated_ordinary_edits_have_exact_expected_mutations_in_combined_pass(tmp_path,kind):
    path=artifact_pdf(tmp_path/'source.pdf');data=decisions(path)
    accept(choose(data,'figure-purpose'),'Artifact')
    if kind=='figure-description':item=choose(data,kind,page=2);value='A revised meaningful description of the second diagram'
    else:item=next(i for i in data['decisions'] if i['kind']==kind and i['page']==1 and i['current']=='P');value='H2'
    accept(item,value)
    target,receipt=apply(path,data,tmp_path)
    assert len(receipt['changed'])==2 and compare_fidelity(path,target)['status']=='pass'
    with pikepdf.open(target) as pdf:
        if kind=='figure-description':assert str(pdf.Root.StructTreeRoot.K[0].K[1].K[1].Alt)==value
        else:assert str(pdf.Root.StructTreeRoot.K[0].K[0].K[1].S)=='/H2'


def test_table_role_scope_changes_keep_unrelated_attributes_in_combined_pass(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        section=pdf.Root.StructTreeRoot.K[0].K[0];cell=section.K[2]
        table=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Table,P=section))
        row=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.TR,P=table,K=pikepdf.Array([cell])))
        table.K=pikepdf.Array([row]);cell.P=row;cell.S=pikepdf.Name.TD
        cell.A=pikepdf.Dictionary(O=pikepdf.Name.Table,RowSpan=1,ColSpan=1)
        section.K[2]=table
        source=tmp_path/'table.pdf'
        with source.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=decisions(source);accept(choose(data,'figure-purpose'),'Artifact')
    cell=next(i for i in data['decisions'] if i['kind']=='table-header')
    accept(cell,'{"role":"TH","scope":"Column"}')
    destination,receipt=apply(source,data,tmp_path)
    assert len(receipt['changed'])==2 and compare_fidelity(source,destination)['status']=='pass'
    with pikepdf.open(destination) as pdf:
        node=pdf.Root.StructTreeRoot.K[0].K[0].K[1].K[0].K[0]
        assert str(node.S)=='/TH'
        attrs=list(node.A);assert any(int(a.get('/RowSpan',0))==1 and int(a.get('/ColSpan',0))==1 for a in attrs)
        assert any(str(a.get('/Scope',''))=='/Column' for a in attrs)


def test_more_than_200_pages_does_not_disable_or_fail_established_processing(tmp_path):
    path=artifact_pdf(tmp_path/'source.pdf')
    with pikepdf.open(path) as pdf:
        for _ in range(199):pdf.add_blank_page(page_size=(20,20))
        source=tmp_path/'long.pdf'
        with source.open('wb') as stream:pdf.save(stream,deterministic_id=True)
    data=decisions(source);item=choose(data,'figure-purpose')
    assert item['structural_eligible'];accept(item,'Artifact')
    destination,receipt=apply(source,data,tmp_path)
    with pikepdf.open(destination) as pdf:assert len(pdf.pages)==201
    assert receipt['changed']==[item['id']]


def test_advanced_proof_limits_disable_only_new_controls_and_keep_metadata_working(tmp_path,monkeypatch):
    from pdf_remediator import structure_edits
    path=artifact_pdf(tmp_path/'source.pdf')
    original=sidecar.collect_decisions(path,inventory_profile=sidecar.STRUCTURAL_INVENTORY_PROFILE)
    def bounded_proof(*args,**kwargs):raise sidecar.DecisionError('Explicit authored proof-limit fixture')
    monkeypatch.setattr(structure_edits,'_snapshot',bounded_proof)
    data=decisions(path)
    assert data['decisions'][:len(original['decisions'])]==original['decisions']
    extra=data['decisions'][len(original['decisions']):]
    assert extra and all(not i['structural_eligible'] and i['allowed_values']==[i['current']] for i in extra)
    title=next(i for i in data['decisions'] if i['kind']=='title');accept(title,'Metadata remains editable with advanced controls unavailable')
    target,receipt=apply(path,data,tmp_path)
    assert receipt['changed']==['metadata:title']
    with pikepdf.open(target) as pdf:assert str(pdf.docinfo.Title)==title['value']
    forced=copy.deepcopy(data);bad=choose(forced,'figure-purpose');bad['structural_eligible']=True;bad['allowed_values'].append('Artifact');accept(bad,'Artifact')
    with pytest.raises(sidecar.DecisionError,match='context'):apply(path,forced,tmp_path,'forced.pdf')
    assert not (tmp_path/'forced.pdf').exists()


def _jpeg_bytes(color=(30,70,170)):
    from PIL import Image
    out=io.BytesIO()
    Image.new('RGB',(8,8),color).save(out,format='JPEG',quality=90)
    return out.getvalue()


def jpeg_artifact_pdf(path):
    source=artifact_pdf(Path(path).with_name('jpeg-source-base.pdf'))
    with pikepdf.open(source) as pdf:
        image=pdf.make_stream(_jpeg_bytes());image.Type=pikepdf.Name.XObject;image.Subtype=pikepdf.Name.Image
        image.Width=8;image.Height=8;image.ColorSpace=pikepdf.Name.DeviceRGB;image.BitsPerComponent=8
        image.Filter=pikepdf.Name.DCTDecode;image.DecodeParms=pikepdf.Dictionary(ColorTransform=1)
        page=pdf.pages[0];page.obj.Resources.XObject=pikepdf.Dictionary(Im1=image)
        raw=page.obj.Contents.read_bytes()
        page.obj.Contents.write(raw.replace(b'q .2 .4 .6 rg 80 180 100 60 re f Q',b'q 100 0 0 60 80 180 cm /Im1 Do Q'))
        with Path(path).open('wb') as stream:pdf.save(stream,deterministic_id=True)
    return Path(path)


def test_valid_jpeg_figure_preserves_exact_encoded_image_and_codec_parameters(tmp_path):
    source=jpeg_artifact_pdf(tmp_path/'jpeg.pdf');original=source.read_bytes()
    with pikepdf.open(source) as pdf:
        image=pdf.pages[0].obj.Resources.XObject.Im1
        with pytest.raises(pikepdf.PdfError):image.read_bytes()
        encoded=image.read_raw_bytes();snapshot=_snapshot(pdf)
        image_key=f'{image.objgen[0]}:{image.objgen[1]}'
        bound=snapshot['objects'][image_key]
        assert bound['payload_mode']=='opaque-encoded' and bound['payload']==hashlib.sha256(encoded).hexdigest()
        assert bound['d']['/Filter']=={'t':'name','v':'/DCTDecode'} and '/DecodeParms' in bound['d']
    data=decisions(source);item=choose(data,'figure-purpose')
    assert item['structural_eligible'];accept(item,'Artifact')
    destination,receipt=apply(source,data,tmp_path)
    assert receipt['changed']==[item['id']] and source.read_bytes()==original
    assert compare_fidelity(source,destination)['status']=='pass'
    with pikepdf.open(destination) as pdf:
        image=pdf.pages[0].obj.Resources.XObject.Im1
        assert image.read_raw_bytes()==encoded and str(image.Filter)=='/DCTDecode'
        assert int(image.DecodeParms.ColorTransform)==1
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][1] is None


@pytest.mark.parametrize('fault',['encoded-payload','filter','decode-parameters'])
def test_opaque_image_bytes_and_codec_metadata_are_not_excluded_from_preservation(tmp_path,monkeypatch,fault):
    from pdf_remediator import structure_edits
    source=jpeg_artifact_pdf(tmp_path/'jpeg.pdf');original=source.read_bytes();data=decisions(source)
    accept(choose(data,'figure-purpose'),'Artifact');good_writer=structure_edits.apply_changes
    def bad_writer(pdf,items,**kwargs):
        changed=good_writer(pdf,items,**kwargs);image=pdf.pages[0].obj.Resources.XObject.Im1
        if fault=='encoded-payload':
            image.write(_jpeg_bytes((190,40,20)));image.Filter=pikepdf.Name.DCTDecode;image.DecodeParms=pikepdf.Dictionary(ColorTransform=1)
        elif fault=='filter':image.Filter=pikepdf.Name.JPXDecode
        else:image.DecodeParms=pikepdf.Dictionary(ColorTransform=0)
        return changed
    monkeypatch.setattr(structure_edits,'apply_changes',bad_writer)
    with pytest.raises(sidecar.DecisionError,match='preserve'):apply(source,data,tmp_path)
    assert source.read_bytes()==original and not (tmp_path/'edited.pdf').exists()


def test_undecodable_and_unreadable_resource_proof_disables_new_controls_only(tmp_path,monkeypatch):
    from pdf_remediator import structure_edits
    source=artifact_pdf(tmp_path/'source.pdf')
    def unreadable_resource(*args,**kwargs):raise pikepdf.PdfError('Authored resource read refusal')
    monkeypatch.setattr(structure_edits,'_snapshot',unreadable_resource)
    data=decisions(source);extra=[i for i in data['decisions'] if i['kind'] in {'figure-purpose','structure-role'}]
    assert extra and all(not i['structural_eligible'] for i in extra)
    title=next(i for i in data['decisions'] if i['kind']=='title');accept(title,'An ordinary title remains editable')
    destination,receipt=apply(source,data,tmp_path)
    assert destination.exists() and receipt['changed']==['metadata:title']


def test_keep_figure_reuses_bound_original_checkpoint_without_reconstructing_deleted_structure(tmp_path):
    source=artifact_pdf(tmp_path/'source.pdf');original=source.read_bytes();data=decisions(source)
    item=choose(data,'figure-purpose');accept(item,'Artifact')
    first,receipt=apply(source,data,tmp_path,'decorative.pdf');first_bytes=first.read_bytes()
    accept(item,'Figure')
    restored,receipt=apply(source,data,tmp_path,'meaningful.pdf')
    assert receipt['changed']==[] and restored.read_bytes()==original
    assert source.read_bytes()==original and first.read_bytes()==first_bytes
    with pikepdf.open(restored) as pdf:
        group=pdf.Root.StructTreeRoot.K[0].K[0]
        assert [str(n.S) for n in group.K]==['/H1','/Figure','/P']
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][1].objgen==group.K[1].objgen
