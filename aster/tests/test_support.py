import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from aster.dashboard import Dashboard
from aster.support import OPERATIONS, catalog, invoke, parse_args


class SupportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.panel = Dashboard(self.tmp.name)

    def tearDown(self):
        self.panel.close(); self.tmp.cleanup()

    def call(self, module, operation, args=None, approve=False):
        result = self.panel.dispatch('prepare_support' if approve else 'support',
            module=module, operation=operation, args_json=json.dumps(args or {}))
        if approve:
            result = self.panel.dispatch('confirm', ticket=result['ticket'])
        return result['result'] if isinstance(result, dict) and result.get('surface') == 'support' else result

    def test_status_of_all_six_modules_is_real_and_backend_stays_unavailable(self):
        with patch('socket.socket', side_effect=AssertionError('No network')), \
                patch('subprocess.Popen', side_effect=AssertionError('No program')):
            for module in OPERATIONS:
                self.assertIsInstance(self.call(module, 'status'), dict)
        self.assertFalse(self.panel.snapshot()['backend']['available'])
        self.assertIsNone(self.panel.snapshot()['backend']['fallback'])

    def test_all_catalog_operations_bind_to_real_methods(self):
        # Rejecting placeholder IDs is fine; a nonexistent method or incorrect
        # keyword contract is not. No mutation is executed by this check.
        import inspect
        from aster.abilities import Abilities
        from aster.ability_workshop import AbilityWorkshop
        from aster.private_memory import PrivateMemory
        from aster.reference_library import ReferenceLibrary
        from aster.communications import Communications
        from aster.media_workshop import MediaWorkshop
        targets = {'ability': AbilityWorkshop(self.panel.store, self.panel.files),
            'memory': PrivateMemory(self.panel.store),
            'library': ReferenceLibrary(self.panel.store, self.panel.files),
            'communications': Communications(self.panel.store, self.panel.files),
            'media': MediaWorkshop(self.panel.store, self.panel.files), 'resources': self.panel.jobs.resources}
        for module, operations in OPERATIONS.items():
            for action, (method, mutation, example) in operations.items():
                with self.subTest(module=module, action=action):
                    target = targets[module]
                    if module == 'ability' and action == 'propose': target = Abilities(self.panel.store, self.panel.files)
                    if module == 'resources' and action in {'queue', 'run-one', 'control'}: target = self.panel.jobs
                    inspect.signature(getattr(target, method)).bind(**example)

    def test_mutation_requires_separate_one_use_review_and_dismiss_is_inert(self):
        args = {'body': 'Use original voice', 'category': 'decision', 'source': 'fixture'}
        with self.assertRaisesRegex(ValueError, 'review'):
            self.call('memory', 'remember', args)
        request = self.panel.dispatch('prepare_support', module='memory', operation='remember', args_json=json.dumps(args))
        self.assertEqual(self.panel.private_memory.search(), [])
        self.panel.dispatch('dismiss', ticket=request['ticket'])
        self.assertEqual(self.panel.private_memory.search(), [])
        with self.assertRaises(ValueError): self.panel.dispatch('confirm', ticket=request['ticket'])
        id_ = self.call('memory', 'remember', args, True)
        self.assertEqual(self.call('memory', 'search', {'query': 'voice'})[0]['id'], id_)

    def test_memory_controls_cover_normal_history_and_preserve_explicit_restore(self):
        id_ = self.call('memory', 'remember', {'body': 'private fixture'}, True)
        hidden = self.call('memory', 'delete', {'id_': id_}, True)
        self.assertNotIn('body', hidden)
        self.assertFalse(self.panel.snapshot()['histories']['memories'])
        with self.assertRaises(ValueError): self.panel.history('memories', id_)
        retained = self.call('memory', 'get', {'id_': id_})
        self.assertEqual(retained['state'], 'deleted')
        self.assertTrue(retained['retained_data'])
        self.call('memory', 'restore', {'id_': id_}, True)
        self.assertEqual(self.panel.history('memories', id_)['body'], 'private fixture')

    def test_source_proposal_test_review_install_preview_and_run(self):
        self.panel.files.change('recipes/tidy.json', json.dumps({'format': 'aster.text-recipe.v1',
            'steps': [{'op': 'strip'}, {'op': 'uppercase'}]}).encode())
        proposal = self.call('ability', 'propose', {'name': 'tidy', 'path': 'recipes/tidy.json', 'permissions': []}, True)
        common = {'proposal_id': proposal['id'], 'source_sha256': proposal['source_sha256']}
        receipt = self.call('ability', 'test', dict(common, cases=[{'input': ' hi ', 'expected': 'HI'}]), True)
        source = self.call('ability', 'source', {'proposal_id': proposal['id']})
        self.assertEqual(source['source_sha256'], proposal['source_sha256'])
        self.panel.files.change('recipes/tidy.json', b'changed workspace source, never the proposal')
        review_args = dict(common, verdict='approved', note='Fixture review', test_receipt_id=receipt['id'])
        request = self.panel.dispatch('prepare_support', module='ability', operation='review', args_json=json.dumps(review_args))
        self.assertIn('immutable_proposal_source', request['message'])
        self.assertIn('uppercase', request['message'])
        self.assertIn(receipt['receipt_sha256'], request['message'])
        self.assertNotIn('changed workspace source', request['message'])
        review = self.panel.dispatch('confirm', ticket=request['ticket'])['result']
        self.call('ability', 'install', dict(common, review_id=review['id']), True)
        plan = self.call('ability', 'preview-run', {'name': 'tidy', 'input_text': ' again '}, True)
        result = self.call('ability', 'run', {'plan_id': plan['id'], 'input_sha256': plan['input_sha256']}, True)
        self.assertEqual(result['output_text'], 'AGAIN')
        self.assertFalse(result['code_executed'])
        with self.assertRaises(ValueError):
            self.call('ability', 'run', {'plan_id': plan['id'], 'input_sha256': plan['input_sha256']}, True)

    def test_resource_run_uses_existing_exact_job_confirmation(self):
        self.call('resources', 'queue', {'action': 'research.links', 'args': {'query': 'a'}, 'ram_mib': 1}, True)
        request = self.panel.dispatch('prepare_support', module='resources', operation='run-one', args_json='{}')
        self.assertEqual(self.panel._pending['operation'], 'run_one')
        self.assertIn('job_id', self.panel._pending)
        self.panel.dispatch('dismiss', ticket=request['ticket'])
        self.assertEqual(self.panel.store.rows('jobs')[0]['status'], 'queued')

    def test_unknown_calls_and_embedded_approval_are_rejected(self):
        for module, op in [('memory', '__class__'), ('shell', 'run'), ('communications', 'send')]:
            with self.assertRaises(ValueError): self.call(module, op)
        with self.assertRaises(ValueError): self.call('memory', 'status', {'approved': True})
        for raw in ['[]', '{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '\ud800', '['*2000]:
            with self.assertRaises(ValueError): parse_args(raw)

    def test_cli_end_to_end_uses_same_local_capabilities(self):
        from aster.__main__ import main
        with tempfile.TemporaryDirectory() as state:
            def cli(*args):
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(['--state', state, *args])
                return code, json.loads(stdout.getvalue() or stderr.getvalue())
            code, listed = cli('support', 'catalog')
            self.assertEqual(code, 0); self.assertEqual(set(listed), set(OPERATIONS))
            args = json.dumps({'body': 'fixture decision', 'category': 'decision'})
            self.assertEqual(cli('support', 'memory', 'remember', '--args-json', args)[0], 2)
            code, id_ = cli('support', 'memory', 'remember', '--args-json', args, '--approve')
            self.assertEqual(code, 0)
            code, found = cli('support', 'memory', 'search', '--args-json', '{"query":"decision"}')
            self.assertEqual(found[0]['id'], id_)
            cli('support', 'memory', 'delete', '--args-json', json.dumps({'id_': id_}), '--approve')
            self.assertEqual(cli('history', 'memories')[1], [])

    def test_evidence_manifest_is_owned_code_only_without_weakening_validation(self):
        from scripts.record_upgrade_checks import source_manifest
        with tempfile.TemporaryDirectory() as state:
            root = Path(state)
            included = ['aster/local.py', 'tests/test_local.py', 'scripts/check.py',
                        'remote-companion/web/client.js', 'android-companion/Main.java',
                        '.github/workflows/tests.yml', 'launch_aster.py', 'remote-companion/check.cjs',
                        'android-companion/build.gradle.kts', 'scripts/check.sh']
            omitted = ['.aster-state/aster.sqlite3', 'vendor/upstream/source.py',
                       'assets/voice.wav', 'docs/private-review.md', 'experiments/upstream/source.py',
                       'test-results/result.json', 'aster/__pycache__/local.pyc']
            for name in included + omitted:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fixture')
            self.assertEqual(set(source_manifest(root)), set(included))

    def test_compact_component_outcomes_preserve_failures_without_provenance(self):
        from scripts.record_upgrade_checks import compact_stage_report
        raw = {'tests_run': 70, 'success': False, 'errors': 2, 'failures': 1, 'skipped': 3,
               'pin': 'withheld', 'test_names': ['withheld'], 'source_sha256': {'withheld': 'withheld'}}
        result = compact_stage_report('components', raw)
        self.assertFalse(result['success']); self.assertEqual(result['errors'], 2)
        self.assertEqual(result['failures'], 1); self.assertEqual(result['tests_run'], 70)
        self.assertEqual(result['skipped'], 3)
        self.assertNotIn('withheld', json.dumps(result))
        candidate = compact_stage_report('candidate-admission', {'status': 'BLOCKED',
            'runtime_compatible': False, 'source_commit': 'withheld'})
        self.assertFalse(candidate['runtime_compatible']); self.assertEqual(candidate['status'], 'BLOCKED')
        self.assertNotIn('source_commit', candidate)

    def test_runner_never_stages_raw_provenance_in_public_output_or_prints_it(self):
        from scripts import record_upgrade_checks as runner
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); private = root/'private'; private.mkdir()
            output = root/'published'; calls=[]
            def run(command, **kwargs):
                calls.append(command)
                if 'experiments.newbrain_adapter.run_checks' in command:
                    path = Path(command[command.index('--report')+1])
                    self.assertEqual(path.parent, private)
                    path.write_text(json.dumps({'tests_run': 70, 'errors': 0, 'failures': 1,
                        'skipped': 0, 'success': False, 'source_commit': 'PRIVATE-PROVENANCE'}))
                    return SimpleNamespace(stdout=b'PRIVATE-PROVENANCE\nRan 70 tests in 0.1s\nFAILED\n', returncode=1)
                if 'experiments.newbrain_candidate.audit' in command:
                    path = Path(command[command.index('--report')+1]); self.assertEqual(path.parent, private)
                    path.write_text(json.dumps({'status': 'BLOCKED_INCOMPLETE_DEPENDENCIES',
                        'runtime_compatible': False, 'source_commit': 'PRIVATE-PROVENANCE'}))
                    return SimpleNamespace(stdout=b'PRIVATE-PROVENANCE\n', returncode=2)
                return SimpleNamespace(stdout=b'owned fixture output\n', returncode=0)
            capture = io.StringIO()
            with patch.object(runner, 'ROOT', root), patch.object(runner.sys, 'argv', ['check', '--output', str(output)]), \
                    patch.object(runner.tempfile, 'mkdtemp', return_value=str(private)), \
                    patch.object(runner.platform, 'platform', return_value='fixture-platform'), \
                    patch.object(runner.subprocess, 'run', side_effect=run), contextlib.redirect_stdout(capture):
                code = runner.main()
            self.assertEqual(code, 1); self.assertEqual(len(calls), 6)
            self.assertNotIn('PRIVATE-PROVENANCE', capture.getvalue())
            for path in output.iterdir(): self.assertNotIn('PRIVATE-PROVENANCE', path.read_text())
            report = json.loads((output/'result.json').read_text())
            self.assertEqual(report['stages'][1]['status'], 'FAIL')
            self.assertEqual(report['stages'][2]['status'], 'PASS')
            self.assertEqual(json.loads((output/'component-result.json').read_text())['failures'], 1)
            self.assertIn('PRIVATE-PROVENANCE', (private/'components.log').read_text())

    def test_malformed_evidence_fails_without_dropping_remaining_checks(self):
        from scripts import record_upgrade_checks as runner
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); private=root/'private'; private.mkdir(); output=root/'published'; calls=[]
            def run(command, **kwargs):
                calls.append(command)
                if '--report' in command:
                    path=Path(command[command.index('--report')+1]); path.write_text('{"PRIVATE-PROVENANCE":')
                return SimpleNamespace(stdout=b'PRIVATE-PROVENANCE\n' if '--report' in command else b'owned\n',
                    returncode=2 if 'experiments.newbrain_candidate.audit' in command else 0)
            stdout=io.StringIO()
            with patch.object(runner,'ROOT',root), patch.object(runner.sys,'argv',['check','--output',str(output)]), \
                    patch.object(runner.tempfile,'mkdtemp',return_value=str(private)), \
                    patch.object(runner.platform,'platform',return_value='fixture-platform'), \
                    patch.object(runner.subprocess,'run',side_effect=run), contextlib.redirect_stdout(stdout):
                self.assertEqual(runner.main(),1)
            self.assertEqual(len(calls),6)
            result=json.loads((output/'result.json').read_text())
            self.assertFalse(result['success'])
            self.assertEqual([s['actual_exit'] for s in result['stages']],[0,0,2,0,0,0])
            self.assertEqual([s['status'] for s in result['stages']],['PASS','FAIL','FAIL','PASS','PASS','PASS'])
            self.assertEqual([s['name'] for s in result['stages']],
                ['foundation','components','candidate-admission','hearing-compatibility','companions','compile'])
            self.assertEqual(result['stages'][1]['evidence_error'],'JSONDecodeError')
            self.assertNotIn('PRIVATE-PROVENANCE',stdout.getvalue())
            for path in output.iterdir(): self.assertNotIn('PRIVATE-PROVENANCE',path.read_text())

    def test_dedicated_component_mode_preserves_scope_failure_and_safe_output(self):
        from scripts import record_upgrade_checks as runner
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); private=root/'private'; private.mkdir(); output=root/'published'; calls=[]
            def run(command, **kwargs):
                calls.append(command)
                self.assertIn('experiments.newbrain_adapter.run_checks',command)
                path=Path(command[command.index('--report')+1]); self.assertEqual(path.parent,private)
                path.write_text(json.dumps({'tests_run':70,'errors':0,'failures':1,'skipped':0,
                    'success':False,'source_commit':'PRIVATE-PROVENANCE'}))
                return SimpleNamespace(stdout=b'PRIVATE-PROVENANCE\nRan 70 tests in 0.1s\nFAILED\n',returncode=1)
            stdout=io.StringIO()
            with patch.object(runner,'ROOT',root), patch.object(runner.sys,'argv',['check','--components-only','--output',str(output)]), \
                    patch.object(runner.tempfile,'mkdtemp',return_value=str(private)), \
                    patch.object(runner.platform,'platform',return_value='fixture-platform'), \
                    patch.object(runner.subprocess,'run',side_effect=run), contextlib.redirect_stdout(stdout):
                self.assertEqual(runner.main(),1)
            self.assertEqual(len(calls),1)
            result=json.loads((output/'result.json').read_text())
            self.assertEqual([s['name'] for s in result['stages']],['components'])
            self.assertEqual(result['stages'][0]['status'],'FAIL')
            self.assertEqual(json.loads((output/'component-result.json').read_text())['tests_run'],70)
            self.assertNotIn('PRIVATE-PROVENANCE',stdout.getvalue())
            for path in output.iterdir(): self.assertNotIn('PRIVATE-PROVENANCE',path.read_text())

    def test_dedicated_workflow_uses_compact_runner_and_artifact_directory(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/'.github/workflows/newbrain-components.yml').read_text()
        self.assertIn('record_upgrade_checks.py --components-only --output component-ci-results',workflow)
        self.assertIn('path: component-ci-results',workflow)
        self.assertNotIn('-m experiments.newbrain_adapter.run_checks',workflow)
        self.assertNotIn('path: component-result.json',workflow)


class NativeSupportUITests(unittest.TestCase):
    def test_native_support_read_mutation_cancel_and_repeat(self):
        try:
            import tkinter as tk
            from tkinter import ttk
            root = tk.Tk()
        except Exception as exc:
            if os.name == 'nt': self.fail('Native Windows Tk support qualification failed: ' + str(exc))
            self.skipTest('No native graphical display: ' + str(exc))
        from aster.desktop import DesktopWindow
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as state:
            app = None
            try:
                app = DesktopWindow(root, state, tk, ttk, Mock())
                def settle():
                    until = time.monotonic()+10
                    while app._busy and time.monotonic()<until:
                        root.update(); time.sleep(.01)
                    self.assertFalse(app._busy)
                settle()
                self.assertEqual(len(app.notebook.tabs()), 7)
                app.notebook.select(5)
                app._support_submit(); settle()
                self.assertIn('literal_case_insensitive_substring', app.local_status.get('1.0', 'end'))
                app.support_operation.set('remember'); app._support_choose_operation()
                app._confirm_dialog = lambda *args: False
                app._support_submit(); settle()
                self.assertEqual(app._snapshot['histories']['memories'], [])
                app._confirm_dialog = lambda *args: True
                app._support_submit()
                app._support_submit()  # repeated while busy cannot create a second action
                settle()
                self.assertEqual(len(app._snapshot['histories']['memories']), 1)
                app.support_operation.set('search'); app._support_choose_operation()
                app._support_submit(); settle()
                self.assertIn('A project decision', app.local_status.get('1.0', 'end'))
                memory_id = app._snapshot['histories']['memories'][0]['id']
                app.history_kind.set('memories'); app._render_history()
                app.history.selection_set(memory_id)
                app._view('memories', app.history, app.history_detail); settle()
                self.assertIn('A project decision', app.history_detail.get('1.0', 'end'))
                app.history_kind.set('events'); app._render_history()
                self.assertNotIn('A project decision', app.history_detail.get('1.0', 'end'))
                app.history_kind.set('memories'); app._render_history()
                app.history.selection_set(memory_id)
                app._view('memories', app.history, app.history_detail); settle()
                app.support_operation.set('remember'); app._support_choose_operation()
                app._replace(app.support_args, json.dumps({'body': 'Another memory'}))
                app._support_submit(); settle()
                other_id = next(row['id'] for row in app._snapshot['histories']['memories'] if row['id'] != memory_id)
                app.history.selection_set(other_id)  # Selection changes without View.
                self.assertIn('A project decision', app.history_detail.get('1.0', 'end'))
                app.support_operation.set('hide'); app._support_choose_operation()
                app._replace(app.support_args, json.dumps({'id_': memory_id}))
                app._support_submit(); settle()
                self.assertEqual([row['id'] for row in app._snapshot['histories']['memories']], [other_id])
                self.assertNotIn('A project decision', app.history_detail.get('1.0', 'end'))
                self.assertNotIn('A project decision', app.local_status.get('1.0', 'end'))
            finally:
                if app is not None:
                    app.worker.close(); self.assertTrue(app.worker.wait_closed(10))
                root.destroy()


if __name__ == '__main__': unittest.main()
