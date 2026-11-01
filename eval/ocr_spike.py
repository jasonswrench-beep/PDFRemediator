"""Measure bounded OCR routes without forced rasterization or PDF/A conversion."""
from pathlib import Path
import argparse, hashlib, json, os, subprocess, time
import pypdfium2 as pdfium
from inspect_pdf import compare_fidelity, inspect_pdf

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parent

def text(path):
    doc=pdfium.PdfDocument(str(path));pages=[]
    try:
        for page in doc:
            tp=page.get_textpage()
            try:pages.append(tp.get_text_range())
            finally:tp.close();page.close()
    finally:doc.close()
    return pages

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compat',action='store_true',help='Use the isolated Phase 0 Windows hOCR text staging launcher')
    parser.add_argument('--root',type=Path,help='Separate evidence directory; default remains eval/spikes/ocr')
    parser.add_argument('--temp-root',type=Path,help='Override temporary directory; default is _temporary under the evidence directory')
    options=parser.parse_args()
    root=options.root.resolve() if options.root else HERE/'spikes/ocr'
    if options.compat and root.resolve()==(HERE/'spikes/ocr').resolve():
        raise ValueError('Compatibility evidence requires a separate --root; preserve stock results')
    root.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env['PYTHONUTF8']='1';env['OMP_THREAD_LIMIT']='1'
    env['PATH']=str(PROJECT/'tools/tesseract')+os.pathsep+env['PATH']
    env['TESSDATA_PREFIX']=str(PROJECT/'tools/tesseract/tessdata')
    # External OCR output files must be movable by this process. The desktop
    # sandbox's default temporary directory rejected those moves; a bounded
    # project-local directory works with the unchanged stock distribution.
    temp_root=options.temp_root.resolve() if options.temp_root else root/'_temporary'
    temp_root.mkdir(parents=True,exist_ok=True)
    env['TEMP']=str(temp_root);env['TMP']=str(temp_root)
    cases=[('scan-only','skip'),('mixed-same-page','skip'),('mixed-same-page','redo'),('tagged-control','skip')]
    results=[]
    for stem,mode in cases:
        folder=root/(stem+'-'+mode);folder.mkdir(exist_ok=True)
        source=HERE/'corpus'/(stem+'.pdf');output=folder/(stem+'.ocr.pdf')
        if output.exists():raise FileExistsError('OCR evidence already exists')
        entry=[str(HERE/'ocr_windows_compat.py')] if options.compat else ['-m','ocrmypdf']
        command=[str(PROJECT/'.venvs/ocr/Scripts/python.exe'),*entry,'--mode',mode,
                 '--output-type','pdf','--optimize','0','--jobs','1','-l','eng',str(source),str(output)]
        started=time.monotonic()
        try:
            run=subprocess.run(command,capture_output=True,env=env,timeout=120)
            (folder/'stdout.txt').write_bytes(run.stdout);(folder/'stderr.txt').write_bytes(run.stderr)
            record={'input':str(source),'mode':mode,'command':command,'returncode':run.returncode,
                    'seconds':round(time.monotonic()-started,4),'output_exists':output.exists()}
            record['temporary_directory']=str(temp_root)
            if options.compat:
                launcher=HERE/'ocr_windows_compat.py'
                record['experimental_compatibility']={'launcher':str(launcher),'sha256':hashlib.sha256(launcher.read_bytes()).hexdigest(),
                    'scope':'OCRmyPDF 17.13.0 generate_hocr output_text staging only; installed packages unchanged',
                    'production_fix':False}
            if output.exists():
                before=text(source);after=text(output)
                record['scan_anchor_present_after']='SCAN-ANCHOR-ALPHA' in '\n'.join(after)
                record['digital_anchor_preserved']='MIXED-DIGITAL-ANCHOR' in '\n'.join(after) if stem=='mixed-same-page' else None
                record['before_text_characters']=sum(map(len,before));record['after_text_characters']=sum(map(len,after))
                record['all_original_digital_text_present']=all(' '.join(t.split()) in ' '.join(after[i].split()) for i,t in enumerate(before))
                record['scan_omega_anchor_present_after']='SCAN-ANCHOR-OMEGA' in '\n'.join(after)
                record['after_text']=after
                record['fidelity']=compare_fidelity(source,output)
                record['inspection']=inspect_pdf(output)
                # OCR is expected to add selectable text; isolate visual preservation.
                record['all_page_render_preserved']=all(p['render_status']=='pass' for p in record['fidelity']['pages'])
                record['expected_added_text_requires_human_review']=mode=='redo' or stem=='scan-only'
        except subprocess.TimeoutExpired as exc:
            record={'input':str(source),'mode':mode,'status':'timeout','seconds':round(time.monotonic()-started,4)}
        (folder/'result.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
        results.append(record)
        print(stem,mode,'exit',record.get('returncode'),'scan text',record.get('scan_anchor_present_after'),
              'render',record.get('all_page_render_preserved'),flush=True)
    (root/'summary.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
