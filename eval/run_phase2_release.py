"""Release evidence for the four Phase 2 core candidates, without human testing."""
from __future__ import annotations
import argparse,csv,json,os,sys,threading,time
from pathlib import Path
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import process_file,implementation_digest,sha,verify_bundle,write_json
from pdf_remediator.sidecar import bind_approval,write_sidecar
from pdf_remediator.workspace import create_workspace,get_view


def run(destination):
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('Use a fresh release-evidence directory.')
    destination.mkdir(parents=True);initial=implementation_digest(RuntimeConfig());rows=[];started=time.monotonic()
    def execute(label,source,config,prior=None,sidecar=None):
        source=ROOT/source;original_hash=sha(source);cancel=threading.Event();finished=threading.Event()
        resources={'peak_sampled_runner_and_descendant_rss_bytes':0,'sample_seconds':.05,'limit_bytes':config.memory_limit_bytes,'limit_exceeded':False}
        def sample():
            while not finished.is_set():
                try:
                    current=psutil.Process(os.getpid());rss=current.memory_info().rss
                    for child in current.children(recursive=True):
                        try:rss+=child.memory_info().rss
                        except psutil.NoSuchProcess:pass
                    resources['peak_sampled_runner_and_descendant_rss_bytes']=max(rss,resources['peak_sampled_runner_and_descendant_rss_bytes'])
                    if rss>config.memory_limit_bytes:resources['limit_exceeded']=True;cancel.set()
                except psutil.NoSuchProcess:pass
                finished.wait(.05)
        sampler=threading.Thread(target=sample,daemon=True);sampler.start()
        try:
            report=process_file(source,destination/'r'/label,config,sidecar=sidecar,
                decision_bundle=prior['bundle_path'] if prior else None,cancel=cancel,
                progress=lambda message:print(label+': '+message,flush=True))
        finally:finished.set();sampler.join(timeout=1)
        output=report.get('output');row={'case':label,'status':report['status'],
            'gate1':report['gate1']['status'],'gate2':report['gate2']['status'],'fidelity':report['fidelity']['status'],
            'source_unchanged':sha(source)==original_hash,'bundle_verified':verify_bundle(report['bundle_path']),
            'bundle_path':report['bundle_path'],'output':output,'manual_pending':len(report['manual_review']['items']),
            'regrouping_pending':sum(item.get('category')=='tag-regrouping' for item in report['manual_review']['items']),
            'seconds':report['timings']['total_seconds'],'resources':resources,'implementation_digest':report['implementation_digest']}
        rows.append(row);write_json(destination/'progress.json',rows);print('RESULT '+json.dumps(row),flush=True)
        return report
    default=RuntimeConfig()
    execute('reading',Path('eval/corpus/simple-embedded.pdf'),default)
    chapter=execute('chapter-before',Path('eval/corpus/structured-chapter.pdf'),default)
    def author_descriptions(report,expected_pages,values,name):
        data=json.loads((Path(report['bundle_path'])/'decisions.json').read_text(encoding='utf-8'))
        figures=[item for item in data['decisions'] if item['kind']=='figure-description']
        if [item['page'] for item in figures]!=expected_pages:raise ValueError('Independent synthetic figure inventory changed.')
        for item,value in zip(figures,values):
            item['value']=value;bind_approval(item,'Synthetic fixture author (automated release test only)','2026-10-16')
        file=destination/name;write_sidecar(data,file);return file
    chapter_decisions=author_descriptions(chapter,[3,3],[
        'An orange circle and blue square represent the two garden plots described by the first caption.',
        'In the second caption context, the orange circle and blue square represent two archive bins.'],'chapter-author-decisions.json')
    execute('chapter',Path('eval/corpus/structured-chapter.pdf'),default,chapter,chapter_decisions)
    synthetic_config=RuntimeConfig(allow_tag_regrouping=True)
    synthetic=execute('synthetic-before',Path('eval/corpus/synthetic-book-200.pdf'),synthetic_config)
    synthetic_decisions=author_descriptions(synthetic,[40,110],[
        'An orange circle and a blue square illustrate the garden plot comparison discussed on this page.',
        'The orange circle and blue square illustrate archive classification in the context of this second figure.'],'book-author-decisions.json')
    execute('synthetic-book',Path('eval/corpus/synthetic-book-200.pdf'),synthetic_config,synthetic,synthetic_decisions)
    book_config=RuntimeConfig(allow_tag_regrouping=True,repair_source_mappings=True,
        title='Think Python: How to Think Like a Computer Scientist, Second Edition')
    book=execute('published-book',Path('eval/external/thinkpython2.pdf'),book_config)
    state=destination/'review-state'/'book.json';create_workspace(book['bundle_path'],state);view=get_view(state)
    write_json(destination/'grouping.json',{'bundle_path':book['bundle_path'],'manual_total':len(view['manual_items']),
        'regrouping_occurrences':sum(item.get('category')=='tag-regrouping' for item in view['manual_items']),
        'regrouping_patterns':len([group for group in view['groups'] if group['category']=='tag-regrouping']),
        'all_groups':len(view['groups']),'approved':view['counts']['manual_approved'],'verification':view['verification'],
        'every_occurrence_addressable':len({item['id'] for item in view['manual_items']})==len(view['manual_items']),
        'groups':view['groups']})
    finals=[row for row in rows if not row['case'].endswith('-before')]
    stable=initial==implementation_digest(default)
    passed=stable and len(finals)==4 and all(row['status']=='candidate' and row['source_unchanged'] and row['bundle_verified']
        and not row['resources']['limit_exceeded'] and all(row[key]=='pass' for key in ('gate1','gate2','fidelity')) for row in finals)
    summary={'schema_version':'phase2-release-trial-1','complete':True,'core_exit_pass':passed,
        'implementation_unchanged':stable,'cases':rows,'seconds':round(time.monotonic()-started,3),
        'verified_records_created':0,'source_manifest_sha256':sha(ROOT/'eval/corpus/manifest.json'),
        'human_testing':'Deferred to Phase 3. Descriptions are explicitly labeled synthetic-author test decisions; no actual-user, the LMS checker or assistive-technology acceptance test occurred.',
        'resource_scope':'Sampled runner-plus-descendant RSS; does not include independent model services or prove an OS hard allocation limit.'}
    write_json(destination/'summary.json',summary)
    with (destination/'summary.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return 0 if passed else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'output/phase2/core-final')
    raise SystemExit(run(parser.parse_args().output))
