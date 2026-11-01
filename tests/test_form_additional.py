"""Independent form preservation fault injection and compatible-profile checks."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator import engines, inspection, pipeline, sidecar
from pdf_remediator.sidecar import bind_approval, file_sha256, write_sidecar
from test_pipeline import generated_chapter
from test_artifact_structure_pipeline import exact_fidelity, files
from test_form_pipeline import (KIND, REVIEWER, accept, assert_preserved, choose, data,
    execute, form_snapshot, form_source, selected_value, value,
    registered_language_fonts, tagged_control, fast_validator)


def test_supported_form_preparation_never_runs_tagger_or_catalog_normalizer(tmp_path, fast_validator, monkeypatch):
    source = form_source(tmp_path/'source'); before = source.read_bytes()
    def refuse(*args, **kwargs): raise AssertionError('Form preparation must retain the exact checkpoint')
    monkeypatch.setattr(engines, 'tag', refuse)
    monkeypatch.setattr(pipeline, 'normalize_catalog', refuse)
    report = execute(source, tmp_path/'prepared')
    assert_preserved(source, report)
    assert Path(report['decision_source']['path']).read_bytes() == before
    assert Path(report['output']['path']).read_bytes() == before


def test_metadata_only_supported_form_passes_full_graph_seal_without_form_rewrite(tmp_path, fast_validator):
    source = form_source(tmp_path/'source', repaired=True); before = form_snapshot(source)
    prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared)
    title = next(row for row in decisions['decisions'] if row['kind'] == 'title')
    title['value'] = 'Explicitly reviewed form metadata'; bind_approval(title, REVIEWER, '2026-10-27')
    plan = write_sidecar(decisions, tmp_path/'metadata.json')
    report = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert_preserved(source, report)
    assert form_snapshot(report['output']['path']) == before
    assert report['gate2']['status'] == 'pass'


@pytest.mark.parametrize('fault', ['value', 'default', 'appearance', 'field-name', 'mapping-name',
    'checkbox-state', 'field-order', 'annotation-order', 'calculation-order', 'flags'])
def test_metadata_only_postwriter_form_changes_refuse_before_publish(tmp_path, fast_validator, monkeypatch, fault):
    source = form_source(tmp_path/'source', repaired=True); original = source.read_bytes()
    prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared); protected = files(Path(prepared['bundle_path']))
    title = next(row for row in decisions['decisions'] if row['kind'] == 'title')
    title['value'] = 'Reviewed metadata with protected original form'; bind_approval(title, REVIEWER, '2026-10-27')
    plan = write_sidecar(decisions, tmp_path/'metadata.json'); apply_original = sidecar.apply_decisions
    def mutate(*args, **kwargs):
        outcome = apply_original(*args, **kwargs); target = Path(args[1]); changed = target.with_name('tampered-'+fault+'.pdf')
        with pikepdf.open(target) as pdf:
            group, checkbox, notes = pdf.Root.AcroForm.Fields; first, choice = group.Kids
            widget = first.Kids[0]
            if fault == 'value': first.V = 'A deliberately different participant'
            elif fault == 'default': first.DV = 'A different default participant'
            elif fault == 'appearance': widget.AP.N.write(b'/Artifact BMC q 0 0 20 20 re f Q EMC')
            elif fault == 'field-name': first.T = 'changedInternalName'
            elif fault == 'mapping-name': first.TM = 'changedSubmissionIdentity'
            elif fault == 'checkbox-state': checkbox.AS = pikepdf.Name.Off
            elif fault == 'field-order': pdf.Root.AcroForm.Fields = pikepdf.Array(list(reversed(pdf.Root.AcroForm.Fields)))
            elif fault == 'annotation-order': pdf.pages[0].Annots = pikepdf.Array(list(reversed(pdf.pages[0].Annots)))
            elif fault == 'calculation-order': pdf.Root.AcroForm.CO = pikepdf.Array([first])
            elif fault == 'flags': first.Ff = 0
            with changed.open('xb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7', fix_metadata_version=False)
        target.write_bytes(changed.read_bytes())
        outcome['output_sha256'] = file_sha256(target)
        return outcome
    monkeypatch.setattr(sidecar, 'apply_decisions', mutate)
    report = execute(source, tmp_path/'refused', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert report['status'] == 'failed' and report['output'] is None
    assert source.read_bytes() == original and files(Path(prepared['bundle_path'])) == protected
    assert 'form_preservation' not in report or report['form_preservation'].get('status') != 'pass'


@pytest.mark.parametrize('kind', ['annotation-name', 'link-name', 'link-target'])
def test_changed_other_annotation_choices_cannot_bypass_whole_form_plan(tmp_path, fast_validator, kind):
    source = form_source(tmp_path/'source'); prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared)
    accept(decisions)
    candidates = [row for row in decisions['decisions'] if row['kind'] == kind]
    if not candidates:
        # Unsupported annotations are absent from the old editing scope.
        assert kind == 'annotation-name'
        return
    row = candidates[0]
    if row.get('structural_eligible') is False:
        original = copy.deepcopy(row)
        with pytest.raises(sidecar.DecisionError):
            bind_approval(dict(row, value='unapproved alteration'), REVIEWER, '2026-10-27')
        assert row == original
        return
    from test_navigation_pipeline import selected_value as nav_value
    row['value'] = nav_value(kind); bind_approval(row, REVIEWER, '2026-10-27')
    plan = write_sidecar(decisions, tmp_path/'conflict.json'); protected = files(Path(prepared['bundle_path']))
    report = execute(source, tmp_path/'refused', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert report['status'] == 'failed' and report['output'] is None
    assert files(Path(prepared['bundle_path'])) == protected


@pytest.mark.parametrize('kind', ['annotation-name', 'link-name', 'link-target', 'bookmark-entry', 'bookmark-additions'])
def test_new_form_profile_preserves_ordinary_nonform_navigation_scope_and_replay(tmp_path, fast_validator, kind):
    from test_navigation_pipeline import navigation_source, accept as nav_accept, nav_snapshot
    source = navigation_source(tmp_path/'source'); prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared)
    assert not any(row['kind'] == KIND for row in decisions['decisions'])
    nav_accept(decisions, kind); plan = write_sidecar(decisions, tmp_path/'navigation.json')
    report = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert report['status'] in {'candidate', 'needs-manual'}, report.get('error'); exact_fidelity(report)
    assert report['fidelity']['reviewed_navigation']['expected_common_navigation_matches'] is True
    assert len(report['fidelity']['reviewed_navigation']['deltas']) == 1
    snapshot = nav_snapshot(report['output']['path'])
    title = next(row for row in decisions['decisions'] if row['kind'] == 'title')
    title['value'] = 'Later reviewed navigation metadata'; bind_approval(title, REVIEWER, '2026-10-27')
    later_plan = write_sidecar(decisions, tmp_path/'later.json')
    later = execute(source, tmp_path/'later', sidecar=later_plan, decision_bundle=report['bundle_path'])
    assert later['status'] in {'candidate', 'needs-manual'}, later.get('error'); exact_fidelity(later)
    assert nav_snapshot(later['output']['path']) == snapshot


def test_unnamed_nonterminal_group_keeps_terminal_names_and_raw_checkpoint(tmp_path, fast_validator):
    original = form_source(tmp_path/'source'); source = tmp_path/'unnamed-group.pdf'
    with pikepdf.open(original) as pdf:
        group = pdf.Root.AcroForm.Fields[0]; del group['/T']
        group.TU = 'Preserved ancestor description that is not inherited'
        with source.open('xb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7')
    inspected = inspection.inspect_pdf(source)
    assert inspected['form_accessibility']['supported_structure'] is True
    assert {'firstName', 'session'} <= {field['name'] for field in inspected['form_accessibility']['fields']}
    assert next(field for field in inspected['form_accessibility']['fields'] if field['name'] == 'firstName')['tooltip'] is None
    before = source.read_bytes(); report = execute(source, tmp_path/'prepared')
    assert_preserved(source, report)
    assert Path(report['decision_source']['path']).read_bytes() == before and source.read_bytes() == before


def test_optional_widget_page_and_parenttree_next_key_stay_absent_after_reviewed_repair(tmp_path, fast_validator):
    original = form_source(tmp_path/'source'); source = tmp_path/'without-optional-keys.pdf'
    with pikepdf.open(original) as pdf:
        for page in pdf.pages:
            for annotation in page.Annots:
                if annotation.Subtype == pikepdf.Name.Widget: del annotation['/P']
        del pdf.Root.StructTreeRoot['/ParentTreeNextKey']
        with source.open('xb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7')
    inspected = inspection.inspect_pdf(source)
    assert inspected['form_accessibility']['supported_structure'] is True
    prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared); accept(decisions)
    plan = write_sidecar(decisions, tmp_path/'accepted.json')
    report = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert_preserved(source, report)
    with pikepdf.open(report['output']['path']) as pdf:
        assert '/ParentTreeNextKey' not in pdf.Root.StructTreeRoot
        assert all('/P' not in annotation for page in pdf.pages for annotation in page.Annots if annotation.Subtype == pikepdf.Name.Widget)


@pytest.mark.parametrize('tooltip', ['First name\r\nwith a retained line ending', 'First name '+('x'*4001)])
def test_untouched_original_tooltip_bytes_survive_an_unrelated_control_edit(tmp_path, fast_validator, tooltip):
    source = form_source(tmp_path/'source', source_tooltip=tooltip); prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared)
    row = choose(decisions); selected = json.loads(row['current'])
    first = next(field for field in row['form_context']['fields'] if field['name'] == 'registration.firstName')
    selected['fields'][0]['tooltip'] = first['tooltip']
    for page in selected['pages']: page['tabs'] = 'S'
    accept(decisions, value(selected)); plan = write_sidecar(decisions, tmp_path/'accepted.json')
    report = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert_preserved(source, report)
    with pikepdf.open(source) as before, pikepdf.open(report['output']['path']) as after:
        assert bytes(before.Root.AcroForm.Fields[0].Kids[0].TU) == bytes(after.Root.AcroForm.Fields[0].Kids[0].TU)




def test_static_widget_appearances_participate_in_strict_all_page_fidelity(tmp_path):
    source = form_source(tmp_path/'source', repaired=True)
    report = inspection.compare_fidelity(source, source)
    assert report['status'] == 'pass'
    rendering = report['form_rendering']
    assert rendering['policy'] == 'supported-static-widget-rendering-1' and rendering['status'] == 'pass'
    assert rendering['initialized_documents'] == [file_sha256(source), file_sha256(source)]
    assert rendering['javascript_platform'] == 'disabled-null' and rendering['xfa_disabled'] is True
    assert rendering['document_or_page_actions_invoked'] is False
    assert all(page['changed_pixel_fraction'] == 0 for page in report['pages'])


def test_an_appearance_only_change_is_visible_to_the_form_fidelity_renderer(tmp_path):
    source = form_source(tmp_path/'source', repaired=True); changed = tmp_path/'appearance-only.pdf'
    with pikepdf.open(source) as pdf:
        widget = pdf.Root.AcroForm.Fields[0].Kids[0].Kids[0]
        widget.AP.N.write(b'/Artifact BMC q 1 0 0 rg 0 0 240 24 re f Q EMC')
        with changed.open('xb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7', fix_metadata_version=False)
    before = inspection.inspect_pdf(source); after = inspection.inspect_pdf(changed)
    assert before['form_accessibility']['supported_structure'] is True
    assert after['form_accessibility']['supported_structure'] is True
    report = inspection.compare_fidelity(source, changed)
    assert report['status'] == 'fail' and report['form_rendering']['status'] == 'pass'
    assert any(page['changed_pixel_fraction'] > 0 for page in report['pages'])
    assert next(item for item in report['checks'] if item['id'] == 'all-page-render-and-content')['status'] == 'fail'


def test_unsupported_dynamic_form_never_receives_a_widget_pixel_pass(tmp_path):
    source = form_source(tmp_path/'source', repaired=True, hazard='field-action')
    report = inspection.compare_fidelity(source, source)
    assert report['status'] != 'pass' and report['form_rendering']['status'] == 'not-tested'
    assert report['form_rendering']['initialized_documents'] == []
    assert next(item for item in report['checks'] if item['id'] == 'form-widget-rendering')['status'] == 'not-tested'


@pytest.mark.parametrize('break_initialization', [False, True])
def test_form_environment_initialization_precedes_page_access_and_closes_on_error(tmp_path, monkeypatch, break_initialization):
    source = form_source(tmp_path/'source', repaired=True); inspected = inspection.inspect_pdf(source)
    original_document = inspection.pdfium.PdfDocument; events = []; documents = []
    class RecordingDocument:
        def __init__(self, path):
            self.real = original_document(path); self.initialized = False; self.closed = False
            self.index = len(documents); documents.append(self); events.append(('open', self.index))
        @property
        def formenv(self): return self.real.formenv
        def init_forms(self, configuration):
            events.append(('initialize', self.index))
            assert not configuration.m_pJsPlatform and bool(configuration.xfa_disabled)
            if break_initialization and self.index == 1: raise RuntimeError('Synthetic initialization failure')
            self.real.init_forms(configuration); self.initialized = True
        def __len__(self):
            assert self.initialized; events.append(('length', self.index)); return len(self.real)
        def __getitem__(self, index):
            assert self.initialized; events.append(('page', self.index)); return self.real[index]
        def close(self): self.real.close(); self.closed = True; events.append(('close', self.index))
    monkeypatch.setattr(inspection, 'inspect_pdf', lambda *args, **kwargs: copy.deepcopy(inspected))
    monkeypatch.setattr(inspection.pdfium, 'PdfDocument', RecordingDocument)
    report = inspection.compare_fidelity(source, source)
    assert len(documents) == 2 and all(document.closed for document in documents)
    assert events[:4] == [('open', 0), ('initialize', 0), ('open', 1), ('initialize', 1)]
    assert report['status'] == ('error' if break_initialization else 'pass')
    if break_initialization: assert report['error']['type'] == 'RuntimeError'



@pytest.mark.parametrize('fault', ['dangling-label', 'nontext-label', 'inline-replacement', 'nested-link'])
def test_independent_form_label_proof_rejects_unproven_paints_and_interactions(tmp_path, fault):
    from test_form_edits import form_pdf
    original = form_pdf(tmp_path/'original.pdf'); source = tmp_path/'label-fault.pdf'
    with pikepdf.open(original) as pdf:
        page = pdf.pages[0]; owner = pdf.Root.StructTreeRoot.K.K.K[0]
        if fault == 'dangling-label': owner.K[0] = 99
        elif fault in {'nontext-label', 'inline-replacement'}:
            instructions = list(pikepdf.parse_content_stream(page)); current = None; changed = []
            for instruction in instructions:
                operator = str(instruction.operator)
                if operator == 'BDC':
                    current = instruction.operands[1].get('/MCID')
                    if fault == 'inline-replacement' and current == 2:
                        instruction.operands[1].ActualText = 'Unapproved inline replacement'
                if fault == 'nontext-label' and current == 2 and operator == 'Tj':
                    changed.extend([pikepdf.ContentStreamInstruction([0, 0, 20, 20], pikepdf.Operator('re')),
                        pikepdf.ContentStreamInstruction([], pikepdf.Operator('f'))])
                else: changed.append(instruction)
                if operator == 'EMC': current = None
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(changed))
        else:
            annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                P=page.obj, Rect=pikepdf.Array([10, 10, 80, 25]), F=4, StructParent=4,
                Dest=pikepdf.Array([page.obj, pikepdf.Name.Fit]), Contents='Preserved nested interaction'))
            link = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Link,
                P=owner, Pg=page.obj, Alt='Read this page again',
                K=pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=annotation, Pg=page.obj)))
            owner.K.append(link); page.Annots.append(annotation)
            pdf.Root.StructTreeRoot.ParentTree.Nums = pikepdf.Array([*list(pdf.Root.StructTreeRoot.ParentTree.Nums), 4, link]); pdf.Root.StructTreeRoot.ParentTreeNextKey = 5
        with source.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    inspected = inspection.inspect_pdf(source)
    assert not inspected.get('error'), inspected.get('error')
    assessment = inspected['form_accessibility']
    assert assessment['supported_structure'] is False and assessment['unsupported_reasons']
    assert any('Form' in reason for reason in assessment['unsupported_reasons'])


@pytest.mark.parametrize('hazard', ['owner-attributes', 'ancestor-alternative'])
def test_independent_form_assessment_refuses_protected_owner_or_ancestor_name_authority(tmp_path, hazard):
    from test_form_edits import form_pdf
    source = form_pdf(tmp_path/'source.pdf', hazard=hazard)
    report = inspection.inspect_pdf(source)
    assert not report.get('error'), report.get('error')
    assessment = report['form_accessibility']
    assert assessment['supported_structure'] is False and assessment['status'] != 'pass'
    assert any('Form owner' in reason or 'Form ancestry' in reason for reason in assessment['unsupported_reasons'])


INERT_FORM_STREAM_HAZARDS = {'stream-parenttree-owner', 'stream-duplicate-mcid-reference',
    'stream-role-mismatch', 'stream-wrong-formtype', 'stream-wrong-subtype', 'stream-no-font',
    'stream-shared-parentkey', 'stream-unknown-key'}


def empty_container_source(directory, tagged_control, *, tagged=True, style='resources', hazard=None):
    """Unused producer defaults, not a control fixture or a flattening route."""
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    restored = directory/'tagged-reference.pdf'; source = directory/'input.pdf'
    with pikepdf.open(tagged_control) as pdf:
        acro = pikepdf.Dictionary(Fields=pikepdf.Array())
        if style in {'defaults', 'resources', 'figure-layout', 'figure-layout-form-stream'}:
            acro.NeedAppearances = False; acro.SigFlags = 0; acro.Q = 0; acro.CO = pikepdf.Array()
        if style in {'resources', 'figure-layout', 'figure-layout-form-stream'}:
            encoding = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Encoding,
                Differences=pikepdf.Array([24, pikepdf.Name.breve, pikepdf.Name.caron,
                    128, pikepdf.Name.bullet, pikepdf.Name.dagger])))
            acro.DR = pikepdf.Dictionary(Font=pikepdf.Dictionary(
                Helv=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                    BaseFont=pikepdf.Name.Helvetica, Name=pikepdf.Name.Helv, Encoding=encoding),
                ZaDb=pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                    BaseFont=pikepdf.Name.ZapfDingbats, Name=pikepdf.Name.ZaDb)),
                Encoding=pikepdf.Dictionary(PDFDocEncoding=encoding))
            acro.DA = pikepdf.String('/Helv 0 Tf 0 g ')
        pdf.Root.AcroForm = pdf.make_indirect(acro)
        if style.startswith('figure-layout'):
            figures = []
            def find_figures(item):
                if isinstance(item, pikepdf.Array):
                    for child in item: find_figures(child)
                elif isinstance(item, pikepdf.Dictionary) and item.get('/Type') == pikepdf.Name.StructElem:
                    if item.get('/S') == pikepdf.Name.Figure: figures.append(item)
                    if '/K' in item: find_figures(item.K)
            find_figures(pdf.Root.StructTreeRoot.K)
            assert figures, 'The positive must use an actual image Figure fixture'
            figures[0].A = pdf.make_indirect(pikepdf.Dictionary(O=pikepdf.Name.Layout,
                BBox=pdf.make_indirect(pikepdf.Array([90, 460, 510, 670]))))
        if style == 'figure-layout-form-stream':
            page = pdf.pages[0]; tree = pdf.Root.StructTreeRoot; caption = tree.K.K[2]
            mcid = int(caption.K); instructions = list(pikepdf.parse_content_stream(page))
            start = next(index for index, operation in enumerate(instructions)
                if str(operation.operator) == 'BDC' and len(operation.operands) == 2
                and isinstance(operation.operands[1], pikepdf.Dictionary) and operation.operands[1].get('/MCID') == mcid)
            end = start + 1; depth = 1
            while depth:
                operator = str(instructions[end].operator)
                if operator in {'BDC', 'BMC'}: depth += 1
                elif operator == 'EMC': depth -= 1
                end += 1
            source_stream = pdf.make_stream(pikepdf.unparse_content_stream(instructions[start:end]))
            source_stream.Type = pikepdf.Name.XObject; source_stream.Subtype = pikepdf.Name.Form
            source_stream.FormType = 1; source_stream.BBox = pikepdf.Array(list(page.MediaBox))
            source_stream.Resources = page.obj.Resources; source_stream.StructParents = 1
            slots = pikepdf.Array([None] * (mcid + 1)); slots[mcid] = caption
            tree.ParentTree.Nums[1][mcid] = None; tree.ParentTree.Nums.extend([1, slots]); tree.ParentTreeNextKey = 2
            caption.K = pikepdf.Dictionary(Type=pikepdf.Name.MCR, MCID=mcid, Stm=source_stream)
            xobjects = page.Resources.get('/XObject', pikepdf.Dictionary())
            # Copy the resource carrier so the Form cannot reference itself.
            resources = pikepdf.Dictionary({str(key): item for key, item in page.Resources.items()})
            resources.XObject = pikepdf.Dictionary({str(key): item for key, item in xobjects.items()})
            resources.XObject.RetainedTextForm = source_stream; page.Resources = resources
            replacement = [pikepdf.ContentStreamInstruction([], pikepdf.Operator('q')),
                pikepdf.ContentStreamInstruction([pikepdf.Name.RetainedTextForm], pikepdf.Operator('Do')),
                pikepdf.ContentStreamInstruction([], pikepdf.Operator('Q'))]
            page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(instructions[:start] + replacement + instructions[end:]))
        if hazard in INERT_FORM_STREAM_HAZARDS:
            assert style == 'figure-layout-form-stream'
            if hazard == 'stream-parenttree-owner': slots[mcid] = tree.K.K[0]
            elif hazard == 'stream-duplicate-mcid-reference': caption.K = pikepdf.Array([caption.K, caption.K])
            elif hazard == 'stream-role-mismatch': caption.S = pikepdf.Name.P
            elif hazard == 'stream-wrong-formtype': source_stream.FormType = 2
            elif hazard == 'stream-wrong-subtype': source_stream.Subtype = pikepdf.Name.Image
            elif hazard == 'stream-no-font': source_stream.Resources = pikepdf.Dictionary()
            elif hazard == 'stream-shared-parentkey': page.StructParents = 1
            elif hazard == 'stream-unknown-key': source_stream.Unknown = True
            else: raise ValueError('Unknown authored Form stream hazard')
        elif hazard in {'resource-stream-action', 'appearance-stream-actions', 'xobject-stream-javascript'}:
            retained = pdf.make_stream(b'Unchanged unused stream payload.\n')
            retained.Type = pikepdf.Name.XObject; retained.Subtype = pikepdf.Name.Form
            retained.FormType = 1; retained.BBox = pikepdf.Array([0, 0, 10, 10]); retained.Resources = pikepdf.Dictionary()
            if hazard == 'resource-stream-action':
                retained.A = pikepdf.Dictionary(S=pikepdf.Name.URI, URI='https://example.invalid/')
                pdf.Root.RetainedProducerData = pikepdf.Dictionary(Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Unused=retained)))
            elif hazard == 'appearance-stream-actions':
                retained.AA = pikepdf.Dictionary(E=pikepdf.Dictionary(S=pikepdf.Name.Named, N=pikepdf.Name.Print))
                pdf.Root.RetainedProducerData = pikepdf.Dictionary(AP=pikepdf.Dictionary(N=retained))
            else:
                retained.S = pikepdf.Name.JavaScript
                pdf.Root.RetainedProducerData = pikepdf.Dictionary(XObject=retained)
        elif hazard and hazard.startswith('figure-'):
            tree = pdf.Root.StructTreeRoot; document = tree.K; figure = document.K[1]
            figure.S = pikepdf.Name.Figure
            attribute = pdf.make_indirect(pikepdf.Dictionary(O=pikepdf.Name.Layout,
                BBox=pdf.make_indirect(pikepdf.Array([48, 500, 540, 520]))))
            figure.A = attribute
            if hazard in {'figure-orphan-lookalike', 'figure-direct-lookalike'}:
                del figure['/A']; figure.S = pikepdf.Name.P
                lookalike = pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Figure,
                    P=document, A=attribute, K=1)
                pdf.Root.RetainedProducerData = lookalike if hazard == 'figure-direct-lookalike' else pdf.make_indirect(lookalike)
            elif hazard == 'figure-action-lookalike': figure.A = pikepdf.Dictionary(S=pikepdf.Name.URI, URI='https://example.invalid/')
            elif hazard == 'figure-unknown-attribute': attribute.Unknown = True
            elif hazard == 'figure-printfield-owner': attribute.O = pikepdf.Name.PrintField
            elif hazard == 'figure-attribute-alias': pdf.Root.RetainedProducerData = attribute
            elif hazard == 'figure-bbox-alias': pdf.Root.RetainedProducerData = attribute.BBox
            elif hazard == 'figure-rolemap-override': tree.RoleMap = pikepdf.Dictionary(Figure=pikepdf.Name.P)
            elif hazard == 'figure-parent-mismatch': figure.P = tree
            elif hazard == 'figure-duplicate-owner': document.K.append(figure)
            elif hazard == 'figure-unknown-child': document.K.append(pikepdf.String('not a structure child'))
            elif hazard == 'figure-invalid-bbox': attribute.BBox = pikepdf.Array([48, False, 540, 520])
            else: raise ValueError('Unknown authored Figure attribute hazard')
        elif hazard == 'xfa': acro.XFA = pikepdf.String('not a supported static form')
        elif hazard == 'unknown-key': acro.UnknownProducerSemantics = True
        elif hazard == 'nonempty-calculation': acro.CO = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(T='unrooted'))])
        elif hazard == 'regenerate-appearances': acro.NeedAppearances = True
        elif hazard == 'malformed-fields': acro.Fields = pikepdf.String('not an array')
        elif hazard == 'unknown-resource': acro.DR.XObject = pikepdf.Dictionary()
        elif hazard == 'stream-font': acro.DR.Font.Helv = pdf.make_stream(b'not a passive font dictionary')
        elif hazard == 'duplicate-encoding': acro.DR.Encoding.PDFDocEncoding.Differences = pikepdf.Array([24, pikepdf.Name.breve, 24, pikepdf.Name.caron])
        elif hazard == 'unsupported-appearance-program': acro.DA = pikepdf.String('/Helv 0 Tf 0 0 m 1 1 l S')
        elif hazard == 'aliased-acroform': pdf.Root.EmptyFormAlias = acro
        elif hazard == 'aliased-fields':
            acro.Fields = pdf.make_indirect(pikepdf.Array()); pdf.Root.EmptyFieldsAlias = acro.Fields
        elif hazard == 'aliased-calculation':
            acro.CO = pdf.make_indirect(pikepdf.Array()); pdf.Root.EmptyCalculationAlias = acro.CO
        elif hazard in {'detached-widget', 'direct-widget', 'detached-field', 'direct-field', 'no-acro-widget', 'no-acro-direct-field'}:
            target = pikepdf.Dictionary(Subtype=pikepdf.Name.Widget, Rect=pikepdf.Array([1, 2, 30, 20])) if 'widget' in hazard else pikepdf.Dictionary(FT=pikepdf.Name.Tx, T='unrootedField')
            direct = hazard in {'direct-widget', 'direct-field', 'no-acro-direct-field'}
            pdf.Root.RetainedProducerData = pikepdf.Dictionary(Child=target if direct else pdf.make_indirect(target))
            if hazard.startswith('no-acro-'): del pdf.Root['/AcroForm']
        elif hazard == 'nested-action':
            pdf.Root.RetainedProducerData = pikepdf.Dictionary(Child=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS='unused is not safe'))
        elif hazard == 'signature-permissions': pdf.Root.Perms = pikepdf.Dictionary()
        elif hazard == 'nested-signature': pdf.Root.RetainedProducerData = pikepdf.Dictionary(Child=pikepdf.Dictionary(Type=pikepdf.Name.Sig))
        elif hazard == 'nested-attribute':
            pdf.Root.RetainedProducerData = pikepdf.Dictionary(Child=pikepdf.Dictionary(A=pikepdf.Dictionary(O=pikepdf.Name.PrintField)))
        elif hazard is not None: raise ValueError('Unknown empty-container hazard')
        with restored.open('xb') as stream: pdf.save(stream, deterministic_id=True)
        if not tagged:
            for key in ('/StructTreeRoot', '/MarkInfo'):
                if key in pdf.Root: del pdf.Root[key]
        with source.open('xb') as stream: pdf.save(stream, deterministic_id=True)
    return source, restored


def empty_container_snapshot(path):
    from test_artifact_structure_pipeline import canonical
    with pikepdf.open(path) as pdf: return canonical(pdf.Root.get('/AcroForm'))


def exact_empty_container_fidelity(report, page_count):
    fidelity = report['fidelity']
    assert fidelity['status'] == 'pass' and len(fidelity['pages']) == page_count
    assert [page['page'] for page in fidelity['pages']] == list(range(1, page_count + 1))
    assert fidelity['thresholds'] == {'pixel_delta': 0, 'max_changed_fraction': 0.0}
    assert fidelity['renderer']['all_pages'] is True
    assert fidelity['text']['ordered_status'] == fidelity['text']['multiset_status'] == 'pass'
    assert fidelity['text']['removed_tokens'] == fidelity['text']['added_tokens'] == 0
    for page in fidelity['pages']:
        assert page['changed_pixel_fraction'] == 0
        assert page['text']['removed_tokens'] == page['text']['added_tokens'] == 0
        assert page['text']['ordered_status'] == 'pass'
        assert page['page_boxes_status'] == page['annotations_status'] == 'pass'


def empty_container_geometry(path):
    from test_artifact_structure_pipeline import canonical
    with pikepdf.open(path) as pdf:
        values = []
        def walk(item, path):
            if isinstance(item, pikepdf.Array):
                for index, child in enumerate(item): walk(child, path+'/'+str(index))
            elif isinstance(item, pikepdf.Dictionary) and item.get('/Type') == pikepdf.Name.StructElem:
                if '/A' in item: values.append({'path': path, 'role': str(item.S), 'attribute': canonical(item.A)})
                if '/K' in item: walk(item.K, path+'/K')
        if '/StructTreeRoot' in pdf.Root: walk(pdf.Root.StructTreeRoot.K, 'K')
        return values


def empty_container_page_instructions(path):
    with pikepdf.open(path) as pdf:
        def content(item):
            if isinstance(item, pikepdf.Stream): return [item.read_bytes()]
            if isinstance(item, pikepdf.Array): return [data for child in item for data in content(child)]
            return []
        return [content(page.obj.get('/Contents')) for page in pdf.pages]


def empty_container_form_streams(path):
    from test_artifact_structure_pipeline import canonical
    with pikepdf.open(path) as pdf:
        values = [canonical(item) for item in pdf.objects
            if isinstance(item, pikepdf.Stream) and item.get('/Subtype') == pikepdf.Name.Form]
        return sorted(values, key=lambda item: json.dumps(item, sort_keys=True))


@pytest.mark.parametrize('tagged', [True, False], ids=['already-tagged', 'requires-tagging'])
@pytest.mark.parametrize('style', ['minimal', 'defaults', 'resources', 'figure-layout', 'figure-layout-form-stream'])
def test_proved_empty_containers_keep_ordinary_preparation_metadata_and_review_replay(tmp_path, tagged_control, generated_chapter, fast_validator, monkeypatch, tagged, style):
    import shutil
    source, reference = empty_container_source(tmp_path/'source', generated_chapter if style.startswith('figure-layout') else tagged_control, tagged=tagged, style=style)
    original = source.read_bytes(); raw_form = empty_container_snapshot(source)
    expected_geometry = empty_container_geometry(reference); instructions = empty_container_page_instructions(source)
    expected_streams = empty_container_form_streams(source)
    if style == 'figure-layout-form-stream':
        fixture_fidelity = inspection.compare_fidelity(generated_chapter, reference)
        exact_empty_container_fidelity({'fidelity': fixture_fidelity}, len(instructions))
    assert bool(expected_geometry) is style.startswith('figure-layout')
    normalizer = pipeline.normalize_catalog; calls = {'tag': 0, 'catalog': 0}
    def tag(source_path, destination, *args, **kwargs):
        calls['tag'] += 1
        assert not tagged, 'Existing linked content must not be retagged'
        # Explicit local engine double restores the known source structure; it
        # does not change painting or the retained empty producer dictionary.
        shutil.copyfile(reference, destination)
        return {'status': 'completed', 'engine': 'synthetic-local-regression-double', 'no_ai': True, 'document_network_calls': 0}
    def normalize(source_path, destination, *args, **kwargs):
        calls['catalog'] += 1
        result = normalizer(source_path, destination, *args, **kwargs)
        assert empty_container_snapshot(destination) == raw_form
        return result
    monkeypatch.setattr(engines, 'tag', tag); monkeypatch.setattr(pipeline, 'normalize_catalog', normalize)
    observed = inspection.inspect_pdf(source)
    assert not observed.get('error') and observed['features']['forms'] is False
    assert 'form_accessibility' not in observed
    assert observed['empty_form_container'] == {'policy': 'passive-empty-acroform-2', 'status': 'inert',
        'scope': 'No controls, form actions or unproved authority; plain page links and bookmarks are left as they are, '
                 'and the original empty dictionary is retained.'}
    prepared = execute(source, tmp_path/'prepared'); decisions = data(prepared)
    assert prepared['status'] in {'candidate', 'needs-manual'}, prepared.get('error')
    exact_empty_container_fidelity(prepared, observed['page_count'])
    assert empty_container_geometry(prepared['output']['path']) == expected_geometry
    assert empty_container_page_instructions(prepared['output']['path']) == instructions
    assert empty_container_form_streams(prepared['output']['path']) == expected_streams
    assert calls == {'tag': int(not tagged), 'catalog': 1}
    assert 'form_route' not in prepared and 'form_preservation' not in prepared
    assert not any(row['kind'] == KIND for row in decisions['decisions'])
    assert not any(row['name'] == 'retained-form-checkpoint' for row in prepared['processors'])
    assert empty_container_snapshot(prepared['decision_source']['path']) == raw_form
    protected = files(Path(prepared['bundle_path']))
    title = next(row for row in decisions['decisions'] if row['kind'] == 'title')
    title['value'] = 'Reviewed ordinary document with unused producer defaults'
    bind_approval(title, REVIEWER, '2026-10-27'); plan = write_sidecar(decisions, tmp_path/'accepted-title.json')
    edited = execute(source, tmp_path/'edited', sidecar=plan, decision_bundle=prepared['bundle_path'])
    assert edited['status'] in {'candidate', 'needs-manual'}, edited.get('error')
    exact_empty_container_fidelity(edited, observed['page_count'])
    assert empty_container_geometry(edited['output']['path']) == expected_geometry
    assert empty_container_page_instructions(edited['output']['path']) == instructions
    assert empty_container_form_streams(edited['output']['path']) == expected_streams
    assert edited['inspection']['metadata']['title'] == title['value']
    assert empty_container_snapshot(edited['output']['path']) == raw_form
    assert calls == {'tag': int(not tagged), 'catalog': 1}
    assert source.read_bytes() == original and files(Path(prepared['bundle_path'])) == protected
    assert edited['data_sent']['document_api_calls'] == 0 and edited['settings']['ocr_mode'] == 'off'
    class NoFormEnvironment:
        formenv = None
        def init_forms(self, *args): raise AssertionError('An inert empty container has no widgets to initialize')
    receipt = inspection.initialize_form_rendering(NoFormEnvironment(), source)
    assert receipt['status'] == 'not-applicable' and receipt['field_count'] == receipt['widget_count'] == 0


@pytest.mark.parametrize('hazard', ['xfa', 'unknown-key', 'nonempty-calculation', 'regenerate-appearances',
    'malformed-fields', 'unknown-resource', 'stream-font', 'duplicate-encoding', 'unsupported-appearance-program',
    'aliased-acroform', 'aliased-fields', 'aliased-calculation', 'detached-widget', 'direct-widget',
    'detached-field', 'direct-field', 'no-acro-widget', 'no-acro-direct-field', 'nested-action', 'nested-attribute', 'signature-permissions', 'nested-signature',
    'figure-orphan-lookalike', 'figure-direct-lookalike', 'figure-action-lookalike', 'figure-unknown-attribute',
    'figure-printfield-owner', 'figure-attribute-alias', 'figure-bbox-alias', 'figure-rolemap-override',
    'figure-parent-mismatch', 'figure-duplicate-owner', 'figure-unknown-child', 'figure-invalid-bbox',
    'stream-parenttree-owner', 'stream-duplicate-mcid-reference', 'stream-role-mismatch', 'stream-wrong-formtype',
    'stream-wrong-subtype', 'stream-no-font', 'stream-shared-parentkey', 'stream-unknown-key',
    'resource-stream-action', 'appearance-stream-actions', 'xobject-stream-javascript'])
def test_unproved_empty_containers_and_detached_controls_keep_the_read_only_form_guard(tmp_path, tagged_control, generated_chapter, fast_validator, monkeypatch, hazard):
    source, _ = empty_container_source(tmp_path/'source', generated_chapter if hazard in INERT_FORM_STREAM_HAZARDS else tagged_control,
        style='figure-layout-form-stream' if hazard in INERT_FORM_STREAM_HAZARDS else 'resources', hazard=hazard)
    original = source.read_bytes()
    def refuse(*args, **kwargs): raise AssertionError('Unproved form data must refuse before any preparation writer')
    monkeypatch.setattr(engines, 'tag', refuse); monkeypatch.setattr(pipeline, 'normalize_catalog', refuse)
    observed = inspection.inspect_pdf(source)
    assert not observed.get('error') and observed['features']['forms'] is True
    assert observed['form_accessibility']['supported_structure'] is False
    assert 'empty_form_container' not in observed
    refused = execute(source, tmp_path/'refused')
    assert refused['status'] == 'needs-manual', refused.get('error')
    assert refused['error']['type'] == 'UnsupportedDocument' and refused['output'] is None
    assert refused['processors'] == [] and source.read_bytes() == original
    class NoFormEnvironment:
        formenv = None
        def init_forms(self, *args): raise AssertionError('Unsupported forms must refuse before renderer initialization')
    with pytest.raises(ValueError, match='Unsupported form widgets'):
        inspection.initialize_form_rendering(NoFormEnvironment(), source)


def test_a_form_page_without_any_annotations_does_not_make_the_form_unsupported(tmp_path):
    """A page with no /Annots has no annotation carrier to judge: it is simply empty, not 'not an ordinary array'."""
    original = form_source(tmp_path/'source'); source = tmp_path/'form-with-a-plain-second-page.pdf'
    with pikepdf.open(original) as pdf:
        pdf.add_blank_page(page_size=(400, 500))
        assert '/Annots' not in pdf.pages[-1].obj
        with source.open('xb') as stream: pdf.save(stream, deterministic_id=True, min_version='1.7')
    assessment = inspection.inspect_pdf(source)['form_accessibility']
    assert 'Page annotation carrier is not an ordinary array' not in assessment['unsupported_reasons']
    assert assessment['supported_structure'] is True, assessment['unsupported_reasons']

