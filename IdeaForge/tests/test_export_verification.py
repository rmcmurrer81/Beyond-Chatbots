"""Exact-byte CAD/STL validation, corruption and fail-closed regressions."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from engineering_pilot import mesh_verify as v

HAS_STACK=all(importlib.util.find_spec(x) for x in ('cadquery','trimesh','numpy'))


@unittest.skipUnless(HAS_STACK,'optional CadQuery/Trimesh stack unavailable')
class ExportVerificationTests(unittest.TestCase):
    def setUp(self):
        from engineering_pilot.cad import export
        from engineering_pilot.schema import validate
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'cad'
        sample=Path(__file__).resolve().parents[1]/'engineering_pilot/examples/two_link.json'
        self.p=validate(json.loads(sample.read_text()))
        self.result=export(self.p,self.root)
        self.path=self.root/'link_1.stl'
        self.manifest=json.loads((self.root/'link_1.stl.manifest.json').read_text())
        self.raw=self.path.read_bytes()

    def verify_changed(self,raw,manifest=None):
        self.path.write_bytes(raw)
        manifest=copy.deepcopy(manifest or self.manifest)
        manifest['file_sha256']=hashlib.sha256(raw).hexdigest()
        result=v.verify(self.path,manifest)
        self.assertEqual(self.path.read_bytes(),raw,'Verifier changed artifact bytes')
        return result

    def records(self):
        import numpy as np
        return np.frombuffer(self.raw[84:],dtype=[('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attribute','<u2')]).copy()

    def binary(self,records):return self.raw[:80]+struct.pack('<I',len(records))+records.tobytes()

    def test_real_cuboids_pass_with_correct_volumes_and_assembly_frames(self):
        self.assertEqual(self.result['status'],'passed')
        a,b=self.result['export_verification']
        self.assertAlmostEqual(a['volume'],50000);self.assertAlmostEqual(b['volume'],45000)
        self.assertEqual(a['bounds_coordinates'][0][0],0);self.assertEqual(b['bounds_coordinates'][0][0],200)
        self.assertEqual(b['bounds_coordinates'][1][0],380)
        self.assertEqual(a['parameter_sha256'],v.parameter_hash(self.p))
        self.assertEqual(a['sha256'],hashlib.sha256(self.raw).hexdigest())
        self.assertIn('physical safety unknown',a['meaning'])

    def test_missing_face_fails_without_repair(self):
        self.assertEqual(self.verify_changed(self.binary(self.records()[:-1]))['status'],'failed')

    def test_reversed_winding_fails_without_repair(self):
        records=self.records();records['vertices']=records['vertices'][:,::-1,:]
        self.assertEqual(self.verify_changed(self.binary(records))['status'],'failed')

    def test_nonfinite_vertices_and_normals_fail(self):
        for field in ('vertices','normal'):
            records=self.records();records[field].flat[0]=float('nan')
            self.assertEqual(self.verify_changed(self.binary(records))['status'],'failed')

    def test_scale_error_and_wrong_placement_fail(self):
        for scale,offset in [(1000,0),(1,10)]:
            records=self.records();records['vertices']=records['vertices']*scale+offset
            self.assertEqual(self.verify_changed(self.binary(records))['status'],'failed')

    def test_swapped_part_and_truncation_fail(self):
        self.assertEqual(self.verify_changed((self.root/'link_2.stl').read_bytes())['status'],'failed')
        self.assertEqual(self.verify_changed(self.raw[:-1])['status'],'failed')

    def test_duplicate_and_degenerate_triangles_fail(self):
        import numpy as np
        records=self.records()
        self.assertEqual(self.verify_changed(self.binary(np.concatenate([records,records[:1]])))['status'],'failed')
        records=self.records();records['vertices'][0,1]=records['vertices'][0,0]
        self.assertEqual(self.verify_changed(self.binary(records))['status'],'failed')

    def test_missing_units_hash_and_part_identity_fail(self):
        for key,value in [('unit',None),('unit','m'),('part_id','link_2'),('parameter_sha256','bad'),('file_sha256','0'*64)]:
            manifest=copy.deepcopy(self.manifest);manifest[key]=value
            self.assertEqual(v.verify(self.path,manifest)['status'],'failed')
        manifest=copy.deepcopy(self.manifest);del manifest['unit']
        self.assertEqual(v.verify(self.path,manifest)['status'],'failed')

    def test_manifest_boolean_bounds_and_nan_volume_fail(self):
        manifest=copy.deepcopy(self.manifest);manifest['bounds_mm'][0][0]=False
        self.assertEqual(v.verify(self.path,manifest)['status'],'failed')
        manifest=copy.deepcopy(self.manifest);manifest['volume_mm3']=float('nan')
        self.assertEqual(v.verify(self.path,manifest)['status'],'failed')

    def test_missing_dependency_and_file_return_unknown(self):
        with patch.object(v,'inspect_stl',side_effect=ImportError('trimesh missing')):
            self.assertEqual(v.verify(self.path,self.manifest)['status'],'unknown')
        self.path.unlink();self.assertEqual(v.verify(self.path,self.manifest)['status'],'unknown')

    def test_oversize_and_symlink_fail_closed(self):
        with patch.object(v,'MAX_BYTES',100):self.assertEqual(v.verify(self.path,self.manifest)['status'],'failed')
        other=self.root/'copy.stl';other.write_bytes(self.raw);self.path.unlink();self.path.symlink_to(other)
        self.assertEqual(v.verify(self.path,self.manifest)['status'],'failed')

    def test_strict_ascii_file_and_invalid_grammar(self):
        triangles,_=v.read_triangles(self.raw)
        lines=['solid test']
        for triangle in triangles:
            lines+=['facet normal 0 0 0','outer loop']
            lines+=['vertex '+' '.join(map(str,vertex)) for vertex in triangle]
            lines+=['endloop','endfacet']
        lines+=['endsolid test']
        raw='\n'.join(lines).encode()
        self.assertEqual(self.verify_changed(raw)['status'],'passed')
        self.assertEqual(self.verify_changed(raw.replace(b'outer loop',b'not a loop',1))['status'],'failed')

    def test_artifact_mutation_during_validation_fails(self):
        inspect=v.inspect_stl
        def mutate(path):
            result=inspect(path);path.write_bytes(self.raw+b'x');return result
        with patch.object(v,'inspect_stl',side_effect=mutate):
            self.assertEqual(v.verify(self.path,self.manifest)['status'],'failed')

    def test_export_propagates_gate_failure(self):
        from engineering_pilot.cad import export
        with patch('engineering_pilot.cad.verify',side_effect=lambda path,manifest:{'status':'failed','part_id':manifest['part_id'],'sha256':manifest['file_sha256']}):
            result=export(self.p,self.root.parent/'bad-export')
        self.assertEqual(result['status'],'failed')

    def test_general_inspector_accepts_multibody_but_pilot_gate_rejects(self):
        import numpy as np
        records=self.records();other=self.records();other['vertices'][:,:,0]+=500
        raw=self.binary(np.concatenate([records,other]))
        self.path.write_bytes(raw)
        details,_=v.inspect_stl(self.path)
        self.assertEqual(details['connected_bodies'],2)
        self.assertTrue(details['watertight']);self.assertTrue(details['positive_volume'])
        self.assertEqual(self.verify_changed(raw)['status'],'failed')

    def test_export_rejects_persisted_manifest_mutation_after_verification(self):
        from engineering_pilot.cad import export
        verify=v.verify
        def mutate(path,manifest):
            result=verify(path,manifest)
            persisted=path.with_name(path.name+'.manifest.json')
            changed=json.loads(persisted.read_text());changed['parameter_sha256']='0'*64
            persisted.write_text(json.dumps(changed))
            return result
        with patch('engineering_pilot.cad.verify',side_effect=mutate):
            result=export(self.p,self.root.parent/'changed-manifest')
        self.assertEqual(result['status'],'failed')
        self.assertTrue(all(r['reason']=='Manifest changed after geometry validation' for r in result['export_verification']))

    def test_export_level_missing_verifier_dependency_remains_unknown(self):
        from engineering_pilot.cad import export
        with patch.object(v,'inspect_stl',side_effect=ImportError('trimesh unavailable')):
            result=export(self.p,self.root.parent/'missing-dependency')
        self.assertEqual(result['status'],'unknown')
        self.assertTrue(all(r['status']=='unknown' for r in result['export_verification']))
        self.assertTrue(all('trimesh unavailable' in r['reason'] for r in result['export_verification']))

    def test_same_bounds_volume_but_nonboundary_facets_fail(self):
        # An arbitrary warped face cannot pass merely by retaining overall extents.
        records=self.records();records['vertices'][0,0,0]+=1
        self.assertEqual(self.verify_changed(self.binary(records))['status'],'failed')


if __name__=='__main__':unittest.main()
