# Synthetic learning and retention comparison

This opt-in Aster experiment tests whether one fixed EWC-inspired weight penalty
adds anything to matched old-example replay. It does not enable the production
brain, replace its architecture, import another person's weights, or modify
NewBrain. A negative or tied result is retained as useful evidence.

## Predeclared design

The full machine-readable design is in
[`protocol.py`](../experiments/newbrain_retention/protocol.py). It is copied with
source fingerprints into `freeze.json` before constructing any study model.

- Five initializations: 11, 29, 47, 71, 101. No seed search or replacement.
- The existing byte-pinned NewBrain token RNN: embedding 16, hidden 64, Aster's
  fixed 16-token vocabulary. Same SGD learning rate 0.01 and clip norm 5.
- Each starts from scratch with 384 balanced old-task updates. Old-task exact
  accuracy must reach 6/6 to qualify; failures remain in every all-seed report.
- Three arms restore the same native baseline bytes. Each runs 192 updates.
  REPLAY and REPLAY_EWC have identical ordering and exposures: 144 new updates
  and 48 old updates. NEW_ONLY instead receives 192 new updates; it is a
  descriptive control, not the causal comparison for the penalty.
- Each batch contains eight duplicate copies of one synthetic row, not eight
  independent examples. There are six unique training rows in each task.
- There are 4,800 actual campaign SGD calls, plus 30 single-row gradient calls
  to estimate importance. Mechanical unit-test updates are separate fixtures.
- Old/new accuracy and target-loss curves use fixed checkpoints. Eight new
  wording combinations are evaluated only after all training has finished.
  These use the same vocabulary and labels, so they measure limited compositional
  interpolation, not language understanding or independent task generalization.

The penalty strength is fixed at 10.0 before any outcome. The importance estimate
is the mean of the squares of six individual old-row gradients at the frozen
baseline. Each gradient is for teacher-forced mean token cross-entropy over the
one-word answer and EOS. No batch-gradient squaring, per-layer normalization,
trace rescaling, damping or held-out selection is performed.

The loss adds `lambda / 2 * sum(F * (theta - anchor)^2)`. Its gradient is added to
the data gradient before the unchanged upstream joint clipping and SGD. This is
an empirical diagonal squared-gradient approximation. It is not the exact Fisher,
a verified posterior precision, a biological mechanism, or a reproduction of a
published benchmark. Loss normalizations matter: using sequence-summed rather
than mean-token gradients would change this penalty's effective strength.

## Interpretation

The primary comparison is paired REPLAY_EWC minus REPLAY. Reports retain every
seed, every observed answer, old-task prequalification failures, newly correct
and lost new answers, and the exact denominator for old retention. Retention
without any newly correct new case is explicitly labelled. A baseline with no
correct old answers cannot establish retention.

The fixed descriptive benefit gate requires all five old baselines to qualify,
better aggregate old retention, no worse new or held-out accuracy, and protected
new accuracy strictly above its own warmup baseline. A tie fails that gate. This
is not a statistical significance test. Five seeds remain initializations of one
very small curriculum, not five independent real-world tasks.

Training/probe/Fisher wall times, gradient counts, update counts, and protection
array storage are reported separately. Arm order is fixed (REPLAY, REPLAY_EWC,
NEW_ONLY). Single-run timing can be confounded by execution order and system
load; it is descriptive overhead, not a powered speed comparison. Protection
stores two additional parameter-sized arrays; reported bytes are not process RAM.

## Verification and use

Use CPython 3.12.14 on Linux, or CPython 3.14.4 on Windows, with NumPy 2.3.5.
No automatic dependency installation or external compute is performed by the lab.

```console
python -m pip install --only-binary=:all: -r requirements-text-learning.txt
python -B scripts/record_retention_checks.py --aggregate --output test-results/retention-learning/local-attempt-01
```

Output directories must be fresh. The recorder preserves compact reports and
failures, never model/anchor/importance arrays. Its temporary model states are
synthetic and remain local. It bounds diagnostic capture and direct child
deadlines; this is not an OS resource sandbox. As in the existing text lab,
checksums bind trusted local files but do not authenticate an attacker-controlled
directory. Source changes invalidate a cold recheck instead of silently migrating
state.

Mechanical tests check finite-difference penalty and combined gradients across
all six parameter roles, the individual-gradient importance estimator, exact
zero-strength parity with upstream SGD, joint clipping, corrupted-state refusal,
and the equality of a protected next update after save/restore. A separate cold
process restores all 20 baseline/final checkpoints with model initialization,
training, gradient calls and selected RNG entry points disabled. It checks exact
parameter hashes/counters/tokens and floating-point values within 1e-12.

The dedicated CI workflow repeats the fixed campaign on native Windows 3.14.4
and Linux 3.12.14. These are engineering replications of the same consumed
evaluation block; they do not create fresh scientific test samples. Existing
repository workflows remain separate regression gates.

## Provenance and primary references

At inspection, upstream NewBrain main remained
[`cbf43167`](https://github.com/rmcmurrer81/newbrain/commit/cbf43167b2a9f3df7b61c1e0d9497d26115a2c94).
The current published decoder still has SHA-256
`52cd4b6e79fcd09198380e12320ff85468fb8bd6bedd5d424ede2b58dbdf5cc0`.
The experiment reuses Aster's existing admitted copy under the original
[`4a5c8396` snapshot](../vendor/newbrain_text_candidates/4a5c8396f820d8caf81b9ccba850617ae9e60489/manifest.json),
whose exact-byte manifest and unchanged notices are checked before loading.
No newer wrapper or private source/state is copied. The separately named Aster
adapter is new project code; generic reuse remains owner-authorized, with no
general public license grant inferred.

- [Kirkpatrick et al., EWC](https://arxiv.org/html/1612.00796v2), especially
  section 2 and equation 3: parameter-specific quadratic protection motivates
  the candidate. Its reported MNIST/Atari performance is not transferable evidence
  for this Aster fixture.
- [Rolnick et al., Experience Replay for Continual Learning](https://papers.neurips.cc/paper_files/paper/2019/hash/fa7cdfad1a5aaf8370ebeda47a1ff1c3-Abstract.html):
  replay is an important comparator. Aster's simple supervised replay is not a
  reproduction of the paper's reinforcement-learning CLEAR algorithm.
- [Kunstner et al., empirical Fisher limitations](https://arxiv.org/abs/1905.12558):
  the empirical Fisher generally cannot be assumed to capture true second-order
  geometry; our estimator is explicitly a heuristic importance proxy.

## Results

The protocol and code were committed at
[`735bdc38`](https://github.com/rmcmurrer81/aster-workstation/commit/735bdc3842d0f4c51bc26763270cf5fcd65689eb)
before the first campaign or holdout readout. Independent review cleared the
mechanics and interpretation first. The freeze and exact-source receipts are in
[`test-results/retention-learning/`](../test-results/retention-learning/).

The first Linux 3.12.14 run found **no incremental benefit from the penalty**:

- All five old baselines reached 6/6, so none were discarded as unqualified.
- Every arm finished 6/6 old, 6/6 new and 8/8 wording holdouts at every seed.
- Across initializations, new exact answers improved from 22/30 to 30/30 and
  holdouts from 36/40 to 40/40. These denominators repeat one curriculum across
  seeds; they are not independent unseen examples or tasks.
- Seeds 11 and 47 already answered all new prompts correctly after old-only
  warmup. They show retention without new exact-answer acquisition. The other
  three seeds gained 2, 3 and 3 new exact answers respectively.
- The NEW_ONLY control also retained everything. This task therefore did not
  expose forgetting, and cannot establish that either replay or EWC prevents it.
  The perfect endpoint is a ceiling, not a solved continual-learning result.
- EWC added 103,680 array bytes for anchor and importance. The initial run's
  median paired training-loop time was 5.3% higher (range 2.4–9.1%); Fisher
  construction took roughly 2 ms per seed. The ratio excludes one-time
  setup/restore and Fisher costs and is noisy descriptive timing only.

The complete aggregate, 3 protocol contracts, 45 combined numerical tests and
the separate 20-checkpoint cold restore passed locally. Passing engineering
checks is separate from the failed incremental-benefit gate. Native CI receipts
are authoritative for their exact commits/platforms; repeated campaigns are
engineering replications, not fresh scientific tests. The weight penalty is not
recommended for production adoption on this evidence, and no production behavior
is enabled.
