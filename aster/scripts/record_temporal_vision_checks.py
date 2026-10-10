"""Retain every focused mechanical and numerical attempt, including failures."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--split',choices=('development','heldout'),default='development');a=p.parse_args()
    output=a.output.absolute()
    if any(x.is_symlink() for x in (output,)+tuple(output.parents)):raise ValueError('Symlink output refused')
    output.mkdir(parents=True,exist_ok=False)
    result={'schema':'aster.temporal-vision-checks.v1','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'environment':{'python':platform.python_version(),'platform':platform.platform()},'split':a.split,
            'stages':[],'scientific_scope':'Synthetic temporal association only; frozen shape/color labels separate from tracking.',
            'production_activated':False,'user_workstation_tested':False}
    selected=[Path(__file__),ROOT/'tests/test_temporal_vision.py',*sorted((ROOT/'experiments/temporal_vision').glob('*.py')),
              ROOT/'experiments/temporal_vision/PROTOCOL.json']
    result['source_sha256']={x.relative_to(ROOT).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in selected}
    stages=[('mechanical',[sys.executable,'-B','-m','unittest','discover','-s','tests','-p','test_temporal_vision.py','-v'],60),
            ('numerical',[sys.executable,'-B','-m','experiments.temporal_vision.run','--split',a.split,'--output',str(output/'run')],120),
            ('compile',[sys.executable,'-m','compileall','-q','experiments/temporal_vision','tests/test_temporal_vision.py','scripts/record_temporal_vision_checks.py'],30)]
    for name,command,timeout in stages:
        start=time.perf_counter()
        try:
            child=subprocess.run(command,cwd=ROOT,env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=timeout)
            log=child.stdout+child.stderr
            (output/f'{name}.stdout.log').write_text(child.stdout,encoding='utf-8')
            (output/f'{name}.stderr.log').write_text(child.stderr,encoding='utf-8')
            stage={'name':name,'returncode':child.returncode,'passed':child.returncode==0,'wall_seconds':time.perf_counter()-start,
                   'log_sha256':hashlib.sha256(log.encode()).hexdigest(),'failure_excerpt':log[-6000:] if child.returncode else None}
            counts=re.search(r'Ran (\d+) tests?',log)
            if counts:stage['tests_run']=int(counts.group(1))
        except subprocess.TimeoutExpired as exc:
            stage={'name':name,'passed':False,'error':'timeout','timeout_seconds':timeout,'wall_seconds':time.perf_counter()-start}
        result['stages'].append(stage)
        (output/f'{len(result["stages"]):02}-{name}.json').write_text(json.dumps(stage,indent=2)+'\n',encoding='utf-8')
        if not stage['passed']:break
    result['success']=len(result['stages'])==len(stages) and all(s['passed'] for s in result['stages'])
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
