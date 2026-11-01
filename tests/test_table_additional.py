"""Independent cross-page, repeated-group and typed-composition table cases."""
import json
from pathlib import Path
import hashlib
import os
import shutil
import site
import subprocess
import sys

import pikepdf
import pytest

from pdf_remediator import inspection, sidecar
from pdf_remediator.sidecar import bind_approval, file_sha256, write_sidecar
from test_table_pipeline import (REVIEWER, accept, assert_preserved, choose, data,
    execute, expected_table, files, selected_value, table_snapshot, table_source,
    value, registered_language_fonts, tagged_control, fast_validator)


def _seed_bootstrap(tmp_path):
    """Exercise effective hash seeds, including on an isolated ._pth runtime.

    Only an owned bootstrap copy omits ._pth; the supplied interpreter and all
    package files remain untouched. No installation or environment change occurs.
    """
    tmp_path=Path(tmp_path);tmp_path.mkdir(parents=True,exist_ok=True)
    root=Path(sys.executable).resolve().parent;executable=Path(sys.executable).resolve()
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    original={str(executable):sha(executable)};copied={}
    if os.name=='nt' and list(root.glob('*._pth')):
        bootstrap=tmp_path/'hash-seed-runtime';bootstrap.mkdir()
        members=[p for p in root.iterdir() if p.is_file() and (p.name in {'python.exe','pythonw.exe'}
            or p.suffix.lower() in {'.dll','.pyd'} or p.name.startswith('python') and p.suffix.lower()=='.zip')]
        assert len(members)<=256 and sum(p.stat().st_size for p in members)<=256*1024**2
        assert any(p.name=='python.exe' for p in members) and any(p.name.startswith('python') and p.suffix=='.zip' for p in members)
        for member in members:
            destination=bootstrap/member.name;shutil.copyfile(member,destination)
            original[str(member)]=sha(member);copied[str(destination)]=sha(destination)
            assert original[str(member)]==copied[str(destination)]
        executable=bootstrap/'python.exe';home=bootstrap
        assert not list(bootstrap.glob('*._pth'))
    else: home=Path(sys.base_prefix).resolve()
    profile=tmp_path/'profile';profile.mkdir();temporary=tmp_path/'tmp';temporary.mkdir()
    package_root=Path(sidecar.__file__).resolve().parents[1]
    dependencies=[Path(p).resolve() for p in site.getsitepackages() if Path(p).is_dir()]
    env={'PATH':os.defpath,'PYTHONHOME':str(home),'PYTHONPATH':os.pathsep.join(map(str,[package_root,home,*dependencies])),
        'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1','HOME':str(profile),'USERPROFILE':str(profile),
        'TEMP':str(temporary),'TMP':str(temporary)}
    if os.name=='nt':
        windows=Path(os.environ.get('SystemRoot',r'C:\Windows')).resolve()
        env.update(SystemRoot=str(windows),WINDIR=str(windows),COMSPEC=str(windows/'System32/cmd.exe'),PATH=str(windows/'System32'))
    script=('import json,os,sys;print(json.dumps({"seed":os.environ["PYTHONHASHSEED"],'
        '"ignore":sys.flags.ignore_environment,"isolated":sys.flags.isolated,'
        '"randomized":sys.flags.hash_randomization,"hash":hash("PDFRemediator-table-order-probe")}))')
    probes=[]
    for seed in ('1','321','1'):
        process=subprocess.run([str(executable),'-B','-X','utf8','-c',script],env={**env,'PYTHONHASHSEED':seed},
            cwd=tmp_path,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30,check=True,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        probe=json.loads(process.stdout);assert probe['seed']==seed and probe['ignore']==probe['isolated']==0 and probe['randomized']==1
        probes.append(probe)
    assert probes[0]['hash']==probes[2]['hash'] and probes[0]['hash']!=probes[1]['hash'], 'The requested hash seed must actually affect this interpreter'
    receipt={'original':original,'copied':copied,'probes':probes,'interpreter':str(executable),'_pth_modified':False}
    (tmp_path/'hash-seed-bootstrap.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    _assert_seed_bootstrap_unchanged(tmp_path)
    return executable,env


def _assert_seed_bootstrap_unchanged(tmp_path):
    receipt=json.loads((Path(tmp_path)/'hash-seed-bootstrap.json').read_text(encoding='utf-8'))
    for path,expected in {**receipt['original'],**receipt['copied']}.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected


def test_table_reference_context_retains_interleaved_authored_k_order_across_effective_seeds(tmp_path):
    from test_table_edits import table_pdf
    source=table_pdf(tmp_path/'base.pdf');nested=tmp_path/'interleaved.pdf'
    with pikepdf.open(source) as pdf:
        root=pdf.Root.StructTreeRoot;document=root.K;table=document.K[0];cell=table.K[0].K[0];page=pdf.pages[0]
        first_created=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Span,P=cell,Pg=page.obj,K=6))
        later_created=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Span,P=cell,Pg=page.obj,K=8))
        cell.K=pikepdf.Array([later_created,5,first_created,7,0])
        root.ParentTree.Nums[1].extend([cell,first_created,cell,later_created])
        extra=b'\n'.join(f'/Span <</MCID {mcid}>> BDC BT /F1 12 Tf 20 {220-mcid*12} Td ({text}) Tj ET EMC'.encode()
            for mcid,text in [(5,'directMiddle'),(6,'laterSpan'),(7,'directLast'),(8,'firstSpan')])
        page.Contents=pdf.make_stream(page.Contents.read_bytes()+b'\n'+extra)
        pdf.save(nested,deterministic_id=True)
    before=nested.read_bytes();runtime,env=_seed_bootstrap(tmp_path/'seeds')
    script='''
import json,pathlib,sys
from pdf_remediator import sidecar
assert pathlib.Path(sidecar.__file__).resolve().parents[1]==pathlib.Path(sys.argv[2]).resolve()
profiles={}
for profile in (sidecar.TABLE_INVENTORY_PROFILE,sidecar.EMPTY_TAG_INVENTORY_PROFILE):
    value=sidecar.collect_decisions(sys.argv[1],inventory_profile=profile)
    assert not value['inventory_errors']
    profiles[profile]=[row for row in value['decisions'] if row['kind']=='table-structure']
print(json.dumps(profiles,sort_keys=True,ensure_ascii=False))
'''
    results=[]
    for seed in ('1','321','1'):
        process=subprocess.run([str(runtime),'-B','-X','utf8','-c',script,str(nested),str(Path(sidecar.__file__).resolve().parents[1])],
            env={**env,'PYTHONHASHSEED':seed},cwd=tmp_path,stdin=subprocess.DEVNULL,capture_output=True,text=True,
            timeout=60,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        results.append(json.loads(process.stdout))
    assert results[0]==results[1]==results[2]
    for rows in results[0].values():
        assert len(rows)==1
        assert [ref['mcid'] for ref in rows[0]['references']]==[8,5,6,7,0,1,2,3]
        assert rows[0]['table_context']['cells'][0]['context_text']=='firstSpan directMiddle laterSpan directLast Cell 0'
    _assert_seed_bootstrap_unchanged(tmp_path/'seeds');assert nested.read_bytes()==before


def altered_source(tmp_path, alteration):
    source=table_source(tmp_path/'builder'); changed=tmp_path/(alteration+'.pdf')
    with pikepdf.open(source) as pdf:
        tree=pdf.Root.StructTreeRoot; first,second=pdf.pages
        section=tree.K.K[0]; table=section.K[1]; head,body=table.K
        if alteration=='multipage':
            cells=list(body.K[1].K); moved=[]; kept=[]; current=None
            for instruction in pikepdf.parse_content_stream(first):
                if str(instruction.operator)=='BDC' and len(instruction.operands)==2:
                    mcid=instruction.operands[1].get('/MCID')
                    if mcid in {10,11,12,13}: current=[]; instruction.operands[1].MCID=int(mcid)-7
                    elif mcid==14: instruction.operands[1].MCID=10
                if current is not None:
                    if str(instruction.operator)=='Tm': instruction=pikepdf.ContentStreamInstruction([*instruction.operands[:5],120],instruction.operator)
                    current.append(instruction)
                    if str(instruction.operator)=='EMC': moved.extend(current); current=None
                else: kept.append(instruction)
            assert current is None and moved
            first.Contents=pdf.make_stream(pikepdf.unparse_content_stream(kept))
            second.Contents=pdf.make_stream(pikepdf.unparse_content_stream([*pikepdf.parse_content_stream(second),*moved]))
            for index,cell in enumerate(cells,3): cell.Pg=second.obj; cell.K=index
            body.K[1].Pg=second.obj; section.K[2].K=10
            old=list(tree.ParentTree.Nums[1]); tree.ParentTree.Nums[1]=pikepdf.Array([*old[:10],old[14]])
            tree.ParentTree.Nums[3]=pikepdf.Array([*list(tree.ParentTree.Nums[3]),*cells])
        elif alteration=='same-kind-rowgroups':
            last=body.K[1]; body.K=pikepdf.Array([body.K[0]])
            another=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.TBody,
                P=table,Pg=first.obj,K=pikepdf.Array([last])))
            last.P=another; table.K=pikepdf.Array([head,body,another])
        elif alteration=='typed-conflict':
            cell=head.K[0].K[0]; leaf=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                S=pikepdf.Name.H2,P=cell,Pg=first.obj,K=cell.K))
            cell.K=leaf; tree.ParentTree.Nums[1][1]=leaf
        elif alteration=='disjoint-tree':
            section2=tree.K.K[1]; heading,paragraph,link=section2.K
            div=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Div,
                P=section2,Pg=second.obj,K=pikepdf.Array([heading,paragraph])))
            heading.P=div; paragraph.P=div; section2.K=pikepdf.Array([div,link])
        else: raise ValueError('Unknown table fixture alteration')
        with changed.open('xb') as stream: pdf.save(stream,deterministic_id=True)
    return changed


def test_table_whose_existing_cells_span_two_pages_keeps_real_owners_and_exact_metadata(tmp_path,fast_validator):
    source=altered_source(tmp_path,'multipage'); original=file_sha256(source)
    initial=inspection.inspect_pdf(source)
    assert not initial.get('error')
    assert next(item for item in initial['checks'] if item['id']=='content-linkage')['status']=='pass'
    prepared=execute(source,tmp_path/'prepared'); decisions=data(prepared); row=choose(decisions)
    assert row['page'] is None and row['table_context']['table']['pages']==[1,2]
    assert [cell['pages'] for cell in row['table_context']['cells']]==[[1]]*9+[[2]]*4
    before=table_snapshot(prepared['decision_source']['path']); protected=files(Path(prepared['bundle_path']))
    accept(decisions); plan=write_sidecar(decisions,tmp_path/'accepted.json')
    result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result); expected=expected_table(before)
    for index,name in enumerate(['h-category','h-participation','h-total','h-online','h-in-person','h-a',None,None,None,'h-b']):
        if name: expected['idtree'][bytes(pikepdf.String(name)).hex()]=before['cells'][index]['mcid']
    assert table_snapshot(result['output']['path'])==expected
    assert result['inspection']['table_relationships']['status']=='pass'
    assert result['inspection']['table_relationships']['tables'][0]['pages']==[1,2]
    assert file_sha256(source)==original and files(Path(prepared['bundle_path']))==protected


def test_distinct_tbody_groups_keep_distinct_span_boundaries_and_valid_complete_plans(tmp_path,fast_validator):
    source=altered_source(tmp_path,'same-kind-rowgroups'); prepared=execute(source,tmp_path/'prepared'); decisions=data(prepared)
    row=choose(decisions); groups=row['table_context']['rows']
    assert groups[2]['group']==groups[3]['group']=='TBody' and groups[2]['group_key']!=groups[3]['group_key']
    malformed=json.loads(selected_value(decisions)); malformed['cells'][5]['row_span']=2
    bad=dict(row,value=value(malformed))
    with pytest.raises(sidecar.DecisionError,match='row group'): sidecar._validate_value(bad)
    before=table_snapshot(prepared['decision_source']['path']); accept(decisions)
    plan=write_sidecar(decisions,tmp_path/'accepted.json'); result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result); assert table_snapshot(result['output']['path'])==expected_table(before)
    assert result['inspection']['table_relationships']['status']=='pass'


@pytest.mark.parametrize('kind',['table-header','heading-tag','semantic-role'])
def test_accepted_legacy_or_semantic_role_changes_inside_table_plan_refuse_before_publish(tmp_path,fast_validator,kind):
    source=altered_source(tmp_path,'typed-conflict'); prepared=execute(source,tmp_path/'prepared'); decisions=data(prepared)
    row=choose(decisions); accept(decisions); first=row['table_context']['cells'][0]['element']
    if kind=='table-header':
        other=next(item for item in decisions['decisions'] if item['kind']==kind and item['element']==first)
        other['value']=value({'role':'TH','scope':'Both'})
    else:
        other=next(item for item in decisions['decisions'] if item['kind']==kind and item.get('structure_path')==row['structure_path']+'/K/0/K/0/K/0/K')
        if kind=='semantic-role':
            assert other['structural_eligible'] is False and other['structural_limitations']
            assert any('protected non-text semantic relationship' in item for item in other['structural_limitations'])
            other['value']='P'; saved=value(other)
            protected=files(Path(prepared['bundle_path'])); original=file_sha256(source)
            with pytest.raises(sidecar.DecisionError): bind_approval(other,REVIEWER,'2026-10-27')
            assert value(other)==saved and other['status']=='pending'
            assert file_sha256(source)==original and files(Path(prepared['bundle_path']))==protected
            assert not (tmp_path/'refused').exists()
            return
        assert other['structural_eligible'],other.get('structural_limitations')
        other['value']='H3' if kind=='heading-tag' else 'P'
    bind_approval(other,REVIEWER,'2026-10-27'); protected=files(Path(prepared['bundle_path'])); original=file_sha256(source)
    plan=write_sidecar(decisions,tmp_path/'conflict.json'); result=execute(source,tmp_path/'refused',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert result['status']=='failed' and result['output'] is None
    assert file_sha256(source)==original and files(Path(prepared['bundle_path']))==protected


def test_disjoint_accepted_reading_order_and_table_metadata_compose_without_paint_change(tmp_path,fast_validator):
    source=altered_source(tmp_path,'disjoint-tree'); prepared=execute(source,tmp_path/'prepared'); decisions=data(prepared)
    before=table_snapshot(prepared['decision_source']['path']); accept(decisions)
    row=next(item for item in decisions['decisions'] if item['kind']=='reading-order' and item.get('structure_path')=='root/K/K/1/K/0')
    assert row['structural_eligible'],row.get('structural_limitations')
    row['value']=value({'children':list(reversed(json.loads(row['current'])['children']))}); bind_approval(row,REVIEWER,'2026-10-27')
    plan=write_sidecar(decisions,tmp_path/'accepted.json'); result=execute(source,tmp_path/'edited',sidecar=plan,decision_bundle=prepared['bundle_path'])
    assert_preserved(source,result); assert table_snapshot(result['output']['path'])==expected_table(before)
    with pikepdf.open(result['output']['path']) as pdf:
        assert [str(node.S) for node in pdf.Root.StructTreeRoot.K.K[1].K[0].K]==['/P','/H1']
    assert result['inspection']['table_relationships']['status']=='pass'
