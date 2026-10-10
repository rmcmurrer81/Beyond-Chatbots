"""Outbound transport thread. No Store, SQLite connection or dispatch access."""
from concurrent.futures import TimeoutError
import threading

from .delivery import PollingStopped, inbox, receipt


def receive_to_worker_once(client, worker, stop=None):
    stop = stop or threading.Event()
    if stop.is_set():
        raise PollingStopped()
    items = inbox(client.call('/v1/inbox'))
    count = 0
    for item in items:
        if stop.is_set():
            raise PollingStopped()
        committed = worker.submit_remote(item)
        while True:
            if stop.is_set():
                raise PollingStopped()
            try:
                committed.result(timeout=0.1)
                break
            except TimeoutError:
                continue
        receipt(client, item, stop.is_set)
        count += 1
    return count


class Poller:
    def __init__(self, client, worker, interval=10):
        self.client, self.worker, self.interval = client, worker, interval
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._status = {'enabled': True, 'state': 'starting', 'received': 0}
        self.thread = threading.Thread(target=self._run, name='aster-remote-outbound', daemon=False)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def status(self):
        with self._lock:
            return dict(self._status)

    def _run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    count = receive_to_worker_once(self.client, self.worker, self.stop_event)
                    with self._lock:
                        self._status.update(state='polling', received=self._status['received'] + count)
                        self._status.pop('error', None)
                except PollingStopped:
                    break
                except Exception as exc:
                    # No exception body: URLs, tokens and incoming text stay private.
                    with self._lock:
                        self._status.update(state='retrying', error=type(exc).__name__)
                if self.stop_event.wait(self.interval):
                    break
        finally:
            with self._lock:
                self._status['state'] = 'stopped'
