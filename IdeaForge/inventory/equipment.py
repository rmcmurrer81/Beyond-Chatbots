from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path

CONFIG=Path("inventory/config.json")

def _cfg(*, strict=False):
    if strict:
        from fabrication.printer_fit import _read_json
        return _read_json(CONFIG)
    return json.loads(CONFIG.read_text(encoding="utf-8"))

def _local_path():
    return Path(_cfg().get("local_inventory","inventory/equipment.json"))

def _load_file(path, *, strict=False):
    p=Path(path)
    if not p.exists(): return []
    if strict:
        from fabrication.printer_fit import _read_json
        value=_read_json(p)
        if not isinstance(value,dict) or not isinstance(value.get("items"),list) or not all(isinstance(x,dict) for x in value["items"]):
            raise ValueError("Strict inventory file requires object items")
        return value["items"]
    try: return json.loads(p.read_text(encoding="utf-8")).get("items",[])
    except Exception: return []

def load_all(*, photo_ledger=None, project_id=None, include_shared=False, strict_ids=False):
    cfg=_cfg(strict=strict_ids)
    local=_load_file(cfg.get("local_inventory","inventory/equipment.json"),strict=strict_ids)
    combined=list(local); seen={x.get("equipment_id") or x.get("name") for x in local}
    strict_seen=set()
    def check_id(item):
        eid=item.get("equipment_id")
        if strict_ids and eid:
            if eid in strict_seen:
                raise ValueError("Duplicate equipment_id across inventory sources: "+str(eid))
            strict_seen.add(eid)
    for item in local: check_id(item)
    for source in cfg.get("optional_imports",[]):
        for item in _load_file(source,strict=strict_ids):
            check_id(item)
            key=item.get("equipment_id") or item.get("name")
            if key in seen: continue
            copy=dict(item); copy["imported_from"]=source
            combined.append(copy); seen.add(key)
    if photo_ledger is not None:
        from core.photo_inventory import PhotoLedger, PhotoEvidenceError
        if not isinstance(photo_ledger, PhotoLedger) or project_id is None:
            raise PhotoEvidenceError("A reviewed PhotoLedger and explicit project scope are required")
        for item in photo_ledger.inventory_items(project_id=project_id, include_shared=include_shared):
            if item["equipment_id"] in seen:
                raise PhotoEvidenceError("Existing inventory ID conflicts with photo projection")
            combined.append(item)
            seen.add(item["equipment_id"])
    return {"schema_version":"0.2","items":combined}

def load_local():
    p=_local_path()
    if not p.exists(): return {"schema_version":"0.2","items":[]}
    return json.loads(p.read_text(encoding="utf-8"))

def save_local(data):
    p=_local_path(); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

def slug(text):
    return re.sub(r"[^a-z0-9]+","-",text.lower()).strip("-")[:90] or "equipment"

def remember(item):
    data=load_local()
    name=str(item.get("name") or "").strip()
    if not name: return None
    manufacturer=item.get("manufacturer")
    model=item.get("model")
    key=(name+" "+str(manufacturer or "")+" "+str(model or "")).lower()
    for old in data.get("items",[]):
        oldkey=(old.get("name","")+" "+str(old.get("manufacturer") or "")+" "+str(old.get("model") or "")).lower()
        if key==oldkey:
            old.update({k:v for k,v in item.items() if v not in (None,"",[])})
            old["last_updated"]=datetime.now(timezone.utc).isoformat()
            save_local(data); return old
    saved={
      "equipment_id":item.get("equipment_id") or slug(name+"-"+str(len(data.get("items",[]))+1)),
      "name":name,
      "category":item.get("category","other"),
      "manufacturer":manufacturer,
      "model":model,
      "quantity":item.get("quantity",1),
      "ownership_status":item.get("ownership_status","owned"),
      "capabilities":item.get("capabilities",[]),
      "specs":item.get("specs",{}),
      "notes":item.get("notes",""),
      "source":"user_statement",
      "last_updated":datetime.now(timezone.utc).isoformat()
    }
    data.setdefault("items",[]).append(saved); save_local(data); return saved

def find(text):
    q=text.lower(); out=[]
    for item in load_all().get("items",[]):
        hay=" ".join([item.get("name",""),str(item.get("manufacturer") or ""),str(item.get("model") or "")," ".join(item.get("capabilities",[]) or [])]).lower()
        if q in hay: out.append(item)
    return out
