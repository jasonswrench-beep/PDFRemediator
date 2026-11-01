"""Isolated adapter using accesspdf's published deterministic pipeline API."""
import dataclasses
import json
from pathlib import Path
import sys
from accesspdf.pipeline import run_pipeline

if __name__ == '__main__':
    result = run_pipeline(Path(sys.argv[1]),Path(sys.argv[2]))
    if hasattr(result,'model_dump'):
        report = result.model_dump(mode='json')
    elif dataclasses.is_dataclass(result):
        report = dataclasses.asdict(result)
    else:
        report = {'result':str(result)}
    Path(sys.argv[3]).write_text(json.dumps(report,indent=2,default=str)+'\n',encoding='utf-8')
    failures = [p for p in getattr(result,'processor_results',[]) if not getattr(p,'success',False)]
    print(json.dumps({'processor_failures':len(failures),'output_exists':Path(sys.argv[2]).is_file()}))
    raise SystemExit(1 if failures else 0)
