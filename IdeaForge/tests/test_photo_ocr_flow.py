"""Flow regressions use mocked native receipts, never run OCR or decode images.

All positive receipts are explicitly test_only=True. Signature bytes here are
self-authored non-decodable ledger fixtures, not an OCR accuracy benchmark.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import photo_ocr as ocr
from core import photo_ocr_flow as flow
from core.photo_inventory import APP_ID, PhotoEvidenceError, PhotoLedger, evaluate, _json_bytes


class PhotoOcrFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.policy = self.base / "policy"
        (self.policy / "ai").mkdir(parents=True)
        self.provider = {"protocol": "aster.provider.selection.v1", "provider": "standalone",
                         "app_id": flow.PROVIDER_APP_ID, "revision": 1}
        self.write_provider()
        self.ai = {"language_model": {"provider": "fixture", "model": "unrun-source-only"},
                   "vision_model": {"provider": "fixture", "model": "not-called"}}
        self.write_ai()
        files = [
            {"path": "python/python.exe", "sha256": "1" * 64, "bytes": 1},
            {"path": "engine/tesseract.exe", "sha256": "2" * 64, "bytes": 1},
            {"path": "model/eng.traineddata", "sha256": "3" * 64, "bytes": 1},
            {"path": "pillow/PIL/__init__.py", "sha256": "4" * 64, "bytes": 1},
        ]
        self.config = {
            "format": "photo-ocr.selection.v1", "enabled": False,
            "runtime_root": str(self.base / "uninstalled-runtime"),
            "python": "python/python.exe", "engine": "engine/tesseract.exe",
            "model": "model/eng.traineddata", "pillow_root": "pillow",
            "files": files, "code_sha256": {name: "5" * 64 for name in
                ("photo_ocr.py", "ocr_worker.py", "ocr_guard.py")},
            "catalog_sha256": ocr.CATALOG_SHA256, "engine_version": "5.5.3",
            "pillow_version": "10.4.0", "os_version": "SYNTHETIC-UNQUALIFIED",
            "qualification": None,
        }
        self.write_config()
        self.store = self.base / "photo_inventory"
        self.ledger = PhotoLedger(self.store, "project_a")
        self.intake()

    def write_provider(self, raw=None):
        (self.policy / "ai_provider.json").write_bytes(
            raw if raw is not None else _json_bytes(self.provider))

    def write_ai(self, raw=None):
        (self.policy / "ai" / "config.json").write_bytes(
            raw if raw is not None else _json_bytes(self.ai))

    def write_config(self, raw=None):
        (self.policy / flow.CONFIG_NAME).write_bytes(
            raw if raw is not None else ocr.canonical_bytes(self.config))

    def intake(self, item="board", view="front"):
        path = self.base / (view + ".png")
        path.write_bytes(b"\x89PNG\r\n\x1a\nSOURCE-ONLY-NO-DECODER-" + view.encode("ascii"))
        return self.ledger.intake(item, [path], reviewer="fixture-human", same_item_confirmed=True)

    def receipt(self, captured, tokens_by_view=None, confidence=99000):
        tokens_by_view = tokens_by_view or [["P3767-0003"] for _ in captured["photos"]]
        images = []
        for photo, tokens in zip(captured["photos"], tokens_by_view):
            words = [{"text": text, "bbox": [n * 320, 10, 300, 40],
                      "confidence_milli": confidence, "line": [1, 1, 1]}
                     for n, text in enumerate(tokens)]
            images.append({
                "photo_sha256": photo["sha256"], "bytes": photo["bytes"],
                "derived_sha256": "6" * 64, "width": 2000, "height": 400,
                "transform": "identity-no-exif", "tsv_sha256": "7" * 64,
                "words": words, "elapsed_ms": 0, "peak_job_memory_bytes": 0,
            })
        selection = hashlib.sha256((self.policy / flow.CONFIG_NAME).read_bytes()).hexdigest()
        return ocr._receipt(captured, selection, ocr.engine_binding(self.config), images, test_only=True)

    def recognize(self, tokens_by_view=None, *, confidence=99000, change=None, malformed=None):
        def native(config, captured, **kwargs):
            self.assertEqual(kwargs["selection_bytes"], (self.policy / flow.CONFIG_NAME).read_bytes())
            receipt = self.receipt(captured, tokens_by_view, confidence)
            if malformed is not None:
                malformed(receipt)
            if change is not None:
                change()
            return receipt
        with patch.object(ocr, "run_ocr", side_effect=native) as native_call:
            value = flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        self.assertEqual(native_call.call_count, 1)
        return value

    def request(self, preview, *, subject="module", confirm=True):
        return {
            "expected_revision": preview["expected_revision"], "reviewer": "fixture-human",
            "expected_subject": subject, "confirm_identity": confirm,
            "observed_words_confirmed": True, "candidate_ids": preview["candidate_ids"],
            "quantity": 2, "ownership": "owned", "scope": "project", "shared_with": [],
        }

    def approve(self, preview, request=None):
        return flow.approve(self.ledger, preview["receipt_sha256"], request or self.request(preview),
                            allow_test_only=True, _policy_root=self.policy)

    def head(self):
        return (self.store / "head.json").read_bytes()

    def test_legacy_manual_read_needs_no_ocr_configuration(self):
        (self.policy / flow.CONFIG_NAME).unlink()
        self.assertEqual(self.ledger.result("board")["recognition"], "unavailable")
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_a")), 1)

    def test_disabled_adapter_is_unavailable_before_native_work(self):
        captured = flow.capture(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        raw = (self.policy / flow.CONFIG_NAME).read_bytes()
        with self.assertRaises(ocr.OcrUnavailable):
            ocr.run_ocr(self.config, captured, store_root=self.store,
                        selection_sha256=hashlib.sha256(raw).hexdigest(), selection_bytes=raw)
        self.assertFalse((self.store / "ocr-run-lock").exists())
        self.assertFalse((self.store / "ocr_receipts").exists())

    def test_absent_explicit_configuration_is_unavailable(self):
        (self.policy / flow.CONFIG_NAME).unlink()
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaises(ocr.OcrUnavailable):
                flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        native.assert_not_called()

    def test_missing_provider_does_not_default_to_standalone(self):
        (self.policy / "ai_provider.json").unlink()
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaises(ocr.OcrUnavailable):
                flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        native.assert_not_called()

    def test_aster_selection_refuses_local_ocr_without_fallback(self):
        self.provider["provider"] = "aster"
        self.write_provider()
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaises(PhotoEvidenceError):
                flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        native.assert_not_called()

    def test_production_api_cannot_inject_policy_root(self):
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaises(PhotoEvidenceError):
                flow.recognize(self.ledger, "board", _policy_root=self.policy)
        native.assert_not_called()

    def test_legacy_provider_identity_is_exact_without_alias_merge(self):
        self.provider["app_id"] = ("humanoidresearcher" if flow.PROVIDER_APP_ID == "humanoid-researcher"
                                   else "humanoid-researcher")
        self.write_provider()
        with self.assertRaises(PhotoEvidenceError):
            flow.capture(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)

    def test_duplicate_or_nonfinite_provider_json_is_refused(self):
        for raw in (b'{"protocol":1,"protocol":2}', b'{"revision":NaN}'):
            self.write_provider(raw)
            with self.assertRaises(PhotoEvidenceError):
                flow.capture(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)

    def test_capture_binds_all_originals_and_current_human_review(self):
        self.intake(view="back")
        captured = flow.capture(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        self.assertEqual(len(captured["photos"]), 2)
        self.assertEqual(captured["photos"], self.ledger.get("board")["photos"])
        self.assertEqual(captured["provider_selection_sha256"],
                         hashlib.sha256((self.policy / "ai_provider.json").read_bytes()).hexdigest())
        self.assertEqual(captured["ai_config_sha256"],
                         hashlib.sha256((self.policy / "ai" / "config.json").read_bytes()).hexdigest())
        snapshot = self.store / "versions" / (str(captured["revision"]) + ".json")
        self.assertEqual(captured["state_sha256"], hashlib.sha256(snapshot.read_bytes()).hexdigest())

    def test_exact_match_preview_preserves_public_quote_box_and_hashes(self):
        value = self.recognize()
        self.assertEqual(value["matches"][0]["quote"], "P3767-0003")
        self.assertEqual(value["matches"][0]["bbox"], [0, 10, 300, 40])
        self.assertEqual(value["matches"][0]["derived_sha256"], "6" * 64)
        self.assertTrue(value["test_only"])
        self.assertTrue(value["stale_policy"])
        self.assertNotIn(str(self.base), json.dumps(value))

    def test_approval_keeps_human_observations_and_ocr_provenance_separate(self):
        photo = self.ledger.get("board")["photos"][0]["sha256"]
        observations = [{"photo_sha256": photo, "subject": "module", "kind": "label",
                         "visibility": "clear", "text": "Human observation kept local"}]
        self.ledger.review("board", reviewer="original-human", expected_subject="module",
                           observations=observations, confirm_identity=False)
        before = copy.deepcopy(self.ledger.get("board")["review"])
        value = self.recognize()
        self.approve(value)
        item = self.ledger.get("board")
        self.assertEqual(item["review"], before)
        self.assertEqual(item["ocr_review"]["receipt_sha256"], value["receipt_sha256"])
        self.assertEqual(item["ocr_review"]["summary"]["identities"]["module"]["memory_gb"], 8)
        self.assertEqual(item["quantity"], 2)
        self.assertTrue(item["ocr_review"]["test_only"])
        self.assertEqual(self.ledger.result("board")["recognition"], "synthetic-evidence-only")
        self.assertEqual(self.ledger.result("board")["status"], "provisional")
        self.assertTrue(self.ledger.result("board")["ocr_provenance"]["test_only"])
        self.assertEqual(self.ledger.result("board")["ocr_provenance"]["qualification"], "synthetic-unqualified")
        self.assertIn("Synthetic OCR receipt fixture", self.ledger.inventory_items(project_id="project_a")[0]["notes"])

    def test_raw_unknown_words_and_reviewer_never_enter_result_or_preview(self):
        value = self.recognize([["P3767-0003", "SYNTHETIC-LOCAL-NOTE"]])
        self.approve(value)
        public = json.dumps(value) + json.dumps(self.ledger.result("board"))
        self.assertNotIn("SYNTHETIC-LOCAL-NOTE", public)
        self.assertNotIn("fixture-human", public)
        self.assertNotIn(str(self.base), public)
        raw = (self.store / "ocr_receipts" / (value["receipt_sha256"] + ".json")).read_bytes()
        self.assertIn(b"SYNTHETIC-LOCAL-NOTE", raw)

    def test_partial_code_refuses_any_inventory_approval(self):
        value = self.recognize([["P3767-0003", "P3767"]])
        before = self.head()
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value, self.request(value, confirm=False))
        self.assertEqual(self.head(), before)
        self.assertIsNone(self.ledger.get("board").get("ocr_review"))

    def test_character_confusion_is_unknown_without_repair(self):
        value = self.recognize([["P3767-OOO3"]])
        self.assertEqual(value["matches"], [])
        self.assertEqual(value["status"], "unresolved")
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value)

    def test_low_confidence_exact_code_remains_unresolved(self):
        value = self.recognize(confidence=84999)
        self.assertEqual(value["status"], "unresolved")
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value)

    def test_conflicting_views_are_not_voted_or_cherry_picked(self):
        self.intake(view="back")
        value = self.recognize([["P3767-0003"], ["P3767-0004"]])
        before = self.head()
        request = self.request(value, confirm=False)
        request["candidate_ids"] = request["candidate_ids"][:1]
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value, request)
        self.assertEqual(value["status"], "conflicting")
        self.assertEqual(self.head(), before)

    def test_same_code_two_views_stays_one_group_one_quantity(self):
        self.intake(view="back")
        value = self.recognize([["P3767-0003"], ["P3767-0003"]])
        self.approve(value)
        items = self.ledger.inventory_items(project_id="project_a")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["quantity"], 2)
        self.assertEqual(len(self.ledger.get("board")["photos"]), 2)

    def test_carrier_code_cannot_confirm_module_identity(self):
        value = self.recognize([["P3768-0000"]])
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value, self.request(value, subject="module"))

    def test_module_carrier_pair_is_assembly_and_never_kit(self):
        self.intake(view="back")
        value = self.recognize([["P3767-0003"], ["P3768-0000"]])
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value, self.request(value, subject="developer_kit"))
        self.approve(value, self.request(value, subject="assembly"))
        identities = self.ledger.get("board")["ocr_review"]["summary"]["identities"]
        self.assertEqual(set(identities), {"module", "carrier"})
        self.assertNotIn("developer_kit", identities)
        self.assertIsNone(identities["carrier"]["memory_gb"])

    def test_kit_requires_own_exact_code_revision_stays_unknown(self):
        value = self.recognize([["945-13450-0000-100"]])
        self.approve(value, self.request(value, subject="developer_kit"))
        identity = self.ledger.get("board")["ocr_review"]["summary"]["identities"]["developer_kit"]
        self.assertIn("B01", identity["name"])
        self.assertEqual(identity["hardware_revision"], "unknown")
        self.assertIsNone(identity["memory_gb"])

    def test_wrong_catalog_or_engine_output_refuses_before_receipt_write(self):
        for field in ("catalog_sha256", "engine"):
            def bad(receipt):
                if field == "engine":
                    receipt["engine"]["model_sha256"] = "f" * 64
                else:
                    receipt[field] = "f" * 64
            with self.assertRaises(PhotoEvidenceError):
                self.recognize(malformed=bad)
        self.assertFalse((self.store / "ocr_receipts").exists())

    def test_malformed_output_unknown_field_and_bool_integer_refused(self):
        for mutate in (
            lambda r: r.update(extra=True),
            lambda r: r["metrics"].update(elapsed_ms=True),
            lambda r: r["images"][0]["words"][0].update(bbox=[0, 0, -1, 1]),
        ):
            with self.assertRaises(PhotoEvidenceError):
                self.recognize(malformed=mutate)
        self.assertFalse((self.store / "ocr_receipts").exists())

    def test_completion_rejects_intervening_ledger_revision(self):
        before = self.head()
        with self.assertRaises(PhotoEvidenceError):
            self.recognize(change=lambda: self.ledger.confirm_quantity("board", 1, reviewer="other-human"))
        self.assertNotEqual(self.head(), before)
        self.assertFalse((self.store / "ocr_receipts").exists())

    def test_completion_rejects_provider_and_ai_and_ocr_rawbyte_changes(self):
        for path in ("ai_provider.json", "ai/config.json", flow.CONFIG_NAME):
            target = self.policy / path
            original = target.read_bytes()
            with self.assertRaises(PhotoEvidenceError):
                self.recognize(change=lambda: target.write_bytes(original + b" "))
            target.write_bytes(original)
        self.assertFalse((self.store / "ocr_receipts").exists())

    def test_completion_rejects_new_photo_view(self):
        with self.assertRaises(PhotoEvidenceError):
            self.recognize(change=lambda: self.intake(view="new"))
        self.assertEqual(len(self.ledger.get("board")["photos"]), 2)
        self.assertFalse((self.store / "ocr_receipts").exists())

    def test_review_requires_expected_revision_and_checked_words(self):
        value = self.recognize()
        for field, bad in (("expected_revision", value["expected_revision"] + 1),
                           ("observed_words_confirmed", False), ("quantity", True)):
            request = self.request(value)
            request[field] = bad
            with self.assertRaises(PhotoEvidenceError):
                self.approve(value, request)
        self.assertIsNone(self.ledger.get("board").get("ocr_review"))

    def test_review_requires_every_candidate_and_no_unknown_request_fields(self):
        value = self.recognize()
        for bad in ([], value["candidate_ids"] * 2):
            request = self.request(value)
            request["candidate_ids"] = bad
            with self.assertRaises(PhotoEvidenceError):
                self.approve(value, request)
        request = self.request(value)
        request["serial"] = "UNKNOWN-FIELD-NOT-A-REAL-SERIAL"
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value, request)

    def test_review_policy_change_is_rejected_without_head_mutation(self):
        value = self.recognize()
        before = self.head()
        self.provider["revision"] = 2
        self.write_provider()
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value)
        self.assertEqual(self.head(), before)

    def test_final_policy_recheck_precedes_publication(self):
        value = self.recognize()
        before = self.head()
        original = flow._selection
        count = []
        def interleave(root):
            count.append(1)
            if len(count) == 2:
                self.write_ai((self.policy / "ai" / "config.json").read_bytes() + b" ")
            return original(root)
        with patch.object(flow, "_selection", side_effect=interleave):
            with self.assertRaises(PhotoEvidenceError):
                self.approve(value)
        self.assertEqual(self.head(), before)

    def test_one_writer_lock_prevents_nested_approval_and_writes(self):
        value = self.recognize()
        before = self.head()
        (self.store / "write-lock").mkdir()
        with self.assertRaises(PhotoEvidenceError):
            self.approve(value)
        self.assertEqual(self.head(), before)
        (self.store / "write-lock").rmdir()
        self.approve(value)
        self.assertFalse((self.store / "write-lock").exists())

    def test_receipt_and_original_tampering_refuse_inventory_read(self):
        value = self.recognize()
        self.approve(value)
        path = self.store / "ocr_receipts" / (value["receipt_sha256"] + ".json")
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.result("board")
        path.write_bytes(original)
        photo = self.ledger.get("board")["photos"][0]["sha256"]
        (self.store / "images" / (photo + ".bin")).write_bytes(b"\x89PNG\r\n\x1a\ntampered")
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.inventory_items(project_id="project_a")

    def test_receipt_cross_project_rebinding_is_refused(self):
        value = self.recognize()
        other = PhotoLedger(self.base / "other_photo_inventory", "project_b")
        other.intake("board", [self.base / "front.png"], reviewer="fixture", same_item_confirmed=True)
        target = other.root / "ocr_receipts"
        target.mkdir()
        source = self.store / "ocr_receipts" / (value["receipt_sha256"] + ".json")
        (target / source.name).write_bytes(source.read_bytes())
        with self.assertRaises(PhotoEvidenceError):
            flow.approve(other, value["receipt_sha256"], self.request(value),
                         allow_test_only=True, _policy_root=self.policy)
        self.assertEqual(other.inventory_items(project_id="project_a"), [])

    def test_restart_preserves_ocr_receipt_and_manual_history(self):
        value = self.recognize()
        self.approve(value)
        reopened = PhotoLedger(self.store, "project_a")
        self.assertEqual(reopened.get("board"), self.ledger.get("board"))
        self.assertEqual(reopened.result("board"), self.ledger.result("board"))
        self.assertFalse(reopened.result("board")["original_image_bytes_in_bundle"])
        self.assertEqual(reopened.result("board")["image_verification"], "unavailable")

    def test_new_view_and_manual_review_clear_ocr_choice_with_history(self):
        value = self.recognize()
        self.approve(value)
        self.ledger.review("board", reviewer="human-correction", expected_subject="unknown", observations=[])
        item = self.ledger.get("board")
        self.assertIsNone(item["ocr_review"])
        self.assertEqual(item["history"][-1]["prior_ocr_review"]["receipt_sha256"], value["receipt_sha256"])
        value = self.recognize()
        self.approve(value)
        self.intake(view="later")
        self.assertIsNone(self.ledger.get("board")["ocr_review"])
        self.assertEqual(self.ledger.result("board")["recognition"], "unavailable")

    def test_quantity_and_sharing_changes_invalidate_ocr_confirmation(self):
        value = self.recognize()
        self.approve(value)
        self.ledger.confirm_quantity("board", 3, reviewer="correction")
        self.assertFalse(self.ledger.get("board")["ocr_review"]["confirm_identity"])
        self.assertEqual(evaluate(self.ledger.get("board"))["status"], "provisional")
        self.ledger.set_sharing("board", scope="equipment", shared_with=["project_b"], reviewer="correction")
        self.assertEqual(self.ledger.inventory_items(project_id="project_b"), [])
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_b", include_shared=True)), 1)

    def test_stale_projection_is_provisional_even_if_review_was_confirmed(self):
        value = self.recognize()
        self.approve(value)
        with patch.object(flow, "review_current", return_value=False):
            result = self.ledger.result("board")
            projected = self.ledger.inventory_items(project_id="project_a")[0]
        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["confidence"], "unknown")
        self.assertEqual(projected["photo_status"], "provisional")
        self.assertFalse(projected["verified"])

    def test_clear_preserves_human_review_and_ocr_history(self):
        value = self.recognize()
        self.approve(value)
        before = self.ledger.get("board")
        revision = int(self.ledger.result("board")["revision"])
        flow.clear(self.ledger, "board", expected_revision=revision, reviewer="human-clear")
        item = self.ledger.get("board")
        self.assertIsNone(item["ocr_review"])
        self.assertEqual(item["review"], before["review"])
        self.assertEqual(item["history"][-1]["prior_ocr_review"], before["ocr_review"])
        self.assertEqual(item["quantity"], 2)

    def test_undo_restores_prior_quantity_sharing_without_restoring_ocr(self):
        self.ledger.confirm_quantity("board", 1, reviewer="original-quantity", ownership="borrowed")
        value = self.recognize()
        request = self.request(value)
        request.update(scope="equipment", shared_with=["project_b"])
        self.approve(value, request)
        revision = int(self.ledger.result("board")["revision"])
        flow.clear(self.ledger, "board", expected_revision=revision, reviewer="human-undo", undo=True)
        item = self.ledger.get("board")
        self.assertEqual((item["quantity"], item["quantity_reviewer"], item["ownership"]),
                         (1, "original-quantity", "borrowed"))
        self.assertEqual((item["scope"], item["shared_with"]), ("project", []))
        self.assertIsNone(item["ocr_review"])

    def test_undo_refuses_after_intervening_edits(self):
        value = self.recognize()
        self.approve(value)
        self.ledger.confirm_quantity("board", 3, reviewer="new-quantity")
        before = self.head()
        with self.assertRaises(PhotoEvidenceError):
            flow.clear(self.ledger, "board", expected_revision=int(self.ledger.result("board")["revision"]),
                       reviewer="human-undo", undo=True)
        self.assertEqual(self.head(), before)

    def test_receipt_quota_and_orphan_budget_refuse_without_review_mutation(self):
        directory = self.store / "ocr_receipts"
        directory.mkdir()
        for number in range(32):
            (directory / (format(number, "064x") + ".json")).write_bytes(b"{}\n")
        before = self.head()
        with self.assertRaises(PhotoEvidenceError):
            self.recognize()
        self.assertEqual(self.head(), before)
        self.assertIsNone(self.ledger.get("board").get("ocr_review"))

    def test_malformed_private_receipt_is_refused_as_controlled_error(self):
        value = self.recognize()
        target = self.store / "ocr_receipts" / (value["receipt_sha256"] + ".json")
        target.write_bytes(b'{"a":1,"a":2}')
        with self.assertRaises(PhotoEvidenceError):
            flow.preview(self.ledger, value["receipt_sha256"])

    def test_private_receipt_hardlink_is_refused_when_supported(self):
        value = self.recognize()
        target = self.store / "ocr_receipts" / (value["receipt_sha256"] + ".json")
        try:
            (self.base / "linked.json").hardlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Fixture filesystem does not support hardlinks")
        with self.assertRaises(PhotoEvidenceError):
            flow.preview(self.ledger, value["receipt_sha256"])


    def test_injected_enabled_selection_never_calls_runner(self):
        self.config["enabled"] = True
        self.write_config()
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaisesRegex(PhotoEvidenceError, "Injected test roots must be disabled and unqualified"):
                flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        native.assert_not_called()

    def test_empty_language_model_selection_refuses_without_runner(self):
        self.ai["language_model"] = {}
        self.write_ai()
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaises(PhotoEvidenceError):
                flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        native.assert_not_called()

    def test_malformed_item_and_history_types_are_controlled(self):
        state = self.ledger._load()
        for bad in (None, 1):
            malformed = copy.deepcopy(state)
            malformed["items"][0] = bad
            with self.assertRaises(PhotoEvidenceError):
                self.ledger._validate(malformed)
            malformed = copy.deepcopy(state)
            malformed["items"][0]["history"][0] = bad
            with self.assertRaises(PhotoEvidenceError):
                self.ledger._validate(malformed)

    def test_summary_boolean_integer_tamper_is_rejected(self):
        value = self.recognize()
        self.approve(value)
        state = self.ledger._load()
        state["items"][0]["ocr_review"]["summary"]["unresolved_model_code_count"] = False
        with self.assertRaises(PhotoEvidenceError):
            self.ledger._validate(state)



    def test_injected_nonempty_qualification_never_calls_runner(self):
        self.config["qualification"] = {
            "format": "photo-ocr.qualification.v1",
            "runtime_sha256": hashlib.sha256(ocr.canonical_bytes(self.config["files"])).hexdigest(),
            "code_sha256": copy.deepcopy(self.config["code_sha256"]),
            "catalog_sha256": self.config["catalog_sha256"],
            "engine_version": self.config["engine_version"],
            "pillow_version": self.config["pillow_version"],
            "os_version": self.config["os_version"],
            "receipt_root": str(self.base / "uninstalled-qualification"),
            "tests": [{"id": name, "status": "unrun", "receipt_path": name + ".json",
                       "receipt_bytes": 1, "receipt_sha256": "0" * 64}
                      for name in sorted(ocr.REQUIRED_TESTS)],
        }
        self.write_config()
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaisesRegex(PhotoEvidenceError, "Injected test roots must be disabled and unqualified"):
                flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        native.assert_not_called()

    def test_receipt_budget_is_reserved_before_runner(self):
        directory = self.store / "ocr_receipts"
        directory.mkdir()
        for number in range(32):
            (directory / (format(number, "064x") + ".json")).write_bytes(b"{}\\n")
        with patch.object(ocr, "run_ocr") as native:
            with self.assertRaises(PhotoEvidenceError):
                flow.recognize(self.ledger, "board", allow_test_only=True, _policy_root=self.policy)
        native.assert_not_called()


    def test_ocr_history_missing_quantity_reviewer_is_controlled(self):
        value = self.recognize()
        self.approve(value)
        state = self.ledger._load()
        del state["items"][0]["history"][-1]["prior_quantity_reviewer"]
        with self.assertRaises(PhotoEvidenceError):
            self.ledger._validate(state)


if __name__ == "__main__":
    unittest.main()
