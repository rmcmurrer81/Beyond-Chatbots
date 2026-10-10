"""Synthetic deterministic PCM fixtures test processing, never audition quality."""
import ast
import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from aster import media_workshop, voice
from aster.files import Files, MAX_BYTES
from aster.media_workshop import MediaWorkshop
from aster.storage import Store


def wav_bytes(channels=1, width=2, rate=8000, frames=100):
    pcm = bytes((i * 37) % 256 for i in range(channels * width * frames))
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(channels); audio.setsampwidth(width); audio.setframerate(rate); audio.writeframes(pcm)
    return buffer.getvalue(), pcm


class MediaWorkshopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'state')
        self.files = Files(self.store)
        self.workshop = MediaWorkshop(self.store, self.files)

    def tearDown(self):
        self.files.close(); self.store.close(); self.temp.cleanup()

    def source(self, **kwargs):
        raw, pcm = wav_bytes(**kwargs)
        self.files.change('media/source.wav', raw)
        return raw, pcm

    def preview(self, start=10, end=50, target='media/exports/clip.wav'):
        return self.workshop.preview_trim('media/source.wav', start, end, target)

    def trim(self, preview):
        return self.workshop.trim(preview['path'], preview['start_frame'], preview['end_frame'],
                                  preview['output_path'], expected_sha256=preview['sha256'], approved=True)

    def test_inspect_exact_formats_duration_frames_and_hashes(self):
        for channels in (1, 2):
            for width in (1, 2, 3, 4):
                with self.subTest(channels=channels, width=width):
                    raw, pcm = self.source(channels=channels, width=width, frames=101)
                    info = self.workshop.inspect('media/source.wav')
                    self.assertEqual(info['frames'], 101)
                    self.assertEqual(info['duration_fraction'], '101/8000')
                    self.assertEqual(info['duration_seconds'], 101/8000)
                    self.assertEqual(info['sample_width_bits'], 8 * width)
                    self.assertEqual(info['channels'], channels)
                    self.assertEqual(info['sha256'], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(info['pcm_sha256'], hashlib.sha256(pcm).hexdigest())
                    self.assertFalse(info['automatic_playback'])

    def test_preview_has_no_files_or_journal_mutations(self):
        self.source()
        before = self.store.rows('changes')
        preview = self.preview()
        self.assertEqual(preview['status'], 'preview_only_not_written')
        self.assertIsNone(preview['previous_output_sha256'])
        self.assertIsNone(self.files.snapshot(preview['output_path']))
        self.assertEqual(self.store.rows('changes'), before)

    def test_exact_trim_sample_bytes_original_unchanged_and_undo(self):
        for channels, width in ((1, 1), (2, 2), (2, 3), (1, 4)):
            with self.subTest(channels=channels, width=width):
                raw, pcm = self.source(channels=channels, width=width)
                result = self.trim(self.preview(start=9, end=50))
                self.assertEqual(result['status'], 'trimmed_local_copy')
                self.assertEqual(self.files.read('media/source.wav'), raw)
                with wave.open(io.BytesIO(self.files.read(result['output_path'])), 'rb') as audio:
                    self.assertEqual(audio.getnframes(), 41)
                    self.assertEqual(audio.readframes(100), pcm[9*channels*width:50*channels*width])
                self.files.undo(result['change_id'])
                self.assertIsNone(self.files.snapshot(result['output_path']))

    def test_overwrite_requires_reviewed_previous_bytes_and_undo_restores(self):
        self.source()
        original = b'Existing user file, deliberately reviewed for overwrite'
        self.files.change('media/exports/clip.wav', original)
        preview = self.preview()
        self.assertEqual(preview['previous_output_sha256'], hashlib.sha256(original).hexdigest())
        result = self.trim(preview)
        self.files.undo(result['change_id'])
        self.assertEqual(self.files.read('media/exports/clip.wav'), original)

    def test_stale_receipt_rejects_new_source_output_and_selection(self):
        self.source(); initial = self.preview()
        self.files.change('media/exports/clip.wav', b'new output')
        with self.assertRaisesRegex(ValueError, 'SHA-256'): self.trim(initial)
        preview = self.preview(); self.source(frames=120)
        with self.assertRaisesRegex(ValueError, 'SHA-256'): self.trim(preview)
        preview = self.preview()
        for start, end, target in ((11, 50, preview['output_path']), (10, 51, preview['output_path']), (10, 50, 'media/exports/other.wav')):
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.workshop.trim('media/source.wav', start, end, target, expected_sha256=preview['sha256'], approved=True)

    def test_approval_boolean_and_receipt_are_required(self):
        self.source(); preview = self.preview()
        for approved, digest in ((False, preview['sha256']), (1, preview['sha256']), ('yes', preview['sha256']),
                                 (True, preview['source_sha256']), (True, None)):
            with self.assertRaises(ValueError):
                self.workshop.trim('media/source.wav', 10, 50, preview['output_path'], expected_sha256=digest, approved=approved)
        self.assertIsNone(self.files.snapshot(preview['output_path']))

    def test_bad_frames_paths_formats_and_output_scope(self):
        self.source()
        for start, end in ((-1, 10), (10, 10), (10, 101), (True, 10), (1, False), (1.0, 10)):
            with self.assertRaises(ValueError): self.preview(start, end)
        for target in ('media/source.wav', 'media/exports/../../escape.wav', '../outside.wav',
                       '/tmp/outside.wav', 'elsewhere/clip.wav', 'media/exports/clip.mp3',
                       'media/exports.wav', 'media\\exports\\clip.wav'):
            with self.assertRaises(ValueError): self.preview(target=target)
        self.files.change('media/exports/existing.wav', wav_bytes()[0])
        with self.assertRaises(ValueError): self.workshop.preview_trim('media/exports/existing.wav', 1, 5, 'media/exports/EXISTING.wav')
        with self.assertRaises(ValueError): self.workshop.inspect('source.mp3')

    def test_corrupt_truncated_oversized_compressed_and_inconsistent_wav(self):
        raw, _ = self.source()
        invalid = [b'not wav', raw[:-1], raw + b'junk', b'RIFX' + raw[4:]]
        for offset, fmt, value in ((20, '<H', 3), (22, '<H', 3), (24, '<I', 7999),
                                    (28, '<I', 1), (32, '<H', 1), (34, '<H', 12), (40, '<I', 199)):
            bad = bytearray(raw); struct.pack_into(fmt, bad, offset, value); invalid.append(bytes(bad))
        for bad in invalid:
            self.files.change('bad.wav', bad)
            with self.subTest(header=bad[:44]), self.assertRaises(ValueError): self.workshop.inspect('bad.wav')
        with self.assertRaises(ValueError): media_workshop._wav(b'x' * (MAX_BYTES + 1))
        with self.assertRaises(ValueError): media_workshop._wav(wav_bytes(frames=0)[0])

    def test_unknown_metadata_is_not_executed_and_is_dropped_from_output(self):
        raw, pcm = wav_bytes()
        payload = b'run arbitrary executable now!'
        extra = b'JUNK' + struct.pack('<I', len(payload)) + payload + (b'\0' if len(payload) % 2 else b'')
        combined = raw + extra
        combined = combined[:4] + struct.pack('<I', len(combined)-8) + combined[8:]
        self.files.change('media/source.wav', combined)
        result = self.trim(self.preview())
        self.assertTrue(result['dropped_ancillary_metadata'])
        self.assertNotIn(payload, self.files.read(result['output_path']))
        self.assertEqual(self.files.read('media/source.wav'), combined)

    def test_duplicate_chunks_and_missing_padding_rejected(self):
        raw, _ = self.source()
        for extra in (raw[12:36], raw[36:], b'JUNK\x08\0\0\0x', b'JUNK\x01\0\0\0xNEXT\0\0\0\0'):
            bad = raw + extra; bad = bad[:4] + struct.pack('<I', len(bad)-8) + bad[8:]
            with self.assertRaises(ValueError): media_workshop._wav(bad)

    @unittest.skipUnless(os.name == 'posix', 'POSIX links; native Windows requires separate qualification')
    def test_symlink_hardlink_fifo_and_output_parent_escape_rejected(self):
        raw, _ = self.source()
        outside = Path(self.temp.name) / 'outside.wav'; outside.write_bytes(raw)
        (self.files.root / 'link.wav').symlink_to(outside)
        os.link(outside, self.files.root / 'hard.wav')
        os.mkfifo(self.files.root / 'pipe.wav')
        for path in ('link.wav', 'hard.wav', 'pipe.wav', '../outside.wav'):
            with self.assertRaises((ValueError, OSError)): self.workshop.inspect(path)
        (self.files.root / 'media' / 'exports').symlink_to(self.temp.name, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)): self.preview()
        self.assertEqual(outside.read_bytes(), raw)

    def test_journal_recovery_and_external_edit_guard(self):
        self.source(); preview = self.preview()
        with patch.object(self.files, '_replace', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): self.trim(preview)
        with self.assertRaisesRegex(ValueError, 'recover'): self.trim(preview)
        self.assertEqual(self.files.recover()[0]['status'], 'not_applied')
        result = self.trim(preview)
        (self.files.root / result['output_path']).write_bytes(b'external edit')
        with self.assertRaises(ValueError): self.files.undo(result['change_id'])

    def test_real_voice_pack_inspected_through_existing_integrity_checks(self):
        before = {name: hashlib.sha256((voice.PACK_PATH/name).read_bytes()).hexdigest() for name in voice._FILE_SPECS}
        result = self.workshop.inspect_voice()
        self.assertEqual(result['status'], 'available_prerecorded_audition')
        self.assertEqual(result['sample']['sha256'], before['sample.wav'])
        self.assertFalse(result['live_synthesis'])
        self.assertFalse(result['ai_response'])
        self.assertEqual(before, {name: hashlib.sha256((voice.PACK_PATH/name).read_bytes()).hexdigest() for name in voice._FILE_SPECS})
        with patch.object(voice, 'inspect_voice', return_value={'status': 'unavailable_invalid_asset'}) as check:
            self.assertEqual(self.workshop.inspect_voice()['status'], 'unavailable_invalid_asset')
            check.assert_called_once_with()

    def test_no_network_process_playback_or_model_activation(self):
        self.source()
        with patch('socket.socket', side_effect=AssertionError('No network')), patch('subprocess.Popen', side_effect=AssertionError('No process')):
            self.workshop.inspect('media/source.wav'); self.trim(self.preview()); self.workshop.inspect_voice()
        status = self.workshop.status()
        for key in ('automatic_playback', 'subprocess_enabled', 'network_enabled', 'live_synthesis',
                    'model_inference', 'video_editing', 'avatars', 'zotero_integration'):
            self.assertIs(status[key], False)
        tree = ast.parse(Path(media_workshop.__file__).read_text())
        imports = {alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imports & {'subprocess', 'socket', 'requests', 'torch', 'transformers', 'ffmpeg'})


if __name__ == '__main__': unittest.main()
