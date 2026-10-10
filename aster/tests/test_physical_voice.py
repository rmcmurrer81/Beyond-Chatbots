"""Fast data/interface contracts; explicit waveform qualification is opt-in.

Run actual-WAV/IO qualification in experiments.physical_voice.test_pipeline_numerical.
Nothing plays sound, opens a microphone, reaches a network, or runs NewBrain.
"""
import contextlib
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from experiments.physical_voice import bridge, demo, pipeline, protocol, storage
from experiments.newbrain_text.persistence import LabError

OWNER = 'synthetic_aster'


def short_plan(**kwargs):
    return protocol.make_plan([protocol.gesture(duration_ms=50)], **kwargs)


def signed_checkpoint(state):
    return {'state': state, 'sha256': protocol.digest(state)}


class PhysicalIntentTests(unittest.TestCase):
    def test_original_default_direction_is_motor_data(self):
        plan = protocol.demo_plan()
        self.assertEqual(plan['owner'], OWNER)
        self.assertEqual(plan['source']['stiffness_scale'], 2.)
        self.assertEqual(plan['sample_rate'], 48000)
        self.assertEqual(plan['substeps'], 4)
        self.assertEqual(protocol.frame_count(plan), 93600)
        self.assertEqual(plan['origin'], {'kind': 'manual_motor_intent'})
        self.assertNotIn('pitch', protocol.canonical(plan).decode())

    def test_closed_intent_source_gesture_pose(self):
        for part in ('plan', 'source', 'gesture', 'pose'):
            for mutation in ('missing', 'extra'):
                plan = short_plan()
                value = {'plan': plan, 'source': plan['source'], 'gesture': plan['gestures'][0],
                         'pose': plan['gestures'][0]['pose']}[part]
                if mutation == 'extra':
                    value['unexpected'] = 0
                else:
                    value.pop(next(iter(value)))
                with self.subTest(part=part, mutation=mutation), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)

    def test_bad_root_types(self):
        for value in (None, [], True, 123, 'untrusted'):
            with self.subTest(value=value), self.assertRaises(protocol.VoiceError):
                protocol.validate(value)

    def test_owner_shape_and_binding(self):
        for owner in ('aster', 'synthetic_', 'synthetic_Aster', 'synthetic_a/b', '', True, None):
            with self.subTest(owner=owner), self.assertRaises(protocol.VoiceError):
                short_plan(owner=owner)
        with self.assertRaisesRegex(protocol.VoiceError, 'voice_owner_mismatch'):
            protocol.validate(short_plan(), 'synthetic_other')

    def test_fixed_rate_and_no_commanded_oscillator(self):
        for key, values in {'schema': [True, 'other'], 'profile': ['copied_voice'],
                            'sample_rate': [24000, 48000., True], 'substeps': [2, 8, 4., True]}.items():
            for value in values:
                plan = short_plan(); plan[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)
        for key in ('pitch_hz', 'seed', 'oscillator', 'provider', 'voice_file'):
            plan = short_plan(); plan[key] = 220
            with self.subTest(key=key), self.assertRaises(protocol.VoiceError):
                protocol.validate(plan)

    def test_hostile_numbers(self):
        for bad in (None, True, '1', math.nan, math.inf, -math.inf, 10**1000):
            for group, key in (('source', 'pressure_pa'), ('source', 'stiffness_scale'),
                               ('source', 'damping_kg_s'), ('source', 'rest_half_gap_m'),
                               ('plan', 'velum'), ('plan', 'delivery_gain'), ('pose', 'tongue_height')):
                plan = short_plan()
                target = plan if group == 'plan' else plan['gestures'][0]['pose'] if group == 'pose' else plan['source']
                target[key] = bad
                with self.subTest(key=key, bad=type(bad).__name__), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)

    def test_public_controls_narrower_than_numerical_core(self):
        for key, values in {'pressure_pa': [-.001, 1000.001], 'stiffness_scale': [.999, 2.001],
                            'damping_kg_s': [.0179, .0241], 'rest_half_gap_m': [0., .000139, .000221]}.items():
            for value in values:
                plan = short_plan(); plan['source'][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(protocol.VoiceError):
                    protocol.validate(plan)
        for value in (-1, .00001, .00999, 1.01):
            with self.subTest(velum=value), self.assertRaises(protocol.VoiceError):
                short_plan(velum=value)
        for value in (0., .01, 1.):
            self.assertEqual(short_plan(velum=value)['velum'], value)

    def test_duration_gesture_and_pose_bounds(self):
        for value in (0, 49, 1501, True, 50., '50'):
            with self.subTest(value=value), self.assertRaises(protocol.VoiceError):
                protocol.make_plan([protocol.gesture(duration_ms=value)])
        for gestures in ([], [protocol.gesture(duration_ms=50)] * 13,
                         [protocol.gesture(duration_ms=1500)] * 3, (protocol.gesture(),)):
            with self.assertRaises(protocol.VoiceError):
                protocol.make_plan(gestures)
        self.assertEqual(protocol.frame_count(protocol.make_plan([protocol.gesture(duration_ms=1500)] * 2)), 144000)
        for key in protocol.POSE_KEYS:
            plan = short_plan(); plan['gestures'][0]['pose'][key] = 1.001
            with self.subTest(key=key), self.assertRaises(protocol.VoiceError):
                protocol.validate(plan)

    def test_json_complexity_and_canonical_refusals(self):
        for raw in (b'', b'\xff', b'{', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                    b'[' * 100 + b']' * 100, b'[' + b'0,' * 9000 + b'0]', b' ' * 32769,
                    '{}', bytearray(b'{}')):
            with self.subTest(size=len(raw)), self.assertRaises(protocol.VoiceError):
                protocol.parse_json(raw)
        cyclic = []; cyclic.append(cyclic)
        for value in (cyclic, object(), {'x': math.inf}):
            with self.assertRaises(protocol.VoiceError):
                protocol.canonical(value)

    def test_plan_and_checkpoint_are_detached(self):
        plan = short_plan(); saved = protocol.validate(plan); box = pipeline.PhysicalVoice(plan)
        plan['source']['pressure_pa'] = 1
        saved['gestures'][0]['pose']['jaw_opening'] = 0
        returned = box.plan; returned['delivery_gain'] = 0
        checkpoint = box.checkpoint(); checkpoint['state']['binding']['engine'] = 'changed'
        binding = box.binding; binding['engine'] = 'changed'
        self.assertEqual(box.plan, short_plan())
        self.assertEqual(box.binding['engine'], pipeline.ENGINE)
        self.assertEqual(box.checkpoint()['state']['binding']['engine'], pipeline.ENGINE)


class PhysicalStateTests(unittest.TestCase):
    def test_zero_progress_checkpoint_is_complete_and_roundtrips(self):
        plan = short_plan()
        box = pipeline.PhysicalVoice(plan)
        state = pipeline.validate_checkpoint(plan, box.checkpoint())
        self.assertEqual(state['filter']['input_samples'], 0)
        self.assertEqual(len(state['filter']['ring']), 145)
        self.assertEqual(len(state['tract']['waves']['oral_forward']), 24)
        self.assertEqual(len(state['tract']['waves']['nasal_backward']), 16)
        restored = pipeline.PhysicalVoice.restore(plan, box.checkpoint(), OWNER)
        self.assertEqual(restored.checkpoint(), box.checkpoint())

    def test_mechanical_parameters_fixed_and_pressure_ramps_explicit(self):
        plan = short_plan()
        mp = pipeline.mechanical_plan(plan)
        self.assertEqual(mp.parameters.lower_stiffness_n_m, 160.)
        self.assertEqual(mp.parameters.coupling_stiffness_n_m, 50.)
        self.assertEqual(mp.initial.lower_displacement_m, 1e-9)
        self.assertEqual(mp.pressure.at(0.), 0.)
        self.assertEqual(mp.pressure.at(.015), 800.)
        self.assertEqual(mp.pressure.at(.05), 0.)
        self.assertAlmostEqual(mp.pressure.at(.0075), 400.)
        self.assertEqual(mp.integration_rate, 192000)

    def test_latency_phase_and_delivery_constants_are_fixed(self):
        self.assertEqual(pipeline.timing()['fir_delay_frames'], 18)
        self.assertFalse(pipeline.timing()['delay_trimmed'])
        self.assertFalse(pipeline.timing()['zero_tail_flushed'])
        self.assertEqual(pipeline.timing()['first_source_endpoint_time_s'], 1/192000)
        self.assertEqual(protocol.FS_PER_SQRT_WATT, 2.)
        self.assertEqual(pipeline.PCM_LIMIT, 6553)

    def test_digest_owner_intent_source_and_runtime_mismatch(self):
        plan = short_plan(); cp = pipeline.PhysicalVoice(plan).checkpoint()
        cp['sha256'] = '0' * 64
        with self.assertRaises(protocol.VoiceError):
            pipeline.validate_checkpoint(plan, cp)
        for key, value in (('owner', 'synthetic_other'), ('intent_sha256', '0' * 64), ('cursor', True)):
            cp = pipeline.PhysicalVoice(plan).checkpoint(); cp['state'][key] = value
            with self.subTest(key=key), self.assertRaises(protocol.VoiceError):
                pipeline.validate_checkpoint(plan, signed_checkpoint(cp['state']))
        cp = pipeline.PhysicalVoice(plan).checkpoint()
        cp['state']['binding']['runtime']['machine'] = 'different'
        cp = signed_checkpoint(cp['state'])
        pipeline.validate_checkpoint(plan, cp)  # Inspection permits a foreign runtime.
        with self.assertRaisesRegex(protocol.VoiceError, 'checkpoint_engine_runtime_mismatch'):
            pipeline.PhysicalVoice.restore(plan, cp, OWNER)

    def test_nested_unknown_missing_and_nonfinite_states_refused(self):
        plan = short_plan()
        for path in (('folds',), ('window',), ('filter',), ('tract',), ('pose',),
                     ('folds', 'mechanics'), ('tract', 'waves')):
            for mode in ('extra', 'missing'):
                cp = pipeline.PhysicalVoice(plan).checkpoint(); part = cp['state']
                for key in path:
                    part = part[key]
                if mode == 'extra':
                    part['unknown'] = 1
                else:
                    part.pop(next(iter(part)))
                with self.subTest(path=path, mode=mode), self.assertRaises(protocol.VoiceError):
                    pipeline.validate_checkpoint(plan, signed_checkpoint(cp['state']))
        cp = pipeline.PhysicalVoice(plan).checkpoint(); cp['state']['filter']['ring'][0] = math.nan
        with self.assertRaises(protocol.VoiceError):
            pipeline.validate_checkpoint(plan, cp)

    def test_component_progress_and_geometry_binding(self):
        plan = short_plan()
        for part, key, value in (('filter', 'input_samples', 4), ('tract', 'sample_index', 1),
                                 ('folds', 'substep_index', 4), ('pose', 'jaw_opening', .1)):
            cp = pipeline.PhysicalVoice(plan).checkpoint(); cp['state'][part][key] = value
            with self.subTest(part=part, key=key), self.assertRaises(protocol.VoiceError):
                pipeline.validate_checkpoint(plan, signed_checkpoint(cp['state']))
        for component, config in (('filter', 'config'), ('tract', 'config'), ('folds', 'plan')):
            cp = pipeline.PhysicalVoice(plan).checkpoint(); cp['state'][component][config]['unexpected'] = 1
            with self.subTest(component=component), self.assertRaises(protocol.VoiceError):
                pipeline.validate_checkpoint(plan, signed_checkpoint(cp['state']))

    def test_inspection_validation_never_steps_physics(self):
        plan = short_plan(); cp = pipeline.PhysicalVoice(plan).checkpoint()
        with patch.object(pipeline.folds.FoldStepper, 'step_substep', side_effect=AssertionError('step forbidden')), \
             patch.object(pipeline.tract.OralNasalTract, 'step', side_effect=AssertionError('step forbidden')), \
             patch.object(pipeline.filters.FlowDecimator, 'push', side_effect=AssertionError('push forbidden')):
            pipeline.validate_checkpoint(plan, cp)

    def test_windows_binding_does_not_probe_platform_hostname(self):
        import platform
        with patch.object(platform, 'system', side_effect=AssertionError('hostname probe')), \
             patch.object(platform, 'machine', side_effect=AssertionError('hostname probe')):
            pipeline.validate_binding(pipeline.engine_binding())

    def test_frame_request_and_runtime_quota_refusals(self):
        for count in (-1, True, 1., 144001):
            with self.subTest(count=count), self.assertRaises(protocol.VoiceError):
                pipeline.PhysicalVoice(short_plan()).render_frames(count)
        box = pipeline.PhysicalVoice(short_plan(), deadline=-1.)
        with self.assertRaisesRegex(protocol.VoiceError, 'render_runtime_quota'):
            box.render_frames(1)
        with self.assertRaisesRegex(protocol.VoiceError, 'renderer_failed'):
            box.checkpoint()

    def test_pcm_actual_measurement_and_canonical_wav(self):
        pcm = struct.pack('<hhhh', 0, 6553, -6553, 0)
        measured = pipeline.measurements(pcm)
        self.assertEqual(measured['peak_pcm'], 6553)
        self.assertEqual(measured['nonzero_samples'], 2)
        self.assertTrue(measured['within_delivery_ceiling'])
        self.assertEqual(len(pipeline.wav_bytes(pcm)), 52)
        self.assertIsNone(pipeline.measurements(bytes(20))['peak_dbfs'])
        for data in (b'', b'a', bytearray(4), bytes(288002)):
            with self.assertRaises(protocol.VoiceError):
                pipeline.measurements(data)


class PhysicalBridgeAndFileTests(unittest.TestCase):
    def test_actual_wrong_label_is_not_replaced_with_target(self):
        envelope = {'report_sha256': '1'*64, 'models': {'INTERLEAVED': {'model_sha256': '2'*64}}}
        row = {'generation': {'tokens': ['cool'], 'terminated_with_eos': True}, 'exact_correct': False}
        report = {'arms': {'INTERLEAVED': {'evaluation': {'new': [row]}}}}
        with patch('experiments.newbrain_text.persistence.read_state', return_value=(envelope, report)) as read:
            plan = bridge.from_text_lab('unread-test-path', OWNER)
        read.assert_called_once_with('unread-test-path', OWNER)
        self.assertEqual(plan['gestures'][0]['pose'], protocol.POSES['rounded'])
        self.assertEqual(plan['origin']['observed_token'], 'cool')
        self.assertFalse(plan['origin']['exact_correct'])
        self.assertEqual(plan['origin']['report_sha256'], '1'*64)
        self.assertEqual(plan['origin']['model_sha256'], '2'*64)

    def test_adapter_refuses_unsupported_output_and_bad_selection(self):
        envelope = {'report_sha256': '1'*64, 'models': {'INTERLEAVED': {'model_sha256': '2'*64}}}
        for tokens, eos in (([], True), (['other'], True), (['warm', 'cool'], True), (['warm'], False)):
            report = {'arms': {'INTERLEAVED': {'evaluation': {'new': [
                {'generation': {'tokens': tokens, 'terminated_with_eos': eos}, 'exact_correct': False}]}}}}
            with patch('experiments.newbrain_text.persistence.read_state', return_value=(envelope, report)), \
                 self.assertRaisesRegex(protocol.VoiceError, 'unsupported_observed_output'):
                bridge.from_text_lab('unread-test-path')
        for kwargs in ({'method': 'qwen'}, {'split': 'private'}, {'case_index': True}, {'case_index': 6}):
            with self.assertRaises(protocol.VoiceError):
                bridge.from_text_lab('unread-test-path', **kwargs)
        with patch('experiments.newbrain_text.persistence.read_state', side_effect=LabError('sensitive-path')), \
             self.assertRaisesRegex(protocol.VoiceError, '^text_lab_state_refused$'):
            bridge.from_text_lab('unread-test-path')

    def test_file_reads_reject_links_size_and_nonregular(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); plain = root/'plain'; plain.write_bytes(b'{}')
            self.assertEqual(storage.read_plain(plain, 2), b'{}')
            with self.assertRaises(protocol.VoiceError):
                storage.read_plain(plain, 1)
            if hasattr(os, 'link'):
                hard = root/'hard'; os.link(plain, hard)
                with self.assertRaises(protocol.VoiceError):
                    storage.read_plain(plain, 10)
                hard.unlink()
            if hasattr(os, 'symlink'):
                link = root/'link'; link.symlink_to(plain)
                with self.assertRaises(protocol.VoiceError):
                    storage.read_plain(link, 10)
            with self.assertRaises(protocol.VoiceError):
                storage.read_plain(root, 10)

    def test_destination_is_checked_before_any_render(self):
        with tempfile.TemporaryDirectory() as directory:
            occupied = Path(directory)/'occupied'; occupied.mkdir()
            with patch.object(storage, 'PhysicalVoice', side_effect=AssertionError('must not render')), \
                 self.assertRaisesRegex(protocol.VoiceError, 'voice_destination_refused'):
                storage.render_bundle(occupied, short_plan())
            with patch.object(storage, 'PhysicalVoice', side_effect=AssertionError('must not render')), \
                 self.assertRaisesRegex(protocol.VoiceError, 'voice_destination_refused'):
                storage.render_bundle(Path(directory)/'missing'/'output', short_plan())

    def test_cli_fixed_errors_do_not_echo_sensitive_paths(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = demo.main(['render', '--intent', '/private/do-not-echo.json', '--output', '/private/output'])
        self.assertEqual(status, 2)
        self.assertNotIn('private', stderr.getvalue())
        self.assertEqual(stdout.getvalue(), '')
        with contextlib.redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit):
            demo.main(['unsupported-secret-command'])
        self.assertEqual(stderr.getvalue(), 'error: invalid_arguments\n')

    def test_cli_generic_failure_and_cancellation_are_fixed(self):
        for exception, status, code in ((RuntimeError('secret-path'), 2, 'physical_voice_failed'),
                                         (KeyboardInterrupt(), 130, 'operation_cancelled')):
            with patch.object(storage, 'inspect_bundle', side_effect=exception), \
                 contextlib.redirect_stderr(io.StringIO()) as stderr:
                result = demo.main(['inspect', '--bundle', 'private-bundle'])
            self.assertEqual(result, status)
            self.assertEqual(stderr.getvalue(), 'error: ' + code + '\n')




if __name__ == '__main__':
    unittest.main()
