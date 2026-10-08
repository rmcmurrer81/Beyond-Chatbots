"""Source-level acceptance tests. Execution status: UNRUN at publication.

Storage/search tests use a clearly labeled fake extraction report. Native backend
tests require exactly pypdfium2 5.14.0 and exercise real generated PDF bytes.
"""
import copy
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from core import pdf_evidence as pdf
from pdf_fixtures import ALPHA, BETA, native_pdf, scanned_pdf, write_fixtures


def _backend_available():
    try:
        return version("pypdfium2") == pdf.BACKEND_VERSION
    except PackageNotFoundError:
        return False


def report_for(raw, rows=ALPHA):
    """Fake storage fixture; this does not test PDFium extraction."""
    pages = []
    for offset in range(0, len(rows), 5):
        passages = []
        for index, (anchor, value) in enumerate(rows[offset:offset + 5]):
            y = 700 - index * 60
            passages.append({"object_index": index, "text": anchor + " " + value + ".",
                             "bbox": [50.0, float(y - 2), 400.0, float(y + 12)]})
        pages.append({"page": len(pages) + 1, "rotation": 0,
                      "bbox": [0.0, 0.0, 612.0, 792.0], "passages": passages,
                      "native_text_status": "native_text_present"})
    return {"schema": pdf.SCHEMA, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "backend": {"package": "pypdfium2", "version": "5.14.0",
                        "pdfium_version": "synthetic-storage-fixture-not-a-native-run"},
            "pages": pages}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.a = self.project("10000001")
        self.b = self.project("10000002")
        self.source = self.base / "manual.pdf"
        self.raw, self.truth = native_pdf(ALPHA)
        self.source.write_bytes(self.raw)

    def project(self, identity):
        root = self.base / identity
        root.mkdir()
        (root / "project.json").write_text(json.dumps(
            {"project_id": identity, "name": "Same project title", "plan": {}}))
        return root

    def ingest(self, root=None, rows=ALPHA, source_id=None, **kwargs):
        raw = self.source.read_bytes()
        with patch.object(pdf, "_run_worker", return_value=report_for(raw, rows)):
            return pdf.ingest_pdf(root or self.a, self.source, source_id=source_id, **kwargs)

    def test_twenty_local_question_cases_and_exact_strings(self):
        self.ingest()
        beta, truth = native_pdf(BETA)
        self.source.write_bytes(beta)
        self.ingest(self.b, BETA)
        for root, rows in ((self.a, ALPHA), (self.b, BETA)):
            for anchor, value in rows:
                with self.subTest(project=root.name, anchor=anchor):
                    hits = pdf.retrieve_pdf(root, f"What does {anchor} state?", limit=1)
                    self.assertEqual(hits[0]["passage"], anchor + " " + value + ".")
                    self.assertEqual(hits[0]["project_id"], root.name)
                    self.assertEqual(pdf.resolve_pdf_citation(root, hits[0]["citation"]), hits[0])
                    self.assertIn("CAD dimension validation", hits[0]["notice"])
                    self.assertNotIn("validated_dimension", hits[0])

    def test_restart_resolves_preserved_exact_bytes_and_boxes(self):
        result = self.ingest()
        row = pdf.retrieve_pdf(self.a, "ALPHA03", limit=1)[0]
        snapshot = self.a / "research/pdf_evidence/sources" / (result["source_sha256"] + ".pdf")
        self.assertEqual(snapshot.read_bytes(), self.raw)
        code = ("import json;from core.pdf_evidence import retrieve_pdf,resolve_pdf_citation;"
                f"r=retrieve_pdf({str(self.a)!r},'ALPHA03',limit=1)[0];"
                f"print(json.dumps(resolve_pdf_citation({str(self.a)!r},r['citation'])))")
        restarted = json.loads(subprocess.check_output(
            [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], text=True))
        self.assertEqual(restarted, row)
        self.assertEqual(row["bbox"], [50.0, 578.0, 400.0, 592.0])

    def test_replacement_preserves_history_and_removes_old_active_hits(self):
        first = self.ingest()
        old = pdf.retrieve_pdf(self.a, "ALPHA01", limit=1)[0]
        self.source.write_bytes(native_pdf(BETA)[0])
        second = self.ingest(rows=BETA, source_id=first["source_id"])
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])
        self.assertEqual(pdf.retrieve_pdf(self.a, "ALPHA01"), [])
        new = pdf.retrieve_pdf(self.a, "BETA01", limit=1)[0]
        self.assertTrue(new["active"])
        retained = pdf.resolve_pdf_citation(self.a, old["citation"])
        self.assertFalse(retained["active"])
        self.assertEqual(retained["passage"], old["passage"])
        self.assertEqual(retained["source_sha256"], first["source_sha256"])

    def test_project_isolation_identical_names_and_copied_store(self):
        self.ingest()
        citation = pdf.retrieve_pdf(self.a, "ALPHA01", limit=1)[0]["citation"]
        self.assertIsNone(pdf.resolve_pdf_citation(self.b, citation))
        self.assertEqual(pdf.retrieve_pdf(self.b, "ALPHA01"), [])
        shutil.copytree(self.a / "research", self.b / "research")
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf.retrieve_pdf(self.b, "ALPHA01")
        # Same numeric ID copied to another folder must also fail root binding.
        (self.b / "project.json").write_text((self.a / "project.json").read_text())
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf.retrieve_pdf(self.b, "ALPHA01")

    def test_private_pdf_absent_from_existing_provider_context(self):
        self.ingest()
        from core import chat_context
        with patch.object(chat_context, "load_all", return_value={"items": []}):
            ordinary = chat_context.build_context(self.a, "ALPHA01 bolt length")
        self.assertNotIn("ALPHA01", ordinary)
        self.assertNotIn("12.5 mm", ordinary)
        self.assertNotIn("IF-PDF-", ordinary)
        self.assertNotIn("manual.pdf", ordinary)

    def test_failed_replacement_keeps_manifest_exact(self):
        first = self.ingest()
        manifest = self.a / "research/pdf_evidence/manifest.json"
        before = manifest.read_bytes()
        self.source.write_bytes(native_pdf(BETA)[0])
        with patch.object(pdf, "_run_worker", side_effect=pdf.PDFEvidenceError("unsupported")):
            with self.assertRaises(pdf.PDFEvidenceError):
                pdf.ingest_pdf(self.a, self.source, source_id=first["source_id"])
        self.assertEqual(manifest.read_bytes(), before)
        self.assertTrue(pdf.retrieve_pdf(self.a, "ALPHA01"))

    def test_snapshot_record_and_citation_tampering_fail_closed(self):
        result = self.ingest()
        store = self.a / "research/pdf_evidence"
        source = store / "sources" / (result["source_sha256"] + ".pdf")
        source.write_bytes(b"%PDF-replaced")
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf.retrieve_pdf(self.a, "ALPHA01")
        source.write_bytes(self.raw)
        record = store / "versions" / (result["version_id"] + ".json")
        old = record.read_bytes()
        record.write_bytes(old + b" ")
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf.retrieve_pdf(self.a, "ALPHA01")
        record.write_bytes(old)
        value = json.loads(old)
        value["report"]["pages"][0]["passages"][0]["citation"] = "IF-PDF-" + "0" * 32
        changed = json.dumps(value).encode()
        record.write_bytes(changed)
        manifest = json.loads((store / "manifest.json").read_bytes())
        manifest["versions"][0]["record_sha256"] = hashlib.sha256(changed).hexdigest()
        (store / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf.retrieve_pdf(self.a, "ALPHA01")

    def test_file_page_object_character_and_storage_limits(self):
        with self.assertRaises(pdf.PDFEvidenceError):
            self.ingest(limits=pdf.Limits(file_bytes=10))
        for limits in (pdf.Limits(pages=1), pdf.Limits(objects_per_page=1),
                       pdf.Limits(object_chars=4), pdf.Limits(total_chars=5),
                       pdf.Limits(result_bytes=10)):
            with self.subTest(limits=limits), self.assertRaises(pdf.PDFEvidenceError):
                self.ingest(limits=limits)
        with patch.object(pdf, "MAX_STORAGE_BYTES", 10):
            with self.assertRaises(pdf.PDFEvidenceError):
                self.ingest()
        for invalid in (pdf.Limits(seconds=float("nan")), pdf.Limits(pages=True),
                        pdf.Limits(file_bytes=8_000_001), pdf.Limits(seconds=31)):
            with self.assertRaises(pdf.PDFEvidenceError):
                self.ingest(limits=invalid)

    def test_enormous_python_integers_fail_without_overflow(self):
        huge = 10 ** 400
        for limits in (pdf.Limits(file_bytes=huge), pdf.Limits(seconds=huge)):
            with self.assertRaises(pdf.PDFEvidenceError):
                self.ingest(limits=limits)
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf._box([0, 0, huge, 1])
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf.retrieve_pdf(self.a, "ALPHA01", seconds=huge)
        from core import pdf_worker
        output = self.base / "worker-output.json"
        values = vars(pdf.Limits()).copy()
        values["file_bytes"] = huge
        with patch.object(pdf_worker, "extract") as extractor:
            self.assertEqual(pdf_worker.main(
                [str(self.source), str(output), json.dumps(values)]), 2)
        extractor.assert_not_called()
        self.assertEqual(json.loads(output.read_text())["error"], "invalid_limits")

    def test_orphan_entry_caps_deadlines_and_interrupted_staging(self):
        store = self.a / "research/pdf_evidence"
        sources = store / "sources"
        sources.mkdir(parents=True)
        for i in range(3):
            (sources / (f"{i:064x}" + ".pdf")).write_bytes(b"")
        with patch.object(pdf, "MAX_STORE_SOURCE_FILES", 3):
            with self.assertRaises(pdf.PDFEvidenceError):
                self.ingest()
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf._storage_bytes(store, -1)
        (store / ".extract-interrupted").mkdir()
        with self.assertRaises(pdf.PDFEvidenceError):
            self.ingest()
        self.assertFalse((store / "manifest.json").exists())

    def test_directory_scan_streams_and_stops_at_cap_plus_one(self):
        store = self.a / "research/pdf_evidence"
        sources = store / "sources"
        sources.mkdir(parents=True)
        for number in range(2):
            (sources / (f"{number:064x}" + ".pdf")).write_bytes(b"")
        consumed = []
        class Entries:
            def __init__(self, iterator):
                self.iterator = iter(iterator)
            def __enter__(self):
                return self
            def __exit__(self, *arguments):
                return False
            def __iter__(self):
                return self
            def __next__(self):
                return next(self.iterator)
        def orphan_entries():
            number = 0
            while True:
                consumed.append(number)
                if len(consumed) > 3:
                    raise AssertionError("directory iterator consumed beyond cap + 1")
                yield Mock(path=str(sources / (f"{number:064x}" + ".pdf")))
                number += 1
        def scandir(path):
            if Path(path) == store:
                return Entries([Mock(path=str(sources))])
            self.assertEqual(Path(path), sources)
            return Entries(orphan_entries())
        with patch.object(pdf.os, "scandir", side_effect=scandir), \
             patch.object(pdf, "MAX_STORE_SOURCE_FILES", 2):
            with self.assertRaisesRegex(pdf.PDFEvidenceError, "entry budget"):
                pdf._storage_bytes(store, pdf.time.monotonic() + 2)
        self.assertEqual(len(consumed), 3)

    def test_version_and_source_limits(self):
        first = self.ingest()
        with patch.object(pdf, "MAX_ACTIVE_SOURCES", 1):
            with self.assertRaises(pdf.PDFEvidenceError):
                self.ingest()
            self.ingest(source_id=first["source_id"])
        with patch.object(pdf, "MAX_VERSIONS", 2):
            with self.assertRaises(pdf.PDFEvidenceError):
                self.ingest(source_id=first["source_id"])

    def test_empty_clipped_invalid_bbox_and_backend_reports(self):
        baseline = report_for(self.raw)
        variants = []
        empty = copy.deepcopy(baseline)
        for page in empty["pages"]:
            page["passages"] = []
            page["native_text_status"] = "no_extractable_native_text_unsupported_image_or_blank"
        variants.append(empty)
        wrong_hash = copy.deepcopy(baseline)
        wrong_hash["source_sha256"] = "0" * 64
        variants.append(wrong_hash)
        wrong_version = copy.deepcopy(baseline)
        wrong_version["backend"]["version"] = "5.13.0"
        variants.append(wrong_version)
        for bbox in ([50, 700, 900, 710], [0, 0, float("nan"), 2], [3, 3, 1, 1]):
            altered = copy.deepcopy(baseline)
            altered["pages"][0]["passages"][0]["bbox"] = bbox
            variants.append(altered)
        for report in variants:
            with self.subTest(report=report), patch.object(pdf, "_run_worker", return_value=report):
                with self.assertRaises(pdf.PDFEvidenceError):
                    pdf.ingest_pdf(self.a, self.source)

    def test_invalid_native_unicode_and_project_metadata_symlink(self):
        report = report_for(self.raw)
        report["pages"][0]["passages"][0]["text"] = "bad\ud800"
        with patch.object(pdf, "_run_worker", return_value=report):
            with self.assertRaises(UnicodeError):
                pdf.ingest_pdf(self.a, self.source)
        project_file = self.a / "project.json"
        project_file.unlink()
        try:
            project_file.symlink_to(self.b / "project.json")
        except OSError:
            self.skipTest("symlink creation unavailable on this host")
        with self.assertRaises(pdf.PDFEvidenceError):
            pdf.retrieve_pdf(self.a, "ALPHA01")

    def test_preserves_native_whitespace_and_table_notice(self):
        report = report_for(self.raw)
        exact = "ALPHA01  row 12.50\r\ncolumn  7.00\tunits"
        report["pages"][0]["passages"][0]["text"] = exact
        with patch.object(pdf, "_run_worker", return_value=report):
            pdf.ingest_pdf(self.a, self.source)
        row = pdf.retrieve_pdf(self.a, "ALPHA01", limit=1)[0]
        self.assertEqual(row["passage"], exact)
        self.assertIn("table relationships", row["notice"])
        self.assertNotIn("table_row", row)

    def test_query_limits_and_literal_injection(self):
        self.ingest()
        self.assertEqual(pdf.retrieve_pdf(self.a, ""), [])
        self.assertIsNone(pdf.resolve_pdf_citation(self.a, "not-a-citation"))
        for query in ("ALPHA01 ' OR * DROP TABLE", "ALPHA01 NEAR(ignored)"):
            self.assertEqual(pdf.retrieve_pdf(self.a, query, limit=1)[0]["project_id"], "10000001")
        for kwargs in ({"limit": -1}, {"limit": 7}, {"seconds": 0},
                       {"seconds": float("inf")}):
            with self.assertRaises(pdf.PDFEvidenceError):
                pdf.retrieve_pdf(self.a, "ALPHA01", **kwargs)

    def test_import_lock_and_elapsed_deadline(self):
        store = self.a / "research/pdf_evidence"
        store.mkdir(parents=True)
        (store / ".import-lock").mkdir()
        with self.assertRaises(pdf.PDFEvidenceError):
            self.ingest()
        (store / ".import-lock").rmdir()
        with patch.object(pdf, "_check_deadline", side_effect=pdf.PDFEvidenceError("deadline")):
            with self.assertRaises(pdf.PDFEvidenceError):
                self.ingest()
        self.assertFalse((store / "manifest.json").exists())

    def test_hard_deadline_kills_only_owned_worker(self):
        owned = Mock()
        owned.wait.side_effect = [subprocess.TimeoutExpired("worker", 1), 0]
        with patch.object(pdf.subprocess, "Popen", return_value=owned) as launcher:
            with self.assertRaises(pdf.PDFEvidenceError):
                pdf._run_worker(self.source, self.base / "result.json", pdf.Limits(), .001)
        owned.kill.assert_called_once_with()
        self.assertEqual(launcher.call_count, 1)
        command = launcher.call_args.args[0]
        self.assertEqual(command[:2], [sys.executable, "-I"])
        self.assertTrue(command[2].endswith("pdf_worker.py"))

    def test_retrieval_does_not_return_success_after_budget_expires(self):
        self.ingest()
        row = pdf.retrieve_pdf(self.a, "ALPHA01", limit=1)[0]
        with patch.object(pdf, "_records", return_value=iter([row])), \
             patch.object(pdf.time, "monotonic", side_effect=[0, 0, 10]):
            with self.assertRaises(pdf.PDFEvidenceError):
                pdf.retrieve_pdf(self.a, "ALPHA01", seconds=1)

    def test_atomic_manifest_temp_cleaned_on_fsync_error(self):
        target = self.base / "manifest.json"
        with patch.object(pdf.os, "fsync", side_effect=OSError("fsync failed")):
            with self.assertRaises(OSError):
                pdf._atomic(target, b"{}")
        self.assertEqual(list(self.base.glob(".manifest-*")), [])
        self.assertFalse(target.exists())

    def test_blank_page_support_is_explicit(self):
        report = report_for(self.raw)
        report["pages"][1]["passages"] = []
        report["pages"][1]["native_text_status"] = "no_extractable_native_text_unsupported_image_or_blank"
        with patch.object(pdf, "_run_worker", return_value=report):
            receipt = pdf.ingest_pdf(self.a, self.source)
        self.assertEqual(receipt["page_support"][1]["status"],
                         "no_extractable_native_text_unsupported_image_or_blank")

    def test_cli_retrieval_is_fresh_process_and_offline(self):
        self.ingest()
        result = subprocess.check_output(
            [sys.executable, "-m", "core.pdf_evidence", "--project", str(self.a),
             "retrieve", "ALPHA04"], cwd=Path(__file__).resolve().parents[1], text=True)
        result = json.loads(result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"][0]["passage"], "ALPHA04 mass 0.075 kg.")


@unittest.skipUnless(_backend_available(), "optional pinned pypdfium2 5.14.0 unavailable")
class NativeBackendTests(unittest.TestCase):
    setUp = StoreTests.setUp
    project = StoreTests.project
    def test_real_two_annotated_pdfs_twenty_questions(self):
        fixtures, scanned = write_fixtures(self.base / "fixtures")
        for root, (source, truth) in zip((self.a, self.b), fixtures):
            receipt = pdf.ingest_pdf(root, source)
            self.assertEqual(receipt["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            for item in truth:
                with self.subTest(question=item["question"]):
                    row = pdf.retrieve_pdf(root, item["question"], limit=1)[0]
                    self.assertEqual(row["passage"], item["expected"])
                    self.assertEqual(row["page"], item["page"])
                    self.assertEqual(row["object_index"], item["object_index"])
                    box, envelope = row["bbox"], item["envelope"]
                    self.assertGreaterEqual(box[0], envelope[0])
                    self.assertGreaterEqual(box[1], envelope[1])
                    self.assertLessEqual(box[2], envelope[2])
                    self.assertLessEqual(box[3], envelope[3])
                    self.assertEqual(pdf.resolve_pdf_citation(root, row["citation"]), row)
                    self.assertIsNone(pdf.resolve_pdf_citation(
                        self.b if root == self.a else self.a, row["citation"]))

    def test_real_scanned_negative_rotation_crop_and_form_refusals(self):
        cases = [
            (scanned_pdf(), "no_native_text"),
            (native_pdf(ALPHA, rotation=90)[0], "rotated_page"),
            (native_pdf(ALPHA, crop=[0, 0, 500, 792])[0], "crop_or_page_origin"),
            (native_pdf(ALPHA, form=True)[0], "form_xobject"),
        ]
        for raw, expected in cases:
            with self.subTest(expected=expected):
                self.source.write_bytes(raw)
                with self.assertRaisesRegex(pdf.PDFEvidenceError, expected):
                    pdf.ingest_pdf(self.a, self.source)
                self.assertEqual(pdf.retrieve_pdf(self.a, "ALPHA01"), [])

    def test_real_page_limit_refusal(self):
        with self.assertRaisesRegex(pdf.PDFEvidenceError, "page_limit"):
            pdf.ingest_pdf(self.a, self.source, limits=pdf.Limits(pages=1))


if __name__ == "__main__":
    unittest.main()
