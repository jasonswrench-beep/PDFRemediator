"""Explicit /Lang edits on proven existing text and page-container scopes.

Language properties never translate or alter text, paint, order or navigation.
Page defaults are existing grouping-element properties, never Page /Lang.
"""
from collections import Counter
import copy
import json

import pikepdf

from .language_tags import is_language_tag, validate_language_tag
from . import structure_edits as graph

KINDS = {'passage-language','page-language'}
TEXT_ROLES = {'/P','/Span','/Lbl','/H','/H1','/H2','/H3','/H4','/H5','/H6',
    '/Caption','/Quote','/BlockQuote','/Code','/TD','/TH','/LBody'}
POLICY = 'explicit-local-language-1'


def _fail(message):
    from .sidecar import DecisionError
    raise DecisionError(message)


def value_for(language):
    return json.dumps({'language':language},sort_keys=True,separators=(',',':'),ensure_ascii=False)


def parse_value(value):
    try: data=json.loads(value)
    except (ValueError,TypeError):_fail('Choose an explicit language tag or inherit the parent language')
    if not isinstance(data,dict) or set(data)!={'language'}:
        _fail('A local language choice permits only its explicit language property')
    language=data['language']
    if language is not None:
        try:validate_language_tag(language)
        except ValueError as exc:_fail(str(exc))
    if value!=value_for(language):_fail('Local language choices must use the canonical saved language value')
    return language


def _direct(node):
    if '/Lang' not in node:return None,True
    raw=node['/Lang']
    if not isinstance(raw,pikepdf.String):return None,False
    return str(raw),True


def _source(kind='unknown',element=None,path=None):
    return {'kind':kind,'element':element,'structure_path':path}


def _context(node,ident,nodes,catalog):
    direct,typed=_direct(node)
    direct_typed=typed
    inherited=None;origin=_source();seen=set();parent=node.get('/P');found=False;ancestors=[]
    while graph._dict(parent) and graph._id(parent) in nodes and graph._id(parent) not in seen:
        pid=graph._id(parent);seen.add(pid)
        language,valid_type=_direct(parent)
        ancestors.append({'element':pid,'structure_path':nodes[pid]['path'],'direct':language,
            'direct_valid':valid_type and (language is None or is_language_tag(language))})
        if '/Lang' in parent and not found:
            inherited=language;origin=_source('structure',pid,nodes[pid]['path'])
            typed=typed and valid_type;found=True
        parent=parent.get('/P')
    if not found:
        inherited,valid_type=_direct(catalog)
        origin=_source('document',None,None) if '/Lang' in catalog else _source()
        typed=typed and valid_type
    effective=direct if '/Lang' in node else inherited
    effective_source=_source('structure',ident,nodes.get(ident,{}).get('path')) if '/Lang' in node else origin
    return {'policy':POLICY,'direct':direct,'direct_valid':direct_typed and (direct is None or is_language_tag(direct)),
        'inherited':inherited,'inherited_valid':is_language_tag(inherited),
        'inherited_source':origin,'effective':effective,'effective_valid':is_language_tag(effective),
        'effective_source':effective_source,'ancestors':ancestors},typed


def _leaf(value,depth=0):
    if depth>30:return False
    if isinstance(value,int):return not isinstance(value,bool) and value>=0
    if isinstance(value,pikepdf.Array):return bool(value) and all(_leaf(v,depth+1) for v in value)
    return (graph._dict(value) and '/MCID' in value and '/K' not in value and '/Stm' not in value
        and str(value.get('/Type','/MCR'))=='/MCR' and isinstance(value['/MCID'],int)
        and not isinstance(value['/MCID'],bool) and value['/MCID']>=0)


def _descendant(ident,ancestor,nodes):
    seen=set()
    while ident in nodes and ident not in seen:
        if ident==ancestor:return True
        seen.add(ident);ident=graph._id(nodes[ident]['parent'])
    return False


def _replacement_ancestor(node):
    seen=set()
    while graph._dict(node) and graph._id(node) not in seen:
        seen.add(graph._id(node))
        if '/ActualText' in node:return True
        node=node.get('/P')
    return False


def _page_language_marks(page,number,cancel=None):
    """Classify only direct-page text; unsupported language precedence is explicit."""
    text=set();bad=set();stack=[];errors=[]
    for index,ins in enumerate(pikepdf.parse_content_stream(page)):
        if index%256==0:graph._tick(cancel)
        operands,op=ins.operands,str(ins.operator)
        if op in {'BMC','BDC'}:
            props=operands[1] if op=='BDC' and len(operands)==2 else None
            if isinstance(props,pikepdf.Name):props=page.resources.get('/Properties',{}).get(str(props))
            raw=props.get('/MCID') if graph._dict(props) else None
            mcid=raw if isinstance(raw,int) and not isinstance(raw,bool) and raw>=0 else None
            stack.append({'mcid':mcid,'artifact':bool(operands and str(operands[0])=='/Artifact'),
                'override':graph._dict(props) and any(k in props for k in ('/Lang','/ActualText')),
                'invalid_mcid':raw is not None and mcid is None})
        elif op=='EMC':
            if stack:stack.pop()
            else:errors.append('Unbalanced content marking prevents a language scope')
        elif op in {'Tj','TJ',"'",'"','Do'}:
            if any(x['artifact'] for x in stack):continue
            keys=[(number,'page',x['mcid']) for x in stack if x['mcid'] is not None]
            if op=='Do':
                obj=page.resources.get('/XObject',{}).get(str(operands[0])) if operands else None
                if isinstance(obj,pikepdf.Stream) and obj.get('/Subtype')==pikepdf.Name.Form:bad.update(keys)
                continue
            text.update(keys)
            if len(keys)!=1 or any(x['override'] or x['invalid_mcid'] for x in stack):bad.update(keys)
            if not keys:errors.append('Unowned page text prevents complete page language coverage')
    if stack:errors.append('Unbalanced content marking prevents a language scope')
    return text,bad,errors


def _analyse(pdf,cancel=None,analysis=None):
    from .inspection import _structure,_page_content
    nodes,arrays,global_problems,snapshot,root=analysis or graph._analyse(pdf,cancel)
    if root is None:return {},{},snapshot
    pages={graph._id(p.obj):i for i,p in enumerate(pdf.pages,1)}
    evidence,owners,objects,_,parent_tree=_structure(pdf,pages)
    incoming=Counter(r for v in [snapshot['root'],snapshot['info'],*snapshot['objects'].values()] for r in graph._references(v))
    pkey_uses=Counter(p.obj.get('/StructParents') for p in pdf.pages
        if isinstance(p.obj.get('/StructParents'),int) and not isinstance(p.obj.get('/StructParents'),bool))
    page_info={}
    for number,page in enumerate(pdf.pages,1):
        graph._tick(cancel)
        content,definitions,painted=_page_content(page,number,owners,parent_tree,{})
        text,bad,mark_errors=_page_language_marks(page,number,cancel)
        reasons=list(global_problems)+mark_errors
        if content['errors'] or content['duplicate_mcids'] or content['parent_tree_failures'] or content['counts'].get('uncovered_paints',0):
            reasons.append('All real page content and ParentTree ownership must be resolved before page language can be changed')
        page_info[number]={'keys':set(painted),'text':text,'bad':bad,'definitions':definitions,
            'painted':painted,'limits':sorted(set(reasons)),'object_references':[
                r for r in evidence['object_references'] if r.get('page') in {None,number}],
            'annotations':list(page.obj.get('/Annots',[])),'object_owners':objects,'parent_tree':parent_tree}
    object_scopes={}
    for ref in evidence['object_references']:object_scopes.setdefault(ref['element'],[]).append(ref.get('page'))
    for ident,rec in nodes.items():
        own_pages={r.get('page') for r in rec['refs'] if r.get('page') is not None}
        if rec.get('page') is not None:own_pages.add(rec['page'])
        own_pages.update(n for n in object_scopes.get(ident,[]) if n is not None)
        children=rec['node'].get('/K');children=list(children) if isinstance(children,pikepdf.Array) else [children]
        has_children=any(graph._dict(child) and '/S' in child for child in children)
        rec['subtree_pages']=own_pages
        rec['unresolved_leaf']=not has_children and not rec['refs'] and not object_scopes.get(ident)
        if '/Pg' in rec['node'] and graph._id(rec['node']['/Pg']) not in pages:rec['unresolved_leaf']=True
        if any(n is None for n in object_scopes.get(ident,[])):rec['unresolved_leaf']=True
    for ident,rec in reversed(list(nodes.items())):
        parent=nodes.get(graph._id(rec['parent']))
        if parent is not None:
            parent['subtree_pages'].update(rec['subtree_pages'])
            parent['unresolved_leaf']=parent['unresolved_leaf'] or rec['unresolved_leaf']
    for ident,rec in nodes.items():
        node=rec['node'];ctx,typed=_context(node,ident,nodes,pdf.Root)
        rec['language_context']=ctx
        rec['language_limits']=list(global_problems)
        if not typed:rec['language_limits'].append('A non-string language property in this scope needs source repair')
        if _replacement_ancestor(node):rec['language_limits'].append('Replacement text in this scope or an ancestor needs source review before local language changes')
        refs=rec['refs'];keys=[(r.get('page'),r.get('stream'),r.get('mcid')) for r in refs]
        if rec['role'] in TEXT_ROLES:
            limits=list(rec['language_limits'])
            if not _leaf(node.get('/K')) or not refs or len(set(r.get('page') for r in refs))!=1 or any(r.get('stream')!='page' or r.get('page') not in page_info for r in refs):
                limits.append('Passage language requires one existing leaf text element on one known page; shared, multipage and Form content remain read-only')
            if len(keys)!=len(set(keys)) or incoming[ident]!=1+len(refs):
                limits.append('The passage has repeated ownership or another inbound reference')
            for r,key in zip(refs,keys):
                number=r.get('page')
                if number not in page_info:continue
                info=page_info[number];page=pdf.pages[number-1];mcid=r.get('mcid');pkey=page.obj.get('/StructParents')
                values=arrays.get(pkey) if isinstance(pkey,int) and not isinstance(pkey,bool) else None
                if (info['definitions'].get(key)!=1 or owners.get(key)!=[ident] or key not in info['text']
                    or not isinstance(values,pikepdf.Array) or not isinstance(mcid,int) or isinstance(mcid,bool)
                    or not 0<=mcid<len(values) or graph._id(values[mcid])!=ident or pkey_uses[pkey]!=1):
                    limits.append('The passage must have exact uniquely owned text and ParentTree references')
                if key in info['bad']:
                    limits.append('Inline language/replacement properties, nested ownership or Form content require source repair')
            rec['passage_limits']=sorted(set(limits))
        elif rec['role'] in graph.GROUP_ROLES:
            children=node.get('/K');limits=list(rec['language_limits'])
            if not isinstance(children,pikepdf.Array) or not children or any(not graph._dict(c) or '/S' not in c for c in children):
                limits.append('Page language requires a nonempty grouping container with existing structure children')
            if isinstance(children,pikepdf.Array) and incoming[ident]!=len(children)+1:
                limits.append('The page container has another owner outside its existing structure relationships')
            rec['page_limits']=sorted(set(limits))
    return nodes,page_info,snapshot


def _row(kind,ident,rec,page,refs,limits,scope,ctx=None):
    context=ctx or rec['language_context']
    display={'structural_eligible':not limits,'structural_limitations':sorted(set(limits)),
        'context_text':str(rec.get('node',{}).get('/T',''))[:500] if rec.get('node') is not None else '',
        'context_text_source':'Existing tagged language scope; compare the complete passage with the page.',
        'language_context':context,'language_scope':scope}
    fingerprint=graph._digest({'kind':kind,'element':ident,'path':rec.get('path'),'references':refs,'display':display})
    current=value_for(context['direct'])
    return {'id':f'language:{kind}:{ident or "page"}:{page}:{fingerprint[:16]}','kind':kind,'page':page,
        'element':ident,'structure_path':rec.get('path'),'references':refs,'context_sha256':fingerprint,
        'current':current,'value':current,'status':'pending',**display}


def inventory(pdf,*,cancel=None,analysis=None,proof_unavailable=False,base_rows=(),base_targets=None,text_contexts=None):
    from .sidecar import DecisionError
    targets={};rows=[]
    try:
        if proof_unavailable:_fail('The complete source graph proof is unavailable')
        nodes,page_info,_=_analyse(pdf,cancel,analysis)
    except InterruptedError:raise
    except (DecisionError,pikepdf.PdfError,RuntimeError,ValueError,TypeError,KeyError,AttributeError):
        nodes={};page_info={}
        for row in base_rows:
            if row.get('kind') not in {'heading-tag','table-header'}:continue
            node=(base_targets or {}).get(row.get('element'))
            if node is None:continue
            direct,typed=_direct(node)
            ctx={'policy':POLICY,'direct':direct,'direct_valid':typed and (direct is None or is_language_tag(direct)),
                'inherited':None,'inherited_valid':False,'inherited_source':_source(),
                'effective':direct,'effective_valid':typed and is_language_tag(direct),'effective_source':_source()}
            scope={'kind':'passage','page':row.get('page'),'target_element':row['element'],
                'coverage':{'known_references':len(row.get('references',[])),'page_real_references':0,'complete_page':False},
                'descendant_overrides':[],'limits':['The complete local-language graph and ownership proof is unavailable; existing processing remains available']}
            record={'node':node,'path':row.get('structure_path'),'language_context':ctx}
            rows.append(_row('passage-language',row['element'],record,row.get('page'),row.get('references',[]),scope['limits'],scope))
        for number in range(1,len(pdf.pages)+1):
            direct,typed=_direct(pdf.Root)
            ctx={'policy':POLICY,'direct':None,'direct_valid':True,'inherited':direct,
                'inherited_valid':typed and is_language_tag(direct),'inherited_source':_source('document'),
                'effective':direct,'effective_valid':typed and is_language_tag(direct),'effective_source':_source('document')}
            limits=['The complete local-language graph and ownership proof is unavailable; existing processing remains available']
            scope={'kind':'page','page':number,'target_element':None,
                'coverage':{'known_references':0,'page_real_references':0,'complete_page':False},
                'descendant_overrides':[],'limits':limits}
            rows.append(_row('page-language',None,{'path':None,'language_context':ctx},number,[],limits,scope))
        return rows,targets,[]
    for ident,rec in nodes.items():
        if 'passage_limits' not in rec:continue
        refs=rec['refs'];pages=sorted({r.get('page') for r in refs if isinstance(r.get('page'),int)})
        page=pages[0] if len(pages)==1 else rec['page']
        scope={'kind':'passage','page':page,'target_element':ident,
            'coverage':{'known_references':len(refs),'page_real_references':len(page_info.get(page,{}).get('keys',[])),'complete_page':False},
            'descendant_overrides':[],'limits':rec['passage_limits']}
        row=_row('passage-language',ident,rec,page,refs,rec['passage_limits'],scope)
        if text_contexts and not row['context_text']:
            snippets=[text_contexts.get((r['page'],r['mcid']),'') for r in refs if r.get('stream')=='page']
            if snippets and all(snippets):
                row['context_text']=' '.join(snippets)[:500]
                row['context_text_source']='MCID-matched selectable text (bounded snippet; inspect the whole passage).'
                row['context_sha256']=graph._digest({k:v for k,v in row.items() if k not in {'id','value','status','context_sha256'}})
                row['id']=f'language:passage-language:{ident}:{page}:{row["context_sha256"][:16]}'
        rows.append(row);targets[ident]=rec['node']
    for page,info in page_info.items():
        candidates=[]
        for ident,rec in nodes.items():
            if 'page_limits' not in rec:continue
            refs=rec['refs'];keys={(r.get('page'),r.get('stream'),r.get('mcid')) for r in refs}
            if not keys or keys!=info['keys'] or any(r.get('page')!=page or r.get('stream')!='page' for r in refs):continue
            descendants={key for key in nodes if _descendant(key,ident,nodes)}
            # A container's object-only descendants need a known matching page;
            # source forms and ambiguous references are already global limits.
            object_problem=any(r.get('page')!=page or r.get('element') not in descendants
                for r in info['object_references'])
            for annotation in info['annotations']:
                owner=info['object_owners'].get(graph._id(annotation),[])
                key=annotation.get('/StructParent') if graph._dict(annotation) else None
                if (len(owner)!=1 or owner[0] not in descendants or not isinstance(key,int)
                    or isinstance(key,bool) or graph._id(info['parent_tree'].get(key))!=owner[0]):object_problem=True
            for did in descendants:
                node=nodes[did]['node'];k=node.get('/K');items=list(k) if isinstance(k,pikepdf.Array) else [k]
                for child in items:
                    if graph._dict(child) and str(child.get('/Type'))=='/OBJR':
                        pg=child.get('/Pg',node.get('/Pg'))
                        if graph._id(pg)!=graph._id(pdf.pages[page-1].obj):object_problem=True
            limits=rec['page_limits']+info['limits']
            if rec['subtree_pages']!={page} or rec['unresolved_leaf']:
                limits.append('Every descendant language scope must resolve exclusively to this page; cross-page or objectless content needs source repair')
            if info['bad']:limits.append('Inline language/replacement or Form content prevents a proven page default')
            if not info['text']:limits.append('No resolved real text needs a page language default')
            if object_problem:limits.append('Object-only content crosses or cannot resolve the page boundary')
            if any('/ActualText' in nodes[d]['node'] for d in descendants):limits.append('A descendant replacement-text scope needs individual source review')
            overrides=[]
            for did in sorted(descendants):
                if did==ident:continue
                node=nodes[did]['node']
                if '/Lang' in node:
                    language,typed=_direct(node)
                    if not typed:limits.append('A descendant has a non-string language property')
                    overrides.append({'element':did,'structure_path':nodes[did]['path'],'language':language,'valid':typed and is_language_tag(language)})
            candidates.append((ident,rec,refs,sorted(set(limits)),overrides))
        chosen=None
        if candidates:
            ordered=sorted(candidates,key=lambda value:len(value[1]['path']))
            outer=ordered[0]
            if all(_descendant(c[0],outer[0],nodes) for c in ordered):chosen=outer
        if chosen:
            ident,rec,refs,limits,overrides=chosen
            scope={'kind':'page','page':page,'target_element':ident,
                'coverage':{'known_references':len(refs),'page_real_references':len(info['keys']),'complete_page':not limits},
                'descendant_overrides':overrides,'limits':limits}
            rows.append(_row('page-language',ident,rec,page,refs,limits,scope));targets[ident]=rec['node']
        else:
            limits=info['limits']+['No unique existing grouping container covers exactly this page; create or repair the source structure rather than inventing a page language scope']
            direct,_=_direct(pdf.Root);ctx={'policy':POLICY,'direct':None,'direct_valid':True,'inherited':direct,
                'inherited_valid':is_language_tag(direct),'inherited_source':_source('document'),
                'effective':direct,'effective_valid':is_language_tag(direct),'effective_source':_source('document')}
            scope={'kind':'page','page':page,'target_element':None,
                'coverage':{'known_references':0,'page_real_references':len(info['keys']),'complete_page':False},
                'descendant_overrides':[],'limits':sorted(set(limits))}
            rows.append(_row('page-language',None,{'path':None,'language_context':ctx},page,[],scope['limits'],scope))
    return rows,targets,[]


def validate_value(item):
    if item.get('kind') not in KINDS:_fail('Unsupported local language decision kind')
    if item.get('structural_eligible') is not True:_fail('This local language scope cannot be edited safely')
    return parse_value(item.get('value'))


def prepare_changes(pdf,items,*,cancel=None,text_contexts=None):
    """Validate every exact target against the original graph before any write."""
    rows,targets,_=inventory(pdf,cancel=cancel,text_contexts=text_contexts)
    fresh={row['id']:row for row in rows};plans=[];values={}
    for item in items:
        graph._tick(cancel);language=validate_value(item);row=fresh.get(item.get('id'))
        if row is None or any(item.get(key)!=row.get(key) for key in ('kind','element','page','structure_path','references','current','context_sha256',
            'structural_eligible','structural_limitations','context_text','context_text_source','language_context','language_scope')):
            _fail('The selected local language context changed')
        ident=item['element']
        if ident in values and values[ident]!=language:_fail('Conflicting local language choices target the same existing element')
        values[ident]=language
        if item['value']!=item['current']:plans.append({'item':item,'node':targets[ident],'language':language})
    return plans


def apply_prepared(plans,*,cancel=None):
    changed=[]
    for plan in plans:
        graph._tick(cancel);node=plan['node'];language=plan['language']
        if language is None:
            if '/Lang' in node:del node['/Lang']
        else:node['/Lang']=pikepdf.String(language)
        changed.append(plan['item']['id'])
    return changed


def prepare_expected(pdf,items,*,cancel=None):
    """Resolve the independent property oracle on the unchanged source graph."""
    rows,targets,errors=inventory(pdf,cancel=cancel)
    if errors:_fail('Local language oracle cannot resolve the source inventory')
    fresh={(r['kind'],r['element'],r['page']):r for r in rows}
    values={};plans=[]
    for item in items:
        graph._tick(cancel);language=validate_value(item);ident=item.get('element')
        row=fresh.get((item.get('kind'),ident,item.get('page')))
        if row is None or ident not in targets or any(item.get(k)!=row.get(k) for k in
            ('kind','element','page','structure_path','references','current','language_context','language_scope','structural_eligible','structural_limitations')):
            _fail('The original language oracle scope is absent or changed')
        if ident in values and values[ident]!=language:_fail('Conflicting language oracle targets')
        values[ident]=language
        plans.append((targets[ident],language))
    return plans


def apply_expected(plans,*,cancel=None):
    """Apply only the independently prepared exact /Lang deltas, with no rebind."""
    for node,language in plans:
        graph._tick(cancel)
        if language is None:
            if '/Lang' in node:del node['/Lang']
        else:node['/Lang']=pikepdf.String(language)
