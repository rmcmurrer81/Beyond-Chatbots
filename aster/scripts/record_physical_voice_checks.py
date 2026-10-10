"""Retain bounded physical-voice qualification without raw trajectory uploads."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
import tempfile
from record_text_learning_checks import canonical, compact_aggregate, fingerprints, run_stage, utc


def public_receipt(value):
    """Copy outcomes while removing known local-only raw-trace locations."""
    if type(value) is not dict:
        raise ValueError('object_receipt_required')
    value = json.loads(canonical(value))
    if 'raw_directory' in value:
        value.pop('raw_directory')
        value['raw_directory_omitted'] = True
    if type(value.get('cases')) is list:
        for case in value['cases']:
            if type(case) is not dict or type(case.get('raw')) is not dict or 'path' not in case['raw']:
                continue
            raw = case['raw']
            if type(raw['path']) is not str:
                raise ValueError('raw_path_type_refused')
            filename = Path(raw.pop('path')).name
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', filename) or filename in ('.', '..'):
                raise ValueError('raw_filename_refused')
            raw['filename'] = filename
            raw['local_path_omitted'] = True
    if 'failure' in value and type(value['failure']) is dict:
        value['failure'] = {'type': value['failure'].get('type', 'unknown'),
                            'local_diagnostic_message_omitted': True}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--aggregate', action='store_true')
    parser.add_argument('--with-text-lab', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    # Local raw traces remain in this execution workspace, never in the upload
    # directory. CI runners are ephemeral; recipes and hashes survive in JSON.
    private = Path(tempfile.mkdtemp(prefix='aster-physical-check-'))
    report = {'schema': 'aster.physical-voice-checks.v1', 'started_utc': utc(),
              'runtime': {'python': platform.python_version(), 'platform': sys.platform},
              'source_before': fingerprints(args.output), 'stages': [], 'completed': False,
              'raw_trajectories_uploaded': False, 'model_state_uploaded': False,
              'raw_retention': 'Local execution workspace only; CI runners are ephemeral',
              'automatic_playback': False, 'production_brain_enabled': False,
              'physiological_or_perceptual_validation': False}

    def persist():
        report['updated_utc'] = utc()
        if report['completed']:
            report['finished_utc'] = report['updated_utc']
        report['success'] = (report['completed'] and bool(report['stages'])
                             and all(s['status'] == 'PASS' for s in report['stages']))
        (args.output / 'result.json').write_bytes(canonical(report))

    def keep_result(row, value, filename, cap=524288):
        # One known private diagnostic field in the filter gate is unnecessary
        # for scientific reproduction; raw artifact names/hashes remain intact.
        value = public_receipt(value)
        raw = canonical(value)
        forbidden = (str(private), 'model_b64', 'state_b64', 'Traceback')
        if len(raw) > cap or any(token.encode() in raw for token in forbidden):
            raise ValueError('public_receipt_refused')
        target = args.output / filename
        with target.open('xb') as stream:
            stream.write(raw)
        row['result_file'], row['result_sha256'] = filename, hashlib.sha256(raw).hexdigest()

    def stage(label, arguments, timeout=300, receipt=None, json_stdout=False, tests=False):
        row, raw = run_stage(label, arguments, private, timeout)
        if tests and (not row['unittest_summaries'] or row['skipped_count']
                      or sum(s['tests'] for s in row['unittest_summaries']) <= 0):
            row['status'], row['error_code'] = 'FAIL', 'positive_unskipped_tests_required'
        try:
            if receipt is not None:
                content = receipt.read_bytes()
                if len(content) > 524288:
                    raise ValueError('receipt_size_limit')
                value = json.loads(content)
                # Retain failed/incomplete scientific results as well as successes.
                keep_result(row, value, label + '.json')
                passed = value.get('passed') is True or value.get('status') == 'pass'
                if not passed:
                    row['status'], row['error_code'] = 'FAIL', 'scientific_gate_incomplete_or_failed'
            elif json_stdout and row['status'] == 'PASS':
                keep_result(row, json.loads(raw), label + '.json', 65536)
        except (OSError, ValueError, TypeError, UnicodeError):
            row['status'], row['error_code'] = 'FAIL', 'public_receipt_missing_or_invalid'
        report['stages'].append(row); persist()
        print(label + ': ' + row['status'], flush=True)
        return row

    persist()  # Even a killed first stage leaves an explicitly incomplete receipt.
    stage('contracts', ['-S', '-m', 'unittest', 'discover', '-s', 'tests',
                        '-p', 'test_physical_*.py', '-v'], tests=True)
    stage('mechanical-campaign', ['-S', '-m', 'experiments.physical_voice.test_numerical',
          '--raw-dir', str(private / 'fold-raw'), '--output', str(private / 'fold-results')],
          timeout=900, receipt=private / 'fold-results' / 'metrics.json')
    for name in ('filter', 'tract'):
        stage(name + '-campaign', ['-S', '-m', 'experiments.physical_voice.check_' + name,
              '--raw-dir', str(private / (name + '-raw')), '--output', str(private / (name + '-results'))],
              timeout=600, receipt=private / (name + '-results') / 'receipt.json')
    stage('coupled-numerical', ['-S', '-m', 'unittest', 'experiments.physical_voice.test_pipeline_numerical', '-v'],
          timeout=600, tests=True)
    bundle = str(private / 'voice')
    for action in ('demo', 'inspect', 'recheck'):
        flag = '--output' if action == 'demo' else '--bundle'
        stage('stdlib-' + action, ['-S', '-m', 'experiments.physical_voice.demo', action, flag, bundle],
              timeout=360, json_stdout=True)
    if args.with_text_lab:
        state = str(private / 'text-state')
        stage('fresh-text-lab', ['-m', 'experiments.newbrain_text.demo', 'run', '--state', state], timeout=180)
        for name, selection in (('new-observation', []),
                                ('baseline-observation', ['--method', 'baseline', '--split', 'old', '--case-index', '1'])):
            linked = str(private / name)
            stage(name + '-to-voice', ['-S', '-m', 'experiments.physical_voice.demo', 'from-text-lab',
                  '--text-state', state, '--output', linked, *selection], timeout=360, json_stdout=True)
            stage(name + '-cold-recheck', ['-S', '-m', 'experiments.physical_voice.demo', 'recheck',
                  '--bundle', linked], timeout=360, json_stdout=True)
    else:
        report['text_lab_bridge'] = 'NOT_RUN: optional exact numerical environment was not requested'
    if args.aggregate:
        row, _ = run_stage('aggregate', ['scripts/record_upgrade_checks.py', '--output', str(private / 'aggregate')], private, 900)
        row['aggregate'] = compact_aggregate(private)
        if row['aggregate'] is None or not row['aggregate']['success']:
            row['status'], row['error_code'] = 'FAIL', 'aggregate_incomplete_or_failed'
        report['stages'].append(row); persist()
        print('aggregate: ' + row['status'], flush=True)
    report['source_after'] = fingerprints(args.output)
    report['source_unchanged'] = report['source_before'] == report['source_after']
    report['stages'].append({'stage': 'source-stability',
                            'status': 'PASS' if report['source_unchanged'] else 'FAIL'})
    report['completed'] = True
    persist()
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
