"""Wholly fictional numeric task inputs; no person, memory or emotion labels."""
import hashlib

OWNER = 'aster-synthetic-component-test'
FIXTURE_SOURCE_SHA256 = hashlib.sha256(b'aster-fictional-task-v1: explicit numeric value lesson').hexdigest()


def event(owner=OWNER):
    features = {'goal_progress': 1.0, 'declared_expectation': 0.0, 'uncertainty': 0.25,
                'social_cooperation': 0.5, 'social_conflict': 0.0,
                'body_available': False, 'body_comfort': None}
    provenance = {k: None if k == 'body_comfort' else
                  {'source_id': 'aster-fictional-task', 'status': 'supplied'}
                  for k in features if k != 'body_available'}
    return {'owner_id': owner, 'event_id': 'synthetic-event-1', 'time_index': 0,
            'features': features, 'provenance': provenance}


def consequence(owner=OWNER, *, corrected=False):
    return {'owner_id': owner, 'event_id': 'synthetic-event-1',
            'consequence_id': 'correction-1' if corrected else 'outcome-1',
            'time_index': 2 if corrected else 1, 'value': -0.5 if corrected else 0.5,
            'status': 'corrected' if corrected else 'supplied',
            'source_id': 'aster-fictional-task', 'supersedes': 'outcome-1' if corrected else None}


def metadata(*, corrected=False):
    return {'attempt_id': 'attempt-2' if corrected else 'attempt-1',
            'experiment_id': 'aster-component-engineering', 'arm_id': 'numeric-value',
            'sequence': 2 if corrected else 1,
            'event_kind': 'value_correction' if corrected else 'value_update',
            'declared_event_status': 'corrected' if corrected else 'supplied',
            'source_id': 'aster-fictional-task', 'source_sha256': FIXTURE_SOURCE_SHA256,
            'supersedes_attempt_id': 'attempt-1' if corrected else None}
