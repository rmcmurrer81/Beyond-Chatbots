"""Only explicit scene dimensions become geometry; papers remain evidence, not CAD."""
from __future__ import annotations
import json
from pathlib import Path
from .model import digest, load, validate


def read_json(path, default=None):
    path = Path(path)
    if not path.exists(): return default
    if path.stat().st_size > 2_000_000: raise ValueError(f'{path.name} exceeds the local input limit.')
    return json.loads(path.read_text(encoding='utf-8'))


def gather(root):
    root = Path(root)
    from .store import Store
    store = Store(root)
    latest = store.revision()
    explicit = root/'workspace3d'/'assembly.json'
    project_explicit = root/'design'/'assembly.json'
    input_revision = store.pointer('input')
    if input_revision:
        scene = store.revision(input_revision)['scene']
    elif explicit.exists() or project_explicit.exists():
        scene = load(explicit if explicit.exists() else project_explicit)
    elif latest and latest['scene']['parts']:
        scene = latest['scene']
    else:
        project = read_json(root/'project.json',{}) or {}
        body = read_json(root/'canonical_design'/'current_body.json',{}) or {}
        subsystems = list(body.get('subsystems',{})) or project.get('plan',{}).get('subsystems',[])
        scene = {'schema_version':1,'units':'mm','title':str(project.get('name','Humanoid assembly' if body else 'Project assembly')),
                 'parts':[], 'unknowns':['No explicit part geometry supplied. Import an assembly or add measured parts.']+
                 [f'{str(name)[:120]}: geometry, mounts and physical parameters unresolved.' for name in subsystems[:40]]}
    sources = []
    for relative in ('research/research.json','research/discoveries.json','design/virtual_concepts.json',
                     'candidate_updates/extracted_specs.json','canonical_design/current_body.json'):
        value = read_json(root/relative)
        if value is not None:
            source={'document':relative,'sha256':digest(value),'verification':'Discovery metadata only; source claims not independently validated.'}
            if isinstance(value,dict):
                records=(value.get('papers') or value.get('web') or [])[:8]
                source['references']=[{'title':str(item.get('title',''))[:200],
                                       'url':str(item.get('url') or item.get('href') or '')[:1000]}
                                      for item in records if isinstance(item,dict)]
            sources.append(source)
    # Stable local report content identifies fresh Humanoid scans without scraping or new network calls.
    report = root/'research_library'/'LATEST.md'
    if report.exists() and report.stat().st_size <= 2_000_000:
        sources.append({'document':'research_library/LATEST.md','sha256':digest(report.read_text(encoding='utf-8'))})
    from .requirements import manifest
    project = read_json(root/'project.json',{}) or {}
    if scene.get('requirements',{}).get('origin') != 'user_authored':
        scene['requirements'] = manifest(project)
    return {'scene':validate(scene),'sources':sources,
            'reason':'Local geometry/evidence refreshed. Dimensions are not inferred from research; geometric screening only.',
            'base_revision':latest['id'] if latest else None}
