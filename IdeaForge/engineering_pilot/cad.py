"""Deterministic solid geometry; engineering units are SI, CAD exports mm."""
import hashlib
import json
from .mesh_verify import parameter_hash, verify


def export(p, directory):
    import cadquery as cq
    from .schema import masses
    directory.mkdir(parents=True, exist_ok=False)
    parts, bom, verification = [], [], []
    input_hash = parameter_hash(p)
    settings = {'linear_tolerance_mm':0.01, 'angular_tolerance_rad':0.1}
    x = 0.0
    for i, mass in zip((1, 2), masses(p)):
        length = p[f'length_{i}_m'] * 1000
        part = cq.Workplane('XY').box(length, p['width_m']*1000, p['thickness_m']*1000,
                                    centered=(False, True, True)).translate((x, 0, 0))
        if len(part.solids().vals()) != 1 or not part.val().isValid():
            raise ValueError('Invalid CAD solid')
        filename = f'link_{i}.stl'
        cq.exporters.export(part, str(directory / filename), tolerance=settings['linear_tolerance_mm'],
                            angularTolerance=settings['angular_tolerance_rad'])
        box=part.val().BoundingBox()
        manifest={'part_id':f'link_{i}', 'unit':'mm', 'parameter_sha256':input_hash,
                  'file_sha256':hashlib.sha256((directory/filename).read_bytes()).hexdigest(),
                  'bounds_mm':[[box.xmin,box.ymin,box.zmin],[box.xmax,box.ymax,box.zmax]],
                  'volume_mm3':part.val().Volume(),'export_settings':settings}
        manifest_bytes=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode('utf-8')
        manifest_path=directory/(filename+'.manifest.json')
        manifest_path.write_bytes(manifest_bytes)
        saved_manifest=manifest_path.read_bytes()
        if saved_manifest!=manifest_bytes:
            checked={'status':'failed','part_id':manifest['part_id'],'reason':'Manifest changed before validation'}
        else:
            checked=verify(directory/filename,json.loads(saved_manifest))
        checked['manifest_sha256']=hashlib.sha256(manifest_bytes).hexdigest()
        checked['exported_sha256']=manifest['file_sha256']
        verification.append(checked)
        parts.append(part.val())
        bom.append({'part': f'link_{i}', 'quantity': 1, 'mass_kg': mass,
                    'geometry': 'uniform rectangular idealization; no bores or servo geometry',
                    'volume_mm3': part.val().Volume(), 'stl': filename})
        x += length
    cq.exporters.export(cq.Compound.makeCompound(parts), str(directory / 'assembly.step'))
    files = {path.name: {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
             for path in sorted(directory.iterdir())}
    # Fail if an output changed after validation before the final file inventory.
    for result in verification:
        name=result['part_id']+'.stl'
        if result['exported_sha256']!=files.get(name,{}).get('sha256'):
            result.update(status='failed',reason='Artifact changed after geometry validation')
        if result.get('manifest_sha256')!=files.get(name+'.manifest.json',{}).get('sha256'):
            result.update(status='failed',reason='Manifest changed after geometry validation')
    # STEP serialization metadata can vary; input hash is the reproducibility identity.
    states=[result['status'] for result in verification]
    status='failed' if 'failed' in states else 'passed' if all(state=='passed' for state in states) else 'unknown'
    return {'status': status, 'export_verification':verification, 'parameter_sha256':input_hash, 'cad_unit': 'mm', 'stl_unit_required_on_import': 'mm', 'bom': bom,
            'files': files, 'mating_frames_mm': [[0,0,0], [p['length_1_m']*1000,0,0], [x,0,0]],
            'excluded_hardware': ['two servos', 'bearings', 'pins', 'fasteners', 'base', 'payload fixture'],
            'manufacturing_readiness': 'unknown: joint hardware, strength, tolerances and fit not modeled'}
