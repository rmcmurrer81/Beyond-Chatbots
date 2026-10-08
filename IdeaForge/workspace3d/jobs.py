"""Bounded in-app worker. SQLite leases resume interrupted local checks after restart."""
from __future__ import annotations
import threading
from pathlib import Path
from .adapters import gather
from .checks import run_checks
from .model import digest
from .store import Store, StaleProposal


def queue_refresh(root):
    store = Store(root)
    payload = gather(root)
    return store.enqueue(payload)


def run_one(root):
    store = Store(root); job = store.claim()
    if not job: return False
    try:
        payload = job['payload']
        # Never overwrite a candidate edited after this job was enqueued.
        latest = store.revision()
        parent = latest['id'] if latest else None
        if parent != payload.get('base_revision'):
            if latest and digest(latest['scene']) != digest(payload['scene']):
                raise StaleProposal('Newer geometry exists; old queued proposal was discarded.')
        tests = run_checks(payload['scene'])
        fingerprint = digest({k:v for k,v in payload.items() if k != 'base_revision'})
        store.add(payload['scene'],payload['reason'],payload['sources'],tests,
                  expected_parent=parent,fingerprint=fingerprint)
        store.finish(job)
    except Exception as error:
        store.finish(job,error)
    return True


class Manager:
    def __init__(self, roots, interval=30):
        self.roots = roots  # callable returns saved project roots, independent of active view
        self.interval = max(1,interval)
        self.stop_event = threading.Event()
        self.errors = {}
        self.cursor = 0
        self.thread = threading.Thread(target=self._loop,daemon=True,name='workspace-geometric-tests')
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                catalog = list(self.roots())
                # Fair bounded batches; saved projects beyond a batch are not starved.
                if catalog:
                    self.cursor %= len(catalog)
                    roots = (catalog[self.cursor:]+catalog[:self.cursor])[:20]
                    self.cursor = (self.cursor+len(roots)) % len(catalog)
                else: roots = []
            except Exception as error:
                self.errors['catalog'] = str(error); roots = []
            for root in roots:
                if self.stop_event.is_set(): break
                try:
                    queue_refresh(root)
                    # At most one bounded job per project per pass; no unbounded drains.
                    run_one(root)
                    self.errors.pop(str(root),None)
                except Exception as error: self.errors[str(root)] = str(error)
            self.stop_event.wait(self.interval)

    def shutdown(self):
        self.stop_event.set()
