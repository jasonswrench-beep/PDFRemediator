"""Reproducible Phase 0 engine harness; not the Phase 1 product CLI."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import psutil
from inspect_pdf import inspect_pdf, compare_fidelity
from normalize import normalize
from validate import validate_pdf

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
JAVA_HOME = Path(os.environ.get('PHASE0_JAVA_HOME',r'C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot'))
JAVA = JAVA_HOME/'bin/java.exe'
CLI = PROJECT/'tools/verapdf/verapdf.bat'
JAR = PROJECT/'.venvs/odl/Lib/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    temporary.replace(path)

def process(command, directory, timeout=600, memory_limit=4*1024**3):
    directory.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env['JAVA_HOME']=str(JAVA_HOME)
    env['PATH']=str(JAVA_HOME/'bin')+os.pathsep+env['PATH']
    env['PYTHONUTF8']='1'
    started=time.monotonic();peak=0;status='error'
    with (directory/'stdout.txt').open('wb') as out,(directory/'stderr.txt').open('wb') as err:
        child=subprocess.Popen([str(x) for x in command],stdout=out,stderr=err,env=env,shell=False)
        try:
            while child.poll() is None:
                try:
                    tree=[psutil.Process(child.pid)]+psutil.Process(child.pid).children(recursive=True)
                    rss=sum(p.memory_info().rss for p in tree if p.is_running())
                    peak=max(peak,rss)
                except (psutil.NoSuchProcess,psutil.AccessDenied):
                    pass
                if time.monotonic()-started > timeout:
                    status='timeout';break
                if peak > memory_limit:
                    status='memory-limit';break
                time.sleep(.05)
            else:
                status='completed' if child.returncode==0 else 'failed'
        finally:
            if child.poll() is None:
                try:
                    tree=psutil.Process(child.pid).children(recursive=True)
                    for p in reversed(tree):
                        try:p.kill()
                        except psutil.NoSuchProcess:pass
                except psutil.NoSuchProcess:pass
                child.kill();child.wait(timeout=15)
    return {'status':status,'returncode':child.returncode,'seconds':round(time.monotonic()-started,4),
            'peak_observed_process_tree_rss_bytes':peak,'timeout_seconds':timeout,
            'observed_rss_limit_bytes':memory_limit,'command':[str(x) for x in command]}

def artifacts():
    manifest=json.loads((HERE/'corpus/manifest.json').read_text(encoding='utf-8'))
    items=[]
    for f in manifest['fixtures']:
        items.append({'id':f['id'],'path':HERE/'corpus'/f['path'],'sha256':f['sha256'],
                      'title':f['id'].replace('_',' ').title(),'source':'original synthetic fixture'})
    book=HERE/'external/thinkpython2.pdf'
    if book.exists():
        items.append({'id':'thinkpython2_real_book','path':book,'sha256':sha(book),'title':'Think Python 2nd edition',
                      'source':'Allen B. Downey, Green Tea Press; CC BY-NC 3.0; publisher download; unchanged original'})
    return items

def evaluate(item,engine,runroot,resume=False):
    destination=runroot/engine/item['id'];report_path=destination/'evaluation.json'
    fingerprint=sha(HERE/'ACCEPTANCE.md')
    implementation={name:sha(HERE/name) for name in ('run_eval.py','normalize.py','engine_accesspdf.py','inspect_pdf.py','validate.py')}
    if resume and report_path.exists():
        saved=json.loads(report_path.read_text(encoding='utf-8'))
        if saved.get('input_sha256')==sha(item['path']) and saved.get('criteria_sha256')==fingerprint and saved.get('implementation_sha256')==implementation and saved.get('complete'):
            print('REUSED',engine,item['id'],flush=True);return saved
        raise RuntimeError('Resume evidence mismatch; use a new run directory')
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f'Use resume or a new run directory: {destination}')
    destination.mkdir(parents=True,exist_ok=True)
    rawdir=destination/'raw';rawdir.mkdir()
    report={'schema_version':'phase0-evaluation-1.0','engine':engine,'fixture':item['id'],
            'input':str(item['path']),'input_sha256':sha(item['path']),'source':item['source'],
            'criteria_sha256':fingerprint,'no_ai':True,'document_cloud_calls':0,'complete':False,
            'implementation_sha256':implementation,
            'not_assessed':['semantic reading order','description meaning','contrast','full WCAG coverage','human LMS checker review']}
    if report['input_sha256']!=item['sha256']:
        raise ValueError('Input changed after manifest')
    report['baseline']=inspect_pdf(item['path'])
    print('START',engine,item['id'],report['baseline'].get('page_count'),'pages',flush=True)
    if engine=='opendataloader':
        command=[JAVA,'-Xmx2048m','-Djava.awt.headless=true','-jar',JAR,
                 '--format','tagged-pdf','--output-dir',rawdir,item['path']]
        raw=rawdir/(item['path'].stem+'_tagged.pdf')
    else:
        raw=rawdir/(item['path'].stem+'_tagged.pdf')
        command=[PROJECT/'.venvs/accesspdf/Scripts/python.exe',HERE/'engine_accesspdf.py',
                 item['path'],raw,rawdir/'processors.json']
    report['engine_execution']=process(command,destination/'engine')
    if not raw.exists():
        report['result']='engine-error';report['complete']=True
        write(report_path,report);print('ERROR no output',engine,item['id'],flush=True);return report
    normalized=destination/'normalized'/raw.name
    report['normalization']=normalize(raw,normalized,item['title'])
    for name,artifact in [('raw',raw),('normalized',normalized)]:
        start=time.monotonic()
        entry={'path':str(artifact),'sha256':sha(artifact),'inspection':inspect_pdf(artifact)}
        entry['validator']=validate_pdf(artifact,destination/('validation-'+name),CLI,JAVA_HOME,180,'xml')
        entry['fidelity']=compare_fidelity(item['path'],artifact,dpi=96,max_changed_fraction=0.0,pixel_delta=0)
        entry['measurement_seconds']=round(time.monotonic()-start,4)
        report[name]=entry
        # Save evidence even if a later measurement is interrupted.
        write(report_path,report)
    normalized_result=report['normalized']
    report['result']='needs-manual'
    if report['engine_execution']['status']!='completed':report['result']='engine-error'
    elif normalized_result['fidelity']['status']!='pass':report['result']='preservation-blocker'
    elif normalized_result['validator']['status']=='pass':report['result']='ua1-pass-supplemental-review-pending'
    report['original_unchanged']=sha(item['path'])==report['input_sha256']
    report['complete']=True;write(report_path,report)
    print('DONE',engine,item['id'],'ua1',normalized_result['validator']['status'],
          'fidelity',normalized_result['fidelity']['status'],'seconds',report['engine_execution']['seconds'],flush=True)
    return report

def summarize(runroot):
    reports=[json.loads(p.read_text(encoding='utf-8')) for p in runroot.glob('*/*/evaluation.json')]
    rows=[]
    for report in reports:
        row={'engine':report['engine'],'fixture':report['fixture'],'pages':report.get('baseline',{}).get('page_count'),
             'engine_status':report.get('engine_execution',{}).get('status'),'seconds':report.get('engine_execution',{}).get('seconds'),
             'peak_rss_mb':round(report.get('engine_execution',{}).get('peak_observed_process_tree_rss_bytes',0)/1024**2,1),'result':report.get('result','incomplete')}
        for name in ('raw','normalized'):
            e=report.get(name,{})
            row[name+'_ua1']=e.get('validator',{}).get('status','not-run')
            row[name+'_failed_rules']=e.get('validator',{}).get('counts',{}).get('failedRules')
            row[name+'_fidelity']=e.get('fidelity',{}).get('status','not-run')
        rows.append(row)
    write(runroot/'summary.json',rows)
    if rows:
        with (runroot/'summary.csv').open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',default='phase0-20261015');p.add_argument('--engines',default='opendataloader,accesspdf')
    p.add_argument('--fixtures',default='');p.add_argument('--resume',action='store_true')
    args=p.parse_args();runroot=HERE/'runs'/args.run
    selected=set(args.fixtures.split(',')) if args.fixtures else None
    items=artifacts()
    if selected and selected-{item['id'] for item in items}:
        p.error('Unknown fixture IDs: '+','.join(sorted(selected-{item['id'] for item in items})))
    errors=0
    for engine in args.engines.split(','):
        if engine not in ('opendataloader','accesspdf'):raise ValueError(engine)
        for item in items:
            if selected and item['id'] not in selected:continue
            try:evaluate(item,engine,runroot,args.resume)
            except Exception as e:
                errors+=1
                write(runroot/engine/item['id']/'harness-error.json',{'type':type(e).__name__,'error':str(e)})
                print('HARNESS ERROR',engine,item['id'],type(e).__name__,str(e),flush=True)
            summarize(runroot)
    print('SUMMARY',runroot/'summary.csv',flush=True)
    return 1 if errors else 0

if __name__=='__main__':raise SystemExit(main())
