"""Small source-only proposed metadata compatibility tests; no simulator or experiment call."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

import newbrain as nb
from evidence_vocabulary import DESCRIPTIVE_EVIDENCE_V1, REGISTRY_EVIDENCE_VOCABULARY_VERSION


def record(evidence="source-derived", identifier="source-a", parents=None):
    return {"id": identifier, "title": "Synthetic metadata control", "origin": "Authored test",
            "url": None, "evidence": evidence, "status": "source-only-test",
            "species": None, "specimen_id": None, "brain_region": None,
            "source_version": None, "retrieved_on": None, "units": {},
            "rights": {"status": "test-only"}, "transformations": [],
            "parents": [] if parents is None else parents, "local_path": None,
            "sha256": None, "limitations": ["No model or biological validation."]}


def registry(*records):
    return {"schema_version": "1.0", "records": list(records)}


class RegistryCompatibilityTests(unittest.TestCase):
    def test_version_and_scientific_core_stay_distinct(self):
        self.assertEqual(REGISTRY_EVIDENCE_VOCABULARY_VERSION, "descriptive-evidence-20261007.v1")
        self.assertEqual(nb.EVIDENCE, {"measured", "source-derived", "inferred", "synthetic", "reference-only"})
        self.assertEqual(len(DESCRIPTIVE_EVIDENCE_V1), 56)
        self.assertTrue(nb.EVIDENCE.isdisjoint(DESCRIPTIVE_EVIDENCE_V1))

    def test_core_and_known_descriptions_preserve_original_record(self):
        examples = ("source-derived", "project-authored-source", "saved-actual-diagnostic-metadata",
                    "observed-reporting-failure", "exact-preserved-published-history")
        for evidence in examples:
            r = registry(record(evidence))
            before = copy.deepcopy(r)
            self.assertEqual(nb.validate_registry(r), ["source-a"])
            self.assertEqual(r, before)

    def test_unknown_near_match_and_malformed_evidence_refuse(self):
        examples = ("probably real", "whole-brain-validated", "Measured", "measured ",
                    " project-authored-source", "project-authored-sources", "", None, 1, True, [], {})
        for evidence in examples:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                nb.validate_registry(registry(record(evidence)))

    def test_incomplete_duplicate_and_missing_parent_refuse(self):
        r = record("project-authored-source")
        del r["origin"]
        with self.assertRaises(ValueError):
            nb.validate_registry(registry(r))
        with self.assertRaises(ValueError):
            nb.validate_registry(registry(record(), record()))
        with self.assertRaises(ValueError):
            nb.validate_registry(registry(record("project-authored-source", parents=["missing"])))

    def test_cycle_and_malformed_parents_units_rights_refuse(self):
        with self.assertRaises(ValueError):
            nb.validate_registry(registry(record(identifier="a", parents=["b"]), record(identifier="b", parents=["a"])))
        for field, bad in (("parents", "a"), ("parents", [42]), ("units", []), ("rights", {})):
            r = record("project-authored-source")
            r[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                nb.validate_registry(registry(r))

    def test_null_path_cannot_claim_hash(self):
        r = record("observed-reporting-failure")
        r["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            nb.validate_registry(registry(r))

    def test_real_hash_and_portable_path_guards_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.bin").write_bytes(b"small synthetic source\n")
            r = record("project-authored-source")
            r["local_path"] = "source.bin"
            r["sha256"] = hashlib.sha256((root / "source.bin").read_bytes()).hexdigest()
            self.assertEqual(nb.validate_registry(registry(r), root), ["source-a"])
            (root / "source.bin").write_bytes(b"changed synthetic source\n")
            with self.assertRaises(ValueError):
                nb.validate_registry(registry(r), root)
            for name in ("../outside.bin", "/tmp/outside.bin", "C:\\outside.bin", "C:outside.bin", "..\\outside.bin"):
                r["local_path"] = name
                with self.subTest(path=name), self.assertRaises(ValueError):
                    nb.validate_registry(registry(r), root)


if __name__ == "__main__":
    unittest.main()
