"""Mechanical tests; these assertions do not establish perception accuracy."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from experiments.vision_lab import pixels,scoring,scenes
from experiments.vision_lab.source import ROOT,VENDOR


class PixelTests(unittest.TestCase):
    def raw(self,objects=(),**kwargs):
        import random
        return scenes.draw(objects,kwargs.pop('bg',0),0,0,random.Random(7),**kwargs)[0]

    def test_invalid_frames(self):
        for raw in (None,bytearray(12288),b'',b'0'*12287,b'0'*12289):
            with self.assertRaises(ValueError):pixels.extract(raw)

    def test_blank(self):
        c,r=pixels.extract(self.raw(bg=65));self.assertEqual(c,());self.assertEqual(r['reason'],'no_component')

    def test_separated_components_boxes(self):
        c,_=pixels.extract(self.raw([('red','square',15,31,5,224),('blue','square',47,31,5,224)],bg=205))
        self.assertEqual([x.box for x in c],[(10,26,21,37),(42,26,53,37)])
        self.assertTrue(all(len(x.pixels)==3072 for x in c))

    def test_touching_is_one_component_not_two_claim(self):
        c,_=pixels.extract(self.raw([('red','square',24,31,7,224),('blue','square',39,31,7,224)]))
        self.assertEqual(len(c),1)

    def test_min_area_discard(self):
        raw=bytearray(12288);raw[3*100:3*100+3]=b'\xff\0\0'
        c,r=pixels.extract(bytes(raw));self.assertEqual(c,());self.assertEqual(r['discarded_small'],1)

    def test_component_overflow_refuses(self):
        objects=[('red','square',x,y,1,224) for x in (8,24,40) for y in (8,24,40)]
        c,r=pixels.extract(self.raw(objects));self.assertEqual(c,());self.assertEqual(r['reason'],'component_limit')

    def test_byte_only_determinism(self):
        raw=self.raw([('green','circle',31,31,7,224)],bg=65)
        self.assertEqual(pixels.extract(raw),pixels.extract(bytes(bytearray(raw))))

    def test_source_metadata_not_in_predict_signature(self):
        import inspect
        from experiments.vision_lab.learner import predict
        self.assertEqual(list(inspect.signature(predict).parameters),['predictor','raw'])

    def test_global_adapter_exact_dimensions(self):
        self.assertEqual(len(pixels.global_patch(bytes(12288))),3072)

    def test_empty_or_invalid_mask(self):
        for indices in ((),(-1,),(4096,),(True,)):
            with self.assertRaises(ValueError):pixels.masked_patch(bytes(12288),indices)


class ScoringTests(unittest.TestCase):
    def obj(self,box,known=True):return {'box':box,'known':known,'color':'red' if known else 'yellow','shape':'square','held_combination':True}
    def pred(self,box,ids=(0,0),accepted=True):return {'box':box,'ids':ids,'accepted':accepted,'abstain':not accepted,'supported':ids[1]<3}

    def test_iou(self):
        self.assertEqual(scoring.iou((0,0,10,10),(0,0,10,10)),1)
        self.assertEqual(scoring.iou((0,0,10,10),(10,0,20,10)),0)

    def test_match_maximizes_count_before_iou(self):
        # p0 can take either; p1 only takes object0. Greedy highest-IoU loses one.
        ps=[self.pred((0,0,15,10)),self.pred((0,0,9,10))]
        obs=[self.obj((0,0,10,10)),self.obj((5,0,15,10))]
        self.assertEqual(set(scoring.match(ps,obs)),{(0,1),(1,0)})

    def test_labels_cannot_affect_matching(self):
        ps=[self.pred((0,0,10,10))];obs=[self.obj((0,0,10,10))]
        first=scoring.match(ps,obs);ps[0]['ids']=(2,2);obs[0]['color']='blue'
        self.assertEqual(first,scoring.match(ps,obs))

    def test_miss_remains_in_known_denominator(self):
        r,_=scoring.score([], [self.obj((0,0,10,10))]);self.assertEqual(r['known'],1);self.assertEqual(r['fn'],1);self.assertEqual(r['exact_frame'],0)

    def test_unknown_false_accept_even_bad_localization(self):
        r,_=scoring.score([self.pred((20,20,30,30))],[self.obj((0,0,10,10),False)])
        self.assertEqual(r['unknown_false_accept_frame'],1);self.assertEqual(r['unknown_matched'],0)

    def test_mixed_unknown_unmatched_accept_is_unsafe(self):
        r,_=scoring.score([self.pred((0,0,10,10)),self.pred((25,0,35,10))],[self.obj((0,0,10,10)),self.obj((20,0,30,10),False)])
        self.assertEqual(r['unknown_unsafe_accept_frame'],1);self.assertEqual(r['accepted_spurious'],1)

    def test_unknown_no_detection_is_not_recognized(self):
        r,_=scoring.score([], [self.obj((0,0,10,10),False)])
        self.assertEqual(r['unknown_false_accept_frame'],0);self.assertEqual(r['exact_frame'],0);self.assertEqual(r['fn'],1)

    def test_spurious_prediction_breaks_exact_frame(self):
        r,_=scoring.score([self.pred((0,0,10,10))],[]);self.assertEqual(r['exact_frame'],0);self.assertEqual(r['fp'],1)

    def test_fourth_slot_separate_from_unknown_rejection(self):
        r,_=scoring.score([self.pred((0,0,10,10),ids=(0,3),accepted=False)],[self.obj((0,0,10,10))])
        self.assertEqual(r['unsupported'],1);self.assertEqual(r['accepted_correct'],0)

    def test_matching_cap(self):
        with self.assertRaises(ValueError):scoring.match([self.pred((0,0,1,1))]*9,[])


class SourceTests(unittest.TestCase):
    def test_upstream_exact_blobs_and_hashes(self):
        manifest=json.loads((VENDOR/'manifest.json').read_text())
        for name,entry in manifest['files'].items():
            raw=(VENDOR/name).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),entry['sha256'])
            self.assertEqual(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),entry['git_blob_sha1'])
        self.assertEqual(manifest['files']['visual_model.py']['git_blob_sha1'],'b5ea8aa178ade39b1976e999812cc5da458a14b3')
        self.assertEqual(manifest['files']['visual_dataset.py']['git_blob_sha1'],'ae6a3b08a5fcf250ab672b22d06a8e85742f6237')

    def test_production_unavailable(self):
        from aster.backend import status
        self.assertFalse(status()['available']);self.assertIsNone(status()['fallback'])

    def test_no_application_imports_of_experiment(self):
        for path in (ROOT/'aster').glob('*.py'):
            self.assertNotIn('vision_lab',path.read_text(encoding='utf-8'))

    def test_development_split_count_and_source_time(self):
        values=scenes.cases('development')
        self.assertEqual(len(values),192)
        self.assertTrue(all(c.observation.timestamp_ms==c.observation.frame_index*100 for c in values))
        self.assertEqual(len({c.observation.rgb for c in values}),len(values))

    def test_screen_schedule_varies_radius_within_each_shape_and_color(self):
        pairs=[((k+j)%3,(k//3+j)%3,(k//9+j)%3) for k in range(24) for j in range(2+k%3)]
        for axis in (0,1):
            for label in range(3):
                self.assertEqual({r for c,s,r in pairs if (c,s)[axis]==label},{0,1,2})

    def test_closed_split(self):
        with self.assertRaises(ValueError):scenes.cases('user-camera')

    def test_import_does_not_load_numpy_or_camera(self):
        code="import sys; import experiments.vision_lab.pixels; assert 'numpy' not in sys.modules; assert 'cv2' not in sys.modules"
        self.assertEqual(subprocess.run([sys.executable,'-B','-c',code],cwd=ROOT,capture_output=True).returncode,0)

    def test_existing_output_refused_before_load(self):
        from experiments.vision_lab.run import experiment
        with tempfile.TemporaryDirectory() as directory, mock.patch('experiments.vision_lab.run.load',side_effect=AssertionError('must not load')):
            with self.assertRaises(FileExistsError):experiment(Path(directory),'development')


if __name__=='__main__':unittest.main()
