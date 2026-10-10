"""Bounded, canonical data-only persistence and atomic no-clobber publication.

Inspection uses only the standard library. Hashes detect corruption and bind
identity; they are not signatures and do not authenticate a hostile editor.
"""
import base64
import binascii
import ctypes
import errno
import hashlib
import json
import itertools
import math
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import sys
import tempfile
from .curriculum import (DEFAULT_OWNER, METHODS, WORDS, canonical, curriculum_hash,
                         locked_curriculum, locked_protocol, protocol_hash)

STATE_CAP = 1048576
REPORT_CAP = 2097152
MANIFEST_CAP = 4096
FILES = ('manifest.json', 'state.json', 'report.json')
BINDINGS = ('owner', 'source_pin', 'source_sha256', 'protocol_sha256', 'curriculum_sha256')
MODEL_NAMES = ('initial', 'baseline') + METHODS
COUNTER_NAMES = ('training_updates', 'training_examples', 'prefix_tokens_seen', 'target_tokens_seen')


class LabError(ValueError):
    """A fixed, path-free refusal code safe for the CLI."""


def need(condition, code):
    if not condition:
        raise LabError(code)


def validate_owner(owner):
    need(type(owner) is str and re.fullmatch(r'synthetic_[a-z][a-z0-9_]{0,47}', owner) is not None,
         'synthetic_owner_required')
    return owner


def _ints(value, *keys):
    return all(type(value.get(key)) is int for key in keys)


def _hash(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate_json_key')
        result[key] = value
    return result


def _json(raw, cap):
    need(type(raw) is bytes and 0 < len(raw) <= cap, 'bounded_json_required')
    try:
        result = json.loads(raw.decode('ascii'), object_pairs_hook=_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(LabError('nonfinite_json')))
        need(canonical(result) == raw, 'canonical_json_required')
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, LabError):
            raise
        raise LabError('invalid_json') from exc
    return result


def _safe_path(path):
    try:
        original = Path(os.fspath(path))
        if not original.is_absolute():
            original = Path.cwd() / original
        need(all(not part.is_symlink() and not (hasattr(part, 'is_junction') and part.is_junction())
                 for part in (original, *original.parents)), 'state_symlink_refused')
        target = Path(os.path.abspath(original))
        need(all(not part.is_symlink() and not (hasattr(part, 'is_junction') and part.is_junction())
                 for part in (target, *target.parents)), 'state_symlink_refused')
        return target
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, LabError):
            raise
        raise LabError('state_path_unavailable') from exc


def check_destination(state_dir):
    target = _safe_path(state_dir)
    need(target.name not in ('', '.', '..') and target.parent.is_dir(), 'state_parent_required')
    need(not target.exists() and not target.is_symlink(), 'state_destination_occupied')
    return target


def _read_plain(path, cap):
    try:
        _safe_path(path)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= cap,
                 'state_plain_bounded_file_required')
            raw = stream.read(cap + 1)
        need(len(raw) == info.st_size, 'state_extent_changed')
        return raw
    except OSError as exc:
        raise LabError('state_file_unavailable') from exc


def _binding(owner):
    from .source import PIN, inspect_sources
    return {'owner': validate_owner(owner), 'source_pin': PIN,
            'source_sha256': inspect_sources()['source_sha256'],
            'protocol_sha256': protocol_hash(), 'curriculum_sha256': curriculum_hash()}


def _expected_counters(name):
    updates = 0 if name == 'initial' else 64 if name == 'baseline' else 112
    prefix_tokens = 0 if name == 'initial' else 1360 if name == 'baseline' else 2384
    return dict(zip(COUNTER_NAMES, (updates, updates * 8, prefix_tokens, updates * 16)))


def _validate_model(saved, name):
    need(type(saved) is dict and set(saved) == {'encoding', 'model_b64', 'model_sha256',
         'parameter_sha256', 'counters'}, 'closed_model_envelope_required')
    need(saved['encoding'] == 'base64' and type(saved['model_b64']) is str
         and len(saved['model_b64']) <= 174764, 'bounded_model_encoding_required')
    try:
        raw = base64.b64decode(saved['model_b64'], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise LabError('invalid_model_encoding') from exc
    need(base64.b64encode(raw).decode('ascii') == saved['model_b64']
         and 12 < len(raw) <= 131072 and raw[:8] == b'NBDG064\x00', 'invalid_model_blob')
    need(_hash(saved['model_sha256']) and hashlib.sha256(raw).hexdigest() == saved['model_sha256'],
         'model_digest_mismatch')
    size = struct.unpack('<I', raw[8:12])[0]
    need(0 < size <= 8192 and 12 + size < len(raw), 'model_metadata_extent')
    meta = _json(raw[12:12 + size], 8192)
    fields = {'schema', 'vocabulary', 'vocabulary_sha256', 'protocol_sha256', 'parameter_sha256',
              'embedding', 'hidden', 'root_seed', 'training_updates', 'training_examples',
              'prefix_tokens_seen', 'target_tokens_seen', 'pretrained', 'glif_integrated'}
    need(type(meta) is dict and set(meta) == fields, 'closed_model_metadata_required')
    need(meta['schema'] == 'newbrain.trained-dialogue.state.hidden64.v1'
         and meta['vocabulary'] == list(WORDS)
         and meta['vocabulary_sha256'] == hashlib.sha256(json.dumps(list(WORDS), separators=(',', ':')).encode('ascii')).hexdigest()
         and meta['protocol_sha256'] == protocol_hash() and type(meta['embedding']) is int and meta['embedding'] == 16
         and type(meta['hidden']) is int and meta['hidden'] == 64 and type(meta['root_seed']) is int
         and meta['root_seed'] == locked_protocol()['root_seed']
         and meta['pretrained'] is False and meta['glif_integrated'] is False, 'model_identity_mismatch')
    expected = _expected_counters(name)
    need(type(saved['counters']) is dict and set(saved['counters']) == set(COUNTER_NAMES)
         and all(type(saved['counters'][k]) is int and type(meta[k]) is int
                 and saved['counters'][k] == meta[k] == expected[k] for k in COUNTER_NAMES),
         'model_counters_mismatch')
    shapes = {'E': (len(WORDS), 16), 'Wxh': (16, 64), 'Whh': (64, 64),
              'bh': (64,), 'Wy': (64, len(WORDS)), 'by': (len(WORDS),)}
    payload, offset, digest = raw[12 + size:], 0, hashlib.sha256()
    need(len(payload) == sum(math.prod(shape) for shape in shapes.values()) * 8, 'model_payload_extent')
    for key, shape in shapes.items():
        length = math.prod(shape) * 8
        chunk = payload[offset:offset + length]
        need(all(math.isfinite(v[0]) and abs(v[0]) <= 1000.0 for v in struct.iter_unpack('<d', chunk)),
             'nonfinite_model_parameters')
        digest.update(key.encode('ascii')); digest.update(str(shape).encode('ascii')); digest.update(chunk)
        offset += length
    need(_hash(saved['parameter_sha256']) and digest.hexdigest() == saved['parameter_sha256']
         == meta['parameter_sha256'], 'parameter_digest_mismatch')
    return raw


def _validate_observation(row, case, checkpoint=None):
    required = {'case_id', 'prefix', 'expected_tokens', 'generation', 'exact_correct', 'target_loss',
                'first_distribution', 'after_teacher_distribution', 'completed_updates', 'parameter_sha256', 'error'}
    need(type(row) is dict and set(row) == required and row['case_id'] == case['id']
         and row['prefix'] == case['prefix'] and row['expected_tokens'] == case['answer']
         and row['error'] is None, 'observation_identity_mismatch')
    need(type(row['completed_updates']) is int and 0 <= row['completed_updates'] <= 112
         and _hash(row['parameter_sha256']) and type(row['target_loss']) is float
         and math.isfinite(row['target_loss']) and row['target_loss'] >= 0, 'invalid_observation_scalar')
    for key in ('first_distribution', 'after_teacher_distribution'):
        values = row[key]
        need(type(values) is list and len(values) == len(WORDS)
             and all(type(v) is float and math.isfinite(v) and 0 <= v <= 1 for v in values)
             and abs(sum(values) - 1) <= 1e-12, 'invalid_whole_probability_distribution')
    gen = row['generation']
    need(type(gen) is dict and set(gen) == {'schema', 'backend', 'tokens', 'answer_text',
         'terminated_with_eos', 'length_limit_reached', 'unknown_prefix_tokens', 'parameter_sha256',
         'qwen_calls_in_this_module', 'full_conversation_demonstrated', 'runtime_qualified'}, 'closed_generation_required')
    need(gen['schema'] == 'newbrain.trained-dialogue.generation.v1'
         and gen['backend'] == 'newbrain.numpy_prefix_rnn_token_decoder_hidden64_v1'
         and type(gen['tokens']) is list and len(gen['tokens']) <= 16
         and all(type(token) is str and token in ('<UNK>',) + WORDS[7:] for token in gen['tokens'])
         and gen['answer_text'] == ' '.join(gen['tokens'])
         and type(gen['terminated_with_eos']) is bool and type(gen['length_limit_reached']) is bool
         and gen['length_limit_reached'] is not gen['terminated_with_eos']
         and (gen['terminated_with_eos'] or len(gen['tokens']) == 16)
         and type(gen['unknown_prefix_tokens']) is int and gen['unknown_prefix_tokens'] == 0
         and type(gen['qwen_calls_in_this_module']) is int and gen['qwen_calls_in_this_module'] == 0
         and gen['full_conversation_demonstrated'] is False and gen['runtime_qualified'] is False
         and gen['parameter_sha256'] == row['parameter_sha256'], 'invalid_generation_output')
    need(type(row['exact_correct']) is bool and row['exact_correct'] == (
        gen['tokens'] == case['answer'] and gen['terminated_with_eos']), 'incorrect_decision_record')
    if checkpoint is not None:
        need(row['completed_updates'] == checkpoint['counters']['training_updates']
             and row['parameter_sha256'] == checkpoint['parameter_sha256'], 'evaluation_checkpoint_mismatch')


def _validate_evaluation(value, checkpoint):
    need(type(value) is dict and set(value) == {'old', 'new', 'heldout'}, 'closed_evaluation_required')
    curriculum = locked_curriculum()
    for split in value:
        need(type(value[split]) is list and len(value[split]) == len(curriculum[split]), 'evaluation_extent')
        for row, case in zip(value[split], curriculum[split]):
            _validate_observation(row, case, checkpoint)


def validate_state(envelope, report, owner):
    """Validate all published data without loading NumPy or executing a model."""
    from .source import PYTHON_VERSIONS
    binding = _binding(owner)
    need(type(envelope) is dict and set(envelope) == {'schema', *BINDINGS, 'models', 'report_sha256'}
         and envelope['schema'] == 'aster.synthetic-text-state.v1', 'closed_state_required')
    need(type(report) is dict and set(report) == {'schema', *BINDINGS, 'curriculum', 'protocol', 'runtime',
         'initial', 'baseline', 'warmup_updates', 'arms', 'actual_total_sgd_calls', 'engineering_run_completed',
         'all_scientific_goals_met', 'scope', 'upstream_probe_ledger_used_for_actual_counters', 'errors'}
         and report['schema'] == 'aster.synthetic-text-report.v1', 'closed_report_required')
    need(all(envelope[k] == report[k] == v for k, v in binding.items()), 'state_binding_mismatch')
    need(envelope['report_sha256'] == hashlib.sha256(canonical(report)).hexdigest(), 'report_digest_mismatch')
    need(canonical(report['curriculum']) == canonical(locked_curriculum())
         and canonical(report['protocol']) == canonical(locked_protocol()), 'locked_protocol_mismatch')
    runtime = report['runtime']
    need(type(runtime) is dict and set(runtime) == {'python', 'implementation', 'numpy', 'platform', 'pointer_bits', 'scope'}
         and type(runtime['python']) is str and runtime['python'] in PYTHON_VERSIONS
         and runtime['implementation'] == 'CPython'
         and runtime['numpy'] == '2.3.5' and runtime['platform'] in ('linux', 'darwin', 'win32')
         and type(runtime['pointer_bits']) is int and runtime['pointer_bits'] in (32, 64)
         and runtime['scope'] == 'version pins; not complete native binary or whole-process qualification', 'runtime_record_mismatch')
    need(report['scope'] == 'Opt-in synthetic experiment; no production imports, owner-state reuse, provider or network calls',
         'report_scope_mismatch')
    need(type(envelope['models']) is dict and set(envelope['models']) == set(MODEL_NAMES), 'model_set_mismatch')
    for name, model in envelope['models'].items():
        _validate_model(model, name)
    for phase in ('initial', 'baseline'):
        section = report[phase]
        need(type(section) is dict and set(section) == {'counters', 'evaluation'}
             and canonical(section['counters']) == canonical(envelope['models'][phase]['counters']), 'phase_counters_mismatch')
        _validate_evaluation(section['evaluation'], envelope['models'][phase])
    need(type(report['arms']) is dict and set(report['arms']) == set(METHODS), 'arm_set_mismatch')
    need(type(report['warmup_updates']) is list and len(report['warmup_updates']) == 64,
         'warmup_extent_mismatch')
    previous_hash = envelope['models']['initial']['parameter_sha256']
    for index, row in enumerate(report['warmup_updates']):
        need(type(row) is dict and set(row) == {'index', 'batch', 'split', 'result'}
             and _ints(row, 'index', 'batch') and row['index'] == index and row['batch'] == index % 6 and row['split'] == 'old', 'warmup_order_mismatch')
        previous_hash = _validate_receipt(row['result'], previous_hash, index + 1, 'old', row['batch'])
    need(previous_hash == envelope['models']['baseline']['parameter_sha256'], 'warmup_hash_chain_mismatch')
    from .training import goal_results
    for method, arm in report['arms'].items():
        need(type(arm) is dict and set(arm) == {'method', 'start_counters', 'end_counters', 'updates',
             'probe_ledger', 'orders', 'evaluation', 'goals', 'errors'} and arm['method'] == method
             and canonical(arm['start_counters']) == canonical(envelope['models']['baseline']['counters'])
             and canonical(arm['end_counters']) == canonical(envelope['models'][method]['counters']) and arm['errors'] == [], 'arm_identity_mismatch')
        _validate_evaluation(arm['evaluation'], envelope['models'][method])
        need(canonical(arm['goals']) == canonical(goal_results(report['baseline']['evaluation'], arm['evaluation'])), 'goal_record_mismatch')
        _validate_arm_trace(arm, envelope['models']['baseline']['parameter_sha256'], envelope['models'][method]['parameter_sha256'])
    need(type(report['actual_total_sgd_calls']) is int and report['actual_total_sgd_calls'] == 208
         and report['engineering_run_completed'] is True and report['upstream_probe_ledger_used_for_actual_counters'] is False
         and report['errors'] == [] and type(report['all_scientific_goals_met']) is bool
         and report['all_scientific_goals_met'] == all(a['goals']['all_scientific_goals_met'] for a in report['arms'].values()),
         'run_accounting_mismatch')
    # Canonical encoding rejects hidden NaNs, hostile custom values, and excessive nesting.
    need(len(canonical(envelope)) <= STATE_CAP and len(canonical(report)) <= REPORT_CAP, 'state_size_limit')
    return envelope, report


def _validate_receipt(receipt, before, completed, split, batch):
    need(type(receipt) is dict and set(receipt) == {'schema', 'loss', 'parameter_sha256_before',
         'parameter_sha256_after', 'parameter_bytes_changed', 'gradient_norm', 'clip_multiplier',
         'new_exposures', 'updates_completed', 'runtime_qualified'}, 'closed_update_receipt_required')
    need(receipt['schema'] == 'newbrain.trained-dialogue.update.v1'
         and receipt['parameter_sha256_before'] == before and _hash(receipt['parameter_sha256_after'])
         and type(receipt['updates_completed']) is int and receipt['updates_completed'] == completed
         and receipt['runtime_qualified'] is False and type(receipt['parameter_bytes_changed']) is bool
         and receipt['parameter_bytes_changed'] == (before != receipt['parameter_sha256_after']), 'update_hash_chain_mismatch')
    for key in ('loss', 'gradient_norm', 'clip_multiplier'):
        need(type(receipt[key]) is float and math.isfinite(receipt[key]) and receipt[key] >= 0,
             'invalid_update_scalar')
    need(0 < receipt['clip_multiplier'] <= 1, 'invalid_clip_multiplier')
    case = locked_curriculum()['new' if split == 'new' else 'old'][batch]
    need(type(receipt['new_exposures']) is dict and _ints(receipt['new_exposures'], 'examples', 'prefix_tokens', 'target_tokens_including_eos')
         and receipt['new_exposures'] == {'examples': 8, 'prefix_tokens': len(case['prefix']) * 8,
         'target_tokens_including_eos': 16}, 'update_exposures_mismatch')
    return receipt['parameter_sha256_after']


def _validate_arm_trace(arm, initial_hash, final_hash):
    probes, orders, updates = arm['probe_ledger'], arm['orders'], arm['updates']
    need(type(probes) is list and len(probes) == 36 and type(orders) is list and len(orders) == 6
         and type(updates) is list and len(updates) == 48, 'arm_trace_extent_mismatch')
    # Validate relative blocks independently, without importing numerical source.
    completed, current_hash, update_index = 64, initial_hash, 0
    method = arm['method']
    for ordinal, order in enumerate(orders):
        cycle, new_pass = divmod(ordinal, 3)
        need(type(order) is dict and set(order) == {'cycle', 'new_pass', 'completed_updates',
             'priority_order', 'chosen_order', 'blocks', 'evaluation_rows_used'}
             and _ints(order, 'cycle', 'new_pass', 'completed_updates')
             and order['cycle'] == cycle and order['new_pass'] == new_pass
             and order['completed_updates'] == completed and order['evaluation_rows_used'] is False, 'order_boundary_mismatch')
        feedback = []
        for batch, case in enumerate(locked_curriculum()['new']):
            probe = probes[ordinal * 6 + batch]
            need(type(probe) is dict and set(probe) == {'schema', 'ordinal', 'method', 'cycle', 'new_pass', 'batch', 'observation'}
                 and _ints(probe, 'ordinal', 'cycle', 'new_pass', 'batch')
                 and probe['schema'] == 'aster.exposed-text-probe.v1' and probe['ordinal'] == ordinal * 6 + batch
                 and probe['method'] == method and probe['cycle'] == cycle and probe['new_pass'] == new_pass
                 and probe['batch'] == batch, 'probe_order_mismatch')
            observation = probe['observation']; _validate_observation(observation, case)
            need(observation['completed_updates'] == completed and observation['parameter_sha256'] == current_hash,
                 'probe_counter_or_hash_mismatch')
            feedback.append(observation)
        ranked = sorted(range(6), key=lambda i: (feedback[i]['exact_correct'], -feedback[i]['target_loss'], i))
        chosen = ranked if method == 'ERROR_PRIORITIZED' else list(range(6))
        need(canonical(order['priority_order']) == canonical(ranked)
             and canonical(order['chosen_order']) == canonical(chosen), 'exposed_ranking_mismatch')
        blocks = []
        for slot, batch in enumerate(chosen):
            blocks.append(['new', batch])
            if method != 'BLOCKED' and slot in (2, 5):
                blocks.append(['protected_old', 2 * new_pass + int(slot == 5)])
        if method == 'BLOCKED' and new_pass == 2:
            blocks.extend(['protected_old', batch] for batch in range(6))
        need(canonical(order['blocks']) == canonical(blocks), 'relative_blocks_mismatch')
        for split, batch in blocks:
            row = updates[update_index]
            need(type(row) is dict and set(row) == {'cycle', 'new_pass', 'split', 'batch', 'result'}
                 and _ints(row, 'cycle', 'new_pass', 'batch')
                 and row['cycle'] == cycle and row['new_pass'] == new_pass
                 and row['split'] == split and row['batch'] == batch, 'training_order_mismatch')
            completed += 1
            current_hash = _validate_receipt(row['result'], current_hash, completed, split, batch)
            update_index += 1
    need(completed == 112 and current_hash == final_hash, 'arm_final_hash_mismatch')


def _rename_exclusive(source, target):
    """Atomic directory publication which cannot replace a raced destination."""
    if os.name == 'nt':
        os.rename(source, target)  # Windows rename refuses an existing destination.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux'):
        function = getattr(libc, 'renameat2', None)
        need(function is not None, 'atomic_publication_unsupported')
        function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        result = function(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    elif sys.platform == 'darwin':
        function = getattr(libc, 'renamex_np', None)
        need(function is not None, 'atomic_publication_unsupported')
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        function.restype = ctypes.c_int
        result = function(os.fsencode(source), os.fsencode(target), 4)
    else:
        raise LabError('atomic_publication_unsupported')
    if result:
        number = ctypes.get_errno()
        raise LabError('state_destination_occupied' if number in (errno.EEXIST, errno.ENOTEMPTY)
                       else 'atomic_publication_failed')


def _sync_directory(path):
    if os.name != 'nt':
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def publish_state(state_dir, envelope, report):
    target = check_destination(state_dir)
    validate_state(envelope, report, envelope.get('owner'))
    state_raw, report_raw = canonical(envelope), canonical(report)
    manifest = {'schema': 'aster.synthetic-text-publication.v1',
                **{key: envelope[key] for key in BINDINGS},
                'files': {'state.json': {'bytes': len(state_raw), 'sha256': hashlib.sha256(state_raw).hexdigest()},
                          'report.json': {'bytes': len(report_raw), 'sha256': hashlib.sha256(report_raw).hexdigest()}}}
    stage = None
    committed = False
    try:
        stage = Path(tempfile.mkdtemp(prefix='.aster-text-stage-', dir=target.parent))
        for filename, raw in (('state.json', state_raw), ('report.json', report_raw), ('manifest.json', canonical(manifest))):
            descriptor = os.open(stage / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                need(stream.write(raw) == len(raw), 'state_write_incomplete')
                stream.flush(); os.fsync(stream.fileno())
            need(_read_plain(stage / filename, len(raw)) == raw, 'state_readback_mismatch')
        read_state(stage, envelope['owner'])
        _sync_directory(stage)
        check_destination(target)
        _rename_exclusive(stage, target)
        committed = True
        stage = None
        _sync_directory(target.parent)
    except OSError as exc:
        raise LabError('state_published_durability_unconfirmed' if committed else 'state_publication_failed') from exc
    finally:
        if stage is not None:
            shutil.rmtree(stage)
    return summary(envelope, report)


def read_state(state_dir, owner=DEFAULT_OWNER):
    validate_owner(owner)
    target = _safe_path(state_dir)
    need(target.is_dir(), 'state_directory_required')
    try:
        with os.scandir(target) as entries:
            need({entry.name for entry in itertools.islice(entries, len(FILES) + 1)} == set(FILES),
                 'state_file_set_mismatch')
    except OSError as exc:
        raise LabError('state_directory_unavailable') from exc
    manifest = _json(_read_plain(target / 'manifest.json', MANIFEST_CAP), MANIFEST_CAP)
    need(type(manifest) is dict and set(manifest) == {'schema', *BINDINGS, 'files'}
         and manifest['schema'] == 'aster.synthetic-text-publication.v1'
         and all(manifest[k] == v for k, v in _binding(owner).items())
         and type(manifest['files']) is dict and set(manifest['files']) == {'state.json', 'report.json'}, 'publication_identity_mismatch')
    parsed = {}
    for name, cap in (('state.json', STATE_CAP), ('report.json', REPORT_CAP)):
        raw = _read_plain(target / name, cap)
        record = manifest['files'][name]
        need(type(record) is dict and set(record) == {'bytes', 'sha256'}
             and type(record['bytes']) is int and record['bytes'] == len(raw)
             and record['sha256'] == hashlib.sha256(raw).hexdigest(), 'publication_digest_mismatch')
        parsed[name] = _json(raw, cap)
    return validate_state(parsed['state.json'], parsed['report.json'], owner)


def summary(envelope, report):
    return {'schema': 'aster.synthetic-text-summary.v1',
            **{key: envelope[key] for key in BINDINGS},
            'engineering_run_completed': report['engineering_run_completed'],
            'actual_total_sgd_calls': report['actual_total_sgd_calls'],
            'all_scientific_goals_met': report['all_scientific_goals_met'],
            'arms': {method: {'counters': arm['end_counters'], 'goals': arm['goals'],
                             'parameter_sha256': envelope['models'][method]['parameter_sha256']}
                     for method, arm in report['arms'].items()},
            'report_file': 'report.json', 'state_file': 'state.json',
            'production_backend_enabled': False, 'general_language_qualified': False,
            'method_superiority_established': False,
            'scope': 'Single fixed synthetic two-label experiment'}


def inspect_state(state_dir, owner=DEFAULT_OWNER):
    envelope, report = read_state(state_dir, owner)
    return {**summary(envelope, report), 'model_executed': False, 'numpy_required': False}
