# Causal synthetic temporal association

This opt-in lab adds a bounded ordinary object tracker to the existing synthetic
pixel extractor. It does not activate Aster, capture a camera or screen, recognize
real-world people or objects, understand movies, or establish learned temporal
cognition. Production still has no active NewBrain backend.

## Attribution and source

Aster base: `446ba6aa0096360fd17d33c9e0fc244d0690f324` (merged static vision PR15).
NewBrain read-only source pin: `cbf43167b2a9f3df7b61c1e0d9497d26115a2c94`.
The existing byte-exact color/shape model and dataset remain unchanged. All three
Aster-owned classifiers are loaded from their previously committed synthetic-only
checkpoints, verified by ZIP and individual SHA-256. There are **zero training
updates**, no copied personal weights, no additional packages or pretrained model.

NewBrain's `research/audiovisual056/AUDIOVISUAL-RESEARCH.md` describes an unrun
broader contract. `research/synthetic-vision-source023/core/pixel_controls.py`
implements a restricted palette/cue-memory control, not a suitable tracking
learner. Neither is copied or executed here. The new tracker is local engineered
Python. Any association advantage belongs to this engineering, not NewBrain
learning. Classifier labels are evaluated separately and never enter the tracker.

## Inputs and bounded state

Each fresh tracker consumes one immutable 64×64 RGB frame and a strictly increasing
integer millisecond timestamp. No identity, source name, true position/velocity,
object count, event flags, scenario label, image filename or future frame is an
inference input. One instance is one source: a new source requires a new instance.
There is no adapter that silently switches between webcam/screen/avatar sources.
The timestamps are synthetic presentation times, not measured capture timing.

The unchanged component extractor locates up to eight components. Tracking uses
only their observed boxes, areas and normalized RGB summaries, with at most sixteen
stored tracks and sixty-four observed frames. Position extrapolation uses elapsed
milliseconds and an explicit maximum-speed prior, not a true velocity label.
Tracks expire after 800 ms. Duplicate, backward, noninteger, nonfinite, boolean
or out-of-range timestamps are refused before state changes.

Outputs distinguish a component-backed detection, a new local track, a continued
local track and an identity abstention. No probability or calibrated confidence
is supplied. A continued handle is a heuristic identity claim. It is not proof
that a visually identical replacement did not occur off-camera. Hidden predicted
positions are never emitted as detections. Overlap/touching still merges visible
components and can break tracking.

Several appearance-compatible histories after missing observations are
quarantined rather than resolved by assumed straight-line hidden motion. The
ambiguity state persists until its history expires. New handles after expiry do
not claim recovery of the earlier identities. Full synthetic hiding uses a
background-equivalent occluding region, so its physical cause is not visible.
The benchmark persistence assumption is not a general solution to object
permanence or identity replacement.

## Comparison and held-out unit

`experiments/temporal_vision/PROTOCOL.json` fixes all modes, parameters, split
combinations, metrics and deadlines. Development uses eighteen complete streams;
held-out evaluation uses twenty-seven. Each has twenty-four ticks, less explicitly
dropped frames in the gap family. A freeze receipt binds exact sources before
held-out frame generation. It is reproducibility evidence, not an independently
secret holdout service. Once consumed, the set is regression evidence; tuning to
its outcomes needs a new version and unused trajectories.

The five reported arms are motion-plus-appearance, appearance/last-position,
nearest-last-position, reset-each-frame, and a shuffled-content motion control.
The shuffled control uses a new monotonic presentation clock; recovery events and ambiguous-identity safety
are not scored on its transformed chronology. Reset identities never reuse the
same integer across frames. Every arm sees the same detector and no classifier
label. All three classifier checkpoints are reported, never selected by score.
They are not independent temporal replications.

Cases include separated motion, near crossings, full hiding, a distractor,
visible overlap, an abrupt appearance change, frame drops, and paired ambiguous
hidden exchanges. The stay/swap twins have exactly identical complete RGB and
timestamp streams but different evaluator-only identity assignments. Operational
outputs must match, and any claim to a pre-hide identity is counted as ambiguous
regardless of a lucky match to one twin's truth. Withheld trajectories vary speed,
scale, start positions and timing together. The invented shape and motion grammar
is shared, so this is not natural-image or novel-motion-family generalization.

## Metrics

Detection matching is label/identity-blind maximum cardinality, then IoU sum,
with IoU ≥ 0.50. Truth uses visible-mask bounds with at least nine visible pixels.
Fully hidden objects do not create detection false negatives. Partially visible
objects remain in the denominator; merged components may match at most one truth.
The background-equivalent hiding surface is not a detection target. Equally
optimal box matches use the matcher's stable traversal order. Identity outcomes
on such ties can depend on that convention; the retained audit identifies them
separately rather than presenting them as uniquely established physical errors.

Track ownership is assigned only on the first matched observation of an object
and never rewritten when a track later switches owners. Reported original-identity
continuity recall includes every previously visible truth instance in its
denominator. Missed detections, identity abstentions and replacement handles lower
recall. Replacement histories are not silently rebound to original identity.
Correct anchored, wrong known-owner and unanchored fragment continuations are
reported separately. First grounded matches are acquisitions, never verified
continuations. The `first_acquisitions` counter is specifically late acquisition
among previously visible eligible instances; ordinary first-frame births are not
in that denominator. Anchored selective error excludes unanchored histories, whose
rate remains visible alongside coverage. These measures accompany switches and fragments so an always-abstain
or always-new strategy cannot look perfect. Identity switches compare the last
non-null matched handle even across detection gaps; contamination separately
counts a handle attached to a different original truth owner.

Each declared resolvable recovery event specifies a pre-hide frame, first visible
reappearance, and a two-tick deadline. Both unconditional all-event and conditional
pre-established denominators are reported. Missed, uncertain, wrong and new-ID
recoveries fail the unconditional metric. Ambiguous twins are scored separately.
Frozen color/shape labels retain the static lab's tiny vocabulary, uncalibrated
0.70 acceptance rule and known unknown-shape failures.

## Replay, evidence and limits

A size-bounded, strict-schema JSON checkpoint retains positions, observed velocity,
appearance, age, ID counter and ambiguity state. It uses no pickle and rejects
corruption, duplicate keys, unsupported versions, invalid geometry and counters.
Its checksum detects accidental corruption, not malicious forgery. A checkpoint
is lab-local state, not a safe source-switch or production persistence contract.

Nine separate Python-process probes restore a meaningful prefix and replay every
remaining frame. All boxes, identities, abstentions and final state bytes must
equal uninterrupted execution. This preserves mistakes too; it does not prove
perception correctness. The exact algorithm/protocol and frozen classifier hashes
are bound by the run receipt. No learning happens in the child process.

Each completed tracking/label frame is appended before advancing. Failure receipts
retain phase, sequence, arm, timestamp and completed-row counts. Output must be a
new directory without symlink ancestors; this cooperative guard is not an OS
sandbox. No partial failure resume is supported.

Use CPython 3.12.14/Linux or 3.14.4/Windows and existing `numpy==2.3.5`:

```
python -m pip install --only-binary=:all: -r requirements-vision.txt
python -B scripts/record_temporal_vision_checks.py --split development --output temporal-dev
python -B scripts/record_temporal_vision_checks.py --split heldout --output temporal-heldout
```

The wrapper caps mechanical checks at 60 seconds and numerical execution at
120 seconds. Memory is bounded structurally but has no OS-enforced limit. Recorded
process high-water memory includes interpreter and earlier stages, excludes cold
children, and is not the user's PC measurement. Direct extraction, association,
classifier-only, and extractor-plus-tracker latencies are reported separately.
None includes capture, decode, display or transport, and 64×64 timings do not
establish 1080p streaming performance. Native Linux/Windows CI is separate from
user-PC testing. A green job means the experiment completed, not that all its
perception predictions were correct.

Actual successes and failures: [retained results](../test-results/temporal-vision/README.md).
