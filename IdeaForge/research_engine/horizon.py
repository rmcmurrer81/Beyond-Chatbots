from __future__ import annotations
import json
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def matching_profiles(project,profiles_path="research_engine/inspiration_profiles.json"):
    try:
        data=_load(profiles_path)
    except ProviderError:
        raise
    except Exception:
        return []
    text=(str(project.get("name",""))+" "+str(project.get("original_idea",""))+" "+json.dumps(project.get("plan",{}),ensure_ascii=False)).lower()
    matches=[]
    for profile in data.get("profiles",[]):
        if any(str(term).lower() in text for term in profile.get("match_terms",[])):
            matches.append(profile)
    return matches

@provider_operation
def expand_topics(project_root,ai_config="ai/config.json"):
    root=Path(project_root)
    project=_load(root/"project.json")
    profiles=matching_profiles(project)
    memory={}
    mp=root/"project_memory.json"
    if mp.exists():
        memory=_load(mp)
    from workspace3d.research_context import requirements_context
    workspace_requirements = requirements_context(root)
    prompt=f"""You are IdeaForge's technology-horizon planner.

Generate search topics for technologies that could help realize this invention, including:
- technologies that can be built/bought now,
- active university/lab research,
- experimental enabling technologies,
- real-world analogues of fictional capabilities.

If the user uses a fictional term such as "hard light", do NOT claim that the fictional technology exists. Translate it into real research directions that could approximate the desired capability (for example tactile/haptic displays, acoustic/ultrasonic haptics, volumetric/light-field display techniques, optical trapping, plasma/voxel display research, or other relevant real approaches if applicable).

Return strict JSON:
{{
 "goal":"...",
 "buildable_now_topics":[],
 "experimental_topics":[],
 "speculative_or_missing_capabilities":[],
 "watch_queries":[]
}}

Keep watch_queries concise and useful for web/scholarly search. Do not invent performance figures.

PROJECT:
{json.dumps(project,ensure_ascii=False)}

MATCHED INSPIRATION PROFILES:
{json.dumps(profiles,ensure_ascii=False)}

PROJECT MEMORY:
{json.dumps(memory,ensure_ascii=False)[:12000]}

USER WORKSPACE REQUIREMENTS (goals and open questions, not evidence of feasibility):
{workspace_requirements}"""
    data=json.loads(text_call([{"role":"user","content":prompt}], task="research_horizon", format="json", options={"temperature":0.1}))

    # Make matched profile seeds deterministic so a watch cannot lose important enabling technologies.
    watch=list(data.get("watch_queries",[]) or [])
    speculative=list(data.get("speculative_or_missing_capabilities",[]) or [])
    for profile in profiles:
        for topic in profile.get("seed_topics",[]) or []:
            if topic not in watch:
                watch.append(topic)
        for alias in profile.get("fictional_capability_aliases",[]) or []:
            entry={
              "capability":alias.get("term"),
              "status":alias.get("status","undemonstrated"),
              "real_world_analogues":alias.get("real_world_analogues",[])
            }
            if not any(str(x).lower().find(str(alias.get("term","")).lower())>=0 for x in speculative):
                speculative.append(entry)
    data["watch_queries"]=watch
    data["speculative_or_missing_capabilities"]=speculative

    publication_guard(root)
    out=root/"research"/"technology_horizon.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    return data

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    print(json.dumps(expand_topics(a.project_root),indent=2))
