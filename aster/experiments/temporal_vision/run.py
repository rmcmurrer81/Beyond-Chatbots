"""Frozen optional temporal experiment; no live input, training or activation."""
import argparse
import base64
from collections import Counter
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import zipfile

from experiments.vision_lab import learner
from experiments.vision_lab.pixels import extract
from experiments.vision_lab.scoring import score as label_score, total as label_total
from experiments.vision_lab.source import ROOT, load
from experiments.vision_lab.run import peak_memory
from . import scenes
from .scoring import Evaluator, summarize
from .tracker import MODES, Tracker


def digest(raw): return hashlib.sha256(raw).hexdigest()


def write(path, value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def sources():
    selected=[*sorted((ROOT/'experiments/temporal_vision').glob('*.py')),ROOT/'experiments/temporal_vision/PROTOCOL.json',
              ROOT/'experiments/vision_lab/__init__.py',ROOT/'experiments/vision_lab/pixels.py',ROOT/'experiments/vision_lab/scoring.py',
              ROOT/'requirements-vision.txt',ROOT/scenes.PROTOCOL['classifier']['source_archive'],
              ROOT/'experiments/vision_lab/source.py',ROOT/'experiments/vision_lab/learner.py',
              ROOT/'experiments/vision_lab/scenes.py',ROOT/'experiments/vision_lab/PROTOCOL.json',
              ROOT/'experiments/vision_lab/run.py',ROOT/'experiments/vision_lab/cold.py',
              *sorted((ROOT/'vendor/newbrain_vision'/scenes.PROTOCOL['newbrain_pin']).glob('*.py')),
              ROOT/'vendor/newbrain_vision'/scenes.PROTOCOL['newbrain_pin']/'manifest.json',
              ROOT/'tests/test_temporal_vision.py',ROOT/'scripts/record_temporal_vision_checks.py']
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in selected}


def models():
    _,model=load()
    config=scenes.PROTOCOL['classifier'];path=ROOT/config['source_archive']
    raw=path.read_bytes()
    if digest(raw)!=config['archive_sha256']:
        raise ValueError('Frozen classifier source archive mismatch')
    result={}
    with zipfile.ZipFile(path) as z:
        for seed,expected in config['checkpoints'].items():
            info=z.getinfo(f'run/seed-{seed}.bin')
            if info.file_size!=28875: raise ValueError('Classifier size mismatch')
            checkpoint=z.read(info)
            if digest(checkpoint)!=expected: raise ValueError('Classifier fingerprint mismatch')
            network=model.FactorizedModel.from_bytes(checkpoint)
            if network.updates!=320: raise ValueError('Classifier update count mismatch')
            result[seed]=network
    return result


def latency(values, scope):
    ordered=sorted(values)
    return {'scope':scope,'samples':len(values),'total_seconds':sum(values),
            'p50_seconds':ordered[len(ordered)//2] if ordered else None,
            'p95_seconds':ordered[int(.95*(len(ordered)-1))] if ordered else None,
            'max_seconds':max(ordered) if ordered else None}


def experiment(output,split):
    output=Path(output).absolute()
    if any(p.is_symlink() for p in (output,)+tuple(output.parents)):
        raise ValueError('Symlink output refused')
    output.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();manifest=sources()
    write(output/'freeze.json',{'schema':'aster.temporal-freeze.v1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'source_sha256':manifest,'protocol':scenes.PROTOCOL,'split':split,
          'no_evaluation_in_this_invocation_before_freeze':True})
    progress={'schema':'aster.temporal-run.v1','completed':False,'split':split,'completed_frames':0,'completed_sequences':0,
              'production_activated':False,'live_input':False,'training_updates':0,
              'environment':{'python':platform.python_version(),'platform':platform.platform(),'numpy':'2.3.5','threads':1}}
    log=output/'frames.jsonl'; log.open('x').close()
    summary=[];cold_rows=[];twins={};label_rows={};arm_times={a:[] for a in scenes.PROTOCOL['arms']};association_times={a:[] for a in scenes.PROTOCOL['arms']};extraction_times=[];label_times={}
    try:
        progress['phase']='load_frozen_classifiers';networks=models()
        initial={s:n.state_digest() for s,n in networks.items()}
        label_rows={s:[] for s in networks};label_times={s:[] for s in networks}
        progress['phase']='generate_evaluator_streams';dataset=scenes.sequences(split)
        write(output/'inputs.json',{'sequences':[scenes.receipt(s) for s in dataset]})
        dev=scenes.sequences('development')
        held_hashes={scenes.stream_digest(s) for s in dataset}
        dev_hashes={scenes.stream_digest(s) for s in dev}
        overlap=held_hashes & dev_hashes if split=='heldout' else set()
        audit={'unit':'complete observed trajectory; paired ambiguous streams intentionally identical within split',
               'sequences':len(dataset),'frames':sum(len(s.frames) for s in dataset),
               'shared_development_heldout_streams':len(overlap),
               'same_shape_and_motion_families':True,'protocol_sources_frozen_before_generation':True}
        write(output/'split-audit.json',audit)
        if overlap: raise AssertionError('Complete stream overlaps development')
        for sequence in dataset:
            progress.update(phase='tracking',sequence_id=sequence.sequence_id)
            sequence_predictions={}
            for arm in scenes.PROTOCOL['arms']:
                progress['arm']=arm
                tracker=Tracker('motion_appearance' if arm=='shuffled_motion' else arm)
                evaluator=Evaluator();ordered=list(sequence.frames)
                if arm=='shuffled_motion':
                    random.Random(31337).shuffle(ordered)
                    ordered=[scenes.Frame(i*100,f.rgb,f.objects,(),()) for i,f in enumerate(ordered)]
                predictions=[];checkpoint=None;cut=None
                for index,f in enumerate(ordered):
                    progress['timestamp_ms']=f.timestamp_ms
                    began=time.perf_counter();pred=tracker.observe(f.rgb,f.timestamp_ms);elapsed=time.perf_counter()-began
                    arm_times[arm].append(elapsed);association_times[arm].append(tracker.last_latency['association_seconds']);predictions.append(pred)
                    scored=evaluator.score(pred['predictions'],f)
                    row={'sequence_id':sequence.sequence_id,'family':sequence.family,'arm':arm,'timestamp_ms':f.timestamp_ms,
                         'rgb_sha256':digest(f.rgb),'output':pred,'scoring':scored,'tracker_total_seconds':elapsed}
                    with log.open('a',encoding='utf-8',newline='\n') as stream:
                        stream.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
                    progress['completed_frames']+=1
                    # One representative per family; points include before/during
                    # hiding, after ambiguity, and before dropped-content gaps.
                    point={'occlusion':10,'distractor':7,'ambiguous_stay':13,'ambiguous_swap':13,'frame_gap':5}.get(sequence.family,9)
                    if arm=='motion_appearance' and sequence.sequence_id.endswith('-00') and index==point:
                        checkpoint=tracker.to_bytes();cut=index+1
                if arm!='shuffled_motion':
                    sequence_predictions[arm]=predictions
                recovery=evaluator.recovery(sequence.events if arm!='shuffled_motion' else ())
                summary.append({'sequence_id':sequence.sequence_id,'family':sequence.family,'arm':arm,
                                'counts':dict(evaluator.counts),'metrics':summarize(evaluator.counts),'recovery':recovery})
                if checkpoint is not None:
                    progress['phase']='cold_replay'
                    prefix=output/f'cold-{sequence.family}'
                    cp=prefix.with_suffix('.checkpoint.json');cp.write_bytes(checkpoint)
                    inputs=prefix.with_suffix('.inputs.json')
                    write(inputs,[{'timestamp_ms':f.timestamp_ms,'rgb':base64.b64encode(f.rgb).decode('ascii')} for f in ordered[cut:]])
                    result=prefix.with_suffix('.result.json')
                    child=subprocess.run([sys.executable,'-B','-m','experiments.temporal_vision.cold',str(cp),str(inputs),str(result)],
                        cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1'),capture_output=True,text=True,timeout=20)
                    process={'sequence_id':sequence.sequence_id,'returncode':child.returncode,'stdout':child.stdout[-1000:],
                             'stderr':child.stderr[-4000:],'checkpoint_sha256':digest(checkpoint),'replay_frames':len(ordered)-cut}
                    write(prefix.with_suffix('.process.json'),process);child.check_returncode()
                    restored=json.loads(result.read_text(encoding='utf-8'))
                    expected=json.loads(json.dumps(predictions[cut:]))
                    same=restored['predictions']==expected and restored['checkpoint']==tracker.to_bytes().decode('utf-8')
                    if not same: raise AssertionError('Cold suffix/state mismatch')
                    cold_rows.append(dict(process,all_decisions_equal=True,final_state_equal=True,training_updates=0))
                    progress['phase']='tracking'
            # Independent frozen labels share component extraction; they do not
            # affect any association arm. Record all three seeds, never best seed.
            progress['phase']='label_only'
            for f in sequence.frames:
                progress['timestamp_ms']=f.timestamp_ms
                began=time.perf_counter();components,extraction=extract(f.rgb);extraction_times.append(time.perf_counter()-began)
                row={'sequence_id':sequence.sequence_id,'family':sequence.family,'timestamp_ms':f.timestamp_ms,'arm':'frozen_labels','seeds':{}}
                for seed,network in networks.items():
                    began=time.perf_counter();pred=learner.prediction_rows(network,components);label_times[seed].append(time.perf_counter()-began)
                    scored,pairs=label_score(pred,f.objects);label_rows[seed].append(scored)
                    row['seeds'][seed]={'predictions':pred,'metrics':scored,'matches':pairs}
                with log.open('a',encoding='utf-8',newline='\n') as stream:
                    stream.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
                progress['completed_frames']+=1
            if sequence.family.startswith('ambiguous'):
                key=sequence.sequence_id.rsplit('-',1)[-1]
                if sequence.family=='ambiguous_stay': twins[key]=sequence_predictions
                elif twins.get(key)!=sequence_predictions: raise AssertionError('Evaluator identity leaked into tracking')
            progress['completed_sequences']+=1
        if initial!={s:n.state_digest() for s,n in networks.items()} or any(n.updates!=320 for n in networks.values()):
            raise AssertionError('Frozen labels changed')
        if manifest!=sources(): raise AssertionError('Source changed during run')
        arms={}
        for arm in scenes.PROTOCOL['arms']:
            selected=[r for r in summary if r['arm']==arm]
            totals=Counter()
            for row in selected:totals.update(row['counts'])
            recovery=[e for r in selected for e in r['recovery'] if not e['ambiguous']]
            conditional=[e for e in recovery if e['pre_established']]
            arms[arm]={'metrics':summarize(totals),'ambiguity_safety_applicable':arm!='shuffled_motion',
                       'families':{family:summarize(sum((Counter(r['counts']) for r in selected if r['family']==family),Counter())) for family in scenes.FAMILIES},
                       'recovery':{'events':len(recovery),'pre_established':len(conditional),'first_frame_success':sum(e['first_frame_success'] for e in recovery),
                                   'on_time_success':sum(e['on_time_success'] for e in recovery),'conditional_on_time_success':sum(e['on_time_success'] for e in conditional)},
                       'association_latency':latency(association_times[arm],'association only, measured directly after extraction; excludes classifier'),
                       'latency':latency(arm_times[arm],'extraction plus association; no classifier, capture, decode, display or transport')}
        result={'arms':arms,'sequences':summary,'frozen_labels':{s:label_total(rows) for s,rows in label_rows.items()},
                'classifier_state_unchanged':True,'checkpoint_fingerprints':scenes.PROTOCOL['classifier']['checkpoints'],
                'classifier_updates_here':0,'association_identical_across_label_checkpoints':'structural independence; tracker has no classifier input',
                'ambiguous_twin_output_equality':True,'cold_replays':cold_rows,
                'extraction_latency':latency(extraction_times,'standalone identical extractor; separately timed passes, not subtracted from tracker timings'),
                'label_latency':{s:latency(v,'frozen classifier after extraction; excludes association') for s,v in label_times.items()},
                'records_sha256':digest(log.read_bytes()),'source_sha256':manifest,
                'interpretation':scenes.PROTOCOL['interpretation']}
        write(output/'summary.json',result)
        progress.update(completed=True,phase='complete',cold_replays=len(cold_rows),classifier_state_unchanged=True)
    except Exception as exc:
        progress['error']={'type':type(exc).__name__,'message':str(exc)}
        raise
    finally:
        progress['wall_seconds']=time.perf_counter()-start;progress['observed_memory']=peak_memory()
        write(output/'result.json',progress)
    return progress


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--split',choices=('development','heldout'),default='development')
    args=parser.parse_args();print(json.dumps(experiment(args.output,args.split),indent=2))


if __name__=='__main__':main()
