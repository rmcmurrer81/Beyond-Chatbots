"""Closed synthetic-owner motor intent for the opt-in physical voice experiment.

Controls are original numerical motor directions, not measured female anatomy.
There is no pitch command, oscillator seed stream, recording or model provider.
"""
import hashlib
import json
import math
import re

RATE = 48000
SUBSTEPS = 4
MAX_MS = 3000
MAX_GESTURES = 12
INTENT_CAP = 32768
PEAK = 0.20
FS_PER_SQRT_WATT = 2.0
PROFILE = 'aster_original_feminine_physical_v1'
SCHEMA = 'aster.physical-voice-intent.v1'
POSE_KEYS = ('tongue_position', 'tongue_height', 'jaw_opening', 'lip_rounding')
# Original broad area-control targets. Labels do not establish phonetic accuracy.
POSES = {
    'open': dict(zip(POSE_KEYS, (.50, .20, .85, .10))),
    'front': dict(zip(POSE_KEYS, (.80, .75, .35, .05))),
    'rounded': dict(zip(POSE_KEYS, (.25, .65, .30, .85))),
}


class VoiceError(ValueError):
    """Fixed refusal code, without user paths or raw input."""


def need(condition, code):
    if not condition:
        raise VoiceError(code)


def canonical(value):
    try:
        return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise VoiceError('invalid_json_data') from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def number(value, low, high):
    try:
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high
    except (ValueError, OverflowError):
        return False


def owner_id(value):
    need(type(value) is str and re.fullmatch(r'synthetic_[a-z][a-z0-9_]{0,47}', value) is not None,
         'synthetic_owner_required')
    return value


def is_hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def parse_json(raw, cap=INTENT_CAP):
    need(type(raw) is bytes and 0 < len(raw) <= cap, 'bounded_json_required')
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(VoiceError('nonfinite_json')))
        pending = [(result, 0)]
        nodes = 0
        while pending:
            value, depth = pending.pop()
            nodes += 1
            need(depth <= 32 and nodes <= 8192, 'json_complexity_refused')
            need(type(value) is not float or math.isfinite(value), 'nonfinite_json')
            children = value.values() if type(value) is dict else value if type(value) is list else ()
            pending.extend((child, depth + 1) for child in children)
        return result
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, VoiceError):
            raise
        raise VoiceError('invalid_json') from exc


def validate_origin(origin):
    need(type(origin) is dict and origin.get('kind') in ('manual_motor_intent', 'text_lab_observation'),
         'voice_origin_refused')
    if origin['kind'] == 'manual_motor_intent':
        need(set(origin) == {'kind'}, 'closed_manual_origin_required')
    else:
        need(set(origin) == {'kind', 'report_sha256', 'model_sha256', 'method', 'split',
             'case_index', 'observed_token', 'exact_correct', 'adapter'}, 'closed_lab_origin_required')
        need(is_hash(origin['report_sha256']) and is_hash(origin['model_sha256'])
             and origin['method'] in ('initial', 'baseline', 'INTERLEAVED', 'BLOCKED', 'ERROR_PRIORITIZED')
             and origin['split'] in ('old', 'new', 'heldout')
             and type(origin['case_index']) is int and 0 <= origin['case_index'] < 6
             and origin['observed_token'] in ('warm', 'cool') and type(origin['exact_correct']) is bool
             and origin['adapter'] == 'aster.text-label-to-physical-pose.v1', 'lab_origin_refused')


def validate(plan, owner=None):
    need(type(plan) is dict and set(plan) == {'schema', 'owner', 'profile', 'sample_rate',
         'substeps', 'source', 'velum', 'delivery_gain', 'origin', 'gestures'}, 'closed_voice_intent_required')
    owner_id(plan['owner'])
    need(owner is None or plan['owner'] == owner_id(owner), 'voice_owner_mismatch')
    need(plan['schema'] == SCHEMA and plan['profile'] == PROFILE, 'voice_protocol_mismatch')
    need(type(plan['sample_rate']) is int and plan['sample_rate'] == RATE
         and type(plan['substeps']) is int and plan['substeps'] == SUBSTEPS, 'sample_rate_refused')
    source = plan['source']
    need(type(source) is dict and set(source) == {'pressure_pa', 'stiffness_scale',
         'damping_kg_s', 'rest_half_gap_m'}, 'closed_source_required')
    for key, low, high in (('pressure_pa', 0., 1000.), ('stiffness_scale', 1., 2.),
                           ('damping_kg_s', .018, .024), ('rest_half_gap_m', .00014, .00022)):
        need(number(source[key], low, high), 'source_control_refused')
    need(number(plan['velum'], 0., 1.) and (plan['velum'] == 0. or plan['velum'] >= .01), 'velum_refused')
    need(number(plan['delivery_gain'], 0., 1.), 'delivery_gain_refused')
    validate_origin(plan['origin'])
    gestures = plan['gestures']
    need(type(gestures) is list and 1 <= len(gestures) <= MAX_GESTURES, 'gesture_count_refused')
    total_ms = 0
    for gesture in gestures:
        need(type(gesture) is dict and set(gesture) == {'duration_ms', 'pose'}, 'closed_gesture_required')
        need(type(gesture['duration_ms']) is int and 50 <= gesture['duration_ms'] <= 1500, 'duration_refused')
        total_ms += gesture['duration_ms']
        pose = gesture['pose']
        need(type(pose) is dict and set(pose) == set(POSE_KEYS)
             and all(number(pose[key], 0., 1.) for key in POSE_KEYS), 'pose_refused')
    need(total_ms <= MAX_MS, 'total_duration_refused')
    return parse_json(canonical(plan))


def gesture(pose='open', duration_ms=650):
    need(type(pose) is str and pose in POSES, 'pose_name_refused')
    return {'duration_ms': duration_ms, 'pose': dict(POSES[pose])}


def make_plan(gestures, owner='synthetic_aster', delivery_gain=1., pressure_pa=800.,
              stiffness_scale=2., damping_kg_s=.020, rest_half_gap_m=.00018, velum=0.):
    return validate({'schema': SCHEMA, 'owner': owner, 'profile': PROFILE, 'sample_rate': RATE,
                     'substeps': SUBSTEPS, 'source': {'pressure_pa': pressure_pa,
                     'stiffness_scale': stiffness_scale, 'damping_kg_s': damping_kg_s,
                     'rest_half_gap_m': rest_half_gap_m}, 'velum': velum,
                     'delivery_gain': delivery_gain, 'origin': {'kind': 'manual_motor_intent'},
                     'gestures': gestures})


def frame_count(plan):
    return sum(g['duration_ms'] * (RATE // 1000) for g in plan['gestures'])


def demo_plan(owner='synthetic_aster'):
    return make_plan([gesture(pose, 650) for pose in POSES], owner)
