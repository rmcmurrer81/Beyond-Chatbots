"""Owner-local state. SQLite transactions preserve history, not model intelligence."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid
from .platform import linklike, lock_state


def token():
    return uuid.uuid4().hex


def text(value, limit=32768):
    if type(value) is not str or not value.strip() or len(value.encode('utf-8')) > limit:
        raise ValueError('Expected nonempty bounded text')
    return value


class Store:
    def __init__(self, root):
        self.root = Path(root).absolute()
        if os.name == 'nt' and (len(self.root.drive) != 2 or self.root.drive[1] != ':'):
            raise ValueError('Windows state requires a local drive path, not UNC/device paths')
        # State must be a new or owner-controlled real directory, never a symlink.
        for part in [self.root, *self.root.parents]:
            if linklike(part):
                raise ValueError('Symlink/reparse state paths are forbidden')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = None
        self.db = None
        try:
            lock_path = self.root / 'session.lock'
            if linklike(lock_path):
                raise ValueError('Symlink/reparse lock file is forbidden')
            self.lock = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
            lock_info = os.fstat(self.lock)
            if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_nlink != 1:
                raise ValueError('Lock must be a regular single-link file')
            try:
                lock_state(self.lock)
            except OSError:
                raise RuntimeError('Another Aster command is using this state directory')
            path = self.root / 'aster.sqlite3'
            for name in ['aster.sqlite3', 'aster.sqlite3-wal', 'aster.sqlite3-shm', 'aster.sqlite3-journal']:
                candidate = self.root / name
                if linklike(candidate):
                    raise ValueError('Symlink database is forbidden')
                if candidate.exists():
                    info = candidate.stat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError('Database must be a regular single-link file')
                    if info.st_size > 64 * 1024 * 1024:
                        raise ValueError('State database exceeds the 64 MiB limit')
            self.db = sqlite3.connect(path, timeout=5)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('PRAGMA foreign_keys=ON')
            page_size = self.db.execute('PRAGMA page_size').fetchone()[0]
            self.db.execute(f'PRAGMA max_page_count={64 * 1024 * 1024 // page_size}')  # Fail rather than prune history
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS identity (id TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, at REAL NOT NULL, body TEXT NOT NULL, source TEXT NOT NULL, supersedes TEXT REFERENCES memories(id));
            CREATE TABLE IF NOT EXISTS prompts (id TEXT PRIMARY KEY, at REAL NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, at REAL NOT NULL, action TEXT NOT NULL, args TEXT NOT NULL, status TEXT NOT NULL, result TEXT, budget REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS changes (id TEXT PRIMARY KEY, at REAL NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL, before BLOB, after BLOB, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS job_effects (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id),
                memory_id TEXT UNIQUE REFERENCES memories(id),
                change_id TEXT UNIQUE REFERENCES changes(id),
                CHECK ((memory_id IS NOT NULL) + (change_id IS NOT NULL) = 1));
            ''')
            with self.db:
                if not self.db.execute('SELECT 1 FROM identity').fetchone():
                    self.db.execute('INSERT INTO identity VALUES (?, ?)', (token(), 'Aster'))

        except BaseException:
            if self.db is not None: self.db.close()
            if self.lock is not None: os.close(self.lock)
            raise

    def event(self, kind, payload):
        self.db.execute('INSERT INTO events(at,kind,payload) VALUES (?,?,?)',
                        (time.time(), kind, json.dumps(payload, ensure_ascii=False, allow_nan=False)))

    def identity(self):
        return dict(self.db.execute('SELECT * FROM identity').fetchone())

    @contextmanager
    def effect_transaction(self):
        """Own one durable effect commit; never commit a caller's transaction.

        sqlite3 connection contexts are not nested transactions. Refuse an
        ambient transaction before an effect can be inserted or a file replaced.
        """
        if self.db.in_transaction:
            raise RuntimeError('Effect operation requires transaction ownership')
        with self.db:
            yield

    def link_job_effect(self, job_id, *, memory_id=None, change_id=None):
        """Insert only inside the same transaction as the associated effect."""
        if not self.db.in_transaction:
            raise RuntimeError('Job effect linkage requires an effect transaction')
        action = 'memory.append' if memory_id is not None else 'file.write'
        job = self.db.execute('SELECT action,status FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not job or job['action'] != action or job['status'] != 'running':
            raise ValueError('Effect requires the matching running job')
        self.db.execute('INSERT INTO job_effects VALUES (?,?,?)', (job_id, memory_id, change_id))

    def job_effect(self, job_id):
        """Describe durable evidence without replay or inferring job success."""
        row = self.db.execute('SELECT * FROM job_effects WHERE job_id=?', (job_id,)).fetchone()
        if row is None:
            return {'state': 'unknown', 'reason': 'no_durable_link'}
        if row['memory_id'] is not None:
            return {'kind': 'memory.append', 'memory_id': row['memory_id'], 'state': 'committed'}
        change = self.db.execute('SELECT status FROM changes WHERE id=?', (row['change_id'],)).fetchone()
        return {'kind': 'file.write', 'change_id': row['change_id'],
                'state': change['status'] if change else 'unknown'}

    def remember(self, body, source='user', supersedes=None, *, job_id=None):
        text(body); text(source, 1024)
        id_ = token()
        with self.effect_transaction():
            self.db.execute('INSERT INTO memories VALUES (?,?,?,?,?)', (id_, time.time(), body, source, supersedes))
            if job_id is not None:
                self.link_job_effect(job_id, memory_id=id_)
            self.event('memory.append', {'id': id_, 'supersedes': supersedes})
        return id_

    def rows(self, table):
        if table not in {'memories', 'events', 'prompts', 'jobs', 'changes'}:
            raise ValueError('Unknown history')
        rows = [dict(r) for r in self.db.execute(f'SELECT * FROM {table} ORDER BY rowid DESC LIMIT 100')]
        for row in rows:
            row.pop('before', None); row.pop('after', None)
            if table == 'jobs': row['effect'] = self.job_effect(row['id'])
        return rows

    def close(self):
        self.db.close()
        os.close(self.lock)
