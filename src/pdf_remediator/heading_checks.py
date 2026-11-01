"""Mechanical heading findings; semantic heading selection remains reviewed."""
from __future__ import annotations

import re

PROFILE = "pdf-heading-structure-1"
FIX = ("Open Document edits and show structure repairs for the affected page. "
       "Choose the existing text element's correct heading level, accept it with "
       "your reviewer name, then Apply accepted edits. If no suitable tagged text "
       "element exists, repair the source document and process a separate PDF.")


def assess_headings(structure, page_count):
    """Check declared heading roles in structure order, without inferring meaning.

    Generic H headings can encode hierarchy through section nesting. They do not
    acquire an invented numbered level here. Unknown numeric coverage is exposed
    as needs-review, while detected mechanical defects block candidacy.
    """
    headings = structure.get("headings", [])
    unreliable = bool(structure.get("errors"))
    numbered, generic, invalid = [], [], []
    for index, item in enumerate(headings):
        role = str(item.get("role", ""))
        digits = re.fullmatch(r"/H([0-9]+)", role)
        row = {"index": index, "element": item.get("element"),
               "page": item.get("page"), "role": role}
        if digits and len(digits[1]) <= 6:
            row["level"] = int(digits[1])
            numbered.append(row)
            if row["level"] < 1 or digits[1].startswith("0"):
                invalid.append(row)
        elif digits:
            row["level"] = None
            invalid.append(row)
        else:
            generic.append(row)
    evidence = {"profile": PROFILE, "heading_count": len(headings),
                "numbered_headings": numbered, "generic_headings": generic,
                "inventory_errors": structure.get("errors", [])}

    def entry(identifier, status, detail):
        return {"id": identifier, "status": status,
                "blocking": status in {"fail", "error"}, "evidence": {**evidence, **detail},
                "scope": "Declared PDF structure roles in structure-tree order",
                "limitations": ["Heading purpose and semantic hierarchy require human review.",
                    "Generic H nesting is not converted to invented numbered levels."],
                "fix_path": FIX}

    absent_status = "needs-review" if unreliable else "fail" if not headings and page_count >= 3 else "pass" if headings else "not-applicable"
    results = [entry("marked-headings", absent_status,
                     {"page_count": page_count, "minimum_pages": 3,
                      "description": "PDFs of at least three pages need marked headings."})]
    if not headings:
        status = "needs-review" if unreliable else "not-applicable"
        return results + [entry(identifier, status, {}) for identifier in
                          ("heading-start-level", "heading-depth", "heading-sequence")]
    first = next((row for row in numbered + generic if row["index"] == 0), None)
    start = "needs-review" if unreliable or not first or first.get("level") is None else "pass" if first["level"] == 1 else "fail"
    results.append(entry("heading-start-level", start, {"first_heading": first}))
    deep = [row for row in numbered if row["level"] > 6] + invalid
    depth = "fail" if deep else "needs-review" if unreliable or generic else "pass"
    results.append(entry("heading-depth", depth, {"out_of_range": deep, "maximum_level": 6}))
    jumps, previous = [], None
    numeric_by_index = {row["index"]: row for row in numbered}
    for index in range(len(headings)):
        current = numeric_by_index.get(index)
        if current and previous and current["level"] > previous["level"] + 1:
            jumps.append({"before": previous, "after": current})
        previous = current
    sequence = "fail" if jumps else "needs-review" if unreliable or generic or invalid else "pass"
    results.append(entry("heading-sequence", sequence, {"skipped_levels": jumps}))
    return results
