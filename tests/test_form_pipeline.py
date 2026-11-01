"""Independently authored static forms, reviewed edits and preservation proof.

Only the strict CLI is a unit-test double. The parent also runs this fixture
through the private Windows worker and real validator without a browser.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import textwrap

import pikepdf
import pytest
from reportlab.pdfgen import canvas

from pdf_remediator import checks, inspection, pipeline, sidecar, workspace
from pdf_remediator.config import RuntimeConfig
from pdf_remediator.sidecar import (FORM_INVENTORY_PROFILE, EMPTY_TAG_INVENTORY_PROFILE, TABLE_INVENTORY_PROFILE,
    SEMANTIC_TREE_INVENTORY_PROFILE, NAVIGATION_INVENTORY_PROFILE,
    PASSAGE_LANGUAGE_INVENTORY_PROFILE, ARTIFACT_STRUCTURE_INVENTORY_PROFILE,
    STRUCTURAL_INVENTORY_PROFILE, LEGACY_INVENTORY_PROFILE,
    bind_approval, collect_decisions, file_sha256, load_sidecar, write_sidecar)
from test_artifact_structure_pipeline import canonical, files, exact_fidelity
from test_language import TEXTS
from test_language_scopes import registered_language_fonts
from test_pipeline import fast_validator, tagged_control

KIND = 'form-controls'
REVIEWER = 'Synthetic form reviewer'
OLD_PROFILES = [LEGACY_INVENTORY_PROFILE, STRUCTURAL_INVENTORY_PROFILE,
    ARTIFACT_STRUCTURE_INVENTORY_PROFILE, PASSAGE_LANGUAGE_INVENTORY_PROFILE,
    NAVIGATION_INVENTORY_PROFILE, SEMANTIC_TREE_INVENTORY_PROFILE, TABLE_INVENTORY_PROFILE]
TOOLTIPS = {'registration.firstName': 'First name (required)',
    'registration.session': 'Session choice', 'updates': 'Receive project updates',
    'notes': 'Additional notes'}
ALTERNATIVES = {name: label + ' form control' for name, label in TOOLTIPS.items()}


def value(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def form_source(directory, *, repaired=False, hazard=None, source_tooltip=None, source_parent_tooltip=None):
    """Two tagged pages, hierarchical/merged fields and immutable live values.

    Visible labels and paragraph MCIDs stay separate from the pure Form sibling
    group. Each Widget has exactly one Form OBJR and a separate ParentTree key.
    Fields/Annots order deliberately differs from the reviewed tag permutation.
    """
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    raw = directory/'paint.pdf'; output = directory/'source.pdf'
    c = canvas.Canvas(str(raw), pagesize=(560, 700), invariant=1)
    c.setTitle('Community project registration and research notes')
    def paint(mcid, role, text, x, y, size=10, wrap=False):
        c._code.append('/'+role+' <</MCID '+str(mcid)+'>> BDC')
        c.setFont('SyntheticVera', size)
        for index, line in enumerate(textwrap.wrap(text, width=94) if wrap else [text]):
            c.drawString(x, y-index*13, line)
        c._code.append('EMC')
    c.bookmarkPage('opening'); c.addOutlineEntry('Project registration', 'opening', level=0)
    paint(0, 'H1', 'Community project registration', 28, 662, 16)
    paint(1, 'P', 'First name (required)', 36, 614)
    paint(2, 'P', 'Receive project updates', 66, 540)
    paint(3, 'P', 'Session choice', 36, 490)
    paint(4, 'P', TEXTS['en'], 28, 415, wrap=True)
    paint(5, 'Link', 'Continue to research notes', 28, 45)
    c.showPage(); c.bookmarkPage('continuation'); c.addOutlineEntry('Research notes', 'continuation', level=0)
    paint(0, 'H1', 'Community research notes', 28, 662, 16)
    paint(1, 'P', 'Additional notes', 36, 614)
    paint(2, 'P', 'First name (repeated from registration)', 36, 490)
    paint(3, 'P', TEXTS['en'], 28, 390, wrap=True)
    paint(4, 'Link', 'Return to project registration', 28, 45)
    c.showPage(); c.save()

    def appearance(pdf, name, text, width=240, height=24):
        path = directory/(name+'-appearance.pdf')
        a = canvas.Canvas(str(path), pagesize=(width, height), invariant=1)
        a._code.append('/Artifact BMC'); a.setFont('SyntheticVera', 10); a.drawString(5, 8, text); a._code.append('EMC')
        a.showPage(); a.save()
        with pikepdf.open(path) as origin:
            stream = pdf.copy_foreign(origin.pages[0].as_form_xobject())
        return stream

    with pikepdf.open(raw) as pdf:
        first, second = pdf.pages
        ap_name = appearance(pdf, 'first-name', 'Pat Jones')
        ap_choice = appearance(pdf, 'session', 'Evening workshop')
        ap_notes = appearance(pdf, 'notes', 'I can help with the community garden.', 400, 48)
        def check_appearance(on):
            commands = '/Artifact BMC q 0 0 0 RG 1 w 1 1 18 18 re S '
            if on: commands += '3 10 m 8 4 l 17 16 l S '
            stream = pdf.make_stream((commands+'Q EMC').encode('ascii'))
            stream.Type = pikepdf.Name.XObject; stream.Subtype = pikepdf.Name.Form
            stream.BBox = pikepdf.Array([0, 0, 20, 20]); stream.Resources = pikepdf.Dictionary()
            return stream
        off, on = check_appearance(False), check_appearance(True)
        font = next(font for font in ap_name.Resources.Font.values() if '/FontDescriptor' in font)
        defaults = pikepdf.Dictionary(Font=pikepdf.Dictionary(FormFont=font))
        group = pdf.make_indirect(pikepdf.Dictionary(T='registration'))
        if source_parent_tooltip is not None: group.TU = pikepdf.String(source_parent_tooltip)
        field = pdf.make_indirect(pikepdf.Dictionary(FT=pikepdf.Name.Tx, T='firstName', Parent=group,
            Ff=2, V='Pat Jones', DV='Default participant', MaxLen=80, DA='/FormFont 10 Tf 0 g'))
        widget = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            Parent=field, P=first.obj, Rect=pikepdf.Array([36, 576, 276, 600]), F=4,
            NM='form-first-name', AP=pikepdf.Dictionary(N=ap_name), StructParent=2))
        field.Kids = pikepdf.Array([widget])
        mirror = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            Parent=field, P=second.obj, Rect=pikepdf.Array([36, 452, 276, 476]), F=4,
            NM='form-first-name-repeated', AP=pikepdf.Dictionary(N=ap_name), StructParent=6))
        field.Kids.append(mirror)
        checkbox = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            FT=pikepdf.Name.Btn, T='updates', Ff=0, V=pikepdf.Name.Yes, DV=pikepdf.Name.Off, AS=pikepdf.Name.Yes,
            P=first.obj, Rect=pikepdf.Array([36, 534, 56, 554]), F=4, NM='form-updates',
            AP=pikepdf.Dictionary(N=pikepdf.Dictionary(Off=off, Yes=on)), StructParent=3))
        choice = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            FT=pikepdf.Name.Ch, T='session', Parent=group, Ff=131072, V='evening', DV='morning',
            Opt=pikepdf.Array([pikepdf.Array(['morning', 'Morning workshop']), pikepdf.Array(['evening', 'Evening workshop'])]),
            I=pikepdf.Array([1]), DA='/FormFont 10 Tf 0 g', P=first.obj,
            Rect=pikepdf.Array([36, 452, 276, 476]), F=4, NM='form-session',
            AP=pikepdf.Dictionary(N=ap_choice), StructParent=4))
        group.Kids = pikepdf.Array([field, choice])
        notes = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Widget,
            FT=pikepdf.Name.Tx, T='notes', Ff=4096, V='I can help with the community garden.', DV='',
            DA='/FormFont 10 Tf 0 g', P=second.obj, Rect=pikepdf.Array([36, 552, 436, 600]), F=4,
            NM='form-notes', AP=pikepdf.Dictionary(N=ap_notes), StructParent=5))
        acro = pdf.make_indirect(pikepdf.Dictionary(Fields=pikepdf.Array([group, checkbox, notes]),
            NeedAppearances=False, DA='/FormFont 10 Tf 0 g', DR=defaults, CO=pikepdf.Array()))
        pdf.Root.AcroForm = acro
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=tree))
        sections = []
        def element(role, parent, page, children=None):
            node = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name('/'+role), P=parent, Pg=page.obj))
            if children is not None: node.K = children
            return node
        arrays = []
        for index, page in enumerate(pdf.pages):
            section = element('Sect', document, page); sections.append(section)
            roles = ['H1', 'P', 'P', 'P', 'P', 'Link'] if index == 0 else ['H1', 'P', 'P', 'P', 'Link']
            owners = [element(role, section, page, mcid) for mcid, role in enumerate(roles)]
            form_group = element('Div', section, page)
            controls = [widget, checkbox, choice] if index == 0 else [notes, mirror]
            form_nodes = []
            for control in controls:
                form = element('Form', form_group, page)
                form.K = pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=control, Pg=page.obj)
                form_nodes.append(form)
            form_group.K = pikepdf.Array(form_nodes)
            link = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([28, 40, 255, 58]), Contents='Research navigation', NM='form-link-'+str(index+1),
                Border=pikepdf.Array([0, 0, 0]), F=4, P=page.obj, StructParent=7+index,
                Dest=pikepdf.Array([second.obj if index == 0 else first.obj, pikepdf.Name.Fit])))
            owners[-1].Alt = 'Read the other project page'
            owners[-1].K = pikepdf.Array([len(owners)-1, pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=link, Pg=page.obj)])
            section.K = pikepdf.Array([*owners[:-1], form_group, owners[-1]])
            page.Annots = pikepdf.Array([*controls, link]); page.StructParents = index
            page.Tabs = pikepdf.Name.S if repaired else pikepdf.Name.R if index == 0 else pikepdf.Name.C
            arrays.extend([index, pikepdf.Array(owners)])
            for control, form in zip(controls, form_nodes): arrays.extend([int(control.StructParent), form])
            arrays.extend([7+index, owners[-1]])
        nums = sorted([(int(arrays[i]), arrays[i+1]) for i in range(0, len(arrays), 2)])
        tree.K = document; document.K = pikepdf.Array(sections)
        tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([item for pair in nums for item in pair])))
        tree.ParentTreeNextKey = 9; pdf.Root.StructTreeRoot = tree
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True); pdf.Root.Lang = 'en-US'
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        # The fixture isolates form-name/navigation faults. Its ordinary XMP
        # metadata is authored correctly up front; the form route must never
        # repair or normalize it as an unreviewed preparation side effect.
        with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False) as metadata:
            metadata['dc:title'] = str(pdf.docinfo.Title)
            metadata['dc:language'] = ['en-US']
            metadata['pdfuaid:part'] = 1
        pdf.Root.Metadata.Type = pikepdf.Name.Metadata
        pdf.Root.Metadata.Subtype = pikepdf.Name.XML
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Dictionary(S=pikepdf.Name.r), 1, pikepdf.Dictionary(S=pikepdf.Name.D, St=4)]))
        pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array(['form-opening', pikepdf.Array([first.obj, pikepdf.Name.XYZ, 0, 680, None])])))
        named = {'registration.firstName': (field, sections[0].K[-2].K[0]),
            'updates': (checkbox, sections[0].K[-2].K[1]),
            'registration.session': (choice, sections[0].K[-2].K[2]), 'notes': (notes, sections[1].K[-2].K[0])}
        if repaired:
            for name, (terminal, owner) in named.items(): terminal.TU = TOOLTIPS[name]; owner.Alt = ALTERNATIVES[name]
            sections[1].K[-2].K[1].Alt = ALTERNATIVES['registration.firstName']
        if source_tooltip is not None: field.TU = pikepdf.String(source_tooltip)
        if hazard == 'xfa': acro.XFA = pdf.make_stream(b'<xdp/>')
        elif hazard == 'need-appearances': acro.NeedAppearances = True
        elif hazard == 'calculation': acro.CO = pikepdf.Array([field])
        elif hazard == 'field-action': field.AA = pikepdf.Dictionary(K=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS='void 0'))
        elif hazard == 'widget-action': widget.A = pikepdf.Dictionary(S=pikepdf.Name.URI, URI='https://example.invalid/')
        elif hazard == 'radio': checkbox.Ff = 32768
        elif hazard == 'pushbutton': checkbox.Ff = 65536
        elif hazard == 'signature': notes.FT = pikepdf.Name.Sig
        elif hazard == 'orphan-widget': del pdf.Root['/AcroForm']
        elif hazard == 'missing-widget': first.Annots = pikepdf.Array([checkbox, choice, first.Annots[-1]])
        elif hazard == 'duplicate-widget': first.Annots.append(widget)
        elif hazard == 'wrong-parent': widget.Parent = notes
        elif hazard == 'duplicate-name': notes.T = 'updates'
        elif hazard == 'wrong-parenttree': tree.ParentTree.Nums[5] = named['updates'][1]
        elif hazard == 'missing-objr': named['registration.firstName'][1].K = pikepdf.Array()
        elif hazard == 'wrong-role': named['registration.firstName'][1].S = pikepdf.Name.P
        elif hazard == 'checkbox-state': checkbox.AS = pikepdf.Name.Off
        elif hazard == 'missing-appearance': del widget['/AP']
        elif hazard == 'hidden': widget.F = 6
        elif hazard == 'unsupported-tabs': first.Tabs = pikepdf.Name.A
        elif hazard == 'choice-value': choice.V = 'unlisted-option'
        elif hazard == 'choice-indices': choice.I = pikepdf.Array([0])
        elif hazard == 'choice-options': choice.Opt = pikepdf.Array(['one', 'one'])
        elif hazard == 'mixed-order': sections[0].K[-2].K = pikepdf.Array([sections[0].K[-2].K[0], sections[0].K[1], *list(sections[0].K[-2].K)[1:]])
        elif hazard is not None: raise ValueError('Unknown authored form hazard')
        with output.open('wb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7')
    return output


def execute(source, output, **kwargs): return pipeline.process_file(source, output, RuntimeConfig(), **kwargs)
def data(report): return load_sidecar(Path(report['bundle_path'])/'decisions.json')
def choose(decisions):
    rows = [row for row in decisions['decisions'] if row['kind'] == KIND]
    assert len(rows) == 1
    assert rows[0]['structural_eligible'], rows[0].get('structural_limitations')
    return rows[0]


def selected_value(decisions, *, reverse=True):
    row = choose(decisions); selected = copy.deepcopy(json.loads(row['current']))
    fields = {field['field']: field for field in row['form_context']['fields']}
    for field in selected['fields']:
        name = fields[field['field']]['name']; field['tooltip'] = TOOLTIPS[name]
        for widget in field['widgets']: widget['alternative'] = ALTERNATIVES[name]
    for page in selected['pages']: page['tabs'] = 'S'
    if reverse:
        for order in selected['orders']: order['children'] = list(reversed(order['children']))
    return value(selected)


def accept(decisions, new_value=None):
    row = choose(decisions); row['value'] = selected_value(decisions) if new_value is None else new_value
    bind_approval(row, REVIEWER, '2026-10-27'); return row


def form_snapshot(path):
    """Literal form oracle keyed by immutable field names, independent of editor IDs."""
    with pikepdf.open(path) as pdf:
        page_numbers = {page.obj.objgen: i+1 for i, page in enumerate(pdf.pages)}
        tree = pdf.Root.StructTreeRoot; by_widget = {}; fields = {}; field_order = []; node_names = {}; nonterminals = {}
        def walk(node, prefix='', parent=None):
            name = prefix + ('.' if prefix else '') + str(node.T); field_order.append(name)
            node_names[node.objgen] = name
            kids = node.get('/Kids')
            if node.get('/Subtype') == pikepdf.Name.Widget: members = [node]
            elif kids is not None and all(kid.get('/Subtype') == pikepdf.Name.Widget for kid in kids): members = list(kids)
            else:
                nonterminals[name] = {str(k): canonical(v) for k, v in node.items() if k not in {'/Parent', '/Kids'}}
                for child in kids: walk(child, name, name)
                return
            fields[name] = {'attributes': {str(k): canonical(v) for k, v in node.items() if k not in {'/Parent', '/Kids', '/P'}},
                'parent_name': parent, 'widgets': []}
            for widget in members:
                by_widget[widget.objgen] = name
                fields[name]['widgets'].append({str(k): canonical(v) for k, v in widget.items() if k not in {'/Parent', '/P'}})
                fields[name]['widgets'][-1]['page'] = page_numbers[widget.P.objgen]
                fields[name]['widgets'][-1]['parent_field'] = node_names.get(widget.Parent.objgen, 'unknown') if '/Parent' in widget else None
        for root in pdf.Root.AcroForm.Fields: walk(root)
        forms = {}; groups = []; owners = {}
        def tags(node):
            if isinstance(node, pikepdf.Array):
                for child in node: tags(child)
            elif isinstance(node, pikepdf.Dictionary) and '/S' in node:
                if node.S == pikepdf.Name.Form:
                    objr = node.K[0] if isinstance(node.K, pikepdf.Array) else node.K
                    name = by_widget[objr.Obj.objgen]; widget_name = str(objr.Obj.NM)
                    forms[widget_name] = {'field': name, 'attributes': {str(k): canonical(v) for k, v in node.items() if k not in {'/P', '/Pg', '/K'}}}
                    owners[node.objgen] = widget_name
                elif node.S == pikepdf.Name.Div:
                    children = list(node.K) if isinstance(node.K, pikepdf.Array) else [node.K]
                    if all(child.S == pikepdf.Name.Form for child in children):
                        groups.append([str((child.K[0] if isinstance(child.K, pikepdf.Array) else child.K).Obj.NM) for child in children])
                tags(node.get('/K'))
        tags(tree.K)
        parent_slots = {}
        for i in range(0, len(tree.ParentTree.Nums), 2):
            key, target = list(tree.ParentTree.Nums)[i:i+2]
            parent_slots[int(key)] = [int(owner.K) if isinstance(owner.K, int) else 'link' for owner in target] if isinstance(target, pikepdf.Array) else owners.get(target.objgen, 'link')
        annotations = [[by_widget.get(annotation.objgen, str(annotation.NM)) for annotation in page.Annots] for page in pdf.pages]
        return {'fields': fields, 'field_order': field_order, 'forms': forms, 'groups': groups,
            'tabs': [str(page.obj.get('/Tabs')) for page in pdf.pages], 'annots': annotations,
            'parent_slots': parent_slots, 'nonterminal_fields': nonterminals,
            'acroform': {str(k): canonical(v) for k, v in pdf.Root.AcroForm.items() if k != '/Fields'}}


def expected_form(before, *, reverse=True):
    expected = copy.deepcopy(before)
    for name, field in expected['fields'].items():
        field['attributes']['/TU'] = canonical(pikepdf.String(TOOLTIPS[name]))
        # Merged fields expose the same permitted TU change as their Widget.
        if '/Subtype' in field['attributes']: field['widgets'][0]['/TU'] = field['attributes']['/TU']
    for owner in expected['forms'].values():
        owner['attributes']['/Alt'] = canonical(pikepdf.String(ALTERNATIVES[owner['field']]))
    expected['tabs'] = ['/S', '/S']
    if reverse: expected['groups'] = [list(reversed(group)) for group in expected['groups']]
    return expected


def fresh_form_reviews(report, decisions):
    row = choose(decisions)
    changed = row['status'] == 'approved' and row['value'] != row['current']
    items = [item for item in report['manual_review']['items'] if item['id'].startswith('form-controls-decision-')]
    assert len(items) == int(changed)
    for item in items:
        assert item['id'] == 'form-controls-decision-'+hashlib.sha256(row['id'].encode()).hexdigest()[:20]
        assert item['category'] == 'form-meaning' and item['required'] is True and item['status'] == 'pending'
        assert item['decision_id'] == row['id'] and item['context_sha256'] == row['context_sha256']
        assert item['evidence'] == {'kind': row['kind'], 'element': row.get('element'), 'structure_path': row.get('structure_path'),
            'references': row['references'], 'binding': row['binding'], 'previous_value': row['current'], 'applied_value': row['value'], 'source_form_context': row['form_context']}
        assert not any(key in item for key in ['reviewer', 'reviewed_at', 'notes', 'approval_sha256'])
    return items


def assert_preserved(source, report):
    assert report['status'] in {'candidate', 'needs-manual'}, report.get('error')
    exact_fidelity(report)
    assert report['data_sent']['document_api_calls'] == 0 and report['settings']['ocr_mode'] == 'off'
    assert report['form_preservation']['status'] == 'pass'
    assert report['inspection']['sha256'] == report['output']['sha256'] == report['gate1']['input_sha256'] == report['fidelity']['after_sha256']
    assert report['form_preservation']['output_sha256'] == report['output']['sha256']


def test_new_form_profile_keeps_seven_previous_inventories_and_verbatim_checkpoint(tmp_path, fast_validator):
    source = form_source(tmp_path/'source'); original = source.read_bytes()
    report = execute(source, tmp_path/'prepared'); decisions = data(report); row = choose(decisions)
    assert decisions['inventory_profile'] == EMPTY_TAG_INVENTORY_PROFILE
    assert row['status'] == 'pending' and row['value'] == row['current']
    assert len(row['form_context']['fields']) == 4
    assert sum(len(field['widgets']) for field in row['form_context']['fields']) == 5
    repeated = next(field for field in row['form_context']['fields'] if field['name'] == 'registration.firstName')
    assert [widget['page'] for widget in repeated['widgets']] == [1, 2]
    independent = next(field for field in report['inspection']['form_accessibility']['fields'] if field['name'] == 'registration.firstName')
    assert len(independent['widgets']) == 2 and independent['tooltip'] is None
    assert Path(report['decision_source']['path']).read_bytes() == original
    assert report['form_route']['policy'] == 'reviewed-form-1'
    assert not any(item['name'] in {'ocr', 'tagger', 'source-mappings'} for item in report['processors'])
    for profile in OLD_PROFILES:
        old = collect_decisions(source, inventory_profile=profile)
        assert not any(item['kind'] == KIND for item in old['decisions'])
    previous = collect_decisions(source, inventory_profile=TABLE_INVENTORY_PROFILE)
    assert [item for item in decisions['decisions'] if item['kind'] not in {KIND,'empty-tag-removal'}] == previous['decisions']
    assert report['inspection']['form_accessibility']['supported_structure'] is True
    assert report['inspection']['form_accessibility']['status'] == 'fail'
    assert fresh_form_reviews(report, decisions) == [] and source.read_bytes() == original
    assert_preserved(source, report)


def test_reviewed_names_alternatives_tabs_and_tag_permutation_preserve_values_and_replay(tmp_path, fast_validator):
    source = form_source(tmp_path/'source'); original = source.read_bytes(); before = form_snapshot(source)
    prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared); protected = files(Path(prepared['bundle_path']))
    accept(decisions); plan = write_sidecar(decisions, tmp_path/'accepted.json')
    report = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert_preserved(source, report); assert form_snapshot(report['output']['path']) == expected_form(before)
    assert report['inspection']['form_accessibility']['status'] == 'pass'
    assert report['gate2']['status'] == 'pass'
    assert len(fresh_form_reviews(report, decisions)) == 1
    state = tmp_path/'review.json'; workspace.create_workspace(report['bundle_path'], state); view = workspace.get_view(state)
    pending = next(item for item in view['manual_items'] if item['id'].startswith('form-controls-decision-'))
    view = workspace.review_item(state, pending['id'], 'approved', REVIEWER, '2026-10-27', view['revision'], 'Keep this previous form observation.')
    for kind, new in [('title', 'Reviewed project form - metadata follow-up'), ('language', 'en-GB')]:
        row = next(row for row in view['decisions'] if row['kind'] == kind)
        view = workspace.edit_decision(state, row['id'], new, view['revision'])
        view = workspace.approve_decision(state, row['id'], REVIEWER, '2026-10-27', view['revision'])
    assert view['counts']['manual_approved'] == 0
    assert next(item for item in view['manual_items'] if item['id'] == pending['id'])['notes'] == 'Keep this previous form observation.'
    saved = state.read_bytes(); export = workspace.export_workspace(state, tmp_path/'export', view['revision'])
    later = execute(source, tmp_path/'metadata', sidecar=export['sidecar_path'], decision_bundle=report['bundle_path'])
    assert_preserved(source, later); assert form_snapshot(later['output']['path']) == form_snapshot(report['output']['path'])
    assert len(fresh_form_reviews(later, data(later))) == 1
    assert source.read_bytes() == original and state.read_bytes() == saved and files(Path(prepared['bundle_path'])) == protected


@pytest.mark.parametrize('hazard', ['xfa', 'need-appearances', 'calculation', 'field-action', 'widget-action',
    'radio', 'pushbutton', 'signature', 'orphan-widget', 'missing-widget', 'duplicate-widget', 'wrong-parent',
    'duplicate-name', 'wrong-parenttree', 'missing-objr', 'wrong-role', 'checkbox-state', 'missing-appearance', 'hidden', 'unsupported-tabs',
    'choice-value', 'choice-indices', 'choice-options'])
def test_independent_raw_form_assessment_refuses_unsupported_or_broken_sources(tmp_path, hazard):
    source = form_source(tmp_path/'source', repaired=True, hazard=hazard)
    report = inspection.inspect_pdf(source)
    assert not report.get('error'), report.get('error')
    assessment = report['form_accessibility']
    assert assessment['supported_structure'] is False and assessment['status'] != 'pass'
    assert assessment['unsupported_reasons']
    assert checks.assess(report)['status'] == 'fail'


def test_unknown_form_policy_cannot_remove_the_unsupported_form_blocker(tmp_path):
    inspected = inspection.inspect_pdf(form_source(tmp_path/'source', repaired=True))
    inspected['form_accessibility']['policy'] = 'unrecognized-draft'
    assessed = checks.assess(inspected)
    assert assessed['status'] == 'fail'
    assert next(row for row in assessed['checks'] if row['id'] == 'unsupported-features')['evidence']['forms']


@pytest.mark.parametrize('profile', OLD_PROFILES)
def test_older_profiles_do_not_gain_a_form_fix_route(tmp_path, fast_validator, profile):
    source = form_source(tmp_path/'source'); original = source.read_bytes()
    older = collect_decisions(source, inventory_profile=profile)
    plan = write_sidecar(older, tmp_path/'older.json')
    report = execute(source, tmp_path/'refused', sidecar=plan)
    assert report['status'] == 'needs-manual' and report['output'] is None
    assert report['error']['type'] == 'UnsupportedDocument' and report['processors'] == []
    assert source.read_bytes() == original


def test_nonterminal_tooltip_never_substitutes_for_a_terminal_accessible_name(tmp_path, fast_validator):
    source = form_source(tmp_path/'source', source_parent_tooltip='Preserved ancestor tooltip\r\nnot an inherited name')
    inspected = inspection.inspect_pdf(source); assessment = inspected['form_accessibility']
    assert assessment['supported_structure'] is True and assessment['status'] == 'fail'
    first = next(field for field in assessment['fields'] if field['name'] == 'registration.firstName')
    assert first['tooltip'] is None and 'Missing nonempty accessible name/tooltip' in first['issues']
    before = form_snapshot(source); prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared)
    context = next(field for field in choose(decisions)['form_context']['fields'] if field['name'] == 'registration.firstName')
    assert context['tooltip'] is None
    accept(decisions); plan = write_sidecar(decisions, tmp_path/'accepted.json')
    report = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert_preserved(source, report)
    assert form_snapshot(report['output']['path']) == expected_form(before)

