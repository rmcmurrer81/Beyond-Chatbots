"""Mechanical contract checks, not assertions of general visual competence."""
import base64
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from experiments.temporal_vision import scenes
from experiments.temporal_vision.scoring import Evaluator, summarize
from experiments.temporal_vision.tracker import MAX_FRAMES, MODES, Tracker, canonical
from experiments.vision_lab.scenes import draw

ROOT=Path(__file__).resolve().parents[1]


def image(objects=()):
    return draw(objects,0,0,0,random.Random(1))[0]


def one(x=20,color='red'):
    return image([(color,'square',x,24,3,224)])


def prediction(tid,status='continued',box=(17,21,24,28)):
    return {'box':list(box),'track_id':tid,'identity_status':status}


def truth_frame(ms=0,identity='a',ambiguous=False):
    return scenes.Frame(ms,one(),({'box':[17,21,24,28],'truth_id':identity},),(),(identity,) if ambiguous else ())


class TrackingTests(unittest.TestCase):
    def test_closed_modes(self):
        with self.assertRaises(ValueError):Tracker('oracle')

    def test_operational_signature(self):
        self.assertEqual(list(inspect.signature(Tracker.observe).parameters),['self','raw','timestamp_ms'])
        code=(ROOT/'experiments/temporal_vision/tracker.py').read_text()
        for forbidden in ('from .scenes','from .scoring','truth_id','classifier','network.predict'):
            self.assertNotIn(forbidden,code)

    def test_invalid_frame_and_timestamp_are_atomic(self):
        t=Tracker();t.observe(one(),100);before=t.to_bytes()
        for stamp in (-1,100,99,True,1.5,float('nan'),float('inf'),None,1_000_000_001):
            with self.assertRaises(ValueError):t.observe(one(),stamp)
            self.assertEqual(t.to_bytes(),before)
        for raw in (b'',bytearray(12288),b'x'*12289,None):
            with self.assertRaises(ValueError):t.observe(raw,200)
            self.assertEqual(t.to_bytes(),before)

    def test_single_continuity_and_motion(self):
        t=Tracker();ids=[]
        for i in range(5):ids.append(t.observe(one(20+i),i*100)['predictions'][0]['track_id'])
        self.assertEqual(ids,[1]*5)
        self.assertEqual(t.tracks[0].vx,.01)

    def test_brief_blank_keeps_identity(self):
        t=Tracker();t.observe(one(),0);t.observe(one(22),100)
        self.assertFalse(t.observe(image(),200)['predictions'])
        self.assertEqual(t.observe(one(26),300)['predictions'][0]['track_id'],1)

    def test_long_gap_starts_new_identity(self):
        t=Tracker();t.observe(one(),0)
        p=t.observe(one(),900)['predictions'][0]
        self.assertEqual(p['track_id'],2);self.assertEqual(p['identity_status'],'new')

    def test_reset_never_reuses_identity_number(self):
        t=Tracker('reset')
        self.assertEqual([t.observe(one(),i*100)['predictions'][0]['track_id'] for i in range(4)],[1,2,3,4])

    def test_new_source_requires_fresh_instance(self):
        a=Tracker();a.observe(one(),100)
        b=Tracker();self.assertEqual(b.observe(one(40),0)['predictions'][0]['identity_status'],'new')

    def test_ambiguous_same_appearance_gap_abstains(self):
        raw=image([('red','square',23,30,3,224),('red','square',42,30,3,224)])
        t=Tracker();t.observe(raw,0);t.observe(image(),100)
        p=t.observe(raw,600)['predictions']
        self.assertEqual([x['track_id'] for x in p],[None,None])
        self.assertTrue(all(x.ambiguous for x in t.tracks))
        self.assertEqual([x['track_id'] for x in t.observe(raw,700)['predictions']],[None,None])

    def test_different_appearance_gap_can_recover(self):
        raw=image([('red','square',23,30,3,224),('blue','square',42,30,3,224)])
        t=Tracker();t.observe(raw,0);t.observe(image(),100)
        self.assertEqual([p['track_id'] for p in t.observe(raw,600)['predictions']],[1,2])

    def test_frame_cap(self):
        t=Tracker()
        for i in range(MAX_FRAMES):t.observe(image(),i)
        before=t.to_bytes()
        with self.assertRaises(ValueError):t.observe(image(),MAX_FRAMES)
        self.assertEqual(t.to_bytes(),before)

    def test_no_predicted_hidden_detection(self):
        t=Tracker();t.observe(one(),0)
        self.assertEqual(t.observe(image(),100)['predictions'],[])
        self.assertEqual(len(t.tracks),1)

    def test_capacity_bounded(self):
        t=Tracker('nearest_position')
        for i in range(32):
            t.observe(image([('red','square',x,y,1,224) for x in (8,24,40,56) for y in (8,56)]),i*100)
            self.assertLessEqual(len(t.tracks),16)
            self.assertLessEqual(len(t.to_bytes()),16384)

    def test_prefix_invariance(self):
        prefix=[one(20+i) for i in range(4)]
        a=Tracker();b=Tracker()
        pa=[a.observe(raw,i*100) for i,raw in enumerate(prefix)]
        pb=[b.observe(raw,i*100) for i,raw in enumerate(prefix)]
        a.observe(one(50),400);b.observe(image(),400)
        self.assertEqual(pa,pb)


class PersistenceTests(unittest.TestCase):
    def test_roundtrip_all_modes(self):
        for mode in MODES:
            a=Tracker(mode);a.observe(one(),0);a.observe(one(22),100)
            b=Tracker.from_bytes(a.to_bytes())
            self.assertEqual(a.to_bytes(),b.to_bytes())
            self.assertEqual(a.observe(one(24),200),b.observe(one(24),200))
            self.assertEqual(a.to_bytes(),b.to_bytes())

    def test_black_on_bright_background_roundtrip(self):
        raw=draw([('red','square',20,20,3,0)],205,0,0,random.Random(1))[0]
        a=Tracker();self.assertEqual(len(a.observe(raw,0)['predictions']),1)
        self.assertEqual(a.tracks[0].color,(0,0,0))
        b=Tracker.from_bytes(a.to_bytes())
        self.assertEqual(a.observe(raw,100),b.observe(raw,100))
        self.assertEqual(a.to_bytes(),b.to_bytes())

    def test_empty_roundtrip(self):
        a=Tracker();self.assertEqual(Tracker.from_bytes(a.to_bytes()).to_bytes(),a.to_bytes())

    def test_corruption_and_size(self):
        for raw in (b'',b'null',b'[]',b'{}',bytearray(b'{}'),b'x'*16385,b'{"payload":{},"payload":{}}',b'NaN'):
            with self.assertRaises(ValueError):Tracker.from_bytes(raw)
        t=Tracker();raw=t.to_bytes().replace(b'motion_',b'notion_')
        with self.assertRaises(ValueError):Tracker.from_bytes(raw)

    def test_schema_and_state_bounds_even_with_recomputed_digest(self):
        t=Tracker();t.observe(one(),100)
        base=json.loads(t.to_bytes())['payload']
        mutations=[('frames',True),('frames',65),('next_id',1),('next_id',513),('last_ms',0),('schema','v2'),('mode','oracle')]
        for key,value in mutations:
            p=dict(base);p[key]=value
            raw=canonical({'payload':p,'sha256':hashlib.sha256(canonical(p)).hexdigest()})
            with self.assertRaises(ValueError):Tracker.from_bytes(raw)
        for key,value in [('id',True),('area',0),('x',65),('last_ms',101),('vx',.05),('color',[0.1,0,0]),('observations',2),('ambiguous',1)]:
            p=json.loads(json.dumps(base));p['tracks'][0][key]=value
            raw=canonical({'payload':p,'sha256':hashlib.sha256(canonical(p)).hexdigest()})
            with self.assertRaises(ValueError):Tracker.from_bytes(raw)

    def test_cold_actual_process_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);t=Tracker();t.observe(one(),0);t.observe(image(),100)
            (d/'state').write_bytes(t.to_bytes())
            (d/'input').write_text(json.dumps([{'timestamp_ms':200,'rgb':base64.b64encode(one(22)).decode()}]))
            expected=t.observe(one(22),200)
            child=subprocess.run([sys.executable,'-B','-m','experiments.temporal_vision.cold',str(d/'state'),str(d/'input'),str(d/'out')],cwd=ROOT,capture_output=True,text=True,timeout=20)
            self.assertEqual(child.returncode,0,child.stderr)
            result=json.loads((d/'out').read_text())
            self.assertEqual(result['predictions'],[json.loads(json.dumps(expected))])
            self.assertEqual(result['checkpoint'],t.to_bytes().decode())


class EvaluationTests(unittest.TestCase):
    def test_all_abstain_is_zero_coverage(self):
        e=Evaluator();e.score([prediction(None)],truth_frame());e.score([prediction(None)],truth_frame(100))
        self.assertEqual(summarize(e.counts)['continuity_coverage'],0)
        self.assertEqual(e.counts['identity_abstentions'],1)

    def test_reset_has_fragments_no_recovery(self):
        e=Evaluator();e.score([prediction(1,'new')],truth_frame());e.score([prediction(2,'new')],truth_frame(100))
        self.assertEqual(e.counts['correct_continuations'],0);self.assertEqual(e.counts['fragments'],1)
        self.assertEqual(e.recovery([{'truth_id':'a','pre_ms':0,'first_ms':100,'deadline_ms':300,'ambiguous':False}])[0]['on_time_success'],False)

    def test_switch_contamination_does_not_relabel_track(self):
        e=Evaluator();e.score([prediction(1,'new')],truth_frame(identity='a'))
        e.score([prediction(1)],truth_frame(100,identity='b'))
        self.assertEqual(e.owner[1],'a');self.assertEqual(e.counts['contaminated_instances'],1)

    def test_missed_identity_stays_in_denominator(self):
        e=Evaluator();e.score([prediction(1,'new')],truth_frame());e.score([],truth_frame(100))
        self.assertEqual(e.counts['eligible_identity'],1);self.assertEqual(e.counts['identity_misses'],1)
        self.assertEqual(summarize(e.counts)['correct_continuation_recall'],0)

    def test_ambiguous_lucky_match_still_unsafe(self):
        e=Evaluator();e.score([prediction(1,'new')],truth_frame())
        e.score([prediction(1)],truth_frame(100,ambiguous=True))
        self.assertEqual(e.counts['ambiguous_prior_claims'],1)

    def test_first_grounded_continued_handle_is_acquisition(self):
        e=Evaluator();e.score([],truth_frame())
        e.score([prediction(1,'continued')],truth_frame(100))
        self.assertEqual(e.counts['correct_continuations'],0)
        self.assertEqual(e.counts['first_acquisitions'],1)
        self.assertEqual(e.counts['unanchored_continuations'],1)

    def test_first_postambiguity_detection_is_not_prior_claim(self):
        e=Evaluator();e.score([],truth_frame())
        e.score([prediction(1,'new')],truth_frame(100,ambiguous=True))
        e.score([prediction(1)],truth_frame(200,ambiguous=True))
        self.assertEqual(e.counts['ambiguous_prior_claims'],0)

    def test_unanchored_fragment_is_not_wrong_known_owner(self):
        e=Evaluator();e.score([prediction(1,'new')],truth_frame())
        e.score([prediction(2,'new')],truth_frame(100))
        e.score([prediction(2)],truth_frame(200))
        self.assertEqual(e.counts['wrong_continuations'],0)
        self.assertEqual(e.counts['unanchored_continuations'],1)

    def test_failure_retains_completed_frame_and_exact_stage(self):
        from experiments.temporal_vision.run import experiment
        sequence=scenes.Sequence('injected','separated',(truth_frame(),truth_frame(100)),(),{})
        original=Tracker.observe
        def observed(tracker,raw,ts):
            if ts==100: raise RuntimeError('injected failure after first completed frame')
            return original(tracker,raw,ts)
        with tempfile.TemporaryDirectory() as td, mock.patch('experiments.temporal_vision.run.models',return_value={}), mock.patch('experiments.temporal_vision.run.scenes.sequences',return_value=(sequence,)), mock.patch.object(Tracker,'observe',observed):
            output=Path(td)/'failed'
            with self.assertRaisesRegex(RuntimeError,'injected failure'):experiment(output,'development')
            result=json.loads((output/'result.json').read_text())
            self.assertFalse(result['completed']);self.assertEqual(result['completed_frames'],1)
            self.assertEqual(result['phase'],'tracking');self.assertEqual(result['timestamp_ms'],100)
            self.assertEqual(len((output/'frames.jsonl').read_text().splitlines()),1)

    def test_dependency_hash_closure(self):
        from experiments.temporal_vision.run import sources
        hashes=sources()
        for path in ('experiments/vision_lab/scenes.py','experiments/vision_lab/run.py','experiments/vision_lab/PROTOCOL.json','vendor/newbrain_vision/cbf43167b2a9f3df7b61c1e0d9497d26115a2c94/visual_model.py','vendor/newbrain_vision/cbf43167b2a9f3df7b61c1e0d9497d26115a2c94/manifest.json'):
            self.assertIn(path,hashes)

    def test_recovery_late_is_not_ontime(self):
        e=Evaluator();e.score([prediction(1,'new')],truth_frame());e.score([],truth_frame(100));e.score([prediction(1)],truth_frame(400))
        event=e.recovery([{'truth_id':'a','pre_ms':0,'first_ms':100,'deadline_ms':300,'ambiguous':False}])[0]
        self.assertFalse(event['on_time_success']);self.assertEqual(event['recovered_ms'],400)

    def test_detection_matching_ignores_identity(self):
        a=Evaluator();b=Evaluator()
        ra=a.score([prediction(1)],truth_frame(identity='a'))
        rb=b.score([prediction(777)],truth_frame(identity='unseen_name'))
        self.assertEqual(ra['matches'],rb['matches'])

    def test_development_twins_exact_and_outputs_equal(self):
        seq=scenes.sequences('development')
        for variant in range(2):
            stay=next(s for s in seq if s.sequence_id==f'development-ambiguous_stay-{variant:02}')
            swap=next(s for s in seq if s.sequence_id==f'development-ambiguous_swap-{variant:02}')
            self.assertEqual(scenes.stream_digest(stay),scenes.stream_digest(swap))
            self.assertNotEqual(stay.frames[12].objects,swap.frames[12].objects)
            a=Tracker();b=Tracker()
            self.assertEqual([a.observe(f.rgb,f.timestamp_ms) for f in stay.frames],[b.observe(f.rgb,f.timestamp_ms) for f in swap.frames])

    def test_no_fully_hidden_detection_targets(self):
        s=next(s for s in scenes.sequences('development') if s.family=='occlusion')
        for f in s.frames:
            self.assertFalse(set(f.hidden_ids)&{o['truth_id'] for o in f.objects})

    def test_no_heldout_execution_in_mechanical_suite(self):
        # Mechanical generation uses development only. Heldout appears only in
        # runner command choices until the independent source review freeze.
        self.assertEqual(len(scenes.sequences('development')),18)

    def test_no_production_activation(self):
        from aster.backend import status
        self.assertFalse(status()['available'])
        for path in (ROOT/'aster').glob('*.py'):
            self.assertNotIn('temporal_vision',path.read_text(encoding='utf-8'))

    def test_existing_output_refused_before_classifier_load(self):
        from experiments.temporal_vision.run import experiment
        with tempfile.TemporaryDirectory() as d,mock.patch('experiments.temporal_vision.run.models',side_effect=AssertionError('no')):
            with self.assertRaises(FileExistsError):experiment(Path(d),'development')


if __name__=='__main__':unittest.main()
