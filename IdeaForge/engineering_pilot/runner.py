"""Resource-bounded fixed-function workers, never execute model-generated code."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from .schema import validate, cheap_checks


def stage(kind, p, directory, deadline):
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        return {'status':'unknown','reason':'time budget exhausted'}
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    try:
        result = subprocess.run([sys.executable,'-m','engineering_pilot.worker',kind],
            input=json.dumps({'parameters':p,'directory':str(directory),'seconds':remaining}),
            text=True,capture_output=True,timeout=remaining,env=env)
        if result.returncode:
            return {'status':'unknown','reason':'worker failed', 'detail':result.stderr[-2000:]}
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {'status':'unknown','reason':'time budget exhausted; worker terminated'}


def run(raw, output, *, seconds=60, optimize=False):
    p = validate(raw)
    if type(seconds) not in (float,int) or not 1 <= seconds <= 120:
        raise ValueError('Time budget must be 1..120 seconds')
    output = Path(output)
    # Fresh directory prevents silently overwriting previous evidence.
    output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic()+seconds
    canonical = json.dumps(raw,sort_keys=True,separators=(',',':'),allow_nan=False)
    report = {'schema_version':1,'example_only':raw['example_only'],'input_sha256':hashlib.sha256(canonical.encode()).hexdigest(),
              'input':raw,'status':'unknown','dependencies':{}, 'candidates':[],
              'limitations':['Input sources are user assertions, not independently verified measurements.',
              'CAD and dynamics are uniform-link idealizations; excluded hardware and structural strength remain unknown.',
              'No full robot, walking, balance, flight or hover validation. No hardware execution.']}
    for name in ('cadquery','mujoco','scipy','trimesh'):
        try: report['dependencies'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: report['dependencies'][name] = 'unavailable'
    candidates = [p]
    if optimize:
        search = stage('search',p,output,deadline)
        report['search'] = search
        if search['status'] == 'passed': candidates = search['shortlist']
        else: candidates = []
    for index, candidate in enumerate(candidates):
        item = {'parameters':candidate,'cheap_checks':cheap_checks(candidate),'cad':{'status':'unknown','reason':'not run'},
                'dynamics':{'status':'unknown','reason':'not run'}}
        if item['cheap_checks']['status'] == 'passed':
            item['dynamics'] = stage('dynamics',candidate,output,deadline)
            item['cad'] = stage('cad',candidate,output / f'candidate_{index:02}',deadline)
        states = [item[k]['status'] for k in ('cheap_checks','cad','dynamics')]
        item['status'] = 'failed' if 'failed' in states else 'passed' if all(s=='passed' for s in states) else 'unknown'
        report['candidates'].append(item)
    states = [item['status'] for item in report['candidates']]
    report['status'] = 'passed' if 'passed' in states else 'failed' if (states and all(x=='failed' for x in states)) or report.get('search',{}).get('status')=='failed' else 'unknown'
    report['conclusion'] = 'bounded model checks only; physical capability and manufacturing readiness remain unknown'
    (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report
