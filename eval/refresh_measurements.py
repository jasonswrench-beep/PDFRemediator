"""Recompute measurements with metrics1.1 while retaining initial evidence."""
from pathlib import Path
import json,time
from inspect_pdf import inspect_pdf,compare_fidelity,SCHEMA_VERSION
from run_eval import write,summarize,sha

HERE=Path(__file__).resolve().parent
REVISION='preservation-semantics-1.1'

def main():
    root=HERE/'runs/phase0-20261015'
    for report_path in sorted(root.glob('*/*/evaluation.json')):
        report=json.loads(report_path.read_text(encoding='utf-8'))
        if not report.get('complete') or report.get('measurement_revision',{}).get('id')==REVISION:continue
        if not all(name in report for name in ('raw','normalized')):continue
        folder=report_path.parent
        archive=folder/'evaluation.initial-metrics-1.0.json'
        if archive.exists():raise FileExistsError('Unexpected partially refreshed evidence')
        archive.write_bytes(report_path.read_bytes())
        start=time.monotonic()
        report['baseline']=inspect_pdf(report['input'])
        for name in ('raw','normalized'):
            entry=report[name]
            if sha(entry['path'])!=entry['sha256']:raise ValueError('Artifact changed')
            entry['inspection']=inspect_pdf(entry['path'])
            entry['fidelity']=compare_fidelity(report['input'],entry['path'])
        entry=report['normalized']
        result='needs-manual'
        if report['engine_execution']['status']!='completed':result='engine-error'
        elif entry['fidelity']['status']!='pass':result='preservation-blocker'
        elif entry['validator']['status']=='pass':result='ua1-pass-supplemental-review-pending'
        report['result']=result
        report['measurement_revision']={'id':REVISION,'metrics_schema':SCHEMA_VERSION,
          'reason':'Preserve original navigation/annotation meaning while allowing separately recorded valid additions and empty-description enrichment; count only painted fonts in font gate.',
          'pixel_thresholds_changed':False,'prior_evidence':str(archive),'seconds':round(time.monotonic()-start,3)}
        write(report_path,report)
        print('REFRESHED',report['engine'],report['fixture'],entry['fidelity']['status'],flush=True)
    summarize(root)

if __name__=='__main__':main()
