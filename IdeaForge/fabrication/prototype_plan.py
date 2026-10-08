from __future__ import annotations
import json
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError
from inventory.equipment import load_all

SUPPORTED=["enclosure","plate","bracket","spacer","simple_housing"]

@provider_operation
def plan(project_root,ai_config="ai/config.json",extra_context=""):
    root=Path(project_root)
    project=json.loads((root/"project.json").read_text(encoding="utf-8"))
    equipment=load_all()
    memory={}
    mp=root/"project_memory.json"
    if mp.exists():
        memory=json.loads(mp.read_text(encoding="utf-8"))
    selected_reference={}
    sr=root/"design"/"selected_reference.json"
    if sr.exists():
        selected_reference=json.loads(sr.read_text(encoding="utf-8"))
    recent=[]
    cp=root/"conversation.jsonl"
    if cp.exists():
        for line in cp.read_text(encoding="utf-8",errors="ignore").splitlines()[-12:]:
            try: recent.append(json.loads(line))
            except Exception: pass
    prompt=f"""Create a practical prototype plan for this IdeaForge project.
Return strict JSON:
{{
 "prototype_goal":"...",
 "prototype_level":"appearance|fit|functional_subsystem|integrated",
 "printable_parts":[
   {{"name":"...","purpose":"...","generator":"enclosure|plate|bracket|spacer|simple_housing|custom_cad","dimensions":{{}},"dimensions_status":"known|tbd","material_notes":"..."}}
 ],
 "off_the_shelf_parts":[],
 "tests":[],
 "unknowns":[]
}}

Rules:
- Prefer inexpensive, low-energy prototypes before full-scale builds.
- Only mark dimensions known when the project contains actual dimensions.
- Do not invent dimensions.
- Use 'custom_cad' for shapes outside the supported simple generators.
- Consider equipment the user already owns.
PROJECT:
{json.dumps(project,ensure_ascii=False)}
PROJECT MEMORY:
{json.dumps(memory,ensure_ascii=False)[:12000]}
SELECTED VISUAL REFERENCE:
{json.dumps(selected_reference,ensure_ascii=False)[:10000]}
RECENT CONVERSATION:
{json.dumps(recent,ensure_ascii=False)[:12000]}
CURRENT REQUEST:
{extra_context}
OWNED EQUIPMENT:
{json.dumps(equipment,ensure_ascii=False)[:16000]}"""
    data=json.loads(text_call([{"role":"user","content":prompt}], task="prototype_plan", format="json", options={"temperature":0.1}))
    publication_guard(root)
    out=root/"fabrication"; out.mkdir(parents=True,exist_ok=True)
    p=out/"prototype_plan.json"; p.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    return p,data

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    path,_=plan(a.project_root); print(path)
