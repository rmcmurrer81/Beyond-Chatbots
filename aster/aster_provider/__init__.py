"""Aster app-provider preparation v1. No live backend, implicit fallback or I/O."""
from .contract import (
    APP_IDS, PROTOCOL, SELECTION_PROTOCOL, Capability, ContextRecord, Message,
    ProviderRequest, ProviderResponse, ProviderSelection, ProviderText, Provenance,
    Readiness, ProviderError, ProviderUnavailable, UnsupportedCapability,
    InvalidRequest, ProviderCancelled, DeadlineExceeded, ReplayMismatch,
    ProtocolMismatch, StaleSelection, schema_identity,
)
from .selection import capture_selection, ensure_selection_current, save_selection
from .client import CancellationToken, ainvoke_text, deadline_after, guard, invoke_text
from .transport import InProcessTestTransport, UnavailableTransport, readiness

__version__ = '1.0.0-preparation'
