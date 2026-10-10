"""Run one engineering check and retain its exact-source evidence, never overwrite."""
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

ROOT = Path(__file__).resolve().parents[1]


def main():
    label, *command = sys.argv[1:]
    if not re.fullmatch(r'[a-z0-9_-]+', label) or not command:
        raise ValueError('Provide a safe unique label followed by a command')
    output = ROOT / 'test-results' / '2026-10-05-support-modules'
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / (label + '.json')
    if receipt.exists():
        raise ValueError('Prior test evidence cannot be overwritten')
    utc = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    sources = {}
    for directory in ('aster', 'tests', 'scripts'):
        for path in sorted((ROOT / directory).rglob('*.py')):
            sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {'schema': 'aster.support-check.v1', 'command': command, 'cwd': str(ROOT),
            'started_utc': utc(), 'python': sys.version, 'platform': platform.platform(),
            'environment': {'DISPLAY': os.environ.get('DISPLAY'), 'os_name': os.name},
            'base_commit': 'fe1424071d0263ac11a4a2ef3f8f367a1e7e6715', 'source_sha256': sources}
    start = time.monotonic()
    try:
        result = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        raw, code = result.stdout, result.returncode
    except subprocess.TimeoutExpired as exc:
        raw, code = exc.stdout or b'', None
        meta['error'] = 'TimeoutExpired after 600 seconds'
    (output / (label + '.log')).write_bytes(raw)
    log = raw.decode('utf-8', errors='replace')
    meta.update(finished_utc=utc(), wall_seconds=time.monotonic()-start, exit_code=code,
                status='PASS' if code == 0 else 'FAIL', log_sha256=hashlib.sha256(raw).hexdigest(),
                unittest_summaries=re.findall(r'Ran \d+ tests? in [^\n]+', log),
                skip_lines=[line for line in log.splitlines() if ' ... skipped ' in line])
    receipt.write_text(json.dumps(meta, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(log)
    return 0 if code == 0 else 1


if __name__ == '__main__': raise SystemExit(main())
