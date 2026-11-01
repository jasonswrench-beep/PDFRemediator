"""Reviewed detachment of proved empty ordinary structure leaves.

Only a selected parent's existing child array changes. Detached objects are
left alone; the root-reachable preservation graph naturally excludes them.
"""
from __future__ import annotations

from collections import Counter
import copy

import pikepdf

from . import structure_edits as graph
from .navigation_edits import canonical_snapshot

KINDS = {'empty-tag-removal'}
POLICY = 'reviewed-empty-tag-removal-1'
LIMITS = {'removals': 100, 'children': 200}
NEUTRAL = {'/Document', '/Part', '/Sect', '/Div'}
LEAVES = {'/P', '/Span'}
_PROTECTED = {'/Alt', '/ActualText', '/E', '/A', '/C', '/ID', '/Ref', '/AF', '/NS', '/R'}
_COMPATIBLE = {'title', 'language', 'figure-description', 'heading-tag', 'table-header'}


def _fail(message):
    from .sidecar import DecisionError
    raise DecisionError(message)


def _dict(value):
    return isinstance(value, pikepdf.Dictionary) and not isinstance(value, pikepdf.Stream)


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _shape(node):
    if '/K' not in node: return 'absent'
    value = node['/K']
    if value is None: return 'null'
    if isinstance(value, pikepdf.Array) and len(value) == 0: return 'empty-array'
    if _int(value) or _dict(value) and ('/MCID' in value or value.get('/Type') == pikepdf.Name.OBJR): return 'content-reference'
    if _dict(value) and '/S' in value: return 'content-child'
    if isinstance(value, pikepdf.Array):
        return 'content-child' if any(_dict(child) and '/S' in child for child in value) else 'content-reference'
    return 'unsupported'


def _children(node):
    raw = node.get('/K')
    if not isinstance(raw, pikepdf.Array): return None
    result = [graph._id(child) for child in raw]
    if (any(not _dict(child) or '/Type' in child and child['/Type'] != pikepdf.Name.StructElem
            or not isinstance(child.get('/S'), pikepdf.Name) for child in raw)
            or None in result or len(result) != len(set(result))): return None
    return result


def _ancestry_children(node):
    raw = node.get('/K')
    if isinstance(raw, pikepdf.Array): return _children(node)
    if (_dict(raw) and ('/Type' not in raw or raw['/Type'] == pikepdf.Name.StructElem)
            and isinstance(raw.get('/S'), pikepdf.Name) and graph._id(raw)):
        return [graph._id(raw)]
    return None


def _candidate_census(pdf, cancel=None):
    root = pdf.Root.get('/StructTreeRoot')
    if root is None: return 0, True
    if not _dict(root): return 0, False
    queue = [(root.get('/K'), 0)]; seen = set(); count = 0; candidates = 0; complete = True
    while queue:
        value, depth = queue.pop(); count += 1
        if count % 256 == 0: graph._tick(cancel)
        if count > 100000 or depth > 200: return candidates, False
        if value is None or _int(value): continue
        if isinstance(value, pikepdf.Array):
            queue.extend((child, depth + 1) for child in value); continue
        if not _dict(value): complete = False; continue
        if value.get('/Type') in (pikepdf.Name.MCR, pikepdf.Name.OBJR) or '/MCID' in value: continue
        if not isinstance(value.get('/S'), pikepdf.Name): complete = False; continue
        ident = graph._id(value)
        if not ident or ident in seen: complete = False
        if ident in seen: continue
        if ident: seen.add(ident)
        if _shape(value) in {'absent', 'null', 'empty-array'}: candidates += 1
        else: queue.append((value.get('/K'), depth + 1))
    return candidates, complete


def _incoming(pdf, cancel=None):
    # Include orphan objects and direct descendants when detecting aliases.
    incoming = Counter(); seen = set(); count = 0; protected = False
    queue = [(pdf.Root, True, 0), (pdf.trailer.get('/Info'), True, 0)] + [(obj, False, 0) for obj in pdf.objects]
    while queue:
        value, edge, depth = queue.pop(); count += 1
        if count % 256 == 0: graph._tick(cancel)
        if count > 1000000 or depth > 200: _fail('Empty-tag reference proof exceeds its bounded scope')
        ident = graph._id(value)
        if ident:
            if edge: incoming[ident] += 1
            if ident in seen: continue
            seen.add(ident); depth = 0
        if isinstance(value, (pikepdf.Dictionary, pikepdf.Stream)):
            if (any(key in value for key in ('/ByteRange', '/JS', '/AA', '/OpenAction', '/XFA'))
                    or value.get('/Type') == pikepdf.Name.Sig or value.get('/Subtype') == pikepdf.Name.Widget
                    or '/FT' in value): protected = True
            queue.extend((child, True, depth + 1) for child in value.values())
        elif isinstance(value, pikepdf.Array): queue.extend((child, True, depth + 1) for child in value)
    return incoming, protected


def _analyse(pdf, cancel=None):
    from .inspection import _structure, _page_content
    candidates, census_complete = _candidate_census(pdf, cancel)
    if census_complete and candidates == 0: return [], {}, None
    if not census_complete and candidates == 0: _fail('The rooted structure census is incomplete; empty-tag status is unproved')
    nodes, arrays, problems, snapshot, root = graph._analyse(pdf, cancel)
    if root is None: return [], {}, None
    incoming, protected = _incoming(pdf, cancel)
    global_limits = list(problems)
    if not census_complete: global_limits.append('The rooted candidate census is incomplete or ambiguous.')
    if '/Lang' in pdf.Root and not isinstance(pdf.Root['/Lang'], pikepdf.String):
        global_limits.append('The inherited document language is not an ordinary string.')
    if pdf.is_encrypted or '/AcroForm' in pdf.Root or '/Perms' in pdf.Root or protected:
        global_limits.append('Encrypted, signed, interactive or scripted documents need a separate supported repair workflow.')
    if not _dict(root) or root.get('/Type') != pikepdf.Name.StructTreeRoot:
        global_limits.append('The source needs a canonical structure root.')
    root_children = _ancestry_children(root)
    if root_children is None or incoming[graph._id(root)] != 1 + len(root_children):
        global_limits.append('The structure root has unsupported child ownership or aliases.')
    if isinstance(root.get('/K'), pikepdf.Array) and graph._id(root['/K']) and incoming[graph._id(root['/K'])] != 1:
        global_limits.append('The root child array has another owner.')
    pages = {graph._id(page.obj): number for number, page in enumerate(pdf.pages, 1)}
    structure, owners, _, _, parent_tree = _structure(pdf, pages)
    if structure['errors']: global_limits.append('The structure references are not uniquely resolvable.')
    witnessed = set()
    for number, page in enumerate(pdf.pages, 1):
        graph._tick(cancel)
        info, definitions, painted = _page_content(page, number, owners, parent_tree, {})
        if info.get('errors') or info.get('duplicate_mcids'):
            global_limits.append('Page marked content cannot be completely resolved.')
        key = page.obj.get('/StructParents'); slots = arrays.get(key) if _int(key) else None
        for reference, found in painted.items():
            page_number, stream, mcid = reference
            occurrence = owners.get(reference, [])
            if (stream == 'page' and found and definitions.get(reference) == 1 and len(occurrence) == 1
                    and isinstance(slots, pikepdf.Array) and 0 <= mcid < len(slots)
                    and graph._id(slots[mcid]) == occurrence[0]): witnessed.add(occurrence[0])
    rolemap = root.get('/RoleMap', {})
    graph_sha = graph._digest(canonical_snapshot(snapshot))
    painted_subtrees = set()
    for witness in witnessed:
        branch = witness; visited = set()
        while branch in nodes and branch not in visited:
            visited.add(branch); painted_subtrees.add(branch); branch = graph._id(nodes[branch]['parent'])
    rows, targets = [], {}
    for ident, rec in nodes.items():
        graph._tick(cancel)
        node = rec['node']; shape = _shape(node)
        if ident in painted_subtrees: continue
        limits = list(global_limits); parent = rec['parent']; parent_id = graph._id(parent)
        children = _children(parent) if _dict(parent) else None
        index = children.index(ident) if children is not None and ident in children else None
        if shape not in {'absent', 'null', 'empty-array'}:
            limits.append('An existing content reference, child or malformed K value is retained even when no paint was found.')
        if ('/Type' in node and node['/Type'] != pikepdf.Name.StructElem or rec['role'] not in LEAVES
                or not isinstance(node.get('/S'), pikepdf.Name) or str(node['/S']) != rec['role']):
            limits.append('Only canonical ordinary P or Span leaves can be removed.')
        if set(map(str, node.keys())) - {'/Type', '/S', '/P', '/K', '/Pg'}:
            limits.append('Descriptions, language, attributes, IDs or other source properties protect this leaf.')
        if incoming[ident] != 1: limits.append('ParentTree, IDTree, dependent references or aliases protect this leaf.')
        if '/Pg' in node and graph._id(node['/Pg']) not in pages:
            limits.append('The leaf has an unresolved page reference.')
        if shape == 'empty-array' and graph._id(node['/K']) and incoming[graph._id(node['/K'])] != 1:
            limits.append('The empty child array has another owner.')
        if (parent_id not in nodes or nodes[parent_id]['role'] not in NEUTRAL or children is None
                or index is None or len(children) < 2 or len(children) > LIMITS['children']):
            limits.append('One neutral parent needs a bounded unique child array with retained siblings.')
        if children is not None:
            if incoming[parent_id] != len(children) + 1: limits.append('The neutral parent has dependent references or aliases.')
            carrier = graph._id(parent['/K'])
            if carrier and incoming[carrier] != 1: limits.append('The parent child array has another owner.')
        ancestry = parent_id; seen = set()
        while ancestry in nodes and ancestry not in seen:
            seen.add(ancestry); ancestor = nodes[ancestry]['node']; ancestor_role = nodes[ancestry]['role']
            if ancestor_role not in NEUTRAL or any(key in ancestor for key in _PROTECTED):
                limits.append('Semantic, replacement, attribute or dependent-reference ancestry protects this scope.')
            if set(map(str, ancestor.keys())) - {'/Type', '/S', '/P', '/K', '/Pg', '/Lang'}:
                limits.append('An ancestor contains additional protected source properties.')
            if '/Pg' in ancestor and graph._id(ancestor['/Pg']) not in pages:
                limits.append('An ancestor page reference is unresolved.')
            if '/Lang' in ancestor and not isinstance(ancestor['/Lang'], pikepdf.String):
                limits.append('The inherited language is not an ordinary source string.')
            ancestor_children = _ancestry_children(ancestor)
            if ancestor_children is None or incoming[ancestry] != 1 + len(ancestor_children):
                limits.append('An ancestor has unsupported children, dependent references or aliases.')
            if isinstance(ancestor.get('/K'), pikepdf.Array) and graph._id(ancestor['/K']) and incoming[graph._id(ancestor['/K'])] != 1:
                limits.append('An ancestor child array has another owner.')
            if not isinstance(ancestor.get('/S'), pikepdf.Name) or str(ancestor['/S']) != ancestor_role:
                limits.append('A remapped or unknown ancestor role needs source review.')
            if _dict(rolemap) and str(ancestor.get('/S')) in rolemap:
                limits.append('A standard ancestor role is remapped in this document.')
            ancestry = graph._id(nodes[ancestry]['parent'])
        if _dict(rolemap) and str(node.get('/S')) in rolemap:
            limits.append('The ordinary leaf role is remapped in this document.')
        nonempty = [child for child in children or [] if child in painted_subtrees]
        if not nonempty: limits.append('At least one independently painted sibling must remain in this parent.')
        source = {'element': ident, 'role': rec['role'].lstrip('/') if rec['role'] else '', 'page': rec['page'],
                  'parent': parent_id, 'index': index, 'structure_path': rec['path'], 'k_shape': shape}
        context = {'policy': POLICY, 'source': source,
            'parent': {'element': parent_id, 'role': nodes[parent_id]['role'].lstrip('/') if parent_id in nodes and nodes[parent_id]['role'] else '',
                       'children': children or [], 'nonempty_children': nonempty, 'retained_minimum': 1}, 'limits': dict(LIMITS)}
        limits = sorted(set(limits)); fingerprint = graph._digest({'graph': graph_sha, 'context': context, 'limitations': limits})
        row = {'id': 'empty-tag:' + ident, 'kind': 'empty-tag-removal', 'current': 'keep', 'value': 'keep', 'status': 'pending',
               'element': ident, 'page': rec['page'], 'structure_path': rec['path'], 'references': copy.deepcopy(rec.get('refs', [])),
               'context_text': '', 'context_text_source': 'Exact existing structure; no text or meaning inferred.',
               'context_sha256': fingerprint, 'structural_eligible': not limits, 'structural_limitations': limits,
               'allowed_values': ['keep', 'remove'] if not limits else ['keep'], 'empty_tag_context': context}
        rows.append(row); targets[row['id']] = {'record': rec, 'nodes': nodes, 'parent': parent, 'snapshot': snapshot}
    return rows, targets, snapshot


def inventory(pdf, *, cancel=None, text_contexts=None):
    try:
        rows, targets, _ = _analyse(pdf, cancel); return rows, targets, []
    except InterruptedError: raise
    except (ValueError, RuntimeError, TypeError, KeyError, AttributeError, pikepdf.PdfError) as exc:
        graph._tick(cancel)
        reason = 'The bounded empty-tag preservation proof is unavailable: ' + str(exc)[:300]
        context = {'policy': POLICY, 'source': {'element': 'unavailable', 'role': '', 'page': None, 'parent': None,
            'index': None, 'structure_path': 'root/K', 'k_shape': 'unsupported'},
            'parent': {'element': None, 'role': '', 'children': [], 'nonempty_children': [], 'retained_minimum': 1}, 'limits': dict(LIMITS)}
        return [{'id': 'empty-tag:unavailable', 'kind': 'empty-tag-removal', 'element': 'unavailable', 'page': None,
            'structure_path': 'root/K', 'references': [], 'current': 'keep', 'value': 'keep', 'status': 'pending',
            'context_text': '', 'context_text_source': 'No complete preservation proof.', 'context_sha256': graph._digest({'context': context, 'reason': reason}),
            'structural_eligible': False, 'structural_limitations': [reason], 'allowed_values': ['keep'], 'empty_tag_context': context}], {}, []


def validate_value(item):
    context = item.get('empty_tag_context')
    if (item.get('kind') not in KINDS or item.get('current') != 'keep'
            or not isinstance(item.get('value'), str) or item['value'] not in {'keep', 'remove'}):
        _fail('An empty-tag choice must keep the source leaf or explicitly remove it')
    if not isinstance(context, dict) or context.get('policy') != POLICY or context.get('limits') != LIMITS:
        _fail('The empty-tag source context changed')
    if item['value'] == 'remove' and (item.get('structural_eligible') is not True or item.get('allowed_values') != ['keep', 'remove']):
        _fail('This source leaf does not have a complete safe-removal proof')


def _prepare(pdf, items, cancel=None, other_changes=()):
    rows, targets, _ = _analyse(pdf, cancel); fresh = {row['id']: row for row in rows}; plans = []; seen = set()
    for item in items:
        graph._tick(cancel)
        if item.get('id') in seen: _fail('An empty-tag decision was repeated')
        seen.add(item.get('id')); validate_value(item)
        original = fresh.get(item['id'])
        if original is None or any(item.get(key) != original.get(key) for key in ('kind', 'element', 'page', 'structure_path', 'references',
                'current', 'context_sha256', 'structural_eligible', 'structural_limitations', 'allowed_values', 'empty_tag_context')):
            _fail('The empty-tag decision is stale or its source capabilities changed')
        if item['value'] == 'keep': continue
        target = targets[item['id']]; context = original['empty_tag_context']
        plans.append({'id': item['id'], 'kind': item['kind'], 'element': item['element'], 'parent': context['parent']['element'],
                      'children': list(context['parent']['children']), 'nonempty_children': list(context['parent']['nonempty_children']),
                      'record': target['record'], 'parent_node': target['parent'],
                      'source_object': copy.deepcopy(target['snapshot']['objects'][item['element']])})
    if len(plans) > LIMITS['removals']: _fail('Remove at most 100 proved empty leaves in one reviewed operation')
    selected = {plan['element'] for plan in plans}; affected = selected | {plan['parent'] for plan in plans}
    for plan in plans:
        kept = [child for child in plan['children'] if child not in selected]
        if not kept or not set(kept) & set(plan['nonempty_children']): _fail('The complete removal batch must retain a painted sibling and a nonempty parent')
    if plans:
        for item in other_changes:
            if item.get('value') == item.get('current') or item.get('kind') in KINDS: continue
            if item.get('kind') not in _COMPATIBLE or item.get('element') in affected:
                _fail('Apply this empty-tag removal separately from the other structural choices')
    return plans


def prepare_changes(pdf, items, *, cancel=None, text_contexts=None, other_changes=()):
    return _prepare(pdf, items, cancel, other_changes)


def prepare_expected(pdf, items, *, cancel=None, text_contexts=None, other_changes=()):
    return _prepare(pdf, items, cancel, other_changes)


def expected_snapshot(snapshot, plans, *, cancel=None):
    expected = copy.deepcopy(snapshot); selected = {plan['element'] for plan in plans}
    for parent in {plan['parent'] for plan in plans}:
        graph._tick(cancel)
        fields = expected['objects'][parent]['v']; array = graph._resolve_encoded(expected, fields['/K'])
        array['v'] = [child for child in array['v'] if not (isinstance(child, dict) and set(child) == {'ref'} and child['ref'] in selected)]
    return graph._prune(expected)


def apply_prepared(pdf, plans, *, cancel=None):
    before = graph._snapshot(pdf, cancel)
    for plan in plans:
        if (_children(plan['parent_node']) != plan['children']
                or before['objects'].get(plan['element']) != plan['source_object']):
            _fail('The prepared empty leaf or its parent sequence changed before writing')
    expected = expected_snapshot(before, plans, cancel=cancel)
    parents = {plan['parent']: plan['parent_node']['/K'] for plan in plans}
    originals = {ident: list(array) for ident, array in parents.items()}; selected = {plan['element'] for plan in plans}
    try:
        for ident, array in parents.items():
            graph._tick(cancel)
            for index in reversed(range(len(array))):
                if graph._id(array[index]) in selected: del array[index]
        if canonical_snapshot(graph._snapshot(pdf, cancel)) != canonical_snapshot(expected):
            _fail('The empty-tag writer changed fields beyond the exact selected parent-child detachments')
    except BaseException:
        for ident, array in parents.items(): array[:] = originals[ident]
        if graph._snapshot(pdf) != before: _fail('The empty-tag writer could not restore its original source graph')
        raise
    return [plan['id'] for plan in plans]
