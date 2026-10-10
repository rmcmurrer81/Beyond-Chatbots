import hashlib
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from aster.apps import discover


class AppDiscoveryTests(unittest.TestCase):
    def test_read_only_discovery_without_record_access(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'catalog.sqlite3'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE apps(app TEXT, root TEXT, seen REAL)')
            db.execute('CREATE TABLE records(secret TEXT)')
            db.execute("INSERT INTO records VALUES ('private research')")
            for row in [('ideaforge', str(Path(root) / 'a'), time.time()), ('humanoid-researcher', str(Path(root) / 'b'), time.time()), ('untrusted', str(Path(root) / 'c'), time.time())]:
                db.execute('INSERT INTO apps VALUES (?,?,?)', row)
            db.commit(); db.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = discover(path)
            self.assertEqual(len(result['apps']), 2)
            self.assertNotIn('private research', str(result))
            self.assertEqual(result['research_access'], 'unavailable_no_aster_grant')
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(all(not app['commands'] for app in result['apps']))

    def test_absent_catalog_is_not_created(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'missing.sqlite3'
            self.assertEqual(discover(path)['status'], 'not_found')
            self.assertFalse(path.exists())

    def test_rejects_stale_and_malformed_records(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'catalog.sqlite3'
            db = sqlite3.connect(path); db.execute('CREATE TABLE apps(app,root,seen)')
            for row in [('ideaforge', '/a', 0), ('ideaforge', 'relative', time.time()), ('ideaforge', '/a', 'bad')]:
                db.execute('INSERT INTO apps VALUES (?,?,?)', row)
            db.commit(); db.close()
            self.assertEqual(discover(path)['apps'], [])

    def test_symlink_catalog_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'link'; path.symlink_to('/does/not/exist')
            with self.assertRaises(ValueError): discover(path)

    def test_malformed_database_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'catalog.sqlite3'; path.write_text('not a database')
            self.assertEqual(discover(path)['status'], 'unavailable_or_incompatible')
