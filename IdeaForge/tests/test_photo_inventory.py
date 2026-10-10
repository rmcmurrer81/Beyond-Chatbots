"""Self-authored synthetic PNG-label fixtures; no real user's photographs."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from core.photo_inventory import APP_ID, CATALOG, PhotoEvidenceError, PhotoLedger, evaluate, _decode

FONT = {
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
}

def synthetic_png(label="P3767-0003", view="front"):
    """An original black/white label drawing, not a hardware photograph."""
    width, height = 8 + 6 * len(label), 15
    rows = []
    for y in range(height):
        row = bytearray([255] * width)
        if 4 <= y < 11:
            for n, char in enumerate(label):
                for x, bit in enumerate(FONT.get(char, FONT["-"])[y-4]):
                    if bit == "1":
                        row[4 + n * 6 + x] = 0
        rows.append(b"\0" + bytes(row))
    def chunk(kind, raw):
        return struct.pack(">I", len(raw)) + kind + raw + struct.pack(">I", zlib.crc32(kind + raw) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) +
            chunk(b"tEXt", b"Fixture\0self-authored synthetic label; " + view.encode("ascii")) +
            chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


class PhotoInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.store = self.base / "ledger"
        self.ledger = PhotoLedger(self.store, "project_a")

    def photo(self, label="P3767-0003", view="front"):
        path = self.base / (view + ".png")
        path.write_bytes(synthetic_png(label, view))
        return path

    def intake(self, paths=None, item="board", **kwargs):
        return self.ledger.intake(item, paths or [self.photo()], reviewer="fixture-reviewer",
                                  same_item_confirmed=True, **kwargs)

    def observations(self, item="board", codes=None):
        images = self.ledger.get(item)["photos"]
        codes = codes or [("module", "P3767-0003", "clear")]
        return [{"photo_sha256": images[min(n, len(images)-1)]["sha256"], "subject": subject,
                 "kind": "model_code", "visibility": visibility, "text": code}
                for n, (subject, code, visibility) in enumerate(codes)]

    def review(self, subject="module", codes=None, confirmed=True):
        return self.ledger.review("board", reviewer="fixture-reviewer", expected_subject=subject,
                                  observations=self.observations(codes=codes), confirm_identity=confirmed)

    def test_multiple_views_are_one_group_and_unknown_quantity(self):
        item = self.intake([self.photo(view="front"), self.photo(view="back")])
        self.assertEqual(len(item["photos"]), 2)
        self.assertIsNone(item["quantity"])
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_a")), 1)

    def test_duplicate_view_bytes_do_not_add_images_or_items(self):
        path = self.photo()
        first = self.intake([path, path])
        before = self.ledger.result("board")["revision"]
        second = self.intake([path])
        self.assertEqual(first, second)
        self.assertEqual(before, self.ledger.result("board")["revision"])
        self.assertEqual(len(second["photos"]), 1)

    def test_duplicate_image_in_another_group_is_refused(self):
        path = self.photo()
        self.intake([path])
        with self.assertRaises(PhotoEvidenceError):
            self.intake([path], item="duplicate")
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_a")), 1)

    def test_same_item_grouping_requires_explicit_confirmation(self):
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.intake("board", [self.photo()], reviewer="fixture", same_item_confirmed=False)

    def test_quantity_requires_positive_integer_and_explicit_ownership(self):
        self.intake()
        for quantity in (True, 0, -1, 1.0, 10001):
            with self.assertRaises(PhotoEvidenceError):
                self.ledger.confirm_quantity("board", quantity, reviewer="fixture")
        self.ledger.confirm_quantity("board", 2, reviewer="fixture", ownership="owned")
        item = self.ledger.inventory_items(project_id="project_a")[0]
        self.assertEqual((item["quantity"], item["ownership_status"]), (2, "owned"))

    def test_quantity_alone_cannot_identify_a_part(self):
        self.intake()
        self.ledger.confirm_quantity("board", 1, reviewer="fixture")
        self.assertEqual(self.ledger.result("board")["status"], "provisional")

    def test_catalog_code_requires_manual_identity_and_quantity_confirmation(self):
        self.intake()
        self.assertEqual(self.review()["status"], "provisional")
        self.ledger.confirm_quantity("board", 1, reviewer="fixture", ownership="owned")
        self.assertEqual(self.review()["status"], "reviewed")
        identity = self.ledger.result("board")["identities"]["module"]
        self.assertEqual(identity["name"], "Jetson Orin Nano 8GB")
        self.assertEqual(identity["hardware_revision"], "unknown")
        self.assertIsNone(identity["document_sha256"])
        self.assertFalse(self.ledger.inventory_items(project_id="project_a")[0]["verified"])

    def test_known_plus_unknown_clear_model_code_remains_provisional(self):
        self.intake()
        self.ledger.confirm_quantity("board", 1, reviewer="fixture")
        result = self.review(codes=[("module", "P3767-0003", "clear"),
                                   ("module", "P3767-9999", "clear")])
        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["unresolved_model_code_count"], 1)
        self.assertIn("module", result["identities"])
        self.assertIsNotNone(result["follow_up"])
        self.assertNotIn("P3767-9999", json.dumps(self.ledger.result("board")))

    def test_unassigned_unknown_clear_code_prevents_confirmation(self):
        self.intake()
        self.ledger.confirm_quantity("board", 1, reviewer="fixture")
        result = self.review(codes=[("module", "P3767-0003", "clear"),
                                   ("unknown", "UNRESOLVED-PUBLIC-CODE", "clear")])
        self.assertEqual(result["status"], "provisional")
        self.assertEqual(result["unresolved_model_code_count"], 1)

    def test_projection_ids_distinguish_hyphenated_scope_ids_and_stores(self):
        one = PhotoLedger(self.base / "one", "a-b")
        two = PhotoLedger(self.base / "two", "a")
        other_store = PhotoLedger(self.base / "other", "a-b")
        path = self.photo()
        for ledger, item in ((one, "c"), (two, "b-c"), (other_store, "c")):
            ledger.intake(item, [path], reviewer="fixture", same_item_confirmed=True)
        keys = [one.inventory_items(project_id="a-b")[0]["equipment_id"],
                two.inventory_items(project_id="a")[0]["equipment_id"],
                other_store.inventory_items(project_id="a-b")[0]["equipment_id"]]
        self.assertEqual(len(set(keys)), 3)

    def test_generic_family_code_does_not_infer_ram_or_exact_model(self):
        self.intake()
        result = self.review(codes=[("module", "P3767", "clear")])
        self.assertEqual(result["identities"], {})
        self.assertEqual(result["status"], "provisional")

    def test_generic_visual_similarity_and_ports_do_not_resolve_identity(self):
        self.intake()
        obs = self.observations()
        obs[0].update(kind="port", text="USB ports and heatsink resemble a Jetson")
        self.ledger.review("board", reviewer="fixture", expected_subject="module",
                           observations=obs, confirm_identity=True)
        self.assertEqual(self.ledger.result("board")["identities"], {})

    def test_blurred_and_missing_markings_remain_provisional(self):
        self.intake()
        for visibility in ("blurred", "missing"):
            result = self.review(codes=[("module", "P3767-0003", visibility)])
            self.assertEqual(result["status"], "provisional")
            self.assertIn("carrier underside", result["follow_up"])
            self.assertEqual(result["identities"], {})

    def test_clear_conflicting_labels_are_not_voted_by_photo_count(self):
        self.intake([self.photo(view="front"), self.photo("P3767-0004", "back")])
        self.ledger.confirm_quantity("board", 1, reviewer="fixture")
        result = self.review(codes=[("module", "P3767-0003", "clear"),
                                   ("module", "P3767-0004", "clear"),
                                   ("module", "P3767-0003", "clear")])
        self.assertEqual(result["status"], "conflicting")
        self.assertNotIn("module", result["identities"])

    def test_carrier_code_claimed_as_module_is_conflicting(self):
        self.intake()
        result = self.review(codes=[("module", "P3768-0000", "clear")])
        self.assertEqual(result["status"], "conflicting")
        self.assertEqual(result["identities"], {})

    def test_known_module_carrier_are_separate_and_do_not_establish_kit(self):
        self.intake([self.photo(view="front"), self.photo("P3768-0000", "back")])
        self.ledger.confirm_quantity("board", 1, reviewer="fixture")
        result = self.review(subject="assembly", codes=[("module", "P3767-0003", "clear"),
                                                       ("carrier", "P3768-0000", "clear")])
        self.assertEqual(result["status"], "reviewed")
        self.assertEqual(set(result["identities"]), {"module", "carrier"})
        self.assertNotIn("developer_kit", result["identities"])
        self.assertIsNone(self.ledger.inventory_items(project_id="project_a")[0]["model"])

    def test_carrier_alone_does_not_identify_module(self):
        self.intake()
        result = self.review(subject="module", codes=[("carrier", "P3768-0000", "clear")])
        self.assertEqual(result["status"], "provisional")
        self.assertNotIn("module", result["identities"])

    def test_developer_kit_requires_its_own_full_box_code(self):
        self.intake([self.photo("945-13450-0000-100")])
        self.ledger.confirm_quantity("board", 1, reviewer="fixture")
        result = self.review(subject="developer_kit", codes=[("developer_kit", "945-13450-0000-100", "clear")])
        self.assertEqual(result["status"], "reviewed")
        self.assertIn("B01", result["identities"]["developer_kit"]["name"])
        self.assertEqual(result["identities"]["developer_kit"]["hardware_revision"], "unknown")

    def test_restart_preserves_original_bytes_and_review(self):
        path = self.photo()
        original = path.read_bytes()
        self.intake([path])
        self.review()
        restarted = PhotoLedger(self.store, "project_a")
        item = restarted.get("board")
        saved = self.store / "images" / (item["photos"][0]["sha256"] + ".bin")
        self.assertEqual(saved.read_bytes(), original)
        self.assertEqual(restarted.result("board"), self.ledger.result("board"))

    def test_user_correction_preserves_previous_review_history(self):
        self.intake()
        self.review(codes=[("module", "P3767-0003", "clear")])
        self.review(codes=[("module", "P3767-0004", "clear")])
        item = self.ledger.get("board")
        previous = item["history"][-1]["prior_review"]
        self.assertEqual(previous["observations"][0]["text"], "P3767-0003")
        self.assertEqual(item["review"]["observations"][0]["text"], "P3767-0004")

    def test_added_view_invalidates_identity_confirmation(self):
        self.intake()
        self.ledger.confirm_quantity("board", 1, reviewer="fixture")
        self.assertEqual(self.review()["status"], "reviewed")
        self.intake([self.photo(view="new_view")])
        self.assertIsNone(self.ledger.get("board")["review"])
        self.assertEqual(self.ledger.result("board")["status"], "provisional")

    def test_project_isolation_and_explicit_shared_equipment_scope(self):
        self.intake()
        self.assertEqual(self.ledger.inventory_items(project_id="project_b"), [])
        self.ledger.set_sharing("board", scope="equipment", shared_with=["project_b"], reviewer="fixture")
        self.assertEqual(self.ledger.inventory_items(project_id="project_b"), [])
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_b", include_shared=True)), 1)
        self.assertEqual(self.ledger.inventory_items(project_id="project_c", include_shared=True), [])

    def test_rebinding_project_or_copying_store_is_refused(self):
        self.intake()
        with self.assertRaises(PhotoEvidenceError):
            PhotoLedger(self.store, "project_b")
        import shutil
        other = self.base / "copied"
        shutil.copytree(self.store, other)
        with self.assertRaises(PhotoEvidenceError):
            PhotoLedger(other, "project_a")

    def test_tampered_original_image_is_refused_and_no_inventory_returned(self):
        self.intake()
        digest = self.ledger.get("board")["photos"][0]["sha256"]
        (self.store / "images" / (digest + ".bin")).write_bytes(synthetic_png("P3767-0004"))
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.inventory_items(project_id="project_a")

    def test_tampered_metadata_snapshot_is_refused(self):
        self.intake()
        revision = self.ledger.result("board")["revision"]
        path = self.store / "versions" / (revision + ".json")
        value = json.loads(path.read_text())
        value["items"][0]["quantity"] = 99
        path.write_text(json.dumps(value))
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.result("board")

    def test_source_image_replacement_cannot_change_saved_original(self):
        path = self.photo()
        self.intake([path])
        first = self.ledger.get("board")["photos"][0]
        path.write_bytes(synthetic_png("P3767-0004"))
        self.assertEqual(self.ledger.get("board")["photos"], [first])

    def test_observation_for_another_image_is_refused(self):
        self.intake()
        obs = self.observations()
        obs[0]["photo_sha256"] = "0" * 64
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.review("board", reviewer="fixture", expected_subject="module", observations=obs)

    def test_serial_field_and_unknown_review_fields_are_refused(self):
        self.intake()
        obs = self.observations()
        obs[0]["serial"] = "SYNTHETIC-PRIVATE-NOT-A-REAL-SERIAL"
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.review("board", reviewer="fixture", expected_subject="module", observations=obs)

    def test_export_metadata_excludes_private_text_and_original_images(self):
        self.intake()
        obs = self.observations()
        obs.append({**obs[0], "kind": "label", "text": "SYNTHETIC-LOCAL-ONLY-NOTE"})
        self.ledger.review("board", reviewer="SYNTHETIC-LOCAL-REVIEWER", expected_subject="module", observations=obs)
        result = self.ledger.result("board")
        raw = json.dumps(result)
        self.assertNotIn("SYNTHETIC-LOCAL", raw)
        self.assertNotIn(str(self.base), raw)
        self.assertFalse(result["original_image_bytes_in_bundle"])
        self.assertEqual(result["image_verification"], "unavailable")
        self.assertEqual(result["local_image_verification"], "sha256-and-byte-count-checked")
        self.assertEqual(result["recognition"], "unavailable")

    def test_file_and_view_limits_refuse_before_inventory_mutation(self):
        path = self.base / "oversize.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (1024 * 1024))
        with self.assertRaises(PhotoEvidenceError):
            self.intake([path])
        with self.assertRaises(PhotoEvidenceError):
            self.intake([self.photo(view="view" + str(n)) for n in range(7)])
        self.assertEqual(self.ledger.inventory_items(project_id="project_a"), [])

    def test_malformed_enum_containers_refuse_as_evidence_error(self):
        self.intake()
        for key in ("subject", "kind", "visibility"):
            for bad in ([], {}, None, 1):
                observations = self.observations()
                observations[0][key] = bad
                with self.assertRaises(PhotoEvidenceError):
                    self.ledger.review("board", reviewer="fixture", expected_subject="module",
                                       observations=observations)
        for bad in ([], {}, None, 1):
            with self.assertRaises(PhotoEvidenceError):
                self.ledger.review("board", reviewer="fixture", expected_subject=bad,
                                   observations=self.observations())

    def test_unsupported_bytes_and_invalid_json_are_refused(self):
        path = self.base / "bad.png"
        path.write_bytes(b"This is not a PNG")
        with self.assertRaises(PhotoEvidenceError):
            self.intake([path])
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1.2}', b'"\xff"'):
            with self.assertRaises(PhotoEvidenceError):
                _decode(raw)

    def test_signature_intake_does_not_claim_a_decoded_or_understood_image(self):
        path = self.base / "signature-only.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\nnot-decodable")
        self.intake([path])
        self.assertEqual(self.ledger.result("board")["recognition"], "unavailable")
        self.assertEqual(self.ledger.result("board")["status"], "provisional")

    def test_provider_is_never_imported_or_called(self):
        import inspect
        import sys
        module = sys.modules[PhotoLedger.__module__]
        source = inspect.getsource(module)
        self.assertNotIn("import requests", source)
        self.assertNotIn("from ai.", source)
        self.assertNotIn("analyze_image(", source)
        self.intake()
        self.assertEqual(self.ledger.result("board")["recognition"], "unavailable")

    def test_locked_intake_writes_no_orphan_images_or_head(self):
        self.intake()
        before_head = (self.store / "head.json").read_bytes()
        before_images = sorted(path.name for path in (self.store / "images").iterdir())
        (self.store / "write-lock").mkdir()
        with self.assertRaises(PhotoEvidenceError):
            self.intake([self.photo(view="second")])
        self.assertEqual((self.store / "head.json").read_bytes(), before_head)
        self.assertEqual(sorted(path.name for path in (self.store / "images").iterdir()), before_images)

    def test_second_intake_during_locked_quota_check_is_refused_without_writes(self):
        self.intake()
        from unittest.mock import patch
        before = self.ledger.result("board")
        second = PhotoLedger(self.store, "project_a")
        path = self.photo(view="second")
        original = self.ledger._layout_budget
        attempted = []
        def interleave():
            if not attempted:
                attempted.append(True)
                with self.assertRaises(PhotoEvidenceError):
                    second.intake("other", [path], reviewer="fixture", same_item_confirmed=True)
            return original()
        with patch.object(self.ledger, "_layout_budget", side_effect=interleave):
            self.intake([path])
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_a")), 1)
        self.assertNotEqual(self.ledger.result("board")["revision"], before["revision"])
        self.assertEqual(len(list((self.store / "images").iterdir())), 2)

    def test_crash_orphan_image_count_limit_refuses_before_writes(self):
        self.intake()
        source = self.photo(view="orphan").read_bytes()
        existing = self.ledger.get("board")["photos"][0]["sha256"]
        for number in range(95):
            # Unique original-fixture bytes, retained as hypothetical crash orphans.
            raw = source + str(number).encode("ascii")
            digest = hashlib.sha256(raw).hexdigest()
            self.assertNotEqual(digest, existing)
            (self.store / "images" / (digest + ".bin")).write_bytes(raw)
        before_head = (self.store / "head.json").read_bytes()
        before_names = sorted(path.name for path in (self.store / "images").iterdir())
        with self.assertRaises(PhotoEvidenceError):
            self.intake([self.photo(view="another")])
        self.assertEqual((self.store / "head.json").read_bytes(), before_head)
        self.assertEqual(sorted(path.name for path in (self.store / "images").iterdir()), before_names)
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_a")), 1)

    def test_existing_orphan_next_revision_refuses_before_image_copy(self):
        self.intake()
        revision = int(self.ledger.result("board")["revision"])
        (self.store / "versions" / (str(revision + 1) + ".json")).write_bytes(b"{}\n")
        before_names = sorted(path.name for path in (self.store / "images").iterdir())
        with self.assertRaises(PhotoEvidenceError):
            self.intake([self.photo(view="new")])
        self.assertEqual(sorted(path.name for path in (self.store / "images").iterdir()), before_names)
        self.assertEqual(len(self.ledger.inventory_items(project_id="project_a")), 1)

    def test_existing_writer_lock_does_not_overwrite(self):
        self.intake()
        before = self.ledger.result("board")
        (self.store / "write-lock").mkdir()
        with self.assertRaises(PhotoEvidenceError):
            self.ledger.confirm_quantity("board", 2, reviewer="fixture")
        self.assertEqual(self.ledger.result("board"), before)

    def test_corrected_quantity_and_sharing_history_are_retained(self):
        self.intake()
        self.ledger.confirm_quantity("board", 2, reviewer="fixture", ownership="owned")
        self.ledger.confirm_quantity("board", 1, reviewer="fixture", ownership="borrowed")
        self.ledger.set_sharing("board", scope="equipment", shared_with=["project_b"], reviewer="fixture")
        history = self.ledger.get("board")["history"]
        self.assertEqual(history[-2]["prior_quantity"], 2)
        self.assertEqual(history[-2]["prior_ownership"], "owned")
        self.assertEqual(history[-1]["prior_scope"], "project")

    def test_catalog_has_exact_public_source_revision_and_locator(self):
        for code, row in CATALOG.items():
            self.assertTrue(code.startswith(("P", "945-")))
            self.assertTrue(row[2].startswith(("https://docs.nvidia.com/", "https://developer.nvidia.com/")))
            self.assertTrue(row[3])
            self.assertTrue(row[4])

    def test_original_image_hardlink_is_refused(self):
        path = self.photo()
        target = self.base / "hardlink.png"
        try:
            target.hardlink_to(path)
        except (OSError, NotImplementedError):
            self.skipTest("Filesystem does not support fixture hardlinks")
        with self.assertRaises(PhotoEvidenceError):
            self.intake([target])

    def test_image_symlink_is_refused_when_supported(self):
        path = self.photo()
        target = self.base / "symlink.png"
        try:
            target.symlink_to(path)
        except (OSError, NotImplementedError):
            self.skipTest("Filesystem does not allow fixture symlinks")
        with self.assertRaises(PhotoEvidenceError):
            self.intake([target])

    def test_opt_in_existing_inventory_loader_projects_without_writing_legacy_file(self):
        self.intake()
        self.ledger.confirm_quantity("board", 1, reviewer="fixture", ownership="owned")
        self.review()
        from unittest.mock import patch
        from inventory import equipment
        with patch.object(equipment, "_cfg", return_value={"local_inventory": str(self.base / "absent.json"), "optional_imports": []}):
            value = equipment.load_all(photo_ledger=self.ledger, project_id="project_a")
        self.assertFalse((self.base / "absent.json").exists())
        self.assertEqual(len(value["items"]), 1)
        self.assertEqual(value["items"][0]["photo_status"], "reviewed")
        self.assertEqual(value["items"][0]["quantity"], 1)

    def test_opt_in_existing_inventory_loader_requires_project_scope(self):
        self.intake()
        from inventory import equipment
        from unittest.mock import patch
        with patch.object(equipment, "_cfg", return_value={"local_inventory": str(self.base / "absent.json"), "optional_imports": []}):
            with self.assertRaises(PhotoEvidenceError):
                equipment.load_all(photo_ledger=self.ledger)


if __name__ == "__main__":
    unittest.main()
