# Experimental hearing compatibility

## What changed

Aster now carries a separate, immutable generic-source copy from NewBrain commit
`bee67b1cbb94234e31faeb8f2c04477d100a647b` under
`vendor/newbrain_hearing_candidates/<commit>/`. It consists of 20 Python modules
(139,886 bytes), the upstream dependency placement map, its README and retained
third-party notices. Each file is bound by size, SHA-256 and Git blob SHA-1. The
Aster manifest itself has a checked-in integrity anchor. This protects against
accidental corruption, not a malicious editor changing both code and anchors.

The six upstream role maps select exact filenames and versions. No original
source comments or runtime guards were rewritten. Existing production components,
voice assets, old candidate and tested source pins remain unchanged. No changes
were made to NewBrain. The new experiment is opt-in, and no Aster application
module imports it as a reasoning backend.

## Provenance and reuse boundary

The owner's explicit request authorized copying needed NewBrain files into Aster
and testing them. The source repository's recorded provenance identifies the
selected generic modules as project-authored generic source. The preserved
placement map and the manifest identify exact source paths and commit URLs.
This owner-authorized copy does not infer an open-source license or permission
for unrelated third-party redistribution.

The complete original third-party notice is retained. Its Allen model notice is
repository-wide context: no Allen model, biological data or code/data from that
model is included in this hearing candidate. The Allen notice must not be read
as commercial clearance. No upstream personal state, historical corpus, gold,
opaque owner bindings, model weights, credentials, private reports or media were
copied. Newly authored Aster fixtures use explicit public deterministic synthetic
tones and identifiers solely for compatibility tests. They are not a reproduction
of the upstream experiments and do not establish a scientific learning claim.

## How to run

From the repository root, with a new output directory each time:

```sh
python -B -m unittest discover -s tests -p test_newbrain_hearing.py -v
python -B -m experiments.newbrain_hearing.checks --output hearing-results
python scripts/record_upgrade_checks.py --output aggregate-results
```

The check command verifies all source bytes before importing a copied module.
It assembles temporary source directories and launches component checks with
`-I -S -B`. Those lower-level APIs have no exact interpreter-version guard and
can be compatibility-tested on Python 3.12. They use an explicit in-memory test
observer, not a qualified process observer. Component tests intentionally have
all generic modules available and therefore are **not blind-learning evidence**.

On CPython 3.14.4, the same command also runs the original producer, blind arm,
independent scorer, new-query producer, fresh-process retention consumer and
retention scorer in their six separate source roles. Every original entry uses
`-I -S -B`. A 45-second subprocess timeout remains outside the source's original
42-second checkpoint boundary. The parent waits for an arm to exit before
launching cold restoration. The original model bytes are the only model state
passed to the new process; no retraining is allowed. All six learned/control
arms receive identical input PCM and are scored independently.

Use `--require-exact-runtime` to fail rather than skip when the interpreter is
not CPython 3.14.4. The four-job hearing workflow runs Windows and Linux on both
3.12 and exactly 3.14.4, uploads compact JSON outcome reports only, and treats exact-runtime skips
as failure in the exact-version jobs. The foundation workflow also includes the
new source tests and component checks. All changed heads need fresh CI.

## Evidence and limits

- The component suite exercises causal partial PCM windows, no padding, malformed
  chunks, lifetime bounds, forged or rehashed frame refusal, retained observer
  failures, bounded parameter updates, freeze behavior, all six arms, complete
  decision-state round trips, no new teaching, and malformed restore refusal.
- Source admission tests reject modified source, extra files and manifest drift,
  check all six role assemblies, and exercise missing-isolation and wrong-version
  refusal without weakening the guard.
- Exact-runtime tests exercise original full write/readback, once-only output,
  no path escape, oversized payload refusal before writing, separate finite
  normal/emergency budgets, finite reads and cooperative stop behavior.
- Original process reports preserve scores for all 24 initial and 24 fresh
  nuisance queries per arm, plus 24 old-query decision-parity checks. Success
  requires unchanged complete decision state and no retraining. It does not
  require every control to be accurate or manufacture a learning advantage.
- Separate directories and import maps reduce accidental label leakage. They
  are **not an OS sandbox**, filesystem ACL boundary or physical proof of zero
  network calls. Native peak memory, descendant-process isolation and hostile
  process containment remain unqualified. No networking or external model is
  used by the harness or selected source; counter fields alone never enforce
  network access, and existing Aster permission controls are unchanged.
- Known unchanged upstream limitation: the spectral frame validator accepts
  `False` or `0.0` for zero external-call counters, whereas the raw validator and
  independent scorer require exact integers. A named characterization test
  records that behavior; green tests do not claim this missing strictness guard.
  This candidate is not exposed to untrusted frames or promoted into production.
- Tone classification is not speech or music understanding, conversation,
  general intelligence, a personality, consciousness or a working assistant.

## Retained runs

Reviewed compact local outcomes are under `test-results/hearing/compact/`. Reports record
Python version/platform family, exact candidate pin, harness fingerprints, counts, actual exits,
runtime scope and skipped paths. Existing attempts are never overwritten. Detailed local logs and environment metadata
are excluded from this publication.
Upstream raw result histories and old restricted provenance reports are not
republished. Generated synthetic model/PCM and module-census diagnostics remain
in temporary test directories, outside published artifacts; those disappear at
cleanup. Compact scores and process exits are retained in the outcome report.

The initial cloud run uses Python 3.12: component compatibility and source guards
pass, but the original process pipeline is explicitly skipped due to the exact
version guard. Exact-head CI and independent review are separate gates; consult
the latest Actions result before treating the process pipeline as verified.

## Durable, user-invoked experiment

The optional command below saves a fresh synthetic experiment in a separate
local directory. Use CPython **3.14.4 exactly** for `run` and `recheck`. The
parent directory must exist; `run` refuses an existing target directory.

```sh
python -B -m experiments.newbrain_hearing.demo run --state ../aster-hearing-demo
python -B -m experiments.newbrain_hearing.demo inspect --state ../aster-hearing-demo
python -B -m experiments.newbrain_hearing.demo recheck --state ../aster-hearing-demo
```

`run` learns the two configured synthetic tones with all six learned/control
arms, saves their complete state and verifies original cold-process parity.
This explicit durable command is an exception to the temporary-state behavior
of the compatibility checker: its generated synthetic PCM, snapshots and local
process diagnostics remain in the directory you selected. It never imports
upstream private state or writes Aster's production memory. Keep this directory
outside the checkout; do not publish it as part of the source tree.

`inspect` can run read-only on Python 3.12. It verifies the receipt, pin, saved
source and input bytes, then shows bounded score totals. It performs no model
execution. `recheck` starts fresh original retention/scoring processes using
saved state, with no new teaching. It repeats the saved queries rather than
sampling a new test corpus. Every recheck writes a separate attempt directory;
previous state and results are not overwritten. Corrupt or incomplete state is
refused, not regenerated or silently repaired.

State admission checks fixed relative paths, exact schemas and fingerprints,
file-size bounds and original role-source bytes. Symlinks, hard-linked files,
Windows reparse points and `.aster-state` destinations are refused. These are
accidental-corruption and misconfiguration controls, not a defense against a
hostile concurrent filesystem writer. The same process/resource limitations
listed above remain. No microphone, live browser, network, background job,
external model or production reasoning is activated.

Exit 0 means the requested operation succeeded. Exit 1 means failed/refused.
Exit 2 means the exact runtime is unavailable (or command arguments are invalid).
Wrong-runtime `run` and `recheck` report `UNAVAILABLE_EXACT_RUNTIME_REQUIRED`
before reading or writing experiment state. A successful `inspect` is only a
saved-state integrity check, not a new learning result.

The 32 durable-CLI unit tests use mocked successful model execution on the
cloud's Python 3.12, with real pinned source staging and receipt validation.
They do not qualify actual learning or the guarded runtime. Exact-version CI
separately runs `run`, `inspect` and `recheck` as three commands on both Windows
and Linux. CI uploads only their compact reports and receipt, never the whole
state directory, model snapshots, PCM or module census.

## First real exact-runtime result

[CI run 37420597870](https://github.com/rmcmurrer81/aster-workstation/actions/runs/37420597870)
passed on Windows and Linux for code head
`7951aed2cc38d93945f976dcc4503a49c2c60add`, using CPython 3.14.4 and the unchanged
isolated original entries. The durable `run`, `inspect` and separate `recheck`
commands all passed. The [compact result](../test-results/hearing/compact/2026-10-06-real-ci-7951aed.json)
retains the measured totals and run/job identifiers without raw state or logs.

On both platforms, the spectral learned arm answered 24/24 initial and 24/24
fresh nuisance queries correctly. DSP and indexed controls also answered 24/24;
this test demonstrates no advantage over those controls. Raw learned answered
12/24, and the two frozen controls abstained on all 24. All six arms reproduced
24/24 earlier decisions after cold restoration, with unchanged decision state
and zero new teaching. The later durable recheck also preserved those decisions.

These results cover one deterministic pair of synthetic frequencies and supplied
features, not real recordings, novel frequencies, speech or general hearing.
Later heads still need their own CI gates; this receipt identifies exactly the
code revision and run it measured.
