from __future__ import annotations
import math
from typing import Any
from .dialogue_audio_signal import gentle_proximity_correction

def postprocess_chatterbox_samples(
    samples: Any,
    *,
    sample_rate: int,
    config: VoiceOutputConfig,
) -> tuple[Any, dict[str, Any]]:
    """Apply one profile-scoped PCM calibration pass after signal validation.

    Both single-turn and streaming playback write this already-calibrated PCM.
    There is no second playback gain, so the setting cannot be applied twice.
    """

    import numpy as np

    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    gain_db = float(config.pcm_output_gain_db)
    cutoff_hz = float(config.proximity_cut_hz)
    cut_mix = float(config.proximity_cut_mix)
    if not math.isfinite(gain_db) or not -60.0 <= gain_db <= 6.0:
        raise ValueError("pcm_output_gain_db must be finite and between -60 and +6 dB")
    if not math.isfinite(cutoff_hz) or not 0.0 <= cutoff_hz < sample_rate / 2.0:
        raise ValueError("proximity_cut_hz must be finite, non-negative, and below Nyquist")
    if not math.isfinite(cut_mix) or not 0.0 <= cut_mix <= 1.0:
        raise ValueError("proximity_cut_mix must be finite and between 0 and 1")

    pre_rms = float(np.sqrt(np.mean(np.square(arr, dtype=np.float64)))) if arr.size else 0.0
    pre_peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    corrected = gentle_proximity_correction(
        arr,
        sample_rate=sample_rate,
        cutoff_hz=cutoff_hz,
        mix=cut_mix,
    )
    scaled = corrected * math.pow(10.0, gain_db / 20.0)
    clipped_sample_count = int(np.count_nonzero(np.abs(scaled) > 0.98))
    processed = np.clip(scaled, -0.98, 0.98).astype(np.float32, copy=False)
    post_rms = (
        float(np.sqrt(np.mean(np.square(processed, dtype=np.float64))))
        if processed.size
        else 0.0
    )
    post_peak = float(np.max(np.abs(processed))) if processed.size else 0.0
    return processed, {
        "applied": bool(gain_db != 0.0 or (cutoff_hz != 0.0 and cut_mix != 0.0)),
        "application_count": 1,
        "gain_db": gain_db,
        "proximity_cut_hz": cutoff_hz,
        "proximity_cut_mix": cut_mix,
        "pre_rms": round(pre_rms, 8),
        "pre_peak": round(pre_peak, 8),
        "post_rms": round(post_rms, 8),
        "post_peak": round(post_peak, 8),
        "clipped_sample_count": clipped_sample_count,
        "pitch_changed": False,
    }
