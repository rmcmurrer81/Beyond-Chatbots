# Optional artificial voice-box experiment

Aster now has an original **software source–filter instrument**: a periodic
glottal-flow-inspired source, breath noise, and three controllable vocal-tract
resonators. The first preset is intended as a feminine synthetic voice direction.
It makes vowel-like sounds; it is **not fluent speech, a trained voice, a physical
larynx, or a biomechanical simulation of vocal-fold tissue and airflow**. No
listening test has established intelligibility, naturalness or perceived gender.

The working desktop voice and all existing voice assets are unchanged. This lab
does not load on Aster startup, enable production NewBrain, answer requests,
record audio, contact a provider, or use Qwen. It uses Python's standard library,
CPU only. There is no installation, training or model download for synthesis.

## Export and inspect a first sound

From the repository root, on Linux or Windows with Python 3.12 or newer:

```console
python -c "from pathlib import Path; Path('.aster-state').mkdir(exist_ok=True)"
python -B -m experiments.voice_box.demo demo --output .aster-state/voice-demo
python -B -m experiments.voice_box.demo inspect --bundle .aster-state/voice-demo
python -B -m experiments.voice_box.demo recheck --bundle .aster-state/voice-demo
```

The five-vowel demonstration lasts 2.75 seconds, with five 450 ms gestures and
100 ms pauses. Open `preview.wav` yourself only when you want to hear it. Start
with low playback volume. The program never plays sound or opens an audio app.
A digital peak cap cannot guarantee a safe acoustic sound level on your speakers
or headphones.

Each export is a **new** directory beneath an existing trusted local parent. An
occupied destination is refused, including an empty directory. No overwrite
option exists. The directory contains:

- `intent.json`: the versioned vocal gesture instructions and synthetic owner
- `preview.wav`: little-endian 24,000 Hz, 16-bit, mono PCM
- `checkpoint.json`: complete oscillator, deterministic noise, resonator and DC
  filter state at the middle of the clip
- `receipt.json`: measured waveform, hashes and explicit capability limitations
- `manifest.json`: exact file sizes and integrity hashes

Inspection reads bounded data and checks the WAV header, extent, samples and
recorded measurements without synthesis. Recheck recomputes the whole clip and
the suffix from the checkpoint and requires byte-for-byte equality. Checkpoints
are bound to the owner, intent, renderer source and Python/platform identity;
cross-platform checkpoint migration is deliberately refused. This is a same-
runtime reproducibility check, not a claim of bit-identical libm across systems.
The identity binding uses built-in OS/runtime facts (pointer width on Windows),
not hostname/network probes. It is not a complete interpreter or native-library
binary fingerprint; a successful actual recheck is still required on the target runtime.
Hashes detect corruption, not a hostile editor who can rewrite an entire bundle.
Keep bundles under a trusted parent; this is not an OS sandbox against another
process changing parent directories concurrently.

## Controls and limits

Copy `experiments/voice_box/example-intent.json` to a new local file and adjust it,
then render explicitly:

```console
python -B -m experiments.voice_box.demo render --intent my-intent.json --output .aster-state/my-voice
```

The closed `aster.voice-intent.v1` interface accepts only declared fields:

- A `synthetic_...` owner, original preset identity, fixed 24 kHz rate and nonzero
  32-bit deterministic noise seed
- Overall gain 0–1; zero gain produces exact digital silence
- 1–32 gestures, each 40–2,000 ms, no more than 8 seconds total
- `a`, `e`, `i`, `o`, `u` or exact silence; these are instrument labels rather
  than a language's complete phoneme inventory
- Start/end fundamental pitch 80–350 Hz, linearly interpolated within a gesture
- Voicing 0–1, breathiness 0–0.4, abstract open-quotient/timbre control 0.35–0.8
- Three ordered formant frequencies 200–4,500 Hz, separated by at least 100 Hz,
  and three resonance bandwidths 60–500 Hz

The default uses a 220→205 Hz pitch contour and original, approximate formant
values. Pitch alone does not define a voice's gender. There is no sampled person,
speaker anatomy, voice clone, phonetic dictionary or learned voice embedding.

The source has 24 harmonics below Nyquist at every admitted pitch, plus seeded
noise. Three stable parallel resonators approximate a vocal tract; their controls
are not tongue/lip geometry. Open quotient shapes a harmonic envelope, not actual
fold opening time. A soft saturator, DC blocker, fixed gain and 10 ms gesture fades
bound output. There is no loudness normalization. The hard digital ceiling is
6,553/32,768, about −14 dBFS; the default clip is quieter. Muting both source
controls or overall gain produces exact silence. Explicit silence and source mute clear filter
memories, so no resonance rings through a pause.

## Bounded connection to Aster's existing experimental brain

The separate [synthetic text-learning lab](TEXT_LEARNING_EXPERIMENT.md) can produce
an actual saved NewBrain-derived experimental decoder result. After running that
lab with its exact optional Python/NumPy pins, the voice lab can explicitly read
and validate that owner's saved report and checkpoint:

```console
python -B -m experiments.voice_box.demo from-text-lab --text-state .aster-state/text-demo --method INTERLEAVED --split new --case-index 0 --output .aster-state/brain-voice
```

This adapter uses **the observed generated token**, not the expected answer:
`warm` selects a 650 ms `a` gesture; `cool` selects a 650 ms `u` gesture. It retains
the recorded correctness flag, including mistakes. Any other output, multiple
tokens or missing termination is refused. This is an audible label encoding, not
the English words “warm” or “cool.” The adapter does not initialize, train or run
the model; it reads an existing observed decision. The qualification script can
separately run a fresh synthetic campaign to exercise the complete path.

Origin metadata binds the voice intent to the saved report, selected model,
method, split and case. Ordinary `render` refuses a claimed text-lab origin: use
the validating adapter. Origin hashes are evidence links, not authentication.
No production brain, person’s saved identity, memories or weights are imported.
Live NewBrain generation, general text-to-phoneme planning, conversational speech,
online learning and speech feedback remain future work.

## Source and rights review

Reviewed primary sources on 2026-10-06:

- [VocalTractLab official download page](https://vocaltractlab.de/index.php?page=vocaltractlab-download)
  lists version 2.4, released 5 December 2025.
- [Official background](https://vocaltractlab.de/index.php?page=background)
  distinguishes direct formant control from geometry-based articulatory synthesis.
  This prototype is the former.
- [Official 2.4 manual](https://vocaltractlab.de/download-vocaltractlab/VTL2.4-manual.pdf)
  describes its more complete glottis/tract models and gestural control.
- [Maintainer backend LICENSE](https://github.com/TUD-STKS/VocalTractLabBackend-dev/blob/main/LICENSE)
  is GNU GPL version 3. This does not by itself resolve every release asset's
  terms or approve redistributing a speaker model in this repository.

No VocalTractLab implementation, binary, speaker asset, recording or model was
downloaded into, executed by, copied into or linked by this experiment. The DSP,
parameters, interface and test fixtures were authored for Aster from general
source–filter principles. No new third-party runtime package is required. The
explicit optional bridge reads the already pinned, owner-authorized text lab;
its existing notices and source pins still apply. Existing repository licensing
is unchanged. A future VTL integration needs a separate version/asset license,
build, runtime, phonetic frontend and platform review before use.

## Verification and next gates

```console
python -B -m unittest discover -s tests -p test_voice_box.py -v
python -B scripts/record_voice_box_checks.py --output voice-checks --aggregate
```

Add `--with-text-lab` only in the text lab's qualified optional environment to run
the real synthetic training campaign and validate the actual observed-label path.
The recorder retains compact outcomes, every failed test identifier, measured WAV
results and source fingerprints, without uploading model state or raw diagnostics.
The dedicated workflow checks Linux and Windows and stores failed attempts too.

The repository's retained receipts distinguish local testing from exact-head CI
and independent review. Passing checks establish bounded export and reproducible
software behavior. They do not establish a realistic female voice, hearing safety,
speech intelligibility or conversational intelligence. Improve the sound only
after listening review, then consider a phoneme planner and a separately reviewed
physical model without replacing the existing working voice automatically.
