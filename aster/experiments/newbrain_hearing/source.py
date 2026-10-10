"""Verify the separately versioned exact source and assemble isolated roles."""
import ast
import hashlib
import json
from pathlib import Path
import shutil

PIN = 'bee67b1cbb94234e31faeb8f2c04477d100a647b'
ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / 'vendor' / 'newbrain_hearing_candidates' / PIN
# Generated once from the reviewed saved manifest. This is an integrity anchor,
# not a signature or a hostile-editor security boundary.
MANIFEST_SHA256 = '98635aea17ef9a4e03fb60584c19d9c39c5bd398ded5c2e39e90bc712791c6a5'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(root=VENDOR):
    root = Path(root)
    raw = (root / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError('Hearing source manifest changed')
    manifest = json.loads(raw)
    if manifest['source_commit'] != PIN or manifest['production_backend_activated'] is not False:
        raise ValueError('Unexpected source pin or production activation')
    expected = {f['path']: f for f in manifest['files']}
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != set(expected) | {'manifest.json'}:
        raise ValueError('Missing or additional candidate source files')
    modules = {}
    for relative, entry in expected.items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Source must be an owned plain file')
        data = path.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256'] or blob != entry['git_blob_sha1']:
            raise ValueError('Exact candidate source bytes changed: ' + relative)
        if path.suffix == '.py':
            if path.name in modules:
                raise ValueError('Ambiguous module basename')
            ast.parse(data, filename=relative)
            modules[path.name] = relative
    if len(modules) != 20 or len(manifest['roles']) != 6:
        raise ValueError('Incomplete generic dependency closure')
    for role in manifest['roles']:
        for item in role['files']:
            entry = expected[item['repository_path']]
            if item['filename'] != Path(item['repository_path']).name or any(item[k] != entry[k] for k in ('sha256', 'bytes')):
                raise ValueError('Role/source mapping differs')
        names = {r['filename'] for r in role['files']}
        if role['role'] == 'staged_blind' and names & {'waveform_corpus.py', 'synthetic_audio.py', 'waveform_score.py', 'score.py', 'retention_labels.py'}:
            raise ValueError('Label-side code in blind role')
    return manifest


def stage(destination, experiment=None, role=None, root=VENDOR):
    """Only exact source copies; no state, bytecode, gold, or loader patching."""
    manifest = verify(root)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    if experiment is None and role is None:
        paths = [r['path'] for r in manifest['files'] if r['path'].endswith('.py')]
    else:
        selected = [r for r in manifest['roles'] if (r['experiment'], r['role']) == (experiment, role)]
        if len(selected) != 1:
            raise ValueError('Unknown or ambiguous source role')
        paths = [r['repository_path'] for r in selected[0]['files']]
    for relative in paths:
        source = Path(root) / relative
        target = destination / source.name
        if target.exists():
            raise ValueError('Duplicate role module')
        shutil.copyfile(source, target)
        if source.read_bytes() != target.read_bytes():
            raise ValueError('Staged bytes differ')
    return destination
