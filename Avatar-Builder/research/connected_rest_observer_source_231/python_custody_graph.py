"""Source-only rooted normal/error projection; corrected artifact_name receipt. Native internals remain opaque and incomplete."""
import array,pathlib,struct,sys,types
MAGIC=b'AV224PG3\x00';NODE_CAP=6000000;REF_CAP=32000000;DEPTH_CAP=512
BINARY_CAP=128*1048576;STRING_CAP=32*1048576;INTEGER_BITS=128
TAGS={'none':0,'bool':1,'int':2,'str':3,'float64':4,'bytes':5,'external_bytes':6,'list':7,'tuple':8,'dict':9,'set':10,'frozenset':11,'selected_instance':12,'exception':13,'traceback':14,'path':15,'opaque':16,'type':17}
class CaptureLimit(RuntimeError):pass
def capture_to(io,root,external=(),known_instances=(),*,artifact_name="PYTHON-REACHABLE-DATA.bin"):
 ext={id(b):(b,p) for b,p in external};known={id(v):(v,f) for v,f in known_instances};keep=[];types_by_name={};external_pins=[];refs=0;count=0;emitted=0;unsupported=0;hist={};wire_bytes=0
 # Fixed12bytes/slot, <0.75 load maximum:96MiB, avoiding millions of Python
 # dict key/value/int allocations. Every referenced original remains in keep.
 SLOTS=8388608;keys=array.array('Q',[0])*SLOTS;values=array.array('I',[0xffffffff])*SLOTS
 def slot(v):
  identity=id(v);s=((identity>>4)*11400714819323198485)&(SLOTS-1);probes=0
  while keys[s] and keys[s]!=identity:
   s=(s+1)&(SLOTS-1);probes+=1
   if probes%4096==0:io.check()
  return s,identity
 def produce(write):
  nonlocal refs,count,emitted,unsupported,wire_bytes
  write(MAGIC);wire_bytes=len(MAGIC)
  def output(i,tag,payload):
   nonlocal emitted,wire_bytes
   h=struct.pack('<IBI',i,tag,len(payload));wire_bytes+=len(h)+len(payload)
   if wire_bytes>BINARY_CAP:raise CaptureLimit('complete_binary_graph_extent')
   write(h);write(payload);emitted+=1;hist[str(tag)]=hist.get(str(tag),0)+1
   if emitted%1024==0:io.check()
  def ids(values,depth):
   a=array.array('I',(visit(v,depth+1) for v in values))
   if sys.byteorder!='little':a.byteswap()
   return a.tobytes()
  def type_id(t,depth):
   key=(t.__module__,t.__qualname__)
   if key not in types_by_name:
    if any(type(x) is not str or len(x.encode())>512 for x in key):raise CaptureLimit('exact_type_name_width')
    # This tuple is kept strongly before recursion like every other temporary.
    keep.append(key);types_by_name[key]=visit(key,depth+1)
   return types_by_name[key]
  def visit(v,depth):
   nonlocal refs,count,unsupported
   refs+=1
   if refs>REF_CAP or depth>DEPTH_CAP:raise CaptureLimit('complete_reference_or_depth_domain')
   s,identity=slot(v)
   if keys[s]:return values[s]
   if count>=NODE_CAP:raise CaptureLimit('complete_node_domain')
   i=count;count+=1;keys[s]=identity;values[s]=i;keep.append(v);t=type(v)
   if v is None:tag=0;payload=b''
   elif t is bool:tag=1;payload=bytes((int(v),))
   elif t is int:
    if v.bit_length()>INTEGER_BITS:raise CaptureLimit('complete_integer_width')
    tag=2;payload=str(v).encode('ascii')
   elif t is str:
    if len(v)>STRING_CAP:raise CaptureLimit('complete_string_character_extent')
    tag=3;payload=v.encode('utf-8','surrogatepass')
    if len(payload)>STRING_CAP:raise CaptureLimit('complete_string_byte_extent')
   elif t is float:tag=4;payload=struct.pack('<d',v) # exact sign and NaN payload bits
   elif t is bytes:
    e=ext.get(id(v))
    if e is not None and e[0] is v:
     index=len(external_pins);external_pins.append(e[1]);tag=6;payload=struct.pack('<IQ',index,len(v))
    else:tag=5;payload=v
   elif t in (list,tuple,set,frozenset):
    if refs+len(v)>REF_CAP:raise CaptureLimit('complete_container_references')
    tag={list:7,tuple:8,set:10,frozenset:11}[t];payload=ids(v,depth)
   elif t is dict:
    if refs+2*len(v)>REF_CAP:raise CaptureLimit('complete_mapping_references')
    tag=9;payload=ids((x for pair in v.items() for x in pair),depth)
   elif isinstance(v,BaseException):
    fields={'args':BaseException.args.__get__(v,t),'cause':BaseException.__cause__.__get__(v,t),'context':BaseException.__context__.__get__(v,t),'traceback':BaseException.__traceback__.__get__(v,t),'suppress_context':BaseException.__suppress_context__.__get__(v,t)}
    try:fields['attributes']=object.__getattribute__(v,'__dict__')
    except AttributeError:fields['attributes']=None
    keep.append(fields);tag=13;payload=struct.pack('<II',type_id(t,depth),visit(fields,depth+1))
   elif t is types.TracebackType:
    f=v.tb_frame;fields={'filename':f.f_code.co_filename,'function':f.f_code.co_name,'line':v.tb_lineno,'locals':f.f_locals,'next':v.tb_next};keep.append(fields);tag=14;payload=struct.pack('<I',visit(fields,depth+1))
   elif t in (pathlib.WindowsPath,pathlib.PosixPath,pathlib.PureWindowsPath,pathlib.PurePosixPath):tag=15;payload=pathlib.PurePath.__str__(v).encode('utf-8','surrogatepass')
   elif id(v) in known and known[id(v)][0] is v:
    fields=known[id(v)][1];keep.append(fields);tag=12;payload=struct.pack('<II',type_id(t,depth),visit(fields,depth+1))
   else:unsupported+=1;tag=16;payload=struct.pack('<IQ',type_id(t,depth),id(v))
   output(i,tag,payload);return i
  root_id=visit(root,0)
  if emitted!=count:raise CaptureLimit('all_complete_nodes_emitted')
  return {'schema':'avatar224.supported-python-error-graph.v3','magic_hex':MAGIC.hex(),'record_header':'<IBI node_id/tag/payload_bytes','tags':TAGS,'root':root_id,'nodes':count,'references':refs,'tag_counts':hist,'wire_bytes':wire_bytes,'external_pins':external_pins,'opaque_nodes':unsupported,'binary_file':artifact_name,'ordering':'postorder records with explicit unique IDs; forward alias/cycle references allowed','scalar_encoding':'float exact little-endian binary64 including sign/NaN payload; decimal signed integer; UTF8 surrogatepass strings; literal raw bytes','supported_builtin_and_selected_instance_projection_complete':True,'all_Python_or_native_state_complete':False,'native_payload_complete':False,'scope':'exact rooted builtin values, selected source fields, original causes/contexts/traceback locals; unsupported/native objects typed identity tokens only'}
 physical,info=io.stream_product(artifact_name,produce);info['binary_pin']=physical;return info

