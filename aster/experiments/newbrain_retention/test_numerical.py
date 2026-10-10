"""Mechanical fixtures use seed 90210; never tune or rerun the study for a gain."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from experiments.newbrain_text.source import load_modules
from .protocol import WORDS, curriculum, row_batch, protocol_hash, schedule, specification
from .protection import (Protection, estimate_importance, protected_copy, checkpoint_bytes, restore_bytes)
from .study import transition, evaluate


class RetentionNumericalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        cls.np = np
        cls.decoder = load_modules().decoder
        cls.rows = curriculum()['old']

    def fresh(self):
        return self.decoder.DialogueDecoder(WORDS, 90210)

    def test_fisher_is_mean_of_squared_individual_gradients(self):
        model = self.fresh()
        before = model.state_bytes(protocol_hash())
        observed = estimate_importance(model, self.rows)
        individual = [model.loss_and_gradients(row_batch(row, 1))[1] for row in self.rows]
        for name in observed:
            expected = self.np.stack([g[name] for g in individual])
            self.np.testing.assert_allclose(observed[name], self.np.mean(expected ** 2, axis=0), rtol=1e-14, atol=1e-15)
        self.assertGreater(float(self.np.linalg.norm(observed['by'] - self.np.mean(self.np.stack([g['by'] for g in individual]), axis=0) ** 2)), 0)
        self.assertEqual(before, model.state_bytes(protocol_hash()))

    def test_penalty_gradient_finite_differences_all_parameter_roles(self):
        model = self.fresh()
        fisher = {name: self.np.full_like(value, 0.25) for name, value in model.p.items()}
        protection = Protection(model.p, fisher, 10.0)
        for value in model.p.values():
            value += 0.02
        penalty, gradients = protection.penalty(model.p)
        self.assertGreater(penalty, 0)
        for name, value in model.p.items():
            index = tuple(0 for _ in value.shape)
            original = value[index]
            value[index] = original + 1e-6
            plus = protection.penalty(model.p)[0]
            value[index] = original - 1e-6
            minus = protection.penalty(model.p)[0]
            value[index] = original
            self.assertAlmostEqual(float(gradients[name][index]), (plus - minus) / 2e-6, delta=1e-8)

    def test_joint_data_plus_penalty_gradients_finite_differences(self):
        base = self.fresh()
        fisher = {name: self.np.full_like(value, 0.25) for name, value in base.p.items()}
        model = protected_copy(base, fisher, 10.0)
        for value in model.p.values():
            value += 0.01
        batch = row_batch(self.rows[0], 1)
        _, gradients, _ = model.loss_and_gradients(batch)
        coordinates = {'E': (3, 3), 'Wxh': (4, 7), 'Whh': (5, 9), 'bh': (11,), 'Wy': (13, 14), 'by': (14,)}
        for name, index in coordinates.items():
            original = model.p[name][index]
            model.p[name][index] = original + 1e-6
            plus = model.loss_and_gradients(batch)[0]
            model.p[name][index] = original - 1e-6
            minus = model.loss_and_gradients(batch)[0]
            model.p[name][index] = original
            self.assertAlmostEqual(float(gradients[name][index]), (plus - minus) / 2e-6, delta=2e-7)

    def test_zero_penalty_preserves_upstream_sgd_exactly(self):
        base = self.fresh()
        protected = protected_copy(base, estimate_importance(base, self.rows), 0.0)
        for row in self.rows:
            self.assertEqual(base.train_step(row_batch(row)), protected.train_step(row_batch(row)))
            self.assertEqual(base.state_bytes(protocol_hash()), protected.state_bytes(protocol_hash()))

    def test_anchor_zero_and_nonzero_after_update(self):
        base = self.fresh()
        protected = protected_copy(base, estimate_importance(base, self.rows), 10.0)
        self.assertEqual(protected.protection.penalty(protected.p)[0], 0.0)
        protected.train_step(row_batch(self.rows[0]))
        self.assertGreater(protected.protection.penalty(protected.p)[0], 0.0)
        with self.assertRaises(ValueError):
            protected.protection.anchor['by'][0] = 5

    def test_upstream_clips_joint_gradient_before_update(self):
        base = self.fresh()
        protected = protected_copy(base, {name: self.np.ones_like(value) for name, value in base.p.items()}, 10.0)
        for value in protected.p.values():
            value += 0.2
        batch = row_batch(self.rows[0], 1)
        _, gradients, _ = protected.loss_and_gradients(batch)
        norm = self.np.sqrt(sum(float((g * g).sum()) for g in gradients.values()))
        self.assertGreater(norm, 5)
        expected = {name: value - 0.01 * 5 / norm * gradients[name] for name, value in protected.p.items()}
        receipt = protected.train_step(batch)
        self.assertAlmostEqual(receipt['clip_multiplier'], 5 / norm)
        for name in expected:
            self.np.testing.assert_allclose(protected.p[name], expected[name], rtol=1e-14, atol=1e-15)

    def test_restore_preserves_configuration_and_next_update(self):
        base = self.fresh()
        model = protected_copy(base, estimate_importance(base, self.rows), 10.0)
        model.train_step(row_batch(self.rows[1]))
        raw = checkpoint_bytes(model)
        with patch.object(self.np.random, 'default_rng', side_effect=AssertionError('RNG forbidden')):
            restored = restore_bytes(raw)
        self.assertEqual(checkpoint_bytes(restored), raw)
        model.train_step(row_batch(self.rows[2]))
        restored.train_step(row_batch(self.rows[2]))
        self.assertEqual(checkpoint_bytes(restored), checkpoint_bytes(model))

    def test_corruption_wrong_owner_protocol_and_shapes_refused(self):
        model = protected_copy(self.fresh(), {name: self.np.ones_like(value) for name, value in self.fresh().p.items()}, 10.0)
        raw = checkpoint_bytes(model)
        with self.assertRaises(ValueError):
            restore_bytes(raw[:-1])
        from .protocol import canonical
        for field, value in [('owner', 'synthetic_foreign'), ('protocol_sha256', '0' * 64)]:
            envelope = json.loads(raw)
            envelope['payload'][field] = value
            envelope['sha256'] = hashlib.sha256(canonical(envelope['payload'])).hexdigest()
            with self.assertRaises(ValueError):
                restore_bytes(canonical(envelope))
        envelope = json.loads(raw)
        envelope['payload']['protection']['anchor']['by'] = [0.0]
        envelope['sha256'] = hashlib.sha256(canonical(envelope['payload'])).hexdigest()
        with self.assertRaises(ValueError):
            restore_bytes(canonical(envelope))

    def test_bad_importance_or_strength_refused(self):
        model = self.fresh()
        for bad in (-1.0, float('nan'), float('inf')):
            importance = {name: self.np.full_like(value, bad) for name, value in model.p.items()}
            with self.assertRaises(ValueError):
                Protection(model.p, importance, 10.0)
        with self.assertRaises(ValueError):
            Protection(model.p, {name: self.np.ones_like(value) for name, value in model.p.items()}, float('nan'))

    def test_evaluation_no_mutation_and_new_acquisition_distinct(self):
        model = self.fresh()
        before = checkpoint_bytes(model)
        evaluate(model, curriculum()['new'])
        self.assertEqual(before, checkpoint_bytes(model))
        result = transition({'observations': [{'id': 'a', 'correct': True}]}, {'observations': [{'id': 'a', 'correct': True}]})
        self.assertEqual(result['retained'], 1)
        self.assertEqual(result['newly_correct'], [])
        result = transition({'observations': [{'id': 'a', 'correct': False}]}, {'observations': [{'id': 'a', 'correct': False}]})
        self.assertIsNone(result['retention_fraction'])

    def test_fixed_budget_match_and_no_heldout_training(self):
        self.assertEqual(schedule('REPLAY'), schedule('REPLAY_EWC'))
        self.assertEqual(sum(split == 'old' for split, _ in schedule('REPLAY')), 48)
        self.assertEqual(sum(split == 'new' for split, _ in schedule('REPLAY')), 144)
        self.assertEqual(specification()['actual_campaign_sgd_calls'], 4800)
        data = curriculum()
        train = {tuple(row['prefix']) for split in ('old', 'new') for row in data[split]}
        heldout = {tuple(row['prefix']) for row in data['heldout']}
        self.assertFalse(train & heldout)
        self.assertEqual(len(heldout), 8)


if __name__ == '__main__':
    unittest.main()
