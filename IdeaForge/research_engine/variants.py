from __future__ import annotations
import json
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

@provider_operation
def analyze_variants(project_root,ai_config="ai/config.json"):
    root=Path(project_root)
    gallery_path=root/"research"/"gallery.json"
    if not gallery_path.exists():
        return None
    gallery=_load(gallery_path).get("images",[])
    if len(gallery)<2:
        return None
    project=_load(root/"project.json")
    compact=[{"index":x.get("index"),"title":x.get("title"),"page_url":x.get("page_url")} for x in gallery]
    prompt=f"""This is an IdeaForge reference-selection task.
The user is building or recreating a specific fictional/visual design or object.
Using only project context and image-result titles/page URLs, identify whether there appear to be meaningfully different visual/design variants.

Return strict JSON:
{{
 "selection_needed": true,
 "target":"...",
 "variants":[
   {{"variant_id":"variant-1","label":"...","description":"...","image_indexes":[1,2]}}
 ],
 "question":"..."
}}

Rules:
- Do not claim two images are different variants unless the metadata supports it.
- If there is not enough evidence, return selection_needed false and one generic variant.
- Keep variant labels descriptive rather than pretending exact canon/version identification is certain.

PROJECT:
{json.dumps(project,ensure_ascii=False)}

REFERENCE METADATA:
{json.dumps(compact,ensure_ascii=False)}"""
    try:
        data=json.loads(text_call([{"role":"user","content":prompt}], task="reference_variants", format="json", options={"temperature":0.1}))
    except ProviderError:
        raise
    except Exception:
        return None
    publication_guard(root)
    out=root/"research"/"reference_variants.json"
    out.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    return data

def select_variant(project_root,variant_id=None,image_index=None):
    root=Path(project_root)
    variants_path=root/"research"/"reference_variants.json"
    gallery_path=root/"research"/"gallery.json"
    data=_load(variants_path) if variants_path.exists() else {"variants":[]}
    gallery=_load(gallery_path).get("images",[]) if gallery_path.exists() else []
    selection={"variant_id":variant_id,"image_index":image_index}
    if variant_id:
        selected=next((x for x in data.get("variants",[]) if x.get("variant_id")==variant_id),None)
        selection["variant"]=selected
    if image_index is not None:
        selection["image"]=next((x for x in gallery if int(x.get("index",0))==int(image_index)),None)
    (root/"design"/"selected_reference.json").write_text(json.dumps(selection,indent=2,ensure_ascii=False),encoding="utf-8")
    return selection
