"""Original, bounded root-power oral/nasal waveguide, in SI units.

24 oral and 16 nasal one-sample bidirectional sections operate at 48 kHz.
The fixed nasal branch joins after oral section 12. The prescribed glottal flow
has no glottal loss or acoustic feedback into the fold solver. Signed boundary
work includes interference with the returning wave; it is a SEPARATE acoustic
ledger, not a closed fluid/tissue energy budget.

Time-varying log-area articulation preserves stored root-power waves. It is
passive numerical articulation, not moving-wall biomechanics. The original area
mapping and fixed 5 kHz power-complementary radiation are synthetic models, not
measured anatomy or calibrated far-field sound. No PCM normalization, clipping,
state reset, oscillator, microphone, playback, or third-party code appears here.
Sources and limitations: docs/PHYSICAL_TRACT_DESIGN.md (Smith's root-power,
normalized scattering and power-complementary waveguide theory).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
from typing import Iterable

SAMPLE_RATE = 48_000
DT = 1. / SAMPLE_RATE
ORAL_SECTIONS = 24
NASAL_SECTIONS = 16
NASAL_JOIN = 12
AREA_MIN_M2 = 1e-6
AREA_MAX_M2 = 1e-3
MAX_FRAMES = 240_000
STATE_VERSION = 1
_RADIATION_ALPHA = (math.tan(math.pi * 5_000 / SAMPLE_RATE) - 1) / (math.tan(math.pi * 5_000 / SAMPLE_RATE) + 1)
_RADIATION_Q = math.sqrt(1. - _RADIATION_ALPHA ** 2)
_INV_SQRT2 = math.sqrt(.5)
_ZERO_ORAL = (0.,) * ORAL_SECTIONS
_ZERO_NASAL = (0.,) * NASAL_SECTIONS
# Original smooth synthetic tube, NOT sampled from a speaker model or anatomy.
_NASAL_AREAS = tuple(1e-4 * (1.35 + .60 * math.sin(math.pi * i / 15) ** 2) for i in range(16))


class TractError(ValueError):
    """Invalid configuration, checkpoint, geometry or input."""


class GuardViolation(TractError):
    """Numerical quota exceeded; the rejected step was not committed."""


def _number(name: str, value: float, low: float, high: float) -> None:
    if type(value) not in (int, float):
        raise TractError(f"{name}: finite real required")
    try:
        valid = math.isfinite(value) and low <= value <= high
    except (ValueError, OverflowError):
        valid = False
    if not valid:
        raise TractError(f"{name}: outside [{low}, {high}]")


def _integer(name: str, value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise TractError(f"{name}: integer in [{low}, {high}] required")


@dataclass(frozen=True, slots=True)
class Articulation:
    """Dimensionless original area-function controls, each in [0, 1]."""
    tongue_position: float = .5
    tongue_height: float = .5
    jaw_opening: float = .5
    lip_rounding: float = 0.

    def __post_init__(self) -> None:
        for field in fields(self):
            _number(field.name, getattr(self, field.name), 0., 1.)


@dataclass(frozen=True, slots=True)
class TractGuards:
    """Numerical limits, not physiological safety limits; may only be tightened."""
    max_abs_flow_m3_s: float = .02
    max_abs_root_power: float = 100.
    max_abs_boundary_pressure_pa: float = 1e6
    max_stored_energy_j: float = 10.
    max_accumulated_energy_j: float = 100.
    max_frames: int = MAX_FRAMES

    def __post_init__(self) -> None:
        for name, cap in (("max_abs_flow_m3_s", .02), ("max_abs_root_power", 100.),
                          ("max_abs_boundary_pressure_pa", 1e6), ("max_stored_energy_j", 10.),
                          ("max_accumulated_energy_j", 100.)):
            _number(name, getattr(self, name), 1e-30, cap)
        _integer("max_frames", self.max_frames, 1, MAX_FRAMES)


@dataclass(frozen=True, slots=True)
class TractConfig:
    """Fixed for a clip, including velum, nasal tube, source area and losses.

    velum_opening is either exactly 0 or [0.01, 1]. For an open velum the
    ACTUAL first nasal section area is base nasal area[0] * velum_opening;
    this same area determines the three-port junction weight. At zero, that
    tube is disconnected with a rigid +1 inlet reflection (not a zero weight).
    propagation_gain applies once to EACH traveling wave on EACH step.
    """
    velum_opening: float = 0.
    propagation_gain: float = .9995
    source_area_m2: float = 1e-4
    nasal_base_areas_m2: tuple[float, ...] = _NASAL_AREAS
    air_density_kg_m3: float = 1.2
    sound_speed_m_s: float = 343.
    guards: TractGuards = TractGuards()

    def __post_init__(self) -> None:
        _number("velum_opening", self.velum_opening, 0., 1.)
        if 0. < self.velum_opening < .01:
            raise TractError("nonzero velum_opening must be at least 0.01")
        _number("propagation_gain", self.propagation_gain, 0., 1.)
        _number("source_area_m2", self.source_area_m2, AREA_MIN_M2, AREA_MAX_M2)
        _number("air_density_kg_m3", self.air_density_kg_m3, .5, 2.)
        _number("sound_speed_m_s", self.sound_speed_m_s, 300., 400.)
        if type(self.guards) is not TractGuards:
            raise TractError("TractGuards required")
        if type(self.nasal_base_areas_m2) is not tuple or len(self.nasal_base_areas_m2) != NASAL_SECTIONS:
            raise TractError("exactly 16 immutable nasal section areas required")
        for area in self.nasal_base_areas_m2:
            _number("nasal area", area, AREA_MIN_M2, AREA_MAX_M2)
        if self.velum_opening and self.nasal_base_areas_m2[0] * self.velum_opening < AREA_MIN_M2:
            raise TractError("open velum creates a sub-envelope first nasal area")

    @property
    def nasal_areas_m2(self) -> tuple[float, ...]:
        if self.velum_opening == 0.:
            return self.nasal_base_areas_m2
        return (self.nasal_base_areas_m2[0] * self.velum_opening,) + self.nasal_base_areas_m2[1:]


def _smoothstep(x: float) -> float:
    # Only the spatial support is bounded; no simulated state is clipped.
    if x <= 0.:
        return 0.
    if x >= 1.:
        return 1.
    return x * x * (3. - 2. * x)


def oral_areas(articulation: Articulation = Articulation(), source_area_m2: float = 1e-4) -> tuple[float, ...]:
    """Smooth positive log-area mapping; index zero is fixed for the clip.

    A broad tongue constriction moves from x=.20 to .80; height deepens it.
    Jaw opens the front, rounding narrows the lip. No anatomy or muscular work
    is inferred. The exponent envelope keeps all areas within 1e-6..1e-3 m².
    """
    if type(articulation) is not Articulation:
        raise TractError("Articulation required")
    _number("source_area_m2", source_area_m2, AREA_MIN_M2, AREA_MAX_M2)
    a = articulation
    center = .2 + .6 * a.tongue_position
    result = [source_area_m2]
    for i in range(1, ORAL_SECTIONS):
        x = i / (ORAL_SECTIONS - 1)
        log_change = (.3 * math.sin(math.pi * x)
                      - 2.4 * a.tongue_height * math.exp(-.5 * ((x - center) / .17) ** 2)
                      + .8 * a.jaw_opening * _smoothstep((x - .45) / .55)
                      - 1.6 * a.lip_rounding * _smoothstep((x - .72) / .28))
        result.append(2.5e-4 * math.exp(log_change))
    return tuple(result)


def scatter(incoming: tuple[float, ...], admittances: tuple[float, ...]) -> tuple[float, ...]:
    """Orthogonal positive-area two/three-port root-power scattering.

    p_i=(a_i+b_i)/sqrt(Y_i) is equal at every port, and the sum of inward
    volume flows sqrt(Y_i)*(a_i-b_i) is zero. Admittance uses SI A/(rho*c).
    """
    if type(incoming) is not tuple or type(admittances) is not tuple or len(incoming) not in (2, 3) or len(incoming) != len(admittances):
        raise TractError("two or three immutable port waves and admittances required")
    for wave in incoming:
        _number("port wave", wave, -100., 100.)
    for y in admittances:
        _number("admittance", y, 1e-12, 1e-3)
    u = tuple(math.sqrt(y) for y in admittances)
    scale = 2. * math.fsum(w * a for w, a in zip(u, incoming)) / math.fsum(admittances)
    return tuple(w * scale - a for w, a in zip(u, incoming))


def radiation(incoming: float, state: float) -> tuple[float, float, float]:
    """Return reflected, outgoing and next storage root-power values.

    Lossless three-way energy accounting: a²+s² = reflected²+outgoing²+s'².
    Output is high-pass/DC zero; reflection low-pass. The one-state allpass
    cutoff is fixed at 5 kHz, a synthetic approximation to mouth/nose radiation.
    """
    _number("radiation incoming", incoming, -100., 100.)
    _number("radiation state", state, -100., 100.)
    return _radiation(incoming, state)


def _radiation(a: float, s: float) -> tuple[float, float, float]:
    x = a * _INV_SQRT2
    v = _RADIATION_ALPHA * x + _RADIATION_Q * s
    return -(x + v) * _INV_SQRT2, (x - v) * _INV_SQRT2, _RADIATION_Q * x - _RADIATION_ALPHA * s


@dataclass(frozen=True, slots=True)
class TractWaves:
    """Waves arriving at section ends next step, plus radiation storage.

    Each delay carries dt*w² joules. Direction 'forward' means source-to-outlet;
    'backward' means outlet-to-source. Preloading is explicit and never erased.
    """
    oral_forward: tuple[float, ...] = _ZERO_ORAL
    oral_backward: tuple[float, ...] = _ZERO_ORAL
    nasal_forward: tuple[float, ...] = _ZERO_NASAL
    nasal_backward: tuple[float, ...] = _ZERO_NASAL
    lip_radiation_state: float = 0.
    nose_radiation_state: float = 0.

    def __post_init__(self) -> None:
        for name, size in (("oral_forward", 24), ("oral_backward", 24), ("nasal_forward", 16), ("nasal_backward", 16)):
            value = getattr(self, name)
            if type(value) is not tuple or len(value) != size:
                raise TractError(f"{name}: immutable tuple of length {size} required")
            for wave in value:
                _number(name, wave, -100., 100.)
        _number("lip radiation state", self.lip_radiation_state, -100., 100.)
        _number("nose radiation state", self.nose_radiation_state, -100., 100.)

    @property
    def energy_j(self) -> float:
        return DT * math.fsum(w * w for w in self.values())

    def values(self) -> tuple[float, ...]:
        return (*self.oral_forward, *self.oral_backward, *self.nasal_forward, *self.nasal_backward,
                self.lip_radiation_state, self.nose_radiation_state)


@dataclass(frozen=True, slots=True)
class TractState:
    """Full immutable physics, clock, control and cumulative diagnostic state."""
    version: int
    config: TractConfig
    sample_index: int
    articulation: Articulation
    waves: TractWaves
    initial_energy_j: float
    source_work_j: float = 0.
    positive_source_work_j: float = 0.
    negative_source_work_j: float = 0.
    propagation_loss_j: float = 0.
    lip_out_energy_j: float = 0.
    nose_out_energy_j: float = 0.
    max_energy_j: float = 0.
    max_abs_wave: float = 0.
    max_abs_boundary_pressure_pa: float = 0.
    max_abs_source_flow_m3_s: float = 0.
    max_abs_lip_root_power: float = 0.
    max_abs_nose_root_power: float = 0.
    max_abs_step_residual_j: float = 0.
    max_abs_ledger_residual_j: float = 0.

    @property
    def energy_j(self) -> float:
        return self.waves.energy_j

    @property
    def energy_residual_j(self) -> float:
        return math.fsum((self.energy_j, -self.initial_energy_j, -self.source_work_j,
                          self.propagation_loss_j, self.lip_out_energy_j, self.nose_out_energy_j))


@dataclass(frozen=True, slots=True)
class TractSample:
    """One accepted raw acoustic sample, never PCM or far-field calibration."""
    sample_index: int
    lip_root_power: float
    nose_root_power: float
    source_flow_m3_s: float
    boundary_pressure_pa: float
    source_returning_root_power: float
    source_launched_root_power: float
    source_work_j: float
    propagation_loss_j: float
    lip_out_energy_j: float
    nose_out_energy_j: float
    stored_energy_j: float
    energy_residual_j: float


def _validate_waves(waves: TractWaves, guards: TractGuards) -> tuple[float, float]:
    if type(waves) is not TractWaves:
        raise TractError("TractWaves required")
    peak = max(abs(w) for w in waves.values())
    energy = waves.energy_j
    if peak > guards.max_abs_root_power or energy > guards.max_stored_energy_j:
        raise GuardViolation("wave or stored energy quota")
    return energy, peak


class OralNasalTract:
    """Fail-fast, sample-atomic stream. Block failure retains accepted samples."""
    def __init__(self, config: TractConfig = TractConfig(), initial: TractWaves = TractWaves(),
                 articulation: Articulation = Articulation()):
        if type(config) is not TractConfig or type(articulation) is not Articulation:
            raise TractError("TractConfig and Articulation required")
        energy, peak = _validate_waves(initial, config.guards)
        self._config = config
        self._state = TractState(STATE_VERSION, config, 0, articulation, initial, energy,
                                 max_energy_j=energy, max_abs_wave=peak)
        self._set_geometry(articulation)

    @property
    def config(self) -> TractConfig:
        return self._config

    @property
    def areas_m2(self) -> tuple[float, ...]:
        return self._areas

    def checkpoint(self) -> TractState:
        return self._state

    @classmethod
    def from_checkpoint(cls, state: TractState) -> OralNasalTract:
        if type(state) is not TractState or type(state.version) is not int or state.version != STATE_VERSION:
            raise TractError("checkpoint type or version")
        if type(state.config) is not TractConfig or type(state.articulation) is not Articulation:
            raise TractError("checkpoint config or controls")
        c, g = state.config, state.config.guards
        _integer("checkpoint progress", state.sample_index, 0, g.max_frames)
        energy, peak = _validate_waves(state.waves, g)
        for name in ("initial_energy_j", "max_energy_j"):
            _number(name, getattr(state, name), 0., g.max_stored_energy_j)
        _number("source_work_j", state.source_work_j, -g.max_accumulated_energy_j, g.max_accumulated_energy_j)
        for name in ("positive_source_work_j", "negative_source_work_j", "propagation_loss_j", "lip_out_energy_j", "nose_out_energy_j"):
            _number(name, getattr(state, name), 0., g.max_accumulated_energy_j)
        for name, ceiling in (("max_abs_wave", g.max_abs_root_power),
                              ("max_abs_boundary_pressure_pa", g.max_abs_boundary_pressure_pa),
                              ("max_abs_source_flow_m3_s", g.max_abs_flow_m3_s),
                              ("max_abs_lip_root_power", g.max_abs_root_power),
                              ("max_abs_nose_root_power", g.max_abs_root_power),
                              ("max_abs_step_residual_j", g.max_accumulated_energy_j),
                              ("max_abs_ledger_residual_j", g.max_accumulated_energy_j)):
            _number(name, getattr(state, name), 0., ceiling)
        scale = max(state.initial_energy_j, state.positive_source_work_j, state.negative_source_work_j, 1e-30)
        tolerance = 1e-9 * scale + 1e-18
        work_discrepancy = math.fsum((state.source_work_j, -state.positive_source_work_j, state.negative_source_work_j))
        if (state.max_energy_j < max(energy, state.initial_energy_j) or state.max_abs_wave < peak
                or abs(state.energy_residual_j) > tolerance or abs(work_discrepancy) > tolerance
                or state.max_abs_ledger_residual_j + tolerance < abs(state.energy_residual_j)):
            raise TractError("inconsistent checkpoint energy or extrema")
        if state.sample_index == 0 and any(getattr(state, name) != 0. for name in (
                "source_work_j", "positive_source_work_j", "negative_source_work_j", "propagation_loss_j",
                "lip_out_energy_j", "nose_out_energy_j", "max_abs_boundary_pressure_pa", "max_abs_source_flow_m3_s",
                "max_abs_lip_root_power", "max_abs_nose_root_power", "max_abs_step_residual_j", "max_abs_ledger_residual_j")):
            raise TractError("unstarted checkpoint has prior work or diagnostics")
        result = cls(c, state.waves, state.articulation)
        result._state = state
        return result

    def _geometry(self, articulation: Articulation) -> tuple:
        areas = oral_areas(articulation, self._config.source_area_m2)
        rc = self._config.air_density_kg_m3 * self._config.sound_speed_m_s
        oral_u = tuple(math.sqrt(area / rc) for area in areas)
        nasal_u = tuple(math.sqrt(area / rc) for area in self._config.nasal_areas_m2)
        oral_pairs = tuple(((u * u - v * v) / (u * u + v * v), 2. * u * v / (u * u + v * v))
                           for u, v in zip(oral_u, oral_u[1:]))
        nasal_pairs = tuple(((u * u - v * v) / (u * u + v * v), 2. * u * v / (u * u + v * v))
                           for u, v in zip(nasal_u, nasal_u[1:]))
        branch_u = (oral_u[NASAL_JOIN - 1], oral_u[NASAL_JOIN], nasal_u[0])
        return areas, oral_u[0], oral_pairs, nasal_pairs, branch_u

    def _set_geometry(self, articulation: Articulation) -> None:
        self._areas, self._source_u, self._oral_pairs, self._nasal_pairs, self._branch_u = self._geometry(articulation)

    def step(self, flow_m3_s: float, articulation: Articulation | None = None) -> TractSample:
        """Advance one sample. Controls may change; stored waves are unchanged.

        Flow at input index 0 first reaches the lips at output index 24.
        The nasal path from source through the junction to outlet is 28 samples.
        """
        state, c = self._state, self._config
        g = c.guards
        if state.sample_index >= g.max_frames:
            raise GuardViolation("tract sample quota exhausted")
        _number("source flow", flow_m3_s, -g.max_abs_flow_m3_s, g.max_abs_flow_m3_s)
        control = state.articulation if articulation is None else articulation
        if type(control) is not Articulation:
            raise TractError("Articulation required")
        # Derived geometry is committed only after a successful physics step.
        changed = control != state.articulation
        geometry = self._geometry(control) if changed else (self._areas, self._source_u, self._oral_pairs, self._nasal_pairs, self._branch_u)
        areas, source_u, oral_pairs, nasal_pairs, branch_u = geometry
        old = state.waves
        of, ob, nf, nb = old.oral_forward, old.oral_backward, old.nasal_forward, old.nasal_backward
        forward, backward, nforward, nbackward = [0.] * 24, [0.] * 24, [0.] * 16, [0.] * 16
        a = ob[0]
        b = a + flow_m3_s / source_u
        pressure = (a + b) / source_u
        # Stable difference of squares, including the signed interference term.
        source_work = DT * (b - a) * (b + a)
        forward[0] = b
        for i, (r, t) in enumerate(oral_pairs, 1):
            left, right = of[i - 1], ob[i]
            backward[i - 1], forward[i] = r * left + t * right, t * left - r * right
        if c.velum_opening == 0.:
            # Rigid nasal closure: +1, not the -1 limit from a zero 3-port weight.
            nforward[0] = nb[0]
        else:
            u, v, w = branch_u
            incoming = of[11], ob[12], nb[0]
            scale = 2. * math.fsum((u * incoming[0], v * incoming[1], w * incoming[2])) / math.fsum((u*u, v*v, w*w))
            backward[11], forward[12], nforward[0] = u*scale-incoming[0], v*scale-incoming[1], w*scale-incoming[2]
        for i, (r, t) in enumerate(nasal_pairs, 1):
            left, right = nf[i - 1], nb[i]
            nbackward[i - 1], nforward[i] = r * left + t * right, t * left - r * right
        backward[-1], lip, lip_state = _radiation(of[-1], old.lip_radiation_state)
        nbackward[-1], nose, nose_state = _radiation(nf[-1], old.nose_radiation_state)
        launched = (*forward, *backward, *nforward, *nbackward)
        gain = c.propagation_gain
        propagation_loss = DT * (1. - gain * gain) * math.fsum(w * w for w in launched)
        # Do not clip, normalize or silently clear small waves or filter tails.
        waves = TractWaves(tuple(gain*w for w in forward), tuple(gain*w for w in backward),
                           tuple(gain*w for w in nforward), tuple(gain*w for w in nbackward), lip_state, nose_state)
        energy, peak = _validate_waves(waves, g)
        raw_peak = max(peak, abs(b), abs(lip), abs(nose), *(abs(w) for w in launched))
        if raw_peak > g.max_abs_root_power or abs(pressure) > g.max_abs_boundary_pressure_pa:
            raise GuardViolation("raw wave or boundary pressure quota")
        lip_energy, nose_energy = DT*lip*lip, DT*nose*nose
        residual = math.fsum((energy, -state.energy_j, -source_work, propagation_loss, lip_energy, nose_energy))
        scale = max(energy, state.energy_j, abs(source_work), propagation_loss, lip_energy, nose_energy, 1e-30)
        if not math.isfinite(residual) or abs(residual) > 5e-13 * scale:
            raise GuardViolation("per-step acoustic energy identity")
        totals = (state.source_work_j + source_work,
                  state.positive_source_work_j + max(source_work, 0.),
                  state.negative_source_work_j + max(-source_work, 0.),
                  state.propagation_loss_j + propagation_loss,
                  state.lip_out_energy_j + lip_energy,
                  state.nose_out_energy_j + nose_energy)
        if any(not math.isfinite(x) or abs(x) > g.max_accumulated_energy_j for x in totals):
            raise GuardViolation("cumulative acoustic work/loss quota")
        ledger_residual = math.fsum((energy, -state.initial_energy_j, -totals[0], totals[3], totals[4], totals[5]))
        if abs(ledger_residual) > 1e-9 * max(state.initial_energy_j, totals[1], totals[2], 1e-30) + 1e-18:
            raise GuardViolation("cumulative acoustic energy identity")
        next_state = TractState(STATE_VERSION, c, state.sample_index+1, control, waves, state.initial_energy_j,
                               *totals, max(state.max_energy_j, energy), max(state.max_abs_wave, raw_peak),
                               max(state.max_abs_boundary_pressure_pa, abs(pressure)),
                               max(state.max_abs_source_flow_m3_s, abs(flow_m3_s)),
                               max(state.max_abs_lip_root_power, abs(lip)), max(state.max_abs_nose_root_power, abs(nose)),
                               max(state.max_abs_step_residual_j, abs(residual)),
                               max(state.max_abs_ledger_residual_j, abs(ledger_residual)))
        sample = TractSample(state.sample_index, lip, nose, flow_m3_s, pressure, a, b,
                             source_work, propagation_loss, lip_energy, nose_energy, energy, residual)
        self._state = next_state
        if changed:
            self._areas, self._source_u, self._oral_pairs, self._nasal_pairs, self._branch_u = geometry
        return sample

    def process(self, flows: Iterable[float], articulation: Articulation | None = None) -> tuple[TractSample, ...]:
        """One constant control target per block; step accepts per-sample controls."""
        return tuple(self.step(flow, articulation) for flow in flows)
