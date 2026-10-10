"""Tiny owner-local fixtures only. Source is retained even when runtime is UNRUN.

These tests cap temporary SQLite files, not the real disk. The cold-start test
reapplies a tiny connection cap in a child; production Store always reapplies its
64 MiB cap. That artificial failure does not establish failure on personal state.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aster.inspection import inspect_state, MAX_OUTPUT_BYTES, MAX_ROWS
from aster.storage import Store


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'state with space # %'
        self.store = Store(self.root)
        self.identity = self.store.identity()
        self.memory_id = self.store.remember('Synthetic retained project note', source='fixture')
        with self.store.db:
            self.store.db.execute("INSERT INTO prompts(id,at,body,status) VALUES('prompt-fixture',1,'Synthetic pending request','waiting_for_newbrain')")
            self.store.db.execute("INSERT INTO jobs(id,at,action,args,status,result,budget) VALUES('job-fixture',1,'memory.append','{}','running',NULL,5)")
            self.store.db.execute("INSERT INTO changes(id,at,path,kind,before,after,status) VALUES('change-fixture',1,'fixture.txt','write',NULL,?,'prepared')", (b'synthetic bytes',))

    def tearDown(self):
        if self.store is not None:
            self.store.close()
        self.temp.cleanup()

    def close_store(self):
        self.store.close()
        self.store = None

    def hashes(self):
        # Clean DELETE-mode fixtures have no WAL reader-bookkeeping sidecars.
        import hashlib
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.iterdir() if path.is_file()}

    def test_live_wal_inspection_preserves_identity_and_interrupted_work(self):
        before = {table: self.store.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in ('identity', 'memories', 'events', 'prompts', 'jobs', 'changes')}
        with patch('aster.files.Files.recover', side_effect=AssertionError('No recovery')), \
             patch('aster.jobs.Jobs.recover', side_effect=AssertionError('No job replay')), \
             patch('aster.lifecycle.Lifecycle.start', side_effect=AssertionError('No startup')):
            for _ in range(2):
                report = inspect_state(self.root)
                self.assertEqual(report['sections']['identity']['rows'], [self.identity])
                self.assertEqual(report['sections']['interrupted_jobs']['rows'][0]['id'], 'job-fixture')
                self.assertEqual(report['sections']['prepared_changes']['rows'][0]['id'], 'change-fixture')
                self.assertEqual(report['sections']['memories']['rows'][0]['id'], self.memory_id)
                self.assertEqual(report['integrity'], 'not_checked')
                self.assertEqual(report['legacy_unlinked_job_outcome'], 'unknown')
                self.assertTrue(report['read_only'])
                self.assertFalse(report['recovery_performed'])
                self.assertEqual(report['replayed_jobs'], 0)
                self.assertNotIn('before', report['sections']['changes']['rows'][0])
                self.assertNotIn('after', report['sections']['changes']['rows'][0])
        after = {table: self.store.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                 for table in before}
        self.assertEqual(before, after)
        self.assertEqual(self.store.db.execute("SELECT status FROM jobs WHERE id='job-fixture'").fetchone()[0], 'running')
        self.assertEqual(self.store.db.execute("SELECT status FROM changes WHERE id='change-fixture'").fetchone()[0], 'prepared')

    def test_clean_database_and_files_unchanged_and_uri_safely_quoted(self):
        self.store.db.execute('PRAGMA journal_mode=DELETE')
        self.close_store()
        before = self.hashes()
        original = sqlite3.connect
        calls, statements = [], []
        class TraceConnection(sqlite3.Connection):
            def execute(self, statement, parameters=()):
                statements.append(statement)
                return super().execute(statement, parameters)
        def connect(uri, **kwargs):
            calls.append(uri)
            return original(uri, factory=TraceConnection, **kwargs)
        with patch('aster.inspection.sqlite3.connect', side_effect=connect):
            report = inspect_state(self.root)
        self.assertEqual(report['sections']['identity']['rows'], [self.identity])
        self.assertEqual(before, self.hashes())
        self.assertTrue(calls[0].endswith('?mode=ro'))
        self.assertIn('%23', calls[0])
        self.assertIn('%25', calls[0])
        self.assertNotIn('immutable', calls[0])
        self.assertNotIn('nolock', calls[0])
        for statement in statements:
            upper = statement.upper()
            self.assertFalse(any(word in upper for word in ('INSERT ', 'UPDATE ', 'DELETE ', 'CREATE ', 'VACUUM', 'MAX_PAGE_COUNT=', 'WAL_CHECKPOINT')))

    def test_memory_visibility_is_respected_without_initialization_writes(self):
        from aster.private_memory import PrivateMemory
        view = PrivateMemory(self.store)
        hidden = view.remember('Synthetic hidden note')
        deleted = view.remember('Synthetic recoverably deleted note')
        view.hide(hidden)
        view.delete(deleted)
        count = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        with patch('aster.private_memory.PrivateMemory.__init__', side_effect=AssertionError('No initializer writes')):
            report = inspect_state(self.root)
        memories = report['sections']['memories']
        self.assertEqual(memories['visibility'], 'active_only')
        self.assertEqual([row['id'] for row in memories['rows']], [self.memory_id])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], count)

    def test_incompatible_visibility_metadata_fails_closed(self):
        with self.store.db:
            self.store.db.execute('CREATE TABLE memory_metadata(unrelated TEXT)')
        report = inspect_state(self.root)
        self.assertEqual(report['sections']['memories']['status'], 'unavailable')
        self.assertEqual(report['sections']['memories']['rows'], [])
        self.assertEqual(report['sections']['identity']['rows'], [self.identity])
        self.assertNotIn('Synthetic retained project note', json.dumps(report))

    def test_visibility_view_is_not_treated_as_legacy_absence(self):
        with self.store.db:
            self.store.db.execute("CREATE VIEW memory_metadata AS SELECT id AS memory_id,'hidden' AS state FROM memories")
        report = inspect_state(self.root)
        memories = report['sections']['memories']
        self.assertEqual(memories['status'], 'unavailable')
        self.assertEqual(memories['reason'], 'incompatible_visibility_metadata')
        self.assertEqual(memories['rows'], [])
        self.assertNotIn('Synthetic retained project note', json.dumps(report))
        self.assertEqual(report['sections']['identity']['rows'], [self.identity])

    def test_optional_durable_links_and_legacy_unknown_are_explicit(self):
        # Standalone compatibility with the legacy pinned schema. The candidate
        # already creates this table; creating it here is fixture setup only.
        with self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS job_effects(
                job_id TEXT PRIMARY KEY REFERENCES jobs(id),
                memory_id TEXT UNIQUE REFERENCES memories(id),
                change_id TEXT UNIQUE REFERENCES changes(id),
                CHECK((memory_id IS NOT NULL) != (change_id IS NOT NULL)))''')
            self.store.db.execute('INSERT INTO job_effects(job_id,memory_id,change_id) VALUES(?,?,NULL)',
                                  ('job-fixture', self.memory_id))
        report = inspect_state(self.root)
        self.assertEqual(report['sections']['job_effects']['rows'],
                         [{'job_id': 'job-fixture', 'memory_id': self.memory_id, 'change_id': None}])
        self.assertIsNone(report['sections']['jobs']['rows'][0]['result'])
        self.assertEqual(report['sections']['jobs']['rows'][0]['status'], 'running')
        self.assertEqual(report['sections']['interrupted_jobs']['rows'][0]['effect'],
                         {'kind': 'memory.append', 'memory_id': self.memory_id, 'state': 'committed'})
        self.assertEqual(report['legacy_unlinked_job_outcome'], 'unknown')

    def test_old_interrupted_job_link_is_not_lost_to_newest_effect_limit(self):
        with self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS job_effects(
                job_id TEXT PRIMARY KEY REFERENCES jobs(id),
                memory_id TEXT UNIQUE REFERENCES memories(id),
                change_id TEXT UNIQUE REFERENCES changes(id),
                CHECK((memory_id IS NOT NULL) != (change_id IS NOT NULL)))''')
            self.store.db.execute('INSERT INTO job_effects(job_id,memory_id,change_id) VALUES(?,?,NULL)',
                                  ('job-fixture', self.memory_id))
            for index in range(8):
                memory = self.store.remember(f'Synthetic newer completed job effect {index}')
                self.store.db.execute('INSERT INTO jobs(id,at,action,args,status,result,budget) VALUES(?,?,?,?,?,?,?)',
                                      (f'new-linked-{index}', index + 2, 'memory.append', '{}', 'completed', '{}', 5))
                self.store.db.execute('INSERT INTO job_effects(job_id,memory_id,change_id) VALUES(?,?,NULL)',
                                      (f'new-linked-{index}', memory))
        report = inspect_state(self.root, limit=3)
        self.assertNotIn('job-fixture', [row['job_id'] for row in report['sections']['job_effects']['rows']])
        interrupted = report['sections']['interrupted_jobs']['rows'][0]
        self.assertEqual(interrupted['id'], 'job-fixture')
        self.assertEqual(interrupted['status'], 'running')
        self.assertEqual(interrupted['effect'],
                         {'kind': 'memory.append', 'memory_id': self.memory_id, 'state': 'committed'})
        self.assertIsNone(interrupted['result'])

    def test_limits_truncation_and_output_bound(self):
        with self.store.db:
            for index in range(MAX_ROWS + 10):
                self.store.db.execute('INSERT INTO events(at,kind,payload) VALUES(?,?,?)',
                                      (index, 'fixture', 'x' * 4096))
                self.store.db.execute('INSERT INTO memories(id,at,body,source,supersedes) VALUES(?,?,?,?,NULL)',
                                      (f'output-memory-{index}', index, 'x' * 4096, 'fixture'))
                self.store.db.execute('INSERT INTO prompts(id,at,body,status) VALUES(?,?,?,?)',
                                      (f'output-prompt-{index}', index, 'x' * 4096, 'waiting_for_newbrain'))
                self.store.db.execute('INSERT INTO jobs(id,at,action,args,status,result,budget) VALUES(?,?,?,?,?,?,?)',
                                      (f'output-job-{index}', index, 'memory.append', 'x' * 4096, 'completed', 'x' * 4096, 5))
        report = inspect_state(self.root, limit=MAX_ROWS)
        events = report['sections']['events']
        self.assertLessEqual(len(events['rows']), MAX_ROWS)
        self.assertTrue(events['has_more'])
        self.assertTrue(report['output_limited'])
        self.assertEqual(report['sections']['identity']['rows'], [self.identity])
        self.assertEqual(report['sections']['interrupted_jobs']['rows'][0]['id'], 'job-fixture')
        self.assertEqual(report['sections']['prepared_changes']['rows'][0]['id'], 'change-fixture')
        self.assertEqual(len(events['rows'][0]['payload'].encode()), 1024)
        self.assertEqual(events['rows'][0]['truncated_fields'], ['payload'])
        self.assertLessEqual(len(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False).encode()) + 1,
                             MAX_OUTPUT_BYTES)
        for invalid in (True, 0, MAX_ROWS + 1, 1.5, '1'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                inspect_state(self.root, limit=invalid)

    def test_global_work_limit_reports_filtered_scan_unavailable(self):
        with self.store.db:
            for index in range(600):
                self.store.db.execute('INSERT INTO jobs(id,at,action,args,status,result,budget) VALUES(?,?,?,?,?,?,?)',
                                      (f'complete-{index}', index, 'memory.append', '{}', 'completed', '{}', 5))
            self.store.db.execute("UPDATE jobs SET status='completed' WHERE id='job-fixture'")
        with patch('aster.inspection.MAX_VM_STEPS', 1000):
            report = inspect_state(self.root, limit=1)
        self.assertEqual(report['sections']['interrupted_jobs']['status'], 'unavailable')
        self.assertEqual(report['sections']['interrupted_jobs']['reason'], 'work_budget')
        self.assertLessEqual(report['sqlite_progress_steps'], 1000)
        self.assertEqual(report['replayed_jobs'], 0)

    def test_time_budget_is_explicit_and_never_fabricates_empty_work(self):
        with patch('aster.inspection.SOFT_SECONDS', 0):
            report = inspect_state(self.root)
        for section in report['sections'].values():
            self.assertEqual(section['status'], 'unavailable')
            self.assertEqual(section['reason'], 'time_budget')
        self.assertEqual(report['status'], 'unavailable')

    def test_compound_section_and_close_failure_preserves_partial_evidence_no_secrets(self):
        original = sqlite3.connect
        class FaultConnection(sqlite3.Connection):
            def execute(self, statement, parameters=()):
                if ' FROM events' in statement:
                    raise sqlite3.OperationalError('fixture private details must not escape')
                return super().execute(statement, parameters)
            def close(self):
                super().close()
                raise sqlite3.OperationalError('fixture close details must not escape')
        def connect(uri, **kwargs):
            return original(uri, factory=FaultConnection, **kwargs)
        with patch('aster.inspection.sqlite3.connect', side_effect=connect):
            report = inspect_state(self.root)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['sections']['identity']['rows'], [self.identity])
        self.assertEqual(report['sections']['events']['status'], 'unavailable')
        self.assertEqual(report['close_error'], 'connection_close_failed')
        self.assertNotIn('private details', json.dumps(report))
        self.assertNotIn('close details', json.dumps(report))
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_locked_database_reports_busy_without_repair_then_reads_after_release(self):
        self.store.db.execute('PRAGMA journal_mode=DELETE')
        self.store.db.execute('BEGIN EXCLUSIVE')
        try:
            report = inspect_state(self.root)
            self.assertEqual(report['status'], 'unavailable')
            self.assertIn(report['reason'], ('busy', 'locked', 'unavailable_or_incompatible'))
            self.assertEqual(report['replayed_jobs'], 0)
            self.assertFalse(report['recovery_performed'])
        finally:
            self.store.db.rollback()
        report = inspect_state(self.root)
        self.assertEqual(report['sections']['identity']['rows'], [self.identity])
        self.assertEqual(report['sections']['interrupted_jobs']['rows'][0]['id'], 'job-fixture')

    def test_missing_corrupt_and_unsafe_state_do_not_create_or_repair(self):
        missing = self.root.parent / 'must-not-exist'
        self.assertEqual(inspect_state(missing)['status'], 'not_found')
        self.assertFalse(missing.exists())
        corrupt = self.root.parent / 'corrupt'
        corrupt.mkdir()
        (corrupt / 'aster.sqlite3').write_bytes(b'fixture corruption')
        report = inspect_state(corrupt)
        self.assertEqual(report['status'], 'unavailable')
        self.assertIn(report['reason'], ('not_a_database', 'unavailable_or_incompatible'))
        self.assertEqual((corrupt / 'aster.sqlite3').read_bytes(), b'fixture corruption')
        unsafe = self.root.parent / 'unsafe'
        unsafe.mkdir()
        (unsafe / 'aster.sqlite3').mkdir()
        self.assertEqual(inspect_state(unsafe)['reason'], 'unsafe_or_oversized_state')

    def test_symlink_and_hardlink_database_rejected(self):
        self.close_store()
        hard = self.root.parent / 'hard'
        hard.mkdir()
        os.link(self.root / 'aster.sqlite3', hard / 'aster.sqlite3')
        self.assertEqual(inspect_state(hard)['reason'], 'unsafe_or_oversized_state')
        (hard / 'aster.sqlite3').unlink()
        if os.name == 'posix':
            link = self.root.parent / 'link'
            link.symlink_to(self.root, target_is_directory=True)
            self.assertEqual(inspect_state(link)['reason'], 'unsafe_or_oversized_state')

    def test_cli_dispatch_bypasses_store_files_jobs_and_creates_no_state(self):
        from aster.__main__ import main
        missing = self.root.parent / 'cli-must-not-exist'
        output = io.StringIO()
        with patch('aster.__main__.Store', side_effect=AssertionError('No Store')), \
             patch('aster.__main__.Files', side_effect=AssertionError('No Files')), \
             patch('aster.__main__.Jobs', side_effect=AssertionError('No Jobs')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(main(['--state', str(missing), 'inspect-state', '--limit', '3']), 2)
        self.assertEqual(json.loads(output.getvalue())['status'], 'not_found')
        self.assertFalse(missing.exists())

    @unittest.skipUnless(os.name == 'nt', 'Requires native Windows SQLite and filesystem behavior')
    def test_native_windows_read_only_file_and_spaced_uri(self):
        self.store.db.execute('PRAGMA journal_mode=DELETE')
        self.close_store()
        path = self.root / 'aster.sqlite3'
        before = self.hashes()
        os.chmod(path, stat.S_IREAD)
        try:
            result = subprocess.run([sys.executable, '-m', 'aster', '--state', str(self.root),
                                     'inspect-state', '--limit', '3'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['sections']['identity']['rows'], [self.identity])
            self.assertTrue(report['read_only'])
            self.assertEqual(before, self.hashes())
        finally:
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


class TinyCappedColdStartupTests(unittest.TestCase):
    @unittest.skipUnless(sys.version_info >= (3, 11), 'Requires native SQLite error-code evidence exposed in CPython 3.11+')
    def test_real_cold_process_full_schema_failure_then_repeatable_read_only_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'tiny-capped'
            store = Store(root)
            try:
                identity = store.identity()
                memory = store.remember('Synthetic capped fixture note')
                with store.db:
                    store.db.execute("INSERT INTO jobs(id,at,action,args,status,result,budget) VALUES('job-capped',1,'memory.append','{}','running',NULL,5)")
                    store.db.execute("INSERT INTO changes(id,at,path,kind,before,after,status) VALUES('change-capped',1,'pending.txt','write',NULL,X'78','prepared')")
                    store.db.execute('CREATE TABLE fixture_fill(data BLOB)')
                store.db.execute('PRAGMA journal_mode=DELETE')
                page_size = store.db.execute('PRAGMA page_size').fetchone()[0]
                current = store.db.execute('PRAGMA page_count').fetchone()[0]
                cap = current + 48
                self.assertLessEqual(cap * page_size, 512 * 1024)
                store.db.execute(f'PRAGMA max_page_count={cap}').fetchone()
                failed = False
                for _ in range(128):
                    try:
                        with store.db:
                            store.db.execute('INSERT INTO fixture_fill VALUES(zeroblob(4096))')
                    except sqlite3.OperationalError as exc:
                        self.assertEqual(getattr(exc, 'sqlite_errorcode', 0) & 0xff,
                                         sqlite3.SQLITE_FULL)
                        failed = True
                        break
                self.assertTrue(failed, 'Tiny bounded fixture must reach SQLITE_FULL')
                cap = store.db.execute('PRAGMA page_count').fetchone()[0]
                self.assertEqual(store.db.execute('PRAGMA freelist_count').fetchone()[0], 0)
            finally:
                store.close()
            script = r'''
import json, sqlite3, sys
from aster.storage import Store
from aster.lifecycle import Lifecycle
root, cap = sys.argv[1], int(sys.argv[2])
original = sqlite3.connect
class TinyCapConnection(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        if sql.startswith('PRAGMA max_page_count='):
            sql = 'PRAGMA max_page_count=' + str(cap)
        return super().execute(sql, parameters)
def connect(*args, **kwargs):
    return original(*args, factory=TinyCapConnection, **kwargs)
sqlite3.connect = connect
store = Store(root)
try:
    try:
        Lifecycle(store).start()
    except sqlite3.OperationalError as exc:
        code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
        # Fixture-only: Store's reopen changed DELETE to WAL. Restore DELETE
        # before the parent's byte-equality baseline; live WAL may use sidecars.
        mode = store.db.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
        print(json.dumps({'phase':'lifecycle.start', 'sqlite_errorcode':code,
                          'fixture_journal_mode':mode,
                          'page_count':store.db.execute('PRAGMA page_count').fetchone()[0]}))
        sys.exit(0 if code == sqlite3.SQLITE_FULL else 99)
    sys.exit(98)
finally:
    store.close()
'''
            result = subprocess.run([sys.executable, '-c', script, str(root), str(cap)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['sqlite_errorcode'], sqlite3.SQLITE_FULL)
            self.assertEqual(json.loads(result.stdout)['fixture_journal_mode'], 'delete')
            import hashlib
            def hashes():
                return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in root.iterdir() if path.is_file()}
            before = hashes()
            for _ in range(2):
                report = inspect_state(root)
                self.assertEqual(report['sections']['identity']['rows'], [identity])
                self.assertEqual(report['sections']['memories']['rows'][0]['id'], memory)
                self.assertEqual(report['sections']['interrupted_jobs']['rows'][0]['id'], 'job-capped')
                self.assertEqual(report['sections']['prepared_changes']['rows'][0]['id'], 'change-capped')
                self.assertEqual(report['replayed_jobs'], 0)
                self.assertFalse(report['recovery_performed'])
                self.assertEqual(report['integrity'], 'not_checked')
            self.assertEqual(before, hashes())
            self.assertLessEqual((root / 'aster.sqlite3').stat().st_size, 512 * 1024)


if __name__ == '__main__':
    unittest.main()
