"""Independent stdlib-only tests for the opt-in original voice-box experiment.

The bridge fixtures mock an already-validated text-lab state. They verify adapter
behavior, not numerical learning or English speech. No test plays or records audio.
"""
import ast
import contextlib
import copy
import hashlib
import io
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch

from experiments.voice_box import bridge, demo, protocol, storage, synth
from experiments.newbrain_text.persistence import LabError

ROOT = Path(__file__).resolve().parents[1]
OWNER = 'synthetic_aster'


def short_plan(**kwargs):
    return protocol.make_plan([protocol.gesture('a', 40)], **kwargs)


def samples(pcm):
    return [value[0] for value in struct.iter_unpack('<h', pcm)]


class VoiceProtocolTests(unittest.TestCase):
    def test_default_demo_has_five_vowels_and_explicit_silences(self):
        plan = protocol.demo_plan()
        self.assertEqual([g['vowel'] for g in plan['gestures']],
                         ['a', 'silence', 'e', 'silence', 'i', 'silence', 'o', 'silence', 'u', 'silence'])
        self.assertEqual(plan['owner'], OWNER)
        self.assertEqual(plan['sample_rate'], 24000)
        self.assertEqual(plan['origin'], {'kind': 'manual_gestures'})

    def test_closed_intent_and_gesture_schemas(self):
        for value in (None, [], True, 'private-value', 42):
            with self.subTest(value=type(value).__name__), self.assertRaises(protocol.VoiceError):
                protocol.validate(value)
        for part in ('plan', 'gesture'):
            for mutation in ('extra', 'missing'):
                plan = short_plan()
                target = plan if part == 'plan' else plan['gestures'][0]
                if mutation == 'extra':
                    target['private_unknown'] = 'never accepted'
                else:
                    target.pop(next(iter(target)))
                with self.subTest(part=part, mutation=mutation), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)

    def test_owner_shape_and_owner_binding(self):
        for owner in ('aster', '', 'synthetic_', 'synthetic_Aster', 'synthetic_a/b',
                      'synthetic_../a', 'synthetic_a\n', 'synthetic_' + 'a' * 49, None, True):
            with self.subTest(owner=repr(owner)), self.assertRaisesRegex(protocol.VoiceError, 'synthetic_owner_required'):
                short_plan(owner=owner)
        self.assertEqual(short_plan(owner='synthetic_a')['owner'], 'synthetic_a')
        with self.assertRaisesRegex(protocol.VoiceError, 'voice_owner_mismatch'):
            protocol.validate(short_plan(), 'synthetic_other')

    def test_protocol_identity_and_integer_limits(self):
        for field, values in {
            'schema': ['other', None], 'profile': ['borrowed_voice', None],
            'sample_rate': [True, 24000.0, 48000, 0],
            'seed': [True, 1.0, 0, -1, 2**32],
        }.items():
            for value in values:
                plan = short_plan(); plan[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)
        for seed in (1, 0xffffffff):
            plan = short_plan(); plan['seed'] = seed
            self.assertEqual(protocol.validate(plan)['seed'], seed)

    def test_hostile_numeric_controls_are_rejected(self):
        bad = [None, True, '1', math.nan, math.inf, -math.inf, 10**1000]
        for field in ('gain', 'voicing', 'breathiness', 'open_quotient', 'pitch_hz', 'formants_hz', 'bandwidths_hz'):
            for value in bad:
                plan = short_plan()
                target = plan if field == 'gain' else plan['gestures'][0]
                if field in ('pitch_hz', 'formants_hz', 'bandwidths_hz'):
                    target[field][0] = value
                else:
                    target[field] = value
                with self.subTest(field=field, value=type(value).__name__), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)

    def test_numeric_control_bounds_and_vector_lengths(self):
        for field, bad_values in {
            'gain': [-0.001, 1.001], 'voicing': [-0.001, 1.001],
            'breathiness': [-0.001, 0.401], 'open_quotient': [0.349, 0.801],
            'pitch_hz': [[79, 200], [200, 351], [], [200], [200, 200, 200], (200, 200)],
            'formants_hz': [[199, 900, 2800], [350, 900, 4501], [800, 899, 2800],
                            [350, 2900, 2800], [350, 900], None],
            'bandwidths_hz': [[59, 90, 120], [90, 120, 501], [90, 120], None],
        }.items():
            for value in bad_values:
                plan = short_plan(); (plan if field == 'gain' else plan['gestures'][0])[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)

    def test_duration_and_gesture_count_are_finite(self):
        for value in (0, 39, 2001, True, 40.0, '40'):
            with self.subTest(duration=value), self.assertRaises(protocol.VoiceError):
                protocol.make_plan([protocol.gesture('a', value)])
        for gestures in ([], [protocol.gesture('a', 40)] * 33,
                         [protocol.gesture('a', 2000)] * 5, (protocol.gesture('a'),)):
            with self.subTest(count=len(gestures)), self.assertRaises(protocol.VoiceError):
                protocol.make_plan(gestures)
        self.assertEqual(len(protocol.make_plan([protocol.gesture('a', 40)] * 32)['gestures']), 32)
        self.assertEqual(synth.VoiceBox(protocol.make_plan([protocol.gesture('a', 2000)] * 4)).frames,
                         protocol.RATE * 8)

    def test_origin_is_closed_and_manual_origin_has_no_provenance_fields(self):
        for value in (None, [], {}, {'kind': 'provider'},
                      {'kind': 'manual_gestures', 'private': 'untrusted'}, {'kind': 'text_lab_observation'}):
            plan = short_plan(); plan['origin'] = value
            with self.subTest(origin=value), self.assertRaises(protocol.VoiceError):
                protocol.validate(plan)

    def test_json_rejects_duplicates_nonfinite_depth_size_and_wrong_encoding(self):
        for raw in (b'', b'\xff', b'{', b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":2}}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'[' * 2000 + b']' * 2000,
                    b'[' + b'0,' * 9000 + b'0]',
                    b' ' * 32769, '{}', bytearray(b'{}')):
            with self.subTest(kind=type(raw).__name__, size=len(raw)), self.assertRaises(protocol.VoiceError):
                protocol.parse_json(raw)
        self.assertEqual(protocol.parse_json(b'{"valid":1}'), {'valid': 1})

    def test_canonical_json_refuses_cycles_nonfinite_and_custom_objects(self):
        cyclic = []; cyclic.append(cyclic)
        for value in (cyclic, object(), {'value': math.nan}, {'value': math.inf}):
            with self.subTest(kind=type(value).__name__), self.assertRaises(protocol.VoiceError):
                protocol.canonical(value)
        self.assertEqual(protocol.canonical({'b': 2, 'a': 1}), b'{"a":1,"b":2}\n')

    def test_validation_and_engine_plan_are_detached(self):
        plan = short_plan(); validated = protocol.validate(plan); box = synth.VoiceBox(plan)
        plan['gestures'][0]['pitch_hz'][0] = 80
        validated['gestures'][0]['pitch_hz'][0] = 100
        returned = box.plan; returned['gestures'][0]['pitch_hz'][0] = 350
        self.assertEqual(box.plan['gestures'][0]['pitch_hz'][0], 220)
        self.assertEqual(box.render_frames(box.frames), synth.render(short_plan()))


class VoiceSynthesisTests(unittest.TestCase):
    def test_all_vowels_are_nonzero_distinct_and_bounded_with_zero_endpoints(self):
        outputs = []
        for vowel in protocol.VOWELS:
            pcm = synth.render(protocol.make_plan([protocol.gesture(vowel, 80)]))
            measured = synth.measurements(pcm)
            self.assertEqual(len(pcm), 80 * 24 * 2)
            self.assertTrue(measured['within_peak_ceiling'])
            self.assertGreater(measured['nonzero_samples'], 0)
            self.assertEqual((measured['first_sample'], measured['last_sample']), (0, 0))
            self.assertEqual(measured['full_scale_clipped_samples'], 0)
            self.assertTrue(all(math.isfinite(measured[key]) for key in ('rms', 'mean', 'peak_dbfs')))
            outputs.append(pcm)
        self.assertEqual(len(set(outputs)), 5)

    def test_extreme_accepted_controls_remain_safe(self):
        for pitch in (80, 350):
            for formants in ([200, 300, 400], [4300, 4400, 4500]):
                for bandwidth in (60, 500):
                    g = protocol.gesture('a', 120, (pitch, pitch), breathiness=0.4,
                                         open_quotient=0.35, formants=formants)
                    g['bandwidths_hz'] = [bandwidth] * 3
                    pcm = synth.render(protocol.make_plan([g], gain=1))
                    with self.subTest(pitch=pitch, bandwidth=bandwidth, formants=formants):
                        self.assertLessEqual(max(map(abs, samples(pcm))), synth.PCM_LIMIT)

    def test_explicit_silence_resets_filter_and_is_exact_zero(self):
        plan = protocol.make_plan([protocol.gesture('a', 40), protocol.gesture('silence', 40),
                                   protocol.gesture('u', 40)])
        box = synth.VoiceBox(plan)
        self.assertTrue(any(box.render_frames(960)))
        self.assertEqual(box.render_frames(960), bytes(1920))
        self.assertEqual(box.memories, [[0, 0]] * 3)
        self.assertEqual(box.dc, [0, 0])
        self.assertTrue(any(box.render_frames(960)))

    def test_gain_zero_and_unexcited_source_are_exact_silence(self):
        plans = (short_plan(gain=0), protocol.make_plan([protocol.gesture('a', 80, voicing=0, breathiness=0)]),
                 protocol.make_plan([protocol.gesture('silence', 80)]))
        for plan in plans:
            pcm = synth.render(plan)
            self.assertEqual(pcm, bytes(len(pcm)))
            result = synth.measurements(pcm)
            self.assertIsNone(result['peak_dbfs'])
            self.assertEqual(result['nonzero_samples'], 0)
            self.assertEqual(result['rms'], 0)

    def test_muted_source_after_voice_is_exact_zero_without_resonator_ring(self):
        plan = protocol.make_plan([protocol.gesture('a', 40),
                                   protocol.gesture('a', 40, voicing=0, breathiness=0),
                                   protocol.gesture('u', 40)])
        box = synth.VoiceBox(plan)
        self.assertTrue(any(box.render_frames(960)))
        self.assertEqual(box.render_frames(960), bytes(1920))
        self.assertEqual(box.memories, [[0, 0]] * 3)
        self.assertEqual(box.dc, [0, 0])
        self.assertTrue(any(box.render_frames(960)))

    def test_constant_pitch_has_expected_fundamental_period(self):
        for f0 in (180, 220, 300):
            gesture = protocol.gesture('a', 300, pitch=(f0, f0), breathiness=0)
            pcm = samples(synth.render(protocol.make_plan([gesture])))[2400:4800]
            lags = range(int(protocol.RATE / (f0 * 1.3)), int(protocol.RATE / (f0 * 0.8)))
            extent = len(pcm) - max(lags)
            best = max(lags, key=lambda lag: sum(pcm[i] * pcm[i + lag] for i in range(extent)))
            self.assertAlmostEqual(protocol.RATE / best, f0, delta=2)

    def test_maximum_duration_renders_exact_extent_without_clipping(self):
        plan = protocol.make_plan([protocol.gesture(v, 2000, pitch=(350, 80), breathiness=0.4)
                                   for v in ('a', 'e', 'i', 'u')], gain=1)
        pcm = synth.render(plan)
        self.assertEqual(len(pcm), protocol.RATE * 8 * 2)
        self.assertTrue(synth.measurements(pcm)['within_peak_ceiling'])

    def test_gain_does_not_peak_normalize_and_is_monotonic(self):
        high = samples(synth.render(short_plan(gain=1)))
        low = samples(synth.render(short_plan(gain=0.25)))
        self.assertLess(max(map(abs, low)), max(map(abs, high)))
        self.assertTrue(all(abs(a - 4 * b) <= 3 for a, b in zip(high, low)))

    def test_voice_pitch_breath_open_quotient_and_formants_affect_output(self):
        base = synth.render(short_plan())
        variations = [protocol.gesture('a', 40, pitch=(300, 300)),
                      protocol.gesture('a', 40, voicing=0.5),
                      protocol.gesture('a', 40, breathiness=0.4),
                      protocol.gesture('a', 40, open_quotient=0.8),
                      protocol.gesture('a', 40, formants=[600, 1800, 3200])]
        for index, gesture in enumerate(variations):
            with self.subTest(control=index):
                self.assertNotEqual(synth.render(protocol.make_plan([gesture])), base)

    def test_seed_controls_noise_and_never_uses_global_random(self):
        import random
        plan = short_plan(); other = copy.deepcopy(plan); other['seed'] += 1
        with patch.object(random, 'random', side_effect=AssertionError('global random used')):
            self.assertEqual(synth.render(plan), synth.render(plan))
            self.assertNotEqual(synth.render(plan), synth.render(other))
        plan['gestures'][0]['breathiness'] = 0; other['gestures'][0]['breathiness'] = 0
        self.assertEqual(synth.render(plan), synth.render(other))

    def test_chunking_matches_single_pass_across_gesture_boundaries(self):
        plan = protocol.make_plan([protocol.gesture('a', 40), protocol.gesture('silence', 40),
                                   protocol.gesture('u', 40)])
        for sizes in ((1,), (17, 31, 941), (960, 0, 1), (1001, 40)):
            box = synth.VoiceBox(plan); chunks = []; index = 0
            while box.cursor < box.frames:
                chunks.append(box.render_frames(sizes[index % len(sizes)])); index += 1
            self.assertEqual(b''.join(chunks), synth.render(plan))
            self.assertEqual(box.render_frames(10), b'')
            self.assertEqual(box.cursor, box.frames)

    def test_frame_count_limits_and_zero_request(self):
        box = synth.VoiceBox(short_plan()); before = box.checkpoint()
        self.assertEqual(box.render_frames(0), b'')
        self.assertEqual(box.checkpoint(), before)
        for count in (-1, True, 1.5, '1', protocol.RATE * 8 + 1):
            with self.subTest(count=count), self.assertRaises(protocol.VoiceError):
                box.render_frames(count)
        self.assertEqual(len(box.render_frames(protocol.RATE * 8)), box.frames * 2)

    def test_checkpoint_restores_exactly_at_start_midpoint_silence_and_end(self):
        plan = protocol.make_plan([protocol.gesture('a', 40), protocol.gesture('silence', 40),
                                   protocol.gesture('u', 40)])
        expected = synth.render(plan)
        for offset in (0, 1, 479, 960, 1000, 1920, 2879, 2880):
            box = synth.VoiceBox(plan); first = box.render_frames(offset)
            saved = box.checkpoint(); restored = synth.VoiceBox.restore(plan, saved, OWNER)
            self.assertEqual(first + restored.render_frames(restored.frames), expected)
            self.assertEqual(saved, box.checkpoint())

    def test_checkpoint_corruption_wrong_owner_intent_or_runtime_refused(self):
        plan = short_plan(); box = synth.VoiceBox(plan); box.render_frames(17)
        original = box.checkpoint()
        corrupt = copy.deepcopy(original); corrupt['state']['cursor'] += 1
        with self.assertRaisesRegex(protocol.VoiceError, 'checkpoint_digest_mismatch'):
            synth.VoiceBox.restore(plan, corrupt, OWNER)
        with self.assertRaises(protocol.VoiceError):
            synth.VoiceBox.restore(plan, original, 'synthetic_other')
        changed = copy.deepcopy(plan); changed['gain'] = 0.3
        with self.assertRaises(protocol.VoiceError):
            synth.VoiceBox.restore(changed, original, OWNER)
        changed = copy.deepcopy(original); changed['state']['binding']['python'] = '0.0.0'
        changed['sha256'] = protocol.digest(changed['state'])
        with self.assertRaisesRegex(protocol.VoiceError, 'checkpoint_binding_mismatch'):
            synth.VoiceBox.restore(plan, changed, OWNER)

    def test_rehashed_checkpoint_scalar_and_filter_damage_refused(self):
        plan = short_plan(); original = synth.VoiceBox(plan).checkpoint()
        for field, values in {
            'cursor': [-1, True, 961, 0.0], 'phase': [-0.1, 1, True],
            'noise': [0, True, 2**32], 'memories': [[], [[101, 0]] * 3, [[True, 0]] * 3],
            'dc': [[], [1.1, 0], [0, 2.1], [False, 0]],
        }.items():
            for value in values:
                checkpoint = copy.deepcopy(original); checkpoint['state'][field] = value
                checkpoint['sha256'] = protocol.digest(checkpoint['state'])
                with self.subTest(field=field, value=value), self.assertRaises(protocol.VoiceError):
                    synth.VoiceBox.restore(plan, checkpoint, OWNER)

    def test_wav_header_and_measurements_match_pcm(self):
        pcm = synth.render(short_plan()); raw = synth.wav_bytes(pcm)
        with wave.open(io.BytesIO(raw), 'rb') as reader:
            self.assertEqual((reader.getnchannels(), reader.getsampwidth(), reader.getframerate()), (1, 2, 24000))
            self.assertEqual(reader.getnframes(), 960)
            self.assertEqual(reader.readframes(960), pcm)
        result = synth.measurements(pcm)
        self.assertEqual(result['pcm_sha256'], hashlib.sha256(pcm).hexdigest())
        self.assertEqual(result['frames'], 960)
        self.assertEqual(result['seconds'], 0.04)

    def test_wav_refuses_unsafe_or_malformed_pcm(self):
        for pcm in (b'', b'\0', bytearray(b'\0\0'), b'\0\0' * (protocol.RATE * 8 + 1),
                    struct.pack('<h', 32767), struct.pack('<h', -32768),
                    struct.pack('<h', synth.PCM_LIMIT + 1)):
            with self.subTest(size=len(pcm)), self.assertRaises(protocol.VoiceError):
                synth.wav_bytes(pcm)
        for pcm in (b'', b'\0', None):
            with self.assertRaises(protocol.VoiceError):
                synth.measurements(pcm)


class VoiceBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name); self.bundle = self.parent / 'bundle'
        self.plan = short_plan()

    def create(self):
        return storage.render_bundle(self.bundle, self.plan)

    def snapshot(self):
        return {path.name: path.read_bytes() for path in self.bundle.iterdir()}

    def rewrite(self, name, value):
        """Rehash corruption to exercise semantic checks rather than digest checks."""
        raw = value if isinstance(value, bytes) else protocol.canonical(value)
        (self.bundle / name).write_bytes(raw)
        manifest = json.loads((self.bundle / 'manifest.json').read_bytes())
        manifest['files'][name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        (self.bundle / 'manifest.json').write_bytes(protocol.canonical(manifest))

    def test_complete_bundle_roundtrip_inspection_and_recheck_are_read_only(self):
        receipt = self.create(); before = self.snapshot()
        self.assertEqual(set(before), {*storage.CAPS, 'manifest.json'})
        inspected = storage.inspect_bundle(self.bundle)
        rechecked = storage.recheck_bundle(self.bundle)
        self.assertTrue(inspected['same_engine_runtime'])
        self.assertTrue(inspected['inspected_without_synthesis'])
        self.assertTrue(rechecked['render_exact'])
        self.assertEqual(self.snapshot(), before)
        for field in ('automatic_playback', 'production_brain_enabled', 'intelligible_speech_verified',
                      'perceptual_voice_gender_verified'):
            self.assertIs(receipt[field], False)
        if os.name != 'nt':
            self.assertEqual(self.bundle.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all((self.bundle / name).stat().st_mode & 0o777 == 0o600 for name in before))

    def test_engine_identity_never_uses_host_discovering_platform_helpers(self):
        # On Windows platform.uname() can discover the hostname through socket.
        # Engine identity must work without that behavior; retain both existing
        # isolated-process audit guards against every socket.* event unchanged.
        refused = AssertionError('host-discovering platform helper used')
        with patch.object(synth.platform, 'system', side_effect=refused), \
             patch.object(synth.platform, 'machine', side_effect=refused), \
             patch.object(synth.platform, 'uname', side_effect=refused):
            box = synth.VoiceBox(self.plan)
            self.assertEqual(len(box.render_frames(box.frames)), box.frames * 2)
            self.create()
            self.assertTrue(storage.inspect_bundle(self.bundle)['same_engine_runtime'])
            self.assertTrue(storage.recheck_bundle(self.bundle)['render_exact'])

    def test_windows_identity_fallback_uses_only_runtime_pointer_width(self):
        # Branch fixture, not a claim that this process ran on Windows.
        refused = AssertionError('host-discovering platform helper used')
        with patch.object(synth.platform, 'system', side_effect=refused), \
             patch.object(synth.platform, 'machine', side_effect=refused), \
             patch.object(synth.platform, 'uname', side_effect=refused), \
             patch.object(synth, 'os', SimpleNamespace()), \
             patch.object(synth.sys, 'platform', 'win32'):
            binding = synth.engine_binding()
        self.assertEqual(binding['system'], 'Windows')
        self.assertEqual(binding['machine'], str(struct.calcsize('P') * 8) + 'bit')

    def test_existing_directory_and_file_are_never_clobbered(self):
        self.create(); before = self.snapshot()
        with self.assertRaises(protocol.VoiceError): self.create()
        self.assertEqual(self.snapshot(), before)
        file = self.parent / 'occupied'; file.write_bytes(b'preserve')
        empty = self.parent / 'empty'; empty.mkdir()
        for target in (file, empty, self.parent / 'missing' / 'output'):
            with self.subTest(target=target.name), self.assertRaises(protocol.VoiceError):
                storage.render_bundle(target, self.plan)
        self.assertEqual(file.read_bytes(), b'preserve'); self.assertEqual(list(empty.iterdir()), [])

    def test_raced_destination_is_preserved_and_staging_is_cleaned(self):
        original = storage._rename_exclusive
        def race(stage, target):
            target.mkdir(); (target / 'winner').write_bytes(b'keep')
            return original(stage, target)
        with patch.object(storage, '_rename_exclusive', side_effect=race):
            with self.assertRaisesRegex(protocol.VoiceError, 'voice_publication_failed'): self.create()
        self.assertEqual((self.bundle / 'winner').read_bytes(), b'keep')
        self.assertEqual({p.name for p in self.parent.iterdir()}, {'bundle'})

    def test_failed_write_leaves_no_partial_publication_or_staging(self):
        with patch.object(storage.os, 'fsync', side_effect=OSError('private-write-diagnostic')):
            with self.assertRaisesRegex(protocol.VoiceError, '^voice_publication_failed$'): self.create()
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_postcommit_durability_failure_reports_existing_bundle(self):
        original = storage._sync_directory
        def fail_parent(path):
            if Path(path) == self.parent: raise OSError('private-sync-diagnostic')
            return original(path)
        with patch.object(storage, '_sync_directory', side_effect=fail_parent):
            with self.assertRaisesRegex(protocol.VoiceError, '^voice_published_durability_unconfirmed$'): self.create()
        self.assertTrue(self.bundle.is_dir())
        self.assertTrue(storage.recheck_bundle(self.bundle)['render_exact'])

    def test_wrong_owner_and_extra_or_missing_files_refused(self):
        self.create()
        with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle, 'synthetic_other')
        extra = self.bundle / 'unexpected'; extra.write_text('private')
        with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle)
        extra.unlink(); (self.bundle / 'checkpoint.json').unlink()
        with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle)

    def test_byte_corruption_is_refused_for_every_bundle_file(self):
        self.create(); before = self.snapshot()
        for name, raw in before.items():
            (self.bundle / name).write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.subTest(file=name), self.assertRaises(protocol.VoiceError):
                storage.inspect_bundle(self.bundle)
            (self.bundle / name).write_bytes(raw)

    def test_rehashed_wav_header_extent_and_ceiling_damage_refused(self):
        self.create(); before = self.snapshot(); wav = before['preview.wav']
        bad_header = bytearray(wav); bad_header[24:28] = struct.pack('<I', 48000)
        unsafe = bytearray(wav); unsafe[44:46] = struct.pack('<h', 32767)
        for raw in (b'not-wave', wav[:-2], wav + b'junk', bytes(bad_header), bytes(unsafe)):
            with self.subTest(size=len(raw)):
                self.rewrite('preview.wav', raw)
                with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle)
                for name, original in before.items(): (self.bundle / name).write_bytes(original)

    def test_receipt_claims_and_measurements_cannot_be_rehashed_into_validity(self):
        self.create(); before = self.snapshot()
        for field, value in (('automatic_playback', True), ('production_brain_enabled', True),
                             ('intelligible_speech_verified', True), ('perceptual_voice_gender_verified', True),
                             ('checkpoint_resume_exact', False), ('checkpoint_frame', 0),
                             ('owner', 'synthetic_other'), ('measurement', {})):
            receipt = json.loads(before['receipt.json']); receipt[field] = value
            self.rewrite('receipt.json', receipt)
            with self.subTest(field=field), self.assertRaises(protocol.VoiceError):
                storage.inspect_bundle(self.bundle)
            for name, raw in before.items(): (self.bundle / name).write_bytes(raw)

    def test_inspection_rejects_rehashed_malformed_checkpoint_without_synthesizing(self):
        self.create(); before = self.snapshot()
        for field, value in (('schema', 'hostile'), ('phase', 99), ('noise', 0),
                             ('memories', []), ('dc', [0, 99]), ('unexpected', 'private')):
            checkpoint = json.loads(before['checkpoint.json']); checkpoint['state'][field] = value
            checkpoint['sha256'] = protocol.digest(checkpoint['state']); self.rewrite('checkpoint.json', checkpoint)
            with self.subTest(field=field), patch.object(synth.VoiceBox, 'render_frames', side_effect=AssertionError('synthesis ran')):
                with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle)
            for name, raw in before.items(): (self.bundle / name).write_bytes(raw)

    def test_inspection_reports_old_runtime_but_recheck_requires_exact_binding(self):
        self.create()
        checkpoint = json.loads((self.bundle / 'checkpoint.json').read_bytes())
        receipt = json.loads((self.bundle / 'receipt.json').read_bytes())
        checkpoint['state']['binding']['python'] = '0.0.0'
        checkpoint['sha256'] = protocol.digest(checkpoint['state'])
        receipt['binding'] = checkpoint['state']['binding']
        self.rewrite('checkpoint.json', checkpoint); self.rewrite('receipt.json', receipt)
        result = storage.inspect_bundle(self.bundle)
        self.assertIs(result['same_engine_runtime'], False)
        self.assertIs(result['checkpoint_resume_checked_now'], False)
        with self.assertRaisesRegex(protocol.VoiceError, 'checkpoint_binding_mismatch'):
            storage.recheck_bundle(self.bundle)

    def test_measurement_bool_integer_substitution_is_refused(self):
        self.create()
        receipt = json.loads((self.bundle / 'receipt.json').read_bytes())
        receipt['measurement']['channels'] = True
        self.rewrite('receipt.json', receipt)
        with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle)

    def test_inspection_does_not_restore_or_execute_numerical_models(self):
        self.create()
        with patch.object(synth.VoiceBox, 'restore', side_effect=AssertionError('restore ran')), \
             patch.object(synth.VoiceBox, 'render_frames', side_effect=AssertionError('synthesis ran')), \
             patch('experiments.newbrain_text.source.load_modules', side_effect=AssertionError('numerical import')):
            self.assertTrue(storage.inspect_bundle(self.bundle)['inspected_without_synthesis'])

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unsupported')
    def test_symlinked_output_parent_bundle_or_member_refused(self):
        self.create()
        parent_link = self.parent / 'parent-link'; parent_link.symlink_to(self.parent, target_is_directory=True)
        with self.assertRaises(protocol.VoiceError):
            storage.render_bundle(parent_link / 'other', self.plan)
        bundle_link = self.parent / 'bundle-link'; bundle_link.symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(bundle_link)
        member = self.bundle / 'intent.json'; saved = self.parent / 'saved.json'; member.rename(saved); member.symlink_to(saved)
        with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle)

    @unittest.skipUnless(hasattr(os, 'link'), 'hardlinks unsupported')
    def test_hardlinked_file_refused(self):
        self.create(); os.link(self.bundle / 'intent.json', self.parent / 'extra-link')
        with self.assertRaises(protocol.VoiceError): storage.inspect_bundle(self.bundle)

    def test_oversize_reads_and_available_posix_fifo_are_refused(self):
        # Windows has no os.mkfifo; FIFO coverage applies only on supporting hosts.
        if hasattr(os, 'mkfifo'):
            fifo = self.parent / 'fifo'; os.mkfifo(fifo)
            with self.assertRaises(protocol.VoiceError): storage.read_plain(fifo, 16)
        large = self.parent / 'large'; large.write_bytes(b'x' * 17)
        with self.assertRaises(protocol.VoiceError): storage.read_plain(large, 16)

    def test_fresh_process_restores_without_optional_dependencies_or_hardware(self):
        self.create(); before = self.snapshot()
        script = """
import importlib.abc, json, sys
sys.path.insert(0, sys.argv[1])
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy','torch','sounddevice','pyaudio','pyttsx3','speech_recognition','aster'}:
            raise AssertionError('forbidden dependency')
sys.meta_path.insert(0, Guard())
def audit(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen','os.system','os.startfile'):
        raise AssertionError('external side effect')
sys.addaudithook(audit)
from experiments.voice_box.storage import recheck_bundle
print(json.dumps(recheck_bundle(sys.argv[2])))
"""
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script, str(ROOT), str(self.bundle)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b'')
        self.assertTrue(json.loads(result.stdout)['render_exact'])
        self.assertEqual(self.snapshot(), before)


class VoiceBridgeTests(unittest.TestCase):
    def fixture(self, token='cool', target='warm', correct=False):
        observation = {'generation': {'tokens': [token], 'terminated_with_eos': True},
                       'target': [target], 'exact_correct': correct}
        result = {'evaluation': {split: [copy.deepcopy(observation)] * 6 for split in ('old', 'new', 'heldout')}}
        methods = ('initial', 'baseline', 'INTERLEAVED', 'BLOCKED', 'ERROR_PRIORITIZED')
        envelope = {'report_sha256': 'a' * 64,
                    'models': {name: {'model_sha256': 'b' * 64} for name in methods}}
        report = {'initial': result, 'baseline': result,
                  'arms': {name: result for name in methods[2:]}}
        return envelope, report

    def test_adapter_uses_actual_incorrect_output_never_target(self):
        for token, target, vowel in (('cool', 'warm', 'u'), ('warm', 'cool', 'a')):
            with patch('experiments.newbrain_text.persistence.read_state', return_value=self.fixture(token, target)) as read:
                plan = bridge.from_text_lab('synthetic-test-state')
            read.assert_called_once_with('synthetic-test-state', OWNER)
            self.assertEqual(plan['gestures'][0]['vowel'], vowel)
            self.assertEqual(plan['origin']['observed_token'], token)
            self.assertIs(plan['origin']['exact_correct'], False)
            self.assertEqual(plan['origin']['report_sha256'], 'a' * 64)
            self.assertEqual(plan['origin']['model_sha256'], 'b' * 64)
            self.assertEqual(plan['origin']['adapter'], 'aster.text-label-to-vowel.v1')

    def test_all_supported_methods_splits_and_selected_indices(self):
        for method in ('initial', 'baseline', 'INTERLEAVED', 'BLOCKED', 'ERROR_PRIORITIZED'):
            for split in ('old', 'new', 'heldout'):
                with patch('experiments.newbrain_text.persistence.read_state', return_value=self.fixture('warm', 'warm', True)):
                    plan = bridge.from_text_lab('synthetic-test-state', method=method, split=split, case_index=5)
                self.assertEqual((plan['origin']['method'], plan['origin']['split'], plan['origin']['case_index']),
                                 (method, split, 5))
                self.assertIs(plan['origin']['exact_correct'], True)

    def test_invalid_selection_refused_before_reading_state(self):
        for kwargs in ({'method': 'invented'}, {'split': 'private'}, {'case_index': True},
                       {'case_index': -1}, {'case_index': 6}, {'owner': 'real_person'}):
            with patch('experiments.newbrain_text.persistence.read_state') as read:
                with self.subTest(kwargs=kwargs), self.assertRaises(protocol.VoiceError):
                    bridge.from_text_lab('synthetic-test-state', **kwargs)
                read.assert_not_called()

    def test_unvalidated_or_corrupt_state_is_refused_without_raw_details(self):
        with patch('experiments.newbrain_text.persistence.read_state', side_effect=LabError('PRIVATE PATH OR INPUT')):
            with self.assertRaisesRegex(protocol.VoiceError, '^text_lab_state_refused$'):
                bridge.from_text_lab('synthetic-test-state')

    def test_empty_multiple_unknown_or_unterminated_observed_tokens_refused(self):
        for tokens, eos in (([], True), (['warm', 'cool'], True), (['unknown'], True), (['warm'], False)):
            envelope, report = self.fixture()
            report['arms']['INTERLEAVED']['evaluation']['new'][0]['generation'] = {
                'tokens': tokens, 'terminated_with_eos': eos}
            with patch('experiments.newbrain_text.persistence.read_state', return_value=(envelope, report)):
                with self.subTest(tokens=tokens, eos=eos), self.assertRaisesRegex(protocol.VoiceError, 'unsupported_observed_output'):
                    bridge.from_text_lab('synthetic-test-state')

    def test_lab_origin_is_closed_typed_and_bounded(self):
        with patch('experiments.newbrain_text.persistence.read_state', return_value=self.fixture()):
            original = bridge.from_text_lab('synthetic-test-state')
        for field, value in (('case_index', True), ('case_index', 6), ('method', 'other'), ('split', 'other'),
                             ('observed_token', 'hello'), ('exact_correct', 1), ('report_sha256', 'x'),
                             ('model_sha256', 'A' * 64), ('adapter', 'invented'), ('extra', 'private')):
            plan = copy.deepcopy(original); plan['origin'][field] = value
            with self.subTest(field=field), self.assertRaises(protocol.VoiceError): protocol.validate(plan)


class VoiceCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name); self.bundle = self.parent / 'voice'

    def command(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = demo.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_render_inspect_and_recheck_cli_roundtrip(self):
        intent = self.parent / 'intent.json'; intent.write_bytes(protocol.canonical(short_plan()))
        for args in (['render', '--intent', str(intent), '--output', str(self.bundle)],
                     ['inspect', '--bundle', str(self.bundle)], ['recheck', '--bundle', str(self.bundle)]):
            code, out, err = self.command(args)
            self.assertEqual(code, 0); self.assertEqual(err, '')
            result = json.loads(out)
            self.assertIs(result['automatic_playback'], False)
            self.assertIs(result['production_brain_enabled'], False)

    def test_cli_failures_never_echo_private_paths_or_input(self):
        private = self.parent / 'PRIVATE_CANARY'
        cases = (['inspect', '--bundle', str(private)], ['render', '--intent', str(private), '--output', str(self.bundle)],
                 ['demo', '--owner', 'PRIVATE_CANARY', '--output', str(self.bundle)],
                 ['from-text-lab', '--text-state', str(private), '--output', str(self.bundle)])
        for args in cases:
            code, out, err = self.command(args)
            self.assertEqual(code, 2); self.assertEqual(out, '')
            self.assertNotIn('PRIVATE_CANARY', err); self.assertNotIn(str(self.parent), err)
            self.assertNotIn('Traceback', err); self.assertTrue(err.startswith('error: '))
        self.assertFalse(self.bundle.exists())

    def test_argument_errors_redact_unknown_flags_and_values(self):
        for args in (['PRIVATE_CANARY'], ['inspect', '--bundle', 'x', '--PRIVATE_CANARY'],
                     ['from-text-lab', '--text-state', 'x', '--output', 'x', '--case-index', 'PRIVATE_CANARY']):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as raised: demo.main(args)
            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(out.getvalue(), ''); self.assertEqual(err.getvalue(), 'error: invalid_arguments\n')

    def test_manual_render_cannot_forge_lab_origin(self):
        fixture = VoiceBridgeTests().fixture()
        with patch('experiments.newbrain_text.persistence.read_state', return_value=fixture):
            plan = bridge.from_text_lab('synthetic-test-state')
        intent = self.parent / 'intent.json'; intent.write_bytes(protocol.canonical(plan))
        code, out, err = self.command(['render', '--intent', str(intent), '--output', str(self.bundle)])
        self.assertEqual(code, 2); self.assertEqual(out, '')
        self.assertEqual(err, 'error: use_verified_lab_adapter\n'); self.assertFalse(self.bundle.exists())

    def test_unexpected_error_and_cancellation_are_fixed_codes(self):
        for error, expected, code in ((RuntimeError('PRIVATE_CANARY'), 'voice_box_failed', 2),
                                      (KeyboardInterrupt(), 'operation_cancelled', 130)):
            with patch.object(demo, 'inspect_bundle', side_effect=error):
                status, out, err = self.command(['inspect', '--bundle', str(self.bundle)])
            self.assertEqual(status, code); self.assertEqual(out, '')
            self.assertEqual(err, 'error: ' + expected + '\n')

    def test_cli_has_no_playback_recording_network_or_production_imports(self):
        script = """
import importlib.abc, sys
sys.path.insert(0, sys.argv[1])
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'aster','numpy','torch','sounddevice','pyaudio','pyttsx3','winsound','speech_recognition'}:
            raise AssertionError('forbidden dependency')
sys.meta_path.insert(0, Guard())
def audit(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen','os.system','os.startfile'):
        raise AssertionError('external side effect')
sys.addaudithook(audit)
from experiments.voice_box.demo import main
raise SystemExit(main(['demo','--output',sys.argv[2]]))
"""
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', script, str(ROOT), str(self.bundle)],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode()); self.assertEqual(result.stderr, b'')
        receipt = json.loads(result.stdout)
        self.assertIs(receipt['automatic_playback'], False)
        self.assertIs(receipt['production_brain_enabled'], False)
        self.assertEqual(receipt['measurement']['frames'], 66000)

    def test_production_modules_never_import_optional_voice_box(self):
        for path in (ROOT / 'aster').rglob('*.py'):
            tree = ast.parse(path.read_bytes())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = ([node.module or ''] if isinstance(node, ast.ImportFrom)
                             else [alias.name for alias in node.names])
                    self.assertFalse(any('voice_box' in name for name in names), path.name)


class VoiceRecorderTests(unittest.TestCase):
    def test_zero_missing_or_skipped_tests_do_not_create_successful_receipt(self):
        scripts = str(ROOT / 'scripts')
        with patch.object(sys, 'path', [scripts, *sys.path]):
            spec = importlib.util.spec_from_file_location('voice_recorder_test_fixture',
                                                         ROOT / 'scripts' / 'record_voice_box_checks.py')
            recorder = importlib.util.module_from_spec(spec); spec.loader.exec_module(recorder)
        for summaries, skipped in (([], 0), ([{'tests': 0}], 0), ([{'tests': 3}], 1)):
            with self.subTest(summaries=summaries, skipped=skipped), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'receipt'
                def stage(label, arguments, work, timeout):
                    return {'stage': label, 'status': 'PASS', 'unittest_summaries': summaries,
                            'skipped_count': skipped}, b'{}'
                with patch.object(sys, 'argv', ['record_voice_box_checks', '--output', str(output)]), \
                     patch.object(recorder, 'run_stage', side_effect=stage), \
                     patch.object(recorder, 'fingerprints', return_value={}), \
                     contextlib.redirect_stdout(io.StringIO()):
                    status = recorder.main()
                report = json.loads((output / 'result.json').read_bytes())
                self.assertEqual(status, 1)
                self.assertIs(report['success'], False)
                self.assertEqual(report['stages'][0]['error_code'], 'actual_unskipped_tests_required')


if __name__ == '__main__':
    unittest.main()
