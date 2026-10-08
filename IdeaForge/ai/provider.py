"""App-owned operation scopes for the opt-in text provider boundary.

No Aster endpoint, credentials, daemon or live transport is configured here.
Prompts, evidence identities, parsing and engineering validation stay in IdeaForge.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import inspect
import json
from pathlib import Path
import threading
import time
import uuid

import requests
from aster_provider import (
    ProviderError, ProviderCancelled, StaleSelection, UnsupportedCapability, InvalidRequest,
    ProviderSelection, save_selection,
    capture_selection, ensure_selection_current, guard, invoke_text,
)

APP_ID = 'ideaforge'
SELECTION_PATH = Path(__file__).resolve().parents[1] / 'ai_provider.json'
SESSION_ID = uuid.uuid4().hex  # Process-local. Never restore requests across restart.
MAX_MESSAGE_CHARS = 180_000
MAX_RESPONSE_CHARS = 262_144
_CURRENT = ContextVar('ideaforge_provider_operation', default=None)


def _bytes(path):
    return Path(path).read_bytes()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def project_id(root):
    if root is None:
        return 'workspace'
    path = Path(root).resolve()
    record = json.loads((path / 'project.json').read_text(encoding='utf-8'))
    # Legacy projects without an ID are scoped to their full canonical path.
    return str(record.get('project_id') or 'legacy-' + _digest(str(path).encode())[:24])


@dataclass
class Operation:
    selection: object
    config_path: Path
    config_digest: str
    config: dict
    root: Path | None
    project: str
    cancellation: threading.Event
    deadline: float
    selection_path: Path
    session_id: str = SESSION_ID
    request_prefix: str = field(default_factory=lambda: uuid.uuid4().hex)
    transport: object = None  # Offline injection only; never loaded from configuration.
    provenance: list = field(default_factory=list)
    project_current: object = None

    def check(self):
        guard(cancellation=self.cancellation.is_set, deadline=self.deadline)
        ensure_selection_current(self.selection, self.selection_path)
        if _digest(_bytes(self.config_path)) != self.config_digest:
            raise StaleSelection('IdeaForge AI configuration changed; start a new operation.')
        if self.root is not None and project_id(self.root) != self.project:
            raise StaleSelection('IdeaForge project identity changed; late result discarded.')
        if self.project_current is not None and self.root is not None:
            current = self.project_current()
            if current is None or Path(current).resolve() != self.root:
                raise ProviderCancelled('IdeaForge project changed; late result discarded.')


def current_operation():
    return _CURRENT.get()


@contextmanager
def operation(project_root=None, config_path='ai/config.json', *, selection_path=None,
              selection=None, cancellation=None, deadline=None, transport=None,
              project_current=None, session_id=None):
    """Capture once, then reuse across nested calls; threads must pass an operation."""
    existing = current_operation()
    if existing is not None:
        existing.check()
        if project_root is not None and existing.root != Path(project_root).resolve():
            raise StaleSelection('Nested provider call belongs to a different project.')
        yield existing
        return
    config_path = Path(config_path).resolve()
    raw = _bytes(config_path)
    config = json.loads(raw)
    selection_path = Path(selection_path or SELECTION_PATH).absolute()
    identity = project_id(project_root)
    selection = selection or capture_selection(selection_path, app_id=APP_ID, project_id=identity)
    timeout = min(max(float(config.get('language_model', {}).get('timeout_seconds', 180)), .01), 1800)
    op = Operation(selection, config_path, _digest(raw), config,
                   Path(project_root).resolve() if project_root is not None else None,
                   identity, cancellation if cancellation is not None else threading.Event(),
                   deadline if deadline is not None else time.time() + timeout,
                   selection_path, session_id or SESSION_ID, transport=transport,
                   project_current=project_current)
    with activate(op):
        yield op


@contextmanager
def activate(op):
    """Run an already captured queue entry without consulting a new selection."""
    token = _CURRENT.set(op)
    try:
        op.check()
        yield op
    finally:
        _CURRENT.reset(token)


def bind_created_project(root):
    """Explicit workspace→new project transition, preserving captured selection."""
    op = current_operation()
    if op is None:
        return
    op.check()
    if op.root is not None:
        raise StaleSelection('An existing project operation cannot be rebound.')
    op.root = Path(root).resolve()
    op.project = project_id(root)
    op.selection = op.selection.for_project(op.project)


def provider_operation(function):
    signature = inspect.signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs)
        arguments.apply_defaults()
        values = arguments.arguments
        owner = values.get('self')
        root = values.get('project_root', getattr(owner, 'current_project', None))
        config = values.get('ai_config', values.get('config_path', getattr(owner, 'config_path', 'ai/config.json')))
        with operation(root, config):
            return function(*args, **kwargs)
    return wrapped


def publication_guard(project_root=None):
    op = current_operation()
    if op is None:
        raise RuntimeError('Model publication requires an active provider operation.')
    op.check()
    if project_root is not None and Path(project_root).resolve() != op.root:
        raise StaleSelection('Model publication belongs to a different project.')


def model_config(kind='language_model'):
    op = current_operation()
    if op is None:
        raise RuntimeError('Provider configuration requires an active operation.')
    op.check()
    return dict(op.config[kind])


def text_call(messages, *, task, format=None, options=None):
    op = current_operation()
    if op is None:
        raise RuntimeError('Text calls require an active provider operation.')
    op.check()
    encoded = json.dumps(messages, ensure_ascii=False, allow_nan=False)
    if (len(encoded.encode("utf-8")) > MAX_MESSAGE_CHARS or len(messages) > 64 or
            any(len(str(message.get("content", "")).encode("utf-8")) > 65536 for message in messages)):
        raise InvalidRequest('IdeaForge text context exceeds the bounded request limit.')
    lm = model_config()
    options = dict(options or {'temperature': lm.get('temperature', .25)})
    def standalone():
        op.check()
        payload = {'model': lm['model'], 'messages': messages, 'stream': False, 'options': options}
        if format is not None:
            payload['format'] = format
        response = requests.post(lm['base_url'].rstrip('/') + '/api/chat', json=payload,
                                 timeout=min(float(lm.get('timeout_seconds', 180)), op.deadline - time.time()))
        response.raise_for_status()
        return response.json()['message']['content']
    result = invoke_text(messages, standalone, app_id=APP_ID, project_id=op.project,
                         task=task, schema=format, selection=op.selection,
                         selection_path=op.selection_path, transport=op.transport,
                         cancellation=op.cancellation.is_set, deadline=op.deadline,
                         session_id=op.session_id,
                         request_id=op.request_prefix + '-' + uuid.uuid4().hex,
                         options=options)
    op.check()
    if not isinstance(result.text, str) or len(result.text.encode("utf-8")) > MAX_RESPONSE_CHARS:
        raise InvalidRequest('Oversized or malformed IdeaForge provider response.')
    receipt=result.provenance.to_dict()
    receipt.update(operation_id=op.request_prefix, ai_config_digest=op.config_digest)
    op.provenance.append(receipt)
    return result.text


def vision_guard():
    op = current_operation()
    if op is None:
        raise RuntimeError('Vision requires an active provider operation.')
    op.check()
    if op.selection.provider != 'standalone':
        raise UnsupportedCapability('Aster vision is unavailable. The standalone qwen3-vl specialist is disabled in Aster mode.')


def status(config_path='ai/config.json', selection_path=None):
    selected = capture_selection(selection_path or SELECTION_PATH, app_id=APP_ID, project_id='workspace')
    if selected.provider == 'aster':
        return 'Aster: unavailable · vision disabled'
    cfg = json.loads(Path(config_path).read_text(encoding='utf-8'))
    return 'Standalone: ' + cfg['language_model']['model'] + ' · vision: qwen3-vl specialist'


def main(argv=None):
    """Explicit local selection only. Does not install, connect or invoke a model."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('standalone', 'aster'))
    parser.add_argument('--selection-path', type=Path, default=SELECTION_PATH)
    parser.add_argument('--config', default='ai/config.json')
    args = parser.parse_args(argv)
    if args.provider:
        selected = capture_selection(args.selection_path, app_id=APP_ID, project_id='workspace')
        save_selection(args.selection_path, ProviderSelection(args.provider, APP_ID, 'workspace', selected.revision + 1))
    print(status(args.config, args.selection_path))


if __name__ == '__main__':
    main()
