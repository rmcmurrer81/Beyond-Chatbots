# Final-file verification for the bounded engineering pilot

The pilot now verifies the actual exported STL bytes against the reviewed cuboid
model before CAD can pass. It does not establish printability, structural safety,
real actuator fit, tolerances, thermal behavior or whole-robot capability.

For each link, the exporter saves a manifest containing the part ID, explicit mm
units, normalized parameter hash, exported file hash, assembly-coordinate bounds,
expected volume and export tolerances. Link 2's translation is checked, not merely
its dimensions. The report records Trimesh's installed version and per-file checks.

The verifier supports strict binary and ASCII STL. It checks raw finite values,
byte/triangle limits, degenerate/duplicate triangles, closed oriented positive
volume, a single connected body, expected dimensions/placement/volume/area and
facets lying on the six expected cuboid planes. It checks the file again for a
mutation during validation and binds final inventory hashes to validated bytes.
Exact duplicate coordinates are indexed for topology only. No vertices move;
no holes are filled; no triangles are deleted; no unit conversion or silent
geometry repair occurs.

Limits: 8,000,000 bytes and 100,000 triangles per file, 0.0001 mm absolute bounds
tolerance and 0.00001 relative volume/area tolerance. The existing subprocess
budget terminates expensive work on timeout. A bad artifact is failed; missing
dependencies or unreadable files are unknown. Passing means only that this
bounded export matches its reviewed idealized cuboid specification. These checks
are not a general proof against every possible mesh self-intersection.

Trimesh 4.12.2 is pinned in the optional pilot requirements. Its MIT-licensed
NumPy-based checks are compatible with IdeaForge's existing >=4.4,<5 requirement.
No major-version upgrade, GPU, model, subscription or hardware action is needed.
https://github.com/mikedh/trimesh/blob/4.12.2/trimesh/base.py

IdeaForge's standalone fabrication validator shares the strict raw inspector,
retains its prior output fields, and reports that mm is an assumption without a
reviewed-model manifest. It can still inspect multi-body print files; the
single-cuboid restriction belongs only to the pilot's reviewed-model gate.
