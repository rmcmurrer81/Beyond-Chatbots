"""One frozen CPU study. Failed goals are results, not reasons to retune."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from experiments.newbrain_text.source import inspect_sources, load_modules, runtime_info
from experiments.newbrain_text.training import observe, counters
from .protocol import (SEEDS, ARMS, WARMUP_UPDATES, ARM_UPDATES, STRENGTH,
    WARMUP_PROBES, ARM_PROBES, WORDS, canonical, specification, curriculum, protocol_hash,
    row_batch, schedule)
from .protection import estimate_importance, protected_copy, checkpoint_bytes, read_checkpoint


def source_binding():
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    files = {path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(root.iterdir()) if path.is_file()}
    for name in ('source.py', 'training.py', 'curriculum.py'):
        path = root.parent / 'newbrain_text' / name
        files[path.relative_to(repo).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'local_files': files, 'upstream': inspect_sources(),
            'sha256': hashlib.sha256(canonical(files)).hexdigest()}


def evaluate(model, rows):
    observations = []
    for row in rows:
        result = observe(model, row)
        observations.append({'id': row['id'], 'expected': row['answer'],
            'tokens': result['generation']['tokens'],
            'terminated_with_eos': result['generation']['terminated_with_eos'],
            'correct': result['exact_correct'], 'target_ce': result['target_loss']})
    return {'correct': sum(row['correct'] for row in observations), 'total': len(rows),
            'mean_target_ce': sum(row['target_ce'] for row in observations) / len(rows),
            'observations': observations}


def snapshot(model, splits=('old', 'new')):
    data = curriculum()
    return {'completed_updates': model.training_updates, 'parameter_sha256': model.parameter_hash(),
            'counters': counters(model), 'splits': {split: evaluate(model, data[split]) for split in splits}}


def transition(before, after):
    old = {row['id'] for row in before['observations'] if row['correct']}
    new = {row['id'] for row in after['observations'] if row['correct']}
    return {'baseline_correct': len(old), 'final_correct': len(new),
            'retained': len(old & new), 'lost': sorted(old - new), 'newly_correct': sorted(new - old),
            'retention_fraction': len(old & new) / len(old) if old else None}


def summarize(report):
    pairs = []
    for record in report['seeds']:
        baseline = record['baseline']['splits']
        for arm in ARMS:
            outcome = record['arms'][arm]
            outcome['transitions'] = {split: transition(baseline[split], outcome['final']['splits'][split])
                                      for split in ('old', 'new', 'heldout')}
            outcome['new_acquisition_demonstrated'] = bool(outcome['transitions']['new']['newly_correct'])
            outcome['retention_without_new_acquisition'] = (
                outcome['transitions']['old']['retained'] > 0 and not outcome['new_acquisition_demonstrated'])
        replay, protected = (record['arms'][arm] for arm in ('REPLAY', 'REPLAY_EWC'))
        differences = {split: protected['final']['splits'][split]['correct'] - replay['final']['splits'][split]['correct']
                       for split in ('old', 'new', 'heldout')}
        pairs.append({'seed': record['seed'], 'old_prequalified': record['old_prequalified'],
                      'correct_deltas_ewc_minus_replay': differences,
                      'retained_delta': protected['transitions']['old']['retained'] - replay['transitions']['old']['retained'],
                      'train_seconds_ratio_ewc_over_replay': protected['train_seconds'] / replay['train_seconds']})
    deltas = {split: sum(pair['correct_deltas_ewc_minus_replay'][split] for pair in pairs)
              for split in ('old', 'new', 'heldout')}
    qualified = [p for p in pairs if p['old_prequalified']]
    qualified_deltas = {split: sum(pair['correct_deltas_ewc_minus_replay'][split] for pair in qualified)
                        for split in ('old', 'new', 'heldout')}
    retained_delta = sum(pair['retained_delta'] for pair in pairs)
    acquired = sum(record['arms']['REPLAY_EWC']['final']['splits']['new']['correct'] - record['baseline']['splits']['new']['correct'] for record in report['seeds'])
    benefit = len(qualified) == len(SEEDS) and retained_delta > 0 and deltas['new'] >= 0 and deltas['heldout'] >= 0 and acquired > 0
    return {'pairs': pairs, 'all_seed_correct_deltas': deltas, 'retained_delta': retained_delta,
        'qualified_seed_count': len(qualified), 'failed_old_prequalification_seeds': [p['seed'] for p in pairs if not p['old_prequalified']],
        'qualified_seed_correct_deltas': qualified_deltas,
        'protected_new_net_acquisition': acquired, 'incremental_benefit_gate_passed': benefit,
        'interpretation': 'Narrow descriptive incremental benefit on this toy curriculum' if benefit else 'No demonstrated incremental benefit under the fixed descriptive gate',
        'independent_tasks': 1, 'initialization_replicates': len(SEEDS), 'statistical_significance_claimed': False}


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    runtime = runtime_info()
    binding = source_binding()
    freeze = {'schema': 'aster.retention.freeze.v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'protocol_sha256': protocol_hash(), 'specification': specification(), 'source_binding': binding}
    # Persist the protocol and source fingerprint before any RNG/model construction.
    (output / 'freeze.json').write_bytes(canonical(freeze))
    decoder, data = load_modules().decoder, curriculum()
    report = {'schema': 'aster.retention.study.v1', 'freeze': freeze, 'runtime': runtime,
              'seeds': [], 'actual_sgd_calls': 0, 'errors': [],
              'engineering_completed': False, 'production_backend_enabled': False}
    try:
        for seed in SEEDS:
            model = decoder.DialogueDecoder(WORDS, seed)
            warmup = []
            warmup_train_seconds = warmup_probe_seconds = 0.0
            for update in range(WARMUP_UPDATES + 1):
                if update in WARMUP_PROBES:
                    started = time.perf_counter()
                    warmup.append(snapshot(model))
                    warmup_probe_seconds += time.perf_counter() - started
                if update < WARMUP_UPDATES:
                    started = time.perf_counter()
                    model.train_step(row_batch(data['old'][update % 6]))
                    warmup_train_seconds += time.perf_counter() - started
                    report['actual_sgd_calls'] += 1
            baseline = snapshot(model)
            baseline_raw = model.state_bytes(protocol_hash())
            (output / f'{seed}-baseline.json').write_bytes(checkpoint_bytes(model))
            started = time.perf_counter()
            importance = estimate_importance(model, data['old'])
            fisher_seconds = time.perf_counter() - started
            record = {'seed': seed, 'warmup_curve': warmup, 'baseline': baseline,
                'warmup_train_seconds': warmup_train_seconds, 'warmup_probe_seconds': warmup_probe_seconds,
                'old_prequalified': baseline['splits']['old']['correct'] == 6,
                'fisher': {'seconds': fisher_seconds, 'per_example_gradient_calls': 6,
                    'sum': sum(float(value.sum()) for value in importance.values()),
                    'max': max(float(value.max()) for value in importance.values()),
                    'array_bytes': sum(value.nbytes for value in importance.values()),
                    'anchor_parameter_sha256': model.parameter_hash()}, 'arms': {}}
            report['seeds'].append(record)
            for arm_name in ARMS:
                arm = (protected_copy(model, importance, STRENGTH) if arm_name == 'REPLAY_EWC'
                       else decoder.DialogueDecoder.from_state_bytes(baseline_raw, WORDS, protocol_hash()))
                curve, train_seconds, probe_seconds = [], 0.0, 0.0
                train_schedule = schedule(arm_name)
                receipts = []
                for update in range(ARM_UPDATES + 1):
                    if update in ARM_PROBES:
                        start = time.perf_counter()
                        curve.append(snapshot(arm))
                        probe_seconds += time.perf_counter() - start
                    if update < ARM_UPDATES:
                        split, row = train_schedule[update]
                        start = time.perf_counter()
                        receipt = arm.train_step(row_batch(data[split][row]))
                        train_seconds += time.perf_counter() - start
                        report['actual_sgd_calls'] += 1
                        receipts.append({'split': split, 'row': row, 'data_plus_penalty_loss': receipt['loss'],
                                         'gradient_norm': receipt['gradient_norm'], 'clip_multiplier': receipt['clip_multiplier']})
                raw = checkpoint_bytes(arm)
                (output / f'{seed}-{arm_name}.json').write_bytes(raw)
                record['arms'][arm_name] = {'curve': curve, 'final': curve[-1],
                    'train_seconds': train_seconds, 'probe_seconds': probe_seconds,
                    'sgd_calls': ARM_UPDATES, 'training_gradient_calls': ARM_UPDATES,
                    'old_updates': sum(split == 'old' for split, _ in train_schedule),
                    'new_updates': sum(split == 'new' for split, _ in train_schedule),
                    'protection_array_bytes': 2 * record['fisher']['array_bytes'] if arm_name == 'REPLAY_EWC' else 0,
                    'checkpoint_sha256': hashlib.sha256(raw).hexdigest(),
                    'updates': receipts}
        # The first heldout observation occurs only after every training arm has ended.
        for record in report['seeds']:
            seed = record['seed']
            for name in ('baseline', *ARMS):
                model = read_checkpoint(output / f'{seed}-{name}.json')
                target = record['baseline'] if name == 'baseline' else record['arms'][name]['final']
                started = time.perf_counter()
                target['splits']['heldout'] = evaluate(model, data['heldout'])
                timing_target = record if name == 'baseline' else record['arms'][name]
                timing_target['final_holdout_seconds'] = time.perf_counter() - started
        if report['actual_sgd_calls'] != specification()['actual_campaign_sgd_calls']:
            raise ValueError('campaign_budget_mismatch')
        if source_binding() != binding:
            raise ValueError('source_changed_during_study')
        report['summary'] = summarize(report)
        report['actual_gradient_calls_including_fisher'] = report['actual_sgd_calls'] + len(SEEDS) * 6
        report['training_row_exposures_including_duplicates'] = report['actual_sgd_calls'] * 8
        report['additional_fisher_row_exposures'] = len(SEEDS) * 6
        report['engineering_completed'] = True
    except Exception as exc:
        report['errors'].append({'type': type(exc).__name__, 'code': 'study_failed_no_automatic_retry'})
        raise
    finally:
        (output / 'report.json').write_bytes(canonical(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({'engineering_completed': report['engineering_completed'],
                      'actual_sgd_calls': report['actual_sgd_calls'], 'summary': report['summary']}, sort_keys=True))


if __name__ == '__main__':
    main()
