"""Closed, byte-pinned source admission. Inspection never imports NumPy."""
import hashlib
import json
from pathlib import Path
import platform
import sys
from types import ModuleType, SimpleNamespace

PIN = '4a5c8396f820d8caf81b9ccba850617ae9e60489'
PYTHON_VERSION = '3.12.14'
PYTHON_VERSIONS = ('3.12.14', '3.14.4')
NUMPY_VERSION = '2.3.5'
_PREFIX = 'research/teaching-method-comparison086/source/numerical/'
_FILES = {
    _PREFIX + 'dialogue_decoder.py': (18123, '52cd4b6e79fcd09198380e12320ff85468fb8bd6bedd5d424ede2b58dbdf5cc0'),
    _PREFIX + 'method_order.py': (6022, '9ee8397c76bc6736eb2d99708342f7bdd6ecddd69c41389ad99954a44c7e80b9'),
    _PREFIX + 'probe_ledger.py': (8135, 'dbde8c0de085a0caacd7606b59240e678eea82da8f025508257c488e1a849ebe'),
    'THIRD_PARTY_NOTICES.md': (4253, 'a1d8572ef289312da73fefcf47accc712d1fed6556bfb10e2620c42392a828a8'),
}


class SourceError(ValueError):
    """Bounded source/runtime refusal; no raw filesystem details exposed."""


def source_root():
    return Path(__file__).resolve().parents[2] / 'vendor' / 'newbrain_text_candidates' / PIN


def _link(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def _read(root, relative, limit):
    path = root / relative
    if _link(root) or any(_link(p) for p in (path, *path.parents)):
        raise SourceError('source_symlink_refused')
    try:
        with path.open('rb') as stream:
            raw = stream.read(limit + 1)
        if not path.is_file() or len(raw) > limit:
            raise SourceError('source_extent_refused')
    except OSError as exc:
        raise SourceError('source_unavailable') from exc
    return raw


def inspect_sources(root=None):
    """Return safe relative-path provenance after checking every selected byte."""
    root = source_root() if root is None else Path(root)
    expected_paths = set(_FILES) | {'manifest.json'}
    observed_paths = set()
    try:
        for count, path in enumerate(root.rglob('*'), 1):
            if count > 32 or _link(path):
                raise SourceError('source_roster_refused')
            if path.is_file():
                observed_paths.add(path.relative_to(root).as_posix())
        if observed_paths != expected_paths:
            raise SourceError('source_roster_mismatch')
    except OSError as exc:
        raise SourceError('source_unavailable') from exc
    records = []
    for relative, (size, expected) in _FILES.items():
        raw = _read(root, relative, size)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != size or digest != expected:
            raise SourceError('source_digest_mismatch')
        records.append({'path': relative, 'bytes': size, 'sha256': digest,
            'git_blob': hashlib.sha1(b'blob ' + str(size).encode('ascii') + b'\0' + raw).hexdigest()})
    try:
        manifest = json.loads(_read(root, 'manifest.json', 16384))
        if (manifest['schema'] != 'aster.newbrain-text.source-manifest.v1'
                or manifest['upstream_repository'] != 'rmcmurrer81/newbrain'
                or manifest['upstream_commit'] != PIN or manifest['files'] != records
                or manifest['exact_source_preserved'] is not True
                or manifest['production_backend_enabled'] is not False):
            raise SourceError('source_manifest_mismatch')
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceError('source_manifest_invalid') from exc
    encoded = json.dumps(records, sort_keys=True, separators=(',', ':')).encode('ascii')
    return {'schema': 'aster.newbrain-text.source-admission.v1', 'upstream_commit': PIN,
        'files': records, 'source_sha256': hashlib.sha256(encoded).hexdigest(),
        'production_backend_enabled': False, 'runtime_executed': False}


def runtime_info():
    """Require the optional qualified numerical runtime, with no auto-install."""
    if platform.python_implementation() != 'CPython' or platform.python_version() not in PYTHON_VERSIONS:
        raise SourceError('requires_cpython_3.12.14_or_3.14.4')
    try:
        import numpy
    except ImportError as exc:
        raise SourceError('optional_numpy_unavailable') from exc
    if numpy.__version__ != NUMPY_VERSION:
        raise SourceError('requires_numpy_' + NUMPY_VERSION)
    return {'python': platform.python_version(), 'implementation': platform.python_implementation(),
        'numpy': numpy.__version__, 'platform': sys.platform,
        'pointer_bits': 64 if sys.maxsize > 2**32 else 32,
        'scope': 'version pins; not complete native binary or whole-process qualification'}


def load_modules():
    """Execute only the three verified generic modules under private names."""
    inspect_sources()
    runtime_info()
    result = {}
    for key, filename in (('decoder', 'dialogue_decoder.py'), ('method_order', 'method_order.py'),
                          ('probe_ledger', 'probe_ledger.py')):
        relative = _PREFIX + filename
        raw = _read(source_root(), relative, _FILES[relative][0])
        if hashlib.sha256(raw).hexdigest() != _FILES[relative][1]:
            raise SourceError('source_changed_before_load')
        module = ModuleType('aster_text_pinned_' + filename[:-3])
        # Relative virtual filename keeps private installation paths out of errors.
        exec(compile(raw, 'newbrain-text/' + filename, 'exec'), module.__dict__)
        result[key] = module
    return SimpleNamespace(**result)
