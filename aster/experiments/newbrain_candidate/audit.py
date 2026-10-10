"""Inspect exact candidate bytes without importing or executing upstream code.

A missing dependency is a refused runtime upgrade, not a skipped positive test.
This reviewed fixed candidate cannot be activated by changing a report or CLI flag.
"""
import argparse
import ast
import datetime
import hashlib
import json
from pathlib import Path
import platform
import sys

PIN = 'df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef'
MANIFEST_SHA256 = 'd5c032737a67c19f863dbdd4c80b446397addc268e72ca19e38e96ed259f8362'
INVENTORY_SHA256 = 'ef651c181fd715ab80a3a9755e8cca884a6970643a969a2faf0ce6b7b9bc5263'
ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / 'vendor' / 'newbrain_candidates' / PIN
INVENTORY = Path(__file__).with_name('dependency-inventory.json')
# Exact standard-library imports found in these four source files. Unknown names
# must go through the reviewed inventory, not the active interpreter's sys.path.
STDLIB = {'argparse', 'hashlib', 'json', 'pathlib', 'struct', 'sys'}


def checked_json(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Pinned review document integrity mismatch: ' + path.name)
    return json.loads(raw)


def audit(candidate=CANDIDATE, inventory_path=INVENTORY):
    candidate = Path(candidate)
    manifest = checked_json(candidate / 'manifest.json', MANIFEST_SHA256)
    inventory = checked_json(Path(inventory_path), INVENTORY_SHA256)
    if manifest['commit'] != PIN or inventory['commit'] != PIN or inventory['full_tree_truncated']:
        raise ValueError('Complete exact source inspection required')
    dependencies = set()
    source_hashes = {}
    for entry in manifest['files']:
        path = entry['path']
        if Path(path).is_absolute() or '..' in Path(path).parts:
            raise ValueError('Unsafe candidate path')
        raw = (candidate / path).read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()
        if sha256 != entry['sha256'] or blob != entry['git_blob_sha1'] or len(raw) != entry['bytes']:
            raise ValueError('Exact upstream byte verification failed: ' + path)
        source_hashes[path] = sha256
        if path.endswith('.py'):
            for node in ast.walk(ast.parse(raw, filename=path)):
                if isinstance(node, ast.Import):
                    dependencies.update(n.name.split('.')[0] for n in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level or not node.module:
                        raise ValueError('Unreviewed relative import')
                    dependencies.add(node.module.split('.')[0])
    external = sorted(dependencies - STDLIB)
    if set(external) != set(inventory['modules']):
        raise ValueError('Dependency review is incomplete')
    missing = [name for name in external if not inventory['modules'][name]]
    # Even supplying similarly named files cannot authorize source/runtime or
    # checkpoint compatibility. This is a fixed reviewed refusal, no plugin hook.
    return {
        'schema': 'aster.newbrain.candidate-admission.v1',
        'recorded_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_commit': PIN, 'source_tree_sha': inventory['source_tree_sha'],
        'manifest_sha256': MANIFEST_SHA256, 'inventory_sha256': INVENTORY_SHA256,
        'source_sha256': source_hashes, 'python': platform.python_version(),
        'platform': platform.platform(), 'status': 'BLOCKED_INCOMPLETE_DEPENDENCIES',
        'runtime_compatible': False, 'production_backend_activated': False,
        'candidate_code_executed': False, 'upstream_results_reproduced': False,
        'missing_published_modules': missing,
        'direct_nonstdlib_modules': external,
        'available_filename_matches_are_qualified': False,
        'other_blockers': [
            'Published RunIO requires CPython 3.14.4 with -I -S -B and source/runtime binding',
            'Required private original models, PCM, gold and binding records are excluded',
            'No qualified general conversational interface in this packet',
            'No general public license grant; project-owned generic source reuse only'],
        'preserved': ['prior qualified component snapshot', 'Aster identity/history', 'voice assets'],
        'scientific_learning_gain_claimed': False,
        'scope': 'AST and exact-byte admission audit only; source checks do not measure intelligence'}


def require_runtime_candidate():
    result = audit()
    raise RuntimeError('Candidate not admitted: ' + ', '.join(result['missing_published_modules']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = audit()
    raw = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.report:
        args.report.write_text(raw, encoding='utf-8')
    print(raw, end='')
    return 2  # Deliberate refusal, never advertise this candidate as a pass.


if __name__ == '__main__':
    raise SystemExit(main())
