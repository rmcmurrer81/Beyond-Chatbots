"""Explicit local selection only; no ambient environment/cwd/global lookup."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from .contract import (InvalidRequest, ProviderSelection, SELECTION_PROTOCOL,
                       StaleSelection, canonical_json)

MAX_CONFIG_BYTES = 8192


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidRequest('Duplicate provider selection key')
        result[key] = value
    return result


def _read(path, project_id):
    path = Path(path)
    if path.is_symlink():
        raise InvalidRequest('Provider selection cannot be a symlink')
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise InvalidRequest('Provider selection must be a regular file')
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InvalidRequest('Provider selection could not be read') from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise InvalidRequest('Provider selection exceeds its byte limit')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InvalidRequest('Provider selection is not valid JSON') from exc
    keys = {'protocol', 'provider', 'app_id', 'revision'}
    if type(value) is not dict or set(value) != keys or value['protocol'] != SELECTION_PROTOCOL:
        raise InvalidRequest('Unsupported provider selection schema')
    return ProviderSelection(value['provider'], value['app_id'], project_id,
                             value['revision'], hashlib.sha256(raw).hexdigest())


def capture_selection(selection_path=None, *, app_id, project_id):
    default = ProviderSelection('standalone', app_id, project_id)
    selected = _read(selection_path, project_id) if selection_path is not None else None
    if selected is None:
        return default
    if selected.app_id != app_id:
        raise InvalidRequest('Provider selection belongs to another app')
    # The root file chooses this app's provider; each operation binds its own project.
    return selected.for_project(project_id)


def ensure_selection_current(selection, selection_path=None):
    current = capture_selection(selection_path, app_id=selection.app_id, project_id=selection.project_id)
    if current != selection:
        raise StaleSelection('Provider configuration changed during the operation; result must not be written')
    return selection


def save_selection(selection_path, selection):
    """Save an explicitly chosen configuration. Callers own UI/authorization."""
    if not isinstance(selection, ProviderSelection):
        raise InvalidRequest('Expected ProviderSelection')
    path = Path(selection_path)
    if path.is_symlink():
        raise InvalidRequest('Provider selection cannot be a symlink')
    data = {'protocol': SELECTION_PROTOCOL, 'provider': selection.provider,
            'app_id': selection.app_id, 'revision': selection.revision}
    raw = (canonical_json(data, MAX_CONFIG_BYTES) + '\n').encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return capture_selection(path, app_id=selection.app_id, project_id=selection.project_id)
