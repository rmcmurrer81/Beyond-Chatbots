"""Immutable, owner-declared code proposals. Nothing here executes or activates code."""
from contextlib import contextmanager
import hashlib
import json
import re
import sqlite3
import time

from .storage import text, token


class Abilities:
    """Files supplies the existing scoped, bounded, platform-safe source reader."""

    def __init__(self, store, files):
        self.store, self.files = store, files
        store.db.executescript('''
        CREATE TABLE IF NOT EXISTS ability_proposals (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL,
            at REAL NOT NULL, path TEXT NOT NULL, source BLOB NOT NULL,
            source_sha256 TEXT NOT NULL, permissions TEXT NOT NULL,
            supersedes TEXT UNIQUE REFERENCES ability_proposals(id),
            UNIQUE(name, version));
        CREATE TABLE IF NOT EXISTS ability_reviews (
            seq INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES ability_proposals(id),
            at REAL NOT NULL, verdict TEXT NOT NULL CHECK(verdict IN ('approved','rejected')),
            note TEXT NOT NULL, source_sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ability_selections (
            seq INTEGER PRIMARY KEY, name TEXT NOT NULL,
            proposal_id TEXT NOT NULL REFERENCES ability_proposals(id),
            previous_seq INTEGER REFERENCES ability_selections(seq),
            kind TEXT NOT NULL, at REAL NOT NULL);
        ''')
        # Accidental SQL updates/deletes cannot rewrite these histories. This is
        # not protection against an owner who can edit the database or code.
        for table in ('ability_proposals', 'ability_reviews', 'ability_selections'):
            for action in ('UPDATE', 'DELETE'):
                store.db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
                    BEFORE {action} ON {table} BEGIN
                    SELECT RAISE(ABORT, 'Ability history is append-only'); END''')
        store.db.commit()

    @contextmanager
    def _write(self, operation):
        try:
            with self.store.db:
                yield
        except (ValueError, OSError, sqlite3.Error) as error:
            # Never journal caller input or exception messages on failed attempts.
            # A full/broken database may also prevent this minimal failure record.
            try:
                with self.store.db:
                    self.store.event('ability.failed', {'operation': operation,
                                                        'error_type': type(error).__name__})
            except sqlite3.Error:
                pass
            raise

    @staticmethod
    def _name(name):
        if type(name) is not str or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}', name):
            raise ValueError('Ability name must be 1–64 lowercase identifier characters')
        return name

    def _row(self, id_):
        text(id_, 64)
        row = self.store.db.execute('SELECT * FROM ability_proposals WHERE id=?', (id_,)).fetchone()
        if row is None:
            raise ValueError('Unknown ability proposal ID')
        return row

    def _review(self, id_):
        return self.store.db.execute('SELECT * FROM ability_reviews WHERE proposal_id=? '
                                     'ORDER BY seq DESC LIMIT 1', (id_,)).fetchone()

    def _selected(self, name):
        return self.store.db.execute('SELECT * FROM ability_selections WHERE name=? '
                                     'ORDER BY seq DESC LIMIT 1', (name,)).fetchone()

    def _metadata(self, row):
        review, selection = self._review(row['id']), self._selected(row['name'])
        approved = review is not None and review['verdict'] == 'approved'
        recorded = selection is not None and selection['proposal_id'] == row['id']
        result = {key: row[key] for key in ('id', 'name', 'version', 'at', 'path',
                                          'source_sha256', 'supersedes')}
        result.update(source_bytes=len(row['source']), declared_permissions=json.loads(row['permissions']),
                      permissions_granted=[], review_status=review['verdict'] if review else 'unreviewed',
                      review_notes_kind='owner_declared_not_verified', tests_executed=False,
                      selection_recorded=recorded, selected_for_future=recorded and approved,
                      execution_enabled=False, activation_enabled=False,
                      status='selected_for_future' if recorded and approved else
                             review['verdict'] if review else 'proposed')
        return result

    def get(self, id_):
        """Metadata plus latest 100 declared reviews; source bytes are never printed."""
        result = self._metadata(self._row(id_))
        result['reviews'] = [dict(row) for row in self.store.db.execute(
            'SELECT * FROM ability_reviews WHERE proposal_id=? ORDER BY seq DESC LIMIT 100', (id_,))]
        result['review_count'] = self.store.db.execute(
            'SELECT COUNT(*) FROM ability_reviews WHERE proposal_id=?', (id_,)).fetchone()[0]
        result['reviews_truncated'] = result['review_count'] > len(result['reviews'])
        return result

    def source(self, id_):
        """Read stored bytes without evaluating, loading, or running them."""
        return bytes(self._row(id_)['source'])

    def list(self):
        """Latest 100 proposal metadata records; earlier IDs remain readable."""
        return [self._metadata(row) for row in self.store.db.execute(
            'SELECT * FROM ability_proposals ORDER BY rowid DESC LIMIT 100').fetchall()]

    def create(self, name, path, permissions, supersedes=None):
        with self._write('create'):
            self._name(name)
            if (type(permissions) is not list or len(permissions) > 16
                    or any(type(p) is not str or not re.fullmatch(r'[a-z][a-z0-9_.:-]{0,63}', p)
                           for p in permissions) or len(set(permissions)) != len(permissions)):
                raise ValueError('Declare at most 16 unique bounded permission labels; these grant nothing')
            latest = self.store.db.execute('SELECT * FROM ability_proposals WHERE name=? '
                                           'ORDER BY version DESC LIMIT 1', (name,)).fetchone()
            if supersedes is not None:
                prior = self._row(supersedes)
                if prior['name'] != name:
                    raise ValueError('A proposal can supersede only the same ability name')
            if (latest is None and supersedes is not None) or (latest is not None and supersedes != latest['id']):
                raise ValueError('A new version must explicitly supersede the latest proposal')
            source = self.files.read(path)  # Existing, explicitly named file only.
            id_, digest = token(), hashlib.sha256(source).hexdigest()
            self.store.db.execute('INSERT INTO ability_proposals VALUES (?,?,?,?,?,?,?,?,?)',
                (id_, name, latest['version'] + 1 if latest else 1, time.time(), path, source,
                 digest, json.dumps(sorted(permissions)), supersedes))
            self.store.event('ability.proposed', {'id': id_, 'source_sha256': digest,
                                                 'execution_enabled': False})
        return self.get(id_)

    def review(self, id_, verdict, note, source_sha256):
        with self._write('review'):
            row = self._row(id_)
            if type(verdict) is not str or verdict not in ('approved', 'rejected'):
                raise ValueError('Review verdict must be approved or rejected')
            text(note, 2048)
            if type(source_sha256) is not str or source_sha256 != row['source_sha256']:
                raise ValueError('Review must identify the exact stored source SHA-256')
            self.store.db.execute('INSERT INTO ability_reviews(proposal_id,at,verdict,note,source_sha256) '
                                  'VALUES (?,?,?,?,?)', (id_, time.time(), verdict, note, source_sha256))
            self.store.event('ability.review_declared', {'id': id_, 'verdict': verdict,
                             'source_sha256': source_sha256, 'tests_executed': False})
        return self.get(id_)

    def _require_approved(self, row):
        review = self._review(row['id'])
        if review is None or review['verdict'] != 'approved' or review['source_sha256'] != row['source_sha256']:
            raise ValueError('The latest source-bound declared review must be approved')

    def _select(self, row, previous_seq, kind):
        self._require_approved(row)
        self.store.db.execute('INSERT INTO ability_selections(name,proposal_id,previous_seq,kind,at) '
                              'VALUES (?,?,?,?,?)', (row['name'], row['id'], previous_seq, kind, time.time()))
        self.store.event('ability.' + kind, {'id': row['id'], 'source_sha256': row['source_sha256'],
                                           'execution_enabled': False, 'activation_enabled': False})

    def select(self, id_):
        with self._write('select'):
            row = self._row(id_)
            previous = self._selected(row['name'])
            if previous is not None and previous['proposal_id'] == id_:
                raise ValueError('This proposal already has the current selection record')
            self._select(row, previous['seq'] if previous else None, 'selected_for_future')
        return self.get(id_)

    def rollback(self, name):
        with self._write('rollback'):
            self._name(name)
            current = self._selected(name)
            if current is None or current['previous_seq'] is None:
                raise ValueError('No earlier selection to restore')
            prior = self.store.db.execute('SELECT * FROM ability_selections WHERE seq=?',
                                          (current['previous_seq'],)).fetchone()
            row = self._row(prior['proposal_id'])
            self._select(row, prior['previous_seq'], 'rolled_back_for_future')
        return self.get(row['id'])
