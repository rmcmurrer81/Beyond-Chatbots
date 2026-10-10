"""Explicit local OCR receipt review, isolated from human photo observations.

Nothing imports a vision/text provider. Native OCR is called only by recognize(),
with an explicit qualified configuration and fixed standalone provider policy.
Raw words remain in private receipt files; inventory and bundle results are summaries.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from . import photo_ocr as ocr
from .photo_inventory import (
    APP_ID, MAX_STATE, PhotoEvidenceError, _choice, _decode, _hash, _id,
    _json_bytes, _keys, _positive, _read, _review_sha256, _safe, _scope,
    _string, evaluate,
)

MAX_RECEIPT = 65536
MAX_RECEIPTS = 32
MAX_RECEIPT_TOTAL = MAX_RECEIPT * MAX_RECEIPTS
REVIEW_FORMAT = APP_ID + ".photo-ocr-review.v1"
PROVIDER_APP_ID = "ideaforge"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_NAME = "photo_ocr_config.json"
REVIEW_KEYS = {
    "format", "receipt_sha256", "capture_sha256", "selection_sha256",
    "catalog_sha256", "engine_sha256", "candidate_ids", "reviewer", "expected_subject",
    "confirm_identity", "observed_words_confirmed", "summary", "test_only",
}
REQUEST_KEYS = {
    "expected_revision", "reviewer", "expected_subject", "confirm_identity",
    "observed_words_confirmed", "candidate_ids", "quantity", "ownership",
    "scope", "shared_with",
}


def _fail(message):
    raise PhotoEvidenceError(message)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _private_string(value, maximum=240, *, empty=False):
    _string(value, maximum, empty=empty)
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        _fail("Control characters in OCR review metadata")
    return value


def _strict_policy_json(raw):
    """AI config contains finite decimal settings; no values are executed."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_RECEIPT:
        _fail("Policy JSON byte limit")
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                _fail("Duplicate policy JSON key")
            result[key] = value
        return result
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=lambda _: _fail("Nonfinite policy JSON"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise PhotoEvidenceError("Invalid policy JSON") from exc
    nodes = 0
    def visit(value, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 4096 or depth > 12:
            _fail("Policy JSON structural limit")
        if type(value) is dict:
            if len(value) > 128:
                _fail("Policy object limit")
            for key, child in value.items():
                _private_string(key, 240)
                visit(child, depth + 1)
        elif type(value) is list:
            if len(value) > 128:
                _fail("Policy list limit")
            for child in value:
                visit(child, depth + 1)
        elif type(value) is str:
            _private_string(value, 2048, empty=True)
        elif type(value) is float:
            if not math.isfinite(value):
                _fail("Nonfinite policy number")
        elif type(value) is int:
            if value.bit_length() > 128:
                _fail("Policy integer limit")
        elif value is not None and type(value) is not bool:
            _fail("Unsupported policy scalar")
    visit(result)
    if type(result) is not dict:
        _fail("Policy JSON object required")
    return result


def _source_root(*, allow_test_only=False, _policy_root=None):
    if type(allow_test_only) is not bool:
        _fail("Invalid test-only choice")
    if _policy_root is not None and not allow_test_only:
        _fail("Production policy/configuration paths are fixed")
    return _safe(SOURCE_ROOT if _policy_root is None else _policy_root)


def _selection_unchecked(root):
    """Require actual files; missing selection never defaults to standalone."""
    provider_raw = _read(root / "ai_provider.json", MAX_RECEIPT)
    provider = _strict_policy_json(provider_raw)
    _keys(provider, {"protocol", "provider", "app_id", "revision"})
    if (provider["protocol"], provider["provider"], provider["app_id"]) != (
            "aster.provider.selection.v1", "standalone", PROVIDER_APP_ID):
        _fail("Local OCR requires this app's explicit standalone selection")
    _positive(provider["revision"], 2**63 - 1)
    ai_raw = _read(root / "ai" / "config.json", MAX_RECEIPT)
    ai = _strict_policy_json(ai_raw)
    if type(ai.get("language_model")) is not dict:
        _fail("AI configuration lacks explicit language-model selection")
    for field in ("provider", "model"):
        _private_string(ai["language_model"].get(field), 240)
    config_raw = _read(root / CONFIG_NAME, MAX_RECEIPT)
    try:
        config = ocr.load_config(config_raw)
    except (ValueError, TypeError) as exc:
        raise PhotoEvidenceError("Invalid local OCR configuration") from exc
    return config, {
        "provider_selection_sha256": _digest(provider_raw),
        "ai_config_sha256": _digest(ai_raw),
        "selection_sha256": _digest(config_raw),
    }, config_raw

def _selection(root):
    try:
        return _selection_unchecked(root)
    except OSError as exc:
        raise ocr.OcrUnavailable("Required explicit local policy/OCR configuration is unavailable") from exc


def _capture_locked(ledger, item_id, state, selection):
    return ledger._capture_locked(
        item_id, state,
        provider_selection_sha256=selection["provider_selection_sha256"],
        ai_config_sha256=selection["ai_config_sha256"])


def capture(ledger, item_id, *, allow_test_only=False, _policy_root=None):
    """Capture immutable bytes/review bindings; no image is decoded or executed."""
    root = _source_root(allow_test_only=allow_test_only, _policy_root=_policy_root)
    with ledger._writer():
        _, selection, _ = _selection(root)
        return _capture_locked(ledger, item_id, ledger._load(), selection)


def receipt_budget(ledger):
    directory = _safe(ledger.root / "ocr_receipts")
    if not directory.exists():
        return {"count": 0, "bytes": 0}
    if not directory.is_dir():
        _fail("OCR receipt directory is not a directory")
    count = total = 0
    with os.scandir(directory) as rows:
        for row in rows:
            count += 1
            if count > MAX_RECEIPTS:
                _fail("OCR receipt count budget")
            path = _safe(row.path)
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not row.name.endswith(".json") or len(row.name) != 69):
                _fail("Invalid private OCR receipt entry")
            _hash(row.name[:-5])
            if not 1 <= info.st_size <= MAX_RECEIPT:
                _fail("OCR receipt byte budget")
            total += info.st_size
    if total > MAX_RECEIPT_TOTAL:
        _fail("Total private OCR receipt budget")
    return {"count": count, "bytes": total}


def _receipt(ledger, digest):
    digest = _hash(digest)
    raw = _read(ledger.root / "ocr_receipts" / (digest + ".json"), MAX_RECEIPT)
    if _digest(raw) != digest:
        _fail("Private OCR receipt hash mismatch")
    try:
        value = ocr.decode_json(raw, max_bytes=MAX_RECEIPT)
        if ocr.receipt_bytes(value) != raw:
            _fail("Noncanonical OCR receipt")
    except (ValueError, TypeError, KeyError) as exc:
        raise PhotoEvidenceError("Invalid private OCR receipt") from exc
    return value


def _save_receipt_locked(ledger, receipt):
    """Immutable create, no overwrite; an interrupted orphan needs manual recovery."""
    raw = ocr.receipt_bytes(receipt)
    if not 1 <= len(raw) <= MAX_RECEIPT:
        _fail("OCR receipt byte limit")
    digest = _digest(raw)
    directory = _safe(ledger.root / "ocr_receipts")
    directory.mkdir(exist_ok=True)
    target = _safe(directory / (digest + ".json"))
    budget = receipt_budget(ledger)
    if target.exists():
        if _read(target, MAX_RECEIPT) != raw:
            _fail("Existing private OCR receipt differs")
        return digest
    if budget["count"] >= MAX_RECEIPTS or budget["bytes"] + len(raw) > MAX_RECEIPT_TOTAL:
        _fail("Private OCR receipt quota exceeded")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("Invalid new OCR receipt handle")
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if _read(target, MAX_RECEIPT) != raw:
            _fail("Private OCR receipt readback mismatch")
    finally:
        os.close(fd)
    return digest


def _validated(receipt, capture_value, selection_sha256, *, allow_test_only=False, config=None):
    try:
        valid = ocr.validate_receipt(
            receipt, expected_capture=capture_value,
            expected_selection_sha256=selection_sha256, expected_config=config)
    except (ValueError, TypeError, KeyError) as exc:
        raise PhotoEvidenceError("Invalid OCR candidate evidence") from exc
    if not valid["test_only"] and config is not None:
        if (not config["enabled"] or config["qualification"] is None
                or any(row["status"] != "passed" for row in config["qualification"]["tests"])):
            _fail("Production review requires the explicitly qualified OCR selection")
    if valid["test_only"] and not allow_test_only:
        _fail("Synthetic receipts are not production recognition evidence")
    return valid


def recognize(ledger, item_id, *, allow_test_only=False, _policy_root=None, cancel=None):
    """Only explicit native operation; stale completion stores no receipt or review."""
    root = _source_root(allow_test_only=allow_test_only, _policy_root=_policy_root)
    with ledger._writer():
        config, selection, selection_bytes = _selection(root)
        if _policy_root is not None and (config["enabled"] or config["qualification"] is not None):
            _fail("Injected test roots must be disabled and unqualified before runner admission")
        captured = _capture_locked(ledger, item_id, ledger._load(), selection)
        budget = receipt_budget(ledger)
        if budget["count"] >= MAX_RECEIPTS or budget["bytes"] + MAX_RECEIPT > MAX_RECEIPT_TOTAL:
            _fail("No reserved receipt capacity; native operation refused")
    receipt = ocr.run_ocr(
        copy.deepcopy(config), copy.deepcopy(captured), store_root=ledger.root,
        selection_sha256=selection["selection_sha256"], selection_bytes=selection_bytes, cancel=cancel)
    valid = _validated(receipt, captured, selection["selection_sha256"],
                       allow_test_only=allow_test_only, config=config)
    if _policy_root is not None and not valid["test_only"]:
        _fail("Injected policy roots require synthetic receipts")
    with ledger._writer():
        _, current_selection, _ = _selection(root)
        state = ledger._load()
        current = _capture_locked(ledger, item_id, state, current_selection)
        if current_selection != selection or current != captured:
            _fail("OCR completion is stale; explicitly recapture and recognize")
        digest = _save_receipt_locked(ledger, valid)
    return preview(ledger, digest)


def _identity(match):
    return {
        "code": match["code"], "name": match["name"], "manufacturer": "NVIDIA",
        "subject": match["subject"], "source_url": match["source_url"],
        "source_revision": match["source_revision"], "source_locator": match["source_locator"],
        "document_sha256": None, "evidence": "local OCR public code checked by human",
        "hardware_revision": "unknown", "memory_gb": match["memory_gb"],
    }


def _summary(receipt, candidate_ids):
    candidate_ids = _candidate_ids(candidate_ids)
    found = ocr.candidates(receipt)
    # Every match and every unresolved code-like word remains in the decision.
    # Selecting one preferred view cannot erase evidence from another view.
    if set(candidate_ids) != {row["id"] for row in found["matches"]}:
        _fail("Review must account for the entire candidate match set")
    by_subject = {}
    for row in found["matches"]:
        by_subject.setdefault(row["subject"], {})[row["code"]] = _identity(row)
    identities = {subject: next(iter(values.values())) for subject, values in by_subject.items()
                  if len(values) == 1}
    conflicts = list(found["conflicts"])
    if any(len(values) > 1 for values in by_subject.values()):
        conflicts.append("Different public codes identify the same component kind")
    return {"identities": identities, "conflicts": sorted(set(conflicts)),
            "unresolved_model_code_count": found["unresolved_count"]}


def _candidate_ids(values):
    if type(values) is not list or len(values) > 128:
        _fail("Candidate selection count limit")
    for value in values:
        _id(value)
    if len(set(values)) != len(values):
        _fail("Duplicate candidate selection")
    return copy.deepcopy(values)


def preview(ledger, receipt_sha256):
    """Public code quotes and boxes only; unknown/raw words remain private."""
    with ledger._writer():
        state = ledger._load()
        receipt = _receipt(ledger, receipt_sha256)
        valid = _validated(receipt, receipt["capture"], receipt["selection_sha256"],
                           allow_test_only=True)
        bound = valid["capture"]
        if (bound["app_id"], bound["project_id"], bound["root_binding"]) != (
                APP_ID, ledger.project_id, ledger.binding):
            _fail("OCR receipt belongs to another app/project/store")
        item = next((row for row in state["items"] if row["item_id"] == bound["item_id"]), None)
        if item is None:
            _fail("OCR receipt item is absent")
        boxes = []
        images = {row["photo_sha256"]: row for row in valid["images"]}
        for match in valid["matches"]:
            word = images[match["photo_sha256"]]["words"][match["word_index"]]
            boxes.append({**copy.deepcopy(match), "quote": match["code"],
                          "bbox": copy.deepcopy(word["bbox"]),
                          "derived_sha256": images[match["photo_sha256"]]["derived_sha256"]})
        return {"receipt_sha256": receipt_sha256, "app_id": APP_ID,
                "project_id": ledger.project_id, "item_id": bound["item_id"],
                "expected_revision": bound["revision"], "test_only": valid["test_only"],
                "status": valid["status"], "matches": boxes,
                "candidate_ids": [row["id"] for row in valid["matches"]],
                "unresolved_model_code_count": valid["unresolved_count"],
                "conflicts": copy.deepcopy(valid["conflicts"]),
                "stale_ledger": (bound["revision"] != state["revision"]
                                 or bound["photos"] != item["photos"]
                                 or bound["state_sha256"] != _digest(_json_bytes(state))),
                "stale_policy": not _policy_matches_receipt(ledger, valid),
                "recognition": "synthetic-evidence-only" if valid["test_only"] else "local-ocr-candidate",
                "notice": "Check every public code quote against its image box; confidence is diagnostic. Inventory needs explicit approval."}


def _review_record(receipt_sha256, receipt, request):
    return {
        "format": REVIEW_FORMAT, "receipt_sha256": receipt_sha256,
        "capture_sha256": _digest(ocr.canonical_bytes(receipt["capture"])),
        "selection_sha256": receipt["selection_sha256"],
        "catalog_sha256": receipt["catalog_sha256"],
        "engine_sha256": _digest(ocr.canonical_bytes(receipt["engine"])),
        "candidate_ids": _candidate_ids(request["candidate_ids"]),
        "reviewer": _private_string(request["reviewer"]),
        "expected_subject": request["expected_subject"],
        "confirm_identity": request["confirm_identity"],
        "observed_words_confirmed": request["observed_words_confirmed"],
        "summary": _summary(receipt, request["candidate_ids"]),
        "test_only": receipt["test_only"],
    }


def approve(ledger, receipt_sha256, request, *, allow_test_only=False, _policy_root=None):
    """One lock rechecks actual policy, immutable originals, receipt and ledger state."""
    _keys(request, REQUEST_KEYS)
    _positive(request["expected_revision"], 128)
    _private_string(request["reviewer"])
    _choice(request["expected_subject"], {"module", "carrier", "developer_kit", "assembly", "unknown"})
    if type(request["confirm_identity"]) is not bool or request["observed_words_confirmed"] is not True:
        _fail("Explicit checked-box review of all public code quotes is required")
    _positive(request["quantity"], 10000)
    _choice(request["ownership"], {"unknown", "owned", "borrowed"})
    _scope(request["scope"], request["shared_with"])
    _candidate_ids(request["candidate_ids"])
    root = _source_root(allow_test_only=allow_test_only, _policy_root=_policy_root)
    with ledger._writer():
        config, selection, _ = _selection(root)
        state = ledger._load()
        receipt = _receipt(ledger, receipt_sha256)
        capture_value = receipt["capture"]
        if state["revision"] != request["expected_revision"]:
            _fail("Review revision changed; recapture explicitly")
        current = _capture_locked(ledger, capture_value["item_id"], state, selection)
        valid = _validated(receipt, current, selection["selection_sha256"],
                           allow_test_only=allow_test_only, config=config)
        if _policy_root is not None and not valid["test_only"]:
            _fail("Injected policy roots require synthetic receipts")
        if valid["status"] != "candidate":
            _fail("Unresolved or conflicting photo groups cannot enter OCR inventory review")
        item = next(row for row in state["items"] if row["item_id"] == current["item_id"])
        record = _review_record(receipt_sha256, valid, request)
        ledger._event(item, "ocr_review", request["reviewer"])
        item["ocr_review"] = record
        # Human observations are intentionally left untouched.
        item["quantity"], item["quantity_reviewer"] = request["quantity"], request["reviewer"]
        item["ownership"] = request["ownership"]
        item["scope"], item["shared_with"] = request["scope"], copy.deepcopy(request["shared_with"])
        if request["confirm_identity"] and evaluate(item)["status"] != "reviewed":
            _fail("Missing, partial, conflicting or ambiguous evidence cannot confirm identity")
        ledger._prepare_next(state)  # Quotas and strict serialization before publication.
        _, final_selection, _ = _selection(root)
        if final_selection != selection:
            _fail("Provider or OCR configuration changed during review")
        # _publish_locked rechecks the current revision; no nested writer lock.
        published = ledger._publish_locked(state)
        value = next(row for row in published["items"] if row["item_id"] == current["item_id"])
        return copy.deepcopy(ledger._evaluation(value))


def validate_stored_review(ledger, item, record, state_revision):
    """Pure receipt validation; installed OCR is not needed to read local history."""
    _keys(record, REVIEW_KEYS)
    if record["format"] != REVIEW_FORMAT:
        _fail("Unknown OCR review format")
    for field in ("receipt_sha256", "capture_sha256", "selection_sha256", "catalog_sha256", "engine_sha256"):
        _hash(record[field])
    _private_string(record["reviewer"])
    _choice(record["expected_subject"], {"module", "carrier", "developer_kit", "assembly", "unknown"})
    if (type(record["confirm_identity"]) is not bool
            or record["observed_words_confirmed"] is not True
            or type(record["test_only"]) is not bool):
        _fail("Invalid stored OCR review")
    _candidate_ids(record["candidate_ids"])
    receipt = _receipt(ledger, record["receipt_sha256"])
    valid = _validated(receipt, receipt["capture"], record["selection_sha256"],
                       allow_test_only=True)
    capture_value = valid["capture"]
    if (capture_value["app_id"], capture_value["project_id"], capture_value["root_binding"],
            capture_value["item_id"]) != (APP_ID, ledger.project_id, ledger.binding, item["item_id"]):
        _fail("Stored OCR review scope mismatch")
    if capture_value["photos"] != item["photos"] or not capture_value["revision"] < state_revision:
        _fail("Stored OCR review photo/revision mismatch")
    if (record["capture_sha256"] != _digest(ocr.canonical_bytes(capture_value))
            or record["catalog_sha256"] != valid["catalog_sha256"]
            or record["engine_sha256"] != _digest(ocr.canonical_bytes(valid["engine"]))
            or record["test_only"] != valid["test_only"]
            or _json_bytes(record["summary"]) != _json_bytes(_summary(valid, record["candidate_ids"]))):
        _fail("Stored OCR review summary/provenance changed")
    raw = _read(ledger.root / "versions" / (str(capture_value["revision"]) + ".json"), MAX_STATE)
    if _digest(raw) != capture_value["state_sha256"]:
        _fail("OCR captured ledger snapshot changed")
    state = _decode(raw)
    if (state.get("app_id"), state.get("project_id"), state.get("root_binding"),
            state.get("revision")) != (APP_ID, ledger.project_id, ledger.binding, capture_value["revision"]):
        _fail("OCR captured snapshot scope mismatch")
    if type(state.get("items")) is not list:
        _fail("OCR captured item list malformed")
    original = next((row for row in state["items"] if type(row) is dict and row.get("item_id") == item["item_id"]), None)
    if (original is None or original.get("photos") != capture_value["photos"]
            or _review_sha256(original) != capture_value["review_sha256"]):
        _fail("OCR captured human/review state changed")


def _policy_matches_receipt(ledger, receipt):
    if receipt["test_only"]:
        return False
    try:
        config, selected, _ = _selection(_source_root())
        if (not config["enabled"] or config["qualification"] is None
                or any(row["status"] != "passed" for row in config["qualification"]["tests"])):
            return False
        captured = receipt["capture"]
        return (selected["selection_sha256"] == receipt["selection_sha256"]
                and selected["provider_selection_sha256"] == captured["provider_selection_sha256"]
                and selected["ai_config_sha256"] == captured["ai_config_sha256"]
                and receipt["engine"] == ocr.engine_binding(config))
    except (OSError, ValueError, TypeError, KeyError):
        return False


def review_current(ledger, record):
    """Current qualification is a reviewed local claim, not authenticated proof."""
    return _policy_matches_receipt(ledger, _receipt(ledger, record["receipt_sha256"]))


def clear(ledger, item_id, *, expected_revision, reviewer, undo=False):
    """Clear active OCR choice; undo restores pre-approval quantity/sharing only."""
    _positive(expected_revision, 128)
    _private_string(reviewer)
    if type(undo) is not bool:
        _fail("Invalid undo choice")
    with ledger._writer():
        state = ledger._load()
        if state["revision"] != expected_revision:
            _fail("Clear/undo revision changed")
        item = next((row for row in state["items"] if row["item_id"] == _id(item_id)), None)
        if item is None or item.get("ocr_review") is None:
            _fail("No active OCR review to clear")
        prior = copy.deepcopy(item["history"][-1])
        if undo and prior["event"] != "ocr_review":
            _fail("Intervening item edits require clear rather than undo")
        ledger._event(item, "ocr_undo" if undo else "ocr_clear", reviewer)
        item["ocr_review"] = None
        if undo:
            item["quantity"], item["ownership"] = prior["prior_quantity"], prior["prior_ownership"]
            item["quantity_reviewer"] = prior["prior_quantity_reviewer"]
            item["scope"], item["shared_with"] = prior["prior_scope"], copy.deepcopy(prior["prior_shared_with"])
        ledger._publish_locked(state)
        return copy.deepcopy(evaluate(item))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, help="Private ignored photo_inventory directory")
    parser.add_argument("--project", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("recognize")
    command.add_argument("item")
    command = commands.add_parser("preview")
    command.add_argument("receipt_sha256")
    command = commands.add_parser("approve")
    command.add_argument("receipt_sha256")
    command.add_argument("request_json", help="Explicit scoped review request; no raw OCR input")
    for name in ("clear", "undo"):
        command = commands.add_parser(name)
        command.add_argument("item")
        command.add_argument("--expected-revision", required=True, type=int)
        command.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    from .photo_inventory import PhotoLedger
    ledger = PhotoLedger(args.store, args.project)
    if args.command == "recognize":
        value = recognize(ledger, args.item)
    elif args.command == "preview":
        value = preview(ledger, args.receipt_sha256)
    elif args.command == "approve":
        request = _decode(_read(args.request_json, MAX_STATE))
        value = approve(ledger, args.receipt_sha256, request)
    else:
        value = clear(ledger, args.item, expected_revision=args.expected_revision,
                      reviewer=args.reviewer, undo=args.command == "undo")
    print(_json_bytes(value).decode("utf-8"), end="")


if __name__ == "__main__":
    main()
