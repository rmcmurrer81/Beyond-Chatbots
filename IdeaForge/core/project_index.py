from __future__ import annotations
import json
from pathlib import Path
from difflib import SequenceMatcher

ROOT=Path("projects")

def list_projects():
    ROOT.mkdir(parents=True,exist_ok=True)
    out=[]
    for p in ROOT.iterdir():
        if not p.is_dir() or not (p/"project.json").exists():
            continue
        try:
            data=json.loads((p/"project.json").read_text(encoding="utf-8"))
        except Exception:
            data={}
        state={}
        sp=p/"workspace_state.json"
        if sp.exists():
            try: state=json.loads(sp.read_text(encoding="utf-8"))
            except Exception: state={}
        out.append({
            "path":p,
            "name":data.get("name",p.name),
            "modified":(p/"project.json").stat().st_mtime,
            "view_status":state.get("view_status","open"),
            "research_status":state.get("research_status","idle"),
            "research_message":state.get("last_message"),
            "unread_discoveries":int(state.get("unread_discoveries",0) or 0),
            "last_discovery_at":state.get("last_discovery_at"),
            "next_watch_at":state.get("next_watch_at"),
            "research_watch_enabled":state.get("research_watch_enabled",True)
        })
    return sorted(out,key=lambda x:x["modified"],reverse=True)

def latest_project():
    items=[x for x in list_projects() if x.get("view_status","open")=="open"]
    return items[0]["path"] if items else None

def find_project(name):
    needle=str(name or "").strip().lower()
    if not needle:
        return None
    items=list_projects()
    # Folder identity wins over any display name, including a numeric title.
    exact_folder=[x for x in items if x["path"].name.lower()==needle]
    if exact_folder: return exact_folder[0]
    # Unknown eight-digit IDs must never fall back to another project.
    if len(needle)==8 and needle.isascii() and needle.isdecimal(): return None
    exact=[x for x in items if x["name"].lower()==needle]
    if exact: return exact[0]
    contains=[x for x in items if needle in x["name"].lower() or needle in x["path"].name.lower()]
    if contains: return contains[0]
    scored=[]
    for item in items:
        score=max(
            SequenceMatcher(None,needle,item["name"].lower()).ratio(),
            SequenceMatcher(None,needle,item["path"].name.lower()).ratio()
        )
        scored.append((score,item))
    scored.sort(key=lambda x:x[0],reverse=True)
    return scored[0][1] if scored and scored[0][0]>=0.45 else None

def load_recent_history(project_root,limit=6):
    p=Path(project_root)/"conversation.jsonl"
    if not p.exists():
        return []
    rows=[]
    for line in p.read_text(encoding="utf-8",errors="ignore").splitlines()[-limit:]:
        try:
            item=json.loads(line)
        except Exception:
            continue
        if item.get("user"):
            rows.append({"role":"user","content":item["user"]})
        if item.get("assistant"):
            rows.append({"role":"assistant","content":item["assistant"]})
    return rows[-limit*2:]
