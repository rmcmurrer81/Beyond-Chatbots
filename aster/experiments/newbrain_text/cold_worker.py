"""One fresh subprocess: data-only restore and read-only decision recheck."""
import argparse
import base64
import hashlib
import json
import math
import os
import sys
from .curriculum import DEFAULT_OWNER, WORDS, canonical, locked_protocol, protocol_hash
from .persistence import LabError, MODEL_NAMES, need, read_state


def _compare(expected, actual, path, differences):
    if type(expected) is float:
        need(type(actual) is float and math.isfinite(actual), 'cold_float_type_mismatch')
        delta = abs(expected - actual)
        differences['maximum_absolute_difference'] = max(differences['maximum_absolute_difference'], delta)
        differences['compared_float_values'] += 1
        policy = locked_protocol()['cold_recheck']
        need(math.isclose(expected, actual, rel_tol=policy['float_relative_tolerance'],
                          abs_tol=policy['float_absolute_tolerance']), 'cold_float_tolerance_exceeded')
    elif type(expected) is dict:
        need(type(actual) is dict and set(actual) == set(expected), 'cold_record_shape_mismatch')
        for key in expected:
            _compare(expected[key], actual[key], path + '.' + key, differences)
    elif type(expected) is list:
        need(type(actual) is list and len(actual) == len(expected), 'cold_list_shape_mismatch')
        for index, (left, right) in enumerate(zip(expected, actual)):
            _compare(left, right, path + '.' + str(index), differences)
    else:
        need(type(actual) is type(expected) and expected == actual, 'cold_exact_decision_mismatch')


def verify(state_dir, owner=DEFAULT_OWNER, parent_pid=None):
    from .source import load_modules, runtime_info
    from .training import counters, evaluate
    need(type(parent_pid) is int and parent_pid > 0 and os.getpid() != parent_pid and os.getppid() == parent_pid,
         'cold_separate_process_required')
    envelope, report = read_state(state_dir, owner)
    initial_state_digest = hashlib.sha256(canonical(envelope)).hexdigest()
    runtime = runtime_info()
    modules = load_modules()
    import numpy as np
    import random
    attempts = {'training': 0, 'rng': 0, 'initialization': 0}

    def forbid_training(*args, **kwargs):
        attempts['training'] += 1
        raise LabError('cold_training_forbidden')

    def forbid_rng(*args, **kwargs):
        attempts['rng'] += 1
        raise LabError('cold_rng_forbidden')

    def forbid_initialization(*args, **kwargs):
        attempts['initialization'] += 1
        raise LabError('cold_initialization_forbidden')

    modules.decoder.DialogueDecoder.train_step = forbid_training
    modules.decoder.DialogueDecoder.loss_and_gradients = forbid_training
    modules.decoder.DialogueDecoder.__init__ = forbid_initialization
    for name in ('default_rng', 'seed', 'RandomState', 'Generator', 'random', 'normal', 'uniform', 'rand', 'randn'):
        setattr(np.random, name, forbid_rng)
    for name in ('seed', 'random', 'randrange', 'randint', 'choice', 'choices', 'sample', 'shuffle', 'Random', 'SystemRandom'):
        setattr(random, name, forbid_rng)
    differences = {'maximum_absolute_difference': 0.0, 'compared_float_values': 0}
    checked = {}
    for name in MODEL_NAMES:
        saved = envelope['models'][name]
        raw = base64.b64decode(saved['model_b64'], validate=True)
        model = modules.decoder.DialogueDecoder.from_state_bytes(raw, WORDS, protocol_hash())
        need(model.parameter_hash() == saved['parameter_sha256'] and counters(model) == saved['counters']
             and model.state_bytes(protocol_hash()) == raw, 'cold_restore_identity_mismatch')
        actual = evaluate(model)
        expected = report[name]['evaluation'] if name in ('initial', 'baseline') else report['arms'][name]['evaluation']
        _compare(expected, actual, name, differences)
        need(model.parameter_hash() == saved['parameter_sha256'] and counters(model) == saved['counters']
             and model.state_bytes(protocol_hash()) == raw, 'cold_observation_mutated_state')
        checked[name] = {'parameter_sha256': model.parameter_hash(), 'counters': counters(model),
                         'decisions_exact': True, 'state_bytes_exact': True}
    observed_envelope, observed_report = read_state(state_dir, owner)
    need(canonical(observed_envelope) == canonical(envelope) and canonical(observed_report) == canonical(report),
         'cold_published_state_changed')
    need(attempts == {'training': 0, 'rng': 0, 'initialization': 0}, 'cold_forbidden_operation_attempted')
    return {'schema': 'aster.synthetic-text-cold-recheck.v1', 'owner': owner,
            'source_sha256': envelope['source_sha256'], 'protocol_sha256': protocol_hash(),
            'curriculum_sha256': envelope['curriculum_sha256'], 'state_sha256': initial_state_digest,
            'child_pid': os.getpid(), 'parent_pid': parent_pid, 'separate_process': True,
            'runtime': runtime, 'models': checked, 'models_verified': len(checked),
            'training_calls': attempts['training'], 'rng_calls': attempts['rng'],
            'initialization_calls': attempts['initialization'], 'published_state_unchanged': True,
            'all_decisions_exact': True, 'all_parameter_bytes_and_counters_exact': True,
            'float_policy': locked_protocol()['cold_recheck'], 'float_comparison': differences,
            'engineering_recheck_passed': True, 'general_language_qualified': False,
            'method_superiority_established': False, 'scope': 'Single fixed synthetic two-label experiment',
            'guard_scope': 'Restoration and evaluation after runtime imports; no model initialization, training, or RNG calls. Not a whole-process RNG claim.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--owner', default=DEFAULT_OWNER)
    parser.add_argument('--parent-pid', required=True, type=int)
    args = parser.parse_args(argv)
    try:
        result = verify(args.state, args.owner, args.parent_pid)
        print(canonical(result).decode('ascii'))
        return 0
    except Exception:
        # Never echo hostile file contents, paths, or an upstream traceback.
        print('{"error":"cold_recheck_failed"}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
