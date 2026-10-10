# Ability proposals: source artifacts only

For the separately implemented bounded JSON recipe test/install/run flow, see [Ability Workshop](ABILITY_WORKSHOP.md). This document describes the original inert source registry; its selected-for-future pointer never executes code.

Aster can preserve an explicitly named existing workspace file as an immutable
proposal. This is a small registry for reviewing versions of a possible future
ability. It does not generate a program, execute one, activate an ability, build
an AR application, install permissions, or provide NewBrain reasoning. The
NewBrain backend remains unavailable. No alternative brain is introduced.

## CLI

Use the same private `--state` directory for every command. The examples below
use the default state directory; `program.py` is relative to its `workspace`.
Only propose source and notes that contain **no credentials or secrets**.

```sh
python -m aster write program.py 'print("source artifact only")'
python -m aster ability propose gripper program.py --permissions-json '["workspace.read"]'
python -m aster ability list
python -m aster ability get PROPOSAL_ID
python -m aster ability review PROPOSAL_ID --verdict approved --note 'Owner source review only; no tests run.' --source-sha256 EXACT_SHA256_FROM_PROPOSAL
python -m aster ability select PROPOSAL_ID
```

`propose` snapshots the bytes read at that moment and records their SHA-256.
Later edits, replacement or trashing of the workspace file do not change that
snapshot. There is no parsing, import, compilation or execution of its contents.
Byte snapshots need not be UTF-8. The file must already exist and must pass the
existing platform-safe `Files.read` boundary, including the 256 KiB limit.

A name has 1–64 characters, begins with a lowercase ASCII letter, and otherwise
contains lowercase letters, digits, `_`, `-` or `.`. A manifest is a JSON list of
at most 16 unique permission labels. Each label begins with a lowercase ASCII
letter and has at most 64 lowercase letters, digits, `_`, `-`, `.`, or `:`.
An empty list is allowed. Labels such as `display.ar` or `camera.read` merely
describe an owner's intended future requirements. They are not recognized APIs,
installed capabilities, OS permission prompts, or authorization grants.

## Versions and declared reviews

To propose another version, name the current latest proposal explicitly:

```sh
python -m aster write program.py 'print("revised source artifact only")'
python -m aster ability propose gripper program.py --permissions-json '[]' --supersedes LATEST_PROPOSAL_ID
```

Versions increase per ability name. Missing, unknown, cross-name, or stale
supersession links are rejected. The earlier bytes, declarations and reviews
remain stored. Approvals do not carry over to a new version, even when its source
bytes match the earlier version.

Review verdicts are `approved` or `rejected`. A nonempty note is required and is
limited to 2,048 UTF-8 bytes. The supplied source hash must match the stored
snapshot exactly. The review is bound to both the proposal ID and that hash.
Every review is appended; a subsequent approval never erases an earlier rejection
or an owner's report of failure. The latest review governs selection eligibility.

Review and test notes are **owner-declared, unverified statements**, not proof
that Aster ran tests or verified safety. Even a note saying "tests passed" leaves
`tests_executed: false`. That field describes this registry, which never runs
artifact tests. Approval also does not establish that the code is safe.

## Selection and rollback

Only a proposal whose latest source-bound review is approved can be selected.
Selection records a version for possible future activation. There is no activation
implementation and no command to execute, load or install the selected source.

```sh
python -m aster ability select NEW_APPROVED_PROPOSAL_ID
python -m aster ability rollback gripper
```

Rollback restores the prior selected version, provided its latest review is still
approved. Repeated rollbacks walk backward through the selection chain; they do
not toggle between two versions. No prior selection, an unknown ability, selecting
the already-selected version, or a rejected rollback target produces an error
without changing the selection history. Rollback does not edit workspace files,
erase proposals or undo any external action.

A later rejection makes `selected_for_future` false even if that proposal retains
the current historical selection record (`selection_recorded: true`). Reapproval
restores that record's eligibility; it still activates nothing. Selection of any
other approved version is an explicit separate action.

All proposal responses report `execution_enabled: false`,
`activation_enabled: false`, `tests_executed: false`, and `permissions_granted: []`.
Statuses are `proposed`, `approved`, `rejected`, or `selected_for_future`.
`review_status` is `unreviewed`, `approved`, or `rejected`.

## Storage and limits

`Abilities(store, files)` exposes `create`, `review`, `select`, `rollback`, `list`
and `get`, as reflected by the CLI. Its Python-only `source(id)` returns stored
bytes without evaluating them. Ordinary CLI results never include source bytes.
`list()` returns the latest 100 proposal summaries. `get(id)` includes the latest
100 reviews with `review_count` and `reviews_truncated`. Older rows remain in the
database; known older proposal IDs remain readable. No history is silently pruned.

Three prefixed SQLite tables hold proposals, reviews and selection history.
Transactions atomically record successful changes and their audit events. SQL
update/delete triggers prevent accidental rewriting of these histories. A failed
mutation attempts to append a minimal `ability.failed` event with the operation
and exception type, without source, notes, input arguments or exception text.
A full or broken database may prevent even that event. Earlier committed history
is retained; a failed creation is not recorded as a successful proposal.

The existing 64 MiB database cap still applies. Snapshots consume that capacity.
State is local, private, unencrypted and persistent, with no purge command. Do not
store secrets in source, permission labels, names, paths or review notes. These
checks are not a sandbox against hostile programs running as the same OS owner.

## Verification

```sh
python -m unittest discover -s tests -p test_abilities.py -v
```

These temporary-state tests cover immutable byte snapshots, bounded declarations,
workspace read restrictions, supersession conflicts, hash-bound declared reviews,
selection and rollback, history retention, failed transactions, an artificial full
database, and restart persistence. Proposed source is never executed. Tests of the
registry are not evidence of NewBrain intelligence or future ability safety.
