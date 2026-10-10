"""Source-authored fixtures. Parser/unit fixtures never establish native OCR accuracy.

Every method is UNRUN in the publication receipt. Opt-in pixel fixtures require a
separately approved local window and qualified/pinned installation; no auto-download.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from core import photo_ocr as ocr

H = "a" * 64
HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def capture(photos=None):
    return ocr.make_capture("humanoidresearcher", "project", H, 1, "item",
        photos or [{"sha256": H, "bytes": 24, "media_type": "image/png"}],
        state_sha256=H, review_sha256=H, provider_selection_sha256=H, ai_config_sha256=H)


def config(enabled=False):
    # Deliberately nonexistent test-only settings; no production passed receipt ships.
    return {"format": ocr.CONFIG_FORMAT, "enabled": enabled, "runtime_root": "C:/not-installed-ocr",
            "python": "python/python.exe", "engine": "engine/tesseract.exe",
            "model": "engine/tessdata/eng.traineddata", "pillow_root": "python/site-packages",
            "files": [{"path": path, "sha256": H, "bytes": 1}
                      for path in ("python/python.exe", "engine/tesseract.exe",
                                   "engine/tessdata/eng.traineddata", "python/site-packages/PIL/__init__.py")],
            "code_sha256": {name: H for name in ("photo_ocr.py", "ocr_worker.py", "ocr_guard.py")},
            "catalog_sha256": ocr.CATALOG_SHA256, "engine_version": "5.5.3",
            "pillow_version": "12.0.0", "os_version": "unqualified-test-environment", "qualification": None}


def words(*tokens, confidence=96000):
    return [{"text": token, "bbox": [index * 10, 2, 9, 9],
             "confidence_milli": confidence, "line": [1, 1, 1]}
            for index, token in enumerate(tokens)]


def receipt(tokens=("P3767-0001",), *, cap=None, confidence=96000):
    cap = cap or capture()
    images = [{"photo_sha256": photo["sha256"], "bytes": photo["bytes"], "derived_sha256": H,
               "width": 1000, "height": 100, "transform": "identity-no-exif", "tsv_sha256": H,
               "words": words(*tokens, confidence=confidence), "elapsed_ms": 1, "peak_job_memory_bytes": 1000}
              for photo in cap["photos"]]
    return ocr._receipt(cap, H, ocr.engine_binding(config()), images, test_only=True)


class StrictParserTests(unittest.TestCase):
    def test_exact_tsv_word_and_confidence(self):
        raw = (HEADER + "5\t1\t1\t1\t1\t1\t1\t2\t10\t9\t96.063751\tP3767-0001\n").encode()
        self.assertEqual(ocr.parse_tsv(raw, 100, 50)[0],
                         {"text": "P3767-0001", "bbox": [1, 2, 10, 9],
                          "confidence_milli": 96063, "line": [1, 1, 1]})

    def test_empty_valid_tsv_is_no_identification(self):
        self.assertEqual(ocr.parse_tsv(HEADER.encode(), 10, 10), [])
        self.assertEqual(receipt(tokens=())["status"], "unresolved")

    def test_wrong_header_or_utf8_refused(self):
        for raw in (b"not tsv\n", HEADER.encode() + b"\xff"):
            with self.assertRaises(ocr.OcrError):
                ocr.parse_tsv(raw, 10, 10)

    def test_tsv_extra_column_refused(self):
        with self.assertRaises(ocr.OcrError):
            ocr.parse_tsv((HEADER + "5\t1\t1\t1\t1\t1\t1\t1\t1\t1\t99\tP3767-0001\textra\n").encode(), 10, 10)

    def test_nonfinite_and_out_of_range_confidence_refused(self):
        for confidence in ("NaN", "Infinity", "-1", "100.1", "True"):
            with self.assertRaises(ocr.OcrError):
                ocr.parse_tsv((HEADER + f"5\t1\t1\t1\t1\t1\t1\t1\t1\t1\t{confidence}\tP3767-0001\n").encode(), 10, 10)

    def test_cross_page_and_outside_box_refused(self):
        for row in ("5\t2\t1\t1\t1\t1\t1\t1\t1\t1\t99\tP3767-0001\n",
                    "5\t1\t1\t1\t1\t1\t9\t9\t9\t9\t99\tP3767-0001\n"):
            with self.assertRaises(ocr.OcrError):
                ocr.parse_tsv((HEADER + row).encode(), 10, 10)

    def test_duplicate_word_and_row_overflow_refused(self):
        row = "5\t1\t1\t1\t1\t1\t1\t1\t1\t1\t99\tP3767-0001\n"
        for raw in ((HEADER + row * 2).encode(), (HEADER + row * 1025).encode(), b"x" * (ocr.MAX_TSV + 1)):
            with self.assertRaises(ocr.OcrError):
                ocr.parse_tsv(raw, 10, 10)

    def test_control_token_and_layout_text_refused(self):
        for row in ("5\t1\t1\t1\t1\t1\t1\t1\t1\t1\t99\tP3\x7f767-0001\n",
                    "1\t1\t0\t0\t0\t0\t0\t0\t10\t10\t-1\tunexpected\n"):
            with self.assertRaises(ocr.OcrError):
                ocr.parse_tsv((HEADER + row).encode(), 10, 10)

    def test_geometry_limit_refused(self):
        with self.assertRaises(ocr.OcrError):
            ocr.parse_tsv(HEADER.encode(), 2001, 1000)


class ConservativeCatalogTests(unittest.TestCase):
    def test_exact_full_sku_binds_memory(self):
        value = receipt()
        match = value["matches"][0]
        self.assertEqual((match["subject"], match["memory_gb"]), ("module", 8))
        self.assertEqual(match["hardware_revision"], "unknown")

    def test_module_carrier_pair_does_not_infer_kit(self):
        value = receipt(("P3767-0001", "P3768-0000"))
        self.assertEqual({m["subject"] for m in value["matches"]}, {"module", "carrier"})
        self.assertEqual(value["status"], "candidate")

    def test_kit_requires_exact_kit_code(self):
        value = receipt(("945-13450-0000-100",))
        self.assertEqual(value["matches"][0]["subject"], "developer_kit")
        self.assertIsNone(value["matches"][0]["memory_gb"])

    def test_nano_module_does_not_guess_memory(self):
        self.assertIsNone(receipt(("P3448-0000",))["matches"][0]["memory_gb"])

    def test_partial_or_character_confused_codes_unresolved(self):
        for code in ("P3767", "P3767-OOOO", "P3767-000I", "p3767-0001", "699-13767-0001-000"):
            value = receipt((code,))
            self.assertEqual(value["status"], "unresolved")
            self.assertEqual(value["matches"], [])

    def test_conflicting_same_role_views_unresolved_as_conflicting(self):
        cap = capture([{"sha256": H, "bytes": 24, "media_type": "image/png"},
                       {"sha256": "b" * 64, "bytes": 25, "media_type": "image/jpeg"}])
        value = receipt(cap=cap)
        value["images"][1]["words"] = words("P3767-0000")
        value = ocr._receipt(cap, H, value["engine"], value["images"], test_only=True)
        self.assertEqual(value["status"], "conflicting")
        self.assertEqual(len(value["matches"]), 2)

    def test_known_plus_unknown_cannot_cherry_pick_confirmation(self):
        value = receipt(("P3767-0001", "P3767-0099"))
        self.assertEqual(value["status"], "unresolved")
        self.assertEqual(value["unresolved_count"], 1)

    def test_low_confidence_code_keeps_candidate_evidence_but_blocks_confirmation(self):
        value = receipt(confidence=1000)
        self.assertEqual(len(value["matches"]), 1)
        self.assertEqual(value["status"], "unresolved")

    def test_unknown_serial_words_stay_private(self):
        value = receipt(("P3767-0001", "PRIVATE_SERIAL_TEST_ONLY"))
        public = ocr.canonical_bytes(ocr.candidates(value))
        self.assertNotIn(b"PRIVATE_SERIAL_TEST_ONLY", public)
        self.assertIn("PRIVATE_SERIAL_TEST_ONLY", value["images"][0]["words"][1]["text"])


class ReceiptBindingTests(unittest.TestCase):
    def test_capture_duplicate_photos_and_bool_revision_refused(self):
        base = capture()
        for mutate in (lambda c: c.update(revision=True),
                       lambda c: c["photos"].append(copy.deepcopy(c["photos"][0]))):
            changed = copy.deepcopy(base)
            mutate(changed)
            with self.assertRaises(ocr.OcrError):
                ocr.validate_capture(changed)

    def test_all_views_required(self):
        value = receipt()
        value["images"] = []
        with self.assertRaises(ocr.OcrError):
            ocr.validate_receipt(value, capture())

    def test_cross_project_store_and_state_refused(self):
        for field, value in (("app_id", "ideaforge"), ("project_id", "other"),
                             ("root_binding", "b" * 64), ("state_sha256", "c" * 64),
                             ("review_sha256", "d" * 64), ("provider_selection_sha256", "e" * 64),
                             ("ai_config_sha256", "f" * 64)):
            expected = capture()
            expected[field] = value
            with self.assertRaises(ocr.OcrError):
                ocr.validate_receipt(receipt(), expected)

    def test_changed_revision_and_selection_refused(self):
        expected = capture()
        expected["revision"] = 2
        with self.assertRaises(ocr.OcrError):
            ocr.validate_receipt(receipt(), expected)
        with self.assertRaises(ocr.OcrError):
            ocr.validate_receipt(receipt(), capture(), "b" * 64)

    def test_tampered_catalog_candidate_or_confidence_refused(self):
        for mutate in (lambda v: v.update(catalog_sha256="b" * 64),
                       lambda v: v["matches"][0].update(memory_gb=16),
                       lambda v: v["images"][0]["words"][0].update(confidence_milli=1000)):
            value = receipt()
            mutate(value)
            with self.assertRaises(ocr.OcrError):
                ocr.validate_receipt(value, capture())

    def test_bool_integer_summary_and_metric_refused(self):
        for mutate in (lambda v: v.update(unresolved_count=False),
                       lambda v: v["matches"][0].update(word_index=False),
                       lambda v: v["metrics"].update(elapsed_ms=True)):
            value = receipt()
            mutate(value)
            with self.assertRaises(ocr.OcrError):
                ocr.validate_receipt(value, capture())

    def test_receipt_bool_byte_count_refused_even_when_equal_one(self):
        cap = capture([{"sha256": H, "bytes": 1, "media_type": "image/png"}])
        value = receipt(cap=cap)
        value["images"][0]["bytes"] = True
        with self.assertRaises(ocr.OcrError):
            ocr.validate_receipt(value, cap)

    def test_unknown_nested_word_field_refused(self):
        value = receipt()
        value["images"][0]["words"][0]["automatic_identity"] = True
        with self.assertRaises(ocr.OcrError):
            ocr.validate_receipt(value, capture())

    def test_engine_must_match_selected_config(self):
        value = receipt()
        value["engine"]["model_sha256"] = "b" * 64
        with self.assertRaises(ocr.OcrError):
            ocr.validate_receipt(value, capture(), expected_config=config())

    def test_receipt_hash_stable_and_test_only_explicit(self):
        value = receipt()
        self.assertTrue(value["test_only"])
        self.assertEqual(ocr.receipt_sha256(value), hashlib.sha256(ocr.receipt_bytes(value)).hexdigest())

    def test_word_geometry_and_group_word_bound_refused(self):
        for mutate in (lambda v: v["images"][0]["words"][0].update(bbox=[1000, 0, 1, 1]),
                       lambda v: v["images"][0].update(words=words(*(["x"] * 129)))):
            value = receipt()
            mutate(value)
            with self.assertRaises(ocr.OcrError):
                ocr.validate_receipt(value, capture())

    def test_duplicate_unknown_nonfinite_json_refused(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1.25}', b'{"x":"\xc2\x80"}'):
            with self.assertRaises(ocr.OcrError):
                ocr.decode_json(raw)
        value = receipt()
        value["extra"] = 1
        with self.assertRaises(ocr.OcrError):
            ocr.validate_receipt(value, capture())


class AdmissionTests(unittest.TestCase):
    def test_disabled_selection_never_scans_or_imports_guard(self):
        cfg = config()
        raw = ocr.canonical_bytes(cfg)
        with patch.object(ocr, "_runtime_files", side_effect=AssertionError("No scan allowed")):
            with self.assertRaises(ocr.OcrUnavailable):
                ocr.run_ocr(cfg, capture(), store_root=Path.cwd(),
                            selection_bytes=raw, selection_sha256=hashlib.sha256(raw).hexdigest())

    def test_enabled_but_unqualified_refuses_before_files(self):
        cfg = config(enabled=True)
        raw = ocr.canonical_bytes(cfg)
        with patch.object(ocr, "_runtime_files", side_effect=AssertionError("No scan allowed")):
            with self.assertRaises(ocr.OcrUnavailable):
                ocr.run_ocr(cfg, capture(), store_root=Path.cwd(),
                            selection_bytes=raw, selection_sha256=hashlib.sha256(raw).hexdigest())

    def test_raw_selection_formatting_change_is_stale(self):
        cfg = config()
        raw = ocr.canonical_bytes(cfg)
        changed = json.dumps(cfg, indent=2).encode("utf-8")
        self.assertEqual(ocr.load_config(changed), cfg)
        with self.assertRaises(ocr.OcrError):
            ocr.run_ocr(cfg, capture(), store_root=Path.cwd(),
                        selection_bytes=changed, selection_sha256=hashlib.sha256(raw).hexdigest())

    def test_cancelled_before_admission(self):
        event = threading.Event()
        event.set()
        cfg = config()
        raw = ocr.canonical_bytes(cfg)
        with self.assertRaisesRegex(ocr.OcrError, "was cancelled"):
            ocr.run_ocr(cfg, capture(), store_root=Path.cwd(), cancel=event,
                        selection_bytes=raw, selection_sha256=hashlib.sha256(raw).hexdigest())

    def test_invalid_cancellation_object_refused(self):
        cfg = config()
        raw = ocr.canonical_bytes(cfg)
        with self.assertRaisesRegex(ocr.OcrError, "Cancellation must use"):
            ocr.run_ocr(cfg, capture(), store_root=Path.cwd(), cancel=True,
                        selection_bytes=raw, selection_sha256=hashlib.sha256(raw).hexdigest())

    def test_config_rejects_paths_and_unknown_fields(self):
        for path in ("../python.exe", "/absolute", "x\\python.exe", "AUX.exe", "a/b:stream", "COM0.dll"):
            cfg = config()
            cfg["python"] = path
            with self.assertRaises(ocr.OcrError):
                ocr.validate_config(cfg)
        cfg = config()
        cfg["auto_download"] = True
        with self.assertRaises(ocr.OcrError):
            ocr.validate_config(cfg)

    def test_config_case_collision_and_pin_overflow_refused(self):
        cfg = config()
        cfg["files"].append({"path": "PYTHON/python.exe", "sha256": H, "bytes": 1})
        with self.assertRaises(ocr.OcrError):
            ocr.validate_config(cfg)
        cfg = config()
        cfg["files"] = cfg["files"] * (ocr.MAX_FILES + 1)
        with self.assertRaises(ocr.OcrError):
            ocr.validate_config(cfg)

    def test_streamed_hash_refuses_cancelled_and_oversized_file(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "pin.bin"
            path.write_bytes(b"pinned")
            self.assertEqual(ocr._hash_file(path, 6), hashlib.sha256(b"pinned").hexdigest())
            event = threading.Event()
            event.set()
            with self.assertRaises(ocr.OcrError):
                ocr._hash_file(path, 6, cancel=event)
            with self.assertRaises(ocr.OcrError):
                ocr._hash_file(path, 5)

    def test_actual_qualification_receipt_bytes_bind_claims(self):
        # These synthetic local records test structure/hash handling only, not OCR.
        with tempfile.TemporaryDirectory() as name:
            cfg = config()
            cfg["files"].append({"path": "python/site-packages/PIL/_imaging.test.pyd", "sha256": H, "bytes": 1})
            root = Path(name).absolute()
            qualification = {"format": "photo-ocr.qualification.v1",
                "runtime_sha256": ocr._digest(cfg["files"]), "code_sha256": cfg["code_sha256"],
                "catalog_sha256": cfg["catalog_sha256"], "engine_version": cfg["engine_version"],
                "pillow_version": cfg["pillow_version"], "os_version": cfg["os_version"],
                "receipt_root": str(root), "tests": []}
            observed = [cfg["python"], cfg["engine"], cfg["model"], cfg["files"][-1]["path"]]
            for index, test_id in enumerate(sorted(ocr.REQUIRED_TESTS)):
                row = {"format": "photo-ocr.qualification-test.v1", "id": test_id, "status": "passed",
                       **{k: qualification[k] for k in ("runtime_sha256", "code_sha256", "catalog_sha256",
                           "engine_version", "pillow_version", "os_version")},
                       "elapsed_ms": 1, "peak_job_memory_bytes": 1, "owned_job_empty": True,
                       "loaded_runtime_paths": observed, "test_only": False}
                raw = ocr.canonical_bytes(row)
                path = f"receipt-{index}.json"
                (root / path).write_bytes(raw)
                qualification["tests"].append({"id": test_id, "status": "passed",
                    "receipt_path": path, "receipt_sha256": hashlib.sha256(raw).hexdigest(), "receipt_bytes": len(raw)})
            cfg["qualification"] = qualification
            cfg = ocr.validate_config(cfg)
            with patch.object(ocr, "_runtime_files", side_effect=AssertionError("No runtime scan allowed")):
                pins = ocr._qualification_files(cfg)
            self.assertEqual(len(pins), len(ocr.REQUIRED_TESTS))
            # Tampered included record bytes cannot be excused by a declared pass.
            path = root / qualification["tests"][0]["receipt_path"]
            path.write_bytes(b"{}")
            with self.assertRaises(ocr.OcrError):
                ocr._qualification_files(cfg)

    def test_nonpassed_qualification_refuses_before_runtime_scan(self):
        cfg = config(enabled=True)
        cfg["qualification"] = {"format": "photo-ocr.qualification.v1",
            "runtime_sha256": ocr._digest(cfg["files"]), "code_sha256": cfg["code_sha256"],
            "catalog_sha256": cfg["catalog_sha256"], "engine_version": cfg["engine_version"],
            "pillow_version": cfg["pillow_version"], "os_version": cfg["os_version"],
            "receipt_root": "C:/no-evidence",
            "tests": [{"id": name, "status": "unrun", "receipt_path": f"receipt-{index}.json",
                       "receipt_sha256": H, "receipt_bytes": 1}
                      for index, name in enumerate(sorted(ocr.REQUIRED_TESTS))]}
        raw = ocr.canonical_bytes(cfg)
        with patch.object(ocr, "_runtime_files", side_effect=AssertionError("No runtime scan allowed")):
            with self.assertRaisesRegex(ocr.OcrUnavailable, "qualification is incomplete"):
                ocr.run_ocr(cfg, capture(), store_root=Path.cwd(),
                            selection_bytes=raw, selection_sha256=hashlib.sha256(raw).hexdigest())

    def test_streamed_hash_refuses_actual_hardlink(self):
        with tempfile.TemporaryDirectory() as name:
            path, other = Path(name) / "pin.bin", Path(name) / "other.bin"
            path.write_bytes(b"pin")
            try:
                os.link(path, other)
            except OSError as exc:
                self.skipTest("Filesystem hardlink support unavailable: " + type(exc).__name__)
            with self.assertRaises(ocr.OcrError):
                ocr._hash_file(path, 3)

    def test_exact_production_environment_is_admitted_without_native_init(self):
        from core.ocr_guard import _validate_spec
        environment = ocr._worker_environment("C:\\Windows", "C:\\private\\scratch")
        spec = _validate_spec(Path("C:\\runtime\\python.exe"),
            ["-I", "-S", "-B", "C:\\code\\ocr_worker.py", "C:\\private\\scratch\\request.json"],
            Path("C:\\private\\scratch"), environment,
            {"C:\\runtime\\python.exe": H, "C:\\code\\ocr_worker.py": H,
             "C:\\private\\scratch\\request.json": H})
        self.assertIn("TEMP=C:\\private\\scratch", spec.environment_block)
        self.assertNotIn("PYTHON", spec.environment_block)

    def test_no_native_import_on_worker_source_import(self):
        worker = Path(ocr.__file__).parent / "ocr_worker.py"
        spec = importlib.util.spec_from_file_location("inert_test_worker", worker)
        module = importlib.util.module_from_spec(spec)
        with patch("subprocess.Popen", side_effect=AssertionError("No native launch allowed")):
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))


# Fixture raster authoring uses only stdlib bytes. It never passes label text,
# filename, metadata, a whitelist or an expected-answer argument to Tesseract.
GLYPHS = {
    "P": ("11110","10001","10001","11110","10000","10000","10000"),
    "0": ("01110","10001","10011","10101","11001","10001","01110"),
    "1": ("00100","01100","00100","00100","00100","00100","01110"),
    "3": ("11110","00001","00001","01110","00001","00001","11110"),
    "4": ("00010","00110","01010","10010","11111","00010","00010"),
    "6": ("01110","10000","10000","11110","10001","10001","01110"),
    "7": ("11111","00001","00010","00100","01000","01000","01000"),
    "8": ("01110","10001","10001","01110","10001","10001","01110"),
    "9": ("01110","10001","10001","01111","00001","00001","01110"),
    "-": ("00000","00000","00000","11111","00000","00000","00000"),
}


def raster_png(label):
    scale, border = 8, 64
    width, height = border * 2 + len(label) * 6 * scale, border * 2 + 7 * scale
    pixels = bytearray(b"\xff" * (width * height * 3))
    for offset, char in enumerate(label):
        for row, values in enumerate(GLYPHS[char]):
            for col, bit in enumerate(values):
                if bit == "1":
                    for dy in range(scale):
                        start = ((border + row * scale + dy) * width + border + (offset * 6 + col) * scale) * 3
                        pixels[start:start + scale * 3] = b"\0" * (scale * 3)
    data = b"".join(b"\0" + pixels[row * width * 3:(row + 1) * width * 3] for row in range(height))
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(data)) + chunk(b"IEND", b"")


@unittest.skipUnless(os.environ.get("PHOTO_OCR_NATIVE_TESTS") == "1",
                     "UNRUN unless exact coordinated native fixture scope is authorized")
class NativePixelQualificationTests(unittest.TestCase):
    def _setup(self):
        from core.ocr_guard import run_guarded
        raw_cfg = ocr._read(Path(os.environ["PHOTO_OCR_QUALIFICATION_CONFIG"]).absolute(), ocr.MAX_JSON)
        cfg = ocr.load_config(raw_cfg)
        runtime = Path(cfg["runtime_root"])
        pins = ocr._runtime_files(cfg)
        code_dir = Path(ocr.__file__).absolute().parent
        for name, digest in cfg["code_sha256"].items():
            self.assertEqual(ocr._hash_file(code_dir / name, ocr.MAX_JSON), digest)
            pins[str(code_dir / name)] = digest
        return run_guarded, cfg, runtime, pins, code_dir

    def _image_output(self, image):
        run_guarded, cfg, runtime, pins, code_dir = self._setup()
        scratch = Path(tempfile.mkdtemp(prefix="ocr-pixel-fixture-")).absolute()
        completed = False
        try:
            input_path, request_path = scratch / "input.bin", scratch / "request.json"
            input_path.write_bytes(image)
            request = {"format": "photo-ocr.worker-request.v1",
                "input_sha256": hashlib.sha256(image).hexdigest(), "input_bytes": len(image), "media_type": "image/png",
                "engine": str(runtime / cfg["engine"]), "model": str(runtime / cfg["model"]),
                "pillow_root": str(runtime / cfg["pillow_root"]), "pillow_version": cfg["pillow_version"],
                "engine_sha256": next(x["sha256"] for x in cfg["files"] if x["path"] == cfg["engine"]),
                "model_sha256": next(x["sha256"] for x in cfg["files"] if x["path"] == cfg["model"])}
            request_path.write_bytes(ocr.canonical_bytes(request))
            localpins = {**pins, str(input_path): hashlib.sha256(image).hexdigest(),
                         str(request_path): hashlib.sha256(request_path.read_bytes()).hexdigest()}
            result = run_guarded(runtime / cfg["python"],
                ["-I", "-S", "-B", str(code_dir / "ocr_worker.py"), str(request_path)],
                cwd=scratch, environment=ocr._worker_environment(os.environ["SystemRoot"], scratch),
                timeout_seconds=5, stdout_limit=ocr.MAX_JSON, stderr_limit=16384,
                expected_sha256=localpins)
            completed = True  # Guard returned only after the owned Job became empty.
            self.assertLessEqual(result.peak_job_memory_bytes, 512 * 1048576)
            return result, ocr.decode_json(result.stdout) if result.exit_code == 0 else None
        finally:
            if completed:
                shutil.rmtree(scratch)
            # Failure retains scratch; never clean an unconfirmed process tree.

    @staticmethod
    def _summary(output, digest=H):
        return ocr._matching([{"photo_sha256": digest, "words": output["words"]}])

    def test_native_pixels_two_codes_without_answer_injection(self):
        # Expected is only raster pixels/assertion, never an engine argument or filename.
        for expected in ("P3767-0001", "P3449-0000"):
            result, output = self._image_output(raster_png(expected))
            self.assertEqual(result.exit_code, 0)
            self.assertIn(expected, [word["text"] for word in output["words"]])

    def test_native_blank_pixels_have_no_code(self):
        result, output = self._image_output(raster_png(""))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self._summary(output)["matches"], [])
        self.assertEqual(self._summary(output)["status"], "unresolved")

    def test_native_partial_marking_does_not_establish_sku(self):
        result, output = self._image_output(raster_png("P3767"))
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self._summary(output)["matches"], [])
        self.assertEqual(self._summary(output)["status"], "unresolved")

    def test_native_conflicting_views_remain_conflicting(self):
        images = []
        for index, label in enumerate(("P3767-0001", "P3767-0000")):
            result, output = self._image_output(raster_png(label))
            self.assertEqual(result.exit_code, 0)
            images.append({"photo_sha256": str(index + 1) * 64, "words": output["words"]})
        self.assertEqual(ocr._matching(images)["status"], "conflicting")

    def test_native_corrupt_png_refused_before_ocr_result(self):
        result, output = self._image_output(b"\x89PNG\r\n\x1a\nnot-a-decodable-container")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIsNone(output)


if __name__ == "__main__":
    unittest.main()
