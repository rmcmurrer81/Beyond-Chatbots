"""Operation-bound synchronous/asynchronous routing, without a live transport."""
from __future__ import annotations
import asyncio
from dataclasses import replace
import hashlib
import inspect
import json
import math
import threading
import time
import uuid
from .contract import *
from .selection import capture_selection
from .transport import checked_transport, validate_response


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()


def deadline_after(seconds):
    if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
        raise InvalidRequest('Deadline duration must be finite and nonnegative')
    return time.time() + seconds


def guard(cancellation=None, deadline=None):
    if cancellation is not None:
        if isinstance(cancellation, CancellationToken):
            cancelled = cancellation.cancelled
        elif callable(cancellation):
            cancelled = cancellation()
            if type(cancelled) is not bool:
                raise InvalidRequest('Cancellation callback must return a boolean')
        else:
            raise InvalidRequest('Expected CancellationToken or boolean callback')
        if cancelled:
            raise ProviderCancelled('Operation was cancelled; provider output must not be committed')
    if deadline is not None:
        if type(deadline) not in (float, int) or not math.isfinite(deadline):
            raise InvalidRequest('Deadline must be a finite absolute Unix timestamp')
        if time.time() >= deadline:
            raise DeadlineExceeded('Absolute operation deadline expired; provider output must not be committed')


def _digest(request):
    data = request.to_dict()
    data.pop('input_digest')
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()


def validate_request(request):
    if not isinstance(request, ProviderRequest) or request.protocol != PROTOCOL:
        raise ProtocolMismatch('Unsupported app-provider request protocol')
    app_identifier(request.app_id)
    for key in ('project_id', 'session_id', 'request_id', 'task', 'schema_id'):
        identifier(getattr(request, key), key)
    ProviderSelection('aster', request.app_id, request.project_id,
                      request.config_revision, request.config_digest)
    if (type(request.memory_scope) is not str or request.memory_scope not in {'project', 'transient'} or
            request.allow_personal_memory is not False or request.allow_training is not False):
        raise InvalidRequest('Personal-memory access and training are prohibited')
    if type(request.messages) is not tuple or not 1 <= len(request.messages) <= MAX_MESSAGES:
        raise InvalidRequest('Expected 1 to 64 immutable messages')
    if any(type(message) is not Message for message in request.messages):
        raise InvalidRequest('Expected typed untrusted messages')
    for message in request.messages:
        message.__post_init__()
    if type(request.context) is not tuple or len(request.context) > MAX_CONTEXT_RECORDS:
        raise InvalidRequest('Context exceeds its record limit')
    for record in request.context:
        if type(record) is not ContextRecord:
            raise InvalidRequest('Expected typed context')
        record.__post_init__()
        if record.app_id != request.app_id or record.project_id != request.project_id:
            raise InvalidRequest('Context must belong to the bound app and project')
    for name, limit in (('schema_json', MAX_SCHEMA_BYTES), ('options_json', MAX_OPTIONS_BYTES)):
        bounded_text(getattr(request, name), name, limit)
        try:
            value = json.loads(getattr(request, name))
        except (ValueError, RecursionError) as exc:
            raise InvalidRequest('Invalid serialized ' + name) from exc
        if canonical_json(value, limit) != getattr(request, name):
            raise InvalidRequest(name + ' must be canonical JSON')
        if name == 'schema_json' and schema_identity(value)[0] != request.schema_id:
            raise InvalidRequest('Schema identity does not match its contents')
        if name == 'options_json':
            validate_options(value)
    guard(deadline=request.deadline)
    if _digest(request) != request.input_digest:
        raise ReplayMismatch('Input digest does not match the complete request')
    return request


def _make_request(messages, selection, task, schema, context, options, session_id, request_id, deadline):
    if not isinstance(messages, (tuple, list)) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise InvalidRequest('Expected a bounded nonempty message sequence')
    parsed = []
    for value in messages:
        if type(value) is Message:
            parsed.append(value)
        elif type(value) is dict and set(value) == {'role', 'content'}:
            parsed.append(Message(**value))
        else:
            raise InvalidRequest('Messages must contain only role and text content')
    if not isinstance(context, (tuple, list)) or len(context) > MAX_CONTEXT_RECORDS:
        raise InvalidRequest('Expected bounded context records')
    records = []
    for value in context:
        try:
            records.append(value if type(value) is ContextRecord else ContextRecord(**value))
        except (TypeError, ValueError) as exc:
            raise InvalidRequest('Invalid context record') from exc
    schema_id, schema_json = schema_identity(schema)
    request = ProviderRequest(selection.app_id, selection.project_id,
        session_id or uuid.uuid4().hex, request_id or uuid.uuid4().hex,
        task, schema_id, schema_json, tuple(parsed), tuple(records),
        canonical_json(validate_options(options), MAX_OPTIONS_BYTES), selection.revision, selection.config_digest,
        deadline, '')
    request = replace(request, input_digest=_digest(request))
    return validate_request(request)


def _selection(selection, selection_path, app_id, project_id):
    if selection is None:
        selection = capture_selection(selection_path, app_id=app_id, project_id=project_id)
    if not isinstance(selection, ProviderSelection):
        raise InvalidRequest('Expected captured ProviderSelection')
    if selection.app_id != app_id or selection.project_id != project_id:
        raise InvalidRequest('Captured provider selection does not match this app/project')
    return selection


def _provenance(selection, *, task, schema_id, session_id, request_id, input_digest='', test_only=False):
    return Provenance(selection.provider, selection.app_id, selection.project_id,
        session_id, request_id, task, schema_id, selection.revision, selection.config_digest,
        input_digest, test_only)


def _start(messages, *, app_id, project_id, task, schema, selection, selection_path,
           transport, context, options, session_id, request_id, cancellation, deadline):
    guard(cancellation, deadline)
    selected = _selection(selection, selection_path, app_id, project_id)
    identifier(task, 'task')
    schema_id = schema_identity(schema)[0]
    session_id = identifier(session_id or uuid.uuid4().hex, 'session_id')
    request_id = identifier(request_id or uuid.uuid4().hex, 'request_id')
    if selected.provider == 'standalone':
        return selected, None, None, _provenance(selected, task=task, schema_id=schema_id,
                                               session_id=session_id, request_id=request_id)
    request = _make_request(messages, selected, task, schema, context, options,
                            session_id, request_id, deadline)
    active = checked_transport(transport)
    ready = active.readiness()
    if not ready.reachable:
        raise ProviderUnavailable(ready.reason)
    if not ready.compatible:
        raise ProtocolMismatch('Provider protocol is incompatible')
    if not ready.qualified:
        raise ProviderUnavailable(ready.reason)
    if not supports_capability(ready.capabilities, task, schema_id, json_schema=type(schema) is dict):
        raise UnsupportedCapability('Required task/output-schema capability is not advertised')
    return selected, request, active, _provenance(selected, task=task, schema_id=schema_id,
        session_id=session_id, request_id=request_id, input_digest=request.input_digest, test_only=ready.test_only)


def invoke_text(messages, standalone_callback, *, app_id, project_id, task, schema=None,
                selection=None, selection_path=None, transport=None, cancellation=None,
                deadline=None, session_id=None, request_id=None, context=(), options=None):
    selected, request, active, provenance = _start(messages, app_id=app_id, project_id=project_id,
        task=task, schema=schema, selection=selection, selection_path=selection_path,
        transport=transport, context=context, options={} if options is None else options,
        session_id=session_id, request_id=request_id, cancellation=cancellation, deadline=deadline)
    guard(cancellation, deadline)
    if selected.provider == 'standalone':
        output = standalone_callback()
        if inspect.isawaitable(output):
            if inspect.iscoroutine(output):
                output.close()
            raise InvalidRequest('Async standalone callback requires ainvoke_text')
    else:
        output = validate_response(request, active.invoke(request)).text
    guard(cancellation, deadline)
    if not isinstance(output, str):
        raise InvalidRequest('Provider text callback must return raw text')
    return ProviderText(output, provenance)


async def ainvoke_text(messages, standalone_callback, *, app_id, project_id, task, schema=None,
                       selection=None, selection_path=None, transport=None, cancellation=None,
                       deadline=None, session_id=None, request_id=None, context=(), options=None):
    selected, request, active, provenance = _start(messages, app_id=app_id, project_id=project_id,
        task=task, schema=schema, selection=selection, selection_path=selection_path,
        transport=transport, context=context, options={} if options is None else options,
        session_id=session_id, request_id=request_id, cancellation=cancellation, deadline=deadline)
    guard(cancellation, deadline)
    candidate = standalone_callback() if selected.provider == 'standalone' else active.ainvoke(request)
    if inspect.isawaitable(candidate):
        try:
            candidate = await candidate if deadline is None else await asyncio.wait_for(
                candidate, timeout=max(0, deadline - time.time()))
        except asyncio.TimeoutError as exc:
            raise DeadlineExceeded('Absolute operation deadline expired during provider call') from exc
    guard(cancellation, deadline)
    output = candidate if selected.provider == 'standalone' else validate_response(request, candidate).text
    if not isinstance(output, str):
        raise InvalidRequest('Provider text callback must return raw text')
    return ProviderText(output, provenance)
