"""Merge corrected measurements without rerunning engines or validation."""
from pathlib import Path
import hashlib,json
from inspect_pdf import inspect_pdf,SCHEMA_VERSION
from run_eval import artifacts,write,summarize

HERE=Path(__file__).resolve().parent

def main():
    root=HERE/'runs/phase0-20261015'
    baseline_validations={};checks=[]
    for item in artifacts():
        inspection=inspect_pdf(item['path'])
        write(HERE/'evidence/baseline-inspection'/(item['id']+'.json'),inspection)
        v=next((HERE/'evidence/baseline-validation'/item['id']).glob('*.verapdf.summary.json'))
        baseline_validations[item['id']]=json.loads(v.read_text(encoding='utf-8'))
        checks.append({'fixture':item['id'],'input_unchanged':hashlib.sha256(item['path'].read_bytes()).hexdigest()==item['sha256']})
    write(HERE/'evidence/baseline-validation/summary.json',baseline_validations)
    for path in sorted(root.glob('*/*/evaluation.json')):
        report=json.loads(path.read_text(encoding='utf-8'))
        if not report.get('complete'):raise ValueError('Incomplete evaluation')
        archive=path.parent/'evaluation.before-final-reconciliation.json'
        if not archive.exists():archive.write_bytes(path.read_bytes())
        report['baseline']=inspect_pdf(report['input'])
        for name in ('raw','normalized'):
            entry=report[name]
            entry['inspection']=inspect_pdf(entry['path'])
            entry['validator']=json.loads(Path(entry['validator']['summary_path']).read_text(encoding='utf-8'))
        entry=report['normalized']
        result='needs-manual'
        if report['engine_execution']['status']!='completed':result='engine-error'
        elif entry['fidelity']['status']!='pass':result='preservation-blocker'
        elif entry['validator']['status']=='pass':result='ua1-pass-supplemental-review-pending'
        report['result']=result
        report['final_reconciliation']={'inspection_schema':SCHEMA_VERSION,
          'changes':['Distinguish partial dangling references from entirely phantom trees.',
                     'Retain aggregate failed assertion counts when veraPDF caps detailed failure records.'],
          'prior_evidence':str(archive),'engine_and_validator_rerun':False,'pixel_thresholds_changed':False}
        write(path,report)
        print('RECONCILED',report['engine'],report['fixture'],flush=True)
    write(HERE/'evidence/input-integrity.json',checks)
    summarize(root)
    sources=[]
    for path in sorted(HERE.glob('*.py')):
        sources.append({'path':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    write(HERE/'evidence/source-manifest.json',{'sources':sources,
      'note':'Final reproducible implementation. Initial runs preceded recorded inspector/parser corrections; prior reports and reconciliation provenance are retained. No original implementation fingerprint is invented for those runs.'})

if __name__=='__main__':main()
