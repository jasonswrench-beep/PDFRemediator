"""Bounded catalog-only normalization for equal-footing engine comparison."""
from pathlib import Path
import pikepdf

VERSION = 'catalog-only-1.0'

def normalize(source, destination, title):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise ValueError('Normalization must write a separate artifact')
    changes = []
    with pikepdf.open(source) as pdf:
        root = pdf.Root
        if root.get('/StructTreeRoot') is not None:
            mark = root.get('/MarkInfo', pikepdf.Dictionary())
            mark['/Marked'] = True
            root['/MarkInfo'] = mark
            changes.append('Marked=true for existing tree; not evidence of real tagging')
        if not root.get('/Lang'):
            root['/Lang'] = 'en-US'
            changes.append('Lang=en-US for English-only evaluation corpus')
        preferences = root.get('/ViewerPreferences', pikepdf.Dictionary())
        preferences['/DisplayDocTitle'] = True
        root['/ViewerPreferences'] = preferences
        previous_title = str(pdf.docinfo.get('/Title', '')).strip()
        if not previous_title or previous_title.lower() in ('untitled','(anonymous)'):
            pdf.docinfo['/Title'] = title
        actual_title = str(pdf.docinfo.get('/Title', title))
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as meta:
            meta['dc:title'] = actual_title
            meta['pdfuaid:part'] = 1
        for page in pdf.pages:
            page.obj['/Tabs'] = pikepdf.Name('/S')
        changes.extend(['DisplayDocTitle=true','dc:title synchronized with meaningful Info title',
                        'staged pdfuaid:part=1 declaration for explicit UA1 testing', 'page Tabs=S'])
        destination.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(destination, deterministic_id=True)
    return {'version':VERSION,'changes':changes,'limitations':['No font or content/structure repair; UA identifier is not a conformance result.']}
