"""A standalone, escaped, script-free review packet for local human review."""
from __future__ import annotations

import base64
from html import escape
import json
from pathlib import Path


def _text(value):
    return escape("" if value is None else str(value), quote=True)


def _json(value):
    return _text(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _details(title, value):
    return f"<details><summary>{_text(title)}</summary><pre>{_json(value)}</pre></details>"


def _items(items, empty):
    if not items:
        return f"<p>{_text(empty)}</p>"
    parts = ["<ul>"]
    for item in items:
        if isinstance(item, dict):
            label = item.get("description", item.get("subject", item.get("message", item.get("id", "Review item"))))
            page = f"; page {item['page']}" if item.get("page") is not None else ""
            if not page and item.get("pages"):
                page = "; pages " + ", ".join(str(number) for number in item["pages"])
            state = item.get("status", "pending")
            parts.append(f"<li><strong>{_text(label)}</strong>{_text(page)} — {_text(state)}")
            if item.get("detail"):
                parts.append(f"<p>{_text(item['detail'])}</p>")
            if item.get("fix_path"):
                parts.append(f"<p>Next step: {_text(item['fix_path'])}</p>")
            parts.append(_details("Item evidence", item) + "</li>")
        else:
            parts.append(f"<li>{_text(item)}</li>")
    parts.append("</ul>")
    return "".join(parts)


def _thumbnails(thumbnails):
    if not thumbnails:
        return ""
    if isinstance(thumbnails, dict):
        thumbnails = [{"page": page, "path": path} for page, path in thumbnails.items()]
    figures = []
    for entry in thumbnails:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        path = Path(entry["path"])
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            continue
        raw = path.read_bytes()
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif raw.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        else:
            # SVG/HTML and remote images are never embedded into this packet.
            continue
        label = f"Page {entry.get('page', '?')} visual reference"
        encoded = base64.b64encode(raw).decode("ascii")
        figures.append(f'<figure><img src="data:{mime};base64,{encoded}" alt="{_text(label)}">'
                       f'<figcaption>{_text(label)}. This thumbnail does not establish semantic accessibility.</figcaption></figure>')
    if not figures:
        return ""
    return '<section aria-labelledby="visuals"><h2 id="visuals">Visual references</h2>' + "".join(figures) + "</section>"


def render_review_packet(report, sidecar, output_path, thumbnails=None):
    """Render evidence without executing document content or fetching assets.

    The editable sidecar is a separate JSON/YAML artifact. This packet cannot
    submit approvals: a person records them through the local review command.
    """
    if not isinstance(report, dict) or not isinstance(sidecar, dict):
        raise ValueError("Report and sidecar must be mappings")
    manual = report.get("manual_review", {})
    queue = manual.get("items", []) if isinstance(manual, dict) else []
    gate2 = report.get("gate2", {})
    if not queue and isinstance(gate2, dict):
        queue = gate2.get("manual_queue", [])
    pending = [item for item in queue if not isinstance(item, dict) or item.get("status") != "approved"]
    blockers = gate2.get("blockers", []) if isinstance(gate2, dict) else []
    combined = list(blockers) + list(report.get("residual_issues", []))
    by_id = {}
    for index, item in enumerate(combined):
        by_id[item.get("id", str(index)) if isinstance(item, dict) else str(index)] = item
    blockers = list(by_id.values())
    rows = []
    for item in sidecar.get("decisions", []):
        if not isinstance(item, dict):
            continue
        rows.append("<tr>" + "".join(f"<td>{_text(item.get(key, ''))}</td>" for key in
                                    ("id", "kind", "page", "current", "value", "status")) + "</tr>")
    assessments = []
    for key, label in (("gate1", "Strict PDF/UA-1 validator"),
                       ("gate2", "Supplemental automated checks"),
                       ("fidelity", "All-page preservation assessment")):
        assessment = report.get(key, {})
        state = assessment.get("status", "not-tested") if isinstance(assessment, dict) else "not-tested"
        assessments.append(f"<section><h3>{_text(label)}: {_text(state)}</h3>" +
                           _details("Assessment details and coverage", assessment) + "</section>")
    output = report.get("output") or {}
    source = report.get("input") or {}
    title = "PDF Remediator — local review packet"
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-src 'none'">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>
<style>
body{{font:1rem/1.6 system-ui,Segoe UI,sans-serif;color:#192b36;background:#fff;max-width:76rem;margin:auto;padding:1.5rem}}
a{{color:#064f89}}a:focus,summary:focus{{outline:3px solid #995100;outline-offset:3px}}h1,h2,h3{{line-height:1.25}}
section{{margin-block:1.8rem}}.status{{font-weight:700;border:2px solid #344e60;padding:.8rem}}code,pre{{font-family:Consolas,monospace}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3f6;padding:1rem}}.table-wrap{{overflow:auto}}
table{{border-collapse:collapse;width:100%}}caption{{text-align:left;font-weight:bold;margin:.5rem 0}}th,td{{border:1px solid #667b89;padding:.5rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#e5edf2}}
summary{{cursor:pointer;font-weight:600}}details{{margin:.7rem 0}}img{{max-width:100%;height:auto;border:1px solid #667b89}}figure{{max-width:38rem;margin:1.5rem 0}}
@media print{{body{{max-width:none}}details{{display:block}}pre{{font-size:.75rem}}}}
</style></head><body><a href="#review-queue">Skip to pending human review</a>
<header><h1>{title}</h1><p class="status">Run status: {_text(report.get('status', 'unknown'))}</p>
<p>Automated candidacy, human review, and an actual LMS checker score are separate records. A candidate still needs the human checks below. This packet does not certify accessibility.</p></header>
<main><section aria-labelledby="binding"><h2 id="binding">Exact document under review</h2>
<p>Source: {_text(source.get('path', ''))}<br>Source SHA-256: <code>{_text(source.get('sha256', sidecar.get('source_sha256', '')))}</code></p>
<p>Output: {_text(output.get('path', 'No releasable PDF'))}<br>Output SHA-256: <code>{_text(output.get('sha256', 'Not published'))}</code></p>
<p>Changing the PDF invalidates previous approvals and verification for those bytes.</p></section>
<section aria-labelledby="blockers"><h2 id="blockers">Blockers and repair paths</h2>{_items(blockers, 'No blockers are recorded in this report.')}</section>
<section aria-labelledby="review-queue"><h2 id="review-queue">Pending human review ({len(pending)})</h2>
{_items(pending, 'No pending items are listed. Verification still requires an eligible candidate, a named reviewer, review scope, and the actual LMS checker score.')}
{_details('All human-review items, including completed checks', queue)}</section>
<section aria-labelledby="decisions"><h2 id="decisions">Explicit reviewer decisions</h2>
<p>Edit the separate decision sidecar and explicitly approve each selected value through the local review command. Existing text is retained by default. Changed values, source fingerprints, staged document fingerprints, or occurrence context invalidate prior approval.</p>
<p>Figure descriptions apply to the listed structure element and page occurrence. The same image used under a different caption has a separate decision. Heading purpose, table relationships, and reading order require human assessment.</p>
<div class="table-wrap"><table><caption>Metadata, image and reviewed structure edits</caption><thead><tr><th scope="col">Decision ID</th><th scope="col">Kind</th><th scope="col">Page</th><th scope="col">Existing value</th><th scope="col">Proposed value</th><th scope="col">Approval</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{_details('Decision bindings and approval fingerprints', sidecar)}</section>
<section aria-labelledby="assessments"><h2 id="assessments">Automated evidence</h2>{''.join(assessments)}</section>
{_thumbnails(thumbnails)}
<section aria-labelledby="privacy"><h2 id="privacy">Processing and data use</h2>{_details('Data-sending record', report.get('data_sent', {}))}{_details('Selected and skipped processors', report.get('processors', []))}</section>
{_details('Complete machine-readable run report', report)}
</main><footer><p>Local, script-free review packet. All document-derived text is escaped. No external assets or document scripts are loaded.</p></footer></body></html>
'''
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
