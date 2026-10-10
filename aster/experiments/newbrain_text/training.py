"""Opt-in fixed-budget numerical lab; never imported by Aster production.

The upstream decoder is used byte-for-byte. This module owns synthetic data,
relative ordering adaptation, actual exposure accounting, and evaluation.
"""
import base64
import hashlib
import math
from .curriculum import (DEFAULT_OWNER, METHODS, WORDS, canonical, curriculum_hash,
                         locked_curriculum, locked_protocol, protocol_hash, teaching_batches)


def counters(model):
    return {key: getattr(model, key) for key in (
        'training_updates', 'training_examples', 'prefix_tokens_seen', 'target_tokens_seen')}


def _data(value):
    """JSON-native copy retaining every returned scalar/token without rounding."""
    import json
    return json.loads(canonical(value))


def observe(model, case):
    """Full greedy output plus whole distributions; never changes parameters."""
    import numpy as np
    before, counts = model.parameter_hash(), counters(model)
    generation = model.generate(tuple(case['prefix']))
    hidden = np.zeros(64)
    for identity in model._ids(tuple(case['prefix'])):
        hidden, _ = model._step(identity, hidden)
    hidden, _ = model._step(1, hidden)
    first, logits, normalizer = model._distribution(hidden)
    target = model.index[case['answer'][0]]
    loss = (normalizer - float(logits[target])) / 2
    hidden, _ = model._step(target, hidden)
    after_teacher, logits, normalizer = model._distribution(hidden)
    loss += (normalizer - float(logits[2])) / 2
    if model.parameter_hash() != before or counters(model) != counts:
        raise ValueError('observation_mutated_model')
    result = {
        'case_id': case['id'], 'prefix': list(case['prefix']), 'expected_tokens': list(case['answer']),
        'generation': _data(generation),
        'exact_correct': list(generation['tokens']) == case['answer'] and generation['terminated_with_eos'],
        'target_loss': float(loss), 'first_distribution': first.tolist(),
        'after_teacher_distribution': after_teacher.tolist(),
        'completed_updates': counts['training_updates'], 'parameter_sha256': before, 'error': None,
    }
    if not math.isfinite(loss) or loss < 0:
        raise ValueError('invalid_observation_loss')
    return result


def evaluate(model):
    curriculum = locked_curriculum()
    return {split: [observe(model, row) for row in curriculum[split]]
            for split in ('old', 'new', 'heldout')}


def _checkpoint(model):
    raw = model.state_bytes(protocol_hash())
    return {'encoding': 'base64', 'model_b64': base64.b64encode(raw).decode('ascii'),
            'model_sha256': hashlib.sha256(raw).hexdigest(),
            'parameter_sha256': model.parameter_hash(), 'counters': counters(model)}


def _counts(evaluation):
    return {split: {'correct': sum(r['exact_correct'] for r in rows), 'total': len(rows)}
            for split, rows in evaluation.items()}


def goal_results(baseline, result):
    oldcorrect = [r['case_id'] for r in baseline['old'] if r['exact_correct']]
    retained = [r['case_id'] for r in result['old'] if r['case_id'] in oldcorrect and r['exact_correct']]
    counts, prior = _counts(result), _counts(baseline)
    goals = {
        'new_improves': counts['new']['correct'] > prior['new']['correct'],
        'old_retained': bool(oldcorrect) and len(retained) == len(oldcorrect),
        'heldout_improves': counts['heldout']['correct'] > prior['heldout']['correct'],
        'old_correct_denominator': len(oldcorrect), 'old_correct_case_ids': oldcorrect,
        'old_retained_numerator': len(retained), 'old_retained_case_ids': retained,
        'counts': counts, 'baseline_counts': prior,
    }
    goals['all_scientific_goals_met'] = all(goals[k] for k in ('new_improves', 'old_retained', 'heldout_improves'))
    return goals


def run_experiment(owner=DEFAULT_OWNER):
    """Return (model envelope, full report) after exactly 208 actual SGD calls.

    No filesystem state is created here. The caller publishes only the whole
    validated result. There is one fixed seed and no result-driven tuning.
    """
    from .persistence import validate_owner
    from .source import PIN, inspect_sources, load_modules, runtime_info
    validate_owner(owner)
    curriculum, protocol = locked_curriculum(), locked_protocol()
    # Lock identities and admit exact source before constructing any model/RNG.
    binding = {'owner': owner, 'source_pin': PIN,
               'source_sha256': inspect_sources()['source_sha256'],
               'protocol_sha256': protocol_hash(), 'curriculum_sha256': curriculum_hash()}
    runtime = runtime_info()
    modules = load_modules()
    model = modules.decoder.DialogueDecoder(WORDS, protocol['root_seed'])
    initial_checkpoint = _checkpoint(model)
    initial_evaluation = evaluate(model)
    old_batches, new_batches = teaching_batches('old'), teaching_batches('new')
    warmup = []
    for index in range(protocol['warmup_updates']):
        receipt = model.train_step(old_batches[index % 6])
        warmup.append({'index': index, 'batch': index % 6, 'split': 'old', 'result': _data(receipt)})
    baseline_raw = model.state_bytes(protocol_hash())
    baseline_checkpoint, baseline_evaluation = _checkpoint(model), evaluate(model)
    models = {'initial': initial_checkpoint, 'baseline': baseline_checkpoint}
    arms = {}
    actual_calls = len(warmup)
    for method in METHODS:
        # Restore from actual warmup bytes; no reseeding and no counter assignment.
        arm = modules.decoder.DialogueDecoder.from_state_bytes(baseline_raw, WORDS, protocol_hash())
        probes, updates, orders = [], [], []
        for cycle in range(protocol['cycles_per_arm']):
            for new_pass in range(protocol['passes_per_cycle']):
                feedback = []
                for batch, case in enumerate(curriculum['new']):
                    observation = observe(arm, case)
                    feedback.append(observation)
                    probes.append({'schema': 'aster.exposed-text-probe.v1', 'ordinal': len(probes),
                                   'method': method, 'cycle': cycle, 'new_pass': new_pass,
                                   'batch': batch, 'observation': observation})
                ranked = tuple(sorted(range(6), key=lambda i: (
                    feedback[i]['exact_correct'], -feedback[i]['target_loss'], i)))
                chosen = ranked if method == 'ERROR_PRIORITIZED' else tuple(range(6))
                # Only this relative upstream interface is compatible with fresh counters.
                blocks = modules.method_order.pass_blocks(method, new_pass, chosen)
                orders.append({'cycle': cycle, 'new_pass': new_pass,
                               'completed_updates': arm.training_updates,
                               'priority_order': list(ranked), 'chosen_order': list(chosen),
                               'blocks': _data(blocks), 'evaluation_rows_used': False})
                for split, batch in blocks:
                    material = new_batches if split == 'new' else old_batches
                    receipt = arm.train_step(material[batch])
                    updates.append({'cycle': cycle, 'new_pass': new_pass, 'split': split,
                                    'batch': batch, 'result': _data(receipt)})
                    actual_calls += 1
        outcomes = evaluate(arm)
        models[method] = _checkpoint(arm)
        arms[method] = {'method': method, 'start_counters': baseline_checkpoint['counters'],
                        'end_counters': counters(arm), 'updates': updates, 'probe_ledger': probes,
                        'orders': orders, 'evaluation': outcomes,
                        'goals': goal_results(baseline_evaluation, outcomes), 'errors': []}
    if actual_calls != protocol['actual_total_sgd_calls']:
        raise ValueError('actual_sgd_quota_mismatch')
    report = {'schema': 'aster.synthetic-text-report.v1', **binding,
              'curriculum': curriculum, 'protocol': protocol, 'runtime': runtime,
              'initial': {'counters': initial_checkpoint['counters'], 'evaluation': initial_evaluation},
              'baseline': {'counters': baseline_checkpoint['counters'], 'evaluation': baseline_evaluation},
              'warmup_updates': warmup, 'arms': arms, 'actual_total_sgd_calls': actual_calls,
              'engineering_run_completed': True,
              'all_scientific_goals_met': all(arm['goals']['all_scientific_goals_met'] for arm in arms.values()),
              'scope': 'Opt-in synthetic experiment; no production imports, owner-state reuse, provider or network calls',
              'upstream_probe_ledger_used_for_actual_counters': False, 'errors': []}
    envelope = {'schema': 'aster.synthetic-text-state.v1', **binding, 'models': models,
                'report_sha256': hashlib.sha256(canonical(report)).hexdigest()}
    return envelope, report
