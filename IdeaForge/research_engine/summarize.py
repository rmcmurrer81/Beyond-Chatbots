from __future__ import annotations
import json
from pathlib import Path
import requests
from ai.provider import provider_operation, text_call, publication_guard, ProviderError

@provider_operation
def summarize(project_root,ai_config="ai/config.json"):
    root=Path(project_root)
    project=json.loads((root/"project.json").read_text(encoding="utf-8"))
    bundle=json.loads((root/"research"/"research.json").read_text(encoding="utf-8"))
    compact={
      "project":project,
      "web":bundle.get("web",[])[:30],
      "papers":bundle.get("papers",[])[:35],
      "labs":bundle.get("labs",[])[:25]
    }
    prompt=f"""You are IdeaForge's engineering research analyst.
Create a source-grounded research brief for this invention project.
Separate:
1. technology that exists and can be bought/built today,
2. experimental university/lab research,
3. capabilities not yet demonstrated in a practical form,
4. promising prototype paths,
5. research groups/institutions worth monitoring,
6. major engineering unknowns.

Do not invent performance figures. Mention source URLs inline where useful.
PROJECT BUNDLE:
{json.dumps(compact,ensure_ascii=False)[:45000]}"""
    text=text_call([{"role":"user","content":prompt}], task="research_summary", options={"temperature":0.15})
    publication_guard(root)
    out=root/"research"/"RESEARCH_BRIEF.md"; out.write_text("# IdeaForge Research Brief\n\n"+text,encoding="utf-8")
    return out

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    print(summarize(a.project_root))
