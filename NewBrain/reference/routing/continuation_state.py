"""Inactive 220 migration: preserve the complete accepted 219 frame once.

The old decoder/219 restoration equations are unchanged. This module owns a
versioned append tail and never creates a random model or issues file IO.
Future ceiling support is framing only, not permission for another lesson.
"""
import hashlib
import json
import struct
from dialogue_decoder import DialogueDecoder, vocabulary_hash
import original_continuation_state as previous_stage
from extended_update_journal import pack, unpack

OLD_UPDATES, ADDED_UPDATES, SELECTED_STOP, MAX_UPDATES = 9184, 1536, 10720, 16384
ROW_BYTES = 176
OLD_STATE_CAP, OLD_METADATA_CAP, MODEL_CAP, SELECTION_CAP = 1860372, 131072, 76892, 8192
TAIL_HEADER = struct.Struct('<I')
STATE_HEADER = struct.Struct('<8sIIIII')
STATE_MAGIC = b'NBCS220\x00'
SELECTED_STATE_UPPER = STATE_HEADER.size + SELECTION_CAP + OLD_STATE_CAP + OLD_METADATA_CAP + MODEL_CAP + TAIL_HEADER.size + ADDED_UPDATES*ROW_BYTES
STATE_CEILING_UPPER = STATE_HEADER.size + SELECTION_CAP + OLD_STATE_CAP + OLD_METADATA_CAP + MODEL_CAP + TAIL_HEADER.size + (MAX_UPDATES-OLD_UPDATES)*ROW_BYTES
STATE_CAP = 4194304
FIELDS = {'schema','old_protocol_sha256','new_protocol_sha256','owner','mode','root_seed',
    'vocabulary_sha256','original_state_sha256','original_metadata_sha256','original_history_sha256',
    'previous_updates','selected_added_updates','selected_cumulative_stop','codec_update_ceiling'}
HASHES = ('old_protocol_sha256','new_protocol_sha256','vocabulary_sha256',
    'original_state_sha256','original_metadata_sha256','original_history_sha256')


def need(ok, why):
    if not ok: raise RuntimeError(why)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def selection_bytes(value):
    need(type(value) is dict and set(value)==FIELDS and value['schema']=='newbrain.foundation220.continuation-selection.v1',
         'Closed common-review selection')
    need(all(type(value[k]) is str and len(value[k])==64 and all(c in '0123456789abcdef' for c in value[k]) for k in HASHES),
         'Complete original and new protocol/byte identities')
    need(value['old_protocol_sha256']!=value['new_protocol_sha256'] and value['mode'] in ('ON','OFF') and
         type(value['owner']) is str and 0<len(value['owner'].encode('utf8'))<=256 and
         type(value['root_seed']) is int and 0<=value['root_seed']<2**32,'Same explicit owner/seed and versioned protocol')
    for k,n in (('previous_updates',OLD_UPDATES),('selected_added_updates',ADDED_UPDATES),
                ('selected_cumulative_stop',SELECTED_STOP),('codec_update_ceiling',MAX_UPDATES)):
        need(type(value[k]) is int and value[k]==n,'Fixed reviewed common-teaching stage')
    raw=canonical(value);need(len(raw)<=SELECTION_CAP,'Whole selection, never clipped');return raw


class ContinuationHold(Exception):
    def __init__(self, primary, retained):
        self.primary,self.retained=primary,retained
        super().__init__('220 continuation failed; original primary and available caller-owned state retained')


class CumulativeJournal:
    """Immutable authenticated 9184-row prefix plus every complete new row.

    The accepted 219 journal stays inside the complete original STATE bytes.
    Its returned row tuple/bytes are immutable. No whole-prefix join/hash or
    full cumulative unpack occurs inside the new SGD append loop. Complete
    validation is performed at restoration and final summary/serialization.
    This is a selected-source invariant, not protection from arbitrary code.
    """
    def __init__(self, old_journal, old_parameter_hash, retained):
        retained['common_journal_partial']=self
        self.previous,self.rows,self.active=old_journal,[],None
        self.initial_parameter_hash=old_journal.initial_parameter_hash
        self.previous_rows=old_journal.all_rows()
        self._authenticated_previous_rows=self.previous_rows
        need(type(old_journal) is previous_stage.CumulativeJournal and type(self.previous_rows) is tuple and
             len(self.previous_rows)==OLD_UPDATES and all(type(r) is bytes and len(r)==ROW_BYTES for r in self.previous_rows),
             'Full returned 9184 immutable original journal rows')
        self.previous_summary=old_journal.summary(old_parameter_hash)
        need(self.previous_summary['updates']==OLD_UPDATES,'Original global update count')

    def completed_updates(self):
        need(self.previous_rows is self._authenticated_previous_rows and len(self.previous_rows)==OLD_UPDATES and
             type(self.rows) is list and len(self.rows)<=ADDED_UPDATES,'Same original immutable row tuple and complete selected tail')
        return OLD_UPDATES+len(self.rows)

    def append(self, update, clock, retained):
        retained['common_journal']=self
        self.active={'original_update':update,'original_clock':clock,'packed':None};retained['journal_active']=self.active
        try:
            need(self.completed_updates()<SELECTED_STOP and type(update) is dict and
                 update.get('updates_completed')==self.completed_updates()+1,'Global ordinal, no counter reset')
            raw=pack(update,clock);self.active['packed']=raw
            observed,timing=unpack(raw)
            need(observed==update and tuple(observed)==tuple(update) and timing==clock,'Full binary64/hash/exposure/clock roundtrip')
            prior,prior_clock=unpack(self.rows[-1] if self.rows else self.previous_rows[-1])
            need(prior['parameter_sha256_after']==update['parameter_sha256_before'] and
                 prior_clock['end_ns']<=clock['start_ns'],'Complete parameter and physical monotonic-clock chain')
            self.rows.append(raw);self.completed_updates();self.active=None
        except BaseException as primary:raise ContinuationHold(primary,retained) from primary

    def all_rows(self):
        self.completed_updates();return self.previous_rows+tuple(self.rows)

    def summary(self, final_parameter_hash):
        before=self.initial_parameter_hash
        exposures=dict(examples=0,prefix_tokens=0,target_tokens_including_eos=0)
        for index,raw in enumerate(self.all_rows(),1):
            row,_=unpack(raw)
            need(row['updates_completed']==index and row['parameter_sha256_before']==before,'All original/new global rows and hashes')
            before=row['parameter_sha256_after']
            for key in exposures:
                exposures[key]+=row['new_exposures'][key];need(exposures[key]<2**32,'Whole cumulative counter domain')
        need(before==final_parameter_hash,'Entire journal reaches current parameters')
        return {'updates':self.completed_updates(),'exposures':exposures}

    def tail_bytes(self):
        self.completed_updates()
        need(all(type(r) is bytes and len(r)==ROW_BYTES for r in self.rows),'Every full appended row')
        return TAIL_HEADER.pack(len(self.rows))+b''.join(self.rows)

    @classmethod
    def from_tail_bytes(cls, raw, old_journal, old_parameter_hash, retained):
        need(type(raw) is bytes and TAIL_HEADER.size<=len(raw)<=TAIL_HEADER.size+ADDED_UPDATES*ROW_BYTES,'Complete selected tail before allocation')
        count=TAIL_HEADER.unpack(raw[:TAIL_HEADER.size])[0]
        need(count<=ADDED_UPDATES and len(raw)==TAIL_HEADER.size+count*ROW_BYTES,'Exact selected row count and extent')
        result=cls(old_journal,old_parameter_hash,retained)
        for i in range(count):
            update,clock=unpack(raw[TAIL_HEADER.size+i*ROW_BYTES:TAIL_HEADER.size+(i+1)*ROW_BYTES])
            result.append(update,clock,retained)
        need(result.tail_bytes()==raw,'Every appended serialized byte preserved');return result


def restore_original(raw, metadata_raw, words, selection, retained):
    retained['original219_state_raw']=raw;retained['original219_metadata_raw']=metadata_raw
    need(type(raw) is bytes and 0<len(raw)<=OLD_STATE_CAP and sha(raw)==selection['original_state_sha256'] and
         type(metadata_raw) is bytes and 0<len(metadata_raw)<=OLD_METADATA_CAP and sha(metadata_raw)==selection['original_metadata_sha256'],
         'Full accepted original219 state and metadata')
    magic,*sizes=previous_stage.STATE_HEADER.unpack(raw[:previous_stage.STATE_HEADER.size])
    need(magic==previous_stage.STATE_MAGIC and sum(sizes)+previous_stage.STATE_HEADER.size==len(raw),
         'Entire original219 framing before selection slice')
    old_selection_raw=raw[previous_stage.STATE_HEADER.size:previous_stage.STATE_HEADER.size+sizes[0]]
    old_selection=json.loads(old_selection_raw);retained['original219_selection']=old_selection
    need(previous_stage.selection_bytes(old_selection)==old_selection_raw and old_selection['new_protocol_sha256']==selection['old_protocol_sha256'] and
         old_selection['owner']==selection['owner'] and old_selection['mode']==selection['mode'] and
         old_selection['root_seed']==selection['root_seed'] and old_selection['vocabulary_sha256']==selection['vocabulary_sha256'],
         'Use the actual original219 selection; never substitute the new selection')
    old_bundle=previous_stage.from_state_bytes(raw,words,old_selection,retained);retained['original219_bundle']=old_bundle
    meta=json.loads(metadata_raw);retained['original219_metadata']=meta
    model=old_bundle['model']
    need(meta['schema']=='newbrain.foundation219.metadata.v1' and meta['stage']=='reopen' and meta['condition']=='CORRECTION' and
         meta['owner']==selection['owner'] and meta['mode']==selection['mode'] and meta['root_seed']==selection['root_seed'] and
         meta['protocol_sha256']==selection['old_protocol_sha256'] and meta['state']['sha256']==sha(raw) and meta['state']['bytes']==len(raw) and
         meta['history']['sha256']==selection['original_history_sha256'] and
         meta['parameter_sha256']==model.parameter_hash() and meta['decoder_details']==model.parameter_details() and
         model.training_updates==OLD_UPDATES and model.training_examples==73472 and model.prefix_tokens_seen==885760 and model.target_tokens_seen==146944 and
         meta['completed_blind_queries_lifetime']==320 and meta['completed_exposed_fit_queries_lifetime']==48 and
         set(meta['archives'])=={'before-correction','correction-train','blind-post','reopen'} and
         len(meta['episodic_bank'])==(48 if selection['mode']=='ON' else 0) and meta['episodic_retrieval_used'] is False,
         'Full completed219 same-owner current model/counter/history/bank identity')
    return old_bundle,meta


def migrate(original_state, original_metadata, words, selection, retained):
    retained['common_selection']=selection;retained['common_originals']={'state':original_state,'metadata':original_metadata}
    try:
        chosen=selection_bytes(selection)
        need(type(words) is tuple and len(words)==42 and vocabulary_hash(words)==selection['vocabulary_sha256'],'Same complete ordered42 inventory')
        old_bundle,meta=restore_original(original_state,original_metadata,words,selection,retained)
        model=old_bundle['model'];old_model=model.state_bytes(selection['old_protocol_sha256']);retained['original_current_model_raw']=old_model
        migrated=model.state_bytes(selection['new_protocol_sha256']);retained['migrated_model_raw']=migrated
        need(previous_stage.model_payload(old_model)==previous_stage.model_payload(migrated),'Exact parameter bits including signed zero, no initialization/SGD migration')
        journal=CumulativeJournal(old_bundle['journal'],model.parameter_hash(),retained)
        return {'selection_raw':chosen,'originals':{'state':original_state,'metadata':original_metadata},'model':model,'journal':journal}
    except BaseException as primary:raise ContinuationHold(primary,retained) from primary


def state_bytes(bundle,retained):
    retained['common_bundle']=bundle
    try:
        need(type(bundle) is dict and set(bundle)=={'selection_raw','originals','model','journal'},'Closed common-review bundle')
        selection=json.loads(bundle['selection_raw']);need(selection_bytes(selection)==bundle['selection_raw'],'Exact selection on save')
        originals,model,journal=bundle['originals'],bundle['model'],bundle['journal']
        need(set(originals)=={'state','metadata'} and sha(originals['state'])==selection['original_state_sha256'] and
             sha(originals['metadata'])==selection['original_metadata_sha256'],'Complete original serialized bytes remain unchanged')
        need(type(model) is DialogueDecoder and type(journal) is CumulativeJournal and model.root_seed==selection['root_seed'] and
             OLD_UPDATES<=model.training_updates<=SELECTED_STOP and model.training_updates==journal.completed_updates(),'Same model/global selected counter')
        summary=journal.summary(model.parameter_hash())
        need(summary['exposures']==dict(examples=model.training_examples,prefix_tokens=model.prefix_tokens_seen,
             target_tokens_including_eos=model.target_tokens_seen),'Full original and appended exposures retained')
        current=model.state_bytes(selection['new_protocol_sha256']);tail=journal.tail_bytes()
        retained['current_model_raw']=current;retained['current_journal_tail_raw']=tail
        parts=(bundle['selection_raw'],originals['state'],originals['metadata'],current,tail)
        caps=(SELECTION_CAP,OLD_STATE_CAP,OLD_METADATA_CAP,MODEL_CAP,TAIL_HEADER.size+ADDED_UPDATES*ROW_BYTES)
        need(all(type(r) is bytes and 0<len(r)<=c for r,c in zip(parts,caps)),'Every full selected component before concatenate')
        raw=STATE_HEADER.pack(STATE_MAGIC,*(len(r) for r in parts))+b''.join(parts);retained['state_raw']=raw
        need(len(raw)<=SELECTED_STATE_UPPER<3145728,'Complete selected frame; future ceiling admits no execution')
        at=STATE_HEADER.size+len(parts[0]);need(raw[at:at+len(originals['state'])]==originals['state'],'Entire original219 serialized frame embedded exactly once')
        return raw
    except BaseException as primary:raise ContinuationHold(primary,retained) from primary


def from_state_bytes(raw,words,selection,retained):
    retained['common_state_input_raw']=raw
    try:
        need(type(raw) is bytes and STATE_HEADER.size<=len(raw)<=SELECTED_STATE_UPPER,'Complete selected common-review state')
        magic,*sizes=STATE_HEADER.unpack(raw[:STATE_HEADER.size])
        caps=(SELECTION_CAP,OLD_STATE_CAP,OLD_METADATA_CAP,MODEL_CAP,TAIL_HEADER.size+ADDED_UPDATES*ROW_BYTES)
        need(magic==STATE_MAGIC and all(0<n<=c for n,c in zip(sizes,caps)) and STATE_HEADER.size+sum(sizes)==len(raw),'Closed frame before allocation')
        parts=[];at=STATE_HEADER.size
        for n in sizes:parts.append(raw[at:at+n]);at+=n
        retained['common_state_parts']=parts;need(parts[0]==selection_bytes(selection),'Exact selected new protocol/owner')
        bundle=migrate(parts[1],parts[2],words,selection,retained);retained['common_restored_bundle']=bundle
        old_model=bundle['model'];old_journal=bundle['journal'].previous
        journal=CumulativeJournal.from_tail_bytes(parts[4],old_journal,old_model.parameter_hash(),retained)
        model=DialogueDecoder.from_state_bytes(parts[3],words,selection['new_protocol_sha256']);retained['restored_current_model']=model
        need(model.state_bytes(selection['new_protocol_sha256'])==parts[3],'Complete current model/counter byte roundtrip')
        bundle['model'],bundle['journal']=model,journal
        need(state_bytes(bundle,retained)==raw,'Original frame and full new rows roundtrip without reset')
        return bundle
    except BaseException as primary:raise ContinuationHold(primary,retained) from primary
