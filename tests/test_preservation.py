"""Adversarial checks for source-conserving tagging checkpoints."""
import hashlib
from pathlib import Path

import pikepdf
import pytest

from pdf_remediator.preservation import preserve_painting


def fixture(path, content, owners=None, dangling=None, list_shape=False, link_targets=0):
    with pikepdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(200, 200))
        page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)))
        page.obj.Contents = pdf.make_stream(content)
        if owners is not None:
            tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
            elements, slots = {}, []
            for mcid, (name, role) in enumerate(owners):
                if name not in elements:
                    elements[name] = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name(role), P=tree, Pg=page.obj, K=pikepdf.Array()))
                elements[name].K.append(mcid)
                slots.append(elements[name])
            if dangling is not None:
                owner = elements[dangling]
                owner.K.append(len(slots))
                slots.append(owner)
            tree.K = pikepdf.Array(elements.values())
            tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array(slots)])))
            if list_shape:
                first, body = list(elements.values())
                li = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.LI, P=tree, Pg=page.obj))
                if link_targets:
                    label = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Lbl, P=li, Pg=page.obj, K=pikepdf.Array([first])))
                    first.P = label
                    page.obj.Annots = pikepdf.Array()
                    for index in range(link_targets):
                        annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=pikepdf.Array([20, 150, 40, 170]), Dest=pikepdf.Array([page.obj, pikepdf.Name.Fit]), Contents="Jump to chapter", StructParent=index + 1))
                        page.obj.Annots.append(annotation)
                        first.K.append(pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Pg=page.obj, Obj=annotation))
                        tree.ParentTree.Nums.extend([index + 1, first])
                    li.K = pikepdf.Array([label, body])
                else:
                    first.P = li
                    li.K = pikepdf.Array([first, body])
                body.P = li
                tree.K = pikepdf.Array([li])
            page.obj.StructParents = 0
            pdf.Root.StructTreeRoot = tree
        pdf.save(path)
    return path


def wrap(mcid, text, role="P", operator="Tj"):
    return f"/{role} <</MCID {mcid}>> BDC ({text}) {operator} EMC ".encode()


PREFIX = b"BT /F1 12 Tf 1 0 0 1 20 160 Tm 18 TL "


def test_same_semantic_owner_coalesces_without_reassigning(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(abcd) Tj ET")
    engine = fixture(tmp_path / "engine.pdf", PREFIX + wrap(0, "ab") + wrap(1, "cd") + b"ET", [("one", "/P"), ("one", "/P")])
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, engine)]
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out)
    assert report["status"] == "pass"
    assert report["changes"]["same_owner_text_runs_restored"] == 1
    with pikepdf.open(out) as pdf:
        assert list(pdf.Root.StructTreeRoot.K[0].K) == [0]
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][1] is None
        shows = [i for i in pikepdf.parse_content_stream(pdf.pages[0]) if str(i.operator) == "Tj"]
        assert len(shows) == 1 and bytes(shows[0].operands[0]) == b"abcd"
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, engine)] == hashes
    assert report["all_page_fidelity_required"] and report["independent_validation_required"]


def test_distinct_owners_never_get_merged(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(abcd) Tj ET")
    engine = fixture(tmp_path / "engine.pdf", PREFIX + wrap(0, "ab", "Lbl") + wrap(1, "cd", "LBody") + b"ET", [("label", "/Lbl"), ("body", "/LBody")])
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out)
    assert report["changes"]["mixed_owner_text_runs_retained"] == 1
    with pikepdf.open(out) as pdf:
        assert len(pdf.Root.StructTreeRoot.K) == 2
        assert [str(e.S) for e in pdf.Root.StructTreeRoot.K] == ["/Lbl", "/LBody"]
        assert [list(e.K) for e in pdf.Root.StructTreeRoot.K] == [[0], [1]]


def test_partial_same_owner_coalescing_keeps_the_distinct_label(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"[(lab) -200 (one) -200 (two)] TJ ET")
    content = PREFIX + b"/Lbl <</MCID 0>> BDC [(lab)] TJ EMC /LBody <</MCID 1>> BDC [-200 (one)] TJ EMC /LBody <</MCID 2>> BDC [-200 (two)] TJ EMC ET"
    engine = fixture(tmp_path / "engine.pdf", content, [("label", "/Lbl"), ("body", "/LBody"), ("body", "/LBody")])
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out)
    assert report["changes"]["same_owner_partial_text_runs_restored"] == 1
    with pikepdf.open(out) as pdf:
        assert [str(e.S) for e in pdf.Root.StructTreeRoot.K] == ["/Lbl", "/LBody"]
        assert [list(e.K) for e in pdf.Root.StructTreeRoot.K] == [[0], [1]]
        shows = [i for i in pikepdf.parse_content_stream(pdf.pages[0]) if str(i.operator) == "TJ"]
        assert len(shows) == 2
        assert list(shows[1].operands[0]) == [-200, pikepdf.String("one"), -200, pikepdf.String("two")]


@pytest.mark.parametrize("edge_spaces", [False, True])
def test_same_paragraph_artifact_spaces_restore_exact_source_without_semantic_regrouping(tmp_path, edge_spaces):
    import pypdfium2 as pdfium

    text = " alpha beta " if edge_spaces else "alpha beta"
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(" + text.encode() + b") Tj ET")
    gap = b"/Artifact BMC ( ) Tj EMC "
    content = PREFIX + (gap if edge_spaces else b"") + wrap(0, "alpha") + gap + wrap(1, "beta") + (gap if edge_spaces else b"") + b"ET"
    engine = fixture(tmp_path / "engine.pdf", content, [("one", "/P"), ("one", "/P")])
    originals = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, engine)]
    out = tmp_path / "restored.pdf"
    report = preserve_painting(source, engine, out)
    assert report["status"] == "pass" and not report["semantic_review_required"]
    assert report["changes"]["same_paragraph_artifact_space_runs_restored"] == 1
    assert report["changes"]["literal_space_artifact_fragments_absorbed"] == (3 if edge_spaces else 1)
    with pikepdf.open(source) as original, pikepdf.open(out) as restored:
        assert len(restored.Root.StructTreeRoot.K) == 1 and str(restored.Root.StructTreeRoot.K[0].S) == "/P"
        assert list(restored.Root.StructTreeRoot.K[0].K) == [0]
        assert restored.Root.StructTreeRoot.ParentTree.Nums[1][1] is None
        unmarked = [i for i in pikepdf.parse_content_stream(restored.pages[0]) if str(i.operator) not in {"BDC", "BMC", "EMC"}]
        assert pikepdf.unparse_content_stream(unmarked) == pikepdf.unparse_content_stream(pikepdf.parse_content_stream(original.pages[0]))
    views = []
    for path in (source, out):
        with pdfium.PdfDocument(str(path)) as document:
            page = document[0]
            bitmap = page.render(scale=96 / 72)
            textpage = page.get_textpage()
            try:views.append((bitmap.to_pil().convert("RGB").tobytes(), textpage.get_text_range()))
            finally:textpage.close();bitmap.close();page.close()
    assert views[0] == views[1]
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, engine)] == originals


@pytest.mark.parametrize("shape", ["distinct-owner", "non-space", "artifact-mcid", "artifact-properties", "nested", "TJ"])
def test_artifact_space_restoration_never_absorbs_unsupported_semantics(tmp_path, shape):
    gap = b"/Artifact BMC ( ) Tj EMC "
    owners = [("one", "/P"), ("one", "/P")]
    source_text = b"(alpha beta) Tj "
    left, right = wrap(0, "alpha"), wrap(1, "beta")
    if shape == "distinct-owner":
        owners[1] = ("two", "/P")
    elif shape == "non-space":
        gap = b"/Artifact BMC (X) Tj EMC "
        source_text = b"(alphaXbeta) Tj "
    elif shape == "artifact-mcid":
        gap = b"/Artifact <</MCID 1>> BDC ( ) Tj EMC "
        right = wrap(2, "beta")
        owners.append(("one", "/P"))
    elif shape == "artifact-properties":
        gap = b"/Artifact <</Type /Layout>> BDC ( ) Tj EMC "
    elif shape == "nested":
        gap = b"/Artifact BMC /Artifact BMC ( ) Tj EMC EMC "
    elif shape == "TJ":
        source_text = b"[(alpha) ( ) (beta)] TJ "
        left = b"/P <</MCID 0>> BDC [(alpha)] TJ EMC "
        gap = b"/Artifact BMC [( )] TJ EMC "
        right = b"/P <</MCID 1>> BDC [(beta)] TJ EMC "
    source = fixture(tmp_path / "source.pdf", PREFIX + source_text + b"ET")
    engine = fixture(tmp_path / "engine.pdf", PREFIX + left + gap + right + b"ET", owners)
    before = hashlib.sha256(engine.read_bytes()).hexdigest()
    out = tmp_path / "retained.pdf"
    report = preserve_painting(source, engine, out)
    assert report["status"] == "pass" and report["changes"].get("same_paragraph_artifact_space_runs_restored", 0) == 0
    assert not report["semantic_review_required"]
    with pikepdf.open(engine) as old, pikepdf.open(out) as retained:
        assert pikepdf.unparse_content_stream(pikepdf.parse_content_stream(retained.pages[0])) == pikepdf.unparse_content_stream(pikepdf.parse_content_stream(old.pages[0]))
        assert len(retained.Root.StructTreeRoot.ParentTree.Nums[1]) == len(owners)
        assert all(value is not None for value in retained.Root.StructTreeRoot.ParentTree.Nums[1])
    assert hashlib.sha256(engine.read_bytes()).hexdigest() == before


def test_list_label_regroup_is_explicit_and_records_pending_review(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(1. Entry) Tj ET")
    content = PREFIX + wrap(0, "1.", "Lbl") + b"/Artifact BMC ( ) Tj EMC " + wrap(1, "Entry", "LBody") + b"ET"
    engine = fixture(tmp_path / "engine.pdf", content, [("label", "/Lbl"), ("body", "/LBody")], list_shape=True)
    default = preserve_painting(source, engine, tmp_path / "default.pdf")
    assert not default["semantic_review_required"]
    out = tmp_path / "regrouped.pdf"
    report = preserve_painting(source, engine, out, allow_tag_regrouping=True)
    assert report["changes"]["opt_in_semantic_regroupings"] == 1
    assert report["semantic_review_required"][0]["status"] == "pending"
    assert report["semantic_review_required"][0]["kind"] == "list-label-regroup"
    with pikepdf.open(out) as pdf:
        li = pdf.Root.StructTreeRoot.K[0]
        assert [str(child.S) for child in li.K] == ["/LBody"]
        assert list(li.K[0].K) == [1]
        shows = [i for i in pikepdf.parse_content_stream(pdf.pages[0]) if str(i.operator) == "Tj"]
        assert len(shows) == 1 and bytes(shows[0].operands[0]) == b"1. Entry"


def test_single_target_link_expansion_preserves_annotation_and_required_list_body(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(4.1 Entry 29) Tj ET")
    content = PREFIX + wrap(0, "4.1", "Link") + wrap(1, " Entry 29", "LBody") + b"ET"
    engine = fixture(tmp_path / "engine.pdf", content, [("link", "/Link"), ("body", "/LBody")], list_shape=True, link_targets=1)
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out, allow_tag_regrouping=True)
    assert report["semantic_review_required"][0]["kind"] == "single-target-list-link-expansion"
    with pikepdf.open(out) as pdf:
        li = pdf.Root.StructTreeRoot.K[0]
        assert len(li.K) == 1 and str(li.K[0].S) == "/LBody"
        link = li.K[0].K[0]
        assert str(link.S) == "/Link" and link.P.objgen == li.K[0].objgen
        objr = next(k for k in link.K if isinstance(k, pikepdf.Dictionary))
        assert objr.Obj.objgen == pdf.pages[0].Annots[0].objgen
        assert str(objr.Obj.Dest[1]) == "/Fit"
        assert objr.Obj.Dest[0].objgen == pdf.pages[0].obj.objgen
        assert str(objr.Obj.Contents) == "Jump to chapter"
        assert list(pdf.Root.StructTreeRoot.ParentTree.Nums[1])[1] is None


def test_regroup_never_collapses_multiple_link_targets(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(4.1 Entry 29) Tj ET")
    content = PREFIX + wrap(0, "4.1", "Link") + wrap(1, " Entry 29", "LBody") + b"ET"
    engine = fixture(tmp_path / "engine.pdf", content, [("link", "/Link"), ("body", "/LBody")], list_shape=True, link_targets=2)
    report = preserve_painting(source, engine, tmp_path / "out.pdf", allow_tag_regrouping=True)
    assert not report["semantic_review_required"]
    assert report["changes"]["mixed_owner_text_runs_retained"] == 1


def toc_tail_fixture(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(Chapter 1. Entry) Tj 0 -30 Td (3) Tj ET")
    content = PREFIX + wrap(0, "Chapter 1.", "Link") + b"/Artifact BMC ( ) Tj EMC " + wrap(1, "Entry", "LBody") + b"0 -30 Td " + wrap(2, "3", "LBody") + b"ET"
    engine = fixture(tmp_path / "engine.pdf", content, [("link", "/Link"), ("body", "/LBody"), ("body", "/LBody")], list_shape=True, link_targets=1)
    return source, engine


def test_toc_link_regroup_preserves_trailing_page_number_and_exact_source_painting(tmp_path):
    import pypdfium2 as pdfium

    source, engine = toc_tail_fixture(tmp_path)
    inputs_before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, engine)]
    out = tmp_path / "restored.pdf"
    report = preserve_painting(source, engine, out, allow_tag_regrouping=True)
    assert report["status"] == "pass" and report["version"] == "source-aligned-painting-1.4"
    review = report["semantic_review_required"][0]
    assert review["kind"] == "single-target-list-link-expansion-preserving-tail"
    assert review["retained_body_tail_mcids"] == [2] and review["page"] == 1
    assert review["status"] == "pending" and report["all_page_fidelity_required"]
    with pikepdf.open(source) as original, pikepdf.open(out) as result:
        body = result.Root.StructTreeRoot.K[0].K[0]
        link = body.K[0]
        assert str(body.S) == "/LBody" and str(link.S) == "/Link"
        assert list(body.K)[1:] == [2]
        assert link.P.objgen == body.objgen
        tree_slots = result.Root.StructTreeRoot.ParentTree.Nums[1]
        assert tree_slots[0].objgen == link.objgen and tree_slots[1] is None and tree_slots[2].objgen == body.objgen
        objr = next(child for child in link.K if isinstance(child, pikepdf.Dictionary))
        assert objr.Obj.objgen == result.pages[0].Annots[0].objgen
        assert objr.Obj.Dest[0].objgen == result.pages[0].obj.objgen
        assert str(objr.Obj.Dest[1]) == "/Fit"
        unmarked = [i for i in pikepdf.parse_content_stream(result.pages[0]) if str(i.operator) not in {"BDC", "BMC", "EMC"}]
        assert pikepdf.unparse_content_stream(unmarked) == pikepdf.unparse_content_stream(pikepdf.parse_content_stream(original.pages[0]))
    pictures, text = [], []
    for path in (source, out):
        with pdfium.PdfDocument(str(path)) as document:
            page = document[0]
            bitmap = page.render(scale=96 / 72)
            pictures.append(bitmap.to_pil().convert("RGB").tobytes())
            bitmap.close()
            textpage = page.get_textpage()
            try:
                text.append(textpage.get_text_range())
            finally:
                textpage.close()
            page.close()
    assert pictures[0] == pictures[1] and text[0] == text[1]
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, engine)] == inputs_before


def test_toc_tail_regroup_remains_opt_in(tmp_path):
    source, engine = toc_tail_fixture(tmp_path)
    out = tmp_path / "default.pdf"
    report = preserve_painting(source, engine, out)
    assert report["status"] == "pass" and not report["semantic_review_required"]
    with pikepdf.open(out) as pdf:
        assert [str(child.S) for child in pdf.Root.StructTreeRoot.K[0].K] == ["/Lbl", "/LBody"]
        assert list(pdf.Root.StructTreeRoot.K[0].K[1].K) == [1, 2]


@pytest.mark.parametrize("case", ["nonprefix-body", "nested-body", "unresolved-tail", "described-label", "conflicting-target", "link-outside-title"])
def test_toc_tail_regroup_refuses_unproved_relationships(tmp_path, case):
    source, raw = toc_tail_fixture(tmp_path)
    engine = tmp_path / "modified.pdf"
    with pikepdf.open(raw) as pdf:
        li = pdf.Root.StructTreeRoot.K[0]
        label, body = li.K
        link = label.K[0]
        if case == "nonprefix-body":
            body.K = pikepdf.Array([2, 1])
        elif case == "nested-body":
            span = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.Span, P=body, Pg=pdf.pages[0].obj, K=2))
            body.K = pikepdf.Array([1, span])
            pdf.Root.StructTreeRoot.ParentTree.Nums[1][2] = span
        elif case == "unresolved-tail":
            raw_content = pdf.pages[0].Contents.read_bytes().replace(wrap(2, "3", "LBody"), b"(3) Tj ")
            pdf.pages[0].Contents = pdf.make_stream(raw_content)
        elif case == "described-label":
            label.ID = "must-retain-label-identifier"
        elif case == "conflicting-target":
            pdf.pages[0].Annots[0].A = pikepdf.Dictionary(S=pikepdf.Name.GoTo, D=pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit]))
        elif case == "link-outside-title":
            link.K.append(2)
            body.K = pikepdf.Array([1])
            pdf.Root.StructTreeRoot.ParentTree.Nums[1][2] = link
        pdf.save(engine, deterministic_id=True)
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out, allow_tag_regrouping=True)
    assert report["status"] == "pass"
    assert not report["semantic_review_required"]
    with pikepdf.open(out) as pdf:
        assert [str(child.S) for child in pdf.Root.StructTreeRoot.K[0].K] == ["/Lbl", "/LBody"]
        assert len(pdf.pages[0].Annots) == 1


def test_regroup_never_absorbs_meaningful_artifact_content(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(1.XEntry) Tj ET")
    content = PREFIX + wrap(0, "1.", "Lbl") + b"/Artifact BMC (X) Tj EMC " + wrap(1, "Entry", "LBody") + b"ET"
    engine = fixture(tmp_path / "engine.pdf", content, [("label", "/Lbl"), ("body", "/LBody")], list_shape=True)
    report = preserve_painting(source, engine, tmp_path / "out.pdf", allow_tag_regrouping=True)
    assert not report["semantic_review_required"]


def test_duplicate_quote_advances_corrected_against_original(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(abcd) ' ET")
    engine = fixture(tmp_path / "engine.pdf", PREFIX + wrap(0, "ab", "Lbl", "'") + wrap(1, "cd", "LBody", "'") + b"ET", [("a", "/Lbl"), ("b", "/LBody")])
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out)
    assert report["changes"]["duplicated_quote_advances_removed"] == 1
    with pikepdf.open(out) as pdf:
        assert [str(i.operator) for i in pikepdf.parse_content_stream(pdf.pages[0]) if str(i.operator) in {"'", "Tj"}] == ["'", "Tj"]


def test_nonexistent_reference_pruned_only_after_full_source_inventory(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(abc) Tj ET")
    engine = fixture(tmp_path / "engine.pdf", PREFIX + wrap(0, "abc") + b"ET", [("one", "/P")], dangling="one")
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out)
    assert report["changes"]["nonexistent_mcid_references_removed"] == 1
    with pikepdf.open(out) as pdf:
        assert list(pdf.Root.StructTreeRoot.K[0].K) == [0]
        assert pdf.Root.StructTreeRoot.ParentTree.Nums[1][1] is None


def test_empty_engine_node_pruned_but_replacement_text_never_discarded(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(abc) Tj ET")
    raw = fixture(tmp_path / "raw.pdf", PREFIX + wrap(0, "abc") + b"ET", [("one", "/P"), ("empty", "/P")])
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, raw, out)
    assert report["changes"]["empty_engine_structure_nodes_removed"] == 1
    with pikepdf.open(out) as pdf:
        assert len(pdf.Root.StructTreeRoot.K) == 1
    engine = tmp_path / "replacement.pdf"
    with pikepdf.open(raw) as pdf:
        pdf.Root.StructTreeRoot.K[1].ActualText = "Do not discard semantic content"
        pdf.save(engine, deterministic_id=True)
    report = preserve_painting(source, engine, tmp_path / "refused.pdf")
    assert report["status"] == "needs-manual"
    assert "strand semantic replacement text" in report["reason"]
    assert not (tmp_path / "refused.pdf").exists()


@pytest.mark.parametrize("bad", [PREFIX + wrap(0, "different") + b"ET", PREFIX + wrap(0, "abc") + b"1 0 Td ET", PREFIX + wrap(0, "abc") + b"/Absent Do ET", PREFIX + b"/P /Unknown BDC (abc) Tj EMC ET", PREFIX + b"(abc) Tj ET"])
def test_unsupported_or_ambiguous_mapping_refuses_entire_output(tmp_path, bad):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(abc) Tj ET")
    engine = fixture(tmp_path / "engine.pdf", bad, [("one", "/P")])
    out = tmp_path / "out.pdf"
    report = preserve_painting(source, engine, out)
    assert report["status"] == "needs-manual" and not report["supported"]
    assert not out.exists()


def test_font_or_glyph_map_changes_refuse(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + b"(abc) Tj ET")
    raw = fixture(tmp_path / "raw.pdf", PREFIX + wrap(0, "abc") + b"ET", [("one", "/P")])
    engine = tmp_path / "engine.pdf"
    with pikepdf.open(raw) as pdf:
        pdf.pages[0].Resources.Font.F1.Encoding = pikepdf.Name.WinAnsiEncoding
        pdf.save(engine, deterministic_id=True)
    report = preserve_painting(source, engine, tmp_path / "out.pdf")
    assert report["status"] == "needs-manual"
    assert "painting resource /Font" in report["reason"]


def test_existing_tags_and_overwrite_refused(tmp_path):
    source = fixture(tmp_path / "source.pdf", PREFIX + wrap(0, "abc") + b"ET", [("one", "/P")])
    engine = fixture(tmp_path / "engine.pdf", PREFIX + wrap(0, "abc") + b"ET", [("one", "/P")])
    assert preserve_painting(source, engine, tmp_path / "out.pdf")["status"] == "needs-manual"
    with pytest.raises(ValueError):
        preserve_painting(source, engine, source)
    existing = tmp_path / "existing.pdf"
    existing.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        preserve_painting(source, engine, existing)
    assert existing.read_bytes() == b"keep"


def line_fixture(directory, variant='plain'):
    """Authored text and bundled licensed fonts; no corpus or native tools."""
    import runpy
    corpus = runpy.run_path(str(Path(__file__).parents[1] / 'eval/build_corpus.py'))
    corpus['register_fonts'](directory)
    source = directory / 'lines.pdf'
    canvas = corpus['new_canvas'](source, 'Original synthetic line-boundary control')
    canvas.setFont(corpus['FONT'], 11)
    first = 'A librarian places blue cards'
    second = 'beside a fictional reading lamp'
    if variant == 'hyphen':
        first += '-'
    elif variant == 'existing-space':
        first += ' '
    elif variant == 'punctuation':
        second = '(beside a fictional reading lamp)'
    elif variant == 'non-ascii':
        second = 'caf\u00e9 beside a reading lamp'
    elif variant == 'leading-space':
        second = ' ' + second
    elif variant == 'digits':
        first += ' 123'
    canvas.drawString(48, 670, first)
    if variant == 'font-change':
        canvas.setFont(corpus['FONT_BOLD'], 11)
    if variant == 'font-size-change':
        canvas.setFont(corpus['FONT'], 12)
    canvas.drawString(180 if variant == 'column' else 300 if variant == 'same-line' else 48,
                      620 if variant == 'gap' else 685 if variant == 'upward' else 670 if variant == 'same-line' else 654, second)
    if variant == 'three-lines':
        canvas.drawString(48, 638, 'while three fictional observations remain available')
    if variant == 'repeated':
        canvas.drawString(48, 638, first)
    canvas.save()
    modified = directory / 'modified.pdf'
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0]
        content = page.Contents.read_bytes()
        if variant == 'text-state':
            content = b'1 Tr\n' + content
        elif variant == 'transform':
            content = b'1 0 0 1 3 4 cm\n' + content
        elif variant == 'tj-array':
            content = content.replace(b'(' + first.encode() + b') Tj',
                                      b'[(' + first.encode() + b')] TJ')
        elif variant == 'rotated-text':
            content = content.replace(b'1 0 0 1 48 670 Tm', b'0 1 -1 0 48 670 Tm')
        elif variant == 'extra-show':
            content = content.replace(b'(' + first.encode() + b') Tj', b'(' + first.encode() + b') Tj ( extra) Tj')
        elif variant == 'font-encoding':
            for font in page.Resources.Font.values():
                font.Encoding = pikepdf.Name.WinAnsiEncoding
        elif variant == 'cmap-multiple-blocks':
            for font in page.Resources.Font.values():
                cmap = font.ToUnicode.read_bytes().replace(b'128 beginbfchar', b'64 beginbfchar')
                cmap = cmap.replace(b'<40> <0040>', b'endbfchar\n64 beginbfchar\n<40> <0040>')
                font.ToUnicode.write(cmap)
        elif variant == 'changed-map':
            for font in page.Resources.Font.values():
                font.ToUnicode.write(font.ToUnicode.read_bytes().replace(b'<20> <0020>', b'<20> <0058>'))
        page.Contents = pdf.make_stream(content)
        pdf.save(modified, deterministic_id=True)
    source.write_bytes(modified.read_bytes())
    modified.unlink()
    engine = directory / 'engine.pdf'
    with pikepdf.open(source) as pdf:
        page = pdf.pages[0]
        tree = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        parent = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                                  S=pikepdf.Name.P, P=tree, Pg=page.obj, K=pikepdf.Array()))
        tree.K = pikepdf.Array([parent])
        slots, instructions = [], []
        for instruction in pikepdf.parse_content_stream(page):
            if str(instruction.operator) in ('Tj', 'TJ'):
                mcid = len(slots)
                owner = parent
                if variant == 'distinct-owner' and mcid == 1:
                    owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                        S=pikepdf.Name.P, P=tree, Pg=page.obj, K=pikepdf.Array()))
                    tree.K.append(owner)
                owner.K.append(mcid)
                slots.append(owner)
                instructions.append(pikepdf.ContentStreamInstruction(
                    [pikepdf.Name.P, pikepdf.Dictionary(MCID=mcid)], pikepdf.Operator('BDC')))
                instructions.append(instruction)
                instructions.append(pikepdf.ContentStreamInstruction([], pikepdf.Operator('EMC')))
            else:
                instructions.append(instruction)
        if variant == 'heading-owner':
            parent.S = pikepdf.Name.H1
        elif variant == 'mcr-children':
            parent.K = pikepdf.Array([pikepdf.Dictionary(Type=pikepdf.Name.MCR, Pg=page.obj, MCID=k) for k in parent.K])
        if variant == 'reverse-order':
            parent.K = pikepdf.Array(reversed(list(parent.K)))
        if variant == 'replacement-text':
            parent.ActualText = 'Unrelated replacement'
        elif variant == 'ancestor-replacement':
            tree.ActualText = 'Unrelated ancestor replacement'
        tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Array(slots)])))
        page.obj.StructParents = 0
        pdf.Root.StructTreeRoot = tree
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(instructions))
        pdf.save(engine, deterministic_id=True)
    return source, engine


def test_source_line_separator_is_automatic_and_preserves_structure_and_pixels(tmp_path):
    from pdf_remediator.inspection import compare_fidelity
    source, engine = line_fixture(tmp_path)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, engine)]
    output = tmp_path / 'out.pdf'
    result = preserve_painting(source, engine, output)
    assert result['status'] == 'pass'
    assert result['changes']['source_line_separators_added'] == 1
    assert result['automatic_line_separators'] == [{'page': 1, 'mcid': 0, 'next_mcid': 1,
            'origin': 'automatic-source-line-separator', 'human_verified': False}]
    assert result['semantic_review_required'] == []
    assert result['independent_validation_required'] and result['all_page_fidelity_required']
    assert compare_fidelity(source, output)['status'] == 'pass'
    with pikepdf.open(output) as pdf:
        shows = [i for i in pikepdf.parse_content_stream(pdf.pages[0]) if str(i.operator) == 'Tj']
        assert bytes(shows[0].operands[0]) == b'A librarian places blue cards '
        assert bytes(shows[1].operands[0]) == b'beside a fictional reading lamp'
        assert list(pdf.Root.StructTreeRoot.K[0].K) == [0, 1]
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, engine)] == hashes


@pytest.mark.parametrize('variant', ['hyphen', 'existing-space', 'punctuation', 'non-ascii',
    'column', 'gap', 'font-change', 'repeated', 'text-state', 'transform', 'tj-array',
    'changed-map', 'distinct-owner', 'reverse-order', 'replacement-text', 'ancestor-replacement'])
def test_ambiguous_line_boundaries_keep_original_text_bytes(tmp_path, variant):
    source, engine = line_fixture(tmp_path, variant)
    output = tmp_path / 'out.pdf'
    result = preserve_painting(source, engine, output)
    assert result['status'] == 'pass'
    assert result['changes']['source_line_separators_added'] == 0
    assert result['automatic_line_separators'] == []
    with pikepdf.open(source) as before, pikepdf.open(output) as after:
        old = [i for i in pikepdf.parse_content_stream(before.pages[0]) if str(i.operator) in ('Tj', 'TJ')]
        new = [i for i in pikepdf.parse_content_stream(after.pages[0]) if str(i.operator) in ('Tj', 'TJ')]
        assert [str(i) for i in old] == [str(i) for i in new]


def test_line_fixture_is_reproducible_without_local_corpus(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    a = line_fixture(first)
    b = line_fixture(second)
    assert [p.read_bytes() for p in a] == [p.read_bytes() for p in b]


@pytest.mark.parametrize('variant', ['leading-space', 'digits', 'font-size-change', 'same-line',
    'upward', 'rotated-text', 'extra-show', 'font-encoding', 'cmap-multiple-blocks',
    'heading-owner', 'mcr-children'])
def test_additional_layout_and_font_shapes_leave_text_untouched(tmp_path, variant):
    from pdf_remediator.inspection import compare_fidelity
    source, engine = line_fixture(tmp_path, variant)
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, engine)]
    output = tmp_path / 'out.pdf'
    report = preserve_painting(source, engine, output)
    assert report['status'] == 'pass'
    assert report['automatic_line_separators'] == []
    assert report['changes']['source_line_separators_added'] == 0
    with pikepdf.open(source) as original, pikepdf.open(output) as result:
        old = [str(i) for i in pikepdf.parse_content_stream(original.pages[0]) if str(i.operator) in ('Tj', 'TJ')]
        new = [str(i) for i in pikepdf.parse_content_stream(result.pages[0]) if str(i.operator) in ('Tj', 'TJ')]
        assert old == new
    assert compare_fidelity(source, output)['status'] == 'pass'
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, engine)] == before


def test_three_wrapped_lines_preserve_both_boundaries_without_rewriting_order(tmp_path):
    from pdf_remediator.inspection import compare_fidelity
    source, engine = line_fixture(tmp_path, 'three-lines')
    output = tmp_path / 'out.pdf'
    report = preserve_painting(source, engine, output)
    assert report['status'] == 'pass' and report['changes']['source_line_separators_added'] == 2
    assert [(r['mcid'], r['next_mcid']) for r in report['automatic_line_separators']] == [(0, 1), (1, 2)]
    assert all(r['human_verified'] is False for r in report['automatic_line_separators'])
    assert compare_fidelity(source, output)['status'] == 'pass'
    with pikepdf.open(output) as pdf:
        shows = [bytes(i.operands[0]) for i in pikepdf.parse_content_stream(pdf.pages[0]) if str(i.operator) == 'Tj']
        assert len(shows) == 3 and shows[0].endswith(b'cards ') and shows[1].endswith(b'lamp ')
        assert shows[2] == b'while three fictional observations remain available'
        assert list(pdf.Root.StructTreeRoot.K[0].K) == [0, 1, 2]


@pytest.mark.parametrize('unsupported_second_page', [False, True])
def test_line_mcid_bindings_are_page_specific_and_unsupported_page_is_unchanged(tmp_path, unsupported_second_page):
    from pdf_remediator.inspection import compare_fidelity
    source, engine = line_fixture(tmp_path)
    for path in (source, engine):
        modified = tmp_path / 'multi-page.pdf'
        with pikepdf.open(path) as pdf:
            pdf.pages.append(pdf.pages[0])
            if unsupported_second_page:
                page = pdf.pages[1]
                page.Contents = pdf.make_stream(b'1 0 0 1 2 0 cm\n' + page.Contents.read_bytes())
            if '/StructTreeRoot' in pdf.Root:
                tree = pdf.Root.StructTreeRoot
                tree.K = pikepdf.Array()
                nums = pikepdf.Array()
                for index, page in enumerate(pdf.pages):
                    owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                        S=pikepdf.Name.P, P=tree, Pg=page.obj, K=pikepdf.Array([0, 1])))
                    tree.K.append(owner)
                    nums.extend([index, pikepdf.Array([owner, owner])])
                    page.obj.StructParents = index
                tree.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=nums))
            pdf.save(modified, deterministic_id=True)
        path.write_bytes(modified.read_bytes())
        modified.unlink()
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, engine)]
    output = tmp_path / 'out.pdf'
    report = preserve_painting(source, engine, output)
    assert report['status'] == 'pass'
    expected = 1 if unsupported_second_page else 2
    assert report['changes']['source_line_separators_added'] == expected
    assert [r['page'] for r in report['automatic_line_separators']] == list(range(1, expected + 1))
    assert all(r['mcid'] == 0 and r['next_mcid'] == 1 and r['human_verified'] is False
               for r in report['automatic_line_separators'])
    fidelity = compare_fidelity(source, output)
    assert fidelity['status'] == 'pass' and len(fidelity['pages']) == 2
    assert all(page['render_status'] == 'pass' for page in fidelity['pages'])
    with pikepdf.open(engine) as original, pikepdf.open(output) as result:
        assert len(result.pages) == 2
        for index in range(2):
            assert list(result.Root.StructTreeRoot.K[index].K) == [0, 1]
        if unsupported_second_page:
            old = [str(i) for i in pikepdf.parse_content_stream(original.pages[1]) if str(i.operator) == 'Tj']
            new = [str(i) for i in pikepdf.parse_content_stream(result.pages[1]) if str(i.operator) == 'Tj']
            assert old == new
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, engine)] == before



@pytest.mark.parametrize("change", [None, "pixels", "decode", "colorspace"])
def test_encoded_image_resource_requires_exact_bytes_and_interpretation(tmp_path, change):
    """Real JPEG resources may pass; altered image bytes/meaning must refuse."""
    import io
    from PIL import Image
    from pdf_remediator.inspection import compare_fidelity

    paths = [tmp_path / "source.pdf", tmp_path / "engine.pdf"]
    source = fixture(paths[0], PREFIX + b"(abcd) Tj ET q 20 0 0 20 30 40 cm /Im1 Do Q")
    engine = fixture(paths[1], PREFIX + wrap(0, "ab") + wrap(1, "cd") +
                     b"ET /Figure <</MCID 2>> BDC q 20 0 0 20 30 40 cm /Im1 Do Q EMC",
                     [("one", "/P"), ("one", "/P"), ("picture", "/Figure")])
    for index, path in enumerate(paths):
        image = Image.new("RGB", (2, 2), "blue" if index and change == "pixels" else "red")
        data = io.BytesIO()
        image.save(data, format="JPEG")
        image.close()
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            resource = pdf.make_stream(data.getvalue())
            resource.Type = pikepdf.Name.XObject
            resource.Subtype = pikepdf.Name.Image
            resource.Width = resource.Height = 2
            resource.BitsPerComponent = 8
            resource.ColorSpace = pikepdf.Name.DeviceGray if index and change == "colorspace" else pikepdf.Name.DeviceRGB
            resource.Filter = pikepdf.Name.DCTDecode
            if index and change == "decode":
                resource.Decode = pikepdf.Array([1, 0, 1, 0, 1, 0])
            pdf.pages[0].obj.Resources.XObject = pikepdf.Dictionary(Im1=resource)
            pdf.save(path)
    before_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    output = tmp_path / "result.pdf"
    report = preserve_painting(source, engine, output)
    if change is None:
        assert report["status"] == "pass"
        assert report["changes"]["same_owner_text_runs_restored"] == 1
        assert compare_fidelity(source, output)["status"] == "pass"
    else:
        assert report["status"] == "needs-manual"
        assert not output.exists()
    assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths] == before_hashes
