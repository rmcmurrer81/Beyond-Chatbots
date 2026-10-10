"""Pinned, reviewed source loader for an isolated value-component experiment.

This is NOT a security sandbox or Aster's conversational backend. Only committed,
reviewed pins can load. Source bytes are verified before compilation, with no
sys.path/sys.modules changes and no imported bytecode cache. A future pin needs
explicit review, registry addition, compatibility tests and its own qualification.
"""
import builtins
import hashlib
import json
from pathlib import Path
from types import ModuleType
from threading import RLock

LEGACY_PIN = 'bd0c5a34ade90470fb2bb0025af30cf4a51881bd'
PIN = 'df8c2bc9dd6359c5a20b14baf0b3dd9982c5f5ef'
APPROVED_MANIFESTS = {
    LEGACY_PIN: '6f70077681c80dfcd467ac3016370047c6de9ebac5abde74e6d532a5530b4a72',
    PIN: '236b3042e47ee11ad5308aecb21943ebeb94aae4df593e322a23f52c433b68bd',
}
REVIEWED_MIGRATIONS = {(LEGACY_PIN, PIN), (PIN, LEGACY_PIN)}
VALUE_PATH = 'research/value-engineering053/learned_value.py'
OBSERVER_PATH = 'research/value-event-engineering054/event_observer.py'
DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'vendor' / 'newbrain_snapshots'
MAX_ENVELOPE = 70000


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def need(condition, message):
    if not condition:
        raise ValueError(message)


class ComponentSource:
    def __init__(self, *, pin=PIN, snapshot_root=DEFAULT_ROOT):
        need(type(pin) is str and pin in APPROVED_MANIFESTS, 'Unreviewed source pin refused')
        self.pin = pin
        root = Path(snapshot_root) / pin
        self.root = root
        raw = (root / 'manifest.json').read_bytes()
        need(len(raw) <= 32768 and hashlib.sha256(raw).hexdigest() == APPROVED_MANIFESTS[pin],
             'Pinned manifest integrity mismatch')
        self.manifest = json.loads(raw)
        need(self.manifest['commit'] == pin and
             self.manifest['schema'] == 'aster.newbrain.component-snapshot.v1', 'Manifest version mismatch')
        self.sources = {}
        # Read and verify ALL copied sources/docs before executing any module.
        for entry in self.manifest['files']:
            path = entry['path']
            need(not Path(path).is_absolute() and '..' not in Path(path).parts, 'Unsafe source path')
            data = (root / path).read_bytes()
            need(len(data) == entry['bytes'] and hashlib.sha256(data).hexdigest() == entry['sha256'],
                 'Source bytes mismatch: ' + path)
            blob = b'blob ' + str(len(data)).encode('ascii') + b'\0' + data
            need(hashlib.sha1(blob).hexdigest() == entry['git_blob_sha1'], 'Git blob mismatch')
            self.sources[path] = data
        self.value = self.load_module(VALUE_PATH, 'aster_experimental_learned_value')
        self.observer = self.load_module(OBSERVER_PATH, 'aster_experimental_event_observer',
                                         {'learned_value': self.value})

    def load_module(self, path, name, dependencies=None):
        """Execute verified upstream bytes under a private module namespace.

        Explicit dependency binding avoids generic learned_value import collisions.
        It does not relax, edit or call the upstream __main__ execution guard.
        """
        dependencies = {} if dependencies is None else dependencies
        source = self.sources[path]
        module = ModuleType(name)
        module.__file__ = str(self.root / path)
        ordinary_import = builtins.__import__

        def bound_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and name in dependencies:
                return dependencies[name]
            return ordinary_import(name, globals, locals, fromlist, level)

        namespace = dict(vars(builtins))
        namespace['__import__'] = bound_import
        module.__dict__['__builtins__'] = namespace
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
        return module

    def fresh(self, owner_id):
        return ValueSession(self, self.value.ValueLearner(owner_id))

    def restore(self, raw, *, owner_id):
        from .persistence import MAX_CHECKPOINT, SESSION_SCHEMA, parse, restore_checkpoint
        data = parse(raw, MAX_CHECKPOINT)
        need(type(data) is dict, 'Closed state envelope required')
        if data.get('schema') == SESSION_SCHEMA:
            return restore_checkpoint(self, raw, owner_id=owner_id)
        need(len(raw) <= MAX_ENVELOPE, 'Bounded state envelope required')
        need(canonical(data) == raw, 'Canonical complete envelope required')
        need(set(data) == {'schema', 'pin', 'owner_id', 'component_sha256', 'state_sha256', 'state'},
             'Closed state envelope required')
        need(data['schema'] == 'aster.newbrain.value-state.v1', 'State schema migration required')
        need(data['owner_id'] == owner_id, 'Cross-owner state refused')
        need(data['pin'] == self.pin, 'Cross-pin state requires explicit reviewed migration')
        need(data['component_sha256'] == hashlib.sha256(self.sources[VALUE_PATH]).hexdigest(),
             'State component provenance mismatch')
        need(type(data['state']) is str and data['state'].isascii(), 'Complete learner state required')
        state = data['state'].encode('ascii')
        need(hashlib.sha256(state).hexdigest() == data['state_sha256'], 'State checksum mismatch')
        model = self.value.ValueLearner.restore(state, expected_owner_id=owner_id)
        return ValueSession(self, model)


    def migrate(self, raw, *, owner_id, from_pin):
        """Explicit reversible migration for the reviewed byte-identical pair only.

        No training, file overwrite, history dropping, or implicit pin conversion.
        Keep the input bytes as an independent rollback checkpoint.
        """
        need((from_pin, self.pin) in REVIEWED_MIGRATIONS, 'Unreviewed migration route refused')
        previous = ComponentSource(pin=from_pin, snapshot_root=self.root.parent)
        need(all(previous.sources[p] == self.sources[p] for p in (VALUE_PATH, OBSERVER_PATH)),
             'Migration requires byte-identical reviewed component sources')
        previous.restore(raw, owner_id=owner_id)
        data = json.loads(raw)
        data['pin'] = self.pin
        return self.restore(canonical(data), owner_id=owner_id)


class ValueSession:
    """Separate owner-scoped numeric lab state; no production tool/autonomy grant.

    .model is legacy raw upstream access and bypasses transactional guarantees.
    Use .learn(), .observer(), and .checkpoint()/save() for bounded custody.
    A trusted single writer owns a checkpoint path; no cross-process lock exists.
    """
    def __init__(self, source, model):
        self.source, self.model = source, model
        self._histories = {}
        self._lock = RLock()

    def snapshot(self):
        """Compatible v1 learner-only bytes; use checkpoint() for observer history."""
        state = self.model.snapshot()['raw']
        raw = canonical({'schema': 'aster.newbrain.value-state.v1', 'pin': self.source.pin,
                         'owner_id': self.model.owner_id,
                         'component_sha256': hashlib.sha256(self.source.sources[VALUE_PATH]).hexdigest(),
                         'state_sha256': hashlib.sha256(state).hexdigest(), 'state': state.decode('ascii')})
        need(len(raw) <= MAX_ENVELOPE, 'Complete envelope exceeds budget')
        return raw

    def checkpoint(self):
        from .persistence import checkpoint
        with self._lock:
            return checkpoint(self)

    def save(self, path):
        from .persistence import atomic_write
        with self._lock:
            raw = self.checkpoint()
            self.source.restore(raw, owner_id=self.model.owner_id)
            atomic_write(path, raw, source=self.source, owner_id=self.model.owner_id)
            return raw

    def learn(self, event, consequence, *, checkpoint_path=None):
        """Stage one numeric update; publish only a complete representable checkpoint."""
        from .persistence import checkpoint, atomic_write, input_raw
        event, consequence = (json.loads(input_raw(data, self.source.observer.MAX_INPUT_BYTES))
                              for data in (event, consequence))
        with self._lock:
            candidate = self.source.value.ValueLearner.restore(self.model.snapshot()['raw'],
                                                               expected_owner_id=self.model.owner_id)
            result = candidate.learn(event, consequence)
            raw = checkpoint(self, model=candidate)
            self.source.restore(raw, owner_id=self.model.owner_id)
            if checkpoint_path is not None:
                atomic_write(checkpoint_path, raw, source=self.source, owner_id=self.model.owner_id)
            self.model = candidate
            return result

    def observer(self, *, experiment_id, arm_id):
        from .persistence import MAX_OBSERVERS, TransactionalObserver
        key = (self.source.value.identifier(experiment_id), self.source.value.identifier(arm_id))
        with self._lock:
            if key not in self._histories:
                need(len(self._histories) < MAX_OBSERVERS, 'Fixed observer capacity; no eviction')
                self._histories[key] = []
            return TransactionalObserver(self, key)

    def respond(self, request):
        raise NotImplementedError('Numeric value component is not a qualified conversational backend')
