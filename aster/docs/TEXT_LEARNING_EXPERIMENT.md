# Optional synthetic text-learning experiment

This is a separate, opt-in Aster-owned learning lab. It does not enable Aster's
production brain, answer saved prompts, dispatch jobs, use Qwen, or load anybody's
NewBrain identity, memories, weights or corpus. Existing hearing, browser and
32-update value-component experiments are unchanged.

## Run, inspect and reopen

The numerical commands require **CPython 3.14.4 and NumPy 2.3.5** on Windows or
Linux. Exact CPython **3.12.14** is also a Linux compatibility lane. No other
Python or NumPy versions are admitted. GitHub's official runtime catalog provides
3.12.14 builds for Linux only, so that version cannot supply the Windows CI lane.
NumPy is an optional dependency, not a requirement of the base Aster application.
Use a separate virtual environment created with the selected exact Python
version, activate it for your platform, then install the exact binary dependency:

```console
python -m pip install --only-binary=:all: -r requirements-text-learning.txt
python -c "from pathlib import Path; Path('.aster-state').mkdir(exist_ok=True)"
python -B -m experiments.newbrain_text.demo run --state .aster-state/text-demo --owner synthetic_aster
python -B -m experiments.newbrain_text.demo inspect --state .aster-state/text-demo --owner synthetic_aster
python -B -m experiments.newbrain_text.demo recheck --state .aster-state/text-demo --owner synthetic_aster
```

Create the parent directory first, as shown above. Run creates a **new** state
directory beneath that existing parent and refuses an occupied destination.
Inspect validates the saved report and model envelope without importing NumPy or
executing the model. Recheck starts a separate Python process, restores all five
checkpoints, and verifies recorded decisions with training, model initialization
and the selected random-number entry points disabled. It does not retrain.

Owners must be explicit synthetic identifiers beginning `synthetic_`. The lab
accepts only its fixed checked-in curriculum, not personal text or external
training data. State is bound to its owner, source, vocabulary, curriculum and
protocol. It is not silently migrated across changed source or protocols.

The CLI prints a compact JSON summary. Complete synthetic outputs and traces are
in the chosen directory's `report.json`; serialized parameters are in
`state.json`, with both bound by `manifest.json`. These generated state files are
not committed or uploaded by the qualification workflow. Keep them in a trusted
local directory. They are checksummed, not encrypted or authenticated against an
attacker who can replace the whole directory consistently.

## What is actually learned

The fixed task maps red/blue and coral/azure cues to the one-token answers
warm/cool, with short wording variations. All vocabulary, old/new examples,
held-out prefixes, scoring rules and the single seed **221086** are hashed before
model construction. There is no seed search or outcome-driven retuning.

- One freshly initialized model starts at zero updates.
- 64 old-only warmup updates create a baseline.
- Three arms restore that exact baseline without reseeding. Each performs 48
  real updates, ending at 112, for **208 actual SGD calls across the campaign**.
- Interleaved, blocked and error-prioritized arms receive equal exposures.
- There are six unique rows per teaching split. Each eight-row batch contains
  eight explicitly declared duplicates of one row. Duplication is not new data.
- Held-out prefixes are never training inputs or ordering feedback. All six
  exposed new rows are probed before each pass, and complete outputs are retained.

The goal checks are deliberately narrow: improve new exact-match count, retain
every previously correct old answer with a nonzero denominator, and improve
held-out exact-match count over the frozen baseline. A goal pass does not mean
all answers are right, demonstrate method superiority, or establish broader
scientific/general-language capability. A goal miss is reported separately from
engineering completion; failed answers are never replaced with expected ones.

The initial fixed-seed development run tied across all three methods: new answers
improved from **3/6 to 6/6**, held-out answers from **3/6 to 5/6**, and old answers
remained **3/6**. Retention was **3/3 previously correct answers**, not 6/6 old
accuracy. These are one small synthetic block, not independent real-world trials.
Final platform receipts, including any differences or failures, are authoritative
for the exact checked source.

## Reused source and separate adapters

Three generic modules are copied byte-for-byte from NewBrain commit
[`4a5c8396f820d8caf81b9ccba850617ae9e60489`](https://github.com/rmcmurrer81/newbrain/commit/4a5c8396f820d8caf81b9ccba850617ae9e60489):

1. `dialogue_decoder.py`: actual from-scratch token-RNN SGD, generation and state
   format. Hidden size 64, embedding size 16, at most 96 vocabulary tokens,
   64 context tokens, eight examples per update and 16 generated steps. It is
   byte-identical to NewBrain's earlier 083 decoder; repinning is not an
   architectural improvement.
2. `method_order.py`: only its relative `pass_blocks` interface drives Aster's
   teaching. A separately named adapter ranks Aster's own exposed feedback.
3. `probe_ledger.py`: preserved for exact source/interface qualification. Its
   original 086 ledger is **not** used for actual Aster state because its fixed
   42-way distributions and 10,720-based counters do not describe this fresh lab.
   Aster's separate bounded ledger records its actual counters and distributions.

The selected modules and exact hashes are under
`vendor/newbrain_text_candidates/4a5c8396f820d8caf81b9ccba850617ae9e60489/`.
Admission checks their exact bytes, manifest, complete selected-file roster and
symlink/junction boundaries before loading. No whole NewBrain runner, capacity
policy, private parent checkpoint or research-owner state is imported. Aster
never writes to NewBrain.

This is owner-authorized reuse of project-authored generic code. No public
license grant is inferred. The unchanged upstream third-party notice is retained
for provenance; its Allen parameter-file discussion refers to an upstream file
that is **not present in this snapshot and not used here**. Different distribution
or commercial-use questions require a separate rights review.

## Bounds, persistence and limitations

The actual curriculum has 16 vocabulary tokens. At the decoder's maximum
vocabulary its parameters occupy 103,680 bytes; this is not measured process RAM.
The complete upstream model serialization is bounded to 128 KiB, while the lab's
five-checkpoint envelope is bounded to 1 MiB and full report to 2 MiB.

Publication stages complete files in a sibling directory and uses an exclusive
atomic directory rename. Existing targets, malformed/corrupt content, foreign
owners and unsupported bindings are refused. This is trusted-local-directory
engineering, not a hostile same-account filesystem, network filesystem, power-loss
or cross-process access-control guarantee. Platform-specific directory durability
and publication failures remain explicit; never interpret a reported error as
permission to overwrite an existing destination.

Cold recheck allows absolute/relative floating-point tolerance of `1e-12`, while
requiring exact parameter bytes, counters, tokens and decisions. Its deadline is
30 seconds. Version pins do not imply identical native NumPy builds or bitwise
cross-platform floating-point calculations. Fixed-size loops and deadline checks
are not an OS memory/CPU sandbox.

There is no ordinary conversation, program generation, semantic memory retrieval,
automatic lifelong learning, autonomous capacity growth or brain replacement.

## Qualification and retained results

```console
python -B scripts/record_text_learning_checks.py --aggregate --output test-results/text-learning/local-attempt-01
```

Choose a fresh output directory for every attempt. The recorder runs the existing
full Aster aggregate, dependency-free boundary tests, actual numerical tests,
durable CLI run, inspection and a genuine cold-process recheck. Numerical tests
must actually run without skips. It fingerprints the full qualification tree
before and after and fails if source changed while checks ran.

The optional GitHub Actions workflow performs the same checks on actual Windows
and Linux with CPython 3.14.4, plus Linux with CPython 3.12.14. All three lanes pin
NumPy 2.3.5 and must actually execute numerical tests. It uploads only compact outcomes,
source-tree digests and summaries; private temporary model state, raw diagnostics,
absolute environment paths and full provenance inventories are excluded. Stage
time measures the whole stage, not model-only latency or peak memory. The recorder
bounds diagnostic capture and the direct child, not arbitrary descendant trees;
the fixed tests own their child cleanup and CI adds a job-level timeout.

Historical development attempts and reviewed platform receipts are retained in
[`test-results/text-learning/`](../test-results/text-learning/). Earlier focused
checks do not supersede exact-final-source aggregate and platform qualification.
