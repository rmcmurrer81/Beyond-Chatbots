"""Expose user-authored goals/questions to existing research planners, not executable code."""
from __future__ import annotations
import json
from pathlib import Path
from .store import Store


def requirements_context(root, limit=8000):
    path=Path(root)/'workspace3d'/'history.sqlite3'
    if not path.exists(): return ''
    revision=Store(root).revision()
    if not revision: return ''
    requirements=revision['scene'].get('requirements',{})
    return json.dumps(requirements,ensure_ascii=False)[:limit]
