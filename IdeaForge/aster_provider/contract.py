"""Versioned, bounded, data-only contract. Importing it performs no I/O."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import re
from typing import Any, Mapping

PROTOCOL = 'aster.app-provider.v1'
SELECTION_PROTOCOL = 'aster.provider.selection.v1'
APP_IDS = frozenset({'ideaforge', 'humanoid-researcher', 'bluebook'})
MAX_MESSAGES = 64
MAX_MESSAGE_BYTES = 65536
MAX_INPUT_BYTES = 524288
MAX_OUTPUT_BYTES = 262144
MAX_SCHEMA_BYTES = 16384
MAX_OPTIONS_BYTES = 8192
MAX_CONTEXT_RECORDS = 32
GENERATION_OPTIONS = frozenset({'temperature', 'num_predict', 'max_tokens',
                                'top_p', 'top_k', 'seed', 'stop'})
_TOKEN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:/@ -]{0,199}$')


class ProviderError(RuntimeError):
    code = 'provider_error'
    fallback = None

    def to_dict(self):
        return {'code': self.code, 'reason': str(self), 'fallback': None}


class ProviderUnavailable(ProviderError):
    code = 'unavailable'


class UnsupportedCapability(ProviderError):
    code = 'unsupported_capability'


class InvalidRequest(ProviderError):
    code = 'invalid_request'


class ProviderCancelled(ProviderError):
    code = 'cancelled'


class DeadlineExceeded(ProviderError):
    code = 'deadline_exceeded'


class ReplayMismatch(ProviderError):
    code = 'replay_mismatch'


class ProtocolMismatch(ProviderError):
    code = 'protocol_mismatch'


class StaleSelection(ProviderError):
    code = 'stale_selection'


def bounded_text(value, name, maximum, *, empty=False):
    if not isinstance(value, str) or (not empty and not value):
        raise InvalidRequest(name + ' must be text' + ('' if empty else ' and nonempty'))
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError as exc:
        raise InvalidRequest(name + ' contains invalid Unicode') from exc
    if size > maximum:
        raise InvalidRequest(name + ' exceeds its UTF-8 byte limit')
    return value


def identifier(value, name):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise InvalidRequest(name + ' must be a bounded identifier')
    return value


def app_identifier(value):
    if type(value) is not str or value not in APP_IDS:
        raise InvalidRequest('Unrecognized app_id')
    return value


def canonical_json(value, maximum=MAX_INPUT_BYTES):
    """Bound bytes/depth/nodes and reject non-JSON or non-finite values."""
    nodes = 0

    def check(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 10000 or depth > 16:
            raise InvalidRequest('JSON structure exceeds its node/depth limit')
        if item is None or type(item) in (str, bool, int):
            if isinstance(item, str):
                bounded_text(item, 'JSON text', maximum, empty=True)
            if type(item) is int and item.bit_length() > 256:
                raise InvalidRequest('JSON integer exceeds its limit')
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise InvalidRequest('JSON numbers must be finite')
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise InvalidRequest('JSON object keys must be strings')
                check(key, depth + 1)
                check(child, depth + 1)
            return
        if type(item) in (list, tuple):
            for child in item:
                check(child, depth + 1)
            return
        raise InvalidRequest('Only data-only JSON values are accepted')

    check(value)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise InvalidRequest('Invalid JSON data') from exc
    return bounded_text(raw, 'JSON envelope', maximum)


def validate_options(options):
    if type(options) is not dict or set(options) - GENERATION_OPTIONS:
        raise InvalidRequest('Only generation-only option keys are allowed; schema uses the typed schema field')
    canonical_json(options, MAX_OPTIONS_BYTES)
    for key, value in options.items():
        if key == 'stop':
            values = [value] if type(value) is str else value
            if type(values) is not list or len(values) > 32:
                raise InvalidRequest('stop must be text or a bounded list of text')
            for item in values:
                bounded_text(item, 'stop sequence', 256)
        elif type(value) not in (int, float) or not math.isfinite(value):
            raise InvalidRequest('Generation numeric options must be finite numbers')
        elif key in {'num_predict', 'max_tokens', 'top_k', 'seed'} and type(value) is not int:
            raise InvalidRequest(key + ' must be an integer')
    return options


def schema_identity(schema=None):
    if schema is None:
        return 'text', 'null'
    if isinstance(schema, str):
        return identifier(schema, 'schema_id'), canonical_json(schema, MAX_SCHEMA_BYTES)
    if type(schema) is not dict:
        raise InvalidRequest('schema must be a stable ID or JSON-schema object')
    raw = canonical_json(schema, MAX_SCHEMA_BYTES)
    return 'sha256:' + hashlib.sha256(raw.encode()).hexdigest(), raw


@dataclass(frozen=True)
class Capability:
    task: str
    schema_id: str = 'text'

    def __post_init__(self):
        identifier(self.task, 'task')
        identifier(self.schema_id, 'schema_id')


def supports_capability(capabilities, task, schema_id, *, json_schema=False):
    """Exact task plus exact schema, or explicit JSON-schema object capability."""
    return (Capability(task, schema_id) in capabilities or
            (json_schema and Capability(task, 'json-schema') in capabilities))


@dataclass(frozen=True)
class ProviderSelection:
    provider: str
    app_id: str
    project_id: str
    revision: int = 0
    config_digest: str = ''

    def __post_init__(self):
        if type(self.provider) is not str or self.provider not in {'standalone', 'aster'}:
            raise InvalidRequest('Provider must be standalone or aster')
        app_identifier(self.app_id)
        identifier(self.project_id, 'project_id')
        if type(self.revision) is not int or not 0 <= self.revision <= 2**53 - 1:
            raise InvalidRequest('Selection revision must be a bounded nonnegative integer')
        if self.config_digest and not re.fullmatch(r'[0-9a-f]{64}', self.config_digest):
            raise InvalidRequest('Invalid selection config digest')

    def to_dict(self):
        return asdict(self)

    def for_project(self, project_id):
        """Explicit child-project binding; never rereads or switches provider."""
        return replace(self, project_id=identifier(project_id, 'project_id'))


@dataclass(frozen=True)
class Message:
    role: str
    content: str
    untrusted: bool = True

    def __post_init__(self):
        if type(self.role) is not str or self.role not in {'system', 'user', 'assistant', 'tool'}:
            raise InvalidRequest('Unsupported message role')
        bounded_text(self.content, 'message content', MAX_MESSAGE_BYTES, empty=True)
        if self.untrusted is not True:
            raise InvalidRequest('App messages must be marked untrusted')


@dataclass(frozen=True)
class ContextRecord:
    source_id: str
    text: str
    app_id: str
    project_id: str
    scope: str = 'project'
    untrusted: bool = True

    def __post_init__(self):
        identifier(self.source_id, 'source_id')
        bounded_text(self.text, 'context text', MAX_MESSAGE_BYTES, empty=True)
        app_identifier(self.app_id)
        identifier(self.project_id, 'project_id')
        if type(self.scope) is not str or self.scope not in {'project', 'transient'} or self.untrusted is not True:
            raise InvalidRequest('Only untrusted project/transient context is permitted')


@dataclass(frozen=True)
class ProviderRequest:
    app_id: str
    project_id: str
    session_id: str
    request_id: str
    task: str
    schema_id: str
    schema_json: str
    messages: tuple[Message, ...]
    context: tuple[ContextRecord, ...]
    options_json: str
    config_revision: int
    config_digest: str
    deadline: float | None
    input_digest: str
    protocol: str = PROTOCOL
    memory_scope: str = 'transient'
    allow_personal_memory: bool = False
    allow_training: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    app_id: str
    project_id: str
    session_id: str
    request_id: str
    task: str
    schema_id: str
    input_digest: str
    config_revision: int
    config_digest: str
    protocol: str = PROTOCOL

    @classmethod
    def for_request(cls, request, text):
        return cls(text=text, **{key: getattr(request, key) for key in (
            'app_id', 'project_id', 'session_id', 'request_id', 'task', 'schema_id',
            'input_digest', 'config_revision', 'config_digest', 'protocol')})


@dataclass(frozen=True)
class Readiness:
    reachable: bool
    compatible: bool
    qualified: bool
    reason: str
    capabilities: tuple[Capability, ...] = ()
    protocol: str = PROTOCOL
    test_only: bool = False
    fallback: None = None
    production_available: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Provenance:
    provider: str
    app_id: str
    project_id: str
    session_id: str
    request_id: str
    task: str
    schema_id: str
    config_revision: int
    config_digest: str
    input_digest: str
    test_only: bool = False
    protocol: str = PROTOCOL
    fallback: None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ProviderText:
    text: str
    provenance: Provenance

    @property
    def metadata(self):
        return self.provenance.to_dict()
