"""EWC-inspired experimental gradient adapter around unchanged upstream SGD."""
import base64
import hashlib
import json
import math
from pathlib import Path

from experiments.newbrain_text.source import load_modules, inspect_sources
from experiments.newbrain_text.curriculum import WORDS
from .protocol import OWNER, canonical, protocol_hash, row_batch

MAX_CHECKPOINT = 2 * 1024 * 1024


def estimate_importance(model, rows):
    """Squared per-row mean-token CE gradients; does not update the model."""
    import numpy as np
    if len(rows) != 6 or len({row['id'] for row in rows}) != 6:
        raise ValueError('six_unique_old_rows_required')
    before = model.state_bytes(protocol_hash())
    result = {name: np.zeros_like(value) for name, value in model.p.items()}
    for row in rows:
        _, gradients, _ = model.loss_and_gradients(row_batch(row, 1))
        for name in result:
            result[name] += gradients[name] ** 2 / len(rows)
    if model.state_bytes(protocol_hash()) != before:
        raise ValueError('fisher_mutated_anchor')
    return result


def protected_class(decoder):
    class ProtectedDecoder(decoder.DialogueDecoder):
        def loss_and_gradients(self, batch):
            loss, gradients, counts = super().loss_and_gradients(batch)
            if getattr(self, 'protection', None) is not None:
                penalty, adjustment = self.protection.penalty(self.p)
                loss += penalty
                for name in gradients:
                    gradients[name] += adjustment[name]
            return loss, gradients, counts
    return ProtectedDecoder


class Protection:
    def __init__(self, parameters, importance, strength):
        import numpy as np
        if (type(strength) is not float or not math.isfinite(strength)
                or not 0 <= strength <= 100 or set(importance) != set(parameters)):
            raise ValueError('invalid_protection')
        self.strength = strength
        self.anchor, self.importance = {}, {}
        for name, parameter in parameters.items():
            value = importance[name]
            if (type(parameter) is not np.ndarray or type(value) is not np.ndarray
                    or value.shape != parameter.shape or value.dtype != np.dtype('float64')
                    or not np.isfinite(value).all() or np.any(value < 0)
                    or not np.isfinite(parameter).all() or np.max(value, initial=0) > 1e12):
                raise ValueError('invalid_importance')
            self.anchor[name] = parameter.copy()
            self.importance[name] = value.copy()
            self.anchor[name].flags.writeable = False
            self.importance[name].flags.writeable = False

    def penalty(self, parameters):
        import numpy as np
        gradients = {name: self.strength * self.importance[name] * (value - self.anchor[name])
                     for name, value in parameters.items()}
        penalty = self.strength / 2 * sum(float(np.sum(self.importance[name] *
                    (value - self.anchor[name]) ** 2)) for name, value in parameters.items())
        if not math.isfinite(penalty) or not all(np.isfinite(g).all() for g in gradients.values()):
            raise ValueError('nonfinite_penalty')
        return penalty, gradients

    def state(self):
        return {'strength': self.strength,
                'anchor': {name: value.tolist() for name, value in self.anchor.items()},
                'importance': {name: value.tolist() for name, value in self.importance.items()}}


def protected_copy(model, importance, strength):
    decoder = load_modules().decoder
    result = protected_class(decoder).from_state_bytes(model.state_bytes(protocol_hash()), WORDS, protocol_hash())
    result.protection = Protection(model.p, importance, strength)
    return result


def checkpoint_bytes(model):
    payload = {'schema': 'aster.retention.checkpoint.v1', 'owner': OWNER,
               'protocol_sha256': protocol_hash(), 'source_sha256': inspect_sources()['source_sha256'],
               'model': base64.b64encode(model.state_bytes(protocol_hash())).decode('ascii'),
               'protection': model.protection.state() if getattr(model, 'protection', None) is not None else None}
    raw = canonical({'payload': payload, 'sha256': hashlib.sha256(canonical(payload)).hexdigest()})
    if len(raw) > MAX_CHECKPOINT:
        raise ValueError('checkpoint_too_large')
    return raw


def restore_bytes(raw):
    import numpy as np
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CHECKPOINT:
        raise ValueError('bounded_checkpoint_required')
    try:
        envelope = json.loads(raw)
        payload = envelope['payload']
        if (set(envelope) != {'payload', 'sha256'} or canonical(envelope) != raw
                or hashlib.sha256(canonical(payload)).hexdigest() != envelope['sha256']
                or set(payload) != {'schema', 'owner', 'protocol_sha256', 'source_sha256', 'model', 'protection'}
                or payload['schema'] != 'aster.retention.checkpoint.v1' or payload['owner'] != OWNER
                or payload['protocol_sha256'] != protocol_hash()
                or payload['source_sha256'] != inspect_sources()['source_sha256']):
            raise ValueError('checkpoint_binding')
        decoder = load_modules().decoder
        model_type = decoder.DialogueDecoder if payload['protection'] is None else protected_class(decoder)
        model = model_type.from_state_bytes(base64.b64decode(payload['model'], validate=True), WORDS, protocol_hash())
        if payload['protection'] is not None:
            state = payload['protection']
            if set(state) != {'strength', 'anchor', 'importance'} or set(state['anchor']) != set(model.p):
                raise ValueError('protection_fields')
            anchor = {name: np.array(value, dtype='float64') for name, value in state['anchor'].items()}
            importance = {name: np.array(value, dtype='float64') for name, value in state['importance'].items()}
            if any(anchor[name].shape != model.p[name].shape or np.max(np.abs(anchor[name]), initial=0) > 1000
                   for name in model.p):
                raise ValueError('protection_anchor_shape')
            model.protection = Protection(anchor, importance, state['strength'])
        return model
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, OverflowError) as exc:
        raise ValueError('invalid_checkpoint') from exc


def read_checkpoint(path):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (path, *path.parents)):
        raise ValueError('checkpoint_link_refused')
    with path.open('rb') as stream:
        return restore_bytes(stream.read(MAX_CHECKPOINT + 1))
