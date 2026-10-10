"""Small pure-data publication regressions; no physics or hardware execution."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, 'path', [str(ROOT / 'scripts'), *sys.path]):
    spec = importlib.util.spec_from_file_location('physical_recorder_test_module',
                                                 ROOT / 'scripts/record_physical_voice_checks.py')
    recorder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recorder)


class PhysicalReceiptTests(unittest.TestCase):
    def test_local_raw_paths_are_removed_without_changing_scientific_values(self):
        source = {'passed': True, 'cases': [{'name': 'probe', 'energy_j': 1.23e-8,
                  'raw': {'path': str(ROOT / 'PRIVATE_CANARY' / 'probe.bin.gz'),
                          'sha256': 'a' * 64, 'bytes': 2048}}]}
        before = copy.deepcopy(source)
        result = recorder.public_receipt(source)
        self.assertEqual(source, before)
        self.assertEqual(result['cases'][0]['energy_j'], 1.23e-8)
        self.assertEqual(result['cases'][0]['raw'], {'filename': 'probe.bin.gz',
                         'sha256': 'a' * 64, 'bytes': 2048, 'local_path_omitted': True})
        self.assertNotIn('PRIVATE_CANARY', str(result))

    def test_existing_filename_only_receipt_is_unchanged(self):
        source = {'passed': True, 'cases': [{'raw': {'filename': 'probe.bin.gz', 'bytes': 50}}]}
        self.assertEqual(recorder.public_receipt(source), source)

    def test_filter_private_directory_is_removed(self):
        result = recorder.public_receipt({'status': 'pass', 'raw_directory': 'PRIVATE_CANARY', 'rates': {'4': 7}})
        self.assertEqual(result, {'status': 'pass', 'raw_directory_omitted': True, 'rates': {'4': 7}})

    def test_failure_type_is_kept_without_local_exception_message(self):
        result = recorder.public_receipt({'passed': False, 'failure': {'type': 'OSError', 'message': 'PRIVATE_CANARY'}})
        self.assertEqual(result['failure'], {'type': 'OSError', 'local_diagnostic_message_omitted': True})
        self.assertIs(result['passed'], False)

    def test_invalid_raw_path_type_and_filename_refused(self):
        for path in (None, True, [], 'bad\nfilename', '.'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                recorder.public_receipt({'cases': [{'raw': {'path': path}}]})

    def test_non_object_receipt_refused(self):
        for value in (None, [], True, 1, 'text'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                recorder.public_receipt(value)


if __name__ == '__main__':
    unittest.main()
