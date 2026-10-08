"""Small asynchronous JSON-lines client for the packaged Windows speech host."""
from __future__ import annotations

from collections import deque
import json
import math
import subprocess
import sys
import threading
import time
from types import MappingProxyType

from .build_windows_host import host_argv

MAX_TEXT = 4000
MAX_LINE = 32768
MAX_COMMANDS = 16
MAX_EVENTS = 32
STATES = {"off", "listening", "thinking", "speaking"}


class VoiceController:
    """Callbacks run on background threads. Queue dict(event) for a GUI/browser.

    Construction/status never starts a process. start() is microphone opt-in.
    stop() invalidates session events immediately and requests cooperative
    cancellation. close() waits briefly for normal exit; it never kills a host.
    """

    def __init__(self, on_event, *, culture="en-US", voice_name=None,
                 tts_backend="system_speech", process_factory=None):
        if not callable(on_event):
            raise TypeError("on_event must be callable")
        if type(culture) is not str or not 1 <= len(culture) <= 64:
            raise ValueError("culture must contain 1..64 characters")
        if voice_name is not None and (type(voice_name) is not str or
                                      not 1 <= len(voice_name) <= 128):
            raise ValueError("voice_name must contain 1..128 characters")
        if tts_backend not in {"system_speech", "sapi_com"}:
            raise ValueError("unsupported tts_backend")
        self._callback = on_event
        self._factory = process_factory or subprocess.Popen
        self._injected = process_factory is not None
        self._config = {"culture": culture, "voice_name": voice_name or "",
                        "tts_backend": tts_backend}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._commands = deque()
        self._events = deque()
        self._event_thread = None
        self._proc = None
        self._thread = None
        self._session = 0
        self._enabled = False
        self._gate = False
        self._paused = True
        self._speech_pending = False
        self._state = "off"
        self._closing = False
        self._pending_stop = False
        self._host_retiring = False
        self._exited = threading.Event()
        self._exited.set()
        self._caps = {"platform": "windows", "engine": tts_backend,
                      "stt_available": None, "tts_available": None,
                      "culture": culture, "voice_name": "", "reason": "not_probed"}

    def capabilities(self):
        """Return a fresh cached dict; never enumerate voices or open a mic."""
        with self._lock:
            return dict(self._caps)

    def status(self):
        with self._lock:
            return {**self._caps, "state": self._state, "session": self._session,
                    "handsfree_enabled": self._enabled, "closing": self._closing,
                    "pending_stop": self._pending_stop,
                    "process_running": self._proc is not None and
                                       self._proc.poll() is None}

    def _argv(self, mode):
        return host_argv(mode)

    def capability_probe_spec(self):
        """A specification only. An external caller owns timeout/supervision."""
        return {"argv": self._argv("Capabilities"),
                "input": json.dumps(self._config, ensure_ascii=True) + "\n",
                "timeout_seconds": 8, "output_limit_bytes": 4096,
                "microphone": False, "playback": False}

    def _emit(self, kind, **details):
        with self._lock:
            if details.get("session", self._session) != self._session:
                return
            event = {"type": kind, "session": self._session,
                     "generation": self._session, **details}
            if len(self._events) >= MAX_EVENTS:
                # A blocked consumer cannot grow memory or leave listening on.
                self._enabled = self._gate = False
                self._paused = True
                self._host_retiring = True
                self._caps["reason"] = "event_consumer_slow"
                self._events.clear()
                self._commands.clear()
                self._commands.append({"command": "close", "session": self._session})
                self._condition.notify_all()
                event = {"type": "error", "session": self._session,
                         "generation": self._session, "code": "event_consumer_slow",
                         "fatal": True}
            self._events.append(MappingProxyType(event))
            if self._event_thread is None:
                self._event_thread = threading.Thread(target=self._deliver_events,
                    name="kira-voice-events", daemon=True)
                self._event_thread.start()

    def _deliver_events(self):
        while True:
            with self._lock:
                if not self._events:
                    self._event_thread = None
                    return
                event = self._events.popleft()
                if event["session"] != self._session:
                    continue
            # No enclosing controller lock: consumers may call controller methods.
            try:
                self._callback(event)
            except Exception:
                with self._lock:
                    self._caps["reason"] = "event_consumer_failed"

    def _enqueue(self, command, *, priority=False, **data):
        with self._condition:
            item = {"command": command, "session": self._session, **data}
            if len(json.dumps(item, ensure_ascii=True) + "\n") > MAX_LINE:
                raise ValueError("voice command exceeded line limit")
            if priority:
                self._commands.clear()
            if len(self._commands) >= MAX_COMMANDS:
                self._emit("error", code="command_queue_full", fatal=False)
                return False
            self._commands.append(item)
            self._condition.notify_all()
            return True

    def _launch(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError("previous speech host has not exited")
            self._exited.clear()
            self._thread = threading.Thread(target=self._run, name="kira-voice-host",
                                            daemon=True)
            self._thread.start()

    def start(self):
        """Enable hands-free listening; return its monotonic session integer."""
        with self._lock:
            if self._closing:
                raise RuntimeError("voice controller is closed")
            if self._host_retiring or (self._thread and self._thread.is_alive()
                    and self._proc is not None and self._proc.poll() is not None):
                self._session += 1
                self._enabled = self._gate = False
                self._state = "off"
                self._emit("error", code="previous_speech_host_pending", fatal=True)
                return self._session
            if self._enabled:
                return self._session
            self._session += 1
            self._enabled = True
            self._gate = False  # open only on the current host's listening ACK
            self._paused = False
            self._speech_pending = False
            self._pending_stop = False
            if sys.platform != "win32" and not self._injected:
                self._enabled = self._gate = False
                self._caps.update(stt_available=False, tts_available=False,
                                  reason="unsupported_platform")
                self._emit("error", code="unsupported_platform", fatal=True)
                self._emit("state", state="off", pending_stop=False)
                return self._session
            self._enqueue("start")
            self._launch()
            return self._session

    def stop(self):
        """Immediately suppress stale transcripts; request mic/speech cancel."""
        with self._lock:
            self._session += 1
            self._enabled = self._gate = False
            self._paused = True
            self._speech_pending = False
            self._state = "off"
            self._pending_stop = bool(self._thread and self._thread.is_alive())
            if self._pending_stop:
                self._enqueue("stop", priority=True)
            self._emit("state", state="off", pending_stop=self._pending_stop)

    def pause(self):
        """Pause listening while an app processes a typed or spoken request."""
        with self._lock:
            if not self._enabled or self._closing:
                return False
            self._gate = False
            self._paused = True
            self._speech_pending = False
            self._state = "thinking"
            self._emit("state", state="thinking", pending_stop=False)
            return self._enqueue("pause")

    def resume(self):
        with self._lock:
            if not self._enabled or self._closing:
                return False
            self._gate = False
            self._paused = False
            self._speech_pending = False
            return self._enqueue("resume")

    def speak(self, text, *, session=None):
        """Speak a plain-text reply only in a still-enabled matching session."""
        if type(text) is not str or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError("speech text must contain 1..4000 characters")
        try:
            if len(text.encode("utf-16-le")) // 2 > MAX_TEXT:
                raise ValueError("speech text exceeds 4000 UTF-16 units")
        except UnicodeError as exc:
            raise ValueError("speech text contains invalid Unicode") from exc
        if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
            raise ValueError("speech text contains unsupported controls")
        with self._lock:
            if not self._enabled or self._closing or (
                    session is not None and session != self._session):
                return False
            self._gate = False
            self._paused = False
            self._speech_pending = True
            accepted = self._enqueue("speak", text=text)
            if not accepted:
                self._speech_pending = False
            return accepted

    def close(self, timeout=2.0):
        """Request normal disposal. False means still pending; no force-kill."""
        if type(timeout) not in (int, float) or not 0 <= timeout <= 10:
            raise ValueError("close timeout must be between 0 and 10 seconds")
        with self._lock:
            if not self._closing:
                self._closing = True
                self._session += 1
                self._enabled = self._gate = False
                self._paused = True
                self._speech_pending = False
                self._state = "off"
                self._pending_stop = bool(self._thread and self._thread.is_alive())
                if self._pending_stop:
                    self._enqueue("close", priority=True)
                self._emit("state", state="off", pending_stop=self._pending_stop)
        if threading.current_thread() is self._thread:
            return self._exited.is_set()
        done = self._exited.wait(timeout)
        if not done:
            self._emit("error", code="close_pending", fatal=False)
        return done

    def _accept(self, value):
        if type(value) is not dict or value.get("type") not in {
                "state", "transcript", "error", "capabilities"}:
            raise ValueError("invalid voice event")
        with self._lock:
            if type(value.get("session")) is not int or value["session"] != self._session:
                return
            kind = value["type"]
            if kind == "capabilities":
                for key in ("stt_available", "tts_available"):
                    if type(value.get(key)) is not bool:
                        raise ValueError("invalid capability flag")
                self._caps.update(
                    stt_available=value["stt_available"],
                    tts_available=value["tts_available"],
                    voice_name=str(value.get("voice_name", ""))[:128],
                    reason=str(value.get("reason", ""))[:256])
                self._emit(kind, **self._caps)
            elif kind == "state":
                state = value.get("state")
                if state not in STATES:
                    raise ValueError("invalid voice state")
                if not self._enabled and state != "off":
                    return
                if state == "listening" and (self._paused or self._speech_pending):
                    return
                if state == "speaking" and self._paused:
                    return
                if state == "speaking":
                    self._speech_pending = False
                self._state = state
                self._pending_stop = value.get("pending_stop") is True
                self._gate = self._enabled and state == "listening"
                completion = {key: value[key] for key in (
                    "recognition_completed_session", "speech_completed_session")
                    if type(value.get(key)) is int}
                self._emit(kind, state=state, pending_stop=self._pending_stop, **completion)
            elif kind == "transcript":
                if not self._enabled or not self._gate or self._closing:
                    return
                text = value.get("text")
                if type(text) is not str or not text.strip() or len(text) > MAX_TEXT:
                    raise ValueError("invalid transcript")
                if len(text.encode("utf-16-le")) // 2 > MAX_TEXT:
                    raise ValueError("transcript exceeded UTF-16 limit")
                if value.get("truncated") is True:
                    self._gate = False
                    self._paused = True
                    self._state = "thinking"
                    self._enqueue("pause")
                    self._emit("error", code="transcript_too_long", fatal=False)
                    self._emit("state", state="thinking", pending_stop=False)
                    return
                confidence = value.get("confidence")
                if confidence is not None and (type(confidence) not in (int, float)
                        or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                    raise ValueError("invalid confidence")
                self._gate = False
                self._paused = True
                self._state = "thinking"
                self._enqueue("pause")
                self._emit(kind, text=text, confidence=confidence,
                           final=True, truncated=value.get("truncated") is True)
                self._emit("state", state="thinking", pending_stop=False)
            else:
                fatal = value.get("fatal") is True
                code = str(value.get("code", "speech_error"))[:128]
                if fatal:
                    self._enabled = self._gate = False
                    self._speech_pending = False
                    self._state = "off"
                    self._caps["reason"] = code
                self._emit(kind, code=code, fatal=fatal)
                if not fatal and code in {"speech_failed", "speech_already_pending"}:
                    self._speech_pending = False
                if fatal:
                    self._emit("state", state="off", pending_stop=False)

    def _read_events(self, proc):
        try:
            while True:
                line = proc.stdout.readline(MAX_LINE + 1)
                if not line:
                    return
                if len(line) > MAX_LINE or not line.endswith("\n"):
                    raise ValueError("voice event exceeded line limit")
                self._accept(json.loads(line))
        except (ValueError, TypeError, RecursionError, OSError, UnicodeError):
            with self._lock:
                if proc is not self._proc:
                    return
                self._enabled = self._gate = False
                self._host_retiring = True
                self._state = "off"
                self._enqueue("close", priority=True)
                self._emit("error", code="invalid_voice_output", fatal=True)

    def _drain_errors(self, proc):
        # Fixed host emits only bounded setup diagnostics. Never retain audio/text.
        try:
            while proc.stderr.read(1024):
                pass
        except (OSError, UnicodeError):
            pass

    def _run(self):
        proc = None
        try:
            proc = self._factory(self._argv("Host"), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="strict", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self._lock:
                self._proc = proc
            proc.stdin.write(json.dumps(self._config, ensure_ascii=True) + "\n")
            proc.stdin.flush()
            readers = [threading.Thread(target=fn, args=(proc,), daemon=True)
                       for fn in (self._read_events, self._drain_errors)]
            for thread in readers:
                thread.start()
            while proc.poll() is None:
                with self._condition:
                    if not self._commands:
                        self._condition.wait(.05)
                    if not self._commands:
                        continue
                    command = self._commands.popleft()
                    if command["session"] != self._session:
                        continue
                line = json.dumps(command, ensure_ascii=True) + "\n"
                if len(line) > MAX_LINE:
                    raise ValueError("voice command exceeded line limit")
                proc.stdin.write(line)
                proc.stdin.flush()
            for thread in readers:
                thread.join(.2)
            if proc.returncode != 0:
                with self._lock:
                    self._enabled = self._gate = False
                    self._host_retiring = True
                    self._state = "off"
                    self._caps["reason"] = "speech_host_unavailable"
                self._emit("error", code="speech_host_unavailable", fatal=True)
        except (OSError, ValueError, subprocess.SubprocessError):
            with self._lock:
                self._enabled = self._gate = False
                self._host_retiring = True
                self._state = "off"
                self._caps["reason"] = "speech_host_failed"
            self._emit("error", code="speech_host_failed", fatal=True)
        finally:
            with self._lock:
                self._host_retiring = True
            if proc is not None and proc.poll() is None:
                try:
                    proc.stdin.close()  # EOF requests normal disposal, no kill.
                except OSError:
                    pass
                with self._lock:
                    self._caps["reason"] = "host_exit_pending"
                # Keep the original process reference and monitor alive. A native
                # stall remains pending; another host is never launched over it.
                while proc.poll() is None:
                    time.sleep(.05)
            if proc is not None:
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            with self._lock:
                finished_session = self._session
                self._proc = None
                self._pending_stop = False
                self._enabled = self._gate = False
                self._state = "off"
                self._host_retiring = False
                self._thread = None
                self._exited.set()
            self._emit("state", session=finished_session, generation=finished_session,
                       state="off", pending_stop=False)
