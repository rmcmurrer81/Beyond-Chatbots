from __future__ import annotations
import json
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError
from bs4 import BeautifulSoup
from ddgs import DDGS
from inventory.equipment import load_local, save_local

def _page_text(url,max_chars=12000):
    try:
        r=requests.get(url,timeout=25,headers={"User-Agent":"IdeaForge/0.2 equipment researcher"})
        r.raise_for_status()
        soup=BeautifulSoup(r.text,"html.parser")
        for t in soup(["script","style","noscript"]): t.decompose()
        text=" ".join(soup.stripped_strings)
        return text[:max_chars]
    except ProviderError:
        raise
    except Exception:
        return ""

@provider_operation
def enrich_equipment(equipment_id,ai_config="ai/config.json"):
    data=load_local()
    item=next((x for x in data.get("items",[]) if x.get("equipment_id")==equipment_id),None)
    if not item: raise KeyError(equipment_id)
    query=" ".join(x for x in [item.get("manufacturer"),item.get("model"),item.get("name"),"official specifications"] if x)
    results=list(DDGS().text(query,max_results=8))
    docs=[]
    for r in results:
        url=r.get("href") or r.get("url")
        if not url: continue
        docs.append({"title":r.get("title"),"url":url,"snippet":r.get("body") or r.get("snippet"),"page":_page_text(url,8000)})
    prompt=f"""Extract conservative equipment specifications from the web-source bundle below.
The equipment is: {json.dumps(item,ensure_ascii=False)}
Return strict JSON with:
{{
 "specs":{{}},
 "capabilities":[],
 "source_urls":[],
 "notes":""
}}
For a 3D printer, useful fields include build_x_mm, build_y_mm, build_z_mm, nozzle_mm, supported_materials, heated_bed, enclosed.
Only include a field if a supplied source supports it. Do not guess.
SOURCES:
{json.dumps(docs,ensure_ascii=False)[:28000]}"""
    parsed=json.loads(text_call([{"role":"user","content":prompt}], task="equipment_enrich", format="json", options={"temperature":0.0}))
    publication_guard()
    item["specs"].update(parsed.get("specs") or {})
    item["capabilities"]=sorted(set((item.get("capabilities") or [])+(parsed.get("capabilities") or [])))
    item["research_sources"]=parsed.get("source_urls") or []
    if parsed.get("notes"): item["notes"]=(item.get("notes","")+" "+parsed["notes"]).strip()
    save_local(data)
    return item

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("equipment_id"); a=p.parse_args()
    print(json.dumps(enrich_equipment(a.equipment_id),indent=2))
