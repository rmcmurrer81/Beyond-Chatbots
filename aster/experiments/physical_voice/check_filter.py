#!/usr/bin/env python3
"""Explicit stdlib-only anti-alias gate; long raw traces live outside the repo.

Run: python -m experiments.physical_voice.check_filter --output FRESH_DIR --raw-dir FRESH_EXTERNAL_DIR
This measures this implementation, rather than accepting the design calculation.
No network, microphone, playback, dependencies, PCM normalization, or publishing.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import FrozenInstanceError, replace
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.physical_voice.filters import (  # noqa: E402
    DecimatorCheckpoint, DecimatorConfig, FilterError, FlowDecimator, GuardViolation,
)

OUTPUT_RATE = 48_000
GRID_POINTS = 16_385
TONE_OUTPUTS = 4096
TONE_WARMUP = 64
AMPLITUDE = .001


def require(value: bool, label: str) -> None:
    if not value:
        raise AssertionError(label)


def rejects(action, exception=FilterError) -> None:
    try:
        action()
    except exception:
        return
    raise AssertionError("invalid input was accepted")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def db(value: float) -> float:
    return 20 * math.log10(max(value, 1e-300))


def signed_response(taps: tuple[float, ...], frequency: float, rate: int) -> float:
    mid = len(taps) // 2
    omega = 2 * math.pi * frequency / rate
    return taps[mid] + 2 * math.fsum(taps[mid - k] * math.cos(omega * k) for k in range(1, mid + 1))


def mechanics_checks(m: int) -> dict:
    config = DecimatorConfig(m)
    filt = FlowDecimator(config)
    taps = filt.taps
    require(len(taps) == 36 * m + 1, "tap count")
    require(taps == taps[::-1], "exact symmetry")
    require(abs(math.fsum(taps) - 1) < 5e-16, "DC normalization")
    require(config.input_rate == OUTPUT_RATE * m and config.output_rate == OUTPUT_RATE, "rates")
    require(config.delay_output_samples == 18 and config.delay_s == .000375, "exact delay")
    require(math.fsum(abs(t) for t in taps) * config.max_input_abs_m3_s < config.max_output_abs_m3_s, "default output headroom")
    for polarity in (-1., 1.):
        for phase in range(m):
            source = tuple(polarity * AMPLITUDE if n == phase else 0. for n in range(80 * m))
            got = FlowDecimator(config).process(source)
            expected = tuple(polarity * AMPLITUDE * taps[n - phase] if 0 <= n - phase < len(taps) else 0.
                             for n in range(0, len(source), m))
            require(got == expected, "impulse and signed polyphase response")
            if phase == 0:
                require(max(range(len(got)), key=lambda k: abs(got[k])) == 18, "impulse group delay")
        steady = FlowDecimator(config).process([polarity * AMPLITUDE] * (200 * m))[40:]
        require(max(abs(y - polarity * AMPLITUDE) for y in steady) < 1e-18, "signed DC")
    rng = random.Random(620026 + m)
    source = tuple(rng.uniform(-.002, .002) for _ in range(2049))
    reference = tuple(math.fsum(t * (source[n-k] if n >= k else 0.) for k, t in enumerate(taps))
                      for n in range(0, len(source), m))
    whole = FlowDecimator(config)
    expected = whole.process(source)
    require(expected == reference, "independent direct convolution")
    blocked = FlowDecimator(config)
    output = []
    index = 0
    while index < len(source):
        require(blocked.process(()) == (), "empty block")
        width = rng.randrange(1, 113)
        output.extend(blocked.process(source[index:index+width]))
        index += width
    require(tuple(output) == expected and blocked.checkpoint() == whole.checkpoint(), "arbitrary block parity")
    positions = sorted(set((0, 1, m-1, m, m+1, len(taps)-1, len(taps), len(taps)+1, 2*len(taps)+3)))
    for position in positions:
        initial = FlowDecimator(config)
        head = initial.process(source[:position])
        checkpoint = initial.checkpoint()
        restored = FlowDecimator.from_checkpoint(checkpoint)
        require(restored.checkpoint() == checkpoint, "immediate checkpoint identity")
        require(head + restored.process(source[position:]) == expected, "checkpoint replay values")
        require(restored.checkpoint() == whole.checkpoint(), "checkpoint replay all state")
        require(initial.checkpoint() == checkpoint, "restored ring independence")
    for invalid in (True, None, "0", float("nan"), float("inf"), -float("inf"), .01000001, -.01000001, 10**400):
        before = filt.checkpoint()
        rejects(lambda: filt.push(invalid), GuardViolation)
        require(filt.checkpoint() == before, "rejected input is atomic")
    bounded = FlowDecimator(replace(config, max_input_samples=3))
    bounded.process([.001, -.001, .001])
    before = bounded.checkpoint()
    rejects(lambda: bounded.push(0.), GuardViolation)
    require(bounded.checkpoint() == before, "sample quota is atomic")
    tiny = FlowDecimator(replace(config, max_output_abs_m3_s=1e-30))
    before = tiny.checkpoint()
    rejects(lambda: tiny.push(.001), GuardViolation)
    require(tiny.checkpoint() == before, "output guard is atomic")
    partial = FlowDecimator(config)
    rejects(lambda: partial.process([.001, -.001, float("nan")]), GuardViolation)
    require(partial.input_samples == 2, "documented partial block progress")
    checkpoint = whole.checkpoint()
    for kwargs in ({"ring": list(checkpoint.ring)}, {"ring": checkpoint.ring[:-1]},
                   {"ring": (float("nan"),) + checkpoint.ring[1:]},
                   {"input_samples": -1}, {"input_samples": True},
                   {"next_index": (checkpoint.next_index + 1) % len(taps)},
                   {"output_samples": checkpoint.output_samples + 1},
                   {"version": 2}, {"version": True}, {"config": {}}):
        rejects(lambda kwargs=kwargs: replace(checkpoint, **kwargs))
    fresh = FlowDecimator(config).checkpoint()
    rejects(lambda: replace(fresh, ring=(.001,) + fresh.ring[1:]))
    rejects(lambda: setattr(config, "oversample", 8), FrozenInstanceError)
    rejects(lambda: setattr(checkpoint, "input_samples", 0), FrozenInstanceError)
    rejects(lambda: checkpoint.ring.__setitem__(0, .1), AttributeError)
    rejects(lambda: FlowDecimator.from_checkpoint({}))
    rejects(lambda: FlowDecimator({}))
    for invalid_m in (True, 2., 0, 1, 3, 16, "4", None):
        rejects(lambda: DecimatorConfig(invalid_m))
    for kwargs in ({"max_input_abs_m3_s": True}, {"max_input_abs_m3_s": .1},
                   {"max_input_abs_m3_s": 0.}, {"max_input_abs_m3_s": float("nan")},
                   {"max_input_abs_m3_s": 10**400}, {"max_output_abs_m3_s": .021},
                   {"max_output_abs_m3_s": -1.}, {"max_output_abs_m3_s": float("inf")},
                   {"max_input_samples": 0}, {"max_input_samples": 2_000_001},
                   {"max_input_samples": True}, {"max_input_samples": 1.}):
        rejects(lambda kwargs=kwargs: replace(config, **kwargs))
    return {"tap_count": len(taps), "sum_taps": math.fsum(taps),
            "l1_norm": math.fsum(abs(t) for t in taps), "group_delay_output_samples": 18,
            "group_delay_seconds": config.delay_s, "signed_impulse_phases_tested": 2*m,
            "checkpoint_positions": positions, "block_and_checkpoint_parity": "bit_exact",
            "finite_bounded_immutable_guards": "pass"}


def response_checks(m: int, raw: Path) -> dict:
    f = FlowDecimator(DecimatorConfig(m))
    bands = (("passband", 0., 16000.), ("stopband", 24000., f.config.input_rate/2))
    result = {}
    with gzip.open(raw / f"filter_response_M{m}.csv.gz", "xt", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("band", "frequency_hz", "signed_zero_phase_gain", "amplitude_db"))
        for band, low, high in bands:
            minimum, maximum, maximum_at = float("inf"), -float("inf"), None
            for index in range(GRID_POINTS):
                frequency = low + (high-low)*index/(GRID_POINTS-1)
                signed = signed_response(f.taps, frequency, f.config.input_rate)
                gain_db = db(abs(signed))
                writer.writerow((band, frequency, signed, gain_db))
                minimum = min(minimum, gain_db)
                if gain_db > maximum:
                    maximum, maximum_at = gain_db, frequency
            if band == "passband":
                require(max(abs(minimum), abs(maximum)) <= .01, "passband <= 0.01 dB")
            else:
                require(maximum <= -80, "stopband >= 80 dB rejection")
            result[band] = {"frequencies": GRID_POINTS, "from_hz": low, "to_hz": high,
                            "minimum_db": minimum, "maximum_db": maximum, "maximum_at_hz": maximum_at}
    return result


def alias_frequency(frequency: float) -> float:
    return abs((frequency + OUTPUT_RATE/2) % OUTPUT_RATE - OUTPUT_RATE/2)


def measured_amplitude(samples: tuple[float, ...], frequency: float, start: int) -> float:
    if frequency == 0:
        return abs(math.fsum(samples) / len(samples))
    if frequency == OUTPUT_RATE/2:
        return abs(math.fsum(v * (-1. if (k+start) % 2 else 1.) for k, v in enumerate(samples)) / len(samples))
    omega = 2 * math.pi * frequency / OUTPUT_RATE
    real = math.fsum(v * math.cos(omega * (k+start)) for k, v in enumerate(samples))
    imaginary = math.fsum(v * math.sin(omega * (k+start)) for k, v in enumerate(samples))
    return 2 * math.hypot(real, imaginary) / len(samples)


def tone_checks(m: int, response: dict, raw: Path) -> dict:
    config = DecimatorConfig(m)
    resolution = OUTPUT_RATE / TONE_OUTPUTS
    stop_bins = {round(2048 + (m*2048-2048) * k/64) for k in range(65)}
    stop_bins.update((2048, 2049, 2050, 2056, 2064, round(response["stopband"]["maximum_at_hz"] / resolution)))
    pass_bins = (0, 1, 64, 256, 512, 683, 1024, 1280, 1365)
    metrics = []
    started = time.perf_counter()
    with gzip.open(raw / f"filter_tones_M{m}.csv.gz", "xt", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("input_frequency_hz", "alias_frequency_hz", "output_sample_index", "raw_signed_flow_m3_s"))
        for band, bins in (("passband", pass_bins), ("stopband", sorted(stop_bins))):
            for bin_number in bins:
                frequency = bin_number * resolution
                alias = alias_frequency(frequency)
                filt = FlowDecimator(config)
                omega = 2*math.pi*frequency/config.input_rate
                values = filt.process(AMPLITUDE * math.cos(omega*n) for n in range((TONE_OUTPUTS + TONE_WARMUP)*m))
                steady = values[TONE_WARMUP:]
                gain = measured_amplitude(steady, alias, TONE_WARMUP) / AMPLITUDE
                predicted = abs(signed_response(filt.taps, frequency, config.input_rate))
                require(abs(gain-predicted) <= 5e-12, "actual decimated alias agrees with FIR response")
                gain_db = db(gain)
                require(abs(gain_db) <= .01 if band == "passband" else gain_db <= -80, "actual tone threshold")
                # Save complete startup and steady-state outputs, not just metrics.
                for k, value in enumerate(values):
                    writer.writerow((frequency, alias, k, value))
                metrics.append({"band": band, "input_hz": frequency, "observed_alias_hz": alias,
                                "measured_gain_db": gain_db, "gain_error_vs_response": gain-predicted})
    elapsed = time.perf_counter() - started
    metric_path = raw / f"filter_tone_metrics_M{m}.json"
    with metric_path.open("x", encoding="utf-8") as file:
        file.write(json.dumps(metrics, indent=2, allow_nan=False) + "\n")
    passing = [row for row in metrics if row["band"] == "passband"]
    stopping = [row for row in metrics if row["band"] == "stopband"]
    worst = max(stopping, key=lambda row: row["measured_gain_db"])
    return {"passband_tones": len(passing), "stopband_tones": len(stopping),
            "coherent_output_samples_per_tone": TONE_OUTPUTS, "startup_output_samples_discarded": TONE_WARMUP,
            "input_amplitude_m3_s": AMPLITUDE, "worst_passband_abs_db": max(abs(row["measured_gain_db"]) for row in passing),
            "worst_stopband": worst, "maximum_gain_error_vs_response": max(abs(row["gain_error_vs_response"]) for row in metrics),
            "tone_gate_elapsed_s_including_trace_io": elapsed}


def performance_check(m: int) -> dict:
    # Deterministic, finite alternating signed source; no WAV, gain or peak norm.
    count = OUTPUT_RATE*m
    filt = FlowDecimator(DecimatorConfig(m))
    started = time.perf_counter()
    output = filt.process(.001 if n % 53 < 27 else -.001 for n in range(count))
    elapsed = time.perf_counter() - started
    require(len(output) == OUTPUT_RATE, "one second output count")
    require(all(math.isfinite(v) for v in output), "finite performance output")
    return {"input_samples": count, "output_samples": len(output), "audio_duration_s": 1.,
            "wall_seconds": elapsed, "seconds_per_audio_second": elapsed,
            "peak_abs_flow_m3_s": max(abs(v) for v in output),
            "performance_is_measurement_not_realtime_gate": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True, help="fresh raw directory outside the repository")
    parser.add_argument("--output", type=Path, required=True, help="fresh directory for receipt.json; never overwritten")
    args = parser.parse_args()
    raw = args.raw_dir.resolve()
    require(not raw.is_relative_to(ROOT), "raw traces must be outside repository")
    output = args.output.resolve()
    if output.exists() or output.is_symlink() or raw.exists() or raw.is_symlink():
        parser.error("--output and --raw-dir must both be fresh, nonexistent directories")
    if output == raw or output in raw.parents or raw in output.parents:
        parser.error("--output and --raw-dir must be disjoint directories")
    output.mkdir(parents=True, exist_ok=False)
    raw.mkdir(parents=True, exist_ok=False)
    sources = (ROOT / "experiments/physical_voice/filters.py", Path(__file__).resolve(), ROOT / "docs/PHYSICAL_TRACT_DESIGN.md")
    hashes_before = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    started = time.perf_counter()
    report = {"schema": "aster_physical_flow_filter_gate_v1", "status": "running",
              "python": sys.version, "source_sha256": hashes_before, "raw_directory": str(raw),
              "design": {"cutoff_hz": 20000., "kaiser_beta": 8.6, "length": "36*M+1",
                         "retained_input_indices": "0,M,2M,...", "startup": "zero prehistory, no implicit tail flush"},
              "rates": {}}
    for m in (2, 4, 8):
        result = mechanics_checks(m)
        result["response"] = response_checks(m, raw)
        result["actual_decimated_tones"] = tone_checks(m, result["response"], raw)
        result["performance"] = performance_check(m)
        report["rates"][str(m)] = result
        print(f"M={m} PASS: passband {result['response']['passband']['minimum_db']:.6f}..{result['response']['passband']['maximum_db']:.6f} dB; "
              f"stopband {result['response']['stopband']['maximum_db']:.3f} dB; actual aliases {result['actual_decimated_tones']['worst_stopband']['measured_gain_db']:.3f} dB", flush=True)
    require(hashes_before == {str(path.relative_to(ROOT)): digest(path) for path in sources}, "source unchanged during gate")
    report["raw_artifacts"] = [{"filename": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
                               for path in sorted(raw.glob("filter_*")) if path.is_file()]
    report["elapsed_seconds"] = time.perf_counter() - started
    report["status"] = "pass"
    report["limitations"] = ["Sampled frequency grid, not an analytic supremum proof.",
                              "Filtering cannot undo alias already folded at integration rate.",
                              "One-way synthetic flow signal processing, not physiological fidelity.",
                              "Python throughput is measured; no real-time or playback claim."]
    receipt = output / "receipt.json"
    with receipt.open("x", encoding="utf-8") as file:
        file.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"PASS; receipt: {receipt}", flush=True)


if __name__ == "__main__":
    main()
