"""Source-only independent experimental lineage above the exact 220 state.

No file IO, random initialization, owner rewrite or model call at import.
The original parent selection is restored first. A separate decoder restore
owns the branch arrays; the full parent state/metadata remain immutable bytes.
Codec ceiling support is framing only. Root must separately freeze the actual
method/data/schedule and qualify complete application/source/error/IO costs.
"""
import hashlib
import json
import struct
import numpy as np
import continuation_state as parent_state
import history_archive as parent_history
from dialogue_decoder import DialogueDecoder, PARAMETER_NAMES, vocabulary_hash
from routed_decoder import RoutingDecoder
from extended_update_journal import pack, unpack

PARENT_UPDATES, MAX_UPDATES, ROW_BYTES = 10720, 16384, 176
PARENT_STATE_CAP = 2346896
PARENT_METADATA_CAP, PARENT_HISTORY_CAP = 131072, 2752512
MODEL_CAP, SELECTION_CAP, MIGRATION_CAP = 103516, 16384, 32768
TAIL_HEADER = struct.Struct('<I')
STATE_HEADER = struct.Struct('<8sIIIIII')
STATE_MAGIC = b'NBMS228\x00'
STATE_CAP = 4194304
METHODS = ('FUNCTIONAL_POOL', 'QUERY_SELECTION')
FIELDS = {'schema', 'parent_owner', 'branch_owner', 'mode', 'method', 'root_seed',
    'parent_protocol_sha256', 'new_protocol_sha256', 'vocabulary_sha256',
    'parent_state_sha256', 'parent_metadata_sha256', 'parent_history_sha256',
    'previous_updates', 'selected_added_updates', 'selected_cumulative_stop',
    'codec_update_ceiling'}
HASHES = ('parent_protocol_sha256', 'new_protocol_sha256', 'vocabulary_sha256',
    'parent_state_sha256', 'parent_metadata_sha256', 'parent_history_sha256')
PARENT_META_FIELDS = {'schema','stage','condition','mode','owner','root_seed',
    'protocol_sha256','old_protocol_sha256','parameter_sha256','decoder_details',
    'state','history','archives','episodic_bank','completed_blind_queries_lifetime',
    'completed_exposed_fit_queries_lifetime','original_history_sha256',
    'original_history_manifest_sha256','episodic_retrieval_used',
    'personal_episodes_created','Maya_birth_or_age_demonstrated',
    'future_stage_requires_new_selection'}


def need(ok, why):
    if not ok: raise RuntimeError(why)


def sha(raw): return hashlib.sha256(raw).hexdigest()

def rows_sha256(rows):
    digest=hashlib.sha256()
    for raw in rows:
        need(type(raw) is bytes and len(raw)==ROW_BYTES,'Every complete original row')
        digest.update(raw)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')


def selection_bytes(value):
    need(type(value) is dict and set(value) == FIELDS and
        value['schema'] == 'newbrain.method228.branch-selection.v1',
        'Closed independently owned experimental selection')
    need(all(type(value[k]) is str and len(value[k]) == 64 and
        all(c in '0123456789abcdef' for c in value[k]) for k in HASHES),
        'Full parent and branch byte/protocol identities')
    need(value['parent_protocol_sha256'] != value['new_protocol_sha256'] and
        value['mode'] in ('ON', 'OFF') and value['method'] in METHODS,
        'Explicit different branch protocol and selected method/mode')
    need(all(type(value[k]) is str and value[k].isascii() and
        value[k].isprintable() and 1 <= len(value[k]) <= 64
        for k in ('parent_owner', 'branch_owner')) and
        value['parent_owner'] != value['branch_owner'],
        'Parent owner preserved; distinct experimental branch owner')
    need(type(value['root_seed']) is int and 0 <= value['root_seed'] < 2**32,
        'Original initialization seed, never a new initialization')
    need(type(value['previous_updates']) is int and
        value['previous_updates'] == PARENT_UPDATES and
        type(value['selected_added_updates']) is int and
        0 < value['selected_added_updates'] <= MAX_UPDATES-PARENT_UPDATES and
        type(value['selected_cumulative_stop']) is int and
        value['selected_cumulative_stop'] == PARENT_UPDATES+value['selected_added_updates'] and
        type(value['codec_update_ceiling']) is int and
        value['codec_update_ceiling'] == MAX_UPDATES,
        'Reviewed selected tail stays under the unchanged decoder ceiling')
    raw = canonical(value)
    need(len(raw) <= SELECTION_CAP, 'Whole selection, never clipped')
    return raw


def state_upper(added):
    need(type(added) is int and 0 <= added <= MAX_UPDATES-PARENT_UPDATES,
        'Finite declared tail extent')
    return (STATE_HEADER.size + SELECTION_CAP + PARENT_STATE_CAP +
        PARENT_METADATA_CAP + MODEL_CAP + MIGRATION_CAP + TAIL_HEADER.size + added*ROW_BYTES)


class BranchHold(Exception):
    def __init__(self, primary, retained):
        self.primary, self.retained = primary, retained
        super().__init__('Experimental branch failed; primary and available application state retained')


class BranchJournal:
    """Full authenticated 10720-row ancestry plus every new complete row.

    Parent byte rows are immutable; no full-prefix join/hash inside append.
    Original globals, parameter hashes, exposures and physical clocks continue.
    The branch owner is lineage metadata, not a rewrite of prior update rows.
    """
    def __init__(self, journal, parent_parameter_hash, selected_added, migration, retained):
        retained['branch_journal_partial'] = self
        self.parent, self.rows, self.active = journal, [], None
        self.selected_added = selected_added
        self.migration = migration
        need(type(migration) is dict and migration['parent_parameter_sha256']==parent_parameter_hash,
            'Explicit complete zero-SGD ancestry boundary')
        need(type(selected_added) is int and 0 < selected_added <= MAX_UPDATES-PARENT_UPDATES,
            'One exact selected finite tail')
        need(type(journal) is parent_state.CumulativeJournal,
            'Original returned parent journal class')
        self.parent_rows = journal.all_rows()
        self._authenticated_parent_rows = self.parent_rows
        self.initial_parameter_hash = journal.initial_parameter_hash
        need(type(self.parent_rows) is tuple and len(self.parent_rows) == PARENT_UPDATES and
            all(type(r) is bytes and len(r) == ROW_BYTES for r in self.parent_rows),
            'Every complete immutable parent row')
        self.parent_summary = journal.summary(parent_parameter_hash)
        need(self.parent_summary['updates'] == PARENT_UPDATES,
            'Authenticated full parent counter/hash chain')

    def completed_updates(self):
        need(self.parent_rows is self._authenticated_parent_rows and
            len(self.parent_rows) == PARENT_UPDATES and type(self.rows) is list and
            len(self.rows) <= self.selected_added,
            'Same immutable ancestry and selected complete tail')
        return PARENT_UPDATES+len(self.rows)

    def append(self, update, clock, retained):
        retained['branch_journal'] = self
        self.active = {'original_update': update, 'original_clock': clock, 'packed': None}
        retained['branch_journal_active'] = self.active
        try:
            need(self.completed_updates() < PARENT_UPDATES+self.selected_added and
                type(update) is dict and
                update.get('updates_completed') == self.completed_updates()+1,
                'Global ordinal without reset or skipped row')
            raw = pack(update, clock); self.active['packed'] = raw
            observed, timing = unpack(raw)
            need(observed == update and tuple(observed) == tuple(update) and timing == clock,
                'All binary64/hash/exposure/clock fields and insertion order preserved')
            prior, prior_clock = unpack(self.rows[-1] if self.rows else self.parent_rows[-1])
            expected_hash = prior['parameter_sha256_after'] if self.rows else self.migration['initial_branch_parameter_sha256']
            need(expected_hash == update['parameter_sha256_before'] and
                prior_clock['end_ns'] <= clock['start_ns'],
                'Full parent/branch parameter and physical clock continuity')
            self.rows.append(raw); self.completed_updates(); self.active = None
        except BaseException as primary:
            if not isinstance(primary,Exception):raise
            raise BranchHold(primary, retained) from primary

    def all_rows(self):
        self.completed_updates()
        return self.parent_rows+tuple(self.rows)

    def summary(self, final_parameter_hash):
        before = self.initial_parameter_hash
        exposures = dict(examples=0, prefix_tokens=0, target_tokens_including_eos=0)
        for index, raw in enumerate(self.parent_rows, 1):
            row, _ = unpack(raw)
            need(row['updates_completed']==index and row['parameter_sha256_before']==before,
                 'Every immutable parent hash/ordinal')
            before=row['parameter_sha256_after']
            for key in exposures:exposures[key]+=row['new_exposures'][key]
        need(before==self.migration['parent_parameter_sha256'] and
             self.migration['updates_added']==self.migration['examples_added']==self.migration['prefix_tokens_added']==self.migration['targets_added']==0 and
             self.migration['boundary_global_update']==PARENT_UPDATES,
             'Routing expansion is an explicit transformation, never a fabricated SGD row')
        before=self.migration['initial_branch_parameter_sha256']
        for index, raw in enumerate(self.rows, PARENT_UPDATES+1):
            row,_=unpack(raw)
            need(row['updates_completed']==index and row['parameter_sha256_before']==before,
                 'Complete post-migration tail hash/ordinal chain')
            before=row['parameter_sha256_after']
            for key in exposures:
                exposures[key]+=row['new_exposures'][key]
                need(exposures[key]<2**32,'Full finite cumulative exposure')
        need(before==final_parameter_hash,'Full two-part journal and transformation reach current model')
        return {'updates':self.completed_updates(),'exposures':exposures,
                'zero_SGD_migration':self.migration}

    def tail_bytes(self):
        self.completed_updates()
        need(all(type(r) is bytes and len(r) == ROW_BYTES for r in self.rows),
            'Every full branch row')
        return TAIL_HEADER.pack(len(self.rows))+b''.join(self.rows)

    @classmethod
    def from_tail_bytes(cls, raw, parent_journal, parent_hash, selected_added, migration, retained):
        retained['branch_tail_input_raw'] = raw
        need(type(raw) is bytes and TAIL_HEADER.size <= len(raw) <=
            TAIL_HEADER.size+selected_added*ROW_BYTES, 'Whole selected tail before allocation')
        count = TAIL_HEADER.unpack(raw[:TAIL_HEADER.size])[0]
        need(count <= selected_added and len(raw) == TAIL_HEADER.size+count*ROW_BYTES,
            'Exact row count and whole extent')
        result = cls(parent_journal, parent_hash, selected_added, migration, retained)
        for i in range(count):
            update, clock = unpack(raw[TAIL_HEADER.size+i*ROW_BYTES:TAIL_HEADER.size+(i+1)*ROW_BYTES])
            result.append(update, clock, retained)
        need(result.tail_bytes() == raw, 'Every complete tail byte roundtrips')
        return result


def restore_parent(raw, metadata_raw, history_raw, words, selection, retained):
    retained['parent220_raw_inputs'] = {'state': raw, 'metadata': metadata_raw, 'history': history_raw}
    need(type(raw) is bytes and 0 < len(raw) <= PARENT_STATE_CAP and sha(raw) == selection['parent_state_sha256'] and
        type(metadata_raw) is bytes and 0 < len(metadata_raw) <= PARENT_METADATA_CAP and
        sha(metadata_raw) == selection['parent_metadata_sha256'] and
        type(history_raw) is bytes and 0 < len(history_raw) <= PARENT_HISTORY_CAP and
        sha(history_raw) == selection['parent_history_sha256'],
        'Complete exact accepted parent220 originals')
    need(len(raw) >= parent_state.STATE_HEADER.size, 'Full parent frame header')
    magic, *sizes = parent_state.STATE_HEADER.unpack(raw[:parent_state.STATE_HEADER.size])
    need(magic == parent_state.STATE_MAGIC and
        parent_state.STATE_HEADER.size+sum(sizes) == len(raw),
        'Entire parent framing before selection slice')
    old_selection_raw = raw[parent_state.STATE_HEADER.size:parent_state.STATE_HEADER.size+sizes[0]]
    old_selection = json.loads(old_selection_raw)
    retained['parent220_original_selection'] = old_selection
    need(parent_state.selection_bytes(old_selection) == old_selection_raw and
        old_selection['new_protocol_sha256'] == selection['parent_protocol_sha256'] and
        old_selection['owner'] == selection['parent_owner'] and old_selection['mode'] == selection['mode'] and
        old_selection['root_seed'] == selection['root_seed'] and
        old_selection['vocabulary_sha256'] == selection['vocabulary_sha256'],
        'Restore actual parent selection/owner; never substitute branch identity')
    parent_retained = {}; retained['parent220_restore_partial'] = parent_retained
    bundle = parent_state.from_state_bytes(raw, words, old_selection, parent_retained)
    retained['parent220_restored_bundle'] = bundle
    meta = json.loads(metadata_raw); retained['parent220_metadata'] = meta
    history = parent_history.unpack(history_raw); retained['parent220_history_parts'] = history
    original_history, manifest, old_entries, entries, _, _ = history
    model = bundle['model']
    need(type(meta) is dict and set(meta) == PARENT_META_FIELDS and
        meta['schema'] == 'newbrain.foundation220.metadata.v1' and meta['stage'] == 'reopen' and
        meta['condition'] == 'COMMON-REVIEW' and meta['owner'] == selection['parent_owner'] and
        meta['mode'] == selection['mode'] and meta['root_seed'] == selection['root_seed'] and
        meta['protocol_sha256'] == selection['parent_protocol_sha256'] and
        meta['old_protocol_sha256'] == old_selection['old_protocol_sha256'] and
        meta['state']['sha256'] == sha(raw) and meta['state']['bytes'] == len(raw) and
        meta['history']['sha256'] == sha(history_raw) and meta['history']['bytes'] == len(history_raw) and
        meta['original_history_sha256'] == sha(original_history) and
        meta['original_history_manifest_sha256'] == sha(manifest) and
        meta['parameter_sha256'] == model.parameter_hash() and meta['decoder_details'] == model.parameter_details() and
        model.training_updates == PARENT_UPDATES and model.training_examples == 85760 and
        model.prefix_tokens_seen == 1037312 and model.target_tokens_seen == 171520 and
        meta['completed_blind_queries_lifetime'] == 548 and meta['completed_exposed_fit_queries_lifetime'] == 96 and
        type(meta['archives']) is dict and set(meta['archives']) == {'before-review','review-train','blind-post','reopen'} and
        len(meta['episodic_bank']) == (48 if selection['mode'] == 'ON' else 0) and
        meta['episodic_retrieval_used'] is False and meta['personal_episodes_created'] == 0 and
        meta['Maya_birth_or_age_demonstrated'] is False and meta['future_stage_requires_new_selection'] is True and
        len(old_entries) == 8 and len(entries) == 4,
        'Entire accepted parent model/counter/history/bank identity')
    for phase, pin in meta['archives'].items():
        report = dict(entries)['220/'+phase]
        need(len(report) == pin['bytes'] and sha(report) == pin['sha256'],
            'Every full parent report archive preserved')
    return bundle, meta


def migrate(parent_raw, parent_metadata_raw, parent_history_raw, words, selection, retained):
    retained['branch_selection'] = selection
    retained['branch_original_inputs'] = {'state': parent_raw, 'metadata': parent_metadata_raw, 'history': parent_history_raw}
    try:
        chosen = selection_bytes(selection)
        need(type(words) is tuple and len(words) == 42 and vocabulary_hash(words) == selection['vocabulary_sha256'],
            'Same exact ordered42 inventory; no implicit vocabulary growth')
        parent, _ = restore_parent(parent_raw, parent_metadata_raw, parent_history_raw, words, selection, retained)
        original_model = parent['model']
        parent_model_raw = original_model.state_bytes(selection['parent_protocol_sha256'])
        retained['parent220_current_model_raw'] = parent_model_raw
        model = RoutingDecoder.from_parent(original_model, selection['method'], retained)
        retained['branch_restored_model'] = model
        need(all(not np.shares_memory(original_model.p[name], model.p[name]) for name in PARAMETER_NAMES),
            'Independent branch arrays; retained parent model cannot mutate with branch SGD')
        migrated = model.state_bytes(selection['new_protocol_sha256']); retained['branch_initial_model_raw'] = migrated
        need(all(original_model.p[n].tobytes()==model.p[n].tobytes() for n in PARAMETER_NAMES),
             'All six inherited parameter arrays exact in BOTH routing arms')
        boundary={'schema':'newbrain.routing228.zero-SGD-migration.v1','architecture':selection['method'],
            'mapping':'base-exact-shared-D16-QKV-zero-R-bypass-v1',
            'parent_state_sha256':selection['parent_state_sha256'],
            'parent_parameter_sha256':original_model.parameter_hash(),
            'initial_branch_parameter_sha256':model.parameter_hash(),
            'boundary_global_update':PARENT_UPDATES,'updates_added':0,'examples_added':0,'prefix_tokens_added':0,'targets_added':0,
            'root_seed':model.root_seed,'parent_history_sha256':selection['parent_history_sha256'],
            'old_rows_sha256':rows_sha256(parent['journal'].all_rows()),'equivalence_report_pin':None}
        retained['migration_boundary']=boundary
        journal = BranchJournal(parent['journal'], original_model.parameter_hash(), selection['selected_added_updates'], boundary, retained)
        return {'selection_raw':chosen,'parent':{'state':parent_raw,'metadata':parent_metadata_raw},
                'model':model,'journal':journal,'migration':boundary}
    except BaseException as primary:
        if not isinstance(primary,Exception):raise
        raise BranchHold(primary, retained) from primary


def state_bytes(bundle, retained):
    retained['branch_bundle'] = bundle
    try:
        need(type(bundle) is dict and set(bundle) == {'selection_raw','parent','model','journal','migration'},
            'Closed independently owned branch bundle')
        selection = json.loads(bundle['selection_raw'])
        need(selection_bytes(selection) == bundle['selection_raw'], 'Whole unchanged selected lineage on save')
        parent, model, journal = bundle['parent'], bundle['model'], bundle['journal']
        need(type(parent) is dict and set(parent) == {'state','metadata'} and
            sha(parent['state']) == selection['parent_state_sha256'] and
            sha(parent['metadata']) == selection['parent_metadata_sha256'],
            'Full parent bytes unchanged forever')
        need(type(model) is RoutingDecoder and model.arm==selection['method'] and type(journal) is BranchJournal and
             journal.migration is bundle['migration'] and
            model.root_seed == selection['root_seed'] and
            journal.selected_added == selection['selected_added_updates'] and
            PARENT_UPDATES <= model.training_updates <= selection['selected_cumulative_stop'] and
            model.training_updates == journal.completed_updates(), 'Original global counter and selected branch tail')
        summary = journal.summary(model.parameter_hash())
        need(summary['exposures'] == {'examples': model.training_examples,'prefix_tokens': model.prefix_tokens_seen,
            'target_tokens_including_eos': model.target_tokens_seen}, 'All parent and branch exposures retained')
        current = model.state_bytes(selection['new_protocol_sha256']); tail = journal.tail_bytes()
        retained['branch_current_model_raw'], retained['branch_current_tail_raw'] = current, tail
        boundary = bundle['migration']; report_pin=boundary['equivalence_report_pin']
        need(type(report_pin) is dict and set(report_pin)=={'path','bytes','sha256'} and
             type(report_pin['bytes']) is int and 0<report_pin['bytes']<=2097152 and
             type(report_pin['path']) is str and 0<len(canonical(report_pin['path']))<=700 and
             type(report_pin['sha256']) is str and len(report_pin['sha256'])==64 and
             all(c in '0123456789abcdef' for c in report_pin['sha256']),
             'A complete actual equivalence report precedes any emitted branch state')
        migration_raw=canonical(boundary);retained['migration_boundary_raw']=migration_raw
        parts = (bundle['selection_raw'], parent['state'], parent['metadata'], current, tail, migration_raw)
        caps = (SELECTION_CAP, PARENT_STATE_CAP, PARENT_METADATA_CAP, MODEL_CAP,
            TAIL_HEADER.size+selection['selected_added_updates']*ROW_BYTES, MIGRATION_CAP)
        need(all(type(raw) is bytes and 0 < len(raw) <= cap for raw, cap in zip(parts, caps)),
            'Every complete component before concatenation')
        raw = STATE_HEADER.pack(STATE_MAGIC, *(len(r) for r in parts))+b''.join(parts)
        retained['branch_state_raw'] = raw
        need(len(raw) <= state_upper(selection['selected_added_updates']) <= STATE_CAP,
            'Full selected frame; codec support admits no lesson')
        at = STATE_HEADER.size+len(parts[0])
        need(raw[at:at+len(parent['state'])] == parent['state'], 'Exact whole parent frame embedded once')
        return raw
    except BaseException as primary:
        if not isinstance(primary,Exception):raise
        raise BranchHold(primary, retained) from primary


def from_state_bytes(raw, parent_history_raw, words, selection, retained):
    retained['branch_state_input_raw'] = raw; retained['branch_parent_history_input_raw'] = parent_history_raw
    try:
        selected = selection_bytes(selection)
        need(type(raw) is bytes and STATE_HEADER.size <= len(raw) <= state_upper(selection['selected_added_updates']),
            'Whole selected branch frame')
        magic, *sizes = STATE_HEADER.unpack(raw[:STATE_HEADER.size])
        caps = (SELECTION_CAP, PARENT_STATE_CAP, PARENT_METADATA_CAP, MODEL_CAP,
            TAIL_HEADER.size+selection['selected_added_updates']*ROW_BYTES, MIGRATION_CAP)
        need(magic == STATE_MAGIC and all(0 < n <= c for n, c in zip(sizes, caps)) and
            STATE_HEADER.size+sum(sizes) == len(raw), 'Closed full framing before allocation')
        parts = []; at = STATE_HEADER.size
        for n in sizes: parts.append(raw[at:at+n]); at += n
        retained['branch_state_parts'] = parts
        need(parts[0] == selected, 'Exact method/parent/branch selection')
        bundle = migrate(parts[1], parts[2], parent_history_raw, words, selection, retained)
        retained['branch_restored_bundle'] = bundle
        original_model, original_journal = bundle['model'], bundle['journal'].parent
        stored=json.loads(parts[5]);need(canonical(stored)==parts[5],'Canonical whole migration boundary')
        expected=dict(bundle['migration']); expected['equivalence_report_pin']=stored.get('equivalence_report_pin')
        need(stored==expected,'Exact immutable zero-SGD transform plus actual equivalence report pin')
        bundle['migration'].update(stored)
        journal = BranchJournal.from_tail_bytes(parts[4], original_journal, bundle['migration']['parent_parameter_sha256'],
            selection['selected_added_updates'], bundle['migration'], retained)
        model_class=RoutingDecoder
        model = model_class.from_state_bytes(parts[3], words, selection['new_protocol_sha256'])
        retained['branch_restored_current_model'] = model
        need(model.arm==selection['method'],'Stored architecture and selected comparison arm agree')
        need(model.state_bytes(selection['new_protocol_sha256']) == parts[3], 'Every current model/counter byte roundtrips')
        bundle['model'], bundle['journal'] = model, journal
        need(state_bytes(bundle, retained) == raw, 'Entire immutable ancestry and complete selected tail roundtrip')
        return bundle
    except BaseException as primary:
        if not isinstance(primary,Exception):raise
        raise BranchHold(primary, retained) from primary
