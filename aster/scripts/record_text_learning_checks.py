"""Run the opt-in numerical lab and retain compact, path-free Aster outcomes.

Private diagnostic files and synthetic model state remain in temporary storage.
Only bounded result summaries, relative source hashes and numeric outcomes leave
that directory. A scientific goal miss is separate from an engineering failure.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_DIAGNOSTIC = 4 * 1024 * 1024


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def fingerprints(output=None):
    """Hash the full qualification tree without publishing provenance inventories.

    All implementation, dependencies, fixtures, workflows, notices and assets are
    included. Existing receipts, Git internals, caches and this run's output are
    excluded because they are evidence or interpreter products, not inputs.
    """
    output = output.resolve() if output is not None else None
    selected = []
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if (any(part in {'.git', '__pycache__', 'test-results', '.venv'} for part in relative.parts)
                or path.suffix == '.pyc' or path == output or output in path.parents):
            continue
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('qualification_source_symlink')
        if path.is_file():
            raw = path.read_bytes()
            selected.append({'path': relative.as_posix(), 'bytes': len(raw),
                             'sha256': hashlib.sha256(raw).hexdigest()})
    return {'scope': 'Complete repository files except Git, caches, historical receipts and current output',
        'files': len(selected), 'bytes': sum(row['bytes'] for row in selected),
        'sha256': hashlib.sha256(canonical(selected)).hexdigest(),
        'raw_source_inventory_published': False}


def run_stage(label, arguments, private, timeout=180):
    """Fixed local commands, bounded pipe capture, direct-child deadline.

    This is not an OS sandbox or descendant-process resource limit. The fixed
    test/CLI implementations own their child cleanup, with CI's job timeout as
    an additional outer boundary. No arbitrary executable is accepted here.
    """
    started, clock = utc(), time.monotonic()
    log = private / (label + '.log')
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    error, code, child = None, None, None
    buffer = bytearray()
    completed, overflow, read_failed = threading.Event(), threading.Event(), threading.Event()
    reader = None
    try:
        child = subprocess.Popen([sys.executable, '-B', *arguments], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False)
        def receive():
            try:
                while len(buffer) <= MAX_DIAGNOSTIC:
                    block = child.stdout.read(min(8192, MAX_DIAGNOSTIC + 1 - len(buffer)))
                    if not block:
                        break
                    buffer.extend(block)
                if len(buffer) > MAX_DIAGNOSTIC:
                    overflow.set()
            except (OSError, ValueError):
                read_failed.set()
            finally:
                completed.set()
        reader = threading.Thread(target=receive, daemon=True)
        reader.start()
        while not (completed.is_set() and child.poll() is not None):
            if overflow.is_set():
                error = 'diagnostic_size_limit'
                break
            if time.monotonic() - clock >= timeout:
                error = 'deadline_exceeded'
                break
            time.sleep(0.02)
        if overflow.is_set():
            error = 'diagnostic_size_limit'
        if read_failed.is_set():
            error = 'diagnostic_read_failed'
        if error is None:
            code = child.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        error = 'process_unavailable_or_unreaped'
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                error = 'direct_child_unreaped'
        if reader is not None:
            reader.join(timeout=1)
            if reader.is_alive():
                error = 'diagnostic_pipe_not_closed'
        if child is not None and completed.is_set():
            child.stdout.close()
    too_large = overflow.is_set()
    raw = bytes(buffer[:MAX_DIAGNOSTIC])
    log.write_bytes(raw)
    text = raw.decode('utf-8', errors='replace')
    summaries = [{'tests': int(n), 'seconds': float(seconds)}
                 for n, seconds in re.findall(r'Ran (\d+) tests? in ([0-9.]+)s', text)]
    failures = re.findall(r'^(?:FAIL|ERROR): ([A-Za-z0-9_.]+) \(([A-Za-z0-9_.]+)\)', text, re.MULTILINE)
    safe_arguments = [str(value).replace(str(private), '<private>').replace(str(ROOT), '<repository>')
                      for value in arguments]
    return {'stage': label, 'command': ['python', '-B', *safe_arguments],
        'started_utc': started, 'finished_utc': utc(),
        'wall_seconds': round(time.monotonic() - clock, 6), 'exit_code': code,
        'status': 'PASS' if code == 0 and error is None else 'FAIL', 'error_code': error,
        'unittest_summaries': summaries, 'skipped_count': len(re.findall(r' \.\.\. skipped ', text)),
        'failed_test_ids': ['.'.join(reversed(row)) for row in failures],
        'diagnostic_sha256': hashlib.sha256(raw).hexdigest(),
        'diagnostic_digest_is_complete': not too_large and completed.is_set() and not read_failed.is_set(),
        'containment_scope': 'Bounded diagnostics and direct-child deadline; not a descendant-process sandbox',
        'private_diagnostics_published': False}, raw


def compact_aggregate(private):
    try:
        raw = (private / 'aggregate' / 'result.json').read_bytes()
        if len(raw) > 1024 * 1024:
            return None
        result = json.loads(raw)
        return {'success': result['success'], 'stages': [
            {key: stage[key] for key in ('name', 'expected_exit', 'actual_exit', 'status',
                                         'unittest_summaries', 'skipped_count')}
            for stage in result['stages']]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--aggregate', action='store_true')
    args = parser.parse_args()
    output = args.output
    # Evidence is append-only by directory; never replace an earlier attempt.
    output.mkdir(parents=True, exist_ok=False)
    private = Path(tempfile.mkdtemp(prefix='aster-text-check-'))
    report = {'schema': 'aster.newbrain-text.checks.v1', 'started_utc': utc(),
        'runtime': {'python': platform.python_version(), 'implementation': platform.python_implementation(),
                    'platform': sys.platform}, 'stages': [], 'source_before': fingerprints(output),
        'production_backend_enabled': False, 'scientific_success_required_for_engineering_pass': False,
        'scope': 'Synthetic optional lab checks; no user state, device installation or conversational qualification',
        'measurement_scope': 'Whole check-stage elapsed time, not model-only latency or memory peak'}

    def persist():
        report['finished_utc'] = utc()
        report['success'] = all(row['status'] == 'PASS' for row in report['stages'])
        (output / 'result.json').write_bytes(canonical(report))

    if args.aggregate:
        row, _ = run_stage('aggregate', ['scripts/record_upgrade_checks.py', '--output', str(private / 'aggregate')], private, 900)
        summary = compact_aggregate(private)
        row['aggregate'] = summary
        if summary is None or not summary.get('success'):
            row['status'], row['error_code'] = 'FAIL', 'aggregate_incomplete_or_failed'
        report['stages'].append(row)
        persist()
        print('aggregate: ' + row['status'], flush=True)

    for label, arguments in (
        ('contracts', ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_newbrain_text.py', '-v']),
        ('numerical', ['-m', 'unittest', 'experiments.newbrain_text.test_numerical', '-v']),
    ):
        row, _ = run_stage(label, arguments, private)
        if (not row['unittest_summaries'] or sum(v['tests'] for v in row['unittest_summaries']) == 0
                or row['skipped_count']):
            row['status'], row['error_code'] = 'FAIL', 'actual_unskipped_tests_required'
        report['stages'].append(row)
        persist()
        print(label + ': ' + row['status'], flush=True)

    state = private / 'synthetic-state'
    for action in ('run', 'inspect', 'recheck'):
        row, raw = run_stage('demo-' + action, ['-m', 'experiments.newbrain_text.demo', action,
            '--state', str(state), '--owner', 'synthetic_aster_fixture'], private)
        # The demo is required to emit only its path-free public report.
        if row['status'] == 'PASS':
            try:
                value = json.loads(raw)
                encoded = canonical(value)
                forbidden = (str(private), str(ROOT), 'model_b64', 'state_b64', 'raw_hex', 'Traceback')
                if len(encoded) > 512 * 1024 or any(word.encode() in encoded for word in forbidden):
                    raise ValueError('unsafe_public_report')
                (output / (action + '-result.json')).write_bytes(encoded)
                row['result_file'] = action + '-result.json'
                row['result_sha256'] = hashlib.sha256(encoded).hexdigest()
            except (ValueError, TypeError, UnicodeError):
                row['status'], row['error_code'] = 'FAIL', 'public_result_invalid'
        report['stages'].append(row)
        persist()
        print('demo-' + action + ': ' + row['status'], flush=True)

    report['source_after'] = fingerprints(output)
    report['source_unchanged'] = report['source_before'] == report['source_after']
    report['stages'].append({'stage': 'source-stability',
        'status': 'PASS' if report['source_unchanged'] else 'FAIL',
        'error_code': None if report['source_unchanged'] else 'source_changed_during_checks'})
    persist()
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
