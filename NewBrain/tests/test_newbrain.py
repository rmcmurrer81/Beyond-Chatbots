"""Offline tests: mathematical/engineering checks, not biological validation."""
import copy
import hashlib
import json
import math
import shutil
import tempfile
import unittest
from pathlib import Path

import newbrain as nb


class FirstCellTests(unittest.TestCase):
    def setUp(self):
        self.model = nb.load_json(nb.ROOT / nb.MODEL_PATH)
        self.registry = nb.load_json(nb.ROOT / "research/provenance.json")

    def test_source_bytes_match_upstream_git_blob(self):
        data = (nb.ROOT / nb.MODEL_PATH).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        self.assertEqual(blob, "1648ea1f6d51a6151578bca557d2e21a16e51393")

    def test_registry_is_valid(self):
        self.assertIn(nb.MODEL_ID, nb.validate_registry(self.registry))

    def test_duplicate_source_rejected(self):
        self.registry["records"].append(copy.deepcopy(self.registry["records"][0]))
        with self.assertRaises(ValueError):
            nb.validate_registry(self.registry)

    def test_missing_origin_field_rejected(self):
        del self.registry["records"][0]["origin"]
        with self.assertRaises(ValueError):
            nb.validate_registry(self.registry)

    def test_unknown_evidence_rejected(self):
        self.registry["records"][0]["evidence"] = "probably real"
        with self.assertRaises(ValueError):
            nb.validate_registry(self.registry)

    def test_missing_parent_rejected(self):
        self.registry["records"][0]["parents"] = ["missing"]
        with self.assertRaises(ValueError):
            nb.validate_registry(self.registry)

    def test_cyclic_lineage_rejected(self):
        self.registry["records"][0]["parents"] = ["h01"]
        self.registry["records"][1]["parents"] = ["bigbrain"]
        with self.assertRaises(ValueError):
            nb.validate_registry(self.registry)

    def test_changed_source_bytes_rejected(self):
        r = next(r for r in self.registry["records"] if r["id"] == nb.MODEL_ID)
        r["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            nb.validate_registry(self.registry)

    def test_escaping_paths_rejected(self):
        for name in ("../outside.json", "/tmp/outside.json", "C:\\outside.json", "C:outside.json", "..\\outside.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                nb.local_file(nb.ROOT, name)

    def test_zero_current_no_spikes_no_drift(self):
        result = nb.simulate(self.model, [0.0] * 1000)
        self.assertEqual(result["spike_indices"], [])
        self.assertTrue(all(v == 0 for v in result["voltage_relative_V"]))

    def test_negative_current_no_spikes(self):
        result = nb.simulate(self.model, [-1e-10] * 1000)
        self.assertEqual(result["spike_indices"], [])
        self.assertLess(result["voltage_relative_V"][-1], 0)

    def test_reproducible_pulse_spikes(self):
        stimulus = nb.make_stimulus(self.model)
        one = nb.simulate(self.model, stimulus)
        self.assertGreater(len(one["spike_indices"]), 0)
        self.assertEqual(one, nb.simulate(self.model, stimulus))
        self.assertTrue(all(0.1 <= k*self.model["dt"] < 0.4 for k in one["spike_indices"]))

    def test_pulse_length_and_current_units(self):
        s = nb.make_stimulus(self.model)
        self.assertEqual(len(s), 10000)
        self.assertEqual(sum(i != 0 for i in s), 6000)
        self.assertEqual(max(s), 3e-10)
        self.assertEqual(s[1999], 0)
        self.assertEqual(s[2000], 3e-10)
        self.assertEqual(s[7999], 3e-10)
        self.assertEqual(s[8000], 0)

    def test_forward_euler_matches_discrete_solution(self):
        current, n = 1e-10, 500
        result = nb.simulate(self.model, [current] * n)
        g = self.model["coeffs"]["G"] / self.model["R_input"]
        c = self.model["C"] * self.model["coeffs"]["C"]
        q = 1 - self.model["dt"] * g / c
        expected = current/g * (1 - q**n)
        self.assertAlmostEqual(result["voltage_relative_V"][-1], expected, places=14)

    def test_continuous_solution_error_decreases_with_step(self):
        errors = []
        for dt in (5e-5, 2.5e-5):
            c = copy.deepcopy(self.model)
            c["dt"] = dt
            n = round(0.01 / dt)
            g = c["coeffs"]["G"] / c["R_input"]
            cap = c["C"] * c["coeffs"]["C"]
            expected = 1e-10/g * (1 - math.exp(-n*dt*g/cap))
            actual = nb.simulate(c, [1e-10]*n)["voltage_relative_V"][-1]
            errors.append(abs(actual-expected))
        self.assertLess(errors[1], errors[0])
        self.assertLess(errors[0], 2e-5)

    def test_threshold_coefficient_used(self):
        result = nb.simulate(self.model, [0.0])
        self.assertEqual(result["threshold_relative_V"], self.model["th_inf"]*self.model["coeffs"]["th_inf"])

    def test_capacitance_coefficient_used(self):
        first = nb.simulate(self.model, [1e-10])["voltage_relative_V"][0]
        self.model["coeffs"]["C"] = 2
        second = nb.simulate(self.model, [1e-10])["voltage_relative_V"][0]
        self.assertAlmostEqual(first, 2*second)

    def test_spikes_are_gaps_not_fake_waveforms(self):
        r = nb.simulate(self.model, nb.make_stimulus(self.model))
        first = r["spike_indices"][0]
        cut = self.model["spike_cut_length"]
        self.assertTrue(all(v is None for v in r["voltage_relative_V"][first:first+cut]))
        self.assertIsNotNone(r["voltage_relative_V"][first+cut])

    def test_non_glif1_model_rejected(self):
        self.model["AScurrent_dynamics_method"]["name"] = "exp"
        with self.assertRaises(ValueError):
            nb.simulate(self.model, [0.0])

    def test_invalid_parameters_rejected(self):
        for name, value in (("C", 0), ("R_input", -1), ("dt", float("nan")), ("dt", 1), ("C", True), ("spike_cut_length", -1)):
            model = copy.deepcopy(self.model)
            model[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                nb.simulate(model, [0.0])

    def test_invalid_input_rejected(self):
        for s in ([], [float("nan")], [float("inf")], [True], [300], [0.0]*200001):
            with self.subTest(length=len(s)), self.assertRaises(ValueError):
                nb.simulate(self.model, s)

    def test_ledger_is_regenerated_exactly(self):
        actual = (nb.ROOT / "SOURCE_LEDGER.md").read_text(encoding="utf-8")
        self.assertEqual(actual, nb.ledger_text(self.registry))

    def test_end_to_end_receipt_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = {"research/provenance.json"}
            names.update(
                r["local_path"]
                for r in self.registry["records"]
                if r.get("local_path")
            )
            for name in sorted(names):
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(nb.ROOT / name, dest)
            output = nb.run_experiment(root)
            receipt = nb.load_json(output / "receipt.json")
            self.assertFalse(receipt["human_recording_compared"])
            self.assertIsNone(receipt["biological_accuracy_metric"])
            self.assertTrue(receipt["controls"]["repeat_identical"])
            self.assertEqual(receipt["trace_sha256"], nb.digest(output / "trace.csv"))
            self.assertTrue((output / "report.html").is_file())
            self.assertNotEqual(output, nb.run_experiment(root))


if __name__ == "__main__":
    unittest.main()
