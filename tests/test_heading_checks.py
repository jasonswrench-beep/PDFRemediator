"""Declared heading-rule boundaries, including generic-H and custom roles."""
import pikepdf
import pytest

from pdf_remediator.heading_checks import assess_headings
from pdf_remediator.inspection import inspect_pdf


def findings(roles, pages=3, errors=None):
    rows = [{"role": role, "page": 1, "element": f"{index}:0"} for index, role in enumerate(roles)]
    return {row["id"]: row for row in assess_headings({"headings": rows, "errors": errors or []}, pages)}


@pytest.mark.parametrize("pages,status", [(1, "not-applicable"), (2, "not-applicable"), (3, "fail"), (4, "fail")])
def test_absent_heading_vendor_page_boundary(pages, status):
    actual = findings([], pages)["marked-headings"]
    assert actual["status"] == status
    assert actual["blocking"] == (status == "fail")
    assert actual["evidence"]["minimum_pages"] == 3
    assert "Apply accepted edits" in actual["fix_path"]


def test_valid_numbered_hierarchy_can_return_to_earlier_levels():
    actual = findings(["/H1", "/H2", "/H3", "/H2", "/H1"])
    assert {row["status"] for row in actual.values()} == {"pass"}


def test_first_heading_and_skipped_levels_are_independent_findings():
    actual = findings(["/H2", "/H4"])
    assert actual["heading-start-level"]["status"] == "fail"
    assert actual["heading-sequence"]["status"] == "fail"
    assert actual["heading-depth"]["status"] == "pass"
    assert actual["heading-sequence"]["evidence"]["skipped_levels"][0]["after"]["role"] == "/H4"


@pytest.mark.parametrize("role", ["/H7", "/H42", "/H0", "/H01", "/H99999999999999999999"])
def test_excessive_or_invalid_numbered_levels_are_detected(role):
    actual = findings(["/H1", role])
    assert actual["heading-depth"]["status"] == "fail"
    assert actual["heading-depth"]["evidence"]["out_of_range"]


def test_generic_heading_never_receives_invented_numbered_pass():
    actual = findings(["/H", "/H2"])
    assert actual["marked-headings"]["status"] == "pass"
    for identifier in ("heading-start-level", "heading-depth", "heading-sequence"):
        assert actual[identifier]["status"] == "needs-review"
        assert actual[identifier]["blocking"] is False


def test_broken_inventory_cannot_prove_absence_or_hierarchy():
    actual = findings([], errors=["RoleMap cycle"])
    assert all(row["status"] == "needs-review" for row in actual.values())


def test_actual_pdf_inventory_includes_custom_roles_resolved_above_six(tmp_path):
    path = tmp_path / "deep-heading.pdf"
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page()
        root = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot))
        root.RoleMap = pikepdf.Dictionary(DeepHeading=pikepdf.Name.H9)
        root.K = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
            S=pikepdf.Name.DeepHeading, P=root, Pg=page.obj))
        pdf.Root.StructTreeRoot = root
        pdf.save(path)
    actual = inspect_pdf(path)
    assert actual["structure"]["headings"][0]["role"] == "/H9"
    assert next(row for row in actual["checks"] if row["id"] == "heading-depth")["status"] == "fail"
