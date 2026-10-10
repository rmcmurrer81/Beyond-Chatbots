"""Predeclared curriculum, budgets and interpretations. No numerical imports."""
import hashlib
import json
from copy import deepcopy
from experiments.newbrain_text.curriculum import WORDS, locked_curriculum

OWNER = 'synthetic_aster_retention'
SEEDS = (11, 29, 47, 71, 101)
ARMS = ('REPLAY', 'REPLAY_EWC', 'NEW_ONLY')
WARMUP_UPDATES = 384
ARM_UPDATES = 192
STRENGTH = 10.0
WARMUP_PROBES = (0, 24, 64, 128, 256, 384)
ARM_PROBES = (0, 24, 48, 96, 192)
SPEC = {
    'schema': 'aster.retention.protocol.v1', 'owner': OWNER,
    'aster_base_commit': '446ba6aa0096360fd17d33c9e0fc244d0690f324',
    'newbrain_inspected_commit': 'cbf43167b2a9f3df7b61c1e0d9497d26115a2c94',
    'seeds': list(SEEDS), 'arms': list(ARMS),
    'warmup_updates': WARMUP_UPDATES, 'arm_updates': ARM_UPDATES,
    'actual_campaign_sgd_calls': len(SEEDS) * (WARMUP_UPDATES + len(ARMS) * ARM_UPDATES),
    'actual_campaign_gradient_calls_including_fisher': 4830,
    'training_row_exposures_including_duplicates': 38400,
    'additional_fisher_row_exposures': 30,
    'learning_rate': 0.01, 'joint_gradient_clip_norm': 5.0,
    'ewc_strength': STRENGTH,
    'fisher_estimator': 'Mean of squared per-example gradients of teacher-forced mean token cross-entropy, over six unique old training rows at frozen warmup state. Each row includes one answer and EOS. No batch-gradient squaring, no model-sampled targets, no epsilon, layer rescaling or trace normalization.',
    'fisher_caveat': 'Empirical diagonal squared-gradient proxy, not the exact Fisher or a validated posterior precision; old optimum and diagonal approximations are not established.',
    'penalty': 'lambda / 2 * sum(F_i * (theta_i - anchor_i)^2); add lambda * F_i * (theta_i - anchor_i) to the data gradient before unchanged upstream joint norm clipping and SGD.',
    'warmup_order': 'Six old rows in cyclic order for 384 updates; each batch is eight identical copies of one row.',
    'replay_order': 'Repeat three new updates then one old update; independently cycle six row indices per split. Both primary arms receive exactly 144 new and 48 old updates, with identical order.',
    'new_only_order': '192 cyclic new updates; descriptive no-replay control has 48 more new updates than the primary arms, so is not an isolated EWC contrast.',
    'warmup_probes': list(WARMUP_PROBES), 'arm_probes': list(ARM_PROBES),
    'holdouts': 'Eight predeclared unseen wording prefixes are read only after every seed and arm has finished. No training, ranking, strength selection, early stopping or reseeding uses them.',
    'old_prequalification': 'All six old training prompts must be exactly correct after warmup. Failed seeds remain reported and are not replaced; all-seed and qualified-seed summaries are distinct.',
    'primary_comparison': 'Paired REPLAY_EWC minus REPLAY final exact old/new/holdout counts and retained baseline-correct old answers. Report every seed and aggregate; five initializations of one toy curriculum are not five independent tasks.',
    'claim_gate': 'Incremental benefit only if old retention is better, new accuracy and heldout accuracy are not worse in the paired aggregate, protected new accuracy strictly improves over its warmup baseline, and all five old baselines qualified. Otherwise no demonstrated incremental benefit. This fixed descriptive gate is not a significance test.',
    'acquisition': 'Report newly correct and lost new training cases relative to frozen warmup, exact counts and CE curves. Retention with no newly correct new cases is not learning.',
    'compute': 'Record wall-clock training and probe time separately, Fisher construction time, real SGD/gradient/example counts and protection array bytes. Runtime is one CPU execution, not a powered speed benchmark or process-memory measurement.',
    'scope': 'One small synthetic two-label task, no conversation, production activation, biology claim, private states, external models or real-world continual-learning claim.',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def curriculum():
    old = locked_curriculum()
    heldout = []
    for order in (('please', 'now'), ('classify', 'please', 'now')):
        for cue, answer in (('red', 'warm'), ('blue', 'cool'), ('coral', 'warm'), ('azure', 'cool')):
            heldout.append({'id': 'holdout_' + '_'.join((*order, cue)),
                            'prefix': ['<USER>', *order, cue], 'answer': [answer]})
    return {'vocabulary': list(WORDS), 'old': old['old'], 'new': old['new'], 'heldout': heldout}


def specification():
    return {**deepcopy(SPEC), 'curriculum': curriculum()}


def protocol_hash():
    return hashlib.sha256(canonical(specification())).hexdigest()


def row_batch(row, copies=8):
    return tuple({'prefix': tuple(row['prefix']), 'answer': tuple(row['answer'])} for _ in range(copies))


def schedule(arm):
    if arm not in ARMS:
        raise ValueError('unknown_arm')
    old = new = 0
    result = []
    for slot in range(ARM_UPDATES):
        split = 'old' if arm != 'NEW_ONLY' and slot % 4 == 3 else 'new'
        index = old if split == 'old' else new
        result.append((split, index % 6))
        if split == 'old':
            old += 1
        else:
            new += 1
    return tuple(result)
