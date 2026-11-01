"""Narrow, provable repairs for designed (publisher-made) PDFs.

Page designs often repeat one drawing (a header, a footer, a background panel) as a Form XObject that many pages
draw. The tagging engine tags such a form once but claims it once per use, so the structure links break and the
strict PDF/UA check fails. This module has two bounded steps, each recording exactly what it did and each followed
by an all-page fidelity gate (every page picture, box and annotation identical; no text token added or removed):

* ``unshare_forms`` runs BEFORE the engine. Every repeated use of a form gets its own byte-identical copy.
* ``repair_tagged_output`` runs AFTER the engine and
    - removes structure references to marked content that does not exist (never moves one to nearby content;
      an emptied element that carries only a placeholder description such as "image 33" is set aside and noted for
      review, an element that carries real replacement text still refuses);
    - drops a structure-element ID that nothing refers to and that no IDTree indexes;
    - removes the optional CIDSet lists of embedded fonts, but only when the caller was given explicit consent.

Three more steps run on a file whose author already tagged it, so the author's work is kept rather than redone:

* ``cover_unmarked_graphics`` marks a few unmarked pictures and drawings as page decoration (never text), so the author's
  tags and picture descriptions can stay; the review is told which pieces were marked.
* ``repair_author_tags`` maps browser-style inline types (Strong, Em) to Span in the RoleMap, turns a Figure that only wraps another
  Figure into a Div, and gives a visible Link with no /Contents the words printed under it, so the strict check accepts the tags.
* ``author_descriptions`` lists the picture descriptions in existing tags, so a rebuild that cannot keep them says so.

Nothing here makes a document accessible; the strict validator, the inspector and the human review still decide.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import itertools
from pathlib import Path

import pikepdf

from .checks import PLACEHOLDER_ALT
from .inspection import PAINT, compare_fidelity
from .preservation import PreservationRefusal, _ident, _prune_refs, _structure_refs

VERSION = 'designed-pdf-repairs-2'
MAX_DEPTH = 12
MAX_NODES = 200_000
TEXT_KEYS = ('/Alt', '/ActualText', '/E')


class _Refusal(Exception):
    """The file is outside the proven shapes; the step does nothing."""


def _og(obj):
    return tuple(obj.objgen) if getattr(obj, 'is_indirect', False) else None


def _page_resources(page_object):
    node = page_object
    while node is not None:
        if '/Resources' in node:
            return node['/Resources']
        node = node.get('/Parent')
    return None


def _instructions(holder):
    try:
        return list(pikepdf.parse_content_stream(holder))
    except Exception as exc:  # pikepdf raises PdfError or ValueError on damaged streams
        raise _Refusal('A content stream could not be read (%s).' % type(exc).__name__) from exc


def _form_calls(items, xobjects):
    """(index, name, form) for every Do that draws a Form XObject."""
    for index, item in enumerate(items):
        if hasattr(item, 'operator') and str(item.operator) == 'Do' and len(item.operands) == 1 and item.operands[0] in xobjects:
            form = xobjects[item.operands[0]]
            if str(form.get('/Subtype', '')) == '/Form':
                yield index, item.operands[0], form


def _private_resources(resources):
    fresh, objects = pikepdf.Dictionary(), pikepdf.Dictionary()
    if resources is not None:
        for key in resources.keys():
            fresh[key] = resources[key]
        if '/XObject' in resources:
            for key in resources['/XObject'].keys():
                objects[key] = resources['/XObject'][key]
    fresh['/XObject'] = objects
    return fresh


def _form_uses(pdf):
    """Read-only count of how many times each Form XObject is drawn, nested draws included."""
    uses, nodes = Counter(), [0]

    def visit(holder, is_page, inherited, trail, depth):
        nodes[0] += 1
        if nodes[0] > MAX_NODES or depth > MAX_DEPTH:
            raise _Refusal('The page designs nest or repeat forms beyond the supported size.')
        resources = _page_resources(holder) if is_page else holder.get('/Resources', inherited)
        if resources is None or '/XObject' not in resources:
            return
        for _, _, form in _form_calls(_instructions(holder), resources['/XObject']):
            key = _og(form)
            if key in trail:
                raise _Refusal('A form draws itself.')
            uses[key] += 1
            visit(form, False, resources, trail | {key}, depth + 1)

    for page in pdf.pages:
        visit(page.obj, True, None, frozenset(), 0)
    return uses


def _fidelity_gate(before, after, cancel=None):
    report = compare_fidelity(before, after, cancel=cancel)
    pages = report.get('pages', [])
    visible = bool(pages) and all(all(p.get(k) == 'pass' for k in ('render_status', 'dimensions_status', 'page_boxes_status', 'annotations_status')) for p in pages)
    text = all(p.get('text', {}).get('removed_tokens', 1) == 0 and p.get('text', {}).get('added_tokens', 1) == 0 for p in pages)
    other = [c for c in report.get('checks', []) if c.get('id', c.get('name')) != 'all-page-render-and-content']
    ok = visible and text and all(c.get('status') in ('pass', 'not-applicable') for c in other)
    return {'status': 'pass' if ok else 'fail', 'pages_compared': len(pages),
            'policy': 'Every page picture, box and annotation identical; no text token added or removed.'}


def unshare_forms(source, destination, cancel=None):
    """Give every repeated use of a Form XObject its own copy, or leave the file alone."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise FileExistsError('Unsharing requires a distinct new output')
    result = {'name': 'unshared-forms', 'version': VERSION, 'status': 'not-needed', 'independent_validation_required': True}
    partial = destination.with_name(destination.name + '.unshare-partial')
    if partial.exists():
        raise FileExistsError('Unsharing checkpoint already exists')
    try:
        with pikepdf.open(source) as pdf:
            if pdf.is_encrypted:
                return {**result, 'status': 'refused', 'reason': 'Encrypted files are outside this repair.'}
            if '/StructTreeRoot' in pdf.Root:
                return {**result, 'reason': 'The file already has a structure tree; its forms are left untouched.'}
            if not any(count > 1 for count in _form_uses(pdf).values()):
                return result
            claimed, made, uses, nodes = set(), Counter(), [0], [0]
            names = itertools.count(1)

            def clone_of(form):
                copy = pikepdf.Stream(pdf, form.read_raw_bytes())
                for key in form.keys():
                    if key != '/Length':
                        copy[key] = form[key]
                if copy.read_bytes() != form.read_bytes():
                    raise _Refusal('A copied form does not decode to the same bytes.')
                return copy

            def visit(holder, is_page, inherited, trail, depth):
                nodes[0] += 1
                if nodes[0] > MAX_NODES or depth > MAX_DEPTH:
                    raise _Refusal('The page designs nest or repeat forms beyond the supported size.')
                resources = _page_resources(holder) if is_page else holder.get('/Resources', inherited)
                if resources is None or '/XObject' not in resources:
                    return
                items = _instructions(holder)
                replaced, fresh = {}, None
                for index, name, form in _form_calls(items, resources['/XObject']):
                    key = _og(form)
                    uses[0] += 1
                    if key in trail:
                        raise _Refusal('A form draws itself.')
                    if key not in claimed:
                        claimed.add(key)
                        visit(form, False, resources, trail | {key}, depth + 1)
                        continue
                    copy = clone_of(form)
                    claimed.add(_og(copy))
                    if fresh is None:
                        fresh = _private_resources(resources)
                    label = pikepdf.Name('/FmCopy%d' % next(names))
                    while label in fresh['/XObject']:
                        label = pikepdf.Name('/FmCopy%d' % next(names))
                    fresh['/XObject'][label] = copy
                    replaced[index] = pikepdf.ContentStreamInstruction([label], pikepdf.Operator('Do'))
                    made[key[0]] += 1
                    visit(copy, False, fresh, trail | {key}, depth + 1)
                if replaced:
                    data = pikepdf.unparse_content_stream([replaced.get(i, item) for i, item in enumerate(items)])
                    if is_page:
                        holder['/Contents'] = pdf.make_stream(data)
                    else:
                        holder.write(data)
                    holder['/Resources'] = fresh

            for page in pdf.pages:
                visit(page.obj, True, None, frozenset(), 0)
            if not made:
                return result
            pdf.save(partial, deterministic_id=True)
        with pikepdf.open(partial) as written:
            still_shared = sum(1 for count in _form_uses(written).values() if count > 1)
        gate = _fidelity_gate(source, partial, cancel)
        result.update(forms_unshared=len(made), copies_made=sum(made.values()), form_uses=uses[0], shared_forms_left=still_shared,
                      visible_preservation=gate,
                      scope='Each repeated use of a page-design form now has its own byte-identical copy; page content is otherwise unchanged.')
        if gate['status'] != 'pass':
            partial.unlink()
            return {**result, 'status': 'refused', 'reason': 'The copied forms changed a page; the original was kept.'}
        partial.replace(destination)
        result['status'] = 'pass' if not still_shared else 'partial'
        return result
    except _Refusal as exc:
        if partial.exists():
            partial.unlink()
        return {**result, 'status': 'refused', 'reason': str(exc)}
    except (pikepdf.PdfError, ValueError, KeyError, TypeError) as exc:
        if partial.exists():
            partial.unlink()
        return {**result, 'status': 'refused', 'reason': 'The file could not be rewritten safely (%s).' % type(exc).__name__}


def _present_marked_content(pdf):
    """Marked-content IDs that exist in the drawing, keyed like the structure references.

    Returns (present, forms_of_page): present holds (stream, mcid) where stream is a page index or a form's object id;
    forms_of_page maps a page index to the forms it draws, so a reference that points at the wrong stream can be told
    from one that points at nothing.
    """
    present, scanned, forms_of_page, nodes = set(), set(), defaultdict(set), [0]

    def scan(holder, key, resources, page, depth):
        nodes[0] += 1
        if nodes[0] > MAX_NODES or depth > MAX_DEPTH:
            raise _Refusal('The page designs nest or repeat forms beyond the supported size.')
        properties = resources.get('/Properties') if resources is not None else None
        xobjects = resources.get('/XObject') if resources is not None else None
        for item in _instructions(holder):
            if not hasattr(item, 'operator'):
                continue
            operator = str(item.operator)
            if operator == 'BDC' and len(item.operands) == 2:
                values = item.operands[1]
                if isinstance(values, pikepdf.Name):
                    values = properties.get(str(values)) if properties is not None else None
                if isinstance(values, pikepdf.Dictionary) and '/MCID' in values:
                    present.add((key, int(values['/MCID'])))
            elif operator == 'Do' and xobjects is not None and len(item.operands) == 1 and item.operands[0] in xobjects:
                form = xobjects[item.operands[0]]
                if str(form.get('/Subtype', '')) == '/Form':
                    form_key = _og(form)
                    forms_of_page[page].add(form_key)
                    if form_key not in scanned:
                        scanned.add(form_key)
                        scan(form, form_key, form.get('/Resources', resources), page, depth + 1)

    for index, page in enumerate(pdf.pages):
        scan(page.obj, index, _page_resources(page.obj), index, 0)
    return present, forms_of_page


def _children(element):
    kids = element.get('/K')
    if kids is None:
        return []
    return list(kids) if isinstance(kids, pikepdf.Array) else [kids]


def _only_content_references(element):
    return all(isinstance(child, int) or (isinstance(child, pikepdf.Dictionary) and '/MCID' in child and '/S' not in child) for child in _children(element))


def _set_aside_placeholders(refs, dangling, forms_of_page):
    """Set aside the placeholder description of an element whose every content reference is missing."""
    by_owner = defaultdict(list)
    for key, owner in refs.items():
        by_owner[_ident(owner)].append(key)
    set_aside = []
    for ident, keys in by_owner.items():
        if not all(key in dangling for key in keys):
            continue
        element = refs[keys[0]]
        present_keys = [key for key in TEXT_KEYS if key in element]
        if present_keys != ['/Alt']:
            continue
        description = str(element['/Alt']).strip()
        if not PLACEHOLDER_ALT.search(description) or not _only_content_references(element) or len(_children(element)) != len(keys):
            continue
        stream = keys[0][0]
        page = stream if isinstance(stream, int) else min((number for number, forms in forms_of_page.items() if stream in forms), default=None)
        set_aside.append({'element': '%d %d R' % ident, 'role': str(element.get('/S', '')), 'description': description,
                          'references': len(keys), 'page': None if page is None else page + 1})
        del element['/Alt']
    return set_aside


def _unused_ids(pdf):
    """Elements whose /ID nothing refers to, when no IDTree exists; otherwise nothing to drop."""
    root = pdf.Root['/StructTreeRoot']
    if '/IDTree' in root:
        return [], None
    carriers, named, seen, stack = [], set(), set(), [(root.get('/K'), 0)]
    while stack:
        node, depth = stack.pop()
        if depth > 400:
            return [], 'The structure tree is deeper than the supported size.'
        if isinstance(node, pikepdf.Array):
            stack.extend((child, depth + 1) for child in node)
        elif isinstance(node, pikepdf.Dictionary) and '/S' in node:
            key = _og(node) or id(node)
            if key in seen:
                continue
            seen.add(key)
            if '/ID' in node:
                carriers.append(node)
            attributes = node.get('/A')
            for attribute in ([] if attributes is None else list(attributes) if isinstance(attributes, pikepdf.Array) else [attributes]):
                if isinstance(attribute, pikepdf.Dictionary) and '/Headers' in attribute:
                    named.update(bytes(name) for name in attribute['/Headers'])
            stack.append((node.get('/K'), depth + 1))
    if any(bytes(node['/ID']) in named for node in carriers):
        return [], 'A table cell refers to a structure ID, so no ID was dropped.'
    return carriers, None


def _cidset_holders(pdf):
    return [obj for obj in pdf.objects if isinstance(obj, pikepdf.Dictionary) and str(obj.get('/Type', '')) == '/FontDescriptor' and '/CIDSet' in obj]


def repair_tagged_output(tagged, destination, *, remove_cidset=False, engine_made=True, cancel=None):
    """Repair the engine's output (or, for CIDSet only, an already tagged file) into a new file, or change nothing."""
    tagged, destination = (Path(p).resolve() for p in (tagged, destination))
    if destination == tagged or destination.exists():
        raise FileExistsError('Repair requires a distinct new output')
    result = {'name': 'tagged-repairs', 'version': VERSION, 'status': 'not-needed', 'independent_validation_required': True,
              'warnings': [], 'set_aside': []}
    partial = destination.with_name(destination.name + '.repair-partial')
    if partial.exists():
        raise FileExistsError('Repair checkpoint already exists')

    def apply(prune):
        details = {'dangling_removed': 0, 'empty_nodes_removed': 0, 'set_aside': [], 'ids_dropped': [], 'cidset_removed': [], 'warnings': []}
        with pikepdf.open(tagged) as pdf:
            if pdf.is_encrypted:
                raise _Refusal('Encrypted files are outside this repair.')
            tree = pdf.Root.get('/StructTreeRoot')
            if engine_made and isinstance(tree, pikepdf.Dictionary):
                if prune:
                    try:
                        refs, parents, page_keys = _structure_refs(pdf)
                    except PreservationRefusal as exc:
                        refs = None
                        details['warnings'].append('Missing structure references were not repaired: ' + str(exc) + '.')
                    if refs is not None:
                        present, forms_of_page = _present_marked_content(pdf)
                        missing = {key for key in refs if key not in present}
                        misplaced = {key for key in missing if isinstance(key[0], int) and any((form, key[1]) in present for form in forms_of_page[key[0]])}
                        if misplaced:
                            details['warnings'].append('%d structure reference(s) point at the wrong stream, not at nothing; they were left for review.' % len(misplaced))
                        dangling = missing - misplaced
                        if dangling:
                            details['set_aside'] = _set_aside_placeholders(refs, dangling, forms_of_page)
                            counts = Counter()
                            _prune_refs(pdf, dangling, page_keys, parents, {}, counts)
                            details['dangling_removed'] = len(dangling)
                            details['empty_nodes_removed'] = counts['empty_engine_structure_nodes_removed']
                carriers, why = _unused_ids(pdf)
                if why:
                    details['warnings'].append(why)
                if carriers:
                    details['ids_dropped'] = [{'role': str(node.get('/S', '')), 'id': bytes(node['/ID']).decode('latin-1')} for node in carriers]
                    for node in carriers:
                        del node['/ID']
            if remove_cidset:
                holders = _cidset_holders(pdf)
                details['cidset_removed'] = sorted({str(holder.get('/FontName', '')) for holder in holders})
                details['cidset_lists'] = len(holders)
                for holder in holders:
                    del holder['/CIDSet']
            if not (details['dangling_removed'] or details['ids_dropped'] or details['cidset_removed']):
                return details, False
            pdf.save(partial, deterministic_id=True)
            return details, True

    try:
        try:
            details, changed = apply(True)
        except (_Refusal, PreservationRefusal, KeyError, TypeError, IndexError, ValueError) as exc:
            if partial.exists():
                partial.unlink()
            result['warnings'].append('Missing structure references were not repaired: %s.' % exc)
            result['prune_refused'] = str(exc)
            details, changed = apply(False)
        result['warnings'] += details.pop('warnings')
        result.update(details)
        if not changed:
            if 'prune_refused' in result:
                return {**result, 'status': 'refused', 'reason': result['prune_refused']}
            return result
        gate = _fidelity_gate(tagged, partial, cancel)
        result['visible_preservation'] = gate
        if gate['status'] != 'pass':
            partial.unlink()
            return {**result, 'status': 'refused', 'reason': 'The repair changed a page; the engine output was kept as it was.'}
        partial.replace(destination)
        result['status'] = 'pass'
        return result
    except _Refusal as exc:
        if partial.exists():
            partial.unlink()
        return {**result, 'status': 'refused', 'reason': str(exc)}
    except (pikepdf.PdfError, ValueError, KeyError, TypeError) as exc:
        if partial.exists():
            partial.unlink()
        return {**result, 'status': 'refused', 'reason': 'The file could not be rewritten safely (%s).' % type(exc).__name__}


# ---------------------------------------------------------------------------------------------------------------------
# Keeping an author's own tags: three small steps that run on an already tagged file.
# ---------------------------------------------------------------------------------------------------------------------

STANDARD_TYPES = frozenset('/' + name for name in (
    'Document Part Art Sect Div BlockQuote Caption TOC TOCI Index NonStruct Private P H H1 H2 H3 H4 H5 H6 L LI Lbl LBody '
    'Table TR TH TD THead TBody TFoot Span Quote Note Reference BibEntry Code Link Annot Ruby RB RT RP Warichu WT WP '
    'Figure Formula Form').split())
# Browser-made PDFs name bold and emphasised text after the HTML element. PDF has no such types; Span is the standard inline type.
INLINE_ROLES = {'/Strong': '/Span', '/Em': '/Span', '/Emphasis': '/Span'}
MAX_COVERED = 25
_PATH_BUILD = frozenset(('m', 'l', 'c', 'v', 'y', 'h', 're'))
_PATH_PAINT = frozenset(('S', 's', 'f', 'F', 'f*', 'B', 'B*', 'b', 'b*'))
_TEXT_SHOW = frozenset(('Tj', 'TJ', "'", '"'))


def _structure_types(pdf):
    """Every structure type name in the tree with how many elements use it."""
    tree = pdf.Root.get('/StructTreeRoot')
    counts, seen, nodes = Counter(), set(), 0
    stack = [tree.get('/K')] if isinstance(tree, pikepdf.Dictionary) else []
    while stack:
        node = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise _Refusal('The structure tree is larger than the supported size.')
        if isinstance(node, pikepdf.Array):
            stack.extend(node)
        elif isinstance(node, pikepdf.Dictionary):
            key = _og(node)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            if '/S' in node:
                counts[str(node['/S'])] += 1
                stack.append(node.get('/K'))
    return counts


def _wrapper_figures(pdf):
    """Figure elements that only wrap other elements: no description, no content of their own, and a Figure inside.

    A browser writes an HTML figure (picture plus caption) as a Figure around the picture's own Figure. The wrapper
    has nothing to describe, so the strict check fails it; as a plain Div it keeps its place and its children.
    """
    found, seen, nodes = [], set(), 0
    stack = [pdf.Root['/StructTreeRoot'].get('/K')]
    while stack:
        node = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise _Refusal('The structure tree is larger than the supported size.')
        if isinstance(node, pikepdf.Array):
            stack.extend(node)
        elif isinstance(node, pikepdf.Dictionary) and '/S' in node:
            key = _og(node)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            children = _children(node)
            if (str(node['/S']) == '/Figure' and not str(node.get('/Alt', '')).strip() and not str(node.get('/ActualText', '')).strip()
                    and children and all(isinstance(child, pikepdf.Dictionary) and '/S' in child for child in children)
                    and any(str(child['/S']) == '/Figure' for child in children)):
                found.append(node)
            stack.append(node.get('/K'))
    return found


def _undescribed_links(pdf):
    """[(page index, annotation)] for visible Link annotations that have no /Contents."""
    found = []
    for number, page in enumerate(pdf.pages):
        for annotation in page.obj.get('/Annots', []):
            if (isinstance(annotation, pikepdf.Dictionary) and str(annotation.get('/Subtype', '')) == '/Link'
                    and not str(annotation.get('/Contents', '')).strip() and not int(annotation.get('/F', 0)) & 2 and '/Rect' in annotation):
                found.append((number, annotation))
    return found


def _link_text(document, number, annotation):
    """The words printed under a link's rectangle, or the link address when nothing is printed there."""
    x0, y0, x1, y1 = (float(value) for value in annotation['/Rect'])
    text = document[number].get_textpage().get_text_bounded(left=min(x0, x1), bottom=min(y0, y1), right=max(x0, x1), top=max(y0, y1))
    text = ' '.join(str(text).split())[:200]
    if text:
        return text, 'visible text'
    action = annotation.get('/A')
    uri = str(action.get('/URI', '')).strip() if isinstance(action, pikepdf.Dictionary) and str(action.get('/S', '')) == '/URI' else ''
    return (uri[:200], 'link address') if uri else ('', '')


def _blank_repairs():
    return {'mapped': {}, 'left_alone': {}, 'retyped': 0, 'links_described': []}


def repair_author_tags(source, destination, cancel=None):
    """Make small, provable fixes that let an author's own tags pass the strict check, or change nothing.

    * Browser-style inline types (Strong, Em) get RoleMap entries that send them to the standard Span.
    * A Figure that only wraps another Figure becomes a Div.
    * A visible Link annotation with no /Contents gets the words printed under it (or its address when nothing is printed).

    Nothing on a page changes; the all-page fidelity gate must pass or the file is kept as it was.
    """
    import pypdfium2 as pdfium
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise FileExistsError('Repair requires a distinct new output')
    result = {'name': 'author-tag-repairs', 'version': VERSION, 'status': 'not-needed', 'independent_validation_required': True, **_blank_repairs()}
    partial = destination.with_name(destination.name + '.author-partial')
    if partial.exists():
        raise FileExistsError('Repair checkpoint already exists')
    document = None
    try:
        with pikepdf.open(source) as pdf:
            if pdf.is_encrypted:
                return result
            tree = pdf.Root.get('/StructTreeRoot')
            if not isinstance(tree, pikepdf.Dictionary):
                return result
            role_map = tree.get('/RoleMap')
            known = {str(key) for key in role_map.keys()} if isinstance(role_map, pikepdf.Dictionary) else set()
            wanted = {}
            for name, count in _structure_types(pdf).items():
                if name in STANDARD_TYPES or name in known:
                    continue
                if name in INLINE_ROLES:
                    wanted[name] = count
                else:
                    result['left_alone'][name] = count
            wrappers = _wrapper_figures(pdf)
            links = _undescribed_links(pdf)
            if not (wanted or wrappers or links):
                return result
            if wanted:
                if not isinstance(role_map, pikepdf.Dictionary):
                    role_map = pdf.make_indirect(pikepdf.Dictionary())
                    tree['/RoleMap'] = role_map
                for name in wanted:
                    role_map[name] = pikepdf.Name(INLINE_ROLES[name])
                    result['mapped'][name] = {'to': INLINE_ROLES[name], 'elements': wanted[name]}
            for node in wrappers:
                node['/S'] = pikepdf.Name.Div
            result['retyped'] = len(wrappers)
            if links:
                document = pdfium.PdfDocument(str(source))
                for number, annotation in links:
                    text, origin = _link_text(document, number, annotation)
                    if text:
                        annotation['/Contents'] = pikepdf.String(text)
                        result['links_described'].append({'page': number + 1, 'description': text, 'from': origin})
            if not (result['mapped'] or result['retyped'] or result['links_described']):
                return result
            pdf.save(partial, deterministic_id=True)
        gate = _fidelity_gate(source, partial, cancel)
        result['visible_preservation'] = gate
        if gate['status'] != 'pass':
            partial.unlink()
            return {**result, **_blank_repairs(), 'status': 'refused', 'reason': 'The tag repair changed a page; the file was kept as it was.'}
        partial.replace(destination)
        result['status'] = 'pass'
        return result
    except _Refusal as exc:
        if partial.exists():
            partial.unlink()
        return {**result, **_blank_repairs(), 'status': 'refused', 'reason': str(exc)}
    except (pikepdf.PdfError, ValueError, KeyError, TypeError, OSError) as exc:
        if partial.exists():
            partial.unlink()
        return {**result, **_blank_repairs(), 'status': 'refused', 'reason': 'The file could not be rewritten safely (%s).' % type(exc).__name__}
    finally:
        if document is not None:
            document.close()


def author_descriptions(source):
    """Picture descriptions already written into a file's tags (placeholders such as "image 3" excluded), with their pages."""
    found = []
    try:
        with pikepdf.open(source) as pdf:
            tree = pdf.Root.get('/StructTreeRoot')
            if not isinstance(tree, pikepdf.Dictionary):
                return found
            index = {tuple(page.obj.objgen): number for number, page in enumerate(pdf.pages, start=1)}
            seen, nodes = set(), 0
            stack = [(tree.get('/K'), None)]
            while stack:
                node, page = stack.pop()
                nodes += 1
                if nodes > MAX_NODES:
                    return found
                if isinstance(node, pikepdf.Array):
                    stack.extend((child, page) for child in reversed(list(node)))
                elif isinstance(node, pikepdf.Dictionary) and '/S' in node:
                    key = _og(node)
                    if key is not None:
                        if key in seen:
                            continue
                        seen.add(key)
                    here = index.get(tuple(node['/Pg'].objgen), page) if '/Pg' in node and getattr(node['/Pg'], 'is_indirect', False) else page
                    if str(node['/S']) in ('/Figure', '/Formula') and '/Alt' in node:
                        text = str(node['/Alt']).strip()
                        if text and not PLACEHOLDER_ALT.search(text):
                            found.append({'page': here, 'role': str(node['/S']).lstrip('/'), 'description': text[:400]})
                    stack.append((node.get('/K'), here))
    except (pikepdf.PdfError, ValueError, KeyError, TypeError, AttributeError):
        return found
    return found


def _plain_graphic(form, depth=0, trail=frozenset()):
    """A Form XObject that paints no text and carries no marking of its own, so hiding it hides no reading content."""
    key = _og(form)
    if depth > MAX_DEPTH or key in trail:
        return False
    resources = form.get('/Resources')
    xobjects = resources.get('/XObject') if resources is not None else None
    for operands, operator in _instructions(form):
        op = str(operator)
        if op in _TEXT_SHOW or op in ('BDC', 'BMC', 'EMC'):
            return False
        if op == 'Do':
            target = xobjects.get(str(operands[0])) if xobjects is not None and operands else None
            if target is None:
                return False
            if str(target.get('/Subtype', '')) == '/Form' and not _plain_graphic(target, depth + 1, trail | {key}):
                return False
    return True


def _unmarked_graphics(page):
    """Instruction ranges of paints that no marking covers: [(start, end, kind)]. Unmarked text is a refusal, not a repair."""
    resources = _page_resources(page.obj)
    properties = resources.get('/Properties') if resources is not None else None
    xobjects = resources.get('/XObject') if resources is not None else None
    items = _instructions(page.obj)
    stack, found = [], []
    for index, item in enumerate(items):
        operands, operator = item
        op = str(operator)
        if op in ('BDC', 'BMC'):
            tag = str(operands[0]) if operands else ''
            values = operands[1] if len(operands) > 1 else None
            if isinstance(values, pikepdf.Name) and properties is not None:
                values = properties.get(str(values))
            stack.append(tag == '/Artifact' or (isinstance(values, pikepdf.Dictionary) and '/MCID' in values))
            continue
        if op == 'EMC':
            if stack:
                stack.pop()
            continue
        if op not in PAINT or any(stack):
            continue
        start, kind = index, None
        if op in _TEXT_SHOW:
            if not any(str(v) for v in operands):
                continue
            raise _Refusal("Page text is outside the author's tags, so the tags cannot be kept as they are.")
        if op == 'Do':
            target = xobjects.get(str(operands[0])) if xobjects is not None and operands else None
            if target is None:
                continue
            subtype = str(target.get('/Subtype', ''))
            if subtype == '/Image':
                kind = 'image'
            elif subtype == '/Form' and _plain_graphic(target):
                kind = 'form'
            else:
                continue
        elif op in ('BI', 'INLINE IMAGE'):
            kind = 'inline-image'
        elif op in _PATH_PAINT or op == 'sh':
            kind = 'vector'
            while start > 0 and str(items[start - 1][1]) in _PATH_BUILD:
                start -= 1
        if kind:
            found.append((start, index, kind))
    return items, found


def cover_unmarked_graphics(source, destination, cancel=None):
    """Mark a few unmarked pictures and drawings as page decoration so an author's own tags can be kept, or change nothing.

    Only images, plain drawings and plain graphic forms are covered; unmarked text, a form with its own marking and more than
    25 pieces are refusals (the file then goes the engine route, as before). The result must pass the linkage and coverage
    checks and the all-page fidelity gate, and the review is told exactly which pieces were marked.
    """
    from .inspection import inspect_pdf
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise FileExistsError('Covering requires a distinct new output')
    result = {'name': 'covered-graphics', 'version': VERSION, 'status': 'not-needed', 'independent_validation_required': True, 'covered': []}
    partial = destination.with_name(destination.name + '.cover-partial')
    if partial.exists():
        raise FileExistsError('Covering checkpoint already exists')
    try:
        with pikepdf.open(source) as pdf:
            if pdf.is_encrypted or not isinstance(pdf.Root.get('/StructTreeRoot'), pikepdf.Dictionary):
                return result
            plans = []
            for number, page in enumerate(pdf.pages, start=1):
                items, found = _unmarked_graphics(page)
                if found:
                    plans.append((number, page, items, found))
                    result['covered'] += [{'page': number, 'kind': kind} for _, _, kind in found]
            if not plans:
                return result
            if len(result['covered']) > MAX_COVERED:
                raise _Refusal("More than %d pieces lie outside the author's tags." % MAX_COVERED)
            for number, page, items, found in plans:
                before, after = Counter(start for start, _, _ in found), Counter(end for _, end, _ in found)
                rebuilt = []
                for index, item in enumerate(items):
                    rebuilt += [([pikepdf.Name.Artifact], pikepdf.Operator('BMC'))] * before.get(index, 0)
                    rebuilt.append(item)
                    rebuilt += [([], pikepdf.Operator('EMC'))] * after.get(index, 0)
                page.obj['/Contents'] = pdf.make_stream(pikepdf.unparse_content_stream(rebuilt))
            pdf.save(partial, deterministic_id=True)
        gate = _fidelity_gate(source, partial, cancel)
        result['visible_preservation'] = gate
        if gate['status'] != 'pass':
            raise _Refusal('Covering changed a page; the file was kept as it was.')
        after_inspection = inspect_pdf(partial, cancel=cancel)
        for kind in ('content-linkage', 'content-coverage'):
            check = next((c for c in after_inspection.get('checks', []) if c.get('id', c.get('name')) == kind), {})
            if check.get('status') != 'pass':
                raise _Refusal('The tags still fail the %s check after covering, so they cannot be kept as they are.' % kind)
        partial.replace(destination)
        result['status'] = 'pass'
        return result
    except _Refusal as exc:
        if partial.exists():
            partial.unlink()
        return {**result, 'covered': [], 'status': 'refused', 'reason': str(exc)}
    except (pikepdf.PdfError, ValueError, KeyError, TypeError, IndexError) as exc:
        if partial.exists():
            partial.unlink()
        return {**result, 'covered': [], 'status': 'refused', 'reason': 'The file could not be rewritten safely (%s).' % type(exc).__name__}
