import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aster.private_memory import PrivateMemory
from aster.storage import Store


class PrivateMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state'
        self.store = Store(self.path)
        self.memory = PrivateMemory(self.store)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_legacy_records_ids_identity_and_store_append_preserved(self):
        identity = self.store.identity()
        legacy = self.store.remember('legacy fact', 'legacy source')
        self.assertEqual(self.memory.get(legacy)['category'], 'history')
        self.assertEqual(self.memory.search('legacy')[0]['id'], legacy)
        added = self.memory.remember('A decision', category='decision')
        self.assertEqual(len(self.store.rows('memories')), 2)
        self.assertEqual(len(self.store.db.execute('PRAGMA table_info(memories)').fetchall()), 5)
        self.store.close()
        self.store = Store(self.path)
        self.memory = PrivateMemory(self.store)
        self.assertEqual(self.store.identity(), identity)
        self.assertEqual(self.memory.get(added)['body'], 'A decision')
        self.assertEqual(self.memory.get(legacy)['source'], 'legacy source')
        self.store.remember('works after restart')
        self.assertEqual(len(self.memory.search()), 3)

    def test_literal_search_category_source_and_unicode(self):
        first = self.memory.remember('Use metric units, 100% sure, Straße', 'preference', 'user:Alice',
                                     source_date='2026-10-05')
        self.memory.remember('Metric bolt chosen', 'decision', 'meeting')
        self.memory.remember('Underscore _ is literal', 'history')
        self.assertEqual(self.memory.search('METRIC', category='preference')[0]['id'], first)
        self.assertEqual(len(self.memory.search('metric')), 2)
        self.assertEqual(self.memory.search('STRASSE')[0]['id'], first)
        self.assertEqual(len(self.memory.search('%')), 1)
        self.assertEqual(len(self.memory.search('_')), 1)
        self.assertEqual(self.memory.search("' OR 1=1 --"), [])
        self.assertEqual(len(self.memory.search(source='meeting')), 1)
        self.assertEqual(self.memory.get(first)['source_date'], '2026-10-05')

    def test_corrections_append_and_inspect_complete_retained_chain(self):
        first = self.memory.remember('Blue', 'preference', 'user', source_date='2026-09-01')
        second = self.memory.correct(first, 'Green', source='correction')
        third = self.memory.correct(second, 'Red', source_date='2026-10-05T22:00:00Z')
        self.assertEqual([r['id'] for r in self.memory.search()], [third])
        self.assertEqual([r['id'] for r in self.memory.chain(second)], [first, second, third])
        self.assertEqual(self.memory.get(first)['body'], 'Blue')
        self.assertEqual(self.memory.get(second)['category'], 'preference')
        self.assertIsNone(self.memory.get(second)['source_date'])
        self.assertEqual(self.memory.get(third)['supersedes'], second)
        self.assertEqual(len(self.memory.search(include_superseded=True)), 3)
        with self.assertRaises(ValueError):
            self.memory.correct(first, 'fork rejected')

    def test_hide_delete_restore_are_recoverable_and_persisted(self):
        memory_id = self.memory.remember('retained sensitive-free fixture', 'decision', 'source')
        self.assertEqual(self.memory.hide(memory_id)['state'], 'hidden')
        self.assertEqual(self.memory.search(), [])
        self.assertEqual(self.memory.search(include_hidden=True)[0]['id'], memory_id)
        deleted = self.memory.delete(memory_id)
        self.assertEqual(deleted['state'], 'deleted')
        self.assertTrue(deleted['retained_data'])
        self.assertEqual(self.memory.search(include_hidden=True), [])
        self.assertEqual(self.memory.search(include_deleted=True)[0]['id'], memory_id)
        self.assertEqual(self.store.rows('memories')[0]['body'], 'retained sensitive-free fixture')
        self.store.close(); self.store = Store(self.path); self.memory = PrivateMemory(self.store)
        self.assertEqual(self.memory.search(), [])
        self.assertEqual(self.memory.restore(memory_id)['state'], 'active')
        self.assertEqual(self.memory.search()[0]['id'], memory_id)
        self.assertEqual(self.memory.get(memory_id)['category'], 'decision')
        self.assertEqual(self.memory.get(memory_id)['source'], 'source')

    def test_hidden_deleted_correction_does_not_revive_old_fact(self):
        old = self.memory.remember('Old value')
        new = self.memory.correct(old, 'New value')
        self.memory.delete(new)
        self.assertEqual(self.memory.search(), [])
        self.assertEqual(self.memory.search(include_superseded=True)[0]['id'], old)
        with self.assertRaises(ValueError):
            self.memory.correct(new, 'Must restore first')
        self.memory.restore(new)
        self.assertEqual(self.memory.search()[0]['id'], new)

    def test_legacy_hidden_metadata_created_without_text_rewrite(self):
        memory_id = self.store.remember('old', 'external')
        before = dict(self.store.db.execute('SELECT * FROM memories WHERE id=?', (memory_id,)).fetchone())
        self.memory.hide(memory_id); self.memory.restore(memory_id)
        after = dict(self.store.db.execute('SELECT * FROM memories WHERE id=?', (memory_id,)).fetchone())
        self.assertEqual(before, after)

    def test_repeated_controls_are_idempotent(self):
        memory_id = self.memory.remember('remember')
        first = self.memory.delete(memory_id)
        count = self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        second = self.memory.delete(memory_id)
        self.assertEqual(first, second)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM events').fetchone()[0], count)

    def test_validation_has_no_partial_append(self):
        invalid = [dict(body=''), dict(body='x', category='fact'), dict(body='x', source=''),
                   dict(body='x', source_date='yesterday'), dict(body='x', source_date='2026-10-05T22:00:00'),
                   dict(body='x', source_date='2026-02-30'), dict(body='x', supersedes='missing'),
                   dict(body='x' * 32769)]
        for kwargs in invalid:
            with self.subTest(kwargs=str(kwargs)[:100]), self.assertRaises(ValueError):
                self.memory.remember(**kwargs)
        self.assertEqual(self.store.rows('memories'), [])
        for kwargs in [dict(query=5), dict(query='x' * 1025), dict(category='unknown'),
                       dict(limit=0), dict(limit=True), dict(limit=101), dict(include_hidden=1),
                       dict(include_deleted='yes'), dict(source='')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.memory.search(**kwargs)
        for action in (self.memory.get, self.memory.hide, self.memory.delete, self.memory.restore, self.memory.chain):
            with self.assertRaises(ValueError):
                action('missing')

    def test_append_and_visibility_events_commit_atomically(self):
        with patch.object(self.store, 'event', side_effect=RuntimeError('simulated transaction failure')):
            with self.assertRaises(RuntimeError):
                self.memory.remember('should roll back')
        self.assertEqual(self.memory.search(), [])
        memory_id = self.memory.remember('stays active')
        with patch.object(self.store, 'event', side_effect=RuntimeError('simulated transaction failure')):
            with self.assertRaises(RuntimeError):
                self.memory.delete(memory_id)
        self.assertEqual(self.memory.get(memory_id)['state'], 'active')

    def test_legacy_branch_and_corruption_are_explicit(self):
        first = self.store.remember('first')
        left = self.store.remember('left', supersedes=first)
        right = self.store.remember('right', supersedes=first)
        self.assertEqual({r['id'] for r in self.memory.chain(left)}, {first, left, right})
        with self.store.db:
            self.store.db.execute('UPDATE memories SET supersedes=? WHERE id=?', (right, first))
        with self.assertRaisesRegex(ValueError, 'cyclic'):
            self.memory.chain(first)

    def test_no_network_and_isolation(self):
        other = Store(Path(self.temp.name) / 'other')
        try:
            with patch('socket.socket', side_effect=AssertionError('No network')):
                self.memory.remember('local-only')
                self.assertEqual(len(self.memory.search('local')), 1)
                self.assertEqual(PrivateMemory(other).search(), [])
            status = self.memory.status()
            self.assertFalse(status['semantic_search'])
            self.assertFalse(status['model_learning'])
            self.assertFalse(status['purge_supported'])
            self.assertFalse(status['encrypted'])
        finally:
            other.close()

    def test_exact_keyword_contract_and_chain_bound(self):
        first = self.memory.remember('one')
        second = self.memory.correct(id_=first, body='two')
        self.assertEqual(self.memory.get(id_=second)['body'], 'two')
        self.assertEqual(len(self.memory.chain(id_=second)), 2)
        self.memory.hide(id_=second)
        self.memory.delete(id_=second)
        self.memory.restore(id_=second)
        with patch('aster.private_memory.MAX_CHAIN', 1):
            with self.assertRaisesRegex(ValueError, 'inspection limit'):
                self.memory.chain(id_=second)

    def test_event_does_not_duplicate_memory_body(self):
        self.memory.remember('fixture body not copied into event', source='fixture source')
        events = json.dumps(self.store.rows('events'))
        self.assertNotIn('fixture body not copied into event', events)
        self.assertNotIn('fixture source', events)
