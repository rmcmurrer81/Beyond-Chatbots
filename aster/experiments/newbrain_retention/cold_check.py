"""Independent process restore with model initialization, RNG and updates blocked."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from unittest.mock import patch

from experiments.newbrain_text import source
from . import protection
from .protocol import SEEDS, ARMS
from .study import snapshot, source_binding


def forbidden(*args, **kwargs):
    raise AssertionError('cold_recheck_training_or_rng_forbidden')


def equal(actual, expected):
    if type(actual) is float and type(expected) is float:
        return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def check(directory):
    import numpy as np
    directory = Path(directory)
    with (directory / 'report.json').open('rb') as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('report_too_large')
    report = json.loads(raw)
    if not report['engineering_completed'] or report['freeze']['source_binding'] != source_binding():
        raise ValueError('completed_bound_report_required')
    modules = source.load_modules()
    results = []
    with patch.object(source, 'load_modules', return_value=modules), patch.object(protection, 'load_modules', return_value=modules), \
         patch.object(modules.decoder.DialogueDecoder, '__init__', forbidden), \
         patch.object(modules.decoder.DialogueDecoder, 'train_step', forbidden), \
         patch.object(modules.decoder.DialogueDecoder, 'loss_and_gradients', forbidden), \
         patch.object(np.random, 'default_rng', forbidden), patch.object(np.random, 'seed', forbidden), \
         patch.object(np.random, 'RandomState', forbidden), patch.object(np.random, 'random', forbidden):
        if [r['seed'] for r in report['seeds']] != list(SEEDS):
            raise ValueError('seed_roster_mismatch')
        for record in report['seeds']:
            for name in ('baseline', *ARMS):
                path = directory / f"{record['seed']}-{name}.json"
                model = protection.read_checkpoint(path)
                before = protection.checkpoint_bytes(model)
                expected = record['baseline'] if name == 'baseline' else record['arms'][name]['final']
                if name != 'baseline' and hashlib.sha256(before).hexdigest() != record['arms'][name]['checkpoint_sha256']:
                    raise ValueError('checkpoint_digest_mismatch')
                if not equal(snapshot(model, ('old', 'new', 'heldout')), expected):
                    raise ValueError('cold_decision_mismatch')
                if protection.checkpoint_bytes(model) != before:
                    raise ValueError('cold_recheck_mutated_model')
                results.append({'seed': record['seed'], 'checkpoint': name, 'passed': True,
                                'parameter_sha256': model.parameter_hash()})
    return {'schema': 'aster.retention.cold-check.v1', 'passed': True, 'restored_models': len(results),
            'training_disabled': True, 'rng_disabled': True, 'float_tolerance': 1e-12, 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = check(args.state)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)
    print(json.dumps({'passed': True, 'restored_models': result['restored_models']}))


if __name__ == '__main__':
    main()
