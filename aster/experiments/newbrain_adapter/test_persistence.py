"""Synthetic transactional custody, exact observation restore, and pin migration."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .component import ComponentSource, DEFAULT_ROOT, LEGACY_PIN, PIN, OBSERVER_PATH, canonical
from .fixtures import OWNER, event, consequence, metadata
from . import persistence


def reseal(data):
    data['history_sha256'] = hashlib.sha256(canonical(data['observers'])).hexdigest()
    return canonical(data)


class PersistenceCases(unittest.TestCase):
    def setUp(self):
        self.source = ComponentSource()
        self.session = self.source.fresh(OWNER)

    def observer(self, session=None):
        return (session or self.session).observer(experiment_id='aster-component-engineering', arm_id='numeric-value')

    def first(self):
        obs = self.observer()
        obs.observe_learn(metadata(), event(), consequence())
        return obs

    def test_safe_learning_capacity_never_changes_live_model_or_checkpoint(self):
        for index in range(32):
            c = consequence(); c.update(consequence_id='outcome-' + str(index), time_index=index + 1)
            previous = self.session.checkpoint()
            model = self.session.model
            try:
                self.session.learn(event(), c)
            except self.source.value.SnapshotRefused as error:
                self.assertGreater(len(error.complete_raw), 32768)
                self.assertLess(index, 31)
                self.assertIs(self.session.model, model)
                self.assertEqual(self.session.checkpoint(), previous)
                self.assertEqual(self.source.restore(previous, owner_id=OWNER).checkpoint(), previous)
                break
        else:
            self.fail('Fixture must reach complete learner snapshot capacity')

    def test_observed_capacity_refusal_preserves_live_history_and_disk(self):
        index = 0
        while True:
            c = consequence(); c.update(consequence_id='warmup-' + str(index), time_index=index + 1)
            try:
                self.session.learn(event(), c)
            except self.source.value.SnapshotRefused:
                break
            index += 1
        obs = self.observer()
        before = self.session.checkpoint()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'
            self.session.save(path)
            with self.assertRaises(self.source.value.SnapshotRefused):
                obs.observe_learn(metadata(), event(), c, checkpoint_path=path)
            self.assertEqual(self.session.checkpoint(), before)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(obs.history(), [])

    def test_envelope_capacity_refuses_all_mutation(self):
        obs = self.observer(); before = self.session.checkpoint()
        with patch.object(persistence, 'MAX_CHECKPOINT', len(before)):
            with self.assertRaisesRegex(ValueError, 'checkpoint exceeds budget'):
                obs.observe_learn(metadata(), event(), consequence())
        self.assertEqual(self.session.checkpoint(), before)
        self.assertEqual(obs.history(), [])

    def test_exact_upstream_summary_and_independent_returned_objects(self):
        obs = self.first()
        raw = self.source.observer.ValueEventObserver(self.source.value.ValueLearner(OWNER),
            experiment_id='aster-component-engineering', arm_id='numeric-value')
        raw.observe_learn(metadata(), event(), consequence())
        self.assertEqual(obs.compact_record('attempt-1'), raw.compact_record('attempt-1'))
        before = self.session.checkpoint()
        history = obs.history(); history[0]['inputs']['event'] = '{}'
        summary = obs.compact_record('attempt-1'); summary['data']['after']['coefficients'][0] = 10
        self.assertEqual(self.session.checkpoint(), before)
        with self.assertRaises(self.source.observer.ObservationRefused):
            obs.compact_record('attempt-1', maximum_bytes=1)
        self.assertEqual(self.session.checkpoint(), before)

    def test_restore_exact_history_then_correction_with_source_chain(self):
        obs = self.first(); original = obs.history(); before = self.session.checkpoint()
        restored = self.source.restore(before, owner_id=OWNER)
        self.assertEqual(restored.checkpoint(), before)
        cold = self.observer(restored)
        self.assertEqual(cold.history(), original)
        cold.observe_learn(metadata(corrected=True), event(), consequence(corrected=True))
        records = cold.history()
        self.assertEqual(records[0], original[0])
        self.assertEqual(records[1]['summary']['metadata']['supersedes_attempt_id'], 'attempt-1')
        self.assertEqual(restored.model.receipts[1]['supersedes'], 'outcome-1')
        self.assertEqual(self.session.checkpoint(), before)
        self.assertEqual(self.source.restore(restored.checkpoint(), owner_id=OWNER).checkpoint(), restored.checkpoint())

    def test_restore_never_invokes_learning(self):
        self.first(); raw = self.session.checkpoint()
        with patch.object(self.source.value.ValueLearner, 'learn', side_effect=AssertionError('No replay exposure')):
            restored = self.source.restore(raw, owner_id=OWNER)
        self.assertEqual(restored.checkpoint(), raw)

    def test_failed_attempt_survives_restore_without_learning(self):
        obs = self.observer(); original_model = self.session.snapshot()
        bad = consequence('foreign-owner')
        with self.assertRaisesRegex(ValueError, 'cross-owner'):
            obs.observe_learn(metadata(), event(), bad)
        self.assertEqual(self.session.snapshot(), original_model)
        h = obs.history()[0]
        self.assertEqual(h['disposition'], 'ROLLED_BACK')
        self.assertEqual(h['summary']['status'], 'FAILED_OR_HELD')
        self.assertEqual(h['before_raw'], h['after_raw'])
        self.assertEqual(h['inputs']['consequence'], canonical(bad).decode('ascii'))
        restored = self.source.restore(self.session.checkpoint(), owner_id=OWNER)
        cold = self.observer(restored)
        self.assertEqual(cold.history(), obs.history())
        m = metadata(); m.update(attempt_id='attempt-2', sequence=2)
        cold.observe_learn(m, event(), consequence())
        self.assertEqual(len(restored.model.receipts), 1)
        self.assertEqual(cold.history()[0], h)

    def test_unknown_after_preserved_while_staged_learning_rolls_back(self):
        obs = self.observer(); before = self.session.snapshot()
        capture = self.source.observer.ValueEventObserver._capture
        calls = []
        def broken_after(instance):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('synthetic after-state unavailable')
            return capture(instance)
        with patch.object(self.source.observer.ValueEventObserver, '_capture', broken_after):
            with self.assertRaisesRegex(RuntimeError, 'after-state unavailable'):
                obs.observe_learn(metadata(), event(), consequence())
        self.assertEqual(self.session.snapshot(), before)
        h = obs.history()[0]
        self.assertEqual(h['summary']['after_status'], 'UNKNOWN')
        self.assertIsNone(h['after_raw']); self.assertIsNone(h['summary']['after'])
        self.assertTrue(h['summary']['operation_returned'])
        self.assertIsNotNone(h['result_raw'])
        self.assertEqual(h['disposition'], 'ROLLED_BACK')
        restored = self.source.restore(self.session.checkpoint(), owner_id=OWNER)
        self.assertEqual(self.observer(restored).history(), obs.history())
        self.assertEqual(restored.model.receipts, [])
        m = metadata(corrected=True)
        with self.assertRaisesRegex(ValueError, 'Correction links'):
            self.observer(restored).observe_learn(m, event(), consequence(corrected=True))
        self.assertEqual(restored.model.receipts, [])

    def test_primary_and_later_failures_and_unknown_before_roundtrip(self):
        for mode in ('before', 'after'):
            with self.subTest(mode=mode):
                s = self.source.fresh(OWNER); obs = self.observer(s)
                capture = self.source.observer.ValueEventObserver._capture; calls = []
                def broken(instance):
                    calls.append(1)
                    if mode == 'before' or len(calls) == 2:
                        raise RuntimeError('synthetic unavailable ' + mode)
                    return capture(instance)
                with patch.object(self.source.observer.ValueEventObserver, '_capture', broken):
                    with self.assertRaises((RuntimeError, ValueError)):
                        obs.observe_learn(metadata(), event(), consequence('other-owner'))
                h = obs.history()[0]
                self.assertEqual(h['summary']['after_status'], 'UNKNOWN')
                self.assertEqual(len(h['later']), 1 if mode == 'after' else 0)
                self.assertEqual(self.source.restore(s.checkpoint(), owner_id=OWNER).checkpoint(), s.checkpoint())
                self.assertEqual(s.model.receipts, [])

    def test_duplicate_attempt_and_observer_capacity_do_not_evict(self):
        obs = self.first(); before = self.session.checkpoint()
        with self.assertRaises(self.source.observer.ObservationRefused):
            obs.observe_learn(metadata(), event(), consequence())
        self.assertEqual(self.session.checkpoint(), before)
        for n in range(2, 5):
            m = metadata(); m.update(attempt_id='attempt-' + str(n), sequence=n)
            c = consequence(); c.update(consequence_id='outcome-' + str(n), time_index=n)
            obs.observe_learn(m, event(), c)
        before = self.session.checkpoint()
        m = metadata(); m.update(attempt_id='attempt-5', sequence=5)
        with self.assertRaises(self.source.observer.ObservationRefused):
            obs.observe_learn(m, event(), consequence())
        self.assertEqual(self.session.checkpoint(), before)
        for n in range(3):
            self.session.observer(experiment_id='other-' + str(n), arm_id='value')
        before = self.session.checkpoint()
        with self.assertRaisesRegex(ValueError, 'observer capacity'):
            self.session.observer(experiment_id='too-many', arm_id='value')
        self.assertEqual(self.session.checkpoint(), before)

    def test_observer_owner_isolation_and_unknown_schema_or_pin(self):
        self.first(); raw = self.session.checkpoint()
        with self.assertRaisesRegex(ValueError, 'Cross-owner'):
            self.source.restore(raw, owner_id='other-owner')
        for field, value in [('schema', 'unknown-v3'), ('pin', LEGACY_PIN),
                             ('component_sha256', '0'*64), ('observer_sha256', '0'*64),
                             ('state_sha256', '0'*64), ('history_sha256', '0'*64)]:
            with self.subTest(field=field):
                data = json.loads(raw); data[field] = value
                with self.assertRaises(ValueError):
                    self.source.restore(canonical(data), owner_id=OWNER)
        self.assertEqual(self.session.checkpoint(), raw)

    def test_tampered_observer_records_refused_even_with_recomputed_history_hash(self):
        obs = self.first(); obs.observe_learn(metadata(corrected=True), event(), consequence(corrected=True))
        raw = self.session.checkpoint()
        mutations = [
            lambda p: p['summary'].__setitem__('owner_id', 'other-owner'),
            lambda p: p['summary'].__setitem__('operation_returned', False),
            lambda p: p['summary'].__setitem__('after_status', 'UNKNOWN'),
            lambda p: p['summary'].__setitem__('parameter_delta', [0.0]*8),
            lambda p: p['summary'].__setitem__('loaded_source_authentication_qualified', True),
            lambda p: p.__setitem__('after_raw', p['before_raw']),
            lambda p: p.__setitem__('disposition', 'ROLLED_BACK'),
            lambda p: p.__setitem__('ordinal', 0),
            lambda p: p['summary']['metadata'].__setitem__('supersedes_attempt_id', 'missing'),
            lambda p: p['inputs'].__setitem__('event', canonical(event('other-owner')).decode('ascii')),
            lambda p: p.__setitem__('unknown', 'no-open-fields'),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                data = json.loads(raw); mutate(data['observers'][0]['records'][1])
                with self.assertRaises(ValueError):
                    self.source.restore(reseal(data), owner_id=OWNER)
        self.assertEqual(self.session.checkpoint(), raw)

    def test_failed_fsync_or_replace_keeps_model_history_and_existing_file(self):
        obs = self.first()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'; before = self.session.save(path)
            for failure in ('fsync', 'replace'):
                with self.subTest(failure=failure):
                    with patch.object(persistence.os, failure, side_effect=OSError('injected ' + failure)):
                        with self.assertRaisesRegex(OSError, 'injected'):
                            obs.observe_learn(metadata(corrected=True), event(), consequence(corrected=True), checkpoint_path=path)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(self.session.checkpoint(), before)
                    self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['checkpoint.json'])
            obs.observe_learn(metadata(corrected=True), event(), consequence(corrected=True), checkpoint_path=path)
            self.assertEqual(path.read_bytes(), self.session.checkpoint())
            self.assertEqual(len(self.source.restore(path.read_bytes(), owner_id=OWNER).model.receipts), 2)

    def test_failed_write_without_old_file_publishes_nothing(self):
        obs = self.observer(); before = self.session.checkpoint()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'
            with patch.object(persistence.os, 'fsync', side_effect=OSError('injected write failure')):
                with self.assertRaises(OSError):
                    obs.observe_learn(metadata(), event(), consequence(), checkpoint_path=path)
            self.assertFalse(path.exists()); self.assertEqual(list(Path(tmp).iterdir()), [])
            self.assertEqual(self.session.checkpoint(), before)

    def test_partial_and_short_writes_leave_exact_live_state_and_disk(self):
        obs = self.observer()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'; before = self.session.save(path)
            original_fdopen = persistence.os.fdopen
            for kind in ('partial-error', 'short-write'):
                class BrokenWriter:
                    def __init__(self, handle):
                        self.handle = handle
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        return self.handle.__exit__(*args)
                    def write(self, raw):
                        self.handle.write(raw[:10])
                        if kind == 'partial-error':
                            raise OSError('injected partial write')
                        return 10
                with self.subTest(kind=kind), patch.object(persistence.os, 'fdopen',
                        side_effect=lambda *a, **k: BrokenWriter(original_fdopen(*a, **k))):
                    with self.assertRaises((OSError, ValueError)):
                        obs.observe_learn(metadata(), event(), consequence(), checkpoint_path=path)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.session.checkpoint(), before)
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['checkpoint.json'])

    def test_unobserved_learning_write_failure_and_success_are_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'; before = self.session.save(path)
            with patch.object(persistence.os, 'replace', side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    self.session.learn(event(), consequence(), checkpoint_path=path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.session.checkpoint(), before)
            self.session.learn(event(), consequence(), checkpoint_path=path)
            self.assertEqual(path.read_bytes(), self.session.checkpoint())
            self.assertEqual(len(self.source.restore(path.read_bytes(), owner_id=OWNER).model.receipts), 1)

    def test_interrupt_never_publishes_staged_learning_or_failure_history(self):
        obs = self.observer(); before = self.session.checkpoint()
        capture = self.source.observer.ValueEventObserver._capture; calls = []
        def interrupted(instance):
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt('synthetic interrupt after staged update')
            return capture(instance)
        with patch.object(self.source.observer.ValueEventObserver, '_capture', interrupted):
            with self.assertRaises(KeyboardInterrupt):
                obs.observe_learn(metadata(), event(), consequence())
        self.assertEqual(self.session.checkpoint(), before)
        self.assertEqual(obs.history(), [])

    def test_failed_attempt_file_write_failure_does_not_publish_failure_history(self):
        obs = self.observer()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'; before = self.session.save(path)
            with patch.object(persistence.os, 'replace', side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    obs.observe_learn(metadata(), event(), consequence('other-owner'), checkpoint_path=path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.session.checkpoint(), before)
            with self.assertRaisesRegex(ValueError, 'cross-owner'):
                obs.observe_learn(metadata(), event(), consequence('other-owner'), checkpoint_path=path)
            self.assertEqual(path.read_bytes(), self.session.checkpoint())
            self.assertEqual(len(self.observer(self.source.restore(path.read_bytes(), owner_id=OWNER)).history()), 1)

    def test_foreign_and_corrupt_destination_refuse_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'
            foreign = self.source.fresh('other-owner').checkpoint(); path.write_bytes(foreign)
            with self.assertRaisesRegex(ValueError, 'Cross-owner'):
                self.session.save(path)
            self.assertEqual(path.read_bytes(), foreign)
            path.write_bytes(b'{bad-json')
            with self.assertRaises(ValueError):
                self.session.save(path)
            self.assertEqual(path.read_bytes(), b'{bad-json')

    def test_symlink_destination_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'checkpoint.json'; path.write_bytes(b'{bad-json')
            link = Path(tmp) / 'link.json'
            try:
                link.symlink_to(path)
            except (OSError, NotImplementedError) as error:
                self.skipTest('Symlink creation unavailable on this platform: ' + str(error))
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                self.session.save(link)
            self.assertEqual(path.read_bytes(), b'{bad-json')

    def test_bounded_malformed_input_and_noncanonical_checkpoint_refuse(self):
        obs = self.observer(); before = self.session.checkpoint()
        for bad in (object(), {'attempt_id': 'a', 'payload': 'x' * 5000}, {'nan': float('nan')}):
            with self.assertRaises(ValueError):
                obs.observe_learn(bad, event(), consequence())
        self.assertEqual(self.session.checkpoint(), before)
        for bad in (before + b' ', b'[]', b'null', b'{}', b'{"schema":1,"schema":2}', b'x'*(persistence.MAX_CHECKPOINT+1)):
            with self.assertRaises(ValueError):
                self.source.restore(bad, owner_id=OWNER)

    def test_explicit_old_new_migration_preserves_both_schemas_and_rollback(self):
        old = ComponentSource(pin=LEGACY_PIN)
        a = old.fresh(OWNER); self.observer(a).observe_learn(metadata(), event(), consequence())
        for original in (a.snapshot(), a.checkpoint()):
            with self.subTest(schema=json.loads(original)['schema']):
                migrated = self.source.migrate(original, owner_id=OWNER, from_pin=LEGACY_PIN)
                updated = migrated.snapshot() if json.loads(original)['schema'].endswith('.v1') else migrated.checkpoint()
                expected = json.loads(original); expected['pin'] = PIN
                self.assertEqual(updated, canonical(expected))
                reverted = old.migrate(updated, owner_id=OWNER, from_pin=PIN)
                self.assertEqual(reverted.snapshot() if json.loads(original)['schema'].endswith('.v1') else reverted.checkpoint(), original)
                self.assertEqual(old.restore(original, owner_id=OWNER).snapshot(), a.snapshot())
        self.assertEqual(self.source.sources, old.sources)
        b = self.source.fresh(OWNER); self.observer(b).observe_learn(metadata(), event(), consequence())
        self.assertEqual(a.model.snapshot(), b.model.snapshot())
        self.assertEqual(self.observer(a).history(), self.observer(b).history())

    def test_migration_rejects_unknown_route_owner_and_source_mismatch(self):
        old = ComponentSource(pin=LEGACY_PIN); raw = old.fresh(OWNER).checkpoint()
        with self.assertRaisesRegex(ValueError, 'Unreviewed migration'):
            self.source.migrate(raw, owner_id=OWNER, from_pin='unknown')
        with self.assertRaisesRegex(ValueError, 'Cross-owner'):
            self.source.migrate(raw, owner_id='other-owner', from_pin=LEGACY_PIN)
        self.source.sources[OBSERVER_PATH] += b'\n'
        with self.assertRaisesRegex(ValueError, 'byte-identical'):
            self.source.migrate(raw, owner_id=OWNER, from_pin=LEGACY_PIN)
        self.assertEqual(old.restore(raw, owner_id=OWNER).checkpoint(), raw)

    def worker(self, mode, path, *args, expected=0):
        command = [sys.executable, '-B', '-m', 'experiments.newbrain_adapter.cold_worker', mode, str(path), *args]
        result = subprocess.run(command, cwd=DEFAULT_ROOT.parents[1], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout) if result.stdout else None

    def test_cold_process_restore_migrate_correct_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            trained = self.worker('train-observed', path, LEGACY_PIN)
            original = path.read_bytes()
            restored = self.worker('restore-observed', path, LEGACY_PIN)
            self.assertEqual(trained, restored)
            migrated_path = Path(tmp) / 'migrated.json'
            migrated_path.write_bytes(self.source.migrate(original, owner_id=OWNER, from_pin=LEGACY_PIN).checkpoint())
            corrected = self.worker('correct-observed', migrated_path, PIN)
            self.assertEqual(corrected['first_record_sha256'], trained['first_record_sha256'])
            self.assertEqual(corrected['receipts'], 2)
            self.assertEqual(corrected, self.worker('restore-observed', migrated_path, PIN))
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(trained, self.worker('restore-observed', path, LEGACY_PIN))

    def test_process_exit_before_or_after_replace_always_leaves_complete_checkpoint(self):
        for phase, code in [('crash-before-replace', 66), ('crash-after-replace', 67)]:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'state.json'
                self.worker('train-observed', path, PIN)
                before = path.read_bytes()
                self.worker(phase, path, PIN, expected=code)
                restored = self.worker('restore-observed', path, PIN)
                self.assertEqual(restored['receipts'], 1 if phase == 'crash-before-replace' else 2)
                if phase == 'crash-before-replace':
                    self.assertEqual(path.read_bytes(), before)
                    self.assertEqual(len(list(Path(tmp).glob('.*.pending'))), 1)
                else:
                    self.assertNotEqual(path.read_bytes(), before)
                    self.assertEqual(len(list(Path(tmp).glob('.*.pending'))), 0)
