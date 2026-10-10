"""Portable, dependency-free test entrypoint for reviewed companion source.

Requires the runner's existing Python, Node.js and JDK 17+. Installs nothing.
This is not an Android APK build or a public network/device test.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REMOTE = ROOT / 'remote-companion'
ANDROID = ROOT / 'android-companion'


def run(command, cwd=ROOT, env=None):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True, timeout=120)


def python_test_patterns():
    # Keep unittest discovery (including nested packages), but do not charge
    # independent modules against one shared 120-second subprocess budget.
    # Duplicate basenames share a discovery group so no test is run twice.
    patterns = sorted({path.name for path in (REMOTE / 'tests').rglob('test*.py')
                       if path.is_file()})
    if not patterns:
        raise RuntimeError('No companion Python test modules found')
    return patterns


def main():
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(REMOTE)])
    for pattern in python_test_patterns():
        run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests',
             '-p', pattern, '-v'], REMOTE, env)
    run([sys.executable, '-m', 'compileall', '-q', 'aster_remote', 'tests'], REMOTE)
    run(['node', '--check', 'web/app.js'], REMOTE)
    run(['node', '--check', 'web/sw.js'], REMOTE)
    run(['node', '--test', 'tests/test_web.cjs'], REMOTE)
    with tempfile.TemporaryDirectory(prefix='aster-java-test-') as output:
        sources = [ANDROID / 'app/src/main/java/dev/aster/companion/InvitationGate.java',
                   ANDROID / 'app/src/test/java/dev/aster/companion/InvitationGateTest.java']
        run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '17', '-target', '17', '-d', output, *sources])
        run(['java', '-cp', output, 'dev.aster.companion.InvitationGateTest'])
    print('Companion source checks passed. No APK, device, public relay, voice or NewBrain test was performed.')


if __name__ == '__main__':
    main()
