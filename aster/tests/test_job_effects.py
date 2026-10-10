"""Durable job/effect evidence across real process exits.

All state and file bytes are synthetic and contained in TemporaryDirectory.
These tests establish process-crash behavior, not power-loss durability. On
Windows the normal Files factory selects the native WindowsFiles adapter;
there is no mock or POSIX-only skip for the crash/recovery cases.
"""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aster.dashboard import Dashboard
from aster.files import Files
from aster.jobs import Jobs
from aster.storage import Store


CRASH_CODE = 73
CHILD = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
from aster.files import Files
from aster.jobs import Jobs
from aster.storage import Store

class Guard:
    def sample(self, force=False):
        return {'allow_new_jobs': True,
                'observation': {'available_bytes': 8 * 1024 ** 3}}

class CrashConnection:
    # Observe actual SQLite transaction commits. Killing in Store.event alone
    # would exercise an uncommitted insert, not a commit-before-result crash.
    def __init__(self, connection, boundary):
        self.connection, self.boundary = connection, boundary
        self.effect = None

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def execute(self, sql, parameters=()):
        statement = ' '.join(sql.upper().split())
        if statement.startswith('UPDATE JOBS ') and 'RESULT' in statement:
            if self.boundary == 'job.before_result':
                os._exit(73)
        result = self.connection.execute(sql, parameters)
        if statement.startswith(('INSERT INTO MEMORIES ', 'INSERT INTO MEMORIES(')):
            self.effect = 'memory'
        elif statement.startswith(('INSERT INTO CHANGES ', 'INSERT INTO CHANGES(')):
            self.effect = 'file.prepared'
        elif statement.startswith('UPDATE CHANGES ') and 'STATUS' in statement:
            if "'APPLIED'" in statement or 'applied' in parameters:
                self.effect = 'file.applied'
        elif statement.startswith('UPDATE JOBS ') and 'RESULT' in statement:
            self.effect = 'job.result'
        return result

    def _before(self):
        if self.effect and self.boundary == self.effect + '.before_commit':
            os._exit(73)

    def _after(self):
        if self.effect and self.boundary == self.effect + '.after_commit':
            os._exit(73)
        self.effect = None

    def commit(self):
        self._before()
        result = self.connection.commit()
        self._after()
        return result

    def rollback(self):
        result = self.connection.rollback()
        self.effect = None
        return result

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self._before()
        result = self.connection.__exit__(kind, value, traceback)
        if kind is None:
            self._after()
        else:
            self.effect = None
        return result

store = Store(sys.argv[2])
files = Files(store)
jobs = Jobs(store, files, memory_guard=Guard())
boundary = sys.argv[3]
store.db = CrashConnection(store.db, boundary)
replace = files._replace
def crash_replace(path, data):
    if boundary == 'file.before_replace':
        os._exit(73)
    replace(path, data)
    if boundary == 'file.after_replace':
        os._exit(73)
files._replace = crash_replace
jobs.run_one()
# A zero/success exit must never accidentally satisfy a crash test.
sys.exit(91)
'''


class Guard:
    def __init__(self, allow=True, available=8 * 1024 ** 3):
        self.allow, self.available = allow, available

    def sample(self, force=False):
        return {'allow_new_jobs': self.allow,
                'observation': {'available_bytes': self.available}}


class AbortOuterTransaction(Exception):
    pass


class JobEffectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state'
        self.store = self.files = self.jobs = None
        self.open()
        self.identity = self.store.identity()

    def tearDown(self):
        self.close()
        self.temp.cleanup()

    def open(self, guard=None):
        self.store = Store(self.path)
        try:
            self.files = Files(self.store)
            self.jobs = Jobs(self.store, self.files, memory_guard=guard or Guard())
        except BaseException:
            if self.files is not None:
                self.files.close()
                self.files = None
            self.store.close()
            self.store = None
            raise

    def close(self):
        if self.files is not None:
            self.files.close()
            self.files = None
        if self.store is not None:
            self.store.close()
            self.store = None
        self.jobs = None

    def count(self, table):
        self.assertIn(table, {'memories', 'changes', 'job_effects', 'events'})
        return self.store.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def row(self, job_id):
        return dict(self.store.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def crash(self, boundary):
        self.close()
        repository = Path(__file__).resolve().parents[1]
        child = subprocess.run(
            [sys.executable, '-c', CHILD, str(repository), str(self.path), boundary],
            cwd=repository, capture_output=True, text=True, timeout=15)
        self.assertEqual(child.returncode, CRASH_CODE,
                         'Boundary did not cause the required process exit: ' + boundary +
                         '\n' + child.stderr[-4000:])
        self.open()
        self.assertEqual(self.store.identity(), self.identity)

    def effect_row(self, job_id):
        value = self.store.db.execute('SELECT * FROM job_effects WHERE job_id=?', (job_id,)).fetchone()
        return dict(value) if value is not None else None

    def assert_unknown(self, job_id):
        self.assertIsNone(self.effect_row(job_id))
        self.assertEqual(self.store.job_effect(job_id),
                         {'state': 'unknown', 'reason': 'no_durable_link'})

    def assert_interrupted(self, job_id, effect_id=None, field=None):
        row = self.row(job_id)
        self.assertEqual(row['status'], 'interrupted')
        value = json.loads(row['result']) if row['result'] else {}
        if effect_id is not None:
            self.assertEqual(value[field], effect_id)
            self.assertTrue(value['timing_unknown'])
        self.assertNotIn('elapsed_seconds', value)
        self.assertNotIn(value.get('status'), {'completed', 'completed_over_budget'})

    def assert_recovery_does_not_replay(self, job_id, expected_changes):
        counts = self.count('memories'), self.count('changes'), self.count('job_effects')
        self.assertEqual(self.files.recover(), expected_changes)
        self.assertEqual(self.jobs.recover(), [job_id])
        events = self.count('events')
        for _ in range(3):
            self.assertEqual(self.files.recover(), [])
            self.assertEqual(self.jobs.recover(), [])
            self.assertEqual(self.jobs.run_one(), {'status': 'idle'})
            self.assertEqual((self.count('memories'), self.count('changes'),
                              self.count('job_effects')), counts)
            self.assertEqual(self.count('events'), events)

    def test_memory_exit_before_effect_commit_leaves_no_effect(self):
        job_id = self.jobs.submit('memory.append', {'text': 'synthetic memory', 'source': 'test'})
        self.crash('memory.before_commit')
        self.assertEqual(self.row(job_id)['status'], 'running')
        self.assertIsNone(self.row(job_id)['result'])
        self.assertEqual(self.count('memories'), 0)
        self.assert_unknown(job_id)
        self.assert_recovery_does_not_replay(job_id, [])
        self.assert_interrupted(job_id)
        self.assert_unknown(job_id)

    def test_memory_exit_after_commit_and_before_result_preserves_exact_id(self):
        for boundary in ('memory.after_commit', 'job.before_result', 'job.result.before_commit'):
            with self.subTest(boundary=boundary):
                job_id = self.jobs.submit('memory.append', {'text': boundary, 'source': 'test'})
                baseline = self.count('memories')
                self.crash(boundary)
                self.assertEqual(self.row(job_id)['status'], 'running')
                self.assertIsNone(self.row(job_id)['result'])
                self.assertEqual(self.count('memories'), baseline + 1)
                linked = self.effect_row(job_id)
                memory_id = linked['memory_id']
                self.assertIsNone(linked['change_id'])
                memory = self.store.db.execute('SELECT body FROM memories WHERE id=?', (memory_id,)).fetchone()
                self.assertEqual(memory['body'], boundary)
                self.assertEqual(self.store.job_effect(job_id),
                                 {'kind': 'memory.append', 'memory_id': memory_id, 'state': 'committed'})
                self.assert_recovery_does_not_replay(job_id, [])
                self.assert_interrupted(job_id, memory_id, 'memory_id')
                history = next(row for row in self.store.rows('jobs') if row['id'] == job_id)
                self.assertEqual(history['effect'], self.store.job_effect(job_id))

    def test_file_exit_before_prepared_commit_never_replaces_bytes(self):
        self.files.change('artifact.txt', b'before')
        count = self.count('changes')
        job_id = self.jobs.submit('file.write', {'path': 'artifact.txt', 'text': 'after'})
        self.crash('file.prepared.before_commit')
        self.assertEqual(self.files.read('artifact.txt'), b'before')
        self.assertEqual(self.count('changes'), count)
        self.assert_unknown(job_id)
        self.assert_recovery_does_not_replay(job_id, [])
        self.assert_interrupted(job_id)

    def test_file_exit_boundaries_keep_exact_journal_id_and_actual_byte_state(self):
        boundaries = (
            ('file.prepared.after_commit', 'prepared', 'not_applied', b'before'),
            ('file.before_replace', 'prepared', 'not_applied', b'before'),
            ('file.after_replace', 'prepared', 'applied', b'after'),
            ('file.applied.before_commit', 'prepared', 'applied', b'after'),
            ('file.applied.after_commit', 'applied', 'applied', b'after'),
            ('job.before_result', 'applied', 'applied', b'after'),
            ('job.result.before_commit', 'applied', 'applied', b'after'),
        )
        for index, (boundary, stored_state, recovered_state, actual) in enumerate(boundaries):
            with self.subTest(boundary=boundary):
                path = 'artifact-' + str(index) + '.txt'
                self.files.change(path, b'before')
                count = self.count('changes')
                job_id = self.jobs.submit('file.write', {'path': path, 'text': 'after'})
                self.crash(boundary)
                self.assertEqual(self.row(job_id)['status'], 'running')
                self.assertIsNone(self.row(job_id)['result'])
                self.assertEqual(self.files.read(path), actual)
                self.assertEqual(self.count('changes'), count + 1)
                linked = self.effect_row(job_id)
                change_id = linked['change_id']
                self.assertIsNone(linked['memory_id'])
                change = self.store.db.execute('SELECT * FROM changes WHERE id=?', (change_id,)).fetchone()
                self.assertEqual((change['path'], change['before'], change['after'], change['status']),
                                 (path, b'before', b'after', stored_state))
                self.assertEqual(self.store.job_effect(job_id),
                                 {'kind': 'file.write', 'change_id': change_id, 'state': stored_state})
                recovery = [{'id': change_id, 'status': recovered_state}] if stored_state == 'prepared' else []
                self.assert_recovery_does_not_replay(job_id, recovery)
                self.assert_interrupted(job_id, change_id, 'change_id')
                self.assertEqual(self.store.job_effect(job_id),
                                 {'kind': 'file.write', 'change_id': change_id, 'state': recovered_state})
                self.assertEqual(self.files.read(path), actual)

    def test_exit_after_result_commit_preserves_actual_completion_and_timing(self):
        for action, args, field in (
                ('memory.append', {'text': 'synthetic', 'source': 'test'}, 'memory_id'),
                ('file.write', {'path': 'completed.txt', 'text': 'synthetic'}, 'change_id')):
            with self.subTest(action=action):
                job_id = self.jobs.submit(action, args, budget=30)
                self.crash('job.result.after_commit')
                row = self.row(job_id)
                self.assertIn(row['status'], {'completed', 'completed_over_budget'})
                result = json.loads(row['result'])
                self.assertEqual(result[field], self.effect_row(job_id)[field])
                self.assertGreaterEqual(result['elapsed_seconds'], 0)
                self.assertFalse(result.get('timing_unknown', False))
                self.assertEqual(self.files.recover(), [])
                self.assertEqual(self.jobs.recover(), [])
                self.assertEqual(self.jobs.run_one(), {'status': 'idle'})
                self.assertEqual(self.row(job_id), row)
                completed = self.store.db.execute(
                    'SELECT payload FROM events WHERE kind=?', ('job.' + row['status'],)).fetchall()
                self.assertIn(job_id, [json.loads(event['payload'])['id'] for event in completed])

    def test_equal_byte_process_exits_remain_indeterminate_without_replay(self):
        for index, boundary in enumerate(('file.before_replace', 'file.after_replace')):
            with self.subTest(boundary=boundary):
                path = 'equal-' + str(index) + '.txt'
                self.files.change(path, b'equal bytes')
                count = self.count('changes')
                job_id = self.jobs.submit('file.write', {'path': path, 'text': 'equal bytes'})
                self.crash(boundary)
                self.assertEqual(self.row(job_id)['status'], 'running')
                self.assertIsNone(self.row(job_id)['result'])
                self.assertEqual(self.count('changes'), count + 1)
                linked = self.effect_row(job_id)
                change_id = linked['change_id']
                self.assertIsNone(linked['memory_id'])
                change = self.store.db.execute(
                    'SELECT * FROM changes WHERE id=?', (change_id,)).fetchone()
                self.assertEqual((change['path'], change['before'], change['after'], change['status']),
                                 (path, b'equal bytes', b'equal bytes', 'prepared'))
                self.assertEqual(self.store.job_effect(job_id),
                                 {'kind': 'file.write', 'change_id': change_id, 'state': 'prepared'})
                self.assert_recovery_does_not_replay(
                    job_id, [{'id': change_id, 'status': 'indeterminate'}])
                self.assert_interrupted(job_id, change_id, 'change_id')
                self.assertEqual(self.store.job_effect(job_id),
                                 {'kind': 'file.write', 'change_id': change_id, 'state': 'indeterminate'})
                self.assertEqual(self.files.read(path), b'equal bytes')
                with self.assertRaises(ValueError):
                    self.files.undo(change_id)
                self.assertEqual(self.files.read(path), b'equal bytes')

    def test_dashboard_job_details_show_live_effect_and_retain_receipt_snapshot(self):
        self.files.change('history.txt', b'before')
        job_id = self.jobs.submit('file.write', {'path': 'history.txt', 'text': 'after'})
        self.crash('file.applied.after_commit')
        change_id = self.effect_row(job_id)['change_id']
        # Bypass startup, lifecycle, worker threads and native UI entirely.
        dashboard = Dashboard.__new__(Dashboard)
        dashboard.store = self.store
        events = self.count('events')
        running = dashboard.history('jobs', job_id)
        self.assertEqual(running['status'], 'running')
        self.assertIsNone(running['result'])
        self.assertEqual(running['effect'],
                         {'kind': 'file.write', 'change_id': change_id, 'state': 'applied'})
        self.assertEqual(self.count('events'), events)
        self.assertEqual(self.files.recover(), [])
        self.assertEqual(self.jobs.recover(), [job_id])
        recovered = dashboard.history('jobs', job_id)
        receipt = recovered['result']
        self.assertEqual(json.loads(receipt)['effect'],
                         {'kind': 'file.write', 'change_id': change_id, 'state': 'applied'})
        self.assert_interrupted(job_id, change_id, 'change_id')
        self.files.undo(change_id)
        events = self.count('events')
        undone = dashboard.history('jobs', job_id)
        self.assertEqual(undone['status'], 'interrupted')
        self.assertEqual(undone['effect'],
                         {'kind': 'file.write', 'change_id': change_id, 'state': 'undone'})
        self.assertEqual(undone['result'], receipt)
        self.assertEqual(json.loads(undone['result'])['effect']['state'], 'applied')
        self.assertEqual(self.files.read('history.txt'), b'before')
        self.assertEqual(self.count('job_effects'), 1)
        self.assertEqual(self.count('events'), events)
        self.assertEqual(self.jobs.recover(), [])
        self.assertEqual(self.files.recover(), [])

    def test_recovery_after_external_edit_reports_conflict_without_overwriting(self):
        self.files.change('artifact.txt', b'before')
        job_id = self.jobs.submit('file.write', {'path': 'artifact.txt', 'text': 'after'})
        self.crash('file.after_replace')
        change_id = self.effect_row(job_id)['change_id']
        (self.files.root / 'artifact.txt').write_bytes(b'external edit')
        self.assert_recovery_does_not_replay(job_id, [{'id': change_id, 'status': 'conflict'}])
        self.assertEqual(self.files.read('artifact.txt'), b'external edit')
        self.assertEqual(self.store.job_effect(job_id),
                         {'kind': 'file.write', 'change_id': change_id, 'state': 'conflict'})
        self.assert_interrupted(job_id, change_id, 'change_id')
        with self.assertRaises(ValueError):
            self.files.undo(change_id)
        self.assertEqual(self.files.read('artifact.txt'), b'external edit')

    def test_legacy_running_job_with_matching_memory_remains_unknown(self):
        job_id = self.jobs.submit('memory.append', {'text': 'matching legacy text', 'source': 'test'})
        memory_id = self.store.remember('matching legacy text', 'test')
        with self.store.db:
            self.store.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        self.assert_recovery_does_not_replay(job_id, [])
        self.assert_unknown(job_id)
        self.assert_interrupted(job_id)
        self.assertEqual(self.store.db.execute('SELECT id FROM memories').fetchone()[0], memory_id)

    def test_legacy_running_file_job_with_matching_journal_remains_unknown(self):
        job_id = self.jobs.submit('file.write', {'path': 'legacy.txt', 'text': 'matching legacy bytes'})
        change_id = self.files.change('legacy.txt', b'matching legacy bytes')
        with self.store.db:
            self.store.db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
        self.assert_recovery_does_not_replay(job_id, [])
        self.assert_unknown(job_id)
        self.assert_interrupted(job_id)
        self.assertEqual(self.files.read('legacy.txt'), b'matching legacy bytes')
        self.assertEqual(self.store.db.execute('SELECT id FROM changes').fetchone()[0], change_id)

    def test_direct_operations_and_supersession_create_no_job_links(self):
        first = self.store.remember('first synthetic memory')
        second = self.store.remember('correction', supersedes=first)
        change_id = self.files.change('direct.txt', b'original')
        undo_id = self.files.undo(change_id)
        self.assertEqual(self.count('job_effects'), 0)
        self.assertIsNone(self.files.snapshot('direct.txt'))
        memory = self.store.db.execute('SELECT supersedes FROM memories WHERE id=?', (second,)).fetchone()
        self.assertEqual(memory['supersedes'], first)
        self.assertEqual(self.store.db.execute('SELECT kind FROM changes WHERE id=?', (undo_id,)).fetchone()[0],
                         'undo:' + change_id)

    def test_undo_preserves_job_origin_and_exposes_original_change_as_undone(self):
        self.files.change('artifact.txt', b'before')
        job_id = self.jobs.submit('file.write', {'path': 'artifact.txt', 'text': 'after'})
        result = self.jobs.run_one()
        self.assertIn(result['status'], {'completed', 'completed_over_budget'})
        change_id = result['result']['change_id']
        self.assertEqual(self.effect_row(job_id)['change_id'], change_id)
        undo_id = self.files.undo(change_id)
        self.assertEqual(self.files.read('artifact.txt'), b'before')
        self.assertEqual(self.store.job_effect(job_id),
                         {'kind': 'file.write', 'change_id': change_id, 'state': 'undone'})
        self.assertEqual(self.count('job_effects'), 1)
        self.assertNotEqual(change_id, undo_id)
        history = next(row for row in self.store.rows('jobs') if row['id'] == job_id)
        self.assertEqual(history['effect']['state'], 'undone')

    def test_applied_job_refuses_undo_after_external_edit(self):
        job_id = self.jobs.submit('file.write', {'path': 'artifact.txt', 'text': 'after'})
        result = self.jobs.run_one()
        change_id = result['result']['change_id']
        (self.files.root / 'artifact.txt').write_bytes(b'external edit')
        with self.assertRaises(ValueError):
            self.files.undo(change_id)
        self.assertEqual(self.files.read('artifact.txt'), b'external edit')
        self.assertEqual(self.effect_row(job_id)['change_id'], change_id)

    def test_run_one_refuses_caller_transaction_before_sampling_or_starting_job(self):
        job_id = self.jobs.submit('memory.append', {'text': 'synthetic', 'source': 'test'})
        before = self.count('memories'), self.count('changes'), self.count('job_effects'), self.count('events')
        with self.assertRaises(AbortOuterTransaction):
            with self.store.db:
                self.store.event('test.caller_owned_transaction', {'id': job_id})
                self.assertTrue(self.store.db.in_transaction)
                with patch.object(self.jobs.memory_guard, 'sample', side_effect=AssertionError('must not sample')):
                    with self.assertRaisesRegex(RuntimeError, 'transaction ownership'):
                        self.jobs.run_one()
                self.assertTrue(self.store.db.in_transaction)
                self.assertEqual(self.row(job_id)['status'], 'queued')
                self.assert_unknown(job_id)
                raise AbortOuterTransaction()
        self.assertEqual((self.count('memories'), self.count('changes'),
                          self.count('job_effects'), self.count('events')), before)
        self.assertEqual(self.row(job_id)['status'], 'queued')

    def test_helpers_refuse_ambient_transaction_before_effect_or_nested_commit(self):
        for operation in ('memory', 'file'):
            with self.subTest(operation=operation):
                before = self.count('memories'), self.count('changes'), self.count('job_effects'), self.count('events')
                with self.assertRaises(AbortOuterTransaction):
                    with self.store.db:
                        self.store.event('test.outer', {'operation': operation})
                        self.assertTrue(self.store.db.in_transaction)
                        with self.assertRaises((ValueError, RuntimeError)):
                            if operation == 'memory':
                                self.store.remember('must not commit')
                            else:
                                self.files.change('ambient.txt', b'must not replace')
                        self.assertTrue(self.store.db.in_transaction)
                        raise AbortOuterTransaction()
                self.assertEqual((self.count('memories'), self.count('changes'),
                                  self.count('job_effects'), self.count('events')), before)
                self.assertIsNone(self.files.snapshot('ambient.txt'))

    def test_effect_audit_failure_rolls_back_effect_and_origin_link(self):
        for action, args, failed_event in (
                ('memory.append', {'text': 'synthetic', 'source': 'test'}, 'memory.append'),
                ('file.write', {'path': 'failed.txt', 'text': 'synthetic'}, 'file.prepared')):
            with self.subTest(action=action):
                job_id = self.jobs.submit(action, args)
                before = self.count('memories'), self.count('changes')
                original = self.store.event
                def fail_event(kind, payload):
                    if kind == failed_event:
                        raise sqlite3.OperationalError('synthetic audit failure')
                    return original(kind, payload)
                with patch.object(self.store, 'event', side_effect=fail_event):
                    result = self.jobs.run_one()
                self.assertEqual(result['status'], 'failed')
                self.assertEqual((self.count('memories'), self.count('changes')), before)
                self.assert_unknown(job_id)
                self.assertIsNone(self.files.snapshot('failed.txt'))

    def test_invalid_origin_link_rolls_back_insert_and_never_replaces_bytes(self):
        before = self.count('memories'), self.count('changes'), self.count('job_effects'), self.count('events')
        with self.assertRaises((sqlite3.IntegrityError, ValueError)):
            self.store.remember('synthetic', job_id='missing-job')
        self.assertEqual((self.count('memories'), self.count('changes'),
                          self.count('job_effects'), self.count('events')), before)
        with self.assertRaises((sqlite3.IntegrityError, ValueError)):
            self.files.change('invalid-origin.txt', b'synthetic', job_id='missing-job')
        self.assertEqual((self.count('memories'), self.count('changes'),
                          self.count('job_effects'), self.count('events')), before)
        self.assertIsNone(self.files.snapshot('invalid-origin.txt'))

    def test_applied_audit_failure_retains_link_for_byte_reconciliation(self):
        job_id = self.jobs.submit('file.write', {'path': 'artifact.txt', 'text': 'after'})
        original = self.store.event
        def fail_event(kind, payload):
            if kind == 'file.applied':
                raise sqlite3.OperationalError('synthetic applied-audit failure')
            return original(kind, payload)
        with patch.object(self.store, 'event', side_effect=fail_event):
            result = self.jobs.run_one()
        self.assertEqual(result['status'], 'failed')
        change_id = self.effect_row(job_id)['change_id']
        self.assertEqual(result['result']['change_id'], change_id)
        self.assertEqual(self.files.read('artifact.txt'), b'after')
        self.assertEqual(self.store.job_effect(job_id)['state'], 'prepared')
        self.assertEqual(self.files.recover(), [{'id': change_id, 'status': 'applied'}])
        self.assertEqual(self.jobs.recover(), [])
        self.assertEqual(self.files.recover(), [])
        self.assertEqual(self.row(job_id)['status'], 'failed')
        self.assertEqual(self.store.job_effect(job_id)['state'], 'applied')

    def test_manual_controls_and_resource_deferral_precede_effect_creation(self):
        job_id = self.jobs.submit('memory.append', {'text': 'synthetic', 'source': 'test'}, ram_mib=64)
        self.assertEqual(self.jobs.control(job_id, 'pause'), 'paused')
        self.assertEqual(self.jobs.run_one(), {'status': 'idle'})
        self.assert_unknown(job_id)
        self.assertEqual(self.jobs.control(job_id, 'resume'), 'queued')
        self.jobs.memory_guard = Guard(allow=False)
        self.assertEqual(self.jobs.run_one()['status'], 'deferred_memory_pressure')
        self.assertEqual(self.row(job_id)['status'], 'queued')
        self.assert_unknown(job_id)
        self.jobs.memory_guard = Guard(available=0)
        self.assertEqual(self.jobs.run_one()['status'], 'deferred_resource_budget')
        self.assertEqual(self.row(job_id)['status'], 'queued')
        self.assert_unknown(job_id)
        self.assertEqual(self.jobs.control(job_id, 'cancel'), 'cancelled')
        self.assertEqual(self.count('memories'), 0)
        self.assertEqual(self.jobs.run_one(), {'status': 'idle'})


if __name__ == '__main__':
    unittest.main()
