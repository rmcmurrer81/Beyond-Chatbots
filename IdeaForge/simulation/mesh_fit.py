from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
from fabrication.printer_fit import PrinterFitStore, screen_geometry, RECEIPT_FORMAT


def run(mesh_path, *, project_root=None, units=None, placement=None, orientation=None):
    """Existing mesh decoder plus explicit project/profile/units/placement screening."""
    path = Path(mesh_path)
    if not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("Mesh must be a nonempty local file at most 32 MiB.")
    with path.open("rb") as handle:
        original=handle.read(32*1024*1024+1)
    if not 0<len(original)<=32*1024*1024:
        raise ValueError("Captured mesh exceeds the 32 MiB byte limit.")
    source_hash = hashlib.sha256(original).hexdigest()
    file_type=path.suffix.lower().lstrip(".")
    if file_type not in ("stl","obj","ply"):
        return {"test":"mesh_fit","status":"unknown","geometric_fit":None,
                "reason":"Only captured STL/OBJ/PLY mesh bytes are supported.",
                "mesh_sha256":source_hash,"mesh_bytes":len(original)}
    # Decode the exact captured bytes, never a mutable path or inferred units.
    import trimesh
    mesh = trimesh.load_mesh(io.BytesIO(original),file_type=file_type,process=False)
    extents = [float(x) for x in mesh.extents]
    model = {"units": units, "size_xyz": extents,
             "placement": {"units": units, "min_xyz": placement, "orientation": orientation}}
    revision = "sha256:" + source_hash
    if project_root is None:
        receipt = {"format": RECEIPT_FORMAT, "binding": None,
                   "result": {"status": "unknown", "geometric_fit": None,
                              "reason": "Explicit project scope and reviewed printer selection are required.",
                              "declared_orientation": None, "configurations": [],
                              "limitations": screen_geometry(model, None)["limitations"]}}
        receipt_id = None
    else:
        store = PrinterFitStore(project_root)
        receipt = store.screen(model, model_revision=revision)
        receipt_id = (store.save_receipt(receipt, model, model_revision=revision)
                      if receipt["binding"]["project_id"] is not None else None)
    return {"test": "mesh_fit", "mesh": str(path), "mesh_sha256": source_hash,
            "mesh_bytes": len(original), "mesh_revision": revision,
            "watertight": bool(getattr(mesh, "is_watertight", False)),
            "unit_status":"declared mm" if units=="mm" else "unknown or unsupported units; raw coordinates",
            "declared_units": units, "extents_raw_coordinates": extents,
            "axis_aligned_fit": None, "printer_fit_receipt": receipt,
            "stored_receipt_sha256": receipt_id}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mesh")
    parser.add_argument("--project")
    parser.add_argument("--units")
    parser.add_argument("--placement", type=float, nargs=3)
    parser.add_argument("--orientation", choices=("xyz", "xzy", "yxz", "yzx", "zxy", "zyx"))
    args = parser.parse_args()
    print(json.dumps(run(args.mesh, project_root=args.project, units=args.units,
                         placement=args.placement, orientation=args.orientation), indent=2))
