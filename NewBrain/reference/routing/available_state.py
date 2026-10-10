"""Lossless supported error graph with complete acknowledged reconstruction.

Every external extent names a FULL input already read/verified in this job, or
a FULL output whose write/readback returned. Root must acquire/verify those
complete original files before reconstructing any slice. Partial/unacknowledged
bytes stay in the sidecar. Native views, live frames and unreturned locals are
explicitly outside this logical application graph.
"""
import hashlib
import json
import math
import struct
import traceback

GRAPH_CAP, DATA_CAP = 41943040, 35651584
NODE_CAP, VISIT_CAP = 196608, 2097152


def need(ok, why):
    if not ok: raise RuntimeError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def acknowledge(known, raw, pin):
    need(type(known) is dict and type(raw) is bytes and type(pin) is dict and
         set(pin)=={'path','bytes','sha256'} and type(pin['path']) is str and
         pin['bytes']==len(raw) and pin['sha256']==sha(raw), 'Full verified original reconstruction source')
    ack=(raw,dict(pin)); extent(known,ack,0,len(raw)); return ack


def extent(known, ack, offset, length):
    raw,pin=ack
    need(type(offset) is int and type(length) is int and 0<=offset<=len(raw) and
         0<=length<=len(raw)-offset,'Exact full acknowledged subextent')
    part=raw[offset:offset+length]; digest=sha(part)
    descriptor={'source':dict(pin),'offset':offset,'bytes':length,'sha256':digest}
    bucket=known.setdefault((length,digest),[])
    if not any(existing==part and row==descriptor for existing,row in bucket):
        bucket.append((part,descriptor))


def own_buffer(local, raw, extents):
    """Complete caller-owned bytes, never an acknowledged physical file.

    Partial writes can still own complete encoded application bytes. Each
    internal slice is reconstructable from the full binary sidecar buffer.
    No native-storage/live-view identity is inferred from this logical record.
    """
    need(type(local) is dict and type(raw) is bytes and type(extents) in (tuple,list),
         'Complete owned buffer and exact finite extents')
    digest=sha(raw); buffer_key=(len(raw),digest)
    entry=local.setdefault(buffer_key,[])
    if not any(existing==raw for existing in entry):entry.append(raw)
    for offset,length in [(0,len(raw))]+list(extents):
        need(type(offset) is int and type(length) is int and 0<=offset<=len(raw) and
             0<=length<=len(raw)-offset,'Exact owned full-buffer slice')
        part=raw[offset:offset+length]; key=(len(part),sha(part))
        rows=local.setdefault(('slice',)+key,[])
        if not any(existing==part and owner==raw and at==offset for existing,owner,at in rows):
            rows.append((part,raw,offset))


def capture(roots, supported, canonical, *, array_type=None, known=None, local=None):
    known={} if known is None else known
    local={} if local is None else local
    local_buffers={}
    nodes,memo,extents,chunks,buckets,reconstruction=[],{},[],[],{},[]
    # Keep every memoized identity alive through the complete traversal.
    identity_owners=[]
    visits,data_size=0,0
    def blob(raw):
        nonlocal data_size
        digest=sha(raw); key=(len(raw),digest)
        for existing,row in known.get(key,()):
            if existing==raw:
                if row['source'] not in reconstruction: reconstruction.append(dict(row['source']))
                return {'external_extent':{'source':reconstruction.index(row['source']),
                    'offset':row['offset'],'bytes':row['bytes'],'sha256':row['sha256']}}
        for existing,owned,offset in local.get(('slice',)+key,()):
            if existing==raw:
                owner_key=(len(owned),sha(owned)); candidates=local_buffers.setdefault(owner_key,[])
                for previous,index in candidates:
                    if previous==owned:break
                else:
                    need(data_size+len(owned)<=DATA_CAP,'Complete local buffer custody; never clip')
                    index=len(extents);extents.append({'offset':data_size,'bytes':len(owned),'sha256':sha(owned)})
                    chunks.append(owned);buckets.setdefault(owner_key,[]).append(index)
                    candidates.append((owned,index));data_size+=len(owned)
                return {'local_slice':{'extent':index,'offset':offset,'bytes':len(raw),'sha256':digest}}
        for index in buckets.get(key,()):
            if chunks[index]==raw: return {'extent':index}
        need(data_size+len(raw)<=DATA_CAP,'Complete unacknowledged binary custody; never clip')
        index=len(extents); extents.append({'offset':data_size,'bytes':len(raw),'sha256':digest})
        chunks.append(raw); buckets.setdefault(key,[]).append(index); data_size+=len(raw)
        return {'extent':index}
    def visit(value):
        nonlocal visits
        visits+=1; need(visits<=VISIT_CAP,'Complete finite available graph visits')
        if value is None or type(value) in (bool,int,str) or (type(value) is float and math.isfinite(value)): return value
        identity=id(value)
        if identity in memo: return {'ref':memo[identity]}
        need(len(nodes)<NODE_CAP,'Complete finite available graph nodes')
        identity_owners.append(value)
        index=len(nodes);memo[identity]=index;row={'type':type(value).__name__};nodes.append(row)
        need(len(identity_owners)==len(nodes),'One strong owner for every memoized identity')
        if type(value) is float:
            row.update(type='float64',raw_hex=struct.pack('<d',value).hex())
        elif type(value) is bytes: row.update(blob(value))
        elif array_type is not None and type(value) is array_type:
            need(not value.dtype.hasobject and value.size<=16384,'Full selected logical numerical array')
            row.update(dtype=value.dtype.str,shape=list(value.shape),order='C',**blob(value.tobytes(order='C')))
        elif type(value) in (list,tuple):
            need(len(value)<=NODE_CAP,'Complete finite sequence');row['items']=[visit(x) for x in value]
        elif type(value) is dict:
            need(len(value)<=NODE_CAP,'Complete finite mapping');row['items']=[[visit(k),visit(v)] for k,v in value.items()]
        elif isinstance(value,BaseException):
            row.update(args=visit(value.args),attributes=visit(vars(value)),cause=visit(value.__cause__),
                context=visit(value.__context__),suppress_context=value.__suppress_context__,
                traceback=''.join(traceback.format_exception(value)))
            if isinstance(value,BaseExceptionGroup):row['exceptions']=visit(value.exceptions)
        elif type(value) in supported:
            fields=dict(vars(value))
            for key in ('output','stop','source_root','bootstrap_root'):
                if key in fields:fields[key]=str(fields[key])
            row['attributes']=visit(fields)
        else:raise RuntimeError('Unsupported retained application type: '+type(value).__name__)
        return {'ref':index}
    root=visit(roots);binary=b''.join(chunks)
    graph={'schema':'newbrain.method226.available-state.v1','roots':root,'nodes':nodes,'visits':visits,
        'extents':extents,'binary_file':'FAILED-AVAILABLE-DATA.bin','binary_bytes':len(binary),'binary_sha256':sha(binary),
        'full_external_reconstruction_roster':reconstruction,'full_binary_reconstruction_required':True,
        'native_storage_views_live_frames_unreturned_temporaries_retained':False}
    need(len(canonical(graph))<=GRAPH_CAP,'Complete logical graph, never clip')
    return graph,binary


def reconstruct(graph_raw,binary,acquire_original):
    """Metadata reader: all original byte acquisition costs belong to its caller."""
    need(type(graph_raw) is bytes and len(graph_raw)<=GRAPH_CAP and type(binary) is bytes and len(binary)<=DATA_CAP,
         'Complete graph plus full binary sidecar')
    graph=json.loads(graph_raw)
    need(graph['schema']=='newbrain.method226.available-state.v1' and graph['binary_bytes']==len(binary) and
         graph['binary_sha256']==sha(binary) and len(graph['nodes'])<=NODE_CAP,'Full exact error reconstruction')
    sources={};resolved={};cursor=0
    for pin in graph['full_external_reconstruction_roster']:
        raw=acquire_original(dict(pin)); key=(pin['path'],pin['bytes'],pin['sha256'])
        need(key not in sources and type(raw) is bytes and len(raw)==pin['bytes'] and sha(raw)==pin['sha256'],
             'Full exact acknowledged original source BEFORE slicing');sources[key]=raw
    payloads=[]
    for row in graph['extents']:
        need(row['offset']==cursor and type(row['bytes']) is int and row['bytes']>=0,'Contiguous complete binary extents')
        part=binary[cursor:cursor+row['bytes']]
        need(len(part)==row['bytes'] and sha(part)==row['sha256'],'Full exact binary extent')
        payloads.append(part);cursor+=row['bytes']
    need(cursor==len(binary),'No trailing or missing sidecar byte')
    visits=0
    def reference(value):
        nonlocal visits
        visits+=1;need(visits<=VISIT_CAP,'Full reference validation bound')
        if type(value) is dict:need(set(value)=={'ref'} and type(value['ref']) is int and 0<=value['ref']<len(graph['nodes']),
                                  'Closed in-range logical alias')
        else:need(value is None or type(value) in (bool,int,float,str),'Original scalar or logical alias')
    reference(graph['roots'])
    for index,node in enumerate(graph['nodes']):
        if node['type']=='float64':
            need(set(node)=={'type','raw_hex'} and type(node['raw_hex']) is str and len(node['raw_hex'])==16 and
                 all(c in '0123456789abcdef' for c in node['raw_hex']), 'Exact full nonfinite binary64 scalar bits')
            raw=bytes.fromhex(node['raw_hex']);need(not math.isfinite(struct.unpack('<d',raw)[0]),'Selected nonfinite scalar node')
            resolved[index]=raw
        elif 'external_extent' in node:
            row=node['external_extent']; source_index=row['source']
            need(type(source_index) is int and 0<=source_index<len(graph['full_external_reconstruction_roster']),
                 'Exact original reconstruction source index')
            pin=graph['full_external_reconstruction_roster'][source_index];raw=sources[(pin['path'],pin['bytes'],pin['sha256'])]
            at,size=row['offset'],row['bytes']
            need(type(at) is int and type(size) is int and 0<=at<=len(raw) and 0<=size<=len(raw)-at,'Full external boundary')
            part=raw[at:at+size];need(sha(part)==row['sha256'],'Full external byte equality');resolved[index]=part
        elif 'local_slice' in node:
            row=node['local_slice']
            need(type(row) is dict and set(row)=={'extent','offset','bytes','sha256'} and
                 type(row['extent']) is int and 0<=row['extent']<len(payloads),
                 'Existing complete caller-owned sidecar buffer')
            owned=payloads[row['extent']];at,size=row['offset'],row['bytes']
            need(type(at) is int and type(size) is int and 0<=at<=len(owned) and
                 0<=size<=len(owned)-at,'Exact internal logical byte extent')
            part=owned[at:at+size];need(sha(part)==row['sha256'],'Full owned slice bytes verified')
            resolved[index]=part
        elif 'extent' in node:
            need(type(node['extent']) is int and 0<=node['extent']<len(payloads),'Existing complete extent')
            resolved[index]=payloads[node['extent']]
        elif 'items' in node:
            for item in node['items']:
                if node['type']=='dict':need(type(item) is list and len(item)==2,'Full mapping pair');reference(item[0]);reference(item[1])
                else:reference(item)
        elif 'args' in node:
            for key in ('args','attributes','cause','context'):reference(node[key])
            if 'exceptions' in node:reference(node['exceptions'])
        elif 'attributes' in node:reference(node['attributes'])
        else:raise RuntimeError('Unknown original logical node')
        if node['type']=='ndarray':
            need(node['dtype'] in ('<f8','<i8') and node['order']=='C' and type(node['shape']) is list,
                 'Selected exact logical array representation')
            count=1
            for size in node['shape']:need(type(size) is int and size>=0,'Exact dimension');count*=size
            need(count<=16384 and len(resolved[index])==count*8,'Full logical array byte extent')
    return graph,resolved
