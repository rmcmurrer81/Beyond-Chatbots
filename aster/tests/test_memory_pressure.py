"""Deterministic local counters; never allocate pressure or close applications."""
import ctypes
import io
import os
import sys
import unittest
from unittest.mock import Mock, patch

from aster.memory_pressure import (MemoryConfig, MemoryGuard, _MemoryStatusEx,
                                   _read_linux_memory, _read_windows_memory, observe_memory)


def reading(used=50):
    return {'source': 'test_fixture', 'total_bytes': 1000, 'available_bytes': 1000 - used * 10}


class MemoryPressureTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.observer = Mock(return_value=reading())
        self.guard = MemoryGuard(observer=self.observer, clock=lambda: self.now)

    def test_initial_state_is_unknown_and_closed(self):
        result = self.guard.status()
        self.assertEqual(result['state'], 'unknown')
        self.assertFalse(result['allow_new_jobs'])
        self.observer.assert_not_called()

    def test_thresholds_and_hysteresis(self):
        for used, state in [(89, 'normal'), (90, 'high'), (89, 'high'), (81, 'high'), (80, 'normal'), (0, 'normal'), (100, 'high')]:
            with self.subTest(used=used):
                result = self.guard.evaluate(reading(used))
                self.assertEqual(result['state'], state)
                self.assertEqual(result['allow_new_jobs'], state == 'normal')
        self.observer.assert_not_called()

    def test_bad_readings_fail_closed_and_preserve_high_latch(self):
        self.guard.evaluate(reading(95))
        for value in [None, {}, [], reading() | {'source': ''}, reading() | {'available_bytes': -1},
                      reading() | {'total_bytes': 0}, reading() | {'available_bytes': 1001},
                      reading() | {'total_bytes': True}, reading() | {'total_bytes': float('nan')},
                      reading() | {'total_bytes': 2 ** 64}, reading() | {'source': 'x' * 129}]:
            with self.subTest(value=value):
                result = self.guard.evaluate(value)
                self.assertEqual(result['state'], 'unknown')
                self.assertFalse(result['allow_new_jobs'])
                self.assertIsNone(result['observation'])
        self.assertEqual(self.guard.evaluate(reading(85))['state'], 'high')
        self.assertEqual(self.guard.evaluate(reading(80))['state'], 'normal')

    def test_periodic_read_and_force_before_job(self):
        self.assertTrue(self.guard.sample()['allow_new_jobs'])
        self.now += 4.9
        self.observer.return_value = reading(95)
        self.assertTrue(self.guard.sample()['allow_new_jobs'])
        self.assertEqual(self.observer.call_count, 1)
        self.assertFalse(self.guard.sample(force=True)['allow_new_jobs'])
        self.now += 5
        self.guard.sample()
        self.assertEqual(self.observer.call_count, 3)
        with self.assertRaises(ValueError):
            self.guard.sample(force='yes')

    def test_observer_failure_is_unknown_not_zero_ram(self):
        self.guard.sample()
        self.observer.side_effect = OSError('unavailable')
        result = self.guard.sample(force=True)
        self.assertEqual(result['reason'], 'observation_unavailable')
        self.assertIsNone(result['observation'])
        self.assertFalse(result['allow_new_jobs'])
        self.assertIsNone(result['newbrain_memory_bytes'])

    def test_stale_and_clock_reversal_defer_work(self):
        self.guard.sample()
        self.now += 15
        self.assertTrue(self.guard.status()['allow_new_jobs'])
        self.now += 0.1
        self.assertEqual(self.guard.status()['reason'], 'stale_observation')
        self.assertTrue(self.guard.sample(force=True)['allow_new_jobs'])
        self.now -= 10
        self.assertEqual(self.guard.sample()['reason'], 'clock_unavailable_or_reversed')
        self.assertFalse(self.guard.status()['allow_new_jobs'])
        self.assertTrue(self.guard.sample()['allow_new_jobs'])

    def test_invalid_clocks_fail_closed(self):
        for now in [float('nan'), float('inf'), -1, True, None]:
            self.now = now
            self.assertFalse(self.guard.sample()['allow_new_jobs'])
            self.assertFalse(self.guard.evaluate(reading())['allow_new_jobs'])
            self.assertFalse(self.guard.status()['allow_new_jobs'])

    def test_no_closure_or_newbrain_estimate_and_copied_result(self):
        with patch('socket.socket', side_effect=AssertionError('No network')), patch('subprocess.Popen', side_effect=AssertionError('No subprocess')):
            result = self.guard.sample()
        self.assertFalse(result['app_closure_enabled'])
        self.assertEqual(result['external_app_allowlist'], [])
        self.assertEqual(result['scope'], 'system_physical_memory')
        self.assertIsNone(result['newbrain_memory_bytes'])
        result['external_app_allowlist'].append('bad')
        result['observation']['total_bytes'] = 1
        self.assertEqual(self.guard.status()['external_app_allowlist'], [])
        self.assertEqual(self.guard.status()['observation']['total_bytes'], 1000)

    def test_validated_configuration(self):
        for values in [{'high_used_percent': True}, {'resume_used_percent': 90}, {'resume_used_percent': -1},
                       {'high_used_percent': 101}, {'high_used_percent': float('nan')},
                       {'sample_interval_seconds': 0}, {'sample_interval_seconds': 16},
                       {'max_sample_age_seconds': 301}, {'max_sample_age_seconds': float('inf')}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                MemoryConfig(**values)
        guard = MemoryGuard(MemoryConfig(high_used_percent=70, resume_used_percent=60), clock=lambda: 0)
        self.assertFalse(guard.evaluate(reading(70))['allow_new_jobs'])
        self.assertTrue(guard.evaluate(reading(60))['allow_new_jobs'])
        for config in [{}, False, 1]:
            with self.assertRaises(ValueError): MemoryGuard(config)


class NativeCounterTests(unittest.TestCase):
    def test_linux_bounded_read_and_exact_counters(self):
        with patch('builtins.open', return_value=io.BytesIO(b'MemTotal: 1000 kB\nMemFree: 1 kB\nMemAvailable: 250 kB\n')) as opened:
            result = _read_linux_memory()
        opened.assert_called_once_with('/proc/meminfo', 'rb')
        self.assertEqual(result, {'source': 'linux_proc_meminfo', 'total_bytes': 1024000, 'available_bytes': 256000})

    def test_linux_unavailable_malformed_or_oversize_is_not_estimated(self):
        for data in [b'MemTotal: 1000 kB\nMemFree: 5 kB\n', b'x' * 65537,
                     b'MemTotal: 1000 B\nMemAvailable: 25 kB',
                     b'MemTotal: 1000 kB\nMemAvailable: 25 kB\nMemAvailable: 5 kB', b'\xff']:
            with self.subTest(data=data[:60]), patch('builtins.open', return_value=io.BytesIO(data)), self.assertRaises(ValueError):
                _read_linux_memory()

    def test_windows_exact_native_structure_and_counter_reader(self):
        self.assertEqual(ctypes.sizeof(_MemoryStatusEx), 64)
        def read(pointer):
            status = ctypes.cast(pointer, ctypes.POINTER(_MemoryStatusEx)).contents
            self.assertEqual(status.dwLength, 64)
            status.ullTotalPhys, status.ullAvailPhys = 8 * 1024 ** 3, 2 * 1024 ** 3
            return 1
        dll = Mock()
        dll.GlobalMemoryStatusEx = Mock(side_effect=read)
        with patch.object(ctypes, 'WinDLL', return_value=dll, create=True) as loader:
            result = _read_windows_memory()
        loader.assert_called_once_with('kernel32', use_last_error=True)
        self.assertEqual(result['source'], 'windows_global_memory_status_ex')
        self.assertEqual(result['available_bytes'], 2 * 1024 ** 3)
        dll.GlobalMemoryStatusEx.return_value = 0
        dll.GlobalMemoryStatusEx.side_effect = None
        with patch.object(ctypes, 'WinDLL', return_value=dll, create=True), self.assertRaises(OSError):
            _read_windows_memory()

    @unittest.skipUnless(os.name == 'nt' or sys.platform.startswith('linux'), 'Native reader supports Windows/Linux')
    def test_actual_local_counter_read_no_network(self):
        with patch('socket.socket', side_effect=AssertionError('No network')):
            result = observe_memory()
        self.assertGreater(result['total_bytes'], 0)
        self.assertGreaterEqual(result['available_bytes'], 0)
        self.assertLessEqual(result['available_bytes'], result['total_bytes'])
        self.assertIn(result['source'], ('windows_global_memory_status_ex', 'linux_proc_meminfo'))

    @unittest.skipUnless(os.name == 'nt', 'Requires actual Windows GlobalMemoryStatusEx; not mocked')
    def test_native_windows_global_memory_status_ex_and_admission(self):
        with patch('socket.socket', side_effect=AssertionError('No network')):
            observation = _read_windows_memory()
            decision = MemoryGuard().sample(force=True)
        self.assertEqual(observation['source'], 'windows_global_memory_status_ex')
        self.assertGreater(observation['total_bytes'], 0)
        self.assertGreaterEqual(observation['available_bytes'], 0)
        self.assertLessEqual(observation['available_bytes'], observation['total_bytes'])
        self.assertIs(type(decision['allow_new_jobs']), bool)
        self.assertIn(decision['state'], ('normal', 'high'))
        self.assertEqual(decision['allow_new_jobs'], decision['state'] == 'normal')
        self.assertEqual(decision['observation']['source'], 'windows_global_memory_status_ex')
        self.assertFalse(decision['app_closure_enabled'])
        self.assertEqual(decision['external_app_allowlist'], [])
        self.assertIsNone(decision['newbrain_memory_bytes'])


if __name__ == '__main__':
    unittest.main()
