"""Nonsecret local configuration with explicit, reproducible runtime paths."""
from __future__ import annotations
from dataclasses import asdict,dataclass,fields
import hashlib,json,os
import math
from pathlib import Path
import tomllib

PROJECT=Path(__file__).resolve().parents[2]

@dataclass
class RuntimeConfig:
    project_root: Path = PROJECT
    java_home: Path = Path(os.environ.get('PHASE0_JAVA_HOME',r'C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot'))
    odl_jar: Path = PROJECT/'.venvs/odl/Lib/site-packages/opendataloader_pdf/jar/opendataloader-pdf-cli.jar'
    validator_cli: Path = PROJECT/'tools/verapdf/verapdf.bat'
    ocr_python: Path = PROJECT/'.venvs/ocr/Scripts/python.exe'
    tesseract_dir: Path = PROJECT/'tools/tesseract'
    timeout_seconds: int = 600
    validator_timeout_seconds: int = 180
    memory_limit_bytes: int = 4*1024**3
    java_heap_mb: int = 2048
    language: str = 'en-US'
    title: str | None = None
    engine: str = 'opendataloader'
    document_kind: str = 'unknown'
    preserve_painting: bool = True
    allow_tag_regrouping: bool = False
    repair_source_mappings: bool = False
    repair_ocr_mappings: bool = False
    remove_cidset: bool = False
    ocr_mode: str = 'off'
    ocr_profile: str = 'standard'
    bookmark_min_pages: int = 20
    # The Check for updates button: "manual" (only when clicked) or "off" (an IT department can turn it off here).
    update_check: str = 'manual'

    def public(self):
        return {key:str(value) if isinstance(value,Path) else value for key,value in asdict(self).items()}

    def digest(self):
        return hashlib.sha256(json.dumps(self.public(),sort_keys=True).encode()).hexdigest()

def load_config(path=None,**overrides):
    values={}
    if path:
        file=Path(path).resolve()
        with file.open('rb') as stream:raw=tomllib.load(stream)
        allowed={f.name for f in fields(RuntimeConfig)}
        values=raw.get('runtime',{})
        if set(raw)-{'runtime'} or set(values)-allowed:
            raise ValueError('Configuration supports only documented [runtime] settings; credentials/providers are not accepted.')
        for key in ('project_root','java_home','odl_jar','validator_cli','ocr_python','tesseract_dir'):
            if key in values:
                candidate=Path(values[key]);values[key]=(file.parent/candidate).resolve() if not candidate.is_absolute() else candidate
    values.update({k:v for k,v in overrides.items() if v is not None})
    result=RuntimeConfig(**values)
    for key in ('preserve_painting','allow_tag_regrouping','repair_source_mappings','repair_ocr_mappings','remove_cidset'):
        if type(getattr(result,key)) is not bool:raise ValueError(key+' must be a TOML boolean (true or false).')
    if result.engine!='opendataloader':raise ValueError('Only the evaluated opendataloader engine is available in Phase 1.')
    if result.document_kind not in ('unknown','reading','slides','equations'):raise ValueError('document_kind must be unknown, reading, slides, or equations.')
    if result.ocr_mode not in ('off','skip','textless','redo'):raise ValueError('OCR must be off, skip, textless, or redo; forced rasterization is unsupported.')
    if result.ocr_profile not in ('standard','table-lines','angles','turns'):raise ValueError('Scan layout must be standard, table-lines, angles, or turns.')
    if result.ocr_profile=='angles' and result.ocr_mode=='redo':raise ValueError('Tilted or vertical text requires the wholly scanned pages or scan-only OCR option; choose textless or skip.')
    if result.ocr_profile=='turns' and result.ocr_mode=='redo':raise ValueError('Sideways or upside-down pages require the wholly scanned pages or scan-only OCR option; choose textless or skip.')
    if result.repair_source_mappings and result.ocr_mode!='off':raise ValueError('Source-mapping repair and OCR must be separate operations in this release.')
    if result.repair_ocr_mappings and (result.ocr_mode!='off' or result.repair_source_mappings):raise ValueError('OCR-derived character-map repair must be its own operation: turn OCR and source-mapping repair off.')
    for key in ('timeout_seconds','validator_timeout_seconds'):
        value=getattr(result,key)
        if type(value) not in (int,float) or not math.isfinite(value) or value<=0:raise ValueError('Invalid finite positive '+key+'.')
    if type(result.memory_limit_bytes) is not int or result.memory_limit_bytes<64*1024**2:raise ValueError('Invalid integer memory budget.')
    if type(result.java_heap_mb) is not int or not 64<=result.java_heap_mb<=16384:raise ValueError('Invalid integer Java heap budget.')
    if type(result.bookmark_min_pages) is not int or result.bookmark_min_pages<1:raise ValueError('Invalid positive bookmark threshold.')
    if not isinstance(result.language,str) or not result.language.strip():raise ValueError('A language code is required.')
    if result.update_check not in ('manual','off'):raise ValueError('update_check must be manual or off.')
    return result

