"""Real Python-owned file IO for a scoped observational Blender test. Native operator IO is unknown."""
from pathlib import Path
import hashlib,io,json,os,stat,time
MiB=1048576
CAPS={'CHILD-CLAIM.json':4096,'OBSERVATIONS.json':32*MiB,'PYTHON-REACHABLE-ERROR.json':8*MiB,'PYTHON-REACHABLE-DATA.bin':128*MiB,'PYTHON-REACHABLE-NORMAL.bin':128*MiB,'PYTHON-REACHABLE-NORMAL.json':8*MiB,'REST-COMPACT.json':8192,'REST-MANIFEST.json':4*MiB,'REST-PROJECTION.json':MiB,'BOOTSTRAP-FAILURE.json':4*MiB,'MODULE-CENSUS.json':8*MiB,'PYTHON-IO.json':8*MiB,'PHASES.json':MiB,'RESULT.json':65536}
def sha(b):return hashlib.sha256(b).hexdigest()
def raw(v,cap=32*MiB):
 # Bounded returned encoding, with no truncation. A single encoder chunk/allocation
 # and native/interpreter internals are not claimed to be independently observed.
 out=bytearray()
 for chunk in json.JSONEncoder(sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=True).iterencode(v):
  part=chunk.encode();need(len(out)+len(part)<=cap,'complete_JSON_encoded_cap');out.extend(part)
 return bytes(out)
def need(v,m):
 if not v:raise ValueError(m)
def pathkey(p):
 # Classify the supplied namespace before resolve can erase a device alias.
 original=Path(p).as_posix()
 if os.name=='nt':
  if original.startswith('//?/'):
   tail=original[4:]
   need(len(tail)>=3 and tail[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and tail[1:3]==':/','closed_local_extended_DOS_path_only')
  else:need(not original.startswith('//') and not original.startswith('/??/'),'UNC_device_and_NT_namespace_refused')
 value=Path(p).resolve().as_posix()
 if os.name=='nt' and value.startswith('//?/'):
  tail=value[4:]
  need(len(tail)>=3 and tail[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and tail[1:3]==':/','resolved_local_extended_DOS_path_only')
  value=tail
 return value.casefold()
def ident(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink
def bridge(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink
def bootstrap_read(path,cap,keeper):
 p=Path(path);row={'path':str(p),'request':cap+1,'bootstrap_reader':True,'opened':False,'close_entered':False,'close_ack':False,'primary':None,'close_error':None,'raw':None};keeper.append(row)
 fd=None;primary=None
 try:
  a=p.lstat();row['pre_path']=ident(a);need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and not getattr(a,'st_file_attributes',0)&1024 and a.st_size<=cap,'bootstrap_regular_extent')
  fd=os.open(p,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT);row['opened']=True;q=os.fstat(fd);row['pre_fd']=ident(q);need(bridge(a)==bridge(q),'bootstrap_path_bridge')
  b=os.read(fd,cap+1);row['raw']=b;z=os.fstat(fd);row['post_fd']=ident(z);need(ident(q)==ident(z) and len(b)==a.st_size,'bootstrap_complete_stable_read')
 except BaseException as e:row['primary']=primary=e;raise
 finally:
  if fd is not None:
   row['close_entered']=True
   try:os.close(fd);row['close_ack']=True
   except BaseException as e:
    row['close_error']=e
    if primary is None:raise
 c=p.lstat();row['post_path']=ident(c);need(ident(a)==ident(c),'bootstrap_path_after_close');row['sha256']=sha(b);row['read_returned']=True
 return b,row
class StopRequested(BaseException):pass
class ObservedText(io.StringIO):
 def __init__(self,text,row):super().__init__(text,newline=None);self.custody=row
 def close(self):
  need(not self.custody['text_close_entered'],'text_close_once')
  self.custody['text_close_entered']=True
  try:super().close();self.custody['text_close_ack']=True
  except BaseException as e:self.custody['text_close_error']=e;raise
class ObservedIO:
 def __init__(self,root,allowed,stop_path,source_cap,started):
  self.root=Path(root);self.allowed={pathkey(p['path']):p for p in allowed};self.stop_path=Path(stop_path)
  need(type(source_cap) is int and 0<source_cap<=512*MiB,'root_debited_source_allowance');self.source_cap=source_cap
  self.read_requested=self.product_requested=0;self.rows=[];self.returns=[];self.general_native_reads=[None]*3;self.failed=False
  self.outputs=[];self.phases=[];self.started=started;self.capture=None
 def check(self):
  if self.stop_path.exists():raise StopRequested('root_cooperative_STOP')
  if time.perf_counter()-self.started>40:raise StopRequested('cooperative_work_deadline')
 def checkpoint(self,state,label):
  # Retain the exact original capture before any callback/clock/STOP failure.
  self.returns.append(state)
  need(len(self.phases)<4096 and type(label) is str and len(label.encode())<=512,'finite_phase_domain')
  t=time.perf_counter();note={'phase':label,'elapsed_seconds':t-self.started,'monotonic_seconds':t,'utc_ns':time.time_ns()}
  self.phases.append(note);self.check();return note
 def require_live(self):need(not self.failed,'prior_IO_failure');self.check()
 def read(self,path,*,pin=None,cap=None,allow_new=False):
  self.require_live();path=Path(path);expected=pin or self.allowed.get(pathkey(path))
  need(expected is not None or allow_new,'unlisted_file_refused')
  if expected is not None:
   need(set(expected)=={'path','bytes','sha256'} and pathkey(expected['path'])==pathkey(path),'closed_physical_pin')
   need(cap is None or expected['bytes']<=cap,'caller_per_file_cap');cap=expected['bytes']
  need(type(cap) is int and 0<=cap<=128*MiB,'finite_read_extent')
  row={'path':str(path),'request':cap+1,'entered':True,'opened':False,'close_entered':False,'close_ack':False,'primary':None,'close_error':None,'raw':None}
  need(len(self.rows)<8192,'source_IO_row_cap');self.rows.append(row);need(self.read_requested+cap+1<=self.source_cap,'source_asset_read_union');self.read_requested+=cap+1
  fd=None;primary=None
  try:
   a=path.lstat();need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and not getattr(a,'st_file_attributes',0)&1024 and a.st_size<=cap,'regular_single_link_no_reparse')
   row['pre_path']=ident(a);fd=os.open(path,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT);row['opened']=True
   q=os.fstat(fd);row['pre_fd']=ident(q);need(bridge(a)==bridge(q),'descriptor_path_bridge')
   b=os.read(fd,cap+1);row['raw']=b;z=os.fstat(fd);row['post_fd']=ident(z)
   need(ident(q)==ident(z) and len(b)==a.st_size,'complete_stable_fd_read')
  except BaseException as e:row['primary']=primary=e;self.failed=True;raise
  finally:
   if fd is not None:
    row['close_entered']=True
    try:os.close(fd);row['close_ack']=True
    except BaseException as e:
     row['close_error']=e;self.failed=True
     if primary is None:raise
  try:
   c=path.lstat();row['post_path']=ident(c);need(ident(a)==ident(c),'stable_path_after_close')
   row['sha256']=sha(b)
   need(expected is None or (len(b)==expected['bytes'] and sha(b)==expected['sha256']),'exact_full_pin')
   row['read_returned']=True
  except BaseException as e:row['primary']=e;self.failed=True;raise
  return b
 def read_bytes(self,path):return self.read(path)
 def hash_file(self,path):return sha(self.read(path))
 def json_file(self,path):
  b=self.read(path);value=json.loads(b.decode('utf-8-sig'));self.returns.append(value);return value
 def text_reader(self,path):
  b=self.read(path);r={'raw':b,'text':None,'owner':None,'text_close_entered':False,'text_close_ack':False,'text_close_error':None};self.returns.append(r)
  r['text']=b.decode('utf-8');r['owner']=ObservedText(r['text'],r);return r['owner']
 def retain_general_native_read(self,index,custody):
  need(type(index) is int and 0<=index<3 and type(custody) is list and not custody and self.general_native_reads[index] is None,'three_original_custody_lists')
  self.general_native_reads[index]=custody
 def publish(self,name,b,*,failure=False):
  # Failure publication is a separate lane and never clears a poisoned read.
  need(name in CAPS and type(b) is bytes and len(b)<=CAPS[name],'complete_artifact_cap_no_truncation')
  if not failure:self.require_live()
  p=self.root/name;need(not p.exists(),'exclusive_once_product')
  self.product_requested+=2*len(b)+1;need(self.product_requested<=768*MiB,'known_product_write_readback_union')
  row={'path':str(p),'write_requested':len(b),'readback_requested':len(b)+1,'write_raw':b,'write_entered':True,'write_returned':None,'close_entered':False,'close_ack':False,'readback_close_ack':False,'primary':None}
  self.outputs.append(row);fd=None
  try:
   fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_BINARY|os.O_NOINHERIT,0o600)
   row['write_returned']=os.write(fd,b);need(row['write_returned']==len(b),'partial_write')
   os.fsync(fd)
  except BaseException as e:row['primary']=e;self.failed=True;raise
  finally:
   if fd is not None:
    row['close_entered']=True
    try:os.close(fd);row['close_ack']=True
    except BaseException as e:
     row['close_error']=e;self.failed=True
     if row['primary'] is None:raise
  fd=None;secondary=None
  try:
   a=p.lstat();row['readback_pre_path']=ident(a);need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and not getattr(a,'st_file_attributes',0)&1024,'product_regular_once')
   fd=os.open(p,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT);q=os.fstat(fd);row['readback_pre_fd']=ident(q);need(bridge(a)==bridge(q),'product_bridge')
   back=os.read(fd,len(b)+1);row['readback_raw']=back;z=os.fstat(fd);row['readback_post_fd']=ident(z);need(ident(q)==ident(z) and back==b,'full_original_readback')
  except BaseException as e:row['readback_error']=secondary=e;self.failed=True;raise
  finally:
   if fd is not None:
    row['readback_close_entered']=True
    try:os.close(fd);row['readback_close_ack']=True
    except BaseException as e:
     row['readback_close_error']=e;self.failed=True
     if secondary is None:raise
  c=p.lstat();row['readback_post_path']=ident(c);need(ident(a)==ident(c),'product_stable_after_close')
  row.update(bytes=len(b),sha256=sha(b));return {'path':str(p),'bytes':len(b),'sha256':sha(b)}
 def stream_product(self,name,producer):
  # The supported error graph is emitted once in64KiB batches. Full actual
  # failed chunk is retained; completed counts/hash plus the actual partial file
  # stay discoverable. A publication failure never claims complete custody.
  need(name in ('PYTHON-REACHABLE-DATA.bin','PYTHON-REACHABLE-NORMAL.bin') and not (self.root/name).exists(),'exclusive_error_stream')
  p=self.root/name;row={'path':str(p),'streamed':True,'write_entered':False,'write_returned':0,'close_entered':False,'close_ack':False,'readback_close_entered':False,'readback_close_ack':False,'chunks':[],'pending_original_chunk':None,'primary':None};self.outputs.append(row)
  fd=None;primary=None;total=0;digest=hashlib.sha256();buffer=bytearray()
  def flush():
   nonlocal total
   if not buffer:return
   self.check()
   chunk=bytes(buffer);buffer.clear();row['pending_original_chunk']=chunk
   need(total+len(chunk)<=CAPS[name],'complete_stream_extent')
   self.product_requested+=len(chunk);need(self.product_requested<=768*MiB,'stream_write_union')
   count=os.write(fd,chunk);row['chunks'].append({'offset':total,'requested':len(chunk),'returned':count,'sha256':sha(chunk)})
   need(count==len(chunk),'partial_stream_write')
   total+=count;digest.update(chunk);row['write_returned']=total;row['pending_original_chunk']=None
  def emit(b):
   need(type(b) is bytes,'exact_stream_chunk_bytes')
   for start in range(0,len(b),65536):
    part=b[start:start+65536]
    if len(buffer)+len(part)>65536:flush()
    buffer.extend(part)
  try:
   fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_BINARY|os.O_NOINHERIT,0o600);row['write_entered']=True
   info=producer(emit);flush();os.fsync(fd)
  except BaseException as e:row['primary']=primary=e;self.failed=True;raise
  finally:
   if fd is not None:
    row['close_entered']=True
    try:os.close(fd);row['close_ack']=True
    except BaseException as e:
     row['close_error']=e;self.failed=True
     if primary is None:raise
  row['complete_producer_return']=info;read_digest=hashlib.sha256();remaining=total;fd=None;secondary=None
  self.product_requested+=total+1;need(self.product_requested<=768*MiB,'stream_full_readback_union')
  try:
   a=p.lstat();row['readback_pre_path']=ident(a);need(a.st_size==total and stat.S_ISREG(a.st_mode) and a.st_nlink==1 and not getattr(a,'st_file_attributes',0)&1024,'complete_stream_regular_file')
   fd=os.open(p,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT);q=os.fstat(fd);row['readback_pre_fd']=ident(q);need(bridge(a)==bridge(q),'stream_readback_bridge')
   while remaining:
    self.check()
    count=min(65536,remaining);b=os.read(fd,count);row['readback_pending_original_chunk']=b;need(len(b)==count,'complete_stream_chunk')
    read_digest.update(b);remaining-=len(b);row['readback_pending_original_chunk']=None
   end=os.read(fd,1);row['readback_end_original']=end;need(end==b'','stream_exact_EOF');z=os.fstat(fd);row['readback_post_fd']=ident(z);need(ident(q)==ident(z) and read_digest.digest()==digest.digest(),'complete_stream_original_readback')
  except BaseException as e:row['readback_error']=secondary=e;self.failed=True;raise
  finally:
   if fd is not None:
    row['readback_close_entered']=True
    try:os.close(fd);row['readback_close_ack']=True
    except BaseException as e:
     row['readback_close_error']=e;self.failed=True
     if secondary is None:raise
  c=p.lstat();row['readback_post_path']=ident(c);need(ident(a)==ident(c),'stream_path_after_close')
  row.update(bytes=total,sha256=digest.hexdigest());return {'path':str(p),'bytes':total,'sha256':digest.hexdigest()},info
 def summary(self):
  # Full returned raw inputs are kept in error custody; normal IO rows contain exact extents/pins.
  def clean(r):
   # New normal-IO projection: preserve the one declared raw stream EOF field
   # without mutating its original bytes/row or introducing a generic encoder.
   omitted=('raw','write_raw','readback_raw','primary','close_error','readback_error','readback_close_error')
   out={}
   for k,v in r.items():
    if k in omitted:continue
    if type(v) is bytes:
     need(k=='readback_end_original' and len(v)<=1,'declared_normal_IO_EOF_byte_field')
     out[k]={'schema':'avatar233.normal-IO-bytes.v1','bytes':len(v),'sha256':sha(v),'hex':v.hex()}
    else:out[k]=v
   return out
  return {'schema':'avatar233.observed-python-IO-lossless-bytes.v1','byte_encoding':'avatar233.normal-IO-bytes.v1','declared_byte_fields':['readback_end_original'],'read_requested':self.read_requested,'product_requested_including_readback':self.product_requested,'read_cap':self.source_cap,'product_cap':768*MiB,'reads':[clean(r) for r in self.rows],'outputs':[clean(r) for r in self.outputs],'scope':'complete_IO_prefix_before_own_PYTHON_IO_and_RESULT_publication','excluded_final_tail':{'names':['PYTHON-IO.json','RESULT.json'],'write_readback_reserved':2*(CAPS['PYTHON-IO.json']+CAPS['RESULT.json'])+2,'root_must_acquire_exact_original_tail_files':True},'native_operator_IO_requested':None,'native_producer_close_observed':None,'native_complete_qualification':False}


