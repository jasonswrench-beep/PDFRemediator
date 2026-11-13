"""Private loopback review application with explicit, revision-bound actions.

This is a single-user desktop companion. No directory is served as a static
filesystem, no external origin is trusted, and PDF pages are rendered locally.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import queue
import re
import secrets
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser

from .config import RuntimeConfig, load_config
from .doctor import ocr_availability
from .pipeline import process_file, sha, verify_bundle, write_json
from .preview import PREVIEW_PROFILE, context_matches as preview_context_matches

ASSETS=Path(__file__).parent/'web_assets'


def _lifecycle(message):
    try:print(datetime.now(timezone.utc).isoformat()+' '+message,flush=True)
    except (OSError,ValueError):pass


def _require_ocr_runtime(config):
    if config.ocr_mode != 'off' or config.repair_ocr_mappings:
        availability = ocr_availability(config)
        if not availability['available']:
            raise ValueError(availability['message'])


def _credential_options(record):
    lineage = record.get('credential_lineage')
    return ({'credential_lineage':lineage['path'],
             'expected_credential_lineage_sha256':lineage['sha256']} if lineage else {})


def download_filename(view):
    """Keep the source stem and a candidacy label without unsafe header bytes."""
    name = re.split(r"[\\/]", str(view.get('source', {}).get('path', 'document.pdf')))[-1]
    stem = name[:-4] if name.lower().endswith('.pdf') else name
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', stem).strip('.-')[:100] or 'document'
    suffix = '-candidate.pdf' if view.get('status') == 'candidate' else '-review-draft.pdf'
    return stem + suffix


MAX_UPLOAD=100*1024**2
MAX_JSON=256*1024


def _process_child(source,destination,config,sidecar,decision_bundle,expected_source_sha256,expected_sidecar_sha256,automatic_authorization,channel,cancel,processing_options=None):
    try:
        report=process_file(source,destination,config,sidecar=sidecar,decision_bundle=decision_bundle,expected_source_sha256=expected_source_sha256,expected_sidecar_sha256=expected_sidecar_sha256,automatic_authorization=automatic_authorization,cancel=cancel,
            progress=lambda message:channel.put(('progress',message)),**(processing_options or {}))
        channel.put(('result',report['bundle_path']))
    except Exception as exc:channel.put(('error',str(exc)[:1200]))


def process_isolated(source,destination,config,cancel,progress,sidecar=None,decision_bundle=None,expected_source_sha256=None,expected_sidecar_sha256=None,automatic_authorization=None,
                     ocr_correction_plan=None,expected_ocr_correction_sha256=None,ocr_correction_bundle=None,source_lineage=None,expected_lineage_sha256=None,
                     credential_lineage=None,expected_credential_lineage_sha256=None):
    """Keep native PDF work separate from the responsive review server."""
    if cancel.is_set():raise InterruptedError('Processing was cancelled before the document worker started.')
    import psutil
    context=multiprocessing.get_context('spawn');channel=context.Queue();stop=context.Event()
    options={key:value for key,value in {'ocr_correction_plan':ocr_correction_plan,'expected_ocr_correction_sha256':expected_ocr_correction_sha256,
        'ocr_correction_bundle':ocr_correction_bundle,'source_lineage':source_lineage,'expected_lineage_sha256':expected_lineage_sha256,
        'credential_lineage':credential_lineage,'expected_credential_lineage_sha256':expected_credential_lineage_sha256}.items() if value is not None}
    child=context.Process(target=_process_child,args=(str(source),str(destination),config,sidecar,decision_bundle,expected_source_sha256,expected_sidecar_sha256,automatic_authorization,channel,stop,options),daemon=False)
    child.start();started=time.monotonic();cancel_started=None;result=None;error=None
    try:
        while child.is_alive() or result is None:
            if cancel.is_set():
                stop.set();cancel_started=cancel_started or time.monotonic()
                if time.monotonic()-cancel_started>20:raise InterruptedError('Processing was cancelled; unfinished staging files were not published.')
            if time.monotonic()-started>config.timeout_seconds*3:raise TimeoutError('The complete document exceeded its processing time budget.')
            try:
                process=psutil.Process(child.pid);rss=process.memory_info().rss
                for descendant in process.children(recursive=True):
                    try:rss+=descendant.memory_info().rss
                    except psutil.NoSuchProcess:pass
                if rss>config.memory_limit_bytes:raise MemoryError('The document exceeded the sampled whole-worker memory budget.')
            except psutil.NoSuchProcess:pass
            try:kind,value=channel.get(timeout=.15)
            except queue.Empty:
                if not child.is_alive():break
                continue
            if kind=='progress':progress(value)
            elif kind=='result':result=value;break
            else:error=value;break
        child.join(timeout=2)
        if error:raise RuntimeError(error)
        if not result:raise RuntimeError('The document worker ended without a completed report.')
        return json.loads((Path(result)/'report.json').read_text(encoding='utf-8'))
    finally:
        if child.is_alive():
            try:
                parent=psutil.Process(child.pid)
                for descendant in reversed(parent.children(recursive=True)):
                    try:descendant.kill()
                    except psutil.NoSuchProcess:pass
                child.terminate();child.join(timeout=5)
            except psutil.NoSuchProcess:pass
        channel.close()


class Application:
    def __init__(self,data_dir,config=None):
        self.root=Path(data_dir).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.config=config or RuntimeConfig();self.token=secrets.token_urlsafe(32)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='pdf-review')
        self.lock=threading.RLock();self.pdf_lock=threading.RLock();self.jobs={}
        for name in ('inputs','workspaces','runs','exports','page-cache','ai-cache'):(self.root/name).mkdir(exist_ok=True)

    def state_path(self,identifier):
        if not re.fullmatch(r'[a-f0-9]{24}',identifier):raise ValueError('Unknown review workspace.')
        path=self.root/'workspaces'/identifier/'state.json'
        if not path.is_file():raise FileNotFoundError('Review workspace was not found.')
        return path

    def import_bundle(self,bundle):
        with self.pdf_lock:return self._import_bundle(bundle)

    def _import_bundle(self,bundle):
        from .workspace import create_workspace
        path=Path(bundle).resolve()
        allowed=(self.config.project_root.resolve(),self.root)
        if not any(path==base or base in path.parents for base in allowed):raise ValueError('Choose a result inside this project or the review data directory.')
        if not verify_bundle(path):raise ValueError('The result is incomplete or changed; it cannot authorize review.')
        for existing in (self.root/'workspaces').glob('*/state.json'):
            try:
                value=json.loads(existing.read_text(encoding='utf-8'))
                if Path(value.get('bundle',{}).get('path','')).resolve()==path:return existing.parent.name
            except (OSError,ValueError,TypeError):continue
        identifier=uuid.uuid4().hex[:24]
        state=self.root/'workspaces'/identifier/'state.json'
        create_workspace(path,state)
        return identifier

    def view(self,identifier):
        from .workspace import get_view
        with self.pdf_lock:return get_view(self.state_path(identifier))

    def dashboard(self):
        from .workspace import get_saved_summary
        rows=[]
        for path in sorted((self.root/'workspaces').glob('*/state.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                value=get_saved_summary(self.state_path(path.parent.name))
                rows.append({'id':path.parent.name,'title':Path(value['source']['path']).name,'status':value['status'],
                    'cancelled':value['cancelled'],
                    'stale':value['stale'],'counts':value['counts'],'page_count':value['page_count'],
                    'artifacts_checked':False})
            except (OSError,ValueError,RuntimeError,KeyError) as exc:
                rows.append({'id':path.parent.name,'title':'Review needs attention','status':'needs-manual',
                    'cancelled':False,
                    'error':str(exc)[:300],'artifacts_checked':False})
        with self.lock:jobs=[self.public_job(job) for job in self.jobs.values()]
        return {'documents':rows,'jobs':jobs,'capabilities':{'ocr':ocr_availability(self.config)},
            'privacy':'Local processing. AI is off until you explicitly request a selected local model.',
            'phase':'Phase 2 pilot build; actual-user and LMS checker testing are Phase 3.'}

    def catalog(self):
        from .workspace import _report_cancelled
        found=[]
        for root in (self.config.project_root/'output',self.root/'runs'):
            if not root.exists():continue
            for path in root.rglob('manifest.json'):
                relative=path.relative_to(root)
                if len(relative.parts)>9 or any(part.startswith('.') for part in relative.parts):continue
                try:
                    report=json.loads((path.parent/'report.json').read_text(encoding='utf-8'))
                    found.append({'path':str(path.parent),'name':Path(report['input']['path']).name,'status':report['status'],
                        'cancelled':_report_cancelled(report)})
                except (OSError,ValueError,KeyError):continue
                if len(found)>=400:break
        return {'bundles':list({item['path']:item for item in found}.values())}

    def upload(self,stream,length,name):
        if not 0<length<=MAX_UPLOAD:raise ValueError('Choose a PDF smaller than 100 MB.')
        if not isinstance(name,str) or '/' in name or '\\' in name or '\x00' in name or Path(name).suffix.lower()!='.pdf':raise ValueError('A plain PDF filename is required.')
        identifier=uuid.uuid4().hex[:24];folder=self.root/'inputs'/identifier;folder.mkdir()
        stem=(re.sub(r'[^A-Za-z0-9_-]+','-',Path(name).stem).strip('-') or 'document')[:32]
        path=folder/(stem+'.pdf');digest=hashlib.sha256();remaining=length;first=b''
        try:
            with path.open('xb') as output:
                while remaining:
                    block=stream.read(min(1024**2,remaining))
                    if not block:raise ValueError('The upload was interrupted.')
                    if not first:first=block[:1024]
                    output.write(block);digest.update(block);remaining-=len(block)
            if b'%PDF-' not in first:raise ValueError('The selected file does not have a PDF header.')
            write_json(folder/'input.json',{'id':identifier,'name':name,'path':str(path),'sha256':digest.hexdigest()})
            return {'id':identifier,'name':name,'bytes':length}
        except Exception:
            path.unlink(missing_ok=True);raise

    def input_path(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{24}',identifier):raise ValueError('Unknown selected PDF.')
        record=json.loads((self.root/'inputs'/identifier/'input.json').read_text(encoding='utf-8'))
        path=Path(record['path']).resolve()
        if self.root/'inputs' not in path.parents or sha(path)!=record['sha256']:raise ValueError('The selected PDF changed.')
        return path

    def public_job(self,job):return {k:v for k,v in job.items() if k not in ('cancel','future')}

    def submit(self,label,function):
        identifier=uuid.uuid4().hex[:24]
        job={'id':identifier,'label':label,'status':'queued','progress':[],'cancel':threading.Event(),'result':None,'error':None}
        with self.lock:self.jobs[identifier]=job
        def progress(message):
            with self.lock:
                job['progress'].append(str(message)[:800]);job['progress']=job['progress'][-60:]
        def work():
            with self.lock:
                if job['cancel'].is_set():
                    job['status']='cancelled'
                    return
                job['status']='running'
            try:
                result=function(job['cancel'],progress,identifier)
                with self.lock:job['result']=result;job['status']='cancelled' if job['cancel'].is_set() else 'done'
            except Exception as exc:
                with self.lock:
                    cancelled=job['cancel'].is_set()
                    job['status']='cancelled' if cancelled else 'failed'
                    # A run that Cancel cut short can leave a result that cannot be opened ("stale evidence"); that is the cancel, not a failure to report.
                    # A deliberate cancel message (InterruptedError) is kept because it says what happened to the files.
                    job['error']=None if cancelled and not isinstance(exc,InterruptedError) else str(exc)[:1200]
        job['future']=self.executor.submit(work)
        return {'job_id':identifier}

    def process(self,payload):
        selected=payload.get('inputs')
        if not isinstance(selected,list) or not 1<=len(selected)<=30:raise ValueError('Select between one and 30 PDFs.')
        paths=[(self.input_path(item),None) for item in selected]
        paths=[(path,sha(path),_credential_options(json.loads((path.parent/'input.json').read_text(encoding='utf-8')))) for path,_ in paths]
        options=payload.get('options',{})
        allowed={'title','language','ocr_mode','ocr_profile','document_kind','allow_tag_regrouping','repair_source_mappings','remove_cidset','repair_ocr_mappings'}
        if not isinstance(options,dict) or set(options)-allowed:raise ValueError('Unknown processing option.')
        config=load_config(**{**self.config.public(),**options})
        # load_config's public path representation is converted here for direct overrides.
        for field in ('project_root','java_home','odl_jar','validator_cli','ocr_python','tesseract_dir'):setattr(config,field,Path(getattr(config,field)))
        _require_ocr_runtime(config)
        def work(cancel,progress,job):
            results=[]
            for source,expected,lineage in paths:
                if cancel.is_set():break
                report=process_isolated(source,self.root/'runs'/job[:12],config,cancel,progress,expected_source_sha256=expected,**lineage)
                ident=self.import_bundle(report['bundle_path']);results.append({'workspace_id':ident,'status':report['status']})
            return {'documents':results}
        return self.submit('Process '+str(len(paths))+' selected PDF(s)',work)

    def credential_copy(self,identifier,payload):
        """Create a new explicitly authorized source, never alter its old review."""
        from .credentials import create_derivative
        from .workspace import credential_copy_consent, RevisionConflict
        state=self.state_path(identifier)
        with self.pdf_lock:
            consent=credential_copy_consent(state,payload)
            request={**payload,'reviewed_at':consent['reviewed_at']}
            view=self.view(identifier)
            if view['revision']!=request['revision'] or view['stale']:
                raise RevisionConflict('The original review changed before creating the separate copy.')
        report=json.loads((Path(view['bundle_path'])/'report.json').read_text(encoding='utf-8'))
        options={key:report['settings'][key] for key in ('title','language','document_kind','allow_tag_regrouping',
            'repair_source_mappings','preserve_painting','bookmark_min_pages','engine') if key in report['settings']}
        # This consent authorizes credential removal only. Recognition and local
        # AI are separate actions; no earlier review authority is inherited.
        config=load_config(**{**self.config.public(),**options,'ocr_mode':'off','ocr_profile':'standard'})
        for field in ('project_root','java_home','odl_jar','validator_cli','ocr_python','tesseract_dir'):
            setattr(config,field,Path(getattr(config,field)))
        def current_consent():
            with self.pdf_lock:
                if credential_copy_consent(state,request)!=consent:
                    raise RevisionConflict('The content-credentials consent changed; reload the original review.')
        def work(cancel,progress,job):
            current_consent()
            if cancel.is_set():raise InterruptedError('Separate-copy creation was cancelled before it started.')
            selected=uuid.uuid4().hex[:24];folder=self.root/'inputs'/selected;folder.mkdir(exist_ok=False)
            output=folder/'credential-free.pdf'
            progress('Creating a separate working copy without Content Credentials. The original remains unchanged.')
            derivative=create_derivative(view['source']['path'],output,folder/'credential-evidence',consent=consent,cancel=cancel)
            if Path(derivative['source_path']).resolve()!=output.resolve() or sha(output)!=derivative['source_sha256']:
                raise ValueError('The separate working copy does not match its proof.')
            current_consent()
            if cancel.is_set():raise InterruptedError('Separate-copy processing was cancelled; retained evidence was not discarded.')
            lineage={'path':derivative['lineage_path'],'sha256':derivative['lineage_sha256']}
            write_json(folder/'input.json',{'id':selected,'name':'credential-free.pdf','path':str(output),
                'sha256':derivative['source_sha256'],'credential_lineage':lineage})
            updated=process_isolated(output,self.root/'runs'/job[:12],config,cancel,progress,
                expected_source_sha256=derivative['source_sha256'],**_credential_options({'credential_lineage':lineage}))
            current_consent()
            if cancel.is_set():raise InterruptedError('Separate-copy processing was cancelled before opening its new review.')
            with self.pdf_lock:
                current_consent()
                result_id=self.import_bundle(updated['bundle_path'])
            if result_id==identifier:raise ValueError('A separate working copy must have a new review identity.')
            return {'documents':[{'workspace_id':result_id,'status':updated['status']}],
                'credential_copy':{'original_workspace_id':identifier,'input_id':selected,'credentials_removed':True,
                    'original_credential_verified':False,'inherited_review_approvals':False}}
        return self.submit('Create a separate copy without Content Credentials and recheck',work)

    def retry(self,identifier,payload):
        from .workspace import RevisionConflict
        view=self.view(identifier)
        if type(payload.get('revision')) is not int or payload['revision']!=view['revision']:
            raise RevisionConflict('Workspace revision changed; reload before retrying.')
        if view['stale']:raise ValueError('The original or review evidence changed or is unavailable; choose the PDF again to start a separate review.')
        if view['historical_status']!='failed':raise ValueError('Retry processing is available only for failed or cancelled attempts.')
        report=json.loads((Path(view['bundle_path'])/'report.json').read_text(encoding='utf-8'))
        if report.get('mode')!='fix':raise ValueError('A read-only check cannot be retried as PDF modification; choose the original explicitly to start processing.')
        # Retain document choices, but use the running service's corrected native paths/budgets.
        options={key:report['settings'][key] for key in ('title','language','ocr_mode','document_kind','allow_tag_regrouping','repair_source_mappings','preserve_painting','bookmark_min_pages','engine')}
        options['ocr_profile']=report['settings'].get('ocr_profile','standard')
        options['remove_cidset']=report['settings'].get('remove_cidset',False)
        options['repair_ocr_mappings']=report['settings'].get('repair_ocr_mappings',False)
        config=load_config(**{**self.config.public(),**options})
        for field in ('project_root','java_home','odl_jar','validator_cli','ocr_python','tesseract_dir'):setattr(config,field,Path(getattr(config,field)))
        _require_ocr_runtime(config)
        def work(cancel,progress,job):
            current=self.view(identifier)
            if current['revision']!=view['revision'] or current['stale']:
                raise RevisionConflict('The review changed while retry was queued; reload before retrying.')
            updated=process_isolated(view['source']['path'],self.root/'runs'/job[:12],config,cancel,progress,
                expected_source_sha256=view['source']['sha256'],
                **_credential_options(report),
                **({'source_lineage':report['source_lineage']['path'],'expected_lineage_sha256':report['source_lineage']['sha256']}
                   if report.get('source_lineage') else {}))
            return {'documents':[{'workspace_id':self.import_bundle(updated['bundle_path']),'status':updated['status']}]}
        return self.submit('Retry processing original PDF',work)

    def apply(self,identifier,payload):
        from .workspace import export_workspace, record_prior_ocr_review, RevisionConflict
        state=self.state_path(identifier);view=self.view(identifier)
        if view['counts']['manual_blocked']:raise ValueError('A reported problem is still blocked. Resolve it before applying edits.')
        if view.get('ocr_editor',{}).get('changed_count'):
            raise ValueError('OCR corrections use Create corrected copy and recheck. Apply document edits and OCR corrections in separate passes; revert one draft group first. Saved corrections remain in this review.')
        if not any(item['id'] in view['unapplied_decisions'] and item.get('status')=='approved' for item in view['decisions']):
            raise ValueError('Accept at least one changed value before applying edits.')
        report=json.loads((Path(view['bundle_path'])/'report.json').read_text(encoding='utf-8'))
        config=load_config(**report['settings'])
        for field in ('project_root','java_home','odl_jar','validator_cli','ocr_python','tesseract_dir'):setattr(config,field,Path(getattr(config,field)))
        _require_ocr_runtime(config)
        with self.pdf_lock:exported=export_workspace(state,self.root/'exports'/uuid.uuid4().hex[:12],payload['revision'])
        def work(cancel,progress,job):
            with self.pdf_lock:
                current=self.view(identifier)
                if current['stale'] or current['revision']!=view['revision']:
                    raise RevisionConflict('The review changed while waiting; reload before applying accepted edits.')
            updated=process_isolated(view['source']['path'],self.root/'runs'/job[:12],config,cancel,progress,
                sidecar=exported['sidecar_path'],decision_bundle=view['bundle_path'],expected_source_sha256=view['source']['sha256'],
                expected_sidecar_sha256=exported['files']['decisions.json'],**_credential_options(report))
            with self.pdf_lock:
                latest=self.view(identifier)
                if latest['stale'] or latest['revision']!=view['revision']:
                    raise RevisionConflict('The source review changed during processing. Its latest edits and reported problems remain; open the completed result separately with Find existing results.')
                result_id=self.import_bundle(updated['bundle_path'])
                if updated.get('source_lineage'):
                    record_prior_ocr_review(state,self.state_path(result_id),view['revision'],
                                            self.view(result_id)['revision'],identifier)
            return {'documents':[{'workspace_id':result_id,'status':updated['status']}]}
        return self.submit('Apply accepted edits and recheck the PDF',work)

    def ocr_apply(self,identifier,payload):
        """Create a separately bound corrected source; never overwrite its review."""
        from .workspace import export_ocr_corrections, record_prior_ocr_review, RevisionConflict
        view=self.view(identifier);revision=payload.get('revision')
        if view.get('credential_lineage'):
            raise ValueError('OCR text-editor chaining is not supported for a Content Credentials working copy; its original and removal proof remain intact.')
        if type(revision) is not int or revision!=view['revision']:
            raise RevisionConflict('Workspace revision changed; reload before creating the corrected copy.')
        if view['stale'] or not view.get('output'):
            raise ValueError('Open an unchanged completed result before correcting its OCR text.')
        report=json.loads((Path(view['bundle_path'])/'report.json').read_text(encoding='utf-8'))
        # Bind the exact selected preparation first. The derivative pipeline
        # disables recognition only after proving that reviewed context.
        config=load_config(**report['settings'])
        for field in ('project_root','java_home','odl_jar','validator_cli','ocr_python','tesseract_dir'):
            setattr(config,field,Path(getattr(config,field)))
        with self.pdf_lock:
            exported=export_ocr_corrections(self.state_path(identifier),self.root/'exports'/uuid.uuid4().hex[:12],revision)
        plan=exported.get('ocr_corrections_path');plan_hash=exported['files'].get('ocr-corrections.json')
        if not plan or not plan_hash:
            raise ValueError('No accepted OCR corrections were exported.')
        def work(cancel,progress,job):
            with self.pdf_lock:
                current=self.view(identifier)
                if current['stale'] or current['revision']!=revision:
                    raise RevisionConflict('The review changed while waiting; reload before creating the corrected copy.')
                if sha(plan)!=plan_hash:
                    raise RevisionConflict('Exported OCR corrections changed before processing; export the current review again.')
            updated=process_isolated(view['source']['path'],self.root/'runs'/job[:12],config,cancel,progress,
                expected_source_sha256=view['source']['sha256'],ocr_correction_plan=plan,
                expected_ocr_correction_sha256=plan_hash,ocr_correction_bundle=view['bundle_path'],**_credential_options(report))
            with self.pdf_lock:
                latest=self.view(identifier)
                if latest['stale'] or latest['revision']!=revision:
                    raise RevisionConflict('The source review changed during OCR correction. Its latest edits and problems remain; open the completed copy separately with Find existing results.')
                result_id=self.import_bundle(updated['bundle_path'])
                if updated.get('source_lineage'):
                    destination=self.state_path(result_id)
                    record_prior_ocr_review(self.state_path(identifier),destination,revision,
                                            self.view(result_id)['revision'],identifier)
            return {'documents':[{'workspace_id':result_id,'status':updated['status']}]}
        return self.submit('Create an OCR-corrected copy and recheck the PDF',work)

    def assist(self,identifier,payload):
        from .workspace import merge_ai_drafts
        from .assistance import suggest
        view=self.view(identifier);state=self.state_path(identifier)
        if view['stale']:raise ValueError('This review is stale. Reprocess before requesting AI assistance.')
        if payload.get('consent') is not True:raise ValueError('Explicitly select sending the chosen context to the local model.')
        revision=payload['revision']
        if type(revision) is not int or revision!=view['revision']:raise ValueError('The review changed. Refresh before requesting suggestions.')
        def work(cancel,progress,job):
            if self.view(identifier)['revision']!=revision:raise ValueError('The review revision changed while waiting; no context was sent.')
            progress('Requesting drafts from the explicitly selected local model.')
            result=suggest(view['bundle_path'],payload['endpoint'],payload['model'],decision_ids=payload.get('decision_ids'),
                cache_dir=self.root/'ai-cache',cancel=cancel,include_images=payload.get('include_images',False),reasoning_effort=payload.get('reasoning_effort'))
            if result.get('status')!='draft':raise RuntimeError(result.get('error','The local model did not return valid drafts.'))
            with self.pdf_lock:merge_ai_drafts(state,result,revision)
            return {'workspace_id':identifier,'assistance':result}
        return self.submit('Draft suggestions with local AI',work)

    def auto_fix(self,identifier,payload):
        """Document-level best-guess authority, never a human review approval."""
        from . import workspace
        from .sidecar import make_automatic_authorization
        view=self.view(identifier);state=self.state_path(identifier);revision=payload.get('revision')
        if payload.get('consent') is not True:raise ValueError('Choose Auto-fix explicitly to authorize automatic choices.')
        if view['stale']:raise ValueError('This review is stale. Reprocess before using automatic mode.')
        if type(revision) is not int or revision!=view['revision']:raise ValueError('The review changed. Refresh before using automatic mode.')
        if view['counts']['manual_blocked']:raise ValueError('A reported problem is still blocked. Resolve it before automatic processing.')
        use_ai=payload.get('use_ai',False)
        if type(use_ai) is not bool:raise ValueError('Choose whether to include local AI.')
        if use_ai and (payload.get('ai_consent') is not True or not isinstance(payload.get('model'),str) or not payload['model'].strip()):
            raise ValueError('Select an installed local model and explicitly authorize automatic local AI choices.')
        old_report=json.loads((Path(view['bundle_path'])/'report.json').read_text(encoding='utf-8'))
        def configuration(settings):
            config=load_config(**settings)
            for field in ('project_root','java_home','odl_jar','validator_cli','ocr_python','tesseract_dir'):setattr(config,field,Path(getattr(config,field)))
            _require_ocr_runtime(config)
            return config
        configuration(old_report['settings'])
        def work(cancel,progress,job):
            current=self.view(identifier)
            if current['revision']!=revision or current['stale']:raise ValueError('The review changed while waiting; no automatic choices or model requests were made.')
            working=identifier;working_state=state;config=configuration(old_report['settings']);preparation=None;warnings=[]
            if not current.get('output'):
                if any(item.get('human_touched') for item in current['decisions']):
                    raise ValueError('This preparation cannot be reused safely with your saved decisions. Reprocess and retain your edits for the new context.')
                progress('Trying the supported layout repairs from the unchanged original.')
                config.allow_tag_regrouping=True
                preparation=process_isolated(current['source']['path'],self.root/'runs'/job[:12]/'prepare',config,cancel,progress,
                    expected_source_sha256=current['source']['sha256'],**_credential_options(old_report))
                initiating=self.view(identifier)
                if initiating['stale'] or initiating['revision']!=revision:
                    raise ValueError('The initiating review changed during preparation; no model context was sent or automatic choices applied.')
                working=self.import_bundle(preparation['bundle_path']);working_state=self.state_path(working);current=self.view(working)
                if not current.get('output') or not current.get('prepared'):
                    return {'documents':[{'workspace_id':working,'status':current['status']}],
                        'auto_fix':{'status':'needs-attention','automatically_handled':0,'warnings':['No safe preparation was available; recorded blockers remain.']}}
            if cancel.is_set():raise InterruptedError('Automatic processing was cancelled before any guesses were applied.')
            eligible=[item['id'] for item in current['decisions'] if item['kind'] in ('title','figure-description')
                and item.get('status')=='pending' and not item.get('human_touched')]
            generated_suggestions=[];generated_decisions=set()
            if use_ai:
                from .assistance import suggest,AssistanceError
                if len(eligible)>24:
                    warnings.append('Local AI was limited to the first 24 eligible decisions. Other descriptions remain visible.')
                eligible=eligible[:24]
                for offset in range(0,len(eligible),8):
                    if cancel.is_set():raise InterruptedError('Automatic processing was cancelled before applying guesses.')
                    initiating=self.view(identifier)
                    expected_revision=current['revision'] if working==identifier else revision
                    if initiating['stale'] or initiating['revision']!=expected_revision:raise ValueError('The initiating review changed; no further model context was sent.')
                    fresh=self.view(working)
                    if fresh['stale'] or fresh['revision']!=current['revision']:raise ValueError('The review changed before the model request. Refresh and try again.')
                    progress('Generating local best guesses for selected title and figure contexts.')
                    try:
                        result=suggest(current['bundle_path'],payload['endpoint'],payload['model'],decision_ids=eligible[offset:offset+8],
                            cache_dir=self.root/'ai-cache',cancel=cancel,include_images=payload.get('include_images',False),reasoning_effort=payload.get('reasoning_effort'))
                    except InterruptedError:raise
                    except (AssistanceError,OSError,TimeoutError) as exc:
                        warnings.append('Local AI could not complete: '+str(exc)[:300]);break
                    if result.get('status')=='cancelled':raise InterruptedError('Automatic local AI was cancelled.')
                    if result.get('status')!='draft':
                        warnings.append('Local AI could not complete: '+str(result.get('error','No valid suggestions were returned.'))[:300]);break
                    with self.pdf_lock:current=workspace.merge_ai_drafts(working_state,result,current['revision'])
                    for item in result['suggestions']:
                        staged=next((draft for draft in current['suggestions'] if draft.get('status')=='draft'
                            and all(draft.get(key)==value for key,value in item.items())),None)
                        if staged is None:raise ValueError('A returned model choice could not be matched to its staged context.')
                        generated_suggestions.append(staged['suggestion_id'])
                    generated_decisions.update(item['id'] for item in result['suggestions'])
            # Only this explicit action creates machine authority. Model text cannot
            # grant itself permission or claim a person's accessibility review.
            authorization=make_automatic_authorization(current['source']['sha256'],current['prepared']['sha256'],
                datetime.now(timezone.utc).isoformat(),decision_ids=sorted(generated_decisions|{
                    item['id'] for item in current['decisions'] if item.get('status')=='auto-accepted' and not item.get('human_touched')}))
            initiating=self.view(identifier)
            expected_revision=current['revision'] if working==identifier else revision
            if initiating['stale'] or initiating['revision']!=expected_revision:raise ValueError('The initiating review changed before automatic application.')
            with self.pdf_lock:
                current=workspace.apply_automatic_suggestions(working_state,authorization,current['revision'],suggestion_ids=generated_suggestions)
                exported=workspace.export_workspace(working_state,self.root/'exports'/uuid.uuid4().hex[:12],current['revision'])
            progress('Applying authorized automatic choices and rerunning every release check.')
            updated=process_isolated(current['source']['path'],self.root/'runs'/job[:12]/'automatic',config,cancel,progress,
                sidecar=exported['sidecar_path'],decision_bundle=current['bundle_path'],expected_source_sha256=current['source']['sha256'],
                expected_sidecar_sha256=exported['files']['decisions.json'],automatic_authorization=authorization,
                **_credential_options(current))
            latest=self.view(working)
            if latest['stale'] or latest['revision']!=current['revision']:
                raise ValueError('The source review changed during automatic processing. Its latest edits and reported problems remain; open the completed result separately before continuing.')
            if working!=identifier:
                initiating=self.view(identifier)
                if initiating['stale'] or initiating['revision']!=revision:raise ValueError('The initiating review changed during automatic processing; its latest edits remain in place.')
            result_id=self.import_bundle(updated['bundle_path']);result_state=self.state_path(result_id)
            with self.pdf_lock:
                result_view=self.view(result_id)
                result_view=workspace.preserve_manual_preferences(state,result_state,result_view['revision'])
                if result_view.get('output') and not result_view['unapplied_decisions']:
                    plan=workspace.plan_automatic_review(result_state)
                    result_view=workspace.commit_automatic_review(result_state,plan,plan['revision'])
                elif result_view['unapplied_decisions']:
                    warnings.append('Your saved pending edits were retained. They still need your acceptance before they change the PDF.')
            summary={'status':'complete' if result_view['status']=='candidate' else 'needs-attention',
                'automatically_handled':result_view['counts'].get('automated_count',0),
                'remaining_checks':result_view['counts'].get('manual_pending_actionable',result_view['counts']['manual_pending']),
                'automatic_decisions_applied':result_view['counts'].get('decision_auto_accepted',0),
                'human_approvals_granted':0,'warnings':warnings,'authorization_id':authorization['authorization_id'],
                'newly_changed_decisions':[item for processor in updated.get('processors',[]) for item in processor.get('changed',[])],
                'source_workspace':identifier,'result_workspace':result_id,'verification':'not-verified'}
            write_json(self.root/'runs'/job[:12]/'automatic-summary.json',summary)
            return {'documents':[{'workspace_id':result_id,'status':result_view['status']}],'auto_fix':summary}
        return self.submit('Auto-fix document and recheck the result',work)

    def render_page(self,identifier,kind,number):
        view=self.view(identifier)
        if view['stale']:raise ValueError('This review is stale. Reprocess the original before previewing or approving it.')
        if kind not in ('original','candidate'):raise ValueError('Unknown page preview.')
        reference=view['source'] if kind=='original' else view.get('output')
        if not reference:raise ValueError('This run has no releasable result PDF.')
        path=Path(reference['path'])
        if not 1<=number<=view['page_count']:raise ValueError('Page is outside the document.')
        cache=self.root/'page-cache'/(PREVIEW_PROFILE+'-'+reference['sha256']+'-'+str(number)+'.png')
        context=cache.with_suffix('.json')
        with self.pdf_lock:
            valid=False
            if cache.is_file() and context.is_file():
                try:
                    saved=json.loads(context.read_text(encoding='utf-8'));signature=saved.pop('signature','')
                    expected_signature=hmac.new(self.token.encode(),json.dumps(saved,sort_keys=True,ensure_ascii=False).encode(),hashlib.sha256).hexdigest()
                    valid=(hmac.compare_digest(signature,expected_signature)
                        and preview_context_matches(saved,reference['sha256'],number,sha(cache)))
                except (OSError,ValueError,TypeError):pass
            if not valid:
                from .process import run
                directory=self.root/'page-cache'/('log-'+uuid.uuid4().hex[:12])
                result=run([sys.executable,'-m','pdf_remediator.preview',path,'--sha256',reference['sha256'],'--page',str(number),
                    '--png',cache,'--context',context],directory,30,min(self.config.memory_limit_bytes,1024**3))
                if result['status']!='completed':
                    cache.unlink(missing_ok=True);context.unlink(missing_ok=True)
                    raise RuntimeError('This page could not be previewed within the local rendering budget.')
                saved=json.loads(context.read_text(encoding='utf-8'))
                if not preview_context_matches(saved,reference['sha256'],number,sha(cache)):
                    cache.unlink(missing_ok=True);context.unlink(missing_ok=True)
                    raise RuntimeError('This page preview lacks the current complete rendering evidence.')
                saved['signature']=hmac.new(self.token.encode(),json.dumps(saved,sort_keys=True,ensure_ascii=False).encode(),hashlib.sha256).hexdigest()
                write_json(context,saved)
            if sha(path)!=reference['sha256']:raise ValueError('The preview document changed.')
        return cache.read_bytes()

    def page_context(self,identifier,number):
        self.render_page(identifier,'original',number)
        view=self.view(identifier)
        path=self.root/'page-cache'/(PREVIEW_PROFILE+'-'+view['source']['sha256']+'-'+str(number)+'.json')
        return json.loads(path.read_text(encoding='utf-8'))

    def credential_record(self,identifier,kind):
        from .credentials import validate_lineage_bindings
        if kind not in ('credential-original','credential-record'):
            raise ValueError('Unknown content-credentials record.')
        view=self.view(identifier);binding=view.get('credential_lineage')
        if view['stale'] or not binding:raise ValueError('No current content-credentials evidence is available.')
        proof=validate_lineage_bindings(binding['path'],view['source']['path'],binding['sha256'])
        if proof.get('binding_verified') is not True:raise ValueError('Content-credentials evidence could not be verified.')
        path=Path(binding['path']) if kind=='credential-record' else Path(binding['path']).parent/'original.pdf'
        expected=binding['sha256'] if kind=='credential-record' else proof['summary']['original']['sha256']
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Content-credentials evidence changed before download.')
        return raw

    def close(self):
        with self.lock:
            for job in self.jobs.values():job['cancel'].set()
        self.executor.shutdown(wait=True,cancel_futures=True)


class ReviewServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,application,port=0):
        self.application=application
        super().__init__(('127.0.0.1',port),Handler)
        self.origin='http://127.0.0.1:'+str(self.server_port)


class _RequestBody:
    def __init__(self,handler):self.handler=handler
    def read(self,length):return self.handler.read_body(length)


class Handler(BaseHTTPRequestHandler):
    server_version='PDFRemediator';sys_version=''
    def log_message(self,*args):pass
    def setup(self):super().setup();self.connection.settimeout(30)
    @property
    def app(self):return self.server.application
    def respond(self,status,body,content_type='application/json; charset=utf-8',download=None):
        raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
        self.end_headers();self.wfile.write(raw)
    def secure(self,api=False):
        if self.headers.get('Host')!=urllib.parse.urlsplit(self.server.origin).netloc:raise PermissionError('Unrecognized local host.')
        origin=self.headers.get('Origin')
        if origin and origin!=self.server.origin:raise PermissionError('External origins are not allowed.')
        if self.headers.get('Sec-Fetch-Site')=='cross-site':raise PermissionError('Cross-site requests are not allowed.')
        if api and not secrets.compare_digest(self.headers.get('X-Review-Token',''),self.app.token):raise PermissionError('Open the private launch link to use this review session.')
    def read_json(self):
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('A JSON action is required.')
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=MAX_JSON:raise ValueError('The requested action is too large or empty.')
        value=json.loads(self.read_body(length))
        if not isinstance(value,dict):raise ValueError('An action must be an object.')
        return value
    def read_body(self,length):
        raw=self.rfile.read(length)
        remaining=getattr(self,'_body_remaining',None)
        if type(remaining) is int:self._body_remaining=max(0,remaining-len(raw))
        return raw
    def discard_small_rejected_body(self):
        # Closing a Windows socket while a small POST body is arriving can
        # reset the connection before the rejection reaches the client.
        # Drain only a bounded declared remainder, with a short deadline.
        remaining=getattr(self,'_body_remaining',None)
        if self.command!='POST' or remaining==0:return
        budget=min(remaining,64*1024) if type(remaining) is int and remaining>0 else 64*1024
        previous=self.connection.gettimeout();deadline=time.monotonic()+.1
        try:
            while budget>0:
                seconds=deadline-time.monotonic()
                if seconds<=0:break
                self.connection.settimeout(seconds)
                raw=self.rfile.read1(min(budget,8192))
                if not raw:break
                budget-=len(raw)
                if type(remaining) is int and remaining>0:
                    remaining-=len(raw);self._body_remaining=remaining
        except (OSError,TimeoutError):pass
        finally:self.connection.settimeout(previous)
    def do_GET(self):
        try:
            parsed=urllib.parse.urlsplit(self.path);path=parsed.path;self.secure(path.startswith('/api/'))
            if path=='/':return self.respond(200,(ASSETS/'index.html').read_bytes(),'text/html; charset=utf-8')
            if path in ('/app.js','/style.css'):
                return self.respond(200,(ASSETS/path[1:]).read_bytes(),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
            if path=='/PDFRemediator.svg':return self.respond(200,(ASSETS/'PDFRemediator.svg').read_bytes(),'image/svg+xml; charset=utf-8')
            if path=='/favicon.ico':return self.respond(200,(ASSETS/'PDFRemediator.ico').read_bytes(),'image/vnd.microsoft.icon')
            if path=='/api/dashboard':return self.respond(200,self.app.dashboard())
            if path=='/api/bundles':return self.respond(200,self.app.catalog())
            if path=='/api/update-check':
                from .updates import check
                return self.respond(200,check(self.app.config))
            if path=='/api/models':
                from .assistance import list_models
                query=urllib.parse.parse_qs(parsed.query)
                return self.respond(200,list_models(query.get('endpoint',[''])[0]))
            match=re.fullmatch(r'/api/workspaces/([a-f0-9]{24})(?:/(page|context|download|ocr|credential-original|credential-record))?',path)
            if match:
                identifier,action=match.groups()
                if not action:return self.respond(200,self.app.view(identifier))
                query=urllib.parse.parse_qs(parsed.query)
                if action in ('credential-original','credential-record'):
                    if parsed.query:raise ValueError('Content-credentials downloads do not accept file paths or query options.')
                    original=action=='credential-original'
                    return self.respond(200,self.app.credential_record(identifier,action),
                        'application/pdf' if original else 'application/json; charset=utf-8',
                        download='original-with-content-credentials.pdf' if original else 'credential-lineage.json')
                if action=='ocr':
                    from .workspace import get_ocr_editor
                    with self.app.pdf_lock:
                        result=get_ocr_editor(self.app.state_path(identifier),int(query.get('page',['1'])[0]),profile=query.get('profile',['legacy'])[0])
                    return self.respond(200,result)
                if action=='page':return self.respond(200,self.app.render_page(identifier,query.get('kind',['original'])[0],int(query.get('page',['1'])[0])),'image/png')
                if action=='context':return self.respond(200,self.app.page_context(identifier,int(query.get('page',['1'])[0])))
                view=self.app.view(identifier)
                if view['stale'] or not view.get('output'):raise ValueError('No current result is available for download.')
                output=Path(view['output']['path'])
                if sha(output)!=view['output']['sha256']:raise ValueError('The result changed. Reprocess before downloading.')
                return self.respond(200,output.read_bytes(),'application/pdf',download=download_filename(view))
            self.respond(404,{'error':'This review page was not found.'})
        except Exception as exc:self.failure(exc)
    def do_POST(self):
        try:
            try:self._body_remaining=int(self.headers.get('Content-Length','0'))
            except ValueError:self._body_remaining=None
            self.secure(True);path=urllib.parse.urlsplit(self.path).path
            if path=='/api/upload':
                if self.headers.get('Content-Type')!='application/pdf':raise ValueError('Choose a PDF file.')
                return self.respond(201,self.app.upload(_RequestBody(self),int(self.headers.get('Content-Length','0')),urllib.parse.unquote(self.headers.get('X-File-Name',''))))
            payload=self.read_json()
            if path=='/api/import':return self.respond(201,{'workspace_id':self.app.import_bundle(payload['path'])})
            if path=='/api/process':return self.respond(202,self.app.process(payload))
            if path=='/api/stop':
                _lifecycle('Stop application requested through authenticated local action.')
                try:
                    # Daemon handlers must finish the acknowledgement before
                    # shutdown can let the service's main thread exit.
                    self.respond(200,{'status':'stopping'})
                    self.wfile.flush()
                except OSError:
                    _lifecycle('Stop acknowledgement could not be delivered; authenticated shutdown will continue.')
                finally:
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            match=re.fullmatch(r'/api/jobs/([a-f0-9]{24})/cancel',path)
            if match:
                with self.app.lock:
                    job=self.app.jobs.get(match[1])
                    if not job:raise ValueError('Unknown processing job.')
                    job['cancel'].set()
                return self.respond(200,{'status':'cancellation-requested'})
            match=re.fullmatch(r'/api/workspaces/([a-f0-9]{24})/(edit|approve|review|group|assist|accept-draft|apply|auto-fix|retry|export|ocr-edit|ocr-approve|ocr-apply|ocr-insert|ocr-remove|credential-copy)',path)
            if not match:return self.respond(404,{'error':'This action was not found.'})
            identifier,action=match.groups();state=self.app.state_path(identifier)
            from . import workspace
            revision=payload['revision'];reviewer=payload.get('reviewer','');date=payload.get('reviewed_at') or datetime.now(timezone.utc).isoformat()
            with self.app.pdf_lock:
                if action=='edit':result=workspace.edit_decision(state,payload['id'],payload['value'],revision)
                elif action=='approve':result=workspace.approve_decision(state,payload['id'],reviewer,date,revision)
                elif action=='review':result=workspace.review_item(state,payload['id'],payload['status'],reviewer,date,revision,notes=payload.get('notes',''))
                elif action=='group':result=workspace.approve_group(state,payload['group_id'],payload['member_ids'],payload['membership_digest'],reviewer,date,revision)
                elif action=='assist':return self.respond(202,self.app.assist(identifier,payload))
                elif action=='accept-draft':result=workspace.accept_suggestion(state,payload['suggestion_id'],revision)
                elif action=='apply':return self.respond(202,self.app.apply(identifier,payload))
                elif action=='retry':return self.respond(202,self.app.retry(identifier,payload))
                elif action=='auto-fix':return self.respond(202,self.app.auto_fix(identifier,payload))
                elif action=='ocr-edit':result=workspace.edit_ocr_text(state,payload['id'],payload['value'],revision,payload['inventory_sha256'],payload['context_sha256'],actor=payload.get('actor','human'),expansion_sha256=payload.get('expansion_sha256'))
                elif action=='ocr-approve':result=workspace.approve_ocr_text(state,payload['id'],reviewer,date,revision,payload['inventory_sha256'],payload['context_sha256'],actor=payload.get('actor','human'),expansion_sha256=payload.get('expansion_sha256'))
                elif action=='ocr-insert':result=workspace.insert_ocr_text(state,payload['anchor_id'],payload['value'],payload['placement'],revision,payload['inventory_sha256'],payload['context_sha256'],identifier=payload.get('id'),actor=payload.get('actor','human'),expansion_sha256=payload.get('expansion_sha256'))
                elif action=='ocr-remove':result=workspace.remove_ocr_insertion(state,payload['id'],revision,payload['inventory_sha256'],payload['context_sha256'],actor=payload.get('actor','human'),expansion_sha256=payload.get('expansion_sha256'))
                elif action=='ocr-apply':return self.respond(202,self.app.ocr_apply(identifier,payload))
                elif action=='credential-copy':return self.respond(202,self.app.credential_copy(identifier,payload))
                else:result=workspace.export_workspace(state,self.app.root/'exports'/uuid.uuid4().hex[:12],revision)
            self.respond(200,result)
        except Exception as exc:self.failure(exc)
    def do_OPTIONS(self):self.respond(403,{'error':'Cross-origin access is disabled.'})
    def failure(self,exc):
        code=403 if isinstance(exc,PermissionError) else 404 if isinstance(exc,FileNotFoundError) else 409 if 'revision' in str(exc).lower() or 'changed' in str(exc).lower() else 400 if isinstance(exc,(ValueError,KeyError,TypeError,RuntimeError)) else 500
        self.discard_small_rejected_body()
        self.respond(code,{'error':str(exc)[:1200] if code!=500 else 'The local action failed. Check the application log.'})


def serve(data_dir,config=None,port=0,open_browser=True,import_bundle=None,session_file=None):
    # A crash that Python cannot catch (an access violation, for one) writes where the program was to the same log the service writes to, instead of ending without a word.
    # The log is the service's standard error when the launcher started it. Where there is none (a window with no console), nothing is turned on and nothing is lost.
    try:
        import faulthandler
        faulthandler.enable(all_threads=True)
    except (AttributeError,OSError,RuntimeError,ValueError):pass
    _lifecycle('PDF Remediator service starting (process %d).'%__import__('os').getpid())
    application=Application(data_dir,config);server=None
    try:
        server=ReviewServer(application,port)
        if import_bundle:application.import_bundle(import_bundle)
        url=server.origin+'/#'+application.token
        if session_file:
            from .pipeline import implementation_digest
            write_json(session_file,{'url':url,'origin':server.origin,'pid':__import__('os').getpid(),
                'implementation_digest':implementation_digest(application.config),'settings_digest':application.config.digest()})
        print('PDF Remediator is ready. Keep this window running.\n'+(server.origin if session_file else url),flush=True)
        if open_browser:webbrowser.open(url)
        try:server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:pass
    finally:
        _lifecycle('PDF Remediator service closing.')
        try:
            if server is not None:server.server_close()
        finally:application.close()
