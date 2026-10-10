"""Connected, inactive experimental teaching methods above accepted220.

All parent arrays/history are authenticated before independent branch restore.
Only independently reviewed supplied/composed new and exact old teachers enter probes or SGD. Fresh questions/gold never
enter the train role. No personal episode, retrieval feature or Maya adoption
is created by copying this experimental lineage. Root owns actual execution.
"""
from datetime import datetime, timezone
import hashlib
import json
import struct
import time
import traceback
import numpy as np
from dialogue_decoder import DialogueDecoder, PARAMETER_NAMES, vocabulary, vocabulary_hash
from routed_decoder import RoutingDecoder
from original_update_journal import UpdateJournal as OriginalJournal
import original_continuation_state as old_state
import original_history_archive as old_history
import continuation_state as parent_state
import history_archive as parent_history
from branch_state import BranchJournal,migrate,state_bytes,from_state_bytes,selection_bytes,STATE_HEADER,TAIL_HEADER,MODEL_CAP
import branch_history
from probe_ledger import ProbeLedger,HEADER as PROBE_HEADER,ROW as PROBE_ROW,CAP as PROBE_CAP
import method_order
from available_state import capture,acknowledge,extent,own_buffer,GRAPH_CAP,DATA_CAP,NODE_CAP,VISIT_CAP
from run_io import RunIO,canonical

LABELS=('a','b','c','unknown')
PHASES=('before-method','method-train','blind-post','reopen')
COMMON={'config','contract','unit_map','vocabulary','selection','state','metadata','history'}
ROLES={'before-method':COMMON|{'union_questions','old_questions','anchors','oov','migration_questions'},
    'method-train':COMMON|{'teacher_pool','old_teaching','before_report','pre_teaching_gate'},
    'blind-post':COMMON|{'fresh_questions','union_questions','old_questions','anchors','oov'},
    'reopen':COMMON|{'fresh_questions','union_questions','old_questions','anchors','oov','previous_report'}}
READ_CAPS={'config':16384,'contract':32768,'unit_map':32768,'vocabulary':4096,'selection':16384,'migration_questions':32768,
    'state':4194304,'metadata':131072,'history':12582912,
    'teacher_pool':65536,'old_teaching':32768,'pre_teaching_gate':65536,'union_questions':65536,
    'fresh_questions':16384,'old_questions':16384,
    'anchors':8192,'oov':8192,'before_report':2097152,'previous_report':2097152}
CONFIG_FIELDS={'schema','root_seed','parent_owners','branch_owners','parent_protocol_sha256',
    'contract_sha256','vocabulary_sha256','teacher_pool_sha256','old_teaching_sha256','unit_map_sha256',
    'cycles','added_updates','cumulative_updates'}
META_FIELDS={'schema','stage','condition','method','mode','owner','parent_owner','root_seed',
    'protocol_sha256','parent_protocol_sha256','parameter_sha256','decoder_details','state','history','archives',
    'episodic_bank','completed_blind_queries_lifetime','completed_exposed_fit_queries_lifetime',
    'exposed_teacher_probes','parent_state_sha256','parent_metadata_sha256','parent_history_sha256',
    'migration_report','migration_auxiliary_observations','episodic_retrieval_used','personal_episodes_created','Maya_birth_or_age_demonstrated',
    'foreign_state_adopted_into_Maya','future_stage_requires_new_selection','probe_ledger'}


def need(ok,why):
    if not ok:raise RuntimeError(why)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def exact_read(io,row,cap,known):
    need(type(row) is dict and set(row)=={'path','bytes','sha256'} and
        type(row['path']) is str and len(canonical(row['path']))<=700 and
        type(row['bytes']) is int and 0<row['bytes']<=cap,'Closed finite input pin before read')
    raw=io.read(row['path'],cap)
    need(len(raw)==row['bytes'] and sha(raw)==row['sha256'],'Whole selected physical input')
    acknowledge(known,raw,row);return raw


def lexical(text):
    need(type(text) is str and text.isascii() and 0<len(text)<=256 and
        all(c.islower() or c.isdigit() or c==' ' for c in text),'Exact bounded exercise text')
    words=tuple(text.split())
    need(0<len(words)<=32 and ' '.join(words)==text and all(w.isalnum() for w in words),'Canonical complete lexical words')
    return words


def prefix(row,words,allow_oov=False):
    need(type(row) is dict and set(row)=={'context','question'},'Blind context/question only')
    result=('<MEMORY>','stated')+lexical(row['context'])+('<QUERY>',)+lexical(row['question'])
    need(len(result)<=32 and (allow_oov or all(w in words for w in result)),'Full selected prefix, OOV only explicit control')
    return result


def stamp():return {'ns':time.perf_counter_ns(),'utc':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}


def encode_prefix(model,tokens,retained):
    if type(model) is RoutingDecoder:return model.encode_prefix(tokens,retained)
    need(type(model) is DialogueDecoder,'Only exact inherited parent or selected routed decoder')
    hidden=np.zeros(64,dtype=np.float64);retained['legacy_hidden']=hidden
    for identity in model._ids(tokens):
        hidden,_=model._step(identity,hidden);retained['legacy_hidden']=hidden
    return hidden


def observe(model,row,words,index,group,local,retained,allow_oov=False):
    tokens=prefix(row,words,allow_oov);start=stamp();before=model.parameter_hash()
    active={'row':index,'group':group,'group_row':local,'context':row['context'],'question':row['question'],
        'prefix':list(tokens),'start':start,'hidden':None,'probability':None,'generation':None,'end':None}
    retained['active_probe']=active
    hidden=encode_prefix(model,tokens,active);active['hidden']=hidden
    hidden,_=model._step(1,hidden);active['hidden']=hidden
    probability,_,_=model._distribution(hidden);active['probability']=probability
    scores=[float(probability[words.index(label)]) for label in LABELS]
    selected=max(range(4),key=lambda i:scores[i]);ordered=sorted(scores,reverse=True)
    generated=model.generate(tokens);active['generation']=generated;end=stamp();active['end']=end
    need(model.parameter_hash()==before,'Every receptive/generation observation makes zero updates')
    observed={'row':index,'group':group,'group_row':local,'context':row['context'],'question':row['question'],
        'prefix':list(tokens),'generation':generated,'first_distribution':{'dtype':'<f8','shape':[42],
        'raw_hex':np.asarray(probability,dtype='<f8').tobytes(order='C').hex()},
        'receptive_decision':{'labels':list(LABELS),'probabilities':scores,'chosen_label':LABELS[selected],
        'top_minus_second_margin':ordered[0]-ordered[1],
        'scope':'learned BOS probabilities restricted to four taught labels; no calibrated open-world rejection'},
        'clock':{'start_ns':start['ns'],'end_ns':end['ns'],'start_utc':start['utc'],'end_utc':end['utc']}}
    need(len(canonical(observed))<=4096,'Full observed row, never clipped')
    retained['active_probe']=None;return observed


def compare(observed,answer,words):
    tokens=observed['generation']['tokens'];prob=struct.unpack('<42d',bytes.fromhex(observed['first_distribution']['raw_hex']))
    expected=words.index(answer);chosen=words.index(tokens[0]) if tokens else 2
    return {'receptive_correct':observed['receptive_decision']['chosen_label']==answer,
        'generated_exact':tuple(tokens)==(answer,),'first_word_correct':bool(tokens) and tokens[0]==answer,
        'first_divergence_index':None if tuple(tokens)==(answer,) else (1 if tokens and tokens[0]==answer else 0),
        'expected_length':1,'generated_length':len(tokens),'empty':not tokens,
        'EOS':observed['generation']['terminated_with_eos'],'length_limit':observed['generation']['length_limit_reached'],
        'first_expected_probability':prob[expected],'first_chosen_probability':prob[chosen],'first_EOS_probability':prob[2],
        'expected_minus_chosen_margin':prob[expected]-prob[chosen],'expected_minus_EOS_margin':prob[expected]-prob[2]}


def teacher_probe(model,example,answer,words,method,mode,cycle,new_pass,row,variant,pool_row,retained):
    before=model.parameter_hash();start=stamp()
    active={'cycle':cycle,'new_pass':new_pass,'row':row,'variant':variant,'pool_row':pool_row,'prefix':example['prefix'],'answer':answer,
        'start':start,'hidden':None,'first':None,'first_logits':None,'first_log_normalizer':None,
        'after_teacher':None,'after_teacher_logits':None,'after_teacher_log_normalizer':None,'loss':None,'end':None}
    retained['active_teacher_probe']=active
    hidden=encode_prefix(model,example['prefix'],active);active['hidden']=hidden
    hidden,_=model._step(1,hidden);active['hidden']=hidden
    first,first_logits,first_normalizer=model._distribution(hidden)
    active.update(first=first,first_logits=first_logits,first_log_normalizer=first_normalizer)
    hidden,_=model._step(words.index(answer),hidden);active['hidden']=hidden
    second,second_logits,second_normalizer=model._distribution(hidden)
    active.update(after_teacher=second,after_teacher_logits=second_logits,after_teacher_log_normalizer=second_normalizer)
    # Exact one-row, two-target stable CE used by the unchanged decoder.
    loss=float(((first_normalizer-float(first_logits[words.index(answer)]))+(second_normalizer-float(second_logits[2])))/2)
    active['loss']=loss
    scores=[float(first[words.index(label)]) for label in LABELS];chosen=LABELS[max(range(4),key=lambda i:scores[i])]
    end=stamp();active['end']=end
    need(model.parameter_hash()==before,'Teacher probe changes no parameter, counter or optimizer state')
    result={'schema':'newbrain.method228.exposed-probe.v1','method':method,'mode':mode,
        'cycle':cycle,'new_pass':new_pass,'row':row,'variant':variant,'pool_row':pool_row,'updates_completed':model.training_updates,
        'chosen_label':chosen,'expected_label':answer,'receptive_wrong':chosen!=answer,'target_loss':loss,
        'first_distribution':{'dtype':'<f8','shape':[42],'raw_hex':np.asarray(first,dtype='<f8').tobytes(order='C').hex()},
        'after_teacher_distribution':{'dtype':'<f8','shape':[42],'raw_hex':np.asarray(second,dtype='<f8').tobytes(order='C').hex()},
        'parameter_sha256':before,'clock':{'start_ns':start['ns'],'end_ns':end['ns'],
        'start_utc':start['utc'],'end_utc':end['utc']}}
    retained['active_teacher_probe']=None;return result


def model_ranges(raw,start,size):
    model=raw[start:start+size];need(12<len(model)<=MODEL_CAP,'Whole selected model frame')
    metadata_size=struct.unpack('<I',model[8:12])[0]
    metadata=json.loads(model[12:12+metadata_size]);hidden=metadata['hidden']
    need(type(hidden) is int and hidden==64 and len(metadata['vocabulary'])==42, 'Exact inherited or routed E16/H64 model')
    routed=model[:8]==b'NBRQ228\x00'
    need((metadata.get('schema')=='newbrain.routing228.decoder-state.v1')==routed,
         'Exact routed frame/header identity before enumerating all ten arrays')
    at=start+12+metadata_size;ranges=[(start,size)]
    shapes=((42,16),(16,hidden),(hidden,hidden),(hidden,),(hidden,42),(42,))
    if routed:shapes+=((16,16),(64,16),(64,16),(16,64))
    for shape in shapes:
        n=1
        for d in shape:n*=d
        ranges.append((at,n*8));at+=n*8
    need(at==start+size,'All parameter bytes in original order');return ranges


def old219_ranges(raw,start,size):
    part=raw[start:start+size];magic,*sizes=old_state.STATE_HEADER.unpack(part[:old_state.STATE_HEADER.size])
    need(magic==old_state.STATE_MAGIC and sum(sizes)+old_state.STATE_HEADER.size==size,'Full original219 frame')
    at=start+old_state.STATE_HEADER.size;ranges=[(start,size)];offsets=[]
    for n in sizes:offsets.append(at);ranges.append((at,n));at+=n
    ranges.extend(model_ranges(raw,offsets[1],sizes[1]));ranges.extend(model_ranges(raw,offsets[3],sizes[3]))
    at=offsets[4];_,selected_size,old_size,count=old_state.JOURNAL_HEADER.unpack(raw[at:at+old_state.JOURNAL_HEADER.size])
    need(old_size==old_state.OLD_JOURNAL_BYTES and count==1024,'Complete original8160 plus1024 rows')
    old_at=at+old_state.JOURNAL_HEADER.size+selected_size;ranges.append((old_at,old_size))
    ranges.extend((old_at+44+i*176,176) for i in range(8160))
    ranges.extend((old_at+old_size+i*176,176) for i in range(count));return ranges


def parent220_ranges(raw,start,size):
    part=raw[start:start+size];magic,*sizes=parent_state.STATE_HEADER.unpack(part[:parent_state.STATE_HEADER.size])
    need(magic==parent_state.STATE_MAGIC and sum(sizes)+parent_state.STATE_HEADER.size==size,'Full original220 frame')
    at=start+parent_state.STATE_HEADER.size;ranges=[(start,size)];offsets=[]
    for n in sizes:offsets.append(at);ranges.append((at,n));at+=n
    ranges.extend(old219_ranges(raw,offsets[1],sizes[1]));ranges.extend(model_ranges(raw,offsets[3],sizes[3]))
    count=parent_state.TAIL_HEADER.unpack(raw[offsets[4]:offsets[4]+4])[0]
    need(count==1536 and sizes[4]==4+count*176,'Every complete original220 tail row')
    ranges.extend((offsets[4]+4+i*176,176) for i in range(count));return ranges


def branch_ranges(raw):
    magic,*sizes=STATE_HEADER.unpack(raw[:STATE_HEADER.size]);need(magic==b'NBMS228\x00' and sum(sizes)+STATE_HEADER.size==len(raw),'Full branch frame')
    at=STATE_HEADER.size;ranges=[(0,len(raw))];offsets=[]
    for n in sizes:offsets.append(at);ranges.append((at,n));at+=n
    ranges.extend(parent220_ranges(raw,offsets[1],sizes[1]));ranges.extend(model_ranges(raw,offsets[3],sizes[3]))
    count=TAIL_HEADER.unpack(raw[offsets[4]:offsets[4]+4])[0]
    need(count<=1536 and sizes[4]==4+count*176,'Every selected branch tail row')
    ranges.extend((offsets[4]+4+i*176,176) for i in range(count));return ranges


def register_ranges(known,raw,pin,ranges):
    ack=acknowledge(known,raw,pin)
    for at,n in ranges:extent(known,ack,at,n)


def history_ranges(raw,parent=False):
    if parent:
        parts=parent_history.unpack(raw);parent_at=0;parent_raw=raw;branch_entries=[];branch_spans=[]
    else:
        parent_raw,parts,branch_entries,branch_spans=branch_history.unpack(raw);parent_at=branch_history.HEADER.size
    original,manifest,old_entries,entries,old_spans,new_spans=parts
    ranges=[(0,len(raw)),(parent_at,len(parent_raw)),(parent_at+parent_history.HEADER.size,len(original)),
        (parent_at+parent_history.HEADER.size+old_history.HEADER.size,len(manifest))]
    ranges.extend((parent_at+parent_history.HEADER.size+at,n) for _,at,n in old_spans)
    ranges.extend((parent_at+at,n) for _,at,n in new_spans)
    ranges.extend((at,n) for _,at,n in branch_spans)
    return parent_raw,parts,branch_entries,ranges


def available(roots,known,local):
    return capture(roots,(DialogueDecoder,RoutingDecoder,BranchJournal,parent_state.CumulativeJournal,
        old_state.CumulativeJournal,OriginalJournal,ProbeLedger,RunIO),canonical,
        array_type=np.ndarray,known=known,local=local)


def failure(io,primary,retained,products,known,local):
    later=[]
    try:
        graph,binary=available({'primary':primary,'retained':retained,'products':products,'io':io},known,local)
        io.write('FAILED-AVAILABLE-DATA.bin',binary,DATA_CAP,emergency=True)
        io.write('FAILED-AVAILABLE-STATE.json',canonical(graph),GRAPH_CAP,emergency=True)
    except BaseException as error:later.append(error)
    try:
        io.write('ERROR.json',canonical({'original_traceback':''.join(traceback.format_exception(primary)),
            'later_tracebacks':[''.join(traceback.format_exception(e)) for e in later],
            'complete_supported_application_graph':not later,'full_external_and_local_reconstruction_required':True,
            'unreturned_decoder_numpy_native_locals_retained':False}),262144,emergency=True)
    except BaseException as error:later.append(error)
    if later:raise BaseExceptionGroup('Original method branch and capture failures',[primary]+later)
    raise primary


def teacher_examples(packet,words,schema):
    need(type(packet) is dict and set(packet)=={'schema','rows','fixed_batches_row_offsets'} and
        packet['schema']==schema and len(packet['rows'])==48,'Full exact exposed teacher packet')
    offsets=packet['fixed_batches_row_offsets']
    need(offsets==[list(b) for b in method_order.FIXED_OFFSETS],'Six complete selected8-row batches')
    examples=[]
    for row in packet['rows']:
        need(type(row) is dict and set(row)=={'context','question','answer'} and row['answer'] in LABELS,'Only supplied teacher labels')
        examples.append({'prefix':prefix({k:row[k] for k in ('context','question')},words),'answer':(row['answer'],)})
    need(sum(len(r['prefix']) for r in examples)==592 and
        all({label:sum(packet['rows'][i]['answer']==label for i in b) for label in LABELS}==dict.fromkeys(LABELS,2) for b in offsets),
        'Exactly592 prefixes and two/class each complete batch')
    return examples,[tuple(examples[i] for i in b) for b in offsets]


def pool_examples(packet,words,method,unit_map):
    clean=False
    expected_count=48 if clean else 192
    expected_schema='newbrain.foundation225.clean-teaching.v1' if clean else 'newbrain.foundation225.role-teaching.v1'
    expected_keys={'schema','rows','fixed_batches_row_offsets'} if clean else {'schema','rows'}
    need(type(packet) is dict and set(packet)==expected_keys and packet['schema']==expected_schema and
        type(packet['rows']) is list and len(packet['rows'])==expected_count,'Only the selected own teacher pool')
    if clean:need(packet['fixed_batches_row_offsets']==[list(b) for b in method_order.FIXED_OFFSETS],'Exact balanced unit batches')
    examples=[]
    for row in packet['rows']:
        need(type(row) is dict and set(row)=={'context','question','answer'} and row['answer'] in LABELS,'Only verified supplied/composed teacher labels')
        examples.append({'prefix':prefix({k:row[k] for k in ('context','question')},words),'answer':(row['answer'],)})
    for variant in range(1 if clean else 4):
        indices=[u if clean else 4*u+variant for u in range(48)]
        need(sum(len(examples[i]['prefix']) for i in indices)==(688 if clean else 928),'Complete same frozen prefix work; no padding')
        for batch in method_order.FIXED_OFFSETS:
            need({label:sum(packet['rows'][indices[u]]['answer']==label for u in batch) for label in LABELS}==dict.fromkeys(LABELS,2),'Every selected batch two per target label')
    if not clean:
        for unit in range(48):
            rows=packet['rows'][4*unit:4*unit+4]
            need(len({r['context'] for r in rows})==4 and len({r['answer'] for r in rows})==1 and
                len({r['question'] for r in rows})==1,'Four fact-order/distractor variants share one target selector and answer')
    need(sum(len(r['prefix']) for r in examples)==(688 if clean else 3712),'Complete own pool work')
    return examples


def check_unit_map(packet):
    need(type(packet) is dict and packet['schema']=='newbrain.routing228.shared-schedule.v1' and
        packet['methods']==list(method_order.METHODS) and packet['cycles']==64 and packet['updates']==1536 and
        packet['start_updates']==10720 and packet['end_updates']==12256 and packet['new_passes_per_cycle']==3 and
        packet['probes_per_branch']==9216 and packet['batch_size']==8 and packet['fixed_variant']==0 and
        packet['prefix_token_work']=={'FUNCTIONAL_POOL':216064,'QUERY_SELECTION':216064} and
        packet['probe_prefix_token_work']=={'FUNCTIONAL_POOL':178176,'QUERY_SELECTION':178176} and
        packet['teacher_presentations']==12288 and packet['total_teacher_targets']==24576 and
        packet['equal_compute_claimed'] is False and packet['no_padding'] is True,'Exact equal-exposure/prefix schedule; weighting arithmetic cost differs')
    need(packet['fixed_unit_batches']==[list(b) for b in method_order.FIXED_OFFSETS] and
        packet['old_fixed_batches']==[list(b) for b in method_order.FIXED_OFFSETS] and
        type(packet['units']) is list and len(packet['units'])==48,'Same balanced unit and old-review batch boundaries')
    for unit,row in enumerate(packet['units']):
        need(row['unit']==unit and row['clean_pool_row']==unit and row['role_pool_rows']==list(range(48+4*unit,48+4*unit+4)),
            'These map rows are UNION240 coordinates; ROLE source index is union minus48')
    return packet


def check_pre_teaching_gate(raw,config,protocol,method,mode,owner,before_pin,migration_pin,retained):
    gate=json.loads(raw);retained['pre_teaching_gate']=gate
    fields={'schema','configuration_sha256','eligible_for_teaching','runtime_authority','blocking_findings',
            'baseline_queries_per_branch','migration_pairs_per_branch','all_four_before_normal_returns_verified',
            'all_four_before_validators_verified','all300_cross_arm_bitwise_parity','all96_parent_migration_parity',
            'all_branches_zero_SGD','engineering_review','engineering_own','branches'}
    need(type(gate) is dict and set(gate)==fields and
         gate['schema']=='newbrain.routing228.pre-teaching-gate.v1' and
         gate['configuration_sha256']==protocol and gate['eligible_for_teaching'] is True and
         gate['runtime_authority'] is False and gate['blocking_findings']==[] and
         gate['baseline_queries_per_branch']==300 and gate['migration_pairs_per_branch']==96 and
         all(gate[k] is True for k in ('all_four_before_normal_returns_verified',
             'all_four_before_validators_verified','all300_cross_arm_bitwise_parity',
             'all96_parent_migration_parity','all_branches_zero_SGD')),
         'All four complete baseline jobs and separate engineering qualification precede ANY teaching')
    def fullpin(q):
        return (type(q) is dict and set(q)=={'path','bytes','sha256'} and
            type(q['path']) is str and 0<len(canonical(q['path']))<=700 and
            type(q['bytes']) is int and 0<q['bytes']<=16777216 and
            type(q['sha256']) is str and len(q['sha256'])==64 and
            all(c in '0123456789abcdef' for c in q['sha256']))
    need(fullpin(gate['engineering_review']) and fullpin(gate['engineering_own']),
         'Root authenticates complete engineering review and genuine normal own before binding this gate')
    need(type(gate['branches']) is list and len(gate['branches'])==4,'Exactly four baselines')
    for row,(width,bank) in zip(gate['branches'],((w,b) for w in ('FUNCTIONAL_POOL','QUERY_SELECTION') for b in ('ON','OFF'))):
        need(type(row) is dict and set(row)=={'method','mode','owner','before_report','migration_report','state','history'} and
             row['method']==width and row['mode']==bank and row['owner']==config['branch_owners'][width][bank] and
             all(fullpin(row[k]) for k in ('before_report','migration_report','state','history')),
             'All four ordered original branch owners and complete output identities')
        if (width,bank)==(method,mode):
            need(row['owner']==owner and row['before_report']==before_pin and row['migration_report']==migration_pin,
                 'No missing, false, foreign or configuration-mismatched gate can start this branch')
    return gate


def migration_observe(model,row,words,index,retained):
    observed=observe(model,row,words,index,'MIGRATION96',index,retained)
    active={'model':model,'observed':observed,'hidden':None,'probabilities':None,'logits':None}
    retained['migration_active']=active
    hidden=encode_prefix(model,prefix(row,words),active);active['hidden']=hidden
    hidden,_=model._step(1,hidden);active['hidden']=hidden
    probability,logits,_=model._distribution(hidden);active['probabilities']=probability;active['logits']=logits
    need(probability.astype('<f8').tobytes().hex()==observed['first_distribution']['raw_hex'],
         'Same model unchanged across migration internal observation')
    result={'observation':observed,'hidden':{'shape':[len(hidden)],'raw_hex':hidden.astype('<f8').tobytes().hex()},
            'logits':{'shape':[42],'raw_hex':logits.astype('<f8').tobytes().hex()}}
    retained['migration_active']=None
    return result


def verify_migration(bundle,parent,raw,words,io,retained,known,local):
    packet=json.loads(raw);retained['migration_question_packet']=packet
    need(type(packet) is dict and set(packet)=={'schema','rows'} and
         packet['schema']=='newbrain.routing228.migration-questions.v1' and len(packet['rows'])==96,
         'Exactly96 already supplied question-only inputs, no sealed labels')
    model=bundle['model']; boundary=bundle['migration']
    rows=[];report={'schema':'newbrain.routing228.migration-observations.v1','boundary_before':dict(boundary),
                   'rows':rows,'parent_observations':96,'branch_observations':96,'extra_SGD_updates':0,
                   'internal_BOS_reencodings':192,'generation_prefix_reencodings':192,'receptive_prefix_encodings':192,
                   'retained_supplied_prefix_tokens_per_encoding_pair':2368,
                   'sealed_answers_read':False,'scope':'finite supplied-prefix numerical preservation, not all floating inputs'}
    retained['migration_report']=report
    parent_before=parent.parameter_hash()
    branch_before=model.parameter_hash()
    for index,row in enumerate(packet['rows'],1):
        io.checkpoint('method.before-migration-parity',{'row':index,'updates':10720})
        old=migration_observe(parent,row,words,index,retained)
        item={'row':index,'parent':old,'branch':None,'comparison':None};rows.append(item)
        new=migration_observe(model,row,words,index,retained);item['branch']=new
        op=np.frombuffer(bytes.fromhex(old['observation']['first_distribution']['raw_hex']),dtype='<f8')
        npv=np.frombuffer(bytes.fromhex(new['observation']['first_distribution']['raw_hex']),dtype='<f8')
        ol=np.frombuffer(bytes.fromhex(old['logits']['raw_hex']),dtype='<f8')
        nl=np.frombuffer(bytes.fromhex(new['logits']['raw_hex']),dtype='<f8')
        oh=np.frombuffer(bytes.fromhex(old['hidden']['raw_hex']),dtype='<f8')
        nh=np.frombuffer(bytes.fromhex(new['hidden']['raw_hex']),dtype='<f8')
        retained['migration_comparison_arrays']={'old_probability':op,'new_probability':npv,'old_logits':ol,'new_logits':nl,'old_hidden':oh,'new_hidden':nh}
        pd=float(np.max(np.abs(op-npv)));ld=float(np.max(np.abs(ol-nl)));hd=float(np.max(np.abs(oh-nh[:64])))
        go,gn=old['observation']['generation'],new['observation']['generation']
        eq=all(go[k]==gn[k] for k in ('tokens','answer_text','terminated_with_eos','length_limit_reached','unknown_prefix_tokens'))
        item['comparison']={'probability_max_abs':pd,'logits_max_abs':ld,'hidden_max_abs':hd,'full_generation_equal':eq,
                            'full_BOS_hidden_bitwise_equal':oh.tobytes()==nh.tobytes(),
                            'full_logits_bitwise_equal':ol.tobytes()==nl.tobytes(),
                            'full_probabilities_bitwise_equal':op.tobytes()==npv.tobytes()}
        need(pd==ld==hd==0.0 and all(item['comparison'][k] for k in
             ('full_BOS_hidden_bitwise_equal','full_logits_bitwise_equal','full_probabilities_bitwise_equal')) and eq,
             'Exact zero-R bypass preserves full finite original forward bits, no tolerance tuning')
        need(len(canonical(item))<=16384,'Whole paired migration observation')
    need(parent.parameter_hash()==parent_before and model.parameter_hash()==branch_before and
         parent.training_updates==model.training_updates==10720,'Zero updates and both models unchanged')
    report['all96_equivalent']=True
    raw=canonical(report);retained['migration_report_raw']=raw
    need(len(raw)<=1638400,'Complete96 pair records and fixed report domain')
    own_buffer(local,raw,[])
    q=io.write('MIGRATION-REPORT.json',raw,2097152);acknowledge(known,raw,q)
    boundary['equivalence_report_pin']=q
    return q


def execute(experiment,*,io,prepared_census):
    need(type(io) is RunIO,'Same exact root-bootstrap RunIO class and instance')
    retained={'raw_inputs':{},'model':None,'bundle':None,'active_probe':None,'active_teacher_probe':None,
        'active_update':None,'current_clock':None,'generations':[],'training_fit':[],
        'method_decisions':[],'feedback_packet':None,'probe_ledger':None,
        'prepared_census':prepared_census,'restoration':{}}
    known={};local={};products={}
    try:
        need(type(experiment) is dict and set(experiment)=={'role','condition','method','mode','inputs'} and
            experiment['role'] in ROLES and experiment['condition']=='QUERY-SELECTION-COMPARISON' and
            experiment['method'] in method_order.METHODS and experiment['mode'] in ('ON','OFF'),
            'One closed selected independently owned method role')
        role,method,mode,inputs=(experiment[k] for k in ('role','method','mode','inputs'))
        need(type(inputs) is dict and set(inputs)==ROLES[role],'No undeclared or fresh train-role input')
        raw=retained['raw_inputs']
        for name in sorted(inputs):
            cap=READ_CAPS[name]
            if role=='before-method' and name=='state':cap=2346896
            if role=='before-method' and name=='history':cap=2752512
            raw[name]=exact_read(io,inputs[name],cap,known)
        config,contract,vocab,selection=(json.loads(raw[k]) for k in ('config','contract','vocabulary','selection'))
        unit_map=check_unit_map(json.loads(raw['unit_map']));retained['unit_map']=unit_map
        retained.update(config=config,contract=contract,selection=selection)
        need(type(config) is dict and set(config)==CONFIG_FIELDS and
            config['schema']=='newbrain.method228.configuration.v1' and
            all(type(config[k]) is int and config[k]==v for k,v in
                (('cycles',64),('added_updates',1536),('cumulative_updates',12256))) and
            config['contract_sha256']==sha(raw['contract']) and config['vocabulary_sha256']==sha(raw['vocabulary']) and
            config['unit_map_sha256']==sha(raw['unit_map']) and type(config['teacher_pool_sha256']) is dict and
            set(config['teacher_pool_sha256'])==set(method_order.METHODS) and
            type(config['parent_owners']) is dict and set(config['parent_owners'])=={'ON','OFF'} and
            len(set(config['parent_owners'].values()))==2 and
            type(config['branch_owners']) is dict and set(config['branch_owners'])==set(method_order.METHODS) and
            all(type(v) is dict and set(v)=={'ON','OFF'} for v in config['branch_owners'].values()),
            'One exact frozen shared schedule, teachers and separate branch controls')
        owners=[v[a] for v in config['branch_owners'].values() for a in ('ON','OFF')]
        need(len(set(owners))==4 and all(type(o) is str and o.isascii() and o.isprintable() and 1<=len(o)<=64 for o in owners) and
            not set(owners)&set(config['parent_owners'].values()),'Four fresh experimental owner IDs; parent IDs remain historical')
        need(contract['schema']=='newbrain.routing228.data-contract.v1' and
            contract['counts']=={'before':300,'post':324,'reopen':324,'union':240,'old':48,'anchors':6,'OOV':6,
                'fresh':24,'fresh_known':18,'fresh_rejection':6,'query_all_heads':3792,'fit_all_heads':960} and
            contract['own_fit']=={'FUNCTIONAL_POOL':240,'QUERY_SELECTION':240} and
            contract['prefix_limit']==32 and contract['generation_limit']==16 and
            contract['private_gold_in_training_or_forward_inputs'] is False and
            type(contract['confirmed_fresh_data']) is dict and set(contract['confirmed_fresh_data'])=={'path','bytes','sha256'},
            'Final connected immutable data contract resolves independently frozen confirmation; teaching-only null is refused')
        need(vocab['schema']=='newbrain.foundation217.training-only-vocabulary.v1','Original ordered common inventory schema')
        words=vocabulary(tuple(vocab['vocabulary']));need(len(words)==42,'Unchanged exact42 inventory')
        protocol=sha(raw['config']);owner=config['branch_owners'][method][mode];parent_owner=config['parent_owners'][mode]
        need(selection_bytes(selection)==raw['selection'] and selection['new_protocol_sha256']==protocol and
            selection['parent_protocol_sha256']==config['parent_protocol_sha256'] and selection['parent_owner']==parent_owner and
            selection['branch_owner']==owner and selection['method']==method and selection['mode']==mode and
            selection['root_seed']==config['root_seed'] and selection['vocabulary_sha256']==vocabulary_hash(words) and
            selection['selected_added_updates']==1536 and selection['selected_cumulative_stop']==12256,
            'Exact root-bound original parent and experimental branch selection')
        census_raw=canonical(prepared_census);need(len(census_raw)<=1048576,'Full current source census before model work')
        current_io=len(canonical(io.rows));need(current_io<=524288,'Full source/input IO roster before restore')
        entry_upper=current_io+128*2048+12288*256+65536
        need(entry_upper<=4194304,'Full normal ENTRY preflight before any model restore')
        products['census']=io.write('MODULE-CENSUS.json',census_raw,1048576);acknowledge(known,census_raw,products['census'])
        previous=json.loads(raw['metadata']);retained['previous_metadata']=previous
        if role=='before-method':
            register_ranges(known,raw['state'],inputs['state'],parent220_ranges(raw['state'],0,len(raw['state'])))
            parent_hist,parent_parts,entries,ranges=history_ranges(raw['history'],parent=True)
            register_ranges(known,raw['history'],inputs['history'],ranges)
            bundle=migrate(raw['state'],raw['metadata'],parent_hist,words,selection,retained['restoration'])
            parent_meta=previous;queries=548;fits=96;probe_count=0;probe_pin=None;archives={};prior_history=None
        else:
            expected={'method-train':'before-method','blind-post':'method-train','reopen':'blind-post'}[role]
            need(type(previous) is dict and set(previous)==META_FIELDS and previous['schema']=='newbrain.method228.metadata.v1' and
                previous['stage']==expected and previous['condition']=='QUERY-SELECTION-COMPARISON' and previous['method']==method and
                previous['mode']==mode and previous['owner']==owner and previous['parent_owner']==parent_owner and
                previous['root_seed']==config['root_seed'] and previous['protocol_sha256']==protocol and
                previous['parent_protocol_sha256']==selection['parent_protocol_sha256'] and previous['state']==inputs['state'] and
                previous['history']==inputs['history'] and previous['episodic_retrieval_used'] is False and
                previous['personal_episodes_created']==0 and previous['Maya_birth_or_age_demonstrated'] is False and
                previous['foreign_state_adopted_into_Maya'] is False and previous['future_stage_requires_new_selection'] is True and
                all(previous[k]==selection[k] for k in ('parent_state_sha256','parent_metadata_sha256','parent_history_sha256')) and
                set(previous['archives'])==set(PHASES[:PHASES.index(role)]),'Complete accepted prior branch owner/history')
            register_ranges(known,raw['state'],inputs['state'],branch_ranges(raw['state']))
            parent_hist,parent_parts,entries,ranges=history_ranges(raw['history'])
            register_ranges(known,raw['history'],inputs['history'],ranges)
            need(len(entries)==1+PHASES.index(role),'Every complete prior branch report')
            for phase,pin in previous['archives'].items():
                r=dict(entries)['228/'+phase];need(len(r)==pin['bytes'] and sha(r)==pin['sha256'],'Full prior branch archive identity')
            migration_raw=dict(entries)['228/migration'];migration_pin=previous['migration_report']
            need(len(migration_raw)==migration_pin['bytes'] and sha(migration_raw)==migration_pin['sha256'] and
                 previous['migration_auxiliary_observations']==192,'Whole96 parent plus96 branch migration observations')
            bundle=from_state_bytes(raw['state'],parent_hist,words,selection,retained['restoration'])
            parent_meta=json.loads(bundle['parent']['metadata']);queries=previous['completed_blind_queries_lifetime']
            fits=previous['completed_exposed_fit_queries_lifetime'];probe_count=previous['exposed_teacher_probes']
            probe_pin=previous['probe_ledger'];archives=dict(previous['archives']);prior_history=raw['history']
            need(queries=={'method-train':848,'blind-post':848,'reopen':1172}[role] and
                fits=={'method-train':96,'blind-post':336,'reopen':336}[role] and
                probe_count==(0 if role=='method-train' else 9216),'Full previous observation counters without relabeling probes')
            need(previous['parameter_sha256']==bundle['model'].parameter_hash() and
                previous['decoder_details']==bundle['model'].parameter_details(),'Current full model/counter parity')
        retained.update(bundle=bundle,parent_metadata=parent_meta,parent_history=parent_hist,parent_history_parts=parent_parts,
            branch_history_entries=entries,bank=list(parent_meta['episodic_bank']))
        need(sha(parent_hist)==selection['parent_history_sha256'],'Entire immutable accepted220 history')
        model=retained['model']=bundle['model'];journal=bundle['journal'];bank=retained['bank']
        need(model.training_updates==(10720 if role in ('before-method','method-train') else 12256) and
            model.root_seed==config['root_seed'] and len(bank)==(48 if mode=='ON' else 0),
            'Full restored parent arrays/counters and unchanged inherited audit bank')
        base,binary=available({'retained':retained,'io':io},known,local)
        need(len(canonical(base))<=16777216 and len(binary)<=4194304 and len(base['nodes'])<=81920 and base['visits']<=655360,
            'Complete supported parent/base graph before any probe or training')
        retained['preflight']={'parent_graph_bytes':len(canonical(base)),'parent_binary_bytes':len(binary),
            'parent_nodes':len(base['nodes']),'parent_visits':base['visits'],'entry_upper':entry_upper,
            'conditional_selected_graph_upper':38917632,'conditional_selected_binary_upper':20146110,
            'conditional_selected_nodes_upper':142792,'conditional_selected_visits_upper':1372024,
            'supported_frozen_role_domain_and_actual_parent_preflight_required':True,
            'unreturned_decoder_numpy_native_temporaries_proven':False}
        if role=='before-method':
            migration_pin=verify_migration(bundle,retained['restoration']['parent220_restored_bundle']['model'],
                raw['migration_questions'],words,io,retained,known,local)
            migration_raw=retained['migration_report_raw'];entries=[('228/migration',migration_raw)]
            products['migration_report']=migration_pin
        else:
            migration_pin=previous['migration_report']
            need(bundle['migration']['equivalence_report_pin']==migration_pin,'Stored boundary and complete migration archive agree')
        before_model=model.state_bytes(protocol);retained['before_model']=before_model
        if role=='method-train':
            check_pre_teaching_gate(raw['pre_teaching_gate'],config,protocol,method,mode,owner,
                inputs['before_report'],migration_pin,retained)
            new_packet=json.loads(raw['teacher_pool']);old_packet=json.loads(raw['old_teaching'])
            retained['teacher_pool'],retained['old_teaching']=new_packet,old_packet
            need(sha(raw['teacher_pool'])==config['teacher_pool_sha256'][method] and sha(raw['old_teaching'])==config['old_teaching_sha256'],
                'Exact same provided teacher pool in both methods')
            new_examples=pool_examples(new_packet,words,method,unit_map)
            old_examples,old_batches=teacher_examples(old_packet,words,'newbrain.foundation220.common-review-teaching.v1')
            retained['examples']={'new':new_examples,'protected_old':old_examples}
            prior=json.loads(raw['before_report']);retained['before_report']=prior
            need(entries[-1]==('228/before-method',raw['before_report']) and prior['owner']==owner and
                prior['method']==method and prior['role']=='before-method' and len(prior['generations'])==300,
                'Full accepted label-free common-union before report, including every wrong prediction')
            for index,row in enumerate(new_packet['rows']):
                pool_row=48+index
                before=prior['generations'][pool_row]
                need(before['group']=='UNION240' and before['group_row']==pool_row+1 and
                    before['context']==row['context'] and before['question']==row['question'],
                    'Only provided own teachers join the actual common blind baseline')
            for index,row in enumerate(old_packet['rows']):
                before=prior['generations'][240+index]
                need(before['group']=='OLD48' and before['context']==row['context'] and before['question']==row['question'],
                    'Every exact protected old teacher joins its actual blind baseline')
            ledger=retained['probe_ledger']=ProbeLedger(protocol,method,mode)
            for cycle in range(64):
                chosen_orders=[]
                for new_pass in range(3):
                    variant=method_order.teacher_variant(method,cycle,new_pass)
                    indices=[4*u+variant for u in range(48)]
                    selected_examples=[new_examples[i] for i in indices]
                    selected_batches=[tuple(selected_examples[u] for u in b) for b in method_order.FIXED_OFFSETS]
                    retained['selected_teacher_indices'],retained['selected_examples'],retained['selected_batches']=indices,selected_examples,selected_batches
                    need(model.training_updates==method_order.probe_update(method,cycle,new_pass),'Actual fixed-interleaving selected probe boundary')
                    probe_before=model.state_bytes(protocol);retained['probe_pass_before_model']=probe_before
                    feedback=[];packet_hash=model.parameter_hash();retained['feedback_rows_partial']=feedback
                    for row,example in enumerate(selected_examples):
                        pool_row=method_order.pool_row(method,cycle,new_pass,row)
                        io.checkpoint('method.before-teacher-probe',{'cycle':cycle,'pass':new_pass,'row':row,'variant':variant,'pool_row':pool_row,'updates':model.training_updates})
                        observed=teacher_probe(model,example,new_packet['rows'][indices[row]]['answer'],words,method,mode,cycle,new_pass,row,variant,pool_row,retained)
                        ledger.append(observed,retained)
                        feedback.append({k:observed[k] for k in ('row','variant','pool_row','receptive_wrong','target_loss')})
                    need(model.state_bytes(protocol)==probe_before,'All48 selected teacher probes preserve the entire model/counters')
                    packet={'schema':'newbrain.foundation228.exposed-feedback.v1','cycle':cycle,'new_pass':new_pass,
                        'completed_updates':model.training_updates,'parameter_sha256':packet_hash,'variant':variant,'rows':feedback}
                    retained['feedback_packet']=packet
                    decision=method_order.feedback_order(method,cycle,new_pass,packet)
                    decision_record={'decision':decision,'feedback_projection_sha256':sha(canonical(packet)),
                        'full_probe_ledger_row_start':(cycle*3+new_pass)*48,'full_probe_ledger_row_count':48}
                    need(len(canonical(decision_record))<=2048,'Full selected target-role variation and interleaving decision record')
                    retained['method_decisions'].append(decision_record)
                    order=tuple(decision['chosen_order']);chosen_orders.append(order)
                    for kind,batch_index in method_order.pass_blocks(method,new_pass,order):
                        batch=(selected_batches if kind=='new' else old_batches)[batch_index]
                        io.checkpoint('method.before-update',{'cycle':cycle,'kind':kind,'batch':batch_index,'variant':variant if kind=='new' else None,'updates':model.training_updates})
                        start=stamp();retained['current_clock']={'start':start,'end':None}
                        update=model.train_step(batch);retained['active_update']=update
                        end=stamp();retained['current_clock']['end']=end
                        need(update['new_exposures']=={'examples':8,'prefix_tokens':sum(len(r['prefix']) for r in batch),'target_tokens_including_eos':16},
                            'All actual natural-prefix and answer/EOS exposures retained')
                        journal.append(update,{'start_ns':start['ns'],'end_ns':end['ns'],'start_utc':start['utc'],'end_utc':end['utc']},retained)
                        retained['active_update']=None
                need(len(method_order.cycle_blocks(method,tuple(chosen_orders)))==24 and
                    model.training_updates==10720+(cycle+1)*24,'Matched semantic-unit and protected-old quotas')
            need(model.training_updates==12256 and model.training_examples==98048 and
                model.prefix_tokens_seen==1253376 and
                model.target_tokens_seen==196096 and len(ledger.rows)==9216,'Complete selected natural-prefix SGD/probe counters')
            fit_before=model.state_bytes(protocol)
            for group,packet in (('NEW_EXPOSED',new_packet),('OLD48',old_packet)):
                for local_index,row in enumerate(packet['rows'],1):
                    index=len(retained['training_fit'])+1
                    io.checkpoint('method.before-exposed-fit',{'row':index,'updates':12256})
                    observed=observe(model,{k:row[k] for k in ('context','question')},words,index,group,local_index,retained)
                    observed['expected_answer']=row['answer'];observed['comparison']=compare(observed,row['answer'],words)
                    if group=='NEW_EXPOSED':
                        unit=(local_index-1)//4
                        variant=(local_index-1)%4
                        observed['teaching_provenance']={'unit':unit,'variant':variant,'pool_row':48+4*unit+variant,
                            'SGD_presentations':48,'exposed_to_SGD':True}
                    else:observed['teaching_provenance']={'old_row':local_index-1,'SGD_presentations':64,'exposed_to_SGD':True}
                    need(len(canonical(observed))<=4096,'Complete own-exposed fit row with exact provenance')
                    retained['training_fit'].append(observed)
            count=240
            need(len(retained['training_fit'])==count and model.state_bytes(protocol)==fit_before,
                'Only own-exposed teachers counted in train fit; every fit generation makes zero updates')
            fits+=count;probe_count=9216
        else:
            specs=(('union_questions','UNION240',240),('old_questions','OLD48',48),('anchors','ANCHORS6',6),('oov','OOV6',6))
            if role!='before-method':specs=(('fresh_questions','FRESH24',24),)+specs
            cohort=[];retained['question_packets']={}
            for name,group,count in specs:
                packet=json.loads(raw[name]);retained['question_packets'][name]=packet
                expected_schema='newbrain.foundation217.blind-questions.v1' if name=='anchors' else ('newbrain.foundation221.blind-questions.v1' if name=='old_questions' else ('newbrain.foundation225.questions.v1' if name=='union_questions' else 'newbrain.routing228.questions.v1'))
                need(type(packet) is dict and set(packet)=={'schema','rows'} and packet['schema']==expected_schema and len(packet['rows'])==count,
                    'Whole blind question cohort without any answer/label input')
                cohort.extend((group,i,row) for i,row in enumerate(packet['rows'],1))
            prior=None
            if role=='reopen':
                prior=json.loads(raw['previous_report']);retained['previous_report']=prior
                need(entries[-1]==('228/blind-post',raw['previous_report']) and prior['owner']==owner and
                    prior['method']==method and prior['role']=='blind-post' and len(prior['generations'])==324,
                    'Full accepted post report, preserving every wrong output')
            for index,(group,group_row,row) in enumerate(cohort,1):
                io.checkpoint('method.before-blind-query',{'row':index,'updates':model.training_updates})
                observed=observe(model,row,words,index,group,group_row,retained,allow_oov=group=='OOV6');retained['generations'].append(observed)
                if prior is not None:
                    earlier=prior['generations'][index-1]
                    need(all(earlier[k]==observed[k] for k in ('row','group','group_row','context','question','prefix','first_distribution','receptive_decision')) and
                        canonical(earlier['generation'])==canonical(observed['generation']),'All324 exact cold decisions/distributions/generations, including failures')
            need(model.state_bytes(protocol)==before_model,'Every blind observation preserves entire model/counters');queries+=len(cohort)
        summary=journal.summary(model.parameter_hash())
        need(summary['updates']==model.training_updates and summary['exposures']=={'examples':model.training_examples,
            'prefix_tokens':model.prefix_tokens_seen,'target_tokens_including_eos':model.target_tokens_seen},'Full parent plus branch journal/counter parity')
        current_state=state_bytes(bundle,retained);retained['final_state_raw']=current_state
        ranges=branch_ranges(current_state);own_buffer(local,current_state,ranges)
        products['state']=io.write('CONTINUATION-STATE.bin',current_state,4194304);register_ranges(known,current_state,products['state'],ranges)
        if role=='method-train':
            ledger_raw=retained['probe_ledger_raw']=retained['probe_ledger'].state_bytes()
            probe_ranges=[(0,len(ledger_raw))]+[(PROBE_HEADER.size+i*PROBE_ROW.size,PROBE_ROW.size) for i in range(9216)]
            own_buffer(local,ledger_raw,probe_ranges)
            products['probe_ledger']=io.write('EXPOSED-PROBE-LEDGER.bin',ledger_raw,PROBE_CAP)
            register_ranges(known,ledger_raw,products['probe_ledger'],probe_ranges);probe_pin=products['probe_ledger']
        report={'schema':'newbrain.method228.report.v1','role':role,'condition':'QUERY-SELECTION-COMPARISON','method':method,'mode':mode,
            'owner':owner,'parent_owner':parent_owner,'protocol_sha256':protocol,'parent_protocol_sha256':selection['parent_protocol_sha256'],
            'parent_parameter_sha256':parent_meta['parameter_sha256'],'parameter_sha256':model.parameter_hash(),
            'decoder_details':model.parameter_details(),'update_summary':summary,'generations':retained['generations'],
            'training_fit':retained['training_fit'],'method_decisions':retained['method_decisions'],'probe_ledger':probe_pin,
            'exposed_teacher_probes':probe_count,'probe_generation_calls':0,'migration_report':migration_pin,'migration_auxiliary_observations':192,'episodic_bank':bank,'episodic_retrieval_used':False,
            'state':products['state'],'previous_archives':archives,'parent_state_sha256':selection['parent_state_sha256'],
            'parent_metadata_sha256':selection['parent_metadata_sha256'],'parent_history_sha256':selection['parent_history_sha256'],
            'completed_blind_queries_lifetime':queries,'completed_exposed_fit_queries_lifetime':fits,
            'full_parent_history_preserved':True,'root_original_wrapper_process_IO_observers_required':True,
            'sealed_gold_opened':False,'training_opened_fresh_questions':False,'personal_episodes_created':0,
            'Maya_birth_age_or_conversation_demonstrated':False,'foreign_state_adopted_into_Maya':False,
            'method_comparison_requires_separate_labels_and_actual_costs':True,'future_stage_requires_new_selection':True}
        base_report={k:v for k,v in report.items() if k not in ('generations','training_fit','method_decisions')}
        need(len(canonical(base_report))<=229376,'Full fixed owner/bank/pins/summary report domain')
        report_bound={'before-method':1459200,'method-train':1606656,'blind-post':1557504,'reopen':1557504}[role]
        report_raw=retained['report_raw']=canonical(report);need(len(report_raw)<=report_bound,'Whole selected report, never clipped')
        own_buffer(local,report_raw,[])
        products['report']=io.write('METHOD-REPORT.json',report_raw,2097152);acknowledge(known,report_raw,products['report'])
        current_history=retained['history_raw']=branch_history.append(parent_hist,entries,role,report_raw,prior_history)
        _,_,_,ranges=history_ranges(current_history);own_buffer(local,current_history,ranges)
        products['history']=io.write('COMPLETE-HISTORY.bin',current_history,12582912);register_ranges(known,current_history,products['history'],ranges)
        archives[role]=products['report']
        meta={'schema':'newbrain.method228.metadata.v1','stage':role,'condition':'QUERY-SELECTION-COMPARISON','method':method,'mode':mode,
            'owner':owner,'parent_owner':parent_owner,'root_seed':config['root_seed'],'protocol_sha256':protocol,
            'parent_protocol_sha256':selection['parent_protocol_sha256'],'parameter_sha256':model.parameter_hash(),
            'decoder_details':model.parameter_details(),'state':products['state'],'history':products['history'],'archives':archives,
            'episodic_bank':bank,'completed_blind_queries_lifetime':queries,'completed_exposed_fit_queries_lifetime':fits,
            'exposed_teacher_probes':probe_count,'migration_report':migration_pin,'migration_auxiliary_observations':192,'parent_state_sha256':selection['parent_state_sha256'],
            'parent_metadata_sha256':selection['parent_metadata_sha256'],'parent_history_sha256':selection['parent_history_sha256'],
            'episodic_retrieval_used':False,'personal_episodes_created':0,'Maya_birth_or_age_demonstrated':False,
            'foreign_state_adopted_into_Maya':False,'future_stage_requires_new_selection':True,'probe_ledger':probe_pin}
        meta_raw=retained['metadata_raw']=canonical(meta);need(len(meta_raw)<=131072,'Complete branch lineage/owner/history metadata')
        own_buffer(local,meta_raw,[])
        products['metadata']=io.write('CONTINUATION-METADATA.json',meta_raw,131072);acknowledge(known,meta_raw,products['metadata'])
        return io.finish({'role':role,'condition':'QUERY-SELECTION-COMPARISON','method':method,'mode':mode,'products':products,
            'scientific_success_requires_separate_label_scoring':True})
    except BaseException as primary:failure(io,primary,retained,products,known,local)
