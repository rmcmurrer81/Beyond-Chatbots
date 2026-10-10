"""Explicit local CLI for the isolated synthetic text-learning experiment."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from .curriculum import DEFAULT_OWNER, canonical, locked_protocol
from .persistence import (LabError, MODEL_NAMES, check_destination, inspect_state, need,
                          publish_state, read_state, validate_owner)


def run(state_dir, owner=DEFAULT_OWNER):
    validate_owner(owner)
    check_destination(state_dir)
    from .training import run_experiment
    envelope, report = run_experiment(owner)
    return publish_state(state_dir, envelope, report)


def inspect(state_dir, owner=DEFAULT_OWNER):
    return inspect_state(state_dir, owner)


def _bounded_output(process, timeout):
    """Drain both pipes concurrently with hard allocation caps and one deadline."""
    deadline = time.monotonic() + timeout
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()
    failures = threading.Event()

    def drain(stream, destination, cap):
        try:
            while True:
                chunk = stream.read(min(4096, cap + 1 - len(destination)))
                if not chunk:
                    return
                destination.extend(chunk)
                if len(destination) > cap:
                    overflow.set()
                    if process.poll() is None:
                        process.kill()
                    return
        except (OSError, ValueError):
            failures.set()

    readers = [threading.Thread(target=drain, args=(stream, buffers[index], cap), daemon=True)
               for index, (stream, cap) in enumerate(((process.stdout, 16384), (process.stderr, 4096)))]
    process._aster_output_readers = readers
    for reader in readers:
        reader.start()
    remaining = max(0.001, deadline - time.monotonic())
    process.wait(timeout=remaining)
    for reader in readers:
        reader.join(max(0, deadline - time.monotonic()))
    need(not any(reader.is_alive() for reader in readers), 'cold_pipe_deadline_exceeded')
    need(not overflow.is_set(), 'cold_output_refused')
    need(not failures.is_set(), 'cold_pipe_failed')
    return bytes(buffers[0]), bytes(buffers[1])


def recheck(state_dir, owner=DEFAULT_OWNER, timeout=30.0):
    """Finite separate-process restore; timeout or cancellation kills the child."""
    need(type(timeout) in (int, float) and not isinstance(timeout, bool)
         and math.isfinite(timeout) and 0 < timeout <= 30.0, 'bounded_recheck_timeout_required')
    envelope, report = read_state(state_dir, owner)
    before = canonical(envelope), canonical(report)
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update({'PYTHONDONTWRITEBYTECODE': '1', 'OPENBLAS_NUM_THREADS': '1',
                        'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'})
    # Keep the trusted repository first and avoid ambient PYTHONPATH startup hooks.
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONSTARTUP', None)
    command = [sys.executable, '-B', '-m', 'experiments.newbrain_text.cold_worker',
               '--state', str(Path(state_dir).absolute()), '--owner', owner,
               '--parent-pid', str(os.getpid())]
    process = None
    try:
        process = subprocess.Popen(command, cwd=root, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = _bounded_output(process, float(timeout))
        need(process.returncode == 0, 'cold_process_failed')
        need(len(stdout) <= 16384 and len(stderr) == 0, 'cold_output_refused')
        result = json.loads(stdout.decode('ascii'))
        need(type(result) is dict and result.get('schema') == 'aster.synthetic-text-cold-recheck.v1'
             and result.get('owner') == owner and result.get('parent_pid') == os.getpid()
             and type(result.get('child_pid')) is int and result['child_pid'] == process.pid and result['child_pid'] != os.getpid()
             and result.get('state_sha256') == hashlib.sha256(before[0]).hexdigest()
             and result.get('models_verified') == 5 and set(result.get('models', {})) == set(MODEL_NAMES)
             and result.get('engineering_recheck_passed') is True and result.get('training_calls') == 0
             and result.get('rng_calls') == 0 and result.get('initialization_calls') == 0,
             'cold_result_identity_mismatch')
        need(result.get('float_policy') == locked_protocol()['cold_recheck'], 'cold_float_policy_mismatch')
        after_envelope, after_report = read_state(state_dir, owner)
        need((canonical(after_envelope), canonical(after_report)) == before, 'published_state_changed_during_recheck')
        return result
    except subprocess.TimeoutExpired as exc:
        raise LabError('cold_recheck_timeout') from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LabError('cold_process_unavailable') from exc
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        if process is not None:
            cleanup_deadline = time.monotonic() + 1.0
            readers = getattr(process, '_aster_output_readers', [])
            for reader in readers:
                reader.join(max(0, cleanup_deadline - time.monotonic()))
            for index, stream in enumerate((process.stdout, process.stderr)):
                if stream is not None and (index >= len(readers) or not readers[index].is_alive()):
                    stream.close()


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'error: invalid_arguments\n')


def main(argv=None):
    parser = _Parser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True, parser_class=_Parser)
    for command in ('run', 'inspect', 'recheck'):
        child = subparsers.add_parser(command)
        child.add_argument('--state', required=True, help='Fresh output directory for run; saved directory otherwise')
        child.add_argument('--owner', default=DEFAULT_OWNER, help='Synthetic owner identifier only')
    args = parser.parse_args(argv)
    try:
        result = {'run': run, 'inspect': inspect, 'recheck': recheck}[args.command](args.state, args.owner)
        print(canonical(result).decode('ascii'))
        return 0
    except LabError as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('error: operation_cancelled', file=sys.stderr)
        return 130
    except Exception:
        print('error: text_lab_failed', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
