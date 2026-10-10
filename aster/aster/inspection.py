"""Bounded inspection of existing owner-local state without Store or lifecycle writes.

This is a SQLite read transaction, not recovery or a database-health certificate.
mode=ro and query_only prohibit database-content writes. SQLite may still use WAL
reader bookkeeping in existing/createable sidecars; no immutable/nolock shortcut
is used on a database that another process may change. Never copy just the main
file from live WAL state. These trusted-owner path checks match Store's boundary;
they are not a hostile same-user filesystem sandbox.
"""
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time

from .platform import linklike

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_ROWS = 50
TEXT_BYTES = 1024
MAX_OUTPUT_BYTES = 256 * 1024
MAX_VM_STEPS = 100000
PROGRESS_INTERVAL = 1000
SOFT_SECONDS = 2.0
BUSY_SECONDS = 0.2
MAX_SQLITE_VALUE_BYTES = 1024 * 1024

# Fixed identifiers only. No caller SQL, schema SQL, file BLOBs or extension loads.
_FIELDS = {
    'identity': ('id', 'name'),
    'memories': ('id', 'at', 'body', 'source', 'supersedes'),
    'events': ('seq', 'at', 'kind', 'payload'),
    'prompts': ('id', 'at', 'body', 'status'),
    'jobs': ('id', 'at', 'action', 'args', 'status', 'result', 'budget'),
    'changes': ('id', 'at', 'path', 'kind', 'status'),
    'lifecycle_sessions': ('id', 'started_at', 'last_seen_at', 'observed_seconds',
                           'closed_at', 'status', 'auto_start'),
    'lifecycle_state': ('singleton', 'crash_streak', 'blocked_until', 'clock_reversal',
                        'recovery_required', 'last_wall'),
    'job_effects': ('job_id', 'memory_id', 'change_id'),
}
_NUMERIC = {'seq', 'at', 'budget', 'started_at', 'last_seen_at', 'observed_seconds',
            'closed_at', 'auto_start', 'singleton', 'crash_streak', 'blocked_until',
            'clock_reversal', 'recovery_required', 'last_wall'}
_TABLES = frozenset(_FIELDS) | {'memory_metadata'}


class _Budget:
    def __init__(self):
        self.started = time.monotonic()
        self.deadline = self.started + SOFT_SECONDS
        self.steps = 0
        self.reason = None

    def exhausted(self):
        if self.reason is None and time.monotonic() >= self.deadline:
            self.reason = 'time_budget'
        return self.reason is not None

    def progress(self):
        self.steps += PROGRESS_INTERVAL
        if self.steps >= MAX_VM_STEPS:
            self.reason = 'work_budget'
        return int(self.exhausted())


def _error(exc, budget):
    if budget.reason:
        return budget.reason
    primary = getattr(exc, 'sqlite_errorcode', 0) & 0xff
    return {
        # Stable SQLite primary result codes; CPython 3.10 lacks named error
        # constants/error attributes and therefore returns the generic category.
        5: 'busy', 6: 'locked', 13: 'database_full', 11: 'corrupt',
        26: 'not_a_database', 18: 'value_limit', 9: 'query_interrupted',
        8: 'read_only_wal_unavailable',
    }.get(primary, 'unavailable_or_incompatible')


def _authorizer(action, first, second, database, trigger):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and first in (
            _TABLES | {'sqlite_master', 'sqlite_schema'}):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and second in {'substr', 'typeof', 'coalesce'}:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and first == 'table_info' and second in _TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_TRANSACTION and first == 'BEGIN':
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _state_path(root):
    root = Path(root).absolute()
    if os.name == 'nt' and (len(root.drive) != 2 or root.drive[1] != ':'):
        raise ValueError('Local Windows state required')
    path = root / 'aster.sqlite3'
    if any(linklike(part) for part in [path, root, *root.parents]):
        raise ValueError('Unsafe state path')
    sizes = {}
    for name in ('aster.sqlite3', 'aster.sqlite3-wal', 'aster.sqlite3-shm', 'aster.sqlite3-journal'):
        candidate = root / name
        if linklike(candidate):
            raise ValueError('Unsafe database sidecar')
        try:
            info = candidate.stat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_DATABASE_BYTES:
            raise ValueError('Unsafe or oversized database')
        sizes[name] = info.st_size
    return path, sizes


def _projection(fields, alias=''):
    prefix = alias + '.' if alias else ''
    result = []
    for field in fields:
        column = prefix + field
        if field in _NUMERIC:
            result.append(f"CASE WHEN typeof({column}) IN ('integer','real') THEN {column} ELSE NULL END AS {field}")
        else:
            result.append(f'substr(CAST({column} AS BLOB),1,{TEXT_BYTES + 1}) AS {field}')
    return ','.join(result)


def _row(row):
    result, truncated = {}, []
    for key, value in dict(row).items():
        if isinstance(value, bytes):
            if len(value) > TEXT_BYTES:
                truncated.append(key)
            value = value[:TEXT_BYTES].decode('utf-8', 'replace')
        elif isinstance(value, float) and not math.isfinite(value):
            value = None
        result[key] = value
    if '_effect_memory_id' in result:
        memory_id = result.pop('_effect_memory_id')
        change_id = result.pop('_effect_change_id')
        change_status = result.pop('_effect_change_status')
        memory_present = result.pop('_effect_memory_present')
        change_present = result.pop('_effect_change_present')
        effect = {'state': 'unknown', 'reason': 'no_durable_link'}
        if memory_id is not None and change_id is not None:
            effect = {'state': 'unknown', 'reason': 'invalid_durable_link',
                      'memory_id': memory_id, 'change_id': change_id}
        elif memory_id is not None:
            effect = {'kind': 'memory.append', 'memory_id': memory_id,
                      'state': 'committed' if memory_present == 1 else 'unknown'}
            if memory_present != 1:
                effect['reason'] = 'linked_record_unavailable'
        elif change_id is not None:
            effect = {'kind': 'file.write', 'change_id': change_id,
                      'state': change_status if change_present == 1 else 'unknown'}
            if change_present != 1:
                effect['reason'] = 'linked_record_unavailable'
        result['effect'] = effect
        truncated = [key.replace('_effect_', 'effect.') for key in truncated]
    if truncated:
        result['truncated_fields'] = truncated
    return result


def _section(db, budget, table, limit, *, tables, where=''):
    if budget.exhausted():
        return {'status': 'unavailable', 'reason': budget.reason, 'rows': []}
    if table not in tables:
        return {'status': 'unavailable', 'reason': 'table_absent', 'rows': []}
    fields = _FIELDS[table]
    try:
        alias = 'm' if table == 'memories' else ('j' if table == 'jobs' else '')
        projection = _projection(fields, alias)
        tail = ''
        if table == 'memories' and 'memory_metadata' in tables:
            # Match normal history visibility without constructing PrivateMemory,
            # whose initializer creates tables/indexes. An incompatible metadata
            # table fails this section closed instead of exposing hidden bodies.
            tail = " LEFT JOIN memory_metadata d ON d.memory_id=m.id WHERE coalesce(d.state,'active')='active'"
        elif table == 'jobs' and 'job_effects' in tables:
            # Link each returned job, including an old interrupted job that the
            # separate newest-effect history limit may omit. All joins use PKs
            # and share this read snapshot/VM budget; no helper/migration writes.
            tail = ' LEFT JOIN job_effects e ON e.job_id=j.id'
            projection += f',substr(CAST(e.memory_id AS BLOB),1,{TEXT_BYTES + 1}) AS _effect_memory_id'
            projection += f',substr(CAST(e.change_id AS BLOB),1,{TEXT_BYTES + 1}) AS _effect_change_id'
            if 'memories' in tables:
                tail += ' LEFT JOIN memories em ON em.id=e.memory_id'
                projection += ',CASE WHEN em.id IS NOT NULL THEN 1 ELSE 0 END AS _effect_memory_present'
            else:
                projection += ',0 AS _effect_memory_present'
            if 'changes' in tables:
                tail += ' LEFT JOIN changes ec ON ec.id=e.change_id'
                projection += ',CASE WHEN ec.id IS NOT NULL THEN 1 ELSE 0 END AS _effect_change_present'
                projection += f',substr(CAST(ec.status AS BLOB),1,{TEXT_BYTES + 1}) AS _effect_change_status'
            else:
                projection += ',0 AS _effect_change_present,NULL AS _effect_change_status'
            if where:
                tail += ' WHERE j.' + where
        elif where:
            tail = ' WHERE ' + (alias + '.' if alias else '') + where
        sql = f'SELECT {projection} FROM {table}' + (' ' + alias if alias else '') + tail
        sql += ' ORDER BY ' + (alias + '.' if alias else '') + 'rowid DESC LIMIT ?'
        rows = db.execute(sql, (limit + 1,)).fetchall()
        converted = [_row(row) for row in rows[:limit]]
        if table == 'jobs' and 'job_effects' not in tables:
            for row in converted:
                row['effect'] = {'state': 'unknown', 'reason': 'no_durable_link'}
        return {'status': 'available', 'rows': converted, 'has_more': len(rows) > limit}
    except sqlite3.Error as exc:
        return {'status': 'unavailable', 'reason': _error(exc, budget), 'rows': []}


def inspect_state(root, *, limit=20):
    """Return a bounded, locally displayed snapshot; never start/recover Store.

    Missing/incompatible sections and exhausted budgets are explicit. An empty
    interrupted-work section is only a snapshot observation, not permission to
    retry a job or a proof that an earlier job had no effect. Legacy unlinked jobs
    remain unknown. Text fields are previews, with truncation labels; no file
    before/after BLOBs or workspace file contents are read. No identity, audit,
    history, limit, lifecycle, job or file mutation is attempted.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError(f'Limit must be an integer from 1 to {MAX_ROWS}')
    budget = _Budget()
    report = {
        'status': 'unavailable', 'read_only': True,
        'snapshot': 'sqlite_read_transaction', 'integrity': 'not_checked',
        'recovery_performed': False, 'replayed_jobs': 0,
        'legacy_unlinked_job_outcome': 'unknown',
        'wal_reader_bookkeeping': 'sqlite_may_require_sidecars',
        'limits': {'rows_per_section': limit, 'text_bytes_per_field': TEXT_BYTES,
                   'database_bytes_per_file': MAX_DATABASE_BYTES, 'output_bytes': MAX_OUTPUT_BYTES,
                   'sqlite_vm_steps': MAX_VM_STEPS, 'progress_interval': PROGRESS_INTERVAL,
                   'soft_seconds': SOFT_SECONDS, 'busy_timeout_seconds': BUSY_SECONDS},
        'sections': {},
    }
    db = None
    try:
        path, sizes = _state_path(root)
        if 'aster.sqlite3' not in sizes:
            report['status'], report['reason'] = 'not_found', 'database_absent'
            return report
        report['storage_bytes'] = sizes
        # as_uri safely quotes #, %, spaces and other filename characters.
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=BUSY_SECONDS,
                             isolation_level=None)
        db.row_factory = sqlite3.Row
        db.set_progress_handler(budget.progress, PROGRESS_INTERVAL)
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-512')
        db.execute('PRAGMA temp_store=MEMORY')
        db.execute('PRAGMA mmap_size=0')
        # CPython 3.10 lacks setlimit; fixed input-file/output/work bounds still
        # apply, but a stricter SQLite value-allocation limit is reported unavailable.
        report['sqlite_value_limit_enforced'] = hasattr(db, 'setlimit')
        if hasattr(db, 'setlimit'):
            db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_SQLITE_VALUE_BYTES)
            db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 8192)
            db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 64)
            db.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        db.set_authorizer(_authorizer)
        db.execute('BEGIN')  # Deferred read snapshot; no Store/session lock acquisition.
        placeholders = ','.join('?' for _ in _TABLES)
        schema = {row[0]: row[1] for row in db.execute(
            f"SELECT name,type FROM sqlite_master WHERE name IN ({placeholders}) LIMIT 20",
            tuple(_TABLES))}
        tables = {name for name, kind in schema.items() if kind == 'table'}
        for table in _FIELDS:
            if table == 'memories' and 'memory_metadata' in schema and schema['memory_metadata'] != 'table':
                # A present unsupported object is not a legacy absent table.
                # Never read bodies while their visibility policy is unavailable.
                report['sections'][table] = {'status': 'unavailable',
                    'reason': 'incompatible_visibility_metadata', 'rows': []}
            else:
                report['sections'][table] = _section(db, budget, table, limit, tables=tables)
        report['sections']['memories']['visibility'] = 'active_only'
        report['sections']['interrupted_jobs'] = _section(
            db, budget, 'jobs', limit, tables=tables, where="status IN ('running','interrupted')")
        report['sections']['prepared_changes'] = _section(
            db, budget, 'changes', limit, tables=tables, where="status='prepared'")
        available = sum(section['status'] == 'available' for section in report['sections'].values())
        report['status'] = 'available' if available == len(report['sections']) else ('partial' if available else 'unavailable')
    except ValueError:
        report['reason'] = 'unsafe_or_oversized_state'
    except OSError:
        report['reason'] = 'state_unavailable'
    except sqlite3.Error as exc:
        report['reason'] = _error(exc, budget)
    finally:
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                report['close_error'] = 'connection_close_failed'
        report['elapsed_seconds'] = round(max(0.0, time.monotonic() - budget.started), 6)
        report['sqlite_progress_steps'] = budget.steps
        # The CLI uses indent=2. Reserve 128 bytes for the final elapsed update
        # and newline. Batch reductions halve history row counts while retaining
        # each section's first observation, including exact identity/work IDs.
        while len(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False).encode('utf-8')) + 1 > MAX_OUTPUT_BYTES - 128:
            populated = [section for section in report['sections'].values() if len(section['rows']) > 1]
            if not populated:
                # Fixed current fields fit with one row/section. If future limits
                # make even that impossible, fail explicitly instead of looping.
                report['status'], report['reason'] = 'unavailable', 'output_budget'
                report['sections'] = {}
                report['output_limited'] = True
                break
            for section in populated:
                del section['rows'][max(1, len(section['rows']) // 2):]
                section['has_more'] = True
                section['output_limited'] = True
            report['output_limited'] = True
        # Include connection close, row conversion and output-bounding work.
        report['elapsed_seconds'] = round(max(0.0, time.monotonic() - budget.started), 6)
    return report
