#!/usr/bin/env python3
"""Record only Aster's bounded reliability fixtures; do not run model jobs.

Run from a reviewed checkout after the coordination test window is released:
    python scripts/record_reliability_checks.py --output evidence/reliability/RUN_NAME

The output directory must not exist. This runner does not open a personal Aster
database, dispatch CI, install dependencies, or upload evidence. Review the retained
logs before publication. A process-exit fixture is not a power-loss durability test.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SUITES = (
    "test_job_effects.py", "test_inspection.py", "test_core.py",
    "test_lifecycle.py", "test_resources.py", "test_windows_files.py",
)
SOURCES = (
    "aster/storage.py", "aster/files.py", "aster/jobs.py", "aster/lifecycle.py",
    "aster/inspection.py", "aster/platform.py", "aster/windows_files.py",
    "aster/resources.py", "aster/memory_pressure.py", "aster/backend.py",
    "aster/__main__.py", "aster/dashboard.py", "aster/system_control.py",
    "scripts/record_reliability_checks.py",
) + tuple("tests/" + name for name in SUITES)
OUTPUT_CAP = 2 * 1024 * 1024  # Combined stdout/stderr bytes per suite.
EVENT_CAP = 512 * 1024
SUMMARY_CAP = 64 * 1024
MAX_SOURCE_BYTES = 1024 * 1024


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path, value):
    # Every evidence file is new; partial runs must also remain reviewable.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def hashes(repo):
    result = {}
    for name in SOURCES:
        path = repo / name
        try:
            if not path.is_file():
                result[name] = {"sha256": None, "reason": "missing"}
                continue
            with path.open("rb") as stream:
                content = stream.read(MAX_SOURCE_BYTES + 1)
            if len(content) > MAX_SOURCE_BYTES:
                result[name] = {"sha256": None, "reason": "exceeds_source_hash_limit"}
            else:
                result[name] = {"sha256": hashlib.sha256(content).hexdigest(),
                                "bytes": len(content)}
        except OSError as error:
            result[name] = {"sha256": None, "reason": "source_read_error:" + type(error).__name__}
    return result


def platform_evidence():
    result = {"sys_platform": sys.platform, "os_name": os.name,
              "pointer_bits": ctypes.sizeof(ctypes.c_void_p) * 8}
    if os.name == "nt":
        version = sys.getwindowsversion()
        result["windows_version"] = {
            "major": version.major, "minor": version.minor, "build": version.build}
    elif hasattr(os, "uname"):
        version = os.uname()
        result.update(system=version.sysname, release=version.release, machine=version.machine)
    return result


def self_resource():
    result = {"user_cpu_seconds": None, "system_cpu_seconds": None,
              "peak_process_memory_bytes": None, "memory_source": None,
              "scope": "test runner process; excludes its fixture subprocesses"}
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        result["user_cpu_seconds"] = usage.ru_utime
        result["system_cpu_seconds"] = usage.ru_stime
        if sys.platform == "darwin":
            result["peak_process_memory_bytes"] = int(usage.ru_maxrss)
            result["memory_source"] = "getrusage.ru_maxrss (bytes on macOS)"
        elif sys.platform.startswith("linux"):
            result["peak_process_memory_bytes"] = int(usage.ru_maxrss * 1024)
            result["memory_source"] = "getrusage.ru_maxrss (KiB on Linux)"
    except (ImportError, OSError, ValueError):
        pass
    return result


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity, events):
        super().__init__(stream, descriptions, verbosity)
        self.events = events
        self.event_bytes = 0
        self.statuses = {}

    def record(self, **value):
        data = (json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n").encode()
        if self.event_bytes + len(data) > EVENT_CAP:
            raise RuntimeError("Per-test evidence exceeds the bounded event limit")
        self.events.write(data)
        self.events.flush()
        self.event_bytes += len(data)

    def key(self, test):
        return test.id()[:512]

    def startTest(self, test):
        super().startTest(test)
        self.statuses[id(test)] = ("UNRUN", "No completed result was observed")
        self.record(event="started", test=self.key(test))

    def addSuccess(self, test):
        super().addSuccess(test)
        self.statuses[id(test)] = ("PASS", None)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.statuses[id(test)] = ("FAIL", "assertion_failure")
        self.record(event="failed", test=self.key(test), status="FAIL", reason="assertion_failure")

    def addError(self, test, err):
        super().addError(test, err)
        self.statuses[id(test)] = ("FAIL", "test_error")
        self.record(event="failed", test=self.key(test), status="FAIL", reason="test_error")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.statuses[id(test)] = ("UNRUN", str(reason)[:512])
        # Class/module skip holders and skipped subtests have no start/stop pair.
        self.record(event="skipped", test=self.key(test), status="UNRUN", reason=str(reason)[:512])

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.statuses[id(test)] = ("UNRUN", "expected_failure; not passing coverage")
        self.record(event="expected_failure", test=self.key(test), status="UNRUN",
                    reason="expected_failure; not passing coverage")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.statuses[id(test)] = ("FAIL", "unexpected_success")
        self.record(event="failed", test=self.key(test), status="FAIL", reason="unexpected_success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.statuses[id(test)] = ("FAIL", "subtest_failure")
        self.record(event="subtest", test=self.key(test),
                    subtest=str(subtest)[:512], status="PASS" if err is None else "FAIL")

    def stopTest(self, test):
        status, reason = self.statuses.pop(id(test))
        self.record(event="finished", test=self.key(test), status=status, reason=reason)
        super().stopTest(test)


def worker(repo, name, events_path, summary_path, temp_root):
    # A parent first attaches the process tree to its termination boundary.
    # If that setup fails, EOF leaves all tests UNRUN and starts no fixtures.
    if sys.stdin.buffer.readline(4) != b"GO\n":
        return 2
    if name not in SUITES:
        raise ValueError("Only the reliability suite allowlist may run")
    tempfile.tempdir = str(temp_root)
    sys.path.insert(0, str(repo))
    os.chdir(repo)

    def no_network(event, args):
        if event in ("socket.connect", "socket.getaddrinfo", "socket.bind"):
            raise RuntimeError("Reliability fixtures cannot use a network connection")

    sys.addaudithook(no_network)
    with events_path.open("xb") as events:
        factory = lambda stream, descriptions, verbosity: EvidenceResult(
            stream, descriptions, verbosity, events)
        suite = unittest.defaultTestLoader.discover(
            str(repo / "tests"), pattern=name)
        result = unittest.TextTestRunner(verbosity=2, resultclass=factory).run(suite)
    write_json(summary_path, {
        "tests_run": result.testsRun,
        "successful": result.wasSuccessful(),
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "resources": self_resource(),
    })
    return 0 if result.wasSuccessful() and result.testsRun else 1


class WindowsJob:
    """Kill the worker and every fixture descendant on timeout or parent exit."""
    def __init__(self, process):
        from ctypes import wintypes as w

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount",
                         "OtherOperationCount", "ReadTransferCount",
                         "WriteTransferCount", "OtherTransferCount")]

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD),
                ("SchedulingClass", w.DWORD),
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic), ("IoInfo", IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.Extended = Extended
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [
            w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.QueryInformationJobObject.argtypes = [
            w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.api.QueryInformationJobObject.restype = w.BOOL
        self.api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.api.TerminateJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(
                    self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.api.AssignProcessToJobObject(
                    self.handle, w.HANDLE(int(process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def peak(self):
        info = self.Extended()
        if self.api.QueryInformationJobObject(
                self.handle, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            return {"peak_process_memory_bytes": int(info.PeakProcessMemoryUsed),
                    "peak_job_memory_bytes": int(info.PeakJobMemoryUsed),
                    "source": "native Windows job object",
                    "scope": "worker and its fixture descendants"}
        return {"peak_process_memory_bytes": None, "peak_job_memory_bytes": None,
                "source": None, "reason": "Windows job resource query unavailable"}

    def kill(self):
        return bool(self.api.TerminateJobObject(self.handle, 124))

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def child_environment(temp_root):
    # Do not copy tokens, provider settings, or personal Aster state variables.
    env = {key: os.environ[key] for key in
           ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT")
           if key in os.environ}
    env.update({
        "HOME": str(temp_root), "USERPROFILE": str(temp_root),
        "APPDATA": str(temp_root), "LOCALAPPDATA": str(temp_root),
        "TMPDIR": str(temp_root), "TMP": str(temp_root), "TEMP": str(temp_root),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
    })
    return env


def read_cases(path):
    cases, subtests, errors = {}, [], []
    if not path.exists():
        return [], [], []
    try:
        with path.open("rb") as stream:
            content = stream.read(EVENT_CAP + 1)
    except OSError as error:
        return [], [], ["case_read_error:" + type(error).__name__]
    if len(content) > EVENT_CAP:
        errors.append("case_event_limit_exceeded")
        content = content[:EVENT_CAP]
    for line in content.splitlines():
        try:
            event = json.loads(line)
            if event.get("event") == "started":
                cases[event["test"]] = {
                    "test": event["test"], "status": "UNRUN",
                    "reason": "Process stopped before a completed result was retained"}
            elif event.get("event") in ("finished", "failed", "skipped", "expected_failure"):
                cases[event["test"]] = {
                    key: event[key] for key in ("test", "status", "reason")}
            elif event.get("event") == "subtest":
                subtests.append(event)
        except (ValueError, UnicodeError, KeyError, AttributeError):
            errors.append("invalid_or_incomplete_case_event")
    return list(cases.values()), subtests, errors


def read_summary(path):
    with path.open("rb") as stream:
        content = stream.read(SUMMARY_CAP + 1)
    if len(content) > SUMMARY_CAP:
        raise ValueError("Worker summary exceeds the evidence read limit")
    return json.loads(content)


def run_suite(repo, name, directory, timeout):
    directory.mkdir()
    started = time.monotonic()
    item = {"suite": name, "status": "UNRUN", "reason": None, "exit_code": None,
            "wall_seconds": None, "test_cases": [], "subtests": [],
            "resources": None, "process_tree_resources": None,
            "stdout": directory.name + "/stdout.txt",
            "stderr": directory.name + "/stderr.txt", "output_complete": False}
    process, job, temporary = None, None, None
    worker_allowed = False
    capture_lock = threading.Lock()
    output_exceeded = threading.Event()
    capture_errors = []
    capture = {"bytes_seen": 0, "bytes_retained": 0}
    threads = []

    def infrastructure_error(error, label):
        if item["reason"] is None or item["status"] == "PASS":
            item.update(status="FAIL" if worker_allowed else "UNRUN",
                        reason=label + ":" + type(error).__name__)
        item["runner_errno"] = getattr(error, "errno", None)
        item["runner_winerror"] = getattr(error, "winerror", None)

    def drain(pipe, path):
        try:
            with path.open("xb") as stream:
                while True:
                    block = pipe.read(4096)
                    if not block:
                        break
                    with capture_lock:
                        capture["bytes_seen"] += len(block)
                        remaining = max(0, OUTPUT_CAP - capture["bytes_retained"])
                        kept = block[:remaining]
                        stream.write(kept)
                        capture["bytes_retained"] += len(kept)
                        if len(kept) != len(block):
                            output_exceeded.set()
        except (OSError, ValueError) as error:
            capture_errors.append(type(error).__name__)
            output_exceeded.set()
        finally:
            pipe.close()

    def kill_tree():
        if process is None:
            return
        if job is not None:
            job.kill()
        elif os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()

    try:
        temporary = tempfile.TemporaryDirectory(prefix="aster-reliability-")
        temp_root = Path(temporary.name)
        command = [
            sys.executable, "-I", "-B", "-u", str(Path(__file__).resolve()),
            "--worker", name, "--events", str(directory / "cases.ndjson"),
            "--child-summary", str(directory / "worker.json"),
            "--temp-root", str(temp_root),
        ]
        item["command"] = ["python", "-I", "-B", "-u",
                           "scripts/record_reliability_checks.py", "--worker", name]
        options = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": subprocess.CREATE_NO_WINDOW}
        process = subprocess.Popen(
            command, cwd=repo, env=child_environment(temp_root),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **options)
        for pipe, file_name in ((process.stdout, "stdout.txt"),
                                (process.stderr, "stderr.txt")):
            thread = threading.Thread(
                target=drain, args=(pipe, directory / file_name), daemon=True)
            thread.start()
            threads.append(thread)
        if os.name == "nt":
            job = WindowsJob(process)
        process.stdin.write(b"GO\n")
        worker_allowed = True
        process.stdin.close()
        deadline = started + timeout
        while process.poll() is None:
            if output_exceeded.is_set():
                item.update(status="FAIL", reason="output_limit_or_capture_error")
                kill_tree()
                break
            if time.monotonic() >= deadline:
                item.update(status="TIMEOUT", reason="suite_time_budget_exhausted")
                kill_tree()
                break
            output_exceeded.wait(0.02)
        process.wait(timeout=1)
        for thread in threads:
            thread.join(timeout=0.25)
        if any(thread.is_alive() for thread in threads):
            kill_tree()
            for thread in threads:
                thread.join(timeout=0.25)
            item.update(status="FAIL", reason="incomplete_pipe_capture")
        item["exit_code"] = process.returncode
        item["output_complete"] = (
            not output_exceeded.is_set() and not capture_errors
            and not any(thread.is_alive() for thread in threads))
        summary_path = directory / "worker.json"
        if item["reason"] is None:
            if output_exceeded.is_set():
                item.update(status="FAIL", reason="output_limit_or_capture_error")
            elif not summary_path.exists():
                item.update(status="FAIL", reason="worker_exit_without_summary")
            else:
                summary = read_summary(summary_path)
                item["resources"] = summary["resources"]
                item["tests_run"] = summary["tests_run"]
                item["skipped"] = summary["skipped"]
                item["expected_failures"] = summary["expected_failures"]
                item.update(
                    status="PASS" if process.returncode == 0 and
                    summary["successful"] and summary["tests_run"] else "FAIL",
                    reason=None if process.returncode == 0 else "test_or_worker_failure")
    except KeyboardInterrupt:
        item.update(status="UNRUN", reason="operator_interrupted", interrupted=True)
    except Exception as error:
        # Keep full test tracebacks in the logs. Infrastructure metadata omits
        # local paths, environment values, and exception messages.
        infrastructure_error(error, "runner_error")
    finally:
        if process is not None:
            try:
                kill_tree()  # Stop any fixture descendant left behind.
                process.wait(timeout=1)
            except Exception as error:
                infrastructure_error(error, "process_termination_error")
                item.update(status="FAIL", reason="process_termination_unconfirmed")
            for thread in threads:
                thread.join(timeout=0.25)
            if process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError as error:
                    infrastructure_error(error, "stdin_close_error")
            item["exit_code"] = process.returncode
            if job is not None:
                try:
                    item["process_tree_resources"] = job.peak()
                except Exception as error:
                    item["process_tree_resources"] = {
                        "peak_process_memory_bytes": None, "peak_job_memory_bytes": None,
                        "source": None, "reason": "resource_query_error:" + type(error).__name__}
                finally:
                    job.close()
        if temporary is not None:
            try:
                temporary.cleanup()
                item["temporary_cleanup"] = "completed"
            except Exception as error:
                item["temporary_cleanup"] = "failed:" + type(error).__name__
                infrastructure_error(error, "temporary_cleanup_error")
        item["worker_allowed"] = worker_allowed
        item["wall_seconds"] = round(time.monotonic() - started, 6)
    item["test_cases"], item["subtests"], item["case_evidence_errors"] = read_cases(
        directory / "cases.ndjson")
    if item["case_evidence_errors"] and item["status"] == "PASS":
        item.update(status="FAIL", reason="incomplete_case_evidence")
    item["output_bytes"] = dict(capture)
    item["capture_errors"] = capture_errors
    write_json(directory / "result.json", item)
    return item


def bounded_seconds(value):
    number = float(value)
    if not 1 <= number <= 120:
        raise argparse.ArgumentTypeError("Budget must be finite, from 1 to 120 seconds")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="A new evidence directory; existing paths are refused")
    parser.add_argument("--total-seconds", type=bounded_seconds, default=120.0)
    parser.add_argument("--suite-seconds", type=bounded_seconds, default=20.0)
    parser.add_argument("--revision", help="Optional user-reported commit; not verified by this script")
    parser.add_argument("--worker", choices=SUITES, help=argparse.SUPPRESS)
    parser.add_argument("--events", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--child-summary", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--temp-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.worker:
        if not all((args.events, args.child_summary, args.temp_root)):
            parser.error("Internal worker requires its evidence and temporary paths")
        return worker(repo, args.worker, args.events, args.child_summary, args.temp_root)
    if args.output is None:
        parser.error("--output is required")
    if args.revision is not None and (
            len(args.revision) != 40 or any(c not in "0123456789abcdefABCDEF" for c in args.revision)):
        parser.error("--revision must be a 40-character hexadecimal commit ID")
    output = args.output.absolute()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("Refusing to overwrite an existing evidence directory")
    before = hashes(repo)
    started = time.monotonic()
    manifest = {
        "schema_version": 1, "started_utc": utc_now(), "status": "UNRUN",
        "reported_revision": args.revision, "revision_verified": False,
        "python": sys.version, "python_implementation": sys.implementation.name,
        "platform": platform_evidence(),
        "sqlite": {"version": sqlite3.sqlite_version,
                   "threadsafety": sqlite3.threadsafety},
        "limits": {"total_execution_seconds": args.total_seconds,
                   "suite_execution_seconds": args.suite_seconds,
                   "combined_stdout_stderr_bytes_per_suite": OUTPUT_CAP,
                   "case_event_bytes_per_suite": EVENT_CAP,
                   "worker_summary_read_bytes": SUMMARY_CAP,
                   "termination_grace_seconds_per_wait": 1},
        "fixture_scope": "allowlisted tests, isolated temporary directories, no personal database",
        "network_scope": "worker audit hook blocks socket connect, resolve and bind; "
                         "fixture subprocesses do not inherit that hook",
        "source_hashes_before": before, "suites": [],
    }
    write_json(output / "environment.json", {
        key: value for key, value in manifest.items() if key != "suites"})
    deadline = started + args.total_seconds
    interrupted = False
    for index, name in enumerate(SUITES, 1):
        remaining = deadline - time.monotonic() - 2  # Reserve bounded termination time.
        if interrupted:
            item = {"suite": name, "status": "UNRUN", "reason": "operator_interrupted"}
        elif remaining < 1:
            item = {"suite": name, "status": "UNRUN", "reason": "total_time_budget_exhausted"}
        elif not (repo / "tests" / name).is_file():
            item = {"suite": name, "status": "UNRUN", "reason": "suite_file_missing"}
        else:
            try:
                item = run_suite(repo, name, output / ("%02d-" % index + name[:-3]),
                                 min(args.suite_seconds, remaining))
            except KeyboardInterrupt:
                item = {"suite": name, "status": "UNRUN", "reason": "operator_interrupted",
                        "interrupted": True}
            except Exception as error:
                item = {"suite": name, "status": "FAIL",
                        "reason": "evidence_error:" + type(error).__name__}
        interrupted = interrupted or item.get("interrupted", False)
        manifest["suites"].append(item)
    manifest["source_hashes_after"] = hashes(repo)
    manifest["source_changed_during_run"] = before != manifest["source_hashes_after"]
    manifest["source_hashes_complete"] = all(
        entry["sha256"] is not None for snapshot in (before, manifest["source_hashes_after"])
        for entry in snapshot.values())
    manifest["finished_utc"] = utc_now()
    manifest["observed_wall_seconds"] = round(time.monotonic() - started, 6)
    statuses = [item["status"] for item in manifest["suites"]]
    incomplete_cases = any(
        item.get("skipped", 0) or item.get("expected_failures", 0) or any(
            case["status"] == "UNRUN" for case in item.get("test_cases", []))
        for item in manifest["suites"])
    if manifest["source_changed_during_run"] or any(s in ("FAIL", "TIMEOUT") for s in statuses):
        manifest["status"] = "FAIL"
    elif "UNRUN" in statuses or incomplete_cases or not manifest["source_hashes_complete"]:
        manifest["status"] = "UNRUN"
    else:
        manifest["status"] = "PASS"
    manifest["status_meaning"] = (
        "PASS requires all requested suites and cases to pass; skipped or expected-failure "
        "cases or incomplete source hashes are UNRUN. FAIL includes timeout/infrastructure "
        "failure/source changes. "
        "Suite PASS can contain individually UNRUN platform-specific cases.")
    write_json(output / "summary.json", manifest)
    for item in manifest["suites"]:
        print("%s %s%s" % (item["status"], item["suite"],
                          (" (" + item["reason"] + ")") if item.get("reason") else ""))
    print("OVERALL " + manifest["status"])
    return {"PASS": 0, "FAIL": 1, "UNRUN": 2}[manifest["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
