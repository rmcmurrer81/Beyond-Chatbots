"""Portable compact-evidence regressions; no public network or user state."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import public_reader_smoke as smoke
from scripts import record_public_reader_checks as recorder


class PublicReaderRecorderTests(unittest.TestCase):
    def stage(self, name='unit', **changes):
        result = {'name': name, 'completed': True, 'success': True, 'reason': 'ok',
            'tests': {'collected': 2, 'run': 2, 'passed': 2, 'skipped': 0, 'failures': 0, 'errors': 0},
            'details': []}
        result.update(changes)
        return result

    def snapshot(self, url):
        return {'source_url': url, 'status': 'read', 'reason': 'ok', 'http_status': 200,
            'title': 'Fixture \U0001f30e', 'text': 'Neutral documentation text', 'links': [],
            'body_sha256': 'a' * 64, 'tls_verified': True,
            'truncated': dict.fromkeys(('body', 'title', 'text', 'links'), False)}

    def test_empty_suite_fails(self):
        with patch.object(recorder, '_load_suite', return_value=(unittest.TestSuite(), None)):
            result = recorder._run_unit_stage('unit')
        self.assertFalse(result['success'])
        self.assertEqual(result['reason'], 'empty_suite')
        self.assertEqual(result['tests']['collected'], 0)

    def test_missing_suite_fails(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, 'ROOT', Path(temp)):
            suite, reason = recorder._load_suite('unit')
        self.assertIsNone(suite)
        self.assertEqual(reason, 'missing_suite')

    def test_missing_required_class_fails(self):
        suite = unittest.TestSuite([unittest.FunctionTestCase(lambda: None)])
        with patch.object(unittest.TestLoader, 'discover', return_value=suite):
            loaded, reason = recorder._load_suite('unit')
        self.assertIsNone(loaded)
        self.assertEqual(reason, 'missing_required_class')

    def test_missing_required_real_tls_fixture_fails(self):
        with patch.object(recorder, 'REQUIRED_FIXTURES', ('test_nonexistent_required_fixture',)):
            suite, reason = recorder._load_suite('fixtures')
        self.assertIsNone(suite)
        self.assertEqual(reason, 'missing_required_fixture')

    def test_skipped_required_stage_fails(self):
        def skip():
            raise unittest.SkipTest('private reason /home/fixture SECRET')
        suite = unittest.TestSuite([unittest.FunctionTestCase(skip)])
        with patch.object(recorder, '_load_suite', return_value=(suite, None)):
            result = recorder._run_unit_stage('native-ui')
        self.assertFalse(result['success'])
        self.assertEqual(result['tests']['skipped'], 1)
        self.assertEqual(result['reason'], 'test_skipped')
        self.assertNotIn('SECRET', json.dumps(result))

    def test_failure_and_error_never_retain_exception_or_output(self):
        def fail():
            print('SECRET title body /home/fixture/private')
            raise AssertionError('SECRET assertion data')
        def error():
            raise ValueError('SECRET exception data')
        suite = unittest.TestSuite([unittest.FunctionTestCase(fail), unittest.FunctionTestCase(error)])
        output = io.StringIO()
        with patch.object(recorder, '_load_suite', return_value=(suite, None)), patch.object(recorder.sys, 'stdout', output):
            result = recorder._run_unit_stage('unit')
        self.assertFalse(result['success'])
        self.assertEqual(result['tests']['failures'], 1)
        self.assertEqual(result['tests']['errors'], 1)
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('/home/', json.dumps(result))

    def test_subtest_parameters_are_never_used_as_test_ids(self):
        class SubTests(unittest.TestCase):
            def test_subtest(self):
                with self.subTest(value='SECRET /private/state?token=secret'):
                    self.fail('SECRET')
        suite = unittest.TestSuite([SubTests('test_subtest')])
        with patch.object(recorder, '_load_suite', return_value=(suite, None)):
            result = recorder._run_unit_stage('unit')
        self.assertEqual(result['tests']['failures'], 1)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('token=', json.dumps(result))

    def test_failure_details_are_bounded(self):
        result = recorder.CompactResult()
        case = unittest.FunctionTestCase(lambda: None)
        for _ in range(100):
            result.addFailure(case, (AssertionError, AssertionError('SECRET'), None))
        self.assertEqual(result.failure_count, 100)
        self.assertEqual(len(result.details), recorder.MAX_DETAILS)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])

    def test_interrupted_suite_is_never_successful(self):
        def interrupt():
            raise KeyboardInterrupt('SECRET')
        suite = unittest.TestSuite([unittest.FunctionTestCase(interrupt)])
        with patch.object(recorder, '_load_suite', return_value=(suite, None)):
            result = recorder._run_unit_stage('unit')
        self.assertFalse(result['completed'])
        self.assertFalse(result['success'])
        self.assertEqual(result['reason'], 'stage_interrupted')

    def test_sanitizer_drops_raw_state_paths_environment_and_provenance(self):
        dirty = self.stage()
        dirty.update(stdout='SECRET', traceback='/home/user', environment={'token': 'SECRET'},
                     title='SECRET', command=['/private/python'], upstream_provenance='SECRET')
        dirty['details'] = [{'test_id': '/private/state?token=SECRET', 'reason': 'SECRET', 'raw': 'SECRET'}]
        result = recorder._clean_stage('unit', dirty)
        encoded = json.dumps(result)
        for forbidden in ('SECRET', '/private', '/home', 'stdout', 'traceback', 'environment', 'command', 'upstream'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(result['details'], [{'test_id': 'unidentified_test', 'reason': 'test_error'}])

    def test_invalid_success_counts_fail_closed(self):
        for changes in ({'collected': 0, 'run': 0, 'passed': 0}, {'run': 1}, {'skipped': 1},
                        {'failures': 1}, {'errors': 1}, {'passed': 1}, {'collected': True}):
            with self.subTest(changes=changes):
                value = self.stage()
                value['tests'].update(changes)
                self.assertFalse(recorder._clean_stage('unit', value)['success'])

    def test_partial_child_cannot_claim_success(self):
        result = recorder._clean_stage('unit', self.stage(completed=False))
        self.assertFalse(result['success'])

    def test_timeout_and_process_failure_have_static_reasons(self):
        with patch.object(recorder.subprocess, 'run', side_effect=subprocess.TimeoutExpired('/private/SECRET', 3, output=b'SECRET')):
            result = recorder._run_stage('unit')
        self.assertEqual(result['reason'], 'stage_timeout')
        failed = SimpleNamespace(stdout=json.dumps(self.stage()).encode(), returncode=1)
        with patch.object(recorder.subprocess, 'run', return_value=failed):
            result = recorder._run_stage('unit')
        self.assertFalse(result['success'])
        self.assertEqual(result['reason'], 'stage_process_failed')

    def test_smoke_timeout_keeps_static_failure_reason_without_results(self):
        value = recorder._empty_stage('public-smoke', 'stage_timeout')
        result = recorder._clean_stage('public-smoke', value)
        self.assertFalse(result['success'])
        self.assertFalse(result['completed'])
        self.assertEqual(result['reason'], 'stage_timeout')

    def test_raw_invalid_child_output_is_not_printed_or_retained(self):
        for raw in (b'SECRET raw traceback /home/person', b'x' * (recorder.MAX_RESULT_BYTES + 1)):
            with self.subTest(size=len(raw)), patch.object(recorder.subprocess, 'run', return_value=SimpleNamespace(stdout=raw, returncode=0)):
                result = recorder._run_stage('unit')
            self.assertEqual(result['reason'], 'invalid_stage_result')
            self.assertNotIn('SECRET', json.dumps(result))

    def test_stages_are_fixed_and_deterministically_ordered(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', side_effect=lambda name: self.stage(name)), \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'controller', '--stage', 'unit', '--stage', 'controller', '--output', str(output)]), 0)
            result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['expected_stages'], ['unit', 'controller'])
            self.assertTrue(result['completed'])
            self.assertTrue(result['success'])
            self.assertFalse(result['public_smoke_qualified'])
            self.assertEqual(set(result['environment']), {'python', 'os'})

    def test_pending_and_stage_checkpoints_never_claim_success(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', side_effect=lambda name: self.stage(name)), \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'unit', '--output', str(output)]), 0)
            for name in ('000-pending.json', '001-unit.json'):
                value = json.loads((output / name).read_text(encoding='utf-8'))
                self.assertFalse(value['completed'])
                self.assertFalse(value['success'])
            self.assertEqual({p.suffix for p in output.iterdir()}, {'.json'})

    def test_existing_output_directory_or_file_is_immutable(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage') as run, \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'existing'
            output.mkdir()
            sentinel = output / 'result.json'
            sentinel.write_text('old evidence', encoding='utf-8')
            self.assertEqual(recorder.main(['--stage', 'unit', '--output', str(output)]), 1)
            self.assertEqual(recorder.main(['--stage', 'unit', '--output', str(sentinel)]), 1)
            self.assertEqual(sentinel.read_text(encoding='utf-8'), 'old evidence')
            run.assert_not_called()
            with self.assertRaises(FileExistsError):
                recorder._write_new(sentinel, {})

    def test_failed_attempt_is_retained_without_stopping_later_stage(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage',
                side_effect=[self.stage('unit', success=False, reason='test_failure'), self.stage('session')]), \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'unit', '--stage', 'session', '--output', str(output)]), 1)
            result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertTrue(result['completed'])
            self.assertFalse(result['success'])
            self.assertEqual([row['name'] for row in result['stages']], ['unit', 'session'])
            self.assertTrue((output / '001-unit.json').is_file())
            self.assertTrue((output / '002-session.json').is_file())

    def test_interrupted_attempt_retains_partial_plan_and_static_reason(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', side_effect=KeyboardInterrupt('SECRET')), \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'unit', '--stage', 'session', '--output', str(output)]), 1)
            result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['expected_stages'], ['unit', 'session'])
            self.assertFalse(result['success'])
            self.assertFalse(result['completed'])
            self.assertEqual(len(result['stages']), 1)
            self.assertEqual(result['stages'][0]['reason'], 'stage_interrupted')
            self.assertNotIn('SECRET', json.dumps(result))

    def test_console_interruption_leaves_only_unsuccessful_checkpoints(self):
        class BrokenConsole(io.StringIO):
            def write(self, text):
                raise BrokenPipeError('SECRET')
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', return_value=self.stage()), \
                patch.object(recorder.sys, 'stdout', BrokenConsole()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'unit', '--output', str(output)]), 1)
            self.assertFalse((output / 'result.json').exists())
            for path in output.iterdir():
                self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['success'])

    def test_windows_cp1252_console_is_reconfigured_for_unicode(self):
        raw_out, raw_err = io.BytesIO(), io.BytesIO()
        out = io.TextIOWrapper(raw_out, encoding='cp1252', errors='strict', newline='', write_through=True)
        err = io.TextIOWrapper(raw_err, encoding='cp1252', errors='strict', newline='', write_through=True)
        text = 'Qualification \u2713 \U0001f30e'
        with self.assertRaises(UnicodeEncodeError):
            out.write(text)
        with patch.object(recorder.sys, 'stdout', out), patch.object(recorder.sys, 'stderr', err):
            recorder._configure_console()
            print(text)
            print(text, file=recorder.sys.stderr)
        self.assertEqual(raw_out.getvalue().decode('utf-8'), text + '\n')
        self.assertEqual(raw_err.getvalue().decode('utf-8'), text + '\n')
        out.detach()
        err.detach()

    def test_text_capture_without_reconfigure_is_supported(self):
        with patch.object(recorder.sys, 'stdout', io.StringIO()), patch.object(recorder.sys, 'stderr', io.StringIO()):
            recorder._configure_console()

    def test_arbitrary_smoke_url_argument_is_refused_without_echo(self):
        err = io.StringIO()
        with patch.object(recorder.sys, 'stderr', err), self.assertRaises(SystemExit) as raised:
            recorder.main(['--output', 'unused', '--url', 'https://private.invalid/?token=SECRET'])
        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn('SECRET', err.getvalue())
        self.assertEqual(err.getvalue(), 'qualification: FAIL invalid_arguments\n')

    def test_smoke_destinations_are_exact_neutral_queries_absent(self):
        self.assertEqual(smoke.MAX_GETS, 2)
        self.assertEqual(smoke.SMOKE_URLS, (
            'https://docs.python.org/3.12/library/urllib.parse.html',
            'https://docs.python.org/3.12/library/ssl.html'))
        for url in smoke.SMOKE_URLS:
            self.assertNotIn('?', url)
            self.assertNotIn('#', url)

    def test_smoke_uses_production_reader_twice_never_follow_or_fallback(self):
        reader = Mock()
        reader.read.side_effect = self.snapshot
        with patch('aster.browser_public.PublicReader', return_value=reader):
            results = smoke.run_smoke()
        self.assertEqual([call.args[0] for call in reader.read.call_args_list], list(smoke.SMOKE_URLS))
        self.assertEqual(reader.read.call_count, 2)
        reader.follow.assert_not_called()
        reader.close.assert_called_once_with()
        self.assertTrue(all(row['success'] for row in results))
        encoded = json.dumps(results)
        self.assertNotIn('Neutral documentation text', encoded)
        self.assertNotIn('Fixture', encoded)

    def test_smoke_read_failure_is_static_without_retry(self):
        reader = Mock()
        reader.read.side_effect = ValueError('SECRET private path')
        with patch('aster.browser_public.PublicReader', return_value=reader):
            results = smoke.run_smoke()
        self.assertEqual(reader.read.call_count, 2)
        self.assertTrue(all(not row['success'] for row in results))
        self.assertNotIn('SECRET', json.dumps(results))
        self.assertEqual({row['reason'] for row in results}, {'smoke_exception'})

    def test_smoke_redirect_unsupported_login_or_insecure_tls_never_pass(self):
        url = smoke.SMOKE_URLS[0]
        for change in ({'status': 'redirect', 'reason': 'redirect_review_required', 'http_status': 301},
                       {'status': 'unsupported', 'reason': 'unsupported_media'},
                       {'status': 'failed', 'reason': 'http_error', 'http_status': 401},
                       {'tls_verified': False}, {'body_sha256': 'SECRET'}, {'source_url': 'https://other.example/'},
                       {'truncated': {'body': True, 'text': False, 'title': False, 'links': False}}):
            with self.subTest(change=change):
                value = self.snapshot(url)
                value.update(change)
                self.assertFalse(smoke.compact_snapshot(url, value)['success'])

    def test_public_smoke_cannot_bypass_failed_prerequisite(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', return_value=self.stage(success=False, reason='test_failure')) as run, \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'unit', '--public-smoke', '--output', str(output)]), 1)
            result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            run.assert_called_once_with('unit')
            self.assertFalse(result['public_smoke_qualified'])
            self.assertEqual(result['stages'][-1]['reason'], 'prerequisite_failed')

    def test_smoke_metadata_is_validated_and_extra_content_dropped(self):
        rows = [smoke.compact_snapshot(url, self.snapshot(url)) for url in smoke.SMOKE_URLS]
        value = recorder._empty_stage('public-smoke', 'ok', completed=True)
        value.update(success=True, smoke=rows)
        for row in rows:
            row.update(text='SECRET', title='SECRET', selected_peer='PRIVATE', links=['SECRET'])
        clean = recorder._clean_stage('public-smoke', value)
        self.assertTrue(clean['success'])
        self.assertNotIn('SECRET', json.dumps(clean))
        self.assertNotIn('PRIVATE', json.dumps(clean))
        value['smoke'] = rows[:1]
        self.assertFalse(recorder._clean_stage('public-smoke', value)['success'])

    def test_malformed_reason_types_fail_without_exception_or_leak(self):
        for reason in (['SECRET'], {'SECRET': True}, None, 7):
            with self.subTest(kind=type(reason).__name__):
                value = self.stage(reason=reason)
                self.assertFalse(recorder._clean_stage('unit', value)['success'])
                page = self.snapshot(smoke.SMOKE_URLS[0])
                page['reason'] = reason
                cleaned = smoke.compact_snapshot(smoke.SMOKE_URLS[0], page)
                self.assertFalse(cleaned['success'])
                self.assertNotIn('SECRET', json.dumps(cleaned))

    def test_smoke_close_error_preserves_attempts_as_failures(self):
        reader = Mock()
        reader.read.side_effect = self.snapshot
        reader.close.side_effect = ValueError('SECRET')
        with patch('aster.browser_public.PublicReader', return_value=reader):
            rows = smoke.run_smoke()
        self.assertEqual(len(rows), 2)
        self.assertFalse(any(row['success'] for row in rows))
        self.assertNotIn('SECRET', json.dumps(rows))

    def test_smoke_child_cannot_forge_successful_nonread_or_unverified_metadata(self):
        for changes in ({'status': 'redirect'}, {'tls_verified': False}, {'http_status': 403},
                        {'body_sha256': None}, {'title_characters': 0}, {'text_characters': -1},
                        {'link_count': True}, {'truncated': {'body': 'SECRET'}}, {'reason': ['SECRET']}):
            with self.subTest(fields=tuple(changes)):
                rows = [smoke.compact_snapshot(url, self.snapshot(url)) for url in smoke.SMOKE_URLS]
                rows[0].update(changes)
                value = recorder._empty_stage('public-smoke', 'ok', completed=True)
                value.update(success=True, smoke=rows)
                result = recorder._clean_stage('public-smoke', value)
                self.assertFalse(result['success'])
                self.assertNotIn('SECRET', json.dumps(result))

    def test_source_changes_during_run_prevent_success(self):
        initial = {name: 'a' * 64 for name in recorder.SOURCES}
        changed = dict(initial)
        changed[recorder.SOURCES[0]] = 'b' * 64
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', return_value=self.stage()), \
                patch.object(recorder, '_source_hashes', side_effect=[initial, changed]), \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'unit', '--output', str(output)]), 1)
            value = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertFalse(value['success'])
            self.assertEqual(value['source_status'], 'source_changed')
            self.assertEqual(value['source_sha256'], initial)

    def test_missing_owned_source_hash_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', return_value=self.stage()), \
                patch.object(recorder, '_source_hashes', return_value={}), \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'unit', '--output', str(output)]), 1)
            value = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertFalse(value['success'])
            self.assertEqual(value['source_status'], 'source_missing')

    def test_source_manifest_only_contains_fixed_owned_names_and_hashes(self):
        hashes = recorder._source_hashes()
        self.assertEqual(set(hashes), set(recorder.SOURCES))
        for name, digest in hashes.items():
            self.assertFalse(Path(name).is_absolute())
            self.assertNotIn('vendor', name)
            self.assertNotIn('test-results', name)
            self.assertRegex(digest, '^[0-9a-f]{64}$')

    def test_smoke_qualification_requires_all_requested_stages(self):
        rows = [smoke.compact_snapshot(url, self.snapshot(url)) for url in smoke.SMOKE_URLS]
        stage = recorder._empty_stage('public-smoke', 'ok', completed=True)
        stage.update(success=True, smoke=rows)
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder, '_run_stage', return_value=stage), \
                patch.object(recorder.sys, 'stdout', io.StringIO()):
            output = Path(temp) / 'new'
            self.assertEqual(recorder.main(['--stage', 'public-smoke', '--output', str(output)]), 0)
            result = json.loads((output / 'result.json').read_text(encoding='utf-8'))
            self.assertTrue(result['public_smoke_qualified'])
            self.assertTrue(result['success'])

    def test_unit_stage_requires_tls_fixture_portability_negative_controls(self):
        suite, reason = recorder._load_suite('unit')
        self.assertIsNone(reason)
        tests = [test for test in recorder._flatten(suite) if type(test).__name__ == 'TLSFixturePortabilityTests']
        self.assertEqual({test._testMethodName for test in tests}, {
            'test_only_bounded_tls_reset_and_abort_outcomes_are_accepted',
            'test_unexpected_server_errors_cannot_pass_certificate_fixture',
            'test_missing_client_verification_or_http_bytes_cannot_pass'})

    def fixture_diagnostics(self):
        return {'client_verification': 'certificate_verification_failed',
                'server_abort': 'peer_reset', 'http_received': False}

    def test_fixture_failure_preserves_only_allowlisted_diagnostics(self):
        diagnostics = self.fixture_diagnostics()
        diagnostics.update(error='SECRET /private/path', host='SECRET', user_state='SECRET')
        def fail(case):
            case.fixture_diagnostics = diagnostics
            case.fail('SECRET error traceback')
        cls = type('LocalTLSFixtureTests', (unittest.TestCase,), {
            '__module__': 'test_public_transport', 'test_real_tls_wrong_hostname_sends_no_http': fail})
        suite = unittest.TestSuite([cls('test_real_tls_wrong_hostname_sends_no_http')])
        with patch.object(recorder, '_load_suite', return_value=(suite, None)):
            result = recorder._run_unit_stage('fixtures')
        self.assertEqual(result['tests']['failures'], 1)
        self.assertFalse(result['success'])
        self.assertEqual(result['fixture_outcomes'], [{
            'test_id': 'test_public_transport.LocalTLSFixtureTests.test_real_tls_wrong_hostname_sends_no_http',
            'diagnostics': self.fixture_diagnostics()}])
        self.assertNotIn('SECRET', json.dumps(result))
        cleaned = recorder._clean_stage('fixtures', result)
        self.assertEqual(cleaned['fixture_outcomes'], result['fixture_outcomes'])
        self.assertFalse(cleaned['success'])

    def test_fixture_success_preserves_diagnostics_without_changing_verdict(self):
        def succeed(case):
            case.fixture_diagnostics = {'client_verification': 'none', 'server_abort': 'none', 'http_received': True}
        cls = type('LocalTLSFixtureTests', (unittest.TestCase,), {
            '__module__': 'test_public_transport', 'test_real_tls_success_checks_hostname_sni_and_body': succeed})
        suite = unittest.TestSuite([cls('test_real_tls_success_checks_hostname_sni_and_body')])
        with patch.object(recorder, '_load_suite', return_value=(suite, None)):
            result = recorder._run_unit_stage('fixtures')
        self.assertTrue(result['success'])
        self.assertEqual(len(result['fixture_outcomes']), 1)
        self.assertTrue(result['fixture_outcomes'][0]['diagnostics']['http_received'])

    def test_malformed_fixture_diagnostics_cannot_leak(self):
        for changes in ({'server_abort': 'SECRET /private/host'}, {'client_verification': 'SECRET'},
                        {'http_received': 'SECRET'}, {'http_received': 1}, {'server_abort': ['SECRET']},
                        {'client_verification': None}):
            with self.subTest(fields=tuple(changes)):
                value = self.fixture_diagnostics()
                value.update(changes)
                self.assertIsNone(recorder._compact_fixture_diagnostics(value))
        for value in (None, [], 'SECRET'):
            self.assertIsNone(recorder._compact_fixture_diagnostics(value))

    def test_fixture_ipc_diagnostics_are_bounded_exact_id_and_enum_allowlisted(self):
        value = self.stage('fixtures')
        test_id = next(iter(recorder.FIXTURE_DIAGNOSTIC_IDS))
        dirty = self.fixture_diagnostics()
        dirty.update(raw_error='SECRET', peer='SECRET', state='SECRET')
        rows = [{'test_id': test_id, 'diagnostics': dirty, 'raw': 'SECRET'}] * 30
        value['fixture_outcomes'] = [None, {'test_id': 'SECRET', 'diagnostics': dirty}] + rows
        result = recorder._clean_stage('fixtures', value)
        self.assertEqual(result['fixture_outcomes'], [{'test_id': test_id, 'diagnostics': self.fixture_diagnostics()}])
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertTrue(result['success'])
        value['fixture_outcomes'][2]['diagnostics']['server_abort'] = 'SECRET'
        result = recorder._clean_stage('fixtures', value)
        self.assertNotIn('fixture_outcomes', result)
        self.assertNotIn('SECRET', json.dumps(result))

    def test_nonfixture_stages_and_test_ids_cannot_emit_fixture_diagnostics(self):
        value = self.stage('unit')
        value['fixture_outcomes'] = [{'test_id': next(iter(recorder.FIXTURE_DIAGNOSTIC_IDS)),
                                     'diagnostics': self.fixture_diagnostics()}]
        self.assertNotIn('fixture_outcomes', recorder._clean_stage('unit', value))
        case = unittest.FunctionTestCase(lambda: None)
        case.fixture_diagnostics = self.fixture_diagnostics()
        result = recorder.CompactResult(capture_fixture_diagnostics=True)
        result.stopTest(case)
        self.assertEqual(result.fixture_outcomes, [])

    def test_ci_requires_both_platforms_native_ui_and_smoke_without_browser_install(self):
        workflow = (recorder.ROOT / '.github/workflows/public-reader.yml').read_text(encoding='utf-8')
        self.assertIn('runs-on: windows-latest', workflow)
        self.assertIn('runs-on: ubuntu-latest', workflow)
        self.assertEqual(workflow.count('--native-ui --public-smoke'), 2)
        self.assertEqual(workflow.count('retention-days: 90'), 2)
        self.assertIn('contents: read', workflow)
        self.assertNotIn('pip install', workflow)
        self.assertNotIn('playwright', workflow.lower())


if __name__ == '__main__':
    unittest.main()
