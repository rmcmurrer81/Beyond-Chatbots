"""Aster-owned, bounded copy-on-write custody for reviewed numeric components.

No pickle, exception reconstruction, tool execution, or upstream source edits.
Checkpoint checksums detect corruption, not an attacker able to rewrite a whole
internally consistent history. Atomic files require a trusted single writer and
an ordinary local filesystem; power-loss durability is not qualified.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from .component import canonical, need, VALUE_PATH, OBSERVER_PATH

SESSION_SCHEMA = 'aster.newbrain.session-state.v2'
MAX_CHECKPOINT = 2 * 1024 * 1024
MAX_OBSERVERS = 4


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw, maximum):
    need(type(raw) is bytes and 1 <= len(raw) <= maximum, 'Bounded complete canonical bytes required')
    try:
        data = json.loads(raw)
        need(canonical(data) == raw, 'Canonical complete data required')
    except (UnicodeError, RecursionError, TypeError) as error:
        raise ValueError('Canonical data-only input required') from error
    return data


def closed(data, keys):
    need(type(data) is dict and set(data) == set(keys.split()), 'Closed checkpoint schema required')


def input_raw(data, maximum):
    try:
        raw = canonical(data)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError('Bounded data-only observation input required') from error
    need(len(raw) <= maximum, 'Complete observation input exceeds budget')
    return raw


def error_data(error):
    if error is None:
        return None
    result = {'type': type(error).__module__ + '.' + type(error).__qualname__, 'message': str(error)}
    need(len(canonical(result)) <= 8192, 'Complete failure description exceeds budget')
    return result


def checkpoint(session, *, model=None, observers=None):
    model = session.model if model is None else model
    observers = session._histories if observers is None else observers
    state = model.snapshot()['raw']
    history = [{'experiment_id': key[0], 'arm_id': key[1], 'records': records}
               for key, records in sorted(observers.items())]
    raw = canonical({'schema': SESSION_SCHEMA, 'pin': session.source.pin,
                     'owner_id': model.owner_id,
                     'component_sha256': digest(session.source.sources[VALUE_PATH]),
                     'observer_sha256': digest(session.source.sources[OBSERVER_PATH]),
                     'state_sha256': digest(state), 'state': state.decode('ascii'),
                     'history_sha256': digest(canonical(history)), 'observers': history})
    need(len(raw) <= MAX_CHECKPOINT, 'Complete checkpoint exceeds budget; no history eviction')
    return raw


def atomic_write(path, raw, *, source, owner_id):
    """Write+flush+fsync a private sibling, then replace; no fallible postcommit IO.

    This is a lab single-writer primitive, not an OS-account adversary boundary.
    Existing corrupt, foreign-owner, cross-pin, or symlink destinations refuse.
    The original file is intact after any failure before successful os.replace.
    """
    target = Path(path)
    if target.is_symlink():
        raise ValueError('Symlink checkpoint destination refused')
    if target.exists():
        need(stat.S_ISREG(target.stat().st_mode), 'Regular checkpoint destination required')
        with target.open('rb') as handle:
            previous = handle.read(MAX_CHECKPOINT + 1)
        source.restore(previous, owner_id=owner_id)
    fd, pending = tempfile.mkstemp(prefix='.' + target.name + '.', suffix='.pending', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            need(handle.write(raw) == len(raw), 'Complete checkpoint write required')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, target)
        pending = None
    finally:
        if pending is not None:
            try:
                os.unlink(pending)
            except FileNotFoundError:
                pass


def boundary_raw(boundary):
    return None if boundary is None else boundary['raw'].decode('ascii')


def retained_record(observer, originals, ordinal):
    record = observer._records[-1]
    summary = observer.compact_record(record['attempt_id'])['data']
    return {'ordinal': ordinal, 'summary': summary,
            'inputs': {k: v.decode('ascii') for k, v in originals.items()},
            'event_raw': None if record['event_raw'] is None else record['event_raw'].decode('ascii'),
            'consequence_raw': None if record['consequence_raw'] is None else record['consequence_raw'].decode('ascii'),
            'before_raw': boundary_raw(record['before']), 'after_raw': boundary_raw(record['after']),
            'result_raw': None if record['result_raw'] is None else record['result_raw'].decode('ascii'),
            'primary': error_data(record['primary']), 'later': [error_data(e) for e in record['later']],
            'phase': record['phase'], 'phase_after': record.get('phase_after'),
            'disposition': 'COMMITTED' if record['status'] == 'COMPLETED' else 'ROLLED_BACK'}


def seed_record(packet):
    """Only prior fields read by the unchanged upstream correction/sequence hook."""
    summary = packet['summary']
    return {'attempt_id': summary['attempt_id'], 'metadata': summary['metadata'],
            'metadata_validated': summary['metadata_validated'], 'status': summary['status'],
            'event_raw': None if packet['event_raw'] is None else packet['event_raw'].encode('ascii'),
            'consequence_raw': None if packet['consequence_raw'] is None else packet['consequence_raw'].encode('ascii')}


class TransactionalObserver:
    """Owner-scoped wrapper; all mutations stage privately before publishing.

    Capacity/serialization/IO failures leave both live learner and history exact.
    Ordinary failed attempts retain a bounded ROLLED_BACK record and re-raise the
    original error. Captured staged boundaries remain factual; UNKNOWN stays null.
    Use checkpoint_path to atomically save each accepted success/failure record.
    """
    def __init__(self, session, key):
        self.session, self.key = session, key

    @property
    def owner_id(self):
        return self.session.model.owner_id

    @property
    def experiment_id(self):
        return self.key[0]

    @property
    def arm_id(self):
        return self.key[1]

    def history(self):
        with self.session._lock:
            return json.loads(canonical(self.session._histories[self.key]))

    def compact_record(self, attempt_id, *, maximum_bytes=8192):
        source = self.session.source
        source.value.identifier(attempt_id)
        source.value.integer(maximum_bytes, 1, source.observer.MAX_SUMMARY_BYTES)
        with self.session._lock:
            packet = next((p for p in self.session._histories[self.key]
                           if p['summary']['attempt_id'] == attempt_id), None)
            need(packet is not None, 'Exact retained attempt')
            raw = canonical(packet['summary'])
            if len(raw) > maximum_bytes:
                raise source.observer.ObservationRefused('Complete compact record oversized; no clipping or retry',
                                                        json.loads(raw), raw)
            return {'data': json.loads(raw), 'raw': raw, 'sha256': digest(raw), 'bytes': len(raw),
                    'publication_approved': False, 'private_owner_record_not_automatic_Git_payload': True}

    def observe_learn(self, meta, event, consequence, *, checkpoint_path=None):
        session, source = self.session, self.session.source
        originals = {k: input_raw(v, source.observer.MAX_INPUT_BYTES)
                     for k, v in [('metadata', meta), ('event', event), ('consequence', consequence)]}
        with session._lock:
            candidate = source.value.ValueLearner.restore(session.model.snapshot()['raw'],
                                                          expected_owner_id=self.owner_id)
            observer = source.observer.ValueEventObserver(candidate, experiment_id=self.experiment_id,
                                                           arm_id=self.arm_id)
            observer._records = [seed_record(p) for p in session._histories[self.key]]
            count = len(observer._records)
            failure = None
            try:
                result = observer.observe_learn(*(json.loads(originals[k])
                                                  for k in ('metadata', 'event', 'consequence')))
            except (source.value.SnapshotRefused, source.observer.ObservationRefused):
                # Complete refused bytes remain on the original error; never publish staged mutation.
                raise
            except Exception as error:
                if len(observer._records) == count:
                    raise
                failure = error
            # BaseException (interrupt/exit) is deliberately never converted to an accepted transaction.
            packet = retained_record(observer, originals,
                                     sum(len(v) for v in session._histories.values()))
            histories = dict(session._histories)
            histories[self.key] = session._histories[self.key] + [packet]
            committed_model = candidate if failure is None else session.model
            raw = checkpoint(session, model=committed_model, observers=histories)
            # Validate our own complete envelope before disk/live publication.
            restore_checkpoint(source, raw, owner_id=self.owner_id)
            if checkpoint_path is not None:
                atomic_write(checkpoint_path, raw, source=source, owner_id=self.owner_id)
            session.model, session._histories = committed_model, histories
            if failure is not None:
                raise failure
            return result


def validate_boundary(source, raw, summary, owner_id):
    if raw is None:
        need(summary is None, 'Unknown boundary must remain null')
        return None
    need(type(raw) is str and raw.isascii(), 'Complete boundary bytes required')
    raw = raw.encode('ascii')
    model = source.value.ValueLearner.restore(raw, expected_owner_id=owner_id)
    expected = {'state_blob_sha256': digest(raw), 'snapshot_bytes': len(raw),
                'parameter_only_sha256': source.value.parameter_digest(model.weights),
                'coefficients': list(model.weights), 'update_count': len(model.receipts),
                'backend': source.value.BACKEND, 'owner_id': owner_id}
    need(canonical(expected) == canonical(summary), 'Exact captured boundary required')
    return model


def validate_record(source, packet, *, owner_id, key, previous, final_model):
    closed(packet, 'ordinal summary inputs event_raw consequence_raw before_raw after_raw result_raw primary later phase phase_after disposition')
    source.value.integer(packet['ordinal'], 0, MAX_OBSERVERS * source.observer.MAX_ATTEMPTS - 1)
    s = packet['summary']
    closed(s, 'schema observer_component learner_backend declared_learner_source_freeze_sha256 declared_learner_source_sha256 loaded_source_authentication_qualified owner_id attempt_id metadata metadata_validated event_sha256 consequence_sha256 before after after_status parameter_delta operation_entered operation_returned operation_result_sha256 status primary_type later_types resource_and_clock_measurements resource_null_reason qwen_provider_calls_in_wrapper whole_application_provider_calls_qualified cold_restart_and_private_durable_custody_qualified scope')
    # These are upstream observation claims, preserved without upgrading their qualification flags.
    constants = {'schema': 'newbrain.value-event-observation.v1',
                 'observer_component': source.observer.OBSERVER_COMPONENT,
                 'learner_backend': source.value.BACKEND,
                 'declared_learner_source_freeze_sha256': source.observer.LEARNER_SOURCE_FREEZE,
                 'declared_learner_source_sha256': source.observer.LEARNER_SOURCE_SHA256,
                 'loaded_source_authentication_qualified': False, 'owner_id': owner_id,
                 'resource_and_clock_measurements': None,
                 'resource_null_reason': 'No authenticated resource/clock observer in this source',
                 'qwen_provider_calls_in_wrapper': 0, 'whole_application_provider_calls_qualified': False,
                 'cold_restart_and_private_durable_custody_qualified': False,
                 'scope': 'Only private current value component coefficients/update history; no complete brain/anatomical map/subjective emotion'}
    need(all(canonical(s[k]) == canonical(v) for k, v in constants.items()), 'Exact observer provenance/qualification required')
    for field in ('metadata_validated', 'operation_entered', 'operation_returned'):
        need(type(s[field]) is bool, 'Exact observer booleans required')
    source.value.identifier(s['attempt_id'])
    need(all(p['summary']['attempt_id'] != s['attempt_id'] for p in previous), 'Duplicate retained attempt refused')
    closed(packet['inputs'], 'metadata event consequence')
    inputs = {}
    for name, raw in packet['inputs'].items():
        need(type(raw) is str and raw.isascii(), 'Exact retained input bytes required')
        inputs[name] = parse(raw.encode('ascii'), source.observer.MAX_INPUT_BYTES)
    need(type(inputs['metadata']) is dict and inputs['metadata'].get('attempt_id') == s['attempt_id'], 'Attempt binds retained original metadata')
    if s['metadata'] is not None:
        need(canonical(s['metadata']) == canonical(inputs['metadata']), 'Original/copied metadata agreement')
    for name in ('event', 'consequence'):
        raw = packet[name + '_raw']
        need(raw is None or raw == packet['inputs'][name], 'Original/copied complete input agreement')
        need(s[name + '_sha256'] == (None if raw is None else digest(raw.encode('ascii'))), 'Observed input checksum mismatch')
    before = validate_boundary(source, packet['before_raw'], s['before'], owner_id)
    after = validate_boundary(source, packet['after_raw'], s['after'], owner_id)
    need(s['after_status'] == ('UNKNOWN' if after is None else 'CAPTURED'), 'Unknown/captured after boundary mismatch')
    need(before is not None or (after is None and not s['operation_entered']), 'Missing before cannot enter learning')
    expected_delta = None if before is None or after is None else [a-b for a, b in zip(after.weights, before.weights)]
    need(canonical(s['parameter_delta']) == canonical(expected_delta), 'Captured parameter delta mismatch')
    for errors in ([packet['primary']] if packet['primary'] is not None else [], packet['later']):
        need(type(errors) is list, 'Complete error list required')
        for error in errors:
            closed(error, 'type message')
            need(type(error['type']) is str and type(error['message']) is str and
                 1 <= len(error['type']) <= 512 and len(canonical(error)) <= 8192, 'Bounded data-only error required')
    need(s['primary_type'] == (None if packet['primary'] is None else packet['primary']['type']) and
         s['later_types'] == [e['type'] for e in packet['later']], 'Complete retained error types required')
    need(packet['phase'] in ('entry', 'before', 'input', 'operation') and
         packet['phase_after'] == (None if before is None else 'after'), 'Exact observation phase required')
    need(not s['operation_returned'] or s['operation_entered'], 'Returned operation must have entered')
    need(not s['operation_entered'] or s['metadata_validated'], 'Learning requires validated metadata')
    if s['metadata_validated']:
        m = s['metadata']
        source.value.closed(m, source.observer.META_KEYS)
        need(m['experiment_id'] == key[0] and m['arm_id'] == key[1], 'Observer identity mismatch')
        source.value.integer(m['sequence']); source.value.identifier(m['source_id']); source.observer.hex64(m['source_sha256'])
        need(all(m['sequence'] > p['summary']['metadata']['sequence'] for p in previous
                 if p['summary']['metadata_validated']), 'Retained strict sequence required')
        need(m['declared_event_status'] in source.value.EVENT_STATUSES and
             m['event_kind'] in ('value_update', 'value_correction'), 'Explicit retained metadata status/kind required')
        need(packet['event_raw'] is not None and packet['consequence_raw'] is not None, 'Validated complete inputs required')
        c = inputs['consequence']; e = inputs['event']
        source.value.event_vector(e, owner_id)
        source.value.closed(c, source.value.CONSEQUENCE_KEYS)
        if m['event_kind'] == 'value_correction':
            prior = next((p for p in previous if p['summary']['attempt_id'] == m['supersedes_attempt_id']), None)
            need(prior is not None and prior['disposition'] == 'COMMITTED' and c['status'] == 'corrected' and
                 json.loads(prior['event_raw'])['event_id'] == e['event_id'] and
                 json.loads(prior['consequence_raw'])['consequence_id'] == c['supersedes'],
                 'Correction retains completed same-event source chain')
        else:
            need(m['supersedes_attempt_id'] is None and c['status'] != 'corrected', 'Retained explicit correction kind required')
    result = packet['result_raw']
    need(result is None or (type(result) is str and result.isascii()), 'Complete result bytes required')
    need(s['operation_result_sha256'] == (None if result is None else digest(result.encode('ascii'))), 'Observed result checksum mismatch')
    need(s['operation_returned'] == (result is not None), 'Returned receipt must be retained')
    if before is not None:
        prefix = final_model.receipts[:len(before.receipts)]
        need(canonical(before.receipts) == canonical(prefix) and before.learning_rate == final_model.learning_rate,
             'Observed before must be a retained learner prefix')
        # Restore validates arithmetic without invoking learn or adding an exposure.
        observed_receipt = None
        if result is not None:
            observed_receipt = parse(result.encode('ascii'), source.value.MAX_BLOB_BYTES)
        elif after is not None and after.receipts != before.receipts:
            need(len(after.receipts) == len(before.receipts) + 1, 'At most one staged operation')
            observed_receipt = after.receipts[-1]
        expected_raw = packet['before_raw']
        if observed_receipt is not None:
            need(s['operation_entered'], 'Observed update requires entered operation')
            e, c = inputs['event'], inputs['consequence']
            vector = source.value.event_vector(e, owner_id)
            source.value.closed(c, source.value.CONSEQUENCE_KEYS)
            need(c['owner_id'] == owner_id and c['event_id'] == e['event_id'], 'Receipt input owner/event mismatch')
            bindings = {'event_id': e['event_id'], 'event_time_index': e['time_index'],
                        'feature_vector': list(vector), 'feature_provenance': e['provenance'],
                        'consequence_id': c['consequence_id'], 'source_id': c['source_id'],
                        'time_index': c['time_index'], 'status': c['status'], 'supersedes': c['supersedes'],
                        'target_declared_consequence': source.value.number(c['value'])}
            need(type(observed_receipt) is dict and all(canonical(observed_receipt.get(k)) == canonical(v)
                 for k, v in bindings.items()), 'Original operation receipt/input consistency required')
            rebuilt = json.loads(packet['before_raw'])
            rebuilt['receipts'].append(observed_receipt)
            rebuilt['weights'] = observed_receipt['weights_after']
            rebuilt['parameter_only_sha256'] = observed_receipt['parameter_only_after_sha256']
            rebuilt_raw = canonical(rebuilt)
            source.value.ValueLearner.restore(rebuilt_raw, expected_owner_id=owner_id)
            expected_raw = rebuilt_raw.decode('ascii')
        if after is not None:
            need(packet['after_raw'] in (packet['before_raw'], expected_raw),
                 'After boundary must match the bounded numeric receipt')
            if result is not None:
                need(packet['after_raw'] == expected_raw, 'Returned receipt agrees with captured after-state')
    if packet['disposition'] == 'COMMITTED':
        need(s['status'] == 'COMPLETED' and packet['primary'] is None and not packet['later'] and
             before is not None and after is not None and result is not None and s['metadata_validated'] and
             len(after.receipts) == len(before.receipts) + 1 and
             canonical(after.receipts) == canonical(final_model.receipts[:len(after.receipts)]),
             'Committed observation requires complete successful live boundaries')
    else:
        need(packet['disposition'] == 'ROLLED_BACK' and s['status'] == 'FAILED_OR_HELD' and
             packet['primary'] is not None, 'Failed attempt must remain explicitly rolled back')
    return before


def restore_checkpoint(source, raw, *, owner_id):
    from .component import ValueSession
    data = parse(raw, MAX_CHECKPOINT)
    closed(data, 'schema pin owner_id component_sha256 observer_sha256 state_sha256 state history_sha256 observers')
    need(data['schema'] == SESSION_SCHEMA, 'State schema migration required')
    need(data['owner_id'] == owner_id, 'Cross-owner state refused')
    need(data['pin'] == source.pin, 'Cross-pin state requires explicit reviewed migration')
    need(data['component_sha256'] == digest(source.sources[VALUE_PATH]) and
         data['observer_sha256'] == digest(source.sources[OBSERVER_PATH]), 'State component/observer provenance mismatch')
    need(type(data['state']) is str and data['state'].isascii(), 'Complete learner state required')
    state = data['state'].encode('ascii')
    need(data['state_sha256'] == digest(state), 'State checksum mismatch')
    model = source.value.ValueLearner.restore(state, expected_owner_id=owner_id)
    history = data['observers']
    need(type(history) is list and len(history) <= MAX_OBSERVERS, 'Bounded observer history required')
    need(data['history_sha256'] == digest(canonical(history)), 'Observer history checksum mismatch')
    session = ValueSession(source, model)
    ordinals, boundaries = [], []
    for group in history:
        closed(group, 'experiment_id arm_id records')
        key = (source.value.identifier(group['experiment_id']), source.value.identifier(group['arm_id']))
        need(key not in session._histories, 'Duplicate observer identity refused')
        records = group['records']
        need(type(records) is list and len(records) <= source.observer.MAX_ATTEMPTS, 'Bounded complete attempts required')
        previous = []
        for packet in records:
            before = validate_record(source, packet, owner_id=owner_id, key=key,
                                     previous=previous, final_model=model)
            ordinals.append(packet['ordinal'])
            boundaries.append((packet['ordinal'], None if before is None else len(before.receipts),
                               packet['disposition']))
            previous.append(packet)
        need([p['ordinal'] for p in records] == sorted(p['ordinal'] for p in records), 'Observer history order required')
        session._histories[key] = records
    need(sorted(ordinals) == list(range(len(ordinals))), 'Complete unique observation order required')
    minimum = 0
    for _, count, disposition in sorted(boundaries):
        if count is not None:
            need(count >= minimum, 'Observation chronology cannot replay committed updates')
            minimum = count + (1 if disposition == 'COMMITTED' else 0)
    need(checkpoint(session) == raw, 'Exact canonical checkpoint reconstruction required')
    return session
