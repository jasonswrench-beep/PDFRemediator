"""Render one bounded local page in a separate native-library process."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .sidecar import file_sha256


PREVIEW_PROFILE = 'page-preview-static-forms-2'
FORM_RENDERING_POLICY = 'supported-static-widget-rendering-1'


def context_matches(data, expected, page, png_sha256):
    """Pure metadata validation; the review server never loads PDFium here."""
    if not isinstance(data, dict):return False
    rendering=data.get('form_rendering')
    if not isinstance(rendering,dict):return False
    fields,widgets=rendering.get('field_count'),rendering.get('widget_count')
    if type(fields) is not int or type(widgets) is not int:return False
    status=rendering.get('status')
    return (data.get('preview_profile')==PREVIEW_PROFILE and data.get('source_sha256')==expected
        and type(data.get('page')) is int
        and data.get('page')==page and data.get('png_sha256')==png_sha256
        and rendering.get('policy')==FORM_RENDERING_POLICY and rendering.get('source_sha256')==expected
        and rendering.get('javascript_platform')=='disabled-null' and rendering.get('xfa_disabled') is True
        and rendering.get('document_or_page_actions_invoked') is False
        and (status=='not-applicable' and fields==widgets==0 or status=='pass' and 1<=fields<=100 and fields<=widgets<=200))


def render(path,expected,page,png,context):
    import pypdfium2 as pdfium
    from .inspection import initialize_form_rendering
    path=Path(path);png=Path(png);context=Path(context)
    if len({path.resolve(),png.resolve(),context.resolve()})!=3:
        raise ValueError('Preview outputs must be distinct from the source and one another.')
    if path.suffix.lower()!='.pdf' or file_sha256(path)!=expected:raise ValueError('The preview source changed.')
    document=pdfium.PdfDocument(str(path))
    try:
        rendering=initialize_form_rendering(document,path)
        if not 1<=page<=len(document):raise ValueError('Page is outside this document.')
        sheet=document[page-1]
        try:
            width,height=sheet.get_size();scale=min(1.6,1800/max(width,height))
            bitmap=sheet.render(scale=scale,draw_annots=True,may_draw_forms=True)
            try:bitmap.to_pil().save(png)
            finally:bitmap.close()
            text=sheet.get_textpage()
            try:content=text.get_text_range()
            finally:text.close()
        finally:sheet.close()
        if file_sha256(path)!=expected:raise ValueError('The preview source changed during rendering.')
        data={'preview_profile':PREVIEW_PROFILE,'source_sha256':expected,'page':page,'png_sha256':file_sha256(png),
            'form_rendering':rendering,'text':content[:30000],'truncated':len(content)>30000,
            'scope':'Selectable page body text and proven static widget appearances for context; field-label meaning, keyboard behavior and screen-reader order remain unverified.'}
        if not context_matches(data,expected,page,data['png_sha256']):raise ValueError('The preview renderer did not prove the current complete rendering profile.')
        context.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    except Exception:
        png.unlink(missing_ok=True);context.unlink(missing_ok=True);raise
    finally:document.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('path');parser.add_argument('--sha256',required=True)
    parser.add_argument('--page',type=int,required=True);parser.add_argument('--png',required=True);parser.add_argument('--context',required=True)
    args=parser.parse_args();render(args.path,args.sha256,args.page,args.png,args.context)
