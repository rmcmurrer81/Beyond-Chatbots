# Reviewed oral/nasal tract design

This design is now implemented and independently checked in the optional physical
voice experiment. The [tract/filter review](../test-results/physical-voice/tract/independent-implementation-review.json)
records its numerical gate; coupled pipeline, platform CI and perceptual quality
are separate qualifications. All geometry below is original synthetic design,
not measured speaker anatomy.

## Delay and geometry

The first topology uses 24 oral sections and 16 nasal sections, each with one
sample of propagation delay in each direction at 48 kHz. Sound speed is 343 m/s,
so the oral length is 171.5 mm. The nasal branch joins after oral section 12.
Topology, nasal geometry and velum opening remain fixed within a clip. Oral
controls smoothly alter positive section areas; the source section stays fixed.

Tongue-like position moves a broad constriction, tongue-like height deepens it,
jaw opening widens the anterior region, and lip rounding narrows the last
sections. An original smooth log-area mapping stays within a documented numerical
area envelope. This is area-function control, without a tongue surface, palate
contact, lip protrusion, stops or turbulence. It is distinct from anatomical
articulatory synthesis. [Story, 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC4222052/)

## Power-normalized propagation

Use area A in m², admittance Y=A/(ρc), and root-power wave w=√Y·p. Thus w² is
traveling acoustic power, with pressure in Pa and volume flow in m³/s.
[Acoustic tube units](https://www.dsprelated.com/freebooks/pasp/Ideal_Acoustic_Tube.html)

For incoming port waves a and uᵢ=√Yᵢ, the outgoing junction waves are:

    b = 2u(uᵀa)/(uᵀu) − a

The matrix is orthogonal, so a junction preserves squared-wave norm. Stored
root-power waves are not rescaled when areas change. This gives passive numerical
articulation; actual moving-wall or muscular work is omitted.
[Normalized scattering](https://www.dsprelated.com/freebooks/pasp/Normalized_Scattering.html),
[time-varying normalization](https://www.dsprelated.com/freebooks/pasp/Power_Normalized_Waveguide_Filters.html)

## Prescribed source and acoustic ledger

With a returning toward the glottis and b launched into the tract, prescribed
volume flow U requires b=a+U/√Y₀. Its pressure is (a+b)/√Y₀. Signed source work
per sample is Δt·(b²−a²)=Δt·p·U, including the interference term. A reflection
coefficient below one would change the prescribed flow and is not silently added.
[Root-power formulation](https://www.dsprelated.com/freebooks/pasp/Root_Power_Waves.html)

Delay storage is Δt times the sum of squared waves. Include radiation-filter
state energy and the loss at every propagation gain. Change in total stored
energy must equal signed source work minus propagation loss and both outlet
energies. Track positive/negative source work separately. This ledger is separate
from fold mechanical/aerodynamic work: a one-way imposed source does not close a
combined fluid–tissue–tract energy budget.

## Radiation and nasal closure

An original one-state orthogonal allpass boundary splits incident power into
low-pass pressure reflection, high-pass radiation, and stored state. Its
sample-exact identity is a²+s²=b²+r²+s_next². This avoids an independently scaled
output differentiator. A fixed 5 kHz cutoff is a synthetic design parameter, not
an exact mouth radiation impedance.
[Power-complementary construction](https://ftp.fpgarelated.com/freebooks/pasp/Power_Complementary_Reflection_Transmission.html)

Radiation has zero DC response; constant source flow may cause startup/offset
transients. Outlet signals are synthetic root-power values, not calibrated
far-field pressure. A fixed mono mix does not replace the separate lip/nose
energy accounts. Real unflanged-pipe radiation is a future model upgrade.
[Levine and Schwinger, 1948](https://journals.aps.org/pr/abstract/10.1103/PhysRev.73.383)

At exactly closed velum, use ordinary oral two-port scattering and a rigid +1
reflection for the nasal inlet. A zero weight in the three-port matrix instead
gives −1 pressure-release reflection, which is not a rigid closure. The open
velum's inlet area must be the actual first nasal section area, avoiding an
undeclared transformer. A disconnected nasal cavity may radiate its own stored
energy; closure does not erase that state.
[Reflection limits](https://dsprelated.com/freebooks/pasp/Plane_Wave_Scattering.html)

## Anti-alias design and acceptance

Mechanical flow must be filtered before decimation. For oversampling M=2,4,8,
the reviewed candidate is a DC-normalized Kaiser-windowed sinc, β=8.6, 20 kHz
cutoff and length 36M+1 (73/145/289 taps). Its delay is 18 output samples,
0.375 ms, at all three rates. Convolution is evaluated only for retained output
samples. [Kaiser FIR design](https://www.dsprelated.com/freebooks/sasp/FIR_Digital_Filter_Design.html)

The separate design calculation sampled 16,385 passband and stopband frequencies
per rate. Worst passband range was −0.000458 to +0.000241 dB; worst stopband maximum
was −87.456 dB. These sampled-grid design results do not replace implementation
tests, actual decimated-tone alias checks, block-state equivalence or performance
measurement. Filtering cannot undo alias already folded at the integration rate.
Negative filtered samples must not be clipped to zero.

Acceptance requires junction continuity/flow/norm tests; exact 24/48 sample
one-way/round-trip delays; 500/1500/2500/3500 Hz uniform quarter-wave resonances;
source identity with returning waves and negative work; passive source-off decay;
time-varying-area energy checks; nasal disconnection and open spectral changes;
≤0.01 dB filter passband error and ≥80 dB stopband rejection; decimated-tone tests;
exact checkpoint replay; and finite raw measurements before the separate fixed-
gain, peak-bounded PCM delivery stage. No per-clip peak normalization is allowed.
