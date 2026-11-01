"""Bounded, ground-truth-only running-furniture artifacting experiment.

This is deliberately not a repetition/geometry detector or a general PDF repair.
Only flat page MCIDs in the original fixture topology are supported. Shared
Form XObjects are detected and refused before any mutation or output write.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import pikepdf
import pypdfium2 as pdfium

from build_corpus import (FIXED_DATE, FONT, FONT_BOLD, INK, new_canvas,
                          register_fonts)
from inspect_pdf import compare_fidelity, inspect_pdf
from validate import validate_pdf

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
REPEATED_PHRASE = "Careful reading needs context."


class Refusal(ValueError):
    """The selected operation cannot be performed within the proven scope."""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _identity(obj):
    return tuple(obj.objgen)


def _region_records(page):
    """Only direct, nonnested MCID regions; never operate by text replacement."""
    instructions = list(pikepdf.parse_content_stream(page))
    records = {}
    active = None
    for index, instruction in enumerate(instructions):
        op = str(instruction.operator)
        if op in ("BDC", "BMC"):
            if active is not None:
                raise Refusal("Nested marked-content sequences are outside the spike scope")
            operands = instruction.operands
            if op != "BDC" or len(operands) != 2 or not isinstance(operands[1], pikepdf.Dictionary):
                raise Refusal("Only explicit dictionary BDC regions are supported")
            if "/MCID" not in operands[1]:
                raise Refusal("Unidentified marked-content region")
            mcid = int(operands[1].MCID)
            if mcid < 0 or mcid in records:
                raise Refusal("Duplicate or negative MCID")
            active = (mcid, index, str(operands[0]))
        elif op == "EMC":
            if active is None:
                raise Refusal("Unbalanced EMC")
            mcid, start, role = active
            records[mcid] = {"start": start, "end": index, "role": role,
                             "region_sha256": hashlib.sha256(pikepdf.unparse_content_stream(instructions[start:index+1])).hexdigest()}
            active = None
    if active is not None:
        raise Refusal("Unclosed marked-content sequence")
    return instructions, records


def _shared_forms(pdf):
    uses = Counter()
    for page in pdf.pages:
        resources = page.Resources.get("/XObject", {})
        for instruction in pikepdf.parse_content_stream(page):
            if str(instruction.operator) == "Do" and instruction.operands:
                form = resources.get(str(instruction.operands[0]))
                if isinstance(form, pikepdf.Stream) and form.get("/Subtype") == pikepdf.Name.Form:
                    uses[_identity(form)] += 1
    return [{"object": list(key), "invocations": count, "shared": count > 1}
            for key, count in sorted(uses.items())]


def fixture(path: Path, shared_form=False) -> dict:
    """Build a fully linked page-scoped fixture and its explicit author decisions."""
    title = "Shared form refusal control" if shared_form else "Ground-truth pagination artifact control"
    c = new_canvas(path, title)
    page_specs = []
    pages = 2 if shared_form else 3
    if shared_form:
        c.beginForm("shared-phrase", 0, -4, 360, 20)
        c.setFillColor(INK); c.setFont(FONT, 11)
        c.drawString(0, 0, REPEATED_PHRASE)
        c.endForm()
    for number in range(1, pages+1):
        specs = [
            {"role": "P", "text": REPEATED_PHRASE, "y": 754, "kind": "Header", "size": 11},
            {"role": "H1", "text": f"Chapter {number}. A careful observation", "y": 706, "size": 19},
            {"role": "P", "text": REPEATED_PHRASE, "y": 645, "size": 11},
            {"role": "P", "text": f"BODY-PAGE-{number}. This repeated sentence is meaningful body content.", "y": 600, "size": 11},
            {"role": "P", "text": f"Page {number}", "y": 30, "kind": "Footer", "size": 9},
        ]
        for mcid, spec in enumerate(specs):
            c._code.append(f"/{spec['role']} <</MCID {mcid}>> BDC")
            if shared_form and mcid in (0, 2):
                c.saveState(); c.translate(48, spec["y"]); c.doForm("shared-phrase"); c.restoreState()
            else:
                c.setFillColor(INK)
                c.setFont(FONT_BOLD if spec["role"] == "H1" else FONT, spec["size"])
                c.drawString(48, spec["y"], spec["text"])
            c._code.append("EMC")
        c.bookmarkPage(f"chapter-{number}")
        c.addOutlineEntry(f"Chapter {number}", f"chapter-{number}", level=0)
        c.showPage(); page_specs.append(specs)
    c.save()
    tagged = path.with_suffix(".linked.pdf")
    with pikepdf.open(path) as pdf:
        structure = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Document, P=structure))
        sections, number_entries = [], []
        for page_index, (page, specs) in enumerate(zip(pdf.pages, page_specs)):
            section = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Sect, P=document, Pg=page.obj))
            # Separate header/footer wrappers exercise removal of empty containers.
            header = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Div, P=section))
            body = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Div, P=section))
            footer = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Div, P=section))
            elements = []
            for mcid, spec in enumerate(specs):
                parent = header if mcid == 0 else footer if mcid == 4 else body
                element = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name('/'+spec['role']), P=parent, Pg=page.obj, K=mcid))
                elements.append(element)
            header.K = pikepdf.Array([elements[0]])
            body.K = pikepdf.Array(elements[1:4])
            footer.K = pikepdf.Array([elements[4]])
            section.K = pikepdf.Array([header, body, footer])
            sections.append(section)
            page.StructParents = page_index
            page.Tabs = pikepdf.Name.S
            number_entries.extend((page_index, pikepdf.Array(elements)))
        document.K = pikepdf.Array(sections)
        structure.K = document
        structure.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array(number_entries)))
        structure.ParentTreeNextKey = len(pdf.pages)
        pdf.Root.StructTreeRoot = structure
        pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
        pdf.Root.Lang = pikepdf.String("en-US")
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([0,pikepdf.Dictionary(S=pikepdf.Name.D,St=1)]))
        with pdf.open_metadata(set_pikepdf_as_editor=False) as metadata:
            metadata['dc:title'] = title
            metadata['dc:creator'] = ["PDF Remediator original synthetic experiment"]
            metadata['pdfuaid:part'] = '1'
            for key in ('xmp:CreateDate','xmp:ModifyDate','xmp:MetadataDate'):
                metadata[key] = FIXED_DATE
        pdf.save(tagged, deterministic_id=True)
    tagged.replace(path)
    decisions = {"schema_version": "phase0-artifact-decisions-1", "input_sha256": sha(path),
                 "decision_source": "Original fixture author ground truth; no repetition or geometry inference",
                 "targets": [], "protected_meaningful_mcid": 2,
                 "protected_phrase": REPEATED_PHRASE}
    with pikepdf.open(path) as pdf:
        for index, page in enumerate(pdf.pages):
            _, records = _region_records(page)
            for mcid in (0, 4):
                decisions['targets'].append({"page": index+1, "mcid": mcid,
                                             "kind": page_specs[index][mcid]['kind'],
                                             "expected_region_sha256": records[mcid]['region_sha256']})
    return decisions


def _leaves(node, parent=None, seen=None):
    seen = set() if seen is None else seen
    ident = _identity(node)
    if ident in seen:
        raise Refusal("Cyclic or repeated structure element")
    seen.add(ident)
    if node.get('/Type') != pikepdf.Name.StructElem:
        raise Refusal("Unexpected structure element type")
    if parent is not None and _identity(node.P) != _identity(parent):
        raise Refusal("Broken structure-parent pointer")
    children = node.get('/K')
    if isinstance(children, int):
        if '/Pg' not in node:
            raise Refusal("Leaf page reference must be explicit")
        return [node]
    if not isinstance(children, pikepdf.Array):
        raise Refusal("Only integer leaves and array containers are supported")
    result = []
    for child in children:
        if not isinstance(child, pikepdf.Dictionary):
            raise Refusal("MCR/OBJR or heterogeneous structure children are unsupported")
        result.extend(_leaves(child, node, seen))
    return result


def artifact_selected(source: Path, destination: Path, decisions: dict) -> dict:
    """Preflight everything, then modify only known page regions and tree links."""
    started = time.monotonic()
    if source.resolve() == destination.resolve() or destination.exists():
        raise Refusal("Output must be a new file distinct from input")
    if sha(source) != decisions.get('input_sha256'):
        raise Refusal("Decision hash does not match input")
    with pikepdf.open(source) as pdf:
        if pdf.is_encrypted or len(pdf.pages) > 10:
            raise Refusal("Encrypted or large input is outside this bounded spike")
        if any(key in pdf.Root for key in ('/AcroForm','/Perms')):
            raise Refusal("Forms or signature-related catalog entries are unsupported")
        forms = _shared_forms(pdf)
        if forms:
            if any(form['shared'] for form in forms):
                raise Refusal("Shared Form XObject reused across occurrences: invocation-sensitive repair not implemented")
            raise Refusal("Form XObject semantics are outside this spike's proven scope")
        structure = pdf.Root.get('/StructTreeRoot')
        if not isinstance(structure, pikepdf.Dictionary) or '/ParentTree' not in structure:
            raise Refusal("Missing structure or ParentTree")
        if '/Kids' in structure.ParentTree or '/Nums' not in structure.ParentTree:
            raise Refusal("Only a flat explicit ParentTree is supported")
        if any(key in structure for key in ('/IDTree','/RoleMap','/Namespaces')):
            raise Refusal("ID trees, custom roles and namespaces require a separate implementation")
        document = structure.K
        leaves = _leaves(document)
        nums = structure.ParentTree.Nums
        if len(nums) % 2:
            raise Refusal("Malformed ParentTree")
        parent_map = {int(nums[i]): nums[i+1] for i in range(0,len(nums),2)}
        if len(parent_map)*2 != len(nums):
            raise Refusal("Duplicate ParentTree key")
        page_by_id = {_identity(page.obj): index+1 for index,page in enumerate(pdf.pages)}
        leaf_map = {}
        for leaf in leaves:
            page_number = page_by_id.get(_identity(leaf.Pg))
            key = (page_number,int(leaf.K))
            if page_number is None or key in leaf_map:
                raise Refusal("Invalid page or duplicate leaf content reference")
            leaf_map[key] = leaf
        parsed = {}; planned = []; seen = set()
        for target in decisions.get('targets',[]):
            number, mcid, kind = target['page'],target['mcid'],target['kind']
            key = (number,mcid)
            if key in seen or kind not in ('Header','Footer') or number < 1 or number > len(pdf.pages):
                raise Refusal("Invalid or duplicate target decision")
            seen.add(key)
            page = pdf.pages[number-1]
            if number not in parsed:
                parsed[number] = _region_records(page)
            instructions, records = parsed[number]
            record = records.get(mcid)
            leaf = leaf_map.get(key)
            if record is None or leaf is None or record['region_sha256'] != target['expected_region_sha256']:
                raise Refusal("Selected MCID region or matching structure leaf is absent/stale")
            parent_key = int(page.StructParents)
            mapping = parent_map.get(parent_key)
            if not isinstance(mapping,pikepdf.Array) or mcid >= len(mapping) or mapping[mcid] is None or _identity(mapping[mcid]) != _identity(leaf):
                raise Refusal("ParentTree entry does not identify the selected leaf")
            if record['role'] != str(leaf.S):
                raise Refusal("Content role and structure leaf disagree")
            planned.append((number,mcid,kind,record['start'],leaf,parent_key))
        if not planned:
            raise Refusal("No author-selected targets")
        removed_ids = {_identity(item[4]) for item in planned}
        for number,mcid,kind,start,leaf,parent_key in planned:
            instructions = parsed[number][0]
            instructions[start] = pikepdf.ContentStreamInstruction(
                [pikepdf.Name.Artifact, pikepdf.Dictionary(Type=pikepdf.Name.Pagination,Subtype=pikepdf.Name('/'+kind))],
                pikepdf.Operator('BDC'))
            parent_map[parent_key][mcid] = None
        pruned = []
        def prune(node):
            if _identity(node) in removed_ids:
                return None
            if isinstance(node.K,pikepdf.Array):
                kept = []
                for child in node.K:
                    result = prune(child)
                    if result is not None:
                        kept.append(result)
                if not kept:
                    pruned.append({'role':str(node.S),'object':list(node.objgen)})
                    return None
                node.K = pikepdf.Array(kept)
            return node
        if prune(document) is None:
            raise Refusal("Operation would remove the entire semantic tree")
        for number,(instructions,_) in parsed.items():
            pdf.pages[number-1].Contents = pdf.make_stream(pikepdf.unparse_content_stream(instructions))
        pdf.save(destination, deterministic_id=True)
    return {'status':'completed','input_sha256':sha(source),'output_sha256':sha(destination),
            'selected_regions':len(planned),'removed_leaf_references':len(removed_ids),
            'pruned_empty_containers':pruned,'parent_tree_policy':'Keep MCID indexes stable; set removed references to null',
            'seconds':round(time.monotonic()-started,6)}


def inspect_semantics(path):
    with pikepdf.open(path) as pdf:
        leaves = _leaves(pdf.Root.StructTreeRoot.K)
        pages = []
        for index,page in enumerate(pdf.pages):
            instructions = list(pikepdf.parse_content_stream(page))
            artifacts,mcids = [],[]
            for ins in instructions:
                if str(ins.operator)=='BDC':
                    role,properties=ins.operands
                    if role==pikepdf.Name.Artifact:
                        artifacts.append({'type':str(properties.get('/Type')),'subtype':str(properties.get('/Subtype'))})
                    elif '/MCID' in properties:
                        mcids.append(int(properties.MCID))
            pages.append({'page':index+1,'mcids':mcids,'artifacts':artifacts,
                          'leaf_mcids':[int(leaf.K) for leaf in leaves if _identity(leaf.Pg)==_identity(page.obj)]})
        return {'pages':pages,'leaf_count':len(leaves),'forms':_shared_forms(pdf)}


def render_examples(source, output, directory):
    """Representative visual QA supplements the all-page numeric comparison."""
    for path,label in ((source,'before'),(output,'after')):
        doc=pdfium.PdfDocument(str(path))
        try:
            page=doc[0]
            try:
                bitmap=page.render(scale=1.25)
                try:
                    image=bitmap.to_pil();image.save(directory/f'{label}-page1.png');image.close()
                finally:bitmap.close()
            finally:page.close()
        finally:doc.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=HERE/'spikes/artifacts')
    parser.add_argument('--java-home',type=Path,default=Path(r'C:\Program Files\Eclipse Adoptium\jdk-25.0.3.9-hotspot'))
    args=parser.parse_args();out=args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Refusing to overwrite prior spike evidence')
    out.mkdir(parents=True,exist_ok=True);register_fonts(out)
    source=out/'pagination-before.pdf';output=out/'pagination-after.pdf'
    decisions=fixture(source);write(out/'decisions.json',decisions)
    before_hash=sha(source)
    operation=artifact_selected(source,output,decisions)
    before=validate_pdf(source,out/'validation-before',PROJECT/'tools/verapdf/verapdf.bat',args.java_home)
    after=validate_pdf(output,out/'validation-after',PROJECT/'tools/verapdf/verapdf.bat',args.java_home)
    fidelity=compare_fidelity(source,output,dpi=96,max_changed_fraction=0,pixel_delta=0)
    write(out/'all-page-fidelity.json',fidelity)
    semantic_before=inspect_semantics(source);semantic_after=inspect_semantics(output)
    semantics_pass=all(page['mcids']==[1,2,3] and page['leaf_mcids']==[1,2,3]
                       and len(page['artifacts'])==2 for page in semantic_after['pages'])
    write(out/'semantics-before.json',semantic_before);write(out/'semantics-after.json',semantic_after)
    render_examples(source,output,out)
    shared=out/'shared-form-before.pdf';shared_decisions=fixture(shared,shared_form=True)
    write(out/'shared-form-decisions.json',shared_decisions)
    shared_before_hash=sha(shared)
    shared_baseline=validate_pdf(shared,out/'validation-shared-before',PROJECT/'tools/verapdf/verapdf.bat',args.java_home)
    shared_output=out/'shared-form-after.pdf'
    try:
        shared_result=artifact_selected(shared,shared_output,shared_decisions)
    except Refusal as exc:
        shared_result={'status':'refused','reason':str(exc)}
    shared_result.update({'input_unchanged':sha(shared)==shared_before_hash,
                          'output_exists':shared_output.exists(),
                          'forms':inspect_semantics(shared)['forms']})
    result={'schema_version':'phase0-artifact-spike-1','scope':'Original synthetic author-selected page MCIDs only',
            'script_sha256':sha(Path(__file__)),'source_sha256':sha(source),'result_sha256':sha(output),
            'operation':operation,'validator_before':{'status':before['status'],'counts':before.get('counts')},
            'validator_after':{'status':after['status'],'counts':after.get('counts')},
            'fidelity_status':fidelity['status'],'all_pages_compared':len(fidelity['pages']),
            'maximum_changed_pixel_fraction':max(page.get('changed_pixel_fraction',1) for page in fidelity['pages']),
            'semantic_assertions':{'status':'pass' if semantics_pass else 'fail','meaningful_repeated_body_mcid_2_remains_tagged':semantics_pass,
                                   'selected_header_footer_regions_are_artifacts':semantics_pass,
                                   'original_input_unchanged':sha(source)==before_hash},
            'shared_form_baseline_validator':{'status':shared_baseline['status'],'counts':shared_baseline.get('counts')},
            'shared_form_refusal':shared_result,
            'limitations':['No generic running-header/footer detection was implemented or evaluated.',
                           'Decisions are exact author ground truth tied to the input hash and region hash.',
                           'No shared or unshared Form XObjects, MCR/OBJR leaves, ID trees, custom roles, hierarchical ParentTrees, forms or signed-input workflows are supported.',
                           'No repeated-image, alternating-header, chapter-opening or footnote heuristic was evaluated.',
                           'Three pages establish a bounded object-update prototype, not whole-book generality.',
                           'Semantic correctness of arbitrary artifact decisions still requires human review.'],
            'recommendation':'Bounded page-level artifact conversion is viable after validated explicit decisions. Generic book furniture removal remains a separate engineering investigation; shared Form cases must route to manual review.'}
    positive=(before['status']=='pass' and after['status']=='pass' and fidelity['status']=='pass' and semantics_pass and sha(source)==before_hash)
    refusal=(shared_result['status']=='refused' and shared_result['input_unchanged'] and not shared_result['output_exists'])
    result['status']='pass' if positive and refusal else 'fail'
    write(out/'results.json',result)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='pass' else 1


if __name__=='__main__':
    raise SystemExit(main())
