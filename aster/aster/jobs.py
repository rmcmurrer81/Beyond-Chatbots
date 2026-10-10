"""Explicit finite actions. No prompt-to-tool execution or arbitrary subprocesses."""
import json
import time
from urllib.parse import quote
from .storage import token, text
from .files import parts, MAX_BYTES

ACTIONS = {'file.write', 'memory.append', 'research.links'}


def validate(action, args):
    if action not in ACTIONS or type(args) is not dict:
        raise ValueError('Unknown action or invalid arguments')
    keys = {'file.write': {'path', 'text'}, 'memory.append': {'text', 'source'}, 'research.links': {'query'}}[action]
    if set(args) != keys: raise ValueError('Action argument fields do not match')
    if action == 'file.write':
        parts(args['path']); text(args['text'], MAX_BYTES)
    if action == 'memory.append': text(args['text']); text(args['source'], 1024)
    if action == 'research.links': text(args['query'], 1000)


class Jobs:
    def __init__(self, store, files, memory_guard=None):
        self.store, self.files = store, files
        if memory_guard is None:
            from .system_control import memory_guard as load_memory_guard
            memory_guard = load_memory_guard(store)
        self.memory_guard = memory_guard
        from .resources import ResourceSupervisor
        self.resources = ResourceSupervisor(store)

    def submit(self, action, args, budget=5.0, *, ram_mib=None, gpu_mib=0):
        validate(action, args)
        if type(budget) not in (int, float) or not 0.1 <= budget <= 30:
            raise ValueError('Wall-time budget must be 0.1–30 seconds')
        self.resources.validate_request(ram_mib, gpu_mib)
        id_ = token()
        with self.store.db:
            self.store.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                (id_, time.time(), action, json.dumps(args), 'queued', None, budget))
            self.resources.record_request(id_, ram_mib, gpu_mib)
            self.store.event('job.queued', {'id': id_, 'action': action})
        return id_

    def control(self, id_, command):
        row = self.store.db.execute('SELECT * FROM jobs WHERE id=?', (id_,)).fetchone()
        transitions = {'pause': {'queued': 'paused'}, 'resume': {'paused': 'queued'},
                       'cancel': {'queued': 'cancelled', 'paused': 'cancelled'}}
        new = transitions.get(command, {}).get(row['status'] if row else '')
        if not new: raise ValueError('Invalid job state transition')
        with self.store.db:
            self.store.db.execute('UPDATE jobs SET status=? WHERE id=?', (new, id_))
            self.store.event('job.' + new, {'id': id_})
        return new

    def effect_result(self, id_, result=None):
        # Preserve only evidence that actually committed. Recovery cannot
        # reconstruct elapsed time or promote an interrupted job to completion.
        result = dict(result or {})
        effect = self.store.job_effect(id_)
        result['effect'] = effect
        for key in ('memory_id', 'change_id'):
            if key in effect:
                result[key] = effect[key]
        return result

    def recover(self):
        # Never replay ambiguous work. File journal can reconcile its own bytes separately.
        with self.store.db:
            ids = [r[0] for r in self.store.db.execute("SELECT id FROM jobs WHERE status='running'")]
            for id_ in ids:
                old = self.store.db.execute('SELECT result FROM jobs WHERE id=?', (id_,)).fetchone()[0]
                result = self.effect_result(id_, json.loads(old) if old else None)
                if 'elapsed_seconds' not in result: result['timing_unknown'] = True
                self.store.db.execute("UPDATE jobs SET status='interrupted',result=? WHERE id=?",
                                      (json.dumps(result), id_))
                self.store.event('job.interrupted', {'id': id_})
        return ids

    def run_one(self):
        if self.store.db.in_transaction:
            raise RuntimeError('Job execution requires transaction ownership')
        row = self.store.db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY at LIMIT 1").fetchone()
        if not row: return {'status': 'idle'}
        memory = self.memory_guard.sample(force=True)
        if not memory['allow_new_jobs']:
            return {'id': row['id'], 'status': 'deferred_memory_pressure', 'memory': memory,
                    'message': 'Job remains queued. Retry explicitly when local memory pressure clears.'}
        admission = self.resources.admission(row['id'], memory)
        if not admission['allowed']:
            return {'id': row['id'], 'status': 'deferred_resource_budget', 'resources': admission,
                    'message': 'Job remains queued; revise the policy or wait for RAM and retry explicitly.'}
        id_, action, args = row['id'], row['action'], json.loads(row['args'])
        validate(action, args)
        with self.store.db:
            self.store.db.execute("UPDATE jobs SET status='running' WHERE id=?", (id_,))
            self.store.event('job.running', {'id': id_})
        start = time.monotonic()
        try:
            if action == 'file.write': result = {'change_id': self.files.change(args['path'], args['text'].encode(), job_id=id_)}
            elif action == 'memory.append': result = {'memory_id': self.store.remember(args['text'], args['source'], job_id=id_)}
            else:
                q = quote(args['query'], safe='')
                result = {'query': args['query'], 'status': 'manual_research_links_only',
                          'sources_fetched': 0, 'links': ['https://www.google.com/search?q=' + q,
                          'https://scholar.google.com/scholar?q=' + q]}
            elapsed = time.monotonic() - start
            state = 'completed' if elapsed <= row['budget'] else 'completed_over_budget'
            result['elapsed_seconds'] = elapsed
            # These bounded in-process operations cannot be preempted safely mid-write.
            # Budget is a measured stop-after-one guard, not a hard CPU/RAM limit.
        except BaseException as exc:
            state = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
            result = self.effect_result(id_, {'error': str(exc), 'elapsed_seconds': time.monotonic() - start})
            with self.store.db:
                self.store.db.execute('UPDATE jobs SET status=?,result=? WHERE id=?', (state, json.dumps(result), id_))
                self.store.event('job.' + state, {'id': id_})
            if isinstance(exc, (KeyboardInterrupt, SystemExit)): raise
            return {'id': id_, 'status': state, 'result': result}
        result = self.effect_result(id_, result)
        with self.store.db:
            self.store.db.execute('UPDATE jobs SET status=?,result=? WHERE id=?', (state, json.dumps(result), id_))
            self.store.event('job.' + state, {'id': id_})
        return {'id': id_, 'status': state, 'result': result}
