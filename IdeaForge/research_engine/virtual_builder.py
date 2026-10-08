from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError

def _load(path,default=None):
    p=Path(path)
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default

@provider_operation
def update_virtual_build(project_root,discoveries=None,ai_config="ai/config.json"):
    root=Path(project_root)
    project=_load(root/"project.json",{}) or {}
    horizon=_load(root/"research"/"technology_horizon.json",{}) or {}
    bundle=_load(root/"research"/"research.json",{}) or {}
    memory=_load(root/"project_memory.json",{}) or {}
    selected=_load(root/"design"/"selected_reference.json",{}) or {}
    existing=_load(root/"design"/"virtual_concepts.json",{}) or {}
    compact={
      "project":project,
      "horizon":horizon,
      "memory":memory,
      "selected_reference":selected,
      "discoveries":discoveries or [],
      "research_web":bundle.get("web",[])[:15],
      "research_papers":bundle.get("papers",[])[:20],
      "existing":existing
    }
    prompt=f"""Update IdeaForge's virtual design concepts for this project.

Return strict JSON:
{{
 "updated_at":"...",
 "current_buildable_concept":{{
   "summary":"...",
   "subsystems":[],
   "prototype_path":[],
   "limitations":[]
 }},
 "experimental_upgrades":[
   {{"name":"...","research_basis":"...","possible_benefit":"...","what_is_missing":"...","validation_needed":"..."}}
 ],
 "speculative_capabilities":[
   {{"capability":"...","status":"not_demonstrated|insufficient_evidence","real_world_analogues":[]}}
 ],
 "next_virtual_tests":[]
}}

Rules:
- Do not claim fictional capabilities exist.
- Keep current buildable technology separate from experimental research and undemonstrated capabilities.
- A discovery may improve an idea, but does not automatically make the design validated.
- Do not invent dimensions or performance figures.
- Preserve useful existing concepts unless new evidence gives a reason to revise them.

CONTEXT:
{json.dumps(compact,ensure_ascii=False)[:48000]}"""
    data=json.loads(text_call([{"role":"user","content":prompt}], task="virtual_build", format="json", options={"temperature":0.12}))
    publication_guard(root)
    data["updated_at"]=datetime.now(timezone.utc).isoformat()
    out=root/"design"; out.mkdir(parents=True,exist_ok=True)
    (out/"virtual_concepts.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    lines=["# IdeaForge Virtual Build","",f"Updated: {data['updated_at']}",""]
    current=data.get("current_buildable_concept") or {}
    lines += ["## What can be built now","",current.get("summary","")]
    if current.get("subsystems"): lines += [""]+[f"- {x}" for x in current["subsystems"]]
    if current.get("prototype_path"):
        lines += ["","### Prototype path",""]+[f"{i+1}. {x}" for i,x in enumerate(current["prototype_path"])]
    if current.get("limitations"):
        lines += ["","### Current limitations",""]+[f"- {x}" for x in current["limitations"]]
    if data.get("experimental_upgrades"):
        lines += ["","## Experimental upgrades",""]
        for x in data["experimental_upgrades"]:
            lines += [f"### {x.get('name','Experimental idea')}","",x.get("possible_benefit",""),f"- Missing: {x.get('what_is_missing','')}",f"- Validation: {x.get('validation_needed','')}",""]
    if data.get("speculative_capabilities"):
        lines += ["## Still speculative / undemonstrated",""]
        for x in data["speculative_capabilities"]:
            lines.append(f"- **{x.get('capability')}** — {x.get('status')} — analogues: {', '.join(x.get('real_world_analogues',[]))}")
    (out/"VIRTUAL_BUILD.md").write_text("\n".join(lines),encoding="utf-8")
    return data

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    print(json.dumps(update_virtual_build(a.project_root),indent=2))
