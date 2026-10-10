# Aster desktop control panel

Run from the checkout in a graphical desktop session with Python 3.10+ and Tk:

```sh
python -m aster --state /absolute/private/aster-state desktop
```

On Windows, use a local fixed NTFS state folder outside OneDrive, for example:

```powershell
$state = Join-Path $env:LOCALAPPDATA 'Aster\state'
python -m aster --state $state desktop
```

Keep using the same state path. It contains Aster's independent identity, pending
requests, memories, job and file history. Opening the window does not load a model,
create a network listener, contact an app, or start a background job runner. No
installer or package download runs. Python without Tk can still use the CLI; a
missing display produces an explicit startup error instead of a headless server.

## What each tab does

- **Requests:** save your text as `waiting_for_newbrain`. The saved request list
  is your text, not a conversation transcript of generated answers. Aster does not
  silently send these requests to a fallback model or turn them into jobs.
- **Workspace:** read and edit UTF-8 files inside `<state>/workspace`, up to
  256 KiB. Use a relative path such as `projects/main.py`. Source text can be
  saved, but no program can be launched. Read asks before replacing an unsaved
  editor draft. Save, overwrite and recoverable trash require review and explicit
  confirmation; cancelling the review changes nothing.
- **Job queue:** choose one finite action and enter its exact JSON fields. Add to
  queue saves it without executing. **Run next once** reviews and runs the oldest
  queued job, regardless of which row is selected. It never drains the queue.
  Pause, resume and cancel act on the selected job before execution only.
- **History:** inspect the most recent 100 entries for requests, jobs, changes,
  memories or events. **Undo selected change** applies only to an applied file
  change and is confirmed separately. New edits are never silently overwritten
  by undo. **Reconcile interrupted** checks journal bytes and labels leftover
  running jobs interrupted; it never replays jobs or overwrites conflicts.
- **Research exports:** review and register a supported capability manifest that
  already exists in Aster's workspace; choose that exact registered app/project;
  review and select a matching local JSON export. Confirmation is bound to the
  reviewed SHA-256. Inspect shows record metadata; Read shows excerpts only if the
  manifest includes that capability. These are immutable owner-selected exports,
  not installed/live app integrations. Provenance is owner-declared, and research
  text remains untrusted data, never instructions or authenticated facts.
- **Voice & status:** inspect the pinned prerecorded voice audition or read local
  app registrations. A successful audition inspection shows a local preview path
  for you to copy and open manually. Voice inspection does not launch a browser/player,
  synthesize speech or claim the sample is an AI response. Catalog registration
  does not grant research access or command permissions.
- **Browser:** type an exact public HTTP(S) URL or search query, review the full
  destination and browser-session warning, then explicitly confirm one handoff.
  Cancel is inert. The outcome distinguishes an accepted launch, failure, and
  uncertain timeout; page loading is never claimed. No page content is read and
  no background browser job is saved. See [Browser actions](BROWSER_ACTIONS.md).

## Explicit job examples

Select the matching action and enter these arguments:

```json
{"query": "robot gripper compliant mechanism"}
```

`research.links` produces manual search links only. No pages are fetched or
opened automatically.

```json
{"text": "This project uses metric units", "source": "user"}
```

`memory.append` records an explicit memory. It does not infer a memory from a
pending conversational request.

```json
{"path": "notes/example.txt", "text": "A local note"}
```

`file.write` reviews whether it will create or overwrite the target when you
choose **Run next once**. A queued write never executes just because a request was
saved or the window opened. Default budget is five seconds; valid values are
0.1–30 seconds. This is a measured wall-time budget, not a hard timeout or OS
resource sandbox. An active local operation cannot safely be paused midway.

## Export control details

The manifest declares `workspace_research_export`, schema/adapter version 1,
recipient `aster`, the exact supported app ID, exact projects, and explicit
`research.inspect` / `research.read` capabilities. The export must match the
selected manifest's app, project and recipient. The full preview, capability
scope and digest appear in a scrollable confirmation window; **Cancel** has the
initial keyboard focus. File changes after preview invalidate the approval.

Use **Refresh exports** to load the registry. The dropdown contains the most
recent 100 enabled registered capabilities. **Clear selection** removes the
current default selection while retaining history; the snapshot remains readable
by its exact ID while the capability is enabled. **Disable capability** revokes
that local capability, including reads through its selections. Neither control
changes permissions in an external app. Detailed schema examples and CLI controls
are documented in [App export adapters](APP_ADAPTERS.md).

## Local state and interruption

The window owns one persistent state lock. Close it before running a CLI command
against the same state directory. Multiple windows cannot write the same state.
SQLite, `Files`, jobs and export adapters all stay on one dedicated worker thread;
Tk only handles presentation. Controls disable while an operation is outstanding,
and the worker also rejects duplicate submissions until the completion is
consumed. A short exact-duplicate click guard also prevents a queue button
double-click from submitting twice when the first local operation finishes quickly. A confirmation ticket is one-use and tied to the exact operation.

Closing waits for an accepted operation to finish and releases the file/database
handles. It does not terminate a write halfway through. Draft editor text is not
saved on close; a close dialog warns about this. Saved state is retained. No jobs
are resumed or replayed on restart. After an abrupt process stop, inspect History
and explicitly reconcile interrupted work before retrying.

File protections are inherited from the existing `Files` implementation: scoped
paths, bounded regular files, link/reparse rejection, journaled replacement,
recoverable trash and conflict-aware undo. Aster's state is owner-local but not
encrypted. File contents, old versions, research snapshots and requests remain in
the journal; there is no purge UI. The protections do not claim a security boundary
against hostile programs running as the same OS user. Never place credentials in
this state folder.

## Implementation and verification

`aster.desktop.launch(state)` imports Tk lazily and returns an exit code after
closing. The CLI must call it **before** opening a `Store`. `Dashboard` is a
synchronous display-independent controller. `DashboardWorker` owns it on one
thread, provides nonblocking `submit` / `poll` / `close`, and allows a final
`wait_closed` outside the event loop. Full history rows are loaded only on demand;
list queries omit file BLOBs and truncate text previews.

```sh
python -m unittest discover -s tests -p test_dashboard.py -v
python -m unittest discover -s tests -v
python -m compileall -q aster tests
```

Controller and worker tests cover persistence, lock contention, path and byte
limits, confirmation dismissal/replay/conflict, queue/run-one/pause/resume/cancel,
explicit recovery, exact export scope/digests/revocation, startup/error/shutdown
and repeated clicks. The native smoke creates the actual seven-tab Tk window and
exercises request, file, queue and export-status UI paths. A non-Windows execution
without a display explicitly skips that test; Windows qualification treats missing
Tk or failure to open its window as a failure. Headless controller tests alone are
not visual or Windows qualification, and no test implies access to the user's PC.


## Optional remote text while the desktop stays open

The default desktop does not poll any network service. After separate owner-approved
relay and credential setup, launch `aster_remote.workstation --desktop` with the
existing `--relay`, `--state` and workstation-token configuration described in
[`remote-companion/README.md`](../remote-companion/README.md#desktop-delivery-and-shutdown-guarantees).
The outbound poller submits only bounded text to this desktop's single state owner.
It never opens a second writer or runs remote commands. Incoming messages remain
pending for NewBrain and appear on refresh. Local confirmation dialogs defer their
commit; shutting down leaves uncommitted relay messages available for retry until
expiry. Do not run a separate standalone bridge against an open desktop state.


## Supporting modules

The Voice & status tab includes the six local support modules. The operation selector loads editable argument examples; each mutation requires an explicit one-use confirmation. Preview hashes are still required for imports and media writes. The separate Browser tab has its own explicit external handoff review. See [supporting modules](SUPPORT_MODULES.md) for complete working boundaries and CLI alternatives.
