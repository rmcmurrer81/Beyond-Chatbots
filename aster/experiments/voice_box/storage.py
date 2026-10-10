"""Data-only bundles, finite reads and atomic no-clobber export.

Uses the already reviewed stdlib-only filesystem helpers from the text lab.
No numerical model is imported, initialized or run by these helpers.
"""
import hashlib
import io
import itertools
import os
from pathlib import Path
import shutil
import tempfile
import wave
from experiments.newbrain_text.persistence import (
    LabError, _read_plain, _rename_exclusive, _safe_path, _sync_directory, check_destination)
from .protocol import RATE, VoiceError, canonical, digest, need, owner_id, parse_json, validate
from .synth import VoiceBox, engine_binding, measurements, render, validate_checkpoint, wav_bytes

CAPS = {'intent.json': 32768, 'checkpoint.json': 4096, 'receipt.json': 8192,
        'preview.wav': RATE * 8 * 2 + 44}


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
    box = VoiceBox(plan)
    split = box.frames // 2
    first = box.render_frames(split)
    checkpoint = box.checkpoint()
    rest = box.render_frames(box.frames)
    restored = VoiceBox.restore(plan, checkpoint, plan['owner'])
    need(restored.render_frames(restored.frames) == rest, 'checkpoint_resume_mismatch')
    pcm = first + rest
    wav = wav_bytes(pcm)
    receipt = {'schema': 'aster.voice-render.v1', 'owner': plan['owner'], 'binding': box.binding,
               'intent_sha256': digest(plan), 'origin': plan['origin'], 'measurement': measurements(pcm),
               'checkpoint_resume_exact': True, 'checkpoint_frame': split,
               'wav_sha256': hashlib.sha256(wav).hexdigest(), 'automatic_playback': False,
               'production_brain_enabled': False, 'intelligible_speech_verified': False,
               'perceptual_voice_gender_verified': False}
    files = {'intent.json': canonical(plan), 'checkpoint.json': canonical(checkpoint),
             'receipt.json': canonical(receipt), 'preview.wav': wav}
    manifest = {'schema': 'aster.voice-bundle.v1', 'owner': plan['owner'],
                'files': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                          for name, raw in files.items()}}
    files['manifest.json'] = canonical(manifest)
    stage = None
    committed = False
    try:
        stage = Path(tempfile.mkdtemp(prefix='.aster-voice-', dir=target.parent))
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
         and manifest['schema'] == 'aster.voice-bundle.v1' and manifest['owner'] == owner
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
                 and wav.getcomptype() == 'NONE' and wav.getnframes() == sum(
                     g['duration_ms'] * (RATE // 1000) for g in plan['gestures']), 'voice_wav_format_mismatch')
            pcm = wav.readframes(RATE * 8 + 1)
    except (wave.Error, EOFError) as exc:
        raise VoiceError('voice_wav_refused') from exc
    need(wav_bytes(pcm) == files['preview.wav'], 'voice_wav_noncanonical')
    receipt = files['receipt.json']
    need(type(receipt) is dict and set(receipt) == {'schema', 'owner', 'binding', 'intent_sha256',
         'origin', 'measurement', 'checkpoint_resume_exact', 'checkpoint_frame', 'wav_sha256',
         'automatic_playback', 'production_brain_enabled', 'intelligible_speech_verified',
         'perceptual_voice_gender_verified'}, 'voice_receipt_refused')
    need(receipt['schema'] == 'aster.voice-render.v1' and receipt['owner'] == owner
         and receipt['intent_sha256'] == digest(plan) and receipt['origin'] == plan['origin']
         and canonical(receipt['measurement']) == canonical(measurements(pcm))
         and receipt['wav_sha256'] == hashlib.sha256(files['preview.wav']).hexdigest()
         and receipt['automatic_playback'] is False and receipt['production_brain_enabled'] is False
         and receipt['intelligible_speech_verified'] is False and receipt['perceptual_voice_gender_verified'] is False
         and receipt['checkpoint_resume_exact'] is True
         and type(receipt['checkpoint_frame']) is int and receipt['checkpoint_frame'] == len(pcm) // 4,
         'voice_receipt_mismatch')
    checkpoint = files['checkpoint.json']
    saved = validate_checkpoint(plan, checkpoint)
    need(saved['binding'] == receipt['binding'] and saved['cursor'] == receipt['checkpoint_frame'],
         'voice_checkpoint_mismatch')
    return plan, checkpoint, receipt, pcm


def inspect_bundle(directory, owner='synthetic_aster'):
    _, _, receipt, _ = read_bundle(directory, owner)
    return {**receipt, 'inspected_without_synthesis': True,
            'checkpoint_resume_checked_now': False,
            'same_engine_runtime': receipt['binding'] == engine_binding()}


def recheck_bundle(directory, owner='synthetic_aster'):
    plan, checkpoint, receipt, pcm = read_bundle(directory, owner)
    box = VoiceBox.restore(plan, checkpoint, owner)
    offset = box.cursor * 2
    need(box.render_frames(box.frames) == pcm[offset:], 'checkpoint_resume_mismatch')
    need(render(plan) == pcm, 'voice_rerender_mismatch')
    return {'schema': 'aster.voice-recheck.v1', 'owner': owner,
            'wav_sha256': receipt['wav_sha256'], 'render_exact': True, 'checkpoint_resume_exact': True,
            'production_brain_enabled': False, 'automatic_playback': False}
