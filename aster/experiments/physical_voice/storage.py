"""Finite data-only bundles with atomic no-clobber output and verified PCM.

The parent directory must already exist and be trusted against concurrent
replacement. Reviewed stdlib-only text-lab helpers reject symlinks, junctions,
hardlinks, nonregular files, oversize reads and an occupied destination. No
inspection calls a renderer step or trains/executes a model.
"""
import hashlib
import io
import itertools
import os
from pathlib import Path
import shutil
import tempfile
import time
import wave
from experiments.newbrain_text.persistence import (
    LabError, _read_plain, _rename_exclusive, _safe_path, _sync_directory, check_destination)
from .protocol import (INTENT_CAP, MAX_MS, RATE, VoiceError, canonical, digest, frame_count,
                       need, owner_id, parse_json, validate)
from .pipeline import (MAX_OPERATION_SECONDS, PhysicalVoice, engine_binding, measurements, timing,
                       validate_binding, validate_checkpoint, validate_diagnostics, wav_bytes)

CAPS = {'intent.json': INTENT_CAP, 'checkpoint.json': 65536, 'receipt.json': 32768,
        'preview.wav': RATE * MAX_MS // 1000 * 2 + 44}
CLAIMS = {'automatic_playback': False, 'production_brain_enabled': False,
          'intelligible_speech_verified': False, 'perceptual_voice_gender_verified': False,
          'anatomical_fidelity_verified': False, 'combined_fluid_tissue_acoustic_energy_closed': False,
          'acoustic_hearing_safety_verified': False, 'brain_executed': False, 'pretrained_voice_used': False}


def read_plain(path, cap):
    try:
        return _read_plain(_safe_path(path), cap)
    except LabError as exc:
        raise VoiceError('voice_file_refused') from exc


def render_bundle(output, plan):
    plan = validate(plan)
    try:
        target = check_destination(output)
    except LabError as exc:
        raise VoiceError('voice_destination_refused') from exc
    deadline = time.monotonic() + MAX_OPERATION_SECONDS
    box = PhysicalVoice(plan, deadline=deadline)
    split = box.frames // 2
    first = box.render_frames(split)
    checkpoint = box.checkpoint()
    rest = box.render_frames(box.frames)
    restored = PhysicalVoice.restore(plan, checkpoint, plan['owner'], deadline=deadline)
    need(restored.render_frames(restored.frames) == rest, 'checkpoint_resume_mismatch')
    need(canonical(restored.diagnostics()) == canonical(box.diagnostics()), 'checkpoint_diagnostics_mismatch')
    pcm = first + rest
    # Independent complete replay also establishes output and cumulative metrics.
    replay = PhysicalVoice(plan, deadline=deadline)
    need(replay.render_frames(replay.frames) == pcm, 'voice_rerender_mismatch')
    need(canonical(replay.diagnostics()) == canonical(box.diagnostics()), 'rerender_diagnostics_mismatch')
    wav = wav_bytes(pcm)
    measured = measurements(pcm)
    need(measured['within_delivery_ceiling'] and measured['first_sample'] == measured['last_sample'] == 0,
         'delivery_measurement_refused')
    receipt = {'schema': 'aster.physical-voice-render.v1', 'owner': plan['owner'], 'binding': box.binding,
               'intent_sha256': digest(plan), 'origin': plan['origin'], 'measurement': measured,
               'diagnostics': box.diagnostics(), 'timing': timing(), 'render_exact': True,
               'checkpoint_resume_exact': True, 'checkpoint_diagnostics_exact': True,
               'checkpoint_frame': split, 'wav_sha256': hashlib.sha256(wav).hexdigest(), **CLAIMS}
    files = {'intent.json': canonical(plan), 'checkpoint.json': canonical(checkpoint),
             'receipt.json': canonical(receipt), 'preview.wav': wav}
    need(all(len(raw) <= CAPS[name] for name, raw in files.items()), 'voice_bundle_size_refused')
    manifest = {'schema': 'aster.physical-voice-bundle.v1', 'owner': plan['owner'],
                'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                          for name, raw in files.items()}}
    files['manifest.json'] = canonical(manifest)
    stage = None
    committed = False
    try:
        stage = Path(tempfile.mkdtemp(prefix='.aster-physical-voice-', dir=target.parent))
        for name, raw in files.items():
            descriptor = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                need(stream.write(raw) == len(raw), 'voice_write_incomplete')
                stream.flush(); os.fsync(stream.fileno())
            need(read_plain(stage / name, len(raw)) == raw, 'voice_readback_mismatch')
        inspect_bundle(stage, plan['owner'])
        _sync_directory(stage)
        check_destination(target)
        _rename_exclusive(stage, target)
        committed, stage = True, None
        _sync_directory(target.parent)
    except (LabError, OSError) as exc:
        raise VoiceError('voice_published_durability_unconfirmed' if committed else 'voice_publication_failed') from exc
    except KeyboardInterrupt as exc:
        if committed:
            raise VoiceError('voice_published_durability_unconfirmed') from exc
        raise
    finally:
        if stage is not None:
            shutil.rmtree(stage)
    return receipt


def read_bundle(directory, owner):
    owner_id(owner)
    try:
        target = _safe_path(directory)
        need(target.is_dir(), 'voice_directory_required')
        with os.scandir(target) as entries:
            names = {entry.name for entry in itertools.islice(entries, len(CAPS) + 2)}
        need(names == {*CAPS, 'manifest.json'}, 'voice_file_set_mismatch')
    except (LabError, OSError) as exc:
        raise VoiceError('voice_directory_refused') from exc
    manifest = parse_json(read_plain(target / 'manifest.json', 4096), 4096)
    need(type(manifest) is dict and set(manifest) == {'schema', 'owner', 'files'}
         and manifest['schema'] == 'aster.physical-voice-bundle.v1' and manifest['owner'] == owner
         and type(manifest['files']) is dict and set(manifest['files']) == set(CAPS), 'voice_manifest_refused')
    files = {}
    for name, cap in CAPS.items():
        raw = read_plain(target / name, cap)
        row = manifest['files'][name]
        need(type(row) is dict and set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int
             and row['bytes'] == len(raw) and row['sha256'] == hashlib.sha256(raw).hexdigest(),
             'voice_file_digest_mismatch')
        files[name] = raw if name.endswith('.wav') else parse_json(raw, cap)
    plan = validate(files['intent.json'], owner)
    try:
        with wave.open(io.BytesIO(files['preview.wav']), 'rb') as wav:
            need(wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == RATE
                 and wav.getcomptype() == 'NONE' and wav.getnframes() == frame_count(plan), 'voice_wav_format_mismatch')
            pcm = wav.readframes(frame_count(plan) + 1)
    except (wave.Error, EOFError) as exc:
        raise VoiceError('voice_wav_refused') from exc
    need(wav_bytes(pcm) == files['preview.wav'], 'voice_wav_noncanonical')
    measured = measurements(pcm)
    receipt = files['receipt.json']
    need(type(receipt) is dict and set(receipt) == {'schema', 'owner', 'binding', 'intent_sha256',
         'origin', 'measurement', 'diagnostics', 'timing', 'render_exact', 'checkpoint_resume_exact',
         'checkpoint_diagnostics_exact', 'checkpoint_frame', 'wav_sha256', *CLAIMS}, 'voice_receipt_refused')
    validate_binding(receipt['binding'])
    need(receipt['schema'] == 'aster.physical-voice-render.v1' and receipt['owner'] == owner
         and receipt['intent_sha256'] == digest(plan) and receipt['origin'] == plan['origin']
         and canonical(receipt['measurement']) == canonical(measured)
         and measured['within_delivery_ceiling'] and measured['first_sample'] == measured['last_sample'] == 0
         and receipt['wav_sha256'] == hashlib.sha256(files['preview.wav']).hexdigest()
         and all(receipt[key] is value for key, value in CLAIMS.items())
         and receipt['render_exact'] is True and receipt['checkpoint_resume_exact'] is True
         and receipt['checkpoint_diagnostics_exact'] is True and canonical(receipt['timing']) == canonical(timing())
         and type(receipt['checkpoint_frame']) is int and receipt['checkpoint_frame'] == frame_count(plan) // 2,
         'voice_receipt_mismatch')
    validate_diagnostics(receipt['diagnostics'], plan)
    checkpoint = files['checkpoint.json']
    saved = validate_checkpoint(plan, checkpoint)
    need(saved['binding'] == receipt['binding'] and saved['cursor'] == receipt['checkpoint_frame'],
         'voice_checkpoint_mismatch')
    return plan, checkpoint, receipt, pcm


def inspect_bundle(directory, owner='synthetic_aster'):
    _, _, receipt, _ = read_bundle(directory, owner)
    return {'schema': 'aster.physical-voice-inspection.v1', 'owner': owner,
            'fresh_checks': {'closed_data': True, 'file_digests': True, 'wav_format': True,
                             'pcm_measurement': receipt['measurement'],
                             'same_engine_runtime': receipt['binding'] == engine_binding()},
            'stored_render_claims': {'render_exact': receipt['render_exact'],
                'checkpoint_resume_exact': receipt['checkpoint_resume_exact'],
                'checkpoint_diagnostics_exact': receipt['checkpoint_diagnostics_exact'],
                'diagnostics': receipt['diagnostics'], 'binding': receipt['binding']},
            'wav_sha256': receipt['wav_sha256'], 'synthesis_performed': False,
            'checkpoint_replay_checked_now': False, **CLAIMS}


def recheck_bundle(directory, owner='synthetic_aster'):
    plan, checkpoint, receipt, pcm = read_bundle(directory, owner)
    deadline = time.monotonic() + MAX_OPERATION_SECONDS
    box = PhysicalVoice.restore(plan, checkpoint, owner, deadline=deadline)
    offset = box.cursor * 2
    need(box.render_frames(box.frames) == pcm[offset:], 'checkpoint_resume_mismatch')
    need(canonical(box.diagnostics()) == canonical(receipt['diagnostics']), 'checkpoint_diagnostics_mismatch')
    replay = PhysicalVoice(plan, deadline=deadline)
    need(replay.render_frames(replay.frames) == pcm, 'voice_rerender_mismatch')
    need(canonical(replay.diagnostics()) == canonical(receipt['diagnostics']), 'rerender_diagnostics_mismatch')
    return {'schema': 'aster.physical-voice-recheck.v1', 'owner': owner,
            'wav_sha256': receipt['wav_sha256'], 'render_exact_checked_now': True,
            'checkpoint_resume_exact_checked_now': True, 'diagnostics_exact_checked_now': True,
            'synthesis_performed': True, **CLAIMS}
