"""The companion runner retains complete discovery and fail-closed stage guards."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import check_companions as harness


class CompanionHarnessTests(unittest.TestCase):
    def test_enumeration_includes_future_modules_and_nested_duplicate_basenames(self):
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory)
            for relative in ('tests/test_z.py', 'tests/testAlpha.py',
                             'tests/pkg/__init__.py', 'tests/pkg/test_nested.py',
                             'tests/pkg/test_z.py', 'tests/helper.py',
                             'tests/test_web.cjs'):
                path = remote / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('', encoding='utf-8')
            with patch.object(harness, 'REMOTE', remote):
                self.assertEqual(harness.python_test_patterns(),
                                 ['testAlpha.py', 'test_nested.py', 'test_z.py'])

    def test_missing_or_empty_test_tree_fails_instead_of_claiming_success(self):
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory)
            for create_tests in (False, True):
                if create_tests:
                    (remote / 'tests').mkdir()
                output = io.StringIO()
                with patch.object(harness, 'REMOTE', remote), \
                        patch.object(harness, 'run') as run, redirect_stdout(output):
                    with self.assertRaisesRegex(RuntimeError, 'No companion Python test'):
                        harness.main()
                run.assert_not_called()
                self.assertNotIn('source checks passed', output.getvalue())

    def assert_discovery_coverage(self, remote, patterns):
        # Discover, but do not execute the remote suites a second time in the
        # foundation suite. A separate process avoids import/path contamination.
        source = '''\
import json, sys, unittest

def ids(suite):
    result = []
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            result.extend(ids(test))
        else:
            if isinstance(test, unittest.loader._FailedTest):
                raise RuntimeError('Test discovery failed: ' + test.id())
            result.append(test.id())
    return result

full = ids(unittest.TestLoader().discover('tests'))
groups = [ids(unittest.TestLoader().discover('tests', pattern=pattern))
          for pattern in json.loads(sys.argv[1])]
print(json.dumps({'full': full, 'groups': groups}))
'''
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join([str(harness.ROOT), str(remote)])
        result = subprocess.run([sys.executable, '-B', '-c', source, json.dumps(patterns)],
                                cwd=remote, env=env, check=True, capture_output=True,
                                text=True, timeout=20)
        coverage = json.loads(result.stdout)
        grouped = [test for group in coverage['groups'] for test in group]
        self.assertTrue(coverage['full'])
        self.assertEqual(sorted(grouped), sorted(coverage['full']))
        self.assertEqual(len(grouped), len(set(grouped)), 'test executed in multiple groups')
        return coverage

    def test_actual_discovery_has_every_case_exactly_once(self):
        self.assert_discovery_coverage(harness.REMOTE, harness.python_test_patterns())

    def test_future_nested_modules_have_every_case_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory)
            for relative in ('tests/test_shared.py', 'tests/testAdded.py',
                             'tests/pkg/test_shared.py', 'tests/pkg/test_nested.py'):
                path = remote / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('import unittest\nclass Case(unittest.TestCase):\n'
                                '    def test_kept(self): pass\n', encoding='utf-8')
            (remote / 'tests/pkg/__init__.py').write_text('', encoding='utf-8')
            with patch.object(harness, 'REMOTE', remote):
                coverage = self.assert_discovery_coverage(remote, harness.python_test_patterns())
            self.assertEqual(len(coverage['full']), 4)
            self.assertEqual(len(coverage['groups']), 3)

    def test_all_python_js_and_java_stages_are_retained(self):
        output = io.StringIO()
        patterns = harness.python_test_patterns()
        with patch.object(harness, 'run') as run, redirect_stdout(output):
            harness.main()
        calls = run.call_args_list
        self.assertEqual(len(calls), len(patterns) + 6)
        for call, pattern in zip(calls, patterns):
            command, cwd, env = call.args
            self.assertEqual(command, [sys.executable, '-m', 'unittest', 'discover',
                                       '-s', 'tests', '-p', pattern, '-v'])
            self.assertEqual(cwd, harness.REMOTE)
            self.assertEqual(env['PYTHONPATH'], os.pathsep.join(
                [str(harness.ROOT), str(harness.REMOTE)]))
        commands = [call.args[0] for call in calls[len(patterns):]]
        self.assertEqual(commands[:4], [
            [sys.executable, '-m', 'compileall', '-q', 'aster_remote', 'tests'],
            ['node', '--check', 'web/app.js'],
            ['node', '--check', 'web/sw.js'],
            ['node', '--test', 'tests/test_web.cjs'],
        ])
        for call in calls[len(patterns):len(patterns) + 4]:
            self.assertEqual(call.args[1], harness.REMOTE)
        self.assertEqual(commands[4][:7], ['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main',
                                         '-source', '17', '-target', '17'])
        self.assertEqual(commands[4][7], '-d')
        self.assertEqual(commands[4][9:], [
            harness.ANDROID / 'app/src/main/java/dev/aster/companion/InvitationGate.java',
            harness.ANDROID / 'app/src/test/java/dev/aster/companion/InvitationGateTest.java',
        ])
        self.assertEqual(commands[5], ['java', '-cp', commands[4][8],
                                       'dev.aster.companion.InvitationGateTest'])
        self.assertEqual(output.getvalue().count('Companion source checks passed.'), 1)

    def test_every_subprocess_keeps_the_120_second_check_true_guard(self):
        with patch.object(harness.subprocess, 'run') as run, redirect_stdout(io.StringIO()):
            harness.main()
        self.assertEqual(run.call_count, len(harness.python_test_patterns()) + 6)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 120)
            self.assertIs(call.kwargs['check'], True)

    def test_failures_and_timeouts_stop_later_checks_without_success(self):
        stage_count = len(harness.python_test_patterns()) + 6
        for failure_type in (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            for failing_stage in range(stage_count):
                with self.subTest(failure=failure_type.__name__, stage=failing_stage):
                    failure = (failure_type(7, ['fixture'])
                               if failure_type is subprocess.CalledProcessError
                               else failure_type(['fixture'], 120))
                    output = io.StringIO()
                    outcomes = [None] * failing_stage + [failure]
                    with patch.object(harness.subprocess, 'run', side_effect=outcomes) as run, \
                            redirect_stdout(output):
                        with self.assertRaises(failure_type) as raised:
                            harness.main()
                    self.assertIs(raised.exception, failure)
                    self.assertEqual(run.call_count, failing_stage + 1)
                    self.assertNotIn('source checks passed', output.getvalue())


if __name__ == '__main__':
    unittest.main()
