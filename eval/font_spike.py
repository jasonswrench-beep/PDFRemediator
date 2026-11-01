"""Exact-source font-program and Unicode-map restoration controls for Phase 0.

No font substitution, inferred character mapping or package mutation is used.
Repairs require the original authoritative control, exact derivative hashes,
matching font metrics and a recorded bundled-font license.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import pikepdf
import pypdfium2 as pdfium

from inspect_pdf import compare_fidelity
from validate import validate_pdf

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


def plain(value):
    if value is None or isinstance(value,(bool,int,float,str)):
        return value
    if isinstance(value,pikepdf.Array):
        return [plain(item) for item in value]
    if isinstance(value,pikepdf.Stream):
        return {'decoded_stream_sha256':digest(value.read_bytes()),
                'dictionary':{str(key):plain(value[key]) for key in sorted(value.keys())}}
    if isinstance(value,pikepdf.Dictionary):
        return {str(key):plain(value[key]) for key in sorted(value.keys())}
    return str(value)


def font_signature(font):
    """Identity/metrics evidence independent of stream object numbers."""
    descriptor=font.FontDescriptor
    return {'base_font':str(font.BaseFont),'subtype':str(font.Subtype),
            'first_char':int(font.FirstChar),'last_char':int(font.LastChar),
            'widths':plain(font.Widths),
            'descriptor_metrics':{str(key):plain(descriptor[key]) for key in sorted(descriptor.keys())
                                  if str(key) not in ('/FontFile','/FontFile2','/FontFile3')},
            'font_program_sha256':digest(descriptor.FontFile2.read_bytes()) if '/FontFile2' in descriptor else None}


def painted_fonts(page):
    """Find font resources actually selected by text-showing instructions."""
    current=None;painted=set()
    for instruction in pikepdf.parse_content_stream(page):
        operator=str(instruction.operator)
        if operator=='Tf':
            current=str(instruction.operands[0])
        elif operator in ('Tj','TJ',"'",'"'):
            if current is None:
                raise ValueError('Text painting without a selected font')
            painted.add(current)
    return painted


def make_missing_program(reference, destination):
    with pikepdf.open(reference) as pdf:
        painted=painted_fonts(pdf.pages[0])
        matches=[key for key,font in pdf.pages[0].Resources.Font.items()
                 if str(key) in painted and str(font.BaseFont).endswith('BitstreamVeraSans-Roman')]
        if len(matches)!=1:
            raise ValueError('Expected exactly one painted regular Vera font')
        resource=str(matches[0]);font=pdf.pages[0].Resources.Font[resource]
        original=font.FontDescriptor.FontFile2
        removed={'resource':resource,'base_font':str(font.BaseFont),
                 'font_program_sha256':digest(original.read_bytes()),
                 'font_program_decoded_bytes':len(original.read_bytes()),
                 'stream_dictionary':plain(original.stream_dict),
                 'reference_font_signature':font_signature(font)}
        del font.FontDescriptor['/FontFile2']
        pdf.save(destination,deterministic_id=True)
    return removed


def restore_exact_program(deficient, authoritative, destination, plan):
    started=time.monotonic()
    if destination.exists() or destination.resolve() in (deficient.resolve(),authoritative.resolve()):
        raise ValueError('Repair output must be new and distinct')
    if sha(deficient)!=plan['deficient_input_sha256'] or sha(authoritative)!=plan['authoritative_sha256']:
        raise ValueError('Repair lineage hash mismatch')
    with pikepdf.open(deficient) as pdf,pikepdf.open(authoritative) as reference:
        resource=plan['resource']
        font=pdf.pages[0].Resources.Font[resource]
        original=reference.pages[0].Resources.Font[resource]
        if '/FontFile2' in font.FontDescriptor:
            raise ValueError('Repair is only for the explicitly missing exact program')
        actual,expected=font_signature(font),font_signature(original)
        actual['font_program_sha256']=expected['font_program_sha256']
        if actual!=expected or expected!=plan['reference_font_signature']:
            raise ValueError('Font identity, widths or descriptor metrics differ')
        stream=original.FontDescriptor.FontFile2
        if digest(stream.read_bytes())!=plan['font_program_sha256']:
            raise ValueError('Authoritative font program differs from declared source')
        # This is the only font-object edit: copy the exact authoritative stream
        # and its dictionary (including Length1); retain current widths/metrics.
        font.FontDescriptor.FontFile2=pdf.copy_foreign(stream)
        copied=font.FontDescriptor.FontFile2
        evidence={'decoded_font_program_sha256':digest(copied.read_bytes()),
                  'copied_stream_dictionary':plain(copied.stream_dict),
                  'descriptor_metrics_preserved':font_signature(font)==expected}
        pdf.save(destination,deterministic_id=True)
    evidence.update({'seconds':round(time.monotonic()-started,6),
                     'operation':'Restore exact FontFile2 stream and stream dictionary only',
                     'status':'completed','output_sha256':sha(destination)})
    return evidence


def restore_exact_maps(deficient,authoritative,destination):
    if destination.exists() or destination.resolve() in (deficient.resolve(),authoritative.resolve()):
        raise ValueError('Map repair output must be new and distinct')
    changes=[]
    with pikepdf.open(deficient) as pdf,pikepdf.open(authoritative) as reference:
        if len(pdf.pages)!=len(reference.pages):
            raise ValueError('Map fixture page-count lineage mismatch')
        touched=set()
        for index,(page,original_page) in enumerate(zip(pdf.pages,reference.pages)):
            for resource,font in page.Resources.Font.items():
                original=original_page.Resources.Font[resource]
                if font_signature(font)!=font_signature(original):
                    raise ValueError('Map restoration requires identical exact font programs and metrics')
                if tuple(font.objgen) in touched:
                    continue
                touched.add(tuple(font.objgen))
                before,after=font.ToUnicode.read_bytes(),original.ToUnicode.read_bytes()
                if before!=after:
                    changes.append({'page':index+1,'resource':str(resource),'base_font':str(font.BaseFont),
                                    'authoritative_program_sha256':font_signature(original)['font_program_sha256'],
                                    'wrong_map_sha256':digest(before),'authoritative_map_sha256':digest(after),
                                    'operation':'Copy exact original ToUnicode stream; infer no character mappings'})
                    font.ToUnicode=pdf.copy_foreign(original.ToUnicode)
        if not changes:
            raise ValueError('Expected known C-to-Z corrupted mapping control')
        pdf.save(destination,deterministic_id=True)
    return {'status':'completed','restored_maps':changes,'output_sha256':sha(destination)}


def extracted_text(path):
    document=pdfium.PdfDocument(str(path));pages=[]
    try:
        for index in range(len(document)):
            page=document[index]
            try:
                text=page.get_textpage()
                try:pages.append(text.get_text_range())
                finally:text.close()
            finally:page.close()
    finally:document.close()
    return pages


def preview(path,destination):
    document=pdfium.PdfDocument(str(path))
    try:
        page=document[0]
        try:
            bitmap=page.render(scale=1.25)
            try:
                image=bitmap.to_pil();image.save(destination);image.close()
            finally:bitmap.close()
        finally:page.close()
    finally:document.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'spikes/fonts')
    parser.add_argument('--java-home',type=Path,default=Path(r'C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot'))
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Refusing to overwrite prior font evidence')
    out.mkdir(parents=True,exist_ok=True)
    original=HERE/'corpus/tagged-control.pdf';wrong_map=HERE/'corpus/mis-mapped-font.pdf'
    original_hash,wrong_hash=sha(original),sha(wrong_map)
    license_source=HERE/'corpus/assets/LICENSE.txt'
    (out/'Bitstream-Vera-LICENSE.txt').write_bytes(license_source.read_bytes())
    missing=out/'missing-font-program.pdf';restored=out/'restored-exact-font.pdf'
    plan=make_missing_program(original,missing)
    plan.update({'deficient_input_sha256':sha(missing),'authoritative_sha256':original_hash,
                 'authoritative_pdf':str(original),'license_path':'Bitstream-Vera-LICENSE.txt',
                 'license_sha256':sha(license_source),'permission_basis':'Bitstream Vera bundled license permits use/copy/distribution subject to included notices; exact existing subset bytes restored, not renamed or substituted'})
    write(out/'exact-program-plan.json',plan)
    restoration=restore_exact_program(missing,original,restored,plan)
    fixed_map=out/'restored-exact-unicode.pdf'
    mapping=restore_exact_maps(wrong_map,original,fixed_map)
    validations={}
    for name,path in (('authoritative-control',original),('missing-program',missing),
                      ('restored-program',restored),('wrong-unicode',wrong_map),('restored-unicode',fixed_map)):
        result=validate_pdf(path,out/f'validation-{name}',PROJECT/'tools/verapdf/verapdf.bat',args.java_home)
        validations[name]={'status':result['status'],'counts':result.get('counts'),
                           'failed_rule_ids':[rule['rule_id'] for rule in result.get('failed_rules',[])],
                           'raw_summary':str(Path(result['summary_path']).relative_to(out))}
    comparisons={}
    for name,before,after in (('deficient-to-restored',missing,restored),
                             ('authoritative-to-restored',original,restored),
                             ('authoritative-to-wrong-unicode',original,wrong_map),
                             ('wrong-to-restored-unicode',wrong_map,fixed_map),
                             ('authoritative-to-restored-unicode',original,fixed_map)):
        result=compare_fidelity(before,after,dpi=96,max_changed_fraction=0,pixel_delta=0)
        write(out/f'fidelity-{name}.json',result)
        comparisons[name]={'status':result['status'],'all_pages_compared':len(result['pages']),
                           'render_statuses':[page['render_status'] for page in result['pages']],
                           'maximum_changed_pixel_fraction':max(page.get('changed_pixel_fraction',1) for page in result['pages']),
                           'text':result.get('text')}
    texts={name:extracted_text(path) for name,path in (('authoritative',original),('wrong-unicode',wrong_map),('restored-unicode',fixed_map))}
    write(out/'synthetic-text-evidence.json',texts)
    for name,path in (('missing-font',missing),('restored-font',restored),('restored-unicode',fixed_map)):
        preview(path,out/f'{name}-page1.png')
    expected=(validations['authoritative-control']['status']=='pass'
              and validations['missing-program']['status']=='fail'
              and validations['restored-program']['status']=='pass'
              and comparisons['authoritative-to-restored']['status']=='pass'
              and validations['wrong-unicode']['status']=='pass'
              and validations['restored-unicode']['status']=='pass'
              and comparisons['authoritative-to-wrong-unicode']['status']=='fail'
              and comparisons['authoritative-to-wrong-unicode']['render_statuses']==['pass']
              and comparisons['authoritative-to-restored-unicode']['status']=='pass'
              and texts['authoritative']!=texts['wrong-unicode']
              and texts['authoritative']==texts['restored-unicode']
              and sha(original)==original_hash and sha(wrong_map)==wrong_hash)
    result={'schema_version':'phase0-font-spike-1','status':'pass' if expected else 'fail',
            'script_sha256':sha(Path(__file__)),'reference_pdf':str(original),'reference_sha256':original_hash,
            'license_sha256':sha(license_source),'program_restoration':restoration,'map_restoration':mapping,
            'validations':validations,'fidelity_comparisons':comparisons,
            'original_inputs_unchanged':sha(original)==original_hash and sha(wrong_map)==wrong_hash,
            'mapping_semantic_control':{'wrong_map_is_syntactically_valid_but_incorrect':True,
                                        'machine_validation_misses_known_C_to_Z_error':validations['wrong-unicode']['status']=='pass',
                                        'restored_text_matches_exact_authoritative_control':texts['authoritative']==texts['restored-unicode']},
            'limitations':['Exact original permitted font subset/program bytes are required; no substitute or guessed embedding.',
                           'Reference font identity, widths and descriptor metrics must match; only the missing FontFile2 stream and its own dictionary are restored.',
                           'Restoration can change the deficient input appearance; comparison with the authoritative reference is a separate result.',
                           'Unicode restoration requires the authoritative exact original map and matching exact font program/metrics; it does not infer arbitrary mappings.',
                           'The real-book PDF/UA 7.21.7 Unicode mapping blocker remains unrepaired.',
                           'Synthetic exact-source controls do not establish general font repair or recognition accuracy.'],
            'recommendation':'Exact-source font embedding/map restoration is viable when authoritative permitted original resources and lineage are available. Otherwise retain the font/mapping blocker and request source-document repair.'}
    write(out/'results.json',result);print(json.dumps(result,indent=2))
    return 0 if expected else 1


if __name__=='__main__':
    raise SystemExit(main())
