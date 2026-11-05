"""Create a separate copy/paste experiment for the exact Windows pilot PDFs.

This is not a general repair or a change to Auto-fix. Only two known synthetic
line endings receive an explicit space, with real gates rerun. The original
result stays unchanged. Desktop PDF viewer behavior still needs an actual human retest.
"""
from pathlib import Path
import argparse
import json
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import pikepdf
from pdf_remediator.checks import assess
from pdf_remediator.config import load_config
from pdf_remediator.doctor import sha
from pdf_remediator.inspection import compare_fidelity, inspect_pdf
from pdf_remediator.validation import validate_pdf

SOURCE_SHA = 'ed1351295101b5dc72c5fa0f5075fb6074ac3d2f4868a2ee4feac3403d3f4a3b'
CANDIDATE_SHA = '41efe341fa7bf14ef0850bec7a24e727d213de376d4797c53e976a3a691cd683'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, candidate, output = [path.resolve() for path in (args.source, args.candidate, args.output)]
    require(sha(source) == SOURCE_SHA, 'This probe accepts only the unchanged synthetic pilot source')
    require(sha(candidate) == CANDIDATE_SHA, 'This probe accepts only the exact uploaded Windows pilot result')
    require(output not in (source, candidate) and not output.exists(), 'Choose a distinct new output file')
    config = load_config(args.config)
    require(config.ocr_mode == 'off', 'Keep OCR off')
    evidence = output.with_suffix('.copy-evidence')
    evidence.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        (evidence / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

    before = compare_fidelity(source, candidate)
    save('before-fidelity.json', before)
    require(before['status'] == 'pass', 'Pilot candidate no longer passes existing source fidelity')
    with pikepdf.open(source) as pdf:
        source_cmaps = {str(name): font.ToUnicode.read_bytes() for name, font in pdf.pages[0].Resources.Font.items()}
        targets = {bytes(operands[0]) for operands, operator in pikepdf.parse_content_stream(pdf.pages[0])
                   if str(operator) == 'Tj' and bytes(operands[0]).endswith((b'Each card', b'This original'))}
    require(len(targets) == 2, 'Expected authored pilot line endings were not found')
    patched = evidence / 'experimental.pdf'
    changes = []
    with pikepdf.open(candidate) as pdf:
        require(len(pdf.pages) == 1, 'Only the one-page pilot is supported')
        page = pdf.pages[0]
        require(isinstance(page.Contents, pikepdf.Stream), 'Unexpected pilot stream shape')
        instructions = list(pikepdf.parse_content_stream(page))
        current_font = None
        for index, (operands, operator) in enumerate(instructions):
            if str(operator) == 'Tf':
                current_font = str(operands[0])
            if str(operator) != 'Tj' or bytes(operands[0]) not in targets:
                continue
            font = page.Resources.Font[current_font]
            require(font.Subtype == pikepdf.Name.TrueType and
                    font.ToUnicode.read_bytes() == source_cmaps.get(current_font) and
                    re.search(rb'(?m)^\s*<20>\s*<0020>\s*$', font.ToUnicode.read_bytes()) is not None,
                    'The pilot font must explicitly map code 20 to a Unicode space')
            # No later text/painting in this BT may be shifted by the extra space.
            tail = []
            for _, next_operator in instructions[index + 1:]:
                tail.append(str(next_operator))
                if str(next_operator) == 'ET':
                    break
            require(tail == ['EMC', 'T*', 'ET'], 'Unexpected text positioning after pilot line')
            raw = bytes(operands[0])
            instructions[index] = pikepdf.ContentStreamInstruction([pikepdf.String(raw + b' ')], operator)
            changes.append(raw)
        require(len(changes) == 2 and set(changes) == targets, 'Pilot lines were missing or repeated')
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(instructions))
        pdf.save(patched, deterministic_id=True)
    gate1 = validate_pdf(patched, evidence / 'validator', config.validator_cli, config.java_home,
                         timeout_seconds=config.validator_timeout_seconds,
                         memory_limit_bytes=config.memory_limit_bytes, heap_mb=config.java_heap_mb)
    inspection = inspect_pdf(patched)
    gate2 = assess(inspection, source=inspect_pdf(source))
    fidelity = compare_fidelity(source, patched)
    save('validator.json', gate1)
    save('supplemental.json', gate2)
    save('fidelity.json', fidelity)
    require(all(value['status'] == 'pass' for value in (gate1, gate2, fidelity)),
            'An existing automated gate failed; no experimental PDF will be exported')
    assessed = sha(patched)
    require(gate1['input_sha256'] == inspection['sha256'] == fidelity['after_sha256'] == assessed,
            'Assessment hashes disagree')
    require(sha(source) == SOURCE_SHA and sha(candidate) == CANDIDATE_SHA, 'An original input changed')
    with patched.open('rb') as inp, output.open('xb') as dest:
        shutil.copyfileobj(inp, dest)
    require(sha(output) == assessed, 'Export changed the assessed bytes')
    save('report.json', {'status': 'experimental-awaiting-desktop-viewer-retest', 'human_verified': False,
         'production_fix_confirmed': False, 'source_sha256': SOURCE_SHA, 'prior_candidate_sha256': CANDIDATE_SHA,
         'output_sha256': assessed, 'explicit_line_end_spaces': 2, 'ai': 'off', 'ocr': 'off',
         'scope': 'Exact synthetic pilot only; does not replace the application result or its review records'})
    print('Created separate experiment:', output)
    print('Automated gates pass. Copy/paste behavior is not confirmed until the desktop PDF viewer retest.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
