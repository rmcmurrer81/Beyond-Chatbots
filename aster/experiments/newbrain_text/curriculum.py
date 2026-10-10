"""Aster-owned, immutable synthetic teaching/evaluation specification.

Nothing is read from a user's NewBrain state or from external text. The entire
curriculum and protocol are hashed before a model is constructed. Held-out
prefixes are never supplied to train_step or exposed-feedback ordering.
"""
from copy import deepcopy
import hashlib
import json

SCHEMA = 'aster.synthetic-text-curriculum.v1'
DEFAULT_OWNER = 'synthetic_aster'
METHODS = ('INTERLEAVED', 'BLOCKED', 'ERROR_PRIORITIZED')
SPECIALS = ('<UNK>', '<BOS>', '<EOS>', '<USER>', '<ASSISTANT>', '<MEMORY>', '<QUERY>')
WORDS = SPECIALS + ('classify', 'please', 'now', 'red', 'blue', 'coral', 'azure', 'warm', 'cool')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


def _case(identity, words, answer):
    return {'id': identity, 'prefix': ['<USER>'] + words, 'answer': [answer]}


_CURRICULUM = {
    'schema': SCHEMA,
    'purpose': 'Synthetic two-label token generation; not conversation or real-world competence',
    'vocabulary': list(WORDS),
    'old': [
        _case('old_red', ['red'], 'warm'),
        _case('old_blue', ['blue'], 'cool'),
        _case('old_classify_red', ['classify', 'red'], 'warm'),
        _case('old_classify_blue', ['classify', 'blue'], 'cool'),
        _case('old_please_red', ['please', 'red'], 'warm'),
        _case('old_please_blue', ['please', 'blue'], 'cool'),
    ],
    'new': [
        _case('new_coral', ['coral'], 'warm'),
        _case('new_azure', ['azure'], 'cool'),
        _case('new_classify_coral', ['classify', 'coral'], 'warm'),
        _case('new_classify_azure', ['classify', 'azure'], 'cool'),
        _case('new_please_coral', ['please', 'coral'], 'warm'),
        _case('new_please_azure', ['please', 'azure'], 'cool'),
    ],
    'heldout': [
        _case('heldout_now_red', ['now', 'red'], 'warm'),
        _case('heldout_now_blue', ['now', 'blue'], 'cool'),
        _case('heldout_now_coral', ['now', 'coral'], 'warm'),
        _case('heldout_now_azure', ['now', 'azure'], 'cool'),
        _case('heldout_please_classify_coral', ['please', 'classify', 'coral'], 'warm'),
        _case('heldout_please_classify_azure', ['please', 'classify', 'azure'], 'cool'),
    ],
    'exposure': {
        'batch_count_per_teaching_split': 6,
        'batch_size': 8,
        'duplicate_copies_of_one_fixed_row_per_batch': 8,
        'warmup_row_order': 'row_index = update_index % 6, starting at zero',
        'warmup_updates': 64,
        'warmup_batch_appearances': [11, 11, 11, 11, 10, 10],
        'per_arm_new_row_copies': 48,
        'per_arm_old_row_copies': 16,
        'heldout_training_exposures': 0,
    },
}
_PROTOCOL = {
    'schema': 'aster.synthetic-text-protocol.v1',
    'root_seed': 221086,
    'seed_selection': 'One fixed seed; no seed search, retry, or outcome-driven tuning',
    'methods': list(METHODS),
    'warmup_updates': 64,
    'cycles_per_arm': 2,
    'passes_per_cycle': 3,
    'updates_per_cycle': 24,
    'actual_total_sgd_calls': 208,
    'final_arm_training_updates': 112,
    'order_adapter': 'aster_six_batch_relative_order.v1',
    'upstream_interface': 'method_order.pass_blocks only; relative offsets, no inherited counters',
    'upstream_probe_ledger': 'provenance/interface fixture only; never used as an Aster training ledger',
    'feedback_ledger': 'aster.exposed-text-probe.v1; actual fresh zero-based model counters',
    'feedback_ranking': 'wrong generated answer first, then descending target CE, then fixed row index',
    'feedback_source': 'All six new teaching rows immediately before each pass; no heldout gold',
    'baseline': 'Frozen old-only checkpoint; same checkpoint cloned into each arm without RNG',
    'probabilities': 'Complete binary64 distributions at BOS and after the one-word teacher target',
    'cold_recheck': {
        'parameter_bytes_and_counters': 'exact',
        'generated_tokens_and_decisions': 'exact',
        'float_absolute_tolerance': 1e-12,
        'float_relative_tolerance': 1e-12,
        'timeout_seconds': 30.0,
        'training_and_rng': 'forbidden; separate Python subprocess with guarded entry points',
    },
    'goal_rules': {
        'new_improves': 'final new exact-match count strictly exceeds frozen baseline count',
        'old_retained': 'every baseline-correct old case remains exactly correct; empty denominator is not a pass',
        'heldout_improves': 'final heldout exact-match count strictly exceeds frozen baseline count',
    },
}


def locked_curriculum():
    return deepcopy(_CURRICULUM)


def curriculum_hash():
    return hashlib.sha256(canonical(_CURRICULUM)).hexdigest()


def locked_protocol():
    result = deepcopy(_PROTOCOL)
    result['curriculum_sha256'] = curriculum_hash()
    return result


def protocol_hash():
    return hashlib.sha256(canonical(locked_protocol())).hexdigest()


def teaching_batches(split):
    """Explicitly duplicated exposure adapter, not upstream 48-row semantics."""
    if split not in ('old', 'new'):
        raise ValueError('teaching_split_required')
    return tuple(tuple({'prefix': tuple(row['prefix']), 'answer': tuple(row['answer'])}
                       for _ in range(8)) for row in _CURRICULUM[split])
