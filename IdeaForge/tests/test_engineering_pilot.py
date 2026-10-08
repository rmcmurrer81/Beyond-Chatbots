import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from engineering_pilot.schema import validate, cheap_checks
from engineering_pilot.runner import run, stage

EXAMPLE=Path(__file__).resolve().parents[1]/'engineering_pilot/examples/two_link.json'

class PilotTests(unittest.TestCase):
    def setUp(self): self.raw=json.loads(EXAMPLE.read_text())
    def test_example_valid_and_cheap_pass(self):
        self.assertEqual(cheap_checks(validate(self.raw))['status'],'passed')
    def test_missing_unknown_units_and_review(self):
        for change in ('missing','unknown','unit','nan','bool','source','review'):
            raw=copy.deepcopy(self.raw)
            if change=='missing': del raw['measurements']['payload_kg']
            elif change=='unknown': raw['measurements']['script']='print(1)'
            elif change=='unit': raw['measurements']['length_1_m']['unit']='mm'
            elif change=='nan': raw['measurements']['length_1_m']['value']=float('nan')
            elif change=='bool': raw['measurements']['length_1_m']['value']=True
            elif change=='source': raw['measurements']['length_1_m']['source']=' '
            else: raw['reviewed']=False
            with self.subTest(change=change),self.assertRaises(ValueError): validate(raw)
    def test_uncertain_mass_and_derived_geometry_are_checked(self):
        p=validate(self.raw);p['mass_max_kg']=.22;p['uncertainty_fraction']=.25
        self.assertIn('mass_limit',cheap_checks(p)['violations'])
        p=validate(self.raw);p['length_2_m']=.05;p['payload_radius_m']=.03
        self.assertIn('payload_geometry',cheap_checks(p)['violations'])

    def test_constraint_failure_skips_expensive_workers(self):
        self.raw['measurements']['torque_limit_nm']['value']=.01
        with tempfile.TemporaryDirectory() as tmp, patch('engineering_pilot.runner.stage') as worker:
            report=run(self.raw,Path(tmp)/'out')
            self.assertEqual(report['status'],'failed');worker.assert_not_called()
    def test_no_feasible_search_is_failed_not_unknown(self):
        with tempfile.TemporaryDirectory() as tmp,patch('engineering_pilot.runner.stage',return_value={'status':'failed','shortlist':[]}):
            self.assertEqual(run(self.raw,Path(tmp)/'out',optimize=True)['status'],'failed')

    def test_unknown_dependency_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp,patch('engineering_pilot.runner.stage',return_value={'status':'unknown','reason':'unavailable'}):
            self.assertEqual(run(self.raw,Path(tmp)/'out')['status'],'unknown')
    def test_budget_and_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): run(self.raw,Path(tmp)/'a',seconds=0)
            with self.assertRaises(FileExistsError): run(self.raw,tmp)
            self.assertEqual(stage('cad',validate(self.raw),Path(tmp),time.monotonic()-1)['status'],'unknown')
    def test_timeout_terminates_worker(self):
        import subprocess
        with patch('engineering_pilot.runner.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',.01)):
            self.assertEqual(stage('cad',validate(self.raw),Path('/unused'),time.monotonic()+1)['status'],'unknown')
    def test_identical_input_hash(self):
        with tempfile.TemporaryDirectory() as tmp,patch('engineering_pilot.runner.stage',return_value={'status':'unknown'}):
            a=run(self.raw,Path(tmp)/'a');b=run(self.raw,Path(tmp)/'b')
            self.assertEqual(a['input_sha256'],b['input_sha256'])

@unittest.skipUnless(all(importlib.util.find_spec(name) for name in ('cadquery','mujoco','scipy')), 'optional CAD/dynamics stack unavailable')
class PilotIntegrationTests(unittest.TestCase):
    def test_dynamic_saturation_and_contacts_fail(self):
        from engineering_pilot.dynamics import evaluate, model_xml
        import mujoco as mj
        p=validate(json.loads(EXAMPLE.read_text()))
        p['torque_limit_nm']=.01
        self.assertEqual(evaluate(p,time.monotonic()+20)['status'],'failed')
        # Deliberately penetrate the floor to verify the collision geometry is active.
        model=mj.MjModel.from_xml_string(model_xml(p,.002).replace('pos="0 0 1"','pos="0 0 0"'))
        data=mj.MjData(model);mj.mj_forward(model,data)
        self.assertGreater(data.ncon,0)
        # Parent/weld filtering must not suppress the non-adjacent payload/link1 pair.
        import math
        model=mj.MjModel.from_xml_string(model_xml(p,.002))
        data=mj.MjData(model);data.qpos[:]=[0,math.pi];mj.mj_forward(model,data)
        self.assertGreater(data.ncon,0)

    def test_actual_export_dynamics_and_repeatable_search(self):
        from engineering_pilot.worker import search
        from engineering_pilot.dynamics import evaluate
        from engineering_pilot.cad import export
        import cadquery as cq
        p=validate(json.loads(EXAMPLE.read_text()))
        first=search(p,time.monotonic()+20);second=search(p,time.monotonic()+20)
        self.assertEqual(first,second)
        self.assertLessEqual(first['evaluations'],76)
        self.assertEqual(len(first['shortlist']),3)
        dynamics=evaluate(p,time.monotonic()+20)
        self.assertEqual(dynamics['status'],'passed',dynamics)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)/'cad'
            result=export(p,directory)
            self.assertEqual(result['status'],'passed')
            solids=cq.importers.importStep(str(directory/'assembly.step')).solids().vals()
            self.assertEqual(len(solids),2)
            self.assertAlmostEqual(sum(s.Volume() for s in solids),95000.,places=5)
            import hashlib,struct
            for name,metadata in result['files'].items():
                content=(directory/name).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(),metadata['sha256'])
                if name.endswith('.stl'):
                    self.assertGreater(struct.unpack('<I',content[80:84])[0],0)

if __name__=='__main__': unittest.main()
