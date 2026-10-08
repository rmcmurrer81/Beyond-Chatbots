from __future__ import annotations
import json
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError
from inventory.equipment import load_all

@provider_operation
def plan(project_root,ai_config="ai/config.json",extra_context=""):
    root=Path(project_root)
    project=json.loads((root/"project.json").read_text(encoding="utf-8"))
    memory={}
    mp=root/"project_memory.json"
    if mp.exists():
        memory=json.loads(mp.read_text(encoding="utf-8"))
    research=""
    brief=root/"research"/"RESEARCH_BRIEF.md"
    if brief.exists(): research=brief.read_text(encoding="utf-8",errors="ignore")[:18000]
    prompt=f"""Create a staged virtual simulation plan for this invention.
Return strict JSON:
{{
 "simulations":[
  {{"name":"...","purpose":"...","type":"mesh_fit|rigid_body|kinematics|structural|thermal_power|optical_vr|electronics|human_factors|other","status":"supported_now|needs_geometry|needs_parameters|external_tool","inputs":[],"outputs":[]}}
 ],
 "prototype_order":[],
 "critical_unknowns":[]
}}

Rules:
- Do not pretend one simulator validates everything.
- Use mesh_fit for printable geometry checks.
- Use rigid_body/kinematics only after geometry/joints/mass are defined.
- Mark structural, thermal, optical or other specialist analyses as needing parameters/tools unless the project actually has them.
- For high-energy or human-worn systems, start with low-energy virtual/subsystem tests.
PROJECT:
{json.dumps(project,ensure_ascii=False)}
RESEARCH BRIEF:
{research}
PROJECT MEMORY:
{json.dumps(memory,ensure_ascii=False)[:12000]}
CURRENT REQUEST:
{extra_context}
OWNED EQUIPMENT:
{json.dumps(load_all(),ensure_ascii=False)[:12000]}"""
    data=json.loads(text_call([{"role":"user","content":prompt}], task="simulation_plan", format="json", options={"temperature":0.1}))
    publication_guard(root)
    out=root/"simulation"; out.mkdir(parents=True,exist_ok=True)
    path=out/"simulation_plan.json"; path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    return path,data

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    path,_=plan(a.project_root); print(path)
