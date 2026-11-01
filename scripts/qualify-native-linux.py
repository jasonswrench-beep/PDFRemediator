"""Run bounded synthetic native Linux contracts with real ODL and veraPDF.

This is automated evidence for the named fixtures only, not full native support
or human accessibility acceptance. AI/OCR remain off. All output is local.
"""
from pathlib import Path
from dataclasses import replace
import argparse
import importlib.util
import json
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from pdf_remediator.config import load_config
from pdf_remediator.doctor import inventory, sha
from pdf_remediator.inspection import compare_fidelity
from pdf_remediator.pipeline import process_file, verify_bundle
from pdf_remediator.sidecar import make_automatic_authorization, bind_automatic_acceptance, write_sidecar


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-book', action='store_true', help='Also check the 200-page synthetic safety boundary')
    args = parser.parse_args()
    require(sys.platform == 'linux', 'This trial is Linux-specific')
    config = load_config(args.config)
    require(config.ocr_mode == 'off', 'OCR must remain off')
    # Avoid silently changing the native scope through optional exception routes.
    require(config.preserve_painting and not config.allow_tag_regrouping and not config.repair_source_mappings,
            'Trial requires painting preservation and no optional repair exceptions')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    summary = {'scope': 'bounded-synthetic-native-linux', 'full_native_qualification': False,
               'human_verified': False, 'ai': 'off', 'ocr': 'off', 'status': 'failed',
               'python': platform.python_version(), 'platform': platform.platform(), 'cases': []}

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

    try:
        doctor = inventory(settings=config)
        save('doctor.json', doctor)
        require(doctor['status'] == 'ready', 'Pinned native dependencies are not ready; see doctor.json')
        spec = importlib.util.spec_from_file_location('native_trial_corpus', ROOT / 'eval/build_corpus.py')
        corpus = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(corpus)
        inputs = output / 'inputs'
        inputs.mkdir()
        corpus.register_fonts(inputs)
        corpus.tag_control(inputs / 'tagged-control.pdf')
        corpus.simple(inputs / 'simple.pdf')
        corpus.tag_variants(inputs / 'tagged-control.pdf', inputs / 'phantom.pdf', inputs / 'incomplete.pdf')
        corpus.tagged_figure_control(inputs / 'figures.pdf')
        corpus.structured(inputs / 'structured.pdf', corpus.ImageReader(corpus.image_asset()))
        corpus.detection_fixtures(inputs)
        cases = [('tagged-control', 'fix'), ('simple', 'fix'), ('phantom', 'check'),
                 ('incomplete', 'check'), ('figures', 'fix'), ('structured', 'fix'),
                 ('forms-detect-only', 'fix')]
        reports = {}
        for name, mode in cases:
            source = inputs / (name + '.pdf')
            before = sha(source)
            report = process_file(source, output / 'results', config, mode=mode)
            reports[name] = report
            bundle = Path(report['bundle_path'])
            require(sha(source) == before, name + ': source changed')
            require(verify_bundle(bundle), name + ': incoherent immutable bundle')
            entry = {'name': name, 'mode': mode, 'status': report['status'], 'source_sha256': before,
                     'bundle': str(bundle.relative_to(output)), 'original_unchanged': True,
                     'gates': {key: (report.get(key) or {}).get('status') for key in ('gate1', 'gate2', 'fidelity')}}
            summary['cases'].append(entry)
            if name == 'simple':
                proof = next(item for item in report['processors'] if item['name'] == 'preserve-painting')
                records = proof.get('automatic_line_separators', [])
                require(proof['changes'].get('source_line_separators_added') == 2 and len(records) == 2,
                        'Simple control must preserve both authored line boundaries')
                require(all(item['origin'] == 'automatic-source-line-separator' and
                            item['human_verified'] is False for item in records),
                        'Source line separators must not imply human verification')
                entry['automatic_line_separators'] = records
            if name in ('tagged-control', 'simple'):
                require(report['status'] == 'candidate', name + ': expected candidate')
                require(all(entry['gates'][key] == 'pass' for key in ('gate1', 'gate2', 'fidelity')),
                        name + ': native gate failure')
                require(report['gate1']['version'] == '1.30.3', name + ': validator version mismatch')
                require(report['gate1']['input_sha256'] == report['output']['sha256'], name + ': validator binding mismatch')
                require(report['fidelity']['after_sha256'] == report['output']['sha256'], name + ': fidelity binding mismatch')
                require(not report['manual_review']['complete'] and report['manual_review']['items'],
                        name + ': automatic processing must not fabricate completed human review')
            else:
                require(report['status'] in ('failed', 'needs-manual'), name + ': unsafe candidacy')
                require(not (bundle / 'candidate.pdf').exists(), name + ': unexpected published candidate')
                if name in ('phantom', 'incomplete'):
                    require(entry['gates']['gate1'] == entry['gates']['gate2'] == 'fail', name + ': false gate pass')
                    require(report['output'] is None, name + ': malformed structure must publish no PDF')
                elif name in ('figures', 'structured'):
                    require(entry['gates']['gate2'] == 'fail' and entry['gates']['fidelity'] == 'pass', name + ': expected semantic blocker with preserved appearance')
                    require(report['output'] and report['output']['review_only'], name + ': draft must be review-only')
                    expected_pages = 4 if name == 'structured' else 1
                    require(len(report['fidelity']['pages']) == expected_pages, name + ': incomplete all-page fidelity')
                else:
                    require(report['output'] is None and entry['gates']['gate1'] == 'not-run', name + ': unsupported form should refuse before validation')
            print(name + ': ' + report['status'], flush=True)
        # Known authored captions are fixture values, not model inference and
        # never named human approval. Every automatic semantic review stays pending.
        previous = reports['figures']
        previous_bundle = Path(previous['bundle_path'])
        previous_manifest = sha(previous_bundle / 'manifest.json')
        decisions = json.loads((previous_bundle / 'decisions.json').read_text(encoding='utf-8'))
        figures = [item for item in decisions['decisions'] if item['kind'] == 'figure-description']
        require(len(figures) == 2, 'Automatic control needs both figure occurrences')
        authorization = make_automatic_authorization(
            decisions['source_sha256'], decisions['document_sha256'], '2026-10-16T12:00:00Z',
            'synthetic-authored-caption-control', decision_ids=[item['id'] for item in figures])
        for item, value in zip(figures, ['Orange circle and blue square represent two garden plots.',
                                         'The same orange circle and blue square represent two archive bins.']):
            origin = {'schema_version': 'phase2-ai-origin-1', 'provider': 'synthetic-authored-ground-truth',
                      'model': 'none; deterministic fixture values, no inference',
                      'context_sha256': item['context_sha256'], 'request_context_sha256': '0' * 64}
            bind_automatic_acceptance(item, value, authorization, origin=origin)
            require('approved_by' not in item and 'approval_sha256' not in item, 'Automatic value claims human approval')
        sidecar = output / 'synthetic-automatic-decisions.json'
        write_sidecar(decisions, sidecar)
        automatic = process_file(inputs / 'figures.pdf', output / 'automatic-results', config,
                                 sidecar=sidecar, decision_bundle=previous_bundle,
                                 automatic_authorization=authorization)
        require(automatic['status'] == 'candidate', 'Automatic fixture failed native candidacy')
        require(all(automatic[key]['status'] == 'pass' for key in ('gate1', 'gate2', 'fidelity')),
                'Automatic fixture bypassed a gate')
        require(automatic['automatic_mode']['human_reviewed'] is False and not automatic['manual_review']['complete'],
                'Automatic fixture fabricated human review')
        require(automatic['data_sent']['document_api_calls'] == 0, 'Automatic fixture called an external provider')
        require(verify_bundle(automatic['bundle_path']) and verify_bundle(previous_bundle) and
                sha(previous_bundle / 'manifest.json') == previous_manifest, 'Automatic fixture modified prior evidence')
        summary['cases'].append({'name': 'authored-automatic-figures', 'status': automatic['status'],
                                 'human_reviewed': False, 'manual_complete': False,
                                 'bundle': str(Path(automatic['bundle_path']).relative_to(output))})
        changed_config = replace(config, java_heap_mb=1024 if config.java_heap_mb != 1024 else 2048)
        refused = process_file(inputs / 'figures.pdf', output / 'changed-settings-results', changed_config,
                               sidecar=sidecar, decision_bundle=previous_bundle,
                               automatic_authorization=authorization)
        require(refused['status'] == 'failed' and refused['output'] is None,
                'Accepted edits reused a preparation with changed settings')
        require('preparation settings' in refused.get('error', {}).get('message', ''),
                'Changed-settings fixture failed for an unexpected reason')
        summary['cases'].append({'name': 'changed-preparation-settings', 'status': refused['status'],
                                 'expected_refusal': True})
        if args.include_book:
            corpus.book(inputs / 'book200.pdf', corpus.ImageReader(corpus.image_asset()))
            book_source_sha = sha(inputs / 'book200.pdf')
            book = process_file(inputs / 'book200.pdf', output / 'book-results', config)
            require(book['status'] == 'needs-manual' and book['gate2']['status'] == 'fail',
                    'Book with missing figure descriptions cannot become a candidate')
            require(len(book['fidelity']['pages']) == 200, 'Book comparison omitted pages')
            require(not (Path(book['bundle_path']) / 'candidate.pdf').exists(), 'Book escaped manual handling')
            if book['fidelity']['status'] == 'fail':
                require(book['output'] is None, 'Book with visual changes published a PDF')
            require(verify_bundle(book['bundle_path']) and sha(inputs / 'book200.pdf') == book_source_sha,
                    'Book original or evidence changed')
            summary['cases'].append({'name': 'book200', 'status': book['status'],
                                     'fidelity': book['fidelity']['status'], 'pages_compared': 200,
                                     'output_published': bool(book['output'])})
            print('book200: ' + book['status'] + '; fidelity=' + book['fidelity']['status'], flush=True)
            # Exercise the separately selected regrouping route from the original
            # source; never change settings while applying a saved decision bundle.
            regroup_config = replace(config, allow_tag_regrouping=True)
            regroup = process_file(inputs / 'book200.pdf', output / 'book-regroup-results', regroup_config)
            require(regroup['status'] == 'needs-manual' and regroup['fidelity']['status'] == 'pass',
                    'Explicit book regrouping did not preserve all pages')
            require(len(regroup['fidelity']['pages']) == 200 and regroup['output']['review_only'],
                    'Regrouped book must remain a 200-page review draft until descriptions are supplied')
            reviews = [item for item in regroup['manual_review']['items'] if item['category'] == 'tag-regrouping']
            require(reviews and all(item['status'] == 'pending' for item in reviews),
                    'Regrouping claimed completed human reviews')
            book_bundle = Path(regroup['bundle_path'])
            book_decisions = json.loads((book_bundle / 'decisions.json').read_text(encoding='utf-8'))
            book_figures = [item for item in book_decisions['decisions'] if item['kind'] == 'figure-description']
            require({item['page'] for item in book_figures} == {40, 110} and len(book_figures) == 2,
                    'Book ground-truth figure occurrences changed')
            book_authorization = make_automatic_authorization(
                book_decisions['source_sha256'], book_decisions['document_sha256'], '2026-10-16T12:00:00Z',
                'synthetic-book-authored-caption-control', decision_ids=[item['id'] for item in book_figures])
            for item in book_figures:
                meaning = 'plot comparison' if item['page'] == 40 else 'archive classification'
                value = 'An orange circle and blue square illustrate ' + meaning + '.'
                origin = {'schema_version': 'phase2-ai-origin-1', 'provider': 'synthetic-authored-ground-truth',
                          'model': 'none; deterministic fixture values, no inference',
                          'context_sha256': item['context_sha256'], 'request_context_sha256': '0' * 64}
                bind_automatic_acceptance(item, value, book_authorization, origin=origin)
            book_sidecar = output / 'synthetic-book-decisions.json'
            write_sidecar(book_decisions, book_sidecar)
            final_book = process_file(inputs / 'book200.pdf', output / 'book-automatic-results', regroup_config,
                                      sidecar=book_sidecar, decision_bundle=book_bundle,
                                      automatic_authorization=book_authorization)
            require(final_book['status'] == 'candidate' and all(final_book[key]['status'] == 'pass'
                    for key in ('gate1', 'gate2', 'fidelity')), 'Authored book did not pass every real gate')
            require(len(final_book['fidelity']['pages']) == 200 and verify_bundle(final_book['bundle_path']),
                    'Authored book evidence incomplete')
            require(not final_book['manual_review']['complete'] and
                    final_book['automatic_mode']['human_reviewed'] is False,
                    'Authored book invented human verification')
            require(final_book['data_sent']['document_api_calls'] == 0 and sha(inputs / 'book200.pdf') == book_source_sha,
                    'Authored book called an external provider or changed the original')
            require(all(item['status'] == 'pending' for item in final_book['manual_review']['items']),
                    'Authored book marked human review complete')
            summary['cases'].append({'name': 'book200-regroup-authored-descriptions',
                                     'status': final_book['status'], 'pages_compared': 200,
                                     'regroup_reviews_pending': len(reviews), 'human_reviewed': False,
                                     'bundle': str(Path(final_book['bundle_path']).relative_to(output))})
            print('book200 explicit regroup + authored descriptions: candidate; human reviews pending', flush=True)

        corpus.tag_control(inputs / 'deliberate-loss.pdf', lost=True)
        corpus.mis_mapping(inputs / 'tagged-control.pdf', inputs / 'wrong-mapping.pdf')
        for name in ('deliberate-loss', 'wrong-mapping'):
            fidelity = compare_fidelity(inputs / 'tagged-control.pdf', inputs / (name + '.pdf'))
            save(name + '-fidelity.json', fidelity)
            require(fidelity['status'] == 'fail' and fidelity['text']['multiset_status'] == 'fail', name + ': content defect escaped')
            expected = 'fail' if name == 'deliberate-loss' else 'pass'
            require(fidelity['pages'][0]['render_status'] == expected, name + ': incorrect appearance evidence')
        summary['status'] = 'all-bounded-contracts-passed'
    except Exception as exc:
        summary['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        save('summary.json', summary)
    print('Bounded native contracts passed. Human acceptance and full native qualification remain outstanding.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
