import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from aster.dashboard import Dashboard, DashboardWorker
from aster.files import MAX_BYTES
from aster.storage import Store


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state'
        self.dashboard = Dashboard(self.path)

    def tearDown(self):
        self.dashboard.close()
        self.temp.cleanup()

    def action(self, action, **args):
        return self.dashboard.dispatch(action, **args)

    def confirm(self, result):
        return self.action('confirm', ticket=result['ticket'])

    def write(self, path='notes/a.txt', content='first'):
        return self.confirm(self.action('prepare_write', path=path, content=content))

    def test_request_is_pending_never_a_response_or_job(self):
        with patch('socket.socket', side_effect=AssertionError('No network')), \
                patch('subprocess.Popen', side_effect=AssertionError('No program launch')):
            result = self.action('save_request', prompt='Please design a program')
        self.assertEqual(result['status'], 'waiting_for_newbrain')
        snapshot = self.dashboard.snapshot()
        self.assertFalse(snapshot['backend']['available'])
        self.assertIsNone(snapshot['backend']['fallback'])
        self.assertEqual(snapshot['pending_requests'], 1)
        self.assertEqual(snapshot['histories']['jobs'], [])
        row = self.action('history', kind='prompts', item_id=result['request_id'])
        self.assertEqual(row['body'], 'Please design a program')

    def test_identity_and_pending_history_survive_restart(self):
        identity = self.dashboard.snapshot()['identity']
        self.action('save_request', prompt='remember my pending work')
        self.dashboard.close()
        self.dashboard = Dashboard(self.path)
        self.assertEqual(self.dashboard.snapshot()['identity'], identity)
        self.assertEqual(self.dashboard.snapshot()['pending_requests'], 1)

    def test_persistent_session_excludes_other_writer(self):
        with self.assertRaises(RuntimeError):
            Store(self.path)

    def test_file_create_requires_one_use_confirmation(self):
        review = self.action('prepare_write', path='a.txt', content='value')
        self.assertIsNone(self.dashboard.files.snapshot('a.txt'))
        self.assertTrue(review['confirmation_required'])
        self.confirm(review)
        self.assertEqual(self.action('read', path='a.txt')['text'], 'value')
        with self.assertRaises(ValueError):
            self.confirm(review)
        self.assertEqual(len(self.dashboard.store.rows('changes')), 1)

    def test_overwrite_preview_and_dismiss_leave_file_unchanged(self):
        self.write()
        review = self.action('prepare_write', path='notes/a.txt', content='second')
        self.assertIn('Overwrite', review['message'])
        self.action('dismiss', ticket=review['ticket'])
        with self.assertRaises(ValueError):
            self.confirm(review)
        self.assertEqual(self.action('read', path='notes/a.txt')['text'], 'first')

    def test_bad_ticket_does_not_approve(self):
        review = self.action('prepare_write', path='a', content='x')
        with self.assertRaises(ValueError):
            self.action('confirm', ticket='wrong')
        self.assertIsNone(self.dashboard.files.snapshot('a'))
        self.action('dismiss', ticket=review['ticket'])

    def test_pending_confirmation_blocks_unrelated_mutation(self):
        review = self.action('prepare_write', path='a', content='x')
        with self.assertRaises(ValueError):
            self.action('save_request', prompt='not now')
        with self.assertRaises(ValueError):
            self.dashboard.prepare_write('b', 'y')
        self.assertEqual(self.dashboard.snapshot()['pending_requests'], 0)
        self.confirm(review)

    def test_create_conflicts_if_file_appears_after_review(self):
        review = self.action('prepare_write', path='a', content='new')
        (self.dashboard.files.root / 'a').write_bytes(b'outside')
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            self.confirm(review)
        self.assertEqual(self.dashboard.files.read('a'), b'outside')
        with self.assertRaises(ValueError):
            self.confirm(review)

    def test_overwrite_conflicts_if_bytes_change_after_review(self):
        self.write('a', 'old')
        review = self.action('prepare_write', path='a', content='new')
        (self.dashboard.files.root / 'a').write_bytes(b'outside')
        with self.assertRaises(ValueError):
            self.confirm(review)
        self.assertEqual(self.dashboard.files.read('a'), b'outside')

    def test_trash_undo_and_undo_creation_all_require_confirmation(self):
        creation = self.write()
        review = self.action('prepare_trash', path='notes/a.txt')
        self.assertEqual(self.dashboard.files.read('notes/a.txt'), b'first')
        trashed = self.confirm(review)
        self.assertIsNone(self.dashboard.files.snapshot('notes/a.txt'))
        undo = self.action('prepare_undo', change_id=trashed['change_id'])
        self.assertIn('restore the previous', undo['message'])
        self.confirm(undo)
        self.assertEqual(self.dashboard.files.read('notes/a.txt'), b'first')
        remove = self.action('prepare_undo', change_id=creation['change_id'])
        self.assertIn('remove the current file', remove['message'])
        self.confirm(remove)
        self.assertIsNone(self.dashboard.files.snapshot('notes/a.txt'))

    def test_undo_refuses_conflicts_before_and_after_review(self):
        change = self.write('a', 'one')
        review = self.action('prepare_undo', change_id=change['change_id'])
        (self.dashboard.files.root / 'a').write_bytes(b'outside')
        with self.assertRaises(ValueError):
            self.confirm(review)
        with self.assertRaises(ValueError):
            self.action('prepare_undo', change_id=change['change_id'])
        self.assertEqual(self.dashboard.files.read('a'), b'outside')

    def test_empty_text_file_and_utf8_bounds(self):
        self.write('empty', '')
        self.assertEqual(self.action('read', path='empty')['text'], '')
        with self.assertRaises(ValueError):
            self.action('prepare_write', path='big', content='é' * (MAX_BYTES // 2 + 1))

    def test_workspace_escape_and_unsafe_files_rejected(self):
        for path in ('../outside', '/tmp/outside', 'a/../b', 'a\\b'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.action('prepare_write', path=path, content='no')
        if os.name == 'posix':
            outside = Path(self.temp.name) / 'outside'
            outside.write_text('safe')
            (self.dashboard.files.root / 'link').symlink_to(outside)
            with self.assertRaises((ValueError, OSError)):
                self.action('prepare_write', path='link', content='no')
            self.assertEqual(outside.read_text(), 'safe')

    def test_only_known_finite_actions(self):
        with self.assertRaises(ValueError):
            self.action('shell', command='anything')
        with self.assertRaises(ValueError):
            self.action('queue', job_action='shell', job_args={'cmd': 'anything'})
        with self.assertRaises(ValueError):
            self.action('queue', job_action='research.links', job_args={'query': 'x'}, budget=31)
        self.assertEqual(self.dashboard.snapshot()['histories']['jobs'], [])

    def test_queue_run_once_and_result_are_explicit(self):
        first = self.action('queue', job_action='memory.append', job_args={'text': 'fact', 'source': 'user'})
        second = self.action('queue', job_action='research.links', job_args={'query': 'no fetch'})
        self.assertEqual(self.dashboard.store.rows('memories'), [])
        review = self.action('prepare_run')
        self.assertIn(first['id'], review['message'])
        result = self.confirm(review)
        self.assertEqual(result['id'], first['id'])
        self.assertEqual(result['status'], 'completed')
        with self.assertRaises(ValueError):
            self.confirm(review)
        self.assertEqual(len(self.dashboard.store.rows('memories')), 1)
        self.assertEqual(self.action('history', kind='jobs', item_id=second['id'])['status'], 'queued')

    def test_queued_write_checks_overwrite_at_execution_time(self):
        self.action('queue', job_action='file.write', job_args={'path': 'a', 'text': 'queued'})
        self.write('a', 'existing')
        review = self.action('prepare_run')
        self.assertIn('Overwrite', review['message'])
        (self.dashboard.files.root / 'a').write_bytes(b'newer')
        with self.assertRaises(ValueError):
            self.confirm(review)
        self.assertEqual(self.dashboard.files.read('a'), b'newer')
        self.assertEqual(self.dashboard.store.rows('jobs')[0]['status'], 'queued')

    def test_changed_next_job_cannot_execute_with_old_ticket(self):
        first = self.action('queue', job_action='research.links', job_args={'query': 'first'})
        second = self.action('queue', job_action='research.links', job_args={'query': 'second'})
        review = self.action('prepare_run')
        self.dashboard.jobs.control(first['id'], 'pause')
        with self.assertRaisesRegex(ValueError, 'Next job changed'):
            self.confirm(review)
        self.assertEqual(self.action('history', kind='jobs', item_id=second['id'])['status'], 'queued')

    def test_pause_resume_cancel_before_execution(self):
        job = self.action('queue', job_action='research.links', job_args={'query': 'x'})['id']
        self.action('control', job_id=job, command='pause')
        self.assertEqual(self.action('prepare_run')['status'], 'idle')
        self.action('control', job_id=job, command='resume')
        self.action('control', job_id=job, command='cancel')
        self.assertEqual(self.action('prepare_run')['status'], 'idle')
        with self.assertRaises(ValueError):
            self.action('control', job_id=job, command='resume')

    def test_manual_links_are_never_fetched_or_opened(self):
        self.action('queue', job_action='research.links', job_args={'query': 'a&b'})
        with patch('socket.socket', side_effect=AssertionError('No network')), \
                patch('webbrowser.open', side_effect=AssertionError('No browser')):
            result = self.confirm(self.action('prepare_run'))
        self.assertEqual(result['result']['sources_fetched'], 0)
        self.assertIn('a%26b', result['result']['links'][0])

    def test_reconcile_is_explicit_and_never_replays(self):
        job_id = self.action('queue', job_action='memory.append', job_args={'text': 'fact', 'source': 'user'})['id']
        with self.dashboard.store.db:
            self.dashboard.store.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        review = self.action('prepare_recover')
        self.assertEqual(self.dashboard.snapshot()['running_jobs'], 1)
        self.confirm(review)
        self.assertEqual(self.dashboard.store.rows('jobs')[0]['status'], 'interrupted')
        self.assertEqual(self.dashboard.store.rows('memories'), [])

    def test_history_lists_are_bounded_and_details_exclude_file_blobs(self):
        self.write('a', 'secret file bytes')
        for index in range(103):
            self.action('save_request', prompt=f'{index}: ' + 'x' * 200)
        snapshot = self.dashboard.snapshot()
        self.assertEqual(len(snapshot['histories']['prompts']), 100)
        self.assertEqual(snapshot['pending_requests'], 103)
        self.assertEqual(len(snapshot['histories']['prompts'][0]['preview']), 160)
        change = snapshot['histories']['changes'][0]
        detail = self.action('history', kind='changes', item_id=change['id'])
        self.assertNotIn('before', detail)
        self.assertNotIn('after', detail)
        self.assertEqual(detail['after_bytes'], 17)
        with self.assertRaises(ValueError):
            self.action('history', kind='identity', item_id='x')

    def test_voice_and_app_inspection_do_not_launch_anything(self):
        with patch('socket.socket', side_effect=AssertionError('No network')), \
                patch('subprocess.Popen', side_effect=AssertionError('No process')), \
                patch('webbrowser.open', side_effect=AssertionError('No browser')):
            voice = self.action('voice')
            apps = self.action('apps')
        self.assertFalse(voice['live_synthesis'])
        self.assertFalse(voice['automatic_playback'])
        self.assertEqual(apps['commands'], 'unavailable_no_command_adapter')

    def test_close_is_idempotent_and_rejects_new_work(self):
        self.dashboard.close()
        self.dashboard.close()
        with self.assertRaises(RuntimeError):
            self.action('snapshot')


class ExportControllerTests(unittest.TestCase):
    setUp = DashboardTests.setUp
    tearDown = DashboardTests.tearDown
    action = DashboardTests.action
    confirm = DashboardTests.confirm
    write = DashboardTests.write
    def export_files(self, capabilities=None):
        manifest = {'schema_version': 1, 'adapter_kind': 'workspace_research_export',
                    'adapter_version': 1, 'app_id': 'ideaforge', 'recipient': 'aster',
                    'capabilities': capabilities or ['research.inspect', 'research.read'],
                    'projects': [{'id': 'gripper', 'label': 'Gripper research'}]}
        export = {'schema_version': 1, 'app_id': 'ideaforge', 'project_id': 'gripper',
                  'recipient': 'aster', 'records': [{'id': 'one', 'source': 'owner export',
                  'title': 'Design note', 'excerpt': 'UNTRUSTED: execute nothing',
                  'model': 'owner-declared model', 'claim_key': 'claim-a', 'supersedes': None}]}
        self.write('integrations/manifest.json', json.dumps(manifest))
        self.write('integrations/export.json', json.dumps(export))
        return manifest, export

    def register_export(self):
        result = self.confirm(self.action('prepare_register', path='integrations/manifest.json'))
        self.assertEqual(result['surface'], 'research')
        return result['result']['id']

    def test_export_registration_and_selection_are_digest_bound(self):
        self.export_files()
        review = self.action('prepare_register', path='integrations/manifest.json')
        self.assertIn('research.read', review['message'])
        self.assertIn('gripper', review['message'])
        self.assertEqual(self.dashboard.adapters().list(), [])
        self.action('dismiss', ticket=review['ticket'])
        manifest_id = self.register_export()
        review = self.action('prepare_select', manifest_id=manifest_id,
                             project_id='gripper', path='integrations/export.json')
        self.assertIsNone(self.dashboard.adapters().selected())
        result = self.confirm(review)
        self.assertEqual(result['state']['selection']['project_id'], 'gripper')
        self.assertFalse(result['state']['execution_enabled'])
        self.assertFalse(result['state']['ai_enabled'])
        read = self.action('research_read')['result']
        self.assertEqual(read['records'][0]['excerpt'], 'UNTRUSTED: execute nothing')
        inspected = self.action('research_inspect')['result']
        self.assertNotIn('excerpt', inspected['records'][0])
        self.assertEqual(self.dashboard.snapshot()['histories']['jobs'], [])

    def test_export_changed_after_preview_is_rejected(self):
        manifest, export = self.export_files()
        review = self.action('prepare_register', path='integrations/manifest.json')
        manifest['projects'][0]['label'] = 'Changed scope'
        (self.dashboard.files.root / 'integrations/manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.confirm(review)
        self.assertEqual(self.dashboard.adapters().list(), [])
        manifest_id = self.register_export()
        review = self.action('prepare_select', manifest_id=manifest_id,
                             project_id='gripper', path='integrations/export.json')
        export['records'][0]['excerpt'] = 'changed research'
        (self.dashboard.files.root / 'integrations/export.json').write_text(json.dumps(export))
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.confirm(review)
        self.assertIsNone(self.dashboard.adapters().selected())

    def test_export_selection_exact_scope_and_revocation(self):
        self.export_files()
        manifest_id = self.register_export()
        with self.assertRaises(ValueError):
            self.action('prepare_select', manifest_id=manifest_id,
                        project_id='wrong-project', path='integrations/export.json')
        self.confirm(self.action('prepare_select', manifest_id=manifest_id,
                                project_id='gripper', path='integrations/export.json'))
        review = self.action('prepare_clear')
        self.assertIsNotNone(self.dashboard.adapters().selected())
        self.confirm(review)
        self.assertIsNone(self.dashboard.adapters().selected())
        with self.assertRaises(ValueError):
            self.action('research_read')
        review = self.action('prepare_disable', manifest_id=manifest_id)
        self.confirm(review)
        with self.assertRaises(ValueError):
            self.action('prepare_select', manifest_id=manifest_id,
                        project_id='gripper', path='integrations/export.json')

    def test_export_read_requires_approved_capability(self):
        self.export_files(capabilities=['research.inspect'])
        manifest_id = self.register_export()
        self.confirm(self.action('prepare_select', manifest_id=manifest_id,
                                project_id='gripper', path='integrations/export.json'))
        self.action('research_inspect')
        with self.assertRaises(ValueError):
            self.action('research_read')



class WorkerTests(unittest.TestCase):
    def wait_for(self, worker, action, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = worker.poll()
            if result is not None and result.action == action:
                return result
            time.sleep(0.005)
        self.fail('Worker did not deliver ' + action)

    def stop(self, worker):
        worker.close()
        worker._thread.join(5)
        self.assertFalse(worker.alive)

    def test_real_worker_keeps_sqlite_on_its_thread_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as root:
            worker = DashboardWorker(root)
            try:
                ready = self.wait_for(worker, 'ready')
                self.assertFalse(ready.error)
                self.assertTrue(worker.submit('save_request', prompt='hello'))
                self.assertFalse(worker.submit('save_request', prompt='duplicate'))
                result = self.wait_for(worker, 'save_request')
                self.assertFalse(result.error)
                self.assertEqual(result.snapshot['pending_requests'], 1)
            finally:
                self.stop(worker)
            controller = Dashboard(root)
            try:
                self.assertEqual(controller.snapshot()['pending_requests'], 1)
            finally:
                controller.close()

    def test_single_flight_remains_busy_until_delivery(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        threads = []
        class Controller:
            def __init__(self, root): threads.append(threading.get_ident())
            def snapshot(self): return {}
            def dispatch(self, action, **args):
                threads.append(threading.get_ident())
                started.set(); release.wait(5); finished.set()
                return {'status': 'ok'}
            def close(self): threads.append(threading.get_ident())
        worker = DashboardWorker('.', Controller)
        try:
            self.wait_for(worker, 'ready')
            self.assertTrue(worker.submit('work'))
            self.assertTrue(started.wait(2))
            self.assertFalse(worker.submit('duplicate'))
            release.set()
            self.assertTrue(finished.wait(2))
            self.assertFalse(worker.submit('duplicate_after_completion'))
            self.assertFalse(self.wait_for(worker, 'work').error)
        finally:
            release.set(); self.stop(worker)
        self.assertEqual(len(set(threads)), 1)
        self.assertNotEqual(threads[0], threading.get_ident())

    def test_close_waits_for_accepted_action_and_rejects_repeats(self):
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        class Controller:
            def __init__(self, root): pass
            def snapshot(self): return {}
            def dispatch(self, action, **args):
                started.set(); release.wait(5)
                return {'status': 'ok'}
            def close(self): closed.set()
        worker = DashboardWorker('.', Controller)
        try:
            self.wait_for(worker, 'ready')
            worker.submit('work')
            self.assertTrue(started.wait(2))
            worker.close()
            self.assertFalse(worker.submit('later'))
            self.assertFalse(closed.is_set())
            release.set()
        finally:
            release.set(); self.stop(worker)
        self.assertTrue(closed.is_set())

    def test_controller_failure_is_reported_without_killing_worker(self):
        with tempfile.TemporaryDirectory() as root:
            worker = DashboardWorker(root)
            try:
                self.wait_for(worker, 'ready')
                worker.submit('read', path='../bad')
                result = self.wait_for(worker, 'read')
                self.assertTrue(result.error)
                self.assertTrue(worker.submit('save_request', prompt='still works'))
                self.assertFalse(self.wait_for(worker, 'save_request').error)
            finally:
                self.stop(worker)

    def test_startup_failure_does_not_accept_more_work(self):
        def fail(root):
            raise RuntimeError('state unavailable')
        worker = DashboardWorker('.', fail)
        try:
            result = self.wait_for(worker, 'startup')
            self.assertEqual(result.error, 'state unavailable')
            worker._thread.join(2)
            self.assertFalse(worker.submit('work'))
        finally:
            self.stop(worker)

    def test_close_during_startup(self):
        release = threading.Event()
        closed = threading.Event()
        class Controller:
            def __init__(self, root): release.wait(5)
            def snapshot(self): return {}
            def close(self): closed.set()
        worker = DashboardWorker('.', Controller)
        try:
            worker.close()
            release.set()
        finally:
            release.set(); self.stop(worker)
        self.assertTrue(closed.is_set())


class NativeSmokeTests(unittest.TestCase):
    def test_tk_window_builds_on_available_display(self):
        try:
            import tkinter as tk
            from tkinter import ttk, messagebox
        except ImportError:
            if os.name == 'nt':
                self.fail('Windows GUI qualification requires tkinter')
            self.skipTest('tkinter unavailable; no packages installed')
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.name == 'nt':
                self.fail('Windows GUI qualification could not open Tk: ' + str(exc))
            self.skipTest('No usable native display: ' + str(exc))
        from aster.desktop import DesktopWindow
        with tempfile.TemporaryDirectory() as state:
            app = None
            try:
                dialogs = Mock()
                app = DesktopWindow(root, state, tk, ttk, dialogs)
                def wait_idle():
                    deadline = time.monotonic() + 5
                    while app._busy and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.01)
                    self.assertFalse(app._busy)
                    dialogs.showerror.assert_not_called()
                wait_idle()
                self.assertEqual(len(app.notebook.tabs()), 7)
                self.assertIn('pending', app.pending_count.get())
                self.assertIsNotNone(app._snapshot)
                app.prompt.insert('1.0', 'A saved GUI request')
                app._save_request(); app._save_request()
                wait_idle()
                self.assertEqual(app._snapshot['pending_requests'], 1)
                self.assertEqual(app.prompt.get('1.0', 'end-1c'), '')
                app.file_path.set('notes/gui.txt')
                app.file_text.insert('1.0', 'GUI text')
                app._confirm_dialog = lambda title, message: False
                app._submit('prepare_write', path=app.file_path.get(), content='GUI text')
                wait_idle()
                self.assertEqual(app._snapshot['histories']['changes'], [])
                app._confirm_dialog = lambda title, message: True
                app._submit('prepare_write', path=app.file_path.get(), content='GUI text')
                wait_idle()
                self.assertEqual(len(app._snapshot['histories']['changes']), 1)
                app.file_text.insert('end', ' unsaved')
                dialogs.askyesno.return_value = False
                app._read_file()
                self.assertIn('unsaved', app.file_text.get('1.0', 'end-1c'))
                dialogs.askyesno.return_value = True
                app._read_file(); wait_idle()
                self.assertEqual(app.file_text.get('1.0', 'end-1c'), 'GUI text')
                app._queue(); app._queue(); wait_idle()
                self.assertEqual(len(app._snapshot['histories']['jobs']), 1)
                app._submit('prepare_run'); wait_idle()
                self.assertEqual(app._snapshot['histories']['jobs'][0]['status'], 'completed')
                app._submit('research_status'); wait_idle()
                self.assertEqual(app._research_state['status'], 'disabled_no_selection')
                app._submit('memory_refresh'); wait_idle()
                self.assertIn('Local RAM:', app.memory_status.get())
                self.assertEqual(app._snapshot['lifecycle']['integrity'], 'ok')
                app._submit('system_status'); wait_idle()
                self.assertIn('disabled_no_reviewed_app_adapters', app.local_status.get('1.0', 'end'))
            finally:
                if app is not None:
                    app.worker.close()
                    app.worker._thread.join(5)
                root.destroy()

    def test_queue_double_click_after_fast_completion_is_not_repeated(self):
        from aster.desktop import DesktopWindow
        app = DesktopWindow.__new__(DesktopWindow)
        app._busy = app._closing = False
        app._last_queue_click = None
        app.worker = Mock()
        app.worker.submit.return_value = True
        app.status = Mock()
        app._set_busy = Mock()
        args = {'job_action': 'research.links', 'job_args': {'query': 'same'}, 'budget': 5}
        with patch('aster.desktop.time.monotonic', side_effect=[10, 10.15, 11]):
            self.assertTrue(app._submit('queue', **args))
            self.assertFalse(app._submit('queue', **args))
            self.assertTrue(app._submit('queue', **args))
        self.assertEqual(app.worker.submit.call_count, 2)

    def test_launch_closes_worker_when_mainloop_raises(self):
        import aster.desktop as desktop
        fake_tk = Mock()
        fake_tk.TclError = RuntimeError
        root = fake_tk.Tk.return_value
        root.mainloop.side_effect = RuntimeError('event loop failure')
        with patch.dict('sys.modules', {'tkinter': fake_tk}), \
                patch.object(desktop, 'DesktopWindow') as window:
            with self.assertRaisesRegex(RuntimeError, 'event loop failure'):
                desktop.launch('unused-state')
        window.return_value.worker.close.assert_called_once()
        window.return_value.worker.wait_closed.assert_called_once()
        root.destroy.assert_called_once()

    def test_desktop_import_does_not_import_tk(self):
        # Lazy construction is required so CLI users do not need GUI packages.
        with patch.dict('sys.modules', {'tkinter': None}):
            module = importlib.import_module('aster.desktop')
            with self.assertRaisesRegex(RuntimeError, 'tkinter'):
                module.launch('unused-state')


if __name__ == '__main__':
    unittest.main()
