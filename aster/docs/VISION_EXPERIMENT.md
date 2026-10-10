# Isolated synthetic vision experiment

This opt-in Aster lab improves and measures a narrow pixel-processing path while
NewBrain's main work continues separately. It does not activate Aster's brain,
webcam, screen capture, application control, OCR, person recognition, video
understanding or conversational reasoning. There is no pretrained visual or
language model and no paid service.

## What the experiment actually does

A fixed pixel-based component extractor estimates a frame's background from its
border, finds contrasting connected components, and sends isolated observed
pixels to an unchanged, freshly trained NewBrain color/shape classifier. The
classifier has learned weights; background subtraction, connected components and
crop/resize are ordinary engineered preprocessing. Gains attributable to that
preprocessing must not be credited to new general intelligence.

The only taught labels are red/green/blue and square/circle/triangle. The inherited
fourth shape output has not been taught and is marked unsupported. It is not an
unknown-object detector. Confidence uses the upstream uncalibrated 0.70 rule.
Unseen shapes can confidently receive a wrong familiar label. Real images can
produce plausible-looking nonsense within this tiny vocabulary.

Camera-like and screen-like mean invented raster proxy families. They are not
camera optics or actual desktop captures. Training on this grammar does not
qualify natural images, printed letters, faces, movie scenes, text instructions,
biological vision, or reliable unknown rejection.

## Source and ownership

- Aster base: `6d3a49b7a788650375a949bd1b4fd91c608ed7ad`.
- Read-only NewBrain inspection: `cbf43167b2a9f3df7b61c1e0d9497d26115a2c94`.
- Two byte-exact generic sources copied: `research/learning034/visual/visual_dataset.py`
  and `visual_model.py`. Original Git blob IDs and SHA-256 are retained in
  `vendor/newbrain_vision/<pin>/manifest.json`.
- This lab does not write to NewBrain or copy a personal identity, checkpoint,
  private curriculum, prior learned weights, personal pictures or biological data.
- All three models start with fresh seeded parameters. Checkpoints are generated
  solely from the disclosed synthetic training grammar and belong to this lab.
- No project license was found at that upstream pin. The same owner's explicit
  private-copy permission supports this experiment; broader redistribution or
  commercial clearance is not inferred. Upstream notices are preserved, but the
  Allen biological model discussed in those notices is not included here.

The latest printed-letter foundation/correction sources were also inspected.
Their receptive tests use supplied language tokens; those results do not provide
pixel OCR. This experiment does not re-label that work as reading images.

## Frozen comparison

`experiments/vision_lab/PROTOCOL.json` declares seeds, schedules, geometry,
nuisances, thresholds, splits, controls and metrics before held-out execution.
Development runs precede the freeze. A fresh process records exact source hashes
before each run and rechecks them after evaluation and cold restart. This is
reproducibility evidence, not an independent blind holdout server. Once the
held-out cases have been examined, changes informed by them require a new
protocol/version and unused holdout, with old failures retained.

Training is the exact upstream 96-example pool, six of nine color–shape pairs,
320 updates × 12 examples = 3,840 exposures, rate 0.15, gradient clipping norm 5.
The three fixed seeds are 13, 29 and 47. No best seed is selected. All 96 training
examples are scored only as exposed-fit sanity, never as held-out results.

The 192-frame held-out set has 36 clean, 36 camera proxy, 24 multiobject screen
proxy, 18 unknown-shape, 18 unknown-color, 12 mixed-unknown, 12 blank, and 36
stress frames. Positions, scales, intensities and nuisance combinations differ
from training; train and test still share the same invented shape templates.
Independent noise seeds alone are not claimed as semantic generalization.
Backgrounds vary across color/shape pairs and screen object counts.

Compared paths:

1. Original global preprocessing: the 64×64 frame is explicitly nearest-resized
   to the upstream 32×32 input, then classified by the same trained checkpoint.
   Fair single-known-object counts are reported separately. This path cannot
   locate multiple objects; that expected limitation is not a hidden advantage.
2. Component extraction plus the same trained checkpoint.
3. The same extraction plus independent nearest shape/color exemplars from the
   same 96 training examples. This is a strong ordinary non-neural baseline;
   its exposure/storage mechanism differs from 3,840 SGD exposures.
4. The same extraction plus an untrained model with the same seed.
5. An evaluator-only oracle using visible ground-truth masks. It is never an
   operational input and never enters headline performance or training. On
   overlap controls, visible-mask bounds can differ from pre-occlusion truth
   boxes, so even this diagnostic can fail the detection IoU threshold.

Prediction receives only immutable RGB bytes. Source tags, frame IDs, timestamps,
object counts, labels, boxes and masks are outside operational inference. The
source identity and index×100ms clock are synthetic provenance, not evidence of
video timing or temporal continuity. Inference is stateless across frames.

## Scoring and failure honesty

Matching uses boxes only, maximizes valid match count first and total IoU second,
and requires IoU ≥ 0.50. Labels cannot determine matches. Reports preserve:

- Detection TP, FP, FN, precision and recall
- Matched-object color, shape and joint correctness
- Correct accepted known-object recall over every expected known object,
  including missed objects; held color–shape pairs separately
- Matched/all-known coverage, selective error and accepted spurious predictions
- Low-confidence abstentions and unsupported fourth-logit outputs separately
- Exact-frame success: all objects located, known objects correctly accepted,
  unknown objects not accepted, no spurious predictions
- Direct unknown false accepts and a conservative unsafe-accept frame metric
  that also counts unmatched accepted boxes on mixed-unknown scenes

Failure to find an unknown object is not successful unknown recognition. A black
or low-contrast frame, component overflow, abstention and unsupported logits are
different outcomes. Blank/background-only, border contact, low contrast,
patterned backgrounds, speckles, thin bridges, touching and overlap cases remain
in their denominators. Confidence is uncalibrated; no reliability or safety
claim follows from a small synthetic false-accept rate.

Every completed case is appended to an evidence JSONL before advancing. Failed
runs retain stage, seed, last attempted case and completed-case count. A failed
optimizer call need not expose all internal partial effects; no resume or state
continuation from failed runs is supported. Fresh runs get new directories.

The successful cold check starts a separate Python process, reloads the exact
bounded binary checkpoint without pickle, performs zero updates, and compares
all returned probe decisions plus state digest and update count. It checks
mechanical persistence, including preserved mistakes, not intelligence.

## Running and resources

Use a separate environment with CPython 3.12.14 on Linux or 3.14.4 on Windows and the optional pinned NumPy
2.3.5 dependency in `requirements-vision.txt`. No dependency installs itself.
The normal Aster application and foundation tests do not require NumPy.

From the repository root:

```
python -m pip install --only-binary=:all: -r requirements-vision.txt
python -B scripts/record_vision_checks.py --split development --output my-vision-dev
python -B scripts/record_vision_checks.py --split heldout --output my-vision-heldout
```

Outputs must be new directories. Existing paths and symlink ancestors are refused;
this is cooperative local output protection, not an OS security sandbox. Do not
point the output inside a production Aster state directory.

The wrapper caps the numerical subprocess at 120 seconds and the mechanical
suite at 60 seconds. Images are exactly 64×64 RGB, extraction accepts at most
8 components, and the dataset/model/update budgets are fixed. There is no hard
memory limit. Recorded process high-water RSS/Windows peak working set includes
the interpreter and prior stages, excludes the cold child, and is not a guarantee
for the user's PC. Per-frame latency includes extraction and prediction but
excludes capture, media decode, frame transport, display and other comparison
arms. These small-image timings do not establish 1080p real-time performance.

Windows and Linux GitHub Actions run the frozen benchmark and retain full results.
A green job means the checks completed normally; it does not make every
perception result correct. Local/Linux, native Windows, user-PC, scientific
performance and production qualification are separate claims.

See [retained results](../test-results/vision-lab/README.md) for actual counts,
failures, source pins, review and exact-head CI evidence.

## Separate temporal experiment and future audiovisual work

The intended future adapters differ: virtual avatar-eye RGB views for Kira
World/Megan, and authorized webcam or screen RGB views for Aster. A shared
pixel-processing core must not receive privileged scene-graph labels. Screen
text must remain untrusted observation; seeing a command is not permission to
execute it. Live capture requires separately reviewed controls and explicit
permission.

The static experiment above remains stateless. A separate opt-in
[temporal association lab](TEMPORAL_VISION_EXPERIMENT.md) now implements a bounded
synthetic comparison. Its results and limits are separate from these static
findings. Broader future capture adapters should freeze causal frame order, a source ID,
monotonic capture timestamp, known frame-drop policy and bounded memory before
execution. Use independent trajectories with crossings, temporary occlusions,
appearance changes and object transfers. Evaluate identity switches, localization,
reacquisition, event order and memory after occlusion. Compare single-frame,
shuffled-frame and memory-reset controls. No future frames or evaluator labels
may reach inference. Those broader capture tests are prospective; this static lab has no tracker.

The later goal of following a novel three-minute audiovisual story additionally
needs real object/person recognition, event and relationship representations,
causal temporal memory, audio alignment and grounded question answering.
Measure decoding/capture throughput, frame lag, event latency and end-to-end
answer quality separately. Static colored shapes satisfy none of those goals.

Two approved public-source challenges are documented in `video-challenges.json`.
Their source descriptions are evaluator-only and cannot be supplied as hints to
a predictor. The current classifier's tiny label space cannot meaningfully name
a pendulum, person or folding bicycle. Download/annotation or an out-of-domain
probe is not a successful comprehension result. Actual video findings, if any,
are recorded separately with their own verified bytes and scope.
