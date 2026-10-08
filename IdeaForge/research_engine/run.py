from ai.provider import provider_operation
from research_engine.research_project import research_project
from research_engine.summarize import summarize

@provider_operation
def run(project_root):
    bundle=research_project(project_root)
    brief=summarize(project_root)
    return bundle,brief

if __name__=="__main__":
    import argparse, json
    p=argparse.ArgumentParser(); p.add_argument("project_root"); a=p.parse_args()
    bundle,brief=run(a.project_root)
    print(json.dumps({"brief":str(brief),"web":len(bundle["web"]),"papers":len(bundle["papers"]),"labs":len(bundle["labs"]),"images":len(bundle["images"])},indent=2))
