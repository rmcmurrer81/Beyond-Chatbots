"""Read-only discovery for the current KiraLabs local research catalog.

Registration is not permission to execute an app or read its project records.
Aster never impersonates the two existing grant recipients.
"""
import math
import os
from pathlib import Path
import sqlite3
import time
from .platform import linklike

APP_IDS = {'ideaforge', 'humanoid-researcher'}


def catalog_path():
    base = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'KiraLabs' / 'research-exchange-v1' / 'catalog.sqlite3'


def discover(path=None):
    path = Path(path) if path is not None else catalog_path()
    result = {'status': 'not_found', 'apps': [], 'research_access': 'unavailable_no_aster_grant',
              'commands': 'unavailable_no_command_adapter'}
    if any(linklike(p) for p in [path, *path.parents]):
        raise ValueError('Symlink catalog paths are forbidden')
    if not path.is_file(): return result
    if path.stat().st_size > 16 * 1024 * 1024: raise ValueError('Catalog exceeds discovery limit')
    db = None
    try:
        # ro prevents creating/mutating this other app's catalog.
        db = sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True, timeout=1)
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: 1, 10000)
        rows = db.execute('SELECT app, root, seen FROM apps LIMIT 20').fetchall()
        for app, root, seen in rows:
            if app not in APP_IDS or type(root) is not str or len(root) > 4096 or not Path(root).is_absolute(): continue
            if type(seen) not in (float, int) or not math.isfinite(seen): continue
            age = time.time() - seen
            if not 0 <= age <= 30 * 86400: continue
            result['apps'].append({'id': app, 'registered_root': root,
                'status': 'registered_only_not_running_verified', 'commands': []})
        result['status'] = 'available'
    except sqlite3.Error:
        result['status'] = 'unavailable_or_incompatible'
    finally:
        if db: db.close()
    return result
