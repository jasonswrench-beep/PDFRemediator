"""Authoritative missing-map closure has narrow evidence and refusal boundaries."""
from pathlib import Path
import importlib.util
import os
import shutil

import pikepdf
import pytest

from pdf_remediator import fonts
from pdf_remediator.inspection import compare_fidelity
from test_pipeline import tagged_control


def fixture(path, existing_mapsto=False):
    """Synthetic text using unchanged, hash-pinned licensed AMS font programs."""
    archive = os.environ.get("PDF_REMEDIATOR_AMSFONTS_ARCHIVE")
    if not archive:
        raise FileNotFoundError("Set PDF_REMEDIATOR_AMSFONTS_ARCHIVE to the reviewed amsfonts.zip; no book or font substitution is used")
    spec = importlib.util.spec_from_file_location("synthetic_type1_control",
        Path(__file__).resolve().parents[1] / "eval/build_type1_control.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder.build_control(path, archive, existing_mapsto=existing_mapsto)


def test_synthetic_type1_control_is_byte_reproducible(tmp_path):
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    fixture(first)
    fixture(second)
    assert first.read_bytes() == second.read_bytes()
    assert (tmp_path / "ams-font-assets/OFL.txt").is_file()


def test_synthetic_control_embeds_unchanged_licensed_programs(tmp_path):
    from fontTools.t1Lib import readPFB

    source = tmp_path / "source.pdf"
    fixture(source)
    with pikepdf.open(source) as pdf:
        for key, name in (("SY", "cmsy10"), ("EX", "cmex10")):
            font = pdf.pages[0].Resources.Font["/" + key]
            assert font.FontDescriptor.FontFile.read_bytes() == readPFB(tmp_path / "ams-font-assets" / (name + ".pfb"))
            assert "/Encoding" not in font  # retain the actual built-in encoding


def test_changed_font_archive_is_refused_without_pdf_or_asset_outputs(tmp_path, monkeypatch):
    archive = os.environ.get("PDF_REMEDIATOR_AMSFONTS_ARCHIVE")
    if not archive:
        raise FileNotFoundError("PDF_REMEDIATOR_AMSFONTS_ARCHIVE is required")
    changed = tmp_path / "changed.zip"
    changed.write_bytes(Path(archive).read_bytes() + b"tampered archive")
    monkeypatch.setenv("PDF_REMEDIATOR_AMSFONTS_ARCHIVE", str(changed))
    source = tmp_path / "source.pdf"
    with pytest.raises(ValueError, match="integrity mismatch"):
        fixture(source)
    assert not source.exists() and not (tmp_path / "ams-font-assets").exists()


def test_official_mapping_data_is_hash_pinned_and_exact():
    entries = fonts._authority()
    assert entries["mapsto"]["utf16be_hex"] == "21A6"
    assert entries["radicalBig"]["utf16be_hex"] == "221AFE02"
    assert entries["mapsto"]["source_line"] == 113
    assert entries["radicalBig"]["source_line"] == 130
    assert "LPPL" in fonts.AUTHORITY["license"]


def test_tampered_authority_file_is_refused(tmp_path, monkeypatch):
    changed = tmp_path / "authority.tex"
    changed.write_bytes(fonts.DATA.read_bytes().replace(b"{mapsto}{21A6}", b"{mapsto}{0037}"))
    monkeypatch.setattr(fonts, "DATA", changed)
    with pytest.raises(fonts.Refused):
        fonts._authority()


def test_exact_two_glyph_correction_preserves_all_other_text_and_pixels(tmp_path):
    original, processed = tmp_path / "source.pdf", tmp_path / "tagged.pdf"
    fixture(original)
    shutil.copyfile(original, processed)
    destination, reference = tmp_path / "fixed.pdf", tmp_path / "reference.pdf"
    result = fonts.repair_source_mappings(original, processed, destination, reference)
    assert result["status"] == "pass", result.get("reason")
    assert {(item["code"], item["glyph_name"]) for item in result["changes"]} == {(55, "mapsto"), (113, "radicalBig")}
    assert len(result["authoritative_corrections"]) == 2
    assert result["expected_text"]["all_other_extracted_characters_unchanged"] is True
    assert result["reference_appearance"]["status"] == "pass"
    assert result["source_reference_fidelity"]["text"]["multiset_status"] == "fail"
    assert compare_fidelity(reference, destination)["status"] == "pass"
    assert result["human_review_pending"]


def test_existing_unicode_mapping_is_never_replaced_even_when_questionable(tmp_path):
    original, processed = tmp_path / "source.pdf", tmp_path / "tagged.pdf"
    fixture(original, existing_mapsto=True)
    shutil.copyfile(original, processed)
    result = fonts.repair_source_mappings(original, processed, tmp_path / "fixed.pdf", tmp_path / "reference.pdf")
    assert result["status"] == "pass", result.get("reason")
    assert [change["glyph_name"] for change in result["changes"]] == ["radicalBig"]
    with pikepdf.open(tmp_path / "fixed.pdf") as pdf:
        assert fonts._cmap_entries(pdf.pages[0].Resources.Font.SY.ToUnicode.read_bytes())[55] == bytes.fromhex("0037")


def test_modified_processed_program_or_mapping_is_refused_without_outputs(tmp_path):
    original, processed = tmp_path / "source.pdf", tmp_path / "tagged.pdf"
    fixture(original)
    with pikepdf.open(original) as pdf:
        # An engine replacing an existing valid mapping breaks source lineage.
        font = pdf.pages[0].Resources.Font.SY
        font.ToUnicode = pikepdf.Stream(pdf, font.ToUnicode.read_bytes().replace(b"<00> <2212>", b"<00> <0041>"))
        pdf.save(processed)
    destination, reference = tmp_path / "fixed.pdf", tmp_path / "reference.pdf"
    result = fonts.repair_source_mappings(original, processed, destination, reference)
    assert result["status"] == "refused"
    assert "differs" in result["reason"]
    assert not destination.exists() and not reference.exists()
    assert not list(tmp_path.glob("*.mapping-partial"))


def test_unsupported_encoding_override_is_not_guessed(tmp_path):
    original, processed = tmp_path / "source.pdf", tmp_path / "tagged.pdf"
    fixture(original)
    with pikepdf.open(original) as pdf:
        font = pdf.pages[0].Resources.Font.SY
        font.Encoding = pikepdf.Dictionary(Differences=pikepdf.Array([55, pikepdf.Name.customglyph]))
        pdf.save(processed)
    result = fonts.repair_source_mappings(original, processed, tmp_path / "fixed.pdf", tmp_path / "reference.pdf")
    assert result["status"] == "refused"


def test_no_applicable_map_makes_byte_identical_copies(tmp_path, tagged_control):
    source = tagged_control
    processed = tmp_path / "processed.pdf"
    shutil.copyfile(source, processed)
    output, reference = tmp_path / "output.pdf", tmp_path / "reference.pdf"
    result = fonts.repair_source_mappings(source, processed, output, reference)
    assert result["status"] == "pass"
    assert result["changes"] == []
    assert source.read_bytes() == reference.read_bytes()
    assert processed.read_bytes() == output.read_bytes()


def test_cmap_parser_refuses_ambiguous_and_inherited_mappings():
    base = b"begincmap\n1 begincodespacerange\n<00> <FF>\nendcodespacerange\n1 beginbfchar\n<00> <2212>\nendbfchar\nendcmap"
    assert fonts._cmap_entries(base) == {0: bytes.fromhex("2212")}
    for value in (base.replace(b"endcmap", b"/Other usecmap\nendcmap"),
                  base.replace(b"1 beginbfchar", b"2 beginbfchar").replace(b"endbfchar", b"<00> <0041>\nendbfchar"),
                  base.replace(b"<00> <FF>", b"<0000> <FFFF>")):
        with pytest.raises(fonts.Refused):
            fonts._cmap_entries(value)


def test_existing_destination_never_overwritten(tmp_path):
    output = tmp_path / "existing.pdf"
    output.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        fonts.repair_source_mappings(tmp_path / "absent-source.pdf", tmp_path / "absent-processed.pdf", output, tmp_path / "reference.pdf")
    assert output.read_bytes() == b"preserve"
