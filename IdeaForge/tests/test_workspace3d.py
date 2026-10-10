"""No native display, network, model, physics engine or fabricated project geometry."""
import copy
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from workspace3d.model import demo, validate, world_vertices, bounds, digest, load
from workspace3d.checks import run_checks
from workspace3d.store import Store, StaleProposal, compare
from workspace3d.jobs import queue_refresh, run_one
from workspace3d.adapters import gather
from workspace3d.requirements import manifest


class SceneTests(unittest.TestCase):
    def test_example_has_explicit_example_provenance(self):
        scene=validate(demo())
        self.assertTrue(all(p['provenance']['status']=='example' for p in scene['parts']))

    def test_invalid_units_dimensions_and_duplicate_ids(self):
        for mutate in (lambda s:s.update(units='m'),
                       lambda s:s['parts'][0]['size_mm'].__setitem__(0,0),
                       lambda s:s['parts'][0]['size_mm'].__setitem__(0,True),
                       lambda s:s['parts'][0]['position_mm'].__setitem__(0,math.inf),
                       lambda s:s['parts'][1].update(id='base'),
                       lambda s:s['parts'][1].update(parent='missing'),
                       lambda s:s['parts'][0].update(parent='arm'),
                       lambda s:s['parts'][0].update(provenance={}),
                       lambda s:s['parts'][2]['joint'].update(angle_deg=100)):
            scene=demo(); mutate(scene)
            with self.assertRaises(ValueError): validate(scene)

    def test_joint_and_hierarchy_work_limits(self):
        scene=demo(); base=scene['parts'][2]
        scene['parts']=[]
        for index in range(9):
            part=copy.deepcopy(base); part['id']=f'p{index}'; part.pop('parent',None)
            scene['parts'].append(part)
        with self.assertRaises(ValueError): validate(scene)
        for index,part in enumerate(scene['parts']):
            part.pop('joint',None)
            if index: part['parent']=f'p{index-1}'
        with self.assertRaises(ValueError): validate(scene)

    def test_bad_requirement_cycle_is_rejected(self):
        scene=demo(); scene['requirements']={'goal':'Custom', 'subsystems':[
            {'id':'a','goal':'A','depends_on':['b']},{'id':'b','goal':'B','depends_on':['a']}]}
        with self.assertRaises(ValueError): validate(scene)

    def test_world_transforms_really_assemble_hierarchy(self):
        scene=demo(); meshes=world_vertices(scene)
        low,high=bounds(meshes['arm'][0])
        self.assertAlmostEqual((low[2]+high[2])/2,51)
        rotated=world_vertices(scene,{'arm':90})
        low,high=bounds(rotated['arm'][0])
        self.assertAlmostEqual(high[0]-low[0],20)
        self.assertAlmostEqual(high[1]-low[1],140)

    def test_checks_find_real_overlap_and_printer_fit(self):
        scene=demo(); scene['parts'][1]['position_mm']=[0,0,0]
        scene['printer_volume_mm']=[100,100,100]
        result=run_checks(scene)
        self.assertIn(['base','bearing'],result['possible_aabb_overlaps'])
        self.assertIsNone(result['printer_fit'][0]['axis_aligned_fit'])
        self.assertEqual(result['printer_fit'][0]['receipt']['result']['status'],'unknown')
        self.assertEqual(len(result['joint_sweeps'][0]['samples']),9)
        self.assertIn('Dynamics unavailable', ' '.join(result['limitations']))

    def test_empty_does_not_report_simulation_success(self):
        self.assertEqual(run_checks({'schema_version':1,'units':'mm','parts':[]})['status'],'missing_geometry')

    def test_checks_do_not_mutate_scene(self):
        scene=demo(); original=copy.deepcopy(scene); run_checks(scene)
        self.assertEqual(scene,original)

    def test_requirements_do_not_claim_fiction_is_real(self):
        value=manifest({'name':'Iron Man suit'})
        self.assertEqual(value['status'],'requirements_only_not_validated')
        self.assertIn('power',value['subsystems'][-1]['depends_on'])
        self.assertIn('not established',manifest({'name':'Star Trek holodeck'})['inspiration'])


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.store=Store(self.root)

    def add(self, scene=None, parent=None, reason='test'):
        scene=scene or demo()
        return self.store.add(scene,reason,[],run_checks(scene),expected_parent=parent)

    def test_no_overwrite_atomic_history_and_baseline(self):
        a=self.add(); self.store.accept(a)
        scene=demo(); scene['parts'][0]['size_mm'][0]=130
        b=self.add(scene,a)
        self.assertNotEqual(a,b)
        self.assertEqual(self.store.pointer('accepted'),a)
        self.assertEqual(self.store.revision(a)['scene']['parts'][0]['size_mm'][0],120)
        self.assertEqual(Store(self.root).pointer(),b)

    def test_stale_proposal_rejected(self):
        self.add()
        with self.assertRaises(StaleProposal): self.add(reason='stale')
        self.assertEqual(len(self.store.history()),1)

    def test_test_hash_must_match_revision(self):
        scene=demo(); tests=run_checks(scene); scene['parts'][0]['size_mm'][0]=140
        with self.assertRaises(ValueError): self.store.add(scene,'bad',[],tests,expected_parent=None)

    def test_lease_recovery_survives_restart(self):
        self.store.enqueue({'scene':demo()})
        first=self.store.claim(lease_seconds=-1)
        second=Store(self.root).claim()
        self.assertEqual(first['id'],second['id']); self.assertNotEqual(first['token'],second['token'])
        self.store.finish(first)
        self.assertEqual(self.store.job_status()[0]['state'],'running')
        self.store.finish(second)
        self.assertEqual(self.store.job_status()[0]['state'],'done')

    def test_active_lease_not_stolen(self):
        self.store.enqueue({'scene':demo()}); self.assertIsNotNone(self.store.claim())
        self.assertIsNone(Store(self.root).claim())

    def test_polling_deduplicates_after_new_revision(self):
        path=self.root/'design'; path.mkdir()
        (path/'assembly.json').write_text(json.dumps(demo()))
        first=queue_refresh(self.root); self.assertTrue(run_one(self.root))
        second=queue_refresh(self.root)
        self.assertEqual(first,second); self.assertFalse(run_one(self.root))
        self.assertEqual(len(self.store.history()),1)

    def test_new_research_creates_revision_without_invented_geometry(self):
        folder=self.root/'design'; folder.mkdir(); (folder/'assembly.json').write_text(json.dumps(demo()))
        queue_refresh(self.root); run_one(self.root); before=self.store.revision()
        folder=self.root/'research'; folder.mkdir(); (folder/'research.json').write_text('{"papers":[{"title":"New motor"}]}')
        queue_refresh(self.root); run_one(self.root); after=self.store.revision()
        self.assertNotEqual(before['id'],after['id'])
        self.assertEqual(before['scene']['parts'],after['scene']['parts'])
        self.assertTrue(after['sources'])

    def test_unverified_measurements_never_become_geometry(self):
        folder=self.root/'candidate_updates'; folder.mkdir()
        (folder/'extracted_specs.json').write_text('{"records":[{"measurements":[{"value":150,"unit":"mm","status":"machine_extracted_unverified"}]}]}')
        self.assertEqual(gather(self.root)['scene']['parts'],[])

    def test_stale_queued_geometry_does_not_replace_user_edit(self):
        queue_refresh(self.root)
        user=self.add()
        run_one(self.root)
        self.assertEqual(self.store.pointer(),user)
        self.assertEqual(self.store.job_status()[0]['state'],'error')

    def test_restore_creates_new_revision(self):
        a=self.add(); scene=demo(); scene['parts'][0]['size_mm'][0]=200
        b=self.add(scene,a)
        c=self.add(self.store.revision(a)['scene'],b,'restored')
        self.assertEqual(len(self.store.history()),3)
        self.assertEqual(self.store.revision(c)['scene'],self.store.revision(a)['scene'])
        self.assertEqual(compare(self.store.revision(a)['scene'],scene)['changed'],['base'])

    def test_bad_input_does_not_erase_revision(self):
        saved=self.add(); folder=self.root/'design'; folder.mkdir()
        (folder/'assembly.json').write_text('{bad')
        with self.assertRaises(ValueError): queue_refresh(self.root)
        self.assertEqual(self.store.pointer(),saved)

    def test_manual_input_is_transactional_and_not_replaced_by_old_file(self):
        scene=demo(); folder=self.root/'design'; folder.mkdir()
        (folder/'assembly.json').write_text(json.dumps(scene))
        scene['parts'][0]['size_mm'][0]=777
        rid=self.store.add(scene,'manual',[],run_checks(scene),expected_parent=None,as_input=True)
        self.assertEqual(self.store.pointer('input'),rid)
        self.assertEqual(gather(self.root)['scene']['parts'][0]['size_mm'][0],777)

    def test_custom_requirements_survive_automatic_refresh(self):
        scene=demo(); scene['requirements']={'origin':'user_authored','goal':'My new machine',
            'subsystems':[{'id':'custom','goal':'Novel subsystem','depends_on':[],
                          'research_questions':['What evidence supports this mechanism?']}]}
        self.store.add(scene,'custom',[],run_checks(scene),expected_parent=None,as_input=True)
        self.assertEqual(gather(self.root)['scene']['requirements'],scene['requirements'])

    def test_crash_after_revision_before_job_finish_is_idempotent(self):
        queue_refresh(self.root); job=self.store.claim(lease_seconds=-1)
        payload=job['payload']
        fingerprint=digest({k:v for k,v in payload.items() if k!='base_revision'})
        rid=self.store.add(payload['scene'],payload['reason'],payload['sources'],run_checks(payload['scene']),
                           expected_parent=None,fingerprint=fingerprint)
        self.assertTrue(run_one(self.root))
        self.assertEqual(self.store.pointer(),rid)
        self.assertEqual(len(self.store.history()),1)
        self.assertEqual(self.store.job_status()[0]['state'],'done')

    def test_save_input_is_readable_and_preserves_scene(self):
        from workspace3d.viewer import save_input
        save_input(self.root,demo())
        self.assertEqual(load(self.root/'workspace3d'/'assembly.json'),demo())


class ProjectionTests(unittest.TestCase):
    def test_actual_viewer_draws_geometry_and_rotates_without_native_display(self):
        from workspace3d.viewer import Workspace
        class Canvas:
            def __init__(self): self.lines=[]
            def delete(self,*a): self.lines=[]
            def winfo_width(self): return 900
            def winfo_height(self): return 600
            def create_line(self,*a,**k): self.lines.append(a)
            def create_text(self,*a,**k): pass
        class Flag:
            def get(self): return False
        viewer=Workspace.__new__(Workspace)
        viewer.destroyed=False; viewer.canvas=Canvas(); viewer.scene=demo()
        viewer.preview=Flag(); viewer.exploded=Flag(); viewer.yaw=-35; viewer.pitch=25
        viewer.zoom=1; viewer.pan=[0,0]; viewer.selected=None
        viewer.draw(); original=viewer.canvas.lines[:]
        self.assertGreater(len(original),30)
        viewer.yaw+=45; viewer.draw()
        self.assertNotEqual(original,viewer.canvas.lines)
        self.assertTrue(all(math.isfinite(v) for line in viewer.canvas.lines for v in line))


if __name__=='__main__': unittest.main()
