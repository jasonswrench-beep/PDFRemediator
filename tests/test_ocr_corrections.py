"""Real encoded/visible proof tests for the first bounded OCR word editor."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import threading

import pikepdf
import pypdfium2 as pdfium
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from pdf_remediator import ocr_corrections as oc


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def bind(path):
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def font(pdf, variable_width=False):
    characters = "".join(chr(c) for c in range(32, 127)) + "éÅÅ"
    codes = {character: index + 1 for index, character in enumerate(characters)}
    order = [".notdef"] + ["g" + str(i) for i in range(1, len(characters) + 1)]
    widths = [300 + index % 7 * 50 if variable_width else 500 for index in range(len(order))]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({ord(character): order[code] for character, code in codes.items()})
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        if name not in (".notdef", order[codes[" "]]):
            right = widths[order.index(name)] - 30
            pen.moveTo((30, 0)); pen.lineTo((right, 0)); pen.lineTo((right, 700)); pen.lineTo((30, 700)); pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (widths[index], 0) for index, name in enumerate(order)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({"familyName": "EditorFixture", "styleName": "Regular", "uniqueFontIdentifier": "EditorFixture-Regular",
                            "fullName": "EditorFixture Regular", "psName": "EditorFixture-Regular"})
    builder.setupPost(); builder.setupMaxp()
    buffer = io.BytesIO(); builder.save(buffer)
    descriptor = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.FontDescriptor, FontName=pikepdf.Name.EditorFixture,
        Flags=4, FontBBox=pikepdf.Array([0, -200, 500, 800]), ItalicAngle=0, Ascent=800, Descent=-200, CapHeight=700,
        StemV=80, FontFile2=pdf.make_stream(buffer.getvalue())))
    descendant = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2,
        BaseFont=pikepdf.Name.EditorFixture, CIDSystemInfo=pikepdf.Dictionary(Registry="Adobe", Ordering="Identity", Supplement=0),
        FontDescriptor=descriptor, CIDToGIDMap=pikepdf.Name.Identity, DW=500,
        W=pikepdf.Array([0, pikepdf.Array(widths)])))
    pairs = "\n".join(f"<{code:04X}> <{character.encode('utf-16-be').hex().upper()}>" for character, code in codes.items())
    cmap = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
            "/CMapName /EditorFixture def\n/CMapType 2 def\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            + str(len(codes)) + " beginbfchar\n" + pairs + "\nendbfchar\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n")
    value = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0,
        BaseFont=pikepdf.Name.EditorFixture, Encoding=pikepdf.Name("/Identity-H"), DescendantFonts=pikepdf.Array([descendant]),
        ToUnicode=pdf.make_stream(cmap.encode("ascii"))))
    return value, codes


def publish_bundle(bundle, source, artifact, prepared, *, profile="angles", lineage=None):
    report = {"mode": "fix", "status": "needs-manual", "run_fingerprint": "controlled-ocr-editor-fixture",
              "input": bind(source), "output": bind(artifact) | {"review_only": True},
              "decision_source": bind(prepared) | {"source_sha256": bind(source)["sha256"]},
              "settings": {"ocr_mode": "textless" if lineage is None else "off", "ocr_profile": profile},
              "fidelity": {"status": "pass"},
              "ocr_pages": [1], "processors": [{"name": "ocr", "status": "completed", "preservation": {"status": "pass"}}]}
    if lineage:
        report["source_lineage"] = bind(lineage)
    dump(bundle / "report.json", report)
    for name in ("decisions.json", "review.json"):
        dump(bundle / name, {})
    (bundle / "review.html").write_text("<p>Controlled test review</p>", encoding="utf-8")
    files = {p.name: bind(p)["sha256"] for p in bundle.iterdir() if p.is_file() and p.name != "manifest.json"}
    dump(bundle / "manifest.json", {"complete": True, "run_fingerprint": report["run_fingerprint"], "files": files})


def fixture_bundle(tmp_path, *, profile="angles", rotated=False, nested=True, words=("bad", "bad", "well"),
                   shared=False, actual_text=False, visible=False, clipping=False, tj_array=False,
                   character_spacing=False, external=None, protected_page=False, clip_text=False, variable_width=False):
    source = tmp_path / "original.pdf"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 200))
        image = pdf.make_stream(b"\xff\xff\xff")
        image.Type = pikepdf.Name.XObject; image.Subtype = pikepdf.Name.Image
        image.Width = 1; image.Height = 1; image.ColorSpace = pikepdf.Name.DeviceRGB; image.BitsPerComponent = 8
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(I=image))
        page.Contents = pdf.make_stream(b"q 300 0 0 200 0 0 cm /I Do Q\n")
        if protected_page:
            page = pdf.add_blank_page(page_size=(300, 200))
            page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(H=pikepdf.Dictionary(Type=pikepdf.Name.Font,
                Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)))
            page.Contents = pdf.make_stream(b"BT /H 14 Tf 20 100 Td (Protected original text.) Tj ET")
        pdf.Root.Lang = "en-GB"; pdf.docinfo.Title = "Original source title"
        pdf.save(source)
    bundle = tmp_path / "bundle"; bundle.mkdir()
    artifact = bundle / "artifact.pdf"; prepared = bundle / "prepared.pdf"
    with pikepdf.open(source) as pdf:
        f, codes = font(pdf, variable_width)
        parts = ["q", "0.866025403784 0.5 -0.5 0.866025403784 70 30 cm" if rotated else "1 0 0 1 0 0 cm",
                 "BT /F 12 Tf", "0 Tr" if visible else "3 Tr"]
        if clipping:
            parts += ["0 0 100 100 re W n"]
        if character_spacing:
            parts += ["1 Tc"]
        for i, word in enumerate(words):
            raw = "".join(f"{codes[c]:04X}" for c in word + " ")
            props = f"/MCID {i} /ActualText (old)" if actual_text else f"/MCID {i}"
            xpos = 295 if clip_text and i == 0 else 20 + i * 60
            parts += [f"1 0 0 1 {xpos} 80 Tm 100 Tz", f"/P << {props} >> BDC",
                      f"[<{raw}>] TJ" if tj_array else f"<{raw}> Tj", "EMC"]
        parts += ["ET Q"]
        leaf = pdf.make_stream(("\n".join(parts)).encode("ascii")); leaf.Type = pikepdf.Name.XObject
        leaf.Subtype = pikepdf.Name.Form; leaf.BBox = pikepdf.Array([0, 0, 300, 200])
        leaf.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F=f))
        root_form = leaf
        if nested:
            outer = pdf.make_stream(b"q /Inner Do Q\n"); outer.Type = pikepdf.Name.XObject; outer.Subtype = pikepdf.Name.Form
            outer.BBox = pikepdf.Array([0, 0, 300, 200]); outer.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Inner=leaf))
            root_form = outer
        page = pdf.pages[0]; page.Resources.XObject.OCR = root_form
        raw = page.Contents.read_bytes() + b"q /OCR Do Q\n" + (b"q /OCR Do Q\n" if shared else b"")
        page.Contents = pdf.make_stream(raw)
        if external == "appearance":
            annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Stamp,
                Rect=pikepdf.Array([0, 0, 20, 20]), AP=pikepdf.Dictionary(N=leaf)))
            page.Annots = pikepdf.Array([annotation])
        elif external == "soft-mask":
            page.Resources.ExtGState = pikepdf.Dictionary(GS=pikepdf.Dictionary(SMask=pikepdf.Dictionary(S=pikepdf.Name.Luminosity, G=leaf)))
        elif external == "structure-actualtext":
            pdf.Root.StructTreeRoot = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot,
                K=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name.P, ActualText="override"))))
        pdf.docinfo.Title = "Earlier accepted metadata must survive"
        pdf.save(artifact)
    shutil.copyfile(artifact, prepared)
    publish_bundle(bundle, source, artifact, prepared, profile=profile)
    return bundle


def plan_for(bundle, path, index=0, value="dad", **changes):
    inv = oc.get_inventory(bundle); item = inv["items"][index]
    row = {"id": item["id"], "context_sha256": item["context_sha256"], "original": item["current"], "value": value,
           "reviewer": "Developer fixture", "reviewed_at": "2026-10-25"}
    row["acceptance_sha256"] = digest(row | {key: inv[key] for key in ("source_sha256", "document_sha256", "inventory_sha256")})
    plan = {"schema_version": oc.PLAN_SCHEMA, **{key: inv[key] for key in ("source_sha256", "document_sha256", "inventory_sha256")},
            "workspace_id": "controlled-fixture", "revision": 3, "corrections": [row], "human_approved": False, "accessibility_approved": False}
    plan.update(changes); dump(path, plan)
    return inv, plan


def text(path):
    with pdfium.PdfDocument(path) as pdf:
        result = []
        for page in pdf:
            tp = page.get_textpage()
            try: result.append(tp.get_text_range())
            finally: tp.close(); page.close()
        return result


@pytest.mark.parametrize("profile", ["standard", "table-lines", "angles"])
@pytest.mark.parametrize("rotated", [False, True])
def test_real_nested_form_correction_preserves_source_other_occurrences_and_current_metadata(tmp_path, profile, rotated):
    bundle = fixture_bundle(tmp_path, profile=profile, rotated=rotated, protected_page=True)
    before = {str(p): bind(p)["sha256"] for p in tmp_path.rglob("*") if p.is_file()}
    path = tmp_path / "accepted.json"; inv, plan = plan_for(bundle, path, index=1)
    assert [item["current"] for item in inv["items"]] == ["bad", "bad", "well"]
    assert inv["items"][0]["id"] != inv["items"][1]["id"]
    assert inv["items"][1]["context_text"] == "bad bad well"
    result = oc.create_derivative(bundle, path, tmp_path / "corrected", expected_plan_sha256=bind(path)["sha256"])
    assert text(result["source_path"])[0].split() == ["bad", "dad", "well"]
    assert text(result["source_path"])[1] == text(tmp_path / "original.pdf")[1]
    proof = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert proof["status"] == "pass-explicit-ocr-text-corrections"
    assert proof["literal_substitutions_verified"] and proof["encoded_unicode_verified"]
    assert all(page["changed_pixel_fraction"] == 0 for page in proof["fidelity"]["pages"])
    assert proof["fidelity"]["status"] == "fail"  # Retain the intentional raw text difference.
    assert proof["human_approved"] is proof["accessibility_approved"] is False
    assert proof["AI_calls"] == proof["OCR_calls"] == 0
    with pikepdf.open(result["source_path"]) as pdf:
        assert str(pdf.docinfo.Title) == "Earlier accepted metadata must survive"
        assert str(pdf.Root.Lang) == "en-GB"
    lineage = oc.validate_lineage(result["lineage_path"], result["source_path"], result["lineage_sha256"])
    assert lineage["original"] == bind(tmp_path / "original.pdf") and lineage["review_required"] is True
    assert all(bind(p)["sha256"] == h for p, h in before.items())


@pytest.mark.parametrize("options,reason", [
    ({"shared": True}, "uniquely invoked"), ({"visible": True}, "Visible"), ({"clipping": True}, "clipped"),
    ({"tj_array": True}, "individual OCR Tj"), ({"actual_text": True}, "ActualText"),
    ({"character_spacing": True}, "specially spaced"), ({"external": "appearance"}, "uniquely invoked"),
    ({"external": "soft-mask"}, "uniquely invoked"), ({"external": "structure-actualtext"}, "ActualText")])
def test_unsupported_occurrences_are_explicitly_read_only(tmp_path, options, reason):
    bundle = fixture_bundle(tmp_path, **options)
    inv = oc.get_inventory(bundle)
    assert inv["eligible"] is False and not inv["items"]
    assert reason in str(inv.get("unsupported_pages", []))


@pytest.mark.parametrize("value", ["", "two words", " leading", "trailing ", "line\nbreak", "nul\0", "x" * 257, "Ω", "😀", "\u200d"])
def test_replacement_bounds_and_missing_glyphs_refuse_without_writing(tmp_path, value):
    inv = oc.get_inventory(fixture_bundle(tmp_path))
    with pytest.raises(oc.OCRCorrectionError): oc.validate_replacement(inv["items"][0], value)


@pytest.mark.parametrize("field", ["source_sha256", "document_sha256", "inventory_sha256"])
def test_stale_plan_bindings_refuse(tmp_path, field):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"
    inv, plan = plan_for(bundle, path); plan[field] = "0" * 64; dump(path, plan)
    with pytest.raises(oc.OCRCorrectionError, match="stale"):
        oc.create_derivative(bundle, path, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


@pytest.mark.parametrize("field,value", [("id", "other"), ("context_sha256", "0" * 64), ("original", "other"),
                                         ("value", "cab"), ("reviewer", ""), ("reviewed_at", "invalid")])
def test_stale_or_missing_human_acceptance_refuses(tmp_path, field, value):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"
    inv, plan = plan_for(bundle, path); plan["corrections"][0][field] = value; dump(path, plan)
    with pytest.raises(oc.OCRCorrectionError): oc.create_derivative(bundle, path, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_frozen_plan_hash_and_duplicate_occurrence_refuse(tmp_path):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; inv, plan = plan_for(bundle, path)
    with pytest.raises(oc.OCRCorrectionError, match="frozen"):
        oc.create_derivative(bundle, path, tmp_path / "wrong-hash", expected_plan_sha256="0" * 64)
    plan["corrections"] *= 2; dump(path, plan)
    with pytest.raises(oc.OCRCorrectionError, match="duplicate"):
        oc.create_derivative(bundle, path, tmp_path / "duplicate")


def test_explicit_unicode_change_is_literal_even_when_nfkc_tokens_match(tmp_path):
    bundle = fixture_bundle(tmp_path, words=("Å", "well")); path = tmp_path / "plan.json"
    plan_for(bundle, path, value="Å")
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    assert text(result["source_path"])[0].split()[0] == "Å"
    assert "Å" not in text(result["source_path"])[0]
    assert json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))["encoded_unicode_verified"]


def test_cancelled_or_changed_input_cannot_publish_a_derivative(tmp_path, monkeypatch):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    stop = threading.Event(); stop.set()
    with pytest.raises(InterruptedError): oc.create_derivative(bundle, path, tmp_path / "cancelled", cancel=stop)
    assert not (tmp_path / "cancelled").exists()
    original = oc._verify_output
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        return result
    monkeypatch.setattr(oc, "_verify_output", changed)
    with pytest.raises(oc.OCRCorrectionError, match="changed"):
        oc.create_derivative(bundle, path, tmp_path / "changed")
    assert not (tmp_path / "changed").exists()
    assert not list(tmp_path.glob(".ocr-source-*"))


def test_existing_destination_original_or_result_are_never_overwritten(tmp_path):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    before = bind(bundle / "artifact.pdf")
    with pytest.raises(oc.OCRCorrectionError, match="overwritten"):
        oc.create_derivative(bundle, path, bundle)
    with pytest.raises(oc.OCRCorrectionError, match="separate"):
        oc.create_derivative(bundle, path, bundle / "new")
    assert bind(bundle / "artifact.pdf") == before


def test_lineage_and_plans_can_be_copied_without_rewriting_their_retained_bindings(tmp_path):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    copied = tmp_path / "copied-lineage.json"; shutil.copyfile(result["lineage_path"], copied)
    proof = oc.validate_lineage(copied, result["source_path"], result["lineage_sha256"])
    assert proof["original"] == bind(tmp_path / "original.pdf")
    with pytest.raises(oc.OCRCorrectionError, match="another"):
        oc.validate_lineage(copied, tmp_path / "original.pdf")


def test_later_correction_retains_true_original_and_does_not_restore_old_metadata(tmp_path):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    first = oc.create_derivative(bundle, path, tmp_path / "first")
    later = tmp_path / "later-bundle"; later.mkdir()
    shutil.copyfile(first["source_path"], later / "artifact.pdf"); shutil.copyfile(first["source_path"], later / "prepared.pdf")
    publish_bundle(later, Path(first["source_path"]), later / "artifact.pdf", later / "prepared.pdf", lineage=first["lineage_path"])
    inventory = oc.get_inventory(later)
    assert inventory["true_original"] == bind(tmp_path / "original.pdf")
    plan_for(later, tmp_path / "second-plan.json", index=1, value="cab")
    second = oc.create_derivative(later, tmp_path / "second-plan.json", tmp_path / "second")
    assert text(second["source_path"])[0].split() == ["dad", "cab", "well"]
    proof = oc.validate_lineage(second["lineage_path"], second["source_path"], second["lineage_sha256"])
    assert proof["original"] == bind(tmp_path / "original.pdf")
    metadata = oc.validate_lineage_bindings(second["lineage_path"], second["source_path"], second["lineage_sha256"])
    assert metadata["original"] == proof["original"] and metadata["bindings_verified"]
    Path(first["lineage_path"]).write_text(Path(first["lineage_path"]).read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(oc.OCRCorrectionError, match="dependency"):
        oc.validate_lineage_bindings(second["lineage_path"], second["source_path"], second["lineage_sha256"])
    with pikepdf.open(second["source_path"]) as pdf: assert str(pdf.docinfo.Title) == "Earlier accepted metadata must survive"


def test_forged_evidence_cannot_authorize_additional_text_changes(tmp_path):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    output = Path(result["source_path"]); altered = tmp_path / "altered.pdf"
    with pikepdf.open(output) as pdf:
        outer = pdf.pages[0].Resources.XObject.OCR
        leaf = outer.Resources.XObject.Inner
        instructions = list(pikepdf.parse_content_stream(leaf)); shows = [i for i, item in enumerate(instructions) if str(item.operator) == "Tj"]
        index = shows[-1]; instructions[index] = pikepdf.ContentStreamInstruction(instructions[shows[0]].operands, pikepdf.Operator("Tj"))
        leaf.write(pikepdf.unparse_content_stream(instructions)); pdf.save(altered)
    shutil.copyfile(altered, output)
    lineage_path = Path(result["lineage_path"]); lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    evidence_path = Path(result["evidence_path"]); evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["after_sha256"] = bind(output)["sha256"]; dump(evidence_path, evidence)
    lineage["current_source"] = bind(output); lineage["evidence"] = bind(evidence_path)
    lineage["binding_sha256"] = digest({key: value for key, value in lineage.items() if key != "binding_sha256"}); dump(lineage_path, lineage)
    with pytest.raises(oc.OCRCorrectionError, match="authorized|untouched"):
        oc.validate_lineage(lineage_path, output)


@pytest.mark.parametrize("loss", ["painting", "excluded-literal", "navigation", "raw-annotation"])
def test_resealed_wrong_prior_ocr_cannot_become_a_corrected_source(tmp_path, loss):
    bundle = fixture_bundle(tmp_path, protected_page=loss == "excluded-literal")
    report = json.loads((bundle / "report.json").read_text(encoding="utf-8")); source = Path(report["input"]["path"])
    if loss == "excluded-literal":
        changed = tmp_path / "changed-original.pdf"
        with pikepdf.open(source) as pdf:
            pdf.pages[1].Contents = pdf.make_stream(b"BT /H 14 Tf 3 Tr 20 100 Td (Protected original text.) Tj ET")
            pdf.save(changed)
        shutil.copyfile(changed, source)
    elif loss == "raw-annotation":
        changed = tmp_path / "changed-original.pdf"
        with pikepdf.open(source) as pdf:
            pdf.pages[0].Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,
                Subtype=pikepdf.Name.Text, Rect=pikepdf.Array([20, 20, 30, 30]), Contents="retain-original-note"))])
            pdf.save(changed)
        shutil.copyfile(changed, source)
    artifact = bundle / "artifact.pdf"; changed = tmp_path / "wrong-artifact.pdf"
    with pikepdf.open(artifact) as pdf:
        if loss == "painting":
            pdf.pages[0].Contents = pdf.make_stream(pdf.pages[0].Contents.read_bytes() + b"\n0 g 0 0 100 100 re f\n")
        elif loss == "excluded-literal":
            pdf.pages[1].Contents = pdf.make_stream(b"BT /H 14 Tf 3 Tr 20 100 Td (Wrong hidden original text.) Tj ET")
        elif loss == "navigation":
            pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Dictionary(P="changed")]))
        # For raw-annotation the prior artifact deliberately lacks the source annotation.
        pdf.save(changed)
    shutil.copyfile(changed, artifact); shutil.copyfile(artifact, bundle / "prepared.pdf")
    publish_bundle(bundle, source, artifact, bundle / "prepared.pdf")  # Coherent hashes and claimed pass are insufficient.
    path = tmp_path / "accepted.json"; plan_for(bundle, path)
    with pytest.raises(oc.OCRCorrectionError, match="Original|original"):
        oc.create_derivative(bundle, path, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def test_clipped_word_is_read_only_while_other_occurrences_remain_editable(tmp_path):
    inv = oc.get_inventory(fixture_bundle(tmp_path, clip_text=True))
    assert inv["eligible"]
    assert 1 not in [item["occurrence"] for item in inv["items"]]
    assert any("clipped" in str(row["limitations"]) for row in inv["unsupported_occurrences"])


@pytest.mark.parametrize("tamper", ["unicode-map", "encoded-space"])
def test_independent_proof_rejects_wrong_unicode_or_missing_encoded_space_even_with_resealed_hashes(tmp_path, tamper):
    bundle = fixture_bundle(tmp_path, words=("Å", "well") if tamper == "unicode-map" else ("bad", "well"))
    path = tmp_path / "plan.json"; plan_for(bundle, path, value="Å" if tamper == "unicode-map" else "dad")
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    output = Path(result["source_path"]); altered = tmp_path / "altered.pdf"
    with pikepdf.open(output) as pdf:
        leaf = pdf.pages[0].Resources.XObject.OCR.Resources.XObject.Inner
        if tamper == "unicode-map":
            cmap = leaf.Resources.Font.F.ToUnicode
            before = cmap.read_bytes(); assert b"<212B>" in before
            cmap.write(before.replace(b"<212B>", b"<00C5>"))
        else:
            instructions = list(pikepdf.parse_content_stream(leaf)); index = next(i for i, item in enumerate(instructions) if str(item.operator) == "Tj")
            raw = bytes(instructions[index].operands[0]); instructions[index] = pikepdf.ContentStreamInstruction([pikepdf.String(raw[:-2])], pikepdf.Operator("Tj"))
            leaf.write(pikepdf.unparse_content_stream(instructions))
        pdf.save(altered)
    shutil.copyfile(altered, output)
    lineage_path = Path(result["lineage_path"]); lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    evidence_path = Path(result["evidence_path"]); evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["after_sha256"] = bind(output)["sha256"]; dump(evidence_path, evidence)
    lineage["current_source"] = bind(output); lineage["evidence"] = bind(evidence_path)
    lineage["binding_sha256"] = digest({key: value for key, value in lineage.items() if key != "binding_sha256"}); dump(lineage_path, lineage)
    with pytest.raises(oc.OCRCorrectionError, match="fonts|separators|authorized"):
        oc.validate_lineage(lineage_path, output)


@pytest.mark.parametrize("value,variable_width", [("dadad", False), ("cab", True), ("w", True)])
def test_replacement_length_and_variable_font_width_preserve_neighbor_advance(tmp_path, value, variable_width):
    bundle = fixture_bundle(tmp_path, variable_width=variable_width)
    path = tmp_path / "plan.json"; plan_for(bundle, path, value=value)
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    assert text(result["source_path"])[0].split() == [value, "bad", "well"]
    proof = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert abs(proof["operations"][0]["old_advance_units"] - proof["operations"][0]["new_advance_units"]) < 1e-7
    assert proof["max_untouched_character_delta_points"] <= .001


def test_lineage_freshness_hashes_dependencies_without_pdf_parsing_or_rendering(tmp_path, monkeypatch):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    def forbidden(*args, **kwargs): raise AssertionError("Freshness must not parse or render PDFs")
    for name in ("_scan", "_page_objects", "_page_text", "inspect_pdf", "compare_fidelity", "get_inventory", "_inventory"):
        monkeypatch.setattr(oc, name, forbidden)
    proof = oc.validate_lineage_bindings(result["lineage_path"], result["source_path"], result["lineage_sha256"])
    assert proof["bindings_verified"] and proof["dependency_count"] >= 10
    assert proof["original"] == bind(tmp_path / "original.pdf")
    assert proof["human_approved"] is proof["accessibility_approved"] is False


@pytest.mark.parametrize("dependency", ["original", "current_source", "parent_source", "corrected_from", "prepared", "plan", "evidence", "manifest", "report"])
def test_lineage_freshness_refuses_modified_external_dependencies(tmp_path, dependency):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    lineage = json.loads(Path(result["lineage_path"]).read_text(encoding="utf-8"))
    target = Path(lineage[dependency]["path"]) if dependency not in ("manifest", "report") else bundle / (dependency + ".json")
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(oc.OCRCorrectionError, match="dependency"):
        oc.validate_lineage_bindings(result["lineage_path"], result["source_path"], result["lineage_sha256"])


def test_lineage_freshness_rechecks_inputs_changed_during_hashing(tmp_path, monkeypatch):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    result = oc.create_derivative(bundle, path, tmp_path / "corrected")
    original = (tmp_path / "original.pdf").resolve(); real_sha = oc._sha; changed = []
    def changing(file):
        value = real_sha(file)
        if Path(file).resolve() == original and not changed:
            original.write_bytes(original.read_bytes() + b" "); changed.append(True)
        return value
    monkeypatch.setattr(oc, "_sha", changing)
    with pytest.raises(oc.OCRCorrectionError, match="changed during"):
        oc.validate_lineage_bindings(result["lineage_path"], result["source_path"], result["lineage_sha256"])


def test_other_immutable_review_files_changed_during_correction_cannot_publish(tmp_path, monkeypatch):
    bundle = fixture_bundle(tmp_path); path = tmp_path / "plan.json"; plan_for(bundle, path)
    original = oc._verify_output
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        (bundle / "review.json").write_text('{"changed":true}\n', encoding="utf-8")
        return result
    monkeypatch.setattr(oc, "_verify_output", changed)
    with pytest.raises(oc.OCRCorrectionError, match="immutable"):
        oc.create_derivative(bundle, path, tmp_path / "refused")
    assert not (tmp_path / "refused").exists()


def expanded_fixture(tmp_path, *, rotation=0, crop=False, rotated_form=False, tagged=True, upright=True):
    bundle = fixture_bundle(tmp_path,rotated=rotated_form,protected_page=True)
    source = tmp_path/"original.pdf"; artifact = bundle/"artifact.pdf"; prepared = bundle/"prepared.pdf"
    for path in (source,artifact):
        with pikepdf.open(path,allow_overwriting_input=True) as pdf:
            pdf.pages[0].obj.Rotate = rotation
            if crop:
                pdf.pages[0].MediaBox = pikepdf.Array([10,20,310,220]); pdf.pages[0].CropBox = pikepdf.Array([20,30,280,190])
            if path == artifact:
                unit = oc._scan(artifact,[1])[0][0]; leaf,_ = oc._leaf(pdf,unit)
                if rotation and upright:
                    box = [float(v) for v in pdf.pages[0].obj.get("/CropBox",pdf.pages[0].MediaBox)]
                    frame,_ = oc._display_frame(box,rotation)
                    leaf.write(b"q\n"+" ".join(str(v) for v in frame).encode("ascii")+b" cm\n"+leaf.read_bytes()+b"\nQ\n")
            if path == artifact and tagged:
                leaf.StructParents = 5
                root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
                document = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.Document,P=root))
                owners = []
                for index in range(3):
                    owner = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,S=pikepdf.Name.P,P=document,Pg=pdf.pages[0].obj,
                        K=pikepdf.Dictionary(Type=pikepdf.Name.MCR,Stm=leaf,Pg=pdf.pages[0].obj,MCID=index)))
                    owners.append(owner)
                document.K = pikepdf.Array(owners); root.K = document
                root.ParentTree = pdf.make_indirect(pikepdf.Dictionary(Nums=pikepdf.Array([5,pikepdf.Array(owners)])))
                root.ParentTreeNextKey = 6; pdf.Root.StructTreeRoot = root; pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
            pdf.save(path)
    shutil.copyfile(artifact,prepared); publish_bundle(bundle,source,artifact,prepared)
    return bundle


def expanded_plan(bundle, path, *, kind="replace", value="éñΩЖ", index=0, order="after", rect=None, corrections=None):
    inv = oc.get_inventory(bundle,profile="expanded-v2"); item = inv["items"][index]
    row = {"id":item["id"],"kind":"replace","original":item["current"],"value":value,"context_sha256":item["context_sha256"],
        "reviewer":"Developer fixture","reviewed_at":"2026-10-25"}
    if kind == "insert":
        row.update(kind="insert",id="ocr-insert-"+"a"*32,anchor_id=item["id"],page=item["page"],original="",
            placement={"rect":rect or [.1,.1,.16,.08],"order":order})
    bindings = {key:inv[key] for key in ("source_sha256","document_sha256","inventory_sha256","expansion_sha256")}
    rows = corrections if corrections is not None else [row]
    for entry in rows: entry["acceptance_sha256"] = digest({k:v for k,v in entry.items() if k != "acceptance_sha256"}|bindings)
    plan = {"schema_version":oc.EXPANDED_PLAN_SCHEMA,**bindings,"workspace_id":"expanded-fixture","revision":1,
        "corrections":rows,"human_approved":False,"accessibility_approved":False}
    dump(path,plan); return inv,plan


def test_legacy_inventory_is_bit_exact_while_expanded_profile_binds_new_font(tmp_path):
    bundle = expanded_fixture(tmp_path)
    before = oc.get_inventory(bundle); expanded = oc.get_inventory(bundle,profile="expanded-v2"); after = oc.get_inventory(bundle)
    assert before == after and before["schema_version"] == oc.INVENTORY_SCHEMA
    assert expanded["schema_version"] == oc.EXPANDED_INVENTORY_SCHEMA
    assert expanded["inventory_sha256"] != before["inventory_sha256"]
    assert expanded["font_policy"]["sha256"] == oc.FONT_SHA256
    assert all(c in expanded["font_policy"]["characters"] for c in "éñΩЖ")
    assert all("supported_characters" not in item and item["font_sha256"] == oc.FONT_SHA256 for item in expanded["items"])
    assert expanded["items"][0]["insertion_eligible"] is True


@pytest.mark.parametrize("value",["café","señor","Ωmega","Журнал"])
def test_expanded_replacement_embeds_actual_new_glyphs_without_changing_original_font(tmp_path,value):
    bundle = expanded_fixture(tmp_path); path = tmp_path/"plan-v2.json"; inv,plan = expanded_plan(bundle,path,value=value)
    originals = {str(p):bind(p)["sha256"] for p in tmp_path.rglob("*") if p.is_file()}
    result = oc.create_derivative(bundle,path,tmp_path/"corrected")
    assert text(result["source_path"])[0].split() == [value,"bad","well"]
    before = oc._scan(bundle/"artifact.pdf",[1])[0]; after = oc._scan(result["source_path"],[1])[0]
    assert before[0]["font"]["sha256"] != after[0]["font"]["sha256"]
    assert before[1]["font"]["sha256"] == after[1]["font"]["sha256"]
    assert oc.validate_lineage(result["lineage_path"],result["source_path"],result["lineage_sha256"])["review_required"]
    assert all(bind(p)["sha256"] == sha for p,sha in originals.items())


@pytest.mark.parametrize("rotation",[0,90,180,270])
@pytest.mark.parametrize("order",["before","after"])
def test_omitted_word_is_real_unicode_with_exact_preview_geometry_order_and_owner(tmp_path,rotation,order):
    bundle = expanded_fixture(tmp_path,rotation=rotation); path = tmp_path/"insert.json"
    anchor = oc.get_inventory(bundle,profile="expanded-v2")["items"][0]
    left,top,width,height = anchor["bbox"]
    rect = [left-.05 if order == "before" else left+width+.01,top,.04,.035]
    inv,plan = expanded_plan(bundle,path,kind="insert",value="café",order=order,rect=rect)
    originalhashes = {str(p):bind(p)["sha256"] for p in tmp_path.rglob("*") if p.is_file()}
    result = oc.create_derivative(bundle,path,tmp_path/"corrected")
    units = oc._scan(result["source_path"],[1],expanded=True)[0]
    assert [u["current"].strip() for u in units] == (["café","bad","bad","well"] if order == "before" else ["bad","café","bad","well"])
    evidence = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["insertions_applied"] == 1 and evidence["structure_ownership_verified"] and evidence["anchor_order_verified"]
    assert all(page["changed_pixel_fraction"] == 0 for page in evidence["fidelity"]["pages"])
    assert oc._raw_structure(bundle/"artifact.pdf") == oc._raw_structure(result["source_path"])
    oc.validate_lineage(result["lineage_path"],result["source_path"],result["lineage_sha256"])
    assert all(bind(p)["sha256"] == sha for p,sha in originalhashes.items())


@pytest.mark.parametrize("value",["مرحبا","漢字","😀","e\u0301","\u200d","two words","\u202eabc"])
def test_expanded_font_rejects_complex_shaping_missing_glyphs_and_control_text(tmp_path,value):
    inv = oc.get_inventory(expanded_fixture(tmp_path),profile="expanded-v2")
    with pytest.raises(oc.OCRCorrectionError): oc.validate_replacement(inv["items"][0],value)


@pytest.mark.parametrize("rect",[[-.1,.2,.1,.1],[.9,.2,.2,.1],[.2,.9,.1,.2],[.2,.2,0,.1],[.2,.2,float("nan"),.1]])
def test_insertion_refuses_invalid_or_off_page_rectangles(tmp_path,rect):
    inv = oc.get_inventory(expanded_fixture(tmp_path),profile="expanded-v2")
    with pytest.raises(oc.OCRCorrectionError): oc.validate_insertion(inv["items"][0],"café",{"order":"after","rect":rect})


def test_insertion_refuses_existing_word_overlap_or_unresolved_tag_owner(tmp_path):
    bundle = expanded_fixture(tmp_path); path = tmp_path/"overlap.json"; inv = oc.get_inventory(bundle,profile="expanded-v2")
    expanded_plan(bundle,path,kind="insert",rect=inv["items"][0]["bbox"])
    with pytest.raises(oc.OCRCorrectionError,match="overlap"): oc.create_derivative(bundle,path,tmp_path/"refused")
    assert not (tmp_path/"refused").exists()
    other = tmp_path/"untagged"; other.mkdir()
    inv = oc.get_inventory(expanded_fixture(other,tagged=False),profile="expanded-v2")
    assert inv["items"][0]["insertion_eligible"] is False


@pytest.mark.parametrize("rotation",[0,90,180,270])
def test_insertion_coordinates_use_cropped_preview_and_quarter_turn(tmp_path,rotation):
    bundle = expanded_fixture(tmp_path,rotation=rotation,crop=True); path = tmp_path/"insert.json"
    anchor = oc.get_inventory(bundle,profile="expanded-v2")["items"][0]
    left,top,width,height = anchor["bbox"]
    expanded_plan(bundle,path,kind="insert",value="café",rect=[left+width+.01,top,.04,.035])
    result = oc.create_derivative(bundle,path,tmp_path/"corrected")
    assert "café" in text(result["source_path"])[0]


def test_insertion_with_ambiguous_upside_down_extraction_order_refuses(tmp_path):
    bundle = expanded_fixture(tmp_path,rotation=180,upright=False); path = tmp_path/"insert.json"
    expanded_plan(bundle,path,kind="insert",order="before")
    with pytest.raises(oc.OCRCorrectionError,match="order|Unicode|separator"):
        oc.create_derivative(bundle,path,tmp_path/"refused")
    assert not (tmp_path/"refused").exists()


@pytest.mark.parametrize("order",["before","after"])
def test_new_encoded_boundaries_preserve_missing_old_separator_and_word_can_be_corrected_later(tmp_path,order):
    bundle = expanded_fixture(tmp_path); artifact = bundle/"artifact.pdf"; prepared = bundle/"prepared.pdf"
    old = oc._scan(artifact,[1])[0][0]
    with pikepdf.open(artifact,allow_overwriting_input=True) as pdf:
        target,_ = oc._leaf(pdf,old); instructions = list(pikepdf.parse_content_stream(target))
        instructions[old["anchor"]["operator"]] = pikepdf.ContentStreamInstruction([pikepdf.String(bytes.fromhex(old["anchor"]["encoded_hex"])[:-2])],pikepdf.Operator("Tj"))
        target.write(pikepdf.unparse_content_stream(instructions)); pdf.save(artifact)
    shutil.copyfile(artifact,prepared); publish_bundle(bundle,tmp_path/"original.pdf",artifact,prepared)
    index = 1 if order == "before" else 0
    anchor = oc.get_inventory(bundle,profile="expanded-v2")["items"][index]; l,t,w,h = anchor["bbox"]
    rect = [l-.05 if order == "before" else l+w+.01,t,.04,.035]
    path = tmp_path/"insert.json"; expanded_plan(bundle,path,kind="insert",order=order,index=index,value="café",rect=rect)
    result = oc.create_derivative(bundle,path,tmp_path/"first")
    units = oc._scan(result["source_path"],[1],expanded=True)[0]; added = next(u for u in units if u["current"] == "café")
    assert added["editable"] and added["anchor"]["leading"] == " " and added["anchor"]["trailing"] == " "
    assert units[0]["anchor"]["trailing"] == ""
    assert text(result["source_path"])[0].split() == ["bad","café","bad","well"]
    later = tmp_path/"later"; later.mkdir(); shutil.copyfile(result["source_path"],later/"artifact.pdf"); shutil.copyfile(result["source_path"],later/"prepared.pdf")
    publish_bundle(later,Path(result["source_path"]),later/"artifact.pdf",later/"prepared.pdf",lineage=Path(result["lineage_path"]))
    inv = oc.get_inventory(later,profile="expanded-v2"); laterindex = next(i for i,item in enumerate(inv["items"]) if item["current"] == "café")
    expanded_plan(later,tmp_path/"replace-later.json",index=laterindex,value="señor")
    followup = oc.create_derivative(later,tmp_path/"replace-later.json",tmp_path/"second")
    assert text(followup["source_path"])[0].split() == ["bad","señor","bad","well"]
    assert oc.validate_lineage(followup["lineage_path"],followup["source_path"],followup["lineage_sha256"])["original"] == bind(tmp_path/"original.pdf")


def reseal_expanded(result):
    lineage = json.loads(Path(result["lineage_path"]).read_text(encoding="utf-8"))
    evidence = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    lineage["current_source"] = bind(result["source_path"]); evidence["after_sha256"] = lineage["current_source"]["sha256"]
    dump(result["evidence_path"],evidence); lineage["evidence"] = bind(result["evidence_path"])
    lineage["binding_sha256"] = digest({k:v for k,v in lineage.items() if k != "binding_sha256"}); dump(result["lineage_path"],lineage)
    return bind(result["lineage_path"])["sha256"]


@pytest.mark.parametrize("tamper",["unicode","glyph","font-name","structure","extra-text"])
def test_resealed_expansion_cannot_hide_wrong_unicode_glyph_font_structure_or_extra_text(tmp_path,tamper):
    bundle = expanded_fixture(tmp_path); path = tmp_path/"insert.json"; expanded_plan(bundle,path,kind="insert",value="café")
    result = oc.create_derivative(bundle,path,tmp_path/"corrected"); source = Path(result["source_path"])
    units = oc._scan(source,[1],expanded=True)[0]; inserted = next(unit for unit in units if unit["current"] == "café")
    with pikepdf.open(source,allow_overwriting_input=True) as pdf:
        leaf,resources = oc._leaf(pdf,inserted); font = resources.Font[inserted["anchor"]["font_name"]]
        if tamper == "unicode": font.ToUnicode.write(font.ToUnicode.read_bytes().replace(b"<00E9> <00E9>",b"<00E9> <0065>"))
        elif tamper == "glyph":
            mapping = font.DescendantFonts[0].CIDToGIDMap; raw = bytearray(mapping.read_bytes()); raw[233*2:233*2+2] = raw[65*2:65*2+2]; mapping.write(bytes(raw))
        elif tamper == "font-name": font.FontName = pikepdf.Name.Wrong; font.DescendantFonts[0].FontDescriptor.FontName = pikepdf.Name.Wrong
        elif tamper == "structure": pdf.Root.StructTreeRoot.K.K[0].S = pikepdf.Name.H1
        else:
            instructions = list(pikepdf.parse_content_stream(leaf)); instructions.insert(inserted["anchor"]["operator"],pikepdf.ContentStreamInstruction([pikepdf.String("extra".encode("utf-16-be"))],pikepdf.Operator("Tj")))
            leaf.write(pikepdf.unparse_content_stream(instructions))
        pdf.save(source)
    fresh = reseal_expanded(result)
    with pytest.raises(oc.OCRCorrectionError): oc.validate_lineage(result["lineage_path"],source,fresh)


@pytest.mark.parametrize("tamper",["literal_insertions_verified","structure_ownership_verified","insertion_geometry_verified","anchor_order_verified","insertions_applied","replacements_applied","font_policy"])
def test_resealed_expanded_evidence_flags_and_counts_cannot_disagree_with_actual_proof(tmp_path,tamper):
    bundle = expanded_fixture(tmp_path); path = tmp_path/"insert.json"; expanded_plan(bundle,path,kind="insert")
    result = oc.create_derivative(bundle,path,tmp_path/"corrected")
    evidence = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8")); evidence[tamper] = False if tamper.endswith("verified") else "wrong"
    dump(result["evidence_path"],evidence); fresh = reseal_expanded(result)
    with pytest.raises(oc.OCRCorrectionError): oc.validate_lineage(result["lineage_path"],result["source_path"],fresh)
    with pytest.raises(oc.OCRCorrectionError): oc.validate_lineage_bindings(result["lineage_path"],result["source_path"],fresh)


def test_expanded_font_cache_still_refuses_changed_program_bytes(tmp_path,monkeypatch):
    qualified = oc._qualified_font(); fake = tmp_path/"program"; (fake/"data").mkdir(parents=True)
    font = fake/"data/NotoSans-Regular.ttf"; font.write_bytes(qualified["raw"]+b"changed")
    monkeypatch.setattr(oc,"__file__",str(fake/"ocr_corrections.py"))
    with pytest.raises(oc.OCRCorrectionError,match="font"): oc._qualified_font()


def test_overlapping_multiple_insertions_and_same_anchor_replacement_refuse(tmp_path):
    bundle = expanded_fixture(tmp_path); path = tmp_path/"insert.json"; inv,plan = expanded_plan(bundle,path,kind="insert")
    original = plan["corrections"][0]; other = dict(original,id="ocr-insert-"+"b"*32,anchor_id=inv["items"][1]["id"],context_sha256=inv["items"][1]["context_sha256"])
    expanded_plan(bundle,path,corrections=[dict(original),other])
    with pytest.raises(oc.OCRCorrectionError,match="overlap"): oc.create_derivative(bundle,path,tmp_path/"overlap")
    replacement = {key:original[key] for key in ("context_sha256","reviewer","reviewed_at")}|{"kind":"replace","id":inv["items"][0]["id"],"original":"bad","value":"café"}
    expanded_plan(bundle,path,corrections=[dict(original),replacement])
    with pytest.raises(oc.OCRCorrectionError,match="different anchors"): oc.create_derivative(bundle,path,tmp_path/"same-anchor")


@pytest.mark.parametrize("row",[None,"bad",7,[]])
def test_malformed_expanded_operations_refuse_before_writing(tmp_path,row):
    bundle = expanded_fixture(tmp_path); path = tmp_path/"plan.json"; inv,plan = expanded_plan(bundle,path)
    plan["corrections"] = [row]; dump(path,plan)
    with pytest.raises(oc.OCRCorrectionError,match="occurrence"): oc.create_derivative(bundle,path,tmp_path/"refused")
    assert not (tmp_path/"refused").exists()


def test_legacy_numeric_tj_refusal_stays_unchanged_while_expanded_restore_is_supported(tmp_path):
    bundle = expanded_fixture(tmp_path); artifact = bundle/"artifact.pdf"; old = oc._scan(artifact,[1])[0][0]
    with pikepdf.open(artifact,allow_overwriting_input=True) as pdf:
        leaf,_ = oc._leaf(pdf,old); instructions = list(pikepdf.parse_content_stream(leaf))
        instructions.insert(old["anchor"]["operator"],pikepdf.ContentStreamInstruction([pikepdf.Array([0])],pikepdf.Operator("TJ")))
        leaf.write(pikepdf.unparse_content_stream(instructions)); pdf.save(artifact)
    shutil.copyfile(artifact,bundle/"prepared.pdf"); publish_bundle(bundle,tmp_path/"original.pdf",artifact,bundle/"prepared.pdf")
    assert not oc.get_inventory(bundle)["eligible"]
    assert oc.get_inventory(bundle,profile="expanded-v2")["eligible"]


def test_accepted_rectangle_cannot_escape_enclosing_form_clipping_bounds(tmp_path):
    bundle = expanded_fixture(tmp_path); artifact = bundle/"artifact.pdf"; old = oc._scan(artifact,[1])[0][0]
    with pikepdf.open(artifact,allow_overwriting_input=True) as pdf:
        leaf,_ = oc._leaf(pdf,old); leaf.BBox = pikepdf.Array([0,0,300,120]); pdf.save(artifact)
    shutil.copyfile(artifact,bundle/"prepared.pdf"); publish_bundle(bundle,tmp_path/"original.pdf",artifact,bundle/"prepared.pdf")
    path = tmp_path/"insert.json"; expanded_plan(bundle,path,kind="insert")
    with pytest.raises(oc.OCRCorrectionError,match="enclosing OCR Form"): oc.create_derivative(bundle,path,tmp_path/"refused")
    assert not (tmp_path/"refused").exists()


def test_expanded_cancellation_during_native_font_fit_cannot_publish(tmp_path,monkeypatch):
    bundle = expanded_fixture(tmp_path); path = tmp_path/"insert.json"; expanded_plan(bundle,path,kind="insert")
    event = threading.Event(); original = oc._independent_ink_bounds
    def measured(*args):
        result = original(*args); event.set(); return result
    monkeypatch.setattr(oc,"_independent_ink_bounds",measured)
    with pytest.raises(Exception,match="cancel"): oc.create_derivative(bundle,path,tmp_path/"refused",cancel=event)
    assert not (tmp_path/"refused").exists()


def test_insertion_last_anchor_generated_space_preserves_exact_encoded_and_owned_old_word(tmp_path):
    bundle = expanded_fixture(tmp_path); artifact = bundle/"artifact.pdf"; old = oc._scan(artifact,[1])[0][-1]
    with pikepdf.open(artifact,allow_overwriting_input=True) as pdf:
        leaf,_ = oc._leaf(pdf,old); instructions = list(pikepdf.parse_content_stream(leaf))
        instructions[old["anchor"]["operator"]] = pikepdf.ContentStreamInstruction([pikepdf.String(bytes.fromhex(old["anchor"]["encoded_hex"])[:-2])],pikepdf.Operator("Tj"))
        leaf.write(pikepdf.unparse_content_stream(instructions)); pdf.save(artifact)
    shutil.copyfile(artifact,bundle/"prepared.pdf"); publish_bundle(bundle,tmp_path/"original.pdf",artifact,bundle/"prepared.pdf")
    inventory = oc.get_inventory(bundle,profile="expanded-v2"); anchor = inventory["items"][-1]; l,t,w,h = anchor["bbox"]
    before = oc._page_objects(artifact)[1]
    assert before["objects"][-1]["text"] == "well"
    path = tmp_path/"insert.json"; expanded_plan(bundle,path,kind="insert",index=2,value="café",rect=[l+w+.01,t,.04,.035])
    result = oc.create_derivative(bundle,path,tmp_path/"corrected"); after = oc._page_objects(result["source_path"])[1]
    assert after["objects"][2]["text"] == "well "  # PDFium's generated boundary view.
    oldunit = oc._scan(artifact,[1],expanded=True)[0][2]; newunit = oc._scan(result["source_path"],[1],expanded=True)[0][2]
    assert oldunit["anchor"]["encoded_hex"] == newunit["anchor"]["encoded_hex"]
    assert [code for owner,code in before["characters"] if owner == 2] == [code for owner,code in after["characters"] if owner == 2]
    assert text(result["source_path"])[0].split() == ["bad","bad","well","café"]
    oc.validate_lineage(result["lineage_path"],result["source_path"],result["lineage_sha256"])
