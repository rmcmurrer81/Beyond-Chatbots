"""Bounded, local physical-memory observations and a self-throttling decision.

There is no process enumeration, application close/kill, model estimate, network,
watchdog, or background thread here. Unknown/stale measurements defer new jobs.
The owning controller calls sample periodically and immediately before job start.
"""
from copy import deepcopy
import ctypes
from dataclasses import dataclass
import math
import os
import sys
import time


@dataclass(frozen=True)
class MemoryConfig:
    high_used_percent: float = 90.0
    resume_used_percent: float = 80.0
    sample_interval_seconds: float = 5.0
    max_sample_age_seconds: float = 15.0

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('Memory thresholds and intervals must be finite numbers')
        if not 0 <= self.resume_used_percent < self.high_used_percent <= 100:
            raise ValueError('Require 0 <= resume_used_percent < high_used_percent <= 100')
        if not 0.1 <= self.sample_interval_seconds <= self.max_sample_age_seconds <= 300:
            raise ValueError('Require 0.1 <= sample interval <= maximum sample age <= 300 seconds')


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_uint32), ('dwMemoryLoad', ctypes.c_uint32),
                ('ullTotalPhys', ctypes.c_uint64), ('ullAvailPhys', ctypes.c_uint64),
                ('ullTotalPageFile', ctypes.c_uint64), ('ullAvailPageFile', ctypes.c_uint64),
                ('ullTotalVirtual', ctypes.c_uint64), ('ullAvailVirtual', ctypes.c_uint64),
                ('ullAvailExtendedVirtual', ctypes.c_uint64)]


def _read_windows_memory():
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    read = kernel32.GlobalMemoryStatusEx
    read.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
    read.restype = ctypes.c_int
    if not read(ctypes.byref(status)):
        raise OSError('GlobalMemoryStatusEx failed')
    return {'source': 'windows_global_memory_status_ex',
            'total_bytes': int(status.ullTotalPhys), 'available_bytes': int(status.ullAvailPhys)}


def _read_linux_memory():
    # No fallback to MemFree: it would count reclaimable cache as unavailable.
    with open('/proc/meminfo', 'rb') as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise ValueError('Memory observation exceeded its 64 KiB read bound')
    fields = {}
    for line in data.decode('ascii').splitlines():
        key, separator, value = line.partition(':')
        if separator and key in ('MemTotal', 'MemAvailable'):
            pieces = value.split()
            if key in fields or len(pieces) != 2 or pieces[1] != 'kB' or not pieces[0].isdigit():
                raise ValueError('Malformed or duplicate physical-memory counter')
            fields[key] = int(pieces[0]) * 1024
    if set(fields) != {'MemTotal', 'MemAvailable'}:
        raise ValueError('Required physical-memory counters are unavailable')
    return {'source': 'linux_proc_meminfo', 'total_bytes': fields['MemTotal'],
            'available_bytes': fields['MemAvailable']}


def observe_memory():
    """Read system physical-memory counters, never a NewBrain/process estimate."""
    if os.name == 'nt':
        return _read_windows_memory()
    if sys.platform.startswith('linux'):
        return _read_linux_memory()
    raise OSError('Physical-memory observer is unavailable on this platform')


class MemoryGuard:
    """Stateful high/resume hysteresis; unknown observations always fail closed.

    observer() returns {source: str, total_bytes: int, available_bytes: int}.
    evaluate(observation) uses that same shape for deterministic controller tests.
    sample(force=True) obtains a fresh reading immediately before a new job.
    """
    def __init__(self, config=None, *, observer=None, clock=None):
        self.config = config if config is not None else MemoryConfig()
        if not isinstance(self.config, MemoryConfig):
            raise ValueError('Expected MemoryConfig')
        self._observer = observer if observer is not None else observe_memory
        self._clock = clock if clock is not None else time.monotonic
        if not callable(self._observer) or not callable(self._clock):
            raise ValueError('Observer and clock must be callable')
        self._high = False
        self._sampled_at = self._last_clock = None
        self._observation = None
        self._state, self._reason = 'unknown', 'not_sampled'

    def _now(self):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise ValueError('Invalid monotonic clock')
        if self._last_clock is not None and now < self._last_clock:
            self._last_clock = now
            self._sampled_at = None
            raise ValueError('Monotonic clock moved backwards')
        self._last_clock = now
        return now

    def _unknown(self, reason):
        self._state, self._reason = 'unknown', reason
        return self._result()

    def _result(self):
        return {'state': self._state, 'reason': self._reason,
                'allow_new_jobs': self._state == 'normal',
                'observation': deepcopy(self._observation),
                'high_used_percent': self.config.high_used_percent,
                'resume_used_percent': self.config.resume_used_percent,
                'sample_interval_seconds': self.config.sample_interval_seconds,
                'max_sample_age_seconds': self.config.max_sample_age_seconds,
                'scope': 'system_physical_memory', 'action': 'defer_new_jobs' if self._state != 'normal' else 'none',
                'app_closure_enabled': False, 'external_app_allowlist': [],
                'newbrain_memory_bytes': None}

    def _evaluate(self, observation, now):
        self._sampled_at = now
        if not isinstance(observation, dict):
            self._observation = None
            return self._unknown('invalid_observation')
        total, available = observation.get('total_bytes'), observation.get('available_bytes')
        source = observation.get('source')
        if (type(total) is not int or type(available) is not int or
                not 0 < total <= (2 ** 64 - 1) or not 0 <= available <= total or
                type(source) is not str or not source or len(source) > 128):
            self._observation = None
            return self._unknown('invalid_observation')
        used = 100.0 * (total - available) / total
        self._observation = {'source': source, 'total_bytes': total, 'available_bytes': available,
                             'used_percent': used}
        if used >= self.config.high_used_percent:
            self._high = True
        elif self._high and used <= self.config.resume_used_percent:
            self._high = False
        self._state = 'high' if self._high else 'normal'
        self._reason = 'high_memory_pressure' if self._high else 'memory_within_threshold'
        return self._result()

    def evaluate(self, observation):
        """Evaluate one caller-provided observation; performs no OS read."""
        try:
            now = self._now()
        except Exception:
            return self._unknown('clock_unavailable_or_reversed')
        return self._evaluate(observation, now)

    def sample(self, force=False):
        """Measure if due; force a fresh reading before admitting a new job."""
        if type(force) is not bool:
            raise ValueError('force must be a boolean')
        try:
            now = self._now()
        except Exception:
            return self._unknown('clock_unavailable_or_reversed')
        if not force and self._sampled_at is not None and now - self._sampled_at < self.config.sample_interval_seconds:
            return self._result()
        try:
            observation = self._observer()
        except Exception:
            self._sampled_at, self._observation = now, None
            return self._unknown('observation_unavailable')
        return self._evaluate(observation, now)

    def status(self):
        """Read the decision without sampling; stale or reversed time defers work."""
        try:
            now = self._now()
        except Exception:
            return self._unknown('clock_unavailable_or_reversed')
        if self._sampled_at is not None and now - self._sampled_at > self.config.max_sample_age_seconds:
            return self._unknown('stale_observation')
        return self._result()
