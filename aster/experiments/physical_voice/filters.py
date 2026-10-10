"""Original, bounded, standard-library anti-alias filtering for signed SI flow.

This opt-in FIR is a numerical component of the reduced physical experiment,
not a physiology model or production audio backend. The fixed reviewed design
is a DC-normalized Kaiser(beta=8.6) windowed sinc with 20 kHz cutoff, 36*M+1
coefficients, and 18 output samples (0.375 ms) of linear-phase group delay.
Only input indices 0, M, 2*M, ... produce convolution/output. Zero prehistory is
explicit; there is no implicit tail flush or negative-flow clipping.

Design rationale and source references: docs/PHYSICAL_TRACT_DESIGN.md. The
implementation is original; it does not use copied source or external assets.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

SAMPLE_RATE = 48_000
CUTOFF_HZ = 20_000.0
KAISER_BETA = 8.6
DELAY_OUTPUT_SAMPLES = 18
MAX_INPUT_SAMPLES = 2_000_000
STATE_VERSION = 1


class FilterError(ValueError):
    """Invalid configuration, finite signed sample, or complete checkpoint."""


class GuardViolation(FilterError):
    """A quota was exceeded without clipping, resetting, or committing it."""


def _finite_bound(name: str, value: float, low: float, high: float) -> None:
    if type(value) not in (int, float):
        raise FilterError(f"{name}: finite real required")
    try:
        valid = math.isfinite(value) and low <= value <= high
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise FilterError(f"{name}: outside [{low}, {high}]")


def _integer(name: str, value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise FilterError(f"{name}: integer in [{low}, {high}] required")


@dataclass(frozen=True, slots=True)
class DecimatorConfig:
    """Immutable fixed filter design with numerical quotas that may tighten.

    Flow bounds use m^3/s and are numerical limits, not physiological claims.
    The separate output bound permits signed FIR ringing. The hard sample
    quota bounds work/storage exposure even for an unbounded input iterator.
    """
    oversample: int = 4
    max_input_abs_m3_s: float = .01
    max_output_abs_m3_s: float = .02
    max_input_samples: int = MAX_INPUT_SAMPLES

    def __post_init__(self) -> None:
        if type(self.oversample) is not int or self.oversample not in (2, 4, 8):
            raise FilterError("oversample must be 2, 4 or 8")
        _finite_bound("max_input_abs_m3_s", self.max_input_abs_m3_s, 1e-30, .01)
        _finite_bound("max_output_abs_m3_s", self.max_output_abs_m3_s, 1e-30, .02)
        _integer("max_input_samples", self.max_input_samples, 1, MAX_INPUT_SAMPLES)

    @property
    def input_rate(self) -> int:
        return SAMPLE_RATE * self.oversample

    @property
    def output_rate(self) -> int:
        return SAMPLE_RATE

    @property
    def tap_count(self) -> int:
        return 36 * self.oversample + 1

    @property
    def delay_output_samples(self) -> int:
        return DELAY_OUTPUT_SAMPLES

    @property
    def delay_s(self) -> float:
        return DELAY_OUTPUT_SAMPLES / SAMPLE_RATE


def _i0(x: float) -> float:
    """I0 by its convergent nonnegative power series on the fixed beta range."""
    term = 1.0
    total = 1.0
    quarter_square = .25 * x * x
    for k in range(1, 129):
        term *= quarter_square / (k * k)
        updated = total + term
        if updated == total:
            return total
        total = updated
    raise FilterError("Kaiser I0 series did not converge")


def _make_taps(config: DecimatorConfig) -> tuple[float, ...]:
    middle = DELAY_OUTPUT_SAMPLES * config.oversample
    cutoff = CUTOFF_HZ / config.input_rate
    denominator = _i0(KAISER_BETA)
    half = []
    for k in range(middle + 1):
        offset = k - middle
        sinc = 2.0 * cutoff if offset == 0 else math.sin(2.0 * math.pi * cutoff * offset) / (math.pi * offset)
        window = _i0(KAISER_BETA * math.sqrt(1.0 - (offset / middle) ** 2)) / denominator
        half.append(sinc * window)
    unscaled = half + half[-2::-1]
    scale = math.fsum(unscaled)
    taps = tuple(value / scale for value in unscaled)
    if not all(math.isfinite(value) for value in taps) or scale <= 0:
        raise FilterError("nonfinite/invalid FIR design")
    return taps


@dataclass(frozen=True, slots=True)
class DecimatorCheckpoint:
    """Complete immutable causal state; deterministic taps are regenerated.

    ring[next_index] is the slot the NEXT accepted input will replace. Counters
    fix the decimation phase; all ring slots, including startup zeros, are saved.
    Restore validates the same invariants as direct checkpoint construction.
    """
    config: DecimatorConfig
    ring: tuple[float, ...]
    next_index: int
    input_samples: int
    output_samples: int
    version: int = STATE_VERSION

    def __post_init__(self) -> None:
        if type(self.config) is not DecimatorConfig:
            raise FilterError("DecimatorConfig required")
        # Revalidate fields as well as the immutable type (e.g. untrusted restore).
        self.config.__post_init__()
        if type(self.version) is not int or self.version != STATE_VERSION:
            raise FilterError("unsupported checkpoint version")
        if type(self.ring) is not tuple or len(self.ring) != self.config.tap_count:
            raise FilterError("complete immutable FIR ring required")
        for value in self.ring:
            _finite_bound("ring sample", value, -self.config.max_input_abs_m3_s,
                          self.config.max_input_abs_m3_s)
        _integer("input_samples", self.input_samples, 0, self.config.max_input_samples)
        _integer("output_samples", self.output_samples, 0,
                 (self.config.max_input_samples + self.config.oversample - 1) // self.config.oversample)
        _integer("next_index", self.next_index, 0, self.config.tap_count - 1)
        if self.next_index != self.input_samples % self.config.tap_count:
            raise FilterError("ring position does not match input progress")
        if self.output_samples != (self.input_samples + self.config.oversample - 1) // self.config.oversample:
            raise FilterError("output progress does not match decimation phase")
        if self.input_samples < self.config.tap_count and any(self.ring[self.input_samples:]):
            raise FilterError("unfilled startup ring slots must be zero")


class FlowDecimator:
    """Causal FIR; blocks and exact checkpoints cannot change sample results.

    A failed push leaves all state unchanged. process() commits each successful
    push in order; if a later sample fails, those earlier samples remain accepted.
    Work is a fixed-size ring update per input and one dot product per retained
    output. Config/taps are exposed immutably; mutable history remains private.
    """
    __slots__ = ("_config", "_taps", "_ring", "_next_index", "_input_samples", "_output_samples")

    def __init__(self, config: DecimatorConfig = DecimatorConfig()) -> None:
        if type(config) is not DecimatorConfig:
            raise FilterError("DecimatorConfig required")
        config.__post_init__()
        self._config = config
        self._taps = _make_taps(config)
        self._ring = [0.0] * config.tap_count
        self._next_index = 0
        self._input_samples = 0
        self._output_samples = 0

    @property
    def config(self) -> DecimatorConfig:
        return self._config

    @property
    def taps(self) -> tuple[float, ...]:
        return self._taps

    @property
    def input_samples(self) -> int:
        return self._input_samples

    @property
    def output_samples(self) -> int:
        return self._output_samples

    def push(self, sample: float) -> float | None:
        config = self._config
        try:
            _finite_bound("input flow", sample, -config.max_input_abs_m3_s, config.max_input_abs_m3_s)
        except FilterError as error:
            raise GuardViolation(str(error)) from error
        if self._input_samples >= config.max_input_samples:
            raise GuardViolation("input sample quota")
        value = float(sample)
        index = self._next_index
        output = None
        if self._input_samples % config.oversample == 0:
            # Substitute the proposed current sample without touching history.
            # The previous value in ring[index] is L samples old and is discarded.
            output = math.fsum(tap * (value if k == 0 else self._ring[(index - k) % len(self._ring)])
                               for k, tap in enumerate(self._taps))
            if not math.isfinite(output) or abs(output) > config.max_output_abs_m3_s:
                raise GuardViolation("output flow quota")
        self._ring[index] = value
        self._next_index = (index + 1) % len(self._ring)
        self._input_samples += 1
        if output is not None:
            self._output_samples += 1
        return output

    def process(self, samples: Iterable[float]) -> tuple[float, ...]:
        result = []
        for sample in samples:
            output = self.push(sample)
            if output is not None:
                result.append(output)
        return tuple(result)

    def checkpoint(self) -> DecimatorCheckpoint:
        return DecimatorCheckpoint(self._config, tuple(self._ring), self._next_index,
                                   self._input_samples, self._output_samples)

    @classmethod
    def from_checkpoint(cls, checkpoint: DecimatorCheckpoint) -> FlowDecimator:
        if type(checkpoint) is not DecimatorCheckpoint:
            raise FilterError("DecimatorCheckpoint required")
        checkpoint.__post_init__()
        restored = cls(checkpoint.config)
        restored._ring = list(checkpoint.ring)
        restored._next_index = checkpoint.next_index
        restored._input_samples = checkpoint.input_samples
        restored._output_samples = checkpoint.output_samples
        return restored
