"""Synthetic regressions; requests and web search are intercepted, never live.

Run boundedly: python -m unittest discover -s tests -p "test_troubleshooting.py" -v
These fixtures do not validate a live model, OCR, image pipeline or hardware.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from ai import provider
from ai.chat import IdeaForgeChat
from troubleshooting import engine
from troubleshooting.context import MAX_LOCAL_CHARS, project_context
from troubleshooting.incidents import classify_outcome


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve()
        self.root=self.project("10000001")
        self.other=self.project("10000002")
        self.ai=self.base/"ai.json"
        self.write(self.ai,{"language_model":{"model":"synthetic","base_url":"http://127.0.0.1:11434",
                                           "timeout_seconds":10,"temperature":0},
                            "vision_model":{"model":"synthetic","base_url":"http://127.0.0.1:11434"}})
        self.selection=self.base/"selection.json"
        self.write(self.selection,{"protocol":"aster.provider.selection.v1","app_id":"ideaforge",
                                   "provider":"standalone","revision":1})
        self.trouble=self.base/"trouble.json"
        self.write(self.trouble,{"max_local_chars":12000,"max_web_bundle_chars":8000})
        self.seen=[]
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(provider,"SELECTION_PATH",self.selection))
        self.stack.enter_context(patch.object(provider.requests,"post",side_effect=self.post))
        self.search=self.stack.enter_context(patch.object(engine,"_search",return_value=[]))

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")

    def project(self,identity):
        root=self.base/identity
        self.write(root/"project.json",{"project_id":identity,"name":"Same title",
                   "plan":{"summary":"Approved project summary "+identity,"unknowns":["Rating TBD"]}})
        return root

    def post(self,url,*,json,timeout):
        self.seen.append(json)
        self.assertEqual(url,"http://127.0.0.1:11434/api/chat")
        self.assertGreater(timeout,0)
        self.assertLessEqual(len(json["messages"][0]["content"].encode("utf-8")),65536)
        query=json["messages"][0]["content"].startswith("Create up to 5")
        result=Mock()
        result.json.return_value={"message":{"content":'{"queries":[]}' if query else "Synthetic report; result unknown."}}
        return result

    def diagnose(self,root=None,problem="motor stuck",**kwargs):
        # Call the actual decorated entry point, including provider identity and
        # publication checks. Only transport/search are intercepted.
        return engine.diagnose(root or self.root,problem,ai_config=str(self.ai),
                               trouble_config=str(self.trouble),**kwargs)

    def messages(self):
        return json.dumps(self.seen,ensure_ascii=False)

    def incident(self,root=None):
        root=root or self.root
        active=json.loads((root/"troubleshooting/ACTIVE.json").read_text(encoding="utf-8"))
        target=Path(active["incident"])
        return target if target.is_absolute() else root/target

    def read_incident(self,root=None):
        return json.loads((self.incident(root)/"incident.json").read_text(encoding="utf-8"))

    def link(self,path,target):
        if path.exists():
            path.unlink()
        try:
            path.symlink_to(target,target_is_directory=target.is_dir())
        except (OSError,NotImplementedError) as exc:
            self.skipTest("Filesystem symlink unavailable: "+str(exc))

    def private_files(self,root,reverse=False):
        files=[
            "research/pdf_evidence/versions/PRIVATE_OLD_PDF.json",
            "research/pdf_evidence/versions/PRIVATE_CURRENT_PDF.json",
            "research/pdf_evidence/manifest.json",
            "research/photos/PRIVATE_PHOTO.json",
            "research/photo_ocr/PRIVATE_OCR.json",
            ".private-staging/PRIVATE_STAGE.txt",
            "private/PRIVATE_NOTE.md",
            "research/RESEARCH_BRIEF.md",
            "fabrication/prototype_plan.json",
            "simulation/simulation_plan.json",
            "README.md","PRIVATE_TOP.txt","troubleshooting/old/REPORT.md"]
        markers=[]
        for i,relative in enumerate(reversed(files) if reverse else files):
            marker="DISTINCT_PRIVATE_"+str(i)+"_"+Path(relative).stem
            path=root/relative
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps({"passage":marker,"filename":marker+".pdf"}),encoding="utf-8")
            markers.append(marker)
        value=json.loads((root/"project.json").read_text(encoding="utf-8"))
        value["private_payload"]="PRIVATE_PROJECT_EXTRA"
        value["plan"]["pdf_evidence"]={"passage":"PRIVATE_NESTED_PROJECT"}
        self.write(root/"project.json",value)
        self.write(root/"project_memory.json",{"facts":[
            {"key":"width","statement":"Approved user width 20 mm","source":"user_statement",
             "source_text":"PRIVATE_RAW_USER_AUDIT"},
            {"key":"imported","statement":"PRIVATE_IMPORTED_PASSAGE","source":"pdf"},
            {"key":"old","statement":"PRIVATE_SUPERSEDED","source":"user_statement","status":"superseded"}
        ],"ocr_payload":"PRIVATE_MEMORY_EXTRA"})
        return markers+["PRIVATE_PROJECT_EXTRA","PRIVATE_NESTED_PROJECT","PRIVATE_RAW_USER_AUDIT",
                        "PRIVATE_IMPORTED_PASSAGE","PRIVATE_SUPERSEDED","PRIVATE_MEMORY_EXTRA"]


class DiagnosisIsolationTests(OfflineCase):
    def test_actual_diagnose_excludes_private_markers_across_budgets_order_and_versions(self):
        markers=self.private_files(self.root)
        markers+=self.private_files(self.other,reverse=True)
        for root in (self.root,self.other):
            for budget in (0,1,200,12000,30000,10**9):
                with self.subTest(project=root.name,budget=budget):
                    self.seen.clear()
                    self.write(self.trouble,{"max_local_chars":budget,"max_web_bundle_chars":10**9})
                    result=self.diagnose(root)
                    self.assertEqual(len(self.seen),2)
                    for marker in markers:
                        self.assertNotIn(marker,self.messages())
                    self.assertNotIn("PRIVATE_OLD_PDF.json",self.messages())
                    self.assertNotIn("PRIVATE_CURRENT_PDF.json",self.messages())
                    self.assertIn("Approved project summary "+root.name,self.messages())
                    self.assertTrue(Path(result["report"]).is_file())

    def test_allowlisted_user_metadata_is_project_scoped(self):
        self.private_files(self.root)
        self.write(self.other/"project_memory.json",{"facts":[{"key":"width",
                   "statement":"FOREIGN_WIDTH_90","source":"user_statement"}]})
        self.diagnose()
        self.assertIn("Approved user width 20 mm",self.messages())
        self.assertNotIn("FOREIGN_WIDTH_90",self.messages())
        self.assertNotIn("10000002",self.messages())

    def test_local_budget_is_hard_and_nonnegative(self):
        self.private_files(self.root)
        for budget in (-1,0,1,100,12000,10**9):
            value=engine._read_local(self.root,budget)
            self.assertLessEqual(len(value.encode("utf-8")),min(max(budget,0),MAX_LOCAL_CHARS))

    def test_unicode_and_large_config_budgets_stay_within_provider_limit(self):
        text="測"*3000
        self.write(self.root/"project.json",{"project_id":"10000001","name":text,
                   "plan":{"summary":text,"capabilities":[text]*12,"subsystems":[text]*12,"unknowns":[text]*12}})
        self.write(self.trouble,{"max_local_chars":10**9,"max_web_bundle_chars":10**9})
        self.search.return_value=[{"snippet":text}]*35
        self.diagnose(problem="測"*1000)
        self.assertEqual(len(self.seen),2)
        for request in self.seen:
            self.assertLessEqual(len(request["messages"][0]["content"].encode("utf-8")),65536)

    def test_oversized_project_json_fails_before_provider_requests(self):
        self.write(self.root/"project.json",{"project_id":"10000001","private":"X"*65537})
        with self.assertRaisesRegex(ValueError,"byte budget"):
            self.diagnose()
        self.assertEqual(self.seen,[])

    def test_oversized_memory_is_omitted_without_its_private_contents(self):
        self.write(self.root/"project_memory.json",{"private":"PRIVATE_TOO_BIG"+"X"*65537})
        self.diagnose()
        self.assertNotIn("PRIVATE_TOO_BIG",self.messages())
        self.assertIn("unavailable",self.messages())

    def test_nested_objects_are_never_stringified_as_approved_fields(self):
        self.write(self.root/"project.json",{"project_id":"10000001","name":{"secret":"PRIVATE_NAME"},
                    "plan":{"summary":{"secret":"PRIVATE_SUMMARY"},"unknowns":[{"secret":"PRIVATE_UNKNOWN"}]}})
        self.diagnose()
        self.assertNotIn("PRIVATE_",self.messages())

    def test_allowed_memory_link_to_outside_project_is_omitted(self):
        target=self.base/"outside.json"
        self.write(target,{"facts":[{"key":"a","statement":"PRIVATE_OUTSIDE","source":"user_statement"}]})
        self.link(self.root/"project_memory.json",target)
        self.diagnose()
        self.assertNotIn("PRIVATE_OUTSIDE",self.messages())

    def test_allowed_memory_link_to_excluded_local_archive_is_omitted(self):
        target=self.root/"research/pdf_evidence/versions/private.json"
        self.write(target,{"facts":[{"key":"a","statement":"PRIVATE_LOCAL_LINK","source":"user_statement"}]})
        self.link(self.root/"project_memory.json",target)
        self.diagnose()
        self.assertNotIn("PRIVATE_LOCAL_LINK",self.messages())

    def test_allowed_project_link_is_rejected_before_requests(self):
        target=self.other/"project.json"
        self.link(self.root/"project.json",target)
        with self.assertRaisesRegex(ValueError,"Linked"):
            self.diagnose()
        self.assertEqual(self.seen,[])

    def test_allowed_memory_hardlink_is_omitted(self):
        target=self.base/"hardlink.json"
        self.write(target,{"facts":[{"key":"a","statement":"PRIVATE_HARDLINK","source":"user_statement"}]})
        try:
            os.link(target,self.root/"project_memory.json")
        except (OSError,NotImplementedError) as exc:
            self.skipTest("Filesystem hardlink unavailable: "+str(exc))
        self.diagnose()
        self.assertNotIn("PRIVATE_HARDLINK",self.messages())

    def test_linked_troubleshooting_store_fails_before_requests_or_writes(self):
        self.link(self.root/"troubleshooting",self.other)
        before=(self.other/"project.json").read_bytes()
        with self.assertRaisesRegex(ValueError,"Linked"):
            self.diagnose()
        self.assertEqual(self.seen,[])
        self.assertEqual(before,(self.other/"project.json").read_bytes())


class IncidentTransitionTests(OfflineCase):
    def test_classification_matrix_is_conservative(self):
        cases={
            "That fixed it!":"resolved","It works now.":"resolved","Thanks, it works now.":"resolved",
            "I don't think that fixed it":"failed","It is not working now":"failed",
            "That fixed it yesterday, but it is not working now":"failed",
            "It works now, but the repair failed":"failed",
            "It works now, but the display is broken":"failed",
            "That fixed it yesterday, but now it crashes":"failed","That didn't work":"failed",
            "It no longer works":"failed","Reopen this incident":"reopen",
            "Is it working now?":"uncertain","If that fixed it, what next?":"uncertain",
            "I hope that fixed it":"uncertain","I don't know if it works now":"uncertain",
            'The log says "it works now"':"uncertain","Yesterday that fixed it":"uncertain",
            "That fixed it before":"uncertain","Don't reopen this incident":"uncertain",
            "If it is not working, should I replace it?":"uncertain","hello":"none",
        }
        for text,expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_outcome(text),expected)

    def test_negated_and_mixed_reports_do_not_resolve_open_incident(self):
        self.diagnose()
        for text in ("I don't think that fixed it","It is not working now",
                     "It works now yesterday, but still broken","Is it working now?",
                     "If that fixed it, what next?"):
            data=engine.record_outcome(self.root,text)
            self.assertEqual(data["status"],"open")
            self.assertIsNone(data["user_outcome"])
        self.assertEqual(len(self.read_incident()["outcome_history"]),5)

    def test_resolution_failure_and_explicit_reopening_preserve_history_and_report(self):
        self.diagnose()
        report=self.incident()/"REPORT.md"
        original=report.read_bytes()
        resolved=engine.record_outcome(self.root,"That fixed it")
        self.assertEqual(resolved["status"],"resolved")
        reopened=engine.record_outcome(self.root,"It is not working now")
        self.assertEqual(reopened["status"],"open")
        self.assertIsNone(reopened["user_outcome"])
        self.assertEqual(reopened["outcome_history"][0]["user_report"],"That fixed it")
        engine.record_outcome(self.root,"It works now")
        explicit=engine.record_outcome(self.root,"Reopen this incident")
        self.assertEqual(explicit["status"],"open")
        self.assertEqual(report.read_bytes(),original)
        self.assertEqual(len(explicit["outcome_history"]),4)

    def test_uncertain_report_keeps_resolved_state_without_confirming_a_new_fix(self):
        self.diagnose()
        engine.record_outcome(self.root,"That fixed it")
        data=engine.record_outcome(self.root,"If it works now, what next?")
        self.assertEqual(data["status"],"resolved")
        self.assertEqual(data["user_outcome"],"That fixed it")
        self.assertEqual(data["outcome_history"][-1]["classification"],"uncertain")

    def test_restart_loads_resolution_then_reopens_with_same_report(self):
        self.diagnose()
        engine.record_outcome(self.root,"That fixed it")
        report=(self.incident()/"REPORT.md").read_bytes()
        code=("import json; from troubleshooting.engine import record_outcome; "
              "print(json.dumps(record_outcome("+repr(str(self.root))+", 'It is not working now')))")
        result=json.loads(subprocess.check_output([sys.executable,"-c",code],text=True,
                          cwd=str(Path(__file__).resolve().parents[1]),timeout=10))
        self.assertEqual(result["status"],"open")
        self.assertEqual(result["outcome_history"][0]["user_report"],"That fixed it")
        self.assertEqual((self.incident()/"REPORT.md").read_bytes(),report)

    def test_project_separation_with_same_titles_and_foreign_absolute_active(self):
        self.diagnose()
        self.diagnose(self.other)
        other_record=self.incident(self.other)/"incident.json"
        before=other_record.read_bytes()
        self.write(self.root/"troubleshooting/ACTIVE.json",{"incident":str(self.incident(self.other)),"status":"open"})
        with self.assertRaisesRegex(ValueError,"outside"):
            engine.record_outcome(self.root,"That fixed it")
        self.assertEqual(other_record.read_bytes(),before)

    def test_copied_active_pointer_with_foreign_identity_is_rejected(self):
        self.diagnose()
        self.diagnose(self.other)
        foreign=json.loads((self.other/"troubleshooting/ACTIVE.json").read_text(encoding="utf-8"))
        self.write(self.root/"troubleshooting/ACTIVE.json",foreign)
        with self.assertRaisesRegex(ValueError,"another project"):
            engine.record_outcome(self.root,"That fixed it")

    def test_legacy_contained_absolute_pointer_migrates_and_retains_resolution(self):
        self.diagnose()
        incident=self.incident()
        self.write(incident/"incident.json",{"status":"resolved","created_at":"old","problem":"old",
                   "user_outcome":"That fixed it","tried_actions":[]})
        self.write(self.root/"troubleshooting/ACTIVE.json",{"incident":str(incident),"status":"resolved"})
        data=engine.record_outcome(self.root,"It is not working now")
        active=json.loads((self.root/"troubleshooting/ACTIVE.json").read_text(encoding="utf-8"))
        self.assertFalse(Path(active["incident"]).is_absolute())
        self.assertEqual(data["outcome_history"][0]["classification"],"legacy_resolution")
        self.assertEqual(data["status"],"open")

    def test_active_incident_symlink_cannot_write_outside_project(self):
        self.diagnose()
        self.diagnose(self.other)
        before=(self.incident(self.other)/"incident.json").read_bytes()
        target=self.root/"troubleshooting/foreign"
        self.link(target,self.incident(self.other))
        self.write(self.root/"troubleshooting/ACTIVE.json",{"incident":"troubleshooting/foreign","status":"open"})
        with self.assertRaisesRegex(ValueError,"Linked"):
            engine.record_outcome(self.root,"That fixed it")
        self.assertEqual((self.incident(self.other)/"incident.json").read_bytes(),before)

    def test_actual_chat_failure_routing_reopens_and_appends_report(self):
        self.diagnose()
        engine.record_outcome(self.root,"That fixed it")
        original=(self.incident()/"REPORT.md").read_bytes()
        original_incident=self.incident()
        chat=IdeaForgeChat.__new__(IdeaForgeChat)
        chat.current_project=self.root
        chat.config_path=self.ai
        with patch.object(engine,"_load",return_value={"max_local_chars":12000,"max_web_bundle_chars":8000}):
            result=chat._troubleshoot("It is not working now")
        self.assertEqual(Path(result["incident_dir"]),original_incident)
        self.assertEqual((original_incident/"REPORT.md").read_bytes(),original)
        self.assertNotEqual(Path(result["report"]).name,"REPORT.md")
        data=self.read_incident()
        self.assertEqual(data["status"],"open")
        self.assertEqual(len(data["reports"]),2)
        self.assertEqual(data["outcome_history"][-1]["classification"],"failed")

    def test_mixed_current_broken_and_crash_reports_reopen_and_route(self):
        self.diagnose()
        chat=IdeaForgeChat.__new__(IdeaForgeChat)
        chat.current_project=self.root
        chat.config_path=self.ai
        for text in ("It works now, but the display is broken",
                     "That fixed it yesterday, but now it crashes"):
            with self.subTest(text=text):
                engine.record_outcome(self.root,"That fixed it")
                self.seen.clear()
                with patch.object(engine,"_load",return_value={"max_local_chars":12000}):
                    result=chat._troubleshoot(text)
                self.assertNotIn("error",result)
                self.assertEqual(len(self.seen),2)
                self.assertEqual(self.read_incident()["status"],"open")
                self.assertEqual(self.read_incident()["outcome_history"][-1]["classification"],"failed")

    def test_large_diagnostic_record_does_not_replace_prior_record_or_report(self):
        self.diagnose()
        incident=self.incident()
        previous=(incident/"incident.json").read_bytes()
        report=(incident/"REPORT.md").read_bytes()
        self.search.return_value=[{"snippet":"X"*engine.MAX_RECORD_BYTES}]
        with self.assertRaisesRegex(ValueError,"record exceeds"):
            self.diagnose(continue_active=True)
        self.assertEqual((incident/"incident.json").read_bytes(),previous)
        self.assertEqual((incident/"REPORT.md").read_bytes(),report)
        self.assertEqual(list(incident.glob("REPORT-*.md")),[])

    def test_indented_followup_byte_budget_refuses_before_new_report(self):
        self.diagnose()
        incident=self.incident()
        previous=(incident/"incident.json").read_bytes()
        with patch.object(engine,"MAX_RECORD_BYTES",len(previous)+1):
            with self.assertRaisesRegex(ValueError,"record exceeds"):
                self.diagnose(continue_active=True)
        self.assertEqual((incident/"incident.json").read_bytes(),previous)
        self.assertEqual(list(incident.glob("REPORT-*.md")),[])

    def test_outcome_history_budget_failure_keeps_previous_record(self):
        self.diagnose()
        incident=self.incident()
        self.write(incident/"incident.json",self.read_incident())
        previous=(incident/"incident.json").read_bytes()
        with patch.object(engine,"MAX_RECORD_BYTES",len(previous)+5):
            with self.assertRaisesRegex(ValueError,"history exceeds"):
                engine.record_outcome(self.root,"That fixed it")
        self.assertEqual((incident/"incident.json").read_bytes(),previous)

    def test_chat_confirmation_and_uncertainty_do_not_route_as_diagnosis(self):
        self.diagnose()
        chat=IdeaForgeChat.__new__(IdeaForgeChat)
        chat.current_project=self.root
        chat.config_path=self.ai
        self.seen.clear()
        self.assertIsNone(chat._troubleshoot("That fixed it"))
        self.assertIsNone(chat._troubleshoot("Is it working now?"))
        self.assertEqual(self.seen,[])
        self.assertEqual(self.read_incident()["status"],"resolved")
        self.assertEqual(self.read_incident()["outcome_history"][-1]["classification"],"uncertain")

    def test_repeated_diagnoses_do_not_collide_or_overwrite_reports(self):
        first=self.diagnose()
        second=self.diagnose()
        self.assertNotEqual(first["incident_dir"],second["incident_dir"])
        self.assertTrue(Path(first["report"]).is_file())
        self.assertTrue(Path(second["report"]).is_file())

    def test_no_active_incident_returns_none(self):
        self.assertIsNone(engine.record_outcome(self.root,"That fixed it"))


if __name__=="__main__":
    unittest.main()
