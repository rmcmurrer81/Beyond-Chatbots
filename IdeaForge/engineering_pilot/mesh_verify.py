"""Read-only STL verification for the pilot's explicitly reviewed cuboids.

No repair, guessing units, tolerant vertex merging, or structural-safety claim.
The caller's subprocess time budget bounds this work; byte/triangle caps bound
input allocation. Exact duplicate vertices are indexed only for topology.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import struct

MAX_BYTES = 8_000_000
MAX_TRIANGLES = 100_000
TOLERANCE_MM = 0.0001
RELATIVE_TOLERANCE = 0.00001


def parameter_hash(parameters):
    return hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_triangles(raw):
    import numpy as np
    if len(raw) > MAX_BYTES: raise ValueError('STL byte budget exceeded')
    if len(raw) >= 84:
        count = struct.unpack('<I', raw[80:84])[0]
        if len(raw) == 84 + 50 * count:
            if not 0 < count <= MAX_TRIANGLES: raise ValueError('Invalid or excessive triangle count')
            dtype = np.dtype([('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attribute', '<u2')])
            records = np.frombuffer(raw, dtype=dtype, count=count, offset=84)
            if not np.isfinite(records['normal']).all(): raise ValueError('Nonfinite STL normals')
            return records['vertices'].astype(float), 'binary'
    # Strict ASCII grammar; malformed binary files are not accepted by a forgiving loader.
    try: lines = [line.strip() for line in raw.decode('ascii').splitlines() if line.strip()]
    except UnicodeDecodeError as error: raise ValueError('Malformed binary STL') from error
    if len(lines) < 9 or not re.fullmatch(r'solid(?:\s.*)?',lines[0]) or not re.fullmatch(r'endsolid(?:\s.*)?',lines[-1]):
        raise ValueError('Malformed STL header or byte count')
    middle = lines[1:-1]
    if len(middle) % 7 or not 0 < len(middle)//7 <= MAX_TRIANGLES: raise ValueError('Malformed ASCII STL facets')
    triangles=[]
    for index in range(0, len(middle), 7):
        facet=middle[index:index+7]
        if not facet[0].startswith('facet normal ') or facet[1] != 'outer loop' or facet[5:] != ['endloop','endfacet']:
            raise ValueError('Malformed ASCII STL facet')
        normal=facet[0].split()[2:]
        if len(normal)!=3 or not all(math.isfinite(float(x)) for x in normal): raise ValueError('Invalid STL normal')
        vertices=[]
        for line in facet[2:5]:
            pieces=line.split()
            if len(pieces)!=4 or pieces[0]!='vertex': raise ValueError('Malformed STL vertex')
            vertices.append([float(x) for x in pieces[1:]])
        triangles.append(vertices)
    return np.asarray(triangles, dtype=float), 'ascii'


def inspect_stl(path):
    """Strict raw geometry inspection shared by the pilot and fabrication helper."""
    import numpy as np
    import trimesh
    path=Path(path)
    if path.is_symlink(): raise ValueError('STL must not be a symlink')
    with path.open('rb') as stream: raw=stream.read(MAX_BYTES+1)
    triangles, encoding=read_triangles(raw)
    if not np.isfinite(triangles).all(): raise ValueError('Nonfinite STL coordinates')
    if (np.abs(triangles)>1e6).any(): raise ValueError('Coordinates exceed bounded pilot range')
    # Coordinate-preserving indexing only: no triangulation deletion or geometry repair.
    vertices,inverse=np.unique(triangles.reshape((-1,3)),axis=0,return_inverse=True)
    faces=inverse.reshape((-1,3))
    if len(np.unique(np.sort(faces,axis=1),axis=0))!=len(faces): raise ValueError('Duplicate STL triangles')
    mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=False,validate=False)
    if (mesh.area_faces<=1e-12).any(): raise ValueError('Degenerate STL triangles')
    # A graph of exact vertices must form one connected body.
    parents=list(range(len(vertices)))
    def find(x):
        while parents[x]!=x:
            parents[x]=parents[parents[x]];x=parents[x]
        return x
    for a,b,c in faces:
        root=find(int(a));parents[find(int(b))]=root;parents[find(int(c))]=root
    connected_bodies=len({find(i) for i in range(len(vertices))})
    result={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'triangles':len(faces),
            'encoding':encoding,'connected_bodies':connected_bodies,'watertight':bool(mesh.is_watertight),
            'winding_consistent':bool(mesh.is_winding_consistent),'positive_volume':bool(mesh.is_volume),
            'bounds_coordinates':mesh.bounds.tolist(),'extents':mesh.extents.tolist(),
            'volume':float(mesh.volume),'area':float(mesh.area)}
    return result,triangles


def verify(path, manifest):
    """Return passed/failed/unknown; validation never changes artifact bytes."""
    import numpy as np
    path=Path(path)
    base={'status':'unknown','part_id':manifest.get('part_id') if isinstance(manifest,dict) else None,
          'meaning':'Export matches reviewed cuboid model only; manufacturing and physical safety unknown.'}
    try:
        required={'part_id','unit','parameter_sha256','file_sha256','bounds_mm','volume_mm3','export_settings'}
        if not isinstance(manifest,dict) or set(manifest)!=required or manifest['unit']!='mm':
            raise ValueError('Exact millimetre export manifest required')
        if not isinstance(manifest['part_id'],str) or not re.fullmatch(r'link_[12]',manifest['part_id']):
            raise ValueError('Unknown pilot part ID')
        if path.name!=manifest['part_id']+'.stl': raise ValueError('Part ID does not match artifact filename')
        for field in ('parameter_sha256','file_sha256'):
            if not isinstance(manifest[field],str) or not re.fullmatch('[0-9a-f]{64}',manifest[field]):
                raise ValueError('Invalid manifest hash')
        raw_bounds=manifest['bounds_mm']
        if not isinstance(raw_bounds,list) or len(raw_bounds)!=2 or any(
                not isinstance(row,list) or len(row)!=3 or any(type(x) not in (int,float) for x in row) for row in raw_bounds):
            raise ValueError('Numeric bounds without booleans required')
        bounds=np.asarray(raw_bounds,dtype=float)
        if bounds.shape!=(2,3) or not np.isfinite(bounds).all() or not (bounds[1]>bounds[0]).all():
            raise ValueError('Invalid expected bounds')
        volume=manifest['volume_mm3']
        if type(volume) not in (int,float) or not math.isfinite(volume) or volume<=0: raise ValueError('Invalid expected volume')
        if not np.isclose(np.prod(bounds[1]-bounds[0]),volume,rtol=RELATIVE_TOLERANCE):
            raise ValueError('Manifest cuboid bounds and volume disagree')
        settings=manifest['export_settings']
        if not isinstance(settings,dict) or set(settings)!={'linear_tolerance_mm','angular_tolerance_rad'} or any(
                type(x) not in (int,float) or not math.isfinite(x) or x<=0 for x in settings.values()):
            raise ValueError('Explicit finite export settings required')
        details,triangles=inspect_stl(path)
        base.update(details,unit='mm',parameter_sha256=manifest['parameter_sha256'],export_settings=manifest['export_settings'])
        if details['sha256']!=manifest['file_sha256']: raise ValueError('Artifact hash differs from exported file')
        failures=[]
        if details['connected_bodies']!=1:failures.append('multiple disconnected STL bodies')
        if not all(details[k] for k in ('watertight','winding_consistent','positive_volume')):failures.append('invalid closed oriented volume')
        if not np.allclose(details['bounds_coordinates'],bounds,rtol=0,atol=TOLERANCE_MM):failures.append('wrong dimensions or assembly placement')
        if not np.isclose(details['volume'],volume,rtol=RELATIVE_TOLERANCE,atol=TOLERANCE_MM):failures.append('wrong volume')
        extent=bounds[1]-bounds[0]
        area=2*(extent[0]*extent[1]+extent[1]*extent[2]+extent[0]*extent[2])
        if not np.isclose(details['area'],area,rtol=RELATIVE_TOLERANCE,atol=TOLERANCE_MM):failures.append('wrong boundary area')
        # Every facet must lie on one of the six reviewed cuboid planes.
        boundary=np.zeros(len(triangles),dtype=bool)
        for axis in range(3):
            for side in range(2):
                boundary |= np.all(np.isclose(triangles[:,:,axis],bounds[side,axis],rtol=0,atol=TOLERANCE_MM),axis=1)
        if not boundary.all():failures.append('facet outside reviewed cuboid boundary')
        # Detect mutation while the file was being inspected; never repair it.
        with path.open('rb') as stream: current=stream.read(MAX_BYTES+1)
        if hashlib.sha256(current).hexdigest()!=details['sha256']:failures.append('artifact changed during validation')
        base.update(status='failed' if failures else 'passed',failures=failures,
                    tolerance_mm=TOLERANCE_MM,relative_tolerance=RELATIVE_TOLERANCE)
    except (ImportError,OSError) as error:
        base.update(status='unknown',reason=str(error))
    except (ValueError,TypeError,OverflowError) as error:
        base.update(status='failed',reason=str(error))
    return base
