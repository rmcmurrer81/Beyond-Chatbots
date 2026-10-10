"""Native Windows safety tests; no mocked Win32 success counts as coverage.

The grammar tests run everywhere. The native tests require actual Windows on a
local NTFS temporary volume and exercise the adapter against the filesystem.
"""
import ctypes
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from aster.files import MAX_BYTES
from aster.storage import Store
from aster.windows_files import WindowsFiles, windows_parts
from aster import windows_files as win


class WindowsPathTests(unittest.TestCase):
    def test_ascii_paths_have_one_case_insensitive_journal_key(self):
        self.assertEqual(windows_parts('Project/MAIN.py'), ('project', 'main.py'))
        self.assertEqual(windows_parts('my project/data-1_(copy).txt'),
                         ('my project', 'data-1_(copy).txt'))

    def test_rejects_traversal_namespaces_devices_and_aliases(self):
        cases = [
            '', '.', '..', '/tmp/a', 'C:/a', 'C:a', '../a', 'a/../b',
            './a', 'a//b', 'a/', 'a\\b', '.hidden', '\\\\server\\share\\x',
            '\\\\?\\C:\\x', '\\\\.\\NUL', 'a:secret', 'a::$DATA',
            'NUL', 'nul.txt', 'CON', 'con .txt', 'PRN.tar.gz', 'AUX',
            'COM1', 'com9.txt', 'LPT1', 'lpt9.py', 'CONIN$', 'CONOUT$',
            'nested/NUL', 'a.', 'a ', 'a./file', 'a /file',
            'name\x00', 'name\x01', 'name\x1f', 'name\x7f',
            'bad<name', 'bad>name', 'bad"name', 'bad|name', 'bad?name',
            'bad*name', 'LONGNA~1.TXT', 'nested/LONGNA~1.TXT',
            'caf\u00e9.txt', 'COM\u00b9.txt', '\ud800.txt', 'a' * 256,
        ]
        for path in cases:
            with self.subTest(path=repr(path)), self.assertRaises(ValueError):
                windows_parts(path)

    @unittest.skipIf(os.name == 'nt', 'Non-Windows fail-closed check')
    def test_adapter_does_not_emulate_windows_on_another_os(self):
        with tempfile.TemporaryDirectory() as temp:
            class Storage:
                root = Path(temp)
            with self.assertRaisesRegex(RuntimeError, 'native Windows'):
                WindowsFiles(Storage())


@unittest.skipUnless(os.name == 'nt', 'Requires native Windows NTFS; not mocked')
class NativeWindowsFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.store = Store(self.base / 'state')
        try:
            self.files = WindowsFiles(self.store)
        except BaseException:
            self.store.close()
            self.temp.cleanup()
            raise

    def tearDown(self):
        self.files.close()
        self.store.close()
        self.temp.cleanup()

    def junction(self, link, destination):
        # mklink is the Windows built-in. Junction creation needs no symlink
        # privilege and must pass on the supported native CI filesystem.
        result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J',
                                 str(link), str(destination)], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(link.lstat().st_file_attributes & win._REPARSE)

    def symlink(self, link, destination, *, directory=False):
        try:
            link.symlink_to(destination, target_is_directory=directory)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows runner has no symlink privilege; junction tests still run')
            raise

    def test_native_file_write_read_trash_undo_and_empty_file(self):
        first = self.files.change('Project/MAIN.py', b'print("hi")\n')
        self.assertEqual(self.files.read('PROJECT/main.PY'), b'print("hi")\n')
        self.assertEqual(self.store.rows('changes')[0]['path'], 'project/main.py')
        update = self.files.change('project/main.py', b'new')
        self.files.undo(update)
        self.assertEqual(self.files.read('project/main.py'), b'print("hi")\n')
        deleted = self.files.change('project/main.py', None, 'trash')
        self.assertIsNone(self.files.snapshot('project/main.py'))
        self.files.undo(deleted)
        self.files.undo(first)
        self.assertIsNone(self.files.snapshot('project/main.py'))
        self.files.change('empty.txt', b'')
        self.assertEqual(self.files.read('empty.txt'), b'')
        self.assertEqual(list(self.files.root.glob('.aster-*')), [])

    def test_native_handle_relative_rename_ignores_current_directory(self):
        # A Win32 relative-name wrapper resolves against cwd on affected builds;
        # native FileRenameInformation must resolve against our held parent.
        outside = self.base / 'other-cwd'
        outside.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(outside)
            for name in ['x', 'ab', 'n' * 255]:
                self.files.change('nested/' + name, b'old')
                self.files.change('nested/' + name, b'new')
                self.assertEqual(self.files.read('nested/' + name), b'new')
                self.assertFalse((outside / name).exists())
        finally:
            os.chdir(previous)

    def test_prepared_edit_cannot_be_bypassed_by_different_case(self):
        # Fault injection tests journal logic; real native operations are tested
        # separately. This is not evidence of a real OS crash.
        with patch.object(self.files, '_replace', side_effect=RuntimeError('simulated crash')):
            with self.assertRaises(RuntimeError):
                self.files.change('Project/FILE.txt', b'a')
        with self.assertRaisesRegex(ValueError, 'recover'):
            self.files.change('PROJECT/file.TXT', b'b')
        self.assertEqual(self.files.recover()[0]['status'], 'not_applied')
        self.files.change('project/file.txt', b'b')
        self.assertEqual(self.files.read('project/file.txt'), b'b')

    def test_imported_mixed_case_prepared_journal_also_blocks(self):
        with patch.object(self.files, '_replace', side_effect=RuntimeError('simulated crash')):
            with self.assertRaises(RuntimeError):
                self.files.change('project/a.txt', b'a')
        with self.store.db:
            self.store.db.execute("UPDATE changes SET path='PROJECT/A.TXT'")
        with self.assertRaisesRegex(ValueError, 'recover'):
            self.files.change('project/a.txt', b'b')
        self.assertEqual(self.files.recover()[0]['status'], 'not_applied')

    def test_ads_and_device_paths_cannot_mutate_files_or_journal(self):
        self.files.change('safe.txt', b'safe')
        before = len(self.store.rows('changes'))
        for path in ['safe.txt:stream', 'safe.txt::$DATA', 'NUL', 'nested/CON.txt']:
            for data in [b'bad', None]:
                with self.subTest(path=path, data=data), self.assertRaises(ValueError):
                    self.files.change(path, data)
        self.assertEqual(len(self.store.rows('changes')), before)
        self.assertEqual(self.files.read('safe.txt'), b'safe')

    def test_rejects_case_sensitive_directory_when_os_can_create_one(self):
        directory = self.files.root / 'sensitive'
        directory.mkdir()
        handle = self.files._api.open(str(directory), win._GENERIC_READ | win._GENERIC_WRITE)
        enabled = win._DWORD(1)
        try:
            result = self.files._api.dll.SetFileInformationByHandle(
                handle, win._FILE_CASE_SENSITIVE_INFO, ctypes.byref(enabled), ctypes.sizeof(enabled))
            if not result:
                error = ctypes.get_last_error()
                if error in {5, 50, 87}:
                    self.skipTest('Runner cannot create a case-sensitive directory (WinError %s)' % error)
                raise ctypes.WinError(error)
        finally:
            self.files._api.close(handle)
        try:
            with self.assertRaisesRegex(ValueError, 'Case-sensitive'):
                self.files._replace('sensitive/a.txt', b'bad')
        finally:
            # Reset the test fixture's flag so cleanup does not depend on it.
            handle = self.files._api.open(str(directory), win._GENERIC_READ | win._GENERIC_WRITE)
            try:
                disabled = win._DWORD(0)
                self.files._api.check(self.files._api.dll.SetFileInformationByHandle(
                    handle, win._FILE_CASE_SENSITIVE_INFO, ctypes.byref(disabled), ctypes.sizeof(disabled)))
            finally:
                self.files._api.close(handle)

    def test_conflict_aware_undo(self):
        change = self.files.change('a.txt', b'one')
        (self.files.root / 'a.txt').write_bytes(b'outside')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.files.undo(change)
        self.assertEqual(self.files.read('a.txt'), b'outside')

    def test_rejects_hardlinks_for_read_write_and_trash(self):
        outside = self.base / 'outside.txt'
        outside.write_bytes(b'safe')
        os.link(outside, self.files.root / 'hard.txt')
        for operation in [lambda: self.files.read('hard.txt'),
                          lambda: self.files._replace('hard.txt', b'bad'),
                          lambda: self.files._replace('hard.txt', None)]:
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(outside.read_bytes(), b'safe')
        self.assertTrue((self.files.root / 'hard.txt').exists())

    def test_rejects_junction_ancestor_without_touching_destination(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'data.txt').write_bytes(b'safe')
        self.junction(self.files.root / 'junction', outside)
        try:
            for path, data in [('junction/data.txt', b'bad'),
                               ('junction/new.txt', b'bad'),
                               ('junction/data.txt', None)]:
                with self.subTest(path=path, data=data), self.assertRaises((ValueError, OSError)):
                    self.files._replace(path, data)
            with self.assertRaises((ValueError, OSError)):
                self.files.read('junction/data.txt')
            self.assertEqual((outside / 'data.txt').read_bytes(), b'safe')
            self.assertFalse((outside / 'new.txt').exists())
        finally:
            os.rmdir(self.files.root / 'junction')

    def test_rejects_junction_as_leaf(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.junction(self.files.root / 'junction', outside)
        try:
            with self.assertRaises((ValueError, OSError)):
                self.files._replace('junction', b'bad')
            self.assertTrue(outside.is_dir())
        finally:
            os.rmdir(self.files.root / 'junction')

    def test_rejects_workspace_reparse_root(self):
        self.files.close()
        os.rmdir(self.files.root)
        outside = self.base / 'outside'
        outside.mkdir()
        self.junction(self.files.root, outside)
        try:
            with self.assertRaises((ValueError, OSError)):
                WindowsFiles(self.store)
        finally:
            os.rmdir(self.files.root)

    def test_rejects_real_workspace_root_replacement(self):
        moved = self.store.root / 'old-workspace'
        self.files.root.rename(moved)
        self.files.root.mkdir()
        with self.assertRaisesRegex(ValueError, 'replaced'):
            self.files.change('a.txt', b'bad')
        self.assertFalse((self.files.root / 'a.txt').exists())

    def test_rejects_leaf_symlink(self):
        outside = self.base / 'outside.txt'
        outside.write_bytes(b'safe')
        self.symlink(self.files.root / 'link', outside)
        for operation in [lambda: self.files.read('link'),
                          lambda: self.files._replace('link', b'bad'),
                          lambda: self.files._replace('link', None)]:
            with self.assertRaises((ValueError, OSError)):
                operation()
        self.assertEqual(outside.read_bytes(), b'safe')

    def test_rejects_dangling_symlink(self):
        missing = self.base / 'missing.txt'
        self.symlink(self.files.root / 'link', missing)
        with self.assertRaises((ValueError, OSError)):
            self.files._replace('link', b'bad')
        self.assertFalse(missing.exists())

    def test_rejects_large_files_and_directories(self):
        (self.files.root / 'large').write_bytes(b'x' * (MAX_BYTES + 1))
        (self.files.root / 'folder').mkdir()
        for path in ['large', 'folder']:
            for operation in [lambda p=path: self.files.read(p),
                              lambda p=path: self.files._replace(p, b'bad'),
                              lambda p=path: self.files._replace(p, None)]:
                with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                    operation()
        self.files.change('max.txt', b'x' * MAX_BYTES)
        self.assertEqual(len(self.files.read('max.txt')), MAX_BYTES)

    def test_ancestor_handles_prevent_rename_and_reparse_writer(self):
        with self.files.parent('nested/deeper/a.txt', create=True) as parent:
            for directory in [self.store.root, self.files.root,
                              self.files.root / 'nested', self.files.root / 'nested' / 'deeper']:
                with self.subTest(directory=directory), self.assertRaises(OSError):
                    directory.rename(directory.with_name(directory.name + '-moved'))
            # Setting a reparse point requires a writable directory handle.
            # A strict handle excludes that open even when the directory is empty.
            with self.assertRaises(OSError):
                handle = self.files._api.open(parent.path, win._GENERIC_WRITE,
                    share=win._SHARE_READ | win._SHARE_WRITE)
                self.files._api.close(handle)
        # The handles are operation-scoped and released even on normal exit.
        nested = self.files.root / 'nested'
        nested.rename(self.files.root / 'moved')

    def test_rename_keeps_parent_and_temp_file_pinned(self):
        original = self.files._api.rename
        observed = []
        def verify_and_rename(handle, parent_handle, name):
            # The check wraps a real native rename, with real native open handles.
            temp_path = self.files._api.normalized_path(handle)
            directory = Path(temp_path).parent
            with self.assertRaises(OSError):
                directory.rename(directory.with_name(directory.name + '-moved'))
            with self.assertRaises(OSError):
                os.unlink(temp_path)
            self.assertTrue(self.files._api.info(parent_handle, directory=True).attributes & win._DIRECTORY)
            original(handle, parent_handle, name)
            observed.append(True)
        with patch.object(self.files._api, 'rename', side_effect=verify_and_rename):
            self.files.change('nested/a.txt', b'one')
            self.files.change('nested/a.txt', b'two')
        self.assertEqual(observed, [True, True])
        self.assertEqual(self.files.read('nested/a.txt'), b'two')

    def test_failed_rename_keeps_old_bytes_and_removes_owned_temp(self):
        self.files.change('a.txt', b'old')
        with patch.object(self.files._api, 'rename', side_effect=OSError('simulated native failure')):
            with self.assertRaises(OSError):
                self.files.change('a.txt', b'new')
        self.assertEqual(self.files.read('a.txt'), b'old')
        self.assertEqual(list(self.files.root.glob('.aster-*')), [])
        self.assertEqual(self.files.recover()[0]['status'], 'not_applied')

    def test_read_handle_denies_writes_and_rename(self):
        self.files.change('a.txt', b'safe')
        with self.files.parent('a.txt') as parent:
            handle = self.files._file(parent)
            try:
                with self.assertRaises(OSError):
                    writer = self.files._api.open(parent.target, win._GENERIC_WRITE,
                                                  share=win._SHARE_READ | win._SHARE_WRITE)
                    self.files._api.close(writer)
                with self.assertRaises(OSError):
                    (self.files.root / 'a.txt').rename(self.files.root / 'b.txt')
                self.assertEqual(self.files._api.read(handle), b'safe')
            finally:
                self.files._api.close(handle)

    def test_native_abi_and_closed_lifecycle(self):
        self.assertEqual(ctypes.sizeof(win._FileInformation), 52)
        self.assertEqual(ctypes.sizeof(win._NTSTATUS), 4)
        self.assertEqual(ctypes.sizeof(win._IoStatusBlock), 2 * ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(win._IoStatusBlock.information.offset, ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(win._RenameInformation.name.offset, 20 if ctypes.sizeof(ctypes.c_void_p) == 8 else 12)
        self.files.close()
        self.files.close()
        with self.assertRaisesRegex(ValueError, 'closed'):
            self.files.read('a.txt')


if __name__ == '__main__':
    unittest.main()
