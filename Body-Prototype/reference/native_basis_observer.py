"""Prospective neutral native eye attachment and tessellation observations only.

No import of bpy, pose setter, saved-scene export, or anatomical acceptance.
The caller supplies exact selected source operands, current bpy, and custody.
"""
import math,struct

def need(value,label):
 if not value:raise ValueError(label)

def point(value):
 need(type(value)in(list,tuple)and len(value)==3,'point_shape')
 out=tuple(float(x)for x in value)
 need(all(type(x)in(int,float)and math.isfinite(float(x))for x in value),'finite_real_point')
 return out

def matrix(value):
 need(type(value)in(list,tuple)and len(value)==4 and all(type(row)in(list,tuple)and len(row)==4 for row in value),'generic_matrix_shape4x4')
 need(all(type(x)in(int,float)and math.isfinite(float(x))for row in value for x in row),'finite_generic_matrix4x4')
 out=[[float(x)for x in row]for row in value]
 need(len(out)==4 and all(len(row)==4 and all(math.isfinite(x)for x in row)for row in out),'finite_native_matrix4x4')
 return out

def native_point(value):
 # Exact native API class; no arbitrary object iteration or subclass admission.
 from mathutils import Vector
 need(type(value)is Vector and len(value)==3,'exact_native_vector3')
 return point((value[0],value[1],value[2]))

def native_matrix(value):
 # Fixed four rows/components after exact Matrix/Vector identity and dimensions.
 from mathutils import Matrix,Vector
 need(type(value)is Matrix and len(value)==4,'exact_native_matrix4x4')
 rows=(value[0],value[1],value[2],value[3])
 need(all(type(row)is Vector and len(row)==4 for row in rows),'exact_native_matrix_rows4')
 return matrix([[row[0],row[1],row[2],row[3]]for row in rows])

def f32(value):
 need(type(value)in(int,float)and math.isfinite(float(value)),'finite_float32_input')
 raw=struct.pack('<f',float(value));out=struct.unpack('<f',raw)[0]
 need(math.isfinite(out),'finite_float32_output')
 return {'source':float(value),'expected_numeric':out,'expected_le_hex':raw.hex()}

def call(state,check,label,fn,*args,**kwargs):
 check(state,label+':before');row={'phase':label,'entered':True,'returned':False,'value':None,'primary':None}
 state['returns'].append(row)
 try:row['value']=fn(*args,**kwargs);row['returned']=True
 except BaseException as error:row['primary']=error;raise
 check(state,label+':after');return row['value']

def asset_parts(geometry):
 eye=geometry['eye_attachment_nomination'];points=eye['whole_points_m'];faces=eye['whole_original_faces'];refs=eye['whole_proxy_refs']
 need(len(points)==96 and len(refs)==96 and len(set(refs))==96 and len(faces)==86,'official_whole_eye96_faces86')
 points=[point(p)for p in points];parts={};vertices=set();face_ids=set()
 for side in ('left','right'):
  value=eye['sides'][side];ids=value['asset_vertex_indices'];need(type(ids)is list and len(ids)==48 and len(set(ids))==48 and all(type(i)is int and 0<=i<96 for i in ids),'exact_side_asset48')
  local={v:i for i,v in enumerate(ids)};selected=[]
  need([point(p)for p in value['points_m']]==[points[i]for i in ids]and value['canonical_vertex_indices']==[refs[i]for i in ids],'original_order_source_coordinates_and_proxy_refs')
  for global_face_id,indices in enumerate(faces):
   need(type(indices)is list and 3<=len(indices)<=4 and len(set(indices))==len(indices)and all(type(i)is int and 0<=i<96 for i in indices),'original_eye_face_indices')
   if any(i in local for i in indices):
    need(all(i in local for i in indices)and global_face_id not in face_ids,'no_cross_side_or_duplicate_face')
    selected.append({'global_face_id':global_face_id,'local_vertex_ids':[local[i]for i in indices],'global_asset_vertex_ids':list(indices)});face_ids.add(global_face_id)
  need([r['local_vertex_ids']for r in selected]==value['faces']and 0<len(selected)<=86,'exact_original_per_side_face_map')
  need(not vertices.intersection(ids),'disjoint_side_vertices');vertices.update(ids)
  parts[side]={'bone_name':'eye.L'if side=='left'else'eye.R','global_asset_vertex_ids':list(ids),'canonical_vertex_ids':[refs[i]for i in ids],'points_m':[list(points[i])for i in ids],'faces':selected,'binary32_expectations':[[f32(x)for x in points[i]]for i in ids]}
 need(vertices==set(range(96))and face_ids==set(range(86)),'all_original_eye_vertices_faces_assigned_once')
 return parts

def mesh_records(mesh,object_matrix,expected_vertices,expected_polygons,check,state,label):
 """Capture native polygon and native loop-triangle channels independently."""
 need(len(mesh.vertices)==expected_vertices and len(mesh.polygons)==expected_polygons,'bounded_native_original_or_evaluated_mesh_extent')
 row={'vertices':[],'polygons':[],'loop_triangles':[],'matrix_world':native_matrix(object_matrix),'native_loop_triangle_calculation_return':None,'native_loop_triangle_calculation_entered':False}
 state['mesh_records'].append(row)
 for vertex in mesh.vertices:
  if len(row['vertices'])%256==0:check(state,label+':vertex-block')
  need(type(vertex.index)is int and vertex.index==len(row['vertices']),'native_vertex_index_order')
  local=native_point(vertex.co);world=native_point(object_matrix@vertex.co);row['vertices'].append({'index':vertex.index,'local_m':list(local),'world_m':list(world)})
 for polygon in mesh.polygons:
  if len(row['polygons'])%256==0:check(state,label+':polygon-block')
  ids=list(polygon.vertices)
  need(type(polygon.index)is int and polygon.index==len(row['polygons'])and 3<=len(ids)<=4 and len(set(ids))==len(ids)and all(type(i)is int and 0<=i<expected_vertices for i in ids),'native_polygon_index_domain')
  row['polygons'].append({'index':polygon.index,'vertex_ids':ids,'loop_start':int(polygon.loop_start),'loop_total':int(polygon.loop_total)})
 # No fan triangulation assumption: actual API return and all native triangles.
 row['native_loop_triangle_calculation_entered']=True
 returned=mesh.calc_loop_triangles();row['native_loop_triangle_calculation_return']=returned
 check(state,label+':calc_loop_triangles-return')
 need(len(mesh.loop_triangles)==sum(len(p['vertex_ids'])-2 for p in row['polygons']),'whole_native_loop_triangle_extent')
 for triangle in mesh.loop_triangles:
  if len(row['loop_triangles'])%256==0:check(state,label+':triangle-block')
  ids=list(triangle.vertices);loops=list(triangle.loops);polygon=int(triangle.polygon_index)
  need(type(triangle.index)is int and triangle.index==len(row['loop_triangles'])and len(ids)==len(loops)==3 and len(set(ids))==3 and all(type(i)is int and 0<=i<expected_vertices for i in ids)and 0<=polygon<expected_polygons,'native_loop_triangle_indices')
  face=row['polygons'][polygon];need(set(ids)<=set(face['vertex_ids'])and all(type(i)is int and face['loop_start']<=i<face['loop_start']+face['loop_total']for i in loops),'native_triangle_polygon_membership')
  row['loop_triangles'].append({'index':triangle.index,'polygon_index':polygon,'vertex_ids':ids,'loop_ids':loops})
 return row

def evaluated_records(bpy,obj,expected_vertices,expected_polygons,state,check,label):
 """Retain acquisition before checks; clear before STOP; retain both failures.

Proven ownership pattern from trial.successor.evaluate_points, with new exact
polygon/loop-triangle channels. This function itself has no actual evidence yet.
"""
 depsgraph=call(state,check,label+':depsgraph',bpy.context.evaluated_depsgraph_get)
 evaluated=call(state,check,label+':evaluated',obj.evaluated_get,depsgraph)
 owner={'object':evaluated,'mesh':None,'mesh_entered':False,'mesh_ack':False,'primary':None,'clear_entered':False,'clear_ack':False,'clear_return':None,'clear_error':None,'clear_checkpoint_error':None}
 state['evaluated_owners'].append(owner);primary=None;cleanup=None;result=None
 try:
  check(state,label+':to_mesh-before');owner['mesh_entered']=True
  mesh=evaluated.to_mesh();owner['mesh']=mesh;owner['mesh_ack']=True
  state['returns'].append({'phase':label+':to_mesh','value':mesh,'returned':True})
  check(state,label+':to_mesh-return')
  result=mesh_records(mesh,evaluated.matrix_world,expected_vertices,expected_polygons,check,state,label+':evaluated-records')
 except BaseException as error:owner['primary']=primary=error
 finally:
  if owner['mesh_entered']:
   owner['clear_entered']=True
   try:
    returned=evaluated.to_mesh_clear();owner['clear_return']=returned;owner['clear_ack']=True
    state['returns'].append({'phase':label+':to_mesh_clear','value':returned,'returned':True})
   except BaseException as error:owner['clear_error']=cleanup=error
   if owner['clear_ack']:
    try:check(state,label+':to_mesh_clear-return')
    except BaseException as error:owner['clear_checkpoint_error']=cleanup=error
 if primary is not None and cleanup is not None:raise BaseExceptionGroup('neutral_eye_primary_and_cleanup',[primary,cleanup])
 if primary is not None:raise primary
 if cleanup is not None:raise cleanup
 return result

def observe_neutral_eyes(bpy,body,geometry,state,check):
 """Attach selected neutral source eyes only; never move existing mesh or rig."""
 need(type(state)is dict,'owned_neutral_state');state.update(returns=[],mesh_records=[],evaluated_owners=[],attachments=[])
 arm=body.parent;need(arm is not None and len(arm.data.bones)==163 and all(p.matrix_basis.is_identity for p in arm.pose.bones),'unchanged_all163_neutral_rig')
 parts=asset_parts(geometry);result={'schema':'avatar.neutral-eye-native.observations.v1','body_before':None,'body_evaluated':None,'eyes':{},'movement_performed':False,'anatomical_fit_accepted':False,'continuous_coverage_accepted':False,'native_roll_conversion_qualified':False,'rigid_eye_attachment_motion_qualified':False,'native_operator_IO_requested':None}
 state['result']=result
 result['body_before']=mesh_records(body.data,body.matrix_world,13380,13378,check,state,'original-body')
 result['body_evaluated']=evaluated_records(bpy,body,13380,13378,state,check,'neutral-body')
 for side in ('left','right'):
  part=parts[side];bone=arm.data.bones.get(part['bone_name']);need(bone is not None,'actual_eye_bone')
  name=body.name+'__neutral_source_eye_'+side;need(len(name.encode())<=256 and bpy.data.objects.get(name)is None and bpy.data.meshes.get(name)is None,'fresh_exact_eye_namespace')
  capture={'side':side,'source':part,'mesh':None,'object':None,'group':None,'modifier':None};state['attachments'].append(capture)
  check(state,side+':mesh-before');mesh=bpy.data.meshes.new(name);capture['mesh']=mesh;check(state,side+':mesh-return')
  returned=mesh.from_pydata(part['points_m'],[],[r['local_vertex_ids']for r in part['faces']]);capture['from_pydata_return']=returned;check(state,side+':from_pydata-return')
  returned=mesh.update();capture['mesh_update_return']=returned;check(state,side+':mesh_update-return')
  obj=bpy.data.objects.new(name,mesh);capture['object']=obj;check(state,side+':object-return')
  returned=bpy.context.scene.collection.objects.link(obj);capture['link_return']=returned;check(state,side+':link-return')
  # Same coordinate frame and parent-preserving-world pattern as existing body.
  obj.parent=arm;obj.matrix_parent_inverse=body.matrix_parent_inverse.copy();obj.matrix_world=body.matrix_world.copy()
  group=obj.vertex_groups.new(name=part['bone_name']);capture['group']=group;check(state,side+':group-return')
  returned=group.add(list(range(48)),1.0,'REPLACE');capture['weight_add_return']=returned;check(state,side+':weight-return')
  modifier=obj.modifiers.new(name='NeutralEyeArmature',type='ARMATURE');capture['modifier']=modifier;check(state,side+':modifier-return')
  modifier.object=arm;modifier.use_vertex_groups=True;modifier.use_bone_envelopes=False
  need(obj.parent is arm and modifier.object is arm and modifier.use_vertex_groups and not modifier.use_bone_envelopes,'exact_rigid_eye_armature_bind')
  original=mesh_records(mesh,obj.matrix_world,48,len(part['faces']),check,state,side+':original-eye')
  conversions=[]
  for vertex,row in zip(original['vertices'],part['binary32_expectations']):
   components=[]
   for actual,expected in zip(vertex['local_m'],row):
    actual_hex=struct.pack('<f',actual).hex();components.append(dict(expected,actual_numeric=actual,actual_le_hex=actual_hex,numeric_equal=actual==expected['expected_numeric'],encoding_equal=actual_hex==expected['expected_le_hex']))
   conversions.append(components)
  need(all(c['numeric_equal']and c['encoding_equal']for row in conversions for c in row),'exact_source_to_binary32_native_point_observation')
  need([r['vertex_ids']for r in original['polygons']]==[r['local_vertex_ids']for r in part['faces']],'exact_native_eye_face_order')
  call(state,check,side+':view-layer-update',bpy.context.view_layer.update)
  evaluated=evaluated_records(bpy,obj,48,len(part['faces']),state,check,side+':neutral-evaluated-eye')
  result['eyes'][side]={'source':part,'native_original':original,'native_evaluated':evaluated,'source_to_binary32_observations':conversions,'source_global_face_ids':[r['global_face_id']for r in part['faces']],'actual_bone_head_local_m':list(native_point(bone.head_local)),'actual_bone_tail_local_m':list(native_point(bone.tail_local)),'actual_bone_matrix_local':native_matrix(bone.matrix_local),'actual_parent_inverse':native_matrix(obj.matrix_parent_inverse),'actual_armature_world':native_matrix(arm.matrix_world),'actual_group_name':group.name,'actual_group_index':group.index,'actual_weights':[[v.index,[[g.group,g.weight]for g in v.groups]]for v in mesh.vertices],'native_neutral_evaluated_matches_original':evaluated['vertices']==original['vertices'],'native_attachment_motion_accepted':False}
 check(state,'neutral_attachment_observations_complete')
 return result

# Added prospective read-only channels. No pose assignment, evaluation driver
# mutation, frame advance, or save operation exists in these functions.
def basis_get(state,check,label,owner,attribute,optional=False):
 check(state,label+':getter-before')
 need(len(state['basis_getters'])<32768,'basis_complete_getter_roster32768_refuse_before_acquisition')
 row={'label':label,'attribute':attribute,'getter_entered':True,'getter_returned':False,'available':None,'raw_value':None,'error':None}
 state['basis_getters'].append(row)
 try:
  row['raw_value']=getattr(owner,attribute);row['getter_returned']=True;row['available']=True
 except AttributeError as error:
  row['error']=error;row['available']=False
  if not optional:raise
 except BaseException as error:row['error']=error;raise
 check(state,label+':getter-after')
 return row['raw_value']

def basis_pointer(value):
 if value is None:return None
 return {'python_type':[type(value).__module__,type(value).__qualname__],'python_identity':str(id(value)),'rna_identifier':getattr(getattr(value,'bl_rna',None),'identifier',None),'name':getattr(value,'name',None),'scope':'Pointer descriptor only; target internals are not recursively qualified.'}

def basis_rna(state,check,label,value):
 """Full bounded top-level RNA property roster; pointer internals separate."""
 properties=list(value.bl_rna.properties)
 need(len(properties)<=256,'basis_rna_property_count256_refuse_not_clip')
 need(len(state['basis_rna_records'])<8192,'basis_rna_record8192_refuse_not_clip')
 row={'owner':basis_pointer(value),'properties':[]};state['basis_rna_records'].append(row)
 for prop in properties:
  key=prop.identifier
  need(type(key)is str and len(key.encode('utf8'))<=256,'basis_rna_identifier_width')
  item={'identifier':key,'rna_type':prop.type,'is_array':bool(getattr(prop,'is_array',False)),'array_length':int(getattr(prop,'array_length',0)),'value':None}
  row['properties'].append(item)
  raw_value=basis_get(state,check,label+':'+key,value,key)
  if prop.type in ('BOOLEAN','INT','FLOAT','STRING','ENUM'):
   if item['is_array']:
    raw_items=list(raw_value)
    def array_view(value,depth=0):
     need(depth<=3,'basis_rna_array_depth3')
     if type(value)in(bool,int,float,str):return value
     values=list(value);need(len(values)<=64,'basis_rna_array_axis64');return [array_view(x,depth+1)for x in values]
    item['value']=array_view(raw_items)
    def leaves(value):return sum(leaves(x)for x in value)if type(value)is list else 1
    need(leaves(item['value'])==item['array_length'] and item['array_length']<=64,'basis_rna_complete_array64')
   elif isinstance(raw_value,set):
    item['value']=sorted(raw_value);need(all(type(x)is str for x in item['value']),'basis_rna_enum_flag_strings')
   else:item['value']=raw_value
   def primitive_leaves(value):
    if type(value)is list:
     for x in value:yield from primitive_leaves(x)
    else:yield value
   values=list(primitive_leaves(item['value']))
   need(all(type(x)in(bool,int,float,str)and(type(x)is not float or math.isfinite(x))and(type(x)is not str or len(x.encode('utf8'))<=4096)for x in values),'basis_rna_finite_supported_primitive')
  elif prop.type=='POINTER':item['value']=basis_pointer(raw_value)
  elif prop.type=='COLLECTION':
   values=list(raw_value);need(len(values)<=128,'basis_rna_complete_collection128')
   item['value']=[basis_pointer(x)for x in values]
   item['collection_scope']='Complete immediate pointer roster; collection item internals are not recursively qualified.'
  else:raise ValueError('unsupported_basis_rna_property_type:'+str(prop.type))
 return row

def basis_constraints(state,check,label,owner):
 values=list(basis_get(state,check,label+':constraints',owner,'constraints'))
 need(len(values)<=64,'basis_constraint64_refuse_not_clip')
 return [basis_rna(state,check,label+':constraint:'+str(i),value)for i,value in enumerate(values)]

def basis_drivers(state,check,label,owner):
 animation=basis_get(state,check,label+':animation_data',owner,'animation_data')
 if animation is None:return {'animation_data':None,'drivers':[]}
 drivers=list(basis_get(state,check,label+':drivers',animation,'drivers'))
 need(len(drivers)<=512,'basis_driver512_refuse_not_clip');result={'animation_data':basis_pointer(animation),'drivers':[]}
 for i,curve in enumerate(drivers):
  key=label+':driver:'+str(i);row={'fcurve':basis_rna(state,check,key,curve),'driver':None,'variables':[]}
  result['drivers'].append(row)
  driver=basis_get(state,check,key+':driver',curve,'driver');row['driver']=basis_rna(state,check,key+':driver',driver)
  variables=list(basis_get(state,check,key+':variables',driver,'variables'));need(len(variables)<=128,'basis_driver_variables128_refuse')
  for j,variable in enumerate(variables):
   targets=list(basis_get(state,check,key+':variable:'+str(j)+':targets',variable,'targets'));need(len(targets)<=8,'basis_driver_targets8_refuse')
   row['variables'].append({'properties':basis_rna(state,check,key+':variable:'+str(j),variable),'targets':[basis_rna(state,check,key+':target:'+str(j)+':'+str(k),target)for k,target in enumerate(targets)]})
 return result

def basis_modifiers(state,check,label,obj):
 values=list(basis_get(state,check,label+':modifiers',obj,'modifiers'))
 need(len(values)<=64,'basis_modifier64_refuse_not_clip')
 return values

def basis_object(state,check,label,obj):
 return {'object':basis_pointer(obj),'parent':basis_pointer(basis_get(state,check,label+':parent',obj,'parent')),'parent_type':basis_get(state,check,label+':parent_type',obj,'parent_type'),'parent_bone':basis_get(state,check,label+':parent_bone',obj,'parent_bone'),'matrix_world':native_matrix(basis_get(state,check,label+':matrix_world',obj,'matrix_world')),'matrix_local':native_matrix(basis_get(state,check,label+':matrix_local',obj,'matrix_local')),'matrix_basis':native_matrix(basis_get(state,check,label+':matrix_basis',obj,'matrix_basis')),'matrix_parent_inverse':native_matrix(basis_get(state,check,label+':matrix_parent_inverse',obj,'matrix_parent_inverse')),'constraints':basis_constraints(state,check,label,obj),'modifiers':[basis_rna(state,check,label+':modifier:'+str(i),modifier)for i,modifier in enumerate(basis_modifiers(state,check,label,obj))],'drivers':basis_drivers(state,check,label,obj),'data_drivers':basis_drivers(state,check,label+':data',obj.data)}

def basis_armature(state,check,label,arm,body):
 bones=list(basis_get(state,check,label+':bones',arm.data,'bones'));poses=list(basis_get(state,check,label+':pose-bones',arm.pose,'bones'))
 need(len(bones)==len(poses)==163 and len({b.name for b in bones})==163 and {b.name for b in bones}=={p.name for p in poses},'basis_all163_complete_original_or_evaluated_roster')
 result={'armature':basis_object(state,check,label+':armature',arm),'body':basis_object(state,check,label+':body',body),'bones':[],'selected_hierarchy':{},'data_channels_scope':'Actual armature-local native properties; no source/API/roll equivalence inferred.'}
 state['basis_armatures'].append(result)
 parents={b.name:None if b.parent is None else b.parent.name for b in bones}
 need(all(x is None or x in parents for x in parents.values()),'basis_parent_closure')
 for root in state['basis_selected_roots']:
  need(root in parents,'actual_selected_control_exists')
  descendants=[]
  for name in parents:
   seen=set();cursor=name
   while cursor is not None:
    need(cursor not in seen,'basis_acyclic_parent_roster');seen.add(cursor)
    if cursor==root:descendants.append(name);break
    cursor=parents[cursor]
  chain=[];cursor=parents[root]
  while cursor is not None:
   need(cursor not in chain,'basis_acyclic_ancestor_chain');chain.append(cursor);cursor=parents[cursor]
  result['selected_hierarchy'][root]={'ancestors_parent_first':chain,'descendants_including_self':descendants,'movement_accepted':False,'chest_only_isolation_accepted':False}
 for bone in bones:
  key=label+':bone:'+bone.name;pose=arm.pose.bones[bone.name]
  channel=basis_get(state,check,key+':matrix_channel',pose,'matrix_channel',True)
  row={'name':bone.name,'parent':parents[bone.name],'head_local_m':list(native_point(basis_get(state,check,key+':head_local',bone,'head_local'))),'tail_local_m':list(native_point(basis_get(state,check,key+':tail_local',bone,'tail_local'))),'matrix_local':native_matrix(basis_get(state,check,key+':matrix_local',bone,'matrix_local')),'pose_matrix':native_matrix(basis_get(state,check,key+':pose_matrix',pose,'matrix')),'pose_matrix_basis':native_matrix(basis_get(state,check,key+':matrix_basis',pose,'matrix_basis')),'pose_matrix_channel':None if channel is None else native_matrix(channel),'pose_matrix_channel_available':channel is not None,'pose_head_native':list(native_point(basis_get(state,check,key+':pose_head',pose,'head'))),'pose_tail_native':list(native_point(basis_get(state,check,key+':pose_tail',pose,'tail'))),'data_metadata':{k:basis_get(state,check,key+':'+k,bone,k)for k in ('use_deform','use_connect','inherit_scale','use_inherit_rotation','use_local_location','use_relative_parent')},'pose_transform_metadata':{k:list(basis_get(state,check,key+':'+k,pose,k))if k in ('location','scale','rotation_euler','rotation_quaternion','rotation_axis_angle','lock_location','lock_rotation','lock_scale')else basis_get(state,check,key+':'+k,pose,k)for k in ('rotation_mode','location','scale','rotation_euler','rotation_quaternion','rotation_axis_angle','lock_location','lock_rotation','lock_rotation_w','lock_rotations_4d','lock_scale')},'constraints':basis_constraints(state,check,key,pose),'API_axis_or_storage_equivalence_qualified':False}
  result['bones'].append(row)
 return result

def basis_snapshot(bpy,body,state,check,label):
 arm=body.parent;need(arm is not None,'basis_actual_body_parent')
 original=basis_armature(state,check,label+':original',arm,body)
 depsgraph=call(state,check,label+':depsgraph',bpy.context.evaluated_depsgraph_get)
 evaluated_arm=call(state,check,label+':evaluated-armature',arm.evaluated_get,depsgraph)
 evaluated_body=call(state,check,label+':evaluated-body',body.evaluated_get,depsgraph)
 evaluated=basis_armature(state,check,label+':evaluated',evaluated_arm,evaluated_body)
 return {'original':original,'evaluated':evaluated,'evaluated_pointer_lifetime_scope':'Read-only observations retained; no temporary mesh was acquired by the basis snapshot.'}

def observe(bpy,body,geometry,state,check):
 """Neutral basis observation around the unchanged eye/mesh observation."""
 need(type(state)is dict,'owned_basis_state')
 need(type(state.get('basis_selected_roots'))is list and len(state['basis_selected_roots'])==5 and len(set(state['basis_selected_roots']))==5 and all(type(x)is str for x in state['basis_selected_roots']),'authenticated_five_control_names_required')
 state.update(returns=[],basis_getters=[],basis_rna_records=[],basis_armatures=[])
 result={'schema':'avatar243.neutral-native-basis.observations.v1','before':None,'neutral_eye_observations':None,'final':None,'matrix_channels_compared_or_accepted':False,'native_axis_or_roll_equivalence_qualified':False,'motion_performed':False,'anatomical_rims_qualified':False,'coverage_qualified':False,'chest_isolation_qualified':False,'saved_derivative_export':None}
 state['basis_result']=result
 result['before']=basis_snapshot(bpy,body,state,check,'basis-before')
 eye_state={};state['neutral_eye_child_state']=eye_state
 result['neutral_eye_observations']=observe_neutral_eyes(bpy,body,geometry,eye_state,check)
 result['final']=basis_snapshot(bpy,body,state,check,'basis-final')
 check(state,'basis_complete_pending_external_review')
 return result
