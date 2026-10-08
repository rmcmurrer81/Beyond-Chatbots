from __future__ import annotations
import json, re, shutil
from datetime import datetime, timezone
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError, model_config
from ddgs import DDGS

TEXT_SUFFIXES={".md",".txt",".json",".csv",".log",".py",".scad",".urdf",".yaml",".yml"}

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _read_local(root,max_chars):
    chunks=[]
    priority=[
        "project.json","project_memory.json","README.md",
        "fabrication/prototype_plan.json","fabrication/generation_report.json",
        "simulation/simulation_plan.json","research/RESEARCH_BRIEF.md"
    ]
    seen=set()
    for rel in priority:
        p=Path(root)/rel
        if p.exists() and p.is_file():
            try: text=p.read_text(encoding="utf-8",errors="ignore")
            except Exception: continue
            chunks.append(f"--- {rel} ---\n{text}")
            seen.add(p.resolve())
    for p in Path(root).rglob("*"):
        if sum(len(x) for x in chunks)>=max_chars: break
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES: continue
        try:
            if p.resolve() in seen: continue
            text=p.read_text(encoding="utf-8",errors="ignore")
        except Exception: continue
        chunks.append(f"--- {p.relative_to(root)} ---\n{text[:5000]}")
    return "\n\n".join(chunks)[:max_chars]

@provider_operation
def _build_queries(problem,visual,project,lm):
    prompt=f"""Create up to 5 focused web-search queries for troubleshooting this invention/prototype problem.
Prefer:
- exact visible error codes/messages;
- exact component/model names;
- the specific failure symptom;
- official documentation/service information when relevant;
- known failure modes for the relevant fabrication/electronics/mechanical process.

Return strict JSON: {{"queries":["..."]}}.

PROJECT:
{json.dumps(project,ensure_ascii=False)}

PROBLEM:
{problem}

VISUAL EVIDENCE:
{visual or "none"}"""
    try:
        data=json.loads(text_call([{"role":"user","content":prompt}], task="troubleshooting_queries",
                                  format="json", options={"temperature":0.0}))
        return [str(x).strip() for x in data.get("queries",[]) if str(x).strip()][:5]
    except ProviderError:
        raise
    except Exception:
        name=project.get("name","")
        base=(problem+" "+(visual or "")).strip()
        return [f"{name} {base}".strip()][:1]

def _search(queries,per_query):
    out=[]; seen=set()
    for q in queries:
        try:
            results=DDGS().text(q,max_results=per_query)
        except Exception:
            continue
        for r in results:
            url=r.get("href") or r.get("url")
            if not url or url in seen: continue
            seen.add(url)
            out.append({
                "query":q,
                "title":r.get("title"),
                "url":url,
                "snippet":r.get("body") or r.get("snippet")
            })
    return out

def _incident_dir(root,problem):
    ts=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    slug=re.sub(r"[^a-z0-9]+","-",problem.lower()).strip("-")[:70] or "issue"
    p=Path(root)/"troubleshooting"/f"{ts}-{slug}"
    p.mkdir(parents=True,exist_ok=True)
    return p

@provider_operation
def diagnose(project_root,problem,image_path=None,ai_config="ai/config.json",trouble_config="troubleshooting/config.json"):
    root=Path(project_root)
    project=_load(root/"project.json")
    cfg=_load(trouble_config)
    ai={"vision_model":model_config("vision_model")} if image_path else {}
    lm=model_config()

    visual=None
    if image_path:
        from ai.vision import analyze_image
        visual=analyze_image(image_path,problem,ai)

    local=_read_local(root,int(cfg.get("max_local_chars",30000)))
    queries=_build_queries(problem,visual,project,lm)
    web=_search(queries,int(cfg.get("web_results_per_query",7)))
    web_bundle=json.dumps(web,ensure_ascii=False)[:int(cfg.get("max_web_bundle_chars",32000))]

    prompt=f"""You are IdeaForge's troubleshooting analyst.

Create a practical diagnostic report for the user's current invention/prototype.

Separate clearly:
1. OBSERVED FACTS — only what the user, project files, or image actually establish.
2. LIKELY CAUSES — hypotheses, each with why it fits and confidence (low/medium/high).
3. DIAGNOSTIC CHECKS — ordered from safest/easiest/reversible to more involved.
4. POSSIBLE FIXES — tie each fix to a cause/check; do not claim it will work.
5. STOP CONDITIONS — when to stop testing because further testing could damage hardware or create a hazard.
6. SOURCES — list useful URLs from the search bundle.

Rules:
- Prefer project-specific evidence over generic advice.
- Do not invent dimensions, voltages, ratings, temperatures, tolerances or error codes.
- Do not tell the user a fix succeeded until they report that it did.
- For powered, moving, hot, high-current, pressurized or human-worn systems, recommend low-energy/unpowered checks before energized testing when possible.
- If the evidence is insufficient, say exactly what photo, measurement, log or test would reduce uncertainty.

PROJECT:
{json.dumps(project,ensure_ascii=False)}

USER PROBLEM:
{problem}

IMAGE ANALYSIS:
{visual or "No image supplied."}

LOCAL PROJECT CONTEXT:
{local}

WEB SEARCH RESULTS:
{web_bundle}"""
    report_text=text_call([{"role":"user","content":prompt}], task="troubleshooting_diagnosis",
                          options={"temperature":0.1})
    publication_guard(root)

    incident=_incident_dir(root,problem)
    if image_path:
        src=Path(image_path)
        if src.exists():
            shutil.copy2(src,incident/("evidence"+src.suffix.lower()))
    record={
      "created_at":datetime.now(timezone.utc).isoformat(),
      "problem":problem,
      "image_analysis":visual,
      "search_queries":queries,
      "web_results":web,
      "status":"open",
      "user_outcome":None,
      "tried_actions":[]
    }
    (incident/"incident.json").write_text(json.dumps(record,indent=2,ensure_ascii=False),encoding="utf-8")
    (incident/"REPORT.md").write_text("# IdeaForge Troubleshooting Report\n\n"+report_text,encoding="utf-8")
    active=Path(root)/"troubleshooting"/"ACTIVE.json"
    active.write_text(json.dumps({"incident":str(incident),"status":"open"},indent=2),encoding="utf-8")
    return {
      "incident_dir":str(incident),
      "report":str(incident/"REPORT.md"),
      "report_text":report_text,
      "queries":queries,
      "sources":web,
      "visual":visual
    }

def record_outcome(project_root,text):
    active=Path(project_root)/"troubleshooting"/"ACTIVE.json"
    if not active.exists(): return None
    try:
        ap=json.loads(active.read_text(encoding="utf-8"))
        incident=Path(ap["incident"])
        data=json.loads((incident/"incident.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    data.setdefault("tried_actions",[]).append({
      "time":datetime.now(timezone.utc).isoformat(),
      "user_report":text
    })
    low=text.lower()
    if any(x in low for x in ("that fixed it","it works now","working now","problem is fixed","solved it")):
        data["status"]="resolved"; data["user_outcome"]=text
        ap["status"]="resolved"
    (incident/"incident.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    active.write_text(json.dumps(ap,indent=2),encoding="utf-8")
    return data

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); p.add_argument("problem"); p.add_argument("--image")
    a=p.parse_args()
    print(json.dumps(diagnose(a.project_root,a.problem,a.image),indent=2))
