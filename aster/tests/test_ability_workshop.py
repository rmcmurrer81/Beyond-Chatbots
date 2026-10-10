"""Real bounded-interpreter tests; no generated Python or shell is executed."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from aster.abilities import Abilities
from aster.ability_workshop import (AbilityWorkshop, FORMAT, MAX_INPUT_BYTES,
                                    MAX_OUTPUT_BYTES, WorkshopBlocked)
from aster.files import Files
from aster.storage import Store


class AbilityWorkshopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'state')
        self.files = Files(self.store)
        self.abilities = Abilities(self.store, self.files)
        self.workshop = AbilityWorkshop(self.store, self.files)

    def tearDown(self):
        self.files.close()
        self.store.close()
        self.temp.cleanup()

    def proposal(self, steps=None, supersedes=None, name='tidy', raw=None, permissions=None):
        source = raw if raw is not None else json.dumps(
            {'format': FORMAT, 'steps': steps or [{'op': 'strip'}, {'op': 'uppercase'}]}).encode()
        self.files.change('recipe.json', source)
        return self.abilities.create(name, 'recipe.json', permissions or [], supersedes)

    def run_cases(self, proposal, cases=None):
        return self.workshop.test(proposal['id'], proposal['source_sha256'],
            cases if cases is not None else [{'input': ' hello ', 'expected': 'HELLO'}])

    def approved(self, proposal, cases=None):
        receipt = self.run_cases(proposal, cases)
        review = self.workshop.review(proposal['id'], 'approved', 'Reviewed source and actual receipt',
                                      proposal['source_sha256'], receipt['id'])
        return receipt, review

    def installed(self, proposal=None, cases=None):
        proposal = proposal or self.proposal()
        receipt, review = self.approved(proposal, cases)
        status = self.workshop.install(proposal['id'], proposal['source_sha256'], review['id'])
        return proposal, receipt, review, status

    def assertBlocked(self, reason, call, *args):
        with self.assertRaises(WorkshopBlocked) as context:
            call(*args)
        self.assertEqual(context.exception.reason, reason)

    def test_full_explicit_lifecycle_and_persistent_receipts(self):
        proposal = self.proposal()
        self.assertFalse(self.workshop.get(proposal['id'])['can_run'])
        receipt, review = self.approved(proposal)
        self.assertTrue(receipt['passed'])
        self.assertTrue(receipt['tests_executed'])
        self.assertEqual(self.workshop.receipt(receipt['id']), receipt)
        self.assertEqual(self.workshop.get(proposal['id'])['status'], 'ready_to_install')
        installed = self.workshop.install(proposal['id'], proposal['source_sha256'], review['id'])
        self.assertEqual(installed['status'], 'installed')
        self.assertTrue(installed['can_run'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_runs').fetchone()[0], 0)
        plan = self.workshop.preview_run('tidy', ' second example ')
        self.assertEqual(plan['status'], 'awaiting_explicit_run')
        self.assertEqual(plan['output_text'], 'SECOND EXAMPLE')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_runs').fetchone()[0], 0)
        result = self.workshop.run(plan['id'], plan['input_sha256'])
        self.assertEqual(result['output_text'], 'SECOND EXAMPLE')
        self.assertTrue(result['recipe_interpreted'])
        self.assertFalse(result['code_executed'])
        self.assertEqual(result['external_effects'], [])
        again = AbilityWorkshop(self.store, self.files)
        self.assertEqual(again.receipt(receipt['id']), receipt)
        self.assertTrue(again.installed('tidy')['can_run'])
        self.assertEqual(again.history('tidy')['count'], 1)

    def test_all_allowlisted_operations_and_literal_replacement(self):
        proposal = self.proposal(steps=[{'op': 'strip'}, {'op': 'lowercase'},
            {'op': 'replace', 'old': '[a-z]', 'new': 'literal'}, {'op': 'prefix', 'text': '<'},
            {'op': 'suffix', 'text': '>'}, {'op': 'uppercase'}])
        cases = [{'input': ' [A-Z] ß ', 'expected': '<LITERAL SS>'},
                 {'input': '', 'expected': '<>'}, {'input': '  猫  ', 'expected': '<猫>'}]
        _, _, _, status = self.installed(proposal, cases)
        self.assertTrue(status['can_run'])
        plan = self.workshop.preview_run('tidy', ' [a-z] ')
        self.assertEqual(self.workshop.run(plan['id'], plan['input_sha256'])['output_text'], '<LITERAL>')

    def test_source_snapshot_hash_not_mutable_workspace_file(self):
        proposal, _, _, _ = self.installed()
        self.files.change('recipe.json', b'import os; os.system("arbitrary")')
        plan = self.workshop.preview_run('tidy', ' okay ')
        self.assertEqual(self.workshop.run(plan['id'], plan['input_sha256'])['output_text'], 'OKAY')
        self.assertEqual(self.workshop.get(proposal['id'])['source_sha256'], proposal['source_sha256'])

    def test_python_shell_and_generated_code_stay_inert(self):
        marker = Path(self.temp.name) / 'must-not-exist'
        for index, source in enumerate((f'from pathlib import Path\nPath({str(marker)!r}).touch()'.encode(),
                                         b'#!/bin/sh\necho unsafe', b'{"op":"eval","code":"1+1"}')):
            proposal = self.proposal(name='unsafe' + str(index), raw=source)
            self.abilities.review(proposal['id'], 'approved', 'Legacy declared review', proposal['source_sha256'])
            self.abilities.select(proposal['id'])
            self.assertBlocked('unsupported_recipe', self.run_cases, proposal)
            self.assertBlocked('unsupported_recipe', self.workshop.install,
                               proposal['id'], proposal['source_sha256'], 'fake-review')
        self.assertFalse(marker.exists())

    def test_no_network_process_or_workspace_calls_during_test_preview_run(self):
        proposal = self.proposal()
        with (patch('socket.socket', side_effect=AssertionError('Network forbidden')),
              patch('subprocess.Popen', side_effect=AssertionError('Subprocess forbidden')),
              patch('os.system', side_effect=AssertionError('Shell forbidden')),
              patch.object(self.files, 'read', side_effect=AssertionError('Runtime file reads forbidden')),
              patch.object(self.files, 'change', side_effect=AssertionError('Runtime file writes forbidden'))):
            self.installed(proposal)
            plan = self.workshop.preview_run('tidy', ' safe ')
            self.assertEqual(self.workshop.run(plan['id'], plan['input_sha256'])['output_text'], 'SAFE')

    def test_invalid_recipes_fail_closed(self):
        recipes = [b'{', b'\xff', b'{}', b'[]', b'null', b'NaN', b'Infinity', b'-Infinity',
            b'{"format":"aster.text-recipe.v1","format":"aster.text-recipe.v1","steps":[{"op":"strip"}]}',
            b'[' * 1100 + b']' * 1100, b' ' * 32769,
            json.dumps({'format': FORMAT, 'steps': []}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': 'strip'}] * 17}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': 'exec', 'code': 'print(1)'}]}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': 'replace', 'old': '', 'new': 'x'}]}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': 'strip', 'extra': 1}]}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': 'prefix', 'text': 1}]}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': 'prefix', 'text': '\ud800'}]}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': 'suffix', 'text': 'x' * 16385}]}).encode(),
            b'{"format":"aster.text-recipe.v1","steps":[{"op":"suffix","text":1e999}]}',
            json.dumps({'format': FORMAT, 'steps': [{'op': 'strip'}], 'permissions': []}).encode(),
            json.dumps({'format': FORMAT, 'steps': [{'op': ['strip']}]}).encode()]
        for index, raw in enumerate(recipes):
            with self.subTest(index=index):
                proposal = self.proposal(name='invalid' + str(index), raw=raw)
                self.assertBlocked('unsupported_recipe', self.run_cases, proposal)
                self.assertFalse(self.workshop.get(proposal['id'])['can_run'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_tests').fetchone()[0], 0)

    def test_external_permission_declarations_are_unsupported(self):
        proposal = self.proposal(permissions=['workspace.write'])
        self.assertBlocked('external_permissions_unsupported', self.run_cases, proposal)
        self.assertEqual(self.workshop.get(proposal['id'])['permissions_granted'], [])

    def test_test_case_validation_bounds_and_exact_fields(self):
        proposal = self.proposal()
        invalid = [[], {}, None, [{'input': 'x'}], [{'input': 'x', 'expected': 'X', 'extra': 1}],
                   [{'input': 1, 'expected': 'X'}], [{'input': '\ud800', 'expected': ''}],
                   [{'input': '猫' * 5462, 'expected': ''}],
                   [{'input': '', 'expected': 'x' * 32769}],
                   [{'input': '', 'expected': ''}] * 17,
                   [{'input': 'x' * 16384, 'expected': 'X' * 32768}] * 6]
        for cases in invalid:
            with self.subTest(cases_type=type(cases)), self.assertRaises(ValueError):
                self.workshop.test(proposal['id'], proposal['source_sha256'], cases)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_tests').fetchone()[0], 0)

    def test_failed_actual_tests_cannot_be_claimed_passing(self):
        proposal = self.proposal()
        receipt = self.run_cases(proposal, [{'input': 'hello', 'expected': 'WRONG'}])
        self.assertFalse(receipt['passed'])
        self.assertNotEqual(receipt['results'][0]['actual_sha256'], receipt['results'][0]['expected_sha256'])
        receipt['passed'] = True  # Mutating a returned object grants nothing.
        self.assertBlocked('tests_failed', self.workshop.review, proposal['id'], 'approved',
                           'Claim all passed', proposal['source_sha256'], receipt['id'])
        self.assertEqual(self.workshop.receipt(receipt['id'])['passed'], False)

    def test_output_expansion_fails_before_large_allocation_and_is_recorded(self):
        proposal = self.proposal(steps=[{'op': 'replace', 'old': 'x', 'new': 'y' * 16384}])
        receipt = self.run_cases(proposal, [{'input': 'x' * 16384, 'expected': ''}])
        self.assertFalse(receipt['passed'])
        self.assertEqual(receipt['results'][0]['error'], 'output_limit')
        self.installed(proposal, [{'input': 'x', 'expected': 'y' * 16384}])
        self.assertBlocked('output_limit', self.workshop.preview_run, 'tidy', 'xxx')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_plans').fetchone()[0], 0)

    def test_intermediate_output_bounds_apply_even_if_later_shrunk(self):
        proposal = self.proposal(steps=[{'op': 'prefix', 'text': ' ' * 10000},
                                      {'op': 'suffix', 'text': ' ' * 10000}, {'op': 'strip'}])
        receipt = self.run_cases(proposal, [{'input': 'a' * 13000, 'expected': 'a' * 13000}])
        self.assertEqual(receipt['results'][0]['error'], 'output_limit')

    def test_exact_limits_and_unicode_byte_accounting(self):
        proposal = self.proposal(steps=[{'op': 'suffix', 'text': 'x' * MAX_INPUT_BYTES}])
        _, _, _, status = self.installed(proposal,
            [{'input': 'x' * MAX_INPUT_BYTES, 'expected': 'x' * MAX_OUTPUT_BYTES}])
        self.assertTrue(status['can_run'])
        plan = self.workshop.preview_run('tidy', 'x' * MAX_INPUT_BYTES)
        self.assertEqual(len(self.workshop.run(plan['id'], plan['input_sha256'])['output_text']), MAX_OUTPUT_BYTES)
        with self.assertRaises(ValueError): self.workshop.preview_run('tidy', '猫' * 5462)

    def test_install_needs_latest_workshop_review_not_legacy_approval(self):
        proposal = self.proposal()
        self.assertBlocked('review_required', self.workshop.install, proposal['id'], proposal['source_sha256'], 'none')
        self.abilities.review(proposal['id'], 'approved', 'Declared legacy approval', proposal['source_sha256'])
        self.abilities.select(proposal['id'])
        self.run_cases(proposal)
        self.assertBlocked('review_required', self.workshop.install, proposal['id'], proposal['source_sha256'], 'none')
        self.assertBlocked('not_installed', self.workshop.preview_run, 'tidy', 'x')

    def test_hash_binding_source_test_review_and_run(self):
        proposal = self.proposal()
        for source_hash in ('0' * 64, None, proposal['source_sha256'].upper()):
            with self.subTest(source_hash=source_hash), self.assertRaises(ValueError):
                self.workshop.test(proposal['id'], source_hash, [{'input': 'a', 'expected': 'A'}])
        receipt, review = self.approved(proposal)
        self.assertBlocked('source_hash_mismatch', self.workshop.install, proposal['id'], '0' * 64, review['id'])
        self.assertBlocked('review_stale', self.workshop.install, proposal['id'], proposal['source_sha256'], 'other')
        other = self.proposal(name='other')
        self.assertBlocked('tests_required', self.workshop.review, other['id'], 'approved', 'Bad receipt',
                           other['source_sha256'], receipt['id'])
        self.workshop.install(proposal['id'], proposal['source_sha256'], review['id'])
        plan = self.workshop.preview_run('tidy', 'a')
        self.assertBlocked('input_hash_mismatch', self.workshop.run, plan['id'], '0' * 64)
        self.assertEqual(self.workshop.run(plan['id'], plan['input_sha256'])['output_text'], 'A')
        self.assertBlocked('run_plan_already_used', self.workshop.run, plan['id'], plan['input_sha256'])

    def test_retest_invalidates_old_review_and_installed_pointer(self):
        proposal, _, _, _ = self.installed()
        plan = self.workshop.preview_run('tidy', 'a')
        receipt = self.run_cases(proposal, [{'input': 'a', 'expected': 'WRONG'}])
        self.assertFalse(receipt['passed'])
        self.assertFalse(self.workshop.get(proposal['id'])['can_run'])
        self.assertEqual(self.workshop.installed('tidy')['status'], 'installed_blocked')
        self.assertBlocked('test_receipt_stale', self.workshop.run, plan['id'], plan['input_sha256'])

    def test_new_passing_receipt_and_approval_require_reinstallation(self):
        proposal, _, _, _ = self.installed()
        plan = self.workshop.preview_run('tidy', 'a')
        _, review = self.approved(proposal)
        self.assertBlocked('installation_stale', self.workshop.preview_run, 'tidy', 'a')
        self.workshop.install(proposal['id'], proposal['source_sha256'], review['id'])
        self.assertBlocked('run_plan_stale', self.workshop.run, plan['id'], plan['input_sha256'])
        self.assertEqual(self.workshop.history('tidy')['count'], 2)

    def test_latest_rejection_blocks_current_install_and_pending_plan(self):
        proposal, receipt, _, _ = self.installed()
        plan = self.workshop.preview_run('tidy', 'a')
        self.workshop.review(proposal['id'], 'rejected', 'Problem found', proposal['source_sha256'], receipt['id'])
        status = self.workshop.get(proposal['id'])
        self.assertEqual(status['blocked_reason'], 'review_rejected')
        self.assertFalse(status['can_run'])
        self.assertBlocked('review_rejected', self.workshop.preview_run, 'tidy', 'a')
        self.assertBlocked('review_rejected', self.workshop.run, plan['id'], plan['input_sha256'])
        self.assertEqual(self.abilities.get(proposal['id'])['review_status'], 'rejected')

    def test_legacy_rejection_cannot_be_bypassed_by_workshop_pointer(self):
        proposal, _, _, _ = self.installed()
        self.abilities.review(proposal['id'], 'rejected', 'Legacy UI revocation', proposal['source_sha256'])
        self.assertBlocked('review_rejected', self.workshop.preview_run, 'tidy', 'a')
        self.abilities.review(proposal['id'], 'approved', 'Legacy UI later approval', proposal['source_sha256'])
        self.assertBlocked('review_stale', self.workshop.preview_run, 'tidy', 'a')

    def test_latest_receipt_required_at_review(self):
        proposal = self.proposal()
        old = self.run_cases(proposal)
        new = self.run_cases(proposal)
        self.assertNotEqual(old['id'], new['id'])
        self.assertBlocked('test_receipt_stale', self.workshop.review, proposal['id'], 'approved',
                           'Old test receipt', proposal['source_sha256'], old['id'])

    def test_engine_change_invalidates_test_receipts(self):
        proposal, _, _, _ = self.installed()
        self.workshop.engine_sha256 = '0' * 64
        self.assertBlocked('test_engine_stale', self.workshop.preview_run, 'tidy', 'a')
        self.assertEqual(self.workshop.get(proposal['id'])['blocked_reason'], 'test_engine_stale')

    def test_unicode_runtime_change_invalidates_saved_test_receipts(self):
        self.installed()
        with patch('aster.ability_workshop.unicodedata.unidata_version', 'different-runtime'):
            changed_runtime = AbilityWorkshop(self.store, self.files)
        self.assertNotEqual(changed_runtime.engine_sha256, self.workshop.engine_sha256)
        self.assertBlocked('test_engine_stale', changed_runtime.preview_run, 'tidy', 'a')

    def test_version_install_and_rollback_are_audited_and_no_execution(self):
        first, _, _, _ = self.installed()
        old_plan = self.workshop.preview_run('tidy', 'A')
        second = self.proposal(steps=[{'op': 'lowercase'}], supersedes=first['id'])
        self.installed(second, [{'input': 'A', 'expected': 'a'}])
        self.assertBlocked('run_plan_stale', self.workshop.run, old_plan['id'], old_plan['input_sha256'])
        third = self.proposal(steps=[{'op': 'prefix', 'text': '!'}], supersedes=second['id'])
        self.installed(third, [{'input': 'A', 'expected': '!A'}])
        self.assertEqual(self.workshop.rollback('tidy')['id'], second['id'])
        self.assertEqual(self.workshop.rollback('tidy')['id'], first['id'])
        self.assertBlocked('no_prior_installation', self.workshop.rollback, 'tidy')
        history = self.workshop.history('tidy')
        self.assertEqual(history['count'], 5)
        self.assertEqual([r['kind'] for r in history['installations']],
                         ['rolled_back', 'rolled_back', 'installed', 'installed', 'installed'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_runs').fetchone()[0], 0)

    def test_rollback_refuses_revoked_prior_version(self):
        first, _, _, _ = self.installed()
        second = self.proposal(supersedes=first['id'])
        self.installed(second)
        self.abilities.review(first['id'], 'rejected', 'Earlier problem', first['source_sha256'])
        self.assertBlocked('review_rejected', self.workshop.rollback, 'tidy')
        self.assertEqual(self.workshop.installed('tidy')['id'], second['id'])
        self.assertEqual(self.workshop.history('tidy')['count'], 2)

    def test_current_rejection_does_not_prevent_explicit_rollback_to_safe_prior(self):
        first, _, _, _ = self.installed()
        second = self.proposal(supersedes=first['id'])
        self.installed(second)
        self.workshop.review(second['id'], 'rejected', 'New version regression', second['source_sha256'])
        self.assertEqual(self.workshop.rollback('tidy')['id'], first['id'])
        self.assertTrue(self.workshop.installed('tidy')['can_run'])

    def test_histories_reject_update_and_delete(self):
        self.installed()
        plan = self.workshop.preview_run('tidy', 'a')
        self.workshop.run(plan['id'], plan['input_sha256'])
        for table in ('workshop_tests', 'workshop_reviews', 'workshop_installations', 'workshop_plans', 'workshop_runs'):
            for operation in ('UPDATE ' + table + ' SET at=0', 'DELETE FROM ' + table):
                with self.subTest(operation=operation), self.assertRaises(sqlite3.IntegrityError):
                    with self.store.db: self.store.db.execute(operation)

    def test_failed_audit_rolls_back_run_and_preserves_single_use_plan(self):
        self.installed()
        plan = self.workshop.preview_run('tidy', 'private input')
        event = self.store.event
        def fail_run(kind, payload):
            if kind == 'workshop.ran':
                raise sqlite3.OperationalError('private exception detail')
            return event(kind, payload)
        with patch.object(self.store, 'event', side_effect=fail_run), self.assertRaises(sqlite3.OperationalError):
            self.workshop.run(plan['id'], plan['input_sha256'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_runs').fetchone()[0], 0)
        self.assertEqual(self.store.rows('events')[0]['kind'], 'workshop.failed')
        self.assertNotIn('private', self.store.rows('events')[0]['payload'])
        self.assertEqual(self.workshop.run(plan['id'], plan['input_sha256'])['output_text'], 'PRIVATE INPUT')

    def test_failed_test_audit_leaves_no_receipt(self):
        proposal = self.proposal()
        event = self.store.event
        def fail_test(kind, payload):
            if kind == 'workshop.tested': raise sqlite3.OperationalError('simulated failure')
            return event(kind, payload)
        with patch.object(self.store, 'event', side_effect=fail_test), self.assertRaises(sqlite3.OperationalError):
            self.run_cases(proposal)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_tests').fetchone()[0], 0)

    def test_receipts_and_general_history_omit_inputs_outputs_and_review_notes(self):
        proposal = self.proposal()
        secret = 'private-data-72c6'
        receipt = self.run_cases(proposal, [{'input': secret, 'expected': secret.upper()}])
        review = self.workshop.review(proposal['id'], 'approved', 'private review note',
                                      proposal['source_sha256'], receipt['id'])
        self.workshop.install(proposal['id'], proposal['source_sha256'], review['id'])
        plan = self.workshop.preview_run('tidy', secret)
        self.workshop.run(plan['id'], plan['input_sha256'])
        for value in (receipt, self.workshop.history('tidy'), self.workshop.get(proposal['id']),
                      self.workshop.status(), self.store.rows('events')):
            serialized = json.dumps(value)
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret.upper(), serialized)
            self.assertNotIn('private review note', serialized)

    def test_status_reports_limits_and_unsupported_capabilities_precisely(self):
        status = self.workshop.status()
        self.assertEqual(status['capabilities']['python_execution'], 'unsupported')
        self.assertEqual(status['capabilities']['file_writes'], 'unsupported')
        self.assertEqual(status['capabilities']['os_sandbox'], 'unavailable')
        self.assertIsNone(status['limits']['wall_clock_timeout'])
        self.assertIn('unicode_version', status['engine'])
        self.assertIn('python_version', status['engine'])
        self.assertEqual(self.workshop.installed('unknown')['status'], 'not_installed')
        proposal, _, _, _ = self.installed()
        self.assertEqual(self.workshop.status()['installed'][0]['id'], proposal['id'])
        self.assertEqual(len(self.workshop.list()), 1)

    def test_real_store_reopen_retains_installation_and_pending_plan(self):
        proposal, receipt, _, _ = self.installed()
        plan = self.workshop.preview_run('tidy', ' resumed ')
        root = self.store.root
        self.files.close()
        self.store.close()
        self.store = Store(root)
        self.files = Files(self.store)
        self.abilities = Abilities(self.store, self.files)
        self.workshop = AbilityWorkshop(self.store, self.files)
        self.assertEqual(self.workshop.receipt(receipt['id']), receipt)
        self.assertEqual(self.workshop.installed('tidy')['id'], proposal['id'])
        self.assertEqual(self.workshop.run(plan['id'], plan['input_sha256'])['output_text'], 'RESUMED')

    def test_corrupt_test_receipt_fails_closed(self):
        proposal, receipt, _, _ = self.installed()
        # Simulate corrupt trusted storage; removing SQL protections is never an API action.
        with self.store.db:
            self.store.db.execute('DROP TRIGGER workshop_tests_no_update')
            self.store.db.execute("UPDATE workshop_tests SET results='[]' WHERE id=?", (receipt['id'],))
        self.assertBlocked('test_receipt_integrity_failed', self.workshop.preview_run, 'tidy', 'a')
        self.assertFalse(self.workshop.get(proposal['id'])['can_run'])

    def test_corrupt_source_and_plan_fail_closed(self):
        proposal, _, _, _ = self.installed()
        plan = self.workshop.preview_run('tidy', 'a')
        with self.store.db:
            self.store.db.execute('DROP TRIGGER workshop_plans_no_update')
            self.store.db.execute("UPDATE workshop_plans SET output_text='WRONG' WHERE id=?", (plan['id'],))
        self.assertBlocked('run_plan_integrity_failed', self.workshop.run, plan['id'], plan['input_sha256'])
        with self.store.db:
            self.store.db.execute('DROP TRIGGER ability_proposals_no_update')
            self.store.db.execute('UPDATE ability_proposals SET source=? WHERE id=?', (b'{}', proposal['id']))
        self.assertBlocked('source_integrity_failed', self.workshop.get, proposal['id'])

    def test_install_transaction_failure_keeps_prior_pointer(self):
        first, _, _, _ = self.installed()
        second = self.proposal(supersedes=first['id'])
        _, review = self.approved(second)
        event = self.store.event
        def fail_install(kind, payload):
            if kind == 'workshop.installed': raise sqlite3.OperationalError('simulated failure')
            return event(kind, payload)
        with patch.object(self.store, 'event', side_effect=fail_install), self.assertRaises(sqlite3.OperationalError):
            self.workshop.install(second['id'], second['source_sha256'], review['id'])
        self.assertEqual(self.workshop.installed('tidy')['id'], first['id'])
        self.assertEqual(self.workshop.history('tidy')['count'], 1)

    def test_source_inspection_returns_exact_snapshot_even_after_rejection(self):
        source = b'{ "format": "aster.text-recipe.v1", "steps": [{"op": "strip"}] }\n'
        proposal = self.proposal(raw=source)
        self.files.change('recipe.json', b'changed source file')
        self.workshop.review(proposal['id'], 'rejected', 'Inspect before deciding again', proposal['source_sha256'])
        inspected = self.workshop.source(proposal['id'])
        self.assertEqual(inspected['source_text'], source.decode('utf-8'))
        self.assertEqual(inspected['source_sha256'], hashlib.sha256(source).hexdigest())
        self.assertEqual(inspected['source_bytes'], len(source))
        self.assertTrue(inspected['utf8_valid'])
        self.assertTrue(inspected['recipe_supported'])
        self.assertEqual(inspected['recipe'], json.loads(source))
        self.assertEqual(inspected['status'], 'supported_recipe')
        self.assertIsNone(inspected['unsupported_reason'])
        self.assertFalse(self.workshop.get(proposal['id'])['can_run'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_tests').fetchone()[0], 0)

    def test_source_inspection_invalid_utf8_is_explicit_and_bounded(self):
        proposal = self.proposal(raw=b'\x00\xff\xfe')
        inspected = self.workshop.source(proposal['id'])
        self.assertEqual(inspected['source_sha256'], proposal['source_sha256'])
        self.assertEqual(inspected['source_bytes'], 3)
        self.assertIsNone(inspected['source_text'])
        self.assertIsNone(inspected['recipe'])
        self.assertFalse(inspected['utf8_valid'])
        self.assertFalse(inspected['recipe_supported'])
        self.assertEqual(inspected['unsupported_reason'], 'invalid_utf8')
        self.assertEqual(inspected['status'], 'unsupported_source')
        large = self.proposal(raw=b'x' * 262144, name='large')
        inspected = self.workshop.source(large['id'])
        self.assertEqual(len(inspected['source_text']), 262144)
        self.assertTrue(inspected['utf8_valid'])
        self.assertEqual(inspected['unsupported_reason'], 'unsupported_recipe')

    def test_source_inspection_does_not_execute_program_or_transform(self):
        marker_path = Path(self.temp.name) / 'not-created-by-inspection'
        source = f'from pathlib import Path\nPath({str(marker_path)!r}).touch()\n'.encode()
        proposal = self.proposal(raw=source)
        with (patch('socket.socket', side_effect=AssertionError('No network')),
              patch('subprocess.Popen', side_effect=AssertionError('No subprocess')),
              patch.object(self.files, 'read', side_effect=AssertionError('No workspace read')),
              patch('aster.ability_workshop._transform', side_effect=AssertionError('No interpretation'))):
            inspected = self.workshop.source(proposal['id'])
        self.assertEqual(inspected['source_text'], source.decode())
        self.assertFalse(inspected['recipe_supported'])
        self.assertEqual(inspected['unsupported_reason'], 'unsupported_recipe')
        self.assertFalse(inspected['python_execution_enabled'])
        self.assertFalse(inspected['shell_execution_enabled'])
        self.assertFalse(marker_path.exists())
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_plans').fetchone()[0], 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM workshop_runs').fetchone()[0], 0)

    def test_source_inspection_does_not_turn_declared_permissions_into_authority(self):
        proposal = self.proposal(permissions=['workspace.write'])
        inspected = self.workshop.source(proposal['id'])
        self.assertTrue(inspected['utf8_valid'])
        self.assertFalse(inspected['recipe_supported'])
        self.assertEqual(inspected['unsupported_reason'], 'external_permissions_unsupported')
        self.assertIsNone(inspected['recipe'])
        self.assertEqual(inspected['permissions_granted'], [])

    def test_duplicate_install_unknown_ids_and_invalid_names(self):
        proposal, _, review, _ = self.installed()
        self.assertBlocked('already_installed', self.workshop.install, proposal['id'], proposal['source_sha256'], review['id'])
        self.assertBlocked('unknown_test_receipt', self.workshop.receipt, 'missing')
        self.assertBlocked('unknown_run_plan', self.workshop.run, 'missing', '0' * 64)
        for operation in (self.workshop.get, self.workshop.history, self.workshop.installed):
            with self.subTest(operation=operation), self.assertRaises(ValueError): operation('../bad')

    def test_review_validation_and_missing_hashes(self):
        proposal = self.proposal()
        receipt = self.run_cases(proposal)
        for verdict, note, digest in (('passed', 'note', proposal['source_sha256']),
                ('approved', '', proposal['source_sha256']), ('approved', 'x' * 2049, proposal['source_sha256']),
                ('approved', 'note', None), ('approved', 'note', '0' * 64)):
            with self.subTest(verdict=verdict), self.assertRaises(ValueError):
                self.workshop.review(proposal['id'], verdict, note, digest, receipt['id'])
        self.assertBlocked('test_receipt_stale', self.workshop.review, proposal['id'], 'rejected',
                           'Reject unrelated receipt', proposal['source_sha256'], 'missing')
        review = self.workshop.review(proposal['id'], 'rejected', 'No tests required to reject', proposal['source_sha256'])
        self.assertEqual(review['verdict'], 'rejected')


if __name__ == '__main__':
    unittest.main()
