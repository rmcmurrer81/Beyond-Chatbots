"""Dependency-free admission/CLI and exact pure-source interface fixtures.

The fixed-086 method/probe fixtures below intentionally use its original
10720-update/42-way ABI. They are NOT Aster training, actual exposure counters,
or learning evidence. Real decoder/lifecycle checks live in the opt-in lab.
"""
import ast
import contextlib
import io
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.newbrain_text import source


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = hashlib.sha256(b'fixed-086-pure-interface-fixture-only').hexdigest()


def pure_module(filename):
    """Execute verified stdlib-only policy/codec source, never the decoder."""
    admitted = source.inspect_sources()
    matches = [record for record in admitted['files'] if Path(record['path']).name == filename]
    if len(matches) != 1 or filename not in ('method_order.py', 'probe_ledger.py'):
        raise AssertionError('Only one reviewed pure source module may be loaded')
    raw = (source.source_root() / matches[0]['path']).read_bytes()
    module = ModuleType('test_fixed086_' + filename[:-3])
    exec(compile(raw, 'fixed086-fixture/' + filename, 'exec'), module.__dict__)
    return module


class TextSourceTests(unittest.TestCase):
    def copy_source(self, directory):
        target = Path(directory) / 'source'
        shutil.copytree(source.source_root(), target)
        return target

    def test_three_exact_modules_and_no_production_activation(self):
        before = set(sys.modules)
        result = source.inspect_sources()
        self.assertEqual(result['upstream_commit'], '4a5c8396f820d8caf81b9ccba850617ae9e60489')
        self.assertEqual({Path(row['path']).name for row in result['files']},
                         {'dialogue_decoder.py', 'method_order.py', 'probe_ledger.py', 'THIRD_PARTY_NOTICES.md'})
        self.assertFalse(result['production_backend_enabled'])
        self.assertFalse(result['runtime_executed'])
        self.assertNotIn('numpy', set(sys.modules) - before)
        for row in result['files']:
            raw = (source.source_root() / row['path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
            self.assertEqual(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(), row['git_blob'])

    def test_byte_tampering_refused_without_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_source(directory)
            path = next(root.rglob('dialogue_decoder.py'))
            value = bytearray(path.read_bytes()); value[-1] ^= 1
            path.write_bytes(value)
            with patch.object(source, 'runtime_info', side_effect=AssertionError('runtime imported')):
                with self.assertRaisesRegex(source.SourceError, 'source_digest_mismatch'):
                    source.inspect_sources(root)

    def test_missing_and_symlinked_selected_sources_refused(self):
        for kind in ('missing', 'symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = self.copy_source(directory)
                path = next(root.rglob('method_order.py'))
                saved = Path(directory) / 'saved.py'
                saved.write_bytes(path.read_bytes())
                path.unlink()
                if kind == 'symlink':
                    path.symlink_to(saved)
                with self.assertRaises(source.SourceError):
                    source.inspect_sources(root)

    def test_extra_unlisted_source_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_source(directory)
            (root / 'unreviewed.py').write_text('raise RuntimeError("must not run")')
            with self.assertRaises(source.SourceError):
                source.inspect_sources(root)

    def test_symlinked_vendor_ancestor_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_source(directory)
            link = Path(directory) / 'link'
            link.symlink_to(root.parent, target_is_directory=True)
            with self.assertRaises(source.SourceError): source.inspect_sources(link / root.name)

    def test_manifest_tampering_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_source(directory)
            manifest = root / 'manifest.json'
            value = json.loads(manifest.read_bytes())
            value['production_backend_enabled'] = True
            manifest.write_text(json.dumps(value))
            with self.assertRaisesRegex(source.SourceError, 'source_manifest_mismatch'):
                source.inspect_sources(root)

    def test_only_two_exact_cpython_versions_accept_exact_numpy(self):
        # These are gate fixtures, not claims that this process ran on both
        # interpreters. Each actual interpreter/platform has its own CI run.
        self.assertEqual(source.PYTHON_VERSIONS, ('3.12.14', '3.14.4'))
        self.assertEqual(source.PYTHON_VERSION, '3.12.14')
        for version in ('3.12.14', '3.14.4'):
            with self.subTest(version=version), \
                 patch.object(source.platform, 'python_version', return_value=version), \
                 patch.object(source.platform, 'python_implementation', return_value='CPython'), \
                 patch.dict(sys.modules, {'numpy': SimpleNamespace(__version__='2.3.5')}):
                result = source.runtime_info()
                self.assertEqual(result['python'], version)
                self.assertEqual(result['implementation'], 'CPython')
                self.assertEqual(result['numpy'], '2.3.5')

    def test_nonmatching_interpreter_refused_before_optional_import(self):
        unsupported = ('3.12.13', '3.12.15', '3.13.4', '3.14.3', '3.14.5', '3.14.4rc1', '3.15.0')
        for version in unsupported:
            with self.subTest(version=version), \
                 patch.object(source.platform, 'python_version', return_value=version), \
                 patch.object(source.platform, 'python_implementation', return_value='CPython'), \
                 patch.dict(sys.modules, {'numpy': None}):
                with self.assertRaisesRegex(source.SourceError, 'requires_cpython_'):
                    source.runtime_info()
        for version in ('3.12.14', '3.14.4'):
            with self.subTest(non_cpython=version), \
                 patch.object(source.platform, 'python_version', return_value=version), \
                 patch.object(source.platform, 'python_implementation', return_value='PyPy'), \
                 patch.dict(sys.modules, {'numpy': None}):
                with self.assertRaisesRegex(source.SourceError, 'requires_cpython_'):
                    source.runtime_info()

    def test_optional_numpy_missing_or_wrong_version_is_refused(self):
        for version in ('3.12.14', '3.14.4'):
            with self.subTest(python=version), \
                 patch.object(source.platform, 'python_version', return_value=version), \
                 patch.object(source.platform, 'python_implementation', return_value='CPython'):
                with patch.dict(sys.modules, {'numpy': None}):
                    with self.assertRaisesRegex(source.SourceError, 'optional_numpy_unavailable'):
                        source.runtime_info()
                for numpy_version in ('2.3.4', '2.3.6', '2.3.5rc1', '0.0.invalid'):
                    with self.subTest(numpy=numpy_version), \
                         patch.dict(sys.modules, {'numpy': SimpleNamespace(__version__=numpy_version)}):
                        with self.assertRaisesRegex(source.SourceError, 'requires_numpy_2.3.5'):
                            source.runtime_info()

    def test_load_checks_source_then_runtime_before_executing(self):
        with patch.object(source, 'inspect_sources', side_effect=source.SourceError('source_digest_mismatch')), \
             patch.object(source, 'runtime_info', side_effect=AssertionError('runtime ran')):
            with self.assertRaisesRegex(source.SourceError, 'source_digest_mismatch'):
                source.load_modules()
        with patch.object(source, 'runtime_info', side_effect=source.SourceError('optional_numpy_unavailable')), \
             patch.object(source, 'ModuleType', side_effect=AssertionError('module executed')):
            with self.assertRaisesRegex(source.SourceError, 'optional_numpy_unavailable'):
                source.load_modules()

    def test_production_modules_do_not_import_or_select_text_lab(self):
        for path in (ROOT / 'aster').rglob('*.py'):
            tree = ast.parse(path.read_bytes(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = ([node.module or ''] if isinstance(node, ast.ImportFrom)
                             else [alias.name for alias in node.names])
                    self.assertFalse(any('newbrain_text' in name for name in names), path.name)
            self.assertNotIn('newbrain_text', path.read_text(), path.name)


class FrozenCurriculumTests(unittest.TestCase):
    def test_fixed_protocol_and_deep_copies_cannot_be_changed_by_callers(self):
        from experiments.newbrain_text import curriculum
        locked, protocol = curriculum.locked_curriculum(), curriculum.locked_protocol()
        original = (curriculum.curriculum_hash(), curriculum.protocol_hash())
        self.assertEqual(protocol['root_seed'], 221086)
        self.assertEqual((protocol['warmup_updates'], protocol['cycles_per_arm'],
                          protocol['passes_per_cycle'], protocol['updates_per_cycle']), (64, 2, 3, 24))
        self.assertEqual(protocol['actual_total_sgd_calls'], 208)
        self.assertEqual(protocol['final_arm_training_updates'], 112)
        self.assertEqual(protocol['curriculum_sha256'], original[0])
        locked['new'][0]['answer'][0] = 'changed'
        protocol['root_seed'] = 999
        self.assertEqual((curriculum.curriculum_hash(), curriculum.protocol_hash()), original)
        self.assertNotEqual(curriculum.locked_curriculum()['new'][0]['answer'][0], 'changed')
        self.assertEqual(curriculum.locked_protocol()['root_seed'], 221086)

    def test_teaching_is_explicit_duplicate_exposure_with_no_heldout_rows(self):
        from experiments.newbrain_text import curriculum
        rows = curriculum.locked_curriculum()
        heldout = {tuple(row['prefix']) for row in rows['heldout']}
        for split in ('old', 'new'):
            batches = curriculum.teaching_batches(split)
            self.assertEqual(len(batches), 6)
            self.assertEqual(len(rows[split]), 6)
            for i, batch in enumerate(batches):
                self.assertEqual(len(batch), 8)
                self.assertEqual(len({tuple(row['prefix']) for row in batch}), 1)
                for row in batch:
                    self.assertEqual(row, {'prefix': tuple(rows[split][i]['prefix']),
                                           'answer': tuple(rows[split][i]['answer'])})
                    self.assertNotIn(row['prefix'], heldout)
                self.assertIsNot(batch[0], batch[1])
        with self.assertRaises(ValueError): curriculum.teaching_batches('heldout')

    def test_scientific_goals_do_not_pass_on_empty_retention_denominator(self):
        from experiments.newbrain_text.training import goal_results
        baseline = {split: [{'case_id': split + str(i), 'exact_correct': False} for i in range(2)]
                    for split in ('old', 'new', 'heldout')}
        result = copy.deepcopy(baseline)
        for split in ('new', 'heldout'):
            result[split][0]['exact_correct'] = True
        goals = goal_results(baseline, result)
        self.assertTrue(goals['new_improves'])
        self.assertTrue(goals['heldout_improves'])
        self.assertEqual(goals['old_correct_denominator'], 0)
        self.assertFalse(goals['old_retained'])
        self.assertFalse(goals['all_scientific_goals_met'])
        baseline['old'][0]['exact_correct'] = True
        self.assertFalse(goal_results(baseline, result)['old_retained'])
        result['old'][0]['exact_correct'] = True
        self.assertTrue(goal_results(baseline, result)['all_scientific_goals_met'])


class Fixed086MethodInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = pure_module('method_order.py')

    def packet(self, method='ERROR_PRIORITIZED', cycle=0, new_pass=0):
        return {'schema': 'newbrain.foundation221.exposed-feedback.v1',
                'cycle': cycle, 'new_pass': new_pass,
                'completed_updates': self.policy.probe_update(method, cycle, new_pass),
                'parameter_sha256': PROTOCOL,
                'rows': [{'row': i, 'receptive_wrong': False, 'target_loss': float(i // 8)} for i in range(48)]}

    def test_relative_cycles_have_exact_equal_exposure_quotas(self):
        for method in self.policy.METHODS:
            orders = (tuple(reversed(range(6))) if method == 'ERROR_PRIORITIZED' else tuple(range(6)),) * 3
            blocks = self.policy.cycle_blocks(method, orders)
            self.assertEqual(len(blocks), 24)
            self.assertEqual(sum(kind == 'new' for kind, _ in blocks), 18)
            for batch in range(6):
                self.assertEqual(blocks.count(('new', batch)), 3)
                self.assertEqual(blocks.count(('protected_old', batch)), 1)
            self.assertEqual(blocks, tuple(item for p, order in enumerate(orders)
                                            for item in self.policy.pass_blocks(method, p, order)))

    def test_original_probe_counters_are_fixed_interface_only(self):
        self.assertEqual(self.policy.STARTING_UPDATES, 10720)
        self.assertEqual(self.policy.probe_update('BLOCKED', 1, 2), 10720 + 24 + 12)
        self.assertEqual(self.policy.probe_update('INTERLEAVED', 1, 2), 10720 + 24 + 16)
        with self.assertRaises(ValueError):
            self.policy.probe_update('BLOCKED', 64, 0)

    def test_error_priority_uses_mistakes_then_loss_stable_without_replacement(self):
        packet = self.packet()
        packet['rows'][8]['receptive_wrong'] = True
        before = copy.deepcopy(packet)
        result = self.policy.feedback_order('ERROR_PRIORITIZED', 0, 0, packet)
        self.assertEqual(result['chosen_order'], [1, 5, 4, 3, 2, 0])
        self.assertFalse(result['replacement'])
        self.assertEqual(result['extra_SGD_updates'], 0)
        self.assertFalse(result['evaluation_rows_used'])
        self.assertEqual(packet, before)
        for row in packet['rows']:
            row.update(receptive_wrong=False, target_loss=1.0)
        result = self.policy.feedback_order('ERROR_PRIORITIZED', 0, 0, packet)
        self.assertEqual(result['chosen_order'], list(range(6)))
        self.assertEqual(result['priority_basis'], 'loss_only_no_observed_mistake')

    def test_fixed_methods_ignore_priority_but_validate_complete_feedback(self):
        for method in ('INTERLEAVED', 'BLOCKED'):
            result = self.policy.feedback_order(method, 0, 0, self.packet(method))
            self.assertEqual(result['priority_order'], [5, 4, 3, 2, 1, 0])
            self.assertEqual(result['chosen_order'], list(range(6)))

    def test_finite_large_loss_mean_does_not_overflow(self):
        packet = self.packet()
        for row in packet['rows']:
            row['target_loss'] = 1e308
        result = self.policy.feedback_order('ERROR_PRIORITIZED', 0, 0, packet)
        self.assertTrue(all(row['mean_target_loss'] == 1e308 for row in result['batch_metrics']))

    def test_incomplete_stale_nonfinite_or_extra_feedback_is_refused(self):
        changes = [lambda p: p['rows'].pop(),
                   lambda p: p['rows'][1].update(row=0),
                   lambda p: p['rows'][0].update(target_loss=float('nan')),
                   lambda p: p['rows'][0].update(target_loss=-1.0),
                   lambda p: p['rows'][0].update(receptive_wrong=1),
                   lambda p: p.update(completed_updates=0),
                   lambda p: p.update(evaluation_rows=[])]
        for change in changes:
            packet = self.packet(); change(packet)
            with self.assertRaises(ValueError):
                self.policy.feedback_order('ERROR_PRIORITIZED', 0, 0, packet)

    def test_invalid_order_or_fixed_method_reordering_is_refused(self):
        for order in (list(range(6)), (0, 0, 2, 3, 4, 5), (False, 1, 2, 3, 4, 5), (5, 4, 3, 2, 1, 0)):
            with self.subTest(order=order), self.assertRaises(ValueError):
                self.policy.pass_blocks('INTERLEAVED', 0, order)


class Fixed086ProbeCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codec = pure_module('probe_ledger.py')

    def row(self, ordinal=0):
        probabilities = [-0.0] + [0.0] * 6 + [1.0] + [0.0] * 34
        distribution = {'dtype': '<f8', 'shape': [42], 'raw_hex': struct.pack('<42d', *probabilities).hex()}
        return {'schema': 'newbrain.method221.exposed-probe.v1', 'method': 'INTERLEAVED', 'mode': 'ON',
                'cycle': 0, 'new_pass': 0, 'row': ordinal, 'updates_completed': 10720,
                'chosen_label': 'a', 'expected_label': 'b', 'receptive_wrong': True, 'target_loss': -0.0,
                'first_distribution': copy.deepcopy(distribution),
                'after_teacher_distribution': copy.deepcopy(distribution), 'parameter_sha256': PROTOCOL,
                'clock': {'start_ns': 10 + ordinal * 10, 'end_ns': 19 + ordinal * 10,
                          'start_utc': '2026-10-06T00:00:00.000001Z', 'end_utc': '2026-10-06T00:00:00.000002Z'}}

    def test_complete_original_row_roundtrips_exact_bytes_and_order(self):
        row = self.row()
        raw = self.codec.pack(row)
        decoded = self.codec.unpack(raw, 'INTERLEAVED', 'ON')
        self.assertEqual(decoded, row)
        self.assertEqual(tuple(decoded), tuple(row))
        self.assertEqual(self.codec.pack(decoded), raw)
        self.assertEqual(decoded['first_distribution']['raw_hex'][:16], struct.pack('<d', -0.0).hex())
        self.assertEqual(struct.pack('<d', decoded['target_loss']), struct.pack('<d', -0.0))

    def test_ledger_roundtrip_preserves_all_rows_and_wrong_cases(self):
        ledger = self.codec.ProbeLedger(PROTOCOL, 'INTERLEAVED', 'ON')
        for ordinal in range(3):
            ledger.append(self.row(ordinal), {})
        raw = ledger.state_bytes()
        restored = self.codec.ProbeLedger.from_state_bytes(raw, PROTOCOL, 'INTERLEAVED', 'ON', {})
        self.assertEqual(restored.state_bytes(), raw)
        self.assertEqual(restored.rows, ledger.rows)
        self.assertEqual(len(restored.rows), 3)

    def test_refused_append_retains_original_without_dropping_prior_rows(self):
        for failure in ('duplicate', 'skip', 'clock', 'distribution', 'counter'):
            ledger = self.codec.ProbeLedger(PROTOCOL, 'INTERLEAVED', 'ON')
            ledger.append(self.row(), {})
            before, retained, row = ledger.state_bytes(), {}, self.row(1)
            if failure == 'duplicate': row['row'] = 0
            elif failure == 'skip': row['row'] = 2
            elif failure == 'clock': row['clock']['start_ns'] = 0
            elif failure == 'distribution': row['first_distribution']['raw_hex'] = '00' * 336
            else: row['updates_completed'] = 0
            with self.subTest(failure=failure), self.assertRaises(self.codec.ProbeHold) as caught:
                ledger.append(row, retained)
            self.assertIs(caught.exception.retained, retained)
            self.assertIs(retained['probe_ledger_active']['original_probe'], row)
            self.assertEqual(ledger.state_bytes(), before)

    def test_exact_dictionary_shape_and_label_consistency_required(self):
        for change in (lambda r: r.update(extra=1), lambda r: r.update(receptive_wrong=False),
                       lambda r: r.update(target_loss=float('inf')),
                       lambda r: r['first_distribution'].update(shape=[41])):
            row = self.row(); change(row)
            with self.assertRaises(ValueError): self.codec.pack(row)
        with self.assertRaises(ValueError):
            self.codec.pack(dict(reversed(tuple(self.row().items()))))

    def test_ledger_extent_and_protocol_binding_are_enforced(self):
        ledger = self.codec.ProbeLedger(PROTOCOL, 'INTERLEAVED', 'ON')
        ledger.append(self.row(), {})
        raw = ledger.state_bytes()
        for altered in (b'', raw[:-1], raw + b'\0', b'WRONGMAG' + raw[8:]):
            with self.assertRaises(ValueError):
                self.codec.ProbeLedger.from_state_bytes(altered, PROTOCOL, 'INTERLEAVED', 'ON', {})
        for protocol, method, mode in (('f' * 64, 'INTERLEAVED', 'ON'),
                                       (PROTOCOL, 'BLOCKED', 'ON'), (PROTOCOL, 'INTERLEAVED', 'OFF')):
            with self.assertRaises(ValueError):
                self.codec.ProbeLedger.from_state_bytes(raw, protocol, method, mode, {})

    def test_capacity_failure_never_evicts_or_replaces(self):
        ledger = self.codec.ProbeLedger(PROTOCOL, 'INTERLEAVED', 'ON')
        ledger.append(self.row(), {})
        before = ledger.state_bytes()
        with patch.object(self.codec, 'ROWS', 1):
            with self.assertRaises(self.codec.ProbeHold): ledger.append(self.row(1), {})
            self.assertEqual(ledger.state_bytes(), before)


class TextCliDependencyFreeTests(unittest.TestCase):
    def command(self, arguments):
        return subprocess.run([sys.executable, '-S', '-B', '-m', 'experiments.newbrain_text.demo', *arguments],
                              cwd=ROOT, capture_output=True, text=True, timeout=10)

    def test_help_and_import_are_available_without_site_packages_or_numpy(self):
        result = self.command(['--help'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('run,inspect,recheck', result.stdout)
        code = ("import sys;from experiments.newbrain_text import source,curriculum,training,persistence,demo,cold_worker;"
                "source.inspect_sources();assert 'numpy' not in sys.modules;print('stdlib-only')")
        result = subprocess.run([sys.executable, '-S', '-B', '-c', code], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'stdlib-only')

    def test_missing_runtime_creates_no_partial_state_and_exposes_no_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'sensitive-local-state'
            result = self.command(['run', '--state', str(state)])
            self.assertEqual(result.returncode, 2)
            self.assertFalse(state.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertNotIn(directory, result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stdout + result.stderr)
            self.assertIn('error:', result.stderr)

    def test_invalid_arguments_and_foreign_owner_are_safe_nonzero_refusals(self):
        for arguments in (['run', '--unknown-private-option'],
                          ['inspect', '--state', '/private-fixture-missing', '--owner', 'real_person']):
            result = self.command(arguments)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('private-fixture', result.stdout + result.stderr)
            self.assertNotIn('unknown-private-option', result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stdout + result.stderr)

    def test_noncanonical_duplicate_nonfinite_and_excess_json_is_refused(self):
        from experiments.newbrain_text import persistence
        for raw in (b'{"x":1,"x":1}', b'{ "x":1}', b'{"x":NaN}', b'{"x":1e999}',
                    b'[]', b'{}x', b'\xff'):
            # [] itself is canonical JSON and is rejected at the state-schema
            # boundary rather than by the generic JSON parser.
            if raw == b'[]':
                with self.assertRaises(persistence.LabError): persistence.validate_state([], {}, 'synthetic_test')
            else:
                with self.subTest(raw=raw), self.assertRaises(persistence.LabError): persistence._json(raw, 128)
        with self.assertRaises(persistence.LabError): persistence._json(b'{"x":1}', 2)

    def test_cold_output_is_bounded_and_oversized_child_is_reaped(self):
        from experiments.newbrain_text import demo, persistence
        with subprocess.Popen([sys.executable, '-S', '-B', '-c', 'print("x" * 20000)'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            try:
                with self.assertRaisesRegex(persistence.LabError, 'cold_output_refused'):
                    demo._bounded_output(process, 5.0)
            finally:
                if process.poll() is None: process.kill()
                process.wait(timeout=5)
            self.assertIsNotNone(process.poll())

    def test_cold_float_policy_keeps_discrete_decisions_exact(self):
        from experiments.newbrain_text import cold_worker, persistence
        differences = {'maximum_absolute_difference': 0.0, 'compared_float_values': 0}
        cold_worker._compare({'loss': 1.0, 'answer': ['warm'], 'correct': True},
                             {'loss': 1.0 + 5e-13, 'answer': ['warm'], 'correct': True}, '', differences)
        self.assertEqual(differences['compared_float_values'], 1)
        for expected, actual in ((True, 1), (['warm'], ['cool']), (1.0, float('nan')), (1.0, 1.01)):
            with self.subTest(expected=expected, actual=actual), self.assertRaises(persistence.LabError):
                cold_worker._compare(expected, actual, '', differences)

    def test_owner_validation_rejects_personal_or_unbounded_identifiers(self):
        from experiments.newbrain_text.persistence import LabError, validate_owner
        for owner in ('person@example.com', '../synthetic_test', 'synthetic_', 'synthetic_' + 'x' * 49, True):
            with self.subTest(owner=owner), self.assertRaises(LabError): validate_owner(owner)


class TextRecorderTests(unittest.TestCase):
    def test_fingerprint_includes_workflows_dependencies_vendor_and_aggregate_sources(self):
        from scripts import record_text_learning_checks as recorder
        with tempfile.TemporaryDirectory() as directory, patch.object(recorder, 'ROOT', Path(directory)):
            root = Path(directory)
            inputs = ['.github/workflows/check.yml', 'requirements-optional.txt', 'vendor/pinned/source.py',
                      'vendor/pinned/THIRD_PARTY_NOTICES.md', 'scripts/record_upgrade_checks.py',
                      'tests/test_existing.py', 'aster/core.py', 'assets/example.txt']
            for relative in inputs:
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('original')
            baseline = recorder.fingerprints()
            self.assertEqual(baseline['files'], len(inputs))
            self.assertFalse(baseline['raw_source_inventory_published'])
            self.assertNotIn('paths', baseline)
            for relative in inputs:
                path = root / relative; path.write_text('changed')
                self.assertNotEqual(recorder.fingerprints()['sha256'], baseline['sha256'], relative)
                path.write_text('original')
            (root / 'test-results').mkdir(); (root / 'test-results' / 'result.json').write_text('historical')
            self.assertEqual(recorder.fingerprints(), baseline)

    def test_output_limit_fails_even_if_child_already_exited(self):
        from scripts import record_text_learning_checks as recorder
        with tempfile.TemporaryDirectory() as directory, patch.object(recorder, 'MAX_DIAGNOSTIC', 64):
            report, raw = recorder.run_stage('overflow-fixture', ['-c', 'print("x" * 200)'], Path(directory), timeout=5)
            self.assertEqual(report['status'], 'FAIL')
            self.assertEqual(report['error_code'], 'diagnostic_size_limit')
            self.assertEqual(len(raw), 64)
            self.assertFalse(report['diagnostic_digest_is_complete'])

    def test_deadline_reaps_direct_child_and_redacts_private_command_path(self):
        from scripts import record_text_learning_checks as recorder
        children, original = [], recorder.subprocess.Popen
        def captured(*args, **kwargs):
            child = original(*args, **kwargs); children.append(child); return child
        with tempfile.TemporaryDirectory() as directory, patch.object(recorder.subprocess, 'Popen', side_effect=captured):
            private = Path(directory)
            report, _ = recorder.run_stage('deadline-fixture', ['-c', 'import time;time.sleep(30)', str(private / 'private.json')],
                                           private, timeout=.05)
            self.assertEqual(report['status'], 'FAIL')
            self.assertEqual(report['error_code'], 'deadline_exceeded')
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())
            self.assertNotIn(directory, json.dumps(report))
            self.assertIn(str(Path('<private>') / 'private.json'), report['command'])

    def test_recorder_requires_unchanged_before_and_after_fingerprints(self):
        from scripts import record_text_learning_checks as recorder
        def staged(label, arguments, private, timeout=180):
            return ({'stage': label, 'status': 'PASS', 'unittest_summaries': [{'tests': 1, 'seconds': 0.0}],
                     'skipped_count': 0}, b'{"synthetic_recorder_fixture_only":true}')
        # Pure recorder control-flow fixture, never a claimed numerical result.
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); output = root / 'out'; private = root / 'private'; private.mkdir()
                with patch.object(sys, 'argv', ['recorder', '--output', str(output)]), \
                     patch.object(recorder, 'fingerprints', side_effect=[{'sha256': 'a'}, {'sha256': 'b' if changed else 'a'}]), \
                     patch.object(recorder, 'run_stage', side_effect=staged), \
                     patch.object(recorder.tempfile, 'mkdtemp', return_value=str(private)), \
                     contextlib.redirect_stdout(io.StringIO()):
                    result = recorder.main()
                report = json.loads((output / 'result.json').read_bytes())
                self.assertEqual(result, 1 if changed else 0)
                self.assertEqual(report['source_unchanged'], not changed)
                self.assertEqual(report['success'], not changed)


if __name__ == '__main__':
    unittest.main()
