"""Integrated admission fixtures. No real application is closed or camera read."""
import tempfile
import unittest
from aster.storage import Store
from aster.files import Files
from aster.jobs import Jobs
from aster.memory_pressure import MemoryGuard
from aster.system_control import memory_config, configure_memory


class SystemControlTests(unittest.TestCase):
    def test_high_unknown_and_hysteresis_defer_without_running_or_replaying_job(self):
        observation = {'source': 'simulation', 'total_bytes': 1000, 'available_bytes': 50}
        with tempfile.TemporaryDirectory() as state:
            store = Store(state); files = Files(store)
            try:
                guard = MemoryGuard(observer=lambda: dict(observation))
                jobs = Jobs(store, files, guard)
                id_ = jobs.submit('file.write', {'path': 'q.txt', 'text': 'one write'})
                self.assertEqual(jobs.run_one()['status'], 'deferred_memory_pressure')
                self.assertIsNone(files.snapshot('q.txt'))
                self.assertEqual(store.rows('jobs')[0]['status'], 'queued')
                observation['available_bytes'] = 150
                self.assertEqual(jobs.run_one()['status'], 'deferred_memory_pressure')
                observation['available_bytes'] = 250
                result = jobs.run_one()
                self.assertEqual(result['id'], id_)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(files.read('q.txt'), b'one write')
                self.assertEqual(jobs.run_one()['status'], 'idle')
                self.assertEqual(len(store.rows('changes')), 1)
                id2 = jobs.submit('memory.append', {'text': 'must wait', 'source': 'simulation'})
                observation.clear()
                self.assertEqual(jobs.run_one()['status'], 'deferred_memory_pressure')
                self.assertFalse(store.rows('memories'))
                jobs.control(id2, 'cancel')
            finally:
                files.close(); store.close()

    def test_configuration_persists_without_changing_identity_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as state:
            store = Store(state)
            identity = store.identity()
            configure_memory(store, 88, 76)
            for high, resume in [(50, 50), (float('nan'), 10), (101, 80), (True, 0)]:
                with self.assertRaises(ValueError): configure_memory(store, high, resume)
            self.assertEqual(memory_config(store).high_used_percent, 88)
            store.close()
            store = Store(state)
            try:
                self.assertEqual(store.identity(), identity)
                self.assertEqual(memory_config(store).resume_used_percent, 76)
                self.assertEqual(len(store.rows('events')), 1)
            finally:
                store.close()

class LifecycleIntegrationTests(unittest.TestCase):
    def test_explicit_unclean_close_is_reported_without_replaying_saved_work(self):
        from aster.dashboard import Dashboard
        with tempfile.TemporaryDirectory() as state:
            first = Dashboard(state)
            request = first.dispatch('save_request', prompt='Wait for NewBrain')
            job = first.dispatch('queue', job_action='file.write',
                                 job_args={'path': 'later.txt', 'text': 'not yet'})
            identity = first.snapshot()['identity']
            first.close(clean=False)
            second = Dashboard(state)
            try:
                snapshot = second.snapshot()
                self.assertEqual(snapshot['identity'], identity)
                self.assertTrue(snapshot['lifecycle']['recovery_required'])
                self.assertEqual(second.history('prompts', request['request_id'])['status'], 'waiting_for_newbrain')
                self.assertEqual(second.history('jobs', job['id'])['status'], 'queued')
                self.assertIsNone(second.files.snapshot('later.txt'))
                prepared = second.dispatch('prepare_recover')
                second.dispatch('confirm', ticket=prepared['ticket'])
                self.assertFalse(second.snapshot()['lifecycle']['recovery_required'])
                self.assertEqual(second.history('jobs', job['id'])['status'], 'queued')
            finally:
                second.close()

    def test_worker_failed_shutdown_preserves_unclean_session(self):
        from aster.dashboard import Dashboard, DashboardWorker
        import time
        with tempfile.TemporaryDirectory() as state:
            worker = DashboardWorker(state)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                result = worker.poll()
                if result is not None: break
                time.sleep(0.01)
            self.assertEqual(result.action, 'ready')
            worker.close(clean=False)
            self.assertTrue(worker.wait_closed(5))
            panel = Dashboard(state)
            try:
                self.assertTrue(panel.snapshot()['lifecycle']['recovery_required'])
            finally:
                panel.close()

    def test_startup_error_ui_cannot_convert_failed_session_to_clean(self):
        from aster.dashboard import Dashboard, DashboardWorker
        from aster.desktop import DesktopWindow
        from unittest.mock import Mock
        import queue
        import threading
        with tempfile.TemporaryDirectory() as state:
            snapshot_entered = threading.Event()
            fail_now = threading.Event()
            error_delivered = threading.Event()
            finish = threading.Event()
            class FailingDashboard(Dashboard):
                def snapshot(self):
                    snapshot_entered.set()
                    if not fail_now.wait(5): raise RuntimeError('fixture timed out')
                    raise RuntimeError('simulated startup snapshot failure')
            class BarrierQueue(queue.Queue):
                def put(self, value, *args, **kwargs):
                    super().put(value, *args, **kwargs)
                    if value.action == 'startup':
                        error_delivered.set()
                        finish.wait(5)
            worker = DashboardWorker(state, FailingDashboard)
            try:
                self.assertTrue(snapshot_entered.wait(5))
                worker._results = BarrierQueue()
                fail_now.set()
                self.assertTrue(error_delivered.wait(5))
                app = object.__new__(DesktopWindow)
                app.worker = worker
                app.root = Mock()
                app.dialogs = Mock()
                app.status = Mock()
                app._closing = False
                app.exit_code = 0
                app._poll()
                self.assertEqual(app.exit_code, 2)
                self.assertFalse(worker._clean_requested)
            finally:
                fail_now.set(); finish.set()
                worker.close(clean=False)
                self.assertTrue(worker.wait_closed(5))
            store = Store(state)
            try:
                row = store.db.execute('SELECT status FROM lifecycle_sessions ORDER BY rowid DESC LIMIT 1').fetchone()
                self.assertEqual(row['status'], 'running')  # Accounted as unclean by the next locked owner.
            finally:
                store.close()

            panel = Dashboard(state)
            try:
                self.assertTrue(panel.snapshot()['lifecycle']['recovery_required'])
            finally:
                panel.close()


if __name__ == '__main__': unittest.main()
