"""Closed, versioned Aster-owned vocal gesture protocol, using only stdlib."""
import hashlib
import json
import math
import re

RATE = 24000
MAX_MS = 8000
MAX_GESTURES = 32
PEAK = 0.20
PROFILE = 'aster_original_feminine_v1'
# Original approximate formant design values, not measured speaker anatomy.
VOWELS = {'a': [850, 1450, 2900], 'e': [550, 2100, 3000],
          'i': [330, 2550, 3300], 'o': [550, 950, 2800],
          'u': [360, 850, 2650]}


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
    except OverflowError:
        return False


def owner_id(value):
    need(type(value) is str and re.fullmatch(r'synthetic_[a-z][a-z0-9_]{0,47}', value) is not None,
         'synthetic_owner_required')
    return value


def is_hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def parse_json(raw, cap=32768):
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


def validate(plan, owner=None):
    need(type(plan) is dict and set(plan) == {'schema', 'owner', 'profile', 'sample_rate',
         'seed', 'gain', 'origin', 'gestures'}, 'closed_voice_intent_required')
    owner_id(plan['owner'])
    need(owner is None or plan['owner'] == owner_id(owner), 'voice_owner_mismatch')
    need(plan['schema'] == 'aster.voice-intent.v1' and plan['profile'] == PROFILE,
         'voice_protocol_mismatch')
    need(type(plan['sample_rate']) is int and plan['sample_rate'] == RATE, 'sample_rate_refused')
    need(type(plan['seed']) is int and 1 <= plan['seed'] <= 0xffffffff, 'seed_refused')
    need(number(plan['gain'], 0, 1), 'gain_refused')
    origin = plan['origin']
    need(type(origin) is dict and origin.get('kind') in ('manual_gestures', 'text_lab_observation'),
         'voice_origin_refused')
    if origin['kind'] == 'manual_gestures':
        need(set(origin) == {'kind'}, 'closed_manual_origin_required')
    else:
        need(set(origin) == {'kind', 'report_sha256', 'model_sha256', 'method', 'split',
             'case_index', 'observed_token', 'exact_correct', 'adapter'}, 'closed_lab_origin_required')
        need(is_hash(origin['report_sha256']) and is_hash(origin['model_sha256'])
             and origin['method'] in ('initial', 'baseline', 'INTERLEAVED', 'BLOCKED', 'ERROR_PRIORITIZED')
             and origin['split'] in ('old', 'new', 'heldout')
             and type(origin['case_index']) is int and 0 <= origin['case_index'] < 6
             and origin['observed_token'] in ('warm', 'cool') and type(origin['exact_correct']) is bool
             and origin['adapter'] == 'aster.text-label-to-vowel.v1', 'lab_origin_refused')
    gestures = plan['gestures']
    need(type(gestures) is list and 1 <= len(gestures) <= MAX_GESTURES, 'gesture_count_refused')
    total_ms = 0
    for g in gestures:
        need(type(g) is dict and set(g) == {'vowel', 'duration_ms', 'pitch_hz', 'voicing',
             'breathiness', 'open_quotient', 'formants_hz', 'bandwidths_hz'}, 'closed_gesture_required')
        need(type(g['vowel']) is str and g['vowel'] in (*VOWELS, 'silence'), 'vowel_refused')
        need(type(g['duration_ms']) is int and 40 <= g['duration_ms'] <= 2000, 'duration_refused')
        total_ms += g['duration_ms']
        need(type(g['pitch_hz']) is list and len(g['pitch_hz']) == 2
             and all(number(v, 80, 350) for v in g['pitch_hz']), 'pitch_refused')
        need(number(g['voicing'], 0, 1) and number(g['breathiness'], 0, 0.4)
             and number(g['open_quotient'], 0.35, 0.8), 'source_control_refused')
        f, b = g['formants_hz'], g['bandwidths_hz']
        need(type(f) is list and len(f) == 3 and all(number(v, 200, 4500) for v in f)
             and f[0] + 100 <= f[1] and f[1] + 100 <= f[2], 'formants_refused')
        need(type(b) is list and len(b) == 3 and all(number(v, 60, 500) for v in b), 'bandwidths_refused')
    need(total_ms <= MAX_MS, 'total_duration_refused')
    return parse_json(canonical(plan))  # Detached data; callers cannot mutate engine intent.


def gesture(vowel, duration_ms=450, pitch=(220, 205), voicing=1.0, breathiness=0.06,
            open_quotient=0.62, formants=None):
    need(vowel in (*VOWELS, 'silence'), 'vowel_refused')
    return {'vowel': vowel, 'duration_ms': duration_ms, 'pitch_hz': list(pitch),
            'voicing': voicing, 'breathiness': breathiness, 'open_quotient': open_quotient,
            'formants_hz': list(formants if formants is not None else VOWELS.get(vowel, VOWELS['a'])),
            'bandwidths_hz': [90, 120, 180]}


def make_plan(gestures, owner='synthetic_aster', gain=0.65):
    return validate({'schema': 'aster.voice-intent.v1', 'owner': owner, 'profile': PROFILE,
                     'sample_rate': RATE, 'seed': 221006, 'gain': gain,
                     'origin': {'kind': 'manual_gestures'}, 'gestures': gestures})


def demo_plan(owner='synthetic_aster'):
    gestures = []
    for vowel in VOWELS:
        gestures += [gesture(vowel), gesture('silence', 100)]
    return make_plan(gestures, owner)
