# NewBrain integration gate

## October 6: separate synthetic text-learning lab

The opt-in [text-learning experiment](TEXT_LEARNING_EXPERIMENT.md) copies three
byte-pinned generic modules from NewBrain `4a5c8396` into a separate lab with fresh
Aster synthetic data. It performs real bounded token-RNN updates, equal-exposure
teaching comparisons and independent-process restore checks. Its optional pinned
NumPy dependency does not enter the base application. Tiny fixture-goal results
do not establish ordinary conversation, and production `aster.backend` remains
unavailable with no fallback. No private state or identity is imported.

The earlier component status below remains a historical record of those separate
value/event and admission experiments; their source pins and limits are unchanged.

## Current status: October 5, 2026

Aster contains two independently tested, isolated pure-Python NewBrain components:
`learned_value.py` and `event_observer.py`, plus their unchanged upstream tests and
notices. The original snapshot at `bd0c5a34ade90470fb2bb0025af30cf4a51881bd` is
retained for rollback. A new versioned snapshot pins the same eight selected files
at current inspected main `df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef`. Every selected
file has the same Git blob as the original pin. Repinning is not a learning or
intelligence gain. Selection and explicit cross-pin state migration are tested
separately from production integration. See the [component lab](../experiments/newbrain_adapter/README.md).

The newer published decision-retention075 generic source and method are retained
unchanged under `vendor/newbrain_candidates/df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef/`.
Its manifest records exact Git blobs, SHA-256, byte sizes, origin and exclusions.
The [static admission audit](../experiments/newbrain_candidate/README.md) refuses
runtime replacement: `cue_readout`, `hearing_learner`, `hearing_limits`,
`pcm_features` and `waveform_corpus` are absent from the complete published tree.
Other matching filenames do not establish the required source/runtime bindings.
The upstream RunIO additionally requires CPython 3.14.4 and isolated runtime
flags; required private models, inputs, gold and bindings are intentionally not
imported. We did not reproduce the reported 075 experiment or invent substitutes.

Only project-authored generic source is reused under the owner's request. No
public license grant is inferred. No person identity/history, private corpus,
learned weight, voice or restricted Allen parameter file has been copied.
NewBrain itself remains read-only. Aster's identity, history and existing voice
assets are separate and retained. Production `aster.backend` remains unavailable;
there is no conversational backend, automatic job dispatch or reasoning fallback.

The dated sections below are historical inspection records. Statements that
no code had been copied applied at those times and are superseded by this section.

## Historical inspected source

Read-only inspection on 2026-10-04 at NewBrain commit
`67a0d88521b21c7d0a3b27b535e07be70d359874`, rechecked after the initial core tests.

- [README](https://github.com/rmcmurrer81/newbrain/blob/67a0d88521b21c7d0a3b27b535e07be70d359874/README.md): restricted experimental results, no full conversational system declared ready.
- [Sidecar adapter](https://github.com/rmcmurrer81/newbrain/blob/67a0d88521b21c7d0a3b27b535e07be70d359874/integration/kira/sidecar_adapter.py): synthetic signals only, no model calls, speech, memory or identity writes.
- [Dialogue source status](https://github.com/rmcmurrer81/newbrain/blob/67a0d88521b21c7d0a3b27b535e07be70d359874/research/dialogue038/README.md): bounded source-only token decoder; ordinary conversation and a complete zero-fallback caller are not demonstrated.

At this initial inspection, no NewBrain source or private artifacts had been
copied. These links recorded inspection, not runtime provenance or endpoint
tests. The later component copy and current source-candidate limits are documented
above; the original no-copy statement is no longer the current repository status.

## Proposed seam, deliberately disabled

`aster.backend.BrainRequest` and `QualifiedNewBrain` define Aster's proposed
subject-scoped Python boundary. This is **not a verified NewBrain API**. There is
no dynamic module loader, endpoint setting, subprocess bridge or enabling switch.
A request currently persists locally with `waiting_for_newbrain`; saved prompts
are never auto-submitted or auto-executed when source changes.

Before adding a real adapter:

1. Recheck NewBrain's current main SHA and status. Pin the exact implementation,
   documented interface, dependency versions, licenses and relevant artifact hashes.
2. Obtain and run a separately reviewed bounded interface test, including absence,
   timeout, malformed response, cancellation, restart and no-fallback cases.
3. Establish actual NewBrain generation, not canned fixtures or another language
   model. Report its measured capabilities and limitations without inflating them.
4. Keep Aster's stable subject ID and explicit memory selection independent from
   shared core code. Reject mismatched subjects and prevent cross-person reads.
5. Responses are advisory text. File changes, app jobs and external transmissions
   still require explicit named actions and their own authorization boundaries.
6. Measure wall time and process resources on the intended machine before raising
   limits. This development environment is CPU-only; nothing is installed on the
   user's computer by this project.

No Qwen/Ollama or other fallback is permitted. A future unavailable NewBrain remains
unavailable. A voice synthesizer, if later added, is an output channel and must not
be relabelled as the reasoning backend or invent a pending brain response.

## Subsequent main-branch check

At 17:31 UTC on 2026-10-04, main advanced to
`a94c55e81090dc684a5e51243338647a889dfdbf`. The single new commit adds four
`research/event-scans052/` documents: observation/creativity protocols, an optimized
backend proposal, a publication template and a status note. They explicitly label
work source-only/unrun and the GPU backend unimplemented. No runtime API or
conversational adapter was added in that change. Aster's integration gate remains
closed; no files from that update were copied or executed.

At 17:50 UTC, main advanced to `e614e42efbb195d6ec98c0d89066f5f89c0f7d41`.
That update adds the pure-Python value-learning prototype and a report accepting
18 bounded engineering fixtures, with comparison limitations. It explicitly
leaves conversation and genuine cold semantic recall unproved. No assistant
interface was added; nothing from this update was copied or executed in Aster.

## Value-event schema inspected at the user's latest request

At 18:09 UTC on 2026-10-04, main was
`394620d0338f974297ad394c563df35bcc042f58`. The new
[value-event observer](https://github.com/rmcmurrer81/newbrain/blob/394620d0338f974297ad394c563df35bcc042f58/research/value-event-engineering054/event_observer.py)
(Git blob `c37e6ef379dd7a4f338a14cee90084f2f0490511`) has the actual compact-record
schema `newbrain.value-event-observation.v1`; its separate result packet reports
14 exposed engineering checks. This is a bounded observer of the eight-coefficient
value learner, not a conversational assistant or subjective emotion result.

A future separately qualified observation adapter should preserve its `owner_id`,
`attempt_id`, source/component hashes, before/after boundaries, correction links,
operation flags and failed/unknown statuses. An unavailable after-state must stay
`UNKNOWN`; it cannot be replaced by before-state or a fabricated no-change result.
The source distinguishes declared hashes from authenticated loaded-source evidence,
and wrapper-only provider counts from whole-application qualification. Missing
resource observations remain null with a reason. These are useful compatibility
requirements for Aster's existing append-only correction and audit boundaries.

At this checkpoint no observer code or private records had been imported or
executed. The later generic observer copy is recorded above. No runtime adapter
is activated merely because this schema exists. Genuine durable cold recall,
conversation and subjective emotions remain explicitly unproved in that packet.

## Control-panel milestone check

At 19:12 UTC on 2026-10-04, main was
`d8e44aa6b82d58ff5b6ca11205f7c5d891decb66`. The comparison since `394620d`
contains two documentation-only commits. The
[runtime qualification status](https://github.com/rmcmurrer81/newbrain/blob/d8e44aa6b82d58ff5b6ca11205f7c5d891decb66/research/runtime055/STATUS.md)
preserves a failed import before learning/inference and an unlaunched probe
that exceeded its unchanged source-size limit. The
[audiovisual research contract](https://github.com/rmcmurrer81/newbrain/blob/d8e44aa6b82d58ff5b6ca11205f7c5d891decb66/research/audiovisual056/AUDIOVISUAL-RESEARCH.md)
explicitly remains unrun; continuous audiovisual understanding and reopened
conversational memory are not qualified. No new runtime adapter was exposed.
Nothing from those sources was executed or copied into Aster.

The future connection must initialize a fresh Aster-owned instance from a pinned,
qualified core. Core upgrades must preserve Aster's own identity and history.
Maya, Kira, Robert, or other subjects' identities, memories, relationships,
preferences and history must never be imported. The desktop control panel only
uses Aster's existing Store and remains usable while this integration gate is shut.
