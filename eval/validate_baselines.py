"""Preserve strict UA1 validation for every original evaluation input."""
from pathlib import Path
import json
from run_eval import artifacts,CLI,JAVA_HOME,write
from validate import validate_pdf

HERE=Path(__file__).resolve().parent

def main():
    root=HERE/'evidence/baseline-validation';root.mkdir(exist_ok=True)
    results={}
    for item in artifacts():
        folder=root/item['id']
        summary=next(folder.glob('*.verapdf.summary.json'),None) if folder.exists() else None
        if summary:
            result=json.loads(summary.read_text(encoding='utf-8'))
        else:
            result=validate_pdf(item['path'],folder,CLI,JAVA_HOME)
        results[item['id']]=result
        print('BASELINE',item['id'],result['status'],result.get('counts'),flush=True)
    write(root/'summary.json',results)

if __name__=='__main__':main()
