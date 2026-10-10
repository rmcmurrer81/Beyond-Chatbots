import tempfile
import unittest
from aster.storage import Store
from aster.files import Files
from aster.jobs import Jobs
from aster.memory_pressure import MemoryGuard
from aster.resources import MIB


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.files = Files(self.store)
        self.observation = {'source': 'fixture', 'total_bytes': 4096*MIB, 'available_bytes': 2048*MIB}
        self.jobs = Jobs(self.store, self.files, MemoryGuard(observer=lambda: dict(self.observation)))

    def tearDown(self):
        self.files.close(); self.store.close(); self.tmp.cleanup()

    def submit(self, **kw):
        return self.jobs.submit('file.write', {'path': 'result.txt', 'text': 'bounded'}, **kw)

    def test_explicit_ram_request_defers_and_runs_once_after_recovery(self):
        job = self.submit(ram_mib=512)
        self.observation['available_bytes'] = 700*MIB
        self.assertEqual(self.jobs.run_one()['status'], 'deferred_resource_budget')
        self.assertIsNone(self.files.snapshot('result.txt'))
        self.observation['available_bytes'] = 800*MIB
        self.assertEqual(self.jobs.run_one()['status'], 'completed')
        self.assertEqual(self.jobs.run_one()['status'], 'idle')
        self.assertEqual(len(self.store.rows('changes')), 1)
        self.assertEqual(self.jobs.resources.status()['jobs'][0]['id'], job)

    def test_gpu_unknown_and_invalid_requests_never_enter_queue(self):
        for kw in ({'gpu_mib': 1}, {'gpu_mib': False}, {'ram_mib': True}, {'ram_mib': 0},
                   {'ram_mib': 513}, {'ram_mib': float('nan')}, {'ram_mib': '4'}):
            with self.subTest(kw=kw), self.assertRaises(ValueError): self.submit(**kw)
        self.assertFalse(self.store.rows('jobs'))

    def test_policy_limits_queue_and_paused_cancel_frees_slot(self):
        self.jobs.resources.configure(max_pending=1)
        first = self.submit()
        self.jobs.control(first, 'pause')
        with self.assertRaisesRegex(ValueError, 'queue limit'): self.submit()
        self.jobs.control(first, 'cancel')
        self.submit()
        self.assertEqual(self.jobs.resources.status()['job_counts']['cancelled'], 1)

    def test_lowered_policy_applies_to_old_request(self):
        self.submit(ram_mib=512)
        self.jobs.resources.configure(max_ram_mib=128)
        result = self.jobs.run_one()
        self.assertEqual(result['status'], 'deferred_resource_budget')
        self.assertEqual(result['resources']['state'], 'request_exceeds_current_policy')

    def test_unknown_observation_fails_closed_for_explicit_request(self):
        job = self.submit(ram_mib=8)
        self.assertFalse(self.jobs.resources.admission(job, {})['allowed'])
        self.observation.clear()
        self.assertEqual(self.jobs.run_one()['status'], 'deferred_memory_pressure')

    def test_legacy_requests_still_use_existing_pressure_guard(self):
        self.submit()
        self.observation['available_bytes'] = 4*MIB
        self.assertEqual(self.jobs.run_one()['status'], 'deferred_memory_pressure')
        self.observation['available_bytes'] = 2048*MIB
        self.assertEqual(self.jobs.run_one()['status'], 'completed')

    def test_configuration_persists_and_never_claims_hard_limits(self):
        identity = self.store.identity()
        self.jobs.resources.configure(64, 128, 10)
        self.files.close(); self.store.close()
        self.store = Store(self.tmp.name); self.files = Files(self.store)
        self.jobs = Jobs(self.store, self.files)
        result = self.jobs.resources.status()
        self.assertEqual(self.store.identity(), identity)
        self.assertEqual(result['policy']['max_ram_mib'], 64)
        self.assertFalse(result['gpu']['execution_enabled'])
        self.assertFalse(result['hard_ram_limit'])
        self.assertFalse(result['hard_timeout'])
        self.assertTrue(result['on_demand_only'])

    def test_config_validation_is_atomic(self):
        before = self.jobs.resources.policy()
        for kw in ({'max_pending': 0}, {'max_pending': True}, {'reserve_ram_mib': -1},
                   {'max_ram_mib': 4097}, {'reserve_ram_mib': float('inf')}):
            with self.subTest(kw=kw), self.assertRaises(ValueError): self.jobs.resources.configure(**kw)
            self.assertEqual(self.jobs.resources.policy(), before)


if __name__ == '__main__': unittest.main()
