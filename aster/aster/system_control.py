"""Explicit owner-local memory settings; no external programs or OS settings."""
from dataclasses import asdict
from .memory_pressure import MemoryConfig, MemoryGuard


def _table(store):
    store.db.execute('''CREATE TABLE IF NOT EXISTS memory_policy (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        version INTEGER NOT NULL, high_percent REAL NOT NULL, resume_percent REAL NOT NULL)''')


def memory_config(store):
    _table(store)
    row = store.db.execute('SELECT * FROM memory_policy WHERE singleton=1').fetchone()
    if row is None:
        return MemoryConfig()
    if row['version'] != 1:
        raise ValueError('Unsupported memory policy version')
    return MemoryConfig(high_used_percent=row['high_percent'], resume_used_percent=row['resume_percent'])


def memory_guard(store):
    return MemoryGuard(memory_config(store))


def configure_memory(store, high_percent, resume_percent):
    config = MemoryConfig(high_used_percent=high_percent, resume_used_percent=resume_percent)
    _table(store)
    with store.db:
        store.db.execute('INSERT INTO memory_policy VALUES (1,1,?,?) ON CONFLICT(singleton) '
                         'DO UPDATE SET version=1,high_percent=excluded.high_percent,resume_percent=excluded.resume_percent',
                         (config.high_used_percent, config.resume_used_percent))
        store.event('memory_policy.configured', {'high_percent': high_percent, 'resume_percent': resume_percent})
    return {'settings': asdict(config), 'scope': 'Aster new-job admission only',
            'external_app_closure_enabled': False, 'takes_effect': 'next Aster command or desktop launch'}
