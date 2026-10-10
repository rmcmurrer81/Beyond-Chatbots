# Foundation validation

2026-10-04, cloud Linux, Python 3.12.14, no GPU/model use.

- `python -m unittest discover -s tests -v`: 30 tests passed.
- `python -m compileall -q aster tests`: passed.
- Real CLI subprocess restart retained Aster identity, prompts and memories.
- Temporary-workspace writes/trash/undo, external edit conflicts, traversal,
  symlinks, hard links, FIFOs, oversized input, single-writer lock and initialization
  failure cleanup were exercised.
- Explicit simulated hard process exits before and after replacement were
  reconciled on a genuine subsequent process open. No user files were used.
- Durable queue pause/resume/cancel, interrupted-job non-replay and one-job execution
  were checked. These are finite deterministic operations, not AI planning tests.
- App catalog fixtures verify read-only discovery, stale/invalid records, no
  research-record access and absent-catalog noncreation. They are synthetic
  registrations, not proof that real apps are installed or connected.
- Backend-absent and manual-research tests forbid socket creation. No NewBrain,
  Qwen, Ollama, other model, voice synthesis or general conversation was run.

One complete test subprocess took 0.4485 seconds wall time. Linux
`resource.RUSAGE_CHILDREN.ru_maxrss` reported 21,180 KiB. This is an OS child
high-water observation for that test invocation, **not simultaneous process-tree
RAM**, a model benchmark or the cost of a future NewBrain backend. A standard
`/usr/bin/time` executable was unavailable; the resource observation used Python's
standard library instead. These numbers are not enforced resource limits.

Independent source review identified a constructor-failure lock leak; cleanup
and regression tests were added, as were hardlinked-database guards. GitHub CI
results belong to the published commit and should be checked separately.

Not tested: Windows secure file tools (unsupported), macOS execution, power loss,
hostile same-OS-user interference, a real NewBrain adapter, real app command APIs,
Aster-authorized cross-app research grants, user-provided voice playback/synthesis.

## Windows candidate source checkpoint

A native Windows adapter and platform state lock were added after the first
Linux-only milestone. Before native CI, the Linux suite collected 52 tests:
33 executed successfully and 19 native-Windows cases were explicitly skipped.
Compile checks passed. Those skips are **not Windows evidence**.

The candidate requires a local fixed NTFS volume and current Windows APIs for
case-sensitivity inspection. It rejects reparse points/junctions/ADS, DOS aliases,
network/device namespaces, hardlinks and unsupported names. Workspace filenames
are ASCII/lowercase journal keys; state-directory Unicode names are permitted.

The Windows matrix will run the actual adapter and the existing real process-crash,
job, identity, lock and persistence tests, plus native-specific guard fixtures.
Any unavailable fixture is reported as skipped, not passed. No user-PC access,
security setting change, installer, persistent agent or data migration occurred.
Native CI results are pending until an exact run is recorded below.

State locking uses Python's documented Windows byte-range lock, which can extend
beyond EOF without writing a sentinel byte:
https://docs.python.org/3/library/msvcrt.html#msvcrt.locking

### First native Windows run: failure retained

Run `37222100109`, head `52fa3fb67f75228130c0d9aef69d5fcf70469bfe`, executed on
Windows Server 2025 / Python 3.12.10. It collected 52 tests and failed with
3 failures, 11 errors and 2 platform skips. Native junction/symlink/hardlink,
ancestor-handle, case-sensitive-directory and state-lock guards passed, but
Win32 `SetFileInformationByHandle(FileRenameInfo)` rejected relative-parent rename
with WinError 87. A POSIX-only registration fixture was also invalid on Windows.
Compile and companion stages were skipped after this failure. This was not a
successful Windows qualification.

The next candidate preserves all native handle/pinning checks and uses the
reviewed native `NtSetInformationFile(FileRenameInformation)` contract for rename;
there is no path-only fallback. Registration fixtures now use real platform-native
absolute temporary paths. Its actual Windows rerun remains pending.

### Corrected native Windows run: passed

[Run 37222565780](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37222565780)
verified exact head `957f8f92b8a28169956abf1c8f0040bf86eacda9`.
Windows Server 2025 build 26100 / CPython 3.12.10 executed **51 of 53 tests**, all
passing. The only skips were the POSIX FIFO case and non-Windows-emulation check.
All **20 Windows-specific cases actually ran**, including real junctions, symbolic
links, hardlinks, case-sensitive directories, ancestor/temporary-file handle
pinning, handle-relative rename independent of current directory, and failure
cleanup. Existing real process-crash, state-lock contention, restart, identity,
job and app-discovery tests also passed.

Windows additionally passed 10 relay/bridge Python tests, 5 Node browser-logic
checks and 1,055 Java offline protocol assertions. Compile/syntax stages passed.
The Linux matrix job passed too (33 core tests executed, 20 Windows cases skipped).
No physical phone, Android APK, public deployment, user PC or live brain/voice
synthesizer was tested. The first native failure above remains part of the record.

## Voice and proposal candidate checkpoint

The supplied original voice WAV's exact bytes and signal metadata were independently
verified. Read-only pack inspection and the manual local preview have 17 focused
checks. The ability proposal registry has 15 focused tests; source bytes are never
executed, and every result reports disabled execution/activation and no permission
grants. CLI checks cover read-only voice state avoidance and inert proposal/review/
selection with no activation command.

The combined Linux candidate collected 88 tests: 68 passed and 20 native Windows
cases were correctly skipped. Companion checks again passed (10 Python, 5 Node,
1,055 Java assertions), plus compile/syntax. These source additions have independent
review; their exact updated Windows matrix is the remaining qualification step.
No playback/listening review, arbitrary program execution, actual brain answer,
Android APK/device run or public remote deployment was performed.

### Voice and proposals: native Windows and Linux passed

[Run 37223693621](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37223693621)
passed for code head `979c0f765a10d1013327959db17997d5d7a5d982`.
Windows executed **84 of 88 tests**, all passing. Its four skips are explicitly
platform-specific: the ability POSIX symlink/FIFO combined fixture, core POSIX FIFO,
voice POSIX FIFO, and the non-Windows-emulation check. Actual Windows symlinks and
junctions were still exercised by the native guard suite; no native guard was
skipped. The supplied pack's native Windows read-only inspection and the CLI's
no-state/no-playback behavior passed. Ability creation, review, selection and
rollback tests also passed without executing proposed source.

Linux executed 68 of 88 tests, all passing, with only the 20 native-Windows cases
skipped. Both platforms also passed 10 relay/bridge Python tests, 5 Node tests,
1,055 Java protocol assertions, and all compilation/syntax stages. The original
five voice assets remain byte-identical to the user's main-branch upload.

These results qualify the documented software mechanics only. A listening review,
new speech synthesis, AI conversation/program generation, actual ability execution,
Android APK/device validation and a public remote connection remain outside the
completed milestone.

## Desktop and local research-export milestone (2026-10-04)

The local desktop exposes existing deterministic controls while NewBrain remains
unavailable. The export adapter reads only explicit, versioned, hash-approved
snapshots already inside Aster's managed workspace. It does not connect to or
command either research app. Those other repositories were not changed or published.

Before publication: the full Linux/headless suite collected 157 tests, with 136
passing and 21 expected skips (20 native-Windows cases and the display test).
A separate run from the actual cloud graphical session passed all 37 dashboard
tests, including native Tk UI construction and repeated/interrupted interactions.
Compilation and the existing 10 relay, 5 Node and 1,055 Java checks also passed.
A socket-denied test verified local file work, queued memory work and reopening
Aster's own identity, pending requests and paused jobs without Internet.

Manual cloud-native UI checks saved a pending request, dismissed a file creation
and verified no file appeared, confirmed the subsequent sandbox write, closed and
reopened the same identity/history, paused/resumed/ran one explicit manual-link
job, and inspected the honest unavailable-export and prerecorded-voice states.
Native screenshots exposed font fallback, clipped footer, cramped result area and
non-ASCII label rendering; those were corrected and the final layout rechecked.
The original supplied voice files remain unchanged. No user computer was accessed.
Windows CI for this exact new milestone must be checked separately; older Windows
success alone does not qualify the new desktop/adapter source.

The exact implementation commit `32f1442074e903c78edd859913a33b941305ba6d`
subsequently passed [Windows and Linux CI](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37229004947).
Windows job `111514507163` collected 157 tests, executed 152 successfully and
skipped five explicitly non-Windows/POSIX fixtures. The actual Tk window and UI
interaction smoke test ran successfully on Windows, as did the socket-denied
outage test and all 20 native Windows file cases. Ubuntu job `111514506996`
executed 136 of 157 with the expected 20 Windows-native and one display skip.
Both jobs also passed compile checks, 10 relay tests, 5 Node tests and 1,055 Java
assertions. Independent review cleared the final controller, desktop, export and
offline scope. The next documentation-only commit records this evidence; its
checks should still be consulted for the final branch head.

## Startup, recovery and RAM candidate (2026-10-04)

The source adds opt-in current-user Windows sign-in registration, a fixed isolated
launcher, durable lifecycle records, auto-start crash backoff, local physical-RAM
admission with hysteresis, and an entirely disabled app-relief diagnostic policy.
No real startup setting, camera, external application or account was accessed.
Registry tests inject fake backends; actual installation still requires the owner's
interactive exact-plan review on their computer.

The final pre-publication Linux run collected 236 tests: 213 passed, 23 expected
platform/display tests skipped. Compilation and companion checks (10 Python,
5 Node, 1,055 Java assertions) passed. Independent review found and fixed optional
startup default-plan routing and a UI startup-error clean-close race. A barrier
regression now proves that UI error handling cannot mark a failed session clean.
Real process-crash fixtures check persistence and no replay; they do not simulate
physical power loss. Native Windows parsing, actual RAM counters and the updated
Tk memory/recovery smoke still require the exact candidate's Windows CI.

Fresh cloud-native UI observation was blocked by the tool approval layer. That
work was paused without an alternative execution route, so no new manual visual
pass is claimed for this increment. The earlier desktop milestone's visual checks
are historical evidence only. Native automated UI testing remains separate.

The first Windows candidate run at `9de998c5d20c10aacd8db8b4f6222459f290db18`
([run 37231056434](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37231056434))
failed with 14 startup-fixture errors and 8 platform skips. The startup path guard
refused the runner's temporary-path spelling as an ambiguous Windows alias before
any registration step. The native Tk, actual GlobalMemoryStatusEx and native
command-line parser tests passed in that run. Linux passed. The test fixture was
corrected to use its owned temporary directory's resolved long path; the
production alias prohibition remains in place. This failure is retained as
evidence and is not treated as a qualified aggregate.

The fixture correction changes only test-owned path normalization and adds native
short-alias rejection coverage. The full Linux suite now collects 237 tests, with
213 passing and 24 expected skips. A Windows rerun is required before merge.

Corrected commit `ea2f0168bd6b88de38f4cecf7210877478a81869` then passed
[run 37231361624](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37231361624).
Windows job `111521488904` executed 229 of 237 tests with eight expected skips;
its real RAM reader, native argument parser, explicit alias-refusal regression and
Tk memory/recovery smoke all passed. Ubuntu job `111521489054` executed 213 of
237 with 24 expected skips. Both passed compile checks, 10 relay tests, 5 Node
tests and 1,055 Java assertions. No real registry setting was touched.

See [permanent test results](TEST_RESULTS.md) for source-pinned machine-readable
receipts and historical evidence. The subsequent documentation-only update records
these results; consult its exact checks before merging.

An archive-integrity regression additionally checks the retained native log's
SHA-256 and reconciles every committed CI count. `test-results/** -text` preserves
its exact bytes on Windows checkout. The focused local archive check passed; this
is receipt integrity, not a new application capability. The next CI run includes
this check in the aggregate (238 collected tests).
