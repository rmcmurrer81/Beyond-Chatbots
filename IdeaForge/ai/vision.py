from __future__ import annotations
import base64
import time
from pathlib import Path
import requests
from ai.provider import operation, vision_guard, model_config, current_operation

SUPPORTED={".png",".jpg",".jpeg",".webp"}

def analyze_image(image_path,prompt,cfg):
    if current_operation() is None:
        with operation():
            return analyze_image(image_path,prompt,cfg)
    vision_guard()
    path=Path(image_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in SUPPORTED:
        raise ValueError("Supported troubleshooting images: PNG, JPG/JPEG, WEBP")
    v=model_config("vision_model")
    data=base64.b64encode(path.read_bytes()).decode("ascii")
    system="""You are IdeaForge's visual troubleshooting stage.
Describe only what is visibly present in the supplied image.
Carefully transcribe visible error messages, codes, labels, measurements, part IDs, damaged areas, misalignment, print defects, wiring labels, connector markings, UI state and warning indicators when legible.
Distinguish observation from interpretation.
Do not invent hidden damage, dimensions, voltages, causes or fixes.
Your output will be used to search the user's project files and external sources."""
    user=f"""User problem:
{prompt}

Inspect the image for evidence relevant to diagnosing the problem. Focus on exact visible details that can be searched or matched against project records."""
    r=requests.post(v["base_url"].rstrip("/")+"/api/chat",json={
        "model":v["model"],"stream":False,
        "messages":[{"role":"system","content":system},{"role":"user","content":user,"images":[data]}],
        "options":{"temperature":v.get("temperature",0.1)}
    },timeout=min(v.get("timeout_seconds",180),current_operation().deadline-time.time()))
    r.raise_for_status()
    vision_guard()
    return r.json()["message"]["content"]
