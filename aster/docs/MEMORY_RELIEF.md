# Memory relief: disabled planning foundation

Aster should reduce its own memory demand first. Other applications may contain
unsaved work, active games, downloads, or pending cloud synchronization. This
module does not inspect or close them. There are no collectors, automatic triggers,
camera access, or process-control APIs. Status displays may read the static report.

`aster.app_relief.plan_relief` is a pure diagnostic function. It accepts exactly
one typed candidate and optional caller-supplied local presence and keyboard-idle
evidence. It reads no devices, clocks, files, processes, or network services and
has no save, close, force-quit, command, callback, or dispatch capability. It does
not collect images, identify people, record keystrokes, or grant permissions.

## Required evidence, still insufficient for action

The planner reports missing safeguards rather than pretending they are available:

- Explicitly known absence; unknown or present always blocks.
- Independently reported keyboard inactivity for at least five minutes.
- Presence, keyboard-idle, and app-state observations no older than 15 seconds,
  from the same caller-selected clock. Missing or future observations block.
- A verified saved-state claim and explicit no-active-game, no-download, and
  no-sync claims. Unknown state blocks; no generic “save everything” exists.

These thresholds are conservative diagnostic defaults, not proof that a person
is away. A webcam failing to see someone is not, by itself, reliable absence or
permission to close anything. Optional evidence is only caller-supplied data;
the module cannot authenticate it. There is no evidence collector in this build.

Every result is `blocked` with `execution_available=False`, even if all supplied
flags look favorable. There is no dispatch function to enable. One candidate per
call is a diagnostic boundary, not an implemented automatic sequence or queue.

`status()` returns a static capability report with an empty operational allowlist
and all collection, save, close, and send capabilities unavailable. It is safe for
status displays; it does not call the planner or inspect the machine.

## Steam, iCloud, and browsers are examples, not an allowlist

All candidate manifests explicitly report `supported=False` and `enabled=False`.
They grant no access and have no adapters. A generic “another program,” a wildcard,
or a process name is unsupported. Naming an app does not authorize closing it.

Each future app integration needs separate review and narrowly scoped permission,
reliable app-specific evidence of safe state, and a verified supported save/close
mechanism. In particular, Steam must not interrupt a game, download, or cloud save;
iCloud must not interrupt synchronization or pending transfers. A claimed saved
state cannot establish these guarantees. User activity or uncertainty must stop
any future sequence, with state rechecked separately before every single app.

## Browser sessions and email drafts

The browser candidate is also unsupported and disabled. Its optional evidence
requires a fresh snapshot, no dirty forms or editors, no active media or download,
a verified public-session-save claim, and known email-compose state. A future
reviewed session store may retain only verified safe public restoration URLs.
It must exclude private/account URLs, query tokens, credentials, and private mail
content. This build does not accept, save, or restore any URL or browser session;
a boolean session claim cannot enable closure.

When email composition is declared active, a supplied draft-save receipt must
match both the exact current content SHA-256 and integer revision. A fresh recheck
must follow the save and explicitly report no subsequent change. Missing receipts,
hash/revision mismatches, stale or future rechecks, and changed or unknown states
block. A receipt is a diagnostic claim, not proof that a real mail provider saved
anything. The planner always reports the missing live pre-close recheck, even with
positive simulated receipts. No draft-save or auto-send operation exists.

Diagnostic results contain canonical candidate IDs and blocker codes only. They
never echo arbitrary candidate text, restoration URLs, email content, hashes, or
revisions, and the module writes no logs.

## Validation scope

`tests/test_app_relief.py` uses explicitly labeled simulations. It verifies unknown
and stale evidence blocking, independent idle checks, unsaved/busy state blocking,
single-candidate input, unsupported arbitrary apps, dirty browser state, exact
draft receipt/revision checks, privacy of diagnostic output, and the unconditional
absence of execution. It does not validate webcam accuracy, real app state, actual saved
files, reclaimed RAM, safe app shutdown, or the user's workstation. No new camera
or process-control dependency is introduced.
