"""Transactional local revisions and leased jobs; never mutates canonical designs."""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .model import digest, validate


class StaleProposal(ValueError): pass


class Store:
    def __init__(self, root):
        self.root = Path(root)
        folder = self.root/'workspace3d'
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder/'history.sqlite3'
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT PRIMARY KEY, parent TEXT, created REAL NOT NULL,
                    scene TEXT NOT NULL, reason TEXT NOT NULL, sources TEXT NOT NULL,
                    tests TEXT NOT NULL, fingerprint TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS pointers (name TEXT PRIMARY KEY, revision TEXT);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL, lease REAL,
                    token TEXT, error TEXT, created REAL NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally: db.close()

    @staticmethod
    def _pointer(db, name):
        row = db.execute('SELECT revision FROM pointers WHERE name=?',(name,)).fetchone()
        return row[0] if row else None

    def pointer(self, name='latest'):
        with self.connection() as db: return self._pointer(db,name)

    def revision(self, rid=None):
        with self.connection() as db:
            rid = rid or self._pointer(db,'latest')
            row = db.execute('SELECT * FROM revisions WHERE id=?',(rid,)).fetchone()
        if not row: return None
        result = dict(row)
        for key in ('scene','sources','tests'): result[key] = json.loads(result[key])
        return result

    def history(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,parent,created,reason FROM revisions ORDER BY created DESC')]

    def add(self, scene, reason, sources, tests, *, expected_parent, fingerprint=None, as_input=False):
        scene = validate(scene)
        if tests.get('scene_hash') != digest(scene):
            raise ValueError('Test results do not belong to this scene.')
        fingerprint = fingerprint or digest({'scene':scene,'reason':reason,'sources':sources,'parent':expected_parent})
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM revisions WHERE fingerprint=?',(fingerprint,)).fetchone()
            if existing: return existing[0]
            if self._pointer(db,'latest') != expected_parent:
                raise StaleProposal('Workspace changed while the proposal was being tested; refresh and retry.')
            rid = uuid.uuid4().hex
            db.execute('INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)',
                       (rid,expected_parent,time.time(),json.dumps(scene,allow_nan=False),str(reason),json.dumps(sources),json.dumps(tests),fingerprint))
            db.execute("INSERT OR REPLACE INTO pointers VALUES ('latest',?)",(rid,))
            if as_input: db.execute("INSERT OR REPLACE INTO pointers VALUES ('input',?)",(rid,))
            return rid

    def accept(self, rid):
        """Select a workspace baseline only; never promote a canonical physical design."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM revisions WHERE id=?',(rid,)).fetchone():
                raise ValueError('Unknown revision.')
            db.execute("INSERT OR REPLACE INTO pointers VALUES ('accepted',?)",(rid,))

    def enqueue(self, payload):
        fingerprint = digest({k:v for k,v in payload.items() if k != "base_revision"})
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO jobs VALUES (?,?,?,\'queued\',NULL,NULL,NULL,?)',
                       (uuid.uuid4().hex,fingerprint,json.dumps(payload,allow_nan=False),time.time()))
            return db.execute('SELECT id FROM jobs WHERE fingerprint=?',(fingerprint,)).fetchone()[0]

    def claim(self, lease_seconds=120):
        now = time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET state='queued',token=NULL WHERE state='running' AND lease<?",(now,))
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row: return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',lease=?,token=? WHERE id=?",(now+lease_seconds,token,row['id']))
            return {'id':row['id'],'token':token,'payload':json.loads(row['payload'])}

    def finish(self, job, error=None):
        with self.connection() as db:
            db.execute('UPDATE jobs SET state=?,error=?,lease=NULL WHERE id=? AND token=?',
                       ('error' if error else 'done',str(error)[:2000] if error else None,job['id'],job['token']))

    def job_status(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT state,error,created FROM jobs ORDER BY created DESC LIMIT 5')]


def compare(before, after):
    a = {p['id']:p for p in (before or {}).get('parts',[])}
    b = {p['id']:p for p in after.get('parts',[])}
    return {'added':sorted(b.keys()-a.keys()),'removed':sorted(a.keys()-b.keys()),
            'changed':sorted(k for k in a.keys()&b.keys() if a[k] != b[k]),
            'unknowns_changed':(before or {}).get('unknowns',[]) != after.get('unknowns',[]),
            'requirements_changed':(before or {}).get('requirements',{}) != after.get('requirements',{})}
