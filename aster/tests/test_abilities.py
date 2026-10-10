"""Proposal mechanics only. These tests do not execute any proposed program."""
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aster.abilities import Abilities
from aster.files import Files, MAX_BYTES
from aster.storage import Store


class AbilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'state'
        self.store = Store(self.path)
        self.files = Files(self.store)
        self.abilities = Abilities(self.store, self.files)
        self.files.change('program.py', b'print("declared artifact only")\n')

    def tearDown(self):
        self.files.close()
        self.store.close()
        self.temp.cleanup()

    def create(self, supersedes=None, name='gripper'):
        return self.abilities.create(name, 'program.py', ['workspace.read'], supersedes)

    def approve(self, proposal):
        return self.abilities.review(proposal['id'], 'approved', 'Owner review only; no tests run.',
                                     proposal['source_sha256'])

    def test_snapshot_is_exact_immutable_and_not_executed(self):
        marker = Path(self.temp.name) / 'must-not-exist'
        source = f'from pathlib import Path\nPath({str(marker)!r}).touch()\n'.encode()
        self.files.change('program.py', source)
        with (patch('socket.socket', side_effect=AssertionError('No network')),
              patch('subprocess.Popen', side_effect=AssertionError('No subprocess'))):
            proposal = self.create()
            self.approve(proposal)
            selected = self.abilities.select(proposal['id'])
        self.assertFalse(marker.exists())
        self.assertEqual(proposal['source_sha256'], hashlib.sha256(source).hexdigest())
        self.assertEqual(self.abilities.source(proposal['id']), source)
        self.files.change('program.py', b'changed source')
        self.files.change('program.py', None, 'trash')
        self.assertEqual(self.abilities.source(proposal['id']), source)
        self.assertFalse(selected['execution_enabled'])
        self.assertFalse(selected['activation_enabled'])
        self.assertFalse(selected['tests_executed'])
        self.assertEqual(selected['permissions_granted'], [])
        self.assertTrue(selected['selected_for_future'])
        self.assertNotIn('source', selected)

    def test_preserves_arbitrary_bytes_without_decoding(self):
        source = b'\x00\xff\xfe\r\n'
        self.files.change('program.py', source)
        proposal = self.create()
        self.assertEqual(self.abilities.source(proposal['id']), source)
        self.assertEqual(proposal['source_bytes'], len(source))

    def test_versions_require_explicit_latest_same_name(self):
        first = self.create()
        other = self.create(name='other')
        for supersedes in (None, other['id'], 'missing'):
            with self.subTest(supersedes=supersedes), self.assertRaises(ValueError):
                self.create(supersedes)
        self.files.change('program.py', b'new source')
        second = self.create(first['id'])
        self.assertEqual(second['version'], 2)
        self.assertEqual(second['supersedes'], first['id'])
        self.assertNotEqual(second['source_sha256'], first['source_sha256'])
        with self.assertRaises(ValueError): self.create(first['id'])
        self.assertEqual(len(self.abilities.list()), 3)
        self.assertEqual(self.abilities.get(first['id'])['version'], 1)

    def test_names_and_manifests_are_bounded_declarations(self):
        for name in ('', 'Capital', '../bad', 'a' * 65, ['bad'], 'name with space'):
            with self.subTest(name=name), self.assertRaises(ValueError): self.create(name=name)
        invalid = ({}, 'network', ['network', 'network'], ['bad permission'], ['x' * 65],
                   [str(n) for n in range(17)], [None], [['unhashable']], ['secret\nvalue'])
        for manifest in invalid:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                self.abilities.create('gripper', 'program.py', manifest)
        proposal = self.abilities.create('gripper', 'program.py', ['display.ar', 'camera.read'])
        self.assertEqual(proposal['declared_permissions'], ['camera.read', 'display.ar'])
        self.assertEqual(proposal['permissions_granted'], [])
        empty = self.abilities.create('other', 'program.py', [])
        self.assertEqual(empty['declared_permissions'], [])

    def test_existing_workspace_only_and_size_limit(self):
        for path in ('missing.py', '../program.py', '/tmp/program.py', 'a/../program.py'):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                self.abilities.create('gripper', path, [])
        (self.files.root / 'large').write_bytes(b'x' * (MAX_BYTES + 1))
        with self.assertRaises(ValueError): self.abilities.create('gripper', 'large', [])
        self.assertEqual(self.abilities.list(), [])

    def test_hardlinks_are_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_bytes(b'outside')
        os.link(outside, self.files.root / 'hard')
        with self.assertRaises((OSError, ValueError)):
            self.abilities.create('gripper', 'hard', [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink/FIFO boundary; native Windows adapter tested separately')
    def test_symlinks_and_special_files_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_bytes(b'outside')
        (self.files.root / 'link').symlink_to(outside)
        os.mkfifo(self.files.root / 'fifo')
        for path in ('link', 'fifo'):
            with self.subTest(path=path), self.assertRaises((OSError, ValueError)):
                self.abilities.create('gripper', path, [])

    def test_review_is_hash_bound_append_only_and_declared(self):
        proposal = self.create()
        for digest in ('0' * 64, None, proposal['source_sha256'].upper()):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.abilities.review(proposal['id'], 'approved', 'note', digest)
        for verdict, note in (('passed', 'note'), ('approved', ''), ('approved', 'x' * 2049)):
            with self.subTest(verdict=verdict, note_size=len(note)), self.assertRaises(ValueError):
                self.abilities.review(proposal['id'], verdict, note, proposal['source_sha256'])
        self.abilities.review(proposal['id'], 'rejected', 'Owner reports failing tests.', proposal['source_sha256'])
        with self.assertRaises(ValueError): self.abilities.select(proposal['id'])
        result = self.abilities.review(proposal['id'], 'approved', 'Owner reports passing tests.', proposal['source_sha256'])
        self.assertEqual([r['verdict'] for r in result['reviews']], ['approved', 'rejected'])
        self.assertEqual(result['review_count'], 2)
        self.assertFalse(result['tests_executed'])
        self.assertEqual(result['review_notes_kind'], 'owner_declared_not_verified')
        self.assertEqual(result['reviews'][1]['note'], 'Owner reports failing tests.')

    def test_unreviewed_and_unknown_ids_cannot_select(self):
        proposal = self.create()
        with self.assertRaises(ValueError): self.abilities.select(proposal['id'])
        for operation in (self.abilities.select, self.abilities.get, self.abilities.source):
            with self.assertRaises(ValueError): operation('missing')
        with self.assertRaises(ValueError): self.abilities.review('missing', 'approved', 'note', 'x')
        self.assertEqual(self.abilities.get(proposal['id'])['status'], 'proposed')

    def test_rollback_restores_prior_selections_without_rewriting_source(self):
        first = self.create()
        self.approve(first)
        self.abilities.select(first['id'])
        with self.assertRaises(ValueError): self.abilities.rollback('gripper')
        with self.assertRaises(ValueError): self.abilities.select(first['id'])
        second = self.create(first['id'])
        third = self.create(second['id'])
        for proposal in (second, third):
            self.approve(proposal)
            self.abilities.select(proposal['id'])
        self.assertEqual(self.abilities.rollback('gripper')['id'], second['id'])
        self.assertEqual(self.abilities.rollback('gripper')['id'], first['id'])
        with self.assertRaises(ValueError): self.abilities.rollback('gripper')
        with self.assertRaises(ValueError): self.abilities.rollback('unknown')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM ability_selections').fetchone()[0], 5)
        self.assertEqual(len(self.abilities.list()), 3)
        self.assertFalse(self.abilities.get(third['id'])['selected_for_future'])

    def test_latest_rejection_blocks_selection_and_rollback(self):
        first = self.create()
        second = self.create(first['id'])
        for proposal in (first, second):
            self.approve(proposal)
            self.abilities.select(proposal['id'])
        rejected = self.abilities.review(second['id'], 'rejected', 'New issue found.', second['source_sha256'])
        self.assertTrue(rejected['selection_recorded'])
        self.assertFalse(rejected['selected_for_future'])
        self.assertEqual(rejected['status'], 'rejected')
        self.abilities.review(first['id'], 'rejected', 'Earlier version also unsafe.', first['source_sha256'])
        with self.assertRaises(ValueError): self.abilities.rollback('gripper')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM ability_selections').fetchone()[0], 2)

    def test_sql_update_and_delete_cannot_rewrite_histories(self):
        proposal = self.create()
        self.approve(proposal)
        self.abilities.select(proposal['id'])
        for table in ('ability_proposals', 'ability_reviews', 'ability_selections'):
            for statement in (f'UPDATE {table} SET at=0', f'DELETE FROM {table}'):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                    with self.store.db: self.store.db.execute(statement)
        self.assertEqual(self.abilities.get(proposal['id'])['review_count'], 1)

    def test_failed_transaction_preserves_previous_artifact_and_records_no_secrets(self):
        first = self.create()
        event = self.store.event
        def fail_proposal(kind, payload):
            if kind == 'ability.proposed': raise sqlite3.OperationalError('simulated private failure details')
            return event(kind, payload)
        with patch.object(self.store, 'event', side_effect=fail_proposal):
            with self.assertRaises(sqlite3.OperationalError): self.create(first['id'])
        self.assertEqual([p['id'] for p in self.abilities.list()], [first['id']])
        last = self.store.rows('events')[0]
        self.assertEqual(last['kind'], 'ability.failed')
        self.assertNotIn('private', last['payload'])
        self.assertNotIn('program.py', last['payload'])
        self.assertEqual(self.create(first['id'])['version'], 2)

    def test_database_full_fails_without_pruning(self):
        first = self.create()
        self.files.change('program.py', b'x' * MAX_BYTES)
        self.store.db.execute('VACUUM')  # Remove free pages before the artificial cap.
        count = self.store.db.execute('PRAGMA page_count').fetchone()[0]
        self.store.db.execute(f'PRAGMA max_page_count={count}').fetchone()
        with self.assertRaises(sqlite3.OperationalError): self.create(first['id'])
        self.assertEqual([p['id'] for p in self.abilities.list()], [first['id']])
        self.assertEqual(self.abilities.source(first['id']), b'print("declared artifact only")\n')

    def test_restart_preserves_identity_source_review_and_selection(self):
        identity = self.store.identity()
        proposal = self.create()
        self.approve(proposal)
        self.abilities.select(proposal['id'])
        self.files.close()
        self.store.close()
        self.store = Store(self.path)
        self.files = Files(self.store)
        self.abilities = Abilities(self.store, self.files)
        result = self.abilities.get(proposal['id'])
        self.assertEqual(self.store.identity(), identity)
        self.assertTrue(result['selected_for_future'])
        self.assertEqual(result['review_count'], 1)
        self.assertFalse(result['execution_enabled'])


if __name__ == '__main__':
    unittest.main()
