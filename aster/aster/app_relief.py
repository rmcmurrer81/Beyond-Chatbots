"""Pure, diagnostic-only memory-relief policy. No observation or action adapters.

All evidence is caller-supplied data, not authenticated proof. Even a fully
positive simulation cannot enable saving, closing, or dispatching any app.
"""

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Literal


MIN_IDLE_SECONDS = 300
MAX_EVIDENCE_AGE_SECONDS = 15


class PresenceState(str, Enum):
    UNKNOWN = 'unknown'
    PRESENT = 'present'
    ABSENT = 'absent'


@dataclass(frozen=True)
class PresenceEvidence:
    state: PresenceState = PresenceState.UNKNOWN
    observed_at: float | None = None


@dataclass(frozen=True)
class KeyboardIdleEvidence:
    idle_seconds: float | None = None
    observed_at: float | None = None


@dataclass(frozen=True)
class CandidateEvidence:
    app_id: str
    observed_at: float | None = None
    saved_state_verified: bool | None = None
    game_active: bool | None = None
    download_active: bool | None = None
    sync_active: bool | None = None


@dataclass(frozen=True)
class DraftSaveReceipt:
    content_sha256: str
    revision: int
    saved_at: float


@dataclass(frozen=True)
class DraftEvidence:
    current_content_sha256: str
    current_revision: int
    rechecked_at: float
    save_receipt: DraftSaveReceipt | None = None
    changed_since_recheck: bool | None = None


@dataclass(frozen=True)
class BrowserEvidence:
    observed_at: float | None = None
    dirty_form: bool | None = None
    dirty_editor: bool | None = None
    media_active: bool | None = None
    download_active: bool | None = None
    public_session_saved_verified: bool | None = None
    email_compose_active: bool | None = None
    draft: DraftEvidence | None = None


@dataclass(frozen=True)
class CandidateManifest:
    app_id: str
    label: str

    @property
    def supported(self) -> Literal[False]:
        return False

    @property
    def enabled(self) -> Literal[False]:
        return False


# Examples for separate future app-specific review, never an allowlist.
CANDIDATE_MANIFESTS = (
    CandidateManifest('steam', 'Steam'),
    CandidateManifest('icloud', 'iCloud'),
    CandidateManifest('browser', 'Web browser'),
)


@dataclass(frozen=True)
class ReliefPlan:
    app_id: str
    blocked_reasons: tuple[str, ...]

    @property
    def status(self) -> Literal['blocked']:
        return 'blocked'

    @property
    def execution_available(self) -> Literal[False]:
        return False


def _number(value: object) -> bool:
    return (type(value) is int and value >= 0
            or type(value) is float and isfinite(value) and value >= 0)


def _fresh(observed_at: object, now: float) -> bool:
    if not _number(observed_at):
        return False
    try:
        return 0 <= now - observed_at <= MAX_EVIDENCE_AGE_SECONDS
    except OverflowError:
        return False


def _hash(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(character in '0123456789abcdef' for character in value))


def _draft_rechecked(draft: DraftEvidence | None, now: float) -> bool:
    if type(draft) is not DraftEvidence or type(draft.save_receipt) is not DraftSaveReceipt:
        return False
    receipt = draft.save_receipt
    return (_hash(draft.current_content_sha256) and _hash(receipt.content_sha256)
            and draft.current_content_sha256 == receipt.content_sha256
            and type(draft.current_revision) is int and draft.current_revision >= 0
            and type(receipt.revision) is int and draft.current_revision == receipt.revision
            and _fresh(draft.rechecked_at, now) and _number(receipt.saved_at)
            and receipt.saved_at <= draft.rechecked_at
            and draft.changed_since_recheck is False)


def status() -> dict:
    """Static capability report; never run collectors or the diagnostic planner."""
    return {
        'status': 'disabled_no_reviewed_app_adapters',
        'mode': 'diagnostic_only',
        'execution_available': False,
        'camera_capture_available': False,
        'keystroke_capture_available': False,
        'presence_collection_available': False,
        'keyboard_idle_collection_available': False,
        'process_inspection_available': False,
        'process_termination_available': False,
        'session_capture_available': False,
        'app_save_available': False,
        'app_close_available': False,
        'draft_save_available': False,
        'email_send_available': False,
        'operational_allowlist': [],
        'candidates': [dict(app_id=manifest.app_id, label=manifest.label,
                            status='candidate_only_unreviewed', supported=False, enabled=False)
                       for manifest in CANDIDATE_MANIFESTS],
    }


def plan_relief(
    candidate: CandidateEvidence,
    *,
    now: float,
    presence: PresenceEvidence | None = None,
    keyboard_idle: KeyboardIdleEvidence | None = None,
    browser: BrowserEvidence | None = None,
) -> ReliefPlan:
    """Report blockers for exactly one app; never return executable instructions.

    Times must use one caller-selected clock. Missing, future, stale, or invalid
    evidence fails closed. These diagnostics neither collect evidence nor grant
    permission. There is intentionally no dispatcher, callback, or batch API.
    """
    if type(candidate) is not CandidateEvidence:
        raise ValueError('Exactly one CandidateEvidence is required; batches are unsupported')
    if type(candidate.app_id) is not str or not candidate.app_id.strip():
        raise ValueError('One explicit app ID is required')
    if not _number(now):
        raise ValueError('A finite nonnegative caller-supplied time is required')
    if presence is not None and type(presence) is not PresenceEvidence:
        raise ValueError('Expected optional typed presence evidence')
    if keyboard_idle is not None and type(keyboard_idle) is not KeyboardIdleEvidence:
        raise ValueError('Expected optional typed keyboard-idle evidence')
    if browser is not None and type(browser) is not BrowserEvidence:
        raise ValueError('Expected optional typed browser evidence')

    # These unconditional blockers cannot be removed by positive input flags.
    reasons = ['action_dispatch_unavailable', 'app_specific_integration_unreviewed']
    known_candidate = candidate.app_id in ('steam', 'icloud', 'browser')
    if not known_candidate:
        reasons.append('unsupported_candidate')
    if presence is None or presence.state is not PresenceState.ABSENT:
        reasons.append('known_absence_required')
    if presence is None or not _fresh(presence.observed_at, now):
        reasons.append('fresh_presence_evidence_required')
    if (keyboard_idle is None or not _number(keyboard_idle.idle_seconds)
            or keyboard_idle.idle_seconds < MIN_IDLE_SECONDS):
        reasons.append('keyboard_idle_delay_required')
    if keyboard_idle is None or not _fresh(keyboard_idle.observed_at, now):
        reasons.append('fresh_keyboard_idle_evidence_required')
    if not _fresh(candidate.observed_at, now):
        reasons.append('fresh_app_state_evidence_required')
    if candidate.saved_state_verified is not True:
        reasons.append('verified_saved_state_required')
    for field in ('game_active', 'download_active', 'sync_active'):
        if getattr(candidate, field) is not False:
            reasons.append('verified_no_' + field + '_required')
    if candidate.app_id == 'browser':
        reasons.append('live_preclose_recheck_unavailable')
        if browser is None or not _fresh(browser.observed_at, now):
            reasons.append('fresh_browser_evidence_required')
        for field in ('dirty_form', 'dirty_editor', 'media_active', 'download_active'):
            if browser is None or getattr(browser, field) is not False:
                reasons.append('verified_no_browser_' + field + '_required')
        if browser is None or browser.public_session_saved_verified is not True:
            reasons.append('verified_public_session_save_required')
        if browser is None or type(browser.email_compose_active) is not bool:
            reasons.append('known_email_compose_state_required')
        elif browser.email_compose_active and not _draft_rechecked(browser.draft, now):
            reasons.append('exact_draft_save_receipt_and_recheck_required')
    # Never echo arbitrary labels, URLs, hashes, revisions, or private content.
    return ReliefPlan(candidate.app_id if known_candidate else 'unsupported', tuple(reasons))
