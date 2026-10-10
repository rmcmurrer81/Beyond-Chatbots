# Durable job effects and read-only inspection

This branch is a source-reviewed reliability candidate. New runtime checks are
UNRUN because the single desktop process probe failed before execution.
It is not a tested release and does not establish a reproduced cold-start defect.

## Job effects

A memory job saves its memory row, audit event and job_effects link in one
SQLite transaction. A file job saves its prepared journal, audit event and
job_effects link in one transaction before replacing external bytes. File
replacement remains outside SQLite; the journal records prepared, applied,
not_applied, conflict, indeterminate and undone states. If before and after
bytes are identical, recovery reports indeterminate: matching bytes cannot show
whether replacement occurred.

The helpers own their transactions and reject an already-active caller
transaction before creating an effect. A nested sqlite3 connection context
cannot provide independent rollback protection. Callers that need a larger
transaction must not invoke these durable effect helpers inside it.

Use Store.job_effect(job_id), normal job history, or the read-only inspector to
find durable IDs. Explicit job recovery marks a running job interrupted, retains
its linked memory_id or change_id, and reports timing_unknown when no duration
was committed. It never retries work or claims recovered success. File recovery
is still an explicit, separate reconciliation against current file bytes.
A result's saved effect state is a historical snapshot; normal job history
returns the current journal state.

An unlinked legacy job has unknown effect state. No matching by text, timestamp
or pathname is attempted. A committed memory ID is evidence of insertion, not
evidence of a finished job. A prepared change ID identifies the intent, not proof
that replacement happened. Repeated recovery must create no additional effects.
Existing manual pause/resume/cancel, resource admission, direct memory correction,
file undo and external-edit conflict checks remain in place.

## Inspection

Run `python -m aster --state PATH inspect-state --limit 20` for a bounded
read-only persisted-state report. Output can contain private local history;
keep it local and do not upload it as fixture evidence.

The explicit inspection command bypasses Store and Lifecycle initialization:
it must not create identity, migrate schema, write audit events, prune history,
increase database caps, recover files or replay jobs. The SQLite URI uses mode=ro,
never immutable for a database that could change. Query-only mode and bounded
queries provide a read snapshot, with per-section unavailable diagnostics.
SQLite WAL read-only access can require existing readable sidecars or reader
bookkeeping; the inspector does not promise zero operating-system metadata writes.

Inspection shows persisted database records only. It does not check file bytes,
repair corruption, infer missing records or certify startup health.
An interrupted job may still be running in another process; use the persisted
status as evidence, not as a live process assertion.

## Qualification status

The existing single-operation saturation test is not a cold-start test.
The new tiny capped fixtures must first demonstrate SQLITE_FULL across an
actual reopen and a Lifecycle.start attempt before any startup defect is claimed.
Compound failures, missing/corrupt tables, bounded output, live WAL reads and
native Windows behavior need actual execution. Fixture caps are deliberately
small and never apply to personal databases.

The crash fixtures use real subprocess os._exit at important memory/file commit,
replacement and result boundaries. Process exits do not establish power-loss
durability. Full evidence and a fixture-only recorder are retained in the repo.
See test-results/reliability-20261008/source-status.json for actual run status.

No NewBrain files or learning/model jobs are part of this change. No CI dispatch,
PR creation or main merge is authorized for this branch.

## Retaining a future run

After the coordination window is released and the executor works, run only the
fixture recorder from a reviewed checkout:

    python scripts/record_reliability_checks.py --output test-results/reliability/FRESH_RUN --revision CHECKOUT_SHA

Use a fresh output directory. The recorder refuses to overwrite prior evidence.
It selects six exact fixture suites, retains stdout, stderr and per-case outcomes,
and reports failures, timeouts and skipped cases. Its default execution budget is
120 seconds total and 20 seconds per suite; termination grace is separately
reported. Resource observations are scoped to what the platform exposes and
missing measurements remain null. The supplied revision is owner-reported;
before/after source hashes bind the files that were actually read.

An overall UNRUN can include passing cases when platform-specific cases were
skipped. Retain those distinctions and review logs before uploading any evidence.
The fixture worker rejects network socket operations; that hook does not
propagate into independently spawned fixture subprocesses. The selected test
sources must therefore remain reviewed and restricted to synthetic local state.
