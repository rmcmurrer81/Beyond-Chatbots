"""Explicit standard .NET Framework build; never runs speech or PowerShell.

Import/spec creation is read-only. Only an explicit build_host() / --build
invocation starts the installed compiler. No download or alternate compiler.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


class BuildFailure(RuntimeError):
    """Unsuccessful cleanup with original primary/error/result objects retained."""
    def __init__(self, primary_error, cleanup_errors, result, completed, lease):
        super().__init__("speech build cleanup failed; original outcome retained")
        self.primary_error = primary_error
        self.cleanup_errors = tuple(cleanup_errors)
        self.result = result
        self.completed = completed
        self.lease = lease


def build_spec():
    """Return fixed compiler/data paths; does not create directories or execute."""
    source = Path(__file__).with_name("windows_speech.cs").resolve()
    with source.open("rb") as stream:
        raw = stream.read(65537)
    if not 1 <= len(raw) <= 65536:
        raise ValueError("speech source exceeds build limit")
    source_hash = hashlib.sha256(raw).hexdigest()
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    framework = windows / "Microsoft.NET/Framework64/v4.0.30319"
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    cache = local / "KiraVoiceHost" / ("v3-" + source_hash)
    host = cache / "kira-speech-host.exe"
    references = [framework / (name + ".dll") for name in (
        "System", "System.Core", "Microsoft.CSharp", "System.Web.Extensions")]
    references.append(windows / "Microsoft.NET/assembly/GAC_MSIL/System.Speech/"
                      "v4.0_4.0.0.0__31bf3856ad364e35/System.Speech.dll")
    argv = [str(framework / "csc.exe"), "/nologo", "/noconfig", "/target:exe",
            "/platform:x64", "/optimize+", "/out:" + str(host)]
    argv.extend("/reference:" + str(ref) for ref in references)
    argv.append(str(source))
    return {"argv": argv, "source": str(source), "source_sha256": source_hash,
            "source_bytes": len(raw), "cache_directory": str(cache),
            "host_exe": str(host), "references": [str(ref) for ref in references],
            "timeout_seconds": 30, "diagnostic_limit_characters": 8192,
            "microphone": False, "playback": False}


def host_argv(mode):
    if mode not in {"Host", "Capabilities"}:
        raise ValueError("invalid speech host mode")
    return [build_spec()["host_exe"], "--mode", mode]


def build_host(*, runner=None, cache_directory=None):
    """Explicit one-shot build. Nonzero/denied compilation is returned, no retry.

    Diagnostics are truncated in the return value. The installed compiler with
    this fixed small source is a cooperating process, not an OS output sandbox.
    A subprocess timeout is an unsuccessful build; the caller must report it.
    cache_directory is for an explicit ephemeral build/test, never a fallback.
    """
    spec = build_spec()
    if cache_directory is not None:
        cache = Path(cache_directory).resolve()
        spec["cache_directory"] = str(cache)
        spec["host_exe"] = str(cache / "kira-speech-host.exe")
        spec["argv"] = ["/out:" + spec["host_exe"] if a.startswith("/out:")
                        else a for a in spec["argv"]]
    cache = Path(spec["cache_directory"])
    cache.mkdir(parents=True, exist_ok=True)
    if Path(spec["host_exe"]).exists():
        raise FileExistsError("speech output already exists; do not overwrite a running host")
    lock = cache / "BUILDING.lock"
    # Exclusive build prevents the two apps from compiling onto the same output.
    lease = lock.open("x", encoding="utf-8")
    primary_error = completed = result = None
    cleanup_errors = []
    try:
        # Another build may have completed between the first check and this lock.
        if Path(spec["host_exe"]).exists():
            raise FileExistsError("speech output exists after acquiring build lock")
        lease.write(spec["source_sha256"] + "\n")
        lease.flush()
        completed = (runner or subprocess.run)(spec["argv"], shell=False,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=spec["timeout_seconds"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        stdout, stderr = completed.stdout or "", completed.stderr or ""
        bound = spec["diagnostic_limit_characters"]
        result = {"exit_code": completed.returncode,
                  "stdout": stdout[:bound], "stderr": stderr[:bound],
                  "diagnostics_truncated": len(stdout) > bound or len(stderr) > bound,
                  "source_sha256": spec["source_sha256"],
                  "host_exe": spec["host_exe"], "microphone": False, "playback": False}
        conserved = build_spec()["source_sha256"]
        if conserved != spec["source_sha256"]:
            raise RuntimeError("speech source changed during build")
        if completed.returncode == 0 and Path(spec["host_exe"]).is_file():
            with Path(spec["host_exe"]).open("rb") as stream:
                compiled = stream.read(2097153)
            if len(compiled) > 2097152:
                raise ValueError("compiled speech application exceeds build limit")
            result["host_sha256"] = hashlib.sha256(compiled).hexdigest()
        elif completed.returncode == 0:
            result["output_missing"] = True
    except BaseException as error:
        primary_error = error
    finally:
        try:
            lease.close()  # One close attempt, before any unlink on Windows.
        except BaseException as error:
            cleanup_errors.append(("close_build_lock", error))
        if not cleanup_errors:
            try:
                lock.unlink()  # Only this invocation's exclusively created lock.
            except BaseException as error:
                cleanup_errors.append(("unlink_build_lock", error))
    if cleanup_errors:
        raise BuildFailure(primary_error, cleanup_errors, result, completed, lease) from primary_error
    if primary_error is not None:
        raise primary_error
    return result


if __name__ == "__main__":
    if sys.argv[1:] == ["--build"]:
        try:
            result = build_host()
            print(json.dumps(result, ensure_ascii=True))
            raise SystemExit(0 if result["exit_code"] == 0 and
                             "host_sha256" in result else 1)
        except BuildFailure as exc:
            print(json.dumps({"error": "BuildFailure", "build_failed": True,
                "primary_error_type": type(exc.primary_error).__name__
                    if exc.primary_error is not None else None,
                "cleanup_errors": [{"stage": stage, "error_type": type(error).__name__}
                                   for stage, error in exc.cleanup_errors],
                "compiler_result": exc.result}, ensure_ascii=True))
            raise SystemExit(1)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            print(json.dumps({"error": type(exc).__name__, "build_failed": True}))
            raise SystemExit(1)
    elif not sys.argv[1:]:
        print(json.dumps(build_spec(), ensure_ascii=True))
    else:
        raise SystemExit("usage: python -m kira_voice.build_windows_host [--build]")
