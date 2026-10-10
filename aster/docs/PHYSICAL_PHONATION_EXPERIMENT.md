# Reduced physical phonation experiment

This opt-in research stage explores part of the human voice mechanism: pressure
and airflow can drive flexible, contacting vocal folds into self-oscillation.
The [source–filter instrument](VOICE_BOX_EXPERIMENT.md) remains intact. Neither
experiment is the production Aster voice or a qualified production NewBrain.

The reduced fold mechanics, oral/nasal tract and anti-alias filter are implemented
and have passed separate numerical and independent-review gates. The
[usage guide](PHYSICAL_VOICE_USAGE.md) describes explicit waveform export,
owner-bound replay and the saved experimental brain-output adapter. A checked
waveform does not establish speech intelligibility or human anatomical fidelity.

## Scientific model and limitations

Two coupled masses describe the lower and upper regions of one vocal fold; a
mirrored partner makes the opening symmetric. All internal quantities use SI.
The independent coordinates are displacement and velocity. No commanded pitch,
sine wave, periodic kick, negative damping or recurring seed drives the model.
One small, explicitly recorded initial displacement can perturb its equilibrium.

For each mass, the net force is aerodynamic force minus viscous damping, spring
restoration and inter-mass coupling, plus unilateral contact restoration. Signed
half-gap is rest half-gap plus displacement. Full opening area is twice fold
length times half-gap. A negative half-gap represents compliant tissue overlap,
not a negative airflow area and not rigid nonpenetration.

Airflow is the positive minimum opening area multiplied by the Bernoulli velocity
from subglottal pressure and air density. The lower mass receives a pressure force
that depends on the ratio between upper and lower gaps. The upper aerodynamic
force is zero in this deliberately simple separation approximation. Closed
branches are evaluated explicitly; no denominator epsilon hides a singularity.

The mechanics are checked against published reduced-model equations. The chosen
sharp switches simplify the smoothed pressure/contact switches in
[Guasch et al. 2024, equations 2, 3d and 6](https://www.legi.grenoble-inp.fr/people/annemie.van-hirtum/_publi/Guasch_Chaos2024.pdf).
Mass, spring, damping and dimension values come from
[Xue et al. 2010, Table I](https://pmc.ncbi.nlm.nih.gov/articles/PMC2933257/).
That paper's Navier–Stokes airflow is not implemented here, and its parameter set
differs from Guasch's. This is a mixed, original reduced experiment, not an exact
reproduction of either paper. [Fulcher et al. 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3477191/)
provides a further check on mechanical equations and force units; its different
airflow model's onset threshold is not used as this experiment's threshold.

Nominal constants are masses 0.125 g and 0.025 g; spring stiffnesses 80 and 8 N/m;
coupling stiffness 25 N/m; damping 0.020 kg/s on each mass; fold length 14 mm;
lower/upper layer thicknesses 2.5/0.5 mm; contact stiffness three times each
spring stiffness; rest half-gaps 0.18 mm; and air density 1.2 kg/m³. These are
research parameters, not a measurement of Aster, a real speaker, or female anatomy.

The model omits three-dimensional tissue, muscle activation, mucosal propagation
beyond two masses, viscous glottal losses, pressure recovery and two-way acoustic
loading. Its fully closed equilibrium receives no opening aerodynamic force
under these branches. Extending adduction needs a different reviewed law. The
experiment cannot establish anatomical fidelity, human vocal health, natural
speech, perceived gender or clinical usefulness.

## Energy and verification rules

Mechanical energy includes mass kinetic energy, both spring energies, coupling
energy and contact potential. For fixed mechanical parameters, its change equals
aerodynamic work minus damping loss. These quantities are **per fold**. Double
energy and mechanical work/loss for the mirrored pair; airflow already uses the
full opening and is not doubled. This mechanical identity does not establish
complete fluid-plus-tissue energy conservation.

Contact and pressure are recomputed at every RK4 stage, including pressure ramps
and offsets. Guard failures must stop the calculation rather than clamp internal
displacements, reset the state, change gain or introduce another seed. Sharp
switches make the ODE nonsmooth, so ordinary fourth-order RK4 convergence is not
assumed. Numerical refinement, raw amplitude, frequency, contact fraction and
mechanical work residual are separate checks.

The independent pre-implementation equation check produced about 135.9 Hz at
800 Pa, and small-seed growth changed sign between 230 and 231 Pa for the exact
simplified equations. That is a numerical reference, not a physiological onset
threshold or proof of a bifurcation value. Exact-zero initial state remains still.
Removing pressure or aerodynamic force makes mechanical motion decay. Disabling
force at positive pressure can leave constant through-flow, so an oscillation
gate uses displacement and AC energy rather than raw flow RMS.

The compact [equation review](../test-results/physical-voice/equation-review/summary.json)
retains original test recipes, numeric rows and corrected diagnostic failures.
In particular, flow can have two local maxima per fold cycle; counting them would
double the estimated fundamental frequency. Interpolated fold crossings and
Welford variance avoid that and false variance caused by subtracting squared means.

## Provenance and staged acceptance

No VocalTractLab implementation, binary, speaker model, recording or other voice
asset is imported. The code is written for Aster from equations and general
physical principles. Existing repository licensing remains unchanged. Published
equations do not establish patent clearance or exclusive ownership of a method.

Raw, bounded synthetic mechanical traces stay local. Repository receipts contain
compact measurements, input recipes and hashes; a quiet WAV alone is not evidence
of physical self-oscillation. The mechanical gate must pass before an articulated
tract, anti-alias audio export or a brain-intent adapter is qualified. Each of
those has separate tests and limitations. Playback remains explicit and under
the user's control.
