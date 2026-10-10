"""Durable foreground lifecycle, explicit recovery, and auto-start crash backoff.

Requires an already-open Store, and therefore its existing single-instance lock.
Only lifecycle records are changed at startup: files, jobs, prompts and outbound
work are never replayed or reconciled. There is no restart watchdog or subprocess.
Process-exit tests do not establish power-loss durability.
"""
from dataclasses import dataclass
import math
import os
import time

from .storage import Store, token


@dataclass(frozen=True)
class LifecycleConfig:
    crash_threshold: int = 3
    short_session_seconds: float = 60.0
    cooldown_seconds: float = 300.0

    def __post_init__(self):
        if type(self.crash_threshold) is not int or not 1 <= self.crash_threshold <= 100:
            raise ValueError('Crash threshold must be an integer from 1 to 100')
        for value in (self.short_session_seconds, self.cooldown_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 86400:
                raise ValueError('Lifecycle durations must be finite, between 1 and 86400 seconds')


class AutoStartBlocked(RuntimeError):
    def __init__(self, report):
        self.report = report
        reason = ('Clock reversal requires a manual recovery launch' if report['clock_reversal_detected'] else
                  'Repeated short unclean sessions: auto-start is in cooldown; launch manually to inspect recovery')
        super().__init__(reason)


def _timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Lifecycle clock must return a finite nonnegative number')
    return float(value)


class Lifecycle:
    """Call start after Store acquisition; heartbeat on the controller's idle tick.

    Unclean duration uses only the last durable monotonic runtime observation. A
    missing heartbeat is conservatively considered short, never invented uptime.
    A backward wall/monotonic clock is reported, and subsequent auto-starts require
    a clean manual launch. Cooldown is wall-clock based across boots; its expiration
    cannot be made immune to forward clock changes without a trusted clock service.
    """
    def __init__(self, store, *, auto_start=False, config=None, wall_clock=None, monotonic=None):
        if not isinstance(store, Store) or store.lock is None or store.db is None:
            raise ValueError('Lifecycle requires an already-open, locked Store')
        os.fstat(store.lock)  # Reject a closed Store before attempting lifecycle work.
        store.db.execute('SELECT 1')
        if type(auto_start) is not bool:
            raise ValueError('auto_start must be a boolean')
        self.store, self.auto_start = store, auto_start
        self.config = config if config is not None else LifecycleConfig()
        if not isinstance(self.config, LifecycleConfig):
            raise ValueError('Expected LifecycleConfig')
        self._wall = wall_clock if wall_clock is not None else time.time
        self._mono = monotonic if monotonic is not None else time.monotonic
        if not callable(self._wall) or not callable(self._mono):
            raise ValueError('Lifecycle clocks must be callable')
        self.session_id = None
        self._ready = self._closed = False
        self._last_wall = self._last_mono = None
        self._observed_seconds = 0.0
        self._unclean_previous = []
        self._unclean_count = 0
        self._integrity = 'not_checked'
        self._allowed = None
        self._clock_reversed_this_session = False

    def _counts(self):
        return {
            'prepared_changes': self.store.db.execute("SELECT count(*) FROM changes WHERE status='prepared'").fetchone()[0],
            'running_jobs': self.store.db.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0],
        }

    def start(self):
        if self._closed:
            raise RuntimeError('Lifecycle is closed')
        if self.session_id is not None:
            return self.status()
        if self._allowed is False:
            raise AutoStartBlocked(self.status())
        # Bounded database size is enforced by Store; stop before lifecycle writes
        # on any failed quick check. This verifies SQLite, not workspace file bytes.
        check = self.store.db.execute('PRAGMA quick_check(1)').fetchone()
        if check is None or check[0] != 'ok':
            self._integrity = 'failed'
            raise RuntimeError('State integrity check failed; automatic startup stopped')
        self._integrity = 'ok'
        now, mono = _timestamp(self._wall()), _timestamp(self._mono())
        self.store.db.executescript('''
        CREATE TABLE IF NOT EXISTS lifecycle_sessions (
            id TEXT PRIMARY KEY, started_at REAL NOT NULL, last_seen_at REAL NOT NULL,
            observed_seconds REAL NOT NULL, closed_at REAL,
            status TEXT NOT NULL CHECK(status IN ('running','clean','unclean')),
            auto_start INTEGER NOT NULL CHECK(auto_start IN (0,1)));
        CREATE TABLE IF NOT EXISTS lifecycle_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), crash_streak INTEGER NOT NULL,
            blocked_until REAL, clock_reversal INTEGER NOT NULL,
            recovery_required INTEGER NOT NULL, last_wall REAL NOT NULL);
        ''')
        self._ready = True
        with self.store.db:
            self.store.db.execute('INSERT OR IGNORE INTO lifecycle_state VALUES (1,0,NULL,0,0,?)', (now,))
            meta = dict(self.store.db.execute('SELECT * FROM lifecycle_state WHERE singleton=1').fetchone())
            reverse = bool(meta['clock_reversal']) or now < meta['last_wall']
            self._clock_reversed_this_session = reverse
            streak, blocked = meta['crash_streak'], meta['blocked_until']
            if blocked is not None and now >= blocked and not reverse:
                streak, blocked = 0, None
            recovery = bool(meta['recovery_required'])
            for old in self.store.db.execute("SELECT * FROM lifecycle_sessions WHERE status='running' ORDER BY rowid"):
                recovery = True
                self._unclean_count += 1
                if len(self._unclean_previous) < 100:
                    self._unclean_previous.append(old['id'])
                streak = streak + 1 if old['observed_seconds'] < self.config.short_session_seconds else 0
                self.store.event('lifecycle.unclean', {'session_id': old['id'],
                    'observed_seconds': old['observed_seconds'], 'replayed_jobs': 0})
            self.store.db.execute("UPDATE lifecycle_sessions SET status='unclean' WHERE status='running'")
            counts = self._counts()
            recovery = recovery or bool(counts['prepared_changes'] or counts['running_jobs'])
            if streak >= self.config.crash_threshold and blocked is None:
                blocked = now + self.config.cooldown_seconds
            self._allowed = not (self.auto_start and (reverse or (blocked is not None and now < blocked)))
            # Manual launch is always the inspection/recovery path, including after
            # a clock correction. Only its clean close clears the reversal latch.
            last_wall = now if self._allowed else max(now, meta['last_wall'])
            self.store.db.execute('UPDATE lifecycle_state SET crash_streak=?,blocked_until=?,clock_reversal=?,recovery_required=?,last_wall=? WHERE singleton=1',
                (streak, blocked, int(reverse), int(recovery), last_wall))
            if self._allowed:
                self.session_id = token()
                self.store.db.execute('INSERT INTO lifecycle_sessions VALUES (?,?,?,?,?,?,?)',
                    (self.session_id, now, now, 0.0, None, 'running', int(self.auto_start)))
                self.store.event('lifecycle.started', {'session_id': self.session_id,
                    'auto_start': self.auto_start, 'recovery_required': recovery, 'replayed_jobs': 0})
                self._last_wall, self._last_mono = now, mono
            else:
                self.store.event('lifecycle.auto_start_blocked', {'blocked_until': blocked,
                    'clock_reversal': reverse, 'crash_streak': streak})
        report = self.status()
        if not self._allowed:
            raise AutoStartBlocked(report)
        return report

    def status(self):
        counts = self._counts()
        meta = dict(self.store.db.execute('SELECT * FROM lifecycle_state WHERE singleton=1').fetchone()) if self._ready else {}
        return {'session_id': self.session_id, 'auto_start': self.auto_start,
                'allowed': self._allowed, 'closed': self._closed, 'integrity': self._integrity,
                'recovery_required': bool(meta.get('recovery_required', False)) or bool(counts['prepared_changes'] or counts['running_jobs']),
                'unclean_previous_sessions': list(self._unclean_previous),
                'unclean_previous_count': self._unclean_count,
                'crash_streak': meta.get('crash_streak', 0),
                'auto_start_blocked_until': meta.get('blocked_until'),
                'clock_reversal_detected': self._clock_reversed_this_session or bool(meta.get('clock_reversal', False)),
                'observed_session_seconds': self._observed_seconds,
                'replayed_jobs': 0, 'automatic_recovery': False, **counts}

    def heartbeat(self):
        if self.session_id is None or self._closed:
            return self.status()
        now, mono = _timestamp(self._wall()), _timestamp(self._mono())
        reverse = now < self._last_wall or mono < self._last_mono
        if mono >= self._last_mono:
            self._observed_seconds += mono - self._last_mono
        self._last_wall, self._last_mono = now, mono
        self._clock_reversed_this_session = self._clock_reversed_this_session or reverse
        with self.store.db:
            self.store.db.execute('UPDATE lifecycle_sessions SET last_seen_at=?,observed_seconds=? WHERE id=? AND status=\'running\'',
                (now, self._observed_seconds, self.session_id))
            self.store.db.execute('UPDATE lifecycle_state SET last_wall=?,clock_reversal=max(clock_reversal,?) WHERE singleton=1',
                (now, int(reverse)))
        return self.status()

    def acknowledge_recovery(self):
        """Explicit controller action after reconciliation, never a startup action.

        Conflicts reported by Files.recover remain in file history; this only
        acknowledges completion of that inspection, without altering file bytes.
        """
        if self.session_id is None or self._closed:
            raise RuntimeError('Recovery acknowledgment requires an active lifecycle')
        counts = self._counts()
        if counts['prepared_changes'] or counts['running_jobs']:
            raise RuntimeError('Inspect/recover prepared changes and running jobs explicitly first')
        with self.store.db:
            self.store.db.execute('UPDATE lifecycle_state SET recovery_required=0 WHERE singleton=1')
            self.store.event('lifecycle.recovery_acknowledged', {'session_id': self.session_id})
        return self.status()

    def close(self, clean=True):
        """Record shutdown while Store is still open; idempotent for one owner."""
        if type(clean) is not bool:
            raise ValueError('clean must be a boolean')
        if self._closed:
            return self.status()
        if self.session_id is not None:
            self.heartbeat()
            with self.store.db:
                if clean:
                    self.store.db.execute("UPDATE lifecycle_sessions SET status='clean',closed_at=? WHERE id=?", (self._last_wall, self.session_id))
                    self.store.db.execute('UPDATE lifecycle_state SET crash_streak=0,blocked_until=NULL WHERE singleton=1')
                    if not self.auto_start:
                        self.store.db.execute('UPDATE lifecycle_state SET clock_reversal=0 WHERE singleton=1')
                    self.store.event('lifecycle.closed', {'session_id': self.session_id, 'clean': True})
                else:
                    # Keep running marker, so the next locked owner accounts for
                    # this unclean exit exactly once just as for a process crash.
                    self.store.event('lifecycle.closed', {'session_id': self.session_id, 'clean': False})
        self._closed = True
        return self.status()


def startup_launch(state):
    """Source-only opt-in startup entry; never spawns a replacement process."""
    from .desktop import launch
    return launch(state, auto_start=True)
