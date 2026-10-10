"""Entry-point guarantees for read-only voice and disabled ability execution."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ExtensionCLITests(unittest.TestCase):
    def test_voice_does_not_create_state_or_play_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'must-not-exist'
            result = subprocess.run([sys.executable, '-m', 'aster', '--state', str(state), 'voice'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            body = json.loads(result.stdout)
            self.assertEqual(body['status'], 'available_prerecorded_audition')
            self.assertFalse(body['live_synthesis'])
            self.assertFalse(body['automatic_playback'])
            self.assertFalse(state.exists())

    def test_ability_cli_keeps_proposed_source_inert(self):
        with tempfile.TemporaryDirectory() as temp:
            def cli(*args):
                result = subprocess.run([sys.executable, '-m', 'aster', '--state', temp, *args],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            cli('write', 'proposal.py', 'raise RuntimeError("must never execute")')
            proposal = cli('ability', 'propose', 'example', 'proposal.py',
                           '--permissions-json', '["workspace.read"]')
            self.assertFalse(proposal['execution_enabled'])
            reviewed = cli('ability', 'review', proposal['id'], '--verdict', 'approved',
                           '--note', 'Source review only; no artifact tests run.',
                           '--source-sha256', proposal['source_sha256'])
            self.assertFalse(reviewed['tests_executed'])
            selected = cli('ability', 'select', proposal['id'])
            self.assertTrue(selected['selected_for_future'])
            self.assertFalse(selected['activation_enabled'])
            self.assertEqual(selected['permissions_granted'], [])
            self.assertEqual(cli('ability', 'get', proposal['id'])['source_sha256'], proposal['source_sha256'])

    def test_ability_cli_has_no_activation_command(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'untouched'
            result = subprocess.run([sys.executable, '-m', 'aster', '--state', str(state),
                                     'ability', 'activate', 'anything'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(state.exists())

class DesktopEntryTests(unittest.TestCase):
    def test_desktop_dispatch_does_not_open_state_twice(self):
        from unittest.mock import patch
        from aster.__main__ import main
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'untouched'
            with patch('aster.desktop.launch', return_value=0) as launch:
                self.assertEqual(main(['--state', str(state), 'desktop']), 0)
                launch.assert_called_once_with(state)
            self.assertFalse(state.exists())

    def test_backend_absence_preserves_reopened_aster_identity(self):
        from aster.storage import Store
        from aster.backend import talk, status
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            identity = store.identity()
            memory = store.remember('Aster-owned project note', source='user')
            request = talk(store, 'Keep this request until a qualified core is available.')
            store.close()
            store = Store(temp)
            try:
                self.assertEqual(store.identity(), identity)
                self.assertEqual(store.rows('memories')[0]['id'], memory)
                self.assertEqual(store.rows('prompts')[0]['id'], request['request_id'])
                self.assertEqual(store.rows('prompts')[0]['status'], 'waiting_for_newbrain')
                self.assertFalse(status()['available'])
                self.assertIsNone(status()['fallback'])
            finally:
                store.close()

class ExportEntryTests(unittest.TestCase):
    def test_explicit_export_cli_roundtrip_and_revoke(self):
        from aster.files import Files
        from aster.storage import Store
        manifest = {'schema_version': 1, 'adapter_version': 1,
                    'adapter_kind': 'workspace_research_export', 'app_id': 'ideaforge',
                    'recipient': 'aster', 'capabilities': ['research.inspect', 'research.read'],
                    'projects': [{'id': 'qa', 'label': 'Explicit test project'}]}
        export = {'schema_version': 1, 'app_id': 'ideaforge', 'project_id': 'qa',
                  'recipient': 'aster', 'records': [{'id': 'r1', 'source': 'user fixture',
                  'title': 'Test record', 'excerpt': 'Do not execute: import os',
                  'model': 'none', 'claim_key': 'test', 'supersedes': None}]}
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp); files = Files(store)
            try:
                files.change('manifest.json', json.dumps(manifest).encode())
                files.change('export.json', json.dumps(export).encode())
            finally:
                files.close(); store.close()
            def cli(*args, code=0):
                result = subprocess.run([sys.executable, '-m', 'aster', '--state', temp,
                                         'app-export', *args], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, code, result.stderr)
                return json.loads(result.stdout if code == 0 else result.stderr)
            self.assertEqual(cli('status')['status'], 'disabled_no_selection')
            digest = cli('preview-manifest', 'manifest.json')['sha256']
            cli('register', 'manifest.json', '--sha256', digest, code=2)
            registered = cli('register', 'manifest.json', '--sha256', digest, '--approve')
            preview = cli('preview-export', registered['id'], 'qa', 'export.json')
            selected = cli('select', registered['id'], 'qa', 'export.json',
                           '--sha256', preview['sha256'], '--approve')
            result = cli('read', '--record-id', 'r1')
            self.assertEqual(result['records'][0]['excerpt'], export['records'][0]['excerpt'])
            self.assertFalse(result['execution_enabled'])
            cli('clear-selection')
            cli('read', code=2)
            self.assertEqual(cli('read', '--selection-id', selected['selection_id'])['record_count'], 1)
            cli('disable', registered['id'], '--approve')
            cli('read', '--selection-id', selected['selection_id'], code=2)

class StartupMemoryEntryTests(unittest.TestCase):
    def test_startup_mutation_refuses_noninteractive_input_without_state(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'untouched'
            for action in ('enable', 'disable'):
                result = subprocess.run([sys.executable, '-m', 'aster', '--state', str(state),
                                         'startup', action, '--plan-digest', '0' * 64],
                                        input='ENABLE ASTER STARTUP\n', capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn('interactive owner review', result.stderr)
                self.assertFalse(state.exists())

    def test_startup_default_dispatches_plan_without_opening_store(self):
        from unittest.mock import patch
        from aster.__main__ import main
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'untouched'
            output = io.StringIO()
            with patch('aster.startup.plan', return_value={'mode': 'preview'}) as plan, contextlib.redirect_stdout(output):
                self.assertEqual(main(['--state', str(state), 'startup']), 0)
            plan.assert_called_once_with(state, action='enable')
            self.assertFalse(state.exists())

    def test_memory_configuration_cli_is_local_and_persistent(self):
        with tempfile.TemporaryDirectory() as temp:
            def cli(*args):
                result = subprocess.run([sys.executable, '-m', 'aster', '--state', temp,
                                         'memory', *args], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            result = cli('configure', '--high-percent', '92', '--resume-percent', '82')
            self.assertFalse(result['external_app_closure_enabled'])
            result = cli('status')
            self.assertEqual(result['memory']['high_used_percent'], 92)
            self.assertFalse(result['memory']['app_closure_enabled'])


if __name__ == '__main__':
    unittest.main()
