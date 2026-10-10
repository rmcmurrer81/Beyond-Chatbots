# Startup recovery and local RAM coordination

The desktop can be launched normally or by the opt-in [Windows sign-in helper](STARTUP.md).
No startup registration is made by opening Aster, downloading the repository, or
running tests. The helper runs after the current user signs in; it cannot switch
on a powered-off PC, change firmware power-restore settings, unlock Windows, or
sign in automatically. An outage recovery therefore depends on the computer
receiving power, booting, and the user signing in normally.

## One state, one foreground instance

Every desktop opens the existing `Store` advisory lock before any lifecycle work.
A second instance using that state is refused. OS process termination releases the
lock; Aster does not delete supposedly stale lock files or trust a PID file. Other
state directories represent separately selected instances, not one shared identity.

On startup Aster performs SQLite `quick_check(1)`, records a new session, and reports
prior unclean sessions, prepared file changes, and jobs left in `running` state.
It does **not** replay writes, resume jobs, resend messages, or execute pending
prompts. The desktop displays a recovery warning. Use **History > Reconcile
interrupted** to review and explicitly invoke existing file reconciliation and job
interruption handling. Conflicting workspace bytes remain protected. A SQLite
check validates database structure; it is not a backup or proof that every file
survived a physical power failure.

An orderly close records a clean session before releasing state. The worker finishes
accepted bounded work before closing. An unhandled UI/worker failure records an
unclean session when cleanup is possible; abrupt process exit leaves its durable
running marker for the next launch to inspect. Tests include real `os._exit`
process-crash fixtures, not actual power-cut tests. Filesystem/device caches and
hardware behavior prevent a blanket power-loss durability guarantee.

## Crash-loop protection

Three consecutive short unclean sessions block automatic launch for five minutes.
A short session means fewer than 60 seconds of durably observed monotonic runtime.
The idle desktop records a heartbeat on its five-second resource check. Unobserved
runtime is conservatively considered short. A clean manual launch remains the
inspection/recovery path and clears the crash streak.

There is no restart watchdog, background service, or endless retry loop. Cooldown
is checked on a later launch; it does not schedule one. Cross-boot cooldown uses
wall time. Backward time changes require a clean manual recovery launch; forward
clock jumps can expire the interval. No network clock service is contacted.

## Physical-memory observations and job admission

Windows reads [GlobalMemoryStatusEx](https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
physical-memory counters. Linux reads bounded `MemTotal` and `MemAvailable` fields
from `/proc/meminfo`. These are system physical-memory observations, not a NewBrain
estimate, per-process accounting, an allocator reservation, or proof of container
resource headroom. Unsupported platforms report unknown instead of inventing data.

The default policy defers new queued jobs at 90% used physical RAM. Once pressure
is high, admission only becomes normal at 80% used or below. This hysteresis avoids
flapping. Stale, malformed, missing or reversed-clock observations fail closed.
The desktop samples while idle at five-second intervals; every explicit `run-one`
forces a fresh observation before changing the queued job to running.

A deferred job stays `queued`, with no file/memory side effect. Nothing automatically
runs it when RAM becomes available: the owner must select **Run next once** again.
Aster does not interrupt an already-running atomic file operation. Direct bounded
owner file actions remain available. Current operations are small; no heavy AI
worker or automatic planner is installed.

```sh
python -m aster --state /absolute/private/state memory status
python -m aster --state /absolute/private/state memory configure --high-percent 90 --resume-percent 80
```

Thresholds must be finite and satisfy `0 <= resume < high <= 100`. Settings are
stored only in Aster's existing state database, with an audit event. They apply to
the next command or desktop launch; close the desktop before using the CLI on its
locked state. These commands change no Windows security or application settings.
The desktop footer reports RAM admission and recovery state; **Voice & status >
Memory & recovery** shows detailed observations and the disabled app-relief policy.

## Other applications and presence

Aster currently does not enumerate, save, close, or kill external applications and
does not access a webcam. The operational allowlist is empty. Steam, iCloud and
browser/email examples are recorded only as [disabled future policy diagnostics](MEMORY_RELIEF.md).
Unknown presence, active downloads/sync/media, unsaved work or an unverified draft
save must block closure. Webcam absence alone cannot establish that closing an app
is safe. No generic Ctrl-S, taskkill, force-close, email send or guessed browser
state is implemented.

## Verification limits

Tests use fake registry backends for enable/disable and never configure the real
runner's startup. A native Windows command-line parser checks quoting, and the
native Windows memory test checks real counters in CI. Linux tests cannot qualify
those Windows APIs. Read the exact commit's CI and [validation record](VALIDATION.md).
No user's workstation, camera, browser, email account, BIOS, or sign-in settings
were accessed during this implementation.
