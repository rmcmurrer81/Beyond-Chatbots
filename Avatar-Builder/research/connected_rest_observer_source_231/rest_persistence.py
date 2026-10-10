"""Inactive pure-value full-rest source; original supplied values only. No missing-original recovery or caller/native admission."""
import hashlib,json,math,struct

PROJECTION_CAP=1048576
STATE_CAP=4194304

class RestPersistenceRefusal(RuntimeError):
 def __init__(self,capture,primary):super().__init__('full_original_rest_persistence_refused');self.capture=capture;self.primary=primary

def prepare_full_rest_persistence230(rest,lineage_binding,source_pins,checkpoint):
 capture={'original_rest':rest,'original_lineage_binding':lineage_binding,'original_source_pins':source_pins,'original_projection_bytes':None,'original_full_points':None,'original_compaction_pairs':None,'manifest':None,'manifest_bytes':None,'completed':False}
 try:
  checkpoint('rest-persistence230:before')
  projection_bytes=rest['projection_bytes'];capture['original_projection_bytes']=projection_bytes
  if type(projection_bytes)is not bytes or len(projection_bytes)>PROJECTION_CAP:raise ValueError('full original projection supported byte domain')
  if hashlib.sha256(projection_bytes).hexdigest()!=lineage_binding['handoff_sha256']:raise ValueError('original projection and lineage hash differ')
  projection=rest['projection']
  if json.dumps(projection,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')!=projection_bytes:raise ValueError('full original projection value/bytes changed')
  full_points=rest['full_points'];source_points=rest['source_canonical_points'];pairs=rest['compaction_pairs'];capture['original_full_points']=full_points;capture['original_source_canonical_points']=source_points;capture['original_compaction_pairs']=pairs
  if type(full_points)is not tuple or len(full_points)!=19158 or type(pairs)is not tuple or len(pairs)!=13380:raise ValueError('entire original19158/13380 sampled domain')
  for ordinal,p in enumerate(full_points):
   if ordinal%256==0:checkpoint('rest-persistence230:original-point:'+str(ordinal))
   if type(p)is not tuple or len(p)!=3 or any(type(x)is not float or not math.isfinite(x) for x in p):raise ValueError('supported original scalar sampled point')
   if struct.unpack('<3f',struct.pack('<3f',*p))!=p:raise ValueError('original sampled point must already be binary32')
  if any(type(pair)is not tuple or len(pair)!=2 or type(pair[0])is not int or type(pair[1])is not int or not 0<=pair[0]<19158 for pair in pairs):raise ValueError('original complete compaction pair domain')
  if tuple(pair[1] for pair in pairs)!=tuple(range(13380)):raise ValueError('original sorted global compaction order')
  if type(source_points)is not tuple or len(source_points)!=19158:raise ValueError('full original before-conversion canonical samples required')
  for ordinal,p in enumerate(source_points):
   if ordinal%256==0:checkpoint('rest-persistence230:source-point:'+str(ordinal))
   if type(p)is not tuple or len(p)!=3 or any(type(x)is not float or not math.isfinite(x) for x in p) or struct.unpack('<3f',struct.pack('<3f',*p))!=p:raise ValueError('original canonical source binary32 sample domain')
  manifest={'schema':'kira.avatar.connected_rest_full_source_manifest230.v1','source_route':'produce_pre_surface_rest_lane','original_canonical_rig_rest_handoff':projection,'original_projection_utf8':projection_bytes.decode('utf8'),'original_projection_sha256':hashlib.sha256(projection_bytes).hexdigest(),'original_full_scaled_canonical_rest_points':full_points,'original_morphed_source_Y_up_points':source_points,'original_compaction_pairs':pairs,'original_lineage_binding':lineage_binding,'selected_source_pin_evidence':source_pins,'original_morphed_source_Y_up_points_included':True,'source_before_native_coordinate_conversion_digest':rest['input_points_digest'],'original_morphed_source_points_cannot_be_recovered_from_digest':True,'original_native_in_process_objects_not_serialized_or_claimed_complete':True,'compact_report_schema_remains_separate':True,'scientific_or_anatomical_or_physiological_or_birth_acceptance':False,'runtime_authority':False}
  capture['manifest']=manifest;encoded=json.dumps(manifest,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8');capture['manifest_bytes']=encoded
  if len(encoded)>STATE_CAP:raise ValueError('complete full rest state supported byte domain exceeded; no clipping')
  checkpoint('rest-persistence230:after');capture['completed']=True
  return capture
 except BaseException as primary:raise RestPersistenceRefusal(capture,primary) from primary
