"""Read-only bounded tool inventory and reproducibility lock snapshot."""
from pathlib import Path
import hashlib,json,platform,subprocess,sys

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parent

def probe(command):
    try:
        p=subprocess.run([str(c) for c in command],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
        return {'command':[str(c) for c in command],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'status':'completed' if p.returncode==0 else 'failed'}
    except Exception as e:return {'command':[str(c) for c in command],'status':'error','error':str(e)}

def main():
    destination=HERE/'evidence';destination.mkdir(exist_ok=True)
    result={'platform':platform.platform(),'architecture':platform.machine(),'python':sys.version,
            'environments':{},'downloads':[],'notes':['No global PATH, Python package, or registry changes were required.','OCRmyPDF17.13.1 was not available from the package index;17.13.0 is the installed and tested release.','Downloaded binary hashes are observed fingerprints; no claim of independent signature verification.']}
    for name in ['eval','odl','accesspdf','ocr']:
        python=PROJECT/'.venvs'/name/'Scripts/python.exe'
        frozen=probe([python,'-m','pip','freeze','--all'])
        (destination/(name+'-requirements.lock.txt')).write_text(frozen.get('stdout',''),encoding='utf-8')
        result['environments'][name]={'freeze':frozen,'consistency':probe([python,'-m','pip','check'])}
    result['java']=probe([Path(r'C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot\bin\java.exe'),'-version'])
    result['tesseract']=probe([PROJECT/'tools/tesseract/tesseract.exe','--version'])
    result['ghostscript']=probe([Path(r'C:\Program Files\gs\gs10.07.1\bin\gswin64c.exe'),'--version'])
    for path in [PROJECT/'tools/verapdf-greenfield-1.30.3-installer.zip',PROJECT/'tools/tesseract-5.5.3.exe',PROJECT/'tools/tesseract/tessdata/eng.traineddata',HERE/'external/thinkpython2.pdf']:
        if path.exists():result['downloads'].append({'path':str(path),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (destination/'environment.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Environment inventory saved; pip consistency:',{k:v['consistency']['status'] for k,v in result['environments'].items()})

if __name__=='__main__':main()
