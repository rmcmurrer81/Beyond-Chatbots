"""Strict, bounded millimetre scene format and dependency-free 3D transforms."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re

MAX_PARTS = 80
MAX_BYTES = 512_000


def number(value, limit=1_000_000):
    return type(value) in (float, int) and math.isfinite(value) and abs(value) <= limit


def vector(value, positive=False):
    return (isinstance(value, list) and len(value) == 3 and
            all(number(x) and (not positive or x > 0) for x in value))


def validate(scene):
    if not isinstance(scene, dict) or type(scene.get('schema_version')) is not int or scene.get('schema_version') != 1 or scene.get('units') != 'mm':
        raise ValueError('Expected schema_version 1 and explicit units mm.')
    if len(json.dumps(scene, allow_nan=False)) > MAX_BYTES:
        raise ValueError('Scene exceeds the bounded workspace size.')
    parts = scene.get('parts')
    if not isinstance(parts, list) or len(parts) > MAX_PARTS:
        raise ValueError(f'parts must contain at most {MAX_PARTS} items.')
    if not isinstance(scene.get('unknowns', []), list) or not all(isinstance(x, str) for x in scene.get('unknowns', [])):
        raise ValueError('unknowns must be a list of descriptions.')
    if not isinstance(scene.get('title','Assembly'), str):
        raise ValueError('Scene title must be text.')
    if scene.get('printer_volume_mm') is not None and not vector(scene['printer_volume_mm'], True):
        raise ValueError('printer_volume_mm must contain three positive dimensions.')
    if sum(p.get('joint') is not None for p in parts if isinstance(p,dict)) > 8:
        raise ValueError('This bounded preview supports at most eight joints.')
    if 'requirements' in scene:
        from .requirements import validate_manifest
        validate_manifest(scene['requirements'])
    ids = set()
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError('Each part must be an object.')
        pid = part.get('id')
        if not isinstance(pid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', pid) or pid in ids:
            raise ValueError('Part IDs must be unique alphanumeric identifiers.')
        ids.add(pid)
        if part.get('shape') not in ('box', 'cylinder') or not vector(part.get('size_mm'), True):
            raise ValueError(f'{pid}: box/cylinder requires three positive size_mm dimensions.')
        if part['shape'] == 'cylinder' and part['size_mm'][0] != part['size_mm'][1]:
            raise ValueError(f'{pid}: cylinder X/Y diameters must match.')
        if not vector(part.get('position_mm')) or not vector(part.get('rotation_deg')):
            raise ValueError(f'{pid}: explicit position_mm and rotation_deg are required.')
        provenance = part.get('provenance')
        if not isinstance(provenance, dict) or provenance.get('status') not in ('user_supplied', 'source_reported', 'example', 'derived') or not isinstance(provenance.get('source'), str) or not provenance['source'].strip():
            raise ValueError(f'{pid}: explicit provenance status and source are required.')
        joint = part.get('joint')
        if joint is not None:
            if not isinstance(joint, dict) or joint.get('axis') not in ('x', 'y', 'z') or not all(number(joint.get(k), 360) for k in ('min_deg', 'max_deg', 'angle_deg')):
                raise ValueError(f'{pid}: joint needs an axis and bounded angles.')
            if not joint['min_deg'] <= joint['angle_deg'] <= joint['max_deg']:
                raise ValueError(f'{pid}: joint angle is outside its declared limits.')
    by_id = {p['id']: p for p in parts}
    for part in parts:
        seen = {part['id']}
        parent = part.get('parent')
        while parent is not None:
            if not isinstance(parent, str) or parent not in by_id or parent in seen:
                raise ValueError('Part parent is missing or the assembly contains a cycle.')
            seen.add(parent)
            if len(seen) > 8: raise ValueError('Assembly hierarchy exceeds eight levels.')
            parent = by_id[parent].get('parent')
    return copy.deepcopy(scene)


def load(path):
    from pathlib import Path
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Assembly file exceeds size limit.')
    return validate(json.loads(path.read_text(encoding='utf-8')))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def rotate(point, degrees):
    x, y, z = point
    for axis, angle in enumerate(degrees):
        c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        if axis == 0: y, z = c*y-s*z, s*y+c*z
        elif axis == 1: x, z = c*x+s*z, -s*x+c*z
        else: x, y = c*x-s*y, s*x+c*y
    return x, y, z


def geometry(part):
    x, y, z = [v/2 for v in part['size_mm']]
    if part['shape'] == 'box':
        vertices = [(a*x, b*y, c*z) for a, b, c in
                    [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
        edges = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    else:
        vertices = [(x*math.cos(i*math.pi/12), y*math.sin(i*math.pi/12), h) for h in (-z,z) for i in range(24)]
        edges = [(j+i,j+(i+1)%24) for j in (0,24) for i in range(24)] + [(i,i+24) for i in range(0,24,3)]
    return vertices, edges


def world_vertices(scene, overrides=None):
    parts = {p['id']: p for p in scene['parts']}
    frames = {}
    def apply(vector, axes):
        return tuple(sum(vector[j]*axes[j][i] for j in range(3)) for i in range(3))
    def frame(part):
        if part['id'] in frames: return frames[part['id']]
        angles=[0.,0.,0.]
        joint=part.get('joint')
        if joint: angles['xyz'.index(joint['axis'])]=(overrides or {}).get(part['id'],joint['angle_deg'])
        axes=[rotate(rotate(unit,angles),part['rotation_deg']) for unit in ((1,0,0),(0,1,0),(0,0,1))]
        origin=tuple(part['position_mm'])
        if part.get('parent'):
            parent_origin,parent_axes=frame(parts[part['parent']])
            origin=tuple(a+b for a,b in zip(parent_origin,apply(origin,parent_axes)))
            axes=[apply(axis,parent_axes) for axis in axes]
        frames[part['id']]=(origin,axes)
        return origin,axes
    result={}
    for part in scene['parts']:
        origin,axes=frame(part); vertices,edges=geometry(part)
        result[part['id']]=([tuple(a+b for a,b in zip(origin,apply(v,axes))) for v in vertices],edges)
    return result


def bounds(vertices):
    return tuple(min(v[i] for v in vertices) for i in range(3)), tuple(max(v[i] for v in vertices) for i in range(3))


def demo():
    def part(pid, shape, size, pos, parent=None, joint=None):
        result = {'id':pid, 'shape':shape, 'size_mm':size, 'position_mm':pos,
                  'rotation_deg':[0,0,0], 'provenance':{'status':'example','source':'Built-in illustrative dimensions; not a project design.'}}
        if parent: result['parent'] = parent
        if joint: result['joint'] = joint
        return result
    return {'schema_version':1,'units':'mm','title':'EXAMPLE: three-part mechanism',
            'unknowns':['Example only. No masses, actuators, tolerances or physical validation.'],
            'parts':[part('base','box',[120,80,20],[0,0,10]),
                     part('bearing','cylinder',[40,40,25],[0,0,22.5],'base'),
                     part('arm','box',[140,20,12],[0,0,18.5],'bearing',{'axis':'z','min_deg':-90,'max_deg':90,'angle_deg':0})]}
