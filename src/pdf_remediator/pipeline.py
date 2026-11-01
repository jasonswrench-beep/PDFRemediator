"""Per-file isolation, exact checkpoints, strict gates, and atomic run bundles."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
from dataclasses import replace
import hashlib,json,os,re,shutil,time,uuid
import copy
from pathlib import Path
from . import __version__
from .config import RuntimeConfig
from .processors import normalize_catalog
from .io_utils import atomic_replace

SCHEMA='phase1-report-1'

class UnsupportedDocument(ValueError):
    pass

def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    atomic_replace(temp,path)


def _metadata_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def implementation_digest(config):
    package=Path(__file__).parent
    files=sorted(p for p in package.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.txt','.tex','.html','.css','.js','.ttf'))
    payload={str(file.relative_to(package)):sha(file) for file in files}
    for name in ('odl_jar','validator_cli'):
        path=Path(getattr(config,name));payload[name]=sha(path) if path.is_file() else 'missing'
    for relative in ('bin/java.exe','release','bin/server/jvm.dll'):
        path=config.java_home/relative;payload['java/'+relative]=sha(path) if path.is_file() else 'missing'
    validator=Path(config.validator_cli).parent
    for file in sorted((validator/'bin').glob('*.jar')) if (validator/'bin').exists() else []:
        payload['validator/'+file.name]=sha(file)
    for name in ('pikepdf','pypdfium2','Pillow','PyYAML','psutil','fontTools'):
        from importlib.metadata import version
        payload[name]=version(name)
    if config.ocr_mode!='off' or config.repair_ocr_mappings:
        for label,path in [('tesseract',config.tesseract_dir/'tesseract.exe'),('english-model',config.tesseract_dir/'tessdata/eng.traineddata')]:
            payload[label]=sha(path) if path.is_file() else 'missing'
        # Embedded Python keeps the factory._pth site below its executable;
        # Windows venvs keep it above Scripts. Never search host/user sites.
        ocrroot=config.ocr_python.parent
        if ocrroot.name.casefold()=='scripts':ocrroot=ocrroot.parent
        ocrsite=ocrroot/'Lib/site-packages'
        for path in sorted((ocrsite/'ocrmypdf').rglob('*.py')) if (ocrsite/'ocrmypdf').exists() else []:
            payload['ocr/'+str(path.relative_to(ocrsite))]=sha(path)
        for path in sorted(ocrsite.glob('*.dist-info/METADATA')) if ocrsite.exists() else []:
            payload['ocr-dependency/'+path.parent.name]=sha(path)
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()

def _cancel(cancel):
    if cancel is not None and cancel.is_set():raise InterruptedError('Processing cancelled; no candidate published.')

def _check(inspection,name):
    return next((item for item in inspection.get('checks',[]) if item['id']==name),{})

def _safe_name(path):
    return (re.sub(r'[^A-Za-z0-9._-]+','-',Path(path).stem).strip('.-') or 'document')[:70]

def _issue(code,description,path='Review the original/source document or repair with a suitable PDF editor.'):
    return {'id':code,'description':description,'fix_path':path}

def discover(source,outdir=None,recurse=False):
    source=Path(source).resolve()
    if source.is_file():return [source]
    if not source.is_dir():raise FileNotFoundError(source)
    out=Path(outdir).resolve() if outdir else None
    if out==source:raise ValueError('A batch output directory must be separate from the input directory.')
    found=[]
    for file in (source.rglob('*') if recurse else source.iterdir()):
        if not file.is_file() or file.suffix.lower()!='.pdf':continue
        resolved=file.resolve()
        if out and (resolved==out or out in resolved.parents):continue
        relative=file.relative_to(source)
        if any(part.startswith('.') or part in ('tools','historical-repository') for part in relative.parts[:-1]):continue
        found.append(resolved)
    return sorted(set(found),key=str)

def verify_bundle(bundle):
    bundle=Path(bundle).resolve();manifest=bundle/'manifest.json'
    try:
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('complete') is not True:return False
        required={'report.json','review.html','review.json','decisions.json'}
        if not isinstance(data.get('files'),dict) or not required.issubset(data['files']):return False
        for relative,digest in data['files'].items():
            file=(bundle/relative).resolve()
            if bundle not in file.parents or not file.is_file() or sha(file)!=digest:return False
        report=json.loads((bundle/'report.json').read_text(encoding='utf-8'))
        if report.get('run_fingerprint')!=data.get('run_fingerprint'):return False
        if report.get('status') not in ('candidate','needs-manual','failed','verified'):return False
        output=report.get('output')
        if output:
            file=Path(output['path']).resolve()
            if file.parent!=bundle or file.name not in data['files'] or sha(file)!=output['sha256']:return False
        elif report['status']=='candidate' and report.get('mode')=='fix':return False
        return True
    except (OSError,ValueError,KeyError,TypeError):return False


def _review_checkpoint(bundle,source_hash,config,cancel=None):
    """Adopt explicit prior preparation, then assess the edited result afresh.

    Review can outlive an application update. Its exact prepared bytes and
    reference are retained; old automated pass results never become new passes.
    """
    bundle=Path(bundle).resolve()
    if not verify_bundle(bundle):raise ValueError('The selected review bundle is incomplete or changed.')
    previous=json.loads((bundle/'report.json').read_text(encoding='utf-8'))
    if previous.get('mode')!='fix' or previous['input']['sha256']!=source_hash:raise ValueError('The review checkpoint belongs to another source or a read-only check.')
    previous_settings=previous.get('settings')
    expected_settings=config.public()
    # Older reviews used the standard OCR route before profiles existed. Accept
    # only that exact missing default; every other preparation setting remains
    # identical, and selecting a new profile requires a separate processing run.
    if isinstance(previous_settings,dict) and 'ocr_profile' not in previous_settings and config.ocr_profile=='standard':
        expected_settings.pop('ocr_profile')
    if isinstance(previous_settings,dict) and 'repair_ocr_mappings' not in previous_settings and not config.repair_ocr_mappings:
        expected_settings.pop('repair_ocr_mappings')
    if isinstance(previous_settings,dict) and 'remove_cidset' not in previous_settings and not config.remove_cidset:
        expected_settings.pop('remove_cidset')
    if previous_settings!=expected_settings:raise ValueError('Keep the original preparation settings when applying accepted edits; reprocess separately to change settings.')
    decision_source=previous.get('decision_source') or {}
    checkpoint=Path(decision_source.get('path',''))
    if not checkpoint.is_file() or sha(checkpoint)!=decision_source.get('sha256'):raise ValueError('The exact prepared review checkpoint is missing or changed.')
    if decision_source.get('source_sha256')!=source_hash:raise ValueError('Review checkpoint source binding is invalid.')
    from .sidecar import collect_decisions,load_sidecar,inventory_profile_for,_STRUCTURAL_CONTEXT
    saved=load_sidecar(bundle/'decisions.json')
    inventory=collect_decisions(checkpoint,source_hash,inventory_profile=inventory_profile_for(saved),cancel=cancel)
    if saved.get('source_sha256')!=source_hash or saved.get('document_sha256')!=sha(checkpoint):raise ValueError('The decision inventory does not match this checkpoint.')
    fields=('id','kind','binding','context_sha256','current','element','page','structure_path','references',
            *_STRUCTURAL_CONTEXT)
    context=lambda data:[{key:item.get(key) for key in fields} for item in data.get('decisions',[])]
    if inventory.get('inventory_errors') or context(inventory)!=context(saved):raise ValueError('The prepared decision context changed.')
    processors=[item for item in previous.get('processors',[]) if item.get('name')!='approved-decisions']
    reference=None;policy=previous.get('fidelity',{}).get('policy')
    if policy:
        if policy not in ('ocr-added-text','authoritative-character-mapping','ocr-derived-character-mapping'):raise ValueError('Unknown preservation reference policy.')
        reference=checkpoint.parent/'reference.pdf'
        expected=previous['fidelity'].get('reference_sha256')
        if not expected or not reference.is_file() or sha(reference)!=expected:raise ValueError('The exact independent preservation reference is missing or changed.')
    processors.append({'name':'review-checkpoint-import','status':'completed','bundle_path':str(bundle),
        'manifest_sha256':sha(bundle/'manifest.json'),'prepared_sha256':sha(checkpoint),
        'scope':'Explicit adoption of exact preparation bytes; all final assessments are rerun.'})
    return checkpoint,processors,reference,policy


def _validated_ocr_lineage(binding,source,expected_sha256=None,cancel=None):
    """Validate the immutable correction ancestry without changing old fidelity rules."""
    from .ocr_corrections import validate_lineage
    if isinstance(binding,(str,Path)):
        binding={'path':str(Path(binding).resolve()),'sha256':expected_sha256}
    if (not isinstance(binding,dict) or set(binding)!={'path','sha256'}
            or not isinstance(binding['path'],str) or not isinstance(binding['sha256'],str)
            or not re.fullmatch('[a-f0-9]{64}',binding['sha256'])):
        raise ValueError('An exact OCR correction lineage path and hash are required.')
    if expected_sha256 is not None and expected_sha256!=binding['sha256']:
        raise ValueError('The expected OCR correction lineage changed.')
    path=Path(binding['path']).resolve()
    if not path.is_file() or sha(path)!=binding['sha256']:
        raise ValueError('OCR correction lineage is missing or changed.')
    details=validate_lineage(path,source,expected_sha256=binding['sha256'],cancel=cancel)
    if not isinstance(details,dict) or sha(path)!=binding['sha256']:
        raise ValueError('OCR correction lineage changed during validation.')
    return {'path':str(path),'sha256':binding['sha256']},details


def _retain_ocr_lineage(binding,staging):
    """Keep raw provenance outside the validator JSON relocation pass."""
    directory=Path(staging)/'lineage';directory.mkdir()
    origin=Path(binding['path']);raw=origin.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=binding['sha256']:
        raise ValueError('OCR correction lineage changed before retention.')
    destination=directory/'source-lineage.json'
    destination.write_bytes(raw)
    if sha(destination)!=binding['sha256']:
        raise ValueError('The retained OCR lineage copy differs from its binding.')
    # A lineage keeps its original absolute bindings. Retain local copies of
    # its plan and proof as evidence, without rewriting the accepted record.
    value=json.loads(raw)
    for key in ('plan','proof','correction_plan','verification','evidence'):
        row=value.get(key)
        if not isinstance(row,dict) or set(row)!={'path','sha256'}:continue
        file=Path(row['path'])
        if file.suffix.lower()!='.json' or not file.is_file() or sha(file)!=row['sha256']:
            raise ValueError('OCR correction plan or proof changed before retention.')
        copy_path=directory/(key+'.json');shutil.copyfile(file,copy_path)
        if sha(copy_path)!=row['sha256'] or sha(file)!=row['sha256']:
            raise ValueError('The retained OCR correction evidence copy differs from its binding.')
    return {'path':str(destination),'sha256':binding['sha256']}


def _process_ocr_derivative(source,outdir,config,*,bundle,plan,expected_plan_sha256,
                            expected_source_sha256=None,cancel=None,progress=None):
    """Correct a separate copy, then use the ordinary unmodified validation gates."""
    from .ocr_corrections import create_derivative
    source=Path(source).resolve();outdir=Path(outdir).resolve();bundle=Path(bundle).resolve()
    original_hash=sha(source)
    if expected_source_sha256 is not None and original_hash!=expected_source_sha256:
        raise ValueError('The selected original changed before OCR correction.')
    if not isinstance(expected_plan_sha256,str) or not re.fullmatch('[a-f0-9]{64}',expected_plan_sha256):
        raise ValueError('An exact accepted OCR correction plan hash is required.')
    plan=Path(plan).resolve()
    if not plan.is_file() or sha(plan)!=expected_plan_sha256:
        raise ValueError('The accepted OCR correction plan is missing or changed.')
    if outdir==bundle or bundle in outdir.parents:
        raise ValueError('An OCR correction result must be outside the prior immutable bundle.')
    if not verify_bundle(bundle):raise ValueError('The prior OCR review bundle changed.')
    previous=json.loads((bundle/'report.json').read_text(encoding='utf-8'))
    expected=config.public()
    if isinstance(previous.get('settings'),dict) and 'ocr_profile' not in previous['settings'] and config.ocr_profile=='standard':
        expected.pop('ocr_profile')
    if isinstance(previous.get('settings'),dict) and 'repair_ocr_mappings' not in previous['settings'] and not config.repair_ocr_mappings:
        expected.pop('repair_ocr_mappings')
    if isinstance(previous.get('settings'),dict) and 'remove_cidset' not in previous['settings'] and not config.remove_cidset:
        expected.pop('remove_cidset')
    if (previous.get('mode')!='fix' or previous.get('input',{}).get('sha256')!=original_hash
            or previous.get('settings')!=expected):
        raise ValueError('Keep the selected review source and preparation when accepting OCR corrections.')
    _cancel(cancel)
    if progress:progress(source.name+': create a separate corrected OCR copy')
    destination=outdir/'.ocr-inputs'/uuid.uuid4().hex
    destination.parent.mkdir(parents=True,exist_ok=True)
    result=create_derivative(bundle,plan,destination,expected_plan_sha256=expected_plan_sha256,cancel=cancel)
    corrected=Path(result['source_path']).resolve()
    lineage={'path':str(Path(result['lineage_path']).resolve()),'sha256':result['lineage_sha256']}
    _validated_ocr_lineage(lineage,corrected,cancel=cancel)
    if sha(source)!=original_hash:raise ValueError('The original changed during OCR correction.')
    # The current artifact already includes earlier accepted catalog edits.
    # Preserve them when the new source goes through normal normalization.
    import pikepdf
    with pikepdf.open(corrected) as pdf:
        language=str(pdf.Root.get('/Lang',config.language))
        title=str(pdf.docinfo['/Title']) if '/Title' in pdf.docinfo else None
    corrected_config=replace(config,ocr_mode='off',ocr_profile='standard',repair_source_mappings=False,repair_ocr_mappings=False,
                             language=language,title=title)
    return process_file(corrected,outdir,corrected_config,mode='fix',cancel=cancel,progress=progress,
                        expected_source_sha256=sha(corrected),source_lineage=lineage)

@contextmanager
def _lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    try:descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('This input is already processing, or an interrupted lock needs review: '+str(path))
    try:
        os.write(descriptor,str(os.getpid()).encode());os.close(descriptor);yield
    finally:
        if path.exists():path.unlink()

def _relative_evidence(value,old,new):
    if isinstance(value,dict):return {k:v if k in ('command','input') else _relative_evidence(v,old,new) for k,v in value.items()}
    if isinstance(value,list):return [_relative_evidence(v,old,new) for v in value]
    if isinstance(value,str) and value.startswith(str(old)):
        return str(new)+value[len(str(old)):]
    return value

def process_file(source,outdir,config:RuntimeConfig,*,mode='fix',sidecar=None,resume=False,cancel=None,progress=None,decision_bundle=None,expected_source_sha256=None,expected_sidecar_sha256=None,automatic_authorization=None,ocr_correction_plan=None,expected_ocr_correction_sha256=None,ocr_correction_bundle=None,source_lineage=None,expected_lineage_sha256=None,credential_lineage=None,expected_credential_lineage_sha256=None):
    from .inspection import inspect_pdf,compare_fidelity
    from .validation import validate_pdf
    from .engines import tag
    from .checks import assess
    from .sidecar import (collect_decisions,write_sidecar,load_sidecar,apply_decisions,
        validate_automatic_authorization,decisions_digest,inventory_profile_for,FORM_INVENTORY_PROFILE,EMPTY_TAG_INVENTORY_PROFILE)
    from .review import render_review_packet
    source=Path(source).resolve();outdir=Path(outdir).resolve()
    if mode not in ('fix','check'):raise ValueError('Unsupported processing mode.')
    if not source.is_file():raise FileNotFoundError(source)
    if ocr_correction_plan is not None:
        if credential_lineage is not None or (ocr_correction_bundle and verify_bundle(ocr_correction_bundle)
                and json.loads((Path(ocr_correction_bundle)/'report.json').read_text(encoding='utf-8')).get('credential_lineage')):
            raise ValueError('OCR-editor chaining for a credential-free source requires a separately proven ancestry route and is not yet supported.')
        if (mode!='fix' or not ocr_correction_bundle or sidecar or decision_bundle or automatic_authorization is not None
                or source_lineage is not None or resume):
            raise ValueError('OCR corrections require a separate accepted correction plan and new result.')
        return _process_ocr_derivative(source,outdir,config,bundle=ocr_correction_bundle,plan=ocr_correction_plan,
            expected_plan_sha256=expected_ocr_correction_sha256,expected_source_sha256=expected_source_sha256,
            cancel=cancel,progress=progress)
    if ocr_correction_bundle is not None or expected_ocr_correction_sha256 is not None:
        raise ValueError('OCR correction context requires its explicit accepted plan.')
    input_hash=sha(source);settings_hash=config.digest();code_hash=implementation_digest(config)
    if expected_source_sha256 is not None and input_hash!=expected_source_sha256:raise ValueError('The selected input changed while waiting to process.')
    if source_lineage is None and decision_bundle:
        # Preserve the existing failed-bundle reporting boundary: malformed
        # checkpoints are refused inside _review_checkpoint, never prepared.
        if verify_bundle(decision_bundle):
            previous=json.loads((Path(decision_bundle)/'report.json').read_text(encoding='utf-8'))
            source_lineage=copy.deepcopy(previous.get('source_lineage'))
    if credential_lineage is None and decision_bundle and verify_bundle(decision_bundle):
        previous=json.loads((Path(decision_bundle)/'report.json').read_text(encoding='utf-8'))
        credential_lineage=copy.deepcopy(previous.get('credential_lineage'))
    credential_binding=None;credential_details=None
    if credential_lineage is not None:
        from .credentials import validate_lineage
        if source_lineage is not None:
            raise ValueError('Credential-free ancestry requires its independent source; OCR-editor chaining is not yet supported.')
        if isinstance(credential_lineage,(str,Path)):
            credential_lineage={'path':str(Path(credential_lineage).resolve()),'sha256':expected_credential_lineage_sha256}
        if (not isinstance(credential_lineage,dict) or set(credential_lineage)!={'path','sha256'}
                or not isinstance(credential_lineage['path'],str) or not isinstance(credential_lineage['sha256'],str)
                or not re.fullmatch('[a-f0-9]{64}',credential_lineage['sha256'])
                or expected_credential_lineage_sha256 is not None and expected_credential_lineage_sha256!=credential_lineage['sha256']):
            raise ValueError('An exact credential lineage path and hash are required.')
        credential_binding={'path':str(Path(credential_lineage['path']).resolve()),'sha256':credential_lineage['sha256']}
        credential_details=validate_lineage(credential_binding['path'],source,credential_binding['sha256'],cancel)
    elif expected_credential_lineage_sha256 is not None:
        raise ValueError('An expected credential lineage hash requires its exact lineage record.')
    lineage_binding=None;lineage_details=None
    if source_lineage is not None:
        if mode!='fix' or config.ocr_mode!='off':
            raise ValueError('A corrected OCR source must be rechecked with OCR off.')
        lineage_binding,lineage_details=_validated_ocr_lineage(source_lineage,source,expected_lineage_sha256,cancel)
    elif expected_lineage_sha256 is not None:
        raise ValueError('An expected OCR lineage hash requires its lineage record.')
    if automatic_authorization is not None:
        if mode!='fix' or not sidecar:raise ValueError('Automatic application requires fix and an explicit bound decision file.')
        automatic_authorization=copy.deepcopy(automatic_authorization)
        validate_automatic_authorization(automatic_authorization,input_hash)
    automatic_hash=decisions_digest(automatic_authorization) if automatic_authorization is not None else None
    decision_hash=sha(sidecar) if sidecar else 'no-decisions'
    if expected_sidecar_sha256 is not None and decision_hash!=expected_sidecar_sha256:raise ValueError('Accepted decisions changed while waiting to process.')
    supplied_decisions=None
    inventory_profile=EMPTY_TAG_INVENTORY_PROFILE
    if decision_bundle and (mode!='fix' or not sidecar):raise ValueError('Applying a prior review checkpoint requires fix and an explicit accepted decision file.')
    import_hash=sha(Path(decision_bundle)/'manifest.json') if decision_bundle else 'no-review-checkpoint'
    source_identity=hashlib.sha256(os.path.normcase(str(source)).encode()).hexdigest()
    fingerprint=hashlib.sha256((input_hash+source_identity+settings_hash+code_hash+decision_hash+mode+import_hash+(automatic_hash or '')+(lineage_binding['sha256'] if lineage_binding else '')+(credential_binding['sha256'] if credential_binding else '')).encode()).hexdigest()
    name=_safe_name(source)+'-'+input_hash[:12]+'-'+fingerprint[:10]
    final=outdir/name
    if final.exists():
        if resume and verify_bundle(final):
            candidates=[final]+sorted(outdir.glob(name+'-retry-*'),key=lambda p:p.stat().st_mtime,reverse=True)
            for previous in candidates:
                if not verify_bundle(previous):continue
                result=json.loads((previous/'report.json').read_text(encoding='utf-8'))
                if result.get('status')!='failed':result['resumed']=True;return result
            final=outdir/(name+'-retry-'+uuid.uuid4().hex[:8])
        else:
            raise FileExistsError('Existing run is immutable or changed; use --resume or another output directory: '+str(final))
    outdir.mkdir(parents=True,exist_ok=True)
    staging=outdir/'.staging'/uuid.uuid4().hex[:16]
    staging.mkdir(parents=True)
    started=time.monotonic();processor_results=[];decisions={};prepared=None;processed=None;reference=None;reference_policy=None;form_route=False
    report={'schema_version':SCHEMA,'tool_version':__version__,'created_at':datetime.now(timezone.utc).isoformat(),
      'input':{'path':str(source),'sha256':input_hash},'output':None,'mode':mode,'status':'failed',
      'settings':config.public(),'settings_digest':settings_hash,'implementation_digest':code_hash,'run_fingerprint':fingerprint,
      'classification':[],'processors':processor_results,'gate1':{'status':'not-run'},'gate2':{'status':'not-tested'},
      'fidelity':{'status':'not-tested'},'manual_review':{'items':[],'complete':False},'residual_issues':[],
      'data_sent':{'provider':None,'document_api_calls':0,'processing':'local-only; no AI enrichment'},'timings':{},
      'bundle_path':str(final),'resumed':False}
    if automatic_authorization is not None:
        report['automatic_mode']={'mode':'best-guess','human_reviewed':False,'authorization':automatic_authorization,
            'authorization_sha256':automatic_hash,'scope':'Explicitly authorized automatic application; no human semantic approvals or verification are supplied.'}
    def announce(message):
        if progress:progress(source.name+': '+message)
        _cancel(cancel)
    try:
        with _lock(outdir/'.locks'/(input_hash+'.lock')):
            announce('inspect input')
            baseline=inspect_pdf(source,cancel=cancel);report['classification']=baseline.get('pages',[])
            report['baseline']=baseline
            if baseline.get('error'):
                if baseline['error'].get('type')=='PasswordError':raise UnsupportedDocument('Password-protected inputs require an explicit derivative workflow.')
                raise ValueError('Input could not be read: '+str(baseline['error']))
            features=baseline.get('features',{})
            if sidecar:
                supplied_decisions=load_sidecar(sidecar)
                if sha(sidecar)!=decision_hash:raise ValueError('Accepted decisions changed while reading them.')
                inventory_profile=inventory_profile_for(supplied_decisions)
            # PDF signature and encryption checks precede any writer.
            import pikepdf
            with pikepdf.open(source) as pdf:
                signed=bool(pdf.Root.get('/Perms')) or any(str(obj.get('/FT',''))=='/Sig' for obj in pdf.objects if isinstance(obj,pikepdf.Dictionary))
                if pdf.is_encrypted:raise UnsupportedDocument('Encrypted inputs require a separately selected derivative workflow.')
                if signed:raise UnsupportedDocument('Signed inputs require an explicit derivative workflow; signatures are not silently invalidated.')
                if float(pdf.pdf_version)>=2:raise UnsupportedDocument('PDF 2.x inputs are outside the evaluated PDF/UA-1 workflow.')
                from .form_edits import has_form_signals,preflight
                if mode=='fix' and has_form_signals(pdf):
                    if inventory_profile not in {FORM_INVENTORY_PROFILE,EMPTY_TAG_INVENTORY_PROFILE}:
                        raise UnsupportedDocument('Older saved-review profiles do not authorize interactive-form edits. Prepare a new result from the unchanged original.')
                    if config.ocr_mode!='off' or config.repair_source_mappings or config.repair_ocr_mappings or config.remove_cidset:
                        raise UnsupportedDocument('Interactive forms require OCR, source character-mapping repair and font-list removal off; their values and appearances are retained exactly.')
                    form_proof=preflight(pdf,cancel=cancel)
                    independent_form=baseline.get('form_accessibility',{})
                    if (not form_proof.get('supported') or independent_form.get('policy')!='bounded-acroform-1'
                            or independent_form.get('supported_structure') is not True):
                        raise UnsupportedDocument('This interactive form is outside the proven label/navigation repair scope: '+
                            '; '.join(form_proof.get('limitations',[]) or independent_form.get('limitations',[]) or ['Independent form structure proof is unavailable.']))
                    form_route=True
                    report['form_route']={'policy':'reviewed-form-1','source_sha256':input_hash,
                        'preparation':'Retain the exact interactive original checkpoint; no tagging, OCR, form filling, flattening or implicit navigation/catalog repair.',
                        'proof':form_proof}
            if lineage_binding:
                report['source_lineage']=_retain_ocr_lineage(lineage_binding,staging)
            if credential_binding:
                from .credentials import retain_lineage
                report['credential_lineage'],report['credential_derivative']=retain_lineage(credential_binding,staging,source,cancel)
            if mode=='fix':
                if config.document_kind in ('slides','equations'):raise UnsupportedDocument('Declared '+config.document_kind+' input requires source-document/manual remediation in this release.')
                special={key:features[key] for key in ('forms','attachments','javascript','optional_content','equation_tags') if features.get(key)}
                if form_route:special.pop('forms',None)
                if special:
                    if special.get('attachments') and baseline.get('content_credentials',{}).get('supported'):
                        raise UnsupportedDocument('This PDF contains a C2PA-labelled Content Credentials manifest. Its cryptographic validity was not verified. Ordinary editing could invalidate it. Keep the original; explicitly authorize a separate copy without credentials before remediation.')
                    raise UnsupportedDocument('Detected features require manual/source-document handling: '+', '.join(special))
                announce('validate original baseline')
                report['baseline_gate1']=validate_pdf(source,staging/'evidence/baseline-validator',config.validator_cli,config.java_home,
                    timeout_seconds=config.validator_timeout_seconds,cancel=cancel,memory_limit_bytes=config.memory_limit_bytes,heap_mb=config.java_heap_mb)
                if report['baseline_gate1'].get('input_sha256')!=input_hash or sha(source)!=input_hash:
                    raise RuntimeError('The baseline validator did not assess the unchanged source bytes.')
            if mode=='check':
                prepared=source;processed=source;decisions=collect_decisions(source,input_hash,inventory_profile=inventory_profile,cancel=cancel)
            else:
                cachekey=hashlib.sha256((input_hash+settings_hash+code_hash+import_hash+(lineage_binding['sha256'] if lineage_binding else '')+(credential_binding['sha256'] if credential_binding else '')).encode()).hexdigest()
                cache=outdir/'.cache'/cachekey;checkpoint=cache/'prepared.pdf';cachemeta=cache/'checkpoint.json'
                cache_created=False
                if decision_bundle:
                    imported,prior_processors,prior_reference,prior_policy=_review_checkpoint(decision_bundle,input_hash,config,cancel=cancel)
                    if not checkpoint.exists() and not cachemeta.exists():
                        announce('adopt the exact accepted review checkpoint')
                        cache.mkdir(parents=True,exist_ok=True);shutil.copyfile(imported,checkpoint)
                        if prior_reference:shutil.copyfile(prior_reference,cache/'reference.pdf')
                        write_json(cachemeta,{'source_sha256':input_hash,'settings_digest':settings_hash,'implementation_digest':code_hash,
                            'sha256':sha(checkpoint),'processors':prior_processors,'anchor_bundle':str(final),
                            'reference':{'sha256':sha(prior_reference),'policy':prior_policy} if prior_reference else None})
                        cache_created=True
                    elif not checkpoint.is_file() or sha(checkpoint)!=sha(imported):raise ValueError('The adopted review cache changed.')
                validcache=False
                if checkpoint.is_file() and cachemeta.is_file():
                    meta=json.loads(cachemeta.read_text(encoding='utf-8'))
                    validcache=meta.get('source_sha256')==input_hash and meta.get('settings_digest')==settings_hash and meta.get('implementation_digest')==code_hash and meta.get('sha256')==sha(checkpoint)
                    if not validcache:raise ValueError('Cached checkpoint is stale or changed; select a new output directory.')
                    if not cache_created:
                        anchor=Path(meta.get('anchor_bundle',''))
                        if not verify_bundle(anchor):raise ValueError('The preparation cache has no intact published provenance; select a new output directory.')
                        original_meta=json.loads((anchor/'report.json').read_text(encoding='utf-8'))
                        if original_meta.get('checkpoint_provenance_sha256')!=_metadata_digest(meta):raise ValueError('Cached preparation provenance changed.')
                    if decision_bundle:
                        expected_reference={'sha256':sha(prior_reference),'policy':prior_policy} if prior_reference else None
                        if meta.get('processors')!=prior_processors or meta.get('reference')!=expected_reference:
                            raise ValueError('The adopted cache provenance differs from the selected immutable review bundle.')
                    report['checkpoint_provenance_sha256']=_metadata_digest(meta)
                if validcache:
                    announce('reuse matching prepared checkpoint');prepared=checkpoint
                    processor_results.extend(meta.get('processors',[]));report['checkpoint_reused']=True
                    if meta.get('reference'):
                        reference=cache/'reference.pdf';reference_policy=meta['reference']['policy']
                        if not reference.is_file() or sha(reference)!=meta['reference']['sha256']:raise ValueError('Preservation reference checkpoint is stale or changed.')
                else:
                    work=staging/'work';work.mkdir();engine_input=source
                    if form_route:
                        announce('retain exact interactive-form checkpoint')
                        prepared_work=work/'prepared.pdf';shutil.copyfile(source,prepared_work)
                        processor_results.append({'name':'retained-form-checkpoint','status':'completed',
                            'input_sha256':input_hash,'output_sha256':sha(prepared_work),
                            'scope':'Interactive values, appearances, field/tag order and catalog are unchanged until explicit reviewed edits.',
                            'warnings':['Configured title/language are not applied implicitly to interactive forms; use their reviewed document edits.'] if config.title else []})
                    else:
                        if config.ocr_mode!='off':
                            from .ocr import run_ocr
                            announce('OCR '+config.ocr_mode)
                            ocr_output=work/'ocr.pdf'
                            outcome=run_ocr(source,ocr_output,config,work/'ocr-process',mode=config.ocr_mode,cancel=cancel)
                            processor_results.append({'name':'ocr',**outcome})
                            if outcome.get('status')=='unsupported':raise UnsupportedDocument('OCR route requires manual/source handling: '+str(outcome.get('error','Unsupported route.')))
                            if outcome.get('status')!='completed' or not ocr_output.is_file():raise RuntimeError('OCR did not complete; inspect its recorded outcome.')
                            if outcome.get('preservation',{}).get('status')!='pass':raise RuntimeError('OCR preservation did not pass the declared added-text policy.')
                            engine_input=ocr_output;reference=ocr_output;reference_policy='ocr-added-text'
                            report['ocr_pages']=(outcome['page_selection']['selected_pages'] if config.ocr_mode == 'textless' else
                                [p.get('page') for p in baseline.get('pages',[]) if p.get('class') in ('scanned','mixed')])
                        if config.repair_ocr_mappings:
                            from .ocr_mappings import POLICY as OCR_MAPPING_POLICY,repair_from_ocr
                            announce('derive missing character maps from OCR')
                            mapped_source=work/'ocr-mapped-source.pdf'
                            outcome=repair_from_ocr(source,mapped_source,config,work/'ocr-mappings',cancel=cancel)
                            processor_results.append(outcome)
                            if outcome.get('status') in ('pass','partial') and mapped_source.is_file():
                                engine_input=mapped_source;reference=mapped_source;reference_policy=OCR_MAPPING_POLICY
                            elif outcome.get('status')!='not-needed':
                                raise UnsupportedDocument('The requested OCR-derived character-map repair could not be proved; no substitute mapping was applied. '+str(outcome.get('error') or ''))
                        existing=inspect_pdf(engine_input,cancel=cancel)
                        usable=all(_check(existing,kind).get('status')=='pass' for kind in ('content-linkage','content-coverage'))
                        if not usable and _check(existing,'content-linkage').get('status')=='pass':
                            from .designed_pdf import cover_unmarked_graphics
                            announce('keep the existing tags: mark a few unmarked graphics as decoration')
                            covered=work/'covered-graphics.pdf'
                            outcome=cover_unmarked_graphics(engine_input,covered,cancel=cancel)
                            if outcome.get('status')!='not-needed':processor_results.append(outcome)
                            if outcome.get('status')=='pass' and covered.is_file():engine_input=covered;usable=True
                        if usable:
                            raw=engine_input;processor_results.append({'name':'engine','status':'skipped','reason':'Existing linked tags and content coverage are retained.'})
                        else:
                            from .designed_pdf import author_descriptions
                            written=author_descriptions(engine_input)
                            if written:processor_results.append({'name':'author-descriptions','status':'needs-manual','descriptions':written,
                                'reason':'The existing tags could not be kept, so the picture descriptions written in them were not carried over.'})
                            tag_source=engine_input
                            if not config.repair_source_mappings:
                                from .designed_pdf import unshare_forms
                                announce('check repeated page parts')
                                unshared=work/'unshared-forms.pdf'
                                outcome=unshare_forms(engine_input,unshared,cancel=cancel)
                                if outcome.get('status')!='not-needed':processor_results.append(outcome)
                                if outcome.get('status') in ('pass','partial') and unshared.is_file():tag_source=unshared
                            announce('tag locally');raw=work/'tagged.pdf'
                            outcome=tag(tag_source,raw,config,work/'engine',cancel=cancel)
                            processor_results.append({'name':'engine',**outcome})
                            if outcome.get('status')!='completed' or not raw.is_file():raise RuntimeError('Tagging did not complete; inspect its recorded outcome.')
                            if config.preserve_painting:
                                from .preservation import preserve_painting
                                announce('restore only proven original painting operations')
                                restored=work/'preserved.pdf'
                                outcome=preserve_painting(tag_source,raw,restored,allow_tag_regrouping=config.allow_tag_regrouping)
                                processor_results.append({'name':'preserve-painting',**outcome})
                                if outcome.get('status') in ('pass','completed') and restored.is_file():raw=restored
                        if not usable or config.remove_cidset:
                            from .designed_pdf import repair_tagged_output
                            announce('repair structure links and optional font lists')
                            repaired=work/'tagged-repairs.pdf'
                            outcome=repair_tagged_output(raw,repaired,remove_cidset=config.remove_cidset,engine_made=not usable,cancel=cancel)
                            if outcome.get('status')!='not-needed':processor_results.append(outcome)
                            if outcome.get('status')=='pass' and repaired.is_file():raw=repaired
                        from .designed_pdf import repair_author_tags
                        announce('make small fixes to the author tags')
                        roled=work/'author-tag-repairs.pdf'
                        outcome=repair_author_tags(raw,roled,cancel=cancel)
                        if outcome.get('status')!='not-needed':processor_results.append(outcome)
                        if outcome.get('status')=='pass' and roled.is_file():raw=roled
                        if config.repair_source_mappings:
                            from .fonts import repair_source_mappings
                            announce('repair only authoritative source character mappings')
                            if Path(raw).resolve()==source:
                                separate=work/'mapping-input.pdf';shutil.copyfile(raw,separate);raw=separate
                            mapped=work/'mapped.pdf';mapped_reference=work/'mapping-reference.pdf'
                            outcome=repair_source_mappings(source,raw,mapped,mapped_reference,cancel=cancel)
                            processor_results.append({**outcome,'name':'source-mappings'})
                            if outcome.get('status')=='pass' and mapped.is_file() and mapped_reference.is_file():
                                raw=mapped;reference=mapped_reference;reference_policy='authoritative-character-mapping'
                            else:raise UnsupportedDocument('The requested source character-mapping repair could not be proved; no substitute mapping was applied.')
                        announce('normalize metadata')
                        prepared_work=work/'prepared.pdf'
                        processor_results.append(normalize_catalog(raw,prepared_work,config.language,config.title))
                    _cancel(cancel)
                    cache.mkdir(parents=True,exist_ok=True)
                    if checkpoint.exists():
                        if sha(checkpoint)!=sha(prepared_work):raise ValueError('Prepared output differs from an existing exact checkpoint; use a new output directory.')
                    else:shutil.copyfile(prepared_work,checkpoint)
                    if reference:
                        cached_reference=cache/'reference.pdf'
                        if cached_reference.exists() and sha(cached_reference)!=sha(reference):raise ValueError('A preservation reference changed unexpectedly.')
                        if not cached_reference.exists():shutil.copyfile(reference,cached_reference)
                        reference=cached_reference
                    metadata={'source_sha256':input_hash,'settings_digest':settings_hash,'implementation_digest':code_hash,
                      'sha256':sha(checkpoint),'processors':processor_results,
                      'anchor_bundle':str(final),'reference':{'sha256':sha(reference),'policy':reference_policy} if reference else None}
                    write_json(cachemeta,metadata);report['checkpoint_provenance_sha256']=_metadata_digest(metadata)
                    prepared=checkpoint
                report['decision_source']={'path':str(prepared),'sha256':sha(prepared),'source_sha256':input_hash}
                decisions=collect_decisions(prepared,input_hash,inventory_profile=inventory_profile,cancel=cancel)
                supplied=supplied_decisions if supplied_decisions is not None else decisions
                applied=staging/'processed.pdf'
                outcome=apply_decisions(prepared,applied,supplied,input_hash,automatic_authorization=automatic_authorization,cancel=cancel)
                if form_route:
                    if sha(prepared)!=input_hash:raise ValueError('The interactive-form checkpoint differs from the unchanged original.')
                    from .structure_edits import verify_output
                    selected_form_edits=[item for item in supplied.get('decisions',[]) if item.get('status') in {'approved','auto-accepted'}
                        and item.get('value')!=item.get('current')]
                    proof=verify_output(prepared,applied,[],other_changes=selected_form_edits,cancel=cancel)
                    report['form_preservation']={'policy':'reviewed-form-1','status':proof['status'],
                        'source_sha256':input_hash,'checkpoint_sha256':sha(prepared),'output_sha256':sha(applied),
                        'graph_sha256':proof['graph_sha256'],
                        'scope':'Exact retained field/widget identities, values, flags, appearances, resources, tree ownership and unselected navigation; only accepted label/navigation and compatible typed metadata deltas.'}
                processor_results.append({'name':'approved-decisions',**outcome});processed=applied;decisions=supplied
                prior_assistance=[{'decision_id':item['id'],'origin':item['ai_origin']} for item in decisions.get('decisions',[])
                    if item.get('status') in ('approved','auto-accepted') and isinstance(item.get('ai_origin'),dict)]
                if prior_assistance:
                    report['data_sent'].update(processing='Local deterministic PDF processing; previously accepted AI drafts are attributed separately.',
                        prior_assistance=prior_assistance,scope='Zero model requests in this processing stage. Earlier model requests remain in the assistance/workspace records.')
            write_sidecar(decisions,staging/'decisions.json')
            if lineage_binding:
                processor_results.append({'name':'accepted-ocr-text-lineage','status':'completed',
                    'source_lineage':copy.deepcopy(report['source_lineage']),
                    'scope':'Separate corrected source; zero OCR or AI calls. All final gates and human reviews are fresh.'})
            assessed_hash=sha(processed)
            report['assessed_sha256']=assessed_hash
            announce('validate PDF/UA-1')
            report['gate1']=validate_pdf(processed,staging/'evidence/validator',config.validator_cli,config.java_home,
               timeout_seconds=config.validator_timeout_seconds,cancel=cancel,memory_limit_bytes=config.memory_limit_bytes,heap_mb=config.java_heap_mb)
            if mode=='check':report['baseline_gate1']=report['gate1']
            from .validation_delta import compare_rules
            report['validation_delta']=compare_rules(report['baseline_gate1'],report['gate1'])
            announce('check linked content and supported semantics')
            inspection=inspect_pdf(processed,cancel=cancel);report['inspection']=inspection
            report['gate2']=assess(inspection,source=baseline)
            declared={'id':'declared-document-kind','status':'fail' if config.document_kind in ('slides','equations') else 'pass',
                'blocking':True,'description':'Declared slide decks and equations require source/manual remediation.',
                'evidence':{'document_kind':config.document_kind},'scope':'Explicit input declaration; no general visual content detector.'}
            report['gate2']['checks'].append(declared)
            report['gate2']['blocking_checks'].append(declared['id'])
            if declared['status']=='fail':report['gate2']['blockers'].append(declared);report['gate2']['status']='fail'
            navigation=inspection.get('navigation',{})
            long_document=inspection.get('page_count',0)>=config.bookmark_min_pages
            for check in [
                {'id':'long-document-bookmarks','status':'pass' if navigation.get('bookmarks') else 'fail' if long_document else 'not-applicable',
                 'description':'Long documents require bookmarks.','evidence':{'threshold':config.bookmark_min_pages,'bookmarks':len(navigation.get('bookmarks',[]))}},
                {'id':'navigation-integrity','status':'fail' if navigation.get('errors') else 'pass',
                 'description':'Existing navigation targets must resolve.','evidence':{'errors':navigation.get('errors',[])}}]:
                check.update(blocking=True,scope='Mechanical navigation screen; semantic adequacy still needs review.')
                report['gate2']['checks'].append(check)
                report['gate2']['blocking_checks'].append(check['id'])
                if check['status']=='fail':report['gate2']['blockers'].append(check);report['gate2']['status']='fail'
            report['gate2']['profile']+='+navigation-1'
            if mode=='check':
                report['fidelity']={'status':'pass','before_sha256':input_hash,'after_sha256':input_hash,'scope':'Read-only check; identical input/output, no transformation or appearance claim.'}
            else:
                announce('compare every page and original navigation')
                navigation_kinds={'annotation-name','link-name','link-target','bookmark-entry','bookmark-additions'}
                navigation_changed=any(item.get('kind') in navigation_kinds and item.get('status')=='approved'
                    and item.get('value')!=item.get('current') for item in decisions.get('decisions',[]))
                navigation_options=({'navigation_review':decisions,'navigation_source':prepared,
                    'navigation_original_sha256':input_hash} if navigation_changed else {})
                raw_fidelity=compare_fidelity(source,processed,cancel=cancel,**navigation_options)
                report['fidelity']=raw_fidelity
                if reference:
                    exact=compare_fidelity(reference,processed,cancel=cancel,**navigation_options)
                    source_reference=compare_fidelity(source,reference,cancel=cancel)
                    visible=bool(source_reference.get('pages')) and all(all(p.get(k)=='pass' for k in ('render_status','dimensions_status','page_boxes_status','annotations_status')) for p in source_reference['pages'])
                    nav_ok=all(c['status']=='pass' for c in source_reference.get('checks',[]) if c['id']!='all-page-render-and-content')
                    proof_name={'ocr-added-text':'ocr','ocr-derived-character-mapping':'ocr-mappings'}.get(reference_policy,'source-mappings')
                    proved_processor=next((p for p in processor_results if p['name']==proof_name),None)
                    proof_ok=bool(proved_processor) and (proved_processor.get('preservation',{}).get('status')=='pass' if reference_policy=='ocr-added-text'
                        else proved_processor.get('visible_preservation',{}).get('status')=='pass' if reference_policy=='ocr-derived-character-mapping'
                        else proved_processor.get('status')=='pass')
                    passed=visible and nav_ok and proof_ok and exact.get('status')=='pass'
                    report['fidelity']={'status':'pass' if passed else 'fail','before_sha256':input_hash,'after_sha256':sha(processed),
                       'policy':reference_policy,'raw_source_comparison':raw_fidelity,'reference_comparison':exact,
                       'source_to_reference':source_reference,'reference_sha256':sha(reference),
                       'scope':'Exact full-page comparison to independently corrected source reference; raw source differences retained. No numeric drift tolerance was relaxed.'}
            if (sha(processed)!=assessed_hash or report['gate1'].get('input_sha256')!=assessed_hash
                or inspection.get('sha256')!=assessed_hash or report['fidelity'].get('after_sha256')!=assessed_hash):
                raise RuntimeError('The assessed PDF changed or assessment hashes disagree; no PDF can be published.')
            manual=[]
            manual.append({'id':'unsupported-content','category':'unsupported-content','subject':'Confirm supported document content',
               'detail':'Check for visual slide decks, untagged equations and other content that cannot be identified reliably from PDF objects. Reading status does not establish mathematical accessibility.',
               'required':True,'status':'pending','declared_kind':config.document_kind})
            for item in report['gate2'].get('manual_queue',[]):
                manual.append({**item,'required':True,'status':'pending'})
            for processor in processor_results:
                for index,item in enumerate(processor.get('semantic_review_required',[])):
                    identifier='regroup-'+hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()[:20]
                    manual.append({'id':identifier,'category':'tag-regrouping','subject':'Review a regrouped list or link','detail':json.dumps(item,ensure_ascii=False),
                       'required':True,'status':'pending','page':item.get('page')})
            for item in decisions.get('decisions',[]):
                if item.get('status')=='auto-accepted':
                    manual.append({'id':'automatic-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'automatic-decision-semantics','subject':'Review an automatically applied best guess',
                        'detail':'This '+item['kind']+' was applied under explicit best-guess authority, without human semantic review.',
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],'automatic_application':copy.deepcopy(item['automatic_application'])})
                if (item.get('kind') in ('figure-purpose','structure-role')
                    and item.get('status')=='approved' and item.get('value')!=item.get('current')):
                    decorative=item['kind']=='figure-purpose'
                    manual.append({'id':'structural-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'reading-order',
                        'subject':'Confirm selected decorative content' if decorative else 'Confirm the selected document or section role',
                        'detail':('Confirm this exact occurrence conveys no information needed to understand the document. '
                            'A meaningful logo or illustration should retain an appropriate description. Marking content decorative does not establish its purpose.'
                            if decorative else 'Confirm the selected existing container has the intended document or section meaning. '
                            'A role correction does not establish correct heading hierarchy or reading order.'),
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],
                        'evidence':{'kind':item['kind'],'element':item.get('element'),
                            'structure_path':item.get('structure_path'),'references':copy.deepcopy(item.get('references',[])),
                            'binding':copy.deepcopy(item['binding']),'previous_value':item['current'],'applied_value':item['value']}})
                if (item.get('kind') in ('page-language','passage-language')
                    and item.get('status')=='approved' and item.get('value')!=item.get('current')):
                    manual.append({'id':'local-language-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'metadata-meaning',
                        'subject':'Confirm the selected page language' if item['kind']=='page-language' else 'Confirm the selected passage language',
                        'detail':'Check this exact scope, inherited language and any explicit exceptions against its meaning and speech output. '
                            'A well-formed language tag or local marker agreement does not establish correct language, translation or pronunciation.',
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],
                        'evidence':{'kind':item['kind'],'element':item.get('element'),
                            'structure_path':item.get('structure_path'),'references':copy.deepcopy(item.get('references',[])),
                            'binding':copy.deepcopy(item['binding']),'previous_value':item['current'],'applied_value':item['value'],
                            'source_language_context':copy.deepcopy(item.get('language_context')),
                            'source_language_scope':copy.deepcopy(item.get('language_scope'))}})
                if (item.get('kind') in ('annotation-name','link-name','link-target','bookmark-entry','bookmark-additions')
                    and item.get('status')=='approved' and item.get('value')!=item.get('current')):
                    navigation_subject={'annotation-name':'Confirm the annotation description',
                        'link-name':'Confirm the alternative link name','link-target':'Confirm the selected link destination',
                        'bookmark-entry':'Confirm the bookmark name and destination',
                        'bookmark-additions':'Confirm the added bookmark hierarchy and coverage'}[item['kind']]
                    manual.append({'id':'navigation-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'reading-order','subject':navigation_subject,
                        'detail':'Check the exact name and destination against the surrounding content, intended purpose and navigation experience. '
                            'For bookmarks, check hierarchy and coverage of meaningful sections. A syntactically valid address, page target or label '
                            'does not establish reachability, appropriate meaning, keyboard access or accessibility.',
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],
                        'evidence':{'kind':item['kind'],'element':item.get('element'),
                            'structure_path':item.get('structure_path'),'references':copy.deepcopy(item.get('references',[])),
                            'binding':copy.deepcopy(item['binding']),'previous_value':item['current'],'applied_value':item['value'],
                            'source_navigation_context':copy.deepcopy(item.get('navigation_context'))}})
                if (item.get('kind') in ('semantic-role','reading-order','tree-move','semantic-list')
                    and item.get('status')=='approved' and item.get('value')!=item.get('current')):
                    tree_subject={'semantic-role':'Confirm the selected paragraph or list role',
                        'reading-order':'Confirm the selected tagged reading order',
                        'tree-move':'Confirm the moved text and its new context',
                        'semantic-list':'Confirm the list labels, bodies, numbering and order'}[item['kind']]
                    manual.append({'id':'semantic-tree-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'reading-order','subject':tree_subject,
                        'detail':'Check the selected existing text, its role and surrounding context against the intended meaning. '
                            'For lists, check label/body pairing, numbering and item order. For moves or reordering, check the full reading sequence '
                            'and retained language. Correct tree syntax and unchanged page appearance do not establish correct semantics or assistive-technology reading order.',
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],
                        'evidence':{'kind':item['kind'],'element':item.get('element'),
                            'structure_path':item.get('structure_path'),'references':copy.deepcopy(item.get('references',[])),
                            'binding':copy.deepcopy(item['binding']),'previous_value':item['current'],'applied_value':item['value'],
                            'source_tree_context':copy.deepcopy(item.get('tree_context'))}})
                if (item.get('kind')=='table-structure' and item.get('status')=='approved'
                    and item.get('value')!=item.get('current')):
                    manual.append({'id':'table-structure-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'table-meaning','subject':'Confirm the table headers, spans and summary',
                        'detail':'Check every selected cell role, header hierarchy and data-cell association against the visible table and intended meaning. '
                            'Verify row and column spans, row-group boundaries, identifiers and any summary. A complete logical grid, valid references and unchanged page images '
                            'do not establish correct header meaning, adequate descriptions or assistive-technology navigation.',
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],
                        'evidence':{'kind':item['kind'],'element':item.get('element'),
                            'structure_path':item.get('structure_path'),'references':copy.deepcopy(item.get('references',[])),
                            'binding':copy.deepcopy(item['binding']),'previous_value':item['current'],'applied_value':item['value'],
                            'source_table_context':copy.deepcopy(item.get('table_context'))}})
                if (item.get('kind')=='form-controls' and item.get('status')=='approved'
                    and item.get('value')!=item.get('current')):
                    manual.append({'id':'form-controls-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'form-meaning','subject':'Confirm the form labels, tooltips and navigation',
                        'detail':'Compare each accessible field name with its printed label and intended purpose, including instructions and required formats. '
                            'Check optional descriptions, field roles, values and states, and the complete logical navigation sequence including links. '
                            'A valid field tree, retained appearances and unchanged page images do not prove correct label meaning, keyboard operation or assistive-technology announcements.',
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],
                        'evidence':{'kind':item['kind'],'element':item.get('element'),
                            'structure_path':item.get('structure_path'),'references':copy.deepcopy(item.get('references',[])),
                            'binding':copy.deepcopy(item['binding']),'previous_value':item['current'],'applied_value':item['value'],
                            'source_form_context':copy.deepcopy(item.get('form_context'))}})
                if (item.get('kind')=='empty-tag-removal' and item.get('status')=='approved'
                    and item.get('value')!=item.get('current')):
                    manual.append({'id':'empty-tag-decision-'+hashlib.sha256(item['id'].encode()).hexdigest()[:20],
                        'category':'empty-tags','subject':'Confirm the reviewed empty-tag removal',
                        'detail':'Compare the original and changed structure around the removed tag. Confirm that no meaningful content, description, label or relationship was removed, that the parent retains its content and that the complete reading sequence remains appropriate. Unchanged page images do not establish correct semantics or assistive-technology behavior.',
                        'required':True,'status':'pending','decision_id':item['id'],'page':item.get('page'),
                        'context_sha256':item['context_sha256'],
                        'evidence':{'kind':item['kind'],'element':item.get('element'),
                            'structure_path':item.get('structure_path'),'references':copy.deepcopy(item.get('references',[])),
                            'binding':copy.deepcopy(item['binding']),'previous_value':item['current'],'applied_value':item['value'],
                            'source_empty_tag_context':copy.deepcopy(item.get('empty_tag_context'))}})
            if reference_policy=='authoritative-character-mapping':
                manual.append({'id':'source-character-corrections','category':'font-characters','subject':'Verify the sourced mathematical character corrections',
                   'detail':'Compare every recorded corrected glyph with its visible mathematical meaning and the retained mapping authority.','required':True,'status':'pending'})
            if reference_policy=='ocr-derived-character-mapping':
                mapped=next((p for p in processor_results if p['name']=='ocr-mappings'),{})
                manual.append({'id':'ocr-derived-character-maps','category':'font-characters',
                   'subject':'Verify the character maps derived from OCR',
                   'detail':'Missing Unicode maps of embedded fonts were inferred from an OCR reading of each page and applied without changing any page picture. '
                       'Compare the extracted or spoken text with the visible text on several pages, especially headings, numbers, symbols and unusual words. '
                       'The map is an inference from OCR, not an authority.'+(' Characters still unmapped in: '+', '.join(mapped.get('fonts_left_incomplete',[]))+'.' if mapped.get('fonts_left_incomplete') else ''),
                   'required':True,'status':'pending',
                   'evidence':{'fonts':copy.deepcopy(mapped.get('fonts',[])),'holdout':copy.deepcopy(mapped.get('holdout')),'evidence_words':mapped.get('evidence_words'),
                       'round_trip':copy.deepcopy(mapped.get('round_trip'))}})
            ocr_outcome=next((p for p in processor_results if p['name']=='ocr'),{})
            if ocr_outcome.get('reading_confidence'):
                from .ocr_confidence import review_item
                unsure_pages=review_item(ocr_outcome['reading_confidence'])
                if unsure_pages:manual.append(unsure_pages)
            covered_graphics=next((p for p in processor_results if p['name']=='covered-graphics'),{})
            if covered_graphics.get('status')=='pass' and covered_graphics.get('covered'):
                pieces=covered_graphics['covered']
                where='; '.join('page %d: %s'%(n,', '.join(sorted({p['kind'].replace('-',' ') for p in pieces if p['page']==n}))) for n in sorted({p['page'] for p in pieces}))
                manual.append({'id':'unmarked-graphics-marked-decorative','category':'figure-meaning',
                    'subject':'Confirm the graphics outside the existing tags are only decoration',
                    'detail':'The existing tags were kept. %d graphic%s the author did not tag (%s) %s marked as page decoration and left out of the reading. Look at %s and decide whether any of them carries meaning that needs a real description.'
                        %(len(pieces),' that' if len(pieces)==1 else 's that',where,'was' if len(pieces)==1 else 'were','it' if len(pieces)==1 else 'them'),
                    'required':True,'status':'pending','page':pieces[0]['page'],'evidence':{'covered':copy.deepcopy(pieces)}})
            author_written=next((p for p in processor_results if p['name']=='author-descriptions'),{})
            if author_written.get('descriptions'):
                items=author_written['descriptions']
                manual.append({'id':'author-descriptions-not-carried','category':'figure-meaning',
                    'subject':'Re-enter the picture descriptions written in the original tags',
                    'detail':'The original tags could not be kept, so the file was tagged again and these picture descriptions were not carried over: '
                        +'; '.join(('page %d: "%s"'%(i['page'],i['description'][:160])) if i.get('page') else '"%s"'%i['description'][:160] for i in items[:12])
                        +(' (and %d more)'%(len(items)-12) if len(items)>12 else '')+'. Give each matching figure its description again, checking that it still fits the picture.',
                    'required':True,'status':'pending','page':next((i['page'] for i in items if i.get('page')),None),'evidence':{'descriptions':copy.deepcopy(items)}})
            repairs=next((p for p in processor_results if p['name']=='tagged-repairs'),{})
            if repairs.get('status')=='pass' and repairs.get('set_aside'):
                aside=repairs['set_aside']
                manual.append({'id':'engine-placeholder-description-set-aside','category':'figure-meaning',
                   'subject':'Check content whose placeholder description was set aside',
                   'detail':'The tagging engine wrote a placeholder description ('+', '.join(sorted({'"'+a['description']+'"' for a in aside}))+') for content it never actually tagged, '
                       'so that structure link was removed and the description was set aside. Look at '+('page '+', '.join(str(n) for n in sorted({a['page'] for a in aside if a['page']})) if any(a['page'] for a in aside) else 'the document')+
                       ' and decide whether the drawing there needs a real description or is only decoration. The removed link does not establish what the content means.',
                   'required':True,'status':'pending','page':next((a['page'] for a in aside if a['page']),None),'evidence':{'set_aside':copy.deepcopy(aside)}})
            if lineage_binding:
                manual.append({'id':'ocr-text-corrections','category':'image-and-ocr',
                    'subject':'Review corrected OCR text against the original',
                    'detail':'This result uses a separate corrected source copy. Compare every accepted correction, remaining text, spacing and reading order with the retained original. Typed corrections do not approve overall OCR accuracy or accessibility.',
                    'required':True,'status':'pending'})
            if credential_binding:
                manual.append({'id':'content-credentials-derivative','category':'source-provenance',
                    'subject':'Review the separate copy without Content Credentials',
                    'detail':'The original and its exact credential payload remain retained. The original credential was not verified and does not apply to this separate working copy. Review source provenance and the complete new PDF; consent to credential removal is not accessibility approval.',
                    'required':True,'status':'pending','evidence':copy.deepcopy(report['credential_derivative'])})
            report['manual_review']={'items':manual,'complete':not manual}
            blockers=report['gate2'].get('blockers',[])
            for block in blockers:
                issue=_issue(block.get('id','supplemental-check'),block.get('description') or block.get('scope','Supplemental check needs attention.'),
                    block.get('fix_path','Review the original/source document or repair with a suitable PDF editor.'))
                if block.get('evidence'):issue['evidence']=copy.deepcopy(block['evidence'])
                report['residual_issues'].append(issue)
            if report['gate1']['status']!='pass':report['residual_issues'].append(_issue('pdfua','Strict PDF/UA-1 validation did not pass. See complete available validator evidence.'))
            if report['fidelity']['status']!='pass':report['residual_issues'].append(_issue('preservation','The result differs from the source in a required preservation check.','Keep the original; inspect differences and repair the source or engine before use.'))
            intact=_check(inspection,'content-linkage').get('status')=='pass' and _check(inspection,'content-coverage').get('status')=='pass'
            phantom=inspection.get('structure',{}).get('phantom_tree',False)
            if phantom or inspection.get('error') or _check(inspection,'content-linkage').get('status') in ('fail','error'):report['status']='failed'
            elif all(report[k].get('status')=='pass' for k in ('gate1','gate2','fidelity')):report['status']='candidate'
            else:report['status']='needs-manual'
            if mode=='fix' and report['fidelity'].get('status')=='pass' and intact and report['status']!='failed':
                filename='candidate.pdf' if report['status']=='candidate' else 'review-draft.pdf'
                target=staging/filename;shutil.copyfile(processed,target)
                if sha(target)!=assessed_hash:raise RuntimeError('The publication copy differs from the assessed PDF.')
                report['output']={'path':str(final/filename),'sha256':sha(target),'review_only':report['status']!='candidate'}
            elif mode=='check':report['assessed_artifact']={'path':str(source),'sha256':input_hash}
            if sha(source)!=input_hash:raise RuntimeError('The original changed during processing; results are invalid.')
            if sidecar and sha(sidecar)!=decision_hash:raise RuntimeError('Accepted decisions changed during processing; results are invalid.')
            if lineage_binding:
                _validated_ocr_lineage(lineage_binding,source,cancel=cancel)
                if sha(report['source_lineage']['path'])!=lineage_binding['sha256']:
                    raise RuntimeError('Retained OCR correction lineage changed during processing.')
            if credential_binding:
                from .credentials import validate_lineage_bindings
                validate_lineage_bindings(report['credential_lineage']['path'],source,report['credential_lineage']['sha256'],cancel)
            if report.get('output'):report['manual_review']['artifact_sha256']=report['output']['sha256']
            report['original_unchanged']=True
            _cancel(cancel)
    except Exception as exc:
        report['status']='needs-manual' if isinstance(exc,UnsupportedDocument) else 'failed';report['output']=None
        report['error']={'type':type(exc).__name__,'message':str(exc)[:1500]}
        report['residual_issues'].append(_issue('processing-error',str(exc)))
        # Never leave an invalid candidate artifact in the publishable bundle.
        for name in ('candidate.pdf','review-draft.pdf'):
            path=staging/name
            if path.is_file():path.unlink()
        if isinstance(exc,InterruptedError):report['cancelled']=True
    report['timings']['total_seconds']=round(time.monotonic()-started,4)
    # Intermediates remain clearly separated diagnostics; only the coherent bundle is published.
    work=staging/'work'
    if work.exists():
        diagnostic=outdir/'.diagnostics'/(name+'.'+uuid.uuid4().hex[:8])
        diagnostic.parent.mkdir(exist_ok=True);atomic_replace(work,diagnostic)
        report=_relative_evidence(report,work,diagnostic)
        report['diagnostics']=str(diagnostic)
    processed_tmp=staging/'processed.pdf'
    if processed_tmp.exists():processed_tmp.unlink()
    report=_relative_evidence(report,staging,final)
    # Fix paths inside validator evidence before computing the immutable manifest.
    for evidence in (staging/'evidence').rglob('*.json') if (staging/'evidence').exists() else []:
        try:
            value=json.loads(evidence.read_text(encoding='utf-8'));write_json(evidence,_relative_evidence(value,staging,final))
        except (ValueError,OSError):pass
    if not (staging/'decisions.json').exists():write_json(staging/'decisions.json',decisions)
    write_json(staging/'report.json',report)
    write_json(staging/'review.json',report['manual_review'])
    render_review_packet(report,decisions,staging/'review.html')
    files={str(file.relative_to(staging)).replace('\\','/'):sha(file) for file in staging.rglob('*') if file.is_file()}
    write_json(staging/'manifest.json',{'schema_version':'phase1-bundle-1','complete':True,'run_fingerprint':fingerprint,'files':files})
    if final.exists():raise FileExistsError('A concurrent run already published this result.')
    atomic_replace(staging,final)
    return report

def batch(source,outdir,config,*,recurse=False,resume=False,sidecar=None,mode='fix',cancel=None,progress=None):
    files=discover(source,outdir,recurse)
    if sidecar and len(files)!=1:raise ValueError('A supplied decision file applies to exactly one document.')
    results=[]
    for file in files:
        if cancel is not None and cancel.is_set():break
        try:result=process_file(file,outdir,config,mode=mode,sidecar=sidecar,resume=resume,cancel=cancel,progress=progress)
        except Exception as exc:result={'input':{'path':str(file)},'status':'failed','error':{'type':type(exc).__name__,'message':str(exc)}}
        results.append(result)
    summary={'schema_version':'phase1-batch-1','files_found':len(files),'processed':len(results),'cancelled':bool(cancel and cancel.is_set()),
             'results':[{'input':r['input'],'status':r['status'],'bundle_path':r.get('bundle_path'),'output':r.get('output'),'residual_issues':r.get('residual_issues',[]),'error':r.get('error')} for r in results]}
    write_json(Path(outdir)/'batch-summary.json',summary)
    return results,summary
