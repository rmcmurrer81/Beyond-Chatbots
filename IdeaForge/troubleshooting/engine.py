from __future__ import annotations
import json, re, shutil, uuid
from itertools import islice
from datetime import datetime, timezone
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError, model_config
from ddgs import DDGS

from troubleshooting.context import contained_path, read_json, project_context, local_context
from troubleshooting.incidents import classify_outcome

MAX_RECORD_BYTES = 262144
MAX_PROBLEM_CHARS = 4000


def _load(path):
    # Configuration is an explicit app input, never project provider context.
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("Troubleshooting configuration exceeds its byte budget.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Troubleshooting configuration must be an object.")
    return value


def _read_local(root, max_chars):
    return local_context(root, max_chars)


def _json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False)


def _write_json(root, relative, value):
    encoded=_json_text(value)
    if len(encoded.encode("utf-8"))>MAX_RECORD_BYTES:
        raise ValueError("Incident serialization exceeds its byte budget.")
    path = contained_path(root, relative)
    temporary = contained_path(root, str(relative) + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(encoded.encode("utf-8"))
        # Recheck before publishing. No concurrent hostile path-swap guarantee.
        contained_path(root, relative)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _active_incident(root):
    root = Path(root).resolve(strict=True)
    project = project_context(root)
    active = read_json(root, "troubleshooting/ACTIVE.json", None, MAX_RECORD_BYTES)
    if active is None:
        return None
    if active.get("project_id") not in (None, project["project_id"]):
        raise ValueError("Active incident belongs to another project.")
    if active.get("project_root") not in (None, str(root)):
        raise ValueError("Active incident is bound to another project location.")
    target = Path(active.get("incident", ""))
    # Accept contained absolute legacy pointers only, then migrate to relative.
    if target.is_absolute():
        try:
            target = target.relative_to(root)
        except ValueError:
            raise ValueError("Active incident is outside the selected project.")
    if len(target.parts) != 2 or target.parts[0] != "troubleshooting":
        raise ValueError("Invalid active incident path.")
    incident = contained_path(root, target)
    data = read_json(root, target / "incident.json", None, MAX_RECORD_BYTES)
    if data is None:
        raise ValueError("Active incident record is missing.")
    if data.get("project_id") not in (None, project["project_id"]):
        raise ValueError("Incident record belongs to another project.")
    if data.get("project_root") not in (None, str(root)):
        raise ValueError("Incident record is bound to another project location.")
    return incident, data, active, project


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
        return [x.strip()[:300] for x in data.get("queries",[])[:5]
                if isinstance(x,str) and x.strip()]
    except ProviderError:
        raise
    except Exception:
        name=project.get("name","")
        base=(problem+" "+(visual or "")).strip()
        return [f"{name} {base}".strip()][:1]

def _search(queries,per_query):
    out=[]; seen=set()
    if per_query <= 0:
        return out
    for q in queries[:5]:
        try:
            results=DDGS().text(q,max_results=per_query)
        except Exception:
            continue
        for r in islice(results,per_query):
            url=r.get("href") or r.get("url")
            if not url or url in seen: continue
            seen.add(url)
            out.append({
                "query":q[:300],
                "title":str(r.get("title") or "")[:300],
                "url":str(url)[:2048],
                "snippet":str(r.get("body") or r.get("snippet") or "")[:1500]
            })
    return out

def _incident_dir(root,problem):
    ts=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    slug=re.sub(r"[^a-z0-9]+","-",problem.lower()).strip("-")[:70] or "issue"
    store=contained_path(root,"troubleshooting")
    store.mkdir(exist_ok=True)
    p=contained_path(root,Path("troubleshooting")/f"{ts}-{slug}-{uuid.uuid4().hex[:12]}")
    p.mkdir()
    return p

@provider_operation
def diagnose(project_root,problem,image_path=None,ai_config="ai/config.json",trouble_config="troubleshooting/config.json",continue_active=False):
    root=Path(project_root).resolve(strict=True)
    if not isinstance(problem,str) or len(problem)>MAX_PROBLEM_CHARS or len(problem.encode("utf-8"))>8000:
        raise ValueError("Troubleshooting problem exceeds its character budget.")
    project=project_context(root)
    contained_path(root,"troubleshooting")
    existing = _active_incident(root) if continue_active else None
    cfg=_load(trouble_config)
    ai={"vision_model":model_config("vision_model")} if image_path else {}
    lm=model_config()

    visual=None
    if image_path:
        from ai.vision import analyze_image
        visual=str(analyze_image(image_path,problem,ai)).encode("utf-8")[:6000].decode("utf-8","ignore")

    local=_read_local(root,int(cfg.get("max_local_chars",30000)))
    queries=_build_queries(problem,visual,project,lm)
    web=_search(queries,max(0,min(int(cfg.get("web_results_per_query",7)),7)))
    web_budget=max(0,min(int(cfg.get("max_web_bundle_chars",8000)),8000))
    web_bundle=json.dumps(web,ensure_ascii=False).encode("utf-8")[:web_budget].decode("utf-8","ignore")

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

    if existing:
        current=_active_incident(root)
        if current is None or current[0] != existing[0]:
            raise ValueError("Active incident changed; diagnostic publication discarded.")
        existing=current
    incident = existing[0] if existing else _incident_dir(root,problem)
    now = datetime.now(timezone.utc).isoformat()
    if existing:
        record = existing[1]
        # REPORT.md is the original report and is never overwritten.
        report_name = "REPORT-" + uuid.uuid4().hex + ".md"
        record.setdefault("reports", [{"path":"REPORT.md","created_at":record.get("created_at")}])
    else:
        report_name = "REPORT.md"
        record = {
            "created_at":now, "problem":problem, "status":"open",
            "user_outcome":None, "tried_actions":[], "outcome_history":[],
            "reports":[]
        }
    record.update(project_id=project["project_id"], project_root=str(root),
                  latest_problem=problem, image_analysis=visual,
                  search_queries=queries, web_results=web)
    if image_path:
        src=Path(image_path)
        if src.is_file():
            # Explicit attachment only; never discovers project photo stores.
            destination=contained_path(root,incident.relative_to(root)/("evidence-"+uuid.uuid4().hex+src.suffix.lower()))
            shutil.copy2(src,destination)
    report=contained_path(root,incident.relative_to(root)/report_name)
    record["reports"].append({"path":report_name,"created_at":now})
    if len(_json_text(record).encode("utf-8"))>MAX_RECORD_BYTES:
        raise ValueError("Incident record exceeds its byte budget; prior reports are preserved.")
    report.write_text("# IdeaForge Troubleshooting Report\n\n"+report_text,encoding="utf-8")
    _write_json(root,incident.relative_to(root)/"incident.json",record)
    _write_json(root,"troubleshooting/ACTIVE.json",{
        "incident":str(incident.relative_to(root)), "status":record["status"],
        "project_id":project["project_id"], "project_root":str(root)
    })
    return {
      "incident_dir":str(incident),
      "report":str(report),
      "report_text":report_text,
      "queries":queries,
      "sources":web,
      "visual":visual
    }

def record_outcome(project_root,text):
    """Persist a user report; failure reopens resolved incidents without erasure."""
    root=Path(project_root).resolve(strict=True)
    if not isinstance(text,str) or len(text)>MAX_PROBLEM_CHARS:
        raise ValueError("Troubleshooting outcome exceeds its character budget.")
    existing=_active_incident(root)
    if existing is None:
        return None
    incident,data,active,project=existing
    previous=data.get("status","open")
    if previous not in ("open","resolved"):
        raise ValueError("Unsupported incident state.")
    classification=classify_outcome(text)
    current=("resolved" if classification=="resolved" else
             "open" if classification in ("failed","reopen") else previous)
    now=datetime.now(timezone.utc).isoformat()
    history=data.setdefault("outcome_history",[])
    # Preserve an old resolution when migrating records from the old format.
    if not history and data.get("user_outcome"):
        history.append({"time":None,"user_report":data["user_outcome"],
                        "classification":"legacy_resolution",
                        "from_status":None,"to_status":previous})
    history.append({"time":now,"user_report":text,"classification":classification,
                    "from_status":previous,"to_status":current})
    data.setdefault("tried_actions",[]).append({"time":now,"user_report":text})
    if classification=="resolved":
        data["user_outcome"]=text
    elif classification in ("failed","reopen"):
        data["user_outcome"]=None
    data.update(status=current, project_id=project["project_id"],project_root=str(root))
    active.update(incident=str(incident.relative_to(root)),status=current,
                  project_id=project["project_id"],project_root=str(root))
    if len(_json_text(data).encode("utf-8"))>MAX_RECORD_BYTES:
        raise ValueError("Incident history exceeds its byte budget; report was not discarded.")
    _write_json(root,incident.relative_to(root)/"incident.json",data)
    _write_json(root,"troubleshooting/ACTIVE.json",active)
    return data

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); p.add_argument("problem"); p.add_argument("--image")
    a=p.parse_args()
    print(json.dumps(diagnose(a.project_root,a.problem,a.image),indent=2))
