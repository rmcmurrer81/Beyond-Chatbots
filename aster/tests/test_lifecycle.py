"""Durable sessions and process-exit fault injection, not real power-loss tests."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from aster.backend import talk
from aster.files import Files
from aster.jobs import Jobs
from aster.lifecycle import AutoStartBlocked, Lifecycle, LifecycleConfig, startup_launch
from aster.storage import Store


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.now, self.mono = 1000.0, 50.0

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def lifecycle(self, **kwargs):
        return Lifecycle(self.store, wall_clock=lambda: self.now, monotonic=lambda: self.mono, **kwargs)

    def test_start_and_clean_close_are_durable_and_idempotent(self):
        life = self.lifecycle()
        self.assertEqual(life.status()['integrity'], 'not_checked')
        report = life.start()
        self.assertTrue(report['allowed'])
        self.assertEqual(report['integrity'], 'ok')
        self.assertFalse(report['recovery_required'])
        self.assertEqual(life.start()['session_id'], report['session_id'])
        self.now += 7
        self.mono += 7
        self.assertEqual(life.heartbeat()['observed_session_seconds'], 7)
        life.close()
        life.close()
        row = self.store.db.execute('SELECT * FROM lifecycle_sessions').fetchone()
        self.assertEqual(row['status'], 'clean')
        self.assertEqual(row['observed_seconds'], 7)
        again = self.lifecycle()
        self.assertFalse(again.start()['recovery_required'])
        again.close()
        with self.assertRaises(RuntimeError): life.start()

    def test_unclean_restart_retains_identity_prompt_memory_and_no_replay(self):
        identity = self.store.identity()
        talk(self.store, 'Keep this request pending')
        memory = self.store.remember('Stable identity test')
        life = self.lifecycle()
        life.start()
        life.close(clean=False)
        self.now += 1
        self.mono += 1
        next_life = self.lifecycle()
        report = next_life.start()
        self.assertTrue(report['recovery_required'])
        self.assertEqual(report['unclean_previous_count'], 1)
        self.assertEqual(report['replayed_jobs'], 0)
        self.assertEqual(self.store.identity(), identity)
        self.assertEqual(self.store.rows('prompts')[0]['status'], 'waiting_for_newbrain')
        self.assertEqual(self.store.rows('memories')[0]['id'], memory)
        next_life.close()
        third = self.lifecycle()
        self.assertTrue(third.start()['recovery_required'])  # clean close alone is not recovery approval
        self.assertFalse(third.acknowledge_recovery()['recovery_required'])
        third.close()

    def test_prepared_changes_and_running_jobs_are_reported_not_changed(self):
        files = Files(self.store)
        try:
            jobs = Jobs(self.store, files)
            id_ = jobs.submit('memory.append', {'text': 'Do not replay', 'source': 'user'})
            with self.store.db:
                self.store.db.execute("UPDATE jobs SET status='running' WHERE id=?", (id_,))
            with patch.object(files, '_replace', side_effect=RuntimeError('fixture interruption')):
                with self.assertRaises(RuntimeError): files.change('pending.txt', b'not applied')
            life = self.lifecycle()
            with patch.object(files, 'recover', side_effect=AssertionError('Not automatic')), patch.object(jobs, 'recover', side_effect=AssertionError('Not automatic')):
                result = life.start()
            self.assertEqual(result['prepared_changes'], 1)
            self.assertEqual(result['running_jobs'], 1)
            self.assertTrue(result['recovery_required'])
            self.assertIsNone(files.snapshot('pending.txt'))
            self.assertEqual(self.store.rows('jobs')[0]['status'], 'running')
            with self.assertRaises(RuntimeError): life.acknowledge_recovery()
            self.assertEqual(files.recover()[0]['status'], 'not_applied')
            self.assertEqual(jobs.recover(), [id_])
            self.assertFalse(life.acknowledge_recovery()['recovery_required'])
            self.assertEqual(self.store.rows('memories'), [])
            life.close()
        finally:
            files.close()

    def test_auto_only_crash_backoff_manual_recovery_path(self):
        config = LifecycleConfig(crash_threshold=2, cooldown_seconds=100)
        for _ in range(2):
            life = self.lifecycle(auto_start=True, config=config)
            life.start()
            life.close(clean=False)
            self.now += 1
            self.mono += 1
        blocked = self.lifecycle(auto_start=True, config=config)
        with self.assertRaises(AutoStartBlocked) as caught: blocked.start()
        report = caught.exception.report
        self.assertEqual(report['crash_streak'], 2)
        self.assertFalse(report['allowed'])
        until = report['auto_start_blocked_until']
        with self.assertRaises(AutoStartBlocked): self.lifecycle(auto_start=True, config=config).start()
        self.assertEqual(blocked.status()['auto_start_blocked_until'], until)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM lifecycle_sessions').fetchone()[0], 2)
        manual = self.lifecycle(config=config)
        self.assertTrue(manual.start()['allowed'])
        manual.acknowledge_recovery()
        manual.close()
        auto = self.lifecycle(auto_start=True, config=config)
        self.assertTrue(auto.start()['allowed'])
        self.assertEqual(auto.status()['crash_streak'], 0)
        auto.close()

    def test_cooldown_expires_without_extending_on_refused_attempts(self):
        config = LifecycleConfig(crash_threshold=1, cooldown_seconds=20)
        life = self.lifecycle(config=config)
        life.start()
        life.close(clean=False)
        with self.assertRaises(AutoStartBlocked): self.lifecycle(auto_start=True, config=config).start()
        self.now += 19
        with self.assertRaises(AutoStartBlocked): self.lifecycle(auto_start=True, config=config).start()
        self.now += 1
        next_life = self.lifecycle(auto_start=True, config=config)
        self.assertTrue(next_life.start()['allowed'])
        self.assertEqual(next_life.status()['crash_streak'], 0)
        next_life.close()

    def test_long_observed_session_does_not_count_as_short_crash(self):
        life = self.lifecycle()
        life.start()
        self.now += 70
        self.mono += 70
        life.heartbeat()
        life.close(clean=False)
        again = self.lifecycle()
        self.assertEqual(again.start()['crash_streak'], 0)
        self.assertTrue(again.status()['recovery_required'])
        again.close()

    def test_unobserved_runtime_is_not_invented_from_downtime(self):
        life = self.lifecycle()
        life.start()
        # Simulate only a lost lifecycle object, intentionally omitting heartbeat/close.
        self.now += 86400
        again = self.lifecycle()
        self.assertEqual(again.start()['crash_streak'], 1)
        again.close()

    def test_wall_clock_reversal_blocks_auto_but_manual_can_recover(self):
        life = self.lifecycle()
        life.start()
        life.close()
        self.now -= 100
        blocked = self.lifecycle(auto_start=True)
        with self.assertRaises(AutoStartBlocked) as caught: blocked.start()
        self.assertTrue(caught.exception.report['clock_reversal_detected'])
        self.now += 200  # Merely waiting does not silently erase the reversal latch.
        with self.assertRaises(AutoStartBlocked): self.lifecycle(auto_start=True).start()
        manual = self.lifecycle()
        self.assertTrue(manual.start()['allowed'])
        manual.close()
        auto = self.lifecycle(auto_start=True)
        self.assertTrue(auto.start()['allowed'])
        auto.close()

    def test_monotonic_reversal_is_reported_without_negative_runtime(self):
        life = self.lifecycle(auto_start=True)
        life.start()
        self.mono -= 10
        result = life.heartbeat()
        self.assertTrue(result['clock_reversal_detected'])
        self.assertEqual(result['observed_session_seconds'], 0)
        life.close()
        with self.assertRaises(AutoStartBlocked): self.lifecycle(auto_start=True).start()

    def test_integrity_failure_stops_before_lifecycle_writes(self):
        life = self.lifecycle()
        original = self.store.db
        fake = Mock(wraps=original)
        def execute(sql, *args):
            if sql.startswith('PRAGMA quick_check'):
                return Mock(fetchone=lambda: ('fixture corruption',))
            return original.execute(sql, *args)
        fake.execute.side_effect = execute
        self.store.db = fake
        try:
            with self.assertRaises(RuntimeError): life.start()
            fake.executescript.assert_not_called()
            self.assertEqual(life.status()['integrity'], 'failed')
        finally:
            self.store.db = original

    def test_configuration_and_clock_validation(self):
        for kwargs in [{'crash_threshold': True}, {'crash_threshold': 0}, {'crash_threshold': 101},
                       {'short_session_seconds': float('nan')}, {'cooldown_seconds': 0}, {'cooldown_seconds': float('inf')}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): LifecycleConfig(**kwargs)
        with self.assertRaises(ValueError): Lifecycle(None)
        with self.assertRaises(ValueError): self.lifecycle(auto_start='yes')
        with self.assertRaises(ValueError): self.lifecycle(config={})
        self.now = float('nan')
        with self.assertRaises(ValueError): self.lifecycle().start()
        self.assertFalse(self.store.db.execute("SELECT name FROM sqlite_master WHERE name='lifecycle_sessions'").fetchone())

    def test_helper_lazy_launch_no_shell(self):
        with patch('aster.desktop.launch', return_value=7) as launch, patch('subprocess.Popen', side_effect=AssertionError('No subprocess')):
            self.assertEqual(startup_launch('fixture-state'), 7)
        launch.assert_called_once_with('fixture-state', auto_start=True)


class LifecycleProcessTests(unittest.TestCase):
    def test_real_process_crash_preserves_state_no_automatic_replay(self):
        with tempfile.TemporaryDirectory() as root:
            script = '''
import json, os, sys
from aster.storage import Store
from aster.lifecycle import Lifecycle
from aster.backend import talk
from aster.files import Files
from aster.jobs import Jobs
s = Store(sys.argv[1]); life = Lifecycle(s); life.start(); f = Files(s)
talk(s, 'Retain this prompt through process exit')
s.remember('Retain this memory')
j = Jobs(s, f); job = j.submit('memory.append', {'text':'Never replay this', 'source':'user'})
with s.db: s.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job,))
print(json.dumps(s.identity()), flush=True)
replace = f._replace
def crash(path, data):
    replace(path, data)
    os._exit(73)
f._replace = crash
f.change('crashed.txt', b'applied before abrupt exit')
'''
            result = subprocess.run([sys.executable, '-c', script, root], text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 73, result.stderr)
            identity = json.loads(result.stdout)
            store = Store(root)
            files = Files(store)
            try:
                life = Lifecycle(store)
                with patch('socket.socket', side_effect=AssertionError('No network')):
                    report = life.start()
                self.assertTrue(report['recovery_required'])
                self.assertEqual(report['unclean_previous_count'], 1)
                self.assertEqual(report['prepared_changes'], 1)
                self.assertEqual(report['running_jobs'], 1)
                self.assertEqual(store.identity(), identity)
                self.assertEqual(store.rows('prompts')[0]['status'], 'waiting_for_newbrain')
                self.assertEqual(len(store.rows('memories')), 1)
                self.assertEqual(files.read('crashed.txt'), b'applied before abrupt exit')
                self.assertEqual(store.rows('changes')[0]['status'], 'prepared')
                self.assertEqual(files.recover()[0]['status'], 'applied')
                self.assertEqual(len(Jobs(store, files).recover()), 1)
                self.assertFalse(life.acknowledge_recovery()['recovery_required'])
                self.assertEqual(len(store.rows('memories')), 1)
                life.close()
            finally:
                files.close()
                store.close()

    def test_existing_store_lock_precedes_lifecycle_in_second_process(self):
        with tempfile.TemporaryDirectory() as root:
            owner = Store(root)
            try:
                Lifecycle(owner).start()
                script = '''
import sys
from aster.storage import Store
from aster.lifecycle import Lifecycle
try:
    s = Store(sys.argv[1]); Lifecycle(s).start()
except RuntimeError as e:
    print(str(e)); sys.exit(0)
sys.exit(99)
'''
                result = subprocess.run([sys.executable, '-c', script, root], text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Another Aster command', result.stdout)
                self.assertEqual(owner.db.execute('SELECT count(*) FROM lifecycle_sessions').fetchone()[0], 1)
            finally:
                owner.close()

    def test_repeated_real_process_exits_trigger_backoff(self):
        with tempfile.TemporaryDirectory() as root:
            script = '''
import os, sys
from aster.storage import Store
from aster.lifecycle import Lifecycle
s=Store(sys.argv[1]); Lifecycle(s, auto_start=True).start(); os._exit(74)
'''
            for _ in range(3):
                result = subprocess.run([sys.executable, '-c', script, root], text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 74, result.stderr)
            store = Store(root)
            try:
                with self.assertRaises(AutoStartBlocked) as caught: Lifecycle(store, auto_start=True).start()
                self.assertEqual(caught.exception.report['crash_streak'], 3)
                manual = Lifecycle(store)
                self.assertTrue(manual.start()['allowed'])
                manual.close()
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
