# Current NewBrain source candidate: blocked runtime admission

This directory is a static compatibility gate. It never imports or executes the
retention075 source, changes the selected component, or enables Aster's backend.
The separately qualified value/observer component lab stays independent.

## What was inspected and copied

NewBrain main was read at `df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef`, with complete
nontruncated source tree `0693e3792ab77211c3de30b7ebb4366b0afbc6ce` (1,264 entries).
The four generic decision-retention075 Python sources and their published method,
scope/review/fixture declarations are retained unchanged under
`vendor/newbrain_candidates/<commit>/`. Exact Git blob identity, SHA-256 and byte
size were verified before saving the manifest. Its executable admission status
is false. Historical SOURCE ONLY and UNRUN comments were not rewritten.

`provenance-review.json` retains the matching generic upstream source075 records,
rights scope and source references. The owner requested reuse of project source;
no public license is assumed. No private history, person state, original saved
models, weights, PCM, gold, corpus, voice or local/native binding was copied.

## Why it cannot replace Aster's brain

Every direct import was checked by AST against the complete published tree. Five
required modules have no published file: `cue_readout`, `hearing_learner`,
`hearing_limits`, `pcm_features`, and `waveform_corpus`. Other filename matches
are recorded as candidates only, not qualified dependency bindings. The published
RunIO source additionally requires CPython 3.14.4 under `-I -S -B`; source075
needs private original model/input/history bindings, which are excluded.

We do not repair NewBrain's source/runtime restrictions, generate replacement
private inputs, run its committed test collection, or claim reproduction of the
upstream reported tone-retention results. The published result concerns saved
decision state on two known synthetic tone classes; it is not a conversational
interface, broad hearing, speech/music, or a full Aster brain.

## Reproduce the gate

From the repository root:

```console
python -B -m experiments.newbrain_candidate.audit --report candidate-admission.json
python -B -m unittest discover -s tests -p test_newbrain_candidate.py -v
```

The audit deliberately returns **2** with `BLOCKED_INCOMPLETE_DEPENDENCIES`.
That is a negative compatibility finding. The five engineering tests pass by
checking refusal, exact source/inventory integrity and no candidate execution;
they are not five successful intelligence or hearing tests.

For a future source update, inspect a new immutable commit, retain this manifest,
verify complete dependency and rights/runtime bindings, add independent state
compatibility tests and obtain review. Merely changing the SHA or finding a
similarly named module cannot make this candidate executable. There is no
activation switch in this audit.
