"""Reviewed names, safe navigation targets and append-only bookmark authoring.

No page program, visible text, annotation geometry, appearance or destination
name tree is edited. Every editable occurrence is bound to its original graph.
"""
from collections import Counter
import copy
from decimal import Decimal
import json
import math
import re
from urllib.parse import urlsplit

import pikepdf

from . import structure_edits as graph

KINDS={'annotation-name','link-name','link-target','bookmark-entry','bookmark-additions'}
POLICY='reviewed-navigation-1'
LIMITS={'name_chars':4000,'title_chars':500,'uri_chars':4096,'new_bookmarks':200,'new_depth':10}
_NAME_SUBTYPES={'/Link','/Text','/Highlight','/Underline','/Squiggly','/StrikeOut'}


def _fail(message):
    from .sidecar import DecisionError
    raise DecisionError(message)


def canonical_value(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _string(value):return str(value) if isinstance(value,pikepdf.String) else None
def _dict(value):return isinstance(value,pikepdf.Dictionary) and not isinstance(value,pikepdf.Stream)
def _integer(value):return isinstance(value,int) and not isinstance(value,bool)


def _text(value,limit,*,empty=False):
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):
        _fail('Use text within the supported length without control characters')
    if not empty and not value.strip():_fail('A changed navigation name or bookmark title cannot be blank')
    if any(0xD800<=ord(c)<=0xDFFF for c in value):_fail('Navigation text contains an invalid Unicode character')
    return value


def _uri(value):
    _text(value,LIMITS['uri_chars'])
    if value!=value.strip() or any(c.isspace() or ord(c)<33 or ord(c)>126 for c in value) or '\\' in value:
        _fail('Use an explicit encoded HTTP, HTTPS or mailto URI without spaces or controls')
    if re.search(r'%(?![0-9A-Fa-f]{2})',value):_fail('URI percent escapes must contain two hexadecimal digits')
    try:
        parts=urlsplit(value)
        if parts.scheme.lower() in {'http','https'}:
            if not parts.netloc or not parts.hostname or parts.username is not None or parts.password is not None:
                _fail('HTTP targets require an explicit host without embedded credentials')
            if parts.port is not None and not 1<=parts.port<=65535:_fail('URI port is outside the supported range')
            host=parts.hostname
            if ':' not in host and (not re.fullmatch(r'[A-Za-z0-9.-]+',host) or '..' in host or host.startswith('.') or host.endswith('.')):
                _fail('Use an explicit encoded host name')
        elif parts.scheme.lower()=='mailto':
            if parts.netloc or not parts.path or '@' not in parts.path or parts.fragment:
                _fail('A mailto target requires an explicit address')
            if re.search(r'%0[ad]',value,re.I):_fail('Mail targets cannot contain encoded line breaks')
        else:_fail('Only explicit HTTP, HTTPS and mailto targets are supported')
    except ValueError as exc:_fail('The navigation URI cannot be parsed: '+str(exc))
    return value


def _target(value,page_count):
    if not isinstance(value,dict):_fail('Choose a supported page or URI target')
    if set(value)=={'kind','page'} and value.get('kind')=='page':
        if not _integer(value['page']) or not 1<=value['page']<=page_count:_fail('Choose an existing page in this PDF')
    elif set(value)=={'kind','uri'} and value.get('kind')=='uri':_uri(value['uri'])
    else:_fail('Only an explicit page or URI target may be written')
    return value


def parse_value(kind,value,page_count,*,current=None):
    if kind in {'annotation-name','link-name'}:
        return _text(value,LIMITS['name_chars'],empty=value==current)
    if not isinstance(value,str) or len(value)>150000:_fail('Navigation decisions exceed the supported payload size')
    try: data=json.loads(value)
    except (ValueError,TypeError):_fail('Navigation choices require their canonical saved JSON value')
    if value!=canonical_value(data):_fail('Navigation choices require canonical saved JSON without duplicate properties')
    def original_target(target):
        return (isinstance(target,dict) and (target=={'kind':'none'} or
            set(target)=={'kind','detail'} and target.get('kind')=='unresolved' and isinstance(target.get('detail'),str)))
    if value==current:
        if kind=='link-target' and original_target(data):return data
        if kind=='bookmark-entry' and isinstance(data,dict) and set(data)=={'title','target'} and isinstance(data['title'],str):
            if original_target(data['target']):return data
            _target(data['target'],page_count);return data
    if kind=='link-target':return _target(data,page_count)
    if kind=='bookmark-entry':
        if not isinstance(data,dict) or set(data)!={'title','target'}:_fail('A bookmark edit permits only its title and target')
        _text(data['title'],LIMITS['title_chars']);_target(data['target'],page_count)
    elif kind=='bookmark-additions':
        if not isinstance(data,dict) or set(data)!={'entries'} or not isinstance(data['entries'],list) or len(data['entries'])>LIMITS['new_bookmarks']:
            _fail('Add at most 200 explicitly named bookmarks')
        previous=0
        for entry in data['entries']:
            if not isinstance(entry,dict) or set(entry)!={'title','page','level'}:_fail('New bookmarks permit only title, page and level')
            _text(entry['title'],LIMITS['title_chars']);_target({'kind':'page','page':entry['page']},page_count)
            level=entry['level']
            if not _integer(level) or not 1<=level<=LIMITS['new_depth'] or level>previous+1:
                _fail('Bookmark levels must begin at 1, increase one level at a time and stay within 10 levels')
            previous=level
    else:_fail('Unsupported navigation decision kind')
    return data


def validate_value(item):
    if item.get('kind') not in KINDS or item.get('structural_eligible') is not True:
        _fail('This navigation occurrence does not have a unique supported source context')
    context=item.get('navigation_context',{})
    count=context.get('page_count')
    if context.get('policy')!=POLICY or not _integer(count) or count<1 or context.get('limits')!=LIMITS:
        _fail('Navigation capabilities or page context changed')
    return parse_value(item['kind'],item.get('value'),count,current=item.get('current'))


def canonical_snapshot(snapshot):
    """Identity-aware canonical graph without recursion through long Next chains."""
    labels={};queue=[]
    def encode(value):
        if isinstance(value,dict) and set(value)=={'ref'}:
            ident=value['ref']
            if ident not in labels:labels[ident]=len(labels)+1;queue.append(ident)
            return {'ref':labels[ident]}
        if isinstance(value,dict):return {k:encode(v) for k,v in sorted(value.items())}
        if isinstance(value,list):return [encode(v) for v in value]
        return value
    result={'root':encode(snapshot['root']),'info':encode(snapshot['info']),'objects':[]}
    index=0
    while index<len(queue):
        ident=queue[index];index+=1;result['objects'].append(encode(snapshot['objects'][ident]))
    return result


def _source_target(node,pages,names):
    action=node.get('/A');dest=node.get('/Dest')
    named=False
    if action is None and dest is None:return {'kind':'none'}
    if action is not None and dest is not None:return {'kind':'unsupported','detail':'Both an action and destination are present'}
    if action is not None:
        if not _dict(action):return {'kind':'unsupported','detail':'Action is not a plain dictionary'}
        kind=str(action.get('/S',''))
        if kind=='/URI' and set(str(k) for k in action)<={'/S','/URI'}:
            if not isinstance(action.get('/S'),pikepdf.Name):return {'kind':'unresolved','detail':'The simple URI action type is not a PDF Name'}
            uri=_string(action.get('/URI'))
            try:_uri(uri)
            except ValueError:return {'kind':'unresolved','detail':'URI is missing or outside the supported explicit URI syntax'}
            return {'kind':'uri','uri':uri}
        if kind!='/GoTo' or not set(str(k) for k in action)<={'/S','/D'}:
            return {'kind':'unsupported','detail':'Action is outside simple URI or local GoTo navigation'}
        if not isinstance(action.get('/S'),pikepdf.Name):return {'kind':'unresolved','detail':'The simple GoTo action type is not a PDF Name'}
        dest=action.get('/D')
    seen=set()
    while isinstance(dest,(pikepdf.Name,pikepdf.String)):
        key=str(dest).lstrip('/') if isinstance(dest,pikepdf.Name) else str(dest)
        if key in seen or key not in names:return {'kind':'unresolved','detail':'Named destination is missing or ambiguous'}
        seen.add(key);dest=names[key];named=True
    if _dict(dest) and set(str(k) for k in dest)=={'/D'}:
        if not named:return {'kind':'unresolved','detail':'A direct destination dictionary must be replaced with an explicit supported destination array'}
        dest=dest['/D']
    if isinstance(dest,pikepdf.Array) and len(dest)>=2 and graph._id(dest[0]) in pages:
        mode=str(dest[1]);sizes={'/Fit':2,'/FitB':2,'/FitH':3,'/FitV':3,'/FitBH':3,'/FitBV':3,'/XYZ':5,'/FitR':6}
        valid=isinstance(dest[1],pikepdf.Name) and mode in sizes and len(dest)==sizes[mode] and all(v is None or isinstance(v,(int,float,Decimal)) and not isinstance(v,bool) and math.isfinite(float(v)) for v in list(dest)[2:])
        if valid and mode=='/FitR':valid=all(v is not None for v in list(dest)[2:]) and dest[2]<dest[4] and dest[3]<dest[5]
        if valid and mode=='/XYZ':valid=dest[4] is None or dest[4]>=0
        if valid:
            return {'kind':'page','page':pages[graph._id(dest[0])]}
    passive=dest is None or isinstance(dest,(pikepdf.Array,pikepdf.Name,pikepdf.String)) or _dict(dest) and set(str(k) for k in dest)=={'/D'}
    return {'kind':'unresolved' if passive else 'unsupported','detail':'Destination is not one proven supported local page view'}


def _named_destinations(pdf):
    names={};bad=set();seen=set();count=0
    def add(key,value):
        if not isinstance(key,(pikepdf.Name,pikepdf.String)):return
        key=str(key).lstrip('/') if isinstance(key,pikepdf.Name) else str(key)
        if key in names:bad.add(key)
        names[key]=value
    def walk(node,depth=0):
        nonlocal count
        if node is None:return
        if not _dict(node) or depth>32:raise ValueError('Named destination tree cannot be resolved')
        ident=graph._id(node)
        if ident and ident in seen:raise ValueError('Named destination tree repeats a node')
        if ident:seen.add(ident)
        values=node.get('/Names',[]);kids=node.get('/Kids',[])
        if not isinstance(values,(list,pikepdf.Array)) or len(values)%2 or not isinstance(kids,(list,pikepdf.Array)):
            raise ValueError('Named destination tree is malformed')
        for i in range(0,len(values),2):
            count+=1
            if count>10000:raise ValueError('Named destination tree exceeds the bounded scope')
            add(values[i],values[i+1])
        for child in kids:walk(child,depth+1)
    catalog_names=pdf.Root.get('/Names',{})
    if _dict(catalog_names):walk(catalog_names.get('/Dests'))
    old=pdf.Root.get('/Dests',{})
    if _dict(old):
        for key,value in old.items():add(pikepdf.Name(str(key)),value)
    for key in bad:names.pop(key,None)
    return names


def _context(scope,count,*,annotation_index=None,bookmark_index=None,source_name=None,source_target=None,linked=None):
    return {'policy':POLICY,'scope':scope,'annotation_index':annotation_index,'bookmark_index':bookmark_index,
        'source_name':source_name,'source_target':source_target,'page_count':count,'allowed_target_kinds':['page','uri'],
        'linked_structure':linked,'limits':copy.deepcopy(LIMITS)}


def _row(ident,kind,current,element,page,path,references,context,limits,graph_sha):
    display={'structural_eligible':not limits,'structural_limitations':sorted(set(limits)),
        'allowed_values':[],'context_text':(context.get('source_name') or '')[:500],
        'context_text_source':'Existing source navigation occurrence; no name, target or coverage is inferred.',
        'navigation_context':context}
    bound={'id':ident,'kind':kind,'current':current,'element':element,'page':page,'structure_path':path,'references':references,**display,'graph_sha256':graph_sha}
    return {k:v for k,v in bound.items() if k!='graph_sha256'}|{'context_sha256':graph._digest(bound),'value':current,'status':'pending'}


def _outline(pdf,pages,names,ref_counts,cancel=None):
    root=pdf.Root.get('/Outlines');records=[];limits=[];expected_incoming=Counter();roots=[]
    if root is None:return {'root':None,'records':[],'roots':[],'visible':0,'limits':[]}
    if not _dict(root) or graph._id(root) is None:return {'root':root,'records':[],'roots':[],'visible':0,'limits':['The existing outline root is not an indirect plain dictionary.']}
    if '/Type' in root and root['/Type']!=pikepdf.Name.Outlines:limits.append('The existing outline root has an unexpected object type.')
    expected_incoming[graph._id(root)]+=1;seen=set()
    def chain(parent,depth):
        if depth>32:raise ValueError('The existing bookmark hierarchy exceeds 32 levels')
        first,last=parent.get('/First'),parent.get('/Last');children=[];node=first;previous=None
        if (first is None)!=(last is None):raise ValueError('The existing bookmark endpoints disagree')
        while node is not None:
            graph._tick(cancel)
            ident=graph._id(node)
            if not _dict(node) or ident is None or ident in seen or len(records)>=2000:raise ValueError('Bookmark nodes are direct, repeated, cyclic or exceed 2000 entries')
            seen.add(ident)
            if graph._id(node.get('/Parent'))!=graph._id(parent) or graph._id(node.get('/Prev'))!=graph._id(previous):
                raise ValueError('Bookmark parent or previous-sibling links do not match the existing tree')
            if previous is None:expected_incoming[ident]+=1
            else:expected_incoming[ident]+=1;expected_incoming[graph._id(previous)]+=1
            expected_incoming[graph._id(parent)]+=1
            rec={'node':node,'id':ident,'index':len(records),'depth':depth,'target':_source_target(node,pages,names)}
            records.append(rec);children.append(rec)
            sub=chain(node,depth+1);rec['children']=sub
            visible_children=sum(1+(c['visible_descendants'] if c['open'] else 0) for c in sub)
            raw=node.get('/Count',0)
            if not _integer(raw) or sub and ('/Count' not in node or abs(raw)!=visible_children) or not sub and raw!=0:
                raise ValueError('Existing bookmark child counts are inconsistent')
            rec['visible_descendants']=visible_children;rec['open']=raw>0
            previous=node;node=node.get('/Next')
        if graph._id(previous)!=graph._id(last):raise ValueError('Existing bookmark last-sibling link is inconsistent')
        if previous is not None:expected_incoming[graph._id(previous)]+=1
        return children
    try:
        roots=chain(root,0)
        visible=sum(1+(r['visible_descendants'] if r['open'] else 0) for r in roots)
        if '/Count' in root and (not _integer(root['/Count']) or root['/Count']!=visible):raise ValueError('The outline root count is inconsistent')
        if any(ref_counts[ident]!=n for ident,n in expected_incoming.items()):raise ValueError('The existing outline has additional inbound aliases')
    except ValueError as exc:limits.append(str(exc));visible=0
    return {'root':root,'records':records,'roots':roots,'visible':visible,'limits':limits}


def _analyse(pdf,cancel=None):
    graph._tick(cancel);snapshot=graph._snapshot(pdf,cancel)
    pages={graph._id(page.obj):n for n,page in enumerate(pdf.pages,1)};count=len(pages)
    common=[]
    if pdf.is_encrypted or '/AcroForm' in pdf.Root or '/Perms' in pdf.Root:common.append('Encrypted, signed or form documents require a separately supported source-repair workflow.')
    if any(isinstance(v,dict) and v.get('t')=='dict' and ('/ByteRange' in v['v'] or v['v'].get('/Type')=={'t':'name','v':'/Sig'}) for v in snapshot['objects'].values()):
        common.append('Signed document bytes must remain unchanged in a separate signing workflow.')
    ref_counts=Counter(r for value in [snapshot['root'],snapshot['info'],*snapshot['objects'].values()] for r in graph._references(value))
    try:names=_named_destinations(pdf)
    except ValueError:names={}
    structure_nodes={};structure_limits=[];objr_owners={};struct_parent_values={}
    if _dict(pdf.Root.get('/StructTreeRoot')):
        try:
            structure_nodes,_,structure_limits,_,root=graph._analyse(pdf,cancel)
            from .inspection import _number_tree
            errors=[];struct_parent_values=_number_tree(root.get('/ParentTree'),errors,set())
            if errors:structure_limits.append('The existing annotation ParentTree is not uniquely resolvable.')
            def objrs(value,owner):
                if isinstance(value,pikepdf.Array):
                    for child in value:objrs(child,owner)
                elif _dict(value) and '/S' not in value and str(value.get('/Type',''))=='/OBJR':
                    aid=graph._id(value.get('/Obj'))
                    if aid:objr_owners.setdefault(aid,[]).append((owner,value))
            for ident,item in structure_nodes.items():objrs(item['node'].get('/K'),ident)
        except (ValueError,RuntimeError,TypeError) as exc:structure_limits=[str(exc)]
    occurrences=Counter();annotations=[];total=0
    for number,page in enumerate(pdf.pages,1):
        graph._tick(cancel);values=page.obj.get('/Annots',[])
        if not isinstance(values,(list,pikepdf.Array)):continue
        for index,node in enumerate(values):
            total+=1
            if total>10000:_fail('Navigation inventory exceeds 10000 annotation occurrences')
            if _dict(node):occurrences[graph._id(node)]+=1;annotations.append((number,index,node,values))
    rows=[];targets={};graph_sha=graph._digest(snapshot)
    for number,index,node,annots in annotations:
        graph._tick(cancel);ident=graph._id(node);subtype=str(node.get('/Subtype',''));limits=list(common)
        if subtype not in _NAME_SUBTYPES:continue
        objrs=objr_owners.get(ident,[])
        if not isinstance(node.get('/Subtype'),pikepdf.Name) or '/Type' in node and node['/Type']!=pikepdf.Name.Annot:
            limits.append('Navigation edits require an actual annotation dictionary with a supported PDF Name subtype.')
        if ident is None or occurrences[ident]!=1:limits.append('This annotation is direct or repeated on more than one occurrence.')
        if ident and ref_counts[ident]!=1+len(objrs):limits.append('This annotation has an additional inbound alias or unsupported relationship.')
        if graph._id(annots) and ref_counts[graph._id(annots)]!=1:limits.append('The annotation array has another owner or alias.')
        if '/P' in node and graph._id(node['/P'])!=graph._id(pdf.pages[number-1].obj):limits.append('The annotation page pointer does not match its actual page.')
        rectangle=node.get('/Rect')
        if not isinstance(rectangle,pikepdf.Array) or len(rectangle)!=4 or any(not isinstance(v,(int,float,Decimal)) or isinstance(v,bool) or not math.isfinite(float(v)) for v in rectangle):
            limits.append('The existing annotation rectangle is not a finite four-number rectangle.')
        if any(k in node for k in ('/RC','/AA','/JS','/Popup','/IRT')):limits.append('Rich text, popup/reply relationships or additional actions require source review.')
        text=_string(node.get('/Contents')) if '/Contents' in node else ''
        name_limits=limits+(['The existing annotation description is not a text string.'] if text is None else [])
        target=_source_target(node,pages,names) if subtype=='/Link' else None
        linked=None
        if len(objrs)==1:
            owner,_=objrs[0];record=structure_nodes.get(owner)
            if record and record.get('role')=='/Link':
                linked={'element':owner,'path':record['path'],'alt':_string(record['node'].get('/Alt')) if '/Alt' in record['node'] else ''}
        context=_context('annotation',count,annotation_index=index,source_name=text,source_target=target,linked=linked)
        refs=[{'page':number,'annotation_index':index,'object':ident}];path=f'pages/{number-1}/Annots/{index}'
        row=_row(f'annotation:{number}:{index}:name','annotation-name',text or '',ident,number,path,refs,context,name_limits,graph_sha)
        rows.append(row);targets[row['id']]={'node':node,'kind':'annotation-name'}
        if subtype=='/Link':
            target_limits=list(limits)
            if target['kind']=='unsupported':target_limits.append(target['detail'])
            for value in [node.get('/A'),node.get('/Dest')]:
                if graph._id(value) and ref_counts[graph._id(value)]!=1:target_limits.append('The existing action or destination has another owner or alias.')
            row=_row(f'annotation:{number}:{index}:target','link-target',canonical_value(target),ident,number,path,refs,context,target_limits,graph_sha)
            rows.append(row);targets[row['id']]={'node':node,'kind':'link-target','source_target':target}
            if linked:
                owner=linked['element'];record=structure_nodes[owner];link=record['node'];link_limits=limits+structure_limits
                own=[(aid,objr) for aid,entries in objr_owners.items() for oid,objr in entries if oid==owner]
                pkey=node.get('/StructParent')
                if len(own)!=1 or own[0][0]!=ident or not _integer(pkey) or graph._id(struct_parent_values.get(pkey))!=owner:
                    link_limits.append('The Link needs exactly one matching OBJR and annotation ParentTree owner.')
                if any('/ActualText' in ancestor['node'] for ancestor in structure_nodes.values() if record['path']==ancestor['path'] or record['path'].startswith(ancestor['path']+'/K')):
                    link_limits.append('Replacement text prevents an unambiguous Link alternate-name edit.')
                ancestors=[ancestor['node'] for ancestor in structure_nodes.values() if record['path']==ancestor['path'] or record['path'].startswith(ancestor['path']+'/K')]
                if any(not _dict(ancestor) or not isinstance(ancestor.get('/S'),pikepdf.Name) or '/Type' in ancestor and ancestor['/Type']!=pikepdf.Name.StructElem for ancestor in ancestors):
                    link_limits.append('Link structure ancestry must contain actual typed structure dictionaries and role Names.')
                if linked['alt'] is None:link_limits.append('The existing Link alternate name is not a text string.')
                if any(ref.get('page')!=number or ref.get('stream')!='page' for ref in record.get('refs',[])):
                    link_limits.append('A Link alternate name requires a single-page direct-content scope; cross-page or Form text requires source repair.')
                children=link.get('/K');children=list(children) if isinstance(children,pikepdf.Array) else [children]
                expected=1+sum(_dict(c) and '/S' in c for c in children)+len(record.get('refs',[]))+1
                if ref_counts[owner]!=expected:link_limits.append('The Link structure element has additional inbound aliases.')
                context2=_context('link-structure',count,annotation_index=index,source_name=linked['alt'],source_target=target,linked=linked)
                context2['link_content_references']=copy.deepcopy(record.get('refs',[]))
                row=_row('link:'+owner+':name','link-name',linked['alt'] or '',owner,number,record['path'],refs,context2,link_limits,graph_sha)
                rows.append(row);targets[row['id']]={'node':link,'kind':'link-name'}
    outline=_outline(pdf,pages,names,ref_counts,cancel)
    for rec in outline['records']:
        node=rec['node'];title=_string(node.get('/Title')) if '/Title' in node else '';limits=common+outline['limits']
        if title is None:limits=limits+['The existing bookmark title is not a text string.']
        if rec['target']['kind']=='unsupported':limits=limits+[rec['target']['detail']]
        for value in [node.get('/A'),node.get('/Dest')]:
            if graph._id(value) and ref_counts[graph._id(value)]!=1:limits=limits+['The existing bookmark action or destination has an additional alias.']
        if any(k in node for k in ('/AA','/SE','/JS')):limits=limits+['Additional bookmark actions or structure relationships require source review.']
        context=_context('bookmark',count,bookmark_index=rec['index'],source_name=title,source_target=rec['target'])
        context['depth']=rec['depth'];value=canonical_value({'title':title or '', 'target':rec['target']})
        row=_row('bookmark:'+str(rec['index'])+':entry','bookmark-entry',value,rec['id'],None,'outlines/'+str(rec['index']),[],context,limits,graph_sha)
        rows.append(row);targets[row['id']]={'node':node,'kind':'bookmark-entry','source_target':rec['target'],'source_name':title}
    context=_context('bookmark-additions',count);context['existing_bookmarks']=len(outline['records']);context['existing_visible']=outline['visible']
    row=_row('bookmarks:additions','bookmark-additions',canonical_value({'entries':[]}),graph._id(outline['root']),None,'outlines/new',[],context,common+outline['limits'],graph_sha)
    rows.append(row);targets[row['id']]={'kind':'bookmark-additions','outline':outline}
    return rows,targets,snapshot,pages


def inventory(pdf,*,cancel=None):
    from .sidecar import DecisionError
    try:rows,targets,_,_=_analyse(pdf,cancel);return rows,targets,[]
    except InterruptedError:raise
    except (DecisionError,ValueError,RuntimeError,TypeError,RecursionError) as exc:
        count=len(pdf.pages);context=_context('bookmark-additions',count)
        row=_row('bookmarks:additions','bookmark-additions',canonical_value({'entries':[]}),None,None,'outlines/new',[],context,
            ['The bounded navigation graph proof is unavailable: '+str(exc)],'unavailable')
        return [row],{},[]


def _prepare(pdf,items,cancel=None):
    rows,targets,_,pages=_analyse(pdf,cancel);fresh={r['id']:r for r in rows};plans=[];seen=set()
    keys=('kind','current','element','page','structure_path','references','context_sha256','structural_eligible','structural_limitations','allowed_values','context_text','context_text_source','navigation_context')
    for item in items:
        graph._tick(cancel);ident=item.get('id');row=fresh.get(ident)
        if ident in seen or row is None or any(item.get(k)!=row.get(k) for k in keys):_fail('Navigation source, occurrence or capability context changed')
        seen.add(ident);value=validate_value(item)
        plan={**targets[ident],'id':ident,'value':value,'element':item.get('element'),'pages':dict(pages)}
        if item['kind']=='bookmark-additions':plan['entries']=value['entries']
        plans.append(plan)
    return plans


def prepare_changes(pdf,items,*,cancel=None):return _prepare(pdf,items,cancel)
def prepare_expected(pdf,items,*,cancel=None):return _prepare(pdf,items,cancel)


def _write_target(node,target,pages):
    if target['kind']=='uri':
        node['/A']=pikepdf.Dictionary(S=pikepdf.Name.URI,URI=target['uri'])
        if '/Dest' in node:del node['/Dest']
    else:
        page=pages[target['page']]
        node['/Dest']=pikepdf.Array([page,pikepdf.Name.Fit])
        if '/A' in node:del node['/A']


def _append(pdf,plan,pages):
    entries=plan['entries']
    if not entries:return
    root=plan['outline']['root']
    if root is None:root=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines));pdf.Root['/Outlines']=root
    nodes=[];parents=[];stack=[];children={}
    for entry in entries:
        level=entry['level'];stack=stack[:level-1];parent=stack[-1] if stack else root
        node=pdf.make_indirect(pikepdf.Dictionary(Title=entry['title'],Parent=parent,Dest=pikepdf.Array([pages[entry['page']],pikepdf.Name.Fit])))
        nodes.append(node);parents.append(parent);children.setdefault(graph._id(parent),[]).append(node);stack.append(node)
    old_last=root.get('/Last');new_roots=children[graph._id(root)]
    if old_last is not None:old_last['/Next']=new_roots[0];new_roots[0]['/Prev']=old_last
    else:root['/First']=new_roots[0]
    root['/Last']=new_roots[-1];root['/Count']=plan['outline']['visible']+len(entries)
    for pid,group in children.items():
        parent=root if pid==graph._id(root) else next(n for n in nodes if graph._id(n)==pid)
        if parent is not root:parent['/First']=group[0];parent['/Last']=group[-1]
        for left,right in zip(group,group[1:]):left['/Next']=right;right['/Prev']=left
    for index,node in reversed(list(enumerate(nodes))):
        group=children.get(graph._id(node),[])
        if group:node['/Count']=sum(1+int(child.get('/Count',0)) for child in group)


def _es(value):return {'t':'string','v':bytes(pikepdf.String(value)).hex()}
def _en(value):return {'t':'number','v':str(Decimal(value).normalize())}
def _ename(value):return {'t':'name','v':value}
def _ed(value):return {'t':'dict','v':value}
def _ea(value):return {'t':'array','v':value}


def expected_snapshot(snapshot,plans,*,cancel=None):
    """Independent encoded-graph delta oracle; never invokes the PDF writer."""
    expected=copy.deepcopy(snapshot)
    root=graph._resolve_encoded(expected,expected['root'])['v']
    def fields(ident):return expected['objects'][ident]['v']
    def target_fields(target,pages):
        if target['kind']=='uri':return {'/A':_ed({'/S':_ename('/URI'),'/URI':_es(target['uri'])})}
        pid=next(pid for pid,n in pages.items() if n==target['page'])
        return {'/Dest':_ea([{'ref':pid},_ename('/Fit')])}
    for plan in plans:
        graph._tick(cancel);kind=plan['kind'];value=plan['value']
        if kind in {'annotation-name','link-name'}:fields(plan['element'])['/Contents' if kind=='annotation-name' else '/Alt']=_es(value)
        elif kind=='link-target':
            d=fields(plan['element']);d.pop('/A',None);d.pop('/Dest',None);d.update(target_fields(value,plan['pages']))
        elif kind=='bookmark-entry':
            d=fields(plan['element'])
            if value['title']!=plan['source_name']:d['/Title']=_es(value['title'])
            if value['target']!=plan['source_target']:
                d.pop('/A',None);d.pop('/Dest',None);d.update(target_fields(value['target'],plan['pages']))
        elif kind=='bookmark-additions' and plan['entries']:
            entries=plan['entries'];oldroot=plan['outline']['root'];rid=graph._id(oldroot) if oldroot is not None else 'navigation:new-root'
            if oldroot is None:expected['objects'][rid]=_ed({'/Type':_ename('/Outlines')});root['/Outlines']={'ref':rid}
            r=fields(rid);old_last=r.get('/Last');nodes=[];stack=[];groups={}
            for index,entry in enumerate(entries):
                ident='navigation:new-'+str(index);stack=stack[:entry['level']-1];parent=stack[-1] if stack else rid
                fields_new={'/Title':_es(entry['title']),'/Parent':{'ref':parent},**target_fields({'kind':'page','page':entry['page']},plan['pages'])}
                expected['objects'][ident]=_ed(fields_new);nodes.append(ident);groups.setdefault(parent,[]).append(ident);stack.append(ident)
            top=groups[rid]
            if old_last is not None:fields(old_last['ref'])['/Next']={'ref':top[0]};fields(top[0])['/Prev']=old_last
            else:r['/First']={'ref':top[0]}
            r['/Last']={'ref':top[-1]};r['/Count']=_en(plan['outline']['visible']+len(entries))
            for parent,children in groups.items():
                if parent!=rid:fields(parent)['/First']={'ref':children[0]};fields(parent)['/Last']={'ref':children[-1]}
                for left,right in zip(children,children[1:]):fields(left)['/Next']={'ref':right};fields(right)['/Prev']={'ref':left}
            counts={}
            for ident in reversed(nodes):
                children=groups.get(ident,[]);counts[ident]=sum(1+counts[c] for c in children)
                if children:fields(ident)['/Count']=_en(counts[ident])
    # canonical_snapshot walks only reachable objects. Avoid recursively
    # following a long appended Next/Prev chain merely to drop old actions.
    return expected


def apply_prepared(pdf,plans,*,cancel=None):
    before=graph._snapshot(pdf,cancel);expected=expected_snapshot(before,plans,cancel=cancel)
    pages={n:pdf.pages[n-1].obj for n in range(1,len(pdf.pages)+1)}
    for plan in plans:
        graph._tick(cancel);kind=plan['kind'];value=plan['value']
        if kind=='annotation-name':plan['node']['/Contents']=value
        elif kind=='link-name':plan['node']['/Alt']=value
        elif kind=='link-target':_write_target(plan['node'],value,pages)
        elif kind=='bookmark-entry':
            if value['title']!=plan['source_name']:plan['node']['/Title']=value['title']
            if value['target']!=plan['source_target']:_write_target(plan['node'],value['target'],pages)
        elif kind=='bookmark-additions':_append(pdf,plan,pages)
    if canonical_snapshot(graph._snapshot(pdf,cancel))!=canonical_snapshot(expected):
        _fail('Navigation writer changed fields outside the explicitly reviewed names, targets and appended bookmark edges')
    return [plan['id'] for plan in plans]
