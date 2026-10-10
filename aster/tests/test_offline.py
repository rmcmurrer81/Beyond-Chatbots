"""Current local tools work with socket creation explicitly denied.

This is an offline software-mechanics fixture, not a NewBrain/speech test.
"""
import tempfile
import unittest
from unittest.mock import patch
from aster.dashboard import Dashboard
from aster.backend import status


class OfflineTests(unittest.TestCase):
    def test_network_denied_local_work_and_pending_requests_survive_restart(self):
        with tempfile.TemporaryDirectory() as state:
            with patch('socket.socket', side_effect=AssertionError('Network forbidden in offline test')), \
                 patch('socket.create_connection', side_effect=AssertionError('Network forbidden in offline test')):
                panel = Dashboard(state)
                identity = panel.snapshot()['identity']
                try:
                    prompt = panel.dispatch('save_request', prompt='Continue my local project offline.')
                    ticket = panel.dispatch('prepare_write', path='notes/offline.txt', content='Offline work')
                    panel.dispatch('confirm', ticket=ticket['ticket'])
                    job = panel.dispatch('queue', job_action='memory.append',
                                         job_args={'text': 'Saved without Internet', 'source': 'user'})
                    panel.dispatch('control', job_id=job['id'], command='pause')
                    self.assertFalse(status()['available'])
                    self.assertIsNone(status()['fallback'])
                    self.assertFalse(panel.dispatch('voice')['live_synthesis'])
                finally:
                    panel.close()
                panel = Dashboard(state)
                try:
                    self.assertEqual(panel.snapshot()['identity'], identity)
                    self.assertEqual(panel.dispatch('read', path='notes/offline.txt')['text'], 'Offline work')
                    self.assertEqual(panel.history('prompts', prompt['request_id'])['status'], 'waiting_for_newbrain')
                    self.assertEqual(panel.history('jobs', job['id'])['status'], 'paused')
                    panel.dispatch('control', job_id=job['id'], command='resume')
                    ticket = panel.dispatch('prepare_run')
                    result = panel.dispatch('confirm', ticket=ticket['ticket'])
                    self.assertEqual(result['status'], 'completed')
                    self.assertEqual(panel.store.rows('memories')[0]['body'], 'Saved without Internet')
                    self.assertEqual(panel.dispatch('prepare_run')['status'], 'idle')
                    self.assertEqual(len(panel.store.rows('prompts')), 1)
                finally:
                    panel.close()


if __name__ == '__main__':
    unittest.main()
