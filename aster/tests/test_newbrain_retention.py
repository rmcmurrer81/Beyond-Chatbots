"""Dependency-free protocol boundaries for the opt-in retention study."""
import unittest
from experiments.newbrain_retention.protocol import (curriculum, protocol_hash, schedule, specification)


class RetentionContractTests(unittest.TestCase):
    def test_protocol_returns_independent_values(self):
        before = protocol_hash()
        spec = specification()
        spec['seeds'].append(999)
        spec['curriculum']['old'][0]['answer'] = ['wrong']
        self.assertEqual(before, protocol_hash())
        self.assertEqual(len(before), 64)

    def test_no_seed_replacement_or_private_vocabulary(self):
        spec = specification()
        self.assertEqual(spec['seeds'], [11, 29, 47, 71, 101])
        self.assertEqual(spec['ewc_strength'], 10.0)
        self.assertEqual(spec['actual_campaign_sgd_calls'], 4800)
        self.assertEqual(len(curriculum()['vocabulary']), 16)

    def test_primary_exposure_match_is_exact(self):
        self.assertEqual(schedule('REPLAY'), schedule('REPLAY_EWC'))
        self.assertEqual(len(schedule('NEW_ONLY')), 192)
        self.assertTrue(all(split == 'new' for split, _ in schedule('NEW_ONLY')))
        with self.assertRaises(ValueError):
            schedule('UNREQUESTED')


if __name__ == '__main__':
    unittest.main()
