"""Display-independent local control panel, with a single owning worker thread.

Only the existing bounded Aster operations are exposed. Confirmation tickets are
one-use, instance-local, and bind file edits to the bytes actually reviewed.
Nothing starts automatically. The browser handoff requires exact local review.
No listener, model, general program launcher, or automatic job runner exists.
Opt-in remote transport can enqueue only validated text for the owning worker.
"""
from concurrent.futures import Future
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import threading
import time

from . import backend
from .files import Files, MAX_BYTES
from .jobs import Jobs, validate
from .storage import Store, token

HISTORIES = ('prompts', 'jobs', 'changes', 'memories', 'events')


class Dashboard:
    """Synchronous controller. Construct, call, and close on one owning thread."""

    def __init__(self, state, *, auto_start=False):
        self.store = Store(state)
        self.files = None
        try:
            self.files = Files(self.store)
            from .lifecycle import Lifecycle
            from .system_control import memory_guard
            self.lifecycle = Lifecycle(self.store, auto_start=auto_start)
            self.lifecycle.start()
            self.memory_guard = memory_guard(self.store)
            self.memory_guard.sample()
        except BaseException:
            if self.files is not None:
                self.files.close()
            self.store.close()
            raise
        self.jobs = Jobs(self.store, self.files, memory_guard=self.memory_guard)
        self._pending = None
        self._adapters = None
        from .private_memory import PrivateMemory
        self.private_memory = PrivateMemory(self.store)
        self._closed = False
        from .browser_public import PublicReader
        self.public_reader = PublicReader()

    def close(self, *, clean=True):
        if not self._closed:
            self._closed = True
            self.public_reader.close()
            try:
                self.lifecycle.close(clean=clean)
            finally:
                try:
                    self.files.close()
                finally:
                    self.store.close()

    def snapshot(self):
        # Explicit SQL projections avoid fetching historical BLOBs or all large
        # job payloads just to paint a list. Full details are selected on demand.
        columns = {
            'prompts': 'id, at, status, substr(body,1,160) AS preview',
            'jobs': 'id, at, action, status, budget',
            'changes': 'id, at, path, kind, status',
            'memories': 'id, at, substr(body,1,160) AS preview, source, supersedes',
            'events': 'seq AS id, at, kind',
        }
        histories = {kind: [dict(row) for row in self.store.db.execute(
            f'SELECT {fields} FROM {kind} ORDER BY rowid DESC LIMIT 100')]
            for kind, fields in columns.items()}
        # Normal history respects recoverable visibility controls. Raw retained
        # versions remain explicitly inspectable through the private memory API.
        histories['memories'] = [dict(id=r['id'], at=r['at'], preview=r['body'][:160],
            source=r['source'], supersedes=r['supersedes'])
            for r in self.private_memory.search(include_superseded=True, limit=100)]
        counts = {row['status']: row['n'] for row in self.store.db.execute(
            'SELECT status, count(*) AS n FROM jobs GROUP BY status')}
        return {'identity': self.store.identity(), 'backend': backend.status(),
                'state': str(self.store.root), 'workspace': str(self.files.root),
                'histories': histories, 'job_counts': counts,
                'pending_requests': self.store.db.execute(
                    "SELECT count(*) FROM prompts WHERE status='waiting_for_newbrain'").fetchone()[0],
                'interrupted_changes': self.store.db.execute(
                    "SELECT count(*) FROM changes WHERE status='prepared'").fetchone()[0],
                'running_jobs': counts.get('running', 0),
                'lifecycle': self.lifecycle.status(), 'memory': self.memory_guard.status()}

    def history(self, kind, item_id):
        if kind not in HISTORIES:
            raise ValueError('Unknown history')
        if kind == 'memories':
            item = self.private_memory.get(item_id)
            if item['state'] != 'active':
                raise ValueError('Memory is hidden or recoverably deleted; use explicit memory controls to inspect or restore')
            return item
        key = 'seq' if kind == 'events' else 'id'
        fields = ('id, at, path, kind, status, length(before) AS before_bytes, '
                  'length(after) AS after_bytes') if kind == 'changes' else '*'
        row = self.store.db.execute(
            f'SELECT {fields} FROM {kind} WHERE {key}=?', (item_id,)).fetchone()
        if not row:
            raise ValueError('History item no longer exists')
        item = dict(row)
        if kind == 'jobs': item['effect'] = self.store.job_effect(item_id)
        return item

    def _prepare(self, operation, message, **payload):
        if self._pending:
            raise ValueError('Finish or dismiss the pending confirmation first')
        ticket = token()
        self._pending = {'ticket': ticket, 'operation': operation, **payload}
        return {'confirmation_required': True, 'ticket': ticket,
                'title': 'Confirm ' + operation.replace('_', ' '), 'message': message}

    def prepare_write(self, path, content):
        if type(content) is not str:
            raise ValueError('File content must be text')
        data = content.encode('utf-8')
        if len(data) > MAX_BYTES:
            raise ValueError('File content exceeds 256 KiB')
        before = self.files.snapshot(path)
        verb = 'Create' if before is None else 'Overwrite'
        return self._prepare('write',
            f'{verb} workspace file {path!r} with {len(data):,} UTF-8 bytes?\n\n'
            'The old version, if any, stays in the local journal for conflict-aware undo. '
            'No code is executed.', path=path, before=before, data=data)

    def prepare_trash(self, path):
        before = self.files.read(path)
        return self._prepare('trash',
            f'Move workspace file {path!r} ({len(before):,} bytes) to recoverable trash?\n\n'
            'It will disappear from the workspace. Its content stays in the local journal '
            'and can be restored using the change ID.', path=path, before=before)

    def prepare_undo(self, change_id):
        row = self.store.db.execute('SELECT * FROM changes WHERE id=?', (change_id,)).fetchone()
        if not row or row['status'] != 'applied':
            raise ValueError('Select an applied change to undo')
        current = self.files.snapshot(row['path'])
        if current != row['after']:
            raise ValueError('File changed since this operation; refusing to overwrite')
        effect = ('remove the current file' if row['before'] is None else
                  f'restore the previous {len(row["before"]):,} bytes')
        return self._prepare('undo',
            f'Undo change {change_id} on {row["path"]!r}?\n\nThis will {effect}. '
            'A new reversible journal entry is recorded.',
            change_id=change_id, path=row['path'], before=current)

    def prepare_run(self):
        row = self.store.db.execute(
            "SELECT * FROM jobs WHERE status='queued' ORDER BY at LIMIT 1").fetchone()
        if not row:
            return {'status': 'idle', 'message': 'No queued job. Paused jobs stay paused.'}
        args = json.loads(row['args'])
        validate(row['action'], args)
        payload = {'job_id': row['id'], 'action': row['action'], 'args': row['args'], 'budget': row['budget']}
        if row['action'] == 'file.write':
            before = self.files.snapshot(args['path'])
            payload.update(path=args['path'], before=before)
            description = (('Create' if before is None else 'Overwrite') +
                           f' workspace file {args["path"]!r} with '
                           f'{len(args["text"].encode("utf-8")):,} UTF-8 bytes.')
        elif row['action'] == 'memory.append':
            description = f'Append a memory attributed to {args["source"]!r}:\n{args["text"][:600]}'
        else:
            description = f'Create manual search links for:\n{args["query"]}\nNo pages will be fetched.'
        return self._prepare('run_one',
            f'Run the next queued job ({row["id"]})?\n\n{description}\n\n'
            f'Measured time budget: {row["budget"]:g} seconds (not a hard timeout). '
            'Exactly one job runs. An active operation cannot be paused or cancelled.', **payload)

    def adapters(self):
        if self._adapters is None:
            from .app_adapters import AppAdapters
            self._adapters = AppAdapters(self.store, self.files)
        return self._adapters

    def research_result(self, result):
        return {'surface': 'research', 'result': result, 'state': self.adapters().status()}

    def prepare_register(self, path):
        preview = self.adapters().preview_manifest(path)
        return self._prepare('register_export',
            'Register this exact owner-selected local export capability?\n\n'
            + json.dumps(preview, ensure_ascii=False, indent=2) +
            '\n\nThis does not connect to or grant access to an installed app. '
            'Only declared local export operations will be enabled. Nothing is executed.',
            export_path=path, sha256=preview['sha256'])

    def prepare_select(self, manifest_id, project_id, path):
        preview = self.adapters().preview_export(manifest_id, project_id, path)
        return self._prepare('select_export',
            'Save and select this exact local export snapshot for the declared app and project?\n\n'
            + json.dumps(preview, ensure_ascii=False, indent=2) +
            '\n\nThe snapshot persists in Aster history. Research content is untrusted '
            'owner-declared data; it will not be treated as instructions or validated claims.',
            manifest_id=manifest_id, project_id=project_id,
            export_path=path, sha256=preview['sha256'])

    def prepare_browser(self, kind, value):
        from .browser_actions import plan
        preview = plan(kind, value)
        return self._prepare('browser',
            'Open this exact destination in your default browser?\n\n' + preview['url'] +
            '\n\n' + preview['message'] +
            ('\n\nOnly the text you typed will be sent as the Google search query.' if kind == 'search' else '') +
            '\n\nNo login, page reading, form completion, or account creation is performed by Aster.',
            kind=kind, value=value, sha256=preview['plan_sha256'])

    def confirm(self, ticket):
        pending = self._pending
        if not pending or ticket != pending['ticket']:
            raise ValueError('Confirmation is missing, stale, or already used')
        self._pending = None  # One use, even after a failed/conflicting attempt.
        if 'path' in pending and self.files.snapshot(pending['path']) != pending['before']:
            raise ValueError('File changed after review. Nothing was executed; review again.')
        operation = pending['operation']
        if operation == 'browser':
            from .browser_actions import open_reviewed
            result = open_reviewed(pending['kind'], pending['value'], approved=True,
                                   expected_sha256=pending['sha256'])
            return {'surface': 'browser', 'result': result}
        if operation == 'write':
            return {'change_id': self.files.change(pending['path'], pending['data']), 'status': 'written'}
        if operation == 'trash':
            return {'change_id': self.files.change(pending['path'], None, 'trash'), 'status': 'trashed'}
        if operation == 'undo':
            return {'change_id': self.files.undo(pending['change_id']), 'status': 'undone'}
        if operation == 'run_one':
            row = self.store.db.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY at LIMIT 1").fetchone()
            if (not row or row['id'] != pending['job_id'] or
                    row['action'] != pending['action'] or row['args'] != pending['args'] or
                    row['budget'] != pending['budget']):
                raise ValueError('Next job changed after review. Review again.')
            return self.jobs.run_one()
        if operation == 'register_export':
            return self.research_result(self.adapters().register(pending['export_path'],
                expected_sha256=pending['sha256'], approved=True))
        if operation == 'select_export':
            return self.research_result(self.adapters().select(pending['manifest_id'],
                pending['project_id'], pending['export_path'],
                expected_sha256=pending['sha256'], approved=True))
        if operation == 'disable_export':
            return self.research_result(self.adapters().disable(pending['manifest_id'], approved=True))
        if operation == 'clear_export':
            return self.research_result(self.adapters().clear_selection())
        if operation == 'recover':
            result = {'files': self.files.recover(), 'interrupted_jobs': self.jobs.recover()}
            lifecycle = self.lifecycle.status()
            if not (lifecycle['prepared_changes'] or lifecycle['running_jobs']):
                lifecycle = self.lifecycle.acknowledge_recovery()
            result['lifecycle'] = lifecycle
            return result
        if operation == 'support':
            from .support import invoke
            result = invoke(self.store, self.files, self.jobs, pending['module'],
                pending['action'], pending['args'], approved=True)
            return {'surface': 'support', 'module': pending['module'],
                    'operation': pending['action'], 'result': result}
        raise ValueError('Unknown confirmation operation')

    def _public_operation(self, action, args, cancelled=None):
        if self._closed:
            raise RuntimeError('Dashboard is closed')
        if self._pending:
            raise ValueError('Finish or dismiss the pending confirmation first')
        if action == 'public_read':
            result = self.public_reader._request(url=args['url'], pending_cancelled=cancelled)
        elif action == 'public_follow':
            result = self.public_reader._request(source_id=args['source_id'],
                link_id=args['link_id'], pending_cancelled=cancelled)
        else:
            operation = {'public_cached': self.public_reader.cached,
                         'public_clear': self.public_reader.clear,
                         'public_status': self.public_reader.status}[action]
            result = operation(**args)
        return {'surface': 'public_reader', 'result': result}

    def dispatch(self, action, **args):
        if self._closed:
            raise RuntimeError('Dashboard is closed')
        if self._pending and action not in {'confirm', 'dismiss', 'snapshot', 'history'}:
            raise ValueError('Finish or dismiss the pending confirmation first')
        if action == 'snapshot': return self.snapshot()
        if action == 'prepare_browser': return self.prepare_browser(**args)
        if action in {'public_read', 'public_follow', 'public_cached', 'public_clear', 'public_status'}:
            return self._public_operation(action, args)
        if action in {'support', 'prepare_support'}:
            from .support import invoke, operation, parse_args
            module, op = args['module'], args['operation']
            arguments = parse_args(args.get('args_json', '{}'))
            _, mutation, _ = operation(module, op)
            if mutation:
                if action != 'prepare_support':
                    raise ValueError('Use the separate local review step for this mutation')
                if module == 'resources' and op == 'run-one':
                    if arguments:
                        raise ValueError('Run next job accepts no arguments')
                    return self.prepare_run()
                review_evidence = ''
                if module == 'ability' and op == 'review':
                    from .ability_workshop import AbilityWorkshop
                    workshop = AbilityWorkshop(self.store, self.files)
                    source = workshop.source(arguments.get('proposal_id'))
                    if source['source_sha256'] != arguments.get('source_sha256'):
                        raise ValueError('Review source hash does not identify this immutable proposal')
                    evidence = {'immutable_proposal_source': source}
                    if arguments.get('test_receipt_id') is not None:
                        evidence['actual_test_receipt'] = workshop.receipt(arguments['test_receipt_id'])
                    review_evidence = '\n\nExact saved source and test evidence:\n' + json.dumps(
                        evidence, indent=2, ensure_ascii=False, allow_nan=False)
                return self._prepare('support',
                    'Approve this exact local ' + module + ' / ' + op + ' operation?\n\n' +
                    json.dumps(arguments, indent=2, ensure_ascii=False, allow_nan=False) +
                    review_evidence +
                    '\n\nNo account is connected and no external message is sent. '
                    'Memory deletion is recoverable and retains stored data. '
                    'Ability runs are bounded text recipes only, never Python or shell.',
                    module=module, action=op, args=arguments)
            result = invoke(self.store, self.files, self.jobs, module, op, arguments)
            return {'surface': 'support', 'module': module, 'operation': op, 'result': result}
        if action == 'memory_refresh':
            self.lifecycle.heartbeat()
            return {'memory': self.memory_guard.sample(), 'lifecycle': self.lifecycle.status()}
        if action == 'system_status':
            from .app_relief import status as relief_status
            self.lifecycle.heartbeat()
            return {'memory': self.memory_guard.sample(), 'lifecycle': self.lifecycle.status(),
                    'external_app_relief': relief_status()}
        if action == 'history': return self.history(**args)
        if action == 'save_request': return backend.talk(self.store, args['prompt'])
        if action == 'read':
            path = args['path']
            return {'path': path, 'text': self.files.read(path).decode('utf-8')}
        if action == 'prepare_write': return self.prepare_write(**args)
        if action == 'prepare_trash': return self.prepare_trash(**args)
        if action == 'prepare_undo': return self.prepare_undo(**args)
        if action == 'prepare_run': return self.prepare_run()
        if action == 'confirm': return self.confirm(args['ticket'])
        if action == 'dismiss':
            if not self._pending or args['ticket'] != self._pending['ticket']:
                raise ValueError('Confirmation is missing or stale')
            self._pending = None
            return {'status': 'dismissed', 'message': 'No operation was performed.'}
        if action == 'queue':
            return {'id': self.jobs.submit(args['job_action'], args['job_args'], args.get('budget', 5)),
                    'status': 'queued', 'message': 'Saved to queue. It will only run after Run next once.'}
        if action == 'control':
            return {'id': args['job_id'], 'status': self.jobs.control(args['job_id'], args['command'])}
        if action == 'prepare_recover':
            return self._prepare('recover',
                'Reconcile interrupted file journal entries and mark leftover running jobs interrupted?\n\n'
                'No jobs are replayed and conflicting files are not overwritten. Review the results before retrying.')
        if action == 'research_status': return self.research_result(self.adapters().status())
        if action == 'prepare_register': return self.prepare_register(**args)
        if action == 'prepare_select': return self.prepare_select(**args)
        if action == 'prepare_disable':
            return self._prepare('disable_export',
                'Disable local export capability ' + args['manifest_id'] + '?\n\n'
                'Its selections will become unreadable through this capability. '
                'Append-only history is retained. This does not change external app permissions.',
                manifest_id=args['manifest_id'])
        if action == 'prepare_clear':
            return self._prepare('clear_export',
                'Clear the default export selection? The saved snapshot and history remain. '
                'It can still be read by its exact ID while its capability remains enabled.')
        if action == 'research_inspect': return self.research_result(self.adapters().inspect())
        if action == 'research_read': return self.research_result(self.adapters().read())
        if action == 'voice':
            from .voice import inspect_voice
            return inspect_voice()
        if action == 'apps':
            from .apps import discover
            return discover()
        raise ValueError('Unknown dashboard action')


@dataclass(frozen=True)
class Completion:
    action: str
    result: object = None
    snapshot: object = None
    error: str = ''


class DashboardWorker:
    """Single-flight handoff: SQLite and Files never cross their owning thread.

    An operation remains busy until its completion is consumed. Rapid repeats
    cannot queue duplicates. close() is nonblocking; accepted work finishes before
    resources close. poll() is the only UI-thread delivery mechanism.
    """

    def __init__(self, state, controller_factory=Dashboard, *, auto_start=False,
                 remote_client=None, remote_queue_capacity=50):
        self._state = Path(state)
        self._factory = controller_factory
        self._auto_start = auto_start
        if type(remote_queue_capacity) is not int or not 1 <= remote_queue_capacity <= 50:
            raise ValueError('Remote queue capacity must be 1–50')
        self._remote = queue.Queue(maxsize=remote_queue_capacity)
        self._wake = threading.Event()
        self._poller = None
        if remote_client is not None:
            from aster_remote.poller import Poller
            self._poller = Poller(remote_client, self)
        self._commands = queue.Queue(maxsize=1)
        self._results = queue.Queue()
        self._lock = threading.Lock()
        self._busy = True
        self._closing = False
        self._clean_requested = None
        self._public_reader = None
        self._public_request_cancel = None
        self._thread = threading.Thread(target=self._run, name='aster-local-state', daemon=False)
        self._thread.start()

    def submit(self, action, **args):
        with self._lock:
            if self._busy or self._closing:
                return False
            self._busy = True
            cancelled = threading.Event() if action in {'public_read', 'public_follow'} else None
            self._public_request_cancel = cancelled
            self._commands.put_nowait((action, args, cancelled))
            self._wake.set()
            return True

    def cancel_public(self):
        """Only thread-safe in-memory invalidation; no storage or new request."""
        with self._lock:
            if self._public_request_cancel is not None:
                self._public_request_cancel.set()
            if self._public_reader is not None:
                self._public_reader.clear()

    def submit_remote(self, value):
        """Separate text-only boundary, never an action name or arbitrary callable.

        Capacity/close failures leave the relay unacknowledged. Futures resolve
        after commit; neither callers nor the transport thread access SQLite.
        """
        from aster_remote.delivery import message
        item = message(value)
        done = Future()
        with self._lock:
            if self._closing:
                raise RuntimeError('Dashboard is closing; retry remote delivery later')
            self._remote.put_nowait((item, done))
            self._wake.set()
        return done

    def _snapshot(self, controller):
        snapshot = controller.snapshot()
        snapshot['remote'] = self._poller.status() if self._poller else {'enabled': False}
        return snapshot

    def poll(self):
        try:
            completion = self._results.get_nowait()
        except queue.Empty:
            return None
        with self._lock:
            self._busy = False
        return completion

    @property
    def alive(self):
        return self._thread.is_alive()

    def close(self, *, clean=True):
        with self._lock:
            if clean is False:
                self._clean_requested = False
            elif self._clean_requested is None:
                self._clean_requested = True
            if self._closing:
                return
            self._closing = True
            if self._public_request_cancel is not None:
                self._public_request_cancel.set()
            if self._public_reader is not None:
                self._public_reader.close()
            if self._poller:
                self._poller.stop()
            self._wake.set()
            try:
                self._commands.put_nowait(None)
            except queue.Full:
                pass  # Accepted work wakes the worker; it checks closing after it.

    def wait_closed(self, timeout=None):
        """Wait only outside the Tk event loop (shutdown or tests)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        self._thread.join(timeout)
        if self._poller and self._poller.thread.ident is not None:
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            self._poller.thread.join(remaining)
        return not self.alive and not (self._poller and self._poller.thread.is_alive())

    def _run(self):
        controller = None
        try:
            controller = (self._factory(self._state, auto_start=True) if self._auto_start
                          else self._factory(self._state))
            with self._lock:
                self._public_reader = getattr(controller, 'public_reader', None)
                if self._closing and self._public_reader is not None:
                    self._public_reader.close()
            if self._poller:
                self._poller.start()
            self._results.put(Completion('ready', snapshot=self._snapshot(controller)))
            while True:
                self._wake.clear()
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    with self._lock:
                        if self._closing:
                            break
                    # Preserve local confirmation isolation. Remote text waits;
                    # it cannot approve, dismiss or invalidate a review ticket.
                    if getattr(controller, '_pending', None) is None:
                        try:
                            item, done = self._remote.get_nowait()
                        except queue.Empty:
                            pass
                        else:
                            if done.set_running_or_notify_cancel():
                                try:
                                    from aster_remote.delivery import save_message
                                    result = save_message(controller.store, item)
                                except Exception as exc:
                                    done.set_exception(exc)
                                else:
                                    done.set_result(result)
                            continue
                    self._wake.wait()
                    continue
                if command is None:
                    break
                action, args, cancelled = command
                result = snapshot = None
                error = ''
                try:
                    if cancelled is not None and isinstance(controller, Dashboard):
                        result = controller._public_operation(action, args, cancelled)
                    else:
                        result = controller.dispatch(action, **args)
                except Exception as exc:
                    error = str(exc) or type(exc).__name__
                try:
                    snapshot = self._snapshot(controller)
                except Exception as exc:
                    error = (error + '\n' if error else '') + 'Refresh failed: ' + str(exc)
                self._results.put(Completion(action, result, snapshot, error))
                with self._lock:
                    if self._closing:
                        break
        except Exception as exc:
            self._results.put(Completion('startup', error=str(exc) or type(exc).__name__))
        finally:
            with self._lock:
                self._closing = True
                if self._poller:
                    self._poller.stop()
                while True:
                    try:
                        _, done = self._remote.get_nowait()
                    except queue.Empty:
                        break
                    if not done.done():
                        done.set_exception(RuntimeError('Dashboard closed before remote commit; retry later'))
            try:
                if controller is not None:
                    if isinstance(controller, Dashboard):
                        controller.close(clean=self._clean_requested is True)
                    else:
                        controller.close()  # Test factories keep their minimal interface.
            except Exception as exc:
                self._results.put(Completion('close', error=str(exc) or type(exc).__name__))
            self._results.put(Completion('closed'))
