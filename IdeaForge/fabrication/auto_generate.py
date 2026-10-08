from __future__ import annotations
import json
from pathlib import Path
from fabrication.enclosure import generate as generate_enclosure

REQUIRED_ENCLOSURE=("inner_x_mm","inner_y_mm","inner_z_mm","wall_mm")

def run(project_root):
    root=Path(project_root)
    plan_path=root/"fabrication"/"prototype_plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(plan_path)
    plan=json.loads(plan_path.read_text(encoding="utf-8"))
    results=[]
    out_root=root/"fabrication"/"generated"
    out_root.mkdir(parents=True,exist_ok=True)
    for idx,part in enumerate(plan.get("printable_parts",[]) or [],1):
        generator=part.get("generator")
        dims=part.get("dimensions") or {}
        status=part.get("dimensions_status")
        if generator=="enclosure" and status=="known" and all(k in dims for k in REQUIRED_ENCLOSURE):
            spec={
              "name":part.get("name",f"enclosure-{idx}"),
              "inner_x_mm":dims["inner_x_mm"],
              "inner_y_mm":dims["inner_y_mm"],
              "inner_z_mm":dims["inner_z_mm"],
              "wall_mm":dims["wall_mm"],
              "lid_thickness_mm":dims.get("lid_thickness_mm",dims["wall_mm"]),
              "clearance_mm":dims.get("clearance_mm",0.3),
              "notes":part.get("material_notes","")
            }
            spec_path=out_root/f"enclosure-{idx}.json"
            spec_path.write_text(json.dumps(spec,indent=2),encoding="utf-8")
            receipt=generate_enclosure(spec_path,out_root/f"enclosure-{idx}")
            results.append({"part":part.get("name"),"status":"generated","receipt":receipt})
        else:
            results.append({"part":part.get("name"),"status":"not_generated","reason":"unsupported generator or dimensions still TBD"})
    report=root/"fabrication"/"generation_report.json"
    report.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf-8")
    return results

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    print(json.dumps(run(a.project_root),indent=2))
