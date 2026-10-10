# Opt-in physical-voice file interface

This original synthetic experiment couples the reviewed reduced fold equations
to a normalized oral/nasal waveguide. It leaves production Aster and the existing
source–filter voice experiment unchanged. It is an offline instrument, with no
microphone, playback, network provider, pretrained voice, voice clone or reasoning
fallback. Production NewBrain remains unavailable.

The default `aster_original_feminine_physical_v1` identity expresses the intended
higher/feminine direction. It uses the tested stiffness-times-two mechanical
case; it does not establish perceived gender, female anatomy, intelligibility,
anatomical fidelity or human vocal health.

## Commands

Run from the repository root. Use a new output directory under an existing,
trusted parent; these examples keep generated PCM outside the repository:

```
python -m experiments.physical_voice.demo demo --output /tmp/aster-physical-demo
python -m experiments.physical_voice.demo inspect --bundle /tmp/aster-physical-demo
python -m experiments.physical_voice.demo recheck --bundle /tmp/aster-physical-demo
python -m experiments.physical_voice.demo render --intent /tmp/motor-intent.json --output /tmp/aster-physical-manual
python -m experiments.physical_voice.demo from-text-lab --text-state /tmp/validated-text-state --method INTERLEAVED --split new --case-index 0 --output /tmp/aster-physical-label
```

`--owner synthetic_aster` is the default. Every command accepts an explicit
synthetic owner and rejects mismatched saved state. CLI errors are fixed,
path-free codes. A render failure or cancellation does not publish partial PCM; cancellation after
the atomic rename reports uncertain durability of the already-complete bundle.
Each command produces only a JSON result and/or a local bundle. Nothing plays it.

The bundle contains exactly `intent.json`, `checkpoint.json`, `receipt.json`,
`preview.wav`, and `manifest.json`. WAV is canonical 48 kHz mono, signed 16-bit
little-endian PCM, with no metadata chunks. The file is at most 3 seconds. No
implicit post-roll, FIR latency trimming or extension beyond that bound occurs.

## Motor intent

A minimal explicit manual intent is:

```json
{
  "schema": "aster.physical-voice-intent.v1",
  "owner": "synthetic_aster",
  "profile": "aster_original_feminine_physical_v1",
  "sample_rate": 48000,
  "substeps": 4,
  "source": {
    "pressure_pa": 800.0,
    "stiffness_scale": 2.0,
    "damping_kg_s": 0.02,
    "rest_half_gap_m": 0.00018
  },
  "velum": 0.0,
  "delivery_gain": 1.0,
  "origin": {"kind": "manual_motor_intent"},
  "gestures": [
    {"duration_ms": 650, "pose": {
      "tongue_position": 0.5, "tongue_height": 0.2,
      "jaw_opening": 0.85, "lip_rounding": 0.1
    }}
  ]
}
```

All schemas are closed: unknown fields, nonfinite values, booleans as numbers,
duplicate JSON keys and excessive JSON complexity fail. Manual JSON is at most
32 KiB. There are 1–12 gestures, each 50–1500 ms, with at most 3000 ms total.
Every pose coordinate is in [0, 1], as a numerical control rather than an
anatomical measurement. Pose targets are smoothed with a fixed 15 ms exponential
time constant; no wave state is rescaled or reset at gesture changes.

Public source controls are narrower than the numerical core:

- Pressure maximum: 0–1000 Pa, with an explicit 15 ms linear onset and 25 ms
  linear final release, evaluated at every RK4 stage
- Stiffness scale: 1–2, multiplying both springs, coupling and contact stiffnesses
- Damping on each mass: 0.018–0.024 kg/s
- Positive rest half-gap on each mass: 0.00014–0.00022 m
- Velum: exactly zero (closed), or [0.01, 1]; fixed throughout the clip
- Delivery gain: [0, 1], which only attenuates final PCM delivery

Masses, mechanical parameters, tract topology, velum, nasal geometry, source
area, losses and radiation law stay fixed per clip. There is one recorded initial
1 nm lower displacement, no commanded pitch, repeated seed or oscillator.
Arbitrary pressure/pose combinations within the public envelope are bounded
inputs, not guarantees of sustained oscillation or successful physiological
behavior. Numerical guard failures abort the run rather than repair the state.

## Sampling, conversion and energy

Every 192 kHz mechanical endpoint is fed into the reviewed 145-tap FIR. The raw
stream's first sample is core endpoint 1 at 1/192000 seconds; FIR retention uses
raw indices 0, 4, 8, and so forth. Its 18 output-frame (0.375 ms) delay remains in
the file. The first oral propagation takes 24 additional frames; the nasal path
takes 28. These timing choices are included in the receipt. Signed filtered flow
is not clamped to zero.

The tract returns separate lip/nose root-power signals in sqrt(watts). The fixed
mono mix is `(lip + nose) / sqrt(2)`. Delivery converts at exactly 2.0 full scale
per sqrt(watt), then applies the requested attenuation, 10 ms clip-endpoint fades
and a 0.20 full-scale ceiling. There is **no per-clip normalization** or automatic
gain adaptation. Receipt metrics distinguish the raw outlet peaks, pre-fade
converted peak, pre-limiter peak and limiter activation count. Actual PCM peak,
RMS, mean, nonzero count, endpoint values and full-scale clip count are measured
from the bytes that are written. The ceiling is a digital delivery bound, not an
acoustic hearing-safety guarantee or calibrated sound pressure level.

Mechanical energy/work/loss values are per fold; multiply by two for the mirrored
pair. Full glottal flow already includes both folds. All-endpoint window statistics
include onset, release and articulation changes: their observed frequency is not
a separate steady-state/self-oscillation qualification. Mechanical and acoustic
energy ledgers are reported separately. The one-way prescribed flow source does
not close a combined fluid–tissue–tract energy budget.

## Replay, inspection and limits

The middle checkpoint contains the complete fold plan/state/cumulative diagnostics,
all mechanical-window moments and crossing progress, FIR ring/counters, tract
traveling waves and both radiation states, acoustic energy ledgers/extrema,
smoothed pose, signal moments, delivery peaks/limiter count and frame cursor.
Owner, intent digest, protocol implementation, exact source-file digests and a
limited Python/platform/architecture identity are bound to it. Runtime metadata
uses built-in facts; it does not probe hostnames or networks on Windows.

Export compares both an independent full render and an exact middle-checkpoint
suffix with the first render, including cumulative diagnostics. `recheck` repeats
both comparisons on the same source/runtime binding. Physics states are never
reconstructed from the PCM. Exact repeatability is only claimed for that bound
implementation and runtime, not across different machines or library builds.
Every export/recheck has a shared 300-second wall-clock budget checked every 256
frames, as well as hard frame/substep bounds. Slow hosts may safely refuse a run.

`inspect` steps no simulation and executes no brain. It freshly checks closed
schemas, owner/digests, bounded component states, exact WAV format and actual PCM
measurements. Stored render/replay/physical metrics appear under
`stored_render_claims`; inspection does not freshly prove those claims. File
digests provide integrity binding, not third-party authenticity or signatures.
Compatible data from a different source/runtime may be inspected when its schema
and fixed constants still match, but cannot be exactly replayed. Historical
calibration bundles with changed constants, including the first quiet 0.05
FS/sqrt(W) attempt, need their matching implementation for inspection/replay.

Writes stage in a private sibling directory, check every readback, validate the
bundle, fsync where supported, and atomically rename without replacing a raced
existing destination. Existing outputs, symlink/junction paths, hardlinked files,
nonregular files, unexpected bundle files and oversize input fail closed. The
existing parent must be trusted against concurrent replacement; this is not a
hostile multi-user directory sandbox. A post-rename fsync error or cancellation reports uncertain
durability and does not pretend the already-published directory was removed.

## Text-lab bridge and verification

The explicit adapter reads an existing validated synthetic text-lab state. It
uses the **actual observed** one-token `warm` or `cool` response, even when wrong,
and keeps the report/model hashes, method, split, case index and correctness flag.
`warm` maps to the original open pose and `cool` to the rounded pose. It never
substitutes the expected label, executes training, performs new reasoning, or
pronounces the English words. Unsupported output fails closed. This demonstrates
a saved experimental label-to-motor interface, not fluent speech or production
brain qualification.

Fast interface tests:

```
python -m unittest tests.test_physical_voice -v
```

Explicit actual-waveform, byte-exact resume, publication and failure-cleanup tests:

```
python -m unittest experiments.physical_voice.test_pipeline_numerical -v
```

Raw experiment bundles and trajectories belong outside the repository. Compact
recipes, final source hashes, measured scalar rows and failures are retained under
`test-results/physical-voice/interface/`. See the component equation/filter/tract
receipts for their independent qualification scope.
