"""Twelve source-authored scenario groups. Runtime qualification is recorded separately."""
import copy
import json
import math
import os
import sqlite3
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fabrication.printer_fit import (PrinterFitStore, FitInputError, PROFILE_FORMAT,
                                    screen_geometry, part_model, digest)
from workspace3d.checks import run_checks
from workspace3d.model import demo, validate
from workspace3d.store import Store


def profile():
    return {"format":PROFILE_FORMAT,"units":"mm","usable_xyz":[100,80,60],
            "margins_min_xyz":[0,0,0],"margins_max_xyz":[0,0,0],"keep_outs":[],
            "review":{"reviewer":"Synthetic test author","note":"Invented test dimensions; no physical printer."}}


def model(size=None, minimum=None, orientation="xyz"):
    return {"units":"mm","size_xyz":size or [90,70,50],
            "placement":{"units":"mm","min_xyz":minimum or [0,0,0],"orientation":orientation}}


class PrinterFitScenarios(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/"project.json").write_text(json.dumps({"project_id":"synthetic-project","name":"Test"}))
        self.inventory={"items":[{"equipment_id":"small","category":"3d_printer","name":"Small",
                                  "specs":{"build_x_mm":10,"build_y_mm":10,"build_z_mm":10}},
                                 {"equipment_id":"chosen","category":"3d_printer","name":"Chosen",
                                  "specs":{"build_x_mm":1000,"build_y_mm":1000,"build_z_mm":1000}}]}
        self.fit=PrinterFitStore(self.root)

    def select(self, value=None, expected=0, inventory=None):
        return self.fit.select("chosen",profile() if value is None else value,expected_revision=expected,
                               inventory=inventory or self.inventory)

    def screen(self, value=None, inventory=None):
        return self.fit.screen(value or model(),model_revision="model-1",
                               inventory=inventory or self.inventory)

    def test_01_selected_printer_and_duplicate_ids(self):
        self.select()
        receipt=self.screen()
        self.assertEqual(receipt["binding"]["selected_printer_id"],"chosen")
        self.assertTrue(receipt["result"]["geometric_fit"])
        # A nominal 1000 mm catalog value must not override the reviewed 100 mm profile.
        self.assertFalse(self.screen(model([101,70,50]))["result"]["geometric_fit"])
        duplicate=copy.deepcopy(self.inventory); duplicate["items"].append(copy.deepcopy(duplicate["items"][1]))
        self.assertEqual(self.screen(inventory=duplicate)["result"]["status"],"unknown")
        with self.assertRaises(FitInputError):
            self.fit.select("chosen",profile(),expected_revision=1,inventory=duplicate)
        with tempfile.TemporaryDirectory() as folder:
            from inventory import equipment
            local=Path(folder)/"local.json"; imported=Path(folder)/"import.json"
            local.write_text(json.dumps(self.inventory)); imported.write_text(json.dumps({"items":[self.inventory["items"][1]]}))
            with patch.object(equipment,"_cfg",return_value={"local_inventory":str(local),"optional_imports":[str(imported)]}):
                with self.assertRaises(ValueError): equipment.load_all(strict_ids=True)
                imported.write_text('{"items":[],"items":[]}' )
                with self.assertRaises(ValueError): equipment.load_all(strict_ids=True)
                imported.write_text('{"items":[{"equipment_id":"other","value":NaN}]}' )
                with self.assertRaises(ValueError): equipment.load_all(strict_ids=True)

    def test_02_reordered_inventory_keeps_selection_and_receipt(self):
        self.select(); before=self.screen()
        reordered={"items":list(reversed(self.inventory["items"]))}
        self.assertEqual(before,self.screen(inventory=reordered))
        self.assertEqual(self.fit.selection()["printer_id"],"chosen")

    def test_03_six_rotations_require_declared_configuration(self):
        p=profile(); p["usable_xyz"]=[80,100,60]; self.select(p)
        unrotated=self.screen()
        self.assertFalse(unrotated["result"]["geometric_fit"])
        self.assertEqual(len(unrotated["result"]["configurations"]),6)
        self.assertEqual([x["orientation"] for x in unrotated["result"]["configurations"]],
                         ["xyz","xzy","yxz","yzx","zxy","zyx"])
        rotated=self.screen(model(orientation="yxz"))
        self.assertTrue(rotated["result"]["geometric_fit"])
        missing=model(); missing["placement"]["orientation"]=None
        self.assertEqual(self.screen(missing)["result"]["status"],"unknown")

    def test_04_margins_and_declared_placement(self):
        p=profile(); p["margins_min_xyz"]=[5,5,0]; p["margins_max_xyz"]=[5,5,0]
        self.select(p)
        self.assertFalse(self.screen()["result"]["geometric_fit"])
        self.assertTrue(self.screen(model(minimum=[5,5,0]))["result"]["geometric_fit"])
        missing=model(); missing["placement"]=None
        self.assertEqual(self.screen(missing)["result"]["status"],"unknown")

    def test_05_effective_z_is_reviewed_not_nominal(self):
        p=profile(); p["margins_max_xyz"]=[0,0,15]; self.select(p)
        receipt=self.screen()
        self.assertFalse(receipt["result"]["geometric_fit"])
        self.assertEqual(receipt["result"]["effective_max_xyz_mm"][2],45)
        self.assertTrue(self.screen(model([90,70,45]))["result"]["geometric_fit"])

    def test_06_keep_out_hit_and_contact_fail(self):
        p=profile(); p["keep_outs"]=[{"id":"clip","min_xyz":[0,0,0],"max_xyz":[5,5,10]}]
        self.select(p); receipt=self.screen(model([10,10,10],[5,0,0]))
        self.assertFalse(receipt["result"]["geometric_fit"])
        self.assertEqual(receipt["result"]["configurations"][0]["keep_out_hits"],["clip"])

    def test_07_keep_out_clear_at_declared_position(self):
        p=profile(); p["keep_outs"]=[{"id":"clip","min_xyz":[0,0,0],"max_xyz":[5,5,10]}]
        self.select(p); receipt=self.screen(model([10,10,10],[6,0,0]))
        self.assertTrue(receipt["result"]["geometric_fit"])
        self.assertEqual(receipt["result"]["configurations"][0]["keep_out_hits"],[])

    def test_08_missing_profile_and_legacy_nominal_are_unknown(self):
        self.assertEqual(self.screen()["result"]["status"],"unknown")
        with self.assertRaises(FitInputError): self.select({})
        # Explicit scene nominal dimensions do not constitute a project reviewed profile.
        scene=demo(); scene["printer_volume_mm"]=[1000,1000,1000]
        result=run_checks(scene,project_root=self.root,inventory=self.inventory)
        self.assertTrue(all(x["receipt"]["result"]["status"]=="unknown" for x in result["printer_fit"]))
        self.assertTrue(all(x["axis_aligned_fit"] is None for x in result["printer_fit"]))

    def test_09_invalid_dimensions_profiles_and_bounds(self):
        self.select()
        for bad in (0,-1,True,math.nan,math.inf,1000001,10**400):
            value=model(); value["size_xyz"][0]=bad
            self.assertEqual(self.screen(value)["result"]["status"],"unknown")
        for bad in (True,-1,math.inf,10**400):
            value=model(); value["placement"]["min_xyz"][0]=bad
            self.assertEqual(self.screen(value)["result"]["status"],"unknown")
        for mutate in (lambda p:p.update(margins_max_xyz=[100,0,0]),
                       lambda p:p.update(usable_xyz=[True,80,60]),
                       lambda p:p.update(usable_xyz=[10**400,80,60]),
                       lambda p:p.update(review={"reviewer":"","note":""}),
                       lambda p:p.update(keep_outs=[{"id":"outside","min_xyz":[0,0,0],"max_xyz":[101,1,1]}]),
                       lambda p:p.update(keep_outs=[{"id":"huge","min_xyz":[0,0,0],"max_xyz":[10**400,1,1]}]),
                       lambda p:p.update(keep_outs=[{"id":"x","min_xyz":[1,0,0],"max_xyz":[1,1,1]}]),
                       lambda p:p.update(keep_outs=[{"id":str(i),"min_xyz":[0,0,0],"max_xyz":[1,1,1]} for i in range(33)])):
            candidate=profile(); mutate(candidate)
            with self.assertRaises(FitInputError): self.select(candidate,expected=1)

    def test_10_stale_and_forged_receipts_cannot_be_accepted(self):
        self.select(); original=self.screen()
        boolean_revision=copy.deepcopy(original); boolean_revision["binding"]["selection_revision"]=True
        self.assertFalse(self.fit.current(boolean_revision,model(),model_revision="model-1",inventory=self.inventory))
        for change in ("model","revision","placement","project","inventory","profile","selection","forged","bool_int"):
            with self.subTest(change=change):
                value=model(); revision="model-1"; inventory=copy.deepcopy(self.inventory)
                receipt=copy.deepcopy(original); project={"project_id":"synthetic-project","name":"Test"}
                if change=="model": value["size_xyz"][0]=89
                if change=="revision": revision="model-2"
                if change=="placement": value["placement"]["min_xyz"][0]=1
                if change=="project": project["name"]="Changed"
                if change=="inventory": inventory["items"][1]["name"]="Changed"
                if change=="profile":
                    p=profile(); p["usable_xyz"][0]=99
                    self.select(p,expected=self.fit.selection()["revision"])
                if change=="selection":
                    self.fit.select("small",profile(),expected_revision=self.fit.selection()["revision"],
                                    inventory=self.inventory)
                if change=="forged": receipt["result"]["status"]="not_fit"
                if change=="bool_int": receipt["result"]["geometric_fit"]=1
                (self.root/"project.json").write_text(json.dumps(project))
                self.assertFalse(self.fit.current(receipt,value,model_revision=revision,inventory=inventory))
                with self.assertRaises(FitInputError):
                    self.fit.save_receipt(receipt,value,model_revision=revision,inventory=inventory)
                (self.root/"project.json").write_text(json.dumps({"project_id":"synthetic-project","name":"Test"}))
                if change in ("profile","selection"):
                    self.select(expected=self.fit.selection()["revision"])
                    original=self.screen()
        # Workspace commit deduplication and reload also cannot carry forged/stale successes.
        scene=demo(); scene["parts"][0]["printer_placement"]={"units":"mm","min_xyz":[0,0,0],"orientation":"xyz"}
        with patch("inventory.equipment.load_all",return_value=self.inventory):
            store=Store(self.root); tests=run_checks(scene,project_root=self.root)
            rid=store.add(scene,"test",[],tests,expected_parent=None,fingerprint="fixture")
            forged=copy.deepcopy(tests); forged["printer_fit"][0]["receipt"]["result"]["geometric_fit"]=True
            # This large example part cannot fit the reviewed 100 mm X volume.
            with self.assertRaises(ValueError):
                store.add(scene,"test",[],forged,expected_parent=rid,fingerprint="fixture")
            type_forgery=copy.deepcopy(tests)
            type_forgery["printer_fit"][0]["receipt"]["result"]["geometric_fit"]=0
            with self.assertRaises(ValueError):
                store.add(scene,"test",[],type_forgery,expected_parent=rid,fingerprint="fixture")
            p=profile(); p["usable_xyz"][0]=130; self.select(p,expected=self.fit.selection()["revision"])
            with self.assertRaises(ValueError):
                store.add(scene,"test",[],tests,expected_parent=rid,fingerprint="fixture")
            reloaded=store.revision(rid)
            self.assertTrue(reloaded["tests"]["printer_fit_stale"])
            self.assertTrue(all(x["receipt"]["result"]["status"]=="unknown" for x in reloaded["tests"]["printer_fit"]))
        with tempfile.TemporaryDirectory() as folder:
            empty_root=Path(folder)
            empty_store=Store(empty_root)
            a={"schema_version":1,"units":"mm","parts":[],"title":"A"}
            empty_store.add(a,"empty",[],run_checks(a),expected_parent=None,fingerprint="empty")
            b=copy.deepcopy(a); b["title"]="B"
            with self.assertRaises(ValueError):
                empty_store.add(b,"changed",[],run_checks(b),expected_parent=empty_store.pointer(),fingerprint="empty")
        from workspace3d.jobs import queue_refresh, run_one
        from workspace3d.adapters import gather
        with patch("inventory.equipment.load_all",return_value=self.inventory):
            folder=self.root/"design"; folder.mkdir(exist_ok=True)
            (folder/"assembly.json").write_text(json.dumps(demo()))
            job_id=queue_refresh(self.root)
            self.select(expected=self.fit.selection()["revision"])
            run_one(self.root)
            self.assertEqual(Store(self.root).job_status()[0]["state"],"error")
            self.assertIn("context changed",Store(self.root).job_status()[0]["error"])
            # Selection changes inside the check callback, after the worker's first context check.
            queue_refresh(self.root)
            original_checks=run_checks
            def changed_during_checks(scene,**kwargs):
                self.select(expected=self.fit.selection()["revision"])
                return original_checks(scene,**kwargs)
            before=len(Store(self.root).history())
            with patch("workspace3d.jobs.run_checks",side_effect=changed_during_checks):
                run_one(self.root)
            self.assertEqual(len(Store(self.root).history()),before)
            self.assertIn("context changed",Store(self.root).job_status()[0]["error"])
            # A captured context cannot be accepted after the project identity file vanishes.
            payload=gather(self.root)
            tests=run_checks(payload["scene"],project_root=self.root)
            (self.root/"project.json").unlink()
            with self.assertRaises(ValueError):
                Store(self.root).add(payload["scene"],"deleted project",payload["sources"],tests,
                                     expected_parent=Store(self.root).pointer())
            (self.root/"project.json").write_text(json.dumps({"project_id":"synthetic-project","name":"Test"}))

    def test_11_selection_receipts_restart_and_project_isolation(self):
        self.select(); receipt=self.screen()
        fingerprint=self.fit.save_receipt(receipt,model(),model_revision="model-1",inventory=self.inventory)
        restarted=PrinterFitStore(self.root)
        self.assertEqual(restarted.selection()["printer_id"],"chosen")
        self.assertEqual(restarted.receipt(fingerprint,model=model(),model_revision="model-1",inventory=self.inventory),receipt)
        self.assertEqual(restarted.receipt(fingerprint)["result"]["status"],"unknown")
        self.assertTrue(restarted.current(receipt,model(),model_revision="model-1",inventory=self.inventory))
        # Saving derived receipts does not edit project.json or stale the receipt.
        self.assertEqual(self.screen(),receipt)
        captured_revision=self.fit._project()[1]
        (self.root/"project.json").write_text(json.dumps({"project_id":"synthetic-project","name":"Changed"}))
        with self.assertRaises(FitInputError):
            self.fit.select("chosen",profile(),expected_revision=1,inventory=self.inventory,
                            expected_project_revision=captured_revision)
        (self.root/"project.json").write_text(json.dumps({"project_id":"synthetic-project","name":"Test"}))
        with tempfile.TemporaryDirectory() as other:
            copied=Path(other)/"copy"
            shutil.copytree(self.root,copied)
            copy_store=PrinterFitStore(copied)
            self.assertIsNone(copy_store.selection())
            self.assertIsNone(copy_store.receipt(fingerprint,model=model(),model_revision="model-1",inventory=self.inventory))
            self.assertFalse(copy_store.current(receipt,model(),model_revision="model-1",inventory=self.inventory))
            copy_store.select("chosen",profile(),expected_revision=0,inventory=self.inventory)
            self.assertTrue(copy_store.screen(model(),model_revision="model-1",inventory=self.inventory)["result"]["geometric_fit"])
        with self.assertRaises(FitInputError): self.select(expected=0)
        with self.fit._connect(initialize=False) as db:
            db.execute("UPDATE printer_receipts SET receipt=? WHERE sha256=?",
                       (json.dumps({"tampered":True}),fingerprint))
        with self.assertRaises(FitInputError):
            restarted.receipt(fingerprint,model=model(),model_revision="model-1",inventory=self.inventory)
        with tempfile.TemporaryDirectory() as other:
            linked=Path(other); (linked/"project.json").write_text((self.root/"project.json").read_text())
            (linked/"workspace3d").mkdir()
            os.link(self.fit.path,linked/"workspace3d"/"history.sqlite3")
            try:
                self.assertEqual(PrinterFitStore(linked).screen(model(),model_revision="model-1",inventory=self.inventory)["result"]["status"],"unknown")
                with self.assertRaises(FitInputError):
                    PrinterFitStore(linked).select("chosen",profile(),expected_revision=0,inventory=self.inventory)
            finally:
                (linked/"workspace3d"/"history.sqlite3").unlink()
        (self.root/"project.json").write_text(json.dumps({"project_id":"other-project","name":"Test"}))
        self.assertIsNone(restarted.selection()); self.assertIsNone(restarted.receipt(fingerprint))
        self.assertEqual(self.screen()["result"]["status"],"unknown")

    def test_12_unknown_units_do_not_infer_or_convert(self):
        self.select()
        for unit in (None,"","inch","cm","MM"):
            value=model(); value["units"]=unit
            self.assertEqual(self.screen(value)["result"]["status"],"unknown")
            candidate=profile(); candidate["units"]=unit
            with self.assertRaises(FitInputError): self.select(candidate,expected=1)
        badscene=demo(); badscene["parts"][0]["printer_placement"]={"units":"mm","min_xyz":[10**400,0,0],"orientation":"xyz"}
        with self.assertRaises(ValueError): validate(badscene)
        value=model(); value["placement"]["units"]=None
        self.assertEqual(self.screen(value)["result"]["status"],"unknown")


if __name__=="__main__": unittest.main()
