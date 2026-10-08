from __future__ import annotations
import json, mimetypes
from pathlib import Path
import requests

def build_gallery(project_root,max_images=12):
    root=Path(project_root)
    research=root/"research"
    data=json.loads((research/"research.json").read_text(encoding="utf-8"))
    gallery=[]
    out=research/"gallery"
    out.mkdir(parents=True,exist_ok=True)
    for idx,item in enumerate(data.get("images",[])[:max_images],1):
        url=item.get("thumbnail") or item.get("image_url")
        local=None
        if url:
            try:
                r=requests.get(url,timeout=20,headers={"User-Agent":"IdeaForge/0.3 reference gallery"})
                r.raise_for_status()
                ctype=r.headers.get("Content-Type","image/jpeg").split(";",1)[0]
                ext=mimetypes.guess_extension(ctype) or ".jpg"
                if ext not in {".jpg",".jpeg",".png",".webp",".gif"}:
                    ext=".jpg"
                p=out/f"ref-{idx:02d}{ext}"
                p.write_bytes(r.content)
                local=str(p)
            except Exception:
                local=None
        gallery.append({
          "index":idx,
          "title":item.get("title") or f"Reference {idx}",
          "page_url":item.get("page_url"),
          "image_url":item.get("image_url"),
          "local_file":local
        })
    (research/"gallery.json").write_text(json.dumps({"images":gallery},indent=2,ensure_ascii=False),encoding="utf-8")
    return gallery

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    print(json.dumps(build_gallery(a.project_root),indent=2))
