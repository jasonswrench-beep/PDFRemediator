"""Reproduce bounded Linux review/retry/apply/restart checks with real native tools.

Uses only authored generated inputs. No browser, AI, OCR or human verification.
Missing native dependencies fail the trial; this is not full native qualification.
"""
from dataclasses import replace
from pathlib import Path
import argparse
import json
import platform
import runpy
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from pdf_remediator import pipeline, web, workspace
from pdf_remediator.config import load_config
from pdf_remediator.doctor import inventory


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate_scope(config, output):
    require(sys.platform == 'linux', 'This bounded trial is Linux-specific; Windows execution is not qualified.')
    require(config.ocr_mode == 'off', 'OCR must remain off.')
    require(config.preserve_painting and not config.allow_tag_regrouping and not config.repair_source_mappings,
            'Painting preservation and the default repair boundaries are required.')
    require(ROOT.resolve() / 'work' in output.resolve().parents, 'Choose a fresh output folder under this checkout\'s work directory.')
    require(not output.exists(), 'The trial output already exists; nothing will be overwritten.')


def wait_job(app, queued, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with app.lock:
            job = app.public_job(app.jobs[queued['job_id']])
        if job['status'] not in ('queued', 'running'):
            return job
        time.sleep(.05)
    with app.lock:
        app.jobs[queued['job_id']]['cancel'].set()
    raise RuntimeError('The bounded review job exceeded its trial deadline; cancellation requested.')


def require_candidate(report):
    require(report['status'] == 'candidate', 'The native trial did not produce a candidate: ' + str(report.get('error', report['status'])))
    require(pipeline.verify_bundle(report['bundle_path']), 'Native candidate bundle is incoherent.')
    require(all(report[key]['status'] == 'pass' for key in ('gate1', 'gate2', 'fidelity')), 'A native release gate failed.')
    require(report['gate1'].get('version') == '1.30.3', 'Unexpected validator version.')
    require(report['gate1']['input_sha256'] == report['output']['sha256'] == report['fidelity']['after_sha256'],
            'Assessment hashes do not match the published PDF.')
    require(report['manual_review']['items'] and not report['manual_review']['complete'], 'Human review must remain pending.')
    require(report['data_sent'].get('provider') is None, 'A model provider was unexpectedly used.')


def bundle_report(view):
    return json.loads((Path(view['bundle_path']) / 'report.json').read_text(encoding='utf-8'))


def run_trial(config, output):
    validate_scope(config, output)
    output.mkdir(parents=True, exist_ok=False)
    summary = {'scope': 'bounded-synthetic-linux-review-lifecycle', 'status': 'failed',
               'full_native_qualification': False, 'human_verified': False, 'ai': 'off', 'ocr': 'off',
               'python': platform.python_version(), 'platform': platform.platform(), 'cases': []}
    app = None
    real_worker = web.process_isolated
    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    def record(name, report=None, **evidence):
        case = {'name': name, 'status': 'pass', **evidence}
        if report is not None:
            case.update(bundle=str(Path(report['bundle_path']).relative_to(output)), result_status=report['status'],
                        gates={key: report.get(key, {}).get('status') for key in ('gate1', 'gate2', 'fidelity')},
                        output_sha256=(report.get('output') or {}).get('sha256'))
        summary['cases'].append(case)
    try:
        doctor = inventory(settings=config)
        save('doctor.json', doctor)
        require(doctor['status'] == 'ready', 'Pinned native prerequisites are not ready; see doctor.json. Nothing is skipped.')
        corpus = runpy.run_path(str(ROOT / 'eval/build_corpus.py'))
        inputs = output / 'inputs'; inputs.mkdir()
        summary['font_provenance'] = corpus['register_fonts'](inputs)
        source = inputs / 'reading-source.pdf'; corpus['simple'](source)
        source_hash = pipeline.sha(source)
        initial = pipeline.process_file(source, output / 'initial', config)
        require_candidate(initial)
        record('original-native-candidate', initial, source_sha256=source_hash)

        broken = replace(config, validator_cli=output / 'intentionally-absent-validator')
        failed = pipeline.process_file(source, output / 'controlled-failure', broken)
        require(failed['status'] == 'failed' and failed['output'] is None, 'Missing validator did not stop publication.')
        require(any('baseline validator did not assess' in item.get('description', '') for item in failed['residual_issues']),
                'Controlled failure did not exercise the expected baseline guard.')
        require(pipeline.verify_bundle(failed['bundle_path']), 'Failed-attempt evidence is incoherent.')
        record('missing-validator-refusal', failed)

        app = web.Application(output / 'review', config)
        failed_id = app.import_bundle(failed['bundle_path']); failed_view = app.view(failed_id)
        failed_bytes = app.state_path(failed_id).read_bytes()
        failed_manifest = pipeline.sha(Path(failed['bundle_path']) / 'manifest.json')
        retried = wait_job(app, app.retry(failed_id, {'revision': failed_view['revision']}))
        require(retried['status'] == 'done', 'Retry failed: ' + str(retried.get('error')))
        identifier = retried['result']['documents'][0]['workspace_id']; view = app.view(identifier)
        require(identifier != failed_id, 'Retry reused the failed review workspace.')
        require_candidate(bundle_report(view))
        require(app.state_path(failed_id).read_bytes() == failed_bytes, 'Retry changed the failed review.')
        require(pipeline.sha(Path(failed['bundle_path']) / 'manifest.json') == failed_manifest, 'Retry changed failed-attempt evidence.')
        record('retry-with-correct-runtime', bundle_report(view), old_review_unchanged=True)

        state = app.state_path(identifier)
        edited = workspace.edit_decision(state, 'metadata:title', 'Authored native lifecycle title', view['revision'])
        accepted = workspace.approve_decision(state, 'metadata:title', 'Synthetic Trial Reviewer', '2026-10-18', edited['revision'])
        accepted_bytes = state.read_bytes()
        applied = wait_job(app, app.apply(identifier, {'revision': accepted['revision']}))
        require(applied['status'] == 'done', 'Accepted-edit application failed: ' + str(applied.get('error')))
        result = app.view(applied['result']['documents'][0]['workspace_id']); report = bundle_report(result)
        require_candidate(report)
        require(report.get('checkpoint_reused') is True, 'Accepted edits did not adopt the bound preparation.')
        require(state.read_bytes() == accepted_bytes, 'Application changed the initiating review.')
        record('apply-accepted-metadata', report, initiating_review_unchanged=True)

        old_token = app.token; app.close(); app = web.Application(output / 'review', config)
        restored = app.view(identifier)
        title = next(item for item in restored['decisions'] if item['id'] == 'metadata:title')
        require(app.token != old_token and state.read_bytes() == accepted_bytes, 'Reconstruction changed saved review or reused session authority.')
        require(title['value'] == 'Authored native lifecycle title' and title['status'] == 'approved' and title['human_touched'],
                'Reconstruction lost the named accepted metadata value.')
        require(restored['verification'] == 'not-verified', 'Restart fabricated human verification.')
        record('saved-review-reconstruction', state_unchanged=True, verification='not-verified')

        completed, changed = [], []
        def worker(*args, **kwargs):
            report = real_worker(*args, **kwargs)
            require_candidate(report); completed.append(report)
            current = app.view(identifier)
            workspace.edit_decision(state, 'metadata:title', 'Later authored synthetic edit', current['revision'])
            changed.append(state.read_bytes())
            return report
        web.process_isolated = worker
        raced = wait_job(app, app.apply(identifier, {'revision': restored['revision']}))
        web.process_isolated = real_worker
        require(raced['status'] == 'failed' and 'changed during' in str(raced.get('error')) and raced['result'] is None,
                'Application attached a result after the review changed.')
        require(state.read_bytes() == changed[0], 'Application lost the later saved edit.')
        require(completed[0]['bundle_path'] in {item['path'] for item in app.catalog()['bundles']}, 'Detached completed result is undiscoverable.')
        require(pipeline.verify_bundle(completed[0]['bundle_path']), 'Detached result lost its integrity.')
        record('later-edit-prevents-result-switch', completed[0], saved_edit_preserved=True, separate_result=True)

        entered, release = threading.Event(), threading.Event()
        def barrier(cancel, progress, job):
            entered.set()
            require(release.wait(5), 'Queue barrier timed out.')
        try:
            first = app.submit('Authored queue barrier', barrier)
            require(entered.wait(2), 'Queue barrier did not start.')
            queued = app.retry(failed_id, {'revision': failed_view['revision']})
            before = sorted(str(path) for path in (app.root / 'runs').rglob('manifest.json'))
            with app.lock: app.jobs[queued['job_id']]['cancel'].set()
            release.set()
            require(wait_job(app, first)['status'] == 'done', 'Queue barrier failed.')
            cancelled = wait_job(app, queued)
            require(cancelled['status'] == 'cancelled' and cancelled['result'] is None, 'Queued cancellation executed work.')
            require(sorted(str(path) for path in (app.root / 'runs').rglob('manifest.json')) == before, 'Cancelled queued retry published another run.')
            record('queued-retry-cancellation', no_new_bundle=True)
        finally:
            release.set()
        require(pipeline.sha(source) == source_hash, 'The original synthetic PDF changed.')
        require(app.view(identifier)['verification'] == 'not-verified', 'Lifecycle trial fabricated verification.')
        summary['original_unchanged'] = True
        summary['status'] = 'all-bounded-contracts-passed'
    except Exception as exc:
        summary['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        web.process_isolated = real_worker
        try:
            if app is not None: app.close()
        except Exception as exc:
            summary['status'] = 'failed'
            summary['cleanup_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        finally:
            save('summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory under this checkout\'s work folder')
    args = parser.parse_args(argv)
    summary = run_trial(load_config(args.config), args.output.resolve())
    if summary['status'] != 'all-bounded-contracts-passed':
        print('Native review lifecycle trial failed; see summary.json. No prerequisites were skipped.', file=sys.stderr)
        return 1
    print('Bounded native review lifecycle checks passed. Human acceptance and full native qualification remain outstanding.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
