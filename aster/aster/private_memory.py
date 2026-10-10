"""Explicit local memory records, deterministic lookup and recoverable controls.

This is storage and substring retrieval, not model memory or semantic learning.
The legacy memories table and its IDs are preserved. Visibility metadata is kept
separately so existing Store.remember callers remain compatible.
"""
from datetime import date, datetime
import time

from .storage import text, token

CATEGORIES = ('decision', 'preference', 'history')
STATES = ('active', 'hidden', 'deleted')
MAX_CHAIN = 1000


def _category(value):
    if value not in CATEGORIES:
        raise ValueError('Category must be decision, preference or history')
    return value


def _source_date(value):
    if value is None:
        return None
    text(value, 64)
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError('Source timestamps require a timezone')
    except (ValueError, TypeError) as error:
        raise ValueError('Use an ISO date or timezone-qualified ISO timestamp') from error
    return value


def _limit(value, maximum=100):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'Limit must be an integer from 1 to {maximum}')
    return value


def _bool(value):
    if type(value) is not bool:
        raise ValueError('Visibility flags must be booleans')
    return value


class PrivateMemory:
    """One explicit memory view over the owner's existing Store.

    hide/delete/restore affect one record, never its correction relatives.
    A deleted record is recoverably hidden; its bytes are not erased. Raw legacy
    history remains an administrative retained-data view, not a filtered search.
    """
    def __init__(self, store):
        self.store = store
        self.store.db.create_function('aster_casefold', 1, str.casefold, deterministic=True)
        with self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS memory_metadata (
                memory_id TEXT PRIMARY KEY REFERENCES memories(id),
                category TEXT NOT NULL CHECK(category IN ('decision','preference','history')),
                source_date TEXT,
                state TEXT NOT NULL CHECK(state IN ('active','hidden','deleted')),
                updated_at REAL NOT NULL
            )''')
            self.store.db.execute('CREATE INDEX IF NOT EXISTS memory_supersedes_lookup ON memories(supersedes)')

    def status(self):
        return {
            'status': 'available', 'search': 'literal_case_insensitive_substring',
            'categories': list(CATEGORIES), 'states': list(STATES),
            'semantic_search': False, 'model_learning': False,
            'encrypted': False, 'deletion': 'recoverably_hidden_not_erased',
            'retained_data': True, 'purge_supported': False,
        }

    @staticmethod
    def _select():
        return '''SELECT m.*, COALESCE(d.category, 'history') AS category,
            d.source_date, COALESCE(d.state, 'active') AS state,
            COALESCE(d.updated_at, m.at) AS updated_at,
            EXISTS(SELECT 1 FROM memories child WHERE child.supersedes=m.id) AS is_superseded
            FROM memories m LEFT JOIN memory_metadata d ON d.memory_id=m.id'''

    @staticmethod
    def _result(row):
        result = dict(row)
        result['is_superseded'] = bool(result['is_superseded'])
        result['retained_data'] = True
        return result

    def get(self, id_):
        """Inspect an exact ID, including retained hidden/deleted content."""
        memory_id = id_
        text(memory_id, 128)
        row = self.store.db.execute(self._select() + ' WHERE m.id=?', (memory_id,)).fetchone()
        if row is None:
            raise ValueError('Unknown memory ID')
        return self._result(row)

    def remember(self, body, category='history', source='user', supersedes=None, source_date=None):
        text(body); text(source, 1024)
        _category(category); _source_date(source_date)
        with self.store.db:
            if supersedes is not None:
                previous = self.get(supersedes)
                if previous['state'] != 'active' or previous['is_superseded']:
                    raise ValueError('Correct an active current record; restore it first if hidden or deleted')
            memory_id, at = token(), time.time()
            self.store.db.execute('INSERT INTO memories(id,at,body,source,supersedes) VALUES (?,?,?,?,?)',
                                  (memory_id, at, body, source, supersedes))
            self.store.db.execute('INSERT INTO memory_metadata VALUES (?,?,?,?,?)',
                                  (memory_id, category, source_date, 'active', at))
            self.store.event('memory.append', {'id': memory_id, 'supersedes': supersedes, 'category': category})
        return memory_id

    def correct(self, id_, body, *, category=None, source=None, source_date=None):
        """Append a correction. Source/category inherit unless explicitly given.

        source_date describes the new claim's source and is not copied from the
        corrected claim; the new record always has its own creation timestamp.
        """
        previous = self.get(id_)
        return self.remember(body, previous['category'] if category is None else category,
                             previous['source'] if source is None else source,
                             id_, source_date)

    def search(self, query='', *, category=None, source=None, include_hidden=False,
               include_deleted=False, include_superseded=False, limit=50):
        """Newest-first literal body search; SQL wildcards have no special meaning."""
        if type(query) is not str or len(query.encode('utf-8')) > 1024:
            raise ValueError('Query must be text within 1024 UTF-8 bytes')
        _limit(limit)
        if category is not None:
            _category(category)
        if source is not None:
            text(source, 1024)
        for flag in (include_hidden, include_deleted, include_superseded):
            _bool(flag)
        conditions, values = [], []
        states = ['active'] + (['hidden'] if include_hidden else []) + (['deleted'] if include_deleted else [])
        conditions.append("COALESCE(d.state,'active') IN (" + ','.join('?' for _ in states) + ')')
        values.extend(states)
        if query:
            conditions.append('instr(aster_casefold(m.body), ?) > 0')
            values.append(query.casefold())
        if category is not None:
            conditions.append("COALESCE(d.category,'history')=?")
            values.append(category)
        if source is not None:
            conditions.append('m.source=?')
            values.append(source)
        if not include_superseded:
            conditions.append('NOT EXISTS(SELECT 1 FROM memories child WHERE child.supersedes=m.id)')
        sql = self._select() + ' WHERE ' + ' AND '.join(conditions) + ' ORDER BY m.at DESC,m.rowid DESC LIMIT ?'
        return [self._result(row) for row in self.store.db.execute(sql, (*values, limit))]

    def _state(self, memory_id, state):
        with self.store.db:
            row = self.get(memory_id)
            if row['state'] != state:
                self.store.db.execute('''INSERT INTO memory_metadata VALUES (?,?,?,?,?)
                    ON CONFLICT(memory_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at''',
                    (memory_id, row['category'], row['source_date'], state, time.time()))
                self.store.event('memory.visibility', {
                    'id': memory_id, 'state': state, 'retained_data': True,
                })
        return self.get(memory_id)

    def hide(self, id_):
        return self._state(id_, 'hidden')

    def delete(self, id_):
        """Recoverably hide one record, retaining all content and provenance."""
        return self._state(id_, 'deleted')

    def restore(self, id_):
        return self._state(id_, 'active')

    def chain(self, id_):
        """Inspect the retained correction family, including legacy branches.

        Cyclic/corrupted or excessively long chains fail explicitly, never loop
        or return a silently truncated history.
        """
        root = self.get(id_)
        visited = set()
        while root['supersedes'] is not None:
            if root['id'] in visited or len(visited) >= MAX_CHAIN:
                raise ValueError('Correction chain is cyclic or exceeds the 1000-record inspection limit')
            visited.add(root['id'])
            root = self.get(root['supersedes'])
        result, pending, visited = [], [root['id']], set()
        while pending:
            current = pending.pop(0)
            if current in visited or len(visited) >= MAX_CHAIN:
                raise ValueError('Correction chain is cyclic or exceeds the 1000-record inspection limit')
            visited.add(current)
            result.append(self.get(current))
            pending.extend(row['id'] for row in self.store.db.execute(
                'SELECT id FROM memories WHERE supersedes=? ORDER BY at,rowid LIMIT ?', (current, MAX_CHAIN + 1)))
            if len(visited) + len(pending) > MAX_CHAIN:
                raise ValueError('Correction chain exceeds the 1000-record inspection limit')
        return result
