"""Engineering tests of the admission refusal, not a NewBrain capability test."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from experiments.newbrain_candidate.audit import CANDIDATE, INVENTORY, audit, require_runtime_candidate


class CandidateAdmissionTests(unittest.TestCase):
    def test_published_candidate_is_incomplete_and_never_executed(self):
        result = audit()
        self.assertEqual(result['missing_published_modules'], [
            'cue_readout', 'hearing_learner', 'hearing_limits', 'pcm_features', 'waveform_corpus'])
        self.assertFalse(result['runtime_compatible'])
        self.assertFalse(result['candidate_code_executed'])
        self.assertFalse(result['production_backend_activated'])
        self.assertFalse(result['upstream_results_reproduced'])
        with self.assertRaisesRegex(RuntimeError, 'Candidate not admitted'):
            require_runtime_candidate()

    def test_exact_bytes_checked_without_loading_any_upstream_module(self):
        before = set(sys.modules)
        audit()
        self.assertFalse(set(sys.modules) - before & {
            'decision_restore', 'retention_consumer', 'query_producer', 'hearing_learner'})

    def test_candidate_source_tampering_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'candidate'
            shutil.copytree(CANDIDATE, root)
            path = root / 'research/decision-retention075/source/decision_restore.py'
            path.write_bytes(path.read_bytes() + b'\n# tamper\n')
            with self.assertRaisesRegex(ValueError, 'Exact upstream byte'):
                audit(root)

    def test_dependency_inventory_tampering_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.json'
            data = json.loads(INVENTORY.read_bytes())
            data['modules']['hearing_learner'] = [{'path': 'fabricated.py'}]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
                audit(inventory_path=path)

    def test_cli_records_blocker_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'audit.json'
            result = subprocess.run([sys.executable, '-B', '-m',
                'experiments.newbrain_candidate.audit', '--report', str(report)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(report.read_text())['status'], 'BLOCKED_INCOMPLETE_DEPENDENCIES')


if __name__ == '__main__':
    unittest.main()
