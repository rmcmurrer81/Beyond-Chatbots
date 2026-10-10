"""UNRUN disposable SYNTHETIC engineering kernel; no IO or candidate calls at import.

A separately reviewed root caller must construct a disposable synthetic H64 with explicit counter sentinels,
authenticate the closed artificial batch and 96 synthetic prefixes,
capture all retained roots on normal/error, and apply process/IO/STOP limits.
This kernel is not a connected runtime admission or scientific training job.
"""
import hashlib,time
import numpy as np
from dialogue_decoder import DialogueDecoder as ParentDecoder
from routed_decoder import RoutingDecoder,PARAMETER_NAMES,ROUTING_NAMES

ARMS=('FUNCTIONAL_POOL','QUERY_SELECTION')
EPSILON=1e-6
ABS_TOL,REL_TOL=2e-7,2e-4
ACTIVITY_FLOOR=1e-12
CALIBRATION_UPDATES=8

def need(ok,why):
    if not ok:raise RuntimeError(why)

def arrays_sha(arrays):
    h=hashlib.sha256()
    for name in PARAMETER_NAMES:
        h.update(name.encode('ascii'));h.update(arrays[name].astype('<f8',copy=False).tobytes())
    return h.hexdigest()

def evaluate(parent,batch,prefixes,protocol,checkpoint,retained):
    """One disposable nomination: no real parent/branch is read or updated."""
    need(type(retained)is dict and callable(checkpoint),'Root retained state and cooperative checkpoint required')
    retained['engineering']={'parent':parent,'batch':batch,'prefixes':prefixes,'models':[],
                             'pairs':[],'gradients':[],'finite_differences':[],'refusals':[],
                             'states':[],'updates':[]}
    s=retained['engineering']
    need(type(parent)is ParentDecoder and type(batch)is tuple and len(batch)==8 and
         type(prefixes)is tuple and len(prefixes)==96,'Exact root-bound synthetic8 and synthetic96; no scientific data')
    need(all(type(r)is dict and set(r)=={'prefix','answer'} and type(r['prefix'])is tuple and
             5<=len(r['prefix'])<=32 and type(r['answer'])is tuple and len(r['answer'])==1 for r in batch) and
         all(type(p)is tuple and 5<=len(p)<=32 for p in prefixes),'Finite artificial one-label tensor targets and full synthetic prefixes')
    before=parent.state_bytes(protocol);s['parent_before']=before
    for arm in ARMS:
        checkpoint('routing.engineering.before-arm',{'arm':arm})
        owned={};model=RoutingDecoder.from_parent(parent,arm,owned)
        s['models'].append({'arm':arm,'migration':owned,'model':model})
        initial=model.state_bytes(protocol);s['models'][-1]['initial']=initial
        s['states'].append({'arm':arm,'step':0,'raw':initial})
        need(sum(x.size for x in model.p.values())==11914 and
             all(model.p[n].tobytes()==parent.p[n].tobytes() for n in ('E','Wxh','Whh','bh','Wy','by')) and
             not any(np.shares_memory(a,b) for a in parent.p.values() for b in model.p.values()),
             'Matched complete11914 parameters, exact independent old arrays')
        for i,prefix in enumerate(prefixes):
            checkpoint('routing.engineering.parity',{'arm':arm,'row':i})
            old=np.zeros(64,dtype=np.float64)
            for identity in parent._ids(prefix):old,_=parent._step(identity,old)
            forward={};new=model.encode_prefix(prefix,forward)
            s['active_forward']=forward
            pair={'arm':arm,'row':i,
                  'parent_hidden_hex':old.astype('<f8',copy=False).tobytes().hex(),
                  'branch_hidden_hex':new.astype('<f8',copy=False).tobytes().hex()}
            s['pairs'].append(pair)
            need(old.tobytes()==new.tobytes(),'Zero-R exact inherited full-prefix hidden bits')
            old,_=parent._step(1,old);new,_=model._step(1,new)
            op,ol,_=parent._distribution(old);npv,nl,_=model._distribution(new)
            og,ng=parent.generate(prefix),model.generate(prefix)
            pair.update({'parent_BOS_hidden_hex':old.astype('<f8',copy=False).tobytes().hex(),
                               'branch_BOS_hidden_hex':new.astype('<f8',copy=False).tobytes().hex(),
                               'parent_logits_hex':ol.astype('<f8',copy=False).tobytes().hex(),
                               'branch_logits_hex':nl.astype('<f8',copy=False).tobytes().hex(),
                               'parent_BOS_hex':op.tobytes().hex(),'branch_BOS_hex':npv.tobytes().hex(),
                               'parent_generation':og,'branch_generation':ng})
            need(op.tobytes()==npv.tobytes() and ol.tobytes()==nl.tobytes() and
                 all(og[k]==ng[k] for k in ('tokens','answer_text','terminated_with_eos','length_limit_reached','unknown_prefix_tokens')),
                 'Exact full distribution/logits/free generation, including wrong outputs')
        restored=RoutingDecoder.from_state_bytes(initial,parent.vocabulary,protocol)
        s['models'][-1]['restored']=restored
        need(restored.state_bytes(protocol)==initial and all(not np.shares_memory(model.p[n],restored.p[n]) for n in PARAMETER_NAMES),
             'Complete independent codec/counter restoration')
        loss,gradient,counts=model.loss_and_gradients(batch)
        s['gradients'].append({'arm':arm,'phase':'zero_R','step':0,'loss':loss,'gradient':gradient,'counts':counts})
        need(float(np.linalg.norm(gradient['R']))>ACTIVITY_FLOOR and
             all(np.all(gradient[n]==0.0) for n in ('Q','K','V')),
             'Non-inert first projection derivative, with legitimately zero first-step Q/K/V derivatives')
        for phase in ('zero_R','after_eight_disposable_updates'):
            if phase!='zero_R':
                for step in range(1,CALIBRATION_UPDATES+1):
                    checkpoint('routing.calibration.before-update',{'arm':arm,'step':step})
                    record={'arm':arm,'step':step,'before_state_sha256':hashlib.sha256(s['states'][-1]['raw']).hexdigest(),
                            'clock_start_ns':time.perf_counter_ns(),'clock_end_ns':None,'update':None,
                            'after_state_sha256':None}
                    s['updates'].append(record)
                    try:record['update']=model.train_step(batch)
                    finally:record['clock_end_ns']=time.perf_counter_ns()
                    raw=model.state_bytes(protocol);s['states'].append({'arm':arm,'step':step,'raw':raw})
                    record['after_state_sha256']=hashlib.sha256(raw).hexdigest()
                    need(record['clock_end_ns']>=record['clock_start_ns'] and
                         record['update']['parameter_bytes_changed']is True and
                         model.training_updates==10720+step,'Exact fixed disposable update and original clocks')
                    if step==1:
                        need(all(model.p[n].tobytes()==restored.p[n].tobytes() for n in ('Q','K','V')),
                             'First-step zero upstream derivatives do not imply first-step QKV learning')
                    loss,gradient,counts=model.loss_and_gradients(batch)
                    observed_phase=phase if step==CALIBRATION_UPDATES else 'after_disposable_update_'+str(step).zfill(2)
                    s['gradients'].append({'arm':arm,'phase':observed_phase,'step':step,
                                          'loss':loss,'gradient':gradient,'counts':counts})
                    checkpoint('routing.calibration.after-update',{'arm':arm,'step':step})
                need(all(float(np.linalg.norm(gradient[n]))>ACTIVITY_FLOOR for n in ROUTING_NAMES),
                     'Every routing matrix group exceeds unchanged activity floor after exactly eight disposable updates')
            base=model.state_bytes(protocol);s['models'][-1]['difference_base']=base
            for name in PARAMETER_NAMES:
                size=model.p[name].size
                # Fixed coordinates plus one logged maximum-gradient coordinate.
                indices=sorted(set((0,size//3,2*size//3,size-1,int(np.argmax(np.abs(gradient[name])))))) if name in ROUTING_NAMES else [0,size-1]
                for index in indices:
                    checkpoint('routing.engineering.finite-difference',{'arm':arm,'phase':phase,'matrix':name,'index':index})
                    flat=model.p[name].reshape(-1);value=float(flat[index])
                    row={'arm':arm,'phase':phase,'step':0 if phase=='zero_R' else CALIBRATION_UPDATES,
                         'matrix':name,'index':index,'base_value':value,'epsilon':EPSILON,
                         'base_frame_sha256':hashlib.sha256(base).hexdigest(),
                         'plus_value':value+EPSILON,'minus_value':value-EPSILON,
                         'plus_loss':None,'minus_loss':None,'analytic':float(gradient[name].reshape(-1)[index]),
                         'numerical':None,'absolute_error':None,'bound':None,'coordinate_restored':False}
                    s['finite_differences'].append(row)
                    try:
                        flat[index]=row['plus_value'];row['plus_loss']=model.loss_and_gradients(batch)[0]
                        flat[index]=row['minus_value'];row['minus_loss']=model.loss_and_gradients(batch)[0]
                    finally:
                        flat[index]=value;row['coordinate_restored']=float(flat[index])==value
                    numerical=(row['plus_loss']-row['minus_loss'])/(2*EPSILON);analytic=row['analytic']
                    error=abs(numerical-analytic);bound=ABS_TOL+REL_TOL*max(abs(numerical),abs(analytic))
                    row.update(numerical=numerical,absolute_error=error,bound=bound)
                    need(error<=bound,'Predeclared finite coordinate check; failure cannot tune tolerance or parameters')
            need(model.state_bytes(protocol)==base,'All numerical perturbations undone with complete codec equality')
        for bad in ((),('<QUERY>',),('<MEMORY>','stated','<QUERY>')):
            before_bad=model.state_bytes(protocol)
            try:model.encode_prefix(bad,{})
            except (ValueError,RuntimeError) as error:s['refusals'].append({'arm':arm,'kind':type(error).__name__,'message':str(error)})
            else:raise RuntimeError('Malformed segmentation unexpectedly accepted')
            need(model.state_bytes(protocol)==before_bad,'Refusal does not mutate model or counters')
    need(parent.state_bytes(protocol)==before,'Disposable engineering leaves the full synthetic parent unchanged')
    return {'schema':'newbrain.routing230.calibration-engineering-kernel-result.v1','status':'complete',
            'migration_pairs':192,'finite_coordinate_checks':len(s['finite_differences']),
            'disposable_updates':16,'calibration_updates_per_arm':8,'activity_floor':ACTIVITY_FLOOR,'scientific_updates':0,'runtime_authority':False,
            'scope':'Finite synthetic engineering only; no real main migration, acquisition, transfer, native completeness or adoption'}
