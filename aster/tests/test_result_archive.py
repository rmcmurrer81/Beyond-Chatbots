"""Check committed archive bytes on every supported checkout, including Windows."""
import hashlib
import json
from pathlib import Path
import unittest


class ResultArchiveTests(unittest.TestCase):
    def test_retained_native_log_hash_and_ci_counts(self):
        root = Path(__file__).resolve().parents[1] / 'test-results'
        validation = json.loads((root / 'index-validation.json').read_text(encoding='utf-8'))
        log = (root / 'local' / 'desktop-native-dashboard.log').read_bytes()
        self.assertEqual(hashlib.sha256(log).hexdigest(), validation['native_log_sha256'])
        index = json.loads((root / 'index.json').read_text(encoding='utf-8'))
        for record in index['ci_runs']:
            relative = Path(record['receipt'])
            self.assertFalse(relative.is_absolute())
            self.assertNotIn('..', relative.parts)
            receipt = json.loads((root / relative).read_text(encoding='utf-8'))
            self.assertEqual(receipt['run_id'], record['run_id'])
            for job in receipt['jobs']:
                core = job['core']
                self.assertEqual(core['collected'], core['executed'] + core['skipped'])
                self.assertEqual(core['executed'], core['passed'] + core['failures'] + core['errors'])


if __name__ == '__main__': unittest.main()
