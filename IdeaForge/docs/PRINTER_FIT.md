# Project-selected printer geometric fit

IdeaForge selects no printer from inventory order. A printer must be chosen for
the open project by exact `equipment_id`; duplicated IDs across local/imported
inventory sources make strict selection unavailable. Nominal inventory build
dimensions are metadata and never create a reviewed profile.

Use the workspace **Printer profile** action, or `PrinterFitStore.select`, to
save an explicitly reviewed profile. Profiles contain only:

- `format: ideaforge.printer-profile.v1`, `units: mm`
- `usable_xyz`: three positive usable dimensions, not inferred nominal dimensions
- `margins_min_xyz`, `margins_max_xyz`: three nonnegative margins at each face
- `keep_outs`: at most 32 rectangles with unique ID, positive extent,
  `min_xyz` / `max_xyz` entirely within usable XYZ
- `review`: nonempty reviewer and note explaining the declared profile

All coordinates are finite numeric values (booleans are invalid), bounded to
1,000,000 mm. Margins must leave positive extent. Profile/model/selected-item/project inputs and strict inventory/config JSON files are bounded to 128 KiB each. Existing missing optional inventory files are explicitly absent; existing unreadable/malformed, duplicate-key or nonfinite inventory inputs fail strict selection. The shared history database and its sidecars are capped at 32 MiB and checked for symlinks/reparse points/hard links before and after operations.
Only explicit millimetres are supported; missing/other units remain unknown and
are never silently converted. No slicer catalogs or AGPL data/code are copied.

Each scene part needs a separate `printer_placement` in **Edit scene**:

```json
{"units":"mm","min_xyz":[0,0,0],"orientation":"xyz"}
```

`min_xyz` is the lower corner of that part's print bounding box in printer
coordinates; it is independent of the part's assembly position and arbitrary
assembly rotation. Six screenings permute local box dimensions as
`xyz, xzy, yxz, yzx, zxy, zyx`, all at that same declared lower corner.
The declared orientation alone determines `geometric_fit`. Other configurations
are information only; IdeaForge does not select or adopt them. This is per-part
screening, not arrangement/packing or exact mesh clearance.

Effective lower bounds are the lower margins; effective upper bounds are usable
XYZ minus upper margins, including effective Z. Equality with those outer bounds
is allowed. Keep-out boundary contact counts as a hit conservatively.

Selections and receipts are append-only tables in the project's existing
`workspace3d/history.sqlite3`. Saving a profile uses an optimistic selection
revision and the same database write lock as workspace revision acceptance.
No default or physically qualified profile ships. Changing a printer requires
explicit review against its current inventory item.

Selections and receipts also bind a hash of the canonical resolved project root; copying the database to another root preserves old records but requires a fresh explicit selection there. Raw absolute root paths are not stored in receipts.

Fit receipts bind that root hash, project ID and canonical JSON hash, model hash and declared
model revision, selection revision, printer-item hash, profile hash, orientation
and placement. The project hash covers the entire current `project.json`,
including meaningful inputs and `last_updated`; ordinary conversation updates
therefore conservatively invalidate previous receipts. Receipts/selection tables
are separate from `project.json`, so saving derived receipts has no hash cycle.
Inventory order does not affect the selected item hash. Item changes, profile
changes, different project/geometry/placement/units/revision, or edited result
flags require fresh screening. Acceptance recomputes the bounded result and
compares canonical JSON (including boolean/integer types); a stored success or user-recomputed receipt hash
alone is insufficient. Workspace reload displays stale receipts as unknown. Direct stored-receipt retrieval also requires current model inputs/revision and recomputes the result; omitted or stale inputs return unknown while the original database record remains unchanged.

The existing mesh-fit and STL-inspection entry points accept `--project`,
`--units mm`, `--placement X Y Z`, and `--orientation`. Without explicit scope,
units, placement and reviewed profile, fit remains unknown. Mesh fit captures at most 32 MiB and decodes only those captured STL/OBJ/PLY bytes with explicit file type. Mesh decoding uses
the existing optional trimesh dependency; this stdlib profile module adds none.
Standalone mesh inspection remains separate from engineering model validation.

Results mean only a declared geometric bounding box fits reviewed bounds and
avoids reviewed keep-outs at the declared placement. They establish no
printability, supports, adhesion, material, toolpath, process, deformation,
CAD-dimension validity, manufacturing quality or design promotion.

## Qualification

Twelve new fixture methods cover selected ID/duplicate IDs, inventory reorder,
six configurations, margins/placement, effective Z, keep-out hit, keep-out clear,
missing profile/legacy nominal values, invalid inputs, stale/forged receipts,
restart/project isolation, and unknown units. The existing legacy workspace
expectation is corrected to unknown without a reviewed project profile.

All fixtures, compilation, SQLite concurrency, native mesh imports/decoding and
Tk interaction are **UNRUN**. Runtime HOLD and the previously failed supported
runner initialization remain in effect. Source review is distinct from testing.

Future isolated commands (proposals only, UNRUN):

```text
python -m unittest discover -s tests -p test_printer_fit.py
python -m unittest discover -s tests -p test_workspace3d.py
```
