"""Unavailable production boundary and explicitly injected in-process fixtures.

There is deliberately no socket, subprocess, runtime loader, Store or endpoint.
Fixture handlers are trusted test code, not code supplied by messages/context.
"""
from __future__ import annotations
import inspect
import json
import threading
from .contract import (Capability, InvalidRequest, ProtocolMismatch, ProviderRequest,
                       ProviderResponse, ProviderUnavailable, Readiness, ReplayMismatch,
                       UnsupportedCapability, MAX_OUTPUT_BYTES, bounded_text, supports_capability)


class UnavailableTransport:
    def readiness(self):
        return Readiness(False, False, False,
            'Preparation only: no qualified NewBrain app-provider backend or live transport is connected.')

    def invoke(self, request):
        raise ProviderUnavailable(self.readiness().reason)

    async def ainvoke(self, request):
        raise ProviderUnavailable(self.readiness().reason)


def validate_response(request, response):
    if not isinstance(response, ProviderResponse):
        raise ProtocolMismatch('Expected a typed ProviderResponse; raw fixture answers are rejected')
    for name in ('protocol', 'app_id', 'project_id', 'session_id', 'request_id',
                 'task', 'schema_id', 'input_digest', 'config_revision', 'config_digest'):
        if (type(getattr(response, name)) is not type(getattr(request, name)) or
                getattr(response, name) != getattr(request, name)):
            raise ProtocolMismatch('Response binding mismatch: ' + name)
    bounded_text(response.text, 'provider output', MAX_OUTPUT_BYTES, empty=True)
    return response


class InProcessTestTransport:
    """Bounded per-instance fixture ledger. Never a production qualification.

Exact retries return the original response. Reusing a request ID with changed
input/bindings is refused. Once full, refuse new requests instead of forgetting
replay protection. No registry, cache or caller data is kept globally or on disk.
"""
    def __init__(self, handler, *, capabilities=(), compatible=True, qualified=True,
                 max_requests=128):
        if not callable(handler):
            raise InvalidRequest('Fixture handler must be callable')
        self.handler = handler
        self.capabilities = tuple(capabilities)
        if (len(self.capabilities) > 128 or
                any(not isinstance(cap, Capability) for cap in self.capabilities)):
            raise InvalidRequest('Expected bounded typed fixture capabilities')
        if type(compatible) is not bool or type(qualified) is not bool:
            raise InvalidRequest('Fixture readiness flags must be boolean')
        if type(max_requests) is not int or not 1 <= max_requests <= 1024:
            raise InvalidRequest('Fixture replay limit must be between 1 and 1024')
        self.compatible, self.qualified = compatible, qualified
        self.max_requests = max_requests
        self._ledger = {}
        self._inflight = set()
        self._lock = threading.Lock()

    def readiness(self):
        return Readiness(True, self.compatible, self.qualified,
            'Injected in-process test fixture only; production NewBrain remains unavailable.',
            self.capabilities, test_only=True)

    def _begin(self, request):
        # Request validation is repeated at the seam; direct fixture use is safe too.
        from .client import validate_request
        validate_request(request)
        ready = self.readiness()
        if not ready.compatible:
            raise ProtocolMismatch('Fixture does not support this contract version')
        if not ready.qualified:
            raise ProviderUnavailable('Fixture is not qualified even for this test')
        if not supports_capability(ready.capabilities, request.task, request.schema_id,
                                   json_schema=type(json.loads(request.schema_json)) is dict):
            raise UnsupportedCapability('Required task/output-schema capability is not advertised')
        with self._lock:
            previous = self._ledger.get(request.request_id)
            if previous is not None:
                digest, response = previous
                if digest != request.input_digest:
                    raise ReplayMismatch('Request ID was already bound to different inputs or scope')
                if request.request_id in self._inflight or response is None:
                    raise ReplayMismatch('Prior request is in flight or did not yield a reusable response')
                return response
            if len(self._ledger) >= self.max_requests:
                raise ReplayMismatch('Fixture replay ledger is full; use a new explicit session transport')
            self._ledger[request.request_id] = (request.input_digest, None)
            self._inflight.add(request.request_id)
        return None

    def _finish(self, request, response=None):
        with self._lock:
            self._inflight.discard(request.request_id)
            self._ledger[request.request_id] = (request.input_digest, response)

    def invoke(self, request):
        previous = self._begin(request)
        if previous is not None:
            return previous
        response = None
        try:
            candidate = self.handler(request)
            if inspect.isawaitable(candidate):
                if inspect.iscoroutine(candidate):
                    candidate.close()
                raise InvalidRequest('Async fixture handler requires ainvoke_text')
            from .client import guard
            guard(deadline=request.deadline)
            response = validate_response(request, candidate)
            return response
        finally:
            self._finish(request, response)

    async def ainvoke(self, request):
        previous = self._begin(request)
        if previous is not None:
            return previous
        response = None
        try:
            candidate = self.handler(request)
            if inspect.isawaitable(candidate):
                candidate = await candidate
            from .client import guard
            guard(deadline=request.deadline)
            response = validate_response(request, candidate)
            return response
        finally:
            self._finish(request, response)


def checked_transport(transport=None):
    if transport is None:
        return UnavailableTransport()
    if type(transport) not in (UnavailableTransport, InProcessTestTransport):
        raise InvalidRequest('Only the unavailable transport or explicit in-process test transport is supported')
    return transport


def readiness(transport=None, *, task=None, schema=None):
    from dataclasses import replace
    from .contract import schema_identity
    ready = checked_transport(transport).readiness()
    if task is not None and ready.reachable and ready.compatible and ready.qualified:
        if not supports_capability(ready.capabilities, task, schema_identity(schema)[0],
                                   json_schema=type(schema) is dict):
            ready = replace(ready, qualified=False,
                reason='Required task/output-schema capability is not advertised; no fallback is permitted.')
    return ready
