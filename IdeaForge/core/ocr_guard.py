"""Private Windows Job guard for the optional local OCR worker.

No image decoder, OCR package, native library or subprocess is loaded at import.
Requires Windows 10+ and a parent outside any Job; there is no breakaway fallback.
The 512 MiB limit is aggregate committed virtual memory, not an RSS promise.
This is a resource guard for a trusted, hash-pinned worker, not a security sandbox.
Win32 lifecycle and recognition qualification are UNRUN until separately cleared.

Primary API references:
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw
https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information
https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject
"""
from __future__ import annotations

import ctypes
import hashlib
import math
import ntpath
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Mapping

JOB_MEMORY_BYTES = 512 * 1024 * 1024
MAX_STDOUT_BYTES = 262144
MAX_STDERR_BYTES = 16384
MAX_TIMEOUT_SECONDS = 30.0
REAP_SECONDS = 2.0
MAX_PIN_FILES = 1024
MAX_PIN_BYTES = 256 * 1024 * 1024
_UNCONFIRMED_IO: list[object] = []
_BROKEN_GUARD = False
_READ_CHUNK = 4096
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DEVICES = re.compile(r"(?:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])\Z", re.I)
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


class GuardError(RuntimeError):
    """Controlled guard failure; messages never include worker output or paths."""


@dataclass(frozen=True)
class GuardResult:
    stdout: bytes
    stderr: bytes
    exit_code: int
    elapsed_ms: int
    peak_job_memory_bytes: int


@dataclass(frozen=True)
class _Spec:
    executable: str
    worker: str
    request: str
    cwd: str
    command: str
    environment_block: str
    hashes: dict[str, str]
    paths: dict[str, str]


def _text(value: object, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise GuardError("invalid-argument")
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise GuardError("invalid-argument")
    try:
        value.encode("utf-16-le", errors="strict")
    except UnicodeError as exc:
        raise GuardError("invalid-argument") from exc
    return value


def _local_absolute(value: object) -> str:
    if not isinstance(value, (str, Path)):
        raise GuardError("invalid-path")
    raw = _text(str(value))
    normalized = raw.replace("/", "\\")
    path = PureWindowsPath(normalized)
    if (not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive)
            or normalized.startswith("\\") or ":" in normalized[2:]):
        raise GuardError("nonlocal-path")
    # Check raw components before pathlib can erase "." components.
    parts = normalized[3:].split("\\")
    if not parts or any(not p or p in (".", "..") or p.endswith((".", " "))
                        or _DEVICES.fullmatch(p.split(".", 1)[0]) for p in parts):
        raise GuardError("invalid-path")
    if any(any(c in p for c in '<>"|?*') for p in parts):
        raise GuardError("invalid-path")
    return str(path)


def _key(path: str) -> str:
    return ntpath.normcase(path)


def _validate_spec(executable: Path, args: list[str], cwd: Path,
                   environment: dict[str, str],
                   expected_sha256: Mapping[str | Path, str]) -> _Spec:
    exe = _local_absolute(executable)
    directory = _local_absolute(cwd)
    if not exe.lower().endswith(".exe"):
        raise GuardError("invalid-executable")
    if (type(args) is not list or len(args) != 5 or args[:3] != ["-I", "-S", "-B"]
            or any(not isinstance(a, str) for a in args)):
        raise GuardError("invalid-worker-command")
    worker = _local_absolute(args[3])
    request = _local_absolute(args[4])
    if not worker.lower().endswith(".py") or not request.lower().endswith(".json"):
        raise GuardError("invalid-worker-command")
    if _key(ntpath.dirname(request)) != _key(directory):
        raise GuardError("request-outside-cwd")
    names = {_key(exe), _key(worker), _key(request)}
    if (len(names) != 3 or not isinstance(expected_sha256, Mapping)
            or not 3 <= len(expected_sha256) <= MAX_PIN_FILES):
        raise GuardError("invalid-pins")
    hashes: dict[str, str] = {}
    paths: dict[str, str] = {}
    for path, digest in expected_sha256.items():
        actual_path = _local_absolute(path)
        name = _key(actual_path)
        if name in hashes or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise GuardError("invalid-pins")
        hashes[name] = digest
        paths[name] = actual_path
    if not names.issubset(hashes):
        raise GuardError("invalid-pins")
    if type(environment) is not dict or not 1 <= len(environment) <= 64:
        raise GuardError("invalid-environment")
    ordered: dict[str, tuple[str, str]] = {}
    for name, value in environment.items():
        if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
            raise GuardError("invalid-environment")
        if name.upper() in ordered or name.upper().startswith("PYTHON"):
            raise GuardError("invalid-environment")
        ordered[name.upper()] = (name, _text(value, maximum=8192))
    if any(ordered.get(name, ("", ""))[1] != "1"
           for name in ("OMP_THREAD_LIMIT", "OMP_NUM_THREADS")):
        raise GuardError("thread-limit-required")
    if not ordered.get("SYSTEMROOT", ("", ""))[1]:
        raise GuardError("systemroot-required")
    env = "\0".join(name + "=" + value for name, value in
                    (ordered[k] for k in sorted(ordered))) + "\0\0"
    command = subprocess.list2cmdline([exe, "-I", "-S", "-B", worker, request])
    if len(env.encode("utf-16-le")) > 32768 or len(command.encode("utf-16-le")) > 32760:
        raise GuardError("command-or-environment-limit")
    # Preserve the exact launch spellings, including on case-sensitive NTFS dirs.
    paths.update({_key(exe): exe, _key(worker): worker, _key(request): request})
    return _Spec(exe, worker, request, directory, command, env, hashes, paths)


def _validate_limits(timeout_seconds: float, stdout_limit: int, stderr_limit: int,
                     cancel: threading.Event | None) -> None:
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (float, int))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise GuardError("invalid-timeout")
    if (type(stdout_limit) is not int or not 1 <= stdout_limit <= MAX_STDOUT_BYTES
            or type(stderr_limit) is not int or not 1 <= stderr_limit <= MAX_STDERR_BYTES):
        raise GuardError("invalid-output-limit")
    if cancel is not None and not isinstance(cancel, threading.Event):
        raise GuardError("invalid-cancellation")


def _execute(session, *, timeout_seconds: float, stdout_limit: int,
             stderr_limit: int, cancel: threading.Event | None,
             clock=time.monotonic, sleep=time.sleep) -> GuardResult:
    """Backend-independent lifecycle; fake sessions exercise this without native work."""
    global _BROKEN_GUARD
    started = clock()
    deadline = started + timeout_seconds
    outputs = [bytearray(), bytearray()]
    peak = 0
    completed = False

    def checkpoint() -> None:
        if cancel is not None and cancel.is_set():
            raise GuardError("cancelled")
        if clock() >= deadline:
            raise GuardError("timeout")

    try:
        checkpoint()
        session.prepare(deadline, clock, checkpoint)
        checkpoint()
        session.create_suspended()
        checkpoint()
        session.verify_job()
        # Resume only a newly created suspended primary thread (suspend count exactly1).
        if session.resume() != 1:
            raise GuardError("unexpected-suspend-count")
        session.close_child_pipe_handles()
        while True:
            checkpoint()
            for index, limit in enumerate((stdout_limit, stderr_limit)):
                chunk = session.read_available(index)
                if not isinstance(chunk, bytes) or len(chunk) > _READ_CHUNK:
                    raise GuardError("invalid-pipe-result")
                if len(outputs[index]) + len(chunk) > limit:
                    raise GuardError("stdout-limit" if index == 0 else "stderr-limit")
                outputs[index].extend(chunk)
            current_peak = session.peak_memory()
            if type(current_peak) is not int or not 0 <= current_peak <= JOB_MEMORY_BYTES:
                raise GuardError("job-memory-limit")
            peak = max(peak, current_peak)
            # The worker exiting is insufficient: its native descendant must also exit.
            if session.active_processes() == 0 and session.pipes_finished():
                if not session.worker_exited():
                    raise GuardError("inconsistent-job-state")
                code = session.exit_code()
                if type(code) is not int or not 0 <= code <= 0xFFFFFFFF:
                    raise GuardError("invalid-exit-code")
                completed = True
                return GuardResult(bytes(outputs[0]), bytes(outputs[1]), code,
                                   max(0, math.ceil((clock() - started) * 1000)), peak)
            sleep(0.005)
    finally:
        # Never enumerate/kill global process names. This session owns exactly one
        # Job and, only for failed creation/assignment, its returned process handle.
        try:
            if not completed:
                session.abort_and_reap(clock=clock, sleep=sleep)
        except BaseException:
            _BROKEN_GUARD = True
            raise
        finally:
            try:
                session.close()
            except BaseException:
                _BROKEN_GUARD = True
                raise


def run_guarded(executable: Path, args: list[str], *, cwd: Path,
                environment: dict[str, str], timeout_seconds: float,
                expected_sha256: Mapping[str | Path, str],
                stdout_limit: int = MAX_STDOUT_BYTES,
                stderr_limit: int = MAX_STDERR_BYTES,
                cancel: threading.Event | None = None) -> GuardResult:
    """Run one hash-pinned worker and at most one native child in an owned Job.

    Args must be exactly -I -S -B absolute_worker.py absolute_request.json.
    The request is a direct child of cwd; launch-file digests and the caller's
    complete runtime-closure file digests are required (<=1024 files/256 MiB).
    Held file handles deny write/delete; directory handles deny move/delete.
    New files can still be created: caller must compare its closed directory
    manifest before/after and serialize a read-only runtime installation.
    No ambient environment/stdio handles, shell, provider or image decoding.
    A Job does not enforce filesystem access, a disk quota or a CPU thread cap.
    Caller/worker must enforce their own fixed input/output and dependency closure.
    """
    _validate_limits(timeout_seconds, stdout_limit, stderr_limit, cancel)
    spec = _validate_spec(executable, args, cwd, environment, expected_sha256)
    if _BROKEN_GUARD or _UNCONFIRMED_IO:
        raise GuardError("previous-io-cleanup-unconfirmed")
    if sys.platform != "win32":
        raise GuardError("windows10-required")
    if sys.getwindowsversion().major < 10:
        raise GuardError("windows10-required")
    session = _WinSession(spec)
    return _execute(session, timeout_seconds=float(timeout_seconds),
                    stdout_limit=stdout_limit, stderr_limit=stderr_limit, cancel=cancel)


# Fixed-width Windows definitions; no DLL/API call occurs at import.
_DWORD = ctypes.c_uint32
_BOOL = ctypes.c_int32
_HANDLE = ctypes.c_void_p
_SIZE_T = ctypes.c_size_t
_LPVOID = ctypes.c_void_p


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", _DWORD), ("lpSecurityDescriptor", _LPVOID),
                ("bInheritHandle", _BOOL)]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [("cb", _DWORD), ("lpReserved", ctypes.c_wchar_p),
                ("lpDesktop", ctypes.c_wchar_p), ("lpTitle", ctypes.c_wchar_p),
                ("dwX", _DWORD), ("dwY", _DWORD), ("dwXSize", _DWORD), ("dwYSize", _DWORD),
                ("dwXCountChars", _DWORD), ("dwYCountChars", _DWORD), ("dwFillAttribute", _DWORD),
                ("dwFlags", _DWORD), ("wShowWindow", ctypes.c_uint16),
                ("cbReserved2", ctypes.c_uint16), ("lpReserved2", _LPVOID),
                ("hStdInput", _HANDLE), ("hStdOutput", _HANDLE), ("hStdError", _HANDLE)]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", _LPVOID)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", _HANDLE), ("hThread", _HANDLE),
                ("dwProcessId", _DWORD), ("dwThreadId", _DWORD)]


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", _DWORD),
                ("MinimumWorkingSetSize", _SIZE_T), ("MaximumWorkingSetSize", _SIZE_T),
                ("ActiveProcessLimit", _DWORD), ("Affinity", _SIZE_T),
                ("PriorityClass", _DWORD), ("SchedulingClass", _DWORD)]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", _SIZE_T), ("JobMemoryLimit", _SIZE_T),
                ("PeakProcessMemoryUsed", _SIZE_T), ("PeakJobMemoryUsed", _SIZE_T)]


class _ACCOUNTING(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in
                ("TotalUserTime", "TotalKernelTime",
                 "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [
                    ("TotalPageFaultCount", _DWORD), ("TotalProcesses", _DWORD),
                    ("ActiveProcesses", _DWORD), ("TotalTerminatedProcesses", _DWORD)]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", _DWORD), ("dwHighDateTime", _DWORD)]


class _FILE_INFO(ctypes.Structure):
    _fields_ = [("dwFileAttributes", _DWORD), ("ftCreationTime", _FILETIME),
                ("ftLastAccessTime", _FILETIME), ("ftLastWriteTime", _FILETIME),
                ("dwVolumeSerialNumber", _DWORD), ("nFileSizeHigh", _DWORD),
                ("nFileSizeLow", _DWORD), ("nNumberOfLinks", _DWORD),
                ("nFileIndexHigh", _DWORD), ("nFileIndexLow", _DWORD)]


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", _SIZE_T), ("InternalHigh", _SIZE_T),
                ("Offset", _DWORD), ("OffsetHigh", _DWORD), ("hEvent", _HANDLE)]


class _WinAPI:
    def __init__(self):
        # Loading system Kernel32 is confined to an explicitly enabled guard run.
        k = ctypes.WinDLL("kernel32.dll", use_last_error=True, winmode=0x00000800)
        self.k = k
        signatures = {
            "CreateJobObjectW": (_HANDLE, [_LPVOID, ctypes.c_wchar_p]),
            "SetInformationJobObject": (_BOOL, [_HANDLE, ctypes.c_int, _LPVOID, _DWORD]),
            "QueryInformationJobObject": (_BOOL, [_HANDLE, ctypes.c_int, _LPVOID, _DWORD, _LPVOID]),
            "IsProcessInJob": (_BOOL, [_HANDLE, _HANDLE, ctypes.POINTER(_BOOL)]),
            "GetCurrentProcess": (_HANDLE, []),
            "CloseHandle": (_BOOL, [_HANDLE]),
            "TerminateJobObject": (_BOOL, [_HANDLE, ctypes.c_uint]),
            "TerminateProcess": (_BOOL, [_HANDLE, ctypes.c_uint]),
            "WaitForSingleObject": (_DWORD, [_HANDLE, _DWORD]),
            "GetExitCodeProcess": (_BOOL, [_HANDLE, ctypes.POINTER(_DWORD)]),
            "ResumeThread": (_DWORD, [_HANDLE]),
            "CreateProcessW": (_BOOL, [ctypes.c_wchar_p, ctypes.c_wchar_p, _LPVOID, _LPVOID,
                                       _BOOL, _DWORD, _LPVOID, ctypes.c_wchar_p,
                                       _LPVOID, ctypes.POINTER(_PROCESS_INFORMATION)]),
            "InitializeProcThreadAttributeList": (_BOOL, [_LPVOID, _DWORD, _DWORD,
                                                           ctypes.POINTER(_SIZE_T)]),
            "UpdateProcThreadAttribute": (_BOOL, [_LPVOID, _DWORD, _SIZE_T, _LPVOID,
                                                   _SIZE_T, _LPVOID, _LPVOID]),
            "DeleteProcThreadAttributeList": (None, [_LPVOID]),
            "CreateFileW": (_HANDLE, [ctypes.c_wchar_p, _DWORD, _DWORD, _LPVOID,
                                       _DWORD, _DWORD, _HANDLE]),
            "GetFileInformationByHandle": (_BOOL, [_HANDLE, ctypes.POINTER(_FILE_INFO)]),
            "GetDriveTypeW": (_DWORD, [ctypes.c_wchar_p]),
            "ReadFile": (_BOOL, [_HANDLE, _LPVOID, _DWORD, ctypes.POINTER(_DWORD), _LPVOID]),
            "CreateNamedPipeW": (_HANDLE, [ctypes.c_wchar_p, _DWORD, _DWORD, _DWORD,
                                           _DWORD, _DWORD, _DWORD, _LPVOID]),
            "ConnectNamedPipe": (_BOOL, [_HANDLE, _LPVOID]),
            "CreateEventW": (_HANDLE, [_LPVOID, _BOOL, _BOOL, ctypes.c_wchar_p]),
            "ResetEvent": (_BOOL, [_HANDLE]),
            "GetOverlappedResult": (_BOOL, [_HANDLE, ctypes.POINTER(_OVERLAPPED),
                                            ctypes.POINTER(_DWORD), _BOOL]),
            "CancelIoEx": (_BOOL, [_HANDLE, _LPVOID]),
            "CreatePipe": (_BOOL, [ctypes.POINTER(_HANDLE), ctypes.POINTER(_HANDLE), _LPVOID, _DWORD]),
        }
        try:
            for name, (restype, argtypes) in signatures.items():
                fn = getattr(k, name)
                fn.restype, fn.argtypes = restype, argtypes
        except AttributeError as exc:
            raise GuardError("native-api-unavailable") from exc

    @staticmethod
    def fail(code: str) -> GuardError:
        # Error numbers help diagnose resource support without leaking input paths.
        return GuardError(code + ":win32-" + str(ctypes.get_last_error()))

    def check(self, value, code: str):
        if not value:
            raise self.fail(code)
        return value

    def handle(self, value, code: str):
        if value in (None, 0, ctypes.c_void_p(-1).value):
            raise self.fail(code)
        return value


class _Pipe:
    def __init__(self, owner):
        self.owner = owner
        self.server = self.client = self.event = None
        self.pending = self.finished = False
        # Register before any asynchronous I/O can be issued; setup failures must
        # preserve OVERLAPPED storage through cleanup too.
        owner.pipes.append(self)
        self.ov = _OVERLAPPED()
        self.buffer = ctypes.create_string_buffer(_READ_CHUNK)
        api, k = owner.api, owner.api.k
        name = "\\\\.\\pipe\\research-ocr-" + uuid.uuid4().hex
        # Overlapped, inbound, exclusive first instance; reject remote clients.
        self.server = owner.own(api.handle(k.CreateNamedPipeW(
            name, 0x40080001, 0x00000008, 1, 0, _READ_CHUNK, 0, None), "pipe-create"))
        self.event = owner.own(api.handle(k.CreateEventW(None, True, False, None), "pipe-event"))
        self.ov.hEvent = self.event
        if not k.ConnectNamedPipe(self.server, ctypes.byref(self.ov)):
            err = ctypes.get_last_error()
            if err not in (997, 535):  # ERROR_IO_PENDING / ERROR_PIPE_CONNECTED
                raise api.fail("pipe-connect")
            connecting = err == 997
            self.pending = connecting
        else:
            connecting = False
        sa = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
        self.client = owner.own(api.handle(k.CreateFileW(
            name, 0x40000000, 0, ctypes.byref(sa), 3, 0, None), "pipe-client"))
        if connecting:
            if k.WaitForSingleObject(self.event, 1000) != 0:
                raise GuardError("pipe-connect-timeout")
            count = _DWORD()
            api.check(k.GetOverlappedResult(self.server, ctypes.byref(self.ov),
                                           ctypes.byref(count), False), "pipe-connect-result")
            self.pending = False

    def _result(self) -> bytes:
        count = _DWORD()
        k, api = self.owner.api.k, self.owner.api
        if k.GetOverlappedResult(self.server, ctypes.byref(self.ov), ctypes.byref(count), False):
            self.pending = False
            if count.value > _READ_CHUNK:
                raise GuardError("invalid-pipe-count")
            # A successful zero-byte pipe read can follow a zero-byte writer
            # operation; it does not prove the writers closed. Keep reading.
            return self.buffer.raw[:count.value]
        error = ctypes.get_last_error()
        if error == 996:  # ERROR_IO_INCOMPLETE
            return b""
        if error in (109, 232):
            self.pending, self.finished = False, True
            return b""
        raise api.fail("pipe-result")

    def _issue(self) -> bytes:
        k, api = self.owner.api.k, self.owner.api
        api.check(k.ResetEvent(self.event), "pipe-reset")
        self.ov = _OVERLAPPED()
        self.ov.hEvent = self.event
        # ReadFile's byte-count pointer is NULL for an asynchronous handle;
        # GetOverlappedResult supplies the authoritative completion count.
        if k.ReadFile(self.server, self.buffer, _READ_CHUNK, None, ctypes.byref(self.ov)):
            self.pending = True
            return self._result()
        error = ctypes.get_last_error()
        if error == 997:
            self.pending = True
            return b""
        if error in (109, 232):  # ERROR_BROKEN_PIPE / ERROR_NO_DATA
            self.finished = True
            return b""
        raise api.fail("pipe-read")

    def read_available(self) -> bytes:
        if self.finished:
            return b""
        return self._result() if self.pending else self._issue()

    def cancel_and_wait(self) -> None:
        if not self.pending:
            return
        k = self.owner.api.k
        # Keep OVERLAPPED and its buffer alive until cancellation is acknowledged.
        if not k.CancelIoEx(self.server, ctypes.byref(self.ov)):
            if ctypes.get_last_error() != 1168:  # ERROR_NOT_FOUND: already completed.
                raise self.owner.api.fail("pipe-cancel")
        if k.WaitForSingleObject(self.event, 2000) != 0:
            raise GuardError("pipe-cancel-unconfirmed")
        count = _DWORD()
        if not k.GetOverlappedResult(self.server, ctypes.byref(self.ov), ctypes.byref(count), False):
            if ctypes.get_last_error() not in (995, 109, 232):  # OPERATION_ABORTED / broken/closed
                raise self.owner.api.fail("pipe-cancel-result")
        self.pending = False


class _WinSession:
    def __init__(self, spec: _Spec):
        self.spec = spec
        self.api = _WinAPI()
        self.handles: list[int] = []
        self.job = None
        self.pi = _PROCESS_INFORMATION()
        self.attributes = None
        self.attribute_initialized = False
        self.pipes: list[_Pipe] = []
        self.inherited: list[int] = []

    def own(self, handle):
        self.handles.append(handle)
        return handle

    def _close_one(self, handle) -> None:
        if handle in self.handles:
            self.api.check(self.api.k.CloseHandle(handle), "close-handle")
            self.handles.remove(handle)

    def _pin(self, path: str, *, directory: bool, maximum: int | None = None) -> int:
        k, api = self.api.k, self.api
        # Read/write directory sharing permits ordinary filesystem work but denies
        # deletion/renaming ancestors. Files deny write/delete for the whole run.
        access, sharing = (0, 3) if directory else (0x80000000, 1)
        flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT / BACKUP
        handle = self.own(api.handle(k.CreateFileW(
            path, access, sharing, None, 3, flags, None), "pin-open"))
        info = _FILE_INFO()
        api.check(k.GetFileInformationByHandle(handle, ctypes.byref(info)), "pin-information")
        if info.dwFileAttributes & 0x400:
            raise GuardError("reparse-pin")
        if bool(info.dwFileAttributes & 0x10) != directory:
            raise GuardError("pin-type")
        if not directory:
            size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
            if info.nNumberOfLinks != 1 or size < 1 or maximum is None or size > maximum:
                raise GuardError("pin-size-or-links")
        return handle

    def prepare(self, deadline, clock, checkpoint) -> None:
        k, api = self.api.k, self.api
        member = _BOOL()
        api.check(k.IsProcessInJob(k.GetCurrentProcess(), None, ctypes.byref(member)),
                  "parent-job-query")
        if member.value:
            raise GuardError("nested-job-refused")
        directories: dict[str, str] = {}
        for target in (*self.spec.paths.values(), self.spec.cwd):
            path = PureWindowsPath(target)
            if k.GetDriveTypeW(path.anchor) != 3:  # DRIVE_FIXED, excludes network/removable.
                raise GuardError("nonfixed-drive")
            # Include the fixed-volume root to pin ancestor identities as well.
            for parent in reversed(path.parents):
                directories[_key(str(parent))] = str(parent)
        directories[_key(self.spec.cwd)] = self.spec.cwd
        for path in directories.values():
            checkpoint()
            self._pin(path, directory=True)
        total_pinned = 0
        for path in self.spec.paths.values():
            maximum = (8192 if _key(path) == _key(self.spec.request) else
                       262144 if _key(path) == _key(self.spec.worker) else
                       128 * 1024 * 1024)
            checkpoint()
            handle = self._pin(path, directory=False, maximum=maximum)
            digest, buffer, count = hashlib.sha256(), ctypes.create_string_buffer(65536), _DWORD()
            total = 0
            while True:
                checkpoint()
                api.check(k.ReadFile(handle, buffer, len(buffer), ctypes.byref(count), None),
                          "pin-read")
                if count.value == 0:
                    break
                total += count.value
                if total > maximum or total_pinned + total > MAX_PIN_BYTES:
                    raise GuardError("pin-size")
                digest.update(buffer.raw[:count.value])
            total_pinned += total
            if digest.hexdigest() != self.spec.hashes[_key(path)]:
                raise GuardError("pin-hash-mismatch")
        self.job = self.own(api.handle(k.CreateJobObjectW(None, None), "job-create"))
        limits = _EXTENDED_LIMIT()
        # ACTIVE_PROCESS + PROCESS_MEMORY + JOB_MEMORY + KILL_ON_JOB_CLOSE;
        # neither BREAKAWAY_OK nor SILENT_BREAKAWAY_OK is set.
        limits.BasicLimitInformation.LimitFlags = 0x00002308
        limits.BasicLimitInformation.ActiveProcessLimit = 2
        limits.ProcessMemoryLimit = limits.JobMemoryLimit = JOB_MEMORY_BYTES
        api.check(k.SetInformationJobObject(self.job, 9, ctypes.byref(limits),
                                            ctypes.sizeof(limits)), "job-limits")
        observed = self._limits()
        if (observed.BasicLimitInformation.LimitFlags != limits.BasicLimitInformation.LimitFlags
                or observed.BasicLimitInformation.ActiveProcessLimit != 2
                or observed.JobMemoryLimit != JOB_MEMORY_BYTES
                or observed.ProcessMemoryLimit != JOB_MEMORY_BYTES):
            raise GuardError("job-limits-unconfirmed")
        for _ in range(2):
            checkpoint()
            _Pipe(self)
        # Anonymous read-only stdin pipe whose writer is already closed (EOF).
        sa = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, True)
        stdin_read, stdin_write = _HANDLE(), _HANDLE()
        api.check(k.CreatePipe(ctypes.byref(stdin_read), ctypes.byref(stdin_write),
                               ctypes.byref(sa), 0), "stdin-create")
        self.own(stdin_read.value)
        self.own(stdin_write.value)
        self._close_one(stdin_write.value)
        self.inherited = [stdin_read.value, self.pipes[0].client, self.pipes[1].client]
        size = _SIZE_T()
        ctypes.set_last_error(0)
        if k.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size)):
            raise GuardError("attribute-size-unexpected")
        if ctypes.get_last_error() != 122 or not 1 <= size.value <= 65536:
            raise GuardError("attribute-size-unavailable")
        self.attributes = ctypes.create_string_buffer(size.value)
        api.check(k.InitializeProcThreadAttributeList(self.attributes, 2, 0,
                                                      ctypes.byref(size)), "attribute-init")
        self.attribute_initialized = True
        self.inherit_array = (_HANDLE * 3)(*self.inherited)
        self.job_array = (_HANDLE * 1)(self.job)
        api.check(k.UpdateProcThreadAttribute(self.attributes, 0, 0x00020002,
                                              self.inherit_array, ctypes.sizeof(self.inherit_array),
                                              None, None), "handle-attribute")
        api.check(k.UpdateProcThreadAttribute(self.attributes, 0, 0x0002000D,
                                              self.job_array, ctypes.sizeof(self.job_array),
                                              None, None), "job-attribute")

    def create_suspended(self) -> None:
        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.dwFlags = 0x101  # STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW
        startup.StartupInfo.wShowWindow = 0  # SW_HIDE
        (startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput,
         startup.StartupInfo.hStdError) = self.inherited
        startup.lpAttributeList = ctypes.cast(self.attributes, _LPVOID)
        command = ctypes.create_unicode_buffer(self.spec.command)
        env = ctypes.create_unicode_buffer(self.spec.environment_block)
        # NO_WINDOW | UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO | SUSPENDED.
        self.api.check(self.api.k.CreateProcessW(
            self.spec.executable, command, None, None, True, 0x08080404,
            env, self.spec.cwd, ctypes.byref(startup), ctypes.byref(self.pi)), "process-create")
        self.own(self.pi.hProcess)
        self.own(self.pi.hThread)

    def verify_job(self) -> None:
        member = _BOOL()
        self.api.check(self.api.k.IsProcessInJob(self.pi.hProcess, self.job, ctypes.byref(member)),
                       "owned-job-query")
        if not member.value or self.active_processes() != 1:
            raise GuardError("owned-job-unconfirmed")
        if self.peak_memory() > JOB_MEMORY_BYTES:
            raise GuardError("startup-memory-limit")

    def resume(self) -> int:
        return int(self.api.k.ResumeThread(self.pi.hThread))

    def close_child_pipe_handles(self) -> None:
        for handle in self.inherited:
            self._close_one(handle)

    def read_available(self, index: int) -> bytes:
        return self.pipes[index].read_available()

    def pipes_finished(self) -> bool:
        return all(pipe.finished for pipe in self.pipes)

    def _limits(self):
        value = _EXTENDED_LIMIT()
        self.api.check(self.api.k.QueryInformationJobObject(
            self.job, 9, ctypes.byref(value), ctypes.sizeof(value), None), "job-query")
        return value

    def peak_memory(self) -> int:
        return int(self._limits().PeakJobMemoryUsed)

    def active_processes(self) -> int:
        value = _ACCOUNTING()
        self.api.check(self.api.k.QueryInformationJobObject(
            self.job, 1, ctypes.byref(value), ctypes.sizeof(value), None), "job-accounting")
        return int(value.ActiveProcesses)

    def worker_exited(self) -> bool:
        result = self.api.k.WaitForSingleObject(self.pi.hProcess, 0)
        if result not in (0, 258):
            raise self.api.fail("process-wait")
        return result == 0

    def exit_code(self) -> int:
        value = _DWORD()
        self.api.check(self.api.k.GetExitCodeProcess(self.pi.hProcess,
                                                    ctypes.byref(value)), "process-exit")
        return int(value.value)

    def abort_and_reap(self, *, clock=time.monotonic, sleep=time.sleep) -> None:
        k, api = self.api.k, self.api
        failure = None
        if self.job:
            if not k.TerminateJobObject(self.job, 0xE0000001):
                failure = api.fail("owned-job-terminate")
        if self.pi.hProcess:
            # Sole returned owned process handle; necessary if a creation/Job
            # verification failure left it outside the Job. Never OpenProcess/PID kill.
            if not k.TerminateProcess(self.pi.hProcess, 0xE0000001):
                # Already exited is acceptable only when the exact handle is signaled.
                if k.WaitForSingleObject(self.pi.hProcess, 0) != 0:
                    failure = api.fail("owned-process-terminate")
            until = clock() + REAP_SECONDS
            while k.WaitForSingleObject(self.pi.hProcess, 0) != 0:
                if clock() >= until:
                    raise GuardError("owned-process-reap-unconfirmed")
                sleep(0.005)
        # Failed limit association may keep accounting active until all returned
        # process/thread references are released. They are signaled before close.
        if self.pi.hProcess:
            self._close_one(self.pi.hThread)
            self._close_one(self.pi.hProcess)
            self.pi.hThread = self.pi.hProcess = None
        if self.job:
            until = clock() + REAP_SECONDS
            while self.active_processes() != 0:
                if clock() >= until:
                    raise GuardError("owned-job-reap-unconfirmed")
                sleep(0.005)
        if failure is not None:
            raise failure

    def close(self) -> None:
        errors = []
        for pipe in self.pipes:
            try:
                pipe.cancel_and_wait()
            except GuardError as exc:
                # CancelIoEx is asynchronous. Preserve its buffers if completion
                # cannot be verified; refuse future launches rather than releasing
                # memory potentially still referenced by an outstanding native I/O.
                _UNCONFIRMED_IO.append(pipe)
                errors.append(exc)
        if self.attribute_initialized:
            self.api.k.DeleteProcThreadAttributeList(self.attributes)
            self.attribute_initialized = False
        # KILL_ON_JOB_CLOSE remains a final owned-only backstop on any failure.
        for handle in list(reversed(self.handles)):
            try:
                self._close_one(handle)
            except GuardError as exc:
                errors.append(exc)
        if errors:
            raise GuardError("owned-handle-cleanup-unconfirmed") from errors[0]
