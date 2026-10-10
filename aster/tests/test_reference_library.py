import hashlib
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aster.files import Files, MAX_BYTES
from aster.reference_library import ReferenceLibrary, MAX_PASSAGE_CHARS
from aster.storage import Store


class ReferenceLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'state')
        self.files = Files(self.store)
        self.library = ReferenceLibrary(self.store, self.files)
        self.files.change('refs/notes.md', b'Heading\nFirst observation\nAster uses metric units.\nNext observation\nEnd\n')
        self.files.change('other/unapproved.txt', b'Never index this without its own approval')

    def tearDown(self):
        self.library.close(); self.files.close(); self.store.close(); self.temp.cleanup()

    def approve(self, folder='refs'):
        return self.library.approve_folder(folder)['id']

    def test_approval_required_exact_scope_and_explicit_file_list(self):
        self.assertEqual(self.library.search('metric'), [])
        with self.assertRaises(ValueError):
            self.library.index_files('missing', ['refs/notes.md'])
        scope = self.approve()
        for paths in [['other/unapproved.txt'], ['refs2/file.txt'], ['refs/../other/unapproved.txt'],
                      ['/etc/passwd'], 'refs/notes.md', [], ['refs/notes.md'] * 33,
                      ['refs/notes.md', 'refs/notes.md']]:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.library.index_files(scope, paths)
        self.assertEqual(self.library.sources(), [])
        self.assertEqual(self.library.index_files(scope, ['refs/notes.md'])[0]['path'], 'refs/notes.md')
        self.assertEqual(self.library.search('own approval'), [])

    def test_exact_passage_lines_source_hash_and_citation(self):
        scope = self.approve()
        indexed = self.library.index_files(scope, ['refs/notes.md'])[0]
        data = self.files.read('refs/notes.md')
        hit = self.library.search('METRIC')[0]
        self.assertEqual(hit['source_id'], indexed['id'])
        self.assertEqual(hit['passage'].encode(), data)
        self.assertEqual(hit['start_line'], 1)
        self.assertEqual(hit['end_line'], 5)
        self.assertEqual(hit['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(hit['citation']['path'], 'refs/notes.md')
        self.assertEqual(hit['citation']['sha256'], hit['sha256'])
        self.assertEqual(hit['source_state'], 'fresh')
        self.assertFalse(hit['stale'])
        self.assertTrue(hit['snapshot'])
        self.assertGreater(hit['indexed_at'], 0)

    def test_literal_casefold_and_text_formats(self):
        self.files.change('refs/symbols.txt', 'Straße 100% _\n'.encode())
        self.files.change('refs/record.json', b'{"choice": "Metric"}\n')
        scope = self.approve()
        self.library.index_files(scope, ['refs/symbols.txt', 'refs/record.json'])
        self.assertEqual(self.library.search('STRASSE')[0]['path'], 'refs/symbols.txt')
        self.assertEqual(len(self.library.search('%')), 1)
        self.assertEqual(len(self.library.search('_')), 1)
        self.assertEqual(self.library.search("' OR 1=1 --"), [])
        self.assertEqual(self.library.search('metric')[0]['path'], 'refs/record.json')

    def test_changed_missing_and_unsafe_source_are_stale_snapshots(self):
        scope = self.approve(); self.library.index_files(scope, ['refs/notes.md'])
        original = self.library.search('metric')[0]
        self.files.change('refs/notes.md', b'Changed current source')
        changed = self.library.search('metric')[0]
        self.assertEqual(changed['source_state'], 'changed')
        self.assertTrue(changed['stale'])
        self.assertEqual(changed['sha256'], original['sha256'])
        self.assertNotEqual(changed['current_sha256'], original['sha256'])
        self.files.change('refs/notes.md', None)
        missing = self.library.search('metric')[0]
        self.assertEqual(missing['source_state'], 'missing')
        self.assertIsNone(missing['current_sha256'])
        with patch.object(self.files, 'read', side_effect=ValueError('unsafe source')):
            self.assertEqual(self.library.search('metric')[0]['source_state'], 'unavailable')

    def test_reindex_preserves_source_id_and_refreshes_snapshot(self):
        scope = self.approve()
        original = self.library.index_files(scope, ['refs/notes.md'])[0]
        self.files.change('refs/notes.md', b'New inches decision')
        updated = self.library.index_files(scope, ['refs/notes.md'])[0]
        self.assertEqual(original['id'], updated['id'])
        self.assertNotEqual(original['sha256'], updated['sha256'])
        self.assertEqual(self.library.search('metric'), [])
        self.assertFalse(self.library.search('inches')[0]['stale'])

    def test_revocation_disables_search_reads_and_reindex_but_retains_bytes(self):
        scope = self.approve(); self.library.index_files(scope, ['refs/notes.md'])
        revoked = self.library.revoke_folder(scope)
        self.assertTrue(revoked['cached_bytes_retained'])
        with patch.object(self.files, 'read', side_effect=AssertionError('revoked read')):
            self.assertEqual(self.library.search('metric'), [])
            self.assertEqual(self.library.sources(), [])
            with self.assertRaises(ValueError):
                self.library.search('metric', folder_id=scope)
            with self.assertRaises(ValueError):
                self.library.index_files(scope, ['refs/notes.md'])
        self.assertIn('metric', self.store.db.execute('SELECT body FROM reference_sources').fetchone()[0])
        self.assertEqual(self.approve(), scope)
        self.assertEqual(self.library.search('metric')[0]['source_state'], 'fresh')

    def test_restart_preserves_ids_approval_and_revocation(self):
        identity = self.store.identity()
        scope = self.approve(); source = self.library.index_files(scope, ['refs/notes.md'])[0]
        self.library.close(); self.files.close(); self.store.close()
        self.store = Store(Path(self.temp.name) / 'state'); self.files = Files(self.store)
        self.library = ReferenceLibrary(self.store, self.files)
        self.assertEqual(self.store.identity(), identity)
        self.assertEqual(self.library.search('metric')[0]['source_id'], source['id'])
        self.library.revoke_folder(scope)
        self.library.close(); self.files.close(); self.store.close()
        self.store = Store(Path(self.temp.name) / 'state'); self.files = Files(self.store)
        self.library = ReferenceLibrary(self.store, self.files)
        self.assertEqual(self.library.folders()[0]['state'], 'revoked')
        self.assertEqual(self.library.search('metric'), [])

    def test_validation_rejects_binary_encoding_unsupported_and_oversized_atomically(self):
        cases = {'refs/binary.txt': b'a\x00b', 'refs/encoding.txt': b'\xff',
                 'refs/control.txt': b'a\x1bb', 'refs/other.pdf': b'%PDF-',
                 'refs/other.docx': b'zip bytes'}
        for path, data in cases.items():
            self.files.change(path, data)
        (self.files.root / 'refs/large.txt').write_bytes(b'x' * (MAX_BYTES + 1))
        scope = self.approve()
        for path in [*cases, 'refs/large.txt']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.library.index_files(scope, ['refs/notes.md', path])
            self.assertEqual(self.library.sources(), [])

    def test_empty_file_accepted_with_no_fabricated_results(self):
        self.files.change('refs/empty.txt', b'')
        self.library.index_files(self.approve(), ['refs/empty.txt'])
        self.assertEqual(self.library.search('anything'), [])
        self.assertEqual(self.library.sources()[0]['byte_size'], 0)

    def test_cache_and_batch_bounds_roll_back_entire_operation(self):
        scope = self.approve()
        self.files.change('refs/second.txt', b'second')
        with patch('aster.reference_library.MAX_SOURCES', 1):
            with self.assertRaises(ValueError):
                self.library.index_files(scope, ['refs/notes.md', 'refs/second.txt'])
        self.assertEqual(self.library.sources(), [])
        with patch('aster.reference_library.MAX_CACHE_BYTES', 4):
            with self.assertRaises(ValueError):
                self.library.index_files(scope, ['refs/notes.md'])
        self.assertEqual(self.library.sources(), [])

    def test_transactions_roll_back_on_event_failure(self):
        scope = self.approve()
        with patch.object(self.store, 'event', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                self.library.index_files(scope, ['refs/notes.md'])
            with self.assertRaises(RuntimeError):
                self.library.revoke_folder(scope)
        self.assertEqual(self.library.sources(), [])
        self.assertEqual(self.library.folders()[0]['state'], 'active')
        self.library.index_files(scope, ['refs/notes.md'])
        old = self.library.search('metric')[0]
        self.files.change('refs/notes.md', b'replacement')
        with patch.object(self.store, 'event', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                self.library.index_files(scope, ['refs/notes.md'])
        self.assertEqual(self.library.search('metric')[0]['sha256'], old['sha256'])

    def test_narrow_folder_and_explicit_root_approval(self):
        self.files.change('refs/sub/item.txt', b'nested metric')
        narrow = self.approve('refs/sub')
        with self.assertRaises(ValueError):
            self.library.index_files(narrow, ['refs/notes.md'])
        self.library.index_files(narrow, ['refs/sub/item.txt'])
        root = self.approve('.')
        self.library.index_files(root, ['other/unapproved.txt'])
        self.assertEqual(len(self.library.search('own approval')), 1)
        self.library.revoke_folder(root)
        self.assertEqual(self.library.search('own approval'), [])
        self.assertEqual(self.library.search('metric')[0]['path'], 'refs/sub/item.txt')

    def test_invalid_folders_do_not_create_approvals_or_directories(self):
        for folder in ['', '..', 'refs/../other', '/tmp', 'refs//sub', 'refs/', 'missing', 'refs/notes.md']:
            with self.subTest(folder=folder), self.assertRaises((ValueError, OSError)):
                self.approve(folder)
        self.assertEqual(self.library.folders(), [])
        self.assertFalse((self.files.root / 'missing').exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink and hardlink security fixtures')
    def test_symlinks_hardlinks_and_fifo_refused_without_reading_outside(self):
        outside = Path(self.temp.name) / 'outside'; outside.mkdir()
        (outside / 'secret.txt').write_text('outside private fixture')
        (self.files.root / 'linked').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.approve('linked')
        (self.files.root / 'refs/link.txt').symlink_to(outside / 'secret.txt')
        (self.files.root / 'refs/sub').symlink_to(outside, target_is_directory=True)
        os.link(outside / 'secret.txt', self.files.root / 'refs/hard.txt')
        os.mkfifo(self.files.root / 'refs/pipe.txt')
        scope = self.approve()
        for path in ['refs/link.txt', 'refs/sub/secret.txt', 'refs/hard.txt', 'refs/pipe.txt']:
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                self.library.index_files(scope, [path])
        self.assertEqual(self.library.sources(), [])
        self.assertEqual((outside / 'secret.txt').read_text(), 'outside private fixture')

    @unittest.skipUnless(os.name == 'posix', 'POSIX directory-swap security fixture')
    def test_directory_replaced_by_symlink_after_approval_is_refused(self):
        scope = self.approve(); self.library.index_files(scope, ['refs/notes.md'])
        (self.files.root / 'refs').rename(self.files.root / 'old_refs')
        (self.files.root / 'refs').symlink_to(self.files.root / 'old_refs', target_is_directory=True)
        with self.assertRaises(OSError):
            self.library.index_files(scope, ['refs/notes.md'])
        self.assertEqual(self.library.search('metric')[0]['source_state'], 'unavailable')

    def test_long_lines_exact_columns_casefold_mapping_and_passage_bound(self):
        line = 'a' * 10000 + 'Straße' + 'z' * 10000
        self.files.change('refs/long.txt', line.encode())
        self.library.index_files(self.approve(), ['refs/long.txt'])
        hit = self.library.search('STRASSE')[0]
        self.assertLessEqual(len(hit['passage']), MAX_PASSAGE_CHARS)
        self.assertIn('Straße', hit['passage'])
        self.assertEqual(hit['passage'], line[hit['start_column'] - 1:hit['end_column']])
        self.assertEqual(hit['start_line'], 1)
        self.assertEqual(hit['end_line'], 1)
        self.assertTrue(hit['clipped'])

    def test_newlines_and_unicode_separators_preserve_exact_source_lines(self):
        data = 'zero\r\none\rtwo\nthree\u2028metric\nfour'.encode()
        self.files.change('refs/newlines.txt', data)
        self.library.index_files(self.approve(), ['refs/newlines.txt'])
        hit = self.library.search('metric')[0]
        self.assertEqual(hit['start_line'], 2)
        self.assertEqual(hit['end_line'], 5)
        self.assertEqual(hit['passage'], 'one\rtwo\nthree\u2028metric\nfour')

    def test_queries_limits_and_deterministic_order(self):
        self.files.change('refs/a.txt', b'metric a')
        self.library.index_files(self.approve(), ['refs/notes.md', 'refs/a.txt'])
        self.assertEqual(self.library.search('metric', limit=1)[0]['path'], 'refs/a.txt')
        for query in ['', ' ', 'x' * 513, 'two\nlines', 5]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.library.search(query)
        for limit in [0, True, 101, '2']:
            with self.assertRaises(ValueError):
                self.library.search('metric', limit=limit)

    def test_no_network_no_model_no_unconfigured_adapters(self):
        with patch('socket.socket', side_effect=AssertionError('No network allowed')):
            self.library.index_files(self.approve(), ['refs/notes.md'])
            self.assertEqual(len(self.library.search('metric')), 1)
        status = self.library.status()
        for adapter in ['pdf', 'ocr', 'zotero']:
            self.assertEqual(status[adapter], 'unconfigured')
        self.assertFalse(status['semantic_search'])
        self.assertFalse(status['recursive_scan'])
        self.assertFalse(status['model_learning'])
        self.assertFalse(status['encrypted'])

    def test_folder_count_limit_and_approval_transaction_rollback(self):
        with patch.object(self.store, 'event', side_effect=RuntimeError('simulated failure')):
            with self.assertRaises(RuntimeError):
                self.approve()
        self.assertEqual(self.library.folders(), [])
        scope = self.approve()
        self.assertEqual(self.approve(), scope)
        with patch('aster.reference_library.MAX_FOLDERS', 1):
            with self.assertRaises(ValueError):
                self.approve('other')
        self.assertEqual(len(self.library.folders()), 1)

    @unittest.skipUnless(os.name == 'nt', 'Requires native Windows NTFS; not mocked')
    def test_native_windows_canonical_scope_and_alias_refusal(self):
        scope = self.approve('REFS')
        self.assertEqual(self.library.folders()[0]['path'], 'refs')
        indexed = self.library.index_files(scope, ['REFS/NOTES.MD'])
        self.assertEqual(indexed[0]['path'], 'refs/notes.md')
        for path in ['refs/notes.md:stream', 'refs/NUL.txt', 'refs/LONGNA~1.txt']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.library.index_files(scope, [path])

    @unittest.skipUnless(os.name == 'nt', 'Requires native Windows NTFS; not mocked')
    def test_native_windows_junction_and_hardlink_refusal(self):
        outside = Path(self.temp.name) / 'outside'; outside.mkdir()
        (outside / 'secret.txt').write_text('outside private fixture')
        link = self.files.root / 'refs/junction'
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(outside)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        try:
            with self.assertRaises((ValueError, OSError)):
                self.approve('refs/junction')
            scope = self.approve()
            with self.assertRaises((ValueError, OSError)):
                self.library.index_files(scope, ['refs/junction/secret.txt'])
            os.link(outside / 'secret.txt', self.files.root / 'refs/hard.txt')
            with self.assertRaises((ValueError, OSError)):
                self.library.index_files(scope, ['refs/hard.txt'])
            self.assertEqual(self.library.sources(), [])
        finally:
            link.rmdir()

    def test_wrong_store_reader_is_rejected_and_owned_close_is_idempotent(self):
        other = Store(Path(self.temp.name) / 'other')
        try:
            with self.assertRaises(ValueError):
                ReferenceLibrary(other, self.files)
            owned = ReferenceLibrary(other)
            owned.close(); owned.close()
        finally:
            other.close()
