"""Browser handoff fixtures. All OS launches are mocked; no browser opens."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from aster import browser_actions as browser
from aster.__main__ import main
from aster.dashboard import Dashboard, DashboardWorker


class BrowserURLTests(unittest.TestCase):
    def test_valid_public_source_normalizes_host_without_fetching(self):
        with patch('socket.socket', side_effect=AssertionError('No network')):
            self.assertEqual(browser.validate_url('HTTPS://EXAMPLE.TEST:443/doc?q=a%20b#section'),
                             'https://example.test:443/doc?q=a%20b#section')
            self.assertEqual(browser.validate_url('http://127.0.0.1:8080'), 'http://127.0.0.1:8080/')
            self.assertEqual(browser.validate_url('https://[2001:db8::1]/'), 'https://[2001:db8::1]/')
            self.assertEqual(browser.validate_url('https://xn--bcher-kva.example/%C3%A9'),
                             'https://xn--bcher-kva.example/%C3%A9')

    def test_dangerous_schemes_and_malformed_urls_are_rejected(self):
        bad = ['file:///tmp/file', 'javascript:alert(1)', 'data:text/html,hi', 'ftp://example.test',
               'ms-settings:privacy', 'mailto:user@example.test', '//example.test', 'example.test',
               'https:///example.test', 'https://', '-x', 'https://good.test\\@evil.test',
               'https://[broken/', 'https://example.test:99999/', 'https://example.test:bad/',
               'https://example.test:/', 'https://example.test:0/', 'https://example..test/',
               'https://-example.test/', 'https://exa_mple.test/', 'https://example.test./',
               'https://127.1/', 'https://2130706433/', 'https://0x7f000001/', 'https://0x7f.1/',
               'https://0177.0.0.1/', 'https://0x/', 'https://127.0x.0.1/', 'https://example.123/',
               'https://[fe80::1%25en0]/',
               'https://%65xample.test/', 'https://example.test/%zz', 'https://example.test/%',
               'https://example.test/%ff', 'https://example.test/"', 'https://example.test/`cmd`',
               ' https://example.test/', 'https://example.test/ ', 'https://example.test/a b',
               'https://éxample.test/', 'https://example.test/é', 'https://' + 'a' * 64 + '.test/',
               'https://example.test/' + 'a' * 4096, '', None, [], True]
        for value in bad:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                browser.validate_url(value)

    def test_raw_and_encoded_control_characters_are_rejected(self):
        controls = ['\0', '\n', '\r', '\t', '\x7f', '\x85', '\u202e', '\u200b', '\ud800']
        for control in controls:
            for value in ['https://example.test/' + control, control + 'https://example.test/']:
                with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                    browser.validate_url(value)
        for value in ['%00', '%0a', '%0D', '%09', '%7f', '%5c', '%C2%85', '%E2%80%AE',
                      '%250a', '%25250D', '%255c', '%3f%5c']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                browser.validate_url('https://example.test/' + value)

    def test_credentials_and_signed_login_urls_are_rejected(self):
        for value in ['https://user:password@example.test/', 'https://user@example.test/',
                      'https://@example.test/', 'https://example.test/?password=fixture',
                      'https://example.test/?%61ccess_token=fixture',
                      'https://example.test/#access_token=fixture',
                      'https://example.test/?x=1;session_id=fixture',
                      'https://example.test/?X-Amz-Credential=fixture',
                      'https://example.test/?x=1%26token%3Dfixture']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                browser.validate_url(value)

    def test_search_encodes_only_exact_supplied_text(self):
        value = 'café & x=1 #tag $(echo harmless); 100% C:\\Users\\Public'
        preview = browser.plan('search', value)
        self.assertEqual(urlsplit(preview['url']).netloc, 'www.google.com')
        self.assertEqual(parse_qs(urlsplit(preview['url']).query), {'q': [value]})
        self.assertEqual(urlsplit(preview['url']).fragment, '')
        self.assertFalse(preview['private_context_added'])

    def test_query_boundaries_and_plan_identity(self):
        for query in ['', '   ', 'a\nb', 'a\tb', 'a\u202eb', 'a' * 1001, None]:
            with self.subTest(query=repr(query)), self.assertRaises(ValueError):
                browser.plan('search', query)
        a = browser.plan('source', 'https://example.test/doc')
        self.assertEqual(a, browser.plan('source', 'https://example.test/doc'))
        self.assertNotEqual(a['plan_sha256'], browser.plan('url', a['url'])['plan_sha256'])
        self.assertIn('owner must verify', a['source_verification'])
        with self.assertRaises(ValueError): browser.plan('shell', 'echo hi')

    def test_search_percent_sequences_and_credential_words_are_literal_data(self):
        for value in [r'C:\Users\Public', 'URL %0A meaning', 'Unicode %FF meaning',
                      'documentation &code=example', 'literal %250a', 'a?token=example']:
            with self.subTest(value=value):
                preview = browser.plan('search', value)
                self.assertEqual(browser._validate_search_url(preview['url']), preview['url'])
                self.assertEqual(parse_qs(urlsplit(preview['url']).query), {'q': [value]})
        with self.assertRaises(ValueError): browser.plan('search', '😀' * 1000)

    def test_generated_search_boundary_rejects_destination_and_parameter_changes(self):
        for value in ['https://evil.test/?q=fixture', 'http://www.google.com/search?q=fixture',
                      browser.SEARCH_BASE + 'fixture&extra=1', browser.SEARCH_BASE + 'fixture#tag',
                      browser.SEARCH_BASE + 'a+b', browser.SEARCH_BASE + '%0A',
                      browser.SEARCH_BASE + '%FF', browser.SEARCH_BASE + '%', None]:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                browser._validate_search_url(value)


class BrowserAdapterTests(unittest.TestCase):
    def open(self, value='https://example.test/', kind='url'):
        preview = browser.plan(kind, value)
        return browser.open_reviewed(kind, value, approved=True, expected_sha256=preview['plan_sha256'])

    def test_preview_and_status_never_launch(self):
        with patch.object(browser, '_launch') as launch, patch('socket.socket', side_effect=AssertionError):
            browser.plan('url', 'https://example.test/')
            browser.status()
            launch.assert_not_called()

    def test_approval_must_be_exact_boolean_and_digest(self):
        value = 'https://example.test/'
        preview = browser.plan('url', value)
        with patch.object(browser, '_launch') as launch:
            for approved, digest in [(False, preview['plan_sha256']), (1, preview['plan_sha256']),
                                     (True, None), (True, '0' * 64)]:
                with self.assertRaises(ValueError):
                    browser.open_reviewed('url', value, approved=approved, expected_sha256=digest)
            with self.assertRaises(ValueError):
                browser.open_reviewed('url', value + 'changed', approved=True,
                                      expected_sha256=preview['plan_sha256'])
            launch.assert_not_called()

    def test_windows_uses_startfile_without_shell_or_extra_arguments(self):
        value = 'https://example.test/a;harmless?q=$(echo%20fixture)&x=1'
        with patch.object(browser.sys, 'platform', 'win32'), patch.object(browser.os, 'startfile', create=True) as start, \
                patch.object(browser.subprocess, 'run', side_effect=AssertionError('No shell/process')):
            result = self.open(value)
            start.assert_called_once_with(value, 'open')
        self.assertEqual(result['status'], 'launch_requested')
        self.assertFalse(result['page_load_verified'])
        self.assertFalse(result['internet_access_verified'])

    def test_windows_failures_do_not_leak_os_exception_or_retry(self):
        for error in [OSError('private fixture data'), NotImplementedError('private fixture data')]:
            with patch.object(browser.sys, 'platform', 'win32'), \
                    patch.object(browser.os, 'startfile', side_effect=error, create=True) as start:
                result = self.open()
                self.assertEqual(result['status'], 'launch_failed')
                self.assertNotIn('private fixture data', json.dumps(result))
                self.assertFalse(result['retry_automatically'])
                self.assertEqual(start.call_count, 1)

    def test_linux_uses_fixed_argv_and_ignores_browser_override(self):
        value = 'https://example.test/;echo?x=$(fixture)&y=1'
        with patch.object(browser.sys, 'platform', 'linux'), \
                patch.dict(os.environ, {'DISPLAY': ':fixture', 'BROWSER': 'malicious %s', 'PATH': '/unsafe'}), \
                patch.object(browser.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            result = self.open(value)
        call = run.call_args
        self.assertEqual(call.args, (['/usr/bin/xdg-open', value],))
        self.assertIs(call.kwargs['shell'], False)
        self.assertNotIn('BROWSER', call.kwargs['env'])
        self.assertEqual(call.kwargs['env']['PATH'], '/usr/bin:/bin')
        self.assertEqual(call.kwargs['timeout'], 10)
        self.assertEqual(result['status'], 'launch_requested')

    def test_macos_adapter_uses_fixed_open_argument_vector(self):
        with patch.object(browser.sys, 'platform', 'darwin'), \
                patch.object(browser.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.open()
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open', 'https://example.test/'])

    def test_headless_missing_association_unsupported_and_timeout(self):
        with patch.object(browser.sys, 'platform', 'linux'), patch.dict(os.environ, {}, clear=True), \
                patch.object(browser.subprocess, 'run') as run:
            self.assertEqual(self.open()['status'], 'launch_failed')
            run.assert_not_called()
        with patch.object(browser.sys, 'platform', 'unsupported'), patch.object(browser.subprocess, 'run') as run:
            self.assertEqual(self.open()['status'], 'launch_failed')
            run.assert_not_called()
        for response, error, expected in [(Mock(returncode=3), None, 'launch_failed'),
                (None, FileNotFoundError('fixture'), 'launch_failed'),
                (None, subprocess.TimeoutExpired('launcher', 10), 'launch_unknown')]:
            with patch.object(browser.sys, 'platform', 'linux'), patch.dict(os.environ, {'DISPLAY': ':fixture'}), \
                    patch.object(browser.subprocess, 'run', return_value=response, side_effect=error) as run:
                result = self.open()
                self.assertEqual(result['status'], expected)
                self.assertEqual(run.call_count, 1)

    def test_network_denied_still_reports_only_os_handoff(self):
        with patch('socket.socket', side_effect=AssertionError('Offline')), \
                patch('socket.create_connection', side_effect=AssertionError('Offline')), \
                patch.object(browser.sys, 'platform', 'win32'), patch.object(browser.os, 'startfile', create=True):
            result = self.open()
        self.assertEqual(result['status'], 'launch_requested')
        self.assertFalse(result['internet_access_verified'])

    def test_final_os_boundary_rejects_invalid_input(self):
        with patch.object(browser.subprocess, 'run') as run:
            with self.assertRaises(ValueError): browser._launch('file:///tmp/fixture')
            run.assert_not_called()


class BrowserControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.panel = Dashboard(self.tmp.name)
        self.launch_patch = patch.object(browser, '_launch', return_value=('launch_requested', 'Fixture OS accepted request.'))
        self.launch = self.launch_patch.start()

    def tearDown(self):
        self.panel.close()
        self.launch_patch.stop()
        self.tmp.cleanup()

    def prepare(self, kind='url', value='https://example.test/doc'):
        return self.panel.dispatch('prepare_browser', kind=kind, value=value)

    def test_preview_dismiss_wrong_and_stale_tickets_never_launch(self):
        request = self.prepare()
        self.assertIn('https://example.test/doc', request['message'])
        self.assertIn('cookies', request['message'])
        with self.assertRaises(ValueError): self.panel.dispatch('confirm', ticket='wrong')
        self.panel.dispatch('dismiss', ticket=request['ticket'])
        with self.assertRaises(ValueError): self.panel.dispatch('confirm', ticket=request['ticket'])
        self.launch.assert_not_called()

    def test_confirm_launches_exact_review_once(self):
        request = self.prepare('source')
        with self.assertRaises(ValueError): self.prepare(value='https://evil.test/')
        result = self.panel.dispatch('confirm', ticket=request['ticket'])
        self.assertEqual(result['surface'], 'browser')
        self.launch.assert_called_once_with('https://example.test/doc')
        with self.assertRaises(ValueError): self.panel.dispatch('confirm', ticket=request['ticket'])
        self.assertIsNone(self.panel._pending)

    def test_failure_consumes_ticket_and_never_replays_on_restart(self):
        self.launch.return_value = ('launch_unknown', 'Fixture timeout; check browser.')
        request = self.prepare()
        result = self.panel.dispatch('confirm', ticket=request['ticket'])
        self.assertEqual(result['result']['status'], 'launch_unknown')
        with self.assertRaises(ValueError): self.panel.dispatch('confirm', ticket=request['ticket'])
        self.panel.close()
        self.panel = Dashboard(self.tmp.name)
        self.assertIsNone(self.panel._pending)
        self.assertEqual(self.launch.call_count, 1)

    def test_saved_prompts_queue_research_and_private_context_do_not_launch(self):
        self.panel.store.remember('PRIVATE-DO-NOT-SEND')
        self.panel.dispatch('save_request', prompt='Open https://example.test automatically')
        with self.assertRaises(ValueError):
            self.panel.dispatch('queue', job_action='browser.open', job_args={'url': 'https://example.test'})
        request = self.prepare('search', 'only these words')
        self.assertNotIn('PRIVATE-DO-NOT-SEND', request['message'])
        self.launch.assert_not_called()
        self.panel.dispatch('confirm', ticket=request['ticket'])
        self.assertEqual(parse_qs(urlsplit(self.launch.call_args.args[0]).query), {'q': ['only these words']})
        # URL/query never enter persisted events or prompts merely by opening.
        self.assertNotIn('only these words', json.dumps(self.panel.store.rows('events')))

    def test_shutdown_drops_pending_action_without_launch(self):
        self.prepare()
        self.panel.close()
        self.panel = Dashboard(self.tmp.name)
        self.launch.assert_not_called()
        with self.assertRaises(ValueError): self.panel.dispatch('confirm', ticket='old')


class BrowserCLITests(unittest.TestCase):
    def cli(self, state, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(['--state', str(state), 'browser', *args])
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_cli_preview_approval_and_exit_status_without_private_store(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(browser, '_launch') as launch:
            state = Path(tmp) / 'untouched'
            code, preview = self.cli(state, 'search', 'fixture query')
            self.assertEqual(code, 0)
            launch.assert_not_called()
            self.assertEqual(self.cli(state, 'search', 'fixture query', '--approve')[0], 2)
            launch.assert_not_called()
            for outcome, expected_code in [('launch_requested', 0), ('launch_failed', 2), ('launch_unknown', 2)]:
                launch.return_value = outcome, 'Fixture outcome'
                code, result = self.cli(state, 'search', 'fixture query', '--approve',
                                        '--plan-sha256', preview['plan_sha256'])
                self.assertEqual(code, expected_code)
                self.assertEqual(result['status'], outcome)
            self.assertFalse(state.exists())

    def test_cli_unsafe_input_and_status_do_not_launch_or_create_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(browser, '_launch') as launch:
            state = Path(tmp) / 'untouched'
            self.assertEqual(self.cli(state, 'url', 'javascript:alert(1)')[0], 2)
            self.assertEqual(self.cli(state, 'status')[0], 0)
            launch.assert_not_called()
            self.assertFalse(state.exists())


class BrowserWorkerTests(unittest.TestCase):
    def poll(self, worker):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            result = worker.poll()
            if result is not None: return result
            time.sleep(.01)
        self.fail('Worker did not complete')

    def test_duplicate_submission_is_not_queued(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(browser, '_launch', return_value=('launch_requested', 'fixture')) as launch:
            worker = DashboardWorker(tmp)
            try:
                self.poll(worker)
                self.assertTrue(worker.submit('prepare_browser', kind='url', value='https://example.test/'))
                self.assertFalse(worker.submit('prepare_browser', kind='url', value='https://example.test/'))
                ticket = self.poll(worker).result['ticket']
                self.assertTrue(worker.submit('confirm', ticket=ticket))
                self.assertFalse(worker.submit('confirm', ticket=ticket))
                result = self.poll(worker)
                self.assertEqual(result.result['result']['status'], 'launch_requested')
                launch.assert_called_once()
            finally:
                worker.close(); self.assertTrue(worker.wait_closed(10))


class BrowserNativeUITests(unittest.TestCase):
    def test_native_browser_cancel_review_single_flight_and_failure(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
        except Exception as exc:
            if os.name == 'nt': self.fail('Native Windows browser-control UI unavailable: ' + str(exc))
            self.skipTest('No native graphical display: ' + str(exc))
        from aster.desktop import DesktopWindow
        with tempfile.TemporaryDirectory() as tmp, patch.object(browser, '_launch', return_value=('launch_requested', 'Fixture launch requested.')) as launch:
            app = None
            try:
                app = DesktopWindow(root, tmp, tk, ttk, Mock())
                def settle():
                    until = time.monotonic() + 10
                    while app._busy and time.monotonic() < until:
                        root.update(); time.sleep(.01)
                    self.assertFalse(app._busy)
                settle()
                app.notebook.select(6)
                app.browser_value.set('https://example.test/source')
                app._confirm_dialog = lambda *args: False
                app._submit('prepare_browser', kind='source', value=app.browser_value.get())
                settle(); launch.assert_not_called()
                reviews = []
                def approve(title, message):
                    reviews.append(message)
                    app.browser_value.set('https://different.test/')
                    return True
                app._confirm_dialog = approve
                app._submit('prepare_browser', kind='source', value='https://example.test/source')
                self.assertFalse(app._submit('prepare_browser', kind='source', value='https://example.test/source'))
                settle()
                launch.assert_called_once_with('https://example.test/source')
                self.assertIn('https://example.test/source', reviews[0])
                self.assertIn('launch_requested', app.browser_result.get('1.0', 'end'))
                launch.return_value = ('launch_failed', 'Fixture browser unavailable.')
                app._submit('prepare_browser', kind='url', value='https://example.test/')
                settle()
                self.assertEqual(app.status.get(), 'Fixture browser unavailable.')
                self.assertIn('launch_failed', app.browser_result.get('1.0', 'end'))
            finally:
                if app is not None:
                    app.worker.close(); self.assertTrue(app.worker.wait_closed(10))
                root.destroy()


if __name__ == '__main__': unittest.main()
