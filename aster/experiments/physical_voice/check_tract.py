"""Explicit bounded original acoustic campaign; not base-test discovery.

Run: python -m experiments.physical_voice.check_tract --output FRESH_DIR --raw-dir FRESH_EXTERNAL_DIR
Raw traces are outside the repository; the fresh output directory holds a receipt.
Pure stdlib, no network/dependencies/audio playback/PCM. Inputs are numerical
probe signals, NOT another vocal-fold oscillator or an audio quality demo.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import random
import struct
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.physical_voice import tract as t

RECORD=struct.Struct('<10d')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initial(seed):
    rng=random.Random(seed)
    return t.TractWaves(*(tuple(rng.uniform(-.025,.025) for _ in range(n)) for n in (24,24,16,16)),.02,-.03)


def pose(i,dynamic):
    if not dynamic:
        return t.Articulation()
    return t.Articulation(.5+.48*math.sin(i*.007),.5+.45*math.sin(i*.013),
                          .5+.48*math.cos(i*.005),.5+.49*math.cos(i*.011))


def run_case(name,config,preloaded,dynamic,driven,raw_dir):
    frames=12_000
    tract=t.OralNasalTract(config,preloaded)
    began=time.perf_counter()
    raw_path=raw_dir/(name+'.bin.gz')
    increases=0
    state=tract.checkpoint()
    previous=state.energy_j
    output=io.BytesIO()
    output.write((json.dumps({'case':name,'config':asdict(config),'initial':asdict(preloaded),
        'frames':frames,'record':'<10d: index,flow,lip,nose,energy,source_work,prop_loss,lip_energy,nose_energy,step_residual',
        'probe':'first 6000: U=1e-4*(.6+.4*sin(.031*i)) if driven; then 0; pose explicit in recipe'})+'\n').encode())
    checkpoint_replay=True
    for i in range(frames):
        flow=1e-4*(.6+.4*math.sin(.031*i)) if driven and i<6000 else 0.
        control=pose(i,dynamic)
        if i in (0,17,1021,6000,11999):
            copy=t.OralNasalTract.from_checkpoint(tract.checkpoint())
            copied=copy.step(flow,control)
        sample=tract.step(flow,control)
        if i in (0,17,1021,6000,11999):
            checkpoint_replay &= copied==sample and copy.checkpoint()==tract.checkpoint()
        if flow==0. and sample.stored_energy_j>previous+1e-13*max(previous,1e-30):
            increases+=1
        previous=sample.stored_energy_j
        output.write(RECORD.pack(i,flow,sample.lip_root_power,sample.nose_root_power,sample.stored_energy_j,
                                sample.source_work_j,sample.propagation_loss_j,sample.lip_out_energy_j,
                                sample.nose_out_energy_j,sample.energy_residual_j))
    with raw_path.open('xb') as file:
        with gzip.GzipFile(fileobj=file,mode='wb',mtime=0,filename='') as compressed:
            compressed.write(output.getvalue())
    final=tract.checkpoint()
    scale=max(final.initial_energy_j,final.positive_source_work_j,final.negative_source_work_j,1e-30)
    ledger_error=abs(final.energy_residual_j)/scale
    passed=checkpoint_replay and increases==0 and ledger_error<1e-10
    assert passed,name
    result={
        'name':name,'passed':passed,'frames':frames,'duration_s':frames/t.SAMPLE_RATE,
        'config':asdict(config),'dynamic_area_controls':dynamic,'source_probe_enabled':driven,
        'initial_energy_j':final.initial_energy_j,'final_energy_j':final.energy_j,
        'signed_source_work_j':final.source_work_j,'positive_source_work_j':final.positive_source_work_j,
        'negative_source_work_magnitude_j':final.negative_source_work_j,
        'propagation_loss_j':final.propagation_loss_j,'lip_out_energy_j':final.lip_out_energy_j,
        'nose_out_energy_j':final.nose_out_energy_j,'ledger_relative_error':ledger_error,
        'max_abs_step_residual_j':final.max_abs_step_residual_j,
        'max_abs_ledger_residual_j':final.max_abs_ledger_residual_j,
        'max_stored_energy_j':final.max_energy_j,'max_abs_root_power':final.max_abs_wave,
        'max_abs_pressure_pa':final.max_abs_boundary_pressure_pa,
        'max_abs_lip_root_power':final.max_abs_lip_root_power,
        'max_abs_nose_root_power':final.max_abs_nose_root_power,
        'source_off_energy_increases':increases,'exact_checkpoint_replays':5,
        'wall_s':time.perf_counter()-began,'raw':{'filename':raw_path.name,'bytes':raw_path.stat().st_size,'sha256':sha(raw_path)}}
    print(name,'PASS',f'ledger relative error {ledger_error:.3g}',flush=True)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--raw-dir',type=Path,required=True,help='fresh raw directory outside repository')
    parser.add_argument('--output',type=Path,required=True,help='fresh directory for receipt.json; never overwritten')
    args=parser.parse_args()
    raw_dir=args.raw_dir.resolve()
    if raw_dir==ROOT or ROOT in raw_dir.parents:
        parser.error('raw directory must be outside repository')
    output=args.output.resolve()
    if output.exists() or output.is_symlink() or raw_dir.exists() or raw_dir.is_symlink():
        parser.error('--output and --raw-dir must both be fresh, nonexistent directories')
    if output==raw_dir or output in raw_dir.parents or raw_dir in output.parents:
        parser.error('--output and --raw-dir must be disjoint directories')
    output.mkdir(parents=True,exist_ok=False)
    raw_dir.mkdir(parents=True,exist_ok=False)
    sources=(ROOT/'experiments/physical_voice/tract.py', ROOT/'experiments/physical_voice/filters.py',
             ROOT/'tests/test_physical_tract.py', Path(__file__).resolve(), ROOT/'docs/PHYSICAL_TRACT_DESIGN.md')
    hashes_before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    log=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_physical_tract.py')
    contracts=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    assert contracts.wasSuccessful(),log.getvalue()
    rng=random.Random(6752)
    max_norm_error,max_pressure_error,max_flow_error=0.,0.,0.
    for ports in (2,3):
        for _ in range(2000):
            a=tuple(rng.uniform(-3,3) for _ in range(ports))
            y=tuple(10**rng.uniform(-9,-5) for _ in range(ports))
            b=t.scatter(a,y)
            scale=math.fsum(x*x for x in a)
            max_norm_error=max(max_norm_error,abs(math.fsum(x*x for x in b)-scale)/scale)
            p=tuple((x+z)/math.sqrt(v) for x,z,v in zip(a,b,y))
            max_pressure_error=max(max_pressure_error,(max(p)-min(p))/max(1.,max(abs(x) for x in p)))
            q=math.fsum(math.sqrt(v)*(x-z) for x,z,v in zip(a,b,y))
            max_flow_error=max(max_flow_error,abs(q))
    assert max_norm_error<3e-14 and max_pressure_error<3e-12 and max_flow_error<1e-16
    rows=[]
    for velum in (0.,.01,.5,1.):
        for gain in (1.,.997):
            rows.append(run_case(f'passive_velum{velum:g}_gain{gain:g}',t.TractConfig(velum_opening=velum,propagation_gain=gain),
                                 initial(671),True,False,raw_dir))
    for velum in (0.,.5):
        rows.append(run_case(f'driven_offset_velum{velum:g}',t.TractConfig(velum_opening=velum),t.TractWaves(),True,True,raw_dir))
    receipt={
        'passed':True,'stage':'separate reduced acoustic implementation gate','python':platform.python_version(),
        'sample_rate':48000,'oral_sections':24,'nasal_sections':16,'nasal_join_after_oral':12,
        'source_hashes':hashes_before,
        'base_contracts':{'count':contracts.testsRun,'passed':contracts.wasSuccessful(),'log':log.getvalue()},
        'junction_random_cases':4000,'max_relative_junction_norm_error':max_norm_error,
        'max_relative_pressure_mismatch':max_pressure_error,'max_abs_flow_sum_m3_s':max_flow_error,
        'oneway_oral_delay_samples':24,'roundtrip_oral_delay_samples':48,
        'quarterwave_uniform_ideal_boundary_test_only_hz':[500,1500,2500,3500],
        'campaign_frames':sum(row['frames'] for row in rows),'cases':rows,
        'numerical_note':'An initial DC-sum test used 2e-16 absolute tolerance, less than one double ULP at 1.0; corrected to3e-16. No implementation change.',
        'limitations':['Original synthetic geometry, not measured speaker anatomy.',
            'Passive numerical articulation retains stored root-power waves; moving-wall mechanical work is absent.',
            'One-way imposed flow, separate acoustic ledger; no closed fold-fluid-tract budget.',
            'Fixed 5kHz power-complementary radiation is not exact mouth/nose impedance or far-field pressure.',
            'Numerical probes and test-only ideal resonances do not establish natural speech, physiological fidelity or clinical validity.',
            'No microphone, playback, voice assets, PCM export, publishing or new dependencies.']}
    assert hashes_before=={str(p.relative_to(ROOT)):sha(p) for p in sources}, 'source changed during gate'
    path=output/'receipt.json'
    with path.open('x',encoding='utf-8') as file:
        file.write(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    print('PASS',len(rows),'cases;',contracts.testsRun,'fast contracts;',path)


if __name__=='__main__':
    main()
