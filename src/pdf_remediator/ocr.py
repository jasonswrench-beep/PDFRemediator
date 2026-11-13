"""Local OCR with bounded processes and all-page preservation gates."""
from pathlib import Path
import json
import math
import os
import re
import shutil
import uuid

import pikepdf

from .doctor import OCR_VERSION, ocr_availability, option, resolve_tools, sha
from .inspection import compare_fidelity, inspect_pdf
from .ocr_angle_evidence import ENV_KEYS as ANGLE_ENV_KEYS, FONT_SHA256, runtime_font, validate_pages as validate_angle_pages
from . import ocr_confidence
from .ocr_pages import PageSelectionRefusal, check_textless_coverage, select_textless_pages
from .ocr_turns import ENV_KEYS as TURN_ENV_KEYS, validate_pages as validate_turn_pages
from .process import local_environment, run


def _ocr_preservation(fidelity, expected_pages=None):
    """Permit added OCR tokens, while retaining every original digital token."""
    if fidelity.get("error"):
        return {"status": "error", "error": fidelity["error"]}
    pages = fidelity.get("pages", [])
    complete_pages = expected_pages is None or (len(pages) == expected_pages and
        [page.get("page") for page in pages] == list(range(1, expected_pages + 1)))
    valid_pages = bool(pages) and complete_pages and all(
        all(p.get(k) == "pass" for k in ("render_status", "dimensions_status", "page_boxes_status", "annotations_status"))
        and p.get("text", {}).get("removed_tokens", 1) == 0 for p in pages)
    other = [check for check in fidelity.get("checks", []) if check.get("id", check.get("name")) != "all-page-render-and-content"]
    valid_other = all(check["status"] in ("pass", "not-applicable") for check in other)
    return {"status": "pass" if valid_pages and valid_other else "fail", "all_pages_compared": len(pages), "expected_pages": expected_pages,
            "policy": "OCR may add selectable tokens; zero removed original tokens and exact visible preservation required.",
            "added_tokens": sum(p.get("text", {}).get("added_tokens", 0) for p in pages),
            "accuracy": "needs-review", "completeness": "needs-review", "reading_order": "needs-review"}


def _require_table_preprocessing_shape(proof):
    """Validate the fixed hook's complete mechanical proof, not table meaning."""
    from .ocr_table_lines import PROFILE_VERSION, MAX_PIXELS, MAX_LINES, MAX_GRIDS

    def number(value):
        if type(value) not in (int, float):
            return False
        try:
            return math.isfinite(value)
        except OverflowError:
            return False

    def box(value, width, height):
        return (isinstance(value, list) and len(value) == 4 and all(type(v) is int for v in value)
                and 0 <= value[0] < value[2] <= width and 0 <= value[1] < value[3] <= height)

    def union_area(boxes):
        # At most 128 line rectangles or 12 grid rectangles; no raster allocation.
        boundaries = sorted({value for item in boxes for value in (item[0], item[2])})
        area = 0
        for left, right in zip(boundaries, boundaries[1:]):
            intervals = sorted((item[1], item[3]) for item in boxes if item[0] <= left < item[2])
            end, span = 0, 0
            for top, bottom in intervals:
                span += max(0, bottom - max(top, end))
                end = max(end, bottom)
            area += (right - left) * span
        return area

    required = {'profile_version', 'image_size', 'dpi', 'input_RGB_pixels_sha256', 'output_RGB_pixels_sha256',
                'grids', 'horizontal_candidates', 'vertical_candidates', 'ruling_mask_fraction',
                'changed_recognition_fraction', 'changed_recognition_bbox', 'header_pixels',
                'header_normalized', 'header_dominant_luma', 'status'}
    valid = isinstance(proof, dict) and required <= proof.keys() and proof.get('profile_version') == PROFILE_VERSION
    size = proof.get('image_size') if valid else None
    valid = (valid and isinstance(size, list) and len(size) == 2
             and all(type(v) is int and v > 0 for v in size) and size[0] * size[1] <= MAX_PIXELS)
    if not valid:
        raise ValueError('Ruled-table OCR preprocessing evidence has invalid version or image geometry.')
    width, height = size
    pixels = width * height
    dpi = proof.get('dpi')
    hashes = [proof.get(name) for name in ('input_RGB_pixels_sha256', 'output_RGB_pixels_sha256')]
    grids = proof.get('grids')
    candidates = [proof.get(name) for name in ('horizontal_candidates', 'vertical_candidates')]
    ruling, changed = proof.get('ruling_mask_fraction'), proof.get('changed_recognition_fraction')
    changed_box = proof.get('changed_recognition_bbox')
    header_pixels, normalized, dominant = (proof.get(name) for name in ('header_pixels', 'header_normalized', 'header_dominant_luma'))
    valid = (number(dpi) and 50 <= dpi <= 1200
             and all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) for value in hashes)
             and isinstance(grids, list) and len(grids) <= MAX_GRIDS
             and all(type(value) is int and value >= 0 for value in candidates) and sum(candidates) <= MAX_LINES
             and number(ruling) and 0 <= ruling <= .05 and number(changed) and 0 <= changed <= .12
             and (changed_box is None if changed == 0 else box(changed_box, width, height))
             and (hashes[0] == hashes[1] if changed == 0 else hashes[0] != hashes[1])
             and type(header_pixels) is int and 0 <= header_pixels <= min(2_000_000, pixels * .15) and type(normalized) is bool
             and (dominant is None or type(dominant) is int and 0 <= dominant < 240)
             and (dominant is not None if header_pixels else not normalized and dominant in (None, 0))
             and (not normalized or header_pixels > 0 and dominant is not None and dominant < 180))
    if not valid:
        raise ValueError('Ruled-table OCR preprocessing evidence has invalid raster hashes, measurements or bounds.')
    line_counts, all_lines, grid_boxes = [0, 0], [], []
    thickness = max(5, min(16, round(dpi * .04))) + 2
    for grid in grids:
        if not isinstance(grid, dict) or not box(grid.get('bounds'), width, height):
            raise ValueError('Ruled-table OCR preprocessing evidence has invalid grid bounds.')
        boxes = []
        for index, axis in enumerate(('horizontal', 'vertical')):
            lines = grid.get(axis)
            if not isinstance(lines, list) or not 3 <= len(lines) <= MAX_LINES or not all(box(value, width, height) for value in lines):
                raise ValueError('Ruled-table OCR preprocessing evidence has invalid ruling segments.')
            if any((value[3] - value[1] > thickness or value[2] - value[0] <= value[3] - value[1]) if index == 0
                   else (value[2] - value[0] > thickness or value[3] - value[1] <= value[2] - value[0]) for value in lines):
                raise ValueError('Ruled-table OCR preprocessing evidence has invalid ruling-axis geometry.')
            line_counts[index] += len(lines)
            boxes.extend(lines)
        envelope = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
        if grid['bounds'] != envelope or envelope[2] - envelope[0] < width * .2:
            raise ValueError('Ruled-table OCR preprocessing evidence grid does not bound its partial ruling segments.')
        all_lines.extend(boxes)
        grid_boxes.append(envelope)
    if any(total > count for total, count in zip(line_counts, candidates)):
        raise ValueError('Ruled-table OCR preprocessing evidence has inconsistent candidate counts.')
    ruling_pixels, changed_pixels = round(ruling * pixels), round(changed * pixels)
    if (not math.isclose(ruling * pixels, ruling_pixels, rel_tol=0, abs_tol=1e-6)
            or not math.isclose(changed * pixels, changed_pixels, rel_tol=0, abs_tol=1e-6)
            or ruling_pixels != union_area(all_lines) or header_pixels > union_area(grid_boxes)
            or changed_pixels > ruling_pixels + (header_pixels if normalized else 0)):
        raise ValueError('Ruled-table OCR preprocessing evidence has inconsistent pixel measurements.')
    if changed_box is not None:
        envelope = [min(item[0] for item in grid_boxes), min(item[1] for item in grid_boxes),
                    max(item[2] for item in grid_boxes), max(item[3] for item in grid_boxes)] if grid_boxes else None
        if (envelope is None or not (envelope[0] <= changed_box[0] < changed_box[2] <= envelope[2]
                and envelope[1] <= changed_box[1] < changed_box[3] <= envelope[3])
                or changed_pixels > (changed_box[2] - changed_box[0]) * (changed_box[3] - changed_box[1])):
            raise ValueError('Ruled-table OCR preprocessing evidence has an inconsistent changed-region bound.')
    if not grids:
        if (proof.get('status') != 'no-grid' or ruling != 0 or changed != 0 or header_pixels != 0
                or normalized or dominant is not None):
            raise ValueError('Ruled-table OCR preprocessing evidence has inconsistent no-grid measurements.')
    elif proof.get('status') != 'filtered' or ruling_pixels == 0 or changed_pixels == 0:
        raise ValueError('Ruled-table OCR preprocessing evidence has inconsistent filtered-grid status.')


OVERSAMPLE_DPI = 300
OVERSAMPLE_BELOW_DPI = 250
OVERSAMPLE_MAX_MPIXELS = 64


def oversample_plan(source, pages):
    """Decide whether recognition should read an enlarged picture of low-resolution pages.

    Text recognition reads small page pictures badly (an 80 dpi scan read about half right; at 300 dpi, about 85% right). The page
    itself is never changed: only the picture handed to recognition is enlarged, and only when a page picture is estimated to be
    under 250 dpi. A page that would need more than 64 megapixels at 300 dpi is left alone, so a poster-sized page cannot exhaust memory.
    """
    plan = {'dpi': None, 'target_dpi': OVERSAMPLE_DPI, 'lowest_estimated_dpi': None, 'pages_below': [], 'reason': 'No page picture is below %d dpi.' % OVERSAMPLE_BELOW_DPI}
    largest = 0.0
    try:
        with pikepdf.open(source) as pdf:
            for number in pages:
                page = pdf.pages[number - 1]
                box = [float(value) for value in page.mediabox]
                width, height = abs(box[2] - box[0]) / 72.0, abs(box[3] - box[1]) / 72.0
                if width <= 0 or height <= 0:
                    continue
                largest = max(largest, width * height * OVERSAMPLE_DPI ** 2 / 1e6)
                resources = page.resources
                xobjects = resources.get('/XObject') if resources is not None else None
                estimate = 0.0
                for name in (xobjects.keys() if xobjects is not None else []):
                    item = xobjects[name]
                    if isinstance(item, pikepdf.Stream) and str(item.get('/Subtype', '')) == '/Image':
                        estimate = max(estimate, max(int(item.get('/Width', 0)), int(item.get('/Height', 0))) / max(width, height))
                if not estimate:
                    continue
                if plan['lowest_estimated_dpi'] is None or estimate < plan['lowest_estimated_dpi']:
                    plan['lowest_estimated_dpi'] = round(estimate)
                if estimate < OVERSAMPLE_BELOW_DPI:
                    plan['pages_below'].append(number)
    except (pikepdf.PdfError, ValueError, TypeError, IndexError, KeyError, OverflowError, OSError) as error:
        plan['reason'] = 'Page picture resolution could not be estimated (%s); pictures were read as they are.' % type(error).__name__
        return plan
    if not plan['pages_below']:
        return plan
    if largest > OVERSAMPLE_MAX_MPIXELS:
        plan['reason'] = 'A page would need %d megapixels at %d dpi, so low-resolution pictures were read as they are.' % (round(largest), OVERSAMPLE_DPI)
        return plan
    plan['dpi'] = OVERSAMPLE_DPI
    plan['reason'] = 'Low-resolution page pictures (pages %s) were enlarged to %d dpi for recognition only.' % (', '.join(str(n) for n in plan['pages_below'][:12]) + (' and more' if len(plan['pages_below']) > 12 else ''), OVERSAMPLE_DPI)
    return plan


def _reading_confidence(profile, required_pages, page_count, source_sha256, directory=None, binding=None, turn_pages=None):
    """How surely each page was read, from the numbers the recognition run left. Advisory: it never fails the reading."""
    if profile == 'angles':
        return {'status': 'not-measured', 'layout': profile, 'policy': ocr_confidence.POLICY, 'pages': [], 'flagged_pages': [], 'not_measured_pages': [],
                'reason': 'The tilted and vertical text layout does not report word confidence, so no page was singled out.'}
    problems = []
    try:
        if profile == 'turns':
            wanted = set(required_pages)
            measured = [{'page': p['page'], 'reading': p['reading']} for p in turn_pages or []
                        if p.get('page') in wanted and ocr_confidence.valid_reading(p.get('reading'))]
        else:
            checked = ocr_confidence.validate_pages(directory, required_pages, binding, source_sha256, page_count)
            measured, problems = checked['pages'], checked['problems']
    except Exception as error:
        measured, problems = [], ['Reading confidence could not be read (%s).' % type(error).__name__]
    summary = ocr_confidence.summarise(measured, required_pages, profile)
    if problems:
        summary['problems'] = problems[:20]
    return summary


def run_ocr(input, output, settings=None, workdir=None, mode="skip", cancel=None):
    source, destination = Path(input).resolve(), Path(output).resolve()
    if mode not in ("skip", "redo", "textless"):
        raise ValueError("Only the measured skip, redo and textless-page routes are supported; force OCR is unavailable")
    if source == destination or destination.exists():
        raise FileExistsError("OCR requires a distinct new output")
    profile = option(settings, "ocr_profile", "standard")
    if profile not in ("standard", "table-lines", "angles", "turns"):
        return {"status": "unsupported", "ocr_profile": profile, "error": "Choose a supported OCR scan layout."}
    if profile == 'angles' and mode not in ('skip', 'textless'):
        return {'status': 'unsupported', 'ocr_profile': profile, 'mode': mode,
                'error': 'Tilted and vertical text recognition supports only skip or wholly scanned pages; redo is unproven.'}
    if profile == 'turns' and mode not in ('skip', 'textless'):
        return {'status': 'unsupported', 'ocr_profile': profile, 'mode': mode,
                'error': 'Sideways and upside-down page recognition supports only skip or wholly scanned pages; redo is unproven.'}
    plugin = Path(__file__).resolve().with_name('ocr_table_plugin.py')
    algorithm = plugin.with_name('ocr_table_lines.py')
    if profile == 'table-lines' and not all(path.is_file() for path in (plugin, algorithm)):
        return {"status": "unsupported", "ocr_profile": profile, "error": "The ruled-table OCR profile is not installed in this copy."}
    table_binding = {'plugin_sha256': sha(plugin), 'algorithm_sha256': sha(algorithm)} if profile == 'table-lines' else None
    angle_paths = {key: Path(__file__).resolve().with_name(name) for key, name in (
        ('plugin_sha256', 'ocr_angle_plugin.py'), ('algorithm_sha256', 'ocr_angles.py'), ('regions_sha256', 'ocr_regions.py'),
        ('evidence_sha256', 'ocr_angle_evidence.py'), ('rescue_sha256', 'ocr_rescue.py'))}
    if profile == 'angles' and not all(path.is_file() for path in angle_paths.values()):
        return {'status': 'unsupported', 'ocr_profile': profile, 'error': 'The tilted and vertical OCR profile is not installed in this copy.'}
    angle_binding = {key: sha(path) for key, path in angle_paths.items()} if profile == 'angles' else None
    turn_paths = {key: Path(__file__).resolve().with_name(name) for key, name in (
        ('plugin_sha256', 'ocr_turn_plugin.py'), ('algorithm_sha256', 'ocr_turns.py'))}
    if profile == 'turns' and not all(path.is_file() for path in turn_paths.values()):
        return {'status': 'unsupported', 'ocr_profile': profile, 'error': 'The sideways and upside-down page profile is not installed in this copy.'}
    turn_binding = {key: sha(path) for key, path in turn_paths.items()} if profile == 'turns' else None
    availability = ocr_availability(settings)
    if not availability["available"]:
        return {"status": "unsupported", "ocr_profile": profile, "error": availability["message"], "availability": availability}
    language = option(settings, "ocr_language", "eng")
    if language != "eng":
        return {"status": "unsupported", "ocr_profile": profile, "error": "Only the locally tested English OCR model is supported"}
    before = inspect_pdf(source, cancel=cancel)
    if before.get("error"):
        return {"status": "error", "ocr_profile": profile, "error": before["error"]}
    features = before.get("features", {})
    if any(features.get(key) for key in ("encrypted", "signed_or_signature_fields", "forms", "attachments", "javascript", "optional_content")):
        return {"status": "unsupported", "ocr_profile": profile, "error": "OCR refuses unsupported input features"}
    image_pages = [p for p in before["pages"] if p["class"] in ("mixed", "scanned")]
    # Multiple image pages share the same bounded single-worker route; every
    # original page must pass the exact visible/zero-removed-token check below.
    if mode == "skip" and any(p["class"] == "mixed" for p in image_pages):
        return {"status": "unsupported", "ocr_profile": profile, "error": "Skip mode omits scanned text on mixed pages; explicitly select redo after review"}
    if mode == "redo" and before.get("structure", {}).get("present"):
        return {"status": "unsupported", "ocr_profile": profile, "error": "Redo on existing tags was not proven to preserve structure; use source-document/manual repair"}
    selection, native_mode = None, mode
    if mode == 'textless':
        native_mode = 'skip'
        try:
            selection = select_textless_pages(before)
        except PageSelectionRefusal as error:
            return {'status': 'unsupported', 'ocr_profile': profile, 'mode': mode, 'requested_mode': mode,
                    'native_mode': native_mode, 'error': str(error)}
    tools = resolve_tools(settings=settings)
    font = runtime_font(tools['ocr_python']) if profile == 'angles' else None
    if font is not None and (not font.is_file() or sha(font) != FONT_SHA256):
        return {'status': 'unsupported', 'ocr_profile': profile, 'mode': mode,
                'error': 'Tilted and vertical OCR requires the qualified font in the selected private OCR runtime.'}
    directory = Path(workdir or destination.parent / "ocr").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    # Native OCR helpers can reject deeply nested Windows temporary paths.
    # Keep each unique temporary root short and retain its path as evidence. It lives under output/review-app, so deleting the
    # saved work also deletes it, and it is removed after every run, finished, failed or cancelled (rendered page images of the
    # person's document can be in it).
    temporary = tools['project_root'] / 'output' / 'review-app' / 'tmp' / 'ocr' / uuid.uuid4().hex[:12]
    temporary.mkdir(parents=True)
    try:
        env = local_environment(tools["java_home"])
        env["PATH"] = str(tools["tesseract_dir"]) + os.pathsep + env.get("PATH", "")
        env["TESSDATA_PREFIX"] = str(tools["tesseract_dir"] / "tessdata")
        env["OMP_THREAD_LIMIT"] = "1"
        env["TEMP"] = env["TMP"] = str(temporary)
        for key in ('PDF_REMEDIATOR_TABLE_EVIDENCE', 'PDF_REMEDIATOR_TABLE_SOURCE_SHA256', *ANGLE_ENV_KEYS, *TURN_ENV_KEYS, *ocr_confidence.ENV_KEYS):
            env.pop(key, None)
        limit = option(settings, "memory_limit_bytes", 4 * 1024**3)
        probe = run([tools["ocr_python"], "-I", "-B", "-X", "utf8", "-m", "ocrmypdf", "--version"], directory / "version",
                    min(option(settings, "timeout_seconds", 600), 30), limit, cancel, env)
        if probe["status"] != "completed" or Path(probe["stdout"]).read_text(encoding="utf-8").strip() != OCR_VERSION:
            return {"status": "error", "ocr_profile": profile, "mode": mode, 'requested_mode': mode, 'native_mode': native_mode,
                    'page_selection': selection, "error": "Pinned OCRmyPDF 17.13.0 startup failed", "version_probe": probe}
        destination.parent.mkdir(parents=True, exist_ok=True)
        original_hash = sha(source)
        command = [tools["ocr_python"], "-I", "-B", "-X", "utf8", "-m", "ocrmypdf", "--mode", native_mode, "--output-type", "pdf",
                   "--optimize", "0", "--rasterizer", "pypdfium", "--jobs", "1", "-l", language]
        if selection is not None:
            command.extend(['--pages', selection['native_page_clause']])
        oversample = None
        if profile in ('standard', 'turns'):
            oversample = oversample_plan(source, selection['selected_pages'] if selection is not None else [p['page'] for p in image_pages])
            if oversample['dpi']:
                command.extend(['--oversample', str(oversample['dpi'])])
        table_evidence = angle_evidence = turn_evidence = None
        if profile == 'turns':
            turn_evidence = directory / 'turns'
            turn_evidence.mkdir()
            env['PDF_REMEDIATOR_TURN_EVIDENCE'] = str(turn_evidence)
            env['PDF_REMEDIATOR_TURN_SOURCE_SHA256'] = original_hash
            word_confidence = directory / 'word-confidence.cfg'
            word_confidence.write_bytes(b'tessedit_create_tsv 1\n')
            command.extend(['--pdf-renderer', 'sandwich', '--tesseract-config', word_confidence, '--plugin', turn_paths['plugin_sha256']])
        elif profile == 'table-lines':
            table_evidence = directory / 'table-lines'
            table_evidence.mkdir()
            env['PDF_REMEDIATOR_TABLE_EVIDENCE'] = str(table_evidence)
            env['PDF_REMEDIATOR_TABLE_SOURCE_SHA256'] = original_hash
            command.extend(['--plugin', plugin])
        elif profile == 'angles':
            angle_evidence = directory / 'angles'
            angle_evidence.mkdir()
            env['PDF_REMEDIATOR_ANGLE_EVIDENCE'] = str(angle_evidence)
            env['PDF_REMEDIATOR_ANGLE_SOURCE_SHA256'] = original_hash
            command.extend(['--pdf-renderer', 'sandwich', '--max-ocr-image-mpixels', '32', '--plugin', angle_paths['plugin_sha256']])
        # How surely each page was read: noted by a small fixed hook (standard and ruled-table layouts) or recorded by the turn hook
        # itself (turns). The hook only observes; it cannot change what is read or written.
        confidence_dir = confidence_binding = None
        confidence_plugin = Path(__file__).resolve().with_name('ocr_confidence_plugin.py')
        confidence_algorithm = Path(ocr_confidence.__file__).resolve()
        if profile in ('standard', 'table-lines') and confidence_plugin.is_file() and confidence_algorithm.is_file():
            confidence_binding = {'plugin_sha256': sha(confidence_plugin), 'algorithm_sha256': sha(confidence_algorithm)}
            confidence_dir = directory / 'confidence'
            confidence_dir.mkdir()
            env[ocr_confidence.ENV_KEYS[0]] = str(confidence_dir)
            env[ocr_confidence.ENV_KEYS[1]] = original_hash
            command.extend(['--plugin', confidence_plugin])
        command.extend([source, destination])
        result = run(command, directory / "execution", option(settings, "timeout_seconds", 600), limit, cancel, env)
        result.update(mode=mode, requested_mode=mode, native_mode=native_mode, language=language, ocr_profile=profile, input_sha256=original_hash, version_probe=probe,
                      temporary_directory=str(temporary), document_network_calls=0, output_type="pdf", optimize=0, rasterizer="pypdfium",
                      source_image_pages=[p["page"] for p in image_pages], no_force=True)
        if oversample is not None:
            result['oversample'] = oversample
        if selection is not None:
            result['page_selection'] = selection
        if sha(source) != original_hash:
            result.update(status="error", error="Input changed during OCR")
        if result['status'] == 'completed' and table_evidence is not None:
            pages = []
            try:
                for path in sorted(table_evidence.glob('*.json')):
                    proof = json.loads(path.read_text(encoding='utf-8'))
                    if (not isinstance(proof, dict) or proof.get('schema') != 'phase1-ocr-table-preprocess-1' or proof.get('profile') != profile
                            or type(proof.get('page')) is not int or not 1 <= proof['page'] <= len(before['pages'])
                            or path.name != f"{proof['page']:06d}.json" or proof.get('adapter_source_sha256') != original_hash
                            or proof.get('plugin_sha256') != table_binding['plugin_sha256'] or proof.get('algorithm_sha256') != table_binding['algorithm_sha256']
                            or proof.get('outside_detected_grids_unchanged') is not True
                            or proof.get('status') not in ('filtered', 'no-grid')):
                        raise ValueError('Ruled-table OCR preprocessing evidence is invalid.')
                    _require_table_preprocessing_shape(proof)
                    pages.append({**proof, 'path': str(path), 'sha256': sha(path)})
                required_pages = set(selection['selected_pages']) if selection is not None else {page['page'] for page in image_pages}
                actual_pages = {page['page'] for page in pages}
                if (actual_pages != required_pages if selection is not None else not required_pages <= actual_pages):
                    raise ValueError('Ruled-table OCR preprocessing evidence is incomplete.')
                if table_binding != {'plugin_sha256': sha(plugin), 'algorithm_sha256': sha(algorithm)}:
                    raise ValueError('Ruled-table OCR implementation changed during processing.')
                result['recognition_preprocessing'] = {'profile': profile, **table_binding, 'pages': pages,
                                                      'scope': 'Recognition-only conditioning; original painting and every existing preservation gate remain unchanged.'}
            except (OSError, ValueError, TypeError) as error:
                result.update(status='error', error=str(error))
        if result['status'] == 'completed' and angle_evidence is not None:
            try:
                if angle_binding != {key: sha(path) for key, path in angle_paths.items()} or sha(font) != FONT_SHA256:
                    raise ValueError('Angle OCR implementation or font changed during processing.')
                required_pages = selection['selected_pages'] if selection is not None else [page['page'] for page in image_pages]
                pages = validate_angle_pages(angle_evidence, required_pages, angle_binding, font, original_hash, len(before['pages']))
                if angle_binding != {key: sha(path) for key, path in angle_paths.items()} or sha(font) != FONT_SHA256:
                    raise ValueError('Angle OCR implementation or font changed during processing.')
                result['recognition_alternatives'] = {'profile': profile, **angle_binding, 'font_sha256': FONT_SHA256, 'pages': pages,
                    'scope': 'Local recognition alternatives and hidden text only; original painting and all preservation gates remain required.'}
            except Exception as error:
                # This is a child-process evidence boundary, including bounded
                # raster/font/PDF parsers. An unreadable proof can never pass.
                result.update(status='error', error='Angle OCR evidence validation failed: ' + str(error))
        if result['status'] == 'completed' and turn_evidence is not None:
            try:
                if turn_binding != {key: sha(path) for key, path in turn_paths.items()}:
                    raise ValueError('Turn recognition implementation changed during processing.')
                required_pages = selection['selected_pages'] if selection is not None else [page['page'] for page in image_pages]
                pages = validate_turn_pages(turn_evidence, required_pages, turn_binding, original_hash, len(before['pages']))
                result['recognition_turns'] = {'profile': profile, **turn_binding, 'pages': pages,
                    'turned_pages': [p['page'] for p in pages if p['turn_ccw']],
                    'scope': 'Local right-angle turn trials and hidden text only; original painting and all preservation gates remain required.'}
            except Exception as error:
                # The evidence is written by a child process; an unreadable proof can never pass.
                result.update(status='error', error='Turn recognition evidence validation failed: ' + str(error))
        if result["status"] == "completed":
            if not destination.is_file() or destination.stat().st_size == 0:
                result.update(status="error", error="OCR completed without a PDF")
            else:
                result["fidelity"] = compare_fidelity(source, destination, cancel=cancel)
                result["preservation"] = _ocr_preservation(result["fidelity"], expected_pages=len(before["pages"]))
                after = inspect_pdf(destination, cancel=cancel)
                result["output_inspection"] = after
                if selection is not None:
                    coverage = check_textless_coverage(selection, result['fidelity'], after)
                    result['textless_page_coverage'] = coverage
                    result['preservation']['textless_page_coverage_status'] = coverage['status']
                    if coverage['status'] != 'pass':
                        result['preservation']['status'] = 'fail'
                if after.get("error"):
                    result.update(status="error", error="OCR output could not be inspected")
                elif any(p["class"] == "scanned" for p in after["pages"]):
                    result.update(status="failed", error="Image-only output still has no selectable text")
                elif result["preservation"]["status"] != "pass":
                    message = 'OCR changed an excluded text-bearing page or left a selected page without text' if selection is not None and coverage['status'] != 'pass' else 'OCR failed exact visible/original-text preservation'
                    result.update(status="failed", error=message)
                elif before.get("structure", {}).get("present"):
                    # Tested skip scope: keep tag inventories and alternatives. This
                    # is a bounded signal, not a semantic-tree equivalence proof.
                    a, b = before["structure"], after["structure"]
                    same = a.get("tag_counts") == b.get("tag_counts") and [f["alt"] for f in a["figures"]] == [f["alt"] for f in b["figures"]]
                    result["existing_tag_inventory_preserved"] = same
                    if not same:
                        result.update(status="failed", error="OCR changed existing tag inventory")
                result.update(output=str(destination), output_sha256=sha(destination),
                              human_review_pending=["OCR accuracy", "OCR completeness", "reading order"])
        if result["status"] == "completed":
            result['reading_confidence'] = _reading_confidence(
                profile, selection['selected_pages'] if selection is not None else [p['page'] for p in image_pages], len(before['pages']), original_hash,
                directory=confidence_dir, binding=confidence_binding,
                turn_pages=result.get('recognition_turns', {}).get('pages'))
        return result
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
