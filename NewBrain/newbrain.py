"""NewBrain: offline, source-traceable GLIF1 engineering experiment (Python 3.10+)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import platform
import re
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

from evidence_vocabulary import DESCRIPTIVE_EVIDENCE_V1, REGISTRY_EVIDENCE_VOCABULARY_VERSION

ROOT = Path(__file__).resolve().parent
VERSION = "0.1.0"
MODEL_ID = "allen-human-488386504-glif1"
MODEL_PATH = "data/reference/allen_488386504_glif1.json"
EVIDENCE = {"measured", "source-derived", "inferred", "synthetic", "reference-only"}
# Metadata vocabulary recognition is independent of scientific/model validation.
REGISTRY_EVIDENCE = EVIDENCE | DESCRIPTIVE_EVIDENCE_V1
METHODS = {
    "voltage_dynamics_method": "linear_forward_euler",
    "threshold_dynamics_method": "inf",
    "threshold_reset_method": "inf",
    "voltage_reset_method": "zero",
    "AScurrent_dynamics_method": "none",
    "AScurrent_reset_method": "none",
}


def digest(path: Path) -> str:
    """Streaming SHA-256; this records bytes, not just a filename."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 2_000_000:
        raise ValueError("JSON input exceeds the 2 MB starter limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def finite(value: Any, name: str, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"Invalid {name}")
    return float(value)


def local_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name:
        raise ValueError("Missing local path")
    win = PureWindowsPath(name)
    if Path(name).is_absolute() or win.is_absolute() or win.drive or "\\" in name:
        raise ValueError("Only portable relative paths are allowed")
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Path escapes project")
    return result


def validate_registry(registry: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Fail closed on missing lineage, mismatched bytes or invented evidence labels."""
    if registry.get("schema_version") != "1.0":
        raise ValueError("Unsupported provenance schema")
    records = registry.get("records")
    if not isinstance(records, list) or not records:
        raise ValueError("Missing source records")
    ids: set[str] = set()
    needed = {"id", "title", "origin", "url", "evidence", "status", "species",
              "specimen_id", "brain_region", "source_version", "retrieved_on",
              "units", "rights", "transformations", "parents", "local_path",
              "sha256", "limitations"}
    for r in records:
        if not isinstance(r, dict) or not needed <= r.keys():
            raise ValueError("Incomplete provenance record")
        if not isinstance(r["id"], str) or not r["id"] or r["id"] in ids:
            raise ValueError("Duplicate or invalid source ID")
        ids.add(r["id"])
        if not isinstance(r["evidence"], str) or r["evidence"] not in REGISTRY_EVIDENCE:
            raise ValueError("Unknown evidence class")
        if not isinstance(r["parents"], list) or not isinstance(r["units"], dict):
            raise ValueError("Invalid parents or units")
        if not isinstance(r["rights"], dict) or "status" not in r["rights"]:
            raise ValueError("Missing rights status")
        if r["local_path"] is not None:
            path = local_file(root, r["local_path"])
            if not re.fullmatch(r"[0-9a-f]{64}", r["sha256"] or ""):
                raise ValueError("Imported file needs a SHA-256")
            if not path.is_file() or digest(path) != r["sha256"]:
                raise ValueError(f"Source file changed or is missing: {r['id']}")
        elif r["sha256"] is not None:
            raise ValueError("Cannot claim file hash without local file")
    graph = {r["id"]: r["parents"] for r in records}
    visited: set[str] = set()
    active: set[str] = set()
    def visit(key: str) -> None:
        if key not in ids:
            raise ValueError(f"Missing parent source: {key}")
        if key in active:
            raise ValueError("Cyclic source lineage")
        if key in visited:
            return
        active.add(key)
        for parent in graph[key]:
            if not isinstance(parent, str):
                raise ValueError("Parent IDs must be strings")
            visit(parent)
        active.remove(key)
        visited.add(key)
    for key in ids:
        visit(key)
    return sorted(ids)


def validate_model(c: dict[str, Any]) -> None:
    for field, expected in METHODS.items():
        if c.get(field) != {"name": expected, "params": {}}:
            raise ValueError(f"Unsupported model rule: {field}; GLIF1 only")
    for name in ("C", "R_input", "dt", "th_inf"):
        finite(c.get(name), name, positive=True)
    for name in ("El", "El_reference", "init_voltage", "init_threshold"):
        finite(c.get(name), name)
    if c["El"] != 0 or c["init_voltage"] != 0 or c.get("th_adapt") is not None:
        raise ValueError("Starter requires zero-reference GLIF1 without adaptation")
    if c.get("init_AScurrents") != [0.0, 0.0]:
        raise ValueError("Nonzero or unsupported initial afterspike currents")
    for name in ("C", "G", "th_inf"):
        finite(c.get("coeffs", {}).get(name), f"coeffs.{name}", positive=True)
    cut = c.get("spike_cut_length")
    if isinstance(cut, bool) or not isinstance(cut, int) or not 0 <= cut <= 10000:
        raise ValueError("Invalid spike_cut_length")
    tau = c["R_input"] / c["coeffs"]["G"] * c["C"] * c["coeffs"]["C"]
    if c["dt"] > tau / 10:
        raise ValueError("Time step too coarse for starter Euler integration")


def simulate(c: dict[str, Any], stimulus: list[float]) -> dict[str, Any]:
    """Restricted GLIF1 model; no fabricated biological action-potential waveform.

    Euler updates have endpoint times. Crossing sample plus cut-1 subsequent
    samples are marked missing; the next sample resumes from a zero reset.
    This is a documented NewBrain convention, NOT certified AllenSDK parity.
    """
    validate_model(c)
    if not isinstance(stimulus, list) or not 1 <= len(stimulus) <= 200000:
        raise ValueError("Stimulus must contain 1..200000 samples")
    for value in stimulus:
        finite(value, "stimulus in A")
        if abs(value) > 1e-8:
            raise ValueError("Current exceeds the starter +/-10 nA bound")
    dt = c["dt"]
    capacitance = c["C"] * c["coeffs"]["C"]
    conductance = c["coeffs"]["G"] / c["R_input"]
    threshold = c["th_inf"] * c["coeffs"]["th_inf"]
    voltage = c["init_voltage"]
    cut = c["spike_cut_length"]
    skip = 0
    trace: list[float | None] = []
    spikes: list[int] = []
    for k, current in enumerate(stimulus):
        if skip:
            trace.append(None)
            skip -= 1
            continue
        voltage += dt * (current - conductance * (voltage - c["El"])) / capacitance
        if voltage > threshold:
            spikes.append(k)
            trace.append(None)
            voltage = 0.0
            skip = max(0, cut - 1)
        else:
            trace.append(voltage)
    return {"voltage_relative_V": trace, "spike_indices": spikes,
            "threshold_relative_V": threshold, "dt_s": dt,
            "time_convention": "sample k is interval [k*dt,(k+1)*dt); output at interval end"}


def make_stimulus(c: dict[str, Any], amplitude_A: float = 3e-10) -> list[float]:
    finite(amplitude_A, "amplitude")
    dt = c["dt"]
    n = round(0.5 / dt)
    if not 1 <= n <= 200000:
        raise ValueError("Default experiment would exceed sample limit")
    return [amplitude_A if 0.1 <= k * dt < 0.4 else 0.0 for k in range(n)]


def ledger_text(registry: dict[str, Any]) -> str:
    lines = ["# NewBrain source ledger", "", "Generated from `research/provenance.json`.",
             "Do not edit this view alone: update the registry, then run `python newbrain.py ledger`.",
             "", "## What is actually present", "",
             "One source-provided HUMAN GLIF1 parameter file is included. It is a fitted cell model, not a brain scan.",
             "No human recording, full brain scan, synapse map, or cross-donor circuit has been imported.",
             "Pulse input and control inputs are synthetic. Outputs are simulations, not measured tissue activity.",
             "The first measured-versus-model comparison remains pending.", "",
             "## Attribution records", ""]
    for r in registry["records"]:
        lines += [f"### {r['id']} — {r['title']}", "",
                  f"- Origin: {r['origin']}", f"- Source: {r['url'] or 'Created within NewBrain'}",
                  f"- Status / evidence: {r['status']} / {r['evidence']}",
                  f"- Species: {r['species'] or 'Not applicable / unknown'}; specimen: {r['specimen_id'] or 'Not supplied'}",
                  f"- Brain region: {r['brain_region'] or 'Not verified; not guessed'}",
                  f"- Version / retrieval date: {r['source_version'] or 'Not pinned'} / {r['retrieved_on'] or 'Not retrieved'}",
                  f"- Units: {json.dumps(r['units'], sort_keys=True)}",
                  f"- Parents: {', '.join(r['parents']) or 'None'}",
                  f"- Local file: {r['local_path'] or 'Not imported'}",
                  f"- SHA-256: {r['sha256'] or 'Not applicable; no local source bytes'}",
                  f"- Rights: {r['rights']['status']}; {r['rights'].get('note', '')}",
                  f"- Transformations: {'; '.join(r['transformations']) or 'None'}",
                  f"- Limitations: {'; '.join(r['limitations'])}", ""]
    lines += ["## Rules for combining future sources", "",
              "Keep specimen IDs separate. Coordinate registration never implies neuron identity between donors.",
              "Every resampling, cropping, parameter fit or inferred connection must create a derived record with parent IDs.",
              "Record species, region, coordinate frame, resolution, units, software version, settings, rights and hashes.",
              "Unknown fields remain null. Never relabel a generated connection or a simulated trace as measured.",
              "An origin record establishes traceability, not scientific correctness or permission for every use.", ""]
    return "\n".join(lines)


def html_report(c: dict[str, Any], result: dict[str, Any], receipt: dict[str, Any]) -> str:
    width, height = 900, 260
    dt = c["dt"]
    trace = result["voltage_relative_V"]
    # Separate polylines at spikes: do not invent a spike waveform across gaps.
    segments, current = [], []
    for k, value in enumerate(trace):
        if value is None:
            if current:
                segments.append(current)
                current = []
            continue
        if k % 5 == 0 or k == len(trace) - 1:
            x = 55 + (width - 80) * (k + 1) / len(trace)
            absolute_mV = (value + c["El_reference"]) * 1000
            y = 20 + (height - 65) * (-45 - absolute_mV) / 45
            current.append(f"{x:.2f},{y:.2f}")
    if current:
        segments.append(current)
    polylines = ''.join('<polyline fill="none" stroke="currentColor" points="' + ' '.join(s) + '"/>' for s in segments)
    summary = html.escape(json.dumps(receipt, indent=2))
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NewBrain first-cell experiment</title><style>body{{font:17px system-ui;max-width:960px;margin:2rem auto;padding:0 1rem;line-height:1.6}}svg{{width:100%;height:auto;border:1px solid}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;border:1px solid}}.status{{padding:1rem;border:2px solid}}h1{{line-height:1.2}}</style>
<h1>NewBrain · First human-cell model</h1><p class="status"><strong>REAL SOURCE PARAMETERS · SYNTHETIC INPUT · SIMULATED OUTPUT</strong><br>
Allen specimen 488386504, GLIF1. This is an engineering test, not a whole brain or a biological-recording comparison.</p>
<h2>What ran</h2><p>A 300 pA pulse from 100 to 400 ms in a 500 ms simulation at a 0.05 ms step.
Simulated spikes: <strong>{len(result['spike_indices'])}</strong>. No-input control spikes: <strong>{receipt['controls']['zero_current_spikes']}</strong>.
Input current, voltage and spike flags are saved in trace.csv. Model-generated spikes are events; missing curve sections are deliberately not filled with invented waveforms.</p>
<h2>Simulated membrane voltage</h2><p>Vertical range −90 to −45 mV; horizontal range 0–500 ms. Display thins samples only; CSV retains every time step.</p>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="Simulated voltage, not a measured recording"><text x="5" y="23">−45</text><text x="5" y="220">−90</text><text x="55" y="250">0 ms</text><text x="820" y="250">500 ms</text>{polylines}</svg>
<h2>Where it came from</h2><p>Source: <a href="{html.escape(receipt["model_source_url"], quote=True)}">Allen Institute, human specimen 488386504 GLIF1 archive</a>.
The source JSON's Git blob fingerprint was matched to Allen's published file; original parameter values were preserved.
The runner applies the published capacitance, conductance and threshold coefficients. It uses NewBrain's explicitly documented event timing, not an independently certified AllenSDK reproduction.</p>
<h2>Not completed</h2><p>No paired biological sweep was imported or compared. No learning, connectivity, consciousness or personal-memory result is claimed.
The live Allen data endpoint was not reachable from the development runtime. This run uses the small parameter file retrieved from Allen's official GitHub research archive.</p>
<h2>Run receipt</h2><pre>{summary}</pre></html>'''


def run_experiment(root: Path = ROOT) -> Path:
    registry = load_json(root / "research/provenance.json")
    validate_registry(registry, root)
    selected = next(r for r in registry["records"] if r["id"] == MODEL_ID)
    if selected["species"] != "Homo sapiens" or selected["evidence"] != "source-derived":
        raise ValueError("Selected record is not the declared human source-derived model")
    c = load_json(local_file(root, selected["local_path"]))
    started = time.perf_counter()
    tracemalloc.start()
    stimulus = make_stimulus(c)
    result = simulate(c, stimulus)
    sham = simulate(c, [0.0] * len(stimulus))
    repeat = simulate(c, stimulus)
    negative = simulate(c, make_stimulus(c, -1e-10))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    seconds = time.perf_counter() - started
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / "runs" / stamp
    output.mkdir(parents=True, exist_ok=False)
    csv_path = output / "trace.csv"
    spike_set = set(result["spike_indices"])
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_endpoint_s", "stimulus_A", "voltage_relative_V", "voltage_absolute_V", "spike_event"])
        for k, value in enumerate(result["voltage_relative_V"]):
            writer.writerow([(k+1)*c["dt"], stimulus[k], "" if value is None else value,
                             "" if value is None else value+c["El_reference"], int(k in spike_set)])
    receipt = {"run_id": stamp, "newbrain_version": VERSION,
               "method": "newbrain-restricted-glif1-forward-euler", "reference_sdk_parity_verified": False,
               "model_source_id": MODEL_ID, "model_source_url": selected["url"],
               "model_source_version": selected["source_version"], "stimulus_source_id": "newbrain-pulse-v1",
               "parents": [MODEL_ID, "newbrain-pulse-v1"], "output_evidence": "simulated",
               "human_recording_compared": False, "biological_accuracy_metric": None,
               "model_sha256": digest(root / MODEL_PATH),
               "registry_sha256": digest(root / "research/provenance.json"),
               "runner_sha256": digest(Path(__file__)), "trace_sha256": digest(csv_path),
               "parameters": c, "stimulus": {"kind": "synthetic_square_current", "amplitude_A": 3e-10,
               "start_s": 0.1, "end_s": 0.4, "duration_s": 0.5},
               "units": {"time": "s", "voltage": "V", "current": "A", "capacitance": "F", "resistance": "ohm"},
               "sample_count": len(stimulus), "time_convention": result["time_convention"],
               "simulated_spike_count": len(spike_set),
               "controls": {"zero_current_spikes": len(sham["spike_indices"]),
                            "negative_current_spikes": len(negative["spike_indices"]),
                            "repeat_identical": result == repeat},
               "random_seed": None, "randomness": "none; deterministic",
               "python": sys.version, "platform": platform.platform(),
               "elapsed_simulation_and_controls_s": seconds, "peak_python_allocations_bytes": peak,
               "memory_note": "tracemalloc allocations, not total process RAM or a PC requirement"}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    (output / "report.html").write_text(html_report(c, result, receipt), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "ledger", "run"], nargs="?", default="run")
    args = parser.parse_args()
    try:
        registry = load_json(ROOT / "research/provenance.json")
        ids = validate_registry(registry)
        if args.command == "check":
            validate_model(load_json(ROOT / MODEL_PATH))
            print(f"Validated {len(ids)} source records and model bytes. No biological comparison implied.")
        elif args.command == "ledger":
            (ROOT / "SOURCE_LEDGER.md").write_text(ledger_text(registry), encoding="utf-8")
            print("Updated SOURCE_LEDGER.md")
        else:
            output = run_experiment()
            print(f"Complete: {output / 'report.html'}\nSynthetic stimulus; biological comparison pending.")
    except (ValueError, OSError, KeyError, StopIteration, TypeError) as exc:
        print(f"NewBrain stopped: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
