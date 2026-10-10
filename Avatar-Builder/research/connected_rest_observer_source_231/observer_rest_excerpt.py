"""Complete existing-route source excerpts; inactive, not directly runnable.
Remaining sources, physical IO, callbacks and native identity admission are
external. No bootstrap/main/launcher/private body values are included.
"""
from pathlib import Path
import sys,types,importlib.util,importlib.machinery,json
from python_custody_graph import capture_to
ROLES = {'trial', 'backend', 'poses', 'lineage_evidence', 'compiler', 'rest_utility', 'entry', 'controller', 'integration', 'producer', 'unused_repair_binding', 'rest_persistence', 'canonical_lineage', 'qualification', 'mesh_intersections', 'resolver', 'unused_surface_binding', 'frame_parameters', 'owned_carrier_io'}
LOAD_ORDER = ('owned_carrier_io', 'frame_parameters', 'mesh_intersections', 'backend', 'canonical_lineage', 'compiler', 'controller', 'entry', 'integration', 'lineage_evidence', 'poses', 'producer', 'qualification', 'resolver', 'rest_utility', 'trial', 'unused_repair_binding', 'unused_surface_binding', 'rest_persistence')
GROUP_BINDINGS = ('REGISTRY_PATH', 'evaluate_adult_foundation_qualification', 'frame_from_mapping', 'parameters_from_mapping', 'author_continuous_adult_female_surface', 'repair_bounded_self_intersections', 'lineage_summary', 'require_mesh_rows', 'seed_mesh_rows', 'resolve_makehuman_skeleton_geometry', 'SKELETON_SHA256', 'prepare_rest_handoff', 'require_rest_handoff_unchanged')
IDENTITY_FIELDS = {'source_read_cap', 'executable', 'inputs_sha256', 'process_birth_utc', 'argv', 'root_source_receipt', 'child_source_read_allowance', 'qpc_start', 'pid', 'schema', 'role', 'root_source_read_requested', 'attempt_id', 'qpc_frequency'}
BODY_DOMAIN = None
raw = sha = need = pathkey = same_pin = CAPS = None

def python_custody_instances(state,io):
 result=[]
 if io is not None:
  fields=dict(vars(io))
  fields['rows']=tuple(dict(r) for r in io.rows)
  fields['outputs']=tuple(dict(r) for r in io.outputs) # excludes future capture producer/chunks
  fields['phases']=tuple(dict(r) for r in io.phases)
  fields['returns']=tuple(io.returns) # exact returned objects/aliases stay strongly rooted
  result.append((io,fields))
 modules=state['modules']
 if 'lineage_evidence' in modules:
  cls=modules['lineage_evidence'].LineageBoundaryCustody
  for owner in state['lineage_owners']:
   need(type(owner) is cls,'exact_lineage_owner_type')
   fields={name:object.__getattribute__(owner,name) for name in cls.__slots__};result.append((owner,fields))
 if 'backend' in modules:
  cls=modules['backend'].BlenderRestAttachmentBackend
  owners=[state.get('backend'),state.get('producer',{}).get('backend')]
  if io is not None:owners.extend(r.get('backend') for r in io.returns if type(r) is dict)
  for owner in owners:
   if owner is not None:
    need(type(owner) is cls,'exact_backend_owner_type');result.append((owner,dict(object.__getattribute__(owner,'__dict__'))))
 if state.get('layout') is not None:
  owner=state['layout'];cls=modules['producer'].ProducerSourceLayout;need(type(owner) is cls,'exact_layout_owner_type')
  result.append((owner,{name:object.__getattribute__(owner,name) for name in cls.__slots__}))
 return result

def _stream_IO_projection(row):
 # Ordinary returned stream fields retain their JSON types; every actual byte
 # value has a new closed/versioned representation, rather than being dropped.
 omitted={'primary','close_error','readback_error','readback_close_error','complete_producer_return','pending_original_chunk','readback_pending_original_chunk'}
 value={};byte_fields=[]
 for k,v in row.items():
  if k in omitted:continue
  if type(v) is bytes:
   need(k=='readback_end_original' and len(v)<=1,'source_declared_stream_byte_field');byte_fields.append(k);value[k]=closed_error_bytes(v)
  else:value[k]=v
 return {'schema':'avatar225.capture-stream-IO-projection.v1','byte_encoding':'avatar225.error-bytes.v1','byte_fields':byte_fields,'values':value,'exception_fields_are_separately_rooted':True}

def load_sources(io,pins,state):
 need(set(pins)==ROLES and len(LOAD_ORDER)==len(ROLES)==19 and set(LOAD_ORDER)==ROLES,'exact_eighteen_source_order')
 need(all(type(pins[r]['path']) is str and len(pins[r]['path'].encode('utf-8','surrogatepass'))<=512 for r in LOAD_ORDER),'bounded_selected_source_pin_paths')
 result={};loader={'load_order':list(LOAD_ORDER),'rows':[],'namespace_owners':[],'aliases':{},'unselected_package_initializers_executed':False}
 state['source_loader']=loader
 alias_roles={'owned_carrier_io':'owned_carrier_io','frame_parameters':'Core.avatar_adult_female_surface_authoring','mesh_intersections':'tools.blender_exact_mesh_intersections'}
 all_names=['Core','tools']+list(alias_roles.values())+['_avatar_observation225_'+r for r in LOAD_ORDER]
 need(len(set(all_names))==len(all_names) and all(n not in sys.modules for n in all_names),'fresh_owned_source_and_alias_namespaces')
 for name in ('Core','tools'):
  module=types.ModuleType(name);module.__package__=name;module.__path__=[]
  module.__spec__=importlib.machinery.ModuleSpec(name,loader=None,is_package=True)
  loader['namespace_owners'].append(module);sys.modules[name]=module
  loader['aliases'][name]={'role':None,'package_path':[],'initializer':None}
 for ordinal,role in enumerate(LOAD_ORDER,1):
  io.check();p=pins[role];b=io.read(p['path'],pin=p);name='_avatar_observation225_'+role
  before=tuple(sys.path)
  need(len(before)<=32 and all(type(x) is str and len(x.encode('utf-8','surrogatepass'))<=512 for x in before) and sum(len(x.encode('utf-8','surrogatepass')) for x in before)<=4096,'bounded_original_import_path')
  row={'ordinal':ordinal,'role':role,'pin':dict(p),'module_name':name,'alias_names':[],'path_before':before,'path_after_exec':None,'path_restore_ack':False,'exec_entered':False,'exec_returned':False,'primary':None,'path_error':None}
  loader['rows'].append(row)
  spec=importlib.util.spec_from_file_location(name,p['path']);need(spec is not None,'exact_source_spec')
  module=importlib.util.module_from_spec(spec);state['modules'][role]=module;sys.modules[name]=module
  primary=None;row['exec_entered']=True
  try:
   # All eighteen original bodies execute once from authenticated returned bytes.
   # Closed local aliases already exist before their dependent imports execute.
   exec(compile(b,p['path'],'exec'),module.__dict__)
   row['exec_returned']=True
  except BaseException as error:row['primary']=primary=error;raise
  finally:
   after=tuple(sys.path);row['path_after_exec']=after
   expected=before
   if role in ('unused_surface_binding','unused_repair_binding'):
    addition=str(Path(p['path']).resolve().parents[1]);need(len(addition.encode('utf-8','surrogatepass'))<=512,'bounded_exact_source_import_path_addition')
    if addition not in before:expected=(addition,)+before
   if after==expected:
    try:sys.path[:]=before;row['path_restore_ack']=tuple(sys.path)==before;need(row['path_restore_ack'],'exact_owned_import_path_restore')
    except BaseException as error:
     row['path_error']=error
     if primary is None:raise
   else:
    error=ValueError('unrecognized_source_import_path_mutation');row['path_error']=error
    # Preserve an original primary if present; retain the independent path error.
    # Unexpected mutation is never silently restored or positively admitted.
    if primary is None:raise error
  need(pathkey(module.__file__)==pathkey(p['path']),'source_origin')
  if role in alias_roles:
   alias=alias_roles[role];need(alias not in sys.modules,'fresh_exact_leaf_alias')
   sys.modules[alias]=module;row['alias_names'].append(alias)
   if '.' in alias:
    parent,leaf=alias.rsplit('.',1);owner=sys.modules[parent]
    need(type(owner) is types.ModuleType and owner.__path__==[] and not hasattr(owner,leaf),'owned_empty_namespace_parent')
    setattr(owner,leaf,module);need(getattr(owner,leaf) is module,'exact_parent_leaf_identity')
   loader['aliases'][alias]={'role':role,'module_name':name,'pin':dict(p)}
  result[role]=module;io.check()
 need(len(result)==19 and all(row['exec_returned'] and row['path_restore_ack'] and row['primary'] is None and row['path_error'] is None for row in loader['rows']),'all_original_eighteen_execs')
 return result

def normal_source_loader_projection(state):
 loader=state['source_loader']
 value={'schema':'avatar231.actual-nineteen-source-loader.v1','load_order':loader['load_order'],'aliases':loader['aliases'],'namespace_initializers':None,'namespace_paths_empty':True,'rows':[{k:v for k,v in row.items() if k not in ('primary','path_error')} for row in loader['rows']]}
 need(len(raw(value,1048576))<=1048576,'complete_normal_loader_json_domain')
 return value

def full_mesh(body,backend,state,label):
 """Complete bounded numeric mesh/rig observations. Native storage/allocator behind getters unknown."""
 mesh=body.data;arm=body.parent
 need(len(mesh.vertices)==13380 and len(mesh.polygons)==13378 and len(mesh.edges)==26756,'mesh_domain')
 need(arm is not None and len(arm.data.bones)==163,'rig_domain')
 value={'schema':'avatar224.full-mesh-rig-observation.v1','vertices':[],'edges':[],'faces':[],'weight_groups':[],'bones':[],'body_world':None,'armature_world':None,'parent_inverse':None,'backend':None}
 state['observations'][label]=value # before any getter/loop can fail
 for group in body.vertex_groups:
  need(type(group.name) is str and len(group.name.encode())<=256 and 0<=group.index<256,'weight_name_and_index')
  value['weight_groups'].append([group.index,group.name])
 need(len(value['weight_groups'])<=256,'weight_group_domain')
 for v in mesh.vertices:
  need(0<=v.index<13380 and len(v.groups)<=4 and all(0<=g.group<256 for g in v.groups),'maximum_four_weights_and_index_domain')
  value['vertices'].append({'index':v.index,'co':list(v.co),'weights':[[g.group,g.weight] for g in v.groups]})
 for e in mesh.edges:
  need(0<=e.index<26756 and len(e.vertices)==2 and all(0<=i<13380 for i in e.vertices),'edge_index_domain');value['edges'].append([e.index,list(e.vertices)])
 for p in mesh.polygons:
  need(0<=p.index<13378 and 3<=len(p.vertices)<=4 and all(0<=i<13380 for i in p.vertices),'original_body_polygon_domain')
  value['faces'].append([p.index,list(p.vertices)])
 for b in arm.data.bones:
  need(type(b.name) is str and len(b.name.encode())<=128 and (b.parent is None or len(b.parent.name.encode())<=128),'bone_name_domain')
  pose=arm.pose.bones.get(b.name);need(pose is not None,'pose_bone')
  value['bones'].append({'name':b.name,'parent':b.parent.name if b.parent else None,'head':list(b.head_local),'tail':list(b.tail_local),'matrix_local':[[float(x) for x in r] for r in b.matrix_local],'use_deform':b.use_deform,'use_connect':b.use_connect,'basis':[[float(x) for x in r] for r in pose.matrix_basis],'rotation_mode':pose.rotation_mode})
 value['body_world']=[[float(x) for x in r] for r in body.matrix_world]
 value['armature_world']=[[float(x) for x in r] for r in arm.matrix_world]
 value['parent_inverse']=[[float(x) for x in r] for r in body.matrix_parent_inverse]
 need([v['index'] for v in value['vertices']]==list(range(13380)),'every_original_body_vertex_in_order')
 need(sha(raw([r[1] for r in value['faces']]))==BODY_DOMAIN['source_compacted_faces_sha256'],'every_original_source_body_face_in_order')
 need(sorted(g[1] for g in value['weight_groups'])==BODY_DOMAIN['effective_weight_group_names'],'exact_remapped_body_weight_groups')
 value['backend']=backend.observe(body)
 return value

def bind_layout(modules,project_root):
 p=modules['producer'];q=modules['qualification'];f=modules['frame_parameters'];u=modules['rest_utility'];c=modules['canonical_lineage'];r=modules['resolver']
 bindings=(q.REGISTRY_PATH,q.evaluate_adult_foundation_qualification,f.frame_from_mapping,f.parameters_from_mapping,modules['unused_surface_binding'].author_continuous_adult_female_surface,modules['unused_repair_binding'].repair_bounded_self_intersections,c.lineage_summary,c.require_mesh_rows,c.seed_mesh_rows,r.resolve_makehuman_skeleton_geometry,u.SKELETON_SHA256,u.prepare_rest_handoff,u.require_rest_handoff_unchanged)
 need(len(bindings)==len(GROUP_BINDINGS),'exact_original_bindings')
 return p.ProducerSourceLayout(Path(project_root),bindings)

def fresh_lineage(modules,result,body,io,state):
 l=modules['lineage_evidence'];owner=l.LineageBoundaryCustody();state['lineage_owners'].append(owner)
 return l.capture_fresh_lineage(result,body,modules['canonical_lineage'],modules['rest_utility'].require_rest_handoff_unchanged,io.checkpoint,custody=owner)

def matching_lineage(modules,body,witness,io,state,label):
 l=modules['lineage_evidence'];owner=l.LineageBoundaryCustody();state['lineage_owners'].append(owner)
 result=l.observe_matching_lineage(body,witness,modules['canonical_lineage'],io.checkpoint,custody=owner)
 state['lineage'][label]=result
 return result

def capture_rest_properties231(body,io,state,label):
 """Exactly one native getter per separate original property, retained before encoding.
 Native getter/allocator internals remain unknown; missing originals are a refusal.
 """
 specs=(('inactive_foundation_build_manifest_json',8192,'REST-COMPACT.json'),
        ('inactive_foundation_producer_manifest_json',4194304,'REST-MANIFEST.json'),
        ('inactive_foundation_canonical_rest_handoff_json',1048576,'REST-PROJECTION.json'))
 capture={'body':body,'rows':[],'completed':False};state.setdefault('rest_property_captures',{})[label]=capture
 io.checkpoint(state,label+':getter-before');getter=getattr(body,'__getitem__');capture['original_getter']=getter
 for key,cap,name in specs:
  row={'property':key,'cap':cap,'artifact':name,'get_entered':True,'get_ack':False,'original_text':None,'original_utf8':None,'parsed':None};capture['rows'].append(row)
  value=getter(key);row['original_text']=value;row['get_ack']=True
  need(type(value)is str,'original_property_string');b=value.encode('utf-8');row['original_utf8']=b
  need(len(b)<=cap,'whole_original_property_cap_no_clipping');row['parsed']=json.loads(b)
  io.checkpoint(state,label+':original-property:'+key)
 need(capture['rows'][0]['parsed']['schema']=='kira.avatar.pre_surface_rest_lane.report.v1','original_compact_schema')
 manifest=capture['rows'][1]['parsed'];projection=capture['rows'][2]['parsed']
 need(manifest['schema']=='kira.avatar.connected_rest_full_source_manifest230.v1','qualified_complete_manifest_schema')
 need(manifest['original_canonical_rig_rest_handoff']==projection and manifest['original_projection_utf8']==capture['rows'][2]['original_text'],'separate_full_projection_exact_original')
 need(manifest['original_projection_sha256']==sha(capture['rows'][2]['original_utf8']),'original_projection_pin')
 need(len(manifest['original_full_scaled_canonical_rest_points'])==19158 and len(manifest['original_morphed_source_Y_up_points'])==19158 and len(manifest['original_compaction_pairs'])==13380,'full_original_preconversion_scaled_and_mapping_domains')
 capture['completed']=True;return capture

def rest_capture_equal231(a,b):
 return tuple(r['original_utf8'] for r in a['rows'])==tuple(r['original_utf8'] for r in b['rows'])

def capture_normal_state231(io,state):
 # Same rooted graph support as the existing error route; original builtins and
 # selected instance fields are retained. Native internals are opaque, not admitted.
 external=[(r['raw'],{'path':r['path'],'bytes':len(r['raw']),'sha256':r['sha256']}) for r in io.rows if r.get('read_returned') and type(r.get('raw'))is bytes and r.get('close_ack') and r.get('sha256')]
 for row in io.outputs:
  if row.get('close_ack') and row.get('readback_close_ack') and row.get('sha256'):
   external.extend((row[k],{q:row[q] for q in ('path','bytes','sha256')}) for k in ('write_raw','readback_raw') if type(row.get(k))is bytes)
 instances=python_custody_instances(state,io);state['normal_selected_instance_fields']=instances
 info=capture_to(io,state,external,instances,artifact_name='PYTHON-REACHABLE-NORMAL.bin');state['normal_graph_info']=info
 info['capture_stream_IO']=_stream_IO_projection(io.outputs[-1]);info['native_capture_complete']=False
 return io.publish('PYTHON-REACHABLE-NORMAL.json',raw(info,CAPS['PYTHON-REACHABLE-NORMAL.json']))

def writer(modules,bpy,inputs,io,state):
 m=modules;layout=bind_layout(m,inputs['project_root']);state['layout']=layout
 pins={k:inputs['source_pin_evidence'][k] for k in m['integration'].EXPECTED_SOURCE_PINS}
 profile=io.read(inputs['profile']['path'],pin=inputs['profile'])
 result=m['controller'].run_optional_rest_lane({'mode':m['integration'].MODE,'config_path':Path(inputs['recipe']['path']),'acknowledge_inactive_authoring':True},integration=m['integration'],producer=m['producer'],compiler=m['compiler'],backend_type=m['backend'].BlenderRestAttachmentBackend,profile_raw=profile,source_pin_evidence=pins,checkpoint=io.checkpoint,asset_lane=io,source_layout=layout,rest_persistence=m['rest_persistence'])
 state['producer']=result;body=result['objects']['body'];backend=result['backend'];state['body']=body
 need(len(result['original_vertices_and_faces'][0])==19158 and len(result['compact_inputs'][0])==13380 and len(result['compact_inputs'][1])==13378,'full_canonical_and_body_domains')
 need(sha(raw(sorted(result['compact_inputs'][2])))==BODY_DOMAIN['source_used_global_indices_sha256'] and sha(raw(result['compact_inputs'][1]))==BODY_DOMAIN['source_compacted_faces_sha256'],'exact_original_source_mapping_and_faces')
 need(result['report']['bone_count']==163 and result['report']['surface_authoring_performed'] is False,'selected_pre_surface')
 need(all(b.matrix_basis.is_identity for b in body.parent.pose.bones),'neutral_writer')
 rest_before=capture_rest_properties231(body,io,state,'writer-rest-before-save');rest_pins={}
 for row in rest_before['rows']:rest_pins[row['artifact']]=io.publish(row['artifact'],row['original_utf8'])
 obs=full_mesh(body,backend,state,'writer-before-save')
 m['compiler']._verify_attached(obs['backend'],result['attachment_capture']['plan'])
 lineage=fresh_lineage(m,result,body,io,state);state['lineage']['writer-fresh']=lineage
 witness=lineage['witness'];blend=io.root/'carrier.blend';need(not blend.exists(),'fresh_blend')
 io.checkpoint(state,'one_real_native_save_enter')
 native=bpy.ops.wm.save_as_mainfile(filepath=str(blend),check_existing=True)
 state['native_save_return']=native;io.checkpoint(state,'one_real_native_save_return')
 need(native=={'FINISHED'},'save_operator_return')
 blob=io.read(blend,cap=64*1048576,allow_new=True);blobpin={'path':str(blend),'bytes':len(blob),'sha256':sha(blob)}
 need(len(blob)>0,'saved_blob')
 rest_after=capture_rest_properties231(body,io,state,'writer-rest-after-save');need(rest_capture_equal231(rest_before,rest_after),'save_preserves_complete_original_rest_properties')
 after=full_mesh(body,backend,state,'writer-after-save');need(raw(after)==raw(obs),'save_changed_full_static_observation')
 matching_lineage(m,body,witness,io,state,'writer-after-save')
 return {'static_snapshot_values':{'writer-before-save':{'full_value_sha256':sha(raw(obs))},'writer-after-save':{'value_equals':'writer-before-save','full_value_sha256':sha(raw(after)),'equality_guard_passed':True,'identity_equality_claimed':False}},'schema':'avatar224.writer-observations.v1','attempt_id':inputs['attempt_id'],'saved_blob':blobpin,'body_name':body.name,'armature_name':body.parent.name,'lineage_binding':result['lineage_binding'],'lineage_witness':witness,'full_static':obs,'full_rest_properties':rest_pins,'full_rest_persistence_observed':True,'anatomy_validated':False,'strictNativeBoundIO':False,'source_pin_evidence':inputs['source_pin_evidence'],'native_save_return':sorted(native),'native_producer_close_observed':None,'native_operator_IO_requested':None,'full_body_ready':False,'runtime_activation_allowed':False}

def reader(modules,bpy,inputs,io,state):
 m=modules;receipt=inputs['writer_receipt']
 need(type(receipt) is dict and set(receipt)=={'original_tool_return','original_call_sequence','review','own','observations','launch_identity','rest_manifest','rest_projection','rest_compact'},'exact_external_writer_custody')
 caps={'original_tool_return':32*1048576,'original_call_sequence':32*1048576,'review':131072,'own':131072,'launch_identity':8192}
 custody={k:json.loads(io.read(receipt[k]['path'],pin=receipt[k],cap=v)) for k,v in caps.items()};state['writer_custody']=custody
 tool=custody['original_tool_return'];review=custody['review'];own=custody['own'];series=custody['original_call_sequence'];identity=custody['launch_identity']
 need(type(tool) is dict and set(tool)=={'schema','attempt_id','role','result'} and tool['schema']=='avatar225.original-tool-return.v1' and tool['attempt_id']==inputs['attempt_id'] and tool['role']=='writer','closed_original_writer_return')
 original_return=tool['result'];need(type(original_return) is dict and original_return.get('exit_code')==0 and 'session_id' not in original_return and type(original_return.get('chunk_id')) is str and type(original_return.get('wall_time_seconds')) in (int,float),'normal_original_writer_tool')
 need(type(series) is dict and set(series)=={'schema','attempt_id','role','calls'} and series['schema']=='avatar225.original-tool-call-sequence.v1' and series['attempt_id']==inputs['attempt_id'] and series['role']=='writer' and type(series['calls']) is list and 1<=len(series['calls'])<=8 and series['calls'][-1]['result']==original_return and all(type(c) is dict and set(c)=={'kind','arguments','result'} and c['kind'] in ('exec_command','write_stdin') for c in series['calls']),'full_original_first_and_tail_writer')
 need(review['schema']=='avatar225.observational-writer-independent-review.v1' and review['role']=='writer' and review['attempt_id']==inputs['attempt_id'] and review['eligible_full_original_rest_writer_reopen231'] is True and review['eligible_for_observational_writer_reopen'] is True and review['normal_process_exit_qualified'] is True and review['runtime_authority'] is False and review['native_complete_qualification'] is False and review['blocking_findings']==[],'scoped_different_writer_review')
 need(all(same_pin(review[k],receipt[k]) for k in ('observations','launch_identity','original_tool_return','original_call_sequence')) and same_pin(own['review'],receipt['review']) and own['actual_review_return']['exit_code']==0,'exact_genuine_writer_review_own')
 current=state['root_launch_identity']
 need(type(identity) is dict and set(identity)==IDENTITY_FIELDS and identity['schema']=='avatar224.root-launch-identity.v1' and identity['role']=='writer' and identity['attempt_id']==inputs['attempt_id'] and identity['pid']!=current['pid'] and identity['process_birth_utc']!=current['process_birth_utc'],'genuinely_distinct_root_observed_reader')
 original=json.loads(io.read(receipt['observations']['path'],pin=receipt['observations']))
 state['writer_observations']=original
 need(original['schema']=='avatar224.writer-observations.v1' and original['attempt_id']==inputs['attempt_id'] and original['source_pin_evidence']==inputs['source_pin_evidence'],'same_exact_writer')
 blob=io.read(original['saved_blob']['path'],pin=original['saved_blob']);need(sha(blob)==original['saved_blob']['sha256'],'cold_full_blob')
 io.checkpoint(state,'one_real_native_load_enter')
 native=bpy.ops.wm.open_mainfile(filepath=original['saved_blob']['path'],load_ui=False)
 state['native_load_return']=native;io.checkpoint(state,'immediate_original_post_open_observation')
 need(native=={'FINISHED'},'load_operator_return')
 # Immediate original return is retained before body/probe work; no fabricated native IO witness.
 body=bpy.data.objects.get(original['body_name']);state['body']=body
 need(body is not None and body.parent is not None and body.parent.name==original['armature_name'],'cold_body_parent')
 backend=m['backend'].BlenderRestAttachmentBackend.__new__(m['backend'].BlenderRestAttachmentBackend);state['backend']=backend
 m['backend'].BlenderRestAttachmentBackend.__init__(backend,bpy,original['lineage_binding'])
 cold_rest=capture_rest_properties231(body,io,state,'reader-original-rest-after-load')
 for row,key in zip(cold_rest['rows'],('rest_compact','rest_manifest','rest_projection')):
  expected_pin=receipt[key];need(same_pin(expected_pin,original['full_rest_properties'][row['artifact']]),'original_writer_full_property_pin');original_property_bytes=io.read(expected_pin['path'],pin=expected_pin);state.setdefault('original_writer_property_bytes',[]).append(original_property_bytes);need(original_property_bytes==row['original_utf8'],'fresh_native_load_preserves_complete_original_property_bytes')
 before=full_mesh(body,backend,state,'reader-cold-neutral');need(raw(before)==raw(original['full_static']),'exact_full_cold_static')
 matching_lineage(m,body,original['lineage_witness'],io,state,'reader-cold')
 trialstate={'returns':[],'objects':{},'phase':'rest-persistence-only'};state['trial_state_custodies'].append(trialstate)
 reports=[];sensors=[];neutral_max=None # rest-only231: original mechanical probes held for separate qualification
 final=full_mesh(body,backend,state,'reader-final-neutral');need(raw(final)==raw(before),'probes_changed_static')
 matching_lineage(m,body,original['lineage_witness'],io,state,'reader-final')
 complete_numeric_returns=[r for r in trialstate['returns'] if r['phase'].endswith((':complete_points',':displacements',':region_observation',':geometric_sensor',':report'))]
 return {'static_snapshot_values':{'reader-cold-neutral':{'value_equals':'writer.full_static','full_value_sha256':sha(raw(before)),'equality_guard_passed':True},'reader-final-neutral':{'value_equals':'reader-cold-neutral','full_value_sha256':sha(raw(final)),'equality_guard_passed':True,'identity_equality_claimed':False}},'schema':'avatar224.reader-observations.v1','attempt_id':inputs['attempt_id'],'full_static':before,'full_original_rest_properties':{r['artifact']:{'bytes':len(r['original_utf8']),'sha256':sha(r['original_utf8'])} for r in cold_rest['rows']},'full_rest_persistence_observed':True,'scalar_equivalence_executed':False,'anatomy_validated':False,'strictNativeBoundIO':False,'neutral_maximum_displacement_m':neutral_max,'complete_numeric_probe_returns':complete_numeric_returns,'reports':reports,'sensors':sensors,'native_load_return':sorted(native),'native_operator_IO_requested':None,'native_producer_close_observed':None,'native_payload_complete':False,'full_body_ready':False,'runtime_activation_allowed':False}
