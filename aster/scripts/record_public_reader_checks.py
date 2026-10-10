"""Record compact, immutable public-reader qualification outcomes, never raw logs.

Each invocation requires a NEW output directory. Append-only JSON checkpoints
keep the pending plan and every attempted stage; result.json is created once.
An interrupted process therefore cannot leave a false successful result.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
ORDER = ('recorder', 'unit', 'session', 'controller', 'fixtures', 'native-ui', 'public-smoke', 'foundation')
DEFAULT_STAGES = ('recorder', 'unit', 'session', 'controller', 'fixtures')
SUITES = {
    'recorder': (('test_public_reader_recorder.py', None),),
    'unit': (('test_public_transport.py', ('PublicURLTests', 'PinnedConnectionTests', 'ResponsePolicyTests', 'ExtractionTests', 'TLSFixturePortabilityTests')),),
    'session': (('test_browser_public.py', ('PublicSupervisorTests', 'PublicReaderSessionTests')),),
    'controller': (('test_browser_public.py', ('PublicControllerTests', 'PublicCLITests')),) ,
    'fixtures': (('test_public_transport.py', ('LocalWireFixtureTests', 'LocalTLSFixtureTests')),) ,
    'native-ui': (('test_browser_public.py', ('PublicNativeUITests',)),),
    'foundation': (('test*.py', None),),
}
REQUIRED_FIXTURES = (
    'test_real_loopback_endpoint_via_test_only_numeric_socket_mapping',
    'test_real_tls_success_checks_hostname_sni_and_body',
    'test_real_tls_untrusted_ca_sends_no_http',
    'test_real_tls_wrong_hostname_sends_no_http',
)
FIXTURE_DIAGNOSTIC_IDS = frozenset('test_public_transport.LocalTLSFixtureTests.' + method
    for method in REQUIRED_FIXTURES if method.startswith('test_real_tls_'))
FIXTURE_ENUMS = {
    'client_verification': frozenset(('none', 'certificate_verification_failed', 'unexpected_client_failure')),
    'server_abort': frozenset(('none', 'tls_failed', 'peer_reset', 'peer_aborted', 'unexpected_os_error')),
}


SOURCES = ('aster/public_transport.py', 'aster/public_worker.py', 'aster/browser_public.py',
    'aster/browser_actions.py', 'aster/dashboard.py', 'aster/desktop.py',
    'tests/test_public_transport.py', 'tests/test_browser_public.py',
    'tests/test_public_reader_recorder.py', 'scripts/public_reader_smoke.py',
    'scripts/record_public_reader_checks.py', '.github/workflows/public-reader.yml',
    'tests/fixtures/public_transport/ca.pem', 'tests/fixtures/public_transport/server.pem',
    'tests/fixtures/public_transport/server-key.pem')
STATIC_REASONS = frozenset(('ok', 'test_failure', 'test_error', 'test_skipped',
    'expected_failure', 'unexpected_success', 'empty_suite', 'missing_suite',
    'missing_required_class', 'missing_required_fixture', 'incomplete_suite',
    'stage_timeout', 'stage_interrupted', 'stage_exception', 'invalid_stage_result',
    'stage_process_failed', 'prerequisite_failed', 'source_missing', 'source_changed', 'smoke_failed'))
COUNTS = ('collected', 'run', 'passed', 'skipped', 'failures', 'errors')
MAX_DETAILS = 20
MAX_RESULT_BYTES = 128 * 1024
STAGE_TIMEOUT = 300


class SilentOutput(io.TextIOBase):
    """Discard test prints in memory; never create raw diagnostic files."""
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def _configure_console():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            reconfigure(encoding='utf-8', errors='backslashreplace')


def _safe_test_id(test):
    # Never call test.id()/str(test): subtests can include URLs, state or secrets.
    module, name = type(test).__module__, type(test).__name__
    method = getattr(test, '_testMethodName', '')
    value = '.'.join((module, name, method))
    if re.fullmatch(r'test[A-Za-z0-9_]*\.[A-Za-z0-9_]+\.test[A-Za-z0-9_]+', value) and len(value) <= 200:
        return value
    return 'unidentified_test'


def _compact_fixture_diagnostics(value):
    # Supplementary observations only: no exception text, addresses or state.
    if type(value) is not dict or type(value.get('http_received')) is not bool:
        return None
    result = {'http_received': value['http_received']}
    for key, allowed in FIXTURE_ENUMS.items():
        field = value.get(key)
        if type(field) is not str or field not in allowed:
            return None
        result[key] = field
    return result


class CompactResult(unittest.TestResult):
    """Count outcomes without constructing or retaining tracebacks/reasons."""
    def __init__(self, capture_fixture_diagnostics=False):
        super().__init__()
        self.capture_fixture_diagnostics = capture_fixture_diagnostics
        self.fixture_outcomes = []
        self.passed = self.failure_count = self.error_count = self.skip_count = 0
        self.details = []

    def _note(self, test, reason):
        if len(self.details) < MAX_DETAILS:
            self.details.append({'test_id': _safe_test_id(test), 'reason': reason})

    def addSuccess(self, test):
        self.passed += 1

    def addFailure(self, test, err):
        self.failure_count += 1
        self._note(test, 'test_failure')

    def addError(self, test, err):
        self.error_count += 1
        self._note(test, 'test_error')

    def addSkip(self, test, reason):
        self.skip_count += 1
        self._note(test, 'test_skipped')

    def addExpectedFailure(self, test, err):
        self.skip_count += 1
        self._note(test, 'expected_failure')

    def addUnexpectedSuccess(self, test):
        self.failure_count += 1
        self._note(test, 'unexpected_success')

    def addSubTest(self, test, subtest, err):
        if err is not None:
            if issubclass(err[0], test.failureException):
                self.addFailure(test, err)
            else:
                self.addError(test, err)

    def stopTest(self, test):
        super().stopTest(test)
        test_id = _safe_test_id(test)
        if (self.capture_fixture_diagnostics and test_id in FIXTURE_DIAGNOSTIC_IDS
                and len(self.fixture_outcomes) < len(FIXTURE_DIAGNOSTIC_IDS)):
            diagnostics = _compact_fixture_diagnostics(getattr(test, 'fixture_diagnostics', None))
            if diagnostics is not None:
                self.fixture_outcomes.append({'test_id': test_id, 'diagnostics': diagnostics})

    def wasSuccessful(self):
        return self.failure_count == 0 and self.error_count == 0


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def _empty_stage(name, reason, completed=False):
    return {'name': name, 'completed': completed, 'success': False,
            'reason': reason, 'tests': dict.fromkeys(COUNTS, 0), 'details': []}


def _load_suite(name):
    tests = []
    for pattern, classes in SUITES[name]:
        if not tuple((ROOT / 'tests').glob(pattern)):
            return None, 'missing_suite'
        loader = unittest.TestLoader()
        loaded = list(_flatten(loader.discover(str(ROOT / 'tests'), pattern=pattern)))
        if loader.errors:
            return None, 'missing_suite'
        if classes:
            for cls in classes:
                selected = [test for test in loaded if type(test).__name__ == cls]
                if not selected:
                    return None, 'missing_required_class'
                tests.extend(selected)
        else:
            tests.extend(loaded)
    if name == 'fixtures' and not set(REQUIRED_FIXTURES).issubset(
            {getattr(test, '_testMethodName', '') for test in tests}):
        return None, 'missing_required_fixture'
    return unittest.TestSuite(tests), None


def _run_unit_stage(name):
    with contextlib.redirect_stdout(SilentOutput()), contextlib.redirect_stderr(SilentOutput()):
        suite, problem = _load_suite(name)
        if problem:
            return _empty_stage(name, problem, completed=True)
        count = suite.countTestCases()
        if not count:
            return _empty_stage(name, 'empty_suite', completed=True)
        result = CompactResult(capture_fixture_diagnostics=name in ('fixtures', 'foundation'))
        interrupted = False
        try:
            suite.run(result)
        except (KeyboardInterrupt, SystemExit):
            interrupted = True
        except Exception:
            return _empty_stage(name, 'stage_exception')
    completed = not interrupted and result.testsRun == count
    success = (completed and result.wasSuccessful() and result.passed > 0
               and (name == 'foundation' or result.skip_count == 0))
    reason = ('stage_interrupted' if interrupted else 'incomplete_suite' if not completed
        else 'test_error' if result.error_count else 'test_failure' if result.failure_count
        else 'test_skipped' if result.skip_count and name != 'foundation' else 'ok')
    stage = {'name': name, 'completed': completed, 'success': success, 'reason': reason,
        'tests': {'collected': count, 'run': result.testsRun, 'passed': result.passed,
            'skipped': result.skip_count, 'failures': result.failure_count, 'errors': result.error_count},
        'details': result.details}
    if result.fixture_outcomes:
        stage['fixture_outcomes'] = result.fixture_outcomes
    return stage


def _run_child_stage(name):
    if name != 'public-smoke':
        return _run_unit_stage(name)
    from scripts.public_reader_smoke import run_smoke, SMOKE_URLS
    with contextlib.redirect_stdout(SilentOutput()), contextlib.redirect_stderr(SilentOutput()):
        smoke = run_smoke()
    success = len(smoke) == len(SMOKE_URLS) and all(item['success'] for item in smoke)
    result = _empty_stage(name, 'ok' if success else 'smoke_failed', completed=True)
    result.update(success=success, smoke=smoke)
    return result


def _clean_stage(name, value):
    """Validate the child protocol then rebuild an allowlisted compact object."""
    if type(value) is not dict or value.get('name') != name:
        return _empty_stage(name, 'invalid_stage_result')
    tests = value.get('tests')
    if (type(tests) is not dict or set(tests) != set(COUNTS)
            or any(type(v) is not int or not 0 <= v <= 1000000 for v in tests.values())
            or type(value.get('completed')) is not bool or type(value.get('success')) is not bool
            or type(value.get('reason')) is not str or value['reason'] not in STATIC_REASONS):
        return _empty_stage(name, 'invalid_stage_result')
    result = _empty_stage(name, value['reason'], completed=value['completed'])
    result['tests'] = dict(tests)
    details = value.get('details', [])
    if type(details) is list:
        for detail in details[:MAX_DETAILS]:
            if type(detail) is not dict:
                continue
            test_id = detail.get('test_id')
            if (type(test_id) is not str or len(test_id) > 200
                    or not re.fullmatch(r'test[A-Za-z0-9_]*\.[A-Za-z0-9_]+\.test[A-Za-z0-9_]+', test_id)):
                test_id = 'unidentified_test'
            reason = detail.get('reason')
            result['details'].append({'test_id': test_id,
                'reason': reason if type(reason) is str and reason in STATIC_REASONS else 'test_error'})
    fixture_outcomes = value.get('fixture_outcomes')
    if name in ('fixtures', 'foundation') and type(fixture_outcomes) is list:
        retained = {}
        for item in fixture_outcomes[:MAX_DETAILS]:
            if type(item) is not dict:
                continue
            test_id = item.get('test_id')
            if type(test_id) is not str or test_id not in FIXTURE_DIAGNOSTIC_IDS:
                continue
            diagnostics = _compact_fixture_diagnostics(item.get('diagnostics'))
            if diagnostics is not None:
                retained[test_id] = {'test_id': test_id, 'diagnostics': diagnostics}
        if retained:
            result['fixture_outcomes'] = list(retained.values())
    success = (value['success'] and result['completed'] and value['reason'] == 'ok'
               and tests['failures'] == 0 and tests['errors'] == 0)
    if name == 'public-smoke':
        from scripts.public_reader_smoke import SMOKE_URLS, REASONS
        smoke = value.get('smoke')
        if any(tests.values()):
            return _empty_stage(name, 'invalid_stage_result')
        if smoke is None and not value['success'] and value['reason'] != 'ok':
            return result
        if type(smoke) is not list or len(smoke) != len(SMOKE_URLS):
            return _empty_stage(name, 'invalid_stage_result')
        result['smoke'] = []
        for url, item in zip(SMOKE_URLS, smoke):
            if (type(item) is not dict or item.get('source_url') != url
                    or item.get('status') not in ('read', 'redirect', 'unsupported', 'failed')
                    or type(item.get('reason')) is not str or item['reason'] not in REASONS):
                return _empty_stage(name, 'invalid_stage_result')
            entry = {key: item[key] for key in ('source_url', 'status', 'reason')}
            for key, limit in (('title_characters', 256), ('text_characters', 12000), ('link_count', 32)):
                val = item.get(key)
                if type(val) is not int or not 0 <= val <= limit:
                    return _empty_stage(name, 'invalid_stage_result')
                entry[key] = val
            status, digest = item.get('http_status'), item.get('body_sha256')
            if status is not None and (type(status) is not int or not 100 <= status <= 599):
                return _empty_stage(name, 'invalid_stage_result')
            if digest is not None and (type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest)):
                return _empty_stage(name, 'invalid_stage_result')
            truncated = item.get('truncated')
            if (type(truncated) is not dict or set(truncated) != {'body', 'title', 'text', 'links'}
                    or any(type(v) is not bool for v in truncated.values())):
                return _empty_stage(name, 'invalid_stage_result')
            entry.update(http_status=status, body_sha256=digest, truncated=dict(truncated),
                         tls_verified=item.get('tls_verified') is True)
            entry['success'] = (item.get('success') is True and entry['status'] == 'read'
                and entry['reason'] == 'ok' and status == 200 and digest is not None
                and entry['tls_verified'] and entry['title_characters'] > 0
                and entry['text_characters'] > 0 and not truncated['body'])
            result['smoke'].append(entry)
        success = success and all(item['success'] for item in result['smoke'])
    else:
        success = (success and tests['collected'] > 0 and tests['run'] == tests['collected']
            and tests['passed'] > 0 and tests['passed'] + tests['skipped'] == tests['run']
            and (name == 'foundation' or tests['skipped'] == 0))
    result['success'] = bool(success)
    if value['success'] and not success and result['reason'] == 'ok':
        result['reason'] = 'invalid_stage_result'
    return result


def _run_stage(name):
    try:
        run = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child-stage', name],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=60 if name == 'public-smoke' else STAGE_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return _empty_stage(name, 'stage_timeout')
    except (KeyboardInterrupt, SystemExit):
        return _empty_stage(name, 'stage_interrupted')
    except Exception:
        return _empty_stage(name, 'stage_exception')
    if len(run.stdout) > MAX_RESULT_BYTES:
        return _empty_stage(name, 'invalid_stage_result')
    try:
        result = _clean_stage(name, json.loads(run.stdout.decode('utf-8')))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return _empty_stage(name, 'invalid_stage_result')
    if run.returncode != 0:
        result.update(success=False, reason='stage_process_failed')
    return result


def _source_hashes():
    result = {}
    for name in SOURCES:
        try:
            path = ROOT / name
            if path.is_file() and not path.is_symlink():
                result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    return result


def _write_new(path, report):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
        stream.write('\n')


def _report(expected):
    os_name = platform.system()
    python_version = platform.python_version()
    hashes = _source_hashes()
    return {'schema': 'aster.public-reader-checks.v1',
        'environment': {'python': python_version if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', python_version) else 'unknown',
            'os': os_name if os_name in ('Windows', 'Linux', 'Darwin') else 'Other'},
        'source_sha256': hashes, 'source_status': 'ok' if len(hashes) == len(SOURCES) else 'source_missing',
        'expected_stages': expected,
        'stages': [], 'completed': False, 'success': False,
        'public_smoke_qualified': False}


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'qualification: FAIL invalid_arguments\n')


def main(argv=None):
    _configure_console()
    parser = QuietParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', action='append', choices=ORDER,
                        help='Select stages; omitted means recorder, unit, session, controller and fixtures')
    parser.add_argument('--native-ui', action='store_true')
    parser.add_argument('--public-smoke', action='store_true')
    parser.add_argument('--foundation', action='store_true')
    args = parser.parse_args(argv)
    selected = set(args.stage or DEFAULT_STAGES)
    for flag, name in ((args.native_ui, 'native-ui'), (args.public_smoke, 'public-smoke'), (args.foundation, 'foundation')):
        if flag:
            selected.add(name)
    expected = [name for name in ORDER if name in selected]
    # Never follow an existing result-directory symlink or reuse evidence.
    try:
        args.output.mkdir(parents=True, exist_ok=False)
    except OSError:
        print('qualification: FAIL output_unavailable', flush=True)
        return 1
    try:
        report = _report(expected)
        _write_new(args.output / '000-pending.json', report)
        for index, name in enumerate(expected, 1):
            try:
                stage = (_empty_stage(name, 'prerequisite_failed', completed=True)
                    if name == 'public-smoke' and any(not row['success'] for row in report['stages'])
                    else _clean_stage(name, _run_stage(name)))
            except (KeyboardInterrupt, SystemExit):
                stage = _empty_stage(name, 'stage_interrupted')
            except Exception:
                stage = _empty_stage(name, 'stage_exception')
            report['stages'].append(stage)
            # Checkpoints are always pending until the final report is created.
            _write_new(args.output / ('%03d-%s.json' % (index, name)), report)
            print(name + ': ' + ('PASS' if stage['success'] else 'FAIL') + ' ' + stage['reason'], flush=True)
            if stage['reason'] == 'stage_interrupted':
                break
        report['completed'] = (len(report['stages']) == len(expected)
            and all(row['completed'] for row in report['stages']))
        if _source_hashes() != report['source_sha256']:
            report['source_status'] = 'source_changed'
        report['success'] = (report['completed'] and report['source_status'] == 'ok'
            and all(row['success'] for row in report['stages']))
        report['public_smoke_qualified'] = report['success'] and any(
            row['name'] == 'public-smoke' and row['success'] for row in report['stages'])
        _write_new(args.output / 'result.json', report)
    except (KeyboardInterrupt, SystemExit, Exception):
        # The immutable pending checkpoints remain fail-closed on I/O/console interruption.
        return 1
    return 0 if report['success'] else 1


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    if len(sys.argv) == 3 and sys.argv[1] == '--child-stage' and sys.argv[2] in ORDER:
        try:
            child_result = _run_child_stage(sys.argv[2])
        except (KeyboardInterrupt, SystemExit):
            child_result = _empty_stage(sys.argv[2], 'stage_interrupted')
        except Exception:
            child_result = _empty_stage(sys.argv[2], 'stage_exception')
        sys.stdout.write(json.dumps(child_result, ensure_ascii=True, separators=(',', ':')) + '\n')
        raise SystemExit(0)
    raise SystemExit(main())
