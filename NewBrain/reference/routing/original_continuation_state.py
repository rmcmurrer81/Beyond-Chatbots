"""Inactive, versioned same-owner model/journal custody primitives.

The primitives issue no file IO, fresh random model initialization, training,
seed selection or runtime authority. Restore allocates arrays from exact bytes.
Importing this source later imports the selected decoder; no import is performed
by its source author. Connected caller/history/error/IO qualification is pending.
"""
import hashlib
import json
import struct
from dialogue_decoder import DialogueDecoder, vocabulary_hash
from original_update_journal import UpdateJournal as OriginalJournal
from original_update_journal import unpack as original_unpack
from extended_update_journal import pack, unpack

OLD_UPDATES = 8160
CORRECTION_UPDATES = 1024
SELECTED_STOP = 9184
MAX_CUMULATIVE_UPDATES = 16384
ROW_BYTES = 176
OLD_JOURNAL_BYTES = 44 + OLD_UPDATES * ROW_BYTES
MODEL_BYTES = 76892
OLD_METADATA_BYTES = 65536
MANIFEST_BYTES = 16384
JOURNAL_MANIFEST_BYTES = 8192
JOURNAL_HEADER = struct.Struct('<8sIII')
JOURNAL_MAGIC = b'NBCJ219\x00'
JOURNAL_BYTES = JOURNAL_HEADER.size + JOURNAL_MANIFEST_BYTES + OLD_JOURNAL_BYTES + (MAX_CUMULATIVE_UPDATES-OLD_UPDATES)*ROW_BYTES
STATE_HEADER = struct.Struct('<8sIIIII')
STATE_MAGIC = b'NBCS219\x00'
STATE_BYTES = STATE_HEADER.size + MANIFEST_BYTES + 2*MODEL_BYTES + OLD_METADATA_BYTES + JOURNAL_BYTES
SELECTION_FIELDS = {'schema', 'old_protocol_sha256', 'new_protocol_sha256', 'owner', 'mode',
                    'root_seed', 'vocabulary_sha256', 'original_model_sha256',
                    'original_metadata_sha256', 'original_journal_sha256',
                    'original_history_manifest_sha256', 'previous_updates',
                    'selected_added_updates', 'selected_cumulative_stop', 'codec_update_ceiling'}
HASH_FIELDS = ('old_protocol_sha256', 'new_protocol_sha256', 'vocabulary_sha256',
               'original_model_sha256', 'original_metadata_sha256', 'original_journal_sha256',
               'original_history_manifest_sha256')
OLD_METADATA_FIELDS = {'schema','protocol_sha256','mode','owner','root_seed',
    'initial_parameter_sha256','parameter_sha256','decoder_details','archives',
    'completed_blind_queries_lifetime','journal','completed_exposed_fit_queries',
    'personal_episodes_created','Maya_birth_or_age_demonstrated','stage','model',
    'condition','episodic_bank','episodic_retrieval_used','continuation_implemented',
    'future_cumulative_learning_migration_required'}


def need(ok, why):
    if not ok:
        raise RuntimeError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def selection_bytes(selection):
    need(type(selection) is dict and set(selection) == SELECTION_FIELDS, 'Closed prospective continuation selection')
    need(selection['schema'] == 'newbrain.foundation219.continuation-selection.v1', 'Versioned continuation selection')
    need(all(type(selection[k]) is str and len(selection[k]) == 64 and
             all(c in '0123456789abcdef' for c in selection[k]) for k in HASH_FIELDS), 'Exact source/archive/protocol hashes')
    need(selection['old_protocol_sha256'] != selection['new_protocol_sha256'], 'Explicit protocol migration, no relabelled old protocol')
    need(type(selection['owner']) is str and 0 < len(selection['owner'].encode('utf-8')) <= 256 and
         type(selection['mode']) is str and selection['mode'] in ('ON', 'OFF'), 'Finite selected original owner/mode')
    need(type(selection['root_seed']) is int and 0 <= selection['root_seed'] < 2**32, 'Original selected seed')
    for key, value in [('previous_updates', OLD_UPDATES), ('selected_added_updates', CORRECTION_UPDATES),
                       ('selected_cumulative_stop', SELECTED_STOP), ('codec_update_ceiling', MAX_CUMULATIVE_UPDATES)]:
        need(type(selection[key]) is int and selection[key] == value, 'Exact finite first correction stage')
    raw = canonical(selection)
    need(len(raw) <= JOURNAL_MANIFEST_BYTES, 'Full closed selection bytes')
    return raw


def owner_state(retained):
    need(type(retained) is dict, 'Caller-owned exact retained state required')
    return retained


class ContinuationHold(Exception):
    def __init__(self, primary, retained):
        self.primary, self.retained = primary, retained
        super().__init__('Continuation primitive failed; original primary and available owned objects retained')


class CumulativeJournal:
    """Full original journal bytes plus complete ordered extension rows.

    The container has a 16,384-row framing ceiling; this first selected stage
    rejects appends beyond 9,184. A later stage needs a new reviewed selection.
    """
    def __init__(self, original_raw, selection, initial_parameter_hash, retained):
        retained = owner_state(retained)
        retained['journal_original_raw'] = original_raw
        retained['journal_selection'] = selection
        retained['journal_partial'] = self
        self.original_raw, self.selection_raw = original_raw, None
        self.rows, self.active, self.original = [], None, None
        self.initial_parameter_hash = initial_parameter_hash
        try:
            self.selection_raw = selection_bytes(selection)
            need(type(original_raw) is bytes and len(original_raw) == OLD_JOURNAL_BYTES and
                 sha(original_raw) == selection['original_journal_sha256'], 'Full exact original 8160-row journal')
            retained['journal_phase'] = 'restore-original'
            self.original = OriginalJournal.from_state_bytes(original_raw, selection['old_protocol_sha256'])
            retained['restored_original_journal'] = self.original
            summary = self.original.summary(initial_parameter_hash, original_unpack(self.original.rows[-1])[0]['parameter_sha256_after'])
            need(summary['updates'] == OLD_UPDATES and self.original.state_bytes() == original_raw, 'Full original journal prefix roundtrip')
            self._check_original()
        except BaseException as primary:
            raise ContinuationHold(primary, retained) from primary

    def selection(self):
        need(type(self.selection_raw) is bytes and 0 < len(self.selection_raw) <= JOURNAL_MANIFEST_BYTES, 'Bounded complete selection before parse')
        value = json.loads(self.selection_raw)
        need(selection_bytes(value) == self.selection_raw, 'Exact canonical selection retained')
        return value

    def _check_original(self):
        selected = self.selection()
        need(type(self.original_raw) is bytes and len(self.original_raw) == OLD_JOURNAL_BYTES and
             sha(self.original_raw) == selected['original_journal_sha256'], 'Immutable original journal bytes')
        need(type(self.original) is OriginalJournal and self.original.state_bytes() == self.original_raw,
             'Every original raw row/header unchanged')
        need(type(self.rows) is list and len(self.rows) <= SELECTED_STOP-OLD_UPDATES and
             all(type(row) is bytes and len(row) == ROW_BYTES for row in self.rows), 'Finite full extension rows')
        return selected

    def completed_updates(self):
        self._check_original()
        return OLD_UPDATES + len(self.rows)

    def append(self, update, clock, retained):
        retained = owner_state(retained)
        retained['cumulative_journal'] = self
        self.active = {'original_update': update, 'original_clock': clock, 'packed': None}
        retained['journal_active'] = self.active
        try:
            self._check_original()
            need(len(self.rows) < SELECTED_STOP-OLD_UPDATES and type(update) is dict and
                 update.get('updates_completed') == OLD_UPDATES+len(self.rows)+1, 'Global ordinal; no reset/skipped update')
            raw = pack(update, clock)
            self.active['packed'] = raw
            observed, observed_clock = unpack(raw)
            need(observed == update and tuple(observed) == tuple(update) and observed_clock == clock,
                 'All original binary64/counter/hash/clock values retained')
            prior, prior_clock = unpack(self.rows[-1]) if self.rows else original_unpack(self.original.rows[-1])
            need(prior['parameter_sha256_after'] == update['parameter_sha256_before'] and
                 prior_clock['end_ns'] <= clock['start_ns'], 'Continuous parameter/monotonic-clock chain')
            self.rows.append(raw)
            self._check_original()
            self.active = None
        except BaseException as primary:
            raise ContinuationHold(primary, retained) from primary

    def all_rows(self):
        self._check_original()
        return tuple(self.original.rows) + tuple(self.rows)

    def summary(self, final_parameter_hash):
        self._check_original()
        before = self.initial_parameter_hash
        exposures = dict(examples=0, prefix_tokens=0, target_tokens_including_eos=0)
        for index, raw in enumerate(self.all_rows(), 1):
            row, _ = unpack(raw)
            need(row['updates_completed'] == index and row['parameter_sha256_before'] == before, 'Entire original and new parameter ordinal chain')
            before = row['parameter_sha256_after']
            for key in exposures:
                exposures[key] += row['new_exposures'][key]
                need(exposures[key] < 2**32, 'Complete cumulative exposure counter domain')
        need(before == final_parameter_hash, 'Complete journal reaches current parameter identity')
        return {'updates': self.completed_updates(), 'exposures': exposures}

    def state_bytes(self):
        self._check_original()
        raw = JOURNAL_HEADER.pack(JOURNAL_MAGIC, len(self.selection_raw), len(self.original_raw), len(self.rows)) + self.selection_raw + self.original_raw + b''.join(self.rows)
        need(len(raw) <= JOURNAL_BYTES, 'Full versioned cumulative journal extent')
        start = JOURNAL_HEADER.size + len(self.selection_raw)
        need(raw[start:start+len(self.original_raw)] == self.original_raw, 'Exact full serialized old prefix, including header')
        return raw

    @classmethod
    def from_state_bytes(cls, raw, selection, initial_parameter_hash, retained):
        retained = owner_state(retained); retained['cumulative_journal_raw'] = raw
        try:
            need(type(raw) is bytes and JOURNAL_HEADER.size <= len(raw) <= JOURNAL_BYTES, 'Bounded complete cumulative journal frame')
            magic, meta_size, old_size, count = JOURNAL_HEADER.unpack(raw[:JOURNAL_HEADER.size])
            need(magic == JOURNAL_MAGIC and 0 < meta_size <= JOURNAL_MANIFEST_BYTES and old_size == OLD_JOURNAL_BYTES and
                 count <= SELECTED_STOP-OLD_UPDATES and len(raw) == JOURNAL_HEADER.size+meta_size+old_size+count*ROW_BYTES,
                 'Exact version/count/extent before row allocation')
            at = JOURNAL_HEADER.size
            need(raw[at:at+meta_size] == selection_bytes(selection), 'Exact owner/protocol selection on restore')
            at += meta_size
            result = cls(raw[at:at+old_size], selection, initial_parameter_hash, retained)
            retained['cumulative_journal_restored'] = result; at += old_size
            for index in range(count):
                row, clock = unpack(raw[at+index*ROW_BYTES:at+(index+1)*ROW_BYTES])
                result.append(row, clock, retained)
            need(result.state_bytes() == raw, 'Complete old-prefix and new-row byte roundtrip')
            return result
        except BaseException as primary:
            raise ContinuationHold(primary, retained) from primary


def model_payload(raw):
    need(type(raw) is bytes and 12 < len(raw) <= MODEL_BYTES, 'Complete fixed42 model extent')
    size = struct.unpack('<I', raw[8:12])[0]
    need(0 < size <= 8192 and 12+size < len(raw), 'Complete model header extent')
    return raw[12+size:]


def migrate(original_model, original_metadata, original_journal, words, selection, retained):
    retained = owner_state(retained)
    originals = {'model': original_model, 'metadata': original_metadata, 'journal': original_journal}
    retained['originals'] = originals; retained['selection'] = selection
    try:
        selected_raw = selection_bytes(selection)
        need(type(words) is tuple and len(words) == 42 and vocabulary_hash(words) == selection['vocabulary_sha256'], 'Same complete ordered42 inventory')
        for name, cap in [('model', MODEL_BYTES), ('metadata', OLD_METADATA_BYTES), ('journal', OLD_JOURNAL_BYTES)]:
            raw = originals[name]
            need(type(raw) is bytes and 0 < len(raw) <= cap and sha(raw) == selection['original_'+name+'_sha256'], 'Every complete original serialized input')
        previous = json.loads(original_metadata); retained['previous_metadata'] = previous
        need(type(previous) is dict and set(previous) == OLD_METADATA_FIELDS and previous['schema'] == 'newbrain.foundation217.model-metadata.v1' and
             previous['stage'] == 'reopen' and previous['condition'] == 'LETTERS' and
             previous['owner'] == selection['owner'] and previous['mode'] == selection['mode'] and
             previous['root_seed'] == selection['root_seed'] and previous['protocol_sha256'] == selection['old_protocol_sha256'] and
             previous['model']['bytes'] == len(original_model) and previous['model']['sha256'] == sha(original_model) and
             previous['journal']['bytes'] == len(original_journal) and previous['journal']['sha256'] == sha(original_journal) and
             previous['completed_blind_queries_lifetime'] == 156 and previous['completed_exposed_fit_queries'] == 16 and
             type(previous['archives']) is dict and set(previous['archives']) == {'baseline','train','blind-post','reopen'} and
             type(previous['episodic_bank']) is list and len(previous['episodic_bank']) == (16 if selection['mode']=='ON' else 0) and
             previous['episodic_retrieval_used'] is False and previous['personal_episodes_created'] == 0 and previous['Maya_birth_or_age_demonstrated'] is False and
             previous['continuation_implemented'] is False and previous['future_cumulative_learning_migration_required'] is True,
             'Exact completed same-owner first letter lifecycle; original archive metadata retained')
        retained['migration_phase'] = 'restore-original-model'
        model = DialogueDecoder.from_state_bytes(original_model, words, selection['old_protocol_sha256'])
        retained['model'] = model
        need(model.state_bytes(selection['old_protocol_sha256']) == original_model and model.training_updates == OLD_UPDATES and
             model.root_seed == selection['root_seed'] and model.parameter_hash() == previous['parameter_sha256'] and
             model.parameter_details() == previous['decoder_details'], 'Complete original model/counter/parameter parity')
        journal = CumulativeJournal(original_journal, selection, previous['initial_parameter_sha256'], retained)
        retained['journal'] = journal
        need(journal.summary(model.parameter_hash())['exposures'] == dict(examples=model.training_examples,
             prefix_tokens=model.prefix_tokens_seen, target_tokens_including_eos=model.target_tokens_seen), 'All prior exposures unchanged')
        retained['migration_phase'] = 'new-protocol-serialization'
        new_model = model.state_bytes(selection['new_protocol_sha256']); retained['migrated_model_raw'] = new_model
        need(model_payload(new_model) == model_payload(original_model), 'Exact ordered parameter bytes including signed zero; no SGD/RNG migration')
        return {'selection_raw': selected_raw, 'originals': originals, 'model': model, 'journal': journal}
    except BaseException as primary:
        raise ContinuationHold(primary, retained) from primary


def state_bytes(bundle, retained):
    retained = owner_state(retained); retained['bundle'] = bundle
    try:
        need(type(bundle) is dict and set(bundle) == {'selection_raw','originals','model','journal'}, 'Closed continuation component bundle')
        need(type(bundle['selection_raw']) is bytes and len(bundle['selection_raw']) <= MANIFEST_BYTES and
             type(bundle['originals']) is dict and set(bundle['originals']) == {'model','metadata','journal'}, 'Closed original byte roles and selection extent')
        selection = json.loads(bundle['selection_raw'])
        need(selection_bytes(selection) == bundle['selection_raw'], 'Exact selection on save')
        originals, model, journal = bundle['originals'], bundle['model'], bundle['journal']
        need(type(model) is DialogueDecoder and type(journal) is CumulativeJournal and
             journal.selection_raw == bundle['selection_raw'] and originals['journal'] == journal.original_raw,
             'Owned model/journal and exact original prefix')
        for name, cap in [('model', MODEL_BYTES), ('metadata', OLD_METADATA_BYTES), ('journal', OLD_JOURNAL_BYTES)]:
            need(type(originals[name]) is bytes and 0 < len(originals[name]) <= cap and sha(originals[name]) == selection['original_'+name+'_sha256'], 'Original serialized bytes still preserved')
        need(model.root_seed == selection['root_seed'] and OLD_UPDATES <= model.training_updates <= SELECTED_STOP and
             model.training_updates == journal.completed_updates(), 'Exact cumulative selected update counter')
        summary = journal.summary(model.parameter_hash())
        need(summary['exposures'] == dict(examples=model.training_examples, prefix_tokens=model.prefix_tokens_seen,
             target_tokens_including_eos=model.target_tokens_seen), 'Full cumulative model/journal exposure parity')
        current = model.state_bytes(selection['new_protocol_sha256']); retained['current_model_raw'] = current
        journal_raw = journal.state_bytes(); retained['current_journal_raw'] = journal_raw
        parts = (bundle['selection_raw'], originals['model'], originals['metadata'], current, journal_raw)
        need(all(type(raw) is bytes for raw in parts) and len(parts[0]) <= MANIFEST_BYTES and
             len(parts[1]) <= MODEL_BYTES and len(parts[2]) <= OLD_METADATA_BYTES and len(parts[3]) <= MODEL_BYTES and
             len(parts[4]) <= JOURNAL_BYTES, 'Every complete component before concatenation')
        raw = STATE_HEADER.pack(STATE_MAGIC, *(len(part) for part in parts)) + b''.join(parts)
        retained['state_raw'] = raw
        need(len(raw) <= STATE_BYTES, 'Full versioned state bound')
        return raw
    except BaseException as primary:
        raise ContinuationHold(primary, retained) from primary


def from_state_bytes(raw, words, selection, retained):
    retained = owner_state(retained); retained['state_input_raw'] = raw
    try:
        need(type(raw) is bytes and STATE_HEADER.size <= len(raw) <= STATE_BYTES, 'Complete bounded state frame')
        magic, *sizes = STATE_HEADER.unpack(raw[:STATE_HEADER.size])
        caps = (MANIFEST_BYTES, MODEL_BYTES, OLD_METADATA_BYTES, MODEL_BYTES, JOURNAL_BYTES)
        need(magic == STATE_MAGIC and all(0 < n <= cap for n, cap in zip(sizes, caps)) and
             len(raw) == STATE_HEADER.size+sum(sizes), 'Exact complete frame before component allocation')
        parts=[];at=STATE_HEADER.size
        for size in sizes:
            parts.append(raw[at:at+size]);at+=size
        retained['state_parts'] = parts
        need(parts[0] == selection_bytes(selection), 'Exact owner/protocol lineage on reopen')
        need(sha(parts[1]) == selection['original_model_sha256'] and sha(parts[2]) == selection['original_metadata_sha256'], 'Authenticated original model/metadata before parsing')
        journal=CumulativeJournal.from_state_bytes(parts[4],selection,json.loads(parts[2])['initial_parameter_sha256'],retained)
        retained['restored_accepted_journal']=journal
        bundle = migrate(parts[1], parts[2], journal.original_raw, words, selection, retained)
        retained['restored_bundle'] = bundle
        model = DialogueDecoder.from_state_bytes(parts[3], words, selection['new_protocol_sha256']);retained['restored_current_model']=model
        need(model.state_bytes(selection['new_protocol_sha256']) == parts[3], 'Complete current model/counter byte roundtrip')
        bundle['model'],bundle['journal']=model,journal
        need(state_bytes(bundle,retained)==raw, 'Entire original/current component frame roundtrip')
        return bundle
    except BaseException as primary:
        raise ContinuationHold(primary, retained) from primary
