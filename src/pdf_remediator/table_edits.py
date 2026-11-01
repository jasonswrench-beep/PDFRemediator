"""Explicit source-bound table metadata plans; page programs are never rewritten.

Header relationships name existing cells, rather than guessing meaning from text
or position.  Both the writer and the encoded graph oracle preserve all fields
outside the exact reviewed Table/TH/TD metadata.
"""
from __future__ import annotations

from collections import Counter
import copy
from decimal import Decimal
import json
import re

import pikepdf

from . import structure_edits as graph
from .navigation_edits import canonical_snapshot

KINDS = {'table-structure'}
POLICY = 'reviewed-table-1'
LIMITS = {'rows': 100, 'cells': 500, 'columns': 100, 'span': 100, 'headers': 32,
          'id_chars': 128, 'summary_chars': 4000, 'payload_chars': 150000}
_NEW_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_.:-]{0,127}\Z')
_TABLE_KEYS = {'/O', '/Scope', '/Headers', '/RowSpan', '/ColSpan', '/Summary'}


def _fail(message):
    from .sidecar import DecisionError
    raise DecisionError(message)


def _dict(value):
    return isinstance(value, pikepdf.Dictionary) and not isinstance(value, pikepdf.Stream)


def _int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def canonical_value(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _children(node):
    raw = node.get('/K')
    children = list(raw) if isinstance(raw, pikepdf.Array) else [raw]
    if all(_dict(child) and isinstance(child.get('/S'), pikepdf.Name) and graph._id(child) for child in children):
        return children
    return None


def _attrs(node):
    """Find a uniquely owned ordinary Table attribute dictionary, retaining shape."""
    problems = []
    if '/C' in node or '/R' in node:
        problems.append('Class-based or revision-dependent table attributes require source review.')
    raw = node.get('/A')
    values = list(raw) if isinstance(raw, pikepdf.Array) else [] if raw is None else [raw]
    if any(not _dict(value) or not isinstance(value.get('/O'), pikepdf.Name) for value in values):
        problems.append('Attribute arrays with revisions or unsupported owners require source review.')
    tables = [(index, value) for index, value in enumerate(values) if _dict(value) and value.get('/O') == pikepdf.Name.Table]
    if len(tables) > 1:
        problems.append('Multiple Table attribute owners are ambiguous.')
    attr = tables[0][1] if len(tables) == 1 else None
    if attr is not None and any(str(key) not in _TABLE_KEYS for key in attr):
        problems.append('Unknown Table attributes require source review before editing this scope.')
    return {'raw': raw, 'attr': attr, 'index': tables[0][0] if len(tables) == 1 else None, 'problems': problems}


def _source_value(node, attr, ids, *, role=None):
    problems = []
    ident = node.get('/ID')
    if ident is not None and not isinstance(ident, pikepdf.String):
        problems.append('A cell ID is not an ordinary PDF string.')
    scope = attr.get('/Scope') if attr is not None else None
    if scope is not None and not isinstance(scope, pikepdf.Name):
        problems.append('A cell Scope is not an ordinary PDF name.')
    elif scope is not None and str(scope) not in {'/Row', '/Column', '/Both'}:
        problems.append('The source Scope name is unsupported; its table meaning needs source review.')
    headers = attr.get('/Headers') if attr is not None else None
    if headers is not None and (not isinstance(headers, pikepdf.Array) or any(not isinstance(x, pikepdf.String) for x in headers)):
        problems.append('A Headers association is not an ordinary array of PDF strings.')
    resolved = []
    for value in headers if isinstance(headers, pikepdf.Array) else []:
        if not isinstance(value, pikepdf.String):
            continue
        targets = ids.get(bytes(value), [])
        resolved.append(targets[0] if len(targets) == 1 else 'unresolved:' + bytes(value).hex())
    spans = {}
    for field, key in [('row_span', '/RowSpan'), ('col_span', '/ColSpan')]:
        value = attr.get(key, 1) if attr is not None else 1
        if not _int(value):
            problems.append('Cell spans must be ordinary PDF integers.')
            value = 1
        spans[field] = value
    return {'element': graph._id(node), 'role': (role if role is not None else str(node.get('/S', ''))).lstrip('/'),
            'id': str(ident) if isinstance(ident, pikepdf.String) else None,
            'scope': str(scope).lstrip('/') if isinstance(scope, pikepdf.Name) else None,
            'headers': resolved, **spans}, problems


def _grid(rows, cells, *, strict=True):
    """Place cells in TR order using declared spans, without visual inference."""
    occupied = {}; positions = {}; widths = []
    for row in rows:
        r = row['index']; column = 0
        for ident in row['cells']:
            cell = cells[ident]
            while (r, column) in occupied:
                column += 1
            rs, cs = cell['row_span'], cell['col_span']
            if not _int(rs) or not _int(cs) or not 1 <= rs <= LIMITS['span'] or not 1 <= cs <= LIMITS['span']:
                if strict: _fail('Each reviewed row/column span must be between 1 and 100')
                rs = cs = 1
            positions[ident] = column
            if column + cs > LIMITS['columns'] or r + rs > len(rows):
                if strict: _fail('Reviewed spans extend outside the bounded table grid')
                rs = cs = 1
            if strict and any(rows[n]['group_key'] != row['group_key'] for n in range(r, min(r + rs, len(rows)))):
                _fail('A row span must remain inside its original row group')
            for rr in range(r, min(r + rs, len(rows))):
                for cc in range(column, min(column + cs, LIMITS['columns'])):
                    if strict and (rr, cc) in occupied:
                        _fail('Reviewed table spans overlap another existing cell')
                    occupied[rr, cc] = ident
            column += cs
        widths.append(max((c + 1 for rr, c in occupied if rr == r), default=0))
    width = max(widths, default=0)
    if strict and (not width or any(w != width for w in widths) or any((r, c) not in occupied for r in range(len(rows)) for c in range(width))):
        _fail('The reviewed cells and spans must form one complete rectangular table grid')
    return positions


def parse_value(value, context, *, current=None):
    if not isinstance(value, str) or len(value) > LIMITS['payload_chars'] or '\x00' in value:
        _fail('Table choices exceed their supported structured payload')
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        _fail('Table choices require their saved structured value')
    if canonical_value(data) != value:
        _fail('Table choices require canonical JSON without duplicate properties')
    if value == current:
        return data
    if not isinstance(data, dict) or set(data) != {'summary', 'cells'} or not isinstance(data['cells'], list):
        _fail('A table plan requires its summary and complete existing cell sequence')
    summary = data['summary']
    if summary is not None and (not isinstance(summary, str) or summary != context['table']['summary'] and (len(summary) > LIMITS['summary_chars'] or '\x00' in summary)):
        _fail('A table summary must be explicit text of at most 4000 characters, or null')
    original = {cell['element']: cell for cell in context['cells']}
    if [cell.get('element') if isinstance(cell, dict) else None for cell in data['cells']] != [cell['element'] for cell in context['cells']]:
        _fail('A table plan must retain every original cell exactly once in source order')
    cells = {}
    for cell in data['cells']:
        if set(cell) != {'element', 'role', 'id', 'scope', 'headers', 'row_span', 'col_span'}:
            _fail('Cell choices contain unsupported properties')
        source = original[cell['element']]
        if not isinstance(cell['role'], str) or cell['role'] not in {'TH', 'TD'} or cell['scope'] is not None and not isinstance(cell['scope'], str) or cell['scope'] not in {None, 'Row', 'Column', 'Both'} or cell['role'] == 'TD' and cell['scope'] is not None:
            _fail('Choose TH/TD and an optional header Scope; data cells cannot have Scope')
        ident = cell['id']
        if ident is not None and (not isinstance(ident, str) or ident != source['id'] and not _NEW_ID.fullmatch(ident)):
            _fail('A changed cell ID must be an explicit ASCII name of at most 128 characters')
        if not isinstance(cell['headers'], list) or len(cell['headers']) > LIMITS['headers'] or any(not isinstance(x, str) for x in cell['headers']) or len(set(cell['headers'])) != len(cell['headers']):
            _fail('Header relationships must name distinct existing source header cells')
        cells[cell['element']] = cell
    for cell in cells.values():
        for target in cell['headers']:
            header = cells.get(target)
            if header is None or target == cell['element'] or header['role'] != 'TH' or not header['id']:
                _fail('Every Headers target must be another named TH cell in this same table')
    visiting = set(); visited = set()
    def visit(ident):
        if ident in visiting: _fail('Header associations must not contain a cycle')
        if ident in visited: return
        visiting.add(ident)
        for target in cells[ident]['headers']: visit(target)
        visiting.remove(ident); visited.add(ident)
    for ident in cells: visit(ident)
    global_ids = [record['id'] for record in context['global_ids'] if record['element'] not in cells]
    global_ids += [cell['id'] for cell in cells.values() if cell['id'] is not None]
    if len(set(global_ids)) != len(global_ids):
        _fail('Reviewed IDs must be unique throughout the document')
    _grid(context['rows'], cells)
    return data


def validate_value(item):
    context = item.get('table_context')
    if item.get('kind') not in KINDS or item.get('structural_eligible') is not True:
        _fail('This table does not have a unique supported source context')
    if not isinstance(context, dict) or context.get('policy') != POLICY or context.get('limits') != LIMITS:
        _fail('Table capabilities or source context changed')
    return parse_value(item.get('value'), context, current=item.get('current'))


def _idtree(root, ids, incoming):
    """Retain the original NameTree topology and every unselected dictionary key."""
    value = root.get('/IDTree'); leaves = []; branches = []; entries = {}; problems = []; seen = set()
    if value is None:
        return {'root': None, 'leaves': [], 'branches': [], 'entries': {}}, problems
    def walk(node, depth=0):
        if depth > 30 or len(seen) > 10000 or not _dict(node):
            raise ValueError('Unsupported IDTree branch')
        ident = graph._id(node)
        if ident and (ident in seen or incoming[ident] != 1):
            raise ValueError('Shared or cyclic IDTree carrier')
        if ident: seen.add(ident)
        names, kids = node.get('/Names'), node.get('/Kids')
        if (names is None) == (kids is None):
            raise ValueError('IDTree needs either Names or Kids')
        carrier = names if names is not None else kids
        if not isinstance(carrier, pikepdf.Array) or graph._id(carrier) and incoming[graph._id(carrier)] != 1:
            raise ValueError('Unsupported or shared IDTree array')
        keys = []
        if names is not None:
            if len(names) % 2: raise ValueError('Odd IDTree Names array')
            pairs = []
            for n in range(0, len(names), 2):
                key, target = names[n], names[n + 1]
                if not isinstance(key, pikepdf.String) or graph._id(target) is None:
                    raise ValueError('Invalid IDTree key or target')
                raw = bytes(key); target_id = graph._id(target)
                if raw in entries or ids.get(raw) != [target_id]:
                    raise ValueError('IDTree mapping does not exactly match the source ID')
                entries[raw] = target_id; keys.append(raw); pairs.append((raw, target_id))
            if keys != sorted(keys): raise ValueError('IDTree keys are not sorted')
            leaves.append({'node': node, 'pairs': pairs})
        else:
            if not kids: raise ValueError('Empty IDTree branch')
            for child in kids: keys.extend(walk(child, depth + 1))
            if keys != sorted(keys) or len(set(keys)) != len(keys): raise ValueError('IDTree child ranges overlap')
            branches.append(node)
        limits = node.get('/Limits')
        if depth > 0 and (not keys or limits is None):
            raise ValueError('A non-root IDTree node needs a nonempty exact Limits range')
        if limits is not None:
            if not isinstance(limits, pikepdf.Array) or len(limits) != 2 or any(not isinstance(x, pikepdf.String) for x in limits) or not keys or [bytes(x) for x in limits] != [keys[0], keys[-1]]:
                raise ValueError('IDTree Limits do not match their exact key range')
            if graph._id(limits) and incoming[graph._id(limits)] != 1: raise ValueError('Shared IDTree Limits array')
        return keys
    try:
        walk(value)
        if set(entries) != set(ids) or any(len(v) != 1 for v in ids.values()):
            raise ValueError('IDTree does not index every unique source ID exactly')
    except ValueError as exc:
        problems.append(str(exc) + '; the ID index needs source review.')
    return {'root': value, 'leaves': leaves, 'branches': branches, 'entries': entries}, problems


def _has_table(pdf):
    root = pdf.Root.get('/StructTreeRoot'); seen = set(); budget = [0]
    if root is None: return False
    if not _dict(root): return True
    roles = root.get('/RoleMap', {}) if _dict(root) else {}
    if not _dict(roles): roles = {}
    def walk(value, depth=0):
        budget[0] += 1
        if depth > 200 or budget[0] > 100000: return True
        if isinstance(value, pikepdf.Array): return any(walk(x, depth + 1) for x in value)
        if not _dict(value): return False
        ident = graph._id(value)
        if ident and ident in seen: return False
        if ident: seen.add(ident)
        role = value.get('/S'); visited = set()
        while isinstance(role, pikepdf.Name) and str(role) in roles:
            if str(role) in visited: return True
            visited.add(str(role)); role = roles[str(role)]
        return role == pikepdf.Name.Table or walk(value.get('/K'), depth + 1)
    return _dict(root) and walk(root.get('/K'))


def _analyse(pdf, cancel=None, *, text_contexts=None):
    if not _has_table(pdf): return [], {}, None
    from .inspection import _structure, _page_content
    nodes, _, problems, snapshot, root = graph._analyse(pdf, cancel)
    pages = {graph._id(page.obj): n for n, page in enumerate(pdf.pages, 1)}
    evidence, owners, _, _, parent_tree = _structure(pdf, pages)
    incoming = Counter(ref for value in [snapshot['root'], snapshot['info'], *snapshot['objects'].values()] for ref in graph._references(value))
    ids = {}; global_ids = []; global_limits = list(problems)
    if not _dict(root):
        global_limits.append('The structure root is not an ordinary dictionary.')
    # Rooted ownership is the only supported StructElem namespace. Unknown
    # reachable structure objects can carry IDs/Headers that a new ID would
    # capture, even when their custom Catalog path is absent from /K.
    def unrooted_structure(value, ident=None):
        if not isinstance(value, dict): return False
        if value.get('t') in {'dict', 'stream'}:
            fields = value['v'] if value['t'] == 'dict' else value['d']
            structured = (fields.get('/Type') == {'t': 'name', 'v': '/StructElem'} or
                          isinstance(fields.get('/S'), dict) and fields['/S'].get('t') == 'name' and '/P' in fields)
            if structured and ident not in nodes: return True
            return any(unrooted_structure(child) for child in fields.values())
        if value.get('t') == 'array':
            return any(unrooted_structure(child) for child in value['v'])
        return False
    if any(unrooted_structure(value, ident) for ident, value in snapshot['objects'].items()):
        global_limits.append('An unrooted reachable structure element has unproven document-wide ID/Headers ownership.')
    for ident, rec in nodes.items():
        value = rec['node'].get('/ID')
        if value is not None:
            if not isinstance(value, pikepdf.String): global_limits.append('A document structure ID is not an ordinary PDF string.')
            else:
                ids.setdefault(bytes(value), []).append(ident); global_ids.append({'id': str(value), 'element': ident})
    index, index_problems = _idtree(root, ids, incoming); global_limits += index_problems
    if pdf.is_encrypted or '/AcroForm' in pdf.Root or '/Perms' in pdf.Root:
        global_limits.append('Encrypted, signed and form documents require a separate supported repair workflow.')
    if any(value.get('t') == 'dict' and ('/ByteRange' in value['v'] or value['v'].get('/Type') == {'t': 'name', 'v': '/Sig'}) for value in snapshot['objects'].values()):
        global_limits.append('Signed document bytes require a separate signing workflow.')
    root_children = _children(root)
    if graph._id(root) is None or root_children is None or incoming[graph._id(root)] != 1 + len(root_children):
        global_limits.append('The structure root has unsupported child ownership or inbound aliases.')
    own_refs = {}
    for ref in evidence['references']: own_refs.setdefault(ref['element'], []).append(ref)
    object_owners = {ref['element'] for ref in evidence['object_references']}
    try: _, parent_chains = graph._parent_arrays(root)
    except ValueError: parent_chains = {}; global_limits.append('ParentTree ownership cannot be independently proved.')
    parent_uses = Counter(page.obj.get('/StructParents') for page in pdf.pages if _int(page.obj.get('/StructParents')))
    page_info = {}
    def carrier_limits(value):
        return graph._id(value) is not None and incoming[graph._id(value)] != 1
    if not (_dict(root.get('/K')) and '/S' in root['/K']) and carrier_limits(root.get('/K')):
        global_limits.append('The root child carrier has another owner.')
    node_limits = {}; attribute_records = {}; outside_headers = []
    for ident, rec in nodes.items():
        node = rec['node']; children = _children(node); attrs = _attrs(node); attribute_records[ident] = attrs
        global_limits += attrs['problems']
        limits = []
        if not _dict(node): limits.append('A structure element is not an ordinary dictionary.')
        indexed = sum(1 for target in index['entries'].values() if target == ident)
        if incoming[ident] != 1 + len(children or []) + len(own_refs.get(ident, [])) + indexed:
            limits.append('A structure element has additional inbound aliases or ambiguous ownership.')
        if '/Type' in node and node['/Type'] != pikepdf.Name.StructElem:
            limits.append('An element has an unsupported structure object type.')
        raw = node.get('/K')
        if not (_dict(raw) and '/S' in raw) and carrier_limits(raw): limits.append('A child/content carrier has another owner.')
        # Nested direct MCR dictionaries/arrays must be uniquely carried too.
        def content_carriers(value, depth=0):
            if depth > 50: limits.append('Content ownership exceeds the proof bound.'); return
            if _dict(value) and '/S' in value: return
            if isinstance(value, pikepdf.Array):
                if carrier_limits(value): limits.append('A nested content carrier has another owner.')
                for child in value: content_carriers(child, depth + 1)
            elif _dict(value) and carrier_limits(value): limits.append('A marked-content carrier has another owner.')
        content_carriers(raw)
        if ident in object_owners: limits.append('Object-reference/annotation table content requires source review.')
        if any(key in node for key in ('/ActualText', '/Ref', '/AF')):
            limits.append('Replacement text, references or associated files protect this table content.')
        if '/C' in node: global_limits.append('Class-based structure attributes require source review before ID changes.')
        for carrier in [attrs['raw'], attrs['attr']]:
            if carrier_limits(carrier): limits.append('An attribute carrier has another owner.')
        if attrs['attr'] is not None:
            headers = attrs['attr'].get('/Headers')
            if headers is not None:
                if not isinstance(headers, pikepdf.Array) or any(not isinstance(x, pikepdf.String) for x in headers):
                    global_limits.append('A document Headers relationship has an unsupported representation.')
                else: outside_headers.extend((ident, bytes(x), tuple(ids.get(bytes(x), []))) for x in headers)
            for value in attrs['attr'].values():
                if isinstance(value, pikepdf.Array) and carrier_limits(value): limits.append('A table attribute value has another owner.')
        node_limits[ident] = limits
    rows_out = []; targets = {}; graph_sha = graph._digest(snapshot)
    for table_id, table in nodes.items():
        if table['role'] != '/Table': continue
        graph._tick(cancel); limits = list(global_limits); rows = []; cells = []; cell_references = {}; table_node = table['node']
        scope = {ident for ident, rec in nodes.items() if ident == table_id or rec['path'].startswith(table['path'] + '/K')}
        if any(ident != table_id and nodes[ident]['role'] == '/Table' for ident in scope):
            limits.append('An enclosing table with nested tables remains read-only; review each inner table separately.')
        ancestry = table_id; visited = set()
        while ancestry in nodes and ancestry not in visited:
            visited.add(ancestry); limits += node_limits[ancestry]
            if any(key in nodes[ancestry]['node'] for key in ('/ActualText', '/Ref', '/AF')):
                limits.append('Replacement text, references or associated files protect this table ancestry.')
            ancestry = graph._id(nodes[ancestry]['parent'])
        for ident in scope: limits += node_limits[ident]
        children = _children(table_node)
        if children is None: limits.append('A table must contain existing TR or explicit row-group structure children.'); children = []
        for child in children:
            role = nodes[graph._id(child)]['role']; group_id = graph._id(child)
            if role == '/Caption': continue
            if role == '/TR': row_nodes = [child]; group = None; group_key = 'direct'
            elif role in {'/THead', '/TBody', '/TFoot'}:
                row_nodes = _children(child) or []; group = role.lstrip('/'); group_key = group_id
                if not row_nodes: limits.append('Empty or unsupported row groups require source review.')
            else: limits.append('Unsupported table children require source review.'); continue
            for row_node in row_nodes:
                if nodes[graph._id(row_node)]['role'] != '/TR': limits.append('Row groups may contain only existing TR elements.'); continue
                row_cells = _children(row_node) or []
                if not row_cells: limits.append('Empty or unsupported rows require source review.')
                cell_ids = []
                for node in row_cells:
                    ident = graph._id(node)
                    if nodes[ident]['role'] not in {'/TH', '/TD'}: limits.append('Rows may contain only existing TH/TD cells.'); continue
                    attrs = attribute_records[ident]; limits += attrs['problems']
                    current, current_limits = _source_value(node, attrs['attr'], ids, role=nodes[ident]['role']); limits += current_limits
                    cell_scope = {key for key in scope if key == ident or nodes[key]['path'].startswith(nodes[ident]['path'] + '/K')}
                    # _structure emits references in the actual authored /K
                    # traversal, including interleaved direct MCIDs and child
                    # elements. Scope sets decide membership, never sequence.
                    refs = [ref for ref in evidence['references'] if ref['element'] in cell_scope]
                    cell_references[ident] = refs
                    refs_pages = sorted({ref['page'] for ref in refs if ref.get('page') in range(1, len(pdf.pages) + 1)})
                    if not refs or any(ref.get('stream') != 'page' or ref.get('page') not in refs_pages for ref in refs):
                        limits.append('Each cell needs proven direct-page marked-content ownership.')
                    for ref in refs:
                        number = ref.get('page'); mcid = ref.get('mcid'); key = (number, ref.get('stream'), mcid)
                        if number not in range(1, len(pdf.pages) + 1): continue
                        if number not in page_info:
                            from .language_edits import _page_language_marks
                            _, blocked, _ = _page_language_marks(pdf.pages[number - 1], number, cancel)
                            page_info[number] = (*_page_content(pdf.pages[number - 1], number, owners, parent_tree, {})[0:3], blocked)
                        info, definitions, painted, blocked = page_info[number]
                        if key in blocked:
                            limits.append('Form or mixed/replacement marked content needs source review.')
                        if info['errors'] or info['duplicate_mcids'] or definitions[key] != 1 or painted[key] < 1 or owners.get(key) != [ref['element']]:
                            limits.append('Cell marked content does not have unique painted ownership.')
                        if any(failure['stream'] == ref['stream'] and failure['mcid'] == mcid for failure in info['parent_tree_failures']):
                            limits.append('Cell ParentTree slots do not match their original owners.')
                        pkey = pdf.pages[number - 1].obj.get('/StructParents')
                        if not _int(pkey) or parent_uses[pkey] != 1 or any(carrier_limits(x) for x in parent_chains.get(pkey, ())):
                            limits.append('A cell ParentTree branch or page key is shared.')
                    text = ' '.join((text_contexts or {}).get((ref['page'], ref['mcid']), '') for ref in refs)[:1000]
                    cells.append({**current, 'page': refs_pages[0] if len(refs_pages) == 1 else None,
                                  'pages': refs_pages, 'row': len(rows), 'index': len(cell_ids), 'column': 0, 'context_text': text})
                    cell_ids.append(ident)
                rows.append({'element': graph._id(row_node), 'index': len(rows), 'group': group, 'group_key': group_key, 'cells': cell_ids})
        if not rows or not cells or len(rows) > LIMITS['rows'] or len(cells) > LIMITS['cells']:
            limits.append('The table is empty or exceeds the bounded row/cell limits.')
        attrs = attribute_records[table_id]; limits += attrs['problems']; summary = attrs['attr'].get('/Summary') if attrs['attr'] is not None else None
        if summary is not None and not isinstance(summary, pikepdf.String): limits.append('The table summary is not an ordinary PDF string.')
        summary = str(summary) if isinstance(summary, pikepdf.String) else None
        current_cells = [{key: cell[key] for key in ('element', 'role', 'id', 'scope', 'headers', 'row_span', 'col_span')} for cell in cells]
        positions = _grid(rows, {cell['element']: cell for cell in cells}, strict=False)
        for cell in cells: cell['column'] = positions.get(cell['element'], 0)
        # Writing standard roles must not acquire a custom RoleMap meaning.
        rolemap = root.get('/RoleMap', {})
        if any('/' + role in rolemap and str(rolemap['/' + role]) != '/' + role for role in ('TH', 'TD')):
            limits.append('A standard cell role is remapped in this document.')
        table_pages = sorted({number for cell in cells for number in cell['pages']})
        context = {'policy': POLICY, 'table': {'element': table_id, 'path': table['path'], 'pages': table_pages, 'summary': summary},
                   'rows': rows, 'cells': cells, 'global_ids': global_ids, 'limits': dict(LIMITS)}
        current = canonical_value({'summary': summary, 'cells': current_cells})
        fingerprint = graph._digest({'graph_sha256': graph_sha, 'context': context, 'limits': sorted(set(limits))})
        row = {'id': 'table:structure:' + table_id, 'kind': 'table-structure', 'element': table_id,
               'page': table_pages[0] if len(table_pages) == 1 else None, 'structure_path': table['path'],
               'references': [{key: ref[key] for key in ('page', 'stream', 'mcid')} for cell in cells for ref in cell_references[cell['element']]],
               'current': current, 'value': current, 'status': 'pending', 'context_text': '',
               'context_text_source': 'source-bound table cells and existing attributes; no relationships inferred',
               'context_sha256': fingerprint, 'structural_eligible': not limits,
               'structural_limitations': sorted(set(limits)), 'allowed_values': [], 'table_context': context}
        rows_out.append(row)
        targets[row['id']] = {'record': table, 'nodes': nodes, 'root': root, 'index': index, 'ids': ids,
                              'attributes': attribute_records, 'outside_headers': outside_headers, 'scope': scope}
    return rows_out, targets, snapshot


def inventory(pdf, *, cancel=None, text_contexts=None):
    try:
        rows, targets, _ = _analyse(pdf, cancel, text_contexts=text_contexts)
        return rows, targets, []
    except (ValueError, RuntimeError, TypeError, KeyError) as exc:
        graph._tick(cancel)
        reason = 'The bounded table preservation proof is unavailable: ' + str(exc)[:350]
        context = {'policy': POLICY, 'table': {'element': 'unavailable', 'path': 'root/K', 'pages': [], 'summary': None},
                   'rows': [], 'cells': [], 'global_ids': [], 'limits': dict(LIMITS)}
        value = canonical_value({'summary': None, 'cells': []})
        row = {'id': 'table:structure:unavailable', 'kind': 'table-structure', 'element': 'unavailable',
               'page': None, 'structure_path': 'root/K', 'references': [], 'current': value, 'value': value,
               'status': 'pending', 'context_text': '', 'context_text_source': 'no complete table proof',
               'context_sha256': graph._digest({'context': context, 'reason': reason}), 'structural_eligible': False,
               'structural_limitations': [reason], 'allowed_values': [], 'table_context': context}
        return [row], {}, []


def _prepare(pdf, items, cancel=None, *, text_contexts=None, other_changes=()):
    rows, targets, _ = _analyse(pdf, cancel, text_contexts=text_contexts); fresh = {row['id']: row for row in rows}; plans = []; seen = set()
    fields = ('kind', 'current', 'element', 'page', 'structure_path', 'references', 'context_sha256', 'structural_eligible',
              'structural_limitations', 'allowed_values', 'context_text', 'context_text_source', 'table_context')
    for item in items:
        graph._tick(cancel); row = fresh.get(item.get('id'))
        if row is None or item['id'] in seen or any(item.get(key) != row.get(key) for key in fields): _fail('Table source, occurrence or capability context changed')
        seen.add(item['id']); value = validate_value(item)
        if item['value'] == item['current']: continue
        target = targets[item['id']]
        plans.append({'id': item['id'], 'element': item['element'], 'value': value, 'source': json.loads(item['current']), **target})
    if not plans: return []
    all_nodes = plans[0]['nodes']; selected = {}; plan_scopes = set()
    for plan in plans:
        if plan_scopes & plan['scope']: _fail('Accepted table plans overlap the same source structure scope')
        plan_scopes |= plan['scope']
        for cell in plan['value']['cells']: selected[cell['element']] = cell
    ids = {}; final_roles = {ident: rec['role'].lstrip('/') for ident, rec in all_nodes.items()}
    for ident, rec in all_nodes.items():
        if ident in selected:
            cell = selected[ident]; source_id = rec['node'].get('/ID'); final_roles[ident] = cell['role']
            raw = bytes(source_id) if isinstance(source_id, pikepdf.String) and cell['id'] == str(source_id) else None if cell['id'] is None else bytes(pikepdf.String(cell['id']))
        else:
            raw = bytes(rec['node']['/ID']) if isinstance(rec['node'].get('/ID'), pikepdf.String) else None
        if raw is not None: ids.setdefault(raw, []).append(ident)
    if any(len(values) != 1 for values in ids.values()): _fail('Reviewed PDF IDs must be byte-unique throughout the document')
    for owner, raw, original_targets in plans[0]['outside_headers']:
        if owner in selected: continue
        targets_now = tuple(ids.get(raw, []))
        if targets_now != original_targets or any(final_roles.get(ident) != 'TH' for ident in targets_now):
            _fail('A table change would dangle, capture or retarget an outside Headers relationship')
    for item in other_changes:
        if item.get('value') == item.get('current'): continue
        if item.get('kind') in {'table-header', 'structure-role', 'heading-tag', 'figure-purpose', 'semantic-role', 'reading-order', 'tree-move', 'semantic-list'} and item.get('element') in plan_scopes:
            _fail('Another accepted structural choice overlaps this table plan')
        if item.get('kind') in {'reading-order', 'tree-move', 'semantic-list'}:
            ident = item.get('element')
            if ident in all_nodes and any(all_nodes[plan['element']]['path'].startswith(all_nodes[ident]['path'] + '/K') for plan in plans):
                _fail('An ancestor tree operation overlaps the reviewed table scope')
    final_ids = {raw: values[0] for raw, values in ids.items()}
    for plan in plans:
        plan['final_ids'] = final_ids
        if plan['index']['root'] is not None and '/Kids' in plan['index']['root'] and any(not pairs for _, pairs in _index_layout(plan)):
            _fail('This ID change would empty an existing IDTree leaf; source index topology needs review')
    return plans


def prepare_changes(pdf, items, *, cancel=None, text_contexts=None, other_changes=()):
    return _prepare(pdf, items, cancel, text_contexts=text_contexts, other_changes=other_changes)


def prepare_expected(pdf, items, *, cancel=None, text_contexts=None, other_changes=()):
    return _prepare(pdf, items, cancel, text_contexts=text_contexts, other_changes=other_changes)


def _enc_name(value): return {'t': 'name', 'v': '/' + value}
def _enc_string(raw): return {'t': 'string', 'v': raw.hex()}
def _enc_array(values): return {'t': 'array', 'v': values}
def _enc_dict(values): return {'t': 'dict', 'v': values}


def _field_changes(plan):
    source = {cell['element']: cell for cell in plan['source']['cells']}; final = {cell['element']: cell for cell in plan['value']['cells']}
    id_bytes = {ident: raw for raw, ident in plan['final_ids'].items()}
    edits = []
    if plan['value']['summary'] != plan['source']['summary']:
        edits.append((plan['element'], '/Summary', None if plan['value']['summary'] is None else _enc_string(bytes(pikepdf.String(plan['value']['summary']))), 'attr'))
    for ident, cell in final.items():
        old = source[ident]
        if cell['role'] != old['role']: edits.append((ident, '/S', _enc_name(cell['role']), 'node'))
        if cell['id'] != old['id']: edits.append((ident, '/ID', None if cell['id'] is None else _enc_string(id_bytes[ident]), 'node'))
        if cell['scope'] != old['scope']: edits.append((ident, '/Scope', None if cell['scope'] is None else _enc_name(cell['scope']), 'attr'))
        for field, key in [('row_span', '/RowSpan'), ('col_span', '/ColSpan')]:
            if cell[field] != old[field]: edits.append((ident, key, {'t': 'number', 'v': str(Decimal(cell[field]).normalize())}, 'attr'))
        old_attr = plan['attributes'][ident]['attr']; raw_old = old_attr.get('/Headers') if old_attr is not None else None
        desired = [id_bytes[target] for target in cell['headers']]
        existing = [bytes(x) for x in raw_old] if isinstance(raw_old, pikepdf.Array) else []
        if cell['headers'] != old['headers'] or desired != existing:
            edits.append((ident, '/Headers', _enc_array([_enc_string(raw) for raw in desired]) if desired else None, 'attr'))
    return edits


def _index_layout(plan):
    index = plan['index']; final = plan['final_ids']; leaves = index['leaves']
    if index['root'] is None:
        return [(None, sorted(final.items()))]
    layout = []
    for leaf in leaves:
        layout.append([leaf['node'], [(raw, target) for raw, target in leaf['pairs'] if final.get(raw) == target]])
    present = {raw for _, pairs in layout for raw, _ in pairs}
    for raw in sorted(set(final) - present):
        chosen = len(layout) - 1
        for n, (_, pairs) in enumerate(layout):
            original = leaves[n]['pairs']
            if original and raw <= original[-1][0]: chosen = n; break
        layout[chosen][1].append((raw, final[raw]))
    return [(node, sorted(pairs)) for node, pairs in layout]


def expected_snapshot(snapshot, plans, *, cancel=None):
    expected = copy.deepcopy(snapshot)
    def resolve(value): return graph._resolve_encoded(expected, value)
    def node_fields(ident): return expected['objects'][ident]['v']
    def attr_fields(ident, plan):
        fields = node_fields(ident); meta = plan['attributes'][ident]
        if meta['attr'] is not None:
            raw = resolve(fields['/A'])
            return resolve(raw['v'][meta['index']])['v'] if raw['t'] == 'array' else raw['v']
        new = _enc_dict({'/O': _enc_name('Table')})
        if '/A' not in fields: fields['/A'] = new
        elif resolve(fields['/A'])['t'] == 'array': resolve(fields['/A'])['v'].append(new)
        else: fields['/A'] = _enc_array([fields['/A'], new])
        meta = copy.copy(meta); meta['attr'] = True  # only this lookup is called once per new owner below
        return new['v']
    created_attrs = {}
    for plan in plans:
        graph._tick(cancel)
        for ident, key, value, destination in _field_changes(plan):
            if destination == 'node': fields = node_fields(ident)
            else:
                cache_key = (plan['id'], ident)
                if cache_key not in created_attrs: created_attrs[cache_key] = attr_fields(ident, plan)
                fields = created_attrs[cache_key]
            if value is None: fields.pop(key, None)
            else: fields[key] = copy.deepcopy(value)
    if plans and (plans[0]['index']['root'] is None and plans[0]['final_ids'] or plans[0]['index']['root'] is not None and plans[0]['final_ids'] != plans[0]['index']['entries']):
        plan = plans[0]; root = node_fields(graph._id(plan['root'])); layout = _index_layout(plan)
        def set_array(fields, key, values):
            old = fields.get(key)
            if old is not None and resolve(old).get('t') == 'array': resolve(old)['v'] = values
            else: fields[key] = _enc_array(values)
        if plan['index']['root'] is None:
            if plan['final_ids']: root['/IDTree'] = _enc_dict({'/Names': _enc_array([value for raw, target in layout[0][1] for value in (_enc_string(raw), {'ref': target})])})
        else:
            # Locate direct as well as indirect name-tree nodes by walking the encoded original.
            leaf_index = [0]
            def edit_tree(raw):
                fields = resolve(raw)['v']; source = None
                if '/Names' in fields:
                    current = resolve(fields['/Names'])['v']; old_pairs = [(bytes.fromhex(resolve(current[n])['v']), current[n + 1]['ref']) for n in range(0, len(current), 2)]
                    index = leaf_index[0]; leaf_index[0] += 1
                    if index >= len(layout) or plan['index']['leaves'][index]['pairs'] != old_pairs:
                        _fail('Independent IDTree leaf identity changed')
                    source = layout[index][1]
                    originals = {pair: (current[n * 2], current[n * 2 + 1]) for n, pair in enumerate(old_pairs)}
                    set_array(fields, '/Names', [value for raw_key, target in source for value in originals.get((raw_key, target), (_enc_string(raw_key), {'ref': target}))])
                    keys = [raw_key for raw_key, _ in source]
                else:
                    keys = []
                    for child in resolve(fields['/Kids'])['v']: keys += edit_tree(child)
                if '/Limits' in fields:
                    if keys:
                        original_limits = resolve(fields['/Limits'])['v']
                        if [resolve(value) for value in original_limits] != [_enc_string(keys[0]), _enc_string(keys[-1])]:
                            set_array(fields, '/Limits', [_enc_string(keys[0]), _enc_string(keys[-1])])
                    else: fields.pop('/Limits', None)
                return keys
            edit_tree(root['/IDTree'])
    return expected


def _pdf_value(encoded):
    if encoded['t'] == 'name': return pikepdf.Name(encoded['v'])
    if encoded['t'] == 'string': return pikepdf.String(bytes.fromhex(encoded['v']))
    if encoded['t'] == 'number': return int(Decimal(encoded['v']))
    if encoded['t'] == 'array': return pikepdf.Array([_pdf_value(x) for x in encoded['v']])
    _fail('Unsupported table writer value')


def apply_prepared(pdf, plans, *, cancel=None):
    before = graph._snapshot(pdf, cancel); expected = expected_snapshot(before, plans, cancel=cancel); created_attrs = {}
    for plan in plans:
        graph._tick(cancel)
        for ident, key, value, destination in _field_changes(plan):
            node = plan['nodes'][ident]['node']; target = node
            if destination == 'attr':
                cache_key = (plan['id'], ident)
                if cache_key not in created_attrs:
                    meta = plan['attributes'][ident]; target = meta['attr']
                    if target is None:
                        target = pikepdf.Dictionary(O=pikepdf.Name.Table); raw = node.get('/A')
                        if raw is None: node['/A'] = target
                        elif isinstance(raw, pikepdf.Array): raw.append(target)
                        else: node['/A'] = pikepdf.Array([raw, target])
                    created_attrs[cache_key] = target
                target = created_attrs[cache_key]
            if value is None:
                if key in target: del target[key]
            else: target[key] = _pdf_value(value)
    if plans and (plans[0]['index']['root'] is None and plans[0]['final_ids'] or plans[0]['index']['root'] is not None and plans[0]['final_ids'] != plans[0]['index']['entries']):
        plan = plans[0]; index = plan['index']; layout = _index_layout(plan)
        if index['root'] is None:
            if plan['final_ids']:
                plan['root']['/IDTree'] = pikepdf.Dictionary(Names=pikepdf.Array([value for raw, ident in layout[0][1] for value in (pikepdf.String(raw), plan['nodes'][ident]['node'])]))
        else:
            def set_array(node, key, values):
                old = node.get(key)
                if isinstance(old, pikepdf.Array):
                    while len(old): del old[-1]
                    old.extend(values)
                else: node[key] = pikepdf.Array(values)
            for node, pairs in layout:
                original = node['/Names']
                originals = {(bytes(original[n]), graph._id(original[n + 1])): (original[n], original[n + 1]) for n in range(0, len(original), 2)}
                set_array(node, '/Names', [value for raw, ident in pairs for value in originals.get((raw, ident), (pikepdf.String(raw), plan['nodes'][ident]['node']))])
            def limits(node):
                if '/Names' in node: keys = [bytes(node['/Names'][n]) for n in range(0, len(node['/Names']), 2)]
                else: keys = [raw for child in node['/Kids'] for raw in limits(child)]
                if '/Limits' in node:
                    if keys:
                        if [bytes(value) for value in node['/Limits']] != [keys[0], keys[-1]]:
                            set_array(node, '/Limits', [pikepdf.String(keys[0]), pikepdf.String(keys[-1])])
                    else: del node['/Limits']
                return keys
            limits(index['root'])
    if canonical_snapshot(graph._snapshot(pdf, cancel)) != canonical_snapshot(expected):
        _fail('The table writer changed fields outside the exact reviewed cell metadata, summary and ID index')
    return [plan['id'] for plan in plans]
