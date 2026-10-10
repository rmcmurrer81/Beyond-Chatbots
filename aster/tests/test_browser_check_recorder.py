"""Browser evidence recorder regressions, independent of optional browser runtime."""
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import record_browser_checks as recorder


class BrowserRecorderTests(unittest.TestCase):
    def test_cp1252_console_accepts_installer_unicode_after_configuration(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252', errors='strict', newline='', write_through=True)
        text = 'Chromium download: ████████ 100% ✓ 😀'
        with self.assertRaises(UnicodeEncodeError):
            stream.write(text)
        with patch.object(recorder.sys, 'stdout', stream):
            recorder._configure_console()
            print(text, flush=True)
        self.assertEqual(raw.getvalue().decode('utf-8'), text + '\n')
        stream.detach()

    def test_full_recorder_keeps_raw_log_bytes_and_runs_past_unicode_output(self):
        raw_console = io.BytesIO()
        stream = io.TextIOWrapper(raw_console, encoding='cp1252', errors='strict', newline='', write_through=True)
        raw_log = 'Chromium: ████████ ✓\nRan 2 tests in 0.01s\nOK\n'.encode('utf-8')
        completed = SimpleNamespace(stdout=raw_log, returncode=0)
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder.platform, 'platform', return_value='fixture-platform'), patch.object(recorder.sys, 'stdout', stream), \
                patch.object(recorder.subprocess, 'run', return_value=completed) as run:
            output = Path(temp) / 'new-evidence'
            self.assertEqual(recorder.main(['--output', str(output)]), 0)
            self.assertEqual(run.call_count, 2)  # Unit and compile; console did not abort orchestration.
            self.assertEqual((output / 'unit.log').read_bytes(), raw_log)
            self.assertEqual((output / 'compile.log').read_bytes(), raw_log)
            result = json.loads((output / 'result.json').read_text())
            self.assertTrue(result['success'])
            self.assertTrue(result['completed'])
            self.assertEqual(result['expected_stages'], ['unit', 'compile'])
            self.assertFalse(result['live_browser_qualified'])
            self.assertEqual([s['name'] for s in result['stages']], ['unit', 'compile'])
        self.assertIn('████████', raw_console.getvalue().decode('utf-8'))
        stream.detach()

    def test_interrupted_before_live_does_not_report_completed_success(self):
        completed = SimpleNamespace(stdout=b'Ran 1 test in 0.01s\nOK\n', returncode=0)
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder.platform, 'platform', return_value='fixture-platform'), patch.object(recorder.sys, 'stdout', io.StringIO()), \
                patch.object(recorder.subprocess, 'run', side_effect=[completed, RuntimeError('interrupted')]):
            output = Path(temp) / 'new-evidence'
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                recorder.main(['--live', '--output', str(output)])
            result = json.loads((output / 'result.json').read_text())
            self.assertEqual(result['expected_stages'], ['unit', 'live', 'compile'])
            self.assertFalse(result['completed'])
            self.assertFalse(result['success'])
            self.assertFalse(result['live_browser_qualified'])
            self.assertNotIn('finished_utc', result)
            self.assertEqual([s['name'] for s in result['stages']], ['unit'])

    def test_console_interruption_cannot_turn_partial_run_into_qualification(self):
        class BrokenConsole(io.StringIO):
            def write(self, value):
                raise BrokenPipeError('simulated interrupted console')
        completed = SimpleNamespace(stdout=b'Ran 1 test in 0.01s\nOK\n', returncode=0)
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder.platform, 'platform', return_value='fixture-platform'), patch.object(recorder.sys, 'stdout', BrokenConsole()), \
                patch.object(recorder.subprocess, 'run', return_value=completed):
            output = Path(temp) / 'new-evidence'
            with self.assertRaises(BrokenPipeError):
                recorder.main(['--live', '--output', str(output)])
            result = json.loads((output / 'result.json').read_text())
            self.assertEqual(len(result['stages']), 1)
            self.assertFalse(result['completed'])
            self.assertFalse(result['success'])
            self.assertFalse(result['live_browser_qualified'])

    def test_interruption_before_first_stage_retains_pending_plan(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder.platform, 'platform', return_value='fixture-platform'), patch.object(recorder.sys, 'stdout', io.StringIO()), \
                patch.object(recorder.subprocess, 'run', side_effect=RuntimeError('interrupted')):
            output = Path(temp) / 'new-evidence'
            with self.assertRaises(RuntimeError):
                recorder.main(['--live', '--output', str(output)])
            result = json.loads((output / 'result.json').read_text())
            self.assertEqual(result['expected_stages'], ['unit', 'live', 'compile'])
            self.assertEqual(result['stages'], [])
            self.assertFalse(result['completed'])
            self.assertFalse(result['success'])
            self.assertFalse(result['live_browser_qualified'])

    def test_failed_final_stage_does_not_qualify_the_run(self):
        passed = SimpleNamespace(stdout=b'Ran 1 test in 0.01s\nOK\n', returncode=0)
        failed = SimpleNamespace(stdout=b'compile failed\n', returncode=1)
        with tempfile.TemporaryDirectory() as temp, patch.object(recorder.platform, 'platform', return_value='fixture-platform'), \
                patch.object(recorder.sys, 'stdout', io.StringIO()), \
                patch.object(recorder.subprocess, 'run', side_effect=[passed, passed, failed]):
            output = Path(temp) / 'new-evidence'
            self.assertEqual(recorder.main(['--live', '--output', str(output)]), 1)
            result = json.loads((output / 'result.json').read_text())
            self.assertTrue(result['completed'])
            self.assertFalse(result['success'])
            self.assertFalse(result['live_browser_qualified'])
            self.assertEqual([s['status'] for s in result['stages']], ['PASS', 'PASS', 'FAIL'])

    def test_text_capture_without_reconfigure_is_supported(self):
        with patch.object(recorder.sys, 'stdout', io.StringIO()) as stream:
            recorder._configure_console()
            print('fixture output')
        self.assertEqual(stream.getvalue(), 'fixture output\n')


if __name__ == '__main__':
    unittest.main()
