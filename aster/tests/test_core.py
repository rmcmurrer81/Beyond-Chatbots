import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aster.storage import Store
from aster.files import Files, MAX_BYTES
from aster.jobs import Jobs
from aster.backend import status, talk


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state'
        self.store = Store(self.path)
        self.files = Files(self.store)
        self.jobs = Jobs(self.store, self.files)

    def tearDown(self):
        self.files.close(); self.store.close(); self.temp.cleanup()

    def test_backend_is_unavailable_and_prompt_persists(self):
        with patch('socket.socket', side_effect=AssertionError('No network allowed')):
            result = talk(self.store, 'Build a program')
        self.assertFalse(status()['available']); self.assertIsNone(status()['fallback'])
        self.assertEqual(result['status'], 'waiting_for_newbrain')
        self.assertEqual(self.store.rows('prompts')[0]['body'], 'Build a program')
        self.assertEqual(self.store.rows('changes'), [])

    def test_identity_survives_restart(self):
        original = self.store.identity()
        self.files.close(); self.store.close()
        self.store = Store(self.path); self.files = Files(self.store)
        self.assertEqual(original, self.store.identity())

    def test_memory_corrections_append(self):
        first = self.store.remember('First fact', 'user')
        second = self.store.remember('Corrected fact', 'user', first)
        rows = self.store.rows('memories')
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0]['supersedes'], first)
        self.assertEqual(rows[1]['body'], 'First fact'); self.assertNotEqual(first, second)
        with self.assertRaises(sqlite3.IntegrityError): self.store.remember('bad', 'user', 'missing')

    def test_state_isolation(self):
        other = Store(Path(self.temp.name) / 'other')
        try:
            self.store.remember('private')
            self.assertEqual(other.rows('memories'), [])
            self.assertNotEqual(self.store.identity()['id'], other.identity()['id'])
        finally: other.close()

    def test_single_writer(self):
        with self.assertRaises(RuntimeError): Store(self.path)

    def test_file_write_trash_undo(self):
        first = self.files.change('project/main.py', b'print("hello")\n')
        self.assertEqual(self.files.read('project/main.py'), b'print("hello")\n')
        second = self.files.change('project/main.py', b'print("updated")\n')
        self.files.undo(second)
        self.assertEqual(self.files.read('project/main.py'), b'print("hello")\n')
        deletion = self.files.change('project/main.py', None, 'trash')
        self.assertIsNone(self.files.snapshot('project/main.py'))
        self.files.undo(deletion)
        self.assertEqual(self.files.read('project/main.py'), b'print("hello")\n')
        self.files.undo(first)
        self.assertIsNone(self.files.snapshot('project/main.py'))

    def test_refuses_undo_after_external_change(self):
        id_ = self.files.change('a', b'a')
        (self.files.root / 'a').write_bytes(b'outside edit')
        with self.assertRaises(ValueError): self.files.undo(id_)
        self.assertEqual(self.files.read('a'), b'outside edit')

    def test_path_traversal(self):
        for path in ['/tmp/escape', '../escape', 'a/../../escape', 'a/../b', './a', 'a//b', 'a\\b', '.private', 'a/']:
            with self.subTest(path=path), self.assertRaises(ValueError): self.files.change(path, b'no')

    def test_symlinks_and_hardlinks(self):
        outside = Path(self.temp.name) / 'outside'; outside.write_bytes(b'safe')
        (self.files.root / 'link').symlink_to(outside)
        (self.files.root / 'dirlink').symlink_to(outside.parent, target_is_directory=True)
        os.link(outside, self.files.root / 'hard')
        for path in ['link', 'dirlink/outside', 'hard']:
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)): self.files.change(path, b'bad')
        self.assertEqual(outside.read_bytes(), b'safe')

    def test_dangling_symlink_rejected(self):
        (self.files.root / 'link').symlink_to('/nonexistent/aster-test')
        with self.assertRaises((ValueError, OSError)): self.files.change('link', b'bad')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO test; Windows has native reparse/ADS tests')
    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.files.root / 'fifo')
        with self.assertRaises(ValueError): self.files.read('fifo')

    def test_size_and_types(self):
        for value in [b'x' * (MAX_BYTES + 1), 'not bytes']:
            with self.assertRaises(ValueError): self.files.change('a', value)
        with self.assertRaises(ValueError): talk(self.store, '')
        with self.assertRaises(ValueError): self.store.remember('x' * 32769)

    def test_prepared_operation_recovery_not_replayed(self):
        with patch.object(self.files, '_replace', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError): self.files.change('a', b'a')
        with self.assertRaises(ValueError): self.files.change('a', b'b')
        self.assertEqual(self.files.recover()[0]['status'], 'not_applied')
        self.assertIsNone(self.files.snapshot('a'))

    def test_crash_after_write_is_reconciled(self):
        original = self.files._replace
        def replace_then_crash(path, data):
            original(path, data); raise RuntimeError('crash after replace')
        with patch.object(self.files, '_replace', side_effect=replace_then_crash):
            with self.assertRaises(RuntimeError): self.files.change('a', b'a')
        self.assertEqual(self.files.recover()[0]['status'], 'applied')
        self.files.undo(self.store.rows('changes')[0]['id'])
        self.assertIsNone(self.files.snapshot('a'))

    def test_job_pause_resume_cancel(self):
        id_ = self.jobs.submit('file.write', {'path': 'a', 'text': 'a'})
        self.jobs.control(id_, 'pause'); self.assertEqual(self.jobs.run_one()['status'], 'idle')
        self.jobs.control(id_, 'resume'); self.jobs.control(id_, 'cancel')
        self.assertEqual(self.jobs.run_one()['status'], 'idle')
        self.assertIsNone(self.files.snapshot('a'))
        with self.assertRaises(ValueError): self.jobs.control(id_, 'resume')

    def test_job_executes_once(self):
        self.jobs.submit('file.write', {'path': 'a', 'text': 'a'})
        self.assertEqual(self.jobs.run_one()['status'], 'completed')
        self.assertEqual(self.jobs.run_one()['status'], 'idle')
        self.assertEqual(len(self.store.rows('changes')), 1)

    def test_job_crash_is_never_replayed(self):
        id_ = self.jobs.submit('memory.append', {'text': 'fact', 'source': 'user'})
        with self.store.db: self.store.db.execute("UPDATE jobs SET status='running' WHERE id=?", (id_,))
        self.assertEqual(self.jobs.recover(), [id_])
        self.assertEqual(self.jobs.run_one()['status'], 'idle')
        self.assertEqual(self.store.rows('memories'), [])

    def test_unknown_actions_and_limits(self):
        for action, args in [('shell', {'cmd': 'rm -rf /'}), ('file.write', {'path': '../a', 'text': 'x'}), ('research.links', {'query': 'x', 'execute': True})]:
            with self.assertRaises(ValueError): self.jobs.submit(action, args)
        for budget in [0, 31, float('nan'), float('inf'), True]:
            with self.assertRaises(ValueError): self.jobs.submit('research.links', {'query': 'a'}, budget)

    def test_research_links_honest_and_escaped(self):
        self.jobs.submit('research.links', {'query': 'a&b/#'})
        with patch('socket.socket', side_effect=AssertionError('No network allowed')): result = self.jobs.run_one()
        self.assertEqual(result['result']['sources_fetched'], 0)
        self.assertIn('a%26b%2F%23', result['result']['links'][0])

    def test_state_symlink_rejected(self):
        link = Path(self.temp.name) / 'link'; link.symlink_to(self.path)
        with self.assertRaises(ValueError): Store(link)


class CLITests(unittest.TestCase):
    def test_real_cli_restart(self):
        with tempfile.TemporaryDirectory() as root:
            def cli(*args):
                result = subprocess.run([sys.executable, '-m', 'aster', '--state', root, *args], text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            identity = cli('status')['identity']
            cli('talk', 'hello Aster')
            cli('remember', 'A test memory')
            self.assertEqual(cli('status')['identity'], identity)
            self.assertEqual(cli('history', 'prompts')[0]['status'], 'waiting_for_newbrain')
            self.assertEqual(cli('history', 'memories')[0]['body'], 'A test memory')



class ProcessCrashTests(unittest.TestCase):
    def test_actual_process_exit_after_replace_recovers(self):
        # Explicit fault simulation in a temporary workspace; not backend evidence.
        with tempfile.TemporaryDirectory() as root:
            script = '''
import os, sys
from aster.storage import Store
from aster.files import Files
s=Store(sys.argv[1]); f=Files(s)
original=f._replace
def crash(path,data):
    original(path,data)
    os._exit(73)
f._replace=crash
f.change('project/test.py', b'print("test")')
'''
            proc = subprocess.run([sys.executable, '-c', script, root], timeout=5)
            self.assertEqual(proc.returncode, 73)
            s = Store(root); f = Files(s)
            try:
                self.assertEqual(f.recover()[0]['status'], 'applied')
                id_ = s.rows('changes')[0]['id']
                f.undo(id_)
                self.assertIsNone(f.snapshot('project/test.py'))
            finally: f.close(); s.close()

    def test_actual_process_exit_before_replace_recovers(self):
        with tempfile.TemporaryDirectory() as root:
            script = '''
import os, sys
from aster.storage import Store
from aster.files import Files
s=Store(sys.argv[1]); f=Files(s)
f._replace=lambda *args: os._exit(74)
f.change('new.txt', b'not written')
'''
            proc = subprocess.run([sys.executable, '-c', script, root], timeout=5)
            self.assertEqual(proc.returncode, 74)
            s = Store(root); f = Files(s)
            try:
                self.assertEqual(f.recover()[0]['status'], 'not_applied')
                self.assertIsNone(f.snapshot('new.txt'))
            finally: f.close(); s.close()

class InitializationRecoveryTests(unittest.TestCase):
    def test_failed_database_init_releases_lock(self):
        for mode in ('symlink', 'malformed', 'hardlink'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                state = root / 'state'; state.mkdir()
                target = root / 'target'; target.write_text('not a database')
                database = state / 'aster.sqlite3'
                if mode == 'symlink': database.symlink_to(target)
                elif mode == 'hardlink': os.link(target, database)
                else: database.write_text('bad SQLite data')
                with self.assertRaises((ValueError, sqlite3.Error)): Store(state)
                database.unlink()
                store = Store(state)
                self.assertEqual(store.identity()['name'], 'Aster')
                store.close()
                self.assertEqual(target.read_text(), 'not a database')

    def test_database_sidecar_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'aster.sqlite3-wal').symlink_to('/does/not/exist')
            with self.assertRaises(ValueError): Store(root)
            (root / 'aster.sqlite3-wal').unlink()
            store = Store(root); store.close()


if __name__ == '__main__': unittest.main()
