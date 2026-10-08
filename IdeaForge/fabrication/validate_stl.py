from __future__ import annotations
import json
from pathlib import Path
from engineering_pilot.mesh_verify import inspect_stl
from fabrication.printer import default_printer, build_volume

def validate(stl_path):
    inspection,_=inspect_stl(stl_path)
    ext=inspection['extents']
    printer=default_printer(); volume=build_volume(printer)
    fits=None
    if volume:
        fits=all(ext[i] <= volume[i] for i in range(3))
    return {
      "file":str(stl_path),
      "file_sha256":inspection["sha256"],
      "unit_status":"coordinates assumed mm; standalone inspection is not reviewed-model validation",
      "geometry_repaired":False,
      "watertight":inspection['watertight'],
      "bounds_mm":ext,
      "volume_mm3":inspection['volume'] if inspection['positive_volume'] else None,
      "printer":printer.get("name") if printer else None,
      "printer_model":printer.get("model") if printer else None,
      "printer_build_volume_mm":volume,
      "fits_default_printer_axis_aligned":fits
    }

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("stl"); a=p.parse_args()
    print(json.dumps(validate(a.stl),indent=2))
