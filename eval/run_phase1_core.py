"""Reproduce the three predeclared Phase 1 core candidates.

The two synthetic figure descriptions are fixture-author test decisions, never
human accessibility verification. The published book remains pending review.
"""
from __future__ import annotations
import argparse,csv,json,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.pipeline import process_file,sha,write_json,verify_bundle,implementation_digest
from pdf_remediator.sidecar import bind_approval,write_sidecar

def run(destination):
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('Select a fresh evidence directory.')
    destination.mkdir(parents=True)
    config=RuntimeConfig()
    start_digest=implementation_digest(config)
    started=time.monotonic();rows=[]
    def execute(label,source,settings,sidecar=None,bundle_label=None):
        source=ROOT/source;before=sha(source)
        report=process_file(source,destination/'r'/(bundle_label or label),settings,sidecar=sidecar,progress=lambda m:print(label+': '+m,flush=True))
        output=report.get('output')
        row={'case':label,'status':report['status'],'gate1':report['gate1']['status'],'gate2':report['gate2']['status'],
             'fidelity':report['fidelity']['status'],'source_unchanged':before==sha(source),
             'bundle_verified':verify_bundle(report['bundle_path']),'bundle_path':report['bundle_path'],
             'output':output,'manual_pending':len(report['manual_review']['items']),
             'seconds':report['timings']['total_seconds'],'implementation_digest':report['implementation_digest']}
        rows.append(row);write_json(destination/'progress.json',rows)
        print('RESULT '+json.dumps(row),flush=True)
        return report
    execute('reading',Path('eval/corpus/simple-embedded.pdf'),config)
    chapter=execute('chapter-before',Path('eval/corpus/structured-chapter.pdf'),config)
    data=json.loads((Path(chapter['bundle_path'])/'decisions.json').read_text(encoding='utf-8'))
    figures=[item for item in data['decisions'] if item['kind']=='figure-description']
    if len(figures)!=2 or any(item['page']!=3 for item in figures):raise ValueError('Synthetic figure inventory changed; recheck independent fixture intent.')
    descriptions=[
      'An orange circle and a blue square represent the two garden plots compared in this section.',
      'The same orange circle and blue square now represent two archive bins, as the second caption explains.']
    for item,value in zip(figures,descriptions):
        item['value']=value
        bind_approval(item,'Synthetic fixture author (automated test only)','2026-10-15')
    decision_file=destination/'synthetic-author-decisions.json';write_sidecar(data,decision_file)
    write_json(destination/'decision-provenance.json',{'scope':'Original synthetic fixture intent from eval/build_corpus.py and corpus/manifest.json; no real-person review or LMS checker verification.',
       'fixture_manifest_sha256':sha(ROOT/'eval/corpus/manifest.json'),'descriptions':descriptions,
       'book_title_source':'Allen Downey, Think Python, Second Edition; exact published book identity, not an inferred title.'})
    execute('chapter',Path('eval/corpus/structured-chapter.pdf'),config,decision_file,bundle_label='chapter-before')
    book_config=RuntimeConfig(allow_tag_regrouping=True,repair_source_mappings=True,
        title='Think Python: How to Think Like a Computer Scientist, Second Edition')
    execute('book',Path('eval/external/thinkpython2.pdf'),book_config)
    selected=[row for row in rows if row['case']!='chapter-before']
    stable=start_digest==implementation_digest(config)
    passed=stable and len(selected)==3 and all(row['status']=='candidate' and row['source_unchanged'] and row['bundle_verified'] and all(row[k]=='pass' for k in ('gate1','gate2','fidelity')) for row in selected)
    summary={'schema_version':'phase1-core-trial-1','core_exit_pass':passed,'implementation_unchanged':stable,
      'cases':rows,'seconds':round(time.monotonic()-started,3),'verified_count':0,
      'limits':'Candidates await human structure, character, contrast and assistive-technology review plus an actual LMS checker score. No LMS upload performed.'}
    write_json(destination/'summary.json',summary)
    with (destination/'summary.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return 0 if passed else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'output/phase1/core-trial')
    raise SystemExit(run(parser.parse_args().output))
