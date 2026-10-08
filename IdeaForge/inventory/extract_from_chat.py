from __future__ import annotations
import json
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError
from inventory.equipment import remember

TRIGGERS=("i have ","i own ","my 3d printer","my printer is","i bought ","i use ","my headset","my computer","my camera","my tools")

def load_config(path="ai/config.json"):
    return json.loads(Path(path).read_text(encoding="utf-8"))

@provider_operation
def maybe_remember(text,config_path="ai/config.json"):
    if not any(t in text.lower() for t in TRIGGERS):
        return []
    prompt=f"""Extract only equipment that the user explicitly says they own/use/have.
Return strict JSON:
{{"items":[{{"name":"...","category":"3d_printer|computer|gpu|vr|camera|audio|electronics_tool|mechanical_tool|measurement_tool|fabrication_tool|robotics_hardware|other","manufacturer":null,"model":null,"quantity":1,"notes":""}}]}}
Do not infer ownership from wishes or recommendations. Preserve exact model names when stated.

USER:
{text}"""
    try:
        data=json.loads(text_call([{"role":"user","content":prompt}], task="equipment_extract", format="json", options={"temperature":0.0}))
    except ProviderError:
        raise
    except Exception:
        return []
    publication_guard()
    saved=[]
    for item in data.get("items",[]) or []:
        if not item.get("name"): continue
        item["ownership_status"]="owned"
        publication_guard()
        obj=remember(item)
        if obj: saved.append(obj)
    return saved
