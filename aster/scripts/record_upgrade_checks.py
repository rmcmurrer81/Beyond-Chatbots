"""Retain complete local/CI upgrade checks without rewriting earlier run evidence.

No model download, user state, deployment or credentials are involved. Test
source fingerprints exclude only previous results and interpreter caches.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def source_manifest(root, output=None):
    """Fingerprint Aster-owned implementation/test tools, never state or inventories.

This controls evidence disclosure only. All component, voice, candidate and
companion validation stages below still run unchanged against the full checkout.
"""
    allowed_roots = {'aster', 'aster_provider', 'tests', 'scripts', 'remote-companion', 'android-companion', '.github'}
    allowed_extensions = {'.py', '.js', '.java', '.kt', '.html', '.css', '.gradle', '.xml', '.yml', '.yaml', '.cmd', '.bat', '.ps1', '.cjs', '.kts', '.sh'}
    source = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if (not path.is_file() or any(p in {'.git', '__pycache__', 'test-results', '.venv'} for p in relative.parts)
                or (relative.parts[0] not in allowed_roots and relative.as_posix() != 'launch_aster.py')
                or path.suffix not in allowed_extensions or output == path or output in path.parents):
            continue
        data = path.read_bytes()
        source[relative.as_posix()] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return source


def compact_stage_report(name, value):
    """Publish Aster outcomes, omitting separate-source provenance inventories."""
    if type(value) is not dict:
        raise ValueError('Expected an outcome object')
    common = {'schema': 'aster.compact-stage-outcome.v1', 'stage': name,
              'redacted': True, 'detail_scope': 'Aster outcomes only; full provenance retained locally'}
    keys = ({'tests_run', 'errors', 'failures', 'skipped', 'success', 'recorded_utc',
             'started_utc', 'suite_wall_seconds', 'conversation_qualified',
             'scientific_learning_gain_claimed'} if name == 'components' else
            {'status', 'recorded_utc', 'candidate_code_executed',
             'production_backend_activated', 'runtime_compatible',
             'scientific_learning_gain_claimed'})
    common.update({key: value[key] for key in keys if key in value})
    return common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing evidence is refused')
    parser.add_argument('--components-only', action='store_true',
                        help='Run the unchanged dedicated component suite with compact evidence')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Kept outside the published/Actions output directory. Nothing uploads this
    # private diagnostic directory or logs its full provenance-bearing contents.
    private_output = Path(tempfile.mkdtemp(prefix='aster-private-check-evidence-'))
    source = source_manifest(ROOT, output)
    source_raw = (json.dumps(source, indent=2, sort_keys=True) + '\n').encode()
    (output / 'source-manifest.json').write_bytes(source_raw)
    stages = [
        ('foundation', [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'], 0),
        ('components', [sys.executable, '-B', '-m', 'experiments.newbrain_adapter.run_checks',
                        '--report', str(private_output / 'component-result.json')], 0),
        ('candidate-admission', [sys.executable, '-B', '-m', 'experiments.newbrain_candidate.audit',
                                 '--report', str(private_output / 'candidate-admission.json')], 2),
        ('hearing-compatibility', [sys.executable, '-B', '-m', 'experiments.newbrain_hearing.checks',
                                   '--output', str(output / 'hearing')], 0),
        ('companions', [sys.executable, '-B', 'scripts/check_companions.py'], 0),
        ('compile', [sys.executable, '-B', '-m', 'compileall', '-q', 'aster', 'aster_provider', 'tests', 'scripts',
                     'experiments/newbrain_adapter', 'experiments/newbrain_candidate',
                     'experiments/newbrain_hearing', 'launch_aster.py'], 0),
    ]
    if args.components_only:
        stages = [stage for stage in stages if stage[0] == 'components']
    report = {'schema': 'aster.upgrade-checks.v1', 'started_utc': utc(),
              'environment': {'python': sys.version, 'platform': platform.platform(),
                              'executable': sys.executable, 'display': os.environ.get('DISPLAY'),
                              'os_name': os.name},
              'source_manifest_sha256': hashlib.sha256(source_raw).hexdigest(), 'stages': [],
              'source_manifest_scope': 'Aster-owned implementation, tests, tools and workflow code only; vendor, assets, documents and runtime inventories omitted',
              'component_detail_scope': 'Compact outcomes published; raw diagnostics remain local only, not durable after ephemeral CI runner disposal',
              'scope': 'Cloud/CI engineering fixtures. No physical phone, deployment, production brain or user workstation test.',
              'scientific_learning_gain_claimed': False}
    for name, command, expected in stages:
        began, started = utc(), time.monotonic()
        try:
            completed = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, timeout=300)
            raw, code, error = completed.stdout, completed.returncode, None
        except subprocess.TimeoutExpired as exc:
            raw, code, error = exc.stdout or b'', None, 'TimeoutExpired after 300 seconds'
        text = raw.decode('utf-8', errors='replace')
        summaries = re.findall(r'Ran \d+ tests? in [^\n]+', text)
        skips = [line for line in text.splitlines() if ' ... skipped ' in line]
        redacted = name in {'components', 'candidate-admission'}
        evidence_error = None
        if redacted:
            (private_output / (name + '.log')).write_bytes(raw)
            filename = 'component-result.json' if name == 'components' else 'candidate-admission.json'
            detail = output / filename
            private_detail = private_output / filename
            compact = {'schema': 'aster.compact-stage-outcome.v1', 'stage': name,
                       'redacted': True, 'detail_available': False}
            try:
                full = private_detail.read_bytes()
                compact = compact_stage_report(name, json.loads(full))
            except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
                evidence_error = type(exc).__name__
                compact['evidence_error'] = evidence_error
            detail.write_text(json.dumps(compact, indent=2, sort_keys=True)+'\n', encoding='utf-8')
            published = {'stage': name, 'actual_exit': code, 'expected_exit': expected,
                         'status': 'PASS' if code == expected and evidence_error is None else 'FAIL', 'error': error,
                         'evidence_error': evidence_error,
                         'unittest_summaries': summaries, 'skipped_count': len(skips),
                         'redacted': True, 'full_diagnostics_retained_locally': True,
                         'outcome': compact}
            raw = (json.dumps(published, indent=2, sort_keys=True)+'\n').encode()
            text = raw.decode()
        log = output / (name + '.log')
        log.write_bytes(raw)
        result = {'name': name, 'command': command, 'cwd': str(ROOT), 'started_utc': began,
                  'finished_utc': utc(), 'wall_seconds': time.monotonic() - started,
                  'expected_exit': expected, 'actual_exit': code, 'error': error,
                  'status': 'PASS' if code == expected and evidence_error is None else 'FAIL', 'log': log.name,
                  'evidence_error': evidence_error,
                  'log_sha256': hashlib.sha256(raw).hexdigest(),
                  'unittest_summaries': summaries,
                  'skip_lines': skips if not redacted else [], 'skipped_count': len(skips),
                  'published_log_redacted': redacted,
                  'note': 'Expected refusal, not runtime qualification' if expected == 2 else None}
        report['stages'].append(result)
        report['finished_utc'] = utc()
        report['success'] = all(r['status'] == 'PASS' for r in report['stages'])
        (output / 'result.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(name + ': ' + result['status'] + ' exit=' + str(code), flush=True)
        # Print exactly the permitted artifact log, never hidden raw diagnostics.
        print(text, flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
