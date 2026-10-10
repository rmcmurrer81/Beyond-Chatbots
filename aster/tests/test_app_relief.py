"""Simulation fixtures only: no camera, keyboard, process, or app observation."""

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest

from aster import app_relief
from aster.app_relief import (
    CANDIDATE_MANIFESTS, MAX_EVIDENCE_AGE_SECONDS, MIN_IDLE_SECONDS,
    BrowserEvidence, CandidateEvidence, DraftEvidence, DraftSaveReceipt,
    KeyboardIdleEvidence, PresenceEvidence, PresenceState, plan_relief, status,
)


SIMULATION_NOW = 1000.0
SIMULATION_CANDIDATE = CandidateEvidence('steam', SIMULATION_NOW, True, False, False, False)
SIMULATION_ABSENCE = PresenceEvidence(PresenceState.ABSENT, SIMULATION_NOW)
SIMULATION_IDLE = KeyboardIdleEvidence(MIN_IDLE_SECONDS, SIMULATION_NOW)
SIMULATION_BROWSER = BrowserEvidence(SIMULATION_NOW, False, False, False, False, True, False)
SIMULATION_DRAFT = DraftEvidence('a' * 64, 2, SIMULATION_NOW,
                                DraftSaveReceipt('a' * 64, 2, SIMULATION_NOW - 1), False)


class AppReliefSimulationTests(unittest.TestCase):
    def plan(self, candidate=SIMULATION_CANDIDATE, **overrides):
        inputs = dict(now=SIMULATION_NOW, presence=SIMULATION_ABSENCE,
                      keyboard_idle=SIMULATION_IDLE)
        inputs.update(overrides)
        return plan_relief(candidate, **inputs)

    def assert_blocked(self, result):
        self.assertEqual(result.status, 'blocked')
        self.assertIs(result.execution_available, False)
        self.assertIn('action_dispatch_unavailable', result.blocked_reasons)
        self.assertIn('app_specific_integration_unreviewed', result.blocked_reasons)

    def test_example_manifests_are_immutable_disabled_unsupported(self):
        self.assertEqual({m.app_id for m in CANDIDATE_MANIFESTS}, {'steam', 'icloud', 'browser'})
        for manifest in CANDIDATE_MANIFESTS:
            self.assertIs(manifest.supported, False)
            self.assertIs(manifest.enabled, False)
            with self.assertRaises(FrozenInstanceError):
                manifest.enabled = True

    def test_positive_simulations_still_cannot_enable_either_example(self):
        for manifest in CANDIDATE_MANIFESTS:
            result = self.plan(replace(SIMULATION_CANDIDATE, app_id=manifest.app_id),
                               browser=SIMULATION_BROWSER)
            self.assert_blocked(result)
            self.assertEqual(len(result.blocked_reasons), 3 if manifest.app_id == 'browser' else 2)
            with self.assertRaises(FrozenInstanceError):
                result.execution_available = True

    def test_unknown_missing_and_present_presence_block(self):
        for evidence in (None, PresenceEvidence(),
                         PresenceEvidence(PresenceState.PRESENT, SIMULATION_NOW),
                         PresenceEvidence('absent', SIMULATION_NOW)):
            result = self.plan(presence=evidence)
            self.assert_blocked(result)
            self.assertIn('known_absence_required', result.blocked_reasons)

    def test_simulated_webcam_absence_alone_never_authorizes_closure(self):
        result = self.plan(CandidateEvidence('steam'), keyboard_idle=None)
        self.assert_blocked(result)
        self.assertIn('keyboard_idle_delay_required', result.blocked_reasons)
        self.assertIn('verified_saved_state_required', result.blocked_reasons)

    def test_stale_missing_future_and_nonfinite_evidence_block(self):
        times = (None, SIMULATION_NOW - MAX_EVIDENCE_AGE_SECONDS - 0.01,
                 SIMULATION_NOW + 0.01, float('nan'), float('inf'), -1, True, '1000')
        for observed_at in times:
            with self.subTest(observed_at=observed_at):
                result = self.plan(
                    replace(SIMULATION_CANDIDATE, observed_at=observed_at),
                    presence=replace(SIMULATION_ABSENCE, observed_at=observed_at),
                    keyboard_idle=replace(SIMULATION_IDLE, observed_at=observed_at))
                self.assert_blocked(result)
                for source in ('presence', 'keyboard_idle', 'app_state'):
                    self.assertIn('fresh_' + source + '_evidence_required', result.blocked_reasons)

    def test_keyboard_idle_is_independent_and_must_reach_delay(self):
        for seconds in (None, 0, MIN_IDLE_SECONDS - 0.01, -1,
                        float('nan'), float('inf'), True, '300'):
            result = self.plan(keyboard_idle=replace(SIMULATION_IDLE, idle_seconds=seconds))
            self.assertIn('keyboard_idle_delay_required', result.blocked_reasons)
            self.assert_blocked(result)

    def test_unsaved_or_unverified_work_blocks_without_saving(self):
        for saved in (None, False, 1, 'true'):
            result = self.plan(replace(SIMULATION_CANDIDATE, saved_state_verified=saved))
            self.assertIn('verified_saved_state_required', result.blocked_reasons)
            self.assert_blocked(result)

    def test_active_or_unknown_game_download_and_sync_each_block(self):
        for field in ('game_active', 'download_active', 'sync_active'):
            for value in (None, True, 0, 'false'):
                result = self.plan(replace(SIMULATION_CANDIDATE, **{field: value}))
                self.assertIn('verified_no_' + field + '_required', result.blocked_reasons)
                self.assert_blocked(result)

    def test_generic_other_apps_and_process_names_are_not_permission(self):
        for app_id in ('another program', '*', 'steam.exe', 'iCloud', 'editor'):
            result = self.plan(replace(SIMULATION_CANDIDATE, app_id=app_id))
            self.assertIn('unsupported_candidate', result.blocked_reasons)
            self.assert_blocked(result)

    def test_status_is_static_disabled_with_empty_operational_allowlist(self):
        result = status()
        self.assertEqual(result['operational_allowlist'], [])
        self.assertEqual(result['mode'], 'diagnostic_only')
        for key, value in result.items():
            if key.endswith('_available'):
                self.assertIs(value, False)
        for candidate in result['candidates']:
            self.assertFalse(candidate['supported'])
            self.assertFalse(candidate['enabled'])
        result['operational_allowlist'].append('steam')
        result['candidates'][0]['enabled'] = True
        self.assertEqual(status()['operational_allowlist'], [])
        self.assertFalse(status()['candidates'][0]['enabled'])

    def test_browser_missing_and_busy_states_block(self):
        candidate = replace(SIMULATION_CANDIDATE, app_id='browser')
        result = self.plan(candidate)
        self.assertIn('fresh_browser_evidence_required', result.blocked_reasons)
        self.assertIn('known_email_compose_state_required', result.blocked_reasons)
        self.assert_blocked(result)
        for field in ('dirty_form', 'dirty_editor', 'media_active', 'download_active'):
            for value in (None, True, 0):
                result = self.plan(candidate, browser=replace(SIMULATION_BROWSER, **{field: value}))
                self.assertIn('verified_no_browser_' + field + '_required', result.blocked_reasons)
                self.assert_blocked(result)

    def test_browser_needs_fresh_evidence_and_verified_public_session_save(self):
        candidate = replace(SIMULATION_CANDIDATE, app_id='browser')
        for browser in (BrowserEvidence(), replace(SIMULATION_BROWSER, observed_at=0),
                        replace(SIMULATION_BROWSER, public_session_saved_verified=None)):
            result = self.plan(candidate, browser=browser)
            self.assert_blocked(result)
            self.assertTrue({'fresh_browser_evidence_required', 'verified_public_session_save_required'}
                            .intersection(result.blocked_reasons))

    def test_email_receipt_must_bind_current_content_revision_and_recheck(self):
        candidate = replace(SIMULATION_CANDIDATE, app_id='browser')
        invalid = (None, replace(SIMULATION_DRAFT, save_receipt=None),
                   replace(SIMULATION_DRAFT, current_content_sha256='b' * 64),
                   replace(SIMULATION_DRAFT, current_revision=3),
                   replace(SIMULATION_DRAFT, current_revision=True),
                   replace(SIMULATION_DRAFT, rechecked_at=0),
                   replace(SIMULATION_DRAFT, rechecked_at=SIMULATION_NOW + 1),
                   replace(SIMULATION_DRAFT, changed_since_recheck=True),
                   replace(SIMULATION_DRAFT, changed_since_recheck=None),
                   replace(SIMULATION_DRAFT, current_content_sha256='email content'),
                   replace(SIMULATION_DRAFT, save_receipt=replace(
                       SIMULATION_DRAFT.save_receipt, saved_at=SIMULATION_NOW + 1)))
        for draft in invalid:
            result = self.plan(candidate, browser=replace(SIMULATION_BROWSER,
                               email_compose_active=True, draft=draft))
            self.assertIn('exact_draft_save_receipt_and_recheck_required', result.blocked_reasons)
            self.assert_blocked(result)

    def test_positive_email_simulation_remains_disabled_and_never_echoes_content(self):
        result = self.plan(replace(SIMULATION_CANDIDATE, app_id='browser'),
                           browser=replace(SIMULATION_BROWSER, email_compose_active=True,
                                           draft=SIMULATION_DRAFT))
        self.assert_blocked(result)
        self.assertIn('live_preclose_recheck_unavailable', result.blocked_reasons)
        self.assertNotIn('exact_draft_save_receipt_and_recheck_required', result.blocked_reasons)
        self.assertNotIn(SIMULATION_DRAFT.current_content_sha256, repr(result))
        secret_label = 'https://mail.example.invalid/compose?token=SIMULATION_SECRET'
        result = self.plan(replace(SIMULATION_CANDIDATE, app_id=secret_label))
        self.assertEqual(result.app_id, 'unsupported')
        self.assertNotIn(secret_label, repr(result))

    def test_only_one_candidate_is_accepted_no_batch(self):
        for candidates in ([], [SIMULATION_CANDIDATE],
                           [SIMULATION_CANDIDATE, replace(SIMULATION_CANDIDATE, app_id='icloud')],
                           (SIMULATION_CANDIDATE,), {'app_id': 'steam'}):
            with self.assertRaisesRegex(ValueError, 'Exactly one'):
                self.plan(candidates)

    def test_invalid_clock_and_untyped_evidence_rejected(self):
        for now in (None, -1, True, '1000', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.plan(now=now)
        for override in ({'presence': {}}, {'keyboard_idle': {}}, {'presence': 'absent'},
                         {'browser': {}}):
            with self.assertRaises(ValueError):
                self.plan(**override)

    def test_source_has_only_pure_standard_library_dependencies_and_no_dispatch(self):
        tree = ast.parse(Path(app_relief.__file__).read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {'dataclasses', 'enum', 'math', 'typing'})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))
        for name in ('dispatch', 'save', 'close', 'terminate', 'capture', 'collect'):
            self.assertFalse(hasattr(app_relief, name))
        self.assertEqual(self.plan(), self.plan())


if __name__ == '__main__':
    unittest.main()
