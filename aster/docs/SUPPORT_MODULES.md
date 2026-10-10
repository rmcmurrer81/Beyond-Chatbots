# Six local support modules

This increment adds useful deterministic tools around the existing NewBrain-only
shell. It does not qualify NewBrain conversation or program generation. No second
model, external account, background runner, user-machine install or public hosting
is activated.

## Open and use

In the desktop, open **Voice & status → Local support modules**. Select a module
and operation, edit its example JSON arguments, and choose **Review / run local
action**. Read operations return immediately; each local mutation has a separate
one-use review dialog. Cancel and window close do not approve an operation.
Imports and WAV trims require a hash returned by their explicit preview command.

The matching CLI is:

```text
python -m aster --state <private-state> support catalog
python -m aster --state <private-state> support memory search --args-json '{"query":"voice"}'
python -m aster --state <private-state> support resources status
```

Every catalog entry includes its exact argument example and whether it changes
local state. Supply `--approve` for that one mutation after reviewing the arguments.
Shell quoting differs in PowerShell; the desktop JSON editor avoids that issue.
Close the desktop before using the CLI on the same state: the existing single
writer lock is unchanged. These commands do not connect accounts or grant access
to folders outside Aster's managed workspace.

## Actual coverage and limits

| Module | Available now | Explicit boundary |
| --- | --- | --- |
| Ability Workshop | Immutable JSON text recipes, isolated in-memory tests, source/test/interpreter-bound review, versioned installation, rollback, exact-input one-use runs | No arbitrary Python, shell, filesystem recipe writes, downloaded-code execution, NewBrain code generation or OS sandbox |
| Private Memory | Case-insensitive literal search, decision/preference/history labels, dates/sources, correction families, hide/recoverable-delete/restore | Not semantic search, learned recall, encryption or secure erasure; retained records remain inspectable by exact ID |
| Reference Library | Explicit workspace-folder approval and file lists, cached UTF-8 TXT/MD/JSON passages with exact path/line/column/hash citations, freshness reporting, revocation | No implicit scan of personal folders, PDF/OCR or live Zotero adapter; cached bytes remain after revocation |
| Communications Desk | Hash-reviewed local email/calendar/GitHub export snapshots, scoped search, source/date display, immutable local draft revisions and unsent outbox | Common owner-prepared export schema, not provider-native imports; no OAuth, live inbox, calendar updates or sending |
| Media/Voice Workshop | PCM WAV metadata, exact-frame preview/trim to a separate journaled output, conflict-aware undo, reuse of existing integrity-checked voice inspection | Small workspace files only (256 KiB); no FFmpeg execution, video editing, live STT/TTS, voice generation or avatar control |
| Resource Supervisor | Existing queue with a pending-job ceiling, optional owner-estimated RAM request and reserve, on-demand single execution, pre-start pause/cancel | Admission estimates, not hard OS RAM/time isolation; GPU executor unavailable; no process launch/kill or automatic app shutdown |

See [Ability Workshop](ABILITY_WORKSHOP.md), [Memory and Library](MEMORY_LIBRARY.md),
and [Communications and Media](COMMUNICATIONS_MEDIA.md) for schemas, examples,
tests and the checked VideoStudio reuse boundary. BlueBook remains an optional
specialist research-export source under the existing app-export interface.

## Resource Supervisor

Defaults are a 512 MiB maximum estimated per-job request, 256 MiB available-RAM
reserve and 256 pending jobs. Configurable bounds are 1–4096 MiB, 0–8192 MiB and
1–1000 pending jobs respectively. An optional `ram_mib` request is checked against
current available physical RAM after the existing high-pressure guard permits
execution. A lowered policy also applies to already queued requests. Insufficient
or unknown RAM leaves the job queued; retry is explicit. `gpu_mib` must be integer
zero; no GPU capacity is invented.

Legacy jobs without a RAM estimate retain their existing finite-action bounds
and memory-pressure guard. They are honestly labeled as having no RAM estimate.
All jobs, including legacy callers, respect the pending queue ceiling. Paused jobs
count toward that ceiling until resumed/completed or cancelled. Cancellation does
not interrupt an active atomic write; completed work is never replayed.

```text
python -m aster --state <private-state> support resources queue --args-json '{"action":"research.links","args":{"query":"motor specifications"},"budget":5,"ram_mib":16,"gpu_mib":0}' --approve
python -m aster --state <private-state> support resources run-one --approve
```

`budget` remains measured wall time after one bounded operation, not a hard
timeout. Resource settings are local Aster policy, not operating-system security
or application settings.

## Regression and evidence

`python scripts/record_upgrade_checks.py --output <new-directory>` runs the full
foundation, pinned NewBrain components, disabled-candidate admission, complete
companion groups and compilation. Windows/Linux Actions use this same runner.
The native support UI test must run on Windows; headless Linux clearly records a
skip. A separate dot-cloud native Linux run covers the actual Tk window.

All new check receipts, exact source hashes, UTC timestamps, commands, complete
logs, skips, failed attempts and fixes are retained under
`test-results/2026-10-05-support-modules/`. None establishes that these features
have been installed or exercised on the owner's Windows PC.
