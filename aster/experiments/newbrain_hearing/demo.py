"""Opt-in durable synthetic-tone experiment; no Aster production integration.

Run and recheck require CPython 3.14.4. Inspect is read-only on Python 3.12+.
The unchanged entries use process isolation, not an OS sandbox. Checksums detect
accidental corruption, not a hostile editor who can replace both data and receipt.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from . import pipeline, source

SCHEMA = 'aster.synthetic-hearing-state.v1'
REPORT_SCHEMA = 'aster.synthetic-hearing-report.v1'
ISOLATION = 'Process isolation, not an OS sandbox.'
RECEIPT_LIMIT = 128 * 1024
REPORT_LIMIT = 2 * 1024 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}')
ROLES = (('210', 'staged_producer'), ('210', 'staged_blind'),
         ('210', 'staged_scorer'), ('211', 'staged_producer'),
         ('211', 'staged_blind'), ('211', 'staged_labels'))
# Fixed names and original-entry read limits: receipts cannot select arbitrary
# files to read or execute. Only fresh Aster-generated synthetic data is retained.
DATA_LIMITS = {
    'run-report.json': REPORT_LIMIT,
    'work/fixture-base.json': 4096,
    'work/fixture-new.json': 4096,
    'work/producer/BLIND-PCM.bin': 49152,
    'work/producer/BLIND-INPUT.json': 4096,
    'work/producer/GOLD.private.json': 16384,
    'work/query-producer/QUERY-PCM.bin': 49152,
    'work/query-producer/QUERY-INPUT.json': 4096,
    'work/query-producer/NEW-GOLD.private.json': 16384,
}
for _arm in pipeline.ARMS:
    DATA_LIMITS[f'work/arm-{_arm}/MODEL.private.json'] = 8192
    DATA_LIMITS[f'work/arm-{_arm}/ARM-REPORT.json'] = 16384


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def check_node(path, directory):
    """Reject links, Windows reparse points, devices and multiply-linked files."""
    info = path.lstat()
    reparse = getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if path.is_symlink() or reparse or not expected(info.st_mode):
        raise ValueError('State paths must be plain owned directories/files')
    if not directory and info.st_nlink != 1:
        raise ValueError('Hard-linked state files are refused')
    return info


def state_path(value, existing):
    path = Path(os.path.abspath(value))
    if any(part.casefold() == '.aster-state' for part in path.parts):
        raise ValueError('Choose a separate synthetic experiment directory, outside .aster-state')
    # Do not resolve away a symlink before admission. Every existing ancestor must
    # be a plain directory; state itself is created once, never merged or reused.
    for parent in reversed(path.parents):
        check_node(parent, True)
    if existing:
        check_node(path, True)
    elif path.exists() or path.is_symlink():
        raise ValueError('State directory already exists; choose a new directory')
    return path


def read_bytes(root, relative, limit):
    path = root / relative
    for parent in reversed(path.relative_to(root).parents):
        check_node(root / parent, True)
    info = check_node(path, False)
    if info.st_size > limit:
        raise ValueError('Saved file exceeds its size limit: ' + relative)
    # Bounded read even if a file changes after lstat. This is an integrity check,
    # not a protection against a malicious concurrent filesystem writer.
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or len(raw) != info.st_size:
        raise ValueError('Saved file size changed: ' + relative)
    return raw


def no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def load_json(raw):
    def invalid_constant(_):
        raise ValueError('Non-finite JSON number')
    return json.loads(raw, object_pairs_hook=no_duplicates, parse_constant=invalid_constant)


def new_json(path, value):
    # Never overwrite any previous report, receipt, diagnostic or result.
    with path.open('x', encoding='ascii') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def metadata(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def role_files(manifest):
    expected = {}
    roles = {(item['experiment'], item['role']): item for item in manifest['roles']}
    if set(roles) != set(ROLES):
        raise ValueError('Unexpected original source roles')
    for experiment, role in ROLES:
        for item in roles[experiment, role]['files']:
            relative = f'work/{experiment}-{role}/{item["filename"]}'
            expected[relative] = {'bytes': item['bytes'], 'sha256': item['sha256']}
    return expected


def check_saved_roles(root, expected):
    check_node(root, True)
    check_node(root / 'work', True)
    for experiment, role in ROLES:
        relative = f'work/{experiment}-{role}'
        directory = root / relative
        check_node(directory, True)
        names = {str(path.relative_to(root).as_posix()) for path in directory.iterdir()}
        wanted = {path for path in expected if path.startswith(relative + '/')}
        if names != wanted:
            raise ValueError('Missing or additional staged role files')
    for relative, entry in expected.items():
        if metadata(read_bytes(root, relative, entry['bytes'])) != entry:
            raise ValueError('Exact original role source changed: ' + relative)


def checked_map(value, expected, limits):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('Receipt file paths differ from the fixed whitelist')
    for relative, item in value.items():
        if (type(item) is not dict or set(item) != {'bytes', 'sha256'}
                or type(item['bytes']) is not int or not 0 <= item['bytes'] <= limits[relative]
                or type(item['sha256']) is not str or not SHA256.fullmatch(item['sha256'])):
            raise ValueError('Invalid receipt byte count or digest')


def validate_run_report(report):
    if (type(report) is not dict or report.get('schema') != REPORT_SCHEMA
            or report.get('operation') != 'run' or report.get('status') != 'PASSED'
            or report.get('success') is not True or report.get('source_commit') != source.PIN):
        raise ValueError('Original run did not complete successfully')
    result = report.get('pipeline', {})
    if (result.get('status') != 'PASSED' or result.get('executed') is not True
            or [item.get('arm') for item in result.get('arms', [])] != list(pipeline.ARMS)
            or any(item.get('old_decision_rows_equal') != 24
                   or type(item.get('new_teachings')) is not int or item['new_teachings'] != 0
                   or item.get('complete_decision_state_unchanged') is not True
                   for item in result['arms'])):
        raise ValueError('Original six-arm parity/no-retraining evidence is incomplete')


def verify_state(root):
    receipt = load_json(read_bytes(root, 'receipt.json', RECEIPT_LIMIT))
    keys = {'schema', 'owner', 'created_utc', 'source_commit', 'source_manifest_sha256',
            'runtime', 'arms', 'isolation', 'files', 'role_source'}
    if type(receipt) is not dict or set(receipt) != keys:
        raise ValueError('Malformed state receipt schema')
    if (receipt['schema'] != SCHEMA or receipt['owner'] != 'aster-synthetic-hearing'
            or receipt['source_commit'] != source.PIN
            or receipt['source_manifest_sha256'] != source.MANIFEST_SHA256
            or receipt['runtime'] != {'implementation': 'CPython', 'version': '3.14.4'}
            or receipt['arms'] != list(pipeline.ARMS) or receipt['isolation'] != ISOLATION):
        raise ValueError('Receipt pin, owner, runtime or experiment scope differs')
    if type(receipt['created_utc']) is not str:
        raise ValueError('Malformed receipt timestamp')
    timestamp = datetime.datetime.fromisoformat(receipt['created_utc'])
    if timestamp.tzinfo is None or timestamp.utcoffset() != datetime.timedelta(0):
        raise ValueError('Receipt timestamp must be UTC')
    expected_roles = role_files(source.verify())
    checked_map(receipt['files'], DATA_LIMITS, DATA_LIMITS)
    checked_map(receipt['role_source'], expected_roles, {key: item['bytes'] for key, item in expected_roles.items()})
    if receipt['role_source'] != expected_roles:
        raise ValueError('Receipt original role source hashes differ from the pinned manifest')
    check_saved_roles(root, expected_roles)
    for relative, item in receipt['files'].items():
        if metadata(read_bytes(root, relative, DATA_LIMITS[relative])) != item:
            raise ValueError('Saved bytes changed: ' + relative)
    report = load_json(read_bytes(root, 'run-report.json', REPORT_LIMIT))
    validate_run_report(report)
    return receipt, report


def base_report(operation):
    return {'schema': REPORT_SCHEMA, 'operation': operation, 'recorded_utc': now(),
            'source_commit': source.PIN, 'status': 'RUNNING', 'success': False,
            'isolation': ISOLATION, 'production_backend_activated': False,
            'speech_or_general_hearing_qualified': False, 'upstream_private_state_used': False}


def run_state(root):
    # Verify source before creating a directory or invoking any original entry.
    manifest = source.verify()
    root.mkdir(mode=0o700, exist_ok=False)
    report = base_report('run')
    report['pipeline'] = {}
    try:
        work = root / 'work'
        work.mkdir(mode=0o700)
        pipeline.run(work, report['pipeline'])
        report.update(status='PASSED', success=True)
        validate_run_report(report)
        roles = role_files(manifest)
        check_saved_roles(root, roles)
        files = {relative: metadata(read_bytes(root, relative, cap))
                 for relative, cap in DATA_LIMITS.items() if relative != 'run-report.json'}
    except Exception as error:
        if report['pipeline'].get('executed') is True:
            report['pipeline']['status'] = 'FAILED'
        report.update(status='FAILED', success=False, error_type=type(error).__name__,
                      error='Synthetic run failed; retained process records and local diagnostics describe the failure.')
        new_json(root / 'run-report.json', report)
        raise
    new_json(root / 'run-report.json', report)
    files['run-report.json'] = metadata(read_bytes(root, 'run-report.json', REPORT_LIMIT))
    receipt = {'schema': SCHEMA, 'owner': 'aster-synthetic-hearing', 'created_utc': now(),
               'source_commit': source.PIN, 'source_manifest_sha256': source.MANIFEST_SHA256,
               'runtime': {'implementation': 'CPython', 'version': '3.14.4'},
               'arms': list(pipeline.ARMS), 'isolation': ISOLATION,
               'files': files, 'role_source': roles}
    new_json(root / 'receipt.json', receipt)
    verify_state(root)
    return {'status': 'PASSED', 'success': True, 'state': str(root),
            'report': str(root / 'run-report.json'), 'isolation': ISOLATION,
            'scope': 'Saved a fresh synthetic-tone experiment, not speech recognition.'}


def arm_summary(arms):
    return [{'arm': item['arm'], 'old_decision_rows_equal': item['old_decision_rows_equal'],
             'new_teachings': item['new_teachings'],
             'fresh_totals': item['fresh_score']['totals'],
             **({'initial_totals': item['initial_score']['totals']} if 'initial_score' in item else {})}
            for item in arms]


def inspect_state(root):
    receipt, report = verify_state(root)
    return {'status': 'VERIFIED_SAVED_STATE', 'success': True, 'state': str(root),
            'created_utc': receipt['created_utc'], 'source_commit': receipt['source_commit'],
            'arms': arm_summary(report['pipeline']['arms']), 'saved_bytes_verified': True,
            'report': str(root / 'run-report.json'),
            'executed': False, 'isolation': ISOLATION,
            'scope': 'Read-only integrity inspection; no model execution or new runtime qualification.'}


def check_retention(restored, scored, arm, model_hash):
    if (restored.get('schema') != 'newbrain.complete-decision-retention211.v1'
            or restored.get('arm') != arm or restored.get('original_model_sha256') != model_hash
            or type(restored.get('new_training_calls')) is not int or restored['new_training_calls'] != 0
            or restored.get('old_parity_count') != 24 or restored.get('new_nuisance_count') != 24):
        raise ValueError('Restored model, arm or no-retraining evidence differs')
    fingerprints = restored.get('decision_fingerprints')
    if (type(fingerprints) is not list or len(fingerprints) != 3
            or any(type(value) is not str or not SHA256.fullmatch(value) for value in fingerprints)
            or len(set(fingerprints)) != 1):
        raise ValueError('Complete decision state changed')
    if (scored.get('schema') != 'newbrain.independent-retention-results211.v1'
            or scored.get('arm') != arm or type(scored.get('new_training_calls')) is not int
            or scored['new_training_calls'] != 0
            or scored.get('old_parity', {}).get('complete_decision_rows_equal') != 24
            or scored.get('old_parity', {}).get('examples') != 24
            or type(scored.get('fresh24')) is not dict):
        raise ValueError('Independent old-decision parity/no-retraining check failed')


def recheck_state(root):
    receipt, _ = verify_state(root)  # Reject all malformed state before any write.
    history = root / 'rechecks'
    if history.exists() or history.is_symlink():
        check_node(history, True)
    else:
        history.mkdir(mode=0o700)
    work = history / ('recheck-' + uuid.uuid4().hex)
    work.mkdir(mode=0o700, exist_ok=False)
    report = base_report('recheck')
    report.update(processes=[], arms=[], original_created_utc=receipt['created_utc'],
                  saved_receipt_sha256=hashlib.sha256(read_bytes(root, 'receipt.json', RECEIPT_LIMIT)).hexdigest(),
                  saved_bytes_verified=True, retrained=False)
    try:
        consumer = root / 'work/211-staged_blind'
        labels = root / 'work/211-staged_labels'
        files = receipt['files']
        qinput = 'work/query-producer/QUERY-INPUT.json'
        qpcm = 'work/query-producer/QUERY-PCM.bin'
        qgold = 'work/query-producer/NEW-GOLD.private.json'
        stop = work / 'STOP'
        for arm in pipeline.ARMS:
            model = f'work/arm-{arm}/MODEL.private.json'
            original = f'work/arm-{arm}/ARM-REPORT.json'
            output = pipeline.invoke(consumer, 'retention_consumer.py', {
                'arm': arm, 'model': root/model, 'expected-model-sha256': files[model]['sha256'],
                'input': root/qinput, 'expected-input-sha256': files[qinput]['sha256'],
                'pcm': root/qpcm, 'expected-pcm-sha256': files[qpcm]['sha256'],
                'output-dir': work/('restore-'+arm), 'stop-file': stop}, work, report['processes'])
            restored_path = output / 'RETENTION-REPORT.json'
            restored_bytes = read_bytes(work, str(restored_path.relative_to(work).as_posix()), 262144)
            output = pipeline.invoke(labels, 'retention_labels.py', {
                'arm': arm, 'original-report': root/original,
                'expected-original-report-sha256': files[original]['sha256'],
                'retention-report': restored_path,
                'expected-retention-report-sha256': hashlib.sha256(restored_bytes).hexdigest(),
                'new-gold': root/qgold, 'expected-new-gold-sha256': files[qgold]['sha256'],
                'output-dir': work/('score-'+arm), 'stop-file': stop}, work, report['processes'])
            restored = load_json(restored_bytes)
            scored = load_json(read_bytes(work, str((output/'RETENTION-SCORES.json').relative_to(work).as_posix()), 65536))
            check_retention(restored, scored, arm, files[model]['sha256'])
            report['arms'].append({'arm': arm, 'old_decision_rows_equal': 24,
                                   'fresh_score': scored['fresh24'], 'new_teachings': 0,
                                   'complete_decision_state_unchanged': True})
        verify_state(root)  # Detect unexpected changes to saved source/input bytes.
        if hashlib.sha256(read_bytes(root, 'receipt.json', RECEIPT_LIMIT)).hexdigest() != report['saved_receipt_sha256']:
            raise ValueError('Saved receipt changed during recheck')
        report.update(status='PASSED', success=True)
    except Exception as error:
        report.update(status='FAILED', success=False, error_type=type(error).__name__,
                      error='Recheck failed; retained process records and local diagnostics describe the failure.')
    new_json(work / 'result.json', report)
    return {'status': report['status'], 'success': report['success'], 'state': str(root),
            'report': str(work/'result.json'), 'arms': arm_summary(report['arms']), 'isolation': ISOLATION}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'inspect', 'recheck'))
    parser.add_argument('--state', required=True, type=Path,
                        help='New isolated experiment directory for run; saved experiment for inspect/recheck.')
    args = parser.parse_args(argv)
    # Before filesystem access or source staging: unavailable must mean no state
    # mutation, not a successful skipped hearing experiment.
    if args.command != 'inspect' and not pipeline.exact_runtime():
        print(json.dumps({'status': 'UNAVAILABLE_EXACT_RUNTIME_REQUIRED', 'success': False,
                          'executed': False, 'reason': 'Run and recheck require CPython 3.14.4; original guards are unchanged.'}))
        return 2
    try:
        root = state_path(args.state, existing=args.command != 'run')
        action = {'run': run_state, 'inspect': inspect_state, 'recheck': recheck_state}[args.command]
        result = action(root)
    except Exception as error:
        result = {'status': 'FAILED_OR_REFUSED', 'success': False,
                  'error_type': type(error).__name__, 'error': str(error)}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
