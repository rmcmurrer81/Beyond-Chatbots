from __future__ import annotations
import json
from pathlib import Path
import trimesh
from fabrication.printer import default_printer, build_volume

def run(mesh_path):
    mesh=trimesh.load_mesh(mesh_path)
    ext=[float(x) for x in mesh.extents]
    printer=default_printer(); volume=build_volume(printer)
    fits=None if not volume else all(ext[i]<=volume[i] for i in range(3))
    return {
      "test":"mesh_fit",
      "mesh":str(mesh_path),
      "watertight":bool(getattr(mesh,"is_watertight",False)),
      "extents_mm":ext,
      "printer":(printer or {}).get("name"),
      "printer_model":(printer or {}).get("model"),
      "printer_build_volume_mm":volume,
      "axis_aligned_fit":fits
    }

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("mesh"); a=p.parse_args()
    print(json.dumps(run(a.mesh),indent=2))
