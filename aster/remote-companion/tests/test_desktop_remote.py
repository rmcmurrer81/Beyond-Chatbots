"""Live loopback transport and single-writer desktop coexistence acceptance."""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from aster.dashboard import DashboardWorker
from aster.storage import Store
from aster_remote.delivery import PollingStopped
from aster_remote.poller import receive_to_worker_once
from aster_remote.workstation import receive_once
import test_remote as original_remote

# Correctness budget for 50 serialized HTTP/durable-commit deliveries, not a
# product latency promise. Keep unrelated interaction/shutdown deadlines intact.
BATCH_COMPLETION_TIMEOUT = 30


class DesktopRemoteTests(unittest.TestCase):
    def setUp(self):
        original_remote.RemoteTests.setUp(self)
        self.workers = []

    def tearDown(self):
        for worker in self.workers:
            worker.close()
            self.assertTrue(worker.wait_closed(12), 'desktop or outbound thread leaked')
        original_remote.RemoteTests.tearDown(self)

    def until(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.005)
        self.fail('condition did not become true')

    def wait_for_batch(self, worker, expected=50, *, timeout=BATCH_COMPLETION_TIMEOUT,
                       pump=None, ready=lambda: True):
        start = time.monotonic()
        next_report = 0
        while True:
            if pump is not None:
                pump()
            elapsed = time.monotonic() - start
            status = worker._poller.status()
            owner_alive = worker.alive
            observer_ready = bool(ready())
            fatal = ('state owner exited' if not owner_alive else
                     'poller stopped' if status.get('state') == 'stopped' else None)
            # Native UI construction returns before worker schema initialization.
            # Unknown is not zero; do not query until actual readiness, nor after
            # a terminal worker state. SQL errors after readiness must propagate.
            prompts = self.count('prompts') if observer_ready and not fatal else None
            progress = {'elapsed_seconds': round(elapsed, 3), 'expected': expected,
                        'prompts': prompts, 'observer_ready': observer_ready, 'poller': status,
                        'queued': worker._remote.qsize(), 'state_owner_alive': owner_alive}
            if (prompts is not None and prompts > expected) or status.get('received', 0) > expected:
                self.fail('batch overdelivery: ' + json.dumps(progress, sort_keys=True))
            complete = (observer_ready and prompts == expected and
                        status.get('received') == expected)
            expired = elapsed >= timeout
            if elapsed >= next_report or complete or expired or fatal:
                print('BATCH_PROGRESS ' + json.dumps(progress, sort_keys=True), flush=True)
                next_report = elapsed + 1
            if fatal:
                self.fail('batch ' + fatal + ': ' + json.dumps(progress, sort_keys=True))
            if complete:
                return elapsed
            if expired:
                self.fail(f'batch delivery deadline ({timeout:g}s): ' +
                          json.dumps(progress, sort_keys=True))
            # Read-only observation at 20 Hz avoids repeatedly opening a DB at
            # the 200 Hz cadence used for short UI handoffs on slower CI disks.
            time.sleep(min(0.05, max(0, timeout - elapsed)))

    @contextmanager
    def delivery_timing(self, scope, expected=50, *, proposed_goal=None):
        """Observe commit-before-receipt and completed HTTP receipt/ack stages."""
        started = time.monotonic()
        timing = {'scope': scope, 'expected': expected, 'receipt_count': 0,
                  'ack_count': 0, 'first_commit_observed_seconds': None,
                  'last_commit_observed_seconds': None, 'last_receipt_seconds': None,
                  'last_ack_seconds': None, 'proposed_latency_goal_seconds': proposed_goal}
        original = self.pc.call
        def observed(path, data=None):
            if path == '/v1/messages':
                elapsed = time.monotonic() - started
                if timing['first_commit_observed_seconds'] is None:
                    timing['first_commit_observed_seconds'] = elapsed
                if self.count('prompts') == expected and timing['last_commit_observed_seconds'] is None:
                    timing['last_commit_observed_seconds'] = elapsed
            result = original(path, data)
            elapsed = time.monotonic() - started
            if path == '/v1/messages':
                timing['receipt_count'] += 1
                timing['last_receipt_seconds'] = elapsed
            elif path == '/v1/ack':
                timing['ack_count'] += 1
                timing['last_ack_seconds'] = elapsed
            return result
        try:
            with patch.object(self.pc, 'call', side_effect=observed):
                yield timing
        finally:
            receipt, ack = timing['last_receipt_seconds'], timing['last_ack_seconds']
            timing['proposed_latency_assessment'] = (
                'not_applicable_startup_backlog' if proposed_goal is None else
                'incomplete' if receipt is None or ack is None else
                'met' if max(receipt, ack) <= proposed_goal else 'missed')
            print('DELIVERY_TIMING ' + json.dumps({key: round(value, 3) if type(value) is float
                  else value for key, value in timing.items()}, sort_keys=True), flush=True)

    def completion(self, worker, action):
        result = []
        def get():
            item = worker.poll()
            if item is not None and item.action == action:
                result.append(item)
                return True
        self.until(get)
        self.assertFalse(result[0].error, result[0].error)
        return result[0]

    def worker(self, **kwargs):
        worker = DashboardWorker(self.path / 'aster', **kwargs)
        self.workers.append(worker)
        self.completion(worker, 'ready')
        return worker

    def command(self, worker, action, **kwargs):
        self.assertTrue(worker.submit(action, **kwargs))
        return self.completion(worker, action)

    def count(self, table, where='1=1'):
        # SQLite's own context manager ends transactions but does not close.
        with closing(sqlite3.connect(
                (self.path / 'aster' / 'aster.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            return db.execute('SELECT count(*) FROM ' + table + ' WHERE ' + where).fetchone()[0]

    def test_count_helper_closes_read_connection_on_success_and_error(self):
        self.worker()
        connect = sqlite3.connect
        for table in ('prompts', 'missing_table_for_close_regression'):
            with self.subTest(table=table):
                opened = []
                def capture(*args, **kwargs):
                    connection = connect(*args, **kwargs)
                    opened.append(connection)  # Keep alive; do not rely on GC.
                    return connection
                try:
                    with patch.object(sqlite3, 'connect', side_effect=capture):
                        if table == 'prompts':
                            self.assertEqual(self.count(table), 0)
                        else:
                            with self.assertRaises(sqlite3.OperationalError):
                                self.count(table)
                    self.assertEqual(len(opened), 1)
                    with self.assertRaisesRegex(sqlite3.ProgrammingError, 'closed'):
                        opened[0].execute('SELECT 1')
                finally:
                    for connection in opened:
                        connection.close()

    def test_count_helper_explicitly_closes_on_success_execute_and_fetch_failure(self):
        for stage in ('success', 'execute', 'fetch'):
            with self.subTest(stage=stage):
                connection = MagicMock(spec=sqlite3.Connection)
                connection.__enter__.return_value = connection
                connection.__exit__.return_value = False
                cursor = connection.execute.return_value
                cursor.fetchone.return_value = (0,)
                if stage == 'execute':
                    connection.execute.side_effect = sqlite3.OperationalError('execute failed')
                elif stage == 'fetch':
                    cursor.fetchone.side_effect = sqlite3.OperationalError('fetch failed')
                with patch.object(sqlite3, 'connect', return_value=connection):
                    if stage == 'success':
                        self.assertEqual(self.count('prompts'), 0)
                    else:
                        with self.assertRaisesRegex(sqlite3.OperationalError, stage + ' failed'):
                            self.count('prompts')
                connection.execute.assert_called_once_with('SELECT count(*) FROM prompts WHERE 1=1')
                connection.close.assert_called_once_with()

    def send(self, item=None):
        return self.phone.call('/v1/messages', item or self.item)

    def test_fifty_live_messages_with_desktop_open_one_writer_no_jobs(self):
        for i in range(50):
            self.send({**self.item, 'id': format(i, '032x'),
                       'body': 'file.write: ' + ('é' * 2042)})
        with self.delivery_timing('startup_backlog_50') as timing:
            worker = self.worker(remote_client=self.pc)
            self.wait_for_batch(worker)
        self.assertEqual(timing['receipt_count'], 50)
        self.assertEqual(timing['ack_count'], 50)
        self.assertEqual(len(self.phone.call('/v1/inbox')['messages']), 50)
        self.assertEqual(self.pc.call('/v1/inbox')['messages'], [])
        result = self.command(worker, 'snapshot')
        self.assertEqual(result.snapshot['pending_requests'], 50)
        self.assertTrue(result.snapshot['remote']['enabled'])
        self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 50)
        self.assertEqual(self.count('jobs'), 0)
        self.assertEqual(self.count('changes'), 0)
        self.assertEqual(self.count('memories'), 0)
        with self.assertRaisesRegex(RuntimeError, 'Another Aster'):
            Store(self.path / 'aster')

    def test_delayed_fifty_message_batch_exceeds_five_seconds_without_duplicates(self):
        items = [{**self.item, 'id': format(i, '032x')} for i in range(50)]
        for item in items:
            self.send(item)
        original = self.pc.call
        receipts, acknowledgements = [], []
        delay_finished = threading.Event()
        delay_start, delay_elapsed = [], []
        def delayed(path, data=None):
            if path == '/v1/messages':
                if not delay_start:
                    delay_start.append(time.monotonic())
                    # Deliberately hold the first receipt longer than the old
                    # five-second correctness wait; no runtime timeout changes.
                    delay_finished.wait(5.25)
                    delay_elapsed.append(time.monotonic() - delay_start[0])
                receipts.append(data['id'])
            response = original(path, data)
            if path == '/v1/ack':
                acknowledgements.append(data['id'])
            return response
        worker = None
        try:
            with patch.object(self.pc, 'call', side_effect=delayed), \
                    self.delivery_timing('synthetic_delayed_startup_backlog_50') as timing:
                worker = self.worker(remote_client=self.pc)
                self.wait_for_batch(worker)
                # Startup/ready scheduling can overlap the hold. Measure the
                # injected delay itself, not time remaining after ready arrives.
                self.assertGreater(delay_elapsed[0], 5)
                self.assertGreater(timing['last_receipt_seconds'] -
                                   timing['first_commit_observed_seconds'], 5)
                print('DELAYED_HOLD_SECONDS ' + str(round(delay_elapsed[0], 3)), flush=True)
                worker.submit_remote(items[0]).result(3)  # Delayed duplicate replay.
                self.assertEqual(self.count('prompts'), 50)
                self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 50)
                self.assertEqual(self.count('jobs'), 0)
                self.assertEqual(timing['receipt_count'], 50)
                self.assertEqual(timing['ack_count'], 50)
                self.assertEqual(len(receipts), 50)
                self.assertEqual(len(set(receipts)), 50)
                self.assertEqual(acknowledgements, receipts)
                self.assertEqual(self.pc.call('/v1/inbox')['messages'], [])
                self.assertEqual(len(self.phone.call('/v1/inbox')['messages']), 50)
        finally:
            delay_finished.set()
            if worker is not None:
                started = time.monotonic()
                worker.close()
                self.assertTrue(worker.wait_closed(12), 'delayed fixture leaked a worker')
                print('DELAYED_BATCH_SHUTDOWN_SECONDS ' +
                      str(round(time.monotonic() - started, 3)), flush=True)

    def test_already_open_single_message_proposed_twenty_second_latency_goal(self):
        worker = self.worker(remote_client=self.pc)
        # Confirm an empty pass completed, so this measures a newly submitted
        # message against an already-open idle poller, not startup backlog drain.
        self.until(lambda: worker._poller.status()['state'] == 'polling')
        with self.delivery_timing('already_open_single_message', expected=1,
                                  proposed_goal=20) as timing:
            self.send()
            self.wait_for_batch(worker, expected=1)
        self.assertEqual(timing['receipt_count'], 1)
        self.assertEqual(timing['ack_count'], 1)
        self.assertLessEqual(timing['last_receipt_seconds'], 20, 'proposed receipt goal missed')
        self.assertLessEqual(timing['last_ack_seconds'], 20, 'proposed ack goal missed')
        self.assertEqual(self.count('prompts'), 1)
        self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 1)
        self.assertEqual(self.count('jobs'), 0)
        self.assertEqual(self.pc.call('/v1/inbox')['messages'], [])
        self.assertEqual(len(self.phone.call('/v1/inbox')['messages']), 1)

    def test_batch_deadline_stays_bounded_and_reports_progress(self):
        from unittest.mock import Mock
        worker = self.worker(remote_client=Mock(call=Mock(return_value={'messages': []})))
        for observer_ready in (False, True):
            with self.subTest(observer_ready=observer_ready), \
                    patch.object(self, 'count', wraps=self.count) as count:
                with self.assertRaisesRegex(AssertionError, 'batch delivery deadline') as failure:
                    self.wait_for_batch(worker, timeout=0.05, ready=lambda: observer_ready)
                observed = '"prompts": 0' if observer_ready else '"prompts": null'
                for field in ('"elapsed_seconds"', '"expected": 50', observed,
                              '"observer_ready"', '"poller"', '"queued"', '"state_owner_alive"'):
                    self.assertIn(field, str(failure.exception))
                if not observer_ready:
                    count.assert_not_called()

    def test_batch_wait_fails_immediately_if_owner_exits_or_poller_stops(self):
        from unittest.mock import Mock
        for failure in ('state owner exited', 'poller stopped'):
            with self.subTest(failure=failure):
                worker = self.worker(remote_client=Mock(call=Mock(return_value={'messages': []})))
                if failure == 'state owner exited':
                    worker.close()
                    self.assertTrue(worker.wait_closed(12))
                else:
                    worker._poller.stop()
                    worker._poller.thread.join(3)
                    self.assertFalse(worker._poller.thread.is_alive())
                    self.assertTrue(worker.alive)
                # No elapsed-time assumption: any sleep proves it did not fail fast.
                with patch('time.sleep', side_effect=AssertionError('unexpected wait after terminal state')), \
                        patch.object(self, 'count', side_effect=AssertionError('read after terminal state')) as count:
                    with self.assertRaisesRegex(AssertionError, 'batch ' + failure):
                        self.wait_for_batch(worker)
                    count.assert_not_called()
                worker.close()
                self.assertTrue(worker.wait_closed(12))

    def test_batch_observation_waits_for_ready_before_reading_preschema_database(self):
        from aster.dashboard import Dashboard
        state = self.path / 'aster'
        state.mkdir()
        with closing(sqlite3.connect(state / 'aster.sqlite3')):
            pass  # A real empty DB exists, but prompts has not been created.
        entered, release = threading.Event(), threading.Event()
        class GatedDashboard(Dashboard):
            def __init__(_self, root):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('test startup gate was not released')
                super().__init__(root)
        self.send()
        worker = DashboardWorker(state, controller_factory=GatedDashboard, remote_client=self.pc)
        self.workers.append(worker)
        seen_ready, pumps = [False], [0]
        try:
            self.assertTrue(entered.wait(3))
            with patch.object(self, 'count', wraps=self.count) as count, \
                    patch('builtins.print', wraps=print) as output:
                def pump():
                    pumps[0] += 1
                    if pumps[0] == 3:
                        count.assert_not_called()
                        release.set()
                    completion = worker.poll()
                    if completion is not None:
                        self.assertFalse(completion.error, completion.error)
                        if completion.action == 'ready':
                            seen_ready[0] = True
                self.wait_for_batch(worker, expected=1, pump=pump, ready=lambda: seen_ready[0])
                self.assertTrue(seen_ready[0])
                self.assertTrue(count.called)
                progress = [json.loads(call.args[0].split(' ', 1)[1])
                            for call in output.call_args_list
                            if call.args and call.args[0].startswith('BATCH_PROGRESS ')]
                self.assertTrue(any(p['prompts'] is None and not p['observer_ready'] for p in progress))
            self.assertEqual(self.count('prompts'), 1)
            self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 1)
        finally:
            release.set()
            worker.close()
            self.assertTrue(worker.wait_closed(12))

    def test_batch_observation_surfaces_database_error_after_ready(self):
        from unittest.mock import Mock
        worker = self.worker(remote_client=Mock(call=Mock(return_value={'messages': []})))
        with patch.object(self, 'count', side_effect=sqlite3.OperationalError('ready-state database failure')):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'ready-state database failure'):
                self.wait_for_batch(worker, ready=lambda: True)

    def test_standalone_second_writer_still_rejected_message_unacked(self):
        self.worker()
        self.send()
        with self.assertRaisesRegex(RuntimeError, 'Another Aster'):
            receive_once(self.pc, self.path / 'aster')
        self.assertEqual(len(self.pc.call('/v1/inbox')['messages']), 1)
        self.assertEqual(self.count('prompts'), 0)

    def test_lost_post_response_and_ack_retry_exactly_once(self):
        for stage in ('/v1/messages', '/v1/ack'):
            with self.subTest(stage=stage):
                item = {**self.item, 'id': ('b' if stage == '/v1/messages' else 'c') * 32}
                self.send(item)
                worker = self.workers[0] if self.workers else self.worker()
                original = self.pc.call
                failed = []
                def lose_response(path, data=None):
                    response = original(path, data)
                    if path == stage and not failed:
                        failed.append(True)
                        raise OSError('lost response after successful server commit')
                    return response
                with patch.object(self.pc, 'call', side_effect=lose_response):
                    with self.assertRaises(OSError):
                        receive_to_worker_once(self.pc, worker)
                receive_to_worker_once(self.pc, worker)
                # Also replay directly after ack, as a delayed duplicate inbox.
                worker.submit_remote(item).result(3)
        self.assertEqual(self.count('prompts'), 2)
        self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 2)
        self.assertEqual(len(self.phone.call('/v1/inbox')['messages']), 2)

    def test_commit_visible_before_receipt_or_ack(self):
        self.send()
        worker = self.worker()
        original = self.pc.call
        observations = []
        def observe(path, data=None):
            if path != '/v1/inbox':
                observations.append(path)
                self.assertEqual(self.count('prompts'), 1)
                self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 1)
            return original(path, data)
        with patch.object(self.pc, 'call', side_effect=observe):
            self.assertEqual(receive_to_worker_once(self.pc, worker), 1)
        self.assertEqual(observations, ['/v1/messages', '/v1/ack'])

    def test_crash_after_commit_before_receipt_survives_restart(self):
        self.send()
        script = '''
import json, os, sys, time
from aster.dashboard import DashboardWorker
from aster_remote.poller import receive_to_worker_once
item = json.loads(sys.argv[2])
class CrashClient:
    def call(self, path, data=None):
        if path == '/v1/inbox': return {'messages': [item]}
        os._exit(73)
worker = DashboardWorker(sys.argv[1])
while worker.poll() is None: time.sleep(0.005)
receive_to_worker_once(CrashClient(), worker)
'''
        child = subprocess.run([sys.executable, '-c', script, str(self.path / 'aster'), json.dumps(self.item)],
                               text=True, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 73, child.stderr)
        self.assertEqual(self.count('prompts'), 1)
        worker = self.worker()
        self.assertEqual(receive_to_worker_once(self.pc, worker), 1)
        self.assertEqual(self.count('prompts'), 1)
        self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 1)
        self.assertEqual(self.count('jobs'), 0)

    def test_pending_confirmation_defers_queue_and_keeps_ticket_valid(self):
        self.send()
        worker = self.worker()
        review = self.command(worker, 'prepare_write', path='local.txt', content='approved locally').result
        result = []
        thread = threading.Thread(target=lambda: result.append(receive_to_worker_once(self.pc, worker)))
        thread.start()
        try:
            self.until(lambda: worker._remote.qsize() == 1)
            self.assertEqual(self.count('prompts'), 0)
            self.assertEqual(len(self.pc.call('/v1/inbox')['messages']), 1)
            self.assertEqual(self.phone.call('/v1/inbox')['messages'], [])
            self.command(worker, 'confirm', ticket=review['ticket'])
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [1])
            self.assertEqual(self.count('prompts'), 1)
            self.assertEqual(self.count('changes'), 1)
        finally:
            worker.close()
            thread.join(5)

    def test_full_queue_rejects_without_ack_and_shutdown_preserves_retry(self):
        self.send()
        worker = self.worker(remote_queue_capacity=1)
        self.command(worker, 'prepare_write', path='local.txt', content='never approved')
        future = worker.submit_remote({**self.item, 'id': 'd' * 32})
        with self.assertRaises(queue.Full):
            receive_to_worker_once(self.pc, worker)
        self.assertEqual(worker._remote.qsize(), 1)
        self.assertEqual(self.count('prompts'), 0)
        self.assertEqual(len(self.pc.call('/v1/inbox')['messages']), 1)
        worker.close()
        self.assertTrue(worker.wait_closed(3))
        with self.assertRaisesRegex(RuntimeError, 'closed before remote commit'):
            future.result(1)
        with self.assertRaisesRegex(RuntimeError, 'closing'):
            worker.submit_remote(self.item)
        replacement = self.worker()
        self.assertEqual(receive_to_worker_once(self.pc, replacement), 1)
        self.assertEqual(self.count('prompts'), 1)
        self.assertEqual(self.count('changes'), 0)

    def test_expiry_rechecked_after_pending_confirmation(self):
        worker = self.worker()
        review = self.command(worker, 'prepare_write', path='local.txt', content='x').result
        with patch('aster_remote.delivery.time.time', return_value=1000):
            future = worker.submit_remote({**self.item, 'expires': 1001})
        self.command(worker, 'dismiss', ticket=review['ticket'])
        with self.assertRaisesRegex(ValueError, 'expired'):
            future.result(3)
        self.assertEqual(self.count('prompts'), 0)

    def test_remote_completion_does_not_release_local_single_flight(self):
        worker = self.worker()
        self.assertTrue(worker.submit('snapshot'))
        worker.submit_remote(self.item).result(3)
        self.assertFalse(worker.submit('save_request', prompt='must not slip through'))
        self.completion(worker, 'snapshot')
        self.assertTrue(worker.submit('snapshot'))
        self.completion(worker, 'snapshot')

    def test_validation_conflict_and_mutable_input_fail_closed(self):
        worker = self.worker()
        for change in ({'action': 'confirm'}, {'body': 'é' * 4096}, {'expires': float('nan')},
                       {'expires': True}, {'id': '../escape'}, {'body': ''}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                worker.submit_remote({**self.item, **change})
        review = self.command(worker, 'prepare_write', path='a', content='b').result
        mutable = dict(self.item)
        future = worker.submit_remote(mutable)
        mutable['body'] = 'changed after enqueue'
        self.command(worker, 'dismiss', ticket=review['ticket'])
        future.result(3)
        with self.assertRaisesRegex(ValueError, 'ID conflict'):
            worker.submit_remote({**self.item, 'body': 'changed replay'}).result(3)
        detail = self.command(worker, 'history', kind='prompts', item_id='remote-' + self.item['id'])
        self.assertEqual(detail.result['body'], self.item['body'])
        self.assertEqual(self.count('prompts'), 1)
        self.assertEqual(self.count('jobs'), 0)

    def test_malformed_late_batch_item_rejects_entire_batch(self):
        worker = self.worker()
        class BadClient:
            def call(_self, path, data=None):
                self.assertEqual(path, '/v1/inbox')
                return {'messages': [self.item, {'action': 'run_one'}]}
        with self.assertRaises(ValueError):
            receive_to_worker_once(BadClient(), worker)
        self.assertEqual(self.count('prompts'), 0)

    def test_default_off_does_not_start_network_or_import_poller(self):
        with patch('socket.socket', side_effect=AssertionError('no networking')):
            worker = self.worker()
            self.assertIsNone(worker._poller)
            self.assertFalse(self.command(worker, 'snapshot').snapshot['remote']['enabled'])

    def test_close_is_nonblocking_during_network_then_stops_without_commit(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        class BlockedClient:
            def call(_self, path, data=None):
                calls.append(path)
                entered.set()
                release.wait(5)
                return {'messages': [self.item]}
        worker = self.worker(remote_client=BlockedClient())
        try:
            self.assertTrue(entered.wait(3))
            start = time.monotonic()
            worker.close()
            self.assertLess(time.monotonic() - start, 0.2)
            self.assertFalse(worker.wait_closed(0.02))
        finally:
            release.set()
        self.assertTrue(worker.wait_closed(3))
        self.assertEqual(calls, ['/v1/inbox'])
        self.assertEqual(self.count('prompts'), 0)

    def test_shutdown_after_commit_before_receipt_leaves_delivery_for_retry(self):
        self.send()
        worker = self.worker()
        stop = threading.Event()
        original = worker.submit_remote
        def stop_after_commit(item):
            future = original(item)
            future.result(3)
            stop.set()
            return future
        with patch.object(worker, 'submit_remote', side_effect=stop_after_commit):
            with self.assertRaises(PollingStopped):
                receive_to_worker_once(self.pc, worker, stop)
        self.assertEqual(self.count('prompts'), 1)
        self.assertEqual(self.phone.call('/v1/inbox')['messages'], [])
        self.assertEqual(len(self.pc.call('/v1/inbox')['messages']), 1)
        receive_to_worker_once(self.pc, worker)
        self.assertEqual(self.count('prompts'), 1)

    def test_failed_commit_rolls_back_then_retries_without_losing_state_owner(self):
        worker = self.worker()
        original = Store.event
        def fail_event(store, kind, payload):
            if kind == 'remote.prompt.saved':
                raise sqlite3.OperationalError('simulated unavailable disk')
            return original(store, kind, payload)
        with patch.object(Store, 'event', fail_event):
            with self.assertRaises(sqlite3.OperationalError):
                worker.submit_remote(self.item).result(3)
        self.assertEqual(self.count('prompts'), 0)
        self.assertEqual(self.count('events', "kind='remote.prompt.saved'"), 0)
        worker.submit_remote(self.item).result(3)
        self.assertEqual(self.command(worker, 'snapshot').snapshot['pending_requests'], 1)

    def test_poller_retries_transient_transport_failure(self):
        from aster_remote.poller import Poller
        self.send()
        original = self.pc.call
        first = [True]
        def transient(path, data=None):
            if first[0]:
                first[0] = False
                raise OSError('simulated temporary outage')
            return original(path, data)
        with patch.object(self.pc, 'call', side_effect=transient), \
                patch('aster_remote.poller.Poller', side_effect=lambda client, worker: Poller(client, worker, 0.02)):
            worker = self.worker(remote_client=self.pc)
            self.until(lambda: worker._poller.status()['received'] == 1)
            self.assertEqual(worker._poller.status()['state'], 'polling')
            self.assertNotIn('error', worker._poller.status())
        self.assertEqual(self.count('prompts'), 1)

    def test_failed_desktop_startup_never_starts_outbound_transport(self):
        owner = self.worker()
        from unittest.mock import Mock
        client = Mock()
        contender = DashboardWorker(self.path / 'aster', remote_client=client)
        self.workers.append(contender)
        self.assertTrue(contender.wait_closed(3))
        client.call.assert_not_called()
        self.assertTrue(owner.alive)

    def test_native_window_with_fifty_remote_messages_when_display_available(self):
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as exc:
            if os.name == 'nt':
                self.fail('Windows native qualification requires tkinter: ' + str(exc))
            self.skipTest('tkinter unavailable: ' + str(exc))
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.name == 'nt':
                self.fail('Windows native qualification requires a usable Tk display: ' + str(exc))
            self.skipTest('No native display available: ' + str(exc))
        from unittest.mock import Mock
        from aster.desktop import DesktopWindow
        app = None
        try:
            for i in range(50):
                self.send({**self.item, 'id': format(i, '032x')})
            dialogs = Mock()
            with self.delivery_timing('native_startup_backlog_50') as timing:
                app = DesktopWindow(root, self.path / 'aster', tk, ttk, dialogs, remote_client=self.pc)
                self.wait_for_batch(app.worker, pump=root.update,
                                    ready=lambda: app._snapshot is not None and not app._busy)
            self.assertEqual(timing['receipt_count'], 50)
            self.assertEqual(timing['ack_count'], 50)
            app._submit('snapshot')
            self.until(lambda: (root.update() or True) and not app._busy)
            self.assertEqual(app._snapshot['pending_requests'], 50)
            self.assertEqual(len(app.requests.get_children()), 50)
            self.assertIn('Remote text: polling', app.memory_status.get())
            dialogs.showerror.assert_not_called()
            self.assertEqual(self.count('jobs'), 0)
            with self.assertRaises(RuntimeError):
                Store(self.path / 'aster')
        finally:
            if app is not None:
                app.worker.close()
                self.assertTrue(app.worker.wait_closed(12))
            root.destroy()

    def test_desktop_cli_passes_existing_configuration_explicitly(self):
        from aster_remote.workstation import main
        with patch('sys.argv', ['bridge', '--desktop', '--relay', self.url,
                                '--allow-loopback-test', '--state', str(self.path / 'aster')]), \
                patch.dict(os.environ, {'ASTER_REMOTE_WORKSTATION_TOKEN': self.pc.token}), \
                patch('aster.desktop.launch', return_value=0) as launch:
            self.assertEqual(main(), 0)
            self.assertEqual(launch.call_args.args, (self.path / 'aster',))
            self.assertEqual(launch.call_args.kwargs['remote_client'].url, self.url)


if __name__ == '__main__':
    unittest.main()
