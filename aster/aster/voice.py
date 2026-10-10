"""Inspect one supplied, prerecorded voice pack without activating any runtime.

The pinned bytes are an audition, never an AI response or a TTS implementation.
Reads are bounded and reject links/reparse points; playback is a separate manual
local-file action. Nothing here downloads, executes, serves, or opens the audio.
The checkout must remain owner-controlled, including during later manual playback.
"""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import struct
import wave


PROFILE_ID = 'aster_warm_female20s_v1'
PACK_PATH = Path(__file__).absolute().parent.parent / 'assets' / 'voices' / PROFILE_ID
# Pin the original supplied files, rather than trusting hashes inside the pack.
_FILE_SPECS = {
    'sample.wav': (1024 * 1024, '01768f1f65137623bfdd0e49b34211b7f31b315403ca5c7a5c75ed9e392bfd2f'),
    'profile.json': (16 * 1024, '78098cd456d00422937b5c5d17c081713feefadb5f51e3368fbf3e55e18de30f'),
    'generation.json': (16 * 1024, 'ca6b80f550c8b7746a37d523dac8bc61d4f8f07c3e0b683d11ca48cef37010f4'),
    'transcript.txt': (8 * 1024, '763396f63008e6e2f9556861a80e52aa577d73e70b644280d4a2a3af8e3f463d'),
    'preview.html': (16 * 1024, 'd79a3493996a602d236066e3f655ca32e47c9a34b1a0f4965805781bedcbbc8f'),
}


def _check_stat(info, limit, *, directory=False):
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('Links and reparse points are forbidden')
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('Expected a real directory')
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Expected a regular single-link file')
    elif info.st_size > limit:
        raise ValueError('Voice file exceeds inspection limit')


def _read_fd(fd, limit):
    before = os.fstat(fd)
    _check_stat(before, limit)
    chunks = bytearray()
    while len(chunks) <= limit:
        data = os.read(fd, min(65536, limit + 1 - len(chunks)))
        if not data:
            break
        chunks.extend(data)
    after = os.fstat(fd)
    _check_stat(after, limit)
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if (len(chunks) > limit or len(chunks) != before.st_size
            or any(getattr(before, name) != getattr(after, name) for name in fields)):
        raise ValueError('Voice file changed during inspection or exceeds limit')
    return bytes(chunks)


def _read_posix(path, limit):
    # Each open is relative to a retained, verified directory descriptor. A
    # replaced ancestor cannot redirect a later open through a symlink.
    required = ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')
    if any(not hasattr(os, name) for name in required) or os.open not in os.supports_dir_fd:
        raise RuntimeError('No safe no-follow file inspection on this platform')
    descriptors = []
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
        directory = os.open(path.anchor, flags)
        descriptors.append(directory)
        _check_stat(os.fstat(directory), 0, directory=True)
        for component in path.parts[1:-1]:
            directory = os.open(component, flags, dir_fd=directory)
            descriptors.append(directory)
            _check_stat(os.fstat(directory), 0, directory=True)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        descriptors.append(fd)
        return _read_fd(fd, limit)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _read_windows(path, limit):
    # Read-only native handles reject reparse points themselves, not only in a
    # path preflight. Retained ancestors disallow rename/delete and write sharing.
    # This path requires qualification on actual Windows; Linux tests do not
    # qualify it. No path-only fallback is used on native API errors.
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Information(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('creation', wintypes.FILETIME),
                    ('access', wintypes.FILETIME), ('write', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD),
                    ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                    ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]

    if (len(path.drive) != 2 or not path.drive[0].isascii()
            or not path.drive[0].isalpha() or path.drive[1] != ':'
            or path.anchor != path.drive + '\\'):
        raise ValueError('Voice inspection requires an absolute local drive path')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateFileW': (wintypes.HANDLE, [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]),
        'GetFileInformationByHandle': (wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(Information)]),
        'GetFileType': (wintypes.DWORD, [wintypes.HANDLE]),
        'GetDriveTypeW': (wintypes.UINT, [wintypes.LPCWSTR]),
        'CloseHandle': (wintypes.BOOL, [wintypes.HANDLE]),
    }
    for name, (restype, argtypes) in signatures.items():
        getattr(api, name).restype = restype
        getattr(api, name).argtypes = argtypes
    if api.GetDriveTypeW(path.anchor) != 3:
        raise ValueError('Voice inspection requires a local fixed drive')
    handles = []
    try:
        for index in range(len(path.parts)):
            candidate = Path(*path.parts[:index + 1])
            handle = api.CreateFileW(str(candidate), 0x80000000, 1, None, 3,
                                     0x00200000 | 0x02000000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = Information()
            if not api.GetFileInformationByHandle(handle, ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if api.GetFileType(handle) != 1 or info.attributes & (0x400 | 0x40):
                raise ValueError('Links, reparse points and special files are forbidden')
            directory = index < len(path.parts) - 1
            if bool(info.attributes & 0x10) != directory:
                raise ValueError('Unexpected voice file or directory type')
            if not directory and (info.links != 1 or (info.size_high << 32 | info.size_low) > limit):
                raise ValueError('Expected a bounded regular single-link file')
        fd = msvcrt.open_osfhandle(handles[-1], os.O_RDONLY | os.O_BINARY)
        handles.pop()  # The CRT now owns the file handle, including on read errors.
        try:
            return _read_fd(fd, limit)
        finally:
            os.close(fd)
    finally:
        for handle in reversed(handles):
            api.CloseHandle(handle)


def _read_regular(path, limit):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Voice pack path must be absolute without traversal')
    # Also provides a portable, explicit check for Windows reparse attributes.
    for candidate in reversed((path, *path.parents)):
        _check_stat(candidate.lstat(), limit, directory=candidate != path)
    if os.name == 'posix':
        return _read_posix(path, limit)
    if os.name == 'nt':
        return _read_windows(path, limit)
    raise RuntimeError('No safe voice inspection on this platform')


def _wav_metadata(data):
    with wave.open(io.BytesIO(data), 'rb') as audio:
        actual = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(),
                  audio.getnframes(), audio.getcomptype())
        if actual != (1, 2, 24000, 345600, 'NONE'):
            raise ValueError('Unexpected WAV format or frame count')
        pcm = audio.readframes(345601)
    if len(pcm) != 691200:
        raise ValueError('Truncated or oversized WAV PCM data')
    samples = (value[0] for value in struct.iter_unpack('<h', pcm))
    peak = squared = clipped = 0
    for value in samples:
        peak = max(peak, abs(value))
        squared += value * value
        clipped += value in (-32768, 32767)
    rms = math.sqrt(squared / 345600)
    if peak != 24063 or clipped != 0 or not math.isclose(rms, 2561.416849, abs_tol=0.000001):
        raise ValueError('Unexpected voice signal statistics')
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'channels': 1, 'sample_rate_hz': 24000, 'sample_width_bits': 16,
            'format': 'PCM16 WAV', 'frames': 345600, 'duration_seconds': 14.4,
            'peak_pcm16': peak, 'rms_pcm16': rms, 'clipped_samples': clipped}


def inspect_voice():
    """Return JSON-safe availability of the fixed pack; never play or synthesize.

    Missing, changed, unsafe, oversized, or unreadable assets fail closed. Paths
    are reported only after the entire pinned pack and preview pass inspection.
    """
    result = {'profile_id': PROFILE_ID, 'status': 'unavailable',
              'audition_available': False, 'prerecorded': True,
              'live_synthesis': False, 'synthesis_backend': 'unavailable_no_runtime',
              'ai_response': False, 'newbrain_contribution': False,
              'listening_review': 'not_performed', 'automatic_playback': False}
    try:
        files = {}
        for name, (limit, digest) in _FILE_SPECS.items():
            data = _read_regular(PACK_PATH / name, limit)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Integrity check failed for ' + name)
            files[name] = data
        metadata = _wav_metadata(files['sample.wav'])
        profile = json.loads(files['profile.json'].decode('utf-8'))
        generation = json.loads(files['generation.json'].decode('utf-8'))
        transcript = files['transcript.txt'].decode('utf-8').removesuffix('\n')
        if (profile['profile_id'] != PROFILE_ID or profile['sample_file'] != 'sample.wav'
                or profile['transcript_file'] != 'transcript.txt'
                or profile['sample_sha256'] != metadata['sha256']
                or generation['audio_sha256'] != metadata['sha256']
                or generation['text_sha256'] != hashlib.sha256(transcript.encode('utf-8')).hexdigest()
                or generation['newbrain_contribution'] is not False
                or generation['reference_audio_used'] is not False):
            raise ValueError('Inconsistent voice pack metadata')
        result.update({'status': 'available_prerecorded_audition', 'audition_available': True,
                       'sample': metadata, 'transcript': transcript,
                       'provenance': 'User-supplied original synthetic speech-only audition; no runtime or weights included',
                       'source_generator_reported': generation['model'],
                       'preview': {'path': str(PACK_PATH / 'preview.html'),
                                   'manual_only': True, 'local_file_only': True}})
    except FileNotFoundError:
        result.update(status='unavailable_missing_asset', reason='The fixed voice pack or local preview is incomplete')
    except (OSError, ValueError, RuntimeError, wave.Error, EOFError, KeyError, TypeError):
        # Do not return a playable path for a pack that failed verification.
        result.update(status='unavailable_invalid_asset', reason='Voice pack failed bounded file, integrity, or metadata checks')
    return result
