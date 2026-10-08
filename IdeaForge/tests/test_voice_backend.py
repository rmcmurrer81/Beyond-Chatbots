"""CPU-only transport/lifecycle tests. No PowerShell, microphone or speech."""
import io
import json
import queue
import threading
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from kira_voice import VoiceController
from kira_voice.build_windows_host import BuildFailure, build_host, build_spec


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("condition did not become true")


class Output:
    def __init__(self):
        self.lines = queue.Queue()
    def readline(self, size):
        return self.lines.get(timeout=3)
    def close(self):
        pass


class Input:
    def __init__(self, proc):
        self.proc = proc
        self.closed = False
    def write(self, line):
        if self.closed:
            raise OSError("closed")
        data = json.loads(line)
        self.proc.commands.append(data)
        command = data.get("command")
        session = data.get("session", 0)
        if command == "start":
            self.proc.event("capabilities", session, stt_available=True,
                            tts_available=True, voice_name="Generic Female", reason="")
            self.proc.event("state", session, state="listening", pending_stop=False)
        elif command == "speak":
            self.proc.event("state", session, state="speaking", pending_stop=False)
        elif command == "resume":
            self.proc.event("state", session, state="listening", pending_stop=False)
        elif command == "stop":
            self.proc.event("state", session, state="off", pending_stop=False)
        elif command == "close":
            if self.proc.hold_exit:
                raise OSError("injected pending close")
            self.proc.finish()
        return len(line)
    def flush(self):
        pass
    def close(self):
        self.closed = True
        if not self.proc.hold_exit:
            self.proc.finish()


class Process:
    def __init__(self, hold_exit=False):
        self.stdout = Output()
        self.stderr = io.StringIO("")
        self.stdin = Input(self)
        self.returncode = None
        self.commands = []
        self.hold_exit = hold_exit
    def event(self, kind, session, **details):
        self.stdout.lines.put(json.dumps({"type": kind, "session": session, **details}) + "\n")
    def finish(self):
        if self.returncode is None:
            self.returncode = 0
            self.stdout.lines.put("")
    def poll(self):
        return self.returncode


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.processes = []
        self.invocations = []
        def factory(argv, **kwargs):
            self.invocations.append((argv, kwargs))
            proc = Process()
            self.processes.append(proc)
            return proc
        self.voice = VoiceController(self.events.append, process_factory=factory)
    def tearDown(self):
        self.voice.close(1)
        for proc in self.processes:
            proc.finish()
    def start(self):
        session = self.voice.start()
        wait_for(lambda: self.voice.status()["state"] == "listening")
        return session, self.processes[0]
    def test_cached_status_and_probe_do_not_launch(self):
        self.assertIsNone(self.voice.capabilities()["stt_available"])
        self.assertEqual(self.voice.status()["state"], "off")
        spec = self.voice.capability_probe_spec()
        self.assertFalse(spec["microphone"])
        self.assertFalse(spec["playback"])
        self.assertEqual(spec["argv"][1:], ["--mode", "Capabilities"])
        self.assertTrue(spec["argv"][0].endswith("kira-speech-host.exe"))
        self.assertNotIn("-Command", spec["argv"])
        self.assertNotIn("-ExecutionPolicy", spec["argv"])
        self.assertEqual(json.loads(spec["input"])["tts_backend"], "system_speech")
        self.assertEqual(self.invocations, [])
    def test_explicit_compiler_spec_has_fixed_source_references_no_speech(self):
        spec = build_spec()
        self.assertTrue(spec["argv"][0].endswith("csc.exe"))
        self.assertEqual(spec["argv"][-1], spec["source"])
        self.assertIn("/target:exe", spec["argv"])
        self.assertFalse(spec["microphone"])
        self.assertFalse(spec["playback"])
        self.assertEqual(len(spec["source_sha256"]), 64)
        self.assertFalse(any("powershell" in arg.lower() for arg in spec["argv"]))
        self.assertEqual(self.invocations, [])
    def test_build_helper_runs_only_injected_compiler_and_returns_failure(self):
        invocations = []
        def fake_compiler(argv, **kwargs):
            invocations.append((argv, kwargs))
            return SimpleNamespace(returncode=1, stdout="", stderr="injected denial")
        with tempfile.TemporaryDirectory() as cache:
            result = build_host(runner=fake_compiler, cache_directory=cache)
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["stderr"], "injected denial")
            self.assertEqual(len(invocations), 1)
            self.assertFalse(invocations[0][1]["shell"])
            self.assertFalse(Path(cache, "BUILDING.lock").exists())
            self.assertFalse(Path(cache, "kira-speech-host.exe").exists())
    def test_delayed_build_rechecks_output_under_owned_lock(self):
        original_open = Path.open
        compiler_calls = []
        with tempfile.TemporaryDirectory() as cache:
            output = Path(cache, "kira-speech-host.exe")
            def open_after_prior_build(path, *args, **kwargs):
                if path.name == "BUILDING.lock":
                    # Prior invocation finished after our initial absence check.
                    output.write_bytes(b"inert existing output")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", open_after_prior_build):
                with self.assertRaises(FileExistsError):
                    build_host(cache_directory=cache,
                               runner=lambda *a, **k: compiler_calls.append(a))
            self.assertEqual(compiler_calls, [])
            self.assertEqual(output.read_bytes(), b"inert existing output")
            self.assertFalse(Path(cache, "BUILDING.lock").exists())
    def test_primary_timeout_and_cleanup_error_retained_as_originals(self):
        primary = TimeoutError("injected primary")
        cleanup = PermissionError("injected unlink failure")
        original_unlink = Path.unlink
        def fail_compiler(*args, **kwargs):
            raise primary
        def fail_cleanup(path, *args, **kwargs):
            if path.name == "BUILDING.lock":
                raise cleanup
            return original_unlink(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as cache:
            with patch.object(Path, "unlink", fail_cleanup):
                with self.assertRaises(BuildFailure) as captured:
                    build_host(cache_directory=cache, runner=fail_compiler)
            error = captured.exception
            self.assertIs(error.primary_error, primary)
            self.assertEqual(error.cleanup_errors[0][0], "unlink_build_lock")
            self.assertIs(error.cleanup_errors[0][1], cleanup)
            self.assertIs(error.__cause__, primary)
            self.assertTrue(error.lease.closed)
            self.assertTrue(Path(cache, "BUILDING.lock").exists())
    def test_nonzero_compiler_return_retained_if_cleanup_fails(self):
        returned = SimpleNamespace(returncode=7, stdout="", stderr="injected compile failure")
        cleanup = PermissionError("injected cleanup")
        original_unlink = Path.unlink
        def fail_cleanup(path, *args, **kwargs):
            if path.name == "BUILDING.lock":
                raise cleanup
            return original_unlink(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as cache:
            with patch.object(Path, "unlink", fail_cleanup):
                with self.assertRaises(BuildFailure) as captured:
                    build_host(cache_directory=cache, runner=lambda *a, **k: returned)
            error = captured.exception
            self.assertIsNone(error.primary_error)
            self.assertIs(error.completed, returned)
            self.assertEqual(error.result["exit_code"], 7)
            self.assertEqual(error.result["stderr"], "injected compile failure")
            self.assertIs(error.cleanup_errors[0][1], cleanup)
    def test_lock_close_error_is_not_retried_and_preserves_primary(self):
        primary = OSError("injected compiler failure")
        cleanup = OSError("injected close acknowledgement failure")
        original_open = Path.open
        wrappers = []
        class Lease:
            def __init__(self, stream):
                self.stream = stream
                self.close_calls = 0
            def write(self, text):
                return self.stream.write(text)
            def flush(self):
                self.stream.flush()
            def close(self):
                self.close_calls += 1
                self.stream.close()
                raise cleanup
        def injected_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            if path.name == "BUILDING.lock":
                lease = Lease(stream)
                wrappers.append(lease)
                return lease
            return stream
        def fail_compiler(*args, **kwargs):
            raise primary
        with tempfile.TemporaryDirectory() as cache:
            with patch.object(Path, "open", injected_open):
                with self.assertRaises(BuildFailure) as captured:
                    build_host(cache_directory=cache, runner=fail_compiler)
            self.assertIs(captured.exception.primary_error, primary)
            self.assertEqual(captured.exception.cleanup_errors[0][0], "close_build_lock")
            self.assertIs(captured.exception.cleanup_errors[0][1], cleanup)
            self.assertEqual(wrappers[0].close_calls, 1)
            self.assertIs(captured.exception.lease, wrappers[0])
            self.assertTrue(Path(cache, "BUILDING.lock").exists())
    def test_one_final_transcript_pauses_and_is_immutable(self):
        session, proc = self.start()
        proc.event("transcript", session, text="hello", confidence=.9, final=True)
        wait_for(lambda: any(e["type"] == "transcript" for e in self.events))
        proc.event("transcript", session, text="echo", confidence=.9, final=True)
        wait_for(lambda: any(c.get("command") == "pause" for c in proc.commands))
        time.sleep(.03)
        rows = [e for e in self.events if e["type"] == "transcript"]
        self.assertEqual([e["text"] for e in rows], ["hello"])
        with self.assertRaises(TypeError):
            rows[0]["text"] = "changed"
        self.assertEqual(self.voice.status()["state"], "thinking")
    def test_delayed_listening_cannot_undo_pause(self):
        session, proc = self.start()
        self.voice.pause()
        proc.event("state", session, state="listening", pending_stop=False)
        proc.event("transcript", session, text="ignored")
        time.sleep(.04)
        self.assertEqual(self.voice.status()["state"], "thinking")
        self.assertFalse(any(e["type"] == "transcript" for e in self.events))
    def test_speech_echo_suppressed_and_resume(self):
        session, proc = self.start()
        self.assertTrue(self.voice.speak("reply", session=session))
        wait_for(lambda: self.voice.status()["state"] == "speaking")
        proc.event("transcript", session, text="reply")
        time.sleep(.03)
        self.assertFalse(any(e["type"] == "transcript" for e in self.events))
        self.assertTrue(self.voice.resume())
        wait_for(lambda: self.voice.status()["state"] == "listening")
        command = next(c for c in proc.commands if c.get("command") == "speak")
        self.assertEqual(command["text"], "reply")
        self.assertNotIn("reply", self.invocations[0][0])
    def test_stop_invalidates_session_and_reply(self):
        session, proc = self.start()
        self.voice.stop()
        self.assertGreater(self.voice.status()["session"], session)
        self.assertFalse(self.voice.speak("old", session=session))
        proc.event("transcript", session, text="late")
        time.sleep(.03)
        self.assertFalse(any(e["type"] == "transcript" for e in self.events))
        self.assertFalse(self.voice.status()["handsfree_enabled"])
    def test_truncated_transcript_never_submits(self):
        session, proc = self.start()
        proc.event("transcript", session, text="partial", truncated=True)
        wait_for(lambda: any(e.get("code") == "transcript_too_long" for e in self.events))
        self.assertFalse(any(e["type"] == "transcript" for e in self.events))
    def test_invalid_confidence_fails_closed(self):
        session, proc = self.start()
        proc.event("transcript", session, text="invalid", confidence=float("nan"))
        wait_for(lambda: any(e.get("code") == "invalid_voice_output" for e in self.events))
        self.assertFalse(self.voice.status()["handsfree_enabled"])
    def test_missing_voice_is_fatal_and_disables(self):
        session, proc = self.start()
        proc.event("error", session, code="female_voice_unavailable", fatal=True)
        wait_for(lambda: not self.voice.status()["handsfree_enabled"])
        self.assertEqual(self.voice.status()["reason"], "female_voice_unavailable")
    def test_transport_bound_checked_before_enqueue(self):
        self.start()
        with self.assertRaises(ValueError):
            self.voice.speak("\U0001f642" * 4000)
        with self.assertRaises(ValueError):
            self.voice.speak("x" * 4001)
        with self.assertRaises(ValueError):
            self.voice.speak("bad\x00")
        self.assertTrue(self.voice.speak("\U0001f642" * 2000))
    def test_normal_close_observed_and_restart_refused(self):
        self.start()
        self.assertTrue(self.voice.close(1))
        self.assertFalse(self.voice.status()["process_running"])
        with self.assertRaises(RuntimeError):
            self.voice.start()
    def test_callback_can_call_controller_without_lock_inversion(self):
        self.start()
        done = threading.Event()
        def callback(event):
            # If callback held the controller lock, this separate thread stalls.
            thread = threading.Thread(target=lambda: (self.voice.status(), done.set()))
            thread.start()
            self.assertTrue(done.wait(.5))
            thread.join()
        self.voice._callback = callback
        self.voice.pause()
        self.assertTrue(done.wait(1))
    def test_retiring_live_host_cannot_be_replaced(self):
        session, proc = self.start()
        proc.hold_exit = True
        proc.stdout.lines.put("invalid JSON\n")
        wait_for(lambda: self.voice._host_retiring)
        new_session = self.voice.start()
        self.assertGreater(new_session, session)
        self.assertEqual(len(self.invocations), 1)
        self.assertFalse(self.voice.status()["handsfree_enabled"])
        proc.finish()
        wait_for(lambda: not self.voice.status()["process_running"])
    def test_dead_host_waiting_for_reader_cannot_accept_restart(self):
        session, proc = self.start()
        proc.returncode = 0  # Keep stdout reader waiting to expose the exit/join gap.
        self.voice.stop()
        restarted = self.voice.start()
        self.assertGreater(restarted, session)
        self.assertFalse(self.voice.status()["handsfree_enabled"])
        self.assertEqual(len(self.invocations), 1)
        proc.stdout.lines.put("")
    def test_fatal_transport_marks_retirement_before_notification(self):
        self.voice.close(1)
        observed = []
        def broken_factory(*args, **kwargs):
            raise OSError("injected launch failure")
        self.voice = VoiceController(self.events.append, process_factory=broken_factory)
        original_emit = self.voice._emit
        def intercept(kind, **details):
            if details.get("code") == "speech_host_failed":
                self.voice.start()  # Immediate reentrant retry must be refused.
                observed.append(self.voice.status()["handsfree_enabled"])
            original_emit(kind, **details)
        self.voice._emit = intercept
        self.voice.start()
        wait_for(lambda: bool(observed))
        self.assertEqual(observed, [False])


if __name__ == "__main__":
    unittest.main()
