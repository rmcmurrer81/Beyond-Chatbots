"""Retain compact original voice-box checks; no playback or private model upload."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
from record_text_learning_checks import canonical, compact_aggregate, fingerprints, run_stage, utc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--aggregate', action='store_true')
    parser.add_argument('--with-text-lab', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'aster.voice-box-checks.v1', 'started_utc': utc(), 'stages': [],
              'runtime': {'python': platform.python_version(), 'platform': sys.platform},
              'source_before': fingerprints(args.output), 'automatic_playback': False,
              'production_brain_enabled': False, 'subjective_listening_test_performed': False,
              'private_model_state_published': False}

    def save():
        report['finished_utc'] = utc()
        report['success'] = bool(report['stages']) and all(r['status'] == 'PASS' for r in report['stages'])
        (args.output / 'result.json').write_bytes(canonical(report))

    with tempfile.TemporaryDirectory(prefix='aster-voice-check-') as tmp:
        private = Path(tmp)
        row, _ = run_stage('voice-contracts', ['-m', 'unittest', 'discover', '-s', 'tests',
                                              '-p', 'test_voice_box.py', '-v'], private, 180)
        if (not row['unittest_summaries'] or row['skipped_count']
                or sum(item['tests'] for item in row['unittest_summaries']) <= 0):
            row['status'], row['error_code'] = 'FAIL', 'actual_unskipped_tests_required'
        report['stages'].append(row); save()
        print('voice-contracts: ' + row['status'], flush=True)

        def demo_stage(label, arguments, retain=True):
            row, raw = run_stage(label, arguments, private, 120)
            if row['status'] == 'PASS':
                try:
                    value = json.loads(raw)
                    # Keep voice receipts, not the model campaign's full report.
                    if retain:
                        encoded = canonical(value)
                        if len(encoded) > 16384 or any(s.encode() in encoded for s in
                                (str(private), 'model_b64', 'state_b64', 'Traceback')):
                            raise ValueError('public_receipt_refused')
                        filename = label + '.json'
                        (args.output / filename).write_bytes(encoded)
                        row['result_file'], row['result_sha256'] = filename, hashlib.sha256(encoded).hexdigest()
                except (ValueError, TypeError, UnicodeError):
                    row['status'], row['error_code'] = 'FAIL', 'public_receipt_invalid'
            report['stages'].append(row); save()
            print(label + ': ' + row['status'], flush=True)

        bundle = str(private / 'voice')
        for action in ('demo', 'inspect', 'recheck'):
            flag = '--output' if action == 'demo' else '--bundle'
            # -S proves ordinary synthesis/inspection work without site packages.
            demo_stage('stdlib-' + action, ['-S', '-m', 'experiments.voice_box.demo', action, flag, bundle])
        if args.with_text_lab:
            state, linked = str(private / 'text-state'), str(private / 'linked-voice')
            demo_stage('fresh-text-lab', ['-m', 'experiments.newbrain_text.demo', 'run', '--state', state], False)
            demo_stage('observed-brain-to-voice', ['-m', 'experiments.voice_box.demo', 'from-text-lab',
                        '--text-state', state, '--output', linked])
            demo_stage('linked-cold-recheck', ['-S', '-m', 'experiments.voice_box.demo', 'recheck', '--bundle', linked])
        else:
            report['text_lab_integration'] = 'NOT_RUN: optional exact numerical environment was not requested'
        if args.aggregate:
            row, _ = run_stage('aggregate', ['scripts/record_upgrade_checks.py', '--output', str(private / 'aggregate')], private, 900)
            row['aggregate'] = compact_aggregate(private)
            if row['aggregate'] is None or not row['aggregate']['success']:
                row['status'], row['error_code'] = 'FAIL', 'aggregate_incomplete_or_failed'
            report['stages'].append(row); save()
            print('aggregate: ' + row['status'], flush=True)
    report['source_after'] = fingerprints(args.output)
    report['source_unchanged'] = report['source_before'] == report['source_after']
    report['stages'].append({'stage': 'source-stability',
                            'status': 'PASS' if report['source_unchanged'] else 'FAIL'})
    save()
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
