# Local 3D assembly workspace: first working slice

Open a saved IdeaForge project and choose **3D Assembly Workspace**. In Humanoid
Researcher, choose that button in the research window or AI chat window.

This is a real wireframe 3D assembly viewer and geometric screening tool. It is
not a CAD kernel, a physics engine, a fabrication guarantee, or a safety sign-off.
The blue/cyan presentation follows the supplied visual reference without treating
that picture as measurable geometry.

## What works

- Box and cylinder parts with explicit millimetre dimensions, Euler rotations,
  parent-relative positions, stable IDs and source provenance.
- Rotate by dragging, Shift-drag to pan, wheel to zoom, click a part to inspect,
  and Fit to recenter. Exploded view changes only the display.
- Explicit parent transforms assemble parts. Optional bounded X/Y/Z rotary joints
  pivot at the part's local origin. The animated preview is kinematics only.
- Import assembly JSON, add a measured box, or edit the scene JSON to set mounts,
  parent relationships, cylinder geometry and joints. No generated Python, shell,
  URDF or model-supplied code is executed.
- Edit arbitrary idea requirements, subsystem dependencies and research questions.
  Iron Man and holodeck maps are optional goal templates; fictional references
  are not physical specifications. Custom requirements survive background passes.
- Each saved candidate includes its exact scene hash, geometric results, reason,
  parent revision and evidence references. History is immutable through the API;
  latest, manual-input and accepted-workspace-baseline pointers are transactional.
- Compare changes, preview history, or restore a historical scene as a NEW
  candidate. Accepting a workspace baseline never changes the approved humanoid
  body or promotes it as physically validated.

## Real tests and explicit limits

The deterministic checks report positive dimensions, complete explicit units,
valid parents/joints, approximate axis-aligned bounding-box overlaps, printer
volume fit when a volume is supplied, and nine geometric samples per rotary
joint. A box overlap is only a possible interference; it is not an exact
collision/clearance verdict. Printer fit excludes supports, tolerances and
alternative print orientations.

Limits are 80 parts, eight joints, eight parent levels and a 512 KB scene. Sweeps
have a three-second wall-time budget and report failure instead of a completed
result if exceeded. Rendering caches world transforms. GUI save/test work runs
on a worker, and UI events are consumed only on the Tk thread. An editor captures
its starting revision: newer work causes a stale-save error rather than silently
being overwritten; the editor stays open.

Dynamics is explicitly unavailable in this workspace. IdeaForge's older optional
PyBullet script remains separate and is not invoked. There is no claim of strength,
thermal behavior, torque adequacy, balance control, fatigue or human safety.
Unknown geometry stays unknown. Machine-extracted measurements are not used as
validated dimensions. The example has explicit EXAMPLE provenance and is never
automatically saved as the project design.

## While the app is running

IdeaForge's existing hourly research watcher still searches its saved projects.
A separate fair, bounded local worker checks saved project geometry/evidence every
30 seconds in batches of up to 20 projects. Closing an individual project view
does not stop its jobs. Custom workspace questions feed the existing technology
horizon planner on subsequent research passes.

Humanoid Researcher's main research window now starts a scan after opening and
repeats hourly; its checkbox pauses that network schedule. Its existing single
canonical-body workspace receives local candidate checks while either the main
or chat window remains open. The chat-only window does NOT run network scans.
General independent multi-project research in Humanoid Researcher is a later
milestone; it still scans its configured robotics topics. Configured providers,
local models and connectivity must work for research to succeed.

Local jobs use SQLite leases, fingerprints and atomic revisions. Unchanged inputs
do not queue forever. Expired interrupted jobs resume after restart. A stale
geometry proposal cannot replace newer user geometry. No work runs while the
computer sleeps or after the applications close; the next launch resumes local
pending work. Running a network scan can still be interrupted by closing its app;
that existing scan pipeline is separate from the durable local geometric jobs.

New evidence currently creates a sourced candidate with geometric checks, not an
automatically invented mechanism. Changed geometry must be explicitly supplied.
The next stages are qualified source-to-parameter mappings, constrained geometry
proposals, exact collision/constraint solving, and verified dynamics integration.

## Sources and coverage

IdeaForge already discovers web results, university/lab results, OpenAlex works,
arXiv papers and images. Its current pipeline does not have a dedicated GitHub
repository search stage. Humanoid Researcher has arXiv, GDELT news discovery and
GitHub repository search, plus its configured knowledge learner. A discovered
paper/repository is not proof of reproducibility or compatibility. The workspace
preserves source paths, hashes, titles and URLs when available and explicitly
labels the records unverified. It does not claim that all metadata represents
verified primary-source engineering evidence.

## Storage and input format

Each saved project has `workspace3d/history.sqlite3`. For Humanoid Researcher's
single workspace this resides beside the workspace package; generated state is
ignored by Git. No approved canonical body is overwritten. Before a manual input
revision exists, `workspace3d/assembly.json` or `design/assembly.json` can provide
explicit geometry. After manual edits, the transactional input revision is the
authoritative scene; import again to adopt an external edited file.

See `workspace3d/example_assembly.json` for the import schema. Size is X/Y/Z;
cylinder X/Y are equal diameters. Positions are local millimetres relative to the
parent (or world for root parts), and rotations are local X/Y/Z Euler degrees.
All geometry is centered on its local origin. `provenance.status` must be
`user_supplied`, `source_reported`, `derived` or `example`, and `source` must
identify the origin of the numbers. Those labels do not certify correctness.

## Verification

`python -m unittest discover -s tests -v` exercises schema/transform validation,
actual geometric checks, custom requirements, stale edits at the store boundary,
immutable revisions, transactional manual inputs, lease recovery, crash after
revision persistence, deduplication, missing/invalid data and the actual viewer's
projection code against a headless canvas. Existing app regression suites are
also retained. A real native Tk/Windows interaction test and live research/model
smoke test are still needed; this environment has no display server.
