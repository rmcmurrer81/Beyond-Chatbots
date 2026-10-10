"""Retain bounded synthetic observations and all failures; exclude model states."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.record_text_learning_checks import (canonical, compact_aggregate, fingerprints, run_stage, utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--aggregate', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = Path(tempfile.mkdtemp(prefix='aster-retention-check-'))
    report = {'schema': 'aster.retention.checks.v1', 'started_utc': utc(), 'stages': [],
              'source_before': fingerprints(output), 'production_backend_enabled': False,
              'scientific_success_required_for_engineering_pass': False,
              'state_files_published': False, 'completed': False}
    required = {'contracts', 'numerical', 'frozen-study', 'cold-restore', 'source-stability'}
    if args.aggregate:
        required.add('aggregate')

    def persist():
        report['finished_utc'] = utc()
        report['success'] = (report['completed'] and required == {s['stage'] for s in report['stages']}
                             and all(s['status'] == 'PASS' for s in report['stages']))
        (output / 'result.json').write_bytes(canonical(report))

    def stage(label, command, timeout=180):
        result, _ = run_stage(label, command, private, timeout)
        report['stages'].append(result)
        persist()
        print(label + ': ' + result['status'], flush=True)
        return result

    if args.aggregate:
        result = stage('aggregate', ['scripts/record_upgrade_checks.py', '--output', str(private / 'aggregate')], 900)
        result['aggregate'] = compact_aggregate(private)
        if result['aggregate'] is None or not result['aggregate']['success']:
            result['status'], result['error_code'] = 'FAIL', 'aggregate_failed_or_incomplete'
        persist()

    for name, command in (
        ('contracts', ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_newbrain_retention.py', '-v']),
        ('numerical', ['-m', 'unittest', 'experiments.newbrain_retention.test_numerical', 'experiments.newbrain_text.test_numerical', '-v']),
    ):
        result = stage(name, command)
        if not result['unittest_summaries'] or sum(r['tests'] for r in result['unittest_summaries']) == 0 or result['skipped_count']:
            result['status'], result['error_code'] = 'FAIL', 'actual_unskipped_tests_required'
        persist()

    # Do not run a scientific campaign after an engineering prerequisite failed.
    if all(row['status'] == 'PASS' for row in report['stages']):
        state = private / 'study'
        result = stage('frozen-study', ['-m', 'experiments.newbrain_retention.study', '--output', str(state)], 180)
        for source_name, output_name in (('freeze.json', 'freeze.json'), ('report.json', 'study.json')):
            path = state / source_name
            if path.is_file():
                raw = path.read_bytes()
                if len(raw) > 4 * 1024 * 1024 or any(value.encode() in raw for value in ('model_b64', str(private), str(ROOT), 'Traceback')):
                    result['status'], result['error_code'] = 'FAIL', 'unsafe_or_oversize_report'
                else:
                    value = json.loads(raw)
                    (output / output_name).write_bytes(canonical(value))
        persist()
        if result['status'] == 'PASS':
            cold = private / 'cold.json'
            result = stage('cold-restore', ['-m', 'experiments.newbrain_retention.cold_check', '--state', str(state), '--output', str(cold)], 30)
            if result['status'] == 'PASS':
                raw = cold.read_bytes()
                value = json.loads(raw)
                if value.get('passed') is not True or value.get('restored_models') != 20:
                    result['status'], result['error_code'] = 'FAIL', 'cold_restore_incomplete'
                else:
                    (output / 'cold.json').write_bytes(canonical(value))
            persist()
    report['source_after'] = fingerprints(output)
    stable = report['source_before'] == report['source_after']
    report['stages'].append({'stage': 'source-stability', 'status': 'PASS' if stable else 'FAIL'})
    report['completed'] = True
    persist()
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
