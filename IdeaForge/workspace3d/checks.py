"""Deterministic, bounded geometric screening. No dynamics or structural solver."""
from __future__ import annotations
from itertools import combinations
import time
from .model import bounds, digest, validate, vector, world_vertices


def run_checks(scene):
    deadline = time.monotonic()+3.0
    scene = validate(scene)
    geometry = world_vertices(scene)
    boxes = {key:bounds(value[0]) for key,value in geometry.items()}
    overlap = []
    for a,b in combinations(boxes, 2):
        amin,amax = boxes[a]; bmin,bmax = boxes[b]
        if all(min(amax[i],bmax[i])-max(amin[i],bmin[i]) > 1e-6 for i in range(3)):
            overlap.append([a,b])
    fit = []
    volume = scene.get('printer_volume_mm')
    if volume is not None and not vector(volume, True):
        raise ValueError('printer_volume_mm must contain three positive dimensions.')
    for part in scene['parts']:
        fit.append({'part':part['id'], 'axis_aligned_fit':
                    all(part['size_mm'][i] <= volume[i] for i in range(3)) if volume else None})
    sweeps = []
    for part in scene['parts']:
        if not part.get('joint'): continue
        joint = part['joint']; samples = []
        for step in range(9):
            if time.monotonic()>deadline:
                raise TimeoutError("Geometric sweep exceeded the three-second budget; simplify the assembly. No completed test is recorded.")
            angle = joint['min_deg']+(joint['max_deg']-joint['min_deg'])*step/8
            points = [v for vertices,_ in world_vertices(scene,{part['id']:angle}).values() for v in vertices]
            samples.append({'angle_deg':angle,'assembly_bounds_mm':bounds(points)})
        sweeps.append({'part':part['id'],'samples':samples})
    return {'scene_hash':digest(scene), 'status':'screened' if geometry else 'missing_geometry',
            'part_count':len(geometry), 'possible_aabb_overlaps':overlap,
            'printer_fit':fit, 'joint_sweeps':sweeps,
            'limitations':['Bounding-box overlap is approximate, not a collision/clearance verdict.',
                          'Printer fit assumes the declared part axes and excludes supports and tolerances.',
                          'Joint sweeps are kinematic previews, not physics or actuator validation.',
                          'Dynamics unavailable in this workspace: verified mass, inertia, collision geometry and solver integration are required.',
                          'No structural, thermal, control, human-safety or manufacturability certification.']}
