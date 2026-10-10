"""Retain safe Aster-only outcomes; raw original-entry diagnostics stay temporary."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

from .source import ROOT, PIN, stage, verify
from .pipeline import run as pipeline, exact_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-exact-runtime', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'schema':'aster.hearing-compatibility.v1','recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_commit':PIN,'python':platform.python_version(),'implementation':platform.python_implementation(),
        'platform':platform.system(),'production_backend_activated':False,'conversation_qualified':False,
        'general_hearing_or_intelligence_claimed':False,'personal_upstream_data_used':False,
        'prior_results_overwritten':False,'source_integrity':{},'component':{},'qualified_runtime':{},'success':False}
    code = 1
    try:
        manifest = verify()
        report['source_integrity'] = {'status':'PASSED','exact_generic_modules':20,'role_manifests':6,
            'exact_generic_source_bytes':sum(e['bytes'] for e in manifest['files'] if e['path'].endswith('.py'))}
        with tempfile.TemporaryDirectory(prefix='aster-hearing-') as temporary:
            work = Path(temporary)
            component = stage(work/'components')
            cmd = [sys.executable,'-I','-S','-B',str(ROOT/'experiments/newbrain_hearing/runner.py'),
                   str(component),str(ROOT/'experiments/newbrain_hearing/component_cases.py'),str(work/'component.json')]
            completed = subprocess.run(cmd,capture_output=True,timeout=60,cwd=work)
            (output/'component-tests.log').write_bytes(completed.stdout+completed.stderr)
            if (work/'component.json').exists():
                report['component'] = json.loads((work/'component.json').read_text())
            if completed.returncode != 0:
                raise RuntimeError('Component compatibility tests failed; see component-tests.log')
            if exact_runtime():
                runtime = stage(work/'runtime-guards','210','staged_producer')
                cmd = [sys.executable,'-I','-S','-B',str(ROOT/'experiments/newbrain_hearing/runner.py'),
                       str(runtime),str(ROOT/'experiments/newbrain_hearing/runtime_cases.py'),str(work/'runtime.json')]
                completed = subprocess.run(cmd,capture_output=True,timeout=60,cwd=work)
                (output/'runtime-guards.log').write_bytes(completed.stdout+completed.stderr)
                if (work/'runtime.json').exists():
                    report['runtime_guards'] = json.loads((work/'runtime.json').read_text())
                    report['runtime_guards']['scope'] = 'Original RunIO under exact isolated CPython 3.14.4'
                if completed.returncode != 0:
                    raise RuntimeError('Exact-runtime guard tests failed')
            pipeline(work, report['qualified_runtime'])
            if args.require_exact_runtime and not exact_runtime():
                raise RuntimeError('This CI job requires exact CPython 3.14.4; skip is not a pass')
            report['success'] = True
            code = 0
    except Exception as error:
        # Outcome-only disclosure: entry stderr stays in ephemeral diagnostics.
        if report['qualified_runtime'].get('executed'):
            report['qualified_runtime']['status'] = 'FAILED'
        report['error_type'] = type(error).__name__
        report['error'] = 'A hearing check failed. See component counts or process exits; detailed diagnostics remain local.'
        print(report['error_type'] + ': ' + report['error'], file=sys.stderr)
    finally:
        report['wall_seconds'] = time.monotonic()-started
        files = {}
        for directory in ('experiments/newbrain_hearing',):
            for path in sorted((ROOT/directory).glob('*.py')):
                files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        report['aster_harness_sha256'] = files
        (output/'result.json').write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'success':report['success'],'component':report['component'],
                      'exact_runtime_status':report['qualified_runtime'].get('status'),
                      'arms':[{'arm':a['arm'],'initial':a['initial_score']['totals'],
                               'fresh':a['fresh_score']['totals'],'old_decision_rows_equal':a['old_decision_rows_equal'],
                               'new_teachings':a['new_teachings']} for a in report['qualified_runtime'].get('arms',[])],
                      'report_file':'result.json'}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
