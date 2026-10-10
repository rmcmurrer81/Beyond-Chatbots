"""Run a bounded opt-in engineering suite; no scientific qualification claims."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import unittest
from .component import PIN, LEGACY_PIN, DEFAULT_ROOT
from .persistence import MAX_CHECKPOINT, MAX_OBSERVERS
from .test_adapter import AdapterCases, upstream_suite
from .test_persistence import PersistenceCases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Optional local generic test receipt; no model state')
    args = parser.parse_args()
    suite = upstream_suite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(AdapterCases))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(PersistenceCases))
    names = []
    def collect(tests):
        for test in tests:
            if isinstance(test, unittest.TestSuite):
                collect(test)
            else:
                names.append(test.id())
    collect(suite)
    started_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    wall = time.perf_counter() - started
    peak = None
    scope = 'Not measured on this platform'
    if sys.platform.startswith('linux'):
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        scope = 'Linux lifetime peak RSS of this Python process only; excludes child processes, not model RAM'
    report = {'schema': 'aster.newbrain.component-engineering-result.v1',
              'started_utc': started_utc,
              'recorded_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'command': [sys.executable, '-B', '-m', 'experiments.newbrain_adapter.run_checks', *sys.argv[1:]],
              'pin': PIN, 'platform': platform.platform(), 'python': platform.python_version(),
              'tests_run': result.testsRun, 'failures': len(result.failures),
              'errors': len(result.errors), 'skipped': len(result.skipped),
              'success': result.wasSuccessful(), 'test_names': names,
              'suite_wall_seconds': wall, 'parent_python_peak_rss_bytes': peak, 'rss_scope': scope,
              'timing_scope': 'Whole exposed test suite, not model response latency',
              'upstream_runtime057_qualified': False, 'scientific_learning_gain_claimed': False,
              'conversation_qualified': False, 'advanced_version_migration_tested': False,
              'reviewed_identical_source_pin_migration_tested': result.wasSuccessful(),
              'observer_history_restore_tested': result.wasSuccessful(),
              'transactional_checkpoint_tested': result.wasSuccessful(),
              'atomic_replace_process_exit_tested': result.wasSuccessful(),
              'power_loss_durability_qualified': False,
              'legacy_pin': LEGACY_PIN,
              'checkpoint_limits': {'bytes': MAX_CHECKPOINT, 'observers': MAX_OBSERVERS,
                                    'attempts_per_observer': 4, 'learner_snapshot_bytes': 32768,
                                    'learner_update_ceiling': 32},
              'qwen_tested': False, 'winner': None,
              'snapshot_manifest_sha256': hashlib.sha256((DEFAULT_ROOT / PIN / 'manifest.json').read_bytes()).hexdigest(),
              'adapter_source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(Path(__file__).parent.glob('*.py'))},
              'limitations': ['Two pure-Python components only', 'Synthetic exposed fixtures',
                              'No NumPy qualification or full brain', 'No app tools or autonomy',
                              'Explicit old/new byte-identical component pin migration only; no advanced architecture migration',
                              'Trusted single-writer local file custody; no hostile-filesystem boundary or power-loss qualification',
                              'Legacy direct session.model mutation bypasses transactional guarantees',
                              'Snapshot capacity may precede update/attempt count limits; no history eviction']}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf8')
    print(json.dumps(report, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
