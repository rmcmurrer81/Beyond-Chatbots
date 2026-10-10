"""Source/mock guard regressions; all execution UNRUN in the authored receipt.

Native tests are separately opt-in and require an approved coordinated window.
They launch only generated private workers, never OCR or personal photographs.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from core import ocr_guard as guard


EXE = r"C:\Runtime\python.exe"
WORKER = r"C:\App\ocr_worker.py"
CWD = r"C:\Private\ocr-scratch"
REQUEST = CWD + r"\request.json"
ENV = {"SystemRoot": r"C:\Windows", "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}
PINS = {EXE: "1" * 64, WORKER: "2" * 64, REQUEST: "3" * 64}


class Clock:
    def __init__(self):
        self.value = 10.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Session:
    def __init__(self, *, active=None, stdout=None, stderr=None, peak=4096, resume=1):
        self.calls = []
        self.active = list(active if active is not None else [0])
        self.output = [list(stdout or []), list(stderr or [])]
        self.peak, self.resume_value = peak, resume
        self.fail_at = None
        self.signaled, self.code = True, 0

    def _call(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise guard.GuardError("mock-" + name)

    def prepare(self, deadline, clock, checkpoint):
        self._call("prepare")
        checkpoint()

    def create_suspended(self):
        self._call("create-suspended")

    def verify_job(self):
        self._call("verify-job")

    def resume(self):
        self._call("resume")
        return self.resume_value

    def close_child_pipe_handles(self):
        self._call("close-child-handles")

    def read_available(self, index):
        self.calls.append("read-" + str(index))
        return self.output[index].pop(0) if self.output[index] else b""

    def pipes_finished(self):
        return not any(self.output)

    def peak_memory(self):
        self.calls.append("peak")
        return self.peak

    def active_processes(self):
        self.calls.append("active")
        return self.active.pop(0) if len(self.active) > 1 else self.active[0]

    def worker_exited(self):
        return self.signaled

    def exit_code(self):
        return self.code

    def abort_and_reap(self, **kwargs):
        self._call("abort-owned-and-reap")

    def close(self):
        self._call("close-owned")


def execute(session, *, timeout=1, out=guard.MAX_STDOUT_BYTES,
            err=guard.MAX_STDERR_BYTES, cancel=None, clock=None):
    clock = clock or Clock()
    return guard._execute(session, timeout_seconds=timeout, stdout_limit=out,
                          stderr_limit=err, cancel=cancel,
                          clock=clock.now, sleep=clock.sleep)


def spec(*, executable=EXE, worker=WORKER, request=REQUEST, cwd=CWD,
         environment=None, pins=None, args=None):
    return guard._validate_spec(executable, args if args is not None else
                                ["-I", "-S", "-B", worker, request],
                                cwd, dict(ENV) if environment is None else environment,
                                dict(PINS) if pins is None else pins)


class GuardArgumentsTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.object(guard, "_BROKEN_GUARD", False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_fixed_isolated_command_and_explicit_environment(self):
        result = spec()
        self.assertEqual(result.executable, EXE)
        self.assertIn("-I -S -B", result.command)
        self.assertTrue(result.environment_block.endswith("\0\0"))
        self.assertNotIn("PYTHONPATH", result.environment_block)

    def test_absolute_local_paths_only(self):
        for bad in ("python.exe", r"C:python.exe", r"\\server\share\python.exe",
                    r"\\?\C:\Runtime\python.exe", r"C:\Runtime\python.exe:stream"):
            with self.subTest(bad=bad), self.assertRaises(guard.GuardError):
                spec(executable=bad)

    def test_raw_traversal_and_ambiguous_windows_components_rejected(self):
        for bad in (r"C:\x\..\python.exe", r"C:\x\.\python.exe",
                    r"C:\x \python.exe", r"C:\x.\python.exe", r"C:\COM0\python.exe",
                    r"C:\LPT9.txt\python.exe", r"C:\x\\python.exe"):
            with self.subTest(bad=bad), self.assertRaises(guard.GuardError):
                spec(executable=bad)

    def test_shell_code_or_module_arguments_are_refused(self):
        for args in (["-c", "print(1)"], ["-I", "-B", WORKER, REQUEST],
                     ["-I", "-S", "-B", "-m", "worker"],
                     ["-I", "-S", "-B", WORKER, REQUEST, "--extra"]):
            with self.subTest(args=args), self.assertRaises(guard.GuardError):
                spec(args=args)

    def test_request_must_be_direct_child_of_cwd(self):
        with self.assertRaisesRegex(guard.GuardError, "request-outside-cwd"):
            spec(request=r"C:\Other\request.json")
        with self.assertRaises(guard.GuardError):
            spec(request=CWD + r"\nested\request.json")

    def test_launch_hashes_are_mandatory_and_lowercase(self):
        for pins in ({EXE: "1" * 64}, {**PINS, WORKER: "A" * 64},
                     {**PINS, REQUEST: "g" * 64}, {**PINS, REQUEST: 3}):
            with self.subTest(pins=pins), self.assertRaises(guard.GuardError):
                spec(pins=pins)

    def test_closure_pins_are_retained_without_case_mangling(self):
        extra = r"C:\Runtime\PIL\_Imaging.PYD"
        result = spec(pins={**PINS, extra: "4" * 64})
        self.assertEqual(result.paths[guard._key(extra)], extra)
        self.assertEqual(set(result.hashes), set(result.paths))
        self.assertEqual(result.paths[guard._key(WORKER)], WORKER)

    def test_case_colliding_pins_and_file_count_overflow_refused(self):
        with self.assertRaises(guard.GuardError):
            spec(pins={**PINS, EXE.lower(): "1" * 64})
        pins = {**PINS, **{rf"C:\Runtime\f{i}.dll": "4" * 64 for i in range(1022)}}
        with self.assertRaises(guard.GuardError):
            spec(pins=pins)

    def test_environment_cannot_smuggle_python_hooks_or_duplicate_names(self):
        for env in ({**ENV, "PYTHONPATH": r"C:\Untrusted"},
                    {**ENV, "systemroot": r"C:\Other"},
                    {**ENV, "BAD=KEY": "x"}, {**ENV, "PATH": "x\nsecret"}):
            with self.subTest(env=env), self.assertRaises(guard.GuardError):
                spec(environment=env)

    def test_one_thread_and_systemroot_are_required(self):
        for env in ({**ENV, "OMP_NUM_THREADS": "2"},
                    {k: v for k, v in ENV.items() if k != "OMP_THREAD_LIMIT"},
                    {**ENV, "SystemRoot": ""}):
            with self.subTest(env=env), self.assertRaises(guard.GuardError):
                spec(environment=env)

    def test_invalid_deadlines_output_limits_and_cancellation(self):
        for timeout in (True, 0, -1, 31, float("nan"), float("inf"), "5"):
            with self.subTest(timeout=timeout), self.assertRaises(guard.GuardError):
                guard._validate_limits(timeout, 100, 100, None)
        for out, err in ((0, 1), (262145, 1), (1, 16385), (True, 1)):
            with self.subTest(out=out, err=err), self.assertRaises(guard.GuardError):
                guard._validate_limits(5, out, err, None)
        with self.assertRaises(guard.GuardError):
            guard._validate_limits(5, 100, 100, object())

    def test_unsupported_platform_never_initializes_native_api(self):
        with patch.object(guard.sys, "platform", "linux"), patch.object(guard, "_WinSession") as native:
            with self.assertRaisesRegex(guard.GuardError, "windows10-required"):
                guard.run_guarded(Path(EXE), ["-I", "-S", "-B", WORKER, REQUEST],
                                  cwd=Path(CWD), environment=dict(ENV), timeout_seconds=5,
                                  expected_sha256=PINS)
            native.assert_not_called()

    def test_unconfirmed_prior_io_refuses_another_launch(self):
        with patch.object(guard, "_UNCONFIRMED_IO", [object()]), patch.object(guard, "_WinSession") as native:
            with self.assertRaisesRegex(guard.GuardError, "previous-io-cleanup-unconfirmed"):
                guard.run_guarded(Path(EXE), ["-I", "-S", "-B", WORKER, REQUEST],
                                  cwd=Path(CWD), environment=dict(ENV), timeout_seconds=5,
                                  expected_sha256=PINS)
            native.assert_not_called()


class GuardLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch.object(guard, "_BROKEN_GUARD", False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_job_is_verified_before_resume_and_handles_closed_on_success(self):
        session = Session(stdout=[b"bounded"], stderr=[b"diagnostic"], peak=16384)
        result = execute(session)
        self.assertEqual(session.calls[:5], ["prepare", "create-suspended", "verify-job",
                                            "resume", "close-child-handles"])
        self.assertEqual((result.stdout, result.stderr, result.exit_code), (b"bounded", b"diagnostic", 0))
        self.assertEqual(result.peak_job_memory_bytes, 16384)
        self.assertNotIn("abort-owned-and-reap", session.calls)
        self.assertEqual(session.calls[-1], "close-owned")

    def test_setup_failure_never_resumes_and_reaps_owned_resources(self):
        for stage in ("prepare", "create-suspended", "verify-job"):
            session = Session()
            session.fail_at = stage
            with self.subTest(stage=stage), self.assertRaises(guard.GuardError):
                execute(session)
            self.assertNotIn("resume", session.calls)
            self.assertEqual(session.calls[-2:], ["abort-owned-and-reap", "close-owned"])

    def test_unexpected_suspend_count_aborts(self):
        for count in (0, 2, 0xFFFFFFFF):
            session = Session(resume=count)
            with self.subTest(count=count), self.assertRaisesRegex(guard.GuardError, "suspend-count"):
                execute(session)
            self.assertIn("abort-owned-and-reap", session.calls)

    def test_both_pipes_are_drained_while_descendant_remains_active(self):
        session = Session(active=[1, 1, 0], stdout=[b"a", b"b", b"c"], stderr=[b"1", b"2", b"3"])
        result = execute(session)
        self.assertEqual(result.stdout, b"abc")
        self.assertEqual(result.stderr, b"123")
        self.assertEqual(session.calls.count("read-0"), 3)
        self.assertEqual(session.calls.count("read-1"), 3)

    def test_stdout_limit_stops_before_unbounded_accumulation(self):
        session = Session(stdout=[b"abcd", b"e"], active=[1, 0])
        with self.assertRaisesRegex(guard.GuardError, "stdout-limit"):
            execute(session, out=4)
        self.assertEqual(session.calls[-2:], ["abort-owned-and-reap", "close-owned"])

    def test_stderr_limit_independent_of_stdout(self):
        session = Session(stderr=[b"abcde"])
        with self.assertRaisesRegex(guard.GuardError, "stderr-limit"):
            execute(session, err=4)
        self.assertIn("abort-owned-and-reap", session.calls)

    def test_timeout_waits_for_descendant_and_terminates_only_owned_job(self):
        session = Session(active=[1])
        with self.assertRaisesRegex(guard.GuardError, "timeout"):
            execute(session, timeout=0.02)
        self.assertEqual(session.calls.count("abort-owned-and-reap"), 1)
        self.assertEqual(session.calls[-1], "close-owned")

    def test_preexisting_cancellation_prevents_any_setup(self):
        event = threading.Event()
        event.set()
        session = Session()
        with self.assertRaisesRegex(guard.GuardError, "cancelled"):
            execute(session, cancel=event)
        self.assertNotIn("prepare", session.calls)
        self.assertEqual(session.calls, ["abort-owned-and-reap", "close-owned"])

    def test_memory_accounting_over_cap_and_malformed_chunks_fail_closed(self):
        for session in (Session(peak=guard.JOB_MEMORY_BYTES + 1),
                        Session(peak=-1), Session(stdout=["text"]), Session(stdout=[b"x" * 4097])):
            with self.subTest(session=session), self.assertRaises(guard.GuardError):
                execute(session)
            self.assertIn("abort-owned-and-reap", session.calls)

    def test_empty_job_requires_signaled_owned_process_and_valid_exit_code(self):
        for session in (Session(), Session()):
            session.signaled = False
            with self.assertRaisesRegex(guard.GuardError, "inconsistent-job-state"):
                execute(session)
        for code in (-1, True, 0x100000000):
            session = Session()
            session.code = code
            with self.subTest(code=code), self.assertRaisesRegex(guard.GuardError, "invalid-exit-code"):
                execute(session)

    def test_cleanup_failure_is_reported_and_handles_still_close(self):
        session = Session(active=[1])
        session.fail_at = "abort-owned-and-reap"
        with self.assertRaisesRegex(guard.GuardError, "mock-abort-owned-and-reap"):
            execute(session, timeout=0.01)
        self.assertEqual(session.calls[-1], "close-owned")
        self.assertTrue(guard._BROKEN_GUARD)

    def test_uint32_exit_status_is_preserved_for_caller_validation(self):
        session = Session()
        session.code = 0xC0000005
        self.assertEqual(execute(session).exit_code, 0xC0000005)


class NativeLifecycleSourceTests(unittest.TestCase):
    def test_cleanup_targets_returned_handles_and_waits_for_job_zero(self):
        session = guard._WinSession.__new__(guard._WinSession)
        kernel = Mock()
        kernel.TerminateJobObject.return_value = 1
        kernel.TerminateProcess.return_value = 1
        kernel.WaitForSingleObject.return_value = 0
        session.api = Mock(k=kernel)
        session.job = 123
        session.handles = [123, 456, 789]
        session.pi = guard._PROCESS_INFORMATION()
        session.pi.hProcess = 456
        session.pi.hThread = 789
        session.active_processes = Mock(side_effect=[1, 0])
        clock = Clock()
        session.abort_and_reap(clock=clock.now, sleep=clock.sleep)
        kernel.TerminateJobObject.assert_called_once_with(123, 0xE0000001)
        kernel.TerminateProcess.assert_called_once_with(456, 0xE0000001)
        self.assertEqual(session.active_processes.call_count, 2)
        self.assertEqual(session.pi.hProcess, None)
        self.assertEqual(session.handles, [123])

    def test_job_not_empty_after_termination_is_explicit_failure(self):
        session = guard._WinSession.__new__(guard._WinSession)
        kernel = Mock()
        kernel.TerminateJobObject.return_value = 1
        session.api = Mock(k=kernel)
        session.job = 123
        session.pi = guard._PROCESS_INFORMATION()
        session.active_processes = Mock(return_value=1)
        clock = Clock()
        with self.assertRaisesRegex(guard.GuardError, "owned-job-reap-unconfirmed"):
            session.abort_and_reap(clock=clock.now, sleep=clock.sleep)

    def test_creation_uses_explicit_application_suspend_job_attributes_no_shell(self):
        session = guard._WinSession.__new__(guard._WinSession)
        session.spec = spec()
        session.attributes = ctypes.create_string_buffer(128)
        session.pi = guard._PROCESS_INFORMATION()
        session.inherited = [1, 2, 3]
        session.handles = []
        kernel = Mock()

        def create(app, command, procsa, threadsa, inherit, flags, env, cwd, startup, pi):
            self.assertEqual(app, EXE)
            self.assertTrue(inherit)
            self.assertEqual(flags, 0x08080404)
            self.assertEqual(cwd, CWD)
            self.assertEqual(startup._obj.StartupInfo.cb, ctypes.sizeof(guard._STARTUPINFOEXW))
            self.assertEqual(startup._obj.StartupInfo.dwFlags, 0x101)
            self.assertEqual(startup._obj.StartupInfo.hStdInput, 1)
            self.assertEqual(startup._obj.StartupInfo.hStdOutput, 2)
            self.assertEqual(startup._obj.StartupInfo.hStdError, 3)
            pi._obj.hProcess, pi._obj.hThread = 100, 101
            return 1

        kernel.CreateProcessW.side_effect = create
        api = Mock(k=kernel)
        api.check.side_effect = lambda value, code: value
        session.api = api
        session.create_suspended()
        self.assertEqual(session.handles, [100, 101])

    def test_native_file_pins_deny_write_delete_and_refuse_aliases(self):
        for attributes, links, size, directory, expected in (
                (0, 1, 123, False, True),
                (0x400, 1, 123, False, False),
                (0, 2, 123, False, False),
                (0, 1, 0, False, False),
                (0, 1, 2048, False, False),
                (0x10, 3, 0, True, True),
                (0x410, 3, 0, True, False)):
            with self.subTest(attributes=attributes, links=links, directory=directory):
                session = guard._WinSession.__new__(guard._WinSession)
                session.handles = []
                kernel = Mock()
                kernel.CreateFileW.return_value = 77

                def information(handle, out):
                    out._obj.dwFileAttributes = attributes
                    out._obj.nNumberOfLinks = links
                    out._obj.nFileSizeLow = size
                    return 1

                kernel.GetFileInformationByHandle.side_effect = information
                api = Mock(k=kernel)
                api.check.side_effect = lambda value, code: value
                api.handle.side_effect = lambda value, code: value
                session.api = api
                if expected:
                    self.assertEqual(session._pin(WORKER, directory=directory, maximum=1024), 77)
                else:
                    with self.assertRaises(guard.GuardError):
                        session._pin(WORKER, directory=directory, maximum=1024)
                args = kernel.CreateFileW.call_args.args
                self.assertEqual(args[1:3], (0, 3) if directory else (0x80000000, 1))
                self.assertEqual(args[5] & 0x00200000, 0x00200000)
                self.assertEqual(session.handles, [77])

    def test_fixed_width_x64_structure_layouts(self):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            self.skipTest("x64 layout assertion; native x86 qualification separate")
        self.assertEqual(ctypes.sizeof(guard._STARTUPINFOW), 104)
        self.assertEqual(ctypes.sizeof(guard._STARTUPINFOEXW), 112)
        self.assertEqual(ctypes.sizeof(guard._EXTENDED_LIMIT), 144)
        self.assertEqual(ctypes.sizeof(guard._ACCOUNTING), 48)
        self.assertEqual(ctypes.sizeof(guard._OVERLAPPED), 32)
        self.assertEqual(guard._EXTENDED_LIMIT.JobMemoryLimit.offset, 120)



class PipeCompletionTests(unittest.TestCase):
    def make_pipe(self, *, immediate=True, chunks=None):
        pipe = guard._Pipe.__new__(guard._Pipe)
        pipe.server, pipe.event = 11, 12
        pipe.pending, pipe.finished = False, False
        pipe.ov = guard._OVERLAPPED()
        pipe.buffer = ctypes.create_string_buffer(4096)
        kernel = Mock()
        kernel.ResetEvent.return_value = 1
        kernel.ReadFile.return_value = 1 if immediate else 0
        values = list(chunks or [b"abc"])

        def completion(handle, overlapped, count, wait):
            value = values.pop(0)
            if isinstance(value, bytes):
                ctypes.memmove(pipe.buffer, value, len(value))
                count._obj.value = len(value)
                return 1
            return 0

        kernel.GetOverlappedResult.side_effect = completion
        api = Mock(k=kernel)
        api.check.side_effect = lambda value, code: value
        api.fail.side_effect = lambda code: guard.GuardError(code)
        pipe.owner = Mock(api=api)
        return pipe, kernel

    def test_immediate_completion_uses_getoverlapped_count_and_null_read_count(self):
        pipe, kernel = self.make_pipe(chunks=[b"actual"])
        self.assertEqual(pipe.read_available(), b"actual")
        self.assertIsNone(kernel.ReadFile.call_args.args[3])
        kernel.GetOverlappedResult.assert_called_once()
        self.assertFalse(pipe.pending)

    def test_immediate_zero_read_does_not_hide_later_data(self):
        pipe, kernel = self.make_pipe(chunks=[b"", b"later"])
        self.assertEqual(pipe.read_available(), b"")
        self.assertFalse(pipe.finished)
        self.assertEqual(pipe.read_available(), b"later")
        self.assertFalse(pipe.finished)
        self.assertEqual(kernel.ReadFile.call_count, 2)

    def test_pending_zero_completion_keeps_pipe_open_for_later_flood(self):
        pipe, kernel = self.make_pipe(immediate=False, chunks=[b"", b"x" * 4096])
        with patch.object(guard.ctypes, "get_last_error", return_value=997, create=True):
            self.assertEqual(pipe.read_available(), b"")
        self.assertTrue(pipe.pending)
        self.assertEqual(pipe.read_available(), b"")
        self.assertFalse(pipe.finished)
        kernel.ReadFile.return_value = 1
        self.assertEqual(len(pipe.read_available()), 4096)
        self.assertFalse(pipe.finished)

    def test_broken_pipe_is_terminal_and_incomplete_read_is_not(self):
        pipe, kernel = self.make_pipe(immediate=False)
        with patch.object(guard.ctypes, "get_last_error", return_value=997, create=True):
            pipe.read_available()
        kernel.GetOverlappedResult.return_value = 0
        kernel.GetOverlappedResult.side_effect = None
        with patch.object(guard.ctypes, "get_last_error", return_value=996, create=True):
            self.assertEqual(pipe.read_available(), b"")
        self.assertTrue(pipe.pending)
        self.assertFalse(pipe.finished)
        with patch.object(guard.ctypes, "get_last_error", return_value=109, create=True):
            self.assertEqual(pipe.read_available(), b"")
        self.assertTrue(pipe.finished)
        self.assertFalse(pipe.pending)


class FixtureCleanupTests(unittest.TestCase):
    def test_unconfirmed_cleanup_preserves_generated_scratch(self):
        root = Path(tempfile.gettempdir()) / "ocr-guard-native-test"
        for attribute, value in (("_BROKEN_GUARD", True), ("_UNCONFIRMED_IO", [object()])):
            with self.subTest(attribute=attribute), patch.object(guard, attribute, value), \
                    patch.object(shutil, "rmtree") as remove:
                self.assertFalse(NativeOptInTests.cleanup_scratch(root))
                remove.assert_not_called()

    def test_confirmed_cleanup_only_removes_exact_generated_directory(self):
        root = Path(tempfile.gettempdir()) / "ocr-guard-native-test"
        with patch.object(guard, "_BROKEN_GUARD", False), patch.object(guard, "_UNCONFIRMED_IO", []), \
                patch.object(shutil, "rmtree") as remove:
            self.assertTrue(NativeOptInTests.cleanup_scratch(root))
            remove.assert_called_once_with(root)
            with self.assertRaises(AssertionError):
                NativeOptInTests.cleanup_scratch(Path(tempfile.gettempdir()) / "unrelated")

_NATIVE = (sys.platform == "win32" and os.environ.get("RESEARCH_OCR_GUARD_NATIVE_TESTS") == "1")


@unittest.skipUnless(_NATIVE, "native processes require explicit coordinated opt-in; UNRUN")
class NativeOptInTests(unittest.TestCase):
    @staticmethod
    def cleanup_scratch(root):
        if guard._BROKEN_GUARD or guard._UNCONFIRMED_IO:
            return False
        # This exact directory was generated by mkdtemp, never selected by a
        # user/worker. Do not delete beneath any unconfirmed owned process/I/O.
        if root.parent != Path(tempfile.gettempdir()) or not root.name.startswith("ocr-guard-native-"):
            raise AssertionError("unexpected private fixture scratch")
        shutil.rmtree(root)
        return True

    def invoke(self, code, *, timeout=5, stdout_limit=262144, cancel=None):
        # Generated guard-only worker, not complete Python/Pillow/Tesseract/DLL
        # closure qualification. Native runtime closure needs separate evidence.
        temp = tempfile.mkdtemp(prefix="ocr-guard-native-")
        root = Path(temp)
        try:
            worker = root / "worker.py"
            request = root / "request.json"
            worker.write_text(code, encoding="utf-8")
            request.write_bytes(b"{}")
            exe = Path(sys.executable)
            paths = [exe, worker, request]
            self.assertLessEqual(exe.stat().st_size, 128 * 1024 * 1024)
            hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
            environment = {"SystemRoot": os.environ["SystemRoot"], "TEMP": temp, "TMP": temp,
                           "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"}
            return guard.run_guarded(exe, ["-I", "-S", "-B", str(worker), str(request)],
                                     cwd=root, environment=environment, timeout_seconds=timeout,
                                     stdout_limit=stdout_limit, expected_sha256=hashes,
                                     cancel=cancel)
        finally:
            if not self.cleanup_scratch(root):
                sys.stderr.write("UNCONFIRMED guard cleanup; generated scratch preserved: " + str(root) + "\n")

    def test_native_bounded_worker_exits_and_returns_peak_commit(self):
        result = self.invoke("import sys\nsys.stdout.buffer.write(b'bounded')\n")
        self.assertEqual(result.stdout, b"bounded")
        self.assertEqual(result.exit_code, 0)
        self.assertGreater(result.peak_job_memory_bytes, 0)
        self.assertLessEqual(result.peak_job_memory_bytes, guard.JOB_MEMORY_BYTES)

    def test_native_output_overflow_is_controlled(self):
        with self.assertRaisesRegex(guard.GuardError, "stdout-limit"):
            self.invoke("import sys\nsys.stdout.buffer.write(b'x' * 4096)\n", stdout_limit=1024)

    def test_native_timeout_includes_owned_child(self):
        code = ("import subprocess,sys,time\n"
                "p=subprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(20)'])\n"
                "time.sleep(20)\n")
        with self.assertRaisesRegex(guard.GuardError, "timeout"):
            self.invoke(code, timeout=0.5)

    def test_native_third_active_process_is_rejected(self):
        code = ("import subprocess,sys\n"
                "args=[sys.executable,'-I','-S','-B','-c','import time;time.sleep(1)']\n"
                "first=subprocess.Popen(args)\n"
                "try:\n"
                " second=subprocess.Popen(args)\n"
                "except OSError:\n"
                " print('third-refused')\n"
                "else:\n"
                " second.wait();print('third-started')\n"
                "first.wait()\n")
        result = self.invoke(code)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), b"third-refused")

    def test_native_cancel_after_resume_reaps_owned_worker(self):
        event = threading.Event()
        original = guard._WinSession
        observed = []

        class CancelAfterResume(original):
            def resume(self):
                count = super().resume()
                observed.append(count)
                if count == 1:
                    event.set()
                return count

        with patch.object(guard, "_WinSession", CancelAfterResume):
            with self.assertRaisesRegex(guard.GuardError, "cancelled"):
                self.invoke("import time\ntime.sleep(20)\n", cancel=event)
        self.assertEqual(observed, [1])
        self.assertFalse(guard._BROKEN_GUARD)
        self.assertFalse(guard._UNCONFIRMED_IO)

    @unittest.skipUnless(os.environ.get("RESEARCH_OCR_GUARD_MEMORY_TESTS") == "1",
                         "512 MiB native memory qualification needs a separate bounded window; UNRUN")
    def test_native_aggregate_committed_memory_limit(self):
        # Two live processes each try300 MiB: the second allocation must be
        # refused by the aggregate512 MiB commit cap, rather than both succeeding.
        child = ("import sys\n"
                 "try:\n"
                 " block=bytearray(300*1024*1024)\n"
                 "except MemoryError:\n"
                 " print('allocation-refused')\n"
                 "else:\n"
                 " print('allocation-succeeded')\n")
        code = ("import subprocess,sys\n"
                "held=bytearray(300*1024*1024)\n"
                "p=subprocess.Popen([sys.executable,'-I','-S','-B','-c'," + repr(child) + "])\n"
                "p.wait()\n"
                "sys.exit(p.returncode)\n")
        result = self.invoke(code, timeout=10)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), b"allocation-refused")
        self.assertLessEqual(result.peak_job_memory_bytes, guard.JOB_MEMORY_BYTES)


if __name__ == "__main__":
    unittest.main()
