# Aster's supplied voice audition

The user/Codex supplied an original synthetic adult feminine voice on main commit
`e33383a393196c8e4c14aa8f506b65f6c2eea789`. Its five original asset files are preserved
unchanged under `assets/voices/aster_warm_female20s_v1/`.

## Received and checked

The exact WAV bytes match Git blob `775cfa0d6c3a7c90e23e6c3d6af4ddf3f1f5e445` and
SHA-256 `01768f1f65137623bfdd0e49b34211b7f31b315403ca5c7a5c75ed9e392bfd2f`.
Independent local readback: 691,244 bytes; mono 24 kHz PCM16; 345,600 frames;
14.4 seconds; peak 24,063; RMS 2,561.41685; zero clipped samples. These are signal
checks, not a listening review of naturalness, perceived presentation or taste.

The pack contains the style profile, exact audition transcript and generation
receipt. The receipt's text hash covers the spoken text without the file's final
newline; file-byte integrity is tracked separately. Git attributes preserve exact
voice metadata/audio bytes across Windows and POSIX checkouts.

The user's local generator was Qwen3-TTS VoiceDesign, a speech synthesizer. Aster
does not load or invoke that model. No weights, generator runtime, private donor
recording, cloned person's voice or credentials were supplied or imported.
NewBrain remains Aster's only intended reasoning backend and is unavailable.

## What this enables

`python -m aster voice` verifies the fixed pack read-only and reports whether the
**prerecorded audition** is available. It neither creates Aster state nor launches
a player, executes bundled code, accesses the network or synthesizes speech.
Open `assets/voices/aster_warm_female20s_v1/preview.html` locally for a manual audio
control. The page labels the audio as a prerecorded audition, not a brain reply.
Nothing automatically plays or is exposed through a public relay endpoint.

A sample/profile is not a complete text-to-speech backend. Arbitrary new spoken
replies, continuous voice identity and a live call path remain unavailable. Those
require a separately reviewed generator interface, operating environment, license
and resource validation; no new runtime or fallback is silently selected.

The original audition script describes intended assistant behavior. Its words
are not evidence of current intelligence, understanding, program generation or
working phone calls. Missing or changed asset bytes fail closed until reviewed.
