"""Local command line workflow; every candidate awaits human verification."""
from __future__ import annotations
import argparse,copy,json,signal,sys,tempfile,threading,webbrowser
from datetime import datetime,timezone
from pathlib import Path
from . import __version__
from .config import load_config

class Cancellation:
    def __init__(self,path=None):self.event=threading.Event();self.path=Path(path) if path else None
    def is_set(self):return self.event.is_set() or bool(self.path and self.path.exists())

def emit(value):print(json.dumps(value,indent=2,ensure_ascii=False,default=str))

def _parser():
    parser=argparse.ArgumentParser(prog='remediator',description='Local PDF accessibility candidates with explicit validation and human review.')
    parser.add_argument('--version',action='version',version=__version__)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('doctor','engines'):
        child=commands.add_parser(name);child.add_argument('--config');child.add_argument('--json',action='store_true')
    child=commands.add_parser('serve',help='Open the private local review application.')
    child.add_argument('--config');child.add_argument('--data-dir',type=Path);child.add_argument('--port',type=int,default=0)
    child.add_argument('--no-open',action='store_true');child.add_argument('--import-bundle',type=Path);child.add_argument('--session-file',type=Path)
    child=commands.add_parser('launch',help='Start or reopen the local review application with a hidden helper.')
    child.add_argument('--data-dir',type=Path)
    child=commands.add_parser('assist',help='Save unapproved drafts from an explicitly selected local model.')
    child.add_argument('bundle',type=Path);child.add_argument('--endpoint',required=True);child.add_argument('--model',required=True)
    child.add_argument('--id',action='append',dest='ids');child.add_argument('-o','--output',type=Path,required=True)
    child.add_argument('--cache',type=Path);child.add_argument('--include-images',action='store_true');child.add_argument('--timeout',type=float,default=60)
    child.add_argument('--reasoning-effort',choices=('none','low','medium','high'))
    for name in ('check','fix'):
        child=commands.add_parser(name);child.add_argument('source',type=Path);child.add_argument('-o','--output',type=Path,required=name=='fix')
        child.add_argument('--config');child.add_argument('--resume',action='store_true');child.add_argument('-r','--recurse',action='store_true')
        child.add_argument('--dry-run',action='store_true');child.add_argument('--json',action='store_true')
        child.add_argument('--title');child.add_argument('--lang',dest='language');child.add_argument('--sidecar',type=Path)
        child.add_argument('--ocr',choices=('off','skip','textless','redo'),help='Use textless to add text only on wholly scanned pages, leaving pages with existing text unchanged.');child.add_argument('--cancel-file',type=Path)
        child.add_argument('--ocr-profile',choices=('standard','table-lines','angles','turns'),help='Choose ordinary scans, visible table grid lines, tilted and vertical text, or pages stored sideways or upside down; originals stay unchanged.')
        child.add_argument('--document-kind',choices=('unknown','reading','slides','equations'),help='Declare known input content; slide decks and equations require source/manual remediation.')
        child.add_argument('--allow-tag-regrouping',action='store_true',default=None,help='Allow the bounded list/link regrouping repair; each change remains a required human review item.')
        child.add_argument('--repair-source-mappings',action='store_true',default=None,help='Repair only the supported missing Type1 character mappings using the original font and pinned authority.')
        child.add_argument('--repair-ocr-mappings',action='store_true',default=None,help='Derive the missing Unicode map of embedded two-byte fonts from an OCR reading of each page (pages stay identical). Every derived map needs human review; this is an inference, not an authority.')
        child.add_argument('--remove-cidset',action='store_true',default=None,help='Remove the optional CIDSet character lists from embedded fonts. Some PDF programs write these lists wrongly, which fails the strict PDF/UA check. Removing them changes no page and no text; readers rebuild what they need from the font itself.')
        child.add_argument('--no-ai',action='store_true',help='All Phase 1 processing is deterministic; this flag documents that intent.')
        child.add_argument('--local-only',action='store_true',help='All Phase 1 document processing is local.')
    child=commands.add_parser('review');child.add_argument('path',type=Path);child.add_argument('--no-open',action='store_true')
    child=commands.add_parser('decisions');sub=child.add_subparsers(dest='action',required=True)
    approve=sub.add_parser('approve');approve.add_argument('sidecar',type=Path);approve.add_argument('--id',action='append',dest='ids',required=True)
    approve.add_argument('--reviewer',required=True);approve.add_argument('--reviewed-at');approve.add_argument('-o','--output',type=Path)
    child=commands.add_parser('ledger');sub=child.add_subparsers(dest='action',required=True)
    for name in ('add','list','export','invalidate'):
        cmd=sub.add_parser(name);cmd.add_argument('--ledger',type=Path,required=True)
        if name=='add':
            cmd.add_argument('bundle',type=Path);cmd.add_argument('--reviewer',required=True);cmd.add_argument('--reviewed-at')
            cmd.add_argument('--ally-score',required=True,type=float);cmd.add_argument('--ally-context',required=True)
            cmd.add_argument('--threshold',type=float,default=67);cmd.add_argument('--review-scope',required=True)
            cmd.add_argument('--review-file',type=Path,required=True);cmd.add_argument('--notes',default='')
        elif name=='export':cmd.add_argument('-o','--output',type=Path,required=True)
        elif name=='invalidate':
            cmd.add_argument('record_id');cmd.add_argument('--reason',required=True);cmd.add_argument('--reviewer',required=True);cmd.add_argument('--reviewed-at')
    return parser

def _review_data(report,file):
    payload=json.loads(file.read_text(encoding='utf-8'))
    expected=(report.get('output') or {}).get('sha256')
    if not expected or payload.get('artifact_sha256')!=expected:raise ValueError('Human review file is not bound to this exact output PDF.')
    original={item['id']:item for item in report.get('manual_review',{}).get('items',[])}
    items=payload.get('items',[])
    if len(items)!=len(original) or {item.get('id') for item in items}!=set(original):raise ValueError('Human review file has a missing or unknown review item.')
    for item in items:
        prior=original[item['id']]
        for key,value in prior.items():
            if key not in ('status','reviewer','reviewed_at','notes') and item.get(key)!=value:raise ValueError('Human review item scope was changed.')
    result=copy.deepcopy(report);result['manual_review']=payload
    return result

def main(argv=None):
    parser=_parser();args=parser.parse_args(argv)
    try:
        if args.command=='serve':
            from .web import serve
            config=load_config(args.config)
            if not 0<=args.port<=65535:raise ValueError('Choose a valid local port.')
            root=args.data_dir or config.project_root/'output/review-app'
            serve(root,config,args.port,not args.no_open,args.import_bundle,args.session_file);return 0
        if args.command=='launch':
            from .launcher import launch
            print(launch(args.data_dir));return 0
        if args.command=='assist':
            from .assistance import suggest
            from .sidecar import write_sidecar
            result=suggest(args.bundle,args.endpoint,args.model,decision_ids=args.ids,cache_dir=args.cache,
                timeout_seconds=args.timeout,include_images=args.include_images,reasoning_effort=args.reasoning_effort)
            write_sidecar(result,args.output)
            emit({'status':result['status'],'draft_file':str(args.output),'data_sent':result['data_sent'],'error':result.get('error'),
                'scope':'Unapproved suggestions only; no PDF or human approval was changed.'})
            return 0 if result['status']=='draft' else 1
        if args.command in ('doctor','engines'):
            from .doctor import inventory
            config=load_config(args.config);result=inventory(settings=config)
            if args.command=='engines':result={'engine':'opendataloader','version':'2.5.13','status':'provisional','providers':[],'runtime':result}
            emit(result);return 0 if result.get('runtime',result).get('status')=='ready' else 1
        if args.command in ('check','fix'):
            from .pipeline import batch,discover
            from .inspection import inspect_pdf
            config=load_config(args.config,title=args.title,language=args.language,ocr_mode=args.ocr,ocr_profile=args.ocr_profile,
                allow_tag_regrouping=args.allow_tag_regrouping,repair_source_mappings=args.repair_source_mappings,repair_ocr_mappings=args.repair_ocr_mappings,remove_cidset=args.remove_cidset,document_kind=args.document_kind)
            if args.sidecar and args.command=='check':raise ValueError('check is read-only; use fix to apply approved decisions.')
            if args.dry_run:
                files=discover(args.source,args.output,args.recurse)
                emit({'mode':'dry-run','documents':[{'path':str(p),'inspection':inspect_pdf(p)} for p in files],
                      'provider_calls':0,'pdfs_modified':0,'resources_downloaded':0,'settings':config.public()});return 0
            token=Cancellation(args.cancel_file)
            previous=signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT,lambda signum,frame:token.event.set())
            def run(destination,temporary=False):
                results,summary=batch(args.source,destination,config,recurse=args.recurse,resume=args.resume,sidecar=args.sidecar,
                    mode=args.command,cancel=token,progress=None if args.json else lambda text:print(text,flush=True))
                if temporary:
                    summary['report_retention']='Temporary assessment only; supply -o to retain the review and evidence bundle.'
                    for entry in summary['results']:entry['bundle_path']=None
                if args.json:emit(summary)
                else:
                    for report in results:print(report['input']['path']+': '+report['status']+'; '+('temporary assessment; use -o to retain evidence' if temporary else report.get('bundle_path','see batch summary')))
                    if not results:print('No PDF files found.',file=sys.stderr)
                return 130 if token.is_set() else 1 if not results or any(r['status']=='failed' for r in results) else 2 if any(r['status']=='needs-manual' for r in results) else 0
            try:
                if args.output:return run(args.output)
                temporary_root=config.project_root/'output/.check-temp';temporary_root.mkdir(parents=True,exist_ok=True)
                with tempfile.TemporaryDirectory(dir=temporary_root,prefix='read-only-') as temporary:
                    return run(Path(temporary),temporary=True)
            finally:signal.signal(signal.SIGINT,previous)
        if args.command=='review':
            path=args.path.resolve()
            packets=[path] if path.is_file() and path.suffix=='.html' else [path/'review.html'] if (path/'review.html').is_file() else sorted(path.glob('*/review.html'))
            if not packets:raise FileNotFoundError('No review packet was found.')
            for packet in packets:
                print(packet)
                if not args.no_open:webbrowser.open(packet.as_uri())
            return 0
        if args.command=='decisions':
            from .sidecar import load_sidecar,write_sidecar,bind_approval
            data=load_sidecar(args.sidecar);byid={item['id']:item for item in data['decisions']}
            if set(args.ids)-set(byid):raise ValueError('Unknown decision ID.')
            date=args.reviewed_at or datetime.now(timezone.utc).isoformat()
            for ident in args.ids:bind_approval(byid[ident],args.reviewer,date)
            output=args.output or args.sidecar;write_sidecar(data,output);print(output);return 0
        if args.command=='ledger':
            from . import ledger
            if args.action=='list':emit(ledger.list_records(args.ledger));return 0
            if args.action=='export':print(ledger.export_ledger(args.ledger,args.output));return 0
            date=args.reviewed_at or datetime.now(timezone.utc).isoformat()
            if args.action=='invalidate':emit(ledger.invalidate_record(args.ledger,args.record_id,args.reason,args.reviewer,date));return 0
            from .pipeline import verify_bundle
            if not verify_bundle(args.bundle):raise ValueError('The candidate bundle is incomplete or changed.')
            report=json.loads((args.bundle/'report.json').read_text(encoding='utf-8'))
            reviewed=_review_data(report,args.review_file)
            result=ledger.add_record(args.ledger,report['output']['path'],reviewed,args.reviewer,date,args.ally_score,args.ally_context,
                threshold=args.threshold,review_scope=args.review_scope,notes=args.notes)
            emit(result);return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
