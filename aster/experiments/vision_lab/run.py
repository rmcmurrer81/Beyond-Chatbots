"""Explicit finite synthetic experiment. Creates new evidence; no app/state access."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from .source import ROOT, VENDOR, load
from .scenes import PROTOCOL,cases,receipt
from . import learner
from .scoring import score,total


def digest(raw):return hashlib.sha256(raw).hexdigest()


def write(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def source_manifest():
    paths=list(Path(__file__).parent.glob('*.py'))+[Path(__file__).with_name('PROTOCOL.json')]+list(VENDOR.iterdir())
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in sorted(paths) if p.is_file()}


def peak_memory():
    if os.name=='posix':
        import resource
        value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return {'bytes':int(value*(1 if sys.platform=='darwin' else 1024)),'method':'process high-water RSS; includes interpreter and prior stages, excludes child','hard_limit':False}
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(x,ctypes.c_size_t) for x in ('peak_working_set','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
        c=Counters();c.cb=ctypes.sizeof(c)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetCurrentProcess.restype=wintypes.HANDLE
        psapi=ctypes.WinDLL('psapi',use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(c),ctypes.sizeof(c)):
            return {'bytes':int(c.peak_working_set),'method':'process peak working set; excludes child','hard_limit':False}
    return {'bytes':None,'method':'unavailable','hard_limit':False}


def experiment(output,split):
    output=Path(output)
    if output.is_symlink():raise ValueError('Output symlink refused')
    # Refuse every existing ancestor symlink; this is not an OS sandbox.
    for p in (output,)+tuple(output.parents):
        if p.exists() and p.is_symlink():raise ValueError('Output ancestor symlink refused')
    output=output.absolute()
    output.mkdir(parents=True,exist_ok=False)
    began=time.perf_counter();frozen=source_manifest()
    write(output/'freeze.json',{'schema':'aster.vision-freeze.v1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'source_sha256':frozen,'protocol':PROTOCOL,'split':split,'no_evaluation_in_this_invocation_before_freeze':True})
    progress={'schema':'aster.vision-run.v1','split':split,'completed':False,'seeds':[],
              'production_available':False,'camera_or_screen_capture':False,'temporal_model':False,
              'environment':{'python':platform.python_version(),'platform':platform.platform(),'numpy':'2.3.5','threads':1,'gpu_used':False}}
    try:
        data,model=load();dataset=cases(split)
        if split=='heldout':
            development=cases('development')
            shared={c.observation.rgb for c in dataset}&{c.observation.rgb for c in development}
            write(output/'split-audit.json',{'train_source':'exact upstream96;32x32 RGB','heldout_frames':len(dataset),'development_frames':len(development),'shared_dev_heldout_rgb_count':len(shared),'template_note':'Same three synthetic shape families; nuisance/composition generalization only, not novel natural image classes.'})
            if shared:raise AssertionError('Development/heldout pixel overlap')
        write(output/'cases.json',{'schema':'aster.vision-cases.v1','cases':[receipt(c) for c in dataset]})
        for seed in PROTOCOL['model_seeds']:
            progress['active_seed']=seed;progress['phase']='training'
            seed_start=time.perf_counter()
            network,nearest,train_frames,labels,losses=learner.train(data,model,seed,PROTOCOL['train_binding'])
            training_wall=time.perf_counter()-seed_start
            checkpoint=network.to_bytes();initial_digest=network.state_digest()
            (output/f'seed-{seed}.bin').write_bytes(checkpoint)
            untrained=model.FactorizedModel(seed)
            records=[];times=[]
            case_log=output/f'seed-{seed}-cases.jsonl'
            case_log.open('x',encoding='utf-8').close()
            progress['phase']='evaluation';progress['completed_cases']=0
            for case in dataset:
                progress['active_case']=case.case_id
                started=time.perf_counter();raw=case.observation.rgb
                observed=learner.predict(network,raw)
                elapsed=time.perf_counter()-started;times.append(elapsed)
                near=learner.predict(nearest,raw);control=learner.predict(untrained,raw)
                oracle=learner.oracle_predict(network,raw,case.visible_masks)
                global_result=learner.global_predict(network,raw)
                arms={}
                for name,pred in [('components_learned',observed['predictions']),('components_nearest',near['predictions']),
                                  ('components_untrained',control['predictions']),('oracle_visible_masks',oracle)]:
                    metrics,matches=score(pred,case.objects)
                    arms[name]={'predictions':pred,'metrics':metrics,'matches':matches}
                known=[o for o in case.objects if o['known']]
                single=len(case.objects)==1 and len(known)==1
                global_result['eligible_single_known']=single
                global_result['correct_accepted_single_known']=bool(single and global_result['accepted'] and
                    global_result['ids']==[['red','green','blue'].index(known[0]['color']),['square','circle','triangle'].index(known[0]['shape'])])
                records.append({'case_id':case.case_id,'family':case.family,'object_count':len(case.objects),
                                'extraction':observed['extraction'],'arms':arms,'original_global':global_result,
                                'learned_total_seconds':elapsed})
                with case_log.open('a',encoding='utf-8',newline='\n') as stream:
                    stream.write(json.dumps(records[-1],sort_keys=True,allow_nan=False)+'\n')
                progress['completed_cases']+=1
            if network.state_digest()!=initial_digest:raise AssertionError('Evaluation changed model state')
            if frozen!=source_manifest():raise AssertionError('Source changed during frozen run')
            # Fresh independent Python process, exact serialized weights and RGB-only probes.
            progress['phase']='cold_restore'
            probe_path=output/f'cold-{seed}.json'
            child=subprocess.run([sys.executable,'-B','-m','experiments.vision_lab.cold',str(output/f'seed-{seed}.bin'),str(probe_path)],
                           cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1'),check=False,timeout=30,capture_output=True,text=True)
            write(output/f'cold-process-{seed}.json',{'returncode':child.returncode,'stdout':child.stdout[:2000],'stderr':child.stderr[:4000]})
            child.check_returncode()
            cold=json.loads(probe_path.read_text(encoding='utf-8'))
            probes=tuple(train_frames[i] for i in (0,15,31,47,63,79,95))
            expected=json.loads(json.dumps(network.predict(probes)))
            if cold['digest']!=initial_digest or cold['predictions']!=expected or cold['updates']!=320:raise AssertionError('Fresh-process restore mismatch')
            summaries={}
            for family in PROTOCOL['heldout_families']:
                selected=[r for r in records if r['family']==family]
                summaries[family]={name:total([r['arms'][name]['metrics'] for r in selected]) for name in selected[0]['arms']}
                eligible=[r['original_global'] for r in selected if r['original_global']['eligible_single_known']]
                summaries[family]['original_global']={'eligible_single_known':len(eligible),'correct_accepted':sum(r['correct_accepted_single_known'] for r in eligible),
                    'multiobject_detection':'unsupported; not pooled into the single-object comparison'}
            sorted_times=sorted(times)
            result={'seed':seed,'training_updates':network.updates,'training_exposures':3840,'loss_samples':losses,
                    'training_seconds':training_wall,'checkpoint_sha256':digest(checkpoint),'inference_state_unchanged':True,
                    'cold_restore':{'same_digest':True,'same_predictions':True,'probe_count':7,'training_updates_in_child':0},
                    'training_sanity_correct':sum(p['ids']==t for start in range(0,96,16) for p,t in zip(network.predict(train_frames[start:start+16]),labels[start:start+16])),
                    'training_sanity_denominator':96,'summaries':summaries,
                    'case_records_file':case_log.name,'case_records_sha256':digest(case_log.read_bytes()),
                    'latency':{'scope':'per-frame extraction plus learned prediction, sequential CPU batch1; excludes decoding/capture/display and all other arms',
                               'frames':len(times),'total_seconds':sum(times),'p50_seconds':sorted_times[len(times)//2],
                               'p95_seconds':sorted_times[int(.95*(len(times)-1))],'max_seconds':max(times)},
                    'parameter_accounting':network.accounting()}
            if frozen!=source_manifest():raise AssertionError('Source changed after cold probe')
            write(output/f'seed-{seed}.json',result)
            progress['seeds'].append({'seed':seed,'result':f'seed-{seed}.json','sha256':digest((output/f'seed-{seed}.json').read_bytes()),
                                      'checkpoint_sha256':digest(checkpoint),'training_seconds':training_wall,'latency':result['latency']})
        if frozen!=source_manifest():raise AssertionError('Source changed before completion')
        progress['completed']=True;progress['phase']='complete'
    except Exception as exc:
        progress['error']={'type':type(exc).__name__,'message':str(exc)}
        raise
    finally:
        progress['wall_seconds']=time.perf_counter()-began;progress['observed_memory']=peak_memory()
        write(output/'result.json',progress)
    return progress


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--split',choices=('development','heldout'),default='development');args=parser.parse_args()
    result=experiment(args.output,args.split)
    print(json.dumps({'completed':result['completed'],'seeds':len(result['seeds']),'wall_seconds':result['wall_seconds'],'observed_memory':result['observed_memory']},indent=2))


if __name__=='__main__':main()
