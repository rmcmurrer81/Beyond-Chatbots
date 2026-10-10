"""Deterministic, bounded geometric screening. No dynamics or structural solver."""
from __future__ import annotations
from itertools import combinations
import time
from .model import bounds, digest, validate, world_vertices
from fabrication.printer_fit import scene_receipts


def run_checks(scene, *, project_root=None, inventory=None):
    deadline = time.monotonic()+3.0
    scene = validate(scene)
    geometry = world_vertices(scene)
    boxes = {key:bounds(value[0]) for key,value in geometry.items()}
    overlap = []
    for a,b in combinations(boxes, 2):
        amin,amax = boxes[a]; bmin,bmax = boxes[b]
        if all(min(amax[i],bmax[i])-max(amin[i],bmin[i]) > 1e-6 for i in range(3)):
            overlap.append([a,b])
    fit = scene_receipts(scene, project_root, inventory=inventory)
    for result in fit:
        # Legacy field is never a nominal-volume success; see the bound receipt.
        result["axis_aligned_fit"] = None
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
                          'Printer fit uses only the project-selected reviewed profile and explicit orthogonal bounding-box placement; legacy printer_volume_mm is not reviewed evidence.',
                          'Joint sweeps are kinematic previews, not physics or actuator validation.',
                          'Dynamics unavailable in this workspace: verified mass, inertia, collision geometry and solver integration are required.',
                          'No structural, thermal, control, human-safety or manufacturability certification.']}
