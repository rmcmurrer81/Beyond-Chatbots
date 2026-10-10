"""Small, testable signal helpers for dialogue listening copies."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt


def assess_generated_speech_chunk(
    samples: Any,
    *,
    sample_rate: int,
    queued_word_count: int,
    min_seconds_per_word: float = 0.18,
    rms_floor: float = 1e-4,
    peak_floor: float = 1e-3,
) -> dict[str, Any]:
    """Apply a lightweight, non-listening sanity gate to generated speech.

    This cannot prove which words were spoken; only ASR or human listening can
    do that.  It catches empty/silent output and grossly short output that
    cannot plausibly contain the number of queued words.
    """

    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if queued_word_count < 0:
        raise ValueError("queued_word_count must be non-negative")
    if min_seconds_per_word <= 0:
        raise ValueError("min_seconds_per_word must be positive")
    finite = bool(arr.size and np.isfinite(arr).all())
    duration = float(arr.size / sample_rate)
    rms = float(np.sqrt(np.mean(np.square(arr, dtype=np.float64)))) if finite else 0.0
    peak = float(np.max(np.abs(arr))) if finite else 0.0
    required_duration = max(0.20, float(queued_word_count) * float(min_seconds_per_word))
    reasons: list[str] = []
    if not arr.size:
        reasons.append("no_samples")
    if arr.size and not finite:
        reasons.append("non_finite_samples")
    if finite and rms < rms_floor:
        reasons.append("rms_below_speech_floor")
    if finite and peak < peak_floor:
        reasons.append("peak_below_speech_floor")
    if duration < required_duration:
        reasons.append("duration_too_short_for_queued_words")
    return {
        "passed": not reasons,
        "scope": "non_silent_pcm_and_conservative_duration_per_queued_word_not_asr_verified",
        "sample_count": int(arr.size),
        "sample_rate": int(sample_rate),
        "duration_seconds": round(duration, 6),
        "queued_word_count": int(queued_word_count),
        "min_seconds_per_word": float(min_seconds_per_word),
        "minimum_plausible_duration_seconds": round(required_duration, 6),
        "rms": round(rms, 8),
        "peak": round(peak, 8),
        "reasons": reasons,
    }


def gentle_proximity_correction(
    samples: Any,
    *,
    sample_rate: int,
    cutoff_hz: float = 95.0,
    mix: float = 0.30,
) -> np.ndarray:
    """Reduce close-mic bass buildup without changing pitch or word timing.

    A second-order high-pass signal is blended with the dry voice.  At the
    default 30% mix, deep proximity rumble is reduced by only about 3 dB while
    mid/high speech remains largely unchanged.  ``mix=0`` disables the filter.
    """

    arr = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if not 0.0 <= float(mix) <= 1.0:
        raise ValueError("mix must be between 0 and 1")
    nyquist = float(sample_rate) / 2.0
    if not 0.0 <= float(cutoff_hz) < nyquist:
        raise ValueError("cutoff_hz must be non-negative and below Nyquist")
    if arr.size == 0 or mix == 0.0 or cutoff_hz == 0.0:
        return arr.copy()

    sos = butter(2, float(cutoff_hz), btype="highpass", fs=float(sample_rate), output="sos")
    highpassed = sosfilt(sos, arr).astype(np.float32, copy=False)
    corrected = (1.0 - float(mix)) * arr + float(mix) * highpassed
    return np.clip(corrected, -0.98, 0.98).astype(np.float32, copy=False)
