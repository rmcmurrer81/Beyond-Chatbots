from __future__ import annotations
import json, queue, threading, time, traceback
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import replace
import uuid
from ai.provider import operation, activate, publication_guard, ProviderError

from core.project_state import (
    load as load_state,
    mark_discoveries,
    schedule_next_watch,
    set_research,
)

def _load_json(path,default=None):
    p=Path(path)
    if not p.exists(): return default
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return default

def _parse_time(value):
    if not value: return None
    try: return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except Exception: return None

class BackgroundResearchManager:
    def __init__(self,event_callback=None,watch_config="research_engine/watch_config.json",ai_config="ai/config.json"):
        self.ai_config=Path(ai_config).resolve()
        self.q=queue.Queue()
        self.event_callback=event_callback
        self.active={}
        self.stop_event=threading.Event()
        self.watch_cfg=_load_json(watch_config,{}) or {}
        self.interval_minutes=float(self.watch_cfg.get("interval_minutes",60))
        from core.project_index import list_projects
        self.resume_pending(list_projects())
        self.worker=threading.Thread(target=self._loop,daemon=True)
        self.monitor=threading.Thread(target=self._watch_loop,daemon=True)
        self.worker.start()
        self.monitor.start()
        from workspace3d.jobs import Manager
        from core.project_index import list_projects
        self.workspace_manager = Manager(lambda: [item["path"] for item in list_projects()])

    def _emit(self,kind,payload):
        if self.event_callback:
            try: self.event_callback(kind,payload)
            except Exception: pass

    def _already_queued(self,key):
        try:
            return any(item[0]==key for item in list(self.q.queue))
        except Exception:
            return False

    def enqueue(self,project_root,mode="deep"):
        root=Path(project_root)
        key=str(root.resolve())
        if key in self.active or self._already_queued(key):
            return False
        with operation(root,self.ai_config,deadline=time.time()+1800) as captured:
            captured=replace(captured,cancellation=threading.Event(),deadline=time.time()+1800,
                             project_current=None,request_prefix=uuid.uuid4().hex,provenance=[])
        set_research(root,"queued",f"{mode} research queued")
        self.q.put((key,mode,captured))
        self._emit("research_queued",{"project":key,"mode":mode})
        return True

    def _run_pass(self,root,mode):
        with operation(root,self.ai_config):
            return self._run_scoped_pass(root,mode)

    def _run_scoped_pass(self,root,mode):
        from research_engine.horizon import expand_topics
        from research_engine.research_project import research_project
        from research_engine.summarize import summarize
        from research_engine.discoveries import assess
        from research_engine.virtual_builder import update_virtual_build

        research_json=root/"research"/"research.json"
        before=_load_json(research_json,{}) or {}

        # Refresh the technology horizon on deep/watch passes and create it on the first pass.
        horizon_file=root/"research"/"technology_horizon.json"
        if mode in {"deep","watch"} or not horizon_file.exists():
            try:
                expand_topics(root)
            except ProviderError:
                raise
            except Exception as e:
                self._emit("research_note",{"project":str(root),"message":f"Technology-horizon update warning: {e}"})

        # Include explicit custom workspace goals in the horizon without executing model output.
        maxq=2 if mode=="quick" else None
        bundle=research_project(root,max_queries_override=maxq)
        # Persist new evidence as pending BEFORE any fallible synthesis. Otherwise
        # a replaced research.json can make the next retry mistake it for baseline.
        if before:
            from research_engine.discovery_selection import claim, release
            lease,_=claim(root,before,bundle)
            release(root,lease)
        brief=summarize(root)

        try:
            from research_engine.gallery import build_gallery
            gallery=build_gallery(root)
        except Exception:
            gallery=[]

        try:
            from research_engine.variants import analyze_variants
            variants=analyze_variants(root)
        except ProviderError:
            raise
        except Exception:
            variants=None

        discoveries=[]
        if before:
            try:
                discoveries=assess(root,before,bundle)
            except ProviderError:
                raise
            except Exception as e:
                self._emit("research_note",{"project":str(root),"message":f"Discovery assessment warning: {e}"})

        virtual=None
        if self.watch_cfg.get("auto_virtual_build",True):
            try:
                virtual=update_virtual_build(root,discoveries)
            except ProviderError:
                raise
            except Exception as e:
                self._emit("research_note",{"project":str(root),"message":f"Virtual-build update warning: {e}"})

        publication_guard(root)
        return bundle,brief,gallery,variants,discoveries,virtual

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                key,mode,captured=self.q.get(timeout=0.3)
            except queue.Empty:
                continue
            root=Path(key)
            self.active[key]=captured
            set_research(root,"running",f"{mode} research running")
            self._emit("research_started",{"project":key,"mode":mode})
            try:
                with activate(captured):
                    bundle,brief,gallery,variants,discoveries,virtual=self._run_pass(root,mode)
                    publication_guard(root)
                    if discoveries:
                        mark_discoveries(root,len(discoveries))
                        self._emit("useful_discovery",{
                            "project":key,
                            "count":len(discoveries),
                            "discoveries":discoveries,
                            "latest_file":str(root/"research"/"LATEST_DISCOVERIES.md")
                        })
                    msg=(
                        f"Research complete: {len(bundle.get('papers',[]))} paper/scholarly records, "
                        f"{len(bundle.get('labs',[]))} institution entries, "
                        f"{len(bundle.get('web',[]))} web results"
                        + (f", {len(discoveries)} useful new discovery/discoveries." if discoveries else ".")
                    )
                    set_research(root,"complete",msg)
                    schedule_next_watch(root,self.interval_minutes)
                    self._emit("research_complete",{
                        "project":key,
                        "mode":mode,
                        "brief":str(brief),
                        "counts":{
                            "papers":len(bundle.get("papers",[])),
                            "labs":len(bundle.get("labs",[])),
                            "web":len(bundle.get("web",[])),
                            "images":len(bundle.get("images",[]))
                        },
                        "gallery":gallery,
                        "variants":variants,
                        "discoveries":discoveries,
                        "virtual_build_updated":bool(virtual)
                    })
            except Exception as e:
                state="interrupted" if captured.cancellation.is_set() or self.stop_event.is_set() else "error"
                set_research(root,state,str(e))
                schedule_next_watch(root,self.interval_minutes)
                self._emit("research_error",{
                    "project":key,
                    "mode":mode,
                    "error":str(e),
                    "traceback":traceback.format_exc()
                })
            finally:
                self.active.pop(key,None)
                self.q.task_done()

    def _watch_loop(self):
        # Periodically enqueue due watched projects while IdeaForge is running.
        while not self.stop_event.is_set():
            try:
                from core.project_index import list_projects
                now=datetime.now(timezone.utc)
                for item in list_projects():
                    root=Path(item["path"])
                    state=load_state(root)
                    if not state.get("research_watch_enabled",True):
                        continue
                    if state.get("research_status") in {"queued","running","interrupted"}:
                        continue
                    key=str(root.resolve())
                    if key in self.active or self._already_queued(key):
                        continue
                    due=_parse_time(state.get("next_watch_at"))
                    if due is None or due <= now:
                        mode="watch" if (root/"research"/"research.json").exists() else "quick"
                        self.enqueue(root,mode)
            except Exception:
                pass
            self.stop_event.wait(20)

    def resume_pending(self,projects):
        for item in projects:
            root=Path(item["path"])
            try:
                state=load_state(root)
                if state.get("research_status") in {"queued","running"}:
                    set_research(root,"interrupted","Previous research was interrupted. Choose Research to start a new operation; no request was replayed.")
            except Exception:
                pass

    def shutdown(self):
        self.stop_event.set()
        for captured in list(self.active.values()):
            captured.cancellation.set()
        for key,mode,captured in list(self.q.queue):
            captured.cancellation.set()
            set_research(Path(key),"interrupted","Queued research cancelled on shutdown; choose Research to start again.")
        self.workspace_manager.shutdown()
