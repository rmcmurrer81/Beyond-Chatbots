"""Bounded local exports using self-authored JSON/text fixtures only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core.research_bundle as bundle_module

from core.research_bundle import (
    BundleError, MAX_FILE, export_bundle, read_verified_input)


class ResearchBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        raw = b'{"project_id":"project-A","source":"self-authored fixture"}\n'
        (self.root / "source.json").write_bytes(raw)
        self.input = {"id": "source", "path": "source.json",
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "media_type": "application/json"}
        self.args = {
            "app_id": "humanoidresearcher", "project_id": "project-A",
            "revision": "revision-1",
            "results": [{"id": "comparison",
                "schema": "humanoidresearcher.assembly-compatibility.v1",
                "status": "unknown", "result": {"project_id": "project-A",
                    "revision": "revision-1", "status": "unknown",
                    "hardware_feasibility": "unknown"}}],
            "inputs": [self.input],
            "tests": [{"id": "focused", "status": "unrun",
                "artifact_ids": ["comparison"], "input_ids": ["source"],
                "details": "UNRUN: fixture declares executor unavailable."}],
            "provenance": {"origin": "self-authored local fixture",
                "producer_revision": "source-fixture-r1", "model": "none",
                "test_only": True},
        }

    def export(self, destination="export", **updates):
        return export_bundle(self.root, destination, **{**self.args, **updates})

    def test_manifest_receipts_and_all_actual_hashes_are_bound(self):
        original = (self.root / "source.json").read_bytes()
        path = self.export()
        bundle = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(bundle), {"format", "recipient", "app_id", "project_id",
            "revision", "artifacts", "inputs", "tests"})
        self.assertEqual(bundle["format"], "aster.research-bundle.v1")
        self.assertEqual(bundle["recipient"], "aster")
        for descriptor in bundle["inputs"] + bundle["artifacts"]:
            raw = (path.parent / descriptor["path"]).read_bytes()
            self.assertEqual(len(raw), descriptor["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), descriptor["sha256"])
        test = bundle["tests"][0]
        raw = (path.parent / test["receipt_path"]).read_bytes()
        receipt = json.loads(raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), test["receipt_sha256"])
        self.assertEqual(len(raw), test["receipt_bytes"])
        self.assertEqual(receipt["artifact_sha256s"],
                         {"comparison": bundle["artifacts"][0]["sha256"]})
        self.assertEqual(receipt["input_sha256s"], {"source": self.input["sha256"]})
        self.assertEqual(receipt["status"], "unrun")
        self.assertEqual((self.root / "source.json").read_bytes(), original)

    def test_source_replacement_hash_mismatch_is_refused(self):
        (self.root / "source.json").write_bytes(b'{"changed":true}\n')
        with self.assertRaises(BundleError):
            self.export()
        self.assertFalse((self.root / "export").exists())

    def test_project_or_revision_mismatch_cannot_be_exported(self):
        for key, value in (("project_id", "other"), ("revision", "other")):
            with self.subTest(key=key):
                args = copy.deepcopy(self.args)
                args["results"][0]["result"][key] = value
                with self.assertRaises(BundleError):
                    export_bundle(self.root, "export", **args)

    def test_input_with_other_project_is_refused(self):
        raw = b'{"project_id":"other-project"}'
        (self.root / "source.json").write_bytes(raw)
        self.input.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        with self.assertRaises(BundleError):
            self.export()

    def test_restart_keeps_exported_snapshots_and_prevents_overwrite(self):
        path = self.export()
        before = {p.relative_to(path.parent): p.read_bytes()
                  for p in path.parent.rglob("*") if p.is_file()}
        (self.root / "source.json").write_bytes(b'{"replacement":true}')
        with self.assertRaises(BundleError):
            self.export()
        self.assertEqual(before, {p.relative_to(path.parent): p.read_bytes()
                  for p in path.parent.rglob("*") if p.is_file()})

    def test_traversal_absolute_ads_backslash_device_and_deep_paths_refused(self):
        for name in ("../source.json", "/source.json", "C:/source.json",
                     "dir\\source.json", "source.json:ads", "CON.json", "COM0.json", "LPT0.txt",
                     "dir/../source.json", "./source.json", "source.json.",
                     "a/b/c/d/e/f/g/h/source.json"):
            with self.subTest(path=name):
                entry = {**self.input, "path": name}
                with self.assertRaises(BundleError):
                    self.export(inputs=[entry])

    def test_duplicate_fields_unknown_fields_and_nonfinite_json_refused(self):
        for raw in (b'{"a":1,"a":2}', b'{"x":NaN}', b"\xff",
                    b'{"x":"' + b"a" * 16385 + b'"}',
                    b"[" * 17 + b"0" + b"]" * 17):
            with self.subTest(raw=raw[:20]):
                (self.root / "source.json").write_bytes(raw)
                entry = {**self.input, "sha256": hashlib.sha256(raw).hexdigest(),
                         "bytes": len(raw)}
                with self.assertRaises(BundleError):
                    self.export(inputs=[entry])
        with self.assertRaises(BundleError):
            self.export(inputs=[{**self.input, "extra": True}])

    def test_distinct_case_ids_keep_unique_payload_names(self):
        results = [self.args["results"][0],
                   {**self.args["results"][0], "id": "Comparison"}]
        path = self.export(results=results)
        bundle = json.loads(path.read_bytes())
        self.assertEqual([r["id"] for r in bundle["artifacts"]], ["comparison", "Comparison"])
        self.assertEqual(len({r["path"].casefold() for r in bundle["artifacts"]}), 2)

    def test_duplicate_receipt_references_are_refused(self):
        tests = [{**self.args["tests"][0], "artifact_ids": ["comparison", "comparison"]}]
        with self.assertRaises(BundleError):
            self.export(tests=tests)

    def test_full_length_ids_use_short_deterministic_payload_names(self):
        identity = "a" * 64
        result = {**self.args["results"][0], "id": identity}
        entry = {**self.input, "id": identity}
        test = {**self.args["tests"][0], "id": identity,
                "artifact_ids": [identity], "input_ids": [identity]}
        path = self.export(results=[result], inputs=[entry], tests=[test])
        bundle = json.loads(path.read_bytes())
        self.assertEqual(bundle["artifacts"][0]["id"], identity)
        self.assertEqual(bundle["inputs"][0]["id"], identity)
        self.assertEqual(bundle["tests"][0]["id"], identity)
        self.assertEqual(bundle["artifacts"][0]["path"], "artifacts/result-01.json")
        self.assertEqual(bundle["inputs"][0]["path"], "inputs/input-01.json")
        self.assertEqual(bundle["tests"][0]["receipt_path"], "receipts/test-01.json")

    def test_json_node_budget_counts_object_keys_and_values(self):
        raw = json.dumps({f"k{i}": i for i in range(5000)}).encode("utf-8")
        (self.root / "source.json").write_bytes(raw)
        entry = {**self.input, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        with self.assertRaises(BundleError):
            self.export(inputs=[entry])

    def test_unsupported_status_or_unresolved_receipt_reference_refused(self):
        for test in (
            {**self.args["tests"][0], "status": "skipped"},
            {**self.args["tests"][0], "artifact_ids": ["missing"]},
            {**self.args["tests"][0], "input_ids": ["missing"]},
            {**self.args["tests"][0], "details": ""},
        ):
            with self.subTest(test=test):
                with self.assertRaises(BundleError):
                    self.export(tests=[test])

    def test_malformed_membership_types_raise_bundle_errors(self):
        for key, value in (("app_id", []), ("app_id", {})):
            with self.subTest(key=key, value=value):
                with self.assertRaises(BundleError):
                    self.export(**{key: value})
        for value in ([], {}):
            with self.subTest(value=value):
                with self.assertRaises(BundleError):
                    self.export(inputs=[{**self.input, "media_type": value}])
                with self.assertRaises(BundleError):
                    self.export(results=[{**self.args["results"][0], "schema": value}])
                with self.assertRaises(BundleError):
                    self.export(tests=[{**self.args["tests"][0], "status": value}])

    def test_c0_and_c1_controls_are_rejected_in_json_and_plain_text(self):
        for control in ("\x01", "\x7f", "\x80", "\x9f"):
            with self.subTest(control=ord(control)):
                for media, raw in (
                    ("application/json", json.dumps({"text": control}).encode("utf-8")),
                    ("text/plain", ("source" + control).encode("utf-8")),
                ):
                    (self.root / "source.json").write_bytes(raw)
                    entry = {**self.input, "media_type": media,
                        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                    with self.assertRaises(BundleError):
                        self.export(inputs=[entry])

    def test_multiline_text_and_details_keep_tab_cr_lf(self):
        raw = b"line one\tvalue\r\nline two\n"
        (self.root / "source.json").write_bytes(raw)
        entry = {**self.input, "media_type": "text/plain",
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        tests = [{**self.args["tests"][0], "details": "UNRUN:\nno runner\tavailable\r\n"}]
        path = self.export(inputs=[entry], tests=tests)
        bundle = json.loads(path.read_bytes())
        self.assertEqual((path.parent / bundle["inputs"][0]["path"]).read_bytes(), raw)
        with self.assertRaises(BundleError):
            self.export("scope-error", project_id="project-A\n")

    def test_changed_output_parent_is_rejected_before_write(self):
        original = bundle_module._write_output
        changed = [False]
        def replace_parent(project, identity, destination, directories, relative, raw):
            if not changed[0]:
                changed[0] = True
                (destination / "inputs").rename(destination / "replaced-inputs")
                (destination / "inputs").mkdir()
            return original(project, identity, destination, directories, relative, raw)
        with patch.object(bundle_module, "_write_output", side_effect=replace_parent):
            with self.assertRaises(BundleError):
                self.export()
        self.assertFalse((self.root / "export" / "bundle.json").exists())

    def test_output_hardlink_is_rejected_during_readback(self):
        original = bundle_module._verify_output
        linked = [False]
        def add_link(project, identity, destination, directories, relative, raw, expected=None):
            if not linked[0]:
                linked[0] = True
                try:
                    os.link(destination / relative, destination / "extra-link.txt")
                except OSError as exc:
                    self.skipTest(f"hard-link fixture unavailable: {exc}")
            return original(project, identity, destination, directories, relative, raw, expected)
        with patch.object(bundle_module, "_verify_output", side_effect=add_link):
            with self.assertRaises(BundleError):
                self.export()
        self.assertFalse((self.root / "export" / "bundle.json").exists())

    def test_photo_metadata_keeps_original_image_verification_unavailable(self):
        result = {"id": "photo",
            "schema": "humanoidresearcher.reviewed-photo-inventory.v1",
            "status": "reviewed", "result": {"project_id": "project-A",
                "revision": "revision-1", "status": "reviewed",
                "original_image_bytes_in_bundle": False,
                "image_verification": "unavailable",
                "photos": [{"sha256": "a" * 64, "bytes": 1234,
                            "media_type": "image/png"}]}}
        tests = [{**self.args["tests"][0], "artifact_ids": ["photo"]}]
        path = self.export(results=[result], tests=tests)
        bundle = json.loads(path.read_bytes())
        wrapper = json.loads((path.parent / bundle["artifacts"][0]["path"]).read_bytes())
        self.assertFalse(wrapper["result"]["original_image_bytes_in_bundle"])
        self.assertEqual(wrapper["result"]["image_verification"], "unavailable")
        result["result"]["original_image_bytes_in_bundle"] = True
        with self.assertRaises(BundleError):
            self.export("other-export", results=[result], tests=tests)

    def test_binary_images_are_never_valid_bundle_inputs(self):
        with self.assertRaises(BundleError):
            self.export(inputs=[{**self.input, "media_type": "image/png"}])

    def test_all_three_registered_apps_use_one_exact_envelope(self):
        for app, schema in (
            ("ideaforge", "ideaforge.reviewed-parameter-link.v1"),
            ("bluebook", "bluebook.reviewed-case-association.v1"),
        ):
            with self.subTest(app=app):
                result = {**self.args["results"][0], "schema": schema}
                path = self.export(app, app_id=app, results=[result])
                bundle = json.loads(path.read_bytes())
                self.assertEqual(bundle["app_id"], app)
                wrapper = json.loads((path.parent / bundle["artifacts"][0]["path"]).read_bytes())
                self.assertEqual(wrapper["format"], schema)
                self.assertEqual(set(wrapper), {"format", "app_id", "project_id",
                    "revision", "status", "provenance", "result"})

    def test_regular_file_hard_links_are_refused(self):
        try:
            os.link(self.root / "source.json", self.root / "alias.json")
        except OSError as exc:
            self.skipTest(f"hard-link fixture unavailable: {exc}")
        with self.assertRaises(BundleError):
            self.export()

    def test_symbolic_link_files_are_refused(self):
        try:
            os.symlink(self.root / "source.json", self.root / "alias.json")
        except OSError as exc:
            self.skipTest(f"symlink fixture unavailable: {exc}")
        with self.assertRaises(BundleError):
            self.export(inputs=[{**self.input, "path": "alias.json"}])

    def test_file_size_and_boolean_byte_counts_are_refused(self):
        for size in (True, 0, MAX_FILE + 1):
            with self.subTest(size=size):
                with self.assertRaises(BundleError):
                    self.export(inputs=[{**self.input, "bytes": size}])

    def test_verified_reader_returns_exact_utf8_source_bytes(self):
        self.assertEqual(read_verified_input(self.root, self.input),
                         (self.root / "source.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
