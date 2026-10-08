from __future__ import annotations
import json, re, secrets
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path("projects")

def slugify(text):
    s=re.sub(r"[^a-z0-9]+","-",text.lower()).strip("-")
    return s[:80] or "new-project"

def create_project(name,idea,plan):
    project_name=name
    ROOT.mkdir(parents=True,exist_ok=True)
    # Reserve before writing. A random ID collision never reuses an old folder.
    for _ in range(100):
        project_id=str(10000000+secrets.randbelow(90000000))
        root=ROOT/project_id
        try:
            root.mkdir()
        except FileExistsError:
            continue
        break
    else:
        raise FileExistsError("Could not reserve an unused project ID.")
    for folder_name in ("research","fabrication","simulation","procurement","design","troubleshooting"):
        (root/folder_name).mkdir(exist_ok=True)
    data={
      "schema_version":"0.1",
      "project_id":project_id,
      "name":project_name,
      "original_idea":idea,
      "created_at":datetime.now(timezone.utc).isoformat(),
      "status":"concept",
      "plan":plan
    }
    (root/"project.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    lines=[
      f"# {project_name}","",
      "## Original idea","",idea,"",
      "## Engineering interpretation","",
      plan.get("summary",""),"",
      "## Intended capabilities",""
    ]
    lines += [f"- {x}" for x in plan.get("capabilities",[])]
    lines += ["","## Subsystems",""]+[f"- {x}" for x in plan.get("subsystems",[])]
    lines += ["","## Research questions",""]+[f"- {x}" for x in plan.get("research_questions",[])]
    lines += ["","## Current feasibility / unknowns",""]+[f"- {x}" for x in plan.get("unknowns",[])]
    (root/"README.md").write_text("\n".join(lines),encoding="utf-8")
    return root

def append_conversation(project_root,user,assistant):
    now=datetime.now(timezone.utc).isoformat()
    root=Path(project_root)
    p=root/"conversation.jsonl"
    with p.open("a",encoding="utf-8") as f:
        f.write(json.dumps({
          "time":now,
          "user":user,
          "assistant":assistant
        },ensure_ascii=False)+"\n")
    project_file=root/"project.json"
    if project_file.exists():
        try:
            data=json.loads(project_file.read_text(encoding="utf-8"))
            data["last_updated"]=now
            project_file.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
        except Exception:
            pass
