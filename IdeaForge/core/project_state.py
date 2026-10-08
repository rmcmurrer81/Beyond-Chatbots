from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

DEFAULTS={
  "view_status":"open",
  "research_status":"idle",
  "last_message":None,
  "last_updated":None,
  "research_watch_enabled":True,
  "last_watch_at":None,
  "next_watch_at":None,
  "unread_discoveries":0,
  "last_discovery_at":None
}

def _path(project_root):
    return Path(project_root)/"workspace_state.json"

def load(project_root):
    p=_path(project_root)
    if not p.exists():
        return dict(DEFAULTS)
    try:
        data=json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data={}
    out=dict(DEFAULTS); out.update(data); return out

def update(project_root,**changes):
    data=load(project_root)
    data.update(changes)
    data["last_updated"]=datetime.now(timezone.utc).isoformat()
    p=_path(project_root)
    p.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return data

def set_view(project_root,status):
    return update(project_root,view_status=status)

def set_research(project_root,status,message=None):
    return update(project_root,research_status=status,last_message=message)

def set_watch_enabled(project_root,enabled):
    return update(project_root,research_watch_enabled=bool(enabled))

def schedule_next_watch(project_root,interval_minutes):
    now=datetime.now(timezone.utc)
    return update(
      project_root,
      last_watch_at=now.isoformat(),
      next_watch_at=(now+timedelta(minutes=float(interval_minutes))).isoformat()
    )

def mark_discoveries(project_root,count):
    data=load(project_root)
    return update(
      project_root,
      unread_discoveries=int(data.get("unread_discoveries",0) or 0)+int(count),
      last_discovery_at=datetime.now(timezone.utc).isoformat()
    )

def clear_discoveries(project_root):
    return update(project_root,unread_discoveries=0)
