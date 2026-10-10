"""Separate one-shot Chatterbox worker; no generic voice fallback."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf8"))
    text = str(request["text"]).strip()
    reference = Path(request["reference"])
    output = Path(request["output"])
    if not text or len(text) > 20000 or not reference.is_file():
        raise ValueError("Invalid voice request")
    import numpy as np
    import soundfile as sf
    import torch
    from chatterbox.tts import ChatterboxTTS
    from voice_support.dialogue_tts import split_for_tts, spoken_words
    from voice_support.dialogue_audio_signal import assess_generated_speech_chunk
    from voice_support.calibration import postprocess_chatterbox_samples

    requested_device = request.get("device", "auto")
    if requested_device not in ("auto", "cpu", "cuda"):
        raise ValueError("voice_device must be auto, cpu, or cuda")
    device = ("cuda" if torch.cuda.is_available() else "cpu") if requested_device == "auto" else requested_device
    values = request.get("calibration", {})
    cfg = SimpleNamespace(pcm_output_gain_db=float(values.get("gain_db", 0)),
                          proximity_cut_hz=float(values.get("proximity_cut_hz", 0)),
                          proximity_cut_mix=float(values.get("proximity_cut_mix", 0)))
    if not all(math.isfinite(x) for x in (cfg.pcm_output_gain_db, cfg.proximity_cut_hz, cfg.proximity_cut_mix)):
        raise ValueError("Nonfinite calibration")
    chunks, _ = split_for_tts(text, max_chars=180)
    model = ChatterboxTTS.from_pretrained(device=device)
    rate = int(model.sr)
    part = output.with_suffix(".part.wav")
    checks = []
    try:
        with sf.SoundFile(str(part), mode="w", samplerate=rate, channels=1,
                          subtype="PCM_16", format="WAV") as sink:
            for index, chunk in enumerate(chunks):
                accepted = None
                for attempt in range(1, 4):
                    generated = model.generate(chunk, audio_prompt_path=str(reference))
                    samples = generated.detach().cpu().numpy().reshape(-1).astype(np.float32)
                    check = assess_generated_speech_chunk(samples, sample_rate=rate,
                                                         queued_word_count=len(spoken_words(chunk)))
                    if check.get("passed") is True:
                        accepted = samples
                        break
                if accepted is None:
                    raise RuntimeError("Chatterbox signal validation failed; no substitute voice used")
                processed, calibration = postprocess_chatterbox_samples(accepted, sample_rate=rate, config=cfg)
                sink.write(processed)
                checks.append({"chunk": index, "signal": check, "calibration": calibration})
                if index < len(chunks) - 1:
                    sink.write(np.zeros(max(1, int(rate * 0.06)), dtype=np.float32))
        part.replace(output)
        output.with_suffix(".metadata.json").write_text(json.dumps({
            "engine": "chatterbox_tts", "device": device, "reference": reference.name,
            "sample_rate": rate, "chunk_checks": checks, "generic_voice_used": False,
            "generation_is_synthetic": True,
        }, indent=2) + "\n", encoding="utf8")
    finally:
        part.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
