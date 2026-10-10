"""Synthetic bounded recovery-isolation tests; all authored, presently UNRUN.

No subprocess, GUI, native permission mutation, model, provider or personal
database is used. PermissionError is injected at the snapshot boundary so the
same cases can run through the native Windows Files factory.
"""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aster import __main__ as cli
from aster.dashboard import Dashboard
from aster.files import Files, MAX_BYTES
from aster.jobs import Jobs
from aster.lifecycle import Lifecycle
from aster.storage import Store


class NoJobExecution:
    def sample(self, force=False):
        raise AssertionError('Recovery must not execute or admit a job')


class FailJournalUpdate:
    """Delegate real transactions; fail only one prepared-row ledger update."""
    def __init__(self, connection, change_id):
        self.connection, self.change_id = connection, change_id

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, kind, value, traceback):
        return self.connection.__exit__(kind, value, traceback)

    def execute(self, sql, parameters=()):
        statement = ' '.join(sql.upper().split())
        if (statement.startswith('UPDATE CHANGES ') and 'STATUS' in statement
                and parameters and parameters[-1] == self.change_id):
            raise sqlite3.OperationalError('synthetic journal bookkeeping failure')
        return self.connection.execute(sql, parameters)


class RecoveryIsolationTests(unittest.TestCase):
    @contextmanager
    def fixture(self, entry, position):
        with tempfile.TemporaryDirectory() as temporary:
            case = {'entry': entry, 'root': Path(temporary) / 'state',
                    'store': None, 'files': None, 'jobs': None,
                    'life': None, 'dashboard': None}
            try:
                self.open_case(case)
                store, files, jobs = case['store'], case['files'], case['jobs']
                case['identity'] = store.identity()
                case['paths'] = ['row-' + str(index) + '.txt' for index in range(3)]
                case['before'] = [b'before-0', b'before-1', b'before-2']
                case['after'] = [b'after-0', b'after-1', b'after-2']
                case['actual'] = [b'after-0', b'before-1', b'external-conflict-2']
                case['outcomes'] = ['applied', 'not_applied', 'conflict']
                case['position'] = position
                case['ids'] = []
                for index, path in enumerate(case['paths']):
                    files.change(path, case['before'][index])
                    linked_job = None
                    if index == position:
                        linked_job = jobs.submit('file.write',
                            {'path': path, 'text': case['after'][index].decode('ascii')})
                        case['linked_job'] = linked_job
                        with store.db:
                            store.db.execute("UPDATE jobs SET status='running' WHERE id=?",
                                             (linked_job,))
                    # Stage an interrupted operation through the real durable
                    # preparation/link transaction, without executing a job.
                    with patch.object(files, '_replace',
                                      side_effect=PermissionError('synthetic preparation stop')):
                        with self.assertRaises(PermissionError):
                            files.change(path, case['after'][index], job_id=linked_job)
                    row = store.db.execute(
                        "SELECT * FROM changes WHERE path=? AND status='prepared'", (path,)).fetchone()
                    case['ids'].append(row['id'])
                    (files.root / path).write_bytes(case['actual'][index])
                case['prepared_rows'] = {
                    row['id']: dict(row) for row in store.db.execute(
                        "SELECT * FROM changes WHERE status='prepared'")}
                case['unrelated_job'] = jobs.submit('memory.append',
                    {'text': 'synthetic unrelated interrupted job', 'source': 'unit-test'})
                with store.db:
                    store.db.execute("UPDATE jobs SET status='running' WHERE id=?",
                                     (case['unrelated_job'],))
                self.assertEqual([row['id'] for row in store.db.execute(
                    "SELECT * FROM changes WHERE status='prepared' ORDER BY rowid")], case['ids'])
                case['file_type'] = type(files)
                if entry == 'dashboard':
                    life = Lifecycle(store, wall_clock=lambda: 1000.0, monotonic=lambda: 10.0)
                    life.start()
                    dashboard = Dashboard.__new__(Dashboard)
                    dashboard.store, dashboard.files, dashboard.jobs = store, files, jobs
                    dashboard.lifecycle = life
                    dashboard._pending, dashboard._closed = None, False
                    case['life'], case['dashboard'] = life, dashboard
                self.assert_no_added_effects(case)
                yield case
            finally:
                self.close_case(case)

    def open_case(self, case):
        case['store'] = Store(case['root'])
        try:
            case['files'] = Files(case['store'])
            case['jobs'] = Jobs(case['store'], case['files'], memory_guard=NoJobExecution())
        except BaseException:
            self.close_case(case)
            raise

    def close_case(self, case):
        life, files, store = case.get('life'), case.get('files'), case.get('store')
        case.update(life=None, files=None, store=None, jobs=None, dashboard=None)
        try:
            if life is not None:
                life.close(clean=True)
        finally:
            try:
                if files is not None:
                    files.close()
            finally:
                if store is not None:
                    store.close()

    def invoke(self, case, code=0, ledger_failure=None):
        if case['entry'] == 'dashboard':
            if ledger_failure is not None:
                case['store'].db = FailJournalUpdate(case['store'].db, ledger_failure)
            review = case['dashboard'].dispatch('prepare_recover')
            return case['dashboard'].dispatch('confirm', ticket=review['ticket'])
        self.close_case(case)
        output, error = io.StringIO(), io.StringIO()
        def open_cli_store(root):
            store = Store(root)
            if ledger_failure is not None:
                store.db = FailJournalUpdate(store.db, ledger_failure)
            return store
        try:
            with (patch.object(cli, 'Store', side_effect=open_cli_store),
                  patch.object(cli, 'Jobs', side_effect=lambda store, files:
                               Jobs(store, files, memory_guard=NoJobExecution())),
                  redirect_stdout(output), redirect_stderr(error)):
                actual_code = cli.main(['--state', str(case['root']), 'recover'])
        finally:
            self.open_case(case)
        self.assertEqual(actual_code, code, error.getvalue())
        if code == 2:
            self.assertEqual(output.getvalue(), '')
            return json.loads(error.getvalue())
        self.assertEqual(error.getvalue(), '')
        return json.loads(output.getvalue())

    @contextmanager
    def observe_recovery(self, case, denied_path=None):
        file_type = case['file_type']
        original_snapshot = file_type.snapshot
        calls = []
        def snapshot(files, path):
            calls.append(path)
            if path == denied_path:
                raise PermissionError('PRIVATE_SYNTHETIC_DETAIL ' + path)
            return original_snapshot(files, path)
        with (patch.object(file_type, 'snapshot', autospec=True, side_effect=snapshot),
              patch.object(file_type, '_replace',
                           side_effect=AssertionError('Recovery must never replace bytes')),
              patch.object(Jobs, 'run_one',
                           side_effect=AssertionError('Recovery must never replay jobs'))):
            yield calls

    def count(self, case, table):
        self.assertIn(table, {'changes', 'jobs', 'job_effects', 'memories', 'prompts'})
        return case['store'].db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def event_payloads(self, case, kind):
        return [json.loads(row[0]) for row in case['store'].db.execute(
            'SELECT payload FROM events WHERE kind=? ORDER BY seq', (kind,))]

    def states(self, case):
        return {row['id']: row['status'] for row in case['store'].db.execute(
            'SELECT id,status FROM changes WHERE id IN (?,?,?)', case['ids'])}

    def assert_no_added_effects(self, case):
        self.assertEqual(tuple(self.count(case, table) for table in
            ('changes', 'jobs', 'job_effects', 'memories', 'prompts')), (6, 2, 1, 0, 0))
        self.assertEqual(case['store'].identity(), case['identity'])

    def assert_bytes(self, case, expected):
        self.assertEqual([(case['files'].root / path).read_bytes()
                          for path in case['paths']], expected)

    def assert_required(self, case, report, required):
        if case['entry'] == 'dashboard':
            self.assertIs(report['lifecycle']['recovery_required'], required)
            self.assertIs(case['life'].status()['recovery_required'], required)
        else:
            self.assertIs(report['recovery_required'], required)

    def assert_interrupted_jobs(self, case, linked_state):
        for job_id in (case['linked_job'], case['unrelated_job']):
            row = case['store'].db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            self.assertEqual(row['status'], 'interrupted')
            result = json.loads(row['result'])
            self.assertIs(result['timing_unknown'], True)
            self.assertNotIn('elapsed_seconds', result)
            self.assertNotIn(result.get('status'), {'completed', 'completed_over_budget'})
            if job_id == case['linked_job']:
                self.assertEqual(result['change_id'], case['ids'][case['position']])
                self.assertEqual(result['effect'], {'kind': 'file.write',
                    'change_id': case['ids'][case['position']], 'state': linked_state})
            else:
                self.assertEqual(result['effect'], {'state': 'unknown', 'reason': 'no_durable_link'})
        self.assertEqual({item['id'] for item in self.event_payloads(case, 'job.interrupted')},
                         {case['linked_job'], case['unrelated_job']})
        self.assertEqual(len(self.event_payloads(case, 'job.interrupted')), 2)

    def exercise_fault(self, fault, position):
        for entry in ('dashboard', 'cli'):
            with self.subTest(entry=entry, fault=fault, position=position):
                with self.fixture(entry, position) as case:
                    fault_id, path = case['ids'][position], case['paths'][position]
                    actual = list(case['actual'])
                    if fault == 'oversize':
                        actual[position] = b'x' * (MAX_BYTES + 1)
                        (case['files'].root / path).write_bytes(actual[position])
                    denied_path = path if fault == 'permission' else None
                    ack = case['life'].acknowledge_recovery if case['life'] is not None else None
                    with self.observe_recovery(case, denied_path) as calls:
                        if ack is not None:
                            with patch.object(case['life'], 'acknowledge_recovery', wraps=ack) as acknowledge:
                                partial = self.invoke(case)
                            acknowledge.assert_not_called()
                        else:
                            partial = self.invoke(case, code=3)
                    self.assertEqual(calls, case['paths'])
                    expected = {'id': fault_id, 'status': 'unresolved',
                                'reason': 'snapshot_unavailable',
                                'error_type': 'ValueError' if fault == 'oversize' else 'PermissionError'}
                    results = {item['id']: item for item in partial['files']}
                    self.assertEqual(len(partial['files']), 3)
                    self.assertEqual(results[fault_id], expected)
                    for index, change_id in enumerate(case['ids']):
                        if index != position:
                            self.assertEqual(results[change_id],
                                             {'id': change_id, 'status': case['outcomes'][index]})
                    self.assertNotIn('PRIVATE_SYNTHETIC_DETAIL', json.dumps(partial))
                    self.assertNotIn(path, json.dumps(partial))
                    self.assertEqual(len(partial['interrupted_jobs']), 2)
                    self.assertEqual(set(partial['interrupted_jobs']),
                                     {case['linked_job'], case['unrelated_job']})
                    self.assert_required(case, partial, True)
                    self.assertEqual(self.states(case), {
                        change_id: 'prepared' if index == position else case['outcomes'][index]
                        for index, change_id in enumerate(case['ids'])})
                    self.assertEqual(dict(case['store'].db.execute(
                        'SELECT * FROM changes WHERE id=?', (fault_id,)).fetchone()),
                        case['prepared_rows'][fault_id])
                    self.assertEqual(case['store'].job_effect(case['linked_job']),
                        {'kind': 'file.write', 'change_id': fault_id, 'state': 'prepared'})
                    self.assert_interrupted_jobs(case, 'prepared')
                    receipt = case['store'].db.execute(
                        'SELECT result FROM jobs WHERE id=?', (case['linked_job'],)).fetchone()[0]
                    recovered = self.event_payloads(case, 'file.recovered')
                    self.assertEqual(len(recovered), 2)
                    self.assertEqual({item['id'] for item in recovered},
                                     set(case['ids']) - {fault_id})
                    self.assert_bytes(case, actual)
                    self.assert_no_added_effects(case)
                    if fault == 'oversize':
                        (case['files'].root / path).write_bytes(case['actual'][position])
                    with self.observe_recovery(case) as calls:
                        retry = self.invoke(case)
                    self.assertEqual(calls, [path])
                    self.assertEqual(retry['files'],
                                     [{'id': fault_id, 'status': case['outcomes'][position]}])
                    self.assertEqual(retry['interrupted_jobs'], [])
                    self.assert_required(case, retry, False)
                    self.assertEqual(self.states(case),
                                     dict(zip(case['ids'], case['outcomes'])))
                    self.assertEqual(case['store'].job_effect(case['linked_job']),
                        {'kind': 'file.write', 'change_id': fault_id,
                         'state': case['outcomes'][position]})
                    self.assertEqual(case['store'].db.execute(
                        'SELECT result FROM jobs WHERE id=?', (case['linked_job'],)).fetchone()[0], receipt)
                    self.assert_interrupted_jobs(case, 'prepared')
                    self.assert_bytes(case, case['actual'])
                    with self.observe_recovery(case) as calls:
                        again = self.invoke(case)
                    self.assertEqual(calls, [])
                    self.assertEqual(again['files'], [])
                    self.assertEqual(again['interrupted_jobs'], [])
                    self.assert_required(case, again, False)
                    self.assertEqual(len(self.event_payloads(case, 'file.recovered')), 3)
                    self.assert_interrupted_jobs(case, 'prepared')
                    self.assert_no_added_effects(case)

    def exercise_bookkeeping_failure(self, audit):
        for entry in ('dashboard', 'cli'):
            with self.subTest(entry=entry, failure='audit' if audit else 'sql'):
                with self.fixture(entry, 1) as case:
                    target = case['ids'][1]
                    original_event = Store.event
                    def event(store, kind, payload):
                        if audit and kind == 'file.recovered' and payload['id'] == target:
                            raise ValueError('synthetic audit validation failure')
                        return original_event(store, kind, payload)
                    expected_error = ValueError if audit else sqlite3.OperationalError
                    with self.observe_recovery(case) as calls:
                        with patch.object(Store, 'event', autospec=True, side_effect=event):
                            if entry == 'dashboard':
                                with self.assertRaises(expected_error):
                                    self.invoke(case, ledger_failure=None if audit else target)
                            else:
                                report = self.invoke(case, code=2,
                                                     ledger_failure=None if audit else target)
                                self.assertIn('error', report)
                                self.assertNotIn('files', report)
                    self.assertEqual(calls, case['paths'][:2])
                    self.assertEqual(self.states(case), {
                        case['ids'][0]: 'applied', case['ids'][1]: 'prepared',
                        case['ids'][2]: 'prepared'})
                    self.assertEqual(self.event_payloads(case, 'file.recovered'),
                                     [{'id': case['ids'][0], 'status': 'applied'}])
                    self.assertEqual(self.event_payloads(case, 'job.interrupted'), [])
                    for job_id in (case['linked_job'], case['unrelated_job']):
                        row = case['store'].db.execute(
                            'SELECT status,result FROM jobs WHERE id=?', (job_id,)).fetchone()
                        self.assertEqual((row['status'], row['result']), ('running', None))
                    self.assertEqual(case['store'].job_effect(case['linked_job']),
                                     {'kind': 'file.write', 'change_id': target, 'state': 'prepared'})
                    if case['life'] is not None:
                        self.assertTrue(case['life'].status()['recovery_required'])
                    self.assert_bytes(case, case['actual'])
                    self.assert_no_added_effects(case)
                    # Remove only the injected DB failure; preserve the real
                    # first-row commit and retry the two still-prepared rows.
                    if isinstance(case['store'].db, FailJournalUpdate):
                        case['store'].db = case['store'].db.connection
                    with self.observe_recovery(case) as calls:
                        retry = self.invoke(case)
                    self.assertEqual(calls, case['paths'][1:])
                    self.assertEqual(retry['files'], [
                        {'id': case['ids'][1], 'status': 'not_applied'},
                        {'id': case['ids'][2], 'status': 'conflict'}])
                    self.assertEqual(len(retry['interrupted_jobs']), 2)
                    self.assertEqual(set(retry['interrupted_jobs']),
                                     {case['linked_job'], case['unrelated_job']})
                    self.assert_required(case, retry, False)
                    self.assert_interrupted_jobs(case, 'not_applied')
                    with self.observe_recovery(case) as calls:
                        again = self.invoke(case)
                    self.assertEqual(calls, [])
                    self.assertEqual(again['files'], [])
                    self.assertEqual(again['interrupted_jobs'], [])
                    self.assert_required(case, again, False)
                    self.assertEqual(len(self.event_payloads(case, 'file.recovered')), 3)
                    self.assert_interrupted_jobs(case, 'not_applied')
                    self.assert_bytes(case, case['actual'])
                    self.assert_no_added_effects(case)

    def test_oversize_first(self):
        self.exercise_fault('oversize', 0)

    def test_oversize_middle(self):
        self.exercise_fault('oversize', 1)

    def test_oversize_last(self):
        self.exercise_fault('oversize', 2)

    def test_permission_first(self):
        self.exercise_fault('permission', 0)

    def test_permission_middle(self):
        self.exercise_fault('permission', 1)

    def test_permission_last(self):
        self.exercise_fault('permission', 2)

    def test_sql_bookkeeping_failure_propagates(self):
        self.exercise_bookkeeping_failure(audit=False)

    def test_audit_value_error_is_not_a_snapshot_fault(self):
        self.exercise_bookkeeping_failure(audit=True)


if __name__ == '__main__':
    unittest.main()
