"""Retain every browser check outcome against exact owned source bytes.

The --live stage is mandatory when requested: missing dependencies/browsers fail,
never skip. This recorder creates a new evidence directory and never overwrites.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('aster/browser_integration.py', 'aster/browser_fixture.py',
           'tests/test_browser_integration.py', 'tests/test_browser_check_recorder.py',
           'tests/browser_fixture_live.py',
           'scripts/record_browser_checks.py', 'requirements-browser.txt',
           '.github/workflows/browser-fixture.yml', 'docs/BROWSER_INTEGRATION.md')


def _configure_console():
    # CI on Windows can inherit CP1252; official browser installers emit Unicode.
    # This affects console presentation only. Retained log bytes stay unchanged.
    reconfigure = getattr(sys.stdout, 'reconfigure', None)
    if reconfigure is not None:
        reconfigure(encoding='utf-8', errors='backslashreplace')


def main(argv=None):
    _configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--foundation', action='store_true')
    parser.add_argument('--install-runtime', action='store_true',
                        help='Explicit CI/developer opt-in: install official optional runtime and Chromium')
    args = parser.parse_args(argv)
    if args.install_runtime and not args.live:
        parser.error('--install-runtime requires --live')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    utc = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    report = {'schema': 'aster.browser-fixture-checks.v1', 'started_utc': utc(),
              'python': sys.version, 'platform': platform.platform(),
              'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in SOURCES},
              'scope': 'Disposable bundled fixtures only; no live websites, user profile or real account actions.',
              'live_browser_required': args.live, 'stages': []}
    stages = []
    if args.install_runtime:
        stages.append(('install-playwright', [sys.executable, '-m', 'pip', 'install',
                                             '-r', 'requirements-browser.txt']))
        browser_install = [sys.executable, '-m', 'playwright', 'install']
        if sys.platform.startswith('linux'):
            browser_install.append('--with-deps')
        stages.append(('install-chromium', browser_install + ['chromium']))
    stages += [('unit', [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests',
                        '-p', 'test_browser_*.py', '-v'])]
    if args.live:
        stages.append(('live', [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests',
                                '-p', 'browser_fixture_live.py', '-v']))
    if args.foundation:
        stages.append(('foundation', [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v']))
    stages.append(('compile', [sys.executable, '-B', '-m', 'compileall', '-q',
        'aster/browser_integration.py', 'aster/browser_fixture.py',
        'tests/test_browser_integration.py', 'tests/test_browser_check_recorder.py',
        'tests/browser_fixture_live.py', 'scripts/record_browser_checks.py']))
    report.update(expected_stages=[name for name, _ in stages], completed=False,
                  success=False, live_browser_qualified=False)
    (output / 'result.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    for name, command in stages:
        began = time.monotonic()
        try:
            result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=300)
            raw, code = result.stdout, result.returncode
        except subprocess.TimeoutExpired as exc:
            raw, code = (exc.stdout or b'') + b'\nCHECK TIMED OUT after 300 seconds\n', None
        log = raw.decode('utf-8', errors='replace')
        skips = [line for line in log.splitlines() if ' ... skipped ' in line]
        summaries = re.findall(r'Ran (\d+) tests? in [^\n]+', log)
        # A missing test suite or skipped live test is not qualification.
        passed = code == 0 and (name in ('compile', 'install-playwright', 'install-chromium') or (summaries and int(summaries[-1]) > 0))
        if name == 'live' and skips:
            passed = False
        (output / (name + '.log')).write_bytes(raw)
        report['stages'].append({'name': name, 'command': command, 'exit_code': code,
            'status': 'PASS' if passed else 'FAIL', 'wall_seconds': time.monotonic() - began,
            'log': name + '.log', 'log_sha256': hashlib.sha256(raw).hexdigest(),
            'tests_run': int(summaries[-1]) if summaries else None, 'skipped': len(skips)})
        report['updated_utc'] = utc()
        report['completed'] = [stage['name'] for stage in report['stages']] == report['expected_stages']
        report['success'] = report['completed'] and all(stage['status'] == 'PASS' for stage in report['stages'])
        report['live_browser_qualified'] = report['success'] and any(
            stage['name'] == 'live' and stage['status'] == 'PASS' for stage in report['stages'])
        if report['completed']:
            report['finished_utc'] = report['updated_utc']
        (output / 'result.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(name + ': ' + report['stages'][-1]['status'], flush=True)
        print(log, flush=True)
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
