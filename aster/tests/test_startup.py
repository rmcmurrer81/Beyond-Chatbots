"""Startup tests never read or write the actual Windows startup registry.

Registry behavior uses fake backends, including the winreg adapter's API calls.
Only command-line parsing uses a native Windows API, without registration.
"""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from aster import startup


class FakeRegistry:
    def __init__(self):
        self.values = {}
        self.writes = []
        self.fail_create = False

    def read(self, name):
        return self.values.get(name)

    def create(self, name, command):
        if self.fail_create:
            raise OSError('simulated registration failure')
        if name in self.values:
            raise RuntimeError('Startup value already exists')
        self.values[name] = startup.RegistryValue(command)
        self.writes.append(('create', name, command))

    def delete_exact(self, name, command):
        if name not in self.values:
            return
        if self.values[name] != startup.RegistryValue(command):
            raise RuntimeError('Startup value changed')
        del self.values[name]
        self.writes.append(('delete', name, command))


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # Windows runner TEMP can contain an existing 8.3 spelling (for example
        # RUNNER~1). Canonicalize this test-owned fixture, not production input.
        self.root = Path(self.temp.name).resolve(strict=True)
        self.state = self.root / 'state'; self.state.mkdir()
        self.checkout = self.root / 'app'; self.checkout.mkdir()
        (self.checkout / 'aster').mkdir()
        (self.checkout / 'aster' / '__init__.py').write_text('')
        (self.checkout / 'launch_aster.py').write_text('# fixture launcher\n')
        self.registry = FakeRegistry()
        self.runtime_patch = patch.object(startup, 'CHECKOUT', self.checkout)
        self.runtime_patch.start()
        # Safety tripwire on all platforms: a missed injected backend cannot
        # touch the CI machine's registry, even for read-only status.
        self.native_patch = patch.object(startup, 'WindowsRegistry', side_effect=AssertionError('No real registry access in tests'))
        self.native_patch.start()

    def tearDown(self):
        self.native_patch.stop(); self.runtime_patch.stop(); self.temp.cleanup()

    def plan(self, action='enable'):
        return startup.plan(self.state, action=action, registry=self.registry)

    def enable(self, confirm=lambda plan: True):
        plan = self.plan()
        return startup.enable(self.state, reviewed_plan_digest=plan['plan_digest'], confirm=confirm, registry=self.registry)

    def disable(self, confirm=lambda plan: True):
        plan = self.plan('disable')
        return startup.disable(self.state, reviewed_plan_digest=plan['plan_digest'], confirm=confirm, registry=self.registry)

    def test_default_plan_is_read_only_and_exact(self):
        before = list(self.state.iterdir())
        plan = self.plan()
        self.assertEqual(list(self.state.iterdir()), before)
        self.assertEqual(self.registry.writes, [])
        self.assertTrue(plan['dry_run']); self.assertEqual(plan['status'], 'disabled')
        self.assertEqual(plan['destination'], 'HKCU\\' + startup.RUN_KEY)
        self.assertEqual(plan['runtime']['argv'], [str(Path(sys.executable).resolve()), '-I', '-S', '-B',
                                                 str(self.checkout / 'launch_aster.py'), '--state', str(self.state)])
        self.assertEqual(plan['runtime']['command'], subprocess.list2cmdline(plan['runtime']['argv']))
        self.assertEqual(plan['plan_digest'], self.plan()['plan_digest'])

    def test_enable_disable_preserve_every_unrelated_value(self):
        self.registry.values['OtherApp'] = startup.RegistryValue('unrelated.exe --start')
        result = self.enable()
        self.assertEqual(result['status'], 'enabled')
        self.assertTrue(result['changed'])
        self.assertTrue((self.state / startup.RECEIPT_NAME).is_file())
        self.assertEqual(startup.status(self.state, registry=self.registry)['status'], 'enabled')
        repeated = self.enable()
        self.assertFalse(repeated['changed']); self.assertEqual(len(self.registry.writes), 1)
        self.assertEqual(self.disable()['status'], 'disabled')
        self.assertEqual(self.registry.values, {'OtherApp': startup.RegistryValue('unrelated.exe --start')})
        self.assertFalse((self.state / startup.RECEIPT_NAME).exists())
        self.assertFalse(self.disable()['changed'])

    def test_no_fresh_approval_no_mutation(self):
        plan = self.plan()
        result = self.enable(lambda shown: False)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(list(self.state.iterdir()), [])
        for confirmation in (None, False, True):
            with self.subTest(confirmation=confirmation), self.assertRaises(ValueError):
                startup.enable(self.state, reviewed_plan_digest=plan['plan_digest'], confirm=confirmation, registry=self.registry)
        result = self.enable(lambda shown: 1)  # truthiness is insufficient
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.registry.writes, [])

    def test_wrong_or_stale_plan_rejected_before_confirmation(self):
        plan = self.plan()
        (self.checkout / 'launch_aster.py').write_text('# changed launcher\n')
        with self.assertRaisesRegex(ValueError, 'plan changed'):
            startup.enable(self.state, reviewed_plan_digest=plan['plan_digest'],
                           confirm=lambda shown: self.fail('Must not ask using stale plan'), registry=self.registry)
        self.assertEqual(self.registry.writes, [])
        self.assertEqual(list(self.state.iterdir()), [])

    def test_registration_change_during_confirmation_is_rejected(self):
        name = self.plan()['value_name']
        def confirm(plan):
            self.registry.values[name] = startup.RegistryValue('foreign.exe')
            return True
        with self.assertRaisesRegex(ValueError, 'changed during confirmation'):
            self.enable(confirm)
        self.assertEqual(self.registry.values[name].data, 'foreign.exe')
        self.assertEqual(self.registry.writes, [])
        self.assertFalse((self.state / startup.RECEIPT_NAME).exists())

    def test_foreign_even_identical_value_is_never_claimed(self):
        plan = self.plan()
        self.registry.values[plan['value_name']] = startup.RegistryValue(plan['runtime']['command'])
        self.assertEqual(self.plan()['status'], 'foreign_value')
        self.assertFalse(self.plan()['can_apply'])
        for fn in (self.enable, self.disable):
            with self.assertRaisesRegex(ValueError, 'unowned'):
                fn()
        self.assertEqual(self.registry.writes, [])

    def test_modified_value_and_changed_registry_type_are_preserved(self):
        self.enable()
        plan = self.plan()
        for value in (startup.RegistryValue('modified.exe'), startup.RegistryValue(plan['runtime']['command'], 2)):
            self.registry.values[plan['value_name']] = value
            self.assertEqual(self.plan()['status'], 'modified_value')
            for fn in (self.enable, self.disable):
                with self.assertRaisesRegex(ValueError, 'modified'):
                    fn()
            self.assertEqual(self.registry.values[plan['value_name']], value)
        self.assertTrue((self.state / startup.RECEIPT_NAME).exists())

    def test_failed_registration_retains_pending_receipt_for_retry(self):
        self.registry.fail_create = True
        with self.assertRaises(OSError):
            self.enable()
        self.assertEqual(self.plan()['status'], 'pending_or_missing')
        self.assertTrue((self.state / startup.RECEIPT_NAME).is_file())
        self.registry.fail_create = False
        self.assertEqual(self.enable()['status'], 'enabled')
        self.disable()

    def test_pending_receipt_can_be_explicitly_cleaned_up(self):
        self.registry.fail_create = True
        with self.assertRaises(OSError):
            self.enable()
        self.assertEqual(self.disable()['status'], 'disabled')
        self.assertFalse((self.state / startup.RECEIPT_NAME).exists())

    def test_updated_launch_plan_requires_disable_and_new_review(self):
        self.enable()
        (self.checkout / 'launch_aster.py').write_text('# update\n')
        self.assertFalse(self.plan()['can_apply'])
        with self.assertRaisesRegex(ValueError, 'different launch plan'):
            self.enable()
        self.assertEqual(self.disable()['status'], 'disabled')
        self.assertEqual(self.enable()['status'], 'enabled')

    def test_disable_uses_recorded_exact_command_after_launcher_is_missing(self):
        enabled = self.enable()
        (self.checkout / 'launch_aster.py').unlink()
        result = self.disable()
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(self.registry.writes[-1], ('delete', enabled['value_name'], enabled['runtime']['command']))

    def test_late_modified_value_is_never_deleted(self):
        self.enable()
        name = self.plan()['value_name']
        original_delete = self.registry.delete_exact
        def racing_delete(value_name, command):
            self.registry.values[name] = startup.RegistryValue('foreign late change')
            original_delete(value_name, command)
        self.registry.delete_exact = racing_delete
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.disable()
        self.assertEqual(self.registry.values[name].data, 'foreign late change')
        self.assertTrue((self.state / startup.RECEIPT_NAME).exists())

    def test_corrupt_or_mismatched_receipt_fails_closed(self):
        self.enable()
        receipt = self.state / startup.RECEIPT_NAME
        saved = receipt.read_text()
        for bad in ('{', '[]', '{}', saved.replace('AsterWorkstation-', 'ForeignProgram-')):
            receipt.write_text(bad)
            with self.subTest(bad=bad[:30]), self.assertRaises(ValueError):
                startup.status(self.state, registry=self.registry)
        self.assertEqual(len(self.registry.writes), 1)

    def test_missing_and_relative_state_do_not_create_directories(self):
        for path in ('relative-state', self.root / 'missing'):
            with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                startup.plan(path, registry=self.registry)
        self.assertFalse((self.root / 'missing').exists())

    def test_state_paths_with_expansion_tokens_and_control_chars_rejected(self):
        for name in ('bad%PATH%', 'bad\nname', 'bad"name'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                startup.plan(self.root / name, registry=self.registry)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows long-path fixture and alias regression')
    def test_native_fixture_is_canonical_but_explicit_aliases_are_rejected(self):
        self.assertEqual(self.root, Path(self.temp.name).resolve(strict=True))
        self.assertFalse(any('~' in part for part in self.root.parts))
        self.assertEqual(startup._state_path(self.state), self.state)
        # Rejection precedes filesystem access, including when 8.3 name
        # generation is disabled on the CI volume.
        with self.assertRaisesRegex(ValueError, 'ambiguous Windows aliases'):
            startup.plan(self.root / 'ASTER~1', registry=self.registry)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        short_path = kernel32.GetShortPathNameW
        short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        short_path.restype = ctypes.c_uint32
        count = short_path(str(self.state), None, 0)
        self.assertGreater(count, 0)
        buffer = ctypes.create_unicode_buffer(count)
        copied = short_path(str(self.state), buffer, count)
        self.assertGreater(copied, 0)
        self.assertLess(copied, count)
        # Some volumes return the long path unchanged. When a real alias is
        # available, prove it names our fixture but is still refused as input.
        alias = Path(buffer.value)
        self.assertTrue(alias.samefile(self.state))
        if any('~' in part for part in alias.parts):
            with self.assertRaisesRegex(ValueError, 'ambiguous Windows aliases'):
                startup.plan(alias, registry=self.registry)
        self.assertEqual(self.registry.writes, [])

    @unittest.skipIf(os.name == 'nt', 'Windows symlink creation can require extra privileges')
    def test_symlink_state_launcher_and_receipt_are_rejected(self):
        link = self.root / 'linked'; link.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(ValueError):
            startup.plan(link, registry=self.registry)
        launcher = self.checkout / 'launch_aster.py'
        launcher.unlink(); launcher.symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):
            self.plan()
        launcher.unlink(); launcher.write_text('# fixture\n')
        (self.state / startup.RECEIPT_NAME).symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):
            self.plan()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX special-file guard')
    def test_fifo_receipt_rejected_before_open(self):
        os.mkfifo(self.state / startup.RECEIPT_NAME)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.plan()

    def test_hardlinked_receipt_is_rejected(self):
        self.enable()
        os.link(self.state / startup.RECEIPT_NAME, self.root / 'receipt-copy')
        with self.assertRaisesRegex(ValueError, 'single-link'):
            self.plan()

    def test_long_command_is_rejected_never_truncated(self):
        with self.assertRaisesRegex(ValueError, '260-character'):
            startup._windows_command(['C:\\Python\\python.exe', 'x' * 260])
        with self.assertRaisesRegex(ValueError, '260-character'):
            startup._windows_command(['C:\\Python\\python.exe', '\U0001f600' * 130])

    @unittest.skipIf(os.name == 'nt', 'Non-Windows read-only unsupported report')
    def test_non_windows_defaults_fail_closed(self):
        plan = startup.plan(self.state)
        self.assertEqual(plan['status'], 'unsupported_platform')
        self.assertFalse(plan['can_apply'])
        with self.assertRaisesRegex(ValueError, 'only on Windows'):
            startup.enable(self.state, reviewed_plan_digest=plan['plan_digest'], confirm=lambda shown: True)
        self.assertEqual(list(self.state.iterdir()), [])


class FakeKey:
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeWinreg:
    HKEY_CURRENT_USER = 'CURRENT_USER_ONLY'
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}
        self.calls = []

    def OpenKey(self, hive, key, reserved, access):
        self.calls.append(('open', hive, key, access)); return FakeKey()

    def CreateKeyEx(self, hive, key, reserved, access):
        self.calls.append(('create-key', hive, key, access)); return FakeKey()

    def QueryValueEx(self, key, name):
        if name not in self.values: raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, command):
        self.calls.append(('set', name, kind, command)); self.values[name] = (command, kind)

    def DeleteValue(self, key, name):
        self.calls.append(('delete', name)); del self.values[name]


class RegistryAdapterTests(unittest.TestCase):
    def setUp(self):
        # Bypass __init__ to attach a fake module. Never import real winreg.
        self.registry = object.__new__(startup.WindowsRegistry)
        self.fake = FakeWinreg(); self.registry.winreg = self.fake

    def test_current_user_fixed_destination_and_exact_uninstall(self):
        self.assertIsNone(self.registry.read('owned'))
        self.registry.create('owned', 'python.exe fixed-launcher.py')
        self.assertEqual(self.registry.read('owned'), startup.RegistryValue('python.exe fixed-launcher.py'))
        self.registry.delete_exact('owned', 'python.exe fixed-launcher.py')
        self.assertEqual(self.fake.values, {})
        for call in self.fake.calls:
            if call[0] in ('open', 'create-key'):
                self.assertEqual(call[1:3], (self.fake.HKEY_CURRENT_USER, startup.RUN_KEY))

    def test_preexisting_and_modified_values_never_mutated(self):
        self.fake.values['owned'] = ('foreign.exe', 1)
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            self.registry.create('owned', 'new.exe')
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.registry.delete_exact('owned', 'new.exe')
        self.fake.values['owned'] = ('new.exe', 2)
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.registry.delete_exact('owned', 'new.exe')
        self.assertFalse(any(call[0] in ('set', 'delete') for call in self.fake.calls))


class FixedLauncherTests(unittest.TestCase):
    def test_isolated_launcher_pins_checkout_with_unrelated_cwd_and_pythonpath(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkout = root / 'fixed checkout'; checkout.mkdir()
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'launch_aster.py', checkout / 'launch_aster.py')
            package = checkout / 'aster'; package.mkdir()
            (package / '__init__.py').write_text('')
            (package / 'lifecycle.py').write_text(
                'import json\n'
                'def startup_launch(state):\n'
                '    print(json.dumps({"state": str(state), "source": __file__}))\n'
                '    return 0\n')
            poison = root / 'poison'; poison.mkdir(); (poison / 'aster').mkdir()
            (poison / 'aster' / '__init__.py').write_text('raise RuntimeError("Wrong checkout imported")\n')
            (poison / 'sitecustomize.py').write_text('raise RuntimeError("Site code executed")\n')
            state = root / 'my state'; state.mkdir()
            env = {**os.environ, 'PYTHONPATH': str(poison)}
            result = subprocess.run([sys.executable, '-I', '-S', '-B', str(checkout / 'launch_aster.py'),
                                     '--state', str(state)], cwd=poison, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload['state'], str(state))
            self.assertEqual(payload['source'], str(package / 'lifecycle.py'))

    def test_rejects_unisolated_invocation_and_arbitrary_arguments(self):
        launcher = Path(__file__).resolve().parents[1] / 'launch_aster.py'
        result = subprocess.run([sys.executable, str(launcher), '--state', '/irrelevant'],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Python -I -S -B', result.stderr)
        for args in ([], ['--module', 'os'], ['--state', 'relative'], ['--state', 'a', '--state', 'b']):
            result = subprocess.run([sys.executable, '-I', '-S', '-B', str(launcher), *args],
                                    capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)


@unittest.skipUnless(os.name == 'nt', 'Native Windows argument parser only; no registry use')
class NativeWindowsCommandTests(unittest.TestCase):
    def test_python_quoting_round_trips_through_windows_parser(self):
        shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        parser = shell32.CommandLineToArgvW
        parser.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        parser.restype = ctypes.POINTER(ctypes.c_wchar_p)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        vectors = [
            ['C:\\Program Files\\Python\\python.exe', '-I', '-S', '-B', 'C:\\Aster app\\launch_aster.py', '--state', 'C:\\my state'],
            ['C:\\Python\\python.exe', 'C:\\Unicode \u00e9\\launch.py', '--state', 'C:\\folder with spaces\\'],
            ['C:\\Python\\python.exe', 'literal & caret^ pipe|', 'embedded"quote', '', 'backslashes\\\\"quote'],
        ]
        for argv in vectors:
            with self.subTest(argv=argv):
                command = startup._windows_command(argv)
                count = ctypes.c_int()
                parsed = parser(command, ctypes.byref(count))
                self.assertTrue(parsed)
                try:
                    self.assertEqual([parsed[i] for i in range(count.value)], argv)
                finally:
                    kernel32.LocalFree(ctypes.cast(parsed, ctypes.c_void_p))
