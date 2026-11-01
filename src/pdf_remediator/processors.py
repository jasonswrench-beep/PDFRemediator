"""Small deterministic catalog repairs with no content or font substitution."""
from pathlib import Path
import re
import pikepdf

PLACEHOLDER=re.compile(r'^(?:untitled|\(anonymous\)|document\d*|microsoft\s+(?:word|powerpoint)\s*[-–].*)$',re.I)

def normalize_catalog(source,destination,language='en-US',title=None):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if source==destination:raise ValueError('Processor must write a separate checkpoint.')
    changes=[];warnings=[]
    with pikepdf.open(source) as pdf:
        root=pdf.Root
        if root.get('/StructTreeRoot') is not None:
            mark=root.get('/MarkInfo',pikepdf.Dictionary());mark['/Marked']=True;root['/MarkInfo']=mark
            changes.append('Set Marked for the existing tree; content linkage is independently checked.')
        if not str(root.get('/Lang','')).strip():
            root['/Lang']=language;changes.append('Set the configured document language.')
        preferences=root.get('/ViewerPreferences',pikepdf.Dictionary())
        preferences['/DisplayDocTitle']=True;root['/ViewerPreferences']=preferences
        if title:
            pdf.docinfo['/Title']=title;changes.append('Set the explicitly supplied title.')
        current=str(pdf.docinfo.get('/Title','')).strip()
        with pdf.open_metadata(set_pikepdf_as_editor=False,update_docinfo=False) as meta:
            if current and not PLACEHOLDER.fullmatch(current):meta['dc:title']=current
            else:warnings.append('A meaningful title must be supplied through --title or an approved decision.')
            if root.get('/StructTreeRoot') is not None:meta['pdfuaid:part']=1
        for page in pdf.pages:page.obj['/Tabs']=pikepdf.Name('/S')
        changes.extend(['Display the document title.','Synchronize meaningful title metadata.','Set page structural tab order.'])
        destination.parent.mkdir(parents=True,exist_ok=True)
        pdf.save(destination,deterministic_id=True)
    return {'name':'catalog','status':'completed','changes':changes,'warnings':warnings,
            'scope':'No appearance edits, font substitution, or inferred semantic decisions.'}
