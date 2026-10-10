"""Opt-in real numerical invariants, separate from the stdlib regression suite.

All fixture seeds and examples are fixed before observing results. These tests
verify engineering contracts, not a claim that a useful language ability was
learned. Deliberately edited weights/counters are only adversarial unit fixtures.
Run: python -B -m unittest experiments.newbrain_text.test_numerical -v
"""
import base64
import copy
import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from . import source


SEED = 860221
PROTOCOL = hashlib.sha256(b'aster-text-numerical-contract-fixture-v1').hexdigest()


class DecoderNumericalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = source.load_modules()
        cls.decoder = cls.modules.decoder
        cls.np = sys.modules['numpy']
        cls.words = cls.decoder.SPECIALS + ('alpha', 'beta', 'query', 'answer', 'old', 'new')
        cls.batch = (
            {'prefix': ('<USER>', 'query', 'alpha', '<ASSISTANT>'), 'answer': ('answer', 'alpha')},
            {'prefix': ('<MEMORY>', 'old', '<QUERY>', 'beta'), 'answer': ('answer', 'beta')},
        )

    def fresh(self):
        return self.decoder.DialogueDecoder(self.words, SEED)

    def rewrite_metadata(self, raw, change):
        length = struct.unpack('<I', raw[8:12])[0]
        value = json.loads(raw[12:12 + length])
        change(value)
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')
        return raw[:8] + struct.pack('<I', len(encoded)) + encoded + raw[12 + length:]

    def test_architecture_and_fresh_counters_are_literal(self):
        model = self.fresh()
        self.assertEqual((self.decoder.EMBEDDING, self.decoder.HIDDEN), (16, 64))
        self.assertEqual((self.decoder.MAX_VOCABULARY, self.decoder.MAX_PREFIX,
                          self.decoder.MAX_RESPONSE, self.decoder.MAX_BATCH), (96, 64, 16, 8))
        self.assertEqual((model.training_updates, model.training_examples,
                          model.prefix_tokens_seen, model.target_tokens_seen), (0, 0, 0, 0))
        self.assertEqual(model.p['E'].shape, (len(self.words), 16))
        self.assertEqual(model.p['Whh'].shape, (64, 64))
        self.assertTrue(all(x.dtype == self.np.dtype('float64') for x in model.p.values()))
        self.assertEqual(model.state_bytes(PROTOCOL), self.fresh().state_bytes(PROTOCOL))

    def test_loss_full_gradients_and_inputs_do_not_mutate(self):
        model = self.fresh()
        before, rows = model.state_bytes(PROTOCOL), copy.deepcopy(self.batch)
        loss, gradients, counts = model.loss_and_gradients(self.batch)
        self.assertTrue(self.np.isfinite(loss) and loss > 0)
        self.assertEqual(set(gradients), set(self.decoder.PARAMETER_NAMES))
        for name, value in gradients.items():
            self.assertEqual(value.shape, model.p[name].shape)
            self.assertTrue(self.np.isfinite(value).all())
            self.assertGreater(float(self.np.linalg.norm(value)), 0)
            self.assertFalse(self.np.shares_memory(value, model.p[name]))
        # Prefix-only role is not a teacher-forced answer input: its gradient
        # proves that backpropagation reaches the prefix recurrence as well.
        self.assertGreater(float(self.np.linalg.norm(gradients['E'][model.index['<USER>']])), 0)
        self.assertEqual(counts, {'examples': 2, 'prefix_tokens': 8, 'target_tokens_including_eos': 6})
        self.assertEqual(model.state_bytes(PROTOCOL), before)
        self.assertEqual(self.batch, rows)

    def test_finite_difference_covers_every_parameter_role(self):
        model = self.fresh()
        before = model.state_bytes(PROTOCOL)
        _, gradients, _ = model.loss_and_gradients(self.batch)
        coordinates = {'E': (3, 3), 'Wxh': (4, 7), 'Whh': (5, 9),
                       'bh': (11,), 'Wy': (13, model.index['alpha']), 'by': (model.index['alpha'],)}
        epsilon = 1e-6
        for name, index in coordinates.items():
            with self.subTest(parameter=name):
                original = model.p[name][index]
                try:
                    model.p[name][index] = original + epsilon
                    plus = model.loss_and_gradients(self.batch)[0]
                    model.p[name][index] = original - epsilon
                    minus = model.loss_and_gradients(self.batch)[0]
                finally:
                    model.p[name][index] = original
                numerical = (plus - minus) / (2 * epsilon)
                self.assertAlmostEqual(float(gradients[name][index]), numerical, delta=2e-7)
        self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_one_actual_sgd_update_matches_full_gradient_formula(self):
        model = self.fresh()
        parameters = {name: value.copy() for name, value in model.p.items()}
        before = model.parameter_hash()
        loss, gradients, counts = model.loss_and_gradients(self.batch)
        norm = float(self.np.sqrt(sum(float(self.np.sum(g * g)) for g in gradients.values())))
        factor = min(1.0, self.decoder.CLIP_NORM / norm)
        result = model.train_step(self.batch)
        for name in parameters:
            self.np.testing.assert_array_equal(model.p[name], parameters[name] - self.decoder.LEARNING_RATE * factor * gradients[name])
        self.assertNotEqual(before, model.parameter_hash())
        self.assertEqual(result['parameter_sha256_before'], before)
        self.assertEqual(result['parameter_sha256_after'], model.parameter_hash())
        self.assertTrue(result['parameter_bytes_changed'])
        self.assertEqual(result['loss'], loss)
        self.assertEqual(result['new_exposures'], counts)
        self.assertEqual((model.training_updates, model.training_examples,
                          model.prefix_tokens_seen, model.target_tokens_seen), (1, 2, 8, 6))

    def test_gradient_clipping_commits_bounded_exact_proposal(self):
        model = self.fresh()
        parameters = {name: value.copy() for name, value in model.p.items()}
        # Controlled derivative fixture isolates the clipping branch. The
        # preceding test uses actual derivatives from the copied decoder.
        gradients = {name: self.np.full_like(value, 100.0) for name, value in model.p.items()}
        counts = {'examples': 1, 'prefix_tokens': 1, 'target_tokens_including_eos': 2}
        norm = float(self.np.sqrt(sum(float(self.np.sum(g * g)) for g in gradients.values())))
        with patch.object(model, 'loss_and_gradients', return_value=(1.0, gradients, counts)):
            result = model.train_step(self.batch)
        self.assertLess(result['clip_multiplier'], 1.0)
        self.assertEqual(result['clip_multiplier'], self.decoder.CLIP_NORM / norm)
        for name in parameters:
            self.np.testing.assert_array_equal(model.p[name], parameters[name] - .01 * result['clip_multiplier'] * gradients[name])

    def test_bad_batch_is_refused_before_any_model_mutation(self):
        bad_batches = [(), list(self.batch), self.batch * 5,
                       ({'prefix': ('query',), 'answer': ('notinvocabulary',)},),
                       ({'prefix': ('<BOS>',), 'answer': ('alpha',)},),
                       ({'prefix': ('query',) * 65, 'answer': ('alpha',)},),
                       ({'prefix': ('query',), 'answer': ('alpha',) * 16},),
                       ({'prefix': ('query',), 'answer': ('<ASSISTANT>',)},),
                       ({'prefix': ('query',), 'answer': ('alpha',), 'extra': 1},)]
        for batch in bad_batches:
            model = self.fresh()
            before = model.state_bytes(PROTOCOL)
            with self.subTest(batch=repr(batch)[:100]):
                with self.assertRaises(self.decoder.DecoderTrainingError) as caught:
                    model.train_step(batch)
                self.assertIs(caught.exception.state['model'], model)
                self.assertFalse(caught.exception.state['parameters_committed'])
                self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_overflow_and_update_ceiling_refuse_without_commit(self):
        for attribute, value in (('training_updates', self.decoder.MAX_UPDATES),
                                 ('training_examples', 2**32 - 1),
                                 ('prefix_tokens_seen', 2**32 - 1),
                                 ('target_tokens_seen', 2**32 - 1)):
            model = self.fresh()
            setattr(model, attribute, value)  # Explicit adversarial metadata fixture.
            before = model.state_bytes(PROTOCOL)
            with self.subTest(attribute=attribute):
                with self.assertRaises(self.decoder.DecoderTrainingError) as caught:
                    model.train_step(self.batch)
                self.assertFalse(caught.exception.state['parameters_committed'])
                self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_nonfinite_gradient_and_invalid_counts_never_commit(self):
        for kind in ('nan', 'shape', 'negative_count'):
            model = self.fresh()
            before = model.state_bytes(PROTOCOL)
            loss, gradients, counts = model.loss_and_gradients(self.batch)
            if kind == 'nan':
                gradients['E'][0, 0] = self.np.nan
            elif kind == 'shape':
                gradients['E'] = gradients['E'][:-1]
            else:
                counts['examples'] = -1
            with self.subTest(kind=kind), patch.object(model, 'loss_and_gradients', return_value=(loss, gradients, counts)):
                with self.assertRaises(self.decoder.DecoderTrainingError) as caught:
                    model.train_step(self.batch)
                self.assertFalse(caught.exception.state['parameters_committed'])
                self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_generation_is_answer_free_and_never_learns_or_uses_rng(self):
        model = self.fresh()
        model.train_step(self.batch)
        before = model.state_bytes(PROTOCOL)
        prefix = ('<USER>', 'unseenword', '<ASSISTANT>')
        with patch.object(model, 'train_step', side_effect=AssertionError('generation trained')), \
             patch.object(model, 'loss_and_gradients', side_effect=AssertionError('generation read a target')), \
             patch.object(self.np.random, 'default_rng', side_effect=AssertionError('generation used RNG')):
            first = model.generate(prefix)
            self.assertEqual(first, model.generate(prefix))
        self.assertEqual(first['unknown_prefix_tokens'], 1)
        self.assertEqual(first['qwen_calls_in_this_module'], 0)
        self.assertFalse(first['full_conversation_demonstrated'])
        self.assertTrue(set(first['tokens']).isdisjoint(self.decoder.SPECIALS[1:]))
        self.assertLessEqual(len(first['tokens']), self.decoder.MAX_RESPONSE)
        self.assertEqual(first['answer_text'], ' '.join(first['tokens']))
        self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_eos_and_nonterminating_response_limit_are_distinct(self):
        for selected, expected_eos in ((2, True), (7, False)):
            model = self.fresh()
            for value in model.p.values():
                value.fill(0)
            model.p['by'][selected] = 50
            # Large role logits must still be excluded from the output domain.
            model.p['by'][model.index['<ASSISTANT>']] = 100
            before = model.state_bytes(PROTOCOL)
            value = model.generate(('query',))
            self.assertEqual(value['terminated_with_eos'], expected_eos)
            self.assertEqual(value['length_limit_reached'], not expected_eos)
            self.assertEqual(value['tokens'], () if expected_eos else ('alpha',) * 16)
            self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_generation_rejects_boundary_and_extent_misuse(self):
        model = self.fresh()
        before = model.state_bytes(PROTOCOL)
        for prefix in ((), ['query'], ('query',) * 65, ('<EOS>',), ('bad token',), ('é',)):
            with self.subTest(prefix=repr(prefix)[:70]), self.assertRaises(ValueError):
                model.generate(prefix)
        self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_exact_restore_never_constructs_trains_or_initializes_rng(self):
        model = self.fresh()
        model.train_step(self.batch)
        before = model.state_bytes(PROTOCOL)
        expected = model.generate(('query', 'alpha'))
        cls = self.decoder.DialogueDecoder
        with patch.object(cls, '__init__', side_effect=AssertionError('restoration initialized')), \
             patch.object(cls, 'train_step', side_effect=AssertionError('restoration trained')), \
             patch.object(self.np.random, 'default_rng', side_effect=AssertionError('restoration seeded')):
            restored = cls.from_state_bytes(before, self.words, PROTOCOL)
            self.assertEqual(restored.state_bytes(PROTOCOL), before)
            self.assertEqual(restored.generate(('query', 'alpha')), expected)
        for name in model.p:
            self.assertFalse(self.np.shares_memory(restored.p[name], model.p[name]))
        restored.p['E'][0, 0] += .01
        self.assertEqual(model.state_bytes(PROTOCOL), before)

    def test_restore_rejects_corruption_wrong_protocol_and_wrong_vocabulary(self):
        raw = self.fresh().state_bytes(PROTOCOL)
        corrupt = bytearray(raw)
        corrupt[-1] ^= 1
        samples = [b'', raw[:-1], raw + b'\x00', b'WRONGMAG' + raw[8:], bytes(corrupt),
                   raw[:8] + struct.pack('<I', 2**32 - 1) + raw[12:]]
        for value in samples:
            with self.subTest(length=len(value)), self.assertRaises((ValueError, UnicodeError)):
                self.decoder.DialogueDecoder.from_state_bytes(value, self.words, PROTOCOL)
        with self.assertRaises(ValueError):
            self.decoder.DialogueDecoder.from_state_bytes(raw, self.words, 'f' * 64)
        with self.assertRaises(ValueError):
            self.decoder.DialogueDecoder.from_state_bytes(raw, self.words[:-1] + ('other',), PROTOCOL)

    def test_restore_rejects_noncanonical_and_forged_metadata(self):
        raw = self.fresh().state_bytes(PROTOCOL)
        edits = [('root_seed', True), ('training_updates', -1), ('training_examples', 2**32),
                 ('hidden', 32), ('pretrained', True), ('glif_integrated', True), ('extra', 1)]
        for key, value in edits:
            changed = self.rewrite_metadata(raw, lambda meta: meta.__setitem__(key, value))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.decoder.DialogueDecoder.from_state_bytes(changed, self.words, PROTOCOL)
        length = struct.unpack('<I', raw[8:12])[0]
        meta = json.loads(raw[12:12 + length])
        pretty = json.dumps(meta, indent=1).encode('ascii')
        changed = raw[:8] + struct.pack('<I', len(pretty)) + pretty + raw[12 + length:]
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.decoder.DialogueDecoder.from_state_bytes(changed, self.words, PROTOCOL)

    def test_closed_vocabulary_and_seed_bounds(self):
        for words in (list(self.words), self.words + ('alpha',), self.decoder.SPECIALS,
                      self.decoder.SPECIALS + ('UPPER',), self.decoder.SPECIALS + ('bad-token',),
                      self.decoder.SPECIALS + tuple('x' + str(i) for i in range(90))):
            with self.subTest(words=repr(words)[:60]), self.assertRaises(ValueError):
                self.decoder.DialogueDecoder(words, SEED)
        for seed in (True, -1, 2**32, 1.0):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                self.decoder.DialogueDecoder(self.words, seed)


class AsterTrainingLifecycleTests(unittest.TestCase):
    """One fixed campaign; scores are data, not engineering pass conditions."""
    @classmethod
    def setUpClass(cls):
        from . import curriculum, training
        cls.curriculum, cls.training = curriculum, training
        cls.modules = source.load_modules()
        cls.np = sys.modules['numpy']
        cls.owner = 'synthetic_contract_owner'
        cls.source_before = source.inspect_sources()
        cls.calls = []
        original_train = cls.modules.decoder.DialogueDecoder.train_step

        def traced_train(model, batch):
            cls.calls.append({'before': training.counters(model), 'batch': copy.deepcopy(batch)})
            return original_train(model, batch)

        with patch.object(source, 'load_modules', return_value=cls.modules), \
             patch.object(cls.modules.decoder.DialogueDecoder, 'train_step', traced_train), \
             patch.object(cls.modules.method_order, 'feedback_order', side_effect=AssertionError('inherited counters used')), \
             patch.object(cls.modules.probe_ledger.ProbeLedger, '__init__', side_effect=AssertionError('upstream ledger used as actual')), \
             patch.object(cls.np.random, 'default_rng', wraps=cls.np.random.default_rng) as rng:
            cls.envelope, cls.report = training.run_experiment(cls.owner)
            cls.rng_calls = rng.call_count

    def test_all_actual_updates_and_exposures_are_honest_and_heldout_excluded(self):
        self.assertEqual(len(self.calls), 208)
        self.assertEqual(self.rng_calls, 1)
        self.assertEqual(self.calls[0]['before'], {'training_updates': 0, 'training_examples': 0,
                                                 'prefix_tokens_seen': 0, 'target_tokens_seen': 0})
        self.assertEqual([self.calls[i]['before']['training_updates'] for i in (64, 112, 160)], [64, 64, 64])
        self.assertEqual(self.report['actual_total_sgd_calls'], 208)
        self.assertFalse(self.report['upstream_probe_ledger_used_for_actual_counters'])
        rows = self.curriculum.locked_curriculum()
        teaching = {tuple(row['prefix']) for split in ('old', 'new') for row in rows[split]}
        heldout = {tuple(row['prefix']) for row in rows['heldout']}
        for record in self.calls:
            self.assertEqual(len(record['batch']), 8)
            for row in record['batch']:
                self.assertIn(row['prefix'], teaching)
                self.assertNotIn(row['prefix'], heldout)

    def test_each_method_has_matched_budget_and_unbroken_actual_update_receipts(self):
        baseline = self.envelope['models']['baseline']
        self.assertEqual(baseline['counters']['training_updates'], 64)
        for method, arm in self.report['arms'].items():
            self.assertEqual(arm['start_counters'], baseline['counters'])
            self.assertEqual(arm['end_counters']['training_updates'], 112)
            self.assertEqual(arm['end_counters']['training_examples'], 896)
            self.assertEqual(len(arm['updates']), 48)
            previous = baseline['parameter_sha256']
            for offset, update in enumerate(arm['updates']):
                receipt = update['result']
                self.assertEqual(receipt['updates_completed'], 65 + offset)
                self.assertEqual(receipt['parameter_sha256_before'], previous)
                self.assertTrue(receipt['parameter_bytes_changed'])
                self.assertEqual(receipt['new_exposures']['examples'], 8)
                self.assertEqual(receipt['new_exposures']['target_tokens_including_eos'], 16)
                previous = receipt['parameter_sha256_after']
            self.assertEqual(previous, self.envelope['models'][method]['parameter_sha256'])
            for batch in range(6):
                self.assertEqual(sum(u['split'] == 'new' and u['batch'] == batch for u in arm['updates']), 6)
                self.assertEqual(sum(u['split'] == 'protected_old' and u['batch'] == batch for u in arm['updates']), 2)

    def test_actual_probe_ledger_covers_whole_current_teaching_observations(self):
        width = len(self.curriculum.WORDS)
        new_ids = {row['id'] for row in self.curriculum.locked_curriculum()['new']}
        for method, arm in self.report['arms'].items():
            self.assertEqual(len(arm['probe_ledger']), 36)
            self.assertEqual(len(arm['orders']), 6)
            for ordinal, probe in enumerate(arm['probe_ledger']):
                self.assertEqual(probe['ordinal'], ordinal)
                observation = probe['observation']
                expected = 64 + 24 * probe['cycle'] + (6 if method == 'BLOCKED' else 8) * probe['new_pass']
                self.assertEqual(observation['completed_updates'], expected)
                self.assertIn(observation['case_id'], new_ids)
                self.assertEqual(observation['generation']['parameter_sha256'], observation['parameter_sha256'])
                for key in ('first_distribution', 'after_teacher_distribution'):
                    distribution = observation[key]
                    self.assertEqual(len(distribution), width)
                    self.assertTrue(all(self.np.isfinite(p) and 0 <= p <= 1 for p in distribution))
                    self.assertAlmostEqual(sum(distribution), 1.0, places=13)
                    self.assertTrue(all(distribution[i] == 0 for i in (1, 3, 4, 5, 6)))
            for order in arm['orders']:
                self.assertFalse(order['evaluation_rows_used'])
                self.assertEqual(sorted(order['chosen_order']), list(range(6)))
                self.assertEqual(order['chosen_order'], order['priority_order'] if method == 'ERROR_PRIORITIZED' else list(range(6)))
                expected_blocks = self.modules.method_order.pass_blocks(method, order['new_pass'], tuple(order['chosen_order']))
                self.assertEqual(order['blocks'], [list(block) for block in expected_blocks])

    def test_learning_scores_are_recomputed_honestly_without_goal_pass_requirement(self):
        self.assertTrue(self.report['engineering_run_completed'])
        self.assertEqual(self.report['errors'], [])
        for arm in self.report['arms'].values():
            expected = self.training.goal_results(self.report['baseline']['evaluation'], arm['evaluation'])
            self.assertEqual(arm['goals'], expected)
            self.assertEqual(set(arm['evaluation']), {'old', 'new', 'heldout'})
            self.assertTrue(all(len(rows) == 6 for rows in arm['evaluation'].values()))
        self.assertEqual(self.report['all_scientific_goals_met'],
                         all(arm['goals']['all_scientific_goals_met'] for arm in self.report['arms'].values()))

    def test_every_saved_model_restores_exactly_without_training_or_rng(self):
        cls = self.modules.decoder.DialogueDecoder
        snapshots = self.envelope['models']
        with patch.object(cls, '__init__', side_effect=AssertionError('restored model initialized')), \
             patch.object(cls, 'train_step', side_effect=AssertionError('restore trained')), \
             patch.object(self.np.random, 'default_rng', side_effect=AssertionError('restore seeded')):
            for name, saved in snapshots.items():
                raw = base64.b64decode(saved['model_b64'], validate=True)
                restored = cls.from_state_bytes(raw, self.curriculum.WORDS, self.curriculum.protocol_hash())
                self.assertEqual(restored.state_bytes(self.curriculum.protocol_hash()), raw)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), saved['model_sha256'])
                self.assertEqual(restored.parameter_hash(), saved['parameter_sha256'])
                self.assertEqual(self.training.counters(restored), saved['counters'])
                observed = self.training.evaluate(restored)
                expected = self.report[name]['evaluation'] if name in ('initial', 'baseline') else self.report['arms'][name]['evaluation']
                self.assertEqual(observed, expected)
        self.assertEqual(source.inspect_sources(), self.source_before)

    def published(self):
        from . import persistence
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'state'
        persistence.publish_state(path, self.envelope, self.report)
        return path

    def snapshot(self, path):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()}

    def resealed(self, change):
        envelope, report = copy.deepcopy(self.envelope), copy.deepcopy(self.report)
        change(envelope, report)
        envelope['report_sha256'] = hashlib.sha256(self.curriculum.canonical(report)).hexdigest()
        return envelope, report

    def test_publication_restores_complete_state_and_owner_without_mutation(self):
        from . import persistence
        path = self.published()
        before = self.snapshot(path)
        self.assertEqual({p.name for p in path.iterdir()}, set(persistence.FILES))
        envelope, report = persistence.read_state(path, self.owner)
        self.assertEqual(envelope, self.envelope)
        self.assertEqual(report, self.report)
        self.assertEqual(self.snapshot(path), before)
        if os.name != 'nt':
            self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in path.iterdir()))
        with self.assertRaises(persistence.LabError):
            persistence.read_state(path, 'synthetic_foreign_owner')
        self.assertEqual(self.snapshot(path), before)

    def test_inspection_works_in_independent_no_site_python_without_numpy(self):
        path = self.published()
        before = self.snapshot(path)
        code = (
            "import sys,json;sys.path.insert(0,sys.argv[1]);"
            "from experiments.newbrain_text.persistence import inspect_state;"
            "value=inspect_state(sys.argv[2],sys.argv[3]);"
            "assert 'numpy' not in sys.modules;print(json.dumps(value))"
        )
        result = subprocess.run([sys.executable, '-S', '-B', '-c', code,
                                 str(Path(__file__).resolve().parents[2]), str(path), self.owner],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertFalse(value['model_executed'])
        self.assertFalse(value['numpy_required'])
        self.assertFalse(value['production_backend_enabled'])
        self.assertEqual(value['actual_total_sgd_calls'], 208)
        self.assertEqual(self.snapshot(path), before)

    def test_existing_destination_is_never_replaced(self):
        from . import persistence
        path = self.published()
        before = self.snapshot(path)
        with self.assertRaisesRegex(persistence.LabError, 'occupied'):
            persistence.publish_state(path, self.envelope, self.report)
        self.assertEqual(self.snapshot(path), before)
        self.assertEqual({p.name for p in path.parent.iterdir()}, {'state'})

    def test_raced_publication_preserves_other_writer_and_cleans_stage(self):
        from . import persistence
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'state'
        original = persistence._rename_exclusive
        def collision(stage, target):
            target.mkdir()
            (target / 'other-writer').write_bytes(b'owned by another writer')
            return original(stage, target)
        with patch.object(persistence, '_rename_exclusive', side_effect=collision):
            with self.assertRaises(persistence.LabError):
                persistence.publish_state(path, self.envelope, self.report)
        self.assertEqual((path / 'other-writer').read_bytes(), b'owned by another writer')
        self.assertEqual({p.name for p in path.parent.iterdir()}, {'state'})

    def test_failed_publication_has_no_partial_destination_or_leftover_stage(self):
        from . import persistence
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'state'
        with patch.object(persistence.os, 'fsync', side_effect=OSError('synthetic filesystem refusal')):
            with self.assertRaises(persistence.LabError):
                persistence.publish_state(path, self.envelope, self.report)
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.iterdir()), [])

    def test_symlink_hardlink_and_extra_files_are_refused(self):
        from . import persistence
        path = self.published()
        alias = path.parent / 'alias'; alias.symlink_to(path, target_is_directory=True)
        with self.assertRaises(persistence.LabError): persistence.read_state(alias, self.owner)
        (path / 'extra').write_bytes(b'not admitted')
        with self.assertRaises(persistence.LabError): persistence.read_state(path, self.owner)
        (path / 'extra').unlink()
        original = path / 'state.json'
        moved = path.parent / 'state-original.json'; original.rename(moved)
        original.symlink_to(moved)
        with self.assertRaises(persistence.LabError): persistence.read_state(path, self.owner)
        original.unlink(); os.link(moved, original)
        with self.assertRaises(persistence.LabError): persistence.read_state(path, self.owner)

    def test_corruption_does_not_get_repaired_retrained_or_written(self):
        from . import persistence
        path = self.published()
        filename = path / 'report.json'
        raw = bytearray(filename.read_bytes()); raw[len(raw) // 2] ^= 1
        filename.write_bytes(raw)
        before = self.snapshot(path)
        with patch.object(source, 'load_modules', side_effect=AssertionError('corruption caused model load')):
            with self.assertRaises(persistence.LabError): persistence.inspect_state(path, self.owner)
        self.assertEqual(self.snapshot(path), before)

    def test_resealed_bad_models_counters_feedback_and_goals_are_refused(self):
        from . import persistence
        changes = [
            lambda e, r: e.update(owner='synthetic_other'),
            lambda e, r: e['models']['initial']['counters'].update(training_updates=10720),
            lambda e, r: e['models']['baseline'].update(model_b64='aW52YWxpZA=='),
            lambda e, r: r.update(actual_total_sgd_calls=207),
            lambda e, r: r['arms']['INTERLEAVED']['probe_ledger'][0]['observation'].update(completed_updates=10720),
            lambda e, r: r['arms']['ERROR_PRIORITIZED']['orders'][0].update(evaluation_rows_used=True),
            lambda e, r: r['arms']['BLOCKED']['updates'].pop(),
            lambda e, r: r['arms']['BLOCKED']['goals'].update(old_correct_denominator=999),
        ]
        for index, change in enumerate(changes):
            envelope, report = self.resealed(change)
            with self.subTest(fixture=index), self.assertRaises(persistence.LabError):
                persistence.validate_state(envelope, report, self.owner)

    def test_state_capacity_fails_before_any_publication(self):
        from . import persistence
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'state'
        with patch.object(persistence, 'STATE_CAP', 1):
            with self.assertRaises(persistence.LabError):
                persistence.publish_state(path, self.envelope, self.report)
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.iterdir()), [])

    def test_independent_process_recheck_is_exact_readonly_and_has_no_learning_or_rng(self):
        from . import demo
        path = self.published()
        before = self.snapshot(path)
        children, original = [], demo.subprocess.Popen
        def captured(*args, **kwargs):
            child = original(*args, **kwargs); children.append(child); return child
        with patch.object(demo.subprocess, 'Popen', side_effect=captured):
            result = demo.recheck(path, self.owner)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)
        self.assertTrue(result['engineering_recheck_passed'])
        self.assertTrue(result['separate_process'])
        self.assertEqual(result['parent_pid'], os.getpid())
        self.assertNotEqual(result['child_pid'], os.getpid())
        self.assertEqual(result['models_verified'], 5)
        self.assertEqual((result['training_calls'], result['rng_calls'], result['initialization_calls']), (0, 0, 0))
        self.assertTrue(result['all_decisions_exact'])
        self.assertTrue(result['all_parameter_bytes_and_counters_exact'])
        self.assertTrue(result['published_state_unchanged'])
        self.assertGreater(result['float_comparison']['compared_float_values'], 0)
        self.assertLessEqual(result['float_comparison']['maximum_absolute_difference'], 1e-12)
        for name, model in result['models'].items():
            self.assertEqual(model['parameter_sha256'], self.envelope['models'][name]['parameter_sha256'])
            self.assertEqual(model['counters'], self.envelope['models'][name]['counters'])
            self.assertTrue(model['decisions_exact'])
            self.assertTrue(model['state_bytes_exact'])
        self.assertEqual(self.snapshot(path), before)

    def test_recheck_timeout_kills_and_reaps_actual_direct_child(self):
        from . import demo, persistence
        path = self.published()
        before, children = self.snapshot(path), []
        original = demo.subprocess.Popen
        def captured(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(demo.subprocess, 'Popen', side_effect=captured), \
             patch.object(demo, '_bounded_output', side_effect=subprocess.TimeoutExpired('fixture', 30)):
            with self.assertRaisesRegex(persistence.LabError, 'cold_recheck_timeout'):
                demo.recheck(path, self.owner)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)
        self.assertEqual(self.snapshot(path), before)

    def test_bad_timeout_and_same_process_recheck_are_refused_without_children(self):
        from . import cold_worker, demo, persistence
        for timeout in (0, -1, True, float('inf'), float('nan'), 31):
            with patch.object(demo.subprocess, 'Popen', side_effect=AssertionError('invalid timeout spawned process')):
                with self.assertRaises(persistence.LabError): demo.recheck('unused', self.owner, timeout=timeout)
        with self.assertRaisesRegex(persistence.LabError, 'separate_process'):
            cold_worker.verify('unused', self.owner, parent_pid=os.getpid())

    def test_saved_runtime_metadata_accepts_only_the_two_declared_exact_pins(self):
        from . import persistence
        # Deliberately resealed metadata fixtures exercise admission only;
        # numerical evidence belongs to the interpreter actually running this
        # suite and is never relabeled as another interpreter/platform result.
        self.assertEqual(source.PYTHON_VERSIONS, ('3.12.14', '3.14.4'))
        for version in ('3.12.14', '3.14.4'):
            envelope, report = self.resealed(lambda e, r: r['runtime'].update(python=version))
            before = self.curriculum.canonical(envelope), self.curriculum.canonical(report)
            with self.subTest(admitted_version=version):
                persistence.validate_state(envelope, report, self.owner)
                self.assertEqual(report['runtime']['python'], version)
                self.assertEqual((self.curriculum.canonical(envelope), self.curriculum.canonical(report)), before)
        for version in ('3.12.13', '3.12.15', '3.13.4', '3.14.3', '3.14.5', '3.14.4rc1', '3.15.0', True, 3.14):
            envelope, report = self.resealed(lambda e, r: r['runtime'].update(python=version))
            with self.subTest(refused_version=version), self.assertRaisesRegex(persistence.LabError, 'runtime_record_mismatch'):
                persistence.validate_state(envelope, report, self.owner)
        for version in ('3.12.14', '3.14.4'):
            for field, value in (('implementation', 'PyPy'), ('numpy', '2.3.4'), ('numpy', '2.3.6'), ('numpy', None)):
                envelope, report = self.resealed(lambda e, r: r['runtime'].update(python=version, **{field: value}))
                with self.subTest(python=version, field=field, value=value), \
                     self.assertRaisesRegex(persistence.LabError, 'runtime_record_mismatch'):
                    persistence.validate_state(envelope, report, self.owner)

    def test_strict_runtime_scope_and_integer_trace_metadata_are_enforced(self):
        from . import persistence
        changes = [
            lambda e, r: r.update(runtime=[]),
            lambda e, r: r['runtime'].update(numpy='different'),
            lambda e, r: r.update(scope='unverified claim'),
            lambda e, r: r['warmup_updates'][0].update(index=False),
            lambda e, r: r['arms']['INTERLEAVED']['orders'][0].update(cycle=0.0),
            lambda e, r: r['arms']['INTERLEAVED']['probe_ledger'][0].update(ordinal=False),
            lambda e, r: r['arms']['INTERLEAVED']['updates'][0].update(batch=0.0),
        ]
        for index, change in enumerate(changes):
            envelope, report = self.resealed(change)
            with self.subTest(fixture=index), self.assertRaises(persistence.LabError):
                persistence.validate_state(envelope, report, self.owner)


if __name__ == '__main__':
    unittest.main()
