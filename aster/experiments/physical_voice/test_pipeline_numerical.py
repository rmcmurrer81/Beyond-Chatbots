"""Explicit actual-waveform qualification, separate from fast root discovery.

Run: python -m unittest experiments.physical_voice.test_pipeline_numerical -v
No playback, microphone, network, training or production-brain activation.
"""
import copy
import hashlib
import json
import subprocess
import sys
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from experiments.physical_voice import pipeline, protocol, storage
OWNER = 'synthetic_aster'
def short_plan(**kwargs):
    return protocol.make_plan([protocol.gesture(duration_ms=50)], **kwargs)


class PhysicalWaveformQualification(unittest.TestCase):
    def test_full_bundle_inspect_recheck_and_atomic_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root/'bundle'
            receipt = storage.render_bundle(output, short_plan())
            self.assertTrue(receipt['checkpoint_resume_exact'])
            self.assertTrue(receipt['render_exact'])
            self.assertEqual(receipt['measurement']['frames'], 2400)
            self.assertTrue(receipt['measurement']['within_delivery_ceiling'])
            with patch.object(pipeline.PhysicalVoice, 'render_frames', side_effect=AssertionError('no synthesis')):
                inspected = storage.inspect_bundle(output)
            self.assertFalse(inspected['synthesis_performed'])
            self.assertFalse(inspected['checkpoint_replay_checked_now'])
            self.assertTrue(storage.recheck_bundle(output)['diagnostics_exact_checked_now'])
            original = (output/'preview.wav').read_bytes()
            with self.assertRaises(protocol.VoiceError):
                storage.render_bundle(output, short_plan())
            self.assertEqual((output/'preview.wav').read_bytes(), original)
            (output/'extra').write_bytes(b'x')
            with self.assertRaises(protocol.VoiceError):
                storage.inspect_bundle(output)
            (output/'extra').unlink()
            (output/'preview.wav').write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            with self.assertRaises(protocol.VoiceError):
                storage.inspect_bundle(output)

    def test_chunk_resume_and_gain_are_delivery_only(self):
        plan = protocol.make_plan([protocol.gesture('open', 50), protocol.gesture('rounded', 50)])
        box = pipeline.PhysicalVoice(plan)
        first = box.render_frames(3011); checkpoint = box.checkpoint(); rest = box.render_frames(box.frames)
        restored = pipeline.PhysicalVoice.restore(plan, checkpoint, OWNER)
        self.assertEqual(restored.render_frames(restored.frames), rest)
        self.assertEqual(restored.diagnostics(), box.diagnostics())
        self.assertEqual(first + rest, pipeline.render(plan))
        low = copy.deepcopy(plan); low['delivery_gain'] = 0.
        muted = pipeline.PhysicalVoice(low); pcm = muted.render_frames(muted.frames)
        self.assertEqual(pcm, bytes(len(pcm)))
        for key in ('mechanical_per_fold', 'mechanical_window_all_endpoints', 'acoustic', 'raw_signals'):
            self.assertEqual(muted.diagnostics()[key], box.diagnostics()[key])

    def test_publication_cleanup_on_failure_and_cancellation(self):
        for exception in (OSError('synthetic-write-error'), KeyboardInterrupt()):
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory)/'bundle'
                with patch.object(storage, '_sync_directory', side_effect=exception), self.assertRaises((protocol.VoiceError, KeyboardInterrupt)):
                    storage.render_bundle(target, short_plan(pressure_pa=0.))
                self.assertFalse(target.exists())
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cold_cli_render_inspect_recheck_without_runtime_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intent = root / 'intent.json'
            intent.write_bytes(protocol.canonical(short_plan(velum=.4)))
            target = root / 'cold-bundle'
            for arguments in (['render', '--intent', str(intent), '--output', str(target)],
                              ['inspect', '--bundle', str(target)], ['recheck', '--bundle', str(target)]):
                command = [sys.executable, '-m', 'experiments.physical_voice.demo', *arguments]
                completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertFalse(result['production_brain_enabled'])
                self.assertFalse(result['brain_executed'])
                self.assertFalse(result['automatic_playback'])
            self.assertTrue(result['checkpoint_resume_exact_checked_now'])

    def test_rehashed_data_still_obeys_closed_schemas_pcm_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'bundle'
            storage.render_bundle(target, short_plan())
            original = {path.name: path.read_bytes() for path in target.iterdir()}
            def changed(name, transform):
                for key, raw in original.items():
                    (target / key).write_bytes(raw)
                value = json.loads(original[name])
                transform(value)
                raw = protocol.canonical(value)
                (target / name).write_bytes(raw)
                manifest = json.loads(original['manifest.json'])
                manifest['files'][name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                (target / 'manifest.json').write_bytes(protocol.canonical(manifest))
            def corrupt_state(value):
                value['state']['tract']['waves']['oral_forward'][0] = 101.
                value['sha256'] = protocol.digest(value['state'])
            cases = [('receipt.json', lambda value: value.update(unknown_field=True)),
                     ('receipt.json', lambda value: value['measurement'].update(peak_pcm=0)),
                     ('receipt.json', lambda value: value['diagnostics']['delivery'].update(limiter_activations=True)),
                     ('intent.json', lambda value: value['gestures'][0]['pose'].update(voice_clone='no')),
                     ('checkpoint.json', corrupt_state)]
            for name, transform in cases:
                changed(name, transform)
                with self.subTest(name=name), self.assertRaises(protocol.VoiceError):
                    storage.inspect_bundle(target)

    def test_atomic_publish_never_replaces_a_raced_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'bundle'
            original_rename = storage._rename_exclusive
            def race(source, destination):
                destination.mkdir()
                (destination / 'keep').write_text('existing data')
                original_rename(source, destination)
            with patch.object(storage, '_rename_exclusive', side_effect=race), self.assertRaises(protocol.VoiceError):
                storage.render_bundle(target, short_plan(pressure_pa=0.))
            self.assertEqual((target / 'keep').read_text(), 'existing data')
            self.assertEqual([path.name for path in Path(directory).iterdir()], ['bundle'])

    def test_source_off_is_quiet_and_extreme_motor_controls_remain_finite(self):
        plan = short_plan(pressure_pa=0.)
        box = pipeline.PhysicalVoice(plan)
        pcm = box.render_frames(box.frames)
        self.assertEqual(pcm, bytes(len(pcm)))
        self.assertEqual(box.diagnostics()['acoustic']['source_work_j'], 0.)
        for stiffness, damping, gap, velum in ((1., .018, .00014, .01), (2., .024, .00022, 1.)):
            plan = short_plan(pressure_pa=1000., stiffness_scale=stiffness,
                              damping_kg_s=damping, rest_half_gap_m=gap, velum=velum)
            for index, key in enumerate(protocol.POSE_KEYS):
                plan['gestures'][0]['pose'][key] = index % 2
            box = pipeline.PhysicalVoice(plan)
            pcm = box.render_frames(box.frames)
            pipeline.validate_checkpoint(plan, box.checkpoint())
            self.assertTrue(pipeline.measurements(pcm)['within_delivery_ceiling'])
            self.assertLess(box.diagnostics()['acoustic']['max_abs_ledger_residual_j'], 1e-12)

    def test_maximum_three_second_extent_is_finite_without_normalization(self):
        plan = protocol.make_plan([protocol.gesture('open', 1500), protocol.gesture('front', 1500)], velum=.4)
        box = pipeline.PhysicalVoice(plan)
        pcm = box.render_frames(box.frames)
        measured = pipeline.measurements(pcm)
        self.assertEqual(measured['frames'], 144000)
        self.assertEqual(measured['duration_s'], 3.)
        self.assertEqual(measured['first_sample'], 0)
        self.assertEqual(measured['last_sample'], 0)
        self.assertGreater(measured['nonzero_samples'], 0)
        self.assertTrue(measured['within_delivery_ceiling'])
        self.assertEqual(box.diagnostics()['delivery']['fixed_fs_per_sqrt_watt'], 2.)
        pipeline.validate_checkpoint(plan, box.checkpoint())

    def test_post_commit_cancellation_reports_published_durability(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'bundle'
            sync = storage._sync_directory
            def interrupt_parent(path):
                if Path(path) == Path(directory):
                    raise KeyboardInterrupt()
                return sync(path)
            with patch.object(storage, '_sync_directory', side_effect=interrupt_parent), \
                 self.assertRaisesRegex(protocol.VoiceError, '^voice_published_durability_unconfirmed$'):
                storage.render_bundle(target, short_plan(pressure_pa=0.))
            self.assertTrue(target.is_dir())
            self.assertFalse(storage.inspect_bundle(target)['synthesis_performed'])


if __name__ == '__main__':
    unittest.main()
