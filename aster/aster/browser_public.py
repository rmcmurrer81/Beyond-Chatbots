"""Explicit anonymous public-source reads, supervised outside the owning process.

Only local read/follow calls initiate requests. Returned page text and labels are
untrusted display data, never executable instructions. Nothing persists.
"""
import argparse
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urldefrag, urlsplit
from types import MappingProxyType

from .public_transport import PublicFetchError, validate_public_url, _CODES

WORKER_DEADLINE = 20.0
MAX_WORKER_OUTPUT = 512 * 1024
SNAPSHOT_SECONDS = 15 * 60
MAX_SESSION_OPERATIONS = 32
MAX_REDIRECTS = 5
_LOCAL_CODES = frozenset(('worker_timeout', 'worker_failed', 'worker_invalid_output',
    'worker_output_limit', 'cancelled', 'reader_busy', 'reader_closed',
    'stale_source', 'invalid_link', 'source_expired', 'operation_limit',
    'redirect_cycle', 'redirect_limit', 'no_source'))


def _failure(code):
    return {'status': 'failed', 'reason': code if code in _CODES | _LOCAL_CODES else 'worker_failed',
            'untrusted_content': True, 'links': [], 'title': '', 'text': '', 'source_id': None}


def _child_environment():
    # Deliberately no inherited PATH, HOME, proxy, credentials, PYTHON*, SSL* or
    # browser/profile configuration. Windows needs its OS directory variables.
    if os.name == 'nt':
        return {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR') if key in os.environ}
    return {}


def _validate_result(value, url):
    """Treat worker output as untrusted IPC, including all metadata and links."""
    if type(value) is not dict:
        raise ValueError
    if set(value) == {'status', 'reason'}:
        if value['status'] != 'failed' or value['reason'] not in _CODES | {'worker_failed'}:
            raise ValueError
        return _failure(value['reason'])
    keys = {'status', 'requested_url', 'source_url', 'title', 'text', 'links',
            'body_sha256', 'truncated', 'reason', 'fetched_at', 'selected_peer',
            'tls_verified', 'untrusted_content', 'http_status'}
    if set(value) != keys or value['status'] not in {'read', 'redirect', 'unsupported', 'failed'}:
        raise ValueError
    if value['requested_url'] != url or value['source_url'] != urldefrag(url)[0]:
        raise ValueError
    if value['reason'] not in _CODES or value['untrusted_content'] is not True:
        raise ValueError
    for field, limit in (('title', 256), ('text', 12000), ('fetched_at', 64), ('body_sha256', 64)):
        if type(value[field]) is not str or len(value[field]) > limit:
            raise ValueError
    # Every displayed string is data, including provenance metadata. Only body
    # text may use ordinary newlines/tabs; metadata cannot contain bidi/control
    # characters even where a permissive parser would otherwise accept them.
    for field, item in value.items():
        if type(item) is str and any(unicodedata.category(char).startswith('C')
                and not (field == 'text' and char in '\n\t') for char in item):
            raise ValueError
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
                        r'(?:\.[0-9]{6})?\+00:00', value['fetched_at']):
        raise ValueError
    fetched = datetime.fromisoformat(value['fetched_at'])
    if fetched.isoformat() != value['fetched_at'] or fetched.utcoffset() != timezone.utc.utcoffset(fetched):
        raise ValueError
    if value['body_sha256'] and not re.fullmatch('[0-9a-f]{64}', value['body_sha256']):
        raise ValueError
    if type(value['tls_verified']) is not bool or value['tls_verified'] != (urlsplit(url).scheme == 'https'):
        raise ValueError
    peer = value['selected_peer']
    if type(peer) is not str or ipaddress.ip_address(peer).version != 4:
        raise ValueError
    validate_public_url('http://' + peer + '/')
    if type(value['http_status']) is not int or not 100 <= value['http_status'] <= 599:
        raise ValueError
    truncated = value['truncated']
    if (type(truncated) is not dict or set(truncated) != {'body', 'text', 'links', 'title'}
            or any(type(item) is not bool for item in truncated.values())):
        raise ValueError
    links = value['links']
    if type(links) is not list or len(links) > 32:
        raise ValueError
    for link in links:
        if type(link) is not dict or set(link) != {'url', 'text'}:
            raise ValueError
        if (type(link['text']) is not str or len(link['text']) > 160
                or any(unicodedata.category(char).startswith('C') for char in link['text'])):
            raise ValueError
        if validate_public_url(link['url']) != link['url']:
            raise ValueError
        if urlsplit(url).scheme == 'https' and urlsplit(link['url']).scheme != 'https':
            raise ValueError
    if value['status'] == 'read' and (value['http_status'] != 200 or not value['body_sha256'] or value['reason'] != 'ok'):
        raise ValueError
    if value['status'] == 'redirect' and (not 300 <= value['http_status'] < 400 or len(links) > 1):
        raise ValueError
    if value['status'] not in {'read', 'redirect'} and links:
        raise ValueError
    return copy.deepcopy(value)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _fetch_in_worker(url, cancelled):
    """Fixed disposable child; bounded pipes and deadline include DNS and parse.

    This is process lifetime containment, not a hard OS memory/CPU sandbox.
    Reader and writer threads avoid unbounded communicate() allocation or pipe
    deadlock, including on Windows. stderr is never retained or displayed.
    """
    child = None
    readers = []
    completed = threading.Event()
    output = bytearray()
    overflow = threading.Event()
    io_failed = threading.Event()
    deadline = time.monotonic() + WORKER_DEADLINE
    try:
        if cancelled.is_set():
            return _failure('cancelled')
        child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).with_name('public_worker.py').resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            shell=False, env=_child_environment(), cwd=str(Path(__file__).resolve().parent),
            close_fds=True)
        # Popen itself can overlap owner cancellation. Never hand the URL to a
        # child created after that cancellation; finally still kills/reaps it.
        if cancelled.is_set():
            return _failure('cancelled')
        def receive():

            try:
                while len(output) <= MAX_WORKER_OUTPUT:
                    block = child.stdout.read(min(8192, MAX_WORKER_OUTPUT + 1 - len(output)))
                    if not block:
                        break
                    output.extend(block)
                if len(output) > MAX_WORKER_OUTPUT:
                    overflow.set()
            except (OSError, ValueError):
                io_failed.set()
            finally:
                completed.set()
        def send():
            try:
                encoded = json.dumps({'url': url}, ensure_ascii=True).encode('ascii') + b'\n'
                # Recheck at the input boundary, after encoding and scheduling.
                # Once the write starts, cancellation is necessarily best effort.
                if not cancelled.is_set():
                    child.stdin.write(encoded)
            except (OSError, ValueError):
                io_failed.set()
            finally:
                try:
                    child.stdin.close()
                except (OSError, ValueError):
                    io_failed.set()

        readers = [threading.Thread(target=receive, daemon=True, name='aster-public-result'),
                   threading.Thread(target=send, daemon=True, name='aster-public-input')]
        for reader in readers:
            reader.start()
        while True:
            if cancelled.is_set():
                return _failure('cancelled')
            if overflow.is_set():
                return _failure('worker_output_limit')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _failure('worker_timeout')
            if completed.is_set() and child.poll() is not None:
                break
            completed.wait(min(.02, remaining)) if not completed.is_set() else time.sleep(min(.02, remaining))
        if child.returncode != 0 or io_failed.is_set():
            return _failure('worker_failed')
        try:
            return _validate_result(json.loads(output.decode('utf-8'), object_pairs_hook=_unique_object), url)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            return _failure('worker_invalid_output')
    except (OSError, ValueError, subprocess.SubprocessError):
        return _failure('worker_failed')
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait()  # Reap this fixed worker, which cannot spawn descendants.
            for reader in readers:
                reader.join(timeout=1)
            for stream in (child.stdin, child.stdout):
                if stream is not None:
                    stream.close()


class PublicReader:
    """One in-memory navigation; IDs are owned, one-use and never persisted by Aster.

    A fresh explicit read starts a new 15-minute / 32-operation navigation.
    Any read/follow attempt consumes the previous snapshot, including errors.
    Concurrent attempts cancel publication of the earlier result.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = None
        self._links = MappingProxyType({})
        self._busy = False
        self._closed = False
        self._generation = 0
        self._cancelled = threading.Event()
        self._started = 0.0
        self._operations = 0
        self._visited = ()
        self._redirects = 0

    def _invalidate(self):
        self._generation += 1
        self._snapshot = None
        self._links = MappingProxyType({})
        self._cancelled.set()

    def clear(self):
        with self._lock:
            self._invalidate()
        return {'status': 'cleared', 'reason': 'cancelled', 'source_id': None, 'links': []}

    def close(self):
        with self._lock:
            self._closed = True
            self._invalidate()

    def status(self):
        with self._lock:
            return {'mode': 'anonymous_static_public_reader', 'busy': self._busy,
                'closed': self._closed, 'has_source': self._snapshot is not None,
                'automatic_requests': False, 'persisted_content': False,
                'forms': False, 'javascript': False, 'cookies': False,
                'worker_deadline_seconds': WORKER_DEADLINE,
                'snapshot_seconds': SNAPSHOT_SECONDS, 'max_operations': MAX_SESSION_OPERATIONS}

    def cached(self):
        with self._lock:
            if self._snapshot is None:
                return _failure('no_source')
            if time.monotonic() - self._started >= SNAPSHOT_SECONDS:
                self._invalidate()
                return _failure('source_expired')
            return copy.deepcopy(self._snapshot)

    def read(self, url):
        return self._request(url=url)

    def follow(self, source_id, link_id):
        return self._request(source_id=source_id, link_id=link_id)

    def _request(self, *, url=None, source_id=None, link_id=None, pending_cancelled=None):
        with self._lock:
            previous, links = self._snapshot, self._links
            self._invalidate()
            if self._closed:
                return _failure('reader_closed')
            if pending_cancelled is not None and pending_cancelled.is_set():
                return _failure('cancelled')
            if self._busy:
                return _failure('reader_busy')
            if source_id is not None or link_id is not None or url is None:
                if type(source_id) is not str or previous is None or source_id != previous['source_id']:
                    return _failure('stale_source')
                if time.monotonic() - self._started >= SNAPSHOT_SECONDS:
                    return _failure('source_expired')
                if type(link_id) is not str or link_id not in links:
                    return _failure('invalid_link')
                if self._operations >= MAX_SESSION_OPERATIONS:
                    return _failure('operation_limit')
                url = links[link_id]
                if previous['status'] == 'redirect':
                    if urldefrag(url)[0] in self._visited:
                        return _failure('redirect_cycle')
                    if self._redirects >= MAX_REDIRECTS:
                        return _failure('redirect_limit')
                    self._redirects += 1
                else:
                    self._visited, self._redirects = (), 0
            else:
                self._started, self._operations = time.monotonic(), 0
                self._visited, self._redirects = (), 0
            try:
                url = validate_public_url(url)
            except PublicFetchError as exc:
                return _failure(exc.code)
            self._operations += 1
            self._visited += (urldefrag(url)[0],)
            self._busy = True
            generation = self._generation
            self._cancelled = cancelled = pending_cancelled if pending_cancelled is not None else threading.Event()
        try:
            result = _fetch_in_worker(url, cancelled)
        except Exception:
            result = _failure('worker_failed')
        with self._lock:
            self._busy = False
            if generation != self._generation or self._closed:
                return _failure('cancelled')
            if result['status'] in {'read', 'redirect'}:
                result = copy.deepcopy(result)
                result['source_id'] = secrets.token_hex(16)
                owned = {}
                for index, link in enumerate(result['links'], 1):
                    link['link_id'] = secrets.token_hex(16)
                    link['number'] = index
                    owned[link['link_id']] = link['url']
                self._snapshot, self._links = copy.deepcopy(result), MappingProxyType(owned)
            return copy.deepcopy(result)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read one anonymous static public source. No browser or account is used.')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    for action in ('read', 'session'):
        item = sub.add_parser(action)
        item.add_argument('--url', required=True)
    args = parser.parse_args(argv)
    reader = PublicReader()
    def emit(value):
        print(json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False))
    try:
        if args.action == 'status':
            emit(reader.status())
            return 0
        result = reader.read(args.url)
        emit(result)
        if args.action == 'read':
            return 0 if result['status'] in {'read', 'redirect'} else 2
        print('Commands: follow N (displayed numbered link), read (cached), clear, quit. No automatic refresh.')
        while True:
            try:
                command = input('public> ').strip()
            except EOFError:
                break
            if command == 'quit':
                break
            if command == 'read':
                result = reader.cached()
            elif command == 'clear':
                result = reader.clear()
            elif command.startswith('follow '):
                current = reader.cached()
                try:
                    number = int(command[7:])
                    selected = next(link for link in current['links'] if link['number'] == number)
                except (ValueError, StopIteration, KeyError):
                    result = reader.follow(current.get('source_id'), 'invalid')
                else:
                    result = reader.follow(current['source_id'], selected['link_id'])
            else:
                reader.clear()
                result = _failure('invalid_link')
            emit(result)
        return 0
    finally:
        reader.close()


if __name__ == '__main__':
    raise SystemExit(main())
