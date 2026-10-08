from __future__ import annotations
import json, time
from pathlib import Path
from urllib.parse import quote_plus
import feedparser, requests
from ddgs import DDGS

ARXIV="https://export.arxiv.org/api/query"
OPENALEX="https://api.openalex.org/works"

def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _queries(project,max_queries=6,memory=None,horizon=None):
    plan=project.get("plan",{})
    base=project.get("name") or project.get("original_idea","")
    visual=plan.get("visual_reference_target")
    q=[base]
    if visual:
        q += [
            str(visual),
            f"{visual} reference front side back details",
            f"{visual} build replica dimensions appearance"
        ]
    if horizon:
        for query in horizon.get("watch_queries",[])[:8]:
            if query:
                q.append(str(query))
    q += [f"{base} {x}" for x in plan.get("subsystems",[])[:3]]
    q += [str(x) for x in plan.get("research_questions",[])[:3]]
    if memory:
        for fact in memory.get("facts",[])[:6]:
            statement=str(fact.get("statement") or "").strip()
            if statement:
                q.append(f"{base} {statement}")
    seen=[]; out=[]
    for x in q:
        x=" ".join(str(x).split())
        if x and x.lower() not in seen:
            out.append(x); seen.append(x.lower())
        if len(out)>=max_queries: break
    return out

def web_search(query,limit):
    out=[]
    try:
        for r in DDGS().text(query,max_results=limit):
            out.append({"title":r.get("title"),"url":r.get("href") or r.get("url"),"snippet":r.get("body") or r.get("snippet"),"source":"web"})
    except Exception:
        pass
    return out

def image_search(query,limit):
    out=[]
    try:
        for r in DDGS().images(query,max_results=limit):
            out.append({"title":r.get("title"),"image_url":r.get("image"),"page_url":r.get("url"),"thumbnail":r.get("thumbnail"),"source":"image_search"})
    except Exception:
        pass
    return out

def openalex_search(query,limit,user_agent):
    out=[]
    try:
        r=requests.get(OPENALEX,params={"search":query,"per-page":limit,"sort":"publication_date:desc"},headers={"User-Agent":user_agent},timeout=35)
        r.raise_for_status()
        for w in r.json().get("results",[]):
            institutions=[]
            for a in w.get("authorships",[]) or []:
                for i in a.get("institutions",[]) or []:
                    name=i.get("display_name")
                    if name and name not in institutions: institutions.append(name)
            loc=w.get("primary_location") or {}
            out.append({
                "title":w.get("display_name"),
                "date":w.get("publication_date"),
                "doi":w.get("doi"),
                "url":loc.get("landing_page_url") or w.get("doi") or w.get("id"),
                "institutions":institutions,
                "cited_by_count":w.get("cited_by_count"),
                "source":"openalex"
            })
    except Exception:
        pass
    return out

def arxiv_search(query,limit,user_agent):
    out=[]
    try:
        r=requests.get(ARXIV,params={"search_query":f"all:{query}","start":0,"max_results":limit,"sortBy":"submittedDate","sortOrder":"descending"},
                       headers={"User-Agent":user_agent},timeout=40)
        r.raise_for_status()
        feed=feedparser.parse(r.content)
        for e in feed.entries:
            out.append({
                "title":" ".join(getattr(e,"title","").split()),
                "url":getattr(e,"id",""),
                "published":getattr(e,"published",None),
                "summary":" ".join(getattr(e,"summary","").split()),
                "authors":[getattr(a,"name","") for a in getattr(e,"authors",[])],
                "source":"arxiv"
            })
        time.sleep(3.1)
    except Exception:
        pass
    return out

def research_project(project_root,config_path="research_engine/config.json",max_queries_override=None):
    root=Path(project_root)
    project=_load(root/"project.json"); cfg=_load(config_path)
    memory={}
    mp=root/"project_memory.json"
    if mp.exists():
        memory=_load(mp)
    horizon={}
    hp=root/"research"/"technology_horizon.json"
    if hp.exists():
        try: horizon=_load(hp)
        except Exception: horizon={}
    queries=_queries(project,int(max_queries_override if max_queries_override is not None else cfg.get("max_queries",6)),memory,horizon)
    web=[]; images=[]; papers=[]; labs={}
    for q in queries:
        if cfg["sources"].get("web",True):
            web += [dict(r,_query=q) for r in web_search(q,int(cfg.get("web_results_per_query",8)))]
            web += [dict(r,_query=q) for r in web_search(q+" university lab research",max(3,int(cfg.get("web_results_per_query",8))//2))]
        if cfg["sources"].get("images",True):
            images += [dict(r,_query=q) for r in image_search(q,int(cfg.get("image_results_per_query",6)))]
        if cfg["sources"].get("openalex",True):
            oa=openalex_search(q,int(cfg.get("openalex_results_per_query",8)),cfg.get("user_agent","IdeaForge/0.2"))
            papers += [dict(r,_query=q) for r in oa]
            for p in oa:
                for inst in p.get("institutions",[]):
                    labs.setdefault(inst,[]).append({"title":p.get("title"),"url":p.get("url"),"date":p.get("date")})
        if cfg["sources"].get("arxiv",True):
            papers += [dict(r,_query=q) for r in arxiv_search(q,int(cfg.get("arxiv_results_per_query",8)),cfg.get("user_agent","IdeaForge/0.2"))]
    research=root/"research"; research.mkdir(parents=True,exist_ok=True)
    bundle={"queries":queries,"web":web,"papers":papers,"labs":[{"institution":k,"works":v} for k,v in labs.items()],"images":images}
    (research/"research.json").write_text(json.dumps(bundle,indent=2,ensure_ascii=False),encoding="utf-8")
    return bundle

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    x=research_project(a.project_root)
    print(json.dumps({"queries":len(x["queries"]),"web":len(x["web"]),"papers":len(x["papers"]),"labs":len(x["labs"]),"images":len(x["images"])},indent=2))
