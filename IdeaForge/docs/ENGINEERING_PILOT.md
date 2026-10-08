# Bounded CAD and dynamics pilot

This optional CLI is a reviewed fixed-function template for **two idealized rigid links**, two ideal torque actuators and a spherical payload. It does not generate or execute Python from an LLM. It is not an Alpha5 model, full robot simulator, manufacturing-ready servo assembly, structural solver, or evidence of walking/hover/flight capability. Main app/model chat behavior is unchanged.

## Install separately

Use an isolated Python 3.11/3.12 virtual environment and the official PyPI index:

```
python -m venv .venv-pilot
# Linux/macOS:
.venv-pilot/bin/python -m pip install --index-url https://pypi.org/simple -r requirements-engineering-pilot.txt
.venv-pilot/bin/python -m engineering_pilot engineering_pilot/examples/two_link.json --output pilot-output --seconds 60 --optimize
# Windows PowerShell equivalents:
.venv-pilot\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements-engineering-pilot.txt
.venv-pilot\Scripts\python.exe -m engineering_pilot engineering_pilot/examples/two_link.json --output pilot-output --seconds 60 --optimize
```

Output directory must be new. Headless Linux Python 3.12 was tested; Windows install/runtime was **not tested**. Wheel availability and transitive compatibility depend on Python/OS. CadQuery/OCP/VTK have substantial disk requirements; use several GB free, 8 GiB RAM, CPU only. Workers use one numerical thread and one process at a time. No GPU/model download, payment or external service is used. Each expensive operation runs in a killable subprocess with the remaining 1–120 second total worker budget; process startup/cleanup and report writing can add overhead. Partial exports after timeout are not usable successful evidence. Optional modules absent or unable to load produce `unknown`, never a fabricated pass.

Direct dependency pins: CadQuery 2.6.1 (Apache-2.0), MuJoCo 3.3.7 (Apache-2.0), SciPy 1.16.2 (BSD-3-Clause). Pins are not a complete cross-platform lock. Transitive dependencies include OCP/Open CASCADE (LGPL-2.1 with exception), VTK (BSD), NumPy (BSD) and others: retain their licenses; review the actual installed distributions before redistribution. No third-party binaries are vendored.

## Inputs and claims

Every field has an exact SI unit, finite bounded value, and nonempty measurement/datasheet source. JSON requires `reviewed: true`. This is the operator's review assertion, **not independent provenance verification**. Replace every example value/source with actual measured dimensions/density, weighed payload, verified actuator joint-side torque limit, and engineering requirements before using user hardware. No dimensions or ratings are filled in silently. `example_only: true` is propagated to the report and CLI result. Never change it to false without measured inputs.

The supplied JSON is synthetic, explicitly labeled and does not describe user hardware. Calculated masses and diagonal inertias assume homogeneous, rectangular, rigid links. Payload inertia assumes a homogeneous sphere. Drive torque must be supplied at the joint (N*m); no gear ratio or peak-to-continuous rating conversion is guessed. Mass uncertainty perturbs both link density and payload by ± the supplied fraction; dimensions, friction, stiffness, COM error and actuator uncertainty are not covered.

## Geometry and mating convention

Lengths extend along +X; both hinge axes are -Y, shoulder at (0,0,0), elbow at (length1,0,0), tool/payload frame at (length1+length2,0,0). Dynamics translates this assembly up 1 m above a floor. CAD is in **mm**, with two separate touching rectangular solids in STEP and per-link STL in assembly coordinates. STL does not encode units: import it as mm. Report includes exact mating frames, volumes, density-derived BOM masses, byte sizes and SHA-256 hashes. Servos, shafts, bearings, base, fixtures and fasteners are explicitly excluded from the solid/BOM model. No bores, fits or physical mating hardware are claimed. This is a geometry/dynamics demonstration before real servo packaging work.

## Bounded checks and optimization

Cheap checks reject reach, upper-uncertainty modeled mass, payload geometry and conservative horizontal static torque violations before CAD/dynamics. `--optimize` searches exactly three dimensions (two lengths and common width) in ±10% bounds clipped to the template range, with SciPy differential evolution, seed 7, 4 generations, population multiplier 5, no polishing or parallel workers. At most 76 cheap evaluations (including baseline), then the three lightest feasible sampled proposals receive real CAD and dynamics checks. Derived proposals are not mislabeled measured inputs; original measurements remain in `input`, candidates contain derived parameters. This is not a global optimality claim.

MuJoCo uses explicit uniform-solid mass, COM and principal inertias, gravity, two bounded joints and joint-side clipped torque motors. A one-second smooth periodic trajectory is tracked with an ideal computed-torque controller (100/s² position and 20/s velocity gains), with reported pre-clipping torque requirement, tracking error and contacts. Static gravity torque is independently compared with the planar analytic expression. Tests run at 4 ms and 2 ms, then ±mass uncertainty at 2 ms. Controller uses the perturbed model in each sensitivity run: this is parameter sensitivity, **not robustness to unknown model error**. Allowed error is 0.05 rad; static cross-check tolerance is 1e-8 N*m; timestep peak torque difference must be ≤max(0.01 N*m, 2%).

MuJoCo automatic parent/weld collision filtering is disabled. Explicit adjacent link/payload contacts are excluded as connected interfaces; other link/payload and floor collisions are checked. No environment obstacles are modeled. Passing these limited checks does not establish collision safety in a real installation. Collision, saturation, excessive error or analytic mismatch fail the candidate. Missing software, timeout and computational errors remain unknown. Overall `passed` means at least one sampled candidate passed these bounded checks; individual candidate statuses remain visible. Manufacturing readiness always remains unknown.

## Reproducibility and tests

`report.json` records source input, canonical input hash, installed direct dependency versions, search seed/bounds/evaluation count, per-trial results and exported file hashes. Input/search/numeric results are repeatable with the same stack; STEP headers may contain timestamps, so byte-identical STEP files across runs are not promised. Run:

```
python -m unittest discover -s tests -p test_engineering_pilot.py -v
python -m unittest discover -s tests -v
```

Without optional dependencies, pure validation/status tests run and the real CAD/dynamics integration test explicitly skips. With the stack, it runs reproducible search, physical equations, STEP reimport/solid volume checks, STL triangle/header checks and artifact hash verification. These tests check software mechanics and this physical idealization, not LLM intelligence or user hardware performance.

References: [CadQuery exports](https://cadquery.readthedocs.io/en/stable/importexport.html), [MuJoCo computation](https://mujoco.readthedocs.io/en/stable/computation/index.html), [SciPy differential evolution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html).
