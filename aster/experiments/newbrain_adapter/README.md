# Pinned NewBrain component lab

This is an **opt-in, isolated engineering test setup**, not Aster's live brain.
The default reviewed source pin is
[`df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef`](https://github.com/rmcmurrer81/newbrain/commit/df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef).
The original
[`bd0c5a34ade90470fb2bb0025af30cf4a51881bd`](https://github.com/rmcmurrer81/newbrain/commit/bd0c5a34ade90470fb2bb0025af30cf4a51881bd)
pin remains available for exact restore and rollback. All eight copied files are
byte-identical between those pins. A later repository pin does **not** make these
components a newer learning architecture.

- `learned_value.py`: eight pure-Python trainable numeric coefficients, bounded
  provenance-bearing lessons, explicit corrections and snapshot/restore.
- `event_observer.py`: before/after observations around that exact learner.

Copied upstream files are byte-for-byte unchanged. Their historical SOURCE ONLY
comments and direct-script guards remain in place. The lab calls their reusable
interfaces through a separate Aster runner; it does not run, repair or claim to
pass NewBrain's held Stock025 runtime qualification. The copied
`runtime057/STATUS.json` preserves that failure. Later whole-runtime candidates
are not imported or enabled by this adapter.

## Run the actual checks

From the repository root, using Python 3.12:

```console
python -B -m experiments.newbrain_adapter.run_checks
python -B -m experiments.newbrain_adapter.run_checks --report result.json
```

The suite includes 32 unchanged upstream exposed engineering fixtures, 13 original
Aster integration tests, and the additional transactional persistence/migration
cases in `test_persistence.py`. The retained result receipt records the exact
collected count, failures and platform skips. New checks cover:

- Real numeric staged updates, explicit correction links, owner isolation,
  bounded learner/history capacity and no eviction
- Exact data-only observer history, failed attempts, original/copied inputs,
  captured boundaries, UNKNOWN after-state, and source-bound receipts
- Atomic local writes, partial/short writes, fsync/replace failures, and genuine
  process exit immediately before/after replacement
- Cold-process restore, correction after reopening, old/new pin migration,
  unchanged rollback bytes, corruption refusal and incompatible-pin refusal
- No learning calls during restore, no conversation/backend activation, and
  preservation of a separate temporary Aster identity and explicit memory

Only synthetic state is written to fresh temporary directories. No learned user
state is committed. [`test-results/2026-10-05-component-persistence/`](../../test-results/2026-10-05-component-persistence/)
retains each development run, full logs, exact commands, UTC times, Python/OS
versions, source digests, implementation decisions and limitations. Earlier
`linux-result.json` and `reports/` remain historical evidence, not the current
suite's result.

Suite time is **not inference latency**. Linux peak RSS is the parent Python
process's lifetime maximum, excludes children, and is not model-only RAM. Windows
results require a separate Windows run; a symlink test explicitly skips if that
platform cannot create the synthetic link. These small standard-library checks
require no GPU, package installation, network, provider or large download. They
do not establish the whole application's memory needs on an 8 GB computer.

## Transactional Aster APIs

The Aster-owned `persistence.py` stages changes in private reconstructed models;
it never edits the upstream implementation.

- `session.learn(event, consequence, checkpoint_path=None)` stages an unobserved
  numeric update. It commits only if the complete learner and session checkpoint
  can be represented and, when requested, successfully written.
- `session.observer(experiment_id=..., arm_id=...)` returns an Aster transactional
  observer. Reusing that identity returns access to its retained history.
  `observer.observe_learn(meta, event, consequence, checkpoint_path=None)` stages
  the actual upstream observation/update. `history()` and `compact_record()`
  return independent data copies.
- `session.checkpoint()` returns canonical `aster.newbrain.session-state.v2`
  bytes containing the learner and all retained observer histories.
  `source.restore(raw, owner_id=...)` restores them exactly, without invoking
  learning or inventing missing observations.
- `session.save(path)` saves the complete current v2 checkpoint using a private
  sibling temporary file, complete write, flush, file fsync and `os.replace`.
  Existing foreign-owner, cross-pin, corrupt or symlink targets are refused.
- `session.snapshot()` remains the original learner-only
  `aster.newbrain.value-state.v1` format for old checkpoints and callers. It does
  **not** export observer history. Restoring v1 begins with no observer records.
- `session.model` remains legacy direct upstream access. Direct `.model.learn()`
  is **nontransactional** and bypasses the new guarantees. The original capacity
  failure test intentionally retains that upstream limitation.

Capacity, serialization and file-write failures never publish staged learner or
history changes. Ordinary invalid/failed observations can retain a complete
`ROLLED_BACK` failure record, then re-raise the original error. The live learner
stays unchanged. If an upstream operation changed only the staged model before a
later failure, its actual captured boundaries/receipt remain in the failure
record. If the after-state was unavailable, it remains `UNKNOWN` and null; the
adapter never substitutes before-state or calls the failed attempt completed.
Failure records that cannot fit or cannot be written are not committed.
Interrupt/exit exceptions abort without publishing an observation.

This is bounded custody: four observers, four attempts per observer, the original
32-update ceiling, the original 32,768-byte learner snapshot limit, bounded input
and summary sizes, and a 2 MiB complete session envelope. Byte capacity can run
out before count ceilings. There is no eviction, automatic retry, compaction,
reset, unlimited growth or silent schema expansion.

## Local file and integrity limits

The writer is for a caller-selected trusted local directory and a **single
writer**. Session methods serialize in-process safe API calls; raw `.model`
access and separate processes are outside that lock. There is no cross-process
locking, authenticated original-run proof, hostile same-account filesystem
boundary, network-filesystem guarantee or encryption. Checksums plus source and
arithmetic validation detect corruption/inconsistent edits; an attacker able to
replace an entire internally consistent checkpoint is outside this threat model.

Injected failures before successful replacement preserve the old file exactly.
Process-exit tests establish that reopening sees an old or new complete file at
that boundary. A crash before replacement can leave a private `.pending` sibling;
it is not a checkpoint and is never automatically loaded or cleaned by the lab.
No fallible file operation follows successful replacement. Directory-fsync,
hardware power-loss survival and production durability are **not qualified**.

Observer exception types/messages are bounded data, never imported exception
classes or executable pickles. Original upstream qualification/publication flags
remain unchanged. Aster's separate persistence tests do not upgrade those flags.

## Explicit migration and rollback

Only the two explicitly reviewed pins above have a migration route:

```python
new_source = ComponentSource()
new_session = new_source.migrate(old_bytes, owner_id=owner_id, from_pin=LEGACY_PIN)
```

Migration first validates the original checkpoint using its declared old source,
checks byte identity of both learner and observer source, changes only the outer
pin, and validates the complete result under the new source. Both v1 and v2 are
supported. No training, file overwrite, history deletion or automatic migration
occurs. The reverse reviewed route also works, and unchanged original bytes
remain a valid independent rollback checkpoint. Saving across an existing old-pin
file is refused: use a separately chosen destination and retain the old file.

Unknown pins, source differences, cross-owner state and unknown schemas refuse.
Future architectures need their own reviewed migration and acceptance fixtures.
This is an actual tested **identical-component source-pin migration**, not an
advanced NewBrain architecture migration or proof of compatible future cores.

## Capability boundaries

This is two numeric components, **not the complete NewBrain**, a biological brain,
learned personality, consciousness or subjective emotion. Lessons are explicit
fictional numeric fixtures. A gradient update is real but does not establish
semantic learning or held-out intelligence. A correction adds a linked update;
it does not erase or perfectly unlearn the earlier event.

There is no conversational decoder, cue learner, NumPy path, whole brain, body,
audiovisual interpretation, Qwen comparison, canned dialogue or fallback model.
`aster.backend` remains unavailable, without autonomy or a fallback. No production
code imports this lab. Its source loader is an integrity check for reviewed
source, not an adversarial sandbox. The adapter receives no Aster Store,
file/tool executor or credentials. Its optional local checkpoint writer is not a
permission grant to operate the workstation or other user files.

## Sources and rights

Every copied file has a source URL, Git blob SHA-1, SHA-256 and byte count in
`vendor/newbrain_snapshots/<pin>/manifest.json`. Retrieval checked Git blob
identity; the loader checks the committed manifest digest and all copied bytes
before executing any component. Source filenames/direct-script guards are not
rewritten. Upstream module dependencies are bound to each private module instance
without adding generic names to `sys.modules` or changing `sys.path`.

The repository owner explicitly requested this copy of their reusable source.
No broad open-source licence is inferred or added. Upstream
`THIRD_PARTY_NOTICES.md` remains for context; its Allen model and other restricted
data are not included. No private person state, identity snapshot, learned
checkpoint, event history, voice, media, credentials, biological parameter file
or atlas was copied. Generic status documents record limitations, not runtime
grants. Exact published source paths are recorded rather than inventing entries
in the older upstream provenance registry.
