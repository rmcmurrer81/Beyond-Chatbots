"""Small real-file local bundle fixtures; execution UNRUN at publication."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from core.ideaforge_bundles import export_parameter_link, export_reviewed_result, PHOTO_SCHEMA
from core.research_bundle import BundleError
import test_parameter_links as fixtures


class IdeaBundleTests(unittest.TestCase):
    setUp = fixtures.ParameterLinkTests.setUp
    project = fixtures.ParameterLinkTests.project
    import_source = fixtures.ParameterLinkTests.import_source
    request = fixtures.ParameterLinkTests.request
    create = fixtures.ParameterLinkTests.create
    receipt = fixtures.ParameterLinkTests.receipt

    def export(self, name="selected_bundle"):
        result = self.create()
        return export_parameter_link(self.root, result["link_id"], name,
                                     producer_revision="synthetic-source-review-unpinned", test_only=True)

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_exact_local_bundle_hashes_and_unrun_receipt(self):
        path = self.export()
        bundle = self.read(path)
        self.assertEqual(set(bundle), {"format", "recipient", "app_id", "project_id",
                                      "revision", "artifacts", "inputs", "tests"})
        self.assertEqual(bundle["format"], "aster.research-bundle.v1")
        self.assertEqual(bundle["app_id"], "ideaforge")
        self.assertEqual(bundle["project_id"], self.root.name)
        self.assertEqual(bundle["revision"], self.revision)
        wrapper = self.read(path.parent / bundle["artifacts"][0]["path"])
        self.assertTrue(wrapper["provenance"]["test_only"])
        for entry in bundle["artifacts"] + bundle["inputs"]:
            raw = (path.parent / entry["path"]).read_bytes()
            self.assertEqual(entry["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(entry["bytes"], len(raw))
        test = bundle["tests"][0]
        self.assertEqual(test["status"], "unrun")
        receipt = self.read(path.parent / test["receipt_path"])
        self.assertEqual(receipt["status"], "unrun")
        self.assertIn("No reviewed link-bound test receipt", receipt["details"])
        self.assertEqual(receipt["artifact_sha256s"],
                         {e["id"]: e["sha256"] for e in bundle["artifacts"]})

    def test_export_redacts_full_passage_filename_root_and_reviewer(self):
        path = self.export()
        payload = "\n".join(p.read_text() for p in path.parent.rglob("*.json"))
        self.assertNotIn(self.row["passage"], payload)
        self.assertNotIn("self-authored-manual.pdf", payload)
        self.assertNotIn("Synthetic test reviewer", payload)
        self.assertNotIn(self.ledger.root_binding, payload)
        self.assertNotIn(str(self.root), payload)
        artifact = self.read(path.parent / self.read(path)["artifacts"][0]["path"])
        result = artifact["result"]
        self.assertFalse(result["original_pdf_bytes_in_bundle"])
        self.assertEqual(result["pdf_source_verification"], "unavailable")
        self.assertEqual(result["selected_quote"]["quote"], "120 mm")
        self.assertEqual(result["source"]["bbox"], self.row["bbox"])
        self.assertEqual(result["source"]["source_sha256"], self.row["source_sha256"])

    def test_included_input_metadata_hash_is_distinct_from_pdf_hash(self):
        path = self.export()
        bundle = self.read(path)
        input_record = bundle["inputs"][0]
        raw = (path.parent / input_record["path"]).read_bytes()
        self.assertNotEqual(input_record["sha256"], self.row["source_sha256"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), input_record["sha256"])
        self.assertEqual(json.loads(raw)["source"]["source_sha256"], self.row["source_sha256"])

    def test_stale_source_export_preserves_declared_receipt_and_staleness(self):
        link = self.create()["link_id"]
        self.ledger.attach_test_receipt(link, self.receipt(link, status="passed"))
        self.import_source("Reviewed base dimension 140 mm.", b"%PDF- replaced",
                           source_id=self.ingested["source_id"])
        path = export_parameter_link(self.root, link, "stale_bundle", producer_revision="synthetic", test_only=True)
        bundle = self.read(path)
        artifact = self.read(path.parent / bundle["artifacts"][0]["path"])
        self.assertEqual(artifact["status"], "stale")
        self.assertEqual(bundle["tests"][0]["status"], "passed")
        receipt = self.read(path.parent / bundle["tests"][0]["receipt_path"])
        self.assertIn("Evidence status: stale", receipt["details"])
        self.assertIn("did not independently run", receipt["details"])

    def test_no_design_or_input_mutation_and_no_second_overwrite(self):
        before = self.store.revision()
        snapshot = self.root / "research/pdf_evidence/sources" / (self.row["source_sha256"]+".pdf")
        raw = snapshot.read_bytes()
        path = self.export()
        with self.assertRaises(BundleError):
            self.export()
        self.assertEqual(self.store.revision(), before)
        self.assertEqual(snapshot.read_bytes(), raw)
        self.assertTrue(path.is_file())

    def test_photo_metadata_only_export_and_image_verification_unavailable(self):
        result = {"project_id": self.root.name, "revision": "1", "status": "reviewed",
                  "item_id": "synthetic_motor", "quantity": 1,
                  "original_image_bytes_in_bundle": False,
                  "image_verification": "unavailable",
                  "photos": [{"sha256": "1"*64, "bytes": 100, "media_type": "image/png"}]}
        path = export_reviewed_result(self.root, "photo_bundle", schema=PHOTO_SCHEMA,
            result=result, producer_revision="synthetic", test_only=True,
            tests=[{"id": "photo_unrun", "status": "unrun", "details": "Synthetic fixture UNRUN."}])
        bundle = self.read(path)
        self.assertEqual(bundle["artifacts"][0]["schema"], PHOTO_SCHEMA)
        self.assertTrue(all(e["media_type"] == "application/json" for e in
                            bundle["artifacts"] + bundle["inputs"]))
        self.assertEqual(self.read(path.parent / bundle["artifacts"][0]["path"])["result"], result)

    def test_photo_original_bytes_or_validation_claim_refused(self):
        for claim in ({"original_image_bytes_in_bundle": True, "image_verification": "unavailable"},
                      {"original_image_bytes_in_bundle": False, "image_verification": "validated"}):
            result = {"project_id": self.root.name, "revision": "1", "status": "reviewed", **claim}
            with self.assertRaises(BundleError):
                export_reviewed_result(self.root, "bad_photo", schema=PHOTO_SCHEMA, result=result,
                    producer_revision="synthetic", test_only=True,
                    tests=[{"id": "unrun", "status": "unrun", "details": "UNRUN"}])
        self.assertFalse((self.root / "bad_photo").exists())

    def test_other_project_result_refused(self):
        result = {"project_id": self.other.name, "revision": "1", "status": "reviewed",
                  "original_image_bytes_in_bundle": False, "image_verification": "unavailable"}
        with self.assertRaises(BundleError):
            export_reviewed_result(self.root, "bad_project", schema=PHOTO_SCHEMA, result=result,
                producer_revision="synthetic", test_only=True,
                tests=[{"id": "unrun", "status": "unrun", "details": "UNRUN"}])

    def test_network_absolute_traversal_device_and_duplicate_tests_refused(self):
        for name in ("../escape", "/absolute", "C:escape", "CON", "bundle/inside", "\\\\host"):
            with self.subTest(name=name), self.assertRaises(BundleError):
                self.export(name)
        result = {"project_id": self.root.name, "revision": "1", "status": "reviewed",
                  "original_image_bytes_in_bundle": False, "image_verification": "unavailable"}
        with self.assertRaises(BundleError):
            export_reviewed_result(self.root, "collision", schema=PHOTO_SCHEMA, result=result,
                producer_revision="synthetic", test_only=True, tests=[
                    {"id": "test", "status": "unrun", "details": "UNRUN"},
                    {"id": "test", "status": "unrun", "details": "UNRUN"}])

    def test_unknown_test_fields_and_empty_or_false_status_refused(self):
        result = {"project_id": self.root.name, "revision": "1", "status": "reviewed",
                  "original_image_bytes_in_bundle": False, "image_verification": "unavailable"}
        for tests in ([], [{"id": "test", "status": "skipped", "details": "UNRUN"}],
                      [{"id": "test", "status": "unrun", "details": "UNRUN", "executed": True}]):
            with self.subTest(tests=tests), self.assertRaises(BundleError):
                export_reviewed_result(self.root, "bad_tests", schema=PHOTO_SCHEMA, result=result,
                                       producer_revision="synthetic", test_only=True, tests=tests)

    def test_owned_staging_summaries_are_cleaned_on_success_and_late_failure(self):
        self.export()
        folder = self.root / "research/result_inputs"
        self.assertEqual(list(folder.iterdir()), [])
        result = {"project_id": self.root.name, "revision": "1", "status": "reviewed",
                  "original_image_bytes_in_bundle": False, "image_verification": "unavailable"}
        with self.assertRaises(BundleError):
            export_reviewed_result(self.root, "late_collision", schema=PHOTO_SCHEMA, result=result,
                producer_revision="synthetic", test_only=True, tests=[
                    {"id": "test", "status": "unrun", "details": "UNRUN"},
                    {"id": "test", "status": "unrun", "details": "UNRUN"}])
        self.assertEqual(list(folder.iterdir()), [])

    def test_case_sensitive_ids_have_distinct_portable_payload_paths(self):
        result = {"project_id": self.root.name, "revision": "1", "status": "reviewed",
                  "original_image_bytes_in_bundle": False, "image_verification": "unavailable"}
        path = export_reviewed_result(self.root, "case_ids", schema=PHOTO_SCHEMA, result=result,
            producer_revision="synthetic", test_only=True, tests=[
                {"id": "test", "status": "unrun", "details": "UNRUN"},
                {"id": "Test", "status": "unrun", "details": "UNRUN"}])
        bundle = self.read(path)
        self.assertEqual([t["id"] for t in bundle["tests"]], ["test", "Test"])
        paths = [t["receipt_path"].casefold() for t in bundle["tests"]]
        self.assertEqual(len(set(paths)), 2)


if __name__ == "__main__":
    unittest.main()
