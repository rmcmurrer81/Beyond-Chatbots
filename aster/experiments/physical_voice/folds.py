"""Bounded, original symmetric two-mass vocal-fold experiment (SI units).

This is a sharp-switch reduced model, not validated human physiology or an exact
reproduction of any published simulator. Fixed parameters, quasi-steady Bernoulli
flow, one lower aerodynamic force, compliant unilateral contact and RK4 are used.
The initial seed is applied ONCE. There is no oscillator, random forcing, reseed,
negative damping, state clipping, tract, anti-alias filter, PCM or audio gain.

Each mass belongs to ONE fold; its mirrored partner moves symmetrically. Energy,
aerodynamic work and damping loss are PER FOLD (multiply these by PAIR_FACTOR).
Flow already crosses the full paired-fold opening and MUST NOT be doubled.
Integration-rate flow samples need low-pass filtering before audio decimation.

Sources/equation limitations: test-results/physical-voice/core/README.md and the
independent review supplied with this experiment. Parameters are fixed for the
entire plan, so no unaccounted mechanical parameter-work term is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
from typing import Iterator

PAIR_FACTOR = 2
SAMPLE_RATE = 48_000
MAX_FRAMES = 240_000
MAX_SUBSTEPS = 2_000_000
MAX_PRESSURE_PA = 2_500.0
STATE_VERSION = 1


class FoldError(ValueError):
    """Invalid finite plan, state, or pressure input."""


class GuardViolation(FoldError):
    """Integration was aborted; no clipping, resetting, or reseeding occurred."""


def _number(name: str, value: float, low: float, high: float) -> None:
    if type(value) not in (int, float):
        raise FoldError(f"{name}: finite real required")
    try:
        valid = math.isfinite(value) and low <= value <= high
    except (ValueError, OverflowError):
        valid = False
    if not valid:
        raise FoldError(f"{name}: outside [{low}, {high}]")


def _integer(name: str, value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise FoldError(f"{name}: integer in [{low}, {high}] required")


@dataclass(frozen=True, slots=True)
class FoldParameters:
    """Mass kg, stiffness N/m, damping kg/s, lengths m, density kg/m^3.

    Defaults are the reviewed mixed simplified parameterization, not fitted.
    Set coupling/contact stiffness to zero for isolated analytic checks.
    """
    lower_mass_kg: float = 1.25e-4
    upper_mass_kg: float = 2.5e-5
    lower_stiffness_n_m: float = 80.0
    upper_stiffness_n_m: float = 8.0
    coupling_stiffness_n_m: float = 25.0
    lower_contact_stiffness_n_m: float = 240.0
    upper_contact_stiffness_n_m: float = 24.0
    lower_damping_kg_s: float = .020
    upper_damping_kg_s: float = .020
    lower_rest_half_gap_m: float = .00018
    upper_rest_half_gap_m: float = .00018
    fold_length_m: float = .014
    lower_thickness_m: float = .0025
    air_density_kg_m3: float = 1.2

    def __post_init__(self) -> None:
        for name in ("lower_mass_kg", "upper_mass_kg"):
            _number(name, getattr(self, name), 1e-6, 1e-2)
        for name in ("lower_stiffness_n_m", "upper_stiffness_n_m"):
            _number(name, getattr(self, name), .01, 2_000.0)
        for name in ("coupling_stiffness_n_m", "lower_contact_stiffness_n_m", "upper_contact_stiffness_n_m"):
            _number(name, getattr(self, name), 0., 5_000.)
        for name in ("lower_damping_kg_s", "upper_damping_kg_s"):
            _number(name, getattr(self, name), 0., 1.)
        for name in ("lower_rest_half_gap_m", "upper_rest_half_gap_m"):
            _number(name, getattr(self, name), 0., .002)
        _number("fold_length_m", self.fold_length_m, .001, .04)
        _number("lower_thickness_m", self.lower_thickness_m, .0001, .01)
        _number("air_density_kg_m3", self.air_density_kg_m3, .5, 2.)


@dataclass(frozen=True, slots=True)
class GuardLimits:
    """Fail-fast numerical quotas, not claims of physiological safety.

    These may be tightened but never expanded beyond the hard maxima below.
    All RK stages AND each accepted endpoint are checked.
    """
    displacement_m: float = .020
    velocity_m_s: float = 20.
    acceleration_m_s2: float = 1e6
    mechanical_energy_j_per_fold: float = .1
    accumulated_work_j_per_fold: float = 10.
    power_w_per_fold: float = 100.
    force_n_per_fold: float = 10.
    full_flow_m3_s: float = .01

    def __post_init__(self) -> None:
        maxima = (.020, 20., 1e6, .1, 10., 100., 10., .01)
        for field, upper in zip(fields(self), maxima):
            _number(field.name, getattr(self, field.name), 1e-30, upper)


@dataclass(frozen=True, slots=True)
class PressureKnot:
    """Outgoing interval is 'hold' (right-continuous jumps) or 'linear'."""
    time_s: float
    pressure_pa: float
    outgoing: str = "hold"

    def __post_init__(self) -> None:
        _number("pressure time", self.time_s, 0., MAX_FRAMES / SAMPLE_RATE)
        _number("pressure", self.pressure_pa, 0., MAX_PRESSURE_PA)
        if type(self.outgoing) is not str or self.outgoing not in ("hold", "linear"):
            raise FoldError("pressure interpolation must be hold or linear")


@dataclass(frozen=True, slots=True)
class PressureSchedule:
    """Finite constant, ramp or on/off schedule; no callable/external input."""
    knots: tuple[PressureKnot, ...] = (PressureKnot(0., 800.),)

    def __post_init__(self) -> None:
        if type(self.knots) is not tuple or not 1 <= len(self.knots) <= 64:
            raise FoldError("pressure schedule requires 1..64 immutable knots")
        if any(type(k) is not PressureKnot for k in self.knots):
            raise FoldError("pressure schedule knot type")
        if self.knots[0].time_s != 0.:
            raise FoldError("pressure schedule must start at zero")
        if any(a.time_s >= b.time_s for a, b in zip(self.knots, self.knots[1:])):
            raise FoldError("pressure knot times must strictly increase")

    @classmethod
    def constant(cls, pressure_pa: float) -> PressureSchedule:
        return cls((PressureKnot(0., pressure_pa),))

    def at(self, time_s: float) -> float:
        _number("evaluation time", time_s, 0., MAX_FRAMES / SAMPLE_RATE)
        return self._at(time_s)

    def _at(self, time_s: float) -> float:
        # Called only at validated bounded integration times by the solver.
        previous = self.knots[0]
        for following in self.knots[1:]:
            if time_s < following.time_s:
                if previous.outgoing == "hold":
                    return previous.pressure_pa
                ratio = (time_s - previous.time_s) / (following.time_s - previous.time_s)
                return previous.pressure_pa + ratio * (following.pressure_pa - previous.pressure_pa)
            previous = following
        return previous.pressure_pa


@dataclass(frozen=True, slots=True)
class MechanicalState:
    """Displacements m, velocities m/s, cumulative signed work/loss J per fold."""
    lower_displacement_m: float = 1e-9
    upper_displacement_m: float = 0.
    lower_velocity_m_s: float = 0.
    upper_velocity_m_s: float = 0.
    aero_work_j_per_fold: float = 0.
    damping_loss_j_per_fold: float = 0.

    def values(self) -> tuple[float, ...]:
        return (self.lower_displacement_m, self.upper_displacement_m,
                self.lower_velocity_m_s, self.upper_velocity_m_s,
                self.aero_work_j_per_fold, self.damping_loss_j_per_fold)


@dataclass(frozen=True, slots=True)
class SimulationPlan:
    """A finite run; at most 5 s, 2 million substeps, 10 million stage checks.

    `initial` records the one applied deterministic physical perturbation, not
    an RNG seed. Checkpoint restore never applies it again.
    """
    frames: int = SAMPLE_RATE
    substeps: int = 4
    sample_rate: int = SAMPLE_RATE
    parameters: FoldParameters = FoldParameters()
    guards: GuardLimits = GuardLimits()
    pressure: PressureSchedule = PressureSchedule()
    initial: MechanicalState = MechanicalState()
    aerodynamic_force_enabled: bool = True

    def __post_init__(self) -> None:
        _integer("frames", self.frames, 1, MAX_FRAMES)
        if type(self.sample_rate) is not int or self.sample_rate != SAMPLE_RATE:
            raise FoldError("only 48000 Hz frame rate is supported")
        if type(self.substeps) is not int or self.substeps not in (2, 4, 8):
            raise FoldError("substeps must be 2, 4 or 8")
        if self.frames * self.substeps > MAX_SUBSTEPS:
            raise FoldError("total substep quota")
        for value, expected in ((self.parameters, FoldParameters), (self.guards, GuardLimits),
                                (self.pressure, PressureSchedule), (self.initial, MechanicalState)):
            if type(value) is not expected:
                raise FoldError(f"{expected.__name__} required")
        if type(self.aerodynamic_force_enabled) is not bool:
            raise FoldError("aerodynamic_force_enabled must be bool")
        if self.pressure.knots[-1].time_s > self.duration_s:
            raise FoldError("pressure knot outside run duration")
        if self.initial.aero_work_j_per_fold != 0 or self.initial.damping_loss_j_per_fold != 0:
            raise FoldError("initial accumulated work and loss must be zero")
        evaluate(self.initial, self.parameters, self.guards, self.pressure._at(0.),
                 self.aerodynamic_force_enabled)

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate

    @property
    def integration_rate(self) -> int:
        return self.sample_rate * self.substeps

    @property
    def total_substeps(self) -> int:
        return self.frames * self.substeps


@dataclass(frozen=True, slots=True)
class Evaluation:
    derivative: tuple[float, ...]
    energy_j_per_fold: float
    lower_force_n_per_fold: float
    full_flow_m3_s: float
    lower_gap_m: float
    upper_gap_m: float


def _evaluate(y: tuple[float, ...], p: FoldParameters, g: GuardLimits,
              pressure: float, force_enabled: bool) -> Evaluation:
    x1, x2, v1, v2, work, loss = y
    if not all(math.isfinite(z) for z in y):
        raise GuardViolation("nonfinite mechanical state")
    if abs(x1) > g.displacement_m or abs(x2) > g.displacement_m:
        raise GuardViolation("displacement quota")
    if abs(v1) > g.velocity_m_s or abs(v2) > g.velocity_m_s:
        raise GuardViolation("velocity quota")
    if abs(work) > g.accumulated_work_j_per_fold or abs(loss) > g.accumulated_work_j_per_fold:
        raise GuardViolation("accumulated work/loss quota")
    if loss < 0.:
        raise GuardViolation("negative accumulated damping loss")
    h1, h2 = p.lower_rest_half_gap_m + x1, p.upper_rest_half_gap_m + x2
    overlap1, overlap2 = min(h1, 0.), min(h2, 0.)
    # Explicit branches avoid denominator epsilon and cancellation near h1=h2.
    # Closure has priority. Compensated four-term addition preserves both
    # sub-ulp equal-rest-gap motion and cancellation at asymmetric contact.
    if h1 <= 0.:
        lower_pressure = 0.
    elif h2 <= 0.:
        lower_pressure = pressure
    else:
        gap_difference = math.fsum((p.lower_rest_half_gap_m, -p.upper_rest_half_gap_m, x1, -x2))
        lower_pressure = (pressure * (gap_difference / h1) * (1. + h2 / h1)
                          if gap_difference > 0. else 0.)
    force = p.fold_length_m * p.lower_thickness_m * lower_pressure if force_enabled else 0.
    # Full area already includes BOTH folds. Geometric closure is not a clip.
    flow = 2. * p.fold_length_m * max(0., min(h1, h2)) * math.sqrt(2. * pressure / p.air_density_kg_m3)
    coupling = p.coupling_stiffness_n_m * (x1 - x2)
    a1 = (force - p.lower_damping_kg_s * v1 - p.lower_stiffness_n_m * x1 - coupling
          - p.lower_contact_stiffness_n_m * overlap1) / p.lower_mass_kg
    a2 = (-p.upper_damping_kg_s * v2 - p.upper_stiffness_n_m * x2 + coupling
          - p.upper_contact_stiffness_n_m * overlap2) / p.upper_mass_kg
    aero_power = force * v1
    loss_power = p.lower_damping_kg_s * v1 * v1 + p.upper_damping_kg_s * v2 * v2
    energy = .5 * (p.lower_mass_kg * v1 * v1 + p.upper_mass_kg * v2 * v2
                   + p.lower_stiffness_n_m * x1 * x1 + p.upper_stiffness_n_m * x2 * x2
                   + p.coupling_stiffness_n_m * (x1 - x2) ** 2
                   + p.lower_contact_stiffness_n_m * overlap1 * overlap1
                   + p.upper_contact_stiffness_n_m * overlap2 * overlap2)
    derivative = (v1, v2, a1, a2, aero_power, loss_power)
    if not all(math.isfinite(z) for z in (*derivative, force, flow, energy)):
        raise GuardViolation("nonfinite derivative/energy/flow")
    if abs(a1) > g.acceleration_m_s2 or abs(a2) > g.acceleration_m_s2:
        raise GuardViolation("acceleration quota")
    if abs(aero_power) > g.power_w_per_fold or loss_power > g.power_w_per_fold:
        raise GuardViolation("power quota")
    if energy > g.mechanical_energy_j_per_fold:
        raise GuardViolation("mechanical energy quota")
    if abs(force) > g.force_n_per_fold or flow > g.full_flow_m3_s:
        raise GuardViolation("force/flow quota")
    return Evaluation(derivative, energy, force, flow, h1, h2)


def evaluate(state: MechanicalState, parameters: FoldParameters = FoldParameters(),
             guards: GuardLimits = GuardLimits(), pressure_pa: float = 800.,
             aerodynamic_force_enabled: bool = True) -> Evaluation:
    """Inspect the guarded SI force law and ODE at one state, without mutation."""
    for value, expected in ((state, MechanicalState), (parameters, FoldParameters), (guards, GuardLimits)):
        if type(value) is not expected:
            raise FoldError(f"{expected.__name__} required")
    _number("pressure", pressure_pa, 0., MAX_PRESSURE_PA)
    if type(aerodynamic_force_enabled) is not bool:
        raise FoldError("force flag must be bool")
    for name, value in zip((f.name for f in fields(state)), state.values()):
        _number(name, value, -10., 10.)
    return _evaluate(state.values(), parameters, guards, pressure_pa, aerodynamic_force_enabled)


@dataclass(frozen=True, slots=True)
class FoldSample:
    """One raw integration-rate endpoint, not an audio-rate PCM sample."""
    substep_index: int
    time_s: float
    pressure_pa: float
    mechanics: MechanicalState
    full_flow_m3_s: float
    energy_j_per_fold: float
    lower_force_n_per_fold: float
    lower_gap_m: float
    upper_gap_m: float


@dataclass(frozen=True, slots=True)
class StepperState:
    """Complete numerical checkpoint; persistence/authentication is out of scope.

    Equality of embedded plans is required on restore. No RNG or hidden phase
    exists. Integer substep time avoids accumulated clock drift. Includes every
    cumulative diagnostic so segmented and continuous execution agree exactly.
    """
    version: int
    plan: SimulationPlan
    substep_index: int
    mechanics: MechanicalState
    initial_energy_j_per_fold: float
    max_energy_j_per_fold: float
    max_energy_residual_j_per_fold: float
    max_abs_displacement_m: float
    max_abs_velocity_m_s: float
    max_abs_acceleration_m_s2: float
    max_overlap_m: float


class FoldStepper:
    """Bounded stream. Failure leaves the last accepted substep unchanged."""
    def __init__(self, plan: SimulationPlan = SimulationPlan(), state: StepperState | None = None):
        if type(plan) is not SimulationPlan:
            raise FoldError("SimulationPlan required")
        self._plan = plan
        first = evaluate(plan.initial, plan.parameters, plan.guards, plan.pressure._at(0.),
                         plan.aerodynamic_force_enabled)
        if state is None:
            y = plan.initial.values()
            self._state = StepperState(STATE_VERSION, plan, 0, plan.initial,
                                      first.energy_j_per_fold, first.energy_j_per_fold, 0.,
                                      max(abs(y[0]), abs(y[1])), max(abs(y[2]), abs(y[3])),
                                      max(abs(first.derivative[2]), abs(first.derivative[3])),
                                      max(0., -first.lower_gap_m, -first.upper_gap_m))
        else:
            self._validate_restore(state, first.energy_j_per_fold)
            self._state = state

    @property
    def plan(self) -> SimulationPlan:
        return self._plan

    @property
    def remaining_substeps(self) -> int:
        return self._plan.total_substeps - self._state.substep_index

    def snapshot(self) -> StepperState:
        return self._state

    def _validate_restore(self, state: StepperState, initial_energy: float) -> None:
        if type(state) is not StepperState or type(state.version) is not int or state.version != STATE_VERSION:
            raise FoldError("checkpoint version/type")
        if state.plan != self._plan:
            raise FoldError("checkpoint plan mismatch")
        _integer("checkpoint progress", state.substep_index, 0, self._plan.total_substeps)
        if state.initial_energy_j_per_fold != initial_energy:
            raise FoldError("checkpoint initial energy mismatch")
        current = evaluate(state.mechanics, self._plan.parameters, self._plan.guards,
                           self._plan.pressure._at(state.substep_index / self._plan.integration_rate),
                           self._plan.aerodynamic_force_enabled)
        g = self._plan.guards
        for name, ceiling in (("initial_energy_j_per_fold", g.mechanical_energy_j_per_fold),
                              ("max_energy_j_per_fold", g.mechanical_energy_j_per_fold),
                              ("max_energy_residual_j_per_fold", 2 * g.accumulated_work_j_per_fold + g.mechanical_energy_j_per_fold),
                              ("max_abs_displacement_m", g.displacement_m), ("max_abs_velocity_m_s", g.velocity_m_s),
                              ("max_abs_acceleration_m_s2", g.acceleration_m_s2), ("max_overlap_m", g.displacement_m)):
            _number(name, getattr(state, name), 0., ceiling)
        y = state.mechanics.values()
        residual = abs(current.energy_j_per_fold - initial_energy - y[4] + y[5])
        if (state.max_energy_j_per_fold < max(initial_energy, current.energy_j_per_fold)
                or state.max_energy_residual_j_per_fold < residual
                or state.max_abs_displacement_m < max(abs(y[0]), abs(y[1]))
                or state.max_abs_velocity_m_s < max(abs(y[2]), abs(y[3]))
                or state.max_abs_acceleration_m_s2 < max(abs(current.derivative[2]), abs(current.derivative[3]))
                or state.max_overlap_m < max(0., -current.lower_gap_m, -current.upper_gap_m)):
            raise FoldError("checkpoint cumulative diagnostics inconsistent")
        if state.substep_index == 0 and state.mechanics != self._plan.initial:
            raise FoldError("checkpoint initial state mismatch")

    def step_substep(self) -> FoldSample:
        if not self.remaining_substeps:
            raise StopIteration
        p = self._plan
        before = self._state
        n = before.substep_index
        dt = 1. / p.integration_rate
        # Times recomputed from integer progress; pressure is evaluated at EVERY stage.
        t, tm, te = n / p.integration_rate, (n + .5) / p.integration_rate, (n + 1) / p.integration_rate
        y = before.mechanics.values()
        def rhs(values: tuple[float, ...], time: float) -> Evaluation:
            try:
                return _evaluate(values, p.parameters, p.guards, p.pressure._at(time), p.aerodynamic_force_enabled)
            except GuardViolation as exc:
                raise GuardViolation(f"substep {n}, time {time:.17g}: {exc}") from exc
        a = rhs(y, t)
        yb = tuple(z + .5 * dt * k for z, k in zip(y, a.derivative))
        b = rhs(yb, tm)
        yc = tuple(z + .5 * dt * k for z, k in zip(y, b.derivative))
        c = rhs(yc, tm)
        yd = tuple(z + dt * k for z, k in zip(y, c.derivative))
        d = rhs(yd, te)
        yn = tuple(z + dt / 6. * (ka + 2. * kb + 2. * kc + kd)
                   for z, ka, kb, kc, kd in zip(y, a.derivative, b.derivative, c.derivative, d.derivative))
        endpoint = rhs(yn, te)
        stages = (a, b, c, d, endpoint)
        stage_values = (y, yb, yc, yd, yn)
        residual = abs(endpoint.energy_j_per_fold - before.initial_energy_j_per_fold - yn[4] + yn[5])
        mechanics = MechanicalState(*yn)
        self._state = StepperState(
            STATE_VERSION, p, n + 1, mechanics, before.initial_energy_j_per_fold,
            max(before.max_energy_j_per_fold, *(e.energy_j_per_fold for e in stages)),
            max(before.max_energy_residual_j_per_fold, residual),
            max(before.max_abs_displacement_m, *(abs(z[i]) for z in stage_values for i in (0, 1))),
            max(before.max_abs_velocity_m_s, *(abs(z[i]) for z in stage_values for i in (2, 3))),
            max(before.max_abs_acceleration_m_s2, *(abs(e.derivative[i]) for e in stages for i in (2, 3))),
            max(before.max_overlap_m, *(-gap for e in stages for gap in (e.lower_gap_m, e.upper_gap_m))))
        return FoldSample(n + 1, te, p.pressure._at(te), mechanics, endpoint.full_flow_m3_s,
                          endpoint.energy_j_per_fold, endpoint.lower_force_n_per_fold,
                          endpoint.lower_gap_m, endpoint.upper_gap_m)

    def step_frame(self) -> tuple[FoldSample, ...]:
        """Return 2/4/8 RAW substep samples, without discarding high-rate flow.

        This convenience method requires a frame boundary. Use step_substep or
        iteration to resume a checkpoint at any integration-rate boundary.
        """
        if self._state.substep_index % self._plan.substeps:
            raise FoldError("step_frame requires frame-aligned progress")
        if not self.remaining_substeps:
            raise StopIteration
        return tuple(self.step_substep() for _ in range(self._plan.substeps))

    def __iter__(self) -> Iterator[FoldSample]:
        while self.remaining_substeps:
            yield self.step_substep()


@dataclass(frozen=True, slots=True)
class MomentsState:
    count: int = 0
    mean: float = 0.
    m2: float = 0.
    minimum: float = 0.
    maximum: float = 0.


class Moments:
    """Stable population variance using Welford, never RMS^2 - mean^2."""
    def __init__(self, state: MomentsState = MomentsState()):
        if type(state) is not MomentsState:
            raise FoldError("MomentsState required")
        _integer("moment count", state.count, 0, MAX_SUBSTEPS)
        for name in ("mean", "minimum", "maximum"):
            _number(name, getattr(state, name), -1e6, 1e6)
        _number("m2", state.m2, 0., 4e18)
        if state.m2 < 0 or state.minimum > state.maximum:
            raise FoldError("invalid moments")
        if state.count == 0 and state != MomentsState():
            raise FoldError("empty moments must be zero")
        if state.count == 1 and (state.m2 or state.minimum != state.mean or state.maximum != state.mean):
            raise FoldError("single observation moments inconsistent")
        if state.count and not state.minimum <= state.mean <= state.maximum:
            raise FoldError("moment mean outside extrema")
        self.count, self.mean, self.m2 = state.count, state.mean, state.m2
        self.minimum, self.maximum = state.minimum, state.maximum

    def add(self, value: float) -> None:
        _number("observation", value, -1e6, 1e6)
        if self.count >= MAX_SUBSTEPS:
            raise FoldError("moment sample quota")
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (value - self.mean)
        if self.count == 1:
            self.minimum = self.maximum = value
        else:
            self.minimum = min(self.minimum, value)
            self.maximum = max(self.maximum, value)

    @property
    def variance(self) -> float:
        return self.m2 / self.count if self.count else 0.

    def snapshot(self) -> MomentsState:
        return MomentsState(self.count, self.mean, self.m2, self.minimum, self.maximum)


@dataclass(frozen=True, slots=True)
class WindowState:
    """Complete state of a separately selected measurement window."""
    parameters: FoldParameters
    moments: tuple[MomentsState, ...]
    closed_count: int
    previous_time_s: float | None
    previous_x1_m: float
    last_crossing_s: float | None
    crossing_count: int
    period_sum_s: float
    period_min_s: float | None
    period_max_s: float


class WindowMetrics:
    """Caller selects the window; x1 upward crossings estimate mechanical F0.

    AC mechanical energy is the quadratic kinetic/spring/coupling energy of
    deviations from the window mean, excluding nonlinear contact energy.
    F0 is suppressed below displacement/AC-energy floors. Transients can still
    cross zero: nonzero F0 alone is NEVER a self-sustained-oscillation gate.
    """
    def __init__(self, parameters: FoldParameters = FoldParameters(), state: WindowState | None = None):
        if type(parameters) is not FoldParameters:
            raise FoldError("FoldParameters required")
        self.parameters = parameters
        if state is None:
            self._moments = [Moments() for _ in range(6)]  # x1,x2,v1,v2,x1-x2,U
            self.closed_count = self.crossing_count = 0
            self.previous_time_s = self.last_crossing_s = self.period_min_s = None
            self.previous_x1_m = self.period_sum_s = self.period_max_s = 0.
        else:
            if type(state) is not WindowState or state.parameters != parameters:
                raise FoldError("window checkpoint parameters/type")
            if type(state.moments) is not tuple or len(state.moments) != 6:
                raise FoldError("window moments length")
            self._moments = [Moments(s) for s in state.moments]
            count = self._moments[0].count
            if any(s.count != count for s in self._moments):
                raise FoldError("window moment counts disagree")
            _integer("closed count", state.closed_count, 0, count)
            _integer("crossing count", state.crossing_count, 0, count)
            for name in ("previous_time_s", "last_crossing_s", "period_min_s"):
                value = getattr(state, name)
                if value is not None:
                    _number(name, value, 0., MAX_FRAMES / SAMPLE_RATE)
            for name in ("period_sum_s", "period_max_s"):
                _number(name, getattr(state, name), 0., MAX_FRAMES / SAMPLE_RATE)
            _number("previous_x1_m", state.previous_x1_m, -.02, .02)
            if bool(count) != (state.previous_time_s is not None):
                raise FoldError("window previous-time mismatch")
            if bool(state.crossing_count) != (state.last_crossing_s is not None):
                raise FoldError("window crossing mismatch")
            if (state.last_crossing_s is not None and state.last_crossing_s > state.previous_time_s
                    or state.crossing_count < 2 and (state.period_sum_s or state.period_min_s is not None or state.period_max_s)
                    or state.crossing_count >= 2 and (state.period_min_s is None or not 0 < state.period_min_s <= state.period_max_s)):
                raise FoldError("window period inconsistency")
            if state.crossing_count >= 2 and state.period_sum_s <= 0.:
                raise FoldError("window period sum must be positive")
            if count == 0 and state.previous_x1_m != 0.:
                raise FoldError("empty window previous displacement must be zero")
            for field in fields(state):
                if field.name not in ("parameters", "moments"):
                    setattr(self, field.name, getattr(state, field.name))

    def observe(self, sample: FoldSample) -> None:
        if type(sample) is not FoldSample:
            raise FoldError("FoldSample required")
        if type(sample.mechanics) is not MechanicalState:
            raise FoldError("sample mechanics type")
        _integer("sample substep index", sample.substep_index, 1, MAX_SUBSTEPS)
        _number("sample time", sample.time_s, 0., MAX_FRAMES / SAMPLE_RATE)
        _number("sample pressure", sample.pressure_pa, 0., MAX_PRESSURE_PA)
        _number("sample energy", sample.energy_j_per_fold, 0., .1)
        _number("sample force", sample.lower_force_n_per_fold, 0., 10.)
        _number("sample flow", sample.full_flow_m3_s, 0., .01)
        for value in sample.mechanics.values():
            _number("sample mechanical quantity", value, -20., 20.)
        if self.previous_time_s is not None and sample.time_s <= self.previous_time_s:
            raise FoldError("window samples must have increasing times")
        x1, x2, v1, v2, _, _ = sample.mechanics.values()
        values = (x1, x2, v1, v2, x1 - x2, sample.full_flow_m3_s)
        # Validate all inputs before mutating the window.
        for value in (*values, sample.lower_gap_m, sample.upper_gap_m):
            _number("sample quantity", value, -1e6, 1e6)
        if self._moments[0].count >= MAX_SUBSTEPS:
            raise FoldError("window sample quota")
        if self.previous_time_s is not None and self.previous_x1_m <= 0. < x1:
            fraction = -self.previous_x1_m / (x1 - self.previous_x1_m)
            crossing = self.previous_time_s + fraction * (sample.time_s - self.previous_time_s)
            if self.last_crossing_s is not None:
                period = crossing - self.last_crossing_s
                self.period_sum_s += period
                self.period_min_s = period if self.period_min_s is None else min(self.period_min_s, period)
                self.period_max_s = max(self.period_max_s, period)
            self.last_crossing_s = crossing
            self.crossing_count += 1
        for moment, value in zip(self._moments, values):
            moment.add(value)
        self.closed_count += int(min(sample.lower_gap_m, sample.upper_gap_m) <= 0.)
        self.previous_time_s, self.previous_x1_m = sample.time_s, x1

    def snapshot(self) -> WindowState:
        return WindowState(self.parameters, tuple(m.snapshot() for m in self._moments),
                           self.closed_count, self.previous_time_s, self.previous_x1_m,
                           self.last_crossing_s, self.crossing_count, self.period_sum_s,
                           self.period_min_s, self.period_max_s)

    def summary(self) -> dict[str, float | int]:
        x1, x2, v1, v2, difference, flow = self._moments
        p = self.parameters
        ac_energy = .5 * (p.lower_mass_kg * v1.variance + p.upper_mass_kg * v2.variance
                          + p.lower_stiffness_n_m * x1.variance + p.upper_stiffness_n_m * x2.variance
                          + p.coupling_stiffness_n_m * difference.variance)
        lower_ptp = x1.maximum - x1.minimum
        valid_frequency = lower_ptp > 1e-8 and ac_energy > 1e-16 and self.crossing_count >= 2
        frequency = (self.crossing_count - 1) / self.period_sum_s if valid_frequency else 0.
        return {"count": x1.count, "f0_hz": frequency, "upward_crossings": self.crossing_count,
                "lower_ptp_m": lower_ptp, "upper_ptp_m": x2.maximum - x2.minimum,
                "lower_ac_rms_m": math.sqrt(x1.variance), "upper_ac_rms_m": math.sqrt(x2.variance),
                "ac_linear_mechanical_energy_j_per_fold": ac_energy,
                "full_flow_mean_m3_s": flow.mean, "full_flow_ac_rms_m3_s": math.sqrt(flow.variance),
                "full_flow_ptp_m3_s": flow.maximum - flow.minimum,
                "geometric_closed_fraction": self.closed_count / x1.count if x1.count else 0.,
                "period_min_s": self.period_min_s or 0., "period_max_s": self.period_max_s}
