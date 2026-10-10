"""UNRUN connected disposable synthetic routing engineering, no private input.
All words, targets and counter values are mechanical fixtures, not lessons,
learning history, an owner identity, or a migration of an actual main model.
"""
import hashlib,json,struct,traceback
import numpy as np
from dialogue_decoder import DialogueDecoder as ParentDecoder,SPECIALS
from routed_decoder import RoutingDecoder,PARAMETER_NAMES,ROUTING_NAMES
from routing_engineering import evaluate
from available_state import capture,acknowledge,own_buffer,GRAPH_CAP,DATA_CAP
from run_io import RunIO,canonical

ROLE='routing-engineering'
CONDITION='SYNTHETIC-ROUTING-CALIBRATION-8'
SPEC_CAP=32768
ARRAY_BYTES=95312
MODEL_CAP=131072
REPORT_CAP=3145728
NORMAL_GRAPH_CAP=16777216
NORMAL_DATA_CAP=8388608
BASE_COUNTERS={'training_updates':10720,'training_examples':85760,'prefix_tokens_seen':1037312,'target_tokens_seen':171520}

def need(ok,why):
    if not ok:raise RuntimeError(why)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def fullpin(q):
    return type(q)is dict and set(q)=={'path','bytes','sha256'} and type(q['path'])is str and len(canonical(q['path']))<=700 and type(q['bytes'])is int and 0<q['bytes']<=SPEC_CAP and type(q['sha256'])is str and len(q['sha256'])==64 and all(c in '0123456789abcdef' for c in q['sha256'])

def arrays(raw):
    return b''.join(raw[n].astype('<f8',copy=False).tobytes(order='C') for n in PARAMETER_NAMES)

def available(roots,known,local):
    return capture(roots,(ParentDecoder,RoutingDecoder,RunIO),canonical,array_type=np.ndarray,known=known,local=local)

def save(io,products,known,local,key,name,raw,cap):
    own_buffer(local,raw,[])
    q=io.write(name,raw,cap);products[key]=q;acknowledge(known,raw,q)
    return q

def fail(io,primary,retained,products,known,local):
    later=[]
    try:
        graph,binary=available({'primary':primary,'retained':retained,'products':products,'io':io},known,local)
        io.write('FAILED-AVAILABLE-DATA.bin',binary,DATA_CAP,emergency=True)
        io.write('FAILED-AVAILABLE-STATE.json',canonical(graph),GRAPH_CAP,emergency=True)
    except BaseException as secondary:later.append(secondary)
    try:
        io.write('ERROR.json',canonical({'schema':'newbrain.routing230.synthetic-calibration-error.v1',
            'original_traceback':''.join(traceback.format_exception(primary)),
            'later_tracebacks':[''.join(traceback.format_exception(e)) for e in later],
            'complete_supported_logical_graph':not later,
            'unreturned_native_python_frame_locals_complete':False,
            'scientific_parent_or_training_state_read':False}),262144,emergency=True)
    except BaseException as secondary:later.append(secondary)
    if later:raise BaseExceptionGroup('Original synthetic engineering and capture failures',[primary]+later)
    raise primary

def check_spec(raw):
    x=json.loads(raw)
    need(type(x)is dict and set(x)=={'schema','purpose','seed','synthetic_counter_sentinels','words','prefixes','batch_prefix_rows','batch_answers','scientific_inputs','real_learning_history_claimed'},'Closed synthetic spec only')
    need(x['schema']=='newbrain.routing228.synthetic-engineering-spec.v1' and x['purpose']=='disposable_numerical_engineering_only' and
         x['seed']==2281729 and type(x['seed'])is int and x['synthetic_counter_sentinels']==BASE_COUNTERS and
         all(type(v)is int for v in x['synthetic_counter_sentinels'].values()) and x['scientific_inputs']==[] and x['real_learning_history_claimed']is False,
         'Fixed synthetic seed and explicitly artificial API counter sentinels')
    words=tuple(SPECIALS)+('stated',)+tuple('fixture'+str(i).zfill(2) for i in range(34))
    need(x['words']==list(words),'Exact synthetic42 inventory; no scientific vocabulary file')
    expected=[]
    for i in range(96):
        n=1+i%28;m=1+(i//28)%min(4,29-n)
        context=tuple(words[8+(i+3*j)%34] for j in range(n))
        question=tuple(words[8+(5*i+7*j+1)%34] for j in range(m))
        expected.append(('<MEMORY>','stated')+context+('<QUERY>',)+question)
    need(x['prefixes']==[list(p) for p in expected] and
         x['batch_prefix_rows']==[13,27,41,55,69,83,95,7] and
         x['batch_answers']==['fixture00','fixture01','fixture02','fixture03']*2,
         'Entire deterministic mechanical tensor exercise; no semantic targets or confirmation examples')
    batch=tuple({'prefix':expected[i],'answer':(a,)} for i,a in zip(x['batch_prefix_rows'],x['batch_answers']))
    return x,words,tuple(expected),batch

def check_inference(model,prefix,retained):
    active={};retained['same_path_active']=active
    before=model.state_bytes(retained['protocol'])
    hidden=model.encode_prefix(prefix,active)
    hidden,_=model._step(1,hidden);p,logits,_=model._distribution(hidden)
    generated=model.generate(prefix);chosen=int(np.argmax(p))
    need((chosen==2 and generated['tokens']==() and generated['terminated_with_eos']) or
         (chosen!=2 and len(generated['tokens'])>0 and generated['tokens'][0]==model.vocabulary[chosen]),
         'Inference and generation use exactly the same routed full42 first-token path')
    need(model.state_bytes(retained['protocol'])==before,'Whole10-array state and counters unchanged by observation')
    out={'parameter_sha256':model.parameter_hash(),'full42_probability_hex':p.astype('<f8').tobytes().hex(),
         'full42_logits_hex':logits.astype('<f8').tobytes().hex(),'generation':generated,'first_argmax_index':chosen}
    retained['same_path_active']=None;return out

def expected_refusal(call,label,retained):
    try:call()
    except (ValueError,RuntimeError) as e:
        retained['refusal_errors'].append(e)
        retained['refusals'].append({'case':label,'type':type(e).__name__,'message':str(e)})
    else:raise RuntimeError('Expected fixed structural refusal was absent: '+label)

def execute(experiment,*,io,prepared_census):
    need(type(io)is RunIO,'Exact source-owned bootstrap IO instance')
    retained={'prepared_census':prepared_census,'synthetic_parent':None,'kernel':{},'products':{},
              'refusal_errors':[],'refusals':[],'same_path':[],'codec_checks':[],'bad_frames':[],'bad_arrays':[]}
    known={};local={};products=retained['products']
    try:
        need(type(experiment)is dict and set(experiment)=={'role','condition','inputs'} and
             experiment['role']==ROLE and experiment['condition']==CONDITION and
             type(experiment['inputs'])is dict and set(experiment['inputs'])=={'synthetic_spec'} and
             fullpin(experiment['inputs']['synthetic_spec']),'Exactly one closed synthetic input, no model/data/owner/teacher path')
        q=experiment['inputs']['synthetic_spec'];raw=io.read(q['path'],q['bytes'])
        need(len(raw)==q['bytes'] and sha(raw)==q['sha256'],'Complete exact synthetic spec')
        acknowledge(known,raw,q);retained['spec_raw']=raw
        spec,words,prefixes,batch=check_spec(raw);retained.update(spec=spec,words=words,prefixes=prefixes,batch=batch)
        protocol=sha(raw);retained['protocol']=protocol
        census=canonical(prepared_census);need(len(census)<=1048576,'Complete observed source census')
        save(io,products,known,local,'census','MODULE-CENSUS.json',census,1048576)
        io.checkpoint('synthetic-engineering.before-constructor',{'seed':spec['seed']})
        parent=ParentDecoder(words,spec['seed']);retained['synthetic_parent']=parent
        retained['constructor_counters']={k:getattr(parent,k) for k in BASE_COUNTERS}
        need(all(v==0 for v in retained['constructor_counters'].values()),'Fresh from-scratch mechanical fixture')
        for k,v in BASE_COUNTERS.items():setattr(parent,k,v)
        parent.validate_parameters()
        retained['counter_attribution']='Artificial API compatibility sentinels, NOT10720 actual updates, lessons or inherited journal'
        initial_parent=parent.state_bytes(protocol);retained['synthetic_parent_initial_raw']=initial_parent
        save(io,products,known,local,'parent','SYNTHETIC-PARENT-STATE.bin',initial_parent,MODEL_CAP)
        result=evaluate(parent,batch,prefixes,protocol,io.checkpoint,retained['kernel'])
        retained['kernel_result']=result;eng=retained['kernel']['engineering']
        need(result['migration_pairs']==192 and result['disposable_updates']==16 and result['scientific_updates']==0 and
             1<=result['finite_coordinate_checks']<=128,'Whole synthetic kernel result, no scientific acceptance')
        need(len(eng['models'])==2 and len(eng['gradients'])==18 and len(eng['pairs'])==192 and len(eng['states'])==18 and len(eng['updates'])==16,'Exact full engineering outputs')
        for arm in ('FUNCTIONAL_POOL','QUERY_SELECTION'):
            need(any(r['arm']==arm and r['phase']=='after_eight_disposable_updates' and
                     r['matrix']=='E' and abs(r['analytic'])>1e-12 for r in eng['finite_differences']),
                 'At least one checked old-embedding coordinate must be active after R becomes nonzero')
        for state in eng['states']:
            restored_state=RoutingDecoder.from_state_bytes(state['raw'],words,protocol)
            need(all(not np.shares_memory(restored_state.p[n],m['model'].p[k])
                     for m in eng['models'] for n in PARAMETER_NAMES for k in PARAMETER_NAMES) and
                 all(not np.shares_memory(restored_state.p[n],earlier['restored'].p[k])
                     for earlier in eng['states'] if 'restored' in earlier
                     for n in PARAMETER_NAMES for k in PARAMETER_NAMES),
                 'Every decoded state owns independent all-ten arrays')
            state['restored']=restored_state
            need(restored_state.state_bytes(protocol)==state['raw'] and
                 restored_state.training_updates==10720+state['step'],
                 'All eighteen full frames and synthetic counters roundtrip')
            save(io,products,known,local,state['arm']+'_STEP_'+str(state['step']).zfill(2),
                 state['arm']+'-STEP-'+str(state['step']).zfill(2)+'.bin',state['raw'],MODEL_CAP)
        for entry in eng['models']:
            model=entry['model'];arm=entry['arm'];initial=entry['initial'];final=model.state_bytes(protocol)
            retained['active_final_frame']=final
            need(tuple(model.p)==PARAMETER_NAMES and model.training_updates==10728 and
                 all(r['update']['parameter_bytes_changed']is True for r in eng['updates'] if r['arm']==arm) and
                 np.linalg.norm(model.p['R'])>0.0,'Exactly eight actual disposable updates per arm, no real ancestry claim')
            initial_model=next(s['restored'] for s in eng['states'] if s['arm']==arm and s['step']==0)
            entry['initial_check_model']=initial_model
            first_model=next(s['restored'] for s in eng['states'] if s['arm']==arm and s['step']==1)
            need(all(np.array_equal(initial_model.p[n],first_model.p[n]) for n in ('Q','K','V')),
                 'First-step QKV unchanged; later activity is measured separately')
            restored=next(s['restored'] for s in eng['states'] if s['arm']==arm and s['step']==8)
            entry['final_restored_model']=restored
            need(restored.state_bytes(protocol)==final and all(restored.p[n].tobytes()==model.p[n].tobytes() and
                 not np.shares_memory(restored.p[n],model.p[n]) for n in PARAMETER_NAMES),'All ten final arrays and counters roundtrip independently')
            retained['codec_checks'].append({'arm':arm,'all_ten_initial_and_final_roundtrip':True,
                                             'initial_bytes':len(initial),'final_bytes':len(final)})
            for i in (0,27,55,95):
                io.checkpoint('synthetic-engineering.same-path',{'arm':arm,'row':i})
                retained['same_path'].append({'arm':arm,'row':i,'observation':check_inference(model,prefixes[i],retained)})
            before_refusals=model.state_bytes(protocol)
            for name in PARAMETER_NAMES:
                original=restored.p[name];bad=original.reshape(-1)[:-1].copy()
                retained['bad_arrays'].append({'arm':arm,'matrix':name,'original':original,'bad':bad})
                try:
                    restored.p[name]=bad
                    expected_refusal(restored.validate_parameters,arm+'.wrong-shape.'+name,retained)
                finally:restored.p[name]=original
            n=struct.unpack('<I',final[8:12])[0];header=json.loads(final[12:12+n]);tail=final[12+n:]
            bad_header=dict(header);bad_header['training_updates']=True
            bh=canonical(bad_header)
            frames=[('truncated',final[:-1]),('trailing',final+b'x'),('magic',b'INVALID!'+final[8:]),
                    ('bool-counter',final[:8]+struct.pack('<I',len(bh))+bh+tail)]
            for label,b in frames:
                retained['bad_frames'].append({'arm':arm,'case':label,'raw':b})
                expected_refusal(lambda b=b:RoutingDecoder.from_state_bytes(b,words,protocol),arm+'.codec.'+label,retained)
            wrong_words=words[:-2]+(words[-1],words[-2])
            expected_refusal(lambda:RoutingDecoder.from_state_bytes(final,wrong_words,protocol),arm+'.vocabulary-order',retained)
            wrong_protocol=('0' if protocol[0]!='0' else '1')+protocol[1:]
            expected_refusal(lambda:RoutingDecoder.from_state_bytes(final,words,wrong_protocol),arm+'.protocol',retained)
            need(model.state_bytes(protocol)==before_refusals and restored.state_bytes(protocol)==final,'Refusals preserve valid reference models')
        for g in eng['gradients']:
            b=arrays(g['gradient']);need(len(b)==ARRAY_BYTES,'Full all-ten gradient arrays in fixed order')
            save(io,products,known,local,g['arm']+'_'+g['phase']+'_gradient',g['arm']+'-'+g['phase']+'-GRADIENT.bin',b,MODEL_CAP)
        need(parent.state_bytes(protocol)==initial_parent and len(retained['refusals'])==32,
             'All disposable checks leave synthetic parent exact; no real parent was opened')
        report={'schema':'newbrain.routing230.synthetic-calibration-result.v1','status':'PASS_SYNTHETIC_COMPONENT_ENGINEERING_ONLY',
            'synthetic_seed':spec['seed'],'synthetic_counter_sentinels':BASE_COUNTERS,'real_learning_history_claimed':False,
            'scientific_inputs':[],'scientific_models_read':0,'scientific_updates':0,'fixture_state_adopted':False,
            'kernel_result':result,'parity_pairs':eng['pairs'],'finite_differences':eng['finite_differences'],
            'calibration_updates':eng['updates'],
            'state_snapshots':[{'arm':s['arm'],'step':s['step'],'sha256':sha(s['raw']),
                                'bytes':len(s['raw']),'training_updates':s['restored'].training_updates}
                               for s in eng['states']],
            'matrix_gradient_norms':[{'arm':g['arm'],'phase':g['phase'],'step':g['step'],'loss':g['loss'],'counts':g['counts'],
                'norms':{n:float(np.linalg.norm(g['gradient'][n])) for n in PARAMETER_NAMES}} for g in eng['gradients']],
            'codec_checks':retained['codec_checks'],'same_path':retained['same_path'],'refusals':retained['refusals'],
            'kernel_segmentation_refusals':eng['refusals'],'products':dict(products),
            'all_original_parameters_preserved_before_disposable_updates':True,
            'scientific_ancestry_confirmation_transfer_and_retention_not_tested':True,
            'native_or_unreturned_frame_completeness':False,'runtime_authority':False}
        report_raw=canonical(report);retained['report_raw']=report_raw
        need(len(report_raw)<=3145728,'Full192 raw parity/128 loss operands/18 states+gradients/16 updates/8 same-path/38 refusals')
        save(io,products,known,local,'report','SYNTHETIC-ENGINEERING-REPORT.json',report_raw,REPORT_CAP)
        graph,binary=available({'retained':retained,'io':io},known,local)
        graph['binary_file']='ENGINEERING-DATA.bin'
        retained['normal_binary']=binary
        graph_raw=canonical(graph);retained['normal_graph_raw']=graph_raw
        retained['normal_snapshot_custody']={
            'complete_graph_bytes':True,'complete_binary_bytes':True,
            'all_original_candidate_and_IO_roots_retained':True,
            'generated_graph_container_identity_retained':False}
        # Full graph bytes already encode every original logical identity/alias.
        # The redundant generated dictionary stays an unreturned serializer local.
        need(len(graph_raw)<=16777216 and len(binary)<=8388608 and len(graph['nodes'])<=81920 and graph['visits']<=655360,
             'Full bounded synthetic normal capture before any graph publication')
        save(io,products,known,local,'data','ENGINEERING-DATA.bin',binary,NORMAL_DATA_CAP)
        save(io,products,known,local,'graph','ENGINEERING-GRAPH.json',graph_raw,NORMAL_GRAPH_CAP)
        return io.finish({'role':ROLE,'condition':CONDITION,'products':products,
            'synthetic_component_engineering_only':True,'independent_actual_review_required':True,
            'scientific_or_runtime_admission':False})
    except BaseException as primary:fail(io,primary,retained,products,known,local)
