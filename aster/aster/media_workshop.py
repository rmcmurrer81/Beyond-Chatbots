"""Bounded standard-library PCM WAV inspection and reversible frame-exact trim.

Workspace-only inputs and scoped output copies. No playback, subprocess, network,
codec install, TTS, model inference, video/avatars, or edits to supplied voice assets.
"""
import hashlib
import io
import json
import struct
import wave

from .files import MAX_BYTES, parts
from . import voice

OUTPUT_PREFIX = ('media', 'exports')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wav(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES or len(raw) < 44:
        raise ValueError('WAV must be bytes within the 256 KiB workspace limit')
    if raw[:4] != b'RIFF' or raw[8:12] != b'WAVE' or struct.unpack_from('<I', raw, 4)[0] + 8 != len(raw):
        raise ValueError('Expected complete RIFF/WAVE without trailing bytes')
    position, fmt, pcm = 12, None, None
    while position < len(raw):
        if position + 8 > len(raw):
            raise ValueError('Truncated WAV chunk header')
        kind, size = struct.unpack_from('<4sI', raw, position)
        start, end = position + 8, position + 8 + size
        if end > len(raw):
            raise ValueError('Truncated WAV chunk data')
        if kind == b'fmt ':
            if fmt is not None or size != 16:
                raise ValueError('Exactly one classic 16-byte PCM format chunk is required')
            fmt = struct.unpack_from('<HHIIHH', raw, start)
        elif kind == b'data':
            if pcm is not None or fmt is None:
                raise ValueError('Exactly one data chunk after the PCM format is required')
            pcm = raw[start:end]
        # Python's wave writer omits the final odd-byte pad; accept that common
        # form but never accept a truncated intermediate chunk or extra payload.
        position = end if end == len(raw) else end + (size % 2)
    if fmt is None or pcm is None or position != len(raw):
        raise ValueError('Missing or malformed WAV format/data chunks')
    tag, channels, rate, byte_rate, align, bits = fmt
    if (tag != 1 or channels not in (1, 2) or bits not in (8, 16, 24, 32)
            or not 8000 <= rate <= 192000 or align != channels * bits // 8
            or byte_rate != rate * align or not pcm or len(pcm) % align):
        raise ValueError('Only complete mono/stereo integer PCM WAV, 8/16/24/32-bit, 8..192 kHz is supported')
    frames = len(pcm) // align
    try:
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes(), audio.getcomptype()) != (channels, bits // 8, rate, frames, 'NONE'):
                raise ValueError('WAV parser metadata mismatch')
            if audio.readframes(frames + 1) != pcm:
                raise ValueError('WAV parser data mismatch')
    except (wave.Error, EOFError) as error:
        raise ValueError('Invalid PCM WAV') from error
    return {'format': f'PCM{bits} WAV', 'channels': channels, 'sample_width_bits': bits,
            'sample_rate_hz': rate, 'frames': frames, 'duration_seconds': frames / rate,
            'duration_fraction': f'{frames}/{rate}', 'bytes': len(raw), 'sha256': _sha(raw),
            'pcm_sha256': _sha(pcm)}, pcm


class MediaWorkshop:
    def __init__(self, store, files):
        self.store, self.files = store, files

    def inspect(self, path):
        names = parts(path)
        if not names[-1].lower().endswith('.wav'):
            raise ValueError('Only workspace PCM .wav files are supported')
        metadata, _ = _wav(self.files.read(path))
        return dict(metadata, path=path, status='inspected_local_pcm', automatic_playback=False,
                    model_generated=False, listening_review='not_performed')

    def inspect_voice(self):
        """Reuse full pinned-asset/provenance checks; never copy or mutate pack."""
        return voice.inspect_voice()

    def _plan(self, path, start_frame, end_frame, output_path):
        source_names, output_names = parts(path), parts(output_path)
        if (not source_names[-1].lower().endswith('.wav') or output_names[:2] != OUTPUT_PREFIX
                or len(output_names) < 3 or not output_names[-1].lower().endswith('.wav')):
            raise ValueError('Use a PCM .wav input and output under media/exports/*.wav')
        if path.casefold() == output_path.casefold():
            raise ValueError('Output must be a separate copy, never the source')
        metadata, pcm = _wav(self.files.read(path))
        if (type(start_frame) is not int or type(end_frame) is not int
                or not 0 <= start_frame < end_frame <= metadata['frames']):
            raise ValueError('Use integer frames with 0 <= start < end <= frame count')
        # Existing output bytes are part of approval, and Files journals them.
        before = self.files.snapshot(output_path)
        width = metadata['channels'] * metadata['sample_width_bits'] // 8
        selected = pcm[start_frame * width:end_frame * width]
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as audio:
            audio.setnchannels(metadata['channels']); audio.setsampwidth(metadata['sample_width_bits'] // 8)
            audio.setframerate(metadata['sample_rate_hz']); audio.writeframes(selected)
        output = buffer.getvalue()
        output_metadata, verified = _wav(output)
        if verified != selected:
            raise ValueError('Selected PCM bytes failed output verification')
        plan = {'path': path, 'source_sha256': metadata['sha256'], 'start_frame': start_frame,
                'end_frame': end_frame, 'output_path': output_path,
                'previous_output_sha256': _sha(before) if before is not None else None,
                'output_sha256': output_metadata['sha256']}
        plan_hash = _sha(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode())
        return dict(plan, sha256=plan_hash, approval_scope='exact_trim_plan_and_existing_output',
                    source=metadata, output=output_metadata, status='preview_only_not_written',
                    dropped_ancillary_metadata=True, original_preserved=True,
                    automatic_playback=False, model_generated=False), output

    def preview_trim(self, path, start_frame, end_frame, output_path):
        return self._plan(path, start_frame, end_frame, output_path)[0]

    def trim(self, path, start_frame, end_frame, output_path, *, expected_sha256, approved=False):
        if approved is not True:
            raise ValueError('Explicit approval is required to write a trimmed copy')
        preview, output = self._plan(path, start_frame, end_frame, output_path)
        if type(expected_sha256) is not str or expected_sha256 != preview['sha256']:
            raise ValueError('Approval must match current trim plan SHA-256; preview again')
        change_id = self.files.change(output_path, output, kind='media.trim_pcm_wav')
        return dict(preview, status='trimmed_local_copy', change_id=change_id,
                    undo='Use Files.undo(change_id); differences detected at revalidation block undo; do not edit concurrently')

    def status(self):
        return {'status': 'local_pcm_wav_tools', 'input_limit_bytes': MAX_BYTES,
                'output_scope': 'media/exports/', 'operations': ['inspect', 'preview_trim', 'trim', 'inspect_voice'],
                'source_asset_edits': False, 'automatic_playback': False, 'subprocess_enabled': False,
                'network_enabled': False, 'live_synthesis': False, 'model_inference': False,
                'video_editing': False, 'avatars': False, 'videostudio_reuse': 'reviewed_not_imported_dependency_and_rights_boundaries',
                'zotero_integration': False, 'listening_review': 'not_performed'}
