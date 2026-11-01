"""Named, source-bound semantic tree edits without changing page programs.

These controls reorder existing tags, move bounded text leaves, and group
explicit existing text nodes into lists. They never invent text or MCIDs.
"""
from __future__ import annotations

from collections import Counter
import copy
import json
import re

import pikepdf

from . import structure_edits as graph
from .navigation_edits import canonical_snapshot

KINDS={'semantic-role','reading-order','tree-move','semantic-list'}
POLICY='reviewed-semantic-tree-1'
LIMITS={'children':100,'list_items':50,'move_parents':100,'payload_chars':100000}
NUMBERING=['None','Disc','Circle','Square','Decimal','UpperRoman','LowerRoman','UpperAlpha','LowerAlpha']
NEUTRAL={'/Document','/Part','/Sect','/Div'}
LEAF_ROLES={'/P','/Span','/Lbl','/LBody','/H'}|{'/H'+str(n) for n in range(1,100)}
_PROTECTED={'/ActualText','/Alt','/E','/C','/Ref','/ID','/AF'}


def _fail(message):
    from .sidecar import DecisionError
    raise DecisionError(message)


def _dict(value):return isinstance(value,pikepdf.Dictionary) and not isinstance(value,pikepdf.Stream)
def _int(value):return isinstance(value,int) and not isinstance(value,bool)
def canonical_value(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def _heading(role):return role=='/H' or isinstance(role,str) and re.fullmatch(r'/H[0-9]+',role) is not None
def _movable_role(role):return role in {'/P','/Span'} or _heading(role)


def _decode(value):
    if not isinstance(value,str) or len(value)>LIMITS['payload_chars'] or '\x00' in value:
        _fail('Semantic tree choices exceed their supported text payload')
    try:data=json.loads(value)
    except (ValueError,TypeError):_fail('Semantic tree choices require their saved structured value')
    if canonical_value(data)!=value:_fail('Semantic tree choices require canonical JSON without duplicate properties')
    return data


def _node_ids(records):return {record['element'] for record in records}


def parse_value(kind,value,context,*,current=None):
    source=context['source'];children=source['children']
    if kind=='semantic-role':
        if not isinstance(value,str) or value not in context.get('role_values',[]):
            _fail('Choose one of the source-bound semantic roles')
        return value
    data=_decode(value)
    if kind=='reading-order':
        if not isinstance(data,dict) or set(data)!={'children'} or not isinstance(data['children'],list):
            _fail('Reading order permits only its existing child sequence')
        if len(data['children'])!=len(children) or any(not isinstance(x,str) for x in data['children']) or Counter(data['children'])!=Counter(children):
            _fail('Reading order must use every existing child exactly once')
    elif kind=='tree-move':
        if not isinstance(data,dict) or set(data)!={'parent','index'} or not isinstance(data['parent'],str) or not _int(data['index']):
            _fail('Choose one existing destination parent and insertion position')
        if value==current:return data
        choices={item['element']:item for item in context['parent_choices']}
        destination=choices.get(data['parent'])
        if destination is None or not 0<=data['index']<=len(destination['children']):
            _fail('The destination or insertion position is outside the proven same-page choices')
        if data['parent']==source['parent']:_fail('Use reading order to reorder children within their existing parent')
    elif kind=='semantic-list':
        if not isinstance(data,dict) or set(data)!={'items','numbering'} or not isinstance(data['items'],list) or data['numbering'] not in NUMBERING:
            _fail('Choose explicit list items and a supported list-numbering style')
        if len(data['items'])>LIMITS['list_items']:_fail('Group at most 50 explicitly selected list items')
        if not data['items'] and data['numbering']!='None':_fail('An empty list plan must retain None numbering')
        candidates=_node_ids(context['list_candidates']);selected=[]
        for item in data['items']:
            if not isinstance(item,dict) or set(item)!={'label','body'} or not isinstance(item['body'],str) or item['label'] is not None and not isinstance(item['label'],str):
                _fail('Each list item needs one existing body and an optional existing label')
            selected.extend(([item['label']] if item['label'] is not None else [])+[item['body']])
        if any(ident not in candidates for ident in selected) or len(selected)!=len(set(selected)):
            _fail('Every selected label/body must be a distinct proven child of this parent')
        positions=sorted(children.index(ident) for ident in selected)
        if positions and positions!=list(range(positions[0],positions[-1]+1)):
            _fail('The selected list nodes must occupy one contiguous source-child range')
    else:_fail('Unsupported semantic tree decision kind')
    return data


def validate_value(item):
    context=item.get('tree_context')
    if item.get('kind') not in KINDS or item.get('structural_eligible') is not True:
        _fail('This semantic tree occurrence does not have a unique supported source context')
    if not isinstance(context,dict) or context.get('policy')!=POLICY or context.get('limits')!=LIMITS:
        _fail('Semantic tree capabilities or source context changed')
    if not _int(context.get('page_count')) or context['page_count']<1:_fail('Semantic tree page scope is unavailable')
    return parse_value(item['kind'],item.get('value'),context,current=item.get('current'))


def _leaf(value,depth=0):
    if depth>30:return False
    if _int(value):return value>=0
    if isinstance(value,pikepdf.Array):return bool(value) and all(_leaf(x,depth+1) for x in value)
    return (_dict(value) and '/MCID' in value and '/K' not in value and '/Stm' not in value
        and ('/Type' not in value or value['/Type']==pikepdf.Name.MCR)
        and _int(value['/MCID']) and value['/MCID']>=0)


def _children(node):
    raw=node.get('/K')
    if _dict(raw) and isinstance(raw.get('/S'),pikepdf.Name):
        return [graph._id(raw)] if graph._id(raw) is not None else None
    if not isinstance(raw,pikepdf.Array):return None
    if any(not _dict(child) or not isinstance(child.get('/S'),pikepdf.Name) or graph._id(child) is None for child in raw):return None
    return [graph._id(child) for child in raw]


def _child_values(node):
    raw=node.get('/K')
    return list(raw) if isinstance(raw,pikepdf.Array) else [raw]


def _list_attributes(value):
    return (_dict(value) and set(str(k) for k in value)<={'/O','/ListNumbering'} and value.get('/O')==pikepdf.Name.List
        and ('/ListNumbering' not in value or isinstance(value['/ListNumbering'],pikepdf.Name) and str(value['/ListNumbering']).lstrip('/') in NUMBERING))


def _ancestry_limits(ident,nodes,*,strict_attributes=False):
    limits=[];seen=set();start=ident
    while ident in nodes and ident not in seen:
        seen.add(ident);node=nodes[ident]['node']
        limits.extend(nodes[ident].get('base_limits',[]))
        if nodes[ident].get('has_objr'):
            limits.append('An annotation/object-reference ancestor protects this semantic scope.')
        if ident!=start and nodes[ident]['role'] not in NEUTRAL|{'/L','/LI','/LBody'}:
            limits.append('This ancestry contains a protected non-text semantic relationship.')
        if '/Lang' in node and not isinstance(node['/Lang'],pikepdf.String):
            limits.append('A non-string inherited language property needs source review.')
        if any(key in node for key in _PROTECTED):limits.append('Replacement text, alternatives, classes, IDs or associated relationships protect this ancestry.')
        if '/A' in node and (strict_attributes or not _list_attributes(node['/A'])):
            limits.append('Existing inherited attributes need source review before this semantic operation.')
        ident=graph._id(nodes[ident]['parent'])
    return limits


def _language(ident,nodes,catalog):
    seen=set()
    while ident in nodes and ident not in seen:
        seen.add(ident);node=nodes[ident]['node']
        if '/Lang' in node:return bytes(node['/Lang']) if isinstance(node['/Lang'],pikepdf.String) else ('invalid',str(node['/Lang']))
        ident=graph._id(nodes[ident]['parent'])
    value=catalog.get('/Lang')
    return bytes(value) if isinstance(value,pikepdf.String) else None if value is None else ('invalid',str(value))


def _summary(ident,nodes):
    rec=nodes[ident]
    return {'element':ident,'role':rec['role'].lstrip('/') if rec['role'] else '',
        'page':rec['semantic_page'],'parent':graph._id(rec['parent']),'index':rec['index'],
        'children':rec['children'] or [],'context_text':rec.get('text','')}


def _analyse(pdf,cancel=None,*,text_contexts=None):
    from .inspection import _structure,_page_content
    nodes,arrays,problems,snapshot,root=graph._analyse(pdf,cancel)
    if root is None:return [],{},snapshot
    pages={graph._id(page.obj):n for n,page in enumerate(pdf.pages,1)}
    evidence,owners,objrefs,_,parent_tree=_structure(pdf,pages)
    global_limits=list(problems)
    if not _dict(root) or '/Type' in root and root['/Type']!=pikepdf.Name.StructTreeRoot:
        global_limits.append('The structure root has an unsupported object type.')
    if pdf.is_encrypted or '/AcroForm' in pdf.Root or '/Perms' in pdf.Root:
        global_limits.append('Encrypted, signed and form documents require a separate supported repair workflow.')
    if any(isinstance(value,dict) and value.get('t')=='dict' and ('/ByteRange' in value['v'] or value['v'].get('/Type')=={'t':'name','v':'/Sig'}) for value in snapshot['objects'].values()):
        global_limits.append('Signed document bytes require a separate signing workflow.')
    incoming=Counter(ref for value in [snapshot['root'],snapshot['info'],*snapshot['objects'].values()] for ref in graph._references(value))
    root_children=_children(root)
    if graph._id(root) is None or root_children is None or incoming[graph._id(root)]!=1+len(root_children):
        global_limits.append('The structure root has additional inbound aliases or unsupported child ownership.')
    root_k=root.get('/K')
    if isinstance(root_k,pikepdf.Array) and graph._id(root_k) and incoming[graph._id(root_k)]!=1:
        global_limits.append('The structure root child array has an additional inbound alias.')
    try:_,parent_chains=graph._parent_arrays(root)
    except ValueError:
        parent_chains={};global_limits.append('ParentTree branch ownership cannot be independently proved.')
    parent_keys=Counter(page.obj.get('/StructParents') for page in pdf.pages if _int(page.obj.get('/StructParents')))
    page_info={}
    for number,page in enumerate(pdf.pages,1):
        graph._tick(cancel);info,definitions,painted=_page_content(page,number,owners,parent_tree,{})
        from .language_edits import _page_language_marks
        _,blocked,_=_page_language_marks(page,number,cancel)
        page_info[number]=(info,definitions,painted,blocked)
    own_refs={}
    for ref in evidence['references']:own_refs.setdefault(ref['element'],[]).append({key:ref[key] for key in ('page','stream','mcid')})
    object_owners={ref['element'] for ref in evidence['object_references']}
    for ident,rec in nodes.items():
        node=rec['node'];children=_children(node);rec['children']=children;rec['own_refs']=own_refs.get(ident,[])
        rec['index']=None
        parent_children=_children(rec['parent']) if _dict(rec['parent']) else None
        if parent_children is not None and ident in parent_children:rec['index']=parent_children.index(ident)
        elif graph._id(rec['parent'].get('/K'))==ident:rec['index']=0
        base=list(global_limits)
        if not _dict(node) or not isinstance(node.get('/S'),pikepdf.Name) or '/Type' in node and node['/Type']!=pikepdf.Name.StructElem:
            base.append('The source is not an ordinary named structure element.')
        if ident in object_owners:base.append('Annotation/object-reference elements are outside text-tree editing.')
        rec['has_objr']=ident in object_owners
        expected=1+len(children or [])+len(rec['own_refs'])
        if incoming[ident]!=expected:base.append('This element has additional inbound aliases or ambiguous ownership.')
        for raw in [node.get('/K')]:
            if graph._id(raw) and not (_dict(raw) and isinstance(raw.get('/S'),pikepdf.Name)) and incoming[graph._id(raw)]!=1:
                base.append('The child/content array has an additional owner.')
        rec['base_limits']=base
        refs=rec['own_refs'];keys=[(ref['page'],ref['stream'],ref['mcid']) for ref in refs]
        scopes={ref['page'] for ref in refs};leaf_limits=list(base)
        if not _leaf(node.get('/K')) or not refs or len(keys)!=len(set(keys)) or len(scopes)!=1 or any(ref['stream']!='page' for ref in refs):
            leaf_limits.append('This operation needs one uniquely owned text leaf on one direct page.')
        else:
            number=next(iter(scopes));info,definitions,painted,blocked=page_info[number]
            if info['errors'] or info['duplicate_mcids'] or any(definitions[key]!=1 or painted[key]<1 or owners.get(key)!=[ident] for key in keys):
                leaf_limits.append('The exact text MCIDs do not have unique painted ownership.')
            failed={(x['stream'],x['mcid']) for x in info['parent_tree_failures']}
            if any((ref['stream'],ref['mcid']) in failed for ref in refs):leaf_limits.append('ParentTree ownership does not match this text leaf.')
            if any(key in blocked for key in keys):leaf_limits.append('Form, mixed or replacement marked content prevents a direct text-tree scope.')
            parent_key=pdf.pages[number-1].obj.get('/StructParents')
            if not _int(parent_key) or parent_keys[parent_key]!=1:leaf_limits.append('The page StructParents key is not uniquely owned.')
            if _int(parent_key) and any(isinstance(carrier,pikepdf.Stream) or graph._id(carrier) and incoming[graph._id(carrier)]!=1 for carrier in parent_chains.get(parent_key,())):
                leaf_limits.append('A ParentTree branch, number array or value array has another owner or alias.')
        reference_limits=list(leaf_limits)
        if not refs or any(not (text_contexts or {}).get((ref['page'],ref['mcid'])) for ref in refs):
            leaf_limits.append('Complete unambiguous text-object evidence is unavailable; image, mixed, Form and bounded scopes stay read-only.')
        if not (rec['role'] in LEAF_ROLES or rec['role'] and re.fullmatch(r'/H[0-9]+',rec['role'])):
            leaf_limits.append('Only supported text-leaf roles are editable here.')
        rec['leaf_limits']=leaf_limits;rec['semantic_page']=next(iter(scopes)) if len(scopes)==1 else rec.get('page')
        rec['subtree_pages']=set(scopes);rec['subtree_safe']=not leaf_limits
        rec['tree_refs']=list(refs)
        rec['role_text_safe']=not leaf_limits and not any(key in node for key in _PROTECTED) and ('/A' not in node or _list_attributes(node['/A']))
        alt=node.get('/Alt')
        rec['order_safe']=(not leaf_limits or rec['role']=='/Figure' and not reference_limits
            and isinstance(alt,pikepdf.String) and bool(str(alt).strip()) and '/ActualText' not in node)
        rec['text']=' '.join((text_contexts or {}).get((ref['page'],ref['mcid']),'') for ref in refs).strip()[:500]
        if rec['role']=='/Figure' and isinstance(alt,pikepdf.String):rec['text']=str(alt)[:500]
    # Bottom-up proof for child-only containers, including every existing leaf.
    for ident,rec in reversed(list(nodes.items())):
        children=rec['children']
        if children is not None:
            for child in children:
                rec['subtree_pages'].update(nodes[child]['subtree_pages']);rec['tree_refs'].extend(nodes[child]['tree_refs'])
            rec['subtree_safe']=(not rec['base_limits'] and bool(children) and len(children)<=LIMITS['children']
                and (rec['role'] in NEUTRAL|{'/L','/LI','/LBody','/P','/Span'} or _heading(rec['role']))
                and all(nodes[child]['subtree_safe'] for child in children))
            rec['order_safe']=(not rec['base_limits'] and bool(children) and len(children)<=LIMITS['children']
                and (rec['role'] in NEUTRAL|{'/L','/LI','/LBody','/P','/Span'} or _heading(rec['role']))
                and all(nodes[child]['order_safe'] for child in children))
            text_container=rec['role'] in NEUTRAL|{'/L','/LI','/LBody','/P','/Span'} or _heading(rec['role'])
            rec['role_text_safe']=(not rec['base_limits'] and bool(children) and len(children)<=LIMITS['children']
                and text_container and all(nodes[child]['role_text_safe'] for child in children)
                and not any(key in rec['node'] for key in _PROTECTED)
                and ('/A' not in rec['node'] or _list_attributes(rec['node']['/A'])))
            rec['semantic_page']=next(iter(rec['subtree_pages'])) if len(rec['subtree_pages'])==1 else None
            rec['text']=' '.join(nodes[child]['text'] for child in children).strip()[:500]
        if '/Pg' in rec['node'] and graph._id(rec['node']['/Pg']) not in pages:rec['subtree_safe']=rec['order_safe']=rec['role_text_safe']=False
        if rec['semantic_page'] is None:rec['subtree_safe']=rec['order_safe']=rec['role_text_safe']=False
    rolemap=root.get('/RoleMap',{})
    def role_safe(role):return not _dict(rolemap) or '/'+role not in rolemap
    for ident,rec in nodes.items():
        values=[rec['role'].lstrip('/') if rec['role'] else '']
        if _heading(rec['role']) and role_safe('P'):
            values.append('P')
        parent=nodes.get(graph._id(rec['parent']))
        if not rec['leaf_limits'] and parent and (parent['role']=='/LI' or 'LI' in parent.get('role_values',[])):
            values.extend(role for role in ('Lbl','LBody') if role_safe(role))
        if rec['children'] and rec['subtree_safe'] and rec['role']=='/Div':
            if all(nodes[child]['role']=='/LI' for child in rec['children']) and role_safe('L'):values.append('L')
            if parent and parent['role']=='/L' and role_safe('LI'):values.append('LI')
        rec['role_values']=list(dict.fromkeys(values))
    # Local snippets come only from the already source-bound direct page MCIDs.
    # Text is informative context; it is never used to infer an operation.
    rows=[];targets={};graph_sha=graph._digest(snapshot)
    for ident,rec in nodes.items():
        graph._tick(cancel);node=rec['node'];children=rec['children'] or []
        base=list(rec['base_limits']);source=_summary(ident,nodes)
        context={'policy':POLICY,'page_count':len(pdf.pages),'source':source,
            'children':[_summary(child,nodes) for child in children], 'parent_choices':[],
            'list_candidates':[],'numbering_values':list(NUMBERING),'limits':dict(LIMITS),'role_values':rec['role_values']}
        refs=rec['tree_refs'];path=rec['path'];page=rec['semantic_page']
        def add(kind,current,limits,ctx=None):
            ctx=copy.deepcopy(ctx or context);fingerprint=graph._digest({'graph_sha256':graph_sha,'kind':kind,'element':ident,'context':ctx,'limits':sorted(set(limits))})
            row={'id':'tree:'+{'semantic-role':'role','reading-order':'order','tree-move':'move','semantic-list':'list'}[kind]+':'+ident,
                'kind':kind,'current':current,'value':current,'status':'pending','element':ident,'page':page,'structure_path':path,
                'references':copy.deepcopy(refs),'context_text':rec['text'],'context_text_source':'source-bound text-object snippets and existing Figure alternatives; no meaning inferred',
                'context_sha256':fingerprint,'structural_eligible':not limits,'structural_limitations':sorted(set(limits)),
                'allowed_values':rec['role_values'] if kind=='semantic-role' else [],'tree_context':ctx}
            rows.append(row);targets[row['id']]={'kind':kind,'record':rec,'nodes':nodes,'root':root,'pages':pages}
        if len(rec['role_values'])>1 or _heading(rec['role']):
            role_limits=base+_ancestry_limits(ident,nodes)
            if _heading(rec['role']) and not role_safe('P'):role_limits.append('The standard paragraph role is remapped in this source.')
            if rec['children'] is None:role_limits+=rec['leaf_limits']
            elif not rec['role_text_safe']:role_limits.append('Role correction needs a bounded same-page pure-text subtree with unique marked-content ownership.')
            add('semantic-role',source['role'],role_limits)
        if rec['children'] is not None and len(children)>=2:
            order_limits=base+_ancestry_limits(ident,nodes)
            if rec['role'] not in NEUTRAL|{'/L','/LI','/LBody'}:
                order_limits.append('Inline text and heading containers are retained as whole atoms; their internal children are not reordered.')
            if not rec['order_safe']:order_limits.append('Reading order needs a uniquely owned same-page tree of supported text nodes or described Figure atoms.')
            add('reading-order',canonical_value({'children':children}),order_limits)
        parent_id=source['parent'];parent=nodes.get(parent_id)
        if rec['children'] is None and _movable_role(rec['role']) and parent and parent['role'] in NEUTRAL:
            move_limits=rec['leaf_limits']+_ancestry_limits(ident,nodes,strict_attributes=True)
            if not parent['subtree_safe'] or len(parent['children'] or [])<2:move_limits.append('The original neutral parent must remain nonempty and have a proven child array.')
            choices=[]
            if not move_limits:
                for destination_id,destination in nodes.items():
                    if destination_id==parent_id or destination['role'] not in NEUTRAL or not destination['subtree_safe'] or destination['semantic_page']!=page:continue
                    if _ancestry_limits(destination_id,nodes,strict_attributes=True):continue
                    if _language(parent_id,nodes,pdf.Root)!=_language(destination_id,nodes,pdf.Root):continue
                    if len(destination['children'] or [])>=LIMITS['children']:continue
                    choices.append(_summary(destination_id,nodes))
            choices=choices[:LIMITS['move_parents']]
            if not choices:move_limits.append('No distinct neutral same-page parent preserves the inherited language and attributes.')
            ctx=copy.deepcopy(context);ctx['parent_choices']=choices
            add('tree-move',canonical_value({'parent':parent_id,'index':source['index']}),move_limits,ctx)
        if rec['children'] is not None and rec['role'] in NEUTRAL:
            candidates=[child for child in children if not nodes[child]['leaf_limits'] and (nodes[child]['role'] in {'/P','/Span','/Lbl','/LBody'} or _heading(nodes[child]['role']))
                and not _ancestry_limits(child,nodes,strict_attributes=True)]
            list_limits=base+_ancestry_limits(ident,nodes,strict_attributes=True)
            if not rec['subtree_safe'] or len(candidates)<1:list_limits.append('List grouping needs proven existing text siblings in one neutral same-page container.')
            if any(not role_safe(role) for role in ('L','LI','Lbl','LBody')):list_limits.append('A standard list role is remapped in this document.')
            ctx=copy.deepcopy(context);ctx['list_candidates']=[_summary(child,nodes) for child in candidates]
            add('semantic-list',canonical_value({'items':[],'numbering':'None'}),list_limits,ctx)
    return rows,targets,snapshot


def inventory(pdf,*,cancel=None,text_contexts=None):
    try:rows,targets,_=_analyse(pdf,cancel,text_contexts=text_contexts);return rows,targets,[]
    except (ValueError,RuntimeError,TypeError,KeyError) as exc:
        graph._tick(cancel)
        # A proof bound disables only these optional controls.
        reason='Semantic tree preservation proof is unavailable: '+str(exc)[:350]
        source={'element':'unavailable','role':'Document','page':None,'parent':None,'index':0,'children':[],'context_text':''}
        context={'policy':POLICY,'page_count':len(pdf.pages),'source':source,'children':[],
            'parent_choices':[],'list_candidates':[],'numbering_values':list(NUMBERING),'limits':dict(LIMITS),'role_values':[]}
        value=canonical_value({'items':[],'numbering':'None'})
        row={'id':'tree:list:unavailable','kind':'semantic-list','current':value,'value':value,'status':'pending',
            'element':'unavailable','page':None,'structure_path':'root/K','references':[],'context_text':'',
            'context_text_source':'no complete semantic tree proof','context_sha256':graph._digest({'context':context,'reason':reason}),
            'structural_eligible':False,'structural_limitations':[reason],'allowed_values':[],'tree_context':context}
        return [row],{},[]


def _final_roles_and_children(nodes,plans):
    roles={ident:rec['role'].lstrip('/') if rec['role'] else '' for ident,rec in nodes.items()}
    children={ident:list(rec['children']) for ident,rec in nodes.items() if rec['children'] is not None}
    for plan in plans:
        kind=plan['kind'];value=plan['value'];ident=plan['element']
        if kind=='semantic-role':roles[ident]=value
        elif kind=='reading-order':children[ident]=list(value['children'])
        elif kind=='tree-move':
            children[plan['source_parent']].remove(ident);children[value['parent']].insert(value['index'],ident)
        elif kind=='semantic-list' and value['items']:
            selected=[node for item in value['items'] for node in ([item['label']] if item['label'] else [])+[item['body']]]
            first=min(children[ident].index(node) for node in selected);children[ident]=[node for node in children[ident] if node not in selected]
            lid='semantic:new-list:'+ident;children[ident].insert(first,lid);roles[lid]='L';children[lid]=[]
            for n,item in enumerate(value['items']):
                iid='semantic:new-item:'+ident+':'+str(n);roles[iid]='LI';children[lid].append(iid)
                children[iid]=([item['label']] if item['label'] else [])+[item['body']]
                if item['label']:roles[item['label']]='Lbl'
                roles[item['body']]='LBody'
    return roles,children


def _prepare(pdf,items,cancel=None,*,text_contexts=None,other_changes=()):
    rows,targets,_,=_analyse(pdf,cancel,text_contexts=text_contexts);fresh={row['id']:row for row in rows};plans=[];seen=set();edge_parents=set();role_nodes=set();retag_nodes=set()
    fields=('kind','current','element','page','structure_path','references','context_sha256','structural_eligible','structural_limitations','allowed_values','context_text','context_text_source','tree_context')
    for item in items:
        graph._tick(cancel);ident=item.get('id');row=fresh.get(ident)
        if ident in seen or row is None or any(item.get(key)!=row.get(key) for key in fields):_fail('Semantic tree source, occurrence or capability context changed')
        seen.add(ident);value=validate_value(item)
        if item['value']==item['current']:continue
        target=targets[ident];rec=target['record'];element=item['element'];kind=item['kind'];parents=set();retags=set()
        if kind=='reading-order':parents.add(element)
        elif kind=='tree-move':parents.update([graph._id(rec['parent']),value['parent']])
        elif kind=='semantic-list' and value['items']:
            parents.add(element);retags={node for entry in value['items'] for node in ([entry['label']] if entry['label'] else [])+[entry['body']]}
        elif kind=='semantic-role':
            if element in role_nodes or element in retag_nodes:_fail('Two accepted semantic choices write the same role')
            role_nodes.add(element)
        if parents&edge_parents:_fail('Accepted tree operations overlap the same original parent; apply a single explicit plan for that scope')
        if retags&(retag_nodes|role_nodes):_fail('Accepted list and role choices overlap the same source text node')
        edge_parents.update(parents);retag_nodes.update(retags)
        plans.append({'kind':kind,'id':ident,'element':element,'value':value,'record':rec,'nodes':target['nodes'],
            'source_parent':graph._id(rec['parent']),'page':item['page'],'pages':dict(target['pages']),
            'source_children':list(rec['children'] or [])})
    if plans:
        nodes=plans[0]['nodes'];roles,children=_final_roles_and_children(nodes,plans)
        role_writes=role_nodes|retag_nodes
        if any(item.get('kind') in {'heading-tag','structure-role'} and item.get('value')!=item.get('current') and item.get('element') in role_writes for item in other_changes):
            _fail('Accepted legacy and semantic choices write the same role; select one explicit role decision')
        for item in other_changes:
            if item.get('kind')=='figure-purpose' and item.get('value')!=item.get('current') and item.get('element') in nodes:
                if graph._id(nodes[item['element']]['parent']) in edge_parents:
                    _fail('Decorative removal and a semantic tree plan change the same original parent')
        _validate_language_composition(pdf,plans,other_changes)
        affected=set(edge_parents)|role_nodes|retag_nodes
        for ident in list(affected):
            if ident in nodes:affected.add(graph._id(nodes[ident]['parent']))
        for ident in affected:
            role=roles.get(ident);kids=children.get(ident,[]);child_roles=[roles.get(child) for child in kids]
            if role=='L' and (not kids or any(value!='LI' for value in child_roles)):_fail('A reviewed list must contain only list-item children')
            if role=='LI' and child_roles not in (['LBody'],['Lbl','LBody']):_fail('Each reviewed list item must contain a body, optionally preceded by one label')
            if role in {'Lbl','LBody'}:
                parent=next((parent for parent,kids in children.items() if ident in kids),None)
                if roles.get(parent)!='LI':_fail('List labels and bodies must belong to a reviewed list item')
    return plans


def _validate_language_composition(pdf,plans,other_changes):
    """Accepted language edits must not make a reviewed move change inheritance."""
    overrides={};catalog=pdf.Root.get('/Lang')
    for item in other_changes:
        if item.get('value')==item.get('current'):continue
        if item.get('kind') in {'page-language','passage-language'}:
            language=json.loads(item['value'])['language'];overrides[item['element']]=None if language is None else bytes(pikepdf.String(language))
        elif item.get('kind')=='language':catalog=pikepdf.String(item['value'])
    def inherited(ident,nodes):
        seen=set()
        while ident in nodes and ident not in seen:
            seen.add(ident);node=nodes[ident]['node']
            if ident in overrides:
                if overrides[ident] is not None:return overrides[ident]
            elif '/Lang' in node:return bytes(node['/Lang']) if isinstance(node['/Lang'],pikepdf.String) else ('invalid',ident)
            ident=graph._id(nodes[ident]['parent'])
        return bytes(catalog) if isinstance(catalog,pikepdf.String) else None if catalog is None else ('invalid','catalog')
    for plan in plans:
        if plan['kind']!='tree-move':continue
        ident=plan['element'];nodes=plan['nodes'];node=nodes[ident]['node']
        direct=overrides.get(ident,bytes(node['/Lang']) if isinstance(node.get('/Lang'),pikepdf.String) else None)
        if direct is None and inherited(plan['source_parent'],nodes)!=inherited(plan['value']['parent'],nodes):
            _fail('The accepted language changes would alter this moved text leaf\'s inherited language')


def prepare_changes(pdf,items,*,cancel=None,text_contexts=None,other_changes=()):return _prepare(pdf,items,cancel,text_contexts=text_contexts,other_changes=other_changes)
def prepare_expected(pdf,items,*,cancel=None,text_contexts=None,other_changes=()):return _prepare(pdf,items,cancel,text_contexts=text_contexts,other_changes=other_changes)


def _name(value):return {'t':'name','v':'/'+value}
def _dict_encoded(value):return {'t':'dict','v':value}
def _array_encoded(values):return {'t':'array','v':values}


def expected_snapshot(snapshot,plans,*,cancel=None):
    expected=copy.deepcopy(snapshot)
    def fields(ident):return expected['objects'][ident]['v']
    def children(raw):
        resolved=graph._resolve_encoded(expected,raw)
        return resolved['v'] if isinstance(resolved,dict) and resolved.get('t')=='array' else [raw]
    for plan in plans:
        graph._tick(cancel);kind=plan['kind'];ident=plan['element'];value=plan['value']
        if kind=='semantic-role':fields(ident)['/S']=_name(value)
        elif kind=='reading-order':fields(ident)['/K']=_array_encoded([{'ref':child} for child in value['children']])
        elif kind=='tree-move':
            source=fields(plan['source_parent']);destination=fields(value['parent'])
            source_k=children(source['/K']);dest_k=children(destination['/K'])
            source['/K']=_array_encoded([child for child in source_k if child!={'ref':ident}])
            dest_k=copy.deepcopy(dest_k);dest_k.insert(value['index'],{'ref':ident});destination['/K']=_array_encoded(dest_k)
            fields(ident)['/P']={'ref':value['parent']}
        elif kind=='semantic-list' and value['items']:
            selected=[node for entry in value['items'] for node in ([entry['label']] if entry['label'] else [])+[entry['body']]]
            source=fields(ident);old=children(source['/K']);first=min(i for i,child in enumerate(old) if child.get('ref') in selected)
            lid='semantic:new-list:'+ident;page_id=next(pid for pid,number in plan['pages'].items() if number==plan['page'])
            li_ids=['semantic:new-item:'+ident+':'+str(n) for n in range(len(value['items']))]
            expected['objects'][lid]=_dict_encoded({'/Type':_name('StructElem'),'/S':_name('L'),'/P':{'ref':ident},'/Pg':{'ref':page_id},
                '/K':_array_encoded([{'ref':iid} for iid in li_ids]),'/A':_dict_encoded({'/O':_name('List'),'/ListNumbering':_name(value['numbering'])})})
            for iid,entry in zip(li_ids,value['items']):
                kids=([entry['label']] if entry['label'] else [])+[entry['body']]
                expected['objects'][iid]=_dict_encoded({'/Type':_name('StructElem'),'/S':_name('LI'),'/P':{'ref':lid},'/K':_array_encoded([{'ref':child} for child in kids])})
                for child in kids:fields(child)['/P']={'ref':iid};fields(child)['/S']=_name('Lbl' if child==entry['label'] else 'LBody')
            kept=[child for child in old if child.get('ref') not in selected];kept.insert(first,{'ref':lid});source['/K']=_array_encoded(kept)
    return expected


def apply_prepared(pdf,plans,*,cancel=None):
    before=graph._snapshot(pdf,cancel);expected=expected_snapshot(before,plans,cancel=cancel)
    for plan in plans:
        graph._tick(cancel);kind=plan['kind'];ident=plan['element'];value=plan['value'];node=plan['record']['node'];nodes=plan['nodes']
        if kind=='semantic-role':node['/S']=pikepdf.Name('/'+value)
        elif kind=='reading-order':node['/K']=pikepdf.Array([nodes[child]['node'] for child in value['children']])
        elif kind=='tree-move':
            source=nodes[plan['source_parent']]['node'];destination=nodes[value['parent']]['node']
            source['/K']=pikepdf.Array([child for child in source['/K'] if graph._id(child)!=ident])
            kids=_child_values(destination);kids.insert(value['index'],node);destination['/K']=pikepdf.Array(kids);node['/P']=destination
        elif kind=='semantic-list' and value['items']:
            selected=[child for entry in value['items'] for child in ([entry['label']] if entry['label'] else [])+[entry['body']]]
            original=_child_values(node);first=min(i for i,child in enumerate(original) if graph._id(child) in selected)
            page=pdf.pages[plan['page']-1].obj
            new_list=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.L,P=node,Pg=page,
                A=pikepdf.Dictionary(O=pikepdf.Name.List,ListNumbering=pikepdf.Name('/'+value['numbering']))))
            items=[]
            for entry in value['items']:
                li=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.LI,P=new_list))
                ids=([entry['label']] if entry['label'] else [])+[entry['body']];kids=[]
                for child in ids:
                    old=nodes[child]['node'];old['/P']=li;old['/S']=pikepdf.Name.Lbl if child==entry['label'] else pikepdf.Name.LBody;kids.append(old)
                li['/K']=pikepdf.Array(kids);items.append(li)
            new_list['/K']=pikepdf.Array(items);kept=[child for child in original if graph._id(child) not in selected];kept.insert(first,new_list);node['/K']=pikepdf.Array(kept)
    if canonical_snapshot(graph._snapshot(pdf,cancel))!=canonical_snapshot(expected):
        _fail('Semantic tree writer changed fields outside the exact reviewed roles, order, moves and list wrappers')
    return [plan['id'] for plan in plans]
