"""Integration checks of actual copied components, not simulated dialogue."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from .component import ComponentSource, DEFAULT_ROOT, PIN, VALUE_PATH, canonical
from .fixtures import OWNER, event, consequence, metadata


class AdapterCases(unittest.TestCase):
    def setUp(self):
        self.source = ComponentSource()

    def test_fresh_aster_value_instance_has_no_imported_history(self):
        a, b = self.source.fresh(OWNER), self.source.fresh('other-synthetic-owner')
        self.assertEqual(a.model.weights, (0.0,) * 8)
        self.assertEqual(a.model.receipts, [])
        a.model.learn(event(), consequence())
        self.assertEqual(b.model.weights, (0.0,) * 8)
        self.assertEqual(b.model.receipts, [])

    def test_source_manifest_and_blob_hashes_verified(self):
        self.assertEqual(len(self.source.sources), 8)
        self.assertEqual(hashlib.sha256(self.source.sources[VALUE_PATH]).hexdigest(),
                         self.source.observer.LEARNER_SOURCE_SHA256)

    def test_tampered_source_refused_before_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(DEFAULT_ROOT / PIN, root / PIN)
            (root / PIN / VALUE_PATH).write_bytes(b'raise RuntimeError("must not execute")\n')
            with self.assertRaisesRegex(ValueError, 'Source bytes mismatch'):
                ComponentSource(snapshot_root=root)

    def test_tampered_manifest_and_unknown_pin_refused(self):
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            ComponentSource(pin='future-unreviewed')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(DEFAULT_ROOT / PIN, root / PIN)
            (root / PIN / 'manifest.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'manifest integrity'):
                ComponentSource(snapshot_root=root)

    def test_no_input_prediction_is_zero_and_does_not_learn(self):
        s = self.source.fresh(OWNER)
        before = s.snapshot()
        self.assertEqual(s.model.predict(event())['expected_value'], 0.0)
        self.assertEqual(before, s.snapshot())

    def test_actual_observed_gradient_and_correction(self):
        s = self.source.fresh(OWNER)
        observer = s.observer(experiment_id='aster-component-engineering', arm_id='numeric-value')
        first = observer.observe_learn(metadata(), event(), consequence())
        old_prediction = s.model.predict(event())['expected_value']
        second = observer.observe_learn(metadata(corrected=True), event(), consequence(corrected=True))
        self.assertGreater(old_prediction, 0)
        self.assertLess(s.model.predict(event())['expected_value'], old_prediction)
        self.assertEqual(s.model.receipts[0], first)
        self.assertEqual(second['supersedes'], 'outcome-1')
        self.assertEqual(observer.compact_record('attempt-2')['data']['after']['update_count'], 2)

    def test_state_roundtrip_cross_owner_and_corruption(self):
        s = self.source.fresh(OWNER)
        s.model.learn(event(), consequence())
        raw = s.snapshot()
        self.assertEqual(self.source.restore(raw, owner_id=OWNER).snapshot(), raw)
        with self.assertRaisesRegex(ValueError, 'Cross-owner'):
            self.source.restore(raw, owner_id='someone-else')
        data = json.loads(raw)
        data['state_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.source.restore(canonical(data), owner_id=OWNER)

    def test_unknown_upgrade_is_rejected_without_changing_rollback_bytes(self):
        s = self.source.fresh(OWNER)
        s.model.learn(event(), consequence())
        checkpoint = s.snapshot()
        future = json.loads(checkpoint)
        future['pin'] = 'future-unreviewed'
        with self.assertRaisesRegex(ValueError, 'Cross-pin'):
            self.source.restore(canonical(future), owner_id=OWNER)
        self.assertEqual(s.snapshot(), checkpoint)
        replacement = ComponentSource().restore(checkpoint, owner_id=OWNER)
        self.assertEqual(replacement.snapshot(), checkpoint)

    def test_schema_migration_is_never_silent(self):
        s = self.source.fresh(OWNER)
        data = json.loads(s.snapshot())
        data['schema'] = 'newbrain-future-unknown'
        with self.assertRaisesRegex(ValueError, 'migration required'):
            self.source.restore(canonical(data), owner_id=OWNER)

    def test_snapshot_capacity_can_precede_update_limit_and_old_checkpoint_survives(self):
        s = self.source.fresh(OWNER)
        previous = s.snapshot()
        for index in range(32):
            c = consequence()
            c['consequence_id'] = 'bounded-outcome-' + str(index)
            c['time_index'] = index + 1
            s.model.learn(event(), c)
            try:
                current = s.snapshot()
            except self.source.value.SnapshotRefused as error:
                self.assertGreater(len(error.complete_raw), 32768)
                self.assertLess(index + 1, 32)
                old = self.source.restore(previous, owner_id=OWNER)
                self.assertEqual(len(old.model.receipts), index)
                self.assertEqual(len(s.model.receipts), index + 1)
                self.assertEqual(old.snapshot(), previous)
                break
            previous = current
        else:
            self.fail('Expected upstream complete-snapshot capacity refusal on this fixture')

    def test_fresh_module_instance_does_not_alias_prior_state(self):
        before = dict(sys.modules)
        other = ComponentSource()
        self.assertIsNot(other.value, self.source.value)
        self.assertIs(other.observer.value, other.value)
        self.assertIs(self.source.observer.value, self.source.value)
        self.assertIs(sys.modules.get('learned_value'), before.get('learned_value'))
        self.assertIs(sys.modules.get('event_observer'), before.get('event_observer'))

    def test_genuine_process_exit_and_cold_restore_preserves_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / 'synthetic-state.json')
            command = [sys.executable, '-B', '-m', 'experiments.newbrain_adapter.cold_worker']
            first = subprocess.run(command + ['train', target], capture_output=True, text=True,
                                   timeout=20, cwd=DEFAULT_ROOT.parents[1], check=True)
            second = subprocess.run(command + ['restore', target], capture_output=True, text=True,
                                    timeout=20, cwd=DEFAULT_ROOT.parents[1], check=True)
            self.assertEqual(first.stderr, '')
            self.assertEqual(second.stderr, '')
            trained, restored = json.loads(first.stdout), json.loads(second.stdout)
            self.assertEqual(trained, restored)
            self.assertEqual(restored['receipts'], 2)

    def test_aster_identity_memory_and_backend_remain_separate(self):
        from aster.storage import Store
        from aster import backend
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'aster-synthetic')
            try:
                store.remember('Fictional cube is blue.', source='synthetic-fixture')
                identity, memories = store.identity(), store.rows('memories')
                s = self.source.fresh(identity['id'])
                s.model.learn(event(identity['id']), consequence(identity['id']))
                self.source.restore(s.snapshot(), owner_id=identity['id'])
                with self.assertRaises(NotImplementedError):
                    s.respond({'prompt': 'hello'})
                self.assertFalse(backend.status()['available'])
                self.assertFalse(backend.status()['autonomous_execution'])
                self.assertIsNone(backend.status()['fallback'])
                self.assertEqual(store.identity(), identity)
                self.assertEqual(store.rows('memories'), memories)
            finally:
                store.close()
            reopened = Store(Path(tmp) / 'aster-synthetic')
            try:
                self.assertEqual(reopened.identity(), identity)
                self.assertEqual(reopened.rows('memories'), memories)
            finally:
                reopened.close()


def upstream_suite():
    source = ComponentSource()
    suite = unittest.TestSuite()
    for path, name in [('research/value-engineering053/test_learned_value.py', 'upstream_value'),
                       ('research/value-event-engineering054/test_event_observer.py', 'upstream_observer')]:
        module = source.load_module(path, name, {'learned_value': source.value,
                                                'event_observer': source.observer})
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    return suite
