from __future__ import annotations
import json
from engineering_pilot.mesh_verify import inspect_stl
from fabrication.printer_fit import PrinterFitStore, RECEIPT_FORMAT, screen_geometry


def validate(stl_path, *, project_root=None, units=None, placement=None, orientation=None):
    inspection, _ = inspect_stl(stl_path)
    extents = inspection["extents"]
    model = {"units": units, "size_xyz": list(extents),
             "placement": {"units": units, "min_xyz": placement, "orientation": orientation}}
    revision = "sha256:" + inspection["sha256"]
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
    return {"file": str(stl_path), "file_sha256": inspection["sha256"],
            "unit_status": ("declared mm; standalone inspection is not reviewed-model validation" if units=="mm"
                            else "unknown or unsupported units; raw coordinates"),
            "declared_units": units, "geometry_repaired": False,
            "watertight": inspection["watertight"], "bounds_raw_coordinates": extents,
            "volume_raw_coordinates3": inspection["volume"] if inspection["positive_volume"] else None,
            "fits_default_printer_axis_aligned": None, "printer_fit_receipt": receipt,
            "stored_receipt_sha256": receipt_id}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("stl")
    parser.add_argument("--project"); parser.add_argument("--units")
    parser.add_argument("--placement", type=float, nargs=3)
    parser.add_argument("--orientation", choices=("xyz", "xzy", "yxz", "yzx", "zxy", "zyx"))
    args = parser.parse_args()
    print(json.dumps(validate(args.stl, project_root=args.project, units=args.units,
                              placement=args.placement, orientation=args.orientation), indent=2))
