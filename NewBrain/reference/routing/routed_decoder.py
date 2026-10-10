"""UNRUN D16 context routing above an independently restored main10720 H64 decoder.
No file IO, model construction, RNG, or candidate calls at import.
Both arms own every Q/K/V/R parameter. Only token mixing weights differ.
"""
import hashlib
import json
import struct
import numpy as np
from dialogue_decoder import DialogueDecoder as ParentDecoder
from dialogue_decoder import vocabulary, vocabulary_hash, hash_string

EMBEDDING,HIDDEN,ROUTING,VOCABULARY=16,64,16,42
MAX_PREFIX,MAX_RESPONSE,MAX_BATCH,MAX_UPDATES=32,16,8,16384
LEARNING_RATE,CLIP_NORM,PARAMETER_LIMIT=0.01,5.0,1000.0
BASE_NAMES=('E','Wxh','Whh','bh','Wy','by')
ROUTING_NAMES=('Q','K','V','R')
PARAMETER_NAMES=BASE_NAMES+ROUTING_NAMES
ARMS=('QUERY_SELECTION','FUNCTIONAL_POOL')
MAGIC=b'NBRQ228\0'
MAX_META_BYTES=8192
PARAMETER_SCALARS=11914
EXACT_ARRAY_BYTES=95312
MAX_STATE_BYTES=103516

def need(ok,why):
    if not ok:raise ValueError(why)

class RoutingError(RuntimeError):
    def __init__(self,primary,state):
        self.primary,self.state=primary,state
        super().__init__('Routing operation incomplete; returned partial state retained without retry')

class RoutingDecoder:
    def __init__(self,*args,**kwargs):
        raise RuntimeError('Restore exact inherited main10720 or complete routing state; no reset constructor')

    _step=ParentDecoder._step
    _distribution=ParentDecoder._distribution

    def _set_vocabulary(self,words):
        ParentDecoder._set_vocabulary(self,words)
        need(len(self.vocabulary)==VOCABULARY,'Unchanged exact42 inventory')

    def _ids(self,words,reply=False):
        result=ParentDecoder._ids(self,words,reply)
        need(reply or len(result)<=MAX_PREFIX,'Complete selected prefix ceiling32')
        return result

    def _shapes(self):
        return {'E':(42,16),'Wxh':(16,64),'Whh':(64,64),'bh':(64,),
                'Wy':(64,42),'by':(42,),'Q':(16,16),'K':(64,16),
                'V':(64,16),'R':(16,64)}

    def validate_parameters(self):
        need(self.arm in ARMS and type(self.p)is dict and tuple(self.p)==PARAMETER_NAMES,
             'Closed ordered base plus all four functional routing matrices')
        for name,shape in self._shapes().items():
            value=self.p[name]
            need(type(value)is np.ndarray and value.dtype==np.dtype('float64') and
                 value.shape==shape and value.flags.c_contiguous and np.isfinite(value).all() and
                 np.max(np.abs(value),initial=0)<=PARAMETER_LIMIT,'Finite exact routing parameter shape')
        need(sum(v.size for v in self.p.values())==PARAMETER_SCALARS and
             sum(v.nbytes for v in self.p.values())==EXACT_ARRAY_BYTES,'Exact matched parameter extent')
        need(type(self.root_seed)is int and 0<=self.root_seed<2**32 and
             type(self.training_updates)is int and 10720<=self.training_updates<=MAX_UPDATES and
             all(type(x)is int and 0<=x<2**32 for x in
                 (self.training_examples,self.prefix_tokens_seen,self.target_tokens_seen)),
             'Full inherited global counters, never zeroed')

    @classmethod
    def from_parent(cls,parent,arm,retained):
        need(type(retained)is dict,'Caller owns complete returned partial roots')
        state={'parent':parent,'model':None,'phase':'validate','parent_hash':None}
        retained['routing_migration_partial']=state
        try:
            need(type(parent)is ParentDecoder and arm in ARMS,'Exact main decoder and declared comparison arm')
            parent.validate_parameters()
            need(len(parent.vocabulary)==42 and parent.training_updates==10720 and
                 parent.training_examples==85760 and parent.prefix_tokens_seen==1037312 and
                 parent.target_tokens_seen==171520,'Exact inherited main10720 exposure tuple')
            state['parent_hash']=parent.parameter_hash()
            result=cls.__new__(cls);state['model']=result
            result._set_vocabulary(parent.vocabulary);result.arm=arm
            for name in ('root_seed','training_updates','training_examples','prefix_tokens_seen','target_tokens_seen'):
                setattr(result,name,getattr(parent,name))
            result.p={name:parent.p[name].copy() for name in BASE_NAMES}
            result.p['Q']=np.eye(16,dtype=np.float64)*0.25
            result.p['K']=np.zeros((64,16),dtype=np.float64)
            result.p['V']=np.zeros((64,16),dtype=np.float64)
            for row in range(64):
                result.p['K'][row,row%16]=0.125
                result.p['V'][row,(row+5)%16]=0.125 if row//16%2==0 else -0.125
            result.p['R']=np.zeros((16,64),dtype=np.float64)
            result.active_call=None
            result.validate_parameters()
            need(all(not np.shares_memory(parent.p[k],result.p[k]) and
                     parent.p[k].tobytes()==result.p[k].tobytes() for k in BASE_NAMES),
                 'Independent exact base arrays with no parent mutation')
            need(parent.parameter_hash()==state['parent_hash'],'Parent hash unchanged after zero-SGD migration')
            state['phase']='complete';return result
        except BaseException as primary:
            if not isinstance(primary,Exception):raise
            raise RoutingError(primary,state) from primary

    def _segment(self,prefix):
        ids=self._ids(prefix)
        need(len(ids)>=5 and prefix[:2]==('<MEMORY>','stated') and
             prefix.count('<QUERY>')==1 and prefix.count('<MEMORY>')==1,
             'Exact existing MEMORY stated/context/QUERY question segmentation')
        split=prefix.index('<QUERY>')
        need(2<split<len(prefix)-1 and all(t not in
             ('<UNK>','<BOS>','<EOS>','<USER>','<ASSISTANT>','<MEMORY>','<QUERY>')
             for t in prefix[2:split]+prefix[split+1:]),
             'Nonempty lexical context and question; OOV spelling maps to UNK normally')
        return ids,tuple(range(2,split)),tuple(range(split+1,len(prefix)))

    def encode_prefix(self,prefix,retained):
        """Shared route for receptive decisions, teacher probes and generation."""
        need(type(retained)is dict,'Caller retained forward cache')
        self.validate_parameters()
        ids,context_positions,question_positions=self._segment(prefix)
        state={'prefix_ids':ids,'context_positions':context_positions,
               'question_positions':question_positions,'cache':[],'hidden':None}
        retained['routing_forward']=state
        hidden=np.zeros(HIDDEN,dtype=np.float64)
        for identity in ids:
            hidden,item=self._step(identity,hidden)
            state['cache'].append(item);state['hidden']=hidden
        contexts=np.stack([state['cache'][i][2] for i in context_positions])
        qemb=np.mean(self.p['E'][list(ids[i] for i in question_positions)],axis=0)
        keys=np.tanh(contexts@self.p['K'])
        values=np.tanh(contexts@self.p['V'])
        query=np.tanh(qemb@self.p['Q'])
        features=keys*values
        if self.arm=='QUERY_SELECTION':
            scores=keys@query/4.0
            exponent=np.exp(scores-float(np.max(scores)))
            weights=exponent/float(np.sum(exponent))
        else:
            scores=None
            weights=np.full(len(context_positions),1.0/len(context_positions),dtype=np.float64)
        pooled=weights@features
        routed=query*pooled
        zero_projection=bool(np.all(self.p['R']==0.0))
        # Mathematical residual is zero here; bypass add/matmul to retain exact legacy forward bits.
        result=hidden if zero_projection else hidden+routed@self.p['R']
        state.update(contexts=contexts,question_embedding=qemb,keys=keys,values=values,
                     query=query,features=features,scores=scores,weights=weights,
                     pooled=pooled,routed=routed,projection_zero=zero_projection,result=result)
        need(np.isfinite(result).all() and np.isfinite(weights).all() and
             abs(float(np.sum(weights))-1.0)<=1e-12,'Finite full routing forward result')
        return result

    def _routing_backward(self,dh,state,gradients):
        gradients['R']+=np.outer(state['routed'],dh)
        dr=dh@self.p['R'].T
        dq=dr*state['pooled']
        dpool=dr*state['query']
        dfeatures=np.outer(state['weights'],dpool)
        dk=dfeatures*state['values']
        dv=dfeatures*state['keys']
        if self.arm=='QUERY_SELECTION':
            dw=state['features']@dpool
            ds=state['weights']*(dw-float(state['weights']@dw))
            dk+=np.outer(ds,state['query'])/4.0
            dq+=state['keys'].T@ds/4.0
        dak=dk*(1.0-state['keys']*state['keys'])
        dav=dv*(1.0-state['values']*state['values'])
        daq=dq*(1.0-state['query']*state['query'])
        gradients['K']+=state['contexts'].T@dak
        gradients['V']+=state['contexts'].T@dav
        gradients['Q']+=np.outer(state['question_embedding'],daq)
        hidden_extra=dak@self.p['K'].T+dav@self.p['V'].T
        query_embedding_gradient=daq@self.p['Q'].T/len(state['question_positions'])
        for position in state['question_positions']:
            gradients['E'][state['prefix_ids'][position]]+=query_embedding_gradient
        return hidden_extra

    def loss_and_gradients(self,batch):
        self.validate_parameters()
        need(type(batch)is tuple and 0<len(batch)<=MAX_BATCH,'Finite complete training batch')
        rows=[]
        for example in batch:
            need(type(example)is dict and set(example)=={'prefix','answer'},'Training-only closed row')
            self._segment(example['prefix'])
            answer=self._ids(example['answer'],reply=True)+(2,)
            rows.append((example['prefix'],answer))
        total_targets=sum(len(a) for _,a in rows)
        gradients={n:np.zeros_like(self.p[n]) for n in PARAMETER_NAMES}
        loss=0.0;active={'phase':'loss','batch':batch,'rows':rows,'gradients':gradients,'forward':None,'reply_cache':None}
        self.active_call=active
        for prefix,answer in rows:
            forward={};active['forward']=forward
            hidden=self.encode_prefix(prefix,forward);route=forward['routing_forward']
            cache=[];active['reply_cache']=cache;previous_token=1
            for target in answer:
                hidden,item=self._step(previous_token,hidden)
                probability,logits,log_normalizer=self._distribution(hidden)
                loss+=(log_normalizer-float(logits[target]))/total_targets
                dz=probability.copy();dz[target]-=1.0;dz/=total_targets
                cache.append((item,dz));previous_token=target
            dh=np.zeros(HIDDEN,dtype=np.float64)
            for (previous,embedding,current,identity),dz in reversed(cache):
                gradients['Wy']+=np.outer(current,dz);gradients['by']+=dz
                dh=dh+dz@self.p['Wy'].T
                da=dh*(1.0-current*current)
                gradients['Wxh']+=np.outer(embedding,da);gradients['Whh']+=np.outer(previous,da)
                gradients['bh']+=da;gradients['E'][identity]+=da@self.p['Wxh'].T
                dh=da@self.p['Whh'].T
            hidden_extra=self._routing_backward(dh,route,gradients)
            by_position={position:hidden_extra[i] for i,position in enumerate(route['context_positions'])}
            for position in range(len(route['cache'])-1,-1,-1):
                previous,embedding,current,identity=route['cache'][position]
                if position in by_position:dh=dh+by_position[position]
                da=dh*(1.0-current*current)
                gradients['Wxh']+=np.outer(embedding,da);gradients['Whh']+=np.outer(previous,da)
                gradients['bh']+=da;gradients['E'][identity]+=da@self.p['Wxh'].T
                dh=da@self.p['Whh'].T
        need(np.isfinite(loss) and loss>=0 and all(np.isfinite(v).all() for v in gradients.values()),
             'Complete finite routed CE/BPTT')
        counts=dict(examples=len(rows),prefix_tokens=sum(len(p) for p,_ in rows),
                    target_tokens_including_eos=total_targets)
        self.active_call=None
        return float(loss),gradients,counts

    def train_step(self,batch):
        state={'model':self,'phase':'validate','gradients':None,'proposal':None,'parameters_committed':False}
        try:
            self.validate_parameters();need(self.training_updates<MAX_UPDATES,'Global update ceiling')
            before=self.parameter_hash();state['phase']='gradient'
            loss,gradients,counts=self.loss_and_gradients(batch);state['gradients']=gradients;state['loss']=loss
            need(tuple(gradients)==PARAMETER_NAMES and all(v.dtype==np.dtype('float64') and
                 v.shape==self.p[n].shape and np.isfinite(v).all() and np.max(np.abs(v),initial=0)<=1e6
                 for n,v in gradients.items()),'Exact complete bounded gradients')
            norm=float(np.sqrt(sum(float(np.sum(v*v)) for v in gradients.values())))
            multiplier=min(1.0,CLIP_NORM/norm) if norm>0 else 1.0
            proposal={n:self.p[n]-LEARNING_RATE*multiplier*gradients[n] for n in PARAMETER_NAMES}
            state['proposal']=proposal
            need(all(np.isfinite(v).all() and np.max(np.abs(v),initial=0)<=PARAMETER_LIMIT
                     for v in proposal.values()),'Finite complete proposal')
            nxt=(self.training_updates+1,self.training_examples+counts['examples'],
                 self.prefix_tokens_seen+counts['prefix_tokens'],self.target_tokens_seen+counts['target_tokens_including_eos'])
            need(all(type(x)is int and 0<=x<2**32 for x in nxt),'Finite cumulative exposures')
            state['phase']='commit';self.p=proposal;state['parameters_committed']=True
            self.training_updates,self.training_examples,self.prefix_tokens_seen,self.target_tokens_seen=nxt
            after=self.parameter_hash()
            return dict(schema='newbrain.trained-dialogue.update.v1',loss=loss,
                parameter_sha256_before=before,parameter_sha256_after=after,parameter_bytes_changed=before!=after,
                gradient_norm=norm,clip_multiplier=multiplier,new_exposures=counts,
                updates_completed=self.training_updates,runtime_qualified=False)
        except BaseException as primary:
            state['forward_partial']=self.active_call;self.active_call=state
            if not isinstance(primary,Exception):raise
            raise RoutingError(primary,state) from primary

    def generate(self,prefix):
        before=self.parameter_hash();state={};self.active_call=state
        hidden=self.encode_prefix(prefix,state);previous=1;emitted=[];terminated=False
        for _ in range(MAX_RESPONSE):
            hidden,_=self._step(previous,hidden);probability,_,_=self._distribution(hidden)
            selected=int(np.argmax(probability))
            if selected==2:terminated=True;break
            emitted.append(self.vocabulary[selected]);previous=selected
        need(self.parameter_hash()==before,'No generation updates')
        self.active_call=None
        return dict(schema='newbrain.trained-dialogue.generation.v1',backend='newbrain.query-routing228.'+self.arm,
            tokens=tuple(emitted),answer_text=' '.join(emitted),terminated_with_eos=terminated,
            length_limit_reached=not terminated,unknown_prefix_tokens=sum(w not in self.index for w in prefix),
            parameter_sha256=before,qwen_calls_in_this_module=0,full_conversation_demonstrated=False,runtime_qualified=False)

    def parameter_hash(self):
        self.validate_parameters();digest=hashlib.sha256(self.arm.encode('ascii'))
        for n in PARAMETER_NAMES:
            v=self.p[n];digest.update(n.encode());digest.update(str(v.shape).encode())
            digest.update(v.astype('<f8',copy=False).tobytes(order='C'))
        return digest.hexdigest()

    def parameter_details(self):
        self.validate_parameters()
        return dict(parameter_scalars=PARAMETER_SCALARS,array_bytes=EXACT_ARRAY_BYTES,
            vocabulary_size=42,embedding=16,hidden=64,routing=16,arm=self.arm,
            training_updates=self.training_updates,training_examples=self.training_examples,
            prefix_tokens_seen=self.prefix_tokens_seen,target_tokens_seen=self.target_tokens_seen,
            scope='Complete private parameter arrays and global exposures; not process RAM or learning evidence')

    def state_bytes(self,protocol_sha256):
        self.validate_parameters();need(hash_string(protocol_sha256),'Exact protocol SHA')
        meta=dict(schema='newbrain.routing228.decoder-state.v1',arm=self.arm,
            vocabulary=list(self.vocabulary),vocabulary_sha256=vocabulary_hash(self.vocabulary),
            protocol_sha256=protocol_sha256,parameter_sha256=self.parameter_hash(),
            embedding=16,hidden=64,routing=16,root_seed=self.root_seed,
            training_updates=self.training_updates,training_examples=self.training_examples,
            prefix_tokens_seen=self.prefix_tokens_seen,target_tokens_seen=self.target_tokens_seen,
            pretrained=False,glif_integrated=False)
        header=json.dumps(meta,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')
        need(len(header)<=MAX_META_BYTES,'Complete bounded canonical metadata')
        raw=MAGIC+struct.pack('<I',len(header))+header+b''.join(
            self.p[n].astype('<f8',copy=False).tobytes(order='C') for n in PARAMETER_NAMES)
        need(len(raw)<=MAX_STATE_BYTES,'Derived complete11914-scalar codec bound')
        return raw

    @classmethod
    def from_state_bytes(cls,raw,words,protocol_sha256):
        need(type(raw)is bytes and 12<len(raw)<=MAX_STATE_BYTES and raw[:8]==MAGIC,'Whole routed state frame')
        n=struct.unpack('<I',raw[8:12])[0]
        need(0<n<=MAX_META_BYTES and len(raw)==12+n+EXACT_ARRAY_BYTES,'Exact full frame before array allocation')
        header=raw[12:12+n];meta=json.loads(header.decode('ascii'))
        fields={'schema','arm','vocabulary','vocabulary_sha256','protocol_sha256','parameter_sha256',
                'embedding','hidden','routing','root_seed','training_updates','training_examples',
                'prefix_tokens_seen','target_tokens_seen','pretrained','glif_integrated'}
        need(type(meta)is dict and set(meta)==fields and
             json.dumps(meta,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')==header,
             'Closed canonical routed metadata')
        words=vocabulary(words)
        need(meta['schema']=='newbrain.routing228.decoder-state.v1' and meta['arm']in ARMS and
             meta['vocabulary']==list(words) and meta['vocabulary_sha256']==vocabulary_hash(words) and
             hash_string(protocol_sha256) and meta['protocol_sha256']==protocol_sha256 and
             type(meta['embedding'])is int and meta['embedding']==16 and
             type(meta['hidden'])is int and meta['hidden']==64 and
             type(meta['routing'])is int and meta['routing']==16 and
             meta['pretrained']is False and meta['glif_integrated']is False,'Exact restored architecture')
        result=cls.__new__(cls);result._set_vocabulary(words);result.arm=meta['arm']
        for name in ('root_seed','training_updates','training_examples','prefix_tokens_seen','target_tokens_seen'):
            setattr(result,name,meta[name])
        flat=np.frombuffer(raw[12+n:],dtype='<f8');result.p={};at=0
        for name,shape in result._shapes().items():
            count=1
            for dimension in shape:count*=dimension
            result.p[name]=flat[at:at+count].reshape(shape).copy();at+=count
        result.active_call=None;result.validate_parameters()
        need(at==PARAMETER_SCALARS and result.parameter_hash()==meta['parameter_sha256'] and
             result.state_bytes(protocol_sha256)==raw,'Complete state and counter roundtrip')
        return result
