"""Use the supplied asset for acceptance; synthetic data is rejection-only.

No test auditions audio or claims a listening review. Native file handling runs
on the current OS; Linux success does not qualify the native Windows reader.
"""
import ast
from contextlib import ExitStack
import hashlib
from html.parser import HTMLParser
import io
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from aster import voice


ORIGINAL_PACK = voice.PACK_PATH


class VoiceInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pack = Path(self.temp.name) / voice.PROFILE_ID
        self.pack.mkdir()

    def copy_original_pack(self):
        for name in voice._FILE_SPECS:
            shutil.copyfile(ORIGINAL_PACK / name, self.pack / name)

    def inspect_copy(self):
        with patch.object(voice, 'PACK_PATH', self.pack):
            return voice.inspect_voice()

    def assert_unavailable(self, result, status='unavailable_invalid_asset'):
        self.assertEqual(result['status'], status)
        self.assertFalse(result['audition_available'])
        self.assertFalse(result['live_synthesis'])
        self.assertFalse(result['ai_response'])
        self.assertEqual(result['synthesis_backend'], 'unavailable_no_runtime')
        self.assertNotIn('preview', result)
        self.assertNotIn('sample', result)

    def test_original_supplied_pack_metadata_and_boundaries(self):
        # Real original bytes, not an invented voice or a mock success.
        result = voice.inspect_voice()
        self.assertEqual(result['status'], 'available_prerecorded_audition')
        self.assertTrue(result['audition_available'])
        self.assertTrue(result['prerecorded'])
        sample = result['sample']
        self.assertEqual(sample['sha256'], '01768f1f65137623bfdd0e49b34211b7f31b315403ca5c7a5c75ed9e392bfd2f')
        self.assertEqual(sample['bytes'], 691244)
        self.assertEqual(sample['channels'], 1)
        self.assertEqual(sample['sample_rate_hz'], 24000)
        self.assertEqual(sample['sample_width_bits'], 16)
        self.assertEqual(sample['frames'], 345600)
        self.assertEqual(sample['duration_seconds'], 14.4)
        self.assertEqual(sample['peak_pcm16'], 24063)
        self.assertAlmostEqual(sample['rms_pcm16'], 2561.416849, places=6)
        self.assertEqual(sample['clipped_samples'], 0)
        self.assertFalse(result['live_synthesis'])
        self.assertFalse(result['ai_response'])
        self.assertFalse(result['newbrain_contribution'])
        self.assertFalse(result['automatic_playback'])
        self.assertEqual(result['listening_review'], 'not_performed')
        self.assertEqual(result['synthesis_backend'], 'unavailable_no_runtime')
        self.assertTrue(result['preview']['manual_only'])
        self.assertTrue(result['preview']['local_file_only'])
        self.assertEqual(Path(result['preview']['path']), ORIGINAL_PACK / 'preview.html')
        self.assertEqual(result['transcript'], (ORIGINAL_PACK / 'transcript.txt').read_text(encoding='utf-8').removesuffix('\n'))

    def test_missing_pack_is_not_created(self):
        missing = self.pack / 'missing'
        with patch.object(voice, 'PACK_PATH', missing):
            self.assert_unavailable(voice.inspect_voice(), 'unavailable_missing_asset')
        self.assertFalse(missing.exists())

    def test_missing_each_required_file_fails_closed(self):
        self.copy_original_pack()
        for name in voice._FILE_SPECS:
            with self.subTest(name=name):
                path = self.pack / name
                data = path.read_bytes()
                path.unlink()
                self.assert_unavailable(self.inspect_copy(), 'unavailable_missing_asset')
                path.write_bytes(data)

    def test_tampered_audio_metadata_transcript_and_preview_rejected(self):
        self.copy_original_pack()
        for name in voice._FILE_SPECS:
            with self.subTest(name=name):
                path = self.pack / name
                data = path.read_bytes()
                changed = bytes([data[0] ^ 1]) + data[1:]
                path.write_bytes(changed)
                self.assert_unavailable(self.inspect_copy())
                path.write_bytes(data)

    def test_fabricated_metadata_cannot_reauthorize_changed_audio(self):
        self.copy_original_pack()
        sample = self.pack / 'sample.wav'
        data = sample.read_bytes() + b'synthetic tampering fixture'
        sample.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        for name in ('profile.json', 'generation.json'):
            path = self.pack / name
            path.write_text(path.read_text().replace(voice._FILE_SPECS['sample.wav'][1], digest))
        self.assert_unavailable(self.inspect_copy())

    def test_oversized_files_rejected_before_content_read(self):
        for name, (limit, _) in voice._FILE_SPECS.items():
            with self.subTest(name=name):
                path = self.pack / name
                # A sparse synthetic rejection fixture, never accepted audio.
                with path.open('wb') as stream:
                    stream.truncate(limit + 1)
                with patch.object(voice, '_read_fd', side_effect=AssertionError('must reject before reading')):
                    with self.assertRaises(ValueError):
                        voice._read_regular(path, limit)
                path.unlink()

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable; reparse guard test still runs')
            raise

    def test_symlink_file_and_dangling_symlink_rejected(self):
        for target in (ORIGINAL_PACK / 'sample.wav', self.pack / 'does-not-exist'):
            with self.subTest(target=str(target)):
                sample = self.pack / 'sample.wav'
                self.symlink(sample, target)
                self.assert_unavailable(self.inspect_copy())
                sample.unlink()

    def test_symlink_directory_and_ancestor_rejected(self):
        linked = self.pack / 'linked'
        self.symlink(linked, ORIGINAL_PACK, directory=True)
        with patch.object(voice, 'PACK_PATH', linked):
            self.assert_unavailable(voice.inspect_voice())
        ancestor = self.pack / 'ancestor'
        self.symlink(ancestor, ORIGINAL_PACK.parent, directory=True)
        with patch.object(voice, 'PACK_PATH', ancestor / voice.PROFILE_ID):
            self.assert_unavailable(voice.inspect_voice())

    def test_reparse_attributes_rejected_without_reading(self):
        # Simulates Windows lstat attributes, not a native Windows qualification.
        original_lstat = Path.lstat
        for target in (self.pack, self.pack / 'sample.wav'):
            with self.subTest(target=str(target)):
                def fake_lstat(path, *args, **kwargs):
                    if path == target:
                        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600,
                            st_file_attributes=0x400, st_nlink=1, st_size=1)
                    return original_lstat(path, *args, **kwargs)
                with patch.object(Path, 'lstat', fake_lstat), \
                        patch.object(voice, '_read_fd', side_effect=AssertionError('reparse file must not be read')):
                    self.assert_unavailable(self.inspect_copy())

    def test_hardlink_rejected(self):
        original = self.pack / 'synthetic-original'
        original.write_bytes(b'synthetic rejection-only content')
        os.link(original, self.pack / 'sample.wav')
        self.assert_unavailable(self.inspect_copy())

    def test_directory_instead_of_regular_file_rejected(self):
        (self.pack / 'sample.wav').mkdir()
        self.assert_unavailable(self.inspect_copy())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO rejection')
    def test_fifo_rejected_without_blocking(self):
        os.mkfifo(self.pack / 'sample.wav')
        self.assert_unavailable(self.inspect_copy())

    def test_synthetic_invalid_wav_fails_metadata_checks(self):
        for data in (b'not a WAV', b'RIFF\x24\x00\x00\x00WAVE', b''):
            with self.subTest(data=data), self.assertRaises((ValueError, wave.Error, EOFError)):
                voice._wav_metadata(data)
        synthetic = io.BytesIO()
        with wave.open(synthetic, 'wb') as audio:
            audio.setparams((1, 2, 24000, 345600, 'NONE', 'not compressed'))
            audio.writeframes(b'\0' * 691200)
        with self.assertRaisesRegex(ValueError, 'signal statistics'):
            voice._wav_metadata(synthetic.getvalue())

    def test_growth_during_read_is_bounded_and_rejected(self):
        path = self.pack / 'synthetic-bounded-file'
        path.write_bytes(b'abcd')
        real_read = os.read
        counts = []
        def changing_read(fd, count):
            counts.append(count)
            if len(counts) == 1:
                with path.open('ab') as stream:
                    stream.write(b'e' * 20)
            return real_read(fd, count)
        with path.open('rb') as stream, patch.object(os, 'read', changing_read):
            with self.assertRaises(ValueError):
                voice._read_fd(stream.fileno(), 8)
        self.assertLessEqual(sum(counts), 9)

    def test_inspection_is_read_only_and_performs_no_automatic_action(self):
        self.copy_original_pack()
        before = {name: (self.pack / name).read_bytes() for name in voice._FILE_SPECS}
        with ExitStack() as stack:
            # No process, network, shell or browser/audio launch is allowed.
            for target in ('subprocess.Popen', 'os.system', 'webbrowser.open',
                           'socket.socket', 'urllib.request.urlopen'):
                stack.enter_context(patch(target, side_effect=AssertionError('automatic action forbidden')))
            result = self.inspect_copy()
        self.assertEqual(result['status'], 'available_prerecorded_audition')
        self.assertEqual(set(before), {entry.name for entry in self.pack.iterdir()})
        for name, data in before.items():
            self.assertEqual(data, (self.pack / name).read_bytes())

    def test_voice_module_does_not_import_generators_network_or_process_tools(self):
        source = Path(voice.__file__).read_text(encoding='utf-8')
        imports = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or '').split('.')[0])
        self.assertFalse(imports & {'subprocess', 'socket', 'urllib', 'requests', 'webbrowser',
                                    'qwen_tts', 'transformers', 'torch', 'sounddevice', 'importlib'})


class PreviewParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class VoicePreviewTests(unittest.TestCase):
    def test_manual_local_audio_only_and_honest_labels(self):
        parser = PreviewParser()
        parser.feed((ORIGINAL_PACK / 'preview.html').read_text(encoding='utf-8'))
        self.assertFalse({'script', 'iframe', 'object', 'embed', 'link', 'form', 'video'} &
                         {tag for tag, _ in parser.tags})
        audio = [attrs for tag, attrs in parser.tags if tag == 'audio']
        self.assertEqual(len(audio), 1)
        self.assertIn('controls', audio[0])
        self.assertNotIn('autoplay', audio[0])
        self.assertEqual(audio[0]['preload'], 'none')
        sources = [attrs for tag, attrs in parser.tags if tag == 'source']
        self.assertEqual(sources, [{'src': 'sample.wav', 'type': 'audio/wav'}])
        for _, attrs in parser.tags:
            self.assertFalse(any(key.startswith('on') for key in attrs))
            for key in ('src', 'href'):
                if key in attrs:
                    self.assertEqual(attrs[key], 'sample.wav')
        policies = [attrs['content'] for tag, attrs in parser.tags
                    if tag == 'meta' and attrs.get('http-equiv') == 'Content-Security-Policy']
        self.assertEqual(len(policies), 1)
        self.assertIn("default-src 'none'", policies[0])
        self.assertIn('media-src file:', policies[0])
        text = ''.join(parser.text)
        self.assertIn('Prerecorded audition', text)
        self.assertIn('not live brain output or a NewBrain response', text)
        self.assertIn('Live speech synthesis is unavailable', text)
        self.assertIn('have not been reviewed by listening', text)
        self.assertIn((ORIGINAL_PACK / 'transcript.txt').read_text(encoding='utf-8').strip(), text)
