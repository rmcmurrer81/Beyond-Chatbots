"""Original bounded DSP approximation, not biomechanical vocal-fold simulation.

A finite harmonic glottal-flow-inspired source and deterministic breath noise
excite three parallel resonators. No recordings, model weights or TTS providers.
"""
import hashlib
import io
import math
import os
from pathlib import Path
import platform
import re
import struct
import sys
import wave
from .protocol import PEAK, RATE, digest, is_hash, need, number, validate

ENGINE = 'aster.source-filter.v1'
PCM_LIMIT = int(32767 * PEAK)


def engine_binding():
    root = Path(__file__).parent
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in ('protocol.py', 'synth.py')}
    # platform.system()/machine() may perform a hostname/socket query on Windows.
    # Use built-in runtime facts only; never probe network or launch a command.
    system = {'win32': 'Windows', 'linux': 'Linux', 'darwin': 'Darwin'}.get(sys.platform, sys.platform)
    machine = os.uname().machine if hasattr(os, 'uname') else str(struct.calcsize('P') * 8) + 'bit'
    return {'engine': ENGINE, 'source_sha256': digest(hashes),
            'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'system': system, 'machine': machine}


def validate_checkpoint(plan, checkpoint):
    """Validate data without running synthesis or requiring the current platform."""
    plan = validate(plan)
    need(type(checkpoint) is dict and set(checkpoint) == {'state', 'sha256'}, 'checkpoint_envelope_refused')
    s = checkpoint['state']
    need(type(s) is dict and set(s) == {'schema', 'owner', 'intent_sha256', 'binding',
         'cursor', 'phase', 'noise', 'memories', 'dc'} and checkpoint['sha256'] == digest(s),
         'checkpoint_digest_mismatch')
    b = s['binding']
    need(type(b) is dict and set(b) == {'engine', 'source_sha256', 'python', 'implementation', 'system', 'machine'}
         and b['engine'] == ENGINE and is_hash(b['source_sha256'])
         and all(type(b[k]) is str and re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', b[k]) is not None
                 for k in ('python', 'implementation', 'system', 'machine')), 'checkpoint_engine_refused')
    need(s['schema'] == 'aster.voice-checkpoint.v1' and s['owner'] == plan['owner']
         and s['intent_sha256'] == digest(plan), 'checkpoint_binding_mismatch')
    frames = sum(g['duration_ms'] * (RATE // 1000) for g in plan['gestures'])
    need(type(s['cursor']) is int and 0 <= s['cursor'] <= frames
         and number(s['phase'], 0, 1) and s['phase'] < 1
         and type(s['noise']) is int and 1 <= s['noise'] <= 0xffffffff, 'checkpoint_scalar_refused')
    need(type(s['memories']) is list and len(s['memories']) == 3
         and all(type(p) is list and len(p) == 2 and all(number(v, -100, 100) for v in p)
                 for p in s['memories']), 'checkpoint_filter_refused')
    need(type(s['dc']) is list and len(s['dc']) == 2
         and number(s['dc'][0], -1, 1) and number(s['dc'][1], -2, 2), 'checkpoint_dc_refused')
    return s


class VoiceBox:
    """Finite renderer. Checkpoints resume exact frames on the same bound runtime."""
    def __init__(self, plan, owner=None):
        self._plan = validate(plan, owner)
        self.binding = engine_binding()
        self.frames = sum(g['duration_ms'] * (RATE // 1000) for g in self._plan['gestures'])
        self.cursor = 0
        self.phase = 0.0
        self.noise = self._plan['seed']
        self.memories = [[0.0, 0.0] for _ in range(3)]
        self.dc = [0.0, 0.0]
        self._schedule = []
        start = 0
        for g in self._plan['gestures']:
            size = g['duration_ms'] * (RATE // 1000)
            # Stable all-pole resonators; poles are strictly inside the unit circle.
            coeffs = []
            for f, b in zip(g['formants_hz'], g['bandwidths_hz']):
                r = math.exp(-math.pi * b / RATE)
                coeffs.append((2 * r * math.cos(2 * math.pi * f / RATE), -(r * r), 1 - r))
            # Smooth finite harmonic pulse. Open quotient alters the spectral envelope;
            # it is an abstract timbre control, not a measured opening-time estimate.
            harmonics = [(k, math.exp(-k * g['open_quotient'] * 0.32) / k)
                         for k in range(1, 25)]
            norm = sum(a for _, a in harmonics)
            self._schedule.append((start, size, g, coeffs, [(k, a / norm) for k, a in harmonics]))
            start += size

    @property
    def plan(self):
        return validate(self._plan)

    def checkpoint(self):
        state = {'schema': 'aster.voice-checkpoint.v1', 'owner': self._plan['owner'],
                 'intent_sha256': digest(self._plan), 'binding': dict(self.binding),
                 'cursor': self.cursor, 'phase': self.phase, 'noise': self.noise,
                 'memories': [list(pair) for pair in self.memories], 'dc': list(self.dc)}
        return {'state': state, 'sha256': digest(state)}

    @classmethod
    def restore(cls, plan, checkpoint, owner):
        box = cls(plan, owner)
        s = validate_checkpoint(box._plan, checkpoint)
        need(s['binding'] == box.binding, 'checkpoint_binding_mismatch')
        box.cursor, box.phase, box.noise = s['cursor'], float(s['phase']), s['noise']
        box.memories = [list(p) for p in s['memories']]
        box.dc = list(s['dc'])
        return box

    def render_frames(self, count):
        need(type(count) is int and 0 <= count <= RATE * 8, 'frame_request_refused')
        end = min(self.frames, self.cursor + count)
        output = bytearray()
        fade = RATE // 100  # 10 ms fades on each gesture, exact zero endpoints.
        for start, size, g, coeffs, harmonics in self._schedule:
            while start <= self.cursor < min(start + size, end):
                index = self.cursor - start
                if g['vowel'] == 'silence' or (g['voicing'] == 0 and g['breathiness'] == 0):
                    value = 0
                    self.memories = [[0.0, 0.0] for _ in range(3)]
                    self.dc = [0.0, 0.0]
                else:
                    f0 = g['pitch_hz'][0] + (g['pitch_hz'][1] - g['pitch_hz'][0]) * index / (size - 1)
                    self.phase = (self.phase + f0 / RATE) % 1.0
                    flow = sum(a * math.sin(2 * math.pi * k * self.phase) for k, a in harmonics)
                    # 24 * 350 Hz = 8400 Hz, below the fixed 12 kHz Nyquist limit.
                    x = self.noise
                    x ^= (x << 13) & 0xffffffff
                    x ^= x >> 17
                    x ^= (x << 5) & 0xffffffff
                    self.noise = x & 0xffffffff
                    noise = self.noise / 2147483648.0 - 1.0
                    excitation = g['voicing'] * flow + g['breathiness'] * noise
                    total = 0.0
                    for j, ((c1, c2, scale), weight) in enumerate(zip(coeffs, (1.0, 0.65, 0.4))):
                        y1, y2 = self.memories[j]
                        y = scale * excitation + c1 * y1 + c2 * y2
                        need(math.isfinite(y) and abs(y) <= 100, 'unstable_filter_refused')
                        self.memories[j] = [y, y1]
                        total += weight * y
                    envelope = min(1.0, index / fade, (size - 1 - index) / fade)
                    # Bounded soft saturation, then fixed -14 dBFS ceiling. No peak
                    # normalization that can amplify silence or tiny signals.
                    saturated = math.tanh(total * 2.0)
                    highpass = saturated - self.dc[0] + 0.995 * self.dc[1]
                    self.dc = [saturated, highpass]
                    # H(z)=(1-z^-1)/(1-.995z^-1) has L1 norm 2. Dividing
                    # by two bounds output without normalizing away silence.
                    need(math.isfinite(highpass) and abs(highpass) <= 2.0000001, 'dc_bound_refused')
                    bounded = max(-1.0, min(1.0, highpass / 2.0))
                    value = round(PCM_LIMIT * self._plan['gain'] * envelope * bounded)
                need(abs(value) <= PCM_LIMIT, 'pcm_ceiling_refused')
                output.extend(struct.pack('<h', value))
                self.cursor += 1
        return bytes(output)


def render(plan):
    box = VoiceBox(plan)
    return box.render_frames(box.frames)


def wav_bytes(pcm):
    need(type(pcm) is bytes and 0 < len(pcm) <= 2 * RATE * 8 and len(pcm) % 2 == 0, 'pcm_extent_refused')
    need(all(abs(v[0]) <= PCM_LIMIT for v in struct.iter_unpack('<h', pcm)), 'pcm_ceiling_refused')
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE); wav.writeframes(pcm)
    return stream.getvalue()


def measurements(pcm):
    need(type(pcm) is bytes and 0 < len(pcm) <= RATE * 8 * 2 and len(pcm) % 2 == 0, 'pcm_extent_refused')
    samples = [v[0] for v in struct.iter_unpack('<h', pcm)]
    peak = max(abs(v) for v in samples)
    return {'frames': len(samples), 'seconds': len(samples) / RATE, 'sample_rate': RATE,
            'channels': 1, 'sample_width_bytes': 2, 'peak_integer': peak,
            'peak_dbfs': 20 * math.log10(peak / 32768) if peak else None,
            'rms': math.sqrt(sum(v * v for v in samples) / len(samples)) / 32768,
            'mean': sum(samples) / len(samples) / 32768,
            'nonzero_samples': sum(v != 0 for v in samples),
            'full_scale_clipped_samples': sum(abs(v) >= 32767 for v in samples),
            'within_peak_ceiling': peak <= PCM_LIMIT, 'first_sample': samples[0], 'last_sample': samples[-1],
            'pcm_sha256': hashlib.sha256(pcm).hexdigest()}
