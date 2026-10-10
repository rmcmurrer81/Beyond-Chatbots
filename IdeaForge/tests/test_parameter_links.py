"""Focused local annotation tests; no native PDF engine or network calls.

PDF import uses an explicitly synthetic storage report, not an extraction proof.
All execution remains UNRUN until an actual runner receipt is recorded.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import pdf_evidence as pdf
from workspace3d.checks import run_checks
from workspace3d.model import demo, digest
from workspace3d.store import Store
from workspace3d.parameter_links import (
    ParameterLinks, LinkError, SCHEMA, RECEIPT_SCHEMA, strict_json)


REVIEW = {"confirmed": True, "reviewer": "Synthetic test reviewer",
          "reviewed_at": "2026-10-08T22:30:00Z",
          "rationale": "Synthetic self-authored numeric source claim reviewed for this parameter."}


class ParameterLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.project("10000001")
        self.other = self.project("10000002")
        self.scene = demo()
        self.store = Store(self.root)
        self.revision = self.store.add(self.scene, "synthetic scene", [], run_checks(self.scene),
                                       expected_parent=None)
        self.source = self.base / "self-authored-manual.pdf"
        self.ingested = self.import_source("Reviewed base dimension 120 mm.", b"%PDF- synthetic source A")
        self.row = pdf.retrieve_pdf(self.root, "Reviewed base dimension")[0]
        self.ledger = ParameterLinks(self.root)

    def project(self, identity):
        root = self.base / identity
        root.mkdir()
        (root / "project.json").write_text(json.dumps({"project_id": identity}),
                                           encoding="utf-8")
        return root

    def import_source(self, text, raw, source_id=None):
        self.source.write_bytes(raw)
        report = {"schema": pdf.SCHEMA, "source_sha256": hashlib.sha256(raw).hexdigest(),
                  "backend": {"package": "pypdfium2", "version": "5.14.0",
                              "pdfium_version": "synthetic-storage-fixture-not-native"},
                  "pages": [{"page": 1, "rotation": 0, "bbox": [0., 0., 612., 792.],
                             "native_text_status": "native_text_present",
                             "passages": [{"object_index": 0, "text": text,
                                           "bbox": [50., 690., 450., 710.]}]}]}
        with patch.object(pdf, "_run_worker", return_value=report):
            return pdf.ingest_pdf(self.root, self.source, source_id=source_id)

    def request(self, row=None, revision=None, scene=None):
        row = row or self.row
        scene = scene or self.scene
        source = {key: copy.deepcopy(row[key]) for key in
                  ("project_id", "source_id", "version_id", "citation", "source_sha256",
                   "page", "bbox", "object_index", "passage", "coordinate_system")}
        return {"schema": SCHEMA, "project_id": self.root.name,
                "revision": revision or self.revision, "scene_hash": digest(scene),
                "parameter": {"part_id": "base", "field": "size_mm", "index": 0},
                "source": source, "selection": {"start": row["passage"].index("120 mm"),
                    "quote": "120 mm", "numeric_text": "120", "unit": "mm"},
                "review": copy.deepcopy(REVIEW)}

    def create(self):
        return self.ledger.create(self.request())

    def receipt(self, link_id, *, status="unrun"):
        item = self.ledger.inspect(link_id)
        return {"schema": RECEIPT_SCHEMA, "id": "synthetic-parameter-check",
                "project_id": self.root.name, "revision": self.revision,
                "scene_hash": digest(self.scene),
                "source_sha256": self.row["source_sha256"],
                "link_sha256": item["record_sha256"], "status": status,
                "command": "Synthetic receipt fixture; no test execution claimed.",
                "observations": "Authored test has not been executed.",
                "run_at": None if status == "unrun" else "2026-10-08T22:31:00Z",
                "review": copy.deepcopy(REVIEW)}

    def test_known_link_exact_quote_box_revision_and_no_scene_mutation(self):
        before = self.store.revision(self.revision)
        history = self.store.history()
        result = self.create()
        item = self.ledger.inspect(result["link_id"])
        self.assertEqual(item["status"], "current")
        self.assertEqual(item["record"]["source"]["bbox"], self.row["bbox"])
        self.assertEqual(item["record"]["source"]["passage"], self.row["passage"])
        self.assertEqual(item["record"]["selection"]["quote"], "120 mm")
        self.assertEqual(item["record"]["revision"], self.revision)
        self.assertEqual(self.store.revision(self.revision), before)
        self.assertEqual(self.store.history(), history)
        self.assertEqual(self.store.pointer(), self.revision)
        self.assertIsNone(self.store.pointer("accepted"))
        self.assertIn("not dimensional certification", item["notice"])

    def test_review_must_be_explicit_and_dated(self):
        for mutate in (lambda r: r["review"].update(confirmed=False),
                       lambda r: r["review"].update(confirmed=1),
                       lambda r: r["review"].update(reviewer=""),
                       lambda r: r["review"].update(rationale=""),
                       lambda r: r["review"].update(reviewed_at="2026-10-08T22:30:00"),
                       lambda r: r["review"].update(reviewed_at="2026-10-08T22:30:00+01:00")):
            request = self.request()
            mutate(request)
            with self.subTest(request=request["review"]), self.assertRaises(LinkError):
                self.ledger.create(request)

    def test_unit_mismatch_requires_manual_conversion_outside_link(self):
        request = self.request()
        request["selection"]["unit"] = "cm"
        with self.assertRaisesRegex(LinkError, "unit"):
            self.ledger.create(request)

    def test_numeric_mismatch_and_wrong_occurrence_rejected(self):
        for selection in (
                {"start": self.row["passage"].index("120 mm")+1, "quote": "20 mm",
                 "numeric_text": "20", "unit": "mm"},
                {"start": 0, "quote": "120 mm", "numeric_text": "120", "unit": "mm"},
                {"start": self.row["passage"].index("120 mm"), "quote": "120 mm",
                 "numeric_text": "12", "unit": "mm"}):
            request = self.request()
            request["selection"] = selection
            with self.subTest(selection=selection), self.assertRaises(LinkError):
                self.ledger.create(request)

    def test_numeric_substring_boundary_even_if_parameter_matches(self):
        scene = demo()
        scene["parts"][0]["size_mm"][0] = 20
        revision = self.store.add(scene, "manual 20", [], run_checks(scene),
                                  expected_parent=self.revision)
        request = self.request(revision=revision, scene=scene)
        request["selection"] = {"start": self.row["passage"].index("120 mm")+1,
                                "quote": "20 mm", "numeric_text": "20", "unit": "mm"}
        with self.assertRaisesRegex(LinkError, "boundaries"):
            self.ledger.create(request)

    def test_angular_parameter_and_exact_unit_supported(self):
        self.import_source("Reviewed rotation 0 deg.", b"%PDF- synthetic angle",
                           source_id=self.ingested["source_id"])
        row = pdf.retrieve_pdf(self.root, "rotation")[0]
        request = self.request()
        request["source"] = {k: row[k] for k in request["source"]}
        request["parameter"] = {"part_id": "base", "field": "rotation_deg", "index": 2}
        request["selection"] = {"start": row["passage"].index("0 deg"), "quote": "0 deg",
                                "numeric_text": "0", "unit": "deg"}
        self.assertEqual(self.ledger.inspect(self.ledger.create(request)["link_id"])["status"], "current")

    def test_exact_source_metadata_and_types_rejected(self):
        for mutate in (lambda r: r["source"].update(source_sha256="0"*64),
                       lambda r: r["source"].update(page=2),
                       lambda r: r["source"].update(page=True),
                       lambda r: r["source"].update(object_index=False),
                       lambda r: r["source"]["bbox"].__setitem__(0, 51.),
                       lambda r: r["source"].update(passage="Edited 120 mm."),
                       lambda r: r["source"].update(version_id="0"*32)):
            request = self.request()
            mutate(request)
            with self.subTest(source=request["source"]), self.assertRaises(LinkError):
                self.ledger.create(request)

    def test_unknown_parameter_and_vector_index_rejected(self):
        for parameter in ({"part_id": "missing", "field": "size_mm", "index": 0},
                          {"part_id": "base", "field": "mass_kg", "index": None},
                          {"part_id": "base", "field": "size_mm", "index": True},
                          {"part_id": "base", "field": "joint.angle_deg", "index": None}):
            request = self.request()
            request["parameter"] = parameter
            with self.subTest(parameter=parameter), self.assertRaises(LinkError):
                self.ledger.create(request)

    def test_other_project_cannot_resolve_or_create_link(self):
        store = Store(self.other)
        store.add(self.scene, "other project", [], run_checks(self.scene), expected_parent=None)
        ledger = ParameterLinks(self.other)
        with self.assertRaises(LinkError):
            ledger.create(self.request())
        self.assertIsNone(pdf.resolve_pdf_citation(self.other, self.row["citation"]))

    def test_copied_ledger_refuses_new_project_or_same_id_other_root(self):
        self.create()
        store = Store(self.other)
        store.add(self.scene, "other scene", [], run_checks(self.scene), expected_parent=None)
        copied = self.other / "workspace3d/parameter_links.sqlite3"
        shutil.copyfile(self.ledger.path, copied)
        with self.assertRaisesRegex(LinkError, "different project"):
            ParameterLinks(self.other)
        (self.other / "project.json").write_text((self.root / "project.json").read_text())
        with self.assertRaisesRegex(LinkError, "different project"):
            ParameterLinks(self.other)

    def test_source_replacement_stales_link_and_receipt_keeps_original_quote(self):
        result = self.create()
        receipt = self.receipt(result["link_id"])
        self.ledger.attach_test_receipt(result["link_id"], receipt)
        original = self.ledger.inspect(result["link_id"])["record"]
        self.import_source("Reviewed base dimension 140 mm.", b"%PDF- synthetic source B",
                           source_id=self.ingested["source_id"])
        item = self.ledger.inspect(result["link_id"])
        self.assertEqual(item["status"], "stale")
        self.assertIn("source_version_replaced", item["reasons"])
        self.assertEqual(item["record"], original)
        self.assertEqual(item["tests"][0]["evidence_status"], "stale")
        self.assertEqual(item["tests"][0]["receipt"]["status"], "unrun")
        self.assertEqual(self.store.revision()["scene"], self.scene)

    def test_reimport_same_bytes_new_version_still_stale(self):
        result = self.create()
        second = self.import_source(self.row["passage"], b"%PDF- synthetic source A",
                                    source_id=self.ingested["source_id"])
        self.assertEqual(second["source_sha256"], self.ingested["source_sha256"])
        self.assertNotEqual(second["version_id"], self.ingested["version_id"])
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "stale")

    def test_changed_scene_revision_stales_link_and_receipt(self):
        result = self.create()
        self.ledger.attach_test_receipt(result["link_id"], self.receipt(result["link_id"]))
        scene = demo()
        scene["parts"][0]["size_mm"][0] = 130
        revision = self.store.add(scene, "manual edit", [], run_checks(scene),
                                  expected_parent=self.revision)
        item = self.ledger.inspect(result["link_id"])
        self.assertEqual(item["status"], "stale")
        self.assertIn("design_revision_changed", item["reasons"])
        self.assertEqual(item["tests"][0]["evidence_status"], "stale")
        self.assertEqual(self.store.pointer(), revision)
        self.assertEqual(self.store.revision()["scene"], scene)

    def test_restore_creates_new_revision_does_not_reactivate_old_link(self):
        result = self.create()
        scene = demo()
        scene["parts"][0]["size_mm"][0] = 130
        middle = self.store.add(scene, "edit", [], run_checks(scene), expected_parent=self.revision)
        restored = self.store.add(self.scene, "restore", [], run_checks(self.scene), expected_parent=middle)
        self.assertNotEqual(restored, self.revision)
        self.assertEqual(digest(self.store.revision(restored)["scene"]), digest(self.scene))
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "stale")

    def test_old_revision_cannot_be_reviewed_as_current(self):
        scene = demo()
        scene["parts"][0]["position_mm"][0] = 1
        self.store.add(scene, "new revision", [], run_checks(scene), expected_parent=self.revision)
        with self.assertRaisesRegex(LinkError, "current design"):
            self.create()

    def test_missing_pdf_snapshot_or_extraction_record_is_unknown(self):
        result = self.create()
        snapshot = self.root / "research/pdf_evidence/sources" / (self.row["source_sha256"]+".pdf")
        snapshot.unlink()
        item = self.ledger.inspect(result["link_id"])
        self.assertEqual(item["status"], "unknown")
        self.assertIn("source_evidence_missing_or_invalid", item["reasons"])
        with self.assertRaises(pdf.PDFEvidenceError):
            self.create()

    def test_missing_design_revision_is_unknown(self):
        result = self.create()
        with self.store.connection() as db:
            db.execute("DELETE FROM revisions WHERE id=?", (self.revision,))
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "unknown")

    def test_restart_and_real_child_process_resolve_same_annotation(self):
        result = self.create()
        before = self.ledger.inspect(result["link_id"])
        self.assertEqual(ParameterLinks(self.root).inspect(result["link_id"]), before)
        code = ("import json;from workspace3d.parameter_links import ParameterLinks;"
                f"print(json.dumps(ParameterLinks({str(self.root)!r}).inspect({result['link_id']!r})))")
        restarted = json.loads(subprocess.check_output(
            [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
            text=True, timeout=5))
        self.assertEqual(restarted, before)

    def test_undo_create_and_withdraw_reversible_without_cad_write(self):
        result = self.create()
        undo = self.ledger.undo(result["event_id"], REVIEW)
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "withdrawn")
        self.ledger.undo(undo, REVIEW)
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "current")
        withdraw = self.ledger.withdraw(result["link_id"], REVIEW)
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "withdrawn")
        self.ledger.undo(withdraw, REVIEW)
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "current")
        self.assertEqual(len(self.store.history()), 1)
        self.assertEqual(self.store.revision()["scene"], self.scene)

    def test_restart_undo_does_not_revive_stale_source(self):
        result = self.create()
        event = self.ledger.withdraw(result["link_id"], REVIEW)
        self.import_source("Reviewed base dimension 140 mm.", b"%PDF- replacement",
                           source_id=self.ingested["source_id"])
        restarted = ParameterLinks(self.root)
        restarted.undo(event, REVIEW)
        self.assertEqual(restarted.inspect(result["link_id"])["status"], "stale")

    def test_stale_undo_event_rejected(self):
        result = self.create()
        self.ledger.withdraw(result["link_id"], REVIEW)
        with self.assertRaisesRegex(LinkError, "changed"):
            self.ledger.undo(result["event_id"], REVIEW)

    def test_idempotent_duplicate_confirmation(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first["link_id"], second["link_id"])
        self.assertTrue(second["idempotent"])
        with self.ledger._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM links").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_receipt_status_and_hash_binding_and_immutable_id(self):
        result = self.create()
        receipt = self.receipt(result["link_id"])
        self.ledger.attach_test_receipt(result["link_id"], receipt)
        self.ledger.attach_test_receipt(result["link_id"], receipt)
        for key, value in (("project_id", self.other.name), ("scene_hash", "0"*64),
                           ("link_sha256", "0"*64), ("source_sha256", "0"*64),
                           ("status", "passed"), ("run_at", "2026-10-08T22:31:00Z")):
            wrong = copy.deepcopy(receipt)
            wrong[key] = value
            with self.subTest(key=key), self.assertRaises(LinkError):
                self.ledger.attach_test_receipt(result["link_id"], wrong)
        self.assertEqual(self.ledger.inspect(result["link_id"])["tests"][0]["receipt"], receipt)

    def test_record_hash_tampering_refused(self):
        result = self.create()
        with self.ledger._db() as db:
            db.execute("UPDATE links SET payload=? WHERE id=?", (b"{}", result["link_id"]))
        with self.assertRaisesRegex(LinkError, "hash mismatch"):
            self.ledger.inspect(result["link_id"])

    def test_unknown_fields_duplicates_nonfinite_and_utf8_rejected(self):
        request = self.request()
        request["certified"] = True
        with self.assertRaises(LinkError):
            self.ledger.create(request)
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'"\xff"'):
            with self.subTest(raw=raw), self.assertRaises(LinkError):
                strict_json(raw)

    def test_current_project_identity_change_is_refused(self):
        result = self.create()
        (self.root / "project.json").write_text('{"project_id":"10000009"}')
        with self.assertRaisesRegex(LinkError, "identity changed"):
            self.ledger.inspect(result["link_id"])

    def test_ledger_limits_fail_before_write(self):
        with patch("workspace3d.parameter_links.MAX_LINKS", 0), self.assertRaises(LinkError):
            self.create()
        with patch("workspace3d.parameter_links.MAX_EVENTS", 0), self.assertRaises(LinkError):
            self.create()
        with self.ledger._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM links").fetchone()[0], 0)
        result = self.create()
        with patch("workspace3d.parameter_links.MAX_RECEIPTS", 0), self.assertRaises(LinkError):
            self.ledger.attach_test_receipt(result["link_id"], self.receipt(result["link_id"]))

    def test_new_annotations_not_in_provider_context(self):
        self.create()
        from core import chat_context
        with patch.object(chat_context, "load_all", return_value={"items": []}):
            text = chat_context.build_context(self.root, "Reviewed base dimension 120 mm")
        self.assertNotIn("IF-PDF-", text)
        self.assertNotIn("Synthetic test reviewer", text)
        self.assertNotIn("Reviewed base dimension", text)

    def test_compound_or_powered_source_units_cannot_link_length(self):
        for suffix in ("/s", "^2", " / s", " ^ 2", "·s", " * s", "²", "³",
                       "         /s", "\n/s", " s^-1", " s⁻¹", " per second", " x mm", "⁻¹", "⁺²"):
            with self.subTest(suffix=suffix):
                self.import_source("Reviewed base dimension 120 mm"+suffix+".",
                                   ("%PDF- compound "+suffix).encode("utf-8"),
                                   source_id=self.ingested["source_id"])
                row = pdf.retrieve_pdf(self.root, "Reviewed base dimension")[0]
                with self.assertRaisesRegex(LinkError, "Compound|boundaries"):
                    self.ledger.create(self.request(row=row))

    def test_recomputed_hash_cannot_hide_malformed_record(self):
        result = self.create()
        item = self.ledger.inspect(result["link_id"])
        for mutate in (lambda r: r.update(parameter_value=True),
                       lambda r: r["review"].update(confirmed=False),
                       lambda r: r["source"].update(page=True),
                       lambda r: r.update(parameter_unit="cm"),
                       lambda r: r.update(revision="0"),
                       lambda r: r["selection"].update(quote="20 mm")):
            record = copy.deepcopy(item["record"])
            mutate(record)
            raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
            with self.ledger._db() as db:
                db.execute("UPDATE links SET payload=?,sha256=? WHERE id=?",
                           (raw, hashlib.sha256(raw).hexdigest(), result["link_id"]))
            with self.subTest(record=record), self.assertRaises((LinkError, pdf.PDFEvidenceError)):
                self.ledger.inspect(result["link_id"])

    def test_recomputed_receipt_hash_still_requires_evidence_scope(self):
        result = self.create()
        receipt = self.receipt(result["link_id"])
        self.ledger.attach_test_receipt(result["link_id"], receipt)
        wrong = copy.deepcopy(receipt)
        wrong["scene_hash"] = "0"*64
        raw = json.dumps(wrong, sort_keys=True, separators=(",", ":")).encode()
        with self.ledger._db() as db:
            db.execute("UPDATE receipts SET payload=?,sha256=? WHERE id=?",
                       (raw, hashlib.sha256(raw).hexdigest(), receipt["id"]))
        with self.assertRaisesRegex(LinkError, "different evidence"):
            self.ledger.inspect(result["link_id"])

    def test_repeat_active_confirmation_is_idempotent_at_link_cap(self):
        result = self.create()
        with patch("workspace3d.parameter_links.MAX_LINKS", 1):
            repeated = self.create()
        self.assertEqual(repeated["link_id"], result["link_id"])
        self.assertTrue(repeated["idempotent"])

    def test_invalid_design_overflow_is_unknown(self):
        result = self.create()
        with patch("workspace3d.parameter_links.validate", side_effect=OverflowError("invalid fixture")):
            self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "unknown")

    def test_history_path_revalidated_for_persistent_ledger(self):
        result = self.create()
        with patch.object(pdf, "_path", wraps=pdf._path) as checked:
            self.ledger.inspect(result["link_id"])
        self.assertIn(((self.root, "workspace3d/history.sqlite3"),), [
            (call.args,) for call in checked.call_args_list])

    def test_pdf_import_lock_is_held_during_scene_and_source_snapshot(self):
        result = self.create()
        original = pdf.resolve_pdf_citation
        def check(root, citation):
            self.assertTrue((self.root / "research/pdf_evidence/.import-lock").is_dir())
            return original(root, citation)
        with patch.object(pdf, "resolve_pdf_citation", side_effect=check):
            self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "current")

    def test_busy_pdf_snapshot_is_unknown_not_current(self):
        result = self.create()
        lock = self.root / "research/pdf_evidence/.import-lock"
        lock.mkdir()
        self.addCleanup(lambda: lock.rmdir() if lock.exists() else None)
        item = self.ledger.inspect(result["link_id"])
        self.assertEqual(item["status"], "unknown")
        self.assertIn("source_snapshot_busy_or_invalid", item["reasons"])

    def test_nonblob_persisted_payload_refused_without_numeric_allocation(self):
        result = self.create()
        with self.ledger._db() as db:
            db.execute("UPDATE links SET payload=? WHERE id=?", (1000000000, result["link_id"]))
        with self.assertRaisesRegex(LinkError, "bounded bytes"):
            self.ledger.inspect(result["link_id"])

    def test_nontext_scene_payload_is_unknown(self):
        result = self.create()
        with self.store.connection() as db:
            db.execute("UPDATE revisions SET scene=? WHERE id=?", (1, self.revision))
        self.assertEqual(self.ledger.inspect(result["link_id"])["status"], "unknown")

    def test_hardlinked_database_refused_before_initializer_writes(self):
        external = self.base / "external.sqlite3"
        with sqlite3.connect(external) as db:
            db.execute("CREATE TABLE untouched(id INTEGER)")
        before = external.read_bytes()
        self.ledger.path.unlink()
        try:
            os.link(external, self.ledger.path)
        except (OSError, NotImplementedError):
            self.skipTest("Hard-link fixture unsupported by this filesystem")
        with self.assertRaisesRegex(LinkError, "one hard link"):
            ParameterLinks(self.root)
        self.assertEqual(external.read_bytes(), before)

    def test_hardlinked_database_sidecar_refused_before_sqlite_access(self):
        external = self.base / "foreign-journal"
        external.write_bytes(b"self-authored foreign sidecar bytes; do not change")
        before = external.read_bytes()
        sidecar = Path(str(self.ledger.path) + "-journal")
        try:
            os.link(external, sidecar)
        except (OSError, NotImplementedError):
            self.skipTest("Hard-link fixture unsupported by this filesystem")
        with self.assertRaisesRegex(LinkError, "one hard link"):
            self.create()
        self.assertEqual(external.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
