"""Opt-in current-user Windows logon registration, never invoked on import.

All public operations default to a read-only plan. Mutations require a matching
plan digest and a fresh interactive approval supplied by the CLI. Registry tests
must inject a backend; they never change the host's real startup configuration.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from .platform import linklike, lock_state

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
REG_SZ = 1
RECEIPT_NAME = 'startup-registration.json'
LOCK_NAME = 'startup-registration.lock'
MAX_RECEIPT_BYTES = 16384
MAX_COMMAND_UNITS = 260
CHECKOUT = Path(__file__).absolute().parent.parent


@dataclass(frozen=True)
class RegistryValue:
    data: object
    kind: int = REG_SZ


class WindowsRegistry:
    """The only real registry adapter. Fixed HKCU key; no shell or admin work.

    Compare immediately before mutation and never restore a whole key. The
    advisory file lock coordinates Aster processes, not hostile same-user tools.
    """
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Startup registration requires native Windows')
        import winreg
        self.winreg = winreg

    def read(self, name):
        w = self.winreg
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_QUERY_VALUE) as key:
                data, kind = w.QueryValueEx(key, name)
                return RegistryValue(data, kind)
        except FileNotFoundError:
            return None

    def create(self, name, command):
        w = self.winreg
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, RUN_KEY, 0,
                           w.KEY_QUERY_VALUE | w.KEY_SET_VALUE) as key:
            try:
                w.QueryValueEx(key, name)
            except FileNotFoundError:
                pass
            else:
                raise RuntimeError('Startup value already exists; nothing was overwritten')
            w.SetValueEx(key, name, 0, w.REG_SZ, command)
            if w.QueryValueEx(key, name) != (command, w.REG_SZ):
                raise RuntimeError('Startup registration verification failed; inspect status')

    def delete_exact(self, name, command):
        w = self.winreg
        try:
            with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0,
                           w.KEY_QUERY_VALUE | w.KEY_SET_VALUE) as key:
                try:
                    current = w.QueryValueEx(key, name)
                except FileNotFoundError:
                    return
                if current != (command, w.REG_SZ):
                    raise RuntimeError('Startup value changed; nothing was removed')
                w.DeleteValue(key, name)
        except FileNotFoundError:
            return


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _absolute_path(value, *, directory=False, allow_resolve=False):
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or any(ord(c) < 32 for c in raw):
        raise ValueError('Startup paths must be nonempty and contain no control characters')
    if any(c in raw for c in ['"', '%', '\x7f']):
        raise ValueError('Startup paths cannot contain quotes or environment expansion tokens')
    path = Path(raw)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Startup requires explicit absolute paths without traversal')
    if os.name == 'nt':
        if len(path.drive) != 2 or path.drive[1] != ':':
            raise ValueError('Startup paths require a local Windows drive, not UNC/device paths')
        for part in path.parts[1:]:
            if ':' in part or part.endswith((' ', '.')) or '~' in part:
                raise ValueError('Startup paths cannot use streams or ambiguous Windows aliases')
    if allow_resolve:
        path = path.resolve(strict=True)  # only the currently running interpreter
    for candidate in [path, *path.parents]:
        if linklike(candidate):
            raise ValueError('Startup paths cannot contain symlinks or reparse points')
    info = path.stat()
    if directory and not stat.S_ISDIR(info.st_mode):
        raise ValueError('Startup state must be an existing directory')
    if not directory and not stat.S_ISREG(info.st_mode):
        raise ValueError('Startup executable and launcher must be regular files')
    return path


def _state_path(state):
    return _absolute_path(state, directory=True)


def _value_name(state):
    identity = os.path.normcase(str(state))
    return 'AsterWorkstation-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]


def _windows_command(argv):
    if any(not isinstance(arg, str) or '\x00' in arg or '\r' in arg or '\n' in arg for arg in argv):
        raise ValueError('Invalid startup argument')
    command = subprocess.list2cmdline(argv)
    # Run values are documented as limited to 260 characters. Count UTF-16
    # units conservatively; never truncate a executable, script, or state path.
    if len(command.encode('utf-16-le')) // 2 > MAX_COMMAND_UNITS:
        raise ValueError('Startup command exceeds the Windows Run 260-character limit; use shorter paths')
    return command


def _runtime(state):
    executable = _absolute_path(sys.executable, allow_resolve=True)
    if os.name == 'nt' and executable.name.lower() not in {'python.exe', 'pythonw.exe'}:
        raise ValueError('Startup supports only the running Python interpreter')
    checkout = _absolute_path(CHECKOUT, directory=True)
    launcher = _absolute_path(checkout / 'launch_aster.py')
    _absolute_path(checkout / 'aster', directory=True)
    _absolute_path(checkout / 'aster' / '__init__.py')
    argv = [str(executable), '-I', '-S', '-B', str(launcher), '--state', str(state)]
    return {'executable': str(executable), 'checkout': str(checkout),
            'launcher': str(launcher), 'state': str(state), 'argv': argv,
            'command': _windows_command(argv),
            'launcher_sha256': hashlib.sha256(launcher.read_bytes()).hexdigest()}


def _receipt_path(state):
    return state / RECEIPT_NAME


def _read_receipt(state):
    path = _receipt_path(state)
    if linklike(path):
        raise ValueError('Startup receipt cannot be a symlink or reparse point')
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_RECEIPT_BYTES:
            raise ValueError('Startup receipt must be a bounded single-link regular file')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    except FileNotFoundError:
        return None, None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_RECEIPT_BYTES:
            raise ValueError('Startup receipt must be a bounded single-link regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
    finally:
        os.close(fd)
    try:
        receipt = json.loads(raw.decode('utf-8'))
        expected_keys = {'schema', 'destination', 'value_name', 'runtime'}
        if not isinstance(receipt, dict) or set(receipt) != expected_keys:
            raise ValueError('Invalid startup receipt fields')
        runtime = receipt['runtime']
        if (receipt['schema'] != 1 or receipt['destination'] != 'HKCU\\' + RUN_KEY
                or receipt['value_name'] != _value_name(state) or not isinstance(runtime, dict)
                or runtime.get('state') != str(state)):
            raise ValueError('Startup receipt does not belong to this state')
        if set(runtime) != {'executable', 'checkout', 'launcher', 'state', 'argv', 'command', 'launcher_sha256'}:
            raise ValueError('Invalid startup receipt runtime')
        for key in ('executable', 'checkout', 'launcher', 'state', 'command', 'launcher_sha256'):
            if not isinstance(runtime[key], str) or not runtime[key]:
                raise ValueError('Invalid startup receipt text')
        if not Path(runtime['executable']).is_absolute() or not Path(runtime['checkout']).is_absolute():
            raise ValueError('Startup receipt paths must be absolute')
        if str(Path(runtime['checkout']) / 'launch_aster.py') != runtime['launcher']:
            raise ValueError('Startup receipt has an unexpected launcher')
        expected_argv = [runtime['executable'], '-I', '-S', '-B', runtime['launcher'], '--state', str(state)]
        if runtime['argv'] != expected_argv or runtime['command'] != _windows_command(expected_argv):
            raise ValueError('Startup receipt has an unexpected command')
    except (UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ValueError('Invalid startup ownership receipt; leave the Run value untouched') from exc
    return receipt, raw


def _backend(registry):
    return registry if registry is not None else (WindowsRegistry() if os.name == 'nt' else None)


def _observed(current):
    if current is None:
        return None
    # Conflict data may have a foreign registry type; keep status JSON-safe.
    data = current.data if isinstance(current.data, (str, int)) else repr(current.data)
    return {'kind': current.kind, 'data': data}


def plan(state, *, action='enable', registry=None):
    """Read-only review plan. No state creation or registry writes happen here."""
    if action not in {'enable', 'disable'}:
        raise ValueError('Startup action must be enable or disable')
    state = _state_path(state)
    receipt, raw = _read_receipt(state)
    backend = _backend(registry)
    name = _value_name(state)
    current = backend.read(name) if backend is not None else None
    runtime = receipt['runtime'] if action == 'disable' and receipt else _runtime(state)
    if backend is None:
        registration, reason = 'unsupported_platform', 'Registration is available only on Windows'
    elif current is None:
        registration = 'pending_or_missing' if receipt else 'disabled'
        reason = None
    elif receipt is None:
        registration, reason = 'foreign_value', 'An unowned Run value exists; it will not be overwritten or removed'
    elif current != RegistryValue(receipt['runtime']['command']):
        registration, reason = 'modified_value', 'The owned Run value was modified; it will not be overwritten or removed'
    else:
        registration, reason = 'enabled', None
    if action == 'enable' and receipt and receipt['runtime'] != runtime and reason is None:
        reason = 'Existing ownership receipt uses a different launch plan; disable it before enabling the new plan'
    result = {'action': action, 'dry_run': True, 'supported': backend is not None,
              'destination': 'HKCU\\' + RUN_KEY, 'value_name': name,
              'registry_type': 'REG_SZ', 'runtime': runtime,
              'receipt': str(_receipt_path(state)), 'receipt_present': receipt is not None,
              'receipt_sha256': hashlib.sha256(raw).hexdigest() if raw else None,
              'observed_value': _observed(current), 'status': registration,
              'can_apply': reason is None, 'blocked_reason': reason,
              'trigger': 'Current user logon only; Windows must boot and this user must sign in',
              'scope': 'No service, scheduled task, administrator change, credentials, automatic login, or BIOS change',
              'concurrency': 'Cooperating Aster processes only; not a hostile same-user security boundary'}
    result['plan_digest'] = _digest(result)
    return result


def status(state, *, registry=None):
    """Report the owned registration read-only, including foreign-value conflicts."""
    return plan(state, action='disable', registry=registry)


@contextmanager
def _mutation_lock(state):
    path = state / LOCK_NAME
    if linklike(path):
        raise ValueError('Startup lock cannot be a symlink or reparse point')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Startup lock must be a regular single-link file')
        try:
            lock_state(fd)
        except OSError as exc:
            raise RuntimeError('Another Aster startup operation is active') from exc
        yield
    finally:
        os.close(fd)


def _write_receipt(state, receipt):
    data = (json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()
    if len(data) > MAX_RECEIPT_BYTES:
        raise ValueError('Startup receipt exceeds size limit')
    fd = os.open(_receipt_path(state), os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _remove_receipt_exact(state, expected_raw):
    _, current_raw = _read_receipt(state)
    if current_raw != expected_raw:
        raise RuntimeError('Startup receipt changed; it was not removed')
    if current_raw is not None:
        _receipt_path(state).unlink()


def _apply(state, action, reviewed_plan_digest, confirm, registry):
    if not isinstance(reviewed_plan_digest, str) or not callable(confirm):
        raise ValueError('A reviewed plan digest and fresh interactive confirmation are required')
    backend = _backend(registry)
    review = plan(state, action=action, registry=backend)
    if reviewed_plan_digest != review['plan_digest']:
        raise ValueError('Startup plan changed; review a fresh plan before continuing')
    if not review['can_apply']:
        raise ValueError(review['blocked_reason'])
    # The UI must display this exact plan and solicit a new owner decision.
    # There is deliberately no --yes/--approve environment variable shortcut.
    if confirm(review) is not True:
        return {**review, 'status': 'cancelled', 'changed': False}
    state = _state_path(state)
    with _mutation_lock(state):
        checked = plan(state, action=action, registry=backend)
        if checked['plan_digest'] != review['plan_digest']:
            raise ValueError('Startup plan changed during confirmation; nothing was applied')
        receipt, raw = _read_receipt(state)
        name, command = review['value_name'], review['runtime']['command']
        changed = False
        if action == 'enable':
            if receipt is None:
                receipt = {'schema': 1, 'destination': review['destination'],
                           'value_name': name, 'runtime': review['runtime']}
                # Journal intent first. A crash leaves a visible recoverable
                # pending receipt, never an untracked registration.
                _write_receipt(state, receipt)
            current = backend.read(name)
            if current is None:
                backend.create(name, command)
                changed = True
            elif current != RegistryValue(command):
                raise RuntimeError('Startup value changed; nothing was overwritten')
            if backend.read(name) != RegistryValue(command):
                raise RuntimeError('Startup registration verification failed; inspect status')
        else:
            if receipt is not None:
                backend.delete_exact(name, command)
                if backend.read(name) is not None:
                    raise RuntimeError('Startup value still exists; ownership receipt retained')
                _remove_receipt_exact(state, raw)
                changed = True
    return {**review, 'dry_run': False, 'changed': changed,
            'status': 'enabled' if action == 'enable' else 'disabled'}


def enable(state, *, reviewed_plan_digest, confirm, registry=None):
    return _apply(state, 'enable', reviewed_plan_digest, confirm, registry)


def disable(state, *, reviewed_plan_digest, confirm, registry=None):
    return _apply(state, 'disable', reviewed_plan_digest, confirm, registry)
