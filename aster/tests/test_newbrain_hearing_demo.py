"""Durable CLI orchestration tests; mocked model runs are not runtime evidence.

The exact CPython 3.14.4 workflow must separately smoke-test real run/recheck.
No test here bypasses or changes the original source's interpreter guard.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.newbrain_hearing import demo, pipeline, source


class HearingDemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.state = self.parent / 'synthetic-hearing'

    def command(self, command, state=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = demo.main([command, '--state', str(state or self.state)])
        return code, json.loads(output.getvalue())

    def snapshot(self, root=None):
        root = root or self.state
        return {path.relative_to(root).as_posix(): ('directory' if path.is_dir() else path.read_bytes())
                for path in root.rglob('*')}

    def fake_pipeline(self, work, report):
        # Real source verification/staging, deliberately fake synthetic model
        # bytes. This only tests durable CLI mechanics on unsupported hosts.
        for experiment, role in demo.ROLES:
            source.stage(work / f'{experiment}-{role}', experiment, role)
        for relative in demo.DATA_LIMITS:
            if relative == 'run-report.json':
                continue
            path = work.parent / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"synthetic_test_only":true}')
        report.update(status='PASSED', executed=True, processes=[], arms=[{
            'arm': arm, 'old_decision_rows_equal': 24, 'new_teachings': 0,
            'complete_decision_state_unchanged': True,
            'initial_score': {'totals': {}}, 'fresh_score': {'totals': {}}}
            for arm in pipeline.ARMS])

    def create_state(self):
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline, 'run', side_effect=self.fake_pipeline):
            code, result = self.command('run')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['success'])
        return result

    def edit_receipt(self, update):
        path = self.state / 'receipt.json'
        value = json.loads(path.read_text())
        update(value)
        path.write_text(json.dumps(value))

    def fake_retention(self, role, entry, arguments, work, records):
        output = Path(arguments['output-dir'])
        output.mkdir()
        arm = arguments['arm']
        records.append({'entry': entry, 'arm': arm, 'exit_code': 0})
        if entry == 'retention_consumer.py':
            self.assertEqual(role, self.state / 'work/211-staged_blind')
            for field in ('model', 'input', 'pcm'):
                self.assertEqual(source.digest(arguments[field]), arguments['expected-' + field + '-sha256'])
            value = {'schema': 'newbrain.complete-decision-retention211.v1', 'arm': arm,
                     'original_model_sha256': arguments['expected-model-sha256'],
                     'new_training_calls': 0, 'old_parity_count': 24, 'new_nuisance_count': 24,
                     'decision_fingerprints': ['a' * 64] * 3}
            demo.new_json(output/'RETENTION-REPORT.json', value)
        elif entry == 'retention_labels.py':
            self.assertEqual(role, self.state / 'work/211-staged_labels')
            for field in ('original-report', 'retention-report', 'new-gold'):
                self.assertEqual(source.digest(arguments[field]), arguments['expected-' + field + '-sha256'])
            value = {'schema': 'newbrain.independent-retention-results211.v1', 'arm': arm,
                     'new_training_calls': 0,
                     'old_parity': {'examples': 24, 'complete_decision_rows_equal': 24},
                     'fresh24': {'totals': {'correct': 12, 'examples': 24}}}
            demo.new_json(output/'RETENTION-SCORES.json', value)
        else:
            self.fail('Recheck called a training or producer entry: ' + entry)
        demo.new_json(output/'ENTRY-RESULT.json', {'test_mock': True})
        return output

    def assert_recheck_refused_without_write(self):
        before = self.snapshot()
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline, 'run') as training, patch.object(pipeline, 'invoke') as invoke:
            code, result = self.command('recheck')
        self.assertEqual(code, 1, result)
        self.assertFalse(result['success'])
        training.assert_not_called()
        invoke.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_wrong_runtime_run_refuses_before_filesystem_or_source_access(self):
        with patch.object(pipeline, 'exact_runtime', return_value=False), \
                patch.object(source, 'verify') as verify, patch.object(demo, 'state_path') as paths:
            code, result = self.command('run')
        self.assertEqual(code, 2)
        self.assertEqual(result['status'], 'UNAVAILABLE_EXACT_RUNTIME_REQUIRED')
        verify.assert_not_called()
        paths.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_wrong_runtime_recheck_does_not_write_existing_state(self):
        self.create_state()
        before = self.snapshot()
        with patch.object(pipeline, 'exact_runtime', return_value=False):
            code, result = self.command('recheck')
        self.assertEqual(code, 2)
        self.assertFalse(result['executed'])
        self.assertEqual(before, self.snapshot())

    def test_run_persists_verified_fresh_state_and_exact_sources(self):
        self.create_state()
        receipt, report = demo.verify_state(self.state)
        self.assertEqual(set(receipt['files']), set(demo.DATA_LIMITS))
        self.assertEqual(receipt['source_commit'], source.PIN)
        self.assertEqual(len(report['pipeline']['arms']), 6)
        self.assertEqual(receipt['isolation'], 'Process isolation, not an OS sandbox.')
        self.assertFalse(report['production_backend_activated'])

    def test_inspect_is_read_only_on_unsupported_runtime(self):
        self.create_state()
        before = self.snapshot()
        with patch.object(pipeline, 'exact_runtime', return_value=False), \
                patch.object(pipeline, 'run') as training, patch.object(pipeline, 'invoke') as invoke:
            code, result = self.command('inspect')
        self.assertEqual(code, 0, result)
        self.assertFalse(result['executed'])
        self.assertTrue(result['saved_bytes_verified'])
        training.assert_not_called()
        invoke.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_duplicate_run_is_refused_without_overwriting(self):
        self.create_state()
        before = self.snapshot()
        with patch.object(pipeline, 'exact_runtime', return_value=True), patch.object(pipeline, 'run') as run:
            code, result = self.command('run')
        self.assertEqual(code, 1, result)
        self.assertIn('already exists', result['error'])
        run.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_empty_existing_directory_is_not_adopted(self):
        self.state.mkdir()
        with patch.object(pipeline, 'exact_runtime', return_value=True):
            code, _ = self.command('run')
        self.assertEqual(code, 1)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_production_state_and_descendants_are_refused(self):
        production = self.parent/'.aster-state'
        production.mkdir()
        for path in (production, production/'hearing'):
            with self.subTest(path=path), patch.object(pipeline, 'exact_runtime', return_value=True):
                code, result = self.command('run', path)
            self.assertEqual(code, 1)
            self.assertIn('outside .aster-state', result['error'])
        self.assertEqual(list(production.iterdir()), [])

    def test_bad_vendor_is_refused_before_state_is_created(self):
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(source, 'verify', side_effect=ValueError('changed source')):
            code, result = self.command('run')
        self.assertEqual(code, 1, result)
        self.assertFalse(self.state.exists())

    def test_missing_receipt_is_refused(self):
        self.create_state()
        (self.state/'receipt.json').unlink()
        self.assert_recheck_refused_without_write()

    def test_malformed_receipts_are_refused(self):
        self.create_state()
        path = self.state/'receipt.json'
        original = path.read_bytes()
        for value in (b'{', b'[]', b'null', b'{"schema":1,"schema":2}', b'{"bad":NaN}'):
            with self.subTest(value=value):
                path.write_bytes(value)
                self.assert_recheck_refused_without_write()
        path.write_bytes(original)

    def test_unknown_schema_fields_and_wrong_scope_are_refused(self):
        self.create_state()
        path = self.state/'receipt.json'
        original = path.read_bytes()
        for field, value in (('unexpected', True), ('schema', 'other'), ('owner', 'upstream'),
                             ('source_commit', '0'*40), ('source_manifest_sha256', '0'*64),
                             ('runtime', {'implementation': 'CPython', 'version': '3.12'}),
                             ('arms', ['LEARNED']), ('created_utc', '2026-01-01'),
                             ('isolation', 'OS sandbox')):
            with self.subTest(field=field):
                path.write_bytes(original)
                self.edit_receipt(lambda receipt: receipt.update({field: value}))
                self.assert_recheck_refused_without_write()

    def test_receipt_paths_are_a_fixed_whitelist(self):
        self.create_state()
        path = self.state/'receipt.json'
        original = path.read_bytes()
        for bad in ('../outside.json', '/tmp/outside.json', 'work/../receipt.json', 'work/unknown.json'):
            with self.subTest(path=bad):
                path.write_bytes(original)
                self.edit_receipt(lambda receipt: receipt['files'].update({bad: {'bytes': 0, 'sha256': '0'*64}}))
                self.assert_recheck_refused_without_write()

    def test_receipt_byte_metadata_is_strict_and_bounded(self):
        self.create_state()
        path = self.state/'receipt.json'
        original = path.read_bytes()
        for value in ({'bytes': True, 'sha256': '0'*64}, {'bytes': -1, 'sha256': '0'*64},
                      {'bytes': 999999999, 'sha256': '0'*64}, {'bytes': 0, 'sha256': '../unsafe'},
                      {'bytes': 0, 'sha256': '0'*64, 'extra': True}):
            with self.subTest(value=value):
                path.write_bytes(original)
                self.edit_receipt(lambda receipt: receipt['files'].update({'work/arm-LEARNED/MODEL.private.json': value}))
                self.assert_recheck_refused_without_write()

    def test_receipt_size_is_capped_before_json_parse(self):
        self.create_state()
        (self.state/'receipt.json').write_bytes(b' ' * (demo.RECEIPT_LIMIT + 1))
        self.assert_recheck_refused_without_write()

    def test_saved_model_and_query_tampering_is_refused(self):
        self.create_state()
        for name in ('work/arm-LEARNED/MODEL.private.json', 'work/query-producer/QUERY-PCM.bin',
                     'work/query-producer/QUERY-INPUT.json', 'work/query-producer/NEW-GOLD.private.json',
                     'work/arm-DSP/ARM-REPORT.json', 'run-report.json'):
            with self.subTest(name=name):
                path = self.state/name
                original = path.read_bytes()
                path.write_bytes(original+b' ')
                self.assert_recheck_refused_without_write()
                path.write_bytes(original)

    def test_missing_saved_bytes_are_not_regenerated(self):
        self.create_state()
        (self.state/'work/arm-RAW_LEARNED/MODEL.private.json').unlink()
        self.assert_recheck_refused_without_write()

    def test_oversized_saved_model_is_refused(self):
        self.create_state()
        (self.state/'work/arm-LEARNED/MODEL.private.json').write_bytes(b'0' * 8193)
        self.assert_recheck_refused_without_write()

    def test_source_change_cannot_be_blessed_by_editing_receipt(self):
        self.create_state()
        relative = 'work/211-staged_blind/retention_consumer.py'
        path = self.state/relative
        path.write_bytes(path.read_bytes()+b'\n# altered\n')
        self.edit_receipt(lambda receipt: receipt['role_source'].update({relative: demo.metadata(path.read_bytes())}))
        self.assert_recheck_refused_without_write()

    def test_missing_or_additional_source_is_refused(self):
        self.create_state()
        path = self.state/'work/211-staged_blind/extra.py'
        path.write_bytes(b'')
        self.assert_recheck_refused_without_write()
        path.unlink()
        (self.state/'work/211-staged_blind/retention_consumer.py').unlink()
        self.assert_recheck_refused_without_write()

    def make_symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest('Host cannot create test symlinks: ' + str(error))

    def test_symlink_state_root_or_ancestor_is_refused(self):
        self.create_state()
        link = self.parent/'linked-state'
        self.make_symlink(link, self.state, True)
        before = self.snapshot()
        code, result = self.command('inspect', link)
        self.assertEqual(code, 1, result)
        alias = self.parent/'alias'
        self.make_symlink(alias, self.parent, True)
        with patch.object(pipeline, 'exact_runtime', return_value=True):
            code, result = self.command('run', alias/'new-run')
        self.assertEqual(code, 1, result)
        self.assertFalse((self.parent/'new-run').exists())
        self.assertEqual(before, self.snapshot())

    def test_symlink_saved_model_is_refused(self):
        self.create_state()
        path = self.state/'work/arm-LEARNED/MODEL.private.json'
        target = self.parent/'model.json'
        path.rename(target)
        self.make_symlink(path, target)
        self.assert_recheck_refused_without_write()

    def test_hardlinked_receipt_or_input_is_refused(self):
        self.create_state()
        for index, relative in enumerate(('receipt.json', 'work/arm-LEARNED/MODEL.private.json')):
            target = self.parent/f'hardlink-{index}'
            try:
                os.link(self.state/relative, target)
            except OSError as error:
                self.skipTest('Host cannot create test hard links: ' + str(error))
            self.assert_recheck_refused_without_write()
            target.unlink()

    def test_reparse_marker_is_refused(self):
        info = SimpleNamespace(st_mode=0o100600, st_nlink=1, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=info):
            with self.assertRaisesRegex(ValueError, 'plain owned'):
                demo.check_node(self.parent/'pretend-reparse', False)

    def test_recheck_uses_saved_bytes_for_all_six_arms_and_never_retrains(self):
        self.create_state()
        original = self.snapshot()
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline, 'run') as training, \
                patch.object(pipeline, 'invoke', side_effect=self.fake_retention) as invoke:
            first_code, first = self.command('recheck')
            second_code, second = self.command('recheck')
        self.assertEqual((first_code, second_code), (0, 0), (first, second))
        training.assert_not_called()
        self.assertEqual(invoke.call_count, 24)
        self.assertNotEqual(first['report'], second['report'])
        for result in (first, second):
            report = json.loads(Path(result['report']).read_text())
            self.assertEqual([item['arm'] for item in report['arms']], list(pipeline.ARMS))
            self.assertFalse(report['retrained'])
            self.assertEqual(len(report['processes']), 12)
        after = self.snapshot()
        self.assertEqual(original, {key: value for key, value in after.items()
                                    if key != 'rechecks' and not key.startswith('rechecks/')} )

    def test_failed_recheck_preserves_subprocess_evidence_without_false_success(self):
        self.create_state()
        original = self.snapshot()
        failed = SimpleNamespace(returncode=7, stdout=b'fixture-output', stderr=b'LOCAL-DIAGNOSTIC')
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline.subprocess, 'run', return_value=failed):
            code, result = self.command('recheck')
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'FAILED')
        report_path = Path(result['report'])
        report = json.loads(report_path.read_text())
        self.assertFalse(report['success'])
        self.assertEqual(report['processes'][0]['exit_code'], 7)
        self.assertEqual((report_path.parent/'stage-1.stderr').read_bytes(), b'LOCAL-DIAGNOSTIC')
        self.assertNotIn('LOCAL-DIAGNOSTIC', report_path.read_text())
        for key, value in original.items():
            self.assertEqual(self.snapshot()[key], value)

    def test_failed_run_preserves_report_and_diagnostics_without_receipt(self):
        def fail(work, report):
            report.update(status='RUNNING', executed=True, processes=[], arms=[])
            pipeline.invoke(work, 'producer.py', {'output-dir': work/'producer'}, work, report['processes'])
        failed = SimpleNamespace(returncode=5, stdout=b'', stderr=b'LOCAL-RUN-FAILURE')
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline, 'run', side_effect=fail), \
                patch.object(pipeline.subprocess, 'run', return_value=failed):
            code, result = self.command('run')
        self.assertEqual(code, 1)
        self.assertFalse(result['success'])
        report = json.loads((self.state/'run-report.json').read_text())
        self.assertFalse(report['success'])
        self.assertEqual(report['pipeline']['status'], 'FAILED')
        self.assertEqual(report['pipeline']['processes'][0]['exit_code'], 5)
        self.assertEqual((self.state/'work/stage-1.stderr').read_bytes(), b'LOCAL-RUN-FAILURE')
        self.assertFalse((self.state/'receipt.json').exists())
        self.assert_recheck_refused_without_write()

    def test_skipped_or_incomplete_pipeline_is_not_success(self):
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline, 'run', side_effect=lambda work, report: report.update(status='SKIPPED', executed=False)):
            code, result = self.command('run')
        self.assertEqual(code, 1, result)
        self.assertFalse((self.state/'receipt.json').exists())
        self.assertFalse(json.loads((self.state/'run-report.json').read_text())['success'])

    def test_zero_exit_without_complete_result_is_not_success(self):
        self.create_state()
        completed = SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline.subprocess, 'run', return_value=completed):
            code, result = self.command('recheck')
        self.assertEqual(code, 1)
        report = json.loads(Path(result['report']).read_text())
        self.assertFalse(report['success'])
        self.assertEqual(report['processes'][0]['exit_code'], 0)
        self.assertEqual(report['arms'], [])

    def test_subprocess_timeout_is_retained_as_failure(self):
        self.create_state()
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline.subprocess, 'run', side_effect=subprocess.TimeoutExpired('test-command', 45)):
            code, result = self.command('recheck')
        self.assertEqual(code, 1)
        report = json.loads(Path(result['report']).read_text())
        self.assertFalse(report['success'])
        self.assertTrue(report['processes'][0]['timed_out'])
        self.assertIsNone(report['processes'][0]['exit_code'])

    def test_mutation_during_recheck_fails_final_saved_byte_verification(self):
        self.create_state()
        def mutate_after_last_score(*args):
            output = self.fake_retention(*args)
            if args[1] == 'retention_labels.py' and args[2]['arm'] == pipeline.ARMS[-1]:
                path = self.state/'work/arm-LEARNED/MODEL.private.json'
                path.write_bytes(path.read_bytes()+b' ')
            return output
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline, 'invoke', side_effect=mutate_after_last_score):
            code, result = self.command('recheck')
        self.assertEqual(code, 1)
        self.assertFalse(result['success'])
        self.assertEqual(len(result['arms']), 6)

    def test_symlink_work_directory_is_refused_before_source_listing(self):
        self.create_state()
        path = self.state/'work'
        target = self.parent/'moved-work'
        path.rename(target)
        self.make_symlink(path, target, True)
        with patch.object(pipeline, 'exact_runtime', return_value=True), patch.object(pipeline, 'invoke') as invoke:
            code, result = self.command('recheck')
        self.assertEqual(code, 1, result)
        invoke.assert_not_called()
        self.assertFalse((self.state/'rechecks').exists())

    def test_parity_failure_in_successful_process_output_is_not_a_pass(self):
        self.create_state()
        def wrong_parity(*args):
            output = self.fake_retention(*args)
            if args[1] == 'retention_labels.py':
                path = output/'RETENTION-SCORES.json'
                value = json.loads(path.read_text())
                value['old_parity']['complete_decision_rows_equal'] = 23
                path.write_text(json.dumps(value))
            return output
        with patch.object(pipeline, 'exact_runtime', return_value=True), \
                patch.object(pipeline, 'invoke', side_effect=wrong_parity):
            code, result = self.command('recheck')
        self.assertEqual(code, 1)
        self.assertFalse(result['success'])
        self.assertEqual(result['arms'], [])


if __name__ == '__main__':
    unittest.main()
