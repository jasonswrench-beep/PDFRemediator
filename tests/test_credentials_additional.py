"""Independent raw C2PA attachment, consent and semantic-detach regressions.

Fixtures and the projection below do not use the credential writer's fixture,
scanner or graph-oracle implementation. The parent runs/creates every PDF.
"""
from __future__ import annotations

import copy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pikepdf
import pytest

from pdf_remediator import credentials,engines,pipeline,sidecar,workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.inspection import inspect_pdf
from test_table_additional import _seed_bootstrap,_assert_seed_bootstrap_unchanged


POLICY = 'remove-content-credentials-1'
PAYLOAD = b'Independent synthetic C2PA-designated manifest; validity not asserted.\x00\xff'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in Path(root).rglob('*') if p.is_file()}


def source_pdf(path, *, mutate=None, af_indirect=False, payload=PAYLOAD,mime_subtype='/application/x-c2pa-manifest-store'):
    """An independently authored two-page PDF; never an authenticity claim."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.new() as pdf:
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        for index in range(2):
            page = pdf.add_blank_page(page_size=(300, 240))
            page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            page.obj.Contents = pdf.make_stream(f'BT /F1 12 Tf 20 190 Td (Independent page {index + 1}) Tj ET'.encode())
        pdf.Root.Lang = 'en-US'
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.docinfo.Title = 'Preserve independent visible pages and metadata'
        pdf.docinfo.Author = 'Synthetic QA fixture'
        pdf.Root.Metadata = pdf.make_stream(b'<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/"/><?xpacket end="w"?>')
        pdf.Root.Metadata.Type = pikepdf.Name.Metadata
        pdf.Root.Metadata.Subtype = pikepdf.Name.XML
        embedded = pdf.make_stream(payload); embedded.Type = pikepdf.Name.EmbeddedFile
        embedded.Subtype = pikepdf.Name(mime_subtype)
        spec = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Filespec,
            F='CAI_Attachment_File.c2pa', UF='CAI_Attachment_File.c2pa',
            AFRelationship=pikepdf.Name.C2PA_Manifest,
            EF=pikepdf.Dictionary(F=embedded)))
        af = pikepdf.Array([spec]); pdf.Root.AF = pdf.make_indirect(af) if af_indirect else af
        if mutate: mutate(pdf, spec, embedded)
        with path.open('xb') as stream:
            pdf.save(stream, deterministic_id=True, min_version='1.7', fix_metadata_version=False,compress_streams=False)
    return path


def assessment(path):
    with pikepdf.open(path) as pdf:
        return credentials.inspect_credentials(pdf)


def consent(path, **changes):
    result = {'policy': POLICY, 'source_sha256': sha(path), 'reviewer': 'Independent synthetic-case reviewer',
        'reviewed_at': '2026-10-28T12:00:00+00:00', 'allow_remove': True}
    result.update(changes)
    return result


def project(path, *, detach=False):
    """Canonical reachable Root/Info graph with independently assigned ref IDs.

    Only the selected catalog AF edge may be omitted. Shared object topology,
    all other keys/values and decoded nonpage/page payloads remain significant.
    """
    with pikepdf.open(path) as pdf:
        references = {}; records = []; pending = []

        def encode(value, *, root=False, dereference=False):
            identity = tuple(value.objgen) if isinstance(value,pikepdf.Object) else None
            if identity == (0,0): identity = None
            if identity and not dereference:
                if identity not in references:
                    references[identity] = len(references); pending.append((references[identity],value,root))
                return {'ref': references[identity]}
            if isinstance(value,pikepdf.Stream):
                ignored = {'/Length','/Filter','/DecodeParms'}
                try: data = value.read_bytes(); mode = 'decoded'
                except pikepdf.PdfError:
                    data = value.read_raw_bytes(); mode = 'opaque'; ignored = {'/Length'}
                return {'stream': {str(k): encode(v) for k,v in sorted(value.items()) if str(k) not in ignored},
                    'mode': mode, 'sha256': hashlib.sha256(data).hexdigest()}
            if isinstance(value,pikepdf.Dictionary):
                return {'dict': {str(k): encode(v) for k,v in sorted(value.items())
                    if not (root and detach and str(k) == '/AF')}}
            if isinstance(value,pikepdf.Array): return {'array': [encode(item) for item in value]}
            if isinstance(value,pikepdf.String): return {'string': bytes(value).hex()}
            if isinstance(value,pikepdf.Name): return {'name': str(value)}
            if value is None or type(value) is bool: return value
            if isinstance(value,(int,float,Decimal)): return {'number':str(Decimal(str(value)).normalize())}
            raise AssertionError('Unrecognized independent fixture object: '+repr(value))

        roots = {'root':encode(pdf.Root,root=True),'info':encode(pdf.trailer.get('/Info'))}
        for number,obj,is_root in pending:
            records.append((number,encode(obj,root=is_root,dereference=True)))
        return {'roots':roots,'objects':records}


@pytest.mark.parametrize('af_indirect',[False,True])
@pytest.mark.parametrize('mime_subtype',['/application/x-c2pa-manifest-store','/application#2Fx-c2pa-manifest-store'])
def test_independent_sole_C2PA_candidate_requires_explicit_consent_and_exact_detach(tmp_path,af_indirect,mime_subtype):
    source=source_pdf(tmp_path/'original.pdf',af_indirect=af_indirect,mime_subtype=mime_subtype); before=source.read_bytes()
    result=assessment(source)
    assert result['policy']=='bounded-c2pa-associated-file-1' and result['supported'] is True
    assert len(result['files'])==1 and result['files'][0]['relationship']=='/C2PA_Manifest'
    assert result['files'][0]['decoded_sha256']==hashlib.sha256(PAYLOAD).hexdigest()
    assert result['files'][0]['decoded_bytes']==len(PAYLOAD)
    assert result['files'][0]['mime_subtype']==mime_subtype and result['credentials_verified'] is False
    expected=project(source,detach=True)
    output=tmp_path/'copy.pdf'; evidence=tmp_path/'evidence'
    created=credentials.create_derivative(source,output,evidence,consent=consent(source))
    assert Path(created['source_path'])==output and created['source_sha256']==sha(output)
    assert output.exists() and source.read_bytes()==before
    assert project(output)==expected
    with pikepdf.open(output) as pdf:
        assert '/AF' not in pdf.Root
        assert not any(isinstance(obj,pikepdf.Stream) and obj.get('/Type')==pikepdf.Name.EmbeddedFile for obj in pdf.objects)
    assert assessment(output)['supported'] is False
    assert (evidence/'original.pdf').read_bytes()==before
    assert (evidence/'credential-payload.bin').read_bytes()==PAYLOAD
    assert Path(created['lineage_path']).is_file() and created['lineage_sha256']==sha(created['lineage_path'])
    for validate in (credentials.validate_lineage_bindings,credentials.validate_lineage):
        verified=validate(created['lineage_path'],output,expected_sha256=created['lineage_sha256'])
        assert verified['binding_verified'] is True and verified['policy']==POLICY
        assert verified['summary']['status']=='credentials-removed-original-not-verified'


def test_independent_existing_links_destinations_labels_outline_and_optional_description_are_retained(tmp_path):
    def navigation(pdf,spec,stream):
        spec.Desc='Producer supplied provenance payload'
        target=pikepdf.Array([pdf.pages[1].obj,pikepdf.Name.Fit])
        pdf.Root.Names=pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array(['chapter-two',target])))
        pdf.Root.PageLabels=pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Dictionary(S=pikepdf.Name.r),1,pikepdf.Dictionary(S=pikepdf.Name.D,St=2)]))
        outline=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines,Count=1))
        entry=pdf.make_indirect(pikepdf.Dictionary(Title='Retain the second-page bookmark',Parent=outline,Dest=target))
        outline.First=entry;outline.Last=entry;pdf.Root.Outlines=outline
        action=pikepdf.Dictionary(S=pikepdf.Name.URI,URI='https://example.invalid/reference',IsMap=False)
        link=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([20,20,140,36]),Contents='Keep this existing link',A=action))
        pdf.pages[0].obj.Annots=pikepdf.Array([link])
    source=source_pdf(tmp_path/'source.pdf',mutate=navigation);before=source.read_bytes()
    assert assessment(source)['supported'] is True
    output=tmp_path/'copy.pdf';evidence=tmp_path/'evidence'
    credentials.create_derivative(source,output,evidence,consent=consent(source))
    assert project(output)==project(source,detach=True) and source.read_bytes()==before


def variant(pdf,spec,stream,hazard):
    if hazard=='ordinary-file': spec.AFRelationship=pikepdf.Name.Data; spec.F='notes.txt';spec.UF='notes.txt'
    elif hazard=='filename-only': del spec['/AFRelationship']
    elif hazard=='no-EF': del spec['/EF']
    elif hazard=='missing-stream': spec.EF.F=pikepdf.Dictionary(Type=pikepdf.Name.EmbeddedFile)
    elif hazard=='second-AF': pdf.Root.AF.append(pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Filespec,F='other.txt',EF=pikepdf.Dictionary(F=pdf.make_stream(b'other')))))
    elif hazard=='name-tree': pdf.Root.Names=pikepdf.Dictionary(EmbeddedFiles=pikepdf.Dictionary(Names=pikepdf.Array(['manifest',spec])))
    elif hazard=='page-AF': pdf.pages[0].obj.AF=pikepdf.Array([spec])
    elif hazard=='structure-AF': pdf.Root.StructTreeRoot=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot,AF=pikepdf.Array([spec])))
    elif hazard=='annotation': pdf.pages[0].obj.Annots=pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.FileAttachment,Rect=pikepdf.Array([10,10,30,30]),FS=spec))])
    elif hazard=='portfolio': pdf.Root.Collection=pikepdf.Dictionary()
    elif hazard=='filespec-alias': pdf.Root.IndependentAlias=spec
    elif hazard=='stream-alias': pdf.Root.IndependentPayloadAlias=stream
    elif hazard=='additional-EF': spec.EF.UF=pdf.make_stream(b'independent additional payload')
    elif hazard=='additional-stream':
        extra=pdf.make_stream(b'other embedded bytes');extra.Type=pikepdf.Name.EmbeddedFile;pdf.Root.IndependentOtherFile=extra
    elif hazard=='signature': pdf.Root.Perms=pikepdf.Dictionary(DocMDP=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Sig,ByteRange=pikepdf.Array([0,1,2,3]))))
    elif hazard=='javascript': pdf.Root.OpenAction=pikepdf.Dictionary(S=pikepdf.Name.JavaScript,JS='doNotExecute()')
    elif hazard=='empty-AF': pdf.Root.AF=pikepdf.Array()
    elif hazard=='AF-scalar': pdf.Root.AF=pikepdf.String('not an array')
    elif hazard=='mime-near-miss': stream.Subtype=pikepdf.Name('/application/other-c2pa-manifest-store')
    elif hazard=='mime-other-escape': stream.Subtype=pikepdf.Name('/application#2fx-c2pa-manifest-store')
    elif hazard=='different-UF': spec.UF='a-different-manifest.c2pa'
    elif hazard=='filename-path': spec.F=spec.UF='../manifest.c2pa'
    elif hazard=='unknown-spec-key': spec.IndependentAuthority='not selected'
    elif hazard=='XMP-extra-claim': pdf.Root.Metadata.write(b'<x:xmpmeta xmlns:x="adobe:ns:meta/">C2PA additional claim</x:xmpmeta>')
    elif hazard=='empty-payload': stream.write(b'')
    else: raise AssertionError(hazard)


@pytest.mark.parametrize('hazard',['ordinary-file','filename-only','no-EF','missing-stream','second-AF',
    'name-tree','page-AF','structure-AF','annotation','portfolio','filespec-alias','stream-alias',
    'additional-EF','additional-stream','signature','javascript','empty-AF','AF-scalar',
    'mime-near-miss','mime-other-escape','different-UF','filename-path','unknown-spec-key','XMP-extra-claim','empty-payload'])
def test_independent_unsupported_or_ambiguous_attachments_never_gain_copy_authority(tmp_path,hazard):
    source=source_pdf(tmp_path/'source.pdf',mutate=lambda pdf,spec,stream:variant(pdf,spec,stream,hazard))
    before=source.read_bytes(); result=assessment(source)
    assert result['supported'] is False
    with pytest.raises(ValueError):
        credentials.create_derivative(source,tmp_path/'forbidden.pdf',tmp_path/'forbidden-evidence',consent=consent(source))
    assert source.read_bytes()==before and not (tmp_path/'forbidden.pdf').exists()
    assert not (tmp_path/'forbidden-evidence').exists(), 'Refusal must precede derivative/evidence creation'


@pytest.mark.parametrize('changes',[{'allow_remove':False},{'allow_remove':1},{'source_sha256':'0'*64},
    {'policy':'remove-all-attachments'},{'reviewer':''},{'reviewed_at':''},{'reviewed_at':'2026-10-28'},{'unexpected':'not authorized'}])
def test_independent_stale_incomplete_or_broader_consent_cannot_write_any_copy(tmp_path,changes):
    source=source_pdf(tmp_path/'source.pdf'); before=source.read_bytes()
    with pytest.raises(ValueError):
        credentials.create_derivative(source,tmp_path/'forbidden.pdf',tmp_path/'forbidden-evidence',consent=consent(source,**changes))
    assert source.read_bytes()==before and not (tmp_path/'forbidden.pdf').exists() and not (tmp_path/'forbidden-evidence').exists()


@pytest.mark.parametrize('existing',['output','evidence','same-source'])
def test_independent_existing_paths_never_replace_original_or_saved_review(tmp_path,existing):
    source=source_pdf(tmp_path/'original.pdf'); output=tmp_path/'copy.pdf'; evidence=tmp_path/'evidence'
    if existing=='output': output.write_bytes(b'An existing saved artifact must remain unchanged')
    elif existing=='evidence': evidence.mkdir();(evidence/'review-notes.json').write_text('{"notes":"retain these saved notes"}')
    else: output=source
    before=files(tmp_path)
    with pytest.raises((ValueError,FileExistsError)):
        credentials.create_derivative(source,output,evidence,consent=consent(source))
    assert files(tmp_path)==before


def test_independent_precancelled_removal_does_not_create_derivative_or_evidence(tmp_path):
    source=source_pdf(tmp_path/'source.pdf'); before=source.read_bytes(); token=threading.Event();token.set()
    with pytest.raises(InterruptedError):
        credentials.create_derivative(source,tmp_path/'copy.pdf',tmp_path/'evidence',consent=consent(source),cancel=token)
    assert source.read_bytes()==before and not (tmp_path/'copy.pdf').exists() and not (tmp_path/'evidence').exists()


@pytest.mark.parametrize('damaged',['source','original.pdf','credential-payload.bin','credential-encoded.bin',
    'consent.json','verification.json','credential-lineage.json'])
def test_independent_lineage_rechecks_every_immutable_dependency(tmp_path,damaged):
    source=source_pdf(tmp_path/'original-source.pdf');original=source.read_bytes();output=tmp_path/'copy.pdf';evidence=tmp_path/'evidence'
    created=credentials.create_derivative(source,output,evidence,consent=consent(source))
    target=output if damaged=='source' else evidence/damaged
    assert target.is_file()
    target.write_bytes(target.read_bytes()+b'\nIndependent deliberate dependency corruption\n')
    for validate in (credentials.validate_lineage_bindings,credentials.validate_lineage):
        with pytest.raises(ValueError):
            validate(created['lineage_path'],output,expected_sha256=created['lineage_sha256'])
    assert source.read_bytes()==original


@pytest.mark.parametrize('same_bytes',[True,False])
def test_independent_uploaded_copy_uses_exact_content_binding_without_approval_credit(tmp_path,same_bytes):
    source=source_pdf(tmp_path/'original.pdf');output=tmp_path/'copy.pdf';evidence=tmp_path/'evidence'
    created=credentials.create_derivative(source,output,evidence,consent=consent(source))
    unrelated=tmp_path/'another-source.pdf';unrelated.write_bytes(output.read_bytes()+(b'' if same_bytes else b'\nChanged source bytes\n'))
    for validate in (credentials.validate_lineage_bindings,credentials.validate_lineage):
        if same_bytes:
            result=validate(created['lineage_path'],unrelated,expected_sha256=created['lineage_sha256'])
            assert result['binding_verified'] is True
            assert result['summary']['source_sha256']==sha(output)
            assert result['summary']['status']=='credentials-removed-original-not-verified'
        else:
            with pytest.raises(ValueError):
                validate(created['lineage_path'],unrelated,expected_sha256=created['lineage_sha256'])


def test_real_C2PA_remains_a_processing_blocker_until_separate_derivative_is_selected(tmp_path):
    source=source_pdf(tmp_path/'source.pdf');before=source.read_bytes();inspected=inspect_pdf(source)
    assert inspected['features']['attachments'] is True
    assert source.read_bytes()==before


def blocked_workspace(root,monkeypatch):
    source=source_pdf(root/'original.pdf')
    def forbidden(*args,**kwargs):raise AssertionError('No writer is authorized on the credentialed source')
    monkeypatch.setattr(engines,'tag',forbidden);monkeypatch.setattr(pipeline,'normalize_catalog',forbidden)
    report=pipeline.process_file(source,root/'blocked',RuntimeConfig(project_root=root),mode='fix')
    assert report['status']=='needs-manual' and report['output'] is None
    assert report['baseline']['content_credentials']['supported'] is True
    state=root/'saved-reviews/workspace.json';workspace.create_workspace(report['bundle_path'],state)
    return source,Path(report['bundle_path']),state,workspace.get_view(state)


def copy_payload(view):
    context=view['credential_copy']
    return {'revision':view['revision'],'source_sha256':context['source']['sha256'],
        'context_sha256':context['context_sha256'],'allow_remove':True,
        'reviewer':'Independent synthetic-case reviewer','reviewed_at':'2026-10-28T00:00:00+00:00'}


def test_independent_actual_blocked_needs_manual_report_exposes_source_bound_consent_without_editing_old_review(tmp_path,monkeypatch):
    source,bundle,state,view=blocked_workspace(tmp_path/'case',monkeypatch)
    assert view['credential_copy']['eligible'] is True
    original=source.read_bytes();state_before=state.read_bytes();bundle_before=files(bundle)
    accepted=workspace.credential_copy_consent(state,copy_payload(view))
    assert accepted==consent(source,reviewed_at='2026-10-28T00:00:00+00:00')
    assert source.read_bytes()==original and state.read_bytes()==state_before and files(bundle)==bundle_before
    assert view['verification']=='not-verified'


@pytest.mark.parametrize('changes',[{'revision':True},{'revision':99},{'source_sha256':'0'*64},
    {'context_sha256':'0'*64},{'allow_remove':False},{'allow_remove':1},{'reviewer':''},
    {'reviewed_at':'2026-10-28'},{'reviewed_at':''},{'automatic':True}])
def test_independent_copy_consent_rejects_stale_or_extra_authority_without_mutating_saved_review(tmp_path,monkeypatch,changes):
    source,bundle,state,view=blocked_workspace(tmp_path/'case',monkeypatch)
    before=state.read_bytes();protected=files(bundle);original=source.read_bytes()
    payload=copy_payload(view);payload.update(changes)
    with pytest.raises(workspace.WorkspaceError):workspace.credential_copy_consent(state,payload)
    assert state.read_bytes()==before and files(bundle)==protected and source.read_bytes()==original


def test_independent_context_from_another_workspace_cannot_authorize_same_source_bytes(tmp_path,monkeypatch):
    first=blocked_workspace(tmp_path/'first',monkeypatch);second=blocked_workspace(tmp_path/'second',monkeypatch)
    assert sha(first[0])==sha(second[0]), 'Independent deterministic source controls should have identical bytes'
    assert first[3]['credential_copy']['context_sha256']!=second[3]['credential_copy']['context_sha256']
    before=second[2].read_bytes()
    with pytest.raises(workspace.WorkspaceError):workspace.credential_copy_consent(second[2],copy_payload(first[3]))
    assert second[2].read_bytes()==before


def test_independent_changed_then_restored_original_never_silently_restores_copy_authority(tmp_path,monkeypatch):
    source,bundle,state,view=blocked_workspace(tmp_path/'case',monkeypatch)
    original=source.read_bytes();protected=files(bundle);payload=copy_payload(view)
    source.write_bytes(original+b'\nChanged after consent context was displayed\n')
    with pytest.raises(workspace.WorkspaceError):workspace.credential_copy_consent(state,payload)
    assert workspace.get_view(state)['stale'] is True
    source.write_bytes(original)
    current=workspace.get_view(state)
    assert current['stale'] is True and current['credential_copy']['eligible'] is False
    with pytest.raises(workspace.WorkspaceError):workspace.credential_copy_consent(state,payload)
    assert files(bundle)==protected and source.read_bytes()==original


def nested_table_source(path):
    """Nested cell /K order deliberately differs from IDs, paint order and MCIDs."""
    with pikepdf.new() as pdf:
        page=pdf.add_blank_page(page_size=(360,300))
        font=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,Subtype=pikepdf.Name.Type1,BaseFont=pikepdf.Name.Helvetica))
        page.obj.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
        root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Document,P=root,Pg=page.obj))
        table=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Table,P=document,Pg=page.obj))
        row=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.TR,P=table,Pg=page.obj))
        header=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.TH,P=row,Pg=page.obj,
            A=pikepdf.Dictionary(O=pikepdf.Name.Table,Scope=pikepdf.Name.Column)))
        data=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.TD,P=row,Pg=page.obj))
        # Create objects and paint them in ascending MCID order. Authoring the
        # tree in another order is intentional; do not "fix" it by sorting IDs.
        words={1:'dataOne',2:'headerTwo',4:'dataFour',7:'headerSeven',8:'dataEight',9:'headerNine'}
        owners={}
        for mcid in sorted(words):
            parent=header if mcid in (2,7,9) else data
            owners[mcid]=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.P,P=parent,Pg=page.obj,K=mcid))
        header.K=pikepdf.Array([owners[9],owners[2],owners[7]])
        data.K=pikepdf.Array([owners[8],owners[1],owners[4]])
        row.K=pikepdf.Array([header,data]);table.K=pikepdf.Array([row]);document.K=pikepdf.Array([table]);root.K=pikepdf.Array([document])
        root.ParentTree=pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Array([owners.get(i) for i in range(10)])])))
        page.obj.StructParents=0
        page.obj.Contents=pdf.make_stream(b' '.join(
            f'/P <</MCID {mcid}>> BDC BT /F1 12 Tf 20 {270-index*24} Td ({words[mcid]}) Tj ET EMC'.encode()
            for index,mcid in enumerate(sorted(words))))
        pdf.Root.StructTreeRoot=root;pdf.Root.MarkInfo=pikepdf.Dictionary(Marked=True);pdf.Root.Lang='en-US'
        pdf.docinfo.Title='Independent multi-child table context'
        with path.open('xb') as output:pdf.save(output,deterministic_id=True,min_version='1.7',fix_metadata_version=False)
    return path


def test_independent_nested_table_context_is_identical_across_hash_seeds_and_preserves_authored_order(tmp_path):
    source=nested_table_source(tmp_path/'nested.pdf');before=source.read_bytes()
    package_root=Path(sidecar.__file__).resolve().parents[1]
    executable,base_environment=_seed_bootstrap(tmp_path)
    script="""
import json,pathlib,sys
from pdf_remediator import sidecar
assert pathlib.Path(sidecar.__file__).resolve().parents[1]==pathlib.Path(sys.argv[2]).resolve()
result=sidecar.collect_decisions(sys.argv[1],inventory_profile=sidecar.TABLE_INVENTORY_PROFILE)
assert not result['inventory_errors']
print(json.dumps([row for row in result['decisions'] if row['kind']=='table-structure'],sort_keys=True,ensure_ascii=False))
"""
    inventories=[]
    try:
        for seed in ('1','2','17','12345'):
            env=base_environment.copy();env['PYTHONHASHSEED']=seed
            completed=subprocess.run([str(executable),'-B','-X','utf8','-c',script,str(source),str(package_root)],
                cwd=tmp_path,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=60,check=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            inventories.append(json.loads(completed.stdout))
    finally:_assert_seed_bootstrap_unchanged(tmp_path)
    assert all(inventory==inventories[0] for inventory in inventories[1:])
    assert len(inventories[0])==1
    row=inventories[0][0]
    assert [cell['context_text'] for cell in row['table_context']['cells']]==[
        'headerNine headerTwo headerSeven','dataEight dataOne dataFour']
    assert [ref['mcid'] for ref in row['references']]==[9,2,7,8,1,4]
    assert source.read_bytes()==before


@pytest.mark.parametrize('change',['tree-order','literal-text'])
def test_independent_real_table_context_change_still_invalidates_rebound_old_approval(tmp_path,change):
    source=nested_table_source(tmp_path/'original-table.pdf');before=source.read_bytes()
    original=sidecar.collect_decisions(source,inventory_profile=sidecar.TABLE_INVENTORY_PROFILE)
    selected=next(row for row in original['decisions'] if row['kind']=='table-structure')
    changed=tmp_path/'changed-table.pdf'
    with pikepdf.open(source) as pdf:
        if change=='tree-order':
            header=pdf.Root.StructTreeRoot.K[0].K[0].K[0].K[0]
            header.K=pikepdf.Array([header.K[1],header.K[0],header.K[2]])
        else:
            content=pdf.pages[0].obj.Contents
            content.write(content.read_bytes().replace(b'(headerNine)',b'(aDifferentWord)'))
        with changed.open('xb') as output:pdf.save(output,deterministic_id=True,min_version='1.7',fix_metadata_version=False)
    fresh=sidecar.collect_decisions(changed,original['source_sha256'],inventory_profile=sidecar.TABLE_INVENTORY_PROFILE)
    current=next(row for row in fresh['decisions'] if row['kind']=='table-structure')
    assert current['context_sha256']!=selected['context_sha256']
    assert current['table_context']['cells'][0]['context_text']!=selected['table_context']['cells'][0]['context_text']
    # Even if a caller updates document hashes and reseals its old acceptance,
    # the stale occurrence context must be compared against the actual PDF.
    supplied=copy.deepcopy(original);supplied['document_sha256']=sha(changed)
    for item in supplied['decisions']:item['binding']['document_sha256']=sha(changed)
    chosen=next(row for row in supplied['decisions'] if row['kind']=='table-structure')
    value=json.loads(chosen['value']);value['summary']='Explicit proposed synthetic summary';chosen['value']=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
    sidecar.bind_approval(chosen,'Independent synthetic-case reviewer','2026-10-28')
    with pytest.raises(sidecar.DecisionError):
        sidecar.apply_decisions(changed,tmp_path/'forbidden.pdf',supplied,original['source_sha256'])
    assert not (tmp_path/'forbidden.pdf').exists() and source.read_bytes()==before

